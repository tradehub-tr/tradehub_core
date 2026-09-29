"""Taşıması yapılmış ortamlarda sepet/favori görsel kopyalarını yeni adrese çevir.

Retro-rename bu alanları eskiden "geçmiş kaydı" sayıp güncellemedi; 90 gün sonra
`Media URL Redirect` satırları silinince görseller kırılırdı (spec
2026-09-28-seo-gorsel-adresi §5.3). Artık `usage.LIVE_SOURCES` içindeler; bu yama
geçmişte yapılmış taşımaların eksiğini kapatır.

İdempotent: yalnız `snapshot_image`'ı HÂLÂ bir yönlendirmenin `source_url`'ine
tam eşit olan satırlar değişir. Her değişiklik yönlendirme satırının
`ref_changes` kanıtına eklenir; böylece o işin geri alınması (`run_rollback`)
bu satırları da eski adrese döndürür — aksi hâlde geri alma sonrası sepet,
artık olmayan hash'li adresi gösterirdi.
"""

from __future__ import annotations

import json

import frappe

from tradehub_core.media import refs

KAYNAKLAR: tuple[tuple[str, str], ...] = (
	("tabCart Item", "snapshot_image"),
	("tabBuyer Favorite Item", "snapshot_image"),
)


def execute(*, only_source: str | None = None) -> dict[str, int]:
	"""`only_source`: yalnız testler için — gerçek veriye dokunmadan tek yönlendirmeyle sınar."""
	sayac: dict[str, int] = {}
	filtre = "where r.source_url = %(kaynak)s" if only_source else ""
	for tablo, kolon in KAYNAKLAR:
		refs._assert_writable(tablo, kolon)  # LIVE_SOURCES'ta değilse yazma yok
		satirlar = frappe.db.sql(
			f"""select t.name as satir, t.`{kolon}` as eski, r.name as yonlendirme, r.target_url as yeni
				from `{tablo}` t join `tabMedia URL Redirect` r on r.source_url = t.`{kolon}`
				{filtre}
				order by r.name, t.name""",  # noqa: S608 — tablo/kolon sabit listeden
			{"kaynak": only_source},
			as_dict=True,
		)
		sayac[tablo] = 0
		ekler: dict[str, list[dict[str, str]]] = {}
		for s in satirlar:
			if not s.yeni or s.yeni == s.eski:
				continue
			frappe.db.sql(  # noqa: S608 — tablo/kolon sabit listeden
				f"update `{tablo}` set `{kolon}`=%s where name=%s and `{kolon}`=%s",
				(s.yeni, s.satir, s.eski),
			)
			sayac[tablo] += 1
			ref = {"table": tablo, "column": kolon, "row": s.satir}
			ekler.setdefault(s.yonlendirme, []).append(refs._retarget_change(ref, s.eski, s.yeni))
		for yonlendirme, degisiklikler in ekler.items():
			_kanita_ekle(yonlendirme, degisiklikler)
	frappe.db.commit()
	print(f"v15_9_62 sepet/favori retarget: {sayac}")
	return sayac


def _kanita_ekle(yonlendirme: str, degisiklikler: list[dict[str, str]]) -> None:
	"""`ref_changes` JSON listesine ekle. Kanıtı olmayan/bozuk eski satırda
	geri alma zaten reddediliyor (`retro_rename._rollback_one`); orada kanıt
	UYDURULMAZ — yalnız yazılabilir liste varsa eklenir."""
	ham = (frappe.db.get_value("Media URL Redirect", yonlendirme, "ref_changes") or "").strip()
	if not ham:
		return
	try:
		mevcut = json.loads(ham)
	except ValueError:
		return
	if not isinstance(mevcut, list):
		return
	frappe.db.set_value(
		"Media URL Redirect",
		yonlendirme,
		"ref_changes",
		json.dumps(mevcut + degisiklikler, ensure_ascii=True),
		update_modified=False,
	)
