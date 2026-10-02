"""Yetim AVIF görünümü (2026-09-30): önce gör, silme varsayılan kuru koşu."""

from __future__ import annotations

import os
import shutil

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_orphans
from tradehub_core.media import yetim_avif

AKTIF = "a" * 64
ESKI = "b" * 64


class TestYetimAvif(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.varliklar: list[str] = []
		self.addCleanup(self._temizle)

	def _temizle(self):
		frappe.db.rollback()
		for ad in self.varliklar:
			frappe.db.delete("Media Rendition", {"asset": ad})
			frappe.db.delete("Media Asset", {"name": ad})
			kok = frappe.get_site_path("public", "files", "media", ad)
			if os.path.isdir(kok):
				shutil.rmtree(kok)
		for satir in frappe.get_all(
			"Media Rendition",
			filters={"purge_reason": yetim_avif.SILME_NEDENI, "asset": ["in", self.varliklar or ["-"]]},
		):
			frappe.db.delete("Media Rendition", {"name": satir.name})
		frappe.db.commit()
		yetim_avif.invalidate()

	def _varlik(self, durum: str) -> str:
		v = frappe.get_doc(
			{"doctype": "Media Asset", "slot_key": "product.image", "media_type": "image", "state": durum}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Media Asset", v.name, "active_version", AKTIF, update_modified=False)
		self.varliklar.append(v.name)
		return v.name

	def _dosya(self, varlik: str, surum: str, genislik: int, *, defter: bool = True) -> str:
		url = f"/files/media/{varlik}/{surum}/w{genislik}-{genislik}.avif"
		yol = frappe.get_site_path("public", url.lstrip("/"))
		os.makedirs(os.path.dirname(yol), exist_ok=True)
		with open(yol, "wb") as f:
			f.write(b"\x00" * (genislik * 10))
		if defter:
			r = frappe.get_doc(
				{
					"doctype": "Media Rendition",
					"asset": varlik,
					"profile": f"w{genislik}",
					"width": genislik,
					"format": "avif",
					"state": "ready",
					"version_hash": surum,
					"file_url": url,
				}
			)
			r.flags.ignore_links = True
			r.insert(ignore_permissions=True)
		return url

	def _kur(self):
		emekli = self._varlik("archived")
		canli = self._varlik("ready")
		self._dosya(emekli, AKTIF, 96)
		self._dosya(emekli, AKTIF, 192)
		self._dosya(canli, AKTIF, 384)  # aktif sürüm: yetim DEĞİL
		self._dosya(canli, ESKI, 640)  # eski sürüm: yetim
		self._dosya(canli, ESKI, 1920, defter=False)  # defterde yok: yalnız raporlanır
		frappe.db.commit()
		return emekli, canli

	def _grup(self, ozet: dict, ad: str) -> dict | None:
		return next((g for g in ozet["groups"] if g["asset"] == ad), None)

	def test_siniflandirma_ve_gruplama(self):
		emekli, canli = self._kur()
		ozet = yetim_avif.ozet(page_size=100, refresh=True)
		tum = yetim_avif._gruplar(yetim_avif.index(), "")
		g_emekli = next(g for g in tum if g["asset"] == emekli)
		g_canli = next(g for g in tum if g["asset"] == canli)
		self.assertEqual((g_emekli["count"], g_emekli["reasons"]), (2, {"archived_asset": 2}))
		self.assertEqual(g_emekli["bytes"], 960 + 1920)
		self.assertTrue(g_emekli["preview"].endswith("w96-96.avif"))
		self.assertEqual(g_canli["reasons"], {"old_version": 1, "unregistered": 1})
		self.assertNotIn(f"/{AKTIF}/w384-384.avif", " ".join(d["file_url"] for d in g_canli["files"]))
		self.assertGreaterEqual(ozet["total_files"], 4)

	def test_silme_varsayilan_kuru_kosu_hicbir_seye_dokunmaz(self):
		emekli, canli = self._kur()
		out = media_orphans.orphan_avif_delete(assets=[emekli, canli])
		self.assertTrue(out["dry_run"])
		self.assertEqual(out["would_delete_files"], 3)
		self.assertEqual(out["skipped_unregistered"], 1)
		for url in (
			f"/files/media/{emekli}/{AKTIF}/w96-96.avif",
			f"/files/media/{canli}/{ESKI}/w640-640.avif",
		):
			self.assertTrue(os.path.exists(frappe.get_site_path("public", url.lstrip("/"))))
		self.assertFalse(frappe.db.exists("Media Rendition", {"asset": emekli, "state": "purged"}))

	def test_gercek_islem_jeton_ister_ve_copu_kullanir(self):
		emekli, canli = self._kur()
		with self.assertRaises(frappe.ValidationError):
			yetim_avif.sil(assets=[emekli], dry_run=False, confirm_token="yanlis")
		kuru = yetim_avif.sil(assets=[emekli], dry_run=True)
		out = yetim_avif.sil(assets=[emekli], dry_run=False, confirm_token=kuru["confirm_token"])
		self.assertEqual(out["moved_to_trash"], 2, out)
		self.assertFalse(
			os.path.exists(frappe.get_site_path("public", "files", "media", emekli, AKTIF, "w96-96.avif"))
		)
		self.assertEqual(frappe.db.count("Media Rendition", {"asset": emekli, "state": "purged"}), 2)
		# Seçilmeyen varlık ve kayıtsız dosya yerinde.
		self.assertTrue(
			os.path.exists(frappe.get_site_path("public", "files", "media", canli, ESKI, "w1920-1920.avif"))
		)
		for satir in frappe.get_all("Media Rendition", filters={"asset": emekli}, fields=["trash_path"]):
			yol = frappe.get_site_path(satir.trash_path)
			if os.path.exists(yol):
				os.remove(yol)

	def test_yalniz_system_manager(self):
		# `frappe.only_for` test bayrağı açıkken kontrolü atlıyor; gerçek dalı sına.
		frappe.flags.in_test = False
		self.addCleanup(lambda: setattr(frappe.flags, "in_test", True))
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				media_orphans.orphan_avif_overview()
		finally:
			frappe.set_user("Administrator")
