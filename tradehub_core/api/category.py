import json
import re

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Max

from tradehub_core.seo.i18n import CONTENT_LANGS, normalize_lang, resolve_content_field
from tradehub_core.utils.content_i18n import apply_translation_payload


def _slugify(text):
	"""Türkçe karakterleri dönüştürüp URL slug üretir."""
	tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")
	text = text.translate(tr_map).lower()
	text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
	return text


# ──────────────────────────── Public ──────────────────────────────────────────

# Mega menü sonucu önbelleği (MOGEM-638 §4.4 / §6 deney 1). Uç nokta storefront'ta
# her sayfada çağrılıyor ve 7.561 kategorilik ağacı her istekte Python'da kuruyordu:
# p50 159 ms, 10 kullanıcıda 2 s, 5 istek/sn tavan. Deneyde önbellekle p50 5 ms.
# Anahtar hesaplamayı etkileyen ÜÇ girdiyi taşır (dil, include_empty, hide_empty
# ayarı) — ayar değişince anahtar değişir, ayrıca temizlik gerekmez. Kategori ve
# (hide_empty açıkken) Listing yazımları `invalidate_mega_menu_cache` ile düşürür.
_MEGA_MENU_CACHE_PREFIX = "mega_menu:"
_MEGA_MENU_TTL_SECONDS = 300


def _mega_menu_cache_key(lang: str, include_empty: bool, hide_empty: bool) -> str:
	return f"{_MEGA_MENU_CACHE_PREFIX}{lang}:{int(include_empty)}:{int(hide_empty)}"


def invalidate_mega_menu_cache(doc=None, method=None):
	"""Tüm dil/ayar varyantlarını düşür. Kategori yazımından (invalidate_category_cache)
	ve hide_empty açıkken Listing yazımından (invalidate_listing_cache) çağrılır."""
	try:
		frappe.cache.delete_keys(f"{_MEGA_MENU_CACHE_PREFIX}*")
	except Exception:
		# best-effort: önbellek temizliği bir doc kaydını asla düşürmemeli
		frappe.log_error("Mega menü önbelleği temizlenemedi", "category")


@frappe.whitelist(allow_guest=True)
def get_mega_menu(lang="tr", include_empty=0):
	"""
	Mega menu için kategori ağacını 3 seviyeye kadar nested döndürür.
	"Marketplace" gibi tek bir virtual root varsa onun çocukları döndürülür.
	Yaprak (3. seviye) yoksa `children` boş kalır — 2 seviyeli veriyle uyumlu.
	Returns: [{ id, name, slug, children: [
	            { id, name, slug, children: [{ id, name, slug }] } ] }]

	`lang`: içerik dili (tr/en/ar/ru); kategori adları o dile çözülür, eksikse
	kaydın content_default_lang'ine fallback eder.

	Sonuç 300 sn Redis'te tutulur (bkz. `_MEGA_MENU_CACHE_PREFIX`).
	"""
	lang = normalize_lang(lang)

	# Ayar okuması önbellek anahtarına girdiği için ağaç sorgusundan ÖNCE yapılır.
	if frappe.utils.cint(include_empty):
		hide_empty = False
	else:
		_setting = frappe.db.get_single_value("Marketplace Settings", "hide_empty_categories")
		hide_empty = frappe.utils.cint(_setting) == 1

	cache_key = _mega_menu_cache_key(lang, bool(frappe.utils.cint(include_empty)), hide_empty)
	# `expires=True` şart: TTL'li anahtarda `get_value` bunsuz Redis ıskasını
	# `frappe.local.cache`'e None olarak yazar ve aynı süreçte bir daha Redis'e
	# bakmaz — set_value(expires_in_sec) ise yalnız Redis'e yazar. Ölçüldü
	# (2026-09-12): bunsuz sıcak çağrı 142 ms'de kaldı, isabet hiç olmadı.
	cached = frappe.cache.get_value(cache_key, expires=True)
	if cached is not None:
		return cached

	result = _build_mega_menu(lang, hide_empty)
	frappe.cache.set_value(cache_key, result, expires_in_sec=_MEGA_MENU_TTL_SECONDS)
	return result


def _build_mega_menu(lang: str, hide_empty: bool) -> list:
	"""Önbelleksiz ağaç kurulumu — `get_mega_menu`nun sorgu + kurulum kısmı."""
	cats = frappe.get_all(
		"Product Category",
		filters={"is_active": 1},
		fields=[
			"name",
			"category_name",
			"content_default_lang",
			*[f"category_name_{lng}" for lng in CONTENT_LANGS],
			"parent_product_category",
			"url_slug",
			"sort_order",
			"lft",
			"rgt",
			"image",
			"icon_class",
		],
		order_by="sort_order asc, lft asc",
	)

	def cat_name(c):
		return (
			resolve_content_field(c, "category_name", lang, c.get("content_default_lang")) or c.category_name
		)

	if not cats:
		return []

	active_ids = {c.name for c in cats}

	# Boş kategorileri ele: alt ağacında (kendisi dahil) hiç aktif Listing olmayan
	# kategoriler storefront mega menüde gösterilmez (dead-end önleme). NSM lft/rgt ile
	# bir kategori, aktif listing'i olan bir kategoriyi alt ağacında barındırıyorsa doludur.
	# Varsayılan: GİZLEME YOK (tüm aktif kategoriler görünür). Yalnız Administrator
	# Marketplace Settings'ten "Boş Kategorileri Gizle"yi açarsa boşlar elenir.
	# include_empty=1 query param'ı ayarı override eder (gösterir) — çözüm get_mega_menu'da.
	populated_lfts = []
	if hide_empty:
		populated_names = {
			r.product_category
			for r in frappe.get_all(
				"Listing",
				filters={"status": "Active"},
				fields=["product_category"],
				distinct=True,
				limit_page_length=0,
			)
			if r.product_category
		}
		if populated_names:
			populated_lfts = [
				d.lft
				for d in frappe.get_all(
					"Product Category",
					filters={"name": ["in", list(populated_names)]},
					fields=["lft"],
				)
				if d.get("lft") is not None
			]

	def has_listings(c):
		if not hide_empty:
			return True
		# NSM kurulmamışsa (lft/rgt yok) güvenli taraf: gizleme
		if c.get("lft") is None or c.get("rgt") is None:
			return True
		return any(c.lft <= dlft <= c.rgt for dlft in populated_lfts)

	# Virtual root'ları bul (parent'ı olmayan veya aktif olmayan)
	virtual_roots = [
		c for c in cats if not c.parent_product_category or c.parent_product_category not in active_ids
	]

	# Eğer tek bir virtual root varsa (ör: "Marketplace"), onun çocuklarını al
	if len(virtual_roots) == 1:
		top_parent = virtual_roots[0].name
		top_cats = [c for c in cats if c.parent_product_category == top_parent]
	else:
		top_cats = virtual_roots

	def _leaf(c):
		return {
			"id": c.name,
			"name": cat_name(c),
			"slug": c.url_slug or _slugify(c.category_name),
			"image": c.image or None,
		}

	result = []
	for top in top_cats:
		if not has_listings(top):
			continue
		groups = [c for c in cats if c.parent_product_category == top.name and has_listings(c)]
		result.append(
			{
				"id": top.name,
				"name": cat_name(top),
				"slug": top.url_slug or _slugify(top.category_name),
				"image": top.image or None,
				"icon_class": top.icon_class or None,
				"children": [
					{
						**_leaf(g),
						"children": [
							_leaf(leaf)
							for leaf in cats
							if leaf.parent_product_category == g.name and has_listings(leaf)
						],
					}
					for g in groups
				],
			}
		)

	return result


@frappe.whitelist(allow_guest=True)
def get_category_version() -> str:
	"""Kategori ağacının parmak izi — storefront cache-busting için.

	`get_mega_menu` storefront'ta IndexedDB'ye 24s persist ediliyor; admin'deki
	değişiklik yansımıyordu. Bu string client tarafında kategori cache anahtarına
	gömülür — değişince anahtar değişir, tanstack-query otomatik yeniden çeker.

	Hook'a gerek yok: değer read-side hesaplanır.
	- düzenleme → MAX(modified) değişir
	- ekleme/silme → COUNT değişir
	- "Boş Kategorileri Gizle" toggle → bayrak değişir

	`is_active=1` filtresi `get_mega_menu` içeriğiyle tutarlı (pasife alınan kök
	menüden düşer, sayım da düşmeli). Sınırlama: hide_empty AÇIKKEN bir Listing'in
	eklenmesi/çıkması versiyona girmez (Listing sayımı pahalı) — tazelik o durumda
	client'taki versiyon staleTime penceresine düşer; ayar şu an kapalı.
	"""
	PC = frappe.qb.DocType("Product Category")
	row = (
		frappe.qb.from_(PC)
		.select(Count(PC.name).as_("cnt"), Max(PC.modified).as_("last_mod"))
		.where(PC.is_active == 1)
	).run(as_dict=True)[0]
	hide_empty = frappe.db.get_single_value("Marketplace Settings", "hide_empty_categories") or "0"
	return f"{row.cnt}-{row.last_mod}-{hide_empty}"


@frappe.whitelist()
def get_category_admin_settings() -> dict:
	"""Kategori sistemi ayarları (admin panel toggle'ı için) — yalnızca Administrator."""
	if frappe.session.user != "Administrator":
		frappe.throw(_("Bu ayara yalnızca Administrator erişebilir"), frappe.PermissionError)
	return {
		"hide_empty_categories": frappe.utils.cint(
			frappe.db.get_single_value("Marketplace Settings", "hide_empty_categories")
		)
	}


@frappe.whitelist()
def set_hide_empty_categories(enabled: int = 0) -> dict:
	"""Boş kategori gizleme ayarını değiştir — yalnızca Administrator.

	`enabled`: 0/1 — truthy ise boş kategoriler storefront mega menüde ve üretici
	filtresinde gizlenir. Kategori sistemini yalnızca Administrator ayarlayabilir.
	"""
	if frappe.session.user != "Administrator":
		frappe.throw(_("Bu ayarı yalnızca Administrator değiştirebilir"), frappe.PermissionError)
	value = 1 if frappe.utils.cint(enabled) else 0
	frappe.db.set_single_value("Marketplace Settings", "hide_empty_categories", value)
	return {"hide_empty_categories": value}


# ──────────────────────────── Seller / Public ─────────────────────────────────


@frappe.whitelist()
def get_platform_category_tree(parent=None, lang: str = "tr"):
	"""
	Satıcıların ürün yüklerken platform kategorisi seçmesi için.
	Giriş yapmış herkes (satıcı dahil) çağırabilir; yalnızca aktif kategoriler döner.
	parent=None → kök kategoriler; parent=<id> → o kategorinin aktif çocukları.

	`lang`: içerik dili (tr/en/ar/ru); dönen `category_name` o dile çözülür, eksikse
	kaydın content_default_lang'ine, o da yoksa base TR alanına fallback eder. `name`
	(kategori ID'si) çeviriden etkilenmez — seçim/submit kaynak ID ile yapılır.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)

	lang = normalize_lang(lang)
	filters = {"is_active": 1}
	if parent:
		filters["parent_product_category"] = parent
	else:
		filters["parent_product_category"] = ["is", "not set"]

	cats = frappe.get_all(
		"Product Category",
		filters=filters,
		fields=[
			"name",
			"category_name",
			"content_default_lang",
			*[f"category_name_{lng}" for lng in CONTENT_LANGS],
			"parent_product_category",
			"url_slug",
			"sort_order",
			"image",
			"icon_class",
		],
		order_by="sort_order asc, lft asc",
	)
	for c in cats:
		c["category_name"] = (
			resolve_content_field(c, "category_name", lang, c.get("content_default_lang")) or c.category_name
		)
		c["child_count"] = frappe.db.count(
			"Product Category",
			{"parent_product_category": c.name, "is_active": 1},
		)
	return cats


@frappe.whitelist()
def search_platform_categories(query: str, limit: int = 20, lang: str = "tr"):
	"""Aktif platform kategorilerinde isim araması.

	Her sonuç için parent_path (breadcrumb) bilgisi de döner, kullanıcı
	"Pantolon" yazıp sonucu seçtiğinde "Tekstil › Erkek › Pantolon"
	yolunu görebilsin.

	`lang`: içerik dili (tr/en/ar/ru). Arama hem kaynak (TR) hem de seçilen dilin
	kolonunda yapılır (panel İngilizceyse "Pants" da eşleşsin); dönen isimler ve
	breadcrumb o dile çözülür.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)
	q = (query or "").strip()
	if len(q) < 2:
		return []
	try:
		lim = min(50, max(1, int(limit)))
	except (ValueError, TypeError):
		lim = 20

	lang = normalize_lang(lang)
	like = f"%{q}%"
	# Hem kaynak (base) hem aktif dil kolonunda ara — panel dili TR değilse
	# kullanıcı çevrilmiş ismi yazdığında da eşleşsin.
	filters = {"is_active": 1}
	or_filters = {"category_name": ["like", like], f"category_name_{lang}": ["like", like]}
	cats = frappe.get_all(
		"Product Category",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"category_name",
			"content_default_lang",
			*[f"category_name_{lng}" for lng in CONTENT_LANGS],
			"parent_product_category",
			"url_slug",
			"icon_class",
		],
		order_by="category_name asc",
		limit_page_length=lim,
	)
	# Her sonuç için kök'e kadar atalarının ismini topla (seçilen dile çözülmüş).
	for c in cats:
		path_names = []
		cursor = c.get("parent_product_category")
		# Cycle koruması — pratikte yok ama defensive.
		# Loop değişkeni `_` Frappe'nin i18n `_()` fonksiyonunu gölgelediği
		# için (F823: fonksiyon başında throw(_(...)) UnboundLocalError atar)
		# `_depth` kullanıyoruz.
		for _depth in range(20):
			if not cursor:
				break
			row = frappe.db.get_value(
				"Product Category",
				cursor,
				[
					"category_name",
					"content_default_lang",
					*[f"category_name_{lng}" for lng in CONTENT_LANGS],
					"parent_product_category",
				],
				as_dict=True,
			)
			if not row:
				break
			path_names.insert(
				0,
				resolve_content_field(row, "category_name", lang, row.get("content_default_lang"))
				or row["category_name"],
			)
			cursor = row.get("parent_product_category")
		c["path"] = " › ".join(path_names) if path_names else ""
		# Sonucun kendi adını da seçilen dile çöz (DISPLAY).
		c["category_name"] = (
			resolve_content_field(c, "category_name", lang, c.get("content_default_lang")) or c.category_name
		)
	return cats


@frappe.whitelist()
def get_category_ancestors(name, lang: str = "tr"):
	"""
	Verilen kategori ID'si için kök'e kadar tüm ata listesini döndürür.
	Satıcının seçtiği kategorinin tam yolunu (breadcrumb) göstermek için kullanılır.
	Döner: [{ name, category_name }, ...] — kökten yaprağa sıralı

	`lang`: içerik dili (tr/en/ar/ru); `category_name` o dile çözülür. `name`
	(kategori ID'si) çeviriden etkilenmez.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)

	lang = normalize_lang(lang)
	path = []
	current = name
	seen = set()
	while current and current not in seen:
		seen.add(current)
		row = frappe.db.get_value(
			"Product Category",
			current,
			[
				"name",
				"category_name",
				"content_default_lang",
				*[f"category_name_{lng}" for lng in CONTENT_LANGS],
				"parent_product_category",
			],
			as_dict=True,
		)
		if not row:
			break
		display_name = (
			resolve_content_field(row, "category_name", lang, row.get("content_default_lang"))
			or row.category_name
		)
		path.append({"name": row.name, "category_name": display_name})
		current = row.parent_product_category

	path.reverse()
	return path


# ──────────────────────────── Admin CRUD ──────────────────────────────────────


@frappe.whitelist()
def get_category_tree(parent=None):
	"""
	Admin panel için kategori ağacı.
	parent=None → kök kategoriler; parent=<id> → o kategorinin çocukları
	"""
	_require_admin()
	filters = {"parent_product_category": parent or ["is", "not set"]}
	cats = frappe.get_all(
		"Product Category",
		filters=filters,
		fields=[
			"name",
			"category_name",
			"content_default_lang",
			*[f"category_name_{lng}" for lng in CONTENT_LANGS],
			"parent_product_category",
			"is_active",
			"sort_order",
			"url_slug",
			"lft",
			"rgt",
		],
		order_by="sort_order asc, lft asc",
	)
	for c in cats:
		c["child_count"] = frappe.db.count("Product Category", {"parent_product_category": c.name})
		# Çeviri tamamlanmışlık göstergesi: adı dolu olan diller (panel rozeti için).
		dl = c.get("content_default_lang") or "tr"
		filled = []
		for lng in CONTENT_LANGS:
			value = (c.get(f"category_name_{lng}") or "").strip()
			if not value and lng == dl:
				value = (c.get("category_name") or "").strip()  # legacy base fallback
			if value:
				filled.append(lng)
		c["name_langs"] = filled
	return cats


@frappe.whitelist()
def get_category_translations():
	"""Çeviri workbench'i için TÜM kategoriler (düz liste) + dil-bazlı adlar.

	Her kategori için base `category_name`, `content_default_lang` ve
	`category_name_{tr/en/ar/ru}` değerleri ile dolu-dil listesi (`name_langs`) döner.
	Satır-içi düzenleme bu değerleri kullanır; kayıt `update_category` ile yapılır.
	"""
	_require_admin()
	cats = frappe.get_all(
		"Product Category",
		fields=[
			"name",
			"category_name",
			"content_default_lang",
			*[f"category_name_{lng}" for lng in CONTENT_LANGS],
		],
		order_by="lft asc",
	)
	for c in cats:
		dl = c.get("content_default_lang") or "tr"
		filled = []
		for lng in CONTENT_LANGS:
			value = (c.get(f"category_name_{lng}") or "").strip()
			if not value and lng == dl:
				value = (c.get("category_name") or "").strip()
			if value:
				filled.append(lng)
		c["name_langs"] = filled
	return cats


@frappe.whitelist()
def create_category(
	category_name,
	parent_id=None,
	sort_order=0,
	is_active=1,
	icon_class=None,
	url_slug=None,
	image=None,
	translations=None,
):
	_require_admin()
	import uuid

	ext_id = str(uuid.uuid4())
	base_slug = url_slug or _slugify(category_name)

	# Slug unique kontrolü — çakışırsa sona sayaç ekle
	slug = base_slug
	counter = 1
	while frappe.db.exists("Product Category", {"url_slug": slug}):
		slug = f"{base_slug}-{counter}"
		counter += 1

	doc = frappe.new_doc("Product Category")
	doc.external_id = ext_id
	doc.category_name = category_name
	doc.parent_product_category = parent_id or None
	doc.sort_order = int(sort_order)
	doc.is_active = int(is_active)
	doc.icon_class = icon_class or ""
	doc.url_slug = slug
	if image is not None:
		doc.image = image
	apply_translation_payload(doc, translations)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name, "external_id": ext_id, "url_slug": slug}


@frappe.whitelist()
def update_category(
	name,
	category_name=None,
	parent_id=None,
	sort_order=None,
	is_active=None,
	icon_class=None,
	url_slug=None,
	image=None,
	translations=None,
):
	_require_admin()
	doc = frappe.get_doc("Product Category", name)
	if category_name is not None:
		doc.category_name = category_name
	if parent_id is not None:
		doc.parent_product_category = parent_id or None
	if sort_order is not None:
		doc.sort_order = int(sort_order)
	if is_active is not None:
		doc.is_active = int(is_active)
	if icon_class is not None:
		doc.icon_class = icon_class
	if url_slug is not None:
		# Başka bir kategoride aynı slug var mı?
		existing = frappe.db.get_value("Product Category", {"url_slug": url_slug}, "name")
		if existing and existing != name:
			frappe.throw(_("Bu URL slug başka bir kategoride kullanılıyor: {0}").format(existing))
		doc.url_slug = url_slug
	if image is not None:
		doc.image = image
	apply_translation_payload(doc, translations)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True}


@frappe.whitelist()
def delete_category(name):
	_require_admin()
	child_count = frappe.db.count("Product Category", {"parent_product_category": name})
	if child_count > 0:
		frappe.throw(_("Bu kategorinin {0} alt kategorisi var. Önce onları silin.").format(child_count))
	frappe.delete_doc("Product Category", name, ignore_permissions=True)
	frappe.db.commit()
	return {"success": True}


def _delete_single(name):
	"""Tek bir kategoriyi linkleri görmezden gelerek kalıcı siler."""
	# force=1 + ignore_on_trash=True link/submit kontrollerini atlar (v15)
	frappe.delete_doc(
		"Product Category",
		name,
		force=1,
		ignore_permissions=True,
		ignore_on_trash=True,
		delete_permanently=True,
	)


def _delete_cascade(name):
	"""Verilen kategoriyi ve tüm alt ağacını yapraktan köke doğru siler."""
	children = frappe.get_all(
		"Product Category",
		filters={"parent_product_category": name},
		pluck="name",
	)
	for child in children:
		_delete_cascade(child)
	_delete_single(name)


@frappe.whitelist()
def bulk_delete_categories(names):
	"""
	Verilen kategori ID listesini ve alt ağaçlarını siler.
	names: JSON string veya liste — ["cat1", "cat2", ...]
	"""
	_require_admin()
	if isinstance(names, str):
		try:
			names = json.loads(names)
		except (ValueError, TypeError):
			frappe.throw(_("Geçersiz kategori listesi"))
	if not isinstance(names, list) or not names:
		frappe.throw(_("Silinecek kategori seçilmedi"))

	# Seçilenler arasında biri diğerinin alt öğesiyse sadece üst olanı sil
	# (çünkü cascade zaten alt ağacı götürecek)
	to_delete = set(names)
	remaining = []
	for name in to_delete:
		if not frappe.db.exists("Product Category", name):
			continue
		ancestor = frappe.db.get_value("Product Category", name, "parent_product_category")
		skip = False
		while ancestor:
			if ancestor in to_delete:
				skip = True
				break
			ancestor = frappe.db.get_value("Product Category", ancestor, "parent_product_category")
		if not skip:
			remaining.append(name)

	deleted = 0
	errors = []
	for name in remaining:
		try:
			_delete_cascade(name)
			frappe.db.commit()
			deleted += 1
		except Exception as e:
			frappe.db.rollback()
			errors.append(f"{name}: {str(e)[:120]}")

	return {"success": True, "deleted": deleted, "errors": errors[:5]}


@frappe.whitelist()
def delete_all_categories():
	"""Tüm Product Category kayıtlarını yapraktan köke doğru siler."""
	_require_admin()
	# lft desc sırası yapraklardan başlatır (NSM tree güvenliği)
	rows = frappe.get_all(
		"Product Category",
		fields=["name"],
		order_by="lft desc",
	)
	deleted = 0
	errors = []
	for r in rows:
		try:
			_delete_single(r.name)
			frappe.db.commit()
			deleted += 1
		except Exception as e:
			frappe.db.rollback()
			errors.append(f"{r.name}: {str(e)[:120]}")
	return {"success": True, "deleted": deleted, "errors": errors[:5]}


# ──────────────────────────── Import ──────────────────────────────────────────


@frappe.whitelist()
def import_categories(json_data):
	"""
	JSON formatındaki kategori ağacını içe aktarır.
	Format: [{ id, name, parent_id, ... }]
	Mevcut kategorilerin üzerine yazar (external_id eşleşmesiyle).
	"""
	_require_admin()

	if isinstance(json_data, str):
		try:
			items = json.loads(json_data)
		except (ValueError, TypeError):
			frappe.throw(_("Geçersiz JSON verisi"))
	else:
		items = json_data

	if not isinstance(items, list):
		frappe.throw(_("JSON bir liste olmalı"))

	# id → item mapping
	by_id = {item["id"]: item for item in items}

	# Root'u bul (parent_id=null)
	roots = [item for item in items if not item.get("parent_id")]
	if not roots:
		frappe.throw(_("Kök kategori bulunamadı (parent_id=null olan kayıt yok)"))

	# Mevcut external_id'leri çek
	existing = {
		row.external_id: row.name
		for row in frappe.get_all("Product Category", fields=["name", "external_id"])
		if row.external_id
	}

	inserted = 0
	updated = 0
	skipped = 0

	# Bulk: per-doc kategori cache invalidation'ını sustur; sonda tek sefer temizlenir.
	frappe.flags.in_category_import = True

	# BFS sırasıyla işle (parent'lar önce eklensin)
	from collections import deque

	queue = deque(roots)
	visited = set()

	while queue:
		item = queue.popleft()
		item_id = item["id"]

		if item_id in visited:
			continue
		visited.add(item_id)

		# Parent henüz işlenmediyse sona at
		parent_id = item.get("parent_id")
		if parent_id and parent_id not in visited and parent_id in by_id:
			queue.append(item)
			# Sonsuz döngüyü önle
			if len(visited) + len(queue) > len(items) * 2:
				skipped += 1
				continue
			continue

		# Frappe parent adı: parent'ın external_id'si = parent'ın name'i
		frappe_parent = parent_id if parent_id and parent_id in by_id else None

		cat_name = (item.get("name") or "").strip()
		if not cat_name:
			skipped += 1
			continue

		# url_slug: unique olması için UUID'nin ilk 8 karakterini ekle
		slug = _slugify(cat_name) + "-" + item_id[:8]

		if item_id in existing:
			# Güncelle
			try:
				doc = frappe.get_doc("Product Category", existing[item_id])
				doc.category_name = cat_name
				doc.parent_product_category = frappe_parent
				doc.url_slug = slug
				doc.is_active = 1
				doc.save(ignore_permissions=True)
				updated += 1
			except Exception:
				skipped += 1
		else:
			# Yeni ekle
			try:
				doc = frappe.new_doc("Product Category")
				doc.external_id = item_id
				doc.category_name = cat_name
				doc.parent_product_category = frappe_parent
				doc.url_slug = slug
				doc.is_active = 1
				doc.sort_order = 0
				doc.insert(ignore_permissions=True)
				existing[item_id] = doc.name
				inserted += 1
			except Exception as e:
				# log_error(title, message): title 140 char ile sinirli; uzun {e} mesajini
				# title'a koymak CharacterLengthExceededError ile tum import'u cokertiyordu.
				frappe.log_error(title="Category import", message=f"{item_id} / {cat_name}: {e}")
				skipped += 1

		# Çocukları kuyruğa ekle
		for child in items:
			if child.get("parent_id") == item_id and child["id"] not in visited:
				queue.append(child)

	frappe.db.commit()

	# NSM ağacını yeniden oluştur
	rebuild_warning = None
	try:
		frappe.utils.nestedset.rebuild_tree("Product Category", "parent_product_category")
		frappe.db.commit()
	except Exception as e:
		frappe.log_error(title="Category rebuild_tree", message=str(e))
		rebuild_warning = _(
			"Kategori ağacı yeniden oluşturulurken hata oluştu. Kategori sıralaması bozuk olabilir, lütfen sayfayı yenileyin."
		)

	# Bulk bitti: kategori-bağımlı storefront cache'lerini TEK sefer düş.
	frappe.flags.in_category_import = False
	from tradehub_core.api.listing import invalidate_listing_cache

	invalidate_listing_cache()

	result = {
		"inserted": inserted,
		"updated": updated,
		"skipped": skipped,
		"total": len(items),
	}
	if rebuild_warning:
		result["warning"] = rebuild_warning
	return result


# ──────────────────────────── Async Import ───────────────────────────────────


def _import_cache_key(job_key):
	return f"tradehub_category_import:{job_key}"


def _update_progress(job_key, **fields):
	key = _import_cache_key(job_key)
	current = frappe.cache.get_value(key) or {}
	current.update(fields)
	frappe.cache.set_value(key, current, expires_in_sec=3600)


def _run_category_import(json_str, job_key):
	"""
	Background worker: büyük kategori JSON'unu import eder.
	İlerleme cache'e yazılır, frontend polling ile okur.
	"""
	try:
		items = json.loads(json_str) if isinstance(json_str, str) else json_str
		total = len(items)

		# Bulk: per-doc kategori cache invalidation'ını sustur; sonda tek sefer temizlenir.
		frappe.flags.in_category_import = True

		# O(n) child index — eski kod her item için tüm listeyi tarıyordu
		children_by_parent = {}
		for item in items:
			children_by_parent.setdefault(item.get("parent_id"), []).append(item)

		by_id = {item["id"]: item for item in items}

		existing = {
			row.external_id: row.name
			for row in frappe.get_all("Product Category", fields=["name", "external_id"])
			if row.external_id
		}

		_update_progress(
			job_key,
			state="running",
			total=total,
			inserted=0,
			updated=0,
			skipped=0,
			processed=0,
		)

		from collections import deque

		queue = deque(children_by_parent.get(None, []))
		visited = set()
		inserted = updated = skipped = 0
		last_flush = 0

		while queue:
			item = queue.popleft()
			item_id = item["id"]
			if item_id in visited:
				continue
			visited.add(item_id)

			parent_id = item.get("parent_id")
			frappe_parent = parent_id if parent_id and parent_id in by_id else None
			cat_name = (item.get("name") or "").strip()

			if not cat_name:
				skipped += 1
			else:
				slug = _slugify(cat_name) + "-" + item_id[:8]
				try:
					if item_id in existing:
						doc = frappe.get_doc("Product Category", existing[item_id])
						doc.category_name = cat_name
						doc.parent_product_category = frappe_parent
						doc.url_slug = slug
						doc.is_active = 1
						doc.save(ignore_permissions=True)
						updated += 1
					else:
						doc = frappe.new_doc("Product Category")
						doc.external_id = item_id
						doc.category_name = cat_name
						doc.parent_product_category = frappe_parent
						doc.url_slug = slug
						doc.is_active = 1
						doc.sort_order = 0
						doc.insert(ignore_permissions=True)
						existing[item_id] = doc.name
						inserted += 1
				except Exception as e:
					# log_error(title, message): title 140 char ile sinirli; uzun mesaji
					# title'a koymak CharacterLengthExceededError ile tum import'u cokertiyordu.
					frappe.log_error(title="Category import", message=f"{item_id} / {cat_name}: {e}")
					skipped += 1

			for child in children_by_parent.get(item_id, []):
				if child["id"] not in visited:
					queue.append(child)

			processed = inserted + updated + skipped
			if processed - last_flush >= 100:
				frappe.db.commit()
				_update_progress(
					job_key,
					state="running",
					inserted=inserted,
					updated=updated,
					skipped=skipped,
					processed=processed,
					total=total,
				)
				last_flush = processed

		frappe.db.commit()

		warning = None
		try:
			frappe.utils.nestedset.rebuild_tree("Product Category", "parent_product_category")
			frappe.db.commit()
		except Exception as e:
			frappe.log_error(title="Category rebuild_tree", message=str(e))
			warning = _("Kategori ağacı yeniden oluşturulurken hata oluştu. Sıralama bozuk olabilir.")

		# Bulk bitti: kategori-bağımlı storefront cache'lerini TEK sefer düş.
		frappe.flags.in_category_import = False
		from tradehub_core.api.listing import invalidate_listing_cache

		invalidate_listing_cache()

		_update_progress(
			job_key,
			state="done",
			inserted=inserted,
			updated=updated,
			skipped=skipped,
			processed=total,
			total=total,
			warning=warning,
		)
	except Exception as e:
		frappe.log_error(title="Category async import", message=str(e))
		_update_progress(job_key, state="error", error=str(e)[:500])


@frappe.whitelist()
def start_category_import(json_data):
	"""JSON içe aktarmayı background job olarak başlatır ve job_key döner."""
	_require_admin()

	if isinstance(json_data, str):
		try:
			items = json.loads(json_data)
			json_str = json_data
		except (ValueError, TypeError):
			frappe.throw(_("Geçersiz JSON verisi"))
	else:
		items = json_data
		json_str = json.dumps(items)

	if not isinstance(items, list) or not items:
		frappe.throw(_("JSON bir liste olmalı ve boş olmamalı"))

	import uuid

	job_key = uuid.uuid4().hex[:16]

	_update_progress(
		job_key,
		state="queued",
		total=len(items),
		inserted=0,
		updated=0,
		skipped=0,
		processed=0,
	)

	frappe.enqueue(
		"tradehub_core.api.category._run_category_import",
		queue="long",
		timeout=1800,
		json_str=json_str,
		job_key=job_key,
	)

	return {"job_key": job_key, "total": len(items)}


@frappe.whitelist()
def get_category_import_status(job_key):
	"""Background import job'unun durumunu döner."""
	_require_admin()
	val = frappe.cache.get_value(_import_cache_key(job_key))
	if not val:
		return {"state": "not_found"}
	return val


# ──────────────────────────── Helper ──────────────────────────────────────────


def _require_admin():
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)
	roles = frappe.get_roles(user)
	if "System Manager" not in roles and user != "Administrator":
		frappe.throw(_("Bu işlem için yönetici yetkisi gerekiyor"), frappe.PermissionError)
