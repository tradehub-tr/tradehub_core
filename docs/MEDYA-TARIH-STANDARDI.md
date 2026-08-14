# Medya Tarih ve Saat Standardı

**TUR-124** · Faz 1 · 2026-08-14

---

## 1. Ölçüm — bulunan hata

Sunucu medya tarihlerini **saat dilimi işareti olmadan** gönderiyordu:

```
2026-08-14 09:39:06.911581
```

Bu dize tek anlamlı değil. Tarayıcı onu **kendi yerel saati** sanıyor. Aynı
yükleme kaydının farklı kullanıcılarda nasıl göründüğü ölçüldü:

| Kullanıcının saat dilimi | Gördüğü | Olması gereken |
|---|---|---|
| İstanbul | 09:39 | 09:39 ✅ |
| Londra | 09:39 | 07:39 ❌ |
| New York | 09:39 | 02:39 ❌ |
| Tokyo | 09:39 | 15:39 ❌ |
| Sidney | 09:39 | 16:39 ❌ |

Herkes **aynı rakamı** görüyordu. Sunucu İstanbul olduğu için yalnız Türkiye'deki
kullanıcı doğru saati görüyordu. Panel dört dili destekliyor (TR, EN, AR, RU) —
yurtdışındaki satıcı dosyasını saatler önce ya da sonra yüklenmiş sanıyordu.

### Panelde dört ayrı biçimlendirme

| Ekran | Görünüm | Sorun |
|---|---|---|
| Medya kütüphanesi | `14 Ağu 2026` | Saat yok |
| Yedek ekranı | `14 Ağu 2026 09:39` | — |
| Optimizasyon | `14.08.2026` | **Dil sabit `tr-TR`** — kullanıcının dili yok sayılıyordu |
| Denetim | `2026-08-14 09:39` | **Ham dize kırpma** — ne dil ne saat dilimi |

Aynı veri dört ekranda dört türlü görünüyordu.

---

## 2. Karar

### Saklama — DEĞİŞMİYOR

Veritabanı Frappe'nin biçiminde kalıyor (`datetime`, sunucu saatinde).
Değiştirmek medyanın kapsamını çok aşar; tüm sistem buna dayalı.

### API çıktısı — ISO 8601 + saat dilimi kayması

Tarih dışarı çıkarken tek anlamlı hâle getiriliyor:

```
2026-08-14T09:39:06+03:00
```

| Parça | Neden |
|---|---|
| `T` ayıracı | ISO 8601 gereği; boşluklu biçim bazı tarayıcılarda ayrıştırılamıyor |
| Saniye çözünürlüğü | Mikro saniye hiçbir ekranda gösterilmiyor, ayrıştırmayı zorlaştırıyor |
| `+03:00` kayması | Dizeyi tek anlamlı yapan şey bu — hatanın kaynağı buydu |

### Panel gösterimi — tek kaynak

Dört biçimlendirme `utils/dateFormat.js` altında birleşti:

| Fonksiyon | Çıktı | Nerede |
|---|---|---|
| `formatDay` | `14 Ağu 2026` | Liste, kart, detay |
| `formatDateTime` | `14 Ağu 2026 09:39` | Yedek, denetim |
| `formatClock` | `09:39` | Denetim satır içi |
| `formatAgo` | `5 dk önce` | Denetim akışı |
| `toTimestamp` | sayı | Sıralama ve karşılaştırma |

Hepsi kullanıcının **dilini** ve **saat dilimini** dikkate alıyor.

### Zaman dilimi stratejisi

```
saklama    sunucu saati (Europe/Istanbul)
taşıma     ISO 8601 + kayma — mutlak an
gösterim   kullanıcının kendi saat dilimi
```

Kullanıcı için kural şu: **gördüğü saat kendi saatidir.** Sunucunun nerede
olduğunu bilmesi gerekmiyor.

---

## 3. Eski biçime dayanıklılık

Sunucunun her ucu aynı anda güncellenmiyor. Panel üç biçimi de kabul ediyor:

| Gelen | Yorum |
|---|---|
| `2026-08-14T09:39:06+03:00` | Yeni standart — olduğu gibi |
| `2026-08-14T09:39:06` | İşaretsiz — sunucu saati varsayılır |
| `2026-08-14 09:39:06.911581` | Eski Frappe biçimi — düzeltilip okunur |

Üçü de **aynı ana** çözülüyor (test edildi). Böylece henüz dönüştürülmemiş bir
uç, ekranı bozmuyor.

---

## 4. Sıralama ve filtreleme

Kabul kriteri *"tarih bazlı sıralama ve filtreleme tutarlı çalışmalı"*.

ISO 8601'in asıl değeri burada: **alfabetik sıra = zaman sırası.** Karışık
biçimler yan yana geldiğinde metin karşılaştırması yanıltıcı olurdu; bu yüzden
sıralama `toTimestamp` üzerinden sayıya çevrilerek yapılıyor.

Sunucu tarafında sıralama zaten veritabanı sütunu üzerinden yapılıyor ve
biçim değişikliğinden etkilenmiyor — iki yönde de tutarlılığı test edildi.

---

## 5. Neyin kapsamda olmadığı

| Konu | Nerede |
|---|---|
| Medya dışı ekranların tarihleri | Bu görev yalnız medyayı kapsıyor |
| Kullanıcının saat dilimini seçebilmesi | Şu an tarayıcınınki kullanılıyor |
| Arama/filtrede tarih aralığı arayüzü | TUR-134 |
| Veritabanı saklama biçimi | Değiştirilmiyor — sistem geneli |

---

## 6. Nasıl doğrulandı

**Backend 14 test:** saklama biçimi korunuyor · envanter ve denetim çıktısı
standartta · kayma doğru · mikro saniye sızmıyor · satırdaki tüm tarih alanları
aynı kuralda · 3 000 girdilik fuzz · sıralama iki yönde tutarlı · gün filtresi
çalışıyor · regresyon.

**Panel 12 test:** üç giriş biçimi aynı ana çözülüyor · işaretsiz tarih sunucu
saati sayılıyor · bozuk girdi çökmüyor · dil değişince ay adı değişiyor ·
mikro saniye gösterime sızmıyor · göreli zaman eşikleri · gelecek tarih
negatife düşmüyor · karışık biçimler doğru sıralanıyor.

**Saat dilimi kanıtı** — aynı kayıt, beş bölge:

```
Europe/Istanbul    14 Ağu 2026 09:39
Europe/London      14 Ağu 2026 07:39
America/New_York   14 Ağu 2026 02:39
Asia/Tokyo         14 Ağu 2026 15:39
Australia/Sydney   14 Ağu 2026 16:39
```
