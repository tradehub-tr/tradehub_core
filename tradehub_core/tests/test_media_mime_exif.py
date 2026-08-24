"""MOGEM-580 — MIME validation and EXIF metadata policy closure tests."""

from __future__ import annotations

import hashlib
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from tradehub_core.media import exif_vault, upload_policy
from tradehub_core.media.pipeline.core import probe as core_probe
from tradehub_core.media.pipeline.image.normalize import NormalizeSpec, normalize
from tradehub_core.media.pipeline.image.probe import GuardConfig

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "images"
GEVSEK = GuardConfig(max_megapixels=200.0, max_bytes=64 * 1024 * 1024, allow_animated=True)


def _png() -> bytes:
	buf = io.BytesIO()
	Image.new("RGB", (32, 24), (25, 100, 180)).save(buf, "PNG")
	return buf.getvalue()


class MimeSozlesmesiTesti(unittest.TestCase):
	def test_magic_byte_mime_uzanti_beyanindan_bagimsizdir(self):
		kunye = upload_policy._slot_probe("yanlis.jpg", _png())
		self.assertEqual(kunye["extension"], ".jpg")
		self.assertEqual(kunye["detected"], "png")
		self.assertEqual(kunye["mime"], "image/png")

	def test_iki_probe_ortak_temel_turleri_ayni_tanir(self):
		ornekler = {
			"jpeg": b"\xff\xd8\xff\xe0" + b"x" * 32,
			"png": b"\x89PNG\r\n\x1a\n" + b"x" * 32,
			"gif": b"GIF89a" + b"x" * 32,
			"tiff": b"II*\x00" + b"x" * 32,
			"pdf": b"%PDF-1.7\n" + b"x" * 32,
			"mp4": b"\x00\x00\x00\x18ftypisom" + b"x" * 32,
			"webm": b"\x1a\x45\xdf\xa3" + b"x" * 32,
		}
		for beklenen, icerik in ornekler.items():
			with self.subTest(kind=beklenen):
				self.assertEqual(upload_policy.sniff(icerik), beklenen)
				self.assertEqual(core_probe.sniff(icerik), beklenen)

	def test_gorsel_uzantisi_altindaki_farkli_gorsel_reddedilir(self):
		with self.assertRaises(upload_policy.UploadRejected) as hata:
			upload_policy.check("yanlis.jpg", content=_png(), media_endpoint=True)
		self.assertIn(upload_policy.CONTENT_MISMATCH.kod, str(hata.exception))

	def test_boyut_tavanlari_tur_bazinda_tanimlidir(self):
		self.assertEqual(upload_policy.MAX_BYTES[upload_policy.KIND_IMAGE], 25 * 1024 * 1024)
		self.assertEqual(upload_policy.MAX_BYTES[upload_policy.KIND_VIDEO], 200 * 1024 * 1024)
		self.assertEqual(upload_policy.MAX_BYTES[upload_policy.KIND_DOCUMENT], 50 * 1024 * 1024)


class ExifSozlesmesiTesti(unittest.TestCase):
	def test_kasa_metadata_alani_sifreli_password_tipindedir(self):
		alan = exif_vault.frappe.get_meta("Media Metadata Vault").get_field("metadata_encrypted")
		self.assertIsNotNone(alan)
		self.assertEqual(alan.fieldtype, "Password")

	def test_kaynak_gps_kasada_gorulur_yayin_ciktisinda_silinir(self):
		kaynak = (IMAGES / "exif_gps.jpg").read_bytes()
		metadata = exif_vault.extract(kaynak)
		self.assertTrue(metadata["has_exif"])
		self.assertTrue(metadata["has_gps"])
		self.assertIn("GPSInfo", json.loads(metadata["raw"]))

		sonuc = normalize(kaynak, NormalizeSpec(), filename="exif_gps.jpg", guard=GEVSEK)
		self.assertTrue(sonuc.ok, sonuc.reason)
		with Image.open(io.BytesIO(sonuc.content)) as yayin:
			self.assertFalse(yayin.getexif().get(0x8825))
			self.assertFalse(yayin.getexif().get_ifd(0x8825))

	def test_orientation_kasada_gecerli_aralikta_tutulur(self):
		metadata = exif_vault.extract((IMAGES / "exif_orientation6.jpg").read_bytes())
		self.assertEqual(metadata["orientation"], 6)

	def test_bozuk_orientation_ve_tarih_guvenli_varsayilana_duser(self):
		class FakeExif(dict):
			def get_ifd(self, _tag):
				raise ValueError("bozuk GPS IFD")

		class FakeImage:
			def __enter__(self):
				return self

			def __exit__(self, *_args):
				return False

			def getexif(self):
				return FakeExif(
					{
						exif_vault.ORIENTATION: "gecersiz",
						exif_vault.DATETIME_ORIGINAL: "2026:99:99 88:77:66",
					}
				)

		with mock.patch.object(Image, "open", return_value=FakeImage()):
			metadata = exif_vault.extract(b"sahte-gorsel")

		self.assertEqual(metadata["orientation"], 1)
		self.assertEqual(metadata["captured_at"], "")
		self.assertFalse(metadata["has_gps"])

	def test_kasa_hatasi_medya_isini_dusurmez_ve_loglanir(self):
		asset = SimpleNamespace(name="asset-1", source_file="file-1")
		with (
			mock.patch.object(exif_vault.frappe.db, "table_exists", return_value=True),
			mock.patch.object(exif_vault, "extract", side_effect=ValueError("bozuk metadata")),
			mock.patch.object(exif_vault.frappe, "get_traceback", return_value="trace"),
			mock.patch.object(exif_vault.frappe, "log_error") as log_error,
		):
			self.assertFalse(exif_vault.retain(asset, b"bozuk"))
		log_error.assert_called_once_with(title="media EXIF vault", message="trace")

	def test_kasa_kaydi_hash_ve_politika_surumu_tasir(self):
		asset = SimpleNamespace(name="asset-1", source_file="file-1")
		doc = SimpleNamespace(save=mock.Mock())
		metadata = {
			"raw": '{"Make":"Kamera"}',
			"has_exif": True,
			"has_gps": False,
			"orientation": 1,
			"captured_at": "2026-08-24 10:00:00",
		}
		with (
			mock.patch.object(exif_vault.frappe.db, "table_exists", return_value=True),
			mock.patch.object(exif_vault.frappe.db, "exists", return_value=None),
			mock.patch.object(exif_vault.frappe, "new_doc", return_value=doc),
			mock.patch.object(exif_vault, "extract", return_value=metadata),
		):
			self.assertTrue(exif_vault.retain(asset, b"kaynak"))

		self.assertEqual(doc.asset, asset.name)
		self.assertEqual(doc.source_file, asset.source_file)
		self.assertEqual(doc.metadata_policy, exif_vault.POLICY_VERSION)
		self.assertEqual(doc.metadata_encrypted, metadata["raw"])
		self.assertEqual(doc.metadata_sha256, hashlib.sha256(metadata["raw"].encode()).hexdigest())
		doc.save.assert_called_once_with(ignore_permissions=True)


if __name__ == "__main__":
	unittest.main()
