# ADR-0016 — Slot politikası VERİdir, kod değil

**Durum:** Kabul edildi · yürürlükte · **makine olarak doğrulanıyor**
**Tarih:** Faz 2/3 (`policy/engine.py`) · Faz 6'da profil matrisine genişletildi (T-063)
**İlgili:** ADR-0004, ADR-0005, ADR-0006, ADR-0012

---

## Bağlam

Sunucu bugün bir yüklemenin **hangi slota** ait olduğunu bilmiyor:
`media/upload_policy.py:306-312` `check()` imzasında slot parametresi yok
(`docs/reports/00-upload-slot-envanteri.md` §7-B B1). Sonuç canlıda ölçüldü:
`product.image` yüklemelerinin **%48,6'sı**, `document.attachment`
yüklemelerinin **%91,8'i** slot politikasına uymuyor.

Slot başına kural kümesi (kabul edilen biçimler, oran bandı, bayt tavanları,
hedef SSIM, türev profilleri, bağlanma noktaları) 9 slot için tanımlanacaktı.
Bu kurallar nerede yaşamalı?

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — Python sabitleri / `if slot == "product.image": …` | En hızlı yazım. Bedeli: her yeni slot, her yeni eşik bir kod değişikliği ve bir deploy; kuralı okumak için kod okumak gerekir. |
| **B (SEÇİLEN)** — Kurallar JSON şemasıyla `policy/slots/*.json` içinde **veri**; kod yalnız şemayı yorumlar | Yeni slot = yeni dosya. Kural belgeyle aynı yerde. Bedeli: şema disiplini, ve politika ile üretim arasına bir `bench migrate` girmesi. |
| C — Kurallar DocType'ta (DB) | Operatör düzenleyebilir. Bedeli: sürümlenmez, gözden geçirilemez, test edilemez; ortamlar arası sapma. |

## Karar

`media/pipeline/policy/engine.py` başlığındaki **tasarım sözü**:

> Yeni bir slot eklemek `policy/slots/` altına bir JSON dosyası koymaktır.
> **BU DOSYA DEĞİŞMEZ.** Kod yalnız şemada olmayan YENİ BİR KISIT TÜRÜ eklenirken
> değişir; yeni bir slot, yeni bir eşik, yeni bir oran, yeni bir mesaj kod
> değişikliği gerektirmez.

Kural bütün katmanlarda tekrarlandı:

- **Profil matrisi** — `image/render.py` başlığı: *"Matris KOD DEĞİL VERİDİR —
  genişlikler, biçimler, kalite ve `fit` değerleri `policy/slots/*.json`'dan
  okunur. Yeni bir genişlik eklemek bu dosyayı değiştirmez."*
- **Hedef SSIM** — koda gömülmez, politikadan okunur (`quality/ssim.py:409`
  `target_for`); politika `quality.metric = "bit_exact"` diyorsa o slotta SSIM
  **aranmaz** (`ssim.py:88`, `:412`).
- **Bağlanma noktaları** — (doctype, alan) → `slot_key` haritası kodda **sabit
  değil**: `bound_to` blokları okunur (`media/pipeline_bridge.py:34`, `:272-287`).
  Yeni bir bağlanma noktası eklemek köprüyü değiştirmez.
- **Video karar tablosu** — eşikler, hedefler ve hatta gerekçeler
  `policy/video_decision.json` içinde (bkz. ADR-0011: karar metni verinin
  içinde yaşıyor).

## Gerekçe

- **Makine olarak doğrulanıyor.** `test_policy_engine.py`, `slots/` altındaki her
  JSON'un motorda **o slota özel tek bir `if` olmadan** değerlendirilebildiğini
  kontrol ediyor. Yani kural bir niyet beyanı değil, bir test.
- Kural ile belge aynı yerde durunca ADR-0012 ve ADR-0013'teki gibi ölçüm
  sonuçları doğrudan politikaya işlenebiliyor (`w384` eklemek bir JSON satırı).
- Mevcut motor yeniden yazılmadı: `upload_policy.check()` platform tabanı olarak
  **kalıyor**, `PolicyEngine` onun **üstüne** slot katmanı koyuyor; iki kapıdan
  ikisi de geçilmeli. `gates.check_before()` farklı soruya cevap veriyor,
  çakışma yok.

## Sonuçlar

### Olumlu

- 9 slot dosyası, 0 slot-özel `if`.
- Ölçümle gelen değişiklikler koda dokunmadan yürürlüğe girdi (ADR-0012 K3,
  ADR-0013 K1).
- Politikanın kendisi gözden geçirilebilir, sürümlenebilir ve diff'lenebilir.

### Olumsuz — ölçüldü

- **Politikayı okuyan tek kapı yok: üç okuyucu var**
  (`docs/reports/21-t030-mimari-inceleme.md` M-11, Orta). Aynı JSON'u üç yerden
  okumak, üç farklı yorum riski demektir.
- **Politika ile üretim arasında bir `bench migrate` var** (aynı rapor M-12):
  JSON'u değiştirmek yetmiyor, `Media Profile` tohumlaması yeniden koşmalı. "Kod
  değişmez" sözü doğru ama "deploy gerekmez" sözü **değil**.
- **Taslak politikanın karar üzerindeki etkisi tanımsız** (aynı rapor M-14,
  **BLOKLAYICI**): bugün **0/9 politika `active`**
  (`docs/reports/16-t029-politika-aktivasyonu.md` §0). Yani veri olarak duran
  kuralların hiçbiri "yürürlükte" işaretli değil ve motorun taslak bir politikayı
  nasıl ele alacağı yazılı değil.
- `PolicyEngine` adı kodda **iki farklı ve uyumsuz şeye** takılı (aynı rapor
  M-02, **BLOKLAYICI**).
