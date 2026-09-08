"""Ses dosyası metadata çıkarımı — başlık, sanatçı, süre, kapak (MOGEM-620 §15).

MOGEM-620 kabul kriteri 18 ses dosyaları için "türüne uygun metadata" istiyor.
Denetimde (4 Eyl 2026) doküman tarafı (`doc_meta.py`) vardı, ses tarafı YOKTU.

NEDEN ffprobe/ffmpeg, NEDEN yeni bir kütüphane DEĞİL
----------------------------------------------------
`mutagen` gibi bir bağımlılık eklemek ID3/MP4/Vorbis etiketlerinin her birini
ayrı ayrı çözmek demekti. ffprobe zaten kurulu (`video_poster.probe_duration`
ve `pipeline/video/probe.py` onu kullanıyor) ve kapsayıcıdan bağımsız TEK bir
`format.tags` sözlüğü döndürüyor — MP3 `TIT2` ile M4A `©nam` aynı `title`
anahtarına iniyor. Yeni bağımsızlık yüzeyi açmamak bilinçli.

KAPAK: kapsayıcının GÖMÜLÜ görselinden gelir (`disposition.attached_pic`).
Üretilmez, kesilmez, uydurulmaz — ses dosyasında video posteri gibi "temsili
kare" kavramı yok; ya gömülü kapak vardır ya yoktur.

HATA SÖZLEŞMESİ: `video_poster` ve `doc_meta` ile AYNI — hiçbir hata
kullanıcının yüklemesini ya da kuyruk işini düşürmez. Her hata log + boş sonuç.

ANTİ-AÇLIK: başarısız çıkarımda `th_media_duration` -1 yazılır ki
`backfill_pending` aynı okunamayan dosyayı her turda yeniden seçmesin
(`doc_meta.apply`'ın `page_count = -1` damgasıyla AYNI desen). Negatif süre
dışarıya SIZMAZ: `seo._birlestir` `max(0, ...)` nöbetçisiyle durdurur.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import frappe

from tradehub_core.media import upload_policy

#: Çıkarımın aday gördüğü uzantılar — TEK KAYNAK `upload_policy`.
#:
#: `video_poster.VIDEO_UZANTILAR`/`doc_meta.DOC_UZANTILAR` emsalinden bilerek
#: ayrıldık: onlar kendi düz listesini tutuyor ve `.pptx` o yüzden yıllarca
#: yüklenemedi (motorda destekli, haritada yok). Aynı sapma seste olmasın.
AUDIO_UZANTILAR: tuple[str, ...] = upload_policy.AUDIO_EXTENSIONS

#: ffprobe/ffmpeg duvar saati. Ses dosyası videodan küçük ama bir podcast
#: bölümü 3 saat olabilir; `video_poster.probe_duration`'ın 30 sn'si etiket
#: okumak için fazlasıyla yeterli (etiketler dosyanın başında/sonunda).
FFPROBE_TIMEOUT: int = 30
FFMPEG_TIMEOUT: int = 60

#: Gömülü kapak tavanı. Bunun üstündeki görsel `File` olarak saklanmaz —
#: bazı albüm kapakları 8 MB'lık PNG oluyor ve kapak SEO'da yalnız
#: `thumbnailUrl` olarak geçiyor, kaynak çözünürlüğünde tutmanın karşılığı yok.
KAPAK_TAVAN_BAYT: int = 2 * 1024 * 1024

#: ffprobe etiket adı → çıktı anahtarı. Kapsayıcı farkını ffprobe zaten
#: siliyor; burada yalnız büyük/küçük harf ve yaygın eşanlamlılar var.
_ETIKET_HARITA: dict[str, str] = {
	"title": "title",
	"artist": "artist",
	"album_artist": "artist",
	"performer": "artist",
	"language": "language",
}


def _bos(reason: str) -> dict:
	return {"ok": False, "reason": reason, "title": "", "artist": "", "duration": 0.0, "language": ""}


def extract(file_url: str) -> dict:
	"""Tek ffprobe koşumunda etiket + süre. İstisna ATMAZ.

	Dönen sözlük `doc_meta.extract` ile aynı sözleşmede: `ok` bayrağı, hata
	durumunda `reason`, başarıda alanlar. Çağıran `ok`'a bakar.
	"""
	yol = _yerel_yol(file_url)
	if not yol:
		return _bos("dosya bulunamadı")
	if Path(yol).suffix.lower() not in AUDIO_UZANTILAR:
		return _bos("desteklenmeyen uzantı")

	try:
		ham = subprocess.run(
			[
				"ffprobe",
				"-v",
				"error",
				"-show_entries",
				"format=duration:format_tags:stream_tags",
				"-of",
				"json",
				yol,
			],
			capture_output=True,
			text=True,
			timeout=FFPROBE_TIMEOUT,
			check=True,
		)
		veri = json.loads(ham.stdout or "{}")
	except Exception:
		frappe.log_error(title="audio_meta.extract", message=frappe.get_traceback())
		return _bos("ffprobe okunamadı")

	bicim = veri.get("format") or {}
	etiketler = {str(k).lower(): v for k, v in (bicim.get("tags") or {}).items()}

	sonuc = {"ok": True, "reason": "", "title": "", "artist": "", "language": ""}
	for ham_ad, hedef in _ETIKET_HARITA.items():
		# `album_artist`/`performer` yalnız `artist` BOŞSA devreye girer —
		# harita sırası bilinçli, ilk dolu olan kazanır.
		if sonuc.get(hedef):
			continue
		deger = str(etiketler.get(ham_ad) or "").strip()
		if deger:
			sonuc[hedef] = deger

	try:
		sonuc["duration"] = float(bicim.get("duration") or 0)
	except (TypeError, ValueError):
		sonuc["duration"] = 0.0

	return sonuc


def extract_cover(file_url: str) -> bytes | None:
	"""Kapsayıcıya gömülü kapak görselini ham bayt olarak döndür; yoksa None.

	`-map 0:v` gömülü görsel akışını seçer (`attached_pic`); ses-yalnız bir
	dosyada video akışı yoksa ffmpeg hata verir ve None döneriz — bu OLAĞAN
	durum, log basılmaz. Yalnız beklenmedik hatalar loglanır.
	"""
	yol = _yerel_yol(file_url)
	if not yol:
		return None

	with tempfile.NamedTemporaryFile(suffix=".jpg", delete=True) as tmp:
		hedef = tmp.name
		try:
			subprocess.run(
				["ffmpeg", "-y", "-i", yol, "-map", "0:v", "-map", "-0:V", "-c", "copy", hedef],
				capture_output=True,
				timeout=FFMPEG_TIMEOUT,
				check=True,
			)
		except subprocess.CalledProcessError:
			# Gömülü kapak yok — beklenen durum, sessiz geç.
			return None
		except Exception:
			frappe.log_error(title="audio_meta.extract_cover", message=frappe.get_traceback())
			return None

		veri = Path(hedef).read_bytes()

	if not veri or len(veri) > KAPAK_TAVAN_BAYT:
		return None
	return veri


def apply(file_url: str) -> bool:
	"""Çıkarımı `file_url`'e işaret eden TÜM `File` kardeşlerine yaz.

	`doc_meta.apply` ile birebir aynı desen: kardeş kayıtların hepsi yazılır
	(aynı adrese 39 kayda kadar işaret edilebiliyor), dolu alanlar EZİLMEZ,
	hata yutulur.
	"""
	try:
		adlar = frappe.get_all("File", filters={"file_url": file_url}, pluck="name")
		if not adlar:
			return False

		sonuc = extract(file_url)
		if not sonuc.get("ok"):
			frappe.db.set_value(
				"File", {"name": ["in", adlar]}, "th_media_duration", -1, update_modified=False
			)
			return False

		sure = float(sonuc.get("duration") or 0)
		if sure > 0:
			frappe.db.set_value(
				"File", {"name": ["in", adlar]}, "th_media_duration", sure, update_modified=False
			)

		# Başlık ve sanatçı yalnız BOŞ olan kardeşlere yazılır — elle girilmiş
		# değeri makine çıkarımı asla ezmez (`doc_meta.apply` ile aynı kural).
		for alan, deger in (
			("th_media_title", (sonuc.get("title") or "").strip()),
			("th_media_artist", (sonuc.get("artist") or "").strip()),
		):
			if not deger or not frappe.db.has_column("File", alan):
				continue
			bos_olanlar = frappe.get_all(
				"File", filters={"name": ["in", adlar], alan: ["is", "not set"]}, pluck="name"
			)
			if bos_olanlar:
				frappe.db.set_value(
					"File", {"name": ["in", bos_olanlar]}, alan, deger, update_modified=False
				)

		_kapagi_yaz(file_url, adlar)
		return True
	except Exception:
		frappe.log_error(title="audio_meta.apply", message=frappe.get_traceback())
		return False


def _kapagi_yaz(file_url: str, adlar: list[str]) -> None:
	"""Gömülü kapağı `File` olarak kaydedip `th_media_poster_url`'e bağla.

	Poster'ı ZATEN OLAN dosyaya dokunulmaz: kapak bir kez çıkarılır, sonraki
	turlar aynı görseli tekrar tekrar `File` olarak yazmaz (backfill her
	çağrıldığında depo şişerdi).
	"""
	mevcut = frappe.db.get_value("File", adlar[0], "th_media_poster_url")
	if mevcut:
		return

	veri = extract_cover(file_url)
	if not veri:
		return

	kapak = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{Path(file_url).stem}-kapak.jpg",
			"is_private": 0,
			"content": veri,
			"decode": False,
		}
	)
	kapak.flags.ignore_permissions = True
	kapak.insert()
	frappe.db.set_value(
		"File",
		{"name": ["in", adlar]},
		"th_media_poster_url",
		kapak.file_url,
		update_modified=False,
	)


def backfill_pending(limit: int = 50) -> int:
	"""Süresi hiç okunmamış ses dosyalarını işle; işlenen sayısını döndür.

	`video_poster.backfill_pending` ile aynı sözleşme. `duration = 0` seçer —
	anti-açlık damgası (-1) bu koşula girmediği için okunamayan dosya bir
	daha seçilmez.

	HAM SQL DENENDİ VE BIRAKILDI: `LIKE '%.mp3'` deseni pymysql'in `%`
	biçimlendirmesiyle çakışıyor ("unsupported format character 'm'") ve
	`%%` ile kaçırmak uzantı listesini SQL metnine gömmek demekti. `or_filters`
	hem bu tuzağı hem de f-string SQL yasağını (kural 11) birden çözüyor.
	"""
	if not frappe.db.has_column("File", "th_media_duration"):
		return 0

	satirlar = frappe.get_all(
		"File",
		filters={"th_media_duration": 0, "file_url": ["!=", ""]},
		or_filters=[["file_url", "like", f"%{u}"] for u in AUDIO_UZANTILAR],
		pluck="file_url",
		limit=int(limit),
	)

	islenen = 0
	for url in dict.fromkeys(satirlar or []):
		if apply(url):
			islenen += 1
	return islenen


def _yerel_yol(file_url: str) -> str:
	"""`/files/ab/hash.mp3` → diskteki mutlak yol. Bulunamazsa boş dize.

	YOLU ELLE KURMAK YANLIŞ — denendi ve ölçüldü: içerik-adresli adlandırma
	dosyaları hash önekine göre alt dizine koyuyor (`naming._shard`, 00–ff) ve
	`Path(file_url).name` ile kurulan yol o dizini atladığı için her ffprobe
	çağrısı "dosya bulunamadı" dönüyordu. `File.get_full_path()` Frappe'nin
	kendi çözümü: shard'ı da public/private ayrımını da o biliyor.
	`video_poster.generate` de aynı yolu kullanıyor.
	"""
	if not file_url:
		return ""
	# TÜM kardeşler denenir, ilki değil. Aynı adrese işaret eden kayıtlardan
	# yalnız BİRİ diske gerçekten yazılmış olabilir: içeriksiz eklenen bir
	# kardeş (yalnız `file_url` taşıyan bağ kaydı) `get_full_path`ten
	# çözülemeyen bir yol döndürüyor ve tek kayda bakan sürüm o kayda
	# çarptığında dosyayı "yok" sayıyordu — ölçüldü, kardeş testi -1 damgası
	# alıyordu.
	adlar = frappe.get_all("File", filters={"file_url": file_url}, pluck="name")
	for ad in adlar or []:
		try:
			yol = frappe.get_doc("File", ad).get_full_path()
		except (frappe.DoesNotExistError, OSError, ValueError):
			# Kayıt/dosya silinmiş olabilir — OLAĞAN durum. Log basmıyoruz:
			# her eksik dosya için hata kaydı üretmek gürültü olurdu.
			continue
		if yol and Path(yol).exists():
			return yol
	return ""
