# ADR-0001 — İçerik-adresli dosya adlandırma (`sha256(içerik)[:32]` + shard)

**Durum:** Kabul edildi · yürürlükte
**Tarih:** karar TUR-141/TUR-130 ile alındı (tarih kayıtta yok, `tradehub_core/media/naming.py` başlığı) · **bedeli 2026-08-19'da ölçüldü**
**İlgili:** ADR-0009 (türevler `File` kaydı açmaz), ADR-0015 (S3 adaptörleri de aynı adreslemeyi kullanır)

---

## Bağlam

Yüklenen dosyalar Frappe'nin varsayılan adlandırmasıyla diske orijinal adlarıyla
yazılıyordu. İki sorun vardı:

1. **Numaralandırma.** `/files/<orijinal-ad>` adresi tahmin edilebilir; dosya adı
   üzerinden envanter taranabilir.
2. **Tek dizin.** Bütün yüklemeler tek `files/` dizinine düşüyor; milyonlarca
   dosyada dizin listelemesi ve dosya sistemi performansı bozuluyor.

Ayrıca aynı içeriğin defalarca yüklenmesi ölçüldü: **4.341 dosyada 109 tekrar
grubu, 110 fazladan kopya, 45,2 MB (%3,9)** (`docs/reports/11-faz1-arge.md`
§T-018).

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| **A** — Frappe varsayılanı (orijinal ad + çakışma soneki) | Değişiklik yok. Numaralandırma açık, dedup yok, tek dizin. |
| **B (SEÇİLEN)** — `sha256(içerik)[:32] + uzantı`, ilk 2 hex karakteri shard dizini | Ad içerikten türer: tahmin edilemez, aynı içerik tek adrese düşer, ~256 dengeli alt dizin. |
| C — Rastgele UUID + shard | Numaralandırmayı ve tek dizini çözer, **dedup'u çözmez**. İçerik eşitliğini görmek için ayrı bir hash kolonu ve sorgu gerekir. |

## Karar

Yeni yüklemelerde disk adı ve `file_url` içerikten türetilir:

```
ad    = sha256(içerik).hexdigest()[:32] + uzantı   ← media/naming.py:55
shard = adın ilk 2 hex karakteri (00–ff)           ← media/naming.py:66
url   = /files/<shard>/<ad>  (private: /private/files/…)
                                                    ← media/naming.py:102 (doc yolu)
                                                       media/naming.py:124 (legacy yol)
```

`hooks.py:961` → `write_file = "tradehub_core.media.naming.write_file_hashed"`.
`File.file_name` (kullanıcıya görünen ad) **değiştirilmez**; yalnız disk adı ve
`file_url` hash'lidir. Mevcut `file_url`'ler korunur — kural yalnız yeni
yüklemelere uygulanır.

## Gerekçe

- **Numaralandırma kapanır.** Adres içerikten türediği için dizin taraması
  anlamsızlaşır.
- **Dedup bedava gelir.** Aynı bayt → aynı yol; ikinci yazma diski büyütmez.
  `media/pipeline/storage/` adaptörleri bunu sözleşme düzeyine taşıdı
  (`created=False`, gerçek MinIO'ya karşı doğrulandı — `docs/reports/23-t051-s3-adaptor.md` §0).
- **Shard doğal uyumlu.** Yedek blob'ları (`media-backups/blobs/<xx>`) zaten aynı
  deseni kullanıyordu.
- Hook iki farklı çağrı yolundan tetikleniyor (`File.save_file()` ve legacy
  `file_manager.save_file()`); ikisi de desteklendi. İlk turda yalnız legacy yol
  yazılmıştı ve **her içerikli yükleme kırılıyordu** — `naming.py` başlığı bunu
  Critical bulgu olarak kaydediyor.

## Sonuçlar

### Olumlu

- Tahmin edilebilir adresler ortadan kalktı.
- Türev merdiveni de aynı adreslemeyi kullanıyor → CDN'de `immutable` + 1 yıl
  önbellek verilebildi (`docs/reports/27-t052-cdn-teslim.md` §1, ölçüldü).
- Depolama adaptörlerinde tekilleştirme sözleşme olarak ifade edilebildi.

### Olumsuz — ve bu ADR'nin asıl konusu

**Aynı içeriği iki farklı satıcı, iki farklı doctype'a yüklerse aynı `file_url`'ü
paylaşan N adet `File` satırı doğar** — çünkü ad yalnız içerikten türer,
sahipten ya da bağlamdan değil.

Bu, Frappe çekirdeğinin `find_file_by_url` mantığıyla birleştiğinde çok kiracılı
bir sızıntı üretir: çekirdek (`frappe/core/doctype/file/utils.py:453`) *"bu URL'e
ait satırlardan **herhangi biri** okunabiliyorsa dosyayı ver"* der. Bu bilinçli
bir çekirdek tasarımıdır ve bizim adlandırma kararımız onu **tetikleyen** taraftır.

**Ölçüm (2026-08-19):**

| Ölçüt | Değer | Kaynak |
|---|---:|---|
| Aynı URL'i paylaşan **özel** dosya | **33** | `DALGA-A-DEVIR.md` Ö-2 |
| Bunlardan **hassas** doctype'a bağlı (KYB/KYC/Order/Payment Transaction) | **29** | aynı |
| Hem özel hem açık satırı olan URL | **0** — public sızıntı yolu bugün boş | aynı |
| İlgisiz bir satıcının okuyabildiği başkasına ait dekont | **3** | `docs/reports/19-d2-hash-ortusme.md` §6 Ö-2 |

`docs/reports/19-d2-hash-ortusme.md` §6 Ö-2 ayrıca şunu kaydediyor: *"Bu benim
değişikliğimin sonucu değil — hiç dokunulmamış private KYB dosyalarıyla tekrar
ölçüldü, aynı desen orada da var."*

`docs/reports/21-t030-mimari-inceleme.md` M-18 bunu **bloklayıcı** olarak
işaretledi: SAD §10.1 adresleme kuralını "değişmez" ilan ediyor ama bu bedeli
ne §10.1'de kabul edilmiş bedel olarak, ne §8 risk listesinde, ne de §2.2
sapma listesinde yazıyor.

### Kabul edilen bedel ve açık iş

Karar **geri alınmıyor** — dedup, numaralandırma koruması ve `immutable`
önbellek onun üzerine kurulu. Bunun yerine:

- Sızıntının düzeltmesi (`find_file_by_url` yolunun kiracıya göre daraltılması)
  ayrı bir görevdir; bu ADR yalnız bedeli kayda geçiriyor.
- **Doğrulanmadı:** ölçümlerin tamamı yerel dev verisidir. Üretimde KYB
  alanlarında gerçek imza sirküleri/kimlik taraması bulunuyor ve aynı mekanizma
  orada gerçek PII sızdırır (`docs/reports/19-d2-hash-ortusme.md` §6 Ö-6, "EN
  YÜKSEK"). Aynı sorgular üretimde koşulmadı.

## Geri dönüş yolu

Hash URL şeması geri alınmaz; çok kiracılı okuma izolasyonu veya çakışma testi
yeniden kırılırsa public/private kapsam anahtara katılır ve eski nesneler salt
okunur geçiş katmanında tutulur. Geri dönüş tetiği: doğrulanmış bir çapraz
kiracı okuması ya da 128-bit kesilmiş hash'te tek gerçek çakışma.
