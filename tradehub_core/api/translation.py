"""Faz 4 — Auto-Translate (cross-border B2B).

Provider: OpenAI GPT-4o-mini (önerilen). Site config'inde
`openai_api_key` set ise gerçek API çağrısı yapar; yoksa STUB modu
(basit prefix etiketi ekler) ile çalışır → test edilebilir.

Frappe site config'inde aşağıdakileri ayarlayın (opsiyonel):
  - openai_api_key
  - openai_model       (default: gpt-4o-mini)
  - translation_provider (default: openai-stub)
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

DEFAULT_PROVIDER = "openai-stub"
DEFAULT_MODEL = "gpt-4o-mini"
SUPPORTED_LANGS = ("tr", "en", "de", "fr", "es", "it", "ar", "ru", "zh")


def _detect_language(text: str) -> str:
	"""Basit dil tespiti — Türkçe karakter sayısına göre.

	Production'da langdetect/cld3 kullanılır; burada offline minimal
	heuristic: Türkçe karakterler (ç, ğ, ı, ö, ş, ü) → "tr", aksi → "en".
	"""
	if not text:
		return "en"
	tr_chars = sum(1 for c in text.lower() if c in "çğıöşüâî")
	if tr_chars >= max(1, len(text) // 50):
		return "tr"
	return "en"


def _get_provider() -> tuple[str, str | None, str]:
	"""Translation Settings (Single) doctype'tan provider config oku.

	Doctype yoksa veya boşsa stub'a düş. site_config (frappe.conf) fallback'i
	geriye dönük uyumluluk için korunur.
	"""
	# Önce Single doctype'tan dene
	try:
		if frappe.db.table_exists("tabSingles"):
			settings = frappe.get_single("Translation Settings")
			provider = settings.provider or DEFAULT_PROVIDER
			model = settings.openai_model or DEFAULT_MODEL
			api_key = None
			if provider == "openai":
				api_key = settings.get_password("openai_api_key", raise_exception=False)
			elif provider == "deepl":
				api_key = settings.get_password("deepl_api_key", raise_exception=False)
			if provider in ("openai", "deepl") and not api_key:
				provider = "stub"
			return provider, api_key, model
	except Exception:
		frappe.log_error(frappe.get_traceback(), "translation.get_provider")
		pass

	# Fallback: site_config
	conf = frappe.conf
	provider = conf.get("translation_provider", DEFAULT_PROVIDER)
	api_key = conf.get("openai_api_key")
	model = conf.get("openai_model", DEFAULT_MODEL)
	if provider == "openai" and not api_key:
		provider = "stub"
	return provider, api_key, model


def _check_quota_and_increment() -> tuple[bool, str]:
	"""Günlük kota kontrolü + atomik increment.

	Returns: (allowed, reason)
	"""
	try:
		settings = frappe.get_single("Translation Settings")
		quota = int(settings.daily_quota or 0)
		used = int(settings.usage_today or 0)
		if quota > 0 and used >= quota:
			return False, "daily_quota_exceeded"
		# Increment
		frappe.db.set_single_value("Translation Settings", "usage_today", used + 1)
		return True, ""
	except Exception:
		frappe.log_error(frappe.get_traceback(), "translation.check_quota")
		# Settings yoksa quota kontrolü atlanır
		return True, ""


def _log_usage(
	translation_name: str | None,
	provider: str,
	source_lang: str,
	target_lang: str,
	tokens: int = 0,
	cost_usd: float = 0.0,
	ok: bool = True,
):
	"""Translation Usage Log kaydı."""
	try:
		doc = frappe.new_doc("Translation Usage Log")
		doc.translation = translation_name
		doc.provider = provider
		doc.source_lang = source_lang
		doc.target_lang = target_lang
		doc.tokens_used = tokens
		doc.cost_usd = cost_usd
		doc.ok = 1 if ok else 0
		doc.logged_at = now_datetime()
		doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "translation.log_usage")
		# Log kaydı kritik değil
		pass


def daily_reset_usage():
	"""Daily scheduler — usage_today sayacını sıfırla."""
	try:
		frappe.db.set_single_value("Translation Settings", "usage_today", 0)
		frappe.db.set_single_value("Translation Settings", "last_reset_at", now_datetime())
	except Exception:
		frappe.log_error(frappe.get_traceback(), "translation.daily_reset_usage")
		pass


def _translate_with_openai(text: str, source_lang: str, target_lang: str, api_key: str, model: str) -> str:
	"""Gerçek OpenAI çağrısı. Bu fonksiyon yalnız api_key set ise tetiklenir.

	Test ortamında stub kullanılır (api_key yok).
	"""
	import json as _json
	import urllib.request

	prompt = (
		f"Translate the following {source_lang} text to {target_lang}. "
		"Keep the B2B/commerce tone. Return only the translation without quotes.\n\n"
		f"Text: {text}"
	)
	payload = {
		"model": model,
		"messages": [{"role": "user", "content": prompt}],
		"temperature": 0.2,
	}
	req = urllib.request.Request(
		"https://api.openai.com/v1/chat/completions",
		data=_json.dumps(payload).encode("utf-8"),
		headers={
			"Content-Type": "application/json",
			"Authorization": f"Bearer {api_key}",
		},
	)
	with urllib.request.urlopen(req, timeout=30) as resp:
		data = _json.loads(resp.read().decode("utf-8"))
	return data["choices"][0]["message"]["content"].strip()


def _translate_stub(text: str, source_lang: str, target_lang: str) -> str:
	"""STUB provider — gerçek çeviri yok, deterministic prefix ekler.

	Test ve geliştirme için. Production'da OpenAI key set edilir.
	"""
	if source_lang == target_lang:
		return text
	prefix = f"[{source_lang}→{target_lang}] "
	return prefix + text


def translate(text: str, target_lang: str, source_lang: str | None = None) -> dict:
	"""Çekirdek translate fonksiyonu. Provider'a göre dispatch eder."""
	if not text:
		return {
			"text": "",
			"source_lang": source_lang or "en",
			"target_lang": target_lang,
			"translator": "noop",
		}
	src = source_lang or _detect_language(text)
	if src == target_lang:
		return {"text": text, "source_lang": src, "target_lang": target_lang, "translator": "noop"}

	provider, api_key, model = _get_provider()
	if provider == "openai" and api_key:
		# Quota check
		allowed, reason = _check_quota_and_increment()
		if not allowed:
			frappe.log_error(title="translate_quota", message="Daily quota exceeded — falling back to stub")
			stub_text = _translate_stub(text, src, target_lang)
			return {
				"text": stub_text,
				"source_lang": src,
				"target_lang": target_lang,
				"translator": "stub-quota",
			}
		try:
			result = _translate_with_openai(text, src, target_lang, api_key, model)
			# Rough cost estimate (gpt-4o-mini: $0.15 / 1M tokens input)
			tokens_est = len(text) // 4  # rough char→token
			cost = (tokens_est / 1_000_000) * 0.15
			return {
				"text": result,
				"source_lang": src,
				"target_lang": target_lang,
				"translator": f"openai/{model}",
				"_tokens": tokens_est,
				"_cost": cost,
			}
		except Exception as e:
			frappe.log_error(title="openai_translate_failed", message=str(e))
			# fallback to stub
	stub_text = _translate_stub(text, src, target_lang)
	return {"text": stub_text, "source_lang": src, "target_lang": target_lang, "translator": "stub"}


@frappe.whitelist(allow_guest=True)
def get_review_translation(review: str, target_lang: str = "tr"):
	"""Public — bir yorumun çevirisini döner (cache hit varsa hızlı)."""
	if not review or not frappe.db.exists("Listing Review", review):
		frappe.throw(_("Yorum bulunamadı"), frappe.DoesNotExistError)
	if target_lang not in SUPPORTED_LANGS:
		frappe.throw(_("Desteklenmeyen hedef dil"))

	# Cache?
	existing = frappe.db.get_value(
		"Review Translation",
		{"review": review, "target_lang": target_lang},
		["name", "source_lang", "translated_title", "translated_body", "translator", "cached_at"],
		as_dict=True,
	)
	if existing:
		return {
			"cached": True,
			"source_lang": existing.source_lang,
			"target_lang": target_lang,
			"translated_title": existing.translated_title,
			"translated_body": existing.translated_body,
			"translator": existing.translator,
			"cached_at": existing.cached_at,
		}

	# Yoksa: review'in title + body'sini çek, çevir, cache'le
	rev = frappe.db.get_value("Listing Review", review, ["title", "body"], as_dict=True)
	if not rev:
		frappe.throw(_("Yorum bulunamadı"), frappe.DoesNotExistError)

	t = translate(rev.title or "", target_lang)
	b = translate(rev.body or "", target_lang)
	src = b["source_lang"]

	doc = frappe.new_doc("Review Translation")
	doc.review = review
	doc.source_lang = src
	doc.target_lang = target_lang
	doc.translator = b["translator"]
	doc.cached_at = now_datetime()
	doc.translated_title = t["text"]
	doc.translated_body = b["text"]
	doc.insert(ignore_permissions=True)

	# Usage log (sadece gerçek API çağrılmışsa)
	if "openai" in b["translator"]:
		_log_usage(
			translation_name=doc.name,
			provider=b["translator"],
			source_lang=src,
			target_lang=target_lang,
			tokens=int(b.get("_tokens", 0)),
			cost_usd=float(b.get("_cost", 0)),
			ok=True,
		)

	# Listing Review.detected_language cache'le
	frappe.db.set_value(
		"Listing Review",
		review,
		{"detected_language": src, "is_translation_available": 1},
		update_modified=False,
	)
	frappe.db.commit()

	return {
		"cached": False,
		"source_lang": src,
		"target_lang": target_lang,
		"translated_title": t["text"],
		"translated_body": b["text"],
		"translator": b["translator"],
		"cached_at": doc.cached_at,
	}


@frappe.whitelist()
def request_translation(review: str, target_lang: str = "tr"):
	"""Admin manuel tetikleme — cache'i bypass eder, yeniden çevirir."""
	from tradehub_core.api.review import _is_admin

	if not _is_admin():
		frappe.throw(_("Yetkisiz"), frappe.PermissionError)
	# Mevcut cache'i sil
	for n in frappe.get_all(
		"Review Translation", filters={"review": review, "target_lang": target_lang}, pluck="name"
	):
		frappe.delete_doc("Review Translation", n, ignore_permissions=True, force=True)
	return get_review_translation(review=review, target_lang=target_lang)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler: cache cleanup (30+ gün eski cache'leri sil)
# ─────────────────────────────────────────────────────────────────────────────
def cleanup_old_cache():
	"""Daily — 30 günden eski Review Translation kayıtlarını siler."""
	from frappe.utils import add_to_date

	cutoff = add_to_date(now_datetime(), days=-30)
	old = frappe.get_all("Review Translation", filters={"cached_at": ["<", cutoff]}, pluck="name")
	for n in old:
		try:
			frappe.delete_doc("Review Translation", n, ignore_permissions=True, force=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "translation.cleanup_old_cache")
			pass
