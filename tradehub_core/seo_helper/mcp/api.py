"""MCP araç seti — Frappe whitelisted uçlar (14.3). MCP süreci (`mcp/server.py`) bunları çağırır.

Araçlar: page_create · page_update · block_add · metadata_suggest · translation_draft ·
seo_audit_run · result_read. **Yazma araçları yalnız `MCP Draft` üretir**; yayın insan onayıyla
(`approve_draft`) ve deterministik doğrulama (11.4, `core.policy.evaluate`) geçince uygulanır.
Her çağrı `MCP Tool Call` kaydıdır (araç, girdi, çıktı, maliyet, süre, sonuç).
"""

from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import now_datetime

from tradehub_core.seo_helper.core.permissions import get_doc_or_deny, require_store_access
from tradehub_core.seo_helper.mcp.auth import require_client, store_scope  # noqa: F401 — _tool_call içinde


@contextmanager
def _tool_call(tool: str, scope: str, store_arg, girdi: dict):
	"""Her araç çağrısı `MCP Tool Call`'a düşer (araç, girdi, çıktı, maliyet, süre, sonuç).
	Kimlik/kapsam burada çözülür ki 403/429 da günlüğe girsin. Hata yolunda: aracın yarım yazdıkları
	geri alınır (rollback), günlük yazılır ve commit edilir — aksi halde Frappe istek hatasında tüm
	işlemi geri aldığı için hata günlükleri HTTP'de hiç kalıcı olmuyordu (monkey bulgusu)."""
	t0 = time.time()
	kayit: dict = {"draft": None, "tokens": (0, 0), "cost": 0.0, "client": None, "store": None}
	sonuc, hata = "ok", ""
	try:
		kayit["client"] = client = require_client(scope)
		istenen_store = _text(store_arg, "store", max_len=140) or None
		if istenen_store and not frappe.db.exists("Admin Seller Profile", istenen_store):
			frappe.throw(_("Mağaza yok: {0}").format(istenen_store), frappe.ValidationError)
		kayit["store"] = store_scope(client, istenen_store)
		yield kayit
	except frappe.PermissionError as e:
		sonuc, hata = "denied", str(e)
		raise
	except Exception as e:  # noqa: BLE001 — sonuç yine de günlüğe düşer, sonra yeniden fırlatılır
		sonuc, hata = "error", f"{type(e).__name__}: {e}"[:500]
		raise
	finally:
		if kayit["client"] is not None:
			_write_tool_log(tool, kayit, girdi, sonuc, hata, t0)


def _write_tool_log(tool: str, kayit: dict, girdi: dict, sonuc: str, hata: str, t0: float) -> None:
	try:
		if sonuc != "ok":
			frappe.db.rollback()
		frappe.get_doc(
			{
				"doctype": "MCP Tool Call",
				"client": kayit["client"].name,
				"tool": tool,
				"store": kayit["store"],
				"input_json": json.dumps(girdi, ensure_ascii=False, default=str)[:20000],
				"output_json": json.dumps(kayit.get("output"), ensure_ascii=False, default=str)[:20000]
				if kayit.get("output") is not None
				else None,
				"cost_tokens_in": kayit["tokens"][0],
				"cost_tokens_out": kayit["tokens"][1],
				"cost_usd": kayit["cost"],
				"duration_ms": int((time.time() - t0) * 1000),
				"result": sonuc,
				"error": hata,
				"draft": kayit.get("draft"),
			}
		).insert(ignore_permissions=True)  # sistem günlüğü; store denetimi araçta yapıldı
		if sonuc != "ok":
			frappe.db.commit()
	except Exception:  # noqa: BLE001
		frappe.log_error(title="MCP Tool Call günlüğü yazılamadı", message=frappe.get_traceback())


def _draft(
	client,
	draft_type: str,
	store: str | None,
	payload: dict,
	target_doctype: str | None = None,
	target_name: str | None = None,
	validation: dict | None = None,
) -> str:
	d = frappe.get_doc(
		{
			"doctype": "MCP Draft",
			"client": client.name,
			"draft_type": draft_type,
			"store": store,
			"target_doctype": target_doctype,
			"target_name": target_name,
			"payload": json.dumps(payload, ensure_ascii=False, default=str),
			"validation": json.dumps(validation or {}, ensure_ascii=False, default=str),
			"status": "draft",
		}
	).insert(ignore_permissions=True)
	return d.name


def _guard_target(client, store: str | None, builder_page: str) -> str | None:
	"""Hedef Builder Page'in GERÇEK mağazası (SEO Page aynası) ile istemci kapsamını karşılaştır;
	döner: taslağa damgalanacak mağaza. Ayna yoksa sayfa platform sayfasıdır (store=None)."""
	if not frappe.db.exists("Builder Page", builder_page):
		frappe.throw(_("Builder sayfası yok: {0}").format(builder_page))
	hedef = frappe.db.get_value("SEO Page", {"builder_page": builder_page}, "store")
	if client.store and hedef != client.store:
		frappe.throw(_("Başka mağazanın sayfası"), frappe.PermissionError)
	if not client.store and store and hedef and hedef != store:
		frappe.throw(_("Başka mağazanın sayfası"), frappe.PermissionError)
	return hedef


def _validate_page_payload(payload: dict, *, route: str | None) -> dict:
	"""Deterministik ön doğrulama (11.4) — politika motorunun saf `evaluate`'i."""
	from tradehub_core.seo_helper.adapters.tradehub import meta as meta_ad
	from tradehub_core.seo_helper.core.policy import evaluate

	policy = (
		frappe.get_doc("SEO Policy", "default").as_dict() if frappe.db.exists("SEO Policy", "default") else {}
	)
	karar = evaluate(
		{
			"route": route or payload.get("route"),
			"slug": payload.get("slug"),
			"lang": payload.get("lang") or "tr",
			"title": payload.get("title"),
			"meta_description": payload.get("meta_description"),
			"publish_state": "draft",
			"robots": payload.get("robots"),
			"canonical_url": payload.get("canonical_url"),
			"has_ugc_html": "<script" in json.dumps(payload).lower(),
		},
		policy,
		site_url=meta_ad.site_url(),
		length_check=meta_ad.check_lengths,
	)
	return karar.as_dict()


# ── argüman zorlama (MCP gövdesi güvenilmez: tipsiz/eksik/bozuk gelir; 500 yerine 417 + günlük) ──

TRANSLATABLE_FIELDS = ("page_title", "meta_description")  # frappe.db.get_value'ya yalnız bu alanlar gider


def _text(v, ad: str, *, required: bool = False, max_len: int = 4000) -> str:
	if v is None or isinstance(v, bool | list | dict | tuple):
		m = ""
	else:
		m = str(v).replace("\x00", "").strip()
	if required and not m:
		frappe.throw(_("'{0}' zorunlu").format(ad), frappe.ValidationError)
	if len(m) > max_len:
		frappe.throw(_("'{0}' çok uzun (> {1})").format(ad, max_len), frappe.ValidationError)
	return m


def _json_arg(v, ad: str, tip):
	"""str ise JSON çöz; None → boş; tip (dict|list) uymuyorsa ValidationError."""
	if isinstance(v, str):
		if not v.strip():
			return tip()
		try:
			v = json.loads(v)
		except json.JSONDecodeError:
			frappe.throw(_("'{0}' geçerli JSON değil").format(ad), frappe.ValidationError)
	if v is None:
		return tip()
	if not isinstance(v, tip):
		frappe.throw(
			_("'{0}' {1} olmalı").format(ad, "nesne" if tip is dict else "liste"), frappe.ValidationError
		)
	return v


def _route_arg(v, ad: str = "route", *, required: bool = True) -> str:
	m = _text(v, ad, required=required, max_len=300)
	if m and (re.search(r"[\s<>\"'\\]", m) or ".." in m):
		frappe.throw(_("'{0}' geçersiz karakter içeriyor").format(ad), frappe.ValidationError)
	return ("/" + m.strip("/")) if m else ""


def _int_arg(v, ad: str) -> int | None:
	if v is None or v == "":
		return None
	try:
		return int(float(v))
	except (TypeError, ValueError):
		frappe.throw(_("'{0}' tam sayı olmalı").format(ad), frappe.ValidationError)


# ── araçlar ────────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["POST"])
def page_create(
	title=None,
	route=None,
	lang="tr",
	meta_description="",
	blocks=None,
	store=None,
) -> dict:
	girdi = {
		"title": title,
		"route": route,
		"lang": lang,
		"meta_description": meta_description,
		"blocks": blocks,
	}
	with _tool_call("page_create", "page:draft", store, girdi) as k:
		client, store = k["client"], k["store"]
		title = _text(title, "title", required=True, max_len=500)
		route = _route_arg(route)
		lang = _text(lang, "lang", max_len=10) or "tr"
		meta_description = _text(meta_description, "meta_description", max_len=2000)
		blocks = _json_arg(blocks, "blocks", list)
		payload = {
			"title": title,
			"route": route,
			"lang": lang,
			"meta_description": meta_description,
			"blocks": blocks or [],
		}
		val = _validate_page_payload(payload, route=payload["route"])
		k["draft"] = _draft(client, "page_create", store, payload, "Builder Page", None, val)
		k["output"] = {"draft": k["draft"], "validation": val}
		return k["output"]


@frappe.whitelist(allow_guest=True, methods=["POST"])
def page_update(builder_page=None, changes=None, store=None) -> dict:
	with _tool_call(
		"page_update", "page:draft", store, {"builder_page": builder_page, "changes": changes}
	) as k:
		client, store = k["client"], k["store"]
		builder_page = _text(builder_page, "builder_page", required=True, max_len=140)
		changes = _json_arg(changes, "changes", dict)
		store = _guard_target(client, store, builder_page)
		sp = frappe.db.get_value(
			"SEO Page",
			{"builder_page": builder_page},
			["store", "route", "title", "meta_description", "lang"],
			as_dict=True,
		)
		birlesik = {**(sp or {}), **changes}
		val = _validate_page_payload(birlesik, route=(sp or {}).get("route"))
		k["draft"] = _draft(client, "page_update", store, changes, "Builder Page", builder_page, val)
		k["output"] = {"draft": k["draft"], "validation": val}
		return k["output"]


@frappe.whitelist(allow_guest=True, methods=["POST"])
def block_add(builder_page=None, block=None, position=None, store=None) -> dict:
	with _tool_call(
		"block_add", "page:draft", store, {"builder_page": builder_page, "block": block, "position": position}
	) as k:
		client, store = k["client"], k["store"]
		builder_page = _text(builder_page, "builder_page", required=True, max_len=140)
		block = _json_arg(block, "block", dict)
		position = _int_arg(position, "position")
		store = _guard_target(client, store, builder_page)
		if not isinstance(block, dict) or not block.get("element"):
			frappe.throw(_("blok bir Builder blok nesnesi olmalı (element alanı zorunlu)"))
		if "<script" in json.dumps(block).lower():
			frappe.throw(_("Blokta script kabul edilmez"))
		k["draft"] = _draft(
			client,
			"block_add",
			store,
			{"block": block, "position": position},
			"Builder Page",
			builder_page,
			{"publishable": True, "findings": []},
		)
		k["output"] = {"draft": k["draft"]}
		return k["output"]


@frappe.whitelist(allow_guest=True, methods=["POST"])
def metadata_suggest(builder_page=None, title="", content="", lang="tr", store=None) -> dict:
	"""OpenAI ile başlık/meta önerisi → taslak. Model çağrısı kota/zaman aşımı/tekrar ile."""
	from tradehub_core.seo_helper.mcp.openai_client import complete

	with _tool_call(
		"metadata_suggest",
		"metadata:suggest",
		store,
		{"builder_page": builder_page, "title": title, "lang": lang},
	) as k:
		client, store = k["client"], k["store"]
		builder_page = _text(builder_page, "builder_page", max_len=140) or None
		title = _text(title, "title", max_len=500)
		content = _text(content, "content", max_len=20000)
		lang = _text(lang, "lang", max_len=10) or "tr"
		if builder_page:
			store = _guard_target(client, store, builder_page)
			bp = (
				frappe.db.get_value(
					"Builder Page", builder_page, ["page_title", "meta_description"], as_dict=True
				)
				or {}
			)
			title = title or bp.get("page_title") or ""
		prompt = (
			f"Dil: {lang}. Aşağıdaki sayfa için SEO başlığı (50-60 karakter) ve meta açıklama (120-155 karakter) öner. "
			f'Yalnız JSON döndür: {{"title": ..., "meta_description": ...}}.\nBaşlık: {title}\nİçerik: {content[:4000]}'
		)
		cevap = complete(prompt, client=client, max_output_tokens=300)
		k["tokens"], k["cost"] = (cevap["tokens_in"], cevap["tokens_out"]), cevap["cost_usd"]
		try:
			oneri = json.loads(cevap["text"][cevap["text"].index("{") : cevap["text"].rindex("}") + 1])
		except (ValueError, json.JSONDecodeError):
			oneri = {"title": "", "meta_description": "", "raw": cevap["text"]}
		val = _validate_page_payload(
			{
				"title": oneri.get("title"),
				"meta_description": oneri.get("meta_description"),
				"lang": lang,
				"route": "/x",
			},
			route="/x",
		)
		k["draft"] = _draft(client, "metadata", store, oneri, "Builder Page", builder_page, val)
		k["output"] = {"draft": k["draft"], "suggestion": oneri, "validation": val, "model": cevap["model"]}
		return k["output"]


@frappe.whitelist(allow_guest=True, methods=["POST"])
def translation_draft(builder_page=None, target_lang=None, fields=None, store=None) -> dict:
	from tradehub_core.seo_helper.mcp.openai_client import complete

	with _tool_call(
		"translation_draft",
		"translation:draft",
		store,
		{"builder_page": builder_page, "target_lang": target_lang, "fields": fields},
	) as k:
		client, store = k["client"], k["store"]
		builder_page = _text(builder_page, "builder_page", required=True, max_len=140)
		target_lang = _text(target_lang, "target_lang", required=True, max_len=10)
		# alan listesi sorguya gider → yalnız beyaz liste (SQL yüzeyi kapalı)
		istenen = _json_arg(fields, "fields", list) or list(TRANSLATABLE_FIELDS)
		fields = [f for f in istenen if isinstance(f, str) and f in TRANSLATABLE_FIELDS]
		if not fields:
			frappe.throw(
				_("fields yalnız {0} olabilir").format(", ".join(TRANSLATABLE_FIELDS)), frappe.ValidationError
			)
		store = _guard_target(client, store, builder_page)
		bp = frappe.db.get_value("Builder Page", builder_page, fields, as_dict=True)
		if not bp:
			frappe.throw(_("Builder sayfası yok: {0}").format(builder_page))
		prompt = f"Şu alanları {target_lang} diline çevir, yalnız JSON döndür (aynı anahtarlar): {json.dumps(bp, ensure_ascii=False)}"
		cevap = complete(prompt, client=client, max_output_tokens=800)
		k["tokens"], k["cost"] = (cevap["tokens_in"], cevap["tokens_out"]), cevap["cost_usd"]
		try:
			ceviri = json.loads(cevap["text"][cevap["text"].index("{") : cevap["text"].rindex("}") + 1])
		except (ValueError, json.JSONDecodeError):
			ceviri = {"raw": cevap["text"]}
		k["draft"] = _draft(
			client,
			"translation",
			store,
			{"target_lang": target_lang, "fields": ceviri},
			"Builder Page",
			builder_page,
			{"publishable": bool(ceviri), "findings": []},
		)
		k["output"] = {"draft": k["draft"], "translation": ceviri}
		return k["output"]


@frappe.whitelist(allow_guest=True, methods=["POST"])
def seo_audit_run(routes=None, store=None) -> dict:
	"""Denetimi ayrı kuyrukta (mcp) başlatır; sonuç `result_read` ile okunur."""
	from tradehub_core.seo_helper.core.queue import enqueue_after_commit

	with _tool_call("seo_audit_run", "audit:run", store, {"routes": routes}) as k:
		client, store = k["client"], k["store"]
		routes = [_route_arg(r, "routes[]") for r in _json_arg(routes, "routes", list)[:500]]
		run = frappe.get_doc(
			{
				"doctype": "SEO Crawl Run",
				"scope": json.dumps({"routes": routes, "store": store}),
				"status": "queued",
				"triggered_by": f"mcp:{client.name}",
				"queue": "mcp",
			}
		).insert(ignore_permissions=True)
		job = enqueue_after_commit(
			"mcp.long",
			{"tool": "audit", "crawl_run": run.name},
			store=store,
			queue="mcp",
			dedupe_key=f"audit:{run.name}",
		)
		k["output"] = {"crawl_run": run.name, "job": job}
		return k["output"]


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def result_read(crawl_run=None, draft=None, store=None) -> dict:
	with _tool_call("result_read", "audit:read", store, {"crawl_run": crawl_run, "draft": draft}) as k:
		store = k["store"]
		crawl_run = _text(crawl_run, "crawl_run", max_len=140) or None
		draft = _text(draft, "draft", max_len=140) or None
		if not crawl_run and not draft:
			frappe.throw(_("crawl_run ya da draft zorunlu"), frappe.ValidationError)
		out: dict = {}
		if crawl_run:
			run = frappe.db.get_value(
				"SEO Crawl Run",
				crawl_run,
				["status", "pages_total", "pages_ok", "findings", "started_at", "finished_at"],
				as_dict=True,
			)
			if not run:
				frappe.throw(_("Tarama yok"))
			filters = {"crawl_run": crawl_run}
			if store:
				filters["store"] = store
			out["run"] = run
			out["findings"] = frappe.get_all(
				"SEO Audit Finding",
				filters=filters,
				fields=["route", "severity", "code", "message"],
				limit_page_length=500,
			)
		if draft:
			d = frappe.db.get_value(
				"MCP Draft",
				draft,
				["status", "draft_type", "target_name", "validation", "store", "review_note"],
				as_dict=True,
			)
			if not d or (store and d.store and d.store != store):
				frappe.throw(_("Taslak yok"), frappe.PermissionError)
			out["draft"] = d
		k["output"] = out
		return out


# ── insan onayı (panel/Desk oturumu; MCP anahtarı DEĞİL) ────────────────


@frappe.whitelist()
def approve_draft(draft: str, note: str = "") -> dict:
	"""SEO Editor/Manager ya da mağaza sahibi onaylar → taslak Builder Page'e uygulanır.
	Deterministik doğrulama geçmemiş taslak onaylanamaz (11.4)."""
	d = get_doc_or_deny("MCP Draft", draft)
	require_store_access(_draft_store(d), "write")
	if d.status != "draft":
		frappe.throw(_("Yalnız 'draft' durumundaki taslak onaylanır"))
	val = json.loads(d.validation or "{}")
	if val and val.get("publishable") is False:
		frappe.throw(
			_("Deterministik doğrulama geçmedi: {0}").format(
				", ".join(f["code"] for f in val.get("findings", []))
			)
		)
	payload = json.loads(d.payload or "{}")
	hedef = _apply_draft(d, payload)
	d.db_set(
		{
			"status": "applied",
			"reviewed_by": frappe.session.user,
			"reviewed_at": now_datetime(),
			"review_note": note,
			"applied_at": now_datetime(),
			"target_name": hedef or d.target_name,
		}
	)
	return {"ok": True, "target": hedef}


@frappe.whitelist()
def reject_draft(draft: str, note: str = "") -> dict:
	d = get_doc_or_deny("MCP Draft", draft)
	require_store_access(_draft_store(d), "write")
	d.db_set(
		{
			"status": "rejected",
			"reviewed_by": frappe.session.user,
			"reviewed_at": now_datetime(),
			"review_note": note,
		}
	)
	return {"ok": True}


def _draft_store(d) -> str | None:
	"""Onay anında hedefin GERÇEK mağazası (taslak açıldıktan sonra değişmiş olabilir)."""
	if d.target_doctype == "Builder Page" and d.target_name:
		return frappe.db.get_value("SEO Page", {"builder_page": d.target_name}, "store") or d.store
	return d.store


def _apply_draft(d, payload: dict) -> str | None:
	"""Taslağı Builder Page'e yaz — sayfa YAYINLANMAZ (published=0); yayın ayrı insan adımı."""
	if d.draft_type == "page_create":
		bp = frappe.get_doc(
			{
				"doctype": "Builder Page",
				"page_title": payload.get("title"),
				"route": payload["route"].strip("/"),
				"published": 0,
				"meta_description": payload.get("meta_description"),
				"language": payload.get("lang"),
				"blocks": json.dumps(payload.get("blocks") or []),
			}
		)
		bp.insert()  # oturum onaylayan kullanıcı; Builder izinleri geçerli
		return bp.name
	bp = frappe.get_doc("Builder Page", d.target_name)
	if d.draft_type == "page_update":
		for k, v in payload.items():
			if k in ("page_title", "title"):
				bp.page_title = v
			elif k in ("meta_description", "canonical_url", "route", "meta_image"):
				bp.set(k, v)
	elif d.draft_type == "block_add":
		blocks = json.loads(bp.draft_blocks or bp.blocks or "[]")
		pos = payload.get("position")
		blocks.insert(pos if isinstance(pos, int) else len(blocks), payload["block"])
		bp.draft_blocks = json.dumps(blocks)
	elif d.draft_type == "metadata":
		bp.page_title = payload.get("title") or bp.page_title
		bp.meta_description = payload.get("meta_description") or bp.meta_description
	elif d.draft_type == "translation":
		# Çeviri: hedef dilde SEO Page aynası (Builder çok dilli sayfayı ayrı Builder Page olarak ister) —
		# ilk sürümde SEO Page kaydına yazılır; Builder tarafı 7.9'da.
		sp_name = frappe.db.get_value(
			"SEO Page", {"builder_page": bp.name, "lang": payload["target_lang"]}, "name"
		)
		f = payload.get("fields") or {}
		veri = {
			"builder_page": bp.name,
			"lang": payload["target_lang"],
			"route": "/" + bp.route.strip("/"),
			"title": f.get("page_title"),
			"meta_description": f.get("meta_description"),
			"source": "mcp",
			"store": d.store,
		}
		sp = frappe.get_doc("SEO Page", sp_name) if sp_name else frappe.new_doc("SEO Page")
		sp.update(veri)
		sp.flags.ignore_permissions = True
		sp.save()
		return sp.name
	bp.save()
	return bp.name
