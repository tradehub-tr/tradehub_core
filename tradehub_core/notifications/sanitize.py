"""E-posta gövdesi için sunucu tarafı HTML temizleme (allowlist).

Panel `utils/sanitize.js` (DOMPurify) ikinci katmandır; asıl karar buradadır.
Tablo düzeni, `class` ve güvenli satır içi CSS korunur (e-posta tasarımı bunlara dayanır).
Bağlantılar yalnız `https://`, kök göreli `/yol`, `mailto:` ya da tek bir şablon değişkeni olabilir;
`javascript:`, `data:`, `vbscript:` ve protokol bağımsız `//` reddedilir.
"""

from __future__ import annotations

import re

import bleach
from bleach.css_sanitizer import CSSSanitizer

ALLOWED_TAGS = frozenset(
	{
		"a", "b", "blockquote", "br", "code", "div", "em", "h1", "h2", "h3", "h4", "hr", "i", "li",
		"ol", "p", "pre", "s", "small", "span", "strong", "sub", "sup", "table", "tbody", "td", "tfoot",
		"th", "thead", "tr", "u", "ul",
	}
)  # fmt: skip

COMMON_ATTRS = ("class", "style", "align", "valign", "width", "height", "bgcolor", "role", "dir", "lang")
TABLE_ATTRS = ("cellpadding", "cellspacing", "border", "colspan", "rowspan")

ALLOWED_CSS = frozenset(
	{
		"background-color", "border", "border-bottom", "border-collapse", "border-color", "border-left",
		"border-radius", "border-right", "border-spacing", "border-top", "box-sizing", "color", "display",
		"font-family", "font-size", "font-style", "font-variant-numeric", "font-weight", "height",
		"letter-spacing", "line-height", "margin", "margin-bottom", "margin-left", "margin-right",
		"margin-top", "max-width", "min-width", "overflow-wrap", "padding", "padding-bottom",
		"padding-left", "padding-right", "padding-top", "table-layout", "text-align", "text-decoration",
		"vertical-align", "white-space", "width", "word-break",
	}
)  # fmt: skip

TOKEN_ONLY = re.compile(r"^\{\{\s*[A-Za-z_][\w.]*\s*\}\}[^\s\"'<>]*$")
SAFE_HREF = re.compile(r"^(https://[^\s\"'<>]+|/(?![/\\])[^\s\"'<>]*|mailto:[^\s\"'<>]+)$", re.IGNORECASE)

MAX_HTML = 100_000  # karakter; aşan gövde kayıtta reddedilir

ANCHOR_RE = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<label>[\s\S]*?)</a>", re.IGNORECASE)
_HREF_RE = re.compile(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)


def anchor_href(attrs: str) -> str | None:
	m = _HREF_RE.search(attrs or "")
	if not m:
		return None
	return m.group(1) if m.group(1) is not None else m.group(2)


def href_ok(value: str) -> bool:
	v = (value or "").strip()
	return bool(SAFE_HREF.match(v) or TOKEN_ONLY.match(v))


def _attr_filter(tag: str, name: str, value: str) -> bool:
	if name in COMMON_ATTRS:
		return True
	if tag in ("table", "td", "th", "tr") and name in TABLE_ATTRS:
		return True
	if tag == "a" and name == "href":
		return href_ok(value)
	if tag == "a" and name in ("title", "target", "rel"):
		return True
	return False


_CLEANER = bleach.Cleaner(
	tags=ALLOWED_TAGS,
	attributes=_attr_filter,
	protocols=["https", "mailto"],
	strip=True,
	strip_comments=True,
	css_sanitizer=CSSSanitizer(allowed_css_properties=ALLOWED_CSS),
)


def clean_html(value: str) -> str:
	"""Allowlist temizliği. Şablon belirteçleri (`{{…}}`) metin olarak korunur."""
	return _CLEANER.clean(str(value or ""))


def strip_tags(value: str) -> str:
	return bleach.clean(str(value or ""), tags=set(), strip=True)
