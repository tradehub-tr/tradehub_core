"""Zararlı içerik taraması ve karantina — pipeline adım 3 (TUR-125).

`docs/MEDYA-ISLEME-PIPELINE.md` sırayı şöyle tanımlıyor: doğrulama (adım 1) →
içerik-hash'li kayıt (adım 2) → **AV tarama (adım 3)** → EXIF temizleme →
optimize → türev. Adım 1 ve 2 çalışıyordu, 3 boştu; bu modül onu doldurur.

Ne YAPMAZ
---------
Uzantı/MIME doğrulaması burada YOKTUR. O iş `media/upload_policy.py` içinde
bitmiş durumda (yasak uzantı listesi, allow-list, magic-byte sniff, tarayıcıda
çalışabilen içerik reddi) ve `utils/security.reject_unsafe_files` kancasıyla
BÜTÜN yükleme yollarını kapsıyor. Buraya ikinci bir kopya yazmak, zamanla
ayrışan iki liste demekti — `is_denied_extension`'ın tek kaynak olarak
durmasının gerekçesiyle aynı.

Bu modülün cevapladığı soru farklı: **içerik politikadan geçti, peki zararlı
mı?** Politika biçime bakar (bu bir JPEG mi, içi HTML mi), tarama imzaya bakar
(bu JPEG bilinen bir zararlıyı taşıyor mu).

Neden kuyrukta
--------------
Tarama disk okuması + imza eşleştirmesi; büyük dosyada saniyeler sürer. İstek
içinde senkron çalıştırmak yükleme yanıtını bekletirdi (checklists.md §2,
kural 9). `File.after_insert` kancası işi `default` kuyruğa devreder.

Durum modeli
------------
    pending    Kuyruğa girdi / taranıyor. Sonuç henüz yok.
    clean      Tarandı, imza bulunamadı.
    infected   Zararlı bulundu → dosya KARANTİNAYA taşındı, artık servis edilmiyor.
    failed     Tarayıcı üç denemede de sonuç veremedi (dead-letter).

Bu alan yaşam döngüsü durumundan (`th_media_state`: Active/Archived/Trashed/
Deleted) AYRIDIR ve `th_media_video_status` ile aynı katmandadır: ikisi de iş
durumu, dosyanın nerede durduğu değil. Karantinayı `th_media_state`'e bir değer
olarak eklemek `ALLOWED_TRANSITIONS` sözlüğünü her iş durumuyla çarpardı.

Karantina neden FİZİKSEL taşıma
-------------------------------
`public/files/` altındaki dosyayı nginx DOĞRUDAN servis ediyor — Python hiç
devreye girmiyor. Yani bir bayrak alanı ("bu dosya zararlı") dosyayı erişime
kapatmaz; kapatmanın tek yolu dosyayı o kökün DIŞINA almaktır. `media/trash.py`
çöp için aynı şeyi yapıyor, karantina da aynı deseni izler:

    public/files/<yol>          →  private/media_quarantine/<yol>
    private/files/<yol>         →  private/media_quarantine/private/<yol>

Bekletme — taranmamış dosya hiç servis edilmez
----------------------------------------------
Dosya, kaydı açılır açılmaz `private/media_scan_hold/` altına alınır ve ancak
tarama TEMİZ dönerse canlı ağaca konur. Böylece "insert ile tarama arasındaki
saniyeler" penceresi de kapanır: taranmamış hiçbir dosya bir an bile servis
edilmez.

`file_url` DEĞİŞMEZ — yalnız dosyanın fiziksel yeri değişir. İçerik-adresli
adlandırmanın (`naming.py`) sözleşmesi bu yüzden korunuyor: adres yükleme anında
kesinleşir, dosya sonradan yerine konur. Alternatif (önce private'a yükleyip
temiz çıkınca public'e taşımak) adresi yükleme anında belirsiz bırakırdı.

Bekletme `hold_until_clean` politikasına bağlı ve varsayılanı "auto" = tarama
açıksa beklet. Tarayıcı YOKKEN bekletmek her yüklemeyi sonsuza kadar görünmez
yapardı. Aynı gerekçeyle, tarama üç denemede de sonuç veremezse (dead-letter)
fail-open modunda dosya bekletmeden ÇIKARILIR — "açık bırakıyoruz" deyip sessizce
kapalı tutmak politikanın tersini yapmak olurdu.

Bekletme ile karantina AYRI kökler: karantina bir KARAR ("bu dosya zararlı"),
bekletme bir ARA DURUM ("henüz bilmiyoruz"). Aynı dizine koymak, operatörün
karantina listesinde henüz taranmamış olağan dosyaları zararlı sanmasına yol
açardı.

Tarayıcı yoksa ne olur
----------------------
ClamAV taban imajda YOK — kurulum ayrı bir adım (bkz. `docs/MEDYA-AV-TARAMA.md`
§6). Bu yüzden politika kurulumdan bağımsız çalışır. Varsayılan "aç" (fail-open):
tarama yapılamayan dosya `failed` damgalanır, panelde görünür, ama servis
edilmeye devam eder. Alternatifi (fail-closed) tarayıcı kurulana kadar HER
yüklemeyi karantinaya atardı — güvenlik adına siteyi kullanılamaz hâle getirmek.
Sıkı davranış `site_config.json` → `media_av_fail_closed: 1` ile açılır; o
zaman `failed` dosyalar da karantinaya taşınır.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import frappe
from frappe.utils import now_datetime

from tradehub_core.media import audit, jobs

SCAN_PENDING: str = "pending"
SCAN_CLEAN: str = "clean"
SCAN_INFECTED: str = "infected"
SCAN_FAILED: str = "failed"

STORED_SCAN_STATUSES: tuple[str, ...] = (SCAN_PENDING, SCAN_CLEAN, SCAN_INFECTED, SCAN_FAILED)

# Karantina kökü — `private/` altında, yani nginx'in doğrudan servis ettiği
# ağacın dışında. `media_trash` ile kardeş; ikisi de "dosya duruyor ama
# erişilemiyor" durumunu temsil ediyor.
QUARANTINE_DIRNAME: str = "media_quarantine"

# Tarama bitene kadar dosyanın bekletildiği kök. Karantinadan AYRI: karantina
# bir KARAR ("bu dosya zararlı"), bekletme bir ARA DURUM ("henüz bilmiyoruz").
# İkisini aynı dizine koymak, operatörün karantina listesine bakıp henüz
# taranmamış olağan dosyaları zararlı sanmasına yol açardı.
SCAN_HOLD_DIRNAME: str = "media_scan_hold"

# Toplam deneme hakkı. Medyadaki bütün kuyruk işleri aynı politikayı kullanır.
MAX_SCAN_ATTEMPTS: int = jobs.MAX_ATTEMPTS

# Kuyruk (RQ) zaman aşımı. Tarayıcının kendi zaman aşımından BÜYÜK olmalı ki
# hata kendi katmanında yakalansın, RQ'nun sert kill'i devreye girmesin —
# `transcode.py`'deki merdivenle aynı gerekçe:
#
#     clamdscan 120 sn  <  kuyruk 300 sn  <  kayıp eşiği 2700 sn
#
# Kayıp eşiği ortak sabit (`jobs.STALE_AFTER_SECONDS`) ve transcode'un uzun
# kuyruğuna göre ayarlı; tarama için fazlasıyla geniş. Bilinçli: iki iş için iki
# ayrı eşik tutmak, süpürücünün hangi işi hangi eşikle değerlendirdiği sorusunu
# her okuyana yeniden sordururdu. Sonucu yalnız "bırakılmış tarama geç fark
# edilir" — veri kaybı değil, gecikme.
QUEUE_TIMEOUT_SECONDS: int = 300
_SCAN_TIMEOUT_SECONDS: int = 120

# Sağlık yoklaması (F-28). Kısa: yoklamanın kendisi dosya yüklemeyi bekletmemeli.
_HEALTH_PROBE_TIMEOUT_SECONDS: int = 5
_HEALTH_TTL_SECONDS: int = 60
_HEALTH_CACHE_KEY: str = "media_av_scanner_health"

# Süreç içi memo — Redis katmanının ÜSTÜNDE, onun yerine değil.
#
# İki sebep: (1) `policy()` her `File` insert'inde ve her tarama adımında
# çağrılıyor, her seferinde Redis'e gitmek gereksiz; (2) Redis katmanı tek
# başına güvenilir değil — test koşusunda yazılan değerin aynı test içinde geri
# okunamadığı ölçüldü (2026-08-28) ve Redis hiç erişilemezse yoklama her
# çağrıda tekrarlanır, yani asılı daemon senaryosunda 5 sn'lik gecikme her
# yüklemeye binerdi. Memo süreç ömrüyle sınırlı ve aynı TTL'e tabi.
_health_memo: dict[str, float | dict] = {}

# Tercih sırası: `clamdscan` arka plandaki daemon'a bağlanır (imza veritabanını
# bir kez yükler, taşımalı çağrı milisaniyeler sürer). `clamscan` her çağrıda
# ~200 MB imzayı baştan okur — yedek yol olarak duruyor, tercih değil.
_SCANNER_CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
	# `--fdpass`: dosyayı açıp tanımlayıcıyı daemon'a geçirir. Olmadan clamd
	# kendi kullanıcısıyla açmaya çalışır ve site dosyalarını okuyamaz.
	("clamdscan", ("--no-summary", "--fdpass")),
	("clamscan", ("--no-summary", "--infected")),
)

# Sağlık yoklamasının argümanları tarayıcıya göre AYRI. Ölçüldü (2026-09-12,
# container, daemon kapalıyken): `clamdscan --version` stderr'e "Could not
# connect to clamd" basıyor ama rc=0 döndürüyor — istemci kendi sürümünü
# daemon'a sormadan yazıyor. `--ping 1` ise daemon'a gerçekten gidiyor:
# PONG → rc=0, ulaşılamıyorsa rc=21. `clamscan` daemon'sız çalışır ve `--ping`
# seçeneğini tanımaz; onun için `--version` yeterli.
_HEALTH_PROBE_ARGS: dict[str, tuple[str, ...]] = {
	"clamdscan": ("--ping", "1"),
	"clamscan": ("--version",),
}

# ClamAV çıkış kodları: 0 temiz, 1 zararlı bulundu, 2+ hata.
_EXIT_CLEAN: int = 0
_EXIT_INFECTED: int = 1


# ── Politika ────────────────────────────────────────────────────────────


def scanner_command() -> tuple[str, ...] | None:
	"""Kurulu tarayıcı komutu — YALNIZ dosya varlığına bakar, çalıştığına değil.

	Sağlık sorusunun cevabı `healthy_scanner_command()`'ta. İkisi ayrı tutuluyor
	çünkü "kurulu mu" bilgisi tanı ekranlarında da lazım ve orada bir alt süreç
	açmanın anlamı yok.
	"""
	for isim, bayraklar in _SCANNER_CANDIDATES:
		yol = shutil.which(isim)
		if yol:
			return (yol, *bayraklar)
	return None


def _saglik_yoklamasi(yol: str) -> tuple[bool, str]:
	"""Tarayıcı GERÇEKTEN cevap veriyor mu — `_HEALTH_PROBE_ARGS` ile yoklanır.

	`clamdscan` bir istemci; asıl iş `clamd` daemon'ında. Daemon ölüyse ya da
	asılıysa binary yerinde durur. İki ölçüm bu fonksiyonun biçimini belirledi:

	* 2026-08-28: daemon SIGSTOP ile dondurulduğunda istemci hata vermiyor,
	  **donuyor** (`timeout` ile rc=124). Yoklamanın kendi zaman aşımı şart.
	* 2026-09-12: daemon hiç yokken `clamdscan --version` rc=0 döndürüyor —
	  yoklama ölü daemon'ı GÖREMİYORDU, F-28'in yazılma sebebi olan durumu
	  kaçırıyordu. Daemon'a gerçekten giden tek şey `--ping`.
	"""
	argumanlar = _HEALTH_PROBE_ARGS.get(os.path.basename(yol), ("--version",))
	try:
		sonuc = subprocess.run(
			[yol, *argumanlar],
			capture_output=True,
			timeout=_HEALTH_PROBE_TIMEOUT_SECONDS,
			check=False,
		)
	except subprocess.TimeoutExpired:
		return False, f"{_HEALTH_PROBE_TIMEOUT_SECONDS} sn içinde yanıt vermedi (daemon asılı olabilir)"
	except Exception as exc:  # noqa: BLE001 - yoklama hiçbir sebeple akışı kesmemeli
		return False, f"{type(exc).__name__}: {exc}"[:160]
	if sonuc.returncode != 0:
		detay = (sonuc.stderr or sonuc.stdout or b"").decode("utf-8", "replace").strip()
		return False, detay[:160] or f"çıkış kodu {sonuc.returncode}"
	return True, (sonuc.stdout or b"").decode("utf-8", "replace").strip()[:160]


def scanner_health(*, refresh: bool = False) -> dict:
	"""Hangi tarayıcı ÇALIŞIYOR — F-28.

	**TANI amaçlıdır — karar yolunda ÇAĞRILMAZ.** `policy()` ve
	`scanner_available()` bilinçli olarak buraya bağlı değil: sağlığı politikaya
	bağlamak, daemon bir an düştüğünde `hold_until_clean`i de kapatıp o aralıkta
	yüklenen dosyaları taranmadan public ağaca çıkarıyordu. Tarama anındaki
	kurtarma `scan_path` → `_yedek_komut` yolunda.

	Buranın işi operatöre "binary duruyor ama daemon cevap vermiyor" farkını
	göstermek. `shutil.which` bu farkı göremiyordu.

	Sonuç önbelleğe alınıyor; bedeli, daemon geri geldiğinde en fazla
	`_HEALTH_TTL_SECONDS` kadar bayat bilgi.
	"""
	if not refresh:
		anlik = _health_memo.get("at")
		deger = _health_memo.get("value")
		if isinstance(anlik, float) and isinstance(deger, dict):
			if time.monotonic() - anlik < _HEALTH_TTL_SECONDS:
				return deger
		try:
			onbellek = frappe.cache.get_value(_HEALTH_CACHE_KEY)
		except Exception:
			onbellek = None
		if isinstance(onbellek, dict):
			_health_memo.update({"at": time.monotonic(), "value": onbellek})
			return onbellek

	adaylar: list[dict] = []
	secilen: tuple[str, ...] | None = None
	for isim, bayraklar in _SCANNER_CANDIDATES:
		yol = shutil.which(isim)
		if not yol:
			adaylar.append({"name": isim, "installed": False, "healthy": False, "detail": "kurulu değil"})
			continue
		saglikli, detay = _saglik_yoklamasi(yol)
		adaylar.append({"name": isim, "installed": True, "healthy": saglikli, "detail": detay})
		if saglikli and secilen is None:
			secilen = (yol, *bayraklar)

	durum = {
		"ok": secilen is not None,
		"command": list(secilen) if secilen else [],
		"scanner": secilen[0] if secilen else "",
		"candidates": adaylar,
		"checked_at": frappe.utils.now(),
	}
	_health_memo.update({"at": time.monotonic(), "value": durum})
	try:
		frappe.cache.set_value(_HEALTH_CACHE_KEY, durum, expires_in_sec=_HEALTH_TTL_SECONDS)
	except Exception:
		# Redis yazılamazsa süreç içi memo devrede kalır; doğruluk bozulmaz,
		# yalnız başka süreçler kendi yoklamasını yapar.
		pass
	return durum


def healthy_scanner_command() -> tuple[str, ...] | None:
	"""Çalıştığı doğrulanmış tarayıcı komutu — yoksa None."""
	durum = scanner_health()
	return tuple(durum["command"]) if durum.get("ok") else None


def scanner_available() -> bool:
	"""Tarayıcı KURULU mu.

	Bilinçli olarak sağlık yoklaması YAPMAZ: `policy()` buradan besleniyor ve
	sağlığa bağlanması daemon düştüğü anda bekletmeyi de kapatıp dosyaları
	taranmadan yayına çıkarıyordu. Daemon'ın gerçekten cevap verip vermediği
	`scan_path` içinde, tarama anında ele alınıyor.
	"""
	return scanner_command() is not None


def policy() -> dict:
	"""Çalışma anı politikası — `site_config.json` üzerinden.

	`media_av_enabled` verilmezse "auto": tarayıcı kuruluysa tara, değilse hiç
	kuyruğa girme. Otomatik olması bilinçli — kurulum yapılınca ayrı bir ayar
	açmayı unutmak, güvenlik özelliğinin sessizce kapalı kalmasının en sık
	sebebi.
	"""
	conf = frappe.conf or {}
	acik = conf.get("media_av_enabled", "auto")
	if acik == "auto" or acik is None:
		etkin = scanner_available()
	else:
		etkin = bool(int(acik))
	# Bekletme: dosya taranana kadar public ağaçtan uzak tutulsun mu. Varsayılan
	# "auto" = tarama açıksa bekle. Tarayıcı YOKKEN bekletmek her yüklemeyi
	# sonsuza kadar görünmez yapardı, o yüzden politikaya bağlı.
	bekletme = conf.get("media_av_hold_until_clean", "auto")
	if bekletme == "auto" or bekletme is None:
		beklet = etkin
	else:
		beklet = bool(int(bekletme))
	# DAEMON SAĞLIĞI BURAYA BAĞLANMAZ (F-28 ilk denemesinin geri alınan hatası).
	# `enabled`i sağlığa bağlamak şunu üretiyordu: clamd bir an düşünce
	# `hold_until_clean` de kapanıyor ve o aralıkta yüklenen dosyalar
	# TARANMADAN public ağaca çıkıyordu. Yani düzeltme, düzelttiğinden daha
	# kötü bir fail-open açıyordu. Kurulum = niyet; daemon'ın anlık durumu
	# işletme meselesidir ve `scan_path` içinde ele alınır.
	return {
		"enabled": etkin,
		"fail_closed": bool(int(conf.get("media_av_fail_closed", 0) or 0)),
		"hold_until_clean": beklet and etkin,
		"scanner": (scanner_command() or ("",))[0],
	}


# ── Yol yardımcıları ────────────────────────────────────────────────────


def _quarantine_root() -> str:
	return frappe.get_site_path("private", QUARANTINE_DIRNAME)


def _split_url(file_url: str) -> tuple[str, str]:
	"""Adresi (kök_türü, göreli_yol) olarak ayır.

	Private dosyalar da taranıyor: KYB belgeleri, sözleşme ekleri ve sohbet
	dosyaları public olmadıkları için ZARARSIZ DEĞİL — bir yönetici onları
	indirip açıyor. Kapsamı public'le sınırlamak, en hassas indirme yolunu
	taramasız bırakırdı.
	"""
	url = (file_url or "").split("?")[0]
	if ".." in url:
		frappe.throw(frappe._("Geçersiz dosya yolu: {0}").format(file_url))
	if url.startswith("/private/files/"):
		return "private", url[len("/private/files/") :]
	if url.startswith("/files/"):
		return "public", url[len("/files/") :]
	frappe.throw(frappe._("Geçersiz dosya yolu: {0}").format(file_url))
	return "", ""  # pragma: no cover — throw yukarıda kesiyor


def _guarded(root: str, relative: str, hata: str, file_url: str) -> str:
	"""Kökün altında kaldığını doğrulanmış mutlak yol.

	`realpath` sembolik bağı da çözer: `files/x -> /etc/passwd` gibi bir bağ
	`startswith` kontrolünü kök karşılaştırmasıyla düşürür.
	"""
	kok = os.path.realpath(root)
	hedef = os.path.realpath(os.path.join(kok, relative))
	if not hedef.startswith(kok + os.sep):
		frappe.throw(frappe._(hata).format(file_url))
	return hedef


def _live_path(file_url: str) -> str:
	tur, goreli = _split_url(file_url)
	kok = frappe.get_site_path("private", "files") if tur == "private" else frappe.get_site_path("public", "files")
	return _guarded(kok, goreli, "Dosya yolu kök dizinin dışında: {0}", file_url)


def _quarantine_path(file_url: str) -> str:
	"""Karantinadaki hedef yol.

	Public ve private ağaçları karantina içinde de AYRI tutuluyor: geri alma
	dosyayı doğru köke döndürebilmeli, yoksa private bir KYB belgesi public
	dizine geri konurdu.
	"""
	tur, goreli = _split_url(file_url)
	alt = os.path.join("private", goreli) if tur == "private" else goreli
	return _guarded(_quarantine_root(), alt, "Karantina yolu kök dizinin dışında: {0}", file_url)


def _hold_root() -> str:
	return frappe.get_site_path("private", SCAN_HOLD_DIRNAME)


def _hold_path(file_url: str) -> str:
	"""Bekletme alanındaki hedef yol — karantinayla aynı ayrım kuralı."""
	tur, goreli = _split_url(file_url)
	alt = os.path.join("private", goreli) if tur == "private" else goreli
	return _guarded(_hold_root(), alt, "Bekletme yolu kök dizinin dışında: {0}", file_url)


def current_path(file_url: str) -> str:
	"""Dosya fiziksel olarak NEREDE — canlı, bekletmede ya da karantinada.

	Tarama işi dosyayı okumak zorunda; bekletme onu canlı ağaçtan çıkardığı için
	`_live_path` tek başına yetmiyor. Sıra önemli: canlı → bekletme → karantina.
	Hiçbirinde yoksa boş döner (dosya silinmiş ya da hiç yazılmamış).
	"""
	for cozucu in (_live_path, _hold_path, _quarantine_path):
		try:
			yol = cozucu(file_url)
		except Exception:
			continue
		if os.path.exists(yol):
			return yol
	return ""


def in_hold(file_url: str) -> bool:
	try:
		return os.path.exists(_hold_path(file_url))
	except Exception:
		return False


def _tasi(src: str, dst: str) -> None:
	"""Dizini hazırlayıp taşı — tek yerde, çünkü üç akış da aynı şeyi yapıyor."""
	os.makedirs(os.path.dirname(dst), exist_ok=True)
	shutil.move(src, dst)


def hold(file_url: str) -> bool:
	"""Dosyayı tarama bitene kadar public ağaçtan çıkar — pencereyi kapatır.

	Kabul kriteri 4 ("riskli dosyalar erişime açılmamalı") bu olmadan yalnız
	KALICI açıklığı kapatıyordu: dosya, kaydın açılması ile taramanın bitmesi
	arasında saniyelerce servis edilebiliyordu. Bekletme o aralığı da kapatır.

	`file_url` DEĞİŞMEZ — yalnız dosyanın fiziksel yeri değişir. İçerik-adresli
	adlandırmanın (`naming.py`) sözleşmesi bu yüzden korunuyor: adres yükleme
	anında kesinleşiyor, dosya sonradan yerine konuyor. Alternatif (önce
	private'a yükleyip sonra public'e taşımak) adresi yükleme anında belirsiz
	bırakırdı.

	Idempotent: zaten bekletmedeyse ya da canlıda yoksa sessizce False döner.
	"""
	try:
		src = _live_path(file_url)
		if not os.path.exists(src):
			return False
		_tasi(src, _hold_path(file_url))
		return True
	except Exception:
		frappe.log_error(
			title="media.av bekletmeye alınamadı", message=f"{file_url}: {frappe.get_traceback()}"
		)
		return False


def _turev_uretimini_tetikle(file_url: str) -> None:
	"""F-27: Beklemeden dönen dosya için türev üretimini YENİDEN kuyruğa al.

	Yükleme anında iki şey aynı anda oluyor: `File.after_insert` türev işini
	kuyruğa alıyor, tarama kancası da dosyayı public ağaçtan bekletmeye
	çekiyor. İş worker'da çalıştığında dosya artık orada değil; hiçbir türev
	üretilmiyor ve iş hatasız biterek yeniden denenmiyor. Tarama temiz çıkıp
	dosya geri konduğunda ise kimse üretimi tekrar tetiklemiyordu.

	Sonuç ölçüldü: bekletmeye giren dosyalar 0 Media Asset ile kalıyor, elle
	tetiklenen aynı dosya 1 üretiyor. Yani tarama açıkken hattın kendisi
	sessizce devre dışı kalıyordu.

	Burası tek doğru yer: dosyanın canlı ağaca DÖNDÜĞÜ an. `maybe_generate_
	renditions` yeniden çağrılıyor, kendi kapıları (bayrak, rollout, kapsam,
	slot, idempotency) olduğu gibi işliyor — burada hiçbir karar kopyalanmıyor.
	`_renditions_exist` zaten üretilmişse iş açılmasını engelliyor, o yüzden
	tekrar çağrı güvenli.

	Best-effort: burada patlamak taramanın sonucunu yazmayı engellememeli.
	"""
	try:
		from tradehub_core.media import pipeline_bridge

		ad = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not ad:
			return
		pipeline_bridge.maybe_generate_renditions(frappe.get_doc("File", ad))
	except Exception:
		frappe.log_error(
			title="media.av türev üretimi tetiklenemedi",
			message=f"{file_url}: {frappe.get_traceback()}",
		)


def release_hold(file_url: str) -> bool:
	"""Bekletmedeki dosyayı canlı ağaca geri koy — tarama temiz çıktı.

	Dosya geri konduktan sonra türev üretimi yeniden tetikleniyor (F-27);
	gerekçe `_turev_uretimini_tetikle` docstring'inde.
	"""
	try:
		src = _hold_path(file_url)
		if not os.path.exists(src):
			return False
		_tasi(src, _live_path(file_url))
		_turev_uretimini_tetikle(file_url)
		return True
	except Exception:
		frappe.log_error(
			title="media.av bekletmeden çıkarılamadı",
			message=f"{file_url}: {frappe.get_traceback()}",
		)
		return False


def _hold_url(yol: str) -> str:
	"""Bekletme yolundan `file_url`'i geri üret — `_hold_path`'in tersi."""
	koke_gore = os.path.relpath(yol, _hold_root())
	if koke_gore.startswith("private" + os.sep):
		return "/private/files/" + koke_gore[len("private") + 1 :].replace(os.sep, "/")
	return "/files/" + koke_gore.replace(os.sep, "/")


@frappe.whitelist()
def sweep_orphaned_holds(dry_run: bool = True, limit: int = 5000) -> dict:
	"""Sahipsiz bekletme kopyalarını raporla / temizle — `cleanup_on_file_trash`'in ikizi.

	Kanca BUNDAN SONRAKİ birikimi önlüyor; bu süpürücü kanca yokken oluşmuş
	YIĞINI temizler. İkisi ayrı: mevcut kurulumlarda kanca tek başına hiçbir
	şeyi düzeltmez.

	**Sahipsiz** = bekletme altında dosya var, ama o adrese ait `File` kaydı
	YOK. Taraması süren gerçek dosyalar (kaydı duran) ASLA silinmez — ölçüt
	dosyanın yaşı ya da tarama durumu değil, kaydının varlığıdır; bu, yarışa
	kapalı tek ölçüt.

	Neden önemli olduğu `cleanup_on_file_trash` docstring'inde: adlandırma
	içerik-adresli olduğu için sahipsiz bir artık, aynı içeriğin YENİ ve temiz
	bir yüklemesini `seo_index.decide` gözünde "karantinada" gösteriyor.

	`dry_run=True` (varsayılan) hiçbir şey silmez — yalnız sayar ve örnekler.
	"""
	dry_run = bool(dry_run) if not isinstance(dry_run, str) else dry_run.lower() not in ("0", "false")
	frappe.only_for("System Manager")

	kok = _hold_root()
	toplam = 0
	sahipsiz: list[str] = []
	bayt = 0
	if not os.path.isdir(kok):
		return {"scanned": 0, "orphans": 0, "deleted": 0, "bytes": 0, "samples": [], "dry_run": dry_run}

	for dizin, _alt, dosyalar in os.walk(kok):
		for ad in dosyalar:
			if toplam >= limit:
				break
			yol = os.path.join(dizin, ad)
			toplam += 1
			try:
				url = _hold_url(yol)
			except Exception:
				continue
			if frappe.db.exists("File", {"file_url": url}):
				continue
			sahipsiz.append(yol)
			try:
				bayt += os.path.getsize(yol)
			except OSError:
				pass

	silinen = 0
	if not dry_run:
		for yol in sahipsiz:
			try:
				os.remove(yol)
				silinen += 1
				try:
					os.rmdir(os.path.dirname(yol))
				except OSError:
					pass
			except OSError:
				continue
		audit.log_media_event(
			action=audit.ACTION_SCAN,
			file_url="",
			reason="orphaned_holds_swept",
			context={"deleted": silinen, "bytes": bayt},
		)

	return {
		"scanned": toplam,
		"orphans": len(sahipsiz),
		"deleted": silinen,
		"bytes": bayt,
		"samples": [_hold_url(y) for y in sahipsiz[:10]],
		"dry_run": dry_run,
	}


def cleanup_on_file_trash(doc, method: str | None = None) -> None:
	"""`File.on_trash` — silinen dosyanın BEKLETME kopyasını da kaldır.

	Bekletme (`media_scan_hold`) geçici bir bekleme odası: dosyayı tarama
	bitene kadar public ağaçtan uzak tutar. `File` kaydı silindiğinde Frappe
	canlı dosyayı siler ama bu kopyadan haberi yoktur ve kopya SONSUZA KADAR
	kalır.

	İki somut zarar ölçüldü (2026-08-29):

	  1. Depolama sızıntısı — `media_scan_hold` altında 509 artık dosya.
	  2. **Yanlış karantina kararı.** Adlandırma içerik-adresli
	     (`sha256[:32].uzantı`); aynı içerik ileride yeniden yüklenirse ADRESİ
	     de aynı olur. `seo_index.decide` bekletme/karantina kontrolünü DOSYA
	     SİSTEMİNDEN yapıyor (`av.in_hold(url)`), dolayısıyla eski artık
	     yüzünden yepyeni ve temiz bir dosya `reason="quarantine"` alıp
	     site haritasından ve yapısal veriden düşüyor.

	KARANTİNA KOPYASI SİLİNMEZ. O bir bekleme odası değil, bulgu kaydı: zararlı
	içeriğin kanıtı ve saklama kararı güvenlik tarafınındır. Yalnız denetime
	yazılır ki sahipsiz kalan kopya izlenebilsin.

	Best-effort: burada patlamak silme işlemini ASLA engellememeli.
	"""
	try:
		file_url = getattr(doc, "file_url", "") or ""
		if not file_url:
			return
		if in_quarantine(file_url):
			audit.log_media_event(
				action=audit.ACTION_SCAN,
				file_url=file_url,
				reason="quarantine_orphaned_by_file_delete",
				context={"note": "File kaydı silindi, karantina kopyası korundu"},
			)
			return
		yol = _hold_path(file_url)
		if not os.path.exists(yol):
			return
		os.remove(yol)
		# Boş kalan shard dizinini topla; 256 boş dizin bırakmanın anlamı yok.
		try:
			os.rmdir(os.path.dirname(yol))
		except OSError:
			pass
	except Exception:
		frappe.log_error(
			title="media.av bekletme kopyası silinemedi",
			message=f"{getattr(doc, 'file_url', '?')}: {frappe.get_traceback()}",
		)


def in_quarantine(file_url: str) -> bool:
	try:
		return os.path.exists(_quarantine_path(file_url))
	except Exception:
		return False


# ── Durum yazma ─────────────────────────────────────────────────────────


def _set_status(name: str, status: str) -> None:
	frappe.db.set_value("File", name, "th_media_scan_status", status, update_modified=False)


def _stamp_started(name: str, *, attempts: int | None = None) -> None:
	"""İşi "şu an çalışıyor" diye damgala — süpürücü buna bakar.

	`next_at` TEMİZLENİR: planlı deneme kuyruğa girdiği anda plan tüketilmiştir.
	Kalsaydı süpürücü aynı dosyayı bir kez daha kuyruğa koyardı.
	"""
	degerler: dict = {
		"th_media_scan_next_at": None,
		"th_media_scan_started_at": now_datetime(),
	}
	if attempts is not None:
		degerler["th_media_scan_attempts"] = attempts
	frappe.db.set_value("File", name, degerler, update_modified=False)


def current_status(file_url: str) -> str:
	"""Adresteki dosyanın tarama durumu — kötü haber kazanır.

	Aynı `file_url`'e birden çok `File` kaydı işaret edebiliyor (ölçüm: tek
	dosyaya 39 kayda kadar) ve durumları ayrışabilir. `infected` varsa o döner:
	bir kayıt "temiz" diyor diye zararlı dosyayı temiz saymak, durum ayrışmasının
	en pahalı hâli olurdu.
	"""
	durumlar = {
		r.th_media_scan_status
		for r in frappe.get_all(
			"File", filters={"file_url": file_url}, fields=["th_media_scan_status"]
		)
		if r.th_media_scan_status
	}
	for oncelikli in (SCAN_INFECTED, SCAN_FAILED, SCAN_PENDING, SCAN_CLEAN):
		if oncelikli in durumlar:
			return oncelikli
	return ""


def is_servable(file_url: str) -> bool:
	"""Bu dosya erişime açık olmalı mı — politika kararı.

	Fiziksel kapıyı karantina taşıması kuruyor; bu fonksiyon Python tarafındaki
	yolların (indirme uçları, yedek paketleme) aynı kararı tekrar üretmeden
	sorabilmesi için var.
	"""
	durum = current_status(file_url)
	if durum == SCAN_INFECTED:
		return False
	if durum == SCAN_PENDING and in_hold(file_url):
		# Henüz bilmiyoruz — bilmediğimiz sürece açmıyoruz.
		return False
	if durum == SCAN_FAILED and policy()["fail_closed"]:
		return False
	return True


# ── Kuyruğa alma ────────────────────────────────────────────────────────


def enqueue_scan(file_url: str, name: str | None = None) -> dict:
	"""Taramayı kuyruğa al — idempotent.

	Durumu zaten dolu olan dosya yeniden kuyruğa GİRMEZ: aynı dosya iki ayrı
	yoldan tetiklenebiliyor (kanca + elle çağrı) ve iki worker aynı dosyayı
	tarayıp birbirinin damgasını ezerdi.
	"""
	if not file_url:
		return {"file_url": file_url, "status": "", "skipped": "no_url"}

	if not policy()["enabled"]:
		# Tarayıcı yok / kapalı: kuyruğa hiç girme. Durum BOŞ bırakılıyor,
		# `failed` yazılmıyor — "denendi, olmadı" ile "hiç denenmedi" farklı
		# şeyler ve panel ikisini karıştırmamalı.
		return {"file_url": file_url, "status": "", "skipped": "disabled"}

	if name and not frappe.db.exists("File", name):
		name = None
	name = name or frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		return {"file_url": file_url, "status": "", "skipped": "no_record"}

	if frappe.db.get_value("File", name, "th_media_scan_status"):
		return {"file_url": file_url, "status": SCAN_PENDING, "skipped": "already"}

	_set_status(name, SCAN_PENDING)
	_stamp_started(name, attempts=0)
	frappe.enqueue(
		"tradehub_core.media.av._run_scan",
		queue="default",
		timeout=QUEUE_TIMEOUT_SECONDS,
		file_url=file_url,
		name=name,
		enqueue_after_commit=True,
	)
	return {"file_url": file_url, "status": SCAN_PENDING}


def rescan_after_write(file_urls, *, reason: str = "") -> dict:
	"""Canlı ağaca YENİ bayt yazıldı — o dosyaları yeniden taramaya sok.

	Kanca `File.after_insert`'e bağlı, yani yalnız KAYIT açan yolları görüyor.
	Oysa baytı değiştiren üç yol daha var ve üçü de yeni kayıt açmıyor:

	    files.replace          satıcı dosyanın içeriğini değiştiriyor
	    restore.apply          platform yedeğinden geri yazılıyor
	    seller_backup.apply    satıcı yedeğinden geri yazılıyor

	Bu yollarda eski damga yeni içeriği AKLIYOR: dosya "clean" görünürken
	diskteki baytlar bambaşka. Damga sıfırlanıp dosya yeniden kuyruğa girmeli —
	kuralın üç kopyası olmasın diye tek yer burası.

	`enqueue_scan` durumu dolu olan dosyayı atlar (idempotency), bu yüzden ÖNCE
	sıfırlama şart; sırayı ters çevirmek bu fonksiyonu sessizce etkisiz kılardı.

	Politika bekletme diyorsa dosya tarama bitene kadar canlı ağaçtan çıkarılır —
	yeni yüklemeyle aynı davranış. Toplu geri yüklemede bu, taranana kadar
	görsellerin görünmemesi demek; operatör isterse `media_av_hold_until_clean`
	ile kapatabilir (felaket kurtarmada bilinçli bir tercih olabilir).

	Best-effort: tarama altyapısındaki bir aksaklık, başarıyla yazılmış içeriği
	geri almayı gerektirmez. Hata loglanır, çağıran akış devam eder.
	"""
	adresler = [u for u in (file_urls or []) if u]
	if not adresler:
		return {"queued": 0, "held": 0}

	if not policy()["enabled"]:
		# Tarayıcı yok/kapalı: damgayı sıfırlamanın da anlamı yok. "Denendi,
		# olmadı" ile "hiç denenmedi" farklı şeyler (bkz. `enqueue_scan`).
		return {"queued": 0, "held": 0, "skipped": "disabled"}

	beklet = policy()["hold_until_clean"]
	kuyruga = 0
	bekletilen = 0

	for url in adresler:
		try:
			if in_quarantine(url):
				# Karantinadaki dosyaya zaten yazılmadı (çağıranlar engelliyor);
				# damgasını sıfırlamak bulguyu silmek olurdu.
				continue
			frappe.db.set_value(
				"File",
				{"file_url": url},
				{
					"th_media_scan_status": "",
					"th_media_scan_attempts": 0,
					"th_media_scan_next_at": None,
				},
				update_modified=False,
			)
			frappe.db.commit()
			if enqueue_scan(url).get("status") == SCAN_PENDING:
				kuyruga += 1
				if beklet and hold(url):
					bekletilen += 1
		except Exception:
			frappe.log_error(
				title="media.av rescan_after_write failed",
				message=f"{url}: {frappe.get_traceback()}",
			)

	if kuyruga:
		audit.log_media_event(
			action=audit.ACTION_SCAN,
			reason=f"rescan_after_write:{reason}" if reason else "rescan_after_write",
			context={"files": len(adresler), "queued": kuyruga, "held": bekletilen},
		)
	return {"queued": kuyruga, "held": bekletilen}


def maybe_scan_on_insert(doc, method: str | None = None) -> None:
	"""`File.after_insert` kancası — her yeni dosya taramaya girer.

	Kapsam transcode kancasından BİLEREK geniş: orada soru "bu videoyu küçültmek
	gerekir mi" (maliyet kararı), burada "bu dosya zararlı mı" (güvenlik kararı).
	Güvenlik kararını satıcıyla, uzantıyla ya da public/private ile daraltmak,
	kapsam dışında kalan her yolu taramasız bırakırdı.

	Klasörler hariç: taranacak içerik yok.

	Best-effort — burada patlamak kullanıcının yüklemesini engellememeli
	(`states.on_file_insert` ile aynı desen).
	"""
	try:
		if doc.get("is_folder"):
			return
		if not doc.get("file_url"):
			# Gömülü içerik (`content` alanı) diske yazılmamış olabilir.
			return
		sonuc = enqueue_scan(doc.get("file_url"), doc.name)
		# Bekletme kuyruğa alma BAŞARILI olduktan sonra: sırayı ters çevirmek,
		# kuyruğa hiç girmemiş bir dosyayı görünmez bırakırdı (kimse geri
		# koymayacağı için kalıcı olarak).
		if sonuc.get("status") == SCAN_PENDING and policy()["hold_until_clean"]:
			hold(doc.get("file_url"))
	except Exception:
		frappe.log_error(title="media.av maybe_scan_on_insert failed", message=frappe.get_traceback())


# ── Tarama ──────────────────────────────────────────────────────────────


def scan_path(path: str) -> tuple[str, str]:
	"""Tek dosyayı tara — (sonuç, imza_adı).

	Sonuç `SCAN_CLEAN` / `SCAN_INFECTED`; tarayıcı çalışamazsa exception atar ve
	çağıran retry yoluna düşer. "Emin değilsek temiz" DEMİYORUZ: tarayıcının
	çökmesi dosyanın temiz olduğunun kanıtı değil.
	"""
	cmd = scanner_command()
	if not cmd:
		raise FileNotFoundError("AV tarayıcısı kurulu değil (clamdscan/clamscan)")

	try:
		return _tara(cmd, path)
	except (subprocess.TimeoutExpired, RuntimeError) as ilk_hata:
		# F-28 — `clamdscan` bir istemci, iş `clamd` daemon'ında. Daemon ölü ya
		# da asılıysa binary yerinde durduğu için seçim değişmiyordu ve HER
		# tarama aynı duvara çarpıyordu: 120 sn zaman aşımı, ardından yeniden
		# deneme ve dead-letter. Ölçüldü (container, 2026-08-28): daemon SIGSTOP
		# ile dondurulduğunda `clamdscan` hata VERMİYOR, donuyor.
		#
		# Ön yoklama YAPILMIYOR — her taramaya alt süreç maliyeti eklerdi ve
		# sağlıklı yolda hiçbir şey kazandırmazdı. Yedek yalnız gerçekten
		# başarısız olunca devreye giriyor.
		yedek = _yedek_komut(cmd)
		if not yedek:
			raise
		frappe.log_error(
			title="media.av tarayıcı yedeğe düştü",
			message=f"{cmd[0]} başarısız ({type(ilk_hata).__name__}); {yedek[0]} deneniyor",
		)
		return _tara(yedek, path)


def _tara(cmd: tuple[str, ...], path: str) -> tuple[str, str]:
	"""Tek tarayıcı çağrısı — sonucu sözleşmeye çevirir."""
	sonuc = subprocess.run(
		[*cmd, path], capture_output=True, timeout=_SCAN_TIMEOUT_SECONDS, check=False
	)
	if sonuc.returncode == _EXIT_CLEAN:
		return SCAN_CLEAN, ""
	if sonuc.returncode == _EXIT_INFECTED:
		return SCAN_INFECTED, _signature_name(sonuc.stdout)
	# 2+ = tarayıcı hatası. Metni exception'a taşıyoruz ki denetim kaydında
	# "neden taranamadı" sorusu cevaplanabilsin.
	ciktilar = (sonuc.stderr or sonuc.stdout or b"").decode("utf-8", "replace").strip()
	raise RuntimeError(f"tarayıcı hata kodu {sonuc.returncode}: {ciktilar[:300]}")


def _yedek_komut(kullanilan: tuple[str, ...]) -> tuple[str, ...] | None:
	"""Tercih sırasında, kullanılandan SONRAKİ ilk kurulu aday.

	`clamdscan` daemon'a bağımlı; `clamscan` tek başına çalışır. Sıra bu yüzden
	anlamlı: yedek her zaman daha bağımsız olan taraf.
	"""
	kullanilan_ad = os.path.basename(kullanilan[0])
	gecildi = False
	for isim, bayraklar in _SCANNER_CANDIDATES:
		if not gecildi:
			gecildi = isim == kullanilan_ad
			continue
		yol = shutil.which(isim)
		if yol:
			return (yol, *bayraklar)
	return None


def _signature_name(stdout: bytes) -> str:
	"""clamdscan çıktısından imza adını ayıkla.

	Biçim: `/yol/dosya: Eicar-Test-Signature FOUND`. Ad bulunamazsa boş döner —
	imzayı okuyamamak bulguyu geçersiz kılmaz.
	"""
	metin = (stdout or b"").decode("utf-8", "replace")
	for satir in metin.splitlines():
		if satir.rstrip().endswith("FOUND"):
			govde = satir.rsplit(":", 1)[-1].strip()
			return govde[: -len("FOUND")].strip() or ""
	return ""


def _run_scan(file_url: str, name: str | None = None) -> None:
	"""Worker'da çalışır — dosyayı tarar, sonuca göre damgalar.

	`name` kayıt adıyla taşınıyor: aynı adrese birden çok kayıt işaret
	edebildiği için adresten çözmek O ADRESTEKİ İLK kaydı bulur, süpürücü ise
	kayıt bazında çalışır — sayaç başka kayıtta artar ve hedef kayıt sonsuza
	kadar `pending` kalırdı (transcode'da yaşandı, aynı tuzak).
	"""
	if name and not frappe.db.exists("File", name):
		name = None
	name = name or frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		# Kuyruğa alındıktan sonra dosya silinmiş olabilir.
		return

	# Damgayı worker BAŞLARKEN tazele: kuyrukta uzun bekleyen iş, gerçekte yeni
	# başlamışken "kayıp" ilan edilip ikinci kez kuyruğa girmesin.
	_stamp_started(name)
	frappe.db.commit()

	try:
		# `_live_path` DEĞİL: dosya bekletmede olabilir (pencereyi kapatan
		# mekanizma onu canlı ağaçtan çıkarıyor) ve orada da taranmalı.
		yol = current_path(file_url)
		if not yol:
			# Dosya hiçbir yerde yok (çöpe taşınmış, geri yüklenmiş, elle
			# silinmiş). Taranacak bir şey yok ve bu bir HATA değil.
			_set_status(name, SCAN_CLEAN)
			frappe.db.commit()
			return

		sonuc, imza = scan_path(yol)
	except Exception as exc:  # noqa: BLE001 — worker hiçbir koşulda kuyruğu patlatmamalı
		_on_scan_failure(name, file_url, exc)
		return

	if sonuc == SCAN_INFECTED:
		_quarantine(name, file_url, imza)
		return

	# Önce dosyayı yerine koy, SONRA temiz damgala. Ters sıra, "temiz" yazılıp
	# taşımanın patladığı durumda dosyayı erişilemez ama panelde sorunsuz
	# gösterirdi — sessiz kayıp.
	geri_kondu = release_hold(file_url)
	_set_status(name, SCAN_CLEAN)
	frappe.db.commit()
	audit.log_media_event(
		action=audit.ACTION_SCAN,
		file_url=file_url,
		context={"result": SCAN_CLEAN, **({"released_from_hold": True} if geri_kondu else {})},
	)


# ── Karantina ───────────────────────────────────────────────────────────


def _quarantine(name: str, file_url: str, imza: str) -> None:
	"""Zararlı dosyayı erişimin dışına taşı.

	Taşıma BAŞARISIZ olursa durum yine de `infected` yazılır. Ters sırayla
	yapmak (önce taşı, sonra damgala) taşımanın başarılı ama damganın yazılamadığı
	durumda dosyayı "temiz görünen ama kayıp" hâle sokardı; bu sırada en kötü
	ihtimalle dosya diskte kalır ama panelde kırmızı görünür — sessiz kalmaz.
	"""
	_set_status(name, SCAN_INFECTED)
	frappe.db.commit()

	tasindi = False
	hata = ""
	try:
		# Dosya canlı ağaçta OLMAYABİLİR: bekletme mekanizması onu zaten oradan
		# çıkarmış olabilir. `current_path` üçünü de biliyor.
		src = current_path(file_url)
		hedef = _quarantine_path(file_url)
		if src and os.path.realpath(src) != os.path.realpath(hedef):
			_tasi(src, hedef)
		tasindi = True
	except Exception as exc:  # noqa: BLE001 — damga zaten yazıldı, burada patlamak kaydı bozar
		hata = str(exc)
		frappe.log_error(
			title="media.av karantinaya taşınamadı",
			message=f"{file_url}: {frappe.get_traceback()}",
		)

	audit.log_media_event(
		action=audit.ACTION_QUARANTINE,
		file_url=file_url,
		allowed=False,
		reason=f"malware:{imza}" if imza else "malware",
		context={"signature": imza, "moved": tasindi, **({"error": hata} if hata else {})},
	)


def release_from_quarantine(file_url: str) -> dict:
	"""Yanlış pozitifi geri al — dosyayı yerine koy, durumu temizle.

	Yetki kontrolü BURADA YAPILMAZ; çağıran API katmanı yapar (bu modül HTTP'den
	doğrudan erişilemez) — `transcode.retry_failed` ile aynı sözleşme.

	Durum `clean` DEĞİL, boş bırakılıyor: dosya taramadan geçip temiz çıkmadı,
	bir insan kararıyla geri getirildi. Boş durum onu yeniden tarama kapsamına
	sokar; "temiz" yazmak insan kararını tarayıcı sonucu gibi gösterirdi.
	"""
	kayitlar = frappe.get_all("File", filters={"file_url": file_url}, pluck="name")
	if not kayitlar:
		frappe.throw(frappe._("Dosya bulunamadı: {0}").format(file_url))

	src = _quarantine_path(file_url)
	if not os.path.exists(src):
		frappe.throw(frappe._("Bu dosya karantinada değil: {0}").format(file_url))

	_tasi(src, _live_path(file_url))

	for kayit in kayitlar:
		frappe.db.set_value(
			"File",
			kayit,
			{"th_media_scan_status": "", "th_media_scan_attempts": 0, "th_media_scan_next_at": None},
			update_modified=False,
		)
	frappe.db.commit()

	audit.log_media_event(
		action=audit.ACTION_QUARANTINE_RELEASE,
		file_url=file_url,
		context={"records": len(kayitlar)},
	)
	return {"file_url": file_url, "released": True, "records": len(kayitlar)}


# ── Başarısızlık, retry, dead-letter ────────────────────────────────────


def _on_scan_failure(name: str, file_url: str, exc: Exception) -> None:
	"""Başarısız denemeyi say; hakkı varsa yenisini planla, yoksa dead-letter.

	Retry sırasında durum `pending` KALIR — kullanıcıya "başarısız" gösterip iki
	dakika sonra "temiz"e dönmek güven bozar; başarısızlık ancak sistem gerçekten
	pes ettiğinde gösterilir (`transcode` ile aynı gerekçe).
	"""
	attempts = (frappe.db.get_value("File", name, "th_media_scan_attempts") or 0) + 1
	frappe.db.set_value("File", name, "th_media_scan_attempts", attempts, update_modified=False)

	sebep = type(exc).__name__
	detay = str(exc)

	if attempts < MAX_SCAN_ATTEMPTS:
		frappe.db.set_value(
			"File", name, "th_media_scan_next_at", jobs.next_attempt_at(attempts), update_modified=False
		)
		frappe.db.commit()
		frappe.log_error(
			title="Medya taraması başarısız — yeniden denenecek",
			message=(
				f"{file_url} (deneme {attempts}/{MAX_SCAN_ATTEMPTS}, "
				f"{jobs.backoff_seconds(attempts)} sn sonra): {detay}"
			),
		)
		audit.log_media_event(
			action=audit.ACTION_SCAN,
			file_url=file_url,
			allowed=False,
			reason=f"scan_retry:{sebep}",
			context={"attempt": attempts, "retry_in": jobs.backoff_seconds(attempts)},
		)
		return

	_dead_letter(name, file_url, attempts, sebep=sebep, detay=detay)


def _dead_letter(name: str, file_url: str, attempts: int, *, sebep: str, detay: str) -> None:
	"""Hak bitti — dosya taranamadı.

	`fail_closed` açıksa taranamayan dosya da karantinaya gider: "emin değilsek
	kapat". Varsayılan kapalı, gerekçesi modül docstring'inde.
	"""
	frappe.db.set_value(
		"File",
		name,
		{"th_media_scan_status": SCAN_FAILED, "th_media_scan_next_at": None},
		update_modified=False,
	)
	frappe.db.commit()
	frappe.log_error(title="Medya taraması başarısız", message=f"{file_url}: {detay}")
	audit.log_media_event(
		action=audit.ACTION_SCAN,
		file_url=file_url,
		allowed=False,
		reason=f"scan_failed:{sebep}",
		context={"attempts": attempts, "fail_closed": policy()["fail_closed"]},
	)

	if policy()["fail_closed"]:
		_quarantine(name, file_url, imza="")
		return

	# Fail-open: taranamayan dosya erişimde KALIR. Bekletmedeyse geri konmalı —
	# aksi halde "açık bırakıyoruz" dediğimiz dosya sessizce sonsuza kadar
	# görünmez kalırdı, yani politika söylediğinin tersini yapardı.
	if release_hold(file_url):
		audit.log_media_event(
			action=audit.ACTION_SCAN,
			file_url=file_url,
			reason="hold_released_fail_open",
			context={"attempts": attempts},
		)


def retry_failed(file_url: str) -> dict:
	"""Dead-letter'daki taramayı insan eliyle yeniden kuyruğa koy.

	Yalnız `failed` kabul edilir: `pending` zaten kuyrukta, `clean` sonuç almış,
	`infected` karantinada (oradan çıkış `release_from_quarantine`).
	"""
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		frappe.throw(frappe._("Dosya bulunamadı: {0}").format(file_url))

	durum = frappe.db.get_value("File", name, "th_media_scan_status")
	if durum != SCAN_FAILED:
		frappe.throw(
			frappe._("Yalnız başarısız taramalar yeniden denenebilir (durum: {0}).").format(durum or "-")
		)

	_set_status(name, SCAN_PENDING)
	_stamp_started(name, attempts=0)
	frappe.enqueue(
		"tradehub_core.media.av._run_scan",
		queue="default",
		timeout=QUEUE_TIMEOUT_SECONDS,
		file_url=file_url,
		name=name,
		enqueue_after_commit=True,
	)
	# Yeniden denerken de beklet: dosya bir kez taranamamış durumda, sonucu
	# yine bilmiyoruz. İlk yüklemedekiyle aynı gerekçe.
	if policy()["hold_until_clean"]:
		hold(file_url)
	return {"file_url": file_url, "status": SCAN_PENDING}


def sweep_stuck_scans(limit: int = 200) -> dict:
	"""Zamanlanmış görev — planlı denemeleri ve bırakılmış taramaları toplar.

	`transcode.sweep_stuck_transcodes` ile birebir aynı iki kusuru kapatır:
	backoff süresi dolmuş planlı denemeler ve sert kill sonrası `pending`de
	asılı kalmış işler. `limit` tek turda dokunulacak azami kayıt — bir kuyruk
	kazası binlerce dosyayı takılı bırakabilir.
	"""
	kayitlar = frappe.get_all(
		# Sistem işi: süpürücünün oturumu yok, kullanıcı yetkisi aranmaz.
		"File",
		filters={"th_media_scan_status": SCAN_PENDING},
		fields=[
			"name",
			"file_url",
			"th_media_scan_attempts",
			"th_media_scan_next_at",
			"th_media_scan_started_at",
		],
		limit=limit,
		order_by="modified asc",
	)

	kuyruga_konan = 0
	dusen = 0
	for k in kayitlar:
		if k.th_media_scan_next_at:
			if not jobs.is_due(k.th_media_scan_next_at):
				continue
			_stamp_started(k.name)
			frappe.db.commit()
			frappe.enqueue(
				"tradehub_core.media.av._run_scan",
				queue="default",
				timeout=QUEUE_TIMEOUT_SECONDS,
				file_url=k.file_url,
				name=k.name,
			)
			kuyruga_konan += 1
			continue

		if not jobs.is_stale(k.th_media_scan_started_at):
			continue

		attempts = int(k.th_media_scan_attempts or 0) + 1
		frappe.db.set_value("File", k.name, "th_media_scan_attempts", attempts, update_modified=False)
		detay = "worker işi bıraktı (kuyruk zaman aşımı ya da süreç öldürüldü)"
		if attempts < MAX_SCAN_ATTEMPTS:
			frappe.db.set_value(
				"File",
				k.name,
				"th_media_scan_next_at",
				jobs.next_attempt_at(attempts),
				update_modified=False,
			)
			frappe.db.commit()
		else:
			_dead_letter(k.name, k.file_url, attempts, sebep="Abandoned", detay=detay)
		dusen += 1

	if kuyruga_konan or dusen:
		frappe.logger("media").info(
			f"av sweep: requeued={kuyruga_konan} abandoned={dusen} scanned={len(kayitlar)}"
		)
	return {"scanned": len(kayitlar), "requeued": kuyruga_konan, "abandoned": dusen}


def backfill_pending(limit: int = 500) -> dict:
	"""Tarama alanı boş olan mevcut dosyaları kuyruğa al.

	Yama alanı ekliyor ama 4.000+ mevcut dosyayı taramaya sokmuyor: tek turda
	hepsini kuyruğa boşaltmak kuyruğu saatlerce meşgul ederdi. Bu fonksiyon elle
	(ya da ileride zamanlanmış olarak) parça parça çalıştırılır.
	"""
	if not policy()["enabled"]:
		return {"queued": 0, "skipped": "disabled"}

	kayitlar = frappe.get_all(
		"File",
		# `["in", ["", None]]` DEĞİL: Frappe bunu `IN ('', NULL)` diye çeviriyor ve
		# SQL'de hiçbir şey NULL'a eşit olmadığı için NULL satırlar HİÇ eşleşmiyor.
		# Alan sonradan eklendiği için mevcut kayıtların tamamı NULL — ölçüldü:
		# 5.120 NULL, 30 boş string. Yani bu süzgeç yanlış yazıldığında geriye
		# dönük tarama, işin %99'unu görmeden "bitti" derdi. `is / not set`
		# ikisini birden kapsıyor (`IFNULL(alan, '') = ''`).
		filters={"th_media_scan_status": ["is", "not set"], "is_folder": 0},
		fields=["name", "file_url"],
		limit=limit,
		order_by="creation desc",
	)
	sayac = 0
	for k in kayitlar:
		if not k.file_url:
			continue
		if enqueue_scan(k.file_url, k.name).get("status"):
			sayac += 1
	return {"queued": sayac, "scanned": len(kayitlar)}
