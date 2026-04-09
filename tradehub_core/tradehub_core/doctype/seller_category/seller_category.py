import frappe
from frappe import _
from frappe.model.document import Document
from tradehub_core.utils.notify import notify


def _is_admin():
    user = frappe.session.user
    return user == "Administrator" or "System Manager" in frappe.get_roles(user)


class SellerCategory(Document):
    def before_insert(self):
        if not _is_admin():
            self.status = "Pending"

    def validate(self):
        if _is_admin():
            return
        # Satıcı sadece kendi profiline kategori ekleyebilir
        seller_profile = _get_seller_profile()
        if not seller_profile:
            frappe.throw(_("Satıcı profili bulunamadı."))
        if self.seller and self.seller != seller_profile:
            frappe.throw(_("Başka bir satıcı adına kategori ekleyemezsiniz."))
        self.seller = seller_profile
        # Satıcı status'ü değiştiremez (Pending'e dönüş hariç — düzenleme sonrası yeniden onay)
        if not self.is_new():
            old_status = frappe.db.get_value("Seller Category", self.name, "status")
            if old_status != self.status and self.status in ("Active", "Rejected"):
                self.status = old_status

    def on_update(self):
        self._send_status_notifications()

    def _send_status_notifications(self):
        """Kategori onay/red durumunda satıcıya bildirim gönder."""
        old = self.get_doc_before_save()
        if not old or old.status == self.status:
            return
        if not self.seller:
            return
        seller_user = frappe.db.get_value("Admin Seller Profile", self.seller, "user") if self.seller else None
        if not seller_user:
            return

        category_name = self.category_name or self.name
        if self.status == "Active" and old.status == "Pending":
            notify(
                recipient_user=seller_user,
                recipient_role="seller",
                type="listing",
                title=_("Kategori Onaylandı"),
                message=_("{0} kategoriniz onaylandı.").format(category_name),
                action_url="/seller/dashboard?tab=categories",
                reference_doctype="Seller Category",
                reference_name=self.name,
            )
        elif self.status == "Rejected":
            notify(
                recipient_user=seller_user,
                recipient_role="seller",
                type="listing",
                title=_("Kategori Reddedildi"),
                message=_("{0} kategoriniz reddedildi.").format(category_name),
                action_url="/seller/dashboard?tab=categories",
                reference_doctype="Seller Category",
                reference_name=self.name,
            )


def _get_seller_profile():
    user = frappe.session.user
    profile = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
    if not profile:
        profile = frappe.db.get_value("Admin Seller Profile", {"email": user}, "name")
    return profile
