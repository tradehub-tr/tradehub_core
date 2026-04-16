import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.utils.notify import notify


class SellerReview(Document):
	def after_insert(self):
		self._notify_seller_new_review()

	def on_update(self):
		self._notify_review_status_change()

	def _notify_seller_new_review(self):
		if not self.seller:
			return
		seller_user = (
			frappe.db.get_value("Admin Seller Profile", self.seller, "user") if self.seller else None
		)
		if not seller_user:
			return
		rating = self.rating or 0
		notify(
			recipient_user=seller_user,
			recipient_role="seller",
			type="review",
			title=_("Yeni Değerlendirme"),
			message=_("{0} yıldız değerlendirme aldınız.").format(rating),
			action_url="/seller/dashboard?tab=reviews",
			reference_doctype="Seller Review",
			reference_name=self.name,
		)

	def _notify_review_status_change(self):
		"""Değerlendirme gizlendiğinde veya yayınlandığında satıcıya bildirim."""
		old = self.get_doc_before_save()
		if not old or old.status == self.status:
			return
		if not self.seller:
			return
		seller_user = (
			frappe.db.get_value("Admin Seller Profile", self.seller, "user") if self.seller else None
		)
		if not seller_user:
			return

		if self.status == "Hidden" and old.status == "Published":
			notify(
				recipient_user=seller_user,
				recipient_role="seller",
				type="review",
				title=_("Değerlendirme Gizlendi"),
				message=_("Bir değerlendirme moderasyon nedeniyle gizlendi."),
				action_url="/seller/dashboard?tab=reviews",
				reference_doctype="Seller Review",
				reference_name=self.name,
			)
		elif self.status == "Published" and old.status == "Hidden":
			notify(
				recipient_user=seller_user,
				recipient_role="seller",
				type="review",
				title=_("Değerlendirme Yayınlandı"),
				message=_("Gizlenmiş bir değerlendirme tekrar yayınlandı."),
				action_url="/seller/dashboard?tab=reviews",
				reference_doctype="Seller Review",
				reference_name=self.name,
			)
