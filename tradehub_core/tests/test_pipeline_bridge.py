# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""`media.pipeline_bridge` testleri — Dalga A2 (türev üretimini tetikleme).

EN ÖNEMLİ TEST `test_bayrak_kapaliyken_enqueue_cagrilmaz`: bayrak kapalıyken
(varsayılan) kanca hiçbir şey yapmamalı. Dalga A'nın tüm güvencesi buna
yaslanıyor — kanca hooks.py'ye eklendi, ama sistemin bugünkü davranışı birebir
aynı kalmalı.

Eksenler:
  1. Bayrak KAPALI → `frappe.enqueue` hiç çağrılmaz.
  2. Bayrak AÇIK → `queue="long"`, `timeout=1800`, `enqueue_after_commit=True`.
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
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import pipeline_bridge, pipeline_flags

DOCTYPE_AYAR = pipeline_flags.SETTINGS_DOCTYPE
KORUNAN_ALANLAR = (
	"media_pipeline_enabled",
	"rendition_on_upload",
	"active_slots",
	"max_renditions_per_asset",
)

SLOT = "product.image"


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


def _dosya_ekle(test, file_name: str, icerik: bytes, **alanlar: object):
	"""Bayraklar KAPALIYKEN dosya ekler (kanca no-op olsun) ve temizliğe yazar."""
	doc = frappe.get_doc(
		{"doctype": "File", "file_name": file_name, "is_private": 0, "content": icerik}
	)
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
		self._ayarla(media_pipeline_enabled=1, rendition_on_upload=1, active_slots=SLOT)


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

	def test_bayrak_acikken_long_kuyruga_atilir(self):
		self._hatti_ac()

		with mock.patch("tradehub_core.media.pipeline_bridge.frappe.enqueue") as m:
			pipeline_bridge.maybe_generate_renditions(self.doc)

		m.assert_called_once()
		args, kwargs = m.call_args
		self.assertEqual(args[0], "tradehub_core.media.pipeline_bridge._run_rendition_job")
		self.assertEqual(kwargs.get("queue"), "long")
		self.assertEqual(kwargs.get("timeout"), 1800)
		self.assertTrue(kwargs.get("enqueue_after_commit"))
		self.assertEqual(kwargs.get("file_url"), self.doc.file_url)


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


def _profil_olustur(test, profile_key: str, widths: str, formats: str = '["webp"]'):
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
			"aspect_ratio": "1:1",
			"fit": "pad",
			"widths": widths,
			"formats": formats,
			"quality_target": 80,
			"generation": "eager",
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
		self.assertEqual(
			frappe.db.get_value("File", ikiz.name, "content_hash"), self.doc.content_hash
		)
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
		asset_name = frappe.db.get_value(
			"Media Asset", {"content_sha256": surum, "slot_key": SLOT}, "name"
		)
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

		encode_sayisi = self._encode_sayarak(
			lambda: pipeline_bridge._run_rendition_job(self.doc.file_url)
		)

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

		encode_sayisi = self._encode_sayarak(
			lambda: pipeline_bridge._run_rendition_job(self.doc.file_url)
		)

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

		encode_sayisi = self._encode_sayarak(
			lambda: pipeline_bridge._run_rendition_job(self.doc.file_url)
		)

		self.assertGreater(encode_sayisi, 0, "bozuk dosya körlemesine atlanmamalı")
		geri = frappe.get_all(
			"Media Rendition",
			filters={"asset": asset_name, "file_url": hedef.file_url},
			fields=["bytes"],
		)
		self.assertEqual(len(geri), 1)
		self.assertEqual(geri[0].bytes, hedef.bytes, "yeniden üretim deterministik baytı geri yazmalı")
		self.assertEqual(os.path.getsize(yol), hedef.bytes, "diskteki bozuk dosya onarılmalı")
