"""T-034 — Durum makinesi ve kuyruk zarfı testleri.

İki iddiayı doğrular:

1. **`tradehub_core/media/pipeline/core/state.py` mevcut yaşam döngüsünü GEÇERSİZ KILMIYOR.**
   `tradehub_core/media/states.py` içindeki `ALLOWED_TRANSITIONS` tablosu
   `ast` ile kaynaktan okunur ve `core/state.py` aynasıyla BİRE BİR
   karşılaştırılır. `av.py` tarama sözlüğü için de aynısı yapılır. Ayna
   eskirse test düşer — bu, "yorumda yazıyordu" güvencesinin makine hâli.

2. **`tradehub_core/media/pipeline/core/jobs.py` retry politikasını TEKRARLAMIYOR.**
   `tradehub_core/media/jobs.py` sabitleri kaynaktan okunur ve modüldeki
   değerlerle karşılaştırılır. Yeni olan tek şey idempotency muhafızıdır ve
   davranışı ayrıca test edilir.

Çalıştırma (bench/site GEREKMEZ):

    python3 -m unittest tests.test_state_machine -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.core import jobs as J  # noqa: E402
from tradehub_core.media.pipeline.core import state as S  # noqa: E402


def _yardimci():
	"""`test_policy_engine.load_module_constants`'ı DOSYA YOLUNDAN yükle.

	`from tests.test_policy_engine import ...` yazmıyoruz: `tests/` bir paket
	değil ve ortama göre başka bir üst düzey `tests` modülü onu gölgeleyebilir
	(konteynerdeki 3.11 ortamında tam olarak bu oluyor). Dosya yolundan
	yüklemek koşum ortamından bağımsızdır.
	"""
	import importlib.util

	yol = Path(__file__).resolve().parent / "test_policy_engine.py"
	spec = importlib.util.spec_from_file_location("_faz3_test_policy_engine", yol)
	modul = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(modul)
	return modul.load_module_constants


load_module_constants = _yardimci()

STATES_SRC = ROOT / "tradehub_core" / "media" / "states.py"
AV_SRC = ROOT / "tradehub_core" / "media" / "av.py"
JOBS_SRC = ROOT / "tradehub_core" / "media" / "jobs.py"


class YasamDongusuAynasiTesti(unittest.TestCase):
	"""Ayna kaynakla aynı mı — sessiz ayrışmaya karşı."""

	@classmethod
	def setUpClass(cls):
		cls.kaynak = load_module_constants(
			STATES_SRC,
			[
				"STATE_ACTIVE",
				"STATE_ARCHIVED",
				"STATE_TRASHED",
				"STATE_DELETED",
				"STORED_STATES",
				"ALL_STATES",
				"ALLOWED_TRANSITIONS",
			],
		)

	def test_durum_adlari_ayni(self):
		self.assertEqual(S.LIFECYCLE_ACTIVE, self.kaynak["STATE_ACTIVE"])
		self.assertEqual(S.LIFECYCLE_ARCHIVED, self.kaynak["STATE_ARCHIVED"])
		self.assertEqual(S.LIFECYCLE_TRASHED, self.kaynak["STATE_TRASHED"])
		self.assertEqual(S.LIFECYCLE_DELETED, self.kaynak["STATE_DELETED"])

	def test_durum_kumeleri_ayni(self):
		self.assertEqual(S.LIFECYCLE_STORED, self.kaynak["STORED_STATES"])
		self.assertEqual(S.LIFECYCLE_ALL, self.kaynak["ALL_STATES"])

	def test_gecis_tablosu_bire_bir_ayni(self):
		self.assertEqual(S.LIFECYCLE_TRANSITIONS, self.kaynak["ALLOWED_TRANSITIONS"])

	def test_tarama_sozlugu_av_ile_ayni(self):
		kaynak = load_module_constants(
			AV_SRC,
			["SCAN_PENDING", "SCAN_CLEAN", "SCAN_INFECTED", "SCAN_FAILED", "STORED_SCAN_STATUSES"],
		)
		self.assertEqual(S.SCAN_PENDING, kaynak["SCAN_PENDING"])
		self.assertEqual(S.SCAN_CLEAN, kaynak["SCAN_CLEAN"])
		self.assertEqual(S.SCAN_INFECTED, kaynak["SCAN_INFECTED"])
		self.assertEqual(S.SCAN_FAILED, kaynak["SCAN_FAILED"])
		self.assertEqual(S.SCAN_ALL, kaynak["STORED_SCAN_STATUSES"])


class YasamDongusuDavranisiTesti(unittest.TestCase):
	"""Mevcut kararlar korunuyor mu."""

	def test_active_dogrudan_silinemez(self):
		"""İki adımlı silme bilinçli bir karar (states.py başlığı); korunuyor."""
		self.assertFalse(S.can_lifecycle(S.LIFECYCLE_ACTIVE, S.LIFECYCLE_DELETED))
		with self.assertRaises(S.InvalidTransition):
			S.lifecycle_transition(S.LIFECYCLE_ACTIVE, S.LIFECYCLE_DELETED)

	def test_copten_kalici_silme_izinli(self):
		sonuc = S.lifecycle_transition(S.LIFECYCLE_TRASHED, S.LIFECYCLE_DELETED)
		self.assertTrue(sonuc.changed)
		self.assertEqual(sonuc.axis, "lifecycle")

	def test_deleted_terminal(self):
		self.assertEqual(S.LIFECYCLE_TRANSITIONS[S.LIFECYCLE_DELETED], frozenset())
		for hedef in S.LIFECYCLE_ALL:
			if hedef == S.LIFECYCLE_DELETED:
				continue
			with self.assertRaises(S.InvalidTransition):
				S.lifecycle_transition(S.LIFECYCLE_DELETED, hedef)

	def test_ayni_duruma_gecis_degisiklik_sayilmaz(self):
		sonuc = S.lifecycle_transition(S.LIFECYCLE_ACTIVE, S.LIFECYCLE_ACTIVE)
		self.assertFalse(sonuc.changed)

	def test_bilinmeyen_durum_hata_verir(self):
		with self.assertRaises(S.InvalidTransition):
			S.lifecycle_transition("Yok", S.LIFECYCLE_ACTIVE)


class AlimEkseniTesti(unittest.TestCase):
	"""Yeni eklenen ingest ekseni."""

	def test_mutlu_yol(self):
		zincir = [
			S.INGEST_RECEIVED,
			S.INGEST_SCREENED,
			S.INGEST_VALIDATED,
			S.INGEST_MASTERED,
			S.INGEST_READY,
		]
		for kaynak, hedef in zip(zincir, zincir[1:]):
			self.assertTrue(S.ingest_transition(kaynak, hedef).changed)

	def test_terminal_durumlardan_cikis_yok(self):
		for durum in S.INGEST_TERMINAL:
			self.assertEqual(S.INGEST_TRANSITIONS[durum], frozenset())
			self.assertTrue(S.terminal(durum))
			with self.assertRaises(S.InvalidTransition):
				S.ingest_transition(durum, S.INGEST_SCREENED)

	def test_basarisiz_is_basa_degil_tarama_sonrasina_doner(self):
		"""Yeniden deneme dosyayı ikinci kez taratmaz — tarama sonucu duruyor."""
		self.assertTrue(S.can_ingest(S.INGEST_FAILED, S.INGEST_SCREENED))
		self.assertFalse(S.can_ingest(S.INGEST_FAILED, S.INGEST_RECEIVED))

	def test_her_durum_receiveddan_erisilebilir(self):
		"""Ulaşılamayan durum, ölü koddur."""
		gorulen = {S.INGEST_RECEIVED}
		sinir = [S.INGEST_RECEIVED]
		while sinir:
			d = sinir.pop()
			for h in S.INGEST_TRANSITIONS[d]:
				if h not in gorulen:
					gorulen.add(h)
					sinir.append(h)
		self.assertEqual(gorulen, set(S.INGEST_ALL))

	def test_gecis_tablosu_tum_durumlari_kapsiyor(self):
		self.assertEqual(set(S.INGEST_TRANSITIONS), set(S.INGEST_ALL))
		for hedefler in S.INGEST_TRANSITIONS.values():
			self.assertTrue(hedefler <= set(S.INGEST_ALL))


class IkiEksenSozlesmesiTesti(unittest.TestCase):
	"""ingest × lifecycle çiftinin geçerliliği."""

	def test_ready_yasam_dongusunde_active_ya_da_archived(self):
		self.assertTrue(S.consistent(S.INGEST_READY, S.LIFECYCLE_ACTIVE))
		self.assertTrue(S.consistent(S.INGEST_READY, S.LIFECYCLE_ARCHIVED))
		self.assertFalse(S.consistent(S.INGEST_READY, S.LIFECYCLE_TRASHED))

	def test_rejected_kayit_olusturmaz(self):
		self.assertEqual(S.allowed_lifecycle_for(S.INGEST_REJECTED), frozenset())
		self.assertTrue(S.consistent(S.INGEST_REJECTED, None))
		for durum in S.LIFECYCLE_ALL:
			self.assertFalse(S.consistent(S.INGEST_REJECTED, durum))

	def test_karantina_trashed_ile_esleser(self):
		self.assertTrue(S.consistent(S.INGEST_QUARANTINED, S.LIFECYCLE_TRASHED))
		self.assertFalse(S.consistent(S.INGEST_QUARANTINED, S.LIFECYCLE_ACTIVE))

	def test_ara_durumlar_active_kalir(self):
		for durum in (
			S.INGEST_RECEIVED,
			S.INGEST_SCREENED,
			S.INGEST_VALIDATED,
			S.INGEST_MASTERED,
			S.INGEST_FAILED,
		):
			self.assertEqual(S.allowed_lifecycle_for(durum), frozenset({S.LIFECYCLE_ACTIVE}))

	def test_guvenlik_karari_politika_kararini_ezer(self):
		"""Enfekte dosya politikayı geçse bile karantinaya gider."""
		self.assertEqual(
			S.ingest_from_decision(True, S.SCAN_INFECTED), S.INGEST_QUARANTINED
		)
		self.assertEqual(
			S.ingest_from_decision(False, S.SCAN_INFECTED), S.INGEST_QUARANTINED
		)
		self.assertEqual(S.ingest_from_decision(False, S.SCAN_CLEAN), S.INGEST_REJECTED)
		self.assertEqual(S.ingest_from_decision(True, S.SCAN_CLEAN), S.INGEST_VALIDATED)


class KuyrukPolitikasiAynasiTesti(unittest.TestCase):
	"""Retry politikası tek yerde — `tradehub_core/media/jobs.py`."""

	@classmethod
	def setUpClass(cls):
		cls.kaynak = load_module_constants(
			JOBS_SRC,
			[
				"STATE_RUNNING",
				"STATE_COMPLETED",
				"STATE_PARTIAL",
				"STATE_ERROR",
				"TERMINAL_STATES",
				"MAX_ATTEMPTS",
				"BACKOFF_SECONDS",
				"STALE_AFTER_SECONDS",
				"SWEEP_EVERY_SECONDS",
			],
		)

	def test_durum_sozlugu_ayni(self):
		self.assertEqual(J.STATE_RUNNING, self.kaynak["STATE_RUNNING"])
		self.assertEqual(J.STATE_COMPLETED, self.kaynak["STATE_COMPLETED"])
		self.assertEqual(J.STATE_PARTIAL, self.kaynak["STATE_PARTIAL"])
		self.assertEqual(J.STATE_ERROR, self.kaynak["STATE_ERROR"])
		self.assertEqual(J.TERMINAL_STATES, self.kaynak["TERMINAL_STATES"])

	def test_retry_sayilari_ayni(self):
		self.assertEqual(J.MAX_ATTEMPTS, self.kaynak["MAX_ATTEMPTS"])
		self.assertEqual(J.BACKOFF_SECONDS, self.kaynak["BACKOFF_SECONDS"])
		self.assertEqual(J.STALE_AFTER_SECONDS, self.kaynak["STALE_AFTER_SECONDS"])
		self.assertEqual(J.SWEEP_EVERY_SECONDS, self.kaynak["SWEEP_EVERY_SECONDS"])

	def test_backoff_kaynakla_ayni_egriyi_verir(self):
		beklenen = self.kaynak["BACKOFF_SECONDS"]
		self.assertEqual(J.backoff_seconds(1), beklenen[0])
		self.assertEqual(J.backoff_seconds(2), beklenen[1])
		# Liste bitince son değer tekrarlanır (kaynak dosyanın kendi kuralı).
		self.assertEqual(J.backoff_seconds(99), beklenen[-1])
		self.assertEqual(J.backoff_seconds(0), beklenen[0])

	def test_stale_esigi_kuyruk_timeoutundan_buyuk(self):
		"""Kaynak dosyanın gerekçesi: aksi hâlde çalışan iş 'kayıp' ilan edilir."""
		self.assertGreater(J.STALE_AFTER_SECONDS, 1800)


class IdempotencyAnahtariTesti(unittest.TestCase):
	def test_ayni_icerik_ayni_anahtar(self):
		a = J.JobEnvelope.build(J.JOB_MASTER, "/files/a.jpg", content_hash="ab" * 32)
		b = J.JobEnvelope.build(J.JOB_MASTER, "/files/kopya.jpg", content_hash="ab" * 32)
		self.assertEqual(a.key, b.key)

	def test_farkli_is_turu_farkli_anahtar(self):
		a = J.JobEnvelope.build(J.JOB_MASTER, "/files/a.jpg", content_hash="ab" * 32)
		b = J.JobEnvelope.build(J.JOB_DERIVE, "/files/a.jpg", content_hash="ab" * 32)
		self.assertNotEqual(a.key, b.key)

	def test_farkli_parametre_farkli_anahtar(self):
		a = J.JobEnvelope.build(J.JOB_DERIVE, "/f.jpg", content_hash="c" * 64, params={"w": 96})
		b = J.JobEnvelope.build(J.JOB_DERIVE, "/f.jpg", content_hash="c" * 64, params={"w": 1920})
		self.assertNotEqual(a.key, b.key)

	def test_parametre_sirasi_anahtari_degistirmez(self):
		a = J.JobEnvelope.build(J.JOB_DERIVE, "/f.jpg", params={"w": 96, "fmt": "webp"})
		b = J.JobEnvelope.build(J.JOB_DERIVE, "/f.jpg", params={"fmt": "webp", "w": 96})
		self.assertEqual(a.key, b.key)

	def test_icerik_yoksa_hedefe_dusulur(self):
		a = J.JobEnvelope.build(J.JOB_SCAN, "/files/a.jpg")
		b = J.JobEnvelope.build(J.JOB_SCAN, "/files/b.jpg")
		self.assertNotEqual(a.key, b.key)

	def test_bilinmeyen_is_turu_hata(self):
		with self.assertRaises(ValueError):
			J.idempotency_key("media.yok", "/a.jpg")

	def test_hedefsiz_ve_iceriksiz_anahtar_uretilemez(self):
		with self.assertRaises(ValueError):
			J.idempotency_key(J.JOB_SCAN, "")

	def test_yeniden_deneme_anahtari_korur(self):
		a = J.JobEnvelope.build(J.JOB_MASTER, "/f.jpg", content_hash="d" * 64)
		b = a.retry()
		self.assertEqual(a.key, b.key)
		self.assertEqual(b.attempt, 1)
		self.assertEqual(b.state, J.STATE_RUNNING)

	def test_deneme_hakki_tukenmesi(self):
		z = J.JobEnvelope.build(J.JOB_MASTER, "/f.jpg", attempt=J.MAX_ATTEMPTS)
		self.assertTrue(z.exhausted)
		self.assertFalse(J.JobEnvelope.build(J.JOB_MASTER, "/f.jpg").exhausted)


class IdempotencyMuhafiziTesti(unittest.TestCase):
	"""`InMemoryGuard` davranışı — sahte saatle."""

	def setUp(self):
		self.simdi = [1000.0]
		self.guard = J.InMemoryGuard(lock_ttl=60, result_ttl=600, clock=lambda: self.simdi[0])
		self.job = J.JobEnvelope.build(J.JOB_MASTER, "/f.jpg", content_hash="e" * 64)

	def test_ilk_talep_verilir_ikincisi_verilmez(self):
		self.assertTrue(self.guard.claim(self.job).granted)
		ikinci = self.guard.claim(self.job)
		self.assertFalse(ikinci.granted)
		self.assertTrue(ikinci.running)

	def test_biten_is_sonucu_tekrar_kullanilir(self):
		self.guard.claim(self.job)
		self.guard.complete(self.job, {"width": 2400})
		sonraki = self.guard.claim(self.job)
		self.assertFalse(sonraki.granted)
		self.assertFalse(sonraki.running)
		self.assertEqual(sonraki.result, {"width": 2400})
		self.assertEqual(sonraki.state, J.STATE_COMPLETED)

	def test_sonuc_ttl_dolunca_is_yeniden_yapilir(self):
		self.guard.claim(self.job)
		self.guard.complete(self.job, {"width": 2400})
		self.simdi[0] += 601
		self.assertTrue(self.guard.claim(self.job).granted)

	def test_kilit_ttl_dolunca_dusen_worker_engel_olmaz(self):
		"""Worker düşerse dosya sonsuza kadar kilitli kalmaz."""
		self.assertTrue(self.guard.claim(self.job).granted)
		self.assertFalse(self.guard.claim(self.job).granted)
		self.simdi[0] += 61
		self.assertTrue(self.guard.claim(self.job).granted)

	def test_hata_sonrasi_backoff_icinde_tekrar_alinmaz(self):
		self.guard.claim(self.job)
		self.guard.fail(self.job, "ffmpeg düştü")
		self.assertEqual(self.guard.state_of(self.job.key), J.STATE_ERROR)
		# Hata kaydı duruyor ama deneme hakkı varsa yeniden alınabilir:
		# backoff zamanlaması kuyruğun işi, kilit yalnız çakışmayı önler.
		tekrar = self.job.retry()
		self.assertTrue(self.guard.claim(tekrar).granted)

	def test_hak_tukendiyse_hata_kaydi_kilit_gibi_davranir(self):
		bitmis = J.JobEnvelope.build(
			J.JOB_MASTER, "/f.jpg", content_hash="e" * 64, attempt=J.MAX_ATTEMPTS
		)
		self.guard.claim(bitmis)
		self.guard.fail(bitmis, "üç denemede de düştü")
		sonuc = self.guard.claim(bitmis)
		self.assertFalse(sonuc.granted)
		self.assertEqual(sonuc.state, J.STATE_ERROR)

	def test_complete_terminal_olmayan_durumu_reddeder(self):
		self.guard.claim(self.job)
		with self.assertRaises(ValueError):
			self.guard.complete(self.job, None, state=J.STATE_RUNNING)

	def test_forget_kilidi_acar(self):
		self.guard.claim(self.job)
		self.guard.forget(self.job.key)
		self.assertEqual(len(self.guard), 0)
		self.assertTrue(self.guard.claim(self.job).granted)

	def test_farkli_isler_birbirini_kilitlemez(self):
		a = J.JobEnvelope.build(J.JOB_DERIVE, "/f.jpg", content_hash="e" * 64, params={"w": 96})
		b = J.JobEnvelope.build(J.JOB_DERIVE, "/f.jpg", content_hash="e" * 64, params={"w": 1920})
		self.assertTrue(self.guard.claim(a).granted)
		self.assertTrue(self.guard.claim(b).granted)


class PaketIskeletiTesti(unittest.TestCase):
	"""Faz 3 sonunda hangi modülün gerçek kod olduğu makine okunur olmalı."""

	def test_alt_paketlerin_hepsi_import_edilebiliyor(self):
		import tradehub_core.media.pipeline as media_engine
		import tradehub_core.media.pipeline.api
		import tradehub_core.media.pipeline.core
		import tradehub_core.media.pipeline.delivery
		import tradehub_core.media.pipeline.image
		import tradehub_core.media.pipeline.policy
		import tradehub_core.media.pipeline.storage
		import tradehub_core.media.pipeline.video

		self.assertTrue(media_engine.__version__)

	def test_iskelet_paketler_kendini_iskelet_ilan_ediyor(self):
		"""İskelet paket `IMPLEMENTED = False` taşır — "kod mu" sorusu tahmine kalmaz."""
		import tradehub_core.media.pipeline as media_engine
		import tradehub_core.media.pipeline.api
		import tradehub_core.media.pipeline.delivery
		import tradehub_core.media.pipeline.image
		import tradehub_core.media.pipeline.storage
		import tradehub_core.media.pipeline.video

		# Faz 6 ile storage/image/video, Faz 8 (T-080…T-085) ile api/delivery
		# GERÇEK koda döndü. Artık iskelet paket YOK. Bayrak gerçeği söylemek
		# zorunda: iskelet olmayanı iskelet ilan etmek de iskeleti kod ilan
		# etmek kadar yanlıştır.
		ISKELETLER: tuple = ()
		for paket in ISKELETLER:
			with self.subTest(paket=paket.__name__):
				self.assertFalse(paket.IMPLEMENTED)
				self.assertTrue(paket.__doc__ and "İSKELET" in paket.__doc__)

		for paket in (
			media_engine.storage,
			media_engine.image,
			media_engine.video,
			media_engine.api,
			media_engine.delivery,
		):
			with self.subTest(paket=paket.__name__, durum="uygulandı"):
				self.assertTrue(paket.IMPLEMENTED)
				self.assertNotIn("İSKELET", paket.__doc__ or "")

	def test_kok_ozet_sozlugu_paket_bayraklariyla_ortusuyor(self):
		"""`media_engine.IMPLEMENTED` özeti ile paketlerin kendi bayrağı ayrışmamalı."""
		import importlib

		import tradehub_core.media.pipeline as media_engine

		for ad, beklenen in media_engine.IMPLEMENTED.items():
			if "." in ad:
				continue
			paket = importlib.import_module(f"tradehub_core.media.pipeline.{ad}")
			with self.subTest(paket=ad):
				self.assertEqual(bool(paket.IMPLEMENTED), bool(beklenen))

	def test_gercek_modullerin_apisi_yerinde(self):
		"""T-033/T-034 modülleri iskelet değil: giriş noktaları çağrılabilir."""
		from tradehub_core.media.pipeline.core.jobs import InMemoryGuard, JobEnvelope, idempotency_key
		from tradehub_core.media.pipeline.core.probe import MediaProbe, probe_bytes
		from tradehub_core.media.pipeline.core.state import consistent, ingest_transition
		from tradehub_core.media.pipeline.policy.engine import PolicyEngine, PolicyRegistry

		for nesne in (
			InMemoryGuard,
			JobEnvelope,
			idempotency_key,
			MediaProbe,
			probe_bytes,
			consistent,
			ingest_transition,
			PolicyEngine,
			PolicyRegistry,
		):
			self.assertTrue(callable(nesne))

	def test_cekirdekte_frappe_importu_yok(self):
		"""`import frappe` yalnız `api/` içinde ve orada da tembel olmalı."""
		import ast as _ast

		kok = ROOT / "media_engine"
		suclu = []
		for yol in sorted(kok.rglob("*.py")):
			if yol.parts[-2] == "api":
				continue
			agac = _ast.parse(yol.read_text(encoding="utf-8"))
			# YALNIZ modül düzeyi. Fonksiyon içindeki geç (lazy) `import
			# frappe` meşrudur ve bilinçli olarak kullanılıyor — paket yine
			# frappe olmadan import edilebilir kalır. `try:` bloğu da modül
			# düzeyi sayılır: `core/jobs.py` üretim modülünü oradan alıyor.
			ust: list = []
			for node in agac.body:
				ust.append(node)
				if isinstance(node, _ast.Try):
					ust.extend(node.body)
					for h in node.handlers:
						ust.extend(h.body)
			for node in ust:
				if isinstance(node, _ast.Import):
					if any(a.name.split(".")[0] == "frappe" for a in node.names):
						suclu.append(str(yol.relative_to(ROOT)))
				elif isinstance(node, _ast.ImportFrom):
					if (node.module or "").split(".")[0] == "frappe":
						suclu.append(str(yol.relative_to(ROOT)))
		self.assertEqual(suclu, [])

	def test_uretim_agacina_yazilmadi(self):
		"""MUTLAK KURAL: `tradehub_core/` altına hiçbir yeni dosya konmadı."""
		self.assertFalse((ROOT / "tradehub_core" / "media_engine").exists())
		self.assertFalse((ROOT / "tradehub_core" / "media" / "policy").exists())


if __name__ == "__main__":
	unittest.main(verbosity=2)
