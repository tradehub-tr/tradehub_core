"""UOM DocType'ını tradehub_core'a devral (Faz 4 — ERPNext decouple).

ERPNext bu siteden kaldırılacak (`bench uninstall-app erpnext`); UOM kayıtları
(239 adet — RFQ.unit ve Listing.stock_uom Link'liyor) korunmalı. Uninstall,
erpnext modüllerine ait tüm DocType'ları (ve tablolarını) siler — bu patch
UOM DocType'ının `module` alanını "Tradehub Core" yaparak kaydı re-home eder,
böylece uninstall UOM'a dokunmaz. Şemayı migrate'in model sync'i zaten bizim
tradehub_core/doctype/uom/uom.json kopyasıyla eşitler (alanlar birebir aynı).

SIRA: Bu patch erpnext uninstall'ından ÖNCE koşmalı — normal akışta orkestratör
önce `bench migrate` (patch burada koşar), sonra uninstall çalıştırır.
erpnext yüklü değilse ya da UOM zaten devralınmışsa no-op. Idempotent.
"""

import frappe


def execute() -> None:
	if not frappe.db.exists("DocType", "UOM"):
		# Taze site: DocType'ı model sync bizim JSON'dan zaten oluşturacak.
		return

	current_module: str | None = frappe.db.get_value("DocType", "UOM", "module")
	if current_module == "Tradehub Core":
		return

	frappe.db.set_value("DocType", "UOM", "module", "Tradehub Core")
	frappe.clear_cache(doctype="UOM")
	frappe.db.commit()
