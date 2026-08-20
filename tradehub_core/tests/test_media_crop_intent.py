"""T-041/T-082 — `Media Crop Intent` kiracı izolasyonu + kaydetme ucu.

`Media Crop Intent` sahiplik kolonu TAŞIMAZ; izolasyon `asset` üzerinden
`Media Asset.owner_seller`a zincirlenir. Zincirlenmiş izolasyonun tehlikesi
sessiz kırılmasıdır: kanca kaydı düşerse DocPerm satırı (`Seller: read=1,
write=1, if_owner=0`) tek başına AÇIK kalır ve her satıcı her niyeti okur.
Bu modül o kapıyı üç yönden ölçer:

  1. Varlığın sahibi satıcı kendi niyetini KAYDEDER ve OKUR.
  2. BAŞKA satıcı ne okuyabilir ne yazabilir (uç + ORM + liste sorgusu).
  3. `Guest` reddedilir.

Ayrıca ucun sözleşmesi sınanır: idempotency (aynı varlık için ikinci çağrı
satır açmaz), 0-1 sözleşmesi (aralık dışı REDDEDİLİR, kelepçelenmez) ve
`suggest_focal`ın gerçek bir görselde 0-1 aralığında odak döndürmesi.

`test_hooks_registered` vacuity korumasıdır: kanca kaydı silinirse 2. gruptaki
testler yalancı yeşile dönmeden önce o test kırmızıya döner.

Gerçek DB kullanılır (`FrappeTestCase`): sınanan şey Frappe'nin izin motoru,
stub'lanamaz.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_media_crop_intent
"""

from __future__ import annotations

import io

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core import permissions
from tradehub_core.api import media_crop

INTENT = "Media Crop Intent"
SLOT = "product.image"


def _sil(doctype: str, name: str) -> None:
	"""Kaydı varsa siler ve KALICI yapar (uçlar kendi içinde commit atıyor)."""
	if frappe.db.exists(doctype, name):
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
		frappe.db.commit()


def _gorsel_baytlari(kenar: int = 320) -> bytes:
	"""Kenar enerjisi TOPLANMIŞ bir JPEG: sol üst çeyrekte desen, kalanı düz.

	Düz renk görselde `focal_from_bytes` `no_edge_energy` ile merkeze düşer;
	odağın gerçekten ÖLÇÜLDÜĞÜNÜ göstermek için enerjinin bir yerde
	yoğunlaşması gerekir.
	"""
	from PIL import Image

	im = Image.new("RGB", (kenar, kenar), (200, 200, 200))
	pikseller = im.load()
	for y in range(kenar // 2):
		for x in range(kenar // 2):
			if (x + y) % 2 == 0:
				pikseller[x, y] = (10, 10, 10)
	buf = io.BytesIO()
	im.save(buf, "JPEG", quality=95)
	return buf.getvalue()


class MediaCropIntentTests(FrappeTestCase):
	# -- fixture yardımcıları ------------------------------------------------

	def _user(self, tag: str, roles: tuple[str, ...]) -> str:
		email = f"t082-{tag}-{self.suffix}@test.local"
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
				"seller_code": f"T082{tag}{self.suffix}",
				"seller_name": f"T082 {tag} {self.suffix}",
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

	def _file(self, tag: str, content: bytes) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"t082-{tag}-{self.suffix}.jpg",
				"content": content,
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: _sil("File", doc.name))
		return doc.name

	def _asset(self, store: str, tag: str, source_file: str | None = None) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": SLOT,
				"media_type": "image",
				"state": "ready",
				"owner_seller": store,
				"content_sha256": frappe.generate_hash(length=64),
				"source_file": source_file,
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: _sil(INTENT, doc.name))
		self.addCleanup(lambda: _sil("Media Asset", doc.name))
		return doc.name

	# -- kurulum -------------------------------------------------------------

	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)

		self.owner = self._user("owner", ("Marketplace Seller", "Seller"))
		self.other = self._user("other", ("Marketplace Seller", "Seller"))
		self.admin = self._user("admin", ("Marketplace Admin",))

		self.owner_store = self._store("A", self.owner)
		self.other_store = self._store("B", self.other)

		self.asset = self._asset(self.owner_store, "a")
		# Saldırganın KENDİ varlığı: liste testinde "kendi kaydı da yok"
		# yanılgısını dışlar.
		self.other_asset = self._asset(self.other_store, "b")

	# -- 1. sahibi satıcı: ÇALIŞMALI ----------------------------------------

	def test_owner_saves_and_reads_own_intent(self):
		"""Varlığın sahibi kendi niyetini kaydeder ve geri okur."""
		frappe.set_user(self.owner)
		yazma = media_crop.save_intent(
			asset=self.asset,
			focal_x=0.25,
			focal_y=0.75,
			method="manual",
			approved_by_user=1,
			# T-114 sunucu kapısı: onay artık önizleme kanıtı İSTİYOR
			# (şartname zorunlu diyor; kanıtsız onay testi
			# test_crop_intent_zoom.py::test_onay_kaniti_olmadan_reddedilir).
			# Bu bir gevşetme değil, sözleşme değişikliği: eski çağrı biçimi
			# onaySIZ yazımlarda aynen çalışıyor.
			previewed_placements=[{"device_kind": "phone", "page": "listing"}],
		)
		self.assertEqual(yazma["status"], 200)
		self.assertTrue(yazma["exists"])
		self.assertAlmostEqual(yazma["intent"]["focal_x"], 0.25, places=6)
		self.assertAlmostEqual(yazma["intent"]["focal_y"], 0.75, places=6)

		okuma = media_crop.get_intent(asset=self.asset)
		self.assertTrue(okuma["exists"])
		self.assertAlmostEqual(okuma["intent"]["focal_x"], 0.25, places=6)
		self.assertEqual(okuma["intent"]["method"], "manual")

		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value(INTENT, self.asset, "method"),
			"manual",
			"şema vokabüleri DB'ye yazılmamış",
		)

	def test_intent_absent_returns_exists_false_not_404(self):
		"""Niyet yazılmamışsa 404 DEĞİL, `exists: false` ile 200 döner."""
		frappe.set_user(self.owner)
		cevap = media_crop.get_intent(asset=self.asset)
		self.assertEqual(cevap["status"], 200)
		self.assertFalse(cevap["exists"])
		self.assertIsNone(cevap["intent"]["focal_x"], "yazılmamış odak 0.5 ile doldurulmuş")

	# -- 2. başka satıcı: REDDEDİLMELİ --------------------------------------

	def test_cross_tenant_read_denied(self):
		"""BAŞKA satıcı niyeti uç üzerinden okuyamaz (404 — varlık sızmasın)."""
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=self.asset, focal_x=0.25, focal_y=0.75, method="manual")

		frappe.set_user(self.other)
		with self.assertRaises(frappe.ValidationError):
			media_crop.get_intent(asset=self.asset)

	def test_cross_tenant_write_denied(self):
		"""BAŞKA satıcı niyet yazamaz; DB'de değer DEĞİŞMEZ."""
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=self.asset, focal_x=0.25, focal_y=0.75, method="manual")

		frappe.set_user(self.other)
		with self.assertRaises(frappe.ValidationError):
			media_crop.save_intent(asset=self.asset, focal_x=0.9, focal_y=0.9, method="manual")

		frappe.set_user("Administrator")
		self.assertAlmostEqual(
			float(frappe.db.get_value(INTENT, self.asset, "focal_x")),
			0.25,
			places=6,
			msg="reddedilmesine rağmen DB'de değer değişmiş",
		)

	def test_cross_tenant_orm_read_denied(self):
		"""ORM yüzeyi de kapalı — uç tek kapı değil."""
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=self.asset, focal_x=0.25, focal_y=0.75, method="manual")

		frappe.set_user(self.other)
		doc = frappe.get_doc(INTENT, self.asset)
		self.assertFalse(
			frappe.has_permission(INTENT, "read", doc=doc, user=self.other),
			"başka satıcı niyeti okuyabiliyor",
		)
		self.assertFalse(
			frappe.has_permission(INTENT, "write", doc=doc, user=self.other),
			"başka satıcı niyete yazabiliyor",
		)

	def test_list_excludes_other_tenants(self):
		"""Liste sorgusu çapraz kiracıyı sızdırmaz, kendi kaydını verir."""
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=self.asset, focal_x=0.25, focal_y=0.75, method="manual")
		frappe.set_user(self.other)
		media_crop.save_intent(asset=self.other_asset, focal_x=0.5, focal_y=0.5, method="manual")

		names = [r["name"] for r in frappe.get_list(INTENT, fields=["name"], limit_page_length=0)]
		self.assertNotIn(self.asset, names, "liste sorgusunda çapraz kiracı sızıntısı")
		self.assertIn(self.other_asset, names, "kendi kaydı listede yok")

	def test_query_conditions_chain_to_asset_owner(self):
		"""Üretilen SQL `asset` üzerinden `owner_seller`a zincirlenmeli."""
		cond = permissions.media_crop_intent_query_conditions(self.other)
		self.assertIn("`tabMedia Crop Intent`.`asset`", cond)
		self.assertIn("tabMedia Asset", cond)
		self.assertIn(frappe.db.escape(self.other_store), cond)

	# -- 3. Guest: REDDEDİLMELİ ---------------------------------------------

	def test_guest_denied(self):
		"""Oturumsuz çağıran hiçbir uca giremez."""
		frappe.set_user("Guest")
		with self.assertRaises(frappe.ValidationError):
			media_crop.get_intent(asset=self.asset)
		with self.assertRaises(frappe.ValidationError):
			media_crop.save_intent(asset=self.asset, focal_x=0.5, focal_y=0.5)

	def test_guest_query_condition_blocks_everything(self):
		self.assertEqual(permissions.media_crop_intent_query_conditions("Guest"), "1=0")
		self.assertFalse(permissions.media_crop_intent_has_permission(None, "read", "Guest"))

	# -- 4. sözleşme: idempotency + 0-1 + öneri ------------------------------

	def test_save_intent_is_idempotent(self):
		"""Aynı varlık için iki çağrı — satır sayısı ARTMAZ."""
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=self.asset, focal_x=0.25, focal_y=0.75, method="manual")
		ilk = frappe.db.count(INTENT, {"asset": self.asset})
		media_crop.save_intent(asset=self.asset, focal_x=0.4, focal_y=0.6, method="manual")
		ikinci = frappe.db.count(INTENT, {"asset": self.asset})

		self.assertEqual(ilk, 1)
		self.assertEqual(ikinci, 1, "ikinci kayıt açıldı — idempotency kırık")
		frappe.set_user("Administrator")
		self.assertAlmostEqual(
			float(frappe.db.get_value(INTENT, self.asset, "focal_x")), 0.4, places=6
		)

	def test_out_of_range_rejected_not_clamped(self):
		"""1'den büyük koordinat REDDEDİLİR; kayıt oluşmaz."""
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			media_crop.save_intent(asset=self.asset, focal_x=1.4, focal_y=0.5)
		frappe.set_user("Administrator")
		self.assertFalse(
			frappe.db.exists(INTENT, self.asset),
			"aralık dışı değer kelepçelenip kaydedilmiş",
		)

	def test_unknown_method_rejected(self):
		"""Şema vokabüleri dışındaki yöntem reddedilir (`edge_energy_v1` dahil)."""
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			media_crop.save_intent(
				asset=self.asset, focal_x=0.5, focal_y=0.5, method="edge_energy_v1"
			)

	def test_controller_rejects_half_written_focal(self):
		"""Denetim katmanı atlansa bile yarım odak DocType'ta durur."""
		frappe.set_user("Administrator")
		doc = frappe.get_doc({"doctype": INTENT, "asset": self.asset, "focal_x": 0.3})
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_suggest_focal_on_real_image(self):
		"""Gerçek görselde odak ölçülür ve 0-1 aralığında döner."""
		frappe.set_user("Administrator")
		dosya = self._file("img", _gorsel_baytlari())
		asset = self._asset(self.owner_store, "img", source_file=dosya)

		frappe.set_user(self.owner)
		cevap = media_crop.suggest_focal(asset=asset)
		oneri = cevap["suggestion"]

		self.assertEqual(cevap["status"], 200)
		self.assertTrue(0.0 <= oneri["focal_x"] <= 1.0, f"focal_x aralık dışı: {oneri['focal_x']}")
		self.assertTrue(0.0 <= oneri["focal_y"] <= 1.0, f"focal_y aralık dışı: {oneri['focal_y']}")
		self.assertTrue(0.0 <= oneri["confidence"] <= 1.0)
		# Eşik kalibre EDİLMEDİ; uç bunu yanıtta taşımak zorunda.
		self.assertFalse(oneri["threshold_calibrated"])
		# Öneri YAZILMAZ — kullanıcı onayına sunulur.
		self.assertFalse(cevap["applied"])
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists(INTENT, asset), "suggest_focal niyet kaydı açmış")

	def test_suggest_focal_cross_tenant_denied(self):
		frappe.set_user(self.other)
		with self.assertRaises(frappe.ValidationError):
			media_crop.suggest_focal(asset=self.asset)

	# -- 5. meşru geniş erişim + vacuity ------------------------------------

	def test_marketplace_admin_keeps_access(self):
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=self.asset, focal_x=0.25, focal_y=0.75, method="manual")

		frappe.set_user(self.admin)
		doc = frappe.get_doc(INTENT, self.asset)
		self.assertTrue(frappe.has_permission(INTENT, "read", doc=doc, user=self.admin))
		self.assertEqual(permissions.media_crop_intent_query_conditions(self.admin), "")

	def test_hooks_registered(self):
		"""Vacuity koruması: kanca kaydı silinirse izolasyon testleri yalancı
		yeşile dönmeden ÖNCE bu test kırmızıya döner."""
		hooks = frappe.get_hooks()
		self.assertIn(
			"tradehub_core.permissions.media_crop_intent_query_conditions",
			hooks.get("permission_query_conditions", {}).get(INTENT, []),
		)
		self.assertIn(
			"tradehub_core.permissions.media_crop_intent_has_permission",
			hooks.get("has_permission", {}).get(INTENT, []),
		)
