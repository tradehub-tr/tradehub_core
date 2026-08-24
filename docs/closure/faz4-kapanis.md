# Faz 4 kapanış — Veri Modeli

Güncelleme: 2026-08-23. Bu dosya Faz 4 teknik durumunun güncel özetidir; insan onayı taklit edilmez.

| ID | Görev | Teknik sonuç | Kanıt |
|---|---|---|---|
| T-040 | DocType şemaları | ✅ Tamam | Resmi 15/15 DocType kurulu; policy/profile migration projection’ı; Settings yalnız Media Superadmin; gerçek ve temiz-site migrate geçti |
| T-041 | Crop intent / öncelik | ✅ Tamam | Beş basamaklı `resolve_crop`, property + INV-10 + simulator parity testleri |
| T-042 | Dedup / version hash | ✅ Tamam | Akış SHA-256, yarış retry, dört girdili hash, version URL, pHash uyarısı ve aktif version promotion |
| T-043 | Usage / orphan | ✅ Tamam | Kalıcı bind/unbind, sampled access bucket, legal hold/yeni kayıt muafiyeti, rapor-only orphan akışı |
| T-044 | Veri modeli gözden geçirme | ✅ Teknik tamam | ER/indeks planı, tam 1M/30M EXPLAIN, temiz migration, kontrollü kayıp + snapshot restore provası |

## T-040 ayrıntısı

- Eklendi: `Media Source`, `Media Policy`, `Media Policy Profile`, `Media Content Rule`.
- Seed sonucu: 9 policy, 36 profile child, 72 content rule. İkinci çalıştırmada aynı sayılar korundu.
- `after_install/after_migrate`, yeni kurulumda patch log’un atlanması durumunu da kapsar.
- İki Settings Single’ın veritabanı DocPerm kümesi yalnız `Media Superadmin`dır.
- Satıcıya açık asset/source/version/rendition/usage sorguları `Media Asset.owner_seller` zincirinden filtrelenir.
- Rendition tekilliği gerçek DB unique indeksiyle `(version_hash, profile, width, format)` olarak zorlanır.

`Media Asset.content_sha256` global UNIQUE değildir. Canlı veride üç SHA farklı kiracı/slot bağlamında tekrar ediyor; global kısıt tenant sahipliğini birleştirirdi. DB tekilliği güvenli kapsamda `asset_key=(owner_seller,slot_key,content_sha256)` ile sağlanır ve SHA ayrıca indekslidir. Bu ölçülmüş güvenlik sapması `docs/data/data-model-review.md` §12.5’te kayıtlıdır.

## Doğrulama özeti

- Saf Faz 4 çekirdek paketi: 153 test geçti, 1 yalnız Frappe bulunmayan host karşılaştırması atlandı.
- Gerçek Frappe entegrasyon seti: Settings, crop intent, version promote, orphan ve usage-source modüllerinde 74/74 geçti.
- Gerçek dev-site migrate: patch 43 = 0,542 sn; patch 44 = 0,136 sn.
- Temiz site: kurulum 24,897 sn; migrate 6,167 sn; 15/15 şema + 7/7 bileşik indeks.
- Ölçek: 1.000.000 asset, 30.000.000 rendition; yedi kritik EXPLAIN’in tamamı indeksli.
- Rollback: backup 0,704 sn; kontrollü kayıp `0/0/0`; restore 6,255 sn; geri kazanım `4/1/7` ve `9/36/72`.

Kanıtlar:

- `docs/data/data-model-review.md` §12
- `docs/data/faz4-scale-benchmark-2026-08-23.json`
- `docs/plans/rollback-doctypes.md`
- `scripts/seed_synthetic.py`

## Çıkış kapısı

Teknik veri modeli, indeks planı, migration ve rollback çıktıları tamamdır. İş akışındaki son kapı teknik sorumlu onayıdır:

```text
Onaylayan (Teknik sorumlu): ____________________
Tarih: ____________________
İmza / karar kaydı: ____________________
```

Bu alan doldurulmadan Plane’de Faz 4 kapanış/onay görevi otomatik olarak Done’a çekilmemelidir; T-040…T-044 uygulama işleri teknik olarak Done adayıdır.
