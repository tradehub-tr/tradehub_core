import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ListingQuestionAnswer(Document):
	def before_insert(self):
		# Form'dan direkt insert için: submitted_at, responder default
		if not self.submitted_at:
			self.submitted_at = now_datetime()
		if not self.responder:
			self.responder = frappe.session.user
		# Form'dan responder_type belirlenmemişse otomatik tespit
		if not self.responder_type:
			self._auto_set_responder_type()

	def validate(self):
		# Form save sırasında da responder_type bot ise yeniden hesapla
		if not self.responder_type:
			self._auto_set_responder_type()

	def after_insert(self):
		from tradehub_core.api.qa import _recompute_question_answer_count

		if self.question:
			_recompute_question_answer_count(self.question)

	def on_trash(self):
		from tradehub_core.api.qa import _recompute_question_answer_count

		if self.question:
			_recompute_question_answer_count(self.question)

	def _auto_set_responder_type(self):
		"""Question'in listing'inden seller_user'ı bul, responder ile karşılaştır."""
		if not self.question or not self.responder:
			return
		listing = frappe.db.get_value("Listing Question", self.question, "listing")
		if not listing:
			return
		seller_profile = frappe.db.get_value("Listing", listing, "seller_profile")
		seller_user = (
			frappe.db.get_value("Admin Seller Profile", seller_profile, "user") if seller_profile else None
		)
		# Admin kontrolü
		roles = set(frappe.get_roles(self.responder))
		if self.responder == "Administrator" or roles & {"System Manager", "Marketplace Admin"}:
			self.responder_type = "admin"
			self.is_seller_answer = 0
		elif seller_user and seller_user == self.responder:
			self.responder_type = "seller"
			self.is_seller_answer = 1
		else:
			self.responder_type = "buyer"
			self.is_seller_answer = 0
