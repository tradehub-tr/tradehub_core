"""Bildirim şablonlarının sınırlı dili: ayrıştırma, doğrulama ve güvenli render.

Sözdizimi panelle (admin-panel `utils/notificationTemplates/template.js`) birebir aynıdır:
    {{ad}}  {{nesne.alan}}  {{#each liste}} … {{/each}}  {{#if ad}} … {{/if}}

Jinja DEĞİLDİR: fonksiyon çağrısı, filtre, attribute yürüyüşü, include/import yoktur.
Noktalı yol yalnız dict anahtarlarından çözülür (`getattr` kullanılmaz). Döngü takma adı
panelle aynı kuraldır: `groups → group`, `group.items → item` (son parça, sondaki "s" atılır).

Frappe'ye bağımlı değildir; saf Python, `unittest` ile frappe olmadan da sınanır.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field

TOKEN_RE = re.compile(
	r"\{\{\s*(#each\s+[A-Za-z_][\w.]*|#if\s+[A-Za-z_][\w.]*|/each|/if|[A-Za-z_][\w.]*)\s*\}\}"
)

MAX_DEPTH = 4  # iç içe blok sınırı
MAX_LOOP_ITEMS = 200  # tek döngüde en çok öğe
MAX_OUTPUT = 200_000  # render çıktısı üst sınırı (karakter)


class TemplateError(ValueError):
	"""Şablon yapısı bozuk (kapanmamış blok, derinlik aşımı)."""

	def __init__(self, kind: str, message: str):
		super().__init__(message)
		self.kind = kind


class RenderLimitError(ValueError):
	"""Render sınırları aşıldı (çıktı boyutu, döngü uzunluğu)."""


@dataclass
class Node:
	type: str  # text | var | each | if
	value: str = ""
	children: list[Node] = field(default_factory=list)


def tokens(text: str) -> list[dict]:
	"""Metindeki belirteçler: [{type: var|open|close|if|endif, name, raw, index}]."""
	out = []
	for m in TOKEN_RE.finditer(str(text or "")):
		t = m.group(1)
		if t.startswith("#each"):
			out.append({"type": "open", "name": t[5:].strip(), "raw": m.group(0), "index": m.start()})
		elif t.startswith("#if"):
			out.append({"type": "if", "name": t[3:].strip(), "raw": m.group(0), "index": m.start()})
		elif t == "/each":
			out.append({"type": "close", "name": "", "raw": m.group(0), "index": m.start()})
		elif t == "/if":
			out.append({"type": "endif", "name": "", "raw": m.group(0), "index": m.start()})
		else:
			out.append({"type": "var", "name": t, "raw": m.group(0), "index": m.start()})
	return out


def parse(text: str) -> list[Node]:
	"""Şablonu ağaca çevirir. Kapanmamış/fazla blokta TemplateError."""
	root: list[Node] = []
	stack: list[Node] = []
	pos = 0
	source = str(text or "")

	def sink() -> list[Node]:
		return stack[-1].children if stack else root

	for m in TOKEN_RE.finditer(source):
		if m.start() > pos:
			sink().append(Node("text", source[pos : m.start()]))
		pos = m.end()
		t = m.group(1)
		if t.startswith("#each") or t.startswith("#if"):
			kind = "each" if t.startswith("#each") else "if"
			if len(stack) >= MAX_DEPTH:
				raise TemplateError("too_deep", f"İç içe blok sınırı {MAX_DEPTH}")
			node = Node(kind, t.split(None, 1)[1].strip())
			sink().append(node)
			stack.append(node)
		elif t in ("/each", "/if"):
			kind = "each" if t == "/each" else "if"
			if not stack or stack[-1].type != kind:
				# Çapraz kapanışta hata, açık kalan (en içteki) bloğun türüdür.
				open_kind = stack[-1].type if stack else kind
				raise TemplateError(
					"unclosed_loop" if open_kind == "each" else "unclosed_condition",
					f"Karşılığı olmayan {{{{{t}}}}}",
				)
			stack.pop()
		else:
			sink().append(Node("var", t))
	if pos < len(source):
		sink().append(Node("text", source[pos:]))
	if stack:
		kind = stack[-1].type
		raise TemplateError(
			"unclosed_loop" if kind == "each" else "unclosed_condition", f"Kapatılmamış {{{{#{kind}}}}}"
		)
	return root


def alias(name: str) -> str:
	"""groups → group, group.items → item (panelle aynı)."""
	last = name.split(".")[-1]
	return last[:-1] if last.endswith("s") else last


def lookup(path: str, scope: dict):
	"""Noktalı yol yalnız dict anahtarlarından çözülür; attribute erişimi yok."""
	cur = scope
	for part in path.split("."):
		if not isinstance(cur, dict) or part.startswith("_"):
			return None
		cur = cur.get(part)
	return cur


def truthy(value) -> bool:
	if isinstance(value, str):
		return bool(value.strip())
	if isinstance(value, list | tuple | dict):
		return len(value) > 0
	return bool(value)


# ── Render ────────────────────────────────────────────────────────────────

SAFE_URL_RE = re.compile(r"^(https://[^\s\"'<>]+|/(?![/\\])[^\s\"'<>]*)$", re.IGNORECASE)


def safe_url(value) -> str:
	"""Render sonrası gerçek URL denetimi: yalnız https:// ya da kök göreli yol."""
	v = str(value or "").strip()
	return v if SAFE_URL_RE.match(v) else ""


def _escape_value(value, mode: str) -> str:
	if value is None:
		return ""
	if isinstance(value, dict | list | tuple):
		return ""  # nesne yerine konmaz
	text = str(value)
	if mode == "html":
		return _html.escape(text, quote=True)
	return text


def render(text: str, scope: dict, mode: str = "text") -> str:
	"""Şablonu doldurur.

	mode="html": şablon önceden temizlenmiş HTML; değerler HTML kaçışlanır.
	mode="text": düz metin; değerler olduğu gibi (SMS, push, konu).
	Bilinmeyen değişken boş dize olur (doğrulama zaten engeller).
	"""
	tree = parse(text)
	out: list[str] = []
	size = [0]

	def emit(s: str):
		size[0] += len(s)
		if size[0] > MAX_OUTPUT:
			raise RenderLimitError("Çıktı boyutu sınırı aşıldı")
		out.append(s)

	def walk(nodes: list[Node], sc: dict):
		for n in nodes:
			if n.type == "text":
				emit(n.value)
			elif n.type == "var":
				emit(_escape_value(lookup(n.value, sc), mode))
			elif n.type == "if":
				if truthy(lookup(n.value, sc)):
					walk(n.children, sc)
			elif n.type == "each":
				items = lookup(n.value, sc)
				if not isinstance(items, list | tuple):
					continue
				if len(items) > MAX_LOOP_ITEMS:
					raise RenderLimitError("Döngü uzunluğu sınırı aşıldı")
				name = alias(n.value)
				for item in items:
					walk(n.children, {**sc, name: item})

	walk(tree, scope or {})
	return "".join(out)


# ── Doğrulama ─────────────────────────────────────────────────────────────


def used_names(text: str) -> set[str]:
	return {t["name"] for t in tokens(text) if t["name"]}


def structure_issue(text: str) -> str | None:
	"""Blok yapısı bozuksa issue türü (unclosed_loop | unclosed_condition | too_deep)."""
	try:
		parse(text)
	except TemplateError as e:
		return e.kind
	return None


def url_template_ok(value: str, variables: list[dict]) -> bool:
	"""Şablondaki bağlantı: https://…, /yol ya da url türünde TEK değişken (panelle aynı)."""
	v = str(value or "").strip()
	if (
		re.match(r"^https://[^\s]+$", v)
		or re.match(r"^/(?![/\\])[^\s]*$", v)
		or re.match(r"^mailto:[^\s@]+@[^\s@]+$", v)
	):
		return True
	m = re.match(r"^\{\{\s*([A-Za-z_][\w.]*)\s*\}\}[^\s]*$", v)
	if not m:
		return False
	return _var_type(m.group(1), variables) == "url"


def _var_type(name: str, variables: list[dict]) -> str | None:
	for v in variables:
		if v.get("name") == name:
			return v.get("type")
	return None
