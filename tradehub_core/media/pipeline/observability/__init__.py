"""tradehub_core.media.pipeline.observability — Faz 13 gözlemlenebilirlik katmanı (T-133).

    metrics.py   Prometheus text exposition format 0.0.4 — sayaç/gösterge/histogram
    logging.py   Korelasyon ID'li yapılandırılmış JSON log + PII maskeleme

İkisi de BAĞIMSIZ ve bağımlılıksızdır: `prometheus_client` kurulu DEĞİL
(konteynerde `ModuleNotFoundError` ile ölçüldü, 2026-08-18) ve `import frappe`
YOKTUR. Sebep `tradehub_core/media/pipeline/__init__.py` çekirdek kuralı: paket bench/site/DB
olmadan test edilebilmelidir. Gözlemlenebilirlik katmanının ölçtüğü hattan
DAHA KIRILGAN olması kabul edilemez — metrik toplayıcı bir import hatası
yüzünden düşerse, hattı görme yeteneğini de kaybederiz.
"""

IMPLEMENTED: dict = {
	# T-133 · tradehub_core/media/pipeline/observability/metrics.py — testi tests/test_observability.py
	"metrics": True,
	# T-133 · tradehub_core/media/pipeline/observability/logging.py — testi tests/test_observability.py
	"logging": True,
}
