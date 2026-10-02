"""Odak noktası okuması — vitrin ve önizleme penceresinin TEK kaynağı (2026-10-01).

Anahtar `(file_url, satıcı)`dır, varlık değil: `kare.py` / `magaza_gorseli.py`
dönüştürdüğü dosyanın eski `Media Asset`ini `archived` yapıp AYNI `File`
satırına yeni varlık açar ve `File.file_url`i yeni adrese çevirir. Odak eski
varlıktaysa bile bu sorgu onu yeni adresle bulur (join `File` üzerinden).
Aynı adreste 5+ mükerrer `File` satırı ölçülmüştür; join `file_url` iledir.

Sistem okumasıdır: odak bir mahremiyet değeri değildir (vitrinde CSS olarak
herkese açık basılıyor) ve guest bağlamında `get_list` hiçbir şey döndürmez.
Kiracı sınırı anahtarın kendisindedir — bir satıcının odağı BAŞKA satıcının
isteğine asla dönmez; yalnız sistem (`owner_seller` boş) odağı yedektir.
Bu yüzden satıcı değeri OTURUMDAN (ya da ürün/mağaza kaydından) gelmelidir,
ASLA istekten (sorgu parametresi, gövde) alınmamalıdır.
"""

from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe.query_builder import DocType


def odaklar(ogeler: Iterable[tuple[str, str]]) -> dict[tuple[str, str], dict[str, float]]:
	"""`(file_url, satıcı)` → `{"x", "y"}` — o satıcının o dosya için kaydettiği EN SON odak.

	Satıcı oturumdan / kayıttan gelmeli, istekten ASLA: izin kontrolü yoktur.
	"""
	istekler = {(str(u), str(s or "")) for u, s in ogeler if u}
	if not istekler:
		return {}
	niyet, varlik, dosya = DocType("Media Crop Intent"), DocType("Media Asset"), DocType("File")
	satirlar = (
		frappe.qb.from_(niyet)
		.join(varlik)
		.on(varlik.name == niyet.asset)
		.join(dosya)
		.on(dosya.name == varlik.source_file)
		.select(dosya.file_url, varlik.owner_seller, niyet.focal_x, niyet.focal_y, niyet.modified)
		.where(dosya.file_url.isin(sorted({u for u, _ in istekler})))
		.where(niyet.focal_x.isnotnull())
		.where(niyet.focal_y.isnotnull())
		.orderby(niyet.modified)
	).run(as_dict=True)
	son: dict[tuple[str, str], dict[str, float]] = {}
	for r in satirlar:
		# Artan `modified` sırası: sonraki satır öncekinin üstüne yazar → en son kazanır.
		son[(r["file_url"], str(r.get("owner_seller") or ""))] = {
			"x": round(float(r["focal_x"]), 4),
			"y": round(float(r["focal_y"]), 4),
		}
	cikti: dict[tuple[str, str], dict[str, float]] = {}
	for u, s in istekler:
		deger = son.get((u, s)) or son.get((u, ""))
		if deger:
			cikti[(u, s)] = deger
	return cikti
