"""Regex Pattern Library resolver — System + Seller Override katmanları."""

import re

import frappe
from frappe import _

PATTERN_CACHE_TTL = 300  # 5 dakika


def resolve_column_mapping(headers: list[str], seller_profile: str) -> dict[str, str]:
	"""Header listesi → {canonical_field: header} mapping.

	Strategy:
	1. Seller Override patterns (priority asc)
	2. System patterns (priority asc)
	3. Unmapped headers → manuel

	Yan etki: eşleşen Pattern Library kayıtlarının match_count sayacını artırır
	(kullanım istatistiği). Header sayısı küçük olduğundan toplu artış N+1 değil.
	"""
	mapping: dict[str, str] = {}
	seller_patterns = _get_patterns(seller_profile, "Column Header")
	system_patterns = _get_patterns(None, "Column Header")

	matched_library_names: list[str] = []
	for header in headers:
		if not header:
			continue
		header_lower = str(header).lower().strip()
		if not header_lower:
			continue

		match = _match_patterns(header_lower, seller_patterns)
		if not match:
			match = _match_patterns(header_lower, system_patterns)
		if match and match[0] not in mapping:
			target_field, library_name = match
			mapping[target_field] = header
			matched_library_names.append(library_name)

	_increment_match_counts(matched_library_names)
	return mapping


def _match_patterns(text: str, patterns: list[dict]) -> tuple[str, str] | None:
	"""Patterns listesinden ilk eşleşeni döndür → (target_field, library_name)."""
	for p in patterns:
		for entry in p.get("patterns", []):
			if not entry.get("enabled"):
				continue
			regex_str = entry.get("regex", "")
			if not regex_str or len(regex_str) > 200:
				continue
			flags = _parse_flags(entry.get("flags", ""))
			try:
				if re.search(regex_str, text, flags):
					return p["target_field"], p["name"]
			except re.error:
				continue
	return None


def extract_sku_from_filename(filename: str, seller_profile: str | None = None) -> str | None:
	"""'SKU Filename' kategorisindeki desenlerle dosya adından SKU çıkar.

	image_matcher'ın varsayılan SKU_FILENAME_RE'si eşleşmezse fallback olarak
	çağrılır (satıcıya özel dosya adı formatları için). Seller Override önce,
	System sonra; desenin 'sku' adlı grubu (yoksa ilk grup, o da yoksa tüm eşleşme)
	SKU sayılır. Hiçbiri eşleşmezse None.
	"""
	if not filename:
		return None
	scopes = [seller_profile, None] if seller_profile else [None]
	for sp in scopes:
		for p in _get_patterns(sp, "SKU Filename"):
			for entry in p.get("patterns", []):
				if not entry.get("enabled"):
					continue
				regex_str = entry.get("regex", "")
				if not regex_str or len(regex_str) > 200:
					continue
				flags = _parse_flags(entry.get("flags", ""))
				try:
					m = re.search(regex_str, filename, flags)
				except re.error:
					continue
				if not m:
					continue
				try:
					sku = m.group("sku")
				except IndexError:
					sku = m.group(1) if m.groups() else m.group(0)
				if sku:
					return sku.strip()
	return None


def _increment_match_counts(library_names: list[str]) -> None:
	"""Eşleşen Library kayıtlarının match_count sayacını DB'de atomik artır.

	Cache'i (PATTERN_CACHE_TTL) değiştirmez — yalnız kalıcı sayaç. İçe aktarma
	sırasında çağrılır (sıcak yol değil); başarısızlık import'u bozmamalı.
	"""
	for name in set(library_names):
		count = library_names.count(name)
		try:
			frappe.db.sql(
				"""
				UPDATE `tabRegex Pattern Library`
				SET match_count = COALESCE(match_count, 0) + %s
				WHERE name = %s
				""",
				(count, name),
			)
		except Exception as e:
			frappe.log_error(f"match_count increment failed: {e}", "regex_lib")


def _parse_flags(flags_str: str | None) -> int:
	flags = 0
	if not flags_str:
		return flags
	for token in str(flags_str).upper().split(","):
		token = token.strip()
		if token == "IGNORECASE":
			flags |= re.IGNORECASE
		elif token == "UNICODE":
			flags |= re.UNICODE
		elif token == "MULTILINE":
			flags |= re.MULTILINE
	return flags


def _get_patterns(seller_profile: str | None, category: str) -> list[dict]:
	"""Pattern Library kayıtlarını getir (cached)."""
	cache_key = f"regex_patterns:{seller_profile or 'SYSTEM'}:{category}"
	cached = frappe.cache.get_value(cache_key)
	if cached is not None:
		return cached

	filters: dict = {"enabled": 1, "pattern_category": category}
	if seller_profile:
		filters["scope"] = "Seller Override"
		filters["seller_profile"] = seller_profile
	else:
		filters["scope"] = "System"

	try:
		libs = frappe.get_all(
			"Regex Pattern Library",
			filters=filters,
			fields=["name", "target_field", "priority"],
			order_by="priority asc",
		)
	except Exception:
		libs = []

	result: list[dict] = []
	for lib in libs:
		try:
			doc = frappe.get_doc("Regex Pattern Library", lib.name)
		except Exception:
			continue
		result.append(
			{
				"name": lib.name,
				"target_field": doc.target_field,
				"priority": doc.priority,
				"patterns": [
					{
						"regex": p.regex,
						"flags": p.flags,
						"enabled": p.enabled,
					}
					for p in (doc.patterns or [])
				],
			}
		)

	frappe.cache.set_value(cache_key, result, expires_in_sec=PATTERN_CACHE_TTL)
	return result


def clear_pattern_cache(doc=None, method=None) -> None:
	"""hooks.py'den çağrılır — Pattern library değişince cache'i temizle."""
	try:
		frappe.cache.delete_keys("regex_patterns:*")
	except Exception:
		pass


@frappe.whitelist()
def test_pattern(regex: str, sample: str, flags: str = "IGNORECASE,UNICODE") -> dict:
	"""Pattern'i örnek string'le test et. SafeRegex koruması ile.

	Returns: {"matched": bool, "match_text": str | None, "error": str | None}
	"""
	from tradehub_core.eca.safe_regex import RegexError, SafeRegex

	if not regex:
		return {"matched": False, "match_text": None, "error": "Pattern boş"}
	if not sample:
		return {"matched": False, "match_text": None, "error": "Test örneği boş"}

	flag_int = _parse_flags(flags)
	try:
		m = SafeRegex.search(regex, sample, flag_int)
		if m:
			return {"matched": True, "match_text": m.group(0), "error": None}
		return {"matched": False, "match_text": None, "error": None}
	except RegexError as e:
		return {"matched": False, "match_text": None, "error": str(e)}
	except re.error as e:
		return {"matched": False, "match_text": None, "error": f"Geçersiz regex: {str(e)[:100]}"}


@frappe.whitelist()
def get_canonical_fields() -> list[str]:
	"""Adaptive ingestion canonical fields listesi (UI dropdown için)."""
	from tradehub_core.bulk_import.ingestion.canonical_fields import get_all_targets

	return get_all_targets()


# ── Sütun Eşleştirmelerim — satıcı literal alternatiflerden güvenli regex ─────


def _build_safe_alias_regex(headers: list[str]) -> str:
	"""Literal başlık alternatiflerinden ReDoS'a düşmeyen güvenli regex üret.

	Her alternatif re.escape() ile kaçırılır, boşluklar `\\s+`'e dönüşür, kelime
	sınırları (`\\b...\\b`) eklenir ve OR ile birleştirilir: `(?:alt1|alt2)`.
	Üretilen desen SafeRegex._validate'i geçer (sabit, backtracking-güvenli).

	Örnek: ["renk", "color", "renk seçeneği"] -> r"\\b(?:renk|color|renk\\s+seçeneği)\\b"
	"""
	parts = []
	seen = set()
	for raw in headers:
		token = (raw or "").strip().lower()
		if not token or token in seen:
			continue
		seen.add(token)
		# Önce escape, sonra kaçırılmış boşlukları esnek ayraca çevir. Boşluk;
		# alt çizgiyi de kabul eder (XML snake_case tag: "base_price" == "base price").
		escaped = re.escape(token).replace("\\ ", r"[\s_]+")
		parts.append(escaped)
	if not parts:
		frappe.throw(_("En az bir geçerli başlık gerekli"))
	return r"\b(?:" + "|".join(parts) + r")\b"


def _current_seller_profile() -> str:
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	profile = _get_seller_profile_for_user(frappe.session.user)
	if not profile:
		frappe.throw(_("Satıcı profili bulunamadı"))
	return profile


@frappe.whitelist()
def save_column_alias(my_header: str, target_field: str, alternatives: str = "") -> dict:
	"""Satıcı sütun eşleştirmesi — literal'lerden güvenli regex üretip kaydet.

	Satıcı regex GÖRMEZ; "benim başlığım" + virgülle "alternatif yazımlar" girer.
	Backend re.escape + OR ile SafeRegex-uyumlu desen üretir ve Seller Override
	"Regex Pattern Library" kaydı (pattern_category="Column Header") oluşturur.

	Args:
	    my_header: Satıcının Excel başlığı (örn. "Renk Seçeneği").
	    target_field: Eşlenecek canonical alan (örn. "variant_axis_1_type").
	    alternatives: Virgülle ayrılmış ek yazımlar (örn. "renk, color").

	Returns:
	    {"ok": True, "name": <pattern name>, "regex": <üretilen>, "target_field": ...}
	"""
	from tradehub_core.eca.safe_regex import RegexError, SafeRegex

	my_header = (my_header or "").strip()
	target_field = (target_field or "").strip()
	if not my_header:
		frappe.throw(_("Başlık zorunlu"))
	if not target_field:
		frappe.throw(_("Hedef alan zorunlu"))

	headers = [my_header] + [a for a in (alternatives or "").split(",")]
	regex = _build_safe_alias_regex(headers)

	# Üretilen deseni doğrula — catastrophic backtracking koruması.
	try:
		SafeRegex.search(regex, my_header.lower(), SafeRegex.IGNORECASE | SafeRegex.UNICODE)
	except RegexError as e:
		frappe.throw(_("Desen güvenli değil: {0}").format(str(e)))

	seller = _current_seller_profile()

	doc = frappe.new_doc("Regex Pattern Library")
	doc.pattern_name = f"{seller} — {my_header} → {target_field}"
	doc.enabled = 1
	doc.target_field = target_field
	doc.target_doctype = "Listing"
	doc.pattern_category = "Column Header"
	doc.scope = "Seller Override"
	doc.seller_profile = seller
	doc.priority = 50
	doc.append(
		"patterns",
		{
			"regex": regex,
			"flags": "IGNORECASE,UNICODE",
			"enabled": 1,
			"description": _("Satıcı sütun eşleştirmesi: {0}").format(my_header),
		},
	)
	doc.insert()

	return {"ok": True, "name": doc.name, "regex": regex, "target_field": target_field}


@frappe.whitelist()
def list_column_aliases() -> list[dict]:
	"""Satıcının kendi sütun eşleştirmelerini listele (regex gizli)."""
	seller = _current_seller_profile()
	rows = frappe.get_list(
		"Regex Pattern Library",
		filters={
			"scope": "Seller Override",
			"seller_profile": seller,
			"pattern_category": "Column Header",
		},
		fields=["name", "pattern_name", "target_field", "enabled"],
		order_by="modified desc",
	)
	return rows


@frappe.whitelist()
def delete_column_alias(name: str) -> dict:
	"""Satıcının kendi sütun eşleştirmesini sil (sahiplik doğrulanır)."""
	seller = _current_seller_profile()
	owner = frappe.db.get_value("Regex Pattern Library", name, "seller_profile")
	if owner != seller:
		frappe.throw(_("Bu eşleştirmeyi silme yetkiniz yok"))
	frappe.delete_doc("Regex Pattern Library", name)
	return {"ok": True, "name": name}


# ── Değer Eşleştirmelerim — hücre-değeri normalizasyonu (ayrı katman) ─────────


@frappe.whitelist()
def save_value_mapping(target_field: str, rows_json: str) -> dict:
	"""Satıcı değer eşleştirmesi kaydet (upsert — alan başına tek kayıt).

	"Sütun Eşleştirmelerim" kolon-ADI'nı çevirir; bu AYRI katman hücre-DEĞERİNİ
	çevirir. Satıcı "[alan] gelen [X] → hedef [Y]" satırları girer; regex YOK.

	Args:
	    target_field: Eşleştirmenin uygulanacağı canonical alan (örn. "condition",
	        "brand", "attr:beden").
	    rows_json: JSON liste — [{"source_value": "Large", "target_value": "XL"}, ...]

	Returns:
	    {"ok": True, "name": <name>, "target_field": ..., "row_count": int}
	"""
	import json

	target_field = (target_field or "").strip()
	if not target_field:
		frappe.throw(_("Hedef alan zorunlu"))

	try:
		rows = json.loads(rows_json or "[]")
	except (ValueError, TypeError):
		frappe.throw(_("Geçersiz satır verisi"))
	if not isinstance(rows, list):
		frappe.throw(_("Satır verisi liste olmalı"))

	seller = _current_seller_profile()

	existing = frappe.db.get_value(
		"Seller Value Mapping",
		{"seller_profile": seller, "target_field": target_field},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Seller Value Mapping", existing)
		doc.set("rows", [])
	else:
		doc = frappe.new_doc("Seller Value Mapping")
		doc.seller_profile = seller
		doc.target_field = target_field
		doc.enabled = 1

	for r in rows:
		if not isinstance(r, dict):
			continue
		src = str(r.get("source_value") or "").strip()
		tgt = str(r.get("target_value") or "").strip()
		if not src or not tgt:
			continue
		doc.append(
			"rows",
			{
				"source_value": src,
				"target_value": tgt,
				"enabled": 1 if r.get("enabled", 1) else 0,
			},
		)

	doc.save()
	return {
		"ok": True,
		"name": doc.name,
		"target_field": target_field,
		"row_count": len(doc.rows or []),
	}


@frappe.whitelist()
def list_value_mappings() -> list[dict]:
	"""Satıcının kendi değer eşleştirmelerini satırlarıyla listele."""
	seller = _current_seller_profile()
	mappings = frappe.get_list(
		"Seller Value Mapping",
		filters={"seller_profile": seller},
		fields=["name", "target_field", "enabled"],
		order_by="modified desc",
	)
	result: list[dict] = []
	for m in mappings:
		doc = frappe.get_doc("Seller Value Mapping", m["name"])
		result.append(
			{
				"name": doc.name,
				"target_field": doc.target_field,
				"enabled": doc.enabled,
				"rows": [
					{
						"source_value": row.source_value,
						"target_value": row.target_value,
						"enabled": row.enabled,
					}
					for row in (doc.rows or [])
				],
			}
		)
	return result


@frappe.whitelist()
def delete_value_mapping(name: str) -> dict:
	"""Satıcının kendi değer eşleştirmesini sil (sahiplik doğrulanır)."""
	seller = _current_seller_profile()
	owner = frappe.db.get_value("Seller Value Mapping", name, "seller_profile")
	if owner != seller:
		frappe.throw(_("Bu eşleştirmeyi silme yetkiniz yok"))
	frappe.delete_doc("Seller Value Mapping", name)
	return {"ok": True, "name": name}


# ── Sistem Eşleştirme (admin, scope=System) ──────────────────────────────────
#
# Satıcı save_column_alias/save_value_mapping desenini System-scope aynalar.
# _build_safe_alias_regex aynen kullanılır (güvenli regex); fark scope="System",
# seller_profile=None, priority=100 (satıcı override 50 daha öncelikli kalır) ve
# admin rol guard.


def _require_admin() -> None:
	frappe.only_for(["System Manager", "Marketplace Admin"])


@frappe.whitelist()
def save_system_column_alias(my_header: str, target_field: str, alternatives: str = "") -> dict:
	"""Sistem sütun eşleştirmesi (admin) — TÜM satıcıları etkiler.

	Admin "başlık + alternatif → alan" girer; backend güvenli regex üretir ve
	scope="System" Regex Pattern Library kaydı oluşturur. Ham regex GÖRÜNMEZ.

	Returns:
	    {"ok": True, "name": <pattern>, "regex": <üretilen>, "target_field": ...}
	"""
	from tradehub_core.eca.safe_regex import RegexError, SafeRegex

	_require_admin()

	my_header = (my_header or "").strip()
	target_field = (target_field or "").strip()
	if not my_header:
		frappe.throw(_("Başlık zorunlu"))
	if not target_field:
		frappe.throw(_("Hedef alan zorunlu"))

	headers = [my_header] + [a for a in (alternatives or "").split(",")]
	regex = _build_safe_alias_regex(headers)

	# Üretilen deseni doğrula — catastrophic backtracking koruması.
	try:
		SafeRegex.search(regex, my_header.lower(), SafeRegex.IGNORECASE | SafeRegex.UNICODE)
	except RegexError as e:
		frappe.throw(_("Desen güvenli değil: {0}").format(str(e)))

	doc = frappe.new_doc("Regex Pattern Library")
	doc.pattern_name = f"Sistem — {my_header} → {target_field}"
	doc.enabled = 1
	doc.target_field = target_field
	doc.target_doctype = "Listing"
	doc.pattern_category = "Column Header"
	doc.scope = "System"
	doc.seller_profile = None
	doc.priority = 100
	doc.append(
		"patterns",
		{
			"regex": regex,
			"flags": "IGNORECASE,UNICODE",
			"enabled": 1,
			"description": _("Sistem sütun eşleştirmesi: {0}").format(my_header),
		},
	)
	doc.insert()

	return {"ok": True, "name": doc.name, "regex": regex, "target_field": target_field}


# ── SKU/XML parametrik desen üreticileri (Karar2=A) ──────────────────────────
#
# Price Normalizer + XML Tag kullanıcıdan parametre alır, güvenli regex'i SİSTEM
# üretir (satıcı/admin ham regex YAZMAZ). SKU Filename + özel durumlar ham regex
# (gated) yolunda kalır. Üretilen desenler SafeRegex._validate'i geçer.

# Ayraç seçenekleri — kullanıcı dropdown anahtarı -> gerçek karakter.
_PRICE_SEPARATORS: dict[str, str] = {"comma": ",", "dot": ".", "none": ""}


def _build_price_normalizer_regex(decimal_sep: str, thousands_sep: str) -> tuple[str, str]:
	"""Fiyat metnini normalize eden güvenli (regex, flags) çifti üret.

	Binlik ayracı kaldıran ve ondalık ayracı noktaya çeviren bir desen üretir.
	Örn: decimal=",", thousands="." → "1.234,56" okunurken nokta silinir, virgül
	noktaya döner. Tek bir karakter-sınıfı tabanlı desen — backtracking yok.

	Yalnız izin verilen ayraçlar (virgül/nokta/yok) kabul edilir; aksi halde throw.
	"""
	dec = _PRICE_SEPARATORS.get(decimal_sep)
	thou = _PRICE_SEPARATORS.get(thousands_sep)
	if dec is None or thou is None:
		frappe.throw(_("Geçersiz ayraç seçimi"))
	if dec == "":
		frappe.throw(_("Ondalık ayraç zorunlu"))
	if dec == thou:
		frappe.throw(_("Ondalık ve binlik ayraç aynı olamaz"))
	# Rakam + ayraçlardan oluşan parayı yakalayan sabit desen (ReDoS-güvenli).
	chars = re.escape(dec) + re.escape(thou) if thou else re.escape(dec)
	regex = r"[0-9" + chars + r"]+"
	return regex, "UNICODE"


def _build_xml_tag_regex(tag: str, attribute: str = "") -> tuple[str, str]:
	"""Bir XML etiketinin içeriğini yakalayan güvenli (regex, flags) çifti üret.

	Örn: tag="price" → r"<price[^>]*>([^<]*)</price>". `.*?` yerine `[^<]*`
	kullanılır (catastrophic backtracking yerine lineer). Öznitelik verilirse
	açılış etiketinde varlığını şart koşar.

	tag/attribute yalnız harf/rakam/-/_ içerebilir (XML adı doğrulaması + güvenlik).
	"""
	tag = (tag or "").strip()
	if not tag or not re.fullmatch(r"[A-Za-z_][\w\-.]*", tag):
		frappe.throw(_("Geçersiz etiket adı"))
	attr = (attribute or "").strip()
	open_tag = re.escape(tag)
	if attr:
		if not re.fullmatch(r"[A-Za-z_][\w\-.]*", attr):
			frappe.throw(_("Geçersiz öznitelik adı"))
		# Açılış etiketinde öznitelik geçsin (değeri serbest); içeriği yakala.
		regex = r"<" + open_tag + r"[^>]*\b" + re.escape(attr) + r"\b[^>]*>([^<]*)</" + open_tag + r">"
	else:
		regex = r"<" + open_tag + r"[^>]*>([^<]*)</" + open_tag + r">"
	return regex, "IGNORECASE,UNICODE"


@frappe.whitelist()
def save_system_advanced_pattern(
	category: str, target_field: str, params_json: str = "{}", pattern_name: str = ""
) -> dict:
	"""SKU/XML gelişmiş sistem deseni kaydet (admin) — kategoriye göre parametrik.

	Karar2=A:
	- "Price Normalizer": params {decimal_sep, thousands_sep} → sistem güvenli regex üretir.
	- "XML Tag": params {tag, attribute?} → sistem güvenli regex üretir.
	- "SKU Filename": params {regex} → ham regex (gated; SafeRegex ile doğrulanır).

	Hepsi scope="System" Regex Pattern Library kaydı oluşturur (save_system_column_alias
	desenini aynalar). Üretilen/verilen regex SafeRegex._validate'ten geçirilir.

	Returns:
	    {"ok": True, "name": <pattern>, "regex": <üretilen>, "target_field": ...}
	"""
	import json

	from tradehub_core.eca.safe_regex import RegexError, SafeRegex

	_require_admin()

	category = (category or "").strip()
	target_field = (target_field or "").strip()
	if not target_field:
		frappe.throw(_("Hedef alan zorunlu"))

	try:
		params = json.loads(params_json or "{}")
	except (ValueError, TypeError):
		frappe.throw(_("Geçersiz parametre verisi"))
	if not isinstance(params, dict):
		params = {}

	if category == "Price Normalizer":
		regex, flags = _build_price_normalizer_regex(
			params.get("decimal_sep") or "", params.get("thousands_sep") or ""
		)
		default_name = _("Fiyat normalleştirme: {0}").format(target_field)
	elif category == "XML Tag":
		regex, flags = _build_xml_tag_regex(params.get("tag") or "", params.get("attribute") or "")
		default_name = _("XML etiketi: {0}").format(params.get("tag") or target_field)
	elif category == "SKU Filename":
		regex = (params.get("regex") or "").strip()
		flags = "IGNORECASE,UNICODE"
		if not regex:
			frappe.throw(_("Regex zorunlu"))
		default_name = _("SKU dosya adı: {0}").format(target_field)
	else:
		frappe.throw(_("Geçersiz kategori"))

	# Üretilen/verilen deseni doğrula — catastrophic backtracking koruması.
	try:
		SafeRegex.search(regex, "", SafeRegex.IGNORECASE | SafeRegex.UNICODE)
	except RegexError as e:
		frappe.throw(_("Desen güvenli değil: {0}").format(str(e)))

	doc = frappe.new_doc("Regex Pattern Library")
	doc.pattern_name = (pattern_name or "").strip() or f"Sistem — {default_name}"
	doc.enabled = 1
	doc.target_field = target_field
	doc.target_doctype = "Listing"
	doc.pattern_category = category
	doc.scope = "System"
	doc.seller_profile = None
	doc.priority = 100
	doc.append(
		"patterns",
		{"regex": regex, "flags": flags, "enabled": 1, "description": default_name},
	)
	doc.insert()

	return {"ok": True, "name": doc.name, "regex": regex, "target_field": target_field}


@frappe.whitelist()
def list_system_aliases() -> list[dict]:
	"""Sistem sütun eşleştirmelerini listele (admin; regex gizli)."""
	_require_admin()
	return frappe.get_list(
		"Regex Pattern Library",
		filters={"scope": "System", "pattern_category": "Column Header"},
		fields=["name", "pattern_name", "target_field", "enabled", "match_count"],
		order_by="match_count desc, modified desc",
	)


@frappe.whitelist()
def delete_system_alias(name: str) -> dict:
	"""Sistem sütun eşleştirmesini sil (admin; yalnızca System scope)."""
	_require_admin()
	scope = frappe.db.get_value("Regex Pattern Library", name, "scope")
	if scope != "System":
		frappe.throw(_("Yalnızca sistem eşleştirmeleri silinebilir"))
	frappe.delete_doc("Regex Pattern Library", name)
	return {"ok": True, "name": name}


@frappe.whitelist()
def save_system_value_mapping(target_field: str, rows_json: str) -> dict:
	"""Sistem değer eşleştirmesi (admin) — TÜM satıcılar için taban katman.

	Satıcı save_value_mapping ile aynı şekil; fark scope="System",
	seller_profile boş. build_value_map System katmanını taban, satıcı katmanını
	override olarak birleştirir.

	Returns:
	    {"ok": True, "name": <name>, "target_field": ..., "row_count": int}
	"""
	import json

	_require_admin()

	target_field = (target_field or "").strip()
	if not target_field:
		frappe.throw(_("Hedef alan zorunlu"))

	try:
		rows = json.loads(rows_json or "[]")
	except (ValueError, TypeError):
		frappe.throw(_("Geçersiz satır verisi"))
	if not isinstance(rows, list):
		frappe.throw(_("Satır verisi liste olmalı"))

	existing = frappe.db.get_value(
		"Seller Value Mapping",
		{"scope": "System", "target_field": target_field},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Seller Value Mapping", existing)
		doc.set("rows", [])
	else:
		doc = frappe.new_doc("Seller Value Mapping")
		doc.scope = "System"
		doc.seller_profile = None
		doc.target_field = target_field
		doc.enabled = 1

	for r in rows:
		if not isinstance(r, dict):
			continue
		src = str(r.get("source_value") or "").strip()
		tgt = str(r.get("target_value") or "").strip()
		if not src or not tgt:
			continue
		doc.append(
			"rows",
			{"source_value": src, "target_value": tgt, "enabled": 1 if r.get("enabled", 1) else 0},
		)

	doc.save()
	return {
		"ok": True,
		"name": doc.name,
		"target_field": target_field,
		"row_count": len(doc.rows or []),
	}


@frappe.whitelist()
def list_system_value_mappings() -> list[dict]:
	"""Sistem değer eşleştirmelerini satırlarıyla listele (admin)."""
	_require_admin()
	mappings = frappe.get_list(
		"Seller Value Mapping",
		filters={"scope": "System"},
		fields=["name", "target_field", "enabled"],
		order_by="modified desc",
	)
	result: list[dict] = []
	for m in mappings:
		doc = frappe.get_doc("Seller Value Mapping", m["name"])
		result.append(
			{
				"name": doc.name,
				"target_field": doc.target_field,
				"enabled": doc.enabled,
				"rows": [
					{
						"source_value": row.source_value,
						"target_value": row.target_value,
						"enabled": row.enabled,
					}
					for row in (doc.rows or [])
				],
			}
		)
	return result


@frappe.whitelist()
def delete_system_value_mapping(name: str) -> dict:
	"""Sistem değer eşleştirmesini sil (admin; yalnızca System scope)."""
	_require_admin()
	scope = frappe.db.get_value("Seller Value Mapping", name, "scope")
	if scope != "System":
		frappe.throw(_("Yalnızca sistem eşleştirmeleri silinebilir"))
	frappe.delete_doc("Seller Value Mapping", name)
	return {"ok": True, "name": name}


@frappe.whitelist()
def get_field_values(target_field: str) -> dict:
	"""Bir hedef alanın geçerli değerlerini döndür (hedef-değer dropdown'u için).

	Kaynak:
	- Select (örn. condition): Listing field JSON `options` newline-ayraçlı.
	- Link (brand/category/stock_uom/Country vb.): _LINK_FIELDS → get_all.
	- attr:<code>: Product Attribute value_options child tablosu.
	- Aksi: serbest metin (free) — dropdown yerine elle giriş.

	Returns:
	    {"kind": "select|link|attr|free", "values": [{value, label}], "free": bool}
	"""
	from tradehub_core.bulk_import import persister

	target_field = (target_field or "").strip()
	if not target_field:
		return {"kind": "free", "values": [], "free": True}

	if target_field.startswith("attr:"):
		return _attribute_field_values(target_field[len("attr:") :].strip())

	if target_field in persister._LINK_FIELDS:
		return _link_field_values(persister._LINK_FIELDS[target_field])

	select_vals = _select_field_values(target_field)
	if select_vals is not None:
		return select_vals

	return {"kind": "free", "values": [], "free": True}


def _select_field_values(fieldname: str) -> dict | None:
	"""Listing Select field options → değer listesi (yoksa None)."""
	try:
		field = frappe.get_meta("Listing").get_field(fieldname)
	except Exception:
		return None
	if not field or field.fieldtype != "Select":
		return None
	# currency Select'i `options:"currency"` ile Currency listesini referanslar.
	if (field.options or "").strip() == "currency":
		rows = frappe.get_all("Currency", filters={"enabled": 1}, fields=["name"], order_by="name asc")
		return {
			"kind": "select",
			"values": [{"value": r["name"], "label": r["name"]} for r in rows],
			"free": False,
		}
	options = [o.strip() for o in (field.options or "").split("\n") if o.strip()]
	return {
		"kind": "select",
		"values": [{"value": o, "label": o} for o in options],
		"free": False,
	}


def _link_label_field(doctype: str) -> str | None:
	"""Link DocType'ın okunur ad alanı — meta.title_field (heuristik fallback ile).

	Product Category/Brand/Product Type gibi DocType'lar autoname=field:<code> ile
	UUID-benzeri `name` üretir; title_field (category_name/brand_name/type_name)
	okunur ad verir. Eski "{dt}_name" heuristiği yalnız Brand'de doğruydu
	(Product Category→category_name, Product Type→type_name'i kaçırıyordu).
	"""
	meta = frappe.get_meta(doctype)
	title_field = (meta.title_field or "").strip()
	if title_field and meta.get_field(title_field):
		return title_field
	heuristic = f"{doctype.lower().replace(' ', '_')}_name"
	return heuristic if meta.get_field(heuristic) else None


def _link_field_values(doctype: str) -> dict:
	"""Link DocType kayıtları → değer listesi (okunur label). Country/UOM ~200 seed olabilir."""
	label_field = _link_label_field(doctype)
	fields = ["name"] + ([label_field] if label_field else [])
	order_by = f"{label_field} asc" if label_field else "name asc"
	rows = frappe.get_all(doctype, fields=fields, order_by=order_by, limit_page_length=0)
	values = []
	for r in rows:
		label = r.get(label_field) if label_field else None
		values.append({"value": r["name"], "label": label or r["name"]})
	return {"kind": "link", "values": values, "free": False}


def _attribute_field_values(code: str) -> dict:
	"""Product Attribute value_options → değer listesi.

	data_type Select/Multi-Select/Color değilse (value_options boş) serbest metin.
	"""
	if not code or not frappe.db.exists("Product Attribute", code):
		return {"kind": "attr", "values": [], "free": True}
	doc = frappe.get_doc("Product Attribute", code)
	values = []
	for opt in doc.value_options or []:
		val = (opt.option_value or "").strip()
		if not val:
			continue
		values.append({"value": val, "label": (opt.option_label or val).strip()})
	# Select tipi olmayan attribute'lar serbest metin hedef-değeri alır.
	free = len(values) == 0
	return {"kind": "attr", "values": values, "free": free}
