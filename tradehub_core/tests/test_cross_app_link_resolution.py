"""
Test DocType Link Resolution (Monolith)

Eski 7-app mimarisi (tradehub_core / catalog / seller / commerce / logistics /
marketing / compliance) terk edildi — bugün tek `tradehub_core` app'i içinde
monolitik. Bu test artık sadece monolit içindeki kritik Link field
ilişkilerinin geçerliliğini doğrular.

Doğrulanan ilişkiler (Sprint 2 sonrası):
1. Listing -> Admin Seller Profile (mağaza)
2. Order -> User Profile (buyer) + Admin Seller Profile (seller)
3. RFQ Quote -> Admin Seller Profile
4. Listing Review -> User Profile (reviewer)
5. KYB Verification -> User (link target)
"""

import json
import unittest
from pathlib import Path


class TestMonolithLinkResolution(unittest.TestCase):
	"""Tek tradehub_core app'i içindeki DocType Link field'larını doğrula."""

	@classmethod
	def setUpClass(cls):
		# tests/ -> tradehub_core/ (module) -> tradehub_core/ (app)
		cls.doctype_root = Path(__file__).parent.parent / "tradehub_core" / "doctype"
		cls.doctypes = {}

		for doctype_dir in cls.doctype_root.iterdir():
			if not doctype_dir.is_dir():
				continue
			json_file = doctype_dir / f"{doctype_dir.name}.json"
			if not json_file.exists():
				continue
			with open(json_file) as f:
				try:
					definition = json.load(f)
				except json.JSONDecodeError:
					continue
			cls.doctypes[definition["name"]] = definition

	def _link_targets(self, doctype_name):
		"""DocType'taki Link field'ların {fieldname: target_doctype} haritası."""
		definition = self.doctypes.get(doctype_name)
		if not definition:
			return {}
		return {
			f["fieldname"]: f.get("options")
			for f in definition.get("fields", [])
			if f.get("fieldtype") == "Link"
		}

	def test_core_doctypes_present(self):
		"""Sprint 2 sonrası kritik DocType'lar paket altında bulunuyor mu?"""
		required = [
			"User Profile",
			"Admin Seller Profile",
			"Listing",
			"Order",
			"RFQ Quote",
			"Listing Review",
			"KYB Verification",
			"Seller Application",
		]
		for name in required:
			self.assertIn(name, self.doctypes, f"DocType '{name}' bulunamadı")

	def test_listing_links_to_admin_seller_profile(self):
		"""Listing.seller_profile → Admin Seller Profile (mağaza entity)."""
		links = self._link_targets("Listing")
		self.assertEqual(links.get("seller_profile"), "Admin Seller Profile")

	def test_order_links_to_user_and_admin_seller_profile(self):
		"""Order.buyer → User; Order.seller → Admin Seller Profile."""
		links = self._link_targets("Order")
		# buyer User'a Link (Frappe core)
		self.assertEqual(links.get("buyer"), "User")
		# seller Admin Seller Profile'a Link
		self.assertEqual(links.get("seller"), "Admin Seller Profile")

	def test_rfq_quote_links_to_admin_seller_profile(self):
		"""RFQ Quote.seller_profile → Admin Seller Profile (Sprint 2 değişikliği)."""
		links = self._link_targets("RFQ Quote")
		self.assertEqual(links.get("seller_profile"), "Admin Seller Profile")

	def test_listing_review_links_to_user_profile(self):
		"""Listing Review.reviewer → User Profile (Sprint 2 değişikliği)."""
		links = self._link_targets("Listing Review")
		self.assertEqual(links.get("reviewer"), "User Profile")

	def test_kyc_verification_doctype_exists(self):
		"""Sprint 2.6: KYC Verification ayrı DocType olarak yaratıldı."""
		self.assertIn("KYC Verification", self.doctypes)
		definition = self.doctypes["KYC Verification"]
		fields = {f["fieldname"]: f for f in definition.get("fields", [])}
		# account_type toggle (Kurumsal/Bireysel)
		self.assertIn("account_type", fields)
		self.assertEqual(fields["account_type"]["fieldtype"], "Select")
		# identity_document zorunlu (her iki toggle için)
		self.assertIn("identity_document", fields)
		# Kurumsal alanlar
		for f in ("company_name", "tax_id", "phone", "address", "billing_address"):
			self.assertIn(f, fields, f"KYC Verification missing field: {f}")

	def test_kyb_verification_refactored_for_sprint26(self):
		"""Sprint 2.6: KYB Verification.verification_kind kaldırıldı,
		mersis_no + kep_address eklendi, document_expiry_date kaldırıldı."""
		definition = self.doctypes["KYB Verification"]
		fields = {f["fieldname"]: f for f in definition.get("fields", [])}
		self.assertNotIn("verification_kind", fields, "verification_kind kaldırılmalıydı")
		self.assertNotIn("document_expiry_date", fields, "document_expiry_date kaldırılmalıydı")
		self.assertIn("mersis_no", fields)
		self.assertIn("kep_address", fields)
		self.assertIn("rejection_category", fields)

	def test_user_profile_autoname_is_user_field(self):
		"""User Profile.autoname = field:user (= email PK)."""
		definition = self.doctypes["User Profile"]
		self.assertEqual(definition.get("autoname"), "field:user")

	def test_user_profile_has_can_buy_can_sell_flags(self):
		"""User Profile içinde can_buy ve can_sell Check field'ları."""
		definition = self.doctypes["User Profile"]
		fields = {f["fieldname"]: f for f in definition.get("fields", [])}
		self.assertEqual(fields.get("can_buy", {}).get("fieldtype"), "Check")
		self.assertEqual(fields.get("can_sell", {}).get("fieldtype"), "Check")

	def test_legacy_buyer_seller_profile_still_present(self):
		"""Eski Buyer Profile / Seller Profile DocType'lar şu an mevcut (Sprint 4'te
		drop olacak); hidden bayrağı runtime patch'te DB üzerinde set edildiği için
		JSON'da görünmez — burada sadece varlık kontrolü yapıyoruz."""
		for legacy in ("Buyer Profile", "Seller Profile"):
			self.assertIn(legacy, self.doctypes, f"{legacy} JSON'u beklenirken silinmiş")


if __name__ == "__main__":
	unittest.main(verbosity=2)
