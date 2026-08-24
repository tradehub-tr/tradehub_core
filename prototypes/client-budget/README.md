# T-015 istemci bütçesi prototipi

Kanonik TypeScript giriş noktası `index.ts`; çalışan üretim uygulaması admin
panelde `src/lib/media/upload/deviceBudget.js` dosyasındadır. Karar saf ve test
edilebilirdir: cihaz sınıfı ile decode/resize/encode MP bütçesinin dar olanı
kazanır. Bütçe aşılırsa yükleme reddedilmez; orijinal sunucuya gider ve kuyruk
satırında görünür `client_budget_server_fallback` bilgisi kalır.

Gerçek cihaz ölçümü otomatik çalışmaz. Laboratuvar sayfası
`probeCanvasCeiling({ makeCanvas })` çağırıp sonucu cihaz/işletim sistemi/
tarayıcı sürümüyle birlikte rapora eklemelidir. Politikadaki varsayılan MP
değerleri ölçüm sonucu diye sunulmaz.
