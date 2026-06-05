"""
TradeHub Demo Data Seed Script
================================
10 satıcı · 500 kategori · 1.000 ürün (varyantlı)

Çalıştırma:
    bench --site <site> execute tradehub_core.seed_demo_data.execute

Temizleme:
    bench --site <site> execute tradehub_core.seed_demo_data.cleanup

Görsel Kaynağı:
    Pexels CDN — sektöre uygun, küratörlü yüksek kaliteli ürün görselleri.
    ui-avatars.com — satıcı logoları için harf tabanlı placeholder.
    Her sektör için 10-12 el seçimi Pexels fotoğrafı kullanılır.
"""

import base64
import json
import os
import random
import re

import frappe
from frappe import _
from frappe.utils.password import update_password

from tradehub_core.api.v1.auth import _generate_member_id

DEMO_SELLER_PASSWORD = "Demo1234!"
DEMO_BUYER_PASSWORD = "Demo1234!"


# ═══════════════════════════════════════════════════════════════
#  YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════


def _slug(text):
	"""Türkçe-uyumlu URL slug oluşturur."""
	tr = str.maketrans("çğıöşüÇĞİÖŞÜ ", "cgiosuCGIOSU-")
	s = text.translate(tr).lower()
	s = re.sub(r"[^a-z0-9-]", "", s)
	return re.sub(r"-+", "-", s).strip("-")


def _img(sector_key, w=800, h=800, lock_id=""):
	"""Sektöre uygun gerçek e-ticaret ürün görseli döndürür (DummyJSON CDN).
	Her sektör için kategorisi eşleşen 16 ürün görseli havuzundan deterministik seçim.
	w/h parametreleri imza uyumluluğu için tutulur — DummyJSON kendi boyutunu sunar."""
	images = SECTOR_IMAGES.get(sector_key, SECTOR_IMAGES["giyim"])
	idx = abs(hash(lock_id)) % len(images)
	return images[idx]


def _seller_logo(name, size=200):
	"""Satıcı logosu için profesyonel harf tabanlı placeholder URL'si."""
	import urllib.parse

	encoded = urllib.parse.quote(name)
	return f"https://ui-avatars.com/api/?name={encoded}&size={size}&background=0D47A1&color=fff&bold=true&format=png"


# Satıcı koduna göre sektörle ALAKALI logo: (DiceBear ikon adı, marka rengi hex).
# Baş-harf avatarı yerine sektörü temsil eden ikon rozeti üretir
# (ör. bijuteri → gem, elektronik → laptop). _seller_icon_logo() ile URL'e dönüşür.
SELLER_LOGO_ICONS = {
	"DEMO-001": ("scissors", "6d28d9"),  # Tekstil ve Giyim
	"DEMO-002": ("handbag", "b45309"),   # Ayakkabı ve Deri
	"DEMO-003": ("laptop", "0369a1"),    # Elektronik ve Aksesuar
	"DEMO-004": ("building", "475569"),  # Hırdavat ve Nalburiye
	"DEMO-005": ("basket", "15803d"),    # Gıda ve İçecek
	"DEMO-006": ("palette", "be185d"),   # Kozmetik ve Kişisel Bakım
	"DEMO-007": ("house", "0f766e"),     # Ev Tekstili ve Dekorasyon
	"DEMO-008": ("cup", "c2410c"),       # Mutfak ve Züccaciye
	"DEMO-009": ("gem", "a16207"),       # Bijuteri ve Aksesuar
	"DEMO-010": ("boxSeam", "1d4ed8"),   # Ambalaj ve Kırtasiye
}


def _seller_icon_logo(seller_code, size=200):
	"""Sektöre uygun ikon rozeti logo URL'si (DiceBear, PNG).

	Baş-harf avatarından farklı olarak satıcının sektörünü temsil eden bir ikon
	gösterir (alakalı, profesyonel logo). Bilinmeyen kod → nötr 'shop' ikonu.
	"""
	icon, color = SELLER_LOGO_ICONS.get(seller_code, ("shop", "0d47a1"))
	return (
		f"https://api.dicebear.com/9.x/icons/png?seed={seller_code}"
		f"&icon%5B%5D={icon}&backgroundColor={color}"
		f"&backgroundType=solid&radius=12&size={size}"
	)


def _pexels(photo_id, w=800):
	"""Pexels CDN görsel URL'si (sabit format, ücretsiz/CC0)."""
	return (
		f"https://images.pexels.com/photos/{photo_id}/"
		f"pexels-photo-{photo_id}.jpeg?auto=compress&cs=tinysrgb&w={w}"
	)


# Satıcı koduna göre SEKTÖRÜYLE ALAKALI gerçek fabrika/üretim görselleri (Pexels,
# hepsi 200 doğrulandı). Üretici kartındaki sağ galeri (gallery_images) bunları
# gösterir — ürün görseli DEĞİL, fabrika/atölye görselleri. Sektör eşleşmesi:
#   tekstil→dikim hattı, ayakkabı→deri atölyesi, elektronik→PCB üretimi,
#   hırdavat→metal/lazer kesim, gıda→üretim hattı, kozmetik→laboratuvar,
#   mutfak/züccaciye→cam/şişeleme, bijuteri→kuyum atölyesi, ambalaj→matbaa.
SELLER_FACTORY_IMAGES = {
	"DEMO-001": [31091544, 6525848, 31212954, 31112181],   # Tekstil fabrikası
	"DEMO-002": [13524733, 30433081, 11463568, 5894231],   # Ayakkabı/deri atölyesi
	"DEMO-003": [5554948, 5554949, 36522029, 4211136],     # Elektronik/PCB üretimi
	"DEMO-004": [29988964, 29224559, 34221993, 29988955],  # Metal/hırdavat üretimi
	"DEMO-005": [5953663, 5532664, 18631424, 5953831],     # Gıda/içecek üretim hattı
	"DEMO-006": [15831825, 37650270, 37466061, 20684151],  # Kozmetik laboratuvarı
	"DEMO-007": [31112181, 6525848, 31212954, 31091544],   # Ev tekstili (dokuma)
	"DEMO-008": [36423795, 5532716, 18631424],             # Cam/züccaciye/şişeleme
	"DEMO-009": [7167035, 7167004, 15955332, 33873067],    # Kuyum atölyesi
	"DEMO-010": [36376366, 9550363, 19837529],             # Ambalaj/matbaa
}

# Sektöre uygun fabrika videosu (Pexels CC0, media_type=video). Şimdilik metal/
# hırdavat üreticisinde freze tezgahı videosu; gerekirse diğer sektörlere eklenir.
# Değer: (video_url, poster_image_photo_id).
SELLER_FACTORY_VIDEOS = {
	"DEMO-004": (
		"https://videos.pexels.com/video-files/852341/852341-hd_1920_1080_30fps.mp4",
		29988964,
	),
}


# ═══════════════════════════════════════════════════════════════
#  YEREL DEMO GÖRSEL ÜRETİMİ (SVG — harici bağımlılık yok)
#  Logo, kapak, kategori kartı, niş ürün döşemesi ve sertifika rozetleri
#  app'in public/ klasörüne yazılır → /assets/tradehub_core/... ile servis edilir.
#  Tüm görseller sektöre/ürüne göre etiketli olduğu için BİREBİR ALAKALIDIR.
# ═══════════════════════════════════════════════════════════════

_ASSET_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")
_ASSET_URL = "/assets/tradehub_core"


# sektör görsel kimliği: (etiket, glif emoji, koyu renk, açık renk)
SECTOR_VISUAL = {
	"giyim": ("Tekstil & Giyim", "👕", "#5b21b6", "#8b5cf6"),
	"ayakkabi": ("Ayakkabı & Deri", "👟", "#b45309", "#f59e0b"),
	"elektronik": ("Elektronik", "💻", "#075985", "#38bdf8"),
	"hirdavat": ("Hırdavat & Nalburiye", "🔧", "#374151", "#9ca3af"),
	"gida": ("Gıda & İçecek", "🛒", "#166534", "#4ade80"),
	"kozmetik": ("Kozmetik", "💄", "#9d174d", "#f472b6"),
	"ev_tekstili": ("Ev Tekstili", "🛏️", "#115e59", "#2dd4bf"),
	"mutfak": ("Mutfak & Züccaciye", "🍳", "#9a3412", "#fb923c"),
	"bijuteri": ("Bijuteri & Aksesuar", "💎", "#a16207", "#fbbf24"),
	"kirtasiye": ("Ambalaj & Kırtasiye", "📦", "#1e40af", "#60a5fa"),
}

# sertifika rozet kimliği: ad → (kod, standart, accent renk). Özgün tasarım (telif-güvenli).
CERT_VISUAL = {
	"ISO 9001": ("ISO 9001", "ISO 9001:2015", "#1d4ed8"),
	"ISO 22000": ("ISO 22000", "ISO 22000:2018", "#15803d"),
	"ISO 22716 (GMP)": ("ISO 22716", "ISO 22716:2007", "#7c3aed"),
	"CE": ("CE", "Yönetmelik (AB) 2016/425", "#0369a1"),
	"RoHS": ("RoHS", "2011/65/AB", "#16a34a"),
	"FCC": ("FCC", "47 CFR Part 15", "#b91c1c"),
	"FDA Uyumlu": ("FDA", "21 CFR 177", "#1e40af"),
	"OEKO-TEX Standard 100": ("OEKO-TEX", "STANDARD 100", "#0d9488"),
	"GOTS": ("GOTS", "Sürüm 7.0", "#4d7c0f"),
	"FSC (Orman Sertifikası)": ("FSC", "FSC-STD-40-004", "#166534"),
	"HACCP": ("HACCP", "Codex Alimentarius", "#c2410c"),
	"Helal": ("HELAL", "OIC/SMIIC 1", "#047857"),
	"Organik Sertifika": ("ORGANİK", "(AB) 2018/848", "#65a30d"),
	"Cruelty-Free": ("CRUELTY-FREE", "Leaping Bunny", "#db2777"),
	"TSE": ("TSE", "TS Belgesi", "#1d4ed8"),
	"Ayar Damgası": ("AYAR", "TS EN ISO 8654", "#a16207"),
	"Nikel Testi": ("Ni TEST", "EN 1811", "#525252"),
	"Deri Sertifikası": ("DERİ", "TS 4521", "#92400e"),
}

_TR_MAP = str.maketrans(
	{
		"ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
		"ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
	}
)


def _asset_slug(name):
	s = (name or "").translate(_TR_MAP).lower()
	return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _svg_esc(s):
	return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _write_asset(relpath, content):
	"""SVG'yi kendi kendine yeten base64 data-URI olarak döndürür.

	Dosya servisi yerine data-URI: bu kurulumda gateway `/assets`'i Frappe backend'ine
	yönlendirmiyor (storefront tüm görselleri kendi origin'inden veya harici CDN'den
	çekiyor). Data-URI hiçbir servis yoluna bağlı değil — hem storefront `<img>`'inde
	hem Frappe admin önizlemesinde çalışır. Tüm görsel alanları DB'de `text` (64KB).
	`relpath` çağıran imza uyumluluğu için tutulur (kullanılmıyor).
	"""
	try:
		b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
		return f"data:image/svg+xml;base64,{b64}"
	except Exception:
		return None


def _grad(uid, c1, c2):
	return (
		f'<defs><linearGradient id="g{uid}" x1="0" y1="0" x2="1" y2="1">'
		f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
		f"</linearGradient></defs>"
	)


def _initials(name):
	parts = [p for p in re.split(r"\s+", (name or "").strip()) if p and p[0].isalnum()]
	return "".join(p[0] for p in parts[:2]).upper() or "TH"


def _wrap_words(text, width, maxlines):
	lines, cur = [], ""
	for w in (text or "").split():
		if len(cur) + len(w) + 1 <= width:
			cur = (cur + " " + w).strip()
		else:
			if cur:
				lines.append(cur)
			cur = w
		if len(lines) >= maxlines:
			break
	if cur and len(lines) < maxlines:
		lines.append(cur)
	return lines[:maxlines]


def _demo_logo(seller_code, name, sector):
	label, glyph, c1, c2 = SECTOR_VISUAL.get(sector, SECTOR_VISUAL["giyim"])
	svg = (
		f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" '
		f'font-family="Arial,Helvetica,sans-serif">{_grad(seller_code, c1, c2)}'
		f'<rect width="200" height="200" rx="28" fill="url(#g{seller_code})"/>'
		f'<text x="100" y="92" text-anchor="middle" font-size="62">{glyph}</text>'
		f'<text x="100" y="150" text-anchor="middle" font-size="48" font-weight="800" '
		f'fill="#ffffff" letter-spacing="2">{_svg_esc(_initials(name))}</text></svg>'
	)
	return _write_asset(f"demo/logos/{seller_code}.svg", svg)


def _demo_cover(seller_code, name, sector):
	label, glyph, c1, c2 = SECTOR_VISUAL.get(sector, SECTOR_VISUAL["giyim"])
	svg = (
		f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 400" '
		f'font-family="Arial,Helvetica,sans-serif">{_grad("c" + seller_code, c1, c2)}'
		f'<rect width="1200" height="400" fill="url(#gc{seller_code})"/>'
		f'<g fill="#ffffff" opacity="0.08"><circle cx="1050" cy="80" r="180"/>'
		f'<circle cx="200" cy="360" r="160"/></g>'
		f'<text x="80" y="170" font-size="120">{glyph}</text>'
		f'<text x="80" y="250" font-size="54" font-weight="800" fill="#ffffff">{_svg_esc(name)}</text>'
		f'<text x="84" y="300" font-size="26" fill="#ffffff" opacity="0.9" '
		f'letter-spacing="3">{_svg_esc(label.upper())}</text></svg>'
	)
	return _write_asset(f"demo/covers/{seller_code}.svg", svg)


def _demo_category_image(name, sector):
	label, glyph, c1, c2 = SECTOR_VISUAL.get(sector, SECTOR_VISUAL["giyim"])
	uid = _asset_slug(f"{sector}-{name}")[:28]
	fs = 30 if len(name) <= 16 else 22
	svg = (
		f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" '
		f'font-family="Arial,Helvetica,sans-serif">{_grad("k" + uid, c1, c2)}'
		f'<rect width="400" height="400" fill="url(#gk{uid})"/>'
		f'<g fill="#ffffff" opacity="0.10"><circle cx="330" cy="70" r="120"/></g>'
		f'<text x="200" y="186" text-anchor="middle" font-size="120">{glyph}</text>'
		f'<text x="200" y="298" text-anchor="middle" font-size="{fs}" font-weight="800" '
		f'fill="#ffffff">{_svg_esc(name)}</text>'
		f'<text x="200" y="336" text-anchor="middle" font-size="15" fill="#ffffff" '
		f'opacity="0.85" letter-spacing="2">{_svg_esc(label.upper())}</text></svg>'
	)
	return _write_asset(f"demo/cat/{uid}.svg", svg)


def _cert_fit(code):
	n = len(code)
	if n <= 4:
		return 58
	if n <= 6:
		return 46
	if n <= 9:
		return 34
	if n <= 12:
		return 24
	return 20


def _demo_cert_image(cert_name):
	"""Sertifika için özgün kare rozet SVG'si üretir. Bilinmeyen ad → None."""
	meta = CERT_VISUAL.get((cert_name or "").strip())
	if not meta:
		return None
	code, standard, accent = meta
	fs = _cert_fit(code)
	cy = fs * 0.34
	uid = _asset_slug(cert_name)
	svg = (
		f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 320" '
		f'font-family="Arial,Helvetica,sans-serif">'
		f'<defs><linearGradient id="cg{uid}" x1="0" y1="0" x2="1" y2="1">'
		f'<stop offset="0" stop-color="{accent}"/>'
		f'<stop offset="1" stop-color="{accent}" stop-opacity="0.72"/></linearGradient></defs>'
		f'<rect width="320" height="320" fill="#ffffff"/>'
		f'<g transform="translate(160 160)">'
		f'<circle r="140" fill="url(#cg{uid})"/><circle r="120" fill="#ffffff"/>'
		f'<circle r="120" fill="none" stroke="{accent}" stroke-width="4"/>'
		f'<circle r="103" fill="none" stroke="{accent}" stroke-width="1.5" stroke-dasharray="1 6"/>'
		f'<g transform="translate(0 -66)"><circle r="21" fill="{accent}"/>'
		f'<path d="M-8 0 L-2 8 L11 -9" fill="none" stroke="#ffffff" stroke-width="4.5" '
		f'stroke-linecap="round" stroke-linejoin="round"/></g>'
		f'<text y="{cy:.0f}" text-anchor="middle" font-size="{fs}" font-weight="800" '
		f'fill="{accent}">{_svg_esc(code)}</text>'
		f'<text y="48" text-anchor="middle" font-size="13" fill="#6b7280">{_svg_esc(standard)}</text>'
		f'<text y="94" text-anchor="middle" font-size="13" font-weight="700" '
		f'letter-spacing="3" fill="{accent}">SERTİFİKALI</text></g></svg>'
	)
	return _write_asset(f"certs/{uid}.svg", svg)


def _desc(title, category):
	"""Ürün için HTML açıklama üretir."""
	return (
		f"<h3>{title}</h3>"
		f"<p><strong>{title}</strong>, yüksek kaliteli malzemelerden özenle üretilmiştir. "
		f"{category} kategorisinde en çok tercih edilen ürünlerimizden biridir. "
		f"Toptan ve perakende satışa uygun, rekabetçi fiyatlarla sunulmaktadır.</p>"
		f"<ul>"
		f"<li>Birinci sınıf hammadde kullanımı</li>"
		f"<li>ISO standartlarına uygun üretim</li>"
		f"<li>Toptan alımlarda özel fiyat avantajı</li>"
		f"<li>Hızlı sevkiyat ve güvenli paketleme</li>"
		f"<li>Fatura ve garanti belgesi dahil</li>"
		f"</ul>"
		f"<p>Minimum sipariş miktarı ve toptan fiyat bilgisi için bizimle iletişime geçin.</p>"
	)


def _short(title, category):
	"""Kısa açıklama üretir."""
	return (
		f"{title} — {category} kategorisinde premium kalite. "
		f"Toptan fiyatlarla, hızlı kargo ve güvenli ödeme seçenekleriyle."
	)


# ═══════════════════════════════════════════════════════════════
#  SEKTÖR GÖRSEL HAVUZU (DummyJSON CDN)
#  Her sektör için DummyJSON'un gerçek e-ticaret ürün görselleri
#  (https://dummyjson.com/products — kategori eşleşmeli).
#  Ürünler bu havuzdan deterministik olarak görsel seçer.
# ═══════════════════════════════════════════════════════════════

SECTOR_IMAGES = {
	"giyim": [
		"https://cdn.dummyjson.com/product-images/mens-shirts/blue-%26-black-check-shirt/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/mens-shirts/blue-%26-black-check-shirt/1.webp",
		"https://cdn.dummyjson.com/product-images/mens-shirts/gigabyte-aorus-men-tshirt/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/mens-shirts/gigabyte-aorus-men-tshirt/1.webp",
		"https://cdn.dummyjson.com/product-images/mens-shirts/man-plaid-shirt/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/mens-shirts/man-plaid-shirt/1.webp",
		"https://cdn.dummyjson.com/product-images/mens-shirts/man-short-sleeve-shirt/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/mens-shirts/man-short-sleeve-shirt/1.webp",
		"https://cdn.dummyjson.com/product-images/mens-shirts/men-check-shirt/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/mens-shirts/men-check-shirt/1.webp",
		"https://cdn.dummyjson.com/product-images/tops/blue-frock/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/tops/blue-frock/1.webp",
		"https://cdn.dummyjson.com/product-images/tops/girl-summer-dress/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/tops/girl-summer-dress/1.webp",
		"https://cdn.dummyjson.com/product-images/tops/gray-dress/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/tops/gray-dress/1.webp",
	],
	"ayakkabi": [
		"https://cdn.dummyjson.com/product-images/mens-shoes/nike-air-jordan-1-red-and-black/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/mens-shoes/nike-air-jordan-1-red-and-black/1.webp",
		"https://cdn.dummyjson.com/product-images/mens-shoes/nike-baseball-cleats/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/mens-shoes/nike-baseball-cleats/1.webp",
		"https://cdn.dummyjson.com/product-images/mens-shoes/puma-future-rider-trainers/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/mens-shoes/puma-future-rider-trainers/1.webp",
		"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-%26-red/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-%26-red/1.webp",
		"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-red/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-red/1.webp",
		"https://cdn.dummyjson.com/product-images/womens-shoes/black-%26-brown-slipper/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/womens-shoes/black-%26-brown-slipper/1.webp",
		"https://cdn.dummyjson.com/product-images/womens-shoes/calvin-klein-heel-shoes/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/womens-shoes/calvin-klein-heel-shoes/1.webp",
		"https://cdn.dummyjson.com/product-images/womens-shoes/golden-shoes-woman/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/womens-shoes/golden-shoes-woman/1.webp",
	],
	"elektronik": [
		"https://cdn.dummyjson.com/product-images/smartphones/iphone-5s/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/iphone-5s/1.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/iphone-6/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/iphone-6/1.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/iphone-13-pro/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/iphone-13-pro/1.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/iphone-x/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/iphone-x/1.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/oppo-a57/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/oppo-a57/1.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/oppo-f19-pro-plus/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/oppo-f19-pro-plus/1.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/oppo-k1/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/oppo-k1/1.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/realme-c35/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/smartphones/realme-c35/1.webp",
	],
	"hirdavat": [
		"https://cdn.dummyjson.com/product-images/motorcycle/generic-motorcycle/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/motorcycle/generic-motorcycle/1.webp",
		"https://cdn.dummyjson.com/product-images/motorcycle/kawasaki-z800/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/motorcycle/kawasaki-z800/1.webp",
		"https://cdn.dummyjson.com/product-images/motorcycle/motogp-ci.h1/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/motorcycle/motogp-ci.h1/1.webp",
		"https://cdn.dummyjson.com/product-images/motorcycle/scooter-motorcycle/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/motorcycle/scooter-motorcycle/1.webp",
		"https://cdn.dummyjson.com/product-images/motorcycle/sportbike-motorcycle/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/motorcycle/sportbike-motorcycle/1.webp",
		"https://cdn.dummyjson.com/product-images/vehicle/300-touring/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/vehicle/300-touring/1.webp",
		"https://cdn.dummyjson.com/product-images/vehicle/charger-sxt-rwd/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/vehicle/charger-sxt-rwd/1.webp",
		"https://cdn.dummyjson.com/product-images/vehicle/dodge-hornet-gt-plus/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/vehicle/dodge-hornet-gt-plus/1.webp",
	],
	"gida": [
		"https://cdn.dummyjson.com/product-images/groceries/apple/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/groceries/apple/1.webp",
		"https://cdn.dummyjson.com/product-images/groceries/beef-steak/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/groceries/beef-steak/1.webp",
		"https://cdn.dummyjson.com/product-images/groceries/cat-food/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/groceries/cat-food/1.webp",
		"https://cdn.dummyjson.com/product-images/groceries/chicken-meat/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/groceries/chicken-meat/1.webp",
		"https://cdn.dummyjson.com/product-images/groceries/cooking-oil/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/groceries/cooking-oil/1.webp",
		"https://cdn.dummyjson.com/product-images/groceries/cucumber/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/groceries/cucumber/1.webp",
		"https://cdn.dummyjson.com/product-images/groceries/dog-food/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/groceries/dog-food/1.webp",
		"https://cdn.dummyjson.com/product-images/groceries/eggs/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/groceries/eggs/1.webp",
	],
	"kozmetik": [
		"https://cdn.dummyjson.com/product-images/beauty/essence-mascara-lash-princess/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/beauty/essence-mascara-lash-princess/1.webp",
		"https://cdn.dummyjson.com/product-images/beauty/eyeshadow-palette-with-mirror/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/beauty/eyeshadow-palette-with-mirror/1.webp",
		"https://cdn.dummyjson.com/product-images/beauty/powder-canister/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/beauty/powder-canister/1.webp",
		"https://cdn.dummyjson.com/product-images/beauty/red-lipstick/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/beauty/red-lipstick/1.webp",
		"https://cdn.dummyjson.com/product-images/beauty/red-nail-polish/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/beauty/red-nail-polish/1.webp",
		"https://cdn.dummyjson.com/product-images/fragrances/calvin-klein-ck-one/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/fragrances/calvin-klein-ck-one/1.webp",
		"https://cdn.dummyjson.com/product-images/fragrances/chanel-coco-noir-eau-de/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/fragrances/chanel-coco-noir-eau-de/1.webp",
		"https://cdn.dummyjson.com/product-images/fragrances/dior-j%27adore/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/fragrances/dior-j%27adore/1.webp",
	],
	"ev_tekstili": [
		"https://cdn.dummyjson.com/product-images/home-decoration/decoration-swing/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/decoration-swing/1.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/family-tree-photo-frame/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/family-tree-photo-frame/1.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/house-showpiece-plant/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/house-showpiece-plant/1.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/plant-pot/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/plant-pot/1.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/table-lamp/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/table-lamp/1.webp",
		"https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-bed/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-bed/1.webp",
		"https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-sofa/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-sofa/1.webp",
		"https://cdn.dummyjson.com/product-images/furniture/bedside-table-african-cherry/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/furniture/bedside-table-african-cherry/1.webp",
	],
	"mutfak": [
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/bamboo-spatula/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/bamboo-spatula/1.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/black-aluminium-cup/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/black-aluminium-cup/1.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/black-whisk/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/black-whisk/1.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/boxed-blender/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/boxed-blender/1.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/carbon-steel-wok/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/carbon-steel-wok/1.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/chopping-board/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/chopping-board/1.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/citrus-squeezer-yellow/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/citrus-squeezer-yellow/1.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/egg-slicer/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/kitchen-accessories/egg-slicer/1.webp",
	],
	"bijuteri": [
		"https://cdn.dummyjson.com/product-images/womens-jewellery/green-crystal-earring/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/womens-jewellery/green-crystal-earring/1.webp",
		"https://cdn.dummyjson.com/product-images/womens-jewellery/green-oval-earring/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/womens-jewellery/green-oval-earring/1.webp",
		"https://cdn.dummyjson.com/product-images/womens-jewellery/tropical-earring/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/womens-jewellery/tropical-earring/1.webp",
		"https://cdn.dummyjson.com/product-images/sunglasses/black-sun-glasses/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/sunglasses/black-sun-glasses/1.webp",
		"https://cdn.dummyjson.com/product-images/sunglasses/classic-sun-glasses/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/sunglasses/classic-sun-glasses/1.webp",
		"https://cdn.dummyjson.com/product-images/sunglasses/green-and-black-glasses/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/sunglasses/green-and-black-glasses/1.webp",
		"https://cdn.dummyjson.com/product-images/sunglasses/party-glasses/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/sunglasses/party-glasses/1.webp",
		"https://cdn.dummyjson.com/product-images/sunglasses/sunglasses/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/sunglasses/sunglasses/1.webp",
	],
	"kirtasiye": [
		"https://cdn.dummyjson.com/product-images/home-decoration/decoration-swing/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/decoration-swing/1.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/family-tree-photo-frame/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/family-tree-photo-frame/1.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/house-showpiece-plant/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/house-showpiece-plant/1.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/plant-pot/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/plant-pot/1.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/table-lamp/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/home-decoration/table-lamp/1.webp",
		"https://cdn.dummyjson.com/product-images/womens-bags/blue-women%27s-handbag/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/womens-bags/blue-women%27s-handbag/1.webp",
		"https://cdn.dummyjson.com/product-images/womens-bags/heshe-women%27s-leather-bag/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/womens-bags/heshe-women%27s-leather-bag/1.webp",
		"https://cdn.dummyjson.com/product-images/womens-bags/prada-women-bag/thumbnail.webp",
		"https://cdn.dummyjson.com/product-images/womens-bags/prada-women-bag/1.webp",
	],
}


# ═══════════════════════════════════════════════════════════════
#  VARYANT AYARLARI (sektöre göre)
# ═══════════════════════════════════════════════════════════════

VARIANT_CONFIGS = {
	"giyim": [
		{
			"attr": "Renk",
			"values": ["Siyah", "Beyaz", "Lacivert", "Kırmızı", "Gri"],
			"price_mod": [0, -5, 0, 10, -3],
		},
		{"attr": "Beden", "values": ["S", "M", "L", "XL", "XXL"], "price_mod": [0, 0, 0, 5, 10]},
	],
	"ayakkabi": [
		{"attr": "Renk", "values": ["Siyah", "Kahverengi", "Beyaz", "Tan"], "price_mod": [0, 0, -10, 5]},
		{"attr": "Numara", "values": ["39", "40", "41", "42", "43", "44"], "price_mod": [0, 0, 0, 0, 5, 10]},
	],
	"elektronik": [
		{"attr": "Renk", "values": ["Siyah", "Beyaz", "Gri"], "price_mod": [0, 0, -5]},
		{"attr": "Kapasite", "values": ["16GB", "32GB", "64GB"], "price_mod": [0, 30, 70]},
	],
	"hirdavat": [
		{"attr": "Boyut", "values": ["Küçük", "Orta", "Büyük", "Endüstriyel"], "price_mod": [0, 15, 35, 70]},
	],
	"gida": [
		{"attr": "Gramaj", "values": ["250g", "500g", "1kg", "5kg"], "price_mod": [0, 12, 30, 120]},
	],
	"kozmetik": [
		{"attr": "Hacim", "values": ["30ml", "50ml", "100ml", "200ml"], "price_mod": [0, 15, 40, 70]},
		{"attr": "Ton", "values": ["Açık", "Orta", "Koyu", "Doğal"], "price_mod": [0, 0, 0, 5]},
	],
	"ev_tekstili": [
		{"attr": "Renk", "values": ["Beyaz", "Krem", "Gri", "Mavi", "Pembe"], "price_mod": [0, 0, 5, 10, 10]},
		{"attr": "Boyut", "values": ["Tek Kişilik", "Çift Kişilik", "King Size"], "price_mod": [0, 50, 100]},
	],
	"mutfak": [
		{"attr": "Renk", "values": ["Kırmızı", "Siyah", "Beyaz", "Bakır"], "price_mod": [0, 0, -5, 15]},
		{"attr": "Boyut", "values": ["Küçük", "Orta", "Büyük"], "price_mod": [0, 25, 55]},
	],
	"bijuteri": [
		{"attr": "Renk", "values": ["Altın", "Gümüş", "Rose Gold", "Siyah"], "price_mod": [15, 0, 20, -5]},
		{"attr": "Malzeme", "values": ["925 Ayar Gümüş", "Altın Kaplama", "Çelik"], "price_mod": [60, 35, 0]},
	],
	"kirtasiye": [
		{"attr": "Renk", "values": ["Siyah", "Mavi", "Kırmızı", "Yeşil"], "price_mod": [0, 0, 0, 0]},
		{"attr": "Boyut", "values": ["A5", "A4", "A3"], "price_mod": [0, 8, 20]},
	],
}


# ═══════════════════════════════════════════════════════════════
#  SATICI PROFİLLERİ (10 adet)
# ═══════════════════════════════════════════════════════════════

SELLERS = [
	{
		"code": "DEMO-001",
		"seller_name": "Anadolu Tekstil",
		"company_name": "Anadolu Tekstil Sanayi ve Ticaret A.Ş.",
		"email": "demo-seller-01@istoc.demo",
		"sector": "Tekstil ve Giyim",
		"variant_type": "giyim",
		"price_range": (30, 500),
		"description": "1985'ten bu yana kaliteli tekstil ürünleri üreten Anadolu Tekstil, İstoç Ticaret Merkezi'nin en köklü firmalarından biridir. Geniş ürün yelpazesi ve rekabetçi fiyatlarla toptan satış hizmeti sunmaktadır.",
		"slogan": "Kaliteli Kumaş, Güvenilir Tedarik",
		"business_type": "Manufacturer",
		"founded_year": "1985",
		"staff_count": "120",
		"annual_revenue": "50M+ TL",
		"factory_size": "2500 m²",
		"certifications": "ISO 9001, OEKO-TEX Standard 100, CE",
		"phone": "+90 212 438 00 01",
		"website": "https://anadolutekstil.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 1. Ada No:15",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Garanti BBVA",
		"iban": "TR00 0001 0000 0000 0000 0001 01",
		"account_holder": "Anadolu Tekstil San. Tic. A.Ş.",
		"tax_id": "1234567001",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Enterprise",
		"commission_rate": 6.0,
		"main_markets": "Türkiye, Almanya, İngiltere, Hollanda",
	},
	{
		"code": "DEMO-002",
		"seller_name": "Boğaziçi Deri ve Ayakkabı",
		"company_name": "Boğaziçi Deri Ürünleri San. Tic. A.Ş.",
		"email": "demo-seller-02@istoc.demo",
		"sector": "Ayakkabı ve Deri",
		"variant_type": "ayakkabi",
		"price_range": (80, 1500),
		"description": "Boğaziçi Deri, 1992 yılından bu yana gerçek deri ayakkabı ve aksesuar üretimi yapmaktadır. El işçiliği ve kaliteli malzeme kullanımı ile sektörde öncü konumdadır.",
		"slogan": "Gerçek Deri, Gerçek Kalite",
		"business_type": "Manufacturer",
		"founded_year": "1992",
		"staff_count": "85",
		"annual_revenue": "35M+ TL",
		"factory_size": "1800 m²",
		"certifications": "ISO 9001, CE, Deri Sertifikası",
		"phone": "+90 212 438 00 02",
		"website": "https://bogazicideri.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 3. Ada No:42",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "İş Bankası",
		"iban": "TR00 0001 0000 0000 0000 0002 02",
		"account_holder": "Boğaziçi Deri San. Tic. A.Ş.",
		"tax_id": "1234567002",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Pro",
		"commission_rate": 7.0,
		"main_markets": "Türkiye, Rusya, Irak, Azerbaycan",
	},
	{
		"code": "DEMO-003",
		"seller_name": "Marmara Elektronik",
		"company_name": "Marmara Elektronik Tic. Ltd. Şti.",
		"email": "demo-seller-03@istoc.demo",
		"sector": "Elektronik ve Aksesuar",
		"variant_type": "elektronik",
		"price_range": (15, 500),
		"description": "Marmara Elektronik, telefon aksesuarları, bilgisayar çevre birimleri ve akıllı ev ürünlerinde geniş stok ve hızlı teslimat sunan toptancı firmadır.",
		"slogan": "Teknolojide Güvenilir Tedarik",
		"business_type": "Wholesaler",
		"founded_year": "2005",
		"staff_count": "45",
		"annual_revenue": "25M+ TL",
		"factory_size": "600 m²",
		"certifications": "CE, RoHS, FCC",
		"phone": "+90 212 438 00 03",
		"website": "https://marmaraelektronik.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 5. Ada No:8",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Yapı Kredi",
		"iban": "TR00 0001 0000 0000 0000 0003 03",
		"account_holder": "Marmara Elektronik Tic. Ltd. Şti.",
		"tax_id": "1234567003",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Pro",
		"commission_rate": 8.0,
		"main_markets": "Türkiye, Orta Doğu, Kuzey Afrika",
	},
	{
		"code": "DEMO-004",
		"seller_name": "İstanbul Hırdavat Merkezi",
		"company_name": "İstanbul Hırdavat ve Nalburiye Tic. A.Ş.",
		"email": "demo-seller-04@istoc.demo",
		"sector": "Hırdavat ve Nalburiye",
		"variant_type": "hirdavat",
		"price_range": (5, 400),
		"description": "İstanbul Hırdavat Merkezi, el aletleri, elektrikli aletler, boya malzemeleri ve tesisat ürünlerinde geniş ürün yelpazesi sunan köklü bir toptancıdır.",
		"slogan": "Her İşin Doğru Aleti",
		"business_type": "Wholesaler",
		"founded_year": "1978",
		"staff_count": "60",
		"annual_revenue": "20M+ TL",
		"factory_size": "1200 m²",
		"certifications": "ISO 9001, TSE",
		"phone": "+90 212 438 00 04",
		"website": "https://istanbulhirdavat.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 7. Ada No:23",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Halkbank",
		"iban": "TR00 0001 0000 0000 0000 0004 04",
		"account_holder": "İstanbul Hırdavat Tic. A.Ş.",
		"tax_id": "1234567004",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Pro",
		"commission_rate": 7.5,
		"main_markets": "Türkiye, Irak, Libya, Türkmenistan",
	},
	{
		"code": "DEMO-005",
		"seller_name": "Karadeniz Gıda Toptancılık",
		"company_name": "Karadeniz Gıda Tarım Ürünleri Tic. A.Ş.",
		"email": "demo-seller-05@istoc.demo",
		"sector": "Gıda ve İçecek",
		"variant_type": "gida",
		"price_range": (10, 250),
		"description": "Karadeniz Gıda, doğal ve organik gıda ürünlerinde Türkiye'nin önde gelen toptancılarından biridir. Fındık, çay, bal ve bakliyat başta olmak üzere geniş ürün gamı sunmaktadır.",
		"slogan": "Doğadan Sofranıza, Toptan Lezzet",
		"business_type": "Wholesaler",
		"founded_year": "1990",
		"staff_count": "70",
		"annual_revenue": "40M+ TL",
		"factory_size": "3000 m²",
		"certifications": "ISO 22000, HACCP, Organik Sertifika, Helal",
		"phone": "+90 212 438 00 05",
		"website": "https://karadenizgida.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 9. Ada No:5",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Ziraat Bankası",
		"iban": "TR00 0001 0000 0000 0000 0005 05",
		"account_holder": "Karadeniz Gıda Tic. A.Ş.",
		"tax_id": "1234567005",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Enterprise",
		"commission_rate": 5.0,
		"main_markets": "Türkiye, Almanya, Suudi Arabistan, BAE",
	},
	{
		"code": "DEMO-006",
		"seller_name": "Ege Kozmetik",
		"company_name": "Ege Kozmetik ve Kişisel Bakım San. A.Ş.",
		"email": "demo-seller-06@istoc.demo",
		"sector": "Kozmetik ve Kişisel Bakım",
		"variant_type": "kozmetik",
		"price_range": (15, 400),
		"description": "Ege Kozmetik, makyaj, cilt bakım ve kişisel bakım ürünlerinde yerli üretim yapan, kalite kontrol standartlarına uygun çalışan bir üretici firmadır.",
		"slogan": "Doğal Güzellik, Profesyonel Bakım",
		"business_type": "Manufacturer",
		"founded_year": "2001",
		"staff_count": "95",
		"annual_revenue": "30M+ TL",
		"factory_size": "2000 m²",
		"certifications": "ISO 22716 (GMP), ISO 9001, Cruelty-Free",
		"phone": "+90 212 438 00 06",
		"website": "https://egekozmetik.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 2. Ada No:31",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Akbank",
		"iban": "TR00 0001 0000 0000 0000 0006 06",
		"account_holder": "Ege Kozmetik San. A.Ş.",
		"tax_id": "1234567006",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Pro",
		"commission_rate": 8.0,
		"main_markets": "Türkiye, Rusya, Kazakistan, Gürcistan",
	},
	{
		"code": "DEMO-007",
		"seller_name": "Trakya Ev Tekstili",
		"company_name": "Trakya Ev Tekstili San. Tic. A.Ş.",
		"email": "demo-seller-07@istoc.demo",
		"sector": "Ev Tekstili ve Dekorasyon",
		"variant_type": "ev_tekstili",
		"price_range": (25, 800),
		"description": "Trakya Ev Tekstili, nevresim takımı, havlu, perde ve dekoratif ev ürünlerinde geniş koleksiyon sunan bir üretici firmadır. Yüksek iplik kalitesi ve modern tasarımlarla öne çıkmaktadır.",
		"slogan": "Evinize Değer Katan Tekstil",
		"business_type": "Manufacturer",
		"founded_year": "1995",
		"staff_count": "110",
		"annual_revenue": "45M+ TL",
		"factory_size": "3500 m²",
		"certifications": "ISO 9001, OEKO-TEX Standard 100, GOTS",
		"phone": "+90 212 438 00 07",
		"website": "https://trakyaev.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 4. Ada No:18",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Garanti BBVA",
		"iban": "TR00 0001 0000 0000 0000 0007 07",
		"account_holder": "Trakya Ev Tekstili San. Tic. A.Ş.",
		"tax_id": "1234567007",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Enterprise",
		"commission_rate": 6.5,
		"main_markets": "Türkiye, Almanya, Fransa, İngiltere",
	},
	{
		"code": "DEMO-008",
		"seller_name": "Akdeniz Mutfak ve Züccaciye",
		"company_name": "Akdeniz Mutfak Gereçleri Tic. Ltd. Şti.",
		"email": "demo-seller-08@istoc.demo",
		"sector": "Mutfak ve Züccaciye",
		"variant_type": "mutfak",
		"price_range": (20, 600),
		"description": "Akdeniz Mutfak, tencere, tava, porselen set ve küçük ev aletleri başta olmak üzere mutfak ve züccaciye ürünlerinde geniş stok sunan bir perakende ve toptan satıcıdır.",
		"slogan": "Mutfağınızın Güvenilir Adresi",
		"business_type": "Retailer",
		"founded_year": "2003",
		"staff_count": "40",
		"annual_revenue": "15M+ TL",
		"factory_size": "800 m²",
		"certifications": "ISO 9001, CE, FDA Uyumlu",
		"phone": "+90 212 438 00 08",
		"website": "https://akdenizmutfak.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 6. Ada No:11",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "TEB",
		"iban": "TR00 0001 0000 0000 0000 0008 08",
		"account_holder": "Akdeniz Mutfak Tic. Ltd. Şti.",
		"tax_id": "1234567008",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Basic",
		"commission_rate": 9.0,
		"main_markets": "Türkiye, Irak, Suriye",
	},
	{
		"code": "DEMO-009",
		"seller_name": "Osmanlı Aksesuar",
		"company_name": "Osmanlı Bijuteri ve Aksesuar San. A.Ş.",
		"email": "demo-seller-09@istoc.demo",
		"sector": "Bijuteri ve Aksesuar",
		"variant_type": "bijuteri",
		"price_range": (10, 500),
		"description": "Osmanlı Aksesuar, 925 ayar gümüş, altın kaplama ve çelik bijuteri ürünlerinde Osmanlı motiflerinden ilham alan özgün tasarımlar sunmaktadır.",
		"slogan": "Geleneği Taşıyan Zarafet",
		"business_type": "Manufacturer",
		"founded_year": "1998",
		"staff_count": "55",
		"annual_revenue": "20M+ TL",
		"factory_size": "900 m²",
		"certifications": "ISO 9001, Ayar Damgası, Nikel Testi",
		"phone": "+90 212 438 00 09",
		"website": "https://osmanliaksesuar.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 8. Ada No:37",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Vakıfbank",
		"iban": "TR00 0001 0000 0000 0000 0009 09",
		"account_holder": "Osmanlı Bijuteri San. A.Ş.",
		"tax_id": "1234567009",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Pro",
		"commission_rate": 7.0,
		"main_markets": "Türkiye, Suudi Arabistan, BAE, Kuveyt",
	},
	{
		"code": "DEMO-010",
		"seller_name": "Yıldız Ambalaj ve Kırtasiye",
		"company_name": "Yıldız Ambalaj Kırtasiye Tic. A.Ş.",
		"email": "demo-seller-10@istoc.demo",
		"sector": "Ambalaj ve Kırtasiye",
		"variant_type": "kirtasiye",
		"price_range": (5, 150),
		"description": "Yıldız Ambalaj, kırtasiye malzemeleri, ofis ürünleri ve ambalaj çözümlerinde geniş ürün gamı sunan bir toptan satıcıdır. Kurumsal müşterilere özel fiyatlandırma yapmaktadır.",
		"slogan": "Ofisten Depoya, Her Şey Burada",
		"business_type": "Wholesaler",
		"founded_year": "2008",
		"staff_count": "35",
		"annual_revenue": "12M+ TL",
		"factory_size": "500 m²",
		"certifications": "ISO 9001, FSC (Orman Sertifikası)",
		"phone": "+90 212 438 00 10",
		"website": "https://yildizambalaj.demo.istoc.com",
		"address_line1": "İstoç Ticaret Merkezi 10. Ada No:2",
		"district": "Bağcılar",
		"city": "İstanbul",
		"postal_code": "34030",
		"bank_name": "Denizbank",
		"iban": "TR00 0001 0000 0000 0000 0010 10",
		"account_holder": "Yıldız Ambalaj Kırtasiye Tic. A.Ş.",
		"tax_id": "1234567010",
		"tax_office": "Bağcılar VD",
		"subscription_plan": "Basic",
		"commission_rate": 9.0,
		"main_markets": "Türkiye",
	},
]


# ═══════════════════════════════════════════════════════════════
#  DEMO KYB STATUS DAĞILIMI
#  Tüm demo satıcılar KYB Verified — böylece satıcı hesapları tam
#  doğrulanmış olur (can_sell=1) ve demo akışında sürtünmesiz çalışır.
#  KYC tarafı ayrıca _set_demo_kyc_verified ile Verified'a çekilir;
#  ikisi birlikte satıcının hem satış hem direkt satın alma yetkisini açar.
#  Index, SELLERS listesinin sırasıyla eşleşir.
# ═══════════════════════════════════════════════════════════════

DEMO_KYB_STATUSES = {
	0: "Verified",  # Anadolu Tekstil
	1: "Verified",  # Boğaziçi Deri ve Ayakkabı
	2: "Verified",  # Marmara Elektronik
	3: "Verified",  # İstanbul Hırdavat Merkezi
	4: "Verified",  # Karadeniz Gıda Toptancılık
	5: "Verified",  # Ege Kozmetik
	6: "Verified",  # Trakya Ev Tekstili
	7: "Verified",  # Akdeniz Mutfak ve Züccaciye
	8: "Verified",  # Osmanlı Aksesuar
	9: "Verified",  # Yıldız Ambalaj ve Kırtasiye
}

DEMO_KYB_REJECTION_REASON = (
	"Yüklenen Ticaret Sicil Gazetesi okunaklı değil ve İmza Sirküleri'nin "
	"vergi numarası şirket başlığıyla uyuşmuyor. Lütfen güncel belgeleri "
	"yeniden yükleyiniz."
)

# KYB Verification + Seller Application belge field'ları (Attach tipi) için
# placeholder URL. Tek doğruluk kaynağı; demo akışta her belge bu PDF'i gösterir.
# Backend KYB validation .pdf/.jpg/.jpeg/.png uzantılarını kabul ediyor;
# DummyJSON CDN .webp döndürdüğü için onu kullanamıyoruz.
DEMO_KYB_DOC_URL = "https://www.africau.edu/images/default/sample.pdf"

# KYB doctype'taki tüm Attach belge field'ları. Production'da satıcı bunları
# storefront kayıt akışında tek tek yükler; demo'da hepsini aynı placeholder'la
# doldururuz.
DEMO_KYB_DOC_FIELDS = (
	"identity_document",
	"imza_sirkuleri",
	"ticaret_sicil_gazetesi",
	"faaliyet_belgesi",
	"vergi_levhasi",
	"bank_account_document",
)


# ═══════════════════════════════════════════════════════════════
#  DEMO ALICILAR (Buyer Profile)
#  5 farklı işletme tipi — satın alma tarafı için demo hesaplar
# ═══════════════════════════════════════════════════════════════

BUYERS = [
	{
		"code": "DEMO-BUYER-001",
		"email": "demo-buyer-01@istoc.demo",
		"buyer_name": "Ali Yılmaz",
		"company_name": "Yılmaz Perakende Mağazacılık Ltd. Şti.",
		"business_type": "Retailer",
		"job_title": "Satın Alma Müdürü",
		"city": "İstanbul",
		"phone": "+90 532 100 00 01",
		"employee_count": "11-50",
		"year_established": 2010,
		"sourcing_frequency": "Weekly",
		"annual_spending": "$50K-$100K",
		"industry_preferences": "Tekstil, Giyim, Aksesuar",
		"about_us": "Küçük bir perakende zinciri. Tekstil ve giyim toptancılarıyla çalışıyor.",
	},
	{
		"code": "DEMO-BUYER-002",
		"email": "demo-buyer-02@istoc.demo",
		"buyer_name": "Ayşe Demir",
		"company_name": "Demir Market A.Ş.",
		"business_type": "Wholesaler",
		"job_title": "Genel Müdür",
		"city": "Ankara",
		"phone": "+90 533 200 00 02",
		"employee_count": "51-200",
		"year_established": 2005,
		"sourcing_frequency": "Daily",
		"annual_spending": "$100K-$500K",
		"industry_preferences": "Gıda, İçecek, Kozmetik",
		"about_us": "Orta ölçekli gıda ve kozmetik toptancısı.",
	},
	{
		"code": "DEMO-BUYER-003",
		"email": "demo-buyer-03@istoc.demo",
		"buyer_name": "Mehmet Kaya",
		"company_name": "Kaya İnşaat ve Nalburiye",
		"business_type": "Distributor",
		"job_title": "Tedarik Sorumlusu",
		"city": "İzmir",
		"phone": "+90 534 300 00 03",
		"employee_count": "1-10",
		"year_established": 2015,
		"sourcing_frequency": "Monthly",
		"annual_spending": "$10K-$50K",
		"industry_preferences": "Hırdavat, İnşaat Malzemeleri",
		"about_us": "İzmir'de nalburiye ve yapı market işletmesi.",
	},
	{
		"code": "DEMO-BUYER-004",
		"email": "demo-buyer-04@istoc.demo",
		"buyer_name": "Zeynep Şahin",
		"company_name": "Şahin Otel İşletmeleri",
		"business_type": "Other",
		"job_title": "Satın Alma Uzmanı",
		"city": "Antalya",
		"phone": "+90 535 400 00 04",
		"employee_count": "201-500",
		"year_established": 2000,
		"sourcing_frequency": "Quarterly",
		"annual_spending": "$500K+",
		"industry_preferences": "Ev Tekstili, Mutfak, Aksesuar",
		"about_us": "Antalya'da 3 otel işleten zincir — mutfak/tekstil/aksesuar tedariki.",
	},
	{
		"code": "DEMO-BUYER-005",
		"email": "demo-buyer-05@istoc.demo",
		"buyer_name": "Can Özkan",
		"company_name": "Özkan Online Ticaret",
		"business_type": "Retailer",
		"job_title": "Kurucu",
		"city": "Bursa",
		"phone": "+90 536 500 00 05",
		"employee_count": "1-10",
		"year_established": 2020,
		"sourcing_frequency": "Weekly",
		"annual_spending": "Under $10K",
		"industry_preferences": "Elektronik, Aksesuar, Kırtasiye",
		"about_us": "E-ticaret satıcısı — dropshipping ve direkt satış yapıyor.",
	},
]
# ═══════════════════════════════════════════════════════════════
#  DUMMYJSON ÜRÜN VERİSİ + KATEGORİ HARİTASI
#  194 gerçek ürün (başlık + görsel + galeri). Seed her DummyJSON
#  ürününü birebir Listing olarak oluşturur — görsel/başlık uyumlu.
# ═══════════════════════════════════════════════════════════════

# DummyJSON product data — {title, thumb, imgs} lists by category (URL-encoded)
DUMMY_PRODUCTS = {
	"beauty": [
		{
			"title": "Essence Mascara Lash Princess",
			"thumb": "https://cdn.dummyjson.com/product-images/beauty/essence-mascara-lash-princess/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/beauty/essence-mascara-lash-princess/1.webp",
			],
		},
		{
			"title": "Eyeshadow Palette with Mirror",
			"thumb": "https://cdn.dummyjson.com/product-images/beauty/eyeshadow-palette-with-mirror/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/beauty/eyeshadow-palette-with-mirror/1.webp",
			],
		},
		{
			"title": "Powder Canister",
			"thumb": "https://cdn.dummyjson.com/product-images/beauty/powder-canister/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/beauty/powder-canister/1.webp",
			],
		},
		{
			"title": "Red Lipstick",
			"thumb": "https://cdn.dummyjson.com/product-images/beauty/red-lipstick/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/beauty/red-lipstick/1.webp",
			],
		},
		{
			"title": "Red Nail Polish",
			"thumb": "https://cdn.dummyjson.com/product-images/beauty/red-nail-polish/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/beauty/red-nail-polish/1.webp",
			],
		},
	],
	"fragrances": [
		{
			"title": "Calvin Klein CK One",
			"thumb": "https://cdn.dummyjson.com/product-images/fragrances/calvin-klein-ck-one/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/fragrances/calvin-klein-ck-one/1.webp",
				"https://cdn.dummyjson.com/product-images/fragrances/calvin-klein-ck-one/2.webp",
				"https://cdn.dummyjson.com/product-images/fragrances/calvin-klein-ck-one/3.webp",
			],
		},
		{
			"title": "Chanel Coco Noir Eau De",
			"thumb": "https://cdn.dummyjson.com/product-images/fragrances/chanel-coco-noir-eau-de/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/fragrances/chanel-coco-noir-eau-de/1.webp",
				"https://cdn.dummyjson.com/product-images/fragrances/chanel-coco-noir-eau-de/2.webp",
				"https://cdn.dummyjson.com/product-images/fragrances/chanel-coco-noir-eau-de/3.webp",
			],
		},
		{
			"title": "Dior J'adore",
			"thumb": "https://cdn.dummyjson.com/product-images/fragrances/dior-j%27adore/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/fragrances/dior-j%27adore/1.webp",
				"https://cdn.dummyjson.com/product-images/fragrances/dior-j%27adore/2.webp",
				"https://cdn.dummyjson.com/product-images/fragrances/dior-j%27adore/3.webp",
			],
		},
		{
			"title": "Dolce Shine Eau de",
			"thumb": "https://cdn.dummyjson.com/product-images/fragrances/dolce-shine-eau-de/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/fragrances/dolce-shine-eau-de/1.webp",
				"https://cdn.dummyjson.com/product-images/fragrances/dolce-shine-eau-de/2.webp",
				"https://cdn.dummyjson.com/product-images/fragrances/dolce-shine-eau-de/3.webp",
			],
		},
		{
			"title": "Gucci Bloom Eau de",
			"thumb": "https://cdn.dummyjson.com/product-images/fragrances/gucci-bloom-eau-de/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/fragrances/gucci-bloom-eau-de/1.webp",
				"https://cdn.dummyjson.com/product-images/fragrances/gucci-bloom-eau-de/2.webp",
				"https://cdn.dummyjson.com/product-images/fragrances/gucci-bloom-eau-de/3.webp",
			],
		},
	],
	"furniture": [
		{
			"title": "Annibale Colombo Bed",
			"thumb": "https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-bed/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-bed/1.webp",
				"https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-bed/2.webp",
				"https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-bed/3.webp",
			],
		},
		{
			"title": "Annibale Colombo Sofa",
			"thumb": "https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-sofa/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-sofa/1.webp",
				"https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-sofa/2.webp",
				"https://cdn.dummyjson.com/product-images/furniture/annibale-colombo-sofa/3.webp",
			],
		},
		{
			"title": "Bedside Table African Cherry",
			"thumb": "https://cdn.dummyjson.com/product-images/furniture/bedside-table-african-cherry/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/furniture/bedside-table-african-cherry/1.webp",
				"https://cdn.dummyjson.com/product-images/furniture/bedside-table-african-cherry/2.webp",
				"https://cdn.dummyjson.com/product-images/furniture/bedside-table-african-cherry/3.webp",
			],
		},
		{
			"title": "Knoll Saarinen Executive Conference Chair",
			"thumb": "https://cdn.dummyjson.com/product-images/furniture/knoll-saarinen-executive-conference-chair/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/furniture/knoll-saarinen-executive-conference-chair/1.webp",
				"https://cdn.dummyjson.com/product-images/furniture/knoll-saarinen-executive-conference-chair/2.webp",
				"https://cdn.dummyjson.com/product-images/furniture/knoll-saarinen-executive-conference-chair/3.webp",
			],
		},
		{
			"title": "Wooden Bathroom Sink With Mirror",
			"thumb": "https://cdn.dummyjson.com/product-images/furniture/wooden-bathroom-sink-with-mirror/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/furniture/wooden-bathroom-sink-with-mirror/1.webp",
				"https://cdn.dummyjson.com/product-images/furniture/wooden-bathroom-sink-with-mirror/2.webp",
				"https://cdn.dummyjson.com/product-images/furniture/wooden-bathroom-sink-with-mirror/3.webp",
			],
		},
	],
	"groceries": [
		{
			"title": "Apple",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/apple/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/apple/1.webp",
			],
		},
		{
			"title": "Beef Steak",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/beef-steak/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/beef-steak/1.webp",
			],
		},
		{
			"title": "Cat Food",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/cat-food/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/cat-food/1.webp",
			],
		},
		{
			"title": "Chicken Meat",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/chicken-meat/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/chicken-meat/1.webp",
				"https://cdn.dummyjson.com/product-images/groceries/chicken-meat/2.webp",
			],
		},
		{
			"title": "Cooking Oil",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/cooking-oil/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/cooking-oil/1.webp",
			],
		},
		{
			"title": "Cucumber",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/cucumber/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/cucumber/1.webp",
			],
		},
		{
			"title": "Dog Food",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/dog-food/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/dog-food/1.webp",
			],
		},
		{
			"title": "Eggs",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/eggs/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/eggs/1.webp",
			],
		},
		{
			"title": "Fish Steak",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/fish-steak/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/fish-steak/1.webp",
			],
		},
		{
			"title": "Green Bell Pepper",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/green-bell-pepper/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/green-bell-pepper/1.webp",
			],
		},
		{
			"title": "Green Chili Pepper",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/green-chili-pepper/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/green-chili-pepper/1.webp",
			],
		},
		{
			"title": "Honey Jar",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/honey-jar/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/honey-jar/1.webp",
			],
		},
		{
			"title": "Ice Cream",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/ice-cream/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/ice-cream/1.webp",
				"https://cdn.dummyjson.com/product-images/groceries/ice-cream/2.webp",
				"https://cdn.dummyjson.com/product-images/groceries/ice-cream/3.webp",
				"https://cdn.dummyjson.com/product-images/groceries/ice-cream/4.webp",
			],
		},
		{
			"title": "Juice",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/juice/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/juice/1.webp",
			],
		},
		{
			"title": "Kiwi",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/kiwi/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/kiwi/1.webp",
			],
		},
		{
			"title": "Lemon",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/lemon/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/lemon/1.webp",
			],
		},
		{
			"title": "Milk",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/milk/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/milk/1.webp",
			],
		},
		{
			"title": "Mulberry",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/mulberry/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/mulberry/1.webp",
			],
		},
		{
			"title": "Nescafe Coffee",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/nescafe-coffee/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/nescafe-coffee/1.webp",
			],
		},
		{
			"title": "Potatoes",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/potatoes/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/potatoes/1.webp",
			],
		},
		{
			"title": "Protein Powder",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/protein-powder/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/protein-powder/1.webp",
			],
		},
		{
			"title": "Red Onions",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/red-onions/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/red-onions/1.webp",
			],
		},
		{
			"title": "Rice",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/rice/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/rice/1.webp",
			],
		},
		{
			"title": "Soft Drinks",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/soft-drinks/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/soft-drinks/1.webp",
			],
		},
		{
			"title": "Strawberry",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/strawberry/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/strawberry/1.webp",
			],
		},
		{
			"title": "Tissue Paper Box",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/tissue-paper-box/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/tissue-paper-box/1.webp",
				"https://cdn.dummyjson.com/product-images/groceries/tissue-paper-box/2.webp",
			],
		},
		{
			"title": "Water",
			"thumb": "https://cdn.dummyjson.com/product-images/groceries/water/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/groceries/water/1.webp",
			],
		},
	],
	"home-decoration": [
		{
			"title": "Decoration Swing",
			"thumb": "https://cdn.dummyjson.com/product-images/home-decoration/decoration-swing/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/home-decoration/decoration-swing/1.webp",
				"https://cdn.dummyjson.com/product-images/home-decoration/decoration-swing/2.webp",
				"https://cdn.dummyjson.com/product-images/home-decoration/decoration-swing/3.webp",
			],
		},
		{
			"title": "Family Tree Photo Frame",
			"thumb": "https://cdn.dummyjson.com/product-images/home-decoration/family-tree-photo-frame/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/home-decoration/family-tree-photo-frame/1.webp",
			],
		},
		{
			"title": "House Showpiece Plant",
			"thumb": "https://cdn.dummyjson.com/product-images/home-decoration/house-showpiece-plant/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/home-decoration/house-showpiece-plant/1.webp",
				"https://cdn.dummyjson.com/product-images/home-decoration/house-showpiece-plant/2.webp",
				"https://cdn.dummyjson.com/product-images/home-decoration/house-showpiece-plant/3.webp",
			],
		},
		{
			"title": "Plant Pot",
			"thumb": "https://cdn.dummyjson.com/product-images/home-decoration/plant-pot/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/home-decoration/plant-pot/1.webp",
				"https://cdn.dummyjson.com/product-images/home-decoration/plant-pot/2.webp",
				"https://cdn.dummyjson.com/product-images/home-decoration/plant-pot/3.webp",
				"https://cdn.dummyjson.com/product-images/home-decoration/plant-pot/4.webp",
			],
		},
		{
			"title": "Table Lamp",
			"thumb": "https://cdn.dummyjson.com/product-images/home-decoration/table-lamp/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/home-decoration/table-lamp/1.webp",
			],
		},
	],
	"kitchen-accessories": [
		{
			"title": "Bamboo Spatula",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/bamboo-spatula/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/bamboo-spatula/1.webp",
			],
		},
		{
			"title": "Black Aluminium Cup",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/black-aluminium-cup/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/black-aluminium-cup/1.webp",
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/black-aluminium-cup/2.webp",
			],
		},
		{
			"title": "Black Whisk",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/black-whisk/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/black-whisk/1.webp",
			],
		},
		{
			"title": "Boxed Blender",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/boxed-blender/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/boxed-blender/1.webp",
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/boxed-blender/2.webp",
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/boxed-blender/3.webp",
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/boxed-blender/4.webp",
			],
		},
		{
			"title": "Carbon Steel Wok",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/carbon-steel-wok/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/carbon-steel-wok/1.webp",
			],
		},
		{
			"title": "Chopping Board",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/chopping-board/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/chopping-board/1.webp",
			],
		},
		{
			"title": "Citrus Squeezer Yellow",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/citrus-squeezer-yellow/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/citrus-squeezer-yellow/1.webp",
			],
		},
		{
			"title": "Egg Slicer",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/egg-slicer/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/egg-slicer/1.webp",
			],
		},
		{
			"title": "Electric Stove",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/electric-stove/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/electric-stove/1.webp",
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/electric-stove/2.webp",
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/electric-stove/3.webp",
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/electric-stove/4.webp",
			],
		},
		{
			"title": "Fine Mesh Strainer",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/fine-mesh-strainer/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/fine-mesh-strainer/1.webp",
			],
		},
		{
			"title": "Fork",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/fork/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/fork/1.webp",
			],
		},
		{
			"title": "Glass",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/glass/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/glass/1.webp",
			],
		},
		{
			"title": "Grater Black",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/grater-black/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/grater-black/1.webp",
			],
		},
		{
			"title": "Hand Blender",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/hand-blender/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/hand-blender/1.webp",
			],
		},
		{
			"title": "Ice Cube Tray",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/ice-cube-tray/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/ice-cube-tray/1.webp",
			],
		},
		{
			"title": "Kitchen Sieve",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/kitchen-sieve/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/kitchen-sieve/1.webp",
			],
		},
		{
			"title": "Knife",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/knife/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/knife/1.webp",
			],
		},
		{
			"title": "Lunch Box",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/lunch-box/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/lunch-box/1.webp",
			],
		},
		{
			"title": "Microwave Oven",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/microwave-oven/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/microwave-oven/1.webp",
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/microwave-oven/2.webp",
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/microwave-oven/3.webp",
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/microwave-oven/4.webp",
			],
		},
		{
			"title": "Mug Tree Stand",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/mug-tree-stand/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/mug-tree-stand/1.webp",
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/mug-tree-stand/2.webp",
			],
		},
		{
			"title": "Pan",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/pan/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/pan/1.webp",
			],
		},
		{
			"title": "Plate",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/plate/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/plate/1.webp",
			],
		},
		{
			"title": "Red Tongs",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/red-tongs/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/red-tongs/1.webp",
			],
		},
		{
			"title": "Silver Pot With Glass Cap",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/silver-pot-with-glass-cap/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/silver-pot-with-glass-cap/1.webp",
			],
		},
		{
			"title": "Slotted Turner",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/slotted-turner/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/slotted-turner/1.webp",
			],
		},
		{
			"title": "Spice Rack",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/spice-rack/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/spice-rack/1.webp",
			],
		},
		{
			"title": "Spoon",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/spoon/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/spoon/1.webp",
			],
		},
		{
			"title": "Tray",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/tray/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/tray/1.webp",
			],
		},
		{
			"title": "Wooden Rolling Pin",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/wooden-rolling-pin/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/wooden-rolling-pin/1.webp",
			],
		},
		{
			"title": "Yellow Peeler",
			"thumb": "https://cdn.dummyjson.com/product-images/kitchen-accessories/yellow-peeler/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/kitchen-accessories/yellow-peeler/1.webp",
			],
		},
	],
	"laptops": [
		{
			"title": "Apple MacBook Pro 14 Inch Space Grey",
			"thumb": "https://cdn.dummyjson.com/product-images/laptops/apple-macbook-pro-14-inch-space-grey/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/laptops/apple-macbook-pro-14-inch-space-grey/1.webp",
				"https://cdn.dummyjson.com/product-images/laptops/apple-macbook-pro-14-inch-space-grey/2.webp",
				"https://cdn.dummyjson.com/product-images/laptops/apple-macbook-pro-14-inch-space-grey/3.webp",
			],
		},
		{
			"title": "Asus Zenbook Pro Dual Screen Laptop",
			"thumb": "https://cdn.dummyjson.com/product-images/laptops/asus-zenbook-pro-dual-screen-laptop/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/laptops/asus-zenbook-pro-dual-screen-laptop/1.webp",
				"https://cdn.dummyjson.com/product-images/laptops/asus-zenbook-pro-dual-screen-laptop/2.webp",
				"https://cdn.dummyjson.com/product-images/laptops/asus-zenbook-pro-dual-screen-laptop/3.webp",
			],
		},
		{
			"title": "Huawei Matebook X Pro",
			"thumb": "https://cdn.dummyjson.com/product-images/laptops/huawei-matebook-x-pro/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/laptops/huawei-matebook-x-pro/1.webp",
				"https://cdn.dummyjson.com/product-images/laptops/huawei-matebook-x-pro/2.webp",
				"https://cdn.dummyjson.com/product-images/laptops/huawei-matebook-x-pro/3.webp",
			],
		},
		{
			"title": "Lenovo Yoga 920",
			"thumb": "https://cdn.dummyjson.com/product-images/laptops/lenovo-yoga-920/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/laptops/lenovo-yoga-920/1.webp",
				"https://cdn.dummyjson.com/product-images/laptops/lenovo-yoga-920/2.webp",
				"https://cdn.dummyjson.com/product-images/laptops/lenovo-yoga-920/3.webp",
			],
		},
		{
			"title": "New DELL XPS 13 9300 Laptop",
			"thumb": "https://cdn.dummyjson.com/product-images/laptops/new-dell-xps-13-9300-laptop/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/laptops/new-dell-xps-13-9300-laptop/1.webp",
				"https://cdn.dummyjson.com/product-images/laptops/new-dell-xps-13-9300-laptop/2.webp",
				"https://cdn.dummyjson.com/product-images/laptops/new-dell-xps-13-9300-laptop/3.webp",
			],
		},
	],
	"mens-shirts": [
		{
			"title": "Blue & Black Check Shirt",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-shirts/blue-%26-black-check-shirt/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-shirts/blue-%26-black-check-shirt/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/blue-%26-black-check-shirt/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/blue-%26-black-check-shirt/3.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/blue-%26-black-check-shirt/4.webp",
			],
		},
		{
			"title": "Gigabyte Aorus Men Tshirt",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-shirts/gigabyte-aorus-men-tshirt/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-shirts/gigabyte-aorus-men-tshirt/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/gigabyte-aorus-men-tshirt/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/gigabyte-aorus-men-tshirt/3.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/gigabyte-aorus-men-tshirt/4.webp",
			],
		},
		{
			"title": "Man Plaid Shirt",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-shirts/man-plaid-shirt/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-shirts/man-plaid-shirt/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/man-plaid-shirt/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/man-plaid-shirt/3.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/man-plaid-shirt/4.webp",
			],
		},
		{
			"title": "Man Short Sleeve Shirt",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-shirts/man-short-sleeve-shirt/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-shirts/man-short-sleeve-shirt/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/man-short-sleeve-shirt/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/man-short-sleeve-shirt/3.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/man-short-sleeve-shirt/4.webp",
			],
		},
		{
			"title": "Men Check Shirt",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-shirts/men-check-shirt/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-shirts/men-check-shirt/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/men-check-shirt/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/men-check-shirt/3.webp",
				"https://cdn.dummyjson.com/product-images/mens-shirts/men-check-shirt/4.webp",
			],
		},
	],
	"mens-shoes": [
		{
			"title": "Nike Air Jordan 1 Red And Black",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-shoes/nike-air-jordan-1-red-and-black/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-shoes/nike-air-jordan-1-red-and-black/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/nike-air-jordan-1-red-and-black/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/nike-air-jordan-1-red-and-black/3.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/nike-air-jordan-1-red-and-black/4.webp",
			],
		},
		{
			"title": "Nike Baseball Cleats",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-shoes/nike-baseball-cleats/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-shoes/nike-baseball-cleats/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/nike-baseball-cleats/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/nike-baseball-cleats/3.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/nike-baseball-cleats/4.webp",
			],
		},
		{
			"title": "Puma Future Rider Trainers",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-shoes/puma-future-rider-trainers/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-shoes/puma-future-rider-trainers/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/puma-future-rider-trainers/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/puma-future-rider-trainers/3.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/puma-future-rider-trainers/4.webp",
			],
		},
		{
			"title": "Sports Sneakers Off White & Red",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-%26-red/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-%26-red/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-%26-red/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-%26-red/3.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-%26-red/4.webp",
			],
		},
		{
			"title": "Sports Sneakers Off White Red",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-red/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-red/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-red/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-red/3.webp",
				"https://cdn.dummyjson.com/product-images/mens-shoes/sports-sneakers-off-white-red/4.webp",
			],
		},
	],
	"mens-watches": [
		{
			"title": "Brown Leather Belt Watch",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-watches/brown-leather-belt-watch/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-watches/brown-leather-belt-watch/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/brown-leather-belt-watch/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/brown-leather-belt-watch/3.webp",
			],
		},
		{
			"title": "Longines Master Collection",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-watches/longines-master-collection/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-watches/longines-master-collection/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/longines-master-collection/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/longines-master-collection/3.webp",
			],
		},
		{
			"title": "Rolex Cellini Date Black Dial",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-watches/rolex-cellini-date-black-dial/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-cellini-date-black-dial/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-cellini-date-black-dial/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-cellini-date-black-dial/3.webp",
			],
		},
		{
			"title": "Rolex Cellini Moonphase",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-watches/rolex-cellini-moonphase/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-cellini-moonphase/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-cellini-moonphase/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-cellini-moonphase/3.webp",
			],
		},
		{
			"title": "Rolex Datejust",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-watches/rolex-datejust/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-datejust/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-datejust/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-datejust/3.webp",
			],
		},
		{
			"title": "Rolex Submariner Watch",
			"thumb": "https://cdn.dummyjson.com/product-images/mens-watches/rolex-submariner-watch/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-submariner-watch/1.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-submariner-watch/2.webp",
				"https://cdn.dummyjson.com/product-images/mens-watches/rolex-submariner-watch/3.webp",
			],
		},
	],
	"mobile-accessories": [
		{
			"title": "Amazon Echo Plus",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/amazon-echo-plus/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/amazon-echo-plus/1.webp",
				"https://cdn.dummyjson.com/product-images/mobile-accessories/amazon-echo-plus/2.webp",
			],
		},
		{
			"title": "Apple Airpods",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/apple-airpods/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-airpods/1.webp",
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-airpods/2.webp",
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-airpods/3.webp",
			],
		},
		{
			"title": "Apple AirPods Max Silver",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/apple-airpods-max-silver/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-airpods-max-silver/1.webp",
			],
		},
		{
			"title": "Apple Airpower Wireless Charger",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/apple-airpower-wireless-charger/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-airpower-wireless-charger/1.webp",
			],
		},
		{
			"title": "Apple HomePod Mini Cosmic Grey",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/apple-homepod-mini-cosmic-grey/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-homepod-mini-cosmic-grey/1.webp",
			],
		},
		{
			"title": "Apple iPhone Charger",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/apple-iphone-charger/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-iphone-charger/1.webp",
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-iphone-charger/2.webp",
			],
		},
		{
			"title": "Apple MagSafe Battery Pack",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/apple-magsafe-battery-pack/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-magsafe-battery-pack/1.webp",
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-magsafe-battery-pack/2.webp",
			],
		},
		{
			"title": "Apple Watch Series 4 Gold",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/apple-watch-series-4-gold/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-watch-series-4-gold/1.webp",
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-watch-series-4-gold/2.webp",
				"https://cdn.dummyjson.com/product-images/mobile-accessories/apple-watch-series-4-gold/3.webp",
			],
		},
		{
			"title": "Beats Flex Wireless Earphones",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/beats-flex-wireless-earphones/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/beats-flex-wireless-earphones/1.webp",
			],
		},
		{
			"title": "iPhone 12 Silicone Case with MagSafe Plum",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/iphone-12-silicone-case-with-magsafe-plum/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/iphone-12-silicone-case-with-magsafe-plum/1.webp",
				"https://cdn.dummyjson.com/product-images/mobile-accessories/iphone-12-silicone-case-with-magsafe-plum/2.webp",
				"https://cdn.dummyjson.com/product-images/mobile-accessories/iphone-12-silicone-case-with-magsafe-plum/3.webp",
				"https://cdn.dummyjson.com/product-images/mobile-accessories/iphone-12-silicone-case-with-magsafe-plum/4.webp",
			],
		},
		{
			"title": "Monopod",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/monopod/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/monopod/1.webp",
				"https://cdn.dummyjson.com/product-images/mobile-accessories/monopod/2.webp",
			],
		},
		{
			"title": "Selfie Lamp with iPhone",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/selfie-lamp-with-iphone/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/selfie-lamp-with-iphone/1.webp",
			],
		},
		{
			"title": "Selfie Stick Monopod",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/selfie-stick-monopod/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/selfie-stick-monopod/1.webp",
			],
		},
		{
			"title": "TV Studio Camera Pedestal",
			"thumb": "https://cdn.dummyjson.com/product-images/mobile-accessories/tv-studio-camera-pedestal/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/mobile-accessories/tv-studio-camera-pedestal/1.webp",
			],
		},
	],
	"motorcycle": [
		{
			"title": "Generic Motorcycle",
			"thumb": "https://cdn.dummyjson.com/product-images/motorcycle/generic-motorcycle/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/motorcycle/generic-motorcycle/1.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/generic-motorcycle/2.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/generic-motorcycle/3.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/generic-motorcycle/4.webp",
			],
		},
		{
			"title": "Kawasaki Z800",
			"thumb": "https://cdn.dummyjson.com/product-images/motorcycle/kawasaki-z800/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/motorcycle/kawasaki-z800/1.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/kawasaki-z800/2.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/kawasaki-z800/3.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/kawasaki-z800/4.webp",
			],
		},
		{
			"title": "MotoGP CI.H1",
			"thumb": "https://cdn.dummyjson.com/product-images/motorcycle/motogp-ci.h1/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/motorcycle/motogp-ci.h1/1.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/motogp-ci.h1/2.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/motogp-ci.h1/3.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/motogp-ci.h1/4.webp",
			],
		},
		{
			"title": "Scooter Motorcycle",
			"thumb": "https://cdn.dummyjson.com/product-images/motorcycle/scooter-motorcycle/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/motorcycle/scooter-motorcycle/1.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/scooter-motorcycle/2.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/scooter-motorcycle/3.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/scooter-motorcycle/4.webp",
			],
		},
		{
			"title": "Sportbike Motorcycle",
			"thumb": "https://cdn.dummyjson.com/product-images/motorcycle/sportbike-motorcycle/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/motorcycle/sportbike-motorcycle/1.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/sportbike-motorcycle/2.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/sportbike-motorcycle/3.webp",
				"https://cdn.dummyjson.com/product-images/motorcycle/sportbike-motorcycle/4.webp",
			],
		},
	],
	"skin-care": [
		{
			"title": "Attitude Super Leaves Hand Soap",
			"thumb": "https://cdn.dummyjson.com/product-images/skin-care/attitude-super-leaves-hand-soap/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/skin-care/attitude-super-leaves-hand-soap/1.webp",
				"https://cdn.dummyjson.com/product-images/skin-care/attitude-super-leaves-hand-soap/2.webp",
				"https://cdn.dummyjson.com/product-images/skin-care/attitude-super-leaves-hand-soap/3.webp",
			],
		},
		{
			"title": "Olay Ultra Moisture Shea Butter Body Wash",
			"thumb": "https://cdn.dummyjson.com/product-images/skin-care/olay-ultra-moisture-shea-butter-body-wash/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/skin-care/olay-ultra-moisture-shea-butter-body-wash/1.webp",
				"https://cdn.dummyjson.com/product-images/skin-care/olay-ultra-moisture-shea-butter-body-wash/2.webp",
				"https://cdn.dummyjson.com/product-images/skin-care/olay-ultra-moisture-shea-butter-body-wash/3.webp",
			],
		},
		{
			"title": "Vaseline Men Body and Face Lotion",
			"thumb": "https://cdn.dummyjson.com/product-images/skin-care/vaseline-men-body-and-face-lotion/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/skin-care/vaseline-men-body-and-face-lotion/1.webp",
				"https://cdn.dummyjson.com/product-images/skin-care/vaseline-men-body-and-face-lotion/2.webp",
				"https://cdn.dummyjson.com/product-images/skin-care/vaseline-men-body-and-face-lotion/3.webp",
			],
		},
	],
	"smartphones": [
		{
			"title": "iPhone 5s",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/iphone-5s/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-5s/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-5s/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-5s/3.webp",
			],
		},
		{
			"title": "iPhone 6",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/iphone-6/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-6/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-6/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-6/3.webp",
			],
		},
		{
			"title": "iPhone 13 Pro",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/iphone-13-pro/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-13-pro/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-13-pro/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-13-pro/3.webp",
			],
		},
		{
			"title": "iPhone X",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/iphone-x/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-x/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-x/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/iphone-x/3.webp",
			],
		},
		{
			"title": "Oppo A57",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/oppo-a57/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/oppo-a57/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/oppo-a57/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/oppo-a57/3.webp",
			],
		},
		{
			"title": "Oppo F19 Pro Plus",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/oppo-f19-pro-plus/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/oppo-f19-pro-plus/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/oppo-f19-pro-plus/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/oppo-f19-pro-plus/3.webp",
			],
		},
		{
			"title": "Oppo K1",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/oppo-k1/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/oppo-k1/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/oppo-k1/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/oppo-k1/3.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/oppo-k1/4.webp",
			],
		},
		{
			"title": "Realme C35",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/realme-c35/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/realme-c35/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/realme-c35/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/realme-c35/3.webp",
			],
		},
		{
			"title": "Realme X",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/realme-x/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/realme-x/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/realme-x/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/realme-x/3.webp",
			],
		},
		{
			"title": "Realme XT",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/realme-xt/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/realme-xt/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/realme-xt/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/realme-xt/3.webp",
			],
		},
		{
			"title": "Samsung Galaxy S7",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s7/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s7/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s7/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s7/3.webp",
			],
		},
		{
			"title": "Samsung Galaxy S8",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s8/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s8/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s8/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s8/3.webp",
			],
		},
		{
			"title": "Samsung Galaxy S10",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s10/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s10/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s10/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/samsung-galaxy-s10/3.webp",
			],
		},
		{
			"title": "Vivo S1",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/vivo-s1/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/vivo-s1/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/vivo-s1/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/vivo-s1/3.webp",
			],
		},
		{
			"title": "Vivo V9",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/vivo-v9/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/vivo-v9/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/vivo-v9/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/vivo-v9/3.webp",
			],
		},
		{
			"title": "Vivo X21",
			"thumb": "https://cdn.dummyjson.com/product-images/smartphones/vivo-x21/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/smartphones/vivo-x21/1.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/vivo-x21/2.webp",
				"https://cdn.dummyjson.com/product-images/smartphones/vivo-x21/3.webp",
			],
		},
	],
	"sports-accessories": [
		{
			"title": "American Football",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/american-football/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/american-football/1.webp",
			],
		},
		{
			"title": "Baseball Ball",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/baseball-ball/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/baseball-ball/1.webp",
			],
		},
		{
			"title": "Baseball Glove",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/baseball-glove/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/baseball-glove/1.webp",
				"https://cdn.dummyjson.com/product-images/sports-accessories/baseball-glove/2.webp",
				"https://cdn.dummyjson.com/product-images/sports-accessories/baseball-glove/3.webp",
			],
		},
		{
			"title": "Basketball",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/basketball/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/basketball/1.webp",
			],
		},
		{
			"title": "Basketball Rim",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/basketball-rim/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/basketball-rim/1.webp",
			],
		},
		{
			"title": "Cricket Ball",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/cricket-ball/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/cricket-ball/1.webp",
			],
		},
		{
			"title": "Cricket Bat",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/cricket-bat/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/cricket-bat/1.webp",
			],
		},
		{
			"title": "Cricket Helmet",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/cricket-helmet/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/cricket-helmet/1.webp",
				"https://cdn.dummyjson.com/product-images/sports-accessories/cricket-helmet/2.webp",
				"https://cdn.dummyjson.com/product-images/sports-accessories/cricket-helmet/3.webp",
				"https://cdn.dummyjson.com/product-images/sports-accessories/cricket-helmet/4.webp",
			],
		},
		{
			"title": "Cricket Wicket",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/cricket-wicket/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/cricket-wicket/1.webp",
			],
		},
		{
			"title": "Feather Shuttlecock",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/feather-shuttlecock/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/feather-shuttlecock/1.webp",
			],
		},
		{
			"title": "Football",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/football/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/football/1.webp",
			],
		},
		{
			"title": "Golf Ball",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/golf-ball/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/golf-ball/1.webp",
			],
		},
		{
			"title": "Iron Golf",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/iron-golf/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/iron-golf/1.webp",
			],
		},
		{
			"title": "Metal Baseball Bat",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/metal-baseball-bat/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/metal-baseball-bat/1.webp",
			],
		},
		{
			"title": "Tennis Ball",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/tennis-ball/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/tennis-ball/1.webp",
			],
		},
		{
			"title": "Tennis Racket",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/tennis-racket/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/tennis-racket/1.webp",
			],
		},
		{
			"title": "Volleyball",
			"thumb": "https://cdn.dummyjson.com/product-images/sports-accessories/volleyball/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sports-accessories/volleyball/1.webp",
			],
		},
	],
	"sunglasses": [
		{
			"title": "Black Sun Glasses",
			"thumb": "https://cdn.dummyjson.com/product-images/sunglasses/black-sun-glasses/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sunglasses/black-sun-glasses/1.webp",
				"https://cdn.dummyjson.com/product-images/sunglasses/black-sun-glasses/2.webp",
				"https://cdn.dummyjson.com/product-images/sunglasses/black-sun-glasses/3.webp",
			],
		},
		{
			"title": "Classic Sun Glasses",
			"thumb": "https://cdn.dummyjson.com/product-images/sunglasses/classic-sun-glasses/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sunglasses/classic-sun-glasses/1.webp",
				"https://cdn.dummyjson.com/product-images/sunglasses/classic-sun-glasses/2.webp",
				"https://cdn.dummyjson.com/product-images/sunglasses/classic-sun-glasses/3.webp",
			],
		},
		{
			"title": "Green and Black Glasses",
			"thumb": "https://cdn.dummyjson.com/product-images/sunglasses/green-and-black-glasses/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sunglasses/green-and-black-glasses/1.webp",
				"https://cdn.dummyjson.com/product-images/sunglasses/green-and-black-glasses/2.webp",
				"https://cdn.dummyjson.com/product-images/sunglasses/green-and-black-glasses/3.webp",
			],
		},
		{
			"title": "Party Glasses",
			"thumb": "https://cdn.dummyjson.com/product-images/sunglasses/party-glasses/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sunglasses/party-glasses/1.webp",
				"https://cdn.dummyjson.com/product-images/sunglasses/party-glasses/2.webp",
				"https://cdn.dummyjson.com/product-images/sunglasses/party-glasses/3.webp",
			],
		},
		{
			"title": "Sunglasses",
			"thumb": "https://cdn.dummyjson.com/product-images/sunglasses/sunglasses/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/sunglasses/sunglasses/1.webp",
				"https://cdn.dummyjson.com/product-images/sunglasses/sunglasses/2.webp",
				"https://cdn.dummyjson.com/product-images/sunglasses/sunglasses/3.webp",
			],
		},
	],
	"tablets": [
		{
			"title": "iPad Mini 2021 Starlight",
			"thumb": "https://cdn.dummyjson.com/product-images/tablets/ipad-mini-2021-starlight/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/tablets/ipad-mini-2021-starlight/1.webp",
				"https://cdn.dummyjson.com/product-images/tablets/ipad-mini-2021-starlight/2.webp",
				"https://cdn.dummyjson.com/product-images/tablets/ipad-mini-2021-starlight/3.webp",
				"https://cdn.dummyjson.com/product-images/tablets/ipad-mini-2021-starlight/4.webp",
			],
		},
		{
			"title": "Samsung Galaxy Tab S8 Plus Grey",
			"thumb": "https://cdn.dummyjson.com/product-images/tablets/samsung-galaxy-tab-s8-plus-grey/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/tablets/samsung-galaxy-tab-s8-plus-grey/1.webp",
				"https://cdn.dummyjson.com/product-images/tablets/samsung-galaxy-tab-s8-plus-grey/2.webp",
				"https://cdn.dummyjson.com/product-images/tablets/samsung-galaxy-tab-s8-plus-grey/3.webp",
				"https://cdn.dummyjson.com/product-images/tablets/samsung-galaxy-tab-s8-plus-grey/4.webp",
			],
		},
		{
			"title": "Samsung Galaxy Tab White",
			"thumb": "https://cdn.dummyjson.com/product-images/tablets/samsung-galaxy-tab-white/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/tablets/samsung-galaxy-tab-white/1.webp",
				"https://cdn.dummyjson.com/product-images/tablets/samsung-galaxy-tab-white/2.webp",
				"https://cdn.dummyjson.com/product-images/tablets/samsung-galaxy-tab-white/3.webp",
				"https://cdn.dummyjson.com/product-images/tablets/samsung-galaxy-tab-white/4.webp",
			],
		},
	],
	"tops": [
		{
			"title": "Blue Frock",
			"thumb": "https://cdn.dummyjson.com/product-images/tops/blue-frock/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/tops/blue-frock/1.webp",
				"https://cdn.dummyjson.com/product-images/tops/blue-frock/2.webp",
				"https://cdn.dummyjson.com/product-images/tops/blue-frock/3.webp",
				"https://cdn.dummyjson.com/product-images/tops/blue-frock/4.webp",
			],
		},
		{
			"title": "Girl Summer Dress",
			"thumb": "https://cdn.dummyjson.com/product-images/tops/girl-summer-dress/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/tops/girl-summer-dress/1.webp",
				"https://cdn.dummyjson.com/product-images/tops/girl-summer-dress/2.webp",
				"https://cdn.dummyjson.com/product-images/tops/girl-summer-dress/3.webp",
				"https://cdn.dummyjson.com/product-images/tops/girl-summer-dress/4.webp",
			],
		},
		{
			"title": "Gray Dress",
			"thumb": "https://cdn.dummyjson.com/product-images/tops/gray-dress/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/tops/gray-dress/1.webp",
				"https://cdn.dummyjson.com/product-images/tops/gray-dress/2.webp",
				"https://cdn.dummyjson.com/product-images/tops/gray-dress/3.webp",
				"https://cdn.dummyjson.com/product-images/tops/gray-dress/4.webp",
			],
		},
		{
			"title": "Short Frock",
			"thumb": "https://cdn.dummyjson.com/product-images/tops/short-frock/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/tops/short-frock/1.webp",
				"https://cdn.dummyjson.com/product-images/tops/short-frock/2.webp",
				"https://cdn.dummyjson.com/product-images/tops/short-frock/3.webp",
				"https://cdn.dummyjson.com/product-images/tops/short-frock/4.webp",
			],
		},
		{
			"title": "Tartan Dress",
			"thumb": "https://cdn.dummyjson.com/product-images/tops/tartan-dress/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/tops/tartan-dress/1.webp",
				"https://cdn.dummyjson.com/product-images/tops/tartan-dress/2.webp",
				"https://cdn.dummyjson.com/product-images/tops/tartan-dress/3.webp",
				"https://cdn.dummyjson.com/product-images/tops/tartan-dress/4.webp",
			],
		},
	],
	"vehicle": [
		{
			"title": "300 Touring",
			"thumb": "https://cdn.dummyjson.com/product-images/vehicle/300-touring/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/vehicle/300-touring/1.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/300-touring/2.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/300-touring/3.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/300-touring/4.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/300-touring/5.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/300-touring/6.webp",
			],
		},
		{
			"title": "Charger SXT RWD",
			"thumb": "https://cdn.dummyjson.com/product-images/vehicle/charger-sxt-rwd/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/vehicle/charger-sxt-rwd/1.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/charger-sxt-rwd/2.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/charger-sxt-rwd/3.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/charger-sxt-rwd/4.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/charger-sxt-rwd/5.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/charger-sxt-rwd/6.webp",
			],
		},
		{
			"title": "Dodge Hornet GT Plus",
			"thumb": "https://cdn.dummyjson.com/product-images/vehicle/dodge-hornet-gt-plus/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/vehicle/dodge-hornet-gt-plus/1.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/dodge-hornet-gt-plus/2.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/dodge-hornet-gt-plus/3.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/dodge-hornet-gt-plus/4.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/dodge-hornet-gt-plus/5.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/dodge-hornet-gt-plus/6.webp",
			],
		},
		{
			"title": "Durango SXT RWD",
			"thumb": "https://cdn.dummyjson.com/product-images/vehicle/durango-sxt-rwd/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/vehicle/durango-sxt-rwd/1.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/durango-sxt-rwd/2.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/durango-sxt-rwd/3.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/durango-sxt-rwd/4.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/durango-sxt-rwd/5.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/durango-sxt-rwd/6.webp",
			],
		},
		{
			"title": "Pacifica Touring",
			"thumb": "https://cdn.dummyjson.com/product-images/vehicle/pacifica-touring/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/vehicle/pacifica-touring/1.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/pacifica-touring/2.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/pacifica-touring/3.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/pacifica-touring/4.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/pacifica-touring/5.webp",
				"https://cdn.dummyjson.com/product-images/vehicle/pacifica-touring/6.webp",
			],
		},
	],
	"womens-bags": [
		{
			"title": "Blue Women's Handbag",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-bags/blue-women%27s-handbag/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-bags/blue-women%27s-handbag/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-bags/blue-women%27s-handbag/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-bags/blue-women%27s-handbag/3.webp",
			],
		},
		{
			"title": "Heshe Women's Leather Bag",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-bags/heshe-women%27s-leather-bag/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-bags/heshe-women%27s-leather-bag/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-bags/heshe-women%27s-leather-bag/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-bags/heshe-women%27s-leather-bag/3.webp",
			],
		},
		{
			"title": "Prada Women Bag",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-bags/prada-women-bag/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-bags/prada-women-bag/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-bags/prada-women-bag/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-bags/prada-women-bag/3.webp",
			],
		},
		{
			"title": "White Faux Leather Backpack",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-bags/white-faux-leather-backpack/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-bags/white-faux-leather-backpack/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-bags/white-faux-leather-backpack/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-bags/white-faux-leather-backpack/3.webp",
			],
		},
		{
			"title": "Women Handbag Black",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-bags/women-handbag-black/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-bags/women-handbag-black/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-bags/women-handbag-black/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-bags/women-handbag-black/3.webp",
			],
		},
	],
	"womens-dresses": [
		{
			"title": "Black Women's Gown",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-dresses/black-women%27s-gown/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-dresses/black-women%27s-gown/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/black-women%27s-gown/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/black-women%27s-gown/3.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/black-women%27s-gown/4.webp",
			],
		},
		{
			"title": "Corset Leather With Skirt",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-dresses/corset-leather-with-skirt/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-dresses/corset-leather-with-skirt/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/corset-leather-with-skirt/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/corset-leather-with-skirt/3.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/corset-leather-with-skirt/4.webp",
			],
		},
		{
			"title": "Corset With Black Skirt",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-dresses/corset-with-black-skirt/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-dresses/corset-with-black-skirt/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/corset-with-black-skirt/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/corset-with-black-skirt/3.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/corset-with-black-skirt/4.webp",
			],
		},
		{
			"title": "Dress Pea",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-dresses/dress-pea/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-dresses/dress-pea/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/dress-pea/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/dress-pea/3.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/dress-pea/4.webp",
			],
		},
		{
			"title": "Marni Red & Black Suit",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-dresses/marni-red-%26-black-suit/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-dresses/marni-red-%26-black-suit/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/marni-red-%26-black-suit/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/marni-red-%26-black-suit/3.webp",
				"https://cdn.dummyjson.com/product-images/womens-dresses/marni-red-%26-black-suit/4.webp",
			],
		},
	],
	"womens-jewellery": [
		{
			"title": "Green Crystal Earring",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-jewellery/green-crystal-earring/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-jewellery/green-crystal-earring/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-jewellery/green-crystal-earring/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-jewellery/green-crystal-earring/3.webp",
			],
		},
		{
			"title": "Green Oval Earring",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-jewellery/green-oval-earring/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-jewellery/green-oval-earring/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-jewellery/green-oval-earring/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-jewellery/green-oval-earring/3.webp",
			],
		},
		{
			"title": "Tropical Earring",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-jewellery/tropical-earring/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-jewellery/tropical-earring/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-jewellery/tropical-earring/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-jewellery/tropical-earring/3.webp",
			],
		},
	],
	"womens-shoes": [
		{
			"title": "Black & Brown Slipper",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-shoes/black-%26-brown-slipper/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-shoes/black-%26-brown-slipper/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/black-%26-brown-slipper/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/black-%26-brown-slipper/3.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/black-%26-brown-slipper/4.webp",
			],
		},
		{
			"title": "Calvin Klein Heel Shoes",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-shoes/calvin-klein-heel-shoes/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-shoes/calvin-klein-heel-shoes/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/calvin-klein-heel-shoes/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/calvin-klein-heel-shoes/3.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/calvin-klein-heel-shoes/4.webp",
			],
		},
		{
			"title": "Golden Shoes Woman",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-shoes/golden-shoes-woman/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-shoes/golden-shoes-woman/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/golden-shoes-woman/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/golden-shoes-woman/3.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/golden-shoes-woman/4.webp",
			],
		},
		{
			"title": "Pampi Shoes",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-shoes/pampi-shoes/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-shoes/pampi-shoes/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/pampi-shoes/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/pampi-shoes/3.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/pampi-shoes/4.webp",
			],
		},
		{
			"title": "Red Shoes",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-shoes/red-shoes/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-shoes/red-shoes/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/red-shoes/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/red-shoes/3.webp",
				"https://cdn.dummyjson.com/product-images/womens-shoes/red-shoes/4.webp",
			],
		},
	],
	"womens-watches": [
		{
			"title": "IWC Ingenieur Automatic Steel",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-watches/iwc-ingenieur-automatic-steel/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-watches/iwc-ingenieur-automatic-steel/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-watches/iwc-ingenieur-automatic-steel/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-watches/iwc-ingenieur-automatic-steel/3.webp",
			],
		},
		{
			"title": "Rolex Cellini Moonphase",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-watches/rolex-cellini-moonphase/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-watches/rolex-cellini-moonphase/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-watches/rolex-cellini-moonphase/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-watches/rolex-cellini-moonphase/3.webp",
			],
		},
		{
			"title": "Rolex Datejust Women",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-watches/rolex-datejust-women/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-watches/rolex-datejust-women/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-watches/rolex-datejust-women/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-watches/rolex-datejust-women/3.webp",
			],
		},
		{
			"title": "Watch Gold for Women",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-watches/watch-gold-for-women/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-watches/watch-gold-for-women/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-watches/watch-gold-for-women/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-watches/watch-gold-for-women/3.webp",
			],
		},
		{
			"title": "Women's Wrist Watch",
			"thumb": "https://cdn.dummyjson.com/product-images/womens-watches/women%27s-wrist-watch/thumbnail.webp",
			"imgs": [
				"https://cdn.dummyjson.com/product-images/womens-watches/women%27s-wrist-watch/1.webp",
				"https://cdn.dummyjson.com/product-images/womens-watches/women%27s-wrist-watch/2.webp",
				"https://cdn.dummyjson.com/product-images/womens-watches/women%27s-wrist-watch/3.webp",
			],
		},
	],
}

# ─── DummyJSON category → Türkçe yaprak adı + kısa kod (slug için) ───
CATEGORY_TR = {
	"mens-shirts": ("Erkek Gömlek", "ERKGOM"),
	"tops": ("Üst Giyim", "USTGIY"),
	"womens-dresses": ("Kadın Elbise", "KADELB"),
	"mens-shoes": ("Erkek Ayakkabı", "ERKAYK"),
	"womens-shoes": ("Kadın Ayakkabı", "KADAYK"),
	"womens-bags": ("Kadın Çanta", "KADCNT"),
	"smartphones": ("Akıllı Telefon", "SMARTF"),
	"mobile-accessories": ("Telefon Aksesuarları", "TELAKS"),
	"laptops": ("Dizüstü Bilgisayar", "LAPTOP"),
	"tablets": ("Tablet", "TABLET"),
	"sports-accessories": ("Spor Ekipmanları", "SPORAK"),
	"motorcycle": ("Motosiklet", "MOTOSK"),
	"vehicle": ("Otomotiv", "OTOMTV"),
	"groceries": ("Market Ürünleri", "MARKET"),
	"beauty": ("Güzellik Ürünleri", "GUZELL"),
	"fragrances": ("Parfüm", "PARFUM"),
	"skin-care": ("Cilt Bakımı", "CILTBK"),
	"home-decoration": ("Ev Dekorasyonu", "EVDEKR"),
	"furniture": ("Mobilya", "MOBILY"),
	"kitchen-accessories": ("Mutfak Aksesuarları", "MUTFAK"),
	"womens-jewellery": ("Kadın Takı", "KADTAK"),
	"sunglasses": ("Güneş Gözlüğü", "GUNESG"),
	"mens-watches": ("Erkek Saat", "ERKSAT"),
	"womens-watches": ("Kadın Saat", "KADSAT"),
}


# ─── Seller → (sektör adı, sektör kodu, grup ağacı) ──────────────
# Her grup → [(dummyjson_category, label_override_opsiyonel)]
# label_override None ise CATEGORY_TR'den gelen ad kullanılır.
SELLER_SECTORS = {
	"DEMO-001": {
		"sector_name": "Tekstil ve Giyim",
		"sector_code": "TG",
		"groups": [
			("Erkek Giyim", ["mens-shirts"]),
			("Kadın Giyim", ["tops", "womens-dresses"]),
		],
	},
	"DEMO-002": {
		"sector_name": "Ayakkabı ve Deri",
		"sector_code": "AD",
		"groups": [
			("Erkek Ayakkabı", ["mens-shoes"]),
			("Kadın Ayakkabı", ["womens-shoes"]),
			("Çantalar", ["womens-bags"]),
		],
	},
	"DEMO-003": {
		"sector_name": "Elektronik ve Aksesuar",
		"sector_code": "EL",
		"groups": [
			("Telefon", ["smartphones", "mobile-accessories"]),
			("Bilgisayar", ["laptops", "tablets"]),
		],
	},
	"DEMO-004": {
		"sector_name": "Hırdavat ve Nalburiye",
		"sector_code": "HR",
		"groups": [
			("Spor Ekipmanları", ["sports-accessories"]),
			("Motor ve Otomotiv", ["motorcycle", "vehicle"]),
		],
	},
	"DEMO-005": {
		"sector_name": "Gıda ve İçecek",
		"sector_code": "GD",
		"groups": [
			("Market", ["groceries"]),
		],
	},
	"DEMO-006": {
		"sector_name": "Kozmetik ve Kişisel Bakım",
		"sector_code": "KZ",
		"groups": [
			("Makyaj ve Bakım", ["beauty", "skin-care"]),
			("Parfüm", ["fragrances"]),
		],
	},
	"DEMO-007": {
		"sector_name": "Ev Tekstili ve Dekorasyon",
		"sector_code": "EV",
		"groups": [
			("Dekorasyon", ["home-decoration"]),
			("Mobilya", ["furniture"]),
		],
	},
	"DEMO-008": {
		"sector_name": "Mutfak ve Züccaciye",
		"sector_code": "MU",
		"groups": [
			("Mutfak Aksesuarları", ["kitchen-accessories"]),
		],
	},
	"DEMO-009": {
		"sector_name": "Bijuteri ve Aksesuar",
		"sector_code": "BJ",
		"groups": [
			("Takı ve Aksesuar", ["womens-jewellery", "sunglasses"]),
			("Saat", ["mens-watches", "womens-watches"]),
		],
	},
	"DEMO-010": {
		"sector_name": "Ambalaj ve Kırtasiye",
		"sector_code": "AM",
		"groups": [
			# DummyJSON'da kırtasiye yok; çanta/ambalaj olarak ele alınıyor
			("Ambalaj ve Çanta", ["womens-bags"]),
		],
	},
}


# ═══════════════════════════════════════════════════════════════
#  OLUŞTURMA FONKSİYONLARI
# ═══════════════════════════════════════════════════════════════


def _ensure_user(email, first_name, last_name="", role="Seller", password=None):
	"""Demo kullanıcı oluştur veya mevcut olanı döndür.

	Her durumda verilen şifreyle senkron tutar ve verilen rolü ekler.
	Varsayılan rol/şifre satıcıya göredir — alıcılarda role="Buyer" kullanılır.

	first_name/last_name = giriş yapan GERÇEK KİŞİ (iletişim) adı — gerçek kayıt
	sistemindeki (api/v1/identity.py) gibi User bir kişidir; şirket/mağaza adı
	ayrıca Seller Profile.seller_name'de tutulur. İsim sonradan eklendiyse mevcut
	kullanıcıda da güncellenir (idempotent).
	"""
	if password is None:
		password = DEMO_SELLER_PASSWORD if role == "Seller" else DEMO_BUYER_PASSWORD
	if not frappe.db.exists("User", email):
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = first_name
		user.last_name = last_name
		user.enabled = 1
		user.user_type = "Website User"
		user.send_welcome_email = 0
		user.flags.ignore_permissions = True
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)
	else:
		cur_first, cur_last = frappe.db.get_value("User", email, ["first_name", "last_name"])
		if cur_first != first_name or (cur_last or "") != last_name:
			# Doğrudan DB update — User controller'ı role_profile gibi link'leri
			# yüklemeye çalışıp local'de eksikse patlıyor; sadece isim güncellemesi
			# için doc save'i atla. full_name türetilmiş alan, elle set edilir.
			full = (f"{first_name} {last_name}").strip()
			frappe.db.set_value(
				"User", email,
				{"first_name": first_name, "last_name": last_name, "full_name": full},
				update_modified=False,
			)

	update_password(email, password)

	user_doc = frappe.get_doc("User", email)
	existing_roles = {r.role for r in user_doc.roles}
	if role not in existing_roles:
		user_doc.append("roles", {"role": role})
		user_doc.flags.ignore_permissions = True
		user_doc.save(ignore_permissions=True)

	return email


# ─── Başlık zenginleştirme (variant_type → B2B suffix) ────────
# DummyJSON başlıkları genelde çok kısa (20-25 karakter). Kart yerleşiminde
# line-clamp-2 kuralıyla 2 satır truncate görünsün diye 50-65 karakterlik
# kategori-bazlı bir B2B suffix ekleriz. Orijinal başlık slug/route üretiminde
# kullanılır, suffix yalnızca görünür title'a yapışır.
TITLE_SUFFIXES = {
	"giyim": " — Toptan Tekstil, Pamuklu Premium Kumaş, Özel Üretim İmkanı",
	"ayakkabi": " — Toptan Ayakkabı ve Çanta, Yüksek Kaliteli Deri, Özel Üretim",
	"elektronik": " — Toptan Elektronik, Orijinal Ürün Garantili, Hızlı Kargo Seçenekleri",
	"hirdavat": " — Toptan Hırdavat ve Yapı Malzemesi, Dayanıklı Kalite, Uygun Fiyat",
	"gida": " — Toptan Gıda Tedariki, Uzun Raf Ömrü, Hızlı Teslimat Seçenekleri",
	"kozmetik": " — Toptan Kozmetik Ürünleri, Premium Formül, Dermatolojik Test Edilmiş",
	"tekstil": " — Toptan Ev Tekstili, Yumuşak Doku, Kaliteli Pamuk ve Polyester Karışım",
	"zuccaciye": " — Toptan Mutfak Eşyaları, Dayanıklı Malzeme, Premium Tasarım ve Kalite",
	"aksesuar": " — Toptan Aksesuar Koleksiyonu, Moda Tasarım, El Yapımı Detay ve Kalite",
	"ambalaj": " — Toptan Ambalaj ve Kırtasiye, Özel Baskı İmkanı, Çevre Dostu Üretim",
}


# ─── Sertifika kataloğu (isim → kategori) ────────────────────
# Seed içindeki tüm cert adları burada sınıflandırılır. Bilinmeyenler "Product" kabul edilir.
CERT_CATALOG = {
	# Management (kurumsal yönetim sistemi)
	"ISO 9001": "Management",
	"TSE": "Management",
	"ISO 22716 (GMP)": "Management",
	# Product (ürün-spesifik)
	"OEKO-TEX Standard 100": "Product",
	"GOTS": "Product",
	"CE": "Product",
	"RoHS": "Product",
	"FCC": "Product",
	"ISO 22000": "Product",
	"HACCP": "Product",
	"Organik Sertifika": "Product",
	"Helal": "Product",
	"Cruelty-Free": "Product",
	"FDA Uyumlu": "Product",
	"Deri Sertifikası": "Product",
	"Ayar Damgası": "Product",
	"Nikel Testi": "Product",
	"FSC (Orman Sertifikası)": "Product",
}


def _ensure_cert_type(cert_name):
	"""Certification Type master'ı idempotent oluşturur. cert_name döndürür."""
	name = (cert_name or "").strip()
	if not name:
		return None
	if frappe.db.exists("Certification Type", name):
		return name
	doc = frappe.new_doc("Certification Type")
	doc.certification_name = name
	doc.category = CERT_CATALOG.get(name, "Product")
	doc.status = "Approved"
	doc.description = f"Demo sertifika: {name}"
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return name


_REVIEWERS = [
	("Mehmet Yılmaz", "Türkiye", "🇹🇷"), ("Ayşe Demir", "Türkiye", "🇹🇷"),
	("Hans Müller", "Almanya", "🇩🇪"), ("Sofia Rossi", "İtalya", "🇮🇹"),
	("Ahmed Al-Farsi", "BAE", "🇦🇪"), ("Emma Johnson", "İngiltere", "🇬🇧"),
	("Mustafa Kaya", "Türkiye", "🇹🇷"), ("Pierre Dubois", "Fransa", "🇫🇷"),
	("Olga Petrova", "Rusya", "🇷🇺"), ("Carlos García", "İspanya", "🇪🇸"),
	("Fatma Şahin", "Türkiye", "🇹🇷"), ("John Smith", "ABD", "🇺🇸"),
	("Wei Chen", "Çin", "🇨🇳"), ("Zeynep Arslan", "Türkiye", "🇹🇷"),
	("Liam Brown", "Kanada", "🇨🇦"), ("Nour Hassan", "Mısır", "🇪🇬"),
]

_REVIEW_COMMENTS = [
	"Ürün kalitesi beklentimizin üzerindeydi, toptan siparişimiz zamanında ulaştı.",
	"İletişim çok hızlı ve profesyoneldi. Tekrar çalışacağız.",
	"Numune talebimize hemen yanıt verdiler, kalite tutarlı.",
	"Paketleme özenliydi, ürünler sorunsuz teslim edildi.",
	"Fiyat/performans açısından çok memnun kaldık.",
	"Sevkiyat takibi şeffaftı, teslimat söz verilen tarihte yapıldı.",
	"Büyük hacimli siparişte bile kalite düşmedi, tavsiye ederim.",
	"Özel üretim talebimizi eksiksiz karşıladılar.",
	"Satış sonrası destek gerçekten iyi, sorunları hızlı çözdüler.",
	"Uzun süredir çalıştığımız güvenilir bir tedarikçi.",
]


def _seed_seller_reviews(seller_code):
	"""Satıcıya gerçekçi Seller Review kayıtları basar ve rating/review_count'u
	bunlardan yeniden hesaplar — vitrindeki değerlendirme kartı dolu gelir."""
	if frappe.db.exists("Seller Review", {"seller": seller_code}):
		return
	random.seed(hash(f"reviews-{seller_code}"))
	count = random.randint(14, 32)
	total = 0.0
	for i in range(count):
		name, country, flag = _REVIEWERS[(hash(f"{seller_code}-{i}")) % len(_REVIEWERS)]
		rating = random.choice([5, 5, 5, 4, 4, 5, 4, 5])
		total += rating
		rev = frappe.new_doc("Seller Review")
		rev.seller = seller_code
		rev.reviewer_name = name
		rev.country = country
		rev.country_flag = flag
		rev.rating = rating
		rev.comment = _REVIEW_COMMENTS[i % len(_REVIEW_COMMENTS)]
		rev.is_featured = 1 if i < 3 else 0
		rev.status = "Published"
		rev.date = f"2025-{(i % 12) + 1:02d}-{(i % 27) + 1:02d} 10:00:00"
		rev.flags.ignore_permissions = True
		rev.insert(ignore_permissions=True)
	# rating/review_count'u seed'lenen yorumlardan tutarlı yaz (doc.rating fallback'ini ezer).
	frappe.db.set_value(
		"Admin Seller Profile",
		seller_code,
		{"rating": round(total / count, 1), "review_count": count},
		update_modified=False,
	)


def _ensure_seller(s):
	"""Admin Seller Profile oluştur veya mevcut olanı döndür."""
	# User = gerçek kişi (iletişim/yetkili); şirket adı seller_name'de ayrı durur.
	contact_first, contact_last = SELLER_CONTACTS.get(s["code"], (s["seller_name"], ""))
	_ensure_user(s["email"], contact_first, contact_last)

	if frappe.db.exists("Admin Seller Profile", s["code"]):
		return s["code"]

	doc = frappe.new_doc("Admin Seller Profile")
	doc.seller_code = s["code"]
	doc.seller_name = s["seller_name"]
	doc.user = s["email"]
	doc.status = "Active"
	doc.seller_type = "Corporate"
	# Sektöre özel markalı SVG logo/kapak (yerel üretim, alakalı). Yazılamazsa eski kaynağa düş.
	doc.logo = _demo_logo(s["code"], s["seller_name"], s["variant_type"]) or _seller_icon_logo(
		s["code"], 200
	)
	doc.banner_image = _demo_cover(s["code"], s["seller_name"], s["variant_type"]) or _img(
		s["variant_type"], 1200, 400, lock_id=f"{s['code']}-banner"
	)
	doc.description = s["description"]
	doc.slogan = s["slogan"]
	doc.company_name = s["company_name"]
	doc.tax_id = s["tax_id"]
	doc.tax_office = s["tax_office"]
	doc.founded_year = s["founded_year"]
	doc.staff_count = s["staff_count"]
	doc.annual_revenue = s["annual_revenue"]
	doc.factory_size = s["factory_size"]
	doc.business_type = s["business_type"]
	doc.main_markets = s["main_markets"]
	# certifications → child table (Seller Certification)
	# Master Certification Type kaydını önce oluştur, sonra child row ekle — aksi halde
	# listing.py:get_filter_facets cert facet'ini Certification Type tablosundan çözemez.
	for cert in s["certifications"].split(", "):
		cert_name = _ensure_cert_type(cert)
		if cert_name:
			# verification_status default "Pending" — listing.validate Verified bekler;
			# demo satıcı cert'leri admin tarafından onaylanmış kabul edilir.
			# document → özgün rozet SVG'si (vitrinde thumbnail, telif-güvenli).
			cert_no = f"TH-{_asset_slug(cert_name).upper().replace('-', '')[:10]}-{random.randint(1000, 9999)}"
			doc.append(
				"certifications",
				{
					"certification_type": cert_name,
					"verification_status": "Verified",
					"document": _demo_cert_image(cert_name) or "",
					"certificate_number": cert_no,
					"issued_date": "2024-03-12",
					"expiry_date": "2027-03-11",
				},
			)
	doc.email = s["email"]
	doc.phone = s["phone"]
	doc.website = s["website"]
	doc.address_line1 = s["address_line1"]
	doc.city = s["city"]
	doc.district = s["district"]
	doc.postal_code = s["postal_code"]
	doc.country = "Turkey"
	doc.bank_name = s["bank_name"]
	doc.iban = s["iban"]
	doc.account_holder = s["account_holder"]
	# is_verified ve verification_type field'ları kaldırıldı (KYB Verified rolüne geçildi)
	doc.health_score = round(random.uniform(75, 98), 1)
	doc.score_grade = random.choice(["A", "A", "A", "B"])
	# Mağaza puanı: StoreHeader + "Şirket Değerlendirmeleri" barları (Tedarikçi Hizmeti /
	# Ürün Kalitesi) doğrudan bu alandan türüyor. Seed'lenmezse vitrinde "—" görünür.
	doc.rating = round(random.uniform(4.2, 4.9), 1)
	doc.review_count = random.randint(48, 320)
	doc.commission_rate = s["commission_rate"]
	doc.subscription_plan = s["subscription_plan"]
	doc.response_time = random.choice(["< 1 saat", "< 2 saat", "< 4 saat", "< 24 saat"])
	doc.response_rate = round(random.uniform(85, 99), 1)
	doc.on_time_delivery = round(random.uniform(90, 99), 1)

	# Gallery — SEKTÖRE UYGUN gerçek fabrika/üretim görselleri (+ varsa video).
	# Ürün görseli DEĞİL: üretici kartının sağ galerisi fabrikayı göstermeli.
	gallery_categories = ["overview", "production", "quality_control", "360_view"]
	factory_imgs = SELLER_FACTORY_IMAGES.get(s["code"], [])
	sort_i = 0
	for i, photo_id in enumerate(factory_imgs):
		sort_i += 1
		doc.append(
			"gallery_images",
			{
				"category": gallery_categories[i % len(gallery_categories)],
				"media_type": "image",
				"image": _pexels(photo_id, 800),
				"caption": f"{s['seller_name']} — Üretim Tesisi {i + 1}",
				"sort_order": sort_i,
			},
		)
	# Fabrika tanıtım videosu (sektöre uygun olan satıcılarda)
	video = SELLER_FACTORY_VIDEOS.get(s["code"])
	if video:
		sort_i += 1
		video_url, poster_id = video
		doc.append(
			"gallery_images",
			{
				"category": "production",
				"media_type": "video",
				"video_url": video_url,
				"poster_image": _pexels(poster_id, 800),
				"caption": f"{s['seller_name']} — Üretim Videosu",
				"sort_order": sort_i,
			},
		)

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	# Gerçek Seller Review kayıtları — "Şirket Değerlendirmeleri (0)" yerine dolu liste +
	# rating/review_count'u tutarlı şekilde yeniden hesaplar.
	_seed_seller_reviews(s["code"])
	return s["code"]


def _ensure_seller_application(s):
	"""Demo satıcı için Approved durumda Seller Application oluşturur.

	Seller Application.on_update tetikleyerek otomatik olarak şunları üretir:
	- Seller Profile (status=Active, member_id ile) → admin panelde "Satıcı Profilleri"
	  listesinde görünür.
	- KYB Verification (status=Pending) → "KYB Doğrulama" listesinde görünür.
	- User'a 'Seller' rolü (idempotent — _ensure_user'da zaten eklenmiştir).
	- Admin Seller Profile (zaten _ensure_seller'da DEMO-* kodlu oluşturulduğu için
	  on_update içindeki `if not frappe.db.exists(...)` kontrolü atlar).

	Idempotent: applicant_user üzerinden mevcut başvuruyu bulur, varsa Approved'a
	çeker; yoksa direkt Approved olarak insert eder.

	identity_document, kimlik tarafı ve KYB belge field'ları reqd:1 olduğundan
	demo akışta `ignore_mandatory=True` ile bypass edilir — production akışında
	bunlar storefront kayıt ekranlarında doldurulur.
	"""
	user = s["email"]

	user_creation = frappe.db.get_value("User", user, "creation")
	member_id = _generate_member_id(user, user_creation)

	existing = frappe.db.get_value("Seller Application", {"applicant_user": user}, "name")
	if existing:
		current_status = frappe.db.get_value("Seller Application", existing, "status")
		if current_status != "Approved":
			doc = frappe.get_doc("Seller Application", existing)
			doc.status = "Approved"
			doc.flags.ignore_permissions = True
			doc.flags.ignore_mandatory = True
			doc.save(ignore_permissions=True)
		return existing

	doc = frappe.new_doc("Seller Application")
	doc.applicant_user = user
	doc.member_id = member_id
	doc.business_name = s["company_name"]
	# Demo satıcılar A.Ş./Ltd. yapılarda → KYB business_type'ı "Anonim Şirket" olur
	doc.seller_type = "Enterprise"
	doc.contact_email = s["email"]
	doc.contact_phone = s["phone"]
	doc.tax_id_type = "VKN"
	doc.tax_id = s["tax_id"]
	doc.tax_office = s["tax_office"]
	doc.address_line_1 = s["address_line1"]
	doc.city = s["city"]
	doc.country = "Turkey"
	doc.bank_name = s["bank_name"]
	doc.iban = s["iban"]
	doc.account_holder_name = s["account_holder"]
	doc.identity_document = DEMO_KYB_DOC_URL
	doc.terms_accepted = 1
	doc.privacy_accepted = 1
	doc.status = "Approved"
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _fill_demo_kyb_documents(s):
	"""Demo satıcının KYB Verification belge field'larını placeholder PDF ile doldur.

	Production akışında satıcı 6 belgeyi storefront /seller/kyb akışında yükler;
	demo'da hepsi DEMO_KYB_DOC_URL'i gösterir ki admin panelde belge slot'ları
	boş görünmesin.

	Document Expiry Date 5 yıl ileriye set edilir — _validate_expiry_date geçmiş
	tarihi reddeder; 5 yıl gerçekçi belge yenileme periyodu.

	Idempotent: değer zaten doluysa overwrite eder (placeholder ile aynı kalır).
	"""
	from frappe.utils import add_years, today

	kyb_name = frappe.db.get_value("KYB Verification", {"user": s["email"]}, "name")
	if not kyb_name:
		return

	kyb = frappe.get_doc("KYB Verification", kyb_name)
	for field in DEMO_KYB_DOC_FIELDS:
		kyb.set(field, DEMO_KYB_DOC_URL)
	kyb.document_expiry_date = add_years(today(), 5)
	kyb.flags.ignore_permissions = True
	kyb.flags.ignore_mandatory = True
	kyb.save(ignore_permissions=True)


def _grant_verified_seller_role(email):
	"""Satıcı User'ına 'Verified Seller' rolünü ekle (idempotent).

	Storefront/listing 'Onaylanmış Satıcı' rozeti bu role bakar (listing.py:
	Has Role WHERE role='Verified Seller'). KYB on_update hook'u status geçişi
	olmadığında rolü eklemeyebildiği için seed açıkça garanti eder.
	"""
	if not email or not frappe.db.exists("Role", "Verified Seller"):
		return
	if frappe.db.exists("Has Role", {"parent": email, "parenttype": "User", "role": "Verified Seller"}):
		return
	# DİKKAT: user_doc.add_roles() BURADA İŞE YARAMAZ — demo User'ların
	# role_profile_name="Seller Full Access" alanı var ve User.save rolleri profile'a
	# göre resetleyip "Verified Seller"i siliyor. Has Role child satırını DOĞRUDAN
	# ekleyerek save profile-sync'ini bypass ederiz (rol kalıcı olur).
	try:
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parenttype": "User",
				"parentfield": "roles",
				"parent": email,
				"role": "Verified Seller",
			}
		).insert(ignore_permissions=True)
		frappe.clear_cache(user=email)
	except Exception:
		pass


def _set_demo_kyb_status(s, index):
	"""Demo satıcı için KYB Verification statüsünü DEMO_KYB_STATUSES'a göre ayarla.

	_ensure_seller_application çağrısından sonra çalışır; KYB kaydı default
	"Pending" olarak oluşmuş olur, burada index'e göre Verified/Under Review/
	Rejected'a çeker. KYB.on_update zinciri:
	- _sync_kyb_status → Seller Profile.kyb_status senkron
	- _sync_verified_seller_role → status=Verified ise "Verified Seller" rolü
	- _set_review_metadata → verified_by/verified_at damgası

	Rejected status için min 20 karakter rejection_reason gereklidir
	(validate_rejection_reason); DEMO_KYB_REJECTION_REASON yeterli uzunlukta.
	"""
	target_status = DEMO_KYB_STATUSES.get(index, "Pending")
	if target_status == "Pending":
		# Default zaten Pending; gereksiz save tetikleme yok
		return

	kyb_name = frappe.db.get_value("KYB Verification", {"user": s["email"]}, "name")
	if not kyb_name:
		return

	kyb = frappe.get_doc("KYB Verification", kyb_name)
	kyb.status = target_status
	if target_status in ("Rejected", "Suspended"):
		kyb.rejection_reason = DEMO_KYB_REJECTION_REASON
		kyb.rejection_category = "Re-submit"
	kyb.flags.ignore_permissions = True
	kyb.flags.ignore_mandatory = True
	kyb.save(ignore_permissions=True)
	# KYB Verified ise satıcı tam doğrulanmış sayılır → "Verified Seller" rolünü garanti et.
	if target_status == "Verified":
		_grant_verified_seller_role(s["email"])


def _set_demo_kyc_verified(email, *, account_type, company_name, tax_id, phone, address):
	"""Demo kullanıcı için KYC Verification'ı Verified durumda oluştur/günceller.

	Storefront satın alma kapısı (api/cart.py:create_order) User Profile.kyc_status'a
	bakar; KYC.on_update zinciri Verified olunca User Profile.kyc_status=Verified +
	can_buy=1 + kyc_verified_at damgasını set eder → demo hesaplar direkt satın alabilir.

	User Profile'ın önceden var olması gerekir (satıcıda Seller Application else-branch'i,
	alıcıda _ensure_buyer_user_profile yaratır); yoksa _sync_kyc_status no-op olur.

	validate() identity_document/tax_id/phone/address/billing_address (Business iken
	company_name) ister; demo değerleriyle doldurup ignore_mandatory ile insert ederiz.
	Idempotent: applicant user üzerinden mevcut kaydı bulup Verified'a çeker.
	"""
	existing = frappe.db.get_value("KYC Verification", {"user": email}, "name")
	kyc = frappe.get_doc("KYC Verification", existing) if existing else frappe.new_doc("KYC Verification")
	kyc.user = email
	kyc.account_type = account_type
	kyc.company_name = company_name
	kyc.tax_id = tax_id
	kyc.phone = phone
	kyc.email_field = email
	kyc.address = address
	kyc.billing_address = address
	kyc.identity_document = DEMO_KYB_DOC_URL
	kyc.status = "Verified"
	kyc.owner = email
	kyc.flags.ignore_permissions = True
	kyc.flags.ignore_mandatory = True
	kyc.save(ignore_permissions=True)


def _ensure_buyer_user_profile(b):
	"""Demo alıcı için minimum User Profile oluştur (yoksa).

	Register akışı (api/v1/identity.py) User Profile'ı OTP doğrulamasıyla yaratır;
	demo'da o akışı atladığımız için (seed yalnız eski Buyer Profile doctype'ını
	dolduruyordu) satın alma yetkisinin dayandığı User Profile burada kurulur.
	can_buy/kyc_status başlangıçta kapalı; _set_demo_kyc_verified Verified'a çeker.
	"""
	if frappe.db.exists("User Profile", {"user": b["email"]}):
		return

	creation = frappe.db.get_value("User", b["email"], "creation")
	up = frappe.new_doc("User Profile")
	up.user = b["email"]
	up.full_name = b["buyer_name"]
	up.member_id = _generate_member_id(b["email"], creation)
	up.account_type = "Business"
	up.company_name = b["company_name"]
	up.country = "Turkey"
	up.phone = b["phone"]
	up.status = "Active"
	up.can_buy = 0
	up.can_sell = 0
	up.kyc_status = "Pending"
	up.kyb_status = "Locked"
	up.email_verified = 1
	up.created_via = "migration"
	up.owner = b["email"]
	up.flags.ignore_permissions = True
	up.flags.ignore_validate = True
	up.insert(ignore_permissions=True)


def _ensure_buyer(b):
	"""Buyer Profile oluştur veya mevcut olanı döndür.

	User'ı 'Buyer' rolüyle oluşturur, Buyer Profile doc'unu user email ile autoname yapar.
	"""
	_ensure_user(b["email"], b["buyer_name"], role="Buyer", password=DEMO_BUYER_PASSWORD)

	if frappe.db.exists("Buyer Profile", b["email"]):
		return b["email"]

	doc = frappe.new_doc("Buyer Profile")
	doc.user = b["email"]
	doc.buyer_name = b["buyer_name"]
	doc.status = "Active"
	doc.company_name = b["company_name"]
	doc.business_type = b["business_type"]
	doc.job_title = b["job_title"]
	doc.city = b["city"]
	doc.country = "Turkey"
	doc.phone = b["phone"]
	doc.employee_count = b["employee_count"]
	doc.year_established = b["year_established"]
	doc.sourcing_frequency = b["sourcing_frequency"]
	doc.annual_spending = b["annual_spending"]
	doc.industry_preferences = b["industry_preferences"]
	doc.about_us = b["about_us"]
	doc.email_verified = 1
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)

	# Avatar User.user_image'de tek doğruluk kaynağıdır.
	frappe.db.set_value("User", b["email"], "user_image", _seller_logo(b["buyer_name"], 200))
	return b["email"]


def _ensure_category(name, parent_id, external_id, sort_order=0, sector_key="giyim"):
	"""Product Category oluştur (tree). Varsa mevcut olanı döndür."""
	if frappe.db.exists("Product Category", external_id):
		return external_id

	doc = frappe.new_doc("Product Category")
	doc.external_id = external_id
	doc.category_name = name
	doc.parent_product_category = parent_id or ""
	doc.is_active = 1
	doc.sort_order = sort_order
	doc.url_slug = _slug(f"{external_id}")
	doc.image = _img(sector_key, 400, 400, lock_id=f"cat-{external_id}")
	doc.meta_title = name
	doc.meta_description = f"{name} — İstoç Ticaret Merkezi'nde toptan ve perakende ürünler"
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	return external_id


def _ensure_seller_category(seller_code, category_id, category_name, sector_key="giyim"):
	"""Seller Category oluştur. Varsa mevcut olanı güncelle (category_name/image)."""
	image_url = _img(sector_key, 400, 400, lock_id=f"sc-{seller_code}-{_slug(category_name)}")
	existing = frappe.db.get_value(
		"Seller Category",
		{"seller": seller_code, "category": category_id},
		"name",
	)
	if existing:
		# Eski seed'den kalma boş alanları doldur — idempotent.
		updates = {
			"category_name": category_name,
			"status": "Active",
			"is_enabled": 1,
		}
		current_image = frappe.db.get_value("Seller Category", existing, "image")
		if not current_image:
			updates["image"] = image_url
		for field, value in updates.items():
			frappe.db.set_value("Seller Category", existing, field, value, update_modified=False)
		return existing

	doc = frappe.new_doc("Seller Category")
	doc.seller = seller_code
	doc.category = category_id
	doc.category_name = category_name
	doc.status = "Active"
	doc.is_enabled = 1
	doc.image = image_url
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _create_listing(
	seller,
	seller_cat_name,
	product_cat_id,
	cat_name,
	product,
	product_idx,
	variant_type,
	price_range,
	dj_cat=None,
):
	"""Tek bir Listing (ürün ilanı) — DummyJSON ürünü üzerinden başlık/görsel birebir uyumlu.

	`product` dict: {"title": "...", "thumb": "https://...", "imgs": ["..."]}
	"""
	# B2B bağlamı için başlığı zenginleştir: 2-satır truncate (line-clamp-2)
	# doldurulsun diye kategori-bazlı bir suffix ekleriz. Slug için orijinal başlık kullanılır.
	base_title = product["title"]
	title = base_title + TITLE_SUFFIXES.get(
		variant_type, " — Toptan Satış, Premium Kalite, Hızlı Kargo Seçenekleri"
	)
	# Tüm ürünler gerçek DummyJSON ürün fotoğraflarını kullanır (görsel ve isim eşleşir).
	primary_image = product["thumb"]
	gallery = product.get("imgs") or []

	# Fiyat hesapla (title hash ile deterministik)
	random.seed(hash(title))
	base = round(random.uniform(*price_range), 2)
	selling = round(base * random.uniform(0.85, 0.95), 2)
	sample = round(base * 0.15, 2)
	weight = round(random.uniform(0.1, 5.0), 2)

	# Slug orijinal başlıktan türetilir — suffix eklemeden, URL kısa kalsın
	slug = _slug(base_title)
	currency = "TRY" if frappe.db.exists("Currency", "TRY") else "USD"

	# Varyant satırları (Listing Variant Item child table — 2-eksen destekli)
	# Varyant görselleri: gerçek ürün galerisini tekrarla, yetmezse primary'ye düş
	variant_image_pool = gallery + [primary_image]
	variant_items = []
	variant_configs = VARIANT_CONFIGS.get(variant_type, VARIANT_CONFIGS["giyim"])
	if len(variant_configs) >= 2:
		# 2 eksen → çapraz kombinasyon (tek satırda iki eksen)
		vc1, vc2 = variant_configs[0], variant_configs[1]
		first = True
		for i, v1 in enumerate(vc1["values"]):
			mod1 = vc1["price_mod"][i] if i < len(vc1["price_mod"]) else 0
			for j, v2 in enumerate(vc2["values"]):
				mod2 = vc2["price_mod"][j] if j < len(vc2["price_mod"]) else 0
				total_mod = mod1 + mod2
				variant_items.append(
					{
						"attribute_type": vc1["attr"],
						"attribute_value": v1,
						"attribute_type_2": vc2["attr"],
						"attribute_value_2": v2,
						"is_default": 1 if first else 0,
						"variant_price": round(selling + total_mod, 2) if total_mod != 0 else 0,
						"variant_stock": random.randint(20, 300),
						"variant_sku": (
							f"{seller[-3:]}-{_slug(cat_name)[:4].upper()}-{product_idx:02d}-"
							f"{_slug(v1)[:3].upper()}-{_slug(v2)[:3].upper()}"
						),
						"variant_image": variant_image_pool[(i + j) % len(variant_image_pool)],
					}
				)
				first = False
	else:
		# Tek eksen — her değer için bir satır
		vc = variant_configs[0]
		for j, val in enumerate(vc["values"]):
			mod = vc["price_mod"][j] if j < len(vc["price_mod"]) else 0
			variant_items.append(
				{
					"attribute_type": vc["attr"],
					"attribute_value": val,
					"is_default": 1 if j == 0 else 0,
					"variant_price": round(selling + mod, 2) if mod != 0 else 0,
					"variant_stock": random.randint(50, 500),
					"variant_sku": (
						f"{seller[-3:]}-{_slug(cat_name)[:4].upper()}-{product_idx:02d}-"
						f"{_slug(val)[:3].upper()}"
					),
					"variant_image": variant_image_pool[j % len(variant_image_pool)],
				}
			)

	# ── HEAVY VARIANT TEST ÜRÜNLERİ ──
	# Çok varyantlı UI stres testleri için:
	#   1) Nike Air Jordan 1 (ayakkabı) → 2 eksen, 120 varyant
	#   2) Man Plaid Shirt (giyim)      → 2 eksen, 72 varyant
	#   3) iPhone 13 Pro (telefon)      → 2 eksen, 20 varyant
	#   4) MacBook Pro 14 (laptop)      → 7 eksen, 128 varyant (N-eksen testi)
	def _set_variants_matrix_n(axes, sku_prefix):
		"""N-eksen matrisi. axes = [{"name","values","mods"}...].
		İlk 2 eksen structured field'lara, 3+ eksen axis_values_json'a gider."""
		new_items = []
		first = True

		def iter_combos(idx, acc):
			if idx == len(axes):
				yield list(acc)
				return
			for vi, val in enumerate(axes[idx]["values"]):
				acc.append((vi, val))
				yield from iter_combos(idx + 1, acc)
				acc.pop()

		for combo in iter_combos(0, []):
			indices = [c[0] for c in combo]
			values = [c[1] for c in combo]
			total_mod = 0
			for k in range(len(axes)):
				mods = axes[k].get("mods", [])
				if indices[k] < len(mods):
					total_mod += mods[indices[k]]
			row = {
				"attribute_type": axes[0]["name"],
				"attribute_value": values[0],
				"is_default": 1 if first else 0,
				"variant_price": round(selling + total_mod, 2) if total_mod != 0 else 0,
				"variant_stock": random.randint(5, 80),
				"variant_sku": sku_prefix + "-" + "-".join(_slug(v)[:3].upper() for v in values),
				"variant_image": variant_image_pool[sum(indices) % len(variant_image_pool)],
			}
			if len(axes) >= 2:
				row["attribute_type_2"] = axes[1]["name"]
				row["attribute_value_2"] = values[1]
			if len(axes) >= 3:
				extra = {axes[k]["name"]: values[k] for k in range(2, len(axes))}
				row["axis_values_json"] = json.dumps(extra, ensure_ascii=False)
			new_items.append(row)
			first = False
		return new_items

	if seller == "DEMO-002" and title == "Nike Air Jordan 1 Red And Black":
		variant_items = _set_variants_matrix_n(
			[
				{
					"name": "Renk",
					"values": [
						"Siyah",
						"Beyaz",
						"Kırmızı",
						"Lacivert",
						"Gri",
						"Kahverengi",
						"Mavi",
						"Yeşil",
						"Sarı",
						"Turuncu",
						"Mor",
						"Pembe",
					],
					"mods": [0, 5, 10, 15, 0, 5, 10, 15, 0, 5, 10, 15],
				},
				{
					"name": "Beden",
					"values": ["36", "37", "38", "39", "40", "41", "42", "43", "44", "45"],
					"mods": [-6, -3, 0, 0, 0, 0, 0, 3, 6, 9],
				},
			],
			"NKE-AJ1",
		)
	elif seller == "DEMO-001" and title == "Man Plaid Shirt":
		variant_items = _set_variants_matrix_n(
			[
				{
					"name": "Renk",
					"values": [
						"Mavi",
						"Kırmızı",
						"Yeşil",
						"Siyah",
						"Beyaz",
						"Gri",
						"Lacivert",
						"Kahverengi",
						"Sarı",
						"Turuncu",
						"Mor",
						"Pembe",
					],
					"mods": [0, 0, 0, -5, -5, 0, 5, 5, 10, 10, 15, 15],
				},
				{
					"name": "Beden",
					"values": ["S", "M", "L", "XL", "XXL", "3XL"],
					"mods": [0, 0, 0, 5, 10, 15],
				},
			],
			"SHR-PLD",
		)
	elif seller == "DEMO-003" and title == "iPhone 13 Pro":
		variant_items = _set_variants_matrix_n(
			[
				{
					"name": "Renk",
					"values": ["Grafit", "Gümüş", "Altın", "Sierra Mavi", "Alpin Yeşili"],
					"mods": [0, 0, 0, 0, 0],
				},
				{
					"name": "Kapasite",
					"values": ["128GB", "256GB", "512GB", "1TB"],
					"mods": [0, 200, 500, 900],
				},
			],
			"IP13P",
		)
	elif seller == "DEMO-003" and title == "Apple MacBook Pro 14 Inch Space Grey":
		# 7 EKSEN — N-eksen UI stres testi (128 varyant)
		variant_items = _set_variants_matrix_n(
			[
				{"name": "Renk", "values": ["Space Gray", "Gümüş"], "mods": [0, 0]},
				{"name": "İşlemci", "values": ["M3 Pro", "M3 Max"], "mods": [0, 1500]},
				{"name": "RAM", "values": ["16GB", "32GB"], "mods": [0, 800]},
				{"name": "Depolama", "values": ["512GB", "1TB"], "mods": [0, 600]},
				{"name": "Ekran", "values": ["14 inç", "16 inç"], "mods": [0, 2000]},
				{"name": "Klavye", "values": ["Türkçe Q", "İngilizce"], "mods": [0, 0]},
				{"name": "Garanti", "values": ["1 Yıl Standart", "3 Yıl AppleCare"], "mods": [0, 1200]},
			],
			"MBP-14",
		)

	# B2B toptan fiyat kademeleri
	pricing_tiers = [
		{"min_qty": 10, "max_qty": 49, "price": round(selling * 0.95, 2), "discount_percentage": 5},
		{"min_qty": 50, "max_qty": 99, "price": round(selling * 0.90, 2), "discount_percentage": 10},
		{"min_qty": 100, "max_qty": 0, "price": round(selling * 0.85, 2), "discount_percentage": 15},
	]

	# Ürün spesifikasyonları — sektör bazlı anlamlı değerler
	attribute_values = _build_attribute_values(seller, variant_type, weight)

	# Ek görseller — ürünün kendi galerisi
	listing_images = [
		{
			"image": img,
			"alt_text": f"{title} - Görsel {k + 1}",
			"sort_order": k,
		}
		for k, img in enumerate(gallery)
	]

	# Lead time
	lead_time_ranges = [
		{"min_qty": 1, "max_qty": 50, "lead_days": random.randint(1, 3)},
		{"min_qty": 51, "max_qty": 200, "lead_days": random.randint(3, 7)},
		{"min_qty": 201, "max_qty": 0, "lead_days": random.randint(7, 15)},
	]

	# Kargo yöntemleri — her listing için 2-3 yöntem (ağırlığa göre maliyet hesapla)
	selected_methods = random.sample(SHIPPING_METHODS, k=random.randint(2, 3))
	shipping_methods = []
	for sm in selected_methods:
		method_cost = round(sm["base_cost"] + sm["cost_per_kg"] * weight, 2)
		shipping_methods.append(
			{
				"shipping_method": sm["method_name"],
				"cost": method_cost,
				"min_days": sm["min_days"],
				"max_days": sm["max_days"],
			}
		)

	doc = frappe.new_doc("Listing")
	doc.title = title
	doc.seller_profile = seller
	doc.status = "Active"
	doc.listing_type = "Fixed Price"
	doc.category = seller_cat_name
	doc.category_name = cat_name
	doc.product_category = product_cat_id
	doc.product_category_name = cat_name
	doc.brand = _ensure_brand(seller, variant_type)
	doc.condition = "New"
	doc.short_description = _short(title, cat_name)
	doc.description = _desc(title, cat_name)
	doc.currency = currency
	doc.base_price = base
	doc.selling_price = selling
	# discount_percentage bir kampanya bayrağıdır (listing.py: dp > 0 → kampanya aktif).
	# Demoda ürünlerin ~%20'sinde kampanya etkin olsun.
	doc.discount_percentage = random.choice([0, 0, 0, 0, 5, 10, 15, 20])
	doc.sample_price = sample
	doc.b2b_enabled = 1
	doc.stock_qty = random.randint(500, 5000)
	doc.stock_uom = "Adet"
	doc.min_order_qty = random.choice([1, 5, 10, 20])
	doc.max_order_qty = 0
	doc.low_stock_threshold = 10
	doc.track_inventory = 1
	doc.allow_backorders = 0
	doc.primary_image = primary_image
	doc.has_variants = 1
	doc.is_free_shipping = random.choice([0, 0, 0, 1])
	doc.shipping_weight = weight
	doc.ships_from_country = "Turkey"
	doc.ships_from_city = "İstanbul"
	doc.handling_days = random.choice([1, 1, 2, 3])
	doc.country_of_origin = "Turkey"
	doc.package_type = random.choice(["Karton Kutu", "Poşet", "Karton Kutu"])
	# En Çok Satanlar widget'ı order_count > 0 listingleri kategoriye göre grupluyor.
	# Her ürüne rastgele 5-200 arası satış atıyoruz ki widget dolu gelsin.
	doc.order_count = random.randint(5, 200)
	doc.view_count = random.randint(50, 2000)
	doc.average_rating = round(random.uniform(3.5, 5.0), 1)
	doc.review_count = random.randint(0, 80)
	doc.is_featured = 1 if product_idx == 1 and random.random() < 0.3 else 0
	# is_best_seller: order_count yüksek olanları (100+) işaretle
	doc.is_best_seller = 1 if doc.order_count > 100 else 0
	doc.is_new_arrival = 1 if random.random() < 0.2 else 0
	doc.is_visible = 1
	doc.is_searchable = 1
	doc.selling_point = random.choice(
		[
			"En düşük fiyat garantisi",
			"Hızlı kargo",
			"Ücretsiz iade",
			"Toptan özel fiyat",
			"Yeni sezon ürünü",
			"",
		]
	)
	doc.route = f"urun/{slug}"
	doc.meta_title = title
	doc.meta_description = _short(title, cat_name)

	# Child table satırları
	for vi in variant_items:
		doc.append("variant_items", vi)
	for pt in pricing_tiers:
		doc.append("pricing_tiers", pt)
	for av in attribute_values:
		doc.append("attribute_values", av)
	for li in listing_images:
		doc.append("listing_images", li)
	for lt in lead_time_ranges:
		doc.append("lead_time_ranges", lt)
	for smi in shipping_methods:
		doc.append("shipping_methods", smi)

	# Ürün sertifikaları (Listing Certification → product_certifications child table).
	# Satıcının Product kategorili cert'lerinden rastgele 1-2 tane seçilir.
	seller_doc = frappe.get_cached_doc("Admin Seller Profile", seller)
	seller_product_certs = [
		row.certification_type
		for row in (seller_doc.get("certifications") or [])
		if row.certification_type
		and frappe.db.get_value("Certification Type", row.certification_type, "category") == "Product"
	]
	if seller_product_certs:
		n = min(len(seller_product_certs), random.randint(1, 2))
		for cert in random.sample(seller_product_certs, n):
			doc.append("product_certifications", {"certification_type": cert})

	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)

	return doc.name


# ─── Yardımcı veri fonksiyonları ────────────────────────────


# ─── Marka haritası (seller_code → (brand_code, brand_name)) ────
# Satıcı hesabının GERÇEK KİŞİ (iletişim/yetkili) adı — User.first_name/last_name.
# Mağaza/şirket adı SELLERS[*]["seller_name"]'de ayrı durur (User ≠ şirket).
SELLER_CONTACTS = {
	"DEMO-001": ("Mehmet", "Yılmaz"),
	"DEMO-002": ("Ayşe", "Demir"),
	"DEMO-003": ("Mustafa", "Kaya"),
	"DEMO-004": ("Hasan", "Çelik"),
	"DEMO-005": ("Fatma", "Şahin"),
	"DEMO-006": ("Zeynep", "Arslan"),
	"DEMO-007": ("Ahmet", "Yıldız"),
	"DEMO-008": ("Elif", "Aydın"),
	"DEMO-009": ("Emre", "Koç"),
	"DEMO-010": ("Selin", "Öztürk"),
}

BRANDS = {
	"DEMO-001": ("DEMO-BRAND-ANADOLU", "Anadolu"),
	"DEMO-002": ("DEMO-BRAND-BOGAZICI", "Boğaziçi"),
	"DEMO-003": ("DEMO-BRAND-MARMARAT", "MarmaraT"),
	"DEMO-004": ("DEMO-BRAND-ISTHIRDAVAT", "İstHırdavat"),
	"DEMO-005": ("DEMO-BRAND-KARADENIZG", "KaradenizG"),
	"DEMO-006": ("DEMO-BRAND-EGEBEAUTY", "EgeBeauty"),
	"DEMO-007": ("DEMO-BRAND-TRAKYAHOME", "TrakyaHome"),
	"DEMO-008": ("DEMO-BRAND-AKDENIZMUT", "AkdenizMut"),
	"DEMO-009": ("DEMO-BRAND-OSMANLIAKS", "OsmanlıAks"),
	"DEMO-010": ("DEMO-BRAND-YILDIZAMB", "YıldızAmb"),
}


def _get_brand_name(seller_code):
	"""Satıcıya uygun marka adı (görüntüleme için)."""
	return BRANDS.get(seller_code, ("DEMO-BRAND-ISTOC", "İstoç"))[1]


def _ensure_brand(seller_code, sector_key="giyim"):
	"""Brand dokümanı oluştur (yoksa). brand_code döndür — Listing.brand Link için."""
	brand_code, brand_name = BRANDS.get(seller_code, ("DEMO-BRAND-ISTOC", "İstoç"))
	if frappe.db.exists("Brand", brand_code):
		return brand_code

	doc = frappe.new_doc("Brand")
	doc.brand_code = brand_code
	doc.brand_name = brand_name
	doc.slug = _slug(brand_code)
	doc.is_active = 1
	doc.status = "Approved"
	doc.official_status = "Verified"
	doc.country = "Turkey"
	doc.logo = _demo_logo(seller_code, brand_name, sector_key) or _seller_icon_logo(seller_code, 200)
	doc.hero_banner = _demo_cover(seller_code, brand_name, sector_key) or _img(
		sector_key, 1920, 400, lock_id=f"brand-{brand_code}-hero"
	)
	doc.tagline = f"{brand_name} — Kalite ve Güven"
	doc.about_title = "Hakkımızda"
	doc.about_content = (
		f"<p><strong>{brand_name}</strong>, İstoç Ticaret Merkezi'nin köklü markalarından biridir.</p>"
	)
	doc.meta_title = brand_name
	doc.meta_description = f"{brand_name} — toptan satış, kaliteli ürünler"
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	return brand_code


# ─── Standart kargo yöntemleri ─────────────────────────────────
SHIPPING_METHODS = [
	{
		"method_name": "Aras Kargo",
		"shipping_type": "Standard",
		"min_days": 2,
		"max_days": 5,
		"base_cost": 35.0,
		"cost_per_kg": 5.0,
	},
	{
		"method_name": "Yurtiçi Kargo",
		"shipping_type": "Standard",
		"min_days": 2,
		"max_days": 4,
		"base_cost": 40.0,
		"cost_per_kg": 6.0,
	},
	{
		"method_name": "MNG Kargo Express",
		"shipping_type": "Express",
		"min_days": 1,
		"max_days": 2,
		"base_cost": 60.0,
		"cost_per_kg": 8.0,
	},
	{
		"method_name": "DHL Yurtdışı",
		"shipping_type": "Air",
		"min_days": 3,
		"max_days": 7,
		"base_cost": 180.0,
		"cost_per_kg": 22.0,
	},
]


def _ensure_shipping_method(m):
	"""Shipping Method oluştur (yoksa). method_name döndür."""
	if frappe.db.exists("Shipping Method", m["method_name"]):
		return m["method_name"]

	doc = frappe.new_doc("Shipping Method")
	doc.method_name = m["method_name"]
	doc.shipping_type = m["shipping_type"]
	doc.is_active = 1
	doc.min_days = m["min_days"]
	doc.max_days = m["max_days"]
	doc.base_cost = m["base_cost"]
	doc.cost_per_kg = m["cost_per_kg"]
	doc.currency = "TRY" if frappe.db.exists("Currency", "TRY") else "USD"
	doc.free_shipping_threshold = 0
	doc.description = f"{m['method_name']} — {m['min_days']}-{m['max_days']} gün teslimat"
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return m["method_name"]


# ─── Standart spec attribute'ları ──────────────────────────────
PRODUCT_ATTRIBUTES = [
	{"code": "DEMO-ATTR-MARKA", "label": "Marka", "group": "Genel", "data_type": "Text"},
	{"code": "DEMO-ATTR-MENSEI", "label": "Menşei", "group": "Genel", "data_type": "Text"},
	{"code": "DEMO-ATTR-MALZEME", "label": "Malzeme", "group": "Teknik", "data_type": "Text"},
	{"code": "DEMO-ATTR-AGIRLIK", "label": "Net Ağırlık", "group": "Teknik", "data_type": "Text"},
	{"code": "DEMO-ATTR-PAKET", "label": "Paketleme", "group": "Lojistik", "data_type": "Text"},
	{"code": "DEMO-ATTR-SERTIFIKA", "label": "Sertifika", "group": "Uyum", "data_type": "Text"},
	{"code": "DEMO-ATTR-GARANTI", "label": "Garanti", "group": "Satış", "data_type": "Text"},
	{"code": "DEMO-ATTR-KULLANIM", "label": "Kullanım Alanı", "group": "Genel", "data_type": "Text"},
	{"code": "DEMO-ATTR-OZELLIK", "label": "Öne Çıkan Özellik", "group": "Genel", "data_type": "Text"},
	{"code": "DEMO-ATTR-BAKIM", "label": "Bakım / Saklama", "group": "Kullanım", "data_type": "Text"},
]


def _ensure_product_attribute(a):
	"""Product Attribute oluştur (yoksa). attribute_code döndür."""
	if frappe.db.exists("Product Attribute", a["code"]):
		return a["code"]

	doc = frappe.new_doc("Product Attribute")
	doc.attribute_code = a["code"]
	doc.attribute_label = a["label"]
	doc.attribute_group = a["group"]
	doc.data_type = a["data_type"]
	doc.is_active = 1
	doc.is_public = 1
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return a["code"]


def _get_material(variant_type):
	"""Sektöre uygun malzeme bilgisi döndür."""
	materials = {
		"giyim": "Pamuk / Polyester Karışım",
		"ayakkabi": "Hakiki Deri",
		"elektronik": "ABS Plastik / Metal",
		"hirdavat": "Krom-Vanadyum Çelik",
		"gida": "Doğal / Organik",
		"kozmetik": "Doğal Özler",
		"ev_tekstili": "Pamuk / Polyester",
		"mutfak": "Paslanmaz Çelik / Granit",
		"bijuteri": "925 Ayar Gümüş / Çelik",
		"kirtasiye": "Geri Dönüştürülebilir Kağıt",
	}
	return materials.get(variant_type, "Karışık")


# ─── Sektör bazlı ürün spesifikasyon havuzu ──────────────────────
# Her sektör için MALZEME / SERTIFIKA / GARANTI / KULLANIM / OZELLIK / BAKIM /
# PAKET değerleri B2B ticarette gerçekçi karşılıklarıyla doldurulur.
SECTOR_SPECS = {
	"giyim": {
		"MALZEME": ["%100 Pamuk Süprem", "%65 Pamuk %35 Polyester", "Modal / Pamuk Karışımı", "Penye Pamuk"],
		"SERTIFIKA": "OEKO-TEX Standard 100",
		"GARANTI": "Üretim hatasına karşı 14 gün iade ve değişim",
		"KULLANIM": "Günlük giyim, kurumsal üniforma, perakende mağaza",
		"OZELLIK": "Nefes alabilen kumaş, anti-pilling, renk haslığı yüksek",
		"BAKIM": "30°C makine yıkaması, ters çevirerek ütüleme",
		"PAKET": "Tekli polibag + 12'li ana koli",
	},
	"ayakkabi": {
		"MALZEME": [
			"Hakiki Deri Üst, Kauçuk Taban",
			"Suni Deri / EVA Taban",
			"Süet Deri / TPR Taban",
			"Tekstil Üst / PU Taban",
		],
		"SERTIFIKA": "CE / REACH uyumlu, kromsuz tabaklama",
		"GARANTI": "Taban ve dikiş için 6 ay üretici garantisi",
		"KULLANIM": "Günlük kullanım, ofis, kurumsal hediye",
		"OZELLIK": "Anatomik iç taban, kaymaz dış taban, esnek yapı",
		"BAKIM": "Nemli bezle silin; deri bakım kremi önerilir",
		"PAKET": "Tekli ayakkabı kutusu + 6'lı ana koli",
	},
	"elektronik": {
		"MALZEME": ["ABS Plastik Gövde, Metal İç Şasi", "Alüminyum Gövde", "Polikarbonat / Cam"],
		"SERTIFIKA": "CE, RoHS, FCC, TSE belgeli",
		"GARANTI": "24 ay resmi distribütör garantisi (parça-işçilik dahil)",
		"KULLANIM": "Ev / ofis / mağaza elektroniği, kurumsal alım",
		"OZELLIK": "Düşük güç tüketimi, aşırı yük koruması, sessiz çalışma",
		"BAKIM": "Kuru bezle temizleyin; nemli ortamdan uzak tutun",
		"PAKET": "Köpük dolgulu kutu + barkodlu master karton",
	},
	"hirdavat": {
		"MALZEME": ["Krom-Vanadyum Çelik (Cr-V)", "Karbon Çelik / Kromlanmış", "Paslanmaz Çelik (304)"],
		"SERTIFIKA": "DIN / ISO 9001 standardına uygun üretim",
		"GARANTI": "Üretim hatasına karşı ömür boyu değişim",
		"KULLANIM": "Profesyonel atölye, sanayi, inşaat",
		"OZELLIK": "Yüksek tork dayanımı, kaymaz sap, korozyon dirençli",
		"BAKIM": "Kullanım sonrası kuru bezle silin, yağlı saklayın",
		"PAKET": "Blister ambalaj + 24'lü display koli",
	},
	"gida": {
		"MALZEME": ["Doğal / Organik Tarım", "Glütensiz", "Şeker İlavesiz", "GDO'suz"],
		"SERTIFIKA": "ISO 22000, Helal, Organik Tarım Sertifikası",
		"GARANTI": "Üretim tarihinden itibaren 18 ay raf ömrü",
		"KULLANIM": "Perakende market, HoReCa, kurumsal mutfak",
		"OZELLIK": "Katkı maddesi içermez, soğuk zincir uyumlu",
		"BAKIM": "Serin, kuru ve doğrudan güneş ışığından uzak saklayın",
		"PAKET": "Vakumlu paket + barkodlu koli (gıda onaylı)",
	},
	"kozmetik": {
		"MALZEME": ["Doğal Bitkisel Özler", "Vegan / Cruelty-Free", "Paraben & Sülfat İçermez"],
		"SERTIFIKA": "GMP, ISO 22716, dermatolojik test edilmiştir",
		"GARANTI": "Açılmamış ürün için 24 ay raf ömrü, açıldıktan sonra 12 ay (12M)",
		"KULLANIM": "Tüm cilt tipleri için uygun, günlük bakım",
		"OZELLIK": "Hipoalerjenik formül, parfümsüz, ph dengeli",
		"BAKIM": "25°C altında, kapağı sıkıca kapalı saklayın",
		"PAKET": "Tekli kutu + içlik + 24'lü teşhir kolisi",
	},
	"ev_tekstili": {
		"MALZEME": ["%100 Pamuk Saten", "%50 Pamuk %50 Polyester", "Mikrofiber"],
		"SERTIFIKA": "OEKO-TEX Standard 100, anti-bakteriyel apre",
		"GARANTI": "Renk solmasına karşı 1 yıl iade garantisi",
		"KULLANIM": "Otel / ev tekstili, toplu konaklama tesisleri",
		"OZELLIK": "Yüksek emicilik, çekmeyen kumaş, ütü gerektirmez",
		"BAKIM": "40°C yıkama, düşük ısıda kurutma, tumbler dryer uyumlu",
		"PAKET": "Şeffaf çanta + askılı kart + 10'lu koli",
	},
	"mutfak": {
		"MALZEME": ["Paslanmaz Çelik 18/10", "Granit Kaplı Alüminyum", "Borosilikat Cam"],
		"SERTIFIKA": "LFGB / FDA gıda teması onaylı",
		"GARANTI": "10 yıl indüksiyon tabanı, 2 yıl genel kullanım garantisi",
		"KULLANIM": "Ev mutfağı, restoran, catering, profesyonel kullanım",
		"OZELLIK": "Bulaşık makinesinde yıkanabilir, indüksiyon uyumlu, ısı dağılımı homojen",
		"BAKIM": "Aşındırıcı kullanmayın; yumuşak süngerle yıkayın",
		"PAKET": "Renkli kutu + iç köpük + 6'lı master koli",
	},
	"bijuteri": {
		"MALZEME": ["925 Ayar Gümüş", "316L Cerrahi Çelik", "Altın Kaplama Pirinç (3 Mikron)"],
		"SERTIFIKA": "Nikel-free, hipoalerjenik (EN 1811 uyumlu)",
		"GARANTI": "Kaplama için 12 ay, taş düşmesine karşı 30 gün değişim",
		"KULLANIM": "Günlük takı, davet, hediyelik, kurumsal hediye",
		"OZELLIK": "Karartmaz kaplama, su ve ter dayanımlı, hipoalerjenik",
		"BAKIM": "Parfüm temasından koruyun; kuru ve havalı yerde saklayın",
		"PAKET": "Mıknatıslı sunum kutusu + bez torba",
	},
	"kirtasiye": {
		"MALZEME": ["FSC Sertifikalı Selüloz Kağıt", "Geri Dönüştürülmüş Karton", "Asit-free Kağıt"],
		"SERTIFIKA": "FSC, EN 71-3 (boya güvenliği)",
		"GARANTI": "Üretim hatasına karşı paket içi değişim",
		"KULLANIM": "Okul, ofis, kurumsal kırtasiye alımı",
		"OZELLIK": "Mürekkep akıtmayan kağıt, dayanıklı cilt, ergonomik tasarım",
		"BAKIM": "Nemli ortamdan uzak tutun; rafta dik saklayın",
		"PAKET": "Shrink + 50'lik koli, palet uyumlu",
	},
}


# ─── Kategori bazlı spec override'ları ───────────────────────────
# `dj_cat` (DummyJSON kategori anahtarı) → SECTOR_SPECS üzerinde override.
# Sektör default'undan daha spesifik, ürünle ilgili metinler.
CATEGORY_SPECS = {
	"smartphones": {
		"MALZEME": "Alüminyum gövde, Gorilla Glass ön/arka panel",
		"OZELLIK": "OLED ekran, hızlı şarj, kablosuz şarj, IP68 toz/su koruması",
		"KULLANIM": "Akıllı telefon — iletişim, mobil çalışma, fotoğraf/video çekimi",
		"GARANTI": "24 ay resmi distribütör garantisi (parça-işçilik dahil)",
		"PAKET": "Köpük dolgulu kutu + adaptör + USB-C kablo + barkodlu master karton",
		"BAKIM": "Yumuşak nemli bezle silin; doğrudan ısıdan ve manyetik alandan uzak tutun",
	},
	"laptops": {
		"MALZEME": "Alüminyum unibody gövde, IPS dokunmatik olmayan ekran",
		"OZELLIK": "SSD depolama, çok çekirdekli işlemci, uzun pil ömrü, arkadan aydınlatmalı klavye",
		"KULLANIM": "Dizüstü bilgisayar — ofis, üretkenlik, mobil çalışma, kurumsal alım",
		"GARANTI": "24 ay üretici garantisi + ücretsiz teknik servis",
		"PAKET": "Köpük dolgulu kutu + adaptör + güç kablosu + master karton",
	},
	"tablets": {
		"MALZEME": "Alüminyum gövde, ince çerçeveli IPS / OLED ekran",
		"OZELLIK": "Hassas dokunmatik ekran, kalem desteği, hızlı şarj, hafif gövde",
		"KULLANIM": "Tablet — sunum, eğitim, perakende POS, mobil saha kullanımı",
	},
	"mobile-accessories": {
		"MALZEME": "Polikarbonat / TPU karışımı, anti-shock köşe yapısı",
		"OZELLIK": "Çok yönlü uyumluluk, kaymaz tutuş, kablo dayanımı, anti-shock",
		"KULLANIM": "Telefon aksesuarı — kılıf, kablo, şarj cihazı, ekran koruyucu",
	},
	"mens-shirts": {
		"MALZEME": "%100 Pamuk Süprem (Ne 30/1), reaktif boyalı",
		"OZELLIK": "Solmaz baskı, ütü gerektirmez kumaş, slim-fit kesim, terlemez yapı",
		"KULLANIM": "Erkek günlük gömlek — ofis, kurumsal üniforma, perakende mağaza",
	},
	"tops": {
		"MALZEME": "Pamuk-modal karışımı, ribana yaka",
		"OZELLIK": "Yumuşak doku, anti-pilling apre, formunu korur, nefes alabilir",
		"KULLANIM": "Üst giyim — günlük kullanım, kombin temel parça, mağaza vitrini",
	},
	"womens-dresses": {
		"MALZEME": "Viskon / polyester karışımı, doğal düşüm",
		"OZELLIK": "Hafif yapı, dökümlü kesim, kolay bakım, çekmez kumaş",
		"KULLANIM": "Kadın elbise — günlük, davet, ofis kombini",
	},
	"mens-shoes": {
		"MALZEME": "Hakiki deri üst, kauçuk dış taban, deri astar",
		"OZELLIK": "Anatomik iç taban, dikişli sandık, kaymaz dış taban, aşınma dirençli",
		"KULLANIM": "Erkek günlük ve klasik ayakkabı — ofis, kurumsal, hediye",
	},
	"womens-shoes": {
		"MALZEME": "Suni deri üst, EVA hafif taban",
		"OZELLIK": "Esnek yapı, ortopedik destek, kaymaz dış taban",
		"KULLANIM": "Kadın günlük ve casual ayakkabı — mağaza, ofis, davet",
	},
	"womens-bags": {
		"MALZEME": "Vegan deri (PU), polyester astar, metal aksesuar",
		"OZELLIK": "Çok bölmeli iç tasarım, ayarlanabilir askı, fermuar kapama",
		"KULLANIM": "Kadın çanta — günlük, davet, iş kullanımı",
	},
	"sports-accessories": {
		"MALZEME": "Sentetik deri / kauçuk / paslanmaz çelik kombinasyon",
		"OZELLIK": "Kayma önleyici yüzey, dayanıklı malzeme, ergonomik tasarım, ter dayanımlı",
		"KULLANIM": "Spor ekipmanı — fitness merkezi, açık hava, kulüp ekipmanı",
	},
	"motorcycle": {
		"MALZEME": "Yüksek dayanımlı çelik / alüminyum alaşım",
		"OZELLIK": "Aşınma dirençli kaplama, OEM uyumlu, vibrasyon dayanımı, korozyona karşı dirençli",
		"KULLANIM": "Motosiklet aksesuarı / yedek parça — yetkili servis ve perakende",
	},
	"vehicle": {
		"MALZEME": "Polipropilen / metal hibrit yapı",
		"OZELLIK": "OE standardı, korozyon dirençli, evrensel araç uyumu",
		"KULLANIM": "Otomotiv yedek parça ve aksesuar — servis ve oto market",
	},
	"groceries": {
		"MALZEME": "Doğal / organik içerik — GDO içermez",
		"OZELLIK": "Katkı maddesi yok, koruyucu içermez, glütensiz seçenekler",
		"KULLANIM": "Market ürünü — perakende, HoReCa, kurumsal mutfak",
	},
	"beauty": {
		"MALZEME": "Bitkisel özler, vegan formül, paraben içermez",
		"OZELLIK": "Hipoalerjenik formül, dermatolojik test edilmiştir, parfümsüz seçenek",
		"KULLANIM": "Güzellik ürünü — günlük cilt/saç bakımı, profesyonel kabin",
	},
	"fragrances": {
		"MALZEME": "Yüksek konsantrasyon esans (EDP/EDT), %96 saflıkta etanol",
		"OZELLIK": "Uzun kalıcılık (8-12 saat), yoğun sillage, IFRA uyumlu kompozisyon",
		"KULLANIM": "Parfüm — günlük, davet, hediye",
	},
	"skin-care": {
		"MALZEME": "Hyalüronik asit, niasinamid, doğal botanikal özler",
		"OZELLIK": "Tüm cilt tipleri için uygun, yağsız hafif doku, gece-gündüz kullanım",
		"KULLANIM": "Cilt bakımı — günlük rutin, profesyonel kabin uygulaması",
	},
	"home-decoration": {
		"MALZEME": "MDF / ahşap / metal kombinasyonu",
		"OZELLIK": "Modern tasarım, kolay montaj, çizilmeye dayanıklı yüzey",
		"KULLANIM": "Ev dekorasyonu — salon, yatak odası, ofis dekor, hediye",
	},
	"furniture": {
		"MALZEME": "Birinci sınıf MDF + masif ahşap iskelet",
		"OZELLIK": "Çizilmeye dayanıklı yüzey, kolay montaj, çelik bağlantı elemanları",
		"KULLANIM": "Mobilya — ev, ofis, otel, kurumsal kullanım",
	},
	"kitchen-accessories": {
		"MALZEME": "Paslanmaz çelik 18/10 + ısıya dayanıklı silikon sap",
		"OZELLIK": "Bulaşık makinesinde yıkanabilir, indüksiyon uyumlu, ergonomik tutuş",
		"KULLANIM": "Mutfak aksesuarı — ev mutfağı, restoran, catering, profesyonel",
	},
	"womens-jewellery": {
		"MALZEME": "925 ayar gümüş / 18 ayar altın kaplama (3 mikron)",
		"OZELLIK": "Karartmaz kaplama, hipoalerjenik, su ve ter dayanımlı",
		"KULLANIM": "Kadın takı — günlük, davet, hediyelik, kurumsal hediye",
	},
	"sunglasses": {
		"MALZEME": "TR-90 polimer çerçeve, polarize cam (UV400 koruma)",
		"OZELLIK": "%100 UV koruma, hafif ergonomik çerçeve, polarize lens",
		"KULLANIM": "Güneş gözlüğü — günlük, açık hava, sürüş, plaj",
	},
	"mens-watches": {
		"MALZEME": "316L paslanmaz çelik kasa, mineral cam, deri/çelik kayış",
		"OZELLIK": "5 ATM su geçirmezlik, kuvars hareket, takvim göstergesi",
		"KULLANIM": "Erkek kol saati — ofis, günlük, hediye",
	},
	"womens-watches": {
		"MALZEME": "316L paslanmaz çelik kasa, hardlex cam",
		"OZELLIK": "Şık ince kasa, kuvars hareket, hipoalerjenik kayış",
		"KULLANIM": "Kadın kol saati — günlük, davet, hediye",
	},
}


def _build_attribute_values(seller, variant_type, weight, dj_cat=None, cat_name=None, base_title=None):
	"""Sektör + kategori + ürün başlığına göre anlamlı spec satırları üret.

	`attribute_label` programatik insert'te fetch_from çalışmadığından elle doldurulur.
	`dj_cat` verilirse CATEGORY_SPECS sektör default'unu override eder.
	`cat_name` ve `base_title` kullanım/öne çıkan özellik metnine zenginleştirme katar.
	"""
	brand_name = _get_brand_name(seller)
	base_specs = SECTOR_SPECS.get(variant_type, SECTOR_SPECS["giyim"])

	malzeme = base_specs["MALZEME"]
	if isinstance(malzeme, list):
		malzeme = random.choice(malzeme)

	ozellik = base_specs["OZELLIK"]
	kullanim = base_specs["KULLANIM"]
	sertifika = base_specs["SERTIFIKA"]
	garanti = base_specs["GARANTI"]
	bakim = base_specs["BAKIM"]
	paket = base_specs["PAKET"]

	# Kategori override'ı
	cat_overrides = CATEGORY_SPECS.get(dj_cat or "", {})
	malzeme = cat_overrides.get("MALZEME", malzeme)
	ozellik = cat_overrides.get("OZELLIK", ozellik)
	kullanim = cat_overrides.get("KULLANIM", kullanim)
	sertifika = cat_overrides.get("SERTIFIKA", sertifika)
	garanti = cat_overrides.get("GARANTI", garanti)
	bakim = cat_overrides.get("BAKIM", bakim)
	paket = cat_overrides.get("PAKET", paket)

	# Ürün başlığını (kısa) özellik satırına ekle: ürünle ilgili olduğunu vurgular
	if base_title:
		short_title = base_title if len(base_title) <= 40 else base_title[:37] + "…"
		ozellik = f"{short_title}: {ozellik}"

	# Net ağırlık
	if weight < 1:
		agirlik = f"{int(weight * 1000)} g"
	elif weight < 10:
		agirlik = f"{weight:.2f} kg"
	else:
		agirlik = f"{weight:.1f} kg"

	label_map = {a["code"]: a["label"] for a in PRODUCT_ATTRIBUTES}

	rows_def = [
		("DEMO-ATTR-MARKA", brand_name, "Genel", 1),
		("DEMO-ATTR-MENSEI", "Türkiye", "Genel", 2),
		("DEMO-ATTR-MALZEME", malzeme, "Teknik", 3),
		("DEMO-ATTR-AGIRLIK", agirlik, "Teknik", 4),
		("DEMO-ATTR-OZELLIK", ozellik, "Genel", 5),
		("DEMO-ATTR-KULLANIM", kullanim, "Genel", 6),
		("DEMO-ATTR-SERTIFIKA", sertifika, "Uyum", 7),
		("DEMO-ATTR-GARANTI", garanti, "Satış", 8),
		("DEMO-ATTR-BAKIM", bakim, "Kullanım", 9),
		("DEMO-ATTR-PAKET", paket, "Lojistik", 10),
	]
	return [
		{
			"attribute": code,
			"attribute_label": label_map.get(code, code),
			"attribute_value": value,
			"attribute_group": group,
			"display_order": order,
		}
		for code, value, group, order in rows_def
	]


# ═══════════════════════════════════════════════════════════════
#  ANASAYFA VİTRİNİ: Hero Slider + Kategori Vitrini (Bento Grid)
# ═══════════════════════════════════════════════════════════════
#
# Bu içerikler admin panelden girilen DOCTYPE kayıtlarıdır (kod değil) —
# git ile taşınmazlar, her ortamın kendi DB'sinde durur. Demo ortamların
# anasayfası boş kalmasın diye seed ile deterministik olarak üretilir.
# İlgili storefront component'leri: HeroTopSlider + CategoryShowcase (bento).

# Hero slider slide'ları — B2B marketplace temalı, site içeriğine uygun.
# bg gradient: background_color → background_color_2 (gradient_angle derece).
HERO_SLIDES = [
	{
		"label_tr": "TREND UYARISI",
		"label_en": "TRENDING NOW",
		"title_tr": "Sezonun en çok tercih edilen ürünleri",
		"title_en": "This season's most preferred products",
		"description_tr": "Binlerce alıcının tercih ettiği çok satan ürünleri keşfedin, sevkiyata hazır tedarikçilerle bağlantı kurun.",
		"description_en": "Discover best-selling products preferred by thousands of buyers and connect with ready-to-ship suppliers.",
		"button_text_tr": "Çok satanları gör",
		"button_text_en": "View best-sellers",
		"button_href": "/cok-satanlar",
		"background_color": "#059669",
		"background_color_2": "#10b981",
		"gradient_angle": 135,
		"content_align": "center",
	},
	{
		"label_tr": "DOĞRULANMIŞ ÜRETİCİLER",
		"label_en": "VERIFIED MANUFACTURERS",
		"title_tr": "Doğrulanmış üreticilerle güvenle çalışın",
		"title_en": "Work safely with verified manufacturers",
		"description_tr": "Binlerce doğrulanmış fabrikadan rekabetçi tekliflerle toptan tedarik edin.",
		"description_en": "Source wholesale from thousands of verified factories with competitive offers.",
		"button_text_tr": "Üreticileri keşfet",
		"button_text_en": "Discover manufacturers",
		"button_href": "/ureticiler",
		"background_color": "#1e3a8a",
		"background_color_2": "#3b82f6",
		"gradient_angle": 135,
		"content_align": "left",
	},
	{
		"label_tr": "FIRSATLAR",
		"label_en": "DEALS",
		"title_tr": "Toptan fiyat avantajını yakalayın",
		"title_en": "Catch the wholesale price advantage",
		"description_tr": "%100 fiyat garantisiyle binlerce üründe avantajlı toptan fiyatlar ve günlük fırsatlar.",
		"description_en": "Advantageous wholesale prices and daily deals on thousands of products with 100% price guarantee.",
		"button_text_tr": "Fırsatları gör",
		"button_text_en": "View deals",
		"button_href": "/firsatlar",
		"background_color": "#b45309",
		"background_color_2": "#f59e0b",
		"gradient_angle": 135,
		"content_align": "left",
	},
]

# Bento grid kutuları — gerçek demo sektör kategorilerine (DEMO-SEC-*) linkli.
# category kutuları: sektör görselli; promo kutuları: düz renk + CTA.
# Layout 4 sütunlu grid'e göre tasarlandı (col_span/row_span).
SHOWCASE_TILES = [
	{
		"tile_type": "category", "col_span": 1, "row_span": 2, "sort_order": 0,
		"label_tr": "Tekstil ve Giyim", "label_en": "Textile & Apparel",
		"sector_key": "giyim", "sector_code": "TG",
		"hover_text_tr": "Toptan tekstil ve hazır giyim", "hover_text_en": "Wholesale textile & apparel",
	},
	{
		"tile_type": "category", "col_span": 1, "row_span": 2, "sort_order": 1,
		"label_tr": "Ayakkabı ve Deri", "label_en": "Footwear & Leather",
		"sector_key": "ayakkabi", "sector_code": "AD",
		"hover_text_tr": "Ayakkabı, çanta ve deri ürünleri", "hover_text_en": "Shoes, bags & leather goods",
	},
	{
		"tile_type": "category", "col_span": 2, "row_span": 1, "sort_order": 2,
		"label_tr": "Elektronik ve Aksesuar", "label_en": "Electronics & Accessories",
		"sector_key": "elektronik", "sector_code": "EL",
		"hover_text_tr": "Telefon, bilgisayar ve aksesuar", "hover_text_en": "Phones, computers & accessories",
	},
	{
		"tile_type": "category", "col_span": 1, "row_span": 1, "sort_order": 3,
		"label_tr": "Kozmetik ve Kişisel Bakım", "label_en": "Cosmetics & Personal Care",
		"sector_key": "kozmetik", "sector_code": "KZ",
		"hover_text_tr": "Makyaj, bakım ve parfüm", "hover_text_en": "Makeup, care & fragrances",
	},
	{
		"tile_type": "promo", "col_span": 1, "row_span": 1, "sort_order": 4,
		"promo_badge_tr": "TİCARET GÜVENCESİ", "promo_badge_en": "TRADE ASSURANCE",
		"promo_title_tr": "Güvenli ödeme, teslimat garantisi", "promo_title_en": "Secure payment, delivery guarantee",
		"background_color": "#1e3a8a",
		"cta_text_tr": "Nasıl çalışır?", "cta_text_en": "How it works", "cta_href": "/ticaret-guvencesi",
	},
]


def _seed_hero_slider():
	"""Hero slider için demo Hero Slide kayıtları (idempotent: önce hepsini sil)."""
	frappe.db.delete("Hero Slide")
	for idx, s in enumerate(HERO_SLIDES):
		doc = frappe.new_doc("Hero Slide")
		doc.update(s)
		doc.background_type = "gradient"
		doc.text_color = "#ffffff"
		doc.overlay = 0
		doc.is_active = 1
		doc.sort_order = (idx + 1) * 10
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
	print(f"  ✓ {len(HERO_SLIDES)} Hero Slide (gradient)")


def _seed_category_showcase():
	"""Bento grid: Settings'i enable et + demo tile'lar (idempotent)."""
	settings = frappe.get_single("Category Showcase Settings")
	settings.is_enabled = 1
	settings.columns = 4
	settings.section_title_tr = "Kategorileri keşfet"
	settings.section_title_en = "Explore categories"
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)

	frappe.db.delete("Category Showcase Tile")
	for t in SHOWCASE_TILES:
		doc = frappe.new_doc("Category Showcase Tile")
		doc.tile_type = t["tile_type"]
		doc.col_span = t["col_span"]
		doc.row_span = t["row_span"]
		doc.sort_order = t["sort_order"]
		doc.is_active = 1
		if t["tile_type"] == "category":
			doc.label_tr = t["label_tr"]
			doc.label_en = t["label_en"]
			doc.hover_text_tr = t.get("hover_text_tr", "")
			doc.hover_text_en = t.get("hover_text_en", "")
			doc.image = _img(t["sector_key"], 800, 800, lock_id=f"tile-{t['sector_code']}")
			# Ürün listeleme sayfası, kategori slug filtresiyle (?cat=).
			# /kategori/{slug} yerine /urunler?cat= kullanılır: ikisi de canonical
			# kategori URL'i ama /urunler tam SPA olarak local + prod'da çalışır;
			# /kategori/{slug} local Frappe'de SEO bot-kabuğuna düşüp blank kalıyor.
			# Sektör kategorisi DEMO-SEC-{code} → url_slug = _slug("DEMO-SEC-{code}")
			doc.link_href = f"/urunler?cat={_slug('DEMO-SEC-' + t['sector_code'])}"
		else:
			doc.promo_badge_tr = t.get("promo_badge_tr", "")
			doc.promo_badge_en = t.get("promo_badge_en", "")
			doc.promo_title_tr = t.get("promo_title_tr", "")
			doc.promo_title_en = t.get("promo_title_en", "")
			doc.background_color = t.get("background_color", "#1e3a8a")
			doc.cta_text_tr = t.get("cta_text_tr", "")
			doc.cta_text_en = t.get("cta_text_en", "")
			doc.cta_href = t.get("cta_href", "/kategoriler")
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
	print(f"  ✓ {len(SHOWCASE_TILES)} Category Showcase Tile (bento) + Settings enabled")


@frappe.whitelist()
def seed_homepage_content():
	"""Sadece anasayfa vitrinini (slider + bento) seed et — tam reseed YAPMADAN.

	Kullanım (bench):
	    bench --site <site> execute tradehub_core.seed_demo_data.seed_homepage_content
	"""
	frappe.flags.ignore_permissions = True
	print("\n[Anasayfa] Hero slider + kategori vitrini seed ediliyor...")
	_seed_hero_slider()
	_seed_category_showcase()
	frappe.db.commit()
	# 60s Redis cache'leri temizle ki storefront hemen görsün.
	frappe.cache.delete_value("hero_slides_active")
	frappe.cache.delete_value("category_showcase_active")
	print("  ✅ Anasayfa vitrini hazır.")


# ═══════════════════════════════════════════════════════════════
#  ANA FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════


@frappe.whitelist()
def execute():
	"""
	Demo veri oluştur: 10 satıcı · 5 alıcı · 500 kategori · 1.000 ürün

	Bu fonksiyon **önce `cleanup()`'ı çağırır** — eski demo verileri silip
	yenilerini yeniden kurar. Böylece her çalıştırma deterministik sonuç verir.

	Kullanım (bench):
	    bench --site <site> execute tradehub_core.seed_demo_data.execute

	Kullanım (tarayıcı konsolu — Login as Administrator sonrası):
	    frappe.call({method: "tradehub_core.seed_demo_data.execute"})
	"""
	if not frappe.session.user == "Administrator" and not frappe.has_permission(
		"Admin Seller Profile", "create"
	):
		frappe.throw(_("Bu işlem için Administrator yetkisi gereklidir."))
	frappe.flags.ignore_permissions = True
	frappe.flags.in_import = True
	random.seed(42)  # Tekrarlanabilir sonuçlar

	total_listings = 0

	print("=" * 60)
	print("  TradeHub Demo Data Seed")
	print("=" * 60)

	# ── −1. Oto-temizlik: eski demo verileri kaldır ───────────
	print("\n[Oto-temizlik] Önceki demo veriler kaldırılıyor...")
	cleanup(silent=True)
	frappe.db.commit()

	# ── 0. Global sözlükler: kargo yöntemleri + spec attribute'ları ─
	print("\n[0/6] Global sözlükler oluşturuluyor (Shipping Method, Product Attribute)...")
	for m in SHIPPING_METHODS:
		_ensure_shipping_method(m)
	print(f"  ✓ {len(SHIPPING_METHODS)} Shipping Method")
	for a in PRODUCT_ATTRIBUTES:
		_ensure_product_attribute(a)
	print(f"  ✓ {len(PRODUCT_ATTRIBUTES)} Product Attribute")
	frappe.db.commit()

	# ── 1. Satıcılar + Markalar ──────────────────────────────
	# Sıra önemli:
	# 1) _ensure_seller — Admin Seller Profile'ı DEMO-* kodlu, zenginleştirilmiş
	#    alanlarla (logo, banner, certifications, gallery) yarat. cleanup() bu
	#    kodlara göre filtreliyor; Seller Application onayında oluşan SEL-* kodlu
	#    profilini değil bu kaydı kullanır.
	# 2) _ensure_seller_application — Status=Approved başvuruyu insert et;
	#    on_update tetiklenerek Seller Profile (panelde görünen satıcı kaydı) +
	#    KYB Verification (Pending) otomatik üretilir. Admin Seller Profile zaten
	#    var olduğundan o adım atlanır.
	print("\n[1/6] Satıcı profilleri ve markalar oluşturuluyor...")
	for idx, s in enumerate(SELLERS):
		_ensure_seller(s)
		_ensure_seller_application(s)
		_fill_demo_kyb_documents(s)
		_set_demo_kyb_status(s, idx)
		_set_demo_kyc_verified(
			s["email"],
			account_type="Business",
			company_name=s["company_name"],
			tax_id=s["tax_id"],
			phone=s["phone"],
			address=f"{s['address_line1']}, {s['district']}/{s['city']}",
		)
		_ensure_brand(s["code"], s.get("variant_type", "giyim"))
		print(f"  ✓ {s['seller_name']} ({s['code']}) — KYB + KYC: Verified")
	frappe.db.commit()

	# ── 2. Alıcılar ──────────────────────────────────────────
	print("\n[2/6] Alıcı profilleri oluşturuluyor...")
	for idx, b in enumerate(BUYERS):
		_ensure_buyer(b)
		_ensure_buyer_user_profile(b)
		# BUYERS sözlüğünde tax_id/adres yok — KYC Business doğrulaması için
		# deterministik sentetik VKN (10 hane) + şehir tabanlı adres üretiriz.
		_set_demo_kyc_verified(
			b["email"],
			account_type="Business",
			company_name=b["company_name"],
			tax_id=f"20000000{idx + 1:02d}",
			phone=b["phone"],
			address=f"{b['city']} - Demo Alıcı Adresi",
		)
		print(f"  ✓ {b['buyer_name']} ({b['company_name']}) — KYC: Verified")
	frappe.db.commit()

	# ── 3. Kategoriler (3 SEVİYE: Sektör → Grup → yaprak ürün kategorisi) ─
	# Her DummyJSON kategorisi sabit bir canonical sektör + grubuna bağlı. Aynı
	# yaprak birden fazla satıcı tarafından kullanılabilir (Alibaba modeli).
	print("\n[3/6] Platform kategorileri oluşturuluyor...")

	# DummyJSON kategorisi →
	#   (sektör_key, sektör_adı, sektör_kodu, grup_adı, grup_kodu)
	DJ_TAXONOMY = {
		"mens-shirts": ("giyim", "Tekstil ve Giyim", "TG", "Erkek Giyim", "ERKGIY"),
		"tops": ("giyim", "Tekstil ve Giyim", "TG", "Kadın Giyim", "KADGIY"),
		"womens-dresses": ("giyim", "Tekstil ve Giyim", "TG", "Kadın Giyim", "KADGIY"),
		"mens-shoes": ("ayakkabi", "Ayakkabı ve Deri", "AD", "Ayakkabı", "AYAKKB"),
		"womens-shoes": ("ayakkabi", "Ayakkabı ve Deri", "AD", "Ayakkabı", "AYAKKB"),
		"womens-bags": ("ayakkabi", "Ayakkabı ve Deri", "AD", "Çanta ve Deri", "CANTAD"),
		"smartphones": ("elektronik", "Elektronik ve Aksesuar", "EL", "Telefon", "TELEFN"),
		"mobile-accessories": ("elektronik", "Elektronik ve Aksesuar", "EL", "Telefon", "TELEFN"),
		"laptops": ("elektronik", "Elektronik ve Aksesuar", "EL", "Bilgisayar", "BILGSY"),
		"tablets": ("elektronik", "Elektronik ve Aksesuar", "EL", "Bilgisayar", "BILGSY"),
		"sports-accessories": ("hirdavat", "Hırdavat ve Nalburiye", "HR", "Spor", "SPOR"),
		"motorcycle": ("hirdavat", "Hırdavat ve Nalburiye", "HR", "Motor ve Otomotiv", "MOTOR"),
		"vehicle": ("hirdavat", "Hırdavat ve Nalburiye", "HR", "Motor ve Otomotiv", "MOTOR"),
		"groceries": ("gida", "Gıda ve İçecek", "GD", "Market", "MARKT"),
		"beauty": ("kozmetik", "Kozmetik ve Kişisel Bakım", "KZ", "Makyaj ve Bakım", "MAKYAJ"),
		"skin-care": ("kozmetik", "Kozmetik ve Kişisel Bakım", "KZ", "Makyaj ve Bakım", "MAKYAJ"),
		"fragrances": ("kozmetik", "Kozmetik ve Kişisel Bakım", "KZ", "Parfüm ve Koku", "PARFKO"),
		"home-decoration": ("ev_tekstili", "Ev Tekstili ve Dekorasyon", "EV", "Dekorasyon", "DEKOR"),
		"furniture": ("ev_tekstili", "Ev Tekstili ve Dekorasyon", "EV", "Mobilya ve Ev", "MOBEV"),
		"kitchen-accessories": ("mutfak", "Mutfak ve Züccaciye", "MU", "Mutfak", "MUTFK"),
		"womens-jewellery": ("bijuteri", "Bijuteri ve Aksesuar", "BJ", "Takı", "TAKI"),
		"sunglasses": ("bijuteri", "Bijuteri ve Aksesuar", "BJ", "Takı", "TAKI"),
		"mens-watches": ("bijuteri", "Bijuteri ve Aksesuar", "BJ", "Saat", "SAAT"),
		"womens-watches": ("bijuteri", "Bijuteri ve Aksesuar", "BJ", "Saat", "SAAT"),
	}

	# Önce parent sektörleri oluştur (unique, kök)
	sector_ids = {}  # sector_code → product_category_name
	for _dj_cat, (vt, sname, scode, _gname, _gcode) in DJ_TAXONOMY.items():
		if scode in sector_ids:
			continue
		sector_ids[scode] = _ensure_category(
			sname,
			"",
			f"DEMO-SEC-{scode}",
			sort_order=0,
			sector_key=vt,
		)
	print(f"  ✓ {len(sector_ids)} sektör (kök kategori)")

	# Sonra grupları sektörün altına (unique)
	group_ids = {}  # group_code → product_category_name
	for _dj_cat, (vt, _sname, scode, gname, gcode) in DJ_TAXONOMY.items():
		if gcode in group_ids:
			continue
		group_ids[gcode] = _ensure_category(
			gname,
			sector_ids[scode],
			f"DEMO-GRP-{gcode}",
			sort_order=0,
			sector_key=vt,
		)
	print(f"  ✓ {len(group_ids)} grup (orta kategori)")

	# En sonda yaprakları grubun altına
	leaf_ids = {}
	for dj_cat, (leaf_name_tr, leaf_short) in CATEGORY_TR.items():
		products = DUMMY_PRODUCTS.get(dj_cat, [])
		if not products:
			continue
		vt, _sname, _scode, _gname, gcode = DJ_TAXONOMY[dj_cat]
		leaf_id = _ensure_category(
			leaf_name_tr,
			group_ids[gcode],
			f"DEMO-CAT-{leaf_short}",
			sort_order=0,
			sector_key=vt,
		)
		try:
			frappe.db.set_value(
				"Product Category",
				leaf_id,
				"image",
				products[0]["thumb"],
				update_modified=False,
			)
		except Exception:
			pass
		leaf_ids[dj_cat] = (leaf_id, leaf_name_tr)
	frappe.db.commit()
	print(
		f"  ✓ {len(leaf_ids)} yaprak kategori "
		f"({len(group_ids)} grup, {len(sector_ids)} sektör altında)"
	)

	# ── 4. Satıcı Kategorileri ──────────────────────────────
	print("\n[4/6] Satıcı-kategori eşleşmeleri oluşturuluyor...")
	# (seller_code, dj_cat) → seller_category_name
	seller_cat_map = {}
	for seller_code, sdef in SELLER_SECTORS.items():
		_seller = next(s for s in SELLERS if s["code"] == seller_code)
		vt = _seller["variant_type"]
		for _group_name, dj_cats in sdef["groups"]:
			for dj_cat in dj_cats:
				if dj_cat not in leaf_ids:
					continue
				leaf_id, leaf_name_tr = leaf_ids[dj_cat]
				sc_name = _ensure_seller_category(seller_code, leaf_id, leaf_name_tr, sector_key=vt)
				seller_cat_map[(seller_code, dj_cat)] = sc_name
	frappe.db.commit()
	print(f"  ✓ {len(seller_cat_map)} satıcı-kategori eşleşmesi")

	# ── 5. Ürün İlanları — her DummyJSON ürünü = 1 Listing ─
	print("\n[5/6] Ürün ilanları oluşturuluyor...")
	for seller_code, sdef in SELLER_SECTORS.items():
		seller_data = next(s for s in SELLERS if s["code"] == seller_code)
		variant_type = seller_data["variant_type"]
		price_range = seller_data["price_range"]
		sector_listings = 0
		for _group_name, dj_cats in sdef["groups"]:
			for dj_cat in dj_cats:
				products = DUMMY_PRODUCTS.get(dj_cat, [])
				if dj_cat not in leaf_ids:
					continue
				leaf_id, leaf_name_tr = leaf_ids[dj_cat]
				sc_name = seller_cat_map[(seller_code, dj_cat)]
				for pidx, product in enumerate(products, 1):
					_create_listing(
						seller=seller_code,
						seller_cat_name=sc_name,
						product_cat_id=leaf_id,
						cat_name=leaf_name_tr,
						product=product,
						product_idx=pidx,
						variant_type=variant_type,
						price_range=price_range,
					)
					total_listings += 1
					sector_listings += 1
					if sector_listings % 20 == 0:
						frappe.db.commit()
		frappe.db.commit()
		print(f"  ✓ {seller_data['seller_name']}: {sector_listings} ürün")

	frappe.db.commit()
	frappe.flags.in_import = False

	# ── 6. Anasayfa vitrini: Hero slider + kategori vitrini (bento) ─
	print("\n[6/6] Anasayfa vitrini oluşturuluyor (hero slider + bento grid)...")
	_seed_hero_slider()
	_seed_category_showcase()
	frappe.db.commit()
	frappe.cache.delete_value("hero_slides_active")
	frappe.cache.delete_value("category_showcase_active")

	print("\n" + "=" * 60)
	print("  ✅ TAMAMLANDI!")
	print(f"  Satıcılar:   {len(SELLERS)}")
	print(f"  Alıcılar:    {len(BUYERS)}")
	print("  Kategoriler: ~500")
	print(f"  Ürünler:     {total_listings}")
	print(f"  Hero slide:  {len(HERO_SLIDES)} · Bento kutu: {len(SHOWCASE_TILES)}")
	print("=" * 60)

	# ── Kimlik Bilgileri Tablosu ────────────────────────────
	print("\n" + "═" * 76)
	print("  🔑 DEMO GİRİŞ BİLGİLERİ")
	print("═" * 76)
	print(f"\n  SATICI HESAPLARI (Rol: Seller — Şifre: {DEMO_SELLER_PASSWORD})")
	print("  " + "─" * 74)
	print(f"  {'Kod':<11} {'E-posta':<32} {'Satıcı Adı':<30}")
	print("  " + "─" * 74)
	for s in SELLERS:
		print(f"  {s['code']:<11} {s['email']:<32} {s['seller_name']:<30}")

	print(f"\n  ALICI HESAPLARI (Rol: Buyer — Şifre: {DEMO_BUYER_PASSWORD})")
	print("  " + "─" * 74)
	print(f"  {'Kod':<15} {'E-posta':<32} {'Alıcı Adı':<25}")
	print("  " + "─" * 74)
	for b in BUYERS:
		print(f"  {b['code']:<15} {b['email']:<32} {b['buyer_name']:<25}")
	print("═" * 76)
	print()


@frappe.whitelist()
def verify_email(user_email):
	"""Belirtilen user için Buyer Profile.email_verified=1 yap (yoksa oluştur).

	checkout akışında auth_guards.require_verified_email() Buyer Profile'ı
	kontrol ediyor; satıcı user'ı checkout test edecekse Buyer Profile gerekir.

	Kullanım:
	    bench --site <site> execute tradehub_core.seed_demo_data.verify_email \
	        --kwargs "{'user_email': 'demo-seller-03@istoc.demo'}"
	"""
	from frappe.utils import now

	if not frappe.db.exists("User", user_email):
		frappe.throw(_("User bulunamadı: {0}").format(user_email))

	existing = frappe.db.exists("Buyer Profile", {"user": user_email})
	if existing:
		bp = frappe.get_doc("Buyer Profile", existing)
		bp.email_verified = 1
		if bp.meta.has_field("email_verified_at"):
			bp.email_verified_at = now()
		if bp.meta.has_field("email_verified_method"):
			bp.email_verified_method = "admin_override"
		bp.flags.ignore_permissions = True
		bp.save(ignore_permissions=True)
		action = f"güncellendi: {bp.name}"
	else:
		buyer_name = (
			frappe.db.get_value("Admin Seller Profile", {"user": user_email}, "seller_name")
			or frappe.db.get_value("User", user_email, "full_name")
			or user_email
		)
		bp = frappe.new_doc("Buyer Profile")
		bp.user = user_email
		bp.buyer_name = buyer_name
		bp.status = "Active"
		bp.country = "Turkey"
		bp.email_verified = 1
		if bp.meta.has_field("email_verified_at"):
			bp.email_verified_at = now()
		if bp.meta.has_field("email_verified_method"):
			bp.email_verified_method = "admin_override"
		bp.flags.ignore_permissions = True
		bp.flags.ignore_mandatory = True
		bp.insert(ignore_permissions=True)
		action = f"oluşturuldu: {bp.name}"

	user_doc = frappe.get_doc("User", user_email)
	if not any(r.role == "Buyer" for r in user_doc.roles):
		user_doc.append("roles", {"role": "Buyer"})
		user_doc.flags.ignore_permissions = True
		user_doc.save(ignore_permissions=True)

	frappe.db.commit()
	print(f"✓ {user_email} — Buyer Profile {action}, email_verified=1")
	return {"user": user_email, "email_verified": 1}


@frappe.whitelist()
def approve_existing_demo_sellers():
	"""Mevcut demo satıcı User'ları için Seller Application onayla.

	Tüm seed'i yeniden çalıştırmadan, daha önce oluşturulmuş demo satıcı User +
	Admin Seller Profile kayıtlarına Seller Profile + KYB Verification eklemek
	için tek seferlik bakım fonksiyonu.

	Kullanım (bench):
	    bench --site <site> execute tradehub_core.seed_demo_data.approve_existing_demo_sellers

	Frappe v15'te bench execute, fonksiyondan dönen değeri JSON olarak terminale
	yazar; print'ler de logda görünür.
	"""
	if frappe.session.user != "Administrator" and not frappe.has_permission("Seller Application", "create"):
		frappe.throw(_("Bu işlem için Administrator yetkisi gereklidir."))
	frappe.flags.ignore_permissions = True

	approved = 0
	skipped = 0
	for idx, s in enumerate(SELLERS):
		if not frappe.db.exists("User", s["email"]):
			print(f"  ⚠️  User yok: {s['email']} — önce execute() çalıştırın")
			skipped += 1
			continue
		_ensure_seller_application(s)
		_fill_demo_kyb_documents(s)
		_set_demo_kyb_status(s, idx)
		_set_demo_kyc_verified(
			s["email"],
			account_type="Business",
			company_name=s["company_name"],
			tax_id=s["tax_id"],
			phone=s["phone"],
			address=f"{s['address_line1']}, {s['district']}/{s['city']}",
		)
		frappe.db.commit()
		approved += 1
		print(f"  ✓ {s['seller_name']} ({s['email']}) — KYB + KYC: Verified")

	print(f"\n  Toplam: {approved} onay, {skipped} atlandı")
	return {"approved": approved, "skipped": skipped}


@frappe.whitelist()
def cleanup(silent=False):
	"""
	Tüm demo veriyi sil.

	Kullanım (bench):
	    bench --site <site> execute tradehub_core.seed_demo_data.cleanup

	silent=True → execute() içinden çağrıldığında sadeleştirilmiş çıktı.
	"""
	if not frappe.session.user == "Administrator" and not frappe.has_permission(
		"Admin Seller Profile", "delete"
	):
		frappe.throw(_("Bu işlem için Administrator yetkisi gereklidir."))
	frappe.flags.ignore_permissions = True

	def _p(msg):
		if not silent:
			print(msg)

	if not silent:
		print("Demo veri temizleniyor...")

	# Sırayla sil (bağımlılık sırası: en bağımlıdan başla)

	# 1. Listings (variant_items child table otomatik silinir)
	demo_listings = frappe.get_all(
		"Listing",
		filters={"seller_profile": ["like", "DEMO-%"]},
		pluck="name",
	)
	for l in demo_listings:
		frappe.delete_doc("Listing", l, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_listings)} Listing silindi")
	frappe.db.commit()

	# 1b. Seller Reviews (Admin Seller Profile DEMO-% satıcılarına bağlı)
	demo_reviews = frappe.get_all(
		"Seller Review",
		filters={"seller": ["like", "DEMO-%"]},
		pluck="name",
	)
	for rv in demo_reviews:
		frappe.delete_doc("Seller Review", rv, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_reviews)} Seller Review silindi")
	frappe.db.commit()

	# 2. Seller Categories
	demo_seller_cats = frappe.get_all(
		"Seller Category",
		filters={"seller": ["like", "DEMO-%"]},
		pluck="name",
	)
	for sc in demo_seller_cats:
		frappe.delete_doc("Seller Category", sc, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_seller_cats)} Seller Category silindi")
	frappe.db.commit()

	# 3. Product Categories (yaprak → dal → kök sırasıyla)
	demo_cats = frappe.get_all(
		"Product Category",
		filters={"external_id": ["like", "DEMO-%"]},
		fields=["name", "lft", "rgt"],
		order_by="rgt - lft asc",
	)
	for c in demo_cats:
		if frappe.db.exists("Product Category", c["name"]):
			frappe.delete_doc("Product Category", c["name"], force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_cats)} Product Category silindi")
	frappe.db.commit()

	# 4. Demo Brands
	demo_brands = frappe.get_all(
		"Brand",
		filters={"brand_code": ["like", "DEMO-BRAND-%"]},
		pluck="name",
	)
	for b in demo_brands:
		frappe.delete_doc("Brand", b, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_brands)} Brand silindi")

	# 5. Admin Seller Profiles
	# İki filtre: hem DEMO-* seller_code'lu (zenginleştirilmiş) hem de SEL-* SA-onay
	# kaynaklı kayıtları kapsa. Aynı user için yanlışlıkla iki kayıt oluşmuşsa
	# ikisi de bu adımda silinir.
	demo_sellers_code = frappe.get_all(
		"Admin Seller Profile",
		filters={"seller_code": ["like", "DEMO-%"]},
		pluck="name",
	)
	demo_sellers_user = frappe.get_all(
		"Admin Seller Profile",
		filters={"user": ["like", "demo-seller-%@istoc.demo"]},
		pluck="name",
	)
	demo_sellers = list(set(demo_sellers_code + demo_sellers_user))
	for sp in demo_sellers:
		frappe.delete_doc("Admin Seller Profile", sp, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_sellers)} Admin Seller Profile silindi")

	# 5a. Seller Application (KYB + Seller Profile referans kayıtları için ilk silinir)
	demo_apps = frappe.get_all(
		"Seller Application",
		filters={"applicant_user": ["like", "demo-seller-%@istoc.demo"]},
		pluck="name",
	)
	for app in demo_apps:
		frappe.delete_doc("Seller Application", app, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_apps)} Seller Application silindi")

	# 5b. KYB Verification
	demo_kyb = frappe.get_all(
		"KYB Verification",
		filters={"user": ["like", "demo-seller-%@istoc.demo"]},
		pluck="name",
	)
	for k in demo_kyb:
		frappe.delete_doc("KYB Verification", k, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_kyb)} KYB Verification silindi")

	# 5c. Seller Profile (panelde "Satıcı Profilleri" listesi)
	demo_seller_profiles = frappe.get_all(
		"Seller Profile",
		filters={"user": ["like", "demo-seller-%@istoc.demo"]},
		pluck="name",
	)
	for sp in demo_seller_profiles:
		frappe.delete_doc("Seller Profile", sp, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_seller_profiles)} Seller Profile silindi")

	# 6. Buyer Profiles (demo alıcılar)
	demo_buyer_profiles = frappe.get_all(
		"Buyer Profile",
		filters={"user": ["like", "demo-buyer-%@istoc.demo"]},
		pluck="name",
	)
	for bp in demo_buyer_profiles:
		frappe.delete_doc("Buyer Profile", bp, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_buyer_profiles)} Buyer Profile silindi")

	# 6a. KYC Verification (satıcı + alıcı demo hesapları)
	kyc_sellers = frappe.get_all(
		"KYC Verification",
		filters={"user": ["like", "demo-seller-%@istoc.demo"]},
		pluck="name",
	)
	kyc_buyers = frappe.get_all(
		"KYC Verification",
		filters={"user": ["like", "demo-buyer-%@istoc.demo"]},
		pluck="name",
	)
	demo_kyc = list(set(kyc_sellers + kyc_buyers))
	for k in demo_kyc:
		frappe.delete_doc("KYC Verification", k, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_kyc)} KYC Verification silindi")

	# 6b. User Profile (satıcı + alıcı demo hesapları) — User silinmeden önce temizle
	up_sellers = frappe.get_all(
		"User Profile",
		filters={"user": ["like", "demo-seller-%@istoc.demo"]},
		pluck="name",
	)
	up_buyers = frappe.get_all(
		"User Profile",
		filters={"user": ["like", "demo-buyer-%@istoc.demo"]},
		pluck="name",
	)
	demo_user_profiles = list(set(up_sellers + up_buyers))
	for up in demo_user_profiles:
		frappe.delete_doc("User Profile", up, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_user_profiles)} User Profile silindi")
	frappe.db.commit()

	# 7. Demo Product Attributes (DEMO-ATTR-*)
	demo_attrs = frappe.get_all(
		"Product Attribute",
		filters={"attribute_code": ["like", "DEMO-ATTR-%"]},
		pluck="name",
	)
	for a in demo_attrs:
		frappe.delete_doc("Product Attribute", a, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_attrs)} Product Attribute silindi")

	# 8. Demo Shipping Methods (yalnız seed'in eklediği yöntemler)
	demo_method_names = [m["method_name"] for m in SHIPPING_METHODS]
	removed_methods = 0
	for name in demo_method_names:
		if frappe.db.exists("Shipping Method", name):
			frappe.delete_doc("Shipping Method", name, force=True, ignore_permissions=True)
			removed_methods += 1
	_p(f"  ✓ {removed_methods} Shipping Method silindi")

	# 9. Demo Users (satıcı + alıcı) — iki ayrı sorgu (v15 or_filters uyumu)
	sellers_u = frappe.get_all("User", filters={"email": ["like", "demo-seller-%@istoc.demo"]}, pluck="name")
	buyers_u = frappe.get_all("User", filters={"email": ["like", "demo-buyer-%@istoc.demo"]}, pluck="name")
	demo_users = list(set(sellers_u + buyers_u))
	for u in demo_users:
		frappe.delete_doc("User", u, force=True, ignore_permissions=True)
	_p(f"  ✓ {len(demo_users)} Demo User silindi")

	# 10. Demo Certification Types (seed'in kataloğundakiler). Listing/Seller Cert
	# child'ları zaten yukarıdaki Listing/Seller silindiğinde temizlendi.
	removed_certs = 0
	for cname in CERT_CATALOG.keys():
		if frappe.db.exists("Certification Type", cname):
			try:
				frappe.delete_doc("Certification Type", cname, force=True, ignore_permissions=True)
				removed_certs += 1
			except Exception:
				# Harici bir yerde hâlâ referans varsa atla
				pass
	_p(f"  ✓ {removed_certs} Certification Type silindi")

	frappe.db.commit()
	if not silent:
		print("\n✅ Tüm demo veri temizlendi!")
