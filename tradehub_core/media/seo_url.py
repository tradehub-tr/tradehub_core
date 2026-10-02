"""SEO'lu görsel adresi: `/files/<slug>-<kısa kod>[__türev].<uzantı>`.

Spec: docs/superpowers/specs/2026-09-28-seo-gorsel-adresi-design.md

Disk ve DB kayıtları içerik-kodlu (`/files/xx/<sha256[:32]>.ext`) kalır; okunur
adres yalnız API çıktısında üretilir, `SeoImageRenderer` geri çözer. Kısa kod
`File.seo_code`'da tutulur: 8 hex, başka FARKLI dosya aynı kodu kullanıyorsa 12/16/32.
"""

from __future__ import annotations

import mimetypes
import os
import re

import frappe

# `frappe.utils` gibi alt modüller BİLEREK fonksiyon içinde içe aktarılıyor: bu modül
# api/* üzerinden, `frappe`'yi minimal bir stub'la değiştiren sözleşme testlerinde de
# yükleniyor (ör. tests/test_favorites_listing_summary.py) — modül düzeyi import onları kırar.
from tradehub_core.seo.slugify import slugify_tr

HASHED_RE = re.compile(r"^/files/([0-9a-f]{2})/([0-9a-f]{32})((?:__[a-z0-9]+)?)\.([a-z0-9]+)\Z")
# `\Z` (review M-1): `$` sondaki `\n`'den önce de eşleşir; `…jpg%0A` isteği de çözülürdü.
SEO_RE = re.compile(r"^/?files/([a-z0-9-]+)-([0-9a-f]{8,32})((?:__[a-z0-9]+)?)\.([a-z0-9]+)\Z")
SLUG_MAX = 60
CODE_LENGTHS = (8, 12, 16, 32)
FALLBACK_SLUG = "gorsel"

# Çarpışma kontrolü SADECE gerçek içerik-adresli (hash'li) satırlara bakar
# (review I-2). Retro-rename rollback'i eski adrese dönen satırın `seo_code`'unu
# temizler (`retro_rename._rollback_one`), ama elle set edilmiş ya da temizliği
# kaçırmış bir eski satır aynı 8 karakteri taşısa bile bu regex'e uymadığı için
# yeni bir atamayı BLOKE EDEMEZ. `%s` parametre olarak bağlanır — MySQL string
# escaping'i burada gerekmiyor (SQL metnine gömülmüyor).
_HASHED_SHAPE_SQL_RE = r"^/files/[0-9a-f]{2}/[0-9a-f]{32}\."

# Final review I-1: okunur adres YALNIZ ürün görseli biçimli dosyalar içindir (spec §2/§3).
# Belge (pdf/txt), video (mp4/webm), tif vb. ne kod alır ne okunur adresle servis edilir.
GORSEL_UZANTILAR: frozenset[str] = frozenset({"jpg", "jpeg", "png", "webp", "avif", "gif"})
# SQL tarafı aynı listenin regex hâli (patch backfill + temizlik).
GORSEL_UZANTI_SQL_RE = r"\.(jpg|jpeg|png|webp|avif|gif)$"

# Final review I-1: bu doctype'lara bağlı (ya da bunların dosya alanında adı geçen)
# içerik okunur adresle ASLA servis edilmez. `presets.EXCLUDED_DOCTYPES` (KYB/KYC,
# Order, Payment Transaction…) + fatura doctype'ları; tembel okunur (stub-güvenli).
_EK_HASSAS_DOCTYPES: tuple[str, ...] = ("Sales Invoice", "Purchase Invoice", "Payment Entry")

# Final review I-2: site_config bayrağı. `0` → API'ler okunur adres ÜRETMEZ (saklanan
# adres aynen döner). Renderer bayraktan BAĞIMSIZ çalışmaya devam eder: dışarıda
# (Google, CDN, favoriler, SW önbelleği) duran okunur adresler kırılmamalı (review M-8).
# Anahtar yoksa KAPALI (güvenli varsayılan): alpha/prod'da bilinçli açılır.
BAYRAK = "seo_image_urls"

HASSAS_CACHE_PREFIX = "tradehub:seo_hassas:"
HASSAS_CACHE_TTL = 3600
# M-4: `codes_for` sorgu başına en çok bu kadar `like` koşulu.
CODES_CHUNK = 500


def acik_mi() -> bool:
	"""`seo_image_urls` site_config bayrağı (yoksa kapalı)."""
	conf = getattr(frappe, "conf", None) or {}
	try:
		return bool(int(conf.get(BAYRAK) or 0))
	except (TypeError, ValueError):
		return False


def hassas_doctypes() -> tuple[str, ...]:
	from tradehub_core.media.presets import EXCLUDED_DOCTYPES

	return tuple(dict.fromkeys((*EXCLUDED_DOCTYPES, *_EK_HASSAS_DOCTYPES)))


def _kolon_eksik_mi(e: Exception) -> bool:
	"""Review M-9: kod `seo_code` sütunundan (patch 61) önce trafiğe çıkabilir."""
	try:
		return bool(frappe.db.is_missing_column(e))
	except Exception:
		return False


def make_slug(title: str | None) -> str:
	s = slugify_tr(title or "")
	if len(s) > SLUG_MAX:
		kesik = s[:SLUG_MAX]
		s = kesik.rsplit("-", 1)[0] if "-" in kesik else kesik
	return s.strip("-") or FALLBACK_SLUG


def _hash_of(file_url: str | None) -> re.Match | None:
	return HASHED_RE.match((file_url or "").split("?")[0])


def _like(h32: str) -> str:
	return f"/files/{h32[:2]}/{h32}.%"


def _write_code(h32: str, kod: str, only_name: str | None) -> None:
	"""Kodu yaz.

	`only_name` verilirse SADECE o `File` satırına yazılır — tek satır UPDATE,
	tek satır kilidi (review I-1). Verilmezse aynı hash'e sahip TÜM satırlara
	toplu yazılır: bu yol `patches/v15_9_61_file_seo_code.py` ve
	`retro_rename.rename_one` tarafından kullanılıyor, ikisi de tek-thread /
	iş-kilidi garantili bağlamda çalışıyor, çapraz-transaction deadlock riski
	`after_insert` kancasındaki gibi değil.
	"""
	if only_name:
		frappe.db.set_value("File", only_name, "seo_code", kod, update_modified=False)
	else:
		frappe.db.sql("update `tabFile` set seo_code=%s where file_url like %s", (kod, _like(h32)))


def assign_code(file_url: str, *, only_name: str | None = None) -> str | None:
	"""Kodu yoksa ata ve yaz; varsa aynen döndür — ve (review M-2) döndürülen
	kodu, hâlâ kodsuz kalmış satırlara da yaz.

	`only_name` verilirse yazma TEK `File` satırına indirgenir. Gerekçe
	(review I-1): `after_insert` kancası aynı içerik için eşzamanlı iki INSERT
	görürse ve her ikisi de `file_url LIKE ...` ile TÜM eşleşen satırları
	güncelleyen bir UPDATE çalıştırırsa, InnoDB bu iki transaction'ı karşılıklı
	kilitleyip birini rollback'e zorlayabilir — bare `except` bunu yutarsa
	upload isteği DB'de hiç var olmayan bir `File` doc'u döndürür. Tek satırlık
	UPDATE bu çakışmayı ortadan kaldırır; okuma (varolan kod / çarpışma kontrolü)
	zaten kilitsiz bir SELECT.
	"""
	m = _hash_of(file_url)
	if not m or m.group(3):  # türev kendi kodunu almaz, orijinalinkini kullanır
		return None
	if m.group(4) not in GORSEL_UZANTILAR:  # final review I-1: yalnız görsel
		return None
	h32 = m.group(2)
	kod = frappe.db.get_value(
		"File", {"file_url": ["like", _like(h32)], "seo_code": ["is", "set"]}, "seo_code"
	)
	if not kod:
		for n in CODE_LENGTHS:
			aday = h32[:n]
			cakisan = frappe.db.sql(
				"""select name from `tabFile`
					where seo_code=%s and file_url not like %s and file_url regexp %s
					limit 1""",
				(aday, _like(h32), _HASHED_SHAPE_SQL_RE),
			)
			if not cakisan:
				kod = aday
				break
		else:
			return None
	_write_code(h32, kod, only_name)
	return kod


def codes_for(file_urls: list[str]) -> dict[str, str]:
	"""`{hash32: kod}` — `file_url_index` üzerinde prefix range scan.

	Review M-1: önceki `substring(file_url,11,32) in (...)` biçimi hem
	`file_url_index` hem `seo_code_index`'i atlıyordu (hesaplanmış sütun ifade
	edilemez indexlenemez). Burada her hash için `file_url like '/files/xx/<h>.%'`
	koşulu OR'lanıyor — sabit önek olduğu için `file_url_index` üzerinde range
	scan çalışır.

	Final review M-4: sitemap parçası on binlerce hash getirebilir; tek dev OR
	listesi range optimizer bellek sınırını aşıp tam taramaya düşer. Hashler
	`CODES_CHUNK`'lık sorgulara bölünür (dönüş biçimi aynı).
	Final review M-9: `seo_code` sütunu henüz yoksa (kod migrate'ten önce
	yayında) boş sözlük döner → çağıranlar ham adres üretir, 500 yok.
	"""
	hashler = sorted({m.group(2) for u in file_urls if (m := _hash_of(u))})
	if not hashler:
		return {}
	sonuc: dict[str, str] = {}
	for i in range(0, len(hashler), CODES_CHUNK):
		parca = hashler[i : i + CODES_CHUNK]
		kosullar = " or ".join(["file_url like %s"] * len(parca))
		try:
			rows = frappe.db.sql(
				f"""select file_url, seo_code from `tabFile`
					where seo_code is not null and seo_code != '' and ({kosullar})""",
				[_like(h) for h in parca],
				as_dict=True,
			)
		except Exception as e:
			if _kolon_eksik_mi(e):
				return {}
			raise
		for r in rows:
			if m := HASHED_RE.match(r.file_url):
				sonuc[m.group(2)] = r.seo_code
	return sonuc


def seo_image_url(file_url: str | None, title: str | None, codes: dict[str, str] | None = None) -> str:
	m = _hash_of(file_url)
	if not m:
		return file_url or ""
	h32, turev, uzanti = m.group(2), m.group(3), m.group(4)
	# Final review I-2: bayrak kapalıysa saklanan adres AYNEN (kill switch).
	# Final review I-1: görsel olmayan uzantı okunur adres almaz.
	if not acik_mi() or uzanti not in GORSEL_UZANTILAR:
		return file_url or ""
	kod = (codes if codes is not None else codes_for([file_url])).get(h32)
	if not kod:
		return (file_url or "").split("?")[0]
	return f"/files/{make_slug(title)}-{kod}{turev}.{uzanti}"


def on_file_after_insert(doc, method=None) -> None:
	# Yükleme yolunu asla düşürmez: kod atanamazsa API bugünkü adresi verir.
	if getattr(doc.flags, "ignore_seo_code", False):
		return
	m = _hash_of(doc.file_url)
	if m:
		# Final review I-1: bu içerik yeni bir hassas kayda bağlanmış olabilir —
		# `resolve`'un hassaslık önbelleği hemen düşsün (1 saat beklemesin).
		frappe.cache.delete_value(_hassas_cache_key(m.group(2)))
	if getattr(doc, "is_private", 0) or getattr(doc, "attached_to_doctype", None) in hassas_doctypes():
		return
	try:
		assign_code(doc.file_url, only_name=doc.name)
	except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
		# Review I-1: kilit çakışması SESSİZCE YUTULMAZ. `frappe.db.sql` bir
		# InnoDB deadlock'unu/lock-wait-timeout'unu zaten bu iki tipe çeviriyor
		# (frappe/database/database.py) — burada yutarsak bu insert'in kendi
		# transaction'ı da rollback edilmiş olabilir, upload isteği DB'de hiç
		# var olmayan bir `File` doc'u döndürür. Doğru davranış: yukarı
		# fırlatmak (çağıran taraf/queue tekrar deneyebilir).
		raise
	except Exception:
		frappe.log_error(title="seo_code atanamadı", message=frappe.get_traceback())


OWNER_CACHE_PREFIX = "tradehub:seo_owner:"
OWNER_CACHE_TTL = 3600


def _owner_cache_key(file_url: str) -> str:
	return f"{OWNER_CACHE_PREFIX}{file_url}"


def owner_slugs(file_url: str) -> list[str]:
	"""Dosyayı kullanan ilanların slug'ları: birincil, galeri, varyant görseli.

	Sıra (review M-4): önce yayındaki (`Active`) ilanlar, sonra birincil → galeri →
	varyant, aynı grupta eski ilan önce. Eski slug'a gelen istek listedeki İLK slug'a
	301 alır — sıra belirleyici olmalı ki kanonik adres istekten isteğe oynamasın ve
	gizli bir ürünün başlığı kanonik olmasın. Taslak/pasif ilanın slug'ı yine KABUL
	edilir (listede kalır). Boş liste: dosya hiçbir ilana bağlı değil → her slug kabul.

	Önbellek (review I-1): üç kolon da indekssiz `text`; her önbelleksiz görsel
	isteğinde üç tablo taraması yerine sonuç `OWNER_CACHE_TTL` saniye tutulur.
	Listing kaydedilince/silinince `invalidate_owner_cache` ilgili anahtarları düşürür.
	Doğrudan SQL ile yapılan değişiklikler (retro-rename retarget) en geç TTL sonunda
	yansır — o arada en kötü durum: sahipsiz sayılıp her slug kabul edilir ya da bir
	saatlik eski kanonik 301 (ikisi de görseli kırmaz).
	"""
	anahtar = _owner_cache_key(file_url)
	# `expires=True`: Frappe aksi hâlde ıska (None) değerini istek-yerel önbelleğe yazar ve
	# aynı istekte az sonra yazılan TTL'li değer bir daha okunmaz.
	onbellek = frappe.cache.get_value(anahtar, expires=True)
	if onbellek is not None:
		return list(onbellek)
	basliklar = frappe.db.sql(
		"""select title from (
				select l.title, l.status, 0 as oncelik, l.creation from `tabListing` l
					where l.primary_image=%(u)s
				union all
				select l.title, l.status, 1, l.creation from `tabListing Image` li
					join `tabListing` l on l.name=li.parent
					where li.image=%(u)s and li.parenttype='Listing'
				union all
				select l.title, l.status, 2, l.creation from `tabListing Variant Item` lv
					join `tabListing` l on l.name=lv.parent
					where lv.variant_image=%(u)s and lv.parenttype='Listing'
			) t order by (status='Active') desc, oncelik, creation""",
		{"u": file_url},
		pluck=True,
	)
	sluglar = list(dict.fromkeys(make_slug(b) for b in basliklar if b))
	frappe.cache.set_value(anahtar, sluglar, expires_in_sec=OWNER_CACHE_TTL)
	return sluglar


def _listing_image_urls(doc) -> set[str]:
	urls = {doc.get("primary_image")}
	urls.update(r.get("image") for r in doc.get("listing_images") or [])
	urls.update(r.get("variant_image") for r in doc.get("variant_items") or [])
	return {(u or "").split("?")[0] for u in urls if u}


def invalidate_owner_cache(doc, method=None) -> None:
	"""Listing `after_insert` / `on_update` / `on_trash`: sahip-slug önbelleğini düşür.

	Hem şimdiki hem kayıt öncesi görseller: görselden çıkarılan ilan da o dosyanın
	sahip listesinden düşmeli. Yalnız hash'li adresler önbelleğe girer; diğerleri
	için silme ucuz ve zararsız.
	"""
	urls = _listing_image_urls(doc)
	onceki = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	if onceki:
		urls |= _listing_image_urls(onceki)
	for u in urls:
		if HASHED_RE.match(u):
			frappe.cache.delete_value(_owner_cache_key(u))


_YOK: dict = {"status": "yok", "disk_url": None, "canonical": None}


def resolve(path: str) -> dict:
	"""Okunur adresi diskteki içerik-adresli dosyaya çöz.

	Dönen `status`: `ok` (servis et), `slug_eski` (`canonical`'a 301), `yok` (404).
	Güvenlik: slug/kod/türev/uzantı yalnız `SEO_RE` gruplarından gelir ve SQL'e
	bağlı parametre olarak girer; disk yolu slug'dan DEĞİL, DB'de bulunan hash +
	regex'ten geçmiş türev/uzantıdan kurulur.
	"""
	m = SEO_RE.match((path or "").split("?")[0])
	if not m:
		return dict(_YOK)
	slug, kod, turev, uzanti = m.groups()
	if uzanti not in GORSEL_UZANTILAR:
		# Final review I-1: yalnız görsel; belge/video kodu olsa bile 404.
		return dict(_YOK)
	try:
		urls = frappe.get_all("File", filters={"seo_code": kod}, pluck="file_url", distinct=True)
	except Exception as e:
		if _kolon_eksik_mi(e):  # review M-9: sütun henüz yok → çözülemez
			return dict(_YOK)
		raise
	adaylar = [a for u in set(urls) if (a := HASHED_RE.match(u or "")) and not a.group(3)]
	if len({a.group(2) for a in adaylar}) != 1:
		# Kod tanınmıyor ya da (olmaması gereken) iki farklı içerikte → belirsiz, 404.
		return dict(_YOK)
	h32 = adaylar[0].group(2)
	if turev:
		asil = sorted(a.group(0) for a in adaylar)[0]
	else:
		# Aynı içerik farklı uzantıyla iki kez yüklenmiş olabilir; istenen uzantı seçilir.
		eslesen = [a.group(0) for a in adaylar if a.group(4) == uzanti]
		if not eslesen:
			return dict(_YOK)
		asil = eslesen[0]
	if hassas_mi(h32):
		return dict(_YOK)
	from frappe.utils import get_files_path

	dosya_adi = f"{h32}{turev}.{uzanti}"
	if not os.path.isfile(os.path.join(get_files_path(is_private=0), h32[:2], dosya_adi)):
		return dict(_YOK)
	disk_url = f"/files/{h32[:2]}/{dosya_adi}"
	sluglar = owner_slugs(asil)
	if sluglar and slug not in sluglar:
		return {
			"status": "slug_eski",
			"disk_url": disk_url,
			"canonical": f"/files/{sluglar[0]}-{kod}{turev}.{uzanti}",
		}
	return {"status": "ok", "disk_url": disk_url, "canonical": None}


def resolve_retired_code(path: str) -> str | None:
	"""`resolve()` "yok" dönünce son çare: kod, kare/retro-rename'in TAŞIDIĞI
	bir dosyanın eski adresine mi aitti (I6, fix round 1).

	Kısa kod (`assign_code`) her zaman içerik-adresli adresin hash'inin bir
	ÖNEKİYDİ. Kare dönüşümü eski `File` satırının `seo_code`'unu temizliyor
	(`kare._uygula`) — yani `resolve()` artık kodu bulamaz ve alpha'da halihazırda
	yayınlanmış okunur adres (arama motoru, favoriler, SW önbelleği) 404'e düşer.
	Burada o eski içerik-adresli adresi `Media URL Redirect.source_url` üzerinden
	arıyoruz (`/files/<kod[:2]>/<kod>...`): süresi dolmamış TAM OLARAK BİR eşleşme
	varsa yeni dosyanın okunur (ya da bulunamazsa hash'li) adresine 301 verilir.
	Sıfır ya da birden fazla eşleşme belirsizdir — çağıran 404'e düşer.

	Türevler (`__w384` gibi) bu asgari köprünün kapsamı dışında: kare hiçbir
	zaman türev üretmiyor, dolayısıyla "eski türevin yeni türevi" sorusu burada
	yok — kapsamı minimal tutmak için atlanır.
	"""
	from frappe.utils import now_datetime

	m = SEO_RE.match((path or "").split("?")[0])
	if not m:
		return None
	slug, kod, turev, uzanti = m.groups()
	if turev or uzanti not in GORSEL_UZANTILAR:
		return None
	desen = f"/files/{kod[:2]}/{kod}%"
	satirlar = frappe.get_all(
		"Media URL Redirect",
		filters={"source_url": ["like", desen], "expires_at": (">", now_datetime())},
		fields=["target_url"],
	)
	if len(satirlar) != 1:
		return None
	return seo_image_url(satirlar[0].target_url, slug)


def _hassas_cache_key(h32: str) -> str:
	return f"{HASSAS_CACHE_PREFIX}{h32}"


def hassas_mi(h32: str) -> bool:
	"""Bu içerik (hash) hassas bir kayda ait mi — final review I-1.

	Üç yol (`media/access_level._is_protected_pii` + `runner._has_sensitive_twin` ile
	aynı mantık): aynı hash'li public/private `File` satırlarından biri private ya da
	hassas doctype'a bağlı; aynı `content_hash`'li bir ikiz private/hassas; ya da
	adres hassas bir doctype'ın dosya alanında (ör. `Order.receipt_url`,
	`attached_to_*` boş yüklenen dekontlar) geçiyor. Kolonların bir kısmı indekssiz;
	sonuç hash başına `HASSAS_CACHE_TTL` saniye önbellekte. Yeni `File` eklenince
	(`on_file_after_insert`) anahtar düşer. Hata olursa güvenli taraf: hassas say.
	"""
	anahtar = _hassas_cache_key(h32)
	onbellek = frappe.cache.get_value(anahtar, expires=True)
	if onbellek is not None:
		return bool(onbellek)
	try:
		sonuc = _hassas_hesapla(h32)
	except Exception:
		frappe.log_error(title="seo hassaslık kontrolü", message=frappe.get_traceback())
		return True
	frappe.cache.set_value(anahtar, int(sonuc), expires_in_sec=HASSAS_CACHE_TTL)
	return sonuc


def _hassas_hesapla(h32: str) -> bool:
	from tradehub_core.media.presets import EXCLUDED_MEDIA_FIELDS

	hassas = hassas_doctypes()
	satirlar = frappe.db.sql(
		"""select file_url, is_private, attached_to_doctype, content_hash from `tabFile`
			where file_url like %s or file_url like %s""",
		(_like(h32), "/private" + _like(h32)),
		as_dict=True,
	)
	if any(r.is_private or r.attached_to_doctype in hassas for r in satirlar):
		return True
	hashler = sorted({r.content_hash for r in satirlar if r.content_hash})
	if hashler and frappe.db.sql(
		"""select 1 from `tabFile` where content_hash in %s
			and (is_private=1 or attached_to_doctype in %s) limit 1""",
		(tuple(hashler), hassas),
	):
		return True
	adresler = sorted({r.file_url for r in satirlar if r.file_url})
	if not adresler:
		return False
	for doctype, alanlar in EXCLUDED_MEDIA_FIELDS.items():
		if not frappe.db.table_exists(doctype):
			continue
		for alan in alanlar:
			if frappe.db.exists(doctype, {alan: ["in", adresler]}):
				return True
	return False


# `mimetypes` tablosu platforma göre eksik olabiliyor (eski imajlarda webp/avif yok).
_EK_MIME: dict[str, str] = {"webp": "image/webp", "avif": "image/avif", "jfif": "image/jpeg"}


def mime_of(disk_url: str) -> str:
	uzanti = disk_url.rsplit(".", 1)[-1].lower()
	return _EK_MIME.get(uzanti) or mimetypes.guess_type(disk_url)[0] or "application/octet-stream"
