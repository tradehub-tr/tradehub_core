# 92 — W8 Güvenlik temizliği + T-134 KVKK denetim izi

**Tarih:** 2026-08-20 · **Kaynak:** rapor 87 (B-02/B-03/B-04) + T-134 şartnamesi
(`71-faz13-guvenlik-observability.html`). **Yöntem:** her kalem ÖNCE ölçüldü
(başka dalgalarca kapanmış mı), sonra yapıldı. Commit atılmadı; `hooks.py` /
`patches.txt`'e DOKUNULMADI (gereken patch §3'te metin olarak raporlandı);
DocType değişikliği konteynerde hedefli `reload-doc` + `clear-cache` ile
uygulandı (tam `bench migrate` koşulmadı — patch değişikliği yok, gerek yoktu).
Konteyner dosya eşitlemesi `docker cp` ile (backend imajı bind-mount değil —
kalıcı dağıtım için imaj rebuild gerekir).

> **Ölçüm dürüstlüğü:** "kapalı/açık" iddialarının hepsi bu koşumda üretilen
> canlı çıktılara dayanır; önceden kırık bulunan her şey HEAD'e karşı ayrıca
> doğrulanıp "pre-existing" olarak işaretlendi (§5).

---

## Özet

| # | Kalem | Önce (ölçüm) | Sonra |
|---|---|---|---|
| 1 | **B-02 gölge modül** `tradehub_core/tradehub_core/api/seller.py` | Başka dalga kapatmamış; Nisan 2026'dan kalma bayat kopya, 5 guest ucunu güncel guard'lar OLMADAN ikinci kez expose ediyor; hiçbir çağıranı yok | **SİLİNDİ** (git geçmişi korur); guest baseline 111→106; HTTP kanıtı: gölge uç artık 417 "No module named", kanonik 200 |
| 2 | **B-03 IBAN permlevel-0** | Kapatılmamış (izolasyon dalgası yalnız satır düzeyini kapatmış + eski davranışı test-pinlemiş); satırı okuyan her rol IBAN'ı okuyordu; IBAN'ı permission-checked yoldan okuyan HİÇBİR ekran yok | `seller_iban`+`seller_bank_name` **permlevel-1**; pl-1 read: System Manager (w=1) + Marketplace Admin; canlı kanıt: alıcı havale ekranları kırılmadı, perm-checked yol IBAN'ı artık vermiyor |
| 3 | **B-04 dev traceback** | **Yalnız-dev DEĞİL**: kapı `System Settings.allow_error_traceback` (v15 default **1**) — `is_traceback_allowed()` developer_mode'a hiç bakmıyor; guest 5xx'te tam traceback + iç yollar ölçüldü | Dev sitede `allow_error_traceback=0` yapıldı, sızıntı ölçülerek kapandı; kalıcı (prod dahil) çözüm patch'i §3'te raporlandı (patches sahipliği bu işte yok) |
| 4 | **T-134 KVKK denetim izi** | KVKK arşiv indirme (m.11) HİÇ denetim üretmiyordu; dahası **iki gerçek kırık ölçüldü**: (a) `actor="System"` ADL Link doğrulamasına takılıyor → `account.anonymize`/`retention_anonymize` satırları HİÇ yazılmamış (ADL'de 0 kayıt); (b) indirme ucu `basename` yüzünden alt-klasörlü dosya yerleşiminde 404 → m.11 indirme akışı fiilen ÇALIŞMIYORDU | 3 yeni denetim noktası (`privacy.export_generated/downloaded/purged`), iki kırık düzeltildi, akış canlıda uçtan uca koşuldu ve ADL satırları doğrulandı; maskeleme kuralı test-pinli |

---

## 1. B-02 — Gölge modül: ölç → sil → doğrula

**Doğum/ömür (git):** dosya `5a6ac29` (initial commit) ile doğmuş; son dokunuş
`656927e` (2026-05-18, profil refactoru). Kanonik `api/seller.py` (2215 satır)
yaşamaya devam ederken gölge 235 satırda kalmış.

**İçerik ölçümü — bayat VE daha zayıf guard'lı:** 7 uç (5 guest: `get_sellers`,
`get_seller`, `get_reviews`, `get_storefront_layout`, `send_inquiry`; 2 oturumlu:
`save_storefront_layout`, `publish_storefront_layout`). Gölge `send_inquiry`
kanoniğin M18/HATA-20/F-034 düzeltmelerinin HİÇBİRİNİ taşımıyordu: rate-limit
yok, self-inquiry engeli yok, min-uzunluk yok, guest'te e-posta zorunluluğu yok
— yani spam korumasının tamamen yanından dolaşan ikinci bir kapıydı. Gölge
`save_storefront_layout` da `require_seller_capability("storefront.write")`
kapısını taşımıyordu.

**Referans ölçümü — sıfır çağıran:** `tradehub_core.tradehub_core.api.seller`
dotted yolu 3 repoda (backend + tradehubfront + admin-panel) yalnız rapor/test
metinlerinde geçiyor; tüm istemciler kanonik `tradehub_core.api.seller.*`
çağırıyor (`sellerShop.ts:352`, `CompanyProfile.ts:469,1106`,
`StorefrontLayoutEditor.vue:654,760` vb.). `publish_storefront_layout`'un
çağıranı hiçbir yerde yok. hooks/fixtures/workspace'te referans yok.

**Aksiyon:** dosya silindi; `tests/test_faz13_guest_surface.py` baseline'ından
5 gölge ucu çıkarıldı, sayı pini 111→106 güncellendi (yorumuyla).

**Doğrulama:**
- `test_faz13_guest_surface` 8/8 — host (3.9) VE konteyner (3.11).
- HTTP: gölge uç → `417 {"exc_type":"ValidationError"... "No module named
  'tradehub_core.tradehub_core.api.seller'"}` (backend restart sonrası da);
  kanonik uç → `200`.
- Geniş süit koşumu §5'te (dokunulanların tamamı yeşil).

---

## 2. B-03 — Payment Transaction IBAN permlevel katmanlaması

### Önce-ölçüm: kim neyi hangi yoldan okuyor

- **DocPerm (pl-0):** System Manager (rwc), Marketplace Admin (rw), Buyer
  (r, `if_owner=1`), Marketplace Seller (r). `seller_iban`/`seller_bank_name`
  pl-0'daydı → satırı okuyan HERKES alan düzeyi engel olmadan IBAN okuyordu.
- **Satır düzeyi izolasyon** başka dalgada kapatılmış: `hooks.py`'de
  `payment_transaction_query_conditions` + `payment_transaction_has_permission`
  (permissions.py:2898,2926) ve `test_payment_transaction_isolation.py` (12
  test) mevcut. Yani kiracı-DIŞI sızıntı yok; kalan iş **alan katmanlaması**.
- **Alıcının havale ekranları** (`api/payment.py`): `get_wire_transfers` /
  `get_bank_interactions` `frappe.get_list(..., ignore_permissions=True)`,
  `get_wire_transfer_detail` `frappe.db.get_value` — permlevel bu yolları
  ETKİLEMEZ. Alıcı havale yapabilmek için IBAN'ı görmeye devam eder.
- **Satıcının kendi IBAN ekranı var mı?** YOK. Panelde Payment Transaction'a
  bağlı hiçbir görünüm yok (tek eşleşme medya slot-envanteri verisi); satıcının
  IBAN kaynağı `Admin Seller Profile.iban` (kendi profil/banka ayarı).
  Storefront/panelde `seller_iban` yalnız `tradehubfront/src/types/payment.ts`
  tip tanımında (alıcı havale ekranlarının tipi).
- **Yazma yolları** hep sistem: `create_payment_transaction` (`insert(
  ignore_permissions=True)`), `update_transaction_status` (`db.set_value`),
  backfill patch'i, raw SQL güncellemesi — pl-1 write kısıtı bunları etkilemez.

Sonuç: taşıma hiçbir ekranı kırmaz → **taşındı**.

### Değişiklik

`payment_transaction.json`: iki alana `"permlevel": 1`; permissions'a iki pl-1
satırı eklendi — System Manager (read+write), Marketplace Admin (read). pl-0
satır perm'leri AYNEN korundu. `modified` güncellendi.

### Canlı doğrulama (reload-doc + clear-cache sonrası, istoc.localhost)

```
tabDocField: (('seller_bank_name', 1), ('seller_iban', 1))
tabDocPerm : Buyer(0,r), M.Admin(0,rw), M.Seller(0,r), SysMgr(0,rw),
             M.Admin(1,r), SysMgr(1,rw)
```

Canlı prob (gerçek kayıt PAY-00003, gerçek alıcı oturumu):

| ölçüm | sonuç |
|---|---|
| alıcı `get_wire_transfer_detail` → IBAN | **VAR** (ekran kırılmadı) |
| alıcı `get_wire_transfers` (3 kayıt) → IBAN | **VAR** |
| alıcı perm-checked yol (`apply_fieldlevel_read_permissions`) | IBAN **GİZLİ** ✅ |
| Marketplace Admin perm-checked yol | IBAN **GÖRÜNÜR** ✅ |

### Testler

- **Yeni:** `tests/test_payment_iban_permlevel.py` (5 test, frappe'siz JSON
  pini + vacuity; CI kapısına eklendi). Host 3.9 ve konteyner 3.11 yeşil.
- **Güncellenen:** `test_payment_transaction_isolation.py` —
  `test_owner_seller_sees_own_payment` eski davranışı pinliyordu (satıcı
  `frappe.client.get` ile kendi satırının IBAN'ını okur; rapor 87'nin
  "permlevel VEYA test-pinle" ikileminde o dalga pinlemeyi seçmişti). Pin,
  yeni katmanlamaya çevrildi (`assertIsNone` + gerekçe yorumu) ve
  `test_marketplace_admin_sees_everything`'e pozitif kontrol eklendi (admin
  IBAN'ı OKUMALI). Konteynerde **12/12 OK**.
- `test_payment_pii_security` 2/2 (gate yoluyla; bu modül frappe-stub'lı olduğu
  için `bench run-tests` ile KOŞULAMAZ — tasarımı öyle, §5 not).

---

## 3. B-04 — Traceback sızıntısı: yalnız-dev davranışı DEĞİL

### Ölçüm

Kapı `frappe/utils/response.py::is_traceback_allowed()`:
`frappe.get_system_settings("allow_error_traceback")` — **DB ayarı**, v15
şemasında **default '1'** (`system_settings.json`), hiçbir frappe patch'i
kapatmıyor ve fonksiyon `developer_mode`'a HİÇ bakmıyor. Yani `developer_mode=0`
olan bir prod sitesi de, kimse ayarı elle kapatmadıysa, guest'e tam traceback
döndürür. Dev sitede canlı ölçüm (guest, B-05 tetikleyicisi — bozuk JSON gövde):

```
ÖNCE : 500 {"exception":"json.decoder.JSONDecodeError...","exc":"[\"Traceback ...
        apps/frappe/frappe/app.py, line 105 ... /usr/local/lib/python3.11/json/...
SONRA: 500 {"exc_type":"JSONDecodeError"}          (Accept: application/json)
SONRA: 0 adet "Traceback|apps/frappe" eşleşmesi     (Accept: text/html)
```

### Yapılan

Dev sitesinde `System Settings.allow_error_traceback = 0` (canlı, ölçülerek
kapandı; hatalar `Error Log`'a yazılmaya devam eder — geliştirici kaybı yok).

### Raporlanan (patch sahipliği bu işte yok — uygulanacak metin)

`tradehub_core/patches/v15_9_25_disable_error_traceback.py`:

```python
import frappe

def execute():
	# B-04 (rapor 87/92): v15'te allow_error_traceback default=1 ve
	# is_traceback_allowed() developer_mode'a bakmaz → prod'da guest'e
	# tam traceback sızar. İdempotent olarak kapat.
	frappe.db.set_single_value("System Settings", "allow_error_traceback", 0)
```

`patches.txt`'e: `tradehub_core.patches.v15_9_25_disable_error_traceback`.
Prod DB'sine erişim olmadığı için prod'un bugünkü değeri ÖLÇÜLEMEDİ (kvkk.md
§10'daki 1 no'lu sınırla aynı); patch uygulanana dek prod'da sızdığı varsayılmalı.

---

## 4. T-134 — KVKK denetim izi: fark analizi + eklemeler

### Şartname vs bugün (fark tablosu)

| Şartname maddesi | Durum (ölçüm) |
|---|---|
| Silme/geri yükleme, ayar değişikliği, moderasyon, toplu iş denetimi | ✅ mevcut (`media/audit.py` 20 eylem; `ACTION_TRASH/UNTRASH/DELETE/PURGE_*`, `ACTION_SETTINGS_CHANGED`, `log_media_batch`) |
| Append-only + hash zinciri + saklama | ✅ mevcut (`flags.audit_write` + DocPerm; `adl_entry_hash`/`verify_chain`; `hot_days=90`) |
| Hassas kayıt maskeleme (URL/kimlik sızmaz) | ✅ mevcut ve **test-pinli**: `test_media_access_level.py::test_gecis_hassas_isaretlenir_ve_ham_url_context_e_yazilmaz` + `::test_gercek_adl_kaydinda_object_name_maskeli`, `test_observability.py` mask testleri. Privacy tarafı için yeni pin bu raporla eklendi (aşağıda) |
| Belge erişimi (imzalı URL, KYC dahil) | ✅ mevcut (`media.signed_access`, `media_access.py:291`) |
| PII alan açma (reveal) denetimi | ✅ mevcut (`log_pii_reveal`, panel `DataMaskingField.vue` kablolu) |
| **KVKK arşivi (m.11 export) erişim logu** | ❌ **YOKTU** → eklendi: `privacy.export_downloaded` (ALLOW + tüm DENY dalları) |
| **Export üretim izi** | ❌ YOKTU → eklendi: `privacy.export_generated` (HIGH — `media.export` emsali) |
| **Export imha izi (m.7)** | ❌ YOKTU → eklendi: `privacy.export_purged` (tek özet satır — `log_media_batch` deseni) |
| Silme/anonimleştirme izleri | ⚠️ kod VARDI ama **hiç çalışmamış** (aşağıda K-1) → onarıldı |
| Sır erişimi (`get_password`) denetimi | ❌ yok (12+ çağrı noktası: sentiment/moderation/translation/push/logistics_admin...) — **açık, raporlandı** |
| legal_hold değişim denetimi | — legal_hold canlı bir özellik değil (retention.py §5.2 "bugün YOK") — denetlenecek yüzey yok |
| Veri sahibi akışının medya ayağı | ❌ hâlâ yok (kvkk.md Ö-K2/Ö-K3) — kapsam dışı, açık |

### Ölçülen iki gerçek kırık (ve onarımı)

**K-1 — `actor="System"` satırları HİÇ yazılmamış.** ADL `actor` alanı
Link→User doğrulamalı; "System" diye bir User yok. Canlı kanıt: ADL'de
`account.anonymize` = **0 satır**, `retention_anonymize` = **0 satır**; benim
ilk `privacy.export_generated` denememde Error Log'a düşen satır:
`log_decision başarısız: actor=System ... Actor: System bulunamadı`. Yani
KVKK m.7 anonimleştirme izleri, eklendikleri günden beri best-effort yutması
yüzünden SESSİZCE kayboluyordu. **Onarım:** 4 çağrı noktasında (`data_export.py`
×2 — benim; `account_deletion.py`, `data_retention.py` — mevcut kırık)
`actor="Administrator"` (sistem işlerinin gerçek oturumu) + gerekçe yorumu.

**K-2 — m.11 indirme akışı fiilen çalışmıyordu.** `download_data_export`
`os.path.basename(file_url)` kullanıyordu; `File.insert` medya motorunun
içerik-adresli yerleşimiyle ZIP'i `/private/files/8f/8f0a...zip` gibi alt
klasöre taşıyor → basename `8f/` parçasını düşürüyor → "Dosya bulunamadı".
Canlı ölçüldü (kvkk.md §10/4'ün "akış hiç koşmadı" şüphesinin cevabı: koşunca
KIRILIYORDU). **Onarım:** `file_url`'den `/private/files/` sonrası göreli yol +
`realpath` ile private/files köküne sabitleme (path-escape denemesi de DENY
denetim satırı üretir, `reason=path_escape`).

### Canlı uçtan uca kanıt (istoc.localhost, DEXP-0602)

| adım | sonuç |
|---|---|
| Talep + `generate_user_data_export` | status=Ready, ZIP 754B (`8c/…zip` alt-klasör) |
| `privacy.export_generated` ADL | **ADL-20260820-000866** — ALLOW/HIGH, actor=Administrator, context `{"doctypes":1,"zip_bytes":754}` (e-posta YOK, token YOK) |
| Yanlış token (guest) | throw'a RAĞMEN DENY satırı kalıcı (commit-önce-throw, `media/audit._persist` gerekçesi); context'te denenen/gerçek token YOK, `ip_hash` VAR |
| Doğru token (guest) | 754B indirildi; **ADL-20260820-000868** — ALLOW, actor=Guest, context `{"ip_hash":"…","zip_bytes":754}`, e-posta sızmadı |

### Maskeleme kuralı — pin durumu

Medya tarafı mevcut testlerle sabit (yukarıdaki iki referans). Privacy tarafı
için **yeni** `tests/test_privacy_audit.py` (9 test, frappe-stub'lı, gerçek
`log_decision` koşar): DENY/ALLOW satırlarının varlığı; token/ham-IP/e-posta
sızmadığı (`test_maskeleme_token_ip_email_sizdirmaz` + vacuity); alt-klasörlü
indirme; path-escape DENY; imhanın tek özet satırı; eylem adlarının
nokta-deseni. Host 3.9 + konteyner 3.11 yeşil. CI kapısına eklendi.

---

## 5. Süit durumu ve önceden-kırıklar (HEAD'e karşı doğrulanmış)

**Benim dokunduğum/eklediğim her şey yeşil (konteyner, Python 3.11):**
`test_payment_transaction_isolation` 12/12 (bench) · `test_media_access_level`
15/15 · `test_kyc_tenant_isolation` 13/13 · `test_file_multirow_isolation`
15/15 (bench) · `test_faz13_guest_surface` 8/8 · `test_payment_iban_permlevel`
5/5 · `test_privacy_audit` 9/9 · `test_audit` 18/18 · `test_payment_pii_security`
2/2 · `test_seller_inquiry_isolation` 1/1 (onarım sonrası).

**Onarılan pre-existing kırık:** `test_seller_inquiry_isolation` hiç
İMPORT EDİLEMİYORDU (`api/seller.py:5`'in `from frappe.utils import getdate,
nowdate` satırı stub'da yoktu — HEAD'de de kırık). Stub'a asgari `frappe.utils`
eklendi; konteynerde yeşil (host 3.9'da `dict | None` sözdizimi yüzünden yine
koşamaz — bilinen 3.9 sınırı, rapor 87).

**Pre-existing kırmızılar (dokunulmadı, HEAD'de de aynı — kanıt: HEAD worktree
konteyner koşumu):** `test_tenant_isolation` (1/22 hata — stub'da
`frappe.utils.now_datetime`/`get_traceback` eksik), `test_audit_hashchain`
(stub'da `frappe.whitelist` eksik — audit/log.py'ye sonradan eklenen F-041
dekoratörü), `test_rebac_abac_e2e`, `test_get_customer_detail_pii` (import
kırıkları). Ayrıca `test_tuple_sync` bilinen askı (rapor 87 devir #7) — koşum
dışı bırakıldı. `test_payment_pii_security` ve benzeri stub-testler
`bench run-tests` ile koşulamaz (stub gerçek frappe modülünü ezer; runner
`frappe.cache` hatası verir) — bunlar kapının `python3 -m unittest` yolu için
tasarlanmış, davranış pre-existing.

---

## 6. Dokunulan dosyalar

- **Silinen:** `tradehub_core/tradehub_core/api/seller.py` (gölge; git korur)
- **DocType:** `.../doctype/payment_transaction/payment_transaction.json`
  (yalnız permlevel katmanı + pl-1 permler)
- **Audit/privacy:** `tradehub_core/privacy/data_export.py` (2 yeni denetim
  noktası + actor onarımı), `tradehub_core/api/v1/compliance.py` (indirme
  denetimi + K-2 yol onarımı + path-escape koruması),
  `tradehub_core/privacy/account_deletion.py`, `tradehub_core/privacy/
  data_retention.py` (yalnız K-1 actor onarımı, birer satır + yorum)
- **Testler:** yeni `test_payment_iban_permlevel.py`, yeni
  `test_privacy_audit.py`; güncellenen `test_faz13_guest_surface.py` (baseline),
  `test_payment_transaction_isolation.py` (pin çevirisi + pozitif kontrol),
  `test_seller_inquiry_isolation.py` (pre-existing import onarımı)
- **Gate:** `scripts/run_authz_tests.sh` (+2 modül)
- **Dokunulmadı:** `hooks.py`, `patches.txt`/`patches/`, prod, nginx, storefront/panel kodu

**İz notu (dev sitesi):** `System Settings.allow_error_traceback` 1→0 (kalıcı,
bilinçli); 2 adet `Data Export Request` (DEXP-0601 probe artığı Ready — 72 saat
sonra `cleanup_expired_exports` imha eder ve artık bunu denetime yazar;
DEXP-0602 kanıt koşumu) + append-only ADL satırları (silinemez, gerçek denetim
kayıtları); backend konteyneri 1 kez restart edildi (gunicorn'daki gölge modül
önbelleği için). Probe yardımcıları konteynerden temizlendi.

## 7. Devir — açık işler (öncelik)

1. **B-04 kalıcılaştırma:** §3'teki patch'i `patches.txt`'e ekle + prod'da
   `allow_error_traceback` değerini ölç (patch sahipliği bu dalgada yoktu).
2. **`download_data_export` token brute-force:** DENY denetimi artık iz
   bırakıyor ama uçta rate-limit yok — `@rate_limit` (send_inquiry emsali)
   eklenmeli (rate_limit.py B-01 atomiklik düzeltmesiyle birlikte).
3. **Sır erişimi denetimi:** `get_password` çağrı noktalarına (12+) T-134'ün
   istediği izi ekle — en değerlisi `logistics_admin.reveal` benzeri uçlar.
4. **KVKK medya ayağı:** Ö-K2 (`_EXPORTABLE_DOCTYPES`'e `File`), Ö-K3
   (`account_deletion`'a medya adımı) — kvkk.md §11 sahipleriyle.
5. **Pre-existing kırmızılar (§5):** 4 stub-test import kırığı + `test_tuple_sync`
   askısı; kapı hijyeni için ayrı iş.
6. **`account.anonymize` satırındaki `user` e-postası:** User.name (login
   anahtarı) anonimleştirmede zaten korunuyor diye bugün sızıntı SAYILMADI ve
   dokunulmadı; hesap adları ileride hash'lenirse bu context de parmak izine
   çevrilmeli.
