import hashlib
import time

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from tradehub_core.utils.content_i18n import sync_content_translations
from tradehub_core.utils.notify import notify

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
		sync_content_translations(self)
		self._validate_seller_sku()
		self._resolve_attribute_links()
		self._ensure_primary_image()
		self.calculate_available_qty()
		self.validate_pricing()
		self.validate_stock()
		self.validate_pricing_tiers()
		self._validate_status_change()
		self._validate_variant_defaults()
		self._validate_variant_pricing()
		self._validate_seo_content()
		self._calculate_completeness()
		self._set_storefront_visible()

	def _validate_seller_sku(self):
		"""Satıcı stok kodu mağaza içinde benzersiz (MOGEM-665 · 1. aşama).

		Ürün API'sinin tamamı `(seller_profile, seller_sku)` eşleşmesine dayanır;
		aynı mağazada aynı kodla iki ürün olursa güncelleme rastgele birine gider.
		Kod kırpılır, boş kod NULL yazılır (boşlar birbirini engellemez); büyük/
		küçük harf farkı aynı kod sayılır (DB collation da öyle, bkz. patch
		v15_9_57 bileşik benzersiz indeks — Python kontrolü atlansa bile DB durdurur).
		"""
		sku = (self.seller_sku or "").strip() if isinstance(self.seller_sku, str) else self.seller_sku
		self.seller_sku = sku or None
		if not self.seller_sku or not self.seller_profile:
			return
		filters = {"seller_profile": self.seller_profile, "seller_sku": self.seller_sku}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		mevcut = frappe.db.get_value("Listing", filters, "name")
		if mevcut:
			frappe.throw(
				_("Bu stok kodu ({0}) mağazanızda zaten kullanılıyor: {1}").format(self.seller_sku, mevcut),
				frappe.ValidationError,
			)

	def _validate_seo_content(self):
		"""SEO kuralı: ürün adı/açıklaması min uzunlukta ve emojisiz olmalı.

		Toplu yükleme de aynı pipeline'a girer (bulk_import.validator ayrıca
		yükleme öncesi satır-bazlı kontrol eder). Eski kataloğu kırmamak için
		yalnız YENİ kayıtta ya da ilgili alan DEĞİŞTİĞİNDE zorlanır; böylece
		mevcut ürünün fiyat/stok düzenlemesi engellenmez, başlığı kısaltılırsa
		veya emoji eklenirse engellenir.

		Test/migrate/patch/install bağlamlarında ATLANIR: mevcut testler ve
		veri taşımaları kısa başlıklı listing oluşturabiliyor; kural yalnız
		gerçek kullanıcı yükleme yollarında (seller formu + toplu import)
		geçerli olsun. Toplu import ayrıca yükleme öncesi satır-bazlı kontrol
		eder (bulk_import.validator)."""
		flags = frappe.flags
		if (
			flags.in_test
			or flags.in_migrate
			or flags.in_patch
			or flags.in_install
			or flags.in_setup_wizard
		):
			return

		from tradehub_core.utils.seo_content import check_description, check_title

		if self.is_new() or self.has_value_changed("title"):
			ok, msg = check_title(self.title)
			if not ok:
				frappe.throw(msg, title=_("SEO Ürün Adı Kuralı"))

		if self.is_new() or self.has_value_changed("description"):
			ok, msg = check_description(self.description)
			if not ok:
				frappe.throw(msg, title=_("SEO Ürün Açıklaması Kuralı"))

	def _set_storefront_visible(self):
		"""Denormalize is_visible + status → tek eşitlik kolonu `storefront_visible`.

		Storefront sorguları `is_visible=1 AND status IN('Active','Out of Stock')`
		yerine `storefront_visible=1` ile filtreler → (storefront_visible, <sort>)
		index'i filesort'suz, index-ordered tarama sağlar (2-değerli status IN
		filesort'a zorluyordu). is_visible/status'un tüm validate mutasyonlarından
		SONRA çağrılır ki değer nihai duruma göre hesaplansın.

		Dunning drift guard (AC-9): mağazanın Store Subscription status'u
		'suspended' iken herhangi bir save (admin/Desk dahil) formülü yeniden
		hesaplayıp hide_store_listings'in yazdığı 0'ı sessizce 1'e çevirmesin
		diye storefront_visible 0'a sabitlenir. Tek frappe.db.get_value maliyeti
		yalnız formülün 1 döndüğü save'lerde ödenir (hot path değil)."""
		from tradehub_core.api.listing import STOREFRONT_VISIBLE_STATUSES

		visible = 1 if (self.is_visible and self.status in STOREFRONT_VISIBLE_STATUSES) else 0
		if visible and self.seller_profile:
			from tradehub_core.entitlement.core import get_subscription_status

			if get_subscription_status(self.seller_profile) == "suspended":
				visible = 0
		self.storefront_visible = visible

	def _resolve_attribute_links(self):
		"""Auto-resolve free-text attribute names to Product Attribute records.

		Sellers fill the 'Özellik Adı' column as free text (frontend key:
		attribute_label). The schema requires the 'attribute' Link field, so
		we look up — or create — a Product Attribute matching the label and
		fill the link before Frappe's mandatory validation runs.
		"""
		for row in self.get("attribute_values") or []:
			if row.get("attribute"):
				continue
			label = (row.get("attribute_label") or row.get("attribute_name") or "").strip()
			if not label:
				continue  # let standard mandatory validation flag it
			code = frappe.scrub(label) or label
			if not frappe.db.exists("Product Attribute", code):
				new_attr = frappe.new_doc("Product Attribute")
				new_attr.attribute_code = code
				new_attr.attribute_label = label
				new_attr.data_type = "Text"
				new_attr.flags.ignore_permissions = True
				new_attr.insert(ignore_permissions=True)
			row.attribute = code
			row.attribute_label = label

	def _ensure_primary_image(self):
		"""Ana görsel boşsa ilk ek görseli ana görsel yap.

		Kart, sepet ve liste görünümleri primary_image kullanır; detay sayfası
		ise tüm galeriyi (primary + listing_images) gösterir. Satıcı görseli
		yalnızca "ek görsel" olarak eklediğinde primary_image boş kalıyor ve
		ürün kartta/sepette fotoğrafsız görünüyordu. sort_order, sonra child
		idx (ekleme sırası) ile ilk görsel seçilir.
		"""
		if self.primary_image:
			return
		rows = sorted(
			(self.get("listing_images") or []),
			key=lambda r: ((r.sort_order or 0), (r.idx or 0)),
		)
		for row in rows:
			if row.image:
				self.primary_image = row.image
				break

	def _calculate_completeness(self):
		from tradehub_core.utils.completeness import calculate_completeness_score

		self.completeness_score = calculate_completeness_score(self)

	def _validate_variant_defaults(self):
		"""Sadece 1 SKU kombinasyonu varsayılan olabilir (tüm matris genelinde)."""
		if not self.variant_items:
			return
		default_count = sum(1 for r in self.variant_items if r.is_default)
		if default_count > 1:
			# Auto-fix: sadece ilk default'u tut, gerisini kaldır
			found_first = False
			for row in self.variant_items:
				if row.is_default:
					if found_first:
						row.is_default = 0
					found_first = True

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
		self._send_status_notifications()
		self._check_stock_alerts()

	def _send_status_notifications(self):
		old = self.get_doc_before_save()
		if not old or old.status == self.status:
			return
		seller_user = (
			frappe.db.get_value("Admin Seller Profile", self.seller_profile, "user")
			if self.seller_profile
			else None
		)
		if not seller_user:
			return

		title_text = self.title or self.listing_code or self.name
		if self.status == "Active" and old.status == "Pending":
			notify(
				recipient_user=seller_user,
				recipient_role="seller",
				type="listing",
				title=_("Ürün Onaylandı"),
				message=_("{0} ürününüz yayına alındı.").format(title_text),
				action_url=f"/app/listing/{self.name}",
				reference_doctype="Listing",
				reference_name=self.name,
			)
		elif self.status == "Rejected":
			reason = self.rejection_reason or ""
			notify(
				recipient_user=seller_user,
				recipient_role="seller",
				type="listing",
				title=_("Ürün Reddedildi"),
				message=_("{0} ürününüz reddedildi. {1}").format(title_text, reason),
				action_url=f"/app/listing/{self.name}",
				reference_doctype="Listing",
				reference_name=self.name,
			)

	def _check_stock_alerts(self):
		"""Stok değişikliğinde satıcıya düşük stok veya stok tükendi bildirimi gönder.
		Manuel kayıt (form save) sırasında çalışır.
		Programmatic stok değişiklikleri stock.py üzerinden _send_stock_alert_if_needed ile yapılır.
		"""
		if not self.track_inventory or self.status != "Active":
			return
		old = self.get_doc_before_save()
		if not old:
			return
		old_available = max(0, flt(old.stock_qty) - flt(old.reserved_qty))
		new_available = flt(self.available_qty)
		if old_available == new_available:
			return

		from tradehub_core.utils.stock import _send_stock_alert_if_needed

		_send_stock_alert_if_needed(self.name, self, old_available, new_available)

	def generate_listing_code(self):
		hash_input = f"{self.title}-{time.time()}"
		return "LST-" + hashlib.md5(hash_input.encode()).hexdigest()[:8].upper()

	def calculate_available_qty(self):
		self.available_qty = max(0, flt(self.stock_qty) - flt(self.reserved_qty))

	def validate_pricing(self):
		"""Enforce hard rules on pricing fields:
		  1. Negatif fiyat reddedilir (HATA 24 — veri butunlugu, coupon istismari).
		  2. Satis fiyati listeleme fiyatini gecemez.

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

		if listing_price < 0:
			frappe.throw(_("Listeleme fiyatı negatif olamaz"))
		if selling_price < 0:
			frappe.throw(_("Satış fiyatı negatif olamaz"))

		if listing_price and selling_price and selling_price > listing_price:
			frappe.throw(_("Satış fiyatı Listeleme fiyatından büyük olamaz"))

		# Y3 — Filtre ve fiyat sıralaması karışık para birimli listing'leri ham
		# selling_price üzerinden karşılaştıramaz. selling_price'ı baz para
		# birimine (TRY) çevirip karşılaştırılabilir selling_price_base'e yaz.
		self.selling_price_base = self._to_base_price(selling_price)

	def _to_base_price(self, amount):
		"""Bir tutarı listing'in native para biriminden baz birime (TRY) çevirir."""
		from tradehub_core.api.currency import _get_exchange_rate

		currency = self.currency or "TRY"
		if currency == "TRY":
			return round(flt(amount), 2)
		return round(flt(amount) * _get_exchange_rate(currency, "TRY"), 2)

	def validate_stock(self):
		"""Stok ve siparis miktari negatif olamaz (HATA 24)."""
		if flt(self.stock_qty) < 0:
			frappe.throw(_("Stok negatif olamaz"))
		if flt(self.min_order_qty) < 0:
			frappe.throw(_("Minimum siparis miktari negatif olamaz"))

	def _validate_variant_pricing(self):
		"""Variant satirlarinda ve toptan fiyat dilimlerinde negatif fiyat reddedilir."""
		for row in self.get("variant_items") or []:
			label = (
				row.get("variant_sku")
				or row.get("attribute_value")
				or row.get("attribute_value_2")
				or row.name
				or ""
			)
			if flt(row.variant_price) < 0:
				frappe.throw(_("Varyant fiyatı negatif olamaz: {0}").format(label))
			if flt(row.variant_stock) < 0:
				frappe.throw(_("Varyant stoğu negatif olamaz: {0}").format(label))
		for tier in self.get("pricing_tiers") or []:
			if flt(tier.price) < 0:
				frappe.throw(_("Toptan fiyat dilimi negatif olamaz"))

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
				frappe.throw("Max quantity must be >= min quantity in pricing tier")
			prev_max = max_qty or float("inf")

	def get_price_for_qty(self, qty=1):
		if self.b2b_enabled and self.pricing_tiers:
			for tier in sorted(self.pricing_tiers, key=lambda t: t.min_qty, reverse=True):
				if qty >= tier.min_qty:
					return tier.price
		return self.selling_price

	def increment_view_count(self):
		frappe.db.set_value("Listing", self.name, "view_count", (self.view_count or 0) + 1)
