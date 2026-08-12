"""tabShipment'tan ERPNext Shipment artığı orphan kolonları düşür (Faz 4).

ERPNext'in kendi Shipment DocType'ı bizim Shipment ile ad çakışması yaşıyordu;
site ERPNext Shipment'ı hiç kullanmadı ve erpnext uninstall ediliyor. DocType
meta artık bizim şemayı gösteriyor ama ERPNext sync'inin eklediği kolonlar
tabloda orphan kalıyor — bu patch yalnız o kolonları DROP eder.

Güvenlik gerekçesi: tablo şu an 0 satır; satır olsaydı bile aşağıdaki liste
YALNIZ ERPNext'e özgü kolonları içerir (iki şemada da bulunan total_weight,
shipment_type, status, carrier, carrier_service listede YOK) — DROP bizim
alanlardaki veriyi etkileyemez, bu yüzden satır sayısına bakılmaksızın düşülür.

Idempotent: her kolon için has_column kontrolü; kolon yoksa atlanır.
"""

import frappe

# ERPNext setup/stock Shipment şemasından kalan kolonlar — bizim
# tradehub_core Shipment şemasıyla kesişen alanlar bilinçli olarak LİSTE DIŞI.
ERPNEXT_SHIPMENT_COLUMNS: tuple[str, ...] = (
	"pickup_from_type",
	"pickup_company",
	"pickup_customer",
	"pickup_supplier",
	"pickup",
	"pickup_address_name",
	"pickup_address",
	"pickup_contact_person",
	"pickup_contact_name",
	"pickup_contact_email",
	"pickup_contact",
	"delivery_to_type",
	"delivery_company",
	"delivery_customer",
	"delivery_supplier",
	"delivery_to",
	"delivery_address_name",
	"delivery_address",
	"delivery_contact_name",
	"delivery_contact_email",
	"delivery_contact",
	"parcel_template",
	"pallets",
	"value_of_goods",
	"pickup_date",
	"pickup_from",
	"pickup_to",
	"pickup_type",
	"incoterm",
	"description_of_content",
	"service_provider",
	"shipment_id",
	"shipment_amount",
	"tracking_url",
	"awb_number",
	"tracking_status",
	"tracking_status_info",
	"amended_from",
)


def execute() -> None:
	if not frappe.db.table_exists("Shipment"):
		return

	to_drop: list[str] = [col for col in ERPNEXT_SHIPMENT_COLUMNS if frappe.db.has_column("Shipment", col)]
	if not to_drop:
		return

	# Kolon adları yukarıdaki sabit whitelist'ten gelir (user input değil) —
	# DDL parametrelenemediği için f-string burada güvenli ve kaçınılmaz.
	drops = ", ".join(f"DROP COLUMN `{col}`" for col in to_drop)
	frappe.db.sql_ddl(f"ALTER TABLE `tabShipment` {drops}")
	frappe.clear_cache(doctype="Shipment")
