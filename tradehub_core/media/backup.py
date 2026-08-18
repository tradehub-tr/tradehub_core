"""Medya yedekleme — dosya ve kayıt birlikte (TUR-131).

**Neden gerekli, ölçümle.** Sistemde yalnız veritabanı yedeği var (Frappe'nin
kendi yedeği). Medya DOSYALARININ hiçbir yedeği yok: diskten bir görsel giderse
geri getirilemiyor. Bu oturumda üç kez yaşandı, ikisi kalıcı kayıpla sonuçlandı.

**Neden içerik-adresli.** Ölçüm (4.195 dosya, 994 MB):

    toplam                994 MB
    günlük değişim         ~12 MB   (son 30 günde 945 dosya / 372 MB)
    diskte boş alan       382 GB

Her anlık görüntüde bütün dosyaları kopyalamak günde 1 GB yazmak demekti.
Bunun yerine dosyalar **imzalarına göre** ortak bir havuzda saklanıyor; anlık
görüntü yalnız "hangi yol hangi imzaya karşılık geliyor" listesini tutuyor.
Sonuç:

  * Depolama artımlı — aynı içerik bir kez saklanır. Aynı görseli 5 satıcı
    yüklemiş olsa bile havuzda tek kopya durur.
  * Ama her anlık görüntü KENDİ BAŞINA eksiksiz — geri yüklemek için önceki
    yedeklere zincirleme bakmak gerekmez. Artımlı yedeklerin klasik zayıflığı
    budur: zincirin bir halkası bozulursa sonrası çöker.

**Dosya ve kayıt birlikte.** Yalnız dosyayı yedeklemek yetmez: `File` kaydı
olmadan dosya sistemde görünmez, kayıt olmadan da hangi ürüne ait olduğu
bilinmez. Bu yüzden her anlık görüntü dosyaların yanında `File` satırlarını da
saklar — özel alanlarımız (durum, çöp damgası, başlık, alternatif metin,
etiket) dahil.

**Yedek almak asla silmez.** Silme ayrı ve açıkça çağrılan işlemlerdir
(`delete_set`, `prune`) ve ikisi de sayaçlı çalışır: havuzdaki bir içerik
ancak hiçbir yedek onu göstermiyorsa kalkar. Son yedek silinemez.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime

import frappe

# Yedek deposu site'ın private alanında: web'den erişilemez.
ROOT_DIRNAME = "media-backups"
BLOBS = "blobs"
SETS = "sets"

# `File` üzerinden saklanan alanlar. Geri yükleme kaydı yeniden kurabilmeli;
# eksik bir alan "dosya döndü ama hangi üründe olduğu kayboldu" demek olurdu.
RECORD_FIELDS: tuple[str, ...] = (
	"name",
	"file_url",
	"file_name",
	"is_private",
	"is_folder",
	"file_size",
	"content_hash",
	"owner",
	"creation",
	"modified",
	"attached_to_doctype",
	"attached_to_name",
	"attached_to_field",
	"folder",
	"th_media_state",
	"th_trashed_at",
	"th_optimized_at",
	"th_original_size",
	"th_media_title",
	"th_media_alt",
	"th_media_description",
	"th_media_tags",
	"th_media_favorite",
	"th_media_width",
	"th_media_height",
	# Video işleme durumu (WP5). Yedeklenmezse geri yüklenen video "hiç
	# işlenmemiş" görünür ve `File.after_insert` kancası onu yeniden ffmpeg'e
	# sokup DİSKTEKİ dosyayı ezer — yani bit-bit geri yüklenen dosya bozulur.
	# `_records` alan listesini kolon varlığına göre süzdüğü için alanın
	# bulunmadığı site'larda sorun çıkarmaz.
	"th_media_video_status",
)

# Okuma parçası — 1 GB'lık dosyayı belleğe almadan imzalamak için.
_CHUNK = 1024 * 1024


def _root() -> str:
	return frappe.get_site_path("private", ROOT_DIRNAME)


def _blob_path(imza: str) -> str:
	# İki harflik alt klasör: tek dizine on binlerce dosya koymak dosya
	# sisteminde listeleme maliyetini uçuruyor.
	return os.path.join(_root(), BLOBS, imza[:2], imza)


# Yedek kimliği tarih damgasından üretiliyor; dışarıdan gelen bir kimlik de
# bu kalıba UYMAK ZORUNDA.
_SET_ID_RE = re.compile(r"^\d{8}_\d{6}(?:_[a-z0-9_]{1,24})?$")


def _set_path(set_id: str) -> str:
	"""Yedek klasörünün yolu — kimlik doğrulanmadan yol kurulmaz.

	Kimlik istekten geliyor ve doğrudan dosya yoluna giriyordu: `../../../etc`
	gibi bir değer yedek kökünün DIŞINA çıkıyordu. Silme ucu eklendiğinde bu,
	rastgele bir klasörü sildirebilirdi.

	İki kat kontrol var: önce kalıp, sonra çözülmüş yolun gerçekten kökün
	altında kaldığının doğrulanması. Yalnız kalıba güvenmek yetmez —
	sembolik bağ ya da kodlanmış bir dizi kalıbı geçerse ikinci kontrol tutar.
	"""
	if not _SET_ID_RE.match(set_id or ""):
		frappe.throw(frappe._("Geçersiz yedek kimliği: {0}").format(set_id))

	kok = os.path.realpath(os.path.join(_root(), SETS))
	tam = os.path.realpath(os.path.join(kok, set_id))
	if tam != kok and not tam.startswith(kok + os.sep):
		frappe.throw(frappe._("Geçersiz yedek kimliği: {0}").format(set_id))
	return tam


def _media_dirs() -> tuple[tuple[str, str], ...]:
	"""Yedeklenecek kökler — (etiket, mutlak yol).

	Özel dosyalar da yedekleniyor: KYB/KYC evrakı kaybolursa satıcı
	doğrulaması sıfırdan yapılır. Kapsam dışı olan şey onları PANELDE
	göstermek; yedeklemek değil.
	"""
	return (
		("public", frappe.get_site_path("public", "files")),
		("private", frappe.get_site_path("private", "files")),
	)


def file_hash(yol: str) -> str:
	h = hashlib.sha256()
	with open(yol, "rb") as fh:
		while parca := fh.read(_CHUNK):
			h.update(parca)
	return h.hexdigest()


def _scan() -> list[dict]:
	"""Diskteki tüm medya dosyalarının künyesi."""
	out: list[dict] = []
	for etiket, kok in _media_dirs():
		if not os.path.isdir(kok):
			continue
		for dizin, _alt, dosyalar in os.walk(kok):
			for ad in dosyalar:
				tam = os.path.join(dizin, ad)
				try:
					st = os.stat(tam)
				except OSError:
					# Tarama sırasında silinmiş olabilir; yedek bunun için
					# durmamalı.
					continue
				out.append(
					{
						"scope": etiket,
						"path": os.path.relpath(tam, kok),
						"size": st.st_size,
						"mtime": int(st.st_mtime),
						"hash": file_hash(tam),
					}
				)
	return out


def _records() -> list[dict]:
	"""`File` satırları — yalnız var olan alanlar sorulur.

	Alan listesi kurulumdan kuruluma değişebiliyor (özel alanlar yamayla
	geliyor). Olmayan bir alanı istemek tüm yedeği düşürürdü.
	"""
	mevcut = set(frappe.db.get_table_columns("File"))
	alanlar = [a for a in RECORD_FIELDS if a in mevcut]
	rows = frappe.get_all("File", fields=alanlar, limit_page_length=0)
	return [{k: (str(v) if isinstance(v, datetime) else v) for k, v in r.items()} for r in rows]


def snapshot(*, label: str = "") -> dict:
	"""Anlık görüntü al — dosyalar + `File` kayıtları.

	Her çağrı kendi başına eksiksiz bir görüntü üretir; depolama tarafında
	yalnız havuzda olmayan içerikler yazılır.
	"""
	baslangic = frappe.utils.now()
	set_id = frappe.utils.now_datetime().strftime("%Y%m%d_%H%M%S")
	if label:
		# Etiket kullanıcıdan geliyor; kimlik kalıbının dışına çıkan her karakter
		# atılır. Aksi hâlde kendi ürettiğimiz kimlik kendi doğrulamamıza takılırdı.
		temiz = re.sub(r"[^a-z0-9_]", "", frappe.scrub(label))[:24].strip("_")
		if temiz:
			set_id = f"{set_id}_{temiz}"

	hedef = _set_path(set_id)
	if os.path.exists(hedef):
		frappe.throw(frappe._("Bu adla bir yedek zaten var: {0}").format(set_id))

	dosyalar = _scan()

	yeni_blob = 0
	yeni_bayt = 0
	for d in dosyalar:
		blob = _blob_path(d["hash"])
		if os.path.isfile(blob):
			continue
		kaynak = os.path.join(dict(_media_dirs())[d["scope"]], d["path"])
		os.makedirs(os.path.dirname(blob), exist_ok=True)
		# Önce geçici ada yaz, sonra taşı: yarım kalan bir kopya havuzda
		# geçerli bir içerik gibi görünürdü.
		gecici = f"{blob}.partial"
		shutil.copy2(kaynak, gecici)
		os.replace(gecici, blob)
		yeni_blob += 1
		yeni_bayt += d["size"]

	kayitlar = _records()

	os.makedirs(hedef, exist_ok=True)
	manifest = {
		"set_id": set_id,
		"created": baslangic,
		"finished": frappe.utils.now(),
		"site": frappe.local.site,
		"label": label,
		"files": dosyalar,
		"stats": {
			"file_count": len(dosyalar),
			"total_bytes": sum(d["size"] for d in dosyalar),
			"new_blobs": yeni_blob,
			"new_bytes": yeni_bayt,
			"record_count": len(kayitlar),
		},
	}
	_yaz(os.path.join(hedef, "manifest.json"), manifest)
	_yaz(os.path.join(hedef, "records.json"), kayitlar)

	# Yapı künyesi: kayıtlar bugünkü sütunlara göre yazıldı. Yedek başka bir
	# veritabanının üzerine açılırsa hangi alanların karşılığı olmadığı ancak
	# bununla anlaşılır — künye olmadan fark sessizce kaybolurdu.
	try:
		from tradehub_core.media import schema

		_yaz(os.path.join(hedef, "schema.json"), schema.capture())
	except Exception:
		# Künye alınamadı diye yedek düşmemeli: asıl iş dosyalar ve kayıtlar.
		frappe.log_error(
			title=f"Medya yedegi: yapi kunyesi alinamadi {set_id}",
			message=frappe.get_traceback(with_context=True),
		)

	return {"set_id": set_id, **manifest["stats"]}


def _yaz(yol: str, veri) -> None:
	"""Atomik yaz — yarım kalan bir manifest, geri yüklemeyi sessizce bozardı."""
	gecici = f"{yol}.partial"
	with open(gecici, "w", encoding="utf-8") as fh:
		json.dump(veri, fh, ensure_ascii=False)
	os.replace(gecici, yol)


def _oku(yol: str):
	with open(yol, encoding="utf-8") as fh:
		return json.load(fh)


def manifest_of(set_id: str) -> dict:
	yol = os.path.join(_set_path(set_id), "manifest.json")
	if not os.path.isfile(yol):
		frappe.throw(frappe._("Yedek bulunamadı: {0}").format(set_id))
	return _oku(yol)


def records_of(set_id: str) -> list[dict]:
	yol = os.path.join(_set_path(set_id), "records.json")
	return _oku(yol) if os.path.isfile(yol) else []


def schema_of(set_id: str) -> dict | None:
	"""Yedek alındığındaki veritabanı yapısı — künye eklenmeden önceki
	yedeklerde yoktur, o zaman None döner."""
	yol = os.path.join(_set_path(set_id), "schema.json")
	if not os.path.isfile(yol):
		return None
	try:
		return _oku(yol)
	except Exception:
		return None


def list_sets() -> list[dict]:
	"""Alınmış yedekler — yeniden eskiye."""
	kok = os.path.join(_root(), SETS)
	if not os.path.isdir(kok):
		return []
	out = []
	for ad in sorted(os.listdir(kok), reverse=True):
		try:
			m = manifest_of(ad)
		except Exception:
			continue
		out.append(
			{
				"set_id": ad,
				"created": m.get("created"),
				"label": m.get("label") or "",
				**(m.get("stats") or {}),
			}
		)
	return out


def verify(set_id: str, *, deep: bool = False) -> dict:
	"""Yedek gerçekten geri yüklenebilir mi — DOKUNMADAN kontrol.

	`deep=False`: her dosyanın havuzda karşılığı var mı (hızlı).
	`deep=True` : havuzdaki içeriğin imzası da yeniden hesaplanır. Sessiz disk
	bozulmasını ancak bu yakalar; yavaş olduğu için isteğe bağlı.

	"Yedeğim var" demek yetmez, "yedeğim çalışıyor" demek gerekir — bu
	fonksiyon olmadan ilki ikincisinin yerine geçerdi.
	"""
	m = manifest_of(set_id)
	eksik: list[str] = []
	bozuk: list[str] = []

	for d in m["files"]:
		blob = _blob_path(d["hash"])
		if not os.path.isfile(blob):
			eksik.append(d["path"])
			continue
		if deep and file_hash(blob) != d["hash"]:
			bozuk.append(d["path"])

	kayitlar = records_of(set_id)
	return {
		"set_id": set_id,
		"files": len(m["files"]),
		"records": len(kayitlar),
		"missing_blobs": eksik[:50],
		"missing_count": len(eksik),
		"corrupt_blobs": bozuk[:50],
		"corrupt_count": len(bozuk),
		"deep": deep,
		"ok": not eksik and not bozuk,
	}


def prune(*, keep: int = 14) -> dict:
	"""Eski yedekleri sil ve artık kimsenin kullanmadığı içerikleri temizle.

	`keep` en yeni kaç anlık görüntünün tutulacağı. Ölçüme göre günde ~12 MB
	değişim var; 14 gün ≈ 1 GB havuz + 168 MB değişim. Diskte 382 GB boş
	olduğu için sınır maliyet değil, gürültü.

	Havuzdaki bir içerik ancak HİÇBİR anlık görüntü onu göstermiyorsa silinir.
	Sayaç bu yüzden şart: paylaşılan içeriği erken silmek, kalan yedekleri
	sessizce bozardı.
	"""
	setler = list_sets()
	silinecek = setler[keep:]
	for s in silinecek:
		shutil.rmtree(_set_path(s["set_id"]), ignore_errors=True)

	temizlik = _collect_orphan_blobs()

	return {
		"removed_sets": [s["set_id"] for s in silinecek],
		"remaining_sets": len(list_sets()),
		**temizlik,
	}


# Günlük görüntü + kaç gün saklanacağı. Ölçümle seçildi (994 MB toplam,
# günde ~12 MB değişim, diskte 382 GB boş): 14 gün ≈ 1 GB havuz + ~170 MB
# değişim. Sınırı belirleyen maliyet değil, listenin okunabilir kalması.
KEEP_SETS: int = 14


def run_scheduled() -> dict:
	"""Günlük yedek — zamanlanmış görev buradan çağrılır.

	Sıra önemli: ÖNCE yedek alınır, SONRA eskiler temizlenir. Tersi olsaydı
	temizlik başarılı, yedek başarısız olduğunda elde daha az yedek kalırdı.

	Hata yutulmuyor ama zincirin geri kalanını da düşürmüyor: yedek alınamadıysa
	temizlik hiç çalışmaz, sorun kayda geçer ve mevcut yedekler olduğu gibi
	durur.
	"""
	try:
		alinan = snapshot(label="scheduled")
	except Exception:
		frappe.log_error(
			title="Medya yedegi alinamadi",
			message=frappe.get_traceback(with_context=True),
		)
		raise

	temizlik = prune(keep=KEEP_SETS)

	# Dışa aktarma paketleri yedeğin ikinci kopyası; süresi geçenler burada
	# düşer. Ayrı bir zamanlanmış görev açmak yerine buraya bağlandı: ikisi de
	# aynı deponun yerini yönetiyor ve sıraları önemli (önce yedek, sonra
	# temizlik).
	paketler = {}
	satici_paketler = {}
	try:
		from tradehub_core.media import backup_export

		paketler = backup_export.cleanup()
		# Satıcı paketleri de aynı turda temizlenir (TUR-131 satıcı tarafı) —
		# ayrı bir zamanlanmış görev, "hangi temizlik nerede" sorusunu her
		# okuyana yeniden sordururdu.
		from tradehub_core.media import seller_backup_export

		satici_paketler = seller_backup_export.cleanup()
	except Exception:
		# Paket temizliği yedeği düşürmemeli: yedek alındı, asıl iş bitti.
		frappe.log_error(
			title="Medya yedek paketleri temizlenemedi",
			message=frappe.get_traceback(with_context=True),
		)

	# Yarım kalan parçalı yükleme oturumları (TUR-123). Tarayıcı kapanırsa
	# parçalar diskte kalıyor; temizleyen olmazsa depo sessizce şişer.
	oturumlar = {}
	try:
		from tradehub_core.media import chunked

		oturumlar = chunked.cleanup()
	except Exception:
		frappe.log_error(
			title="Medya yukleme oturumlari temizlenemedi",
			message=frappe.get_traceback(with_context=True),
		)

	return {
		"snapshot": alinan,
		"prune": temizlik,
		"exports": paketler,
		"seller_exports": satici_paketler,
		"upload_sessions": oturumlar,
	}


def delete_set(set_id: str) -> dict:
	"""Tek bir yedeği sil.

	Havuzdaki içerikler HEMEN silinmez: aynı içeriği başka bir yedek de
	gösteriyor olabilir. Sahipsiz kalanlar aynı işlemde ayıklanır — sayaç
	olmadan silmek, kalan yedekleri sessizce bozardı.
	"""
	yol = _set_path(set_id)
	if not os.path.isdir(yol):
		frappe.throw(frappe._("Yedek bulunamadı: {0}").format(set_id))

	kalan_once = len(list_sets())
	if kalan_once <= 1:
		# Son yedeği silmek "yedeğim var" durumunu sessizce bitirir. Yıkıcı
		# olmasa da geri dönüşü yok; açık bir engel daha iyi.
		frappe.throw(frappe._("Son yedek silinemez. Önce yeni bir yedek alın."))

	shutil.rmtree(yol, ignore_errors=True)
	temizlik = _collect_orphan_blobs()
	return {"set_id": set_id, "remaining_sets": len(list_sets()), **temizlik}


def _collect_orphan_blobs() -> dict:
	"""Hiçbir yedeğin göstermediği içerikleri sil."""
	kullanilan: set[str] = set()
	for s in list_sets():
		for d in manifest_of(s["set_id"])["files"]:
			kullanilan.add(d["hash"])

	silinen = 0
	kazanilan = 0
	blob_kok = os.path.join(_root(), BLOBS)
	if os.path.isdir(blob_kok):
		for alt in os.listdir(blob_kok):
			ad = os.path.join(blob_kok, alt)
			if not os.path.isdir(ad):
				continue
			for imza in os.listdir(ad):
				if imza in kullanilan or imza.endswith(".partial"):
					continue
				try:
					p = os.path.join(ad, imza)
					kazanilan += os.path.getsize(p)
					os.remove(p)
					silinen += 1
				except OSError:
					continue
	return {"removed_blobs": silinen, "freed_bytes": kazanilan}


def usage() -> dict:
	"""Yedek deposunun kapladığı yer — maliyet kararı için."""
	toplam = 0
	sayi = 0
	for dizin, _alt, dosyalar in os.walk(_root()):
		for ad in dosyalar:
			try:
				toplam += os.path.getsize(os.path.join(dizin, ad))
				sayi += 1
			except OSError:
				continue
	return {"bytes": toplam, "files": sayi, "sets": len(list_sets())}
