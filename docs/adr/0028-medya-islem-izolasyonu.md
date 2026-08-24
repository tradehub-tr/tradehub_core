# ADR-0028 — Güvenilmeyen medya ayrı süreçte süre ve bellek limitleriyle işlenir

**Durum:** Kabul edildi
**Tarih:** 2026-08-23 · **İlgili:** ADR-0004, ADR-0014

## Bağlam

Dosya başlığı güvenli görünse bile codec parser/decode CPU, adres alanı veya
native kütüphane hatasıyla worker'ı öldürebilir. Yalnız Pillow uyarısı veya
uygulama try/except'i native süreç çökmesini izole etmez.

## Seçenekler

| Seçenek | Ölçüm / bedel |
|---|---|
| Ana worker içinde decode | En düşük spawn maliyeti; bomb/crash tüm worker'ı etkiler |
| Container başına ortak medya worker | Kaynak kotası var; tek kötü iş diğer işleri etkileyebilir |
| **İş başına child process + RLIMIT_AS + timeout** | **Seçildi**; kontrollü `failed` sonucu |

## Ölçüm verisi

`docs/reports/17-guvenlik-arge.md`: malicious korpus 10/10 iki kapıda red,
100 MP bomba tam decode edilmeden red; izolasyon 36/36; SVG sanitizer 52 test
(3 platform skip). Meşru public/private korpusta yeni yanlış red farkı 0.

## Karar

Header/MIME/polyglot/MP kapısı parent'ta decode öncesi çalışır. Kabul edilen
güvenilmeyen decode/encode child process'te RLIMIT_AS ve duvar saati timeout'u
ile yapılır. Limit/sinyal temiz hata koduna çevrilir; parent kuyruk worker'ı
yaşamaya devam eder. Yarım çıktı promote edilmez.

## Sonuçlar

Olumlu: bomb/native crash etki alanı tek iştir. Olumsuz: process spawn ve IPC
maliyeti; platforma göre RLIMIT desteği değişir ve test skip'i görünür kalır.

## Geri dönüş yolu

İzolasyon overhead'i p95 bütçesini aşarsa yalnız doğrulanmış küçük/yerel format
sınıfı kalıcı sandbox worker havuzuna alınabilir; ana worker decode yolu açılmaz.
Child protokolü hata üretirse media pipeline bayrağı kapanır ve kaynak dosya
karantinada kalır.
