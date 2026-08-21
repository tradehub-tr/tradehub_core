#!/usr/bin/env python3
# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""`docs/api/openapi-http.yaml` üreticisi — GERÇEK HTTP yüzeyi (Faz 8 / T-085).

NEDEN İKİNCİ BİR BELGE
======================
`docs/api/openapi.yaml` `tradehub_core/media/pipeline/api/spec.py` tarafından
üretilir ve **saf Python** kütüphane katmanını (`UploadApi`, `CropApi`,
`DeliveryApi`, `AdminApi`) anlatır. O katman `@frappe.whitelist()` TAŞIMAZ
(`pipeline/api/crop.py` başlığı bunu açıkça söyler), `ApiResponse` döndürür ve
belgedeki `/api/media/v1/...` yolları için hiçbir yönlendirme kuralı YOKTUR —
ölçüldü: depoda `media/v1` dizgisi `pipeline/api/` ve `docs/api/` dışında hiç
geçmiyor. Yani o belge bir **kütüphane sözleşmesidir**, HTTP yüzeyi değil.

Bugün HTTP üzerinden gerçekten çağrılabilen medya uçları başka dosyalarda ve
başka adreslerde duruyor: `/api/method/<noktalı.yol>`. Bu betik onları
**koddan** çıkarır ve ayrı bir OpenAPI belgesine basar. İki katman bilerek
AYRI iki dosyada tutulur; tek belgede birleştirmek "bu adrese istek atabilirim"
yanılgısını üretirdi.

    openapi.yaml        → kütüphane sözleşmesi, whitelist YOK, yol YOK
    openapi-http.yaml   → gerçek whitelist uçları, /api/method/… , ÖLÇÜLDÜ

NASIL ÇALIŞIR — `import frappe` YOK
===================================
Kaynak dosyalar `ast` ile ayrıştırılır. `frappe` import edilmez; betik
bench dışında, site olmadan koşar (`test_api_contracts.py` ile aynı disiplin).
Bu aynı zamanda bir doğrulamadır: imza, `allow_guest`, `methods` ve yetki
kapısı **dosyadan** okunur, elle yazılmış bir tabloya güvenilmez.

Elle yazılan tek şey `ANLATIM` sözlüğüdür: ölçülmüş yanıt şemaları ve
uzun açıklamalar. Oradaki her anahtar koddaki bir uca karşılık gelmek
ZORUNDADIR — karşılığı olmayan anahtar betiği düşürür (`--check`).

Koşum:

    python3 scripts/gen_http_openapi.py            # üret + yaz
    python3 scripts/gen_http_openapi.py --check    # sapma var mı (yazmaz)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

KOK = Path(__file__).resolve().parents[1]
CIKTI = KOK / "docs" / "api" / "openapi-http.yaml"

API_VERSION = "1.0.0"
OPENAPI_VERSION = "3.1.0"

#: Taranan kaynaklar — (dosya yolu, noktalı modül adı, etiket).
KAYNAKLAR: tuple[tuple[str, str, str], ...] = (
	("tradehub_core/api/media_manifest.py", "tradehub_core.api.media_manifest", "delivery"),
	("tradehub_core/api/media_access.py", "tradehub_core.api.media_access", "delivery"),
	("tradehub_core/api/media_crop.py", "tradehub_core.api.media_crop", "crop"),
	("tradehub_core/api/seller_media.py", "tradehub_core.api.seller_media", "seller"),
	("tradehub_core/api/media_admin.py", "tradehub_core.api.media_admin", "admin"),
	# T-123 — RUM toplama ucu. Ayrı dosya, ayrı etiket: telemetri yazma ucu
	# medya CRUD'u değildir; misafire açık TEK yazma ucu olduğu görünür kalsın.
	("tradehub_core/api/rum.py", "tradehub_core.api.rum", "rum"),
	(
		"tradehub_core/tradehub_core/doctype/media_storage_settings/media_storage_settings.py",
		"tradehub_core.tradehub_core.doctype.media_storage_settings.media_storage_settings",
		"storage",
	),
)

#: Gövdede aranan yetki kapıları → sözleşmede yazılacak cümle.
#: Anahtar, çağrının `ast.unparse` çıktısının ÖNEKİDİR.
KAPILAR: tuple[tuple[str, str], ...] = (
	("_guard_destructive(", "Rol: System Manager (yıkıcı işlem). Ret denetime yazılır."),
	("_guard(", "Rol: System Manager veya Marketplace Admin. Ret denetime yazılır."),
	("_require_superadmin(", "Rol: Media Superadmin veya System Manager + DocType izni."),
	("_store(", "Oturumdan mağaza çözülür; mağazasız oturum reddedilir (`PermissionError`)."),
	(
		"_principal(",
		"Oturum → `env.Principal`; kütüphane `require_auth` + `same_store` uygular "
		"(başka mağazanın varlığı 'bulunamadı' ile döner, varlığı SIZMAZ).",
	),
	("ownership.assert_owns(", "Dosyanın çağıranın mağazasına ait olduğu doğrulanır."),
	("frappe.only_for(", "Frappe rol kapısı (`frappe.only_for`)."),
	("_owns_listing(", "İlan sahipliği ayrıca doğrulanır (ikinci katman)."),
)

#: Frappe'nin `@frappe.whitelist()` varsayılanı: GET ve POST birlikte açıktır.
VARSAYILAN_YONTEMLER: tuple[str, ...] = ("GET", "POST")


# ═══════════════════════════════════════════════════════════════════════
# 1. Koddan envanter
# ═══════════════════════════════════════════════════════════════════════


def _cagrilar(node: ast.AST) -> list[str]:
	"""Fonksiyon gövdesindeki tüm çağrıların `ast.unparse` metni."""
	return [ast.unparse(n.func) + "(" for n in ast.walk(node) if isinstance(n, ast.Call)]


def _kapilar(node: ast.AST, allow_guest: bool) -> list[str]:
	"""Uçta gerçekten çağrılan yetki kapıları — koddan, tahminden değil."""
	metin = "\n".join(_cagrilar(node))
	bulunan = [cumle for onek, cumle in KAPILAR if onek in metin]
	kaynak = ast.unparse(node)
	if "frappe.session.user" in kaynak and "Guest" in kaynak:
		bulunan.append("Gövdede ayrıca açık misafir kontrolü var.")
	if not allow_guest:
		bulunan.insert(0, "Oturum zorunlu (`allow_guest` YOK) — misafir 403 alır.")
	else:
		bulunan.insert(0, "Misafire AÇIK (`allow_guest=True`).")
	return bulunan


def _ozet(node: ast.FunctionDef) -> str:
	"""Docstring'in ilk satırı — belgedeki `summary`."""
	ds = ast.get_docstring(node) or ""
	return ds.strip().split("\n")[0].strip() or node.name


def envanter() -> list[dict[str, Any]]:
	"""Tüm kaynaklardaki `@frappe.whitelist()` uçları — sıralı, deterministik."""
	cikti: list[dict[str, Any]] = []
	for goreli, modul, etiket in KAYNAKLAR:
		yol = KOK / goreli
		agac = ast.parse(yol.read_text(encoding="utf-8"))
		for node in agac.body:
			if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
				continue
			wl = None
			susleyiciler: list[str] = []
			for d in node.decorator_list:
				hedef = d.func if isinstance(d, ast.Call) else d
				ad = ast.unparse(hedef)
				if ad == "frappe.whitelist":
					wl = {"allow_guest": False, "methods": None}
					if isinstance(d, ast.Call):
						for kw in d.keywords:
							if kw.arg == "allow_guest":
								wl["allow_guest"] = bool(ast.literal_eval(kw.value))
							elif kw.arg == "methods":
								wl["methods"] = list(ast.literal_eval(kw.value))
				else:
					susleyiciler.append(ast.unparse(d))
			if wl is None:
				continue

			args = node.args
			# `zip` yerine indeks: `zip(strict=…)` Python 3.10+ ister, bu betik
			# 3.9 yorumlayıcıda da koşabilmeli (yerel geliştirme ortamı 3.9.6).
			varsayilanlar = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)
			params = []
			for sira, a in enumerate(args.args):
				d = varsayilanlar[sira]
				params.append(
					{
						"name": a.arg,
						"type": ast.unparse(a.annotation) if a.annotation else "",
						"default": ast.unparse(d) if d is not None else None,
					}
				)
			cikti.append(
				{
					"key": f"{modul}.{node.name}",
					"module": modul,
					"fn": node.name,
					"tag": etiket,
					"file": goreli,
					"line": node.lineno,
					"allow_guest": wl["allow_guest"],
					"methods": tuple(wl["methods"] or VARSAYILAN_YONTEMLER),
					"decorators": susleyiciler,
					"returns": ast.unparse(node.returns) if node.returns else "",
					"params": params,
					"summary": _ozet(node),
					"gates": _kapilar(node, wl["allow_guest"]),
				}
			)
	return cikti


# ═══════════════════════════════════════════════════════════════════════
# 2. Elle yazılan anlatım — YALNIZ ölçülmüş uçlar
# ═══════════════════════════════════════════════════════════════════════

#: `x-measured` değerleri:
#:   "http"    → bu belge yazılırken gerçek HTTP çağrısıyla doğrulandı
#:   "http-fail" → çağrıldı, sözleşmeyi KARŞILAMADI (gerekçe `x-mismatch`)
#:   yok       → yalnız koddan çıkarıldı, HTTP ile denenmedi
ANLATIM: dict[str, dict[str, Any]] = {
	"tradehub_core.api.media_manifest.get_manifest": {
		"description": (
			"Tek ilanın teslim manifesti. `Media Engine Settings.manifest_api_enabled` "
			"bayrağı KAPALIYKEN de 200 döner: `enabled=false`, `renditions=[]` ve "
			"`fallback` alanında ham `file_url`. Uç hiçbir durumda istisna fırlatmaz — "
			"bir manifest hatası vitrini kırmamalıdır. Bulunamayan ilan ile "
			"yayınlanmamış ilan AYIRT EDİLMEZ (yayın takvimi sızmasın)."
		),
		"x-measured": "http",
		"x-measurement": (
			"2026-08-19, misafir, bayrak KAPALI: LST-00560 → 200, 908 B, "
			"`enabled=false`, 7 görsel, `fallback=/files/191-ff0258.jpg`, ETag var."
		),
		"schema": "Manifest",
	},
	"tradehub_core.api.media_manifest.get_manifest_batch": {
		"description": (
			"Çok ilan tek istek. `listings` JSON dizisi ya da virgüllü liste kabul "
			"eder (GET üzerinden geldiği için dizge). `max_batch` (50) üstü "
			"REDDEDİLMEZ, kırpılır ve kırpılanlar `skipped` içinde geri verilir. "
			"`missing` DAİMA boştur: misafire hangi kimliğin gerçek olduğunu söylemek "
			"numaralandırma kehanetidir."
		),
		"x-measured": "http",
		"x-measurement": (
			"2026-08-19, misafir: `[\"LST-00560\",\"LST-YOK-9999\"]` → 200, "
			"`requested=2`, `returned=1`, `missing=[]`, `truncated=false`, "
			"`max_batch=50`. Virgüllü biçim de aynı gövdeyi verdi."
		),
		"schema": "ManifestBatch",
	},
	"tradehub_core.api.media_manifest.get_signed_url": {
		"description": (
			"`media_access.get_signed_url`e devreder ve yanıta `cache_control: "
			"private, no-store` ekler. Kripto burada yazılmaz. Guest çağıramaz; "
			"whitelist bayrağı gevşetilse bile gövdede ikinci bir oturum kontrolü var."
		),
		"x-measured": "http",
		"x-measurement": (
			"2026-08-19: misafir → 403 `PermissionError`. Administrator → 200, "
			"`url`+`exp`+`ttl_seconds=900`+`cache_control=private, no-store`."
		),
		"schema": "SignedUrlCached",
	},
	"tradehub_core.api.media_access.get_signed_url": {
		"description": (
			"Süreli imzalı indirme adresi üretir (`frappe.utils.verified_command`, "
			"site secret + HMAC-SHA512). İmzaya `file`, `exp` ve — satırın "
			"`content_hash`'i varsa — `blob` girer. Yetkisiz kullanıcı için imza "
			"ÜRETİLMEZ: `File.has_permission(\"read\")` ve `blob_matches_row` "
			"kapılarının ikisi de geçilmelidir; her ret denetime yazılır."
		),
		"x-measured": "http",
		"x-measurement": (
			"2026-08-19: misafir → 403. Administrator → 200, `ttl_seconds=900`, "
			"üretilen adres `blob=` ve `_signature=` taşıyor."
		),
		"schema": "SignedUrl",
	},
	"tradehub_core.api.media_access.download": {
		"description": (
			"İmzalı adresle private dosya indirir — OTURUM GEREKMEZ. Parametreler "
			"gövdeden değil `frappe.form_dict`ten okunur (`file`, `exp`, `blob`, "
			"`_signature`). Sıra: imza → yol → süre → yol (2. kez) → blob bağı → "
			"servis. Her ret denetime yazılır. BAŞARIDA gövde JSON DEĞİLDİR: dosyanın "
			"kendisi döner. REDDE Frappe'nin HTML hata sayfası döner, JSON zarf değil."
		),
		"x-measured": "http",
		"x-measurement": (
			"2026-08-19: geçerli imza + oturumsuz → 200, 634.926 B, "
			"`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`. "
			"İmza bozuldu → 403; `blob` bozuldu → 403; `exp` geçmişe çekildi → 403; "
			"imzasız çağrı → 403. Dördü de HTML `Geçersiz Bağlantı` sayfası."
		),
		"schema": None,
	},
	"tradehub_core.api.seller_media.browse_my_media": {
		"description": (
			"Satıcının KENDİ medyası, sanal klasör ağacında tek seviye. `store` "
			"parametresi YOKTUR ve eklenmeyecektir: mağaza her çağrıda oturumdan "
			"türetilir. Bulunamayan kategori/ilan için hata değil BOŞ sonuç döner — "
			"\"yok\" ile \"senin değil\" ayrımı başka mağazanın kimliklerini keşfe "
			"kapı açardı. Dönüş şekli seviyeye göre değişir: kök ve kategori "
			"seviyeleri `{folders:[…]}`, dosya seviyeleri `{items:[…], total:n}`."
		),
		"x-measured": "http",
		"x-measurement": (
			"2026-08-19, satıcı oturumu (SEL-00003): kök → "
			"`{folders:[{public,7},{private,11},{chat,0}]}`; `scope=public` → 3 klasör; "
			"`scope=private` → 11 dosya; `scope=chat` → `{items:[],total:0}`; "
			"`scope=bogus` → 417 `ValidationError`; başka mağazanın ilanı "
			"(`listing=LST-00560`) → `{items:[],total:0}` (sızıntı yok). "
			"Misafir → 403, mağazasız oturum (Administrator) → 403 "
			"\"Bu işlem için bir mağaza hesabı gerekiyor.\""
		),
		"schema": "BrowseLevel",
	},
	"tradehub_core.api.seller_media.get_my_summary": {
		"x-measured": "http",
		"x-measurement": (
			"2026-08-19, satıcı: 200 → "
			"`{store, active, trashed, bytes, quota_bytes, tags}`."
		),
		"schema": "SellerSummary",
	},
	"tradehub_core.api.seller_media.get_my_media": {
		"x-measured": "http",
		"x-measurement": "2026-08-19, satıcı, `page_size=2`: 200 → `{items:[…], …}`.",
		"schema": "PagedFiles",
	},
	"tradehub_core.api.seller_media.upload_limits": {
		"x-measured": "http",
		"x-measurement": (
			"2026-08-19, satıcı: 200 → `extensions` (22), `media_extensions` (15), "
			"`denied_extensions` (13), `kinds`."
		),
		"schema": None,
	},
	"tradehub_core.api.media_admin.get_image_inventory": {
		"x-measured": "http",
		"x-measurement": (
			"2026-08-19: misafir → 403; satıcı → 403 (rol kapısı); Administrator, "
			"`page_size=2` → 200 `{items:[…]}`."
		),
		"schema": "PagedFiles",
	},
	"tradehub_core.tradehub_core.doctype.media_storage_settings.media_storage_settings.get_storage_status": {
		"description": (
			"Ayardan kurulan gerçek depo planını döndürür (sır İÇERMEZ: anahtar, "
			"parola, imza gizi yok — yalnız kip, backend sınıfı ve engelleyiciler). "
			"`docs/reports/32-faz8-api-kapanis.md` §5 bu ucu HTTP 500 `ImportError` "
			"ile UYUŞMAZ işaretlemişti; DocType satırı veritabanına girdikten sonra "
			"2026-08-19'da yeniden ölçüldü ve 200 döndü."
		),
		"schema": "StorageStatus",
	},
	"tradehub_core.tradehub_core.doctype.media_storage_settings.media_storage_settings.test_connection": {
		"description": (
			"Yapılandırılmış hedefe gerçek bağlantı denemesi (`s3` | `cdn` | "
			"`imgproxy`). Hedef tanımsızsa istisna FIRLATMAZ: `ok: false` ve "
			"`steps[].detail` ile söyler. Bu uç da 32 numaralı raporda UYUŞMAZ "
			"işaretliydi; bugün 200 dönüyor."
		),
		"schema": "ConnectionTest",
	},
	"tradehub_core.api.rum.collect": {
		"description": (
			"RUM (gerçek kullanıcı ölçümü) beacon'ı. GÖVDE SORGU PARAMETRESİ "
			"DEĞİLDİR: `Content-Type: text/plain;charset=UTF-8` + JSON "
			"`{\"samples\": [...]}` — `sendBeacon` başlık gönderemediği ve "
			"`application/json` CORS ön-kontrolü tetiklediği için (rapor 60 "
			"§5.2). Geçersiz örnek de 200 alır; ret sebebi istemciye "
			"SIZDIRILMAZ. Oran sınırı aşımı 429. CSRF muafiyeti framework'ün "
			"doğal davranışı (misafir oturumunda kayıtlı token yok) — "
			"`ignore_csrf` AÇILMADI; gerekçe `api/rum.py` modül başlığında."
		),
	},
}

# ═══════════════════════════════════════════════════════════════════════
# 2b. ÖLÇÜM KAYITLARI — gerçek HTTP çağrılarından (T-080, 2026-08-19)
# ═══════════════════════════════════════════════════════════════════════

#: Her kayıt bir **gerçek** `/api/method/…` çağrısından gelir. Sahte istemci
#: yoktur; ölçüm anında imajdaki kaynak dosyalar çalışma ağacıyla `sha256`
#: karşılaştırmasından geçti.
#:
#: Düzeyler (`x-measured` alanına yazılır):
#:
#:   "http"          Başarı gövdesi ölçüldü.
#:   "http-partial"  Uç ÇAĞRILDI ama yalnız ret/doğrulama yolu ölçülebildi;
#:                   başarı gövdesi bu sitede veri üretmeden çıkarılamazdı.
#:                   Gerekçe cümlenin içindedir. "Geçti" DEMEK DEĞİLDİR.
#:   "http-fail"     Çağrıldı, belgelenen gövdeyi ÜRETEMEDİ (`x-mismatch`).
#:
#: Alan YOKSA uç hiç çağrılmamıştır — sessizce "geçti" sayılmasın.
#:
#: Kimlikler: `misafir` (oturumsuz), `Administrator`, `satıcı` =
#: `ali.bal@turksab.com` → SEL-00003, `satıcı-2` = `ahmeetseker@gmail.com` →
#: SEL-00001. Satıcı oturumları Frappe'nin kendi `user.impersonate` ucuyla
#: açıldı; hiçbir parola değiştirilmedi.
OLCUM: dict[str, tuple[str, str]] = {
	# ── crop (T-082) ────────────────────────────────────────────────
	"tradehub_core.api.media_crop.get_intent": (
		"http",
		"2026-08-19. Misafir → 403 `PermissionError`. Satıcı, kendi mağazasının "
		"test varlığı: 200 → `{asset, slot_key, exists, intent, source, windows, "
		"etag, status}`; niyet yokken `exists=false` ve 7 pencere (w96…w1920) "
		"döndü — 404 DEĞİL. Kayıttan sonra `exists=true` ve `intent.focal_x/"
		"focal_y/method/confidence/approved_by_user` yazılan değerleri taşıdı. "
		"`if_none_match` eşleşince gövde `{etag, status: 304}` — HTTP durumu yine "
		"**200**. Satıcı-2 aynı varlığı istedi → 417 \"Medya varlığı bulunamadı.\" "
		"— olmayan varlıkla BİREBİR aynı yanıt (varlığın varlığı sızmıyor). "
		"Ölçüm varlığı ve niyeti ölçümden sonra silindi.",
	),
	"tradehub_core.api.media_crop.suggest_focal": (
		"http",
		"2026-08-19. Misafir → 403. Satıcı → 200 → `{asset, slot_key, suggestion, "
		"applied: false, windows, status}`; `suggestion` = `{focal_x, focal_y, "
		"confidence, measured: true, reason: \"measured\", grid: 32, threshold: "
		"0.5, threshold_calibrated: false, above_threshold, method}`. Güven eşiğin "
		"altında kaldığında `above_threshold: false` ile geliyor, hata değil. "
		"`@rate_limit(30/60s)` kovası ÖLÇÜLDÜ: tek satıcı oturumunda arka arkaya "
		"34 çağrı → 29 × 200, sonraki 5 × **429** `TooManyRequestsError`; ilk ret "
		"30. çağrıda. Yani sabit `max_calls=30` iken pencerede geçen çağrı 29.",
	),
	"tradehub_core.api.media_crop.save_intent": (
		"http",
		"2026-08-19. Misafir → 403. Satıcı, kendi varlığı, `overrides` YOK: 200 → "
		"`get_intent` ile aynı gövde, `exists=true`. **İdempotent doğrulandı**: "
		"aynı yük iki kez gönderildi, `Media Crop Intent` satır sayısı 1 kaldı "
		"(DB'den sayıldı). Ret yolları: `focal_x=1.4` → 417 \"0 ile 1 arasında "
		"olmalı (INV-10)\"; `method=\"edge_energy_v1\"` → 417 \"İzin verilenler: "
		"center, manual, smartcrop\"; satıcı-2 → 417 \"Medya varlığı bulunamadı.\" "
		"**UYUŞMAZLIK: `overrides` yolu bugün ÇALIŞMIYOR** — `x-mismatch`e bakın. "
		"Ölçüm kaydı silindi.",
	),
	# ── storage (32-faz8'deki iki UYUŞMAZLIK bugün KAPANDI) ─────────
	"tradehub_core.tradehub_core.doctype.media_storage_settings.media_storage_settings"
	".get_storage_status": (
		"http",
		"2026-08-19, Administrator → **200**: `{plan: {mode, requested_mode, "
		"degraded, downgraded_from, reasons, signer_available, backend}, blockers: "
		"[…]}`; ölçüldüğünde `mode=\"local\"`, `backend=\"LocalDiskStorage\"`, "
		"`degraded=false`. Satıcı → 403 (rol kapısı). Misafir → 403. "
		"`docs/reports/32-faz8-api-kapanis.md` §5'teki HTTP 500 `ImportError` "
		"ARTIK YOK: `Media Storage Settings` DocType satırı veritabanında var "
		"(`frappe.db.get_value` → \"Media Storage Settings\"). O rapordaki "
		"`x-mismatch` bu ölçümle kapandı.",
	),
	"tradehub_core.tradehub_core.doctype.media_storage_settings.media_storage_settings"
	".test_connection": (
		"http",
		"2026-08-19, Administrator, `target=cdn` → **200**: `{target, ok: false, "
		"steps: [{step, ok, ms, detail}], ms}`; `detail=\"adres tanımlı değil\"` "
		"(CDN yapılandırılmamış — uç doğru davranıyor, `ok=false` ile söylüyor). "
		"Satıcı → 403. Önceki rapordaki HTTP 500 `ImportError` ARTIK YOK.",
	),
	# ── delivery ────────────────────────────────────────────────────
	# (§4 ölçümleri `ANLATIM` içinde ayrıca duruyor.)
	# ── seller ──────────────────────────────────────────────────────
	"tradehub_core.api.seller_media.get_my_usage": (
		"http",
		"2026-08-19, satıcı, KENDİ dosyası → 200 `{file_url, verdict, usages, "
		"orders, history, records}`; `verdict` ölçümde `in_use`. **Kiracı sınırı**: "
		"aynı satıcı BAŞKA mağazanın dosyasını (`/files/191-ff0258.jpg`) sordu → "
		"**404** `DoesNotExistError` (`ownership.assert_owns`). Misafir → 403.",
	),
	"tradehub_core.api.seller_media.preview_release": (
		"http",
		"2026-08-19, satıcı → 200 `{total, owned, by_verdict, in_use}`; iki dosyalık "
		"seçimde `{total: 2, owned: 2, by_verdict: {unused: 2}, in_use: 0}`.",
	),
	"tradehub_core.api.seller_media.get_dimensions": (
		"http",
		"2026-08-19, satıcı → 200 `{width, height}` (ölçüm dosyası 4×3 PNG → "
		"`{4, 3}`). NOT: docstring'in dediği gibi ilk okuyuşta ölçü üstveriye "
		"YAZILIR — bu uç saf okuma değildir.",
	),
	"tradehub_core.api.seller_media.upload_media": (
		"http",
		"2026-08-19, satıcı, `data:image/png;base64,…` ile 4×3 PNG → 200 "
		"`{file_url, file_name, bytes, video_status}`. **PNG sunucuda WebP'ye "
		"çevrildi**: gönderilen `t080-olcum.png`, dönen `t080-olcum.webp` "
		"(66 B). Ölçüm dosyası `purge_media` ile kalıcı silindi.",
	),
	"tradehub_core.api.seller_media.update_media": (
		"http",
		"2026-08-19, satıcı → 200; `patch={\"title\",\"alt\",\"description\"}` "
		"gönderildi, yanıt tüm üstveriyi döndü: `{title, alt, description, tags, "
		"favorite, width, height}`. Ölçüm dosyası sonradan silindi.",
	),
	"tradehub_core.api.seller_media.toggle_favorite": (
		"http",
		"2026-08-19, satıcı → 200; art arda iki çağrı `favorite`ı `true` → `false` "
		"çevirdi (gövde `update_media` ile aynı üstveri sözlüğü).",
	),
	"tradehub_core.api.seller_media.add_tag": (
		"http",
		"2026-08-19, satıcı, tek dosya → 200 `{tagged: 1}`.",
	),
	"tradehub_core.api.seller_media.rename_media": (
		"http",
		"2026-08-19, satıcı → 200 `{file_url, file_name}`. Docstring'in sözü "
		"ölçülerek doğrulandı: `file_url` DEĞİŞMEDİ, yalnız `file_name` değişti.",
	),
	"tradehub_core.api.seller_media.duplicate_media": (
		"http",
		"2026-08-19, satıcı → 200 `{file_url, file_name, bytes}`; yeni adres "
		"`…-kopya.webp`. Kopya ölçümden sonra silindi.",
	),
	"tradehub_core.api.seller_media.replace_media": (
		"http",
		"2026-08-19, satıcı, yeni PNG içeriği → 200 `{file_url, bytes}`; `file_url` "
		"korundu, `bytes` 66 → 74 değişti (içerik gerçekten değişti).",
	),
	"tradehub_core.api.seller_media.archive_media": (
		"http",
		"2026-08-19, satıcı → 200 `{archived, failed: [], skipped, details: "
		"[{file_url, records, archived}]}`.",
	),
	"tradehub_core.api.seller_media.unarchive_media": (
		"http",
		"2026-08-19, satıcı → 200 `{unarchived, failed: [], skipped, details: "
		"[{file_url, records}]}`.",
	),
	"tradehub_core.api.seller_media.purge_media": (
		"http",
		"2026-08-19, satıcı, ölçüm için üretilen 3 dosya → 200 `{purged: 3, "
		"failed: [], skipped: 0, details: [{file_url, records, refs_cleared, "
		"remaining_owners, physically_deleted: true}]}`. Ölçümden sonra "
		"`get_my_summary` `{active: 6, bytes: 20466224}` ile ölçüm ÖNCESİ değere "
		"döndü — üretilen kayıt kalmadı.",
	),
	"tradehub_core.api.seller_media.upload_begin": (
		"http",
		"2026-08-19, satıcı → 200 `{upload_id, chunk_bytes: 2097152, chunk_count, "
		"file_name}`.",
	),
	"tradehub_core.api.seller_media.upload_chunk": (
		"http",
		"2026-08-19, satıcı, `index=0` → 200 `{upload_id, received: 1, "
		"chunk_count: 1, complete: true}`.",
	),
	"tradehub_core.api.seller_media.upload_finish": (
		"http",
		"2026-08-19, satıcı → 200 `{file_url, file_name, bytes, video_status}` — "
		"`upload_media` ile AYNI gövde. Üretilen dosya silindi.",
	),
	"tradehub_core.api.seller_media.upload_abort": (
		"http",
		"2026-08-19, satıcı → 200 `{upload_id, aborted: true}`; hemen ardından "
		"`upload_status` aynı kimlik için 417 verdi — iptal gerçekten iptal.",
	),
	"tradehub_core.api.seller_media.upload_status": (
		"http",
		"2026-08-19, satıcı: açık oturum → 200 `{upload_id, file_name, "
		"chunk_count, chunk_bytes, received: [0], created}`. Bilinmeyen/iptal "
		"edilmiş kimlik → **417** `UploadRejected` `[upload_session_unknown]` "
		"(`ValidationError` değil, ayrı bir istisna sınıfı).",
	),
	"tradehub_core.api.seller_media.retry_video": (
		"http-partial",
		"2026-08-19, satıcı, GÖRSEL dosya ile → 417 \"Yalnız başarısız videolar "
		"yeniden denenebilir (durum: -).\" Başarı yolu ÖLÇÜLMEDİ: bu sitede "
		"dead-letter durumunda video yok ve bir videoyu bilerek bozmak veri "
		"bozmak olurdu.",
	),
	"tradehub_core.api.seller_media.create_backup": (
		"http",
		"2026-08-19, satıcı → 200 `{set_id, file_count, total_bytes, new_blobs, "
		"new_bytes, record_count, skipped_unscanned, pruned}`; ölçümde 9 dosya / "
		"22 kayıt. Üretilen yedek kökü ölçümden sonra tamamen silindi "
		"(`list_backups` yeniden `{sets: [], usage: {sets: 0}}`).",
	),
	"tradehub_core.api.seller_media.list_backups": (
		"http",
		"2026-08-19, satıcı → 200 `{sets: [{set_id, created, label, file_count, "
		"total_bytes, new_blobs, new_bytes, record_count, skipped_unscanned}], "
		"usage: {bytes, blobs, sets, max_sets: 5}}`. Yedek yokken `sets: []`.",
	),
	"tradehub_core.api.seller_media.verify_backup": (
		"http",
		"2026-08-19, satıcı, `deep=1` → 200 `{set_id, files, records, "
		"missing_blobs: [], missing_count: 0, corrupt_blobs: [], corrupt_count: 0, "
		"deep: true, ok: true}`. Bilinmeyen `set_id` → 417 \"Geçersiz yedek "
		"kimliği\".",
	),
	"tradehub_core.api.seller_media.plan_backup_restore": (
		"http",
		"2026-08-19, satıcı → 200 `{set_id, created, ok, missing_file, "
		"missing_file_count, conflict, conflict_count, extra, extra_count, "
		"missing_record, missing_record_count, not_owned, not_owned_count, "
		"unscanned…}`. Bilinmeyen `set_id` → 417.",
	),
	"tradehub_core.api.seller_media.apply_backup_restore": (
		"http-partial",
		"2026-08-19, satıcı, `only=[\"/files/yok-9999-t080.jpg\"]` (kasten "
		"olmayan dosya) → 200 `{set_id, files_written: 0, overwritten: [], "
		"conflicts_skipped: [], skipped_not_owned: [], skipped_unscanned: [], "
		"records_created: 0, applied: true}`. Gövde şeması ölçüldü, GERÇEK bir "
		"geri yükleme ÖLÇÜLMEDİ — dosya üzerine yazmak veri bozardı.",
	),
	"tradehub_core.api.seller_media.delete_backup": (
		"http-partial",
		"2026-08-19, satıcı → **417** \"Son yedek silinemez.\" Kural gerçekten "
		"uygulanıyor; başarı gövdesi ÖLÇÜLMEDİ (silmek için ikinci bir yedek "
		"üretmek gerekirdi). Ölçüm yedeği API dışından, dosya sisteminden "
		"kaldırıldı.",
	),
	"tradehub_core.api.seller_media.start_backup_export": (
		"http",
		"2026-08-19, satıcı → 200 `{set_id, state: \"hazirlaniyor\", started, "
		"finished: null, actor, done: 0, total, file_name: null, bytes: 0, "
		"error: null}`.",
	),
	"tradehub_core.api.seller_media.backup_export_status": (
		"http",
		"2026-08-19, satıcı, paket hazırken → 200 `{…, state: \"hazir\", finished, "
		"done: 9, total: 9, file_name: \"medya-yedegim-….zip\", bytes}`. "
		"`discard` sonrası aynı uç `state: \"\"`, `exists: false`, `stale: false` "
		"döndü. Bilinmeyen `set_id` → 417.",
	),
	"tradehub_core.api.seller_media.discard_backup_export": (
		"http",
		"2026-08-19, satıcı → 200 `{set_id, state: \"\"}`; ardından durum ucu "
		"`exists: false` dedi.",
	),
	"tradehub_core.api.seller_media.download_backup_export": (
		"http",
		"2026-08-19, satıcı → **200, `application/zip`** — gövde JSON DEĞİL, "
		"paketin kendisi (`PK` sihirli baytıyla başlıyor). Bilinmeyen `set_id` → "
		"417 (JSON).",
	),
	# ── admin ───────────────────────────────────────────────────────
	"tradehub_core.api.media_admin.browse_media": (
		"http",
		"2026-08-19, Administrator, kök seviye → 200 `{folders: [{id, count}]}` "
		"(`public`/`private`/`chat`). Satıcı → 403, misafir → 403.",
	),
	"tradehub_core.api.media_admin.get_private_files": (
		"http",
		"2026-08-19, Administrator, `page_size=2` → 200 `{items: [{name, "
		"file_name, file_url, file_size, creation, attached_to_doctype, "
		"attached_to_name, …}], …}`.",
	),
	"tradehub_core.api.media_admin.get_record_media": (
		"http",
		"2026-08-19, Administrator, `doctype=Listing&name=LST-00560` → 200 "
		"`{doctype, name, page_path, slots: [{file_url, kind, field, row, "
		"file_name, file_size, …}]}`.",
	),
	"tradehub_core.api.media_admin.get_file_usage": (
		"http",
		"2026-08-19, Administrator → 200 `{file_url, verdict, usages: [{kind, "
		"field, doctype, name, label, status, page_path}], …}`.",
	),
	"tradehub_core.api.media_admin.get_file_references": (
		"http",
		"2026-08-19, Administrator → 200 `{file_url, items: [{table, column, kind, "
		"label, row, owner, owner_doctype, exact, readonly, row_owned}], …}` — "
		"referanslar TABLO/KOLON düzeyinde veriliyor.",
	),
	"tradehub_core.api.media_admin.get_dangling_references": (
		"http",
		"2026-08-19, Administrator → 200 `{items: [], total_rows: 0}` (bu sitede "
		"kopuk referans yok).",
	),
	"tradehub_core.api.media_admin.repair_dangling_references": (
		"http",
		"2026-08-19, Administrator, `dry_run=1` (varsayılan) → 200 "
		"`{dangling_urls: 0, dry_run: true, details: []}`. `dry_run=0` "
		"ÇALIŞTIRILMADI — yıkıcı.",
	),
	"tradehub_core.api.media_admin.preview_trash": (
		"http",
		"2026-08-19, Administrator → 200 `{total, by_verdict, in_use, "
		"live_places}`.",
	),
	"tradehub_core.api.media_admin.get_pending_count": (
		"http",
		"2026-08-19, Administrator → 200 `{count: 2841}`.",
	),
	"tradehub_core.api.media_admin.get_restorable_count": (
		"http",
		"2026-08-19, Administrator → 200 `{count: 4}`.",
	),
	"tradehub_core.api.media_admin.get_optimization_status": (
		"http",
		"2026-08-19, Administrator: bilinmeyen anahtar → 200 `{state: "
		"\"not_found\"}` (hata DEĞİL). Gerçek bir iş anahtarıyla → 200 `{state: "
		"\"partial\", preset, dry_run, total, processed, optimized, skipped, "
		"errors, original_bytes, new_bytes, skip_reasons, message}`.",
	),
	"tradehub_core.api.media_admin.start_image_optimization": (
		"http",
		"2026-08-19, Administrator, `dry_run=1` ve KASTEN OLMAYAN dosya adı → 200 "
		"`{job_key, count, preset: \"balanced\", dry_run: 1}`. İş kuyruğa girdi ve "
		"`get_optimization_status` `errors: 1` ile bitti — hiçbir gerçek dosyaya "
		"dokunulmadı. Gerçek dosya üzerinde optimizasyon ÖLÇÜLMEDİ.",
	),
	"tradehub_core.api.media_admin.start_restore": (
		"http",
		"2026-08-19, Administrator, kasten olmayan dosya adı → 200 `{job_key, "
		"count, mode: \"restore\"}`; iş `errors: 1` ile bitti. Gerçek geri alma "
		"ÖLÇÜLMEDİ.",
	),
	"tradehub_core.api.media_admin.restore_image": (
		"http-partial",
		"2026-08-19, Administrator, olmayan dosya → **404** `DoesNotExistError` "
		"(417 değil). Başarı yolu ÖLÇÜLMEDİ — gerçek bir görseli arşivden geri "
		"almak veri değiştirirdi.",
	),
	"tradehub_core.api.media_admin.retry_transcode": (
		"http-partial",
		"2026-08-19, Administrator, olmayan dosya → 417 \"Dosya bulunamadı: …\". "
		"Başarı yolu ÖLÇÜLMEDİ (dead-letter videosu yok).",
	),
	"tradehub_core.api.media_admin.set_access_level": (
		"http-partial",
		"2026-08-19, Administrator, olmayan dosya → **404** `DoesNotExistError`. "
		"Başarı yolu ÖLÇÜLMEDİ — gerçek bir dosyayı public↔private çevirmek "
		"vitrini etkilerdi.",
	),
	"tradehub_core.api.media_admin.trash_files": (
		"http-partial",
		"2026-08-19, Administrator, olmayan dosya → 200 `{moved: 0, failed: "
		"[{file_url, error}], freed_bytes: 0}` — kısmi hata dizisi ÖLÇÜLDÜ. "
		"Gerçek bir dosya çöpe ATILMADI.",
	),
	"tradehub_core.api.media_admin.restore_from_trash": (
		"http-partial",
		"2026-08-19, Administrator, olmayan dosya → 200 `{restored: 0, failed: "
		"[{file_url, error}]}`. Gerçek geri alma ÖLÇÜLMEDİ.",
	),
	"tradehub_core.api.media_admin.delete_trashed": (
		"http-partial",
		"2026-08-19, Administrator, olmayan dosya → 200 `{deleted: 0, "
		"freed_bytes: 0, records: 0, failed: [{file_url, error}]}`. Gerçek kalıcı "
		"silme ÖLÇÜLMEDİ.",
	),
	"tradehub_core.api.media_admin.purge_trash": (
		"http",
		"2026-08-19, Administrator, `older_than_days=36500` (hiçbir dosya bu "
		"kadar eski olamaz → kasıtlı boş küme) → 200 `{deleted: 0, freed_bytes: 0, "
		"records: 0}`. Gerçek bir çöp boşaltma ÖLÇÜLMEDİ.",
	),
	"tradehub_core.api.media_admin.purge_archive": (
		"http",
		"2026-08-19, Administrator, `older_than_days=36500` → 200 `{deleted: 0, "
		"freed_bytes: 0}`. Gerçek arşiv temizliği ÖLÇÜLMEDİ.",
	),
	"tradehub_core.api.media_admin.get_media_audit": (
		"http",
		"2026-08-19, Administrator, `page_size=2` → 200 `{items: [{name, "
		"timestamp, actor, actor_role, tenant, action, decision, severity, "
		"object_name, …}], …}`.",
	),
	"tradehub_core.api.media_admin.get_media_audit_facets": (
		"http",
		"2026-08-19, Administrator, `days=30` → 200 `{actions: {…sayaçlar…}, …}`; "
		"ölçümde `media.access_denied: 323`, `media.optimize: 243` gibi.",
	),
	"tradehub_core.api.media_admin.get_media_audit_actors": (
		"http",
		"2026-08-19, Administrator → 200 `{items: [{actor, tenant, n, tenant_name, "
		"actor_name, actor_display}]}`.",
	),
	"tradehub_core.api.media_admin.get_media_audit_targets": (
		"http",
		"2026-08-19, Administrator → 200 `{items: [{object_name, n}]}`.",
	),
	"tradehub_core.api.media_admin.get_media_audit_report": (
		"http",
		"2026-08-19, Administrator, gerçek bir `ADL-…` kimliğiyle → 200 `{event: "
		"{name, timestamp, actor, action, decision, severity, object_name, "
		"context, …}, …}`.",
	),
	"tradehub_core.api.media_admin.export_media_audit": (
		"http",
		"2026-08-19, Administrator → 200 `{csv: \"timestamp,action,decision,"
		"severity,actor,tenant,object_name,ip_address,context\\r\\n…\"}` — CSV "
		"gövde İÇİNDE dizge olarak döner, `text/csv` dosya indirmesi DEĞİLDİR.",
	),
	"tradehub_core.api.media_admin.list_media_backups": (
		"http",
		"2026-08-19, Administrator → 200 `{sets: [], usage: {bytes: 0, files: 0, "
		"sets: 0}, keep: 14}` — bu sitede yönetim yedeği YOK.",
	),
	"tradehub_core.api.media_admin.verify_media_backup": (
		"http-partial",
		"2026-08-19, Administrator, bilinmeyen `set_id` → 417 \"Geçersiz yedek "
		"kimliği\". Başarı gövdesi ÖLÇÜLMEDİ: sitede yönetim yedeği yok ve "
		"`create_media_backup` bütün medyayı kopyalardı.",
	),
	"tradehub_core.api.media_admin.plan_media_restore": (
		"http-partial",
		"2026-08-19, Administrator, bilinmeyen `set_id` → 417. Başarı gövdesi "
		"ÖLÇÜLMEDİ (yedek yok).",
	),
	"tradehub_core.api.media_admin.apply_media_restore": (
		"http-partial",
		"2026-08-19, Administrator, bilinmeyen `set_id` → 417. Başarı yolu "
		"ÖLÇÜLMEDİ — gerçek bir geri yükleme veri değiştirirdi.",
	),
	"tradehub_core.api.media_admin.repair_missing_media": (
		"http-partial",
		"2026-08-19, Administrator → 417 \"Hiç yedek yok.\" Başarı yolu "
		"ÖLÇÜLMEDİ.",
	),
	"tradehub_core.api.media_admin.prune_media_backups": (
		"http",
		"2026-08-19, Administrator, `keep=14` → 200 `{removed_sets: [], "
		"remaining_sets: 0, removed_blobs: 0, freed_bytes: 0}` (silinecek yedek "
		"yoktu).",
	),
	"tradehub_core.api.media_admin.delete_media_backup": (
		"http-partial",
		"2026-08-19, Administrator, bilinmeyen `set_id` → 417. Başarı yolu "
		"ÖLÇÜLMEDİ.",
	),
	"tradehub_core.api.media_admin.start_media_backup_export": (
		"http-partial",
		"2026-08-19, Administrator, bilinmeyen `set_id` → 417. Başarı yolu "
		"ÖLÇÜLMEDİ (yedek yok). Satıcı karşılığı `start_backup_export` uçtan uca "
		"ölçüldü ve çalışıyor.",
	),
	"tradehub_core.api.media_admin.media_backup_export_status": (
		"http-partial",
		"2026-08-19, Administrator, bilinmeyen `set_id` → 417. Başarı gövdesi "
		"ÖLÇÜLMEDİ.",
	),
	"tradehub_core.api.media_admin.discard_media_backup_export": (
		"http-partial",
		"2026-08-19, Administrator, bilinmeyen `set_id` → 417. Başarı yolu "
		"ÖLÇÜLMEDİ.",
	),
	"tradehub_core.api.media_admin.download_media_backup_export": (
		"http-partial",
		"2026-08-19, Administrator, bilinmeyen `set_id` → 417 (JSON). Başarı "
		"yolunda ikili paket dönmesi bekleniyor; ÖLÇÜLMEDİ. Satıcı karşılığı "
		"`download_backup_export` `application/zip` ile ölçüldü.",
	),
	"tradehub_core.api.media_admin.scan_overview": (
		"http",
		"2026-08-19, Administrator → 200 `{policy: {enabled, fail_closed, "
		"hold_until_clean, scanner}, counts: {pending, clean, infected, failed, "
		"unscanned}}`; ölçümde tarama KAPALI (`enabled: false`) ve "
		"`unscanned: 5020`.",
	),
	"tradehub_core.api.media_admin.list_scan_hold": (
		"http",
		"2026-08-19, Administrator → 200 `{items: [], total: 0, page, page_size}`.",
	),
	"tradehub_core.api.media_admin.list_quarantine": (
		"http",
		"2026-08-19, Administrator → 200 `{items: [], total: 0, page, page_size}`.",
	),
	"tradehub_core.api.media_admin.sweep_scans": (
		"http",
		"2026-08-19, Administrator, POST → 200 `{scanned: 0, requeued: 0, "
		"abandoned: 0}`. Aynı uç **GET** ile çağrılınca 403 "
		"`PermissionError: Not permitted` (yöntem kısıtı ölçüldü).",
	),
	"tradehub_core.api.media_admin.retry_scan": (
		"http-partial",
		"2026-08-19, Administrator, olmayan dosya → 417 \"Dosya bulunamadı\". "
		"Başarı yolu ÖLÇÜLMEDİ (başarısız taraması olan dosya yok).",
	),
	"tradehub_core.api.media_admin.release_quarantine": (
		"http-partial",
		"2026-08-19, Administrator, olmayan dosya → 417 \"Dosya bulunamadı\". "
		"Karantinada dosya olmadığı için başarı yolu ÖLÇÜLMEDİ.",
	),
	"tradehub_core.api.media_admin.scan_backfill": (
		"http",
		"2026-08-19, Administrator, `limit=0` → 200 `{queued: 0, skipped: "
		"\"disabled\"}` — tarama kapalı olduğu için uç hiçbir şey kuyruğa almadı "
		"ve bunu gövdede SÖYLÜYOR.",
	),
	# ── W6 SDK turu (2026-08-20) — bu turda eklenen 10 uç ─────────────
	# Oturum: `tests/e2e/global-setup.ts` deseniyle bench'te üretilen satıcı
	# `sid`i (ali.bal@turksab.com → SEL-00003). Yazan ölçümlerin izleri
	# (klasör, klasör bağı) ölçümden sonra silindi / köke geri taşındı.
	"tradehub_core.api.media_manifest.manifest_batch": (
		"http",
		"2026-08-20, satıcı, POST `{file_urls: [<kendi dosyası>, \"/files/yok.png\"]}` "
		"→ 200 `{manifests: {<adres>: {file, file_url, assets, renditions, "
		"version} | null}, requested: 2, returned: 1, max_batch: 100}`; olmayan "
		"adres `null` döndü, hata DEĞİL. `version` alanı türev üretilmemiş "
		"dosyada `null` (T-061 sürüm zenginleştirmesi — dolu hâli "
		"`version_enrichment_for_assets` sözleşmesidir). Misafir → 403 "
		"`PermissionError` (gövdedeki açık misafir kontrolü).",
	),
	"tradehub_core.api.rum.collect": (
		"http",
		"2026-08-20, misafir, POST `Content-Type: text/plain;charset=UTF-8`, "
		"gövde `{\"samples\": []}` → 200 `{ok: true}`. Gövde JSON parametre "
		"DEĞİL, ham istek gövdesidir (`frappe.request.get_data()` ile okunur; "
		"`sendBeacon` başlık gönderemediği için `text/plain` bilinçli). Geçersiz "
		"örnek de 200 alır — ret sebebi istemciye SIZDIRILMAZ (şema keşfi "
		"oraklına dönüşmesin), yalnız `media_rum_rejected_total` sayacına gider.",
	),
	"tradehub_core.api.seller_media.list_folders": (
		"http",
		"2026-08-20, satıcı → 200 `{folders: [], max_depth: 5}` (mağazanın "
		"klasörü yokken boş liste, hata değil). Klasör açıldıktan sonra satırlar "
		"`{name, folder_name, parent_folder, file_count}` taşıdı. Misafir → 403.",
	),
	"tradehub_core.api.seller_media.create_folder": (
		"http",
		"2026-08-20, satıcı, POST `{folder_name: \"olcum-w6-sdk\"}` → 200 "
		"`{name: \"qj5f5qmmtc\", folder_name, parent_folder: \"\"}`. "
		"Ölçüm klasörü ölçümden sonra silindi.",
	),
	"tradehub_core.api.seller_media.rename_folder": (
		"http",
		"2026-08-20, satıcı, POST `{folder, new_name}` → 200 `{name, "
		"folder_name}`; `name` DEĞİŞMEDİ, yalnız `folder_name` değişti "
		"(kimlik kararlı — alt bağlar kırılmasın).",
	),
	"tradehub_core.api.seller_media.delete_folder": (
		"http",
		"2026-08-20, satıcı, boş klasör, POST `{folder}` → 200 "
		"`{deleted: \"<name>\"}`. Dolu klasör reddi `media_folder.py:on_trash`ta "
		"— bu ölçümde klasör önce boşaltıldı.",
	),
	"tradehub_core.api.seller_media.move_media": (
		"http",
		"2026-08-20, satıcı, POST `{file_urls: [<kendi>, <olmayan>], folder}` → "
		"200 `{moved: 1, failed: [], skipped: 1}` — sahip olunmayan/olmayan adres "
		"SESSİZCE atlanmaz, `skipped` sayacına girer ama HANGİSİ olduğu dönmez. "
		"`folder: \"\"` ile aynı dosya köke geri taşındı (`moved: 1`).",
	),
	"tradehub_core.api.seller_media.list_folder_media": (
		"http",
		"2026-08-20, satıcı, 1 dosyalık klasör → 200 `{items: [{name, file_url, "
		"file_name, file_size, creation, title, alt, description, tags, "
		"favorite, width, height}], total: 1}` — satır biçimi `get_my_media` "
		"ile aynı (bilinçli, iki uç tek ekran koduyla çizilsin).",
	),
	"tradehub_core.api.seller_media.find_in_my_library": (
		"http",
		"2026-08-20, satıcı, geçerli ama eşleşmeyen 64 hanelik hash → 200 "
		"`{found: false, file: null}`; geçersiz `sha256=xyz` → 417 \"64 haneli "
		"onaltılık SHA-256 bekleniyor.\" Eşleşme dönerse `file` yalnız "
		"`{file_url, file_name, uploaded_at}` taşır (bilinçli üç alan).",
	),
	"tradehub_core.api.seller_media.list_orphans": (
		"http",
		"2026-08-20, satıcı, `days_unused=30&page_length=5` → 200 `{items: [], "
		"total: 0, start: 0, page_length: 5, days_unused: 30, scanned_at, scan: "
		"{live_fields: 17, order_fields: 5, history_scanned: false, "
		"failed_sources: []}}` — tarama sınırı gövdede makine okunur duruyor.",
	),
}

#: Ölçülmemiş kalan uçlar ve GEREKÇESİ. Boş bırakmak "ölçüldü" demek olurdu.
OLCULMEYEN: dict[str, str] = {
	"tradehub_core.api.media_admin.create_media_backup": (
		"ÇAĞRILMADI. Uç bütün sitenin medyasının anlık kopyasını alır "
		"(bu sitede 5.020 dosya); ölçüm için üretilip silinemeyecek kadar büyük "
		"bir yan etki olurdu. Satıcı karşılığı `seller_media.create_backup` "
		"uçtan uca ölçüldü ve aynı yedek çekirdeğini kullanıyor."
	),
	# MOGEM-582 retro-rename (2026-08-21) — henüz canlı HTTP trafiğine açılmadı.
	# `start_retro_rename`/`rollback_retro_rename` gerçek sitede 5.020 dosyanın
	# adını/DB kaydını GERÇEKTEN değiştirir (dry_run=1 bile iş kuyruğa girip
	# Redis ilerleme durumu + `ACTIVE_KEY` kilidini yazar) — ölçüm için üretilip
	# geri alınamayacak kadar büyük bir yan etki. Okuma-yalnız kardeşleri
	# (`retro_rename_count/plan/history`, `get_retro_rename_status`,
	# `stop_retro_rename`) tutarlılık için AYNI gerekçeyle burada — bu 7 uç
	# birlikte, ayrı bir HTTP ölçüm turunda kapatılacak (`retro_rename.py` unit
	# testleri Task 2-5'te uçtan uca is-mantığını zaten kanıtlıyor).
	"tradehub_core.api.media_admin.retro_rename_count": (
		"ÇAĞRILMADI. `start_retro_rename`/`rollback_retro_rename` ile aynı "
		"özellik grubu — ayrı HTTP ölçüm turunda birlikte kapatılacak."
	),
	"tradehub_core.api.media_admin.retro_rename_plan": (
		"ÇAĞRILMADI. `start_retro_rename`/`rollback_retro_rename` ile aynı "
		"özellik grubu — ayrı HTTP ölçüm turunda birlikte kapatılacak."
	),
	"tradehub_core.api.media_admin.start_retro_rename": (
		"ÇAĞRILMADI. Gerçek sitede 5.020 dosyayı geri dönüşü zor biçimde "
		"yeniden adlandırma işi kuyruğa girer; ölçüm için üretilip silinemeyecek "
		"kadar büyük bir yan etki olurdu."
	),
	"tradehub_core.api.media_admin.get_retro_rename_status": (
		"ÇAĞRILMADI. `start_retro_rename`/`rollback_retro_rename` ile aynı "
		"özellik grubu — ayrı HTTP ölçüm turunda birlikte kapatılacak."
	),
	"tradehub_core.api.media_admin.stop_retro_rename": (
		"ÇAĞRILMADI. `start_retro_rename`/`rollback_retro_rename` ile aynı "
		"özellik grubu — ayrı HTTP ölçüm turunda birlikte kapatılacak."
	),
	"tradehub_core.api.media_admin.rollback_retro_rename": (
		"ÇAĞRILMADI. Gerçek sitede `Media URL Redirect` satırlarına dayanarak "
		"dosyaları eski adına geri taşır; ölçüm için üretilip silinemeyecek "
		"kadar büyük bir yan etki olurdu."
	),
	"tradehub_core.api.media_admin.retro_rename_history": (
		"ÇAĞRILMADI. `start_retro_rename`/`rollback_retro_rename` ile aynı "
		"özellik grubu — ayrı HTTP ölçüm turunda birlikte kapatılacak."
	),
}


#: ÖLÇÜLDÜ ve SÖZLEŞMEYİ KARŞILAMADI. Belgeden gizlenmez.
UYUSMAZLIK: dict[str, str] = {
	"tradehub_core.api.media_crop.save_intent": (
		"2026-08-19, satıcı, gerçek HTTP: `overrides` yolu UÇTAN UCA ÇALIŞMIYOR — "
		"iki katman `profile` alanı için AYRI sözlük konuşuyor ve ikisini birden "
		"geçen bir değer YOK.\n"
		"  • `overrides=[{\"profile\": \"w384\", …}]` → kütüphane doğrulamasını "
		"geçer, sonra Frappe **417 `LinkValidationError`: \"Satır #1: Profil: w384 "
		"bulunamadı.\"** — çünkü `Media Crop Override.profile` bir "
		"`Link → Media Profile`tır ve o DocType'ın kayıtları "
		"`product.image:w384` biçiminde adlandırılmıştır.\n"
		"  • `overrides=[{\"profile\": \"product.image:w384\", …}]` → bu kez "
		"kütüphane reddeder: **417 \"`product.image:w384` bu slotta tanımlı bir "
		"profil değil.\"** — `pipeline/api/crop.py` slot içi kısa adları "
		"(`w96…w1920`) bekler; `get_intent().windows[].profile` de bu kısa adı "
		"döndürür.\n"
		"Sonuç: `save_intent` `overrides` OLMADAN 200 döner ve idempotenttir; "
		"`overrides` ile HER ZAMAN 417 döner. `docs/reports/37-media-crop-intent.md` "
		"§2.2 bu ikiliği çözdüğünü söylüyor — ölçüm çözülmediğini gösteriyor. "
		"Belge bu ucu 'kısmen çalışır' olarak anlatır; düzeltme bu görevin "
		"dokunma listesindeki `api/**` ve `media/**` altındadır."
	),
}

# `OLCUM` kayıtları `ANLATIM`a BURADA birleşir — elle yazılan açıklama ile
# ölçülen cümle ayrı yerlerde durur ki biri diğerini sessizce ezmesin.
for _anahtar, (_duzey, _cumle) in OLCUM.items():
	_kayit = ANLATIM.setdefault(_anahtar, {})
	_kayit["x-measured"] = _duzey
	_kayit["x-measurement"] = _cumle
#: Ölçülen gövdelerden çıkarılan şema adları — uç → şema.
SEMA_BAGI: dict[str, str] = {
	"tradehub_core.api.media_crop.get_intent": "CropIntentView",
	"tradehub_core.api.media_crop.save_intent": "CropIntentView",
	"tradehub_core.api.media_crop.suggest_focal": "FocalSuggestion",
	"tradehub_core.tradehub_core.doctype.media_storage_settings"
	".media_storage_settings.get_storage_status": "StorageStatus",
	"tradehub_core.tradehub_core.doctype.media_storage_settings"
	".media_storage_settings.test_connection": "ConnectionTest",
	# W6 SDK turu (2026-08-20) — ölçülen gövdelerden çıkarılan şemalar.
	"tradehub_core.api.media_manifest.manifest_batch": "FileManifestBatch",
	"tradehub_core.api.rum.collect": "RumAck",
	"tradehub_core.api.seller_media.list_folders": "FolderList",
	"tradehub_core.api.seller_media.create_folder": "FolderCreated",
	"tradehub_core.api.seller_media.rename_folder": "FolderRenamed",
	"tradehub_core.api.seller_media.delete_folder": "FolderDeleted",
	"tradehub_core.api.seller_media.move_media": "MoveResult",
	"tradehub_core.api.seller_media.list_folder_media": "PagedFiles",
	"tradehub_core.api.seller_media.find_in_my_library": "LibraryMatch",
	"tradehub_core.api.seller_media.list_orphans": "OrphanList",
}
for _anahtar, _sema in SEMA_BAGI.items():
	ANLATIM.setdefault(_anahtar, {}).setdefault("schema", _sema)
for _anahtar, _cumle in UYUSMAZLIK.items():
	ANLATIM.setdefault(_anahtar, {})["x-mismatch"] = _cumle
for _anahtar, _cumle in OLCULMEYEN.items():
	ANLATIM.setdefault(_anahtar, {})["x-unmeasured"] = _cumle


# ═══════════════════════════════════════════════════════════════════════
# 3. Şemalar — ÖLÇÜLMÜŞ gövdelerden
# ═══════════════════════════════════════════════════════════════════════

SEMALAR: dict[str, Any] = {
	"FrappeEnvelope": {
		"type": "object",
		"description": (
			"Frappe her `@frappe.whitelist()` dönüşünü `message` altına sarar. "
			"Bu belgedeki her yanıt şeması `message`in İÇERİĞİDİR."
		),
		"required": ["message"],
		"properties": {"message": {}},
	},
	"StorageStatus": {
		"type": "object",
		"description": (
			"`get_storage_status` gövdesi — 2026-08-19'da ÖLÇÜLDÜ. Sır taşımaz."
		),
		"required": ["plan", "blockers"],
		"properties": {
			"plan": {
				"type": "object",
				"required": ["mode", "requested_mode", "degraded", "signer_available", "backend"],
				"properties": {
					"mode": {"type": "string", "examples": ["local", "s3", "tiered"]},
					"requested_mode": {"type": "string"},
					"degraded": {"type": "boolean", "description": "İstenen kipe düşülemediyse true."},
					"downgraded_from": {"type": "string"},
					"reasons": {"type": "array", "items": {"type": "string"}},
					"signer_available": {"type": "boolean"},
					"backend": {"type": "string", "examples": ["LocalDiskStorage"]},
				},
			},
			"blockers": {
				"type": "array",
				"items": {"type": "string"},
				"description": "Kipi güvenle açmayı engelleyen bilinen kusurlar (`B-02` gibi kodlu).",
			},
		},
	},
	"ConnectionTest": {
		"type": "object",
		"description": "`test_connection` gövdesi — ÖLÇÜLDÜ. Başarısızlık istisna DEĞİL, `ok: false`.",
		"required": ["target", "ok", "steps"],
		"properties": {
			"target": {"type": "string", "examples": ["s3", "cdn", "imgproxy"]},
			"ok": {"type": "boolean"},
			"steps": {
				"type": "array",
				"items": {
					"type": "object",
					"required": ["step", "ok"],
					"properties": {
						"step": {"type": "string"},
						"ok": {"type": "boolean"},
						"ms": {"type": "number"},
						"detail": {"type": "string"},
					},
				},
			},
			"ms": {"type": "number"},
		},
	},
	"CropIntentView": {
		"type": "object",
		"description": (
			"`get_intent` / `save_intent` gövdesi — ÖLÇÜLDÜ. Niyet hiç yazılmamışsa "
			"da 200 döner: `exists: false` ve örtük (merkez) pencereler."
		),
		"required": ["asset", "slot_key", "exists", "intent", "source", "windows", "etag"],
		"properties": {
			"asset": {"type": "string"},
			"slot_key": {"type": "string", "examples": ["product.image"]},
			"exists": {"type": "boolean"},
			"intent": {"$ref": "#/components/schemas/CropIntentBody"},
			"source": {
				"type": "object",
				"required": ["width", "height", "source_ratio"],
				"properties": {
					"width": {"type": "integer"},
					"height": {"type": "integer"},
					"source_ratio": {"type": "number"},
				},
			},
			"windows": {"type": "array", "items": {"$ref": "#/components/schemas/CropWindow"}},
			"etag": {"type": "string", "description": "Tırnaklı. Gövdede taşınır, BAŞLIKTA değil."},
			"status": {"type": "integer", "description": "Kütüphanenin niyet ettiği durum; HTTP durumu DEĞİL."},
		},
	},
	"CropIntentBody": {
		"type": "object",
		"description": "Kaydedilmiş niyet. Yazılmamışsa tüm koordinatlar `null`.",
		"required": ["focal_x", "focal_y", "method", "approved_by_user", "overrides"],
		"properties": {
			"focal_x": {"type": ["number", "null"], "description": "0-1 normalize."},
			"focal_y": {"type": ["number", "null"]},
			"safe_x": {"type": ["number", "null"]},
			"safe_y": {"type": ["number", "null"]},
			"safe_w": {"type": ["number", "null"]},
			"safe_h": {"type": ["number", "null"]},
			# Stüdyonun zoom üçlüsü — ÜÇÜ BİRLİKTE yazılır/silinir
			# (api/media_crop.py:451-467 imzası; pipeline/api/crop.py:285-287
			# okuma gövdesi; birlikte-verilme kuralı pipeline/api/crop.py:415-437).
			"zoom": {
				"type": ["number", "null"],
				"description": "Stüdyonun zoom çarpanı, 1-16. `center_x`/`center_y` ile BİRLİKTE.",
			},
			"center_x": {"type": ["number", "null"], "description": "Pan merkezi, 0-1 normalize."},
			"center_y": {"type": ["number", "null"]},
			"method": {"type": "string", "examples": ["manual", "smartcrop", "center"]},
			"confidence": {"type": ["number", "null"]},
			"approved_by_user": {"type": "boolean"},
			"overrides": {
				"type": "array",
				"items": {"type": "object"},
				"description": "ÖLÇÜM: bu dizi bugün YAZILAMIYOR — `x-mismatch`e bakın.",
			},
			"updated_at": {
				"type": ["string", "null"],
				"description": "ÖLÇÜMDE kayıt yazıldıktan sonra da `null` geldi.",
			},
		},
	},
	"CropWindow": {
		"type": "object",
		"description": "Tek profil için çözülmüş pencere — ÖLÇÜLDÜ (7 profil: w96…w1920).",
		"required": ["x", "y", "w", "h", "method", "profile", "width", "fit", "pixels"],
		"properties": {
			"x": {"type": "number"},
			"y": {"type": "number"},
			"w": {"type": "number"},
			"h": {"type": "number"},
			"method": {"type": "string", "examples": ["focal", "center", "override", "safe_focal", "smartcrop"]},
			"priority": {"type": "integer"},
			"profile": {
				"type": "string",
				"examples": ["w384"],
				"description": (
					"SLOT İÇİ kısa ad. `Media Profile` DocType'ındaki kayıt adı "
					"`product.image:w384` biçimindedir — İKİSİ AYNI DEĞİL."
				),
			},
			"target_ratio": {"type": ["number", "null"]},
			"source_ratio": {"type": "number"},
			"confidence": {"type": ["number", "null"]},
			"approved_by_user": {"type": "boolean"},
			"is_suggestion": {"type": "boolean"},
			"width": {"type": "integer"},
			"fit": {"type": "string", "examples": ["pad", "cover"]},
			"pixels": {
				"type": "object",
				"required": ["left", "top", "width", "height"],
				"properties": {
					"left": {"type": "integer"},
					"top": {"type": "integer"},
					"width": {"type": "integer"},
					"height": {"type": "integer"},
				},
			},
		},
	},
	"FocalSuggestion": {
		"type": "object",
		"description": "`suggest_focal` gövdesi — ÖLÇÜLDÜ. YAZMAZ (`applied: false`).",
		"required": ["asset", "slot_key", "suggestion", "applied", "windows"],
		"properties": {
			"asset": {"type": "string"},
			"slot_key": {"type": "string"},
			"applied": {"type": "boolean", "description": "DAİMA false — öneri onaya sunulur."},
			"suggestion": {
				"type": "object",
				"required": ["focal_x", "focal_y", "confidence", "measured", "reason", "method"],
				"properties": {
					"focal_x": {"type": "number", "description": "DAİMA 0-1."},
					"focal_y": {"type": "number"},
					"confidence": {"type": "number"},
					"measured": {"type": "boolean", "description": "false ise merkez döndü, hata DEĞİL."},
					"reason": {"type": "string", "examples": ["measured"]},
					"grid": {"type": "integer"},
					"threshold": {"type": "number"},
					"threshold_calibrated": {
						"type": "boolean",
						"description": "ÖLÇÜMDE false — eşik kalibre EDİLMEMİŞ, yanıt bunu söylüyor.",
					},
					"above_threshold": {"type": "boolean"},
					"method": {"type": "string"},
				},
			},
			"windows": {"type": "array", "items": {"$ref": "#/components/schemas/CropWindow"}},
			"status": {"type": "integer"},
		},
	},
	"CropNotModified": {
		"type": "object",
		"description": (
			"`get_intent` + eşleşen `if_none_match` gövdesi — ÖLÇÜLDÜ. HTTP durumu "
			"**200**'dür. DİKKAT: manifest ucunun `{not_modified: true}` bayrağıyla "
			"AYNI DEĞİL; bu katmanda İKİ ayrı 'değişmedi' sözleşmesi var."
		),
		"required": ["etag", "status"],
		"properties": {
			"etag": {"type": "string"},
			"status": {"type": "integer", "examples": [304], "description": "Gövdedeki sayı; HTTP durumu 200."},
		},
	},
	"FrappeError": {
		"type": "object",
		"description": (
			"Frappe'nin istisna zarfı. `pipeline/api/envelope.py`nin "
			"`{error_code, retryable, …}` gövdesi ile AYNI DEĞİLDİR: whitelist "
			"katmanı o zarfı kullanmaz."
		),
		"properties": {
			"exception": {"type": "string"},
			"exc_type": {"type": "string"},
			"exc": {"type": "string", "description": "JSON dizisi olarak traceback."},
			"_server_messages": {"type": "string"},
		},
	},
	"RenditionRow": {
		"type": "object",
		"description": "Düz türev satırı — `renditions` dizisinin elemanı.",
		"required": ["source", "asset", "profile", "url", "width", "height", "format", "bytes"],
		"properties": {
			"source": {"type": "string", "description": "Ham `file_url`."},
			"asset": {"type": "string"},
			"profile": {"type": "string", "examples": ["w384", "w768"]},
			"url": {"type": "string", "description": "`Media Rendition.file_url` — DİSKTEKİ adres."},
			"width": {"type": "integer"},
			"height": {"type": "integer"},
			"format": {"type": "string", "examples": ["avif", "webp"]},
			"bytes": {"type": "integer"},
		},
	},
	"ManifestImage": {
		"type": "object",
		"required": ["file_url", "alt_text", "primary", "asset", "manifest"],
		"properties": {
			"file_url": {"type": "string"},
			"alt_text": {"type": "string"},
			"primary": {"type": "boolean"},
			"asset": {"type": "string", "description": "`Media Asset` adı; yoksa boş dizge."},
			"manifest": {
				"type": ["object", "null"],
				"description": (
					"`RenderManifest.to_dict()` + yalnız üretilmiş `variants`. "
					"Türev yoksa `null` — istemci ham `file_url`a düşer."
				),
			},
		},
	},
	"Manifest": {
		"type": "object",
		"description": "`get_manifest` gövdesi (`message` içeriği).",
		"required": [
			"listing", "slot", "enabled", "fallback", "renditions", "images",
			"suppressed", "etag", "cache_control",
		],
		"properties": {
			"listing": {"type": "string"},
			"slot": {"type": "string", "default": "product.image"},
			"enabled": {
				"type": "boolean",
				"description": "`manifest_api_enabled` bayrağı. Kapalıyken de 200 döner.",
			},
			"fallback": {
				"type": "string",
				"description": "Ham `file_url`; türev varsa merdivenin orta basamağı.",
			},
			"renditions": {"type": "array", "items": {"$ref": "#/components/schemas/RenditionRow"}},
			"images": {"type": "array", "items": {"$ref": "#/components/schemas/ManifestImage"}},
			"suppressed": {
				"type": "integer",
				"description": "`benefit_gate_passed=0` olduğu için elenen türev sayısı.",
			},
			"etag": {"type": "string", "description": "İçerik adresli; tırnaklı."},
			"cache_control": {"type": "string", "examples": ["public, max-age=60, must-revalidate"]},
		},
	},
	"NotModified": {
		"type": "object",
		"description": (
			"`if_none_match` (ya da `If-None-Match` başlığı) tuttuğunda dönen gövde. "
			"HTTP durumu YİNE 200'dür — Frappe whitelist katmanı 304 üretmez, "
			"gövdesizlik `not_modified` bayrağıyla bildirilir."
		),
		"required": ["not_modified", "etag", "cache_control"],
		"properties": {
			"not_modified": {"const": True},
			"etag": {"type": "string"},
			"cache_control": {"type": "string"},
		},
	},
	"ManifestBatch": {
		"type": "object",
		"required": [
			"slot", "enabled", "manifests", "missing", "requested", "returned",
			"truncated", "max_batch", "skipped", "etag", "cache_control",
		],
		"properties": {
			"slot": {"type": "string"},
			"enabled": {"type": "boolean"},
			"manifests": {
				"type": "object",
				"additionalProperties": {"$ref": "#/components/schemas/Manifest"},
				"description": "İlan adı → manifest. Alt gövdelerde `etag`/`cache_control` YOKTUR.",
			},
			"missing": {
				"type": "array",
				"items": {"type": "string"},
				"description": "DAİMA boş — bilinçli. Numaralandırma kehaneti olmasın diye.",
			},
			"requested": {"type": "integer"},
			"returned": {"type": "integer"},
			"truncated": {"type": "boolean"},
			"max_batch": {"type": "integer", "const": 50},
			"skipped": {
				"type": "array",
				"items": {"type": "string"},
				"description": "Tavanı aşıp kırpılan kimlikler — çağıranın kendi girdisinin yankısı.",
			},
			"etag": {"type": "string"},
			"cache_control": {"type": "string"},
		},
	},
	"SignedUrl": {
		"type": "object",
		"required": ["url", "exp", "ttl_seconds"],
		"properties": {
			"url": {
				"type": "string",
				"description": "`/api/method/tradehub_core.api.media_access.download?file=…&exp=…&blob=…&_signature=…`",
			},
			"exp": {"type": "integer", "description": "Unix zaman damgası."},
			"ttl_seconds": {"type": "integer", "description": "Clamp'lenmiş süre (60…86400)."},
		},
	},
	"SignedUrlCached": {
		"allOf": [
			{"$ref": "#/components/schemas/SignedUrl"},
			{
				"type": "object",
				"required": ["cache_control"],
				"properties": {"cache_control": {"const": "private, no-store"}},
			},
		],
	},
	"BrowseFolder": {
		"type": "object",
		"required": ["id", "count"],
		"properties": {
			"id": {"type": "string"},
			"label": {"type": "string"},
			"count": {"type": "integer"},
		},
	},
	"BrowseLevel": {
		"oneOf": [
			{
				"type": "object",
				"required": ["folders"],
				"properties": {
					"folders": {"type": "array", "items": {"$ref": "#/components/schemas/BrowseFolder"}}
				},
			},
			{
				"type": "object",
				"required": ["items", "total"],
				"properties": {
					"items": {"type": "array", "items": {"type": "object"}},
					"total": {"type": "integer"},
				},
			},
		],
		"description": "Seviyeye göre klasör listesi VEYA dosya listesi.",
	},
	"SellerSummary": {
		"type": "object",
		"required": ["store", "active", "trashed", "bytes"],
		"properties": {
			"store": {"type": "string"},
			"active": {"type": "integer"},
			"trashed": {"type": "integer"},
			"bytes": {"type": "integer"},
			"quota_bytes": {"type": ["integer", "null"]},
			"tags": {"type": "array", "items": {"type": "string"}},
		},
	},
	"PagedFiles": {
		"type": "object",
		"required": ["items"],
		"properties": {
			"items": {"type": "array", "items": {"type": "object"}},
			"total": {"type": "integer"},
			"page": {"type": "integer"},
			"page_size": {"type": "integer"},
		},
	},
	# ── W6 SDK turu (2026-08-20) — ölçülen gövdelerden ─────────────────
	"FileManifestBatch": {
		"type": "object",
		"description": (
			"`manifest_batch` gövdesi — DOSYA bazlı panel envanteri. "
			"`get_manifest_batch` (İLAN bazlı, guest) ile karıştırmayın."
		),
		"required": ["manifests", "requested", "returned", "max_batch"],
		"properties": {
			"manifests": {
				"type": "object",
				"additionalProperties": {
					"oneOf": [{"$ref": "#/components/schemas/FileManifest"}, {"type": "null"}]
				},
				"description": (
					"İstenen adres → manifest. Erişilemeyen adres `null` — 'yok', "
					"'silinmiş' ve 'başka satıcının özel dosyası' AYIRT EDİLMEZ."
				),
			},
			"requested": {"type": "integer"},
			"returned": {"type": "integer"},
			"max_batch": {"type": "integer", "const": 100},
		},
	},
	"FileManifest": {
		"type": "object",
		"required": ["file", "file_url", "assets", "renditions", "version"],
		"properties": {
			"file": {"type": "string", "description": "`File` docname."},
			"file_url": {"type": "string"},
			"assets": {"type": "array", "items": {"type": "string"}},
			"renditions": {
				"type": "array",
				"items": {"$ref": "#/components/schemas/RenditionRow"},
				"description": "HAM üretim envanteri — fayda kapısını geçmeyenler dâhil.",
			},
			"version": {
				"type": ["object", "null"],
				"description": (
					"T-061 sürüm zenginleştirmesi (`version_enrichment_for_assets`). "
					"Türev üretilmemiş dosyada `null` — ÖLÇÜLDÜ."
				),
			},
		},
	},
	"FolderList": {
		"type": "object",
		"required": ["folders", "max_depth"],
		"properties": {
			"folders": {
				"type": "array",
				"items": {
					"type": "object",
					"required": ["name", "folder_name", "parent_folder", "file_count"],
					"properties": {
						"name": {"type": "string"},
						"folder_name": {"type": "string"},
						"parent_folder": {"type": "string", "description": "Boş dizge = kök."},
						"file_count": {"type": "integer"},
					},
				},
			},
			"max_depth": {"type": "integer", "const": 5},
		},
	},
	"FolderCreated": {
		"type": "object",
		"required": ["name", "folder_name", "parent_folder"],
		"properties": {
			"name": {"type": "string"},
			"folder_name": {"type": "string"},
			"parent_folder": {"type": "string"},
		},
	},
	"FolderRenamed": {
		"type": "object",
		"required": ["name", "folder_name"],
		"properties": {
			"name": {"type": "string", "description": "DEĞİŞMEZ — kimlik kararlı."},
			"folder_name": {"type": "string"},
		},
	},
	"FolderDeleted": {
		"type": "object",
		"required": ["deleted"],
		"properties": {"deleted": {"type": "string", "description": "Silinen klasörün `name`i."}},
	},
	"MoveResult": {
		"type": "object",
		"required": ["moved", "failed", "skipped"],
		"properties": {
			"moved": {"type": "integer"},
			"failed": {
				"type": "array",
				"items": {
					"type": "object",
					"required": ["file_url", "error"],
					"properties": {"file_url": {"type": "string"}, "error": {"type": "string"}},
				},
			},
			"skipped": {
				"type": "integer",
				"description": "Sahip olunmayan adres sayısı — HANGİSİ olduğu dönmez.",
			},
		},
	},
	"OrphanList": {
		"type": "object",
		"required": ["items", "total", "start", "page_length", "days_unused", "scanned_at", "scan"],
		"properties": {
			"items": {"type": "array", "items": {"type": "object"}},
			"total": {"type": "integer"},
			"start": {"type": "integer"},
			"page_length": {"type": "integer"},
			"days_unused": {"type": "integer"},
			"scanned_at": {"type": "string"},
			"scan": {
				"type": "object",
				"description": "Taramanın neyi GÖRMEDİĞİ — ekran göstermek ZORUNDA (T-043).",
				"required": ["live_fields", "order_fields", "history_scanned", "failed_sources"],
				"properties": {
					"live_fields": {"type": "integer"},
					"order_fields": {"type": "integer"},
					"history_scanned": {"type": "boolean", "const": False},
					"failed_sources": {"type": "array", "items": {"type": "string"}},
				},
			},
		},
	},
	"LibraryMatch": {
		"type": "object",
		"description": "`find_in_my_library` gövdesi. Eşleşmeme ile 'başka mağazada var' AYNI yanıttır.",
		"required": ["found", "file"],
		"properties": {
			"found": {"type": "boolean"},
			"file": {
				"oneOf": [
					{
						"type": "object",
						"required": ["file_url", "file_name", "uploaded_at"],
						"properties": {
							"file_url": {"type": "string"},
							"file_name": {"type": "string"},
							"uploaded_at": {"type": "string"},
						},
					},
					{"type": "null"},
				],
				"description": "Bilinçli üç alan — sahip/kullanım bilgisi bu uca taşınmaz.",
			},
		},
	},
	"RumAck": {
		"type": "object",
		"description": (
			"`rum.collect` gövdesi — BİLİNÇLİ boşa yakın: `sendBeacon` yanıtı "
			"okuyamaz ve ret ayrıntısı şema keşfine yarardı."
		),
		"required": ["ok"],
		"properties": {"ok": {"type": "boolean", "const": True}},
	},
}


# ═══════════════════════════════════════════════════════════════════════
# 4. Belge kurulumu
# ═══════════════════════════════════════════════════════════════════════

#: `str` dışı tipler için OpenAPI karşılığı. Bilinmeyen tip `string` sayılır:
#: Frappe zaten sorgu dizgesinden gelen her şeyi dizge olarak alır.
TIP_ESLEME: dict[str, dict[str, Any]] = {
	"str": {"type": "string"},
	"int": {"type": "integer"},
	"float": {"type": "number"},
	"bool": {"type": "boolean"},
	"dict": {"type": "object"},
}


def _param_semasi(tip: str) -> dict[str, Any]:
	if tip in TIP_ESLEME:
		return dict(TIP_ESLEME[tip])
	if "list" in tip:
		return {
			"type": "string",
			"description": "JSON dizisi ya da virgüllü liste olarak gönderilir (GET sorgu dizgesi).",
		}
	return {"type": "string"}


def _operasyon(uc: dict[str, Any]) -> dict[str, Any]:
	anlatim = ANLATIM.get(uc["key"], {})
	sema_adi = anlatim.get("schema")
	basarili: dict[str, Any]
	if sema_adi:
		basarili = {"$ref": f"#/components/schemas/{sema_adi}"}
	else:
		basarili = {"description": "Şema belgelenmedi — uç HTTP ile doğrulanmadı ya da ikili gövde döner."}

	params = [
		{
			"name": p["name"],
			"in": "query",
			"required": p["default"] is None,
			"schema": _param_semasi(p["type"]),
			"description": (
				f"Python tipi `{p['type'] or '?'}`"
				+ (f", varsayılan `{p['default']}`" if p["default"] is not None else ", ZORUNLU")
			),
		}
		for p in uc["params"]
	]

	op: dict[str, Any] = {
		"tags": [uc["tag"]],
		"operationId": f"{uc['module'].rsplit('.', 1)[-1]}_{uc['fn']}",
		"x-allowed-methods": list(uc["methods"]),
		"summary": uc["summary"],
		"x-python": uc["key"],
		"x-source": f"{uc['file']}:{uc['line']}",
		"x-authorization": " ".join(uc["gates"]),
	}
	if anlatim.get("description"):
		op["description"] = anlatim["description"]
	if uc["decorators"]:
		op["x-decorators"] = list(uc["decorators"])
	if anlatim.get("x-measured"):
		op["x-measured"] = anlatim["x-measured"]
	if anlatim.get("x-measurement"):
		op["x-measurement"] = anlatim["x-measurement"]
	if anlatim.get("x-mismatch"):
		op["x-mismatch"] = anlatim["x-mismatch"]
	if anlatim.get("x-unmeasured"):
		op["x-unmeasured"] = anlatim["x-unmeasured"]
	if params:
		op["parameters"] = params

	yanitlar: dict[str, Any] = {
		"200": {
			"description": "Başarılı. Gövde Frappe zarfıyla `message` altındadır.",
			"content": {
				"application/json": {
					"schema": {
						"type": "object",
						"required": ["message"],
						"properties": {"message": basarili},
					}
				}
			},
		},
		"403": {"$ref": "#/components/responses/Denied"},
		"417": {"$ref": "#/components/responses/Validation"},
		"500": {"$ref": "#/components/responses/ServerError"},
	}
	if uc["key"].startswith("tradehub_core.api.media_manifest.get_manifest"):
		yanitlar["200"]["content"]["application/json"]["schema"]["properties"]["message"] = {
			"oneOf": [basarili, {"$ref": "#/components/schemas/NotModified"}]
		}
	if uc["key"] == "tradehub_core.api.media_crop.get_intent":
		# ÖLÇÜLDÜ: eşleşen `if_none_match` gövdeyi kısaltıyor, HTTP durumu 200 kalıyor.
		yanitlar["200"]["content"]["application/json"]["schema"]["properties"]["message"] = {
			"oneOf": [basarili, {"$ref": "#/components/schemas/CropNotModified"}]
		}
	if "suggest_focal" in uc["key"]:
		yanitlar["429"] = {"$ref": "#/components/responses/RateLimited"}
	op["responses"] = yanitlar
	op["security"] = [] if uc["allow_guest"] else [{"frappeSession": []}, {"frappeToken": []}]
	return op


def build_document() -> dict[str, Any]:
	"""Belgenin tamamı. Saf fonksiyon — aynı kod → aynı sözlük."""
	uclar = envanter()
	paths: dict[str, Any] = {}
	for uc in uclar:
		yol = f"/api/method/{uc['key']}"
		# TEK operasyon basılır. Frappe `@frappe.whitelist()`i kısıtlamadıkça
		# hem GET hem POST kabul eder; ikisini de ayrı ayrı basmak belgeyi iki
		# katına çıkarıp aynı sözleşmeyi tekrar ederdi. İzin verilen yöntemler
		# `x-allowed-methods` altında YAZILI durur.
		birincil = "post" if uc["methods"] == ("POST",) else "get"
		paths[yol] = {birincil: _operasyon(uc)}

	misafir = [u["key"] for u in uclar if u["allow_guest"]]
	olculen = [k for k, v in ANLATIM.items() if v.get("x-measured") == "http"]
	kismi = [k for k, v in ANLATIM.items() if v.get("x-measured") == "http-partial"]
	uyusmayan = [k for k, v in ANLATIM.items() if v.get("x-measured") == "http-fail"]
	uyusmaz_alan = sorted(UYUSMAZLIK)
	olculmeyen = sorted(k for k in (u["key"] for u in uclar) if not ANLATIM.get(k, {}).get("x-measured"))

	return {
		"openapi": OPENAPI_VERSION,
		"info": {
			"title": "İstoç Medya API — GERÇEK HTTP yüzeyi",
			"version": API_VERSION,
			"summary": "`@frappe.whitelist()` taşıyan, /api/method/… ile çağrılabilen medya uçları.",
			"description": (
				"Bu belge `docs/api/openapi.yaml`ın KARDEŞİDİR, KOPYASI DEĞİL. "
				"O belge `tradehub_core/media/pipeline/api/` altındaki SAF PYTHON "
				"kütüphane katmanını anlatır: o katmanda `@frappe.whitelist()` yoktur "
				"(bkz. `pipeline/api/crop.py` başlığı), fonksiyonlar `ApiResponse` "
				"döndürür ve oradaki `/api/media/v1/...` yolları için depoda hiçbir "
				"yönlendirme kuralı bulunmaz — yani o yollara HTTP isteği atılamaz. "
				"Buradaki uçlar ise gerçekten çağrılabilir. İki katman bilerek ayrı "
				"iki dosyada tutulur.\n\n"
				"ÖLÇÜM DURUMU: her operasyonda `x-measured` alanı vardır. `http` = "
				"başarı gövdesi gerçek HTTP çağrısıyla ölçüldü; `http-partial` = uç "
				"çağrıldı ama yalnız ret/doğrulama yolu ölçülebildi (gerekçe "
				"`x-measurement` içinde); `http-fail` = çağrıldı, sözleşmeyi "
				"karşılamadı. Alan hiç yoksa `x-unmeasured` gerekçeyi yazar. "
				"Sözleşmeden sapan ölçülmüş davranışlar `x-contract-deviations` "
				"altında toplu hâlde durur — istemci yazmadan ÖNCE okuyun."
			),
			"license": {"name": "Proprietary", "identifier": "LicenseRef-Istoc-Proprietary"},
		},
		"servers": [{"url": "https://istoc.localhost", "description": "Yerel geliştirme (docker compose)."}],
		"tags": [
			{"name": "delivery", "description": "Teslim manifesti ve imzalı private erişim."},
			{"name": "seller", "description": "Satıcının kendi medya kütüphanesi (mağaza kapsamlı)."},
			{"name": "admin", "description": "Yönetim uçları (rol kapılı)."},
			{"name": "crop", "description": "Kırpma niyeti, odak önerisi ve çözülmüş pencereler."},
			{"name": "storage", "description": "Depolama ayarı ve bağlantı testi."},
			{
				"name": "rum",
				"description": (
					"Gerçek kullanıcı ölçümü (RUM) toplama — misafire açık TEK yazma ucu; "
					"gövde `text/plain` JSON'dur, sorgu parametresi değil."
				),
			},
		],
		"x-layer-note": (
			"HTTP yüzeyi = bu dosya. Kütüphane sözleşmesi = docs/api/openapi.yaml. "
			"İkisini birleştirmeyin: birleştirmek çağrılamayan yollara çağrılabilir "
			"görüntüsü verir."
		),
		"x-endpoint-count": len(uclar),
		"x-guest-endpoints": sorted(misafir),
		"x-measured-endpoints": sorted(olculen),
		"x-partially-measured-endpoints": sorted(kismi),
		"x-unmeasured-endpoints": olculmeyen,
		"x-mismatched-endpoints": sorted(uyusmayan),
		"x-endpoints-with-mismatch": uyusmaz_alan,
		"x-measurement-method": (
			"Her `x-measured` alanı GERÇEK bir `/api/method/…` çağrısından gelir "
			"(2026-08-19, `istoc.localhost`, docker compose). Sahte istemci "
			"kullanılmadı. Ölçümden önce imajdaki `api/*.py` dosyalarının çalışma "
			"ağacıyla `sha256` eşitliği doğrulandı. `Media Engine Settings` "
			"bayrakları ölçüm boyunca 0 kaldı. Yazan uçlar ya kasten var olmayan "
			"hedeflerle (doğrulama yolu), ya da ölçüm için üretilip sonra silinen "
			"test verisiyle çağrıldı; ölçüm sonunda mağaza özeti ölçüm öncesi "
			"değerine döndü."
		),
		"x-contract-deviations": [
			"304 ÜRETİLMEZ. Koşullu istek eşleşse bile HTTP durumu 200'dür; "
			"'değişmedi' bilgisi GÖVDEDE taşınır. Üstelik İKİ AYRI sözleşme var: "
			"`media_manifest.get_manifest` `{not_modified: true, etag, "
			"cache_control}`, `media_crop.get_intent` ise `{etag, status: 304}` "
			"döner. Tek bir istemci ayrıştırıcısı ikisini de tanımak zorundadır.",
			"`frappe.ValidationError` HTTP **417** ile döner, 400 ile değil. "
			"Ölçülen tüm iş kuralı redleri (geçersiz kapsam, geçersiz yedek "
			"kimliği, 0-1 dışı koordinat, bilinmeyen kırpma yöntemi, 'son yedek "
			"silinemez') 417'dir.",
			"Bu katmanda **400 yalnız CSRF** için görülür: oturum çerezli bir POST "
			"`X-Frappe-CSRF-Token` başlığı olmadan gelirse 400 `CSRFTokenError`. "
			"GET isteklerinde CSRF kontrolü YOKTUR.",
			"**Zorunlu parametre eksikse HTTP 500 `TypeError` döner** — 400/417 "
			"değil. Ölçüldü: `get_manifest` (misafir) ve zorunlu parametreli 18 "
			"yönetim ucu (satıcı oturumu) `TypeError: … missing 1 required "
			"positional argument` ile 500 verdi.",
			"**Argüman bağlama, uç içindeki yetki kapısından ÖNCE çalışır.** "
			"Oturum açmış ama yetkisiz bir kullanıcı zorunlu parametreyi "
			"vermezse 403 değil 500 alır; parametreleri verince 403 alır "
			"(49 yönetim/depolama ucunun 49'unda ölçüldü). Misafir bu tuzağa "
			"düşmez: whitelist kapısı argüman bağlamadan önce çalıştığı için "
			"misafir DAİMA 403 alır — 90 ucun oturum isteyen 87'sinin TAMAMINDA "
			"ölçüldü; kalan 3'ü zaten misafire açık uçlar.",
			"`methods=[\"POST\"]` taşıyan bir uç GET ile çağrılınca **403 "
			"`PermissionError: Not permitted`** döner — yani yöntem hatası ile "
			"yetki reddi AYNI durum kodunu paylaşır, yalnız mesaj ayırır.",
			"Bulunamayan kaynak için tek bir durum kodu YOK: `restore_image` ve "
			"`set_access_level` **404 `DoesNotExistError`**, `retry_scan` / "
			"`retry_transcode` / `release_quarantine` **417 `ValidationError`**, "
			"`seller_media.get_my_usage` başka mağazanın dosyası için **404**, "
			"`media_crop.*` başka mağazanın varlığı için **417** döner.",
			"`api/media_crop.py::_throw` `frappe.local.response['http_status_code']` "
			"ile kütüphanenin durum kodunu (ör. 404) korumayı amaçlıyor, ama "
			"ÖLÇÜMDE hiç 404 gözlenmedi: `frappe.throw(..., exc=ValidationError)` "
			"durumu 417'ye çeviriyor. İstemci `media_crop` uçlarında 404 BEKLEMESİN.",
			"`pipeline/api/envelope.py`nin `{error_code, retryable}` zarfı bu "
			"katmanda KULLANILMAZ. Hata gövdesi Frappe'nin `{exception, exc_type, "
			"exc, _server_messages}` zarfıdır.",
			"CSV ve paket indirmeleri farklı davranır: `export_media_audit` CSV'yi "
			"JSON gövdenin İÇİNDE dizge olarak döner, `download_backup_export` ise "
			"`application/zip` ikili gövde döner.",
		],
		"x-frappe-envelope": (
			"Başarı: {\"message\": <gövde>}. Hata: {\"exception\", \"exc_type\", \"exc\"} "
			"ve HTTP durumu (403 PermissionError, 417 ValidationError, 500 diğer). "
			"`pipeline/api/envelope.py`nin {error_code, retryable} zarfı BU KATMANDA "
			"KULLANILMAZ."
		),
		"paths": paths,
		"components": {
			"securitySchemes": {
				"frappeSession": {"type": "apiKey", "in": "cookie", "name": "sid"},
				"frappeToken": {
					"type": "http",
					"scheme": "token",
					"description": "`Authorization: token <api_key>:<api_secret>`",
				},
			},
			"responses": {
				"Denied": {
					"description": (
						"Yetki reddi (`frappe.PermissionError`). Misafir de, yetkisiz "
						"oturum da bunu alır."
					),
					"content": {"application/json": {"schema": {"$ref": "#/components/schemas/FrappeError"}}},
				},
				"Validation": {
					"description": "`frappe.ValidationError` — Frappe bunu 417 ile döner, 400 ile değil.",
					"content": {"application/json": {"schema": {"$ref": "#/components/schemas/FrappeError"}}},
				},
				"RateLimited": {
					"description": (
						"`@rate_limit` kovası doldu — `TooManyRequestsError`. ÖLÇÜLDÜ: "
						"`media_crop.suggest_focal` 60 sn'lik pencerede 29 çağrıya izin "
						"verdi, 30.'yu 429 ile reddetti (`max_calls=30`)."
					),
					"content": {"application/json": {"schema": {"$ref": "#/components/schemas/FrappeError"}}},
				},
				"BadRequest": {
					"description": (
						"ÖLÇÜLDÜ: bu katmandaki TEK 400. Oturum çerezli bir POST "
						"`X-Frappe-CSRF-Token` başlığı olmadan gelirse Frappe "
						"`CSRFTokenError` ile 400 döner. İş mantığı hatası 400 ÜRETMEZ "
						"— o 417'dir."
					),
					"content": {"application/json": {"schema": {"$ref": "#/components/schemas/FrappeError"}}},
				},
				"ServerError": {
					"description": "Beklenmeyen sunucu hatası.",
					"content": {"application/json": {"schema": {"$ref": "#/components/schemas/FrappeError"}}},
				},
			},
			"schemas": SEMALAR,
		},
	}


# ═══════════════════════════════════════════════════════════════════════
# 5. Deterministik YAML yazıcı
# ═══════════════════════════════════════════════════════════════════════

BASLIK = (
	"# ÜRETİLMİŞ DOSYA — ELLE DÜZENLEMEYİN.\n"
	"# Kaynak: scripts/gen_http_openapi.py :: build_document()\n"
	"# Yeniden üret: python3 scripts/gen_http_openapi.py\n"
	"# Sapma testi: tradehub_core/tests/test_http_api_contracts.py\n"
	"#\n"
	"# Bu dosya GERÇEK HTTP yüzeyini anlatır (@frappe.whitelist()).\n"
	"# Kütüphane katmanı için docs/api/openapi.yaml'a bakın — o katman\n"
	"# whitelist TAŞIMAZ ve oradaki yollara istek atılamaz.\n"
)


def _skaler(deger: Any) -> str:
	if deger is True:
		return "true"
	if deger is False:
		return "false"
	if deger is None:
		return "null"
	if isinstance(deger, (int, float)):
		return str(deger)
	metin = str(deger).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
	return f'"{metin}"'


def _emit(deger: Any, girinti: int, out: list[str]) -> None:
	bosluk = "  " * girinti
	if isinstance(deger, dict):
		if not deger:
			out[-1] += " {}"
			return
		for anahtar, alt in deger.items():
			satir = f"{bosluk}{_skaler(anahtar)}:"
			if isinstance(alt, (dict, list)):
				out.append(satir)
				_emit(alt, girinti + 1, out)
			else:
				out.append(f"{satir} {_skaler(alt)}")
	elif isinstance(deger, list):
		if not deger:
			out[-1] += " []"
			return
		for eleman in deger:
			if isinstance(eleman, (dict, list)):
				out.append(f"{bosluk}-")
				_emit(eleman, girinti + 1, out)
			else:
				out.append(f"{bosluk}- {_skaler(eleman)}")


def dump_yaml(document: dict[str, Any]) -> str:
	out: list[str] = [BASLIK.rstrip("\n")]
	_emit(document, 0, out)
	return "\n".join(out) + "\n"


def yaml_path() -> Path:
	return CIKTI


def write_yaml(path: Path | None = None) -> str:
	hedef = Path(path) if path else CIKTI
	hedef.parent.mkdir(parents=True, exist_ok=True)
	hedef.write_text(dump_yaml(build_document()), encoding="utf-8")
	return str(hedef)


# ═══════════════════════════════════════════════════════════════════════
# 6. Doğrulama
# ═══════════════════════════════════════════════════════════════════════


def validate() -> list[str]:
	"""Belgeyi ve `ANLATIM` sözlüğünü koda karşı doğrula. Boş liste = temiz."""
	bulgular: list[str] = []
	kodda = {u["key"] for u in envanter()}
	for anahtar in ANLATIM:
		if anahtar not in kodda:
			bulgular.append(f"ANLATIM'da var, kodda YOK: {anahtar}")
	doc = build_document()
	semalar = set(doc["components"]["schemas"])
	metin = dump_yaml(doc)
	for parca in metin.split('"$ref": "#/components/schemas/')[1:]:
		ad = parca.split('"')[0]
		if ad not in semalar:
			bulgular.append(f"kırık $ref: {ad}")
	gorulen: set[str] = set()
	for _yol, item in doc["paths"].items():
		for _yontem, op in item.items():
			if op["operationId"] in gorulen:
				bulgular.append(f"tekrarlı operationId: {op['operationId']}")
			gorulen.add(op["operationId"])
			if not op.get("responses"):
				bulgular.append(f"yanıtsız operasyon: {op['operationId']}")
			# Her uç ya ÖLÇÜLDÜ ya da NEDEN ölçülmediğini yazar. Sessiz boşluk
			# "geçti" gibi okunur; bu depoda tam olarak o hata iki kez yapıldı.
			if not op.get("x-measured") and not op.get("x-unmeasured"):
				bulgular.append(
					f"ne ölçüm ne gerekçe: {op['x-python']} — `OLCUM`a ya da "
					f"`OLCULMEYEN`e kayıt girin"
				)
	gecerli = {"http", "http-partial", "http-fail"}
	for anahtar, (duzey, _c) in OLCUM.items():
		if duzey not in gecerli:
			bulgular.append(f"bilinmeyen ölçüm düzeyi: {anahtar} → {duzey}")
	return bulgular


def main(argv: list[str]) -> int:
	bulgular = validate()
	if bulgular:
		for b in bulgular:
			print(f"BULGU: {b}", file=sys.stderr)
		return 1
	if "--check" in argv:
		mevcut = CIKTI.read_text(encoding="utf-8") if CIKTI.is_file() else ""
		if mevcut != dump_yaml(build_document()):
			print("SAPMA: docs/api/openapi-http.yaml güncel değil.", file=sys.stderr)
			return 1
		print("temiz")
		return 0
	yol = write_yaml()
	doc = build_document()
	print(f"yazıldı: {yol}")
	print(
		f"uç: {doc['x-endpoint-count']} | misafir: {len(doc['x-guest-endpoints'])} "
		f"| ölçülen: {len(doc['x-measured-endpoints'])} "
		f"| kısmi ölçülen: {len(doc['x-partially-measured-endpoints'])} "
		f"| ölçülmeyen: {len(doc['x-unmeasured-endpoints'])} "
		f"| uyuşmazlık: {len(doc['x-endpoints-with-mismatch'])}"
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main(sys.argv[1:]))
