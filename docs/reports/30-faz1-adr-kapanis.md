# 30 — Faz 1 ADR seti: kararların arkeolojisi ve kapanış değerlendirmesi

**Tarih:** 2026-08-19 · **Dal:** `ahmet` · **Görev:** Faz 1'in tek açık kalemi — ADR seti
**Üretilen:** `docs/adr/` — **17 ADR + `README.md` dizini**
**Tetikleyen kayıt:** `docs/reports/14-nihai-denetim.md:221` — *"Faz 1 ❌ AÇIK · **ADR seti YOK** — `find docs -iname "*adr*"` → **0**. İmza yok"*

> **Bu belge hiçbir `.py`, DocType/politika JSON'una ya da `docs/standards/`
> dosyasına dokunmadı.** Bütün kaynaklar **salt okundu**. Yazılan tek şey
> `docs/adr/` altındaki 18 markdown dosyası ve bu rapor.

---

## 0. Tek cümlelik sonuç

> **Faz 1'in ADR ayağı kapandı: 17 karar bulundu, doğrulandı ve ADR biçiminde
> yazıldı — hiçbiri uydurulmadı. Ama Faz 1 KAPANMIYOR: denetimin ikinci gerekçesi
> ("İmza yok") duruyor ve bu bir belge işi değil, bir onay işidir.**

---

## 1. Yöntem — ADR nasıl bulundu

Kural: **ADR "şöyle yapalım" belgesi değildir.** Verilmiş bir kararı kaydeder.
Bu depoda kararlar zaten verilmişti ve çoğu ölçümle gerekçelendirilmişti; bu
çalışma onları bulup biçime döktü.

Taranan kaynaklar:

| Kaynak | Ne çıktı |
|---|---|
| `docs/reports/` 00–29 (31 dosya, ~21.000 satır) | ADR-0001, 0006, 0008, 0010, 0015, 0017'nin ölçüm gövdesi |
| `docs/standards/logo.md` §13 · `company-cover-video.md` §10 | ADR-0012, 0013 (K1–K8'in tetik/ölçüm/dönüş kaydı) |
| `DALGA-A-DEVIR.md` | ADR-0002, 0005, 0009'un doğrulaması |
| **Kod içi gerekçe yorumları** | ADR-0004, 0005, 0007, 0009, 0011, 0016'nın birincil kaynağı |
| DocType JSON'ları (salt oku) | ADR-0005'in şema kanıtı (`media_rendition.json:43-44`) |
| Politika JSON'ları (salt oku) | ADR-0011, 0016 (`video_decision.json`, `policy/slots/`) |

**Bu depoda kod yorumları alışılmadık derecede zengin** ve birçok kararın **tek**
yazılı gerekçesi orada. Örnekler:

- `media/pipeline/image/render.py:90-100` — `WEBP_METHOD=4` (*"method=4 → 37.250
  bayt, method=6 → 37.340 bayt … 4'te kalmak için ölçülmüş bir gerekçe var"*) ve
  `AVIF_SPEED=None` (*"varsayılan → 28.897 B / 59 ms, speed=8 → 41.060 B / 51 ms.
  Hız kazancı bayta değmiyor"*).
- `media/pipeline_bridge.py:610-622` — ADR-0005'in kararı ve gerekçesi, karar
  noktasının tam üstünde.
- `media/naming.py` başlığı — ADR-0001'in iki çağrı yolu ve fix round 1'de
  bulunan Critical hata.
- `media/pipeline_flags.py` başlığı — ADR-0002'nin iki değişmez kuralı.
- `policy/engine.py` başlığı — ADR-0016'nın "tasarım sözü".

Not: `WEBP_METHOD` ve `AVIF_SPEED` **ayrı birer ADR yapılmadı**; ölçülmüş
parametre seçimleridir ve zaten kod içinde sayısıyla gerekçelendirilmiş
durumdalar. ADR-0006'nın "Gerekçe" bölümünde bu tür ayarların nerede yaşadığı
belirtildi.

---

## 2. Yazılan 17 ADR

| # | Karar | Ölçümle mi? | Karar ölçümle DEĞİŞTİ mi |
|---|---|:--:|---|
| 0001 | İçerik-adresli depolama (`sha256[:32]` + shard) | ✅ | Hayır — ama **bedeli** ölçüldü (33 çok sahipli özel URL, 29'u hassas) |
| 0002 | Bayrak arkasında paralel hat | ✅ | Hayır — sözleşme ölçümle doğrulandı (`hooks.py` 23 ekleme / **0 silme**) |
| 0003 | Ayrı app değil, kütüphane | ⚠ | Hayır — ama **uygulama karardan saptı** (G4 kayboldu) |
| 0004 | Saf çekirdek / Frappe kabuğu | ✅ | Hayır — testle kilitli |
| 0005 | `Media Rendition.profile` `Link` → `Data` | ✅ | **EVET** — docname yazımı manifesti boş döndürüyordu (K-2) |
| 0006 | Adaptif kalite: bütçe 4, aralık (70,95) | ✅ | **EVET** — aralık (40,95) 8/10 çözüyordu, (70,95) 10/10 |
| 0007 | Fayda kapısı INV-05 | ✅ | Hayır — ama video hattını **kilitlediği** ölçüldü |
| 0008 | Pillow'da kal, pyvips reddedildi | ✅ 360 koşum | Hayır — K-11 "libvips ekle"den "ölçüldü, ertelendi"ye döndü |
| 0009 | Türevler `File` kaydı açmaz | ✅ | Hayır — ama K7 kota kararıyla **çelişiyor** |
| 0010 | AV1 şimdi eklenmiyor | ✅ 42+ koşum | **EVET** — Faz 1'in "%40 küçük" izlenimi kalite eşitlenince çürüdü |
| 0011 | H.264 birincil, VP9 değil | ⚠ | Hayır — gerekçe dış bilgi, bu depoda ölçülmedi |
| 0012 | Logo merdiveni 4 → **5** basamak, kayıpsız WebP | ✅ | **EVET** — K3 önerisi A idi, ölçüm B'yi getirdi (5/18 tavanı aşıyor) |
| 0013 | Opak JPEG uyarıyla kabul; oran bandı 1:2…2:1 | ✅ | **EVET (K1)** — öneri "RET" idi, JPEG payı %50 çıkınca B; **K2 onaylandı** (%11 < %20) |
| 0014 | Yıkıcı işler çift kapı + kuru koşum | ✅ | Hayır — vacuity kanıtıyla doğrulandı |
| 0015 | S3 yazıldı, varsayılan kapalı, düşüş raporlanır | ✅ 91 test / MinIO | Hayır — ama SigV2 hatası ancak gerçek servise karşı yakalandı |
| 0016 | Slot politikası VERİdir, kod değil | ✅ testle | Hayır |
| 0017 | Saliency eşik üstünde ve yalnız öneri | ✅ n=400 canlı | **EVET** — fixture korpusu (n=32) karar veremedi, canlı örneklem verdi |

**7 ADR'de karar ölçümle değişti.** Bu, depodaki en güçlü desendir: karar önce
**sayısal bir tetikle** yazılıyor, sonra ölçüm tetiği çalıştırıyor ve gerekiyorsa
öneriyi deviriyor. Elenen seçenek tabloları hiçbir yerde silinmemiş; ADR'lerde de
korundu.

### Görev listesinde istenen 8 ADR'nin karşılıkları

| İstenen | Yazılan |
|---|---|
| İçerik-adresli depolama + çok kiracılı bedeli | **ADR-0001** (sonuçlar bölümü gerilimi yazıyor) |
| Bayrak arkasında paralel çalıştırma | **ADR-0002** |
| Tek monolitik app | **ADR-0003** |
| `Media Rendition.profile` `Link` → `Data` | **ADR-0005** |
| Adaptif kalite döngüsü (`DEFAULT_MAX_ENCODES=4`) | **ADR-0006** |
| AV1 şimdi eklenmiyor | **ADR-0010** |
| Kayıpsız WebP logo + 40 KiB tavanı + K3'ün dönüşü | **ADR-0012** |
| Saf çekirdek / Frappe kabuğu ayrımı | **ADR-0004** |

Ek olarak bulunup yazılanlar: **0007** (fayda kapısı), **0008** (Pillow/pyvips),
**0009** (türev `File` açmaz), **0011** (H.264/VP9), **0013** (logo K1/K2),
**0014** (GC çift kapı), **0015** (S3 kapalı), **0016** (politika veridir),
**0017** (saliency).

---

## 3. Yazılamayan kararlar — ve neden

| Karar | Neden ADR yazılmadı |
|---|---|
| **S-03 — "Yeni DocType açılmaz"** | Karar **çürüdü**: bugün 5 DocType kurulu (`Media Asset/Rendition/Processing Job/Profile/Engine Settings`). Ama **terk edilme gerekçesi hiçbir belgede bulunamadı**; SAD hâlâ kararı yürürlükteymiş gibi anlatıyor (`21-t030-mimari-inceleme.md` M-04, BLOKLAYICI). Gerekçesiz bir dönüşü ADR olarak yazmak, gerekçe **uydurmak** olurdu. |
| **Eski hattın (`engine.to_webp`) ne zaman kaldırılacağı** | ADR-0002 iki hattın yan yana yaşayacağını kaydediyor, ama sonlandırma kararı **hiçbir yerde verilmemiş**. Karar yok → ADR yok. |
| **Kapalı-gövde manifest sözleşmesi (2 sorgu)** | `DALGA-A-DEVIR.md` bunu açıkça *"o ayrı bir karar"* diye bırakıyor. Karar **verilmemiş**. |
| **`rate_limit._bucket_key` kova stratejisi (kullanıcı mı IP mi)** | "Kapsam dışı bırakıldı" yazıyor; bir tercih değil bir erteleme. |
| **`Media Asset` `if_owner=1` daraltması** | `DALGA-A-DEVIR.md` bunu bilinçli kısıt olarak sayıyor ama seçenekler ve gerekçe tartışılmamış; geri alma yöntemi yazılı ("iki `if_owner` satırını sil"). Karar niteliği zayıf. |
| **`WEBP_METHOD=4`, `AVIF_SPEED=None`, `JPEG_SAVE_KW`** | Gerçek ölçülmüş kararlar, ama **kod içinde sayısıyla zaten gerekçelendirilmişler** ve kapsamları tek bir sabit. Ayrı ADR şişme olurdu; ADR-0006'da anıldı. |
| **Kota değerlerinin K7'ye göre yeniden boyutlandırılması** | `company-cover-video.md` §10.9 bunu *"bağlı görev — bu karar tek başına eksiktir"* diye bırakıyor. Karar **verilmedi**. |

---

## 4. Faz 1 kapanıyor mu — NET CEVAP

`docs/reports/14-nihai-denetim.md:221` Faz 1'i iki gerekçeyle açık sayıyor:

| Gerekçe | Bugünkü durum |
|---|---|
| **1. "ADR seti YOK — `find docs -iname "*adr*"` → 0"** | ✅ **KAPANDI.** `docs/adr/` altında 17 ADR + dizin. Her ADR'de en az bir `dosya:satır` ya da rapor atıfı var; doğrulanamayan iddialar "doğrulanmadı" diye işaretli. |
| **2. "İmza yok"** | ❌ **AÇIK.** Faz 1 çıktısının (`11-faz1-arge.md`) bir onay/imza bloğu yok ve bu belge onu **veremez** — imza bir insanın eylemidir, bir belgenin değil. Aynı kalem Faz 3 (SAD onaysız), Faz 14 (imza bloğu boş) ve SRS (TASLAK) için de açık. |

> ### KARAR: Faz 1 bu ADR setiyle KAPANMIYOR.
> Denetimin iki gerekçesinden **biri** kapandı. Kalan tek engel bir belge eksiği
> değil, bir **onay** eksiğidir: `docs/reports/11-faz1-arge.md`'ye (ve tercihen
> `docs/adr/README.md`'ye) platform yöneticisinin onay/imza bloğu düşmesi
> gerekiyor.

Bu, ajanın kapatabileceği bir kalem değildir. Bunu "kapandı" saymak,
`13-faz14-kabul.md`'nin eleştirilen alışkanlığını tekrarlamak olurdu.

### Faz 1'in kendi içindeki, denetimin saymadığı açıklar

Denetim yalnız iki gerekçe yazdı, ama `11-faz1-arge.md` §11 kendi kendine **8
ölçülmemiş kalem** listeliyor. Bugünkü durumları:

| # | Ölçülmeyen | Bugün |
|---|---|---|
| Ö-1 | Gerçek ürün fotoğrafında hedefi tutan kalite | ❌ hâlâ ölçülmedi (ADR-0006'nın en büyük boşluğu) |
| Ö-2 | SSIM'in `scikit-image` ile çapraz doğrulaması | ❌ hâlâ ölçülmedi |
| Ö-3 | AV1 vs VP9 kalite-eşitli kıyas | ✅ **KAPANDI** — `22-t072-vmaf-av1.md` (VMAF aracı getirildi, ADR-0010) |
| Ö-4 | Disk taraması ↔ DB sayımı farkı (4.341 vs 4.958) | ❌ açıklanmadı |
| Ö-5 | 220 dpi'lik 102 dosyanın slot dağılımı | ❌ |
| Ö-6 | Saliency merkezinin insan seçimiyle uyumu | ❌ (ADR-0017'de "doğrulanmadı" olarak işaretli) |
| Ö-7 | `company.cover_video` alt sınırının canlıdaki ihlali | ✅ **kısmen** — `08-canli-olcum.md` §7, 23 videonun 5'i okunabildi; slot eşlemesi hâlâ yok |
| Ö-8 | `ruff` | ❌ kurulu değil |

Bu 8 kalem denetimin Faz 1 gerekçesine **girmedi**, dolayısıyla kapıyı bugün
etkilemiyor. Ama Faz 1 "imza"ya geldiğinde imzalayanın önüne bu liste konmalıdır:
**8 kalemin 1'i tam, 1'i kısmen kapandı, 6'sı açık.**

---

## 5. Bu ADR setinin ortaya çıkardığı, daha önce tek yerde yazılı olmayan üç gerilim

ADR'leri yan yana yazmak, tek tek raporlarda görünmeyen üç çelişkiyi görünür
kıldı. Üçü de `docs/adr/README.md` sonunda da kayıtlı:

1. **ADR-0001 ↔ güvenlik.** İçerik-adresleme dedup'u ve `immutable` önbelleği
   getirdi; **aynı** mekanizma çok kiracılı bir okuma sızıntısı doğurdu. Karar
   geri alınmıyor, bedeli kabul ediliyor, düzeltmesi ayrı görev. Bu gerilimin
   SAD'da hiç yazmadığı `21-t030-mimari-inceleme.md` M-18'de bloklayıcı olarak
   duruyor.
2. **ADR-0009 ↔ K7.** Türevler `File` kaydı açmıyor (kota şişmesin diye); ama
   yönetici "rendition'lar kotadan sayılsın" dedi ve kota kapısı **`File`
   üzerinden** bayt sayıyor. İki karar bugün birbirini uygulanamaz kılıyor.
3. **ADR-0007 ↔ ADR-0010/0011.** Fayda kapısı doğru çalışıyor ve **tam bu yüzden**
   video hattı üretimde hiç çıktı vermiyor. Kapı gevşetilmedi (doğru karar), kök
   neden (sabit CRF 23) düzeltilmedi.

---

## 6. Ne yapılmadı

- Hiçbir kaynak dosyaya, DocType/politika JSON'una ya da `docs/standards/`e
  dokunulmadı.
- Hiçbir ölçüm **yeniden koşulmadı**: bu belgedeki her sayı adı geçen rapordan
  ya da doğrudan okunan koddan alındı. Kod atıfları (`dosya:satır`) bu oturumda
  tek tek açılıp doğrulandı; rapor sayıları **doğrulanmadı**, kaynağıyla
  aktarıldı.
- Faz 1'e imza atılmadı ve `11-faz1-arge.md` değiştirilmedi.

---

## 7. KANIT VE KAPI DURUMU — 2026-08-19 eki (D-1 / T-019)

> **Bu bölüm §4'ün "Faz 1 KAPANMIYOR" kararını değiştirmez ve hiçbir onay
> alanı doldurmaz.** Yalnız kapıların ölçülmüş durumunu ve *"kapanmadıysa tek
> adımda ne gerekiyor"* sorusunun cevabını ekler.
> Tam dosya: **`docs/reports/54-d1-faz0-2-kapanis.md`** §3.

### 7.1 Dört kapı

| Kapı | Durum | **Ölçüm [Ö]** | Tek adımda ne gerekiyor |
|---|---|---|---|
| **ADR seti var mı** | ✅ **KAPANDI** | `docs/adr/` → **17 ADR + README**; 17/17'sinde `Bağlam · Seçenekler · Karar · Gerekçe · Sonuçlar` bölümleri tam | — |
| **Geri dönüş yolu** | ❌ **AÇIK** | `grep -l '^## .*[Gg]eri dönüş' docs/adr/*.md` → **0**. Şablon **5 bölümlü**, altıncı bölüm hiçbir ADR'de kurulmamış. Metin içinde geri dönüş koşulu geçen: **2** ADR (`0002`, `0003`) | 17 ADR'ye birer `## Geri dönüş yolu`. 15'i **karar** ister, kopyalanamaz |
| **8 zorunlu konu** | ❌ **6 / 8** | Eksik 1: **istemci kütüphane seti** — `grep -liE 'mediabunny\|uppy\|istemci kütüphane\|client-side\|tarayıcı tarafı' docs/adr/0*.md` → **0 dosya**. Eksik 2: **CDN** — `grep -lw CDN` → yalnız `0001`, orada da **1 kez** (yan cümle, ADR konusu değil) | 2 yeni ADR. **Girdileri hazır:** `44-t081-yukleyici.md` (istemci) ve `27-t052-cdn-teslim.md` (CDN). Üç fazın en somut, tek oturumda kapatılabilir kalemi |
| **İmza** | ❌ **AÇIK** | `11-faz1-arge.md`'de ve `docs/adr/README.md`'de **onay bloğu fiziksel olarak yok**. `07-faz0-kapanis.md` §10'daki gibi doldurulacak bir alan **kurulmamış** | Önce bloğu **kur**, sonra imzaya sun. Blok kurmak belge işidir; imza insan eylemidir |

### 7.2 Faz 1'in karnesi bugün değişti — T-017 kapandı **[Ö]**

`33-dogrulama-faz0-3.md` T-017'yi **YOK** (kanca yolu RED=2 / GEÇTİ=8) diye
ölçmüştü. Bu oturumda kapı bağımsız olarak yeniden ölçüldü — 10 kötücül fixture,
`upload_policy.check()`, iki yolda, ret kodlarıyla:

```
bomb_100mp.png  [upload_image_bomb]      · data_uri_svg.txt  [upload_content_dangerous]
empty_zero_byte.jpg [upload_content_empty] · executable_as.png [upload_content_dangerous]
fake_docx.docx  [upload_container_invalid] · jpeg_with_html_tail.jpg [upload_appended_payload]
polyglot_pdf_as.jpg [upload_type_mismatch] · polyglot_png_as.jpg [upload_type_mismatch]
script_payload.svg [upload_ext_denied]    · truncated.jpg   [upload_content_truncated]

kanca yolu: RED=10 GECTI=0        medya ucu: RED=10 GECTI=0
```

✅ Kaynağın kabul kriteri (*"`fixtures/malicious/` içindeki HER dosya
reddediliyor"*) **karşılanıyor**. 100 MP decompression bomb iki yolda da kesiliyor.

| Faz 1 karnesi | rapor 33 (bu sabah) | **bugünkü ölçümle** |
|---|---:|---:|
| TAM | 5 | **6** |
| KISMİ | 4 | 4 |
| **YOK** | **1** (T-017) | **0** |

> Rapor 33 yalnız-oku alandır; düzeltme burada ve `54-…md` §3.3'te kayda geçti.

### 7.3 İmzalayanın önüne konacak ek liste

§4'ün son tablosundaki 8 ölçülmemiş kalem (`11-faz1-arge.md` §11) imza anında
görülmelidir: **1 tam · 1 kısmen · 6 açık**. Bu oturumda hiçbiri yeniden
ölçülmedi — **[R]**.

> **Faz 1 üç fazın imzaya en yakın olanıdır:** açık üç kalemin ikisi belge
> işidir (2 ADR + geri dönüş yolu bölümleri), üçüncüsü bir onay bloğunun
> kurulmasını ister. §4'ün kararı geçerlidir: **Faz 1 bugün kapanmıyor.**
