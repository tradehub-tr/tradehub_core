# ADR-0002 — Yeni medya hattı bayrak arkasında, eski hattın YANINDA çalışır

**Durum:** Kabul edildi · yürürlükte (bayraklar bugün **0**)
**Tarih:** 2026-08-18/19 (Dalga A)
**İlgili:** ADR-0014 (yıkıcı işlerde aynı desen), ADR-0009

---

## Bağlam

`tradehub_core/media/pipeline/` altında 71 modülük bir medya motoru yazılmıştı
ama ürüne bağlı değildi. Üretimde hâlâ tek çıktı üretiliyordu:
`media/pipeline.py::to_webp` koşulsuz `thumbnail((1920,1920))` + WebP yazıyor ve
iş bitiyordu. Ölçüm bunun bedelini gösterdi: ürün detay sayfası **13,14 MB**
görsel indiriyor ve 31 render noktasının **0'ında** `srcset` var
(`docs/reports/03-render-envanteri.md`).

Motoru bağlamak, çalışan bir pazaryerinin **yükleme yolunu** değiştirmek demekti:
sipariş, ödeme ve KYB akışlarıyla aynı `File.after_insert` kancasını paylaşan bir
nokta.

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| **A** — Eski hattı yeni hatla değiştir (`to_webp` çağrısını sil) | Tek hat, tek davranış. Ama geri dönüş bir revert gerektirir; bayrak yok, aşamalı açılış yok. Yükleme kırılırsa satıcı ürün ekleyemez. |
| **B (SEÇİLEN)** — Yeni kanca en sona eklenir, **üç kat bayrak** arkasında; eski hat aynen servis etmeye devam eder | Geri dönüş tek kutucuk. Bedeli: iki hat bir süre yan yana yaşar, iki kod yolu bakılır. |
| C — Ayrı bir "shadow" ortamda çalıştır, üretime hiç bağlama | Sıfır risk ama gerçek veriyle hiç ölçüm alınamaz; üretim korpusundaki patolojiler görülmez. |

## Karar

`hooks.py` `doc_events["File"]["after_insert"]` listesine **5. sıraya, en sona**
`tradehub_core.media.pipeline_bridge.maybe_generate_renditions` eklendi. Mevcut
dört kanca (`states`, `audit`, `transcode`, `av`) sırası ve içeriğiyle korundu.

Üç kat kapı, hepsi fail-safe "kapalı" (`media/pipeline_bridge.py` başlığı,
`media/pipeline_flags.py`):

1. `pipeline_flags.is_enabled("rendition_on_upload")` — ana şalter
   (`media_pipeline_enabled`) + alt bayrak. Kapalıysa fonksiyon **ilk satırda**
   döner: ne DB okunur, ne kuyruğa iş girer.
2. Kapsam daraltması — KVKK kapsam dışı doctype'lar ve `document.attachment`
   slotu (KYB/KYC/kimlik belgeleri) **açıkça** hariç.
3. `pipeline_flags.is_slot_enabled(slot_key)` — `active_slots` boşken hiçbir slot
   açık değildir; operatör açtığı slotu tek tek yazar.

İki değişmez kural `pipeline_flags.py` başlığında yazılı:

- **Varsayılan KAPALI.** Ayar okunamıyorsa (DocType migrate edilmedi, DB yok,
  site bağlamı yok, alan adı yanlış) sonuç `False`. Bayrak okuma hatası asla yeni
  kod yolunu açmaz ve çağıranı patlatmaz.
- **Ana şalter her şeyi keser.** `media_pipeline_enabled` kapalıyken alt bayraklar
  ve tüm slotlar `False` döner — kaydedilmiş değerleri ne olursa olsun.

Bayrak değeri istek kapsamında `frappe.local_cache` ile tutulur; **cross-request
önbellek bilinçli olarak kullanılmadı** — bayrağı kapatmanın anında etki etmesi
gerekir.

## Gerekçe

- Ölçülebilir bir "önce/sonra" ancak iki hat aynı sistemde yan yana çalışırken
  alınabilir.
- Geri dönüş maliyeti tek kutucuğa indi; bu, üretim yükleme yoluna dokunmanın ön
  koşuluydu.
- `frappe.client_cache` görev metninde isteniyordu ama bu kurulumdaki Frappe
  **v15.116.1**'de yok (ClientCache v16/develop ile geldi) — v15 karşılığı
  `frappe.local_cache` kullanıldı ve sapma modül başlığına yazıldı.

## Sonuçlar

### Olumlu — ölçüldü

| İddia | Ölçüm | Kaynak |
|---|---|---|
| `hooks.py` bozulmadı | `git diff --stat`: **23 ekleme, 0 silme**; 4 mevcut kanca aynı sırada, yeni kanca 5. sırada (çalışma zamanında da doğrulandı) | `docs/reports/15-dalga-a-dogrulama.md` §5 |
| Bayrak kapalıyken sistem birebir aynı | Gerçek `File` insert: `Media Asset` 0→0, `Rendition` 0→0, `Processing Job` 0→0, kuyruk `long` 0→0; mevcut hat (`states.py`) çalışmaya devam etti | aynı §4c |
| Geri alma çalışıyor | T-124 pilotundan sonra: bayraklar 0, Asset/Rendition/Job 0, 84 türev dosyası silindi, diskte `.avif` 0, `File` 5014 (değişmedi) | `DALGA-A-DEVIR.md` T-124 |
| Bayrak açılınca gerçekten kazandırıyor | En ağır ürün sayfası `LST-00560`: 9,99 MB → **0,186 MB (%98,1)**; en pesimist senaryoda bile %93,8 ve <2 MB kabul kriteri geçiyor | aynı |

### Olumsuz

- **Bayrak kapalıyken bile istek başına 1 `Media Engine Settings` okuması var.**
  `hooks.py`'nin eski yorumu "DB'ye sorgu gitmez" diyordu; yanlıştı, düzeltildi
  (`DALGA-A-DEVIR.md` K-4). Davranış güvenli, maliyet sıfır değil.
- Manifest ucu bayrak kapalıyken hâlâ **2 sorgu** atıyor. Sıfıra indirmek
  kapalı-gövde sözleşmesini (`fallback` + `images`) değiştirmeyi gerektiriyor —
  bilinçli olarak kapsam dışı bırakıldı (`DALGA-A-DEVIR.md` "Bilinen kalan kısıtlar").
- İki hat bir süre yan yana yaşayacak: `engine.to_webp` ve `pipeline.image.render`
  aynı anda bakılır. Eski hattın ne zaman kaldırılacağı **karara bağlanmadı**.
- Bayrak katmanı ve tasarlanmış iki tek-nokta **SAD'da yok**
  (`docs/reports/21-t030-mimari-inceleme.md` M-13, "Yüksek").

## Geri dönüş yolu

Yeni hatta hata/latency bütçesi aşılırsa üç medya bayrağı 0'a çekilir; eski hat
kod değişmeden hizmet verir. Eski hat ancak dalga başına hata oranı, p95 ve
manifest paritesi kabul kapılarını geçen bir gözlem penceresinden sonra
kaldırılır; bu kanıt yoksa paralel çalışma kararı yeniden açılır.
