# ADR-0009 — Türevler için `File` kaydı açılmaz

**Durum:** Kabul edildi · yürürlükte · **K7 bağlantısı ADR-0022 ile çözüldü**
**Tarih:** karar `docs/sad/SAD-v1.0.md` (S-04) · doğrulama 2026-08-19
**İlgili:** ADR-0001, ADR-0002, ADR-0014

---

## Bağlam

Türev merdiveni bir kaynaktan onlarca dosya üretiyor (T-124 ölçümü: 7 görsel →
**84 türev**). Bu dosyaların Frappe'nin `File` DocType'ında karşılığı olmalı mı?

İki somut risk vardı:

1. **Kota.** `entitlement.checks.check_media_storage_quota` (hooks.py:258) bugün
   her `File` kaydını sayıyor. Türevler `File` olursa satıcının kotası fiilen
   bölünür.
2. **Özyineleme.** Kanca `File.after_insert` üzerinde. Türev bir `File` açarsa
   kanca kendi kendini tetikler.

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — Her türev bir `File` kaydı açsın | Envanter, izin ve GC mekanizmaları türevleri "bedava" görür. Bedeli: kota şişer, `after_insert` özyinelenir, `File` tablosu ~10 kat büyür. |
| **B (SEÇİLEN)** — Türev diske yazılır, `File` kaydı açılmaz; muhasebesi `Media Rendition` satırında tutulur | Özyineleme ve File tablosu büyümesi çözülür. Kota ADR-0022 uyarınca ledger baytını ayrı sayaçtan toplar. |
| C — Ayrı bir hafif `File` alt tipi | Frappe'de böyle bir kavram yok; `File`'a alan eklemek bütün mekanizmaları etkiler. |

## Karar

`media/pipeline_bridge.py:16-19`:

> Ürettiği türevler için `File` kaydı **AÇILMAZ** (bkz. `_write_rendition_file`)
> — hem envanteri/kotayı şişirmesin hem de `after_insert` kancası kendi kendini
> tetikleyip sonsuz döngü kurmasın diye.

Türev dosyası diske ADR-0001'in içerik-adresli adlandırmasıyla yazılır; kaydı
`Media Rendition` satırıdır (`file_url`, `bytes`, `width/height/format`, `ssim`,
`benefit_gate_passed`).

## Gerekçe

- SAD'ın gerekçesi (kota şişmesi) doğrulandı; koda **ikinci bir gerekçe**
  (özyineleme) eklendi.
- Aynı yaklaşım depoda zaten vardı: görsel arşivi `ARCHIVE_DIRNAME` deseniyle
  "envanteri ve kotayı şişirmesin" diye `File` açmıyor (`presets.py:33-35`).
- Doğrulama ölçüldü: `media/pipeline_bridge.py` içinde `File` dokümanı açan
  **hiçbir** çağrı yok — `new_doc("File")`, `save_file`,
  `get_doc({"doctype": "File"})` için **sıfır eşleşme**
  (`docs/reports/21-t030-mimari-inceleme.md` M-06 ✅).

## Sonuçlar

### Olumlu

- `File` tablosu şişmedi, kanca özyinelenmedi; kota gerçek türev baytını
  ledger'dan ayrıca sayıyor (ADR-0022).
- T-124 geri alma testinde 84 türev dosyası silindiğinde `File` sayısı **5014
  (değişmedi)** — iki muhasebenin ayrık olduğu ölçüldü (`DALGA-A-DEVIR.md`).

### K7 kota bağlantısı — ADR-0022 ile çözüldü

**1. Kota kararı (K7) artık uygulanıyor.**
`docs/standards/company-cover-video.md` §10.9'da platform yöneticisi **K7'yi
"rendition'lar kotadan SAYILSIN"** diye karara bağladı — belgedeki önerinin
**tersi**. ADR-0022 seçenek D bu bağı kurdu: `storage_usage(store)` public
orijinal baytlarına `Media Rendition.bytes → Media Asset.owner_seller`
toplamını ekliyor. Türev hâlâ `File` açmıyor; kota iki sayaçtan tek bayt toplamı
üretiyor.

K7'nin ölçülmüş çarpanı (`docs/reports/18-faz7-kapanis.md`, 3 gerçek kapak videosu):

| Ne | İlk iddia | ÖLÇÜLEN |
|---|---|---|
| Nesne sayısı | 6× | **6×** (doğru) |
| **Bayt** çarpanı | ~6× | **2,85× · 3,13× · 4,56×** → operatif ~**3** |
| "tipik 30 sn ≈ 19 MB" | 19 MB | **4,95–8,80 MB** |

HLS fiziksel segment adediyle tahmin edilmez; `Media Rendition.bytes` HLS
paketinin ilan edilen toplamını taşır. Kota nesne sayısını değil bu gerçek
ledger baytını kullanır. Güncel sözleşme `tenant-media-quota.md` içindedir.

**2. Türevler `File` tabanlı GC ve envanterin dışında.** Saklama/GC işleri
(`media/pipeline/storage/retention.py`) ve `usage.py` referans zinciri `File`
üzerinden çalışıyor. Türev temizliği ayrı bir yol gerektiriyor ve
`regenerate_on_demand=True` varsayımı bugün **tutulamayan bir söz**:
`Media Rendition.generation` alanında `lazy` seçeneği tanımlı ama onu yazan kod
yok (`docs/reports/26-t053-saklama-gc.md` §6).

**3. Doğrulanmadı:** türevlerin diskte biriktiğini fark edecek bir izleme yok;
T-124'te elle silindiler.

## Geri dönüş yolu

Kota, yasal saklama veya sahiplik sorguları rendition ledger'ıyla güvenilir
çözülemezse türevler için ayrı kayıt modeli değerlendirilir; mevcut `File`
tablosuna toplu satır açılmaz. Ledger migration'ı eksik sayım üretirse kota
bayrağı kapatılır ve önceki “orijinaller sayılır” davranışına dönülür.
