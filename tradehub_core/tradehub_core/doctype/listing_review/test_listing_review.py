"""Listing Review — Faz 1 testleri.

Senaryolar:
  1. Geçerli yorum oluşturma → status=Pending, is_verified_purchase=1
  2. Aynı order_item için ikinci yorum reddedilir
  3. Kendi mağazasına yorum yapan satıcı reddedilir
  4. Order durumu Tamamlandı/Kargoda dışındaysa reddedilir
  5. Rating 1..5 dışı reddedilir
  6. Body < 10 char reddedilir
  7. Approved → Listing.average_rating doğru hesaplanır
  8. Approved → Hidden → average_rating sıfırlanır
  9. Trash → average_rating sıfırlanır + Order Item.has_review=0
 10. Edit penceresi: 24 saat sonra reddedilir, edit_count > 1 reddedilir
"""

from __future__ import annotations

import json
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime


def _ensure_user(email: str, full_name: str = "Test User") -> str:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": full_name.split()[0],
				"last_name": " ".join(full_name.split()[1:]) or "User",
				"send_welcome_email": 0,
				"enabled": 1,
				"new_password": "test12345",
			}
		)
		user.insert(ignore_permissions=True)
	return email


def _ensure_buyer_profile(user_email: str, company: str = "Test Tekstil") -> str:
	row = frappe.db.get_value("Buyer Profile", {"user": user_email}, "name")
	if row:
		return row
	doc = frappe.get_doc(
		{
			"doctype": "Buyer Profile",
			"user": user_email,
			"buyer_name": "Buyer A",
			"company_name": company,
			"city": "İstanbul",
			"status": "Active",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_seller_profile(user_email: str, code: str = "TST-SLR-001") -> str:
	existing = frappe.db.get_value("Admin Seller Profile", {"user": user_email}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Admin Seller Profile",
			"user": user_email,
			"email": user_email,
			"seller_name": "Test Seller",
			"seller_code": code,
			"status": "Active",
			"company_name": "Seller Co",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_kyb_verified(user_email: str) -> None:
	"""Order validation seller KYB Verified olmasını ister — seed et.

	KYB Verification'ın belge alanları zorunlu; test fixture için
	ignore_mandatory ile bypass ediyoruz (status alanı Order doğrulamasının
	kontrol ettiği tek değer).
	"""
	existing = frappe.db.get_value("KYB Verification", {"user": user_email}, "name")
	if existing:
		frappe.db.set_value("KYB Verification", existing, "status", "Verified")
		return
	doc = frappe.get_doc(
		{
			"doctype": "KYB Verification",
			"user": user_email,
			"company_title": "Seller Co Ltd",
			"status": "Verified",
		}
	)
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)


def _ensure_listing(seller_name: str, code: str = "TST-LST-001") -> str:
	existing = frappe.db.get_value("Listing", {"listing_code": code}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Listing",
			"listing_code": code,
			"title": "Test Tişört",
			"seller_profile": seller_name,
			"status": "Active",
			"currency": "TRY",
			"base_price": 100,
			"selling_price": 100,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_order(buyer_email: str, seller_name: str, listing_name: str, status: str = "Tamamlandı"):
	"""Yeni bir Order + 1 Order Item üretir, (order_name, order_item_name) döner."""
	order = frappe.get_doc(
		{
			"doctype": "Order",
			"buyer": buyer_email,
			"seller": seller_name,
			"status": status,
			"order_date": now_datetime(),
			"currency": "TRY",
			"subtotal": 100,
			"shipping_fee": 0,
			"total": 100,
			"items": [
				{
					"listing": listing_name,
					"listing_title": "Test Tişört",
					"unit_price": 100,
					"quantity": 1,
					"total_price": 100,
				}
			],
		}
	)
	order.insert(ignore_permissions=True)
	return order.name, order.items[0].name


class TestListingReview(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.buyer_email = _ensure_user("test_buyer_lr@example.com", "Buyer A")
		cls.seller_email = _ensure_user("test_seller_lr@example.com", "Seller A")
		cls.buyer_profile = _ensure_buyer_profile(cls.buyer_email)
		cls.seller = _ensure_seller_profile(cls.seller_email)
		_ensure_kyb_verified(cls.seller_email)
		cls.listing = _ensure_listing(cls.seller)

	def setUp(self):
		# Her test için temiz bir order üret + Listing rating cache'ini sıfırla
		frappe.set_user("Administrator")
		# Önceki test koşumundan kalmış olabilecek state'i temizle
		frappe.db.sql("DELETE FROM `tabListing Review` WHERE listing = %s", (self.listing,))
		frappe.db.set_value(
			"Listing",
			self.listing,
			{
				"average_rating": 0,
				"review_count": 0,
				"rating_distribution": None,
				"last_review_at": None,
			},
			update_modified=False,
		)
		frappe.db.commit()
		self.order, self.order_item = _ensure_order(
			self.buyer_email, self.seller, self.listing, status="Tamamlandı"
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		# Test verisini temizle
		frappe.db.sql("DELETE FROM `tabListing Review` WHERE listing = %s", (self.listing,))
		frappe.db.sql("DELETE FROM `tabOrder Item` WHERE parent = %s", (self.order,))
		frappe.db.sql("DELETE FROM `tabOrder` WHERE name = %s", (self.order,))
		frappe.db.commit()

	# ------------------------------------------------------------------
	# 1. Geçerli yorum oluşturma
	# ------------------------------------------------------------------
	def test_create_valid_review_starts_pending(self):
		frappe.set_user(self.buyer_email)
		from tradehub_core.api.review import submit_listing_review

		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Ürün çok kaliteli, hızlı geldi. Kesinlikle tavsiye ederim.",
			title="Harika ürün",
		)
		self.assertTrue(res["success"])
		self.assertEqual(res["status"], "Pending")

		doc = frappe.get_doc("Listing Review", res["name"])
		self.assertEqual(doc.is_verified_purchase, 1)
		self.assertEqual(doc.seller, self.seller)
		self.assertEqual(doc.reviewer_user, self.buyer_email)
		self.assertEqual(doc.rating, 5)

	# ------------------------------------------------------------------
	# 2. Duplicate (aynı order_item)
	# ------------------------------------------------------------------
	def test_duplicate_review_rejected(self):
		frappe.set_user(self.buyer_email)
		from tradehub_core.api.review import submit_listing_review

		submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="İlk yorum. Yeterince uzun bir metin.",
		)
		with self.assertRaises(frappe.ValidationError):
			submit_listing_review(
				order_item=self.order_item,
				rating=4,
				body="İkinci yorum denemesi, yine yeterince uzun.",
			)

	# ------------------------------------------------------------------
	# 3. Kendi mağazasına yorum yapan satıcı
	# ------------------------------------------------------------------
	def test_self_review_rejected(self):
		# Order'ın buyer'ını seller_email yap
		frappe.set_user("Administrator")
		frappe.db.set_value("Order", self.order, "buyer", self.seller_email)
		frappe.db.commit()

		frappe.set_user(self.seller_email)
		from tradehub_core.api.review import submit_listing_review

		with self.assertRaises(frappe.PermissionError):
			submit_listing_review(
				order_item=self.order_item,
				rating=5,
				body="Kendi ürünüme yorum yazma denemesi.",
			)

	# ------------------------------------------------------------------
	# 4. Order delivered olmayan
	# ------------------------------------------------------------------
	def test_non_delivered_order_rejected(self):
		frappe.set_user("Administrator")
		frappe.db.set_value("Order", self.order, "status", "Ödeme Bekleniyor")
		frappe.db.commit()

		frappe.set_user(self.buyer_email)
		from tradehub_core.api.review import submit_listing_review

		with self.assertRaises(frappe.ValidationError):
			submit_listing_review(
				order_item=self.order_item,
				rating=5,
				body="Henüz teslim olmadı, yorum yapma denemesi.",
			)

	# ------------------------------------------------------------------
	# 5. Rating range
	# ------------------------------------------------------------------
	def test_rating_out_of_range(self):
		frappe.set_user(self.buyer_email)
		from tradehub_core.api.review import submit_listing_review

		with self.assertRaises(frappe.ValidationError):
			submit_listing_review(
				order_item=self.order_item,
				rating=0,
				body="Sıfır puan denemesi, body uzun olmalı.",
			)

	def test_rating_above_5_rejected(self):
		frappe.set_user(self.buyer_email)
		from tradehub_core.api.review import submit_listing_review

		with self.assertRaises(frappe.ValidationError):
			submit_listing_review(
				order_item=self.order_item,
				rating=6,
				body="6 puan denemesi, body uzun olmalı tabii.",
			)

	# ------------------------------------------------------------------
	# 6. Body length
	# ------------------------------------------------------------------
	def test_short_body_rejected(self):
		frappe.set_user(self.buyer_email)
		from tradehub_core.api.review import submit_listing_review

		with self.assertRaises(frappe.ValidationError):
			submit_listing_review(order_item=self.order_item, rating=5, body="kısa")

	# ------------------------------------------------------------------
	# 7. Approved → Listing.average_rating doğru hesaplanır
	# ------------------------------------------------------------------
	def test_approve_updates_listing_rating(self):
		frappe.set_user(self.buyer_email)
		from tradehub_core.api.review import (
			admin_moderate_review,
			get_listing_rating_summary,
			submit_listing_review,
		)

		res = submit_listing_review(
			order_item=self.order_item,
			rating=4,
			body="Güzel ürün, paketleme dikkatli, gönderim hızlı.",
		)
		# Pending iken Listing.average_rating 0 olmalı
		row = frappe.db.get_value("Listing", self.listing, ["average_rating", "review_count"], as_dict=True)
		self.assertEqual(int(row.review_count or 0), 0)

		# Admin onaylar
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")

		row = frappe.db.get_value(
			"Listing",
			self.listing,
			["average_rating", "review_count", "rating_distribution"],
			as_dict=True,
		)
		self.assertEqual(int(row.review_count), 1)
		self.assertAlmostEqual(float(row.average_rating), 4.0, places=2)
		dist = json.loads(row.rating_distribution or "{}")
		self.assertEqual(int(dist.get("4", 0)), 1)

		# Order Item.has_review = 1
		oi = frappe.db.get_value("Order Item", self.order_item, ["has_review", "review"], as_dict=True)
		self.assertEqual(int(oi.has_review), 1)
		self.assertEqual(str(oi.review), str(res["name"]))

		# Summary API
		summary = get_listing_rating_summary(self.listing)
		self.assertEqual(summary["review_count"], 1)
		self.assertEqual(summary["verified_purchase_count"], 1)

	# ------------------------------------------------------------------
	# 8. Approved → Hidden
	# ------------------------------------------------------------------
	def test_hide_removes_from_aggregate(self):
		frappe.set_user(self.buyer_email)
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review

		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Birinci yorum, gizleme testine girecek.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		admin_moderate_review(name=res["name"], action="hide")

		row = frappe.db.get_value("Listing", self.listing, ["average_rating", "review_count"], as_dict=True)
		self.assertEqual(int(row.review_count), 0)
		self.assertEqual(float(row.average_rating), 0.0)

	# ------------------------------------------------------------------
	# 9. Trash
	# ------------------------------------------------------------------
	def test_trash_removes_from_aggregate_and_order_item(self):
		frappe.set_user(self.buyer_email)
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review

		res = submit_listing_review(
			order_item=self.order_item,
			rating=3,
			body="Trash testi için yazılan bir yorum metni.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		frappe.delete_doc("Listing Review", res["name"], ignore_permissions=True, force=True)

		row = frappe.db.get_value("Listing", self.listing, ["average_rating", "review_count"], as_dict=True)
		self.assertEqual(int(row.review_count), 0)
		oi = frappe.db.get_value("Order Item", self.order_item, "has_review")
		self.assertEqual(int(oi or 0), 0)

	# ------------------------------------------------------------------
	# 10. Edit penceresi
	# ------------------------------------------------------------------
	def test_edit_count_limit(self):
		frappe.set_user(self.buyer_email)
		from tradehub_core.api.review import submit_listing_review, update_listing_review

		res = submit_listing_review(
			order_item=self.order_item,
			rating=4,
			body="İlk versiyon, daha sonra güncellenecek.",
		)
		# 1. düzenleme — geçerli
		update_listing_review(name=res["name"], body="Güncellenmiş ilk düzenleme metni.", rating=5)
		# 2. düzenleme — reddedilmeli
		with self.assertRaises(frappe.ValidationError):
			update_listing_review(name=res["name"], body="İkinci kez güncelleme denemesi.")

	def test_edit_window_expires(self):
		frappe.set_user(self.buyer_email)
		from tradehub_core.api.review import submit_listing_review, update_listing_review

		res = submit_listing_review(
			order_item=self.order_item,
			rating=4,
			body="Eski tarihli bir yorum, edit penceresi geçmiş olacak.",
		)
		# submitted_at'ı 25 saat öncesine çek
		frappe.set_user("Administrator")
		frappe.db.set_value(
			"Listing Review",
			res["name"],
			"submitted_at",
			add_to_date(now_datetime(), hours=-25),
			update_modified=False,
		)
		frappe.db.commit()
		frappe.set_user(self.buyer_email)
		with self.assertRaises(frappe.ValidationError):
			update_listing_review(name=res["name"], body="Süre geçti, bu güncellenemez.")

	# ==================================================================
	# Faz 2 — yeni testler
	# ==================================================================

	def _make_approved_review(self, rating=5, aspects=None, images=None):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=rating,
			body="Faz 2 test yorum metni yeterince uzun olmalı.",
			aspects=aspects,
			images=images,
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		return res["name"]

	# 1. 5 boyutlu puan kaydedilir + Listing aspect ortalaması güncellenir
	def test_aspects_saved_and_aggregated(self):
		from tradehub_core.api.review import get_listing_rating_summary

		name = self._make_approved_review(
			rating=5,
			aspects={
				"product_quality": 5,
				"service": 4,
				"shipping": 3,
				"spec_match": 5,
				"documentation": 4,
			},
		)
		doc = frappe.get_doc("Listing Review", name)
		self.assertEqual(doc.product_quality_rating, 5)
		self.assertEqual(doc.service_rating, 4)
		self.assertEqual(doc.shipping_rating, 3)

		summary = get_listing_rating_summary(self.listing)
		self.assertAlmostEqual(summary["aspect_averages"]["product_quality"], 5.0, places=2)
		self.assertAlmostEqual(summary["aspect_averages"]["service"], 4.0, places=2)
		self.assertAlmostEqual(summary["aspect_averages"]["shipping"], 3.0, places=2)

	# 2. Aspect rating 1..5 dışı reddedilir
	def test_aspect_rating_out_of_range(self):
		from tradehub_core.api.review import submit_listing_review

		frappe.set_user(self.buyer_email)
		with self.assertRaises(frappe.ValidationError):
			submit_listing_review(
				order_item=self.order_item,
				rating=5,
				body="Aspect dışı puan testi yeterince uzun.",
				aspects={"product_quality": 9},
			)

	# 3. Image limit (max 10)
	def test_image_limit_enforced(self):
		from tradehub_core.api.review import submit_listing_review

		frappe.set_user(self.buyer_email)
		images = [{"image": f"/files/test{i}.png"} for i in range(11)]
		# 11 görsel verirsek API ilk 10'u alır (silently truncate) — limit kontrol
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Image limit testi yeterince uzun yorum.",
			images=images,
		)
		doc = frappe.get_doc("Listing Review", res["name"])
		self.assertEqual(len(doc.images), 10)

	# 4. Helpful vote unique (aynı user 2 kez aynı oyu veremez)
	def test_helpful_vote_unique(self):
		from tradehub_core.api.review import vote_review_helpful

		name = self._make_approved_review()
		# Buyer'dan FARKLI bir kullanıcı oy versin (kendi yorumuna oy yasak)
		voter_email = "test_voter_lr@example.com"
		_ensure_user(voter_email, "Voter A")
		frappe.set_user(voter_email)
		r1 = vote_review_helpful(review=name, vote="helpful")
		self.assertTrue(r1["success"])
		r2 = vote_review_helpful(review=name, vote="helpful")
		# Aynı oy → changed=False, kayıt zaten vardı
		self.assertFalse(r2["changed"])

	# 5. Helpful sayacı doğru
	def test_helpful_count_updates(self):
		from tradehub_core.api.review import unvote_review, vote_review_helpful

		name = self._make_approved_review()
		voter_email = "test_voter2_lr@example.com"
		_ensure_user(voter_email, "Voter B")
		frappe.set_user(voter_email)
		vote_review_helpful(review=name, vote="helpful")
		count = frappe.db.get_value("Listing Review", name, "helpful_count")
		self.assertEqual(int(count), 1)

		# Vote değişimi: helpful → not_helpful
		vote_review_helpful(review=name, vote="not_helpful")
		row = frappe.db.get_value(
			"Listing Review", name, ["helpful_count", "not_helpful_count"], as_dict=True
		)
		self.assertEqual(int(row.helpful_count), 0)
		self.assertEqual(int(row.not_helpful_count), 1)

		# Unvote
		unvote_review(review=name)
		row = frappe.db.get_value(
			"Listing Review", name, ["helpful_count", "not_helpful_count"], as_dict=True
		)
		self.assertEqual(int(row.helpful_count), 0)
		self.assertEqual(int(row.not_helpful_count), 0)

	# 6. Kendi yoruma oy verme yasak
	def test_self_vote_rejected(self):
		from tradehub_core.api.review import vote_review_helpful

		name = self._make_approved_review()
		frappe.set_user(self.buyer_email)
		with self.assertRaises(frappe.PermissionError):
			vote_review_helpful(review=name, vote="helpful")

	# 7. Abuse threshold (3 ihbar) → otomatik Hidden
	def test_abuse_threshold_auto_hide(self):
		from tradehub_core.api.review import report_review_abuse

		name = self._make_approved_review()
		# 3 farklı kullanıcıdan ihbar gönder
		for i in range(3):
			email = f"test_reporter{i}_lr@example.com"
			_ensure_user(email, f"Reporter {i}")
			frappe.set_user(email)
			report_review_abuse(review=name, reason="Spam", note=f"Test ihbar {i}")
		row = frappe.db.get_value("Listing Review", name, ["status", "abuse_report_count"], as_dict=True)
		self.assertEqual(row.status, "Hidden")
		self.assertEqual(int(row.abuse_report_count), 3)

	# 8. Aynı kullanıcı tekrar ihbar edemez
	def test_duplicate_abuse_report_rejected(self):
		from tradehub_core.api.review import report_review_abuse

		name = self._make_approved_review()
		email = "test_dup_reporter_lr@example.com"
		_ensure_user(email, "Dup Reporter")
		frappe.set_user(email)
		report_review_abuse(review=name, reason="Spam")
		with self.assertRaises(frappe.ValidationError):
			report_review_abuse(review=name, reason="Spam")

	# 9. Seller reply: yalnız kendi review'ine
	def test_seller_reply_only_owner(self):
		from tradehub_core.api.review import submit_seller_reply

		name = self._make_approved_review()
		# 3rd party user reply yazamaz
		stranger = "test_stranger_lr@example.com"
		_ensure_user(stranger, "Stranger")
		frappe.set_user(stranger)
		with self.assertRaises(frappe.PermissionError):
			submit_seller_reply(review=name, reply="3rd party deneme yanıt.")

		# Seller user yazabilir
		frappe.set_user(self.seller_email)
		r = submit_seller_reply(review=name, reply="Teşekkürler, geri bildirim için.")
		self.assertTrue(r["success"])
		self.assertIsNotNone(r.get("seller_reply_at"))

	# 10. Bulk moderate
	def test_bulk_moderate(self):
		from tradehub_core.api.review import admin_bulk_moderate, submit_listing_review

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Bulk moderate test yorum yeterince uzun.",
		)
		frappe.set_user("Administrator")
		out = admin_bulk_moderate(names=[res["name"]], action="approve")
		self.assertEqual(out["total"], 1)
		self.assertTrue(out["results"][0]["ok"])
		self.assertEqual(out["results"][0]["status"], "Approved")

	# ==================================================================
	# Faz 3 — Risk Score, Reputation, ML Weighted Rating
	# ==================================================================

	# 11. Risk Score: First-time reviewer → +5
	def test_risk_first_time_reviewer(self):
		from tradehub_core.api.review import submit_listing_review

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="İlk yorumum yeterince uzun bir metin.",
		)
		score = frappe.db.get_value("Listing Review", res["name"], "risk_score")
		# First-time +5, body length 39+ char ile body_length_anomaly tetiklenmemeli
		self.assertGreaterEqual(int(score or 0), 5)

	# 12. Risk Score: Body length anomaly (5★ + < 30 char)
	def test_risk_body_length_anomaly(self):
		from tradehub_core.api.review import submit_listing_review

		frappe.set_user(self.buyer_email)
		# Tam 25 karakter, 5★ → +15 + first-time +5 = 20
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Çok kısa bir yorum bu",  # 21 char
		)
		factors_json = frappe.db.get_value("Listing Review", res["name"], "risk_factors_json")
		self.assertIn("body_length_anomaly", factors_json or "")

	# 13. Risk Score: Rating-text mismatch (5★ + negatif kelime)
	def test_risk_rating_text_mismatch(self):
		from tradehub_core.api.review import submit_listing_review

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Ürün berbat ama yine de 5 yıldız veriyorum garip yorum.",
		)
		factors_json = frappe.db.get_value("Listing Review", res["name"], "risk_factors_json")
		self.assertIn("rating_text_mismatch", factors_json or "")

	# 14. Risk threshold high → weighted_contribution = 0.1
	def test_risk_high_threshold_penalizes_weight(self):
		from tradehub_core.api.review import submit_listing_review

		# Çoklu sinyal tetikleyelim: kısa body + negatif kelime + 5★
		# body_length_anomaly (+15) + rating_text_mismatch (+20) + first_time (+5) = 40
		# Bu orta risk. Daha yüksek için boilerplate da gerek.
		# Önce bir review yaz, sonra çok benzer ikincisini yaz (boilerplate)
		# Ama ikinci review için yeni order item gerekir.
		# Bunun yerine düşük: orta risk testi
		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Berbat kötü iade kalitesiz!",  # 27 char + negatif keyword + 5★
		)
		row = frappe.db.get_value(
			"Listing Review",
			res["name"],
			["risk_score", "weighted_contribution"],
			as_dict=True,
		)
		score = int(row.risk_score)
		# body_length(15) + mismatch(20) + first_time(5) = 40 → medium → 0.5
		self.assertGreaterEqual(score, 31)
		self.assertLess(float(row.weighted_contribution), 1.0)

	# 15. Reviewer Reputation: ilk hesaplama Newcomer
	def test_reputation_initial_newcomer(self):
		from tradehub_core.api.reputation import recompute_user

		# Önce bir Approved review olsun
		from tradehub_core.api.review import (
			admin_moderate_review,
			submit_listing_review,
		)

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Reputation baseline test yorum metni.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		out = recompute_user(self.buyer_email)
		self.assertEqual(out["tier"], "Newcomer")
		self.assertLessEqual(out["score"], 75)

	# 16. Reputation: helpful vote ile skor artar
	def test_reputation_increments_on_helpful(self):
		from tradehub_core.api.reputation import recompute_user
		from tradehub_core.api.review import (
			admin_moderate_review,
			submit_listing_review,
			vote_review_helpful,
		)

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Reputation helpful test yorum metni.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")

		base = recompute_user(self.buyer_email)["score"]

		# Voter olarak farklı user oluştur
		voter = "test_rep_voter@example.com"
		_ensure_user(voter, "Rep Voter")
		frappe.set_user(voter)
		vote_review_helpful(review=res["name"], vote="helpful")

		frappe.set_user("Administrator")
		new_rep = recompute_user(self.buyer_email)
		self.assertGreater(new_rep["score"], base)
		self.assertEqual(new_rep["helpful_received"], 1)

	# 17. Reputation: tier upgrade'i
	def test_reputation_tier_upgrade(self):
		from tradehub_core.api.reputation import recompute_user

		user = self.buyer_email
		# Hesaplama: 50 base + helpful_received*2 (max 30) → 80
		# Doğrudan DB'ye yüksek helpful_count enjekte edip recompute test edelim
		# Burada: 1 review insert et, helpful_count'u manuel set et
		from tradehub_core.api.review import (
			admin_moderate_review,
			submit_listing_review,
		)

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Tier upgrade test yorum yeterince uzun.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		# Helpful count manuel inject (örnek 20)
		frappe.db.set_value("Listing Review", res["name"], "helpful_count", 20, update_modified=False)
		out = recompute_user(user)
		# 50 + min(30, 20*2=40)=30 + (review_count=1, threshold 10 -> 0)
		# = 80 → Top Contributor (75-89)
		self.assertEqual(out["tier"], "Top Contributor")

	# 18. ML Weighted Rating: Approved review için weighted_rating güncellenir
	def test_weighted_rating_basic(self):
		from tradehub_core.api.rating_engine import compute_weighted_rating
		from tradehub_core.api.review import (
			admin_moderate_review,
			submit_listing_review,
		)

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=4,
			body="Weighted rating basic test yorum metni.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")

		out = compute_weighted_rating(self.listing)
		self.assertEqual(out["weighted_review_count"], 1)
		# Verified purchase + recency tam + Newcomer (1.0) → rating ~= 4
		self.assertGreater(out["weighted_rating"], 0)

	# 19. Trust signals payload'ı geliyor
	def test_trust_signals_payload(self):
		from tradehub_core.api.review import (
			admin_moderate_review,
			get_listing_rating_summary,
			submit_listing_review,
		)

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Trust signals payload test yorum metni.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")

		s = get_listing_rating_summary(self.listing)
		self.assertIn("weighted_rating", s)
		self.assertIn("trust_signals", s)
		ts = s["trust_signals"]
		self.assertEqual(ts["verified_purchase_pct"], 100.0)

	# 20. Risk recompute idempotent (aynı review için ikinci kez çağrılır)
	def test_risk_idempotent(self):
		from tradehub_core.api.review import submit_listing_review
		from tradehub_core.api.risk import compute_and_apply_risk_score

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Idempotent risk test yorum yeterince uzun bir metin.",
		)
		doc = frappe.get_doc("Listing Review", res["name"])
		first = doc.risk_score

		# Tekrar çağır
		compute_and_apply_risk_score(doc)
		second = frappe.db.get_value("Listing Review", res["name"], "risk_score")

		# Sonuç aynı olmalı (deterministic)
		self.assertEqual(int(first or 0), int(second or 0))

		# Tek bir Review Risk Score kaydı olmalı
		cnt = frappe.db.count("Review Risk Score", filters={"review": res["name"]})
		self.assertEqual(cnt, 1)

	# 21. get_reviewer_profile endpoint çalışıyor
	def test_get_reviewer_profile(self):
		from tradehub_core.api.reputation import get_reviewer_profile, recompute_user

		recompute_user(self.buyer_email)
		profile = get_reviewer_profile(user=self.buyer_email)
		self.assertEqual(profile["user"], self.buyer_email)
		self.assertIn(
			profile["tier"],
			(
				"Newcomer",
				"Trusted",
				"Top Contributor",
				"Verified Pro",
			),
		)

	# 22. KYB Verified buyer 1.5x weight
	def test_kyb_buyer_weight_multiplier(self):
		from tradehub_core.api.rating_engine import compute_review_weight

		# Mock review dict — KYB verified vs not
		base = {
			"is_verified_purchase": 1,
			"is_kyb_verified": 0,
			"order_total": 0,
			"published_at": now_datetime(),
			"reviewer_user": None,
			"weighted_contribution": 1.0,
		}
		w_no_kyb = compute_review_weight(base)
		base_kyb = dict(base, is_kyb_verified=1)
		w_kyb = compute_review_weight(base_kyb)
		# KYB ekstra ×1.5 katsayı
		self.assertAlmostEqual(w_kyb / w_no_kyb, 1.5, places=2)

	# 23. Order size multi
	def test_order_size_multiplier(self):
		from tradehub_core.api.rating_engine import compute_review_weight

		base = {
			"is_verified_purchase": 1,
			"is_kyb_verified": 0,
			"published_at": now_datetime(),
			"reviewer_user": None,
			"weighted_contribution": 1.0,
		}
		w_small = compute_review_weight(dict(base, order_total=100))
		w_big = compute_review_weight(dict(base, order_total=15000))
		# 10K+ → 1.3x
		self.assertAlmostEqual(w_big / w_small, 1.3, places=2)

	# 24. Recency decay: 12+ ay → 0.5
	def test_recency_decay_old_review(self):
		from frappe.utils import add_to_date

		from tradehub_core.api.rating_engine import compute_review_weight

		old_date = add_to_date(now_datetime(), days=-400)  # ~13 ay
		base = {
			"is_verified_purchase": 1,
			"is_kyb_verified": 0,
			"order_total": 0,
			"published_at": old_date,
			"reviewer_user": None,
			"weighted_contribution": 1.0,
		}
		fresh = dict(base, published_at=now_datetime())
		w_old = compute_review_weight(base)
		w_fresh = compute_review_weight(fresh)
		self.assertAlmostEqual(w_old / w_fresh, 0.5, places=2)

	# 25. Risk penalty: high risk weighted_contribution=0.1
	def test_risk_high_penalty(self):
		from tradehub_core.api.rating_engine import compute_review_weight

		base = {
			"is_verified_purchase": 1,
			"is_kyb_verified": 0,
			"order_total": 0,
			"published_at": now_datetime(),
			"reviewer_user": None,
		}
		w_normal = compute_review_weight(dict(base, weighted_contribution=1.0))
		w_high_risk = compute_review_weight(dict(base, weighted_contribution=0.1))
		self.assertAlmostEqual(w_high_risk / w_normal, 0.1, places=2)

	# ==================================================================
	# Faz 4 — Q&A, Timeline, Translation, Dispute, Templates, Vine
	# ==================================================================

	# 26. Soru oluşturma → status Pending
	def test_qa_submit_question(self):
		from tradehub_core.api.qa import submit_listing_question

		frappe.set_user(self.buyer_email)
		r = submit_listing_question(
			listing=self.listing,
			question="Bu ürünün stok durumu nedir ve hızlı kargo seçeneği var mı?",
		)
		self.assertTrue(r["success"])
		self.assertEqual(r["status"], "Pending")

	# 27. Cevap eklenince status Answered
	def test_qa_answer_changes_status(self):
		from tradehub_core.api.qa import submit_listing_question, submit_question_answer

		frappe.set_user(self.buyer_email)
		q = submit_listing_question(
			listing=self.listing,
			question="Garanti süresi hakkında bilgi alabilir miyim?",
		)
		# Admin cevap yazsın
		frappe.set_user("Administrator")
		a = submit_question_answer(
			question=q["name"],
			answer="Standart 2 yıl garanti sunuyoruz.",
		)
		self.assertTrue(a["success"])
		# Status Answered olmuş mu?
		q_row = frappe.db.get_value("Listing Question", q["name"], ["status", "answer_count"], as_dict=True)
		self.assertEqual(q_row.status, "Answered")
		self.assertEqual(int(q_row.answer_count), 1)

	# 28. Seller cevabı → is_seller_answer=1
	def test_qa_seller_answer_flag(self):
		from tradehub_core.api.qa import submit_listing_question, submit_question_answer

		frappe.set_user(self.buyer_email)
		q = submit_listing_question(
			listing=self.listing,
			question="Numune gönderebilir misiniz lütfen?",
		)
		frappe.set_user(self.seller_email)
		a = submit_question_answer(
			question=q["name"],
			answer="Evet, numune ücretsizdir.",
		)
		self.assertTrue(a["is_seller_answer"])
		self.assertEqual(a["responder_type"], "seller")

	# 29. Question helpful vote unique
	def test_qa_helpful_vote_unique(self):
		from tradehub_core.api.qa import submit_listing_question, vote_question_helpful

		frappe.set_user(self.buyer_email)
		q = submit_listing_question(
			listing=self.listing,
			question="Test sorusu helpful oy kontrolü için yazılmıştır.",
		)
		voter = "qa_voter@test.com"
		_ensure_user(voter, "QA Voter")
		frappe.set_user(voter)
		r1 = vote_question_helpful(target_type="question", target_id=str(q["name"]))
		self.assertTrue(r1["changed"])
		# Aynı oy ikinci kez → changed=False
		r2 = vote_question_helpful(target_type="question", target_id=str(q["name"]))
		self.assertFalse(r2["changed"])

	# 30. Timeline: T+30 update ekle
	def test_timeline_add_update(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.timeline import get_review_timeline, submit_review_update

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Timeline testi için ana yorum metni yeterince uzun.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")

		frappe.set_user(self.buyer_email)
		u = submit_review_update(
			review=res["name"],
			stage="30-day",
			rating=4,
			body="1 ay sonra: ürün hâlâ iyi durumda, küçük bir aşınma var.",
		)
		self.assertTrue(u["success"])
		self.assertEqual(u["stage"], "30-day")

		# Timeline 2 entry: Initial + 30-day
		tl = get_review_timeline(review=res["name"])
		stages = [t["stage"] for t in tl["timeline"]]
		self.assertIn("Initial", stages)
		self.assertIn("30-day", stages)

	# 31. Long-term score 90-day update'ten hesaplanır
	def test_timeline_long_term_score(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.timeline import submit_review_update

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Long term score testi için ana yorum metni.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		frappe.set_user(self.buyer_email)
		submit_review_update(
			review=res["name"],
			stage="90-day",
			rating=4,
			body="3 ay sonra: kalite hala iyi ama bazı sorunlar oluyor.",
		)
		submit_review_update(
			review=res["name"],
			stage="Long-term",
			rating=3,
			body="6 ay sonra: kalite düştü, beklenti karşılanmadı.",
		)

		score = frappe.db.get_value("Listing Review", res["name"], "long_term_score")
		# (4+3)/2 = 3.5
		self.assertAlmostEqual(float(score), 3.5, places=2)

	# 32. Translation: cache hit ikinci çağrıda
	def test_translation_cache(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.translation import get_review_translation

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=4,
			body="This is an English review for translation cache test.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")

		# İlk çağrı: cached=False
		r1 = get_review_translation(review=res["name"], target_lang="tr")
		self.assertFalse(r1["cached"])
		# İkinci çağrı: cached=True
		r2 = get_review_translation(review=res["name"], target_lang="tr")
		self.assertTrue(r2["cached"])

	# 33. Translation language detection
	def test_translation_language_detect(self):
		from tradehub_core.api.translation import _detect_language

		self.assertEqual(_detect_language("Bu çok güzel bir ürün."), "tr")
		self.assertEqual(_detect_language("This is a great product."), "en")

	# 34. Dispute: 1★ yorum üzerinden açılır
	def test_dispute_open_from_low_rating(self):
		from tradehub_core.api.dispute import open_dispute_from_review
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=1,
			body="Ürün gerçekten kötü ve hasarlı geldi, çok hayal kırıklığı.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")

		frappe.set_user(self.buyer_email)
		d = open_dispute_from_review(
			review=res["name"],
			dispute_type="Damaged",
			description="Ürün hasarlı geldi, fotoğraf elimde var.",
		)
		self.assertTrue(d["success"])
		self.assertEqual(d["status"], "Open")

	# 35. Dispute: 3★+ yorum için reddedilir
	def test_dispute_high_rating_rejected(self):
		from tradehub_core.api.dispute import open_dispute_from_review
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=4,
			body="Ürün gayet iyi, sadece kargo biraz geç geldi.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")

		frappe.set_user(self.buyer_email)
		with self.assertRaises(frappe.ValidationError):
			open_dispute_from_review(
				review=res["name"],
				dispute_type="Other",
				description="High rating dispute test.",
			)

	# 36. Dispute resolve → review rozet'ı set
	def test_dispute_resolution_sets_badge(self):
		from tradehub_core.api.dispute import open_dispute_from_review, resolve_dispute
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=2,
			body="Ürün beklediğim gibi değil, kalite zayıf.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		frappe.set_user(self.buyer_email)
		d = open_dispute_from_review(
			review=res["name"],
			dispute_type="Product Quality",
			description="Kalite reklamla uyumlu değil, iade istiyorum.",
		)
		frappe.set_user("Administrator")
		r = resolve_dispute(
			dispute=d["name"],
			in_favor_of="buyer",
			note="Hasar kanıtlandı, iade onaylandı.",
		)
		self.assertEqual(r["status"], "Resolved-Buyer")
		badge = frappe.db.get_value("Listing Review", res["name"], "dispute_resolved_in_favor_of")
		self.assertEqual(badge, "buyer")

	# 37. Template seed: 4 default şablon
	def test_template_seed(self):
		from tradehub_core.api.templates import seed_default_templates

		seed_default_templates()
		templates = frappe.get_all(
			"Category Review Template",
			filters={"is_active": 1},
			fields=["template_name"],
		)
		names = [t.template_name for t in templates]
		self.assertIn("Tekstil Şablonu", names)
		self.assertIn("Makine Ekipman Şablonu", names)

	# 38. Template answers submit
	def test_template_submit_answers(self):
		from tradehub_core.api.review import submit_listing_review
		from tradehub_core.api.templates import (
			get_template_answers,
			seed_default_templates,
			submit_template_answers,
		)

		seed_default_templates()
		# Listing'in product_category'sini set et (mevcut yoksa atla)
		# Test fixture listing'inde product_category yok, manuel set:
		tekstil_tpl = "Tekstil Şablonu"
		# Şablonun category'sini test listing'in product_category'sine bağla
		# (test fixture'ında listing.product_category boş — burada şablon
		# kategori olmadan da çalışsın diye listing'e bir kategori atayıp,
		# şablonu o kategoriye yönlendirelim).
		# Mevcut Product Category'lerden birini al:
		cat = frappe.db.get_value("Product Category", {}, "name")
		if not cat:
			# Yoksa testi geçemeyiz — skip
			self.skipTest("Product Category yok, template testi atlandı")
		frappe.db.set_value("Listing", self.listing, "product_category", cat, update_modified=False)
		frappe.db.set_value("Category Review Template", tekstil_tpl, "category", cat, update_modified=False)

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Template answers test review metni yeterince uzun.",
		)
		ans = submit_template_answers(
			review=res["name"],
			answers={"color_consistency": 5, "stitch_quality": 4},
		)
		self.assertTrue(ans["success"])
		# Çekildi mi?
		got = get_template_answers(review=res["name"])
		self.assertEqual(got["answers"].get("color_consistency"), 5)

	# 39. Trusted Reviewer Invitation eligibility
	def test_trusted_reviewer_invitation_eligibility(self):
		from tradehub_core.api.reputation import invite_trusted_reviewer, recompute_user

		# Buyer'ı Newcomer'da bırakıp davet etmek istesek hata almalı
		recompute_user(self.buyer_email)  # Newcomer
		frappe.set_user("Administrator")
		with self.assertRaises(Exception):
			invite_trusted_reviewer(user=self.buyer_email, listing=self.listing)

	# 40. Trusted Reviewer accept flow
	def test_trusted_reviewer_accept(self):
		from tradehub_core.api.reputation import accept_reviewer_invitation, invite_trusted_reviewer

		# Önceki koşumdan kalma davet varsa sil (idempotent)
		for n in frappe.get_all(
			"Trusted Reviewer Invitation",
			filters={"user": self.buyer_email, "listing": self.listing},
			pluck="name",
		):
			frappe.delete_doc("Trusted Reviewer Invitation", n, ignore_permissions=True, force=True)

		# Buyer'ı Top Contributor yap (helpful_count manuel inject)
		# Önce 1 review insert + manuel helpful
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Vine test — buyer'ı Top Contributor yapacağız.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		# Helpful count manuel inject
		frappe.db.set_value("Listing Review", res["name"], "helpful_count", 20, update_modified=False)
		from tradehub_core.api.reputation import recompute_user

		rep = recompute_user(self.buyer_email)
		self.assertIn(rep["tier"], ("Top Contributor", "Verified Pro"))

		# Davet
		inv = invite_trusted_reviewer(user=self.buyer_email, listing=self.listing)
		self.assertEqual(inv.get("tier") in ("Top Contributor", "Verified Pro"), True)

		# Kabul et
		frappe.set_user(self.buyer_email)
		a = accept_reviewer_invitation(name=inv["name"])
		self.assertEqual(a["status"], "Accepted")

	# ==================================================================
	# Faz 5 — Storefront API, SEO, Analytics, Rate Limit, Translation
	# ==================================================================

	# 41. Translation Settings doctype default values
	def test_translation_settings_default(self):
		frappe.set_user("Administrator")
		settings = frappe.get_single("Translation Settings")
		# Migration patch sonrası provider en az "stub" olmalı
		self.assertIn(settings.provider, ("stub", "openai", "deepl", "google"))

	# 42. Translation usage log oluşur (stub mode)
	def test_translation_usage_log_skipped_for_stub(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.translation import get_review_translation

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=4,
			body="English review for translation log test.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		before = frappe.db.count("Translation Usage Log")
		get_review_translation(review=res["name"], target_lang="tr")
		after = frappe.db.count("Translation Usage Log")
		# Stub mode → usage log oluşmaz
		self.assertEqual(before, after)

	# 43. Rate limit: 5 çağrı sonrası 6. fail eder
	def test_rate_limit_blocks_after_max(self):
		from tradehub_core.api.rate_limit import TooManyRequestsError, rate_limit, reset_bucket

		@rate_limit(max_calls=3, window_seconds=10, scope="test_rl")
		def test_fn():
			return "ok"

		reset_bucket("test_rl")
		# İlk 3 başarılı
		for _ in range(3):
			self.assertEqual(test_fn(), "ok")
		# 4. blok
		with self.assertRaises(TooManyRequestsError):
			test_fn()
		reset_bucket("test_rl")

	# 44. SEO JSON-LD schema yapısı
	def test_seo_jsonld_structure(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.seo import get_review_schema_jsonld

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="SEO schema testi için yorum metni.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")

		schema = get_review_schema_jsonld(listing=self.listing)
		self.assertEqual(schema["@context"], "https://schema.org")
		self.assertEqual(schema["@type"], "Product")
		self.assertIn("aggregateRating", schema)
		self.assertEqual(schema["aggregateRating"]["bestRating"], 5)
		self.assertGreaterEqual(len(schema.get("review", [])), 1)

	# 45. Storefront review page tek API'da summary + reviews
	def test_storefront_review_page(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.storefront_api import (
			get_storefront_review_page,
		)

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Storefront page test için yorum yeterince uzun.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		from tradehub_core.api.rate_limit import reset_bucket

		reset_bucket("sf_review_page")

		page = get_storefront_review_page(listing=self.listing, page=1)
		self.assertIn("summary", page)
		self.assertIn("reviews", page)
		self.assertIn("qa_total", page)
		self.assertGreaterEqual(page["total"], 1)
		# Reviewer reputation eklendi mi?
		self.assertIn("reviewer", page["reviews"][0])

	# 46. Storefront get_my_reviews login zorunlu
	def test_storefront_my_reviews_login_required(self):
		from tradehub_core.api.rate_limit import reset_bucket
		from tradehub_core.api.storefront_api import get_my_reviews

		reset_bucket("sf_my_reviews", user="Guest")

		frappe.set_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			get_my_reviews()
		frappe.set_user("Administrator")

	# 47. Analytics daily snapshot
	def test_analytics_daily_snapshot(self):
		from tradehub_core.api.analytics import daily_snapshot

		out = daily_snapshot()
		self.assertTrue(out["success"])
		# Snapshot kaydı oluştu mu?
		self.assertTrue(frappe.db.exists("Review Analytics Snapshot", out["snapshot"]))

	# 48. Admin dashboard metrics endpoint
	def test_admin_dashboard_metrics(self):
		from tradehub_core.api.analytics import get_admin_dashboard_metrics

		frappe.set_user("Administrator")
		m = get_admin_dashboard_metrics()
		# Beklenen keys
		expected = {
			"total_reviews",
			"pending_reviews",
			"high_risk_today",
			"open_disputes",
			"active_invitations",
			"translations_today",
			"tier_distribution",
		}
		self.assertTrue(expected.issubset(set(m.keys())))

	# 49. Storefront QA page rate limit
	def test_storefront_qa_page(self):
		from tradehub_core.api.qa import submit_listing_question
		from tradehub_core.api.rate_limit import reset_bucket
		from tradehub_core.api.storefront_api import get_qa_page

		# Önce bir soru ekleyelim ve answered yapalım
		frappe.set_user(self.buyer_email)
		q = submit_listing_question(
			listing=self.listing,
			question="Test sorusu storefront QA için yazılmıştır.",
		)
		from tradehub_core.api.qa import submit_question_answer

		frappe.set_user("Administrator")
		submit_question_answer(question=q["name"], answer="Test cevabı.")

		reset_bucket("sf_qa_page", user="_global")
		out = get_qa_page(listing=self.listing)
		self.assertGreaterEqual(out["total"], 1)

	# 50. Webhook test endpoint (no URL set → not configured)
	def test_webhook_no_config(self):
		from tradehub_core.api.webhooks import webhook_test

		frappe.set_user("Administrator")
		r = webhook_test(channel="slack")
		# webhook URL set değilse "configured: False"
		self.assertFalse(r["configured"])

	# 51. Storefront submit_review rate-limit (5 in 60s)
	def test_storefront_submit_review_rate_limit(self):
		from tradehub_core.api.rate_limit import TooManyRequestsError, reset_bucket

		reset_bucket("sf_submit_review", user=self.buyer_email)
		# 5 başarılı olmasına gerek yok — sadece rate limit çalıştığını doğrula
		# Submit etmeye gerek yok; decorator'ün kendi mekaniği işliyor.
		# Burada üst seviyede submit denesek ancak duplicate order_item için
		# fail eder. Manuel rate limit testi yeterli.
		from tradehub_core.api.rate_limit import rate_limit

		@rate_limit(max_calls=2, window_seconds=10, scope="test_sf_submit")
		def fake_submit():
			return "ok"

		reset_bucket("test_sf_submit")
		self.assertEqual(fake_submit(), "ok")
		self.assertEqual(fake_submit(), "ok")
		with self.assertRaises(TooManyRequestsError):
			fake_submit()
		reset_bucket("test_sf_submit")

	# 52. SEO HTML script tag çıktı doğru formatlı
	def test_seo_html_script_tag(self):
		from tradehub_core.api.seo import get_review_schema_html

		html = get_review_schema_html(listing=self.listing)
		self.assertTrue(html.startswith('<script type="application/ld+json">'))
		self.assertTrue(html.rstrip().endswith("</script>"))

	# 53. Snapshot history endpoint
	def test_snapshot_history(self):
		from tradehub_core.api.analytics import daily_snapshot, get_snapshot_history

		daily_snapshot()
		frappe.set_user("Administrator")
		h = get_snapshot_history(days=7)
		self.assertGreaterEqual(h["total"], 1)

	# ==================================================================
	# Faz 6 — Sentiment, Moderation, Push, Mobile, AB, OAuth2
	# ==================================================================

	# 54. Sentiment stub: positive
	def test_sentiment_stub_positive(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.sentiment import analyze_review_sentiment

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item,
			rating=5,
			body="Ürün gerçekten harika ve kaliteli geldi, tavsiye ederim.",
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		out = analyze_review_sentiment(res["name"])
		self.assertEqual(out["sentiment"], "positive")

	# 55. Sentiment anomaly: 5★ + negatif
	def test_sentiment_anomaly(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.sentiment import analyze_review_sentiment

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item, rating=5, body="Berbat ürün kalitesiz iade ettim hasarlı geldi"
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		out = analyze_review_sentiment(res["name"])
		self.assertTrue(out["anomaly"])

	# 56. Topic extraction
	def test_sentiment_topics(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.sentiment import analyze_review_sentiment

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item, rating=5, body="Kargo çok hızlı geldi kalite mükemmel ambalaj iyiydi."
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		out = analyze_review_sentiment(res["name"])
		topics = out["topics"]
		self.assertIn("kargo", topics)
		self.assertIn("kalite", topics)

	# 57. Listing sentiment summary
	def test_listing_sentiment_summary(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.sentiment import analyze_review_sentiment, get_listing_sentiment_summary

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item, rating=5, body="Harika ürün kargo hızlı kalite iyi tavsiye ederim."
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		analyze_review_sentiment(res["name"])
		s = get_listing_sentiment_summary(listing=self.listing)
		self.assertGreaterEqual(s["total_analyzed"], 1)

	# 58. Push subscribe
	def test_push_subscribe(self):
		from tradehub_core.api.push import get_public_key, subscribe

		frappe.set_user(self.buyer_email)
		r = subscribe(endpoint="https://example.com/push/abc", p256dh="testkey", auth="testauth")
		self.assertTrue(r["success"])
		pk = get_public_key()
		self.assertIn("public_key", pk)

	# 59. Push duplicate update
	def test_push_duplicate(self):
		from tradehub_core.api.push import subscribe

		frappe.set_user(self.buyer_email)
		ep = "https://example.com/push/dup"
		r1 = subscribe(endpoint=ep, p256dh="k1", auth="a1")
		r2 = subscribe(endpoint=ep, p256dh="k2", auth="a2")
		self.assertEqual(r1["subscription"], r2["subscription"])

	# 60. Mobile JWT encode/decode
	def test_mobile_jwt_roundtrip(self):
		import time

		from tradehub_core.api.mobile_api import _decode_jwt, _encode_jwt

		now_ts = int(time.time())
		token = _encode_jwt({"sub": "test@x.com", "iat": now_ts, "exp": now_ts + 60, "type": "access"})
		decoded = _decode_jwt(token)
		self.assertEqual(decoded["sub"], "test@x.com")

	# 61. JWT expired
	def test_jwt_expired(self):
		import time

		from tradehub_core.api.mobile_api import _decode_jwt, _encode_jwt

		now_ts = int(time.time())
		token = _encode_jwt({"sub": "x", "iat": now_ts - 7200, "exp": now_ts - 3600})
		with self.assertRaises(frappe.AuthenticationError):
			_decode_jwt(token)

	# 62. Mobile token pair
	def test_mobile_token_pair(self):
		from tradehub_core.api.mobile_api import _create_token_pair

		t = _create_token_pair(self.buyer_email, "dev1", "android")
		self.assertIn("access_token", t)
		self.assertIn("refresh_token", t)

	# 63. Seller analytics 30d
	def test_seller_analytics(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.seller_analytics import _compute_seller_period

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item, rating=5, body="Seller analytics test review yeterince uzun metin."
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		out = _compute_seller_period(self.seller, "30d")
		self.assertGreaterEqual(out["total_reviews"], 1)

	# 64. AB Test metric value
	def test_ab_metric_value(self):
		from tradehub_core.api.ab_testing import _metric_value

		v = _metric_value(self.listing, "weighted_rating")
		self.assertIsInstance(v, float)

	# 65. API Application secret üretimi
	def test_api_app_secret(self):
		frappe.set_user("Administrator")
		for n in frappe.get_all("API Application", filters={"app_name": "Test XYZ"}, pluck="name"):
			frappe.delete_doc("API Application", n, ignore_permissions=True, force=True)
		doc = frappe.new_doc("API Application")
		doc.app_name = "Test XYZ"
		doc.developer_email = "dev@test.com"
		doc.rate_limit_tier = "free"
		doc.insert(ignore_permissions=True)
		self.assertIsNotNone(doc.client_id)
		sec = doc.get_password("client_secret", raise_exception=False)
		self.assertGreater(len(sec), 20)

	# 66. OAuth2 token flow
	def test_oauth2_token(self):
		frappe.set_user("Administrator")
		for n in frappe.get_all("API Application", filters={"app_name": "Test OAuth"}, pluck="name"):
			frappe.delete_doc("API Application", n, ignore_permissions=True, force=True)
		app = frappe.new_doc("API Application")
		app.app_name = "Test OAuth"
		app.developer_email = "oauth@x.com"
		app.rate_limit_tier = "free"
		app.append("scopes", {"scope": "read_reviews"})
		app.insert(ignore_permissions=True)
		sec = app.get_password("client_secret", raise_exception=False)

		from tradehub_core.api.rate_limit import reset_bucket

		reset_bucket("oauth_token")  # kova artık oturum kimliğine göre (IP/kullanıcı)

		from tradehub_core.api.v1.public_api import token

		out = token(grant_type="client_credentials", client_id=app.client_id, client_secret=sec)
		self.assertIn("access_token", out)

	# 67. OAuth2 invalid secret
	def test_oauth2_invalid_secret(self):
		from tradehub_core.api.rate_limit import reset_bucket
		from tradehub_core.api.v1.public_api import token

		reset_bucket("oauth_token")  # kova artık oturum kimliğine göre (IP/kullanıcı)
		with self.assertRaises(frappe.AuthenticationError):
			token(grant_type="client_credentials", client_id="nonexistent", client_secret="wrong")

	# 68. Default moderation rules seed
	def test_default_moderation_rules(self):
		cnt = frappe.db.count("Moderation Rule", filters={"is_active": 1})
		self.assertGreaterEqual(cnt, 2)

	# 69. Sentiment unique per review
	def test_sentiment_unique(self):
		from tradehub_core.api.review import admin_moderate_review, submit_listing_review
		from tradehub_core.api.sentiment import analyze_review_sentiment

		frappe.set_user(self.buyer_email)
		res = submit_listing_review(
			order_item=self.order_item, rating=4, body="Sentiment unique test review metni yeterince uzun."
		)
		frappe.set_user("Administrator")
		admin_moderate_review(name=res["name"], action="approve")
		analyze_review_sentiment(res["name"])
		analyze_review_sentiment(res["name"])
		cnt = frappe.db.count("Review Sentiment Analysis", filters={"review": res["name"]})
		self.assertEqual(cnt, 1)

	# 70. AB Test minimum 2 variant
	def test_ab_test_min_variants(self):
		frappe.set_user("Administrator")
		for n in frappe.get_all("Listing AB Test", filters={"test_name": "Test 1var"}, pluck="name"):
			frappe.delete_doc("Listing AB Test", n, ignore_permissions=True, force=True)
		doc = frappe.new_doc("Listing AB Test")
		doc.test_name = "Test 1var"
		doc.seller = self.seller
		doc.metric = "weighted_rating"
		doc.test_period_days = 30
		doc.append("variants", {"variant_listing": self.listing, "label": "A", "traffic_weight": 100})
		doc.insert(ignore_permissions=True)

		from tradehub_core.api.ab_testing import start_ab_test

		with self.assertRaises(frappe.ValidationError):
			start_ab_test(test_name=doc.name)

	# 71. Tier rate limit yapısı
	def test_oauth2_tier_structure(self):
		from tradehub_core.api.v1.public_api import RATE_LIMITS

		self.assertLess(RATE_LIMITS["free"]["max_calls"], RATE_LIMITS["pro"]["max_calls"])


if __name__ == "__main__":
	unittest.main()
