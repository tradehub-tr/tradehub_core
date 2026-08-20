# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-051 (şartname) — `Media Superadmin` rolü + `Media Storage Settings` varsayılanları.

Rol NEDEN burada açılıyor: `media/pipeline/doctype_specs/` altındaki 13 tasarım
JSON'unun tamamı `Media Superadmin` rolüne atıfta bulunuyordu ama rol DB'de
HİÇ YOKTU (ölçüldü, 2026-08-19). Frappe olmayan bir role verilen DocPerm
satırını sessizce yok sayar; yani rol yaratılmadan izin modeli kâğıt üstünde
kalırdı.

Varsayılanlar `local` yazılır — bugün üretime alınabilir tek kip o
(`docs/reports/23-t051-s3-adaptor.md` §7). Yama idempotenttir ve `tabSingles`'ta
satırı OLAN hiçbir alana dokunmaz: operatörün bilinçli olarak değiştirdiği bir
ayarı bir migrate'in geri alması, bu yamanın yapabileceği en tehlikeli şey olurdu
(v15_9_22 emsali).
"""

from __future__ import annotations

import frappe

ROLE: str = "Media Superadmin"
DOCTYPE: str = "Media Storage Settings"

#: Alan -> varsayılan. Hiçbiri S3 açmaz.
VARSAYILANLAR: dict[str, object] = {
	"backend": "local",
	"blocker_ack": 0,
	"signed_url_ttl_seconds": 0,
	"keep_originals": 1,
	"original_local_days": 0,
	"original_then_action": "notify_only",
	"trash_retention_days": 30,
	"derivative_unused_days": 90,
	"derivative_action": "notify_only",
	"derivative_regenerate_on_demand": 1,
	"archive_retention_days": 30,
	"backup_keep_sets": 14,
}


def execute() -> dict:
	rol_yaratildi = _rolu_kur()

	# Yeni DocType migrate sırasında bu yamadan önce yüklenmemiş olabilir.
	#
	# DİKKAT — `reload_doc` dosyayı BULAMAZSA sessizce `False` döner, hata
	# FIRLATMAZ. Bu yama bir kez tam olarak böyle davrandı: `tabSingles`a 29
	# değer yazıldı, `Patch Log`a "koştu" yazıldı, ama `tabDocType` satırı hiç
	# oluşmadı → `get_single` ve iki whitelist ucu `ImportError` ile HTTP 500
	# verdi (bulgu: `docs/reports/32-faz8-api-kapanis.md`). Sessiz başarısızlığı
	# gürültülü hâle getiriyoruz: dönüş değeri kontrol edilir ve yama patlar.
	if not frappe.reload_doc("tradehub_core", "doctype", "media_storage_settings"):
		frappe.throw(
			frappe._("Media Storage Settings DocType yüklenemedi — şema dosyası bulunamadı.")
		)

	yazilan: list[str] = []
	for alan, varsayilan in VARSAYILANLAR.items():
		if _kayitli_mi(alan):
			continue
		frappe.db.set_single_value(DOCTYPE, alan, varsayilan)
		yazilan.append(alan)

	frappe.db.commit()
	return {"role_created": rol_yaratildi, "written": yazilan}


def _rolu_kur() -> bool:
	"""Rolü yarat. `desk_access=1`: rol sahipleri System User olarak çalışır."""
	if frappe.db.exists("Role", ROLE):
		return False
	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": ROLE,
			"desk_access": 1,
			"is_custom": 1,
			# Rol hiçbir kullanıcıya OTOMATİK atanmaz. Atama bilinçli bir
			# yönetim kararıdır; sır taşıyan bir ekranın anahtarı yamayla
			# dağıtılmaz.
		}
	).insert(ignore_permissions=True)
	return True


def _kayitli_mi(alan: str) -> bool:
	"""Single değerinin `tabSingles`'ta satırı var mı (v15_9_22 ile aynı gerekçe).

	`get_single_value` ile "boş mu" diye bakmak yetmez: operatörün bilerek 0
	yaptığı bir alan da boş görünür ve yama onu her koşuda yeniden yazardı.
	`Singles` bir DocType değil, Frappe'nin singleton değer tablosudur —
	`frappe.db.exists` orada DAİMA None döner.
	"""
	satir = frappe.db.sql(
		"SELECT 1 FROM `tabSingles` WHERE `doctype` = %s AND `field` = %s LIMIT 1",
		(DOCTYPE, alan),
	)
	return bool(satir)
