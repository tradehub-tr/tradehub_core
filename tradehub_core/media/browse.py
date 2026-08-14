"""Medya Gezgini — sanal klasör ağacı (panel klasör görünümü).

Klasörler SANALDIR: disk hash-shard'lı kalır (TUR-130 — fiziksel
satıcı/kategori klasörü URL'leri kırar ve shard mimarisini geri alırdı),
ağaç tamamen metadata'dan türetilir:

    public/                        private/
      <mağaza>/                      <bağlı belge türü>/  (KYB, KYC, ...)
        <ürün kategorisi>/           __other__            (bağsız/diğer)
        __none__  (ürüne bağsız)
      __platform__ (sahipsiz — yönetim yüklemeleri, banner vb.)

Sahiplik kuralı `media/ownership.py` ile aynı iki yol: mağaza kullanıcısının
YÜKLEDİĞİ veya mağazanın ürünlerinde KULLANILAN dosya o mağazanındır.
Kategori, dosyayı kullanan ürünün `Listing.product_category` alanından gelir;
kaynak alanlar `usage.LIVE_SOURCES`'ın ürün-görseli alt kümesi (ana görsel,
galeri, varyant görseli).

Ağacın kurulumu tek geçişte yapılır ve kısa süreli önbelleğe alınır
(`_SNAPSHOT_TTL`): ~3k dosyada Python tarafı ucuz, pahalı olan mağaza-başına
sorgular. Yeni yükleme en geç TTL sonunda klasörde görünür — gezgin bir
rapor ekranı, canlı akış değil.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.query_builder.functions import Count

_SNAPSHOT_TTL = 300
_SNAPSHOT_KEY = "tradehub:media_browse:public"

PLATFORM_STORE = "__platform__"
NO_CATEGORY = "__none__"  # üründe kullanılıyor ama ürün kategorisiz
UNUSED = "__unused__"  # yüklenmiş ama hiçbir üründe durmuyor
OTHER_GROUP = "__other__"

# Bu belge türleri mağazaya göre bir seviye daha klasörlenir: yüzlerce KYB/KYC
# belgesini tek düz listede vermek kullanılamaz. Bağ: dosya → doğrulama
# belgesi (`attached_to_name`) → belgenin kullanıcısı → kullanıcının mağazası.
DETAILED_PRIVATE_GROUPS: tuple[str, ...] = ("KYB Verification", "KYC Verification")

MAX_PAGE_SIZE = 100

# (tablo, url kolonu, parent üzerinden mi) — ürün görseli taşıyan canlı alanlar.
# `usage.LIVE_SOURCES`'ın kategoriye bağlanabilir alt kümesi: vitrin/logo gibi
# ürünsüz alanların kategorisi yoktur, onlar sahiplik yoluyla mağazaya düşer.
_LISTING_IMAGE_SOURCES: tuple[tuple[str, str, bool], ...] = (
	("tabListing", "primary_image", False),
	("tabListing Image", "image", True),
	("tabListing Variant Item", "variant_image", True),
)


def _listing_usage_rows() -> list[dict]:
	"""(file_url, mağaza, kategori) üçlüleri — ürün görseli kullanan her alandan."""
	rows: list[dict] = []
	for table, column, via_parent in _LISTING_IMAGE_SOURCES:
		f = frappe.qb.Table(table)
		listing = frappe.qb.Table("tabListing")
		if via_parent:
			q = (
				frappe.qb.from_(f)
				.join(listing)
				.on(listing.name == f.parent)
				.select(
					f[column].as_("file_url"),
					listing.seller_profile.as_("store"),
					listing.product_category.as_("category"),
				)
				.where(f[column].like("/files/%"))
			)
		else:
			q = (
				frappe.qb.from_(listing)
				.select(
					listing[column].as_("file_url"),
					listing.seller_profile.as_("store"),
					listing.product_category.as_("category"),
				)
				.where(listing[column].like("/files/%"))
			)
		rows.extend(q.run(as_dict=True))
	return rows


def _user_store_map() -> dict[str, str]:
	"""Yükleyen kullanıcı → mağaza. `ownership.users_of` mağaza-başına cache'li."""
	from tradehub_core.media import ownership

	mapping: dict[str, str] = {}
	for store in frappe.get_all("Admin Seller Profile", pluck="name"):
		for user in ownership.users_of(store):
			mapping.setdefault(user, store)
	return mapping


def _public_snapshot(refresh: bool = False) -> dict:
	"""Public ağacın tamamı: {stores: {store: {cats: {cat: [url]}, none: [url]}},
	platform: [url], labels: {store: seller_name}}."""
	if not refresh:
		cached = frappe.cache().get_value(_SNAPSHOT_KEY)
		if cached:
			return cached

	files = frappe.get_all(
		"File",
		filters={"is_private": 0, "file_url": ["like", "/files/%"]},
		fields=["file_url", "owner"],
		order_by="creation desc",
		limit_page_length=0,
	)
	# Aynı adrese birden çok File kaydı düşebiliyor (ölçülmüş, bkz. ownership) —
	# klasör ağacı adres bazlı, ilk kayıt kazanır.
	seen: dict[str, str] = {}
	for r in files:
		seen.setdefault(r.file_url, r.owner or "")

	stores: dict[str, dict] = defaultdict(lambda: {"cats": defaultdict(set), "none": set()})
	assigned: set[str] = set()

	for row in _listing_usage_rows():
		url, store = row.get("file_url"), row.get("store")
		if not url or not store or url not in seen:
			continue
		category = row.get("category") or NO_CATEGORY
		stores[store]["cats"][category].add(url)
		assigned.add(url)

	user_store = _user_store_map()
	for url, owner in seen.items():
		if url in assigned:
			continue
		store = user_store.get(owner)
		if store:
			stores[store]["none"].add(url)
			assigned.add(url)

	platform = [u for u in seen if u not in assigned]

	labels = {
		r.name: r.seller_name or r.name
		for r in frappe.get_all(
			"Admin Seller Profile",
			filters={"name": ["in", list(stores)]},
			fields=["name", "seller_name"],
		)
	}

	snapshot = {
		"stores": {
			store: {
				"cats": {cat: sorted(urls) for cat, urls in data["cats"].items()},
				"none": sorted(data["none"]),
			}
			for store, data in stores.items()
		},
		"platform": sorted(platform),
		"labels": labels,
		"total": len(seen),
	}
	frappe.cache().set_value(_SNAPSHOT_KEY, snapshot, expires_in_sec=_SNAPSHOT_TTL)
	return snapshot


def _store_urls(data: dict) -> set[str]:
	urls: set[str] = set(data["none"])
	for bucket in data["cats"].values():
		urls.update(bucket)
	return urls


def root() -> dict:
	public_total = frappe.db.count("File", {"is_private": 0, "file_url": ["like", "/files/%"]})
	private_total = frappe.db.count("File", {"is_private": 1, "file_url": ["like", "/private/files/%"]})
	return {
		"folders": [
			{"id": "public", "count": public_total},
			{"id": "private", "count": private_total},
		]
	}


def public_stores(refresh: bool = False) -> dict:
	snap = _public_snapshot(refresh=refresh)
	folders = [
		{"id": store, "label": snap["labels"].get(store, store), "count": len(_store_urls(data))}
		for store, data in snap["stores"].items()
	]
	folders.sort(key=lambda f: (-f["count"], f["label"]))
	folders.append({"id": PLATFORM_STORE, "label": "", "count": len(snap["platform"])})
	return {"folders": folders}


def public_categories(store: str, refresh: bool = False) -> dict:
	snap = _public_snapshot(refresh=refresh)
	data = snap["stores"].get(store)
	if not data:
		return {"folders": []}
	labels = {
		r.name: r.category_name or r.name
		for r in frappe.get_all(
			"Product Category",
			filters={"name": ["in", list(data["cats"])]},
			fields=["name", "category_name"],
		)
	}
	folders = [
		{"id": cat, "label": labels.get(cat, cat), "count": len(urls)}
		for cat, urls in data["cats"].items()
		if cat != NO_CATEGORY
	]
	folders.sort(key=lambda f: (-f["count"], f["label"]))
	# İki durum bilinçli AYRI: "kategorisiz ürünün görseli" bir veri-kalitesi
	# sinyali, "hiçbir üründe durmayan yükleme" ise temizlik adayı.
	uncategorized = len(data["cats"].get(NO_CATEGORY, []))
	if uncategorized:
		folders.append({"id": NO_CATEGORY, "label": "", "count": uncategorized})
	if data["none"]:
		folders.append({"id": UNUSED, "label": "", "count": len(data["none"])})
	return {"folders": folders}


def private_groups() -> dict:
	f = frappe.qb.DocType("File")
	rows = (
		frappe.qb.from_(f)
		.select(f.attached_to_doctype, Count(f.name).as_("n"))
		.where(f.is_private == 1)
		.where(f.file_url.like("/private/files/%"))
		.groupby(f.attached_to_doctype)
		.run(as_dict=True)
	)
	folders, other = [], 0
	for r in rows:
		if r.attached_to_doctype:
			folders.append({"id": r.attached_to_doctype, "label": r.attached_to_doctype, "count": r.n})
		else:
			other += r.n
	folders.sort(key=lambda x: (-x["count"], x["label"]))
	if other:
		folders.append({"id": OTHER_GROUP, "label": "", "count": other})
	return {"folders": folders}


def _group_doc_store_map(group: str) -> dict[str, str]:
	"""Belge adı → mağaza; kullanıcısı bir mağazaya çözülemeyen belgede ""."""
	from tradehub_core.media import ownership

	docs = frappe.get_all(group, fields=["name", "user"], limit_page_length=0)
	user_store: dict[str, str] = {}
	mapping: dict[str, str] = {}
	for d in docs:
		u = d.user or ""
		if u not in user_store:
			user_store[u] = (ownership.store_of(u) if u else None) or ""
		mapping[d.name] = user_store[u]
	return mapping


def private_group_stores(group: str) -> dict:
	"""KYB/KYC gibi detaylı grupların mağaza alt klasörleri."""
	rows = frappe.get_all(
		"File",
		filters={
			"is_private": 1,
			"attached_to_doctype": group,
			"file_url": ["like", "/private/files/%"],
		},
		fields=["attached_to_name"],
		limit_page_length=0,
	)
	doc_store = _group_doc_store_map(group)
	counts: dict[str, int] = defaultdict(int)
	for r in rows:
		counts[doc_store.get(r.attached_to_name, "")] += 1

	store_ids = [s for s in counts if s]
	labels = {}
	if store_ids:
		labels = {
			r.name: r.seller_name or r.name
			for r in frappe.get_all(
				"Admin Seller Profile",
				filters={"name": ["in", store_ids]},
				fields=["name", "seller_name"],
			)
		}
	folders = [{"id": s, "label": labels.get(s, s), "count": n} for s, n in counts.items() if s]
	folders.sort(key=lambda f: (-f["count"], f["label"]))
	if counts.get(""):
		folders.append({"id": OTHER_GROUP, "label": "", "count": counts[""]})
	return {"folders": folders}


def _paginate_urls(urls: list[str], page: int, page_size: int, search: str) -> dict:
	"""URL kümesini File satırlarına çevirip sayfala — küme zaten bellekte."""
	if search:
		needle = search.lower()
		urls = [u for u in urls if needle in u.lower()]
	total = len(urls)
	start = (page - 1) * page_size
	window = urls[start : start + page_size]
	if not window:
		return {"items": [], "total": total}

	rows = frappe.get_all(
		"File",
		filters={"file_url": ["in", window]},
		fields=["name", "file_name", "file_url", "file_size", "creation", "is_private"],
		limit_page_length=0,
	)
	by_url: dict[str, dict] = {}
	for r in rows:
		by_url.setdefault(r.file_url, r)
	items = [by_url[u] for u in window if u in by_url]
	return {"items": items, "total": total}


def files(
	*,
	scope: str,
	store: str = "",
	category: str = "",
	group: str = "",
	sub: str = "",
	page: int = 1,
	page_size: int = 50,
	search: str = "",
) -> dict:
	page = max(1, int(page or 1))
	page_size = min(MAX_PAGE_SIZE, max(1, int(page_size or 50)))
	search = (search or "").strip()

	if scope == "private":
		f = frappe.qb.DocType("File")
		q = frappe.qb.from_(f).where(f.is_private == 1).where(f.file_url.like("/private/files/%"))
		if group == OTHER_GROUP:
			q = q.where((f.attached_to_doctype.isnull()) | (f.attached_to_doctype == ""))
		elif group:
			q = q.where(f.attached_to_doctype == group)
		if group in DETAILED_PRIVATE_GROUPS and sub:
			doc_store = _group_doc_store_map(group)
			if sub == OTHER_GROUP:
				names = [n for n, s in doc_store.items() if not s]
			else:
				names = [n for n, s in doc_store.items() if s == sub]
			# Boş liste SQL'de "her şey" olmasın — eşleşme yoksa hiçbir şey dön.
			q = q.where(f.attached_to_name.isin(names or ["__no_match__"]))
		if search:
			pattern = f"%{search}%"
			q = q.where((f.file_name.like(pattern)) | (f.file_url.like(pattern)))
		total = q.select(Count(f.name)).run()[0][0]
		rows = (
			q.select(
				f.name,
				f.file_name,
				f.file_url,
				f.file_size,
				f.creation,
				f.is_private,
				f.attached_to_doctype,
			)
			.orderby(f.creation, order=frappe.qb.desc)
			.limit(page_size)
			.offset((page - 1) * page_size)
			.run(as_dict=True)
		)
		from tradehub_core.media import access_level

		for r in rows:
			# `get_private_files` ile aynı iki yönlü PII kararı — iki liste
			# aynı dosyada farklı aksiyon göstermesin.
			r["pii"] = access_level._is_protected_pii(r, r.file_url)
		return {"items": rows, "total": total}

	snap = _public_snapshot()
	if store == PLATFORM_STORE:
		urls = list(snap["platform"])
	else:
		data = snap["stores"].get(store)
		if not data:
			return {"items": [], "total": 0}
		if category == NO_CATEGORY:
			urls = list(data["cats"].get(NO_CATEGORY, []))
		elif category == UNUSED:
			urls = list(data["none"])
		elif category:
			urls = list(data["cats"].get(category, []))
		else:
			urls = sorted(_store_urls(data))
	return _paginate_urls(urls, page, page_size, search)
