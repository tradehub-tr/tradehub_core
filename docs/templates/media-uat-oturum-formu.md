# MOGEM-617 / T-142 moderatörlü UAT oturum formu

Bu form bir gerçek satıcıyla yürütülen oturum içindir. Katılımcının adını,
e-postasını veya telefonunu sonuç CSV'lerine yazmayın; yalnız `S01`…`S999`
takma kodunu kullanın. Ekran/ses kaydı ancak ayrı açık rızayla alınır.

## Oturum öncesi

- Katılımcı kodu: `S__`
- [ ] Gerçek satıcı hesabı doğrulandı.
- [ ] En az 5 gerçek ürün hazır.
- [ ] Katılım rızası kaydedildi.
- [ ] Ekran/ses kaydı için ayrı rıza kararı kaydedildi.
- Moderatör kodu: `M__`
- Tarih/saat ve saat dilimi: `YYYY-MM-DDTHH:MM:SS+03:00`

## Görev kaydı

Her görev için başlangıç ve bitişi saat dilimli ISO-8601 biçiminde yazın.
Katılımcı üç dakika takılmadan yardım etmeyin. Tamamlanan her görev için DB
kaydı, ekran kanıtı veya güvenli iç referansı `evidence_ref` alanına koyun.

| Görev | Başlangıç | Bitiş | Tamamlandı 0/1 | Yardım | Kanıt | Karışıklık notu |
|---|---|---|---:|---:|---|---|
| G1 — 5 ürün görseli yükle | | | | | | |
| G2 — kırpma ve odak ayarla | | | | | | |
| G3 — cihaz önizlemelerini incele/onayla | | | | | | |
| G4 — logo yükle | | | | | | |
| G5 — company video yükle | | | | | | |
| G6 — küçük görsel reddini oku ve düzelt | | | | | | |

## G6 anlama puanı

Hata mesajını ekrandan kaldırıp “Bu yükleme neden kabul edilmedi ve şimdi ne
yapmanız gerekiyor?” diye sorun.

- `1`: sebep ve düzeltme eylemi doğru.
- `0.5`: yalnız biri doğru.
- `0`: yanlış veya bilmiyor.

Puan: `___`

## Bulgular

Her bulguyu `media-uat-findings.csv` içinde ayrı satır yapın. `critical`,
`high`, `medium`, `low`; `open` veya `closed` kullanın. Her bulguda anonim
sorumlu kodu ve hedef tarih, kapalı bulguda kanıt zorunludur.

## Rapor üretimi

Oturumları `media-uat-results.csv` şemasına aktarın ve çalıştırın:

```bash
python3 scripts/summarize_media_uat.py media-uat-results.csv media-uat-findings.csv
python3 scripts/summarize_media_uat.py media-uat-results.csv media-uat-findings.csv --check-gate
```

İkinci komut yalnız ≥10 gerçek/açık rızalı satıcı, kişi başına ≥5 ürün,
tam-anlama oranı ≥%90, sıfır puanlı katılımcı olmaması ve tüm kritik bulguların
kapanması halinde `0` ile çıkar.
