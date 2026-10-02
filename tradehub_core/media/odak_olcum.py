"""`suggest_focal` öneri kalitesi ölçümü (spec 2026-10-01 §4.3) — iyileştirme AYRI iş.

Elle kaydedilmiş (`method = manual`) mağaza görseli odaklarını, aynı dosya için
`focal_from_bytes` önerisiyle karşılaştırır. Yazmaz.

    docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && \
        bench --site istoc.localhost execute tradehub_core.media.odak_olcum.olc"
"""

from __future__ import annotations

import math

import frappe
from frappe.query_builder import DocType

from tradehub_core.media.pipeline.api import crop as crop_lib


def olc(limit: int = 200) -> dict:
	niyet, varlik = DocType("Media Crop Intent"), DocType("Media Asset")
	satirlar = (
		frappe.qb.from_(niyet)
		.join(varlik)
		.on(varlik.name == niyet.asset)
		.select(niyet.asset, niyet.focal_x, niyet.focal_y, varlik.slot_key, varlik.source_file)
		.where(niyet.method == "manual")
		.where(niyet.focal_x.isnotnull())
		.where(varlik.slot_key.isin(["company.cover_image", "seller.logo"]))
		.orderby(niyet.modified, order=frappe.qb.desc)
		.limit(int(limit))
	).run(as_dict=True)
	sonuc = []
	for r in satirlar:
		try:
			icerik = frappe.get_doc("File", r["source_file"]).get_content()
		except (OSError, frappe.DoesNotExistError):
			continue
		oneri = crop_lib.focal_from_bytes(icerik)
		elle = (float(r["focal_x"]), float(r["focal_y"]))
		sonuc.append(
			{
				"asset": r["asset"],
				"slot": r["slot_key"],
				"manual": [round(elle[0], 3), round(elle[1], 3)],
				"suggested": [round(oneri.x, 3), round(oneri.y, 3)],
				"measured": oneri.measured,
				"distance": round(math.hypot(oneri.x - elle[0], oneri.y - elle[1]), 3),
			}
		)
	mesafeler = sorted(s["distance"] for s in sonuc)
	ozet = {
		"n": len(sonuc),
		"median": mesafeler[len(mesafeler) // 2] if mesafeler else None,
		"within_0_15": sum(1 for d in mesafeler if d <= 0.15),
	}
	print(frappe.as_json({"ozet": ozet, "satirlar": sonuc}))
	return {"ozet": ozet, "satirlar": sonuc}
