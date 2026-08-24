# ADR-0004 — Saf çekirdek / Frappe kabuğu ayrımı: `api/` dışında modül düzeyinde `import frappe` yok

**Durum:** Kabul edildi · yürürlükte · testle kilitli
**Tarih:** Faz 3 (T-032) · son doğrulama 2026-08-23
**İlgili:** ADR-0003 (kütüphane olma kararının korunan yarısı)

---

## Bağlam

ADR-0003 medya motorunu ayrı app değil kütüphane yapmaya karar verdi. Ama
"kütüphane" olmak bir dizin adı değil, bir **bağımlılık** ifadesidir: `import
frappe` yapan bir modül site, bench ve veritabanı olmadan çalışmaz, dolayısıyla
tek başına test edilemez.

Bu kütüphanede test edilebilirliğin bedeli somut: sözleşme testleri (75),
politika motoru testleri (38), kırpma geometrisi (37), SSIM (21), izolasyon (36),
SVG (52) — hepsi bench olmadan koşabilmeli.

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — Nerede gerekiyorsa `import frappe` | En kolay yazım. Bedeli: paketin hiçbir parçası bench'siz koşmaz; CI'da tam bir Frappe kurulumu şart. |
| **B (SEÇİLEN)** — `api/` **kabuk**, geri kalanı **saf çekirdek**: çekirdekte modül düzeyinde `import frappe` yasak | Çekirdek bench'siz test edilir. Bedeli: frappe'ye gerçekten ihtiyaç duyulan yerlerde fonksiyon içi (tembel) import ya da enjeksiyon gerekir. |
| C — Tam bağımlılık enjeksiyonu (frappe hiç import edilmez, her şey dışarıdan geçer) | En saf. Bedeli: her çağrı noktasında adaptör yazımı; bu boyutta bir modül için aşırı. |

## Karar

`tradehub_core/media/pipeline/__init__.py` içinde yazılı olan **çekirdek kuralı**:

> `api/` dışındaki hiçbir modül **modül düzeyinde** `import frappe` yapmaz —
> paket bench/site/DB olmadan test edilebilir olmalıdır.

Frappe'ye gerçekten ihtiyaç duyulan yerlerde **fonksiyon içi bilinçli geç import**
kullanılır ve `# noqa: PLC0415` ile işaretlenir
(`core/usage.py:432`, `core/usage.py:442`, `storage/mirror.py:241`).

Frappe'ye bağlanma işi **köprüde** toplanır: `tradehub_core/media/pipeline_bridge.py`
motoru `File.after_insert` kancasına bağlayan **tek** noktadır.

## Gerekçe

- Testin ucuz olması, ölçümün ucuz olması demektir. Bu depodaki karar kültürü
  (ADR-0006, ADR-0008, ADR-0010, ADR-0013) ölçüme dayanıyor; ölçüm bench
  gerektirseydi çoğu koşulmazdı.
- Kural **tahmine bırakılmadı**: `tests/test_state_machine.py::test_cekirdekte_frappe_importu_yok`
  doğrular. Ayrıca her iskelet alt paketin `__init__.py`'sinde `IMPLEMENTED`
  bayrağı var ve `pipeline/__init__.py` bunların tek bakışta okunabilen özetini
  taşıyor — "kod mu iskelet mi" sorusu tahmine bırakılmaz.

## Sonuçlar

### Olumlu

- Kural modül başlıklarında **tek tek yazılı** ve bu yüzden kendi kendini
  savunuyor: `core/crop.py:45`, `core/dedup.py:30`, `core/probe.py:1`,
  `core/usage.py:37`, `image/normalize.py:50`, `image/classify.py:52`,
  `image/lqip.py:47`, `image/probe.py:34`, `security/svg.py:62`,
  `security/__init__.py:13`, `observability/metrics.py:55`,
  `observability/logging.py:40`.
- Frappe'siz koşum kanıtlandı: 75 sözleşme + 47 durum/iskelet testi site
  olmadan geçiyor; donmuş contract paketi mypy'da 0 hata.
- Kırpma geometrisinin TypeScript ikizi (`core/crop_geometry.ts`) ancak saf
  çekirdek sayesinde birebir eşlenebildi: **584 vektörde en büyük sapma 0,0 px**
  (ölçüldü).

### Korunan sınırlar

- Fake uygulamalar tek başına yeterli kanıt sayılmaz. Contract matrisi fake ile
  birlikte gerçek PolicyEngine, `PillowImageEngine` ve `FfmpegVideoEngine`
  imza/davranışını doğrular; CI'da gerçek ffmpeg smoke testi çalışır.
- Kanonik çalışma-zamanı politika kaynağı yalnız `policy/slots/*.json`'dır;
  `docs/standards/policies` belge/ölçüm izdüşümüdür.
- Frappe gerektiren işlerde tembel import veya kabuk adaptörü bakım maliyeti
  getirir; bu maliyet saflık testinin bilinçli karşılığıdır.

## Geri dönüş yolu

Saf çekirdek API'si bir zorunlu Frappe işlemini dependency injection ile ifade
edemez ve bunun bakım maliyeti ölçülürse yalnız ilgili adapter kabuğa alınır;
çekirdeğe doğrudan `import frappe` eklenmez. `test_state_machine` ve import
tarama kapısı kırılırsa değişiklik geri çevrilir.
