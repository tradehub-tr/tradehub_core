# 16 — T-029: politika aktivasyonu ve SRS onay denemesi

**Tarih:** 2026-08-19 · **Branch:** `ahmet` · **Görev:** T-029 (Faz 2 kapanış / SRS)
**Ortam:** yerel stack ayakta (`istoc-dev-*`, 13 konteyner), uygulama Docker imajına
gömülü — değişen dosyalar `docker cp` ile taşındı ve sha256 ile doğrulandı.

---

## 0. Tek cümlelik sonuç

**Hiçbir politika `active` yapılmadı (0/9) ve SRS `v1.0 ONAYLI` yapılmadı — ikisi de
kasıtlı.** 12 açık yönetici kararının 12'si gerçekten kapandı ve bu **G4 kapısını**
kapattı; ama aktivasyonun önündeki engeller **karar değil, sistem düzeyinde eksikti**
ve üçü de bu oturumda kod/dosya üzerinde doğrulandı.

---

## 1. Görevin varsayımı ve ölçümün söylediği

Görev şu varsayımla başladı: *"Bugün bunun önündeki engel kalktı: 12 açık kararın
12'si kapandı."* Ölçüm bu varsayımı **kısmen çürüttü**.

SRS (`docs/srs/SRS-v1.0.md` §6.7) `TASLAK → v1.0 ONAYLI` geçişini **yedi kapıya**
bağlıyor. Kararların kapanması bu kapılardan **yalnız birini** (G4) ilgilendiriyordu:

| Kapı | Ne istiyor | 2026-08-19 durumu | Karar kapanışıyla ilgisi |
|---|---|---|---|
| **G1** | Doğrulama betiği çıkış kodu **0** + kanonik set kararı | 🟡 **KISMEN** — betik çıkış kodu **1**, 6 hata; kanonik set kararı yok | Yok |
| **G2** | Şema video/belge biçimini ifade ediyor | ✅ **GEÇTİ** (rev2'de kapanmıştı) | Yok |
| **G3** | Açık soruların hepsi kapatılmış ya da CR'a bağlanmış | ❌ **AÇIK — 49 madde** | Kısmi (13 madde karara bağlıydı, kapandı) |
| **G4** | **14 yönetici kararı onaylanmış** | ✅ **GEÇTİ — 14/14** | **Tam — bu turda kapandı** |
| **G5** | `content_rules.json` kalibre edilmiş | ❌ **AÇIK** — `UNCALIBRATED`, değişmedi | Yok (etiketli korpus işi) |
| **G6** | En az bir politika `status: "active"` | ❌ **AÇIK — 0/9** | **Yok — asıl bulgu, aşağıda** |
| **G7** | `accept.max_megapixels_hard` işlevsel | ❌ **AÇIK** — 2 politikada alan yok, 80 MP 0 dosya kesiyor | Yok |

**Sonuç: 2 kapı geçti (G2, G4), 1 kısmen (G1), 4 açık (G3, G5, G6, G7).**
§9.3'ün sürüm kuralı "G1–G7'nin **tamamı**" diyor → SRS **v1.0 ONAYLI olamaz**.

---

## 2. Aktivasyon: hangi politika, neden yapılmadı

Elemeyi iki aşamada yaptım. Önce **şemanın kendi kuralı**
(`slot-policy.schema.json`, `status` alanının açıklaması):

> "Bir politika, içindeki her `null` `encoder_quality` ve her 'kalibre edilmedi'
> kaynaklı eşik giderilmeden `active` olamaz."

Sonra **SRS'in kuralları** (§6.2, FR-005, FR-144, FR-149).

### 2.1 Birinci elek — şemanın kuralı

| Politika | `encoder_quality` null | `open_questions` | Karara bağlı mı? | Birinci eleği geçti mi |
|---|---:|---:|---|---|
| `seller-logo` | **0** | 5 → **3** | 4'ü (K3–K6) + SVG geçişi **kapandı** | ✅ **GEÇTİ** |
| `brand-logo` | **0** | 5 → **1** | 4'ü (K3–K6) kapandı; **1'i kapanmadı** | ❌ |
| `company-cover-video` | **0** | 8 | 1'i (K7) karara bağlıydı; **7'si ölçüm** | ❌ |
| `document-attachment` | **0** | 6 | **Hiçbiri** — 6'sı da üretim ölçümü | ❌ |
| `user-avatar` | **0** | 6 | **Hiçbiri**; ayrıca `encoder_quality.webp = 82` **kalibre EDİLMEDİ** ve `master.colorspace='srgb'` bir **değişiklik önerisi** ("üretim görselleriyle karşılaştırılmadan `active` edilmemeli" — dosyanın kendi metni) | ❌ |
| `product-video` | **1** (`poster_1024.avif`) | 6 | Hayır | ❌ |
| `category-banner` | **3** | 6 | Hayır — dosya kendi yazıyor: "şema kuralı gereği status 'active' olamaz" | ❌ |
| `company-cover-image` | **5** | 6 | Hayır — aynı öz-beyan | ❌ |
| `product-image` | **5** | 7 | Hayır — aynı öz-beyan | ❌ |

**Birinci eleği yalnız `seller.logo` geçti.**

### 2.2 `brand.logo` neden geçemedi — doğrulanmış tek engel

Politikanın kendi `open_questions` maddesi:

> "`Brand.logo` `LIVE_SOURCES`'ta KAYITLI DEĞİL (`media/usage.py:32-41`). Bu politika
> uygulanmadan önce o kayıt eklenmeli, yoksa marka logoları 'kullanılmıyor' görünüp
> silme adayı olur."

**2026-08-19'da okundu ve hâlâ geçerli.** `tradehub_core/media/usage.py:32-41`
`LIVE_SOURCES` **8 satır** taşıyor:

```
tabListing.primary_image · tabListing.video_url · tabListing Image.image
tabListing Variant Item.variant_image · tabListing Variant Item.variant_gallery
tabStorefront Layout.sections · tabSeller Gallery Image.image
tabAdmin Seller Profile.logo
```

`tabBrand` **yok**. Kaydın eklenmesi `media/usage.py` değişikliğidir —
T-029'un kapsamı dışında ve **dokunulmayacak dosyalar** listesinde.
`brand-logo.json` `draft` bırakıldı, engel `open_questions`'ta yeniden yazıldı.

### 2.3 `seller.logo` neden `active` YAPILMADI — üç engel, üçü de doğrulandı

Politika şemanın kuralını sağlıyordu. Aktivasyonu **SRS'in kendi kuralları**
engelledi:

**(1) SRS §6.2 — açık yasak.**
> "Aşağıdakiler tamamlanmadan hiçbir slot politikası `active` yapılamaz."

Listenin **ilk maddesi** FR-001: `upload_policy.check()` `slot_key` parametresi
alıyor. **Doğrulandı — almıyor.** `tradehub_core/media/upload_policy.py:307-313`:

```python
def check(
	file_name: str,
	*,
	content: bytes | None = None,
	size: int = 0,
	media_endpoint: bool = False,
) -> Karar:
```

Slot kimliği sunucuya hiç ulaşmıyor. `active` bir politikanın zorlanacak kod yolu
**yok** — işaret bir **beyandan** ibaret kalırdı. (Bayraklar da 0: aşağıda §5.)

**(2) FR-144 — bu dosyayı adıyla sayıyor.**
> "Sistem, **her** görsel slotunda `accept.max_megapixels_hard` alanının **var
> olmasını** zorunlu kılmalıdır; alanı olmayan politika `active`
> **yapılamamalıdır**."

**Doğrulandı — alan yok.** Ölçüm:

| politika | `accept.max_megapixels_hard` | `master.max_megapixels` |
|---|---|---|
| `category-banner` · `company-cover-image` · `document-attachment` · `product-image` · `user-avatar` | 80 | var |
| `company-cover-video` · `product-video` | 8,3 | var |
| **`seller-logo` · `brand-logo`** | **YOK** | **YOK** |

Eşik uydurulamaz: FR-143 değerin **bellek bütçesinden** türetilmesini ve
`sources` bloğunda yazılı olmasını istiyor (önerilen 40 MP ≈ 160 MB/çözüm).

> **FR-144'ün gerekçesinde bir netleştirme — ölçüldü.** FR-144 "bu iki slotta
> 500 MP'lik bir logo tek bir sayıya bile takılmaz" diyor. `seller.logo` için
> **tam doğru değil**: `require.max_edge = 4096` bugün bile uzun kenarı 4096'yı
> aşan her dosyayı reddediyor (`policy/engine.py:879`, `block=require`,
> `on_violation.require="reject"`) ve `4096² = 16,7 MP` fiilen bir tavan koyuyor.
> Yani slot piksel bombasına karşı **savunmasız değil**. FR-144'ün *alanın
> varlığı* şartı yine de geçerli; düzeltilmesi gereken gerekçe cümlesindeki
> abartıdır — **gereksinim metni değiştirilmedi** (§9.3'e göre CR ister).

**(3) FR-149 — `compliance_measured` yok.**
> "Sistem, bir slot politikasını `active` yapmadan **önce**, o politikanın gerçek
> veriye uygulanmış **uyum karnesini** politikanın içinde taşımalıdır."

**Doğrulandı — blok yok** ve şemada da tanımlı değil. Karne verisi zaten ölçülü:
`seller.logo` ihlal oranı **%31,6** (n=19, `09-slot-bazinda-istatistik.md` §3);
%10'un üstü olduğu için FR-149'un kuralıyla `enforcement_mode` **`new_uploads_only`**
olurdu.

**Üçü de bu politikanın dışındaki işlerdir** (`media/upload_policy.py` imzası,
şemaya yeni blok, FR-143 eşik türetmesi) ve hiçbiri kararların kapanmasıyla
kapanmaz. `seller-logo.json` `draft` bırakıldı; üç engel `open_questions`'a
madde madde, kaynaklarıyla yazıldı.

> **G6 ile §6.2 çelişiyor — kayda geçirildi, çözülmedi.** §6.2 "hiçbir politika
> `active` yapılamaz" diyor; G6 "en az biri `active` olmalı" diyor. İkisi aynı
> anda sağlanamaz. Bu revizyon **daha kısıtlayıcı olanı** (§6.2) uyguladı ve
> çelişkiyi SRS §6.7-C'ye yazdı.

---

## 3. TBD taraması — çıktılar

**Kanonik kalıplar (`TBD`/`TODO`/`FIXME`/`XXX`/`TBC`):**

```
$ grep -rniE "\b(TBD|TODO|FIXME|XXX|TBC)\b" tradehub_core/media/pipeline/policy/ | wc -l
       0
$ grep -rniE "\b(TBD|TODO|FIXME|XXX|TBC)\b" docs/standards/ | wc -l
       1
  → docs/standards/company-cover-video.md:280  "gösterir. Hiçbiri TBD değildir."
    OLUMSUZLAMA cümlesi, yer tutucu DEĞİL.
```

**Politika dosyalarında kalan TBD: 0.** Ama bu depoda "açık kalem" `TBD` ile değil
Türkçe işaretlerle yazılıyor; asıl tarama budur:

| politika | `status` | `open_questions` | `encoder_quality` null | `ÖLÇÜLMEDİ`/`ölçülmedi` | `kalibre edilmedi` | `karar bekliyor` |
|---|---|---:|---:|---:|---:|---:|
| `seller-logo` | draft | 3 | **0** | 1 | 0 | 0 |
| `brand-logo` | draft | 1 | **0** | 1 | 0 | 0 |
| `company-cover-video` | draft | 8 | **0** | 14 | 1 | 0 |
| `document-attachment` | draft | 6 | **0** | 2 | 0 | 0 |
| `user-avatar` | draft | 6 | **0** | 2 | 0 | 0 |
| `category-banner` | draft | 6 | **3** | 1 | 0 | 0 |
| `company-cover-image` | draft | 6 | **5** | 2 | 0 | 0 |
| `product-image` | draft | 7 | **5** | 13 | 2 | 1 |
| `product-video` | draft | 6 | **1** | 4 | 0 | 1 |
| **TOPLAM** | **0 active / 9 draft** | **49** | **14** | **40** | **3** | **2** |

`open_questions` rev2'de 55 idi → **49**. Düşüşün tamamı **karara bağlı** 13
maddeden (logo K3–K6 × 2 dosya + SVG geçişi + kapak videosu K7) ve
`pending_admin_decisions` 7 → 0'dan geliyor; yerine `seller-logo`'ya **3
doğrulanmış aktivasyon engeli** eklendi. **Ölçüm bekleyen tek bir madde
kapatılmadı.**

`seller-logo`'da kalan tek `ÖLÇÜLMEDİ`, `production_verification_required` D3:
`render_points[].content_box_px` değerleri Tailwind sınıfından **türetildi**,
tarayıcıda ölçülmedi. Bu bir **eşik** değil, profil genişliklerinin türetildiği
kutu ölçüsü; yanlışsa sonucu aşırı/eksik servis olur, **hatalı ret olmaz**.

---

## 4. Kararlara bağlı alanların doğrulanması

Görev özellikle şunu sordu: *"`seller-logo.json` ve `brand-logo.json` bugün `w384`
rung'u aldı (K3 ölçümle B'ye çevrildi) — bu iki dosya güncel mi?"*

**Profiller güncel, prose GÜNCEL DEĞİLDİ.** Ölçüm:

| Ne | Durum (denetimden önce) |
|---|---|
| `profiles[]` dizisi | ✅ `w384` **var** (max_bytes 23.040 = 40.960 × 384²/512²), iki dosyada da. 5 rung: 64/128/256/384/512 (+ og1200×630) |
| `profiles[w384].derived_from` | ✅ K3 ölçümünü taşıyor |
| `open_questions[0]` | ❌ **"K3 — Merdiven 4 rung mu, 5 rung mu? ÖNERİ: 4 rung"** — kapanmış kararı açık gösteriyordu |
| `notes[2]` | ❌ **"KARAR K3 — AÇIK KALDI … Varsayılan yürürlükte: 4 rung"** — `profiles[]` ile **doğrudan çelişiyordu** |
| `sources["profiles[].width"]` | ❌ "42 talep, **4 rung** ile karşılanıyor" |
| `profiles[w512].max_overshoot_note` | ❌ "384 rung'u bunu 1,37×'e **indirir**" (gelecek kipi — eklendiği hâlde) |
| `sources["profiles_ladder_identical_to_seller"]` (brand) | ❌ "AYNI merdiven **(64/128/256/512)**" |
| `pending_admin_decisions` (kapak videosu) | ❌ 7 madde, hepsi kapanmış kararlar; **K8 hiç listelenmemişti** |

Yani **sayılar doğruydu, metin yalan söylüyordu.** Bu tutarsızlıkların hepsi
düzeltildi (§6).

**14 kararın kapanış tablosu** (kaynak: `logo.md` §13 + "VARSAYILANDA ONAYLANAN
KARARLAR"; `company-cover-video.md` §10.9 + "VARSAYILANDA ONAYLANAN KARARLAR"):

| Belge | # | Sonuç | Politikada karşılığı |
|---|---|---|---|
| `logo.md` | K1 | **B** — JPEG kabul + uyarı | Zaten işlenmişti (08-18) |
| `logo.md` | K2 | **A** — band 1:2…2:1 kaldı | Değişen sayı yok |
| `logo.md` | K3 | **B** — 5 rung (+384) | `profiles[]` ✅ · prose **bu turda düzeltildi** |
| `logo.md` | K4 | **A** — yalnız kayıpsız WebP | Değişen sayı yok (`formats: ["webp"]` zaten) |
| `logo.md` | K5 | **A** — 512×512 | `require.recommended_edge` zaten 512. Panel metni **admin-panel deposunda, ayrı görev**. Markada karşılığı **hâlâ açık** (Brand.logo için hiç tavsiye metni yok) |
| `logo.md` | K6 | **A** — yalnız yeni yüklemeler | Değişen sayı yok; değişen kuralın **kapsamı** |
| `cover-video.md` | K1 | Eklenmesin (1080p) | Değişen yok; **sayısal tetik açık kalıyor** (§11-D3 > %15) |
| `cover-video.md` | K2 | **AÇILDI** — yalnız doğrulanmış satıcılara | `video.modes.ambient.requires_admin_approval` **güncellendi**. `default:false` ve `implemented_today:false` **DEĞİŞMEDİ** — kip artık slot düzeyinde değil satıcı düzeyinde açılıyor; kapının `VerificationBadge`'e bağlanması **ayrı görev** |
| `cover-video.md` | K3 | Opsiyonel kalsın | Değişen yok |
| `cover-video.md` | K4 | Yalnız yeni yüklemeler | Değişen yok |
| `cover-video.md` | K5 | Satıcı beyanı | Değişen yok |
| `cover-video.md` | K6 | 4 kategori sabit | Değişen yok |
| `cover-video.md` | K7 | **SAYILSIN** ⚠️ **öneriden ayrıldı** | `open_questions` maddesi karara bağlandı; **borç doğdu**, aşağıda |
| `cover-video.md` | K8 | Mevcuda dokunulmaz | Değişen yok; blokta hiç listelenmemişti, `notes`'a eklendi |

### ⚠️ K7 bir gereksinim borcu doğurdu

Karar: rendition'lar `File` kaydı açıp satıcı medya kotasından **sayılacak**
(politikanın önerisi bunun **tersiydi**). `entitlement.checks.check_media_storage_quota`
bugün her `File` kaydını sayıyor ve kapak videosu slotu kapak başına **6 nesne**
üretiyor (tipik ~19 MB, en kötü ~37,5 MB — `company-cover-video.md` §6.5). Kota
değerleri değişmezse satıcılar kotalarını yaklaşık **6 kat hızlı** doldurur.

**Bu revizyonda yapılmadı.** Kota değerlerinin yeniden boyutlandırılması ya da
rendition'lar için ayrı bir kota kalemi tanımlanması ayrı bir iştir;
`docs/standards/kota.md` bu karara göre güncellenmeli. Madde
`company-cover-video.json` `open_questions` içinde **açık** bırakıldı.

---

## 5. Koşumlar ve çıktıları

### 5.1 Şema doğrulaması — 9/9

```
brand-logo.json OK · category-banner.json OK · company-cover-image.json OK
company-cover-video.json OK · document-attachment.json OK · product-image.json OK
product-video.json OK · seller-logo.json OK · user-avatar.json OK
uyumsuz: 0     (jsonschema 4.25.1, Draft202012Validator)
```

### 5.2 `PolicyRegistry().load()` — 9/9 (hem yerelde hem konteynerde)

```
KONTEYNER — yuklenen politika sayisi: 9
  brand.logo             status=draft    profiles=6 open_questions=1
  category.banner        status=draft    profiles=3 open_questions=6
  company.cover_image    status=draft    profiles=5 open_questions=6
  company.cover_video    status=draft    profiles=3 open_questions=8
  document.attachment    status=draft    profiles=1 open_questions=6
  product.image          status=draft    profiles=7 open_questions=7
  product.video          status=draft    profiles=2 open_questions=6
  seller.logo            status=draft    profiles=6 open_questions=3
  user.avatar            status=draft    profiles=3 open_questions=6
PolicyEngine kuruldu: OK
```

### 5.3 `docs/standards/README.md` §6 değişmez betiği

`KeyError` yerine hata sayan varyantla (betiğin kendisi hâlâ `master["max_megapixels"]`
ile çöküyor — T10 / FR-148):

```
[D3] brand.logo : content_rules 'animated' → tanımsız message_key 'animated'
[D4] brand.logo : master.max_megapixels YOK
[D5] brand-logo : politika var, docs/standards/brand-logo.md YOK
[D3] seller.logo: content_rules 'animated' → tanımsız message_key 'animated'
[D4] seller.logo: master.max_megapixels YOK
[D5] seller-logo: politika var, docs/standards/seller-logo.md YOK

şemaya uyumlu politika: 9/9 | toplam hata: 6
open_questions TOPLAM = 49 | pending_admin_decisions = 0 | encoder_quality null = 14
ACTIVE: YOK (0/9)
ÇIKIŞ KODU = 1
```

**rev2 ile birebir aynı.** Bu 6 hatanın **4'ü betik kusuru**:

- **D5 ×2** — bilinen yanlış pozitif: iki logo slotunun ortak belgesi `logo.md`.
- **D3 ×2 — YENİ TESPİT.** Betik `content_rules[].message_key` dizgesinin
  `messages.tr` içinde **birebir** bulunmasını arıyor. Motor bunu böyle çözmüyor:
  `policy/engine.py:80-110` `MESSAGE_KEYS` haritası
  `"animated": ("animated", "format_animated")` diyor ve `_message()` (`:493-509`)
  bu sırayla deniyor — `format_animated` iki politikanın da `messages.tr`'sinde
  **tanımlı**. Yani bu hata **çalışma zamanında etki üretmiyor**; D5 gibi bir
  betik kusurudur. **Düzeltilmedi** — `message_key` karara bağlı bir alan değil ve
  düzeltmesi FR-148'in işi.

Gerçek olan **2 hata**: `master.max_megapixels` iki logo politikasında yok
(G7 / FR-144 ile aynı kök).

### 5.4 Testler

| Nerede | Modüller | Sonuç |
|---|---|---|
| Yerel (`python3 -m unittest`) | `test_policy_dpi`, `test_policy_engine`, `test_contracts`, `test_video_decision`, `test_delivery_sizes` | **Ran 206 · OK** (skipped=7, expected failures=1) |
| Konteyner (`env/bin/python -m unittest`) | aynı 5 modül | **Ran 206 · OK** (expected failures=1) |

Tek `expectedFailure` bilinçlidir:
`test_policy_dpi::test_satici_upload_yolu_urun_slotu_tabanini_karsilar`
(`engine.to_webp` uzun kenarı 1920'ye sabitliyor — önceden var olan bulgu).

### 5.5 `Media Profile` tohumlayıcısı — beklenmedik artış YOK

```
$ bench --site istoc.localhost execute tradehub_core.patches.v15_9_23_media_profile_seed.execute
{"created": 0, "updated": 0, "unchanged": 36, "skipped": 0}

$ bench --site istoc.localhost execute frappe.db.count --args '["Media Profile"]'
36        (önce 36 → sonra 36)
```

**Beklenen sonuçtu ve öngörüldü:** tohumlayıcı yalnız `profiles[]` dizisini okuyor
(`_profile_fields`: `name`, `width`, `formats`, `fit`, `target_ratio`,
`encoder_quality`). Bu turda **hiçbir `profiles[]` dizisine dokunulmadı** — değişen
alanlar `status`, `notes`, `open_questions`, `sources`, `pending_admin_decisions`
ve bir `max_overshoot_note`. Hiçbiri tohumlayıcının okuduğu alan değil.

36 = 6+6+3+5+3+1+7+2+3 (slot başına profil sayısı). Tohumlayıcı iki kez koşuldu
(aktivasyon denemesinden önce ve `draft`'a döndükten sonra); **ikisinde de aynı
çıktı**.

### 5.6 Bayraklar — 0 kaldı

```
$ bench --site istoc.localhost execute frappe.client.get_value \
    --kwargs '{"doctype":"Media Engine Settings","fieldname":[...]}'
{"active_slots": "", "manifest_api_enabled": "0",
 "media_pipeline_enabled": "0", "rendition_on_upload": "0"}
```

Görev başında ve sonunda aynı. Hiçbir bayrağa dokunulmadı.

### 5.7 `docker cp` doğrulaması

9 politika dosyasının sha256'sı yerel ile konteyner arasında **birebir eşit**
(koşum çıktısı oturum kaydında). 3 değiştirilen dosya kopyalandı, 6'sı zaten
eşitti.

---

## 6. Değiştirilen dosyalar

**Dokunulmayanlar (kural gereği):** `docs/standards/logo.md`,
`docs/standards/company-cover-video.md`, `media/presets.py`, `api/**`,
`media/**/*.py`, DocType JSON'ları. Hiçbirine yazılmadı.

### `tradehub_core/media/pipeline/policy/slots/seller-logo.json`
- `status`: **`draft` kaldı** (aktivasyon denendi, §2.3'teki üç engel yüzünden geri alındı).
- `open_questions`: K3/K4/K5/K6 + SVG geçişi **kapatıldı**; yerine 3 **doğrulanmış
  aktivasyon engeli** (FR-001 `slot_key`, FR-144 `max_megapixels_hard`,
  FR-149 `compliance_measured`) kaynaklarıyla yazıldı. 5 → 3.
- `notes`: `KARAR K3 — AÇIK KALDI` girdisi **K3 KAPANDI (B — 5 rung)** ile
  değiştirildi; K4/K5/K6 kapanış kayıtları, SVG geçişinin `notes`'a taşınma
  gerekçesi ve `STATUS = DRAFT KALDI` gerekçe notu eklendi. 9 → 14.
- `sources`: `profiles[].width` (4 → 5 rung), `png_fallback_not_generated`
  (K4 kapandı) güncellendi; `profiles[w384]` ve `status=draft` kaynakları eklendi.
- `profiles[w512].max_overshoot_note`: gelecek kipi → kapanmış karar.

### `tradehub_core/media/pipeline/policy/slots/brand-logo.json`
- `status`: **`draft`** — §2.2'deki `LIVE_SOURCES` engeli yüzünden.
- `open_questions`: K3–K6 kapatıldı; **`LIVE_SOURCES` maddesi kaldı** ve
  2026-08-19 doğrulamasıyla yeniden yazıldı. 5 → 1.
- `notes`: K3 kapanışı + K4/K5/K6 kayıtları + `STATUS = DRAFT KALDI` gerekçesi. 9 → 13.
  K5'in **markada uygulanamaz** olduğu ayrıca yazıldı (Brand.logo için panelde
  hiç ölçü tavsiyesi metni yok).
- `sources`: `profiles_ladder_identical_to_seller` (5 rung), `profiles[w384]`,
  `status=draft`.

### `tradehub_core/media/pipeline/policy/slots/company-cover-video.json`
- `status`: **`draft`** — 8 `open_questions` maddesinin 7'si ölçüm bekliyor.
- `pending_admin_decisions`: **7 → 0**. K1–K8'in sekizi de karara bağlandığı için
  blok boşaltıldı; sonuçlar `notes`'a taşındı (K8 dahil — blokta hiç yoktu).
- `video.modes.ambient.requires_admin_approval`: K2 onayı + doğrulanmış-satıcı
  kapısı + `default:false`'un neden değişmediği yazıldı.
- `open_questions`: K7 maddesi karara bağlandı ve **kota borcuna** çevrildi.
- `notes`: 8 kararın sonuç kaydı, K7'nin ölçülebilir bedeli, `STATUS = DRAFT KALDI`
  gerekçesi. 8 → 11.

### `docs/srs/SRS-v1.0.md`
**Sürüm: `v1.0 TASLAK`, revizyon 3** (`v1.0 ONAYLI` **yapılmadı**).
- Başlık durum bloğu: T3/T7/T8/T9 kapandı; T1/T2/T4/T5/T6/T10 açık; G2/G4 geçti.
- **Yeni** "Revizyon 3 — 2026-08-19: ne değişti" bölümü (7 satırlık değişiklik tablosu + kapsam beyanı).
- **Yeni** §0.3-C: üçüncü TBD taraması, politika başına işaret tablosu, betik
  çıktısı, T1–T10 durum tablosu, **14 kararın kapanış tablosu**, K7 ve K2'nin
  doğurduğu iş kalemleri.
- **Yeni** §6.7-C: kapıların üçüncü ölçümü + kalan iş tablosu + `seller.logo`'nun
  neden `active` yapılmadığının üç maddelik gerekçesi + G6/§6.2 çelişkisinin kaydı.
- §6.1: 12/13/14 numaralı kriterler güncellendi (14 ✅ kapandı, 12 ve 13 ❌);
  kapanış sayısı 12/19 → **13/19**.
- FR-035 (logo merdiveni 5 → **6 profil**) ve NFR-009 (logo depolama bütçesi
  4 rung → 5 rung: 256/188 → **301/210,5 KiB/logo**) güncellendi.
- §9.1: sürüm/tarih/kapı/karar/`status`/açık soru satırları; **rev3'te değişen
  gereksinimler** tablosu (FR-030 merdiven, K7 kota, K2 ambient).
- §9.2: platform yöneticisi satırına "14 kararın 14'ü **VERİLDİ**" işareti;
  belgenin geri kalanı **hâlâ onaysız**.
- §9.3: "Rev3 sürüm notu — neden hâlâ `v1.0 ONAYLI` DEĞİL" (G3/G5/G6/G7'nin her
  birinin ne istediği tek tek).

**Önceki revizyonların anlık görüntü tabloları (2026-08-17, 2026-08-18) silinmedi** —
belgenin kendi konvansiyonu bu.

---

## 7. Kapanmayanlar — sonraki görevler için

| # | İş | Neden bu turda yapılmadı | Kapattığı kapı |
|---|---|---|---|
| 1 | `upload_policy.check()`'e `slot_key` parametresi (FR-001, B1) | `media/*.py` **dokunulmayacaklar** listesinde | G6, §6.2 |
| 2 | `accept.max_megapixels_hard`'ı bellek bütçesinden türet + 2 logo politikasına ekle (FR-143, FR-144) | Eşik **karara bağlı değil**, türetme işi; uydurulamaz | G7, G6 |
| 3 | `compliance_measured` bloğunu şemaya ekle + 9 politikaya yaz (FR-149) | Şema değişikliği; kapsam dışı | G6 |
| 4 | `Brand.logo`'yu `media/usage.py` `LIVE_SOURCES`'a ekle | `media/*.py` dokunulmayacak | `brand.logo` aktivasyonu |
| 5 | Kota değerlerini K7'ye göre yeniden boyutlandır + `kota.md`'yi güncelle | Karar bir **borç** doğurdu, ayrı iş | — (yeni borç) |
| 6 | `ambient` kipini `VerificationBadge`'e bağla (K2) | Storefront + backend işi | — (yeni borç) |
| 7 | Doğrulama betiğini onar: `KeyError` + D3 `MESSAGE_KEYS` + D5 eşleme (FR-148) | `message_key` karara bağlı alan değil | G1 |
| 8 | Kanonik politika setini ilan et (T6) | Karar yazılı değil | G1 |
| 9 | `content_rules.json` kalibrasyonu (≥300 görsel etiketli korpus) | İnsan etiketlemesi | G5 |
| 10 | Kalan 49 `open_questions` maddesini kapat ya da CR'a bağla | Üretim ölçümü ister | G3 |
| 11 | Marka tarafında ölçü tavsiyesi metni (K5'in Brand karşılığı) | admin-panel deposu | — |
| 12 | Panel `400×400` → `512×512` metni (K5) | admin-panel deposu (`DocTypeFormView.vue:448`) | — |

---

## 8. Dürüstlük notu

Koşulmayan hiçbir şeye "geçti" denmedi. Bu raporda **geçti** yazan her satırın
altında ya bir komut çıktısı ya bir dosya:satır referansı var. Özellikle:

- **`seller.logo` aktivasyonu denendi ve GERİ ALINDI.** Dosya bir süre
  `status: "active"` taşıdı, tohumlayıcı o hâlde de koşuldu (aynı çıktı: 36
  unchanged), sonra §2.3'teki üç engel doğrulanınca `draft`'a döndürüldü. Bu
  sıra gizlenmedi.
- **SRS `v1.0 ONAYLI` YAPILMADI.** Görev bunu istiyordu; ölçüm izin vermedi.
  Belgenin kendi §9.3'ü "G1–G7'nin tamamı" diyor ve 4 kapı açık. ONAYLI
  işaretlemek, belgenin en çok değer verdiği şeyi — kendi kuralına uymayı —
  çiğnemek olurdu.
- **G6 ile §6.2 çelişiyor.** Bu çelişki çözülmedi, kayda geçirildi. Çözümü bir
  karar işidir: ya §6.2 "Faz 3 tamamlanmadan" şartı gevşetilir (CR ister), ya
  G6'nın metni "aktivasyona hazır" olarak yeniden yazılır.

---

## 9. KANIT VE KAPI DURUMU — 2026-08-19 eki (D-1 / T-029, T-020, T-023)

> **Bu bölüm §0'ın kararını değiştirmez, hiçbir onay alanı doldurmaz ve hiçbir
> politika/SRS dosyasına dokunmaz.** Yalnız 7 kapının bağımsız yeniden ölçümünü,
> §6.2'nin kutucuk sayımını ve iki **belge düzeyi kusuru** ekler.
> Tam dosya: **`docs/reports/54-d1-faz0-2-kapanis.md`** §5.

### 9.1 Yedi kapı — bağımsız yeniden ölçüm **[Ö]**

| Kapı | Bu raporun yazdığı | **2026-08-19 bağımsız ölçüm** | Karar |
|---|---|---|---|
| **G1** | 🟡 KISMEN | jsonschema (4.25.1) → **9/9, TOPLAM HATA = 0** ✅. Ama `policy/slots/` (**9 dosya**) ile `docs/standards/policies/` (**13 dosya**) yan yana; **kanonik set kararı yazılı değil** | 🟡 **doğrulandı** |
| **G2** | ✅ GEÇTİ | Tekrarlanmadı **[R]** | ✅ |
| **G3** | ❌ 49 | `open_questions` toplamı **49** (1 · 6 · 6 · 8 · 6 · 7 · 6 · 3 · 6); hiçbirinde CR-ID yok | ❌ **doğrulandı** |
| **G4** | ✅ 14/14 | Tekrarlanmadı **[R]**; rapor 33 §4.3 bağımsız doğruladı. ⚠ **kanıt belgenin kendi beyanıdır** — `logo.md` ve `company-cover-video.md`'de imzalı onay bloğu, ad/tarih alanı **yok** | ✅ **ama kanıt beyan** |
| **G5** | ❌ AÇIK | ⚠ **DİZE OLARAK GEÇER, ÖZÜNDE AÇIK** — §9.3 | ❌ **açık sayılmalı** |
| **G6** | ❌ 0/9 | **`active` = 0 / 9**, hepsi `draft` | ❌ **doğrulandı** |
| **G7** | ❌ AÇIK | `accept.max_megapixels_hard` **7 / 9** politikada (`brand-logo`, `seller-logo`'da yok); var olan 7'nin **5'inde eşik 80 MP** → canlıdaki **0 dosyayı** keser | ❌ **doğrulandı** |

Ek ölçüm: `encoder_quality` null **= 14** (category-banner 3 · company-cover-image 5 ·
product-image 5 · product-video 1) — bu raporun sayısı **doğrulandı**.

### 9.2 SRS §6.2 — 20 kutucuk, 20'si işaretsiz **[Ö]**

SRS'in tamamında **53 `- [ ]`, 0 işaretli**; §6.2'de **20 / 20 işaretsiz**.
Bu 20 maddenin **6'sı** programatik olarak ölçüldü:

| Madde | FR | Ölçüm | Sonuç |
|---|---|---|---|
| `check()` `slot_key` alıyor | FR-001 | `grep -c slot_key media/upload_policy.py` → **0**; imza `check(file_name, *, content, size, media_endpoint)` | ❌ |
| 9/9 tek şemaya uyuyor | FR-002/003 | jsonschema **0 hata** | ✅ **tek karşılanan** |
| `max_megapixels_hard` 9/9 | FR-144 | **7 / 9** | ❌ |
| `compliance_measured` karnesi | FR-149 | **0 / 9** dolu | ❌ |
| `th_media_duration_ms` | FR-133 | `grep -rn` → **0** | ❌ |
| `optimization` yanıt bloğu | FR-064 | `grep -rn '"optimization"' api/` → **0** | ❌ |
| **kalan 14 madde** | — | **ölçülmedi** | **doğrulanmadı** |

### 9.3 G5 uyarısı — kapı bugün **dize düzeyinde** geçer hâle geldi **[Ö]**

SRS §6.7 G5'in doğrulama kuralı harfiyen `calibration_status != "UNCALIBRATED"`.

```
content_rules.json  calibration_status = "TRIGGER_RATE_MEASURED_UNLABELED"
git diff:  - "UNCALIBRATED"   + "TRIGGER_RATE_MEASURED_UNLABELED"
```

Ama 9 kuralın **9'unun** `threshold_status`'ı hâlâ *"KALİBRE EDİLMEDİ"* (ya da
*"KALİBRE EDİLMEZ — ürün kararı"*) ile başlıyor; 2 kuralda ek not
*"ÇALIŞTIRILAMADI (ölçüm aracı yok)"*. **Yanlış pozitif oranı ölçülmedi,
etiketli korpus yok.**

> **Bu G5'in metnindeki bir kusurdur, bir başarı değil.** Kapı bir dize
> karşılaştırmasına dayandığı için kalibrasyon yapılmadan geçilebilir hâle
> geldi. `54-…md` G5'i **AÇIK** sayar. Öneri: G5'in kuralı T-025'in kendi
> kabul kriterine (*"FP < %5 **ölçülmüş**"*) bağlanmalıdır — bu bir SRS metin
> düzeltmesidir ve `docs/srs/` yalnız-oku olduğu için yapılmadı.
>
> ⚠ `38-t017-guvenlik-kapisi.md` §6.3: `extreme_blur` **RED üretebilen** bir
> kuraldır ve canlı ürün görsellerinin **%1,70'ini (22 dosya)** gizlerdi;
> kuralın kendi `rollout` sözleşmesi reject kuralları için FP < %1 istiyor.

### 9.4 FR-003'ün "CI'da koşar" kriteri bugünkü imajla sağlanamaz **[Ö]**

```
konteyner: env/bin/python -c "import jsonschema"  →  ModuleNotFoundError
host:      jsonschema 4.25.1  →  9/9, 0 hata
requirements.txt · pyproject.toml · setup.py:  "jsonschema" → 0 isabet
```

Şema doğrulaması çalışıyor, **ama yalnız geliştirici makinesinde**. G1'in ve
§6.2'nin 2. maddesinin *"doğrulanıyor"* iddiası bugün **taşınabilir değildir**.
Tek adım: `requirements.txt`'e `jsonschema` + imaj yeniden inşası — mekanik iş.

### 9.5 Onay bloğu — var, ama eksik **[Ö]**

| Belge | Blok | Ölçüm |
|---|---|---|
| `SRS-v1.0.md` §9.2 | ✅ **VAR** | 5 rol. SRS'te toplam **5 boş kutucuk, 1 işaretli kutucuk**; İşaretli olan yalnız *"T7'nin 14 kararı VERİLDİ"* içindir, aynı satır *"geri kalanı hâlâ onaysız"* (boş kutucuk) diyor. Diğer 4 rol tamamen işaretsiz. ❌ **Ad/tarih/imza için doldurulacak alan yok** |
| **bu rapor (`16-…md`)** | ❌ **YOK** | `grep -c` (kutucuk gliflerini ve "İmza" dizesini arayan) → **0** |
| `logo.md`, `company-cover-video.md` | ❌ **YOK** | G4'ün 14 kararını taşıyorlar; onay **cümle** olarak yazılı, blok olarak değil |

### 9.6 §7'nin bir gerekçesi çürüdü **[Ö]**

§7'nin 1. maddesi FR-001'i *"`media/*.py` **dokunulmayacaklar** listesinde"*
diye kapsam dışı bıraktı. **`tradehub_core/media/upload_policy.py` bugün
değişti** (`git status: M`; T-017 düzeltmesi, `38-t017-guvenlik-kapisi.md`).
Gerekçe artık geçerli değil — G6'nın üç engelinden birinin kilidi açıldı.
Kalan iki engel (FR-144 politika JSON'u, FR-149 şema değişikliği) duruyor.

> **§0'ın kararı geçerlidir: SRS `v1.0 ONAYLI` olamaz.** 7 kapının 2'si geçti
> (G2, G4), 1'i kısmen (G1), 4'ü açık (G3, G5, G6, G7). **G3 ve G5 onay
> yetkisiyle bile kapanmaz.** İmzalayanın önüne konacak liste:
> `54-d1-faz0-2-kapanis.md` §9.3.
