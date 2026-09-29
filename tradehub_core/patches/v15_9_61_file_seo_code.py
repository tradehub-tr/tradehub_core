"""File.seo_code — SEO'lu görsel adresinin kısa kodu (spec 2026-09-28-seo-gorsel-adresi).

İdempotent: alan create_custom_fields(update=True); doldurma yalnız boş satırlara.

Final review I-1: kod YALNIZ görsel uzantılı (`seo_url.GORSEL_UZANTILAR`), private
olmayan ve hassas doctype'a bağlı olmayan satırlara atanır. `temizle()` daha önce
(ilk sürüm) koda kavuşmuş belge/video/hassas satırların kodunu siler — patch'in
kendisi zaten her koşuda çağırır; patch'in çoktan koştuğu ortamda (lokal) elle:

	bench --site <site> execute tradehub_core.patches.v15_9_61_file_seo_code.temizle
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "seo_code",
			"label": "SEO Code",
			"fieldtype": "Data",
			"length": 32,
			"hidden": 1,
			"no_copy": 1,
			"search_index": 1,
			"module": "Tradehub Core",
		}
	]
}


def execute() -> None:
	create_custom_fields(FIELDS, update=True)
	frappe.db.commit()
	from tradehub_core.media import seo_url

	temizle()
	hassas = seo_url.hassas_doctypes()
	urls = frappe.db.sql(
		"""select distinct file_url from `tabFile`
			where is_folder=0 and is_private=0 and ifnull(seo_code,'')=''
			and ifnull(attached_to_doctype,'') not in %s
			and file_url regexp '^/files/[0-9a-f]{2}/[0-9a-f]{32}\\\\.'
			and file_url regexp %s""",
		(hassas, seo_url.GORSEL_UZANTI_SQL_RE),
		pluck=True,
	)
	for url in urls:
		seo_url.assign_code(url)
	frappe.db.commit()


def temizle() -> dict:
	"""Kapsam dışı satırların `seo_code`'unu sil (idempotent; ikinci koşuda 0).

	1. Görsel olmayan uzantı (mp4/txt/tif/pdf…).
	2. Hassas doctype'a bağlı ya da private satır — ve AYNI hash'i paylaşan tüm
	   satırlar (kod hash başına tek; biri hassassa içerik hassas).

	Ters referans (`Order.receipt_url` gibi, `attached_to_*` boş) burada taranmaz:
	yetki `seo_url.resolve` → `hassas_mi` kontrolündedir, kod tek başına erişim vermez.
	"""
	from tradehub_core.media import seo_url

	frappe.db.sql(
		"""update `tabFile` set seo_code=NULL
			where ifnull(seo_code,'')!='' and file_url not regexp %s""",
		(seo_url.GORSEL_UZANTI_SQL_RE,),
	)
	gorsel_disi = frappe.db.sql("select row_count()")[0][0]
	kodlar = frappe.db.sql(
		"""select distinct seo_code from `tabFile`
			where ifnull(seo_code,'')!='' and (is_private=1 or attached_to_doctype in %s)""",
		(seo_url.hassas_doctypes(),),
		pluck=True,
	)
	hassas = 0
	if kodlar:
		frappe.db.sql("update `tabFile` set seo_code=NULL where seo_code in %s", (tuple(kodlar),))
		hassas = frappe.db.sql("select row_count()")[0][0]
	frappe.db.commit()
	sonuc = {"gorsel_disi": gorsel_disi, "hassas": hassas}
	print(f"seo_code temizlik: {sonuc}")
	return sonuc
