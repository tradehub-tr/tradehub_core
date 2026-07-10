"""Faz 5 — Shadow-mode gözlem: gerçek istek path'inde RBAC kararını ReBAC ile
karşılaştırıp 'shadow divergence' loglar.

ENFORCE ETMEZ — yalnız enforce ÖNCESİ burn-in verisi toplar (Carta/Figma geçiş
dersi: sapmayı 0'a indir, sonra doctype-başına enforce aç).

Güvenlik sözleşmesi (enterprise, 0 regresyon):
  - Config flag `rebac_shadow_observe` KAPALI iken TAM no-op → merge zero-impact.
  - Kararı/isteği ASLA değiştirmez, ASLA exception fırlatmaz (fail-safe).
  - `frappe.has_permission` ÇAĞIRMAZ → `has_permission` handler'ından çağrılabilir
    (recursion YOK); `pdp._rebac_reconcile` (doğrudan `rebac_client.check` +
    divergence log) kullanılır.
  - Örnekleme `rebac_shadow_sample` (varsayılan 1 = her çağrı; N = ~1/N) ile
    hot-path OpenFGA çağrı hacmi sınırlanır.

Açma (burn-in):
    bench --site <site> set-config rebac_shadow_observe true
    bench --site <site> set-config rebac_shadow_sample 20    # ~%5 örnekle
Divergence trendi: Error Log title=`rebac.shadow_divergence` (grep/dashboard).
"""

from __future__ import annotations

import random

import frappe


def observe(user: str, doctype: str, name: str | None, ptype: str, rbac_allow: bool) -> None:
	"""RBAC kararını (rbac_allow) ReBAC ile karşılaştır + sapma logla. No-op/fail-safe.

	Args:
	    user: karar verilen kullanıcı.
	    doctype: DocType (yalnız ReBAC-modellenmiş tipler değerlendirilir).
	    name: doküman adı (yoksa gözlem atlanır).
	    ptype: izin tipi (read/write/...) — ReBAC relation'a registry map'ler.
	    rbac_allow: gerçek RBAC kararı (handler'ın döndürdüğü sonuç).
	"""
	try:
		if not name or not doctype:
			return
		conf = getattr(frappe, "conf", None)
		if not conf or not conf.get("rebac_shadow_observe"):
			return  # flag kapalı → tam no-op
		sample = int(conf.get("rebac_shadow_sample") or 1)
		if sample > 1 and random.randint(1, sample) != 1:
			return  # örnekleme dışı
		from tradehub_core.authz import pdp

		# _rebac_reconcile: fail-safe, non-recursive; rbac!=rebac ise divergence loglar.
		# Dönüş değeri shadow'da KULLANILMAZ (karar değişmez).
		pdp._rebac_reconcile(user, (ptype or "read").lower(), doctype, name, bool(rbac_allow), {})
	except Exception:  # noqa: BLE001 — gözlem asla kararı/isteği bozmaz
		pass
