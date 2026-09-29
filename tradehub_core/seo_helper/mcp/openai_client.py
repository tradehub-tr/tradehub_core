"""OpenAI ince istemcisi (14.4) — zaman aşımı, tekrar deneme ve kota sınırı ile.

`openai` paketi bench'te yok; Responses API'ye `requests` ile gidilir. Anahtar
`site_config.openai_api_key` (kod/DB'de saklanmaz). Her çağrı `MCP Tool Call`'a token/maliyet
yazar; aylık kota `MCP Client.tokens_used_month` + Settings bütçesi ile kesilir.
"""

from __future__ import annotations

import time

import frappe
import requests
from frappe import _

ENDPOINT = "https://api.openai.com/v1/responses"
RETRY_STATUS = {429, 500, 502, 503, 504}
# Kaba fiyat tablosu (USD / 1M token) — maliyet İZLEME içindir, fatura değil; Settings'ten ezilebilir.
PRICE = {"gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.00, 8.00), "gpt-4o-mini": (0.15, 0.60)}


class QuotaExceeded(frappe.ValidationError):
	http_status_code = 429


def _settings():
	return frappe.get_cached_doc("SEO Helper Settings")


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
	fi, fo = PRICE.get(model, (1.0, 4.0))
	return round(tokens_in / 1e6 * fi + tokens_out / 1e6 * fo, 6)


def check_quota(client, tahmini_token: int = 0) -> None:
	s = _settings()
	if s.mcp_monthly_token_budget:
		ay = frappe.db.sql(
			"select coalesce(sum(cost_tokens_in+cost_tokens_out),0) from `tabMCP Tool Call` where creation >= date_format(now(), '%Y-%m-01')"
		)[0][0]
		if int(ay) + tahmini_token > int(s.mcp_monthly_token_budget):
			raise QuotaExceeded(_("Platform aylık MCP token bütçesi doldu"))
	if (
		client
		and client.monthly_token_budget
		and int(client.tokens_used_month or 0) + tahmini_token > int(client.monthly_token_budget)
	):
		raise QuotaExceeded(_("İstemci aylık token bütçesi doldu"))


def complete(
	prompt: str, *, client=None, model: str | None = None, max_output_tokens: int = 800, post=None
) -> dict:
	"""Tek metin tamamlama. Döner {text, tokens_in, tokens_out, model, attempts, cost_usd}.
	`post` test için enjekte edilebilir (requests.post imzası)."""
	s = _settings()
	model = model or s.openai_model or "gpt-4.1-mini"
	timeout = int(s.mcp_call_timeout_sec or 60)
	retries = int(s.mcp_max_retries or 2)
	api_key = frappe.conf.get("openai_api_key")
	if not api_key:
		frappe.throw(_("site_config.openai_api_key tanımlı değil"), frappe.ValidationError)
	check_quota(client, max_output_tokens)
	post = post or requests.post
	body = {"model": model, "input": prompt, "max_output_tokens": max_output_tokens}
	son_hata = None
	for deneme in range(retries + 1):
		try:
			r = post(
				ENDPOINT,
				json=body,
				headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
				timeout=timeout,
			)
		except requests.RequestException as e:
			son_hata = f"{type(e).__name__}: {e}"
			time.sleep(min(2**deneme, 8))
			continue
		if r.status_code in RETRY_STATUS and deneme < retries:
			son_hata = f"HTTP {r.status_code}"
			time.sleep(min(2**deneme, 8))
			continue
		if r.status_code >= 400:
			frappe.throw(
				_("OpenAI hatası {0}: {1}").format(r.status_code, (r.text or "")[:200]),
				frappe.ValidationError,
			)
		data = r.json()
		usage = data.get("usage") or {}
		ti, to = int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
		text = ""
		for item in data.get("output") or []:
			for c in item.get("content") or []:
				if c.get("type") in ("output_text", "text"):
					text += c.get("text") or ""
		if client:
			frappe.db.sql(
				"update `tabMCP Client` set tokens_used_month = coalesce(tokens_used_month,0) + %s, calls_month = coalesce(calls_month,0) + 1 where name=%s",
				(ti + to, client.name),
			)
		return {
			"text": text.strip(),
			"tokens_in": ti,
			"tokens_out": to,
			"model": model,
			"attempts": deneme + 1,
			"cost_usd": cost_usd(model, ti, to),
		}
	frappe.throw(
		_("OpenAI'ye ulaşılamadı ({0} deneme): {1}").format(retries + 1, son_hata), frappe.ValidationError
	)
