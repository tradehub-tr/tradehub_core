"""Yetim AVIF türevleri — önce GÖR, sonra (ayrı kararla) sil.

2026-09-30: ürün görseli merdiveni AVIF'ten WebP'ye geçti. Eski AVIF türev
dosyaları diskte duruyor (kullanıcı kararı: SİLİNMEZ, önce görülür). Bu modül
"hiçbir manifestin artık göstermediği" AVIF dosyalarını bulur:

* ``archived_asset`` — varlık emekli (`state=archived`, ör. kare dönüşümü
  öncesi eski içerik).
* ``old_version``   — varlık canlı ama dosya aktif sürüme ait değil (manifest
  yalnız ``active_version`` satırlarını sunar, bkz. api/media_manifest.py).
* ``asset_missing`` — `Media Rendition` satırı var, varlık satırı yok.
* ``unregistered``  — diskte `/files/media/<varlık>/…/*.avif` var ama hiçbir
  `Media Rendition` satırı onu anlatmıyor. Bunlar YALNIZ raporlanır; silme
  kapısı defter satırı olmayan dosyaya dokunmaz.

Silme varsayılan olarak KURU koşudur ("ne silinirdi"). Gerçek işlem yalnız
kuru koşunun döndürdüğü onay jetonuyla ve `trash.move_to_trash(rendition=…)`
denetimli kapısından geçer: soft-delete, 30 gün geri alınabilir, audit'li.
"""

from __future__ import annotations

import os
from typing import Any

import frappe

CACHE_KEY = "tradehub:media:yetim_avif:v1"
CACHE_TTL = 600
URL_ONEKI = "/files/media/"
SEBEPLER = ("archived_asset", "old_version", "asset_missing", "unregistered")
SILINEBILIR = frozenset({"archived_asset", "old_version", "asset_missing"})
SILME_NEDENI = "orphan_avif"
SILME_GRACE_GUN = 30


def _disk_yolu(url: str) -> str | None:
	"""`/files/media/...avif` → public disk yolu; kök dışına çıkan yol `None`."""
	if not (url.startswith(URL_ONEKI) and url.lower().endswith(".avif")):
		return None
	kok = os.path.realpath(frappe.get_site_path("public", "files", "media"))
	yol = os.path.realpath(frappe.get_site_path("public", url.lstrip("/")))
	return yol if yol.startswith(kok + os.sep) else None


def _boyut(yol: str | None) -> int | None:
	try:
		return os.path.getsize(yol) if yol else None
	except OSError:
		return None


def _defter_satirlari() -> list[dict]:
	"""AVIF `Media Rendition` satırları + varlık durumu. TEK sorgu (sistem taraması)."""
	return frappe.db.sql(
		"""
		SELECT r.name, r.asset, r.version_hash, r.file_url, r.width, r.bytes, r.profile,
		       a.name AS asset_row, a.state AS asset_state, a.active_version, a.slot_key,
		       a.source_file
		FROM `tabMedia Rendition` r
		LEFT JOIN `tabMedia Asset` a ON a.name = r.asset
		WHERE r.format = 'avif' AND r.state NOT IN ('purged', 'trashed')
		  AND r.file_url LIKE %(onek)s
		""",
		{"onek": URL_ONEKI + "%"},
		as_dict=True,
	)


def _sebep(satir: dict) -> str | None:
	if not satir.get("asset_row"):
		return "asset_missing"
	if satir.get("asset_state") == "archived":
		return "archived_asset"
	if str(satir.get("version_hash") or "") != str(satir.get("active_version") or ""):
		return "old_version"
	return None


def _kayitsiz_dosyalar(bilinen: set[str]) -> list[dict]:
	"""Diskte olup hiçbir defter satırının anlatmadığı `*.avif` dosyaları."""
	kok = frappe.get_site_path("public", "files", "media")
	cikti: list[dict] = []
	if not os.path.isdir(kok):
		return cikti
	for dizin, _alt, dosyalar in os.walk(kok):
		for ad in dosyalar:
			if not ad.lower().endswith(".avif"):
				continue
			yol = os.path.join(dizin, ad)
			url = "/files/media/" + os.path.relpath(yol, kok).replace(os.sep, "/")
			if url in bilinen:
				continue
			cikti.append(
				{
					"rendition": "",
					"asset": url[len(URL_ONEKI) :].split("/", 1)[0],
					"file_url": url,
					"bytes": _boyut(yol) or 0,
					"width": 0,
					"reason": "unregistered",
				}
			)
	return cikti


def tara() -> dict[str, Any]:
	"""Tam tarama: `{"files": [...], "groups": {...}}`. Pahalı — `index()` önbellekli."""
	dosyalar: list[dict] = []
	bilinen: set[str] = set()
	varliklar: dict[str, dict] = {}
	for satir in _defter_satirlari():
		url = str(satir.file_url or "")
		bilinen.add(url)
		sebep = _sebep(satir)
		if not sebep:
			continue
		boyut = _boyut(_disk_yolu(url))
		if boyut is None:
			# Defter satırı var, dosya diskte yok: yer kaplamıyor, listelenmez.
			continue
		dosyalar.append(
			{
				"rendition": satir.name,
				"asset": satir.asset,
				"file_url": url,
				"bytes": boyut,
				"width": int(satir.width or 0),
				"reason": sebep,
			}
		)
		varliklar.setdefault(
			satir.asset, {"slot_key": satir.slot_key or "", "source_file": satir.source_file or ""}
		)
	dosyalar.extend(_kayitsiz_dosyalar(bilinen))
	return {"files": dosyalar, "assets": varliklar}


def index(refresh: bool = False) -> dict[str, Any]:
	if not refresh:
		onbellek = frappe.cache.get_value(CACHE_KEY)
		if onbellek:
			return onbellek
	sonuc = tara()
	frappe.cache.set_value(CACHE_KEY, sonuc, expires_in_sec=CACHE_TTL)
	return sonuc


def invalidate() -> None:
	frappe.cache.delete_value(CACHE_KEY)


def _gruplar(veri: dict[str, Any], slot: str = "") -> list[dict]:
	gruplar: dict[str, dict] = {}
	for d in veri["files"]:
		meta = veri["assets"].get(d["asset"]) or {}
		if slot and meta.get("slot_key") != slot:
			continue
		g = gruplar.setdefault(
			d["asset"],
			{
				"asset": d["asset"],
				"slot_key": meta.get("slot_key") or "",
				"source_file": meta.get("source_file") or "",
				"count": 0,
				"bytes": 0,
				"reasons": {},
				"preview": "",
				"_onizleme_genislik": 0,
				"files": [],
			},
		)
		g["count"] += 1
		g["bytes"] += int(d["bytes"] or 0)
		g["reasons"][d["reason"]] = g["reasons"].get(d["reason"], 0) + 1
		g["files"].append(d)
		# Önizleme: en küçük basamak (hafif) — ama 0 genişlikli kayıtsız dosyalar son çare.
		w = int(d["width"] or 0) or 10**6
		if not g["preview"] or w < g["_onizleme_genislik"]:
			g["preview"], g["_onizleme_genislik"] = d["file_url"], w
	for g in gruplar.values():
		g.pop("_onizleme_genislik", None)
	return sorted(gruplar.values(), key=lambda g: (-g["bytes"], g["asset"]))


def _kaynak_bilgisi(gruplar: list[dict]) -> None:
	"""Sayfadaki grupların kaynak dosya adı ve ilanı — tek sorgu."""
	adlar = [g["source_file"] for g in gruplar if g["source_file"]]
	if not adlar:
		return
	bilgi = {
		r.name: r
		for r in frappe.get_all(
			"File",
			filters={"name": ["in", adlar]},
			fields=["name", "file_name", "file_url", "attached_to_doctype", "attached_to_name"],
		)
	}
	for g in gruplar:
		f = bilgi.get(g["source_file"])
		g["file_name"] = f.file_name if f else ""
		g["source_url"] = f.file_url if f else ""
		g["listing"] = f.attached_to_name if f and f.attached_to_doctype == "Listing" else ""


def ozet(page: int = 1, page_size: int = 20, slot: str = "", refresh: bool = False) -> dict[str, Any]:
	veri = index(refresh=refresh)
	gruplar = _gruplar(veri, slot)
	toplam_dosya = sum(g["count"] for g in gruplar)
	toplam_bayt = sum(g["bytes"] for g in gruplar)
	sebep_ozeti: dict[str, dict[str, int]] = {s: {"count": 0, "bytes": 0} for s in SEBEPLER}
	for g in gruplar:
		for d in g["files"]:
			sebep_ozeti[d["reason"]]["count"] += 1
			sebep_ozeti[d["reason"]]["bytes"] += int(d["bytes"] or 0)
	page_size = max(1, min(100, int(page_size or 20)))
	page = max(1, int(page or 1))
	sayfa = gruplar[(page - 1) * page_size : page * page_size]
	_kaynak_bilgisi(sayfa)
	for g in sayfa:
		g["files"] = sorted(g["files"], key=lambda d: (d["width"], d["file_url"]))[:12]
	return {
		"total_files": toplam_dosya,
		"total_bytes": toplam_bayt,
		"total_groups": len(gruplar),
		"by_reason": sebep_ozeti,
		"deletable_files": sum(v["count"] for k, v in sebep_ozeti.items() if k in SILINEBILIR),
		"deletable_bytes": sum(v["bytes"] for k, v in sebep_ozeti.items() if k in SILINEBILIR),
		"page": page,
		"page_size": page_size,
		"groups": sayfa,
	}


def _hedefler(veri: dict[str, Any], assets: list[str] | None) -> tuple[list[dict], list[dict]]:
	secim = set(assets or [])
	hedef, atlanan = [], []
	for d in veri["files"]:
		if secim and d["asset"] not in secim:
			continue
		(hedef if d["reason"] in SILINEBILIR and d["rendition"] else atlanan).append(d)
	return hedef, atlanan


def onay_jetonu(hedef: list[dict]) -> str:
	return f"{len(hedef)}:{sum(int(d['bytes'] or 0) for d in hedef)}"


def sil(assets: list[str] | None = None, dry_run: bool = True, confirm_token: str = "") -> dict[str, Any]:
	"""Varsayılan KURU koşu. Gerçek işlem kuru koşunun jetonunu ister.

	Gerçek işlemde her dosya `trash.move_to_trash(rendition=…)` kapısından
	geçer (soft-delete, `SILME_GRACE_GUN` gün geri alınabilir). Defter satırı
	olmayan (`unregistered`) dosyalar hiçbir koşulda silinmez.
	"""
	veri = index(refresh=True)
	hedef, atlanan = _hedefler(veri, assets)
	jeton = onay_jetonu(hedef)
	govde = {
		"dry_run": bool(dry_run),
		"would_delete_files": len(hedef),
		"would_delete_bytes": sum(int(d["bytes"] or 0) for d in hedef),
		"skipped_unregistered": sum(1 for d in atlanan if d["reason"] == "unregistered"),
		"confirm_token": jeton,
		"sample": [d["file_url"] for d in hedef[:20]],
	}
	if dry_run:
		return govde
	if not confirm_token or confirm_token != jeton:
		frappe.throw(
			frappe._("Onay jetonu güncel değil. Önce yeniden kuru koşu yapın."), frappe.ValidationError
		)
	from tradehub_core.media import trash

	tasinan, hatali = 0, []
	for d in hedef:
		try:
			sonuc = trash.move_to_trash(
				d["file_url"], rendition=d["rendition"], reason=SILME_NEDENI, grace_days=SILME_GRACE_GUN
			)
			if sonuc.get("ok", True):
				tasinan += 1
			else:
				hatali.append({"file_url": d["file_url"], "error": str(sonuc.get("reason") or "")})
		except (frappe.ValidationError, OSError) as exc:
			hatali.append({"file_url": d["file_url"], "error": str(exc)[:200]})
	invalidate()
	govde.update({"moved_to_trash": tasinan, "errors": hatali[:50]})
	return govde
