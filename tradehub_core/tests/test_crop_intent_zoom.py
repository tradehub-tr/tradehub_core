"""T-105 B/C/E + T-114 — zoom/center kaydı ve sunucu onay kapısı.

İki kayıp bu görevle kapandı; bu modül ikisinin de geri gelmemesini ölçer:

  1. **Zoom kayboluyordu.** Stüdyo pencereyi
     `cropWindow(zoomBase(zoom, center), targetAR, focal)` ile kurar; yük
     yalnız odak taşıdığı için sunucu pencereyi daima tam kadrajdan
     kuruyordu (ölçüldü: `cropPixelParity` B sınıfı 119/120 sapan, 7391 px'e
     kadar). Artık `Media Crop Intent` zoom üçlüsünü (zoom, center_x,
     center_y) taşıyor ve `core/crop.py::zoom_region_of` taban bölgeyi
     yeniden kuruyor (yeni ölçüm: B sınıfı 3/120 sapan, en büyük 1 px).
  2. **Onay kapısı yalnız istemcideydi.** T-114 şartnamesi
     (62-faz11-simulator.html): "Kayıt sunucu tarafında da doğrulanıyor:
     eksik previewed_placements ile publish reddediliyor. Frontend
     atlatılamaz." Kapı iki katmanda: uç (400 + MEDIA_PREVIEW_REQUIRED) ve
     DocType doğrulaması (ORM yüzeyi).

Vacuity ölçümü: kapı kaldırılarak (approved_by_user kontrol satırları geçici
yorumlanarak) `test_onay_kaniti_olmadan_reddedilir` ve
`test_orm_yuzeyinde_de_kapi_var` KIRMIZI gösterildi, sonra kapı geri kondu —
testler kapıyı gerçekten ölçüyor, kendiliğinden yeşil değiller.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_crop_intent_zoom
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_crop
from tradehub_core.media.pipeline.core import crop as crop_core
from tradehub_core.media.pipeline.core import crop_geometry

INTENT = "Media Crop Intent"
SLOT = "product.image"

#: Kapıdan geçen asgari kanıt — SimApprovalGate'in gönderdiği biçimde.
KANIT = [{"device_kind": "phone", "page": "listing", "profile": "product-main"}]


def _sil(doctype: str, name: str) -> None:
	"""Kaydı varsa siler ve KALICI yapar (uçlar kendi içinde commit atıyor)."""
	if frappe.db.exists(doctype, name):
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
		frappe.db.commit()


class CropIntentZoomTests(FrappeTestCase):
	# -- fixture yardımcıları (test_media_crop_intent.py ile aynı desen) -----

	def _user(self, tag: str, roles: tuple[str, ...]) -> str:
		email = f"t105z-{tag}-{self.suffix}@test.local"
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": tag,
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: _sil("User", doc.name))
		return doc.name

	def _store(self, tag: str, user: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_code": f"T105Z{tag}{self.suffix}",
				"seller_name": f"T105Z {tag} {self.suffix}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: _sil("Admin Seller Profile", doc.name))
		return doc.name

	def _asset(self, store: str, tag: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": SLOT,
				"media_type": "image",
				"state": "ready",
				"owner_seller": store,
				"content_sha256": frappe.generate_hash(length=64),
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: _sil(INTENT, doc.name))
		self.addCleanup(lambda: _sil("Media Asset", doc.name))
		return doc.name

	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)
		self.owner = self._user("owner", ("Marketplace Seller", "Seller"))
		self.owner_store = self._store("A", self.owner)
		self.asset = self._asset(self.owner_store, "a")

	# -- 1. zoom üçlüsü: kayıt + geri okuma -----------------------------------

	def test_zoom_kaydedilir_ve_okunur(self):
		"""Üçlü yazılır, yanıt ve DB aynı sayıyı verir; alanlar şemada VAR."""
		frappe.set_user(self.owner)
		cevap = media_crop.save_intent(
			asset=self.asset,
			focal_x=0.3,
			focal_y=0.7,
			zoom=2.5,
			center_x=0.6,
			center_y=0.4,
			method="manual",
		)
		self.assertEqual(cevap["status"], 200)
		self.assertAlmostEqual(cevap["intent"]["zoom"], 2.5, places=6)
		self.assertAlmostEqual(cevap["intent"]["center_x"], 0.6, places=6)
		self.assertAlmostEqual(cevap["intent"]["center_y"], 0.4, places=6)

		okuma = media_crop.get_intent(asset=self.asset)
		self.assertAlmostEqual(okuma["intent"]["zoom"], 2.5, places=6)

		frappe.set_user("Administrator")
		satir = frappe.db.get_value(
			INTENT, self.asset, ["zoom", "center_x", "center_y"], as_dict=True
		)
		self.assertAlmostEqual(float(satir["zoom"]), 2.5, places=6)
		self.assertAlmostEqual(float(satir["center_x"]), 0.6, places=6)
		self.assertAlmostEqual(float(satir["center_y"]), 0.4, places=6)

	def test_zoom_penceresi_yanittaki_pencerelere_yansir(self):
		"""Kaydedilen zoom, çözülen pencereye GERÇEKTEN girer (2. seviye).

		Varlığın ölçüsü bilinmiyor (source_file yok) → kare varsayımı; zoom=2,
		merkez ve odak ortada → taban bölge (0.25, 0.25, 0.5, 0.5). Bu slotun
		profilleri pad/contain (oran zorlanmaz, ölçüldü: product-image.json),
		yani pencere taban bölgenin KENDİSİ olmalı — zoom yine de 2. seviyeyi
		(`safe_focal`) seçtirir ve pencereyi tam kadrajdan taban bölgeye indirir.
		"""
		frappe.set_user(self.owner)
		cevap = media_crop.save_intent(
			asset=self.asset,
			focal_x=0.5,
			focal_y=0.5,
			zoom=2,
			center_x=0.5,
			center_y=0.5,
			method="manual",
		)
		pencereler = cevap["windows"]
		self.assertTrue(pencereler, "slot profilleri yüklenmedi — ölçüm boş")
		for w in pencereler:
			self.assertEqual(w["method"], "safe_focal", f"zoom tabanı kullanılmamış: {w}")
			self.assertGreaterEqual(w["x"], 0.25 - 1e-6)
			self.assertGreaterEqual(w["y"], 0.25 - 1e-6)
			self.assertLessEqual(w["x"] + w["w"], 0.75 + 1e-6)
			self.assertLessEqual(w["y"] + w["h"], 0.75 + 1e-6)

	# -- 2. aralık ve bütünlük redleri ---------------------------------------

	def test_zoom_aralik_disi_reddedilir(self):
		"""ZOOM_MIN altı ve ZOOM_MAX üstü 400 ile döner; kayıt oluşmaz."""
		frappe.set_user(self.owner)
		for kotu in (0.5, 17, "abc"):
			with self.assertRaises(frappe.ValidationError):
				media_crop.save_intent(
					asset=self.asset, focal_x=0.5, focal_y=0.5,
					zoom=kotu, center_x=0.5, center_y=0.5,
				)
		frappe.set_user("Administrator")
		self.assertFalse(
			frappe.db.exists(INTENT, self.asset),
			"aralık dışı zoom kelepçelenip kaydedilmiş",
		)

	def test_center_aralik_disi_reddedilir(self):
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			media_crop.save_intent(
				asset=self.asset, focal_x=0.5, focal_y=0.5,
				zoom=2, center_x=1.4, center_y=0.5,
			)

	def test_yarim_uclu_reddedilir(self):
		"""Zoom merkezsiz (ya da merkez zoom'suz) taşınamaz."""
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			media_crop.save_intent(asset=self.asset, focal_x=0.5, focal_y=0.5, zoom=2)
		with self.assertRaises(frappe.ValidationError):
			media_crop.save_intent(
				asset=self.asset, focal_x=0.5, focal_y=0.5, center_x=0.5, center_y=0.5
			)

	def test_controller_zoom_araligini_korur(self):
		"""Uç atlanıp ORM ile yazılsa bile aralık DocType'ta durur."""
		frappe.set_user("Administrator")
		doc = frappe.get_doc(
			{"doctype": INTENT, "asset": self.asset, "zoom": 0.5, "center_x": 0.5, "center_y": 0.5}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	# -- 3. geriye uyumluluk: parametresiz eski çağrı -------------------------

	def test_eski_cagri_zoom_bilmeden_calisir(self):
		"""Zoom göndermeyen eski çağrı AYNEN çalışır; üçlü yazılmamış kalır."""
		frappe.set_user(self.owner)
		cevap = media_crop.save_intent(
			asset=self.asset, focal_x=0.25, focal_y=0.75, method="manual"
		)
		self.assertEqual(cevap["status"], 200)
		self.assertIsNone(cevap["intent"]["zoom"], "yazılmamış zoom uydurulmuş")
		self.assertIsNone(cevap["intent"]["center_x"])
		# Pencere eski davranışla aynı: 3. seviye (odak), taban tam kare.
		oranli = [w for w in cevap["windows"] if w.get("target_ratio")]
		for w in oranli:
			self.assertEqual(w["method"], "focal")

	def test_parametresiz_cagri_kayitli_zoomu_korur(self):
		"""None = "dokunma": yalnız odak güncelleyen çağrı üçlüyü SİLMEZ."""
		frappe.set_user(self.owner)
		media_crop.save_intent(
			asset=self.asset, focal_x=0.5, focal_y=0.5,
			zoom=3, center_x=0.5, center_y=0.5, method="manual",
		)
		cevap = media_crop.save_intent(asset=self.asset, focal_x=0.4, focal_y=0.6)
		self.assertAlmostEqual(cevap["intent"]["zoom"], 3.0, places=6)
		self.assertAlmostEqual(cevap["intent"]["focal_x"], 0.4, places=6)

	def test_safe_area_zoomsuz_gelirse_ucluyu_siler(self):
		"""Eski istemci tabanı `safe_area` ile yeniden tanımlarsa bayat zoom
		onu gölgelememeli — üçlü silinir (gerekçe `pipeline/api/crop.py`)."""
		frappe.set_user(self.owner)
		media_crop.save_intent(
			asset=self.asset, focal_x=0.5, focal_y=0.5,
			zoom=3, center_x=0.5, center_y=0.5, method="manual",
		)
		cevap = media_crop.save_intent(
			asset=self.asset, focal_x=0.5, focal_y=0.5,
			safe_area={"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
		)
		self.assertIsNone(cevap["intent"]["zoom"], "bayat zoom safe_area'yı gölgeler")
		self.assertAlmostEqual(cevap["intent"]["safe_x"], 0.1, places=6)

	# -- 4. T-114 onay kapısı -------------------------------------------------

	def test_onay_kaniti_olmadan_reddedilir(self):
		"""approved=1 + boş previewed_placements → red; kayıt OLUŞMAZ."""
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			media_crop.save_intent(
				asset=self.asset, focal_x=0.5, focal_y=0.5, approved_by_user=1
			)
		frappe.set_user("Administrator")
		self.assertFalse(
			frappe.db.exists(INTENT, self.asset),
			"kanıtsız onay kaydedilmiş — T-114 kapısı delik",
		)

	def test_bos_liste_kanit_sayilmaz(self):
		"""`[]` göndererek kapı atlatılamaz — boş kanıt, kanıt değildir."""
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			media_crop.save_intent(
				asset=self.asset, focal_x=0.5, focal_y=0.5,
				approved_by_user=1, previewed_placements=[],
			)

	def test_onay_kanitla_kaydedilir(self):
		frappe.set_user(self.owner)
		cevap = media_crop.save_intent(
			asset=self.asset, focal_x=0.5, focal_y=0.5,
			approved_by_user=1, previewed_placements=KANIT,
		)
		self.assertEqual(cevap["status"], 200)
		self.assertTrue(cevap["intent"]["approved_by_user"])

	def test_onaysiz_kayit_kanit_istemez(self):
		"""approved=0 eski davranıştır: kanıtsız kaydedilebilir (öneri akışı)."""
		frappe.set_user(self.owner)
		cevap = media_crop.save_intent(
			asset=self.asset, focal_x=0.5, focal_y=0.5, approved_by_user=0
		)
		self.assertEqual(cevap["status"], 200)

	def test_kayitli_kanit_sonraki_onayda_gecerli(self):
		"""Kanıt bir kez yazıldıysa sonraki onaylı yazım yeniden göndermek
		zorunda değil — kapı isteği DEĞİL kaydı ölçer."""
		frappe.set_user(self.owner)
		media_crop.save_intent(
			asset=self.asset, focal_x=0.5, focal_y=0.5,
			approved_by_user=1, previewed_placements=KANIT,
		)
		cevap = media_crop.save_intent(
			asset=self.asset, focal_x=0.6, focal_y=0.6, approved_by_user=1
		)
		self.assertEqual(cevap["status"], 200)
		self.assertTrue(cevap["intent"]["approved_by_user"])

	def test_orm_yuzeyinde_de_kapi_var(self):
		"""Uç atlanıp doğrudan doc yazılsa bile kanıtsız onay geçemez."""
		frappe.set_user("Administrator")
		doc = frappe.get_doc(
			{"doctype": INTENT, "asset": self.asset, "approved_by_user": 1}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	# -- 5. çözücü katman + sabit eşitliği ------------------------------------

	def test_zoom_sabitleri_geometriyle_ayni(self):
		"""`core/crop.py` sabitleri `crop_geometry`den import EDEMEZ (parite
		üreticisi dosyayı paketsiz yüklüyor); kopya buradan kilitlenir."""
		self.assertEqual(crop_core.ZOOM_MIN, crop_geometry.ZOOM_MIN)
		self.assertEqual(crop_core.ZOOM_MAX, crop_geometry.ZOOM_MAX)

	def test_zoom_region_of_zoom_base_ile_ayni_pencere(self):
		"""Normalize kurulum, piksel uzayındaki `zoom_base` ile birebir aynı
		bölgeyi vermeli — 3×2 dejenere kaynak (MIN_EDGE_PX tabanı) dahil."""
		durumlar = [
			(4000, 3000, 2.5, 0.6, 0.4),
			(1920, 1080, 7.9999, 0.01, 0.99),
			(3, 2, 8.0, 0.5, 0.5),  # 1 px tabanı devreye girer
			(8688, 8368, 1.0001, 0.5, 0.5),
		]
		for sw, sh, z, cx, cy in durumlar:
			beklenen = crop_geometry.zoom_base(sw, sh, z, cx, cy)
			bolge = crop_core.zoom_region_of(
				{"zoom": z, "center_x": cx, "center_y": cy}, sw, sh
			)
			self.assertIsNotNone(bolge, f"bölge üretilmedi: {(sw, sh, z)}")
			for ad, gercek, hedef in (
				("x", bolge.x * sw, beklenen.x),
				("y", bolge.y * sh, beklenen.y),
				("w", bolge.w * sw, beklenen.w),
				("h", bolge.h * sh, beklenen.h),
			):
				self.assertLess(
					abs(gercek - hedef),
					crop_geometry.PARITY_TOLERANCE_PX,
					f"{ad} sapıyor ({sw}×{sh} z={z}): {gercek} != {hedef}",
				)

	def test_zoom_bir_tam_kare_yazilmamis_sayilir(self):
		"""zoom=1 tam kadrajdır → bölge None; zincir eski davranışta kalır.
		DB varsayılanı 0 da (yazılmamış) None vermeli."""
		self.assertIsNone(
			crop_core.zoom_region_of({"zoom": 1, "center_x": 0.5, "center_y": 0.5})
		)
		self.assertIsNone(
			crop_core.zoom_region_of({"zoom": 0, "center_x": 0.0, "center_y": 0.0})
		)
		self.assertIsNone(crop_core.zoom_region_of({"zoom": 2, "center_x": None, "center_y": 0.5}))
