"""Hard validators — değişmez kurallar (kullanıcı kapatamaz)."""

import re

from tradehub_core.utils.seo_content import check_title, check_description

SKU_VALID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_.]{0,49}$")


def validate_sku(sku) -> tuple[bool, str | None]:
	if sku is None or not str(sku).strip():
		return False, "SKU boş olamaz"
	value = str(sku).strip()
	if not SKU_VALID_PATTERN.match(value):
		return False, "SKU sadece harf/rakam/tire/nokta/altçizgi içerebilir (max 50)"
	return True, None


def validate_price(price) -> tuple[bool, str | None]:
	if price is None or price == "":
		return False, "Fiyat boş olamaz"
	# Adaptive ingestion'ın price normalizer'ı TR ("1.245,00") + EN ("1,234.56")
	# formatlarını destekler. Naive replace(",", ".") TR formatında "1.245.00"
	# çıkarıp ValueError attı.
	from tradehub_core.bulk_import.ingestion.normalizers.price import parse_price

	p = parse_price(price)
	if p is None:
		return False, "Geçersiz fiyat formatı"
	if p < 0:
		return False, "Fiyat negatif olamaz"
	if p > 10_000_000:
		return False, "Fiyat 10 milyonu aşamaz"
	return True, None


def validate_stock(qty) -> tuple[bool, str | None]:
	if qty is None or qty == "":
		return True, None
	from tradehub_core.bulk_import.ingestion.normalizers.qty import parse_qty

	q = parse_qty(qty)
	if q is None:
		return False, "Geçersiz stok formatı"
	if q < 0:
		return False, "Stok negatif olamaz"
	return True, None


def validate_title(title) -> tuple[bool, str | None]:
	# SEO kuralları (min uzunluk + emoji yasağı) ortak modülde; tekil kayıtla aynı.
	return check_title(title)


def validate_description(description) -> tuple[bool, str | None]:
	# SEO açıklama kuralı (min uzunluk + emoji yasağı) — ortak modül.
	return check_description(description)


# Import için zorunlu, fallback'i olmayan canonical alanlar → kullanıcıya gösterilen etiket.
# Bunlar mapping'de yoksa her satır insert'te ham Frappe "MandatoryError" üretir;
# onun yerine yükleme öncesi tek ve anlaşılır bir mesaj veriyoruz.
_REQUIRED_MAPPING_FIELDS = {
	"sku": "Stok Kodu (SKU)",
	"title": "Ürün Adı",
	"base_price": "Fiyat",
}


def validate_mapping(mapping: dict) -> list[str]:
	"""Satır-bağımsız mapping kontrolü — zorunlu sütunlar eşleşti mi?

	mapping: {canonical_field: source_header}
	Returns: eksik varsa tek anlaşılır mesaj içeren liste, yoksa boş liste.
	"""
	missing = [label for field, label in _REQUIRED_MAPPING_FIELDS.items() if field not in mapping]
	if not missing:
		return []
	return [
		"Şu zorunlu sütun(lar) hiçbir başlıkla eşleşmedi: {}. "
		"Lütfen yükleme öncesi eşleştirme ekranında doğru sütunlara bağlayın.".format(", ".join(missing))
	]


def validate_row(row: dict, mapping: dict) -> list[dict]:
	"""Tüm row için validasyonları çalıştır. Errors listesi döner.

	mapping: {canonical_field: source_header}
	row: parser çıktısı (source headers → values)
	"""
	errors: list[dict] = []

	sku_col = mapping.get("sku")
	if sku_col and sku_col in row:
		ok, msg = validate_sku(row[sku_col])
		if not ok:
			errors.append({"field": "sku", "message": msg})
	elif sku_col:
		errors.append({"field": "sku", "message": "SKU sütunu satırda yok"})

	price_col = mapping.get("base_price")
	if price_col and price_col in row:
		ok, msg = validate_price(row[price_col])
		if not ok:
			errors.append({"field": "base_price", "message": msg})

	stock_col = mapping.get("stock_qty")
	if stock_col and stock_col in row:
		ok, msg = validate_stock(row[stock_col])
		if not ok:
			errors.append({"field": "stock_qty", "message": msg})

	title_col = mapping.get("title")
	if title_col and title_col in row:
		ok, msg = validate_title(row[title_col])
		if not ok:
			errors.append({"field": "title", "message": msg})

	desc_col = mapping.get("description")
	if desc_col and desc_col in row:
		ok, msg = validate_description(row[desc_col])
		if not ok:
			errors.append({"field": "description", "message": msg})

	return errors
