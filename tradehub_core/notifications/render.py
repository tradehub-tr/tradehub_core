"""Yayınlanmış (ya da test için taslak) içerikten kanal mesajı üretir.

Dil seçimi: istenen dil, o sürümün snapshot'ında "hazir" ise kullanılır; değilse TR (kaynak)
içeriğe düşülür. Seçilen ve kullanılan dil ayrı döner (gönderim kaydına yazılır). "kopya" durumundaki
içerik gerçek çeviri sayılmaz.

Güvenlik: e-posta gövdesi render ÖNCESİ ve SONRASI allowlist'ten geçer (değer kaynaklı
`javascript:` bağlantı ikinci geçişte düşer); düz metin alanlarına değer olduğu gibi girer;
uygulama içi bağlantı render sonrası `safe_url` ile ayrıca doğrulanır.
"""

from __future__ import annotations

import re

from tradehub_core.notifications import catalog, email_layout, template_lang
from tradehub_core.notifications.sanitize import clean_html

PREFS_PATH = "/pages/dashboard/settings.html#bildirimler"


def resolve_lang(content: dict, channel: str, requested: str, states: dict) -> tuple[dict | None, str]:
	by_lang = (content or {}).get(channel) or {}
	if requested != catalog.SOURCE_LANG and states.get(requested) == "hazir" and by_lang.get(requested):
		return by_lang[requested], requested
	return by_lang.get(catalog.SOURCE_LANG), catalog.SOURCE_LANG


def _text(value: str, data: dict) -> str:
	return template_lang.render(value or "", data, "text").strip()


def html_to_text(html: str) -> str:
	s = re.sub(r"<a\b[^>]*href=\"([^\"]*)\"[^>]*>([\s\S]*?)</a>", r"\2: \1", html or "", flags=re.I)
	s = re.sub(r"</(p|h1|h2|h3|tr|li|div)>|<br\s*/?>", "\n", s, flags=re.I)
	s = re.sub(r"<[^>]+>", "", s)
	for a, b in (
		("&nbsp;", " "),
		("&amp;", "&"),
		("&lt;", "<"),
		("&gt;", ">"),
		("&quot;", '"'),
		("&#x27;", "'"),
	):
		s = s.replace(a, b)
	return re.sub(r"\n{3,}", "\n\n", "\n".join(line.strip() for line in s.split("\n"))).strip()


def build_message(
	event_key: str,
	channel: str,
	fields: dict,
	data: dict,
	lang: str,
	*,
	mandatory: bool,
	base_url: str = "",
	sms_currency_as_text: bool = False,
) -> dict:
	if channel == "email":
		subject = _text(fields.get("subject"), data)
		preheader = _text(fields.get("preheader"), data)
		body = clean_html(template_lang.render(clean_html(fields.get("html") or ""), data, "html"))
		text = _text(fields.get("text"), data) or html_to_text(body)
		category = catalog.CATEGORIES.get((catalog.get(event_key) or {}).get("category"), {})
		html = email_layout.page(
			lang,
			subject,
			preheader,
			category.get("title", "iStoc"),
			body,
			email_layout.footer(lang, f"{base_url}{PREFS_PATH}", mandatory),
		)
		return {"subject": subject, "html": html, "text": text}
	if channel == "inapp":
		return {
			"title": _text(fields.get("title"), data)[:200],
			"message": _text(fields.get("message"), data)[:1000],
			"action_label": _text(fields.get("action_label"), data),
			"action_url": template_lang.safe_url(_text(fields.get("action_url"), data)),
		}
	if channel == "push":
		return {"title": _text(fields.get("title"), data), "body": _text(fields.get("body"), data)}
	text = _text(fields.get("text"), data)
	if sms_currency_as_text:
		text = text.replace("₺", "TL")
	return {"text": text}
