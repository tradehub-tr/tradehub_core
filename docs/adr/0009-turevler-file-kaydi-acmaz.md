# ADR-0009 — Türevler için `File` kaydı açılmaz

**Durum:** Kabul edildi · yürürlükte · **kota kararıyla (K7) çelişiyor**
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
| **B (SEÇİLEN)** — Türev diske yazılır, `File` kaydı açılmaz; muhasebesi `Media Rendition` satırında tutulur | Kota ve özyineleme çözülür. Bedeli: türevler `File` tabanlı hiçbir mekanizmanın (kota, envanter, GC, izin) görüş alanında değil. |
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

- Kota şişmedi, kanca özyinelenmedi.
- T-124 geri alma testinde 84 türev dosyası silindiğinde `File` sayısı **5014
  (değişmedi)** — iki muhasebenin ayrık olduğu ölçüldü (`DALGA-A-DEVIR.md`).

### Olumsuz — ve yürürlükteki başka bir kararla çelişiyor

**1. Kota kararı (K7) bu kararla bugün uygulanamaz.**
`docs/standards/company-cover-video.md` §10.9'da platform yöneticisi **K7'yi
"rendition'lar kotadan SAYILSIN"** diye karara bağladı — belgedeki önerinin
**tersi**. Ama kota kapısı `File` üzerinden bayt sayıyor
(`entitlement/checks.py:272` ← `media/files.py:267 storage_usage`) ve türevlerin
`File` kaydı yok. Karar yürürlüğe girdiğinde bu bağlantı ayrıca kurulmalı.

K7'nin ölçülmüş çarpanı (`docs/reports/18-faz7-kapanis.md`, 3 gerçek kapak videosu):

| Ne | İlk iddia | ÖLÇÜLEN |
|---|---|---|
| Nesne sayısı | 6× | **6×** (doğru) |
| **Bayt** çarpanı | ~6× | **2,85× · 3,13× · 4,56×** → operatif ~**3** |
| "tipik 30 sn ≈ 19 MB" | 19 MB | **4,95–8,80 MB** |

Ayrıca **6 nesne modeli HLS'i hiç saymıyor**: HLS gereken tek dosya **409 nesne /
+27,3 MB** üretti. `docs/standards/kota.md` bu karara göre güncellenmeli — bu iş
**yapılmadı**.

**2. Türevler `File` tabanlı GC ve envanterin dışında.** Saklama/GC işleri
(`media/pipeline/storage/retention.py`) ve `usage.py` referans zinciri `File`
üzerinden çalışıyor. Türev temizliği ayrı bir yol gerektiriyor ve
`regenerate_on_demand=True` varsayımı bugün **tutulamayan bir söz**:
`Media Rendition.generation` alanında `lazy` seçeneği tanımlı ama onu yazan kod
yok (`docs/reports/26-t053-saklama-gc.md` §6).

**3. Doğrulanmadı:** türevlerin diskte biriktiğini fark edecek bir izleme yok;
T-124'te elle silindiler.
