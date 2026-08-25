"""T-143 testleri — backfill orkestratörü, otomatik durdurma, atomik geçiş.

Sınanan beş şey (kaynak doküman T-143 kabul kriterleriyle birebir):

1. **Parti parti, düşük öncelikli kuyrukta.** Batch boyutu plana uyuyor,
   enqueue çağrısı `media-image-bulk` kuyruğuna gidiyor, canlı kuyrukla aynı
   kuyruk seçilirse yapılandırma REDDEDİLİYOR.
2. **Canlı trafik koruması.** Canlı kuyruk derinliği eşiği aşarsa batch
   ENQUEUE EDİLMİYOR; normale dönünce devam ediyor.
3. **Otomatik durdurma.** Hata oranı %2'yi aşınca kalan batch'ler enqueue
   edilmiyor. İkincil eşikler (`file_missing`, `decode_failed` > %1) ve
   `state="not_found"` (TTL doldu) de durduruyor — "ölçemedim" GEÇTİ
   SAYILMIYOR.
4. **Atomik geçiş.** Türev kümesi hazır olana kadar eski küme yayında;
   geçiş tek işlem. Eş zamanlı okuma testinde hiçbir okuyucu YARIM küme
   görmüyor (404'ün yapısal sebebi budur).
5. **Pano ve satıcı bildirimi.** İlerleme/hata oranı/tahmini bitiş üretiliyor,
   ölçülmemiş alan `None` kalıyor (0 değil); B sınıfı dosyalar için bildirim
   üretiliyor, A sınıfı için ÜRETİLMİYOR.

Koşum (frappe/site/bench/Redis GEREKMEZ):

    python3 -m unittest tests.test_migration_backfill -v

ÖLÇÜLMEYEN: gerçek `runner.run_batch` ile uçtan uca koşum. Bu testler sahte
bir `BatchRunner` kullanır; sahtenin gerçek runner'ın davranışını taklit ettiği
`migration.md` §4.1'deki dosya:satır okumalarına dayanır, ÖLÇÜLMEDİ.
"""

from __future__ import annotations

import sys
import threading
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.migration import backfill as bf  # noqa: E402

# ── Sahteler ────────────────────────────────────────────────────────────


class SahteRunner:
	"""`runner.run_batch` + `read_progress` taklidi.

	`sonuclar` listesi batch sırasına göre tüketilir; liste biterse son
	sonuç tekrarlanır. Böylece "üçüncü batch'te hata oranı fırlıyor" gibi
	senaryolar kurulabilir.
	"""

	def __init__(self, sonuclar: Sequence[Mapping[str, Any]] | None = None) -> None:
		self.sonuclar: list[Mapping[str, Any]] = list(sonuclar or [])
		self.cagrilar: list[dict[str, Any]] = []
		self._ilerleme: dict[str, Mapping[str, Any]] = {}

	def _varsayilan(self, adet: int) -> dict[str, Any]:
		return {
			"state": bf.JOB_COMPLETED,
			"processed": adet,
			"optimized": adet,
			"skipped": 0,
			"errors": 0,
			"skip_reasons": {},
		}

	def enqueue(self, file_names: Sequence[str], *, job_key: str, queue: str, dry_run: bool) -> str:
		self.cagrilar.append(
			{"files": tuple(file_names), "job_key": job_key, "queue": queue, "dry_run": dry_run}
		)
		sira = len(self.cagrilar) - 1
		if self.sonuclar:
			ham = self.sonuclar[min(sira, len(self.sonuclar) - 1)]
			kayit = dict(self._varsayilan(len(file_names)))
			kayit.update(ham)
		else:
			kayit = self._varsayilan(len(file_names))
		self._ilerleme[job_key] = kayit
		return job_key

	def progress(self, job_key: str) -> Mapping[str, Any]:
		return self._ilerleme.get(job_key, {"state": bf.JOB_NOT_FOUND})


class SahteKuyruk:
	"""Derinlik ölçer. `derinlikler` sırayla tüketilir, biterse son değer kalır."""

	def __init__(self, derinlikler: Sequence[int]) -> None:
		self.derinlikler = list(derinlikler)
		self.okumalar = 0

	def depth(self, queue: str) -> int:
		i = min(self.okumalar, len(self.derinlikler) - 1)
		self.okumalar += 1
		return self.derinlikler[i]


class SahteBildirim:
	def __init__(self) -> None:
		self.gonderilen: list[bf.SellerNotice] = []

	def notify(self, notice: bf.SellerNotice) -> None:
		self.gonderilen.append(notice)


def plan_uret(a: int = 450, b: int = 0) -> bf.BackfillPlan:
	return bf.BackfillPlan(
		a_class=tuple(f"FILE-A-{i:04d}" for i in range(a)),
		b_class=tuple(
			{"file_name": f"FILE-B-{i:04d}", "alt_sinif": "B1", "store": "SELLER-001"} for i in range(b)
		),
		slot_of={f"FILE-A-{i:04d}": "listing_main" for i in range(a)},
	)


def orkestrator(runner, **kwargs):
	"""Test orkestratörü: uyku YOK (sleep sahte), saat monoton sayaç."""
	sayac = {"t": 0.0}

	def saat() -> float:
		sayac["t"] += 1.0
		return sayac["t"]

	kwargs.setdefault("clock", saat)
	kwargs.setdefault("sleep", lambda _s: None)
	return bf.BackfillOrchestrator(runner, **kwargs)


# ═══════════════════════════════════════════════════════════════════════
# 1. Plan ve batch kesme
# ═══════════════════════════════════════════════════════════════════════


class PlanTesti(unittest.TestCase):
	def test_batch_boyutu_plandan_gelir(self):
		"""§4.2 — varsayılan 200; 450 dosya → 200 + 200 + 50."""
		self.assertEqual(bf.DEFAULT_BATCH_SIZE, 200)
		batchler = plan_uret(450).batches()

		self.assertEqual([b.size for b in batchler], [200, 200, 50])
		self.assertEqual([b.index for b in batchler], [1, 2, 3])

	def test_job_key_kararli_ve_okunabilir(self):
		batch = plan_uret(10).batches()[0]
		self.assertEqual(batch.job_key, "backfill-0001")

	def test_sifir_batch_boyutu_reddedilir(self):
		with self.assertRaises(bf.BackfillError):
			plan_uret(10).batches(0)

	def test_plan_json_a_ve_b_sinifini_ayirir(self):
		veri = bf.stamp_plan(
			{
				"kaynak": "plan_backfill.py",
				"kayitlar": [
					{"file_name": "a1", "sinif": "A", "slots": ["listing_main"]},
					{"file_name": "a2", "sinif": "A'"},
					{"file_name": "b1", "sinif": "B1"},
					{"file_name": "c1", "sinif": "C"},
				],
			}
		)
		plan = bf.BackfillPlan.from_plan_json(veri)

		self.assertEqual(plan.a_class, ("a1",))
		self.assertEqual(tuple(row["file_name"] for row in plan.unsupported_a), ("a2",))
		self.assertEqual(len(plan.b_class), 1)
		self.assertEqual(plan.slot_of["a1"], "listing_main")

	def test_bilinmiyor_B_sinifi_gibi_calistirilmaz(self):
		veri = bf.stamp_plan(
			{"records": [{"file_name": "probe-edilmedi", "class": "BILINMIYOR", "file_url": "/files/x.jpg"}]}
		)
		plan = bf.BackfillPlan.from_plan_json(veri)

		self.assertEqual(plan.unknown_count, 1)
		self.assertEqual(plan.b_class, ())

	def test_bozuk_plan_hata_verir(self):
		with self.assertRaises(bf.BackfillError):
			bf.BackfillPlan.from_plan_json([])  # type: ignore[arg-type]

	def test_planlayicinin_eski_rep_name_alani_gecis_icin_okunur(self):
		veri = bf.stamp_plan(
			{"records": [{"rep_name": "FILE-1", "class": "A_otomatik", "file_url": "/files/a.jpg"}]}
		)
		plan = bf.BackfillPlan.from_plan_json(veri)
		self.assertEqual(plan.a_class, ("FILE-1",))
		self.assertEqual(plan.records[0]["file_name"], "FILE-1")

	def test_plan_ozeti_degisen_icerigi_reddeder(self):
		veri = bf.stamp_plan({"records": [{"file_name": "FILE-1", "class": "A", "file_url": "/files/a.jpg"}]})
		veri["records"][0]["file_url"] = "/files/degisti.jpg"
		with self.assertRaises(bf.BackfillError):
			bf.BackfillPlan.from_plan_json(veri)

	def test_a_b_sinifinda_kimlik_eksigi_sessizce_atlanmaz(self):
		veri = bf.stamp_plan({"records": [{"class": "A_otomatik", "file_url": "/files/a.jpg"}]})
		with self.assertRaises(bf.BackfillError):
			bf.BackfillPlan.from_plan_json(veri)


# ═══════════════════════════════════════════════════════════════════════
# 2. Kuyruk disiplini
# ═══════════════════════════════════════════════════════════════════════


class KuyrukDisiplinTesti(unittest.TestCase):
	def test_backfill_ayri_kuyruga_gider(self):
		"""§5.2 — canlı ve bulk medya kanonik ayrı kuyruklardadır."""
		runner = SahteRunner()
		orkestrator(runner).run(plan_uret(10), dry_run=True)

		self.assertEqual(runner.cagrilar[0]["queue"], "media-image-bulk")
		self.assertNotEqual(runner.cagrilar[0]["queue"], bf.DEFAULT_LIVE_QUEUE)

	def test_canli_kuyrukla_ayni_kuyruk_REDDEDILIR(self):
		"""Aynı kuyrukta öncelik ayrımı YOKTUR — yapılandırma kabul edilmez."""
		with self.assertRaises(bf.BackfillError):
			bf.BackfillConfig(queue="media-image-live", live_queue="media-image-live")

	def test_canli_kuyruk_doluyken_enqueue_edilmez(self):
		"""§5.3 — derinlik > eşik iken batch kuyruğa KONMAZ."""
		runner = SahteRunner()
		kuyruk = SahteKuyruk([5])  # hep dolu
		orch = orkestrator(runner, queue_probe=kuyruk, config=bf.BackfillConfig(pause_limit=3))

		rapor = orch.run(plan_uret(10), dry_run=True)

		self.assertEqual(rapor.state, bf.RUN_PAUSED)
		self.assertEqual(runner.cagrilar, [], "canlı kuyruk doluyken batch enqueue edildi")

	def test_kuyruk_bosalinca_devam_eder(self):
		runner = SahteRunner()
		kuyruk = SahteKuyruk([3, 2, 0])
		orch = orkestrator(runner, queue_probe=kuyruk, config=bf.BackfillConfig(pause_limit=5))

		rapor = orch.run(plan_uret(10), dry_run=True)

		self.assertEqual(rapor.state, bf.RUN_COMPLETED)
		self.assertEqual(len(runner.cagrilar), 1)

	def test_derinlik_olculemiyorsa_bu_da_kaydedilir(self):
		"""Prob yoksa kapı açık sayılır ama 'ölçülmedi' diye işaretlenir."""
		runner = SahteRunner()
		orch = orkestrator(runner)

		rapor = orch.run(plan_uret(10), dry_run=True)

		self.assertFalse(orch.guard.measurable)
		self.assertTrue(rapor.live_checks)
		self.assertFalse(rapor.live_checks[0]["measured"])

	def test_derinlik_okumasi_patlarsa_DURAKLAR(self):
		"""Ölçüm patladıysa 'temiz' varsayılmaz."""

		class Patlayan:
			def depth(self, queue: str) -> int:
				raise RuntimeError("redis yok")

		runner = SahteRunner()
		orch = orkestrator(runner, queue_probe=Patlayan(), config=bf.BackfillConfig(pause_limit=2))

		rapor = orch.run(plan_uret(10), dry_run=True)

		self.assertEqual(rapor.state, bf.RUN_PAUSED)
		self.assertEqual(runner.cagrilar, [])


# ═══════════════════════════════════════════════════════════════════════
# 3. Otomatik durdurma
# ═══════════════════════════════════════════════════════════════════════


class DurdurmaKriteriTesti(unittest.TestCase):
	def test_hata_orani_tanimi_skipped_i_saymaz(self):
		"""§7.1 — `errors / processed`; `skipped` HATA DEĞİLDİR."""
		oran = bf.error_rate({"processed": 100, "errors": 2, "skipped": 90})
		self.assertAlmostEqual(oran, 0.02)

	def test_sifir_islenende_bolme_yok(self):
		self.assertEqual(bf.error_rate({"processed": 0, "errors": 0}), 0.0)

	def test_esigin_tam_ustunde_durur_esitte_durmaz(self):
		esik = bf.StopPolicy()
		esitte = bf.evaluate_stop(
			{"state": bf.JOB_PARTIAL, "processed": 100, "errors": 2, "skip_reasons": {}}, esik
		)
		ustunde = bf.evaluate_stop(
			{"state": bf.JOB_PARTIAL, "processed": 100, "errors": 3, "skip_reasons": {}}, esik
		)

		self.assertFalse(esitte.halt, "tam %2 durdurmamalı — kriter '> %2'")
		self.assertTrue(ustunde.halt)
		self.assertEqual(ustunde.code, bf.STOP_ERROR_RATE)

	def test_ikincil_esik_file_missing(self):
		karar = bf.evaluate_stop(
			{
				"state": bf.JOB_COMPLETED,
				"processed": 200,
				"errors": 0,
				"skip_reasons": {"file_missing": 3},
			}
		)
		self.assertTrue(karar.halt)
		self.assertEqual(karar.code, bf.STOP_SKIP_REASON)
		self.assertEqual(karar.measured["skip_reason"], "file_missing")

	def test_ikincil_esik_decode_failed(self):
		karar = bf.evaluate_stop(
			{
				"state": bf.JOB_COMPLETED,
				"processed": 200,
				"errors": 0,
				"skip_reasons": {"decode_failed": 3},
			}
		)
		self.assertTrue(karar.halt)
		self.assertEqual(karar.measured["skip_reason"], "decode_failed")

	def test_izlenmeyen_skip_sebebi_durdurmaz(self):
		"""Kapı 4'e takılmak (`already_small`) BEKLENEN davranıştır."""
		karar = bf.evaluate_stop(
			{
				"state": bf.JOB_COMPLETED,
				"processed": 200,
				"errors": 0,
				"skip_reasons": {"already_small": 190},
			}
		)
		self.assertFalse(karar.halt)

	def test_not_found_gecti_SAYILMAZ(self):
		"""§7.3 — TTL dolduysa hata oranı BİLİNMİYOR demektir; durulur."""
		karar = bf.evaluate_stop({"state": bf.JOB_NOT_FOUND})

		self.assertTrue(karar.halt)
		self.assertEqual(karar.code, bf.STOP_PROGRESS_LOST)

	def test_terminal_olmayan_is_durdurur(self):
		karar = bf.evaluate_stop({"state": bf.JOB_RUNNING, "processed": 12})

		self.assertTrue(karar.halt)
		self.assertEqual(karar.code, bf.STOP_JOB_STUCK)
		self.assertEqual(karar.already_processed, 12)

	def test_gecersiz_politika_reddedilir(self):
		with self.assertRaises(bf.BackfillError):
			bf.StopPolicy(error_rate_max=0.0)
		with self.assertRaises(bf.BackfillError):
			bf.StopPolicy(skip_reason_max=1.5)


class OtomatikDurmaKosumTesti(unittest.TestCase):
	def test_esik_asilinca_kalan_batchler_enqueue_EDILMEZ(self):
		"""450 dosya = 3 batch; ikincisi %5 hata → üçüncü hiç kuyruğa girmez."""
		runner = SahteRunner(
			[
				{"state": bf.JOB_COMPLETED, "processed": 200, "errors": 0},
				{"state": bf.JOB_PARTIAL, "processed": 200, "errors": 10},
				{"state": bf.JOB_COMPLETED, "processed": 50, "errors": 0},
			]
		)
		rapor = orkestrator(runner).run(plan_uret(450), dry_run=False)

		self.assertEqual(rapor.state, bf.RUN_HALTED)
		self.assertEqual(len(runner.cagrilar), 2, "durdurmadan sonra üçüncü batch enqueue edildi")
		self.assertEqual(rapor.stop.code, bf.STOP_ERROR_RATE)

	def test_durdurma_kaydinda_ISLENMIS_dosya_sayisi_var(self):
		"""§7.2 sınırı gizlenmiyor: eşik aşılsa bile bir batch işlenmiş olur."""
		runner = SahteRunner([{"state": bf.JOB_PARTIAL, "processed": 200, "errors": 40}])
		rapor = orkestrator(runner).run(plan_uret(400), dry_run=False)

		self.assertTrue(rapor.stop.halt)
		self.assertEqual(rapor.stop.already_processed, 200)

	def test_temiz_kosum_tamamlanir(self):
		runner = SahteRunner()
		rapor = orkestrator(runner).run(plan_uret(450), dry_run=True)

		self.assertEqual(rapor.state, bf.RUN_COMPLETED)
		self.assertEqual(len(runner.cagrilar), 3)
		self.assertEqual(rapor.processed, 450)
		self.assertEqual(rapor.errors, 0)

	def test_varsayilan_kuru_kosumdur(self):
		"""Yanlışlıkla üretim koşumu başlatmak, yanlışlıkla kuru koşmaktan pahalı."""
		runner = SahteRunner()
		orkestrator(runner).run(plan_uret(10))

		self.assertTrue(runner.cagrilar[0]["dry_run"])

	def test_max_batches_ile_kademeli_kosum(self):
		runner = SahteRunner()
		rapor = orkestrator(runner).run(plan_uret(450), dry_run=True, max_batches=1)

		self.assertEqual(len(runner.cagrilar), 1)
		self.assertEqual(rapor.planned_batches, 3, "plan toplamı kırpılmamalı")


# ═══════════════════════════════════════════════════════════════════════
# 4. Atomik geçiş
# ═══════════════════════════════════════════════════════════════════════


class AtomikGecisTesti(unittest.TestCase):
	def setUp(self):
		self.switch = bf.AtomicSwitch()
		self.eski = ("/files/media/A/v1/card-640.webp", "/files/media/A/v1/zoom-2400.webp")
		self.yeni = ("/files/media/A/v2/card-640.webp", "/files/media/A/v2/zoom-2400.webp")
		self.switch.publish_initial("A", self.eski)

	def test_stage_yayina_dokunmaz(self):
		self.switch.stage("A", self.yeni[:1])

		self.assertEqual(self.switch.active("A"), self.eski, "raf yayını değiştirdi")

	def test_commit_tek_islemde_gecirir(self):
		self.switch.stage("A", self.yeni)
		self.switch.commit("A", expected=2)

		self.assertEqual(self.switch.active("A"), self.yeni)
		self.assertEqual(self.switch.staged("A"), ())

	def test_eksik_merdiven_commit_EDILEMEZ(self):
		self.switch.stage("A", self.yeni[:1])

		with self.assertRaises(bf.BackfillError):
			self.switch.commit("A", expected=2)
		self.assertEqual(self.switch.active("A"), self.eski, "eksik küme yayına girdi")

	def test_bos_kume_rafa_konamaz(self):
		with self.assertRaises(bf.BackfillError):
			self.switch.stage("A", [])

	def test_rollback_yayini_bozmaz(self):
		self.switch.stage("A", self.yeni)
		self.switch.rollback("A")

		self.assertEqual(self.switch.active("A"), self.eski)
		self.assertEqual(self.switch.staged("A"), ())
		self.assertEqual(self.switch.rollbacks, 1)

	def test_es_zamanli_okuma_YARIM_kume_gormez(self):
		"""Geçiş sırasında 404 oluşmadığının testi: her okuma TAM bir küme."""
		okumalar: list[tuple] = []
		dur = threading.Event()

		def okuyucu():
			while not dur.is_set():
				okumalar.append(self.switch.active("A"))

		t = threading.Thread(target=okuyucu, daemon=True)
		t.start()
		try:
			for i in range(200):
				sonek = f"v{i + 2}"
				self.switch.stage("A", tuple(u.replace("v1", sonek) for u in self.eski))
				self.switch.commit("A", expected=2)
		finally:
			dur.set()
			t.join(timeout=5)

		self.assertGreater(len(okumalar), 0, "okuyucu hiç okumadı — test bir şey kanıtlamıyor")
		for kume in okumalar:
			self.assertEqual(len(kume), 2, f"YARIM küme görüldü: {kume}")

	def test_hic_yayinlanmamis_varlik_bos_doner(self):
		self.assertEqual(self.switch.active("YOK"), ())


# ═══════════════════════════════════════════════════════════════════════
# 5. Pano ve satıcı bildirimi
# ═══════════════════════════════════════════════════════════════════════


class PanoTesti(unittest.TestCase):
	def test_pano_ilerleme_ve_hata_orani_tasir(self):
		# `processed` VERİLMEZ: sahte runner onu batch boyutundan türetir, yoksa
		# 50'lik son batch de 200 işlenmiş görünür ve toplam yalan olur.
		runner = SahteRunner([{"state": bf.JOB_COMPLETED, "errors": 1}])
		plan = plan_uret(450)
		orch = orkestrator(runner)
		rapor = orch.run(plan, dry_run=False)

		pano = orch.dashboard(rapor, plan)

		self.assertEqual(pano["planned_files"], 450)
		self.assertEqual(pano["processed"], 450)
		self.assertGreater(pano["error_rate"], 0.0)
		self.assertEqual(pano["error_rate_threshold"], 0.02)
		self.assertEqual(pano["per_slot"], {"listing_main": 450})

	def test_olculmemis_hiz_None_kalir_sifir_degil(self):
		"""Saat hiç ilerlemezse süre ölçülmemiştir; 0 yazmak yalan olur."""
		runner = SahteRunner()
		orch = bf.BackfillOrchestrator(runner, clock=lambda: 0.0, sleep=lambda _s: None)
		rapor = orch.run(plan_uret(10), dry_run=True)

		self.assertIsNone(rapor.avg_seconds_per_file)
		self.assertIsNone(rapor.eta_seconds())

	def test_eta_olculen_hizdan_turer(self):
		runner = SahteRunner()
		orch = orkestrator(runner)
		rapor = orch.run(plan_uret(450), dry_run=True, max_batches=1)

		self.assertIsNotNone(rapor.avg_seconds_per_file)
		self.assertIsNotNone(rapor.eta_seconds())
		self.assertGreater(rapor.eta_seconds(), 0.0, "kalan iş var ama ETA sıfır")

	def test_rapor_json_lanabilir(self):
		import json

		runner = SahteRunner()
		rapor = orkestrator(runner).run(plan_uret(10), dry_run=True)

		json.dumps(rapor.to_dict())  # istisna atmamalı


class SaticiBildirimiTesti(unittest.TestCase):
	def test_b_sinifi_icin_bildirim_uretilir(self):
		plan = plan_uret(a=10, b=3)
		bildirimler = bf.build_notices(plan)

		self.assertEqual(len(bildirimler), 3)
		self.assertEqual(bildirimler[0].subclass, "B1")
		self.assertIn("Çözünürlük yetersiz", bildirimler[0].message)
		self.assertEqual(bildirimler[0].deadline_days, 30)

	def test_a_sinifi_icin_bildirim_URETILMEZ(self):
		"""§6.1 — A sınıfında satıcının yapacağı bir şey yok, `file_url` değişmez."""
		bildirimler = bf.build_notices(plan_uret(a=100, b=0))

		self.assertEqual(bildirimler, ())

	def test_bilinmeyen_alt_sinif_genel_mesaja_duser(self):
		plan = bf.BackfillPlan(b_class=({"file_name": "x", "alt_sinif": "B9"},))
		(bildirim,) = bf.build_notices(plan)

		self.assertTrue(bildirim.message)
		self.assertEqual(bildirim.subclass, "B9")

	def test_bildirim_gonderilir(self):
		hedef = SahteBildirim()
		runner = SahteRunner()
		orch = orkestrator(runner, notifier=hedef)

		orch.run(plan_uret(a=10, b=2), dry_run=True, notify=True)

		self.assertEqual(len(hedef.gonderilen), 2)

	def test_notify_kapaliyken_gonderilmez(self):
		hedef = SahteBildirim()
		orch = orkestrator(SahteRunner(), notifier=hedef)

		orch.run(plan_uret(a=10, b=2), dry_run=True)

		self.assertEqual(hedef.gonderilen, [])


class PlatformBildirimSinkTesti(unittest.TestCase):
	"""Somut sink — `SellerNotice`'i `notify()` çağrısına sarar (rapor 98).

	`notify_fn`/`resolve_user_fn` enjekte edilerek canlı site OLMADAN sınanır:
	sink'in satıcıya doğru zarfı ürettiği, sahibi çözülemeyen mağazayı atladığı,
	e-posta seçeneğini ilettiği ve `run(notify=True)` yolundan uçtan uca çalıştığı.
	"""

	def _kayitli_sink(self, kullanicilar, **kw):
		cagrilar: list[dict[str, Any]] = []

		def sahte_notify(**kwargs):
			# Gerçek `notify` oluşan Platform Notification'ın `name`'ini döndürür.
			cagrilar.append(kwargs)
			return f"PN-{len(cagrilar):04d}"

		sink = bf.PlatformNotificationSink(
			notify_fn=sahte_notify,
			resolve_user_fn=lambda store: kullanicilar.get(store),
			**kw,
		)
		return sink, cagrilar

	def test_bildirim_saticiya_notify_ile_dusurulur(self):
		sink, cagrilar = self._kayitli_sink({"SELLER-001": "ali@example.com"})
		notice = bf.SellerNotice(
			store="SELLER-001",
			file_name="a.jpg",
			slot="listing_main",
			subclass="B1",
			message="Çözünürlük yetersiz",
		)

		sink.notify(notice)

		self.assertEqual(len(cagrilar), 1, "satıcıya tam bir Platform Notification düşmeli")
		c = cagrilar[0]
		self.assertEqual(c["recipient_user"], "ali@example.com")
		self.assertEqual(c["reference_doctype"], "Admin Seller Profile")
		self.assertEqual(c["reference_name"], "SELLER-001")
		self.assertEqual(c["message"], "Çözünürlük yetersiz")
		self.assertIn("a.jpg", c["title"])
		self.assertEqual(c["type"], bf.NOTICE_TYPE)
		self.assertFalse(c["send_email"])
		self.assertEqual(sink.sent, 1)
		self.assertEqual(sink.skipped, 0)

	def test_sahipsiz_magaza_atlanir_notify_EDILMEZ(self):
		sink, cagrilar = self._kayitli_sink({})  # hiçbir mağazanın sahibi yok
		sink.notify(bf.SellerNotice(store="YOK", file_name="x", slot="", subclass="B1", message="m"))

		self.assertEqual(cagrilar, [], "sahibi çözülemeyen mağazaya bildirim gitmez")
		self.assertEqual(sink.sent, 0)
		self.assertEqual(sink.skipped, 1, "sessizce düşmez — SAYILIR")

	def test_send_email_secenegi_notify_e_iletilir(self):
		sink, cagrilar = self._kayitli_sink({"S": "u@e.com"}, send_email=True)
		sink.notify(bf.SellerNotice(store="S", file_name="f", slot="", subclass="B2", message="m"))

		self.assertTrue(cagrilar[0]["send_email"], "e-posta seçeneği notify'a iletilmeli")

	def test_kucuk_backfill_sink_bagli_her_B_bildirimi_duser(self):
		"""≤5 dosyalık koşum + sink bağlı → her B bildirimi satıcıya düşer."""
		sink, cagrilar = self._kayitli_sink({"SELLER-001": "ali@example.com"})
		orch = orkestrator(SahteRunner(), notifier=sink)

		orch.run(plan_uret(a=5, b=2), dry_run=True, notify=True)

		self.assertEqual(len(cagrilar), 2)
		self.assertEqual(sink.sent, 2)

	def test_VACUITY_sink_yoksa_bildirim_gitmez(self):
		"""Somut sink olmadan: bildirim ÜRETİLİR ama kanal kopuk — gitmez."""
		orch = orkestrator(SahteRunner(), notifier=None)

		rapor = orch.run(plan_uret(a=5, b=2), dry_run=True, notify=True)

		# Bildirimler planda var; ne var ki somut sink bağlı değil — rapor 98'in
		# ölçtüğü hata tam buydu. Sink bağlanınca yukarıdaki test bunları taşır.
		self.assertEqual(len(rapor.notices), 2)


# ═══════════════════════════════════════════════════════════════════════
# 6. Kapasite aritmetiği
# ═══════════════════════════════════════════════════════════════════════


class KapasiteTesti(unittest.TestCase):
	def test_guvenli_batch_boyutu_formulu(self):
		"""1800 / (6 s × 3) = 100 — bulk worker timeout'u kullanılır."""
		self.assertEqual(bf.safe_batch_size(6.0), 100)

	def test_yavas_dosyada_batch_kuculur(self):
		self.assertLess(bf.safe_batch_size(60.0), bf.safe_batch_size(6.0))

	def test_olculmemis_hiz_reddedilir(self):
		"""Süre ölçülmediyse batch boyutu TÜRETİLEMEZ — sayı uydurulmaz."""
		with self.assertRaises(bf.BackfillError):
			bf.safe_batch_size(0.0)

	def test_batch_tavani_uygulanir(self):
		self.assertLessEqual(bf.safe_batch_size(0.001), 2000)

	def test_sure_tahmini(self):
		self.assertAlmostEqual(bf.estimate_duration(300, 6.0), 1800.0)
		self.assertAlmostEqual(bf.estimate_duration(300, 6.0, workers=2), 900.0)

	def test_sifir_worker_reddedilir(self):
		with self.assertRaises(bf.BackfillError):
			bf.estimate_duration(10, 1.0, workers=0)


# ═══════════════════════════════════════════════════════════════════════
# 7. Katman disiplini
# ═══════════════════════════════════════════════════════════════════════


class KatmanDisiplinTesti(unittest.TestCase):
	def test_modul_duzeyinde_frappe_importu_yok(self):
		"""Paket bench/site olmadan import edilebilir kalmalı."""
		import ast

		agac = ast.parse(
			(ROOT / "tradehub_core" / "media" / "pipeline" / "migration" / "backfill.py").read_text(
				encoding="utf-8"
			)
		)
		suclu = []
		for node in agac.body:
			if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "frappe" for a in node.names):
				suclu.append(node.lineno)
			elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "frappe":
				suclu.append(node.lineno)
		self.assertEqual(suclu, [])

	def test_uretim_agacina_yazilmadi(self):
		"""MUTLAK KURAL: `tradehub_core/` altına hiçbir şey konmadı."""
		self.assertFalse((ROOT / "tradehub_core" / "migration").exists())
		self.assertFalse((ROOT / "tradehub_core" / "media" / "backfill.py").exists())

	def test_paket_kendini_uygulandi_ilan_ediyor(self):
		import tradehub_core.media.pipeline as media_engine

		self.assertTrue(media_engine.migration.IMPLEMENTED)
		self.assertTrue(media_engine.IMPLEMENTED["migration"])


if __name__ == "__main__":
	unittest.main(verbosity=2)
