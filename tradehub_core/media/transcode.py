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
  2. `_run_transcode(file_url, name)` — worker'da çalışır. ffmpeg ile videoyu VP9/
     Opus WebM'e normalize eder, diskteki dosyanın YERİNE yazar (`file_url`
     sabit kalır — `Listing` gibi referanslar kırılmaz), durumu `ready`
     yapar.

Retry + dead-letter (TUR-296): hata `failed`'a DOĞRUDAN düşmez. Deneme sayısı
`th_media_transcode_attempts`'te tutulur; `jobs.MAX_ATTEMPTS` altındaysa yeni
bir deneme PLANLANIR (`th_media_transcode_next_at`) ve durum `processing` kalır
— kullanıcı ekranda "işleniyor" görmeye devam eder, geçici bir hata (disk dolu,
imajdan ffmpeg'in kısa süreliğine kalkması) kalıcı başarısızlık sayılmaz. Sayaç
dolunca dosya dead-letter'dır: durum `failed`, denetim kaydına `attempts` ile
düşer ve bir insan (satıcı `retry_video`, yönetici `retry_transcode`) elle
tetiklemeden sistem o dosyaya bir daha dokunmaz.

Retry KUYRUĞA ANINDA KONMAZ. İki nedenle:

  1. Backoff — disk dolduysa ya da ffmpeg yoksa saniyeler içinde düzelmez; üç
     hak saniyeler içinde yanar ve dosya boşuna dead-letter'a düşerdi.
  2. Sert kill — RQ zaman aşımı ya da OOM-killer worker'ı vurduğunda `except`
     bloğu HİÇ çalışmaz; sayaç artmaz, dosya sonsuza kadar `processing`de
     asılı kalırdı. Kuyruğa geri koyma işini süpürücüye devredince bu iki
     durum tek mekanizmayla çözülüyor.

`sweep_stuck_transcodes` (hooks.py, 5 dakikada bir) iki şeyi toplar: zamanı
gelmiş planlı denemeleri ve `jobs.STALE_AFTER_SECONDS` boyunca `processing`de
asılı kalmış (worker'ın bıraktığı) işleri.

Zaman aşımı merdiveni — her katman bir üsttekinden kısa, ki hata KENDİ
katmanında yakalansın ve bir üstteki sert kill devreye girmesin:

    ffprobe  20 sn  <  ffmpeg 1700 sn  <  kuyruk 1800 sn  <  kayıp eşiği 2700 sn

`ffmpeg`/`ffprobe` yoksa `_run_transcode`/`needs_transcode` `FileNotFoundError`
alır; ikisi de bunu güvenli tarafa düşerek yakalar (worker çökmez).
"""

from __future__ import annotations

import json
import os
import subprocess

import frappe
from frappe.utils import now_datetime

from tradehub_core.media import audit, jobs, ownership

VIDEO_STATUS_PROCESSING: str = "processing"
VIDEO_STATUS_READY: str = "ready"
VIDEO_STATUS_FAILED: str = "failed"

# Toplam deneme hakkı (ilk çalıştırma dahil). Politika `media/jobs.py`'de —
# medyadaki bütün kuyruk işleri aynı sayıyı kullanır. Bu ad geriye dönük
# uyumluluk için duruyor (testler ve `MEDYA-ISLEME-PIPELINE.md` ona atıf yapar).
MAX_TRANSCODE_ATTEMPTS: int = jobs.MAX_ATTEMPTS

# Kuyruk (RQ) zaman aşımı. ffmpeg'inkinden BÜYÜK olmalı: küçük olursa RQ, ffmpeg
# kendi kendine durup hatayı yazamadan süreci sert öldürür ve iş sayaca
# yazılmadan kaybolur.
QUEUE_TIMEOUT_SECONDS: int = 1800

# ffmpeg zaman aşımı — kuyruk timeout'undan biraz kısa tutuluyor ki ffmpeg kendi
# içinde durup hatayı yazsın, RQ'nun sert kill'i devreye girmesin.
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
	# Durum, filtre sözlüğüyle DEĞİL kayıt adıyla yazılıyor: içerik-hash'li
	# adlandırma (WP4) aynı içeriği aynı `file_url`'e eşliyor, yani tek adrese
	# birden çok `File` kaydı düşmesi artık olağan. Filtreyle yazmak başka
	# satıcının kaydına da durum basardı.
	if not needs_transcode(doc.get_full_path()):
		frappe.db.set_value(
			"File", name, "th_media_video_status", VIDEO_STATUS_READY,
			update_modified=False,
		)
		return

	frappe.db.set_value("File", name, "th_media_video_status", VIDEO_STATUS_PROCESSING)
	# Taze başlangıç: önceki (başarısız) turdan kalan sayaç yeni yüklemeye
	# sayılmasın — retry hakkı dosya başına değil, İŞ başına.
	_stamp_started(name, attempts=0)
	frappe.enqueue(
		"tradehub_core.media.transcode._run_transcode",
		queue="long",
		timeout=QUEUE_TIMEOUT_SECONDS,
		file_url=file_url,
		name=name,
		enqueue_after_commit=True,
	)


def _stamp_started(name: str, *, attempts: int | None = None) -> None:
	"""İşi "şu an çalışıyor" diye damgala — süpürücü buna bakar.

	`next_at` TEMİZLENİR: planlı deneme kuyruğa girdiği anda plan tüketilmiştir;
	kalsaydı süpürücü aynı dosyayı bir kez daha kuyruğa koyar ve iki worker aynı
	dosyaya yazardı.
	"""
	degerler: dict = {
		"th_media_transcode_next_at": None,
		"th_media_transcode_started_at": now_datetime(),
	}
	if attempts is not None:
		degerler["th_media_transcode_attempts"] = attempts
	frappe.db.set_value("File", name, degerler, update_modified=False)


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
		# Geri yükleme (`media.restore.apply`) dosyayı yedekteki hâliyle diske
		# yazıp kaydı sonra açıyor. Burada transcode'a girmek az önce geri
		# yüklenen dosyayı ezer — bayrak varsa dokunma.
		if getattr(getattr(doc, "flags", None), "th_skip_transcode", False):
			return

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


def _run_transcode(file_url: str, name: str | None = None) -> None:
	"""Worker'da çalışır — ffmpeg ile videoyu normalize eder.

	Başarısızlıkta asla yarım dosya diske YAZILMAZ: ffmpeg çıktısı geçici bir
	dosyaya yazılır, yalnız süreç başarıyla bitince kaynağın YERİNE
	`os.replace` ile taşınır (atomik) — yarıda kesilen bir transcode orijinal
	videoyu bozmaz.

	`name` ZORUNLU DEĞİL ama verilmesi gerekir: aynı `file_url`'e 39 kayda kadar
	işaret edebiliyor (bkz. `media/inventory.py`) ve adresten çözmek O ADRESTEKİ
	İLK kaydı buluyor. Süpürücü kayıt bazında çalıştığı için sayaç başka kayıtta
	artıyor, süpürücünün hedef kaydı ise sonsuza kadar `processing`de kalıyordu.
	Kayıt adı kuyruğa taşınınca durum makinesi hep aynı kayıt üzerinde yürüyor.
	Adres üstünden çözme yalnız geriye dönük uyumluluk için duruyor (deploy
	anında kuyrukta bekleyen eski işler `name` taşımıyor).
	"""
	if name and not frappe.db.exists("File", name):
		name = None
	name = name or frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		# Kuyruğa alındıktan sonra dosya bırakılmış/silinmiş olabilir — worker
		# bunun için patlamamalı.
		return

	# Damgayı worker BAŞLARKEN tazele: kuyrukta uzun bekleyen bir iş, gerçekte
	# yeni başlamışken "kayıp" ilan edilip ikinci kez kuyruğa girmesin.
	_stamp_started(name)
	frappe.db.commit()

	# AV kesişimi (TUR-125 × TUR-296). Tarama sistemi dosyayı fiziksel olarak
	# taşıyabiliyor; transcode bunu bilmezse ffmpeg "dosya yok" diye patlar ve
	# deneme hakkı BOŞUNA yanar — bekletme + yavaş tarama, sağlıklı bir videoyu
	# üç turda dead-letter'a düşürüyordu (kanca sırası: transcode kuyruğa girer,
	# av hemen ardından dosyayı bekletmeye alır).
	from tradehub_core.media import av

	try:
		if av.in_quarantine(file_url):
			# Zararlı bulunmuş dosya bir daha kuyruğa GİRMEZ: retry onu geri
			# getirmez, `processing`de bırakmak kullanıcıya sonsuz spinner
			# gösterir. Dead-letter, sebep denetimde.
			_dead_letter(
				name,
				file_url,
				int(frappe.db.get_value("File", name, "th_media_transcode_attempts") or 0),
				sebep="Quarantined",
				detay="dosya karantinada; transcode karantina kalkmadan yapılamaz",
			)
			return
		if av.in_hold(file_url):
			# Tarama sürüyor — bu bir BAŞARISIZLIK DEĞİL, erken gelmişiz.
			# Sayaç ARTMAZ; deneme yalnız ertelenir ve işi süpürücü yeniden
			# kuyruğa koyar. Bekletme sonsuz değil: tarama temiz/failed'da
			# dosyayı geri koyar, infected'da yukarıdaki dala düşülür.
			frappe.db.set_value(
				"File",
				name,
				"th_media_transcode_next_at",
				jobs.next_attempt_at(1),
				update_modified=False,
			)
			frappe.db.commit()
			return
	except Exception:
		# Tarama durumu okunamadı: transcode'u durdurma sebebi değil — dosya
		# canlı ağaçtaysa normal yol zaten çalışır.
		frappe.log_error(
			title="transcode: av durumu okunamadi", message=frappe.get_traceback()
		)

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
		_on_transcode_failure(name, file_url, exc)


def _on_transcode_failure(name: str, file_url: str, exc: Exception) -> None:
	"""Başarısız denemeyi sayar; hakkı varsa yenisini planlar, yoksa
	dead-letter'a düşürür.

	Retry'da durum `processing` KALIR: kullanıcıya "başarısız" gösterip iki
	dakika sonra kendiliğinden "hazır"a dönmek güven bozar — başarısızlık ancak
	sistem gerçekten pes ettiğinde gösterilir.
	"""
	attempts = (
		frappe.db.get_value("File", name, "th_media_transcode_attempts") or 0
	) + 1
	frappe.db.set_value(
		"File", name, "th_media_transcode_attempts", attempts, update_modified=False
	)

	if attempts < MAX_TRANSCODE_ATTEMPTS:
		_schedule_retry(name, file_url, attempts, sebep=type(exc).__name__, detay=str(exc))
		return

	_dead_letter(name, file_url, attempts, sebep=type(exc).__name__, detay=str(exc))


def _schedule_retry(name: str, file_url: str, attempts: int, *, sebep: str, detay: str) -> None:
	"""Yeni denemeyi PLANLA — kuyruğa koymaz, damgayı yazar.

	Kuyruğa anında koymak backoff'u anlamsız kılardı: `frappe.enqueue`'un
	gecikme parametresi yok (v15), o yüzden bekleme damga üzerinden yürütülüyor
	ve işi süpürücü alıyor.
	"""
	frappe.db.set_value(
		"File",
		name,
		"th_media_transcode_next_at",
		jobs.next_attempt_at(attempts),
		update_modified=False,
	)
	frappe.db.commit()
	frappe.log_error(
		title="Video transcode başarısız — yeniden denenecek",
		message=(
			f"{file_url} (deneme {attempts}/{MAX_TRANSCODE_ATTEMPTS}, "
			f"{jobs.backoff_seconds(attempts)} sn sonra): {detay}"
		),
	)
	# Denetimde retry ayrı bir olaydır: "3 deneme yapıldı" bilgisi yalnız
	# dead-letter kaydından çıkarılamaz.
	audit.log_media_event(
		action=audit.ACTION_OPTIMIZE,
		file_url=file_url,
		allowed=False,
		reason=f"video_transcode_retry:{sebep}",
		context={
			"kind": "video_transcode",
			"attempt": attempts,
			"retry_in": jobs.backoff_seconds(attempts),
		},
	)


def _dead_letter(name: str, file_url: str, attempts: int, *, sebep: str, detay: str) -> None:
	"""Hak bitti. Bundan sonra bu dosyaya yalnız insan eliyle dokunulur.

	`next_at` temizlenir: dead-letter'daki dosya süpürücünün kapsamından
	tamamen çıkmalı, aksi halde plan damgası kalır ve iş sessizce yeniden
	kuyruğa girerdi.
	"""
	frappe.db.set_value(
		"File",
		name,
		{
			"th_media_video_status": VIDEO_STATUS_FAILED,
			"th_media_transcode_next_at": None,
		},
		update_modified=False,
	)
	frappe.db.commit()
	frappe.log_error(title="Video transcode başarısız", message=f"{file_url}: {detay}")
	# Fix round 1, Bulgu 2: yalnız Error Log yeterli değil — transcode
	# başarısızlığı medya denetim ekranında (ADL) da görünmeli, başarı
	# dalıyla AYNI desen.
	audit.log_media_event(
		action=audit.ACTION_OPTIMIZE,
		file_url=file_url,
		allowed=False,
		reason=f"video_transcode_failed:{sebep}",
		context={"kind": "video_transcode", "attempts": attempts},
	)


def retry_failed(file_url: str) -> dict:
	"""Dead-letter'daki (`failed`) videoyu insan eliyle yeniden kuyruğa koy.

	Yalnız `failed` durumundaki dosyayı kabul eder: `processing` zaten kuyrukta,
	`ready`'yi yeniden işlemek kullanıcının onayladığı çıktıyı ezer, boş durum
	video değildir. Yetki kontrolü BURADA YAPILMAZ — çağıran API katmanı yapar
	(satıcı: sahiplik, yönetici: rol); bu modül HTTP'den doğrudan erişilemez.
	"""
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		frappe.throw(frappe._("Dosya bulunamadı: {0}").format(file_url))

	durum = frappe.db.get_value("File", name, "th_media_video_status")
	if durum != VIDEO_STATUS_FAILED:
		frappe.throw(
			frappe._("Yalnız başarısız videolar yeniden denenebilir (durum: {0}).").format(
				durum or "-"
			)
		)

	# Karantinadaki video yeniden kuyruğa KONMAZ: iş yine "dosya yok" ile düşer
	# ve düğme çalışıyormuş gibi görünürdü. Kullanıcı önce karantinayı
	# çözmeli — mesaj bunu açıkça söylüyor (TUR-125).
	from tradehub_core.media import av

	if av.in_quarantine(file_url):
		frappe.throw(
			frappe._("Bu dosya karantinada. Önce güvenlik ekranından çözülmesi gerekiyor.")
		)

	_stamp_started(name, attempts=0)
	frappe.db.set_value("File", name, "th_media_video_status", VIDEO_STATUS_PROCESSING)
	frappe.enqueue(
		"tradehub_core.media.transcode._run_transcode",
		queue="long",
		timeout=QUEUE_TIMEOUT_SECONDS,
		file_url=file_url,
		name=name,
		enqueue_after_commit=True,
	)
	return {"file_url": file_url, "status": VIDEO_STATUS_PROCESSING}


def sweep_stuck_transcodes(limit: int = 200) -> dict:
	"""Zamanlanmış görev — planlı denemeleri ve bırakılmış işleri toplar.

	İki ayrı kusuru TEK mekanizmayla kapatır:

	  1. **Planlı retry** (`next_at` dolu, zamanı gelmiş): backoff süresi
	     dolduğu için iş kuyruğa konur.
	  2. **Bırakılmış iş** (`next_at` boş, `started_at` çok eski): RQ zaman
	     aşımı ya da OOM-killer worker'ı vurmuş; `except` bloğu hiç çalışmadığı
	     için sayaç artmamış ve dosya `processing`de asılı kalmış. Burada
	     başarısızlık sayılır — hakkı varsa yeni deneme planlanır, yoksa
	     dead-letter.

	`limit`: tek turda dokunulacak azami kayıt. Bir kuyruk kazası binlerce
	dosyayı aynı anda takılı bırakabilir; hepsini tek turda kuyruğa boşaltmak
	süpürücüyü kendisi bir olay hâline getirirdi.
	"""
	kayitlar = frappe.get_all(
		# Sistem işi: süpürücünün oturumu yok, kullanıcı yetkisi aranmaz.
		"File",
		filters={"th_media_video_status": VIDEO_STATUS_PROCESSING},
		fields=[
			"name",
			"file_url",
			"th_media_transcode_attempts",
			"th_media_transcode_next_at",
			"th_media_transcode_started_at",
		],
		limit=limit,
		order_by="modified asc",
	)

	kuyruga_konan = 0
	dusen = 0
	for k in kayitlar:
		if k.th_media_transcode_next_at:
			if not jobs.is_due(k.th_media_transcode_next_at):
				continue
			_stamp_started(k.name)
			frappe.db.commit()
			frappe.enqueue(
				"tradehub_core.media.transcode._run_transcode",
				queue="long",
				timeout=QUEUE_TIMEOUT_SECONDS,
				file_url=k.file_url,
				name=k.name,
			)
			kuyruga_konan += 1
			continue

		if not jobs.is_stale(k.th_media_transcode_started_at):
			continue

		# Bırakılmış iş: sayacı ilerlet, sonra normal başarısızlık yolundan geç.
		attempts = int(k.th_media_transcode_attempts or 0) + 1
		frappe.db.set_value(
			"File", k.name, "th_media_transcode_attempts", attempts, update_modified=False
		)
		detay = "worker işi bıraktı (kuyruk zaman aşımı ya da süreç öldürüldü)"
		if attempts < MAX_TRANSCODE_ATTEMPTS:
			_schedule_retry(k.name, k.file_url, attempts, sebep="Abandoned", detay=detay)
		else:
			_dead_letter(k.name, k.file_url, attempts, sebep="Abandoned", detay=detay)
		dusen += 1

	if kuyruga_konan or dusen:
		frappe.logger("media").info(
			f"transcode sweep: requeued={kuyruga_konan} abandoned={dusen} "
			f"scanned={len(kayitlar)}"
		)
	return {"scanned": len(kayitlar), "requeued": kuyruga_konan, "abandoned": dusen}
