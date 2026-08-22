"""Medya indexability — bir görsel aranabilir mi (TUR-135 Dilim 2, §6.1).

Karar belgesi: `docs/MEDYA-SEO-SOZLESMESI.md` §6.1 · mimari: ADR-0023.

TEK KARAR NOKTASI
-----------------
Site haritası, `robots` meta'sı ve yapısal veri üretimi aynı soruyu soruyor:
"bu görsel arama motoruna gösterilmeli mi". Üç yerde üç ayrı koşul yazmak,
gün gelip birinin unutulması demek — çöpteki dosya sitemap'te kalır. Karar
burada bir kez veriliyor.

İLKE — private ROBOTS İLE GİZLENMEZ
-----------------------------------
Üst belge §9: "Private asset 'robots.txt ile gizledim' mantığıyla korunmamalı;
gerçek authentication/authorization kullanılmalı." Bu sistemde o korumayı
`access_level` + Frappe izinleri sağlıyor (TUR-126). `noindex` yalnız
*erişilebilir ama aranmaması gereken* varlık içindir — ikisi farklı sorular.

DURUM KAYNAĞI
-------------
Yaşam döngüsü çekirdeğin (`File.th_media_state`, ADR-0023), erişim seviyesi
`File.is_private`, tarama durumu AV'nin, hak süresi SEO'nun. Hepsi okunur,
hiçbiri burada yazılmaz.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, nowdate

from tradehub_core.media import seo

#: `max-image-preview` — Google'ın görsel önizleme boyutu direktifi.
PREVIEW_LARGE: str = "max-image-preview:large"
PREVIEW_NONE: str = "max-image-preview:none"

#: Ret sebepleri — denetim (§6.3) ve panel aynı sözlüğü kullanır.
REASON_PRIVATE: str = "private"
REASON_STATE: str = "state"
REASON_QUARANTINE: str = "quarantine"
REASON_EXPIRED: str = "rights_expired"
REASON_ORPHAN: str = "orphan"
REASON_MISSING: str = "missing"


def decide(file_url: str, *, check_usage: bool = True) -> dict:
	"""Bu görsel indexlenebilir mi — `{indexable, reason, robots}`.

	`check_usage=False` toplu üretimde kullanımı atlar: kullanım sorgusu
	pahalı (16 kaynak taraması) ve site haritası zaten yalnız kullanılan
	görsellerden geçiyor.
	"""
	url = (file_url or "").split("?")[0]
	if not url:
		return _ret(REASON_MISSING)

	kayit = frappe.db.get_value(
		"File",
		{"file_url": url},
		["name", "is_private", "th_media_state"],
		as_dict=True,
	)
	if not kayit:
		return _ret(REASON_MISSING)

	if int(kayit.get("is_private") or 0):
		# Erişim zaten kapalı; sitemap'e girmemesi teyit, koruma değil.
		return _ret(REASON_PRIVATE)

	durum = (kayit.get("th_media_state") or "Active").strip()
	if durum and durum != "Active":
		return _ret(REASON_STATE, detay=durum)

	try:
		from tradehub_core.media import av

		if av.in_quarantine(url) or av.in_hold(url):
			return _ret(REASON_QUARANTINE)
	except Exception:
		# Tarama durumu okunamıyorsa indexability kararı DEĞİŞMEZ: dosya
		# public ve aktif. Güvenlik kararı `access_level`'ın işi.
		frappe.log_error(title="media.seo_index av lookup", message=frappe.get_traceback())

	alanlar = seo.fields_for(url)
	bitis = alanlar.get("rights_expires_on")
	if bitis and getdate(bitis) < getdate(nowdate()):
		return _ret(REASON_EXPIRED, detay=str(bitis))

	if check_usage:
		from tradehub_core.media import usage

		karar = (usage.verdicts_for([url]) or {}).get(url) or {}
		if karar.get("verdict") not in ("in_use", None):
			# Hiçbir sayfada görünmeyen görselin site haritasında yeri yok:
			# Google'ı var olmayan bir bağlama gönderir.
			return _ret(REASON_ORPHAN, detay=karar.get("verdict", ""))

	return {"indexable": True, "reason": "", "robots": f"index, {PREVIEW_LARGE}"}


def _ret(reason: str, detay: str = "") -> dict:
	return {
		"indexable": False,
		"reason": f"{reason}:{detay}" if detay else reason,
		"robots": f"noindex, {PREVIEW_NONE}",
	}
