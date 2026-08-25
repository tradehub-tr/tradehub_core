# T-142 — Kullanıcı kabul testi (UAT) ve satıcı pilotu planı

**Görev:** T-142 · **Faz:** 14 · **Bağımlılık:** T-141 · **Tarih:** 2026-08-18
**Kaynak kabul kriterleri:** `docs/72-faz14-test-kabul.html` → T-142

---

## 0. Bu belgenin durumu — ÖNCE BUNU OKU

> **BU BİR PLANDIR. PİLOT KOŞULMADI.** Bu belgede satıcıdan gelmiş tek bir
> ölçüm, tamamlanmış tek bir görev, hesaplanmış tek bir tamamlama oranı
> **yoktur**. Aşağıdaki her sayı ya bir **eşik** (karar için önceden yazılmış),
> ya bir **hesap** (formülü yanında), ya da **ÖLÇÜLMEDİ** etiketlidir.

**2026-08-24 teknik güncellemesi:** Crop Studio, cihaz önizleme/simülatör,
slot-aware uploader ve küçük-görsel ret yönlendirmesi artık arayüzde vardır ve
otomatik test paketindedir. Pilot teknik olarak koşulabilir. Buna rağmen gerçek
≥10 satıcı, açık rıza, moderatör kayıtları ve ≥%90 anlama ölçümü olmadan T-142
tamamlanmış sayılmaz. Aşağıdaki eski “arayüz yok” tespitlerini bu güncelleme
geçersiz kılar.

### 0.1 Kabul kriterleri karşılığı

| Kaynak dokümandaki kriter | Bu belgedeki karşılığı | Bugünkü durum |
|---|---|---|
| En az 10 gerçek satıcıyla pilot; her biri en az 5 ürün | §2 katılımcı çerçevesi, §3 görev seti | **KOŞULMADI** |
| Görev tamamlama oranı, ortalama süre, hata/karışıklık noktaları ölçülmüş | §4 ölçüm aygıtı, §5 telemetri | **ÖLÇÜLMEDİ** |
| Reddedilen yüklemelerde anlama oranı ≥ %90 | §6 anlama testi + **istatistiksel dürüstlük notu** | **ÖLÇÜLMEDİ** |
| Bulgular önceliklendirilmiş; kritikler go-live öncesi kapalı | §7 bulgu yönetimi, §8 çıkış kapısı | **BULGU YOK** (pilot koşulmadı) |

---

## 1. ÖN KOŞULLAR — teknik akış hazır, saha koşumu açık

Kaynak dokümanın T-142 görev listesi altı görev istiyor. Her birinin bugün
karşılığı olup olmadığı **kod okunarak** belirlendi:

| # | Görev (kaynak dokümandan) | Bugün koşulabilir mi | Dayanak |
|---|---|---|---|
| (a) | 5 ürün görseli yükle | ✅ **EVET** | Slot-aware `MediaUploader` + `seller_media` akışı bağlı; preflight ve sunucu kararı aynı sebep kodlarını kullanıyor. |
| (b) | Kırpma ve odak ayarla | ✅ **EVET** | `CropStudioModal` Medya Kütüphanesi ve ürün formuna bağlı; crop intent, odak ve onay akışı testli. |
| (c) | Önizlemeleri incele ve onayla | ✅ **EVET** | `/media-simulator`, cihaz önizlemeleri ve Crop Studio preview şeridi mevcut. |
| (d) | Logo yükle | ✅ **EVET** | Mevcut panel akışı çalışıyor |
| (e) | Company video yükle | ✅ **EVET** | Mevcut transcode hattı çalışıyor (`tradehub_core/media/transcode.py`) |
| (f) | Bilerek küçük görsel yükle, hata mesajını oku, düzelt | ✅ **EVET** | `short_edge_too_small` / `area_too_small` preflight kodları görünür Türkçe açıklama ve düzeltme yönlendirmesi üretir; sunucu kapısı ayrıca uygular. |

### 1.1 Pilotun iki dalgası — karşılaştırma tasarımı

Teknik eksik nedeniyle bölme zorunluluğu kalktı. Önce/sonra karşılaştırması
isteniyorsa iki dalga korunabilir; yalnız nihai kabul için altı görev aynı pilotta
koşulabilir:

| Dalga | Kapsam | Ön koşulu | Ne öğrenir |
|---|---|---|---|
| **UAT-1** | (a) sınırlı + (d) + (e) | **Bugün koşulabilir** | Bugünkü yükleme akışının taban çizgisi: süre, terk oranı, karışıklık noktaları. Yeni motorla karşılaştırma için **ÖNCE/SONRA** ölçümünün "önce"si |
| **UAT-2** | (a) tam + (b) + (c) + (f) | Teknik akış hazır; gerçek katılımcı/onam/takvim gerekir | Kabul kriterinin kendisi: anlama oranı, kırpma/önizleme akışı |

> **UAT-1 atlanmamalı.** "Sonra"nın anlamlı olması için "önce" ölçümü gerekir;
> `docs/reports/03-performans-taban-cizgisi.md` yalnız teknik taban çizgisini
> (LCP/CLS) ölçtü, **kullanıcı tarafında taban çizgisi yok**.

---

## 2. Katılımcılar

### 2.1 Örneklem çerçevesi

**Hedef:** ≥ 10 gerçek satıcı, her biri ≥ 5 ürün.

Çerçeve gerçek veriden çıkarılır (ÖLÇÜLECEK, bugün ÖLÇÜLMEDİ):

```sql
-- Aktif satıcı sayısı ve ürün başına medya dağılımı
select p.name as store, count(distinct l.name) as urun, count(f.name) as medya
from `tabAdmin Seller Profile` p
left join `tabListing` l on l.seller = p.name
left join `tabFile` f on f.attached_to_name = l.name
group by p.name
order by urun desc;
```

Bilinen tek ölçüm: **4.958 dosya / 1.559 MB** (`docs/reports/08-canli-olcum.md`),
sahiplik zinciri **%100 çözülebiliyor** (`media/ownership.py:6` — 2.839/2.839).
Satıcı başına dağılım **ÖLÇÜLMEDİ**.

### 2.2 Katmanlı seçim — 12 satıcı davet, 10 tamamlama hedefi

Kaynak doküman "en az 10" diyor; **12 davet edilir** çünkü pilotlarda tipik
katılımcı kaybı vardır ve 10'un altına düşmek kriteri düşürür.

| Katman | Kota | Neden bu katman |
|---|---:|---|
| Tekstil | 4 | Ölçülen katalogda ağırlıklı kategori (ÖLÇÜLECEK — §2.1 sorgusu) |
| Elektronik | 3 | Görsel standardı en sıkı kategori (beyaz zemin, çoklu açı) |
| Mobilya | 3 | En büyük dosyalar; piksel tavanı ve oran ihlalleri burada yoğun |
| Diğer | 2 | Kategori dışı davranışı yakalamak için |
| **Toplam** | **12** | |

**Teknik yetkinlik çaprazı** (her katmanda en az bir tane olacak şekilde):

| Seviye | Tanım (ölçülebilir) | Hedef |
|---|---|---|
| Düşük | Son 90 günde panele < 5 giriş; görsel düzenleme aracı kullanmıyor | ≥ 4 |
| Orta | Haftalık giriş; telefonla çekip doğrudan yüklüyor | ≥ 5 |
| Yüksek | Görselleri hazırlayıp yüklüyor (Photoshop/Canva); oran biliyor | ≥ 3 |

**Dışlama:** İstoç personeli, demo hesaplar (`seed_demo_data.py` ile üretilen
18 `data:` URI logolu hesap — `docs/reports/08-canli-olcum.md` §2.1) pilota
**alınmaz**; bunlar gerçek satıcı davranışı üretmez.

### 2.3 Onam ve KVKK

- Ekran kaydı ve konuşma kaydı **yalnız açık onamla**. Onam metni ayrı
  saklanır; katılımcı adı bulgu raporunda **geçmez** (katılımcı kodu: `S01`…`S12`).
- Pilot **gerçek mağaza verisiyle** yapılır; test görselleri satıcının kendi
  ürünleridir. Yüklenen her dosya pilottan sonra satıcının kontrolündedir,
  silinmez.
- Telemetri olayları kişi bazında değil **katılımcı kodu** bazında toplanır.

---

## 3. Görev seti ve başarı ölçütü

Her görev için: ne isteniyor, "tamamlandı" ne demek, nasıl ölçülüyor.

| # | Görev | "Tamamlandı" tanımı (ikili) | Ölçüm | Dalga |
|---|---|---|---|---|
| G1 | 5 ürün görseli yükle | 5 dosyanın 5'i `File` kaydı olarak yazıldı ve üründe görünüyor | Sunucu kaydı (telemetri değil) | UAT-1 |
| G2 | Kırpma + odak ayarla (1 ürün) | `Media Crop Intent` kaydı yazıldı ve `focal_x/focal_y` varsayılandan farklı | DB | UAT-2 |
| G3 | Önizlemeleri incele ve onayla | En az 3 cihaz sınıfı önizlendi, sonra onay | Telemetri (`preview_viewed`, `approved`) | UAT-2 |
| G4 | Logo yükle | Logo alanı dolu, dosya diskte | DB | UAT-1 |
| G5 | Kapak videosu yükle | Video `ready` durumuna geçti (transcode dahil) | `th_video_status` | UAT-1 |
| G6 | Bilerek küçük görsel yükle → hata mesajını oku → **düzelt** | Ret aldı **ve** ardından kuralı karşılayan bir dosya yükledi | Sunucu + §6 anlama sorusu | UAT-2 |

**Ölçülecek üç sayı (her görev için):**

1. **Tamamlama oranı** = tamamlayan katılımcı / katılımcı.
2. **Süre** = ilk etkileşimden tamamlanmaya kadar (medyan; ortalama değil —
   n=10'da tek bir uzun kuyruk ortalamayı bozar).
3. **Yardım isteme sayısı** = moderatöre yöneltilen soru adedi.

**Eşik yok — bilinçli.** Kaynak doküman G1–G5 için sayısal bir kapı koymuyor;
uydurulmuş bir "%80 tamamlama" eşiği yazmak, ölçüm öncesi karar vermek olurdu.
Tek sayısal kapı **G6'nın anlama oranıdır** (§6) ve o kaynak dokümanda yazılı.

---

## 4. Ölçüm aygıtı

### 4.1 Oturum düzeni

| Parametre | Değer | Gerekçe |
|---|---|---|
| Süre | 60 dk / katılımcı | 6 görev + anlama soruları + serbest yorum |
| Kip | Uzaktan, ekran paylaşımlı, moderatörlü | İstoç satıcıları coğrafi olarak dağınık; ayrıca ekran kaydı kolay |
| Moderatör müdahalesi | **Yalnız 3 dakika takıldıktan sonra** | Takılma noktası ölçülecek şey; erken yardım veriyi siler |
| Düşünce sesli (think-aloud) | Evet | Karışıklık noktası tamamlama oranından daha bilgilendirici |

### 4.2 Kaydedilen ham veri

| Alan | Kaynak | Not |
|---|---|---|
| Görev başlangıç/bitiş damgası | Moderatör formu | Saat dilimli ISO-8601; analiz aracı negatif/eksik süreyi reddeder |
| Yardım isteme | Moderatör notu | |
| Terk (görevden vazgeçme) | Moderatör formu | `completed=0`; bitiş yine kaydedilir |
| Ret kodu ve mesajı | Sunucu yanıtı (`code` alanı) | `tradehub_core/media/pipeline/core/errors.py` kod kataloğu |
| Anlama cevabı | §6 protokolü | Sözlü, kayıttan çözümlenir |

Kanonik boş şablonlar `docs/templates/media-uat-results.csv` ve
`docs/templates/media-uat-findings.csv`; oturum akışı
`docs/templates/media-uat-oturum-formu.md` içindedir. Çevrimdışı analiz:

```bash
python3 scripts/summarize_media_uat.py media-uat-results.csv media-uat-findings.csv --check-gate
```

Araç şemayı, takma katılımcı kodunu, açık rıza işaretini, saat dilimli süreleri,
kanıt bağlantılarını ve bulgu sahip/tarihlerini doğrular; görev bazında tamamlama,
medyan süre, yardım/karışıklık sayısı, tam-anlama oranı ve Wilson %95 aralığını
üretir.

---

## 5. Ürün telemetrisi — opsiyonel ve mahremiyet onayına bağlı

Panelde bugün ürün analitiği var; **medya akışı için olay yok** (kod
taramasıyla doğrulanmalı — §9-D1). T-142'nin ölçümleri §4'teki anonim,
moderatörlü form + sunucu/DB kanıtıyla alınabildiği için bu eksik pilotu teknik
olarak bloke etmez. Gelecekte mahremiyet/retention onayı verilirse önerilen olay
seti şudur:

| Olay | Ne zaman | Taşıdığı alanlar |
|---|---|---|
| `media_upload_started` | Dosya seçildiğinde | `slot_key`, `bytes`, `participant` |
| `media_upload_rejected` | Sunucu ret döndüğünde | `code`, `slot_key` |
| `media_upload_succeeded` | Varlık yazıldığında | `asset`, `slot_key`, `seconds` |
| `crop_opened` / `crop_saved` | Crop Studio | `asset`, `method` |
| `preview_viewed` | Cihaz sekmesi değiştiğinde | `asset`, `device_class` |
| `step_abandoned` | Ekran terk edildiğinde | `step`, `seconds_on_step` |

> **Bu olaylar YAZILMADI.** Açık ürün davranışı takibi, kullanıcı rızası,
> saklama süresi ve erişim modeli belirlenmeden eklenmez. Pilot, saat dilimli
> moderatör kaydı ve tamamlanan her görev için zorunlu `evidence_ref` ile koşar;
> ikinci gözlemci/oturum kaydı kullanılacaksa ayrıca açık rıza alınır.

---

## 6. Anlama oranı ≥ %90 — protokol ve İSTATİSTİKSEL DÜRÜSTLÜK

### 6.1 Protokol

G6'dan hemen sonra, moderatör hata mesajını **ekrandan kaldırır** ve tek soru
sorar:

> "Bu yükleme neden kabul edilmedi ve şimdi ne yapmanız gerekiyor?"

**Puanlama (iki bağımsız değerlendirici, anlaşmazlıkta üçüncü):**

| Puan | Ölçüt |
|---|---|
| **1 — anladı** | Hem sebebi (çözünürlük yetersiz) hem eylemi (daha büyük görsel yükle / yeniden çek) doğru söyledi |
| **0,5 — yarım** | Sebebi söyledi ama ne yapacağını bilmiyor **veya** tersi |
| **0 — anlamadı** | Yanlış sebep, "bilmiyorum", ya da mesajı okumadan tekrar aynı dosyayı yükledi |

Anlama oranı = puan toplamı / katılımcı sayısı. **Kapı: ≥ %90.**

### 6.2 ⚠ n=10 ile %90 ölçülemez — bu kapının gerçek belirsizliği

Kaynak doküman "≥ %90" diyor ve "en az 10 satıcı" diyor. İkisi birlikte
**istatistiksel olarak yetersizdir** ve bu, planın gizlemediği bir sınırdır.
Wilson %95 güven aralığı (bu makinede hesaplandı):

| Gözlenen | Nokta tahmini | %95 güven aralığı |
|---|---:|---|
| **9/10** | %90,0 | **%59,6 – %98,2** |
| 18/20 | %90,0 | %69,9 – %97,2 |
| 27/30 | %90,0 | %74,4 – %96,5 |
| 45/50 | %90,0 | %78,6 – %95,7 |
| 9/11 | %81,8 | %52,3 – %94,9 |

Okunuşu: **10 kişiyle "9 kişi anladı" sonucu, gerçek anlama oranının %60
olmasıyla da uyumludur.** Yani n=10'da bu kapı "geçti" dendiğinde kanıt
gücü düşüktür.

**Karar (plan tarafından, ölçüm öncesi):**

1. Kapı **korunur** — kriter gevşetilmez, ≥ %90 aynen kalır.
2. Kapıya **ikinci bir koşul** eklenir: **hiçbir katılımcı 0 puan almamalı.**
   n=10'da tek bir "hiç anlamadı" vakası, oran %90 çıksa bile mesajın
   yeniden yazılmasını tetikler. Gerekçe: 0 puanlı bir katılımcı, güven
   aralığının alt ucunun gerçek olduğunun işaretidir.
3. Kapı sonucu rapora **güven aralığıyla birlikte** yazılır. "%90 sağlandı"
   cümlesi tek başına **yasaktır**.
4. Ölçüm gücünü artırmak isteyen ekip için hedef: **n ≥ 30** (aralık genişliği
   yarıya iner). Bu bir öneridir, kaynak dokümanın kriteri değildir.

### 6.3 Mesaj kalitesinin ikinci ölçütü — davranış

Anlama sorusundan bağımsız, **davranışsal** ölçüt de kaydedilir:

> Ret aldıktan sonra **ilk denemede** kuralı karşılayan bir dosya yükleyen
> katılımcı oranı.

Bu ölçüt sözlü cevaptan daha güvenilirdir (kişi anladığını sanabilir).
Eşiği **YOK** — ilk pilotta taban çizgisi olarak ölçülür.

---

## 7. Bulgu yönetimi

### 7.1 Şiddet tanımı — tahmine bırakılmaz

| Şiddet | Tanım | Örnek |
|---|---|---|
| **Kritik** | Satıcı görevi **tamamlayamıyor** ya da veri kaybı / yanlış veri yazılıyor | Yükleme sessizce başarısız oluyor; kırpma yanlış kaydediliyor |
| **Yüksek** | Görev tamamlanıyor ama ≥ 3 katılımcı yardım almadan yapamadı | Hata mesajı ne yapılacağını söylemiyor |
| **Orta** | Görev tamamlanıyor, tek katılımcı takıldı, çözüm bulunabiliyor | Buton etiketi yanıltıcı |
| **Düşük** | Estetik / tercih | Renk, boşluk |

### 7.2 Bulgu kaydı zorunlu alanları

`şiddet · başlık · adım · katılımcı kodları · kanıt (kayıt zaman damgası) ·
öneri · sahip · hedef tarih · azaltım`

Sahip ve hedef tarih **boş bırakılamaz**; boş bırakılan bulgu "kapatılmamış"
sayılır.

### 7.3 Kapanış kuralı

- **Kritik bulgular go-live ÖNCESİ kapanır** (T-144 kontrol listesinde kapı).
- Yüksek bulgular go-live'ın **%50 aşamasından önce** kapanır.
- Orta/düşük bulgular backlog'a düşer, tarih verilir.

---

## 8. Pilotun çıkış kapısı

UAT "bitti" denmesi için hepsi gereklidir:

- [ ] ≥ 10 satıcı, her biri ≥ 5 ürün ile katıldı (G1 tamamlandı)
- [ ] Her görev için tamamlama oranı ve medyan süre **ölçüldü ve yazıldı**
- [ ] Anlama oranı ölçüldü, **güven aralığıyla birlikte** raporlandı (§6.2)
- [ ] Hiçbir katılımcı anlama testinde 0 puan almadı (§6.2 madde 2)
- [ ] Kritik bulguların tamamı kapandı; her birinin kanıtı var
- [ ] Bütün oturum satırlarında saat dilimli süre + kanıt var ve
      `summarize_media_uat.py --check-gate` sıfırla döndü

**Bugün bu listedeki hiçbir kutu işaretlenemez** — pilot koşulmadı.

---

## 9. ÜRETİMDE / PİLOT ÖNCESİ DOĞRULANMALI

### D1 — Medya telemetrisi gerçekten var mı

```bash
grep -rn "media_upload\|crop_saved\|preview_viewed" \
  /Users/ahmet/Desktop/istoc/admin-panel/frontend/src \
  /Users/ahmet/Desktop/istoc/tradehubfront/src | wc -l
# Beklenen bugün: 0. Ürün takibi ancak §5 mahremiyet/retention kararıyla eklenir.
```

### D2 — Satıcı × ürün × medya dağılımı (§2.1 örneklem çerçevesi)

```bash
docker exec -i istoc-dev-backend-1 bench --site istoc.localhost console <<'EOF'
import frappe
rows = frappe.db.sql("""
  select p.name store, count(distinct l.name) urun
  from `tabAdmin Seller Profile` p
  left join `tabListing` l on l.seller = p.name
  group by p.name having urun >= 5 order by urun desc
""", as_dict=True)
print("≥5 ürünü olan satıcı:", len(rows))
for r in rows[:20]: print(" ", r["store"], r["urun"])
EOF
```

`≥5 ürünü olan satıcı < 12` çıkarsa katman kotaları (§2.2) yeniden dağıtılır;
kriterin kendisi (≥10 satıcı) düşürülmez.

### D3 — G6 üretimde tetiklenebiliyor mu

```bash
# 999 px kısa kenarlı bir görsel product.image slotunda REDDEDİLİYOR mu?
# Beklenen: short_edge_too_small veya area_too_small kodlu ret.
docker exec -i istoc-dev-backend-1 bench --site istoc.localhost console <<'EOF'
from tradehub_core.media import upload_policy
import inspect
print(inspect.signature(upload_policy.check))
EOF
```

İmzada `slot` parametresi bulunmalı; ayrıca pilot öncesi gerçek panelden küçük
fixture yüklenerek görünen mesaj ve ardından geçerli dosyayla düzeltme yolu
doğrulanmalıdır. Otomatik ret, kullanıcının mesajı anladığına kanıt değildir.

---

## 10. Kaynaklar

- Kaynak tasarım dokümanı: `docs/72-faz14-test-kabul.html` → T-142
- `docs/reports/08-canli-olcum.md` — 4.958 dosya, sahiplik %100
- `docs/reports/03-performans-taban-cizgisi.md` — teknik taban çizgisi
- `docs/templates/media-uat-oturum-formu.md`, `media-uat-results.csv`,
  `media-uat-findings.csv` ve `scripts/summarize_media_uat.py` — anonim saha
  kaydı, sözleşme doğrulaması ve kabul hesabı
- `docs/ui/faz9-media-library.md`, `faz10-crop-studio.md`, `faz11-simulator.md`
  — uygulanmış arayüzlerin tasarım/kabul kaynakları
- `docs/srs/SRS-v1.0.md` FR-001, FR-015, FR-062, FR-063 — G6'nın bağlı olduğu
  gereksinimler
