"""tradehub_core.media.pipeline.security — Faz 13 güvenlik katmanı (T-130…T-132).

İki modül, iki ayrı tehdit:

    isolation.py   Kaynak tüketimi — dekompresyon bombası, sonsuz döngü,
                   bellek şişmesi. Cevap: işi ALT SÜREÇTE, rlimit altında
                   çalıştır; süreç ölürse worker yaşamaya devam etsin.
    svg.py         Aktif içerik — SVG içindeki script/handler/harici referans.
                   Cevap: ayrıştır, tehlikeli düğüm ve öznitelikleri KALDIR.

Belge karşılığı: `docs/security/faz13-tehdit-modeli.md`.

**`import frappe` YOKTUR.** `tradehub_core/media/pipeline/__init__.py` çekirdek kuralı: `api/`
dışındaki hiçbir modül modül düzeyinde frappe'ye bağlanmaz — paket bench/site/DB
olmadan test edilebilmelidir.
"""

IMPLEMENTED: dict = {
	# T-130 · tradehub_core/media/pipeline/security/isolation.py — testi tests/test_isolation.py
	"isolation": True,
	# T-131 · tradehub_core/media/pipeline/security/svg.py — testi tests/test_svg_sanitize.py
	"svg": True,
}
