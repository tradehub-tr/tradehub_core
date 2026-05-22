"""Storefront statik sayfa kayıtları (Faz 4c).

63 statik HTML sayfası için path → metadata. Admin paneli bu listeden
Static Page SEO record'larını seed eder ve render_static_page endpoint'i
path lookup için kullanır.

Yeni sayfa eklerken: bu listeye entry ekle, sonra
`bench execute tradehub_core.setup.seed_static_pages.run` çalıştır.
"""

# Her entry: {
#   path: TR canonical path (örn. "/yardim-merkezi")
#   title: admin için display label
#   html_path: storefront dist relative path (örn. "pages/help/help-center.html")
#   indexable_default: seed sırasında noindex=0 yapılsın mı
#   sitemap_priority: 0.0-1.0 (string olarak)
#   sitemap_changefreq: always|hourly|daily|weekly|monthly|yearly|never
# }
STATIC_PAGES = [
	# ── Ana + listing (5) ─────────────────────────────────
	{"path": "/", "title": "Anasayfa", "html_path": "index.html",
	 "indexable_default": True, "sitemap_priority": "1.0", "sitemap_changefreq": "daily"},
	{"path": "/urunler", "title": "Tüm Ürünler", "html_path": "pages/products.html",
	 "indexable_default": True, "sitemap_priority": "0.9", "sitemap_changefreq": "daily"},
	{"path": "/kategoriler", "title": "Tüm Kategoriler", "html_path": "pages/categories.html",
	 "indexable_default": True, "sitemap_priority": "0.8", "sitemap_changefreq": "weekly"},
	{"path": "/markalar", "title": "Tüm Markalar", "html_path": "pages/manufacturers.html",
	 "indexable_default": True, "sitemap_priority": "0.7", "sitemap_changefreq": "weekly"},
	{"path": "/sepet", "title": "Sepet", "html_path": "pages/cart.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},

	# ── Auth (4, hepsi noindex) ───────────────────────────
	{"path": "/giris", "title": "Giriş", "html_path": "pages/auth/login.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/kayit", "title": "Kayıt Ol", "html_path": "pages/auth/register.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/sifremi-unuttum", "title": "Şifremi Unuttum",
	 "html_path": "pages/auth/forgot-password.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/sifre-sifirla", "title": "Şifre Sıfırla",
	 "html_path": "pages/auth/reset-password.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},

	# ── Yardım (6) ────────────────────────────────────────
	{"path": "/yardim-merkezi", "title": "Yardım Merkezi",
	 "html_path": "pages/help/help-center.html",
	 "indexable_default": True, "sitemap_priority": "0.6", "sitemap_changefreq": "monthly"},
	{"path": "/sss", "title": "Sık Sorulan Sorular", "html_path": "pages/help/faq.html",
	 "indexable_default": True, "sitemap_priority": "0.6", "sitemap_changefreq": "monthly"},
	{"path": "/sss/detay", "title": "SSS Detay", "html_path": "pages/help/faq-detail.html",
	 "indexable_default": False, "sitemap_priority": "0.3", "sitemap_changefreq": "monthly"},
	{"path": "/destek/yeni", "title": "Yeni Destek Talebi",
	 "html_path": "pages/help/help-ticket-new.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/destek/taleplerim", "title": "Destek Taleplerim",
	 "html_path": "pages/help/help-tickets.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/destek/talep", "title": "Destek Talep Detay",
	 "html_path": "pages/help/help-ticket.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},

	# ── Bilgi (14) ────────────────────────────────────────
	{"path": "/satis-sonrasi", "title": "Satış Sonrası",
	 "html_path": "pages/info/after-sales.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "monthly"},
	{"path": "/blog", "title": "Blog", "html_path": "pages/info/blog.html",
	 "indexable_default": True, "sitemap_priority": "0.6", "sitemap_changefreq": "weekly"},
	{"path": "/kariyer", "title": "Kariyer", "html_path": "pages/info/careers.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "monthly"},
	{"path": "/kurumsal-sorumluluk", "title": "Kurumsal Sorumluluk",
	 "html_path": "pages/info/csr.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "monthly"},
	{"path": "/uyelik", "title": "Üyelik", "html_path": "pages/info/membership.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "monthly"},
	{"path": "/izleme", "title": "İzleme", "html_path": "pages/info/monitoring.html",
	 "indexable_default": False, "sitemap_priority": "0.3", "sitemap_changefreq": "monthly"},
	{"path": "/haberler", "title": "Haberler", "html_path": "pages/info/news.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "weekly"},
	{"path": "/ortakliklar", "title": "Ortaklıklar",
	 "html_path": "pages/info/partnerships.html",
	 "indexable_default": True, "sitemap_priority": "0.4", "sitemap_changefreq": "monthly"},
	{"path": "/odeme-secenekleri", "title": "Ödeme Seçenekleri",
	 "html_path": "pages/info/payments.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "monthly"},
	{"path": "/iade-politikasi", "title": "İade Politikası",
	 "html_path": "pages/info/refund-policy.html",
	 "indexable_default": True, "sitemap_priority": "0.6", "sitemap_changefreq": "monthly"},
	{"path": "/kargo-lojistik", "title": "Kargo ve Lojistik",
	 "html_path": "pages/info/shipping-logistics.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "monthly"},
	{"path": "/kargo-koruma", "title": "Kargo Koruması",
	 "html_path": "pages/info/shipping-protection.html",
	 "indexable_default": True, "sitemap_priority": "0.4", "sitemap_changefreq": "monthly"},
	{"path": "/vergi", "title": "Vergi Bilgileri", "html_path": "pages/info/tax.html",
	 "indexable_default": True, "sitemap_priority": "0.4", "sitemap_changefreq": "monthly"},
	{"path": "/ticaret-guvencesi/detay", "title": "Ticaret Güvencesi Detay",
	 "html_path": "pages/info/trade-assurance-detail.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "monthly"},

	# ── Hukuki (10) ───────────────────────────────────────
	{"path": "/erisilebilirlik", "title": "Erişilebilirlik",
	 "html_path": "pages/legal/accessibility.html",
	 "indexable_default": True, "sitemap_priority": "0.3", "sitemap_changefreq": "yearly"},
	{"path": "/cerezler", "title": "Çerez Politikası",
	 "html_path": "pages/legal/cookies.html",
	 "indexable_default": True, "sitemap_priority": "0.4", "sitemap_changefreq": "yearly"},
	{"path": "/mesafeli-satis", "title": "Mesafeli Satış Sözleşmesi",
	 "html_path": "pages/legal/distance-sales.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "yearly"},
	{"path": "/fikri-mulkiyet", "title": "Fikri Mülkiyet",
	 "html_path": "pages/legal/ip.html",
	 "indexable_default": True, "sitemap_priority": "0.3", "sitemap_changefreq": "yearly"},
	{"path": "/kvkk", "title": "KVKK Aydınlatma Metni",
	 "html_path": "pages/legal/kvkk.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "yearly"},
	{"path": "/yasal-uyari", "title": "Yasal Uyarı",
	 "html_path": "pages/legal/notice.html",
	 "indexable_default": True, "sitemap_priority": "0.3", "sitemap_changefreq": "yearly"},
	{"path": "/gizlilik", "title": "Gizlilik Politikası",
	 "html_path": "pages/legal/privacy.html",
	 "indexable_default": True, "sitemap_priority": "0.6", "sitemap_changefreq": "yearly"},
	{"path": "/urun-listeleme-kurallari", "title": "Ürün Listeleme Kuralları",
	 "html_path": "pages/legal/product-listing.html",
	 "indexable_default": True, "sitemap_priority": "0.4", "sitemap_changefreq": "yearly"},
	{"path": "/iade-kosullari", "title": "İade Koşulları",
	 "html_path": "pages/legal/returns.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "yearly"},
	{"path": "/kullanim-kosullari", "title": "Kullanım Koşulları",
	 "html_path": "pages/legal/terms.html",
	 "indexable_default": True, "sitemap_priority": "0.5", "sitemap_changefreq": "yearly"},

	# ── Dashboard (14, hepsi noindex) ─────────────────────
	{"path": "/hesabim/adresler", "title": "Adreslerim",
	 "html_path": "pages/dashboard/addresses.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim", "title": "Hesabım",
	 "html_path": "pages/dashboard/buyer-dashboard.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/kisiler", "title": "Kişilerim",
	 "html_path": "pages/dashboard/contacts.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/favoriler", "title": "Favorilerim",
	 "html_path": "pages/dashboard/favorites.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/sorularim", "title": "Sorularım",
	 "html_path": "pages/dashboard/inquiries.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/kyb", "title": "KYB Doğrulama",
	 "html_path": "pages/dashboard/kyb.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/mesajlar", "title": "Mesajlarım",
	 "html_path": "pages/dashboard/messages.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/siparisler", "title": "Siparişlerim",
	 "html_path": "pages/dashboard/orders.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/odeme", "title": "Ödeme Yöntemlerim",
	 "html_path": "pages/dashboard/payment.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/profil", "title": "Profilim",
	 "html_path": "pages/dashboard/profile.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/rfq", "title": "RFQ Taleplerim",
	 "html_path": "pages/dashboard/rfq.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/rfq/yeni", "title": "Yeni RFQ",
	 "html_path": "pages/dashboard/rfq-form.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/rfq/teklifler", "title": "RFQ Teklifleri",
	 "html_path": "pages/dashboard/rfq-quotes.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/hesabim/ayarlar", "title": "Hesap Ayarları",
	 "html_path": "pages/dashboard/settings.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},

	# ── Order (4, hepsi noindex) ──────────────────────────
	{"path": "/odeme", "title": "Ödeme Sayfası",
	 "html_path": "pages/order/checkout.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/odeme/basarili", "title": "Ödeme Başarılı",
	 "html_path": "pages/order/order-success.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/odeme/basarisiz", "title": "Ödeme Başarısız",
	 "html_path": "pages/order/payment-failed.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/odeme/isleniyor", "title": "Ödeme İşleniyor",
	 "html_path": "pages/order/payment-processing.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},

	# ── Seller (7) ────────────────────────────────────────
	{"path": "/satici-ol", "title": "Satıcı Ol",
	 "html_path": "pages/seller/sell.html",
	 "indexable_default": True, "sitemap_priority": "0.7", "sitemap_changefreq": "monthly"},
	{"path": "/satici/fiyatlandirma", "title": "Satıcı Fiyatlandırması",
	 "html_path": "pages/seller/sell-pricing.html",
	 "indexable_default": True, "sitemap_priority": "0.6", "sitemap_changefreq": "monthly"},
	{"path": "/satici/dashboard", "title": "Satıcı Paneli",
	 "html_path": "pages/seller/dashboard.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/satici/basvuru-bekleyen", "title": "Başvuru Bekleniyor",
	 "html_path": "pages/seller/application-pending.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/satici/tedarikci-kurulum", "title": "Tedarikçi Kurulumu",
	 "html_path": "pages/seller/supplier-setup.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/satici/dogrulama", "title": "Satıcı Doğrulama",
	 "html_path": "pages/seller/verification.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},
	{"path": "/satici/vitrin", "title": "Satıcı Vitrini",
	 "html_path": "pages/seller/seller-storefront.html",
	 "indexable_default": False, "sitemap_priority": "0.1", "sitemap_changefreq": "never"},

	# ── Top + Special (5) ─────────────────────────────────
	{"path": "/firsat", "title": "Fırsatlar",
	 "html_path": "pages/top-deals.html",
	 "indexable_default": True, "sitemap_priority": "0.7", "sitemap_changefreq": "daily"},
	{"path": "/cok-satanlar", "title": "Çok Satanlar",
	 "html_path": "pages/top-ranking.html",
	 "indexable_default": True, "sitemap_priority": "0.7", "sitemap_changefreq": "daily"},
	{"path": "/cok-satanlar/kategori", "title": "Kategoriye Göre Çok Satanlar",
	 "html_path": "pages/top-ranking-category.html",
	 "indexable_default": True, "sitemap_priority": "0.6", "sitemap_changefreq": "daily"},
	{"path": "/size-ozel", "title": "Size Özel Seçimler",
	 "html_path": "pages/tailored-selections.html",
	 "indexable_default": True, "sitemap_priority": "0.6", "sitemap_changefreq": "weekly"},
	{"path": "/ticaret-guvencesi", "title": "Ticaret Güvencesi",
	 "html_path": "pages/trade-assurance.html",
	 "indexable_default": True, "sitemap_priority": "0.6", "sitemap_changefreq": "monthly"},

	# ── 404 ───────────────────────────────────────────────
	{"path": "/404", "title": "Sayfa Bulunamadı", "html_path": "404.html",
	 "indexable_default": False, "sitemap_priority": "0.0", "sitemap_changefreq": "never"},
]


def find_entry(path: str) -> dict | None:
	"""Path'e göre registry entry döner; yoksa None."""
	if not path:
		return None
	for entry in STATIC_PAGES:
		if entry["path"] == path:
			return entry
	return None


def indexable_paths() -> list[str]:
	"""indexable_default=True olan path'lerin listesi."""
	return [e["path"] for e in STATIC_PAGES if e.get("indexable_default")]
