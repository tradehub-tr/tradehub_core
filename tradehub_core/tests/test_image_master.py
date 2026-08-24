"""T-061/T-062 production master karar tablosu testleri."""

from __future__ import annotations

import io
import unittest

from PIL import Image

from tradehub_core.media.pipeline.image import classify, master

POLICY = {
	"master": {
		"max_long_edge": 240,
		"min_long_edge": 200,
		"max_megapixels": 0.0576,
		"dpi_out": 72,
		"colorspace": "srgb",
		# Slot dosyasındaki tarihsel WebP değeri sınıf tablosuyla değiştirilir.
		"format": "webp",
		"orientation": "apply_exif",
		"strip_metadata": {"exif": True, "gps": True, "xmp": True, "icc": False},
	}
}


def _image(mode: str, color, *, dpi=(300, 300)) -> bytes:
	buf = io.BytesIO()
	Image.new(mode, (300, 300), color).save(buf, "PNG", dpi=dpi)
	return buf.getvalue()


def _decision(klass: str, confidence: str = "high") -> classify.Classification:
	return classify.Classification(
		klass=klass,
		confidence=confidence,
		chain=classify.format_chain(klass, {"AVIF": True, "WEBP": True, "JPEG": True, "PNG": True, "WEBP:lossless": True, "AVIF:alpha": True, "WEBP:alpha": True}),
	)


class MasterAAA(unittest.TestCase):
	def test_photo_uses_jpeg_q88_and_writes_72_dpi(self) -> None:
		result = master.make_master(
			_image("RGB", (80, 120, 160)),
			POLICY,
			classification=_decision(classify.SINIF_PHOTO),
		)

		self.assertTrue(result.ok, result.reason)
		self.assertEqual(result.format, "JPEG")
		self.assertEqual((result.normalized.width, result.normalized.height), (240, 240))
		self.assertTrue(result.normalized.dpi_written)
		self.assertAlmostEqual(result.normalized.dpi[0], 72, delta=0.1)

	def test_transparent_master_is_lossless_png_with_alpha(self) -> None:
		result = master.make_master(
			_image("RGBA", (20, 40, 60, 100)),
			POLICY,
			classification=_decision(classify.SINIF_TRANSPARENT, "exact"),
		)

		self.assertTrue(result.ok, result.reason)
		self.assertEqual(result.format, "PNG")
		self.assertTrue(result.normalized.has_alpha)
		self.assertTrue(result.normalized.dpi_written)

	def test_low_confidence_photo_uses_safe_lossless_master(self) -> None:
		result = master.make_master(
			_image("RGB", (255, 255, 255)),
			POLICY,
			classification=_decision(classify.SINIF_PHOTO, "low"),
		)

		self.assertTrue(result.ok, result.reason)
		self.assertEqual(result.format, "PNG")

	def test_animation_is_never_flattened_to_image_master(self) -> None:
		decision = _decision(classify.SINIF_ANIMATION, "exact")
		decision = classify.Classification(
			klass=decision.klass,
			confidence=decision.confidence,
			target_pipeline=classify.PIPELINE_VIDEO,
			job_type=classify.JOB_TYPE_VIDEO_FROM_ANIMATION,
		)

		result = master.make_master(_image("RGB", (0, 0, 0)), POLICY, classification=decision)

		self.assertFalse(result.ok)
		self.assertEqual(result.reason, classify.JOB_TYPE_VIDEO_FROM_ANIMATION)


if __name__ == "__main__":
	unittest.main()
