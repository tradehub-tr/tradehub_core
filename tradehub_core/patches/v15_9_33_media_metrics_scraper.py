# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-133 (Şerit A) — Prometheus scrape kimliği: rol + yetkisiz servis kullanıcısı.

NEDEN BİR KULLANICI GEREKİYOR — ÖLÇÜLDÜ (canlı HTTP, 2026-08-19)
----------------------------------------------------------------
`/metrics` ucu bearer token ile korunuyor, ama Frappe'nin `validate_auth`ı
iki parçalı bir `Authorization` başlığı görüp de bir KULLANICI atanmamışsa
isteği fonksiyona hiç ulaştırmadan 401 ile kesiyor:

    if len(authorization_header) == 2 and frappe.session.user in ("", "Guest"):
        raise frappe.AuthenticationError

Ölçüm: tokensız istek 403 (uç kendi kapısından), YANLIŞ token 401 (Frappe'nin
kapısından) — ve doğru token da 401 alıyordu. `auth_hooks` kancası tokeni bu
kullanıcıya çeviriyor.

BU KULLANICI NE YAPABİLİR — kasten ÇOK AZ
-----------------------------------------
* `user_type = "Website User"` → desk yok.
* Tek rolü `Media Metrics Scraper` ve o rolün HİÇBİR DocType'ta DocPerm satırı
  YOK (bu yama da eklemiyor). Yani oturum açmış olmak hiçbir kayda erişim
  vermiyor.
* Parola atanmıyor ve `new_password` yazılmıyor: bu hesaba parolayla
  girilemez. TEK kimlik kanıtı `site_config.media_metrics_token`.
* `/metrics` erişimi role DEĞİL token'ın kendisine bağlı (`_token_ok`), yani
  bu rolü birine vermek metrik okutmaz.

Idempotent: var olan rolü/kullanıcıyı DEĞİŞTİRMEZ — operatör kullanıcıyı
devre dışı bırakmışsa bir `migrate` onu geri açmamalı.
"""

from __future__ import annotations

import frappe

ROL: str = "Media Metrics Scraper"
KULLANICI: str = "media-metrics@tradehub.local"


def execute() -> dict:
	rol_yaratildi = _rolu_kur()
	kullanici_yaratildi = _kullaniciyi_kur()
	frappe.db.commit()
	return {
		"role": ROL,
		"role_created": rol_yaratildi,
		"user": KULLANICI,
		"user_created": kullanici_yaratildi,
	}


def _rolu_kur() -> bool:
	if frappe.db.exists("Role", ROL):
		return False
	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": ROL,
			# Desk erişimi YOK: bu rol bir insan için değil.
			"desk_access": 0,
			"is_custom": 1,
		}
	).insert(ignore_permissions=True)
	return True


def _kullaniciyi_kur() -> bool:
	"""Servis kullanıcısı. Var olanı DEĞİŞTİRMEZ (devre dışı bırakılmış olabilir)."""
	if frappe.db.exists("User", KULLANICI):
		return False
	kullanici = frappe.get_doc(
		{
			"doctype": "User",
			"email": KULLANICI,
			"first_name": "Media Metrics",
			"last_name": "Scraper",
			"user_type": "Website User",
			"send_welcome_email": 0,
			"enabled": 1,
		}
	)
	# `ignore_permissions`: yama Administrator olmayan bir bağlamda da koşabilir
	# ve bu kullanıcı bir kullanıcı girdisinden DEĞİL, sabit bir sistem
	# kimliğinden yaratılıyor.
	kullanici.insert(ignore_permissions=True)
	kullanici.add_roles(ROL)
	return True
