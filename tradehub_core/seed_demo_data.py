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

import frappe
from frappe import _
import re
import random


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
    """Sektöre uygun Pexels CDN görsel URL'si döndürür.
    Her sektör için el seçimi 10-12 fotoğraf havuzundan deterministik seçim yapar."""
    images = SECTOR_IMAGES.get(sector_key, SECTOR_IMAGES["giyim"])
    idx = abs(hash(lock_id)) % len(images)
    photo_id = images[idx]
    return f"https://images.pexels.com/photos/{photo_id}/pexels-photo-{photo_id}.jpeg?auto=compress&cs=tinysrgb&w={w}&h={h}&fit=crop"


def _seller_logo(name, size=200):
    """Satıcı logosu için profesyonel harf tabanlı placeholder URL'si."""
    import urllib.parse
    encoded = urllib.parse.quote(name)
    return f"https://ui-avatars.com/api/?name={encoded}&size={size}&background=0D47A1&color=fff&bold=true&format=png"


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
#  SEKTÖR GÖRSEL HAVUZU (Pexels CDN)
#  Her sektör için el seçimi, yüksek kaliteli Pexels fotoğrafları.
#  Ürünler bu havuzdan deterministik olarak görsel seçer.
# ═══════════════════════════════════════════════════════════════

SECTOR_IMAGES = {
    "giyim": [
        8386655, 2249249, 10084285, 23105762, 1884584,
        6068952, 3812433, 19599223, 5490975, 5531746,
        6069551, 34850999,
    ],
    "ayakkabi": [
        2371935, 5117638, 11946032, 4010649, 17918933,
        233226, 2529148, 14834103, 2529147, 772286,
    ],
    "elektronik": [
        1420709, 10433477, 31450274, 9130508,
        2255355, 3394666, 844923, 5054358, 1037999,
    ],
    "hirdavat": [
        162553, 9754817, 19174967, 32777394, 8985454,
        909256, 15102481, 33868599, 8341833, 14637831,
    ],
    "gida": [
        7420982, 1161682, 2260825, 5966434, 5078584,
        531446, 264537, 27588072, 12124907, 15777497,
    ],
    "kozmetik": [
        29709957, 17545641, 3735619, 234220, 3018845,
        1115128, 8128684, 1722868, 35173950, 3190,
    ],
    "ev_tekstili": [
        9565729, 4112553, 15404863, 14465274, 4989084,
        3201758, 9899861, 7614416, 7546283, 19878558,
    ],
    "mutfak": [
        5825385, 10397050, 8583858, 1395967, 12908572,
        2074130, 5728162, 7958223, 4997810, 793765,
    ],
    "bijuteri": [
        1616096, 8184263, 32382386, 14058109, 1395306,
        230290, 1352783, 2685089, 6927690, 265906,
    ],
    "kirtasiye": [
        8015700, 7410461, 10834810, 7857523, 7464674,
        18725637, 7310197, 16955622, 8580739, 5957,
    ],
}


# ═══════════════════════════════════════════════════════════════
#  VARYANT AYARLARI (sektöre göre)
# ═══════════════════════════════════════════════════════════════

VARIANT_CONFIGS = {
    "giyim": [
        {"attr": "Renk", "values": ["Siyah", "Beyaz", "Lacivert", "Kırmızı", "Gri"],
         "price_mod": [0, -5, 0, 10, -3]},
        {"attr": "Beden", "values": ["S", "M", "L", "XL", "XXL"],
         "price_mod": [0, 0, 0, 5, 10]},
    ],
    "ayakkabi": [
        {"attr": "Renk", "values": ["Siyah", "Kahverengi", "Beyaz", "Tan"],
         "price_mod": [0, 0, -10, 5]},
        {"attr": "Numara", "values": ["39", "40", "41", "42", "43", "44"],
         "price_mod": [0, 0, 0, 0, 5, 10]},
    ],
    "elektronik": [
        {"attr": "Renk", "values": ["Siyah", "Beyaz", "Gri"],
         "price_mod": [0, 0, -5]},
        {"attr": "Kapasite", "values": ["16GB", "32GB", "64GB"],
         "price_mod": [0, 30, 70]},
    ],
    "hirdavat": [
        {"attr": "Boyut", "values": ["Küçük", "Orta", "Büyük", "Endüstriyel"],
         "price_mod": [0, 15, 35, 70]},
    ],
    "gida": [
        {"attr": "Gramaj", "values": ["250g", "500g", "1kg", "5kg"],
         "price_mod": [0, 12, 30, 120]},
    ],
    "kozmetik": [
        {"attr": "Hacim", "values": ["30ml", "50ml", "100ml", "200ml"],
         "price_mod": [0, 15, 40, 70]},
        {"attr": "Ton", "values": ["Açık", "Orta", "Koyu", "Doğal"],
         "price_mod": [0, 0, 0, 5]},
    ],
    "ev_tekstili": [
        {"attr": "Renk", "values": ["Beyaz", "Krem", "Gri", "Mavi", "Pembe"],
         "price_mod": [0, 0, 5, 10, 10]},
        {"attr": "Boyut", "values": ["Tek Kişilik", "Çift Kişilik", "King Size"],
         "price_mod": [0, 50, 100]},
    ],
    "mutfak": [
        {"attr": "Renk", "values": ["Kırmızı", "Siyah", "Beyaz", "Bakır"],
         "price_mod": [0, 0, -5, 15]},
        {"attr": "Boyut", "values": ["Küçük", "Orta", "Büyük"],
         "price_mod": [0, 25, 55]},
    ],
    "bijuteri": [
        {"attr": "Renk", "values": ["Altın", "Gümüş", "Rose Gold", "Siyah"],
         "price_mod": [15, 0, 20, -5]},
        {"attr": "Malzeme", "values": ["925 Ayar Gümüş", "Altın Kaplama", "Çelik"],
         "price_mod": [60, 35, 0]},
    ],
    "kirtasiye": [
        {"attr": "Renk", "values": ["Siyah", "Mavi", "Kırmızı", "Yeşil"],
         "price_mod": [0, 0, 0, 0]},
        {"attr": "Boyut", "values": ["A5", "A4", "A3"],
         "price_mod": [0, 8, 20]},
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
        "sector": "Tekstil & Giyim",
        "variant_type": "giyim",
        "price_range": (30, 500),
        "description": "1985'ten bu yana kaliteli tekstil ürünleri üreten Anadolu Tekstil, İstoç Ticaret Merkezi'nin en köklü firmalarından biridir. Geniş ürün yelpazesi ve rekabetçi fiyatlarla toptan satış hizmeti sunmaktadır.",
        "slogan": "Kaliteli Kumaş, Güvenilir Tedarik",
        "business_type": "Manufacturer",
        "founded_year": "1985", "staff_count": "120",
        "annual_revenue": "50M+ TL", "factory_size": "2500 m²",
        "certifications": "ISO 9001, OEKO-TEX Standard 100, CE",
        "phone": "+90 212 438 00 01", "website": "https://anadolutekstil.demo.istoc.com",
        "address_line1": "İstoç Ticaret Merkezi 1. Ada No:15",
        "district": "Bağcılar", "city": "İstanbul", "postal_code": "34030",
        "bank_name": "Garanti BBVA",
        "iban": "TR00 0001 0000 0000 0000 0001 01",
        "account_holder": "Anadolu Tekstil San. Tic. A.Ş.",
        "tax_id": "1234567001", "tax_office": "Bağcılar VD",
        "subscription_plan": "Enterprise", "commission_rate": 6.0,
        "main_markets": "Türkiye, Almanya, İngiltere, Hollanda",
    },
    {
        "code": "DEMO-002",
        "seller_name": "Boğaziçi Deri & Ayakkabı",
        "company_name": "Boğaziçi Deri Ürünleri San. Tic. A.Ş.",
        "email": "demo-seller-02@istoc.demo",
        "sector": "Ayakkabı & Deri",
        "variant_type": "ayakkabi",
        "price_range": (80, 1500),
        "description": "Boğaziçi Deri, 1992 yılından bu yana gerçek deri ayakkabı ve aksesuar üretimi yapmaktadır. El işçiliği ve kaliteli malzeme kullanımı ile sektörde öncü konumdadır.",
        "slogan": "Gerçek Deri, Gerçek Kalite",
        "business_type": "Manufacturer",
        "founded_year": "1992", "staff_count": "85",
        "annual_revenue": "35M+ TL", "factory_size": "1800 m²",
        "certifications": "ISO 9001, CE, Deri Sertifikası",
        "phone": "+90 212 438 00 02", "website": "https://bogazicideri.demo.istoc.com",
        "address_line1": "İstoç Ticaret Merkezi 3. Ada No:42",
        "district": "Bağcılar", "city": "İstanbul", "postal_code": "34030",
        "bank_name": "İş Bankası",
        "iban": "TR00 0001 0000 0000 0000 0002 02",
        "account_holder": "Boğaziçi Deri San. Tic. A.Ş.",
        "tax_id": "1234567002", "tax_office": "Bağcılar VD",
        "subscription_plan": "Pro", "commission_rate": 7.0,
        "main_markets": "Türkiye, Rusya, Irak, Azerbaycan",
    },
    {
        "code": "DEMO-003",
        "seller_name": "Marmara Elektronik",
        "company_name": "Marmara Elektronik Tic. Ltd. Şti.",
        "email": "demo-seller-03@istoc.demo",
        "sector": "Elektronik & Aksesuar",
        "variant_type": "elektronik",
        "price_range": (15, 500),
        "description": "Marmara Elektronik, telefon aksesuarları, bilgisayar çevre birimleri ve akıllı ev ürünlerinde geniş stok ve hızlı teslimat sunan toptancı firmadır.",
        "slogan": "Teknolojide Güvenilir Tedarik",
        "business_type": "Wholesaler",
        "founded_year": "2005", "staff_count": "45",
        "annual_revenue": "25M+ TL", "factory_size": "600 m²",
        "certifications": "CE, RoHS, FCC",
        "phone": "+90 212 438 00 03", "website": "https://marmaraelektronik.demo.istoc.com",
        "address_line1": "İstoç Ticaret Merkezi 5. Ada No:8",
        "district": "Bağcılar", "city": "İstanbul", "postal_code": "34030",
        "bank_name": "Yapı Kredi",
        "iban": "TR00 0001 0000 0000 0000 0003 03",
        "account_holder": "Marmara Elektronik Tic. Ltd. Şti.",
        "tax_id": "1234567003", "tax_office": "Bağcılar VD",
        "subscription_plan": "Pro", "commission_rate": 8.0,
        "main_markets": "Türkiye, Orta Doğu, Kuzey Afrika",
    },
    {
        "code": "DEMO-004",
        "seller_name": "İstanbul Hırdavat Merkezi",
        "company_name": "İstanbul Hırdavat ve Nalburiye Tic. A.Ş.",
        "email": "demo-seller-04@istoc.demo",
        "sector": "Hırdavat & Nalburiye",
        "variant_type": "hirdavat",
        "price_range": (5, 400),
        "description": "İstanbul Hırdavat Merkezi, el aletleri, elektrikli aletler, boya malzemeleri ve tesisat ürünlerinde geniş ürün yelpazesi sunan köklü bir toptancıdır.",
        "slogan": "Her İşin Doğru Aleti",
        "business_type": "Wholesaler",
        "founded_year": "1978", "staff_count": "60",
        "annual_revenue": "20M+ TL", "factory_size": "1200 m²",
        "certifications": "ISO 9001, TSE",
        "phone": "+90 212 438 00 04", "website": "https://istanbulhirdavat.demo.istoc.com",
        "address_line1": "İstoç Ticaret Merkezi 7. Ada No:23",
        "district": "Bağcılar", "city": "İstanbul", "postal_code": "34030",
        "bank_name": "Halkbank",
        "iban": "TR00 0001 0000 0000 0000 0004 04",
        "account_holder": "İstanbul Hırdavat Tic. A.Ş.",
        "tax_id": "1234567004", "tax_office": "Bağcılar VD",
        "subscription_plan": "Pro", "commission_rate": 7.5,
        "main_markets": "Türkiye, Irak, Libya, Türkmenistan",
    },
    {
        "code": "DEMO-005",
        "seller_name": "Karadeniz Gıda Toptancılık",
        "company_name": "Karadeniz Gıda Tarım Ürünleri Tic. A.Ş.",
        "email": "demo-seller-05@istoc.demo",
        "sector": "Gıda & İçecek",
        "variant_type": "gida",
        "price_range": (10, 250),
        "description": "Karadeniz Gıda, doğal ve organik gıda ürünlerinde Türkiye'nin önde gelen toptancılarından biridir. Fındık, çay, bal ve bakliyat başta olmak üzere geniş ürün gamı sunmaktadır.",
        "slogan": "Doğadan Sofranıza, Toptan Lezzet",
        "business_type": "Wholesaler",
        "founded_year": "1990", "staff_count": "70",
        "annual_revenue": "40M+ TL", "factory_size": "3000 m²",
        "certifications": "ISO 22000, HACCP, Organik Sertifika, Helal",
        "phone": "+90 212 438 00 05", "website": "https://karadenizgida.demo.istoc.com",
        "address_line1": "İstoç Ticaret Merkezi 9. Ada No:5",
        "district": "Bağcılar", "city": "İstanbul", "postal_code": "34030",
        "bank_name": "Ziraat Bankası",
        "iban": "TR00 0001 0000 0000 0000 0005 05",
        "account_holder": "Karadeniz Gıda Tic. A.Ş.",
        "tax_id": "1234567005", "tax_office": "Bağcılar VD",
        "subscription_plan": "Enterprise", "commission_rate": 5.0,
        "main_markets": "Türkiye, Almanya, Suudi Arabistan, BAE",
    },
    {
        "code": "DEMO-006",
        "seller_name": "Ege Kozmetik",
        "company_name": "Ege Kozmetik ve Kişisel Bakım San. A.Ş.",
        "email": "demo-seller-06@istoc.demo",
        "sector": "Kozmetik & Kişisel Bakım",
        "variant_type": "kozmetik",
        "price_range": (15, 400),
        "description": "Ege Kozmetik, makyaj, cilt bakım ve kişisel bakım ürünlerinde yerli üretim yapan, kalite kontrol standartlarına uygun çalışan bir üretici firmadır.",
        "slogan": "Doğal Güzellik, Profesyonel Bakım",
        "business_type": "Manufacturer",
        "founded_year": "2001", "staff_count": "95",
        "annual_revenue": "30M+ TL", "factory_size": "2000 m²",
        "certifications": "ISO 22716 (GMP), ISO 9001, Cruelty-Free",
        "phone": "+90 212 438 00 06", "website": "https://egekozmetik.demo.istoc.com",
        "address_line1": "İstoç Ticaret Merkezi 2. Ada No:31",
        "district": "Bağcılar", "city": "İstanbul", "postal_code": "34030",
        "bank_name": "Akbank",
        "iban": "TR00 0001 0000 0000 0000 0006 06",
        "account_holder": "Ege Kozmetik San. A.Ş.",
        "tax_id": "1234567006", "tax_office": "Bağcılar VD",
        "subscription_plan": "Pro", "commission_rate": 8.0,
        "main_markets": "Türkiye, Rusya, Kazakistan, Gürcistan",
    },
    {
        "code": "DEMO-007",
        "seller_name": "Trakya Ev Tekstili",
        "company_name": "Trakya Ev Tekstili San. Tic. A.Ş.",
        "email": "demo-seller-07@istoc.demo",
        "sector": "Ev Tekstili & Dekorasyon",
        "variant_type": "ev_tekstili",
        "price_range": (25, 800),
        "description": "Trakya Ev Tekstili, nevresim takımı, havlu, perde ve dekoratif ev ürünlerinde geniş koleksiyon sunan bir üretici firmadır. Yüksek iplik kalitesi ve modern tasarımlarla öne çıkmaktadır.",
        "slogan": "Evinize Değer Katan Tekstil",
        "business_type": "Manufacturer",
        "founded_year": "1995", "staff_count": "110",
        "annual_revenue": "45M+ TL", "factory_size": "3500 m²",
        "certifications": "ISO 9001, OEKO-TEX Standard 100, GOTS",
        "phone": "+90 212 438 00 07", "website": "https://trakyaev.demo.istoc.com",
        "address_line1": "İstoç Ticaret Merkezi 4. Ada No:18",
        "district": "Bağcılar", "city": "İstanbul", "postal_code": "34030",
        "bank_name": "Garanti BBVA",
        "iban": "TR00 0001 0000 0000 0000 0007 07",
        "account_holder": "Trakya Ev Tekstili San. Tic. A.Ş.",
        "tax_id": "1234567007", "tax_office": "Bağcılar VD",
        "subscription_plan": "Enterprise", "commission_rate": 6.5,
        "main_markets": "Türkiye, Almanya, Fransa, İngiltere",
    },
    {
        "code": "DEMO-008",
        "seller_name": "Akdeniz Mutfak & Züccaciye",
        "company_name": "Akdeniz Mutfak Gereçleri Tic. Ltd. Şti.",
        "email": "demo-seller-08@istoc.demo",
        "sector": "Mutfak & Züccaciye",
        "variant_type": "mutfak",
        "price_range": (20, 600),
        "description": "Akdeniz Mutfak, tencere, tava, porselen set ve küçük ev aletleri başta olmak üzere mutfak ve züccaciye ürünlerinde geniş stok sunan bir perakende ve toptan satıcıdır.",
        "slogan": "Mutfağınızın Güvenilir Adresi",
        "business_type": "Retailer",
        "founded_year": "2003", "staff_count": "40",
        "annual_revenue": "15M+ TL", "factory_size": "800 m²",
        "certifications": "ISO 9001, CE, FDA Uyumlu",
        "phone": "+90 212 438 00 08", "website": "https://akdenizmutfak.demo.istoc.com",
        "address_line1": "İstoç Ticaret Merkezi 6. Ada No:11",
        "district": "Bağcılar", "city": "İstanbul", "postal_code": "34030",
        "bank_name": "TEB",
        "iban": "TR00 0001 0000 0000 0000 0008 08",
        "account_holder": "Akdeniz Mutfak Tic. Ltd. Şti.",
        "tax_id": "1234567008", "tax_office": "Bağcılar VD",
        "subscription_plan": "Basic", "commission_rate": 9.0,
        "main_markets": "Türkiye, Irak, Suriye",
    },
    {
        "code": "DEMO-009",
        "seller_name": "Osmanlı Aksesuar",
        "company_name": "Osmanlı Bijuteri ve Aksesuar San. A.Ş.",
        "email": "demo-seller-09@istoc.demo",
        "sector": "Bijuteri & Aksesuar",
        "variant_type": "bijuteri",
        "price_range": (10, 500),
        "description": "Osmanlı Aksesuar, 925 ayar gümüş, altın kaplama ve çelik bijuteri ürünlerinde Osmanlı motiflerinden ilham alan özgün tasarımlar sunmaktadır.",
        "slogan": "Geleneği Taşıyan Zarafet",
        "business_type": "Manufacturer",
        "founded_year": "1998", "staff_count": "55",
        "annual_revenue": "20M+ TL", "factory_size": "900 m²",
        "certifications": "ISO 9001, Ayar Damgası, Nikel Testi",
        "phone": "+90 212 438 00 09", "website": "https://osmanliaksesuar.demo.istoc.com",
        "address_line1": "İstoç Ticaret Merkezi 8. Ada No:37",
        "district": "Bağcılar", "city": "İstanbul", "postal_code": "34030",
        "bank_name": "Vakıfbank",
        "iban": "TR00 0001 0000 0000 0000 0009 09",
        "account_holder": "Osmanlı Bijuteri San. A.Ş.",
        "tax_id": "1234567009", "tax_office": "Bağcılar VD",
        "subscription_plan": "Pro", "commission_rate": 7.0,
        "main_markets": "Türkiye, Suudi Arabistan, BAE, Kuveyt",
    },
    {
        "code": "DEMO-010",
        "seller_name": "Yıldız Ambalaj & Kırtasiye",
        "company_name": "Yıldız Ambalaj Kırtasiye Tic. A.Ş.",
        "email": "demo-seller-10@istoc.demo",
        "sector": "Ambalaj & Kırtasiye",
        "variant_type": "kirtasiye",
        "price_range": (5, 150),
        "description": "Yıldız Ambalaj, kırtasiye malzemeleri, ofis ürünleri ve ambalaj çözümlerinde geniş ürün gamı sunan bir toptan satıcıdır. Kurumsal müşterilere özel fiyatlandırma yapmaktadır.",
        "slogan": "Ofisten Depoya, Her Şey Burada",
        "business_type": "Wholesaler",
        "founded_year": "2008", "staff_count": "35",
        "annual_revenue": "12M+ TL", "factory_size": "500 m²",
        "certifications": "ISO 9001, FSC (Orman Sertifikası)",
        "phone": "+90 212 438 00 10", "website": "https://yildizambalaj.demo.istoc.com",
        "address_line1": "İstoç Ticaret Merkezi 10. Ada No:2",
        "district": "Bağcılar", "city": "İstanbul", "postal_code": "34030",
        "bank_name": "Denizbank",
        "iban": "TR00 0001 0000 0000 0000 0010 10",
        "account_holder": "Yıldız Ambalaj Kırtasiye Tic. A.Ş.",
        "tax_id": "1234567010", "tax_office": "Bağcılar VD",
        "subscription_plan": "Basic", "commission_rate": 9.0,
        "main_markets": "Türkiye",
    },
]


# ═══════════════════════════════════════════════════════════════
#  SEKTÖR → KATEGORİ → ÜRÜN AĞACI
#  Her sektör 1 satıcıya ait · 50 yaprak kategori · 100 ürün
#  Format: ("YaprakKategori", "Ürün Adı 1", "Ürün Adı 2")
# ═══════════════════════════════════════════════════════════════

SECTORS = [
    # ── 1. TEKSTİL & GİYİM (DEMO-001) ─────────────────────────
    {
        "name": "Tekstil & Giyim", "code": "TG", "seller": "DEMO-001",
        "groups": [
            ("Erkek Giyim", [
                ("T-Shirt", "Premium Pamuklu Basic T-Shirt", "Slim Fit V-Yaka T-Shirt"),
                ("Gömlek", "Oxford Düğmeli Yaka Gömlek", "Slim Fit Çizgili İş Gömleği"),
                ("Polo Yaka", "Pima Pamuk Polo Yaka Tişört", "Nakışlı Klasik Polo Tişört"),
                ("Pantolon", "Slim Fit Chino Pantolon", "Regular Fit Kumaş Pantolon"),
                ("Kot Pantolon", "Slim Fit Likralı Denim", "Straight Fit Yıkamalı Jean"),
                ("Şort", "Pamuklu Chino Şort", "Keten Yazlık Şort"),
                ("Ceket", "Blazer Slim Fit Ceket", "Keten Yazlık Ceket"),
                ("Mont", "Şişme Kaz Tüyü Mont", "Su Geçirmez Softshell Mont"),
                ("Yelek", "Kapitone Hafif Yelek", "Polar Fermuarlı Yelek"),
                ("Takım Elbise", "İtalyan Kesim Takım Elbise", "Slim Fit Yelekli Takım Elbise"),
            ]),
            ("Kadın Giyim", [
                ("Elbise", "Krep Kumaş Midi Elbise", "Çiçek Desenli Yazlık Elbise"),
                ("Bluz", "Saten Uzun Kollu Bluz", "Fırfırlı Şifon Bluz"),
                ("Kadın Gömlek", "Oversize Poplin Gömlek", "Bağlamalı Crop Gömlek"),
                ("Etek", "Pileli Midi Etek", "Deri Görünümlü Mini Etek"),
                ("Kadın Pantolon", "Yüksek Bel Palazzo Pantolon", "Tapered Kumaş Pantolon"),
                ("Kadın Ceket", "Crop Blazer Ceket", "Tüvit Chanel Ceket"),
                ("Trençkot", "Klasik Bej Trençkot", "Oversize Kuşaklı Trençkot"),
                ("Hırka", "Uzun Örgü Hırka", "Crop Triko Hırka"),
                ("Kazak", "Boğazlı Yün Kazak", "Oversize Triko Kazak"),
                ("Tunik", "Desenli Viskon Tunik", "Düz Pamuklu Tunik"),
            ]),
            ("Çocuk Giyim", [
                ("Bebek Giyim", "Organik Pamuk Bebek Tulumu", "Bebek Zıbın Seti 5'li"),
                ("Erkek Çocuk Giyim", "Baskılı Çocuk T-Shirt", "Çocuk Eşofman Takımı"),
                ("Kız Çocuk Giyim", "Tüllü Kız Çocuk Elbise", "Fırfırlı Çocuk Bluz"),
                ("Genç Erkek Giyim", "Genç Kapüşonlu Sweatshirt", "Genç Jogger Pantolon"),
                ("Genç Kız Giyim", "Genç Crop Top Takım", "Genç Yüksek Bel Jean"),
            ]),
            ("Spor Giyim", [
                ("Eşofman Takımı", "Slim Fit Eşofman Takımı", "Oversize Pamuklu Eşofman"),
                ("Spor Tayt", "Yüksek Bel Spor Tayt", "Dikişsiz Squat-Proof Tayt"),
                ("Forma", "Nefes Alan Spor Forma", "Reflektörlü Koşu Forması"),
                ("Spor Şort", "Çift Katmanlı Spor Şort", "Cepli Antrenman Şortu"),
                ("Yağmurluk", "Packable Hafif Yağmurluk", "Kapüşonlu Rüzgarlık"),
            ]),
            ("İç Giyim & Çorap", [
                ("Erkek İç Giyim", "Pamuklu Boxer 3'lü Paket", "Modal Atlet 2'li Set"),
                ("Kadın İç Giyim", "Dantelli Sütyen-Külot Takımı", "Pamuklu Bikini 5'li Paket"),
                ("Çorap", "Bambu Erkek Çorap 6'lı", "Spor Bilek Çorap 10'lu Paket"),
                ("Pijama Takımı", "Saten Pijama Takımı", "Pamuklu Uzun Kollu Pijama"),
                ("Bornoz", "Havlu Bornoz Premium", "Waffle Dokuma Spa Bornoz"),
            ]),
            ("Hamile Giyim", [
                ("Hamile Elbise", "Beli Ayarlanabilir Hamile Elbise", "Emzirme Özellikli Elbise"),
                ("Hamile Pantolon", "Hamile Likralı Pantolon", "Hamile Jean Pantolon"),
                ("Hamile Üst Giyim", "Hamile Tunik Bluz", "Hamile Sweatshirt"),
            ]),
            ("Büyük Beden", [
                ("Büyük Beden Erkek", "Büyük Beden Polo Yaka", "Büyük Beden Pantolon"),
                ("Büyük Beden Kadın", "Büyük Beden Viskon Elbise", "Büyük Beden Likralı Pantolon"),
                ("Büyük Beden Çocuk", "Büyük Beden Çocuk Eşofman", "Büyük Beden Çocuk T-Shirt"),
            ]),
            ("Kumaş & Aksesuar", [
                ("Kumaş Metre", "Pamuklu Poplin Kumaş (m)", "Viskon Krep Kumaş (m)"),
                ("Düğme", "Sedef Gömlek Düğmesi 100'lü", "Metal Ceket Düğmesi 50'li"),
                ("Fermuar", "YKK Metal Fermuar 20cm", "Gizli Etek Fermuarı 50cm"),
                ("İplik", "Polyester Dikiş İpliği 5000m", "Pamuk Nakış İpliği Seti"),
                ("Dantel", "Güpür Dantel Şerit (m)", "Tül Dantel Kumaş (m)"),
                ("Kurdele", "Saten Kurdele Seti 10 Renk", "Grogren Kurdele 25mm"),
                ("Elastik Bant", "Örme Lastik Bant 3cm", "Silikon Baskılı Lastik"),
                ("Astar", "Polyester Astar Kumaş (m)", "Saten Astar Kumaş (m)"),
                ("Tela", "Yapışkan Tela Nonwoven (m)", "Dokuma Tela Ağır (m)"),
            ]),
        ],
    },
    # ── 2. AYAKKABI & DERİ (DEMO-002) ─────────────────────────
    {
        "name": "Ayakkabı & Deri", "code": "AD", "seller": "DEMO-002",
        "groups": [
            ("Erkek Ayakkabı", [
                ("Klasik Ayakkabı", "Deri Bağcıklı Klasik Ayakkabı", "Rugan Loafer Ayakkabı"),
                ("Erkek Spor Ayakkabı", "Hafif Koşu Ayakkabısı", "Günlük Sneaker Ayakkabı"),
                ("Günlük Ayakkabı", "Deri Makosen Ayakkabı", "Süet Casual Ayakkabı"),
                ("Erkek Bot", "Deri Postal Bot", "Su Geçirmez Trekking Bot"),
                ("Erkek Sandalet", "Deri Çapraz Bantlı Sandalet", "Ortopedik Erkek Sandalet"),
                ("Erkek Terlik", "Deri Ev Terliği", "Anatomik Parmak Arası Terlik"),
                ("Loafer", "El Yapımı Deri Loafer", "Süet Püsküllü Loafer"),
                ("Oxford Ayakkabı", "Brogue Detaylı Oxford", "Cap Toe Oxford Ayakkabı"),
            ]),
            ("Kadın Ayakkabı", [
                ("Topuklu Ayakkabı", "Stiletto Sivri Burun Topuklu", "Kalın Topuklu Platform"),
                ("Düz Ayakkabı", "Deri Babet Ayakkabı", "Mary Jane Düz Ayakkabı"),
                ("Kadın Spor Ayakkabı", "Platform Sneaker Ayakkabı", "Hafif Yürüyüş Ayakkabısı"),
                ("Kadın Bot", "Deri Uzun Çizme", "Chelsea Bilekte Bot"),
                ("Kadın Sandalet", "Hasır Dolgu Topuk Sandalet", "İnce Bantlı Topuklu Sandalet"),
                ("Kadın Terlik", "Kürklü Ev Terliği", "Deri Tokalı Terlik"),
                ("Babet", "Fiyonklu Babet Ayakkabı", "Sivri Burun Düz Babet"),
                ("Platform Ayakkabı", "Kalın Taban Platform", "Espadril Platform Ayakkabı"),
            ]),
            ("Çocuk Ayakkabı", [
                ("Bebek Ayakkabı", "İlk Adım Bebek Ayakkabısı", "Yumuşak Taban Bebek Patiği"),
                ("Erkek Çocuk Ayakkabı", "Cırtlı Spor Ayakkabı", "Işıklı Çocuk Sneaker"),
                ("Kız Çocuk Ayakkabı", "Simli Babet Ayakkabı", "Çiçekli Sandalet"),
                ("Okul Ayakkabısı", "Siyah Deri Okul Ayakkabısı", "Lacivert Cırtlı Okul Ayakkabısı"),
            ]),
            ("Çanta", [
                ("Erkek Çanta", "Deri Postacı Çanta", "Kanvas Omuz Çantası"),
                ("Kadın El Çantası", "Hakiki Deri Tote Çanta", "Zincir Askılı Çapraz Çanta"),
                ("Sırt Çantası", "Laptop Bölmeli Sırt Çantası", "Mini Deri Sırt Çantası"),
                ("Evrak Çantası", "İtalyan Deri Evrak Çantası", "Slim Laptop Evrak Çantası"),
                ("Cüzdan", "RFID Korumalı Deri Cüzdan", "Fermuarlı Kadın Cüzdan"),
                ("Valiz", "Kabin Boy Sert Valiz", "Büyük Boy Tekerlekli Valiz"),
                ("Bel Çantası", "Deri Bel Çantası Unisex", "Spor Bel Çantası"),
                ("Laptop Çantası", "15.6 inç Deri Laptop Çantası", "MacBook Sleeve Kılıf"),
            ]),
            ("Deri Aksesuar", [
                ("Kemer", "Hakiki Deri Klasik Kemer", "Otomatik Tokalı Deri Kemer"),
                ("Kartlık", "RFID Engelli Deri Kartlık", "Slim Kredi Kartlık"),
                ("Pasaportluk", "Deri Pasaport Kılıfı", "Seyahat Organizatör Pasaportluk"),
                ("Anahtarlık", "Deri Anahtarlık Halkası", "Akıllı İzleyicili Anahtarlık"),
                ("Deri Bileklik", "El Örgüsü Deri Bileklik", "Çelik Tokalı Deri Bileklik"),
                ("Gözlük Kılıfı", "Sert Deri Gözlük Kutusu", "Yumuşak Süet Gözlük Kılıfı"),
            ]),
            ("Ayakkabı Bakım", [
                ("Ayakkabı Boyası", "Premium Deri Boyası Seti", "Süet Temizleme Spreyi"),
                ("Ayakkabı Fırçası", "At Kılı Parlatma Fırçası", "Krep Fırça Süet İçin"),
                ("Tabanlık", "Ortopedik Jel Tabanlık", "Koku Giderici Aktif Karbon Taban"),
                ("Ayakkabı Kalıbı", "Sedir Ağacı Ayakkabı Kalıbı", "Plastik Ayakkabı Kalıbı"),
            ]),
            ("Deri Hammadde", [
                ("Suni Deri", "PU Suni Deri Kumaş (m)", "Deri Görünümlü Kumaş (m)"),
                ("Gerçek Deri", "Dana Derisi Tabaka", "Keçi Derisi Nubuk Tabaka"),
                ("Nubuk Deri", "Nubuk Deri Tabaka 1.2mm", "Renkli Nubuk Deri Parçası"),
                ("Süet Deri", "Süet Deri Tabaka Premium", "İnce Süet Deri Kesim"),
                ("Deri Boya", "Deri Boyama Seti 12 Renk", "Deri Kenar Boyası"),
                ("Deri Yapıştırıcı", "Deri Özel Yapıştırıcı 500ml", "Kontakt Yapıştırıcı Tüp"),
            ]),
            ("Ayakkabı Aksesuarları", [
                ("Bağcık", "Yassı Spor Bağcık 120cm", "Yuvarlak Deri Bağcık 80cm"),
                ("Toka", "Metal Ayakkabı Tokası Altın", "Dekoratif Taşlı Toka"),
                ("Topuk Desteği", "Silikon Topuk Yastığı", "Jel Topuk Kaldırıcı"),
                ("Ayakkabı Süsü", "Dekoratif Ayakkabı Klipsi", "Kristal Taşlı Süs Tokası"),
                ("Jel Ped", "Metatarsal Jel Ped", "Ön Taban Jel Ped"),
                ("Ayakkabı Torbası", "Kadife Ayakkabı Torbası", "Seyahat Ayakkabı Organizatör"),
            ]),
        ],
    },
    # ── 3. ELEKTRONİK & AKSESUAR (DEMO-003) ──────────────────
    {
        "name": "Elektronik & Aksesuar", "code": "EA", "seller": "DEMO-003",
        "groups": [
            ("Telefon Aksesuar", [
                ("Telefon Kılıfı", "Şeffaf Silikon Telefon Kılıfı", "Deri Cüzdanlı Telefon Kılıfı"),
                ("Ekran Koruyucu", "9H Temperli Cam Ekran Koruyucu", "Mat Anti-Glare Ekran Filmi"),
                ("Şarj Kablosu", "USB-C Hızlı Şarj Kablosu 2m", "3'ü 1 Arada Şarj Kablosu"),
                ("Kablosuz Şarj", "15W Qi Kablosuz Şarj Standı", "3'ü 1 Arada Kablosuz Şarj İstasyonu"),
                ("Araç Tutucu", "Manyetik Araç İçi Telefon Tutucu", "Vantuzlu Araç Telefon Tutucu"),
                ("Selfie Çubuğu", "Bluetooth Uzaktan Kumandalı Selfie", "Tripodlu Selfie Çubuğu"),
                ("Gimbal", "3 Eksenli Akıllı Telefon Gimbal", "Mini Cep Gimbal Stabilizer"),
                ("Pop Socket", "Manyetik Pop Socket Tutucu", "Yüzük Tasarımlı Telefon Tutucu"),
            ]),
            ("Kulaklık & Ses", [
                ("Bluetooth Kulaklık", "ANC Bluetooth Over-Ear Kulaklık", "Neckband Spor Bluetooth Kulaklık"),
                ("Kablolu Kulaklık", "Hi-Fi Stüdyo Monitör Kulaklık", "Kulak İçi Kablolu Kulaklık"),
                ("TWS Kulaklık", "ANC TWS Kablosuz Kulaklık", "Spor TWS Su Geçirmez Kulaklık"),
                ("Bluetooth Hoparlör", "Taşınabilir Bluetooth Hoparlör 20W", "Mini Bluetooth Hoparlör IPX7"),
                ("Soundbar", "2.1 Kanal Bluetooth Soundbar", "Kompakt TV Soundbar"),
                ("Mikrofon", "USB Kondenser Stüdyo Mikrofon", "Yaka Mikrofonu Kablosuz"),
            ]),
            ("Bilgisayar Aksesuar", [
                ("Mouse", "Ergonomik Kablosuz Mouse", "RGB Oyuncu Mouse 16000 DPI"),
                ("Klavye", "Mekanik RGB Oyuncu Klavye", "Slim Bluetooth Klavye"),
                ("Mouse Pad", "XXL Oyuncu Mouse Pad RGB", "Deri Mouse Pad Bilek Destekli"),
                ("USB Hub", "USB-C 7in1 Hub Dock", "USB 3.0 4 Port Hub"),
                ("Webcam", "Full HD 1080p Webcam", "4K Auto-Focus Webcam"),
                ("Monitor Standı", "Alüminyum Monitor Yükseltici", "Çekmeceli Ahşap Monitor Standı"),
                ("Laptop Standı", "Ayarlanabilir Alüminyum Laptop Standı", "Taşınabilir Katlanır Laptop Standı"),
                ("Soğutucu", "5 Fanlı Laptop Soğutucu", "Slim Alüminyum Laptop Soğutucu"),
            ]),
            ("Güç & Şarj", [
                ("Powerbank", "20000mAh PD Hızlı Şarj Powerbank", "10000mAh Slim Powerbank"),
                ("Şarj Adaptörü", "65W GaN USB-C Şarj Adaptörü", "20W PD iPhone Şarj Adaptörü"),
                ("Çoklu Priz", "6'lı Akıllı Priz USB Çıkışlı", "Uzatma Kablosu 5m Anahtarlı"),
                ("UPS", "650VA Line Interactive UPS", "1000VA Online UPS"),
                ("Güneş Enerjili Şarj", "Katlanır Solar Panel 21W", "Solar Powerbank 30000mAh"),
                ("Araç Şarjı", "Dual USB-C Araç Şarj Cihazı", "FM Transmitter Araç Şarjı"),
            ]),
            ("Akıllı Ev", [
                ("Akıllı Priz", "WiFi Akıllı Priz Enerji İzleme", "Zigbee Akıllı Priz 4'lü"),
                ("Akıllı Lamba", "RGB WiFi Akıllı LED Ampul", "Akıllı LED Şerit 5m"),
                ("Güvenlik Kamerası", "360° PTZ WiFi Güvenlik Kamerası", "Dış Mekan IP66 Kamera"),
                ("Akıllı Kilit", "Parmak İzi Akıllı Kapı Kilidi", "Şifreli Bluetooth Kilit"),
                ("Sensör", "Hareket Sensörü Zigbee", "Kapı/Pencere Sensörü WiFi"),
                ("Akıllı Kumanda", "IR Akıllı Uzaktan Kumanda", "WiFi Universal Kumanda"),
            ]),
            ("Oyun Aksesuarları", [
                ("Gamepad", "Bluetooth Kablosuz Gamepad", "PS5 DualSense Uyumlu Gamepad"),
                ("Oyun Kulaklığı", "7.1 Surround Oyuncu Kulaklığı", "RGB Oyuncu Kulaklık Mikrafonlu"),
                ("Oyun Mouse", "Ultra Hafif Oyuncu Mouse 60g", "MMO Oyuncu Mouse 12 Tuş"),
                ("Oyun Klavye", "60% Mekanik Mini Oyun Klavye", "TKL RGB Mekanik Klavye"),
                ("Joystick", "Uçuş Simülatör Joystick", "Arcade Joystick Retro"),
                ("VR Gözlük", "Bağımsız VR Gözlük 128GB", "Telefon Uyumlu VR Gözlük"),
            ]),
            ("Kablolar & Adaptörler", [
                ("HDMI Kablo", "HDMI 2.1 8K Kablo 2m", "HDMI to VGA Dönüştürücü Kablo"),
                ("USB-C Kablo", "USB-C to USB-C 100W PD Kablo 2m", "USB-C to Lightning Kablo MFi"),
                ("Ethernet Kablo", "Cat7 Ethernet Kablo 10m", "Cat6 Patch Kablo 5m"),
                ("Ses Kablosu", "3.5mm AUX Kablo Örgülü 1.5m", "Optik Toslink Ses Kablosu 2m"),
                ("Dönüştürücü", "USB-C to HDMI 4K Adaptör", "DisplayPort to HDMI Dönüştürücü"),
            ]),
            ("Depolama", [
                ("USB Bellek", "Metal USB 3.0 Flash Bellek 64GB", "USB-C Flash Bellek 128GB"),
                ("Harici Disk", "Taşınabilir SSD 1TB USB-C", "Harici HDD 2TB USB 3.0"),
                ("SD Kart", "MicroSD Kart 256GB A2 V30", "SD Kart 128GB UHS-II"),
                ("SSD Kutusu", "NVMe M.2 SSD Kutusu USB-C", "2.5 inç SATA SSD Kutusu"),
                ("NAS Cihazı", "2 Bay NAS Sunucu", "4 Bay NAS Raid Destekli"),
            ]),
        ],
    },
    # ── 4. HIRDAVAT & NALBURİYE (DEMO-004) ───────────────────
    {
        "name": "Hırdavat & Nalburiye", "code": "HN", "seller": "DEMO-004",
        "groups": [
            ("El Aletleri", [
                ("Çekiç", "Çelik Saplı Çekiç 500g", "Lastik Çekiç Çift Başlı"),
                ("Tornavida Seti", "32 Parça Tornavida Seti", "İzole Tornavida Seti 7'li"),
                ("Pense", "Kombine Pense 200mm", "Karga Burun Pense Seti"),
                ("Anahtar Takımı", "Allen Anahtar Seti 9 Parça", "Kombine Anahtar Takımı 12'li"),
                ("Testere", "El Testeresi 500mm", "Demir Testeresi Mini"),
                ("Keski", "Ahşap Oyma Keski Seti 6'lı", "Düz Keski 20mm"),
                ("Maket Bıçağı", "Otomatik Geri Çekmeli Maket Bıçağı", "Profesyonel Maket Bıçağı Seti"),
                ("Matkap Ucu", "HSS Matkap Ucu Seti 19 Parça", "Beton Matkap Ucu Seti 8'li"),
            ]),
            ("Elektrikli Aletler", [
                ("Matkap", "Akülü Darbeli Matkap 20V", "Sütunlu Matkap Tezgahı"),
                ("Taşlama", "Avuç İçi Taşlama 125mm", "Düz Taşlama Makinesi"),
                ("Dekupaj", "Elektrikli Dekupaj Testere", "Akülü Dekupaj Testere 18V"),
                ("Vidalama", "Akülü Vidalama 12V Kompakt", "Darbeli Akülü Vidalama 20V"),
                ("Hava Tabancası", "Sıcak Hava Tabancası 2000W", "Boya Tabancası HVLP"),
                ("Lehim Havyası", "Ayarlanabilir Lehim İstasyonu 60W", "Lehim Tabancası Seti"),
            ]),
            ("Boya & Vernik", [
                ("İç Cephe Boya", "Silinebilir İç Cephe Boyası 15L", "Anti-Bakteriyel İç Cephe Boyası 3.5L"),
                ("Dış Cephe Boya", "Elastik Dış Cephe Boyası 15L", "Silikon Esaslı Dış Cephe 7.5L"),
                ("Ahşap Vernik", "Su Bazlı Ahşap Vernik 2.5L", "Yacht Vernik Parlak 0.75L"),
                ("Sprey Boya", "Akrilik Sprey Boya 400ml", "Metalik Efekt Sprey Boya"),
                ("Boya Rulosu", "Kadife Rulo 25cm Seti", "Sünger Rulo Desen Seti"),
                ("Boya Fırçası", "Kestirme Fırça Seti 5'li", "Badana Fırçası 15cm"),
            ]),
            ("Hırdavat Malzeme", [
                ("Vida", "Paslanmaz Sac Vida Seti 500'lü", "Havşa Başlı Vida Karışık Set"),
                ("Çivi", "Beton Çivisi Seti 200'lü", "Süsleme Çivisi Pirinç 100'lü"),
                ("Dübel", "Plastik Dübel Seti 300'lü", "Kimyasal Dübel M12 Seti"),
                ("Menteşe", "Paslanmaz Menteşe 4 inç 2'li", "Soft-Close Menteşe 4'lü"),
                ("Kilit", "Silindir Kapı Kilidi Seti", "Asma Kilit Pirinç 50mm"),
                ("Kapı Kolu", "Rozetli Kapı Kolu Seti", "Paslanmaz Çekme Kapı Kolu"),
                ("Sürgü", "Alüminyum Kapı Sürgüsü", "Emniyet Sürgüsü Çelik"),
                ("Mandal", "Rulolu Kapı Mandalı", "Top Mandal Seti 10'lu"),
            ]),
            ("Elektrik Malzeme", [
                ("Kablo", "NYM Tesisat Kablosu 3x2.5 100m", "TTR Kablo 2x1.5 50m"),
                ("Priz", "Sıva Üstü İkili Priz Topraklı", "Gömme Priz USB Çıkışlı"),
                ("Anahtar", "Komütatör Anahtar Beyaz", "Dimmer Anahtar LED Uyumlu"),
                ("Sigorta", "Otomatik Sigorta B16 Seti", "Kaçak Akım Rölesi 2P 40A"),
                ("LED Ampul", "LED Ampul E27 12W 6'lı", "LED Filament Ampul Vintage"),
                ("Spot Lamba", "GU10 LED Spot 7W 10'lu", "Sıva Altı LED Panel 18W"),
            ]),
            ("Su Tesisatı", [
                ("Musluk", "Paslanmaz Mutfak Musluğu", "Fotoselli Lavabo Musluğu"),
                ("Batarya", "Termostatik Banyo Bataryası", "Tek Kollu Lavabo Bataryası"),
                ("Duş Başlığı", "Yağmur Tepe Duş Seti 25cm", "Filtreli Duş Başlığı"),
                ("Boru", "PPR Boru 20mm 4m", "Fleksi Hortum 1/2 inç 50cm"),
                ("Conta", "O-Ring Conta Seti 225 Parça", "Kauçuk Conta 1/2 inç 50'li"),
                ("Sifon", "Lavabo Sifonu Krom", "Mutfak Evye Sifonu Çift Gözlü"),
            ]),
            ("Bahçe Aletleri", [
                ("Bahçe Makası", "Profesyonel Budama Makası", "Çit Biçme Makası 60cm"),
                ("Çapa", "Küçük El Çapası Ergonomik", "Çift Taraflı Çapa"),
                ("Kürek", "Bahçe Küreği Fiberglas Saplı", "Kar Küreği Alüminyum"),
                ("Hortum", "Flexibel Bahçe Hortumu 30m", "Yassı Hortum Makaralı 15m"),
                ("Fıskiye", "8 Fonksiyonlu Bahçe Fıskiyesi", "Sprinkler Döner Fıskiye"),
            ]),
            ("İş Güvenliği", [
                ("Baret", "CE Onaylı İş Bareti", "Ventilli Güvenlik Bareti"),
                ("İş Eldiveni", "Nitril Kaplı İş Eldiveni 12'li", "Isıya Dayanıklı Kaynakçı Eldiveni"),
                ("Koruyucu Gözlük", "Anti-Fog Koruyucu Gözlük", "UV Koruma İş Gözlüğü"),
                ("Reflektif Yelek", "Hi-Vis Reflektif İş Yeleği", "Cepli İş Güvenliği Yeleği"),
                ("İş Ayakkabısı", "S3 Çelik Burunlu İş Ayakkabısı", "Kompozit Burun İş Botu"),
            ]),
        ],
    },
    # ── 5. GIDA & İÇECEK (DEMO-005) ──────────────────────────
    {
        "name": "Gıda & İçecek", "code": "GI", "seller": "DEMO-005",
        "groups": [
            ("Bakliyat", [
                ("Kuru Fasulye", "Yerli Dermason Fasulye 1kg", "İspir Şeker Fasulye 1kg"),
                ("Nohut", "Koçbaşı Nohut 1kg", "Sarı Nohut Organik 1kg"),
                ("Mercimek", "Kırmızı Mercimek 1kg", "Yeşil Mercimek 1kg"),
                ("Bulgur", "Pilavlık Bulgur 1kg", "Köftelik İnce Bulgur 1kg"),
                ("Pirinç", "Baldo Pirinç 1kg", "Osmancık Pirinç 5kg"),
                ("Kuskus", "Tam Buğday Kuskus 500g", "İnce Kuskus 1kg"),
            ]),
            ("Baharat", [
                ("Kırmızı Biber", "Toz Kırmızı Biber 500g", "Pul Kırmızı Biber Acılı 250g"),
                ("Karabiber", "Tane Karabiber 250g", "Öğütülmüş Karabiber 100g"),
                ("Kimyon", "Tane Kimyon 250g", "Öğütülmüş Kimyon 100g"),
                ("Kekik", "Dağ Kekiği 500g", "Limon Kekiği 100g"),
                ("Zerdeçal", "Toz Zerdeçal 250g", "Organik Zerdeçal Kök 200g"),
                ("Tarçın", "Toz Tarçın Seylan 100g", "Çubuk Tarçın 50g"),
                ("Sumak", "Ekşi Sumak 500g", "İnce Öğütülmüş Sumak 250g"),
                ("Pul Biber", "Urfa Pul Biber 500g", "Antep Pul Biber Tatlı 250g"),
            ]),
            ("Kuru Meyve & Kuruyemiş", [
                ("Fındık", "Giresun Tombul Fındık İç 1kg", "Kavrulmuş Fındık 500g"),
                ("Ceviz", "Yerli Ceviz İç 1kg", "Kelebek Ceviz İç 500g"),
                ("Badem", "Çiğ Badem İç 500g", "Kavrulmuş Tuzlu Badem 250g"),
                ("Kuru Kayısı", "Malatya Kuru Kayısı 1kg", "Organik Kuru Kayısı 500g"),
                ("Kuru İncir", "Aydın Kuru İncir 1kg", "Naturel Kuru İncir 500g"),
                ("Kuru Üzüm", "Çekirdeksiz Kuru Üzüm 1kg", "Sarı Kuru Üzüm 500g"),
                ("Antep Fıstığı", "İç Antep Fıstığı 500g", "Kavrulmuş Tuzlu Fıstık 250g"),
                ("Leblebi", "Sarı Leblebi 1kg", "Çikolatalı Leblebi 500g"),
            ]),
            ("Yağlar", [
                ("Zeytinyağı", "Erken Hasat Natürel Sızma Zeytinyağı 1L", "Riviera Zeytinyağı 5L"),
                ("Ayçiçek Yağı", "Rafine Ayçiçek Yağı 5L", "Soğuk Sıkım Ayçiçek Yağı 1L"),
                ("Tereyağı", "Trabzon Yaylası Tereyağı 500g", "Pastörize Tereyağı 1kg"),
                ("Hindistan Cevizi Yağı", "Soğuk Sıkım Hindistan Cevizi Yağı 500ml", "Organik Virgin Coconut Oil 250ml"),
                ("Susam Yağı", "Soğuk Sıkım Susam Yağı 500ml", "Kavurma Susam Yağı 250ml"),
            ]),
            ("Konserve & Turşu", [
                ("Domates Konserve", "Domates Püresi 830g", "Domates Kurusu Yağlı 300g"),
                ("Zeytin", "Gemlik Siyah Zeytin 1kg", "Yeşil Kırma Zeytin 1kg"),
                ("Turşu", "Kornişon Turşu 720ml", "Karışık Turşu 1.5L"),
                ("Salça", "Biber Salçası 1.5kg", "Domates Salçası 700g"),
                ("Reçel", "Vişne Reçeli 380g", "Kayısı Reçeli Ev Yapımı 450g"),
            ]),
            ("Bal & Pekmez", [
                ("Çiçek Balı", "Yayla Çiçek Balı 850g", "Süzme Çiçek Balı 450g"),
                ("Kestane Balı", "Organik Kestane Balı 480g", "Macahel Kestane Balı 250g"),
                ("Üzüm Pekmezi", "Geleneksel Üzüm Pekmezi 800g", "Organik Üzüm Pekmezi 450g"),
                ("Dut Pekmezi", "Doğal Dut Pekmezi 800g", "Karadut Pekmezi 450g"),
            ]),
            ("İçecek", [
                ("Çay", "Rize Çayı 1kg Dökme", "Earl Grey Çay 500g"),
                ("Türk Kahvesi", "Orta Kavrulmuş Türk Kahvesi 500g", "Dibek Kahvesi 250g"),
                ("Bitki Çayı", "Ihlamur Çayı 100g", "Ada Çayı Dağ 200g"),
                ("Şerbet", "Nar Şerbeti Konsantre 700ml", "Limon Şerbeti Geleneksel 1L"),
                ("Limonata", "Ev Yapımı Limonata Konsantre 1L", "Naneli Limonata 750ml"),
                ("Ayran Tozu", "Geleneksel Ayran Tozu 500g", "Yoğurt Kültürlü Ayran Tozu 1kg"),
            ]),
            ("Un & Tahıl", [
                ("Buğday Unu", "Ekmeklik Buğday Unu 5kg", "Tam Buğday Unu 2kg"),
                ("Mısır Unu", "İnce Mısır Unu 1kg", "Mısır Nişastası 500g"),
                ("Yulaf", "Yulaf Ezmesi 1kg", "Steel Cut Yulaf 500g"),
                ("Çavdar", "Çavdar Unu 1kg", "Çavdar Ekmek Karışımı 500g"),
            ]),
            ("Şekerleme", [
                ("Lokum", "Antep Fıstıklı Lokum 500g", "Gül Yapraklı Lokum 350g"),
                ("Helva", "Tahin Helvası Kakaolu 500g", "Pişmaniye 250g"),
                ("Pestil", "Kayısı Pestili 300g", "Dut Pestili 200g"),
                ("Çikolata", "Bitter Çikolata %70 Kakao 100g", "Fındıklı Sütlü Çikolata 200g"),
            ]),
        ],
    },
    # ── 6. KOZMETİK & KİŞİSEL BAKIM (DEMO-006) ─────────────
    {
        "name": "Kozmetik & Kişisel Bakım", "code": "KB", "seller": "DEMO-006",
        "groups": [
            ("Makyaj", [
                ("Ruj", "Mat Likit Ruj Uzun Süren", "Nemlendirici Krem Ruj"),
                ("Fondöten", "Full Coverage Likit Fondöten", "BB Krem SPF30 Doğal"),
                ("Maskara", "Volume Lash Maskara Siyah", "Waterproof Uzatıcı Maskara"),
                ("Far Paleti", "18'li Nötr Tonlar Far Paleti", "Simli Pigment Far Paleti 12'li"),
                ("Allık", "Baked Allık Şeftali Tonu", "Likit Allık Doğal Pembe"),
                ("Kapatıcı", "Full Cover Kapatıcı Stick", "Göz Altı Aydınlatıcı Kapatıcı"),
                ("Dudak Kalemi", "Su Geçirmez Dudak Kalemi", "Retractable Lip Liner Nude"),
                ("Eyeliner", "Keçe Uçlu Eyeliner Siyah", "Jel Eyeliner Fırça ile"),
            ]),
            ("Cilt Bakım", [
                ("Nemlendirici", "Hyaluronik Asit Nemlendirici 50ml", "Aloe Vera Jel Nemlendirici 200ml"),
                ("Güneş Kremi", "SPF50+ Yüz Güneş Kremi 50ml", "Vücut Güneş Losyonu SPF30 200ml"),
                ("Serum", "Vitamin C Aydınlatıcı Serum 30ml", "Niacinamide %10 Serum 30ml"),
                ("Tonik", "AHA/BHA Peeling Tonik 200ml", "Gül Suyu Canlandırıcı Tonik 250ml"),
                ("Temizleyici", "Micellar Temizleme Suyu 400ml", "Köpük Yüz Temizleyici 150ml"),
                ("Yüz Maskesi", "Kil Maskesi Arındırıcı 100ml", "Sheet Mask Hyaluronik 5'li"),
                ("Göz Kremi", "Anti-Age Göz Çevresi Kremi 15ml", "Koyu Halka Aydınlatıcı Göz Jeli"),
                ("Peeling", "Enzim Peeling Jel 100ml", "AHA %30 Profesyonel Peeling"),
            ]),
            ("Saç Bakım", [
                ("Şampuan", "Keratin Onarıcı Şampuan 500ml", "Yağlı Saçlar İçin Şampuan 400ml"),
                ("Saç Kremi", "Argan Yağlı Saç Kremi 300ml", "Protein Yapılandırıcı Krem 250ml"),
                ("Saç Maskesi", "Derin Onarım Saç Maskesi 500ml", "Keratin Botox Saç Maskesi 300ml"),
                ("Saç Yağı", "Argan Yağı Saf 100ml", "Hint Yağı Saç Bakım 150ml"),
                ("Saç Spreyi", "Isı Koruyucu Sprey 200ml", "Parlak Finish Saç Spreyi 300ml"),
                ("Saç Boyası", "Amonyaksız Saç Boyası Seti", "Organik Kına Saç Boyası 100g"),
            ]),
            ("Vücut Bakım", [
                ("Duş Jeli", "Aromatik Duş Jeli 500ml", "Nemlendirici Duş Yağı 300ml"),
                ("Vücut Losyonu", "Shea Butter Vücut Losyonu 400ml", "Bronzlaştırıcı Vücut Losyonu 250ml"),
                ("El Kremi", "İntensif El Kremi 75ml", "Balmumu El Kremi Onarıcı 50ml"),
                ("Ayak Bakım", "Çatlak Giderici Ayak Kremi 100ml", "Ayak Peeling Çorabı"),
                ("Tüy Dökücü", "Hassas Cilt Tüy Dökücü Krem 150ml", "Wax Ağda Bandı 20'li"),
                ("Vücut Spreyi", "Parfümlü Vücut Spreyi 200ml", "Terleme Önleyici Vücut Spreyi"),
            ]),
            ("Parfüm & Deodorant", [
                ("Kadın Parfüm", "Floral EDP Kadın 100ml", "Orientale EDT Kadın 50ml"),
                ("Erkek Parfüm", "Woody EDP Erkek 100ml", "Fresh Sport EDT Erkek 75ml"),
                ("Roll-on", "Sensitive Roll-on Deodorant 50ml", "Anti-Stain Roll-on 48h 50ml"),
                ("Sprey Deodorant", "Fresh Cotton Deo Sprey 150ml", "Sport Active Deo Sprey 200ml"),
                ("Kolonya", "Limon Kolonyası 400ml", "Lavanta Kolonyası 200ml"),
            ]),
            ("Tırnak Bakım", [
                ("Oje", "Gel Efektli Oje 12ml", "Vegan Oje Seti 6'lı"),
                ("Tırnak Bakım Seti", "Tırnak Güçlendirici Serum 10ml", "Tırnak Bakım Kiti 5 Parça"),
                ("Protez Tırnak", "Press-On Tırnak Seti 24'lü", "Akrilik Tırnak Başlangıç Kiti"),
                ("Tırnak Süsleme", "Tırnak Sticker Seti 12 Sayfa", "Nail Art Fırça Seti 15'li"),
            ]),
            ("Ağız Bakım", [
                ("Diş Macunu", "Beyazlatıcı Diş Macunu 100ml", "Hassas Dişler İçin Diş Macunu 75ml"),
                ("Diş Fırçası", "Bambu Diş Fırçası 4'lü", "Elektrikli Diş Fırçası Sonic"),
                ("Ağız Çalkalama", "Antiseptik Ağız Gargarası 500ml", "Alkalsız Ağız Bakım Suyu 250ml"),
                ("Diş İpi", "Mint Aromalı Diş İpi 50m", "Ara Yüz Fırçası Seti 8'li"),
            ]),
            ("Erkek Bakım", [
                ("Tıraş Köpüğü", "Hassas Cilt Tıraş Köpüğü 200ml", "Tıraş Jeli Aloe Vera 150ml"),
                ("Tıraş Bıçağı", "5 Bıçaklı Tıraş Bıçağı 4'lü Yedek", "Safety Razor Paslanmaz"),
                ("After Shave", "Yatıştırıcı After Shave Balm 100ml", "Mentollü After Shave Losyon 150ml"),
                ("Sakal Yağı", "Organik Sakal Bakım Yağı 30ml", "Sakal Yumuşatıcı Yağ 50ml"),
                ("Sakal Fırçası", "Domuz Kılı Sakal Fırçası", "Sakal Tarak ve Fırça Seti"),
            ]),
            ("Makyaj Aletleri", [
                ("Makyaj Fırça Seti", "Profesyonel 12'li Fırça Seti", "Vegan Makyaj Fırça Seti 8'li"),
                ("Makyaj Süngeri", "Beauty Blender Sünger 3'lü", "Silikon Makyaj Aplikatörü"),
                ("Makyaj Aynası", "LED Işıklı Büyüteçli Ayna", "Katlanır Seyahat Aynası"),
                ("Makyaj Çantası", "Profesyonel Makyaj Bavulu", "Şeffaf PVC Makyaj Çantası"),
            ]),
        ],
    },
    # ── 7. EV TEKSTİLİ & DEKORASYON (DEMO-007) ──────────────
    {
        "name": "Ev Tekstili & Dekorasyon", "code": "ET", "seller": "DEMO-007",
        "groups": [
            ("Yatak Odası", [
                ("Nevresim Takımı", "Ranforce Çift Kişilik Nevresim Takımı", "Saten Jakarlı Nevresim Takımı"),
                ("Pike", "Pamuklu Yaz Pikesi Çift Kişilik", "Jakarlı Pike Takımı"),
                ("Yorgan", "Mikrofiber Silikon Yorgan", "Kaz Tüyü Yorgan Premium"),
                ("Yastık", "Visco Yastık Ortopedik", "Kaz Tüyü Yastık 50x70"),
                ("Yatak Örtüsü", "Kadife Yatak Örtüsü Takımı", "Kapitone Yatak Örtüsü"),
                ("Çarşaf", "Lastikli Çarşaf Pamuk Saten", "Jersey Fitted Çarşaf"),
                ("Yastık Kılıfı", "Saten Yastık Kılıfı 2'li", "Nakışlı Dekoratif Yastık Kılıfı"),
                ("Alez", "Su Geçirmez Fitted Alez", "Pamuklu Quilted Alez"),
            ]),
            ("Banyo", [
                ("Havlu", "Pamuklu Havlu Seti 6 Parça", "Bambu Karışım Havlu 70x140"),
                ("Banyo Paspası", "Pamuklu Banyo Paspası Seti", "Kaymaz Taban Memory Foam Paspas"),
                ("Bornoz", "Velur Bornoz Kadın", "Şal Yaka Pamuklu Bornoz Erkek"),
                ("Duş Perdesi", "Polyester Duş Perdesi 180x200", "Çift Katmanlı Duş Perdesi"),
                ("Banyo Seti", "5 Parça Seramik Banyo Seti", "Bambu Banyo Aksesuar Seti"),
                ("Havlu Askılık", "Paslanmaz Havlu Askılık", "Yapışkanlı Havlu Kancası 4'lü"),
            ]),
            ("Mutfak Tekstil", [
                ("Masa Örtüsü", "Leke Tutmaz Masa Örtüsü 160x220", "Keten Masa Örtüsü Düz Renk"),
                ("Runner", "Pamuklu Runner 40x150", "Hasır Runner Doğal 35x120"),
                ("Peçete", "Keten Peçete 4'lü Set", "Pamuklu Peçete Desenli 6'lı"),
                ("Mutfak Havlusu", "Kadife Mutfak Havlusu 3'lü", "Waffle Mutfak Bezi 5'li"),
                ("Önlük", "Keten Mutfak Önlüğü", "Su Geçirmez Aşçı Önlüğü"),
            ]),
            ("Salon", [
                ("Perde", "Fon Perde Blackout 2'li", "Kadife Fon Perde Premium"),
                ("Tül Perde", "Dantel Tül Perde Kırık Beyaz", "Sade Şifon Tül Perde"),
                ("Koltuk Örtüsü", "Elastik Koltuk Kılıfı 3+2+1", "Pamuklu Koltuk Şalı"),
                ("Kırlent", "Kadife Kırlent Kılıfı 45x45 2'li", "Boho Tarzı Kırlent 4'lü Set"),
                ("Battaniye", "Tv Battaniyesi Polar", "Pamuklu Çift Kişilik Battaniye"),
                ("Dekoratif Yastık", "Keten Dekoratif Yastık", "Payetli Dönüşüm Yastık"),
                ("Halı", "Modern Geometrik Halı 160x230", "Vintage Desen Halı 200x290"),
                ("Kilim", "El Dokuma Kilim 120x180", "Pamuklu Şönil Kilim 80x150"),
            ]),
            ("Çocuk Odası", [
                ("Bebek Nevresim", "Organik Bebek Nevresim Takımı", "Desenli Bebek Uyku Seti"),
                ("Çocuk Perde", "Baskılı Çocuk Perde Blackout", "Rengarenk Çocuk Tül Perde"),
                ("Çocuk Halı", "Oyun Desenli Çocuk Halısı", "Hayvan Figürlü Çocuk Halısı"),
                ("Oyun Matı", "EVA Puzzle Oyun Matı 9 Parça", "Pamuklu Katlanır Oyun Matı"),
                ("Çocuk Battaniye", "Kabartmalı Çocuk Battaniyesi", "Pelüş Çocuk Battaniyesi"),
            ]),
            ("Bahçe & Balkon", [
                ("Balkon Perdesi", "Dış Mekan Güneşlik Perde", "Plastik Balkon Perdesi"),
                ("Dış Mekan Yastık", "Su Geçirmez Dış Mekan Minder", "Bahçe Sandalye Minderi"),
                ("Bahçe Örtüsü", "Masa Bahçe Mobilya Örtüsü", "Şemsiye Koruma Kılıfı"),
                ("Hamak", "Pamuklu Çift Kişilik Hamak", "Paraşüt Kumaş Kamp Hamağı"),
            ]),
            ("Dekorasyon", [
                ("Mum", "Kokulu Soya Mumu 3'lü Set", "Dekoratif Sütun Mum 2'li"),
                ("Vazo", "Cam Vazo El Yapımı 30cm", "Seramik Vazo Modern 25cm"),
                ("Çerçeve", "Ahşap Fotoğraf Çerçevesi 5'li Set", "Altın Metal Çerçeve 20x30"),
                ("Duvar Saati", "Minimalist Metal Duvar Saati 40cm", "Vintage Ahşap Duvar Saati"),
                ("Dekoratif Ayna", "Yuvarlak Hasır Çerçeveli Ayna", "Modern Geometrik Duvar Aynası"),
                ("Biblo", "Seramik Dekoratif Biblo Seti", "Reçine Hayvan Figürü"),
                ("Kitap Desteği", "Metal Kitap Desteği 2'li", "Mermer Efektli Bookend"),
                ("Dekoratif Tabak", "Duvar Tabağı Osmanlı Motifli", "Seramik Servis Tabağı Dekoratif"),
            ]),
            ("Saklama & Düzen", [
                ("Sepet", "Hasır Saklama Sepeti 3'lü", "Pamuklu Örgü Sepet L"),
                ("Saklama Kutusu", "Kapaklı Kumaş Saklama Kutusu", "Şeffaf Plastik Organizer 4'lü"),
                ("Organizer", "Çekmece İçi Organizer 6'lı", "Takı Organizatör Ahşap"),
                ("Hurç", "Vakumlu Hurç Seti 5 Parça", "Non-Woven Hurç 3'lü"),
                ("Askı", "Kadife Elbise Askısı 20'li", "Ahşap Takım Elbise Askısı 5'li"),
                ("Çamaşır Sepeti", "Bambu Çamaşır Sepeti Kapaklı", "Katlanır Kumaş Çamaşır Sepeti"),
            ]),
        ],
    },
    # ── 8. MUTFAK & ZÜCCACİYE (DEMO-008) ────────────────────
    {
        "name": "Mutfak & Züccaciye", "code": "MZ", "seller": "DEMO-008",
        "groups": [
            ("Pişirme", [
                ("Tencere", "Granit Derin Tencere 24cm", "Paslanmaz Çelik Tencere 20cm"),
                ("Tava", "Döküm Granit Tava 28cm", "Paslanmaz Çelik Omlet Tava 22cm"),
                ("Düdüklü Tencere", "Çelik Düdüklü Tencere 7L", "Alüminyum Düdüklü Tencere 5L"),
                ("Sahan", "Bakır Sahan 16cm", "Granit Yumurta Sahanı 14cm"),
                ("Güveç", "Toprak Güveç Kapağı ile 3L", "Seramik Güveç Kabı 2L"),
                ("Wok Tava", "Karbon Çelik Wok 30cm", "Granit Wok Tava Cam Kapaklı"),
                ("Izgara Tava", "Döküm Izgara Tava 26cm", "İki Taraflı Tost Tava"),
                ("Krep Tava", "Yapışmaz Krep Tava 26cm", "Döküm Pankek Tava"),
            ]),
            ("Kesim & Hazırlık", [
                ("Bıçak Seti", "7 Parça Şef Bıçak Seti", "Seramik Bıçak Seti 4'lü"),
                ("Kesme Tahtası", "Bambu Kesme Tahtası 3'lü", "Mermer Kesme Tahtası 30x40"),
                ("Rende", "4 Taraflı Paslanmaz Rende", "Microplane Zester Rende"),
                ("Doğrayıcı", "Çok Fonksiyonlu Doğrayıcı", "Soğan Doğrayıcı Manuel"),
                ("Havanlık", "Granit Havanlık Büyük", "Mermer Havanlık Seti"),
                ("Süzgeç", "Paslanmaz Çelik Süzgeç Seti 3'lü", "Silikon Katlanır Süzgeç"),
            ]),
            ("Servis", [
                ("Tabak Takımı", "24 Parça Porselen Yemek Takımı", "Bone China Servis Seti 12 Kişilik"),
                ("Bardak Seti", "Kristal Su Bardağı 6'lı", "Renkli Meşrubat Bardağı 6'lı"),
                ("Çay Takımı", "Porselen Çay Seti 12 Parça", "Cam Çay Bardağı Tabağı 6'lı"),
                ("Kahve Fincanı", "Espresso Fincanı 6'lı Seti", "Türk Kahvesi Fincan Seti Porselen"),
                ("Servis Tabağı", "Oval Servis Tabağı 35cm", "Bölmeli Kahvaltı Tabağı"),
                ("Kase", "Porselen Çorba Kasesi 6'lı", "Salata Kasesi Cam Büyük"),
                ("Sürahi", "Cam Sürahi Filtreli 1.5L", "Porselen Limonata Sürahisi"),
                ("Meyvelik", "Paslanmaz Çelik Meyvelik 3 Katlı", "Ahşap Meyvelik"),
            ]),
            ("Saklama", [
                ("Kavanoz Seti", "Cam Kavanoz Seti 5'li", "Seramik Kapaklı Kavanoz 3'lü"),
                ("Saklama Kabı", "Cam Saklama Kabı 10'lu Set", "Vakumlu Saklama Kabı 5'li"),
                ("Ekmeklik", "Bambu Ekmek Kutusu", "Metal Ekmek Kutusu Retro"),
                ("Yağdanlık", "Cam Yağdanlık Damlatmaz", "Seramik Yağ Sirke Seti"),
                ("Baharat Seti", "Döner Baharat Standı 12'li", "Cam Baharat Kavanoz 6'lı"),
            ]),
            ("Küçük Ev Aletleri", [
                ("Blender", "Profesyonel Smoothie Blender 1000W", "El Blender Seti 4 Başlıklı"),
                ("Çay Makinesi", "Otomatik Çay Makinesi Çelik", "Çift Demlikli Çay Makinesi"),
                ("Tost Makinesi", "Izgara ve Tost Makinesi 1800W", "Waffle Tost Makinesi 4'lü"),
                ("Mikser", "Stand Mikser 1200W Paslanmaz", "El Mikseri 5 Kademeli"),
                ("Kahve Makinesi", "Filtre Kahve Makinesi 12 Bardak", "Espresso Makinesi Pod Uyumlu"),
                ("Fritöz", "Airfryer Sıcak Hava Fritözü 5.5L", "Derin Yağ Fritözü 3L"),
            ]),
            ("Fırın & Pasta", [
                ("Kek Kalıbı", "Silikon Kek Kalıbı 26cm", "Kelepçeli Kek Kalıbı 28cm"),
                ("Borcam", "Oval Borcam Kapağı ile 2L", "Kare Borcam Set 3'lü"),
                ("Muffin Kalıbı", "12'li Muffin Kalıbı Silikon", "Mini Cupcake Kalıbı 24'lü"),
                ("Pasta Sıkma", "Profesyonel Pasta Sıkma Seti 26 Uç", "Silikon Pasta Sıkma Torbası"),
                ("Oklava", "Ahşap Oklava Düz 40cm", "Silikon Oklava Ayarlanabilir"),
            ]),
            ("Çatal Bıçak", [
                ("Çatal Bıçak Seti", "72 Parça Çatal Bıçak Takımı", "24 Parça Mat Çatal Bıçak Seti"),
                ("Tatlı Kaşığı", "Paslanmaz Tatlı Kaşığı 12'li", "Altın Renk Çay Kaşığı 6'lı"),
                ("Servis Seti", "Salata Servis Seti Ahşap", "Pasta Servis Bıçağı Spatula"),
                ("Steak Bıçağı", "Steak Bıçağı 6'lı Set", "Japon Çelik Steak Bıçağı"),
                ("Açacak", "Şarap Açacağı Tirbuşon", "Çok Fonksiyonlu Konserve Açacağı"),
            ]),
            ("Plastik & Tek Kullanımlık", [
                ("Plastik Kap", "Mikrodalga Uyumlu Kap 50'li", "Meal Prep Kabı 3 Bölme 30'lu"),
                ("Streç Film", "Gıda Streç Film 300m", "Alüminyum Folyo 100m"),
                ("Buzdolabı Poşeti", "Kilitli Poşet Seti 100'lü", "Vakum Poşet Rulo 28cm"),
                ("Pişirme Kağıdı", "Fırın Pişirme Kağıdı 8m", "Silikon Pişirme Matı 2'li"),
            ]),
            ("Bar Aksesuarları", [
                ("Şarap Açacağı", "Elektrikli Şarap Açacağı", "Garson Tirbuşon Profesyonel"),
                ("Buz Kovası", "Paslanmaz Çelik Buz Kovası", "Akrilik Buz Kovası LED"),
                ("Kokteyl Shaker", "Profesyonel Shaker Seti 11 Parça", "Boston Shaker Çelik"),
            ]),
        ],
    },
    # ── 9. BİJUTERİ & AKSESUAR (DEMO-009) ───────────────────
    {
        "name": "Bijuteri & Aksesuar", "code": "BA", "seller": "DEMO-009",
        "groups": [
            ("Yüzük", [
                ("Altın Kaplama Yüzük", "22K Altın Kaplama Osmanlı Yüzük", "İnce Band Altın Kaplama Yüzük"),
                ("Gümüş Yüzük", "925 Ayar Gümüş Taşlı Yüzük", "Oksitlenmiş Gümüş Erkek Yüzük"),
                ("Taşlı Yüzük", "Zirkon Taşlı Solitaire Yüzük", "Renkli Taş Cluster Yüzük"),
                ("Alyans", "Klasik Çift Alyans Seti", "Taşlı Nişan Yüzüğü"),
                ("Eklem Yüzüğü", "Midi Ring Set 5'li", "Minimalist Eklem Yüzük Seti"),
            ]),
            ("Kolye", [
                ("Altın Kaplama Kolye", "Osmanlı Tuğralı Altın Kaplama Kolye", "İnce Zincir Altın Kolye"),
                ("İnci Kolye", "Doğal İnci Kolye 45cm", "Barok İnci Choker Kolye"),
                ("Taşlı Kolye", "Zirkon Damla Kolye Seti", "Safir Renkli Taşlı Kolye"),
                ("Zincir Kolye", "Kalın Zincir Kolye Çelik", "Figaro Zincir Kolye 60cm"),
                ("Uçlu Kolye", "Melek Kanadı Uçlu Kolye", "Hayat Ağacı Uçlu Kolye"),
            ]),
            ("Bileklik", [
                ("Kelepçe Bileklik", "Çelik Kelepçe Bileklik Altın", "Taşlı Kelepçe Bileklik"),
                ("Boncuk Bileklik", "Doğal Taş Boncuk Bileklik", "Nazar Boncuklu Bileklik"),
                ("Deri Bileklik", "Erkek Deri Bileklik Manyetik", "Örgü Deri Bileklik"),
                ("Zincir Bileklik", "Mariner Zincir Bileklik Çelik", "Tennis Bileklik Zirkon"),
                ("Charm Bileklik", "Charm Bileklik 5 Uçlu", "Pandora Tarzı Bileklik"),
            ]),
            ("Küpe", [
                ("Halka Küpe", "Altın Kaplama Halka Küpe 3cm", "Gümüş Büyük Halka Küpe"),
                ("Sallantılı Küpe", "Kristal Sallantılı Küpe", "Boho Tarzı Uzun Küpe"),
                ("Taşlı Küpe", "Pırlanta Montür Zirkon Küpe", "Renkli Taşlı Küpe Seti"),
                ("İnci Küpe", "Klasik İnci Küpe 8mm", "Çift Taraflı İnci Küpe"),
                ("Çivi Küpe", "Minimal Çivi Küpe Altın", "Taşlı Çivi Küpe Seti 3'lü"),
            ]),
            ("Saat", [
                ("Kadın Kol Saati", "Çelik Kordon Kadın Kol Saati", "Deri Kordon Zarif Kadın Saati"),
                ("Erkek Kol Saati", "Kronograf Erkek Kol Saati", "Minimalist Erkek Saati Mesh Kordon"),
                ("Akıllı Saat Kordon", "Silikon Akıllı Saat Kordon 42mm", "Metal Akıllı Saat Kordon 44mm"),
                ("Saat Kutusu", "6 Bölmeli Deri Saat Kutusu", "Otomatik Saat Sarıcı"),
                ("Cep Saati", "Vintage Cep Saati Zincirli", "Osmanlı Motifli Cep Saati"),
            ]),
            ("Gözlük", [
                ("Kadın Güneş Gözlüğü", "Cat Eye Güneş Gözlüğü UV400", "Oversized Kadın Güneş Gözlüğü"),
                ("Erkek Güneş Gözlüğü", "Aviator Polarize Güneş Gözlüğü", "Spor Güneş Gözlüğü Erkek"),
                ("Okuma Gözlüğü", "Katlanır Okuma Gözlüğü", "Mavi Işık Filtreli Okuma Gözlüğü"),
                ("Gözlük Çerçevesi", "Retro Yuvarlak Gözlük Çerçevesi", "Titanyum Gözlük Çerçevesi"),
                ("Gözlük Kılıfı", "Sert Kabuk Gözlük Kutusu", "Deri Manyetik Gözlük Kılıfı"),
            ]),
            ("Saç Aksesuarları", [
                ("Toka", "İnci Detaylı Saç Tokası", "Metal Geometrik Saç Tokası"),
                ("Taç", "Kristal Gelin Tacı", "Çiçekli Saç Tacı Boho"),
                ("Saç Bandı", "Kadife Saç Bandı", "Düğümlü Saç Bandı Seti 3'lü"),
                ("Tırnak Tokası", "Büyük Tırnak Tokası Asetatlı", "Mini Tırnak Tokası 6'lı"),
                ("Saç İpi", "İpek Saç Lastikleri 10'lu", "Spiral Saç Lastiği 5'li"),
                ("Saç Tokası", "Bobby Pin Dekoratif 20'li", "Firkete Minimalist Seti"),
            ]),
            ("Şal & Fular", [
                ("İpek Şal", "El Boyama İpek Şal 90x90", "Dijital Baskı İpek Şal"),
                ("Pamuk Fular", "Pamuklu Yazlık Fular", "Organik Pamuk Fular"),
                ("Kaşmir Atkı", "Saf Kaşmir Atkı 200cm", "Kaşmir Karışım Atkı"),
                ("Bandana", "Pamuklu Bandana 5'li Set", "İpek Bandana Retro Desen"),
                ("Boyunluk", "Polar Boyunluk Unisex", "Merino Yün Boyunluk"),
            ]),
            ("Diğer Aksesuarlar", [
                ("Broş", "Kristal Çiçek Broş", "Vintage Osmanlı Broş"),
                ("Kol Düğmesi", "Paslanmaz Çelik Kol Düğmesi", "Gümüş Kol Düğmesi Kutulu"),
                ("Kravat İğnesi", "Altın Kaplama Kravat İğnesi", "Minimalist Çelik Kravat İğnesi"),
                ("Şapka", "Fedora Şapka Keçe", "Panama Şapka Hasır"),
                ("Eldiven", "Deri Eldiven Kürklü İç", "Dokunmatik Uyumlu Yün Eldiven"),
                ("Şemsiye", "Otomatik Katlanır Şemsiye", "Baston Şemsiye Rüzgar Dayanımlı"),
                ("Anahtarlık", "Deri Anahtarlık İsim Baskılı", "Metal Araba Anahtarlığı"),
                ("Rozet", "Emaye Pin Rozet 5'li", "Özel Tasarım Logo Rozet"),
                ("Yaka İğnesi", "Çiçek Yaka İğnesi", "Taşlı Yaka İğnesi Altın"),
            ]),
        ],
    },
    # ── 10. AMBALAJ & KIRTASİYE (DEMO-010) ──────────────────
    {
        "name": "Ambalaj & Kırtasiye", "code": "AK", "seller": "DEMO-010",
        "groups": [
            ("Defter & Not", [
                ("Spiralli Defter", "A4 Spiralli Kareli Defter 120 Yaprak", "A5 Spiralli Çizgili Defter 80 Yaprak"),
                ("Ciltli Defter", "Deri Kapaklı Ciltli Defter A5", "Hardcover Bullet Journal Noktalı"),
                ("Not Defteri", "Yapışkanlı Not Kağıdı 12'li", "Kraft Not Defteri Cep Boy"),
                ("Yapışkanlı Not", "Post-it Küp Not 400 Yaprak", "Neon Renkli Yapışkanlı Not 5'li"),
                ("Planlayıcı", "Haftalık Planlayıcı 52 Sayfa", "Günlük Planlayıcı Tarihsiz"),
                ("Ajanda", "2025 Günlük Ajanda A5", "Haftalık Ajanda Deri Kapaklı"),
            ]),
            ("Kalem & Yazı", [
                ("Tükenmez Kalem", "Metal Tükenmez Kalem Kutulu", "Tükenmez Kalem 50'li Paket"),
                ("Kurşun Kalem", "HB Kurşun Kalem 12'li", "Mekanik Kurşun Kalem 0.7mm"),
                ("Fosforlu Kalem", "Fosforlu Kalem Seti 6 Renk", "Pastel Fosforlu Kalem 4'lü"),
                ("Keçeli Kalem", "İnce Uç Keçeli Kalem 12'li", "Brush Pen Kaligrafi Seti 6'lı"),
                ("Dolma Kalem", "Iridium Uçlu Dolma Kalem", "Piston Dolma Kalem Hediye Seti"),
                ("Silgi", "Dust-Free Silgi 3'lü", "Elektrikli Silgi Kalem Pilli"),
            ]),
            ("Dosya & Klasör", [
                ("Telli Dosya", "Telli Dosya 50'li Paket", "Plastik Telli Dosya 25'li"),
                ("Sunum Dosyası", "40 Yaprak Sunum Dosyası", "Sıkıştırmalı Dosya A4"),
                ("Klasör", "Geniş Halkalı Klasör A4", "Körüklü Organizer Dosya 12 Bölme"),
                ("Evrak Rafı", "3 Katlı Metal Evrak Rafı", "Ahşap Evrak Düzenleyici"),
                ("Zarf", "A4 Kraft Zarf 100'lü", "Kapaklı Dosya Zarfı 50'li"),
            ]),
            ("Ofis Malzemeleri", [
                ("Zımba", "Metal Zımba Makinesi No:24", "Cep Tipi Mini Zımba"),
                ("Delgeç", "2 Delikli Metal Delgeç", "4 Delikli Ayarlanabilir Delgeç"),
                ("Bant", "Seloteyp 6'lı Paket", "Çift Taraflı Bant 18mm 10m"),
                ("Makas", "Ergonomik Ofis Makası 21cm", "Titanyum Kaplamalı Makas"),
                ("Hesap Makinesi", "12 Haneli Masaüstü Hesap Makinesi", "Bilimsel Hesap Makinesi 240 Fonksiyon"),
            ]),
            ("Ambalaj Malzemeleri", [
                ("Karton Kutu", "E-Ticaret Kargo Kutusu 25x20x10 50'li", "Karton Kutu Büyük 40x30x20 25'li"),
                ("Kraft Poşet", "Kraft Kağıt Poşet 100'lü", "Büküm Saplı Kraft Çanta 50'li"),
                ("Balonlu Naylon", "Balonlu Ambalaj 50cm x 10m", "Balonlu Zarf 26x36 25'li"),
                ("Koli Streç Film", "Streç Film 17 mikron 500m", "Mini Streç Film El Tipi"),
                ("Koli Bandı", "Koli Bandı Şeffaf 6'lı", "Baskılı Koli Bandı Özel Tasarım"),
                ("Etiket", "A4 Lazer Etiket 100 Sayfa", "Termal Barkod Etiketi 1000'li"),
                ("Kurşun Mühür", "Güvenlik Mühürü 100'lü", "Plastik Mühür Etiketli 200'lü"),
                ("Ambalaj Kağıdı", "Kraft Ambalaj Kağıdı Rulo 70cm", "Hediye Ambalaj Kağıdı 10'lu"),
            ]),
            ("Parti & Etkinlik", [
                ("Balon", "Metalik Balon 50'li Paket", "Folyo Harf Balon Seti"),
                ("Konfeti", "Renkli Kağıt Konfeti 500g", "Metalik Konfeti Top Atıcı 6'lı"),
                ("Parti Tabağı", "Karton Parti Tabağı 25'li", "Temalı Doğum Günü Tabağı 8'li"),
                ("Parti Bardağı", "Karton Bardak 50'li", "Temalı Parti Bardağı 8'li"),
                ("Masa Süsü", "Masa Konfeti Yıldız 100g", "Masa Örtüsü Parti 137x274"),
            ]),
            ("Hediye & Sunum", [
                ("Hediye Kutusu", "Mıknatıslı Hediye Kutusu 3'lü", "Pencereli Hediye Kutusu 10'lu"),
                ("Hediye Çantası", "Lüks Hediye Çantası 10'lu", "Mini Hediye Çantası 20'li"),
                ("Kurdale", "Saten Kurdale 25mm 100m", "Organze Kurdale 10mm 50m"),
                ("Hediye Kağıdı", "Premium Hediye Ambalaj Kağıdı 5'li", "Çocuk Temalı Hediye Kağıdı 10'lu"),
                ("Fiyonk", "Hazır Fiyonk Yapıştırmalı 50'li", "Pull Bow Fiyonk 14cm 10'lu"),
            ]),
            ("Okul Malzemeleri", [
                ("Okul Çantası", "Ortopedik Okul Çantası Set", "Tekerlekli Okul Çantası"),
                ("Kalem Kutusu", "Çift Fermuarlı Kalem Kutusu", "Silikon Kalem Kutusu Figürlü"),
                ("Resim Defteri", "A3 Resim Defteri 20 Yaprak", "Sketch Book Spiralli A4"),
                ("Boya Kalemi", "Kuru Boya 24 Renk", "Pastel Boya Seti 36 Renk"),
                ("Cetvel", "Şeffaf Cetvel 30cm", "Cetvel Seti Açıölçer İletki"),
            ]),
            ("Baskı & Reklam", [
                ("Kartvizit", "350gr Kuşe Kartvizit 1000 Adet", "Özel Kesim Kartvizit 500 Adet"),
                ("Afiş", "A3 Kuşe Afiş Baskı 50 Adet", "B1 Poster Baskı 10 Adet"),
                ("Broşür", "A4 Üç Katlı Broşür 500 Adet", "A5 Broşür 1000 Adet"),
                ("Roll-up", "80x200 Roll-up Banner", "100x200 X-Banner"),
                ("Sticker", "Kesimli Sticker 500 Adet", "Vinyl Sticker Dış Mekan 100 Adet"),
            ]),
        ],
    },
]


# ═══════════════════════════════════════════════════════════════
#  OLUŞTURMA FONKSİYONLARI
# ═══════════════════════════════════════════════════════════════

def _ensure_user(email, first_name):
    """Demo kullanıcı oluştur veya mevcut olanı döndür."""
    if frappe.db.exists("User", email):
        return email
    user = frappe.new_doc("User")
    user.email = email
    user.first_name = first_name
    user.enabled = 1
    user.user_type = "Website User"
    user.send_welcome_email = 0
    user.flags.ignore_permissions = True
    user.flags.no_welcome_mail = True
    user.insert(ignore_permissions=True)
    return email


def _ensure_seller(s):
    """Admin Seller Profile oluştur veya mevcut olanı döndür."""
    if frappe.db.exists("Admin Seller Profile", s["code"]):
        return s["code"]

    _ensure_user(s["email"], s["seller_name"])

    doc = frappe.new_doc("Admin Seller Profile")
    doc.seller_code = s["code"]
    doc.seller_name = s["seller_name"]
    doc.user = s["email"]
    doc.status = "Active"
    doc.seller_type = "Corporate"
    doc.logo = _seller_logo(s["seller_name"], 200)
    doc.banner_image = _img(s["variant_type"], 1200, 400, lock_id=f'{s["code"]}-banner')
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
    for cert in s["certifications"].split(", "):
        doc.append("certifications", {
            "certification_type": cert.strip(),
        })
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
    doc.is_verified = 1
    doc.verification_type = "Verified Multispecialty Supplier"
    doc.health_score = round(random.uniform(75, 98), 1)
    doc.score_grade = random.choice(["A", "A", "A", "B"])
    doc.commission_rate = s["commission_rate"]
    doc.subscription_plan = s["subscription_plan"]
    doc.response_time = random.choice(["< 1 saat", "< 2 saat", "< 4 saat", "< 24 saat"])
    doc.response_rate = round(random.uniform(85, 99), 1)
    doc.on_time_delivery = round(random.uniform(90, 99), 1)

    # Gallery images
    for i in range(1, random.randint(4, 6)):
        doc.append("gallery_images", {
            "image": _img(s["variant_type"], 600, 400, lock_id=f'{s["code"]}-gallery-{i}'),
            "caption": f"Fabrika/Mağaza Görüntüsü {i}",
        })

    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return s["code"]


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
    """Seller Category oluştur. Varsa mevcut olanı döndür (name'i integer)."""
    existing = frappe.db.get_value(
        "Seller Category",
        {"seller": seller_code, "category": category_id},
        "name",
    )
    if existing:
        return existing

    doc = frappe.new_doc("Seller Category")
    doc.seller = seller_code
    doc.category = category_id
    doc.category_name = category_name
    doc.status = "Active"
    doc.is_enabled = 1
    doc.image = _img(sector_key, 400, 400, lock_id=f"sc-{seller_code}-{_slug(category_name)}")
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return doc.name


def _create_listing(seller, sector, seller_cat_name, product_cat_id, cat_name,
                     title, product_idx, variant_type, price_range):
    """Tek bir Listing (ürün ilanı) ve varyantlarını oluştur."""
    # Fiyat hesapla
    random.seed(hash(title))  # Deterministik fiyat
    base = round(random.uniform(*price_range), 2)
    selling = round(base * random.uniform(0.85, 0.95), 2)
    compare = round(base * random.uniform(1.1, 1.3), 2)
    sample = round(base * 0.15, 2)
    weight = round(random.uniform(0.1, 5.0), 2)

    slug = _slug(title)
    img_seed = f"{seller}-{slug}"
    currency = "TRY" if frappe.db.exists("Currency", "TRY") else "USD"

    # Varyant satırları oluştur
    variant_items = []
    variant_configs = VARIANT_CONFIGS.get(variant_type, VARIANT_CONFIGS["giyim"])
    for vc in variant_configs:
        for j, val in enumerate(vc["values"]):
            mod = vc["price_mod"][j] if j < len(vc["price_mod"]) else 0
            variant_items.append({
                "attribute_type": vc["attr"],
                "attribute_value": val,
                "variant_price": round(selling + mod, 2) if mod != 0 else 0,
                "variant_stock": random.randint(50, 500),
                "variant_sku": f"{seller[-3:]}-{_slug(cat_name)[:4].upper()}-{product_idx:02d}-{_slug(val)[:3].upper()}",
                "variant_image": _img(variant_type, 400, 400, lock_id=f"{img_seed}-{_slug(val)}"),
            })

    # B2B toptan fiyat kademeleri
    pricing_tiers = [
        {"min_qty": 10, "max_qty": 49, "price": round(selling * 0.95, 2), "discount_percentage": 5},
        {"min_qty": 50, "max_qty": 99, "price": round(selling * 0.90, 2), "discount_percentage": 10},
        {"min_qty": 100, "max_qty": 0, "price": round(selling * 0.85, 2), "discount_percentage": 15},
    ]

    # Ürün spesifikasyonları
    attribute_values = [
        {"attribute_name": "Marka", "attribute_value": _get_brand(seller), "attribute_group": "Genel"},
        {"attribute_name": "Menşei", "attribute_value": "Türkiye", "attribute_group": "Genel"},
        {"attribute_name": "Malzeme", "attribute_value": _get_material(variant_type), "attribute_group": "Teknik"},
        {"attribute_name": "Garanti", "attribute_value": "1 Yıl", "attribute_group": "Satış"},
    ]

    # Ek görseller
    listing_images = [
        {"image": _img(variant_type, 800, 800, lock_id=f"{img_seed}-extra-{k}"), "alt_text": f"{title} - Görsel {k+1}", "sort_order": k}
        for k in range(3)
    ]

    # Lead time
    lead_time_ranges = [
        {"min_qty": 1, "max_qty": 50, "lead_days": random.randint(1, 3)},
        {"min_qty": 51, "max_qty": 200, "lead_days": random.randint(3, 7)},
        {"min_qty": 201, "max_qty": 0, "lead_days": random.randint(7, 15)},
    ]

    doc = frappe.new_doc("Listing")
    doc.title = title
    doc.seller_profile = seller
    doc.status = "Active"
    doc.listing_type = "Fixed Price"
    doc.category = seller_cat_name
    doc.product_category = product_cat_id
    doc.brand = _get_brand(seller)
    doc.condition = "New"
    doc.short_description = _short(title, cat_name)
    doc.description = _desc(title, cat_name)
    doc.currency = currency
    doc.base_price = base
    doc.selling_price = selling
    doc.compare_at_price = compare
    doc.discount_percentage = round((1 - selling / compare) * 100, 1)
    doc.sample_price = sample
    doc.b2b_enabled = 1
    doc.stock_qty = random.randint(500, 5000)
    doc.stock_uom = "Nos"
    doc.min_order_qty = random.choice([1, 5, 10, 20])
    doc.max_order_qty = 0
    doc.low_stock_threshold = 10
    doc.track_inventory = 1
    doc.allow_backorders = 0
    doc.primary_image = _img(variant_type, 800, 800, lock_id=img_seed)
    doc.has_variants = 1
    doc.is_free_shipping = random.choice([0, 0, 0, 1])
    doc.shipping_weight = weight
    doc.ships_from_country = "Turkey"
    doc.ships_from_city = "İstanbul"
    doc.handling_days = random.choice([1, 1, 2, 3])
    doc.country_of_origin = "Turkey"
    doc.package_type = random.choice(["Karton Kutu", "Poşet", "Karton Kutu"])
    doc.is_featured = 1 if product_idx == 1 and random.random() < 0.3 else 0
    doc.is_best_seller = 1 if random.random() < 0.1 else 0
    doc.is_new_arrival = 1 if random.random() < 0.2 else 0
    doc.is_on_sale = 1 if selling < base * 0.9 else 0
    doc.is_visible = 1
    doc.is_searchable = 1
    doc.selling_point = random.choice([
        "En düşük fiyat garantisi", "Hızlı kargo", "Ücretsiz iade",
        "Toptan özel fiyat", "Yeni sezon ürünü", "",
    ])
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

    doc.flags.ignore_permissions = True
    doc.flags.ignore_links = True
    doc.insert(ignore_permissions=True)

    # Standalone Listing Variant dokümanları (kombinasyonlar)
    _create_listing_variants(doc.name, variant_configs, selling, img_seed, seller, sector_key=variant_type)

    return doc.name


def _create_listing_variants(listing_name, variant_configs, base_price, img_seed, seller_code, sector_key="giyim"):
    """Birkaç anahtar kombinasyon için standalone Listing Variant oluştur."""
    if len(variant_configs) < 2:
        # Tek eksen — her değer için bir variant
        vc = variant_configs[0]
        for i, val in enumerate(vc["values"][:4]):
            mod = vc["price_mod"][i] if i < len(vc["price_mod"]) else 0
            _ensure_listing_variant(
                listing_name,
                variant_name=val,
                sku=f"{seller_code[-3:]}-{_slug(val)[:6].upper()}-VAR",
                price=round(base_price + mod, 2),
                stock=random.randint(50, 300),
                attrs=[{"attribute_name": vc["attr"], "attribute_value": val}],
                image=_img(sector_key, 600, 600, lock_id=f"{img_seed}-var-{_slug(val)}"),
            )
        return

    # İki eksen — çapraz kombinasyonlar (ilk 3 × ilk 2)
    vc1, vc2 = variant_configs[0], variant_configs[1]
    count = 0
    for i, v1 in enumerate(vc1["values"][:3]):
        for j, v2 in enumerate(vc2["values"][:2]):
            if count >= 5:
                return
            mod1 = vc1["price_mod"][i] if i < len(vc1["price_mod"]) else 0
            mod2 = vc2["price_mod"][j] if j < len(vc2["price_mod"]) else 0
            _ensure_listing_variant(
                listing_name,
                variant_name=f"{v1} - {v2}",
                sku=f"{seller_code[-3:]}-{_slug(v1)[:3].upper()}-{_slug(v2)[:3].upper()}",
                price=round(base_price + mod1 + mod2, 2),
                stock=random.randint(30, 200),
                attrs=[
                    {"attribute_name": vc1["attr"], "attribute_value": v1},
                    {"attribute_name": vc2["attr"], "attribute_value": v2},
                ],
                image=_img(sector_key, 600, 600, lock_id=f"{img_seed}-var-{_slug(v1)}-{_slug(v2)}"),
            )
            count += 1


def _ensure_listing_variant(listing_name, variant_name, sku, price, stock, attrs, image):
    """Tek bir Listing Variant dokümanı oluştur."""
    doc = frappe.new_doc("Listing Variant")
    doc.listing = listing_name
    doc.variant_name = variant_name
    doc.sku = sku
    doc.is_active = 1
    doc.price = price
    doc.stock_qty = stock
    doc.primary_image = image
    for attr in attrs:
        doc.append("variant_attributes", attr)
    doc.flags.ignore_permissions = True
    doc.flags.ignore_links = True
    doc.insert(ignore_permissions=True)


# ─── Yardımcı veri fonksiyonları ────────────────────────────

def _get_brand(seller_code):
    """Satıcıya uygun marka adı döndür."""
    brands = {
        "DEMO-001": "Anadolu",
        "DEMO-002": "Boğaziçi",
        "DEMO-003": "MarmaraT",
        "DEMO-004": "İstHırdavat",
        "DEMO-005": "KaradenizG",
        "DEMO-006": "EgeBeauty",
        "DEMO-007": "TrakyaHome",
        "DEMO-008": "AkdenizMut",
        "DEMO-009": "OsmanlıAks",
        "DEMO-010": "YıldızAmb",
    }
    return brands.get(seller_code, "İstoç")


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


# ═══════════════════════════════════════════════════════════════
#  ANA FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════

@frappe.whitelist()
def execute():
    """
    Demo veri oluştur: 10 satıcı · 500 kategori · 1.000 ürün

    Kullanım (bench):
        bench --site <site> execute tradehub_core.seed_demo_data.execute

    Kullanım (tarayıcı konsolu — Login as Administrator sonrası):
        frappe.call({method: "tradehub_core.seed_demo_data.execute"})
    """
    if not frappe.session.user == "Administrator" and not frappe.has_permission("Admin Seller Profile", "create"):
        frappe.throw(_("Bu işlem için Administrator yetkisi gereklidir."))
    frappe.flags.ignore_permissions = True
    frappe.flags.in_import = True
    random.seed(42)  # Tekrarlanabilir sonuçlar

    total_listings = 0

    print("=" * 60)
    print("  TradeHub Demo Data Seed")
    print("=" * 60)

    # ── 1. Satıcılar ────────────────────────────────────────
    print("\n[1/4] Satıcı profilleri oluşturuluyor...")
    for s in SELLERS:
        _ensure_seller(s)
        print(f"  ✓ {s['seller_name']} ({s['code']})")
    frappe.db.commit()

    # ── 2. Kategoriler ──────────────────────────────────────
    print("\n[2/4] Platform kategorileri oluşturuluyor...")
    for sector in SECTORS:
        _seller = next(s for s in SELLERS if s["code"] == sector["seller"])
        vt = _seller["variant_type"]
        sector_id = _ensure_category(
            sector["name"], "", f"DEMO-{sector['code']}", sort_order=0, sector_key=vt
        )
        leaf_count = 0
        for group_name, leaves in sector["groups"]:
            group_id = _ensure_category(
                group_name, sector_id,
                f"DEMO-{sector['code']}-{_slug(group_name)}",
                sector_key=vt,
            )
            for idx, leaf_tuple in enumerate(leaves):
                leaf_name = leaf_tuple[0]
                leaf_id = _ensure_category(
                    leaf_name, group_id,
                    f"DEMO-{sector['code']}-{_slug(leaf_name)}",
                    sort_order=idx,
                    sector_key=vt,
                )
                leaf_count += 1
        print(f"  ✓ {sector['name']}: {leaf_count} kategori")
    frappe.db.commit()

    # ── 3. Satıcı Kategorileri ──────────────────────────────
    print("\n[3/4] Satıcı-kategori eşleşmeleri oluşturuluyor...")
    # Her satıcıyı kendi sektöründeki yaprak kategorilerle eşleştir
    seller_cat_map = {}  # (seller_code, leaf_id) → seller_category_name
    for sector in SECTORS:
        seller_code = sector["seller"]
        _seller = next(s for s in SELLERS if s["code"] == seller_code)
        vt = _seller["variant_type"]
        for group_name, leaves in sector["groups"]:
            for leaf_tuple in leaves:
                leaf_name = leaf_tuple[0]
                leaf_id = f"DEMO-{sector['code']}-{_slug(leaf_name)}"
                sc_name = _ensure_seller_category(seller_code, leaf_id, leaf_name, sector_key=vt)
                seller_cat_map[(seller_code, leaf_id)] = sc_name
    frappe.db.commit()
    print(f"  ✓ {len(seller_cat_map)} satıcı-kategori eşleşmesi")

    # ── 4. Ürün İlanları ────────────────────────────────────
    print("\n[4/4] Ürün ilanları oluşturuluyor...")
    for sector in SECTORS:
        seller_code = sector["seller"]
        seller_data = next(s for s in SELLERS if s["code"] == seller_code)
        variant_type = seller_data["variant_type"]
        price_range = seller_data["price_range"]
        sector_listings = 0

        for group_name, leaves in sector["groups"]:
            for leaf_tuple in leaves:
                leaf_name = leaf_tuple[0]
                prod1_title = leaf_tuple[1]
                prod2_title = leaf_tuple[2]
                leaf_id = f"DEMO-{sector['code']}-{_slug(leaf_name)}"
                sc_name = seller_cat_map.get((seller_code, leaf_id))

                if not sc_name:
                    continue

                for pidx, ptitle in enumerate([prod1_title, prod2_title], 1):
                    _create_listing(
                        seller=seller_code,
                        sector=sector["name"],
                        seller_cat_name=sc_name,
                        product_cat_id=leaf_id,
                        cat_name=leaf_name,
                        title=ptitle,
                        product_idx=pidx,
                        variant_type=variant_type,
                        price_range=price_range,
                    )
                    total_listings += 1
                    sector_listings += 1

                # Her 20 üründe commit
                if sector_listings % 20 == 0:
                    frappe.db.commit()

        frappe.db.commit()
        print(f"  ✓ {seller_data['seller_name']}: {sector_listings} ürün")

    frappe.db.commit()
    frappe.flags.in_import = False

    print("\n" + "=" * 60)
    print(f"  ✅ TAMAMLANDI!")
    print(f"  Satıcılar:  {len(SELLERS)}")
    print(f"  Kategoriler: ~500")
    print(f"  Ürünler:    {total_listings}")
    print("=" * 60)


@frappe.whitelist()
def cleanup():
    """
    Tüm demo veriyi sil.

    Kullanım (bench):
        bench --site <site> execute tradehub_core.seed_demo_data.cleanup

    Kullanım (tarayıcı konsolu):
        frappe.call({method: "tradehub_core.seed_demo_data.cleanup"})
    """
    if not frappe.session.user == "Administrator" and not frappe.has_permission("Admin Seller Profile", "delete"):
        frappe.throw(_("Bu işlem için Administrator yetkisi gereklidir."))
    frappe.flags.ignore_permissions = True
    print("Demo veri temizleniyor...")

    # Sırayla sil (bağımlılık sırası: en bağımlıdan başla)

    # 1. Listing Variant
    variants = frappe.get_all(
        "Listing Variant",
        filters={"listing": ["like", "LST-%"]},
        pluck="name",
    )
    # Sadece demo satıcılara ait listing'lerin varyantlarını sil
    demo_listings = frappe.get_all(
        "Listing",
        filters={"seller_profile": ["like", "DEMO-%"]},
        pluck="name",
    )
    if demo_listings:
        demo_variants = frappe.get_all(
            "Listing Variant",
            filters={"listing": ["in", demo_listings]},
            pluck="name",
        )
        for v in demo_variants:
            frappe.delete_doc("Listing Variant", v, force=True, ignore_permissions=True)
        print(f"  ✓ {len(demo_variants)} Listing Variant silindi")

    # 2. Listings
    for l in demo_listings:
        frappe.delete_doc("Listing", l, force=True, ignore_permissions=True)
    print(f"  ✓ {len(demo_listings)} Listing silindi")
    frappe.db.commit()

    # 3. Seller Categories
    demo_seller_cats = frappe.get_all(
        "Seller Category",
        filters={"seller": ["like", "DEMO-%"]},
        pluck="name",
    )
    for sc in demo_seller_cats:
        frappe.delete_doc("Seller Category", sc, force=True, ignore_permissions=True)
    print(f"  ✓ {len(demo_seller_cats)} Seller Category silindi")
    frappe.db.commit()

    # 4. Product Categories (yaprak → dal → kök sırasıyla)
    demo_cats = frappe.get_all(
        "Product Category",
        filters={"external_id": ["like", "DEMO-%"]},
        fields=["name", "lft", "rgt"],
        order_by="rgt - lft asc",  # Yapraklar önce
    )
    for c in demo_cats:
        if frappe.db.exists("Product Category", c["name"]):
            frappe.delete_doc("Product Category", c["name"], force=True, ignore_permissions=True)
    print(f"  ✓ {len(demo_cats)} Product Category silindi")
    frappe.db.commit()

    # 5. Admin Seller Profiles
    demo_sellers = frappe.get_all(
        "Admin Seller Profile",
        filters={"seller_code": ["like", "DEMO-%"]},
        pluck="name",
    )
    for sp in demo_sellers:
        frappe.delete_doc("Admin Seller Profile", sp, force=True, ignore_permissions=True)
    print(f"  ✓ {len(demo_sellers)} Admin Seller Profile silindi")

    # 6. Demo Users
    demo_users = frappe.get_all(
        "User",
        filters={"email": ["like", "demo-seller-%@istoc.demo"]},
        pluck="name",
    )
    for u in demo_users:
        frappe.delete_doc("User", u, force=True, ignore_permissions=True)
    print(f"  ✓ {len(demo_users)} Demo User silindi")

    frappe.db.commit()
    print("\n✅ Tüm demo veri temizlendi!")
