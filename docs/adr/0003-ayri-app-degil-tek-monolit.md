# ADR-0003 — Medya motoru ayrı Frappe app'i değil, app içi saf alt pakettir

**Durum:** Kabul edildi · uygulamayla hizalı
**Tarih:** Faz 3 (T-032) · son doğrulama 2026-08-23
**İlgili:** ADR-0004 (saf çekirdek / Frappe kabuğu ayrımı)

## Bağlam

Kaynak görev “Frappe app iskeleti” diyerek ayrı bir `media_engine` app'i
öngörüyordu. İstoç'ta yükleme hook'ları, `File` uzantıları, DocType'lar,
yetkilendirme ve migration sırası zaten `tradehub_core` app'ine aittir. İkinci
app aynı veriyi ve tek yükleme kapısını iki release/migrate sınırına bölerdi.

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — Ayrı `media_engine` Frappe app'i | Bağımsız kurulum; fakat iki app, iki migrate sırası ve cross-app veri/hook bağımlılığı |
| **B — `tradehub_core.media.pipeline` app içi saf alt paket (seçilen)** | Tek app/release/migrate; çekirdek yine bench/site olmadan test edilebilir |
| C — Kodun tamamını mevcut Frappe bağlı `media/` modüllerine karıştırmak | Paket sınırı ve ucuz contract testi kaybolur |

## Karar

`tradehub_core/media/pipeline/`, import yolu
`tradehub_core.media.pipeline` olan **app içi saf çekirdektir**. Ayrı Frappe app
değildir; kendi `hooks.py`, `modules.txt` veya app kaydı yoktur. Frappe/RQ/DB
bağlantıları `pipeline_bridge.py`, `api/` ve DocType kabuğunda kalır.

Bu, T-032'deki ayrı-app sözcüğünden kabul edilmiş bir sapmadır; görevdeki
modülerlik, CI ve Docker worker kabul ölçütleri korunur:

- paket alt modülleri açıkça ayrılmıştır;
- beş Protocol ve üretim adaptörleri site olmadan test edilir;
- Frappe köprüsü tek giriş noktasıdır;
- beş medya worker'ı Compose projeksiyonunda ayrıdır.

## Gerekçe ve ölçülen sonuç

- **Tek veri sahibi:** Media Asset/Version/Rendition/Processing Job ve `File`
  bağları aynı app migrate döngüsündedir.
- **Tek yükleme kapısı:** yetki, kota, politika ve denetim hook sırasını iki app
  arasında koordine etmek gerekmez.
- **Saflık korundu:** `test_contracts` 75 ve `test_state_machine` 47 test
  bench/site olmadan geçer; contract mypy kapısı 0 hatadır.
- **Üretim sınırı gerçektir:** `PillowImageEngine` ve `FfmpegVideoEngine`
  donmuş Protocol'leri karşılar; yalnız fake uygulamaya dayalı değildir.

Bedel: paket başka bir Frappe kurulumuna tek başına `bench get-app` ile
kurulamaz ve app'ten bağımsız release edilemez. Bugün bağımsız tüketici yoktur;
bu bedel bilinçli kabul edilmiştir.

## Geri dönüş yolu

Bağımsız deploy/ölçekleme ihtiyacı monolit release döngüsünü ölçülebilir biçimde
engellerse saf `pipeline` paketi yeni app'e taşınır. Frappe kabuğu yeni app'e
alınır; eski import yolları en az bir sürüm uyumluluk shim'iyle korunur ve
DocType sahipliği için açık migration yazılır.
