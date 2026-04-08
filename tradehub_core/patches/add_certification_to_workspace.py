import frappe
import json


def execute():
    ws_name = "Sat\u0131c\u0131 Paneli"
    if not frappe.db.exists("Workspace", ws_name):
        return

    ws = frappe.get_doc("Workspace", ws_name)
    content = json.loads(ws.content or "[]")

    # Check if already added
    if any("Certification Type" in json.dumps(item) for item in content):
        return

    # Find sp1 spacer (after Satici Yonetimi section)
    sp1_idx = next((i for i, item in enumerate(content) if item.get("id") == "sp1"), None)
    if sp1_idx is None:
        return

    # Insert shortcut before spacer
    content.insert(sp1_idx, {
        "id": "sc20",
        "type": "shortcut",
        "data": {"shortcut_name": "Certification Type", "col": 4},
    })

    ws.content = json.dumps(content)

    # Add shortcut entry if not exists
    has_shortcut = any(
        s.link_to == "Certification Type" for s in ws.shortcuts
    )
    if not has_shortcut:
        ws.append("shortcuts", {
            "color": "Green",
            "doc_view": "List",
            "label": "Certification Type",
            "link_to": "Certification Type",
            "stats_filter": "",
            "type": "DocType",
        })

    ws.flags.ignore_permissions = True
    ws.save()
    frappe.db.commit()
