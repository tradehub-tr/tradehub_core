"""Sprint 6 — DB-driven sidebar API.

Frontend `data/navigation.js` sabit array'i yerine bu endpoint'ten render-edilebilir
sidebar JSON çekilir. Süper admin TH Module Registry / TH Module Policy
değişiklikleri yaptığında sidebar anında güncellenir (cache 5dk + flush hooks).

Endpoint:
    /api/method/tradehub_core.api.v1.navigation.get_navigation?panel=seller

Response:
    {
      "panel": "seller",
      "sections": [
        {
          "section_key": "store",
          "module_key": "seller.store",
          "label": "Mağazam",
          "icon": "store",
          "color": "#7c3aed",
          "mode": "visible",
          "items": [   # groups
            {
              "module_key": "seller.store.profil",
              "label": "Profil & Finans",
              "color": "#f59e0b",
              "mode": "visible",
              "items": [   # items
                { "module_key": "...", "label": "Profilim", "icon": "user-check",
                  "route": null, "doctype": "User Profile", "mode": "visible",
                  "seller_owned": true }
              ]
            }
          ]
        }
      ]
    }
"""

from __future__ import annotations

import frappe


@frappe.whitelist(methods=["GET"])
def get_navigation(panel: str = "seller") -> dict:
	"""Oturumdaki kullanıcı için panel sidebar tree'sini döner.

	Cache: per-user × panel (resolver içinde 5dk).
	"""
	from tradehub_core.utils.permission_resolver import get_navigation_tree

	if panel not in ("seller", "admin", "storefront", "shared"):
		panel = "seller"

	tree = get_navigation_tree(panel=panel)

	sections: list[dict] = []
	for section in tree:
		groups: list[dict] = []
		for group in section.get("children", []):
			items: list[dict] = []
			for item in group.get("children", []):
				items.append(
					{
						"module_key": item["module_key"],
						"label": item["label"],
						"icon": item.get("icon") or "",
						"route": item.get("route") or None,
						"doctype": item.get("doctype_ref") or None,
						"mode": item.get("mode", "visible"),
						"seller_owned": bool(item.get("seller_owned")),
						"order": item.get("display_order", 0),
					}
				)
			groups.append(
				{
					"module_key": group["module_key"],
					"label": group.get("label") or "",
					"color": group.get("color") or "",
					"mode": group.get("mode", "visible"),
					"order": group.get("display_order", 0),
					"items": items,
				}
			)
		sections.append(
			{
				"module_key": section["module_key"],
				"section_key": section.get("section_key") or "",
				"label": section.get("label") or "",
				"icon": section.get("icon") or "",
				"color": section.get("color") or "",
				"mode": section.get("mode", "visible"),
				"order": section.get("display_order", 0),
				"items": groups,
			}
		)

	# Hidden modüllerin pointer listesi — router guard URL bypass'i engellemek
	# için tree'de görünmeyen ama erişimi kısıtlı doctype/route'ları bu liste
	# üzerinden tespit eder.
	from tradehub_core.utils.permission_resolver import get_hidden_module_pointers

	hidden = get_hidden_module_pointers(panel=panel)

	return {
		"panel": panel,
		"sections": sections,
		"hidden_doctypes": hidden["doctypes"],
		"hidden_routes": hidden["routes"],
	}


@frappe.whitelist(methods=["GET"])
def get_module_mode_map(panel: str = "seller") -> dict:
	"""Frontend için sadece mode haritası — küçük payload, hızlı senkronizasyon."""
	from tradehub_core.utils.permission_resolver import (
		get_module_mode_map as _resolver_mode_map,
	)

	return {"panel": panel, "modes": _resolver_mode_map(panel=panel)}
