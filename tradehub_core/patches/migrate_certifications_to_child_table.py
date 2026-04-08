"""Migrate certifications from Small Text field to Seller Certification child table.

Parses comma-separated certifications string, creates Certification Type master records,
and populates Seller Certification child table rows.
"""
import frappe


# Known management certifications
MANAGEMENT_CERTS = {
    "ISO 9001", "ISO 14001", "ISO 45001", "ISO 22000", "ISO 27001",
    "IECQ", "IECQ QC080000", "BSCI", "SEDEX", "SA8000", "OHSAS 18001",
    "GMP", "HACCP", "FSC",
}


def execute():
    # Skip if Certification Type doctype doesn't exist yet
    if not frappe.db.table_exists("tabCertification Type"):
        return

    # Get all Admin Seller Profiles that have certifications text
    profiles = frappe.db.sql(
        """SELECT name, certifications FROM `tabAdmin Seller Profile`
           WHERE certifications IS NOT NULL AND certifications != ''""",
        as_dict=True,
    )

    if not profiles:
        return

    for profile in profiles:
        certs_str = profile.certifications or ""
        cert_names = [c.strip() for c in certs_str.split(",") if c.strip()]

        for cert_name in cert_names:
            # Determine category
            category = "Management" if cert_name.upper() in {c.upper() for c in MANAGEMENT_CERTS} else "Product"

            # Create Certification Type if not exists
            if not frappe.db.exists("Certification Type", {"certification_name": cert_name}):
                ct = frappe.new_doc("Certification Type")
                ct.certification_name = cert_name
                ct.category = category
                ct.status = "Approved"
                ct.flags.ignore_permissions = True
                try:
                    ct.insert()
                except Exception:
                    # Duplicate or other error — skip
                    pass

            # Add to Seller Certification child table if not already there
            existing = frappe.db.exists(
                "Seller Certification",
                {"parent": profile.name, "certification_type": cert_name},
            )
            if not existing:
                doc = frappe.get_doc("Admin Seller Profile", profile.name)
                doc.append("certifications", {
                    "certification_type": cert_name,
                })
                doc.flags.ignore_permissions = True
                doc.save()

    frappe.db.commit()
