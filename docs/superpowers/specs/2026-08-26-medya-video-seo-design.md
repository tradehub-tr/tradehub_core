# Medya Video SEO — Tasarım (Dilim 4)

**Plane:** MOGEM-620 (Medya SEO / Keşfedilebilirlik / AI Arama Katmanı)
**Üst sözleşme:** `docs/MEDYA-SEO-SOZLESMESI.md` §6.4 — "Video SEO, ayrı dilim;
görsel dilimleri bitmeden başlanmaz" → Dilim 1-3 tamamlandı (§9.1), şart sağlandı.
**Tarih:** 2026-08-26 · **Durum:** Onaylandı (kullanıcı, bu tarihte)

---

## 1. Amaç ve bugünkü açık

Vitrinde video iki yerde görünüyor: ürün galerisine yüklenen `.mp4/.webm`
dosyaları (slayt olarak) ve `video_url` promo videosu (YouTube/Vimeo embed ya
da dosya). SEO tarafında bugün:

| Yüzey | Bugün |
|---|---|
| `VideoObject` (JSON-LD) | **Yok** — kod tabanında 0 eşleşme |
| Video sitemap (`xmlns:video`) | **Yok** |
| `<video poster>` | **Yok** — galeri karosu tarayıcının seçtiği (çoğu zaman siyah) kare |
| Süre / transcript / altyazı | Alan bile yok |

Google'ın video rehberi thumbnail + `VideoObject` + video sitemap'i temel
sinyal sayıyor; üçü de eksik.

## 2. Kararlar (netleştirme sorularının sonucu)

| # | Karar | Seçenek |
|---|---|---|
| K1 | Poster üretimi **canlı yoldan**: mevcut `media/transcode.py` akışına hafif ffmpeg adımı. Pipeline'ın flag arkasındaki `pipeline/video/poster.py`'si AÇILMAZ — Media Asset rollout'una bağlanmak bu dilimin kapsamını büyütür. Kare seçim kuralı (pencere + luma kapısı) oradan **uyarlanır**, kod paylaşılmaz | Kullanıcı onayı |
| K2 | Transcript/metadata için **panel UI bu dilimde** yapılır — alanlar "yazılabilir ama doldurulamaz" kalmasın (TUR-135 ar-ge sonucu 1'in dersi) | Kullanıcı onayı |
| K3 | Başlık/açıklama/caption için **yeni kolon açılmaz**: görseller için var olan 4 dilli `th_media_title/caption` + `th_media_description` videoda da geçerli; tek okuma kapısı `media/seo.fields_for` zaten döndürüyor | YAGNI |
| K4 | `expires` karşılığı mevcut `rights_expires_on`; `regionsAllowed` **eklenmez** (tüketicisi yok) | YAGNI |
| K5 | YouTube/Vimeo promo videoları `VideoObject`'e `embedUrl` ile girer; dosya videoları `contentUrl` ile | Google rehberi ikisini de destekler |

## 3. Şema — tek patch

`File`'a 4 kolon (`th_media_` öneki, mevcut desen):

| Kolon | Tip | Kaynak |
|---|---|---|
| `th_media_duration` | Float (saniye) | ffprobe — transcode/poster adımında yazılır |
| `th_media_poster_url` | Data (URL) | Poster üretimi (§4) |
| `th_media_transcript` | Long Text | Elle (panel); AI servisi PM kararı bekliyor |
| `th_media_captions_url` | Data (URL) | WebVTT dosyası — panelden yüklenir, `File` olarak saklanır |

Tek dil: transcript video dilindedir, çeviri seti açılmaz (görüşme dilinde
üretilen içerik değil; ihtiyaç doğarsa ayrı karar).

Okuma yolu: `media/seo.fields_for` bu 4 alanı da döndürecek şekilde genişler —
tüketiciler (schema builder, sitemap, Listing API, denetim) doğrudan kolon
okumaz (TUR-135 kuralı: `tests/test_media_seo.py` sabitler).

## 4. Poster üretimi — canlı yol

`media/transcode.py` akışına eklenir; `media/video_poster.py` yeni modül:

- **Ne zaman:** `_run_transcode` başarıyla bitince VE `needs_transcode=False`
  kestirme yolunda (her video poster alır). İdempotent: `th_media_poster_url`
  doluysa ve kaynak video değişmediyse no-op.
- **Kare seçimi** (pipeline `poster.py` kuralının sadeleştirilmiş hâli):
  1. Pencere `[0.5 sn, min(5 sn, süre × 0.25)]`
  2. ffmpeg `thumbnail=n=120` — histogramca en temsili kare
  3. Luma kapısı %6-%94; düşerse `[süre × 0.25, süre × 0.50]` penceresinde
     bir kez daha; o da düşerse poster üretilmez, denetimde `missing_poster`
- **Çıktı:** JPEG (kalite ~82, uzun kenar ≤ 1280), `naming.py` içerik-hash'li
  adla public `File`; `th_media_poster_url` + `th_media_duration` yazılır.
- **Geri doldurma:** `av.backfill_pending` deseni — zamanlanmış, turda ≤ 50
  video, `media-maint` kuyruğu (video başına ffmpeg maliyeti görselden büyük).
- **Hata:** ffmpeg hatası transcode'un retry/dead-letter desenine katılmaz;
  poster yardımcı üründür — hata loglanır, video yayında kalır, denetim uyarır.

## 5. VideoObject + video sitemap

- `seo/schema_builder.py` → `video_object(fields, *, page_ctx) -> dict | None`:
  `name` (title → alt → dosya görünen adı zinciri), `description`,
  `thumbnailUrl` (poster; yoksa nesne yine üretilir ama denetim uyarır),
  `uploadDate` (`File.creation`, ISO 8601), `duration` (`PT#M#S`),
  `contentUrl` **veya** `embedUrl` (K5), `expires` (`rights_expires_on`),
  `transcript` (doluysa).
- Ürün sayfası JSON-LD'si: `Product`'ın yanına video varsa `VideoObject`
  eklenir (mevcut `ImageObject` deseniyle aynı giriş noktası).
- **Indexability:** `media/seo_index.decide()` kararına uyar — `noindex`
  video ne JSON-LD'ye ne sitemap'e girer.
- `seo/sitemap_generator.py`: `xmlns:video` namespace + sayfa başına
  `<video:video>` (thumbnail_loc, title, description, content_loc |
  player_loc, duration, publication_date, expiration_date). Görsel sitemap'in
  (`image:image`) kurulu deseni birebir izlenir.

## 6. Listing API + vitrin

- `api/listing.py`: `imageMeta` kardeşi `videoMeta` —
  `{url, poster, title, duration, captionsUrl}`; kullanım ezmesi
  (`Media SEO Override`) title'a uygulanır.
- Vitrin (`tradehubfront`): galeri video slaydı ve promo video
  `<video poster="...">` basar; `captionsUrl` doluysa
  `<track kind="captions">`. Sabit boyut yerine gerçek ölçü zaten Dilim 2
  davranışı — video için `videoWidth/Height` bilinmiyorsa atlanır (CLS için
  `aspect-ratio` konteyneri mevcut galeri bileşeninde).

## 7. Panel UI (admin-panel)

`MediaDetailPanel`'e video bölümü (yalnız video dosyalarında görünür):

- Başlık/açıklama/caption düzenleme — görsellerle aynı SEO form bileşeni
  yeniden kullanılır
- Transcript: textarea
- Altyazı: `.vtt` yükleme (upload_policy'ye `vtt` uzantısı, ~1 MB sınır,
  düz metin doğrulaması) → `th_media_captions_url`
- Poster: önizleme + "Yeniden üret" butonu (yeni API ucu, `media-maint`
  kuyruğuna iş atar)

## 8. Denetim

`media/seo_audit.py`'ye 3 kural (hepsi WARN, yalnız video dosyalarında):
`missing_poster`, `missing_transcript`, `missing_duration`. Skor kırılımları:
poster → Performans, transcript → Erişilebilirlik, duration → Yapısal veri.

## 9. Test stratejisi

- **Poster:** küçük fixture videolarla (siyah açılışlı, kısa) kare seçimi,
  luma kapısı, idempotens, hata yolu — ffmpeg gerçek çağrı (CI'da mevcut)
- **Şema/okuma kapısı:** `fields_for` yeni alanları döndürür; doğrudan kolon
  okuma yasağı regresyon testi
- **VideoObject/sitemap:** builder birim testleri + indexability kesişimi
  (noindex video dışarıda)
- **Listing API:** `videoMeta` sözleşme testi
- **Panel:** Vitest — video bölümü render/emit; `.vtt` doğrulama
- Ölçüm: mevcut videolar üzerinde önce/sonra denetim raporu (TUR-135 §9.1
  deseni)

## 10. Kapsam dışı

Watch page, `SeekToAction`, Key Moments, HLS/DASH, önizleme klibi (pipeline'da
kalır), AI transcript (PM kararı), `regionsAllowed` / yaş sınırı / içerik
derecelendirmesi (tüketicisi yok). Medya landing page dilimi geldiğinde
`slug`/`canonical` videoda da anlam kazanır — bu dilimde dokunulmaz.

## 11. Uygulama sırası

1. Şema patch'i + `fields_for` genişletmesi
2. Poster üretimi + geri doldurma
3. `VideoObject` + video sitemap
4. Listing API `videoMeta` + vitrin poster/track
5. Panel video bölümü + `.vtt` yükleme + poster yeniden üretme ucu
6. Denetim kuralları + önce/sonra ölçüm

## 12. Amendment — 2026-08-26 final inceleme

Final inceleme sırasında netleşen kapsam sınırı — belge §2 K5'i tamamlıyor,
geri almıyor:

- **K5 embed `VideoObject` üretimi bu dilimde FİİLEN kapsam dışı.** K5 kararı
  `embedUrl`'i (YouTube/Vimeo) `VideoObject`'e desteklenen bir alan olarak
  tanımlıyor, ama üretim zinciri (§4 poster akışı) yalnız yerel dosyaya
  (`/files/...`) ffmpeg çalıştırıyor — gömülü oynatıcının ne bir `File`
  kaydı ne posteri var. Sonuç: `build_video_object` embed video için
  `poster_url` boş bulur ve sözleşmesi gereği `None` döner
  (`schema_builder.py` — "Poster'ı olmayan video JSON-LD'ye GİRMEZ").
  Dolayısıyla embed promo videolar bugün `VideoObject` JSON-LD'sine hiç
  girmiyor; bu bir bug değil, K5'in üretim tarafında henüz karşılanmamış
  bir yarısı.
- **Poster türetmesi ayrı bir takip görevi.** Gömülü oynatıcılar için poster
  üçüncü taraf API'den türetilebilir (ör. YouTube `https://img.youtube.com/
  vi/{id}/hqdefault.jpg`, Vimeo oEmbed `thumbnail_url`), ama bu ffmpeg akışıyla
  paylaşılamaz — ayrı bir entegrasyon, ayrı hata yüzeyi (video kaldırılmış,
  private, API kotası). Bu dilimin kapsamına sokulmadı; ölçüm raporunda
  `LST-00202` bulgusu (docs/reports/106-video-seo-olcum.md §3.1) aynı
  gerekçeyle işaretlendi.
