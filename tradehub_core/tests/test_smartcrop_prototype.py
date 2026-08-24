"""T-014 üç yöntemli smartcrop prototipi testleri."""

from __future__ import annotations

import unittest

from tradehub_core.media.pipeline.core.smartcrop import (
	METHOD_BACKGROUND,
	METHOD_ENTROPY_EDGE,
	METHOD_ONNX,
	SmartcropError,
	background_segmentation,
	entropy_edge,
	normalized_error,
	onnx_u2netp,
)


def product(*, box=(130, 35, 190, 105), background=(250, 250, 250), foreground=(200, 20, 30)):
	from PIL import Image, ImageDraw

	image = Image.new("RGB", (200, 140), background)
	ImageDraw.Draw(image).rectangle(box, fill=foreground)
	return image


class FakeInput:
	name = "input.1"


class FakeSession:
	def get_inputs(self):
		return [FakeInput()]

	def run(self, _outputs, feed):
		import numpy as np

		assert feed["input.1"].shape == (1, 3, 320, 320)
		mask = np.zeros((1, 1, 320, 320), dtype=np.float32)
		mask[:, :, 80:240, 200:300] = 1.0
		return [mask]


class SmartcropPrototypeTest(unittest.TestCase):
	def test_arka_plan_segmentasyonu_sagdaki_urunu_bulur(self):
		prediction = background_segmentation(product())
		self.assertEqual(prediction.method, METHOD_BACKGROUND)
		self.assertGreater(prediction.focal_x, 0.65)
		self.assertGreater(prediction.confidence, 0.1)
		self.assertLess(prediction.runtime_ms, 1000)

	def test_entropi_kenar_sagdaki_urune_yaklasir(self):
		prediction = entropy_edge(product())
		self.assertEqual(prediction.method, METHOD_ENTROPY_EDGE)
		self.assertGreater(prediction.focal_x, 0.55)
		self.assertGreater(prediction.working_set_estimate_bytes, 0)

	def test_duz_beyaz_zemin_bilmiyorum_der(self):
		from PIL import Image

		flat = Image.new("RGB", (200, 140), "white")
		for method in (entropy_edge, background_segmentation):
			with self.subTest(method=method.__name__):
				prediction = method(flat)
				self.assertEqual(prediction.confidence, 0.0)
				self.assertEqual((prediction.focal_x, prediction.focal_y), (0.5, 0.5))

	def test_onnx_adapteri_normalized_maskeden_odak_cikarir(self):
		prediction = onnx_u2netp(product(), session=FakeSession())
		self.assertEqual(prediction.method, METHOD_ONNX)
		self.assertGreater(prediction.focal_x, 0.7)
		self.assertAlmostEqual(prediction.focal_y, 0.5, delta=0.02)

	def test_onnx_model_yokken_uydurmaz(self):
		with self.assertRaises(SmartcropError):
			onnx_u2netp(product())

	def test_normalize_hata_kose_kose_bir(self):
		from tradehub_core.media.pipeline.core.smartcrop import SmartcropPrediction

		prediction = SmartcropPrediction("x", 1.0, 1.0, 1.0, (0, 0, 1, 1), 0.0, 0)
		self.assertAlmostEqual(normalized_error(prediction, 0.0, 0.0), 1.0)


if __name__ == "__main__":
	unittest.main()
