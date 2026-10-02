"""Medya kuyruğu düşüşü — tanımsız kuyruk `long`'a gider, tanımlı olan aynen kalır.

2026-10-02 prod: Press bench'inde yalnız short/default/long worker'ı var,
`workers` anahtarı yok; `frappe.enqueue(queue="media-image-live")`
`ValidationError` atıyordu ve yüklenen görselin hiç `Media Asset`'i oluşmuyordu.

Saf-Python (bench gerekmez):

    cd tradehub_core && python3 -m unittest tradehub_core.tests.test_media_queue_fallback
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

try:
	import frappe  # noqa: F401
except ImportError:
	_stub = types.ModuleType("frappe")
	_stub.logger = lambda *a, **k: mock.MagicMock()
	_stub.get_conf = lambda: {}
	sys.modules["frappe"] = _stub

from tradehub_core.media import queue_fallback  # noqa: E402
from tradehub_core.media.pipeline.core import queues  # noqa: E402

PROD_QUEUES = {"short": 300, "default": 300, "long": 1500}
LOCAL_QUEUES = {**PROD_QUEUES, **{spec.name: spec.timeout_seconds for spec in queues.QUEUE_SPECS}}


def _config(kuyruklar: dict[str, int] | None = None, *, hata: Exception | None = None):
	"""`frappe.utils.background_jobs.get_queues_timeout` sahtesiyle modül yaması."""
	bg = types.ModuleType("frappe.utils.background_jobs")
	if hata is not None:

		def _patla():
			raise hata

		bg.get_queues_timeout = _patla
	else:
		bg.get_queues_timeout = lambda: dict(kuyruklar or {})
	utils = sys.modules.get("frappe.utils") or types.ModuleType("frappe.utils")
	return mock.patch.dict(sys.modules, {"frappe.utils": utils, "frappe.utils.background_jobs": bg})


class ResolveQueueTest(unittest.TestCase):
	def setUp(self) -> None:
		queue_fallback._LOGGED.clear()
		self.logger = mock.MagicMock()
		patcher = mock.patch.object(queue_fallback.frappe, "logger", return_value=self.logger, create=True)
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_prod_benzeri_tanimsiz_medya_kuyrugu_longa_duser(self):
		with _config(PROD_QUEUES):
			for spec in queues.QUEUE_SPECS:
				with self.subTest(queue=spec.name):
					self.assertEqual(queue_fallback.resolve_queue(spec.name), "long")
					self.assertFalse(queue_fallback.is_configured(spec.name))

	def test_tanimli_kuyruk_aynen_doner(self):
		with _config(LOCAL_QUEUES):
			for spec in queues.QUEUE_SPECS:
				with self.subTest(queue=spec.name):
					self.assertEqual(queue_fallback.resolve_queue(spec.name), spec.name)
		self.logger.warning.assert_not_called()

	def test_yerlesik_kuyruklar_her_zaman_aynen_doner(self):
		with _config(PROD_QUEUES):
			for ad in ("short", "default", "long"):
				self.assertEqual(queue_fallback.resolve_queue(ad), ad)

	def test_dusus_surec_basina_bir_kez_loglanir(self):
		with _config(PROD_QUEUES):
			for _ in range(5):
				queue_fallback.resolve_queue("media-image-live")
			queue_fallback.resolve_queue("media-video")
		self.assertEqual(self.logger.warning.call_count, 2)

	def test_yapilandirma_okunamazsa_eski_davranis_korunur(self):
		with _config(hata=RuntimeError("conf yok")):
			self.assertEqual(queue_fallback.resolve_queue("media-image-live"), "media-image-live")

	def test_dusus_kuyrugu_frappe_yerlesik_long(self):
		self.assertEqual(queue_fallback.FALLBACK_QUEUE, "long")
		self.assertIn(queue_fallback.FALLBACK_QUEUE, PROD_QUEUES)


class CagriYerleriTest(unittest.TestCase):
	"""Her medya `frappe.enqueue`'su medya kuyruğunu resolve_queue'dan geçirmeli."""

	MEDYA_ADLARI = (
		"RQ_QUEUE",
		"RQ_QUEUE_VIDEO",
		"RQ_QUEUE_BULK",
		"IMAGE_BULK.name",
		"IMAGE_LIVE.name",
		"VIDEO_RQ_QUEUE",
		"pipeline_bridge.RQ_QUEUE_BULK",
		'"media-image-live"',
		'"media-image-bulk"',
		'"media-video"',
		'"media-ai"',
		'"media-maint"',
	)

	def test_ham_medya_kuyrugu_ile_enqueue_kalmadi(self):
		kok = _APP_ROOT / "tradehub_core"
		ihlal: list[str] = []
		for yol in [*kok.joinpath("media").rglob("*.py"), *kok.joinpath("api").rglob("*.py")]:
			if "pipeline/simulator" in str(yol) or "pipeline/fakes" in str(yol):
				continue
			for no, satir in enumerate(yol.read_text(encoding="utf-8").splitlines(), 1):
				temiz = satir.strip()
				if any(temiz == f"queue={ad}," for ad in self.MEDYA_ADLARI):
					ihlal.append(f"{yol.relative_to(kok)}:{no}: {temiz}")
		self.assertEqual(ihlal, [])


if __name__ == "__main__":
	unittest.main()
