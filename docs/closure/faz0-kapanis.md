# Faz 0 Kapanış Dosyası — Keşif

**Güncel teknik kapanış:** 2026-08-23

**Kapsam:** T-000…T-009
**Kural:** Faz 0 üretim davranışı değiştirmez; envanter, ölçüm, fixture,
karar girdisi ve kapanış kanıtı üretir.

> 2026-08-20 tarihli önceki kapanış anlık görüntüsü eskimiştir. Video 7/8,
> gerçek fotoğraf yok, mobil ölçüm yok, CSV yok, pyvips yok ve 40 dosya
> sınıflandırılmadı maddelerinin tamamı aşağıdaki güncel kanıtlarla kapanmıştır.
> Tarihsel ayrıntı `docs/reports/07-faz0-kapanis.md` içinde korunur.

## 1. Görev tablosu

| ID | Görev | Teknik durum | Güncel kanıt / karar |
|---|---|---|---|
| **T-000** | Ortam ve bağımlılık envanteri | ✅ **DONE-ready** | Runtime, codec, servis, worker, limit ve sürümler yeniden ölçüldü; bulunmayan araçlar “kurulu değil” olarak açık. `00-ortam-envanteri.md` güncel eki. |
| **T-001** | Upload slot/yüzey envanteri | ✅ **DONE-ready** | Backend **41/41** dosya alanı raporda; Medya Kütüphanesi `MediaUploader` ve admin Seller Verification yüklemesi güncel eke işlendi. |
| **T-002** | Frappe File akışı / storage | ✅ **DONE-ready** | Yükleme→File hook→public/private storage→teslim akışı, private auth ve üçten fazla extension point `01-dosya-akisi.md` içinde. |
| **T-003** | Üretim-benzeri medya istatistiği | ✅ **DONE-ready** | 5.126 File satırı; 2.914 eşsiz public URL; dokuz slotun tamamında p50/p90/p99; ≥20 anomali; aggregate JSON + `media-stats.csv`. |
| **T-004** | Render/LCP taban çizgisi | ✅ **DONE-ready** | Dört sayfa × iki cihaz = 8 koşum; 1.231 yerel-görselli ürün içinden en ağır 10 seçilip iki profilde 20 ek koşum. |
| **T-005** | Rol, tenant ve private erişim | ✅ **DONE-ready** | İzin matrisi mevcut; negatif tenant 22/22, private signed URL 17/17 geçti. |
| **T-006** | Golden fixture korpusu | ✅ **DONE-ready** | 36 görsel + 11 video + 10 izole kötücül = **57/57**, SHA-256 doğrulamalı, 90,48 MiB <1 GiB; gerçek foto/video örnekleri var. |
| **T-007** | Kütüphane/engine benchmark | ✅ **DONE-ready** | 360/360 ölçüm; Pillow+draft sayısal karar; pyvips/libvips ve FFmpeg güncel imajda; tekrar betiği + CI compile kapısı. |
| **T-008** | Depolama/maliyet tabanı | ✅ **DONE-ready** | Formül, üç 12-ay senaryosu, eager/lazy sayısal karşılaştırma; güncel 904 MiB public + 188 MiB private ve boş MinIO durumu eklendi. |
| **T-009** | Faz 0 kapanış / exit approval | 🟡 **TEKNİK DONE, insan onayı bekliyor** | Yedi keşif raporu, fixture korpusu, açık soru atamaları ve otomatik kapanış testi hazır. Plane'de Done'a çekme ve Platform yöneticisi imzası insan onayıdır. |

**Teknik çıktı tamlığı:** 10/10 görevin artefaktı ve doğrulama kanıtı vardır.

**Resmî iş akışı durumu:** T-000…T-008 Done'a hazır; T-009 Platform yöneticisi
onayından sonra Done'a çekilir.

## 2. Çıkış kapısı

| Zorunlu çıktı | Sonuç | Kanıt |
|---|---|---|
| Yedi keşif raporu | ✅ | T-000, T-001, T-002, T-003, T-004, T-005 ve T-008 raporları; T-006/T-007 ek teknik raporları da vardır. |
| Golden korpus | ✅ | `tradehub_core/tests/fixtures/media/manifest.json`: 57 kayıt, 57 GEÇTİ, 0 KALDI. |
| Makine-okunur medya istatistiği | ✅ | `tradehub_core/tests/fixtures/media-stats.csv` + iki aggregate JSON. |
| Mobil + desktop performans | ✅ | 8 çekirdek + 20 worst-10 ürün koşumu. |
| Açık soru listesi ve ataması | ✅ | §4; her teknik soru Faz 1 veya Faz 2 sahibiyle eşleşir. |
| Otomatik bütünlük kapısı | ✅ | `test_faz0_closure.py`; unittest ve `pytest -m fixtures`; 10 dakikalık CI timeout. |
| Platform yöneticisi onayı | ⏳ | Bu belge imza atamaz; aşağıdaki insan onay bloğu bekler. |

## 3. Eski bloklayıcıların kapanışı

| Eski açık | Güncel sonuç |
|---|---|
| K-1: 40 public hash eşleşmesi sınıflandırılmadı | ✅ 44 dosyanın tamamı görsel olarak sınıflandırıldı; dört yapısal receipt sızıntısı private'a alındı, kalan 40 ürün/logo vb. zararsız ortaklık; belirsiz 0. `19-d2-hash-ortusme.md`. |
| Video fixture 7/8 | ✅ 11 video; dördü gerçek DEV kaynağı. |
| Gerçek fotoğraf yok | ✅ Canon fotoğraf + Adobe RGB ICC'li gerçek kaynak. |
| `media-stats.csv` yok | ✅ Kanonik repo yolu `tradehub_core/tests/fixtures/media-stats.csv`. |
| Mobil profil yok | ✅ Dört sayfa mobil+desktop; worst-10 için 20 ek koşum. |
| pyvips yeniden çalışmıyor | ✅ pyvips 2.2.3 / libvips 8.14.1 güncel backend imajında. |
| Ortam envanteri “Docker kapalı” | ✅ 15 çalışan servis üzerinden güncellendi. |

Üretim imajı erişimi Faz 0 yerel keşif çıktısını bloke etmez; prod/rollout
paritesi Faz 14 go-live kapısında yeniden doğrulanır. Faz 0 bu kontrolü
“yapıldı” diye işaretlemez.

## 4. Açık sorular — sahip ve devir

Bu sorular keşfin çıktısıdır; Faz 0 artefakt eksikliği değildir.

| ID | Soru / bulgu | Karar sahibi | Devir |
|---|---|---|---|
| F0-Q01 | Admin Seller Verification yüklemesi seller-profile isteyen ortak belge ucuyla salt admin oturumunda çalışıyor mu? | Backend + güvenlik | **Faz 1 / T-017**, entegrasyon testi; gerekirse Faz 2 belge slotu sözleşmesi |
| F0-Q02 | Harici ürün/kategori/avatar URL'leri yerelleştirilecek mi? | Ürün + depolama | **Faz 1 / T-018** maliyet-dedup kararı; **Faz 2 / T-028** migration |
| F0-Q03 | Üçüncü taraf avatar servisi medya politikasının dışında kalabilir mi? | Platform mimarisi | **Faz 1 / T-018** |
| F0-Q04 | İçerik-adresli fakat `tabFile` kayıtsız 4.661 disk adayı nasıl sınıflandırılacak? | Depolama + operasyon | **Faz 1 / T-018**, sonra **Faz 2 / T-028** |
| F0-Q05 | Ürün videosuna azami süre kuralı eklenecek mi? | Video + ürün | **Faz 1 / T-016** ölçüm kararı; **Faz 2 / T-023** standardı |
| F0-Q06 | En ağır ürünlerde 18,48 sn mobil LCP ve 21,1 MB desktop transfer için hangi profil bütçesi seçilecek? | Frontend + medya mimarisi | **Faz 1 / T-013–T-015** kalite/preflight kararı; uygulama Faz 12 |
| F0-Q07 | MinIO'ya geçiş hangi `r`, egress ve istek eşiğinde tetiklenecek? | DevOps + maliyet | **Faz 1 / T-018**; **Faz 2 / T-028** |
| F0-Q08 | Compose'da tanımlı `queue-media-video` ne zaman deploy edilecek? | DevOps | **Faz 1 / T-019** karar kaydı; gerçek rollout Faz 14 |

Kanonik politika kaynağı sorusu açık değildir: ADR-0016 ve çalışan
`PolicyEngine` uyarınca kaynak `tradehub_core/media/pipeline/policy/slots/*.json`;
`docs/standards/policies` tarihsel/belgesel settir. Değişiklikler bu kararı
izlemelidir.

## 5. Otomatik doğrulama

```bash
python -m unittest tradehub_core.tests.test_faz0_closure
python -m pytest -m fixtures tradehub_core/tests/test_faz0_closure.py -q
```

İzin kanıtları:

- `test_tenant_isolation`: 22/22 OK
- `test_media_access`: 17/17 OK
- `test_policy_engine`: 38/38 OK; manifest karar paritesi dahil
- `test_media_security_gate`: 18/18 OK
- `test_faz0_closure`: unittest 11/11 ve pytest marker koşumu 11/11 OK

CI: `.github/workflows/faz0-discovery.yml`, azami 10 dakika.

## 6. Onay

Teknik ekip T-000…T-009 çıktılarını tamamlamıştır. Plane durumu ve resmî Faz 0
çıkışı için aşağıdaki **insan onayı** gerekir.

```text
Onaylayan (Platform yöneticisi): ______________________
Tarih: ______________________
İmza / Plane onayı: ______________________
```
