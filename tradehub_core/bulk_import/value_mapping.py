"""Değer Eşleştirmelerim — satıcı yapılandırılabilir hücre-değeri normalizasyonu.

"Sütun Eşleştirmelerim" kolon-ADI'nı canonical alana çevirir (resolve aşaması).
Bu modül AYRI katman: canonical alan + gelen HÜCRE DEĞERİ → hedef değer (persist
ÖNCESİ). Böylece eskiden hata veren (Select) / boş kalan (Link) / ham giden (attr)
değerler kurtarılır.

Kanca: runner._canonicalize — her mapped canonical alan için `apply_value_mapping`
gelen değeri satıcı eşleştirmesiyle değiştirir. Link alanlarında transform
persister._resolve_link'ten ÖNCE girer (normalize edilmiş değer sonra link'e çözülür).

persister'daki hardcoded _TR_COUNTRY_ALIASES / _TR_UOM_ALIASES / _CONDITION_TR_ALIASES
fallback olarak KORUNUR (persister içinde) — bu modül onların YANINA, satıcıya özel
genel lookup ekler. Satıcı eşleştirmesi varsa o öncelikli, yoksa persister'ın
hardcoded tablosu devreye girer (davranış bozulmaz).
"""

import frappe

VALUE_MAP_CACHE_TTL = 300  # 5 dakika

# Free-text anahtar alanlar — bunlara değer eşleştirmesi UYGULANMAZ (sku/parent_sku
# gibi kimlik alanlarına map uygulamak cluster bağını bozar; feature yalnız
# Select/Link/attr hedefleri içindir).
_KEY_FIELDS_NO_MAPPING: frozenset[str] = frozenset(
	{
		"sku",
		"parent_sku",
		"variant_sku",
		"barcode",
	}
)


def build_value_map(seller_profile: str | None) -> dict[str, dict[str, str]]:
	"""Satıcının değer eşleştirmelerini {target_field: {source_lower: target}} kur.

	5 dakika Redis cache'lenir (key: value_map:{seller}). Aktif olmayan kayıt/satır
	atlanır. source_value lower-case anahtar (case-insensitive eşleşme).
	"""
	if not seller_profile:
		return {}

	cache_key = f"value_map:{seller_profile}"
	cached = frappe.cache.get_value(cache_key)
	if cached is not None:
		return cached

	value_map: dict[str, dict[str, str]] = {}
	# Sistem işi: arka plan runner bağlamı, perm by-pass kasıtlı (seller_profile
	# filtresi tenant izolasyonunu zaten sağlıyor).
	mappings = frappe.get_all(
		"Seller Value Mapping",
		filters={"seller_profile": seller_profile, "enabled": 1},
		fields=["name", "target_field"],
	)
	for m in mappings:
		target_field = (m.get("target_field") or "").strip()
		if not target_field:
			continue
		try:
			doc = frappe.get_doc("Seller Value Mapping", m["name"])
		except Exception as exc:
			frappe.log_error(f"value_map load failed {m['name']}: {exc}", "value_mapping")
			continue
		field_map = value_map.setdefault(target_field, {})
		for row in doc.rows or []:
			if not row.enabled:
				continue
			src = (row.source_value or "").strip()
			tgt = (row.target_value or "").strip()
			if not src or not tgt:
				continue
			field_map[src.lower()] = tgt

	frappe.cache.set_value(cache_key, value_map, expires_in_sec=VALUE_MAP_CACHE_TTL)
	return value_map


def apply_value_mapping(target_field: str, value, value_map: dict[str, dict[str, str]]):
	"""Tek alan + gelen değer için satıcı eşleştirmesi varsa hedef değeri döndür.

	Eşleşme yoksa veya alan kimlik alanıysa değer DEĞİŞMEDEN döner (downstream
	persister coerce/resolve normal çalışır — hardcoded fallback'lar devrede kalır).
	"""
	if not value_map or value is None:
		return value
	if target_field in _KEY_FIELDS_NO_MAPPING:
		return value
	field_map = value_map.get(target_field)
	if not field_map:
		return value
	key = str(value).strip().lower()
	if not key:
		return value
	return field_map.get(key, value)
