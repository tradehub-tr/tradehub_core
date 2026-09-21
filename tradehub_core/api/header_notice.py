import frappe
from frappe.utils import get_datetime, now_datetime

CACHE_KEY = "header_notices_active"
CACHE_TTL = 60  # seconds

#: Duyuru metinlerinin dilleri — TEK KAYNAK, `category_showcase.DILLER` ile birebir.
#
# 2026-09-21: `ar` ve `ru` eklendi. Bulundu: vitrin dört dile açılırken yapılan
# kırma turunda ("aynı kusur kardeş modüllerde de var mı?") bu modülün de yalnız
# `_tr`/`_en` kolonu taşıdığı ölçüldü. Duyuru şeridi sitenin HER sayfasında
# çiziliyor, yani Arapça/Rusça ziyaretçi her sayfada Türkçe bir şerit görüyordu.
#
# Kusur o gün GİZLİYDİ: canlıda aktif duyuru yoktu (`notices: []`, ölçüldü) ve
# LOCAL'de hiç kayıt yoktu. Biri duyuru yayınladığı gün görünür olurdu.
#
# VERİ PATCH'İ YOK — bilinçli: duyuru metinleri admin tarafından yazılıyor,
# sözlükle önceden çevrilemez. Yeni alanlar boş başlar ve `_tr`ye düşer;
# admin panelden doldurur.
DILLER = ("tr", "en", "ar", "ru")

#: Duyuru başına çevrilebilir alan kökleri (her biri `<kok>_<dil>` kolonu taşır).
CEVRILEBILIR_ALANLAR = ("message", "link_text")

#: Dilden bağımsız duyuru alanları.
SABIT_ALANLAR = (
	"name",
	"link_href",
	"icon",
	"background_color",
	"sort_order",
	"start_at",
	"end_at",
)


@frappe.whitelist(allow_guest=True)
def get_active_notices() -> dict:
	"""Storefront tarafından çağrılır; login zorunlu değil."""
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is not None:
		return cached

	settings = frappe.get_cached_doc("Header Notice Settings")
	display_mode = settings.display_mode or "marquee"

	now = now_datetime()
	rows = frappe.get_all(
		"Header Notice",
		filters={"is_active": 1},
		fields=[
			*SABIT_ALANLAR,
			*(f"{kok}_{dil}" for kok in CEVRILEBILIR_ALANLAR for dil in DILLER),
		],
		order_by="sort_order asc, creation desc",
	)

	def in_window(n: dict) -> bool:
		if n.get("start_at") and get_datetime(n["start_at"]) > now:
			return False
		if n.get("end_at") and get_datetime(n["end_at"]) < now:
			return False
		return True

	def duyuru(n: dict) -> dict:
		cikti = {
			"name": n["name"],
			"link_href": n.get("link_href") or "",
			"icon": n.get("icon") or "none",
			"background_color": n.get("background_color") or "#1a1a1a",
			"sort_order": n["sort_order"],
		}
		for kok in CEVRILEBILIR_ALANLAR:
			for dil in DILLER:
				cikti[f"{kok}_{dil}"] = n.get(f"{kok}_{dil}") or ""
		return cikti

	active = [duyuru(n) for n in rows if in_window(n)]

	payload = {
		"success": True,
		"display_mode": display_mode,
		"notices": active,
	}
	frappe.cache.set_value(CACHE_KEY, payload, expires_in_sec=CACHE_TTL)
	return payload


def invalidate_cache(doc, method=None) -> None:
	"""hooks.py doc_events tarafından çağrılır."""
	frappe.cache.delete_value(CACHE_KEY)
