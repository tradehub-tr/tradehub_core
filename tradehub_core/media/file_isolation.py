"""Ö-2 — aynı `file_url`'i paylaşan `File` satırları üzerinden kiracı sızıntısını kapatır.

## Mekanizma (Frappe çekirdeği, bizim bug'ımız değil)

`frappe/core/doctype/file/utils.py::find_file_by_url` bir URL'e ait TÜM `File`
satırlarını çeker ve **herhangi biri** okunabilirse dosyayı verir::

	files = frappe.get_all("File", filters={"file_url": path}, fields="*")
	for file_data in files:
		file = frappe.get_doc(doctype="File", **file_data)
		if file.is_downloadable():
			return file

Sonra `frappe/utils/response.py::download_private_file` **satırın içeriğini
değil, URL'in kendisini** serve eder (`send_private_file(path)`). Yani izin
satır bazında, teslimat URL bazında verilir. Bir URL'de birden çok kiracının
satırı varsa, kiracılardan herhangi biri o URL'deki tek blob'u indirebilir.

Ölçüm (2026-08-19, `istoc.localhost`): 949 çok-satırlı URL, bunların 33'ü özel
ve birden çok sahipli, 29'u KYB/KYC/Order/Payment Transaction eki içeriyor.
**4 URL'de iki AYRI `content_hash` var** — yani satır↔içerik bağı fiilen
kopmuş; bir satırın izni, o satırın yüklediğinden BAŞKA bir belgeyi açıyor.

## Neden `has_permission` kancası TEK BAŞINA yetmez

`File.is_downloadable()` → `frappe.core.doctype.file.file.has_permission(...)`
**modül-seviyesi fonksiyonunu doğrudan** çağırır; `frappe.has_permission()`
üzerinden geçmediği için `hooks.py` → `has_permission` zinciri (yani
`has_controller_permissions`) bu yolda HİÇ çalışmaz. Kanca yalnız desk/ORM
yüzeyini kapatır, indirmeyi kapatmaz.

Bu yüzden asıl daraltma `override_doctype_class` ile File denetleyicisinin
`is_downloadable()` metodunda yapılır (bkz. `TenantIsolatedFile`); kanca
(`file_has_permission`) desk/ORM yüzeyi için savunma katmanı olarak eklenir.

## Kural — YALNIZ daraltır, asla genişletmez

`is_downloadable()` önce `super()` çağırır; Frappe'nin verdiği bir izni
kaldırabilir, vermediği bir izni veremez. Daraltma iki katmanlı:

  1. **Kimlik belgeleri** (`_PII_REFERENCE_DOCTYPES`): eki yalnız belgenin
     öznesi (`user`) ve o kullanıcının mağazasındaki kullanıcılar okur.
     Üçüncü taraf okuyucusu olan bir senaryo yoktur.
  2. **Diğer her şey**: çağıran bir mağazaya bağlıysa ve satır da BAŞKA bir
     mağazaya bağlanabiliyorsa reddet. Çağıran mağazaya bağlı değilse (alıcı,
     platform-dışı kullanıcı) ya da satır mağazaya bağlanamıyorsa kural
     uygulanmaz — Frappe'nin kararı geçerli kalır (meşru erişimi kırmamak için
     bilinçli fail-open).

Platform rolleri (`_is_platform_full_access`) ve `Administrator` muaftır;
public dosyalar hiç değerlendirilmez.
"""

import hashlib
import os

import frappe
from frappe.core.doctype.file.file import File
from frappe.utils import cint, get_files_path

# Belirsiz blob kontrolü (V2, aşağıda) için üst sınır: bunun üstündeki dosyada
# indirme yolunda hash hesaplamak kabul edilemez (video türevleri GB'lara çıkar).
_AMBIGUOUS_BLOB_MAX_BYTES = 64 * 1024 * 1024
_AMBIGUITY_CACHE_TTL = 300

# Kimlik/uyum belgeleri: eklerinin üçüncü-taraf okuyucusu YOKTUR. Bu doktipler
# için kural, çağıranın mağazası olup olmamasından bağımsız uygulanır.
_PII_REFERENCE_DOCTYPES: frozenset[str] = frozenset(
	{
		"KYB Verification",
		"KYC Verification",
		"Seller Verification",
		"Seller Application",
	}
)

# Referans doktipinin mağaza (Admin Seller Profile) alanı — meta taraması
# yerine açık harita: `Payment Transaction.seller` bir Data alanıdır ve
# `_resolve_seller_field_name` gibi meta-tabanlı çözümleyiciler Link olmayan
# alanlarda sessizce yanlış sonuç verebilir.
_TENANT_FIELD_BY_DOCTYPE: dict[str, str] = {
	"Order": "seller",
	"Payment Transaction": "seller",
	"Listing": "seller",
	"Seller Verification": "seller",
	"Media Asset": "owner_seller",
	"Seller Balance": "seller_profile",
	"Seller Gallery Image": "seller",
	"Seller Certification": "seller",
	"Seller Category": "seller",
	"Bulk Import Job": "seller",
}

# KARŞI-TARAF doktipleri: kaydın `seller` alanı kaydı OLUŞTURANIN mağazası
# değil, karşı taraftır (bkz. `utils/tenant.COUNTERPARTY_SELLER_DOCTYPES`).
# Bu kayıtlarda meşru okuyucu kümesi = satıcı mağazası ∪ {alıcı/soran/yorumcu}.
# Alıcı aynı zamanda BAŞKA bir mağazanın satıcısı olabilir (ölçümde 5 vaka:
# SEL-00014 kullanıcısı SEL-00016'dan alışveriş yapmış); yalnız mağaza
# karşılaştırması bu kullanıcının KENDİ dekontunu okumasını kırardı.
_PARTY_FIELDS_BY_DOCTYPE: dict[str, tuple[str, ...]] = {
	"Order": ("buyer",),
	"Payment Transaction": ("buyer",),
	"Order Dispute": ("buyer",),
	"Seller Inquiry": ("buyer", "replied_by"),
	"Listing Question": ("asker",),
	"Listing Review": ("reviewer_user",),
	"RFQ": ("buyer",),
}

# Referans doktipinin "özne kullanıcı" alanı (kimlik belgeleri).
_SUBJECT_FIELD_BY_DOCTYPE: dict[str, str] = {
	"KYB Verification": "user",
	"KYC Verification": "user",
	"Seller Application": "applicant_user",
}


def _seller_profile_of(user: str | None) -> str | None:
	"""Kullanıcının mağazası — `utils.tenant` kanonik resolver'ına delege.

	Lazy import: bu modül File denetleyicisi olarak yüklendiği için import
	zincirini olabildiğince kısa tutuyoruz (döngüsel import riski).
	"""
	if not user or user in ("Guest", "Administrator"):
		return None
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	return _get_seller_profile_for_user(user)


def _is_platform_role(user: str) -> bool:
	"""Platform tam-erişim rolü mü (System Manager, Marketplace Admin, ...)."""
	from tradehub_core.permissions import _is_platform_full_access

	return bool(_is_platform_full_access(user))


def _field_value(doctype: str, name: str, field: str) -> str | None:
	"""Tek alan okuması — doktipte alan yoksa/kayıt yoksa None.

	Meta kontrolü zorunlu: harita ile şema ayrışabilir (`Seller Application`
	örneği) ve doğrudan sorgu `Unknown column` ile PATLAR. Bu modül izin
	yolunda çalışıyor; burada bir istisna HER dosya indirmesini kırar.
	"""
	try:
		if not frappe.get_meta(doctype).has_field(field):
			return None
		return frappe.db.get_value(doctype, name, field)
	except (frappe.DoesNotExistError, frappe.PermissionError):
		# Doktip kaldırılmış ya da okunamıyor → kiracı çözülemedi say.
		frappe.clear_last_message()
		return None


def _reference_subject_user(doctype: str, name: str) -> str | None:
	"""Kimlik belgesinin öznesi olan kullanıcı — alan yoksa None."""
	field = _SUBJECT_FIELD_BY_DOCTYPE.get(doctype)
	if not field:
		return None
	# İzin katmanının kendisiyiz; izin kontrolü olmadan tek alan okunur.
	return _field_value(doctype, name, field)


def _reference_party_users(doctype: str, name: str) -> set[str]:
	"""Karşı-taraf kaydının mağaza DIŞI meşru okuyucuları (alıcı, soran, ...)."""
	fields = _PARTY_FIELDS_BY_DOCTYPE.get(doctype)
	if not fields:
		return set()
	return {v for v in (_field_value(doctype, name, f) for f in fields) if v}


def _reference_tenant(doctype: str, name: str) -> str | None:
	"""Referans belgenin ait olduğu mağaza — çözülemezse None."""
	if doctype == "Admin Seller Profile":
		return name

	field = _TENANT_FIELD_BY_DOCTYPE.get(doctype)
	if field:
		value = _field_value(doctype, name, field)
		# Data alanı (Payment Transaction.seller) profil adı DIŞINDA bir şey
		# taşıyor olabilir — Admin Seller Profile olarak doğrulanmadan
		# kiracı sayılmaz.
		if value and frappe.db.exists("Admin Seller Profile", value):
			return value

	subject = _reference_subject_user(doctype, name)
	if subject:
		return _seller_profile_of(subject)

	return None


def _row_tenant(doc) -> str | None:
	"""Bir `File` satırının bağlandığı mağaza — çözülemezse None.

	Sıra: bağlı belge → satırı yükleyen kullanıcının mağazası. Bağlı belge
	önce gelir, çünkü sızıntının konusu ekin AİT OLDUĞU belgedir; yükleyen
	admin/onboarding kullanıcısı olabilir (ölçümde 6 satırın sahibi
	`Administrator`).
	"""
	doctype = doc.get("attached_to_doctype")
	name = doc.get("attached_to_name")
	if doctype and name:
		tenant = _reference_tenant(doctype, name)
		if tenant:
			return tenant
	return _seller_profile_of(doc.get("owner"))


def is_tenant_readable(doc, user: str | None = None) -> bool:
	"""Frappe'nin `read` kararını kiracı ölçütüyle daraltır — yalnız REDDEDER.

	Args:
	    doc: `File` dokümanı (ya da `attached_to_*`/`owner`/`is_private`
	        anahtarlarını taşıyan dict).
	    user: Değerlendirilecek kullanıcı; boşsa oturum kullanıcısı.

	Returns:
	    True → daraltma yok (Frappe'nin kararı geçerli).
	    False → çapraz kiracı; erişim reddedilmeli.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		# Frappe zaten reddediyor; burada karar üretmeye gerek yok.
		return True
	if user == "Administrator" or _is_platform_role(user):
		return True
	if not cint(doc.get("is_private")):
		# Public dosyada kiracı sınırı yok — URL zaten herkese açık.
		return True

	doctype = doc.get("attached_to_doctype")
	name = doc.get("attached_to_name")
	caller_tenant = _seller_profile_of(user)

	# 1) Kimlik belgeleri — özne kullanıcı + onun mağazası dışında okuyucu yok.
	if doctype and name and doctype in _PII_REFERENCE_DOCTYPES:
		subject = _reference_subject_user(doctype, name)
		if subject:
			if subject == user:
				return True
			subject_tenant = _seller_profile_of(subject)
			return bool(subject_tenant and subject_tenant == caller_tenant)
		# Özne çözülemedi → 2. katmana düş.

	# 2) Karşı-taraf kayıtları — alıcı/soran kendi belgesini her zaman okur.
	# Bu kontrol mağaza karşılaştırmasından ÖNCE gelmeli: alıcı aynı zamanda
	# başka bir mağazanın satıcısı olabilir.
	if doctype and name and user in _reference_party_users(doctype, name):
		return True

	# 3) Genel kural — çağıran mağazaya bağlı değilse (alıcı, platform-dışı
	# kullanıcı) daraltma yapma; Frappe'nin bağlı-belge kontrolü geçerli kalsın.
	if not caller_tenant:
		return True

	row_tenant = _row_tenant(doc)
	if not row_tenant:
		# Satır hiçbir mağazaya bağlanamıyor (sistem dosyası, bağsız yükleme).
		# Fail-open: burada reddetmek meşru erişimi kırma riskini taşır.
		return True

	return row_tenant == caller_tenant


class TenantIsolatedFile(File):
	"""`override_doctype_class` → "File". Tek fark: `is_downloadable` daraltılır.

	`find_file_by_url` her aday satır için `frappe.get_doc(doctype="File", ...)`
	çağırır; denetleyici sınıf override'ı sayesinde o nesne BU sınıftır ve
	`is_downloadable()` çapraz kiracı satırlarında False döner. Böylece
	"satırlardan herhangi biri" mantığı "çağıranın kendi kiracısına ait bir
	satır" mantığına daralır.
	"""

	def is_downloadable(self) -> bool:
		if not super().is_downloadable():
			return False
		if not is_tenant_readable(self, frappe.session.user):
			return False
		if frappe.session.user == "Administrator" or _is_platform_role(frappe.session.user):
			return True
		# V2 — satır↔blob bağı kopuk URL'lerde yalnız içeriği eşleşen satır geçer.
		return blob_matches_row(self)


def file_has_permission(doc, ptype=None, user=None, debug=False):
	"""`hooks.py` → `has_permission["File"]`. **Asla True dönmez.**

	`frappe.permissions.has_controller_permissions` kanca listesini TERS sırada
	gezer ve ilk None-olmayan sonucu döndürür. `tradehub_core` frappe'den SONRA
	yüklendiği için burada True dönmek Frappe'nin kendi File kontrolünü
	tamamen atlatırdı — o yüzden yalnız `False` (reddet) veya `None`
	(devret) üretilir.

	Kapsam okuma yüzeyiyle sınırlı: yazma/silme yolları zaten bağlı belgenin
	write iznine bakıyor ve o belgeler kiracı kancalarıyla korunuyor; burada
	yazmayı da reddetmek medya hattının kendi akışlarını kırma riski taşır.
	"""
	if doc is None or ptype not in ("read", "select", "print", "email", "export", "share"):
		return None
	user = user or frappe.session.user
	if is_tenant_readable(doc, user):
		return None
	return False


# ---------------------------------------------------------------------------
# V2 — satır ↔ içerik bağının koptuğu URL'ler
# ---------------------------------------------------------------------------
# Yukarıdaki kiracı kuralı "B, A'nın SATIRINA ulaşamaz" der. Ama teslimat
# satırın içeriğini değil URL'i serve ediyor: B kendi satırı üzerinden de
# URL'deki tek blob'u alır. Ölçümde 33 özel çok-sahipli URL'in 4'ünde İKİ AYRI
# `content_hash` var (ör. 120840 vs 120877 bayt) — yani en az bir satırın
# `content_hash`'i diskteki blob'la UYUŞMUYOR. O satırın izni, sahibinin
# yüklediğinden BAŞKA bir kiracının belgesini açar.
#
# Kural: yalnız bu belirsiz URL'lerde satırın `content_hash`'i diskteki blob'un
# md5'iyle karşılaştırılır (Frappe `content_hash` = içeriğin md5'i). Belirsiz
# olmayan URL'de (vakaların ~%99'u) tek bir sayaç sorgusu çalışır ve o da
# 5 dakika cache'lenir.


def _url_is_ambiguous(file_url: str) -> bool:
	"""Bu URL'de birden çok içerik hash'i mi var (satır↔blob bağı kopuk mu)?"""
	cache_key = f"tradehub:file_url_ambiguous:{file_url}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached == "yes"

	distinct = frappe.db.sql(
		"""SELECT COUNT(DISTINCT `content_hash`) FROM `tabFile`
		   WHERE `file_url` = %s AND `content_hash` IS NOT NULL AND `content_hash` != ''""",
		file_url,
	)
	ambiguous = bool(distinct and distinct[0][0] and distinct[0][0] > 1)
	frappe.cache().set_value(cache_key, "yes" if ambiguous else "no", expires_in_sec=_AMBIGUITY_CACHE_TTL)
	return ambiguous


def _blob_hash(file_url: str) -> str | None:
	"""Diskteki blob'un md5'i — okunamıyorsa/çok büyükse None (karar verilemez)."""
	if not file_url.startswith("/private/files/"):
		return None
	relative = file_url.split("/private/files/", 1)[1]
	path = get_files_path(*relative.split("/"), is_private=1)
	try:
		if os.path.getsize(path) > _AMBIGUOUS_BLOB_MAX_BYTES:
			return None
		digest = hashlib.md5()
		with open(path, "rb") as handle:
			for chunk in iter(lambda: handle.read(1024 * 1024), b""):
				digest.update(chunk)
		return digest.hexdigest()
	except OSError:
		# Dosya yok / okunamıyor → karar verilemez, kiracı kuralı geçerli kalsın.
		return None


def blob_matches_row(doc) -> bool:
	"""Belirsiz URL'de satırın içeriği diskteki blob'la aynı mı?

	Belirsiz olmayan URL'de her zaman True (ek maliyet yok). Karar
	verilemeyen durumlarda (hash boş, dosya okunamıyor, boyut sınırı)
	fail-open — bu kural kiracı kuralının YERİNE değil, ÜSTÜNE gelir.
	"""
	file_url = doc.get("file_url")
	row_hash = doc.get("content_hash")
	if not file_url or not row_hash:
		return True
	if not _url_is_ambiguous(file_url):
		return True
	disk_hash = _blob_hash(file_url)
	if not disk_hash:
		return True
	return disk_hash == row_hash
