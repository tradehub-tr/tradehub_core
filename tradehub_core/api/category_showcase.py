import frappe
from frappe.utils import get_datetime, now_datetime

CACHE_KEY = "category_showcase_active"
CACHE_TTL = 60  # seconds

#: Vitrin metinlerinin dilleri — TEK KAYNAK.
#
# 2026-09-21: `ar` ve `ru` eklendi. Ölçüldü (17 Eyl, alpha'da gerçek Suudi
# IP'siyle): otomatik dil seçimi sayfayı Arapça ve RTL açıyordu ama vitrin
# bölümü Türkçe/İngilizce kalıyordu ("Kategorileri keşfet", "Tüm kategoriler").
# Sebep çeviri hattında değil ŞEMADAYDI — bu DocType'ta `_ar`/`_ru` kolonu
# hiç yoktu. Kanıt: `docs/ulke-turu-kanit/alpha/01-SA-anasayfa.png`.
#
# Alan listesi ve yük bu demetten TÜRETİLİR; beşinci bir dil eklendiğinde
# tek satır değişir ve hiçbir alan unutulmaz.
DILLER = ("tr", "en", "ar", "ru")

#: Kutu başına çevrilebilir alan kökleri (her biri `<kok>_<dil>` kolonu taşır).
CEVRILEBILIR_ALANLAR = ("label", "hover_text", "promo_badge", "promo_title", "cta_text")

#: Dilden bağımsız kutu alanları.
SABIT_ALANLAR = (
	"name",
	"tile_type",
	"col_span",
	"row_span",
	"sort_order",
	"image",
	"link_href",
	"background_color",
	"cta_href",
	"start_at",
	"end_at",
)


@frappe.whitelist(allow_guest=True)
def get_active_tiles() -> dict:
	"""Storefront tarafından çağrılır; login zorunlu değil."""
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is not None:
		return cached

	settings = frappe.get_cached_doc("Category Showcase Settings")
	enabled = bool(settings.is_enabled)
	section_title = {dil: settings.get(f"section_title_{dil}") or "" for dil in DILLER}
	columns = int(settings.columns or 4)

	if not enabled:
		payload = {
			"success": True,
			"enabled": False,
			"section_title": section_title,
			"columns": columns,
			"tiles": [],
		}
		frappe.cache.set_value(CACHE_KEY, payload, expires_in_sec=CACHE_TTL)
		return payload

	now = now_datetime()
	rows = frappe.get_all(
		"Category Showcase Tile",
		filters={"is_active": 1},
		fields=[
			*SABIT_ALANLAR,
			*(f"{kok}_{dil}" for kok in CEVRILEBILIR_ALANLAR for dil in DILLER),
		],
		order_by="sort_order asc, creation desc",
	)

	def in_window(r: dict) -> bool:
		if r.get("start_at") and get_datetime(r["start_at"]) > now:
			return False
		if r.get("end_at") and get_datetime(r["end_at"]) < now:
			return False
		return True

	def kutu(r: dict) -> dict:
		cikti = {
			"name": r["name"],
			"tile_type": r.get("tile_type") or "category",
			"col_span": int(r.get("col_span") or 1),
			"row_span": int(r.get("row_span") or 1),
			"sort_order": r.get("sort_order") or 0,
			"image": r.get("image") or "",
			"link_href": r.get("link_href") or "",
			"background_color": r.get("background_color") or "#cc9900",
			"cta_href": r.get("cta_href") or "",
		}
		for kok in CEVRILEBILIR_ALANLAR:
			for dil in DILLER:
				cikti[f"{kok}_{dil}"] = r.get(f"{kok}_{dil}") or ""
		return cikti

	tiles = [kutu(r) for r in rows if in_window(r)]

	payload = {
		"success": True,
		"enabled": True,
		"section_title": section_title,
		"columns": columns,
		"tiles": tiles,
	}
	frappe.cache.set_value(CACHE_KEY, payload, expires_in_sec=CACHE_TTL)
	return payload


def invalidate_cache(doc, method=None) -> None:
	"""hooks.py doc_events tarafından çağrılır."""
	frappe.cache.delete_value(CACHE_KEY)
