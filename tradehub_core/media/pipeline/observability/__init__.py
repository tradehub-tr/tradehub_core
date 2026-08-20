"""tradehub_core.media.pipeline.observability — Faz 13 gözlemlenebilirlik katmanı (T-133).

    metrics.py     Prometheus text exposition format 0.0.4 — sayaç/gösterge/histogram
    logging.py     Korelasyon ID'li yapılandırılmış JSON log + PII maskeleme
    instrument.py  Ölçüm noktaları — hattı değiştirmeden metriğe bağlama
    exporter.py    Çok süreçli toplama: parça yaz, birleştir, tek `/metrics` gövdesi
    alerts.py      Alarm kuralı (Prometheus YAML) + Grafana panosu ÜRETİCİSİ

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
	# T-133 · instrument.py — testi tests/test_observability_instrument.py (26 test).
	# UYARI: kod GERÇEK ama `install()` HİÇBİR YERDEN ÇAĞRILMIYOR; bağlama
	# noktası `hooks.py`dir ve bu görevin kapsamı dışındadır. "Var" ile
	# "devrede" farkı burada açıkça yazılıdır.
	"instrument": True,
	# T-133 · exporter.py — testi tests/test_observability_exporter.py (19 test).
	# UYARI: `/metrics` HTTP ucu YOK (uç `api/` altında olurdu, kapsam dışı).
	"exporter": True,
	# T-133 · alerts.py — testi tests/test_observability_alerts.py (20 test).
	# UYARI: üretilen kural ve pano metni HİÇBİR YERE KURULMADI; Prometheus ve
	# Grafana bu projede kurulu değil ve `docker/` kapsam dışı.
	"alerts": True,
}

#: Kütüphane hazır ama ÜRETİMDE DEVREDE OLMAYAN parçalar — "yazıldı" ile
#: "çalışıyor" karıştırılmasın diye ayrı bir sözlük. Her satırın karşısında
#: eksik olan TEK adım yazılı; ayrıntı `docs/reports/42-t133-gozlemlenebilirlik.md`.
NOT_WIRED: dict = {
	"instrument.install": "hooks.py `after_migrate`/boot kaydı yok",
	"exporter.metrics_response": "`/metrics` HTTP ucu yok (api/ kapsam disi)",
	"alerts.to_prometheus_rules": "Prometheus kurulu degil, kural dosyasi yuklenmiyor",
	"alerts.grafana_dashboard": "Grafana kurulu degil, pano ice aktarilmadi",
}
