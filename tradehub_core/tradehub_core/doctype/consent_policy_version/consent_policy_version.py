import frappe
from frappe.model.document import Document


class ConsentPolicyVersion(Document):
    def before_save(self):
        if self.status == "Active":
            self._supersede_older_versions()

    def _supersede_older_versions(self):
        older = frappe.get_all(
            "Consent Policy Version",
            filters={
                "policy_type": self.policy_type,
                "status": "Active",
                "name": ("!=", self.name),
            },
            pluck="name",
        )
        for name in older:
            frappe.db.set_value(
                "Consent Policy Version", name, "status", "Superseded",
                update_modified=False,
            )
