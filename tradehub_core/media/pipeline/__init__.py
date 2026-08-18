"""media_engine — İstoç medya motoru kütüphanesi.

**Bu bir Frappe app'i DEĞİLDİR.** Kaynak tasarım dokümanı ayrı bir
`media_engine` app'i öngörüyor; İstoç'ta medya `tradehub_core` içinde bir
modüldür ve bu paket onun YANINDA duran bir kütüphanedir. Gerekçe:
`docs/sad/SAD-v1.0.md` §2.3 (S-01 sapması).

İçerik:
    policy/     Faz 2 çıktısı — slot politikası şeması ve 9 slot dosyası (veri).
    contracts/  Faz 3 — beş çekirdek arayüz (`typing.Protocol`).
    fakes/      Faz 3 — sözleşme testleri için bellek-içi sahte uygulamalar.
"""

__version__ = "0.1.0"

# ── Faz 3 (T-032) alt paket haritası ────────────────────────────────────
#
# `media_engine` iki katmanlıdır ve ikisi farklı soruyu cevaplar:
#
#     contracts/ + fakes/   arayüz (Protocol) ve sözleşme testleri için sahteler
#     api/ core/ storage/ delivery/ image/ video/
#                           çalışan uygulama sınırları
#
# Bu paketlerin hangisi Faz 3 sonunda GERÇEK kod, hangisi yalnız sözleşmesini
# ilan eden iskelet — aşağıdaki sözlük söyler. Her iskelet paketin kendi
# `__init__.py`'sinde de `IMPLEMENTED = False` bayrağı vardır; bu sözlük onun
# tek bakışta okunabilen özetidir. "Kod mu iskelet mi" sorusu tahmine
# bırakılmaz.
#
# ÇEKİRDEK KURALI: `api/` dışındaki hiçbir modül MODÜL DÜZEYİNDE `import
# frappe` yapmaz — paket bench/site/DB olmadan test edilebilir olmalıdır.
# `tests/test_state_machine.py::test_cekirdekte_frappe_importu_yok` doğrular.
IMPLEMENTED: dict[str, bool] = {
	# T-080…T-085 · tradehub_core/media/pipeline/api/{spec,upload,crop,delivery,admin,envelope}.py
	# — testi tests/test_api_contracts.py
	"api": True,
	# T-050…T-054 · tradehub_core/media/pipeline/storage/ — testi tests/test_dedup.py
	"storage": True,
	# T-052 · delivery/signed.py · T-083 · delivery/manifest.py
	"delivery": True,
	# T-063/T-064/T-066 · tradehub_core/media/pipeline/image/{render,reprocess,report}.py
	# — testleri tests/test_render.py + tests/test_render_regression.py
	"image": True,
	# T-070…T-074 · tradehub_core/media/pipeline/video/{probe,decision,transcode,poster,hls}.py
	# — testleri tests/test_video_decision.py + tests/test_video_transcode.py
	"video": True,
	"core.errors": True,
	"core.probe": True,
	"core.state": True,
	"core.jobs": True,
	# T-100 · tradehub_core/media/pipeline/core/crop_geometry.py (+ .ts ikizi)
	# — testi tests/test_crop_geometry.py (37 test). TS paritesi node ile ÖLÇÜLDÜ:
	#   584 vektörde en büyük sapma 0,0 px.
	"core.crop_geometry": True,
	"policy.engine": True,
	# T-013 · tradehub_core/media/pipeline/quality/ssim.py — testi tests/test_quality_ssim.py (21 test)
	"quality.ssim": True,
	# T-110/T-112 · tradehub_core/media/pipeline/simulator/{devices,placements}.json + srcset.py
	# — testi tests/test_simulator_srcset.py (34 test). T-111/113/114/115 arayüz
	#   katmanıdır ve storefront/panel salt okunur olduğu için YAZILMADI;
	#   planı docs/ui/faz11-simulator.md.
	"simulator": True,
	# T-143 · tradehub_core/media/pipeline/migration/backfill.py — testi
	# tests/test_migration_backfill.py. Orkestratör GERÇEK koddur; üretim
	# adaptörleri (`FrappeBatchRunner`, `FrappeQueueDepth`) bench/site
	# olmadan KOŞULAMAZ ve bu oturumda koşulmadı — modül docstring'inde
	# açıkça yazılı.
	"migration": True,
	# T-130 · tradehub_core/media/pipeline/security/isolation.py — testi tests/test_isolation.py
	# (36 test). Alt süreç izolasyonu + rlimit. ÜRETİM HATTINA HENÜZ BAĞLI DEĞİL:
	# bağlama noktaları docs/security/faz13-tehdit-modeli.md §6 Ö-5'te listeli.
	"security.isolation": True,
	# T-131 · tradehub_core/media/pipeline/security/svg.py — testi tests/test_svg_sanitize.py
	# (52 test). docs/standards/logo.md §6.2 SVG-1…SVG-10'un kod karşılığı.
	# SVG yükleme kapıları AÇILMADI; bu modül o açılışın ÖN KOŞULUDUR.
	"security.svg": True,
	# T-133 · tradehub_core/media/pipeline/observability/{metrics,logging}.py
	# — testi tests/test_observability.py (72 test)
	"observability.metrics": True,
	"observability.logging": True,
}

# ── Faz 13'ün belge çıktıları (T-132 / T-134) ───────────────────────────
#
# Kod olmayan çıktılar da burada kayıtlı: "bu faz ne üretti" sorusunun cevabı
# tek yerde dursun, IMPLEMENTED sözlüğüne bakan biri belgeleri kaçırmasın.
DOCS: dict = {
	"T-132": "docs/security/faz13-tehdit-modeli.md",
	"T-134": "docs/security/faz13-gdpr.md",
}
