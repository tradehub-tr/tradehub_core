"""Satıcı medya yedeği — mağazanın kendi dosyaları, kendi deposunda (TUR-131).

`media/backup.py` PLATFORMUN yedeğidir: tüm dosyalar, tüm `File` satırları, tek
havuz. Yönetim felaket kurtarması için doğru olan bu; ama satıcıya verilemez —
bir mağazanın diğerinin envanterini görmesi, indirmesi ya da geri yüklemesi
demek olurdu.

Bu modül aynı fikri **kiracı sınırları içinde** yeniden kuruyor:

    private/media-seller-backups/<store>/blobs/<xx>/<imza>
    private/media-seller-backups/<store>/sets/<set_id>/manifest.json
    private/media-seller-backups/<store>/sets/<set_id>/records.json

**Havuz mağaza başına ayrı.** Platform havuzunu paylaşmak depolama açısından
cazip ama yanlış: aynı içeriği iki mağaza yüklediğinde tek blob olurdu ve biri
yedeğini silince diğerininki sessizce bozulurdu. Kiracı izolasyonu, birkaç
mükerrer bayttan önce gelir.

**Kapsam = satıcının kütüphanesinde GÖRDÜĞÜ dosyalar.** Aynı sorgu iskeleti
(`inventory._base_query` + `ownership.scope`) kullanılıyor. Böylece "yedeğim
neyi kapsıyor" sorusunun cevabı ekranla birebir aynı: panelde görünmeyen bir
dosya (private, hassas belge ikizi, kapsam dışı doctype eki) yedeğe de girmez.

**İndirilen pakette veritabanı YOKTUR.** Satıcı kendi dosyalarını ve kendi
kayıtlarının okunabilir künyesini (CSV) alır; ham veritabanı çıktısı verilmez.
Veritabanına yazma yalnız tek bir yerde ve dar kapsamda olur: satıcının KENDİ
`File` kaydı kaybolmuşsa geri kurulur (`apply(..., records=True)`). Kaydın
sahibi mağazanın kullanıcılarından biri değilse dokunulmaz.

Geri yükleme kuralları `media/restore.py` ile aynı, çünkü tehlike aynı:

  * önce plan, sonra uygulama — kimse yanlışlıkla geri yükleme başlatamaz
  * asla silmez — yedekten sonra yüklenen dosya "fazla" diye raporlanır, durur
  * değişmiş dosyanın üzerine yazmaz — `overwrite` açıkça istenmedikçe
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime

import frappe

from tradehub_core.media import backup, ownership

ROOT_DIRNAME = "media-seller-backups"
BLOBS = "blobs"
SETS = "sets"

# Mağaza başına tutulacak azami yedek sayısı. Havuz artımlı olduğu için 5 set
# ≈ 1 kopya + değişimler; sayıyı büyütmenin maliyeti değişim hacmi kadardır.
# Yeni yedek alınırken en eskisi otomatik düşer — satıcıdan "yer aç" istemek,
# yedeklemeyi caydırırdı.
MAX_SETS_PER_STORE: int = 5

# Ardışık yedekler arası asgari süre. Artımlı olduğu için ikinci yedek
# neredeyse bedava, ama düğmeye üst üste basmak diski tarayıp CPU yakar ve
# listeyi anlamsız kılar (aynı içeriğe 20 satır).
MIN_INTERVAL_SECONDS: int = 600

# Satıcının kendi kayıtlarından pakete konacak alanlar. `backup.RECORD_FIELDS`
# ile aynı değil: iç işleyişe ait alanlar (folder, is_folder, content_hash)
# satıcı için gürültü, künyede işi yok.
RECORD_FIELDS: tuple[str, ...] = (
	"name",
	"file_url",
	"file_name",
	"file_size",
	"owner",
	"creation",
	"attached_to_doctype",
	"attached_to_name",
	"th_media_state",
	"th_trashed_at",
	"th_optimized_at",
	"th_media_title",
	"th_media_alt",
	"th_media_description",
	"th_media_tags",
	"th_media_favorite",
	"th_media_width",
	"th_media_height",
	"th_media_video_status",
)

_SET_ID_RE = re.compile(r"^\d{8}_\d{6}(?:_[a-z0-9_]{1,24})?$")
# Mağaza kimliği de yola giriyor. Kalıba uymayan bir değer (ör. "../..") yedek
# kökünün dışına çıkardı; kimlik doğrulaması yalnız `set_id` için yeterli değil.
_STORE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# --- yol kurma (kiracı sınırı burada) ---------------------------------------


def _store_root(store: str) -> str:
	"""Mağazanın yedek kökü — kimlik doğrulanmadan yol kurulmaz."""
	if not _STORE_RE.match(store or ""):
		frappe.throw(frappe._("Geçersiz mağaza kimliği."))
	return frappe.get_site_path("private", ROOT_DIRNAME, store)


def _blob_path(store: str, imza: str) -> str:
	# İmza da yola giriyor; sha256 dışında bir şey gelirse yol kaçışı olurdu.
	if not re.fullmatch(r"[0-9a-f]{64}", imza or ""):
		frappe.throw(frappe._("Geçersiz içerik imzası."))
	return os.path.join(_store_root(store), BLOBS, imza[:2], imza)


def _set_path(store: str, set_id: str) -> str:
	"""Yedek klasörü — kalıp VE çözülmüş yol iki kez doğrulanır.

	`backup._set_path` ile aynı desen: yalnız kalıba güvenmek yetmez, sembolik
	bağ ya da kodlanmış bir dizi kalıbı geçebilir. İkinci kontrol, çözülmüş
	yolun gerçekten MAĞAZANIN kökü altında kaldığını doğrular — bu olmadan bir
	satıcı başka mağazanın yedeğine ulaşabilirdi.
	"""
	if not _SET_ID_RE.match(set_id or ""):
		frappe.throw(frappe._("Geçersiz yedek kimliği: {0}").format(set_id))

	kok = os.path.realpath(os.path.join(_store_root(store), SETS))
	tam = os.path.realpath(os.path.join(kok, set_id))
	if tam != kok and not tam.startswith(kok + os.sep):
		frappe.throw(frappe._("Geçersiz yedek kimliği: {0}").format(set_id))
	return tam


def _live_path(rel: str) -> str:
	"""Yedekteki göreli yolun diskteki karşılığı.

	Kapsam yalnız public (bkz. modül docstring'i), o yüzden tek kök var. Göreli
	yol manifest'ten geliyor ama yine de kök altında kaldığı doğrulanıyor:
	manifest dosyası elle kurcalanmış olabilir.
	"""
	kok = os.path.realpath(frappe.get_site_path("public", "files"))
	tam = os.path.realpath(os.path.join(kok, rel))
	if not tam.startswith(kok + os.sep):
		frappe.throw(frappe._("Geçersiz dosya yolu: {0}").format(rel))
	return tam


# --- kapsam -----------------------------------------------------------------


def _store_urls(store: str) -> list[str]:
	"""Mağazanın yedeğe girecek dosya adresleri.

	Envanterle AYNI sorgu iskeleti kullanılıyor: panelde görünmeyen bir dosya
	yedeğe de girmemeli. Kapsam kuralları (private hariç, hassas belge ikizi
	hariç, kapsam dışı doctype ekleri hariç) `_base_query` içinde; burada
	tekrarlanmıyor ki ikisi ayrışmasın.
	"""
	from tradehub_core.media import inventory

	f, q = inventory._base_query()
	q = ownership.scope(q, f, store)
	return [r[0] for r in q.select(f.file_url).run() if r and r[0]]


def _yokluk_sebebi(file_url: str | None) -> str:
	"""Dosya canlı ağaçta yoksa sebebi — "kayıp" ile "beklemede"yi ayırır.

	`scan_hold`: taraması sürüyor, bir sonraki yedeğe girer.
	`quarantine`: zararlı bulundu; yedeğe GİRMEMESİ doğru davranış — geri
	yükleme zararlıyı sisteme geri getirirdi.
	`missing`: gerçekten kayıp, ilgilenilmesi gereken tek durum.
	"""
	if not file_url:
		return "missing"
	try:
		from tradehub_core.media import av

		if av.in_quarantine(file_url):
			return "quarantine"
		if av.in_hold(file_url):
			return "scan_hold"
	except Exception:
		# Tarama modülü bir sebeple yüklenemezse rapor yine üretilmeli.
		pass
	return "missing"


def _servis_edilebilir(file_url: str) -> bool:
	"""Dosya erişime açık mı — kararı AV politikası veriyor (TUR-125).

	Tarama sistemi, henüz taranmamış ya da zararlı bulunmuş dosyayı public
	ağaçtan FİZİKSEL olarak çıkarıyor (`media_scan_hold` / `media_quarantine`);
	`file_url` değişmiyor, dosya yer değiştiriyor. Karar burada yeniden
	üretilmiyor — `av.is_servable` zaten bu çağrı için yazılmış (docstring'inde
	"yedek paketleme" örnek veriliyor).

	Tarama modülü yoksa (eski kurulum) kapı açık: yedekleme, olmayan bir
	bileşenin yokluğu yüzünden durmamalı.
	"""
	try:
		from tradehub_core.media import av
	except ImportError:
		return True
	try:
		return av.is_servable(file_url)
	except Exception:
		# Politika okunamadı: yedek almak güvenlik kararı değil, bu yüzden
		# fail-open. Geri YAZMA tarafı ayrıca korunuyor (`apply`).
		frappe.log_error(
			title="Satici yedegi: tarama durumu okunamadi",
			message=frappe.get_traceback(with_context=True),
		)
		return True


def _scan(store: str) -> tuple[list[dict], list[str]]:
	"""Mağazanın dosyalarının künyesi — (yedeklenecekler, atlananlar).

	İki ayrı sebeple atlanır ve ikisi de SESSİZ KALMAMALI:

	  * Kaydı olup dosyası kaybolmuş adres — yedeklenecek içerik yok. Yeni bir
	    kayıp değil; `plan` onu `missing_file` olarak zaten gösteriyor.
	  * Taranmayı bekleyen ya da karantinadaki dosya — public ağaçta değil.
	    Sessizce atlamak satıcıya EKSİK bir yedeği tam gibi gösterirdi.
	"""
	out: list[dict] = []
	atlanan: list[str] = []
	for url in _store_urls(store):
		if not url.startswith("/files/"):
			continue
		rel = url[len("/files/") :]
		if not _servis_edilebilir(url):
			atlanan.append(rel)
			continue
		try:
			tam = _live_path(rel)
			st = os.stat(tam)
		except (OSError, frappe.ValidationError):
			continue
		out.append(
			{
				"path": rel,
				"file_url": url,
				"size": st.st_size,
				"mtime": int(st.st_mtime),
				"hash": backup.file_hash(tam),
			}
		)
	return out, atlanan


def _uploaded_urls(store: str) -> set[str]:
	"""Mağazanın gerçekten YÜKLEDİĞİ dosya adresleri — yazma yetkisinin sınırı.

	`_store_urls` (ve kütüphane görünümü) iki yoldan sahiplik tanıyor: mağazanın
	yüklediği dosyalar VEYA mağazanın kayıtlarında kullanılan dosyalar. İkincisi
	OKUMA için doğru — satıcı ürününde duran görseli görmeli, yedeğinde de
	bulmalı. Ama YAZMA için tehlikeli: paylaşılan bir dosyayı geri yazmak, o
	dosyayı yükleyen BAŞKA mağazanın bugünkü sürümünü eski hâline döndürürdü.
	Ölçüldü: 30 adres iki mağazaya birden ait (bkz. `media/ownership.py`).

	Bu yüzden geri yükleme yalnız bu kümeye yazar; kalanı rapor edilip atlanır.
	"""
	kullanicilar = list(ownership.users_of(store))
	if not kullanicilar:
		return set()
	return set(
		# Sistem işi: kapsam zaten mağazanın kullanıcılarına daraltıldı.
		frappe.get_all(
			"File",
			filters={"owner": ["in", kullanicilar], "is_folder": 0},
			pluck="file_url",
			limit_page_length=0,
		)
	)


def _records(store: str, urls: set[str]) -> list[dict]:
	"""Mağazanın `File` satırları — yalnız yedeğe giren adresler için.

	Alan listesi kolon varlığına göre süzülüyor: özel alanlar yamayla geliyor,
	olmayan bir alanı istemek tüm yedeği düşürürdü (`backup._records` ile aynı
	gerekçe).
	"""
	if not urls:
		return []
	mevcut = set(frappe.db.get_table_columns("File"))
	alanlar = [a for a in RECORD_FIELDS if a in mevcut]
	rows = frappe.get_all(
		# Sistem işi: kapsam zaten mağazaya daraltıldı, ayrıca kullanıcı
		# yetkisiyle süzmek "kendi dosyamı yedekleyemedim" durumuna yol açardı.
		"File",
		filters={"file_url": ["in", list(urls)], "is_folder": 0},
		fields=alanlar,
		limit_page_length=0,
	)
	kullanicilar = set(ownership.users_of(store))
	return [
		{k: (str(v) if isinstance(v, datetime) else v) for k, v in r.items()}
		for r in rows
		# Yalnız MAĞAZANIN yüklediği kayıtlar künyeye giriyor. Paylaşılan bir
		# adreste başka mağazanın kaydı da olabilir; onu pakete koymak başka
		# kiracının verisini sızdırmak olurdu.
		if r.get("owner") in kullanicilar
	]


# --- yedek alma -------------------------------------------------------------


def _yaz(yol: str, veri) -> None:
	"""Atomik yaz — yarım kalan bir manifest geri yüklemeyi sessizce bozardı."""
	gecici = f"{yol}.partial"
	with open(gecici, "w", encoding="utf-8") as fh:
		json.dump(veri, fh, ensure_ascii=False)
	os.replace(gecici, yol)


def _oku(yol: str):
	with open(yol, encoding="utf-8") as fh:
		return json.load(fh)


def _son_yedek_zamani(store: str) -> str | None:
	setler = list_sets(store)
	return setler[0]["created"] if setler else None


def _yeni_set_id(store: str, label: str = "") -> str:
	"""Çakışmayan bir yedek kimliği üret.

	Damga saniye çözünürlüklü; aynı saniyede iki yedek alınırsa kimlik
	çakışıyordu. Üretimde hız sınırı bunu zaten engelliyor ama kimliğin
	benzersizliği bir başka ayarın yan etkisine bırakılmamalı — sınır
	gevşetilirse (ya da testte kapatılırsa) yedek alma sessizce patlardı.

	Etiket kullanıcıdan geliyor; kimlik kalıbının dışındaki her karakter atılır,
	yoksa kendi ürettiğimiz kimlik kendi doğrulamamıza takılırdı.
	"""
	damga = frappe.utils.now_datetime().strftime("%Y%m%d_%H%M%S")
	temiz = re.sub(r"[^a-z0-9_]", "", frappe.scrub(label))[:20].strip("_") if label else ""

	for sayac in range(1, 50):
		ek = temiz if sayac == 1 else f"{temiz}{sayac}" if temiz else str(sayac)
		aday = f"{damga}_{ek}" if ek else damga
		try:
			# `exist_ok=False` bilerek: klasörü açabilen kimliği kazanır. Önce
			# "var mı" diye bakıp sonra açmak, iki eşzamanlı isteğin aynı
			# klasöre yazmasına açık kapı bırakıyordu.
			os.makedirs(_set_path(store, aday), exist_ok=False)
			return aday
		except FileExistsError:
			continue

	# Buraya düşmek aynı saniyede 50 yedek demek — gerçekte imkânsız, ama
	# sessiz bir sonsuz döngü yerine açık bir hata bırakılıyor.
	frappe.throw(frappe._("Yedek kimliği üretilemedi, birkaç saniye sonra tekrar deneyin."))


def create(store: str, *, label: str = "") -> dict:
	"""Mağazanın anlık görüntüsünü al.

	Her görüntü kendi başına eksiksizdir: geri yüklemek için önceki yedeklere
	zincirleme bakmak gerekmez. Depolama tarafında yalnız havuzda olmayan
	içerikler yazılır — aynı görsel değişmediyse ikinci kez yer kaplamaz.
	"""
	son = _son_yedek_zamani(store)
	if son and frappe.utils.time_diff_in_seconds(frappe.utils.now(), son) < MIN_INTERVAL_SECONDS:
		frappe.throw(
			frappe._("Az önce yedek aldınız. {0} dakikada bir yedek alınabilir.").format(
				MIN_INTERVAL_SECONDS // 60
			)
		)

	# Yer yoksa hiç başlamamak, yarıda dolu diskle durmaktan iyidir. Ölçü
	# kabaca son yedeğin boyutu: artımlı olduğu için gerçek ihtiyaç bundan
	# küçük, yani kontrol temkinli tarafta.
	kok = _store_root(store)
	os.makedirs(kok, exist_ok=True)
	son_boyut = (list_sets(store) or [{}])[0].get("total_bytes") or 0
	if son_boyut and shutil.disk_usage(kok).free < son_boyut * 1.2:
		frappe.throw(frappe._("Yedek için yeterli disk alanı yok."))

	baslangic = frappe.utils.now()
	set_id = _yeni_set_id(store, label)
	hedef = _set_path(store, set_id)  # `_yeni_set_id` klasörü zaten açtı

	dosyalar, taranmamis = _scan(store)

	yeni_blob = 0
	yeni_bayt = 0
	for d in dosyalar:
		blob = _blob_path(store, d["hash"])
		if os.path.isfile(blob):
			continue
		os.makedirs(os.path.dirname(blob), exist_ok=True)
		# Önce geçici ada yaz, sonra taşı: yarım kalan bir kopya havuzda geçerli
		# bir içerik gibi görünürdü.
		gecici = f"{blob}.partial"
		shutil.copy2(_live_path(d["path"]), gecici)
		os.replace(gecici, blob)
		yeni_blob += 1
		yeni_bayt += d["size"]

	kayitlar = _records(store, {d["file_url"] for d in dosyalar})

	manifest = {
		"set_id": set_id,
		"store": store,
		"created": baslangic,
		"finished": frappe.utils.now(),
		"label": label,
		"files": dosyalar,
		"stats": {
			"file_count": len(dosyalar),
			"total_bytes": sum(d["size"] for d in dosyalar),
			"new_blobs": yeni_blob,
			"new_bytes": yeni_bayt,
			"record_count": len(kayitlar),
			# Taranmayı bekleyen / karantinadaki dosyalar yedeğe GİRMEDİ.
			# Sayı manifest'te duruyor ki "yedeğim tam mı" sorusu sonradan da
			# cevaplanabilsin.
			"skipped_unscanned": len(taranmamis),
		},
	}
	_yaz(os.path.join(hedef, "manifest.json"), manifest)
	_yaz(os.path.join(hedef, "records.json"), kayitlar)

	dusen = prune(store)

	from tradehub_core.media import audit

	audit.log_media_event(
		action=audit.ACTION_BACKUP,
		tenant=store,
		context={"set_id": set_id, **manifest["stats"], "pruned": dusen.get("removed", 0)},
	)
	return {"set_id": set_id, **manifest["stats"], "pruned": dusen.get("removed", 0)}


# --- okuma ------------------------------------------------------------------


def manifest_of(store: str, set_id: str) -> dict:
	yol = os.path.join(_set_path(store, set_id), "manifest.json")
	if not os.path.isfile(yol):
		frappe.throw(frappe._("Yedek bulunamadı: {0}").format(set_id))
	return _oku(yol)


def records_of(store: str, set_id: str) -> list[dict]:
	yol = os.path.join(_set_path(store, set_id), "records.json")
	return _oku(yol) if os.path.isfile(yol) else []


def list_sets(store: str) -> list[dict]:
	"""Mağazanın yedekleri — yeniden eskiye."""
	kok = os.path.join(_store_root(store), SETS)
	if not os.path.isdir(kok):
		return []
	out = []
	for ad in sorted(os.listdir(kok), reverse=True):
		try:
			m = manifest_of(store, ad)
		except Exception:
			# Yarım kalmış / bozuk klasör listeyi düşürmemeli.
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


def verify(store: str, set_id: str, *, deep: bool = False) -> dict:
	"""Yedek gerçekten geri yüklenebilir mi — DOKUNMADAN kontrol.

	`deep=False`: her dosyanın havuzda karşılığı var mı (hızlı).
	`deep=True` : içeriğin imzası yeniden hesaplanır; sessiz disk bozulmasını
	ancak bu yakalar, yavaş olduğu için isteğe bağlı.
	"""
	m = manifest_of(store, set_id)
	eksik: list[str] = []
	bozuk: list[str] = []

	for d in m["files"]:
		blob = _blob_path(store, d["hash"])
		if not os.path.isfile(blob):
			eksik.append(d["path"])
			continue
		if deep and backup.file_hash(blob) != d["hash"]:
			bozuk.append(d["path"])

	return {
		"set_id": set_id,
		"files": len(m["files"]),
		"records": len(records_of(store, set_id)),
		"missing_blobs": eksik[:50],
		"missing_count": len(eksik),
		"corrupt_blobs": bozuk[:50],
		"corrupt_count": len(bozuk),
		"deep": deep,
		"ok": not eksik and not bozuk,
	}


def usage(store: str) -> dict:
	"""Mağazanın yedeği diskte ne kadar yer kaplıyor."""
	kok = _store_root(store)
	toplam = 0
	sayi = 0
	for dizin, _alt, dosyalar in os.walk(os.path.join(kok, BLOBS)):
		for ad in dosyalar:
			try:
				toplam += os.path.getsize(os.path.join(dizin, ad))
				sayi += 1
			except OSError:
				continue
	return {"bytes": toplam, "blobs": sayi, "sets": len(list_sets(store)), "max_sets": MAX_SETS_PER_STORE}


# --- geri yükleme -----------------------------------------------------------


def plan(store: str, set_id: str) -> dict:
	"""Ne olacağını söyle — HİÇBİR ŞEYE DOKUNMA.

	Kabul kriteri "geri yükleme senaryosu test edilebilir şekilde tarif edilmiş
	olmalı" diyor. Bu fonksiyon o tarifin kendisi.

	`extra` (bugün var, yedekte yok) RAPORLANIR ama hiçbir zaman silinmez —
	yedekten sonra yüklenen dosyaları temizlemek, "geri yükleme" adı altında
	veri kaybı olurdu.
	"""
	m = manifest_of(store, set_id)
	kayitlar = records_of(store, set_id)

	ok = 0
	eksik_dosya: list[dict] = []
	catisma: list[dict] = []

	yedekteki = set()
	for d in m["files"]:
		yedekteki.add(d["path"])
		try:
			canli = _live_path(d["path"])
		except frappe.ValidationError:
			continue
		if not os.path.isfile(canli):
			# Dosya canlı ağaçta yok — ama "kayıp" demeden önce NEDEN yok
			# olduğuna bakılıyor (TUR-125). Tarama bekleyen dosya geçici olarak
			# `media_scan_hold`'da, zararlı bulunan `media_quarantine`'de durur.
			# İkisi de kayıp DEĞİL; "N dosya kayıp!" diye alarm vermek raporu
			# gürültüye boğar ve gerçek kayıpları görünmez yapardı.
			eksik_dosya.append(
				{
					"path": d["path"],
					"file_url": d.get("file_url"),
					"size": d["size"],
					"reason": _yokluk_sebebi(d.get("file_url")),
				}
			)
			continue
		# Boyut farklıysa imza hesaplamaya gerek yok — kesin farklı.
		if os.path.getsize(canli) != d["size"] or backup.file_hash(canli) != d["hash"]:
			catisma.append({"path": d["path"], "file_url": d.get("file_url")})
			continue
		ok += 1

	# Bugün mağazada olup yedekte olmayanlar — yalnız bilgi, asla silinmez.
	#
	# Adres listesi kayıtlardan geliyor ama DİSK kontrolü şart: kaydı olup
	# dosyası kaybolmuş bir adres yedeğe hiç girmemişti (`_scan` onu atlıyor) ve
	# burada "yedekten sonra eklenmiş" gibi görünüyordu. Kullanıcıya "2 yeni
	# dosyan var" demek, aslında 2 dosyasını kaybettiği anlamına geliyordu.
	fazla = []
	for url in _store_urls(store):
		if not url.startswith("/files/"):
			continue
		rel = url[len("/files/") :]
		if rel in yedekteki:
			continue
		try:
			if os.path.isfile(_live_path(rel)):
				fazla.append(rel)
		except frappe.ValidationError:
			continue
	fazla.sort()

	mevcut_kayitlar = set(
		frappe.get_all("File", filters={"name": ["in", [r.get("name") for r in kayitlar] or [""]]},
		               pluck="name", limit_page_length=0)
	)
	eksik_kayit = [r for r in kayitlar if r.get("name") and r["name"] not in mevcut_kayitlar]

	# Geri yükleme bunlara DOKUNMAYACAK (başka mağazanın yüklemesi). Planın
	# uygulamayla aynı şeyi söylemesi gerekiyor.
	kendi = _uploaded_urls(store)
	yazilamaz = sorted(
		d["path"] for d in m["files"] if d.get("file_url") not in kendi
	)
	# Karantina / tarama bekleyen dosyalar da geri yazılmayacak (TUR-125).
	taranmamis = sorted(
		d["path"]
		for d in m["files"]
		if d.get("file_url") in kendi and not _servis_edilebilir(d.get("file_url") or "")
	)

	return {
		"set_id": set_id,
		"created": m.get("created"),
		"ok": ok,
		"missing_file": eksik_dosya[:200],
		"missing_file_count": len(eksik_dosya),
		"conflict": catisma[:200],
		"conflict_count": len(catisma),
		"extra": fazla[:200],
		"extra_count": len(fazla),
		"missing_record": [
			{"name": r["name"], "file_url": r.get("file_url"), "file_name": r.get("file_name")}
			for r in eksik_kayit[:200]
		],
		"missing_record_count": len(eksik_kayit),
		"not_owned": yazilamaz[:200],
		"not_owned_count": len(yazilamaz),
		"unscanned": taranmamis[:200],
		"unscanned_count": len(taranmamis),
		"applied": False,
	}


def apply(
	store: str,
	set_id: str,
	*,
	files: bool = True,
	records: bool = True,
	overwrite: bool = False,
	only: list[str] | None = None,
) -> dict:
	"""Planı uygula. Hiçbir durumda dosya ya da kayıt SİLİNMEZ.

	`overwrite=False` (varsayılan): içeriği değişmiş dosyalara dokunulmaz —
	dosya optimize edilmiş ya da yenisiyle değiştirilmiş olabilir, yedekteki
	eski hâlini geri yazmak sessiz bir gerileme demektir.

	Kayıt kurma, satıcının kendi kaydıyla SINIRLI: `owner` mağazanın
	kullanıcılarından biri değilse dokunulmaz. Bu, paketi elle kurcalayıp
	başka kiracının kaydını enjekte etme yolunu kapatır.
	"""
	m = manifest_of(store, set_id)
	istenen = set(only or [])

	yazilan: list[str] = []
	uzerine: list[str] = []
	atlanan_catisma: list[str] = []
	atlanan_sahiplik: list[str] = []
	atlanan_tarama: list[str] = []

	if files:
		# Yazma yetkisi yalnız mağazanın YÜKLEDİĞİ dosyalarda. Paylaşılan bir
		# dosyayı geri yazmak başka kiracının sürümünü ezerdi (bkz.
		# `_uploaded_urls`). Küme bir kez hesaplanıyor: dosya başına sorgu
		# 2.800 dosyalık bir yedekte N+1 olurdu.
		kendi = _uploaded_urls(store)
		for d in m["files"]:
			if istenen and d["path"] not in istenen:
				continue
			if d.get("file_url") not in kendi:
				atlanan_sahiplik.append(d["path"])
				continue
			# Dosya yedek alındıktan SONRA karantinaya düşmüş olabilir. Blob'u
			# public ağaca geri yazmak, tarama sisteminin fiziksel olarak
			# çıkardığı bir dosyayı geri koyar ve karantinayı ETKİSİZ kılar —
			# üstelik kayıtlar hâlâ "karantinada" der, yani kimse fark etmez.
			# Geri yükleme bir güvenlik kararını geçersiz kılamaz.
			if not _servis_edilebilir(d.get("file_url") or ""):
				atlanan_tarama.append(d["path"])
				continue
			blob = _blob_path(store, d["hash"])
			if not os.path.isfile(blob):
				# Havuzda yoksa geri yüklenemez; `verify` bunu önceden söyler.
				continue

			canli = _live_path(d["path"])
			if os.path.isfile(canli):
				ayni = os.path.getsize(canli) == d["size"] and backup.file_hash(canli) == d["hash"]
				if ayni:
					continue
				if not overwrite:
					atlanan_catisma.append(d["path"])
					continue
				uzerine.append(d["path"])

			os.makedirs(os.path.dirname(canli), exist_ok=True)
			gecici = f"{canli}.restoring"
			shutil.copy2(blob, gecici)
			os.replace(gecici, canli)
			yazilan.append(d["path"])

	kurulan_kayit: list[str] = []
	if records:
		kurulan_kayit = _restore_records(store, set_id, istenen)

	frappe.db.commit()

	# Geri yazılan baytlar taramaya girer — platform geri yüklemesiyle aynı
	# gerekçe (`media/restore.py`), aynı kural (`av.rescan_after_write`).
	try:
		from tradehub_core.media import av as _av

		_av.rescan_after_write(
			[d.get("file_url") for d in m["files"] if d["path"] in set(yazilan)],
			reason="seller_restore",
		)
	except Exception:
		frappe.log_error(
			title=f"Satici yedegi: yeniden tarama kuyruklanamadi {set_id}",
			message=frappe.get_traceback(with_context=True),
		)

	from tradehub_core.media import audit

	audit.log_media_event(
		action=audit.ACTION_RESTORE,
		tenant=store,
		context={
			"set_id": set_id,
			"files_written": len(yazilan),
			"overwritten": len(uzerine),
			"conflicts_skipped": len(atlanan_catisma),
			"skipped_not_owned": len(atlanan_sahiplik),
			"skipped_unscanned": len(atlanan_tarama),
			"records_created": len(kurulan_kayit),
			"overwrite_allowed": bool(overwrite),
		},
	)

	return {
		"set_id": set_id,
		"files_written": len(yazilan),
		"overwritten": uzerine[:50],
		"overwritten_count": len(uzerine),
		"conflicts_skipped": atlanan_catisma[:50],
		"conflicts_skipped_count": len(atlanan_catisma),
		# Yedekte var ama mağazanın kendi yüklemesi değil: geri yazılmadı.
		# Sessizce atlamak "geri yükledim ama dosyam gelmedi" durumunu
		# açıklanamaz kılardı.
		"skipped_not_owned": atlanan_sahiplik[:50],
		"skipped_not_owned_count": len(atlanan_sahiplik),
		# Karantinada / tarama bekleyen: geri yazılmadı.
		"skipped_unscanned": atlanan_tarama[:50],
		"skipped_unscanned_count": len(atlanan_tarama),
		"records_created": len(kurulan_kayit),
		"applied": True,
	}


def _restore_records(store: str, set_id: str, istenen: set[str]) -> list[str]:
	"""Kaybolmuş `File` kayıtlarını geri kur — YALNIZ mağazanın kendi kayıtları.

	Dosya ile kayıt ayrı kaybolabiliyor: dosya silinip kayıt kalabilir (üründe
	kırık görsel), kayıt silinip dosya kalabilir (diskte sahipsiz dosya, satıcı
	kütüphanesinde görünmez). İkincisinin karşılığı burası.

	Üç koruma var:
      1. Kayıt yedeğin `records.json`'ından geliyor — satıcı gövde gönderemiyor.
      2. `owner` mağazanın kullanıcılarından biri olmalı.
      3. Aynı adla kayıt zaten varsa DOKUNULMUYOR — mevcut veri ezilmez.
	"""
	kayitlar = records_of(store, set_id)
	if not kayitlar:
		return []

	kullanicilar = set(ownership.users_of(store))
	adlar = [r.get("name") for r in kayitlar if r.get("name")]
	mevcut = set(
		frappe.get_all("File", filters={"name": ["in", adlar or [""]]}, pluck="name",
		               limit_page_length=0)
	)

	kurulan: list[str] = []
	for r in kayitlar:
		ad = r.get("name")
		if not ad or ad in mevcut:
			continue
		if r.get("owner") not in kullanicilar:
			# Paket kurcalanmış ya da sahiplik değişmiş; başka kiracının kaydı
			# buradan kurulamaz.
			continue
		if istenen and (r.get("file_url") or "").split("/")[-1] not in istenen:
			continue
		try:
			doc = frappe.get_doc(
				{
					"doctype": "File",
					**{k: v for k, v in r.items() if v is not None},
				}
			)
			# Dosya zaten diskte; Frappe'nin yeniden yazmasına gerek yok.
			doc.flags.ignore_file_validate = True
			# Geri yükleme dosyayı yedekteki HÂLİYLE kuruyor. `after_insert`
			# zincirindeki video transcode kancası burada çalışırsa dosyayı
			# yeniden kodlayıp diskte EZER (bkz. restore.py'deki aynı gerekçe).
			doc.flags.th_skip_transcode = True
			doc.insert(ignore_permissions=True, set_name=ad)

			# Frappe kayıt eklerken `owner`'ı oturumdaki kullanıcıyla eziyor.
			# Sahiplik yükleyenden türediği için bu, geri yüklenen dosyayı
			# mağazadan koparır ve satıcı onu kütüphanesinde GÖREMEZ.
			geri_yaz = {alan: r[alan] for alan in ("owner", "creation") if r.get(alan)}
			if geri_yaz:
				frappe.db.set_value("File", ad, geri_yaz, update_modified=False)

			kurulan.append(ad)
		except Exception as e:
			frappe.log_error(
				title=f"Satici yedegi: kayit kurulamadi {ad}",
				message=f"{e}\n{frappe.get_traceback(with_context=True)}",
			)
	return kurulan


# --- silme / temizlik -------------------------------------------------------


def delete_set(store: str, set_id: str) -> dict:
	"""Bir yedeği sil. Son yedek silinemez — "yedeğim var" sanısıyla tek
	kopyayı kaybetmek en pahalı hata olurdu."""
	setler = list_sets(store)
	if len(setler) <= 1:
		frappe.throw(frappe._("Son yedek silinemez."))
	if set_id not in {s["set_id"] for s in setler}:
		frappe.throw(frappe._("Yedek bulunamadı: {0}").format(set_id))

	shutil.rmtree(_set_path(store, set_id), ignore_errors=True)
	temizlik = _collect_orphan_blobs(store)
	return {"deleted": set_id, **temizlik}


def prune(store: str, *, keep: int = 0) -> dict:
	"""En yeni `keep` yedeği tut, kalanları sil.

	Havuzdaki bir içerik ancak HİÇBİR yedek onu göstermiyorsa kalkar. Sayaç
	şart: paylaşılan içeriği erken silmek, kalan yedekleri sessizce bozardı.
	"""
	keep = keep or MAX_SETS_PER_STORE
	setler = list_sets(store)
	silinecek = setler[keep:]
	for s in silinecek:
		shutil.rmtree(_set_path(store, s["set_id"]), ignore_errors=True)
	temizlik = _collect_orphan_blobs(store) if silinecek else {"freed_bytes": 0, "removed_blobs": 0}
	return {"removed": len(silinecek), **temizlik}


def _collect_orphan_blobs(store: str) -> dict:
	"""Hiçbir yedeğin göstermediği içerikleri havuzdan kaldır."""
	kullanilan: set[str] = set()
	for s in list_sets(store):
		try:
			for d in manifest_of(store, s["set_id"])["files"]:
				kullanilan.add(d["hash"])
		except Exception:
			continue

	kok = os.path.join(_store_root(store), BLOBS)
	silinen = 0
	bayt = 0
	for dizin, _alt, dosyalar in os.walk(kok):
		for ad in dosyalar:
			if ad in kullanilan:
				continue
			yol = os.path.join(dizin, ad)
			try:
				bayt += os.path.getsize(yol)
				os.remove(yol)
				silinen += 1
			except OSError:
				continue
	return {"freed_bytes": bayt, "removed_blobs": silinen}
