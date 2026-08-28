# 111 — Bulk Localization: panel düğmesi + canlı ölçüm (Görev 3/3)

**Tarih:** 2026-08-27
**Ortam:** `istoc-dev-backend-1`, site `istoc.localhost` (yerel dev).
**Kapsam:** Dilim 8'in (Bulk Localization) SON görevi — panelde "Çeviri
backfill" düğmesi, i18n anahtarları, T2'den devreden 1 docstring cümlesi ve
gerçek katalogda `backfill_localization` canlı koşumu + ölçümü.

Yöntem (rapor 106-110 ile aynı kısıt): `docker cp` ile konteynere taşınan
tek seferlik script'ler, `bench --site istoc.localhost console` içine
`echo "exec(open('/tmp/....py').read(), {})" | bench ... console` ile
beslendi. **Bu görevde `frappe.db.commit()` çağrıldı** — talimatın kendisi
gereği: `backfill_localization` kural-tabanlı, idempotent ve L1/L6 korumalı
bir yazma işidir, koşumun kendisi ölçümün parçası (kullanıcı onayı gerekmez).

---

## 1. Yapılan değişiklikler

### 1.1 Backend — T2'den devreden docstring cümlesi

`tradehub_core/media/seo_generate.py::backfill_localization` docstring'ine
tek cümle eklendi:

> `limit` her dil için ayrı uygulanır, TOPLAM tavan değildir.

Kodun kendisi zaten böyle davranıyordu (her dil için ayrı `_backfill_adaylari`
+ `refresh_alt` turu); eksik olan yalnız bunun docstring'de açık yazılmasıydı.

### 1.2 Panel — "Çeviri backfill" düğmesi

`admin-panel/frontend/src/views/system/MediaSeoView.vue`: mevcut `backfillAlt`
iki adımlı onay desenini (`confirming` state, tehlike/iptal buton çifti)
birebir izleyen yeni bir dal eklendi (`confirming === 'loc'`). Tetikleyici
düğme `confirming === ''` durumunda `backfillAlt` tetikleyicisinin yanına
kondu (`Languages` ikonu, lucide-vue-next'te zaten kayıtlı).

`admin-panel/frontend/src/composables/useMediaSeo.js`: `backfillAlt`/
`backfillDimensions` ile aynı desende yeni `backfillLocalization(count)`
action'ı — `backfill_media_localization` uçnoktasını çağırır, sonucu
`load({ refresh: true })` ile satırları tazeleyip döndürür.

Toast, backend'in `by_lang` sözlüğünü kısa bir dize özetine çeviriyor
(`summarizeByLang`, örn. `"en: 12, ar: 0, ru: 0"`) — brief'in istediği "tek
toplam sayı yerine dil kırılımı da görünsün" gereksinimi.

i18n (`tr.js` + `en.js`, `mediaSeo` namespace):

| Anahtar | TR | EN |
|---|---|---|
| `action.backfillLocalization` | Çeviri backfill | Translation backfill |
| `action.backfillLocalizationConfirm` | Eminim, üret | Confirm, generate |
| `toast.localized` | `{n} görsele çeviri yazıldı, {s} atlandı. ({byLang})` | `{n} images translated, {s} skipped. ({byLang})` |
| `finding.missing_localized_alt` | Çevrilebilir ALT eksik | Translatable alt text missing |

`ar.js`/`ru.js` **dokunulmadı** — brief açıkça yalnız tr/en istiyordu (rapor
110'da da aynı kapsam kararı verilmişti, `ar.js`/`ru.js` zaten 20/21 mevcut
kodu taşıyan bir borç bırakmıştı). Eksik anahtarlarda vue-i18n fallback
locale'e (`en`) düşer — çeviri kaybolmaz, yalnızca dil değişmez.

**Değişen dosyalar:** `tradehub_core/media/seo_generate.py`,
`admin-panel/frontend/src/composables/useMediaSeo.js`,
`admin-panel/frontend/src/views/system/MediaSeoView.vue`,
`admin-panel/frontend/src/i18n/locales/tr.js`,
`admin-panel/frontend/src/i18n/locales/en.js`.

### 1.3 Panel testi

`MediaSeoView.vue`'ya özel bir test dosyası **yok** (brief: "yoksa YENİ test
dosyası açma") — güvenlik için tüm panel paketi koşuldu:

```
$ npm test   # admin-panel/frontend
ℹ tests 1393
ℹ pass 1385
ℹ fail 3
ℹ skipped 5
```

3 başarısızlık **bu değişiklikten önce de var, ilgisiz** (rapor 110'da da
aynı 3): `contract.live.test.js` içindeki 2 canlı-API zaman aşımı ve
`policyEngineParity.test.js`'in `engine.py` hash-eşleşme kontrolü — hiçbiri
bu görevde dokunulan dosyalarla ilgili değil. `npm run build` de temiz
(`MediaSeoView-*.js` bundle'ı üretildi, hata yok).

---

## 2. Canlı ölçüm — yöntem

```
$ docker cp seo_generate.py istoc-dev-backend-1:.../media/seo_generate.py
$ docker cp olcum_111.py istoc-dev-backend-1:/tmp/olcum_111.py
$ docker exec -i istoc-dev-backend-1 bash -c \
    'echo "exec(open(\"/tmp/olcum_111.py\").read(), {})" | bench --site istoc.localhost console'
```

Script sırasıyla: (1) `title_{lang}` doluluk sayımı, (2) 300 url'lik bir
örneklemde `seo_audit.audit_batch` ile ÖNCE skoru + `missing_localized_alt`
sayısı, (3) `seo_generate.backfill_localization(limit=2000)` — GERÇEK yazma,
`frappe.db.commit()` fonksiyon içinde çağrılıyor, (4) aynı çağrı ikinci kez —
idempotentlik kanıtı, (5) aynı örneklemde SONRA skoru + sayısı.

---

## 3. Kaynak-çeviri doluluğu (dürüst taban)

| Ölçü | Değer |
|---|---:|
| `Listing` (storefront_visible=1) toplam | **2.723** |
| `title_en` dolu | **199** (%7,3) |
| `title_ar` dolu | **199** (%7,3) |
| `title_ru` dolu | **199** (%7,3) |

Aynı 199 kayıt üçünde de dolu — dev seed verisinde çeviri tek bir kaynaktan
(muhtemelen aynı içe aktarma turu) geldiği anlaşılıyor.

**Kritik bulgu — bu 199 kaydın TAMAMI harici görsel kullanıyor:**

| Ölçü | Değer |
|---|---:|
| `title_en` dolu VE `primary_image` harici URL (`https://cdn.dummyjson.com/...`) | **199 / 199** |
| `title_en` dolu VE `primary_image` yerel `File` kaydına bağlı | **0** |
| Katalog genelinde harici `primary_image` taşıyan TÜM storefront_visible kayıt | **199** |

Yani harici-görselli kayıt kümesi ile çevirisi-olan kayıt kümesi **birebir
aynı küme**. `backfill_localization`'ın aday sorgusu (`_backfill_adaylari`)
yalnız `tabFile`'da GERÇEK bir kayda sahip, Listing'e bağlı adresleri tarar
(`media/seo_generate.py` docstring'i, TUR-135 §5.1) — harici URL'ler için
hiç `File` satırı yok, dolayısıyla bu 199 kayıt aday kümesine **hiç girmiyor**.

---

## 4. `backfill_localization(limit=2000)` — koşum 1 (gerçek yazma)

```json
{
  "scanned": 5979, "written": 0, "skipped": 5979,
  "reasons": { "no_translation": 5979 },
  "by_lang": {
    "en": { "scanned": 1993, "written": 0, "skipped": 1993, "reasons": { "no_translation": 1993 } },
    "ar": { "scanned": 1993, "written": 0, "skipped": 1993, "reasons": { "no_translation": 1993 } },
    "ru": { "scanned": 1993, "written": 0, "skipped": 1993, "reasons": { "no_translation": 1993 } }
  }
}
```

Toast'ta gösterilecek özet: **"en: 0, ar: 0, ru: 0 yazıldı"** — bugünkü
ortamda gerçek sonuç budur.

**`no_translation` oranı: %100 (5979/5979).** Kural motoru dürüst
davranıyor: kopyalama yapmadı (L1), hiçbir dil kolonuna yalan çeviri
yazmadı. `1993` (limit değil, gerçek aday sayısı — 2000'in altında,
`limit` her üç dilde de doyurulmadı) her dilde AYNI çünkü aday sorgusu
dile bakmaksızın "Listing'e bağlı, `alt_{lang}` boş, yerel `File`'ı olan"
kümesini döndürüyor; bu üç dilde de aynı 1993 dosyaydı (hiçbiri önceden
kısmen doldurulmamıştı).

**Kök neden zinciri (bağımsız sorgularla doğrulandı):**

| Ölçü | Değer |
|---|---:|
| Listing'e bağlı, yerel `File` kaydı olan benzersiz görsel adresi (katalog geneli) | **1.993** |
| Bunlardan `th_media_alt` (tr) dolu olan | **0** |
| Bunlardan `th_media_alt_en/ar/ru` dolu olan | **0 / 0 / 0** |
| Katalog genelinde toplam public `File` | 5.232 |

Yani bu ortamda **tabanın kendisi (tr alt backfill'i, TUR-135) hiç
koşulmamış** — `th_media_alt` dahi %100 boş. Bu, Dilim 8'in bir hatası
değil; ortamın (yeniden kurulmuş/sıfırlanmış dev site) durum notu.
Localization backfill'i doğru çalışıyor: verilen 1993 adayın hepsini
gerçekten denedi, hepsinde kaynak çevirisi olmadığını (çünkü çeviri sahibi
199 kayıt harici görsel kullanıyor) doğru tespit edip `no_translation` ile
atladı — **sıfır kopyalama, sıfır yanlış pozitif**.

---

## 5. Koşum 2 — idempotentlik kanıtı

```json
{
  "scanned": 5979, "written": 0, "skipped": 5979,
  "reasons": { "no_translation": 5979 },
  "by_lang": { "en": {"written": 0, ...}, "ar": {"written": 0, ...}, "ru": {"written": 0, ...} }
}
```

İkinci koşum **birebir aynı** sonucu üretti (`scanned`/`skipped`/`reasons`
tamamen eşleşiyor). Bu ortamda `written=0` olduğu için "ikinci koşumda 0
yazar" iddiası zaten trivyal doğru; asıl kanıt aday kümesinin de
DEĞİŞMEMİŞ olması (1993=1993 her dilde) — birinci koşum hiçbir satırı
"denendi ama sonuç aynı" (`unchanged`) durumuna sokmadı, ikinci koşum
tamamen aynı adayları tamamen aynı sebeple tekrar denedi. Kabul kriteri 5
("Backfill idempotent; ikinci koşum 0 yazar") **karşılandı**, ama bu
ortamda hem birinci hem ikinci koşum 0 yazdığı için "yazmayı durdurma"
davranışı bu ölçümle **ispatlanamadı** — yalnız "tekrar tekrar çalıştırmak
güvenli, veri bozmuyor" ispatlandı. Gerçek "yazdı → ikincisi 0 yazdı" kanıtı
mevcut birim testlerinde var (`test_media_seo_pipeline.py`,
`TestBackfillAdaylariDilDuyarli` ve ilişkili idempotentlik testleri — bkz.
§7, 82/82 yeşil).

---

## 6. Skor önce/sonra + `missing_localized_alt`

300 url'lik örneklem (storefront_visible=1 ilanların `primary_image`'i,
`modified desc` sıralı):

| Boyut | Önce | Sonra |
|---|---:|---:|
| `localization` | **0** | **0** |
| `overall` | 55 | 55 |
| `missing_localized_alt` (tetiklenme) | **0** | **0** |

**Değişmedi — ve bu beklenen bir sonuç, hata değil.** `backfill_localization`
0 yazdığı için (§4) skor da değişemezdi. `localization=0` de tutarlı: skor
formülü (`_yerellestirme_puani`) 4 dilden kaçında `alt` dolu olduğuna bakıyor
(§seo_audit.py:414-422) — bu örneklemdeki dosyaların hiçbirinde **hiçbir
dilde** (tr dahil) alt metni yok (§4 tablosu), dolayısıyla skor sıfır.
`missing_localized_alt`'ın 0 kalması da doğru sessizlik: kural yalnız
"kaynak çevirisi VAR ama alt boş" durumunda uyarır (L4); bu örneklemde
kaynak çevirisi olan tek küme (199 harici-görselli kayıt) örneklemin
kendisinde muhtemelen hiç yok ya da varsa bile `File` kaydı olmadığı için
`audit_batch`'in `kayitlar` haritasında yer almıyor, kural tetiklenemiyor.

`_KURAL_BOYUT` bütünlüğü: **33** kod (kabul kriteri 7 ile tutarlı, T1/T2'de
zaten sabitlenmişti — bu görevde değişmedi).

---

## 7. Test koşumu — backend

```
$ docker cp seo_generate.py istoc-dev-backend-1:.../media/seo_generate.py
$ docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests \
    --module tradehub_core.tests.test_media_seo_pipeline
Ran 82 tests in 6.113s
OK
```

82/82 yeşil (T1/T2'nin bıraktığı tam modül + bu görevde eklenen 0 yeni test —
görev kapsamı yalnız docstring). `ruff check` (container içinde,
`seo_generate.py` üzerinde): **All checks passed!**. `media_admin.py`
üzerinde 1 önceden var olan, ilgisiz `F401` (kullanılmayan `video_poster`
import'u, satır 1609 — bu görevde dokunulan `backfill_media_localization`
uçnoktasından ~180 satır uzakta, bu görevin kapsamı dışı, düzeltilmedi).

**`docker cp` gerekliliği:** Konteynerdeki `apps/tradehub_core` host reposunun
bind-mount'u değil, imaj build'inde gömülü ayrı bir kopya (rapor 110'daki
aynı not). Bu görevde değiştirilen tek backend dosyası
(`tradehub_core/media/seo_generate.py`) `docker cp` ile geçici taşındı —
**imaj rebuild edilmedi, recreate/migrate çalıştırılmadı.**

---

## 8. Öz-denetim

- **Tüm sayılar gerçek sorgu/koşum çıktısı** — tahmini/yuvarlanmış değer yok.
  `backfill_localization` GERÇEKTEN çağrıldı (2 kez), `frappe.db.commit()`
  fonksiyon içinde çalıştı; script kendisi ek `commit()` çağırmadı (gerek
  yoktu, fonksiyon zaten çağırıyor).
- **"0 yazıldı" dürüstçe raporlandı ve kök nedeni izlendi** — yüzeysel "kural
  çalışmıyor" sonucuna varmak yerine üç ayrı doğrulama sorgusuyla (title_en
  doluluk × harici URL kesişimi, yerel-File evreni, tr alt taban durumu)
  gerçek nedenin veri şekli (çeviri sahibi kayıtların hepsi harici görsel
  kullanıyor) olduğu gösterildi.
- **SEO değeri çeviri geldikçe doğar** — mekanizma (kural zinciri, dil
  parametresi, `by_lang` sayaçları, `no_translation` ayrımı, L1/L6 koruması)
  kanıtlanmış durumda: 1993 gerçek adayın tamamı doğru sebeple, sıfır
  kopyalamayla atlandı. Bugün 0 yazılmasının nedeni motorda değil, veride —
  yerel dosyaya bağlı hiçbir ilanın gerçek bir dil çevirisi yok. Yerel
  görsellere bağlı ilanlar `title_{lang}` alanlarını doldurmaya başladığı an
  (örn. içerik ekibi çeviri girdikçe ya da harici görseller yerelleştirildikçe)
  aynı düğme aynı mekanizmayla gerçek `alt_{lang}` üretecek — kod bunun için
  hazır, bekleyen taraf içerik.
- **İdempotentlik kısmi kanıtlandı canlı ortamda** (§5) — "yazdıktan sonra
  ikincisi 0 yazar" kolu birim testlerle (§7, 82/82) kapatılıyor, bu ortamda
  canlı veri her iki koşumda da 0 yazdığı için tam döngü demonstre
  edilemedi; bu bir eksiklik olarak burada açıkça not edildi.
- **Panel işi minimal ve mevcut deseni birebir izledi** — yeni component/route
  yok, `backfillAlt`in iki adımlı onay + toast deseni aynen tekrarlandı.
- **Yazma disiplini:** commit YOK, `git add` YOK, yeni branch YOK, subagent
  YOK. `docker cp` geçici (imaj rebuild edilmedi). Panel değişiklikleri
  yalnız `npm run build` ile derlendi, canlıya deploy edilmedi.
