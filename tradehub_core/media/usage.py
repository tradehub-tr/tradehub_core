"""Bir görselin nerede kullanıldığını çözümler.

Ekran yalnız optimizasyon paneli değil, aynı zamanda bir **rapor**: "8 üründe
kullanılıyor" demek yetmez, hangi ürünlerde, varyant mı değil mi, o ürün hâlâ
yayında mı — bunların görünmesi gerekiyor. Silme kararı da buradan çıkacak.

Kaynak alanlar `information_schema` taramasıyla bulundu (bkz. LIVE_SOURCES):
görsel URL'i geçen 23 alan var, ama hepsi "kullanım" değil. Üçe ayrılıyorlar:

  CANLI      → Listing.primary_image, Listing Image.image, varyant alanları,
               vitrin, satıcı galerisi, logo. Silinirse sitede bir şey kırılır.
  GEÇMİŞ     → tabVersion, tabDeleted Document, tabComment, Error Log, bulk
               import kayıtları. Dosya bir zamanlar kullanılmış ya da sadece
               loglanmış; silinmesi siteyi bozmaz.
  SİPARİŞ    → Cart Item.snapshot_image, Order.receipt_url. Ürün görselinin
               kopyası; geçmiş siparişin delili sayılır, ayrı işaretlenir.

Frappe **soft-delete yapmaz**: silinen kayıt `Deleted Document`'a taşınır. Bu
yüzden "sadece geçmişte geçiyor" ayrı bir kategoridir — dosyayı kullanan ürün
silinmiş demektir, dosya artık boştadır.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

import frappe

# (tablo, kolon, tür, etiket) — tür UI'da gruplama ve karar için kullanılır.
LIVE_SOURCES: tuple[tuple[str, str, str, str], ...] = (
	("tabListing", "primary_image", "listing_main", "Ana görsel"),
	("tabListing", "video_url", "listing_video", "Video"),
	("tabListing Image", "image", "listing_gallery", "Galeri"),
	("tabListing Variant Item", "variant_image", "variant_main", "Varyant görseli"),
	("tabListing Variant Item", "variant_gallery", "variant_gallery", "Varyant galerisi"),
	("tabStorefront Layout", "sections", "storefront", "Vitrin düzeni"),
	("tabSeller Gallery Image", "image", "seller_gallery", "Satıcı galerisi"),
	("tabAdmin Seller Profile", "logo", "seller_logo", "Mağaza logosu"),
)

# Sipariş anında kopyalanan görseller — canlı kullanım değil ama geçmiş
# siparişin kaydı. Silme kararında ayrı ağırlık taşır.
ORDER_SOURCES: tuple[tuple[str, str, str, str], ...] = (
	("tabCart Item", "snapshot_image", "cart_snapshot", "Sepet anlık görüntüsü"),
	("tabOrder", "receipt_url", "order_receipt", "Sipariş dekontu"),
)

# Yalnız iz bırakan tablolar — kullanım sayılmaz.
HISTORY_SOURCES: tuple[tuple[str, str, str, str], ...] = (
	("tabVersion", "data", "version", "Değişiklik geçmişi"),
	("tabDeleted Document", "data", "deleted", "Silinmiş kayıt"),
	("tabComment", "content", "comment", "Yorum"),
	("tabBulk Import Job Error", "raw_row_json", "import_error", "Toplu yükleme hatası"),
	("tabBulk Import Job", "data_file", "import_job", "Toplu yükleme dosyası"),
	("tabError Log", "error", "error_log", "Hata kaydı"),
)

# Karar etiketleri — filtre ve rozet bunları kullanır.
VERDICTS: tuple[str, ...] = ("in_use", "order_only", "history_only", "unused")

_CHUNK = 400


def _chunks(seq: list, n: int = _CHUNK):
	for i in range(0, len(seq), n):
		yield seq[i : i + n]


def _match_rows(table: str, column: str, urls: list[str], extra: str = "") -> list[dict]:
	"""`urls` içindeki herhangi biri geçen satırları dön. LIKE ile, chunk'lı."""
	out: list[dict] = []
	for chunk in _chunks(urls):
		# LOCATE: LIKE utf8mb4'te 4 baytlık karakterli satırlarda eşleşmiyor.
		cond = " or ".join([f"locate(%s, `{column}`) > 0"] * len(chunk))
		vals = list(chunk)
		sel = f"`{column}` as _val" + (f", {extra}" if extra else "")
		try:
			out += frappe.db.sql(f"select {sel} from `{table}` where {cond}", vals, as_dict=True)
		except Exception:
			frappe.log_error(
				title=f"Usage scan failed: {table}.{column}",
				message=frappe.get_traceback(with_context=True),
			)
	return out


def _urls_in(value: str, wanted: set[str]) -> set[str]:
	"""Bir metin alanında geçen ve aradığımız kümede olan URL'ler."""
	if not isinstance(value, str) or "/files/" not in value:
		return set()
	found = set(re.findall(r"/(?:private/)?files/[^\"'\s\\,\)\]}>]+", value))
	return {u.split("?")[0] for u in found} & wanted


def verdicts_for(urls: list[str], deep: bool = False) -> dict[str, dict]:
	"""Toplu karar — `{url: {verdict, live, order, history}}`.

	İki kademeli, çünkü kaynakların maliyeti taban tabana zıt (50 dosya, ölçüm):

	    CANLI + SİPARİŞ  ->  116 ms   (10 alan)
	    GEÇMİŞ           -> 3.546 ms  (Version 934, Deleted Document 2.018, Error Log 552)

	`deep=False` (varsayılan): yalnız canlı ve sipariş taranır, karar
	`in_use / order_only / not_in_use` olur. Liste her açılışta bunu kullanır.

	`deep=True`: geçmiş de taranır, `not_in_use` ikiye ayrılır —
	`history_only` (kullanılıyordu, kayıt silinmiş) ve `unused` (hiç kullanılmamış).
	Detay penceresi ve "derin tarama" filtresi bunu ister.
	"""
	wanted = {u for u in urls if u}
	if not wanted:
		return {}

	groups = [(LIVE_SOURCES, "live"), (ORDER_SOURCES, "order")]
	if deep:
		groups.append((HISTORY_SOURCES, "history"))

	acc: dict[str, dict[str, int]] = {u: {"live": 0, "order": 0, "history": 0} for u in wanted}
	for group, key in groups:
		for table, column, _kind, _label in group:
			for row in _match_rows(table, column, list(wanted)):
				for u in _urls_in(row.get("_val"), wanted):
					acc[u][key] += 1

	out: dict[str, dict] = {}
	for u, c in acc.items():
		if c["live"]:
			v = "in_use"
		elif c["order"]:
			v = "order_only"
		elif not deep:
			v = "not_in_use"
		elif c["history"]:
			v = "history_only"
		else:
			v = "unused"
		out[u] = {"verdict": v, **c}
	return out


# Filtre için tüm kümenin kararı — pahalı, Redis'te önbelleklenir.
VERDICT_CACHE_KEY = "tradehub_media_verdicts"
VERDICT_TTL = 600


def _referenced_urls(group: tuple) -> set[str]:
	"""Bir kaynak grubunda geçen TÜM görsel URL'leri — tek sorgu / alan.

	`verdicts_for` belirli URL'leri sorar ve 400 OR'lu LIKE üretir; tüm küme için
	bu çok pahalı (ölçüm: 6,1 sn). Burada tersi yapılır: alan başına tek
	`like '%/files/%'` ile URL taşıyan satırlar çekilip regex ile ayrıştırılır.
	"""
	found: set[str] = set()
	for table, column, _kind, _label in group:
		try:
			# LOCATE kullanılıyor: LIKE, utf8mb4'te 4 baytlık karakter içeren
			# satırlarda eşleşmiyor (bkz. inventory.py Left/Right notu).
			rows = frappe.db.sql(f"select `{column}` from `{table}` where locate('/files/', `{column}`) > 0")
		except Exception:
			frappe.log_error(
				title=f"Usage scan failed: {table}.{column}",
				message=frappe.get_traceback(with_context=True),
			)
			continue
		for (val,) in rows:
			if isinstance(val, str) and "/files/" in val:
				for m in re.findall(r"/(?:private/)?files/[^\"\'\s\\,\)\]}>]+", val):
					found.add(m.split("?")[0])
	return found


def usage_counts_all(refresh: bool = False) -> dict[str, int]:
	"""`{url: canlı kullanım sayısı}` — "en çok kullanılana göre sırala" için.

	Liste sıralaması eskiden `attached_to_name` sayısına bakıyordu; o alan
	dosyaların çoğunda boş olduğu için sıralama hiçbir şey ayırt etmiyordu.
	Gerçek kullanım 10+ tabloya yayılmış metin alanlarından çıkıyor, SQL'de
	sıralanamıyor — bu yüzden sayı burada üretilip önbelleğe konur, sıralama
	`inventory` tarafında bu haritayla yapılır.
	"""
	key = f"{VERDICT_CACHE_KEY}:counts"
	if not refresh:
		cached = frappe.cache.get_value(key)
		if cached:
			return cached

	counts: dict[str, int] = defaultdict(int)
	for table, column, _kind, _label in LIVE_SOURCES:
		try:
			rows = frappe.db.sql(f"select `{column}` from `{table}` where locate('/files/', `{column}`) > 0")
		except Exception:
			continue
		for (val,) in rows:
			if isinstance(val, str) and "/files/" in val:
				for m in re.findall(r"/(?:private/)?files/[^\"\'\s\\,\)\]}>]+", val):
					counts[m.split("?")[0]] += 1

	out = dict(counts)
	frappe.cache.set_value(key, out, expires_in_sec=VERDICT_TTL)
	return out


def verdict_map_all(deep: bool = False, refresh: bool = False) -> dict[str, str]:
	"""Tüm public dosyalar için `{url: verdict}` — filtreleme bunu kullanır.

	Sayfa başına değil küme başına hesaplanır; aksi hâlde "hiç kullanılmayanları
	göster" filtresi sayfalamayı bozardı (filtre sayfadan sonra uygulanamaz).
	"""
	key = f"{VERDICT_CACHE_KEY}:{'deep' if deep else 'fast'}"
	if not refresh:
		cached = frappe.cache.get_value(key)
		if cached:
			return cached

	live = _referenced_urls(LIVE_SOURCES)
	order = _referenced_urls(ORDER_SOURCES)
	history = _referenced_urls(HISTORY_SOURCES) if deep else set()

	# Kapsam listeyle AYNI olmalı: aksi hâlde "356 hiç kullanılmamış" der ama
	# filtre 333 satır getirir (fark, hassas doctype'lara bağlı ekler).
	from tradehub_core.media.presets import EXCLUDED_DOCTYPES

	excluded = ", ".join(["%s"] * len(EXCLUDED_DOCTYPES))
	urls = [
		r[0]
		for r in frappe.db.sql(
			f"""select file_url from tabFile where is_folder=0 and is_private=0
			and left(file_url, 7) = '/files/' and file_url not in (
				select file_url from tabFile where attached_to_doctype in ({excluded})
				and file_url is not null)
			and (content_hash is null or content_hash not in (
				select content_hash from tabFile where ifnull(content_hash,'')<>''
				and (is_private=1 or attached_to_doctype in ({excluded}))))
			group by file_url""",
			tuple(EXCLUDED_DOCTYPES) * 2,
		)
	]
	out: dict[str, str] = {}
	for u in urls:
		if u in live:
			out[u] = "in_use"
		elif u in order:
			out[u] = "order_only"
		elif not deep:
			out[u] = "not_in_use"
		elif u in history:
			out[u] = "history_only"
		else:
			out[u] = "unused"

	frappe.cache.set_value(key, out, expires_in_sec=VERDICT_TTL)
	return out


def _listing_labels(names: set[str]) -> dict[str, dict]:
	if not names:
		return {}
	rows = frappe.get_all(
		"Listing",
		filters={"name": ["in", list(names)]},
		fields=["name", "title", "status", "seller_profile"],
		limit_page_length=0,
	)
	return {r["name"]: r for r in rows}


def resolve(file_url: str) -> dict:
	"""Tek dosyanın tam kullanım dökümü — detay penceresi bunu gösterir."""
	url = (file_url or "").split("?")[0]
	if not url:
		frappe.throw(frappe._("Dosya yolu zorunlu."))

	wanted = {url}
	usages: list[dict] = []
	listing_names: set[str] = set()

	# ── Canlı kullanım ────────────────────────────────────────────────
	for table, column, kind, label in LIVE_SOURCES:
		extra = "name" if table in ("tabListing", "tabStorefront Layout", "tabAdmin Seller Profile") else "parent, idx"
		if table == "tabListing Variant Item":
			extra = "parent, idx, attribute_type, attribute_value, variant_sku, is_default"
		for row in _match_rows(table, column, [url], extra=extra):
			if not _urls_in(row.get("_val"), wanted):
				continue
			owner = row.get("name") or row.get("parent")
			item = {"kind": kind, "field": label, "doctype": "Listing", "name": owner}
			if kind.startswith("variant"):
				parts = [p for p in (row.get("attribute_type"), row.get("attribute_value")) if p]
				item["variant"] = " · ".join(parts) or "—"
				item["variant_sku"] = row.get("variant_sku") or ""
				item["is_default"] = bool(row.get("is_default"))
			if kind == "listing_gallery":
				item["position"] = row.get("idx")
			if table == "tabStorefront Layout":
				item["doctype"] = "Storefront Layout"
			elif table == "tabAdmin Seller Profile":
				item["doctype"] = "Admin Seller Profile"
			elif table == "tabSeller Gallery Image":
				item["doctype"] = "Admin Seller Profile"
			if item["doctype"] == "Listing" and owner:
				listing_names.add(owner)
			usages.append(item)

	labels = _listing_labels(listing_names)
	for u in usages:
		if u["doctype"] == "Listing":
			meta = labels.get(u["name"]) or {}
			u["label"] = meta.get("title") or u["name"]
			u["status"] = meta.get("status") or ""

	# ── Sipariş kopyaları ─────────────────────────────────────────────
	orders: list[dict] = []
	for table, column, kind, label in ORDER_SOURCES:
		extra = "name" if table == "tabOrder" else "parent"
		for row in _match_rows(table, column, [url], extra=extra):
			if _urls_in(row.get("_val"), wanted):
				orders.append({"kind": kind, "field": label, "name": row.get("name") or row.get("parent")})

	# ── Geçmiş izleri (sayı yeter, detay gürültü) ─────────────────────
	history: list[dict] = []
	for table, column, kind, label in HISTORY_SOURCES:
		n = sum(1 for row in _match_rows(table, column, [url]) if _urls_in(row.get("_val"), wanted))
		if n:
			history.append({"kind": kind, "label": label, "count": n})

	# ── Bu dosyaya işaret eden File kayıtları ─────────────────────────
	records = frappe.get_all(
		"File",
		filters={"file_url": url},
		fields=["name", "file_name", "creation", "owner", "attached_to_doctype", "attached_to_name"],
		order_by="creation asc",
		limit_page_length=0,
	)
	for r in records:
		r["creation"] = str(r["creation"])
		# Bağlı olduğu kayıt hâlâ duruyor mu — Frappe soft-delete yapmadığı için
		# "yok" demek gerçekten silinmiş demek.
		if r.get("attached_to_doctype") and r.get("attached_to_name"):
			try:
				r["target_exists"] = bool(
					frappe.db.exists(r["attached_to_doctype"], r["attached_to_name"])
				)
			except Exception:
				r["target_exists"] = False
		else:
			r["target_exists"] = None

	verdict = (
		"in_use" if usages else "order_only" if orders else "history_only" if history else "unused"
	)

	return {
		"file_url": url,
		"verdict": verdict,
		"usages": usages,
		"orders": orders,
		"history": history,
		"records": records,
		# Kaç kayıt fazladan: aynı dosyaya işaret eden File kayıtlarının
		# kullanılandan fazlası. Temizlik adayı sayısı.
		"redundant_records": max(0, len(records) - max(1, len({u["name"] for u in usages}))),
	}


def storefront_hits(url: str) -> int:
	"""Vitrin JSON'unda geçiyor mu — `Storefront Layout.sections` JSON blob."""
	n = 0
	for row in _match_rows("tabStorefront Layout", "sections", [url], extra="name"):
		try:
			if url in json.dumps(row.get("_val") or ""):
				n += 1
		except Exception:
			continue
	return n
