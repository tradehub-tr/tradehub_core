"""T-134 §2 — servis-config sır okumalarının ortak denetim yardımcısı.

ŞARTNAME (docs/71-faz13-guvenlik-observability.html, T-134 kabul kriteri 2):
"sır erişimi (`get_password` çağrısı)" audit'e yazılır.

Bugün YALNIZ `api/v1/logistics_admin._log_secret_access` (kullanıcı-tetikli
`reveal_carrier_secret`) denetimliydi. Servis-config sırları — OpenAI/DeepL API
anahtarı, VAPID özel anahtarı, S3/imgproxy anahtarları, API Application
client_secret — `get_password` ile okunuyor ama iz bırakmıyordu (rapor 92 §3).

Bu yardımcı o çağrıları TEK ortak desenle denetime bağlar. `logistics_admin`in
private `_log_secret_access`i (capability + tenant taşıyan, kullanıcı-tetikli
reveal) OLDUĞU GİBİ bırakıldı — o dosya bu görevin dokunulabilir listesinde
değil ve anlamı farklı (HIGH, tenant-scoped). Burası düşük gürültülü sistem
okuması: NORMAL severity.

KVKK/güvenlik maskesi (logistics deseniyle aynı): sır DEĞERİ ve tam URL asla
denetim satırına girmez — yalnız HANGİ servis, HANGİ alan, KİM, NE ZAMAN.
"""

from __future__ import annotations

import frappe


def log_secret_access(
	*,
	service: str,
	field: str,
	object_doctype: str | None = None,
	object_name: str | None = None,
	tenant: str | None = None,
) -> None:
	"""Bir servis-config sırrının okunduğunu Authorization Decision Log'a yazar.

	Best-effort: denetim yazımı patlasa bile çağıran iş akışı (çeviri, push,
	moderasyon, API auth) DEVAM eder — `log_decision`ın kendisi de best-effort'tur.

	Args:
	    service: "openai" / "deepl" / "vapid" / "s3" / "imgproxy" / "api_application".
	    field: Okunan Password alanının adı (değeri DEĞİL).
	    object_doctype/object_name: Sırrı taşıyan ayar/kayıt (ör. "Translation
	        Settings"). Kimlik burada; sır değeri hiçbir yerde.
	    tenant: Varsa satıcı `Admin Seller Profile` adı.
	"""
	try:
		from tradehub_core.audit import log as audit

		audit.log_decision(
			actor=frappe.session.user if hasattr(frappe, "session") else None,
			action="config.secret_access",
			decision=audit.DECISION_ALLOW,
			layer=audit.LAYER_L3,
			object_doctype=object_doctype,
			object_name=object_name,
			tenant=tenant,
			rule_id="t134.secret_access",
			# Kullanıcı-tetikli reveal DEĞİL — sistem servis-config okuması. HIGH
			# yerine NORMAL: her push/çeviri/API-auth çağrısında HIGH satır basmak
			# severity filtresini işe yaramaz hâle getirirdi (media.scan/settings
			# için verilen kararın aynısı).
			severity=audit.SEVERITY_NORMAL,
			context={"service": service, "field": field},
		)
	except Exception:  # noqa: BLE001 — denetim hatası iş akışını bozmaz
		try:
			frappe.log_error(
				f"Sır erişim kaydı yazılamadı: {service}/{field}",
				"audit.secret_access",
			)
		except Exception:
			pass
