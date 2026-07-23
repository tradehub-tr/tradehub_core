"""Listing oluşturucu / güncelleyici — ECA hook'larıyla entegre.

`frappe.flags.in_bulk_import = True` runner tarafından set edildiğinden,
ECA Rule'lar `bulk_only` filter ile bu context'te tetiklenebilir.
"""

import re

import frappe
from frappe import _

from tradehub_core.bulk_import.image_matcher import normalize_sku_key

# canonical (regex_lib pattern target_field) → Listing DB field adı
_CANONICAL_TO_DB: dict[str, str] = {
	"sku": "seller_sku",
}

# Listing DB tarafında set edilebilen field'lar (canonical-translated sonrası)
WRITABLE_FIELDS: set[str] = {
	# Temel
	"title",
	"seller_sku",
	"short_description",
	"description",
	"tags",
	"barcode",
	# Marketplace alanları (T1)
	"currency",
	"condition",
	"stock_uom",
	"listing_type",
	"brand",
	"category",
	"product_category",
	"product_type",
	"product_family",
	"attribute_set",
	# Fiyat
	"base_price",
	"selling_price",
	"discount_percentage",
	"sample_price",
	# Envanter (T2)
	"stock_qty",
	"min_order_qty",
	"max_order_qty",
	"sell_in_moq_multiples",
	"low_stock_threshold",
	"track_inventory",
	"allow_backorders",
	# Medya
	"primary_image",
	"video_url",
	# Kargo (T2)
	"is_free_shipping",
	"shipping_weight",
	"weight",
	"ships_from_country",
	"ships_from_city",
	"handling_days",
	"country_of_origin",
}

UPSERT_PRESERVE_IF_EMPTY: set[str] = set(WRITABLE_FIELDS)

# TR sayı format normalize edilecek numeric alanlar
_NUMERIC_FIELDS: set[str] = {
	"base_price",
	"selling_price",
	"sample_price",
	"discount_percentage",
	"stock_qty",
	"min_order_qty",
	"max_order_qty",
	"low_stock_threshold",
	"shipping_weight",
	"weight",
	"handling_days",
}

# Frappe Check field'ları: 0/1'e çevrilecek
_BOOLEAN_FIELDS: set[str] = {
	"sell_in_moq_multiples",
	"track_inventory",
	"allow_backorders",
	"is_free_shipping",
}

# Link field → DocType eşleşmesi (xlsx'te değer varsa o DocType'ta lookup)
_LINK_FIELDS: dict[str, str] = {
	"stock_uom": "UOM",
	"brand": "Brand",
	"category": "Category",
	"product_category": "Product Category",
	"product_type": "Product Type",
	"product_family": "Product Family",
	"attribute_set": "Attribute Set",
	"ships_from_country": "Country",
	"country_of_origin": "Country",
}

# Frappe Country DocType İngilizce kayıtlı (~200 seed); Frappe UOM da öyle.
# Satıcı xlsx'te Türkçe yazınca alias üzerinden Link'e bağla.
_TR_COUNTRY_ALIASES: dict[str, str] = {
	"türkiye": "Turkey",
	"turkiye": "Turkey",
	"almanya": "Germany",
	"amerika": "United States",
	"abd": "United States",
	"ingiltere": "United Kingdom",
	"i̇ngiltere": "United Kingdom",
	"birleşik krallık": "United Kingdom",
	"fransa": "France",
	"italya": "Italy",
	"i̇talya": "Italy",
	"ispanya": "Spain",
	"i̇spanya": "Spain",
	"çin": "China",
	"japonya": "Japan",
	"güney kore": "South Korea",
	"rusya": "Russia",
	"yunanistan": "Greece",
	"bulgaristan": "Bulgaria",
	"romanya": "Romania",
	"iran": "Iran",
	"i̇ran": "Iran",
	"irak": "Iraq",
	"i̇rak": "Iraq",
	"suriye": "Syria",
	"birleşik arap emirlikleri": "United Arab Emirates",
	"bae": "United Arab Emirates",
	"suudi arabistan": "Saudi Arabia",
	"polonya": "Poland",
	"hollanda": "Netherlands",
	"belçika": "Belgium",
	"i̇sviçre": "Switzerland",
	"isviçre": "Switzerland",
	"avusturya": "Austria",
	"i̇sveç": "Sweden",
	"isveç": "Sweden",
	"norveç": "Norway",
	"danimarka": "Denmark",
	"finlandiya": "Finland",
}

_TR_UOM_ALIASES: dict[str, str] = {
	"adet": "Nos",
	"ad": "Nos",
	"adt": "Nos",
	# İngilizce şablon örneği "Piece" kullanır; ERPNext seed'inde countable UOM "Nos".
	"piece": "Nos",
	"pieces": "Nos",
	"pcs": "Nos",
	"pc": "Nos",
	"kg": "Kg",
	"kilogram": "Kg",
	"gram": "Gram",
	"gr": "Gram",
	"ton": "Tonne",
	"litre": "Litre",
	"lt": "Litre",
	"l": "Litre",
	"ml": "Mililitre",
	"mililitre": "Mililitre",
	"metre": "Meter",
	"m": "Meter",
	"cm": "Centimeter",
	"santimetre": "Centimeter",
	"mm": "Millimeter",
	"milimetre": "Millimeter",
	"m2": "Square Meter",
	"m³": "Cubic Meter",
	"m3": "Cubic Meter",
	"paket": "Box",
	"kutu": "Box",
	"koli": "Box",
	"set": "Set",
	"çift": "Pair",
	"saat": "Hour",
	"gün": "Day",
}

# Select field için izin verilen değerler (case-insensitive); normalize
# Listing.condition options (DocType): New / Used - Like New / Used - Good / Refurbished
_SELECT_FIELDS: dict[str, set[str]] = {
	"condition": {"New", "Used - Like New", "Used - Good", "Refurbished"},
}

# Satıcı xlsx'te Türkçe ("Yeni", "2. El", "Yenilenmiş" vb.) yazdığında otomatik
# İngilizce option'a çevir. _normalize_select önce alias map'e bakar.
_CONDITION_TR_ALIASES: dict[str, str] = {
	"yeni": "New",
	"new": "New",
	"sıfır": "New",
	"sifir": "New",
	"2. el": "Used - Like New",
	"2.el": "Used - Like New",
	"ikinci el": "Used - Like New",
	"i̇kinci el": "Used - Like New",
	"used - like new": "Used - Like New",
	"used like new": "Used - Like New",
	"iyi": "Used - Good",
	"used - good": "Used - Good",
	"used good": "Used - Good",
	"yenilenmiş": "Refurbished",
	"yenilenmis": "Refurbished",
	"refurbished": "Refurbished",
}

# xlsx'te yoksa create_listing default'u uygulasın
_DEFAULTS: dict[str, object] = {
	"currency": "TRY",  # Listing.currency reqd, schema default "USD" — TR marketplace için TRY
	"condition": "New",
}


def _normalize_numeric(value):
	"""TR (`1.245,00`) ve EN formatlı sayı string'lerini float'a çevir."""
	if value is None or value == "":
		return None
	if isinstance(value, int | float):
		return value
	s = str(value).strip()
	if not s:
		return None
	if "," in s and "." in s:
		if s.rfind(",") > s.rfind("."):
			s = s.replace(".", "").replace(",", ".")
		else:
			s = s.replace(",", "")
	elif "," in s:
		s = s.replace(",", ".")
	s = re.sub(r"[^\d.\-]", "", s)
	try:
		return float(s)
	except ValueError:
		return value


_TRUE_TOKENS = {"1", "true", "evet", "e", "var", "yes", "y", "on", "doğru", "dogru"}
_FALSE_TOKENS = {"0", "false", "hayır", "hayir", "h", "yok", "no", "n", "off", "yanlış", "yanlis"}


def _normalize_boolean(value):
	"""'Evet'/'Hayır'/'E'/'H'/'true'/'false'/'1'/'0' → 0|1."""
	if value is None or value == "":
		return None
	if isinstance(value, bool):
		return 1 if value else 0
	if isinstance(value, int | float):
		return 1 if value else 0
	s = str(value).strip().lower()
	if s in _TRUE_TOKENS:
		return 1
	if s in _FALSE_TOKENS:
		return 0
	return None  # tanınmayan → schema default uygulanır


def _resolve_link(doctype: str, raw_value):
	"""xlsx'teki etiket → Link DocType `name`. Yoksa None (schema default kalsın)."""
	if not raw_value:
		return None
	v = str(raw_value).strip()
	if not v:
		return None
	# Türkçe alias tablosu (Country/UOM seed İngilizce geliyor)
	lower = v.lower()
	if doctype == "Country" and lower in _TR_COUNTRY_ALIASES:
		v = _TR_COUNTRY_ALIASES[lower]
	elif doctype == "UOM" and lower in _TR_UOM_ALIASES:
		v = _TR_UOM_ALIASES[lower]
	# Doğrudan name eşleşmesi
	if frappe.db.exists(doctype, v):
		return v
	# Yaygın etiket field'larında ara
	for label_field in (f"{doctype.lower().replace(' ', '_')}_name", "label", "title"):
		try:
			match = frappe.db.get_value(doctype, {label_field: v}, "name")
			if match:
				return match
		except Exception:
			frappe.log_error(f"Failed to resolve link field for doctype={doctype} value={v!r}", "bulk_import.persister._resolve_link")
			continue
	return None


def _normalize_select(field: str, value):
	"""Select field değerini izin verilen set'e en yakın eşleşmeye çevir.

	condition için önce TR alias map'e bakılır (Yeni → New, Yenilenmiş → Refurbished
	vb.); böylece satıcı Türkçe yazdığında DocType'ın İngilizce option'larına
	otomatik eşlenir.
	"""
	if value is None or value == "":
		return None
	allowed = _SELECT_FIELDS.get(field, set())
	if not allowed:
		return value
	s = str(value).strip().lower()
	# TR → EN alias (condition için). TR locale "YENİ".lower() → "yeni̇" (combining
	# dot above) üretebilir; NFKD normalize + combining mark strip ile düz "yeni"
	# elde edip alias eşleşmesini garanti et.
	if field == "condition":
		import unicodedata

		s_norm = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
		aliased = _CONDITION_TR_ALIASES.get(s) or _CONDITION_TR_ALIASES.get(s_norm)
		if aliased and aliased in allowed:
			return aliased
	for opt in allowed:
		if opt.lower() == s:
			return opt
	return None


def _coerce_value(db_field: str, value):
	"""Tek bir DB field'ı için tür dönüşümü uygula."""
	if db_field in _NUMERIC_FIELDS:
		return _normalize_numeric(value)
	if db_field in _BOOLEAN_FIELDS:
		return _normalize_boolean(value)
	if db_field in _LINK_FIELDS:
		return _resolve_link(_LINK_FIELDS[db_field], value)
	if db_field in _SELECT_FIELDS:
		return _normalize_select(db_field, value)
	return value


# Mapping/template ürünü olan PIM kolon prefix'i. "attr:<attribute_code>" deseni
# download_template (api.py) tarafından üretilir; bu key'ler Listing field'ı değil,
# attribute_values child tablosuna satır olarak yazılır.
_ATTR_KEY_PREFIX = "attr:"


def _coerce_row(row_data: dict) -> dict:
	"""Canonical key → DB field translate + tür normalize.

	`attr:<code>` key'leri Listing DB field'ı değil child-row kaynağıdır; coerce
	dışında tutulur ve _apply_attribute_values tarafından ayrıca işlenir.
	"""
	out: dict = {}
	for key, value in row_data.items():
		if key.startswith(_ATTR_KEY_PREFIX):
			continue
		db_field = _CANONICAL_TO_DB.get(key, key)
		out[db_field] = _coerce_value(db_field, value)
	return out


def _apply_attribute_values(doc, row_data: dict, warnings: list[str] | None = None) -> None:
	"""`attr:<code>` key'lerini Listing.attribute_values child satırlarına çevir.

	Her geçerli `attr:<attribute_code>` için {attribute, attribute_value} satırı
	eklenir. Boş değerler atlanır. Product Attribute kaydı bulunamayan code'lar
	satır olarak yazılmaz; bunun yerine `warnings` listesine uyarı eklenir (runner
	bu uyarıyı satır-uyarısı mekanizmasıyla kaydeder).

	Product Attribute autoname `field:attribute_code` olduğundan name == code.
	Geçerli code'lar tek batch'le doğrulanır (loop içi DB call / N+1 yok).
	"""
	pairs: list[tuple[str, str]] = []
	for key, value in row_data.items():
		if not key.startswith(_ATTR_KEY_PREFIX):
			continue
		code = key[len(_ATTR_KEY_PREFIX) :].strip()
		if not code:
			continue
		val = "" if value is None else str(value).strip()
		if not val:
			continue
		pairs.append((code, val))

	if not pairs:
		return

	codes = list({code for code, _ in pairs})
	valid_codes = {
		r.name
		for r in frappe.get_all(
			"Product Attribute",
			filters={"name": ["in", codes]},
			fields=["name"],
		)
	}

	for code, val in pairs:
		if code not in valid_codes:
			if warnings is not None:
				warnings.append(_("Geçersiz öznitelik kodu, satır atlandı: {0}").format(code))
			continue
		doc.append("attribute_values", {"attribute": code, "attribute_value": val})


def _apply_defaults(doc) -> None:
	"""Boş bırakılan kritik alanlara default değer ata."""
	for field, default in _DEFAULTS.items():
		if not getattr(doc, field, None):
			setattr(doc, field, default)


def _attach_images(doc, listing_images: list[str]) -> None:
	"""İlki primary_image, kalanı listing_images child table'a."""
	if not listing_images:
		return
	doc.primary_image = listing_images[0]
	for i, img_url in enumerate(listing_images[1:], 1):
		doc.append("listing_images", {"image": img_url, "sort_order": i})


def create_listing(
	row_data: dict,
	seller_profile: str,
	job_name: str,
	listing_images: list[str] | None = None,
	warnings: list[str] | None = None,
) -> str:
	"""Yeni Listing oluştur. before_insert hook status=Pending yapar."""
	coerced = _coerce_row(row_data)
	doc = frappe.new_doc("Listing")
	for field, value in coerced.items():
		if field in WRITABLE_FIELDS and value is not None and value != "":
			setattr(doc, field, value)
	doc.seller_profile = seller_profile
	doc.created_by_bulk_job = job_name

	_apply_defaults(doc)

	# selling_price reqd=1; satıcı indirim vermediyse liste fiyatı satış fiyatıdır.
	if not doc.selling_price and doc.base_price:
		doc.selling_price = doc.base_price

	_attach_images(doc, listing_images or [])
	_apply_attribute_values(doc, row_data, warnings)

	# Bulk import güvenilir sunucu-içi işlem: satıcı kimliği doğrulanmış ve
	# seller_profile açıkça set edili (tenant izolasyonu korunur). Arka plan
	# işinde rol-bazlı "create" izni düşmesin diye ignore_permissions=True.
	doc.insert(ignore_permissions=True)
	return doc.name


def update_listing(
	existing_sku: str,
	row_data: dict,
	seller_profile: str,
	job_name: str,
	listing_images: list[str] | None = None,
	warnings: list[str] | None = None,
) -> tuple[str, list[str]]:
	"""Upsert modda mevcut Listing'i güncelle. Boş alanlar korunur."""
	name = frappe.db.get_value(
		"Listing",
		{"seller_sku": existing_sku, "seller_profile": seller_profile},
		"name",
	)
	if not name:
		frappe.throw(_("Listing bulunamadı: {0}").format(existing_sku))

	doc = frappe.get_doc("Listing", name)
	coerced = _coerce_row(row_data)
	changed: list[str] = []

	for field, value in coerced.items():
		if field not in WRITABLE_FIELDS:
			continue
		if value is None or value == "":
			continue
		if getattr(doc, field, None) != value:
			setattr(doc, field, value)
			changed.append(field)

	if listing_images:
		doc.set("listing_images", [])
		_attach_images(doc, listing_images)
		if "listing_images" not in changed:
			changed.append("listing_images")

	# attr:<code> kolonu geldiyse spec'leri yeniden kur (listing_images deseni gibi);
	# dolu attr kolonu yoksa mevcut attribute_values korunur.
	if any(k.startswith(_ATTR_KEY_PREFIX) and (v not in (None, "")) for k, v in row_data.items()):
		doc.set("attribute_values", [])
		_apply_attribute_values(doc, row_data, warnings)
		if "attribute_values" not in changed:
			changed.append("attribute_values")

	# Bulk import güvenilir sunucu-içi güncelleme (yukarıdaki create gerekçesi).
	doc.save(ignore_permissions=True)
	return doc.name, changed


def check_sku_exists(sku, seller_profile: str) -> bool:
	"""Satıcının verdiği stok kodu (seller_sku) bu satıcıda mevcut mu?"""
	if not sku:
		return False
	return bool(
		frappe.db.exists(
			"Listing",
			{"seller_sku": str(sku).strip(), "seller_profile": seller_profile},
		)
	)


# ─────────────────────────────────────────────────────────────────
# T8 — Varyant desteği
# ─────────────────────────────────────────────────────────────────


# Varyant ekseni canonical kolon çiftleri. download_template (api.py) statik
# olarak 1-3 ekseni üretir; 3+ eksen için axis_values_json (12'ye kadar) korunur.
# Bu liste hem axes_config hem child satır yazımı tarafından kullanılır.
_VARIANT_AXIS_KEYS: tuple[tuple[str, str], ...] = (
	("variant_axis_1_type", "variant_axis_1_value"),
	("variant_axis_2_type", "variant_axis_2_value"),
	("variant_axis_3_type", "variant_axis_3_value"),
)

# axis_values_json en fazla bu kadar ekseni tutar (storefront kombinasyon limiti).
_MAX_VARIANT_AXES = 12


def _extract_variant_axes(vrow: dict) -> list[tuple[str, str]]:
	"""Tek varyant satırından (type, value) eksen çiftlerini sırayla çıkar.

	1-3 eksen `variant_axis_N_type/value` canonical kolonlarından gelir; 3+ eksen
	için `axis:<type>` deseni (varsa) eklenir. Boş çiftler atlanır. En fazla
	_MAX_VARIANT_AXES çift döner.
	"""
	axes: list[tuple[str, str]] = []
	for type_key, value_key in _VARIANT_AXIS_KEYS:
		t = (vrow.get(type_key) or "").strip()
		v = (vrow.get(value_key) or "").strip()
		if t and v:
			axes.append((t, v))
	# 3+ eksen genişleme kapısı: axis:<type> kolonları (statik şablonda yok ama
	# özel mapping ile gelebilir) sıra korunarak eklenir.
	for key, raw in vrow.items():
		if not key.startswith("axis:"):
			continue
		t = key[len("axis:") :].strip()
		v = "" if raw is None else str(raw).strip()
		if t and v and (t, v) not in axes:
			axes.append((t, v))
	return axes[:_MAX_VARIANT_AXES]


def _build_variant_axes_config(variant_rows: list[dict]) -> str:
	"""variant_items rows'tan eksen tip → değer listesi JSON'u üret.

	Listing.variant_axes_config Long Text — storefront varyant seçimini bu
	JSON'a göre render eder. 1-3 eksen kolon çiftlerinden, 3+ eksen
	`axis:<type>` deseninden toplanır.
	Örnek çıktı: {"Renk": ["Kırmızı", "Mavi"], "Beden": ["S", "M", "L"]}
	"""
	import json

	axes: dict[str, list[str]] = {}
	for r in variant_rows:
		for t, v in _extract_variant_axes(r):
			axes.setdefault(t, [])
			if v not in axes[t]:
				axes[t].append(v)
	return json.dumps(axes, ensure_ascii=False)


def create_listing_with_variants(
	parent_row: dict,
	variant_rows: list[dict],
	seller_profile: str,
	job_name: str,
	images_idx: dict[str, list[str]] | None = None,
	warnings: list[str] | None = None,
) -> str:
	"""Varyantlı Listing oluştur: parent doc + variant_items child rows.

	parent_row: master ürün satırı (canonical keys; parent_sku boş, seller_sku dolu)
	variant_rows: her varyant ayrı satır; parent_sku == parent_row.sku
	images_idx: {sku: [file_url, ...]} — hem parent_sku hem her variant_sku için
	            ayrı resim arşivi.
	"""
	images_idx = images_idx or {}
	parent_sku = str(parent_row.get("sku") or "").strip()
	# Görsel lookup'ı normalize anahtarla — index key'leri build_image_index'te
	# normalize edildi (büyük/küçük & Türkçe bağımsız eşleşme).
	parent_imgs = images_idx.get(normalize_sku_key(parent_sku), []) if parent_sku else []

	coerced = _coerce_row(parent_row)
	doc = frappe.new_doc("Listing")
	for field, value in coerced.items():
		if field in WRITABLE_FIELDS and value is not None and value != "":
			setattr(doc, field, value)
	doc.seller_profile = seller_profile
	doc.created_by_bulk_job = job_name
	doc.has_variants = 1
	doc.variant_axes_config = _build_variant_axes_config(variant_rows)

	_apply_defaults(doc)

	if not doc.selling_price and doc.base_price:
		doc.selling_price = doc.base_price

	_attach_images(doc, parent_imgs)
	# attribute_values parent satırından — varyant eksenleri ayrı variant_items'a gider.
	_apply_attribute_values(doc, parent_row, warnings)

	# Varyant child rows
	import json

	for i, vrow in enumerate(variant_rows):
		v_sku = str(vrow.get("variant_sku") or "").strip()
		v_imgs = images_idx.get(normalize_sku_key(v_sku), []) if v_sku else []
		variant_image = v_imgs[0] if v_imgs else None
		# Ek görseller JSON listesi (variant_gallery Long Text)
		gallery_json = json.dumps(v_imgs[1:], ensure_ascii=False) if len(v_imgs) > 1 else None

		axes = _extract_variant_axes(vrow)
		# 1-3 ekseni ayrı kolonlara yaz; 3+ ekseni axis_values_json'a koru.
		# attribute_type/value reqd — 1. eksen boşsa "Renk" default'u uygulanır.
		axis_values_json = (
			json.dumps([{"type": t, "value": v} for t, v in axes], ensure_ascii=False)
			if len(axes) > 2
			else None
		)

		doc.append(
			"variant_items",
			{
				"variant_sku": v_sku,
				"attribute_type": (axes[0][0] if len(axes) > 0 else "") or "Renk",
				"attribute_value": axes[0][1] if len(axes) > 0 else "",
				"attribute_type_2": (axes[1][0] if len(axes) > 1 else "") or None,
				"attribute_value_2": (axes[1][1] if len(axes) > 1 else "") or None,
				"attribute_type_3": (axes[2][0] if len(axes) > 2 else "") or None,
				"attribute_value_3": (axes[2][1] if len(axes) > 2 else "") or None,
				"axis_values_json": axis_values_json,
				"variant_price": _normalize_numeric(vrow.get("variant_price")) or 0,
				"variant_stock": _normalize_numeric(vrow.get("variant_stock")) or 0,
				"variant_image": variant_image,
				"variant_gallery": gallery_json,
				"is_default": 1 if i == 0 else 0,
			},
		)

	# Bulk import güvenilir sunucu-içi işlem: satıcı kimliği doğrulanmış ve
	# seller_profile açıkça set edili (tenant izolasyonu korunur). Arka plan
	# işinde rol-bazlı "create" izni düşmesin diye ignore_permissions=True.
	doc.insert(ignore_permissions=True)
	return doc.name
