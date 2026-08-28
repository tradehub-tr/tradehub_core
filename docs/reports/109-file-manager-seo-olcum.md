# 109 — Dosya Yöneticisi SEO: denetim kuralları + ölçüm (Task 6)

**Tarih:** 2026-08-27
**Ortam:** `istoc-dev-backend-1`, site `istoc.localhost` (yerel dev).
**Kapsam:** 2026-08-27 Dosya Yöneticisi SEO görev setinin (Task 1-6) SON
dilimi — `seo_audit.py`'ye 3 yeni denetim kuralı (`missing_doc_title`,
`missing_doc_text`, `missing_doc_language`) + bu kuralların/pipeline'ın
gerçek envanter ölçümü. Sayfa bazlı SEO skoru bu dilimin kapsamı dışında.

Yöntem (rapor 106/107/108 ile aynı kısıt): `docker cp` ile konteynere
taşınan tek seferlik script, `bench --site istoc.localhost console` içine
`exec(open('/tmp/measure_109.py').read())` ile beslendi (çok satırlı
döngüler console stdin pipe'ında bozulduğu için).

---

## 1. Uygulanan kural

`tradehub_core/media/seo_audit.py::_doc_bulgulari` — `_watch_slug_bulgusu`
(video) deseninin doküman kardeşi, **yalnız `audit_file`'ın (tekil, `deep=True`)
gövdesinde** çağrılır; `audit_batch`'e (toplu yol) bilerek EKLENMEDİ — aynı
maliyet gerekçesi (`_document_listings` iki toplu sorgu açıyor, N dosya için
toplu tarafta tekrarlamak pahalı olurdu).

Koşul (ikisi birden gerekli):
1. Uzantı `doc_meta.DOC_UZANTILAR` içinde (`.pdf/.docx/.xlsx/.pptx`).
2. En az bir `Listing Document` ile **vitrinde görünen** bir ilana bağlı
   (`media_public._document_listings` — import edildi, yeniden yazılmadı).

Üç kural:

| Kod | Boyut | Koşul |
|---|---|---|
| `missing_doc_title` | metadata | `alanlar["title"]` boş |
| `missing_doc_text` | discoverability | `alanlar["extracted_text"]` boş |
| `missing_doc_language` | metadata | Bağlı `Listing Document` satırlarından HERHANGİ birinin `language`'ı boş |

`missing_doc_text` KASITLI OLARAK `page_count`'a bakmıyor: `doc_meta.apply`
başarısız çıkarımda `-1` yazıyor ama `fields_for` bunu dışa `max(0,...)` ile
kırpıyor — "çıkarım hiç denenmedi/başarısız" ile "gerçekten sıfır sayfa"
dışarıdan ayırt edilemiyor, ikisinde de WARN doğru (taranmış/taranamayan
içerik arama motoruna hiçbir şey söylemiyor — mesaj bu iki olası kökü de
taşıyor: "taranamaz/boş içerik olabilir, OCR gerekebilir").

`missing_doc_language` basit kural: dosya birden fazla ilana bağlıysa
hangi satırın boş olduğunu ayrıştırmaz, HERHANGİ biri boşsa WARN üretir.

`_KURAL_BOYUT` haritasına üç giriş eklendi (yukarıdaki tablo).

---

## 2. Envanter — gerçek sorgu çıktıları

| Ölçü | Değer |
|---|---:|
| Public `.pdf` `File` satırı | **0** |
| Public `.docx` `File` satırı | **0** |
| Public `.xlsx` `File` satırı | **0** |
| Public `.pptx` `File` satırı | **0** |
| **Toplam public doküman `File` satırı** | **0** |
| Toplam `Listing Document` child satırı | **0** |
| — dil dolu / dil boş | 0 / 0 |
| — başlık dolu / başlık boş | 0 / 0 |
| Distinct bağlı dosya adresi | **0** |

**Dürüst okuma:** bu ortamda şu an **hiçbir seller/admin gerçek bir PDF/Office
dosyasını bir ilana bağlamamış** — `Listing Document` child'ı bugünkü görev
setinin (Task 1) kendisiyle açıldı, henüz canlı içerik yok. `test_file_manager_seo`
modülünün 64 testi (Düzeltme turu 1 dahil) kendi fixture'larını `addCleanup`/`_geri_al` ile TAM temizledi
— ölçüm script'i test koşusundan SONRA çalıştırıldı ve **sıfır test artığı
kaldığını da doğrudan kanıtlıyor** (rapor 108'in aksine, burada test kirliliği
YOK — 108'deki `File` artığı sorunu `test_media_watch.py`'nin ÖNCEDEN yazılmış
bir testinden kaynaklanıyordu, bu görevin (`test_file_manager_seo`) kendi
temizliği farklı ve eksiksiz çalıştı).

---

## 3. `doc_indexable` — gerçek koşum

| Ölçü | Değer |
|---|---:|
| Kontrol edilen distinct dosya sayısı | 0 |
| `doc_indexable(url) == True` | **0** |

Bağlı dosya olmadığı için havuz zaten boş — beklenen sonuç, §2'nin doğrudan
devamı.

---

## 4. Çıkarım / backfill durumu

| Ölçü | Değer |
|---|---:|
| Backfill öncesi aday (boş `page_count`+`extracted_text`) distinct dosya | 0 |
| `doc_meta.backfill_docs(limit=500)` — 1. koşu işlenen | **0** |
| Backfill sonrası kalan aday | 0 |
| `doc_meta.backfill_docs(limit=500)` — 2. koşu işlenen (idempotent doğrulama) | **0** |

Aday havuzu zaten boş olduğu için backfill'in idempotency'si burada "0 → 0"
şeklinde doğrulandı; asıl davranışsal kanıt `TestDocMetaBackfillIdempotent::
test_i_backfill_ikinci_turda_ayni_dosyalari_secmez` testinde (kendi
fixture'larıyla, gerçek 2 PDF ile) senkron olarak zaten var — testler
bölümünde ayrıca listelendi.

---

## 5. `missing_doc_title`/`missing_doc_text`/`missing_doc_language` — gerçek koşum

| Ölçü | Değer |
|---|---:|
| `missing_doc_title` WARN sayısı | 0 |
| `missing_doc_text` WARN sayısı | 0 |
| `missing_doc_language` WARN sayısı | 0 |

**Bu "0" — brief'in beklediği dürüst sonuç:** "index'e giren doküman: 0
(beklenen — içerik gelince dolacak)". Kuralların kendisinin GERÇEKTEN
çalıştığı `TestDocSeoBulgular` altında senkron olarak, sentetik fixture'larla
doğrulandı (aşağıda test özetinde) — üretim verisinde henüz denetlenecek
gerçek bir doküman olmadığı için bu sayının 0 olması pipeline'ın bozuk
olduğu anlamına gelmiyor, yalnız platformun bu özelliği henüz kullanılmadığı
anlamına geliyor.

---

## 6. `.pptx` artık yüklenebiliyor — test kanıtına atıf

Task 5'in platform düzeltmesi (`upload_policy.EXTENSIONS`'a `.pptx` eklendi)
bu görev setinde iki testle doğrulanmış durumda —
`tradehub_core/tests/test_file_manager_seo.py::TestUploadPolicyPptxKabul`:

- `test_pptx_icerigi_check_ten_gecer` — `upload_policy.check()` artık
  `.pptx` içeriğini `KIND_DOCUMENT` olarak kabul ediyor (önceden hiç
  yüklenemiyordu, Task 2 raporunun "ölü kod" bulgusu).
- `test_pptx_gercek_file_kaydi_olarak_yuklenebilir` — gerçek bir `File.insert()`
  ile `.pptx` kaydı oluşturuluyor (`naming.py`'nin hash adlandırma kapısı
  artık `ValueError` fırlatmıyor).

İkisi de bu koşumda **64/64** paketinin içinde YEŞİL geçti (aşağıda, Düzeltme
turu 1 sayısıyla).

---

## 7. Testler — gerçek koşum

```
$ docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_file_manager_seo
Ran 64 tests in 4.151s
OK
```

64 test (Task 1-6 birlikte) — Task 6'nın eklediği `TestDocSeoBulgular` 8 test
(6 ilk turdan + 2 Düzeltme turu 1'den):

- `test_bagli_belgede_uc_kural_da_warn_verir` — başlıksız + metni
  çıkarılmamış + dili boş, vitrinde görünen ilana bağlı PDF → üçü de WARN.
- `test_alanlari_dolu_belgede_hicbir_kural_tetiklenmez` — başlık/metin/dil
  dolu → hiçbiri.
- `test_gorsel_uzantida_kurallar_calismaz` — `.png` (DOC_UZANTILAR dışı,
  ilana bağlı olsa bile) → hiçbiri.
- `test_baglanmamis_belgede_kurallar_calismaz` — hiçbir ilana bağlı değil →
  hiçbiri.
- `test_deep_false_ta_calismaz` — `audit_file(..., deep=False)` → hiçbiri.
- `test_audit_batch_deep_true_de_calismaz` — `audit_batch([...], deep=True)`
  → hiçbiri (toplu yola bilerek eklenmedi).
- **(Düzeltme turu 1)** `test_iki_ilanli_belge_birinde_bos_dil_varsa_warn_verir`
  — aynı dosya İKİ vitrinde görünen ilana bağlı, biri dil dolu (`tr`) diğeri
  boş → `missing_doc_language` WARN VAR (docstring'in "HERHANGİ birinde
  boşsa" iddiası ilk kez çok-ilan senaryosuyla doğrulandı — önceki 6 test
  yalnız TEK ilanlıydı).
- **(Düzeltme turu 1)** `test_iki_ilanli_belge_ikisinde_de_dil_doluysa_warn_yok`
  — aynı kurulumun ters ucu, iki bağlı satırın İKİSİ de dolu (`tr`/`en`) →
  `missing_doc_language` hiç tetiklenmez.

Tam paket regresyon:

```
$ docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_media_watch
Ran 36 tests in 2.917s
OK

$ docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_media_seo_pipeline
Ran 39 tests in 1.244s
OK
```

`ruff check` + `ruff format --check` — `seo_audit.py`'ye eklenen kod ve
`test_file_manager_seo.py`'nin TAMAMI (Düzeltme turu 1 dahil) temiz. (`seo_audit.py`'nin
ÖNCEDEN VAR OLAN, bu görevde dokunulmamış `audit_batch`/`_technical_findings`
bölümünde `ruff format --check` 7 önceden var olan format farkı raporluyor —
bunlar bu görevin eklediği satırların DIŞINDA, kapsam dışı bırakıldı,
KORUNANLAR kuralı gereği dokunulmadı.)

---

## 8. Öz-denetim

- **Tüm sayılar gerçek sorgu çıktısı** — `docker cp` ile taşınan
  `/tmp/measure_109.py` script'i `frappe.db.sql`, `doc_indexable`,
  `doc_meta.backfill_docs`, `seo_audit.audit_file` gibi gerçek API'leri
  çağırdı; tahmini/yuvarlanmış değer yok.
- **"0" dürüstçe raporlandı, gizlenmedi** — hem envanter hem WARN sayıları
  gerçekten sıfır çünkü bu ortamda henüz gerçek bir doküman yüklenip bir
  ilana bağlanmadı. Kuralların ÇALIŞTIĞI iddiası envanterden değil,
  `TestDocSeoBulgular`'ın senkron/sentetik testlerinden geliyor.
- **`_doc_bulgulari`'nın `audit_batch`'e EKLENMEME kararı** açıkça test
  edildi (`test_audit_batch_deep_true_de_calismaz`) — `_watch_slug_bulgusu`
  için geçerli olan AYNI maliyet gerekçesi (108 raporunun §7'sindeki
  gerekçeyle birebir aynı).
- **Test artığı YOK** — bu görevin kendi 64 testi (Düzeltme turu 1 dahil) tam temizlik yaptı,
  ölçüm script'i test koşusundan SONRA "0" okudu ve bu sıfırın test
  kirliliğinden değil gerçek boş veriden geldiğini doğruladı (108'in
  aksine).
- **Yazma disiplini:** ölçüm script'i `SELECT`/`get_value` + tek bir
  YAZMA işlemi (`doc_meta.backfill_docs`, görevin istediği adım, aday
  havuzu zaten boş olduğu için 0 satır etkiledi). `git add`/commit
  YAPILMADI.
- **Düzeltme turu 1 (denetim bulgusu, 1 Important):** ilk sürümde
  `missing_doc_language`'ın "dosya birden çok ilana bağlıysa HERHANGİ
  birinde dil boşsa WARN" iddiası yalnız kod yorumunda vardı, testlerin
  hepsi (6/6) TEK ilanlı senaryoydu — çok-ilanlı dal hiç koşulmamıştı. İki
  test eklendi (`_iki_gorunur_ilan` + `_ilan_belge_baglar_ozel` iki farklı
  `language` değeriyle): (a) biri dolu biri boş → WARN VAR, (b) ikisi de
  dolu → WARN YOK. Kapsam yalnız test dosyasıydı, `seo_audit.py`'ye
  DOKUNULMADI (davranış zaten doğruydu, yalnız kanıt eksikti). 64/64 yeşil,
  ruff temiz, `git add`/commit YAPILMADI.
- **KORUNANLAR:** `seo_audit.py` dışında hiçbir kaynak dosyaya
  dokunulmadı (bu rapor hariç).
