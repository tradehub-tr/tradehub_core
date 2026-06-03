"""Sprint 6 — DB-driven RBAC E2E test paketi.

Test kapsamı:
  A. DocType varlık + seed verisi (Capability Registry/Grant, Module Registry/Policy)
  B. permission_resolver (capability + module mode)
  C. seller_capabilities.has_seller_capability DB-first karar zinciri
  D. permission_console endpoint'leri (list / update / audit)
  E. api/v1/navigation get_navigation endpoint + tree filter
  F. Cache invalidation (doc_events hook'ları)
  G. Güvenlik sınırları (protected capability/module, non-admin reddi)
  H. E2E senaryolar (grant → kullanıcı erişimi, policy → sidebar gizleme)

Çalıştırma:
    docker exec docker-backend-1 bench --site dev.localhost run-tests \\
        --module tradehub_core.tests.test_sprint6_rbac
"""

import unittest

import frappe

# Test sabitleri — bütün testlerde paylaşılır
_TEST_PROFILE = "Seller Finance Staff"
_TEST_CAP = "view.bank_info"
_TEST_USER = "ali.turgut@turksab.com"  # Finance Staff profile'lı sub-user
_OWNER_USER = "bora.aydeger@turksab.com"  # Seller Full Access (Owner)
_TEST_MODULE = "seller.store.profil.magaza"  # Mağaza Ayarları
_PROTECTED_CAP = "bank_info.write"  # is_protected=1
_PROTECTED_MODULE = "seller.dashboard.main.home"  # is_protected=1


# ──────────────────────────────────────────────────────────────────────────
# A) DocType varlık + seed
# ──────────────────────────────────────────────────────────────────────────


class TestSprint6_A_DocTypes(unittest.TestCase):
	"""4 yeni DocType doğru yaratıldı mı + beklenen sayıda seed kayıt var mı."""

	def test_capability_registry_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "TH Capability Registry"))

	def test_capability_grant_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "TH Capability Grant"))

	def test_module_registry_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "TH Module Registry"))

	def test_module_policy_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "TH Module Policy"))

	def test_capability_registry_seed_count(self):
		count = frappe.db.count("TH Capability Registry")
		self.assertGreaterEqual(count, 31, f"En az 31 capability bekleniyor, {count} bulundu")

	def test_capability_grant_seed_count(self):
		count = frappe.db.count("TH Capability Grant", {"granted": 1})
		self.assertGreaterEqual(count, 80, f"En az 80 grant bekleniyor, {count}")

	def test_module_registry_seed_count(self):
		count = frappe.db.count("TH Module Registry", {"is_active": 1})
		self.assertGreaterEqual(count, 50, f"En az 50 modül bekleniyor, {count}")

	def test_module_policy_seed_count(self):
		count = frappe.db.count("TH Module Policy", {"mode": "hidden"})
		self.assertGreaterEqual(count, 200, f"En az 200 hidden policy bekleniyor, {count}")

	def test_protected_owner_only_capabilities_marked(self):
		"""Owner-only 6 capability hepsi is_protected=1 olmalı."""
		protected = frappe.get_all(
			"TH Capability Registry",
			filters={"is_owner_only": 1},
			fields=["name", "is_protected"],
		)
		self.assertEqual(len(protected), 6, "6 owner-only capability bekleniyor")
		for cap in protected:
			self.assertEqual(
				cap["is_protected"],
				1,
				f"Owner-only capability korumalı olmalı: {cap['name']}",
			)

	def test_kyc_required_capabilities_marked(self):
		"""Finance + bank_info için requires_kyc=1."""
		expected = {"order.confirm_payment", "order.refund", "balance.withdraw", "bank_info.write"}
		kyc_caps = frappe.get_all(
			"TH Capability Registry",
			filters={"requires_kyc": 1},
			pluck="name",
		)
		for cap in expected:
			self.assertIn(cap, kyc_caps, f"{cap} requires_kyc=1 olmalı")

	def test_owner_profile_has_all_capabilities(self):
		"""Seller Full Access (Owner) tüm capability'leri grant alır."""
		all_caps = frappe.get_all("TH Capability Registry", filters={"is_active": 1}, pluck="name")
		owner_grants = frappe.get_all(
			"TH Capability Grant",
			filters={"role_profile": "Seller Full Access", "granted": 1},
			pluck="capability",
		)
		missing = set(all_caps) - set(owner_grants)
		self.assertEqual(missing, set(), f"Owner için eksik grant'lar: {missing}")

	def test_module_registry_tree_structure(self):
		"""Section/group/item hiyerarşisi tutarlı: item parent=group, group parent=section."""
		items = frappe.get_all(
			"TH Module Registry",
			filters={"item_type": "item", "panel": "seller"},
			fields=["name", "parent_th_module_registry"],
		)
		for it in items:
			self.assertTrue(
				it["parent_th_module_registry"],
				f"Item parent'ı boş: {it['name']}",
			)
			parent_type = frappe.db.get_value(
				"TH Module Registry", it["parent_th_module_registry"], "item_type"
			)
			self.assertEqual(
				parent_type,
				"group",
				f"{it['name']} parent'ı group olmalı, {parent_type} bulundu",
			)


# ──────────────────────────────────────────────────────────────────────────
# B) permission_resolver
# ──────────────────────────────────────────────────────────────────────────


class TestSprint6_B_Resolver(unittest.TestCase):
	"""permission_resolver fonksiyonları doğru veri döner mi."""

	def setUp(self):
		from tradehub_core.utils.permission_resolver import flush_all_cache, flush_module_cache

		flush_all_cache()
		flush_module_cache()

	def test_get_capabilities_owner_returns_all(self):
		from tradehub_core.utils.permission_resolver import get_capabilities

		caps = get_capabilities(_OWNER_USER)
		self.assertGreaterEqual(len(caps), 30, "Owner en az 30 capability almalı")
		self.assertIn("view.bank_info", caps, "Owner view.bank_info almalı")
		self.assertIn("bank_info.write", caps, "Owner bank_info.write (owner-only) almalı")

	def test_get_capabilities_finance_staff_limited(self):
		"""Finance Staff Operations capability'lerini almamalı."""
		from tradehub_core.utils.permission_resolver import get_capabilities

		caps = get_capabilities(_TEST_USER)
		# Finance Staff Operations capability'sini almaz
		self.assertNotIn("order.ship", caps, "Finance Staff order.ship almamalı")
		self.assertNotIn("view.bank_info", caps, "Finance Staff view.bank_info almamalı (COOWNER tier)")
		# Ama Finance capability'lerini alır
		self.assertIn("order.refund", caps, "Finance Staff order.refund almalı")

	def test_get_capabilities_guest_empty(self):
		from tradehub_core.utils.permission_resolver import get_capabilities

		caps = get_capabilities("Guest")
		self.assertEqual(caps, set(), "Guest boş set almalı")

	def test_get_module_mode_finance_staff_hidden(self):
		from tradehub_core.utils.permission_resolver import get_module_mode

		mode = get_module_mode(_TEST_USER, _TEST_MODULE, panel="seller")
		self.assertEqual(mode, "hidden", "Finance Staff için Mağaza Ayarları hidden olmalı")

	def test_get_module_mode_owner_visible(self):
		from tradehub_core.utils.permission_resolver import get_module_mode

		mode = get_module_mode(_OWNER_USER, _TEST_MODULE, panel="seller")
		self.assertEqual(mode, "visible", "Owner için Mağaza Ayarları visible olmalı")

	def test_get_navigation_tree_owner_full(self):
		from tradehub_core.utils.permission_resolver import get_navigation_tree

		tree = get_navigation_tree(_OWNER_USER, panel="seller")
		section_keys = {s["section_key"] for s in tree}
		# Tüm seller section'ları görünür
		self.assertIn("store", section_keys, "Owner Mağazam görmeli")
		self.assertIn("orders", section_keys, "Owner Siparişler görmeli")

	def test_get_navigation_tree_filters_hidden(self):
		"""Finance Staff için seller.store.profil.magaza tree'de görünmemeli."""
		from tradehub_core.utils.permission_resolver import get_navigation_tree

		tree = get_navigation_tree(_TEST_USER, panel="seller")
		all_keys = []
		for section in tree:
			for group in section.get("children", []):
				for item in group.get("children", []):
					all_keys.append(item["module_key"])
				all_keys.append(group["module_key"])
			all_keys.append(section["module_key"])
		self.assertNotIn(
			_TEST_MODULE,
			all_keys,
			"Hidden modül tree çıktısında olmamalı",
		)


# ──────────────────────────────────────────────────────────────────────────
# C) seller_capabilities.has_seller_capability
# ──────────────────────────────────────────────────────────────────────────


class TestSprint6_C_HasCapability(unittest.TestCase):
	"""DB-first karar zinciri doğrulanır."""

	def setUp(self):
		from tradehub_core.utils.permission_resolver import flush_all_cache

		flush_all_cache()

	def test_owner_gets_all_capabilities(self):
		from tradehub_core.utils.seller_capabilities import has_seller_capability

		self.assertTrue(has_seller_capability("view.bank_info", _OWNER_USER))
		self.assertTrue(has_seller_capability("order.ship", _OWNER_USER))
		self.assertTrue(has_seller_capability("bank_info.write", _OWNER_USER))

	def test_finance_staff_denied_owner_only(self):
		from tradehub_core.utils.seller_capabilities import has_seller_capability

		# Owner-only capability — Owner değilse her zaman False
		self.assertFalse(
			has_seller_capability("bank_info.write", _TEST_USER),
			"Finance Staff owner-only capability alamaz",
		)
		self.assertFalse(
			has_seller_capability("owner.transfer", _TEST_USER),
		)

	def test_finance_staff_tier_match(self):
		from tradehub_core.utils.seller_capabilities import has_seller_capability

		# Finance Staff Finance tier — view.order_amounts almalı
		self.assertTrue(has_seller_capability("view.order_amounts", _TEST_USER))

	def test_finance_staff_no_operations(self):
		from tradehub_core.utils.seller_capabilities import has_seller_capability

		# Finance Staff Operations capability'sini almamalı
		self.assertFalse(has_seller_capability("listing.write", _TEST_USER))
		self.assertFalse(has_seller_capability("order.ship", _TEST_USER))

	def test_undefined_capability_denied(self):
		from tradehub_core.utils.seller_capabilities import has_seller_capability

		self.assertFalse(
			has_seller_capability("nonexistent.capability", _OWNER_USER),
			"Tanımsız capability fail-secure False dönmeli",
		)


# ──────────────────────────────────────────────────────────────────────────
# D) permission_console endpoint'leri
# ──────────────────────────────────────────────────────────────────────────


class TestSprint6_D_Endpoints(unittest.TestCase):
	"""permission_console list/update endpoint'leri."""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")

	def test_list_capabilities_shape(self):
		from tradehub_core.api.v1 import permission_console as pc

		res = pc.list_capabilities()
		self.assertIn("role_profiles", res)
		self.assertIn("capabilities", res)
		self.assertGreaterEqual(len(res["capabilities"]), 31)
		self.assertGreater(len(res["role_profiles"]), 0)
		# Her capability "key" field'ına sahip olmalı (MariaDB alias fix)
		self.assertIn("key", res["capabilities"][0])
		self.assertIn("grants", res["capabilities"][0])

	def test_list_modules_tree_shape(self):
		from tradehub_core.api.v1 import permission_console as pc

		res = pc.list_modules_tree(panel="seller")
		self.assertIn("modules", res)
		self.assertGreaterEqual(len(res["modules"]), 50)
		# Her modül "key" ve "policies" field'ına sahip olmalı
		self.assertIn("key", res["modules"][0])
		self.assertIn("policies", res["modules"][0])

	def test_update_capability_grant_create_then_delete(self):
		from tradehub_core.api.v1 import permission_console as pc

		# Test öncesi temizlik
		existing = frappe.db.get_value(
			"TH Capability Grant",
			{"role_profile": "Seller Operations", "capability": "view.bank_info"},
			"name",
		)
		if existing:
			frappe.delete_doc("TH Capability Grant", existing, ignore_permissions=True, force=1)
			frappe.db.commit()

		# Insert
		r = pc.update_capability_grant(
			role_profile="Seller Operations",
			capability="view.bank_info",
			granted=True,
			note="E2E test",
		)
		self.assertEqual(r["action"], "created")
		frappe.db.commit()

		# Delete
		r = pc.update_capability_grant(
			role_profile="Seller Operations",
			capability="view.bank_info",
			granted=False,
		)
		self.assertEqual(r["action"], "deleted")
		frappe.db.commit()

	def test_update_capability_grant_protected_owner_denied(self):
		"""Korumalı capability Owner profile'ından çekilemez."""
		from tradehub_core.api.v1 import permission_console as pc

		with self.assertRaises(frappe.PermissionError):
			pc.update_capability_grant(
				role_profile="Seller Full Access",
				capability=_PROTECTED_CAP,
				granted=False,
			)

	def test_update_module_policy_cycle(self):
		"""visible (delete) → hidden (insert) → masked (update) → visible (delete)."""
		from tradehub_core.api.v1 import permission_console as pc

		# Önce mevcut policy'yi sil (clean state)
		existing = frappe.db.get_value(
			"TH Module Policy",
			{"module": "seller.store.sertifika", "role_profile": "Seller Operations"},
			"name",
		)
		if existing:
			frappe.delete_doc("TH Module Policy", existing, ignore_permissions=True, force=1)
			frappe.db.commit()

		# visible (kayıt yok) → noop
		r = pc.update_module_policy(
			module="seller.store.sertifika",
			role_profile="Seller Operations",
			mode="visible",
		)
		self.assertEqual(r["action"], "noop")

		# hidden → created
		r = pc.update_module_policy(
			module="seller.store.sertifika",
			role_profile="Seller Operations",
			mode="hidden",
		)
		self.assertEqual(r["action"], "created")
		frappe.db.commit()

		# masked → updated
		r = pc.update_module_policy(
			module="seller.store.sertifika",
			role_profile="Seller Operations",
			mode="masked",
		)
		self.assertEqual(r["action"], "updated")
		frappe.db.commit()

		# visible → reset_to_default
		r = pc.update_module_policy(
			module="seller.store.sertifika",
			role_profile="Seller Operations",
			mode="visible",
		)
		self.assertEqual(r["action"], "reset_to_default")
		frappe.db.commit()

	def test_update_module_policy_protected_hidden_denied(self):
		"""Korumalı modül hidden yapılamaz."""
		from tradehub_core.api.v1 import permission_console as pc

		with self.assertRaises(frappe.PermissionError):
			pc.update_module_policy(
				module=_PROTECTED_MODULE,
				role_profile="Seller Operations",
				mode="hidden",
			)

	def test_update_module_policy_invalid_mode(self):
		from tradehub_core.api.v1 import permission_console as pc

		with self.assertRaises(frappe.ValidationError):
			pc.update_module_policy(
				module=_TEST_MODULE,
				role_profile="Seller Operations",
				mode="invalid_mode",
			)

	def test_list_rbac_audit_returns_recent_changes(self):
		from tradehub_core.api.v1 import permission_console as pc

		res = pc.list_rbac_audit(limit=10)
		self.assertIn("entries", res)
		self.assertIn("count", res)
		self.assertIsInstance(res["entries"], list)
		# Audit log opsiyonel — Version tablosu boş olabilir test ortamında
		for entry in res["entries"]:
			self.assertIn("timestamp", entry)
			self.assertIn("actor", entry)
			self.assertIn("target_doctype", entry)


# ──────────────────────────────────────────────────────────────────────────
# E) api/v1/navigation get_navigation endpoint
# ──────────────────────────────────────────────────────────────────────────


class TestSprint6_E_Navigation(unittest.TestCase):
	"""get_navigation endpoint tree + filter."""

	def test_get_navigation_seller_shape(self):
		from tradehub_core.api.v1.navigation import get_navigation

		frappe.set_user(_OWNER_USER)
		nav = get_navigation(panel="seller")
		self.assertEqual(nav["panel"], "seller")
		self.assertIsInstance(nav["sections"], list)
		self.assertGreater(len(nav["sections"]), 0)

	def test_get_navigation_owner_includes_kyb(self):
		"""Owner için KYB Doğrulama tree'de olmalı."""
		from tradehub_core.api.v1.navigation import get_navigation

		frappe.set_user(_OWNER_USER)
		nav = get_navigation(panel="seller")
		all_routes = []
		for section in nav["sections"]:
			for group in section["items"]:
				for item in group["items"]:
					all_routes.append(item.get("module_key"))
		self.assertIn(
			"seller.store.profil.kyb",
			all_routes,
			"Owner için KYB Doğrulama görünür olmalı",
		)

	def test_get_navigation_finance_staff_excludes_team(self):
		"""Finance Staff için Ekibim tree'de olmamalı."""
		from tradehub_core.api.v1.navigation import get_navigation

		frappe.set_user(_TEST_USER)
		nav = get_navigation(panel="seller")
		all_keys = []
		for section in nav["sections"]:
			all_keys.append(section["module_key"])
			for group in section["items"]:
				all_keys.append(group["module_key"])
				for item in group["items"]:
					all_keys.append(item["module_key"])
		self.assertNotIn(
			"seller.store.ekip.ekibim",
			all_keys,
			"Finance Staff için Ekibim görünmemeli",
		)
		self.assertNotIn(
			"seller.store.profil.kyb",
			all_keys,
			"Finance Staff için KYB görünmemeli",
		)


# ──────────────────────────────────────────────────────────────────────────
# F) Cache invalidation hooks
# ──────────────────────────────────────────────────────────────────────────


class TestSprint6_F_CacheInvalidation(unittest.TestCase):
	"""doc_events hooks Redis cache flush ediyor mu."""

	def setUp(self):
		frappe.set_user("Administrator")
		# Test artıklarını temizle (önceki commit'lerden kalmış olabilir).
		# frappe.db.delete doc_events tetiklemez → resolver cache kirli kalır;
		# explicit flush_all_cache ile fail-safe.
		frappe.db.delete(
			"TH Capability Grant",
			{"role_profile": _TEST_PROFILE, "capability": _TEST_CAP},
		)
		frappe.db.delete(
			"TH Module Policy",
			{
				"module": "seller.store.vitrin.layout",
				"role_profile": _TEST_PROFILE,
			},
		)
		frappe.db.commit()
		from tradehub_core.utils.permission_resolver import flush_all_cache

		flush_all_cache()
		# Module cache farklı key prefix'i — explicit temizlik için
		try:
			frappe.cache().delete_keys("tradehub:mod:user:")
		except Exception:
			pass

	def tearDown(self):
		frappe.db.delete(
			"TH Capability Grant",
			{"role_profile": _TEST_PROFILE, "capability": _TEST_CAP},
		)
		frappe.db.delete(
			"TH Module Policy",
			{
				"module": "seller.store.vitrin.layout",
				"role_profile": _TEST_PROFILE,
			},
		)
		frappe.db.commit()
		from tradehub_core.utils.permission_resolver import flush_all_cache

		flush_all_cache()
		try:
			frappe.cache().delete_keys("tradehub:mod:user:")
		except Exception:
			pass

	def test_grant_insert_flushes_capability_cache(self):
		from tradehub_core.utils.permission_resolver import get_capabilities

		# Önce cache'i doldur
		caps_before = get_capabilities(_TEST_USER)
		self.assertNotIn("view.bank_info", caps_before)

		# Insert grant
		existing = frappe.db.get_value(
			"TH Capability Grant",
			{"role_profile": _TEST_PROFILE, "capability": _TEST_CAP},
			"name",
		)
		if existing:
			frappe.delete_doc("TH Capability Grant", existing, ignore_permissions=True, force=1)

		doc = frappe.new_doc("TH Capability Grant")
		doc.role_profile = _TEST_PROFILE
		doc.capability = _TEST_CAP
		doc.granted = 1
		doc.note = "E2E cache test"
		doc.insert(ignore_permissions=True)
		frappe.db.commit()

		# Cache flush sonrası yeniden çek — grant artık görünmeli
		caps_after = get_capabilities(_TEST_USER)
		self.assertIn(
			"view.bank_info",
			caps_after,
			"Insert sonrası cache flush ile yeni grant görünmeli",
		)

		# Cleanup
		frappe.delete_doc("TH Capability Grant", doc.name, ignore_permissions=True, force=1)
		frappe.db.commit()

	def test_module_policy_insert_flushes_module_cache(self):
		from tradehub_core.utils.permission_resolver import get_module_mode

		# Önce mevcut policy'yi sil
		existing = frappe.db.get_value(
			"TH Module Policy",
			{"module": "seller.store.vitrin.layout", "role_profile": _TEST_PROFILE},
			"name",
		)
		if existing:
			frappe.delete_doc("TH Module Policy", existing, ignore_permissions=True, force=1)
			frappe.db.commit()

		# Cache doldur (varsayılan visible)
		mode_before = get_module_mode(_TEST_USER, "seller.store.vitrin.layout", panel="seller")
		self.assertEqual(mode_before, "visible")

		# Insert hidden policy
		doc = frappe.new_doc("TH Module Policy")
		doc.module = "seller.store.vitrin.layout"
		doc.role_profile = _TEST_PROFILE
		doc.mode = "hidden"
		doc.note = "E2E cache test"
		doc.insert(ignore_permissions=True)
		frappe.db.commit()

		# Cache flush ile yeni mode görünmeli
		mode_after = get_module_mode(_TEST_USER, "seller.store.vitrin.layout", panel="seller")
		self.assertEqual(mode_after, "hidden", "Insert sonrası cache flush ile hidden mode görünmeli")

		# Cleanup
		frappe.delete_doc("TH Module Policy", doc.name, ignore_permissions=True, force=1)
		frappe.db.commit()


# ──────────────────────────────────────────────────────────────────────────
# G) Güvenlik sınırları
# ──────────────────────────────────────────────────────────────────────────


class TestSprint6_G_Security(unittest.TestCase):
	"""Non-admin endpoint reddi + protected kayıt korunumu."""

	def test_non_admin_cannot_list_capabilities(self):
		"""Süper admin olmayan kullanıcı list_capabilities çağıramaz."""
		from tradehub_core.api.v1 import permission_console as pc

		frappe.set_user(_TEST_USER)
		try:
			with self.assertRaises(frappe.PermissionError):
				pc.list_capabilities()
		finally:
			frappe.set_user("Administrator")

	def test_non_admin_cannot_update_grant(self):
		from tradehub_core.api.v1 import permission_console as pc

		frappe.set_user(_TEST_USER)
		try:
			with self.assertRaises(frappe.PermissionError):
				pc.update_capability_grant(
					role_profile="Seller Operations",
					capability="order.ship",
					granted=True,
				)
		finally:
			frappe.set_user("Administrator")

	def test_protected_capability_cannot_be_deleted(self):
		"""is_protected=1 capability silinemez."""
		# Cleanup state
		frappe.set_user("Administrator")
		try:
			# Owner-only protected capability seç
			cap_name = frappe.db.get_value(
				"TH Capability Registry",
				{"is_protected": 1, "is_owner_only": 1},
				"name",
			)
			self.assertIsNotNone(cap_name, "En az 1 korumalı owner-only capability olmalı")

			doc = frappe.get_doc("TH Capability Registry", cap_name)
			with self.assertRaises(frappe.PermissionError):
				doc.delete()
		finally:
			frappe.set_user("Administrator")

	def test_protected_module_cannot_be_deleted(self):
		"""is_protected=1 modül silinemez."""
		frappe.set_user("Administrator")
		try:
			mod_name = frappe.db.get_value(
				"TH Module Registry",
				{"is_protected": 1},
				"name",
			)
			self.assertIsNotNone(mod_name, "En az 1 korumalı modül olmalı")

			doc = frappe.get_doc("TH Module Registry", mod_name)
			with self.assertRaises(frappe.PermissionError):
				doc.delete()
		finally:
			frappe.set_user("Administrator")

	def test_protected_module_cannot_be_hidden_via_policy(self):
		"""Faz F.2 + Faz H.5 — Korumalı modül için `update_module_policy`
		`mode=hidden` ile çağrılırsa engellenmeli (UI'da modal uyarı, backend
		PermissionError). Faz F.2 öncesi `is_protected` seed eksik olduğu için
		bu invariant runtime'da tetiklenemiyordu.
		"""
		from tradehub_core.api.v1 import permission_console as pc

		frappe.set_user("Administrator")
		try:
			mod_name = frappe.db.get_value(
				"TH Module Registry",
				{"is_protected": 1},
				"name",
			)
			self.assertIsNotNone(
				mod_name,
				"Faz F.2 seed sonrası en az 1 protected modül olmalı (v15_6_16)",
			)
			# Korumalı modül için mode=hidden → throw
			with self.assertRaises(frappe.PermissionError):
				pc.update_module_policy(
					module=mod_name,
					role_profile="Seller Operations",
					mode="hidden",
				)
			# Aynı modül için mode=visible/masked → engellenmez (sadece hidden
			# yasaktı). visible 'reset_to_default' veya 'noop' davranır;
			# throw beklemiyoruz.
			result = pc.update_module_policy(
				module=mod_name,
				role_profile="Seller Operations",
				mode="visible",
			)
			self.assertIn(result.get("action"), ("noop", "reset_to_default"))
		finally:
			frappe.set_user("Administrator")

	def test_capability_grant_unique_pair_enforced(self):
		"""Aynı (role_profile, capability) çifti tek kayıt olmalı."""
		# İlk kaydı al
		first = frappe.db.get_value(
			"TH Capability Grant",
			{"role_profile": "Seller Full Access"},
			["name", "role_profile", "capability"],
			as_dict=True,
		)
		self.assertIsNotNone(first)

		# Aynı çifti tekrar yaratmaya çalış
		dup = frappe.new_doc("TH Capability Grant")
		dup.role_profile = first["role_profile"]
		dup.capability = first["capability"]
		dup.granted = 1
		with self.assertRaises((frappe.DuplicateEntryError, frappe.ValidationError)):
			dup.insert(ignore_permissions=True)


# ──────────────────────────────────────────────────────────────────────────
# H) E2E senaryolar
# ──────────────────────────────────────────────────────────────────────────


class TestSprint6_H_Scenarios(unittest.TestCase):
	"""End-to-end iş akışı senaryoları."""

	def setUp(self):
		"""Önceki test artıklarını temizle (commit edilmiş kayıtlar rollback olmaz)."""
		frappe.set_user("Administrator")
		from tradehub_core.utils.permission_resolver import flush_all_cache, flush_module_cache

		# Test'in dokunduğu spesifik kayıtları temizle
		for cap in ("view.bank_info",):
			existing = frappe.db.get_value(
				"TH Capability Grant",
				{"role_profile": _TEST_PROFILE, "capability": cap},
				"name",
			)
			if existing:
				frappe.db.delete("TH Capability Grant", existing)

		for mod_key in (
			"seller.store.vitrin.layout",
			"seller.store.sertifika",
		):
			existing = frappe.db.get_value(
				"TH Module Policy",
				{"module": mod_key, "role_profile": _TEST_PROFILE},
				"name",
			)
			if existing:
				frappe.db.delete("TH Module Policy", existing)

		frappe.db.commit()
		flush_all_cache()
		flush_module_cache()

	def tearDown(self):
		"""Test sonrası kalan kayıtları kesin sil — bir sonraki run temiz başlasın."""
		frappe.set_user("Administrator")
		for cap in ("view.bank_info",):
			frappe.db.delete(
				"TH Capability Grant",
				{"role_profile": _TEST_PROFILE, "capability": cap},
			)
		for mod_key in (
			"seller.store.vitrin.layout",
			"seller.store.sertifika",
		):
			frappe.db.delete(
				"TH Module Policy",
				{"module": mod_key, "role_profile": _TEST_PROFILE},
			)
		frappe.db.commit()

	def test_e2e_grant_then_user_can_access(self):
		"""
		Senaryo:
		  1. Süper admin Finance Staff'a view.bank_info grant ediyor
		  2. resolver.has_capability = True (DB-first; F1 ile aynı pattern)
		  3. Cleanup: grant sil → False
		"""
		from tradehub_core.api.v1 import permission_console as pc
		from tradehub_core.utils.permission_resolver import flush_all_cache, has_capability

		# Baseline
		before = has_capability(_TEST_USER, "view.bank_info")
		self.assertFalse(before, "Baseline: Finance Staff view.bank_info almaz")

		# Grant
		r = pc.update_capability_grant(
			role_profile=_TEST_PROFILE,
			capability="view.bank_info",
			granted=True,
			note="E2E senaryo",
		)
		self.assertEqual(r["action"], "created")
		flush_all_cache()

		after = has_capability(_TEST_USER, "view.bank_info")
		self.assertTrue(after, "Grant sonrası Finance Staff view.bank_info almalı")

		# Geri al
		r = pc.update_capability_grant(
			role_profile=_TEST_PROFILE,
			capability="view.bank_info",
			granted=False,
		)
		self.assertEqual(r["action"], "deleted")
		flush_all_cache()

		final = has_capability(_TEST_USER, "view.bank_info")
		self.assertFalse(final, "Delete sonrası tekrar False olmalı")

	def test_e2e_module_policy_then_sidebar_filtered(self):
		"""
		Senaryo:
		  1. Süper admin Finance Staff için seller.store.vitrin.layout'u hidden yapıyor
		  2. get_navigation Finance Staff için bu item'ı dönmemeli
		  3. Cleanup: policy sil → tekrar visible
		"""
		from tradehub_core.api.v1 import permission_console as pc
		from tradehub_core.api.v1.navigation import get_navigation

		frappe.set_user("Administrator")

		# Cleanup
		existing = frappe.db.get_value(
			"TH Module Policy",
			{"module": "seller.store.vitrin.layout", "role_profile": _TEST_PROFILE},
			"name",
		)
		if existing:
			frappe.delete_doc("TH Module Policy", existing, ignore_permissions=True, force=1)
			frappe.db.commit()

		def get_visible_items(user):
			frappe.set_user(user)
			nav = get_navigation(panel="seller")
			keys = []
			for section in nav["sections"]:
				for group in section["items"]:
					for item in group["items"]:
						keys.append(item["module_key"])
			frappe.set_user("Administrator")
			return keys

		# Baseline: layout görünür
		before = get_visible_items(_TEST_USER)
		self.assertIn("seller.store.vitrin.layout", before)

		# Hidden policy ekle
		r = pc.update_module_policy(
			module="seller.store.vitrin.layout",
			role_profile=_TEST_PROFILE,
			mode="hidden",
			note="E2E senaryo",
		)
		self.assertEqual(r["action"], "created")
		frappe.db.commit()

		# Etki: artık görünmemeli
		after = get_visible_items(_TEST_USER)
		self.assertNotIn(
			"seller.store.vitrin.layout",
			after,
			"Hidden policy sonrası sidebar'dan kalkmalı",
		)

		# Cleanup
		r = pc.update_module_policy(
			module="seller.store.vitrin.layout",
			role_profile=_TEST_PROFILE,
			mode="visible",
		)
		self.assertEqual(r["action"], "reset_to_default")
		frappe.db.commit()

		final = get_visible_items(_TEST_USER)
		self.assertIn("seller.store.vitrin.layout", final)

	def test_e2e_session_user_payload_includes_capabilities(self):
		"""
		Senaryo: get_session_user payload'ı `capabilities` listesi içeriyor mu.
		"""
		from tradehub_core.api.v1.auth import get_session_user

		frappe.set_user(_OWNER_USER)
		try:
			res = get_session_user()
			self.assertTrue(res.get("logged_in"))
			user_data = res.get("user", {})
			self.assertIn("capabilities", user_data, "Payload'da capabilities listesi olmalı")
			caps = user_data["capabilities"]
			self.assertIsInstance(caps, list)
			self.assertGreater(len(caps), 0, "Owner en az 1 capability almalı")
			self.assertIn("view.bank_info", caps)
		finally:
			frappe.set_user("Administrator")


# ──────────────────────────────────────────────────────────────────────────
# I) Sprint 4 — Field mask pattern testleri
# ──────────────────────────────────────────────────────────────────────────


class TestSprint4_I_MaskPatterns(unittest.TestCase):
	"""apply_field_mask pattern davranışları."""

	def test_none_pattern_returns_null(self):
		from tradehub_core.utils.permission_resolver import apply_field_mask

		self.assertIsNone(apply_field_mask("anything", "none"))

	def test_last4_keeps_last_four(self):
		from tradehub_core.utils.permission_resolver import apply_field_mask

		self.assertEqual(apply_field_mask("12345678", "last4"), "••••5678")
		self.assertEqual(apply_field_mask("ABCD", "last4"), "••••")
		self.assertEqual(apply_field_mask("AB", "last4"), "••")

	def test_initials_keeps_first_letter(self):
		from tradehub_core.utils.permission_resolver import apply_field_mask

		self.assertEqual(apply_field_mask("Ali Yılmaz", "initials"), "A••• Y•••")
		self.assertEqual(apply_field_mask("Mehmet Can Demir", "initials"), "M••• C••• D•••")
		self.assertEqual(apply_field_mask("Ali", "initials"), "A•••")

	def test_iban_xxx_last4_pattern(self):
		from tradehub_core.utils.permission_resolver import apply_field_mask

		out = apply_field_mask("TR74 1111 2222 3333 4444 1923", "iban_xxx_last4")
		# İlk 2 (TR) + maskelenmiş orta + son 4 (1923), 4'lü gruplara bölünmüş
		self.assertTrue(out.startswith("TR"))
		self.assertTrue(out.endswith("1923"))
		self.assertIn("••", out)

	def test_bullets_full_mask(self):
		from tradehub_core.utils.permission_resolver import apply_field_mask

		self.assertEqual(apply_field_mask("secret", "bullets"), "••••••")

	def test_email_domain_keeps_domain(self):
		from tradehub_core.utils.permission_resolver import apply_field_mask

		self.assertEqual(
			apply_field_mask("ali.yilmaz@example.com", "email_domain"),
			"a•••@example.com",
		)
		# Email değil → fail-safe full bullet
		out = apply_field_mask("notanemail", "email_domain")
		self.assertEqual(out, "•" * len("notanemail"))

	def test_unknown_pattern_returns_none(self):
		from tradehub_core.utils.permission_resolver import apply_field_mask

		self.assertIsNone(apply_field_mask("anything", "unknown_pattern"))

	def test_empty_value_returned_as_is(self):
		from tradehub_core.utils.permission_resolver import apply_field_mask

		self.assertEqual(apply_field_mask("", "last4"), "")
		self.assertIsNone(apply_field_mask(None, "last4"))


# ──────────────────────────────────────────────────────────────────────────
# J) Sprint 4 — view.tax_id capability + Capability matrix update
# ──────────────────────────────────────────────────────────────────────────


class TestSprint4_J_ViewTaxIdCapability(unittest.TestCase):
	"""view.tax_id capability seed ve grant doğrulaması."""

	def test_capability_exists_in_registry(self):
		self.assertTrue(
			frappe.db.exists("TH Capability Registry", "view.tax_id"),
			"view.tax_id Registry'de olmalı",
		)

	def test_owner_has_grant(self):
		self.assertTrue(
			frappe.db.exists(
				"TH Capability Grant",
				{"role_profile": "Seller Full Access", "capability": "view.tax_id"},
			)
		)

	def test_coowner_has_grant(self):
		self.assertTrue(
			frappe.db.exists(
				"TH Capability Grant",
				{"role_profile": "Seller Co-Owner", "capability": "view.tax_id"},
			)
		)

	def test_manager_does_not_have_grant(self):
		"""Manager varsayılan olarak view.tax_id almaz (COOWNER tier)."""
		exists = frappe.db.exists(
			"TH Capability Grant",
			{"role_profile": "Seller Manager", "capability": "view.tax_id"},
		)
		self.assertFalse(exists, "Manager için view.tax_id default'ta verilmez")


# ──────────────────────────────────────────────────────────────────────────
# K) Sprint 5 — view.customer_pii capability + CRM maskeleme
# ──────────────────────────────────────────────────────────────────────────


class TestSprint5_K_CustomerPIICapability(unittest.TestCase):
	"""view.customer_pii Registry seed + grant matrisi."""

	def test_capability_exists(self):
		self.assertTrue(frappe.db.exists("TH Capability Registry", "view.customer_pii"))

	def test_owner_has_grant(self):
		self.assertTrue(
			frappe.db.exists(
				"TH Capability Grant",
				{
					"role_profile": "Seller Full Access",
					"capability": "view.customer_pii",
				},
			)
		)

	def test_finance_staff_no_grant(self):
		"""Finance Staff default'ta view.customer_pii almaz."""
		exists = frappe.db.exists(
			"TH Capability Grant",
			{
				"role_profile": "Seller Finance Staff",
				"capability": "view.customer_pii",
			},
		)
		self.assertFalse(exists, "Finance Staff için seed grant yok")


class TestSprint5_L_ContactPIIMaskingHandler(unittest.TestCase):
	"""crm_masking.mask_pii_fields handler davranışı."""

	def setUp(self):
		frappe.set_user("Administrator")

	def test_handler_bypasses_administrator(self):
		from unittest.mock import MagicMock

		from tradehub_core.api.v1.crm_masking import mask_pii_fields

		doc = MagicMock()
		doc.doctype = "Contact"
		doc.get.side_effect = lambda key: {"owner": "someone@x.com"}.get(key)

		frappe.set_user("Administrator")
		mask_pii_fields(doc)
		# Administrator → bypass → set() çağrılmamalı
		doc.set.assert_not_called()

	def test_handler_bypasses_owner(self):
		"""Kayıt sahibi PII'yi açık görür."""
		from unittest.mock import MagicMock

		from tradehub_core.api.v1.crm_masking import mask_pii_fields

		doc = MagicMock()
		doc.doctype = "Contact"
		doc.get.side_effect = lambda key: {
			"owner": _TEST_USER,
			"email_id": "test@example.com",
			"phone": "5551234567",
			"mobile_no": "5559876543",
			"email_ids": [],
			"phone_nos": [],
		}.get(key)

		frappe.set_user(_TEST_USER)
		try:
			mask_pii_fields(doc)
			doc.set.assert_not_called()
		finally:
			frappe.set_user("Administrator")

	def test_handler_masks_non_owner_without_capability(self):
		"""Owner olmayan + view.customer_pii yok → flat fields maskelenir."""
		from unittest.mock import MagicMock

		from tradehub_core.api.v1.crm_masking import mask_pii_fields

		doc = MagicMock()
		doc.doctype = "Contact"
		# Mock setup — sahip farklı kullanıcı
		doc.get.side_effect = lambda key: {
			"owner": "different@user.com",
			"email_id": "secret@example.com",
			"phone": "5551234567",
			"mobile_no": "5559876543",
			"email_ids": [],
			"phone_nos": [],
		}.get(key)

		# ali.turgut Finance Staff (view.customer_pii yok)
		frappe.set_user(_TEST_USER)
		try:
			mask_pii_fields(doc)
			# email_id, phone, mobile_no için doc.set çağrılmalı
			set_calls = [c.args[0] for c in doc.set.call_args_list]
			self.assertIn("email_id", set_calls)
			self.assertIn("phone", set_calls)
			self.assertIn("mobile_no", set_calls)
		finally:
			frappe.set_user("Administrator")

	def test_handler_skips_unknown_doctype(self):
		"""_PII_FIELDS_BY_DOCTYPE'da olmayan DocType'lar maskelenmez."""
		from unittest.mock import MagicMock

		from tradehub_core.api.v1.crm_masking import mask_pii_fields

		doc = MagicMock()
		doc.doctype = "Some Random DocType"
		doc.get.side_effect = lambda key: {"owner": "x@y.com"}.get(key)

		frappe.set_user(_TEST_USER)
		try:
			mask_pii_fields(doc)
			doc.set.assert_not_called()
		finally:
			frappe.set_user("Administrator")


# ──────────────────────────────────────────────────────────────────────────
# M) Sprint 5 — Admin Seller Profile / User Profile per-field maskeleme
# ──────────────────────────────────────────────────────────────────────────


class TestSprint5_M_PerFieldMasking(unittest.TestCase):
	"""Per-field capability — aynı kayıtta iban maskeli, tax_id açık olabilir."""

	def setUp(self):
		frappe.set_user("Administrator")

	def test_admin_seller_profile_in_pii_map(self):
		"""Admin Seller Profile + User Profile maskeleme spec'e dahil mi."""
		from tradehub_core.api.v1.crm_masking import _PII_FIELDS_BY_DOCTYPE

		self.assertIn("Admin Seller Profile", _PII_FIELDS_BY_DOCTYPE)
		self.assertIn("User Profile", _PII_FIELDS_BY_DOCTYPE)

	def test_admin_seller_profile_iban_pattern_is_iban_xxx_last4(self):
		from tradehub_core.api.v1.crm_masking import _PII_FIELDS_BY_DOCTYPE

		fields = dict((f[0], f[1:]) for f in _PII_FIELDS_BY_DOCTYPE["Admin Seller Profile"])
		self.assertEqual(fields["iban"][0], "iban_xxx_last4")
		self.assertEqual(fields["iban"][2], "view.bank_info")
		self.assertEqual(fields["tax_id"][2], "view.tax_id")

	def test_per_field_capability_isolation(self):
		"""view.bank_info açık + view.tax_id kapalı → iban açık, tax_id maskeli."""
		from unittest.mock import MagicMock

		from tradehub_core.api.v1.crm_masking import mask_pii_fields

		# Bora.aydeger Owner — kayıt sahibi DEĞİL ama Owner her capability'i alır
		# Bu test için non-owner + farklı user gerekli. Mock'la kontrol ediyoruz.
		doc = MagicMock()
		doc.doctype = "Admin Seller Profile"
		doc.get.side_effect = lambda key: {
			"user": "different@user.com",
			"owner": "different@user.com",
			"iban": "TR74 1111 2222 3333 4444 1923",
			"bank_name": "Test Bank",
			"account_holder": "Ali Yılmaz",
			"tax_id": "12345678901",
		}.get(key)
		doc.flags = MagicMock()

		frappe.set_user(_TEST_USER)  # Finance Staff — view.bank_info ve view.tax_id YOK
		try:
			mask_pii_fields(doc)
			# Her 4 alan da maskelenmeli
			set_calls = [c.args[0] for c in doc.set.call_args_list]
			self.assertIn("iban", set_calls)
			self.assertIn("bank_name", set_calls)
			self.assertIn("account_holder", set_calls)
			self.assertIn("tax_id", set_calls)
		finally:
			frappe.set_user("Administrator")

	def test_user_profile_owner_bypass_uses_user_field(self):
		"""User Profile için sahip kontrolü `user` field'ına göre yapılır."""
		from unittest.mock import MagicMock

		from tradehub_core.api.v1.crm_masking import _is_record_owner

		doc = MagicMock()
		doc.doctype = "User Profile"
		doc.get.side_effect = lambda key: {"user": _TEST_USER, "owner": "someone@x.com"}.get(key)

		# user == session.user → True
		self.assertTrue(_is_record_owner(doc, _TEST_USER))
		# user != session.user → False
		self.assertFalse(_is_record_owner(doc, "different@user.com"))

	def test_masked_fields_flag_populated(self):
		"""Maskeli alanlar doc.flags._masked_fields'a yazılır."""
		from unittest.mock import MagicMock

		from tradehub_core.api.v1.crm_masking import mask_pii_fields

		doc = MagicMock()
		doc.doctype = "Admin Seller Profile"
		doc.get.side_effect = lambda key: {
			"user": "x@y.com",
			"iban": "TR74 1111 2222 1923",
			"bank_name": "X Bank",
			"account_holder": "A Y",
			"tax_id": "1234567890",
		}.get(key)
		doc.flags = MagicMock()
		doc.flags._masked_fields = []

		frappe.set_user(_TEST_USER)
		try:
			mask_pii_fields(doc)
			# doc.flags._masked_fields'a 4 field yazılmalı (atom set_attr)
			# MagicMock attribute assign'ı kayıtlanır
			# _masked_fields set edildi mi
			self.assertEqual(doc.flags._masked_fields, ["iban", "bank_name", "account_holder", "tax_id"])
		finally:
			frappe.set_user("Administrator")


# ──────────────────────────────────────────────────────────────────────────
# N) Sprint 5 — Plan kapısı sync endpoint
# ──────────────────────────────────────────────────────────────────────────


class TestSprint5_N_PlanCapabilitySync(unittest.TestCase):
	"""list_plan_capability_sync endpoint shape ve mantığı."""

	def setUp(self):
		frappe.set_user("Administrator")

	def test_endpoint_returns_correct_shape(self):
		from tradehub_core.api.v1 import permission_console as pc

		res = pc.list_plan_capability_sync()
		self.assertIn("plans", res)
		self.assertIn("capabilities", res)
		self.assertIn("stats", res)
		self.assertIn("total_plan_gated", res["stats"])
		self.assertIn("unsynced_count", res["stats"])
		self.assertIn("fully_synced_count", res["stats"])

	def test_only_plan_gated_capabilities_listed(self):
		"""plan_feature_flag boş olan capability'ler listeye girmez."""
		from tradehub_core.api.v1 import permission_console as pc

		res = pc.list_plan_capability_sync()
		for cap in res["capabilities"]:
			self.assertTrue(
				cap.get("plan_feature_flag"),
				f"plan_feature_flag boş olan capability döndü: {cap['key']}",
			)

	def test_rfq_quote_in_results(self):
		"""rfq.quote seed capability'sinin plan sync sonuçlarında olması."""
		from tradehub_core.api.v1 import permission_console as pc

		res = pc.list_plan_capability_sync()
		keys = [c["key"] for c in res["capabilities"]]
		self.assertIn("rfq.quote", keys)

	def test_unsynced_flag_when_no_plan_has_feature(self):
		"""Hiçbir plan'da olmayan feature için is_unsynced=True."""
		from tradehub_core.api.v1 import permission_console as pc

		res = pc.list_plan_capability_sync()
		for cap in res["capabilities"]:
			if not cap["plans_enabled"]:
				self.assertTrue(cap["is_unsynced"])
				self.assertFalse(cap["is_consistent"])
			else:
				self.assertFalse(cap["is_unsynced"])
				self.assertTrue(cap["is_consistent"])

	def test_plan_status_has_all_plans(self):
		"""plan_status dict her plan code'u içerir."""
		from tradehub_core.api.v1 import permission_console as pc

		res = pc.list_plan_capability_sync()
		plans = set(res["plans"])
		for cap in res["capabilities"]:
			self.assertEqual(set(cap["plan_status"].keys()), plans)

	def test_non_admin_rejected(self):
		from tradehub_core.api.v1 import permission_console as pc

		frappe.set_user(_TEST_USER)
		try:
			with self.assertRaises(frappe.PermissionError):
				pc.list_plan_capability_sync()
		finally:
			frappe.set_user("Administrator")


# ──────────────────────────────────────────────────────────────────────────
# O) Sprint 5 — update_plan_capability_flag endpoint
# ──────────────────────────────────────────────────────────────────────────


class TestSprint5_O_UpdatePlanCapabilityFlag(unittest.TestCase):
	"""Subscription Plan capability_flags güncelleme.

	Note: Subscription Plan controller capability_flags key'lerinin
	Feature Catalog'ta tanımlı olmasını şart koşar. setUp test flag'i
	geçici olarak Feature Catalog'a ekler, tearDown siler.
	"""

	_TEST_PLAN = "PRO"
	_TEST_FLAG = "feature.sprint5_e2e_test_flag"

	def setUp(self):
		"""Clean state — Feature Catalog'a test flag + plan'lardan flag temizle."""
		frappe.set_user("Administrator")
		self._ensure_feature_catalog()
		self._reset_flag()

	def tearDown(self):
		"""Plan'lardan + Feature Catalog'dan test flag'i temizle."""
		self._reset_flag()
		self._remove_feature_catalog()

	def _ensure_feature_catalog(self):
		"""Feature Catalog DocType yoksa test'i skip et; varsa entry ekle."""
		if not frappe.db.exists("DocType", "Feature Catalog"):
			self.skipTest("Feature Catalog DocType yok")
		# Feature Catalog autoname=field:feature_key → name == feature_key
		if not frappe.db.exists("Feature Catalog", self._TEST_FLAG):
			doc = frappe.new_doc("Feature Catalog")
			doc.feature_key = self._TEST_FLAG
			doc.display_name = "E2E Test Feature"
			doc.category = "FunctionalFeatures"
			doc.feature_type = "Capability"
			doc.flags.ignore_permissions = True
			doc.flags.ignore_mandatory = True
			doc.insert(ignore_permissions=True)
			frappe.db.commit()

	def _remove_feature_catalog(self):
		if frappe.db.exists("Feature Catalog", self._TEST_FLAG):
			frappe.delete_doc(
				"Feature Catalog",
				self._TEST_FLAG,
				ignore_permissions=True,
				force=1,
			)
			frappe.db.commit()

	def _reset_flag(self):
		if not frappe.db.exists("Subscription Plan", self._TEST_PLAN):
			return
		import json

		plan = frappe.get_doc("Subscription Plan", self._TEST_PLAN)
		raw = plan.capability_flags or "{}"
		try:
			flags = json.loads(raw) if isinstance(raw, str) else (raw or {})
		except (ValueError, TypeError):
			flags = {}
		if self._TEST_FLAG in flags:
			del flags[self._TEST_FLAG]
			plan.capability_flags = json.dumps(flags, sort_keys=True)
			plan.flags.ignore_permissions = True
			plan.save(ignore_permissions=True)
			frappe.db.commit()

	def test_enable_flag_in_single_plan(self):
		"""Tekil plan'a flag ekleme."""
		import json

		from tradehub_core.api.v1 import permission_console as pc

		r = pc.update_plan_capability_flag(
			plan_codes=self._TEST_PLAN,
			feature_flag=self._TEST_FLAG,
			enabled=True,
		)
		self.assertEqual(r["updated"], [self._TEST_PLAN])
		self.assertTrue(r["enabled"])

		# DB'de doğrula
		raw = frappe.db.get_value("Subscription Plan", self._TEST_PLAN, "capability_flags")
		flags = json.loads(raw)
		self.assertTrue(flags.get(self._TEST_FLAG))

	def test_disable_flag(self):
		"""Mevcut flag'i False'a çek."""
		import json

		from tradehub_core.api.v1 import permission_console as pc

		# Önce ekle
		pc.update_plan_capability_flag(
			plan_codes=self._TEST_PLAN,
			feature_flag=self._TEST_FLAG,
			enabled=True,
		)
		# Sonra disable
		r = pc.update_plan_capability_flag(
			plan_codes=self._TEST_PLAN,
			feature_flag=self._TEST_FLAG,
			enabled=False,
		)
		self.assertEqual(r["updated"], [self._TEST_PLAN])
		self.assertFalse(r["enabled"])

		raw = frappe.db.get_value("Subscription Plan", self._TEST_PLAN, "capability_flags")
		flags = json.loads(raw)
		# Flag silinmez, False set edilir
		self.assertIn(self._TEST_FLAG, flags)
		self.assertFalse(flags[self._TEST_FLAG])

	def test_bulk_update_via_json_array(self):
		"""JSON array string ile birden çok plan."""
		import json

		from tradehub_core.api.v1 import permission_console as pc

		# FREE ve STARTER mevcut olmalı (seed'den)
		test_plans = ["FREE", "STARTER"]
		# Sadece var olanları al
		plans = [p for p in test_plans if frappe.db.exists("Subscription Plan", p)]
		if len(plans) < 2:
			self.skipTest("FREE/STARTER plan seed yok")

		try:
			r = pc.update_plan_capability_flag(
				plan_codes=json.dumps(plans),
				feature_flag=self._TEST_FLAG,
				enabled=True,
			)
			self.assertEqual(set(r["updated"]), set(plans))

			# Her plan'da flag True olmalı
			for p in plans:
				raw = frappe.db.get_value("Subscription Plan", p, "capability_flags")
				flags = json.loads(raw or "{}")
				self.assertTrue(flags.get(self._TEST_FLAG), f"{p} planında flag false")
		finally:
			# Cleanup — tearDown sadece _TEST_PLAN'ı temizler, diğerleri için manuel
			for p in plans:
				if p == self._TEST_PLAN:
					continue
				plan = frappe.get_doc("Subscription Plan", p)
				flags = json.loads(plan.capability_flags or "{}")
				if self._TEST_FLAG in flags:
					del flags[self._TEST_FLAG]
					plan.capability_flags = json.dumps(flags, sort_keys=True)
					plan.flags.ignore_permissions = True
					plan.save(ignore_permissions=True)
			frappe.db.commit()

	def test_missing_plan_reported(self):
		"""Var olmayan plan_code 'missing' listesine girer."""
		from tradehub_core.api.v1 import permission_console as pc

		r = pc.update_plan_capability_flag(
			plan_codes="NON_EXISTENT_PLAN_XYZ",
			feature_flag=self._TEST_FLAG,
			enabled=True,
		)
		self.assertEqual(r["updated"], [])
		self.assertIn("NON_EXISTENT_PLAN_XYZ", r["missing"])

	def test_empty_feature_flag_rejected(self):
		from tradehub_core.api.v1 import permission_console as pc

		with self.assertRaises(frappe.ValidationError):
			pc.update_plan_capability_flag(
				plan_codes=self._TEST_PLAN,
				feature_flag="",
				enabled=True,
			)

	def test_non_admin_rejected(self):
		from tradehub_core.api.v1 import permission_console as pc

		frappe.set_user(_TEST_USER)
		try:
			with self.assertRaises(frappe.PermissionError):
				pc.update_plan_capability_flag(
					plan_codes=self._TEST_PLAN,
					feature_flag=self._TEST_FLAG,
					enabled=True,
				)
		finally:
			frappe.set_user("Administrator")


# ──────────────────────────────────────────────────────────────────────────
# P) Sprint 5 — Mask audit event (rate-limited log_decision)
# ──────────────────────────────────────────────────────────────────────────


class TestSprint5_P_MaskAuditLog(unittest.TestCase):
	"""crm_masking._maybe_log_mask_event rate-limited davranışı."""

	def setUp(self):
		frappe.set_user("Administrator")
		# Test öncesi cache temizle
		try:
			frappe.cache().delete_value(f"pii_mask_log:{_TEST_USER}:Contact")
		except Exception:
			pass

	def tearDown(self):
		try:
			frappe.cache().delete_value(f"pii_mask_log:{_TEST_USER}:Contact")
		except Exception:
			pass
		frappe.set_user("Administrator")

	def test_first_call_writes_log(self):
		"""İlk maskeleme olayında ADL'e log yazılır."""
		from unittest.mock import MagicMock

		from tradehub_core.api.v1.crm_masking import _maybe_log_mask_event

		# Mevcut ADL kayıt sayısını al
		before = frappe.db.count(
			"Authorization Decision Log",
			{"action": "pii.field_masked", "actor": _TEST_USER},
		)

		doc = MagicMock()
		doc.doctype = "Contact"
		doc.get.side_effect = lambda key: {"name": "test_contact_001"}.get(key)

		_maybe_log_mask_event(doc, ["email_id", "phone"], _TEST_USER)
		frappe.db.commit()

		after = frappe.db.count(
			"Authorization Decision Log",
			{"action": "pii.field_masked", "actor": _TEST_USER},
		)
		self.assertEqual(after, before + 1, "Bir adet log kaydı eklenmeli")

	def test_rate_limit_skips_when_cache_key_set(self):
		"""Cache'te rate limit key'i set ise log atılmaz (deterministik test)."""
		from unittest.mock import MagicMock

		from tradehub_core.api.v1.crm_masking import _maybe_log_mask_event

		# Manuel olarak cache key'i set et — simüle önceki çağrı
		cache_key = f"pii_mask_log:{_TEST_USER}:Contact"
		frappe.cache().set_value(cache_key, 1, expires_in_sec=3600)

		before = frappe.db.count(
			"Authorization Decision Log",
			{"action": "pii.field_masked", "actor": _TEST_USER},
		)

		doc = MagicMock()
		doc.doctype = "Contact"
		doc.get.side_effect = lambda key: {"name": "test_contact_skip"}.get(key)

		_maybe_log_mask_event(doc, ["email_id", "phone"], _TEST_USER)
		frappe.db.commit()

		after = frappe.db.count(
			"Authorization Decision Log",
			{"action": "pii.field_masked", "actor": _TEST_USER},
		)
		self.assertEqual(after, before, "Rate limit aktif iken log atılmamalı")


class TestSprint5_P2_AuditEndpointIncludesMaskEvents(unittest.TestCase):
	"""list_rbac_audit endpoint'i FieldMask source'unu içerir mi."""

	def setUp(self):
		frappe.set_user("Administrator")
		try:
			frappe.cache().delete_value(f"pii_mask_log:{_TEST_USER}:Contact")
		except Exception:
			pass

	def tearDown(self):
		try:
			frappe.cache().delete_value(f"pii_mask_log:{_TEST_USER}:Contact")
		except Exception:
			pass
		frappe.set_user("Administrator")

	def test_endpoint_returns_field_mask_entries(self):
		"""Bir maskeleme olayı yazıldıktan sonra list_rbac_audit FieldMask döner."""
		from unittest.mock import MagicMock

		from tradehub_core.api.v1 import permission_console as pc
		from tradehub_core.api.v1.crm_masking import _maybe_log_mask_event

		doc = MagicMock()
		doc.doctype = "Contact"
		doc.get.side_effect = lambda key: {"name": "test_contact_audit"}.get(key)

		_maybe_log_mask_event(doc, ["email_id", "phone"], _TEST_USER)
		frappe.db.commit()

		audit = pc.list_rbac_audit(limit=50)
		field_mask_entries = [e for e in audit["entries"] if e["source"] == "FieldMask"]
		self.assertTrue(
			len(field_mask_entries) > 0,
			"Mask event endpoint çıktısında olmalı",
		)
		# Son kayıt yeni olduğumuz olmalı (sıralı)
		latest = field_mask_entries[0]
		self.assertEqual(latest["target_doctype"], "Contact")
		self.assertIn("email_id", latest["summary"])

	def test_endpoint_entries_sorted_by_timestamp_desc(self):
		"""Karışık Version + FieldMask kayıtları timestamp'e göre sıralı."""
		from tradehub_core.api.v1 import permission_console as pc

		audit = pc.list_rbac_audit(limit=30)
		entries = audit["entries"]
		if len(entries) < 2:
			self.skipTest("Yeterli kayıt yok")
		for i in range(len(entries) - 1):
			self.assertGreaterEqual(
				entries[i]["timestamp"],
				entries[i + 1]["timestamp"],
				"Entries timestamp DESC sıralı olmalı",
			)


# ──────────────────────────────────────────────────────────────────────────
# Q) Sprint 5 Faz 2 — apply_list_masking helper
# ──────────────────────────────────────────────────────────────────────────


class TestSprint5_Q_ListMasking(unittest.TestCase):
	"""apply_list_masking — get_list çıktısı için maskeleme."""

	def setUp(self):
		frappe.set_user("Administrator")

	def test_administrator_bypasses_list_masking(self):
		from tradehub_core.api.v1.crm_masking import apply_list_masking

		rows = [
			{"name": "Contact-1", "email_id": "ali@x.com", "phone": "5551234567", "owner": "x@y.com"},
		]
		out = apply_list_masking(rows, "Contact", "Administrator")
		# Administrator → bypass → değer aynı
		self.assertEqual(out[0]["email_id"], "ali@x.com")
		self.assertEqual(out[0]["phone"], "5551234567")
		self.assertNotIn("_masked_fields", out[0])

	def test_owner_row_not_masked(self):
		from tradehub_core.api.v1.crm_masking import apply_list_masking

		rows = [
			{"name": "Contact-1", "email_id": "secret@x.com", "phone": "5551234567", "owner": _TEST_USER},
		]
		out = apply_list_masking(rows, "Contact", _TEST_USER)
		self.assertEqual(out[0]["email_id"], "secret@x.com")
		self.assertNotIn("_masked_fields", out[0])

	def test_non_owner_without_capability_masked(self):
		from tradehub_core.api.v1.crm_masking import apply_list_masking

		rows = [
			{
				"name": "Contact-1",
				"email_id": "secret@example.com",
				"phone": "5551234567",
				"owner": "other@user.com",
			},
		]
		out = apply_list_masking(rows, "Contact", _TEST_USER)
		# Finance Staff'da view.customer_pii yok → email_id ve phone maskeli
		self.assertNotEqual(out[0]["email_id"], "secret@example.com")
		self.assertNotEqual(out[0]["phone"], "5551234567")
		self.assertIn("_masked_fields", out[0])
		self.assertIn("email_id", out[0]["_masked_fields"])
		self.assertIn("phone", out[0]["_masked_fields"])

	def test_multiple_rows_owner_mixed(self):
		"""Aynı listede owner satırı açık + non-owner maskeli olabilir."""
		from tradehub_core.api.v1.crm_masking import apply_list_masking

		rows = [
			{"name": "Contact-A", "email_id": "mine@x.com", "phone": "5551111111", "owner": _TEST_USER},
			{"name": "Contact-B", "email_id": "yours@x.com", "phone": "5552222222", "owner": "other@x.com"},
		]
		out = apply_list_masking(rows, "Contact", _TEST_USER)
		# Owner satırı temiz
		self.assertEqual(out[0]["email_id"], "mine@x.com")
		self.assertNotIn("_masked_fields", out[0])
		# Non-owner satırı maskeli
		self.assertNotEqual(out[1]["email_id"], "yours@x.com")
		self.assertIn("_masked_fields", out[1])

	def test_admin_seller_profile_uses_user_field_for_owner(self):
		"""Admin Seller Profile sahibi `user` field'ından kontrol edilir."""
		from tradehub_core.api.v1.crm_masking import apply_list_masking

		rows = [
			{
				"name": "ASP-001",
				"user": _TEST_USER,  # session.user
				"iban": "TR74 1234 5678 9012 3456 7890",
				"tax_id": "1234567890",
			},
		]
		out = apply_list_masking(rows, "Admin Seller Profile", _TEST_USER)
		# user field == session.user → owner → maskeleme yok
		self.assertEqual(out[0]["iban"], "TR74 1234 5678 9012 3456 7890")
		self.assertNotIn("_masked_fields", out[0])

	def test_unknown_doctype_skipped(self):
		from tradehub_core.api.v1.crm_masking import apply_list_masking

		rows = [{"name": "X", "secret_field": "value", "owner": "x@y.com"}]
		out = apply_list_masking(rows, "Unknown DocType", _TEST_USER)
		# Unknown doctype → dokunmaz
		self.assertEqual(out[0]["secret_field"], "value")


# ──────────────────────────────────────────────────────────────────────────
# R) Sprint 5 Faz 3 — Frappe Desk PII permlevel koruması
# ──────────────────────────────────────────────────────────────────────────


class TestSprint5_R_DeskPermlevelProtection(unittest.TestCase):
	"""Property Setter + Custom DocPerm doğrulaması."""

	_DOCTYPES = ("Admin Seller Profile", "User Profile", "Contact")
	_PRIVILEGED = (
		"Seller Owner",
		"Seller Co-Owner",
		"Compliance Officer",
		"System Manager",
		"Marketplace Admin",
	)
	_NON_PRIVILEGED = ("Seller", "Marketplace Seller")

	def test_pii_fields_have_permlevel_2_property_setter(self):
		"""Tüm PII field'lar permlevel=2 Property Setter sahibi olmalı."""
		from tradehub_core.setup.pii_permlevel_setup import _PII_FIELDS_BY_DOCTYPE

		for doctype, fields in _PII_FIELDS_BY_DOCTYPE.items():
			for fieldname in fields:
				ps_name = f"{doctype}-{fieldname}-permlevel"
				if not frappe.db.exists("DocField", {"parent": doctype, "fieldname": fieldname}):
					continue
				ps_value = frappe.db.get_value("Property Setter", ps_name, "value")
				self.assertEqual(
					ps_value,
					"2",
					f"{doctype}.{fieldname} için Property Setter value=2 değil ({ps_value})",
				)

	def test_privileged_roles_have_permlevel_2_read(self):
		"""Privileged role'ler permlevel=2 read=1 Custom DocPerm'e sahip."""
		for doctype in self._DOCTYPES:
			for role in self._PRIVILEGED:
				if not frappe.db.exists("Role", role):
					continue
				existing = frappe.db.get_value(
					"Custom DocPerm",
					{"parent": doctype, "role": role, "permlevel": 2},
					["read", "write"],
					as_dict=True,
				)
				self.assertIsNotNone(existing, f"{doctype}/{role} permlevel 2 Custom DocPerm yok")
				self.assertEqual(
					existing["read"],
					1,
					f"{doctype}/{role} read=1 olmalı, {existing['read']} bulundu",
				)

	def test_non_privileged_roles_blocked_at_permlevel_2(self):
		"""'Seller' ve 'Marketplace Seller' permlevel 2'de read=0 olmalı."""
		for doctype in self._DOCTYPES:
			for role in self._NON_PRIVILEGED:
				if not frappe.db.exists("Role", role):
					continue
				existing = frappe.db.get_value(
					"Custom DocPerm",
					{"parent": doctype, "role": role, "permlevel": 2},
					["read", "write"],
					as_dict=True,
				)
				if not existing:
					# Custom DocPerm yoksa zaten okuma yok — OK
					continue
				self.assertEqual(
					existing["read"],
					0,
					f"{doctype}/{role} read=0 olmalı (non-privileged), {existing['read']}",
				)
				self.assertEqual(
					existing["write"],
					0,
					f"{doctype}/{role} write=0 olmalı",
				)

	def test_seller_owner_has_write_permission(self):
		"""Seller Owner Admin Seller Profile için permlevel 2 write=1 olmalı."""
		existing = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": "Admin Seller Profile", "role": "Seller Owner", "permlevel": 2},
			"write",
		)
		self.assertEqual(existing, 1, "Seller Owner ASP permlevel 2 write=1 olmalı")

	def test_compliance_officer_read_only(self):
		"""Compliance Officer permlevel 2 sadece read; write=0."""
		for doctype in self._DOCTYPES:
			existing = frappe.db.get_value(
				"Custom DocPerm",
				{"parent": doctype, "role": "Compliance Officer", "permlevel": 2},
				["read", "write"],
				as_dict=True,
			)
			if not existing:
				continue
			self.assertEqual(existing["read"], 1)
			self.assertEqual(
				existing["write"],
				0,
				f"Compliance Officer {doctype} write=0 olmalı",
			)


if __name__ == "__main__":
	unittest.main()
