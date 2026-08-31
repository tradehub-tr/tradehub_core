# Kapsamlı Medya Denetim Paketi (KD)
#
# Bu paket, mevcut test korpusundan BAĞIMSIZ olarak yazıldı: her iddia
# kaynak kodun okunmasından türetildi, var olan bir testin beklentisi
# kopyalanmadı. Amaç mevcut testleri tekrar etmek değil, onların
# doğrulamadığı davranışı (girdi/çıktı sözleşmeleri, doğrulamalar,
# sınır değerler, güvenlik kaçışları, regresyon) ölçmektir.
#
# Koşum:
#   export DOCKER_HOST=unix:///var/run/docker.sock
#   docker exec istoc-backend bench --site tradehub.localhost run-tests \
#       --module tradehub_core.tests.kapsamli.test_kd_01_probe_kapi
#
# Modül düzeni:
#   test_kd_01_probe_kapi        künye çıkarımı + kabul kapısı (birim + sınır)
#   test_kd_02_normalize         normalleştirme sözleşmesi (DPI/yön/alfa/ölçü)
#   test_kd_03_siniflandirma     sınıflandırma + format zinciri + render
#   test_kd_04_video             video karar tablosu + benefit gate + poster
#   test_kd_05_depolama          storage adapter'ları + retention + imzalı URL
#   test_kd_06_politika_kota     PolicyEngine + upload policy + kota
#   test_kd_07_guvenlik          SVG/XSS, bomba, polyglot, yol kaçışı, izolasyon
#   test_kd_08_yetki_sizinti     izin/tenant sızıntısı + ayar sırları
#   test_kd_09_api_sozlesme      zarf, idempotency, chunked upload, manifest
#   test_kd_10_seo               medya SEO alanları, watch page, JSON-LD, sitemap
#   test_kd_11_regresyon         golden/invariant regresyon kapıları
#   test_kd_12_maymun_fuzz       monkey/fuzz — rastgele ve bozuk girdi dayanıklılığı
#   test_kd_13_smoke             uçtan uca duman testi (hızlı, her koşumda)
