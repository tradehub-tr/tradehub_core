"""T-130 — alt süreç izolasyonu testleri.

Sözleşme tek cümledir ve bu dosyanın omurgası odur:

    **Başarısız iş, worker'ı öldürmez.**

Her arıza sınıfı ayrı ayrı üretilir (istisna, sonsuz döngü, duvar saati aşımı,
`abort()`, eksik ikili, bellek bombası) ve HER birinde iki şey ölçülür:
  1. sonuç nesnesi doğru sebebi taşıyor mu,
  2. TEST SÜRECİ hâlâ yaşıyor mu (`os.getpid()` değişmedi, sonraki test koştu).

ÖLÇÜLMÜŞ PLATFORM FARKI — testler bunu bilir
============================================
`RLIMIT_AS` **macOS/Darwin'de UYGULANMIYOR**. Bu makinede ölçüldü
(2026-08-18): 100 MB'lık `RLIMIT_AS` altında 400 MB'lık `bytearray` sorunsuz
ayrıldı ve `getrlimit(RLIMIT_AS)` `RLIM_INFINITY` döndürdü. Aynı kod
üretim ortamında (Linux, `istoc-dev-backend-1`, Python 3.11.6) `MemoryError`
verdi ve `tradehub_core/tests/fixtures/malicious/bomb_100mp.png` 64/96/128 MB sınırlarının
üçünde de `isolation_memory` ile durduruldu.

Yani bellek koruması ÜRETİMDE VAR, YEREL macOS'ta YOK. Test bunu gizlemez:
bellek testi Linux dışında `skipTest` ile atlanır ve atlama mesajı sebebi
yazar. "Yerelde geçti" demek "üretimde korunuyor" demek değildir; tersi de.

Çalıştırma:

    python3 -m unittest discover -s /Users/ahmet/Desktop/istoc/tradehub_core/tests -v
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOMBA = ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious" / "bomb_100mp.png"

if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.security import isolation as iso  # noqa: E402

LINUX = sys.platform.startswith("linux")


# ── modül düzeyi yardımcılar (fork edilen çocukta çalışır) ──────────────


def _kare(x):
	return x * x


def _patla():
	raise ValueError("kasitli hata")


def _sonsuz_dongu():
	while True:  # noqa: B909
		pass


def _uyu(saniye):
	time.sleep(saniye)
	return "uyandim"


def _bellek_ye(bayt):
	blok = bytearray(bayt)
	return len(blok)


def _dosya_tanitici_dondur():
	"""Pickle EDİLEMEYEN değer — süreç sınırını nesne değil BAYT geçer."""
	return open(os.devnull)


def _bombayi_ac(veri):
	from PIL import Image

	Image.MAX_IMAGE_PIXELS = None
	import io

	im = Image.open(io.BytesIO(veri))
	im.load()
	return im.size


class LimitSozlesmesi(unittest.TestCase):
	"""`Limits` → rlimit çevirisi ve mevcut sabitlerle hizalanma."""

	def test_rlimit_ciftleri_saf_ve_ongorulebilir(self):
		lim = iso.Limits(cpu_seconds=10, address_space_bytes=1024, file_size_bytes=2048, open_files=64, core_bytes=0)
		harita = {ad: (y, s) for ad, y, s in iso._rlimit_ciftleri(lim)}
		self.assertEqual(harita["RLIMIT_CPU"], (10, 10 + iso.CPU_HARD_GRACE_SECONDS))
		self.assertEqual(harita["RLIMIT_AS"], (1024, 1024))
		self.assertEqual(harita["RLIMIT_CORE"], (0, 0))

	def test_none_sinir_koymaz(self):
		lim = iso.Limits(cpu_seconds=None, address_space_bytes=None, file_size_bytes=None, open_files=None, core_bytes=None)
		self.assertEqual(iso._rlimit_ciftleri(lim), [])

	def test_core_dump_varsayilan_olarak_kapali(self):
		"""Core dump bellek dökümüdür → PII taşır (KVKK). Varsayılan 0."""
		self.assertEqual(iso.IMAGE_LIMITS.core_bytes, 0)

	def test_cpu_limiti_duvar_saatinden_kucuk(self):
		"""Sonsuz DÖNGÜ önce CPU'ya takılsın; duvar saati I/O için kalsın."""
		for ad, lim in iso.PROFILLER.items():
			if lim.cpu_seconds is None:
				continue
			with self.subTest(profil=ad):
				self.assertLessEqual(lim.cpu_seconds, lim.wall_timeout_s)

	def test_video_sureleri_mevcut_sabitlerle_ayrismamis(self):
		"""`contracts/video.py` değerleri YENİDEN TANIMLANMADI, içeri alındı."""
		from tradehub_core.media.pipeline.contracts.video import FFMPEG_TIMEOUT_SECONDS, FFPROBE_TIMEOUT_SECONDS

		self.assertEqual(iso.VIDEO_LIMITS.wall_timeout_s, float(FFMPEG_TIMEOUT_SECONDS))
		self.assertEqual(iso.PROBE_LIMITS.wall_timeout_s, float(FFPROBE_TIMEOUT_SECONDS))

	def test_tarama_suresi_av_py_ile_ayni(self):
		"""`media/av.py:126` `_SCAN_TIMEOUT_SECONDS = 120` ile hizalı mı.

		`av.py` frappe'ye bağlı olduğu için import EDİLMEZ; sabit dosyadan
		metin olarak okunur — ayrışma yine de yakalanır.
		"""
		metin = (ROOT / "tradehub_core" / "media" / "av.py").read_text(encoding="utf-8")
		self.assertIn(f"_SCAN_TIMEOUT_SECONDS: int = {int(iso.SCAN_TIMEOUT_SECONDS)}", metin)

	def test_bellek_tavani_olculen_en_buyuk_dosyayi_gecirir(self):
		"""72,71 MP kaynakta ölçülen tepe ~947 MB; tavan onun üstünde olmalı."""
		self.assertGreater(iso.IMAGE_LIMITS.address_space_bytes, 947 * 1024 * 1024)

	def test_apply_limits_asla_firlatmaz(self):
		"""`fork` ile `exec` arasında istisna = çocuğun tanımsız davranışı.

		**`apply_limits` ÇOCUK tarafı içindir ve ÇOCUKTA çağrılır.** Test
		süreci içinde doğrudan çağırmak test koşucusunun KENDİ limitlerini
		kalıcı olarak düşürür ve rlimit'in sert sınırı geri yükseltilemez
		(POSIX). Bu tuzak bu testi yazarken YAŞANDI: `open_files=0` ile
		çağrılan ilk sürüm, koşucunun dosya tanıtıcı hakkını sıfırladı ve
		sonraki 5 test `OSError: [Errno 24] Too many open files` ile düştü.
		Bu yüzden çağrı `run_callable` ile izole çocukta yapılır.
		"""
		for lim in (
			iso.IMAGE_LIMITS,
			iso.Limits(cpu_seconds=-5, address_space_bytes=1, open_files=0, core_bytes=0, nice=999),
			iso.Limits(cpu_seconds=None, address_space_bytes=None, nice=None),
		):
			with self.subTest(lim=lim):
				sonuc = iso.run_callable(iso.apply_limits, lim, limits=iso.Limits(wall_timeout_s=10.0))
				self.assertIsNone(sonuc.exception, sonuc.exception)
				self.assertIsInstance(sonuc.value, list)


class BasariliCalistirma(unittest.TestCase):
	def test_callable_deger_dondurur(self):
		sonuc = iso.run_callable(_kare, 7)
		self.assertTrue(sonuc.ok, sonuc.sebep)
		self.assertEqual(sonuc.value, 49)
		self.assertEqual(sonuc.sebep, iso.SEBEP_OK)
		self.assertEqual(sonuc.exit_code, 0)

	def test_kwargs_gecer(self):
		sonuc = iso.run_callable(_uyu, saniye=0.0)
		self.assertEqual(sonuc.value, "uyandim")

	def test_cocuk_ebeveynin_pidini_kullanmaz(self):
		"""Gerçekten AYRI süreçte mi çalışıyor."""
		sonuc = iso.run_callable(os.getpid)
		self.assertTrue(sonuc.ok)
		self.assertNotEqual(sonuc.value, os.getpid())

	def test_komut_calisir(self):
		sonuc = iso.run_command(["/bin/echo", "merhaba"], limits=iso.PROBE_LIMITS)
		self.assertTrue(sonuc.ok, sonuc.stderr)
		self.assertEqual(sonuc.stdout.strip(), b"merhaba")

	def test_stdin_gecer(self):
		sonuc = iso.run_command(["/bin/cat"], limits=iso.PROBE_LIMITS, stdin_data=b"veri")
		self.assertTrue(sonuc.ok)
		self.assertEqual(sonuc.stdout, b"veri")


class ArizaSiniflari(unittest.TestCase):
	"""Her arıza doğru sebeple döner ve HİÇBİRİ istisna fırlatmaz."""

	def test_istisna_yakalanir_ve_kunyesi_tasinir(self):
		sonuc = iso.run_callable(_patla)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.sebep, iso.SEBEP_EXCEPTION)
		self.assertEqual(sonuc.exception["type"], "ValueError")
		self.assertIn("kasitli hata", sonuc.exception["message"])

	def test_duvar_saati_asimi(self):
		lim = iso.Limits(wall_timeout_s=1.0, cpu_seconds=None, address_space_bytes=None)
		t0 = time.monotonic()
		sonuc = iso.run_callable(_uyu, 30, limits=lim)
		gecen = time.monotonic() - t0
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.sebep, iso.SEBEP_TIMEOUT)
		self.assertTrue(sonuc.timed_out)
		self.assertLess(gecen, 15, "zaman asimi gercekten kesmedi")

	def test_cpu_limiti_sonsuz_donguyu_keser(self):
		lim = iso.Limits(wall_timeout_s=30.0, cpu_seconds=1, address_space_bytes=None)
		sonuc = iso.run_callable(_sonsuz_dongu, limits=lim)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.sebep, iso.SEBEP_CPU)
		self.assertEqual(sonuc.signal_no, signal.SIGXCPU)

	def test_abort_sinyali_killed_olarak_siniflanir(self):
		sonuc = iso.run_callable(os.abort)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.sebep, iso.SEBEP_KILLED)
		self.assertIsNotNone(sonuc.signal_no)

	def test_picklelanamayan_donus_istisna_olur(self):
		sonuc = iso.run_callable(_dosya_tanitici_dondur)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.sebep, iso.SEBEP_EXCEPTION)

	def test_olmayan_ikili_spawn_failed(self):
		sonuc = iso.run_command(["/kesinlikle/olmayan/ikili"], limits=iso.PROBE_LIMITS)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.sebep, iso.SEBEP_SPAWN_FAILED)
		self.assertTrue(sonuc.retryable)

	def test_bos_komut_reddedilir(self):
		self.assertEqual(iso.run_command([]).sebep, iso.SEBEP_SPAWN_FAILED)

	def test_sifirdan_farkli_cikis_kodu(self):
		sonuc = iso.run_command(["/bin/sh", "-c", "exit 3"], limits=iso.PROBE_LIMITS)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.sebep, iso.SEBEP_EXIT)
		self.assertEqual(sonuc.exit_code, 3)

	def test_komut_zaman_asiminda_surec_grubu_olur(self):
		"""Torun süreç de gitmeli — `killpg` olmadan arkada kalırdı."""
		lim = iso.Limits(wall_timeout_s=1.0, cpu_seconds=None, address_space_bytes=None)
		t0 = time.monotonic()
		sonuc = iso.run_command(["/bin/sh", "-c", "sleep 30 & sleep 30"], limits=lim)
		self.assertEqual(sonuc.sebep, iso.SEBEP_TIMEOUT)
		self.assertLess(time.monotonic() - t0, 15)


class BellekBombasi(unittest.TestCase):
	"""RLIMIT_AS — yalnız Linux'ta uygulanıyor (ölçüldü, modül başlığına bak)."""

	def setUp(self):
		if not LINUX:
			self.skipTest(
				"RLIMIT_AS macOS/Darwin'de UYGULANMIYOR (2026-08-18 olcumu): "
				"100 MB sinir altinda 400 MB ayrildi. Uretim Linux'ta calisiyor."
			)

	def test_asiri_ayirma_memory_ile_doner(self):
		lim = iso.Limits(wall_timeout_s=20.0, cpu_seconds=None, address_space_bytes=100 * 1024 * 1024)
		sonuc = iso.run_callable(_bellek_ye, 400 * 1024 * 1024, limits=lim)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.sebep, iso.SEBEP_MEMORY)

	def test_dekompresyon_bombasi_worker_i_oldurmez(self):
		if not BOMBA.is_file():
			self.skipTest(f"fixture yok: {BOMBA}")
		try:
			import PIL  # noqa: F401
		except Exception:
			self.skipTest("Pillow yok")
		onceki_pid = os.getpid()
		lim = iso.IMAGE_LIMITS.with_(address_space_bytes=64 * 1024 * 1024, wall_timeout_s=30.0)
		sonuc = iso.run_callable(_bombayi_ac, BOMBA.read_bytes(), limits=lim)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.sebep, iso.SEBEP_MEMORY)
		self.assertEqual(os.getpid(), onceki_pid, "EBEVEYN OLDU — sozlesme ihlali")

	def test_bellek_hatasi_tekrar_denenmez(self):
		"""Aynı dosya aynı sonucu verir; kuyruk hakkı yakılmamalı."""
		self.assertNotIn(iso.SEBEP_MEMORY, iso.RETRYABLE_SEBEPLER)

	def test_harici_surec_rss_watchdog_ile_kesilir(self):
		"""ffmpeg gibi mmap-ağır süreçlerde fiziksel RSS tavanı uygulanır."""
		if not iso.PSUTIL_AVAILABLE:
			self.skipTest("psutil yok — RSS watchdog uygulanamaz")
		lim = iso.Limits(
			wall_timeout_s=10.0,
			cpu_seconds=None,
			address_space_bytes=None,
			resident_memory_bytes=24 * 1024 * 1024,
		)
		sonuc = iso.run_command(
			[sys.executable, "-c", "import time; x=bytearray(96*1024*1024); time.sleep(5)"],
			limits=lim,
			poll_interval_s=0.05,
		)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.sebep, iso.SEBEP_MEMORY)
		self.assertIn("RSS_WATCHDOG", sonuc.limits_applied)
		self.assertGreater(sonuc.peak_rss_bytes, lim.resident_memory_bytes)


class WorkerHayatta(unittest.TestCase):
	"""Sözleşmenin kendisi: art arda altı arıza, ebeveyn hâlâ ayakta."""

	def test_arka_arkaya_arizalar_sonrasi_surec_yasiyor(self):
		pid = os.getpid()
		kisa = iso.Limits(wall_timeout_s=1.0, cpu_seconds=1, address_space_bytes=None)
		sonuclar = [
			iso.run_callable(_patla),
			iso.run_callable(_uyu, 30, limits=kisa),
			iso.run_callable(_sonsuz_dongu, limits=kisa),
			iso.run_callable(os.abort),
			iso.run_callable(_dosya_tanitici_dondur),
			iso.run_command(["/kesinlikle/olmayan/ikili"]),
		]
		for s in sonuclar:
			self.assertFalse(s.ok)
		self.assertEqual(os.getpid(), pid)
		# Ve süreç hâlâ ÇALIŞABİLİR durumda:
		self.assertEqual(iso.run_callable(_kare, 5).value, 25)

	def test_zombi_birakmaz(self):
		"""Her `fork` için `waitpid` yapılıyor mu — zombi süreç birikmemeli."""
		for _ in range(5):
			iso.run_callable(_patla)
		# Docker/PID-namespace altında kısa ömürlü bir yardımcı çocuk hâlâ
		# KOSUYORSA ``waitpid(..., WNOHANG)`` (0, 0) dönebilir; bu zombi
		# değildir. En çok bir saniye bitmesini bekle. Pozitif pid dönerse test
		# onu burada reaped etmiştir ve run_callable zombi bırakmış demektir.
		son = time.monotonic() + 1.0
		while True:
			try:
				pid, _durum = os.waitpid(-1, os.WNOHANG)
			except ChildProcessError:
				break
			if pid > 0:
				self.fail(f"zombi cocuk test tarafindan reaped edildi: pid={pid}")
			if time.monotonic() >= son:
				self.fail("bir cocuk 1 saniyeden uzun sure bitmedi")
			time.sleep(0.01)


class SonucSozlesmesi(unittest.TestCase):
	def test_to_dict_ham_ciktiyi_sizdirmaz(self):
		"""ffmpeg hata metni dosya YOLU taşır — log'a ham yol yazılmamalı."""
		sonuc = iso.run_command(["/bin/sh", "-c", "echo /private/files/ab/kimlik.jpg >&2; exit 1"])
		sozluk = sonuc.to_dict()
		self.assertNotIn("stdout", sozluk)
		self.assertNotIn("stderr", sozluk)
		self.assertIn("stderr_bytes", sozluk)
		self.assertGreater(sozluk["stderr_bytes"], 0)

	def test_retryable_tablosu(self):
		self.assertIn(iso.SEBEP_TIMEOUT, iso.RETRYABLE_SEBEPLER)
		self.assertIn(iso.SEBEP_KILLED, iso.RETRYABLE_SEBEPLER)
		self.assertIn(iso.SEBEP_SPAWN_FAILED, iso.RETRYABLE_SEBEPLER)
		self.assertNotIn(iso.SEBEP_EXCEPTION, iso.RETRYABLE_SEBEPLER)
		self.assertNotIn(iso.SEBEP_CPU, iso.RETRYABLE_SEBEPLER)

	def test_cikti_tavani_kirpar(self):
		lim = iso.PROBE_LIMITS.with_(max_output_bytes=64)
		sonuc = iso.run_command(["/bin/sh", "-c", "head -c 5000 /dev/zero | tr '\\0' 'x'"], limits=lim)
		self.assertLessEqual(len(sonuc.stdout), 64)
		self.assertIn("stdout_kirpildi", sonuc.uyarilar)

	def test_sure_olculur(self):
		sonuc = iso.run_callable(_uyu, 0.2)
		self.assertGreaterEqual(sonuc.duration_ms, 150)

	def test_durum_gercegi_soyler(self):
		d = iso.durum()
		self.assertEqual(d["fork_available"], hasattr(os, "fork"))
		self.assertEqual(d["platform"], sys.platform)
		self.assertIsInstance(d["applicable_rlimits"], list)

	def test_fork_kapaliyken_yine_calisir_ama_uyarir(self):
		"""Güvenlik katmanı yoksa hat DURMAZ; eksiklik raporlanır."""
		sonuc = iso.run_callable(_kare, 6, allow_fork=False)
		self.assertTrue(sonuc.ok)
		self.assertEqual(sonuc.value, 36)
		self.assertEqual(sonuc.limits_applied, [])
		self.assertTrue(sonuc.uyarilar)

	def test_fork_kapaliyken_istisna_yine_yutulur(self):
		sonuc = iso.run_callable(_patla, allow_fork=False)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.sebep, iso.SEBEP_EXCEPTION)


class GercekIkiliyleEntegrasyon(unittest.TestCase):
	"""ffprobe varsa gerçek bir alt süreç izolasyonda koşturulur."""

	def setUp(self):
		self.ffprobe = shutil.which("ffprobe")
		if not self.ffprobe:
			self.skipTest("ffprobe yok (konteynerde VAR, yerelde olmayabilir)")

	def test_ffprobe_izolasyonda_calisir(self):
		sonuc = iso.run_command([self.ffprobe, "-version"], limits=iso.PROBE_LIMITS)
		self.assertTrue(sonuc.ok, sonuc.stderr[:200])
		self.assertIn(b"ffprobe", sonuc.stdout.lower() + sonuc.stderr.lower())

	def test_ffprobe_bozuk_dosyada_temiz_hata_verir(self):
		bozuk = ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious" / "truncated.jpg"
		if not bozuk.is_file():
			self.skipTest("truncated.jpg yok")
		sonuc = iso.run_command(
			[self.ffprobe, "-v", "error", "-show_format", str(bozuk)], limits=iso.PROBE_LIMITS
		)
		self.assertIn(sonuc.sebep, (iso.SEBEP_OK, iso.SEBEP_EXIT))
		self.assertIsNotNone(sonuc.exit_code)


if __name__ == "__main__":
	unittest.main(verbosity=2)
