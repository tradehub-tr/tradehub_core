# T-054 · Faz 5 yedek/DR kapanış kanıtı

**Tarih:** 2026-08-23  
**Ortam:** `istoc-dev-backend-1` / `istoc.localhost` / geliştirme  
**Set:** `20260823_104322_t054_phase5`

## Sonuç

| Kapı | Ölçülen sonuç | Durum |
|---|---:|:---:|
| Snapshot | 8.893 orijinal, 1.041.292.081 bayt, 5.126 kayıt | ✅ |
| Yeniden üretilebilir türevleri dışlama | `/files/media/` altında 1.197 dosya | ✅ |
| Tam derin bütünlük | 8.893/8.893; eksik 0, bozuk 0 | ✅ |
| Deterministik rastgele örneklem | 100/100; eksik 0, bozuk 0 | ✅ |
| Tek dosya restore tatbikatı | 13 bayt, 280,7 ms, DB kaydı değişikliği 0 | ✅ |
| Restore sonrası SHA-256 | manifest = eski canlı = geri yüklenen | ✅ |

Restore edilen kontrollü hedef:

```text
16/162f904de0e363ff8a9bab7bb99b667f.txt
sha256 162f904de0e363ff8a9bab7bb99b667f5de62833afe3632574aa9a250c54c94a
```

Dosya önce manifest hash'iyle doğrulandı, atomik olarak staging adına taşındı,
`restore.apply(..., records=False, overwrite=False, only=[...])` ile geri getirildi
ve tekrar hash'lendi. Başarı sonrası staging kopyası silindi; canlı dosya aynı
baytlarla yerinde kaldı. Hata dalı, canlı hedef oluşmazsa staging dosyasını geri
almaya ayarlıydı.

## Uygulanan teknik kapanışlar

- `backup._scan()` güncel rendition kökünü (`public/files/media/`) ve legacy
  `__<profile>.<format>` çıktılarını dışlıyor.
- Manifest, `backup_policy.derivatives=excluded_regenerable` kararını ve
  `excluded_regenerable_derivatives` sayacını taşıyor.
- `backup.verify_sample()` set kimliği veya verilen seed ile tekrarlanabilir
  rastgele örneklem seçiyor ve blob SHA-256'larını yeniden hesaplıyor.
- İzole test, tek orijinal + tek rendition ile snapshot → dışlama → restore →
  kasıtlı blob bozulmasını yakalama zincirini gerçek dosya sistemi üzerinde
  doğruluyor (`test_retention_gc.py::TestBackupDrTatbik`).

## RPO/RTO kararı

- Yerel snapshot hedef RPO: **24 saat**.
- Tek dosya hedef RTO: **≤ 5 dakika**; bu tatbikatta dosya katmanı **280,7 ms**.
- Tam disk hedef RTO: **≤ 4 saat**; uzak depodan ağ aktarımı üretim
  altyapısında ayrıca ölçülmelidir.
- Site + DB hedef RTO: **≤ 8 saat**; DB restore süresi bu medya tatbikatının
  kapsamı dışındadır.

Bu kanıt geliştirme ortamı içindir. Üretimde 3-2-1 kuralını tamamlayan uzak
kopya, zamanlayıcı alarmı ve üç aylık restore tatbikatı operasyon sahibi onayıyla
açılmalıdır; bu insan/altyapı kapısı kod tarafından geçilmiş sayılmaz.
