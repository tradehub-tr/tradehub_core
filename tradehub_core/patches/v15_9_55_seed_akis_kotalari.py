"""MOGEM-620 §18 — akış tipi medya kotalarını planlara seed.

`v15_9_17_seed_storage_quota` ile BİREBİR aynı desen ve aynı kademe mantığı;
farkı üç yeni anahtar:

    quota.max_bandwidth_mb_per_month
    quota.max_transformations_per_month
    quota.max_ai_calls_per_month

SEMANTİK (`entitlement.core.within_quota` ve `media/meter.py` ile aynı):
    -1 sınırsız · 0 devre dışı · >0 gerçek sınır · tanımsız → UYGULANMAZ

NEDEN `v15_9_17`'DEN FARKLI OLARAK FAIL-OPEN
--------------------------------------------
Depolama kotasında tanımsız değer `within_quota`'da deny üretiyordu ve o
yüzden seed'in koşması KRİTİKTİ. Burada `meter.check` tanımsızı açıkça
"unconfigured → allowed" sayıyor. Yani bu yama koşmazsa üç kota
UYGULANMAZ — kimse engellenmez. Bilinçli: yeni bir kotanın ilk etkisi
"herkesin işi durdu" olmamalı.

KADEME DEĞERLERİ NEREDEN
------------------------
Ölçüme dayanıyor, uydurma değil:
  * Bant genişliği: katalog bugün 4.804 görsel · ~9 MB video fixture
    (rapor 113 envanteri). Pro kademesi için 500 GB/ay, ortalama bir
    satıcının aylık trafiğinin ~50 katı — kota bir tavan, bir hedef değil.
  * Dönüşüm: bir görsel slot başına en çok 6 türev üretiyor
    (`company-cover-video.json` K7 ölçümü). Pro'da 50.000 dönüşüm ≈ 8.000
    yeni görsel/ay.
  * AI çağrısı: bugün tek tüketici yorum görseli moderasyonu
    (`api/moderation.py`). Free'de 100/ay, o akışı kapatmadan maliyeti
    sınırlıyor.

Idempotent: anahtar zaten tanımlıysa DOKUNULMAZ (admin override'ları ezilmez).
"""

from __future__ import annotations

import json

import frappe

_UNLIMITED = -1

#: `{anahtar: {kademe: değer}}`. Kademe eşleşmesi `v15_9_17` ile aynı:
#: plan adında alt dize araması, case-insensitive.
_HEDEFLER: dict[str, dict[str, int]] = {
	"quota.max_bandwidth_mb_per_month": {
		"enterprise": _UNLIMITED,
		"pro": 500_000,
		"premium": 500_000,
		"starter": 100_000,
		"_": 20_000,
	},
	"quota.max_transformations_per_month": {
		"enterprise": _UNLIMITED,
		"pro": 50_000,
		"premium": 50_000,
		"starter": 10_000,
		"_": 2_000,
	},
	"quota.max_ai_calls_per_month": {
		"enterprise": _UNLIMITED,
		"pro": 5_000,
		"premium": 5_000,
		"starter": 1_000,
		"_": 100,
	},
}

#: Kademe eşleşme sırası — "pro" ile "premium" ayrı ama "enterprise" önce
#: denenmeli, aksi hâlde "enterprise-pro" gibi bir plan adı "pro"ya düşerdi.
_SIRA: tuple[str, ...] = ("enterprise", "premium", "pro", "starter")


def _default_for_plan(plan_name: str, kademeler: dict[str, int]) -> int:
	lname = (plan_name or "").lower()
	for token in _SIRA:
		if token in lname and token in kademeler:
			return kademeler[token]
	return kademeler["_"]


def execute() -> dict:
	plans = frappe.get_all("Subscription Plan", fields=["name", "quota_limits"])
	updated: list[str] = []
	skipped: list[str] = []

	for p in plans:
		raw = p.get("quota_limits")
		try:
			quotas = json.loads(raw) if isinstance(raw, str) else (raw or {})
		except (ValueError, TypeError):
			continue
		if not isinstance(quotas, dict):
			continue

		degisti = False
		for anahtar, kademeler in _HEDEFLER.items():
			if anahtar in quotas:
				continue
			quotas[anahtar] = _default_for_plan(p["name"], kademeler)
			degisti = True

		if not degisti:
			skipped.append(p["name"])
			continue

		frappe.db.set_value(
			"Subscription Plan",
			p["name"],
			"quota_limits",
			json.dumps(quotas, sort_keys=True, ensure_ascii=False),
			update_modified=False,
		)
		updated.append(p["name"])

	frappe.db.commit()

	# `v15_9_17` ile aynı gerekçe: cache temizlenmezse yeni kotalar 5 dakika
	# boyunca görünmez ve `meter.limit_for` `None` dönmeye devam eder.
	try:
		frappe.cache().delete_keys("tradehub:entitlement:")
	except Exception:
		frappe.log_error("entitlement cache flush failed", "v15_9_55_seed_akis_kotalari")

	return {"updated": updated, "skipped_already_set": skipped}
