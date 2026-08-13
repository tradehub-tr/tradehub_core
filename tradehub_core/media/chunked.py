"""Parçalı yükleme — büyük dosyalar için (TUR-123).

**Neden gerekli, ölçümle.** Tek parça yükleme dosyayı base64 ile taşıyor ve
içeriği **%33 şişiriyor**: 21 MB'lık bir dosya ~28 MB'lık isteğe dönüşüyor ve
bu boyut hem tarayıcının hem sunucunun belleğinde bir bütün olarak duruyor.
İzin listesinde video uzantıları varken tek parça sınırının 25 MB olması kendi
içinde çelişkiydi — ürünün video alanı var ama gerçek bir video yüklenemiyordu.

**Nasıl çalışıyor.** Yükleme üç adım:

    baslat(ad, toplam)   → oturum kimliği + parça boyutu
    parca(kimlik, sıra)  → parçayı diske ekle
    bitir(kimlik)        → birleştir, POLİTİKADAN GEÇİR, kaydı aç

Parçalar geldikçe diske yazılıyor; hiçbir anda dosyanın tamamı bellekte
durmuyor. Bu aynı zamanda gerçek ilerlemeyi mümkün kılıyor: ekran kaç parçanın
gittiğini biliyor, artık 0'dan 100'e atlamıyor.

**Politika birleşimden SONRA uygulanıyor.** Parça parça bakmak aldatıcı olurdu:
ilk parça geçerli bir görsel başlığı taşıyıp devamı bambaşka bir içerik
olabilir. Kural bütün dosyaya uygulanır — yeni bir kapı açmak, o kapıda aynı
kilidin olmasını gerektirir.

**Oturumlar mağazaya bağlı.** Kimlik tahmin edilse bile başka mağazanın
oturumuna parça eklenemez; kapsam kontrolü her adımda tekrarlanıyor.
"""

from __future__ import annotations

import os
import re
import shutil

import frappe

from tradehub_core.media import upload_policy

ROOT_DIRNAME = "media-uploads"

# Parça boyutu: 2 MB. Küçük tutmanın bedeli istek sayısı, büyük tutmanın bedeli
# bellek ve yeniden deneme maliyeti — kopan bir yükleme bütün parçayı tekrar
# gönderir. 2 MB'da 200 MB'lık dosya 100 parça eder; ikisi de makul.
CHUNK_BYTES: int = 2 * 1024 * 1024

# Üst sınır: en büyük türün sınırı / parça boyutu, üstüne pay. Sayaç olmadan
# sonsuz parça göndermek diski doldurmanın yolu olurdu.
MAX_CHUNKS: int = 256

# Yarım kalan oturumlar bu süre sonunda silinir. Tarayıcı kapanırsa parçalar
# diskte kalıyor; temizleyen olmazsa depo sessizce şişer.
SESSION_TTL_HOURS: int = 6

_ID_RE = re.compile(r"^[a-f0-9]{24}$")


def _root() -> str:
	yol = frappe.get_site_path("private", ROOT_DIRNAME)
	os.makedirs(yol, exist_ok=True)
	return yol


def _session_dir(upload_id: str) -> str:
	"""Oturum klasörü — kimlik doğrulanmadan yol kurulmaz.

	Kimlik istekten geliyor ve doğrudan dosya yoluna giriyor. Yedek kimliğinde
	aynı hata yol kaçışına açıktı (`../../../etc`); burada baştan kapatılıyor:
	önce kalıp, sonra çözülmüş yolun kökün altında kaldığının doğrulanması.
	"""
	if not _ID_RE.match(upload_id or ""):
		upload_policy.reddet(
			upload_policy.SESSION_UNKNOWN, frappe._("Geçersiz yükleme kimliği.")
		)
	kok = os.path.realpath(_root())
	tam = os.path.realpath(os.path.join(kok, upload_id))
	if tam != kok and not tam.startswith(kok + os.sep):
		upload_policy.reddet(
			upload_policy.SESSION_UNKNOWN, frappe._("Geçersiz yükleme kimliği.")
		)
	return tam


def _meta_path(upload_id: str) -> str:
	return os.path.join(_session_dir(upload_id), "meta.json")


def _read_meta(upload_id: str, store: str) -> dict:
	yol = _meta_path(upload_id)
	if not os.path.isfile(yol):
		upload_policy.reddet(
			upload_policy.SESSION_UNKNOWN, frappe._("Yükleme oturumu bulunamadı ya da süresi doldu.")
		)
	with open(yol, encoding="utf-8") as fh:
		import json

		meta = json.load(fh)
	# Kapsam her adımda yeniden doğrulanıyor: kimliği ele geçiren biri başka
	# mağazanın oturumuna parça ekleyememeli.
	if meta.get("store") != store:
		upload_policy.reddet(
			upload_policy.SESSION_UNKNOWN, frappe._("Yükleme oturumu bulunamadı ya da süresi doldu.")
		)
	return meta


def _write_meta(upload_id: str, meta: dict) -> None:
	import json

	yol = _meta_path(upload_id)
	gecici = f"{yol}.partial"
	with open(gecici, "w", encoding="utf-8") as fh:
		json.dump(meta, fh, ensure_ascii=False)
	os.replace(gecici, yol)


def begin(file_name: str, total_bytes: int, store: str) -> dict:
	"""Oturum aç — adı ve boyutu ŞİMDİDEN denetle.

	Boyut daha ilk adımda kontrol ediliyor: 300 MB'lık bir dosyanın 150 parçasını
	alıp sonunda "çok büyük" demek, hem kullanıcının hem diskin zamanını boşa
	harcamak olurdu.
	"""
	if not store:
		upload_policy.reddet(
			upload_policy.STORE_REQUIRED, frappe._("Bu işlem için bir mağaza hesabı gerekiyor.")
		)

	toplam = int(total_bytes or 0)
	karar = upload_policy.check(file_name, size=toplam, media_endpoint=True)

	if toplam <= 0:
		upload_policy.reddet(upload_policy.CONTENT_EMPTY, frappe._("Dosya içeriği boş."))

	parca_sayisi = (toplam + CHUNK_BYTES - 1) // CHUNK_BYTES
	if parca_sayisi > MAX_CHUNKS:
		upload_policy.reddet(
			upload_policy.TOO_MANY_CHUNKS, frappe._("Dosya çok fazla parçaya bölünüyor.")
		)

	upload_id = frappe.generate_hash(length=24)
	dizin = _session_dir(upload_id)
	os.makedirs(dizin, exist_ok=True)

	meta = {
		"upload_id": upload_id,
		"file_name": karar.file_name,
		"kind": karar.kind,
		"total_bytes": toplam,
		"chunk_bytes": CHUNK_BYTES,
		"chunk_count": parca_sayisi,
		"received": [],
		"store": store,
		"user": frappe.session.user,
		"created": frappe.utils.now(),
	}
	_write_meta(upload_id, meta)

	return {
		"upload_id": upload_id,
		"chunk_bytes": CHUNK_BYTES,
		"chunk_count": parca_sayisi,
		"file_name": karar.file_name,
	}


def put_chunk(upload_id: str, index: int, content: bytes, store: str) -> dict:
	"""Tek parçayı diske yaz.

	Parçalar SIRASIZ gelebilir — ağ paralel gönderebilir, yeniden deneme araya
	girebilir. Sıra numarası dosya adında tutuluyor, birleştirme sırayı kendisi
	kuruyor. Aynı parçanın tekrar gelmesi zararsız: üzerine yazılır.
	"""
	meta = _read_meta(upload_id, store)

	sira = int(index)
	if sira < 0 or sira >= meta["chunk_count"]:
		upload_policy.reddet(upload_policy.CHUNK_ORDER, frappe._("Geçersiz parça sırası."))
	if not content:
		upload_policy.reddet(upload_policy.CONTENT_EMPTY, frappe._("Parça boş."))

	# Parça, ilan edilen boyutu aşamaz. Aşabilseydi 10 parçalık bir oturum
	# ilan edilip her parçada 200 MB gönderilerek sınır atlatılabilirdi.
	if len(content) > CHUNK_BYTES:
		upload_policy.reddet(upload_policy.TOO_LARGE, frappe._("Parça çok büyük."))

	with open(os.path.join(_session_dir(upload_id), f"{sira:05d}.part"), "wb") as fh:
		fh.write(content)

	alinan = sorted(set(meta.get("received") or []) | {sira})
	meta["received"] = alinan
	_write_meta(upload_id, meta)

	return {
		"upload_id": upload_id,
		"received": len(alinan),
		"chunk_count": meta["chunk_count"],
		"complete": len(alinan) == meta["chunk_count"],
	}


def finish(upload_id: str, store: str) -> bytes:
	"""Parçaları birleştir ve İÇERİĞİ döndür — kaydı çağıran açar.

	Kayıt burada açılmıyor: dosya oluşturma medya ucunun işi ve orada denetim
	kaydı, sahiplik, üstveri gibi başka sorumluluklar var. Burada yalnız
	"parçalar bir dosya oldu" garantisi veriliyor.
	"""
	meta = _read_meta(upload_id, store)

	alinan = set(meta.get("received") or [])
	eksik = [i for i in range(meta["chunk_count"]) if i not in alinan]
	if eksik:
		upload_policy.reddet(
			upload_policy.CHUNK_MISSING,
			frappe._("Yükleme tamamlanmadı: {0} parça eksik.").format(len(eksik)),
		)

	dizin = _session_dir(upload_id)
	parcalar = bytearray()
	for i in range(meta["chunk_count"]):
		with open(os.path.join(dizin, f"{i:05d}.part"), "rb") as fh:
			parcalar.extend(fh.read())

	icerik = bytes(parcalar)

	# POLİTİKA BİRLEŞİMDEN SONRA. Parça parça bakmak aldatıcı olurdu: ilk parça
	# geçerli bir görsel başlığı taşıyıp devamı script olabilirdi.
	upload_policy.check(meta["file_name"], content=icerik, media_endpoint=True)

	return icerik


def cleanup_session(upload_id: str, store: str | None = None) -> None:
	"""Oturumu sil. `store` verilirse kapsam da doğrulanır."""
	if store is not None:
		_read_meta(upload_id, store)
	shutil.rmtree(_session_dir(upload_id), ignore_errors=True)


def meta_of(upload_id: str, store: str) -> dict:
	"""Oturumun durumu — ekran yarıda kalan yüklemeyi sürdürebilsin."""
	meta = _read_meta(upload_id, store)
	return {
		"upload_id": upload_id,
		"file_name": meta["file_name"],
		"chunk_count": meta["chunk_count"],
		"chunk_bytes": meta["chunk_bytes"],
		"received": sorted(meta.get("received") or []),
		"created": meta.get("created"),
	}


def cleanup(*, hours: int | None = None) -> dict:
	"""Süresi geçen oturumları sil — günlük görev buradan çağırır.

	`hours=0` "hepsi dolmuş say" demektir; sıfırı varsayılan diye okumak,
	hepsini silmek isteyen çağrıya sessizce hiçbir şey yapmazdı.
	"""
	sinir = SESSION_TTL_HOURS if hours is None else max(0, int(hours))
	kok = _root()
	silinen = 0
	kazanilan = 0

	for ad in os.listdir(kok):
		dizin = os.path.join(kok, ad)
		if not os.path.isdir(dizin):
			continue
		meta_yolu = os.path.join(dizin, "meta.json")
		damga = None
		if os.path.isfile(meta_yolu):
			try:
				import json

				with open(meta_yolu, encoding="utf-8") as fh:
					damga = json.load(fh).get("created")
			except Exception:
				damga = None
		if damga:
			try:
				if frappe.utils.time_diff_in_hours(frappe.utils.now(), damga) < sinir:
					continue
			except Exception:
				pass

		for dizin_yolu, _alt, dosyalar in os.walk(dizin):
			for d in dosyalar:
				try:
					kazanilan += os.path.getsize(os.path.join(dizin_yolu, d))
				except OSError:
					pass
		shutil.rmtree(dizin, ignore_errors=True)
		silinen += 1

	return {"removed_sessions": silinen, "freed_bytes": kazanilan}
