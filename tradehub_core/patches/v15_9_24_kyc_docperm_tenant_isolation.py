"""Ö-3 — KYC Verification kiracı izolasyonu: "Seller Owner" Custom DocPerm daraltması.

Kök neden (ölçüldü, canlı DB 2026-08-19):
  `v15_8_3_seller_owner_kyb_kyc_docperm` patch'i "Seller Owner" rolüne HEM KYB
  HEM KYC Verification'da permlevel-0 `read=1, write=1, if_owner=0` verdi.
  Gerekçesinde şöyle yazıyor: *"Tenant izolasyonu KORUNUR: her iki doctype'ta
  permission_query_conditions + has_permission hook'u var"*. Bu cümle KYB için
  doğruydu, KYC için DEĞİLDİ — `hooks.py` yalnız KYB'yi kaydetmişti. Yani
  patch'in güvenlik varsayımı KYC tarafında hiç var olmadı.

  Ölçülen etki (kanıt: docs/reports/24-kyc-izolasyon.md):
    - "Seller Owner" rolündeki mağaza sahibi BAŞKASININ KYC kaydını
      `frappe.client.get` ile tam okuyordu (phone, address, billing_address,
      tax_id, identity_document, email_field).
    - `frappe.client.set_value` ile BAŞKASININ `phone` alanını DEĞİŞTİRDİ.
    - `frappe.get_list` sistemdeki tüm KYC kayıtlarını döndürüyordu.

Düzeltme iki parçalı — bu patch ikinci parçadır:
  1. `permissions.py` + `hooks.py`: `kyc_verification_query_conditions` ve
     `kyc_verification_has_permission` (KYB'nin birebir aynası). ASIL kapı bu.
  2. (bu patch) DocPerm satırının daraltılması — savunma derinliği.

Satır neden SİLİNMİYOR:
  Meşru bir kullanımı var ve ölçüldü. Panel (admin-panel) KYC formunu generic
  desk REST üzerinden açıp kaydediyor (`api.updateDoc("KYC Verification", ...)`,
  `DocTypeFormView.vue`); v15_8_3 tam olarak bu yoldaki 403'ü kapatmak için
  eklendi. Satır silinirse mağaza sahibi KENDİ KYC kaydını panelde açamaz.

`if_owner` neden 1 YAPILMIYOR:
  Bu doctype'ta `owner` doğru eksen DEĞİL. Canlı ölçüm: 24 kaydın 15'inde
  `owner = "Administrator"` (seed/onay akışı) ama `user` gerçek kişi. `if_owner=1`
  yapmak bu 15 kullanıcının kendi kaydına erişimini KIRARDI. Doğru eksen `user`
  link alanı — ve onu 1. parçadaki has_permission/query_conditions uygular;
  `if_owner`'dan daha güçlüdür (owner yeniden atanabilir, `user` link'i şemadır).

Bu patch'in yaptığı daraltma:
  - `export`: 1 → 0. Ölü + riskli grant: `report=0` olduğu için satıcı zaten
    rapor görünümüne giremiyor, ama `export` bir PII doctype'ında satıcı rolüne
    duran bir yetki bırakıyordu. Kaldırıldı.
  - `create/delete/submit/cancel/amend/import/share/print/email/report`: 0'a
    sabitlendi (bugün de 0'lar; patch bunu invariant hâline getiriyor ki ileride
    bir "union" patch'i sessizce açamasın).
  - `read/write`: 1 KALIYOR (meşru panel akışı), artık kendi kaydıyla sınırlı.

İdempotent: yalnız farklı olan bayrağı yazar, ikinci koşumda no-op döner.
"""

from __future__ import annotations

import frappe

_DOCTYPE = "KYC Verification"
_ROLE = "Seller Owner"

# Kalması gereken bayraklar (meşru panel akışı) — has_permission kancası
# bunları kendi kaydına daraltır.
_KEEP = {"read": 1, "write": 1}

# Sıfıra sabitlenen bayraklar. `export` bugün 1; gerisi zaten 0 ama invariant
# olarak yazılıyor.
_DENY = {
	"create": 0,
	"delete": 0,
	"submit": 0,
	"cancel": 0,
	"amend": 0,
	"report": 0,
	"export": 0,
	"import": 0,
	"share": 0,
	"print": 0,
	"email": 0,
	"if_owner": 0,
}


def _isolation_hooks_registered() -> dict:
	"""1. parçanın gerçekten yüklü olduğunu doğrula.

	Bu patch tek başına yeterli DEĞİL — daraltma savunma derinliği, asıl kapı
	hook'lar. Hook yoksa sessizce geçmek v15_8_3'ün hatasını tekrarlamak olur;
	o yüzden görünür bir hata kaydı bırakıyoruz.
	"""
	hooks = frappe.get_hooks()
	pqc = (hooks.get("permission_query_conditions") or {}).get(_DOCTYPE)
	hp = (hooks.get("has_permission") or {}).get(_DOCTYPE)
	state = {"permission_query_conditions": bool(pqc), "has_permission": bool(hp)}
	if not (pqc and hp):
		frappe.log_error(
			title="KYC izolasyon kancası eksik",
			message=(
				f"{_DOCTYPE} için permission_query_conditions/has_permission kaydı "
				f"bulunamadı: {state}. v15_9_24 daraltması tek başına kiracı "
				"izolasyonu SAĞLAMAZ — hooks.py kaydı geri konmalı."
			),
		)
	return state


def execute() -> dict:
	result = {"hooks": _isolation_hooks_registered(), "changed": {}, "row": None}

	if not frappe.db.exists("DocType", _DOCTYPE) or not frappe.db.exists("Role", _ROLE):
		result["skipped"] = "missing_doctype_or_role"
		return result

	name = frappe.db.exists("Custom DocPerm", {"parent": _DOCTYPE, "role": _ROLE, "permlevel": 0})
	if not name:
		# Satır yoksa daraltılacak bir şey de yok. YENİ satır AÇMIYORUZ —
		# bu patch bir hardening patch'i, erişim genişletmez.
		result["skipped"] = "no_docperm_row"
		return result

	row = frappe.get_doc("Custom DocPerm", name)
	for field, want in {**_KEEP, **_DENY}.items():
		if int(row.get(field) or 0) != want:
			result["changed"][field] = {"from": int(row.get(field) or 0), "to": want}
			row.set(field, want)

	if result["changed"]:
		row.save(ignore_permissions=True)
		frappe.clear_cache(doctype=_DOCTYPE)
		frappe.db.commit()

	result["row"] = {f: int(row.get(f) or 0) for f in ({**_KEEP, **_DENY})}
	return result
