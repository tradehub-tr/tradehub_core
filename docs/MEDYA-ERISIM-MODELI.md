# Medya Erişim Modeli — public / private + imzalı erişim

**TUR-126** · Faz 1 · 2026-08-14

Bu belge medya varlıklarının kime, nasıl açık olduğunu tanımlar: public/private
davranışı, yetkilendirme (platform RBAC = "Auth 2.0"), private dosyaların güvenli
paylaşımı (imzalı süreli URL) ve erişim-seviyesi değişikliğinin denetimi.
İsimlendirme [[MEDYA-DEPOLAMA-STANDARDI]] (TUR-130), enumeration önleme TUR-141.

---

## 1. Karar özeti

| Konu | Karar |
|---|---|
| **Public medya** | `/files/` — anonim, nginx doğrudan servis (ürün görselleri). Hash-isim + noindex + rate-limit (TUR-141) |
| **Private medya** | `/private/files/` — Frappe permission: Guest→403, `has_permission(read)` → owner / DocShare / bağlı-doc delegasyonu. X-Accel-Redirect internal nginx |
| **Yetkilendirme ("Auth 2.0")** | Platform RBAC: rol + capability + tenant (`auth_guards`, `permission_resolver`, `seller_capabilities`, `tenant`). Ayrı bir OAuth değil |
| **İmzalı süreli URL** | **EKLENECEK** — private dosyayı girişsiz paylaşmak için HMAC-imzalı, süreli link (Frappe `verified_command`) |
| **Erişim-seviyesi toggle** | **EKLENECEK** — süper-admin public↔private çevirebilir; KYB/KYC muaf; her değişim audit |
| **Denetim** | Erişim kararları + seviye değişimleri `Authorization Decision Log`'a (media.access_denied / media.level_changed) |

---

## 2. Mevcut model (doğrulanmış, korunuyor)

### 2.1 Public
`public/files/` altındaki dosyalar nginx tarafından **doğrudan, kimlik doğrulamasız**
servis edilir. Ürün görselleri, mağaza logoları için bilinçli — bunlar zaten public
ürün sayfasında görünür. Sertleştirme (TUR-141): içerik-hash isim (tahmin edilemez)
+ `X-Robots-Tag: noindex` + `limit_req` rate-limit.

### 2.2 Private
`private/files/` altındaki dosyalar Frappe permission katmanından geçer
(`download_private_file`, `frappe/utils/response.py`):

1. `frappe.session.user == "Guest"` → **403** (canlı doğrulandı).
2. `find_file_by_url(path)` → dosyanın `is_downloadable()` → `has_permission("read")`.
3. Kurallar (`File.has_permission`): Administrator → izin; `owner == user` → izin;
   explicit DocShare → izin; aksi halde **bağlı dokümana delege** (`attached_to_doctype`
   → `ref_doc.has_permission("read")`); hiçbiri değilse **reddet**.
4. Erişim `X-Accel-Redirect` ile internal nginx location'a yönlenir — private dizin
   web'den **hiç doğrudan erişilemez**.

`tradehub_core`'da `File` için custom `has_permission` YOK → Frappe varsayılanı +
bağlı-doc delegasyonu geçerli (Listing, KYB Verification, Order, vb. kendi
permission'ları belirler). Private dağılımı: KYB 489, owner-only 71, Bulk Import 29,
KYC 9, Brand 4, Seller Application 3.

### 2.3 "Auth 2.0" ne demek
Platformun yetki sistemi — ayrı bir OAuth 2.0 sunucusu değil:
`utils/auth_guards.py` (endpoint kapıları), `permission_resolver.py`,
`seller_capabilities.py` (capability grant), `tenant.py` (tenant izolasyonu). Medya
erişimi bu sistemin `has_permission` + capability kararlarına yaslanır.

---

## 3. YENİ: İmzalı süreli URL (private paylaşım)

### 3.1 İhtiyaç
Private dosya bugün **sadece oturumla** erişilebiliyor. Bir KYB belgesini giriş
yapmamış bir dış denetçiyle/paydaşla paylaşmak mümkün değil. Çözüm: **süreli,
imzalı** bir link — token doğruysa ve süresi geçmediyse dosya servis edilir.

### 3.2 Tasarım (Frappe `verified_command` üzerine)
- **İmza primitifi:** `frappe.utils.verified_command.get_signed_params` /
  `verify_request` — site secret (`conf["secret"]` ya da `encryption_key`) ile HMAC.
  Kendi kripto YAZILMAZ.
- **İmza endpoint'i** `media_access.get_signed_url(file_url, ttl_seconds=900)`:
  - Çağıranın o dosyaya **read yetkisi olduğunu** doğrular (`File.has_permission`)
    — yetkin olmadığın dosyaya imzalı link ÜRETEMEZSİN.
  - Params: `file=<file_url>&exp=<now+ttl>`; `get_signed_params` ile imzalanır.
  - Döner: `/api/method/tradehub_core.api.media_access.download?file=..&exp=..&_signature=..`
  - Varsayılan TTL 15dk, üst sınır (ör. 24s) sabit.
- **İndirme handler'ı** `media_access.download()` (`allow_guest=True`):
  1. `verify_request()` — HMAC geçerli mi (imza `file`+`exp`'i kapsar, oynanamaz).
  2. `exp > now` — süre dolmadı mı (exp imzalı olduğu için uzatılamaz).
  3. `file_url` gerçekten `/private/files/` altında mı (path traversal + public'i imzalama).
  4. Dosyayı stream et (X-Accel-Redirect ile, response.py deseninde).
  - Her indirme audit'e `media.signed_access` olarak yazılır (kim, hangi dosya, ne zaman).

### 3.3 Güvenlik kuralları
- İmza yalnız **imza anındaki yetkilendirmeyi** taşır — link'i alan, süre boyunca o
  dosyaya erişir (bilinçli: paylaşım özelliği). Süre kısa tutulur.
- İmzalanacak dosya `/private/files/` dışıysa reddedilir (public zaten açık; imza gereksiz).
- EXCLUDED_DOCTYPES (KYB/KYC) için imzalı link üretimi **capability-gated** olabilir
  (yalnız yetkili roller PII belgesi paylaşabilsin) — implementasyon kararı.

---

## 4. YENİ: Erişim-seviyesi toggle (public ↔ private)

### 4.1 İhtiyaç
Bir medyanın erişim seviyesi bugün upload'ta sabitlenir, sonradan değişmez.
Süper-admin bir görseli private↔public çevirebilmeli (yanlış yüklenen bir belgeyi
private'a almak; bir tanıtım görselini public yapmak).

### 4.2 Tasarım
- **Endpoint** `media_admin.set_access_level(file_url, is_private)`:
  - `_guard()` — yalnız `System Manager` / `Marketplace Admin`.
  - **KYB/KYC/EXCLUDED_DOCTYPES muaf:** bu doctype'lara bağlı dosya **public
    yapılamaz** (PII sızıntısı koruması) → `frappe.throw`.
  - Dosyayı fiziksel taşı: `private/files/<ab>/` ↔ `public/files/<ab>/` (shard korunur),
    `file_url` prefix güncellenir.
  - **Referans güncelleme:** `media/refs.py`'ın bulma altyapısı üzerine — dosyayı
    kullanan tüm referanslar (`Listing.primary_image` vb., `_WRITABLE` allow-list)
    yeni URL'e güncellenir. Atomik: taşıma + referans + `File.is_private` tek transaction.
  - **Audit:** her değişim `media.level_changed` (kim, dosya, eski→yeni seviye, zaman)
    → denetlenebilir (kabul kriteri).
- **Panel:** MediaOptimize/MediaAudit ekranına "erişim seviyesi" göstergesi + (süper-admin)
  değiştirme aksiyonu; onay adımı (geri alınamaz uyarısı).

### 4.3 Riskler
- Referans güncellemesi eksik kalırsa kırık görsel → `refs.find()` ile önce etki
  raporu, sonra atomik uygulama. Referanssız (henüz bağlanmamış) dosyada risk yok.
- Public→private çevirince eski public URL 404 olur (kasıtlı — artık gizli). Cache/CDN
  purge notu.

---

## 5. Kabul kriterleri karşılığı

| Kriter | Durum |
|---|---|
| Public/private davranışları açıkça tanımlı | ✅ §2 (mevcut, doğrulanmış) |
| Yetkisiz erişim engelli | ✅ §2.2 (canlı 403 doğrulandı) |
| Private için güvenli erişim stratejisi | ✅ §2.2 (session) + §3 (imzalı süreli URL) |
| Erişim seviyesi değişiklikleri denetlenebilir | ✅ §4.2 (media.level_changed audit) |

---

## Ek — 21 Ağu 2026: tarama akışıyla kesişim

`set_access_level` artık taşımadan önce **AV durumunu** sorar
(`av.in_quarantine` / `av.in_hold`). Gerekçe: tarama akışı (TUR-125) dosyayı
fiziksel olarak canlı ağacın dışına taşıyabiliyor (`media_scan_hold`,
`media_quarantine`); bu kontrol olmadan `isfile` "diskte bulunamadı" diyordu —
dosya vardı, başka kökteydi; mesaj yanıltıcıydı ve iki mekanizma aynı dosyayı
taşımak için yarışıyordu. Davranış: tarama bitip dosya yerine dönene (ya da
karantinadan çıkarılana) kadar seviye değişmez; red `media.level_changed`
olayıyla (`allowed=False`, `reason=av_state_blocks_move`, adres maskeli)
denetime yazılır. ADR-0023 "kavram başına tek sahip": tarama durumu AV
modülünündür, erişim modülü onu okur.
