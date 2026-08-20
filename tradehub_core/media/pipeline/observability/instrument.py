"""T-133 — ölçüm noktaları: hattı DEĞİŞTİRMEDEN metriğe ve log'a bağlama.

SORUN — sayaç var, sayan yok
============================
`metrics.py` 24 metrik TANIMLIYOR, `logging.py` yapılandırılmış olay yazmayı
MÜMKÜN kılıyor. Ölçüldü (2026-08-19, `grep -rn` bütün depo):

    UPLOAD_TOTAL / JOB_TOTAL / SCAN_TOTAL / IMAGE_PROCESS_DURATION / …
        → yalnız metrics.py'nin KENDİSİNDE geçiyor.
    log_event / correlation_scope
        → yalnız logging.py'nin kendisinde ve testte geçiyor.

Yani `/metrics` bugün servis edilse **bütün seriler boş** dönerdi. Eksik olan
kütüphane değil, kütüphaneyi çağıran satırlar: **ölçüm noktaları**.

NEDEN ÇAĞRI YERİNE SARMALAYICI
==============================
Doğrusu, ölçülen fonksiyonun içine iki satır yazmaktır. Bu modül bunu YAPMAZ,
üç sebeple:

  1. `image/`, `video/`, `security/`, `policy/` modülleri bu görevin dosya
     kapsamı DIŞINDA (aynı anda 14 ajan çalışıyor; o dosyalara dokunmak
     çakışma üretir ve gözlemlenebilirlik değişikliği başka bir ajanın
     düzeltmesini geri alabilir).
  2. Ölçüm, ölçtüğü kodun içine sızdığında geri almak zorlaşır. Sarmalayıcı
     `uninstall()` ile tek çağrıda kalkar; bu, metrik toplamanın kendisi bir
     olaya sebep olduğunda (bkz. `INSTRUMENT_ERRORS_TOTAL`) elimizdeki tek
     acil müdahale kolu.
  3. Aynı deseni OpenTelemetry'nin otomatik enstrümantasyonu kullanır —
     icat edilmiş bir yol değil.

**Bedeli açıkça:** sarmalayıcı yalnız `install()` çağrıldığında devrededir ve
`install()`'ı bugün hiçbir yer ÇAĞIRMIYOR. Bağlama noktası `hooks.py`'dir
(`app_include`/`after_migrate` ya da `boot`), o dosya da bu görevin kapsamı
dışında. Yani bu modül hattı **bağlanabilir** hâle getirir, **bağlamaz**.
Kalan tek satır `docs/reports/42-t133-gozlemlenebilirlik.md` §6'da yazılı.

GÜVENLİK SÖZLEŞMESİ — ölçüm ölçtüğü işi DÜŞÜREMEZ
=================================================
Her kayıt fonksiyonu `try/except` içinde koşar. Hata yutulur ama SESSİZ
KALMAZ: `INSTRUMENT_ERRORS_TOTAL{point=…}` artar. Yutmamak, bir etiket
çıkarma hatasının kullanıcının yüklemesini düşürmesi demekti; sessiz yutmak
ise metriklerin sessizce eksilmesi. İkisi de kabul edilmez.

Sarmalayıcı istisnayı **yeniden fırlatır** — hata yolunun süresi ölçülür,
hata yolu GİZLENMEZ (`metrics._Zamanlayici` ile aynı karar).

ETİKET KARDİNALİTESİ
====================
Hiçbir kayıt fonksiyonu dosya adı, URL, kullanıcı ya da kiracı yazmaz.
`metrics.py`'nin "etiket kardinalitesi DAR" kuralı ve `logging.py`'nin PII
sözleşmesi burada da geçerlidir; ölçüm noktası, maskelemeyi delen en kolay
yerdir.

`import frappe` YOKTUR — bench gerektiren noktalar (`media/av.py`,
`media/audit.py`) import edilemezse **atlanır** ve raporda sebebiyle görünür.
"""

from __future__ import annotations

import functools
import importlib
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import logging as mlog
from . import metrics as mm

#: Etiket değeri tavanı. Uzun bir `reason` metriği bozmaz ama seri adını
#: okunamaz yapar; kesme sessiz değil, `…` ile görünür.
MAX_ETIKET_UZUNLUK: int = 64

#: Etiketi çıkarılamayan değer. `""` DEĞİL: boş etiket Prometheus'ta geçerli
#: ama panelde "hiç gelmedi" ile "çıkarılamadı" ayırt edilemez hâle gelir.
BILINMEYEN: str = "unknown"


def _e(deger: Any) -> str:
	"""Etiket değeri — kısalt, boşsa `unknown` yap."""
	metin = str(deger if deger not in (None, "") else BILINMEYEN)
	return metin if len(metin) <= MAX_ETIKET_UZUNLUK else metin[: MAX_ETIKET_UZUNLUK - 1] + "…"


@dataclass(frozen=True)
class Cagri:
	"""Sarmalanan çağrının künyesi — kayıt fonksiyonuna verilen tek argüman."""

	args: Tuple[Any, ...]
	kwargs: Dict[str, Any]
	sonuc: Any
	hata: Optional[BaseException]
	sure_s: float

	@property
	def basarili(self) -> bool:
		return self.hata is None

	def arg(self, sira: int, ad: str = "", varsayilan: Any = None) -> Any:
		"""Konumsal ya da anahtarlı argümanı al.

		Sarmalanan fonksiyonlar hem `f(x)` hem `f(src=x)` biçiminde çağrılıyor;
		yalnız birine bakan bir kayıt fonksiyonu, çağrı biçimi değiştiğinde
		sessizce `unknown` yazmaya başlardı.
		"""
		if ad and ad in self.kwargs:
			return self.kwargs[ad]
		if 0 <= sira < len(self.args):
			return self.args[sira]
		return varsayilan


#: Kayıt fonksiyonu — metrikleri yazar, hiçbir şey döndürmez.
Kayit = Callable[[Cagri], None]


@dataclass(frozen=True)
class Nokta:
	"""Tek ölçüm noktası: hangi fonksiyon, hangi metrik, hangi olay adı.

	`nitelik` noktalı olabilir (`PolicyEngine.evaluate`) — sınıf metodları da
	sarmalanabilsin. Sarmalama SINIF üzerinde yapılır, örnek üzerinde değil:
	örnek başına sarmalamak, motor her yeniden yaratıldığında ölçümü
	kaybettirirdi.
	"""

	ad: str
	modul: str
	nitelik: str
	olay: str
	kayit: Kayit
	#: Bu noktanın yazdığı metriklerin TAM adları — `metrik_kapsami()` bunu
	#: kullanır. Elle yazılır çünkü kayıt fonksiyonunun içine bakarak
	#: çıkarmak (bytecode taraması) kırılgan olurdu.
	metrikler: Tuple[str, ...] = ()
	#: Bench/site gerektiriyor mu — atlandığında bunun beklenen mi yoksa
	#: gerçek bir arıza mı olduğunu rapor ayırt edebilsin.
	bench_gerekir: bool = False


# ── Kayıt fonksiyonları ─────────────────────────────────────────────────
#
# Her biri TEK bir noktanın sözleşmesini uygular ve sonuç nesnesinin
# alanlarına doğrudan bakar. Genel bir "alanları otomatik etiketle"
# mekanizması bilinçli olarak YAZILMADI: otomatik etiketleme, sonuç
# nesnesine yarın eklenen `file_url` alanını sessizce metriğe taşırdı.


def _kayit_policy(c: Cagri) -> None:
	"""`PolicyEngine.evaluate` → yükleme sonucu + politika ihlali."""
	karar = c.sonuc
	slot = _e(getattr(karar, "slot", None) or c.arg(1, "slot"))
	probe = c.arg(2, "probe")
	kind = _e(getattr(probe, "kind", None))
	if c.hata is not None:
		mm.UPLOAD_TOTAL.inc(slot=slot, kind=kind, outcome="error", reason=_e(type(c.hata).__name__))
		return

	kodlar = tuple(getattr(karar, "codes", ()) or ())
	engelleyen = karar.blocking() if hasattr(karar, "blocking") else ()
	outcome = "accepted" if getattr(karar, "allow", False) else "rejected"
	# Sebep: engelleyen ihlal varsa ONUN kodu; yoksa (uyarı düzeyinde ihlal)
	# ilk kod; hiç ihlal yoksa `ok`. "Kabul edildi ama uyarı vardı" durumu
	# `outcome=accepted, reason=<kod>` olarak görünür — bu ayrım kapının ne
	# kadar gergin ayarlandığını gösteren tek sinyal.
	if engelleyen:
		reason = _e(engelleyen[0].code)
	elif kodlar:
		reason = _e(kodlar[0])
	else:
		reason = "ok"
	mm.UPLOAD_TOTAL.inc(slot=slot, kind=kind, outcome=outcome, reason=reason)

	for ihlal in getattr(karar, "violations", ()) or ():
		mm.POLICY_VIOLATION_TOTAL.inc(
			slot=slot, reason=_e(getattr(ihlal, "rule", "")), action=_e(getattr(ihlal, "action", ""))
		)


def _kayit_probe(c: Cagri) -> None:
	"""`image.probe.probe_header` → süre + kaynak boyutu + çözünürlük."""
	p = c.sonuc
	fmt = _e(getattr(p, "detected", None) or getattr(p, "fmt", None))
	mm.IMAGE_PROCESS_DURATION.observe(c.sure_s, op="probe", format=fmt)
	if c.hata is not None:
		return
	boyut = int(getattr(p, "byte_size", 0) or 0)
	if boyut:
		mm.SOURCE_BYTES.observe(boyut, kind="image")
	mp = float(getattr(p, "megapixels", 0.0) or 0.0)
	if mp:
		mm.SOURCE_MEGAPIXELS.observe(mp)


def _kayit_normalize(c: Cagri) -> None:
	"""`image.normalize.normalize` → süre (biçim etiketli)."""
	r = c.sonuc
	fmt = _e(getattr(r, "fmt", None))
	mm.IMAGE_PROCESS_DURATION.observe(c.sure_s, op="normalize", format=fmt)


def _kayit_lqip(c: Cagri) -> None:
	"""`image.lqip.encode` → süre. Biçim sabit: LQIP her zaman ThumbHash."""
	mm.IMAGE_PROCESS_DURATION.observe(c.sure_s, op="lqip", format="thumbhash")


def _kayit_svg(c: Cagri) -> None:
	"""`security.svg.sanitize` → sonuç kodu.

	`slot` bu çağrıda YOKTUR (`sanitize` yalnız içerik + politika alır) ve
	uydurulmaz: `unknown` yazılır. Slot kırılımı isteniyorsa çağıran tarafın
	slotu iletmesi gerekir — bu, sarmalayıcının bilerek kabul ettiği sınır.
	"""
	if c.hata is not None:
		mm.SVG_SANITIZE_TOTAL.inc(slot=BILINMEYEN, code=_e(type(c.hata).__name__))
		return
	mm.SVG_SANITIZE_TOTAL.inc(slot=BILINMEYEN, code=_e(getattr(c.sonuc, "kod", None)))


def _profil_adi(limits: Any) -> str:
	"""`Limits` nesnesini profil adına çevir — `PROFILLER` sözlüğü üzerinden.

	Ters arama, `run_callable(..., limits=IMAGE_LIMITS)` çağrısındaki profili
	çağırana yeni bir argüman EKLEMEDEN kurtarır. Sözlükte yoksa (özel
	`Limits`) `custom` yazılır; `unknown` değil, çünkü bu bir eksik ölçüm
	değil, bilinen bir durumdur.
	"""
	try:
		from ..security import isolation as iso
	except Exception:
		return BILINMEYEN
	if limits is None:
		# `limits` VERİLMEDİ demek "profil bilinmiyor" DEĞİL: `run_callable` ve
		# `run_command` imzalarında varsayılan `IMAGE_LIMITS`tir, yani çağrı
		# gerçekten image profiliyle koştu. `unknown` yazmak, en sık kullanılan
		# yolun tamamını ölçüm dışına atardı.
		limits = iso.IMAGE_LIMITS
	for ad, lim in iso.PROFILLER.items():
		if lim is limits or lim == limits:
			return _e(ad)
	return "custom"


def _kayit_isolation(c: Cagri) -> None:
	"""`security.isolation.run_*` → izole çalıştırma sonucu."""
	profil = _profil_adi(c.kwargs.get("limits"))
	if c.hata is not None:
		mm.ISOLATION_TOTAL.inc(profile=profil, reason=_e(type(c.hata).__name__))
		return
	mm.ISOLATION_TOTAL.inc(profile=profil, reason=_e(getattr(c.sonuc, "sebep", None)))


def _kayit_transcode(c: Cagri) -> None:
	"""`video.transcode.transcode` → süre + sonuç.

	`accepted=False` "hata" değildir (çıktı fayda kapısını geçemedi, kaynak
	korundu). Üç ayrı sonuç etiketi bu yüzden var; ikisini birleştirmek
	"transcode bozuk" alarmını her gereksiz dönüşümde çaldırırdı.
	"""
	if c.hata is not None:
		# Aksiyon adı YALNIZ sonuç nesnesinden okunur. Hata yolunda ilk
		# argümana düşmek cazip ama o `src` DOSYA YOLUDUR — etiket olarak
		# yazmak hem seri patlaması hem `logging.py` PII sözleşmesinin
		# ihlali olurdu.
		mm.VIDEO_TRANSCODE_DURATION.observe(c.sure_s, action=BILINMEYEN, outcome="error")
		return
	aksiyon = _e(getattr(c.sonuc, "action", None))
	outcome = "accepted" if getattr(c.sonuc, "accepted", False) else "rejected"
	mm.VIDEO_TRANSCODE_DURATION.observe(c.sure_s, action=aksiyon, outcome=outcome)


def _kayit_scan(c: Cagri) -> None:
	"""`media/av.py` `scan_path` → tarama durumu (clean/infected/failed)."""
	if c.hata is not None:
		mm.SCAN_TOTAL.inc(status="failed")
		return
	sonuc = c.sonuc
	durum = sonuc[0] if isinstance(sonuc, (tuple, list)) and sonuc else sonuc
	mm.SCAN_TOTAL.inc(status=_e(durum))


def _kayit_audit(c: Cagri) -> None:
	"""`media/audit.py` `log_media_event` → denetim yazımının kendisi.

	Denetim best-effort'tur ve istisna fırlatmaz; yazım sessizce dursa bugün
	hiçbir sinyal yok. Bu sayaç o sinyaldir. Etiketler ÇAĞRI argümanlarından
	okunur (dönüş değeri yalnız kayıt adıdır) — `action` zaten sabit bir
	sözlükten gelir, kardinalite dardır.
	"""
	action = _e(c.kwargs.get("action") or c.arg(0, "action"))
	izinli = c.kwargs.get("allowed", True)
	decision = "allow" if izinli else "deny"
	# Şiddet, ADL'nin kendi kuralının aynası DEĞİL: burada yalnız "reddedildi
	# mi" bilinir. Yanlış bir yeniden hesaplama, iki kaynağın çelişmesinden
	# daha kötü olurdu — bu yüzden yalnız iki değer üretilir.
	severity = "high" if not izinli else "normal"
	mm.AUDIT_EVENT_TOTAL.inc(action=action, decision=decision, severity=severity)


# ── Nokta tablosu ───────────────────────────────────────────────────────
#
# Sıra ANLAMLI DEĞİL ama liste kararlıdır (rapor çıktısı sıralı olsun).

NOKTALAR: Tuple[Nokta, ...] = (
	Nokta(
		ad="policy.evaluate",
		modul="tradehub_core.media.pipeline.policy.engine",
		nitelik="PolicyEngine.evaluate",
		olay="upload.evaluated",
		kayit=_kayit_policy,
		metrikler=("media_upload_total", "media_policy_violation_total"),
	),
	Nokta(
		ad="image.probe",
		modul="tradehub_core.media.pipeline.image.probe",
		nitelik="probe_header",
		olay="image.probed",
		kayit=_kayit_probe,
		metrikler=(
			"media_image_process_duration_seconds",
			"media_source_bytes",
			"media_source_megapixels",
		),
	),
	Nokta(
		ad="image.normalize",
		modul="tradehub_core.media.pipeline.image.normalize",
		nitelik="normalize",
		olay="image.normalized",
		kayit=_kayit_normalize,
		metrikler=("media_image_process_duration_seconds",),
	),
	Nokta(
		ad="image.lqip",
		modul="tradehub_core.media.pipeline.image.lqip",
		nitelik="encode",
		olay="image.lqip",
		kayit=_kayit_lqip,
		metrikler=("media_image_process_duration_seconds",),
	),
	Nokta(
		ad="svg.sanitize",
		modul="tradehub_core.media.pipeline.security.svg",
		nitelik="sanitize",
		olay="svg.sanitized",
		kayit=_kayit_svg,
		metrikler=("media_svg_sanitize_total",),
	),
	Nokta(
		ad="isolation.run_callable",
		modul="tradehub_core.media.pipeline.security.isolation",
		nitelik="run_callable",
		olay="image.isolated",
		kayit=_kayit_isolation,
		metrikler=("media_isolation_total",),
	),
	Nokta(
		ad="isolation.run_command",
		modul="tradehub_core.media.pipeline.security.isolation",
		nitelik="run_command",
		olay="command.isolated",
		kayit=_kayit_isolation,
		metrikler=("media_isolation_total",),
	),
	Nokta(
		ad="video.transcode",
		modul="tradehub_core.media.pipeline.video.transcode",
		nitelik="transcode",
		olay="video.transcoded",
		kayit=_kayit_transcode,
		metrikler=("media_video_transcode_duration_seconds",),
	),
	Nokta(
		ad="av.scan_path",
		modul="tradehub_core.media.av",
		nitelik="scan_path",
		olay="media.scanned",
		kayit=_kayit_scan,
		metrikler=("media_scan_total",),
		bench_gerekir=True,
	),
	Nokta(
		ad="audit.log_media_event",
		modul="tradehub_core.media.audit",
		nitelik="log_media_event",
		olay="media.audited",
		kayit=_kayit_audit,
		metrikler=("media_audit_event_total",),
		bench_gerekir=True,
	),
)

#: Hiçbir ölçüm noktasının yazmadığı, TOPLAYICI gerektiren metrikler. Liste
#: bir eksiklik itirafıdır ve `metrik_kapsami()` ile sayısal olarak
#: doğrulanır: bunlar periyodik bir işin (envanter taraması, PII haritası
#: denetimi) yazması gereken göstergelerdir, çağrı yolunda üretilmezler.
TOPLAYICI_GEREKTIREN: Tuple[str, ...] = (
	"media_storage_bytes",
	"media_storage_objects",
	"media_orphan_files",
	"media_pii_field_coverage",
	"media_pii_unprotected_files",
	"media_bytes_saved_total",
)

#: Nokta tablosunun DIŞINDA, ama yine de bu depoda yazanı OLAN metrikler.
#: Ayrı tutuluyorlar çünkü "yazanı yok" ile "yazanı başka yerde" aynı şey
#: değil; birleştirmek `metrik_kapsami()`nin açık-eksik sayısını yalanlardı.
NOKTA_DISI_YAZILAN: Dict[str, str] = {
	# Sarmalayıcının kendi hata sayacı — `_kaydet()` yazar.
	"media_instrumentation_errors_total": "observability/instrument.py::_kaydet",
	# Kuyruk işi sonucu — iş TERMİNAL olduğunda çağrı yerinde yazılır (K-1).
	# `media/runner.py` batch işlerini (optimize/restore) `jobs.record_terminal`
	# ile sayar; retry'lı işler (transcode/av) henüz bağlanmadı (rapora bkz.).
	"media_job_total": "media/jobs.py::record_terminal (media/runner.py çağırır)",
	"media_job_attempts": "media/jobs.py::record_terminal (media/runner.py çağırır)",
	# RUM köprüsü — `delivery/rum.py::to_metrics()` yazar.
	"media_rum_p75_milliseconds": "delivery/rum.py::to_metrics",
	"media_rum_cls_p75": "delivery/rum.py::to_metrics",
	"media_rum_samples_total": "delivery/rum.py::to_metrics",
	"media_rum_estimated_population": "delivery/rum.py::to_metrics",
	"media_rum_rejected_total": "delivery/rum.py::reject_reason",
}


# ── Kurulum ─────────────────────────────────────────────────────────────

#: Sarmalayıcıyı işaretleyen nitelik — iki kez kurulumu ve yabancı bir
#: sarmalayıcıyı kaldırmayı ayırt eder.
_ISARET: str = "__media_engine_nokta__"

_KILIT = threading.Lock()
#: ad → (sahip nesne, nitelik adı, orijinal çağrılabilir)
_KURULU: Dict[str, Tuple[Any, str, Callable]] = {}


@dataclass
class KurulumRaporu:
	"""`install()` sonucunun künyesi — sayılarla, tahminle değil."""

	bagli: Tuple[str, ...] = ()
	zaten_bagli: Tuple[str, ...] = ()
	atlanan: Tuple[Tuple[str, str], ...] = ()

	@property
	def toplam(self) -> int:
		return len(self.bagli) + len(self.zaten_bagli) + len(self.atlanan)

	@property
	def kapsam(self) -> float:
		"""Bağlanan nokta oranı (0-1). Bölme sıfıra karşı korunur."""
		return (len(self.bagli) + len(self.zaten_bagli)) / self.toplam if self.toplam else 0.0

	def to_dict(self) -> Dict[str, Any]:
		return {
			"bound": list(self.bagli),
			"already_bound": list(self.zaten_bagli),
			"skipped": [{"point": a, "reason": s} for a, s in self.atlanan],
			"total": self.toplam,
			"coverage": round(self.kapsam, 4),
		}


def _coz(nokta: Nokta) -> Tuple[Any, str, Callable]:
	"""(sahip, nitelik adı, orijinal) — bulunamazsa `LookupError`."""
	modul = importlib.import_module(nokta.modul)
	parcalar = nokta.nitelik.split(".")
	sahip: Any = modul
	for ara in parcalar[:-1]:
		sahip = getattr(sahip, ara)
	son = parcalar[-1]
	if not hasattr(sahip, son):
		raise LookupError("attribute_missing")
	orijinal = getattr(sahip, son)
	if not callable(orijinal):
		raise LookupError("not_callable")
	return sahip, son, orijinal


def _sar(nokta: Nokta, orijinal: Callable) -> Callable:
	"""Ölçen sarmalayıcı. İstisnayı YUTMAZ, süreyi her hâlükârda yazar."""

	@functools.wraps(orijinal)
	def sarmalayici(*args: Any, **kwargs: Any) -> Any:
		t0 = time.perf_counter()
		try:
			sonuc = orijinal(*args, **kwargs)
		except BaseException as hata:  # noqa: BLE001 - yeniden fırlatılıyor
			_kaydet(nokta, Cagri(args, kwargs, None, hata, time.perf_counter() - t0))
			raise
		_kaydet(nokta, Cagri(args, kwargs, sonuc, None, time.perf_counter() - t0))
		return sonuc

	setattr(sarmalayici, _ISARET, nokta.ad)
	setattr(sarmalayici, "__media_engine_orijinal__", orijinal)
	return sarmalayici


def _kaydet(nokta: Nokta, cagri: Cagri) -> None:
	"""Kayıt fonksiyonunu KORUMALI çağır — ölçüm, ölçtüğü işi düşüremez."""
	try:
		nokta.kayit(cagri)
	except Exception:
		try:
			mm.INSTRUMENT_ERRORS_TOTAL.inc(point=nokta.ad)
		except Exception:
			# Sayaç bile yazılamıyorsa yapacak bir şey yok; burada bir
			# istisna kaçırmak, ölçümün çağıranı düşürmesi demek olurdu.
			pass
		return
	# Hata yolunda TEK bir yapılandırılmış olay yazılır. Başarı yolunda
	# yazılmaz: her başarılı probe için bir satır, log hacmini ölçtüğümüz
	# işten büyük yapardı (4.958 dosya × 5 adım).
	if cagri.hata is not None:
		mlog.log_event(
			f"{nokta.olay}.failed",
			level=40,
			error_type=type(cagri.hata).__name__,
			duration_ms=int(cagri.sure_s * 1000),
			point=nokta.ad,
		)


def install(noktalar: Sequence[Nokta] = NOKTALAR) -> KurulumRaporu:
	"""Ölçüm noktalarını bağla. Tekrar çağırmak GÜVENLİDİR (idempotent).

	Bağlanamayan nokta bir hata DEĞİLDİR: `media/av.py` ve `media/audit.py`
	`import frappe` yapar ve bench dışında yüklenemez. Rapor bunu `skipped`
	altında sebebiyle döndürür — sessizce eksik ölçmek yerine, neyin
	ölçülmediğini söylemek.
	"""
	bagli: List[str] = []
	zaten: List[str] = []
	atlanan: List[Tuple[str, str]] = []
	with _KILIT:
		for nokta in noktalar:
			if nokta.ad in _KURULU:
				zaten.append(nokta.ad)
				continue
			try:
				sahip, ad, orijinal = _coz(nokta)
			except LookupError as e:
				atlanan.append((nokta.ad, str(e)))
				continue
			except Exception as e:
				atlanan.append((nokta.ad, f"module_missing:{type(e).__name__}"))
				continue
			if getattr(orijinal, _ISARET, None):
				# Başka bir kurulum turu (ya da başka bir süreçte paylaşılan
				# modül nesnesi) zaten sarmış; iki kat sarmak her çağrıyı iki
				# kez sayardı.
				zaten.append(nokta.ad)
				continue
			setattr(sahip, ad, _sar(nokta, orijinal))
			_KURULU[nokta.ad] = (sahip, ad, orijinal)
			bagli.append(nokta.ad)
	return KurulumRaporu(tuple(bagli), tuple(zaten), tuple(atlanan))


def uninstall() -> Tuple[str, ...]:
	"""Bütün sarmalayıcıları kaldır, orijinalleri geri koy.

	Test izolasyonu için ZORUNLU: sarmalayıcı süreç ömrü boyunca kalır ve
	bir sonraki testin sayaçlarına karışır.
	"""
	kaldirilan: List[str] = []
	with _KILIT:
		for ad, (sahip, nitelik, orijinal) in list(_KURULU.items()):
			mevcut = getattr(sahip, nitelik, None)
			# Yalnız KENDİ sarmalayıcımızı kaldır: araya başka bir sarmalayıcı
			# girmişse onu ezmek, o katmanı sessizce yok etmek olurdu.
			if getattr(mevcut, _ISARET, None) == ad:
				setattr(sahip, nitelik, orijinal)
				kaldirilan.append(ad)
			_KURULU.pop(ad, None)
	return tuple(kaldirilan)


def kurulu_mu(ad: str) -> bool:
	with _KILIT:
		return ad in _KURULU


def durum() -> Dict[str, Any]:
	"""Şu an bağlı olan noktalar — sağlık ucu ve rapor için."""
	with _KILIT:
		bagli = sorted(_KURULU)
	return {
		"points_total": len(NOKTALAR),
		"points_bound": len(bagli),
		"bound": bagli,
		"bench_only": [n.ad for n in NOKTALAR if n.bench_gerekir],
	}


def metrik_kapsami(registry: Optional[mm.Registry] = None) -> Dict[str, Any]:
	"""Hangi metriğin yazanı var, hangisinin yok — SAYIYLA.

	T-133'ün "ölçüm noktaları" kabul kriterinin tek dürüst cevabı bu
	fonksiyondur: metrik tanımlamak ile metriği DOLDURMAK ayrı şeylerdir ve
	tanımlı-ama-boş bir seri, panelde "sorun yok" gibi görünür.
	"""
	kayit = registry or mm.REGISTRY
	tanimli = {m.ad for m in kayit.metrikler()}
	yazilan = {ad for nokta in NOKTALAR for ad in nokta.metrikler}
	toplayici = set(TOPLAYICI_GEREKTIREN)
	disarida = set(NOKTA_DISI_YAZILAN)
	yazani_yok = sorted(tanimli - yazilan - disarida)
	return {
		"defined": len(tanimli),
		"written_by_points": len(yazilan & tanimli),
		"written_elsewhere": sorted(disarida & tanimli),
		"needs_collector": sorted(toplayici & tanimli),
		"no_writer": yazani_yok,
		# Ne nokta yazıyor, ne toplayıcı bekleniyor, ne de başka bir yazanı
		# var — yani gerçekten SAHİPSİZ. Bu listenin boş olmaması bir açıktır.
		"unaccounted": sorted(set(yazani_yok) - toplayici),
	}


__all__ = [
	"BILINMEYEN",
	"MAX_ETIKET_UZUNLUK",
	"NOKTALAR",
	"NOKTA_DISI_YAZILAN",
	"TOPLAYICI_GEREKTIREN",
	"Cagri",
	"KurulumRaporu",
	"Nokta",
	"durum",
	"install",
	"kurulu_mu",
	"metrik_kapsami",
	"uninstall",
]
