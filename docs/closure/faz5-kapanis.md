# Faz 5 Kapanış Dosyası — Depolama, S3/CDN, Retention

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-055 hazırlığı — imza atılmaz.)

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| Depolama kabul raporu (4 mod) | DevOps + teknik sorumlu |

## 2. Kapıyı karşılayan ölçümler

| Kalem | Durum | Kanıt |
|---|---|---|
| 4 kip sözleşme testi (sahte istemci) | **KARŞILANDI** | test_storage_adapters **137 OK** — local/s3/mirror/tiered aynı `StorageContractMixin` gövdesi (23, 55 §7.2). |
| 4 kip gerçek S3 uyumlu servise karşı | **KARŞILANDI (MinIO)** | test_storage_adapters_minio **91 OK, 0 skip** her koşumda (23; 55 §7.4; 57b 22:47:42). Ölçülmüş medyanlar (256 KiB): local put 2,07 ms · s3 put 45,49 ms · mirror(inline) 317,42 ms · tiered put 1,94 ms; demote 51,06 ms; kesinti yolunda mirror **fail-safe** (yerel put başarılı, failed:1). |
| Fabrika düşüş sözleşmesi | **KARŞILANDI** | 8 kombinasyon ölçüldü: `s3_enabled=0` iken s3/mirror/tiered → local'e sebep raporuyla düşüyor (23). |
| CDN teslim (dev edge) | **KARŞILANDI (dev)** | 27-t052-cdn-teslim.md canlı curl: içerik-adresli türev `immutable` · private 403 + `private, no-store` · imzalı indirme 200 (634.926 B) · byte-range 206 · bozuk/süresi geçmiş imza 403×4. |
| **T-055 kabul paketi** | **BUGÜN OLUŞTURULDU — Local kipi CANLI GEÇTİ** | `tradehub_core/tests/acceptance/test_storage_acceptance.py` (bu dalga, W6). Konteyner koşumu (istoc-dev-backend-1, 2026-08-20): **Ran 14 — OK (skipped=4)**. Gerçek koşan 10 test: Local uçtan uca (içerik-adresli ad, dedup created=False, atomik yazım kalıntısız, public↔private taşıma, imzalı URL doğrulama/kurcalama reddi), boto3 saflığı (taze alt süreçte `sys.modules` kontrolü), `build_storage` local planı, S3-istenmiş-ama-kapalı → yerel düşüş + sebep, retention kuru koşumu 0 silme. **Skip 4**: s3_primary / mirror / tiered uçtan uca + canlı yanlış-kimlik — gerekçe: `MEDIA_ENGINE_S3_*` kabul ortamı tanımsız; dev MinIO'ya örtük bağlanmak kabul kanıtı sayılmaz. Sahte yeşil yok. |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK)

1. **S3/Mirror/Tiered kabul senaryoları SKIP** — kabul ortamı (gerçek hedef S3 + `MEDIA_ENGINE_S3_*`) sağlanınca aynı dosya koşturulmalı; bugünkü kanıt yalnız adaptör-sözleşme düzeyi (23'ün 91 MinIO testi).
2. **Retention dry-run raporu "incelenmiş ve onaylanmış" değil** — "onaylanmış bir insan eylemidir, gerçekleşmedi" (57b T-055(4)). Kuru koşumun hiçbir şey silmediği bugün testle kanıtlandı; onay İNSAN'da.
3. **`test_retention_gc` bayat test** — 37 koşan / **1 fail**: `test_hooks_kaydi_henuz_yok` ("run_scheduled_gc_originals artık hooks.py'de kayıtlı — rapor 40 güncellenmeli") (55 §7.4/Y-5, 57b §1.4). Paket bu düzeltilmeden yeşile dönmez.
4. **T-054 DR: 0 yedek seti** — canlı `backup.list_sets()` → **0** (57b 22:51:34); `backup-dr.md` hedef RPO 24 sa / RTO ≤30 dk, kayıtlı gerçek: "RPO Sınırsız / RTO Ölçülemez"; DB restore süresi ÖLÇÜLMEDİ; `verify()` hiçbir scheduler'da yok. → **İNSAN/DevOps provası şart.**
5. **Üretim kalıcılığı**: boto3 bench venv'ine elle kuruldu — imaj rebuild'de **kaybolur**; `requirements.txt`'te yok (23 §2.2, 55 Y-6). `docker/` git reposu değil → MinIO compose bloğu + gateway.conf (+91 satır) **versiyonsuz** (23 §2.1, 27 §8.1).
6. **`cdn_purge_*` alanlarını okuyan 0 kod** — T-052 kriter 3 yapısal açık (55 Y-7).
7. **Kip açılabilirliği**: 23 hükmü — local zaten açık; **s3/mirror/tiered = "hayır"** (mirror'a zamanlanmış `reconcile` yok; tiered `age_days=90` ölçüm değil varsayım; B-02/B-03/B-04/B-05 bulguları). 25 §4: ayar ekranı `backend != local` kaydını `blocker_ack` istemeden reddediyor (bilinçli kapı).
8. **Bayrak durumu**: `media_pipeline_enabled=1` DEV'de (69 §1); `media_retention_gc_enforce*` anahtarları yok → GC kuru koşum (55 §7.5).

## 4. Kapı durumu özeti

**Kapı: KISMEN KARŞILANDI (bugünkü W6 işiyle).** Dünkü durum "istenen çıktı hiç üretilmedi" idi (55 §9); bugün `tests/acceptance/` paketi var ve **Local kipi konteynerde gerçekten geçti (10 test)**. Kalanlar: S3'lü 3 kipin kabul ortamında koşumu, retention dry-run onayı (İNSAN), DR provası (İNSAN/DevOps), test_retention_gc bayat testinin düzeltilmesi.

## 5. Kaynak raporlar
`docs/reports/`: 23-t051-s3-adaptor.md · 55-d2-faz3-5-kapanis.md §7 · 57b-durum-faz4-7.md · 25-t051-depolama-ayarlari.md · 26-t053-saklama-gc.md · 27-t052-cdn-teslim.md · 40-t043-kullanim-gc.md · 83-w6-kapanis-dosyalari.md (T-055 koşum kanıtı) · `tradehub_core/tests/acceptance/test_storage_acceptance.py`

## Ek ölçüm — 2026-08-20 (W8, rapor 94 §9)

- **§3.1 (S3/Mirror/Tiered kabul SKIP) → DEV-KABULDE KAPANDI, bağımsız yeniden koşumla:** `MEDIA_ENGINE_S3_*` compose MinIO'suna açıkça işaret ederek `test_storage_acceptance` **Ran 14 — OK, 0 skip** (s3_primary/mirror/tiered/yanlış-kimlik dahil; geçici `t055-kabul-w8` bucket'ı koşum sonrası silindi). Rapor 87'nin 4/4'ü bu koşumda tekrarlandı. Gerçek hedef S3'te koşum hâlâ İNSAN/DevOps işi.
- **§3.3 (bayat bekçi) → KAPANDI:** `test_retention_gc`'nin `test_hooks_kaydi_henuz_yok` bekçisi düzeltilmiş — artık kaydın VARLIĞINI sabitliyor (kod bugün okundu; paketin tam koşumu bu oturumda tekrarlanmadı).
- **T-053 "kayıtlı + ÇALIŞIR" ölçüldü:** scheduler **enabled**; 3 GC işi (`run_scheduled_gc` + `_originals` + `_derivatives`) `stopped=0` ve bugün 09:13–09:14'te **Complete** (`Scheduled Job Log`). Enforce anahtarları yok → koşumlar kuru-koşum, silme 0 — tasarlanan güvenli durum.
- **T-052 canlı curl (bu koşum):** private **403** · imzasız download **403** · misafir get_signed_url **403** · Range → **206** · Content-Type doğru. **YENİ BULGU:** üretim türev adresleri artık version_hash'li (`/files/media/{asset}/{64hex}/…`, 92/92 — "içerik değişince URL değişir" fiilen sağlandı) ama nginx `immutable` map'i yalnız eski `/files/{2hex}/{32hex}.ext` kalıbını tanıyor → gerçek türevler `max-age=300, must-revalidate` ile dönüyor. Kapanış için 1 satırlık map güncellemesi gerekiyor (kod yasağı gereği bu koşumda yapılmadı). `cdn_purge_*` okuyan kod bugün de 0 (§3.6 sürüyor).
- **§3.5 kısmen zayıfladı:** boto3 1.34.162 bench venv'inde ve bugünkü 14/14 koşum onunla yapıldı; `docker/` versiyonsuzluğu ve requirements kalıcılığı sorusu değişmedi.

## 6. Onay

```
Onaylayan (DevOps): ______________________   Tarih: ______________   İmza: ______________
Onaylayan (Teknik sorumlu): ______________________   Tarih: ______________   İmza: ______________
```
