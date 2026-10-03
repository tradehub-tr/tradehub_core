"""Şablon içerik doğrulaması (sunucu). Panel `utils/notificationTemplates/validation.js` ile aynı
kuralları uygular; tür adları API sözleşmesindeki `Issue.kind` enum'udur.

Ayrıca kayıt anında uygulanan normalize (HTML temizleme, izinsiz alan reddi, boyut sınırı) burada.
Saf modül: frappe gerekmez.
"""

from __future__ import annotations

import re

from tradehub_core.notifications import catalog, template_lang
from tradehub_core.notifications.sanitize import ANCHOR_RE, anchor_href, clean_html, href_ok, strip_tags

GSM = (
	"@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZ"
	"ÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM_EXT = "^{}\\[~]|€"
TR_NON_GSM = "şŞğĞıİç"

BLOCKING = {
	"unknown_variable",
	"missing_required_variable",
	"empty_required_field",
	"invalid_url",
	"missing_action_label",
	"missing_action_url",
	"unclosed_loop",
	"unclosed_condition",
}

MESSAGES = {
	"unknown_variable": "Tanımsız değişken: {{{{{variable}}}}}",
	"missing_required_variable": "Zorunlu değişken içerikte yok: {{{{{variable}}}}}",
	"empty_required_field": "Zorunlu alan boş",
	"invalid_url": "Geçersiz bağlantı",
	"too_long": "Metin önerilen uzunluğu aşıyor",
	"missing_translation": "Çeviri hazır değil",
	"missing_action_label": "Düğme metni eksik",
	"missing_action_url": "Düğme bağlantısı eksik",
	"unclosed_loop": "Döngü başı ve sonu eşleşmiyor",
	"unclosed_condition": "Koşul başı ve sonu eşleşmiyor",
	"sms_unicode": "SMS Unicode olarak gider; segment sınırı 70 karakter",
	"sms_segments": "SMS birden çok segment olarak ücretlendirilir",
	"missing_event_data": "Olay verisinde zorunlu değer eksik",
}


def issue(kind, channel, lang, field, variable=None):
	out = {
		"kind": kind,
		"channel": channel,
		"lang": lang,
		"field": field or "",
		"message": MESSAGES[kind].format(variable=variable or ""),
	}
	if variable:
		out["variable"] = variable
	return out


class FieldError(ValueError):
	"""Kayıt anında reddedilen alan (izinsiz alan, tip, boyut)."""

	def __init__(self, field_errors: dict):
		super().__init__("field errors")
		self.field_errors = field_errors


def normalize_fields(channel: str, fields) -> dict:
	"""Kayıt öncesi: yalnız kanalın alanları, metin tipi, boyut sınırı, HTML temizliği."""
	if not isinstance(fields, dict):
		raise FieldError({"fields": "Alanlar nesne olmalı."})
	allowed = catalog.FIELDS[channel]
	errors = {}
	out = {}
	for name, value in fields.items():
		if name not in allowed:
			errors[name] = "Bu kanalda böyle bir alan yok."
			continue
		if value is None:
			value = ""
		if not isinstance(value, str):
			errors[name] = "Metin olmalı."
			continue
		limit = catalog.FIELD_HARD_MAX.get(name, catalog.DEFAULT_HARD_MAX)
		if len(value) > limit:
			errors[name] = f"En fazla {limit} karakter."
			continue
		if allowed[name].get("html"):
			value = clean_html(value)
		elif channel != "email" or name != "text":
			# Düz metin alanlarında HTML etiketi taşınmaz.
			value = strip_tags(value) if "<" in value else value
		out[name] = value
	if errors:
		raise FieldError(errors)
	for name in allowed:
		out.setdefault(name, "")
	return out


def sms_info(text: str, currency_as_text: bool = False) -> dict:
	if currency_as_text:
		text = text.replace("₺", "TL")
	length = 0
	unicode_ = False
	turkish = False
	for ch in text:
		if ch in GSM:
			length += 1
		elif ch in GSM_EXT:
			length += 2
		else:
			unicode_ = True
			turkish = turkish or ch in TR_NON_GSM
	if unicode_:
		length = len(text)
	single, multi = (70, 67) if unicode_ else (160, 153)
	segments = 0 if not length else (1 if length <= single else -(-length // multi))
	return {"length": length, "unicode": unicode_, "turkish": turkish, "segments": segments}


def _sample_scope(variables):
	return {v["name"]: v.get("sample") for v in variables if not v.get("scope")}


def validate_scope(data, channel, lang, variables, required, conditional=None, sms_currency_as_text=False):
	"""Tek kanal × dil. data None ise içerik yok → sorun üretilmez."""
	if not data:
		return []
	known = {v["name"] for v in variables}
	out = []
	used = set()
	for fname, spec in catalog.FIELDS[channel].items():
		value = str(data.get(fname) or "")
		plain = re.sub(r"<[^>]+>", "", value).replace("&nbsp;", " ") if spec.get("html") else value
		if spec.get("required") and not plain.strip():
			out.append(issue("empty_required_field", channel, lang, fname))
		kind = template_lang.structure_issue(value)
		if kind in ("unclosed_loop", "unclosed_condition"):
			out.append(issue(kind, channel, lang, fname))
		elif kind == "too_deep":
			out.append(issue("unclosed_loop", channel, lang, fname))
		seen = set()
		for t in template_lang.tokens(value):
			if not t["name"]:
				continue
			used.add(t["name"])
			if t["name"] not in known and t["name"] not in seen:
				seen.add(t["name"])
				out.append(issue("unknown_variable", channel, lang, fname, t["name"]))
		if spec.get("max") and len(value) > spec["max"]:
			out.append(issue("too_long", channel, lang, fname))
		if spec.get("url") and value.strip() and not template_lang.url_template_ok(value, variables):
			out.append(issue("invalid_url", channel, lang, fname))
		if spec.get("html"):
			for m in ANCHOR_RE.finditer(value):
				href = anchor_href(m.group("attrs"))
				if href is None or not (href_ok(href) and template_lang.url_template_ok(href, variables)):
					out.append(issue("invalid_url", channel, lang, fname))
				if not re.sub(r"<[^>]+>", "", m.group("label")).strip():
					out.append(issue("missing_action_label", channel, lang, fname))
	if channel == "inapp":
		label = str(data.get("action_label") or "").strip()
		url = str(data.get("action_url") or "").strip()
		if url and not label:
			out.append(issue("missing_action_label", channel, lang, "action_label"))
		if label and not url:
			out.append(issue("missing_action_url", channel, lang, "action_url"))
	for name in required:
		if name not in used:
			out.append(
				issue("missing_required_variable", channel, lang, catalog.PRIMARY_FIELD[channel], name)
			)
	for by_channel in (conditional or {}).values():
		for name in by_channel.get(channel, []):
			if name not in used:
				out.append(
					issue("missing_required_variable", channel, lang, catalog.PRIMARY_FIELD[channel], name)
				)
	if channel == "sms" and str(data.get("text") or "").strip():
		filled = (
			template_lang.render(data["text"], _sample_scope(variables), "text")
			if not any(i["kind"] in ("unclosed_loop", "unclosed_condition") for i in out)
			else data["text"]
		)
		info = sms_info(filled, sms_currency_as_text)
		if info["unicode"]:
			out.append(issue("sms_unicode", channel, lang, "text"))
		if info["segments"] > 1:
			out.append(issue("sms_segments", channel, lang, "text"))
	return out


def validate_all(key, channels, translation_states, draft, sms_currency_as_text=False):
	"""Olayın tümü: açık kanallar × içeriği olan diller + hazır olmayan diller (uyarı)."""
	variables = catalog.variables_for(key)
	required = catalog.required_for(key)
	conditional = catalog.conditional_for(key)
	issues = []
	for ch in catalog.CHANNELS:
		if channels.get(ch, "kapali") == "kapali":
			continue
		for lang in catalog.LANGS:
			issues += validate_scope(
				(draft.get(ch) or {}).get(lang),
				ch,
				lang,
				variables,
				required.get(ch, []),
				conditional,
				sms_currency_as_text,
			)
		# Açık kanalın kaynak dil içeriği hiç yoksa yayın yapılamaz.
		if not (draft.get(ch) or {}).get(catalog.SOURCE_LANG):
			issues.append(issue("empty_required_field", ch, catalog.SOURCE_LANG, catalog.PRIMARY_FIELD[ch]))
	for lang in catalog.LANGS:
		state = translation_states.get(lang)
		if state and state != "hazir":
			issues.append(
				{
					"kind": "missing_translation",
					"channel": "email",
					"lang": lang,
					"field": "",
					"message": MESSAGES["missing_translation"],
				}
			)
	return split(issues)


def split(issues):
	return {
		"blocking": [i for i in issues if i["kind"] in BLOCKING],
		"warnings": [i for i in issues if i["kind"] not in BLOCKING],
	}


def missing_event_data(key: str, channel: str, data: dict) -> list[str]:
	"""Gerçek gönderimde zorunlu değer eksikse değişken adları (örnek değer KONMAZ)."""
	names = list(catalog.required_for(key).get(channel, []))
	for cond, by_channel in catalog.conditional_for(key).items():
		if template_lang.truthy(data.get(cond)):
			names += by_channel.get(channel, [])
	return [n for n in names if not template_lang.truthy(data.get(n))]
