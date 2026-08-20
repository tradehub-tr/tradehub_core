# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Media RUM Sample — T-123 gerçek kullanıcı ölçümü (RUM) ham örneklemi.

Alan kümesi `tradehub_core/media/pipeline/delivery/rum.py` içindeki
`DOCTYPE_FIELDS` / `DOCTYPE_DESIGN` sözleşmesinden birebir türetildi;
`rum.doctype_matches_sample()` boş dönüyorsa şema ile saklama aynı şeyi
söylüyor demektir (test: tradehub_core.tests.test_rum_endpoint).

TASARIM KARARLARI (rum.DOCTYPE_DESIGN — gerekçeleriyle):
- `Link`/`Dynamic Link` alanı YOK: kayıt hiçbir kullanıcıya ya da belgeye
  bağlanamamalı. Bağlanabilseydi "PII yok" iddiası şemayla değil disiplinle
  korunuyor olurdu.
- Kayıtlar yalnız `tradehub_core.api.rum.collect` ucundan yazılır
  (`ignore_permissions=True`, owner=Guest ve bilgi taşımaz). Hiçbir role
  create/write izni verilmedi.
- Saklama 30 gün (KVKK m.4/2-d — ölçülü ve sınırlı süre); temizlik işi
  `tradehub_core.api.rum.purge_expired_samples` (scheduler kaydı orkestratörde).
"""

import frappe
from frappe.model.document import Document


class MediaRUMSample(Document):
	pass


def on_doctype_update() -> None:
	"""`creation` üzerine indeks — rum.DOCTYPE_DESIGN["indexes"] şartı.

	Saklama temizliği (`purge_expired_samples`) ve pencere bazlı toplama
	(`aggregate`) hep `creation` aralığıyla sorgular; indeks olmadan her
	temizlik tam tablo taraması olurdu.
	"""
	frappe.db.add_index("Media RUM Sample", ["creation"])
