# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Kimlik bilgisi maskeleme — SAF fonksiyonlar, Frappe bağımlılığı YOK.

NEDEN FRAPPE'SİZ:
	Maskeleme, log yazımının en kritik parçası. Frappe'ye (dolayısıyla siteye,
	veritabanına, bench'e) bağlı olsaydı yalnız entegrasyon testinde
	doğrulanabilirdi. Burada saf tutulduğu için düz `python -m unittest` ile de,
	bench içinden de aynı şekilde koşar; bir kimlik bilgisinin log'a düşüp
	düşmediği sorusu asla "ortam kurulu muydu"ya bağlı kalmaz. Uyarılar bu
	yüzden `frappe.log_error` ile değil stdlib `logging` ile yazılır.

İKİ KATMANLI SAVUNMA — sıra önemlidir:

1. **DEĞER-TABANLI REDAKSİYON (birincil).** `secret_values` ile verilen
   dizgiler gövdede/başlıkta/hata metninde BİREBİR aranır ve `***` ile
   değiştirilir. Bu katman girdinin BİÇİMİNDEN bağımsızdır: SOAP, base64,
   querystring, `requests` istisna metni — hepsinde çalışır. Gerekçe: istek
   ZATEN BİZİM kurduğumuz istektir; sır materyalinin değerleri çağrı anında
   bilinir. Anahtar adını tahmin etmek yerine değeri aramak, "tanımadığım
   biçim = maskeleme yok" kaçışını kapatır.

   ⚠️ BU KATMAN OPSİYONEL DEĞİL, ZORUNLU SAYILMALIDIR. `secret_values`
   verilmediğinde `{'X-Trace': <jeton>}` gibi beklenmedik bir taşıma HAM
   kalır — anahtar denylist'i `x_trace`'i tanımaz ve tanıyamaz. Çağıran
   tarafın `secret_values` geçmemesi "sır yoktu" anlamına GELMEZ; bu yüzden
   `log.py::write_integration_log` argüman hiç verilmediğinde uyarı yazar.

2. **ANAHTAR DENYLIST'İ (ikincil).** Değer bilinmediğinde (ör. taşıyıcının
   YANITINDA dönen bir oturum jetonu) tek savunma budur. Anahtar eşleşmesi
   ayraç/büyük-küçük harf duyarsızdır, camelCase'i ayrıştırır, JSON/
   querystring/XML-element/XML-öznitelik/HTTP-başlık/YAML/Python-repr
   biçimlerini kapsar.

TÜRKÇE NORMALİZASYON — `str.lower()` YETMEZ:
	`'İ'.lower()` Python'da `'i'` DEĞİL, `'i' + U+0307` (birleştirici nokta)
	döndürür; `casefold()` de aynıdır. Bu yüzden `ŞİFRE`/`MÜŞTERİ_KODU` gibi
	TR klavyede VARSAYILAN yazımlar denylist'e hiç uğramıyordu (ölçüldü).
	`_fold` birleştirici noktayı atar, ayrıca ASCII katlanmış bir ikinci
	aday üretir (`şifre` → `sifre`) ki denylist'in iki yazımını da tutmak
	zorunda kalmayalım. Aynı şekilde camelCase sınırı `[A-Z]` ile
	ARANMAZ — Python str regex'inde `[A-Z]` SALT ASCII'dir ve `musteriŞifre`
	bölünmezdi; sınır `str.isupper()` ile programatik bulunur.

	ÜÇ EK NORMALİZASYON ADIMI (hepsi ölçülmüş sızıntıdan doğdu):
	  * **NFKC.** Girdi NFD ayrıştırılmış gelebilir (`ş` = `s` + U+0327);
	    `NFD('ŞİFRE')` ve `NFD('şifre')` HAM sızıyordu. NFD macOS kaynaklı
	    gövdelerin ve bazı Java/.NET SOAP yığınlarının varsayılanıdır.
	  * **Harf↔rakam sınırı.** `Sifre2`, `password2`, `apiKey2`, `Kod2` tek
	    segment kaldıkları için denylist'e HİÇ uğramıyordu — oysa ayraçlı
	    kardeşleri (`secret_2`) maskeleniyordu. TR kargo SOAP'ı çok hesaplı
	    kurulumlarda rutin olarak `Sifre2`/`MusteriKodu2` taşır.
	  * **Ayraçsız yazım.** `_key_forms` her adın `_` silinmiş hâlini üretir.

NEDEN SABİT "***":
	Kısmi maskeleme (`abcd…efgh`) hem uzunluk hem de baş/son karakter ipucu
	sızdırır; kısa bir API anahtarında bu bilginin kendisi saldırıya yardım eder.
	`mask_value` her zaman aynı sabiti döndürür — uzunluk ipucu bile verilmez.

TEK KÜME KURALI:
	Aynı içerik dict, JSON metni ya da querystring olarak gelse de AYNI sonucu
	verir. Anahtar kümesi tek bir varsayılandan (`DEFAULT_SENSITIVE_KEYS`)
	gelir; sözlük yolu ile metin yolu farklı kümeler kullanmaz. (Eski
	davranışta `{'cookie': 'sid=x'}` dict olarak maskelenmiyor, aynı içerik
	metin olarak maskeleniyordu.)

FAIL-CLOSED VE "ASLA FIRLATMAZ":
	`mask_payload` / `mask_headers` / `mask_mapping` sözleşme gereği İSTİSNA
	FIRLATMAZ. Gerekçe: bunlar `Carrier Integration Log` yazımının hem yazıcı
	hem DocType katmanında çağrılır; birinden sızan bir istisna DENETİM İZİNİ
	tamamen düşürür (3 KB'lık iç içe JSON POST eden bir saldırgan o çağrının
	log satırını engelleyebiliyordu — ölçüldü). Beklenmedik hata durumunda
	`MASK` döner (fail-closed: ham veri ASLA geçmez) ve uyarı loglanır.
	Özyineleme `MAX_MASK_DEPTH` ile açıkça sayılır; `json.loads`'ın
	`RecursionError`'ı da yakalanır.

XML SINIRI — "ANLAYAMADIĞIM YERİ HAM BIRAK" VARSAYIMI TERSİNE ÇEVRİLDİ:
	Üç denetim turu üst üste AYNI sınıftan kenar durumu üretti (CDATA, 64 KiB
	penceresi + kapanışsız etiket, iç içe kapanışsız çocuk). Kök sorun tekil
	hatalar değil, tarayıcının "sınırı bulamadım → geri kalanı olduğu gibi yaz"
	varsayımıydı. Artık ÜÇ KATMAN var ve üçü de ters yönde çalışır:

	(a) **DERİNLİK SAYAN SINIR** (`_ancestor_boundary`). Hassas bir etiketin
	    kapanışı bulunamadığında fail-closed maskeleme "bir sonraki etikete
	    kadar" DEĞİL, "bir ATANIN kapanışına (derinlik < 0) ya da metnin
	    sonuna kadar" uygulanır. İyi biçimli ÇOCUK alt ağaçlar YUTULUR.
	    Eski kural `<Sifre><Deger>SECRET</Deger>` girdisinde sınırı `<Deger>`'in
	    başında buluyor, maskelenecek aralık BOŞ kalıyor ve gövde HAM geçiyordu
	    (ölçüldü — TR kargo SOAP zarfının kanonik biçimi tam budur). Ata
	    kapanışında durmak, `direction="inbound"` gövdesine tek bir
	    `<Password>` ekleyen saldırganın TÜM denetim izini silmesini de
	    engeller: maskeleme `</ata>` görünce biter.

	(b) **EMİN OLAMADIĞINDA FAIL-CLOSED** (`_fail_closed`). Derinlik
	    taraması metnin sonuna AÇIK KALMIŞ çocuklarla (derinlik > 0) ulaşırsa
	    gövde bir elemanın ORTASINDAN kesilmiş demektir — `log.py::MAX_BODY_BYTES`
	    (64 KiB) kırpması maskelemeden ÖNCE yapıldığı için gerçek taşıyıcı
	    yanıtları rutin olarak bu hâlde gelir. O noktada tarayıcının etiket
	    modeli güvenilmezdir. Tarama BÜTÇESİ dolduğunda da aynı yol işler. Bir
	    sonraki kenar durumu SESSİZ SIZINTI yerine GÖRÜNÜR bir işaret üretir.

	    EYLEMİN KAPSAMI 9. TURDA DARALTILDI — YEREL TETİKLEYİCİ, YEREL EYLEM:
	    dört fail-safe dalı TEK bir çözülemeyen `<` yüzünden GÖVDENİN TAMAMINI
	    özete indiriyordu; o `<`ten ÖNCEKİ, tamamen anlaşılmış ve zaten
	    maskelenmiş kısım dahil. 301 kesim noktasında ölçüldü: öznitelikli
	    gövdenin 130'u, CDATA'lı gövdenin 154'ü, düz gövdenin 40'ı TÜM denetim
	    izini siliyordu (JSON gövdede 0 — sorun XML/HTML'e özgü). Bugün eylem
	    `çözülemeyen noktadan ÖNCESİ (korunur) + ***` olur. Sızıntı yönü
	    değişmez: `<`ten sonrası bütünüyle gider.

	    TEK İSTİSNA — ÖN EK BİLGİ TAŞIMIYORSA ÖZET: `<!DOCTYPE html>` ile başlayan
	    bir taşıyıcı/vekil HTML hata sayfasında çözülemeyen dizi metnin ta
	    başındadır ve yerelleştirme yalnız `'***'` üretir — özetten BİLGİ OLARAK
	    DAHA AZ, çünkü bayt sayısı da kaybolur. Orada `<XML gövdesi, N bayt,
	    K hassas alan — sınır çözülemedi>` üretilmeye devam eder; ön ek yokken
	    "gövde buradaydı, şu kadardı" diyen TEK bilgi kaynağı odur.

	    ÖLÇÜT 10. TURDA KONUMSALDAN İÇERİKSELE ÇEVRİLDİ: kapı `lt == 0` idi ve
	    aynı gövde TEK karakterlik bir önekle (boşluk / BOM / satır sonu) 57
	    karakterlik özet yerine 4 karakterlik `' ***'` veriyordu — %93 bilgi
	    kaybı, üstelik docstring'in KENDİ ÖRNEĞİNDE. 8. tur aynı önek listesini
	    (`\\xa0`, `\\u200b`, `ï»¿`, `HTTP 500: `, tek tırnak) SIZINTI kaynağı
	    olarak ölçmüştü; burada aynı liste TEŞHİS KAYBI kaynağıydı. Bugün karar
	    `_carries_information` ile İÇERİK üzerinden verilir. Sızıntı riski SIFIR:
	    seçim iki ZATEN-REDAKTE-EDİLMİŞ çıktı arasındadır.

	(c) **DENGELİ KAPANIŞ EŞLEŞTİRME** (`_find_close_tag`, 7. tur). (a) ve (b)
	    yalnız "sınırı BULAMADIM" durumunu ele alır; 7. tur ÜÇÜNCÜ bir çıkış
	    ölçtü: **"yanlış anladım ama anladığımı sandım."** Kapanış araması
	    DERİNLİK SAYMIYOR, AYNI ADLI bir TORUNUN kapanışını elemanın sınırı
	    sanıyordu. Girdi İYİ BİÇİMLİ olduğu için (a) ve (b)'nin hiçbir fail-safe
	    dalı tetiklenmiyor, sınır POZİTİF dönüyor ve elemanın kalanı HAM
	    yazılıyordu (63 hassas ad × 3 torun derinliği = 189/189 vektör):

	        '<LoginResponse><Kod><Kod>01</Kod>TOKEN</Kod></LoginResponse>'

	    DERS: fail-safe'ler yalnız BİLİNMEYENİ kapsar; YANLIŞ BİLİNENİ kapsamaz.
	    Bir sınır iddiası POZİTİF döndüğünde iddianın DOĞRULUĞU ayrıca sınanmalıdır
	    (bkz. `TestXmlSameNameDescendant.test_positive_boundary_claim_is_true`).

	KAPALI VE İYİ BİÇİMLİ gövdeler (a)/(b) yollarına HİÇ girmez: kapanış etiketi
	bulunduğunda davranış değişmedi, teşhis değeri korunur.

	(d) **ÖZETE İNME ÖLÇÜTÜ — "BU METİN MARKUP MI?"** (`_contains_markup_construct`,
	    8. tur). (a)-(c) hep "XML'in İÇİNDE ne olur"u düzeltti; 8. tur tarayıcının
	    NE ZAMAN ÖZETE İNDİĞİNİ ölçtü. `_mask_text` `error_message`/`request_body`/
	    `response_body` alanlarının HEPSİNE uygulanır ve bunların çoğu XML DEĞİL, düz
	    metindir; özete inme dalları ise metinde HASSAS BİR ŞEY OLUP OLMADIĞINA hiç
	    bakmadan iniyordu:

	        'error: 5 < 10 gecti' → '<XML gövdesi, 19 bayt, 0 hassas alan …>'

	    Yön güvenliydi ama TEŞHİS MALİYETİ kabul edilemez — üstelik özetin KENDİSİ
	    "0 hassas alan" diyordu: mekanizma hiçbir şey saklamadığını İLAN EDEREK tüm
	    teşhisi yok ediyordu.

	    ARA ÇÖZÜM VE ONUN FAIL-OPEN'I (bu turda GERİ ALINDI): aşırı-düzeltme önce
	    metnin BAŞINA bakan bir GİRİŞ KAPISIYLA giderilmişti (baştaki boşluk/BOM
	    atlandıktan sonra `<` + geçerli ad / `?` / `!` yoksa XML tarayıcısı HİÇ
	    koşmuyordu). Kapı aşırı-düzeltmeyi gerçekten kapattı ama GERÇEK SIZINTI
	    üretti. Bağımsız ölçüm (`mask_payload`; `SECRETVALUE123` bir taşıyıcı
	    YANITINDAKİ oturum jetonu yerine geçiyor) 11/11 vektörde HAM çıktı verdi:

	        '\\xa0<Sifre>SECRETVALUE123</Sifre>'          NBSP  U+00A0
	        '\\u2028…' '\\u2029…' '\\u3000…' '\\x85…'     LS / PS / IDSP / NEL
	        '\\u200b<Sifre>…'                            ZWSP  U+200B
	        '\\x00<Sifre>…'                              NULL  U+0000
	        'ï»¿<Sifre>…'                                latin1'e düşmüş BOM
	        'HTTP 500: <Sifre>…'                         HTTP durum öneki
	        'Sunucu hatasi: <soap:Sifre>…</soap:Sifre>'  SOAP fault öneki
	        "'<Sifre>…</Sifre>'"                         tek tırnak sarmalı

	    Değer-tabanlı birincil katman bu sınıfta YARDIM EDEMEZ: taşıyıcının
	    YANITINDA gelen jetonun değerini sistem önceden BİLMEZ (`secret_values`
	    yalnız BİZİM gönderdiğimiz sırları taşır), dolayısıyla etiket-tabanlı
	    maskeleme o sınıfın TEK savunmasıdır.

	    KÖK NEDEN — İKİ AYRI SORU TEK KARARA BAĞLANMIŞTI:
	        1. "Bu metin MARKUP mı?"           → ölçütün cevaplaması gereken soru
	        2. "Markup'ı AYRIŞTIRABİLDİM Mİ?"  → (b)/(c) fail-safe'inin sorusu
	    Metnin BAŞINA bakmak 1. soruyu KONUM üzerinden cevaplıyordu; oysa soru
	    İÇERİKLE ilgilidir. Baştaki tek bir karakter (bir NBSP, bir `HTTP 500:`
	    öneki) markup'ı markup olmaktan ÇIKARMAZ.

	    BUGÜNKÜ ÖLÇÜT: giriş kapısı YOKTUR, XML tarayıcısı yine HER metinde koşar
	    — yukarıdaki 11 vektör bu yüzden normal maskeleme yolundan geçer ve sızıntı
	    sınıfı kapanır. DEĞİŞEN, tarayıcının ÖZETE İNME kararıdır: (b)/(c)'nin dört
	    fail-safe dalı özete inmeden ÖNCE metnin TAMAMINDA yapı-KÖR bir tarama yapar
	    (`_contains_markup_construct`). Metinde markup benzeri TEK BİR yapı bile
	    yoksa özet ÜRETİLMEZ; o ana kadar maskelenmiş kısım + kalan HAM metin döner
	    ve ikincil katmanlar (URL userinfo, `_mask_delimited_pairs`, değer-tabanlı
	    redaksiyon) normal şekilde işler. Böylece:

	        'error: 5 < 10 gecti'         → DEĞİŞMEDEN geçer (markup YOK)
	        'a < b <Sifre>SECRET</Sifre>' → ÖZET (ilk `< b` çözülemiyor AMA
	                                        metinde `<Sifre>` VAR — sızıntı YOK)

	    Fazla sayım GÜVENLİDİR: yorum içindeki `<Sifre>` de markup sayılır, bu
	    yalnız özete indirir, asla ham bırakmaz.

	(e) **ELEMAN HASSASSA ÖZNİTELİKLERİ DE HASSASTIR** (`_mask_tag_attributes`,
	    9. tur). (a)-(d) hep "sınır NEREDE biter"i düzeltti; 9. tur maskelemenin
	    NEREDE BAŞLADIĞINI ölçtü. Hassas bir açılış etiketi bulunduğunda etiketin
	    TAMAMI (öznitelik bloğu dahil) HAM yazılıyor, yalnız İÇERİK `***`
	    yapılıyordu; kendi kendine kapanan hassas etikette ise HİÇ maskeleme
	    yoktu. Koddaki gerekçe "değeri öznitelikte, onu `_mask_delimited_pairs`
	    ele alır"dı ve YANLIŞTI: o katman yalnız ÖZNİTELİK ADINA bakar, "içinde
	    bulunduğun ELEMAN hassas" bilgisini hiç almaz — iki katmanın sözleşmesi
	    tam burada ayrışıyordu. Ölçüm (63 hassas ad × 10 öznitelik adı × 2 şekil):

	        '<Sifre deger="SESSIONTOKEN_ABC999"/>'              → DEĞİŞMEDEN
	        '<Sifre deger="SESSIONTOKEN_ABC999">icerik</Sifre>' → '…">***</Sifre>'

	    1260/1260 vektör HAM sızıyordu, 630'u üstelik YANILTICI maske taşıyordu
	    (`***` görünür, jeton yanındaki öznitelikte durur). Girdilerin hepsi İYİ
	    BİÇİMLİ XML'dir — hiçbir fail-safe dalı tetiklenmez; bu, (c) ile aynı
	    aileden bir "yanlış anladım ama anladığımı sandım" vakasıdır. Bugün hassas
	    elemanın açılış etiketindeki TÜM öznitelik DEĞERLERİ (öznitelik ADINA
	    BAKILMAKSIZIN) maskelenir; adlar ve etiket adı teşhis için KORUNUR. Hassas
	    OLMAYAN elemanın öznitelikleri bu yola HİÇ girmez. 10. TURDA TEK İSTİSNA
	    EKLENDİ: öznitelik adı `NON_SENSITIVE_KEYS`te TAM AD olarak varsa değeri
	    BIRAKILIR — kural o kümeyi tamamen atlıyordu ve `<Kod tracking_number=…>`
	    (TR kargo XML'inin en yaygın sonuç elemanı) gövdesinde operatörün
	    belgelenmiş kaçış kapısı ÇALIŞMIYORDU. Ölçüm `_mask_tag_attributes`te.

TEK KÜME KURALI, ANAHTAR KONUMU DA DAHİL (10. tur):
	Değer-tabanlı birincil katman sözlük yolunda YALNIZ değerlere uygulanıyordu;
	`{'SUPERSECRET123': 'v'}` anahtarı HAM geçerken aynı içerik JSON metni
	(`'{"SUPERSECRET123":"v"}'` → `{"***": "v"}`) ve querystring (`'…=v'` →
	`'***=v'`) olarak doğru maskeleniyordu — modülün kendi ilan ettiği kuralın
	ÖLÇÜLMÜŞ ihlali. `_mask_mapping` artık anahtarı da redaksiyondan geçirir;
	SIRA kritiktir (önce ad-tabanlı denylist, sonra anahtar redaksiyonu) ve
	teşhis anahtarları ANAHTAR konumunda görünür kalır. Ayrıntı orada.

	11. TURDA AYNI BOŞLUK BAŞLIK TARAFINDA ÖLÇÜLDÜ: `mask_headers` kendi
	döngüsünde anahtarı redaksiyondan GEÇİRMİYORDU. Yazıcı yolu (`log.py::
	_redact_deep`) bunu kapatıyordu ama `mask_headers` PUBLIC bir API'dir ve
	doğrudan çağrıldığında `{'SUPERSECRET123': 'v'}` başlığının ADI HAM
	geçiyordu. Savunma, çağıranın hangi kapıdan girdiğine bağlı olamaz.

ANAHTAR/DEĞER SINIRI — AYNI DOKTRİN, 10. TURDA KEY/VALUE TARAFINA UYGULANDI:
	XML tarayıcısı 7. turda "sınırı güvenle belirleyemiyorsan HAM BIRAKMA, kapat"
	kuralını öğrendi; `_mask_delimited_pairs` o kuralı HİÇ ALMAMIŞTI ve hâlâ
	"anlayamadığım yeri ham bırak" varsayımıyla çalışıyordu. Anahtar DOĞRU
	tanınıyor, ama değerin KAPANIŞ TIRNAĞI (ya da kapanış parantezi)
	bulunamayınca `_scan_value` `None` dönüyor ve DEĞER HİÇ MASKELENMİYORDU:

	    '{"a":1,"sifre":"SESSIONTOKEN_ABC999'   → DEĞİŞMEDEN (SIZINTI)
	    'sifre="SESSIONTOKEN_ABC999'            → DEĞİŞMEDEN (SIZINTI)
	    "sifre='SESSIONTOKEN_ABC999"            → DEĞİŞMEDEN (SIZINTI)
	    "auth=('user','SESSIONTOKEN_ABC999"     → DEĞİŞMEDEN (SIZINTI)

	Şekil TEORİK DEĞİL: `log.py::MAX_BODY_BYTES` (64 KiB) kırpması otomatiktir
	ve gövdenin SONUNDAN keser; kesim bir değerin ortasına düştüğünde tam olarak
	bu şekil oluşur. 301 kesim noktalı süpürmede JSON gövdenin 4'ü, Python-repr
	gövdenin 4'ü ham sızıyordu (fix sonrası ikisi de 0). `direction="inbound"`
	webhook gövdeleri ayrıca karşı tarafın kontrolündedir.

	`strip_partial_secret_tail` bu boşluğu KAPATMAZ: o yalnız DEĞER-tabanlı
	katmanın kuyruğunu temizler ve sırrın DEĞERİNİN önceden bilinmesini
	gerektirir. Taşıyıcının YANITINDA gelen bir jetonun değeri bilinmez; orada
	tek savunma ANAHTAR-tabanlı bu katmandır.

	BUGÜN: sınır bulunamazsa değer METNİN SONUNA kadar maskelenir. Eylem 9. tur
	kuralına uygun şekilde YERELDİR — çözülemeyen noktadan ÖNCESİ korunur.
	Takas ve reddedilen "satır sonuna kadar" alternatifi `_scan_value`
	docstring'inde ölçümüyle birlikte yazılı.

	11. TUR — AYNA GÖRÜNTÜSÜ: 10. tur ayraçtan SONRAKİ boşluğu düzeltti, ayraçtan
	ÖNCEKİ sınıf (`_PAIR_KEY_RE`) `[ \t]{0,8}` olarak KALDI. XML 1.0
	`Eq ::= S? '=' S?` boşluğu `=`in İKİ YANINDA da meşru sayar; `sifre\\n="TOKEN"`
	ve hizalama boşluklu `sifre          ="TOKEN"` HİÇ maskelenmiyordu
	(20160 vektörün 10080'i ham). Sınıf bugün SİMETRİKTİR: `[ \\t\\r\\n]`, üst
	sınırsız. Aşırı maskeleme takası, reddedilen "en fazla bir satır sonu"
	alternatifi ve ReDoS gerekçesi `_PAIR_KEY_RE` yorumunda ölçümüyle yazılı.

	DERS (bu turun kendisi): bir sınırın İKİ YANI varsa, bir yanı düzeltmek
	ötekini düzeltmez — kapatılan her sızıntı için AYNASI ayrıca ölçülmelidir.

YANLIŞ POZİTİF ÖDÜNLEŞMESİ (bilinçli):
	Denylist segment tabanlıdır: anahtarın HERHANGİ bir bitişik segment dizisi
	denylist'te ise alan maskelenir. `token_status_code` gibi teşhis amaçlı
	görünen bir ad da maskelenir. Bu FAIL-CLOSED tercihtir: bir teşhis alanını
	kaybetmenin maliyeti, bir oturum jetonunu log'a düşürmenin maliyetinden
	küçüktür. Gerçekten gereken teşhis alanları `NON_SENSITIVE_KEYS`'e TAM AD
	olarak eklenir — son ek olarak değil (bkz. o kümenin gerekçesi).
"""

from __future__ import annotations

import base64
import json
import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping
from decimal import Decimal
from functools import lru_cache
from typing import Any
from urllib.parse import quote, quote_plus

#: Modülün public yüzeyi — kardeş modüllerdeki (`log.py`) konvansiyonla aynı
#: konumda: import bloğunun HEMEN ALTINDA. Dosya sonundayken aynı pakette iki
#: ayrı konvansiyon vardı ve "bu ad dışarıya açık mı" sorusu 1150 satır aşağıda
#: cevaplanıyordu.
#:
#: TEST SÖZLEŞMESİ (üretim tüketicisi YOK, yalnız testler kilitler):
#: 	`DEPTH_EXCEEDED` ve `BASE64_VARIANT_MIN_LENGTH` bir API değil, ölçülmüş bir
#: 	davranışın adıdır — testler sabit metni/eşiği kopyalamak yerine buradan
#: 	okur. Üretim kodu bunlara dayanmamalıdır.
__all__ = [
	"BASE64_VARIANT_MIN_LENGTH",  # test sözleşmesi
	"DEFAULT_SENSITIVE_KEYS",
	"DEPTH_EXCEEDED",  # test sözleşmesi
	"MASK",
	"MAX_MASK_DEPTH",
	"MIN_NUMERIC_SECRET_LENGTH",
	"MIN_SECRET_LENGTH",
	"NON_SENSITIVE_KEYS",
	"SENSITIVE_HEADER_KEYS",
	"SENSITIVE_KEYS",
	"XML_BOUNDARY_UNRESOLVED",  # test sözleşmesi
	"build_secret_variants",
	"is_sensitive_key",
	"mask_headers",
	"mask_mapping",
	"mask_payload",
	"mask_value",
	"redact_text",
	"redact_with_variants",
	"secret_texts",
	"strip_partial_secret_tail",
]

#: Modül uyarıları — Frappe'siz kalabilmek için stdlib logging.
_LOGGER = logging.getLogger("tradehub_core.logistics.masking")

#: Değeri ASLA log'a yazılmayacak GÖVDE anahtarları (küçük harfe indirgenmiş).
#:
#: TR kargo entegrasyonları Türkçe alan adı kullanır (`sifre`, `musteri_kodu`);
#: İngilizce-only bir liste bu sistemde neredeyse hiçbir şey yakalamaz.
#:
#: BİTİŞİK YAZIM: `accesstoken`, `clientsecret`, `privatekey` gibi ayraçsız
#: yazımlar ELLE eklenmez — `_key_forms` her girdinin `_` silinmiş hâlini
#: OTOMATİK üretir. Bu yüzden buraya ayraçlı kanonik ad yazmak yeter.
SENSITIVE_KEYS: frozenset[str] = frozenset(
	{
		# --- İngilizce, klasik ---
		"api_key",
		"api_secret",
		"apikey",
		"password",
		"passwd",
		"pwd",
		"passphrase",
		"secret",
		"client_secret",
		"token",
		"access_token",
		"refresh_token",
		"id_token",
		"session_token",
		"authorization",
		"http_auth",
		"webhook_secret",
		"x-api-key",
		"credential",
		"credentials",
		"username",
		"user_name",
		"auth",
		"bearer",
		"pin",
		"otp",
		# --- Türkçe ---
		"sifre",
		"şifre",
		"parola",
		"kullanici_adi",
		"kullanıcı_adı",
		"kullanici",
		"kullanıcı",
		"musteri_kodu",
		"müşteri_kodu",
		"musteri_no",
		"müşteri_no",
		"kod",
		"gizli_anahtar",
		# --- Kripto / imza ---
		"key",
		"private_key",
		"public_key",
		"certificate",
		"cert",
		"pfx",
		"p12",
		"signature",
		"hmac",
		"nonce",
		"salt",
		# --- Oturum ---
		"session",
		"session_id",
		"sessionid",
		"sessid",
		"jsessionid",
		"phpsessid",
	}
)

#: HTTP başlıklarında ek olarak maskelenenler.
SENSITIVE_HEADER_KEYS: frozenset[str] = SENSITIVE_KEYS | frozenset(
	{
		"cookie",
		"set-cookie",
		"proxy-authorization",
		"www-authenticate",
		"x-auth-token",
		"x-csrf-token",
		"x-session-token",
	}
)

#: Varsayılan küme — SÖZLÜK ve METİN yolları AYNI kümeyi kullanır.
#:
#: Küme seçimi tek yerde: gövdeye başlık adları da uygulanır. Fazladan yedi ad
#: yüzünden yanlış pozitif riski, `{'cookie': ...}` gibi bir içeriğin dict
#: olarak sızması riskinden çok daha küçük.
DEFAULT_SENSITIVE_KEYS: frozenset[str] = SENSITIVE_HEADER_KEYS

#: ASLA maskelenmeyecek TEŞHİS alanları — YALNIZ TAM AD eşleşmesinde geçerli.
#:
#: Çıplak `key`/`auth`/`kod` denylist'e girince `idempotency_key` gibi teşhis
#: için zorunlu alanlar da maskelenirdi; bir sevkiyatın hangi idempotency
#: anahtarıyla gönderildiğini göremeyen operatör çift-gönderim vakasını
#: çözemez. Bu liste o zararı kapatır ve KAPSAMI DAR tutulur.
#:
#: ⚠️ SON EK OLARAK UYGULANMAZ — REGRESYON GEREKÇESİ:
#: 	Bu küme eskiden son-ek adaylarının HER seviyesinde denetleniyordu. Sonuç:
#: 	`password_cache_key` / `secret_object_key` / `sifre_hata_kod` MASKELENMİYORDU
#: 	(ölçüldü) — çünkü allowlist son eki (`cache_key`, `hata_kod`) denylist
#: 	segmentini (`password`, `sifre`) geçersiz kılıyordu. Allowlist artık yalnız
#: 	TAM anahtar (ve HTTP satıcı ön eki `x-` sıyrılmış hâli) için bakılır.
#:
#: ⚠️ ALTYAPI ADLARI ÇIKARILDI (`routing_key`, `partition_key`, `sort_key`,
#: 	`primary_key`, `foreign_key`, `cache_key`, `object_key`): bir kargo
#: 	entegrasyonunun teşhisinde bu adlar GEÇMEZ; kümede durmaları yalnız
#: 	`*_key` biçiminde bir saldırı yüzeyi açıyordu.
NON_SENSITIVE_KEYS: frozenset[str] = frozenset(
	{
		"idempotency_key",
		"tracking_number",
		"tracking_code",
		"tracking_key",
		"order_code",
		"order_no",
		"order_number",
		"shipment_code",
		"shipment_no",
		"barcode",
		"barkod",
		"reference_code",
		"reference_no",
		"invoice_no",
		"waybill_no",
		"error_code",
		"status_code",
		"response_code",
		"country_code",
		"currency_code",
		"postal_code",
		"zip_code",
		# TR teşhis kodları — `kod` denylist'te olduğu için açıkça beyaz listede
		"takip_kod",
		"siparis_kod",
		"posta_kod",
		"il_kod",
		"ilce_kod",
		"urun_kod",
		"hata_kod",
	}
)

#: Maskelenen değerin yerine yazılan sabit.
MASK: str = "***"

#: Özyineleme sınırı aşıldığında yazılan işaret.
DEPTH_EXCEEDED: str = "<max depth exceeded>"

#: Maskelemenin izleyeceği azami yapı derinliği.
#:
#: Python'un varsayılan özyineleme sınırı ~1000'dir ve `_mask_any`/`_redact_deep`
#: kare başına birden çok çerçeve harcar. Açık sayaç olmadan 3 KB'lık iç içe bir
#: webhook gövdesi `RecursionError` fırlatıyor ve LOG SATIRINI TAMAMEN
#: DÜŞÜRÜYORDU (ölçüldü) — yani denetim izi saldırgan tarafından bastırılabiliyordu.
MAX_MASK_DEPTH: int = 64

#: Değer-tabanlı redaksiyonda dikkate alınan asgari sır uzunluğu.
#:
#: Daha kısa değerler (`"1"`, `"TR"`, `"AK"`) gövdenin her yerinde geçer;
#: birebir aramak metni harap eder ve log'u okunamaz hale getirir. Kısa bir
#: değer zaten tek başına sır olamaz. Atlanan her değer için UYARI yazılır —
#: sessizce atlamak "redakte edildi sandım" yanılgısı üretir.
MIN_SECRET_LENGTH: int = 6

#: SAYISAL sırlar için asgari RAKAM sayısı — `MIN_SECRET_LENGTH`'in sayısal karşılığı.
#:
#: ÖLÇÜLMÜŞ ÇAKIŞMA (5. tur): 4. tur `int`/`float`'ı sır türü olarak kabul ederek
#: "sessizce düşürme"yi doğru kapattı, ama yeni bir çakışma açtı — 6 haneli
#: SAYISAL bir kimlik `MIN_SECRET_LENGTH=6` eşiğini karşılıyor ve gövdedeki HER
#: geçişi yok ediliyordu:
#:
#:     mask_payload('{"tracking_number":"123456","adet":123456,"tutar":"123456"}',
#:                  secret_values=[123456])
#:         → üçü de `***` (tracking_number ALLOWLIST'te olduğu hâlde)
#:
#: Yön güvenli (fazla redaksiyon) ama teşhis kaybı gerçek: TR taşıyıcılarında
#: müşteri/hesap/şube kodu tipik olarak 4-9 hanelidir ve gövdenin her yerinde
#: MEŞRU olarak geçer. Kısa bir sayı tek başına sır olamaz — tıpkı `"1"`/`"TR"`
#: gibi. Eşik RAKAM SAYISI üzerinden ölçülür (`123456.78` → 8 rakam), böylece
#: ondalık ayraç eşiği sahte olarak doldurmaz. Anahtar-tabanlı denylist
#: (`api_key`, `sifre`, …) bu değerleri ADIYLA maskelemeye devam eder; kapanan
#: yalnız DEĞER-tabanlı ikinci katmandır.
MIN_NUMERIC_SECRET_LENGTH: int = 10

#: Sayısal biçimde kabul edilen karakterler (işaret, ondalık/binlik ayraç dahil).
_NUMERIC_SECRET_CHARS: frozenset[str] = frozenset("0123456789+-.,")

#: Yalnız ASCII rakamlar sayılır: `'٣'.isdigit()` True'dur ama gövdede sayısal
#: kimlik olarak geçmez ve eşiği sahte olarak doldurmamalı.
_ASCII_DIGITS: frozenset[str] = frozenset("0123456789")

#: base64 varyantı yalnız BU uzunluktan itibaren üretilir.
#:
#: Kısa bir sırrın base64'ü (`"abc123"` → `"YWJjMTIz"`) meşru veriyle çakışıp
#: gövdeyi gereksiz yere harap edebilir; uzun sırlarda (Basic auth başlığı,
#: jeton) ise gerçek ve sık bir taşıma biçimidir.
BASE64_VARIANT_MIN_LENGTH: int = 12

# REGEX GÜVENLİĞİ — bu kalıplar kullanıcı/taşıyıcı kontrolündeki MEGABAYTLIK
# metinler üzerinde koşar. Önceki sürüm `[A-Za-z0-9_.\-]+` ile sınırsız açgözlü
# eşleşme yapıyordu ve `=` içermeyen uzun bir belirteçte her başlangıç noktası
# için geri izleme yaparak O(n²)'ye çıkıyordu (ölçüldü: 192 KB'lık tek bir gövde
# maskelemesi 254 sn). Savunmalar:
#   1. her nicelikleyici ÜST SINIRLI — geri izleme sabit
#   2. kalıpların başında negatif geriye-bakış — eşleşme yalnız belirteç
#      BAŞLARINDA denenir, uzun bir belirtecin her karakterinde değil
#   3. iç içe nicelikleyici YOK — üstel patlama yolu kapalı
#   4. XML elemanı ve DEĞER gövdeleri artık regex ile DEĞİL, indeks tabanlı
#      `str.find` döngüleriyle taranır (aşağı bkz.) — hem ReDoS'suz hem de
#      "değer 4096 karakteri aştı → hiç maskeleme" FAIL-OPEN'ı kapalı.

#: `key:` / `key=` / `"key":` / `'key':` başlangıcını bulan TEK kalıp.
#:
#: Değerin kendisi BİLEREK bu kalıba dahil DEĞİL: değer sınırı biçime göre
#: değişir (satır sonu / `&` / kapanış tırnağı / kapanış parantezi) ve regex'te
#: üst sınırlı yazmak `<Token>` + 5000 karakter vakasındaki gibi FAIL-OPEN
#: üretiyordu. Değer `_scan_value` ile indeksle taranır.
#:
#: ANAHTAR SINIFI UNICODE (`\w`), ASCII DEĞİL — ölçülmüş fail-open:
#: 	`[A-Za-z0-9_.\-]` ile `şifre=SECRET` metninde eşleşme `ş`'den SONRA
#: 	başlıyor ve anahtar `ifre` olarak okunuyordu; `ifre` denylist'te olmadığı
#: 	için değer HAM kalıyordu (aynı içerik SÖZLÜK olarak verildiğinde doğru
#: 	maskeleniyordu — "tek küme kuralı"nı delen bir asimetri). `MÜŞTERİ_KODU=`,
#: 	`Şifre2=` ve NFD yazımlar aynı sınıftaydı. Geriye-bakış da aynı sınıfa
#: 	genişletildi ki eşleşme yine yalnız belirteç BAŞINDA denensin.
#: 	Nicelikleyiciler ÜST SINIRLI kaldığı için ReDoS profili değişmez.
#:
#: BİRLEŞTİRİCİ İŞARETLER SINIFA DAHİL (`̀-ͯ`): `\w` Unicode'da
#: yalnız ALFANÜMERİK sayılanları kapsar, `Mn` (combining mark) kategorisini
#: KAPSAMAZ. NFD yazımda `ş` = `s` + U+0327 olduğu için `şifre=SECRET` metninde
#: eşleşme işaretten sonra yeniden başlıyor ve anahtar yine `ifre` okunuyordu —
#: yani NFD, sınıf ASCII'den `\w`'ye genişletildikten SONRA da sızıyordu
#: (ölçüldü). TR'nin ihtiyaç duyduğu tüm işaretler (U+0306 breve, U+0307 nokta,
#: U+0308 çift nokta, U+0327 çengel) bu tek blokta.
#:
#: AYRAÇTAN ÖNCEKİ BOŞLUK — 11. TUR, 10. TURUN AYNA GÖRÜNTÜSÜ (ÖLÇÜLMÜŞ FAIL-OPEN):
#: 	10. tur `_scan_value`'nun ayraçtan SONRAKİ penceresini `' \t\r\n'` + ÜST
#: 	SINIRSIZ yaptı; ayraçtan ÖNCEKİ sınıf `[ \t]{0,8}` olarak KALDI. XML 1.0
#: 	`Eq ::= S? '=' S?` boşluğu `=` işaretinin İKİ YANINDA da meşru sayar, yani
#: 	kapatılan sızıntının tam simetriği açık kalmıştı (`mask_payload`; jeton bir
#: 	taşıyıcı YANITINDAKİ oturum jetonu yerine geçer, `secret_values`'ta YOKTUR →
#: 	değer-tabanlı birincil katman bu sınıfta YARDIM EDEMEZ):
#:
#: 	    '<Kayit sifre\n="SESSIONTOKEN_ABC999"/>'         → DEĞİŞMEDEN (SIZINTI)
#: 	    '<Kayit sifre \n = "SESSIONTOKEN_ABC999"/>'      → DEĞİŞMEDEN (SIZINTI)
#: 	    '<Kayit sifre          ="SESSIONTOKEN_ABC999"/>' → DEĞİŞMEDEN (SIZINTI)
#: 	    'sifre\n= SESSIONTOKEN_ABC999'                   → DEĞİŞMEDEN (SIZINTI)
#: 	    '<Kayit sifre ="X"/>' / '<Kayit sifre="X"/>'     → DOĞRU (tek boşluk)
#:
#: 	63 hassas ad × 10 ayraç-öncesi boşluk şekli × 6 ayraç-sonrası şekil × 6 biçim
#: 	= 20160 vektörün 10080'i HAM sızıyordu; fix sonrası 0. Çok-satırlı ön eklerle
#: 	(`\n\n`, `\r\n\r\n`, ` \n \n `) ayrı süpürmede 840/840 → 0.
#:
#: ÜST SINIR NEDEN KONMADI — AŞIRI MASKELEME TAKASI ÖLÇÜLDÜ:
#: 	Genişletme, "hassas görünen bir kelime satır sonunda, `=` bir sonraki satırın
#: 	başında" şeklindeki MEŞRU metinleri de yer: 25 gerçekçi (sırsız) çok satırlı
#: 	teşhis metninden 7'si etkilendi. ÖLÇÜLEN KİLİT BULGU — bu YENİ bir aşırı
#: 	maskeleme SINIFI DEĞİL: yedisinin de satır sonu BOŞLUKLA değiştirilmiş hâli
#: 	BUGÜNKÜ kodda ZATEN maskeleniyor:
#:
#: 	    'Alanlar: sifre = 5 karakter olmali' → '… = *** karakter olmali'  (bugün)
#: 	    'Kod = 4021 hatasi'                 → 'Kod = *** hatasi'         (bugün)
#: 	    'key = deger esleme tablosu…'       → 'key = *** esleme…'        (bugün)
#:
#: 	Yani genişletme, modülün ZATEN KABUL ETTİĞİ "yanlış pozitif ödünleşmesini"
#: 	satır sonları boyunca TUTARLI hâle getirir. Kayıp her vakada TEK JETONLADIR
#: 	(sonlandırıcı bir sonraki boşlukta/satır sonunda durur), gövdenin kuyruğu
#: 	YAŞAR — ölçülen 7 vakanın hepsinde doğrulandı.
#:
#: 	"EN FAZLA BİR SATIR SONU" ALTERNATİFİ ÖLÇÜLDÜ VE REDDEDİLDİ: 7 zarardan
#: 	yalnız 1'ini geri kazanıyor (`'sifre\n\n\n= x'`), buna karşılık BOŞ SATIRLI
#: 	ön eki (`'<Kayit sifre\n\n="TOKEN"/>'` — ElementTree'nin kabul ettiği İYİ
#: 	BİÇİMLİ XML) KALICI olarak açık bırakıyordu: aynı süpürmede 840/840 ham.
#: 	%14 teşhis kazancı için bir sonraki turun bulacağı bir sızıntı sınıfı açık
#: 	bırakmak, bu modülün fail-closed doktrinine aykırıdır.
#:
#: ReDoS — SINIF TEK PARÇA OLMAK ZORUNDA: `[ \t]*(?:\r?\n)?[ \t]*` biçimi
#: 	(iki BİTİŞİK sınırsız nicelikleyici) klasik `a*a*` polinom patlamasıdır ve
#: 	ÖLÇÜLDÜ: `'sifre' + ' '*n + 'X'` girdisinde n=20 000 → 2,630 s, n=200 000 →
#: 	262,844 s. Tek sınıf (`[ \t\r\n]*`) geri izlemeyi adım başına O(1) yapar:
#: 	aynı girdide n=200 000 → 0,021 s. Sınıf ASLA iki parçaya bölünmemeli.
_PAIR_KEY_RE = re.compile(
	r"(?<![\w.\-̀-ͯ])(?P<q>[\"']?)"
	r"(?P<key>[\w.\-̀-ͯ]{1,128})(?P=q)[ \t\r\n]*(?P<sep>[:=])"
)

#: XML/HTML açılış etiketi adı — yalnız AD sınırlıdır, öznitelikler ve değer
#: indeksle taranır (öznitelik bloğu 512 baytı aştığında eşleşmenin tamamen
#: düşmesi FAIL-OPEN'dı).
#:
#: `[^\W\d]` = "harf ya da `_`" (Unicode): `<Şifre>` ASCII sınıfıyla HİÇ
#: eşleşmiyordu ve TR SOAP zarflarında en olası yazım tam olarak budur.
#: `<![CDATA[`, `<?xml`, `<!--` yine etiket sayılmaz (`!`/`?` sınıf dışı).
#:
#: `:` AD BAŞINDA DA GEÇERLİDİR (6. tur): XML 1.0 `NameStartChar` üretimi `:`i
#: AÇIKÇA içerir ve `<:Sifre>TOKEN</:Sifre>` ÖLÇÜLDÜĞÜNDE değişmeden geçiyordu
#: (ad `:` ile başlayamaz sanılıyordu; `ns:Sifre` zaten çalışıyordu çünkü orada
#: `:` ad ORTASINDADIR). RAKAM KASTEN DIŞARIDA: XML'de ad rakamla başlayamaz ve
#: sınıfa rakam girerse `<!`/`<?` ayrımı da bulanır — rakamla başlayan bir
#: "etiket" bilinçli olarak etiket SAYILMAZ (geçersiz XML, karakter verisi).
#:
#: BU KARARIN MALİYETİ ÖLÇÜLDÜ (7. tur) — yorum boşluğu eskiden "başka katman
#: yakalar" gibi okutuyordu, ÖYLE DEĞİL: `<2Sifre>SESSIONTOKEN_ABC999</2Sifre>`
#: girdisinde İKİNCİL katman (`_mask_delimited_pairs`) de yakalamaz, çünkü
#: gövdede `=`/`:` ayracı YOKTUR ve `_PAIR_KEY_RE` hiç eşleşmez. Koruma YALNIZ
#: değer-tabanlı BİRİNCİL katmandan (`secret_values`) gelir. 7. turdan sonra bu
#: girdi ayrıca fail-safe ÖZETE iner (`_looks_like_tag` → `_markup_region_end`
#: `None`), yani ham geçmez; ama bu bir MASKELEME değil TEŞHİS KAYBIDIR ve
#: sınıfın gerçek çözümü çağıranın `secret_values` geçmesidir.
_TAG_NAME_RE = re.compile(r"(?:[^\W\d]|:)[\w:.\-̀-ͯ]{0,127}")

#: `scheme://kullanici:PAROLA@host` — URL userinfo bölümü.
#:
#: `://` gerektirdiği için sıradan metinde eşleşme denemesi ilk 32 karakterde
#: düşer; negatif geriye-bakış uzun bir belirtecin her karakterinde yeniden
#: denenmesini engeller.
_URL_USERINFO_RE = re.compile(
	r"(?P<prefix>(?<![A-Za-z0-9+.\-])[A-Za-z][A-Za-z0-9+.\-]{0,31}://[^/\s:@]{1,256}:)"
	r"[^/\s@]{1,4096}@"
)

# Değer sonlandırıcıları — biçime göre ayrı (hepsi karakter sınıfı, geri izleme yok).
_TERM_EQ_RE = re.compile(r"[&;,\s\"'()\[\]{}<>]")
_TERM_JSON_RE = re.compile(r"[,}\]\r\n]")
_TERM_LINE_RE = re.compile(r"[\r\n]")
_TERM_LINE_SQ_RE = re.compile(r"[\r\n']")
_TERM_LINE_DQ_RE = re.compile(r"[\r\n\"]")

#: Anahtarı parçalarına ayıran ayraçlar (`-` zaten `_`'ye normalize ediliyor).
_KEY_SEGMENT_RE = re.compile(r"[_.\s:]+")

#: TR ASCII katlaması — denylist'in iki yazımını da tutmak zorunda kalmamak için.
_TR_ASCII_MAP = str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"})

#: `'İ'.lower()` == `'i' + U+0307`; birleştirici nokta atılmazsa hiçbir TR
#: anahtar eşleşmez.
_COMBINING_DOT: str = "̇"

#: Parantezli değer taramasının azami penceresi.
_MAX_BRACKET_SCAN: int = 4096

#: KAPANIŞ ETİKETİNDE `</Ad` ile `>` arasında atlanan azami boşluk (XML 1.0
#: `ETag ::= '</' Name S? '>'`). YALNIZ `_find_close_tag` kullanır.
#:
#: 10. TURDA KAPSAMI DARALDI: aynı sabit `_scan_value`'nun ayraç-sonrası boşluk
#: penceresini de sınırlıyordu ve orada FAIL-OPEN üretiyordu (ayraçtan sonra
#: satır sonu ya da 8'den çok boşluk gelince değer HİÇ maskelenmiyordu — 116/116
#: vektör ham sızdı; ölçüm `_scan_value` docstring'inde). Burada sınırın yönü
#: TERSİDİR ve GÜVENLİDİR: sınırı aşan bir kapanış "bulunamadı" sayılır, eleman
#: `_ancestor_boundary`/`_fail_closed` yoluna girer ve FAZLA maskelenir.
_MAX_CLOSE_TAG_GAP: int = 8

#: BİLGİ TAŞIMAYAN karakterlerin Unicode kategorileri (`_carries_information`).
#:
#: `Cc` kontrol (NUL, NEL), `Cf` biçim (BOM U+FEFF, ZWSP U+200B), `Zs`/`Zl`/`Zp`
#: boşluk (SPACE, NBSP, IDSP, LS, PS). Bir ön ek YALNIZ bunlardan oluşuyorsa
#: `_fail_closed` yerelleştirme yerine ÖZETE iner — ölçülmüş gerekçe orada.
_INVISIBLE_CATEGORIES: frozenset[str] = frozenset({"Cc", "Cf", "Zs", "Zl", "Zp"})

#: `_match_bracket`: dengeli kapanış metinde HİÇ YOK (kırpmanın kanonik sonucu).
#: Kuyruk zaten BOŞTUR, değeri metnin sonuna kadar maskelemek teşhis kaybettirmez.
_BRACKET_NO_CLOSE: int = -1

#: `_match_bracket`: kapanış VAR ama `_MAX_BRACKET_SCAN` bütçesinin ÖTESİNDE.
#: Kuyruk VAR ve DOLU — maske bütçe sonunda biter, tarama devam eder (10. tur ölçümü
#: `_match_bracket` docstring'inde).
_BRACKET_BUDGET_EXHAUSTED: int = -2

#: Anahtardaki azami segment sayısı — bitişik dizi taraması O(k²), k sınırlı.
_MAX_KEY_SEGMENTS: int = 12

#: Kırpma kuyruğunda aranan azami sır ön eki uzunluğu.
_MAX_TAIL_SCAN: int = 512

#: Kuyrukta bir sır ön eki sayılabilmesi için asgari uzunluk — 1-3 karakterlik
#: rastlantısal eşleşmeler her metnin sonunu `***` yapardı.
_MIN_TAIL_PREFIX: int = 4

#: Sınırı çözülemeyen XML gövdesinin yerine yazılan FAIL-SAFE özet.
#:
#: TEST SÖZLEŞMESİ: testler biçimi kopyalamak yerine buradan okur.
#: `{0}` = gövdenin UTF-8 bayt uzunluğu, `{1}` = sayılan hassas etiket adedi.
#: Bayt ve alan sayısı BİLEREK korunur: özet opak bir `***` değil, "gövde
#: buradaydı, şu kadardı, içinde şu kadar hassas alan vardı" diyen bir teşhis
#: kaydıdır (bkz. modül docstring'i, XML SINIRI (b)).
#:
#: KAPSAM 9. TURDA DARALDI, ÖLÇÜT 10. TURDA İÇERİKSELLEŞTİ: bu özet artık YALNIZ
#: korunacak ön ek BİLGİ TAŞIMIYORKEN üretilir (`_fail_closed` +
#: `_carries_information`). Bilgi taşıyan ön ek varsa fail-safe YERELLEŞTİRİLİR
#: ve gövdenin anlaşılmış kısmı olduğu gibi kalır — ölçülmüş gerekçe
#: `_fail_closed` docstring'inde.
#:
#: `{1}` ARTIK ÇÖZÜLEMEYEN BÖLGEDE DE DOĞRU SAYAR (10. tur): sayım eskiden ilk
#: çözülemeyen `<`te duruyordu ve o nokta bu dalda YAPISAL OLARAK gövdenin
#: başıydı, yani baskın dalda HER ZAMAN "0 hassas alan" yazıyordu — gövdede
#: hassas eleman VARKEN bile.
XML_BOUNDARY_UNRESOLVED: str = "<XML gövdesi, {0} bayt, {1} hassas alan — sınır çözülemedi>"

#: XML tarayıcısının TEK BİR METİN için harcayabileceği azami tarama bütçesi.
#:
#: ÖLÇÜLMÜŞ GEREKÇE (O(k·n), 4. tur): memoizasyon etiket ADI başına tek tarama
#: garanti ediyor ama FARKLI adlarda çalışmıyor ve arama metnin sonuna kadar
#: gidiyor. 1 MB gövdede k=5000 farklı kapanışsız etiket 1,254 sn sürüyordu
#: (düz doğrusal); gerçek tavan olan 64 KiB kırpmasında 7406 farklı etiket
#: 0,200 sn/satır ediyordu — tipik gövdenin 10-25 katı. `direction="inbound"`
#: gövdesi saldırgan kontrolünde ve her satır bir RQ işçisini bloke ediyor.
#:
#: Bütçe METİN UZUNLUĞUNUN KATI olarak verilir (mutlak bir pencere DEĞİL):
#: `_MAX_ELEMENT_SPAN` tarzı sabit bir pencere 3. turdaki sızıntının ta
#: kendisiydi — ileri konumdaki bir arama, ilkinin hiç görmediği metni tarıyor
#: ve memoizasyonun monotonluk varsayımını deliyordu. Kat sayısı, iyi biçimli
#: gövdelerin kapanış aramalarının toplamını (≈ iç içe geçme derinliği × n)
#: rahatça karşılar; bütçeyi ancak patolojik girdi tüketir ve tükendiğinde
#: kalan hassas etiketler taranmadan fail-safe ÖZET yoluna gider.
_TAG_SCAN_BUDGET_FACTOR: int = 16

#: Kısa metinlerde bütçenin anlamsızlaşmaması için taban.
#:
#: İKİ TARAMA DAHA bu tabanı DOĞRUDAN üst sınır olarak kullanır — `_count_sensitive_tags`
#: (özet üretmenin kendisi maliyet vektörü olmamalı) ve `_contains_markup_construct`
#: (özete inme ölçütü). İkisi de bütçe bitince GÜVENLİ yöne gider. Taban,
#: `log.py::MAX_BODY_BYTES` (64 KiB) kırpmasının DÖRT KATIDIR: gerçek log gövdeleri
#: bu sınıra hiç dayanmaz, yalnız doğrudan çağrılan patolojik girdiler dayanır.
_MIN_TAG_SCAN_BUDGET: int = 256 * 1024

#: `<` ile başlayan ama ETİKET OLMAYAN markup bölgeleri: `(açılış, kapanış)`.
#:
#: TARAYICI MARKUP-KÖRDÜ (5. tur — dördüncü kez kenar durumu üreten sınıf).
#: Kapanış etiketi ham `str.find` ile aranıyordu ve bu bölgelerin İÇİNDEKİ sahte
#: kapanış GERÇEK sanılıyordu. Ölçülen iki sızıntı (ikisi de ElementTree ile
#: ayrıştırılabilir ve konformant ayrıştırıcıya göre jeton `<Token>`'ın İÇİNDE):
#:
#:     '<R><Token><!-- </Token> -->SESSIONTOKEN_ABC999</Token></R>'
#:     '<R><Token><![CDATA[</Token>]]>SESSIONTOKEN_ABC999</Token></R>'
#:
#: 4. turun fail-safe'i bu yolu KAPSAMIYORDU: özet yalnız "kapanış BULUNAMADI"
#: dalında tetikleniyor, tarayıcı ise "sınırı buldum" sanıyordu. Sıra ÖNEMLİ:
#: `<!--` ile `<![CDATA[` ilk iki karakteri paylaşır, `<?` en sonda kalmalı.
_MARKUP_REGIONS: tuple[tuple[str, str], ...] = (
	("<!--", "-->"),
	("<![CDATA[", "]]>"),
	("<?", "?>"),
)

#: `_markup_region_end` "burada bölge YOK" cevabı. `None` = "bölge AÇILDI ama
#: KAPANMADI" ve fail-safe özete iner — ikisi karıştırılmamalı.
_NOT_MARKUP: int = -1

#: `<!` ile başlayan markup BİLDİRİMİ ön eki — `<!--` ve `<![CDATA[` DIŞINDA
#: kalan HER şey (6. tur; bu sınıfın ALTINCI kırılması).
#:
#: Tarayıcı beş turdur "TANIDIĞIM yapıları atla, GERİSİNİ İŞLE" mantığındaydı ve
#: her turda listeye bir yapı eklendi, bir sonraki tur EKLENMEYENİ buldu. `<!`
#: ailesinin tamamı (`<!DOCTYPE`, `<!ENTITY`, `<!ATTLIST`, `<!ELEMENT`,
#: `<!NOTATION`, `<![IGNORE[`, `<![INCLUDE[`, çıplak `<!x` / `<!` / `<![`)
#: `_NOT_MARKUP` alıyordu; `_TAG_NAME_RE` `!` ile eşleşmediği için üç tarayıcı da
#: `at = lt + 1` ile bildirimin İÇİNE giriyor ve orada duran SAHTE kapanışı
#: GERÇEK sanıyordu. `_find_close_tag` POZİTİF sınır döndürdüğü için fail-safe
#: özet HİÇ tetiklenmiyor, kapanıştan sonraki gerçek değer HAM geçiyordu:
#:
#:     '<Sifre>x<!ENTITY e "</Sifre>">TOKEN</Sifre>' → '<Sifre>***</Sifre>">TOKEN…'
#:     '<Sifre><!DOCTYPE d [</Sifre>]>TOKEN</Sifre>' → '<Sifre>***</Sifre>]>TOKEN…'
#:
#: MANTIK TERSİNE ÇEVRİLDİ: bildirim gövdesinin dil bilgisi (iç içe `[...]`
#: alt kümeleri, tırnaklı literaller, `<!NOTATION` sözdizimi) doğru ayrıştırmak
#: için ayrı bir ayrıştırıcı gerektirir; tarayıcı bunu ANLAMIYOR ve artık öyle
#: DİYOR — `None` → fail-safe ÖZET. Bu bildirimler TR kargo SOAP yanıtlarının
#: GÖVDESİNDE meşru olarak bulunmaz (prolog'da DTD kullanan bir taşıyıcı yanıtı
#: yok), yani fazladan özetin operasyonel maliyeti sıfıra yakın; buna karşılık
#: "tanımadığım yapı" sınıfı TAMAMEN kapanır.
#:
#: İLKE: tarayıcının BİLMEDİĞİ hiçbir yapı ham geçmez — ya doğru işlenir ya özete iner.
_MARKUP_DECLARATION: str = "<!"

#: Etiket sonu `>` ararken durulması gereken karakterler — tırnak bölgesi
#: ATLANMALI, aksi halde öznitelik DEĞERİ içindeki `>` etiket sonu sanılır.
_TAG_SPECIAL_RE = re.compile("[\"'>]")

#: `_tag_end`: metin bitti, etiket kapanmadı. Kuyruk zaten yarım bir etiket —
#: içinde ELEMAN İÇERİĞİ olamaz, tarayıcı güvenle durur.
_TAG_END_TRUNCATED: int = -1

#: `_tag_end`: öznitelik tırnağı KAPANMADI. Etiketin nerede bittiği bilinemez,
#: yani "bundan sonrası içeriktir" iddiası kurulamaz → fail-safe ÖZET.
_TAG_END_AMBIGUOUS: int = -2


# ---------------------------------------------------------------------------
# Anahtar normalizasyonu
# ---------------------------------------------------------------------------


def _fold(text: str) -> str:
	"""TR-güvenli küçük harfe indirme — ÖNCE Unicode birleştirme (NFKC).

	İKİ AYRI TUZAK, ikisi de ölçüldü:

	* **NFD ayrıştırılmış girdi.** `unicodedata.normalize` hiç çağrılmıyordu.
	  NFC yazımda `ŞİFRE`/`şifre` maskeleniyor ama `NFD('ŞİFRE')` HAM sızıyordu:
	  NFD'de `ş` = `s` + U+0327 (combining cedilla) iken hem denylist hem
	  `_TR_ASCII_MAP` TEK KOD NOKTALI `ş` (U+015F) bekliyor. NFD, macOS
	  kaynaklı gövdelerin ve bazı Java/.NET SOAP yığınlarının VARSAYILANIDIR.
	  NFC yerine NFKC seçildi: uyumluluk katlaması `ﬁ` ligatürünü, tam-genişlik
	  (`ｐａｓｓｗｏｒｄ`) ve daireli rakam gibi görsel eşdeğerleri de kanonik
	  yazıma indirir — hepsi anahtar adını gizleyip denylist'i atlatma yolu.
	* **`str.lower()` TEK BAŞINA YETMEZ.** `'İ'.lower()` `'i'` değil
	  `'i\\u0307'` döndürür (`casefold()` de aynı). Birleştirici nokta
	  atılmazsa `ŞİFRE`, `MÜŞTERİ_KODU`, `MUSTERİKODU` denylist'e HİÇ uğramaz.
	  Bu adım NFKC'den SONRA gelmek zorunda: normalizasyon `I`+U+0307'yi
	  `İ`'ye geri toplar, `lower()` onu yeniden ayırır, nokta EN SON atılır.
	"""
	lowered = unicodedata.normalize("NFKC", text).lower()
	if _COMBINING_DOT in lowered:
		lowered = lowered.replace(_COMBINING_DOT, "")
	return lowered


def _split_camel(text: str) -> str:
	"""camelCase/PascalCase/ACRONYMWord ve HARF↔RAKAM sınırlarına `_` koyar.

	Regex ile YAPILMAZ: Python str kalıplarında `[A-Z]` SALT ASCII'dir; `Ş`,
	`İ`, `Ö` ile eşleşmez ve `musteriŞifre` hiç bölünmezdi (ölçüldü).
	`str.isupper()`/`islower()` Unicode tablosuna bakar.

	`HTTPAuth` → `HTTP_Auth` (kısaltma sınırı) ve `clientSecret` →
	`client_Secret` (klasik camel sınırı) — ikisi de gerekli.

	HARF↔RAKAM SINIRI — ÖLÇÜLMÜŞ FAIL-OPEN:
		`_KEY_SEGMENT_RE` yalnız `[_.\\s:]+` ile böler; rakam bitişik yazılan
		anahtarlar tek segment kalıyor ve denylist'e HİÇ uğramıyordu. HAM
		sızanlar (hepsi ölçüldü): `password2`, `Password1`, `sifre2`, `Sifre2`,
		`şifre2`, `apiKey2`, `api_key2`, `token1`, `pwd1`, `Kod2`,
		`musteri_kodu2`, `secret1`, `key2`. AYRAÇLI kardeşleri (`secret_2`,
		`password_2`, `api_key_v2`) DOĞRU maskeleniyordu — yani boşluk tam
		olarak "rakam bitişik" vakasıydı. Bu teorik değil: TR kargo SOAP
		sözleşmeleri çok hesaplı/alt-bayi kurulumlarında rutin olarak `Sifre2`,
		`Kod2`, `MusteriKodu2` taşır.

		`api_key2` → `api_key_2` yapmak yeter; segment mantığı gerisini zaten
		hallediyor (`_MAX_KEY_SEGMENTS` korunur) ve çalışan `secret_2` vakasıyla
		simetrik olur. Denylist kümesi de AYNI üretimden geçtiği için (`p12` →
		`p_12`) iki taraf simetrik kalır.

		Birleştirici işaretler (NFD kalıntısı) ne harf ne rakamdır; sınır kuralı
		en az bir taraf HARF olduğunda uygulanır, böylece `s`+U+0327+`2` gibi
		diziler sahte segment üretmez.
	"""
	if len(text) < 2:
		return text

	pieces: list[str] = []
	last = len(text) - 1
	for index, char in enumerate(text):
		if index:
			previous = text[index - 1]
			if char.isupper():
				following = text[index + 1] if index < last else ""
				if previous.islower() or previous.isdigit() or (previous.isupper() and following.islower()):
					pieces.append("_")
			elif char.isdigit() != previous.isdigit() and (char.isalpha() or previous.isalpha()):
				pieces.append("_")
		pieces.append(char)
	return "".join(pieces)


@lru_cache(maxsize=8192)
def _normalize_text(text: str) -> str:
	"""Anahtar metnini karşılaştırma biçimine indirger.

	Sırayla: Unicode NFKC birleştirmesi, XML ad alanı ön eki atılır
	(`soap:Password` → `Password`), camelCase/harf-rakam sınırlarına `_` konur,
	TR-güvenli küçük harfe inilir, `-` → `_` yapılır.

	NFKC BURADA, `_split_camel`'DEN ÖNCE: `_fold` de normalize eder ama o
	bölmeden SONRA çalışır ve NFD girdide kısaltma sınırı kaçardı —
	`NFD('KODŞifre')` içinde `Ş` = `S` + U+0327 olduğu için `following`
	birleştirici işarettir, `islower()` False döner ve `KOD_Şifre` bölünmesi
	hiç yapılmazdı. NFKC idempotent olduğundan `_fold`'daki ikinci çağrı
	bedavadır; `_fold` kendi başına da doğru kalmalı (tek kullanımlık değil,
	katlama primitifi).
	"""
	value = unicodedata.normalize("NFKC", text.strip())
	if ":" in value:
		value = value.rsplit(":", 1)[-1]
	return _fold(_split_camel(value)).replace("-", "_")


def _normalize_key(key: Any) -> str:
	"""`_normalize_text`'in tür-toleranslı sarmalayıcısı (sıcak yol, memoize)."""
	return _normalize_text(key if isinstance(key, str) else str(key))


@lru_cache(maxsize=8192)
def _key_forms(normalized: str) -> frozenset[str]:
	"""Bir anahtarın karşılaştırılacak TÜM yazım biçimleri.

	Üç eksen: olduğu gibi, TR→ASCII katlanmış (`şifre` → `sifre`) ve ayraçsız
	(`musteri_kodu` → `musterikodu`). Ayraçsız biçim `accesstoken`, `sessid`,
	`clientsecret`, `KULLANICIADI` gibi bitişik yazımları denylist'e ELLE
	eklemek zorunda kalmadan yakalar — küme kurulurken de aynı üretim
	uygulandığı için iki taraf simetriktir.
	"""
	if not normalized:
		return frozenset()

	forms = {normalized, normalized.translate(_TR_ASCII_MAP)}
	forms |= {form.replace("_", "") for form in tuple(forms)}
	return frozenset(form for form in forms if form)


def _allow_forms(normalized: str) -> frozenset[str]:
	"""Allowlist için TAM anahtar biçimleri (+ HTTP satıcı ön eki sıyrılmış hâli).

	`x-idempotency-key` bir HTTP başlığında `idempotency_key`'in ta kendisidir;
	`x_` ön ekini sıyırmak bu tek meşru varyantı kurtarır ve allowlist'i son ek
	kuralına geri döndürmez.
	"""
	forms = set(_key_forms(normalized))
	if normalized.startswith("x_"):
		forms |= _key_forms(normalized[2:])
	return frozenset(forms)


@lru_cache(maxsize=32)
def _normalized_haystack(keys: frozenset[str]) -> frozenset[str]:
	"""Küme başına BİR KEZ hesaplanan normalize edilmiş arama kümesi.

	Eski sürümde bu küme `is_sensitive_key` her çağrıldığında yeniden
	kuruluyordu ve fonksiyon regex geri çağrısından eşleşme BAŞINA (20 bin
	kez) çağrılıyordu.
	"""
	haystack: set[str] = set()
	for entry in keys:
		haystack |= _key_forms(_normalize_key(entry))
	return frozenset(haystack)


@lru_cache(maxsize=4096)
def _is_sensitive_normalized(normalized: str, keys: frozenset[str]) -> bool:
	"""Normalize edilmiş anahtar hassas mı? (memoize edilmiş sıcak yol)

	KARAR SIRASI:

	1. **Allowlist yalnız TAM anahtar için.** Döngünün İÇİNDE bakılsaydı
	   allowlist son eki denylist segmentini geçersiz kılardı; ölçülen regresyon
	   buydu (`password_cache_key` maskelenmiyordu).
	2. **Denylist bitişik segment dizisi için.** Yalnız son ek DEĞİL: `auth_error_code`
	   ve `token_status_code` gibi sır adını ÖN EKTE taşıyan anahtarlar son-ek
	   kuralından tamamen kaçıyordu. Bitişik dizi taraması `x_api_key` →
	   `api_key` ve `musteri_kodu_alani` → `musteri_kodu` vakalarını da kapsar.
	"""
	if not normalized:
		return False

	if _allow_forms(normalized) & _normalized_haystack(NON_SENSITIVE_KEYS):
		return False

	deny = _normalized_haystack(keys)
	segments = [part for part in _KEY_SEGMENT_RE.split(normalized) if part][:_MAX_KEY_SEGMENTS]
	if not segments:
		return False

	for start in range(len(segments)):
		for end in range(start + 1, len(segments) + 1):
			if _key_forms("_".join(segments[start:end])) & deny:
				return True
	return False


def is_sensitive_key(key: Any, extra: frozenset[str] | None = None) -> bool:
	"""Anahtar hassas mı?

	Args:
		key: Kontrol edilecek anahtar.
		extra: Ek hassas anahtar kümesi (varsayılana EKLENİR).

	Returns:
		Anahtar hassas ise True.
	"""
	keys = DEFAULT_SENSITIVE_KEYS if not extra else (DEFAULT_SENSITIVE_KEYS | extra)
	return _is_sensitive_normalized(_normalize_key(key), keys)


def mask_value(value: str) -> str:
	"""Bir değeri TAMAMEN maskeler.

	Uzunluk ipucu dahil hiçbir şey sızdırılmaz; her zaman sabit `***` döner.

	Args:
		value: Maskelenecek değer (imza gereği metin; kullanılmaz).

	Returns:
		Sabit maske dizgisi.
	"""
	return MASK


# ---------------------------------------------------------------------------
# Birincil savunma — DEĞER-TABANLI REDAKSİYON
# ---------------------------------------------------------------------------


def secret_texts(raw: Any) -> tuple[str, ...]:
	"""Bir sır değerini aranabilir METİN gösterimlerine çevirir.

	`bytes` ÖZEL OLARAK ELE ALINIR: eski sürüm `str(raw)` yapıyordu ve
	`str(b'SECRET')` == `"b'SECRET'"` gövdede ASLA bulunmuyordu — bytes bir sır
	SESSİZCE redakte edilmiyordu (ölçüldü). HMAC anahtarları, `b64decode`
	çıktısı ve `requests`'e verilen ham auth materyali sıklıkla bytes'tır.

	PUBLIC — `integration/secrets.py` de bu dönüşümü kullanır. Private kalsaydı
	toplayıcı ya kendi kopyasını yazacaktı ya da (ölçülmüş davranış) `str`
	olmayan sır alanlarını SESSİZCE atacaktı; ikisi de bu modülün açıkça
	kapattığı sınıflar.
	"""
	if isinstance(raw, str):
		return (raw,)

	if isinstance(raw, (bytes, bytearray, memoryview)):
		data = bytes(raw)
		texts: list[str] = []
		try:
			texts.append(data.decode("utf-8"))
		except UnicodeDecodeError:
			pass
		# latin-1 ASLA patlamaz: baytın gövdeye "olduğu gibi" gömüldüğü hâli.
		texts.append(data.decode("latin-1"))
		texts.append(data.hex())
		texts.append(base64.b64encode(data).decode("ascii"))
		return tuple(texts)

	if isinstance(raw, Decimal):
		# `str(Decimal('1E+3'))` == `'1E+3'` — gövdede ASLA bu biçimde geçmez.
		# `format(raw, 'f')` bilimsel gösterimi açar (`'1000'`) ve ondalık
		# basamakları korur. Bugün bu tür `ERROR` ile DÜŞÜRÜLÜYORDU, yani
		# `Decimal` taşıyan bir kimlik alanı için birincil savunma kapalıydı.
		return (format(raw, "f"),)

	if isinstance(raw, (int, float)):
		return (str(raw),)

	_LOGGER.warning("Beklenmedik sır türü redakte edilemedi: %s — str()'e düşülüyor", type(raw).__name__)
	return (str(raw),)


def _numeric_secret_digits(value: str) -> int | None:
	"""Değer SAYISAL biçimde mi; öyleyse kaç ASCII RAKAM taşıyor?

	Döner: rakam sayısı; değer sayısal biçimde değilse ya da hiç rakam
	taşımıyorsa `None`. Biçim üzerinden karar verilir (türü üzerinden değil):
	`123456` ile `"123456"` aynı çakışma riskini taşır ve aynı eşiğe tabidir.
	"""
	if not value:
		return None
	digits = 0
	for char in value:
		if char not in _NUMERIC_SECRET_CHARS:
			return None
		if char in _ASCII_DIGITS:
			digits += 1
	return digits or None


def build_secret_variants(secret_values: Iterable[Any] | None) -> tuple[str, ...]:
	"""Sır değerlerinin aranacak BİÇİM varyantlarını üretir.

	Aynı sır gövdede düz, URL-encoded (`quote`), form-encoded (`quote_plus`)
	ya da base64 (Basic auth başlığı) hâlinde görünebilir; hepsi aranır.
	`bytes` sırlar için ayrıca utf-8/latin-1 yorumu ve hex gösterimi eklenir.

	Kurallar:
		* `MIN_SECRET_LENGTH`'ten kısa değerler ATLANIR ve UYARI yazılır.
		* SAYISAL biçimli değerler için eşik `MIN_NUMERIC_SECRET_LENGTH` RAKAMDIR
		  (bkz. o sabitin ölçülmüş gerekçesi: 6 haneli müşteri kodu gövdedeki her
		  meşru geçişini yok ediyordu).
		* base64 varyantı yalnız `BASE64_VARIANT_MIN_LENGTH`'ten uzun sırlar için
		  üretilir (kısa base64 meşru veriyle çakışır).
		* Sonuç UZUNDAN KISAYA sıralanır — kısa bir sır uzun bir sırrın alt
		  dizgisi olabilir; önce kısası değiştirilseydi uzun sır parçalanır ve
		  geri kalanı log'da açıkta kalırdı.
		* Karşılaştırma büyük/küçük harf DUYARLIDIR (base64/hex sırlar).

	Args:
		secret_values: Bilinen sır dizgileri (str, bytes, sayı).

	Returns:
		Uzunluğa göre azalan sırada, tekilleştirilmiş varyant demeti.
	"""
	if not secret_values:
		return ()

	variants: set[str] = set()
	for raw in secret_values:
		if raw is None:
			continue
		for value in secret_texts(raw):
			digits = _numeric_secret_digits(value)
			minimum = MIN_NUMERIC_SECRET_LENGTH if digits is not None else MIN_SECRET_LENGTH
			measure = digits if digits is not None else len(value)
			if measure < minimum:
				# SESSİZ ATLAMA YASAK: çağıran "redakte edildi" sanmasın.
				_LOGGER.warning(
					"Çok kısa sır redakte EDİLMEDİ (%s=%d < %d)",
					"rakam" if digits is not None else "uzunluk",
					measure,
					minimum,
				)
				continue
			candidates = {value, quote(value, safe=""), quote_plus(value)}
			if len(value) >= BASE64_VARIANT_MIN_LENGTH:
				try:
					candidates.add(base64.b64encode(value.encode("utf-8")).decode("ascii"))
				except (UnicodeEncodeError, ValueError):  # pragma: no cover — savunma
					pass
			variants.update(item for item in candidates if len(item) >= MIN_SECRET_LENGTH)

	return tuple(sorted(variants, key=len, reverse=True))


def redact_text(text: str, secret_values: Iterable[Any] | None) -> str:
	"""Metinde bilinen sır değerlerini BİREBİR arar ve `***` ile değiştirir.

	`error_message` gibi hiçbir yapısı olmayan düz metinler için birincil
	savunma budur: `requests`'in bağlantı hatası metni tam URL'i query
	string'iyle taşır (`?musteri_kodu=42&sifre=SECRET`) ve orada maskelenecek
	bir "anahtar" yoktur, yalnız değer vardır.

	Args:
		text: Redakte edilecek metin.
		secret_values: Bilinen sır dizgileri (varyantları otomatik türetilir).

	Returns:
		Sırları değiştirilmiş metin.
	"""
	if not text or not secret_values:
		return text
	return redact_with_variants(text, build_secret_variants(secret_values))


def redact_with_variants(text: str, variants: tuple[str, ...]) -> str:
	"""Önceden hesaplanmış varyantlarla redaksiyon (sıcak yol — yeniden üretmez).

	`redact_text` her çağrıda `build_secret_variants` koşar; bir log satırı
	yazılırken aynı sır kümesi ONLARCA yaprakta aranır, o yüzden varyantlar bir
	kez üretilip bu fonksiyona verilir.

	PUBLIC — `strip_partial_secret_tail` ile SİMETRİK: ikisi de `variants`
	demetini alır ve `log.py` ikisini de kullanır. Yayınlanmadığı sürece
	`log.py::_redact` satır satır aynı kopyayı taşıyordu; kopya, tam da
	kopyaların tehlikesini anlatan turda geri gelmişti.

	Args:
		text: Redakte edilecek metin.
		variants: `build_secret_variants` çıktısı (uzundan kısaya sıralı).

	Returns:
		Sırları `***` ile değiştirilmiş metin.
	"""
	if not text or not variants:
		return text
	for variant in variants:
		if variant in text:
			text = text.replace(variant, MASK)
	return text


def strip_partial_secret_tail(text: str, variants: tuple[str, ...]) -> str:
	"""Kırpma sınırında kalan YARIM sırrı keser.

	NEDEN GEREKLİ: kırpma redaksiyondan ÖNCE yapılır (50 MB'lık gövdeyi tam boy
	maskelemek için değil). Kırpma tam bir sırrın ortasına denk geldiğinde geriye
	sırrın ÖN EKİ kalır ve birebir eşleşme yapan redaksiyon onu göremez —
	ölçüldü: 308 karakterlik bir sırrın ilk 202 karakteri HAM kaldı. PEM özel
	anahtar, SAML assertion ve uzun bearer jetonu tam bu sınıfta.

	Metnin son `_MAX_TAIL_SCAN` karakteri, varyantların GERÇEK ön eklerine karşı
	uzundan kısaya denetlenir; eşleşen kuyruk `***` ile değiştirilir.

	Args:
		text: Kırpılmış metin.
		variants: `build_secret_variants` çıktısı.

	Returns:
		Yarım sır taşımayan metin.
	"""
	if not text or not variants:
		return text

	window = min(len(text), _MAX_TAIL_SCAN)
	for cut in range(len(text) - window, len(text) - _MIN_TAIL_PREFIX + 1):
		suffix = text[cut:]
		for variant in variants:
			if len(variant) > len(suffix) and variant.startswith(suffix):
				return text[:cut] + MASK
	return text


# ---------------------------------------------------------------------------
# İkincil savunma — anahtar tabanlı maskeleme
# ---------------------------------------------------------------------------


def mask_mapping(
	data: Mapping,
	extra_keys: frozenset[str] | None = None,
	*,
	secret_values: Iterable[Any] | None = None,
) -> dict:
	"""Sözlüğü anahtar duyarlı ve DERİN maskeler. **Asla fırlatmaz.**

	Hassas anahtarın değeri `***` olur; diğer değerler `mask_payload` ile
	yeniden taranır, böylece iç içe yapılar da kapsanır.

	Args:
		data: Maskelenecek eşleme.
		extra_keys: Ek hassas anahtar kümesi.
		secret_values: Değer-tabanlı redaksiyon için bilinen sırlar.

	Returns:
		Maskelenmiş yeni sözlük (girdi DEĞİŞTİRİLMEZ). Hata hâlinde
		`{"_masking_failed": "***"}` (fail-closed).
	"""
	keys = DEFAULT_SENSITIVE_KEYS if not extra_keys else (DEFAULT_SENSITIVE_KEYS | extra_keys)
	try:
		return _mask_mapping(data, keys, build_secret_variants(secret_values), 0)
	except Exception:  # noqa: BLE001 — sözleşme: maskeleme fırlatmaz, fail-closed döner
		_LOGGER.warning("mask_mapping başarısız — fail-closed", exc_info=True)
		return {"_masking_failed": MASK}


def mask_headers(
	headers: Any,
	*,
	secret_values: Iterable[Any] | None = None,
) -> dict:
	"""HTTP başlıklarını maskeler. **Asla fırlatmaz.**

	Başlık değerleri `mask_payload`'a SOKULMAZ: bir başlık değeri gövde değildir,
	JSON gibi yorumlanması (`"100"` → 100) log'u yanıltıcı hale getirirdi. Hassas
	olmayan skaler değer metne çevrilir ve değer-tabanlı redaksiyondan geçer;
	Mapping/liste değerler (`requests` bazı başlıkları böyle taşır) yapısal
	maskelemeden geçer — `str()` ile düzleştirilseydi İÇ anahtarları hiç
	değerlendirilmezdi.

	GİRDİ NORMALİZASYONU: `requests` başlıkları liste-of-tuple olarak da taşır;
	eski sürüm orada `AttributeError` FIRLATIYOR ve log satırını tamamen
	düşürüyordu (ölçüldü). Artık `dict()` denenir, olmazsa boş sözlük + uyarı.

	BAŞLIK ADI DA REDAKTE EDİLİR — 11. TUR, ÖLÇÜLMÜŞ SIZINTI:
		Değer-tabanlı birincil katman burada YALNIZ değerlere uygulanıyordu;
		ANAHTAR konumundaki bir sır HAM geçiyordu:

			mask_headers({'SUPERSECRET123': 'v', 'X-Trace': 'SUPERSECRET123'},
			             secret_values=['SUPERSECRET123'])
				→ {'SUPERSECRET123': 'v', 'X-Trace': '***'}   ADI HAM

		`log.py::_redact_deep` YAZICI yolunda bunu kapatıyordu (uçtan uca boşluk
		YOK), ama `mask_headers` PUBLIC bir API'dir ve doğrudan çağrılabilir —
		savunma çağıranın hangi kapıdan girdiğine bağlı olamaz. Bu, 10. turda
		`_mask_mapping` için kapatılan boşluğun başlık tarafındaki AYNASIDIR ve
		aynı deseni kullanır.

	SIRA KRİTİK — ÖNCE DENYLIST, SONRA ANAHTAR REDAKSİYONU:
		Denylist kararı başlığın ADIYLA verilir. Anahtar önce redakte edilseydi
		denylist `'***'` görür ve `Authorization` gibi bir adı KAÇIRIRDI.

	AŞIRI MASKELEME YOK: redaksiyon `secret_values` ile BİREBİR eşleşmeye
	dayanır, ad TAHMİN EDİLMEZ. `Content-Type`, `X-Request-Id`,
	`Idempotency-Key`, `User-Agent`, `X-Trace` gibi teşhis başlıklarının ADI
	GÖRÜNÜR kalır (ölçüldü).

	Args:
		headers: Başlık eşlemesi / çift dizisi. None ise boş sözlük döner.
		secret_values: Değer-tabanlı redaksiyon için bilinen sırlar.

	Returns:
		Maskelenmiş başlık sözlüğü.
	"""
	if not headers:
		return {}

	try:
		items = _header_items(headers)
		variants = build_secret_variants(secret_values)
		masked: dict = {}
		for key, value in items:
			if _is_sensitive_normalized(_normalize_key(key), DEFAULT_SENSITIVE_KEYS):
				masked_value: Any = MASK
			elif isinstance(value, (Mapping, list, tuple, set, frozenset)):
				masked_value = _mask_any(value, DEFAULT_SENSITIVE_KEYS, variants, 1)
			else:
				masked_value = redact_with_variants(str(value), variants)
			masked[redact_with_variants(key, variants) if isinstance(key, str) else key] = masked_value
		return masked
	except Exception:  # noqa: BLE001 — sözleşme: maskeleme fırlatmaz, fail-closed döner
		_LOGGER.warning("mask_headers başarısız — fail-closed", exc_info=True)
		return {"_masking_failed": MASK}


def _header_items(headers: Any) -> list[tuple[Any, Any]]:
	"""Başlık kabını `(anahtar, değer)` listesine indirger."""
	if isinstance(headers, Mapping):
		return list(headers.items())
	try:
		return list(dict(headers).items())
	except (TypeError, ValueError):
		_LOGGER.warning("Tanınmayan başlık kabı yok sayıldı: %s", type(headers).__name__)
		return []


def mask_payload(
	body: Any,
	*,
	extra_keys: frozenset[str] | None = None,
	secret_values: Iterable[Any] | None = None,
) -> Any:
	"""Herhangi bir gövdeyi maskeler. **Asla fırlatmaz.**

	Kabul edilen türler ve davranış:

		None                → None
		dict / Mapping      → derin (nested) maskeleme
		list / tuple / set  → her eleman için derin maskeleme
		bytes               → utf-8 decode denenir; olmazsa `<binary N bytes>`
		str                 → JSON ayrıştırılabiliyorsa ayrıştırılıp maskelenir
		                      ve tekrar JSON'a yazılır; ayrıştırılamıyorsa
		                      XML elemanı, XML özniteliği, URL userinfo,
		                      `"key":"value"`, `key: value` ve `key=value`
		                      kalıpları maskelenir
		int/float/bool      → olduğu gibi
		DİĞER HER ŞEY       → `<TypeName>`

	SON MADDE ÖNEMLİ: eski sürüm tanımadığı nesneleri değiştirmeden geçiriyor,
	`log.py` de `json.dumps(default=str)` ile onların `repr`'ini yazıyordu.
	Bir `requests.PreparedRequest` ya da bir adapter kimlik nesnesinin `repr`'i
	kimlik bilgisi taşır. Artık tür adı dışında hiçbir şey yazılmaz.

	SÖZLEŞME — İSTİSNA FIRLATMAZ: bu fonksiyon `Carrier Integration Log`
	yazımının HEM yazıcı HEM DocType katmanında çağrılır. Bir istisna denetim
	izini tamamen düşürürdü (3 KB'lık iç içe JSON `RecursionError` üretiyordu —
	ölçüldü). Beklenmedik hata `MASK` ile sonuçlanır: ham veri ASLA geçmez.

	Args:
		body: Maskelenecek gövde.
		extra_keys: Ek hassas anahtar kümesi.
		secret_values: Değer-tabanlı redaksiyon için bilinen sırlar.

	Returns:
		Maskelenmiş gövde; girdiyle aynı türde (str girdide str döner).
		Hata hâlinde `MASK`.
	"""
	keys = DEFAULT_SENSITIVE_KEYS if not extra_keys else (DEFAULT_SENSITIVE_KEYS | extra_keys)
	try:
		return _mask_any(body, keys, build_secret_variants(secret_values), 0)
	except Exception:  # noqa: BLE001 — sözleşme: maskeleme fırlatmaz, fail-closed döner
		_LOGGER.warning("mask_payload başarısız — fail-closed", exc_info=True)
		return MASK


def _mask_any(body: Any, keys: frozenset[str], variants: tuple[str, ...], depth: int) -> Any:
	if body is None:
		return None

	if depth > MAX_MASK_DEPTH:
		# Açık sayaç: `RecursionError` yerine görünür bir işaret. Sayaç olmadan
		# saldırgan kontrolündeki iç içe webhook gövdesi log satırını düşürüyordu.
		return DEPTH_EXCEEDED

	if isinstance(body, Mapping):
		return _mask_mapping(body, keys, variants, depth)

	if isinstance(body, (list, tuple, set, frozenset)):
		return [_mask_any(item, keys, variants, depth + 1) for item in body]

	if isinstance(body, (bytes, bytearray, memoryview)):
		return _mask_bytes(bytes(body), keys, variants, depth)

	if isinstance(body, str):
		return _mask_text(body, keys, variants, depth)

	# bool `int` alt sınıfıdır; ikisi de olduğu gibi geçer.
	if isinstance(body, (bool, int, float)):
		return body

	# Tanınmayan nesne: repr'i kimlik bilgisi taşıyabilir — yalnız tür adı kalır.
	return f"<{type(body).__name__}>"


def _mask_mapping(data: Mapping, keys: frozenset[str], variants: tuple[str, ...], depth: int) -> dict:
	"""Sözlüğü maskeler — DEĞER anahtar ADIYLA, ANAHTAR değer-tabanlı redaksiyonla.

	ANAHTAR KONUMUNDAKİ SIR — 10. TUR, ÖLÇÜLMÜŞ SIZINTI:
		Değer-tabanlı birincil katman sözlük yolunda YALNIZ değerlere uygulanıyordu;
		anahtar konumundaki bir sır HAM geçiyordu. Aynı içerik JSON METNİ olarak
		verildiğinde doğru maskeleniyordu — yani modülün kendi ilan ettiği
		**TEK KÜME KURALI** (aynı içerik dict / JSON metni / querystring olarak
		gelse de AYNI sonuç) ÖLÇÜLEREK ihlal ediliyordu:

			mask_payload({'SUPERSECRET123': 'v'},        secret_values=[…])
				→ {'SUPERSECRET123': 'v'}   ANAHTAR HAM
			mask_payload({'data': {'SUPERSECRET123': 1}}, secret_values=[…])
				→ {'data': {'SUPERSECRET123': 1}}   ANAHTAR HAM
			mask_payload('{"SUPERSECRET123":"v"}',       secret_values=[…])
				→ {"***": "v"}              JSON METNİ yolunda MASKELİ
			mask_payload('SUPERSECRET123=v',             secret_values=[…])
				→ '***=v'                   QUERYSTRING yolunda MASKELİ

		ERİŞİLEBİLİR: `direction='inbound'` webhook gövdeleri ve `parse_qs`
		çıktıları karşı tarafın kontrolündedir; bir jetonu ANAHTAR konumuna
		koymak tek satırlık bir seçimdir.

	SIRA KRİTİK — ÖNCE DENYLIST, SONRA ANAHTAR REDAKSİYONU:
		Denylist kararı anahtarın ADIYLA verilir. Anahtar önce redakte edilseydi
		denylist `'***'` görür ve `sifre` gibi bir adı KAÇIRIRDI. Bu yüzden
		`_is_sensitive_normalized` HER ZAMAN ham anahtarla çağrılır.

	AŞIRI MASKELEME YOK: redaksiyon `secret_values` ile BİREBİR eşleşmeye
	dayanır, anahtar ADINI tahmin etmez. `tracking_number`, `barcode`,
	`order_no`, `status_code`, `idempotency_key`, `request_id`, `hata_kodu`
	gibi teşhis anahtarları ANAHTAR konumunda GÖRÜNÜR kalır (ölçüldü).

	ÇARPIŞMA (bilinçli, teşhis kaybı yönünde): iki farklı anahtar aynı sırra
	indirgenirse (`{'SECRETA': 1, 'SECRETB': 2}` → tek `'***'`) sonuncusu kalır.
	Yön güvenli; alternatif (sıra numarası eklemek) sır SAYISINI sızdırırdı.
	"""
	if depth > MAX_MASK_DEPTH:
		return {"_depth": DEPTH_EXCEEDED}

	masked: dict = {}
	for key, value in data.items():
		if _is_sensitive_normalized(_normalize_key(key), keys):
			masked_value: Any = MASK
		else:
			masked_value = _mask_any(value, keys, variants, depth + 1)
		masked[redact_with_variants(key, variants) if isinstance(key, str) else key] = masked_value
	return masked


def _mask_bytes(raw: bytes, keys: frozenset[str], variants: tuple[str, ...], depth: int) -> str:
	"""Bayt gövdesini maskeler; metne çevrilemiyorsa boyut özetiyle değiştirir."""
	try:
		text = raw.decode("utf-8")
	except UnicodeDecodeError:
		# İkili içerik (etiket PDF/ZPL, imza bloğu). Ham baytı log'a yazmak hem
		# faydasız hem de içinde kimlik bilgisi taşıyabilir — yalnız boyut kalır.
		return f"<binary {len(raw)} bytes>"
	return _mask_text(text, keys, variants, depth)


def _mask_text(text: str, keys: frozenset[str], variants: tuple[str, ...], depth: int) -> str:
	"""Metin gövdesini maskeler: önce JSON, olmazsa XML + kalıplar; sonra redaksiyon.

	XML TARAYICISI HER METİNDE KOŞAR — GİRİŞ KAPISI YOKTUR (8. tur, Paket M).
	Bir ara turda buraya `_looks_like_xml_body(text)` kapısı konmuştu: baştaki
	boşluk/BOM atlandıktan sonra metin `<` + geçerli ad / `?` / `!` ile
	başlamıyorsa XML tarayıcısı HİÇ koşmuyordu. Kapı hedeflediği aşırı-düzeltmeyi
	giderdi ama ÖLÇÜLMÜŞ SIZINTI üretti — 11/11 vektör HAM döndü (tam tablo:
	modül docstring'i, XML SINIRI (d)). Üç örnek:

		'\\xa0<Sifre>SECRETVALUE123</Sifre>'       NBSP öneki
		'HTTP 500: <Sifre>SECRETVALUE123</Sifre>'  HTTP durum öneki
		"'<Sifre>SECRETVALUE123</Sifre>'"          tek tırnak sarmalı

	Baştaki TEK bir karakter markup'ı markup olmaktan çıkarmaz: "bu metin markup
	mı" sorusu KONUMLA değil İÇERİKLE cevaplanır. Aşırı-düzeltmenin gerçek
	kaynağı da kapının yokluğu değildi — `_mask_xml_elements`'in fail-safe
	dalları metinde markup OLUP OLMADIĞINA bakmadan özete iniyordu. Ölçüt artık
	ORADA duruyor (`_contains_markup_construct`), burada DEĞİL.

	Özet döndüğünde metnin TAMAMI onunla değişir; diğer tüm durumlarda ikincil
	katmanlar (URL userinfo, `_mask_delimited_pairs`) ve değer-tabanlı redaksiyon
	AYNEN çalışır.
	"""
	parsed = _try_json(text)
	if parsed is not None:
		masked = json.dumps(_mask_any(parsed, keys, variants, depth + 1), ensure_ascii=False)
		return redact_with_variants(masked, variants)

	text, summary = _mask_xml_elements(text, keys)
	if summary is not None:
		# SINIR ÇÖZÜLEMEDİ: gövdenin tamamı fail-safe özete iner. Devam eden
		# kalıp taramaları (`_mask_delimited_pairs`, URL userinfo) burada
		# ANLAMSIZ olurdu — özette maskelenecek bir şey yok — ve özetin
		# kendisini bozabilirdi.
		return summary

	if "://" in text:
		text = _URL_USERINFO_RE.sub(lambda match: f"{match.group('prefix')}{MASK}@", text)
	if "=" in text or ":" in text:
		text = _mask_delimited_pairs(text, keys)

	return redact_with_variants(text, variants)


def _try_json(text: str) -> Any:
	"""Metni JSON olarak ayrıştırmayı dener; yalnız dict/list sonucunu döndürür.

	Skaler JSON (`"123"`, `"null"`, `"true"`) BİLEREK reddedilir: bunlar
	ayrıştırıldığında maskelenecek bir anahtar/değer çifti içermez ve
	`json.dumps` ile geri yazmak metni sessizce yeniden biçimlendirirdi.

	`RecursionError` DE YAKALANIR: `json.loads` derin girdide (ölçüldü: 3.001
	baytlık `{"a":` zinciri) `RecursionError` fırlatıyor ve yazıcı bunu
	yakalayıp `None` döndürerek LOG SATIRINI DÜŞÜRÜYORDU. `direction='inbound'`
	webhook gövdesi saldırgan kontrolünde olduğu için bu, denetim izini
	bastırma yoluydu.
	"""
	stripped = text.strip()
	if not stripped or stripped[0] not in "{[":
		return None
	try:
		parsed = json.loads(stripped)
	except (ValueError, TypeError, RecursionError):
		return None
	return parsed if isinstance(parsed, (dict, list)) else None


# ---------------------------------------------------------------------------
# XML elemanı — İNDEKS TABANLI tarayıcı (regex DEĞİL)
# ---------------------------------------------------------------------------


def _mask_xml_elements(text: str, keys: frozenset[str]) -> tuple[str, str | None]:
	"""Hassas XML elemanının İÇERİĞİNİ tamamen `***` yapar.

	Döner: `(maskelenmiş metin, özet)`. `özet` None DEĞİLSE çağıran metnin
	TAMAMINI onunla değiştirmelidir (sınır çözülemedi — fail-safe).

	NEDEN REGEX DEĞİL — iki ölçülmüş FAIL-OPEN:

	* **CDATA.** Eski değer grubu `[^<]{0,4096}` idi; `<![CDATA[` ilk
	  karakterinde eşleşmeyi kırıyordu ve `<Sifre><![CDATA[SESSIONABC999]]></Sifre>`
	  DEĞİŞMEDEN dönüyordu. CDATA, TR kargo SOAP yanıtlarında (Aras/Yurtiçi/MNG)
	  yaygındır ve tam da "değer bilinmiyor, tek savunma denylist" senaryosudur:
	  taşıyıcının YANITINDA dönen oturum jetonu `secret_values` içinde YOKTUR.
	  Aynı kök neden değerde geçen çıplak `<` karakterini de kaçırıyordu.
	* **4096 karakter üst sınırı.** `<Token>` + 5000 karakter, ya da açılış
	  etiketinde 512 baytı aşan öznitelik bloğu → eşleşme tamamen düşüyor, yani
	  MASKELEME HİÇ UYGULANMIYORDU. JWT/SAML/uzun oturum jetonu 4 KB'ı rahat aşar.

	Tarayıcı `str.find` döngüsüdür: geri izleme yok, karmaşıklık O(n).
	Sınırsız nicelikleyici GERİ GETİRİLMEZ.

	KAPANIŞ ETİKETİ YOKSA FAIL-CLOSED — ÜÇ TUR ÜST ÜSTE ÖLÇÜLMÜŞ SINIF:
		`mask_payload('<Sifre><![CDATA[SESSIONABC999')` bir zamanlar GİRDİYLE
		AYNI dönüyordu (2. tur). 3. turda sınır "bir sonraki GERÇEK etiket"
		yapıldı; 4. turda o da sızdı, çünkü içerik BİR ÇOCUK ETİKETLE
		BAŞLADIĞINDA sınır hemen `gt + 1`'e düşüyor ve maskelenecek aralık BOŞ
		kalıyordu:

			'<Sifre><Deger>SESSIONTOKEN_ABC999</Deger>'  → GİRDİYLE AYNI
			'<soap:Body><LoginResult><Sifre><Value>TOK'  → GİRDİYLE AYNI
			'<Sifre>\\n<Deger>SESSIONTOKEN_ABC999</Deger>' → '<Sifre>***<Deger>…'

		İkinci satır TR kargo SOAP zarfının KANONİK biçimi; üçüncüsü modülün
		`_scan_value` docstring'inde "hiç maskelememekten daha kötü" diye
		YASAKLADIĞI yanıltıcı kısmi maske. Sınır artık DERİNLİK SAYAR
		(`_ancestor_boundary`): iyi biçimli çocuk alt ağaçlar yutulur, yalnız
		bir ATANIN kapanışı (derinlik < 0) ya da metnin sonu durdurur.

		Sınır neden "metnin sonu" değil de "ata kapanışı": kapanmamış tek bir
		`<Password>` bütün gövdeyi silseydi, `direction='inbound'` webhook
		gövdesine o etiketi ekleyen bir saldırgan DENETİM İZİNİ tamamen
		bastırabilirdi — modülün başka yerde açıkça kapattığı saldırı.

	MARKUP-FARKINDA TARAMA — DÖRDÜNCÜ TURDA KENAR DURUMU ÜRETEN SINIF (5. tur):
		Kapanış araması ham `str.find` idi ve yorum (`<!-- -->`), CDATA
		(`<![CDATA[ ]]>`) ve işlem talimatı (`<?p ?>`) İÇİNDEKİ sahte kapanışı
		GERÇEK sanıyordu. Ölçülen iki sızıntı (özet ÜRETİLMİYORDU, çünkü tarayıcı
		"sınırı buldum" sanıyordu):

			'<R><Token><!-- </Token> -->SESSIONTOKEN_ABC999</Token></R>'
			'<R><Token><![CDATA[</Token>]]>SESSIONTOKEN_ABC999</Token></R>'

		`_find_close_tag`, `_ancestor_boundary` ve `_count_sensitive_tags`
		üçü de artık bu bölgeleri ATLAR (`_markup_region_end`); `</tag>` yalnız
		bölgelerin DIŞINDA kabul edilir. Aynı sınıfın üçüncü üyesi ÖZNİTELİK
		DEĞERİYDİ ve bu testler yazılırken ölçüldü:

			'<Sifre>x<Child a="></Sifre>">SESSIONTOKEN_ABC999</Child>'

		Kapanış araması bu yüzden artık `find(needle)` değil bir YAPI
		YÜRÜYÜŞÜDÜR: her etiket `_tag_end` ile TEK ADIMDA geçilir, öznitelik
		değerinin içine hiç girilmez. Tek geçişli `str.find` döngüsü ve O(n)
		korundu — `at` monoton ilerliyor.

		İLKE: tarayıcının "sınırı buldum" iddiası markup-farkında olmalı; emin
		olamadığı HER durumda özet. Beş turun kanıtladığı şey, elle XML taramanın
		"buldum" iddiasına tek başına güvenilemeyeceğidir.

	MANTIK TERSİNE ÇEVRİLDİ — SINIFI KAPATMA (6. tur):
		Beş tur boyunca kural "TANIDIĞIM yapıları atla, GERİSİNİ İŞLE"ydi ve her
		turda tanınan yapı listesine bir madde eklendi; bir sonraki tur her
		seferinde EKLENMEYENİ buldu (CDATA → 64 KiB → iç içe → yorum/PI +
		öznitelik `>` → `<!` bildirim ailesi). Kural artık tersidir:
		**tanımadığım hiçbir yapıyı İŞLEME, güvenli yöne git.** Somut olarak
		`<!` ile başlayan ve yorum/CDATA olmayan HER dizi (`<!DOCTYPE`,
		`<!ENTITY`, `<!ATTLIST`, `<!ELEMENT`, `<!NOTATION`, `<![IGNORE[`,
		`<![INCLUDE[`, çıplak `<!x`) `_markup_region_end` tarafından
		"çözülemedi" sayılır ve gövde ÖZETE iner. Ölçülen sızıntı:

			'<Sifre>x<!ENTITY e "</Sifre>">TOKEN</Sifre>'
				→ '<Sifre>***</Sifre>">TOKEN</Sifre>'   [SIZINTI]

		Sınır ayrıca AD DOĞRULAR (`_ancestor_boundary`): başıboş `</Yanlis>`
		artık maskeyi erken kapatamaz.

	SINIR ÇÖZÜLEMEZSE FAIL-CLOSED (`_fail_closed`): derinlik taraması metnin
	sonuna AÇIK KALMIŞ çocuklarla (derinlik > 0) ulaşırsa gövde bir elemanın
	ORTASINDAN kesilmiştir — `log.py::MAX_BODY_BYTES` kırpması maskelemeden ÖNCE
	yapıldığı için gerçek taşıyıcı yanıtları rutin olarak böyle gelir. O noktada
	etiket modeli güvenilmezdir. AYNI YOL üç durumda daha işler: tarama BÜTÇESİ
	tükendiğinde, bir markup bölgesi AÇILIP KAPANMADIĞINDA
	(`'<Sifre><![CDATA[SECRET'` — kırpılmış gövdede rutin) ve bir öznitelik
	TIRNAĞI kapanmadığında. KAPALI ve iyi biçimli gövdeler bu yola HİÇ girmez.

	9. TUR — EYLEM YERELLEŞTİ: dördü de eskiden gövdenin TAMAMINI
	`XML_BOUNDARY_UNRESOLVED` özetine indiriyordu; artık yalnız çözülemeyen `<`ten
	SONRASI gider, ÖNCESİ korunur. Özet yalnız korunacak ön ek yokken üretilir.
	Ölçülmüş teşhis kaybı ve tek istisnanın gerekçesi `_fail_closed`
	docstring'indedir.

	ÖZET YOLUNDA `resolved` YAPISAL OLARAK 0'DIR: sayaç ancak `parts`'a bir maske
	yazılırken artar; `parts` doluysa korunacak ön ek VAR demektir ve
	`_fail_closed` yerelleştirmeyi seçer. Parametre yine de taşınır — değişmez
	koşulu kodun kendisi ifade etsin, çağrı yerleri "0 geç" diye bilmek zorunda
	kalmasın.

	Kapanış etiketi bulunamayan hassas bir etiket `dead_tags`'e yazılır: yalnız
	KAPANIŞ ARAMASI atlanır (fail-closed maskeleme yine uygulanır) — 20 bin
	kapanmamış `<Password>` girdisindeki O(k·n) patlaması böyle kapanır.
	Anahtar NORMALİZE edilmiş addır: `<Password>`/`<passWord>`/`<PASSWORD>`
	varyantları tek girdiyi paylaşır (5120 varyant + 1 MB gövde 0,420 sn
	sürüyordu — ölçüldü). XML büyük/küçük harfe duyarlı olduğu için bu
	birleştirme bir varyantın kapanışını "yok" sayabilir; yön GÜVENLİDİR
	(fazla maskeleme), asla ham bırakma değil.

	MEMOİZASYON MONOTON DEĞİL, AMA YÖNÜ GÜVENLİ: `_find_close_tag` artık bir
	BÜTÇE penceresiyle arıyor, yani ileri konumdaki bir arama ilkinin görmediği
	metne bakabilir. 3. turda aynı gözlem SIZINTIYDI (sabit 64 KiB penceresi +
	"kesin bulunamaz" iddiası), çünkü yanlış işaretleme HAM BIRAKMAYA yol
	açıyordu. Bugün yanlış işaretlemenin tek sonucu fail-closed maskeleme ya da
	özet — teşhis kaybı, sızıntı değil. `_MAX_ELEMENT_SPAN` tarzı sabit pencere
	GERİ GETİRİLMEZ.
	"""
	parts: list[str] = []
	pos = 0
	cursor = 0
	length = len(text)
	dead_tags: set[str] = set()
	budget = max(_MIN_TAG_SCAN_BUDGET, _TAG_SCAN_BUDGET_FACTOR * length)
	resolved = 0
	# AÇIK ATA ADLARI (6. tur). `_ancestor_boundary` derinliği AD-KÖR sayıyordu
	# ve derinlik 0'da gördüğü HERHANGİ bir kapanışı "ata kapanışı" sanıyordu;
	# başıboş bir `</Yanlis>` maskeyi ERKEN kapatıyordu. Sınırın gerçekten bir
	# ATAYA ait olduğunu doğrulayabilmek için ata adları buradan taşınıyor.
	open_stack: list[str] = []
	open_counts: dict[str, int] = {}

	while cursor < length:
		lt = text.find("<", cursor)
		if lt < 0:
			break

		region = _markup_region_end(text, lt, length)
		if region is None:
			# Bölge AÇILIP KAPANMADI ya da `<!` bildirimi — tarayıcı yapıyı
			# ANLAMIYOR. Etiket modeli buradan sonra güvenilmez.
			if resolved == 0 and not _contains_markup_construct(text):
				# Metinde markup benzeri TEK BİR yapı bile yok: bu bir XML
				# gövdesi değil, `'error: 5 < 10 gecti'` gibi düz metindir.
				break
			return _fail_closed(text, parts, pos, lt, resolved, keys)
		if region != _NOT_MARKUP:
			# Bölgenin İÇİ karakter verisidir; içindeki `<Sifre>` eleman değildir.
			cursor = region
			continue

		closing = text.startswith("</", lt)
		match = _TAG_NAME_RE.match(text, lt + 2 if closing else lt + 1)
		if match is None:
			# ULAŞILMAZ: `_looks_like_tag` (tek karar noktası) geçerli adı olmayan
			# her `<` dizisini zaten `None` yaptı. Savunma amaçlı GÜVENLİ yön —
			# ama düz metni özete indirmemek için ölçüt burada da sorulur.
			if resolved == 0 and not _contains_markup_construct(text):
				break
			return _fail_closed(text, parts, pos, lt, resolved, keys)

		gt = _tag_end(text, match.end())
		if gt == _TAG_END_AMBIGUOUS:
			# Kapanmamış öznitelik tırnağı. Eskiden ham `find(">")` tırnak içindeki
			# `>`ı etiket sonu sayıp yoluna devam ediyordu; ham `break` ise geri
			# kalan gövdeyi OLDUĞU GİBİ yazardı (`'<a b="><Sifre>SECRET'` ölçüldü).
			if resolved == 0 and not _contains_markup_construct(text):
				break
			return _fail_closed(text, parts, pos, lt, resolved, keys)
		if gt == _TAG_END_TRUNCATED:
			# Metin YARIM bir etiketin ortasında bitti. `_TAG_END_TRUNCATED`ın
			# gerekçesi "kuyrukta ELEMAN İÇERİĞİ olamaz, tarayıcı güvenle durur"du
			# ve İÇERİK için doğrudur — ama kuyrukta ÖZNİTELİK DEĞERİ olabilir.
			# 64 KiB kırpma süpürmesinde ölçüldü (301 kesim noktası, öznitelikli
			# gövde): `<Sifre deger="SESSIONTOKEN_ABC999` gibi yarım kalmış hassas
			# açılış etiketleri HAM geçiyordu. Kırpma maskelemeden ÖNCE yapıldığı
			# için bu, gerçek taşıyıcı yanıtlarında ERİŞİLEBİLİR bir yoldur.
			# YALNIZ hassas ADLI açılış etiketinde fail-closed olunur; sıradan bir
			# yarım etiket (`'metin sonunda <Takip'`) aşırı maskelenmez.
			if not closing and _is_sensitive_normalized(_normalize_key(match.group(0)), keys):
				return _fail_closed(text, parts, pos, lt, resolved, keys)
			break
		cursor = gt + 1

		if closing:
			# Kapanış etiketi artık YUTULMUYOR, yığından DÜŞÜLÜYOR: `_ancestor_boundary`
			# ata adlarını buradan alıyor. Eşleşmeyen kapanış yok sayılır.
			_close_element(open_stack, open_counts, match.group(0))
			continue

		tag = match.group(0)
		normalized = _normalize_key(tag)
		sensitive = _is_sensitive_normalized(normalized, keys)
		#: Hassas elemanın AÇILIŞ ETİKETİ, öznitelik DEĞERLERİ maskelenmiş hâlde
		#: (9. tur — aşağıdaki üç kullanımın tamamı bu tek üretimi paylaşır).
		open_tag = (
			text[pos : match.end()] + _mask_tag_attributes(text, match.end(), gt) + text[gt : gt + 1]
			if sensitive
			else ""
		)

		if text[gt - 1] == "/":
			# KENDİ KENDİNE KAPANAN ETİKET (9. tur). Eskiden koşulsuz `continue`
			# ediliyordu, gerekçe "değeri öznitelikte, onu `_mask_delimited_pairs`
			# ele alır"dı. YANLIŞTI: o katman yalnız ÖZNİTELİK ADINA bakar ve
			# "içinde bulunduğun ELEMAN hassas" bilgisini hiç almaz.
			if sensitive:
				parts.append(open_tag)
				pos = gt + 1
				cursor = gt + 1
				resolved += 1
			continue

		if not sensitive:
			_open_element(open_stack, open_counts, tag)
			continue

		bounds = None
		if normalized not in dead_tags:
			bounds, spent = _find_close_tag(text, gt + 1, tag, budget)
			budget -= spent
		if bounds is not None:
			# Alt ağaç DENGELİ olarak atlanıyor: hassas etiket kendi kapanışıyla
			# birlikte tüketildi, ata yığını değişmez (bu yüzden PUSH yok).
			close_start, close_end = bounds
			parts.append(open_tag)
			parts.append(MASK)
			pos = close_start
			cursor = close_end
			resolved += 1
			continue

		dead_tags.add(normalized)
		# Hassas etiket kapanmamış sayılıyor → örtük olarak burada kapanır,
		# ata yığınına GİRMEZ; `stop` bir ATANIN kapanışıdır ve o kapanış bir
		# sonraki turda normal yoldan yığından düşer.
		stop, spent = _ancestor_boundary(text, gt + 1, budget, open_counts)
		budget -= spent
		if stop is None:
			# Sınır GÜVENLE belirlenemedi (kırpılmış gövde ya da bütçe bitti).
			# Buraya gelindiyse metin ZATEN markup'tır (hassas bir açılış etiketi
			# bulundu); ölçüt yine de sorulur — dört dalın tek bir kuralı olsun.
			if resolved == 0 and not _contains_markup_construct(text):
				break
			return _fail_closed(text, parts, pos, lt, resolved, keys)
		parts.append(open_tag)
		parts.append(MASK)
		pos = stop
		cursor = stop
		resolved += 1

	parts.append(text[pos:])
	return "".join(parts), None


def _mask_tag_attributes(text: str, start: int, gt: int) -> str:
	"""HASSAS bir elemanın açılış etiketindeki TÜM öznitelik DEĞERLERİNİ `MASK` yapar.

	Args:
		text: Gövdenin tamamı.
		start: Etiket ADININ bittiği indeks (`_TAG_NAME_RE` eşleşmesinin sonu).
		gt: Etiketi kapatan `>` indeksi (`_tag_end` ile TIRNAK-FARKINDA bulunmuş).

	Returns:
		`text[start:gt]` bölgesinin maskelenmiş hâli (etiket adı ve `>` çağıranda).

	ÖLÇÜLMÜŞ SIZINTI (9. tur) — ELEMANIN KENDİ ÖZNİTELİĞİ HAM GEÇİYORDU:
		`_mask_xml_elements` hassas bir açılış etiketi bulunca etiketin TAMAMINI
		(öznitelik bloğu dahil) `parts`'a HAM yazıyor, yalnız İÇERİĞİ `***`
		yapıyordu; kendi kendine kapanan hassas etikette ise HİÇ maskeleme
		yapmıyordu. Koddaki gerekçe "değeri öznitelikte, onu `_mask_delimited_pairs`
		ele alır"dı ve YANLIŞTI: o katman yalnız ÖZNİTELİK ADINA bakar, "içinde
		bulunduğun ELEMAN hassas" bilgisini hiç almaz. İki katmanın sözleşmesi tam
		burada ayrışıyordu. Ölçüm (`mask_payload`, jeton bir taşıyıcı YANITINDAKİ
		oturum jetonu yerine geçiyor — değeri önceden BİLİNMEZ, yani birincil
		değer-tabanlı katman bu sınıfta YARDIM EDEMEZ):

			'<Sifre deger="SESSIONTOKEN_ABC999"/>'               → DEĞİŞMEDEN
			'<Sifre deger="SESSIONTOKEN_ABC999">icerik</Sifre>'  → '…ABC999">***</Sifre>'
			'<R><ApiKey k="SESSIONTOKEN_ABC999"/><Takip>TR-1</Takip></R>' → DEĞİŞMEDEN

		İkinci satır yalnız sızıntı değil YANILTICI maskedir: çıktıda `***` görünür,
		operatör "redakte edildi" sanır, jeton yanındaki öznitelikte durur.
		TOPLU ÖLÇÜM: 63 hassas ad × 10 öznitelik adı × 2 şekil = 1260 vektör,
		1260'ı HAM sızıyordu (630'u yanıltıcı maske taşıyordu). Girdilerin hepsi
		İYİ BİÇİMLİ XML'dir (ElementTree kabul eder), hiçbir fail-safe dalı
		tetiklenmez, özet üretilmez — yani bu, `_find_close_tag` sınıfıyla aynı
		aileden: **"yanlış anladım ama anladığımı sandım."**

	KURAL: ELEMAN hassassa ÖZNİTELİK ADINA BAKILMAZ — değerleri de hassastır.
	`xmlns` bildirimleri, `id`, `type` gibi teşhis öznitelikleri de maskelenir;
	yön FAIL-CLOSED seçildi (modülün "yanlış pozitif ödünleşmesi" doktrini).
	Öznitelik ADLARI ve etiket adı KORUNUR — teşhis için gereken yapı bilgisi
	(`<Sifre deger="***"/>`) ayakta kalır, yalnız değerler gider.

	TEK İSTİSNA — `NON_SENSITIVE_KEYS` (10. tur, ÖLÇÜLMÜŞ AŞIRI MASKELEME):
		Kural 9. turda `NON_SENSITIVE_KEYS`i TAMAMEN atlıyordu, yani operatör
		modülün BELGELENMİŞ kaçış kapısına bir teşhis alanı eklediğinde bu yolda
		HİÇBİR ŞEY değişmiyor ve nedenini de göremiyordu:

			'<Kod tracking_number="TR123456789" error_code="4021"
			      status_code="401" barkod="1234567890123">E</Kod>'
				→ '<Kod tracking_number="***" error_code="***"
				        status_code="***" barkod="***">***</Kod>'
			KONTROL '<Sonuc tracking_number="TR123456789" …/>' → DEĞİŞMEDEN

		`<Kod>` TR kargo XML'inin en yaygın sonuç/durum elemanıdır (`kod`
		denylist'tedir) — yani bu, nadir değil BASKIN yoldur. Gerçekçi 164 KB'lık
		bir gövdede yalnız bu kuraldan 17.890 karakter ve 900/900 zaman damgası
		kayboluyordu. Öznitelik adı bugün `NON_SENSITIVE_KEYS` ile TAM AD
		karşılaştırılır (SON EK OLARAK DEĞİL — modülün kendi kuralı, bkz. o
		kümenin gerekçesi) ve eşleşen özniteliğin değeri BIRAKILIR.

		TAKAS (bilinçli): `direction="inbound"` bir webhook'ta saldırgan
		`<Sifre tracking_number="JETON"/>` yazıp değeri ham geçirebilir. O jeton
		SALDIRGANIN KENDİ verisidir; bu katmanın koruduğu sınıf taşıyıcının
		YANITINDA dönen jetondur ve hiçbir taşıyıcı jetonu `error_code` /
		`tracking_number` adlı bir özniteliğe koymaz. Ayrıca `secret_values`
		verilmişse değer-tabanlı birincil katman o değeri yine yakalar.

	BELGELENMİŞ SINIR — `=` İLE TÜKETİLMEYEN BELİRTEÇ HAM KALIR:
		Tarama `=` etrafında yürür; öznitelik bloğunda `=` ile tüketilmeyen bir
		belirteç (HTML'de geçerli boolean öznitelik: `<Sifre disabled>`) olduğu
		gibi kalır. ÖLÇÜLDÜ VE ERİŞİLEMEZ: 720 yönlendirilmiş iyi-biçimli vektör
		+ 40.000 fuzz + 301 kesim noktası → iyi biçimli XML'de 0 sızıntı, çünkü
		XML'de öznitelik değeri HER ZAMAN `=` sonrası tırnaklıdır (`AttValue`
		üretimi başka biçim tanımaz). Kapatmanın tek yolu "tırnaksız her belirteci
		maskele" olurdu; bu, boolean öznitelikli HTML parçalarında aşırı maskeleme
		üretir ve etiketin yapı bilgisini sessizce siler. Gerçek bir taşıyıcının
		boolean öznitelikte sır taşıdığı GÖZLENİRSE karar yeniden açılmalı.

	HASSAS OLMAYAN elemanın öznitelikleri BU FONKSİYONA HİÇ GİRMEZ; onlar için
	bugünkü `_mask_delimited_pairs` davranışı (ad-tabanlı) aynen korunur —
	`'<Adres il="Istanbul"/>'` değişmeden geçmeye devam eder.

	TIRNAK-FARKINDA: tek tırnak, çift tırnak ve (HTML'de geçerli, XML'de değil)
	TIRNAKSIZ değer ayrı ayrı ele alınır. `gt` zaten `_tag_end` ile tırnak
	bölgelerini atlayarak bulunduğu için `[start, gt)` aralığı TEK bir etiketin
	öznitelik bloğudur; tarama o aralığın dışına ÇIKAMAZ. Tırnaksız değerin
	sonundaki `/` (kendi kendine kapanan etiket) DEĞERE DAHİL EDİLMEZ, aksi hâlde
	`'<Sifre deger=abc/>'` → `'<Sifre deger=***>'` olur ve etiketin kendi kendine
	kapanma bilgisi sessizce kaybolurdu.

	MALİYET: `[start, gt)` üzerinde tek geçişli `str.find` döngüsü, geri izleme
	yok, O(etiket uzunluğu). Etiketlerin aralıkları ayrık olduğu için toplam O(n)
	korunur — ReDoS profili değişmez (ölçüldü: depodaki tüm zamanlama vektörleri).
	"""
	out: list[str] = []
	at = start
	while at < gt:
		eq = text.find("=", at, gt)
		if eq < 0:
			break
		index = eq + 1
		while index < gt and text[index] in " \t\r\n":
			index += 1
		if index >= gt:
			break
		keep = _is_allowlisted_attribute(text, at, eq)
		quote = text[index]
		if quote in "\"'":
			close = text.find(quote, index + 1, gt)
			if close < 0:
				# ULAŞILMAZ: tırnak `gt`den önce kapanmasaydı `_tag_end`
				# `_TAG_END_AMBIGUOUS` döner ve çağıran buraya hiç gelmezdi.
				# Savunma amaçlı GÜVENLİ yön: kalan blok tamamen maskelenir
				# (allowlist BU dalda uygulanmaz — sınırı bilmeden bırakılamaz).
				out.append(text[at : index + 1])
				out.append(MASK)
				return "".join(out)
			if keep:
				out.append(text[at : close + 1])
			else:
				out.append(text[at : index + 1])
				out.append(MASK)
				out.append(quote)
			at = close + 1
			continue
		end = index
		while end < gt and text[end] not in " \t\r\n":
			end += 1
		if end == gt and text[end - 1] == "/":
			end -= 1
		if end == index:
			# Tırnaksız değer BOŞ (`'<Sifre a=/>'`): maskelenecek bir şey yok,
			# ama `at`i ilerletmezsek aynı `=` sonsuza kadar bulunurdu.
			at = index
			continue
		if keep:
			out.append(text[at:end])
		else:
			out.append(text[at:index])
			out.append(MASK)
		at = end
	out.append(text[at:gt])
	return "".join(out)


def _is_allowlisted_attribute(text: str, low: int, eq: int) -> bool:
	"""`eq`'deki `=` işaretinin ÖZNİTELİK ADI `NON_SENSITIVE_KEYS`'te mi (TAM AD)?

	Ad, `=`ten GERİYE doğru okunur: önce boşluk (`Eq ::= S? '=' S?`) atlanır,
	sonra bir sonraki boşluk/tırnak/`/`/`<`e kadar olan belirteç alınır. Tarama
	`low`un (bir önceki özniteliğin bittiği yer, ya da etiket adının sonu)
	GERİSİNE GEÇMEZ.

	Karşılaştırma `_is_sensitive_normalized`in allowlist adımıyla AYNI ifadedir
	(`_allow_forms` × `_normalized_haystack(NON_SENSITIVE_KEYS)`) — yani TAM AD,
	SON EK DEĞİL. İki yerde iki farklı kural olsaydı operatörün kaçış kapısı
	yoluna göre farklı davranırdı; ölçülen tam da o asimetriydi (bkz.
	`_mask_tag_attributes` docstring'i).
	"""
	end = eq
	while end > low and text[end - 1] in " \t\r\n":
		end -= 1
	begin = end
	while begin > low and text[begin - 1] not in " \t\r\n\"'/<":
		begin -= 1
	name = text[begin:end]
	if not name:
		return False
	return bool(_allow_forms(_normalize_key(name)) & _normalized_haystack(NON_SENSITIVE_KEYS))


def _fail_closed(
	text: str, parts: list[str], pos: int, lt: int, resolved: int, keys: frozenset[str]
) -> tuple[str, str | None]:
	"""Çözülemeyen bir `<`ten SONRASINI maskeler; korunacak ön ek YOKSA özete iner.

	Args:
		text: Gövdenin tamamı.
		parts: O ana kadar üretilmiş çıktı parçaları (maskelenmiş ön ek).
		pos: `parts`'a henüz yazılmamış ham bölgenin başlangıcı.
		lt: Çözülemeyen `<` karakterinin indeksi.
		resolved: Bu noktadan ÖNCE sınırı çözülüp maskelenmiş hassas etiket sayısı.
		keys: Hassas anahtar kümesi.

	Returns:
		`_mask_xml_elements` sözleşmesindeki `(metin, özet)` ikilisi.

	ÖLÇÜLMÜŞ TEŞHİS KAYBI (9. tur) — YEREL TETİKLEYİCİ, GLOBAL EYLEM:
		Dört fail-safe dalı (`region is None`, `match is None`,
		`_TAG_END_AMBIGUOUS`, `_ancestor_boundary → None`) TEK bir çözülemeyen `<`
		yüzünden GÖVDENİN TAMAMINI özete indiriyordu — o `<`ten ÖNCEKİ, tamamen
		anlaşılmış ve zaten maskelenmiş kısım dahil. `log.py::MAX_BODY_BYTES`
		(64 KiB) kırpması maskelemeden ÖNCE yapıldığı için bu dal gerçek taşıyıcı
		yanıtlarında rutin olarak tetiklenir. 301 kesim noktasında ölçüm
		(gerçekçi TR kargo XML'i):

			öznitelikli gövde: 130/301 kesim noktası TÜM gövdeyi siliyor
			CDATA'lı gövde:    154/301
			düz gövde:          40/301
			JSON gövde:          0/301   (sorun XML/HTML'e özgü)

		Operatöre kalan ortalama karakter: özet 32.000-57.000 | yerelleştirme 65.380.

	YENİ KURAL — KORUNACAK ÖN EK VARSA YERELLEŞTİR, YOKSA ÖZETLE:
		`text[pos:lt]` + `MASK` döndürülür; `lt`ten METNİN SONUNA kadar HER ŞEY
		gider. Sızıntı yönü değişmez, çünkü `lt`ten önceki bölgede kalan hassas
		elemanların hepsi ZATEN işlenmiştir (`pos` onların ötesine taşınmıştır) ve
		dördüncü dalda `lt` hassas etiketin KENDİ başlangıcıdır — o da maskenin
		İÇİNDE kalır.

		AMA korunacak ön ek BİLGİ TAŞIMIYORSA ESKİ ÖZET KORUNUR. Gerekçe ÖLÇÜLDÜ:
		`<!DOCTYPE html>` ile başlayan bir taşıyıcı/vekil HTML hata sayfasında
		yerelleştirme yalnız `'***'` üretir — bu, özetten BİLGİ OLARAK DAHA
		AZDIR, çünkü bayt sayısı da kaybolur. Özet "N bayt, K hassas alan"
		bilgisini taşır ve ön ek yokken TEK bilgi kaynağıdır.

	ÖLÇÜT KONUMSAL DEĞİL İÇERİKSEL — 10. TUR (8. TURUN DERSİ TEKRARLIYORDU):
		Kapı `lt == 0 and not parts` idi, yani KONUMA bakıyordu. Aynı gövde tek
		karakterlik bir önekle %93 daha az bilgi veriyordu (ölçüldü;
		HTML = `'<!DOCTYPE html>\\n<html><body>502 Bad Gateway …</body></html>'`):

			ön ek YOK    → 57 kr  '<XML gövdesi, 100 bayt, 0 hassas alan — …>'
			tek boşluk   →  4 kr  ' ***'
			BOM          →  4 kr  '\\ufeff***'
			satır sonu   →  4 kr  '\\n***'

		Docstring'in KENDİ ÖRNEĞİ (`<!DOCTYPE html>` hata sayfası) tam olarak
		tek karakterlik bir önekle bozuluyordu. 8. tur bu önek listesini
		(`\\xa0`, `\\u200b`, `ï»¿`, `HTTP 500: `, tek tırnak) SIZINTI kaynağı
		olarak ölçmüştü — burada aynı liste TEŞHİS KAYBI kaynağıydı; iki kez
		aynı ders: **KONUM ÖLÇÜTÜ YANLIŞ ÖLÇÜTTÜR.**

		Karar bugün İÇERİKLE verilir: ön ek yalnız boşluk/BOM/kontrol karakteri
		içeriyorsa (`_carries_information` False) özete inilir. SIZINTI RİSKİ
		SIFIR — karar iki ZATEN-REDAKTE-EDİLMİŞ çıktı arasında yapılır; `lt`ten
		sonrası her iki dalda da bütünüyle gider. `HTTP 500: ` ve SOAP fault gibi
		GERÇEK bilgi taşıyan önekler yerelleştirmede KORUNMAYA devam eder.

	BİLİNEN TAKASLAR (ikisi de bilinçli):

	* Özet, ön ekte "YANLIŞ POZİTİF bir sınır iddiası" olsaydı onu da siliyordu —
	  yani tesadüfi bir İKİNCİ savunma katmanıydı. Yerelleştirme onu bırakır.
	  O sınıf (`_find_close_tag`in aynı adlı toruna kanması) 7. turda derinlik
	  sayımıyla kapatıldı ve `TestXmlSameNameDescendant` ile kilitlidir; ikinci
	  savunmaya dayanmak zaten "ölçülmemiş güvence"ydi.
	* Yerelleştirme ÖN EKTEKİ YORUM/CDATA İÇERİĞİNİ HAM BIRAKIR (ölçüldü):

			'<!-- <Sifre>TOKEN</Sifre> -->…<!'  → yorum GÖVDESİ ham kalır

	  Bu 9. tur ÖNCESİ de doğruydu — `_markup_region_end` "bölgenin içi karakter
	  verisidir" der ve bir yorumun içindeki `<Sifre>` bir eleman DEĞİLDİR — ama
	  eski GLOBAL özet o bölgeyi tesadüfen örtüyordu. Kararın kendisi (yorum
	  içeriğini eleman saymamak) doğrudur; onu kapatmak her yorum satırını
	  maskelemek demektir. Sınıf burada ADLANDIRILMIŞTIR ki bir sonraki tur bunu
	  "yeni sızıntı" sanmasın; gerçek çözüm çağıranın `secret_values` geçmesidir.
	"""
	prefix = "".join(parts) + text[pos:lt]
	if not _carries_information(prefix):
		return "", _summarize_xml(text, lt, resolved, keys)
	parts.append(text[pos:lt])
	parts.append(MASK)
	return "".join(parts), None


def _carries_information(prefix: str) -> bool:
	"""Korunacak ön ek TEŞHİS BİLGİSİ taşıyor mu?

	`False` yalnız ön ek TAMAMEN görünmez karakterlerden oluşuyorsa döner:
	boşluk (`Zs`/`Zl`/`Zp` + `str.isspace`), BOM/sıfır genişlikli işaretler
	(`Cf`) ve kontrol karakterleri (`Cc`). Böyle bir ön ek `' ***'` çıktısında
	operatöre HİÇBİR ŞEY söylemez; oysa özet bayt ve alan sayısını taşır.

	`'HTTP 500: '`, SOAP fault metni, latin1'e düşmüş BOM (`ï»¿` — mojibake ama
	GÖRÜNÜR karakterler) ve tek tırnak sarmalı BİLGİ SAYILIR ve korunur.
	"""
	return any(unicodedata.category(char) not in _INVISIBLE_CATEGORIES for char in prefix)


def _markup_region_end(text: str, lt: int, limit: int) -> int | None:
	"""`lt`'de bir markup bölgesi (yorum/CDATA/PI) başlıyor mu, başlıyorsa nerede biter.

	Döner:
		`_NOT_MARKUP` (-1): burada bölge yok — çağıran normal etiket işlemesine devam eder.
		`None`: yapı GÜVENLE ÇÖZÜLEMEDİ. ÜÇ alt durum var ve üçü de aynı
			cevabı hak eder: (a) bölge AÇILDI ama `limit` içinde KAPANMADI
			(kırpılmış gövdede — 64 KiB tavanı — RUTİN), (b) `<!` ile başlayan
			ve yorum/CDATA OLMAYAN bir markup BİLDİRİMİ (`<!DOCTYPE`, `<!ENTITY`,
			`<!ATTLIST`, `<!ELEMENT`, `<!NOTATION`, `<![IGNORE[`, `<![INCLUDE[`,
			çıplak `<!x`) — tarayıcı bu dil bilgisini AYRIŞTIRMIYOR, (c) `<`
			GEÇERLİ BİR ADLA devam ETMİYOR (`_looks_like_tag`, 7. tur — aşağıda).
			Üçü de etiket modelini geçersiz kılar; çağıran fail-safe ÖZETE inmelidir
			— METİN GERÇEKTEN MARKUP İSE. `'error: 5 < 10 gecti'` gibi hiçbir markup
			yapısı içermeyen düz metinde özet TEŞHİSİ YOK EDER ve saklanacak bir şey
			de yoktur; ölçüt çağıranda (`_contains_markup_construct`, 8. tur).
		`>= 0`: bölgenin kapanışından SONRAKİ ilk indeks.

	TEK KARAR NOKTASI: düzeltme bilerek burada duruyor — üç tarayıcı
	(`_mask_xml_elements`, `_find_close_tag`, `_ancestor_boundary`) ve
	`_count_sensitive_tags` bu fonksiyonu çağırdığı için dördü birden düzelir.
	5. tur aynı sınıfı üç çağrı yerinde AYRI AYRI ele almıştı; bu bir sonraki
	yapının yine bir çağrı yerinde unutulması demekti.

	Kapanış araması `limit` ile sınırlı: bölge kapanışı bütçe penceresinin
	dışındaysa da "bilmiyorum" cevabı verilir (yön güvenli). Çağıranların hepsi
	`limit`'e kadar İLERLEYEREK tarar, bu yüzden bölge taramaları AYRIKTIR ve
	toplam maliyet O(n) kalır — bölge başına metin sonuna kadar tarama YOK.

	FAIL-SAFE MALİYETİ ÖLÇÜLDÜ (7. tur) — karar YÖN OLARAK DOĞRU, DEĞİŞTİRİLMEDİ.
	7. turda maliyet şuydu: saldırganın `direction='inbound'` gövdesine eklediği
	İKİ BAYT (`<!`) TÜM denetim izini özete indiriyordu; gövdede hassas etiket
	BULUNMASI GEREKMEZDİ.

		'<Root><Takip>TR-123456</Takip><Durum>Teslim</Durum>'
		'<Sube>Kadikoy</Sube></Root>' + '<!'
			→ '<XML gövdesi, 80 bayt, 0 hassas alan — sınır çözülemedi>'  [7. TUR]
			→ '<Root><Takip>TR-123456</Takip>…</Root>***'                 [9. TUR]

	9. TURDA BU MALİYET BÜYÜK ÖLÇÜDE KAPANDI: `_fail_closed` eylemi çözülemeyen
	`<`ten SONRASIYLA sınırlar, yani takip numarası/durum/şube artık HAYATTA
	kalır. Kararın kendisi (bildirimi AYRIŞTIRMAMAK) değişmedi — alternatif,
	6. turda ölçülen ham sızıntının ta kendisiydi. Bu bir MALİYET VEKTÖRÜ de
	DEĞİLDİR (64 KiB'lık `<!` gövdesi 0,01 ms) ve YAN KANAL da değildir.
	"""
	for opener, closer in _MARKUP_REGIONS:
		if text.startswith(opener, lt):
			close = text.find(closer, lt + len(opener), limit)
			return None if close < 0 else close + len(closer)
	if text.startswith(_MARKUP_DECLARATION, lt):
		# TANIMADIĞIM YAPI → GÜVENLİ YÖN. Bildirimin nerede bittiğini bilmeden
		# "buradan sonrası eleman içeriğidir" iddiası kurulamaz; içindeki sahte
		# kapanışı GERÇEK saymak tam olarak 6. turda ölçülen sızıntıydı.
		return None
	if not _looks_like_tag(text, lt):
		# AYNI İLKENİN SON CEBİ (7. tur): `<` geçerli bir ADLA devam etmiyorsa
		# tarayıcı burada NE OLDUĞUNU bilmiyor. Üç tarayıcı da eskiden tek
		# karakter ilerleyip DEVAM ediyordu — yani "anlamadığım diziyi yok say".
		return None
	return _NOT_MARKUP


def _looks_like_tag(text: str, lt: int) -> bool:
	"""`lt`'deki `<` GEÇERLİ ADLI bir etiket (açılış ya da kapanış) başlatıyor mu.

	KARAR TEK YERDE (`_markup_region_end` bunu çağırır): 5. turun dersi tam
	olarak buydu — aynı sınıf üç çağrı yerinde AYRI AYRI ele alındığında bir
	sonraki yapı yine bir çağrı yerinde unutuluyor. `_mask_xml_elements`,
	`_find_close_tag` ve `_ancestor_boundary` artık `_TAG_NAME_RE` eşleşmesini
	KENDİ BAŞLARINA yorumlamaz; üçünün de "eşleşme yok" dalı ULAŞILMAZDIR ve
	savunma amaçlı fail-safe'e bağlanmıştır.

	ÖLÇÜLEN SIZINTI (şiddet MINOR — girdi hiçbir XML ayrıştırıcısı tarafından
	kabul edilmiyor, ElementTree: "not well-formed"; sızıntı ancak HTML5
	tokenizer semantiği varsayılırsa gerçek, çünkü orada `</` + harf-olmayan bir
	BOGUS COMMENT'tir ve `>`a kadar yutulur):

		'<Sifre>x</</Sifre>SESSIONTOKEN_ABC999</Sifre>'
			→ '<Sifre>***</Sifre>SESSIONTOKEN_ABC999</Sifre>'

	Aynı davranış `<>`, `</>`, `<//>`, `< ` ile de üretildi (5 vektör).
	"""
	return _TAG_NAME_RE.match(text, lt + 2 if text.startswith("</", lt) else lt + 1) is not None


def _contains_markup_construct(text: str) -> bool:
	"""Metnin HERHANGİ BİR YERİNDE markup benzeri TEK BİR yapı var mı?

	ÖZETE İNME ÖLÇÜTÜ (8. tur, Paket M). `_mask_xml_elements`'in DÖRT fail-safe
	dalı bu soruyu sorar; cevap `False` ise özet ÜRETİLMEZ, tarayıcı ana
	döngüden çıkar ve o ana kadar maskelenmiş kısım + kalan HAM metin döner.

	İKİ AYRI SORU, İKİ AYRI MEKANİZMA:
		1. "Bu metin MARKUP mı?"          → BU fonksiyon
		2. "Markup'ı AYRIŞTIRABİLDİM Mİ?" → `_markup_region_end` + fail-safe özet
	Bir ara tur ikisini tek karara bağlamış ve 1. soruyu metnin BAŞINA bakarak
	(`_looks_like_xml_body`) cevaplamıştı. Aşırı-düzeltme gerçekten kapandı ama
	KONUM ölçütü 11/11 vektörde SIZDIRDI (`\\xa0`, `\\u2028`, `\\u2029`, `\\u3000`,
	`\\x85`, `\\u200b`, `\\x00` önekleri; latin1'e düşmüş BOM `ï»¿`; `HTTP 500: `;
	SOAP fault öneki; tek tırnak sarmalı) — tam tablo modül docstring'inde,
	XML SINIRI (d). Baştaki TEK bir karakter markup'ı markup olmaktan çıkarmaz;
	soru İÇERİKLE ilgilidir, konumla değil.

	YAPI-KÖR TARAMA: her `<` için yalnız iki şey sorulur — ardından `!` ya da `?`
	geliyor mu, yoksa `_looks_like_tag` (kapanış `</Ad` dahil) geçerli bir ad
	görüyor mu. `_markup_region_end`, kapanış eşleştirme ve derinlik mantığı
	BİLEREK KULLANILMAZ: burada amaç yapıyı ANLAMAK değil, "markup var mı"
	demektir. Yorum içindeki `<Sifre>`yi de saymak SORUN DEĞİLDİR — fazla sayım
	yalnız özete indirir, ASLA ham bırakmaz.

	BİLİNEN VE ÖLÇÜLMÜŞ SINIR — BOZUK ADLI HASSAS ETİKET (bilinçli takas):
		Gövdenin TAMAMINDA tek bir geçerli etiket yoksa ve hassas veri XML'in
		ad kuralına UYMAYAN bir etikette taşınıyorsa ham geçer (ölçüldü):

			'<2Sifre>TOKEN</2Sifre>'  '<-Sifre>…'  '<.Sifre>…'  '< Sifre>…'

		ERİŞİLEBİLİR DEĞİL: uyumlu hiçbir XML üreticisi rakam/tire/nokta/boşlukla
		BAŞLAYAN ad yaymaz, üstelik sızıntı için gövdede kök eleman dahil TEK bir
		geçerli etiketin bile bulunmaması gerekir — gerçek bir yanıtta kök her
		zaman geçerlidir. Aynı şekil bir gövdenin İÇİNDE geçtiğinde (`'<R><2Sifre>…'`)
		kök geçerli olduğu için ölçüt `True` döner ve özete iner.

		NEDEN KAPATILMADI: kapatmanın tek yolu `<`ten sonra kısa bir "bozuk ad"
		sıçraması yapıp hassas ad aramaktır. O kural `'deger < 5 sifre kadar'`
		gibi DÜZ METİN bir hata mesajını özete indirir (ölçüldü). Yani erişilemez
		bir sızıntı, daha olası bir TEŞHİS KAYBIYLA takas edilmiş olurdu — bu
		modülün bir ara turda tam tersi yönde yaptığı hatanın aynısı. Gerçek bir
		taşıyıcının bozuk adlı etiket yaydığı GÖZLENİRSE karar yeniden açılmalı.
		Sınır `test_malformed_name_tags_are_a_documented_limit` ile KİLİTLİDİR.

	MALİYET: tek geçişli `str.find` döngüsü, geri izleme yok, O(n). `_mask_text`
	çağrısı başına EN FAZLA BİR KEZ koşar (her dal ya `return` ya `break` eder).
	Tarama `_MIN_TAG_SCAN_BUDGET` karakterle kırpılır; bütçe biterse `True`
	dönülür — EMİN OLMADIĞINDA GÜVENLİ YÖN ÖZETE İNMEKTİR. Bütçe (256 KiB)
	`log.py::MAX_BODY_BYTES` kırpmasının (64 KiB) dört katıdır, yani gerçek log
	gövdeleri bu dala hiç girmez.
	"""
	length = len(text)
	limit = min(length, _MIN_TAG_SCAN_BUDGET)
	at = 0
	while at < limit:
		lt = text.find("<", at, limit)
		if lt < 0:
			break
		if text.startswith(("<!", "<?"), lt) or _looks_like_tag(text, lt):
			return True
		at = lt + 1
	return limit < length


def _tag_end(text: str, start: int) -> int:
	"""Etiket sonu `>`ını TIRNAK BÖLGELERİNİ ATLAYARAK bulur.

	Ham `text.find(">")` öznitelik DEĞERİ içindeki `>`ı etiket sonu sanıyordu ve
	`self-closing` kararı da (`text[gt - 1] == "/"`) o yanlış konuma bakıyordu.
	ÖLÇÜLDÜ (çift ve tek tırnakta aynı):

		'<Sifre>x<Child a="/>"></Child>SESSIONTOKEN_ABC999'
			→ '<Sifre>***</Child>SESSIONTOKEN_ABC999'   [SIZINTI]

	Tırnak-DIŞI `>` bulunduğunda `text[gt - 1]` ya gerçek bir `/` ya da öznitelik
	değerini kapatan tırnaktır; böylece self-closing kararı da kendiliğinden
	düzelir. Tarama tek geçişli ve monotondur (arama pencereleri ayrık) — O(n).

	Döner: `>` indeksi, `_TAG_END_TRUNCATED` ya da `_TAG_END_AMBIGUOUS`.
	"""
	index = start
	while True:
		found = _TAG_SPECIAL_RE.search(text, index)
		if found is None:
			return _TAG_END_TRUNCATED
		quote = found.group()
		if quote == ">":
			return found.start()
		close = text.find(quote, found.end())
		if close < 0:
			return _TAG_END_AMBIGUOUS
		index = close + 1


def _find_close_tag(text: str, start: int, tag: str, budget: int) -> tuple[tuple[int, int] | None, int]:
	"""`</tag>` konumunu bulur. Döner: `((kapanış başı, kapanış sonrası), harcanan bütçe)`.

	Pencere `start + budget` ile SINIRLI — ama bütçe metin uzunluğunun katıdır,
	sabit bir pencere DEĞİL (3. turdaki sızıntı tam olarak sabit 64 KiB
	penceresinden çıkmıştı). Bütçe içinde kapanış bulunamazsa çağıran
	fail-closed/özet yoluna düşer; hiçbir koşulda ham metin geçmez.

	YAPI-FARKINDA (5. tur) — ham `str.find(needle)` ÜÇ ayrı bağlamda sahte
	kapanışı GERÇEK sanıyordu ve üçü de aynı sınıfın üyesi:

		markup bölgesi   '<R><Token><!-- </Token> -->SECRET</Token></R>'
		                 '<R><Token><![CDATA[</Token>]]>SECRET</Token></R>'
		öznitelik değeri '<Sifre>x<Child a="></Sifre>">SECRET</Child>'

	Bu yüzden arama artık `find(needle)` DEĞİL, bir YAPI YÜRÜYÜŞÜDÜR: her `<`
	için sırayla (a) markup bölgesi mi — öyleyse bölgenin sonuna atla, (b) aranan
	kapanış mı — öyleyse bitir, (c) başka bir etiket mi — öyleyse ETİKETİN
	SONUNA (`_tag_end`, tırnak-farkında) atla. Öznitelik değerinin içi hiçbir
	zaman ziyaret edilmez, çünkü etiketin tamamı tek adımda geçilir.

	Kapanmamış bir bölge ya da kapanmamış bir öznitelik tırnağı "kapanışı buldum"
	iddiasını imkânsız kılar → `None` (çağıran fail-safe/özet yoluna düşer).

	DENGELİ EŞLEŞTİRME (7. tur — ölçülmüş sızıntı, 189/189 vektör):
	Altı tur boyunca yalnız yapı TANIMA katmanı (`_markup_region_end`,
	`_tag_end`) sertleştirildi; EŞLEŞTİRME katmanı hiç sınanmadı ve DERİNLİK
	SAYMIYORDU. AYNI ADLI bir TORUN sıradan etiket gibi atlanıyor, torunun
	kapanışı elemanın kapanışı sanılıyordu:

		'<LoginResponse><Kod><Kod>01</Kod>SESSIONTOKEN_ABC999</Kod></LoginResponse>'
			→ '<LoginResponse><Kod>***</Kod>SESSIONTOKEN_ABC999</Kod></LoginResponse>'

	EN AĞIR YANI fail-safe'in HİÇ TETİKLENMEMESİYDİ: girdi iyi biçimliydi
	(ElementTree ile doğrulandı), bölge çözülüyordu, `_tag_end` belirsizlik
	bildirmiyordu ve bu fonksiyon POZİTİF bir sınır döndürüyordu. Yani "ya doğru
	işle ya özete in" ilkesinin ÜÇÜNCÜ, o güne kadar belgelenmemiş çıkışıydı:
	**"yanlış anladım ama anladığımı sandım."** Denetim ölçümü:
	`DEFAULT_SENSITIVE_KEYS`'teki 63 adın 63'ünde ve torun derinliği 1/2/3'ün
	üçünde de ham sızıntı; aynı adlı torunu OLMAYAN 320 negatif kontrolde sızıntı
	YOK. Önkoşul TEK: aynı adlı torun.

	`_ancestor_boundary` bu deseni (`_open_element`/`_close_element`) ZATEN doğru
	uyguluyordu — aynı modülde iki farklı yaklaşım vardı ve düzeltme yeni bir
	kavram icat etmek yerine DOĞRU olanı eksik olan yere taşır. Burada ad TEK
	olduğu için yığın değil sayaç yeter.

	`at` MONOTON ilerler ve her adım sabit sayıda C düzeyi arama yapar; döngü
	O(n) kalır — sayaç ReDoS profilini DEĞİŞTİRMEZ (bkz.
	`TestMaskingRegressionTiming` markup varyantları).
	"""
	if budget <= 0:
		return None, 0
	needle = f"</{tag}"
	length = len(text)
	limit = min(length, start + budget)
	at = start
	#: `start`'tan sonra AÇILMIŞ ama henüz kapanmamış AYNI ADLI torun sayısı.
	depth = 0

	while at < limit:
		lt = text.find("<", at, limit)
		if lt < 0:
			break

		# Bölge kapanışı bütçe penceresinin ÖTESİNDE olabilir; onu "kapanmamış"
		# saymak gereksiz özet üretirdi. `at` pencerenin dışına çıkarsa döngü
		# koşulu zaten durdurur ve fail-safe işler.
		region = _markup_region_end(text, lt, length)
		if region is None:
			return None, limit - start
		if region != _NOT_MARKUP:
			at = region
			continue

		if text.startswith(needle, lt):
			after = lt + len(needle)
			index = after
			gap = min(length, after + _MAX_CLOSE_TAG_GAP)
			while index < gap and text[index] in " \t\r\n":
				index += 1
			if index < length and text[index] == ">":
				if depth == 0:
					return (lt, index + 1), after - start
				# AYNI ADLI TORUNUN kapanışı: elemanın sınırı DEĞİL, yalnız
				# derinliği düşürür. Aramaya buradan devam edilir.
				depth -= 1
				at = index + 1
				continue

		closing = text.startswith("</", lt)
		match = _TAG_NAME_RE.match(text, lt + 2 if closing else lt + 1)
		if match is None:
			# ULAŞILMAZ: `_markup_region_end` geçerli adı OLMAYAN her `<` dizisini
			# `None` yapar (7. tur, tek karar noktası). Yine de savunma amaçlı
			# GÜVENLİ yön seçilir — eski `at = lt + 1` "anlamadığım diziyi
			# yok say" demekti ve `</` bogus-comment belirsizliğini ham bırakıyordu.
			return None, limit - start
		gt = _tag_end(text, match.end())
		if gt < 0:
			return None, limit - start
		if not closing and match.group(0) == tag and text[gt - 1] != "/":
			# AYNI ADLI TORUN AÇILIŞI — eskiden sıradan etiket gibi atlanıyordu.
			depth += 1
		at = gt + 1

	return None, limit - start


def _open_element(stack: list[str], counts: dict[str, int], name: str) -> None:
	"""Açılış etiketini yığına iter. `counts` üyelik testini O(1) tutar."""
	stack.append(name)
	counts[name] = counts.get(name, 0) + 1


def _close_element(stack: list[str], counts: dict[str, int], name: str) -> bool:
	"""Kapanış etiketini yığında EŞLEŞTİRİR. Döner: eşleşen açılış var mıydı.

	Eşleşme varsa yığın o ada kadar boşaltılır (aradaki kapanmamış çocuklar
	hoşgörülü ayrıştırıcıda örtük olarak kapanır). Eşleşme YOKSA yığına
	DOKUNULMAZ — başıboş kapanışın derinliği bozmasına izin verilmez.

	Maliyet: her `pop` bir `append`'i tüketir, toplam O(n) amortize; üyelik
	testi sözlükten O(1) — 50 bin başıboş kapanış O(n²) üretmez.
	"""
	if not counts.get(name):
		return False
	while stack:
		top = stack.pop()
		counts[top] -= 1
		if top == name:
			break
	return True


def _ancestor_boundary(
	text: str, start: int, budget: int, ancestors: Mapping[str, int]
) -> tuple[int | None, int]:
	"""Hassas içeriğin BİTTİĞİ noktayı bulur — durma noktası ATA KAPANIŞIDIR.

	`start`'tan itibaren iyi biçimli ÇOCUK alt ağaçlar yutulur. Durma noktası,
	yığında AÇILIŞI OLMAYAN ve `ancestors` içinde ADI GEÇEN ilk kapanıştır.

	Args:
		ancestors: hassas etiketin çevresinde AÇIK olan ata adları → adet
			(`_mask_xml_elements` tutar). Ad doğrulaması bunu gerektirir.

	Döner: `(durma indeksi | None, harcanan bütçe)`. `None` üç durumda gelir ve
	üçü de "sınırı GÜVENLE bilmiyorum" demektir: (a) metnin sonuna AÇIK çocukla
	ulaşıldı (gövde kırpılmış), (b) bütçe tükendi, (c) bozuk etiket (`>` yok).
	Çağıran o durumda gövdeyi fail-safe ÖZETE indirir.

	Metnin sonuna DENGELİ ulaşmak `None` DEĞİLDİR: orada maskeleme metnin sonuna
	kadar uygulanır ve geriye ham hiçbir şey kalmaz — belirsizlik yoktur.

	DERİNLİK SAYIMI AD-KÖRDÜ (6. tur — ölçülmüş sızıntı):

		'<R><Sifre></Yanlis>SECRET</R>' → '<R><Sifre>***</Yanlis>SECRET</R>'

	`</Yanlis>` ne `<Sifre>`'nin kapanışıdır ne de bir ata; hoşgörülü bir
	ayrıştırıcı onu YOK SAYAR ve jetonu `<Sifre>`'nin İÇİNDE görür. Eski kod
	`depth 0`da gördüğü HERHANGİ bir kapanışı "ata" sayıp maskeyi orada
	kapatıyordu; denetim fuzz'ı bu TEK kök nedenden 2.534 varyant üretti.

	SEÇİLEN YOL — eşleşmeyen kapanışı YOK SAY: bu fonksiyon zaten yalnız
	`_find_close_tag` BAŞARISIZ olduğunda çalışır, yani "yapıyı tam anlayamadım"
	durumundayız ve modülün doktrini orada GÜVENLİ YÖNÜ seçmeyi söyler. En kötü
	ihtimalle maske metnin sonuna kadar uzar (belgelenmiş güvenli yön); asla
	erken kapanmaz. Alternatif "eşleşmezse `None` → özet" her başıboş kapanışta
	gövdenin TAMAMINI özete indirirdi — teşhis kaybı, aynı güvenlikle.

	Ata ADI doğrulanır: `</Root>` ancak GERÇEKTEN açık bir `<Root>` atası varsa
	durdurur. Bu, "kapanmamış `<Password>` bütün denetim izini silemez"
	güvencesini korur (ölçülü test: `injected_password_cannot_erase…`).

	MARKUP-FARKINDA (5. tur): yorum/CDATA/PI bölgeleri ve `<!` bildirimleri
	`_markup_region_end` üzerinden ele alınır.
	"""
	if budget <= 0:
		return None, 0
	length = len(text)
	stop = min(length, start + budget)
	stack: list[str] = []
	counts: dict[str, int] = {}
	at = start
	while at < stop:
		lt = text.find("<", at, stop)
		if lt < 0:
			break
		region = _markup_region_end(text, lt, length)
		if region is None:
			return None, min(stop, length) - start
		if region != _NOT_MARKUP:
			at = region
			continue
		closing = text.startswith("</", lt)
		match = _TAG_NAME_RE.match(text, lt + 2 if closing else lt + 1)
		if match is None:
			# ULAŞILMAZ (bkz. `_looks_like_tag`); savunma amaçlı GÜVENLİ yön.
			return None, min(stop, length) - start
		gt = _tag_end(text, match.end())
		if gt < 0:
			return None, min(stop, length) - start
		name = match.group(0)
		if closing:
			if not _close_element(stack, counts, name) and ancestors.get(name):
				return lt, lt - start
		elif text[gt - 1] != "/":
			_open_element(stack, counts, name)
		at = gt + 1

	if stop < length or stack:
		# Bütçe bitti ya da gövde bir elemanın ortasından kesilmiş.
		return None, stop - start
	return length, length - start


def _summarize_xml(text: str, start: int, resolved: int, keys: frozenset[str]) -> str:
	"""Sınırı çözülemeyen gövdeyi FAIL-SAFE özete indirir.

	YALNIZ `_fail_closed` ÇAĞIRIR ve yalnız korunacak ön ek BİLGİ TAŞIMIYORKEN
	(9. tur kapsam daralması + 10. turun içeriksel ölçütü). `resolved` bu yolda
	YAPISAL OLARAK 0'dır: sayaç ancak `parts`'a bir maske yazılırken artar ve
	`parts` doluysa ön ek `***` içerir, yani BİLGİ TAŞIR. `start` görünmez bir
	ön ekten sonrasını gösterebilir (0 olmak zorunda değil). İmza genel kalır:
	değişmez koşul çağıranda ifade edilir, burada varsayılmaz.

	Args:
		text: Gövdenin tamamı (özet gövdenin TAMAMINI değiştirir).
		start: Sınırı çözülemeyen hassas etiketin başlangıcı.
		resolved: Bu noktadan ÖNCE sınırı çözülüp maskelenmiş hassas etiket sayısı.
		keys: Hassas anahtar kümesi.
	"""
	fields = resolved + _count_sensitive_tags(text, start, keys)
	return XML_BOUNDARY_UNRESOLVED.format(len(text.encode("utf-8", errors="replace")), fields)


def _count_sensitive_tags(text: str, start: int, keys: frozenset[str]) -> int:
	"""`start`'tan itibaren hassas AÇILIŞ etiketlerini sayar (tek doğrusal geçiş).

	Kapanış araması YAPILMAZ; maliyet bir taramayla sınırlıdır ve ayrıca
	`_MIN_TAG_SCAN_BUDGET` karakterle kırpılır — özet üretmenin kendisi bir
	maliyet vektörü olmamalı.

	MARKUP-FARKINDA (5. tur): yorum/CDATA/PI içindeki `<Sifre>` bir eleman değil
	karakter verisidir; sayıma girerse özetin alan sayısı şişer.

	ÇÖZÜLEMEYEN BÖLGEDE SAYIM DURMAZ — 10. TUR, ÖLÇÜLMÜŞ YANLIŞ BEYAN:
		Sayım `_markup_region_end` `None` döndüğü İLK noktada `break` ediyordu.
		`_fail_closed` özeti YALNIZ `lt == 0`da ürettiği için o nokta HER ZAMAN
		indeks 0'dır — yani özetin taşıdığı TEK teşhis bilgisi BASKIN DALDA
		yapısal olarak yanlıştı:

			mask_payload('<!DOCTYPE html>\\n<html><body>'
			             '<Sifre>SESSIONTOKEN_ABC999</Sifre><ApiKey>K2</ApiKey>'
			             '</body></html>')
				→ '<XML gövdesi, 95 bayt, 0 hassas alan — sınır çözülemedi>'
				  (gövdede 2 hassas eleman VAR)

		8. tur "mekanizma hiçbir şey saklamadığını İLAN EDEREK teşhisi yok
		ediyor" ifadesini kabul edilemez ilan etmişti; aynı ifade burada
		`_count_sensitive_tags` üzerinden geri gelmişti.

		Çözülemeyen bölge artık ATLANARAK (`at = lt + 1`) sayıma devam edilir.
		Sayım MASKELEME KARARINI ETKİLEMEZ — özet zaten üretiliyor, bu sayı
		yalnız raporlanır — bu yüzden çözülemeyen bir bölgenin İÇİNDEKİ
		`<Sifre>` de sayılabilir. FAZLA SAYIM GÜVENLİDİR: operatöre "burada
		hassas alan vardı" der, "yoktu" demez.
	"""
	count = 0
	at = start
	length = len(text)
	stop = min(length, start + _MIN_TAG_SCAN_BUDGET)
	while at < stop:
		lt = text.find("<", at, stop)
		if lt < 0:
			break
		region = _markup_region_end(text, lt, length)
		if region is None:
			# Bölge ÇÖZÜLEMEDİ → ATLA, sayımı bitirme (yukarıdaki gerekçe).
			at = lt + 1
			continue
		if region != _NOT_MARKUP:
			at = region
			continue
		# KAPANIŞ ETİKETİ AYRI ELE ALINIR: `_looks_like_tag` artık `</Ad>`ı da
		# GEÇERLİ sayıyor, bu yüzden buradaki eşleşme `lt + 1`de denenirse `/`de
		# düşer ve sayım ilk kapanışta dururdu. Sayıma yalnız AÇILIŞ girer.
		closing = text.startswith("</", lt)
		match = _TAG_NAME_RE.match(text, lt + 2 if closing else lt + 1)
		if match is None:
			# ULAŞILMAZ (bkz. `_looks_like_tag`); sayım güvenle durur.
			break
		if not closing and _is_sensitive_normalized(_normalize_key(match.group(0)), keys):
			count += 1
		at = match.end()
	return count


# ---------------------------------------------------------------------------
# `key=value` / `key: value` / `"key": value` — İNDEKS TABANLI değer taraması
# ---------------------------------------------------------------------------


def _mask_delimited_pairs(text: str, keys: frozenset[str]) -> str:
	"""Ayraçla ayrılmış anahtar/değer çiftlerini maskeler.

	KAPSANAN BİÇİMLER (hepsi ölçülerek eklendi — öncekiler HAM sızıyordu):

		Authorization: Basic SECRET     ham HTTP başlık dökümü
		X-Api-Key: SECRET               aynı
		Cookie: SESSID=SECRET           aynı
		password: SECRET                YAML
		-H 'X-Api-Key: SECRET'          curl komut satırı
		data={'sifre': 'SECRET'}        Python repr / `frappe.get_traceback()`
		"api_secret": "SECRET"          JSON parçası (ayrıştırılamayan metinde)
		client_secret=SECRET            querystring / form-encoded
		password="SECRET"               XML özniteliği (uzunluk sınırı YOK)
		auth=('user','SECRET')          Python tuple değeri

	**Python repr biçimi özellikle kritiktir:** `frappe.get_traceback()` ve
	`repr(exception)` çıktısı TAM OLARAK bu biçimdedir ve doğrudan
	`error_message`'a akar.

	Anahtar konumu üst sınırlı bir regex ile bulunur (geri izlemesiz); DEĞER
	indeksle taranır, çünkü değere üst sınır koymak `<Token>` + 5000 karakter
	vakasındaki gibi FAIL-OPEN üretir.
	"""
	parts: list[str] = []
	pos = 0

	for match in _PAIR_KEY_RE.finditer(text):
		if match.start() < pos:
			continue
		if not _is_sensitive_normalized(_normalize_key(match.group("key")), keys):
			continue

		scanned = _scan_value(text, match)
		if scanned is None:
			continue

		value_start, end, replacement = scanned
		# `text[pos:value_start]` ayraç SONRASI boşluğu da taşır: `Authorization: ***`
		# okunabilirliği korunur, `Authorization:***` gibi biçim bozulmaz.
		parts.append(text[pos:value_start])
		parts.append(replacement)
		pos = end

	parts.append(text[pos:])
	return "".join(parts)


def _scan_value(text: str, match: re.Match) -> tuple[int, int, str] | None:
	"""Ayraçtan sonraki DEĞERİ sınırlar: `(başlangıç, bitiş, yerine yazılacak)`.

	`None` = maskelenecek değer YOK (değer GERÇEKTEN sıfır uzunlukta). `None`
	"sınırı bulamadım" ANLAMINA GELMEZ.

	SIFIR UZUNLUKLU DEĞER MASKELENMEZ: eski `_KV_RE` `{0,4096}` ile boş değer
	eşleştiriyordu ve `'sifre=&b=2'` → `'sifre=***&b=2'` üretiyordu — çıktı
	MASKELENMİŞ GÖRÜNÜYOR ama maskelenmiş bir şey YOKTUR. Bu YANILTICI çıktı,
	hiç maskelememekten daha kötüdür. Kural bugün YALNIZ ayraçtan hemen sonra
	BOŞLUK OLMAYAN bir sonlandırıcı (`&`, `;`, `,`, `)`, `]`, `}`, `<`, `>`)
	geldiğinde işler — yani değerin gerçekten boş olduğu ölçülebildiğinde.

	AYRAÇTAN SONRAKİ BOŞLUK PENCERESİ — 10. TUR, ÖLÇÜLMÜŞ FAIL-OPEN:
		Pencere yalnız `' \\t'` atlıyordu ve 8 karakterle sınırlıydı (sınır
		`_find_close_tag` ile PAYLAŞILAN bir sabitti — bugün `_MAX_CLOSE_TAG_GAP`
		adıyla YALNIZ orada, yönü GÜVENLİ olan yerde durur).
		Ayraçtan sonra SATIR SONU (ya da 8'den çok boşluk) gelince değerin
		başlangıcı bulunamıyor, fonksiyon `None` dönüyor ve `_mask_delimited_pairs`
		çifti ATLIYORDU — yani HİÇ MASKELEME YAPILMIYORDU (fail-OPEN). Ölçüm
		(`mask_payload`; hepsi ElementTree'nin kabul ettiği İYİ BİÇİMLİ XML,
		jeton bir taşıyıcı YANITINDAKİ oturum jetonu yerine geçer):

			'<Kayit sifre=\\n"SESSIONTOKEN_ABC999">x</Kayit>'         → DEĞİŞMEDEN
			'<Kayit\\n  sifre =\\n  "SESSIONTOKEN_ABC999"\\n .../>'      → DEĞİŞMEDEN
			'<Kayit sifre=          "SESSIONTOKEN_ABC999"/>'         → DEĞİŞMEDEN
			"<Kayit api_key=\\n'SESSIONTOKEN_ABC999'/>"               → DEĞİŞMEDEN
			'<Kayit sifre=\\nSESSIONTOKEN_ABC999'  (kırpılmış)         → DEĞİŞMEDEN
			'Authorization:\\r\\n Basic SESSIONTOKEN_ABC999' (katlanmış) → DEĞİŞMEDEN

		116 yönlendirilmiş vektörün 116'sı HAM sızıyordu (fix sonrası 0).

		ERİŞİLEBİLİR, KIRPMA GEREKTİRMEZ: XML 1.0 `Eq ::= S? '=' S?` gereği `=`
		etrafında satır sonu MEŞRUDUR ve biçimlendirilmiş SOAP yanıtlarında
		(.NET/Java, öznitelik-başına-satır düzeni) rutindir. Değer taşıyıcının
		YANITINDAKİ jetondur → `secret_values`'ta YOKTUR → değer-tabanlı birincil
		katman bu sınıfta YARDIM EDEMEZ; anahtar-tabanlı katman TEK savunmadır.

		KÖK NEDEN ASİMETRİYDİ: 9. turda eklenen `_mask_tag_attributes` hassas
		ELEMANDA `' \\t\\r\\n'` atlar ve doğru maskeler; bu fonksiyon hassas
		ÖZNİTELİKTE atlamıyordu. Üstelik `_mask_tag_attributes` docstring'i hassas
		OLMAYAN elemanın özniteliklerini AÇIKÇA buraya devrediyordu — devredilen
		katman işi yapmıyordu. Pencere artık `' \\t\\r\\n'` atlar ve ÜST SINIRSIZDIR
		(atlanan karakterlerin hepsi boşluktur, geri izleme yok, maliyet O(n)).

		AŞIRI MASKELEME BEDELİ (ölçüldü, kabul edildi ve SINIRLI): DEĞERİ BOŞ
		bırakılmış bir anahtardan sonra gelen satır artık değer sayılır. Ölçüm:

			'Content-Type: …\\nAuthorization:\\nX-Takip: TR-9\\nDurum: OK'
				→ '…\\nAuthorization:\\n***\\nDurum: OK'   (BİR satır gitti)

		Kayıp TEK SATIRLADIR — sonlandırıcı (`_TERM_LINE_RE` / `_TERM_JSON_RE` /
		`_TERM_EQ_RE`) hemen sonraki satır sonunda durur, gövdenin kuyruğu YAŞAR.
		Yön FAIL-CLOSED'dır ve modülün "yanlış pozitif ödünleşmesi" doktrinine
		uygundur: bir teşhis satırını kaybetmenin maliyeti, biçimlendirilmiş HER
		SOAP yanıtında jetonu ham yazmanın maliyetinden küçüktür. Değeri DOLU olan
		başlıklarda hiçbir şey değişmez (`'Authorization: Basic X\\nX-Takip: TR-9'`
		→ kuyruk aynen korunur).

	AYRACIN ARDINDA DEĞER BAŞLANGICI YOKSA → FAIL-CLOSED:
		Boşluk atlandıktan sonra metin bittiyse (`'sifre='`, `'sifre:   '`)
		"hiç maskeleme" YANLIŞ cevaptır: bu şekil `log.py::MAX_BODY_BYTES`
		kırpmasının tam ayraçta kesilmiş hâlidir ve değer GERÇEKTE oradaydı.
		Ayraçtan metnin sonuna kadar maskelenir (`'sifre=***'`). Aynı fonksiyonun
		"kapanmamış tırnak → fail-CLOSED, boşlukla ayrılmış değer → fail-OPEN"
		çelişkisi böylece giderilir — İKİ DAL TEK DOKTRİNE bağlıdır.

	SINIR BULUNAMAZSA HAM BIRAKILMAZ — 10. TUR, ÖLÇÜLMÜŞ FAIL-OPEN:
		Kapanış tırnağı ya da kapanış parantezi bulunamadığında bu fonksiyon
		`None` dönüyor, `_mask_delimited_pairs` çifti ATLIYOR ve DEĞER HİÇ
		MASKELENMİYORDU. Anahtar DOĞRU tanınmıştı; kaybedilen tek şey sınırdı.
		Ölçüm (`mask_payload`, `SESSIONTOKEN_ABC999` bir taşıyıcı YANITINDAKİ
		oturum jetonu yerine geçiyor — değeri BİLİNMEZ, yani değer-tabanlı
		birincil katman bu sınıfta YARDIM EDEMEZ):

			'{"a":1,"sifre":"SESSIONTOKEN_ABC999'   → DEĞİŞMEDEN  (SIZINTI)
			'sifre="SESSIONTOKEN_ABC999'            → DEĞİŞMEDEN  (SIZINTI)
			"sifre='SESSIONTOKEN_ABC999"            → DEĞİŞMEDEN  (SIZINTI)
			'{"api_key":"SESSIONTOKEN_ABC999'       → DEĞİŞMEDEN  (SIZINTI)
			"{'sifre': 'SESSIONTOKEN_ABC999"        → DEĞİŞMEDEN  (SIZINTI)
			"auth=('user','SESSIONTOKEN_ABC999"     → DEĞİŞMEDEN  (SIZINTI)

		ERİŞİLEBİLİRLİK ÖLÇÜLDÜ: `log.py::MAX_BODY_BYTES` (64 KiB) kırpması
		OTOMATİKTİR, gövdenin SONUNDAN keser ve kesim bir değerin ortasına
		düştüğünde TAM OLARAK bu şekli üretir. 301 kesim noktalı süpürmede
		JSON gövdenin 4'ü, Python-repr gövdenin 4'ü HAM sızıyordu (XML/CDATA/
		HTTP-başlık gövdelerinde 0 — sorun tırnak/parantez sınırına özgü).
		Kırpma bilgisi ARTIK gövdeye eklenmez, `_truncated` ZARF alanına yazılır
		(bkz. `log.py::_body_envelope`), yani kırpılmış gövde tam kesim
		noktasında BİTER: "metnin sonuna kadar maskele" o sınıfta HİÇBİR teşhis
		alanı kaybettirmez.

		TIRNAKSIZ DEĞER ZATEN FAIL-CLOSED'DI (ölçüldü): sonlandırıcı
		bulunamayınca `end = length` olur ve değer sonuna kadar maskelenir
		(`'sifre=SESSIONTOKEN_ABC999'` → `'sifre=***'`). Boşluk YALNIZ tırnaklı
		ve parantezli şekillerdeydi; bu tur onları tırnaksız kardeşleriyle
		SİMETRİK hâle getirir.

	SEÇİLEN SINIR — METNİN SONU, "SATIR SONU" DEĞİL (takas ÖLÇÜLDÜ):
		Ara seçenek olarak "kapanmamış tırnağı SATIR SONUNA kadar maskele"
		denendi; çok satırlı bir dökümde sonraki satırların teşhisini korurdu.
		REDDEDİLDİ, çünkü ARTIK SIZINTI bırakıyor: `'{"sifre":"AAA\\nBBB'`
		girdisinde `BBB` HAM kalır — kapanmamış bir tırnağın içinde ham satır
		sonu bulunması "değerin bittiği" ANLAMINA GELMEZ (XML öznitelik değeri
		ve YAML katlanmış skaler ham satır sonu taşıyabilir). Sınır
		BİLİNEMİYORSA tek dürüst cevap metnin sonudur — bu, XML tarafının
		`_ancestor_boundary`/`_fail_closed` doktriniyle (bkz. modül docstring'i,
		XML SINIRI (a)/(b)) AYNI karardır.

		AŞIRI MASKELEME BEDELİ (ölçüldü, kabul edildi): kapanmamış tırnak
		metnin ORTASINDAYSA kuyruktaki MEŞRU teşhis alanları da gider —
		`'sifre="TOKEN, takip=TR-123456, durum=OK'` → `'sifre="***'`. Eylem
		9. turdaki gibi YERELDİR: çözülemeyen noktadan ÖNCESİ (anahtar adı ve
		tüm gövde ön eki) OLDUĞU GİBİ korunur, yalnız değerin başladığı yerden
		sonrası gider. KAPANMIŞ değerlerde davranış DEĞİŞMEZ — bu dal yalnız
		`_find_close_quote` `None` ya da `_match_bracket` `_BRACKET_NO_CLOSE`
		döndüğünde işler; kural kapanmış değerlere sızsaydı her gövdenin kuyruğu
		yok olurdu. PARANTEZLİ değerde BÜTÇE TÜKENMESİ bu daldan AYRIDIR
		(`_BRACKET_BUDGET_EXHAUSTED`): orada kapanış VARDIR, kuyruk DOLUDUR ve
		maske bütçe sonunda BİTER — ölçümü `_match_bracket` docstring'inde.

		AÇILIŞ TIRNAĞI KORUNUR, KAPANIŞ YAZILMAZ (`sifre="***`): kapanış
		tırnağı da yazmak "değer burada bitti" diye YANLIŞ bir iddia kurardı.
		Bayt sayısı BİLEREK yazılmaz — yutulan aralık sırrın KENDİSİYLE başlar,
		sayı vermek `mask_value`'nun yasakladığı uzunluk ipucunu sızdırırdı.
	"""
	length = len(text)
	index = match.end()
	# `_mask_tag_attributes` ile SİMETRİK: satır sonu da atlanır, ÜST SINIR YOK.
	while index < length and text[index] in " \t\r\n":
		index += 1
	if index >= length:
		# Ayraçtan sonra yalnız boşluk kaldı → değer kırpmayla gitmiş olabilir.
		# FAIL-CLOSED: ayraçtan metnin sonuna kadar maskele.
		return match.end(), length, MASK

	key_quote = match.group("q")
	char = text[index]

	if char in "\"'":
		close = _find_close_quote(text, index)
		if close is None:
			return index, length, f"{char}{MASK}"
		return index, close + 1, f"{char}{MASK}{char}"

	if char in "([{":
		end = _match_bracket(text, index)
		if end == _BRACKET_NO_CLOSE:
			end = length
		elif end == _BRACKET_BUDGET_EXHAUSTED:
			# Kuyruk VAR ve DOLU: maske BÜTÇE SONUNDA biter, tarama devam eder.
			end = min(length, index + _MAX_BRACKET_SCAN)
		return index, end, f'"{MASK}"' if key_quote else MASK

	terminator = _terminator_for(match, text)
	found = terminator.search(text, index)
	end = found.start() if found else length
	if end <= index:
		# Değer sıfır uzunlukta — yanıltıcı `***` YAZMA.
		return None
	return index, end, f'"{MASK}"' if (key_quote and match.group("sep") == ":") else MASK


def _terminator_for(match: re.Match, text: str) -> re.Pattern:
	"""Değerin nerede bittiğini belirleyen karakter sınıfını seçer.

	* `key=value` → querystring/form sınırları (`&`, `;`, `,`, boşluk, tırnak,
	  parantez, `<`/`>`); eski `_KV_RE` davranışıyla uyumlu ama tırnak ve
	  parantez eklenmiş (bkz. `auth=('user','SECRET')`).
	* `"key": value` → JSON sınırları (`,`, `}`, `]`, satır sonu). Anahtar
	  tırnaklıysa değer tırnaksız bile olsa `"***"` yazılır ki dış JSON
	  ayrıştırılabilir kalsın.
	* `key: value` (tırnaksız anahtar) → SATIR SONUNA kadar. Ham HTTP başlığı ve
	  YAML böyle: `Authorization: Basic <base64>` içinde virgül de boşluk da
	  meşru değerdir. Anahtarı saran bir tırnak varsa (`-H 'X-Api-Key: ...'`)
	  o tırnak da sonlandırıcıdır.
	"""
	if match.group("sep") == "=":
		return _TERM_EQ_RE
	if match.group("q"):
		return _TERM_JSON_RE

	start = match.start()
	wrapper = text[start - 1] if start else ""
	if wrapper == "'":
		return _TERM_LINE_SQ_RE
	if wrapper == '"':
		return _TERM_LINE_DQ_RE
	return _TERM_LINE_RE


def _find_close_quote(text: str, start: int) -> int | None:
	"""Kapanış tırnağını bulur (`\\"` kaçışı atlanır). Üst sınır YOK — bilinçli.

	JWT/SAML gibi 4 KB'ı aşan öznitelik değerleri üst sınır yüzünden HİÇ
	maskelenmiyordu; `str.find` doğrusal olduğu için sınır koymaya gerek yok.

	`None` = "kapanış YOK". Çağıran bunu FAIL-CLOSED yorumlar (değeri metnin
	sonuna kadar maskeler, bkz. `_scan_value`). Eskiden burada `dead_quotes`
	adlı bir küme vardı: kapanışsız bir tırnak karakteri bir kez işaretlenir ve
	AYNI karakterle başlayan sonraki değerler HİÇ TARANMAZDI. Amaç O(n²)
	korumasıydı ama sonucu FAIL-OPEN'ı YAYMAKTI. Fail-closed dal aynı korumayı
	daha sıkı sağlar: değer metnin sonuna kadar tüketildiği için `pos` metnin
	sonuna atlar ve kalan TÜM eşleşmeler `match.start() < pos` ile zaten elenir —
	metin başına EN FAZLA BİR kapanışsız-tırnak taraması yapılır.
	"""
	quote_char = text[start]
	at = start + 1
	while True:
		at = text.find(quote_char, at)
		if at < 0:
			return None
		if quote_char == '"' and _is_escaped(text, at):
			at += 1
			continue
		return at


def _is_escaped(text: str, index: int) -> bool:
	"""`\\"` mı yoksa `\\\\"` mı? Ters bölü sayısı tek ise kaçış vardır."""
	backslashes = 0
	cursor = index - 1
	while cursor >= 0 and text[cursor] == "\\":
		backslashes += 1
		cursor -= 1
	return backslashes % 2 == 1


def _match_bracket(text: str, start: int) -> int:
	"""Dengeli parantez/köşeli/süslü kapanışının BİR SONRAKİ indeksini döndürür.

	Döner:
		`>= 0`: dengeli kapanıştan SONRAKİ ilk indeks.
		`_BRACKET_NO_CLOSE`: kapanış metinde HİÇ YOK (64 KiB kırpmasının kanonik
			sonucu). Kuyruk zaten BOŞTUR — çağıran metnin sonuna kadar maskeler.
		`_BRACKET_BUDGET_EXHAUSTED`: kapanış VAR ama `_MAX_BRACKET_SCAN`
			bütçesinin ÖTESİNDE. Kuyruk VAR ve DOLU — çağıran maskeyi BÜTÇE
			SONUNDA bitirir ve taramaya devam eder.

	İKİ ANLAM 10. TURDA AYRILDI — ÖLÇÜLMÜŞ TEŞHİS KAYBI:
		Fonksiyon eskiden ikisine de `None` diyordu ve `_scan_value` ikisini de
		"metnin sonuna kadar maskele" diye yorumluyordu. Bütçe dalında bu SAF
		teşhis kaybıdır: kapanıştan sonraki her şey kuyruktadır ve YAŞIYORDUR.
		Ölçüm (düz METİN yolu — `error_message` bu yoldan geçer):

			'Kargo hatasi: auth=(' + 'x'*1000 + ')' + KUYRUK
				girdi 1078 → çıktı   79   kuyruk sağlam: True   (bütçe İÇİNDE)
			'Kargo hatasi: auth=(' + 'x'*5000 + ')' + KUYRUK
				girdi 5078 → çıktı   22   kuyruk sağlam: FALSE  (bütçe AŞILDI)

		KUYRUK = ' | takip=TR-123456 | sube=SISLI | durum=Teslim | http=200';
		ikinci satırda takip/şube/durum/http bilgisinin TAMAMI siliniyordu.

	SIZINTI AÇMAZ: sırrın durduğu ilk `_MAX_BRACKET_SCAN` karakter yine
	maskelenir. Bütçenin ÖTESİNDEKİ iç içe hassas anahtarlar eski davranışta
	tamamen atlanıyordu (metin sonuna kadar tek maske); bugün normal yoldan
	taranmaya devam eder — yön hem teşhis hem güvenlik açısından İYİLEŞİR.
	"""
	pairs = {"(": ")", "[": "]", "{": "}"}
	closing = pairs[text[start]]
	opening = text[start]
	depth = 0
	length = len(text)
	stop = min(length, start + _MAX_BRACKET_SCAN)
	for index in range(start, stop):
		char = text[index]
		if char == opening:
			depth += 1
		elif char == closing:
			depth -= 1
			if depth == 0:
				return index + 1
	return _BRACKET_NO_CLOSE if stop == length else _BRACKET_BUDGET_EXHAUSTED
