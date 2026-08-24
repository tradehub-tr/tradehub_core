# 15 — T-015 istemci tarafı işleme bütçesi

**Tarih:** 2026-08-23 · **Durum:** prototip/üretim fallback'i tamam, gerçek cihaz laboratuvarı açık

## Uygulanan karar

Karar motoru `admin-panel/frontend/src/lib/media/upload/deviceBudget.js`, Vue
yükleme akışı `useMediaUpload.js`, prototip girişi
`prototypes/client-budget/index.ts` içindedir. `deviceMemory`,
`hardwareConcurrency`, iOS/iPadOS sinyali, `createImageBitmap`, Worker ve runtime
canvas probe birlikte değerlendirilir. Runtime ölçümü politika tavanını yalnız
daraltabilir; büyütemez.

| Cihaz sınıfı | Decode | Resize | Encode | Davranış |
|---|---:|---:|---:|---|
| Düşük / iOS muhafazakâr | 12 MP | 8 MP | 6 MP | Büyük kaynak doğrudan sunucuya |
| Orta | 25 MP | 16 MP | 12 MP | Uygun kaynak worker'da |
| Yüksek masaüstü | 50 MP | 32 MP | 24 MP | Uygun kaynak worker'da |
| Bilinmeyen | 12 MP | 8 MP | 6 MP | Muhafazakâr sınıf |

Bu tablo **ölçülmüş cihaz sonucu değil, güvenli başlangıç politikasıdır**.
Worker veya `createImageBitmap` yoksa ana iş parçacığında riskli decode
denenmez. MP/canvas tavanı aşılırsa orijinal yükleme devam eder,
`client_budget_server_fallback` bulgusu kuyrukta ve PreflightPanel'de kullanıcıya
görünür. Sıkıştırma hatası da sessizce yutulmaz; aynı fallback'e gider.

## Doğrulama

`deviceBudget.test.js` 7/7 ve upload queue testleri 10/10 geçer. Kapsananlar:
dört cihaz sınıfı, iPadOS masaüstü UA, tavan içi istemci işlemi, büyük dosyada
sunucu fallback'i, runtime canvas tavanının yalnız daraltması, Worker/bitmap
yokluğu ve canvas probe'un ilk hatada durması.

## Açık laboratuvar kapısı

Fiziksel düşük/orta Android, iPhone/Safari ve masaüstünde 25 MP kaynak;
100 MP bomb, HEIC ve animasyonlu GIF için süre/çökme/canvas alanı henüz
ölçülmedi. Safari için internetteki yaklaşık 16,7 MP değeri ölçülmüş proje
sonucu gibi yazılmadı. `probeCanvasCeiling({makeCanvas})` cihaz laboratuvarı
harness'idir. Bu dört gerçek cihaz satırı dolmadan T-015'in “ölçüm” kabul
kriteri tamamlanmış sayılmaz; fallback kodu ise şimdiden çalışır durumdadır.

