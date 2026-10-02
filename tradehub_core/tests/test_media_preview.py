"""Görsel önizleme uçları + odak okuması (2026-10-01).

    docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && \
        bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_preview"
"""

from __future__ import annotations

import io

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tradehub_core.api import media_crop, media_preview
from tradehub_core.media import odak
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401

INTENT = "Media Crop Intent"
SLOT = "company.cover_image"


def _sil(doctype: str, name: str) -> None:
	if frappe.db.exists(doctype, name):
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
		frappe.db.commit()


def _png(w: int = 2000, h: int = 408) -> bytes:
	buf = io.BytesIO()
	Image.new("RGB", (w, h), (30, 60, 90)).save(buf, "PNG")
	return buf.getvalue()


class MediaPreviewTests(FrappeTestCase):
	def _user(self, tag: str, roles: tuple[str, ...] = ("Marketplace Seller", "Seller")) -> str:
		email = f"onz-{tag}-{self.suffix}@test.local"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": tag,
				# Açık kullanıcı adı: paralel testlerle `first_name`→`username` çakışma yarışını önler.
				"username": f"onz-{tag}-{self.suffix}",
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)  # test kurulumu
		frappe.db.commit()
		self.addCleanup(lambda: _sil("User", email))
		return email

	def _store(self, tag: str, user: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_code": f"ONZ{tag}{self.suffix}",
				"seller_name": f"ONZ {tag} {self.suffix}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)  # test kurulumu
		frappe.db.commit()
		self.addCleanup(lambda: _sil("Admin Seller Profile", doc.name))
		return doc.name

	def _asset(self, store: str, slot: str, state: str, source_file: str = "") -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": slot,
				"media_type": "image",
				"state": state,
				"owner_seller": store,
				"content_sha256": frappe.generate_hash(length=64),
				"source_file": source_file or self.file_name,
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)  # test kurulumu
		frappe.db.commit()
		self.addCleanup(lambda: _sil(INTENT, doc.name))
		self.addCleanup(lambda: _sil("Media Asset", doc.name))
		return doc.name

	def setUp(self):
		super().setUp()
		self._orig = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)
		self.owner = self._user("owner")
		self.other = self._user("other")
		self.owner_store = self._store("A", self.owner)
		self.other_store = self._store("B", self.other)
		dosya = frappe.get_doc(
			{"doctype": "File", "file_name": f"onz-{self.suffix}.png", "content": _png(), "is_private": 0}
		).insert(ignore_permissions=True)  # test kurulumu
		frappe.db.set_value("File", dosya.name, {"th_media_width": 2000, "th_media_height": 408})
		frappe.db.commit()
		self.addCleanup(lambda: _sil("File", dosya.name))
		self.file_name = dosya.name
		self.url = dosya.file_url

	# ── hedef seçimi ────────────────────────────────────────────────────

	def test_target_prefers_ready_asset_of_same_slot(self):
		self._asset(self.owner_store, "library.image", "ready")
		self._asset(self.owner_store, SLOT, "archived")
		hazir = self._asset(self.owner_store, SLOT, "ready")
		frappe.set_user(self.owner)
		hedef = media_preview.get_preview_target(file_url=self.url, slot_key=SLOT)
		self.assertEqual(hedef["asset"], hazir)
		self.assertFalse(hedef["processing"])
		self.assertEqual((hedef["source"]["width"], hedef["source"]["height"]), (2000, 408))
		self.assertIsNone(hedef["focal"])

	def test_other_seller_gets_no_asset_and_no_focal(self):
		varlik = self._asset(self.owner_store, SLOT, "ready")
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=varlik, focal_x=0.78, focal_y=0.45)
		frappe.set_user(self.other)
		hedef = media_preview.get_preview_target(file_url=self.url, slot_key=SLOT)
		self.assertEqual(hedef["asset"], "")
		self.assertIsNone(hedef["focal"])

	def test_target_returns_saved_focal(self):
		varlik = self._asset(self.owner_store, SLOT, "ready")
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=varlik, focal_x=0.78, focal_y=0.45)
		hedef = media_preview.get_preview_target(file_url=self.url, slot_key=SLOT)
		self.assertEqual(hedef["focal"], {"x": 0.78, "y": 0.45})

	def _yonlendirme(self, eski: str, yeni: str) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": eski,
				"target_url": yeni,
				"job_key": f"onz-{self.suffix}",
				"expires_at": frappe.utils.add_days(frappe.utils.now_datetime(), 30),
			}
		).insert(ignore_permissions=True)  # test kurulumu
		frappe.db.commit()
		self.addCleanup(lambda: _sil("Media URL Redirect", doc.name))

	def test_converted_old_url_follows_redirect_to_asset(self):
		"""Mağaza görseli WebP'ye çevrilince File satırı yeni adrese taşınır (final review I-5).

		Düzenleyici hâlâ eski adresi tutuyor; uç `Media URL Redirect` ile yeni
		adrese geçip varlığı bulmalı, `file_url` olarak da yeni adresi dönmeli.
		"""
		hazir = self._asset(self.owner_store, SLOT, "ready")
		eski = f"/files/onz-eski-{self.suffix}.png"
		self._yonlendirme(eski, self.url)
		frappe.set_user(self.owner)
		hedef = media_preview.get_preview_target(file_url=eski, slot_key=SLOT)
		self.assertEqual(hedef["asset"], hazir)
		self.assertEqual(hedef["file_url"], self.url)
		self.assertEqual((hedef["source"]["width"], hedef["source"]["height"]), (2000, 408))

	def test_redirect_never_reaches_other_sellers_asset(self):
		self._asset(self.other_store, SLOT, "ready")
		eski = f"/files/onz-eski-b-{self.suffix}.png"
		self._yonlendirme(eski, self.url)
		frappe.set_user(self.owner)
		hedef = media_preview.get_preview_target(file_url=eski, slot_key=SLOT)
		self.assertEqual(hedef["asset"], "")
		self.assertIsNone(hedef["focal"])

	def test_live_url_ignores_redirect_rows(self):
		"""Adresin kendi File satırı varsa yönlendirme izlenmez."""
		hazir = self._asset(self.owner_store, SLOT, "ready")
		self._yonlendirme(self.url, f"/files/onz-baska-{self.suffix}.webp")
		frappe.set_user(self.owner)
		hedef = media_preview.get_preview_target(file_url=self.url, slot_key=SLOT)
		self.assertEqual(hedef["asset"], hazir)
		self.assertEqual(hedef["file_url"], self.url)

	def test_session_user_carries_store_name_for_preview(self):
		"""Önizleme bağlamı satıcının gerçek mağaza adını gösterir (spec §4.2, final review I-2)."""
		from tradehub_core.api.v1.auth import get_session_user

		frappe.set_user(self.owner)
		profil = get_session_user()["user"]["admin_seller_profile"]
		self.assertEqual(profil["name"], self.owner_store)
		self.assertEqual(profil["seller_name"], f"ONZ A {self.suffix}")

	def test_unknown_slot_rejected(self):
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			media_preview.get_preview_target(file_url=self.url, slot_key="user.avatar")

	def test_guest_rejected(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			media_preview.get_preview_target(file_url=self.url, slot_key=SLOT)
		with self.assertRaises(frappe.PermissionError):
			media_preview.get_preview_prefs()

	# ── kaynak künyesi (ölçü + erişim) ──────────────────────────────────

	def _dosya(self, as_user: str, private: int) -> tuple[str, str]:
		"""`as_user` adına yüklenmiş dosya; ölçü kolonları BOŞ (canlıdaki gibi)."""
		frappe.set_user(as_user)
		dosya = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"onz-{private}-{frappe.generate_hash(length=6)}.png",
				"content": _png(),
				"is_private": private,
			}
		).insert(ignore_permissions=True)  # test kurulumu
		frappe.db.commit()
		frappe.set_user("Administrator")
		self.addCleanup(lambda: _sil("File", dosya.name))
		return dosya.name, dosya.file_url

	def test_dimensions_from_image_header_when_stored_zero(self):
		frappe.db.set_value("File", self.file_name, {"th_media_width": 0, "th_media_height": 0})
		frappe.db.commit()
		self._asset(self.owner_store, SLOT, "ready")
		frappe.set_user(self.owner)
		kaynak = media_preview.get_preview_target(file_url=self.url, slot_key=SLOT)["source"]
		self.assertEqual((kaynak["width"], kaynak["height"]), (2000, 408))
		self.assertGreater(kaynak["bytes"], 0)
		self.assertEqual(kaynak["format"], "png")

	def test_own_file_without_asset_gets_metadata(self):
		_, url = self._dosya(self.owner, private=1)
		frappe.set_user(self.owner)
		kaynak = media_preview.get_preview_target(file_url=url, slot_key=SLOT)["source"]
		self.assertEqual((kaynak["width"], kaynak["height"]), (2000, 408))
		self.assertGreater(kaynak["bytes"], 0)

	def test_foreign_or_private_file_gives_no_metadata(self):
		buyer = self._user("buyer", roles=())
		ozel_ad, ozel_url = self._dosya(self.owner, private=1)
		self._asset(self.owner_store, "product.image", "ready", source_file=ozel_ad)
		self._asset(self.owner_store, "product.image", "ready")
		bos_kaynak = {"width": 0, "height": 0, "bytes": 0, "format": ""}
		for kim in (self.other, buyer):
			for url in (ozel_url, self.url):
				frappe.set_user(kim)
				hedef = media_preview.get_preview_target(file_url=url, slot_key="product.image")
				with self.subTest(kim=kim, url=url):
					self.assertEqual(hedef["asset"], "")
					self.assertIsNone(hedef["focal"])
					self.assertEqual(hedef["source"], bos_kaynak)
					self.assertEqual(hedef["square"], {"original": None, "size": 0})
		frappe.set_user(self.owner)
		hedef = media_preview.get_preview_target(file_url=ozel_url, slot_key="product.image")
		self.assertEqual((hedef["source"]["width"], hedef["source"]["height"]), (2000, 408))

	def test_forged_file_row_for_foreign_url_gives_no_metadata(self):
		"""`upload_file(file_url=…)` çağıranın sahip olduğu bir satır açar; künye yine sızmamalı."""
		buyer = self._user("buyer", roles=())
		_, ozel_url = self._dosya(self.owner, private=1)
		bos_kaynak = {"width": 0, "height": 0, "bytes": 0, "format": ""}
		for saldirgan in (self.other, buyer):
			frappe.set_user(saldirgan)
			sahte = frappe.get_doc(
				{"doctype": "File", "file_name": "sahte.png", "file_url": ozel_url, "is_private": 1}
			).insert(ignore_permissions=True)  # test kurulumu: upload_file'ın açtığı satırın eşi
			frappe.db.commit()
			self.addCleanup(lambda ad=sahte.name: _sil("File", ad))
			self.assertEqual(frappe.db.get_value("File", sahte.name, "owner"), saldirgan)
			hedef = media_preview.get_preview_target(file_url=ozel_url, slot_key="product.image")
			with self.subTest(saldirgan=saldirgan):
				self.assertEqual(hedef["asset"], "")
				self.assertEqual(hedef["source"], bos_kaynak)
				self.assertEqual(hedef["square"], {"original": None, "size": 0})
		frappe.set_user(self.owner)
		kaynak = media_preview.get_preview_target(file_url=ozel_url, slot_key=SLOT)["source"]
		self.assertEqual((kaynak["width"], kaynak["height"]), (2000, 408))

	# ── odak okuması ────────────────────────────────────────────────────

	def test_odaklar_latest_wins_and_archived_counts(self):
		eski = self._asset(self.owner_store, SLOT, "ready")
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=eski, focal_x=0.1, focal_y=0.1)
		frappe.set_user("Administrator")
		frappe.db.set_value("Media Asset", eski, "state", "archived", update_modified=False)
		yeni = self._asset(self.owner_store, SLOT, "ready")
		self.assertEqual(
			odak.odaklar([(self.url, self.owner_store)]), {(self.url, self.owner_store): {"x": 0.1, "y": 0.1}}
		)
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=yeni, focal_x=0.78, focal_y=0.45)
		self.assertEqual(
			odak.odaklar([(self.url, self.owner_store)])[(self.url, self.owner_store)], {"x": 0.78, "y": 0.45}
		)

	def test_odaklar_never_crosses_tenants(self):
		varlik = self._asset(self.owner_store, SLOT, "ready")
		frappe.set_user(self.owner)
		media_crop.save_intent(asset=varlik, focal_x=0.78, focal_y=0.45)
		self.assertEqual(odak.odaklar([(self.url, self.other_store)]), {})

	# ── kullanıcı tercihi ───────────────────────────────────────────────

	def test_prefs_default_on_and_per_user(self):
		frappe.set_user(self.owner)
		self.addCleanup(lambda: frappe.defaults.clear_user_default(media_preview.PREF_KEY, self.owner))
		self.assertEqual(media_preview.get_preview_prefs(), {"autoopen": True})
		self.assertEqual(media_preview.set_preview_prefs(autoopen="0"), {"autoopen": False})
		self.assertEqual(media_preview.get_preview_prefs(), {"autoopen": False})
		frappe.set_user(self.other)
		self.assertEqual(media_preview.get_preview_prefs(), {"autoopen": True})
