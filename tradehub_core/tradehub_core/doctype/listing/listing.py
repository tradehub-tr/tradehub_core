import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, flt, cint
import hashlib
import time

# Satıcının onay sonrası değiştirebileceği durumlar
SELLER_ALLOWED_STATUSES = {"Active", "Paused", "Out of Stock"}
# Sadece admin'in ayarlayabileceği durumlar
ADMIN_ONLY_STATUSES = {"Pending", "Rejected", "Draft"}


def _is_admin():
    return frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles()


def _get_seller_profile_from_session():
    user = frappe.session.user
    profile = frappe.db.get_value("Admin Seller Profile", {"owner": user}, "name")
    if not profile:
        profile = frappe.db.get_value("Admin Seller Profile", {"email": user}, "name")
    return profile or ""


class Listing(Document):
    def before_insert(self):
        if not self.listing_code:
            self.listing_code = self.generate_listing_code()
        # Satıcı tarafından eklenen listing her zaman Pending başlar
        if not _is_admin():
            self.status = "Pending"
            # Satıcı kendi profiline otomatik atanır
            if not self.seller_profile:
                self.seller_profile = _get_seller_profile_from_session()

    def validate(self):
        self.calculate_available_qty()
        self.validate_pricing()
        self.validate_pricing_tiers()
        self._validate_status_change()

    def _validate_status_change(self):
        if _is_admin():
            return  # Admin her değişikliği yapabilir
        # Satıcı: sadece onaylanmış listing'de izinli statüler arasında geçiş yapabilir
        old_status = frappe.db.get_value("Listing", self.name, "status") if not self.is_new() else "Pending"
        new_status = self.status
        if old_status == "Rejected":
            # Reddedilmiş listing satıcı tarafından düzenlenip kaydedilince tekrar onaya gönderilir
            self.status = "Pending"
            self.rejection_reason = ""
        elif old_status in ADMIN_ONLY_STATUSES:
            # Pending/Draft — satıcı durum değiştiremez
            self.status = old_status
            if new_status != old_status:
                frappe.throw(_("Bu listing henüz admin tarafından onaylanmamış. Durum değiştirilemez."))
        elif new_status not in SELLER_ALLOWED_STATUSES:
            frappe.throw(_("Geçersiz durum. İzin verilen durumlar: Active, Paused, Out of Stock"))

    def on_update(self):
        if self.status == "Active" and not self.published_at:
            self.db_set("published_at", now_datetime())

    def generate_listing_code(self):
        hash_input = f"{self.title}-{time.time()}"
        return "LST-" + hashlib.md5(hash_input.encode()).hexdigest()[:8].upper()

    def calculate_available_qty(self):
        self.available_qty = max(0, flt(self.stock_qty) - flt(self.reserved_qty))

    def validate_pricing(self):
        """Enforce the only hard rule on pricing fields: selling cannot exceed
        listing.

        The seller's day-to-day price (selling_price) is never auto-overwritten
        by the system. discount_percentage is purely a campaign trigger:

          - dp = 0  → no campaign, listing is not in Top Deals
          - dp > 0  → campaign active. The "campaign price" the customer sees
                      is selling_price × (1 − dp/100), computed at *display
                      time only* (see _format_listing_card in api/listing.py).
                      selling_price itself stays untouched, so when the seller
                      ends the campaign by setting dp back to 0, their normal
                      price is automatically restored on the storefront.
        """
        listing_price = flt(self.base_price)
        selling_price = flt(self.selling_price)

        if listing_price and selling_price and selling_price > listing_price:
            frappe.throw(_("Satış fiyatı Listeleme fiyatından büyük olamaz"))

    def validate_pricing_tiers(self):
        if not self.b2b_enabled or not self.pricing_tiers:
            return
        prev_max = 0
        for tier in sorted(self.pricing_tiers, key=lambda t: flt(t.min_qty)):
            min_qty = flt(tier.min_qty)
            max_qty = flt(tier.max_qty)
            if min_qty <= prev_max:
                frappe.throw(f"Pricing tier overlap: min_qty {min_qty} overlaps with previous tier")
            if max_qty and max_qty < min_qty:
                frappe.throw(f"Max quantity must be >= min quantity in pricing tier")
            prev_max = max_qty or float('inf')

    def get_price_for_qty(self, qty=1):
        if self.b2b_enabled and self.pricing_tiers:
            for tier in sorted(self.pricing_tiers, key=lambda t: t.min_qty, reverse=True):
                if qty >= tier.min_qty:
                    return tier.price
        return self.selling_price

    def increment_view_count(self):
        frappe.db.set_value("Listing", self.name, "view_count", (self.view_count or 0) + 1)
