"""T-130 — alt süreç izolasyonu: bellek / CPU / duvar saati limiti.

SORUN
=====
Medya işleri bugün worker'ın KENDİ süreci içinde çalışıyor:

    tradehub_core/media/runner.py     Pillow `optimize()` doğrudan çağrılıyor
    tradehub_core/media/pipeline.py     `Image.open(...)` — süreç içinde decode
    tradehub_core/media/av.py:484     `subprocess.run(..., timeout=120)`
    tradehub_core/media/transcode.py  `subprocess.run(..., timeout=1700)`

Alt iki satır zaten alt süreç kullanıyor ve zaman aşımı koyuyor; ama BELLEK
sınırı hiçbirinde yok. Üst iki satırda ne alt süreç var ne de sınır: bir
dekompresyon bombası (`tradehub_core/tests/fixtures/malicious/bomb_100mp.png`, 97 KB dosya →
100 MP piksel) worker'ın adres alanını doldurur, Linux OOM killer RQ worker
sürecini öldürür ve KUYRUKTAKİ DİĞER İŞLER de gider. Tek bozuk dosya, tüm
medya hattını durdurur.

Bu modülün sözleşmesi tek cümledir:

    **Başarısız iş, worker'ı öldürmez.**

Her genel fonksiyon SONUÇ NESNESİ döndürür; hiçbiri istisna fırlatmaz. Çağıran
`sonuc.ok` bakar, `sonuc.sebep` ile kuyruk kararını verir.

ÖLÇÜM — limitler nereden geldi
==============================
Canlı envanter (2026-08-18, 4.958 dosya): MP p50=1,56 · p90=5,01 · p99=29,21 ·
MAX=72,71. Bu makinede (macOS, Pillow 11.3.0, python3) `engine.optimize()`
süresi ve kümülatif tepe RSS'i ölçüldü:

| MP    | mod  | kaynak   | süre    | kümülatif tepe RSS |
|-------|------|----------|---------|--------------------|
| 1,56  | RGB  |  0,77 MB | 0,07 s  |    41,8 MB         |
| 5,01  | RGB  |  2,49 MB | 0,23 s  |   116,3 MB         |
| 29,21 | RGB  | 14,56 MB | 0,58 s  |   407,4 MB         |
| 72,71 | RGB  | 36,31 MB | 1,05 s  |   947,5 MB         |
| 29,21 | CMYK | 46,03 MB | 0,85 s  | 1.001,8 MB         |

(RSS `ru_maxrss` kümülatiftir — satırlar birbirinin üstüne biner, tek işin
tepe değeri DEĞİLDİR; üst sınır olarak okunmalı.)

Buradan:
  * `IMAGE_LIMITS.address_space_bytes = 1,5 GB` — en büyük GERÇEK dosyanın
    (72,71 MP) ölçülen tepesinin ~1,6 katı. Daha dar bir sınır bugün çalışan
    dosyaları keserdi; daha geniş bir sınır bombayı durdurmazdı.
  * `IMAGE_LIMITS.wall_timeout_s = 60` — ölçülen en kötü sürenin (1,05 s) ~57
    katı. Zaman aşımı "yavaş dosyayı" değil "takılmış işi" yakalamak içindir;
    yüklü worker'da 50 kat pay bilinçli.
  * `cpu_seconds < wall_timeout_s` — sonsuz DÖNGÜ önce CPU limitine takılır
    (SIGXCPU, temiz sinyal); duvar saati ise I/O'da BLOKE kalmış işi yakalar.
    İkisi farklı arızadır, ikisi de gerekir.

MEVCUT MERDİVENE UYUM (yeniden yazılmadı, hizalandı)
====================================================
    ffprobe    20 s   tradehub_core/media/pipeline/contracts/video.py:42
    clamdscan 120 s   tradehub_core/media/av.py:126
    ffmpeg   1700 s   tradehub_core/media/pipeline/contracts/video.py:43
    kuyruk   1800 s   RQ
    kayıp    2700 s   tradehub_core/media/jobs.py STALE_AFTER_SECONDS

Bu modül o sayıları YENİDEN TANIMLAMAZ; `VIDEO_LIMITS` / `SCAN_LIMITS`
onları içeri alır (import edilebiliyorsa) ve yalnız BELLEK + duvar saati
sertleştirmesini ekler. Ayrışma testle yakalanır.

İKİ GİRİŞ, İKİ TEHDİT MODELİ
============================
    run_command()    Harici ikili (ffmpeg/ffprobe/clamdscan). Güven sınırı
                     zaten süreç sınırı; eklenen tek şey rlimit + süreç
                     GRUBU öldürme (ffmpeg alt süreç doğurur, `kill(pid)`
                     yetmez).
    run_callable()   Python çağrılabiliri (Pillow decode). `fork()` ile
                     ayrı sürece alınır. Buradaki kazanç büyük: bugün worker'ı
                     öldüren bomba artık yalnız çocuğu öldürür.

`run_callable` NEDEN `multiprocessing` DEĞİL
============================================
`multiprocessing` "spawn" başlangıç yöntemi çağrılabilirin İMPORT EDİLEBİLİR
olmasını ister (modül düzeyinde tanımlı); testlerdeki yerel fonksiyonlar ve
`functools.partial` sarmalları bu koşulu sağlamaz. "fork" yöntemi ise havuz
yönetimi, semafor ve atexit makinesi getirir — worker'ın RQ bağlamında hepsi
fazladan risk. Burada ham `os.fork()` + tek yönlü boru kullanılıyor:

  * çocuk `os._exit()` ile biter → ebeveynin `atexit` kancaları, açık DB
    soketleri, buffer'ları ÇALIŞTIRILMAZ/FLUSH EDİLMEZ (çift commit riski yok),
  * çocuk `os.setsid()` ile yeni oturuma geçer → grup olarak öldürülebilir,
  * dönüş değeri pickle ile borudan geçer, boyutu `max_output_bytes` ile
    sınırlıdır.

**UYARI — thread'li süreçte fork.** `fork()` yalnız çağıran thread'i kopyalar;
kilidini başka bir thread'in tuttuğu bir kilit çocukta SONSUZA KADAR kilitli
kalır. RQ worker'ı tek thread'lidir, gunicorn/web süreci DEĞİLDİR. Bu yüzden
`run_callable` KUYRUK bağlamı içindir; istek içinde kullanılmamalıdır
(`allow_fork=False` ile kapatılabilir, o zaman `SEBEP_UNSUPPORTED` döner).

**UYARI — `preexec_fn`.** `subprocess`'in `preexec_fn` parametresi thread-safe
değildir (CPython belgesi). Aynı gerekçeyle `run_command` da kuyruk bağlamı
içindir. Sınır uygulanamıyorsa iş yine çalışır, `limits_applied` boş döner ve
`uyarilar` alanına neden yazılır — güvenlik sertleştirmesi yüzünden çalışan
hattı durdurmak, koruduğundan çok zarar verirdi.
"""

from __future__ import annotations

import os
import pickle
import select
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

try:  # pragma: no cover - POSIX dışında (Windows) yok
	import resource as _resource

	RESOURCE_AVAILABLE: bool = True
except Exception:  # pragma: no cover
	_resource = None  # type: ignore[assignment]
	RESOURCE_AVAILABLE = False

FORK_AVAILABLE: bool = hasattr(os, "fork")

# ── Sebep kodları ───────────────────────────────────────────────────────
#
# `contracts/errors.py` sözleşmesiyle aynı desen: makine okur, çağıran karar
# verir. `retryable` bilgisi burada TABLO olarak duruyor çünkü kuyruk kararı
# (yeniden dene / dead-letter) bu ayrıma bağlı:
#
#   timeout / killed   → geçici olabilir (yüklü makine, OOM killer) → DENE
#   memory / cpu       → dosyanın kendisi çok büyük → aynı dosya aynı sonuç → DENEME
#   exit / exception   → içerik hatası → DENEME
#   spawn_failed       → ikili yok / fd tükendi → sistem arızası → DENE

SEBEP_OK: str = "ok"
SEBEP_TIMEOUT: str = "isolation_timeout"
SEBEP_MEMORY: str = "isolation_memory"
SEBEP_CPU: str = "isolation_cpu"
SEBEP_KILLED: str = "isolation_killed"
SEBEP_EXIT: str = "isolation_exit"
SEBEP_EXCEPTION: str = "isolation_exception"
SEBEP_SPAWN_FAILED: str = "isolation_spawn_failed"
SEBEP_OUTPUT_TOO_LARGE: str = "isolation_output_too_large"
SEBEP_UNSUPPORTED: str = "isolation_unsupported"

RETRYABLE_SEBEPLER: frozenset = frozenset(
	{SEBEP_TIMEOUT, SEBEP_KILLED, SEBEP_SPAWN_FAILED}
)

#: Çocuk sürecin ayrılmış çıkış kodları. 1-125 aralığı harici ikililerin
#: kendi kodlarına aittir; 120+ aralığı burada da kabuk (126/127) ile
#: çakışmayacak şekilde seçildi.
EXIT_EXCEPTION: int = 120
EXIT_MEMORY: int = 121
EXIT_PICKLE: int = 122

#: `SIGXCPU` RLIMIT_CPU YUMUŞAK sınırına basıldığında gelir. Sert sınır
#: yumuşaktan `CPU_HARD_GRACE_SECONDS` fazladır: süreç SIGXCPU'yu yakalayıp
#: temiz kapanmaya çalışırsa şansı olsun, çalışmazsa çekirdek SIGKILL'i bassın.
CPU_HARD_GRACE_SECONDS: int = 5

#: Zaman aşımında SIGTERM ile SIGKILL arasındaki bekleme. ffmpeg SIGTERM'de
#: yarım dosyayı kapatıp çıkar; hemen SIGKILL basmak geçici dosyayı ortada
#: bırakırdı.
TERM_GRACE_SECONDS: float = 3.0


def _mb(n: float) -> int:
	return int(n * 1024 * 1024)


@dataclass(frozen=True)
class Limits:
	"""Tek bir izole çalıştırmanın kaynak tavanı.

	Alanların `None` olması "sınır koyma" demektir — sistemin varsayılanı
	geçerli kalır. Sıfır DEĞİL: `RLIMIT_CORE=0` gerçek bir sınırdır (core
	dump yazma), `None` ise hiç dokunmamaktır.
	"""

	#: Duvar saati. I/O'da BLOKE kalmış işi yakalar (CPU limiti yakalayamaz).
	wall_timeout_s: float = 60.0
	#: RLIMIT_CPU (saniye, yumuşak). Sonsuz DÖNGÜ'yü yakalar.
	cpu_seconds: Optional[int] = 45
	#: RLIMIT_AS (bayt). Dekompresyon bombasının tek gerçek durdurucusu.
	address_space_bytes: Optional[int] = _mb(1536)
	#: RLIMIT_FSIZE (bayt). Diski dolduran çıktıya karşı.
	file_size_bytes: Optional[int] = _mb(512)
	#: RLIMIT_NOFILE. fd sızdıran ikiliye karşı.
	open_files: Optional[int] = 256
	#: RLIMIT_CORE. 0 = core dump YOK (bellek dökümü PII taşır — NFR/KVKK).
	core_bytes: Optional[int] = 0
	#: `nice` değeri. Transcode hattından korunuyor (transcode.py:349): medya
	#: işi CPU-yoğun, sipariş/ödeme kuyruklarını aç bırakmamalı.
	nice: Optional[int] = 10
	#: stdout+stderr / pickle sonucu için tavan. Aşılırsa çıktı KIRPILIR ve
	#: sebep `isolation_output_too_large` olur — ebeveynin belleğini çocuğun
	#: çıktısıyla doldurmak, izolasyonun amacını tersine çevirirdi.
	max_output_bytes: int = _mb(8)

	def with_(self, **degisiklik: Any) -> "Limits":
		"""Tek alan değiştirilmiş kopya — `dataclasses.replace` sarmalı."""
		from dataclasses import replace

		return replace(self, **degisiklik)


# ── Hazır profiller ─────────────────────────────────────────────────────
#
# Video ve tarama süreleri MEVCUT koddan alınır (yeniden tanımlanmaz); import
# edilemezse aşağıdaki ayna kullanılır ve `tests/test_isolation.py` ayrışmayı
# düşürür.

_AYNA = {"FFPROBE_TIMEOUT_SECONDS": 20, "FFMPEG_TIMEOUT_SECONDS": 1700, "SCAN_TIMEOUT_SECONDS": 120}

try:  # pragma: no cover - paket yolu varsa bu dal çalışır
	from tradehub_core.media.pipeline.contracts.video import FFMPEG_TIMEOUT_SECONDS, FFPROBE_TIMEOUT_SECONDS

	UPSTREAM_VIDEO_AVAILABLE: bool = True
except Exception:  # pragma: no cover
	FFPROBE_TIMEOUT_SECONDS = _AYNA["FFPROBE_TIMEOUT_SECONDS"]
	FFMPEG_TIMEOUT_SECONDS = _AYNA["FFMPEG_TIMEOUT_SECONDS"]
	UPSTREAM_VIDEO_AVAILABLE = False

SCAN_TIMEOUT_SECONDS: int = _AYNA["SCAN_TIMEOUT_SECONDS"]

#: Görsel işleme (Pillow decode/encode). Ölçüm gerekçesi modül başlığında.
IMAGE_LIMITS: Limits = Limits(
	wall_timeout_s=60.0,
	cpu_seconds=45,
	address_space_bytes=_mb(1536),
	file_size_bytes=_mb(512),
)

#: ffprobe — yalnız başlık okur, bellek ihtiyacı küçük, süre kısa.
PROBE_LIMITS: Limits = Limits(
	wall_timeout_s=float(FFPROBE_TIMEOUT_SECONDS),
	cpu_seconds=max(5, FFPROBE_TIMEOUT_SECONDS - 5),
	address_space_bytes=_mb(512),
	file_size_bytes=_mb(16),
	max_output_bytes=_mb(4),
)

#: ffmpeg — uzun ve bellek-yoğun. CPU limiti duvar saatinden AZ konur; aşırı
#: paralel çekirdek kullanımı da böylece kendiliğinden sınırlanır.
VIDEO_LIMITS: Limits = Limits(
	wall_timeout_s=float(FFMPEG_TIMEOUT_SECONDS),
	cpu_seconds=FFMPEG_TIMEOUT_SECONDS,
	address_space_bytes=_mb(3072),
	file_size_bytes=_mb(2048),
	max_output_bytes=_mb(4),
)

#: clamdscan — imza eşleştirmesi; süre av.py'deki `_SCAN_TIMEOUT_SECONDS`.
SCAN_LIMITS: Limits = Limits(
	wall_timeout_s=float(SCAN_TIMEOUT_SECONDS),
	cpu_seconds=max(5, SCAN_TIMEOUT_SECONDS - 10),
	address_space_bytes=_mb(1024),
	file_size_bytes=_mb(64),
	max_output_bytes=_mb(1),
)

PROFILLER: Dict[str, Limits] = {
	"image": IMAGE_LIMITS,
	"probe": PROBE_LIMITS,
	"video": VIDEO_LIMITS,
	"scan": SCAN_LIMITS,
}


@dataclass
class IsolationResult:
	"""İzole çalıştırmanın sonucu. **Bu nesne istisna YERİNE geçer.**"""

	ok: bool
	sebep: str = SEBEP_OK
	exit_code: Optional[int] = None
	signal_no: Optional[int] = None
	duration_ms: int = 0
	stdout: bytes = b""
	stderr: bytes = b""
	#: `run_callable` için çağrılabilirin dönüş değeri (`ok=True` ise anlamlı).
	value: Any = None
	#: Çocukta yakalanan istisnanın künyesi — `{"type", "message"}`.
	exception: Optional[Dict[str, str]] = None
	#: Gerçekten UYGULANABİLEN rlimit adları. Boşsa sertleştirme YOK demektir.
	limits_applied: List[str] = field(default_factory=list)
	#: Sınır uygulanamadıysa ya da çıktı kırpıldıysa buraya yazılır.
	uyarilar: List[str] = field(default_factory=list)

	@property
	def retryable(self) -> bool:
		"""Kuyruk bu işi tekrar denemeli mi (bkz. sebep tablosu)."""
		return self.sebep in RETRYABLE_SEBEPLER

	@property
	def timed_out(self) -> bool:
		return self.sebep == SEBEP_TIMEOUT

	def to_dict(self) -> Dict[str, Any]:
		"""Log/metrik için düz sözlük — ham çıktı DEĞİL, yalnız uzunluğu.

		stdout/stderr bilinçli olarak dışarıda: ffmpeg hata metni dosya YOLU
		içerir, log'a ham yol yazmak PII maskeleme sözleşmesini deler
		(`observability/logging.py`).
		"""
		return {
			"ok": self.ok,
			"reason": self.sebep,
			"exit_code": self.exit_code,
			"signal": self.signal_no,
			"duration_ms": self.duration_ms,
			"stdout_bytes": len(self.stdout),
			"stderr_bytes": len(self.stderr),
			"retryable": self.retryable,
			"limits_applied": list(self.limits_applied),
			"warnings": list(self.uyarilar),
		}


# ── rlimit uygulama ─────────────────────────────────────────────────────


def _rlimit_ciftleri(limits: Limits) -> List[Tuple[str, int, int]]:
	"""`(resource adı, yumuşak, sert)` üçlüleri. Saf fonksiyon — test edilebilir."""
	ciftler: List[Tuple[str, int, int]] = []
	if limits.cpu_seconds is not None:
		yumusak = max(1, int(limits.cpu_seconds))
		ciftler.append(("RLIMIT_CPU", yumusak, yumusak + CPU_HARD_GRACE_SECONDS))
	if limits.address_space_bytes is not None:
		v = int(limits.address_space_bytes)
		ciftler.append(("RLIMIT_AS", v, v))
	if limits.file_size_bytes is not None:
		v = int(limits.file_size_bytes)
		ciftler.append(("RLIMIT_FSIZE", v, v))
	if limits.open_files is not None:
		v = int(limits.open_files)
		ciftler.append(("RLIMIT_NOFILE", v, v))
	if limits.core_bytes is not None:
		v = int(limits.core_bytes)
		ciftler.append(("RLIMIT_CORE", v, v))
	return ciftler


def apply_limits(limits: Limits) -> List[str]:
	"""**Çocuk süreçte** çalışır: rlimit'leri uygular, `nice` değerini düşürür.

	Uygulanabilenlerin adını döndürür. **Hiçbir koşulda istisna fırlatmaz** —
	bu fonksiyon `fork()` ile `exec()` arasında çalışır; orada bir istisna,
	çocuğun ebeveynin traceback makinesini çalıştırması demektir.

	**TUZAK — bunu ebeveynde ÇAĞIRMAYIN.** Fonksiyon çağrıldığı sürece etki
	eder; worker'ın içinde çağrılırsa worker'ın KENDİ limitleri düşer ve
	rlimit'in sert sınırı geri yükseltilemez (POSIX). Bu testi yazarken
	yaşandı: `open_files=0` ile ebeveynde çağrılan bir satır, koşucunun
	dosya tanıtıcı hakkını sıfırladı ve sonraki beş test
	`OSError: [Errno 24] Too many open files` ile düştü. Doğru kullanım
	`run_callable` / `limit_preexec` üzerindendir; ikisi de çocuk tarafında
	çağırır.

	Sert sınırı düşürmek geri alınamaz (POSIX): bu yüzden yalnız MEVCUT sert
	sınırdan küçük değerler yazılır, büyütme denemesi sessizce atlanır.
	"""
	uygulanan: List[str] = []
	if not RESOURCE_AVAILABLE:
		return uygulanan

	for ad, yumusak, sert in _rlimit_ciftleri(limits):
		kaynak = getattr(_resource, ad, None)
		if kaynak is None:  # platformda yok (örn. bazı BSD'lerde RLIMIT_AS)
			continue
		try:
			mevcut_y, mevcut_s = _resource.getrlimit(kaynak)
			hedef_s = sert if mevcut_s == _resource.RLIM_INFINITY else min(sert, mevcut_s)
			hedef_y = min(yumusak, hedef_s) if hedef_s != _resource.RLIM_INFINITY else yumusak
			if mevcut_y != _resource.RLIM_INFINITY and mevcut_y < hedef_y:
				# Zaten daha sıkı — dokunma.
				uygulanan.append(ad)
				continue
			_resource.setrlimit(kaynak, (hedef_y, hedef_s))
			uygulanan.append(ad)
		except Exception:
			continue

	if limits.nice is not None:
		try:
			os.nice(int(limits.nice))
			uygulanan.append("nice")
		except Exception:
			pass
	return uygulanan


def limit_preexec(limits: Limits) -> Callable[[], None]:
	"""`subprocess(preexec_fn=...)` için kapama.

	Yeni bir OTURUM açar (`os.setsid`): ffmpeg/clamdscan alt süreç doğurur;
	zaman aşımında yalnız `pid`'i öldürmek torunları arkada bırakır ve dosya
	kilitli kalır. Oturum kimliği = süreç grubu olduğu için `killpg` tek
	çağrıda ağacın tamamını alır.
	"""

	def _pre() -> None:  # pragma: no cover - yalnız çocuk süreçte çalışır
		try:
			os.setsid()
		except Exception:
			pass
		apply_limits(limits)

	return _pre


# ── Harici süreç ────────────────────────────────────────────────────────


def _oldur(pid: int, *, grup: bool = True) -> None:
	"""SIGTERM → bekle → SIGKILL. Zaten ölmüşse sessizce geçer."""
	for sig, bekle in ((signal.SIGTERM, TERM_GRACE_SECONDS), (signal.SIGKILL, 0.0)):
		try:
			if grup:
				os.killpg(os.getpgid(pid), sig)
			else:
				os.kill(pid, sig)
		except Exception:
			return
		if bekle <= 0:
			return
		son = time.monotonic() + bekle
		while time.monotonic() < son:
			try:
				bitti, _ = os.waitpid(pid, os.WNOHANG)
			except Exception:
				return
			if bitti == pid:
				return
			time.sleep(0.05)


def _sinifla(exit_code: Optional[int], signal_no: Optional[int], zaman_asimi: bool) -> str:
	"""Çıkış kodu + sinyalden sebep türet."""
	if zaman_asimi:
		return SEBEP_TIMEOUT
	if signal_no is not None:
		if signal_no == getattr(signal, "SIGXCPU", -1):
			return SEBEP_CPU
		if signal_no == getattr(signal, "SIGXFSZ", -1):
			return SEBEP_EXIT
		return SEBEP_KILLED
	if exit_code == EXIT_MEMORY:
		return SEBEP_MEMORY
	if exit_code in (EXIT_EXCEPTION, EXIT_PICKLE):
		return SEBEP_EXCEPTION
	if exit_code:
		return SEBEP_EXIT
	return SEBEP_OK


def run_command(
	argv: Sequence[str],
	*,
	limits: Limits = IMAGE_LIMITS,
	stdin_data: Optional[bytes] = None,
	env: Optional[Mapping[str, str]] = None,
	cwd: Optional[str] = None,
	use_preexec: bool = True,
) -> IsolationResult:
	"""Harici ikiliyi rlimit + süreç grubu izolasyonunda çalıştır.

	`subprocess.run(..., timeout=…)` üzerine iki şey ekler:
	  1. rlimit (bellek/CPU/dosya boyutu/core dump) — bugün HİÇBİR yerde yok,
	  2. zaman aşımında süreç GRUBUNU öldürme — `subprocess`'in kendi
	     `TimeoutExpired` yolu yalnız doğrudan çocuğu öldürür, ffmpeg'in
	     doğurduğu torunlar arkada kalır.

	İstisna fırlatmaz; ikili bulunamazsa `SEBEP_SPAWN_FAILED` döner.
	"""
	baslangic = time.monotonic()
	uyarilar: List[str] = []
	if not argv:
		return IsolationResult(
			ok=False, sebep=SEBEP_SPAWN_FAILED, uyarilar=["bos_komut"], duration_ms=0
		)

	pre = None
	if use_preexec and hasattr(os, "fork"):
		pre = limit_preexec(limits)
	else:
		uyarilar.append("preexec_kapali_sinir_uygulanmadi")

	try:
		surec = subprocess.Popen(  # noqa: S603 - argv listesi, shell YOK
			list(argv),
			stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			preexec_fn=pre,  # noqa: PLW1509 - gerekçe modül başlığında
			cwd=cwd,
			env=dict(env) if env is not None else None,
			close_fds=True,
			start_new_session=pre is None,
		)
	except Exception as exc:  # ikili yok, izin yok, fd tükendi…
		return IsolationResult(
			ok=False,
			sebep=SEBEP_SPAWN_FAILED,
			duration_ms=int((time.monotonic() - baslangic) * 1000),
			exception={"type": type(exc).__name__, "message": str(exc)[:300]},
			uyarilar=uyarilar,
		)

	zaman_asimi = False
	try:
		out, err = surec.communicate(input=stdin_data, timeout=limits.wall_timeout_s)
	except subprocess.TimeoutExpired:
		zaman_asimi = True
		_oldur(surec.pid, grup=True)
		try:
			out, err = surec.communicate(timeout=TERM_GRACE_SECONDS + 2)
		except Exception:
			out, err = b"", b""
	except Exception as exc:
		_oldur(surec.pid, grup=True)
		return IsolationResult(
			ok=False,
			sebep=SEBEP_SPAWN_FAILED,
			duration_ms=int((time.monotonic() - baslangic) * 1000),
			exception={"type": type(exc).__name__, "message": str(exc)[:300]},
			uyarilar=uyarilar,
		)

	out = out or b""
	err = err or b""
	if len(out) > limits.max_output_bytes:
		out = out[: limits.max_output_bytes]
		uyarilar.append("stdout_kirpildi")
	if len(err) > limits.max_output_bytes:
		err = err[: limits.max_output_bytes]
		uyarilar.append("stderr_kirpildi")

	rc = surec.returncode
	sinyal = -rc if (rc is not None and rc < 0) else None
	kod = rc if (rc is not None and rc >= 0) else None
	sebep = _sinifla(kod, sinyal, zaman_asimi)

	# ffmpeg/Pillow bellek sınırına çarptığında sinyal DEĞİL, hata metniyle
	# çıkar. Metinden sınıflandırmak kırılgan olurdu ama `SEBEP_EXIT`'i
	# `SEBEP_MEMORY`'ye çevirmek kuyruk kararını düzeltir: bellek yetmezliği
	# aynı dosyada tekrar denemeye DEĞMEZ.
	if sebep == SEBEP_EXIT and _bellek_metni(err):
		sebep = SEBEP_MEMORY

	return IsolationResult(
		ok=(sebep == SEBEP_OK),
		sebep=sebep,
		exit_code=kod,
		signal_no=sinyal,
		duration_ms=int((time.monotonic() - baslangic) * 1000),
		stdout=out,
		stderr=err,
		limits_applied=(_rlimit_adlari(limits) if pre is not None else []),
		uyarilar=uyarilar,
	)


_BELLEK_IMLERI: Tuple[bytes, ...] = (
	b"cannot allocate memory",
	b"out of memory",
	b"memoryerror",
	b"std::bad_alloc",
	b"virtual memory exhausted",
)


def _bellek_metni(err: bytes) -> bool:
	dusuk = (err or b"")[-4096:].lower()
	return any(im in dusuk for im in _BELLEK_IMLERI)


def _rlimit_adlari(limits: Limits) -> List[str]:
	"""Bu platformda GERÇEKTEN uygulanabilecek rlimit adları (ebeveyn tarafı).

	Çocuk `apply_limits`'ten dönen listeyi ebeveyne aktaramaz (exec sonrası
	kaybolur); bu fonksiyon aynı elemeyi ebeveynde tekrar yapar.
	"""
	if not RESOURCE_AVAILABLE:
		return []
	adlar = [ad for ad, _, _ in _rlimit_ciftleri(limits) if getattr(_resource, ad, None) is not None]
	if limits.nice is not None:
		adlar.append("nice")
	return adlar


# ── Python çağrılabiliri ────────────────────────────────────────────────


def run_callable(
	fn: Callable[..., Any],
	*args: Any,
	limits: Limits = IMAGE_LIMITS,
	allow_fork: bool = True,
	**kwargs: Any,
) -> IsolationResult:
	"""Python çağrılabilirini AYRI SÜREÇTE, rlimit altında çalıştır.

	Kullanım (bugünkü hattı değiştirmeden sarma):

	    from tradehub_core.media import engine
	    sonuc = run_callable(engine.optimize, icerik, 2000, 88, limits=IMAGE_LIMITS)
	    if sonuc.ok:
	        cikti = sonuc.value          # OptimizeResult
	    elif sonuc.sebep == SEBEP_MEMORY:
	        ...                          # bomba: dosyayı reddet, TEKRAR DENEME

	Dönüş değeri pickle ile borudan geçer; picklelanamayan değer (açık dosya
	tanıtıcısı, Pillow `Image` nesnesi) `SEBEP_EXCEPTION` ile döner. Bu bir
	kısıt değil sözleşmedir: süreç sınırını BAYT geçer, nesne değil.

	`fork()` yoksa ya da `allow_fork=False` ise **çağrılabilir yine çalışır**,
	ama AYNI süreçte ve sınırsız; sonuçta `uyarilar` alanına neden yazılır ve
	`limits_applied` boş döner. Güvenlik katmanının yokluğu yüzünden çalışan
	bir hattı durdurmak, koruduğundan çok zarar verirdi (av.py'deki fail-open
	gerekçesiyle aynı).
	"""
	baslangic = time.monotonic()
	if not (FORK_AVAILABLE and allow_fork):
		return _dogrudan_calistir(fn, args, kwargs, baslangic, sebep_notu="fork_yok_sinirsiz_calisti")

	try:
		oku_fd, yaz_fd = os.pipe()
	except Exception as exc:
		return IsolationResult(
			ok=False,
			sebep=SEBEP_SPAWN_FAILED,
			duration_ms=int((time.monotonic() - baslangic) * 1000),
			exception={"type": type(exc).__name__, "message": str(exc)[:300]},
		)

	try:
		pid = os.fork()
	except Exception as exc:
		os.close(oku_fd)
		os.close(yaz_fd)
		return IsolationResult(
			ok=False,
			sebep=SEBEP_SPAWN_FAILED,
			duration_ms=int((time.monotonic() - baslangic) * 1000),
			exception={"type": type(exc).__name__, "message": str(exc)[:300]},
		)

	if pid == 0:  # pragma: no cover - çocuk süreç; ölçüm ebeveynde
		_cocuk(fn, args, kwargs, oku_fd, yaz_fd, limits)
		os._exit(EXIT_EXCEPTION)  # buraya asla gelinmez

	# ── ebeveyn ──
	os.close(yaz_fd)
	son = time.monotonic() + float(limits.wall_timeout_s)
	ham, zaman_asimi, kirpildi = _borudan_oku(oku_fd, son, limits.max_output_bytes)
	try:
		os.close(oku_fd)
	except Exception:
		pass

	if zaman_asimi:
		_oldur(pid, grup=True)

	kod: Optional[int] = None
	sinyal: Optional[int] = None
	try:
		_, durum = os.waitpid(pid, 0)
		if os.WIFSIGNALED(durum):
			sinyal = os.WTERMSIG(durum)
		elif os.WIFEXITED(durum):
			kod = os.WEXITSTATUS(durum)
	except Exception:
		pass

	uyarilar: List[str] = []
	if kirpildi:
		uyarilar.append("sonuc_kirpildi")
	sebep = _sinifla(kod, sinyal, zaman_asimi)
	deger: Any = None
	istisna: Optional[Dict[str, str]] = None

	if not kirpildi and ham:
		try:
			basarili, yuk = pickle.loads(ham)
			if basarili:
				deger = yuk
			else:
				istisna = yuk
				# Çocuk istisnayı YAKALADI ve bildirdi: bellek hatasıysa
				# sebebi `memory`'ye yükselt — kuyruk "tekrar deneme" desin.
				if istisna.get("type") == "MemoryError":
					sebep = SEBEP_MEMORY
				elif sebep == SEBEP_OK:
					sebep = SEBEP_EXCEPTION
		except Exception as exc:
			sebep = SEBEP_EXCEPTION if sebep == SEBEP_OK else sebep
			istisna = {"type": type(exc).__name__, "message": f"sonuc cozulemedi: {str(exc)[:200]}"}
	elif kirpildi:
		sebep = SEBEP_OUTPUT_TOO_LARGE
	elif sebep == SEBEP_OK:
		# Çıkış kodu 0 ama boru boş: çocuk sonucu yazamadan öldü.
		sebep = SEBEP_EXCEPTION
		istisna = {"type": "EmptyResult", "message": "cocuk surec sonuc yazmadan bitti"}

	return IsolationResult(
		ok=(sebep == SEBEP_OK and istisna is None),
		sebep=sebep,
		exit_code=kod,
		signal_no=sinyal,
		duration_ms=int((time.monotonic() - baslangic) * 1000),
		value=deger,
		exception=istisna,
		limits_applied=_rlimit_adlari(limits),
		uyarilar=uyarilar,
	)


def _cocuk(  # pragma: no cover - ayrı süreçte çalışır
	fn: Callable[..., Any],
	args: tuple,
	kwargs: dict,
	oku_fd: int,
	yaz_fd: int,
	limits: Limits,
) -> None:
	"""Çocuk süreç gövdesi. **Her yol `os._exit()` ile biter.**

	`sys.exit()` KULLANILMAZ: `SystemExit` istisnası ebeveynden kopyalanan
	`atexit` kancalarını ve buffer flush'ını çalıştırır — açık DB soketi
	varsa çift commit, açık dosya varsa yarım yazma riski doğar.
	"""
	kod = EXIT_EXCEPTION
	try:
		try:
			os.close(oku_fd)
		except Exception:
			pass
		try:
			os.setsid()
		except Exception:
			pass
		apply_limits(limits)

		try:
			deger = fn(*args, **kwargs)
			yuk: Tuple[bool, Any] = (True, deger)
			kod = 0
		except MemoryError as exc:
			yuk = (False, {"type": "MemoryError", "message": str(exc)[:300]})
			kod = EXIT_MEMORY
		except BaseException as exc:  # noqa: BLE001 - çocuk hiçbir şeyi kaçırmamalı
			yuk = (False, {"type": type(exc).__name__, "message": str(exc)[:300]})
			kod = EXIT_EXCEPTION

		try:
			ham = pickle.dumps(yuk, protocol=pickle.HIGHEST_PROTOCOL)
		except Exception as exc:
			ham = pickle.dumps(
				(False, {"type": "PicklingError", "message": str(exc)[:300]}),
				protocol=pickle.HIGHEST_PROTOCOL,
			)
			kod = EXIT_PICKLE

		toplam = 0
		while toplam < len(ham):
			try:
				toplam += os.write(yaz_fd, ham[toplam : toplam + 65536])
			except BrokenPipeError:
				break
			except Exception:
				break
		try:
			os.close(yaz_fd)
		except Exception:
			pass
	except BaseException:
		kod = EXIT_EXCEPTION
	finally:
		os._exit(kod)


def _borudan_oku(fd: int, son: float, tavan: int) -> Tuple[bytes, bool, bool]:
	"""Boruyu son teslim zamanına kadar oku. `(veri, zaman_asimi, kirpildi)`.

	Ebeveyn okumazsa çocuk boru dolduğunda BLOKE olur ve zaman aşımına kadar
	bekler; bu yüzden okuma bekleme ile İÇ İÇE değil, AYNI döngüde yapılır.
	"""
	parcalar: List[bytes] = []
	toplam = 0
	kirpildi = False
	while True:
		kalan = son - time.monotonic()
		if kalan <= 0:
			return b"".join(parcalar), True, kirpildi
		try:
			hazir, _, _ = select.select([fd], [], [], min(kalan, 0.2))
		except Exception:
			return b"".join(parcalar), False, kirpildi
		if not hazir:
			continue
		try:
			parca = os.read(fd, 65536)
		except Exception:
			return b"".join(parcalar), False, kirpildi
		if not parca:
			return b"".join(parcalar), False, kirpildi
		toplam += len(parca)
		if toplam > tavan:
			kirpildi = True
			return b"".join(parcalar), False, kirpildi
		parcalar.append(parca)


def _dogrudan_calistir(
	fn: Callable[..., Any],
	args: tuple,
	kwargs: dict,
	baslangic: float,
	*,
	sebep_notu: str,
) -> IsolationResult:
	"""İzolasyon yokken son çare: aynı süreçte çalıştır ama YİNE fırlatma.

	"Worker'ı öldürme" sözleşmesinin izolasyonsuz da geçerli olan yarısı:
	istisna yakalanır, sonuç nesnesine çevrilir. Bellek bombasına karşı
	koruma YOKTUR — `uyarilar` bunu açıkça söyler.
	"""
	try:
		deger = fn(*args, **kwargs)
		return IsolationResult(
			ok=True,
			sebep=SEBEP_OK,
			exit_code=0,
			duration_ms=int((time.monotonic() - baslangic) * 1000),
			value=deger,
			uyarilar=[sebep_notu],
		)
	except MemoryError as exc:
		return IsolationResult(
			ok=False,
			sebep=SEBEP_MEMORY,
			duration_ms=int((time.monotonic() - baslangic) * 1000),
			exception={"type": "MemoryError", "message": str(exc)[:300]},
			uyarilar=[sebep_notu],
		)
	except BaseException as exc:  # noqa: BLE001
		return IsolationResult(
			ok=False,
			sebep=SEBEP_EXCEPTION,
			duration_ms=int((time.monotonic() - baslangic) * 1000),
			exception={"type": type(exc).__name__, "message": str(exc)[:300]},
			uyarilar=[sebep_notu],
		)


def durum() -> Dict[str, Any]:
	"""İzolasyonun bu makinede gerçekte NE KADAR uygulanabildiği.

	Sağlık ucu ve `observability/metrics.py` bunu yayınlar: "sertleştirme
	açık" demek ile gerçekten uygulanmış olmak ayrı şeylerdir.
	"""
	return {
		"resource_available": RESOURCE_AVAILABLE,
		"fork_available": FORK_AVAILABLE,
		"platform": sys.platform,
		"applicable_rlimits": _rlimit_adlari(IMAGE_LIMITS),
		"profiles": {ad: lim.wall_timeout_s for ad, lim in PROFILLER.items()},
		"upstream_video_constants": UPSTREAM_VIDEO_AVAILABLE,
	}


__all__ = [
	"CPU_HARD_GRACE_SECONDS",
	"FORK_AVAILABLE",
	"IMAGE_LIMITS",
	"PROBE_LIMITS",
	"PROFILLER",
	"RESOURCE_AVAILABLE",
	"RETRYABLE_SEBEPLER",
	"SCAN_LIMITS",
	"SEBEP_CPU",
	"SEBEP_EXCEPTION",
	"SEBEP_EXIT",
	"SEBEP_KILLED",
	"SEBEP_MEMORY",
	"SEBEP_OK",
	"SEBEP_OUTPUT_TOO_LARGE",
	"SEBEP_SPAWN_FAILED",
	"SEBEP_TIMEOUT",
	"SEBEP_UNSUPPORTED",
	"VIDEO_LIMITS",
	"IsolationResult",
	"Limits",
	"apply_limits",
	"durum",
	"limit_preexec",
	"run_callable",
	"run_command",
]
