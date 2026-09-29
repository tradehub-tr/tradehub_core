"""TradeHub adaptörleri (14.1 — "mevcut Frappe/TradeHub kabiliyetlerine adaptörler").

Kural: `tradehub_core.seo` KOPYALANMAZ, sarılır. Bu paket seo_helper_cms'in
tradehub_core'a dokunduğu TEK yerdir; imza değişirse yalnız burası kırılır
(uyumluluk testi: `tests/test_adapters.py`).
"""
