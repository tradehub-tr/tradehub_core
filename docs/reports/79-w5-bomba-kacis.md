# 79 · W5 — Megapiksel-bomba kaçış aralığının kapanması (rapor 75, bulgu 4)

**Tarih:** 2026-08-20
**Kapsam:** GÜVENLİK düzeltmesi. Panel E2E denetiminin ölçtüğü kaçış: Pillow'un
kendi `MAX_IMAGE_PIXELS` tavanının üstünde boyut BEYAN eden PNG (30000×30000,
900 MP) başlığı hiç açılamadığı için ölçü 0 okunuyor ve 80 MP bomba tavanı
**hiç değerlendirilmiyordu** — dosya 200 ile kabul edildi (canlı iz:
`/files/25/25b8f950….png`). Yalnız 80–89 MP penceresi yakalanıyordu.
Kural artık **fail-closed**.

---

## 1. Kök neden (ÖLÇÜLDÜ)

- `content_gate.inspect` 7. kuralı piksel ölçüsünü `image/probe._open_header`
  (Pillow `Image.open`) üzerinden okuyordu.
- Pillow, beyan edilen piksel sayısı `MAX_IMAGE_PIXELS × 2` (≈179 MP) üstündeyse
  `DecompressionBombError` atar ve başlığı **hiç açmaz**. `_open_header` bunu
  genel `except Exception` ile yutuyor, ölçü `(0, 0)` kalıyordu.
- Eski kural `mp > 80` idi; `0 > 80` yanlış → kural **sessizce atlanıyordu**.
  Modüldeki yorum bunu bilinçli sayıyordu ("Pillow açamazsa … kural
  kendiliğinden atlanır — yanlış pozitif riski taşımaz") — riskin kendisi tam
  olarak buydu: en agresif bomba, denetimden *hata yüzünden* muaftı.

## 2. Düzeltme

| Dosya | Değişiklik |
|---|---|
| `tradehub_core/media/pipeline/image/probe.py` | **`declared_dimensions(head, detected)`** eklendi: PNG/JPEG/GIF/WebP/BMP boyutunu **Pillow'a hiç sormadan** ilk baytlardan okur (PNG IHDR, JPEG SOFn yürüyüşü, GIF mantıksal ekran, WebP VP8/VP8L/VP8X, BMP core/info header). `_open_header` `DecompressionBombError`'ı ayrı yakalayıp `decompression_bomb` işaretler. `probe_header` Pillow ölçü veremediyse beyanı ham baytlardan doldurur. `_guard`'daki piksel tavanı `readable`'dan bağımsızlaştı ve fail-closed: ölçü ham baytlardan da okunamayıp `decompression_bomb` işaretliyse yine `megapixel_bomb` RED. |
| `tradehub_core/media/pipeline/security/content_gate.py` | `_boyut_basliktan` önce `declared_dimensions`, sonra Pillow başlığı dener; `None` = hiçbir yolla okunamadı. 7. kural fail-closed: içerik bilinen görsel biçimiyse (`IMAGE_KINDS`) ölçüsü **okunamayan** ya da **0/negatif** dosya da `upload_image_bomb` ile RED. AVIF/HEIC (`sniff` onları `mp4`/`""` görür) fail-closed dalına GİRMEZ — meşru korpus (852 dosya) kesilmez, eski atlama davranışı yalnız onlarda sürer. |
| `tradehub_core/tests/test_media_bomb_escape.py` | YENİ — 14 test, bench'siz (aşağıda). |

Hata kodu **uydurulmadı**: `content_gate.KOD_BOMB = "upload_image_bomb"` →
`upload_policy.CONTENT_BOMB` → HTTP 417; probe tarafında mevcut
`SEBEP_MEGAPIXEL_BOMB = "megapixel_bomb"`.

## 3. Testler — `test_media_bomb_escape.py` (bench'siz)

Sentetik üretici, panel E2E `helpers.ts makeBombPng()` ile aynı yapı
(geçerli imza + IHDR + küçük IDAT + IEND; fixture depoya KONMADI).

| Sınıf | İddia |
|---|---|
| `KacisAraligi` | 30000² (900 MP, Pillow-açılamaz — pencere ölçümü testin içinde) → RED `olculen=900.0`; 9200² (84,6 MP) ve 12000² (144 MP, S10'un bombası) → HÂLÂ RED; gerçek 2000² PNG ve sentetik 100² → GEÇER |
| `FailClosed` | 0×0 beyan → RED; PNG imzalı bozuk başlık (IEND'li, kesiklik kuralına düşmesin diye) → RED; ölçüsüz görsel-olmayan içerik (CSV) → eskisi gibi girmez |
| `ProbeKapisi` | `probe_header(30000²)` → `codes[0] == "megapixel_bomb"`, ölçü ham baytlardan (30000, 30000) okunmuş; `assert_accepted` → `ImageRejected`; 9200² regresyonu |
| `BeyanOlcusu` | `declared_dimensions` temiz fixture korpusunda (PNG/JPEG/GIF/WebP/BMP) Pillow'un okuduğu ölçünün **aynısını** verir; TIFF/bilinmeyen → `None` |

## 4. Kırmızı kanıt (vacuity)

Yeni test modülü, düzeltme UYGULANMADAN önce konteynere tek başına kopyalanıp
koşturuldu (`env/bin/python -m unittest`, düzeltilmemiş probe/content_gate ile):

```
FAIL: test_pillow_tavani_ustu_bomba_reddedilir
  AssertionError: () is not true : 900 MP bomba kapıdan GEÇTİ — kaçış aralığı hâlâ açık
FAIL: test_sifir_boyut_beyani_reddedilir      'upload_image_bomb' not found in []
FAIL: test_bozuk_baslik_reddedilir            'upload_image_bomb' not found in []
FAIL: test_probe_header_bomba_kodunu_verir    'megapixel_bomb' not found in ('decode_failed',)
(+ 3 ERROR: BeyanOlcusu — `declared_dimensions` henüz yok)
```

Düzeltme kopyalandıktan sonra aynı komut **14/14 OK**. Testler düzeltmeyi
gerçekten ölçüyor; 9200²/12000²/normal-görsel testleri düzeltme öncesinde de
geçiyordu (o pencereler zaten çalışıyordu — bulgunun sınırıyla tutarlı).

## 5. Doğrulama (KONTEYNERDE koşturuldu — `istoc-dev-backend-1`)

| Komut | Sonuç |
|---|---|
| `env/bin/python -m unittest test_media_bomb_escape + test_media_security_gate + test_image_probe + test_media_security_svg` | **58 test OK** |
| `env/bin/python -m unittest test_contracts test_image_classify test_image_normalize test_observability test_observability_instrument test_policy_engine test_svg_sanitize test_state_machine test_e2e_scenarios` | **OK** (skip'ler hariç 0 fail) |
| `bench --site istoc.localhost run-tests --module tradehub_core.tests.test_pipeline_bridge` | **22 test OK** |
| `bench … run-tests --module tradehub_core.tests.test_media_av` | 90/91 — `test_backfill_null_satiri_kuyruga_alir` DÜŞÜYOR; **ÖNCEDEN de düşüyordu** (düzeltme geri alınıp aynı konteynerde tekrar koşturularak ölçüldü — bu değişiklikle ilgisiz, .txt dosyası + AV backfill süzgeci; ayrı iş) |
| Yerel `ruff check` (3 dosya) | temiz (`ruff format --check`'in tek şikâyeti probe.py'de DOKUNULMAYAN eski bir satır — yerel ruff 0.16.3 / proje pini farkı, elle biçim değiştirilmedi) |

## 6. Canlı ölçüm — S10 yolu (rapor 75 W4-5 helper deseni)

Satıcı oturumu `global-setup.ts` deseniyle üretildi (bench console →
`frappe.sessions.Session`, `ali.bal@turksab.com` / SEL-00003), CSRF
`get_session_user`'dan alındı, istekler `http://istoc.localhost` üzerinden
gerçek `upload_media` ucuna atıldı (backend konteyneri `docker cp` sonrası
yeniden başlatıldı ki gunicorn yeni modülü yüklesin):

| İstek | Yanıt |
|---|---|
| `e2e-w5-bomb30000.png` (30000², **daha önce 200 ile geçen vaka**) | **HTTP 417 · `upload_error: upload_image_bomb`** |
| `e2e-w5-bomb12000.png` (12000², eski pencere regresyonu) | **HTTP 417 · `upload_image_bomb`** |
| `e2e-w5-normal.png` (64², reddin ardından — worker sağlam) | **HTTP 200** (`/files/c6/c6acaf2eac058fe319911e664bb82c02.webp`) |

Reddedilen iki bomba **hiçbir File kaydı yazmadı** (ölçüldü:
`count(File, e2e-w5-bomb%) = 0`). Bırakılan tek iz: `e2e-w5-normal.webp`
(1 File kaydı, 86 bayt) — rapor 75 §5'teki e2e izi sınıfında, temizlik ayrı iş.

## 7. Dokunulmayanlar

`pipeline_bridge.py`, `enrich.py`, `api/**`, `hooks.py`, `patches.txt`,
frontend, `docker/` — değişmedi. Mevcut hiçbir test gevşetilmedi; düzeltme
worker/scheduler konteynerlerine de kopyalandı (`docker cp`, imaj rebuild'i
ayrı iş — bkz. memory: konteyner dosyaları imaj yeniden kurulunca sıfırlanır,
kalıcılık repo'daki bu commit'tedir).
