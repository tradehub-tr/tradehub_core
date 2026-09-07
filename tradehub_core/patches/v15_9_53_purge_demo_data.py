# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Demo/mock veriyi kalıcı olarak temizle — canlıya (alpha/prod) geçişte bir kez çalışır.

Neden patch: `seed_demo_data.cleanup` şimdiye kadar yalnız elle (bench execute)
çağrılıyordu. Ürün gerçek veriyle yayına alınırken demo satıcılar/ilanlar/markalar
sistemde kalmasın diye deploy migrate'inde otomatik koşsun. Patch mekanizması bunu
site başına TEK KEZ çalıştırır (tabPatch Log), bir daha tekrarlamaz.

Kapsam (cleanup içinde tanımlı, dar filtreler):
  - Listing.seller_profile LIKE 'DEMO-%'
  - Admin/Seller Profile, KYB, Seller Application: seller_code 'DEMO-%' veya
    user 'demo-seller-%@istoc.demo'; adlı demo hesapların (NAMED_DEMO_SELLER_EMAILS)
    profil/başvuru kayıtları — ama User login'leri KORUNUR.
  - Brand 'DEMO-BRAND-%', Seller Review 'DEMO-%', demo-*@istoc.demo kullanıcıları,
    seed kataloğundaki Shipping Method / Certification Type / Product Attribute.

Gerçek (DEMO işaretsiz) ilan, satıcı ve kullanıcılar SİLİNMEZ. cleanup kendi
içinde commit eder; idempotent — kayıt yoksa no-op.
"""

import frappe

from tradehub_core.seed_demo_data import cleanup


def execute():
	try:
		cleanup(silent=True)
	except Exception:
		# Deploy'u bir temizlik hatası yüzünden durdurma; günlüğe yaz, devam et.
		frappe.log_error(
			title="v15_9_53_purge_demo_data", message=frappe.get_traceback()
		)
