# 70 · T-131 — Medyaya özgü dosya servis sertleştirmesi (nginx)

Tarih: 2026-08-20 · Kapsam: servis katmanı (nginx). Backend SVG sanitizasyonu
(`reject_unsafe_files` + probe guard) bu işten ÖNCE zaten vardı; bu iş yalnız
edge başlıklarını ekler.

## Şartname eşlemesi (71-faz13 → T-131 kabul kriterleri)

| Kriter | Uygulama | Durum |
|---|---|---|
| Ayrı origin **veya** `CSP: sandbox` | `/files/` + `/private/files/` yanıtlarında `.svg` uzantısına koşullu `Content-Security-Policy: sandbox; default-src 'none'` | ✅ (404 yanıtıyla kanıtlı; gerçek SVG dosyasıyla ÖLÇÜLMEDİ — sistemde hiç SVG yok) |
| `X-Content-Type-Options: nosniff` her yanıtta | İki location'da da `proxy_hide_header` + edge `add_header … always` (tek başlık) | ✅ ölçüldü |
| Doğru `Content-Type` | Upstream'den geçiyor, dokunulmadı (`image/png`, `image/jpeg` ölçüldü) | ✅ ölçüldü |
| HTML/JS asla inline servis edilmez | `.html/.htm/.xhtml/.shtml/.xml/.xsl/.xslt/.js/.mjs/.cjs` uzantılarına `Content-Disposition: attachment` | ✅ (404 yanıtıyla kanıtlı; gerçek HTML/JS dosyası /files/ altında yok) |
| SVG `Content-Disposition` kuralı | Attachment BİLEREK basılmadı (görüntü MIME'ı bozma yasağı); inline servise sandbox CSP eşlik ediyor — şartnamenin "satır içi gerekiyorsa yalnızca temizlenmiş" koşulu backend sanitizasyonu ile karşılanıyor | ✅ (bilinçli sapma, gerekçe aşağıda) |

## Değişen dosyalar

- `docker/nginx/storefront.local.template` — 3 tek-parça "T-131" bloğu:
  1. http-context'te 2 `map` (`$t131_files_csp`, `$t131_files_dispo`) —
     `limit_req_zone files_zone` satırının hemen altında,
  2. `location ^~ /files/` içinde başlık bloğu,
  3. `location ^~ /private/files/` içinde başlık bloğu.
  Geri alma = üç bloğu silmek; başka satır değişmedi.
- `docker/nginx/admin-panel.local.template` — yalnız karar notu (yorum).
  **Uygulanmadı çünkü ölçüldü:** bu sunucu `/files/` proxy'lemiyor;
  `wget http://admin-panel:80/files/0012.png` (gateway içinden) → **404**.
  Panelin kullanıcı-medyası gateway → storefront zincirinden geçer ve
  storefront blokları onu kapsar.

## Neden böyle

- **Boş map + `add_header`:** nginx boş değerli başlığı hiç basmaz → tek
  `add_header` satırı yalnız eşleşen uzantıda başlık üretir; görüntü/video
  MIME'ları hiçbir yeni başlık almaz (yasak: görsele `attachment`).
- **`proxy_hide_header X-Content-Type-Options`:** nosniff'i bugüne dek yalnız
  upstream (frappe-frontend) basıyordu; `/files/` bloğunun kendi
  `add_header`'ı (X-Robots-Tag) server-level nosniff mirasını zaten kesmişti.
  Çift başlık yerine "önce gizle, tek doğruyu bas" (gateway.conf deseni).
- **`/private/files/` başlık tekrarı:** bloğa ilk `add_header` girince
  server-level miras kesilir; önceki davranış (X-Frame-Options DENY vb.)
  açıkça tekrarlanarak korundu. Tek bilinçli fark: site CSP'si
  (`script-src 'unsafe-inline'` içeriyor → SVG'de inline script'e izin
  verirdi) yerine koşullu sandbox CSP.
- **SVG'ye attachment yok:** parent-görev yasağı (görüntü MIME'ı bozma) +
  `<img>` teslimi riske girmesin. Yanıtın kendi CSP'si `<img>` render'ını
  etkilemez; SVG'ye doğrudan gidilirse sandbox script'i keser.

## Kalıcılık uyarısı (bilinen tuzak)

`docker/nginx/*.local.template` dosyaları `gen-local-nginx.sh` ÜRETİMİ.
Script tekrar koşarsa T-131 blokları (tıpkı önceki `/files/` limit_req +
X-Robots-Tag sertleştirmesi gibi) silinir. Kalıcı çözüm kaynak şablonlara
(`tradehubfront/nginx.conf.template`) taşımak — bu işin kapsamı dışında
(izinli dosya listesi yalnız `docker/nginx/*.template`).

## Ölçümler (curl -sI, istoc.localhost, 2026-08-20)

### ÖNCE
```
/files/0012.png            → 200 image/png; nosniff YALNIZ upstream'den; CSP yok; Disposition yok
/files/yok.svg   (404)     → CSP yok, Disposition yok
/files/yok.html            → (ölçülmedi-öncesinde ama kural yoktu: hiçbir koşullu başlık tanımlı değildi)
/private/files/yok.pdf     → 403; storefront'un BÜYÜK site CSP'si miras (script-src 'unsafe-inline' → SVG'de inline script izinliydi)
admin-panel:80/files/0012.png → 404 (proxy yok)
```

### SONRA
```
/files/0012.png            → 200 image/png; X-Content-Type-Options: nosniff (tek); CSP YOK; Content-Disposition YOK ✅
/files/yok.svg   (404)     → Content-Security-Policy: sandbox; default-src 'none' ✅
/files/yok.html  (404)     → Content-Disposition: attachment ✅
/files/yok.js    (404)     → Content-Disposition: attachment ✅
/private/files/yok.pdf     → 403; DENY + nosniff + Referrer + Permissions-Policy açık; büyük CSP gitti ✅
/private/files/yok.svg     → Content-Security-Policy: sandbox; default-src 'none' ✅
```
Not: `.svg/.html/.js` ölçümleri 404 yanıtı üzerinden — `add_header … always` +
`$uri` map'i 404'te de işler, kural kanıtı geçerlidir. **Gerçek SVG içeriğiyle
uçtan uca servis ÖLÇÜLMEDİ** (sites/*/public/files altında hiç .svg yok; test
SVG'si bilinçli olarak yerleştirilmedi).

### Regresyon
```
Ana sayfa /                                   → 200 text/html ✅
Ürün sayfası /urun/20-adet-alci-tas-…         → 200 text/html ✅
Panel /panel/                                 → 200 text/html ✅
Ürünün gerçek <img>'i /files/Ekran%20…png     → 200 image/png, attachment YOK ✅
/files/0004.jpg                               → 200 image/jpeg ✅
Panel kendi JS'i /panel/assets/index-….js     → 200 application/javascript, attachment YOK ✅
Storefront kendi JS'i /assets/index-….js      → 200 application/javascript, attachment YOK ✅
nginx -t (storefront konteyneri)              → syntax ok / test successful ✅
```
(`/assets/` ve `/panel` location'larında T-131 add_header'ı yok → map oralarda
başlık üretemez; uygulamanın kendi JS/SVG'leri etkilenmez — ölçümle doğrulandı.)

## Geri alma

`docker/nginx/storefront.local.template` içindeki üç "T-131" işaretli bloğu sil
→ `docker compose restart storefront`. Başka hiçbir dosya/servis değişmedi.
