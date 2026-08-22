"""`Media SEO Override` DocType'ını kur ve indekslerini garanti et (TUR-135 Dilim 1).

Karar: `docs/MEDYA-SEO-SOZLESMESI.md` §4.3 — varlık metadata'sı ≠ kullanım
metadata'sı. Aynı görsel üç sayfada üç farklı alt metni isteyebilir; tek
global alan bunu karşılayamaz.

Desen `v15_9_28_media_usage`'dan alındı (aynı depoda iki farklı indeks kurma
yöntemi olmasın): `reload_doc` → tablo doğrulaması → eksik indeksleri ekle.
Frappe `search_index` ile tekil olmayan indeksi kendi kurar ama BİLEŞİK ve
UNIQUE indeksi kurmaz; anahtar dörtlüsünün tekilliği yalnız uygulama
katmanında kalırsa yarış koşulunda iki ezme oluşabilir.

İdempotent: DocType yeniden yüklenir, var olan indeks atlanır.
"""

from __future__ import annotations

import frappe
from frappe import _

DOCTYPE: str = "Media SEO Override"
TABLO: str = "tabMedia SEO Override"

#: indeks adı → (UNIQUE mi, kolonlar)
INDEKSLER: dict[str, tuple[bool, tuple[str, ...]]] = {
	# Okuma yolu: bir dosyanın TÜM ezmeleri (fields_for tek sorguda çeker).
	"ix_seo_override_file": (False, ("file_url",)),
	# Ters yön: bir kaydın (ör. Listing) tüm ezmeleri — panel ve toplu işlem.
	"ix_seo_override_ref": (False, ("ref_doctype", "ref_name")),
	# Anahtar dörtlüsü tekil: aynı kullanım için iki ezme olamaz.
	"uk_seo_override_quad": (True, ("file_url", "ref_doctype", "ref_name", "ref_field")),
}


def execute() -> dict:
	if not frappe.reload_doc("tradehub_core", "doctype", "media_seo_override"):
		frappe.throw(_("Media SEO Override DocType yüklenemedi — şema dosyası bulunamadı."))
	if not frappe.db.table_exists(DOCTYPE):
		frappe.throw(_("DocType kaydı oluştu ama tablosu yok: {0}").format(TABLO))

	eklenen = [ad for ad in INDEKSLER if _indeks_kur(ad)]
	frappe.db.commit()
	return {"doctype": DOCTYPE, "indexes_added": eklenen, "indexes_total": len(INDEKSLER)}


def _mevcut_indeksler() -> set[str]:
	satirlar = frappe.db.sql(
		"""select index_name from information_schema.statistics
		where table_schema = database() and table_name = %s""",
		(TABLO,),
	)
	return {r[0] for r in satirlar}


def _indeks_kur(ad: str) -> bool:
	"""Yoksa ekler. Döndürdüğü değer "bu koşumda eklendi mi"."""
	if ad in _mevcut_indeksler():
		return False
	tekil, kolonlar = INDEKSLER[ad]
	kolon_listesi = ", ".join(f"`{k}`" for k in kolonlar)
	benzersiz = "UNIQUE " if tekil else ""
	# Kolon ve indeks adları bu modüldeki SABİT sözlükten geliyor; dışarıdan
	# değer almıyor (anti-patterns.md §11 f-string SQL kuralının gerekçesi).
	frappe.db.sql(f"ALTER TABLE `{TABLO}` ADD {benzersiz}INDEX `{ad}` ({kolon_listesi})")
	return True
