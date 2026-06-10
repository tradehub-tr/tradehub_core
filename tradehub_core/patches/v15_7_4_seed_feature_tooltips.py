"""Storefront pricing tablosu (Tüm paket özellikleri) tooltip içeriği seed.

Her Feature Catalog özelliğinin `description` alanı storefront karşılaştırma
tablosunda özellik adının yanındaki ⓘ ikonunun hover tooltip'i olarak gösterilir
(bkz. public_pricing._build_features_matrix → tooltip; SellPageLayout matris satırı).

Önceki açıklamalar v15_6_22 seed'inden gelen kısa etiketlerdi (ör. "...kotası").
Bu patch alıcıya "özellik ne işe yarar" anlatan daha açıklayıcı metinlerle ezer.
Admin bu metinleri Feature Catalog ekranından düzenleyebilir; boş bırakılırsa
tooltip ikonu hiç gösterilmez (per-feature tooltip kontrolü).

Idempotent: feature_key bulunamazsa atlanır; mevcut değer aynıysa yazma yapılmaz.
"""

from __future__ import annotations

import frappe

# feature_key -> storefront tooltip açıklaması (alıcı odaklı, "ne işe yarar")
TOOLTIPS: dict[str, str] = {
	# ── Komisyon & Limitler ───────────────────────────────────────────
	"quota.commission_rate": "Tamamlanan her satıştan platformun aldığı komisyon oranı. Oran düştükçe kazancınızın daha fazlası size kalır.",
	"quota.max_active_listings": "Vitrininizde aynı anda yayında tutabileceğiniz aktif ürün ilanı sayısı.",
	"quota.team_seats": "Mağazayı birlikte yönetebileceğiniz ekip üyesi (alt kullanıcı) koltuğu sayısı.",
	"quota.max_products": "Kataloğunuza ekleyebileceğiniz toplam ürün sayısı (yayında olsun olmasın).",
	"quota.max_sub_users": "Mağaza sahibinin altında oluşturabileceği yetkili alt kullanıcı sayısı.",
	"quota.max_co_owners": "Mağaza üzerinde sahip (co-owner) yetkisine sahip olabilecek ortak sayısı.",
	"quota.max_regions": "Ürünlerinizi satışa açabileceğiniz farklı bölge / pazar sayısı.",
	"quota.max_orders_per_month": "Bir ay içinde alabileceğiniz toplam sipariş sayısının üst sınırı.",
	"quota.api_rate_limit": "API üzerinden dakikada gönderebileceğiniz istek (request) sayısı sınırı.",
	# ── Vitrin & Mağaza ───────────────────────────────────────────────
	"feature.ai.translate": "Ürün başlık ve açıklamalarınızı yapay zekâ ile otomatik çoklu dile çevirir; yurt dışı alıcılara tek tıkla ulaşırsınız.",
	"feature.storefront.tier": "Mağaza vitrininizin tasarım ve özelleştirme seviyesi (Standart, Premium, Tam özel).",
	"quota.featured_listings_monthly": "Her ay vitrininizde ve arama sonuçlarında öne çıkarabileceğiniz ürün ilanı sayısı.",
	"feature.storefront.languages": "Vitrin ve ürün sayfalarınızın alıcılara gösterilebileceği dil sayısı.",
	"feature.storefront.rich_media": "Ürünlerinize video ve 360° dönen görsel ekleyerek alıcıya daha güçlü bir sunum yaparsınız.",
	"feature.storefront.custom_subdomain": "Mağazanız markaniz.istoc.com gibi size özel bir alt adresten yayınlanır.",
	"feature.store.basic_storefront": "Ürünlerinizi sergileyen standart mağaza vitrini.",
	"feature.store.custom_theme": "Mağaza vitrininizin renk, logo ve düzenini markanıza göre özelleştirme.",
	"feature.store.custom_domain": "Mağazanızı kendi alan adınızdan (örn. www.markaniz.com) yayınlama.",
	"feature.store.multi_language": "Mağaza içeriğini birden fazla dilde sunarak farklı ülkelerden alıcılara hitap etme.",
	"feature.pim.basic_product": "Tek varyantlı standart ürün oluşturma ve yönetme.",
	"feature.pim.multi_variant": "Renk, beden gibi farklı seçenekleri tek ürün altında varyant olarak yönetme.",
	"feature.pim.attribute_set": "Ürünlere kategoriye özel teknik özellik setleri (attribute) tanımlama.",
	"feature.pim.product_family": "Benzer ürünleri bir ürün ailesi altında gruplayarak toplu yönetme.",
	"feature.pim.bulk_import": "Çok sayıda ürünü dosya ile tek seferde sisteme aktarma.",
	# ── B2B Ticaret Modülleri ─────────────────────────────────────────
	"quota.rfq_quotes_monthly": "Alıcılardan gelen teklif taleplerine (RFQ) aylık yanıt verebileceğiniz teklif sayısı.",
	"feature.sales.sample_sales": "Toplu siparişten önce alıcının ürünü test etmesi için numune satışına izin verir.",
	"feature.pim.bulk_csv_upload": "Ürünlerinizi CSV / Excel dosyasıyla toplu olarak yükleme ve güncelleme.",
	"feature.commerce.trade_assurance": "Sipariş tutarı teslimat onaylanana kadar güvende tutulur; alıcı ile aranızda güven sağlar.",
	"feature.commerce.custom_payment_terms": "Alıcılara vadeli ödeme, peşinat gibi özel ödeme planları tanımlama.",
	"feature.functional.rfq": "Alıcıların toplu alımlar için sizden özel fiyat teklifi (RFQ) istemesini sağlar.",
	"feature.functional.approval_chain": "Sipariş ve tekliflerin yayınlanmadan önce ekip içinde onay sürecinden geçmesi.",
	"feature.functional.cargo_integration": "Anlaşmalı kargo firmalarıyla otomatik gönderi oluşturma ve takip.",
	"feature.functional.commission_report": "Satışlarınızdan kesilen komisyonların detaylı dökümünü görüntüleme.",
	"feature.b2b.approved_vendor_list": "Kurumsal alıcıların yalnızca onayladıkları tedarikçilerden alım yapmasını sağlar.",
	"feature.b2b.cost_center": "Harcamaları masraf merkezlerine göre ayırarak kurumsal bütçe takibi.",
	"feature.b2b.organization_hierarchy": "Şirket içi departman / şube yapısını tanımlayıp yetkileri buna göre dağıtma.",
	"feature.crm.module": "Müşteri adaylarını, görüşmeleri ve satış fırsatlarını tek panelden yönetme.",
	# ── Güven & Doğrulama ─────────────────────────────────────────────
	"feature.storefront.manufacturer_badge_tier": "Üretici kimliğinizin doğrulandığını gösteren rozet; alıcı gözünde güvenilirliğinizi artırır.",
	"feature.support.vat_refund_advisory": "İhracat işlemlerinde KDV iadesi ve vergi konularında uzman danışmanlık.",
	"feature.logistics.insured_shipping": "Gönderileriniz hasar / kayıp durumuna karşı sigorta kapsamında taşınır.",
	# ── Pazarlama & Görünürlük ────────────────────────────────────────
	"feature.marketing.search_boost": "Ürünlerinizin site içi arama sonuçlarında üst sıralarda gösterilmesi.",
	"feature.marketing.keyword_ads": "Anahtar kelime bazlı reklamlarla ürünlerinizi hedefli alıcılara gösterme (tıklama başına ödeme).",
	"quota.ad_credit_monthly": "Reklam kampanyalarında kullanabileceğiniz aylık reklam kredisi.",
	"feature.support.event_invitations": "İstoc'un düzenlediği B2B fuar ve alıcı buluşmalarına öncelikli davet.",
	# ── Destek & Kurumsal ─────────────────────────────────────────────
	"feature.support.dedicated": "Size özel atanmış bir hesap yöneticisinden öncelikli ve kişisel destek.",
	"feature.support.tier": "Erişebileceğiniz destek kanalı ve yanıt önceliği seviyesi.",
	"feature.api.access": "Kendi sistemlerinizi İstoc'a bağlamak için programatik API erişimi.",
	"feature.api.erp_integration": "Sipariş ve stok verilerini ERP / muhasebe yazılımınızla otomatik senkronlama.",
	"feature.analytics.basic": "Ziyaret, görüntülenme ve satış gibi temel mağaza istatistikleri.",
	"feature.analytics.advanced": "Dönüşüm, trafik kaynağı ve müşteri davranışı gibi derinlemesine raporlar.",
	"feature.analytics.export": "Rapor ve verilerinizi Excel / CSV olarak dışa aktarma.",
	"feature.api.webhook": "Sipariş, stok gibi olaylarda kendi sisteminize otomatik bildirim gönderme.",
	"feature.role.custom_creation": "Ekip üyeleri için özel yetki rolleri tanımlayarak erişimi hassas yönetme.",
}


def execute() -> None:
	updated = 0
	for feature_key, desc in TOOLTIPS.items():
		if not frappe.db.exists("Feature Catalog", feature_key):
			continue
		current = frappe.db.get_value("Feature Catalog", feature_key, "description")
		if (current or "") == desc:
			continue
		frappe.db.set_value("Feature Catalog", feature_key, "description", desc, update_modified=False)
		updated += 1
	frappe.db.commit()
	frappe.logger().info(f"v15_7_4_seed_feature_tooltips: {updated} feature açıklaması güncellendi.")
