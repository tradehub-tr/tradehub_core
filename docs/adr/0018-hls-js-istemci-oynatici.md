# ADR-0018 — HLS oynatma için `hls.js` eklenir (MSE fallback)

**Durum:** KABUL (kararlaştırıldı — kullanıcı onayı, 2026-08-20) · uygulama W7 dalgasında (rapor 85)
**Tarih:** 2026-08-20 · **Yazan:** W7 doküman eşitlemesi (rapor 88)

## Bağlam

Video motoru DEV'de ilk gerçek koşumunda HLS merdiveni üretti (3 basamak,
405 segment, `master.m3u8` HTTP 200 — `81-w6-video-kosum.md` §3). Ama panel
oynatıcısı `MediaVideo.vue` HLS'i **yalnız tarayıcının yerli desteği varsa**
kullanıyor; dosyanın kendi yorumu açıkça `"hls.js EKLENMEDİ. Yeni bağımlılık
kararı bu görevin işi değil"` diyor (`admin-panel/frontend/src/components/media/MediaVideo.vue:27-31`).
Sonuç: Chrome/Firefox (MSE'li ama yerli HLS'siz tarayıcılar) üretilen HLS
merdivenini **hiç kullanamıyor**, progresif mp4'e düşüyor — merdivenin bant
genişliği sınıfları bu tarayıcılarda ölü kod.

## Seçenekler

| # | Seçenek | Elenme/seçilme gerekçesi |
|---|---|---|
| A | Yerli HLS ile yetin (bugünkü durum) | Chrome/Firefox'ta merdiven hiç oynamaz; HLS üretiminin faydası yalnız Safari/iOS'a kalır |
| B | **`hls.js` ekle — tembel yüklenen MSE fallback'i** | **SEÇİLDİ** — endüstri standardı, `hlsSrc` prop'u zaten var, tembel import ile ana pakete girmez |
| C | dash.js / Shaka'ya geç (format değişikliği) | Motor HLS üretiyor (rapor 81); format değiştirmek bu karardan çok daha büyük bir iş ve ölçülmüş bir gerekçesi yok |

## Karar

`hls.js` bağımlılık olarak eklenir; `MediaVideo.vue` yerli HLS yoksa ve MSE
varsa `hls.js` ile `.m3u8` oynatır. Sıra korunur: yerli HLS → `hls.js` →
progresif `src` (mevcut "HLS bir iyileştirme kademesidir, tek yol değil"
felsefesi değişmez).

## Gerekçe

- Kullanıcı onayı verildi (2026-08-20; yeni-bağımlılık kararı CLAUDE.md §2.11
  gereği kullanıcıya aitti — verildi).
- Üretilmiş gerçek çıktı var: 3 basamaklı merdiven + açılış bütçesi 3/3 geçti
  (rapor 81 §3, halka 6) — oynatıcı tarafı olmadan bu çıktı iki büyük
  tarayıcı ailesinde erişilemezdi.

## Sonuçlar

**Olumlu:** HLS merdiveni tüm modern tarayıcılarda çalışır; `MediaVideo.vue`
prop sözleşmesi (`hlsSrc`) değişmez.
**Olumsuz / bedel:** yeni çalışma-zamanı bağımlılığı (paket boyutu + güvenlik
takibi); tembel import edilmezse ana bundle büyür — uygulama tembel import
şartıyla yapılmalı. Video manifest temsili hâlâ yok (rapor 81 §7) — `hlsSrc`'yi
dolduracak backend halkası ayrı iş; `hls.js` tek başına ekranda video açmaz.

## Kanıt

`docs/reports/81-w6-video-kosum.md` §3/§7 · `MediaVideo.vue:18-31,56-61` ·
uygulama ve ölçümleri: W7 koşumu, `docs/reports/85-*.md` (bu ADR yazılırken
rapor henüz numaralanıyordu; 2026-08-20 W7 dalgası).

**Uygulamanın ilk ölçülen izi (2026-08-20, bu ADR yazılırken):**
`admin-panel/frontend/package.json:42` → `"hls.js": "^1.7.1"` — bağımlılık
W7 ajanınca eklendi; davranış ölçümleri rapor 85'te.
