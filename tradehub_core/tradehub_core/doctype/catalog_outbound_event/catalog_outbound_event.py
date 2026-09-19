# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Catalog Outbound Event — mağazanın dış sisteme giden stok olayı (MOGEM-665 · 5. aşama).

Kayıtları `tradehub_core.integration.outbound` üretir ve iletir; bu sınıf yalnız
şema sahibidir. `listing` bilinçli olarak **Data** (Link değil): olay geçmişi ürünün
ömründen bağımsız bir denetim kaydıdır; Link olsaydı satıcı ürünü silerken
LinkExistsError ile kilitlenirdi. Satıcı yalnız kendi mağazasının olaylarını görür
(`permissions.catalog_outbound_event_query_conditions`).
"""

from frappe.model.document import Document


class CatalogOutboundEvent(Document):
	pass
