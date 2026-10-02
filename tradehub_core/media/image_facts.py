"""Görsel dosyaların ölçülen künyesi (DPI · renk uzayı · alfa) — kayıt katmanı.

Hesap `media/pipeline/image/facts.py`'de (saf, frappe'siz); burada yalnız
diskten okuma, `File`/`Media Rendition` alanlarına yazma ve geriye dönük
doldurma var.

Nerede saklanıyor
-----------------
* **Kaynak dosya** → `File.th_media_dpi / th_media_colorspace / th_media_alpha
  / th_media_facts` (patch `v15_9_65_media_image_facts`). Değer fiziksel
  dosyanın gerçeği olduğu için aynı `file_url`'i taşıyan TÜM `File`
  satırlarına aynı değer yazılır (`metadata.ensure_dimensions` deseni).
* **Türev** → `Media Rendition.output_dpi / output_colorspace /
  output_has_alpha` (DocType JSON).

`th_media_facts` durumu: `ok` (ölçüldü), `unreadable` (dosya var ama görsel
olarak açılamadı), `missing` (diskte yok). Boş = henüz ölçülmedi. Panel "—"
yalnız `unreadable`/`missing` için gösterir; `ok` iken DPI 0 "dosyada DPI
kaydı yok" demektir — ölçüm sonucudur, eksik veri değil.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

import frappe

from tradehub_core.media.pipeline.image import facts as facts_mod

FILE_FIELDS: tuple[str, ...] = ("th_media_dpi", "th_media_colorspace", "th_media_alpha", "th_media_facts")
RENDITION_FIELDS: tuple[str, ...] = ("output_dpi", "output_colorspace", "output_has_alpha")

STATUS_OK = "ok"
STATUS_UNREADABLE = "unreadable"
STATUS_MISSING = "missing"

IMAGE_EXTENSIONS: tuple[str, ...] = (
	".jpg",
	".jpeg",
	".png",
	".webp",
	".tif",
	".tiff",
	".gif",
	".bmp",
	".avif",
	".heic",
	".heif",
)
RENDITION_IMAGE_FORMATS: tuple[str, ...] = ("webp", "avif", "jpeg", "jpg", "png")


def is_image_url(file_url: str | None) -> bool:
	return str(file_url or "").split("?")[0].lower().endswith(IMAGE_EXTENSIONS)


def disk_path(file_url: str | None) -> str | None:
	"""`/files/…` ya da `/private/files/…` adresinin disk yolu; kök dışına çıkarsa `None`."""
	url = str(file_url or "").split("?")[0]
	if url.startswith("/private/files/"):
		kok = os.path.realpath(frappe.get_site_path("private", "files"))
		rel = url[len("/private/files/") :]
	elif url.startswith("/files/"):
		kok = os.path.realpath(frappe.get_site_path("public", "files"))
		rel = url[len("/files/") :]
	else:
		return None
	yol = os.path.realpath(os.path.join(kok, rel))
	if not yol.startswith(kok + os.sep):
		return None
	return yol


def measure_url(file_url: str) -> dict[str, Any]:
	"""Diskteki dosyayı ölç. Dönüş her zaman `status` taşır; salt-okur."""
	yol = disk_path(file_url)
	if not yol or not os.path.isfile(yol):
		return {"status": STATUS_MISSING}
	olcum = facts_mod.measure(yol)
	if not olcum.ok:
		return {"status": STATUS_UNREADABLE, "reason": olcum.reason}
	return {"status": STATUS_OK, **olcum.to_dict()}


def file_values(olcum: Mapping[str, Any]) -> dict[str, Any]:
	if olcum.get("status") != STATUS_OK:
		return {
			"th_media_dpi": 0,
			"th_media_colorspace": "",
			"th_media_alpha": "",
			"th_media_facts": olcum.get("status") or STATUS_UNREADABLE,
		}
	return {
		"th_media_dpi": int(olcum.get("dpi") or 0),
		"th_media_colorspace": str(olcum.get("colorspace") or "")[:140],
		"th_media_alpha": "yes" if olcum.get("has_alpha") else "no",
		"th_media_facts": STATUS_OK,
	}


def rendition_values(olcum: Mapping[str, Any]) -> dict[str, Any]:
	"""Ölçümü `Media Rendition` alanlarına çevir; ölçülemediyse boş sözlük."""
	if olcum.get("status") != STATUS_OK:
		return {}
	return {
		"output_dpi": int(olcum.get("dpi") or 0),
		"output_colorspace": str(olcum.get("colorspace") or "")[:140],
		"output_has_alpha": 1 if olcum.get("has_alpha") else 0,
	}


def rendition_values_from_bytes(content: bytes) -> dict[str, Any]:
	"""Encode edilen türev baytlarından alan değerleri (üretim anı)."""
	olcum = facts_mod.measure(content)
	if not olcum.ok:
		return {}
	return rendition_values({"status": STATUS_OK, **olcum.to_dict()})


def file_fields_ready() -> bool:
	return all(frappe.db.has_column("File", alan) for alan in FILE_FIELDS)


def rendition_fields_ready() -> bool:
	return all(frappe.db.has_column("Media Rendition", alan) for alan in RENDITION_FIELDS)


def store_file_facts(file_url: str, olcum: Mapping[str, Any] | None = None) -> dict[str, Any]:
	"""Ölç (verilmediyse) ve aynı adresi taşıyan TÜM `File` satırlarına yaz. Commit YOK."""
	olcum = dict(olcum or measure_url(file_url))
	if file_fields_ready():
		frappe.db.set_value(
			"File",
			{"file_url": file_url},
			file_values(olcum),
			update_modified=False,
		)
	return olcum


def facts_payload(row: Mapping[str, Any]) -> dict[str, Any] | None:
	"""`File` satırındaki saklı değerler → API gövdesi; ölçülmemişse `None`."""
	durum = str(row.get("th_media_facts") or "")
	if not durum:
		return None
	if durum != STATUS_OK:
		return {"status": durum, "dpi": None, "colorspace": None, "has_alpha": None}
	alfa = str(row.get("th_media_alpha") or "")
	return {
		"status": STATUS_OK,
		"dpi": int(row.get("th_media_dpi") or 0),
		"colorspace": str(row.get("th_media_colorspace") or ""),
		"has_alpha": True if alfa == "yes" else False if alfa == "no" else None,
	}


def source_facts_for(dosyalar: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any] | None]:
	"""File satırları (`name`, `file_url`) → `{name: künye}`.

	Saklı değer varsa o döner; yoksa dosya ŞİMDİ ölçülür ve saklanır (yeni
	yüklenen, geriye dönük doldurmadan sonra gelen dosya). Görsel olmayan
	dosyada `None`.
	"""
	adlar = [str(d["name"]) for d in dosyalar if d.get("name")]
	if not adlar:
		return {}
	sakli: dict[str, Mapping[str, Any]] = {}
	if file_fields_ready():
		for satir in frappe.get_all(
			"File",
			filters={"name": ["in", adlar]},
			fields=["name", *FILE_FIELDS],
			limit_page_length=0,
		):
			sakli[satir["name"]] = satir
	cikti: dict[str, dict[str, Any] | None] = {}
	for dosya in dosyalar:
		ad = str(dosya.get("name") or "")
		url = str(dosya.get("file_url") or "")
		if not ad:
			continue
		if not is_image_url(url):
			cikti[ad] = None
			continue
		hazir = facts_payload(sakli.get(ad) or {})
		if hazir is None:
			olcum = store_file_facts(url)
			hazir = facts_payload(file_values(olcum))
		cikti[ad] = hazir
	return cikti


# ── Geriye dönük doldurma ───────────────────────────────────────────────


def backfill_files(*, only_missing: bool = True, commit_every: int = 500) -> dict[str, int]:
	"""Tüm görsel `File` adreslerini ölç ve yaz. Dosyalara YAZMAZ (salt-okur)."""
	if not file_fields_ready():
		return {"skipped_no_fields": 1}
	kosul = "and ifnull(th_media_facts, '') = ''" if only_missing else ""
	uzanti_kosulu = " or ".join(f"lower(file_url) like '%%{u}'" for u in IMAGE_EXTENSIONS)
	adresler = frappe.db.sql_list(
		f"""select distinct file_url from `tabFile`
		where ifnull(is_folder, 0) = 0 and ifnull(file_url, '') != ''
		and ({uzanti_kosulu}) {kosul}"""
	)
	sayac = {"urls": len(adresler), STATUS_OK: 0, STATUS_UNREADABLE: 0, STATUS_MISSING: 0}
	for i, url in enumerate(adresler, start=1):
		olcum = store_file_facts(url)
		sayac[olcum["status"]] = sayac.get(olcum["status"], 0) + 1
		if i % commit_every == 0:
			frappe.db.commit()
	frappe.db.commit()
	return sayac


def backfill_renditions(*, only_missing: bool = True, commit_every: int = 1000) -> dict[str, int]:
	"""`ready` görsel türevlerini diskten ölç ve yaz. Dosyalara YAZMAZ (salt-okur)."""
	if not rendition_fields_ready():
		return {"skipped_no_fields": 1}
	filtre: dict[str, Any] = {"state": "ready", "format": ["in", list(RENDITION_IMAGE_FORMATS)]}
	if only_missing:
		filtre["output_colorspace"] = ["is", "not set"]
	satirlar = frappe.get_all(
		"Media Rendition", filters=filtre, fields=["name", "file_url"], limit_page_length=0
	)
	sayac = {"rows": len(satirlar), STATUS_OK: 0, STATUS_UNREADABLE: 0, STATUS_MISSING: 0}
	for i, satir in enumerate(satirlar, start=1):
		olcum = measure_url(satir["file_url"] or "")
		sayac[olcum["status"]] = sayac.get(olcum["status"], 0) + 1
		degerler = rendition_values(olcum)
		if degerler:
			frappe.db.set_value("Media Rendition", satir["name"], degerler, update_modified=False)
		if i % commit_every == 0:
			frappe.db.commit()
	frappe.db.commit()
	return sayac


def backfill_all() -> dict[str, dict[str, int]]:
	"""Kuyruk girişi (patch'in kuyruğa attığı iş)."""
	return {"files": backfill_files(), "renditions": backfill_renditions()}


def metadata_gap_report() -> dict[str, Any]:
	"""DOSYASINDA DPI ya da ICC taşımayan görsellerin sayımı (salt-okur, DB'den).

	Geriye dönük doldurma bu dosyalara DEĞER YAZMAZ — dosyada olmayan DPI'ı
	kayda "72" diye geçirmek ölçüm uydurmak olurdu. Dosyanın kendisini
	düzeltmek yeniden kodlama ister; o karar kullanıcıda.
	"""
	return {
		"files": frappe.db.sql(
			"""select th_media_facts status,
				sum(th_media_dpi = 0) no_dpi,
				sum(th_media_colorspace = 'RGB') untagged_rgb,
				count(distinct file_url) urls
			from `tabFile` where ifnull(th_media_facts, '') != '' group by th_media_facts""",
			as_dict=True,
		),
		"renditions": frappe.db.sql(
			"""select format, sum(output_dpi = 0) no_dpi,
				sum(output_colorspace = 'RGB') untagged_rgb,
				sum(ifnull(output_colorspace, '') = '') unmeasured, count(*) total
			from `tabMedia Rendition` where state = 'ready' and format in ('webp','avif','jpeg','png')
			group by format""",
			as_dict=True,
		),
	}
