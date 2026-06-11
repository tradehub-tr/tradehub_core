"""Adaptive column resolver — 4 katmanlı kaskat (Profile → Regex → Attribute → Semantic)."""

import frappe

from tradehub_core.bulk_import import regex_lib
from tradehub_core.bulk_import.ingestion import profile_store, semantic

# Türkçe karakterleri ASCII'ye indirger — başlık eşlemesi büyük/küçük ve
# Türkçe/İngilizce yazım farkından bağımsız olsun (Çelik == celik == Celik).
_TR_FOLD = str.maketrans(
	{
		"ı": "i",
		"İ": "i",
		"ş": "s",
		"Ş": "s",
		"ğ": "g",
		"Ğ": "g",
		"ü": "u",
		"Ü": "u",
		"ö": "o",
		"Ö": "o",
		"ç": "c",
		"Ç": "c",
	}
)


def _fold(text: str) -> str:
	"""lower + strip + Türkçe-fold — normalize edilmiş eşleştirme anahtarı."""
	return (text or "").strip().translate(_TR_FOLD).lower()


# Çoklu görsel kolonu için sentetik slot tavanı (primary_image + image_2..image_N).
# runner._IMAGE_URL_FIELDS ile hizalı kalmalı.
_MAX_IMAGE_COLUMNS = 10


def _next_image_slot(mapping: dict) -> str | None:
	"""primary_image dolu olduğunda boş image_2..image_N slotunu döndür."""
	for i in range(2, _MAX_IMAGE_COLUMNS + 1):
		key = f"image_{i}"
		if key not in mapping:
			return key
	return None


def _resolve_attributes(headers: list[str], used_headers: set[str]) -> dict[str, str]:
	"""Eşlenmemiş başlıkları Product Attribute kayıtlarıyla dinamik eşle.

	Betimleyici attribute'lar (Material, Renk, vb.) statik sinonim sözlüğünde
	değildir; DB'den çekilip başlık `attribute_label_en` / `attribute_label` /
	`attribute_code` ile (normalize) karşılaştırılır. Eşleşirse hedef
	`attr:<attribute_code>` olur — persister bu prefix'i tüketir.

	include_in_bulk_template=1 olanlar önceliklidir (önce onlar denenir).

	Returns: {"attr:<code>": header} mapping.
	"""
	# system işi — kullanıcı verisi değil, taksonomi kataloğu okunuyor.
	attrs = frappe.get_all(
		"Product Attribute",
		fields=[
			"name",
			"attribute_code",
			"attribute_label",
			"attribute_label_en",
			"include_in_bulk_template",
		],
		order_by="include_in_bulk_template desc, display_order asc, name asc",
	)

	# Normalize edilmiş etiket → attribute_code lookup. İlk gelen (öncelikli)
	# kazanır; aynı etiketi paylaşan ikinci attribute üzerine yazmaz.
	label_to_code: dict[str, str] = {}
	for a in attrs:
		code = a.get("attribute_code") or a.get("name")
		for label in (a.get("attribute_label_en"), a.get("attribute_label"), code):
			key = _fold(label)
			if key and key not in label_to_code:
				label_to_code[key] = code

	mapping: dict[str, str] = {}
	for header in headers:
		if header in used_headers or not header or not str(header).strip():
			continue
		code = label_to_code.get(_fold(str(header)))
		if code:
			target = f"attr:{code}"
			if target not in mapping:
				mapping[target] = header
				used_headers.add(header)
	return mapping


def resolve_columns(
	headers: list[str],
	seller_profile: str,
	sheet_name: str | None = None,
) -> dict:
	"""Header listesini canonical field'lara eşle.

	Returns:
		{
			"mapping": {canonical_field: header},
			"sources": {canonical_field: "profile" | "regex" | "attribute" | "semantic"},
			"confidence": {canonical_field: float 0..1},
			"unmapped": [headers that couldn't be resolved],
			"conflicts": [{field, winner_header, winner_score, loser_headers}],
			"profile_used": profile_name | None,
			"overall_score": float 0..1,
		}

	`conflicts`: Aynı canonical alana birden çok başlık aday olduğunda en yüksek
	skorlu kazanır; kaybeden başlıklar sessizce yutulmaz, burada raporlanır ki
	kullanıcı önizlemede görüp düzeltebilsin (ör. "BİRİM" vs "BİRİM FİYAT" fiyat
	alanı için yarışınca yanlış olanın base_price'ı kapması engellenir).
	"""
	# Layer 1: Profile (full match)
	profile = profile_store.lookup_profile(headers, seller_profile)
	if profile and profile.get("mapping"):
		profile_store.increment_hit_count(profile["profile_name"])
		# Bu profile'ı doğrudan kullan — %100 confidence
		mapping = profile["mapping"]
		sources = {f: "profile" for f in mapping}
		confidence = {f: 1.0 for f in mapping}
		unmapped = [h for h in headers if h not in mapping.values()]
		return {
			"mapping": mapping,
			"sources": sources,
			"confidence": confidence,
			"unmapped": unmapped,
			"conflicts": [],
			"profile_used": profile["profile_name"],
			"overall_score": 1.0,
		}

	# Layer 2: Regex Pattern Library
	regex_mapping = regex_lib.resolve_column_mapping(headers, seller_profile)
	sources: dict[str, str] = {f: "regex" for f in regex_mapping}
	confidence: dict[str, float] = {f: 0.9 for f in regex_mapping}  # Regex match = high confidence
	mapping: dict[str, str] = dict(regex_mapping)
	used_headers: set[str] = set(regex_mapping.values())

	# Layer 3: Betimleyici Product Attribute dinamik eşleme (attr:<code>)
	attr_mapping = _resolve_attributes(headers, used_headers)
	for target, header in attr_mapping.items():
		if target not in mapping:
			mapping[target] = header
			sources[target] = "attribute"
			confidence[target] = 0.95  # tam etiket eşleşmesi = yüksek güven

	# Layer 4: Semantic — skorlu arbitrasyon (en yüksek skor kazanır)
	# Önce tüm eşlenmemiş başlıkların en iyi semantic adayını topla, sonra skora
	# göre azalan sırada ata. Aynı alana ikinci aday gelirse atlanmaz: çakışma
	# olarak kaydedilir. Böylece "ilk gelen kapar" yüzünden düşük skorlu başlık
	# (örn. "BİRİM", 0.76) yüksek skorluyu (örn. "BİRİM FİYAT", 0.96) ezemez.
	candidates: list[tuple[float, str, str]] = []
	for header in headers:
		if header in used_headers or not header or not str(header).strip():
			continue
		target, score = semantic.resolve_header_semantic(header)
		if target and target not in mapping:
			candidates.append((score, target, header))

	candidates.sort(key=lambda c: c[0], reverse=True)
	conflicts_by_target: dict[str, dict] = {}
	for score, target, header in candidates:
		if header in used_headers:
			continue
		if target in mapping:
			# Görsel sütunları çoklu olabilir (Image #1/#2/#3) — çakışma değil galeri:
			# ek başlıkları image_2..image_N slotlarına ata (runner hepsini okur).
			if target == "primary_image":
				slot = _next_image_slot(mapping)
				if slot:
					mapping[slot] = header
					sources[slot] = "semantic"
					confidence[slot] = round(score, 3)
					used_headers.add(header)
					continue
			conflict = conflicts_by_target.setdefault(
				target,
				{
					"field": target,
					"winner_header": mapping[target],
					"winner_score": confidence.get(target, 0.0),
					"loser_headers": [],
				},
			)
			conflict["loser_headers"].append({"header": header, "score": round(score, 3)})
			continue
		mapping[target] = header
		sources[target] = "semantic"
		confidence[target] = round(score, 3)
		used_headers.add(header)

	conflicts = list(conflicts_by_target.values())

	# Compute overall score
	if confidence:
		overall = sum(confidence.values()) / len(confidence)
	else:
		overall = 0.0

	unmapped = [h for h in headers if h and h not in used_headers]

	return {
		"mapping": mapping,
		"sources": sources,
		"confidence": confidence,
		"unmapped": unmapped,
		"conflicts": conflicts,
		"profile_used": None,
		"overall_score": round(overall, 3),
	}
