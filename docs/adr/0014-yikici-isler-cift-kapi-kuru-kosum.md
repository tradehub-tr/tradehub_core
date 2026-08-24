# ADR-0014 — Yıkıcı işler varsayılan kuru koşum ve iki bağımsız kapı arkasında

**Durum:** Kabul edildi · yürürlükte · ölçümle doğrulandı
**Tarih:** 2026-08-19 (T-053)
**İlgili:** ADR-0002 (aynı emniyet deseninin yükleme yolundaki hâli), ADR-0009

---

## Bağlam

Saklama (retention) ve çöp toplama (GC) işleri dosya **siler**. `hooks.py`'ye
günlük zamanlanmış bir iş olarak bağlanacaklardı. Yanlış konfigüre edilmiş bir
GC, çalışan bir pazaryerinde geri alınamaz veri kaybı demektir.

Depoda bunun bir emsali de var: kota/erişim kararlarının retroaktif olmaması
(`_is_protected_pii`) sessiz bir sızıntı üretmişti; sessiz davranışların bedeli
ölçülmüştü.

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — İşi doğrudan ıslak (silen) modda bağla | Politika hemen uygulanır. Bedeli: yanlış politika = geri alınamaz kayıp; hiçbir prova yok. |
| **B (SEÇİLEN)** — Varsayılan **kuru koşum**; ıslak koşum **iki bağımsız kapıya** bağlı: `site_config` bayrağı **ve** politikanın `keep_forever=false` yapılması | Prova gerçek veriyle yapılır, hiçbir şey silinmez. Bedeli: iki ayrı yerde ayar; "neden silmiyor" sorusu iki yere bakmayı gerektirir. |
| C — Tek kapı (yalnız bayrak) | Basit. Bedeli: bayrak yanlışlıkla açılırsa politika varsayılanları neyi silecekse siler. |

## Karar

`media/pipeline/storage/retention.py` işleri `hooks.py`'ye günlük olarak
kaydedildi (`hooks.py:160` →
`tradehub_core.media.pipeline.storage.retention.run_scheduled_gc`), ve
`hooks.py:154` yorumu kuralı yazıyor: *"site_config'te
`media_retention_gc_enforce` = 1 yapılmadıkça hiçbir …"*.

`retention.py` **yeniden yazılmadı**; içindeki politika modeli
(`OriginalRetention`, `DerivativeRetention`, `RetentionPolicy`) korundu.
`hooks.py` değişikliği **yalnız ekleme, 0 silme**.

## Gerekçe ve doğrulama — ölçüldü

`docs/reports/26-t053-saklama-gc.md` §0:

| Kanıt | Sonuç |
|---|---|
| Kuru koşum hiçbir şey silmiyor | `File` 5014 → **5014**, disk 1.153.218.661 → **1.153.218.661 bayt** (fark **0**) |
| Kuru koşum boşuna değil | Agresif politikayla **4.429 aday, 1,44 GB** üretti — "hiç çalışmadı" ile karışmıyor |
| Legal hold koruyor | `legal_hold=1` → `blocked/legal_hold`; `legal_hold=0` → `delete` (**tek değişken bu**) |
| Eksik dosya dayanıklılığı | Diskte karşılığı olmayan **10** `File` kaydı → `missing_on_disk` ile atlandı, koşum tamamlandı |
| **Vacuity kanıtı** | Legal hold kontrolü kaldırıldı → **2 test KIRMIZI**; geri kondu → **22 test YEŞİL** |

Vacuity kanıtı bu depoda tekrar eden bir kalite kuralıdır: bir testin gerçekten
bir şey doğruladığı, kontrolü **kaldırıp kırmızıya düşürerek** gösterilir.

## Sonuçlar

### Olumlu

- Politika gerçek veriyle prova edilebiliyor; "ne silinecekti" sorusunun cevabı
  silmeden alınıyor.
- İki kapı bağımsız: bayrak yanlışlıkla açılsa bile politika `keep_forever=true`
  olduğu sürece hiçbir şey silinmez.
- Aynı emniyet deseni yükleme yolunda da uygulandı (ADR-0002) — depoda tutarlı
  bir "varsayılan güvenli" kültürü var.

### Olumsuz / açık

- **`regenerate_on_demand=True` bugün tutulamayan bir söz.**
  `Media Rendition.generation` alanında `lazy` seçeneği tanımlı ama onu **yazan
  kod yok** ve boru hattı bayrağı kapalı. Türev silmeyi bu söze dayandıran bir
  politika, geri gelmeyecek dosyaları siler. Kod artık bunu ölçüp silmeyi
  bildirime düşürüyor (`docs/reports/26-t053-saklama-gc.md` §6).
- `Brand.logo` tuzağı: `usage.py` kararı **`history_only`** (yani silinebilir!).
  GC koruma kümesine alınarak elle telafi edildi — yani `usage.py`'nin sınıflaması
  ile GC'nin davranışı **ayrışıyor**; kalıcı çözüm `usage.py` tarafında.
- İki kapı, yanlış tanı riskini artırıyor: "GC neden çalışmıyor" sorusunun iki
  ayrı cevabı var.
- **Doğrulanmadı:** ıslak koşum üretimde hiç denenmedi; kurtarma provası (T-054)
  yapılmadı.

## Geri dönüş yolu

Silme manifesti, koruma kümesi veya kurtarma provası tek hata verirse ıslak
bayrak kapanır ve yalnız dry-run raporu üretilir. Çift kapı kullanıcı hatası
yaratırsa sadeleştirme ancak eşdeğer iki bağımsız güvenlik sinyali ve başarılı
restore provasıyla değerlendirilir.
