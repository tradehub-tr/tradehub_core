# KVKK uyum kaydı — medya ve kişisel veri

**Tarih:** 2026-08-19 · **Görev:** T-134 · **Depo:** `tradehub_core` (`ahmet`)
**Ölçüm ortamı:** `istoc-dev-backend-1`, site `istoc.localhost`, Frappe v15,
bench Python 3.11.6

**Kardeş belgeler — bu belge onların yerine GEÇMEZ:**

| Belge | Ne anlatır | Bu belgeyle ilişkisi |
|---|---|---|
| `docs/security/faz13-gdpr.md` | EXIF/metadata temizliği, GDPR eşlemesi, ölçüm deneyleri | Teknik mekanizma. Bu belge onu tekrar etmez, §3'te atıf yapar |
| `docs/security/faz13-tehdit-modeli.md` | T-132 tehdit modeli | Saldırı yüzeyi |
| `docs/reports/19-`, `24-`, `28-`, `29-` | Bugün ölçülen ve kapatılan açıklar | **Bu belgenin §4'ü bu dört rapordan türedi** |

> **Hukuki not.** Bu belge hukuk mütalaası değildir. 6698 sayılı KVKK
> maddelerine yapılan atıflar, hangi teknik kontrolün hangi yükümlülüğe
> karşılık geldiğini göstermek içindir. Nihai değerlendirme veri sorumlusunun
> ve hukuk danışmanının işidir. Özellikle §4.6'daki **ihlal bildirimi
> değerlendirmesi bir karar değil, karar için gereken teknik girdidir.**

---

## 0. Yöntem etiketleri

| Etiket | Anlamı |
|---|---|
| **[Ö]** | Bu görevde canlı sitede **ölçüldü** — betik §9'da, çıktı aynen aktarıldı |
| **[K]** | Kod okundu (`dosya:satır`) |
| **[R]** | Başka bir raporda ölçülmüş, buraya alıntılandı (rapor numarası yazılı) |
| **[T]** | Tasarım/hukuk yorumu — ölçüm değil |
| **[?]** | **ÖLÇÜLEMEDİ** → §10 |

---

## 1. Bu belge neden var

`docs/reports/36-dogrulama-faz12-14.md` T-134'ü **KISMİ** saydı ve iki gerekçe
yazdı: *"KVKK envanteri + veri sahibi talebi akışı"* belgelenmemiş ve
`docs/compliance/kvkk.md` yok. Birinci gerekçe doğru, ikincisi yarım: KVKK
içeriğinin bir kısmı `docs/security/faz13-gdpr.md` altında duruyordu ama o
belge **EXIF temizliğine** odaklı ve kendi kapsamını öyle tanımlıyor.

Eksik olan üç şey vardı ve bu belge onları verir:

1. **Envanter** — medya hattında kişisel veri tam olarak hangi alanlarda ve
   bugün kaç dosya (§3, ölçüldü).
2. **Olay kaydı** — 2026-08-19'da kapatılan açıkların kişisel veriyle ilgili
   olanları, KVKK madde eşlemesi ve ihlal bildirimi değerlendirmesi (§4).
3. **Veri sahibi talebi akışı** — bugün ne var, ne yok (§5, ölçüldü).

---

## 2. Roller ve kapsam

| KVKK kavramı | Bu sistemdeki karşılığı |
|---|---|
| Veri sorumlusu | Platform işletmecisi (İstoç Ticaret Merkezi tüzel kişiliği) |
| Veri işleyen | Barındırma ve depolama sağlayıcıları; bugün **tek makine + yerel disk** [Ö] |
| İlgili kişi | Alıcı (`Buyer`), satıcı yetkilisi (`Seller Owner`/`Marketplace Seller`), başvuru sahibi |
| Özel nitelikli veri | Kimlik belgesi taraması (TCKN + fotoğraf) — KVKK m.6 |

**Yurt dışı aktarım (m.9):** bugün **yok** [Ö] — `media_storage_settings`
backend'i `local`, S3/CDN kipleri açık değil ve `boto3` imaja alınmamış
(`docs/reports/25-t051-depolama-ayarlari.md`). S3 kipi açılırsa bucket
bölgesi m.9 değerlendirmesi gerektirir; bu, kipi açacak görevin ön koşuludur.

---

## 3. Envanter — medya hattında kişisel veri **nerede, kaç tane**

### 3.1 Ölçüm (2026-08-19) [Ö]

Kaynak: `tradehub_core/media/presets.py` `EXCLUDED_DOCTYPES` (8 doctype) +
`EXCLUDED_MEDIA_FIELDS` (13 dosya tutan alan). Sayılar canlı DB'den okundu.

| Doctype · alan | KVKK sınıfı | Dosya referansı | **Public olan** |
|---|---|---:|---:|
| `KYC Verification.identity_document` | m.6 özel nitelikli | 24 | **0** |
| `KYB Verification.identity_document` | m.6 özel nitelikli | 33 | **0** |
| `KYB Verification.bank_account_document` | m.5 | 33 | **0** |
| `KYB Verification.imza_sirkuleri` | m.5 + ticari | 33 | **0** |
| `KYB Verification.ticaret_sicil_gazetesi` | m.5 + ticari | 33 | **0** |
| `KYB Verification.faaliyet_belgesi` | m.5 + ticari | 33 | **0** |
| `KYB Verification.vergi_levhasi` | m.5 + ticari | 33 | **0** |
| `Seller Application.identity_document` | m.6 özel nitelikli | 13 | **0** |
| `Seller Certification.document` | m.5 | 30 | **0** |
| `Seller Verification.document` | m.5 | 1 | **0** |
| `Order.receipt_url` | m.5 (finansal) | 3 | **0** |
| `Payment Transaction.receipt_url` | m.5 (finansal) | 3 | **0** |
| `Data Export Request.file_url` | m.11 çıktısı (her şeyi içerir) | 0 | **0** |
| **TOPLAM** | | **272** | **0** |

Ek olarak eklenti (`File.attached_to_doctype`) yolundan: `KYB Verification`
489, `KYC Verification` 9, `Seller Application` 3, `Order` 3,
`Payment Transaction` 3, `Seller Verification` 1 dosya — **hepsi private** [Ö].

Depo geneli: **5.042 `File` kaydı** — 616 private, 4.426 public [Ö].

### 3.2 Bu tablonun söylediği [T]

**Public sütununun tamamı sıfır.** Bu, 2026-08-19'da yapılan düzeltmelerin
(§4.3) **bugün hâlâ tuttuğunun** bağımsız ölçümüdür: `19-d2-hash-ortusme.md`
o gün bu yollardan 4 dosyayı public bulmuştu.

Sıfır olması *mekanizmanın* güvenli olduğu anlamına **gelmez**. `presets.py`'nin
kendi bakım notu [K] uyarıyor: `EXCLUDED_DOCTYPES`'e yeni bir doctype eklenip
haritaya yazılmazsa, o doctype'ın dosyaları toggle korumasının dışında kalır.
Bugün bu boşluğu izleyen bir ölçüm **yok**; T-133'ün
`media_pii_field_coverage{status="unmapped"}` göstergesi tam bunun içindir ve
**henüz yazanı yoktur** (bkz. `docs/reports/42-t133-gozlemlenebilirlik.md` §5).

### 3.3 EXIF ve dolaylı kişisel veri

Ürün fotoğrafının EXIF bloğu GPS koordinatı (depo/ev adresi), cihaz seri
numarası ve kişi adı taşıyabilir. Mekanizma, ölçümü ve kalan açığı
`docs/security/faz13-gdpr.md` §3-§5'te — burada **tekrarlanmıyor**, çünkü
iki belgede duran aynı sayı, biri güncellenince sessizce yalan söyler.

---

## 4. Olay kaydı — 2026-08-19 kişisel veri bulguları

2026-08-19'da toplam **11 güvenlik açığı kapatıldı**; bunlardan **4'ü doğrudan
kişisel veriyle** ilgiliydi. Aşağıdaki dördü, kaynak raporlarındaki ölçümlerle
birlikte KVKK açısından değerlendiriliyor. Diğer yedisi (hız sınırı kovası,
yetki yükseltme türevleri, path traversal savunmaları vb.) kişisel veriye
doğrudan erişim sağlamadığı için burada değil, kaynak raporlarındadır.

### 4.1 O-1 — `KYC Verification` kiracı izolasyonu yoktu

| | |
|---|---|
| Kaynak | `docs/reports/24-kyc-izolasyon.md` [R] |
| Bulgu | `Seller Owner` rolü, `KYC Verification` üzerinde `permlevel=0, read=1, write=1, if_owner=0`; `hooks.py`'de ne `permission_query_conditions` ne `has_permission` kaydı vardı |
| Etki ölçüsü | **37 kullanıcı**, sistemdeki **24 KYC kaydının tamamını** okuyabiliyor **ve permlevel-0 alanlarını değiştirebiliyordu** |
| Sızan alanlar | `phone`, `address`, `billing_address`, `tax_id`, `identity_document`, `email_field` |
| Kritik nokta | Sızıntı fixture artefaktı **değil**: gerçek bir mağaza sahibi (`demo-seller-01@istoc.demo`), gerçek bir alıcının `KYC-00024` kaydını okudu |
| Kök neden | 2026-06-16 tarihli patch, KYC için **hiç var olmayan** bir korumaya dayanarak yazma izni verdi (docstring KYB için doğru, KYC için yanlıştı) |
| Düzeltme | `permissions.py` +30 satır (KYB kancasının birebir aynası), `hooks.py` +5 satır (0 silme) |
| KVKK | m.12/1 (veri güvenliği) ihlali; m.6 özel nitelikli veri (`identity_document`) etkilendi; m.4/2-ç (ölçülülük) |
| Bugünkü durum [Ö] | KYC kayıt sayısı 24 — ölçümdeki sayıyla aynı; ilgili 24 `identity_document` dosyasının **0'ı public** |

### 4.2 O-2 — `Payment Transaction` çapraz-kiracı okuma (IDOR)

| | |
|---|---|
| Kaynak | `docs/reports/28-faz13-pentest.md` T1 + `29-pentest-duzeltmeleri.md` §3 [R] |
| Bulgu | `Marketplace Seller`'a `read=1, if_owner=0`, kiracı kancası yok — O-1 ile **birebir aynı desen** |
| Sömürü | Sıfırdan yaratılmış, hiçbir kaydı olmayan bir satıcı hesabı, gerçek `sid` çerezi ile gateway üzerinden `GET /api/resource/Payment Transaction/PAY-00001` → **HTTP 200** |
| Sızan alanlar | `buyer` (e-posta), `seller_iban` (**TR71...**), `amount`, `seller_bank_name`, `receipt_url` |
| Zincirleme | Dosya baytları **korundu** — `File.has_permission` `Order` okumasına devrediyor, saldırganda yoktu (pentest T5). **Metadata sızdı, dosya sızmadı** |
| Düzeltme | `permissions.py` +130, `hooks.py` +10 (0 silme); sonra: tekil okuma **403**, liste **boş** |
| Doğrulama | 12 test yeşil + **vacuity: 4 test kırmızıya döndü** [R] |
| KVKK | m.12/1; IBAN + taraf + tutar üçlüsü finansal kişisel veri; m.5 |
| Bugünkü durum [Ö] | `Payment Transaction` 3 kayıt, 3 `receipt_url`, **0'ı public** |

### 4.3 O-3 — Dekontlar public katmanda duruyordu

| | |
|---|---|
| Kaynak | `docs/reports/19-d2-hash-ortusme.md` [R] |
| Bulgu | Hassas `content_hash` paylaşan **44 public dosya** incelendi; 40'ı zararsız (aynı görselin iki kullanımı), **4'ü gerçek sızıntı** |
| Sızıntının niteliği | İçerik değil **yapı**: platformun kendi politikasının "asla public olamaz" dediği yuvada (`Order.receipt_url` / `Payment Transaction.receipt_url`) `is_private=0` |
| Kök neden | `_is_protected_pii` **retroaktif değil** — koruma yalnız `set_level` anında çalışır; baştan public yüklenmiş dosyayı hiçbir kod yolu geri kapatmaz |
| Düzeltme | 4 dosya private'a alındı |
| Kalan risk [T] | Mekanizma canlı: satıcı aynı görseli hem ürün görseli (public) hem KYB eki (private) olarak yükleyebiliyor. Üretimde KYB alanına gerçek kimlik taraması yüklenip aynı dosya ürün görseli olarak kullanılırsa **bugün onu durduran hiçbir şey yok** |
| KVKK | m.12/1; m.4/2-ç |
| Bugünkü durum [Ö] | Aynı iki alanda 6 dosya referansı, **0'ı public** — düzeltme tutuyor |

### 4.4 O-4 — Çapraz-kiracı private dosya erişimi (`find_file_by_url`)

| | |
|---|---|
| Kaynak | `19-d2-hash-ortusme.md` §6 Ö-2 + `28-faz13-pentest.md` T10 + DALGA A [R] |
| Bulgu | Aynı URL'e ait **birden çok `File` satırından herhangi biri** okunabiliyorsa erişim veriliyordu; ilgisiz bir satıcı (`cankayaplastik@istoc.com`) başka satıcının dekontlarından 3'üne ulaşabiliyordu |
| Etki ölçüsü | DALGA A'da **71 çapraz-kiracı dosya erişimi** kapatıldı; daha önceki ölçümde 437 erişimin 318'inin kök nedeni aynı izin satırıydı [R] |
| Düzeltme sonrası doğrulama | Pentest T10: başka satıcı bağlamında `find_file_by_url(...)` → **`None`** (ENGELLENDİ) |
| KVKK | m.12/1; etkilenen dosyalar KYB ekleri ve dekontlar — m.6 kapsamı dahil |
| Test | `tests/test_file_multirow_isolation.py` — 15 test [R] |

### 4.5 Kimlik doğrulamanın kendisinin atlanması (bütünlük ihlali)

Yukarıdaki dördü **gizlilik** ihlaliydi. `29-pentest-duzeltmeleri.md` T2/T3
ayrı bir sınıfı kapattı: `Seller`/`Marketplace Seller` rolü taşıyan kullanıcı
**kendi** KYC/KYB kaydının `status` alanını `Verified` yapabiliyordu — KYC
kaydı okunmuyor, **doğrulanmış sayılıyordu**. `can_buy=1` ve
`Verified Seller` rolü kendi kendine veriliyordu [R].

KVKK açısından bu m.4/2-b (**doğru ve güncel olma**) ihlalidir: kimlik
doğrulama kaydının değeri, onu operatörün doğruladığı varsayımından gelir.
Düzeltme `status` alanını permlevel-1'den **permlevel-4**'e taşıdı + controller
guard'ı ekledi; 14 test, vacuity'de 5 test kırmızıya döndü [R].

### 4.6 İhlal bildirimi değerlendirmesi (m.12/5) — **karar değil, girdi** [T]

| Soru | Teknik cevap |
|---|---|
| Kişisel veri üçüncü kişilerce erişilebilir hâle geldi mi? | **Evet** — O-1, O-2, O-4 için canlı ortamda kanıtlandı |
| Erişim gerçekleşti mi, yoksa yalnız mümkün müydü? | O-1'de gerçek bir kullanıcı bağlamıyla **gerçekleştirildi** (test amaçlı, denetçi tarafından). Gerçek kötü niyetli erişim olup olmadığı **[?] ÖLÇÜLEMEDİ** — bkz. aşağı |
| Geçmişe dönük erişim kaydı var mı? | **Kısmen.** `Authorization Decision Log` medya erişimlerini tutuyor (bugün 2.151 medya olayı, 427'si DENY [Ö]) ama `Payment Transaction` / `KYC Verification` **doctype okumaları** ADL'ye yazılmıyor — yani "kim okudu" sorusu bu iki açık için cevaplanamaz |
| Ortam | Bulgular **geliştirme sitesinde** ölçüldü. Üretim DB'sine erişim bu görevlerde YOKTU; mekanizma (aynı kod, aynı DocPerm satırları, aynı hooks) üretimde de aynıdır, **kayıt sayıları farklıdır** |

**Sonuç [T]:** Bildirim yükümlülüğünün doğup doğmadığı, üretim ortamında bu
izin satırlarının ne kadar süre açık kaldığına ve erişim kayıtlarına bağlıdır.
Bu iki girdinin ikisi de bugün **elde yok**. Veri sorumlusu, üretimde aynı
DocPerm satırlarının varlığını ve süresini tespit etmeden karar veremez;
tespit için gereken sorgu `24-kyc-izolasyon.md` §1'de hazırdır.

**Kalıcı düzeltme önerisi (Ö-K1):** hassas doctype'larda okuma da ADL'ye
yazılmalı (en azından `KYC/KYB Verification`, `Payment Transaction`). Bugün
`audit/log.py::log_pii_reveal` bir `@frappe.whitelist()` ucudur ve **yalnız
admin panelinin maskeli alanı açma akışı** çağırır; depoda sunucu tarafı tek
bir çağrı yeri yok [K] ve canlıda **0 `pii.reveal` kaydı** var [Ö]. REST
üzerinden yapılan okuma hiçbir iz bırakmıyor.

---

## 5. Veri sahibi talebi akışı — bugün ne var, ne yok

### 5.1 Var olan makine [K][Ö]

| Yükümlülük | Kod | Bugünkü kayıt sayısı [Ö] |
|---|---|---|
| Erişim / taşınabilirlik (m.11/1-b,c) | `privacy/data_export.py` + `Data Export Request` doctype | **0 talep** |
| Rıza kaydı | `privacy/consent.py` + `User Consent Log` | **11 kayıt** |
| Silme / anonimleştirme (m.7) | `privacy/account_deletion.py` — 15 günlük süre (`_GRACE_PERIOD_DAYS`) | — |
| Saklama süresi uygulaması (m.4/2-d) | `privacy/data_retention.py` + `Data Retention Policy` doctype | **0 politika satırı** |
| İşleme kaydı (m.12) | `media/audit.py` → `Authorization Decision Log` | **2.151 medya olayı** |

### 5.2 Ölçülen boşluklar — medya, bu akışların DIŞINDA

**Boşluk 1 — dışa aktarım medyayı hiç içermiyor [Ö].**
`_EXPORTABLE_DOCTYPES` **15 doctype** tanımlıyor: `User`, `User Profile`,
`Seller Profile`, `Seller Application`, `Addresses`, `Order`, `Cart`, `RFQ`,
`Listing Review`, `Listing Question`, `Search History`, `User Product View`,
`User Email Preference`, `Buyer Favorite List`, `User Consent Log`.

Bu listede:
* `File` **yok** → ilgili kişinin yüklediği hiçbir belge dışa aktarılmıyor;
* §3'teki 8 hassas doctype'ın yalnız **2'si** var (`Seller Application`,
  `Order`) ve o ikisinde de dosya alanı (`identity_document`, `receipt_url`)
  aktarılan alan listesinde **yok** [K];
* `KYC Verification`, `KYB Verification`, `Payment Transaction`,
  `Seller Certification`, `Seller Verification` hiç yok.

Yani bir ilgili kişi m.11 talebinde bulunursa, **kendi kimlik belgesini ve
dekontunu geri alamaz.**

**Boşluk 2 — hesap silme dosyalara dokunmuyor [Ö].**
`privacy/account_deletion.py` içinde `File`, `attachment`, `identity_document`
geçen **tek bir satır yok** (grep: 0 eşleşme). 12 anonimleştirme fonksiyonu
(kullanıcı, adres, sipariş, yorum, soru, arama geçmişi…) alan bazlıdır. Sonuç:
hesap anonimleştirildikten sonra **kimlik taraması diskte kalır** ve
`File.owner` üzerinden hâlâ o hesaba bağlıdır. KVKK m.7 (yok etme) medya için
karşılanmıyor.

**Boşluk 3 — saklama politikası tablosu boş [Ö].**
`Data Retention Policy` **0 satır**. `run_data_retention_enforcement`
zamanlayıcıya bağlı ama uygulayacak politika yok; yani saklama süresi sınırı
bugün **kodda var, veride yok**.

**Boşluk 4 — talep akışının kendisi hiç koşmamış [Ö].**
`Data Export Request` 0 kayıt. Akış canlıda **hiç denenmedi**; §10'a yazıldı.

### 5.3 Önerilen akış (uygulanmadı) [T]

1. `_EXPORTABLE_DOCTYPES`'e `File` eklenir; filtre `owner = <ilgili kişi>` +
   `attached_to_doctype ∈ EXCLUDED_DOCTYPES`. Dosyanın **kendisi** ZIP'e
   konur, yalnız yolu değil (yol tek başına m.11'i karşılamaz).
2. Aktarımdan önce `media/audit.py::ACTION_EXPORT` yazılır — veri sunucuyu
   terk ettiği için bu, denetimin zorunlu satırıdır [K].
3. `account_deletion.py`'ye medya adımı: `EXCLUDED_MEDIA_FIELDS` haritasındaki
   alanlardan gelen dosyalar `media/trash.py` → `archive.py` üzerinden
   silinir. Doğrudan `os.unlink` **yasak**: silme de denetlenmeli.
4. `Data Retention Policy` satırları tohumlanır; medya için taban öneri:
   KYC/KYB belgeleri ilişki bitiminden itibaren 10 yıl (VUK/TTK saklama
   yükümlülüğü ile çakışma **[?] hukuk danışmanına sorulmalı**), dekont 10
   yıl, RUM örneklemi 30 gün (`delivery/rum.py::DOCTYPE_DESIGN`).

---

## 6. İşleme kaydı ve denetim izi (m.12)

### 6.1 Bugünkü kapsam [Ö]

`media/audit.py` **20 eylem** tanımlıyor (bu görevde 19'dan 20'ye çıktı, bkz.
§6.2). Canlı ADL'de medya olayı dağılımı:

| Eylem | Kayıt | Eylem | Kayıt |
|---|---:|---|---:|
| `media.upload` | 877 | `media.quarantine` | 81 |
| `media.access_denied` | 375 | `media.scope_denied` | 51 |
| `media.optimize` | 244 | `media.signed_access` | 48 |
| `media.level_changed` | 188 | `media.quarantine_release` | 36 |
| `media.storage_settings_changed` | 110 | `media.delete` | 16 |
| `media.scan` | 108 | `media.restore` | 11 |
| `media.export` | 2 | `media.reclaim` / `media.backup` / `media.release` | 1 + 1 + 1 |

**Toplam 2.151 medya olayı** (ADL'nin tamamı 2.716), **427'si DENY**,
**434 kayıtta hedef maskeli** (`masked:<sha256[:12]>`) — yani hassas dosya
kimlikleri denetim penceresinden geri sızmıyor.

**Hiç kayıt üretmemiş 4 eylem:** `media.trash`, `media.untrash`,
`media.purge_trash`, `media.purge_archive`. Bu, kodun yazmadığı anlamına
gelmez — bu sitede çöp/arşiv akışının **hiç koşmadığı** anlamına gelir. İkisi
ayrı şeydir ve ayrımı bugün ölçen bir sinyal yok; T-133'ün
`media_audit_event_total` sayacı ve `MediaAuditWritesStopped` alarmı tam bunun
içindir.

### 6.2 Bu görevde kapatılan açık — 110 kayıt görünmez duruyordu [Ö]

`media_storage_settings.py:116` bir sabiti kendi dosyasında tanımlamış ama
`media/audit.py::MEDIA_ACTIONS` tuple'ına ekleyememişti (dosya kapsamı
dışıydı) ve sonucu kendi yorumunda yazmıştı: kayıtlar ADL'ye **yazılıyor**,
panelin medya denetimi ekranı `MEDIA_ACTIONS` ile süzdüğü için **görünmüyor**.

Ölçüldü — düzeltmeden önce ve sonra, aynı çağrı (`audit.facets()`):

```
ONCE   : tanimli_action=19   panelde_gorunen=2041   settings_changed=0
SONRA  : tanimli_action=20   panelde_gorunen=2151   settings_changed=110
```

**110 ayar değişikliği kaydı denetim ekranına geri geldi.** T-134'ün
"silme/**ayar**/onay/retention/sır erişimi audit'e yazılıyor" kriterinin
"ayar" ayağı, yazılıyordu ama **okunamıyordu**; artık okunuyor.

> Sabit `_HIGH_SEVERITY_ACTIONS`'a bilinçli olarak **eklenmedi**: aynı eylem
> adını gerçek ayar değişikliği ve bağlantı testi paylaşıyor
> (`media_storage_settings.py:428`); testler sık koşar ve hepsini HIGH
> işaretlemek severity filtresini işe yaramaz hâle getirirdi. Başarısız test
> ve reddedilen değişiklik zaten `allowed=False` ile HIGH'a düşüyor.

### 6.3 Denetim izinin bütünlüğü [K]

ADL hash zinciri tutuyor (`prev_hash` / `entry_hash`) ve `media/audit.py`
`report()` her kaydın bütünlüğünü yeniden hesaplayarak doğruluyor. `intact`
alanı üç değer alır: `True` (doğrulandı), `False` (**kurcalanmış**), `None`
(**doğrulanamadı** — `entry_hash` boş). Üçünün ayrı tutulması önemlidir:
"doğrulanamadı"yı "kurcalanmış" diye göstermek, denetim ekranında
üretilebilecek en yanıltıcı çıktıdır.

### 6.4 Log'da PII

`observability/logging.py` maskelemeyi iki yoldan tetikler (anahtar adı + değer
deseni) ve **`media/audit.py` ile aynı parmak izi biçimini** üretir
(`sha256[:12]`, `masked:` öneki). Aynı olmak zorunda: ADL kaydı ile log satırı
aynı dosyayı farklı kimlikle gösterseydi, bir ihlal incelemesinde ikisini
eşleştirmek imkânsız olurdu. Ayrışma `tests/test_observability.py` ile düşer.

**Ölçüm noktalarında da aynı kural:** `observability/instrument.py`'nin hiçbir
kayıt fonksiyonu dosya adı, URL, kullanıcı ya da kiracı yazmaz; hata yolunda
ilk argümanın (bir dosya yolu) etikete yazılmadığı ayrı bir testle düşürülür
(`test_hata_yolunda_dosya_yolu_etikete_yazilmaz`).

---

## 7. Aydınlatma metni — medya bölümü (taslak)

> **Uygulanmadı.** Aşağıdaki metin storefront'un aydınlatma sayfasına
> eklenmek üzere hazırlanmış TASLAKTIR; `tradehubfront` bu görevin kapsamı
> dışındadır ve metin hukuk onayından geçmemiştir.

**Yüklediğiniz görsel ve belgeler hakkında**

- **Hangi veriler:** Ürün görselleri, mağaza görselleri, kimlik belgesi
  taraması, imza sirküleri, ticaret sicil gazetesi, faaliyet belgesi, vergi
  levhası, banka hesap belgesi ve ödeme dekontları.
- **Neden işleniyor:** Kimlik ve yetki doğrulaması (KVKK m.5/2-ç, m.6/3),
  sözleşmenin kurulması ve ifası (m.5/2-c), yasal saklama yükümlülükleri
  (m.5/2-a).
- **Nasıl korunuyor:** Kimlik ve finansal belgeler **erişim kısıtlı** alanda
  saklanır ve bağlantıları süreli imzalı bağlantı ile verilir; herkese açık
  ürün görsellerinden ayrı bir katmandadır. İşlenen görsellerin konum (GPS)
  ve cihaz bilgisi işleme sırasında düşürülür. Her yükleme ve silme işlemi
  denetim kaydına yazılır.
  *(Uyarı: "GPS düşürülür" cümlesi bugün TÜM dosyalar için doğru DEĞİL —
  `faz13-gdpr.md` §5 ölçtü: temizlik optimizasyon adımına bağlı ve
  optimizasyon dosyaların önemli bir kısmını atlıyor. Metin yayımlanmadan
  önce ya o açık kapatılmalı ya da cümle koşullu yazılmalıdır. "Her
  görüntüleme denetlenir" ifadesi de bugün karşılanmıyor — §4.6.)*
- **Ne kadar süre:** Kimlik ve mali belgeler yasal saklama süresi boyunca;
  ürün görselleri ilanın yayından kalkmasından sonra 30 gün çöp kutusunda,
  ardından arşiv ve kalıcı silme akışına girer.
- **Haklarınız (m.11):** Yüklediğiniz belgelerin bir kopyasını isteyebilir,
  düzeltilmesini veya silinmesini talep edebilirsiniz. Talepler hesap
  ayarlarındaki **Verilerimi indir** akışı üzerinden alınır.
  *(Bugün bu akış medyayı kapsamıyor — §5.2 Boşluk 1. Metin, boşluk
  kapatılmadan yayımlanmamalıdır; aksi hâlde karşılanamayan bir taahhüt
  verilmiş olur.)*

---

## 8. `Media Audit Log` DocType — **tasarım, kurulmadı**

`36-dogrulama-faz12-14.md` T-134'ü kısmi sayarken `Media Audit Log` DocType'ının
yokluğunu gerekçe gösterdi. Bu görevde DocType **kurulmadı** — ve kurulmaması
gerektiği görüşündeyiz. Gerekçe ve tasarım
`docs/reports/42-t133-gozlemlenebilirlik.md` §7'de; özeti:

Medya denetimi bugün `Authorization Decision Log` üzerinde **çalışıyor**
(2.151 kayıt, hash zinciri, maskeleme, 20 eylem). İkinci bir tablo açmak
CLAUDE.md §4'ün "DocType bloat" kuralına aykırı olur ve hash zincirini ikiye
böler. Eksik olan tablo değil, ADL üzerinde **eksik kalan üç alan**: hassas
doctype okumalarının kaydı (§4.6 Ö-K1), veri sahibi talebi olayları ve
retention uygulama kayıtları.

---

## 9. Ölçüm betikleri

Ölçümler dört geçici betikle yapıldı; konteynere `docker cp` ile taşındı,
`../env/bin/python` ile koşturuldu ve **hiçbiri veri yazmadı** (yalnız
`SELECT` / `frappe.db.count`). Betikler `/tmp` altındaydı ve koşum sonunda
silindi. Yeniden üretmek için gereken sorgular:

```python
# Envanter (§3.1)
for dt, alanlar in presets.EXCLUDED_MEDIA_FIELDS.items():
    for alan in alanlar:
        urls = frappe.db.sql(f"SELECT `{alan}` FROM `tab{dt}` WHERE `{alan}` != ''")
        frappe.db.count("File", {"file_url": ["in", urls], "is_private": 0})

# Denetim dağılımı (§6.1)
frappe.db.sql("SELECT action, COUNT(*) FROM `tabAuthorization Decision Log` "
              "WHERE action LIKE 'media.%' GROUP BY action")

# Panelde görünen (§6.2)
from tradehub_core.media import audit; audit.facets()
```

> Yukarıdaki ilk parçadaki f-string SQL **ölçüm betiğine** aittir; alan ve
> doctype adları koddaki sabit haritadan gelir, kullanıcı girdisinden değil.
> Üretim koduna bu biçimde girmemelidir (`anti-patterns.md` §11).

---

## 10. ÖLÇÜLEMEYENLER

Bu bölüm bilinçli olarak uzun. "Ölçtük ve temiz" ile "bakmadık" arasındaki
farkı belgelemek, bu belgenin en önemli işlerinden biri.

| # | Ne ölçülemedi | Neden | Gereken |
|---|---|---|---|
| 1 | **Üretim ortamındaki durum** | Üretim DB'sine erişim yok | Aynı sorguların üretimde koşturulması — §4.6 kararı buna bağlı |
| 2 | **Açıkların üretimde ne kadar süre açık kaldığı** | DocPerm değişiklik geçmişi tutulmuyor | `Custom DocPerm.modified` + patch tarihleri karşılaştırması |
| 3 | **Gerçek (kötü niyetli) erişim olup olmadığı** | `Payment Transaction` / `KYC Verification` okumaları ADL'ye yazılmıyor | Ö-K1 uygulanmadan geçmişe dönük cevap YOK |
| 4 | **Veri sahibi talebi akışının uçtan uca çalışması** | `Data Export Request` 0 kayıt — akış hiç koşmadı | Bir test talebi + üretilen ZIP'in içerik denetimi |
| 5 | **Hesap silmenin medyayı bıraktığının canlı kanıtı** | Kod okundu (0 `File` referansı), silme akışı koşulmadı | Anonimleştirme sonrası `File` sayımı |
| 6 | **`unmapped` PII alanı var mı** | Ölçen kod yok; `media_pii_field_coverage` göstergesinin yazanı yok | T-133 toplayıcı işi (rapor 42 §5) |
| 7 | **EXIF temizliğinin bugünkü kapsamı** | `faz13-gdpr.md` §5 ölçtü: temizlik optimizasyona bağlı ve optimizasyon çoğu dosyayı atlıyor | O belgedeki Ö-2 önerisi |
| 8 | **Saklama sürelerinin hukuki doğruluğu** | Hukuk sorusu, teknik ölçüm değil | Danışman onayı |

---

## 11. Açık maddeler — sahibi ve tek adımı

| # | Madde | KVKK | Şiddet | Tek adım |
|---|---|---|---|---|
| **Ö-K1** | Hassas doctype okumaları denetime yazılmıyor | m.12 | **YÜKSEK** | `KYC/KYB Verification`, `Payment Transaction` için `has_permission` içinde `log_pii_reveal` çağrısı |
| **Ö-K2** | Dışa aktarım medyayı içermiyor | m.11/1-b,c | **YÜKSEK** | `_EXPORTABLE_DOCTYPES`'e `File` + hassas 5 doctype |
| **Ö-K3** | Hesap silme dosyaları bırakıyor | m.7 | **YÜKSEK** | `account_deletion.py`'ye `media/trash.py` üzerinden medya adımı |
| **Ö-K4** | `Data Retention Policy` boş | m.4/2-d | ORTA | Politika satırlarının tohumlanması (patch) |
| **Ö-K5** | `_is_protected_pii` retroaktif değil | m.12 | ORTA | Periyodik tarayıcı + `media_pii_unprotected_files` göstergesini yazan iş |
| **Ö-K6** | Aydınlatma metni yayımlanmadı | m.10 | ORTA | §7 taslağı + hukuk onayı + storefront sayfası |
| **Ö-K7** | PII alan kapsamı ölçülmüyor | m.12 | ORTA | `media_pii_field_coverage` toplayıcısı (rapor 42 §5) |

---

## 12. Sonuç

Medya hattında kişisel veri **nerede olduğu bilinen** 13 alanda, 272 dosya
referansında duruyor ve bugün **hiçbiri public değil** [Ö]. 2026-08-19'da
kapatılan dört kişisel veri açığının dördü de bağımsız ölçümle **kapalı**
doğrulandı.

Karşılanan: veri güvenliği (m.12/1) medya katmanında, işleme kaydı (m.12) 20
eylemle ve hash zinciriyle, veri minimizasyonu (m.4/2-ç) EXIF tarafında
kısmen, özel nitelikli veriye ek koruma (m.6) private katman + imzalı bağlantı
ile.

Karşılanmayan ve bu belgenin en net çıktısı: **ilgili kişinin hakları
medyaya ulaşmıyor.** m.11 dışa aktarımı dosyaları içermiyor, m.7 silme
dosyalara dokunmuyor, m.4/2-d saklama politikası tablosu boş. Üçü de kod
gerektiriyor, üçü de bu görevin dosya kapsamı dışında — üçü de §11'de sahibi
ve tek adımıyla yazılı.
