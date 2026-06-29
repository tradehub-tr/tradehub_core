"""Listing Review controller — ürün bazlı yorum (Faz 1).

Validation kuralları, status lifecycle ve cache invalidation burada toplanır.
Hooks (after_insert/on_update/on_trash) ayrıca tradehub_core.api.review
modülünden çağrılır — controller sadece doc-level tutarlılığa odaklanır.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, time_diff_in_hours

from tradehub_core.utils.notify import notify

EDITABLE_HOURS = 24
MIN_BODY_LENGTH = 10
MAX_BODY_LENGTH = 5000
MAX_TITLE_LENGTH = 140
ORDER_DELIVERED_STATUSES = {"Tamamlandı", "Kargoda"}
KYB_VERIFIED_STATUS = "Verified"

# Faz 2 sabitleri
MAX_IMAGES = 10
ASPECT_FIELDS = (
	"product_quality_rating",
	"service_rating",
	"shipping_rating",
	"spec_match_rating",
	"documentation_rating",
)
SELLER_REPLY_EDITABLE_HOURS = 24


class ListingReview(Document):
	def validate(self):
		self._normalize_text_fields()
		self._validate_rating()
		self._validate_aspect_ratings()
		self._validate_body_length()
		self._validate_title_length()
		self._validate_order_chain()
		self._populate_seller_from_listing()
		self._populate_reviewer_from_user()
		self._guard_self_review()
		self._guard_duplicate_review()
		self._populate_verification_flags()
		self._validate_images_limit()
		self._enforce_edit_window()
		self._track_seller_reply_changes()

	def before_insert(self):
		if not self.submitted_at:
			self.submitted_at = now_datetime()
		# Sadece admin/system manager bypass edebilir; normal akışta her insert Pending.
		if not self._actor_is_admin():
			self.status = "Pending"
			self.published_at = None
		self.edit_count = 0
		self.updated_at = None

	def after_insert(self):
		self._notify_seller_new_review()

	def on_update(self):
		old = self.get_doc_before_save()
		if not old:
			return
		if old.status != self.status:
			self._on_status_changed(old.status, self.status)
		# Approved kayıtta içerik değişti — agregasyonu yenile (rating güncellenmiş olabilir)
		elif self.status == "Approved" and (old.rating != self.rating):
			_recompute_listing_rating(self.listing)

		# Faz 4: content (title/body) değiştiyse Review Translation cache'lerini sil
		content_changed = (old.title or "") != (self.title or "") or (old.body or "") != (self.body or "")
		if content_changed:
			try:
				for n in frappe.get_all(
					"Review Translation",
					filters={"review": self.name},
					pluck="name",
				):
					frappe.delete_doc(
						"Review Translation",
						n,
						ignore_permissions=True,
						force=True,
					)
				# is_translation_available cache reset
				frappe.db.set_value(
					"Listing Review",
					self.name,
					"is_translation_available",
					0,
					update_modified=False,
				)
			except Exception:
				pass

	def on_trash(self):
		# Order Item.has_review temizlenir
		if self.order_item:
			frappe.db.set_value(
				"Order Item",
				self.order_item,
				{"has_review": 0, "review": None},
				update_modified=False,
			)

		# Cascade: bu review'e bağlı tüm yan kayıtları sil (link guard'ı atlat).
		# Frappe normalde Link veren child kayıt varsa parent'ı silmiyor;
		# bu yüzden manuel temizlik yapıyoruz.
		for dt in ("Review Risk Score", "Review Helpful Vote", "Review Abuse Report"):
			if not frappe.db.table_exists(f"tab{dt}"):
				continue
			for n in frappe.get_all(dt, filters={"review": self.name}, pluck="name"):
				try:
					frappe.delete_doc(dt, n, ignore_permissions=True, force=True)
				except Exception:
					frappe.db.sql(f"DELETE FROM `tab{dt}` WHERE name = %s", (n,))

		# on_trash kayıt fiziksel silinmeden önce çalışır → kendi name'imizi dışla
		from tradehub_core.api.review import recompute_listing_rating

		recompute_listing_rating(self.listing, exclude_review_name=self.name)

	# ------------------------------------------------------------------
	# Validation helpers
	# ------------------------------------------------------------------
	def _normalize_text_fields(self):
		if self.body:
			self.body = self.body.strip()
		if self.title:
			self.title = self.title.strip()

	def _validate_rating(self):
		try:
			rating = int(self.rating) if self.rating is not None else 0
		except (ValueError, TypeError):
			frappe.throw(_("Puan 1 ile 5 arasında bir tam sayı olmalıdır"))
		if rating < 1 or rating > 5:
			frappe.throw(_("Puan 1 ile 5 arasında olmalıdır"))
		self.rating = rating

	def _validate_aspect_ratings(self):
		# 5 boyut puanı opsiyonel — ama girilmişse 1..5 aralığında olmalı
		for field in ASPECT_FIELDS:
			value = self.get(field)
			if value in (None, "", 0):
				self.set(field, None)
				continue
			try:
				v = int(value)
			except (ValueError, TypeError):
				frappe.throw(_("{0} 1 ile 5 arasında olmalı").format(field))
			if v < 1 or v > 5:
				frappe.throw(_("{0} 1 ile 5 arasında olmalı").format(field))
			self.set(field, v)

	def _validate_images_limit(self):
		images = self.get("images") or []
		if len(images) > MAX_IMAGES:
			frappe.throw(_("En fazla {0} görsel yükleyebilirsiniz").format(MAX_IMAGES))

	def _validate_body_length(self):
		body = self.body or ""
		if len(body) < MIN_BODY_LENGTH:
			frappe.throw(_("Yorum en az {0} karakter olmalıdır").format(MIN_BODY_LENGTH))
		if len(body) > MAX_BODY_LENGTH:
			frappe.throw(_("Yorum en fazla {0} karakter olabilir").format(MAX_BODY_LENGTH))

	def _validate_title_length(self):
		if self.title and len(self.title) > MAX_TITLE_LENGTH:
			frappe.throw(_("Başlık en fazla {0} karakter olabilir").format(MAX_TITLE_LENGTH))

	def _validate_order_chain(self):
		if not (self.order and self.order_item and self.listing):
			frappe.throw(_("Sipariş, sipariş kalemi ve ürün zorunludur"))

		oi = frappe.db.get_value(
			"Order Item",
			self.order_item,
			["parent", "parenttype", "listing"],
			as_dict=True,
		)
		if not oi:
			frappe.throw(_("Sipariş kalemi bulunamadı"), frappe.DoesNotExistError)
		if oi.parenttype != "Order" or oi.parent != self.order:
			frappe.throw(_("Sipariş kalemi bu siparişe ait değil"))
		if oi.listing != self.listing:
			frappe.throw(_("Sipariş kalemi seçilen ürüne ait değil"))

		order_row = frappe.db.get_value(
			"Order",
			self.order,
			["buyer", "status"],
			as_dict=True,
		)
		if not order_row:
			frappe.throw(_("Sipariş bulunamadı"), frappe.DoesNotExistError)
		if order_row.status not in ORDER_DELIVERED_STATUSES:
			frappe.throw(_("Yalnızca tamamlanmış siparişlere yorum yapılabilir"))

		# reviewer_user, sipariş sahibinin User'ıyla eşleşmeli
		if not self.reviewer_user:
			# session'dan al
			self.reviewer_user = frappe.session.user if frappe.session.user != "Guest" else None
		if not self.reviewer_user:
			frappe.throw(_("Yorum yapmak için giriş yapmalısınız"), frappe.AuthenticationError)
		if order_row.buyer != self.reviewer_user and not self._actor_is_admin():
			frappe.throw(_("Yalnızca siparişi veren alıcı yorum yapabilir"), frappe.PermissionError)

	def _populate_seller_from_listing(self):
		seller = frappe.db.get_value("Listing", self.listing, "seller_profile")
		if not seller:
			frappe.throw(_("Ürünün satıcısı bulunamadı"))
		self.seller = seller

	def _populate_reviewer_from_user(self):
		# Sprint 2 — reviewer = User Profile.name (autoname=field:user; bu reviewer_user'a eşit)
		up_name = frappe.db.get_value("User Profile", {"user": self.reviewer_user}, "name")
		self.reviewer = up_name

		display = None
		if up_name:
			up = frappe.db.get_value(
				"User Profile",
				up_name,
				["company_name", "full_name", "country"],
				as_dict=True,
			)
			if up:
				company = (up.company_name or "").strip()
				name = (up.full_name or "").strip()
				country = (up.country or "").strip()
				base = company or name or ""
				display = f"{base} ({country})" if base and country else base
		if not display:
			# fallback: User.full_name
			display = frappe.db.get_value("User", self.reviewer_user, "full_name") or self.reviewer_user
		self.reviewer_display_name = display

	def _guard_self_review(self):
		if not self.seller:
			return
		seller_user = frappe.db.get_value("Admin Seller Profile", self.seller, "user")
		if seller_user and seller_user == self.reviewer_user:
			frappe.throw(_("Kendi ürününüze yorum yapamazsınız"), frappe.PermissionError)

	def _guard_duplicate_review(self):
		if not self.order_item:
			return
		filters = {"order_item": self.order_item}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Listing Review", filters):
			frappe.throw(_("Bu sipariş kalemi için zaten bir yorum yapılmış"))

	def _populate_verification_flags(self):
		# Verified Purchase: order_item zaten zorunlu — her zaman 1
		self.is_verified_purchase = 1

		# KYB doğrulanmış buyer mı?
		kyb = 0
		if self.reviewer_user:
			kyb_status = frappe.db.get_value("KYB Verification", {"user": self.reviewer_user}, "status")
			if kyb_status == KYB_VERIFIED_STATUS:
				kyb = 1
		self.is_kyb_verified = kyb

	def _enforce_edit_window(self):
		if self.is_new():
			return
		# Sistem-içi çağrılar (ör: recompute_abuse_count_and_threshold,
		# scheduled jobs) bu kontrolü baypaslar.
		if getattr(self.flags, "system_save", False):
			return
		old = self.get_doc_before_save()
		if not old:
			return

		actor_admin = self._actor_is_admin()

		# İçerik düzenlemesi: rating/title/body/aspect/video
		content_changed = (
			old.rating != self.rating
			or (old.title or "") != (self.title or "")
			or (old.body or "") != (self.body or "")
			or any((old.get(f) or 0) != (self.get(f) or 0) for f in ASPECT_FIELDS)
			or (old.video_url or "") != (self.video_url or "")
		)

		# Buyer içerik düzenlemesi → 24 saat penceresi + yeniden moderasyon.
		# Her düzenleme yorumu tekrar onaya soktuğu (status=Pending) için ayrı bir
		# "max edit" limiti uygulanmaz; pencere içinde tekrar tekrar düzenlenebilir.
		if content_changed and not actor_admin:
			if old.submitted_at:
				hours = time_diff_in_hours(now_datetime(), old.submitted_at)
				if hours > EDITABLE_HOURS:
					frappe.throw(
						_("Yorum yalnızca gönderimden sonraki {0} saat içinde düzenlenebilir").format(
							EDITABLE_HOURS
						)
					)
			self.edit_count = (old.edit_count or 0) + 1
			self.updated_at = now_datetime()
			# Düzenlenen içerik yeniden moderasyona girsin (Approved/Hidden → Pending)
			self.status = "Pending"

		# Status, published_at, rejected_reason yalnız admin değiştirebilir.
		# İstisna: buyer içerik düzenlemesinin tetiklediği sistemsel "Pending"
		# geçişi (yukarıda) serbest — kontrollü re-moderasyon akışı.
		admin_only_fields = {"status", "published_at", "rejected_reason"}
		for f in admin_only_fields:
			if (old.get(f) or "") != (self.get(f) or "") and not actor_admin:
				if f == "status" and content_changed and self.status == "Pending":
					continue
				frappe.throw(_("Bu alanı yalnızca yöneticiler değiştirebilir: {0}").format(f))

		# Faz 2: helpful/abuse cache'leri ve seller_reply_* alanları
		# yalnız sistem (controller / vote-handler) tarafından güncellenir
		# — buyer'ın bu alanları formdan değiştirmesini engelle.
		read_only_cache_fields = {
			"helpful_count",
			"not_helpful_count",
			"abuse_report_count",
			"seller_reply_at",
			"seller_reply_by",
			"seller_reply_within_hours",
		}
		for f in read_only_cache_fields:
			if (old.get(f) or 0) != (self.get(f) or 0) and not actor_admin:
				# Buyer formdan değiştiremez; admin/sistem geçer
				if not self._actor_is_seller_owner():
					self.set(f, old.get(f))

	# ------------------------------------------------------------------
	# Status transitions
	# ------------------------------------------------------------------
	def _on_status_changed(self, old_status: str, new_status: str):
		if new_status == "Approved":
			if not self.published_at:
				frappe.db.set_value(
					"Listing Review",
					self.name,
					"published_at",
					now_datetime(),
					update_modified=False,
				)
			# Order Item.has_review = 1
			if self.order_item:
				frappe.db.set_value(
					"Order Item",
					self.order_item,
					{"has_review": 1, "review": self.name},
					update_modified=False,
				)
			_recompute_listing_rating(self.listing)
			self._notify_seller_published()
			self._notify_buyer_published()
		elif new_status == "Hidden":
			_recompute_listing_rating(self.listing)
			self._notify_seller_hidden()
			self._notify_buyer_hidden()
		elif new_status == "Rejected":
			# Rejected her zaman agregasyon dışıdır; Approved -> Rejected geçişinde
			# review_count/average_rating bayat kalmasın diye burada da recompute
			# şart (bu elif, alttaki "Approved'dan çıktı" dalını gölgeliyordu).
			_recompute_listing_rating(self.listing)
			self._notify_buyer_rejected()
		elif old_status == "Approved" and new_status != "Approved":
			# Approved -> başka bir state (ör. Pending): agregasyondan çıkar
			_recompute_listing_rating(self.listing)

	# ------------------------------------------------------------------
	# Notifications
	# ------------------------------------------------------------------
	def _notify_seller_new_review(self):
		seller_user = (
			frappe.db.get_value("Admin Seller Profile", self.seller, "user") if self.seller else None
		)
		if not seller_user:
			return
		notify(
			recipient_user=seller_user,
			recipient_role="seller",
			type="review",
			title=_("Yeni Ürün Yorumu (Moderasyonda)"),
			message=_("{0} ürünü için yeni bir yorum geldi.").format(self.listing),
			action_url="/review-moderation",
			reference_doctype="Listing Review",
			reference_name=self.name,
		)

	def _notify_seller_published(self):
		seller_user = (
			frappe.db.get_value("Admin Seller Profile", self.seller, "user") if self.seller else None
		)
		if not seller_user:
			return
		notify(
			recipient_user=seller_user,
			recipient_role="seller",
			type="review",
			title=_("Yorum Yayınlandı"),
			message=_("Ürünleriniz için bir yorum yayına alındı."),
			action_url="/review-moderation",
			reference_doctype="Listing Review",
			reference_name=self.name,
		)

	def _notify_seller_hidden(self):
		seller_user = (
			frappe.db.get_value("Admin Seller Profile", self.seller, "user") if self.seller else None
		)
		if not seller_user:
			return
		notify(
			recipient_user=seller_user,
			recipient_role="seller",
			type="review",
			title=_("Yorum Gizlendi"),
			message=_("Bir yorum moderasyon nedeniyle gizlendi."),
			action_url="/review-moderation",
			reference_doctype="Listing Review",
			reference_name=self.name,
		)

	def _notify_buyer_published(self):
		if not self.reviewer_user:
			return
		notify(
			recipient_user=self.reviewer_user,
			recipient_role="buyer",
			type="review",
			title=_("Yorumunuz Yayınlandı"),
			message=_("Yorumunuz onaylandı ve yayına alındı."),
			action_url="/account/reviews",
			reference_doctype="Listing Review",
			reference_name=self.name,
		)

	def _notify_buyer_rejected(self):
		if not self.reviewer_user:
			return
		reason = self.rejected_reason or _("Topluluk kurallarına uygun değil.")
		notify(
			recipient_user=self.reviewer_user,
			recipient_role="buyer",
			type="review",
			title=_("Yorumunuz Reddedildi"),
			message=str(reason),
			action_url="/account/reviews",
			reference_doctype="Listing Review",
			reference_name=self.name,
		)

	def _notify_buyer_hidden(self):
		if not self.reviewer_user:
			return
		notify(
			recipient_user=self.reviewer_user,
			recipient_role="buyer",
			type="review",
			title=_("Yorumunuz Gizlendi"),
			message=_("Yorumunuz şikayet üzerine geçici olarak gizlendi."),
			action_url="/account/reviews",
			reference_doctype="Listing Review",
			reference_name=self.name,
		)

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------
	@staticmethod
	def _actor_is_admin() -> bool:
		user = frappe.session.user
		if user == "Administrator":
			return True
		roles = set(frappe.get_roles(user))
		return bool(roles & {"System Manager", "Marketplace Admin"})

	def _actor_is_seller_owner(self) -> bool:
		"""Form'u kaydeden kullanıcı, bu yorumun seller'ının user'ı mı?"""
		if not self.seller:
			return False
		seller_user = frappe.db.get_value("Admin Seller Profile", self.seller, "user")
		return bool(seller_user and seller_user == frappe.session.user)

	# ------------------------------------------------------------------
	# Seller reply lifecycle (Faz 2)
	# ------------------------------------------------------------------
	def _track_seller_reply_changes(self):
		"""Seller reply alanı değişti mi? Değiştiyse who/when/SLA stamp'le."""
		if self.is_new():
			# Insert sırasında reply olmamalı (buyer açıyor)
			return
		old = self.get_doc_before_save()
		if not old:
			return

		old_reply = (old.seller_reply or "").strip()
		new_reply = (self.seller_reply or "").strip()
		if old_reply == new_reply:
			return

		# Değişim oldu: yeni reply mı, edit mi, silindi mi?
		from frappe.utils import time_diff_in_hours

		actor = frappe.session.user
		now = now_datetime()

		if not new_reply:
			# Reply silindi
			self.seller_reply_at = None
			self.seller_reply_by = None
			self.seller_reply_within_hours = None
			return

		# Yeni reply yazıldı
		if not old_reply:
			# İlk kez yazıldı
			if not self._actor_is_admin() and not self._actor_is_seller_owner():
				frappe.throw(_("Sadece satıcı bu yoruma yanıt yazabilir"), frappe.PermissionError)
			self.seller_reply_at = now
			self.seller_reply_by = actor
			# SLA: review submit'ten reply'a kaç saat geçti
			if old.submitted_at:
				self.seller_reply_within_hours = round(time_diff_in_hours(now, old.submitted_at), 1)
			return

		# Reply düzenlendi
		if not self._actor_is_admin() and not self._actor_is_seller_owner():
			frappe.throw(_("Sadece satıcı kendi yanıtını düzenleyebilir"), frappe.PermissionError)
		if old.seller_reply_at:
			edit_window = time_diff_in_hours(now, old.seller_reply_at)
			if edit_window > SELLER_REPLY_EDITABLE_HOURS and not self._actor_is_admin():
				frappe.throw(
					_("Yanıt yalnızca yazıldıktan sonra {0} saat içinde düzenlenebilir").format(
						SELLER_REPLY_EDITABLE_HOURS
					)
				)


def _recompute_listing_rating(listing_name: str | None):
	"""Yardımcı: tek bir Listing için rating cache'ini yeniden hesaplar.

	Modül içi kullanım için thin wrapper — ana iş tradehub_core.api.review'da.
	"""
	if not listing_name:
		return
	from tradehub_core.api.review import recompute_listing_rating

	recompute_listing_rating(listing_name)
