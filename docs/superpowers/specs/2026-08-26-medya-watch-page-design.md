# Medya Video Watch Page — Tasarım (Dilim 5)

**Plane:** MOGEM-620 · **Durum haritası:** `docs/MOGEM-620-DURUM.md` C-1
**Üst belge bağı:** "raw file ≠ indexable landing/watch page" (kritik mimari
karar) + video spec'inin kapsam dışı bıraktığı watch page/SeekToAction borcu
(`2026-08-26-medya-video-seo-design.md` §10, §12).
**Tarih:** 2026-08-26 · **Durum:** Onaylandı (kullanıcı; kapsam+URL+index
kuralı kararları AskUserQuestion ile alındı)

---

## 1. Kararlar

| # | Karar | Kaynak |
|---|---|---|
| W1 | Kapsam: YALNIZ video watch page. Görsel landing (`/medya/g/…`) ayrı dilim | Kullanıcı |
| W2 | URL: `/medya/v/<slug>` — medya ailesine tek kök | Kullanıcı |
| W3 | Index kuralı: `storefront_visible` ilana bağlı + posterli + `seo_index.decide()` olumlu → index; aksi hâlde sayfa açılır ama **noindex** + sitemap dışı | Kullanıcı |
| W4 | SeekToAction dahil; **Key Moments/chapters kapsam dışı** (bölüm verisi alanı yok) | YAGNI |
| W5 | Embed (YouTube/Vimeo) videolara watch page AÇILMAZ — posteri yok (video spec amendment §12 ile tutarlı) | Tutarlılık |
| W6 | Slug değişimi eski adresi kırmaz: `Media URL Redirect` (301) yeniden kullanılır | Mevcut altyapı |

## 2. Slug + canonical doldurma

- `th_media_slug` boşsa üretilir: `slugify_tr(title → alt → dosya görünen adı)`;
  çakışmada `-<hash6>` eki (içerik hash'inin ilk 6'sı — deterministik).
- `th_media_canonical = /medya/v/<slug>` aynı anda yazılır.
- Tetikleme: video poster üretimiyle aynı anlarda (transcode sonrası /
  fast-path) + mevcut videolar için tek seferlik backfill (parça parça,
  `media-maint`).
- Slug elle değiştirilirse (panel): eski `/medya/v/<eski>` → yeni adrese 301
  satırı açılır (`Media URL Redirect`, `job_key="watch-slug"`); canonical
  güncellenir.
- Okuma/yazma yalnız `media/seo.py` kapısından (slug/canonical zaten SINGLE'da).

## 3. Backend — sayfa verisi ve resolver

- **Public uç** `api/media_public.py::get_watch_page(slug: str) -> dict`
  (allow_guest): `{title, caption, description, transcript, posterUrl,
  sources: [{src, type}] (WebM + varsa HLS master), captionsUrl, durationSec,
  uploadDate, license: {creator, creditText, copyrightNotice, licenseUrl,
  acquireLicensePageUrl}, listings: [{slug, title, image}], indexable,
  canonical}`. Kaynaklar manifest alt katmanından (`media_manifest` deseni);
  bayrak kapalıysa ham `file_url`'e düşer. Slug bulunamazsa 404.
- **Resolver dalı** `seo/page_resolver.py`: `/medya/v/<slug>` (+ `/en/…`)
  rotası — `pages/media-watch.html` gövdesine meta (`title`, `description`,
  `og:video*`, `robots`) + JSON-LD enjekte eder; `/urun` dalıyla aynı desen.
- **JSON-LD:** `build_video_object` çıktısı + `potentialAction`:
  `{"@type": "SeekToAction", "target": {"@type": "EntryPoint",
  "urlTemplate": "<site>/medya/v/<slug>?t={seek_to_second_number}"},
  "startOffset-input": "required name=seek_to_second_number"}`.
  `contentUrl` ham dosya, `url` watch page, `embedUrl` yok (W5).

## 4. Index/robots davranışı (W3)

Tek karar fonksiyonu (backend): `watch_indexable(file_url) -> bool` =
`seo_index.decide(...)["indexable"]` AND posterli AND en az bir
`storefront_visible` ilana bağlı (usage üzerinden). Sonuç üç yerde tüketilir:
robots meta (resolver), sitemap üretimi, `get_watch_page.indexable`.
Gizli/orphan/postersüz video: sayfa 200 döner ama `noindex, nofollow` +
sitemap dışı. Private dosya: mevcut erişim modeli gereği medya 404'tür —
watch page de slug çözümünde 404 verir.

## 5. Vitrin (tradehubfront)

- `nginx.conf.template` + `vite.config.ts::PRETTY` listesine
  `/^\/(?:en\/)?medya\/v\/[^/]+/ → /pages/media-watch.html` rewrite'ı.
- Yeni `pages/media-watch.html` + `pages/media-watch.ts`: slug'ı pathname'den
  okur, `get_watch_page` çağırır; oynatıcı (`<video poster>` + `<track>`),
  başlık/caption, açılır transcript bloğu, lisans satırı, bağlı ürün
  kart(lar)ı. `?t=<sn>` parametresi oynatıcıyı o saniyeden başlatır
  (SeekToAction hedefi). Slug 404 → mevcut 404 davranışı.
- Yeni bağlantı noktası: ürün sayfasındaki video slaydına "videoyu kendi
  sayfasında aç" bağlantısı (küçük, keşfedilebilirlik + iç link sinyali).

## 6. Sitemap + canonical

- Video sitemap'e watch page'ler KENDİ `<url>` girdileri olarak eklenir
  (`loc = /medya/v/<slug>`, `<video:video>` gövdesiyle); yalnız W3'e göre
  indexable olanlar. Ürün sayfası video girdileri korunur.
- Watch page kendi kendine canonical (resolver basar); `th_media_canonical`
  alanı da aynı değeri taşır (tutarlılık denetimle izlenir).

## 7. Panel (küçük)

MediaSeoDrawer video bölümüne: slug alanı (düzenlenebilir; kayıtta 301
köprüsü) + "Sayfayı gör" linki. Denetime 1 kural: video indexable ama slug
boş → `missing_watch_slug` (WARN, discoverability kırılımı).

## 8. Test stratejisi

- Slug üretimi/çakışma/301 köprüsü — birim + FrappeTestCase.
- `get_watch_page` sözleşme testi (dolu/boş alanlar, 404, indexable üçlüsü).
- Resolver: meta + JSON-LD enjeksiyonu, noindex dalı (mevcut resolver test
  desenine ek).
- SeekToAction JSON şekli birim testi; vitrin `?t=` davranışı Vitest.
- Sitemap: watch girdisi yalnız indexable videoda (noindex dışarıda) testi.
- Ölçüm: kaç video watch page + index aldı, örnek sayfada HTTP + JSON-LD
  kanıtı (rapor).

## 9. Kapsam dışı

Görsel landing (`/medya/g/`), Key Moments/chapters, embed videolar (W5),
HLS üretimi (varsa tüketilir), yorum/paylaşım gibi sayfa etkileşimleri,
watch page için ayrı çok dilli slug (tek slug; içerik alanları zaten 4 dilli).

## 10. Uygulama sırası (plan için iskelet)

1. Slug/canonical üretimi + 301 köprüsü + backfill
2. `get_watch_page` ucu + `watch_indexable`
3. Resolver dalı + JSON-LD (SeekToAction)
4. Vitrin sayfası + rewrite + `?t=` + ürün sayfası linki
5. Sitemap watch girdileri
6. Panel slug alanı + denetim kuralı + ölçüm raporu
