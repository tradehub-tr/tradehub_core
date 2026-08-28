# Bulk Localization — Tasarım (Dilim 8)

**Plane:** MOGEM-620 §14 (Bulk Operations) kalanı + §11 (Multilingual) alt bacağı
**Durum haritası:** `docs/MOGEM-620-DURUM.md` A-14 kalanı
**Tarih:** 2026-08-27 · **Durum:** Onaylandı (kullanıcı: "İkisini de sırayla" —
A-9 → A-14 otonom akış) · **Not:** commit yasağı sürüyor — worktree'de birikir.

---

## 1. Gerçeklik ölçümü ve işin doğası

Keşif (2026-08-27): çok dilli kolonlar (`th_media_alt_{lang}` × tr/en/ar/ru)
ve tek-kapı yazma/okuma hazır (`set_asset_fields` çok dilli sözlük kabul
ediyor; `fields_for_many` `localized` haritasını bedavaya döndürüyor). Kural
motoru (`seo_generate`) BİLİNÇLİ olarak yalnız `alt_tr` üretiyor — kod
yorumu: *"Türkçe metni İngilizce kolona yazmak 'çeviri var' yalanı
söylerdi."* `localization` skor boyutu bu yüzden tavan 25'te (yalnız tr).
Çeviri kaynağı AI'sız da mevcut: `Listing.title_{lang}` sufix kolonları
(`CONTENT_TRANSLATABLE_FIELDS`) + `PLATFORM_TERMS` sabit sözlüğü.

## 2. Kararlar

| # | Karar | Gerekçe |
|---|---|---|
| L1 | **Kopyalama YASAK, AI YOK** — `alt_{lang}` yalnız kaynak alan (`Listing.title_{lang}`, kategori adı vb.) o dilde GERÇEKTEN doluysa kural zinciriyle üretilir; yoksa `no_translation` sebebiyle atlanır | Kod tabanının yerleşik ilkesi (`seo_generate.py:160-163`, "Boş, yanlıştan iyidir"); kopyalama skoru yalancı 100'e çıkarır; AI D-listesinde |
| L2 | Kural motoru **dil parametresi** kazanır: `generate_alt(file_url, lang="tr")` — Listing dalı `resolve_content_field(listing, "title", lang)`, sabit ekler `translate_platform_term` ile | Mevcut zincir korunur, dil tek eksen |
| L3 | Backfill **senkron + limit'li** (`backfill_media_alt` emsali) — kuyruk YOK | Metin işi; ölçülen desen |
| L4 | `missing_localized_alt` finding kuralı (warn, **localization** boyutu — boyutun İLK kodu): alt_tr dolu AMA kaynak çevirisi mevcut bir dilde alt boş | Panel `code` süzgeci bedavaya çalışır; "çevrilebilirdi ama çevrilmedi" gerçek sinyal — kaynak çevirisi olmayan dosyada SUSAR (L1 tutarlılığı) |
| L5 | Skor formülü DEĞİŞMEZ (yalnız `alt`, 4 dil, tavan 100) — title/caption skora girmez | Ölçüm kesintisi yaratmamak; elle doldurulan alanlar (tasarım gereği) skoru cezalandırmamalı |
| L6 | `alt_source` damgası dil-körü kalır; çok dilli yazım YALNIZ `REFRESHABLE` (boş/rule/ai) damgalı dosyalarda çalışır, damgayı DEĞİŞTİRMEZ | Dil-başına damga = yeni kolon + tüm okuma yolları; YAGNI. İnsan metnine dokunulmaz garantisi korunur |
| L7 | Panel: MediaSeoView'a mevcut `backfillAlt` deseninde tek "Çeviri backfill" düğmesi; çoklu satır seçimi UI'sı KAPSAM DIŞI | Kural-tabanlı backfill seçim istemez; MediaBulkBar taşıma işi ayrı dilim |
| L8 | `PLATFORM_TERMS`'e ~6 sabit eklenir ("kategorisi", "mağaza logosu", "mağaza kapak görseli", "marka logosu", "marka kapak görseli", "{n}. görsel" kalıbı) | Sabit ekler tek sözlükten (mevcut desen) |

## 3. Kapsamdaki değişiklikler

- `media/seo_generate.py`: `_listing_metni(listing, lang)`, `generate_alt(file_url, lang="tr")`,
  `refresh_alt(file_url, *, lang="tr", force=False)` (dönüş sözleşmesine `no_translation` sebebi eklenir);
  `_backfill_adaylari(limit, lang, only_listing)` — `alt_{lang}` boş VE dosya Listing'e bağlı adaylar;
  `backfill_localization(limit=500, langs=("en","ar","ru"))` → `{scanned, written, skipped, reasons, by_lang}`.
- `seo/i18n.py`: `PLATFORM_TERMS` +6 giriş (en/ar/ru üçlüsüyle); "{n}. görsel" kalıbı için
  `format_image_ordinal(n, lang)` benzeri küçük yardımcı (PLATFORM_TERMS düz sözlüğüne sığmıyorsa).
- `api/media_admin.py`: `backfill_media_localization(limit=500)` whitelist ucu (`_guard`; `backfill_media_alt` emsali).
- `media/seo_audit.py`: `missing_localized_alt` (warn, localization) — `audit_fields` saf katmanında
  (`localized` haritası + Listing çeviri varlığı bilgisi gerekiyorsa batch katmanında; uygulama planda netleşir,
  N+1 yasak). `_KURAL_BOYUT` 33 kod; bütünlük assert'i güncellenir (32→33).
- Panel: `MediaSeoView.vue` düğme + iki adımlı onay (mevcut desen) + tr/en i18n (+
  `mediaSeo.finding.missing_localized_alt` etiketi).
- Rapor 111: `Listing.title_{lang}` doluluk oranları (çeviri kaynağı ne kadar var — dürüst),
  backfill koşum sonuçları (`by_lang`), localization skor önce/sonra, `missing_localized_alt` sayısı.

## 4. Yüzeyler

Panel: tek düğme + toast (L7). Vitrin işi YOK (okuma tarafı `translated_alt`
fallback'iyle zaten çalışıyor). Yeni DocType/kolon YOK — patch gerekmez.

## 5. Test stratejisi

- `generate_alt` dil dalları: title_en dolu → EN alt üretilir (sabit ekler çevrili);
  title_en boş → `no_translation`; insan damgalı dosyaya yazılmaz (L6); force yalnız REFRESHABLE'da.
- Backfill: `by_lang` sayaçları; aday sorgusu yalnız eksik-dil dosyalarını bulur; idempotent (ikinci koşum 0 yazar).
- `missing_localized_alt`: kaynak çevirisi varken boş → WARN; kaynak çevirisi yokken → SUSAR; `_KURAL_BOYUT` 33.
- Panel düğme testi (mevcut backfillAlt test deseni varsa).
- Regresyon: `test_media_seo.py` (çok dil), `test_media_seo_pipeline.py` tam modül.

## 6. Kapsam dışı

AI çeviri (D-listesi) · TR kopyalama (L1) · caption/title toplu üretimi
(kaynak veri yok; elle — tasarım gereği) · dil-başına `alt_source` (L6) ·
çoklu satır seçim UI / MediaBulkBar taşıma (L7) · locale-specific medya
override · transcript çok dil (K3) · skor formülü genişletmesi (L5).

## 7. Kabul kriterleri

1. `title_en` dolu bir ilanın görseli backfill sonrası `alt_en` kazanır; sabit ekler İngilizce.
2. `title_en` boş ilanın görseline `alt_en` YAZILMAZ (`no_translation` sayacı artar) — kopyalama yok.
3. İnsan (`human`/`edited`) damgalı dosyanın hiçbir dil kolonuna dokunulmaz.
4. `missing_localized_alt` yalnız "çevrilebilirdi ama çevrilmedi" durumunda WARN üretir; panel süzgecinde listelenir.
5. Backfill idempotent; ikinci koşum 0 yazar.
6. Rapor 111 kaynak-çeviri doluluğunu ve `by_lang` sonuçlarını dürüstçe verir.
7. Mevcut 32 kural + skorlar regresyonsuz (tam modül yeşil); `_KURAL_BOYUT` 33 assert'i güncel.

## 8. Uygulama sırası (plan iskeleti)

1. i18n sabitleri + `seo_generate` dil desteği (üretim + refresh + testler)
2. Aday sorgusu + `backfill_localization` + whitelist ucu + `missing_localized_alt` kuralı
3. Panel düğmesi + i18n + rapor 111 ölçümü
