# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-061/062/065 — `Media Version` zenginleştirme testleri.

İki katman test edilir:

1. **Saf katman** (`pipeline/image/enrich.py`): iki FARKLI görüntü iki FARKLI
   LQIP üretir (değer görüntüden türer, sabit değildir), hash <30 bayt kalır,
   alfa/sınıf/zincir doğru çıkar, data URI gerçekten çözülebilir bir PNG'dir.
2. **Üretim yolu** (`doctype/media_version.py::before_insert`): sürüm kaydı
   açılınca alanlar DOLAR. Vacuity kontrolü: üretim çağrısı
   (`_enrich_from_source`) kapatılınca aynı akış alanları BOŞ bırakır — yani
   "alanlar dolu" iddiası o çağrıya bağlıdır; çağrı silinirse
   `test_uretim_yolu_alanlari_doldurur` KIRMIZI olur.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_version_enrichment
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media.pipeline.contracts.storage import ObjectKey, ObjectRef
from tradehub_core.media.pipeline.delivery import manifest as manifest_mod
from tradehub_core.media.pipeline.image import classify as classify_mod
from tradehub_core.media.pipeline.image import enrich as enrich_mod
from tradehub_core.media.pipeline.image import lqip as lqip_mod
from tradehub_core.tradehub_core.doctype.media_version.media_version import (
	MediaVersion,
	enrich_version,
	version_enrichment_for_assets,
)

# Tarama kancası bu modülde nötrleniyor: `hold_until_clean` açıkken dosya
# insert anında public ağaçtan çıkarılıyor ve LQIP/zenginleştirme üretim yolu
# dosyayı bulamıyor. Gerekçe `tests/av_notr.py` başlığında.
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401

#: `lqip.py` sözleşme sınırı — ham hash bu sınırı aşamaz.
MAX_HASH_BYTES = lqip_mod.MAX_HASH_BYTES


def _jpeg_gradyan(seed: int = 0) -> bytes:
	"""Deterministik, fotoğraf sınıfına düşen degrade görüntü."""
	from PIL import Image

	im = Image.new("RGB", (160, 120))
	px = im.load()
	for x in range(160):
		for y in range(120):
			px[x, y] = ((x + seed * 40) % 256, (y * 2) % 256, (x + y) % 256)
	tampon = io.BytesIO()
	im.save(tampon, "JPEG", quality=90)
	return tampon.getvalue()


def _png_saydam_logo() -> bytes:
	"""Kesim logo: saydam zemin üstünde tek renkli dolu blok."""
	from PIL import Image

	im = Image.new("RGBA", (200, 160), (0, 0, 0, 0))
	blok = Image.new("RGBA", (120, 90), (200, 30, 30, 255))
	im.paste(blok, (40, 35))
	tampon = io.BytesIO()
	im.save(tampon, "PNG")
	return tampon.getvalue()


class EnrichPureTests(FrappeTestCase):
	"""Saf katman — DB'ye dokunmaz."""

	def test_iki_farkli_goruntu_iki_farkli_lqip(self):
		"""LQIP görüntünün İÇERİĞİNDEN türemeli; iki girdi iki hash."""
		e1 = enrich_mod.enrich(_jpeg_gradyan(0), filename="a.jpg")
		e2 = enrich_mod.enrich(_jpeg_gradyan(3), filename="b.jpg")
		self.assertTrue(e1.ok and e2.ok)
		self.assertTrue(e1.lqip and e2.lqip)
		self.assertNotEqual(e1.lqip, e2.lqip)
		self.assertNotEqual(e1.lqip_data_uri, e2.lqip_data_uri)

	def test_ayni_goruntu_ayni_lqip(self):
		"""Deterministiklik — idempotent yeniden işleme aynı değeri üretmeli."""
		kaynak = _jpeg_gradyan(1)
		self.assertEqual(
			enrich_mod.enrich(kaynak, filename="a.jpg").lqip,
			enrich_mod.enrich(kaynak, filename="a.jpg").lqip,
		)

	def test_hash_30_bayt_altinda(self):
		for kaynak, ad in ((_jpeg_gradyan(0), "a.jpg"), (_png_saydam_logo(), "logo.png")):
			e = enrich_mod.enrich(kaynak, filename=ad)
			self.assertTrue(e.lqip)
			self.assertLessEqual(len(base64.b64decode(e.lqip)), MAX_HASH_BYTES)

	def test_saydam_goruntu_kunyesi(self):
		"""Alfa → transparent sınıfı, alfa gerektiren zincir, saydamsız baskın renk."""
		e = enrich_mod.enrich(_png_saydam_logo(), filename="logo.png")
		self.assertTrue(e.ok)
		self.assertTrue(e.has_alpha)
		self.assertEqual(e.classification, classify_mod.SINIF_TRANSPARENT)
		beklenen = tuple(a.fmt for a in classify_mod.FORMAT_CHAINS[e.classification])
		self.assertEqual(e.format_chain_names, beklenen)
		# Baskın renk logonun kendisi olmalı, arkasındaki boşluk değil.
		self.assertEqual(e.dominant_color, "#c81818")

	def test_normalize_alanlari(self):
		"""T-061: ölçü kaynaktan, dpi/colorspace normalize kararından."""
		e = enrich_mod.enrich(_jpeg_gradyan(0), filename="a.jpg")
		self.assertEqual((e.width, e.height), (160, 120))
		self.assertEqual(e.dpi, 72)
		self.assertEqual(e.colorspace, "sRGB")
		self.assertFalse(e.has_alpha)

	def test_data_uri_cozulebilir_png(self):
		"""URI süsleme değil, gerçekten açılabilir bir görüntü olmalı."""
		from PIL import Image

		e = enrich_mod.enrich(_jpeg_gradyan(0), filename="a.jpg")
		onek = "data:image/png;base64,"
		self.assertTrue(e.lqip_data_uri.startswith(onek))
		im = Image.open(io.BytesIO(base64.b64decode(e.lqip_data_uri[len(onek):])))
		im.load()
		self.assertEqual(im.mode, "RGBA")
		# ThumbHash çözücüsü en uzun kenarı 32'ye kurar; oran korunur.
		self.assertEqual(max(im.size), 32)

	def test_bozuk_girdi_ok_false(self):
		e = enrich_mod.enrich(b"bu bir goruntu degil", filename="x.jpg")
		self.assertFalse(e.ok)
		self.assertTrue(e.reason)

	def test_manifest_version_meta_tasir(self):
		"""Teslim katmanı: `version_meta` süzülüp manifeste girer, iç alan sızmaz."""
		e = enrich_mod.enrich(_png_saydam_logo(), filename="logo.png")
		builder = manifest_mod.build_default()
		ref = ObjectRef(key=ObjectKey(shard="ab", name="ab12cd.png"))
		meta = dict(e.to_dict(), policy_snapshot="SIZMAMALI")
		sozluk = builder.build_image("product.image", ref, version_meta=meta).to_dict()
		self.assertEqual(sozluk["lqip"], e.lqip_data_uri)
		self.assertEqual(sozluk["dominant_color"], e.dominant_color)
		self.assertEqual(sozluk["version"]["classification"], "transparent")
		self.assertNotIn("policy_snapshot", sozluk["version"])
		# version_meta verilmeyince anahtarlar DURUR ama boştur — "üretilmedi"
		# bilgisi anahtar yokluğuyla değil boşlukla taşınır.
		bos = builder.build_image("product.image", ref).to_dict()
		self.assertEqual((bos["lqip"], bos["dominant_color"], bos["version"]), ("", "", {}))


class MediaVersionEnrichmentTests(FrappeTestCase):
	"""Üretim yolu — sürüm kaydı açılırken alanlar dolar."""

	def _fixture(self, kaynak: bytes, ad: str) -> tuple[str, str]:
		"""(File docname, Media Asset adı) — köprünün açtığı kayıtların taklidi."""
		dosya = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": ad,
				"is_private": 0,
				"content": kaynak,
			}
		).insert(ignore_permissions=True)
		# Sistem kaydı: test kendi kiracısını kurmuyor, sahiplik konu dışı.
		varlik = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": "product.image",
				"media_type": "image",
				"state": "processing",
				"source_file": dosya.name,
				"content_sha256": hashlib.sha256(kaynak).hexdigest()[:32],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(self._temizle, dosya.name, varlik.name)
		return dosya.name, varlik.name

	@staticmethod
	def _temizle(dosya: str, varlik: str) -> None:
		frappe.db.delete("Media Version", {"asset": varlik})
		frappe.delete_doc("Media Asset", varlik, ignore_permissions=True, force=True)
		frappe.delete_doc("File", dosya, ignore_permissions=True, force=True)

	def _surum_ac(self, varlik: str, kaynak: bytes):
		"""`pipeline_bridge._ensure_version` ile AYNI alan kümesi."""
		return frappe.get_doc(
			{
				"doctype": "Media Version",
				"asset": varlik,
				"version_hash": hashlib.sha256(kaynak + b"|test-surum").hexdigest(),
				"source_hash": hashlib.sha256(kaynak).hexdigest(),
				"policy_snapshot": "{}",
				"engine_version": "pillow-test",
				"is_active": 0,
			}
		).insert(ignore_permissions=True)

	def test_uretim_yolu_alanlari_doldurur(self):
		"""Sürüm açılınca T-061/062/065 alanları DOLU olmalı."""
		kaynak = _png_saydam_logo()
		_, varlik = self._fixture(kaynak, "enrich-logo.png")
		surum = self._surum_ac(varlik, kaynak)

		self.assertTrue(surum.lqip, "lqip boş — üretim yolu çağrılmamış")
		self.assertLessEqual(len(base64.b64decode(surum.lqip)), MAX_HASH_BYTES)
		self.assertTrue(surum.lqip_data_uri.startswith("data:image/png;base64,"))
		self.assertEqual(surum.dominant_color, "#c81818")
		self.assertEqual(surum.classification, "transparent")
		self.assertTrue(surum.has_alpha)
		self.assertEqual((surum.width, surum.height), (200, 160))
		self.assertEqual((surum.dpi, surum.colorspace), (72, "sRGB"))
		zincir = json.loads(surum.format_chain)
		self.assertEqual([a["fmt"] for a in zincir], ["AVIF", "WEBP", "PNG"])

		# DB satırı da aynı değerleri taşımalı (yalnız bellek nesnesi değil).
		db = frappe.db.get_value(
			"Media Version", surum.name, ["lqip", "classification"], as_dict=True
		)
		self.assertEqual((db.lqip, db.classification), (surum.lqip, "transparent"))

	def test_iki_kaynak_iki_lqip_db(self):
		"""Uçtan uca: iki farklı dosya → iki farklı kalıcı LQIP."""
		k1, k2 = _jpeg_gradyan(0), _jpeg_gradyan(5)
		_, v1 = self._fixture(k1, "enrich-a.jpg")
		_, v2 = self._fixture(k2, "enrich-b.jpg")
		s1, s2 = self._surum_ac(v1, k1), self._surum_ac(v2, k2)
		self.assertTrue(s1.lqip and s2.lqip)
		self.assertNotEqual(s1.lqip, s2.lqip)

	def test_vacuity_uretim_cagrisi_olmadan_alanlar_bos(self):
		"""Üretim çağrısı kapatılınca alanlar BOŞ kalmalı.

		Bu, `test_uretim_yolu_alanlari_doldurur`'un vacuous olmadığının
		kanıtı: alanları dolduran TEK şey `before_insert` içindeki
		`_enrich_from_source` çağrısıdır — çağrı üretimden silinirse asıl
		test kırmızıya düşer, başka bir yol alanları sessizce doldurmaz.
		"""
		kaynak = _jpeg_gradyan(2)
		_, varlik = self._fixture(kaynak, "enrich-vacuity.jpg")
		with mock.patch.object(MediaVersion, "_enrich_from_source", lambda self: None):
			surum = self._surum_ac(varlik, kaynak)
		self.assertFalse(surum.lqip)
		self.assertFalse(surum.classification)
		self.assertFalse(surum.dominant_color)
		self.assertFalse(int(surum.width or 0))

	def test_enrich_version_backfill(self):
		"""Alan eklenmeden ÖNCE açılmış (boş) kayıt sonradan doldurulabilmeli."""
		kaynak = _jpeg_gradyan(7)
		_, varlik = self._fixture(kaynak, "enrich-backfill.jpg")
		with mock.patch.object(MediaVersion, "_enrich_from_source", lambda self: None):
			surum = self._surum_ac(varlik, kaynak)
		self.assertFalse(surum.lqip)

		self.assertTrue(enrich_version(surum.name))
		db = frappe.db.get_value(
			"Media Version", surum.name, ["lqip", "classification", "width"], as_dict=True
		)
		self.assertTrue(db.lqip)
		self.assertEqual(db.classification, "photo")
		self.assertEqual(db.width, 160)
		# İkinci çağrı işlem yapmaz (idempotent) — dolu kaydı yeniden hesaplamaz.
		self.assertFalse(enrich_version(surum.name))

	def test_version_enrichment_for_assets(self):
		"""Uç sahiplerinin alt katman okuması: varlık → künye sözlüğü."""
		kaynak = _png_saydam_logo()
		_, varlik = self._fixture(kaynak, "enrich-read.png")
		self._surum_ac(varlik, kaynak)

		harita = version_enrichment_for_assets([varlik])
		self.assertIn(varlik, harita)
		kunye = harita[varlik]
		self.assertTrue(kunye["lqip"])
		self.assertEqual(kunye["classification"], "transparent")
		self.assertTrue(kunye["has_alpha"])
		# format_chain dizge değil ÇÖZÜLMÜŞ liste dönmeli.
		self.assertIsInstance(kunye["format_chain"], list)
		self.assertEqual(kunye["format_chain"][0]["fmt"], "AVIF")
		self.assertEqual(version_enrichment_for_assets([]), {})
