# ADR-0015 — S3/mirror/tiered adaptörleri yazılır ama varsayılan kapalıdır; düşüş sessiz değil raporlanır

**Durum:** Kabul edildi · yürürlükte (üretimde S3 **kapalı**)
**Tarih:** karar `docs/sad/SAD-v1.0.md` (S-05) · ölçüm 2026-08-19 (T-051)
**İlgili:** ADR-0001, ADR-0014

---

## Bağlam

SAD'ın S-05 kararı *"Nesne deposu yok, yerel disk korunur … Bugün taşıyacak bir
gerekçe ölçülmedi"* diyordu. Sonradan Faz 5'te dört depolama kipi yazıldı:
`local`, `s3`, `mirror`, `tiered`. Yani kararın **kapsamı** eskidi ama
**sonucu** hâlâ savunuluyor muydu?

Ayrıca çok kiracılı bir sistemde depolama kipini yanlışlıkla değiştirmek, dosya
teslimini tümden kırabilir.

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — Adaptörleri yazma, yerel diskte kal | S-05'e harfiyen sadık. Bedeli: S3'e geçiş günü sıfırdan yazılır ve ölçülmemiş olur. |
| **B (SEÇİLEN)** — Adaptörleri yaz, **varsayılan kapalı** tut; `s3_enabled=0` iken `S3Storage` **kurulamasın**, fabrika yerele düşsün ve **düşüşü raporlasın** | Geçiş yolu hazır ve ölçülmüş; üretim davranışı değişmiyor. Bedeli: kullanılmayan kod bakılır. |
| C — Adaptörleri yaz ve aç | Erken. Ölçülmemiş bir teslim yolunu üretime almak. |

## Karar

- `media/pipeline/storage/s3.py:11-18` iki katı kural koyuyor: `s3_enabled=0` iken
  `S3Storage` **kurulamaz**, fabrika yerel depoya düşer ve düşüşü
  `StoragePlan.downgraded_from` ile **raporlar** — **sessiz düşüş yok**.
  `import boto3` modül düzeyinde yok (ADR-0004 ile tutarlı).
- Ayar yüzeyi (`Media Storage Settings`, Single) kuruldu; `Media Superadmin` rolü
  yaratıldı; gizli anahtarlar `Password` fieldtype ile şifreli (`tabSingles`'ta
  yıldız, `__Auth`'ta Fernet); bağlantı testi **gerçek** yaz/oku/sil turu yapıyor
  (MinIO'ya karşı 450 ms ölçüldü); denetim kaydı ADL'ye yazılıyor ve **sır kayda
  girmiyor** (`docs/reports/25-t051-depolama-ayarlari.md` §1).
- **Ekran S3'ü bugün açtırmıyor:** local dışı bir kip, `docs/reports/23-t051-s3-adaptor.md`
  §7'deki açık kapılar ekranda listelenip **açıkça kabul edilmeden** kaydedilemiyor.

## Gerekçe

Dört kipin dördü de gerçek bir S3 uyumlu servise (MinIO) karşı ölçüldü.
Sahte istemcili paketten tek satır test metni kopyalanmadan, o dosyanın
`StorageContractMixin`'i **ithal edilerek** koşuldu: **91 test, hepsi geçti.**
İçerik-adresleme, dedup (`created=False`), kapsam ayrımı, `move` sırasında
anahtar korunması, `ObjectNotFound`, idempotent `delete`, tembel `iter_keys`,
TTL kelepçesi — hepsi gerçek serviste de tutuyor.

Ama üretime alınamaz: **2 yüksek öncelikli kusur** var ve ikisi de tek satırlık
değil.

| # | Bulgu | Etki |
|---|---|---|
| **B-01** | Presigned URL **SigV2** üretiliyor, SigV4 değil | AWS S3'ün 2014 sonrası bölgelerinde private dosya indirme **hiç çalışmaz** |
| **B-02** | `S3Storage.exists()` ağ hatasında istisna atıyor — sözleşme "hata atmaz" diyor | `tiered` kipinde `url_for()` soğuk katman düşünce render'ı kırar; 8,9 sn asılı kalır |
| **B-04** | `TieredStorage.delete()` sıcaktan siler, soğuk düşükken istisna atar | KVKK silme talebi "başarısız" görünürken sıcak kopya gitmiş olur |

## Sonuçlar

### Olumlu

- Geçiş yolu **ölçülmüş** olarak hazır; S3 günü geldiğinde bilinmeyen yok.
- Düşüşün raporlanması (`downgraded_from`) sessiz bir üretim sürprizini önlüyor.
- SigV2 hatası **ancak gerçek servise karşı** yakalandı: sahte S3 istemcisi
  presign taklidinde `X-Amz-Expires`'ı kendisi uyduruyordu ve **137 test bu hatayı
  kaçırdı** (`DALGA-A-DEVIR.md`). Bu, "adaptörü yaz ama gerçeğe karşı ölç"
  kararının doğrudan getirisidir.

### Olumsuz / açık

- Kullanılmayan dört kip bakım yükü ve yanlış güven kaynağı.
- SAD'ın §4.1 satırı (*"StorageAdapter · Bağımlılık: Yerel disk (S-05)"*) artık
  eksik: katmanlı depo, ayna, yaslandırma sırası (`tiered.py:19-27`: soğuğa yaz →
  sha256 doğrula → sıcaktan sil) ve `downgraded_from` raporlaması mimari
  davranışlardır ve **SAD'da yok**
  (`docs/reports/21-t030-mimari-inceleme.md` M-05).
- 3 kusur bilinçli olarak **düzeltilmedi** (rapor adaptörlere dokunmadı).
- **Doğrulanmadı:** gerçek AWS S3'e karşı hiç koşulmadı; ölçüm MinIO ile yapıldı.

## Geri dönüş yolu

S3/mirror/tiered yalnız sözleşme, hata enjeksiyonu ve geri yükleme provası
geçince açılır. Hata/latency veya hash doğrulama kapısı bozulursa
`s3_enabled=0` ve `mode=local` ile anında yerel birincile dönülür; mirror
kuyruğu durdurulur, yerel kopyalar doğrulanmadan silinmez.
