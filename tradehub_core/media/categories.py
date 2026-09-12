"""Medya kategorizasyonu: katalog, N:M atama ve deterministik öneriler.

ER özeti::

    Admin Seller Profile 1 ── N Media Category
    Media Category       1 ── N Media Category Assignment
    public file_url      1 ── N Media Category Assignment

``file_url`` bilinçli bir Link değildir: aynı fiziksel adres birden fazla File
satırıyla ve birden fazla tenant'la paylaşılabilir. Tenant kolonu ilişki
kaydında bulunduğu için iki mağaza aynı URL'yi birbirinden bağımsız
kategorize eder.

Öneri motoru kararını otomatik olarak "gerçek" saymaz. Dosya adı, satıcının
kendi üstverisi, içerik türü ve çağıranın verdiği kaynak metninden kanıt
üretir; sonucu ``suggestion`` kaynaklı ve 0..1 güven değerli atama olarak
saklar. Kullanıcının seçimi aynı bağı ``manual`` kaynağına yükseltir.
"""

from __future__ import annotations

import mimetypes
import re
import unicodedata
from collections.abc import Iterable

import frappe
from frappe import _

from tradehub_core.media import metadata, ownership

MAX_CATEGORIES_PER_FILE: int = 25
MAX_BATCH: int = 200
MAX_SUGGESTIONS: int = 10
_TOKEN = re.compile(r"[a-z0-9]+")
_TR_MAP = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g"})

_KIND_TERMS: dict[str, frozenset[str]] = {
	"image": frozenset({"image", "gorsel", "resim", "fotograf", "foto", "picture", "photo"}),
	"video": frozenset({"video", "film", "klip", "clip"}),
	"document": frozenset({"document", "belge", "dokuman", "pdf", "spreadsheet", "tablo"}),
}


def normalize_category_ids(value) -> tuple[str, ...]:
	"""JSON/dizi girdisini benzersiz, sınırlandırılmış kategori kimliklerine çevir."""
	if isinstance(value, str):
		try:
			parsed = frappe.parse_json(value)
		except Exception:
			parsed = [part for part in value.split(",") if part]
		value = parsed if isinstance(parsed, list) else [parsed]
	clean: list[str] = []
	for raw in value or []:
		category = str(raw or "").strip()
		if not category or category in clean:
			continue
		if len(category) > 140:
			frappe.throw(_("Geçersiz kategori kimliği."))
		clean.append(category)
	if len(clean) > MAX_CATEGORIES_PER_FILE:
		frappe.throw(
			_("Bir medyaya en çok {0} kategori atanabilir.").format(MAX_CATEGORIES_PER_FILE)
		)
	return tuple(clean)


def _my_categories(
	store: str, category_ids: Iterable[str], *, active_only: bool = False
) -> dict[str, dict]:
	ids = tuple(dict.fromkeys(category_ids))
	if not ids:
		return {}
	filters: dict = {"store": store, "name": ["in", list(ids)]}
	if active_only:
		filters["is_active"] = 1
	rows = frappe.get_all(
		"Media Category",
		filters=filters,
		fields=[
			"name",
			"category_name",
			"parent_category",
			"category_type",
			"description",
			"color",
			"is_active",
		],
		limit_page_length=0,
	)
	result = {row["name"]: row for row in rows}
	if len(result) != len(ids):
		# Eksik ile yabancı tenant kimliği aynı hata: varlığı doğrulanmaz.
		frappe.throw(_("Kategori bulunamadı."), frappe.DoesNotExistError)
	return result


def list_categories(store: str, *, include_inactive: bool = False) -> list[dict]:
	"""Tenant kategori kataloğu + kategori başına atanmış benzersiz medya sayısı."""
	filters: dict = {"store": store}
	if not include_inactive:
		filters["is_active"] = 1
	rows = frappe.get_all(
		"Media Category",
		filters=filters,
		fields=[
			"name",
			"category_name",
			"parent_category",
			"category_type",
			"description",
			"color",
			"is_active",
			"creation",
			"modified",
		],
		order_by="category_name asc",
		limit_page_length=0,
	)
	counts = {
		row.category: int(row.count or 0)
		for row in frappe.get_all(
			"Media Category Assignment",
			filters={"store": store},
			fields=["category", "count(distinct file_url) as count"],
			group_by="category",
			limit_page_length=0,
		)
	}
	for row in rows:
		row["assignment_count"] = counts.get(row["name"], 0)
		row["is_active"] = bool(row.get("is_active"))
	return rows


def assignments_for_urls(file_urls: Iterable[str], store: str) -> dict[str, list[dict]]:
	"""URL kümesinin kategori bağlarını iki toplu sorguda döndür (N+1 yok)."""
	urls = tuple(
		dict.fromkeys(str(url or "").split("?", 1)[0] for url in file_urls if url)
	)
	if not urls:
		return {}
	assignments = frappe.get_all(
		"Media Category Assignment",
		filters={"store": store, "file_url": ["in", list(urls)]},
		fields=[
			"name",
			"file_url",
			"category",
			"assignment_source",
			"confidence",
			"evidence",
			"assigned_by",
			"creation",
		],
		limit_page_length=0,
	)
	category_ids = {row["category"] for row in assignments}
	categories = {
		row["name"]: row
		for row in frappe.get_all(
			"Media Category",
			filters={"store": store, "name": ["in", list(category_ids)]},
			fields=["name", "category_name", "parent_category", "category_type", "color", "is_active"],
			limit_page_length=0,
		)
	} if category_ids else {}
	out: dict[str, list[dict]] = {url: [] for url in urls}
	for assignment in assignments:
		category = categories.get(assignment["category"])
		if not category:
			continue
		out.setdefault(assignment["file_url"], []).append(
			{
				"assignment": assignment["name"],
				"name": category["name"],
				"category_name": category["category_name"],
				"parent_category": category.get("parent_category") or "",
				"category_type": category["category_type"],
				"color": category.get("color") or "",
				"is_active": bool(category.get("is_active")),
				"assignment_source": assignment["assignment_source"],
				"confidence": float(assignment.get("confidence") or 0),
				"evidence": assignment.get("evidence") or "",
				"assigned_by": assignment.get("assigned_by") or "",
				"assigned_at": assignment.get("creation"),
			}
		)
	for values in out.values():
		values.sort(key=lambda row: (row["category_name"].casefold(), row["name"]))
	return out


def category_facets(file_urls: Iterable[str], store: str) -> list[dict]:
	"""Envanter URL kümesindeki kategori sayaçları (atanmamış katalog satırı yok)."""
	assignments = assignments_for_urls(file_urls, store)
	counts: dict[str, dict] = {}
	for rows in assignments.values():
		for row in rows:
			entry = counts.setdefault(
				row["name"],
				{
					"name": row["name"],
					"category_name": row["category_name"],
					"category_type": row["category_type"],
					"color": row["color"],
					"is_active": row["is_active"],
					"count": 0,
				},
			)
			entry["count"] += 1
	return sorted(counts.values(), key=lambda row: (-row["count"], row["category_name"].casefold()))


def _upsert_assignment(
	*,
	store: str,
	file_url: str,
	category: str,
	assignment_source: str,
	confidence: float,
	evidence: str = "",
) -> tuple[str, bool]:
	existing = frappe.db.get_value(
		"Media Category Assignment",
		{"store": store, "file_url": file_url, "category": category},
		["name", "assignment_source", "confidence"],
		as_dict=True,
	)
	if existing:
		# Otomatik bir koşu kullanıcının açık manuel kararını geriye çeviremez.
		if existing.assignment_source == "manual" and assignment_source != "manual":
			return existing.name, False
		if (
			assignment_source != "manual"
			and existing.assignment_source != "manual"
			and float(existing.confidence or 0) > float(confidence)
		):
			return existing.name, False
		frappe.db.set_value(
			"Media Category Assignment",
			existing.name,
			{
				"assignment_source": assignment_source,
				"confidence": confidence,
				"evidence": evidence[:500],
				"assigned_by": frappe.session.user,
			},
		)
		return existing.name, False
	doc = frappe.get_doc(
		{
			"doctype": "Media Category Assignment",
			"category": category,
			"file_url": file_url,
			"store": store,
			"assignment_source": assignment_source,
			"confidence": confidence,
			"evidence": evidence,
			"assigned_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)
	return doc.name, True


def set_for_file(file_url: str, category_ids, store: str) -> dict:
	"""Bir dosyanın nihai kullanıcı seçimini değiştir (idempotent replace)."""
	file_url = (file_url or "").split("?", 1)[0].strip()
	ownership.assert_owns(store, file_url)
	ids = normalize_category_ids(category_ids)
	_my_categories(store, ids, active_only=True)
	for assignment in frappe.get_all(
		"Media Category Assignment",
		filters={"store": store, "file_url": file_url},
		fields=["name", "category"],
		limit_page_length=0,
	):
		if assignment["category"] not in ids:
			frappe.delete_doc(
				"Media Category Assignment", assignment["name"], ignore_permissions=True, force=True
			)
	for category in ids:
		_upsert_assignment(
			store=store,
			file_url=file_url,
			category=category,
			assignment_source="manual",
			confidence=1,
			evidence="user_selection",
		)
	return {"file_url": file_url, "categories": assignments_for_urls([file_url], store).get(file_url, [])}


def remove_from_many(file_urls, category_ids, store: str) -> dict:
	"""Seçili dosyalardan verilen kategorilerin bağını kaldır.

	`add_to_many`'nin simetriği ve sözleşmesi birebir aynı (`assigned` yerine
	`removed`). Ayrı fonksiyon olmasının sebebi `set_for_file`'ın yapamaması:
	o NİHAİ listeyi yazar, yani "şu iki kategoriyi kaldır" demek için çağıranın
	her dosyanın mevcut listesini önce okuyup farkı hesaplaması gerekirdi —
	200 dosyada 200 ek okuma ve iki istemcide iki farklı hesap.

	KAYNAK AYRIMI KORUNUR: yalnız bu mağazanın (`store`) atamaları silinir.
	Aynı dosya başka bir mağazanın kütüphanesinde de duruyorsa onun kategori
	ataması bu çağrıdan etkilenmez.
	"""
	urls = tuple(
		dict.fromkeys(str(url or "").split("?", 1)[0] for url in (file_urls or []) if url)
	)
	if len(urls) > MAX_BATCH:
		frappe.throw(_("Tek seferde en çok {0} dosya işlenebilir.").format(MAX_BATCH))
	ids = normalize_category_ids(category_ids)
	_my_categories(store, ids, active_only=False)
	removed = 0
	skipped = 0
	failed: list[dict] = []
	for url in urls:
		if not ownership.owns(store, url):
			skipped += 1
			continue
		try:
			for assignment in frappe.get_all(
				"Media Category Assignment",
				filters={"store": store, "file_url": url, "category": ["in", list(ids)]},
				pluck="name",
				limit_page_length=0,
			):
				frappe.delete_doc(
					"Media Category Assignment", assignment, ignore_permissions=True, force=True
				)
				removed += 1
		except Exception as exc:
			frappe.log_error(title="media.categories remove_from_many", message=frappe.get_traceback())
			failed.append({"file_url": url, "error": str(exc)})
	return {
		"removed": removed,
		"files": len(urls) - skipped - len(failed),
		"skipped": skipped,
		"failed": failed,
	}


def add_to_many(file_urls, category_ids, store: str) -> dict:
	"""Seçili dosyalara bir veya daha fazla manuel kategori ekle."""
	urls = tuple(
		dict.fromkeys(str(url or "").split("?", 1)[0] for url in (file_urls or []) if url)
	)
	if len(urls) > MAX_BATCH:
		frappe.throw(_("Tek seferde en çok {0} dosya işlenebilir.").format(MAX_BATCH))
	ids = normalize_category_ids(category_ids)
	_my_categories(store, ids, active_only=True)
	assigned = 0
	skipped = 0
	failed: list[dict] = []
	for url in urls:
		if not ownership.owns(store, url):
			skipped += 1
			continue
		try:
			for category in ids:
				_assignment_name, created = _upsert_assignment(
					store=store,
					file_url=url,
					category=category,
					assignment_source="manual",
					confidence=1,
					evidence="bulk_user_selection",
				)
				assigned += int(created)
		except Exception as exc:
			failed.append({"file_url": url, "error": str(exc)})
	return {"assigned": assigned, "files": len(urls) - skipped - len(failed), "skipped": skipped, "failed": failed}


def _normalized(value: str) -> str:
	text = unicodedata.normalize("NFKD", str(value or "").translate(_TR_MAP))
	return " ".join(_TOKEN.findall("".join(ch for ch in text if not unicodedata.combining(ch)).lower()))


def _tokens(value: str) -> set[str]:
	return {token for token in _normalized(value).split() if len(token) >= 2}


def suggest(file_url: str, store: str, *, source: str = "") -> list[dict]:
	"""Dosya adı/üstveri/kaynak/içerik türünden açıklanabilir öneriler üret."""
	file_url = (file_url or "").split("?", 1)[0].strip()
	ownership.assert_owns(store, file_url)
	meta = metadata.read(file_url, store)
	# İçerik-adresli depolamada URL hash olabilir; kullanıcının gördüğü gerçek
	# ad ``File.file_name`` alanındadır. Yalnız tenant kullanıcılarının satırları
	# okunur. Dosya salt kullanım yoluyla görünüyorsa kendi File satırı yoktur;
	# o durumda URL son parçası güvenli geri düşüştür.
	file_names = frappe.get_all(
		"File",
		filters={
			"file_url": file_url,
			"owner": ["in", list(ownership.users_of(store)) or ["__none__"]],
		},
		pluck="file_name",
		limit_page_length=0,
	)
	file_names = [str(name) for name in file_names if name]
	file_name = next(iter(file_names), file_url.rsplit("/", 1)[-1])
	mime = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
	kind = "image" if mime.startswith("image/") else "video" if mime.startswith("video/") else "document"
	fields = {
		"file_name": _normalized(" ".join(file_names) or file_name.rsplit(".", 1)[0]),
		"title": _normalized(meta.get("title") or ""),
		"description": _normalized(meta.get("description") or ""),
		"tags": _normalized(" ".join(meta.get("tags") or [])),
		"source": _normalized(str(source or "")[:200]),
		"content_type": _normalized(f"{mime} {' '.join(_KIND_TERMS[kind])}"),
	}
	weights = {
		"tags": 0.98,
		"source": 0.92,
		"title": 0.88,
		"file_name": 0.84,
		"description": 0.76,
		"content_type": 0.86,
	}
	suggestions: list[dict] = []
	for category in list_categories(store):
		name = _normalized(category["category_name"])
		name_tokens = _tokens(name)
		if not name_tokens:
			continue
		score = 0.0
		evidence: list[str] = []
		for field, text in fields.items():
			if not text:
				continue
			# İçerik türü yalnız content_type kategorilerini besler; aksi halde
			# "kampanya video" gibi bir kategori sırf video olduğu için şişerdi.
			if field == "content_type" and category["category_type"] != "content_type":
				continue
			field_tokens = _tokens(text)
			overlap = len(name_tokens & field_tokens) / len(name_tokens)
			candidate = 0.0
			if name and name in text:
				candidate = weights[field]
			elif overlap:
				candidate = weights[field] * overlap * 0.72
			if candidate > 0:
				score = max(score, candidate)
				evidence.append(field)
		if score < 0.35:
			continue
		suggestions.append(
			{
				"name": category["name"],
				"category_name": category["category_name"],
				"category_type": category["category_type"],
				"color": category.get("color") or "",
				"confidence": round(min(1.0, score), 4),
				"evidence": sorted(set(evidence)),
				"assignment_source": "suggestion",
			}
		)
	return sorted(
		suggestions,
		key=lambda row: (-row["confidence"], row["category_name"].casefold()),
	)[:MAX_SUGGESTIONS]


def apply_suggestions(
	file_url: str, store: str, *, source: str = "", threshold: float = 0.7
) -> dict:
	"""Eşiği geçen önerileri idempotent biçimde otomatik atama olarak yaz."""
	try:
		threshold = float(threshold)
	except (TypeError, ValueError):
		frappe.throw(_("Öneri eşiği sayı olmalıdır."))
	if not 0 <= threshold <= 1:
		frappe.throw(_("Öneri eşiği 0 ile 1 arasında olmalıdır."))
	file_url = (file_url or "").split("?", 1)[0].strip()
	applied = 0
	all_suggestions = suggest(file_url, store, source=source)
	for row in all_suggestions:
		if row["confidence"] < threshold:
			continue
		_assignment_name, created = _upsert_assignment(
			store=store,
			file_url=file_url,
			category=row["name"],
			assignment_source="suggestion",
			confidence=row["confidence"],
			evidence=",".join(row["evidence"]),
		)
		applied += int(created)
	return {
		"file_url": file_url,
		"applied": applied,
		"suggestions": all_suggestions,
		"categories": assignments_for_urls([file_url], store).get(file_url, []),
	}
