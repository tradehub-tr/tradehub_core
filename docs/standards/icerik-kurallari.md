# İçerik Uygunluk Kuralları ve Eşik Kalibrasyonu

**T-025** · Medya Motoru · Rapor tarihi: **2026-08-17**
Branch: `medya-motoru-faz0-faz2` · Çalışma alanı: `/Users/ahmet/Desktop/istoc-medya-wt`

Politika dosyası: `tradehub_core/media/pipeline/policy/content_rules.json`
Kalibrasyon betiği: `scripts/calibrate_content_rules.py` (**yazıldı, çalıştırılmadı**)

---

## 0. Bu belgenin dürüstlük beyanı

**Bu belgedeki hiçbir eşik kalibre edilmemiştir.** Hepsi literatürden ya da
yaygın pratikten türetilmiş **başlangıç değerleri**dir ve her birinin yanında
nereden geldiği yazılıdır.

| Kısıt | Durum |
|---|---|
| Docker | Kapalı |
| Üretim veritabanı | Erişim yok |
| Canlı site | Erişim yok |
| Etiketli görsel korpusu | **Yok** |
| `bench` | Çalıştırılmadı |
| `scripts/calibrate_content_rules.py` | Yazıldı, **çalıştırılmadı** (yalnız `python3 -m py_compile` ile sözdizimi denetlendi) |

Bu oturumda **hiçbir görsel ölçülmedi**. Betikteki metrik fonksiyonları tek bir
gerçek görselle sınanmadı. "Yanlış pozitif oranı < %5" bir **hedeftir**, bir
bulgu değil — hiçbir kural için ölçülmedi.

Ölçülmesi gerekip ölçülemeyen her şey §7 (**ÜRETİMDE DOĞRULANMALI**)
bölümündedir; orada çalıştırılacak komutlar tam olarak yazılıdır.

---

## 1. Mevcut durum — kodda zaten ne var

Bu bölüm yeni tasarım değil, **var olanın envanteri**.

### 1.1 NSFW yolu ZATEN VAR

İki dosyada OpenAI tabanlı moderasyon çalışıyor. Bu politika onu
**yeniden tasarlamaz**, üstüne eşikleme ve kapsam ekler.

| Ne | Yer | Ne yapıyor |
|---|---|---|
| Vision çağrısı | `tradehub_core/api/moderation.py:100-132` | `gpt-4o-mini`'ye JSON şemalı prompt: `{decision, nsfw_score 0-1, violence_score 0-1, text_detected}`. `urllib.request`, `timeout=30` (`:130`) |
| Stub yedeği | `tradehub_core/api/moderation.py:95-97` | API anahtarı yoksa **her görsele `allow`** |
| Anahtar kaynağı | `tradehub_core/api/moderation.py:143-148` | `Translation Settings.openai_api_key` (`get_password`) |
| Hook | `tradehub_core/api/moderation.py:135-176` | `check_image_content(doc, method)` |
| Hook bağlantısı | `tradehub_core/hooks.py:437-439` | **yalnız** `Listing Review Image` → `after_insert` |
| Log | `tradehub_core/api/moderation.py:161-169` | `Image Moderation Log` doctype'ına yazar |
| Red aksiyonu | `tradehub_core/api/moderation.py:172-173` | `Listing Review.status = "Hidden"` |
| Admin manuel kontrol | `tradehub_core/api/moderation.py:179-195` | `admin_check_image(image_url)` whitelisted |

`Image Moderation Log` alanları
(`tradehub_core/tradehub_core/doctype/image_moderation_log/image_moderation_log.json`):
`review` (Link → Listing Review), `image_url`, `decision`
(`allow|reject|manual_review`), `nsfw_score`, `violence_score`,
`text_detected`, `checked_at`.

Ayrıca metin tarafında kural motoru var:
`tradehub_core/api/moderation.py:18-52` `_evaluate_rules()` — `Moderation Rule`
doctype'ından `risk_score_high` / `abuse_threshold` / `banned_phrase` /
`reviewer_repeat_rejected` tetikleyicilerini okuyup `auto_reject` / `auto_hide` /
`flag_for_review` / `suspend_user` uyguluyor (`:55-89`). Sentiment tarafı
`tradehub_core/api/sentiment.py` — aynı OpenAI anahtarı, aynı stub-fallback
deseni (`:120-130`).

### 1.2 Mevcut NSFW yolunun beş açığı

Bunlar bu belgenin bulgusu; **çözümü bu belgede yok**, çünkü mevcut koda
dokunmuyoruz. Kayda geçiriliyor.

1. **Kapsam.** Hook yalnız `Listing Review Image`'da (`hooks.py:437-439`).
   `Listing Image` (ürün görseli) ve satıcı vitrin görselleri
   (`tradehub_core/api/seller.py:1647` üzerinden yüklenen `gallery_images`,
   tavan 20) **hiç moderasyondan geçmiyor**. Yani pazaryerinde asıl teşhir
   edilen görseller denetimsiz.
2. **Skorlar karara girmiyor.** `moderation.py:165-166` `nsfw_score` ve
   `violence_score` alanlarını **kaydediyor**, `:172` ise kararı yalnız modelin
   döndürdüğü `decision` **string**'ine bakarak veriyor. Yani eşik diye bir şey
   yok; dil modelinin kelime seçimine güveniliyor.
3. **`manual_review` ölü karar.** `Image Moderation Log.decision` alanında
   `manual_review` seçeneği var (doctype JSON), ama hiçbir kod bunu bir kuyruğa
   düşürmüyor. Kaydedilir, kimse bakmaz.
4. **Fail-open.** Anahtar yoksa `_stub_check_image()` her şeye `allow`
   (`:95-97`, `:156-157`). Anahtar süresi dolarsa moderasyon **sessizce**
   kapanır; hiçbir uyarı üretilmez.
5. **Senkron ağ çağrısı.** `after_insert` içinde 30 saniyeye kadar bloklayan
   HTTP isteği (`:130`). Yükleme isteğinin gecikmesi doğrudan OpenAI'nin yanıt
   süresine bağlı.

### 1.3 Minimum görsel sayısı ZATEN VAR

3 sayısı bu politikanın icadı değil:

| Ne | Yer |
|---|---|
| `if len(images) < 3: missing.append(f"Ek Görseller ({len(images)}/3)")` | `tradehub_core/utils/completeness.py:231-232` |
| Görsel başına 0.10 puan, tavan 0.30 | `tradehub_core/utils/completeness.py:140-141` |
| 5 görselde +0.10 bonus | `tradehub_core/utils/completeness.py:142-143` |
| Yorum görseli tavanı: 10 | `tradehub_core/tradehub_core/doctype/listing_review/listing_review.py:25` (`MAX_IMAGES`) |
| Satıcı vitrin tavanı: 20 | `tradehub_core/api/seller.py:1647` |

`min_image_count` kuralının tek yeniliği: bu eşiği **yayın anında görünür bir
uyarıya** çevirmek. Sayım tanımı değişmez — `primary_image` sayıya dâhil
değildir (`completeness.py:139-140`).

### 1.4 Yeniden yazılmayan altyapı

| İhtiyaç | Kodda zaten var |
|---|---|
| Hata kodu sözleşmesi (`kod` + `retryable`) | `tradehub_core/media/upload_policy.py:99-139` |
| Kodlu ret mekanizması | `tradehub_core/media/upload_policy.py:142-162` (`UploadRejected`, `reddet()`) |
| İçerik imzası / tehlikeli içerik | `tradehub_core/media/upload_policy.py:187-224` (`_DANGEROUS_MARKERS`) |
| Atlama sebepleri sözlüğü | `tradehub_core/media/gates.py:28-37` (`SKIP_REASONS`) |
| EXIF döndürme + Pillow ön işleme | `tradehub_core/media/pipeline.py:102`, `:161` |
| Animasyon tespiti | `tradehub_core/media/pipeline.py:60` (`Probe.animated`) |
| Kalite/boyut varsayılanları | `tradehub_core/media/presets.py:13-16` (balanced: 2000px / q88) |

İçerik kuralları bu sözleşmelerin **aynısını** kullanır: kod + retryable
biçimi, `not_measurable` gibi atlama sebepleri, aynı ön işleme.

---

## 2. Karar modeli

```
pass  <  warn  <  manual_review  <  reject
```

**KRİTİK KURAL — yalnız iki kural RED üretebilir:**

| RED üretebilen | RED üretemeyen (hepsi UYARI) |
|---|---|
| `nsfw_content` | `flat_background`, `frame_fill`, `overlay_text`, `border_frame`, `blur`, `duplicate_image`, `min_image_count` |
| `extreme_blur` | |

- **Uyarı** = kullanıcıya gösterilen, kapatılabilir öneri. Kayıt oluşur, yayın
  **engellenmez**, `completeness_score`'a **dokunulmaz**
  (`completeness.py:134-147` bu politikanın konusu değil).
- **Red** = dosya **silinmez**; ilgili kayıt `Hidden` durumuna alınır ve
  moderasyon kuyruğuna düşer. Mevcut davranışla aynı
  (`moderation.py:172-173`). İtiraz edilebilir.
- Birden çok kural tetiklenirse **en yüksek aksiyon** kazanır; uyarılar
  birikimli listelenir.

**Neden bu kadar az RED?** Uyarı gürültüsü bedavaymış gibi görünür ama
değildir: satıcı ilk üç yanlış uyarıdan sonra hepsini kapatmayı öğrenir ve
kural seti işlevsiz hâle gelir. Bu yüzden FP bütçesi uyarılarda **%5**, red
kurallarında **%1** olmalıdır (§4.2).

### 2.1 Hata kodları

`upload_policy.py:99-139`'daki `Kod(kod, retryable)` biçimiyle aynı; ön ek
`content_` (yükleme reddi değil, içerik değerlendirmesi).

| Kural | Kod | retryable |
|---|---|---|
| flat_background | `content_background_not_flat` | false |
| — alt sinyal | `content_background_not_white` | false |
| frame_fill | `content_frame_fill_low` | false |
| overlay_text | `content_overlay_text` | false |
| border_frame | `content_has_border` | false |
| blur | `content_blurry` | false |
| extreme_blur | `content_extreme_blur` | false |
| nsfw_content | `content_nsfw` | false |
| duplicate_image | `content_duplicate_image` | false |
| min_image_count | `content_min_images` | false |

Hiçbiri retryable değil: aynı görsel aynı sonucu verir.

---

## 3. Kurallar — ölçüm, eşik, aksiyon, mesaj

### 3.0 Ortak ön işleme (eşiklerin ön koşulu)

Tüm ölçümler şu ön işlemden **geçmiş** görsel üzerinde yapılır. Ön işleme
değişirse **eşikler anlamını yitirir** — özellikle Laplacian varyansı ölçeğe
duyarlıdır.

| Adım | Değer | Gerekçe |
|---|---|---|
| EXIF | `ImageOps.exif_transpose` | `media/engine.py:102` ile aynı |
| Analiz uzun kenarı | **512 px**, LANCZOS | Ölçek sabitlenmeden Laplacian eşiği taşınamaz |
| Renk uzayı | RGB; luma = BT.601 (`0.299R+0.587G+0.114B`) | |
| Alfa | Beyaz zemine kompozit; bbox için alfa maskesi tercih edilir | Kesilmiş (cut-out) PNG yaygın |
| Atla: animasyonlu | `pass` + sebep `not_measurable` | `media/engine.py:60` |
| Atla: uzun kenar < 200 px | `pass` + sebep `not_measurable` | Metrikler güvenilmez |

`not_measurable` **uyarı üretmez**. "Ölçemedim"i "temiz" saymak da "kirli"
saymak da yanlıştır; kural sessizce atlanır ve loglanır.

---

### 3.1 Düz / beyaz zemin — `flat_background` → **UYARI**

| | |
|---|---|
| **Ölçüm** | Dış kenardan 2 px kalınlığında halka alınır. Halkanın kanal-başına **medyanı** zemin rengi kabul edilir (ortalama değil: ürün kenara taşmışsa ortalama kayar). Zemin rengine kanal-başına maksimum farkı toleransta kalan piksellerin oranı = `flat_bg_ratio`. |
| **Eşik** | `flat_bg_ratio < 0.90` → uyarı. Tolerans **12/255**, halka 2 px. |
| **Alt sinyal** | `flat_bg_ratio >= 0.90` ama zemin luma `< 240` → ayrı uyarı `content_background_not_white` |
| **Durum** | **KALİBRE EDİLMEDİ — başlangıç değeri** |
| **Nereden** | %90 oranı görev tanımından. Tolerans 12/255 (~%4.7) JPEG blok gürültüsünün tipik genliğinden: q88 JPEG'de düz alanlarda ±8-10 seviye sapma olağan (`media/presets.py:15` varsayılan kalite 88). `white_luma_min=240` pazaryeri pratiği (saf beyaz 255; 240 stüdyo aydınlatmasına pay bırakır). |

**Kullanıcı mesajı:**
> Fotoğrafın arka planı karışık görünüyor. Ürünü düz, tercihen beyaz bir zemin
> üzerinde çekerseniz alıcılar ürünü daha net görür.

**İpucu:** Beyaz bir kâğıt/fon üzerine koyup tekrar çekebilir ya da arka planı
silen bir uygulama kullanabilirsiniz.

**Yanlış pozitif riski: orta.** Lifestyle/ortam çekimleri kasıtlı olarak
karışık zeminlidir. Kenara taşan geniş desenli tekstilde zemin halkası ürünün
kendisidir (İstoç'ta tekstil yoğun). Gradyan stüdyo fonları düz değildir ama
profesyoneldir. → Kalibrasyonda lifestyle görselleri ayrı etiketlenmeli.

---

### 3.2 Ürün çerçeve doluluğu — `frame_fill` → **UYARI**

| | |
|---|---|
| **Ölçüm** | Zemin rengi §3.1 gibi bulunur; toleransı aşan pikseller ön plan maskesi olur. **Alfa kanalı varsa maske ondan alınır** (daha güvenilir). Maskenin satır/sütun kütle dağılımında %0.5–%99.5 yüzdelikleri bbox sınırıdır (tek tük gürültü pikseli bbox'ı kadraja şişirmesin). `fill_ratio = bbox alanı / görsel alanı`. |
| **Eşik** | `fill_ratio < 0.70` → uyarı. Tolerans **20/255**. `foreground_ratio < 0.02` ise `not_measurable` (uyarı yok). |
| **Durum** | **KALİBRE EDİLMEDİ — başlangıç değeri** |
| **Nereden** | %70 görev tanımından ve büyük pazaryerlerinin ürün fotoğrafı kılavuzlarındaki "%85 doluluk" önerisinden **bilinçli olarak gevşetilmiş** — %85 ambalajlı/kutulu üründe yanlış pozitif üretir. Tolerans 20/255, zemin kuralındakinden yüksek: burada amaç zemini değil **ürünü** bulmak; gölge ve yansımayı zemin saymak istiyoruz. |

**Kullanıcı mesajı:**
> Ürün fotoğrafta çok küçük kalmış. Ürünü kadraja daha çok doldurarak
> (yakından çekerek veya kırparak) alıcıların detayları görmesini sağlayın.

**İpucu:** Ürün fotoğrafın en az dörtte üçünü kaplamalı. Fazla boşluğu
kırpmanız yeterli.

**Yanlış pozitif riski: orta-yüksek.** İnce uzun ürünlerde (halat, boru, kablo)
bbox alanı doğal olarak küçüktür. Beyaz zeminde beyaz/şeffaf ürünün maskesi
eksik çıkar. → Alfa varsa bbox **alfadan** hesaplanır; bu dallanma betikte
uygulandı.

---

### 3.3 Metin / filigran / logo bindirmesi — `overlay_text` → **UYARI**

| | |
|---|---|
| **Ölçüm (birincil)** | **MEVCUT KODU KULLANIR.** `moderation.py:100-132` Vision çağrısı zaten `text_detected` döndürüyor ve `:167` bunu `Image Moderation Log.text_detected` alanına yazıyor. Yeni bir OCR yolu kurulmaz; var olan alan okunur. |
| **Ölçüm (yedek)** | `pytesseract` ile OCR; `conf >= 60` ve kelime uzunluğu `>= 3` filtreli kutu alanlarının toplamı / görsel alanı. Kenar bölgesindeki (dış %15) metin ayrıca sayılır. |
| **Eşik** | Vision `text_detected` uzunluğu `>= 3` **VEYA** yerel `ocr_text_area_ratio >= 0.02` → uyarı |
| **Durum** | **KALİBRE EDİLMEDİ — başlangıç değeri** |
| **Nereden** | `min_chars=3`: 1-2 karakterlik OCR çıktısı neredeyse hep gürültüdür (desen, vida). `conf=60` Tesseract'ın 0-100 ölçeğinde yaygın gürültü kesme noktası. Alan oranı %2: altındaki metin genelde ürünün **üzerindeki** meşru marka etiketi, üstündeki bindirmedir. |

**Kullanıcı mesajı:**
> Fotoğrafın üzerinde yazı, logo veya filigran görünüyor. Ürün fotoğraflarında
> bindirilmiş metin ve fiyat etiketi kullanılmamalı.

**İpucu:** Ürünün kendi üzerindeki marka/etiket sorun değil; sonradan eklenen
yazı, çerçeve yazısı ve filigranı kaldırın.

**Bağımlılık durumu:**
- Birincil yol **hazır** ama yalnız `Listing Review Image`'da tetikleniyor
  (`hooks.py:437-439`) — ürün görsellerinde hiç çalışmıyor.
- Yedek yol **eksik**: `pytesseract` ve `tesseract-ocr` ikilisi ne
  `pyproject.toml` (`dependencies = ["defusedxml>=0.7", "scikit-learn>=1.3"]`)
  ne `requirements.txt` içinde. Bağımlılık eklenmeden yerel OCR kapalıdır.

**Yanlış pozitif riski: YÜKSEK — listedeki en riskli kural.** Ürünün kendisi
metin taşıyabilir: kitap kapağı, ambalajlı gıda, etiketli bidon, matbaa ürünü,
teknik çizim. Bunlar İstoç'ta yaygın. → Metnin **kenarda** mı (filigran
olasılığı) yoksa **ürün bbox'ı içinde** mi (meşru olasılığı) olduğu ayrımı
kalibrasyonda mutlaka ölçülmeli. FP %5'in altına inmezse kural **varsayılan
olarak kapatılmalı**.

---

### 3.4 Çerçeve / kenarlık — `border_frame` → **UYARI**

| | |
|---|---|
| **Ölçüm** | Kenardan içeri 1..`max_t` derinlikte halkalar taranır. Çerçeve = üç koşul **birlikte**: **(a)** 0..t-1 halkaları kendi içinde düz (kanal std < 6), **(b)** t derinliğindeki halka band renginden `>= 30/255` ayrılıyor, **(c)** band renginin **iç bölgedeki** kaplama oranı `<= 0.50`. |
| **Eşik** | `border_thickness_px >= 2` ve (a)(b)(c) sağlanıyor → uyarı. `max_t = 0.05 × min(genişlik, yükseklik)`. Çevre kapsaması `>= %95`. |
| **Durum** | **KALİBRE EDİLMEDİ — başlangıç değeri** |
| **Nereden** | `max_thickness_ratio=0.05`: gerçek dekoratif çerçeveler kısa kenarın %5'inden incedir; üstü zemindir. `band_std_max=6` ve `band_contrast_min=30`, §3.1'deki 12/255 toleransıyla tutarlı seçildi — "düz" sayılmak için toleranstan sıkı, "ayrı" sayılmak için üç kat gevşek olmalı ki gri geçişler çerçeve sanılmasın. Çevre %95: bir kenarı eksik olan şey çerçeve değildir. |

**(c) koşulu neden şart:** onsuz **düz beyaz zeminli her ürün fotoğrafı
"çerçeveli" sayılırdı** — beyaz halkalar düzdür, sonunda ürüne çarpar ve
kontrast koşulu sağlanır. (c) bu politikanın ana yanlış-pozitif kalkanıdır.

**Kullanıcı mesajı:**
> Fotoğrafa çerçeve/kenarlık eklenmiş görünüyor. Ürün fotoğraflarında çerçeve
> kullanılmamalı — vitrindeki kırpma ile üst üste binerek kötü görünür.

**İpucu:** Çerçeveyi kırpın; ürün fotoğrafın kenarına kadar uzanmalı.

**Yanlış pozitif riski: orta.** Ürünün kendisi çerçeve olabilir (tablo, ayna,
pencere profili — İstoç'ta gerçek ihtimal). Vinyet ışıklandırma. Ekran
görüntüsünden kalan kenar şeridi ise **doğru** pozitiftir.

---

### 3.5 Bulanıklık — `blur` → **UYARI**

| | |
|---|---|
| **Ölçüm** | Gri tonlama → uzun kenar 512 px → 4-komşulu 3×3 Laplacian → sonucun **varyansı**. OpenCV kullanılmaz; numpy dilimlemesiyle yazıldı. |
| **Eşik** | `laplacian_var < 100.0` → uyarı |
| **Durum** | **KALİBRE EDİLMEDİ — başlangıç değeri** |
| **Nereden** | Yöntem: Pech-Pacheco ve ark., *"Diatom autofocusing in brightfield microscopy: a comparative study"*, ICPR 2000. **100 eşiği OpenCV topluluğunda yaygınlaşmış başlangıç değeridir ve görsel kümesine özgüdür — evrensel değildir.** Bu yüzden kalibrasyon zorunlu. |

**Kullanıcı mesajı:**
> Fotoğraf net görünmüyor. Alıcılar bulanık fotoğraflı ürünlere daha az
> güveniyor — daha net bir kare çekmenizi öneririz.

**İpucu:** Telefonu sabitleyin, ürüne dokunarak odaklayın ve yeterli ışıkta
çekin.

**Yanlış pozitif riski: orta.** Kasıtlı sığ alan derinliği (bokeh) genel
varyansı düşürür. Düz renkli desensiz ürünler (tek renk kumaş topu, düz metal
levha) net olsa bile kenar enerjisi düşüktür. Ağır JPEG detayı silmiş olabilir.
→ Ölçümü **ürün bbox'ı içinde** yapmak ve "kenar yoğunluğu çok düşük" durumunu
`not_measurable` saymak gerekir; bu iyileştirme kalibrasyonla doğrulanmadan
uygulanmamalı.

---

### 3.6 Aşırı bulanıklık — `extreme_blur` → **RED**

| | |
|---|---|
| **Ölçüm** | §3.5 ile aynı, **artı üç koruma koşulu**. |
| **Eşik** | `laplacian_var < 20.0` **VE** `tenengrad_mean < 4.0` **VE** orijinal uzun kenar `>= 800 px` → RED |
| **Durum** | **KALİBRE EDİLMEDİ — başlangıç değeri.** Kalibre edilene kadar `reject` yerine `manual_review` modunda çalıştırılmalı (§5, stage_1). |
| **Nereden** | 20.0, uyarı eşiğinin (100) beşte biri; bu seviyede görsel "ürün seçilemiyor" sınıfına girer. **İkinci sinyal (Tenengrad = Sobel gradyan enerjisi ortalaması) istenmesinin sebebi:** tek metriğe dayalı RED, tek hatalı ölçümle satıcının ürününü yayından düşürür. `>= 800 px` koruması: küçük görseller `media/gates.py:59` `too_small` kapısının konusudur, RED buraya taşınmamalı. |

**Kullanıcı mesajı:**
> Bu fotoğraf ürünün seçilemeyeceği kadar bulanık olduğu için yayınlanamadı.
> Lütfen daha net bir fotoğraf yükleyin.

**İpucu:** Fotoğraf çok bulanık olduğu için kabul edilemedi. Yeniden çekip
yükleyebilir veya itiraz edebilirsiniz.

**RED aksiyonu:** kayıt `Hidden`, dosya **silinmez**, moderasyon kuyruğu,
itiraz açık.

**Yanlış pozitif riski:** korumalarla düşük, korumasız yüksek (buğulu/mat yüzey
makro çekimleri; ürünü hâlâ gösteren hareket bulanıklığı). **RED eşiği
kalibrasyonda FP %1'in altına inmeden açılmamalıdır.**

---

### 3.7 NSFW / yasaklı içerik — `nsfw_content` → **RED + moderasyon kuyruğu**

| | |
|---|---|
| **Ölçüm** | **MEVCUT KOD, YENİDEN TASARLANMADI.** `moderation.py:100-132` → `gpt-4o-mini` Vision, `{decision, nsfw_score, violence_score, text_detected}`. Anahtar: `Translation Settings.openai_api_key` (`:143-148`). Anahtar yoksa `_stub_check_image()` her şeye `allow` (`:95-97`). Log: `Image Moderation Log` (`:161-169`). |
| **Eşik** | `nsfw_score >= 0.85` **VEYA** `violence_score >= 0.85` → RED. `0.50 – 0.85` bandı → `manual_review`. Stub modunda → `pass`. |
| **Durum** | **KALİBRE EDİLMEDİ — başlangıç değeri.** Ayrıca: **mevcut kod bu skorları hiç eşiklemiyor** (§1.2 madde 2). |
| **Nereden** | 0.85/0.50 ikili eşik kurulumu ticari içerik moderasyonu API'lerinin tipik hassasiyet/duyarlılık ayrımından alınan başlangıç değeridir. **Uyarı:** `gpt-4o-mini`'nin döndürdüğü sayı kalibre edilmiş bir olasılık değil, dil modelinin ürettiği bir sayıdır. Gerçek bir sınıflandırıcı skorundan daha az güvenilirdir ve dağılımı ÜRETİMDE ölçülmelidir (§7). |

**Kullanıcı mesajı:**
> Bu görsel içerik kurallarımıza uymadığı için yayınlanamadı ve incelemeye
> alındı. Hatalı olduğunu düşünüyorsanız itiraz edebilirsiniz.

**İpucu:** Görsel moderasyon kuyruğuna alındı. Bir yetkili en kısa sürede
inceleyecek.

**RED aksiyonu:** kayıt `Hidden` (mevcut davranış, `:172-173`), moderasyon
kuyruğu, admin bildirimi, itiraz açık.

**Yanlış pozitif riski: bilinmiyor — ölçülmedi.** İstoç'a özgü birinci derece
riskler:

| Kategori | Neden tetiklenir |
|---|---|
| İç giyim / mayo / çorap / tekstil | Mankenli çekimlerde NSFW skoru meşru şekilde yükselir |
| Kasap / çiğ et / gıda | `violence_score` tetiklenir |
| Bıçak / kesici / hırdavat / av | `violence_score` tetiklenir, ürünler meşrudur |

→ **Kategori muafiyeti şart.** Bu kategorilerde `reject` yerine
`manual_review`. Muafiyet listesi `content_rules.json` →
`category_overrides`. **Kategori adları placeholder'dır**; gerçek
`Product Category` adları üretim veritabanından alınmalı (§7).

---

### 3.8 Yinelenen görsel — `duplicate_image` → **UYARI**

| | |
|---|---|
| **Ölçüm** | Gri tonlama → 32×32 → 2B **DCT-II** → sol üst 8×8 blok → DC hariç medyan eşikleme → **64 bit pHash**. Aynı `Listing` altındaki çiftlerin **Hamming** mesafesi. `imagehash`, `scipy`, `opencv` bağımlılığı **yok**: DCT matrisi saf numpy ile kuruluyor. |
| **Eşik** | `phash_hamming_distance <= 8` → uyarı |
| **Durum** | **KALİBRE EDİLMEDİ — başlangıç değeri** |
| **Nereden** | 64 bit pHash için yaygın pratik: `<=5` "neredeyse aynı", `<=10` "benzer". 8 ikisinin ortası. |

**Kullanıcı mesajı:**
> Bu üründe birbirinin neredeyse aynısı olan görseller var. Farklı açılardan
> çekilmiş fotoğraflar alıcının kararını kolaylaştırır.

**İpucu:** Tekrar eden fotoğrafı kaldırıp yerine farklı bir açı, detay veya
ölçek fotoğrafı ekleyin.

**Yanlış pozitif riski: YÜKSEK.** pHash renge büyük ölçüde **duyarsızdır**;
aynı pozda çekilmiş **renk varyantları** yakın hash verir ve bu tam olarak
yanlış pozitiftir. Beyaz zeminde ürünün küçük kaldığı fotoğraflarda hash'in
çoğu zemindir, farklı ürünler bile yakın çıkar. → İkinci sinyal olarak **renk
histogramı mesafesi** ölçülmeli: pHash yakın ama renk uzaksa varyant kabul
edilip uyarı **üretilmemeli**. Betik bu değeri (`color_hist_distance`) hesaplar
ve raporlar, ama **eşiği kalibre edilmedi**.

---

### 3.9 Minimum görsel sayısı — `min_image_count` → **UYARI (yayın öncesi)**

| | |
|---|---|
| **Ölçüm** | `len(doc.listing_images)`. Tanım `completeness.py:139-140` ile **aynı**: `primary_image` sayıya dâhil değil. |
| **Eşik** | `< 3` → yayın öncesi uyarı |
| **Durum** | **KALİBRE EDİLMEZ — ürün kararı, ölçüm değil** |
| **Nereden** | 3 sayısı kodda zaten var: `completeness.py:231-232`. |

**Kullanıcı mesajı:**
> Bu ürün için {count} görsel var. En az 3 fotoğraf ekleyen ilanlar alıcılar
> tarafından daha çok tıklanıyor.

**İpucu:** Ön, arka ve detay olmak üzere en az 3 fotoğraf önerilir.

> **Not — sayı uydurmama:** "daha çok tıklanıyor" ifadesi bu kod tabanında
> **ölçülmedi**. Mesaja bilinçli olarak **oran/yüzde yazılmadı**. Gerçek
> tıklanma farkı ölçülmeden mesaja sayı eklenmemeli.

**Yanlış pozitif riski: yok.** Yalnız uyarı; yayını engellemez.

---

## 4. Kalibrasyon — nasıl yapılacak

### 4.1 Betik

`scripts/calibrate_content_rules.py` (891 satır, çalıştırılabilir, **ÇALIŞTIRILMADI**).

Ne yapar:
1. Etiketli korpusu okur (manifest CSV).
2. Her görsel için ölçülebilir metrikleri hesaplar — numpy + Pillow, başka
   bağımlılık yok.
3. Her kural için eşiği süpürür; **her eşik noktasında FP ve FN oranını**
   çıkarır.
4. `FP <= --fp-budget` kısıtı altında FN'i en küçükleyen eşiği **önerir**.
5. Öneriyi JSON'a yazar ve mevcut başlangıç eşiğini yanına koyar.

Ne yapmaz:
- **Ağa çıkmaz.** NSFW skoru üretmez; Vision çıktılarını manifest'ten okur.
- **Politika dosyasını değiştirmez.** Önerir; uygulamak insan kararıdır.

Ölçtüğü metrikler ve kaynak fonksiyonlar:

| Metrik | Fonksiyon |
|---|---|
| `flat_bg_ratio`, `bg_luma` | `flat_bg_ratio()` |
| `fill_ratio`, `foreground_ratio`, `bbox` | `frame_fill_ratio()` |
| `border_thickness_px`, `interior_match` | `border_frame()` |
| `laplacian_var`, `tenengrad_mean` | `laplacian_var()` |
| 64-bit pHash | `phash()` + `hamming()` |
| Renk histogramı L1 mesafesi | `color_hist_distance()` |
| OCR metin alanı (opsiyonel) | `ocr_text_signal()` |

### 4.2 FP/FN tanımı ve bütçe

- **FP** = kural tetiklendi ama insan etiketi "temiz" → satıcıyı **yanlış**
  uyardık.
- **FN** = kural tetiklenmedi ama etiket "kusurlu" → bir kusuru kaçırdık.

Bütçe FP tarafındadır. Yanlış uyarmak, bir kusuru kaçırmaktan pahalıdır:
uyarı gürültüsü bütün kural setini öğrenilmiş çaresizliğe çevirir.

| Kural sınıfı | FP bütçesi |
|---|---|
| Uyarı kuralları | **%5** (`false_positive_budget: 0.05`) |
| RED kuralları (`nsfw_content`, `extreme_blur`) | **%1** — `--fp-budget 0.01` ile ayrıca çalıştırılmalı |

### 4.3 Korpus gereksinimi

- **En az 300 görsel**, **gerçek üretim görsellerinden** örneklenmiş. Sentetik
  korpusla kalibrasyon yanlış güven verir. Betik 300 altında **uyarı basar**.
- Her kural için **her iki sınıftan en az 30 örnek**. Altında betik eşik
  önermez, "YETERSİZ ETİKET" der.
- Kategori dağılımı üretimi yansıtmalı; §3.7'deki riskli kategoriler
  (iç giyim, kasap, bıçak) **mutlaka temsil edilmeli** — yoksa FP oranı
  yapay olarak iyi çıkar.

Manifest CSV (UTF-8, başlıklı):

```
path,listing,category,label_flat_background,label_frame_fill,label_overlay_text,label_border_frame,label_blur,label_extreme_blur,label_nsfw,nsfw_score,violence_score,vision_text_detected
```

Etiket anlamı her kuralda aynı: `1` = kural tetiklenmeli, `0` = tetiklenmemeli,
**boş** = etiketlenmedi, analize girmez.

Yinelenen görsel için ayrı çift dosyası:

```
listing,path_a,path_b,label_duplicate
```

### 4.4 Çalıştırma

```bash
# 1) Uyarı kuralları — FP bütçesi %5
python3 /Users/ahmet/Desktop/istoc-medya-wt/scripts/calibrate_content_rules.py \
  --corpus   /veri/korpus \
  --manifest /veri/korpus/manifest.csv \
  --dup-labels /veri/korpus/duplicates.csv \
  --policy   /Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/pipeline/policy/content_rules.json \
  --out      /veri/korpus/onerilen_esikler_warn.json

# 2) RED kuralları — FP bütçesi %1
python3 /Users/ahmet/Desktop/istoc-medya-wt/scripts/calibrate_content_rules.py \
  --corpus   /veri/korpus \
  --manifest /veri/korpus/manifest.csv \
  --policy   /Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/pipeline/policy/content_rules.json \
  --fp-budget 0.01 \
  --out      /veri/korpus/onerilen_esikler_reject.json
```

Çıktıda her kural için: mevcut başlangıç eşiği, önerilen eşik, o eşikteki FP/FN
oranı ve tam süpürme eğrisi. Politika dosyası **elle** güncellenir ve o satırda
`threshold_status` `KALİBRE EDİLMEDİ — başlangıç değeri` yerine
`kalibre: <tarih>, korpus n=<N>, FP=<oran>` olur.

### 4.5 Bağımlılıklar — doğrulanmadı

| Paket | Durum | Kanıt |
|---|---|---|
| Pillow | Kodda yaygın kullanılıyor ama **doğrudan bağımlılık değil** | `media/engine.py:82`, `:102`, `:161`, `:187` kullanıyor; `pyproject.toml` `dependencies` listesinde YOK — Frappe ile geldiği varsayılıyor |
| numpy | **Dolaylı** — yalnız scikit-learn üzerinden | `requirements.txt:3` `scikit-learn>=1.3` |
| pytesseract / tesseract-ocr | **Kurulu değil** | Ne `pyproject.toml` ne `requirements.txt` içinde |
| opencv / scipy / imagehash | **Kullanılmıyor** — betik hiçbirine ihtiyaç duymayacak şekilde yazıldı | — |

Betik numpy/Pillow yokluğunda `ImportError` ile ölmez; ne kurulacağını yazıp
çıkış kodu 3 döner.

---

## 5. Aşamalı açılış

Kalibre edilmemiş eşikle doğrudan RED üretmek satıcı kaybettirir.

| Aşama | Davranış | Çıkış koşulu |
|---|---|---|
| **0 — gölge** (≥14 gün) | Tüm kurallar çalışır, **loglanır**, kullanıcıya hiçbir şey gösterilmez. RED kuralları da yalnız loglar. | Her kural için el ile örneklenen 200 tetiklenmede FP < %5 (RED kurallarında < %1) |
| **1 — yalnız uyarı** | Uyarılar kullanıcıya gösterilir. `extreme_blur` ve `nsfw_content` `reject` **yerine** `manual_review` üretir. | Moderatörün el ile verdiği karar ile otomatik kararın uyumu > %95 |
| **2 — uygulama** | `nsfw_content` ve `extreme_blur` RED üretir. **Diğer her şey kalıcı olarak uyarı kalır.** | — |

**Geri alma tetiği:** haftalık itiraz oranı reddedilen görsellerin %10'unu
aşarsa aşama 1'e dönülür.

---

## 6. Gözlemlenebilirlik

Log hedefi: mevcut `Image Moderation Log`. **Ama** doctype'ta yalnız `review`
(Link → Listing Review) alanı var; ürün görselleri için genel bir kaynak
referansı (`source_doctype` + `source_name`) **yok**. Bu politika mevcut
doctype'a **dokunmaz**, eksiği kayda geçirir.

Her kural için toplanması gereken:

| Metrik | Neden |
|---|---|
| `trigger_count`, `trigger_rate` | Kuralın ne sıklıkta konuştuğu |
| `manual_override_count` | Moderatör kararı otomatikten farklı |
| `appeal_count`, `appeal_success_rate` | — |

**Üretimde yanlış pozitifin tek gerçek ölçüsü `appeal_success_rate`'tir**;
etiketli korpus üretimde yok. Bu oran %5'i aşan kural kalibrasyona geri döner.

---

## 7. ÜRETİMDE DOĞRULANMALI

Aşağıdakilerin **hiçbiri** bu oturumda yapılmadı. Docker kapalı, üretim
veritabanına ve canlı siteye erişim yok, görsel korpusu yok.

### 7.1 Bağımlılıkların gerçekten var olduğunu doğrula

```bash
# Frappe bench konteynerinde
docker compose exec backend bash -lc \
  'python3 -c "import PIL, numpy; print(\"Pillow\", PIL.__version__); print(\"numpy\", numpy.__version__)"'

# pytesseract (overlay_text yedek yolu) — büyük olasılıkla YOK
docker compose exec backend bash -lc \
  'python3 -c "import pytesseract; print(pytesseract.get_tesseract_version())" || echo YOK'
```

**Beklenen:** Pillow ve numpy var. `pytesseract` YOK → `overlay_text` kuralı
yalnız Vision `text_detected` yoluyla çalışabilir.

### 7.2 Korpusu üretimden örnekle

```bash
# Kategori dağılımını koruyarak 400 ürün görseli örnekle
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, json, random
rows = frappe.db.sql("""
    SELECT li.image, li.parent AS listing, l.product_category AS category
    FROM `tabListing Image` li
    JOIN `tabListing` l ON l.name = li.parent
    WHERE li.image IS NOT NULL AND li.image != ''
""", as_dict=True)
random.seed(42)
random.shuffle(rows)
print(len(rows), "toplam görsel")
open("/tmp/korpus_ornek.json","w").write(json.dumps(rows[:400], ensure_ascii=False))
PY

# Dosyaları çek
docker compose cp backend:/tmp/korpus_ornek.json /veri/korpus/ornek.json
```

Sonra `ornek.json`'daki `image` yollarını `sites/*/public/files` altından
kopyalayıp §4.3'teki manifest'i **elle etiketle**. Etiketleme insan işidir;
otomatikleştirilemez — otomatik etiketle kalibrasyon dairesel olur.

### 7.3 Vision skorlarını üret (NSFW eşiği için)

`nsfw_score`/`violence_score` bu betikte **üretilmez**. Mevcut kod yolu
kullanılmalı:

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, json, csv
from tradehub_core.api.moderation import _openai_vision_check
key = frappe.get_single("Translation Settings").get_password("openai_api_key", raise_exception=False)
assert key, "ANAHTAR YOK — _stub_check_image her şeye allow der, kalibrasyon YAPILAMAZ"
rows = json.load(open("/tmp/korpus_ornek.json"))
with open("/tmp/vision_skorlari.csv","w",newline="",encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["image","nsfw_score","violence_score","text_detected"])
    for r in rows:
        try:
            out = _openai_vision_check(r["image"], key)
            w.writerow([r["image"], out.get("nsfw_score"), out.get("violence_score"), out.get("text_detected","")])
        except Exception as e:
            w.writerow([r["image"], "", "", f"HATA:{e}"])
PY
```

**Uyarı:** anahtar yoksa `_stub_check_image()` her şeye `allow` ve skor 0.0
döner (`moderation.py:95-97`). **Stub ile üretilmiş skorlarla kalibrasyon
yapılamaz** — betik bunu raporunda not eder ama insanın kontrol etmesi gerekir.

Ayrıca 400 görsellik bir tarama **ücretlidir**. Maliyeti bu oturumda
hesaplanmadı (token/görsel fiyatı bilinmiyor); tarama öncesi hesaplanmalı.

### 7.4 gpt-4o-mini skor dağılımını ölç (0.85 eşiği doğru yerde mi)

```bash
docker compose exec backend bench --site istoc.localhost mariadb <<'SQL'
SELECT
  ROUND(nsfw_score, 1) AS kova,
  COUNT(*)             AS adet
FROM `tabImage Moderation Log`
GROUP BY kova ORDER BY kova;

SELECT decision, COUNT(*) FROM `tabImage Moderation Log` GROUP BY decision;

-- Mevcut kodda skor eşiklenmiyor: decision='reject' olanların skor aralığı
SELECT decision, MIN(nsfw_score), AVG(nsfw_score), MAX(nsfw_score),
                 MIN(violence_score), AVG(violence_score), MAX(violence_score)
FROM `tabImage Moderation Log` GROUP BY decision;
SQL
```

**Ne aranıyor:** modelin `decision='reject'` dediği kayıtların skorları 0.85'in
neresinde? Eğer `reject` kararları 0.6 civarındaysa 0.85 eşiği hiç
tetiklenmez ve politika ölü doğar.

### 7.5 min_image_count kuralının kaç ilanı uyaracağını ölç

```bash
docker compose exec backend bench --site istoc.localhost mariadb <<'SQL'
SELECT gorsel_sayisi, COUNT(*) AS ilan_adedi FROM (
  SELECT l.name, COUNT(li.name) AS gorsel_sayisi
  FROM `tabListing` l
  LEFT JOIN `tabListing Image` li ON li.parent = l.name
  GROUP BY l.name
) t GROUP BY gorsel_sayisi ORDER BY gorsel_sayisi;
SQL
```

**Ne aranıyor:** 3'ün altında kaç ilan var? Bu sayı toplamın %70'i ise kural
faydalı bir uyarı değil, kitlesel gürültü olur ve **aşamalı açılışta
düşünülmesi gerekir**.

### 7.6 Kategori adlarını doğrula (muafiyet listesi placeholder)

```bash
docker compose exec backend bench --site istoc.localhost mariadb <<'SQL'
SELECT name, parent_product_category FROM `tabProduct Category`
WHERE LOWER(name) REGEXP 'giyim|mayo|çorap|tekstil|bıçak|kesici|hırdavat|gıda|kasap|et|tablo|ayna|çerçeve|kitap|kırtasiye|matbaa|ambalaj';
SQL
```

`content_rules.json` → `category_overrides` içindeki kategori adları
**placeholder'dır**; bu sorgunun çıktısıyla değiştirilmeli.

### 7.7 Kural motorunun performans maliyetini ölç

Her görselde 512 px'e indirme + 6 metrik hesabı yapılıyor. Yükleme yolunda
senkron çalışırsa gecikme ekler.

```bash
# Korpus hazır olduğunda: 400 görselde toplam süre
time python3 /Users/ahmet/Desktop/istoc-medya-wt/scripts/calibrate_content_rules.py \
  --corpus /veri/korpus --manifest /veri/korpus/manifest.csv \
  --out /tmp/olcum.json --limit 400
```

**Ne aranıyor:** görsel başına ortalama süre. 100 ms'yi aşarsa kural motoru
`after_insert`'te değil kuyrukta (`frappe.enqueue`) çalışmalı — mevcut Vision
çağrısının senkron olması hâlâ ayrı bir sorun (§1.2 madde 5).

### 7.8 Kapsam açığını doğrula

```bash
docker compose exec backend bench --site istoc.localhost mariadb <<'SQL'
-- Moderasyondan geçmiş görsel sayısı vs toplam ürün görseli sayısı
SELECT (SELECT COUNT(*) FROM `tabImage Moderation Log`)  AS moderasyon_kaydi,
       (SELECT COUNT(*) FROM `tabListing Review Image`)  AS yorum_gorseli,
       (SELECT COUNT(*) FROM `tabListing Image`)         AS urun_gorseli,
       (SELECT COUNT(*) FROM `tabSeller Gallery Image`)  AS vitrin_gorseli;
SQL
```

**Beklenen bulgu (doğrulanmadı):** `moderasyon_kaydi ≈ yorum_gorseli`, buna
karşılık `urun_gorseli` ve `vitrin_gorseli` için **sıfır** moderasyon kaydı —
`hooks.py:437-439`'daki tek hook bağlantısının doğal sonucu.

---

## 8. Bu belge neyi kasıtlı olarak yapmadı

| Yapılmadı | Neden |
|---|---|
| Mevcut hiçbir dosya değiştirilmedi | Kural 1: yalnız yeni dosya |
| `moderation.py` yeniden tasarlanmadı | Kural 5: var olanı anlat, üstüne yazma. NSFW yolu §1.1'de belgelendi, §1.2'deki açıkları kayda geçti |
| `Image Moderation Log` doctype'ına alan eklenmedi | Mevcut dosya değişikliği olurdu; eksik §6'da not edildi |
| `completeness.py` skorlaması değiştirilmedi | 3-görsel eşiği orada zaten var; uyarı onu tekrar eder, ezmez |
| Betik çalıştırılmadı | Görsel korpusu yok; çalıştırmak sahte sayı üretirdi |
| Mesajlara istatistik/yüzde yazılmadı | Hiçbiri ölçülmedi (§3.9 notu) |
| Vision maliyeti hesaplanmadı | Token/görsel fiyatı bu oturumda bilinmiyor (§7.3) |

---

## 9. Dosya listesi

| Dosya | Satır | Ne |
|---|---|---|
| `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/pipeline/policy/content_rules.json` | — | 9 kural, eşikler, kategori muafiyetleri, aşamalı açılış, `not_measured` listesi |
| `/Users/ahmet/Desktop/istoc-medya-wt/docs/standards/icerik-kurallari.md` | — | Bu belge |
| `/Users/ahmet/Desktop/istoc-medya-wt/scripts/calibrate_content_rules.py` | 891 | Eşik kalibrasyonu; `chmod +x` yapıldı, **çalıştırılmadı** |
