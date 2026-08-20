# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-042 / INV-08 — `Media Asset.active_version` atomik yazarı + rollback.

Şema göçmüştü (`active_version` kolonu + `Media Version.is_active`) ama YAZAN
üretim kodu yoktu; docstring'deki 3-cümlelik atomik protokol yalnız tasarımdı.
Bu modül o protokolü koda döken `promote_version` / `rollback_version`'ı ve
okuma yolunun (`version_enrichment_for_assets`) `active_version` tercihini test
eder.

Kapsananlar:
  * promote atomik — geçiş sonrası TAM bir aktif ve o da `active_version`
    (`_validate_active_consistency` her adımda geçer).
  * yanlış asset'in sürümü / hazır-olmayan varlık reddedilir.
  * rollback önceki yayına döner, denetim izi bırakır.
  * **Vacuity:** atomiklik bir mid-transaction hatasıyla bozulursa geçiş TAM
    geri alınır (eski sürüm hâlâ yayında). Araya `commit` girse bu test kırmızı
    olur — atomikliğin iddiası buna bağlıdır.
  * okuma yolu `active_version` VARSA onu tercih eder; YOKSA fallback korunur.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_version_promote
"""

from __future__ import annotations

import hashlib
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tradehub_core.doctype.media_version import media_version as mv_mod
from tradehub_core.tradehub_core.doctype.media_version.media_version import (
	ACTION_VERSION_PROMOTE,
	ACTION_VERSION_ROLLBACK,
	promote_version,
	rollback_version,
	version_enrichment_for_assets,
)

SLOT = "product.image"


class _PromoteTestBase(FrappeTestCase):
	"""Ortak fixture: bir `ready` Media Asset + sürüm açma yardımcıları."""

	def _asset(self, *, state: str = "ready", sha: str | None = None) -> str:
		sha = sha or hashlib.sha256(frappe.generate_hash().encode()).hexdigest()[:32]
		varlik = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": SLOT,
				"media_type": "image",
				"state": state,
				"content_sha256": sha,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(self._temizle, varlik.name)
		return varlik.name

	def _surum(self, asset: str, *, etiket: str) -> str:
		"""Zenginleştirmesiz (mock'lu) sürüm — promote testleri künye istemiyor."""
		vhash = hashlib.sha256(f"{asset}|{etiket}".encode()).hexdigest()
		with mock.patch.object(mv_mod.MediaVersion, "_enrich_from_source", lambda self: None):
			doc = frappe.get_doc(
				{
					"doctype": "Media Version",
					"asset": asset,
					"version_hash": vhash,
					"source_hash": hashlib.sha256(etiket.encode()).hexdigest(),
					"policy_snapshot": "{}",
					"engine_version": "pillow-test",
					"is_active": 0,
				}
			).insert(ignore_permissions=True)
		return doc.name

	def _temizle(self, asset: str) -> None:
		frappe.db.delete("Media Version", {"asset": asset})
		frappe.db.set_value("Media Asset", asset, "active_version", None, update_modified=False)
		frappe.delete_doc("Media Asset", asset, ignore_permissions=True, force=True)

	# — küçük okuyucular —

	@staticmethod
	def _active(asset: str) -> str | None:
		return frappe.db.get_value("Media Asset", asset, "active_version")

	@staticmethod
	def _is_active(version: str) -> int:
		return int(frappe.db.get_value("Media Version", version, "is_active") or 0)

	def _assert_tek_aktif(self, asset: str, version: str) -> None:
		"""TAM bir aktif ve o da `active_version`; controller kapısı da geçer."""
		self.assertEqual(self._active(asset), version)
		isaretli = frappe.get_all(
			"Media Version", filters={"asset": asset, "is_active": 1}, pluck="name"
		)
		self.assertEqual(isaretli, [version])
		# Controller'ın kendi tutarlılık kapısı fırlatmamalı.
		frappe.get_doc("Media Version", version)._validate_active_consistency()


class PromoteTests(_PromoteTestBase):
	def test_promote_yayina_alir_ve_tutarli(self):
		"""İlk promote: sürüm yayında, active_version ve is_active hizalı."""
		asset = self._asset()
		v1 = self._surum(asset, etiket="v1")
		self.assertIsNone(self._active(asset))

		adl = promote_version(asset, v1, commit=False)
		self._assert_tek_aktif(asset, v1)
		self.assertTrue(adl, "promote denetim kaydı yazmalı")

	def test_promote_gecis_eski_surumu_korur(self):
		"""İkinci sürüme geçiş TAM bir aktif bırakır; eski sürüm SİLİNMEZ/erişilir."""
		asset = self._asset()
		v1 = self._surum(asset, etiket="v1")
		v2 = self._surum(asset, etiket="v2")
		promote_version(asset, v1, commit=False)

		promote_version(asset, v2, commit=False)
		self._assert_tek_aktif(asset, v2)
		self.assertEqual(self._is_active(v1), 0, "eski sürüm artık aktif değil")
		# Eski sürüm hâlâ erişilebilir (geçiş onu silmez).
		self.assertTrue(frappe.db.exists("Media Version", v1))

	def test_promote_idempotent(self):
		"""Zaten yayındaki sürümü tekrar promote → no-op, sahte kayıt yok."""
		asset = self._asset()
		v1 = self._surum(asset, etiket="v1")
		promote_version(asset, v1, commit=False)

		self.assertIsNone(promote_version(asset, v1, commit=False))
		self._assert_tek_aktif(asset, v1)

	def test_yanlis_asset_surumu_reddedilir(self):
		"""Başka varlığın sürümü bu varlığa yayına alınamaz."""
		a1 = self._asset()
		a2 = self._asset()
		yabanci = self._surum(a2, etiket="yabanci")
		with self.assertRaises(frappe.ValidationError):
			promote_version(a1, yabanci, commit=False)
		self.assertIsNone(self._active(a1))

	def test_hazir_olmayan_varlik_reddedilir(self):
		"""`state != ready` iken sürüm yayına alınamaz."""
		asset = self._asset(state="processing")
		v1 = self._surum(asset, etiket="v1")
		with self.assertRaises(frappe.ValidationError):
			promote_version(asset, v1, commit=False)
		self.assertIsNone(self._active(asset))

	def test_var_olmayan_surum_reddedilir(self):
		asset = self._asset()
		with self.assertRaises(frappe.ValidationError):
			promote_version(asset, "yok-boyle-bir-hash", commit=False)

	def test_tutarsiz_durum_reddedilir(self):
		"""`_validate_active_consistency`'nin dişi var: elle çelişki → throw.

		Bu, tutarlılık kapısının vacuous olmadığının kanıtı — promote'un ona
		güvenmesi, kapının gerçekten çelişkiyi yakalamasına dayanır.
		"""
		asset = self._asset()
		v1 = self._surum(asset, etiket="v1")
		v2 = self._surum(asset, etiket="v2")
		# active_version = v1 ama v2 is_active=1 → çelişki.
		frappe.db.set_value("Media Asset", asset, "active_version", v1, update_modified=False)
		frappe.db.set_value("Media Version", v2, "is_active", 1, update_modified=False)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Media Version", v2)._validate_active_consistency()

	def test_promote_atomik_hata_da_tam_geri_alinir(self):
		"""VACUITY: geçiş ortasında hata → hiçbir yazma kalıcı olmaz.

		Tutarlılık kapısını fırlatacak şekilde bozar, promote'u bir savepoint
		içinde çağırır ve hatadan sonra ESKİ durumun (v1 yayında) bozulmadığını
		doğrular. Eğer `_write_active_version_atomic` araya bir `frappe.db.commit()`
		koysaydı, "eski is_active=0" adımı savepoint dışına kaçar, geri alınamaz
		ve bu test kırmızı olurdu — atomiklik iddiası tam da buna bağlı.
		"""
		asset = self._asset()
		v1 = self._surum(asset, etiket="v1")
		v2 = self._surum(asset, etiket="v2")
		promote_version(asset, v1, commit=False)
		self._assert_tek_aktif(asset, v1)

		with mock.patch.object(mv_mod, "_assert_active_consistent", side_effect=RuntimeError("boom")):
			frappe.db.savepoint("sp_promote_atomik")
			with self.assertRaises(RuntimeError):
				promote_version(asset, v2, commit=False)
			frappe.db.rollback(save_point="sp_promote_atomik")

		# Eski durum bozulmadan yerinde: v1 hâlâ tek aktif.
		self._assert_tek_aktif(asset, v1)
		self.assertEqual(self._is_active(v2), 0)


class RollbackTests(_PromoteTestBase):
	def test_rollback_onceki_surume_doner(self):
		asset = self._asset()
		v1 = self._surum(asset, etiket="v1")
		v2 = self._surum(asset, etiket="v2")
		promote_version(asset, v1, commit=False)
		promote_version(asset, v2, commit=False)
		self._assert_tek_aktif(asset, v2)

		donulen = rollback_version(asset, commit=False)
		self.assertEqual(donulen, v1)
		self._assert_tek_aktif(asset, v1)

	def test_rollback_denetim_izi_birakir(self):
		asset = self._asset()
		v1 = self._surum(asset, etiket="v1")
		v2 = self._surum(asset, etiket="v2")
		promote_version(asset, v1, commit=False)
		promote_version(asset, v2, commit=False)
		rollback_version(asset, commit=False)

		izler = frappe.get_all(
			"Authorization Decision Log",
			filters={"object_doctype": "Media Asset", "object_name": asset},
			fields=["action"],
			order_by="timestamp asc, creation asc",
		)
		eylemler = [i.action for i in izler]
		self.assertEqual(
			eylemler, [ACTION_VERSION_PROMOTE, ACTION_VERSION_PROMOTE, ACTION_VERSION_ROLLBACK]
		)

	def test_rollback_gecmis_yoksa_throw(self):
		asset = self._asset()
		self._surum(asset, etiket="v1")
		with self.assertRaises(frappe.ValidationError):
			rollback_version(asset, commit=False)


class ReadPathActiveVersionTests(_PromoteTestBase):
	def test_active_version_tercih_edilir_en_yeni_maskelemez(self):
		"""active_version VARSA okuma yolu onu döndürür — daha yeni sürüm değil."""
		asset = self._asset()
		v1 = self._surum(asset, etiket="v1")
		self._surum(asset, etiket="v2-daha-yeni")
		# Eski v1'i yayına al; v2 daha yeni ama yayında değil.
		promote_version(asset, v1, commit=False)

		harita = version_enrichment_for_assets([asset])
		self.assertIn(asset, harita)
		# name == version_hash; dönen künye v1'in.
		self.assertEqual(harita[asset]["version_hash"], v1)

	def test_active_version_yoksa_fallback_korunur(self):
		"""active_version BOŞ → geriye uyum: en yeni (is_active/creation) kazanır."""
		asset = self._asset()
		self._surum(asset, etiket="v1")
		v2 = self._surum(asset, etiket="v2")
		self.assertIsNone(self._active(asset))

		harita = version_enrichment_for_assets([asset])
		self.assertEqual(harita[asset]["version_hash"], v2)

	def test_bos_giris(self):
		self.assertEqual(version_enrichment_for_assets([]), {})
