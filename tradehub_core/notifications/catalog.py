"""Bildirim olay kataloğu — sunucunun tek kaynağı.

Kaynak: `desing/bildirim-sablonlari-2026-10-02/assets/olay-sozlesmesi.js` (EVENTS). Yalnız
anahtar / kategori / alıcı / kanal kuralı / varsayılan / gönderim taşınır. Prototipin sahte sürüm
numarası, kişi, tarih, aylık hacim ve "hazır" çeviri işaretleri bilinçli olarak TAŞINMAZ.

Kanal kuralı, varsayılan ve gönderim, seed sonrasında Platform Notification Event kaydında yaşar
(yönetici değiştirebilir). Değişken tanımı, koşullu zorunlular ve olay adı/gerekçe ise burada
kalır: kullanıcı anahtar, alıcı ya da değişken listesi değiştiremez.
"""

from __future__ import annotations

CHANNELS = ("inapp", "email", "push", "sms")
USER_CHANNELS = ("email", "push", "sms")
LANGS = ("tr", "en", "ar", "ru")
SOURCE_LANG = "tr"
CHANNEL_STATES = ("zorunlu", "secmeli", "kapali")
DELIVERY = ("aninda", "ozetlenebilir")
TRANSLATION_STATES = ("hazir", "bekliyor", "kopya", "eksik")
FREQUENCIES = ("instant", "daily", "weekly")

CATEGORIES = {
	"account": {"title": "Hesap ve güvenlik", "module": "Kimlik"},
	"orders": {"title": "Siparişler", "module": "Sipariş"},
	"rfq": {"title": "Teklif ve RFQ", "module": "RFQ"},
	"store": {"title": "Mağaza ve başvuru", "module": "Mağaza"},
	"reviews": {"title": "Değerlendirmeler", "module": "Değerlendirme"},
	"logistics": {"title": "Lojistik", "module": "Lojistik"},
	"billing": {"title": "Abonelik ve ödemeler", "module": "Abonelik"},
	"digest": {"title": "Özet e-postaları", "module": "Özet"},
}

# Kanal başına düzenlenebilir alanlar (panel `constants/notificationTemplates.js` FIELDS ile aynı).
FIELDS = {
	"email": {
		"subject": {"max": 78, "required": True},
		"preheader": {"max": 110},
		"html": {"html": True, "required": True},
		"text": {},
	},
	"inapp": {
		"title": {"max": 80, "required": True},
		"message": {"max": 200, "required": True},
		"action_label": {"max": 24},
		"action_url": {"url": True},
	},
	"push": {"title": {"max": 50, "required": True}, "body": {"max": 120, "required": True}},
	"sms": {"text": {"required": True}},
}
PRIMARY_FIELD = {"email": "html", "inapp": "message", "push": "body", "sms": "text"}
FIELD_HARD_MAX = {"html": 100_000, "text": 20_000}  # kayıtta reddedilen üst sınır
DEFAULT_HARD_MAX = 2_000


def _ch(inapp, email, push, sms):
	return {"inapp": inapp, "email": email, "push": push, "sms": sms}


Z, S, K = "zorunlu", "secmeli", "kapali"

# ── Değişken kümeleri ─────────────────────────────────────────────────────


def var(name, label, sample, type_="text", sample_long=None, scope=None):
	out = {"name": name, "label": label, "sample": sample, "type": type_, "scope": scope}
	if sample_long is not None:
		out["sample_long"] = sample_long
	return out


GENERIC_VARIABLES = [
	var("recipient_name", "Alıcı adı", "Deniz Yıldız", sample_long="Yıldız Konfeksiyon Tekstil Sanayi A.Ş."),
	var("reference_no", "Kayıt numarası", "TH-24081", sample_long="TH-2408100045-B"),
	var("event_date", "Olay zamanı", "2 Eki 2026, 14:32"),
	var("action_url", "Ayrıntı bağlantısı", "https://istoc.example/siparis/TH-24081", "url"),
]
GENERIC_REQUIRED = {
	"email": ["reference_no", "action_url"],
	"inapp": ["reference_no"],
	"push": ["reference_no"],
	"sms": ["reference_no"],
}

SPECIFIC_VARIABLES = {
	"identity.otp": [
		var("otp_code", "Doğrulama kodu", "482915"),
		var("expires_minutes", "Geçerlilik (dakika)", 30),
		var("expires_at", "Son geçerlilik", "2 Eki 2026, 15:02"),
		var("action_label", "İşlem", "Yeni hesap kaydı"),
		var("requested_at", "Talep zamanı", "2 Eki 2026, 14:32"),
		var("email", "E-posta adresi", "de•••@ornek-tekstil.example"),
		var("device", "Cihaz", "Chrome, macOS"),
		var("location", "Konum", "İstanbul (yaklaşık)"),
	],
	"identity.password_reset": [
		var("first_name", "Ad", "Deniz"),
		var("email", "E-posta adresi", "de•••@ornek-tekstil.example"),
		var("reset_url", "Sıfırlama bağlantısı", "https://istoc.example/auth/sifre-sifirla?key=ornek", "url"),
		var("reset_expires_hours", "Geçerlilik (saat)", 24),
		var("requested_at", "Talep zamanı", "2 Eki 2026, 09:14"),
		var("device", "Cihaz", "Chrome, Windows"),
	],
	"store.application_result": [
		var(
			"company_name",
			"Firma adı",
			"Yıldız Konfeksiyon",
			sample_long="Yıldız Konfeksiyon Tekstil Sanayi ve Dış Ticaret A.Ş.",
		),
		var("application_no", "Başvuru no", "SA-2026-0312"),
		var("application_approved", "Başvuru onaylandı", True, "boolean"),
		var("documents_required", "Ek belge isteniyor", False, "boolean"),
		var("approved_at", "Onay zamanı", "2 Eki 2026, 11:05"),
		var("reviewed_at", "İnceleme zamanı", "2 Eki 2026, 11:05"),
		var("email", "Yetkili e-posta", "ma•••@yildiz-konfeksiyon.example"),
		var("panel_url", "Mağaza paneli bağlantısı", "https://istoc.example/panel", "url"),
		var("documents_url", "Belge yükleme bağlantısı", "https://istoc.example/panel/basvuru", "url"),
		var("docs_count", "İstenen belge sayısı", 2),
		var(
			"docs",
			"İstenen belgeler",
			[{"name": "Vergi levhası", "reason": "Yüklenen dosya okunaksız."}],
			"loop",
		),
		var("doc.name", "Belge adı", "Vergi levhası", scope="docs"),
		var("doc.reason", "Belge nedeni", "Yüklenen dosya okunaksız.", scope="docs"),
		var("deadline", "Belge son tarihi", ""),
		var("rejection_reason", "İnceleme notu", "Vergi levhası okunaksız; güncel taramayı yükleyin."),
		var("status_url", "Durum bağlantısı", "https://istoc.example/panel", "url"),
	],
	"payment.receipt": [
		var("company_name", "Firma adı", "Yıldız Konfeksiyon"),
		var("plan_name", "Plan", "Mağaza Pro"),
		var("billing_cycle", "Faturalama dönemi", "aylık"),
		var("period", "Dönem", "2 Eki – 1 Kas 2026"),
		var("total", "Toplam", "₺1.250,00"),
		var("paid_at", "Ödeme zamanı", "2 Eki 2026, 14:32"),
		var("payment_reference", "Ödeme referansı", "SPR-0001"),
		var("receipt_no", "Makbuz no", ""),
		var("receipt_url", "Makbuz bağlantısı", "", "url"),
		var("card_last4", "Kart son 4 hane", ""),
		var("period_end", "Abonelik bitişi", "1 Kas 2026"),
		var("invoice_note", "Fatura notu göster", True, "boolean"),
		var("subscription_url", "Abonelik ayarları", "https://istoc.example/panel/abonelik", "url"),
	],
	"order.confirm_reminder": [
		var("order_no", "Sipariş no", "TH-24081"),
		var("buyer_company", "Alıcı firma", "Örnek Tekstil Ltd."),
		var("items_count", "Kalem sayısı", 3),
		var("order_total", "Sipariş tutarı", "₺12.480,00"),
		var("ordered_at", "Sipariş zamanı", "1 Eki 2026, 18:32"),
		var("waiting_hours", "Bekleme süresi (saat)", 20),
		var("seller_store_name", "Mağaza adı", "Yıldız Konfeksiyon"),
		var("order_url", "Sipariş bağlantısı", "https://istoc.example/panel/siparisler/TH-24081", "url"),
		var("preferences_url", "Tercih bağlantısı", "https://istoc.example/ayarlar/bildirimler", "url"),
	],
}

_DIGEST_VARIABLES = [
	var("recipient_name", "Alıcı adı", "Yıldız Konfeksiyon"),
	var("digest_title", "Özet başlığı", "1 Eki 2026 günlük özeti"),
	var("period", "Dönem", "1 Eki 2026"),
	var("total_count", "Gelişme sayısı", 11),
	var("generated_at", "Hazırlanma zamanı", "2 Eki 2026, 08:00"),
	var(
		"groups",
		"Gruplar",
		[
			{
				"title": "Siparişler",
				"count": 7,
				"more": True,
				"more_n": 4,
				"items": [{"title": "TH-24066 kargoya verildi", "time": "09:12", "url": "/bildirimler"}],
			}
		],
		"loop",
	),
	var("group.title", "Grup başlığı", "Siparişler", scope="groups"),
	var("group.count", "Grup olay sayısı", 7, scope="groups"),
	var("group.more", "Gösterilmeyen var", True, "boolean", scope="groups"),
	var("group.more_n", "Gösterilmeyen sayısı", 4, scope="groups"),
	var("group.items", "Grup satırları", [], "loop", scope="groups"),
	var("item.title", "Satır başlığı", "TH-24066 kargoya verildi", scope="group.items"),
	var("item.time", "Satır zamanı", "09:12", scope="group.items"),
	var("item.url", "Satır bağlantısı", "/bildirimler", "url", scope="group.items"),
	var("digest_url", "Bildirimler bağlantısı", "https://istoc.example/bildirimler", "url"),
	var("preferences_url", "Tercih bağlantısı", "https://istoc.example/ayarlar/bildirimler", "url"),
]
SPECIFIC_VARIABLES["digest.daily"] = _DIGEST_VARIABLES
SPECIFIC_VARIABLES["digest.weekly"] = _DIGEST_VARIABLES

SPECIFIC_REQUIRED = {
	"identity.otp": {"email": ["otp_code", "expires_minutes"], "sms": ["otp_code"]},
	"identity.password_reset": {
		"email": ["reset_url", "reset_expires_hours"],
		"inapp": ["requested_at"],
	},
	"store.application_result": {
		"email": ["company_name", "application_no"],
		"inapp": ["application_no"],
	},
	"payment.receipt": {
		"email": ["plan_name", "total", "paid_at"],
		"inapp": ["plan_name", "total"],
	},
	"order.confirm_reminder": {
		"email": ["order_no", "order_url"],
		"inapp": ["order_no"],
		"push": ["order_no"],
	},
	"digest.daily": {"email": ["groups", "total_count"]},
	"digest.weekly": {"email": ["groups", "total_count"]},
}

# Koşullu zorunlular: koşul değişkeni doğruysa o dalın değişkenleri olay verisinde dolu olmalı
# ve e-posta içeriğinde kullanılmalı (`{{#if koşul}}` bloğu içinde).
CONDITIONAL_REQUIRED = {
	"store.application_result": {
		"application_approved": {"email": ["panel_url", "approved_at"]},
		"documents_required": {"email": ["documents_url", "rejection_reason"]},
	},
}

# ── Olaylar ───────────────────────────────────────────────────────────────


def ev(key, name, category, recipients, channels, defaults, delivery, why=None):
	return {
		"key": key,
		"name": name,
		"category": category,
		"recipients": recipients,
		"channels": channels,
		"defaults": defaults,
		"delivery": delivery,
		"why": why,
	}


EVENTS = [
	ev("identity.otp", "Doğrulama kodu", "account", ["buyer", "seller"], _ch(K, Z, K, Z), {}, "aninda",
		"Giriş ve işlem onayı için tek kullanımlık kod; kodsuz işlem tamamlanamaz."),
	ev("identity.password_reset", "Şifre sıfırlama ve hesap güvenliği", "account", ["buyer", "seller"],
		_ch(Z, Z, K, K), {}, "aninda", "Şifre değişimi ve yeni cihaz girişi; hesabı korur."),
	ev("payment.receipt", "Ödeme makbuzu", "account", ["buyer", "seller"], _ch(Z, Z, K, K), {}, "aninda",
		"Ödemenin kaydıdır; her ödeme sonrası gönderilir. Fatura ayrıca düzenlenir."),
	ev("account.status", "Hesap durumu", "account", ["buyer", "seller"], _ch(Z, Z, K, K), {}, "aninda",
		"KYB/KYC sonucu ve askıya alma kararları; hesabın kullanımını doğrudan etkiler."),
	ev("identity.suspicious_login", "Şüpheli giriş", "account", ["admin"], _ch(Z, Z, K, K), {}, "aninda",
		"Yönetici hesabına olağan dışı giriş denemesi."),
	ev("order.received", "Yeni sipariş", "orders", ["seller"], _ch(Z, S, S, K),
		{"email": True, "push": True}, "aninda"),
	ev("order.confirm_reminder", "Sipariş onay hatırlatması", "orders", ["seller"], _ch(Z, S, S, K),
		{"email": True, "push": True}, "aninda"),
	ev("order.confirmed", "Sipariş onaylandı", "orders", ["buyer"], _ch(Z, S, S, K),
		{"email": True, "push": True}, "ozetlenebilir"),
	ev("order.shipped", "Kargoya verildi", "orders", ["buyer", "seller"], _ch(Z, S, S, K),
		{"email": False, "push": True}, "ozetlenebilir"),
	ev("order.delivered", "Teslim edildi", "orders", ["buyer", "seller"], _ch(Z, S, S, K),
		{"email": False, "push": True}, "ozetlenebilir"),
	ev("order.cancelled", "İptal ve iade", "orders", ["buyer", "seller"], _ch(Z, S, S, K),
		{"email": True, "push": True}, "aninda"),
	ev("rfq.created", "Yeni teklif isteği", "rfq", ["seller"], _ch(Z, S, S, K),
		{"email": True, "push": True}, "ozetlenebilir"),
	ev("rfq.quoted", "Teklif yanıtı geldi", "rfq", ["buyer"], _ch(Z, K, S, K), {"push": True}, "ozetlenebilir"),
	ev("rfq.expiring", "Teklif süresi doluyor", "rfq", ["buyer", "seller"], _ch(Z, K, S, K),
		{"push": True}, "aninda"),
	ev("store.application_result", "Başvuru durumu", "store", ["seller"], _ch(Z, Z, K, K), {}, "aninda",
		"Satıcı başvurusunun onayı ya da ek belge isteği; mağazanın açılmasını doğrudan etkiler."),
	ev("store.document_expiring", "Belge süresi doluyor", "store", ["seller"], _ch(Z, Z, K, K), {}, "aninda",
		"Süresi dolan belge yenilenmezse satış durabilir."),
	ev("store.moderation_result", "Ürün moderasyon sonucu", "store", ["seller"], _ch(Z, S, K, K),
		{"email": True}, "ozetlenebilir"),
	ev("store.showcase_changed", "Vitrin değişikliği", "store", ["seller"], _ch(Z, S, K, K),
		{"email": False}, "ozetlenebilir"),
	ev("review.created", "Yeni yorum", "reviews", ["seller"], _ch(Z, K, S, K), {"push": True}, "ozetlenebilir"),
	ev("review.replied", "Yoruma yanıt", "reviews", ["buyer", "seller"], _ch(Z, K, S, K),
		{"push": True}, "ozetlenebilir"),
	ev("shipment.delayed", "Kargo gecikti", "logistics", ["buyer", "seller"], _ch(Z, S, S, K),
		{"email": False, "push": True}, "aninda"),
	ev("shipment.address_issue", "Teslimat adresi sorunu", "logistics", ["buyer", "seller"],
		_ch(Z, S, S, S), {"email": True, "push": True, "sms": False}, "aninda"),
	ev("subscription.renewing", "Abonelik yenileme hatırlatması", "billing", ["seller"], _ch(Z, S, K, K),
		{"email": True}, "aninda"),
	ev("payment.failed", "Ödeme başarısız", "billing", ["buyer", "seller"], _ch(Z, Z, S, Z),
		{"push": True}, "aninda"),
	ev("digest.daily", "Günlük özet", "digest", ["buyer", "seller"], _ch(K, S, K, K), {"email": True},
		"ozetlenebilir"),
	ev("digest.weekly", "Haftalık özet", "digest", ["buyer", "seller"], _ch(K, S, K, K), {"email": True},
		"ozetlenebilir"),
]  # fmt: skip

EVENT_KEYS = tuple(e["key"] for e in EVENTS)
DIGEST_KEYS = ("digest.daily", "digest.weekly")
_BY_KEY = {e["key"]: e for e in EVENTS}

# Olayın yapısal kilidi: bu kanalların kuralı yönetici tarafından değiştirilemez.
# OTP ve özet e-postasında uygulama içi kanal anlamsızdır (kod bildirim kutusuna yazılmaz;
# özetin kendisi bildirim değildir).
STRUCTURAL_LOCKS = {
	"identity.otp": {"inapp": "kapali"},
	"digest.daily": {"inapp": "kapali", "push": "kapali", "sms": "kapali"},
	"digest.weekly": {"inapp": "kapali", "push": "kapali", "sms": "kapali"},
}


def get(key: str) -> dict | None:
	return _BY_KEY.get(key)


def variables_for(key: str) -> list[dict]:
	return SPECIFIC_VARIABLES.get(key, GENERIC_VARIABLES)


def required_for(key: str) -> dict:
	base = SPECIFIC_REQUIRED.get(key, GENERIC_REQUIRED)
	return {ch: list(base.get(ch, [])) for ch in CHANNELS}


def conditional_for(key: str) -> dict:
	return CONDITIONAL_REQUIRED.get(key, {})


def mandatory_of(channels: dict) -> bool:
	"""Hiçbir kanal seçmeli değilse olay kullanıcıda 'zorunlu' özetinde görünür."""
	return S not in channels.values() and any(v == Z for v in channels.values())


def module_of(category: str) -> str:
	return CATEGORIES.get(category, {}).get("module", "")
