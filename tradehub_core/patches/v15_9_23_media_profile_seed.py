# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""DALGA A / K-1 — `Media Profile` kayıtlarını slot politikalarından tohumla.

`tabMedia Profile` bugüne kadar **0 satır**dı: DocType A1a'da kuruldu ama
tohumlama kodu hiç yazılmadı. `media/pipeline_bridge._generate` profil
bulamayınca `frappe.log_error` yazıp **0 türev** üretiyor — yani bayrak açılsa
bile hattın son halkası boşta dönüyordu (docs/reports/15-dalga-a-dogrulama.md
§K-1).

HAKİKAT KAYNAĞI
---------------
`tradehub_core/media/pipeline/policy/slots/*.json` dosyalarındaki `profiles[]`
blokları. Dosyalar elle AÇILMAZ; `policy/engine.py` içindeki `PolicyRegistry`
okur — `slot_key` çakışması, eksik anahtar gibi kontroller orada zaten var ve
burada kopyalanmamalı.

ADLANDIRMA (K-2 ile aynı sözleşme)
----------------------------------
    docname / profile_key = "{slot_key}:{policy_profile}"   ör. product.image:w384
    policy_profile        = "w384"                          politikadaki ham ad

`Media Profile.autoname = field:profile_key`, yani docname GLOBAL tekil olmak
zorunda; politika profil adları ise slotlar arası çakışıyor (`w64`, `w128`,
`w256`, `w512`, `og1200x630` hem `brand.logo` hem `seller.logo` politikasında
var). Tekilliği slot öneki sağlar. Manifest kütüphanesinin beklediği HAM ad
ayrı kolonda (`policy_profile`) durur ve `Media Rendition.profile` kolonuna o
yazılır.

İDEMPOTENTLİK
-------------
1. Kayıt VARSA yeniden açılmaz — `profile_key` deterministik olduğu için ikinci
   koşum kayıt ÇOĞALTMAZ.
2. Politikadan gelen alanlar (geometri, biçim, kalite) her koşumda güncellenir:
   politika değişirse reçete de değişmeli.
3. `enabled` YALNIZ ilk açılışta yazılır. Operatörün elle kapattığı bir profili
   migrate geri açmamalı; idempotentlik "aynı sonuç" demektir, "elle yapılanı
   sil" demek değil.

Politikada olmayan bir alan (ör. `generation`) UYDURULMAZ: DocType varsayılanı
neyse o kalır.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from tradehub_core.media.pipeline.policy.engine import PolicyRegistry

#: Docname biçimi — bkz. modül başlığı "ADLANDIRMA".
_KEY_FORMAT: str = "{slot}:{name}"

#: Operatörün elindeki alanlar: ilk açılıştan sonra patch bunlara DOKUNMAZ.
_OPERATOR_OWNED: frozenset[str] = frozenset({"enabled"})

#: DocType'ta `JSON` tipli alanlar. Karşılaştırma metin üzerinden yapılamaz:
#: aynı liste `"[96]"` ya da `[96]` olarak dönebiliyor.
_JSON_FIELDS: frozenset[str] = frozenset({"widths", "formats"})

#: `Media Profile.label` alan uzunluğu.
_LABEL_MAX: int = 100


def execute() -> dict[str, int]:
	"""Her slot politikasının her profilini `Media Profile` olarak upsert eder."""
	# Yeni `policy_profile` alanı bu patch'ten önce senkronlanmamış olabilir.
	frappe.reload_doc("tradehub_core", "doctype", "media_profile", force=True)

	registry = PolicyRegistry()
	sayac = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
	for slot in registry.keys():
		for ham in registry.get(slot).get("profiles") or ():
			alanlar = _profile_fields(slot, ham)
			if alanlar is None:
				sayac["skipped"] += 1
				continue
			sayac[_upsert(alanlar)] += 1

	frappe.db.commit()
	return sayac


def _profile_fields(slot: str, ham: dict[str, Any]) -> dict[str, Any] | None:
	"""Politika profilini DocType alanlarına çevirir; reçete değilse `None`.

	Adı, pozitif genişliği ya da biçimi olmayan bir girdi türev üretemez;
	eksiği tamamlamak yerine atlanır (sayaçta `skipped` olarak görünür).
	"""
	ad = str(ham.get("name") or "").strip()
	genislik = ham.get("width")
	bicimler = [str(f) for f in (ham.get("formats") or ()) if f]
	if not ad or not isinstance(genislik, int) or genislik <= 0 or not bicimler:
		return None

	alanlar: dict[str, Any] = {
		"profile_key": _KEY_FORMAT.format(slot=slot, name=ad),
		"policy_profile": ad,
		"label": f"{slot} {ad}"[:_LABEL_MAX],
		"slot_key": slot,
		"widths": [genislik],
		"formats": bicimler,
	}
	# Politikada olmayan alan yazılmaz — DocType varsayılanı kalır.
	fit = str(ham.get("fit") or "").strip()
	if fit:
		alanlar["fit"] = fit
	oran = str(ham.get("target_ratio") or "").strip()
	if oran:
		alanlar["aspect_ratio"] = oran
	kalite = _quality_target(ham, bicimler)
	if kalite is not None:
		alanlar["quality_target"] = kalite
	return alanlar


def _quality_target(ham: dict[str, Any], bicimler: list[str]) -> int | None:
	"""`encoder_quality` bloğundan tek tam sayı hedef çıkarır; yoksa `None`.

	Blok biçim başına değer taşıyor (`{"avif": null, "webp": 80}`), DocType ise
	tek `quality_target` tutuyor: tercih sırasındaki İLK tam sayı kazanır.
	`null` (kodlayıcı varsayılanı) ve `"lossless"` sayı değildir; hiçbiri sayı
	değilse alan doldurulmaz — 0 yazmak "kalite sıfır" ile "hedef yok"u
	karıştırırdı.
	"""
	blok = ham.get("encoder_quality")
	if not isinstance(blok, dict):
		return None
	for bicim in bicimler:
		deger = blok.get(bicim)
		# `bool` de `int`tir; kalite hedefi olarak anlamsız.
		if isinstance(deger, int) and not isinstance(deger, bool) and deger > 0:
			return deger
	return None


def _upsert(alanlar: dict[str, Any]) -> str:
	"""Kaydı açar ya da politikadan gelen alanlarını günceller.

	Dönüş: `"created"` | `"updated"` | `"unchanged"` — çağıran sayaç tutar.
	"""
	profile_key = alanlar["profile_key"]
	if not frappe.db.exists("Media Profile", profile_key):
		yeni = {alan: _stored(alan, deger) for alan, deger in alanlar.items()}
		yeni.update({"doctype": "Media Profile", "enabled": 1})
		# Sistem migration'ı — kullanıcı akışı değil.
		frappe.get_doc(yeni).insert(ignore_permissions=True)
		return "created"

	doc = frappe.get_doc("Media Profile", profile_key)
	degisti = False
	for alan, deger in alanlar.items():
		if alan == "profile_key" or alan in _OPERATOR_OWNED:
			continue
		mevcut = _as_list(doc.get(alan)) if alan in _JSON_FIELDS else doc.get(alan)
		if mevcut == deger:
			continue
		doc.set(alan, _stored(alan, deger))
		degisti = True
	if not degisti:
		return "unchanged"
	doc.save(ignore_permissions=True)
	return "updated"


def _stored(alan: str, deger: Any) -> Any:
	"""JSON alanlarını metne çevirir; diğerlerini olduğu gibi bırakır."""
	return json.dumps(deger) if alan in _JSON_FIELDS else deger


def _as_list(deger: Any) -> list:
	"""JSON alanının metin ya da liste hâlini tek biçime indirger."""
	if isinstance(deger, list):
		return deger
	if not deger:
		return []
	try:
		cozulen = json.loads(deger)
	except (json.JSONDecodeError, TypeError):
		return []
	return cozulen if isinstance(cozulen, list) else []
