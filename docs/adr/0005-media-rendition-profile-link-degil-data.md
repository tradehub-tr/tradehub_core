# ADR-0005 — `Media Rendition.profile` alanı `Link` değil `Data`

**Durum:** Kabul edildi · yürürlükte · A/B deneyiyle kanıtlandı
**Tarih:** 2026-08-19 (Dalga A, K-2)
**İlgili:** ADR-0002

---

## Bağlam

Türev (rendition) satırları hangi profile ait olduklarını söylemek zorunda.
İki ad var ve **aynı değiller**:

| Ad | Örnek | Nerede |
|---|---|---|
| Politika profil adı | `w384`, `w128`, `og1200x630` | `media/pipeline/policy/slots/*.json` → `profiles[].name` |
| `Media Profile` docname | `product.image:w384` | `Media Profile.profile_key` (autoname) |

Docname **global tekil** olmak zorunda (`media_profile.json:5` →
`"autoname": "field:profile_key"`), ama politika profil adları **slotlar arası
çakışıyor**: `w64/w128/w256/w512/og1200x630` hem `brand.logo` hem `seller.logo`
politikasında var. Bu yüzden "docname = politika adı" kuralı uygulanamaz.

Köprü ilk yazıldığında `Media Rendition.profile`'a **docname** yazıyordu; manifest
ise **politika adını** bekliyordu. Sonuç: eşleşme yok → `NoProfileAvailable` →
**manifest sessizce boş dönüyordu.** Bu, Dalga A'nın iki bloklayıcısından biriydi
(`DALGA-A-DEVIR.md` K-2, yer: `media/pipeline_bridge.py`).

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — `Link` kalsın, docname yazılsın, manifest docname'i çözsün | Referans bütünlüğü DB'de. Bedeli: manifest her satır için `Media Profile`'ı okuyup `policy_profile`'a çevirmeli — kütüphaneye giden sözleşmeye bir join daha girer, ve slot öneki istemciye sızar. |
| B — `Link` kalsın, docname = politika adı olsun | En temiz görünen. **Uygulanamaz**: `w128` iki slotta birden var, global tekillik kırılır. |
| **C (SEÇİLEN)** — Alan `Data` olsun, **politika profil adını** taşısın; docname ayrı kolonda (`policy_profile` ham ad, `profile_key` slot önekli docname) | Manifest kolonu olduğu gibi kullanır. Bedeli: DB referans bütünlüğü yok; profil politikadan silinirse satır öksüz kalır. |

## Karar

`Media Rendition.profile` → **`Data`** (`media_rendition.json:43-44`), `reqd: 1`,
`search_index: 1`.

Köprü oraya politika profil adını yazar — gerekçe kodda, karar noktasının tam
üstünde duruyor (`media/pipeline_bridge.py:610-622`):

```python
# K-2: buraya POLİTİKA profil adı (`w384`) yazılır, `Media Profile`
# docname'i (`product.image:w384`) DEĞİL. …
# Alan şemada `Data`: taşıdığı değer bir docname değil, sözleşme
# adıdır ve slotlar arası tekil DEĞİLDİR (`w128` iki slotta birden
# var), yani `Link` olarak ifade edilemez.
"profile": profil.policy_profile,
```

İki ad `Media Profile` üzerinde ayrı kolonlarda tutulur
(`patches/v15_9_23_media_profile_seed.py:21-28`):

```
docname / profile_key = "{slot_key}:{policy_profile}"   ör. product.image:w384
policy_profile        = "w384"                          politikadaki ham ad
```

## Gerekçe

- `api/media_manifest.py` bu kolonu olduğu gibi kütüphaneye `available_profiles`
  olarak veriyor ve kütüphane onu **slot politikasındaki adla** karşılaştırıyor.
  Taşınan değer bir docname değil, bir **sözleşme adıdır**.
- `Link` bir DB kısıtıdır; ifade etmek istediğimiz şey (slot içinde tekil, global
  tekil değil) o kısıtla ifade edilemiyor. Yanlış tipi zorlamak yerine tip
  düşürülüp fark **kolon açıklamasında** yazıldı
  (`media_profile.json:36`).

## Sonuçlar

### Olumlu

- Manifest boş dönme hatası kapandı; A/B deneyiyle kanıtlandı
  (`DALGA-A-DEVIR.md` K-2 ✅, `docs/reports/15-dalga-a-dogrulama.md` §6.4 kök neden).
- Kütüphane ile sunucu arasındaki sözleşme tek bir dizeye indi; istemci slot
  önekini hiç görmüyor.
- `Media Profile` yine de var ve politikanın DB projeksiyonunu tutuyor; seed
  patch'i idempotent (3 koşuyla kanıtlandı, 34 profil).

### Olumsuz

- **Referans bütünlüğü DB'de yok.** Politikadan bir profil kaldırılırsa
  `Media Rendition` satırları öksüz bir ada işaret eder; bunu yakalayacak bir
  kısıt yok, yalnız manifest tarafında eşleşmeme olarak görünür.
- İki ad arasındaki dönüşüm **üç yerde** yazılı (doctype açıklaması, seed patch
  başlığı, köprü yorumu). Üçü bugün tutarlı; ayrışırlarsa hata yine sessiz olur.
- `Media Rendition` ve `Media Processing Job` sahiplik kolonu **taşımıyor**;
  izolasyon `Media Asset` üzerinden alt sorguyla zincirleniyor. Bu bilinçli
  (devirde eskiyen kopya alan yaratılmadı) ama her sorguya bir join ekliyor
  (`docs/reports/15-dalga-a-dogrulama.md` §5).

## Geri dönüş yolu

Profiller global, kalıcı ve foreign-key bütünlüğü gerektiren kayıtlara dönüşürse
`Data` → `Link` migration'ı yeniden değerlendirilir. Önce mevcut anahtarlar
profil docname'lerine eşlenir; eşlenemeyen tek satır varsa migration durur ve
Data şeması korunur.
