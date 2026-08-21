# Medya Depolama Yapısı ve İsimlendirme Standardı

**TUR-130** · Faz 1 · 2026-08-14

Bu belge medya dosyalarının **nereye** ve **hangi adla** yazıldığını tanımlar:
depolama hiyerarşisi, dosya adı üretimi, çakışma davranışı, türev dosya yeri ve
ölçeklenme stratejisi. İsimlendirme kararı [[MEDYA-YUKLEME-SOZLESMESI]] (TUR-123)
ve enumeration önleme (TUR-141) ile birlikte okunur.

---

## 1. Karar özeti (tek tabloda)

| Konu | Karar |
|---|---|
| **Public medya kökü** | `<site>/public/files/` — nginx doğrudan servis eder |
| **Private medya kökü** | `<site>/private/files/` — Frappe permission katmanından geçer |
| **Dosya adı** | `<sha256(içerik)[:32]>.<uzantı>` — içerik-adresli, tahmin-edilemez |
| **Shard** | Hash-prefix: `files/<ab>/<hash>.<ext>` (adın ilk 2 hex'i alt dizin) |
| **Çakışma** | İçerik-adresli ad → aynı içerik = aynı yol → doğal dedup |
| **Türev** | Ayrı kökte, asset+sürüm adresli: `/files/media/{asset}/{version_hash}/{profil}-{genişlik}.{ext}` (`pipeline_bridge._write_rendition_file`); video yerinde üzerine yazılır, suffix yok |
| **Eski isimler** | Verbatim (`0505.jpg`) idi → retro-rename ile içerik-adresli ada taşınır, 301 köprüsü ile (§7) |

---

## 2. Neden bu belge yazıldı — ölçülen risk

Bugünkü yapı **düz** (tek dizin, alt dizin yok):

```
public/files/     → 2.858 dosya (ürün görselleri, public medya)  [DÜZ]
private/files/    → 192 dosya  (KYB/KYC belgeleri)               [DÜZ]
```

İki somut risk:

1. **Ölçek — dosya sistemi yavaşlaması.** Tek dizinde milyonlarca dosya
   olduğunda `readdir`/`stat`/`ls` doğrusal yavaşlar (ext4/xfs dizin indeksine
   rağmen backup, senkron, listeleme araçları etkilenir). İstoç ölçeğinde
   yüzlerce satıcı × yüzlerce ürün × birden çok görsel = milyon mertebesi
   erişilebilir.
2. **Tahmin edilebilirlik.** Eski isimlerin %50'si (`0505.jpg`) URL'den toplu
   çekilebiliyordu. İçerik-hash isimlendirme (WP4/TUR-141) bunu kapattı; bu
   belge o kararı depolama düzeyinde standartlaştırır.

---

## 3. Depolama hiyerarşisi

### 3.1 Ana kökler

| Kök | İçerik | Erişim |
|---|---|---|
| `public/files/` | Ürün görselleri, mağaza logoları, public medya | Anonim (nginx doğrudan) |
| `private/files/` | KYB/KYC belgeleri, sertifikalar, RFQ ekleri | Permission-gated (Frappe) |

### 3.2 Medya-özel private kökler (mevcut, korunuyor)

| Kök | Sabit | İşi |
|---|---|---|
| `private/image_originals/` | `presets.ARCHIVE_DIRNAME` | Optimize edilenlerin arşiv orijinali (30 gün geri-alma) |
| `private/media_trash/` | `trash.TRASH_DIRNAME` | Soft-delete (30 gün retention) |
| `private/media-backups/` | `backup.ROOT_DIRNAME` | İçerik-adresli yedek: `blobs/<xx>/<sha256>` + manifest |

Bu üç kök `File` kaydı ÜRETMEZ (kotaya girmez) ve web'den erişilemez. Public
medyanın kota + servis düzlemi yalnız `public/files/` ve `private/files/`'tir.

---

## 4. İsimlendirme standardı

### 4.1 Kural

Yeni her yükleme:

```
<sha256(içerik)[:32]>.<uzantı>
```

- **32 hex** (128-bit) — tahmin edilemez (enumeration önleme).
- **İçerik-adresli** — aynı içerik her zaman aynı adı üretir → doğal dedup.
- **Uzantı korunur** — nginx MIME/cache ve `.webp/.mp4` uzantı-bazlı davranış çalışır.
- **Görünen ad (`File.file_name`) değişebilir** — kullanıcı-dostu ad ayrı tutulur;
  yalnız disk adı + `file_url` hash'lidir.

Uygulama: `media/naming.py:write_file_hashed` (Frappe `write_file` hook'u, her
iki upload yolunu da destekler — bkz. modül docstring'i).

### 4.2 Shard — hash-prefix

Fiziksel yol adın ilk 2 hex karakterine göre shard'lanır:

```
/files/<ab>/<abcdef...>.webp        (ab = hash[:2])
/private/files/<ab>/<abcdef...>.pdf
```

- **256 alt dizin** (`00`–`ff`) → dosyalar eşit dağılır; tek dizinde milyon
  yerine ~dizin başına birkaç bin dosya.
- **İçerik-adresli isimle doğal uyum** — hash'in kendisi shard anahtarı, ekstra
  metadata gerekmez.
- **Yedek blob'ları zaten böyle** (`media-backups/blobs/<xx>/`) — tutarlı desen.
- **Dedup korunur** — aynı içerik aynı hash → aynı shard → aynı yol.

### 4.3 Çakışma davranışı

İçerik-adresli isimlendirme çakışmayı **yapısal olarak** çözer:

- Aynı içerik iki kez yüklenirse → aynı `file_url` → fiziksel tek dosya.
  (Frappe'nin `content_hash` dedup'ı da bunu insert öncesi yakalar.)
- Farklı içerik → farklı hash → farklı yol. SHA-256 çakışması pratikte imkânsız.
- Rastgele suffix / sayaç GEREKMEZ (eski Frappe `get_file_name` deseni).

---

## 5. Türev dosyalar (WebP variant, thumbnail, video rendition)

Türevler **ayrı kökte, asset + sürüm hash'i adresli** dururlar — orijinalin
yanında değil:

```
/files/ab/<hash>.jpg                                    ← orijinal (içerik-adresli, shard)
/files/media/<asset>/<version_hash>/thumb-320.webp     ← thumbnail
/files/media/<asset>/<version_hash>/card-768.webp      ← profil × genişlik
/files/media/<asset>/<version_hash>/hls/master.m3u8    ← video (HLS); tek dosya video yerinde üzerine yazılır
```

Gerekçe:
- **Türev adresi orijinalin yolundan bağımsız** (asset adı + sürüm hash'i) —
  orijinal yeniden adlandırılsa (§7) türevler kırılmaz.
- **Eski shard-yanı türevler** (`/files/xx/<hash>.webp`) hâlâ vardır ve
  `Media Rendition.file_url` üzerinden okunmaya devam eder — geriye dönük
  uyumluluk için taşınmadılar.
- **Üretim:** `pipeline_bridge._write_rendition_file`, `dedup.rendition_path`.

> Türevlerin **üretimi** ve yaşam döngüsü TUR-297 (versioning) / TUR-128
> (WebP+srcset) işidir. Bu belge yalnız KONUMU tanımlar.

---

## 6. Geriye dönük uyumluluk

- **Mevcut `file_url`'ler KIRILMAZ.** Shard + hash yalnız YENİ yüklemelere uygulanır.
- Mevcut düz `/files/0505.jpg` yolları çalışmaya devam eder (nginx her iki deseni
  de servis eder: `/files/<ad>` ve `/files/<ab>/<ad>`).
- Referanslar (`Listing.primary_image` vb.) `file_url`'i denormalize string olarak
  tutar; yeni yüklemeler zaten sharded URL kaydeder, eski referanslar dokunulmaz.

---

## 7. Retro-rename (uygulandı)

Eski isimlerin migration'ı **uygulandı ve test edildi**. Spec:
`docs/superpowers/specs/2026-08-21-medya-retro-rename-design.md`; plan:
`docs/superpowers/plans/2026-08-21-medya-retro-rename.md`.

- **Araç:** `tradehub_core/media/retro_rename.py`
  - `plan()` — salt-okunur rapor (referans taraması, gömülü/orphan sayımı).
  - `run_job` — queue job: dosya başına `os.replace` → tüm `tabFile.file_url`
    paylaşım satırları güncellenir → `refs.retarget` (artık gömülü JSON/HTML
    referanslar dahil) → `Media URL Redirect` satırı yazılır (`source_url,
    target_url, job_key, expires_at, file_rows, file_names`) → commit. Hata
    halinde rollback + dosya geri taşınır. Batch sınırlarında durdurma bayrağı;
    `ERROR_RATE_STOP = 0.02`.
  - `run_rollback(job_key, rollback_key)` — kimlik tabanlı geri alma.
- **301 köprüsü:** `tradehub_core/media/redirect_renderer.py::MediaRedirectRenderer`
  — `page_renderer` hook'u üzerinden tek indeksli sorgu. `Website Route Redirect`
  bilinçli olarak KULLANILMADI (her istekte tüm kuralları regex ile tarar).
  `REDIRECT_TTL_DAYS = 90` — günlük cron (`retro_rename.purge_expired_redirects`)
  süresi dolan satırları temizler; 90 gün sonra eski URL 404 döner.
- **Admin API** (System Manager): `media_admin.retro_rename_count /
  retro_rename_plan / start_retro_rename / get_retro_rename_status /
  stop_retro_rename / rollback_retro_rename / retro_rename_history`. Admin panel
  kartı **yayında**: Sistem → Medya Optimizasyonu → "Eski adlandırma" kartı
  (önizle / onayla / ilerleme / durdur / geri al). Yalnız System Manager görür.
- **Lokal ölçüm (2026-08-21):** 2.843 distinct eski public URL / 4.319 `tabFile`
  satırı; tam `plan()` ≈ 20 sn; 303 gömülü referans, 28 sipariş-geçmişi
  (salt-okunur) referansı, 389 orphan.

Bu arada nginx sertleştirmesi (TUR-141: `/files/`'a `X-Robots-Tag: noindex` +
`limit_req`) eski isimlerin toplu çekilmesini pratikte zorlaştırır.

### 7.1 Koşu öncesi zorunlu adımlar (alpha/prod)

Aşağıdakiler **öneri değil**; atlanırsa ya araç hiç çalışmaz ya da geri
alınamayan veri kaybı olur.

1. **`bench migrate`** — `Media URL Redirect` doctype'ı ve `file_names` alanı
   olmadan `run_job` ilk dosyada patlar.
2. **İmaj rebuild + restart** — backend ve panel imajları kodu içeriyor (bind
   mount YOK). Rebuild sonrası `backend`, `queue-long`, `queue-short`,
   `scheduler`, `frappe-frontend` yeniden başlatılmalı; iş `long` kuyruğunda
   koşuyor, worker restart edilmezse ESKİ kodu çalıştırır.
3. **M-A arşivi ÖNCE boşaltılmalı.** `media/archive.py` undo-arşivi dosyaları
   `file_url` ile adresler (`relative_path_for`) ve retro-rename bu arşivi
   TAŞIMAZ. Taşınan bir dosyanın 30 günlük "orijinale dön" penceresi koşudan
   sonra sessizce kaybolur. Bu yüzden koşudan ÖNCE `archive.purge_expired()`
   koşulmalı ve `archive.usage_bytes()` 0'a yakın olmalı; değilse önce bekleyen
   geri-almalar tamamlanmalı.
4. **`bench --site <site> clear-website-cache`** — koşudan ve geri almadan
   SONRA. Kod `_clear_404_cache()` ile `website_404`'ü zaten siliyor (I1); bu
   ek emniyet, sayfa/route önbelleklerini de temizler.
5. **Edge önbelleği: geri almadan sonra ~5 dk pencere.** Gateway `/files/`
   yanıtlarına `$thc_media_cache` ile ~5 dk `Cache-Control` veriyor
   (`docker/nginx/gateway.conf`), yani 301'ler edge'de tutulur. Geri alma
   sonrasında eski adres 5 dk daha yeni adrese yönlenebilir — beklenen davranış,
   panik yok.
6. **Geri alma DURDURULAMAZ ve süreye tabidir.** `run_rollback`'in durdurma
   bayrağı yoktur; başlatıldı mı biter. `REDIRECT_TTL_DAYS = 90` dolduğunda
   günlük cron yönlendirme satırlarını siler — **satırlar silindikten sonra geri
   alma mümkün değildir**.
7. **Worker ölürse kilit takılı kalır.** `tradehub:retro_rename:active`
   anahtarı `PROGRESS_TTL` (1 saat) ile yazılıyor; worker `finally`'ye
   ulaşmadan ölürse panel 1 saate kadar "zaten çalışan iş var" der. Elle açma:
   `frappe.cache.delete_value("tradehub:retro_rename:active")`.
8. **`tabFile` satırı olmayan düz dosyalar kapsam DIŞI.** Araç adayları
   `tabFile`'dan okur; diskte durup hiçbir `File` satırı göstermeyen dosyalar
   ne taşınır ne raporlanır. Koşu sonrası `scripts/media_stats.py` `reconcile()`
   + düz disk taramasıyla teyit et.

---

## 8. Ölçeklenebilirlik hedefi (özet)

| Boyut | Bu standartla davranış |
|---|---|
| Dosya sayısı | Hash-prefix shard → dizin başına ~N/256; milyonlarda bile hızlı |
| Dedup | İçerik-adresli → aynı içerik tek fiziksel dosya |
| Tahmin edilebilirlik | 128-bit hash → enumeration imkânsız |
| Türev çoğalması | Ayrı kök, asset+sürüm adresli → yönetilebilir, orijinalden bağımsız |
| CDN'e geçiş | Yol yapısı (`/files/<ab>/<hash>`) CDN origin olarak temiz |
