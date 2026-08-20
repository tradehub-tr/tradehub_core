# ADR-0020 (TASLAK) — Devam edebilir yükleme: tus protokolü mü, mevcut `chunked.py` sözleşmesi mi

**Durum:** ÖNERİLDİ · **Karar: BEKLİYOR** (platform yöneticisi — rapor 57 karar listesi "Faz 8 TS SDK/tus")
**Tarih:** 2026-08-20 · **Yazan:** W7 doküman eşitlemesi (rapor 88)

## Bağlam

Pano T-081/T-091 "kesilen yüklemeler **tus protokolüyle** son bayttan devam
eder" ve "Uppy + tus yükleyici" diyor. Ölçülen gerçek (rapor 44 §3, rapor 61e):

- **Sunucuda tus YOK** — hiçbir uçta tus başlığı, `PATCH .../uploads/...` yolu
  ya da `Idempotency-Key` parametresi geçmiyor (grep ile ölçüldü, rapor 44).
- Sunucuda **çalışan bir parçalı yükleme sözleşmesi VAR**: `media/chunked.py`
  (`baslat/parca/bitir`; parçalar diske akar, politika **birleşimden sonra**
  bütüne uygulanır, oturumlar mağazaya bağlı — dosya docstring'i).
- İstemcide `session.js` `localStorage` tabanlı devam edebilirliği bu
  sözleşmeye karşı kurdu; `tus-js-client`/Uppy **bilinçli kurulmadı**
  ("konuşacağı bir uç yok" — rapor 44 §3, `session.js:6-7` başlık notu).
- **`Idempotency-Key` iki tarafta da yok** — istemci yalnız `finish`'i tek
  sefere kilitliyor (rapor 61e).

## Seçenekler

| # | Seçenek | Ölçülen/bilinen bedel |
|---|---|---|
| A | Sunucuya gerçek tus protokolü ekle (`tus-js-client` 4.3.1 + Uppy) | Yeni protokol yüzeyi + upload tek kapı kuralıyla (NFR-015) hizalama işi; mevcut `chunked.py` + `session.js` çifti ya atılır ya ikilenir. Kazanım: standart protokol, hazır istemci ekosistemi |
| B | Mevcut `chunked.py` sözleşmesini resmîleştir: pano metnindeki "tus" ifadesi "devam edebilir parçalı yükleme" olarak revize edilir; eksik `Idempotency-Key` sunucu+istemciye eklenir | Kazanım: çalışan, testli, kiracı-bağlı mevcut kod korunur. Bedel: kaynak dokümandan **bilinçli sapma** — imza ister |
| C | Hibrit: dış SDK tüketicileri için tus, panel için mevcut sözleşme | İki devam-edebilirlik yolu = iki doğruluk kaynağı; bakım maliyeti iki kat |

## Karar

**BEKLİYOR.** Bu ADR karar vermez; seçenekleri ölçülmüş durumlarıyla kayda
geçirir. Karar verilirken: (a) hangi seçenek seçilirse seçilsin
`Idempotency-Key` eksiği ayrıca kapatılmalı (rapor 44/61e'de iki kez ölçüldü);
(b) pano kabul kriteri metni seçilen yola göre revize edilmeli — bugün kriter
harfiyen "tus" dediği için B/C seçimi görev karnesinde sonsuza dek KISMİ
görünür.

## Gerekçe (kararın neden şimdi gerektiği)

T-081/T-091 karneleri bu belirsizlik yüzünden KISMİ'de asılı (rapor 61e);
plan belgesi de kalemi "KARAR" olarak işaretledi
(`docs/plans/frontend-kalan-45-plani.md:123`).

## Sonuçlar

Karar verilmeden: istemci `session.js` yoluna yatırım yapmaya devam ediyor;
tus'a sonradan dönüş, biriken istemci kodunun değişmesi demek — bekleme
maliyeti zamanla artıyor.

## Kanıt

`docs/reports/44-t081-yukleyici.md` §3 · `docs/reports/61e-fe-denetim-faz8-9.md`
T-081/T-091 satırları · `tradehub_core/media/chunked.py` docstring ·
`admin-panel/frontend/src/lib/media/upload/session.js:1-51`.
