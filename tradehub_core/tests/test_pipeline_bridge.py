# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""`media.pipeline_bridge` testleri — Dalga A2 (türev üretimini tetikleme).

EN ÖNEMLİ TEST `test_bayrak_kapaliyken_enqueue_cagrilmaz`: bayrak kapalıyken
(varsayılan) kanca hiçbir şey yapmamalı. Dalga A'nın tüm güvencesi buna
yaslanıyor — kanca hooks.py'ye eklendi, ama sistemin bugünkü davranışı birebir
aynı kalmalı.

Eksenler:
  1. Bayrak KAPALI → `frappe.enqueue` hiç çağrılmaz.
  2. Bayrak AÇIK → `queue="media-image-live"`, `timeout=60`,
     `enqueue_after_commit=True`.
  3. İdempotency: aynı içerik+slot için türev zaten varsa ikinci kez iş açılmaz.
  4. Kapsam: private / KYB (KVKK kapsam dışı) / video / bilinmeyen slot muaf.
  5. Slot çözümü politikanın `bound_to` bloklarından okunur.
  6. Uçtan uca: `_run_rendition_job` gerçek görselden türev üretir, diske yazar,
     Media Asset/Rendition/Processing Job kayıtlarını açar.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_pipeline_bridge
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_manifest
from tradehub_core.media import pipeline_bridge, pipeline_flags

DOCTYPE_AYAR = pipeline_flags.SETTINGS_DOCTYPE
KORUNAN_ALANLAR = (
	"media_pipeline_enabled",
	"rendition_on_upload",
	"active_slots",
	"max_renditions_per_asset",
	"rollout_percent",
	"rollout_stores",
)

SLOT = "product.image"
PERF_FIXTURE = Path(__file__).parent / "fixtures" / "media" / "images" / "ok_product_1x1_2400.jpg"


def _gorsel_baytlari(kenar: int = 1200) -> bytes:
	"""Sıkışması mümkün, gerçek bir JPEG üretir (düz renk değil — fayda kapısı
	düz renkte türevi kaynaktan büyük bulup passthrough'a düşebilir)."""
	from PIL import Image

	im = Image.new("RGB", (kenar, kenar))
	pikseller = im.load()
	for y in range(kenar):
		for x in range(0, kenar, 4):
			renk = ((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256)
			for dx in range(4):
				if x + dx < kenar:
					pikseller[x + dx, y] = renk
	buf = io.BytesIO()
	im.save(buf, "JPEG", quality=95)
	return buf.getvalue()


def _animasyon_baytlari() -> bytes:
	from PIL import Image

	ilk = Image.new("RGB", (32, 32), (255, 0, 0))
	ikinci = Image.new("RGB", (32, 32), (0, 0, 255))
	buf = io.BytesIO()
	ilk.save(buf, "GIF", save_all=True, append_images=[ikinci], duration=40, loop=0)
	return buf.getvalue()


def _sil(doctype: str, name: str) -> None:
	"""Kaydı varsa siler ve KALICI yapar.

	`commit` şart: `_run_rendition_job` worker davranışını taklit ederek kendi
	içinde commit atıyor; o commit'ten sonra testin kendi rollback'i artık
	kaydı geri almaz — temizlik de aynı kalıcılıkta olmalı, yoksa her koşu
	gerçek site veritabanında artık bırakır.
	"""
	if frappe.db.exists(doctype, name):
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
		frappe.db.commit()


def _asset_temizle(asset_name: str) -> None:
	"""Test üretim ağacını FK sırasıyla ve yalnız kendi asset kökünden sil."""
	if not frappe.db.exists("Media Asset", asset_name):
		return
	frappe.db.set_value("Media Asset", asset_name, "active_version", None, update_modified=False)
	if frappe.db.exists("Media Crop Intent", asset_name):
		frappe.delete_doc("Media Crop Intent", asset_name, ignore_permissions=True, force=True)
	if frappe.db.table_exists("Media Quality Report"):
		frappe.db.delete("Media Quality Report", {"asset": asset_name})
	frappe.db.delete("Media Rendition", {"asset": asset_name})
	frappe.db.delete("Media Processing Job", {"asset": asset_name})
	frappe.db.delete("Media Version", {"asset": asset_name})
	frappe.delete_doc("Media Asset", asset_name, ignore_permissions=True, force=True)
	frappe.db.commit()
	kok = frappe.get_site_path("public", "files", "media", asset_name)
	if os.path.isdir(kok):
		shutil.rmtree(kok)


def _dosya_ekle(test, file_name: str, icerik: bytes, **alanlar: object):
	"""Bayraklar KAPALIYKEN dosya ekler (kanca no-op olsun) ve temizliğe yazar."""
	doc = frappe.get_doc({"doctype": "File", "file_name": file_name, "is_private": 0, "content": icerik})
	doc.insert(ignore_permissions=True)
	test.addCleanup(lambda: _sil("File", doc.name))
	if alanlar:
		frappe.db.set_value("File", doc.name, alanlar)
		doc.reload()
	return doc


class _BayrakliTest(FrappeTestCase):
	"""Ayar singleton'ını yazan testler için ortak kurulum/temizlik."""

	def setUp(self) -> None:
		self._orijinal = {a: frappe.db.get_single_value(DOCTYPE_AYAR, a) for a in KORUNAN_ALANLAR}
		self._ayarla(media_pipeline_enabled=0, rendition_on_upload=0)

	def tearDown(self) -> None:
		for alan, deger in self._orijinal.items():
			frappe.db.set_single_value(DOCTYPE_AYAR, alan, deger)
		# Worker'ın commit'i test ortasında bayrakları kalıcı hâle getiriyor;
		# geri yükleme de commit'lenmezse site AÇIK bayrakla kalır.
		frappe.db.commit()
		pipeline_flags.clear_cache()

	def _ayarla(self, **degerler: object) -> None:
		for alan, deger in degerler.items():
			frappe.db.set_single_value(DOCTYPE_AYAR, alan, deger)
		pipeline_flags.clear_cache()

	def _hatti_ac(self) -> None:
		self._ayarla(
			media_pipeline_enabled=1,
			rendition_on_upload=1,
			active_slots=SLOT,
			rollout_percent=100,
			rollout_stores="",
		)


class TestBayrakKapisi(_BayrakliTest):
	def setUp(self) -> None:
		super().setUp()
		self.doc = _dosya_ekle(
			self,
			"kopru-urun-gorseli.jpg",
			_gorsel_baytlari(64),
			attached_to_doctype="Listing",
			attached_to_field="primary_image",
		)

	def test_bayrak_kapaliyken_enqueue_cagrilmaz(self):
		"""EN KRİTİK TEST — varsayılan (kapalı) hâlde sistem bugünkü gibi davranır."""
		with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
			pipeline_bridge.maybe_generate_renditions(self.doc)

		m.assert_not_called()

	def test_ana_salter_acik_alt_bayrak_kapaliyken_enqueue_cagrilmaz(self):
		self._ayarla(media_pipeline_enabled=1, rendition_on_upload=0, active_slots=SLOT)

		with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
			pipeline_bridge.maybe_generate_renditions(self.doc)

		m.assert_not_called()

	def test_slot_etkin_degilse_enqueue_cagrilmaz(self):
		"""`active_slots` boşken hiçbir slot açık değildir (fail-safe)."""
		self._ayarla(media_pipeline_enabled=1, rendition_on_upload=1, active_slots="")

		with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
			pipeline_bridge.maybe_generate_renditions(self.doc)

		m.assert_not_called()

	def test_bayrak_acikken_canli_gorsel_kuyruguna_atilir(self):
		self._hatti_ac()

		with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
			pipeline_bridge.maybe_generate_renditions(self.doc)

		m.assert_called_once()
		args, kwargs = m.call_args
		self.assertEqual(args[0], "tradehub_core.media.pipeline_bridge._run_rendition_job")
		self.assertEqual(kwargs.get("queue"), "media-image-live")
		self.assertEqual(kwargs.get("timeout"), 60)
		self.assertTrue(kwargs.get("enqueue_after_commit"))
		self.assertEqual(kwargs.get("file_url"), self.doc.file_url)

	def test_rollout_sifirda_disaridaki_magaza_kuyruga_girmez_canary_girer(self):
		self._ayarla(
			media_pipeline_enabled=1,
			rendition_on_upload=1,
			active_slots=SLOT,
			rollout_percent=0,
			rollout_stores="SELLER-CANARY",
		)
		with (
			mock.patch.object(pipeline_bridge.ownership, "store_of", return_value="SELLER-OUT"),
			mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as enqueue,
		):
			pipeline_bridge.maybe_generate_renditions(self.doc)
		enqueue.assert_not_called()

		with (
			mock.patch.object(pipeline_bridge.ownership, "store_of", return_value="SELLER-CANARY"),
			mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as enqueue,
		):
			pipeline_bridge.maybe_generate_renditions(self.doc)
		enqueue.assert_called_once()


class TestKapsam(_BayrakliTest):
	"""Kapsam daraltması — `transcode.maybe_transcode_on_insert` ile aynı omurga."""

	def setUp(self) -> None:
		super().setUp()
		self._hatti_ac()

	def _enqueue_cagrildi_mi(self, doc) -> bool:
		with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
			pipeline_bridge.maybe_generate_renditions(doc)
		return m.called

	def test_private_dosya_muaf(self):
		doc = _dosya_ekle(
			self,
			"kopru-private.jpg",
			_gorsel_baytlari(64),
			is_private=1,
			attached_to_doctype="Listing",
			attached_to_field="primary_image",
		)

		self.assertFalse(self._enqueue_cagrildi_mi(doc))

	def test_kyb_belgesi_muaf(self):
		"""KVKK kapsam dışı doctype: private işaretlenmemiş olsa bile işlenmez."""
		doc = _dosya_ekle(
			self,
			"kopru-kyb.jpg",
			_gorsel_baytlari(64),
			attached_to_doctype="KYB Verification",
			attached_to_field="identity_document",
		)

		self.assertFalse(self._enqueue_cagrildi_mi(doc))

	def test_gorsel_olmayan_dosya_muaf(self):
		doc = _dosya_ekle(
			self,
			"kopru-video.mp4",
			b"sahte video icerigi",
			attached_to_doctype="Listing",
			attached_to_field="primary_image",
		)

		self.assertFalse(self._enqueue_cagrildi_mi(doc))

	def test_bagsiz_dosya_muaf(self):
		"""Slot çözülemiyorsa (hiçbir yere eklenmemiş dosya) kapsam dışı."""
		doc = _dosya_ekle(self, "kopru-bagsiz.jpg", _gorsel_baytlari(64))

		self.assertFalse(self._enqueue_cagrildi_mi(doc))

	def test_geri_yukleme_bayragi_muaf(self):
		doc = _dosya_ekle(
			self,
			"kopru-restore.jpg",
			_gorsel_baytlari(64),
			attached_to_doctype="Listing",
			attached_to_field="primary_image",
		)
		doc.flags.th_skip_transcode = True

		self.assertFalse(self._enqueue_cagrildi_mi(doc))


class TestSlotCozumu(FrappeTestCase):
	"""Harita politikanın `bound_to` bloklarından okunur — kodda sabit liste yok."""

	def test_listing_primary_image_urun_gorseli(self):
		self.assertEqual(pipeline_bridge.resolve_slot_key("Listing", "primary_image"), SLOT)

	def test_listing_image_alt_tablosu(self):
		self.assertEqual(pipeline_bridge.resolve_slot_key("Listing Image", "image"), SLOT)

	def test_satici_logosu(self):
		self.assertEqual(pipeline_bridge.resolve_slot_key("Admin Seller Profile", "logo"), "seller.logo")

	def test_alan_bossa_tek_slotlu_doctype_cozulur(self):
		self.assertEqual(pipeline_bridge.resolve_slot_key("Listing Image", ""), SLOT)

	def test_alan_bossa_iki_slotlu_doctype_cozulmez(self):
		"""`Admin Seller Profile` hem seller.logo hem company.cover_image'e bağlı —
		tahmin yapmak yanlış oran ve yanlış kırpma demektir."""
		self.assertIsNone(pipeline_bridge.resolve_slot_key("Admin Seller Profile", ""))

	def test_kyb_slotu_disarida(self):
		"""`document.attachment` slotu yükleme kancasından ASLA çözülmez."""
		self.assertIsNone(pipeline_bridge.resolve_slot_key("KYB Verification", "identity_document"))

	def test_bilinmeyen_doctype(self):
		self.assertIsNone(pipeline_bridge.resolve_slot_key("Sales Order", "image"))


def _profil_olustur(
	test,
	profile_key: str,
	widths: str,
	formats: str = '["webp"]',
	*,
	generation: str = "eager",
	fit: str = "pad",
	aspect_ratio: str = "1:1",
):
	if frappe.db.exists("Media Profile", profile_key):
		frappe.delete_doc("Media Profile", profile_key, ignore_permissions=True, force=True)
	doc = frappe.get_doc(
		{
			"doctype": "Media Profile",
			"profile_key": profile_key,
			# K-2: `profile_key` docname'dir ve `{slot_key}:{policy_profile}`
			# biçimindedir; kütüphanenin beklediği HAM profil adı ayrı kolonda
			# durur ve `Media Rendition.profile` kolonuna o yazılır.
			"policy_profile": profile_key.rsplit(":", 1)[-1],
			"label": "Test profili",
			"slot_key": SLOT,
			"enabled": 1,
			"aspect_ratio": aspect_ratio,
			"fit": fit,
			"widths": widths,
			"formats": formats,
			"quality_target": 80,
			"generation": generation,
		}
	)
	doc.insert(ignore_permissions=True)
	test.addCleanup(lambda: _sil("Media Profile", doc.name))
	return doc


class TestIdempotency(_BayrakliTest):
	def setUp(self) -> None:
		super().setUp()
		self.doc = _dosya_ekle(
			self,
			"kopru-idempotent.jpg",
			_gorsel_baytlari(320),
			attached_to_doctype="Listing",
			attached_to_field="primary_image",
		)
		self._hatti_ac()

	def test_ayni_dosya_ikinci_kez_no_op(self):
		"""İlk çağrı kuyruğa atar; türev üretildikten sonra ikinci çağrı sessizdir."""
		with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
			pipeline_bridge.maybe_generate_renditions(self.doc)
		self.assertEqual(m.call_count, 1)

		# İşin çıktısını taklit et: Asset + Rendition kayıtları.
		profil = _profil_olustur(self, "test-idempotent-w96", "[96]")
		surum = pipeline_bridge.version_hash(self.doc)
		asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": SLOT,
				"media_type": "image",
				"state": "ready",
				"content_sha256": surum,
				"source_file": self.doc.name,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: _sil("Media Asset", asset.name))
		rend = frappe.get_doc(
			{
				"doctype": "Media Rendition",
				"asset": asset.name,
				"profile": profil.name,
				"width": 96,
				"height": 96,
				"format": "webp",
				"file_url": "/files/00/deneme.webp",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: _sil("Media Rendition", rend.name))

		with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
			pipeline_bridge.maybe_generate_renditions(self.doc)

		m.assert_not_called()


class TestHassasIkiz(_BayrakliTest):
	"""Rapor 69 §7.2 — hassas-ikiz içerik türev ÜRETMEZ (optimize akışıyla tutarlı).

	W3-B'nin gerçek veriyle ölçtüğü sapma: optimize akışı `sensitive_content_twin`
	gerekçesiyle reddettiği içeriği türev hattı işliyor, herkese açık türev
	üretiyordu. Buradaki üç test o deliği ve KANITININ boş doğru olmadığını ölçer:
	ikizli içerik ne kancadan ne worker'dan geçer; ikiz kontrolü KALDIRILINCA
	aynı dosya üretime girer (yani engeli koyan tek şey o kontrol).
	"""

	def setUp(self) -> None:
		super().setUp()
		# Koşu başına benzersiz içerik: JPEG sonuna eklenen kuyruk görüntüyü
		# bozmaz, content_hash'i benzersizleştirir (önceki koşu artığı karışmaz).
		self.icerik = _gorsel_baytlari(64) + frappe.generate_hash(length=12).encode()
		self.doc = _dosya_ekle(
			self,
			"kopru-ikiz.jpg",
			self.icerik,
			attached_to_doctype="Listing",
			attached_to_field="primary_image",
		)
		# Hassas ikiz: AYNI içerik private bir File kaydında da duruyor —
		# `runner._has_sensitive_twin`in yakaladığı durumun birebir kendisi.
		ikiz = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "kopru-ikiz-private.jpg",
				"is_private": 1,
				"content": self.icerik,
			}
		)
		ikiz.insert(ignore_permissions=True)
		self.addCleanup(lambda: _sil("File", ikiz.name))
		# Ön koşul: iki kayıt gerçekten aynı content_hash'i taşıyor — taşımıyorsa
		# aşağıdaki "üretmez" iddiaları hiçbir şey ölçmez, burada patla.
		self.assertTrue(self.doc.content_hash)
		self.assertEqual(frappe.db.get_value("File", ikiz.name, "content_hash"), self.doc.content_hash)
		self._hatti_ac()

	def test_hassas_ikizli_icerik_kuyruga_girmez(self):
		with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
			pipeline_bridge.maybe_generate_renditions(self.doc)
		m.assert_not_called()

	def test_worker_da_uretmez(self):
		"""Kuyruğa iş bayrak açıkken girmiş olabilir — worker da aynı kapıyı sorar."""
		pipeline_bridge._run_rendition_job(self.doc.file_url)
		parmak_izi = pipeline_bridge.content_fingerprint(self.doc)
		self.assertFalse(
			frappe.db.exists("Media Asset", {"content_sha256": parmak_izi, "slot_key": SLOT}),
			"hassas ikizli içerik için Media Asset açılmamalı",
		)

	def test_kirmizi_kanit_kontrol_kaldirilinca_uretir(self):
		"""Vacuity kanıtı: dosya bunun DIŞINDA tamamen kapsam içinde.

		İkiz kontrolü kaldırılınca aynı dosya kuyruğa GİRER — yani yukarıdaki
		"üretmez" testleri, dosyanın zaten kapsam dışı olmasından değil, tam
		olarak bu kontrolden geçiyor. Kontrol bir gün sessizce gevşetilirse
		önce bu üçlü kırmızıya döner.
		"""
		with (
			mock.patch("tradehub_core.media.runner._has_sensitive_twin", return_value=False),
			mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m,
		):
			pipeline_bridge.maybe_generate_renditions(self.doc)
		self.assertEqual(m.call_count, 1, "kontrol kalkınca üretim başlamalıydı — test boş doğru")


class TestUctanUcaUretim(_BayrakliTest):
	"""`_run_rendition_job` — worker tarafı gerçekten türev üretiyor mu?"""

	def setUp(self) -> None:
		super().setUp()
		self.doc = _dosya_ekle(
			self,
			"kopru-uctan-uca.jpg",
			_gorsel_baytlari(1200),
			attached_to_doctype="Listing",
			attached_to_field="primary_image",
		)
		self._tohumlanmis_profilleri_kapat()
		self.profil = _profil_olustur(self, "test-uctan-uca", "[96, 384]")
		self._hatti_ac()

	def _tohumlanmis_profilleri_kapat(self) -> None:
		"""Slotun TOHUMLANMIŞ profillerini test süresince kapatır (sonra geri açar).

		`patches/v15_9_23_media_profile_seed.py` `product.image` için politikadaki
		7 gerçek profili açıyor. Bu test TEK profilin merdivenini ölçüyor; gerçek
		profiller açıkken beklenen basamak listesi kuruluma bağlı olurdu.
		"""
		for ad in frappe.get_all("Media Profile", filters={"slot_key": SLOT, "enabled": 1}, pluck="name"):
			frappe.db.set_value("Media Profile", ad, "enabled", 0)
			self.addCleanup(frappe.db.set_value, "Media Profile", ad, "enabled", 1)

	def _temizle(self, asset_name: str) -> None:
		"""Üretilen kayıtları VE diske yazılan türev dosyalarını kaldırır."""
		for rend in frappe.get_all(
			"Media Rendition", filters={"asset": asset_name}, fields=["name", "file_url"]
		):
			yol = frappe.get_site_path("public", (rend.file_url or "").lstrip("/"))
			if rend.file_url and os.path.exists(yol):
				os.remove(yol)
			_sil("Media Rendition", rend.name)
		for job in frappe.get_all("Media Processing Job", filters={"asset": asset_name}, pluck="name"):
			_sil("Media Processing Job", job)
		# Sürüm kayıtları Asset'e Link verir — Asset'ten ÖNCE silinmeli.
		for surum in frappe.get_all("Media Version", filters={"asset": asset_name}, pluck="name"):
			_sil("Media Version", surum)
		_sil("Media Asset", asset_name)

	def test_turevler_uretilir_diske_yazilir_ve_kayitlanir(self):
		pipeline_bridge._run_rendition_job(self.doc.file_url)

		# Eski adla çağrı BİLEREK korunuyor: `version_hash` artık
		# `content_fingerprint`in takma adı; bu satır uyumluluğun kanıtı.
		surum = pipeline_bridge.version_hash(self.doc)
		asset_name = frappe.db.get_value("Media Asset", {"content_sha256": surum, "slot_key": SLOT}, "name")
		self.assertTrue(asset_name, "Media Asset açılmadı")
		self.addCleanup(lambda: self._temizle(asset_name))

		self.assertEqual(frappe.db.get_value("Media Asset", asset_name, "state"), "ready")

		# T-042: sürüm kaydı açılmış ve hash KÜTÜPHANEDEN yeniden hesaplanabilir
		# olmalı — köprünün kendi hash'i değil, dedup.version_hash'in 4 girdisi.
		from tradehub_core.media.pipeline.core import dedup
		from tradehub_core.media.pipeline.image import render as _render

		surumler = frappe.get_all(
			"Media Version",
			filters={"asset": asset_name},
			fields=["name", "version_hash", "source_hash", "engine_version"],
		)
		self.assertEqual(len(surumler), 1, "tek üretim tek Media Version açmalı")
		kayit = surumler[0]
		icerik = self.doc.get_content()
		if isinstance(icerik, str):
			icerik = icerik.encode()
		beklenen_kaynak = dedup.stream_sha256(icerik).sha256
		self.assertEqual(kayit.source_hash, beklenen_kaynak, "source_hash TAM 64 hane olmalı")
		beklenen_hash = dedup.version_hash(
			beklenen_kaynak,
			_render.load_slot_policy(SLOT),
			None,
			kayit.engine_version,
		)
		self.assertEqual(kayit.version_hash, beklenen_hash)
		self.assertEqual(kayit.name, beklenen_hash, "autoname=field:version_hash")

		turevler = frappe.get_all(
			"Media Rendition",
			filters={"asset": asset_name},
			fields=["width", "format", "file_url", "bytes", "benefit_gate_passed", "profile"],
			order_by="width asc",
		)
		self.assertEqual([t.width for t in turevler], [96, 384])
		for t in turevler:
			# K-2: kolon POLİTİKA profil adını taşır, `Media Profile` docname'ini
			# değil. Manifest kütüphanesi bu değeri politika adıyla karşılaştırıyor;
			# docname yazılırsa manifest sessizce boş döner.
			self.assertEqual(t.profile, self.profil.policy_profile)
			self.assertEqual(t.format, "webp")
			self.assertTrue(t.benefit_gate_passed)
			self.assertGreater(t.bytes, 0)
			yol = frappe.get_site_path("public", t.file_url.lstrip("/"))
			self.assertTrue(os.path.exists(yol), f"türev diske yazılmadı: {t.file_url}")
			# T-042 / INV-09: adres version_hash TAŞIMALI —
			# /files/media/{asset}/{version_hash}/{profil}-{genişlik}.{uzantı}
			cozulen = dedup.parse_rendition_path(t.file_url)
			self.assertIsNotNone(cozulen, f"türev adresi T-042 düzeninde değil: {t.file_url}")
			self.assertEqual(cozulen["asset"], asset_name)
			self.assertEqual(cozulen["version_hash"], beklenen_hash)
			self.assertEqual(cozulen["width"], t.width)

		job = frappe.get_all(
			"Media Processing Job",
			filters={"asset": asset_name},
			fields=["status", "job_type", "queue", "idempotency_key"],
		)
		self.assertEqual(len(job), 1)
		self.assertEqual(job[0].status, "success")
		self.assertEqual(job[0].job_type, "rendition")
		self.assertEqual(job[0].idempotency_key, f"rendition:{surum}:{SLOT}")

	def test_bayrak_kapaliyken_worker_da_hicbir_sey_yazmaz(self):
		"""Bayrak iş kuyrukta beklerken kapatılmış olabilir — worker da sorar."""
		self._ayarla(media_pipeline_enabled=0)

		pipeline_bridge._run_rendition_job(self.doc.file_url)

		surum = pipeline_bridge.version_hash(self.doc)
		self.assertFalse(
			frappe.db.exists("Media Asset", {"content_sha256": surum, "slot_key": SLOT}),
			"bayrak kapalıyken Media Asset açılmamalı",
		)


class TestMevcutTurevAtlama(_BayrakliTest):
	"""T-064/W8 — mevcut-türev atlama: version_hash aynı + dosya diskte → encode YOK.

	Ölçülen açık (2026-08-20): DB satırları silinip disk dosyaları dururken
	(yetim disk / DB geri yüklemesi) `_run_rendition_job` 48 encode'un 48'ini
	yeniden yapıyordu — W6-B'nin videoda bulduğu "yol-determinizmi var ama her
	koşum yeniden kodluyor" deseninin görüntü karşılığı. Atlama sonrası aynı
	senaryo 0 encode.
	"""

	def setUp(self) -> None:
		super().setUp()
		self.doc = _dosya_ekle(
			self,
			"kopru-atlama.jpg",
			_gorsel_baytlari(640),
			attached_to_doctype="Listing",
			attached_to_field="primary_image",
		)
		for ad in frappe.get_all("Media Profile", filters={"slot_key": SLOT, "enabled": 1}, pluck="name"):
			frappe.db.set_value("Media Profile", ad, "enabled", 0)
			self.addCleanup(frappe.db.set_value, "Media Profile", ad, "enabled", 1)
		self.profil = _profil_olustur(self, "test-atlama", "[96, 384]")
		self._hatti_ac()

	def _temizle(self, asset_name: str) -> None:
		for rend in frappe.get_all(
			"Media Rendition", filters={"asset": asset_name}, fields=["name", "file_url"]
		):
			yol = frappe.get_site_path("public", (rend.file_url or "").lstrip("/"))
			if rend.file_url and os.path.exists(yol):
				os.remove(yol)
			_sil("Media Rendition", rend.name)
		for job in frappe.get_all("Media Processing Job", filters={"asset": asset_name}, pluck="name"):
			_sil("Media Processing Job", job)
		for surum in frappe.get_all("Media Version", filters={"asset": asset_name}, pluck="name"):
			_sil("Media Version", surum)
		_sil("Media Asset", asset_name)

	def _uret_ve_asset_al(self) -> str:
		pipeline_bridge._run_rendition_job(self.doc.file_url)
		surum = pipeline_bridge.content_fingerprint(self.doc)
		asset_name = frappe.db.get_value("Media Asset", {"content_sha256": surum, "slot_key": SLOT}, "name")
		self.assertTrue(asset_name, "Media Asset açılmadı")
		self.addCleanup(lambda: self._temizle(asset_name))
		return asset_name

	def _encode_sayarak(self, fn):
		"""`render.encode` çağrılarını sayarak `fn`'i koşar; sayıyı döner."""
		from tradehub_core.media.pipeline.image import render as render_mod

		sayac = {"n": 0}
		orijinal = render_mod.encode

		def sayan(*a, **kw):
			sayac["n"] += 1
			return orijinal(*a, **kw)

		with mock.patch.object(render_mod, "encode", sayan):
			fn()
		return sayac["n"]

	def test_ikinci_kosum_hic_encode_yapmaz(self):
		"""Normal yol: kayıtlar dururken ikinci koşum DB kapısından döner — 0 encode."""
		asset_name = self._uret_ve_asset_al()
		onceki = frappe.db.count("Media Rendition", {"asset": asset_name})
		self.assertGreater(onceki, 0)

		encode_sayisi = self._encode_sayarak(lambda: pipeline_bridge._run_rendition_job(self.doc.file_url))

		self.assertEqual(encode_sayisi, 0, "ikinci koşum yeniden kodlamamalı")
		self.assertEqual(frappe.db.count("Media Rendition", {"asset": asset_name}), onceki)

	def test_yetim_disk_dosyalari_encodesuz_kayda_baglanir(self):
		"""Satırlar silinir, dosyalar diskte kalır → yeniden koşum 0 encode + kayıtlar geri."""
		asset_name = self._uret_ve_asset_al()
		turevler = frappe.get_all(
			"Media Rendition",
			filters={"asset": asset_name},
			fields=["name", "file_url", "bytes", "width", "height", "format"],
		)
		self.assertGreater(len(turevler), 0)
		for t in turevler:
			_sil("Media Rendition", t.name)
			yol = frappe.get_site_path("public", t.file_url.lstrip("/"))
			self.assertTrue(os.path.exists(yol), "önkoşul: türev dosyası diskte durmalı")

		encode_sayisi = self._encode_sayarak(lambda: pipeline_bridge._run_rendition_job(self.doc.file_url))

		self.assertEqual(encode_sayisi, 0, "diskte duran türev yeniden kodlanmamalı")
		yeni = {
			t.file_url: t
			for t in frappe.get_all(
				"Media Rendition",
				filters={"asset": asset_name},
				fields=["file_url", "bytes", "width", "height", "format"],
			)
		}
		self.assertEqual(len(yeni), len(turevler), "her disk dosyası için kayıt geri açılmalı")
		for t in turevler:
			geri = yeni.get(t.file_url)
			self.assertIsNotNone(geri, f"kayıt geri açılmadı: {t.file_url}")
			# Künye disk gerçeklerinden gelir — adres deterministik olduğu için
			# bayt/ölçü ilk üretimle birebir aynı olmalı.
			self.assertEqual(geri.bytes, t.bytes)
			self.assertEqual(geri.width, t.width)
			self.assertEqual(geri.height, t.height)
			self.assertEqual(geri.format, t.format)

	def test_bozuk_disk_dosyasi_atlanmaz_yeniden_uretilir(self):
		"""Diskteki dosya açılmıyorsa atlama uygulanmaz — türev yeniden üretilir."""
		asset_name = self._uret_ve_asset_al()
		turevler = frappe.get_all(
			"Media Rendition", filters={"asset": asset_name}, fields=["name", "file_url", "bytes"]
		)
		hedef = turevler[0]
		yol = frappe.get_site_path("public", hedef.file_url.lstrip("/"))
		with open(yol, "wb") as f:
			f.write(b"bozuk")  # açılamayan içerik
		for t in turevler:
			_sil("Media Rendition", t.name)

		encode_sayisi = self._encode_sayarak(lambda: pipeline_bridge._run_rendition_job(self.doc.file_url))

		self.assertGreater(encode_sayisi, 0, "bozuk dosya körlemesine atlanmamalı")
		geri = frappe.get_all(
			"Media Rendition",
			filters={"asset": asset_name, "file_url": hedef.file_url},
			fields=["bytes"],
		)
		self.assertEqual(len(geri), 1)
		self.assertEqual(geri[0].bytes, hedef.bytes, "yeniden üretim deterministik baytı geri yazmalı")
		self.assertEqual(os.path.getsize(yol), hedef.bytes, "diskteki bozuk dosya onarılmalı")


class TestFaz6UretimAkislari(_BayrakliTest):
	"""T-062/063/064 üretim boşlukları — AAA ve yarış kapıları."""

	def setUp(self) -> None:
		super().setUp()
		for ad in frappe.get_all("Media Profile", filters={"slot_key": SLOT, "enabled": 1}, pluck="name"):
			frappe.db.set_value("Media Profile", ad, "enabled", 0)
			self.addCleanup(frappe.db.set_value, "Media Profile", ad, "enabled", 1)
		self._hatti_ac()

	def _doc(self, name: str, content: bytes):
		return _dosya_ekle(
			self,
			name,
			content,
			attached_to_doctype="Listing",
			attached_to_field="primary_image",
		)

	def _asset(self, doc) -> str:
		asset = frappe.db.get_value(
			"Media Asset",
			{"content_sha256": pipeline_bridge.content_fingerprint(doc), "slot_key": SLOT},
			"name",
		)
		self.assertTrue(asset)
		self.addCleanup(_asset_temizle, asset)
		return asset

	@staticmethod
	def _encode_sayarak(fn) -> int:
		from tradehub_core.media.pipeline.image import render as render_mod

		sayac = {"n": 0}
		orijinal = render_mod.encode

		def sayan(*args, **kwargs):
			sayac["n"] += 1
			return orijinal(*args, **kwargs)

		with mock.patch.object(render_mod, "encode", sayan):
			fn()
		return sayac["n"]

	def test_animated_gif_classifier_contract_video_hattina_gider(self):
		# Arrange
		doc = self._doc("faz6-animation.gif", _animasyon_baytlari())

		# Act
		with mock.patch.object(pipeline_bridge.frappe, "enqueue") as enqueue:
			pipeline_bridge._run_rendition_job(doc.file_url)

		# Assert
		enqueue.assert_called_once()
		args, kwargs = enqueue.call_args
		self.assertEqual(args[0], "tradehub_core.media.pipeline_bridge._run_animation_job")
		self.assertEqual(kwargs["queue"], "media-video")
		self.assertEqual(kwargs["file_url"], doc.file_url)
		self.assertEqual(kwargs["slot_override"], "product.video")

	def test_animated_gif_gercek_mp4_webm_poster_ve_job_uretir(self):
		# Arrange
		if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
			self.skipTest("ffmpeg/ffprobe production image testinde mevcut")
		doc = self._doc("faz6-animation-real.gif", _animasyon_baytlari())

		# Act
		with mock.patch.object(pipeline_bridge.frappe, "enqueue"):
			pipeline_bridge._run_rendition_job(doc.file_url)
		pipeline_bridge._run_animation_job(doc.file_url, slot_override="product.video")
		asset = frappe.db.get_value(
			"Media Asset",
			{
				"content_sha256": pipeline_bridge.content_fingerprint(doc),
				"slot_key": "product.video",
			},
			"name",
		)

		# Assert
		self.assertTrue(asset)
		self.addCleanup(_asset_temizle, asset)
		self.assertEqual(frappe.db.get_value("Media Asset", asset, "media_type"), "video")
		self.assertEqual(frappe.db.get_value("Media Asset", asset, "state"), "ready")
		version = frappe.db.get_value("Media Asset", asset, "active_version")
		self.assertTrue(version)
		self.assertEqual(frappe.db.get_value("Media Version", version, "classification"), "animation")
		rows = frappe.get_all(
			"Media Rendition",
			filters={"asset": asset, "version_hash": version},
			fields=["profile", "format", "file_url", "bytes", "benefit_gate_passed"],
			order_by="profile asc",
		)
		self.assertEqual(
			{(row.profile, row.format) for row in rows},
			{("h264", "mp4"), ("vp9", "webm"), ("poster", "png")},
		)
		self.assertTrue(all(int(row.bytes or 0) > 0 for row in rows))
		self.assertTrue(all(int(row.benefit_gate_passed or 0) == 1 for row in rows))
		self.assertTrue(all(os.path.isfile(frappe.get_site_path("public", row.file_url.lstrip("/"))) for row in rows))
		job = frappe.get_all(
			"Media Processing Job",
			filters={"asset": asset},
			fields=["job_type", "status"],
			limit=1,
		)[0]
		self.assertEqual((job.job_type, job.status), ("video_from_animation", "success"))

	def test_normalize_master_version_rendition_ve_raporun_ortak_girdisidir(self):
		# Arrange
		_profil_olustur(self, "faz6-master-bridge", "[96]", fit="contain", aspect_ratio="")
		kaynak = _gorsel_baytlari(320)
		doc = self._doc("faz6-master-bridge.jpg", kaynak)

		# Act
		with mock.patch.object(
			pipeline_bridge,
			"_generate",
			wraps=pipeline_bridge._generate,
		) as generate:
			pipeline_bridge._run_rendition_job(doc.file_url)
		asset = self._asset(doc)
		version_name = frappe.db.get_value("Media Asset", asset, "active_version")
		version = frappe.get_doc("Media Version", version_name)
		master_bytes = generate.call_args.args[0]

		# Assert — normalize edilen bayt hem encode girdisi hem Version künyesidir.
		self.assertNotEqual(master_bytes, kaynak)
		self.assertEqual(generate.call_args.kwargs["classification"].klass, version.classification)
		self.assertIn("+master-", version.engine_version)
		self.assertEqual((version.width, version.height, version.dpi), (320, 320, 72))
		self.assertTrue(version.lqip)
		self.assertTrue(version.dominant_color)
		self.assertTrue(frappe.parse_json(version.format_chain))
		from PIL import Image

		with Image.open(io.BytesIO(master_bytes)) as master_image:
			self.assertEqual(master_image.size, (version.width, version.height))
			self.assertAlmostEqual(master_image.info["dpi"][0], 72, delta=0.1)
		if frappe.db.table_exists("Media Quality Report"):
			report_json = frappe.db.get_value(
				"Media Quality Report",
				{"asset": asset, "version": version_name, "report_type": "asset"},
				"report_json",
			)
			self.assertTrue(report_json)
			report = frappe.parse_json(report_json)
			self.assertEqual(report["processing"]["normalized"]["width"], version.width)
			self.assertEqual(report["processing"]["normalized"]["dpi"], [72.0, 72.0])

	def test_upscale_basamaklari_kayit_ve_manifest_adayindan_duser(self):
		# Arrange
		_profil_olustur(self, "faz6-upscale", "[96, 384]")
		doc = self._doc("faz6-upscale.jpg", _gorsel_baytlari(64))

		# Act
		encode = self._encode_sayarak(lambda: pipeline_bridge._run_rendition_job(doc.file_url))
		asset = self._asset(doc)

		# Assert
		self.assertEqual(encode, 0, "uygunsuz basamak encode'a hiç girmemeli")
		self.assertEqual(frappe.db.count("Media Rendition", {"asset": asset}), 0)
		self.assertEqual(frappe.db.get_value("Media Asset", asset, "state"), "ready")
		self.assertTrue(frappe.db.get_value("Media Asset", asset, "active_version"))

	def test_lazy_ilk_istekte_uretilir_ve_ikinci_istek_cache_hit(self):
		# Arrange
		_profil_olustur(self, "faz6-lazy", "[96]", generation="lazy")
		doc = self._doc("faz6-lazy.jpg", _gorsel_baytlari(320))
		pipeline_bridge._run_rendition_job(doc.file_url)
		asset = self._asset(doc)
		self.assertEqual(frappe.db.count("Media Rendition", {"asset": asset}), 0)
		sonuclar: list[dict] = []

		# Act
		ilk_encode = self._encode_sayarak(
			lambda: sonuclar.append(pipeline_bridge.ensure_lazy_renditions(asset))
		)
		ikinci_encode = self._encode_sayarak(
			lambda: sonuclar.append(pipeline_bridge.ensure_lazy_renditions(asset))
		)

		# Assert
		self.assertGreater(ilk_encode, 0)
		self.assertEqual(ikinci_encode, 0)
		self.assertEqual([s["status"] for s in sonuclar], ["generated", "cached"])
		self.assertEqual(
			frappe.db.count("Media Rendition", {"asset": asset, "generation": "lazy"}),
			1,
		)

	def test_manifest_ilk_okuma_lazy_uretir_ikinci_okuma_persistent_cache_hit(self):
		# Arrange
		_profil_olustur(self, "faz6-lazy-manifest", "[96]", generation="lazy")
		doc = self._doc("faz6-lazy-manifest.jpg", _gorsel_baytlari(320))
		pipeline_bridge._run_rendition_job(doc.file_url)
		asset = self._asset(doc)
		self.assertEqual(frappe.db.count("Media Rendition", {"asset": asset}), 0)

		# Act
		ilk: list[dict] = []
		ikinci: list[dict] = []
		ilk_encode = self._encode_sayarak(lambda: ilk.append(media_manifest.manifest_batch([doc.name])))
		ikinci_encode = self._encode_sayarak(lambda: ikinci.append(media_manifest.manifest_batch([doc.name])))

		# Assert
		self.assertGreater(ilk_encode, 0, "ilk gerçek manifest okuması lazy encode etmeliydi")
		self.assertEqual(ikinci_encode, 0, "ikinci istek DB/disk cache'inden gelmeli")
		ilk_turev = ilk[0]["manifests"][doc.name]["renditions"]
		ikinci_turev = ikinci[0]["manifests"][doc.name]["renditions"]
		self.assertEqual(len(ilk_turev), 1)
		self.assertEqual(ikinci_turev, ilk_turev)
		self.assertTrue(os.path.isfile(frappe.get_site_path("public", ilk_turev[0]["file_url"].lstrip("/"))))

	def test_basarili_worker_kalite_raporu_ve_metrik_uretimine_baglidir(self):
		# Arrange
		from tradehub_core.media.pipeline.image import report as report_mod

		_profil_olustur(self, "faz6-quality-report", "[96]")
		doc = self._doc("faz6-quality-report.jpg", _gorsel_baytlari(320))

		# Act
		with (
			mock.patch.object(pipeline_bridge, "_quality_report_table_ready", return_value=True),
			mock.patch.object(report_mod, "persist_report") as persist,
			mock.patch.object(report_mod, "record_report_metrics") as metrics,
		):
			pipeline_bridge._run_rendition_job(doc.file_url)
		asset = self._asset(doc)

		# Assert
		persist.assert_called_once()
		rapor = persist.call_args.args[0]
		metrics.assert_called_once_with(rapor)
		toplam = sum(
			int(row.bytes or 0)
			for row in frappe.get_all("Media Rendition", filters={"asset": asset}, fields=["bytes"])
		)
		self.assertEqual(rapor["totals"]["bytes"], toplam)
		self.assertEqual(rapor["asset"]["id"], asset)
		self.assertEqual(rapor["extra"]["trigger"], "upload")

	def test_production_bridge_34_gercek_rendition_12_saniye_altinda(self):
		# Arrange — 17 ayrı tuval × 2 format; cache kopyası değil 34 gerçek çıktı.
		self.assertTrue(PERF_FIXTURE.is_file(), "2400×2400 performans fixture'ı yok")
		widths = [(i + 1) * 96 for i in range(17)]
		_profil_olustur(
			self,
			"faz6-prod-perf",
			frappe.as_json(widths),
			formats=frappe.as_json(["webp", "jpeg"]),
			fit="contain",
			aspect_ratio="",
		)
		self._ayarla(max_renditions_per_asset=40)
		kaynak = PERF_FIXTURE.read_bytes()
		doc = self._doc("faz6-prod-perf.jpg", kaynak)

		# Act
		baslangic = time.perf_counter()
		with mock.patch.object(
			pipeline_bridge,
			"_record_generation_report",
			wraps=pipeline_bridge._record_generation_report,
		) as report_hook:
			pipeline_bridge._run_rendition_job(doc.file_url)
		sure = time.perf_counter() - baslangic
		asset = self._asset(doc)
		outcome = report_hook.call_args.args[3]
		satirlar = frappe.get_all(
			"Media Rendition",
			filters={"asset": asset},
			fields=["profile", "width", "format", "bytes", "ssim"],
		)

		# Assert
		self.assertEqual(len(satirlar), 34)
		self.assertEqual(len(outcome.results), 34)
		self.assertTrue(all(r.encodes <= 4 for r in outcome.results))
		self.assertTrue(all(not r.ssim_target or r.ssim >= r.ssim_target for r in outcome.results))
		self.assertEqual(
			len({(int(r.width), str(r.format)) for r in satirlar}),
			34,
		)
		self.assertTrue(all(int(r.bytes or 0) < len(kaynak) for r in satirlar))
		self.assertTrue(all(float(r.ssim or 0.0) > 0.0 for r in satirlar))
		self.assertLess(sure, 12.0, f"production bridge 34 rendition {sure:.3f} sn sürdü")

	def test_lazy_lock_takipcisi_encode_etmez(self):
		# Arrange
		_profil_olustur(self, "faz6-lazy-lock", "[96]", generation="lazy")
		doc = self._doc("faz6-lazy-lock.jpg", _gorsel_baytlari(320))
		pipeline_bridge._run_rendition_job(doc.file_url)
		asset = self._asset(doc)
		kilit = mock.Mock()
		kilit.acquire.return_value = False

		# Act
		with (
			mock.patch.object(pipeline_bridge.frappe.cache, "lock", return_value=kilit),
			mock.patch.object(pipeline_bridge, "_generate") as generate,
		):
			sonuc = pipeline_bridge.ensure_lazy_renditions(asset, blocking_timeout=0)

		# Assert
		self.assertEqual(sonuc["status"], "pending")
		generate.assert_not_called()

	def test_lazy_iki_gercek_eszamanli_cagrida_toplam_bir_encode(self):
		# Arrange — iki thread aynı eksik lazy profili görüp aynı kilide gelir.
		from PIL import Image

		from tradehub_core.media.pipeline.image import render as render_mod

		asset = mock.Mock()
		asset.name = "MA-LAZY-RACE"
		asset.slot_key = SLOT
		asset.media_type = "image"
		asset.state = "ready"
		asset.active_version = "MV-LAZY-RACE"
		asset.source_file = "FILE-LAZY-RACE"
		source = mock.Mock(is_private=0)
		source.get_content.return_value = _gorsel_baytlari(64)
		durum = {"ready": False, "encode": 0}
		durum_kilidi = threading.Lock()
		basla = threading.Barrier(2)

		class EszamanliKilit:
			def __init__(self):
				self._kilit = threading.Lock()
				self._iki_istek = threading.Barrier(2)

			def acquire(self):
				# İlk üretim başlamadan iki gerçek çağrının da lock kapısına
				# ulaştığını kanıtla; sonra tek sahibi normal mutex seçsin.
				self._iki_istek.wait(timeout=5)
				return self._kilit.acquire()

			def release(self):
				self._kilit.release()

		ortak_kilit = EszamanliKilit()
		sonuclar: list[dict] = []
		hatalar: list[BaseException] = []
		sahte_db = mock.Mock()
		sahte_db.exists.return_value = True
		sahte_cache = mock.Mock()
		sahte_cache.lock.return_value = ortak_kilit
		sahte_frappe = mock.Mock(db=sahte_db, cache=sahte_cache)
		sahte_frappe.get_doc.side_effect = lambda doctype, _name: (
			asset if doctype == "Media Asset" else source
		)

		def eksik(*_args, **_kwargs):
			with durum_kilidi:
				return () if durum["ready"] else ("faz6-lazy-race",)

		def tek_encode(*_args, **_kwargs):
			render_mod.encode(Image.new("RGB", (16, 16), (20, 40, 60)), "webp", 80)
			with durum_kilidi:
				durum["ready"] = True
			return pipeline_bridge.GenerationOutcome(required=1, ready=1)

		orijinal_encode = render_mod.encode

		def sayan_encode(*args, **kwargs):
			with durum_kilidi:
				durum["encode"] += 1
			return orijinal_encode(*args, **kwargs)

		def cagir():
			try:
				basla.wait(timeout=5)
				sonuclar.append(
					pipeline_bridge.ensure_lazy_renditions(
						asset.name,
						blocking_timeout=5,
					)
				)
			except BaseException as exc:  # noqa: BLE001 — thread hatası assert'e taşınır
				hatalar.append(exc)

		# Act — DB/disk çevresi sabitlenir; production fonksiyonunun çift kontrolü
		# ve gerçek bloklayan singleflight akışı iki thread üzerinde çalışır.
		with (
			# Frappe'nin `LocalProxy` DB nesnesi yeni thread'de bağlı değildir;
			# thread-safe sahte çevre yalnız dış I/O'yu sabitler, test edilen gerçek
			# `ensure_lazy_renditions` kontrol/lock akışını değiştirmez.
			mock.patch.object(pipeline_bridge, "frappe", sahte_frappe),
			mock.patch.object(pipeline_bridge.pipeline_flags, "is_enabled", return_value=True),
			mock.patch.object(pipeline_bridge.pipeline_flags, "is_slot_enabled", return_value=True),
			mock.patch.object(pipeline_bridge, "_missing_lazy_profiles", side_effect=eksik),
			mock.patch.object(pipeline_bridge, "_version_crop_intent", return_value=None),
			mock.patch.object(pipeline_bridge, "_generate", side_effect=tek_encode),
			mock.patch.object(pipeline_bridge, "_record_generation_report"),
			mock.patch.object(render_mod, "encode", side_effect=sayan_encode),
		):
			threadler = [threading.Thread(target=cagir) for _ in range(2)]
			for thread in threadler:
				thread.start()
			for thread in threadler:
				thread.join(timeout=10)

		# Assert
		self.assertTrue(all(not thread.is_alive() for thread in threadler), "lazy yarış kilitlendi")
		self.assertEqual(hatalar, [], f"lazy yarış hataları: {hatalar}")
		self.assertEqual(durum["encode"], 1, "iki eşzamanlı istek ikinci kez encode etti")
		self.assertCountEqual([sonuc["status"] for sonuc in sonuclar], ["generated", "cached"])

	def test_motor_ciktisi_100den_fazla_es_boyutlu_adayin_sonunda_bulunur(self):
		# Arrange — eşleşme eski 100 aday sınırının hemen arkasında.
		hedef = bytes(range(32))
		cache = mock.Mock()
		cache.get_value.return_value = None
		gorulen_limit: list[int] = []

		with tempfile.TemporaryDirectory() as kok:
			satirlar = []
			for index in range(101):
				icerik = hedef if index == 100 else index.to_bytes(2, "big") * 16
				yol = Path(kok) / f"aday-{index}.bin"
				yol.write_bytes(icerik)
				satirlar.append(
					{
						"name": f"MR-{index}",
						"asset": "MA-ENGINE",
						"profile": "w96",
						"format": "webp",
						"file_url": str(yol),
					}
				)

			def adaylari_getir(*_args, limit_page_length=20, **_kwargs):
				gorulen_limit.append(limit_page_length)
				return satirlar if limit_page_length == 0 else satirlar[:limit_page_length]

			# Act
			with (
				mock.patch.object(pipeline_bridge.frappe, "get_all", side_effect=adaylari_getir),
				mock.patch.object(pipeline_bridge.frappe, "cache", return_value=cache),
				mock.patch.object(pipeline_bridge, "_media_disk_path", side_effect=lambda url: url),
			):
				eslesme = pipeline_bridge._engine_output_match(hedef)

		# Assert
		self.assertIsNotNone(eslesme)
		self.assertEqual(eslesme["name"], "MR-100")
		self.assertEqual(gorulen_limit, [0, 0], "ledger ve legacy adayları sayfada kesildi")
		cache.set_value.assert_called_once()

	def test_rendition_dosyasi_temp_uzerinden_atomik_replace_edilir(self):
		# Arrange
		from tradehub_core.media.pipeline.core import dedup

		asset = "MA-ATOMIC"
		version = "a" * 64
		profil = "w96"
		icerik = b"yeni-tam-rendition"
		url = dedup.rendition_path(asset, version, profil, 96, "webp")
		gercek_replace = os.replace

		with tempfile.TemporaryDirectory() as kok:
			hedef = Path(kok) / url.removeprefix("/files/")
			hedef.parent.mkdir(parents=True, exist_ok=True)
			hedef.write_bytes(b"eski-tam-rendition")
			replace_cagrilari: list[tuple[str, str]] = []

			def replace_kontrol(kaynak, hedef_yol):
				# Final dosya replace anına kadar eski ve tam; yenisi yalnız tempte.
				self.assertEqual(Path(hedef_yol), hedef)
				self.assertNotEqual(Path(kaynak), hedef)
				self.assertEqual(hedef.read_bytes(), b"eski-tam-rendition")
				self.assertEqual(Path(kaynak).read_bytes(), icerik)
				replace_cagrilari.append((kaynak, hedef_yol))
				gercek_replace(kaynak, hedef_yol)

			# Act
			with (
				mock.patch.object(pipeline_bridge, "get_files_path", return_value=kok),
				mock.patch.object(pipeline_bridge.os, "replace", side_effect=replace_kontrol),
			):
				donen_url = pipeline_bridge._write_rendition_file(asset, version, profil, 96, "webp", icerik)

			# Assert
			self.assertEqual(donen_url, url)
			self.assertEqual(hedef.read_bytes(), icerik)
			self.assertEqual(len(replace_cagrilari), 1)
			self.assertEqual(list(hedef.parent.glob(f"{hedef.name}.tmp-*")), [])

	def test_motor_ciktisi_reupload_sifir_encode(self):
		# Arrange
		_profil_olustur(self, "faz6-reupload", "[96]")
		master = self._doc("faz6-reupload-master.jpg", _gorsel_baytlari(640))
		pipeline_bridge._run_rendition_job(master.file_url)
		asset = self._asset(master)
		row = frappe.db.get_value(
			"Media Rendition",
			{"asset": asset},
			["name", "file_url", "version_hash", "output_sha256", "engine_signature"],
			as_dict=True,
		)
		url = row.file_url
		with open(frappe.get_site_path("public", url.lstrip("/")), "rb") as handle:
			engine_output = handle.read()
		reupload = self._doc("faz6-reupload.webp", engine_output)

		# Act
		encode = self._encode_sayarak(lambda: pipeline_bridge._run_rendition_job(reupload.file_url))

		# Assert
		self.assertEqual(encode, 0)
		self.assertEqual(row.version_hash, frappe.db.get_value("Media Asset", asset, "active_version"))
		self.assertEqual(row.output_sha256, pipeline_bridge.content_sha256(engine_output))
		self.assertEqual(len(row.engine_signature or ""), 64)
		self.assertFalse(
			frappe.db.exists(
				"Media Asset",
				{"content_sha256": pipeline_bridge.content_fingerprint(reupload), "slot_key": SLOT},
			)
		)
		policy_job = frappe.db.get_value(
			"Media Processing Job",
			{"idempotency_key": f"engine-output-policy:{row.output_sha256}:{SLOT}"},
			["job_type", "status", "error_code"],
			as_dict=True,
		)
		self.assertEqual(dict(policy_job), {"job_type": "report", "status": "success", "error_code": None})

	def test_crop_omission_eski_rowu_tarihsel_tutar_aktif_manifestten_dusurur(self):
		# Arrange — 640px master'da w384 hazır; zoom=2 yeni crop genişliğini
		# 320px'e indirip aynı basamağı no-upscale nedeniyle omitted yapar.
		_profil_olustur(self, "faz6-crop-omit", "[384]")
		doc = self._doc("faz6-crop-omit.jpg", _gorsel_baytlari(640))
		pipeline_bridge._run_rendition_job(doc.file_url)
		asset = self._asset(doc)
		eski = frappe.db.get_value("Media Asset", asset, "active_version")
		eski_url = frappe.db.get_value("Media Rendition", {"asset": asset, "version_hash": eski}, "file_url")
		with open(frappe.get_site_path("public", eski_url.lstrip("/")), "rb") as handle:
			eski_engine_output = handle.read()
		intent = frappe.get_doc(
			{
				"doctype": "Media Crop Intent",
				"asset": asset,
				"zoom": 2.0,
				"center_x": 0.5,
				"center_y": 0.5,
				"method": "manual",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(intent.name, asset)

		# Act
		pipeline_bridge._run_crop_reprocess_job(asset)
		yeni = frappe.db.get_value("Media Asset", asset, "active_version")
		panel = media_manifest.manifest_batch([doc.name])
		reupload = self._doc("faz6-crop-omit-historical.webp", eski_engine_output)
		reupload_encode = self._encode_sayarak(lambda: pipeline_bridge._run_rendition_job(reupload.file_url))

		# Assert — eski exact-output ledger durur ama yalnız yeni active_version
		# okunur; omitted hedef sürümünde satır olmadığı için manifest boştur.
		self.assertNotEqual(yeni, eski)
		satirlar = frappe.get_all(
			"Media Rendition",
			filters={"asset": asset},
			fields=["version_hash", "profile", "output_sha256", "engine_signature"],
			limit_page_length=0,
		)
		self.assertEqual(len(satirlar), 1)
		self.assertEqual(satirlar[0].version_hash, eski)
		self.assertTrue(satirlar[0].output_sha256)
		self.assertTrue(satirlar[0].engine_signature)
		self.assertEqual(panel["manifests"][doc.name]["renditions"], [])
		self.assertEqual(media_manifest._turevleri_getir([asset], {asset: yeni}), {})
		self.assertEqual(reupload_encode, 0, "tarihsel exact engine output tekrar encode edilmemeli")
		self.assertFalse(
			frappe.db.exists(
				"Media Asset",
				{"content_sha256": pipeline_bridge.content_fingerprint(reupload), "slot_key": SLOT},
			)
		)

	def test_eksik_matris_active_version_degistirmez(self):
		# Arrange
		_profil_olustur(self, "faz6-incomplete", "[96]")
		doc = self._doc("faz6-incomplete.jpg", _gorsel_baytlari(320))
		eksik = pipeline_bridge.GenerationOutcome(required=2, ready=1, failed=1)

		# Act
		with (
			mock.patch.object(pipeline_bridge, "_generate", return_value=eksik),
			mock.patch.object(pipeline_bridge, "_promote_initial_version") as promote,
		):
			pipeline_bridge._run_rendition_job(doc.file_url)
		asset = self._asset(doc)

		# Assert
		promote.assert_not_called()
		self.assertIsNone(frappe.db.get_value("Media Asset", asset, "active_version"))
		self.assertEqual(frappe.db.get_value("Media Asset", asset, "state"), "failed")

	def test_reprocess_yarisinda_eksik_yeni_matris_eski_active_versioni_korur(self):
		# Arrange — okuyucunun hâlihazırda tam ve erişilebilir bir sürümü var.
		_profil_olustur(self, "faz6-reprocess-race", "[96, 192]")
		doc = self._doc("faz6-reprocess-race.jpg", _gorsel_baytlari(640))
		pipeline_bridge._run_rendition_job(doc.file_url)
		asset = self._asset(doc)
		eski_active = frappe.db.get_value("Media Asset", asset, "active_version")
		eski_url = frappe.get_all(
			"Media Rendition",
			filters={"asset": asset},
			pluck="file_url",
		)
		eksik = pipeline_bridge.GenerationOutcome(required=4, ready=3, failed=1)

		# Act — rakip reprocess tam matris kuramadan promote etmeye çalışıyor.
		with (
			mock.patch.object(pipeline_bridge, "_generate", return_value=eksik),
			mock.patch.object(pipeline_bridge, "_promote_complete_version") as promote,
		):
			basarili = pipeline_bridge._run_policy_reprocess_asset(asset)

		# Assert — okuyucu eski TAM sürümü ve bütün immutable dosyaları görür.
		self.assertFalse(basarili)
		promote.assert_not_called()
		self.assertEqual(frappe.db.get_value("Media Asset", asset, "active_version"), eski_active)
		self.assertTrue(eski_url)
		self.assertTrue(
			all(os.path.isfile(frappe.get_site_path("public", url.lstrip("/"))) for url in eski_url)
		)

	def test_eski_version_dosyasi_carry_forward_sonrasi_okunur(self):
		# Arrange
		_profil_olustur(self, "faz6-carry", "[96]")
		doc = self._doc("faz6-carry.jpg", _gorsel_baytlari(640))
		pipeline_bridge._run_rendition_job(doc.file_url)
		asset_name = self._asset(doc)
		asset = frappe.get_doc("Media Asset", asset_name)
		eski_url = frappe.db.get_value("Media Rendition", {"asset": asset_name}, "file_url")
		eski_yol = frappe.get_site_path("public", eski_url.lstrip("/"))
		icerik = doc.get_content()
		if isinstance(icerik, str):
			icerik = icerik.encode()
		yeni = pipeline_bridge._ensure_version(
			asset, SLOT, icerik, crop_intent={"zoom": 1.2, "center_x": 0.5, "center_y": 0.5}
		)

		# Act
		encode = self._encode_sayarak(
			lambda: self.assertTrue(pipeline_bridge._carry_forward_renditions(asset_name, yeni.version_hash))
		)
		yeni_url = frappe.db.get_value(
			"Media Rendition",
			{"asset": asset_name, "version_hash": yeni.version_hash},
			"file_url",
		)

		# Assert
		self.assertEqual(encode, 0)
		self.assertNotEqual(yeni_url, eski_url)
		self.assertEqual(frappe.db.count("Media Rendition", {"asset": asset_name}), 2)
		self.assertTrue(os.path.isfile(eski_yol), "eski immutable version silinmemeli")
		self.assertTrue(os.path.isfile(frappe.get_site_path("public", yeni_url.lstrip("/"))))

	def test_policy_bulk_asset_basi_planlanir_bulk_kuyrukta_ve_iptal_edilebilir(self):
		# Arrange / Act — üst uç her asset'i ayrı iş olarak rate-planlar.
		with mock.patch.object(pipeline_bridge, "_enqueue_scheduled_policy_item") as schedule:
			sonuc = pipeline_bridge.enqueue_policy_reprocess(
				["asset-a", "asset-b", "asset-c"], rate_per_minute=30
			)

		# Assert
		self.assertEqual(sonuc["queue"], "media-image-bulk")
		self.assertEqual(schedule.call_count, 3)
		self.assertEqual([c.kwargs["delay_seconds"] for c in schedule.call_args_list], [0.0, 2.0, 4.0])
		with mock.patch.object(pipeline_bridge.frappe, "enqueue") as enqueue:
			pipeline_bridge._enqueue_scheduled_policy_item(
				sonuc["token"], "asset-a", index=0, delay_seconds=0
			)
		self.assertEqual(enqueue.call_args.kwargs["queue"], "media-image-bulk")
		self.assertEqual(enqueue.call_args.kwargs["asset_name"], "asset-a")
		queue = mock.Mock()
		with mock.patch("frappe.utils.background_jobs.get_queue", return_value=queue) as get_queue:
			pipeline_bridge._enqueue_scheduled_policy_item(
				sonuc["token"], "asset-b", index=1, delay_seconds=2.0
			)
		get_queue.assert_called_once_with("media-image-bulk")
		self.assertEqual(queue.enqueue_in.call_args.args[0].total_seconds(), 2.0)
		envelope = queue.enqueue_in.call_args.kwargs["kwargs"]
		self.assertEqual(envelope["method"], "tradehub_core.media.pipeline_bridge._run_policy_reprocess_item")
		self.assertEqual(envelope["kwargs"], {"token": sonuc["token"], "asset_name": "asset-b"})

		# Cancel flag is checked before an independently scheduled item starts.
		iptal = pipeline_bridge.cancel_policy_reprocess(sonuc["token"])
		with mock.patch.object(pipeline_bridge, "_run_policy_reprocess_asset") as run:
			pipeline_bridge._run_policy_reprocess_item(sonuc["token"], "asset-b")
		run.assert_not_called()
		self.assertEqual(iptal["status"], "cancelling")
		self.assertEqual(pipeline_bridge.policy_reprocess_status(sonuc["token"])["status"], "cancelled")

	def test_legacy_policy_dispatcher_workerda_sleep_etmez(self):
		# Arrange / Act
		with (
			mock.patch.object(pipeline_bridge, "_enqueue_scheduled_policy_item") as schedule,
			mock.patch.object(pipeline_bridge.time, "sleep") as sleep,
		):
			pipeline_bridge._run_policy_reprocess_batch("legacy-token", ["a", "b"], rate_per_minute=10)

		# Assert
		self.assertEqual(schedule.call_count, 2)
		sleep.assert_not_called()
