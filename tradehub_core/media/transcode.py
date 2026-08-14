"""Video async transcode (VP9/Opus, WebM) — RQ `long` kuyruğu (TUR-296/297, WP5).

Görsel yolunun aksine (`engine.to_webp` — istek içinde senkron), video
transcode dakikalar sürebilir. `upload_media` içinde senkron çalıştırmak
istek thread'ini/HTTP timeout'unu patlatır (checklists.md §2, kural 9) —
bu yüzden `frappe.enqueue(..., queue="long")`.

WP5 — KOŞULLU + GLOBAL: Client (tarayıcı, mediabunny) çoğu videoyu zaten
sıkıştırıyor; sunucunun HER videoyu tekrar transcode etmesi 100'lerce eşzamanlı
yüklemede kuyruğu boğar. Bu yüzden sunucu SADECE client'ın sıkıştıramadığı
(hâlâ büyük/yüksek bitrate'li) videoları işler — `needs_transcode` bu kararı
verir. Ayrıca güvenlik ağı yalnız satıcı medya kütüphanesiyle (`upload_media`)
sınırlı değil: ürün formunun genel `upload_file` yolu da `maybe_transcode_on_insert`
GLOBAL `File.after_insert` kancasıyla aynı ağa girer (chat/KYB/private videolar
muaf — bkz. o fonksiyonun docstring'i).

Akış:
  1. `enqueue_transcode(file_url)` — istek thread'inde (ya da `after_insert`
     kancasında) çalışır. Zaten `processing`/`ready` ise idempotent no-op
     (aynı dosya iki ayrı yoldan — `upload_media` VE global kanca — tetiklenirse
     ikinci kez kuyruğa girmesin). `needs_transcode` False dönerse (video zaten
     küçük/sıkışmış) kuyruğa HİÇ girmez, durumu direkt `ready` yapar. True
     dönerse durumu `processing` yapar (kullanıcı ekranda "işleniyor" görsün)
     ve gerçek işi `_run_transcode`'a devreder.
  2. `_run_transcode(file_url)` — worker'da çalışır. ffmpeg ile videoyu VP9/
     Opus WebM'e normalize eder, diskteki dosyanın YERİNE yazar (`file_url`
     sabit kalır — `Listing` gibi referanslar kırılmaz), durumu `ready`
     yapar. Hata olursa `failed` + `frappe.log_error`.

`ffmpeg`/`ffprobe` yoksa `_run_transcode`/`needs_transcode` `FileNotFoundError`
alır; ikisi de bunu güvenli tarafa düşerek yakalar (worker çökmez).
"""

from __future__ import annotations

import json
import os
import subprocess

import frappe

from tradehub_core.media import audit, ownership

VIDEO_STATUS_PROCESSING: str = "processing"
VIDEO_STATUS_READY: str = "ready"
VIDEO_STATUS_FAILED: str = "failed"

# ffmpeg zaman aşımı — kuyruk timeout'undan (1800 sn) biraz kısa tutuluyor ki
# ffmpeg kendi içinde durup "failed" yazsın, RQ'nun sert kill'i devreye girmesin.
_FFMPEG_TIMEOUT_SECONDS: int = 1700

# ffprobe çok daha hızlı olmalı — yalnız metadata okuyor, transcode yapmıyor.
_FFPROBE_TIMEOUT_SECONDS: int = 20

# Client (mediabunny) genelde 1280px'e/makul bitrate'e sıkıştırıyor. Bu
# eşiklerin ÜSTÜNDEKİ video "client sıkıştıramamış" sayılır → sunucu işler.
# `_run_transcode`'daki `scale=min(1280,iw)` hedefiyle TUTARLI tutuluyor —
# aksi halde sunucu, kendi hedef çözünürlüğünün altındaki videoyu bile
# transcode kuyruğuna sokardı.
NEEDS_TRANSCODE_MAX_WIDTH: int = 1280
NEEDS_TRANSCODE_MAX_BITRATE: int = 2_500_000  # 2.5 Mbps

# Global güvenlik ağının kapsadığı video uzantıları — `api/seller_media.py`
# `VIDEO_EXTENSIONS` ile TUTARLI (orası upload zamanı izin listesi, burası
# insert-sonrası tarama; iki liste ayrışırsa bir tür ya kabul edilip hiç
# transcode edilmez ya da tersi).
VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".webm", ".mov", ".m4v"})


def needs_transcode(file_path_or_url: str) -> bool:
	"""Video zaten küçük/sıkışmışsa transcode'u ATLA, aksi halde işaretle.

	`ffprobe` ile gerçek video parametreleri (genişlik + bitrate) okunur:

	  - genişlik > 1280 VEYA bitrate > 2.5 Mbps  → True  (client sıkıştıramamış,
	    sunucu transcode etmeli)
	  - ikisi de eşiğin altında                  → False (zaten küçük/sıkışmış,
	    sunucu tekrar iş yapmaz)

	`ffprobe` çalışamazsa (yok, dosya bozuk, format tanınmıyor, video stream'i
	yok) GÜVENLİ TARAFA düşülür: True — "emin değilsek transcode et", "emin
	değilsek atla" değil. Her durumda `frappe.log_error` ile loglanır ki
	ffprobe'un sistemli biçimde başarısız olması (ör. imajdan kalktı) sessizce
	geçmesin.
	"""
	cmd = [
		"ffprobe", "-v", "error",
		"-select_streams", "v:0",
		"-show_entries", "stream=width,bit_rate:format=bit_rate",
		"-of", "json",
		file_path_or_url,
	]
	try:
		sonuc = subprocess.run(
			cmd, check=True, capture_output=True, timeout=_FFPROBE_TIMEOUT_SECONDS
		)
		veri = json.loads(sonuc.stdout)
		streams = veri.get("streams") or []
		if not streams:
			raise ValueError("ffprobe video stream döndürmedi")
	except Exception as exc:
		frappe.log_error(
			title="needs_transcode: ffprobe okunamadı",
			message=f"{file_path_or_url}: {exc}",
		)
		return True

	stream = streams[0]
	genislik = int(stream.get("width") or 0)
	bitrate_ham = stream.get("bit_rate") or (veri.get("format") or {}).get("bit_rate") or 0
	try:
		bitrate = int(bitrate_ham)
	except (TypeError, ValueError):
		bitrate = 0

	return genislik > NEEDS_TRANSCODE_MAX_WIDTH or bitrate > NEEDS_TRANSCODE_MAX_BITRATE


def enqueue_transcode(file_url: str) -> None:
	"""Video yüklemesi sonrası transcode'u KOŞULLU olarak kuyruğa al.

	İdempotent: dosyanın durumu zaten `processing`/`ready` ise hiçbir şey
	yapmaz. Bu, aynı dosyanın iki ayrı yoldan (`upload_media`'nın kendi
	çağrısı VE `maybe_transcode_on_insert` global kancası) tetiklenmesi
	durumunda ikinci kez kuyruğa girmesini önler.

	`needs_transcode` False dönerse (video zaten küçük/sıkışmış — client
	tarafından mediabunny ile işlenmiş) kuyruğa HİÇ girmez, durumu direkt
	`ready` yapar. True dönerse `th_media_video_status`'u hemen `processing`
	yapar — panel bu alanı okuyup "işleniyor" rozetini gösterebilsin.
	`enqueue_after_commit=True`: `upload_media` içinde `File.insert()` henüz
	commit edilmemişken worker tetiklenirse dosyayı bulamaz (race).
	"""
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		# Dosya kaydı yoksa (silinmiş/bulunamıyor) yapacak bir şey yok.
		return

	mevcut_durum = frappe.db.get_value("File", name, "th_media_video_status")
	if mevcut_durum in (VIDEO_STATUS_PROCESSING, VIDEO_STATUS_READY):
		return

	doc = frappe.get_doc("File", name)
	if not needs_transcode(doc.get_full_path()):
		frappe.db.set_value(
			"File", {"file_url": file_url}, "th_media_video_status", VIDEO_STATUS_READY,
			update_modified=False,
		)
		return

	frappe.db.set_value(
		"File", {"file_url": file_url}, "th_media_video_status", VIDEO_STATUS_PROCESSING
	)
	frappe.enqueue(
		"tradehub_core.media.transcode._run_transcode",
		queue="long",
		timeout=1800,
		file_url=file_url,
		enqueue_after_commit=True,
	)


def maybe_transcode_on_insert(doc, method: str | None = None) -> None:
	"""`File.after_insert` GLOBAL kancası (WP5) — yalnız satıcı medya kütüphanesi
	(`upload_media`) değil, ürün formunun genel `upload_file` yolu da bu
	güvenlik ağına girsin diye (TUR-296/297 takip).

	Kapsam BİLEREK dar tutuluyor:

	  - Yalnız video uzantıları (`VIDEO_EXTENSIONS`).
	  - Yalnız `is_private=0` — chat ekleri, KYB/KYC belgeleri PRIVATE
	    yükleniyor, bu yüzden zaten muaf.
	  - Yalnız (a) sahibi bir satıcıya çözülebilen (`ownership.store_of`)
	    VEYA (b) `Listing`e eklenmiş dosyalar — platform/yönetim yüklemeleri
	    ve seller olmayan kullanıcı yüklemeleri kapsam dışı.

	`enqueue_transcode` kendi içinde idempotent (durum zaten `processing`/
	`ready` ise no-op) — bu kanca `upload_media`'dan ÖNCE (aynı `File.insert()`
	çağrısı içinde, `after_insert` olarak) çalışsa bile, `upload_media`'nın
	kendi ardışık çağrısı ikinci kez kuyruğa girmez.

	Best-effort: burada patlamak dosya yüklemesini asla engellememeli
	(`states.on_file_insert` ile aynı desen).
	"""
	try:
		if doc.get("is_folder") or doc.get("is_private"):
			return

		uzanti = os.path.splitext(doc.get("file_name") or "")[1].lower()
		if uzanti not in VIDEO_EXTENSIONS:
			return

		satici_mi = bool(ownership.store_of(doc.get("owner")))
		listing_eki_mi = doc.get("attached_to_doctype") == "Listing"
		if not (satici_mi or listing_eki_mi):
			return

		enqueue_transcode(doc.get("file_url"))
	except Exception:
		frappe.log_error(
			title="media.transcode maybe_transcode_on_insert failed",
			message=frappe.get_traceback(),
		)


def _run_transcode(file_url: str) -> None:
	"""Worker'da çalışır — ffmpeg ile videoyu normalize eder.

	Başarısızlıkta asla yarım dosya diske YAZILMAZ: ffmpeg çıktısı geçici bir
	dosyaya yazılır, yalnız süreç başarıyla bitince kaynağın YERİNE
	`os.replace` ile taşınır (atomik) — yarıda kesilen bir transcode orijinal
	videoyu bozmaz.
	"""
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		# Kuyruğa alındıktan sonra dosya bırakılmış/silinmiş olabilir — worker
		# bunun için patlamamalı.
		return

	doc = frappe.get_doc("File", name)
	src_path = doc.get_full_path()
	dst_path = f"{src_path}.transcoding.webm"

	# `nice -n 10`: transcode CPU-yoğun; worker'ın diğer kuyruklarını
	# (default/short — sipariş, ödeme gibi kullanıcı-görünür işler) aç
	# bırakmak için düşük öncelikte çalıştırılır.
	cmd = [
		"nice", "-n", "10",
		"ffmpeg", "-y",
		"-i", src_path,
		# `min(1280,iw)` ifadesindeki virgül ffmpeg filtergraph'ta zincir ayracıdır;
		# tek tırnakla quote edilmezse "scale" filtresi "min(1280" olarak kesilip
		# patlar (gerçek ffmpeg ile doğrulandı — mock testlerde görülmüyordu).
		"-vf", "scale='min(1280,iw)':-2",
		"-c:v", "libvpx-vp9",
		"-b:v", "0",
		"-crf", "32",
		"-c:a", "libopus",
		dst_path,
	]

	try:
		subprocess.run(cmd, check=True, capture_output=True, timeout=_FFMPEG_TIMEOUT_SECONDS)
		os.replace(dst_path, src_path)
		frappe.db.set_value("File", name, "th_media_video_status", VIDEO_STATUS_READY, update_modified=False)
		frappe.db.commit()
		audit.log_media_event(
			action=audit.ACTION_OPTIMIZE, file_url=file_url, context={"kind": "video_transcode"}
		)
	except Exception as exc:  # noqa: BLE001 — worker hiçbir koşulda kuyruğu patlatmamalı
		try:
			if os.path.exists(dst_path):
				os.remove(dst_path)
		except OSError:
			pass
		frappe.db.set_value("File", name, "th_media_video_status", VIDEO_STATUS_FAILED, update_modified=False)
		frappe.db.commit()
		frappe.log_error(title="Video transcode başarısız", message=f"{file_url}: {exc}")
		# Fix round 1, Bulgu 2: yalnız Error Log yeterli değil — transcode
		# başarısızlığı medya denetim ekranında (ADL) da görünmeli, başarı
		# dalıyla (yukarıda) AYNI desen.
		audit.log_media_event(
			action=audit.ACTION_OPTIMIZE,
			file_url=file_url,
			allowed=False,
			reason=f"video_transcode_failed:{type(exc).__name__}",
			context={"kind": "video_transcode"},
		)
