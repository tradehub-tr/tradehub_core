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


def _search_variants(url: str) -> list[str]:
	r"""Bir adresin veritabanında geçebileceği yazımları.

	`Storefront Layout.sections` JSON'u kaçışlı yazılıyor: `/files/Adsız.jpg`
	orada `/files/Adsız.jpg` olarak duruyor. Yalnız ham yazım arandığı
	sürece o satır hiç GETİRİLMİYORDU — dolayısıyla Türkçe adlı vitrin görselleri
	"kullanılmıyor" görünüp silme adayı oluyordu.
	"""
	kacisli = json.dumps(url, ensure_ascii=True)[1:-1]
	return [url] if kacisli == url else [url, kacisli]


# Bir kaydın hangi mağazaya ait olduğunu söyleyen koşullar. Satıcı kendi medya
# kütüphanesine baktığında kullanım hesabı YALNIZ kendi kayıtları üzerinden
# yapılır: başka satıcının ürününde geçtiği bilgisi ona ne gösterilir ne de
# sayılır.
#
# Buradaki koşullar tablo bazında elle yazıldı çünkü mağaza bağı her tabloda
# farklı: kimi doğrudan alan taşıyor, kimi ana kaydına bakıyor, mağaza kaydının
# kendisi ise zaten mağazanın ta kendisi.
#
# Listede OLMAYAN bir tablo, mağaza süzgeci istendiğinde tamamen DIŞARIDA
# bırakılır (bkz. `_match_rows`). Yeni bir kaynak eklenip buraya koşulu
# yazılmazsa sonuç eksik olur — ama sızıntı olmaz. Yanlış yön bilinçli seçildi.
STORE_FILTERS: dict[str, str] = {
	"tabListing": "seller_profile = %s",
	"tabListing Image": "parent in (select name from tabListing where seller_profile = %s)",
	"tabListing Variant Item": "parent in (select name from tabListing where seller_profile = %s)",
	"tabStorefront Layout": "seller_profile = %s",
	"tabSeller Gallery Image": "parent = %s",
	"tabAdmin Seller Profile": "name = %s",
	"tabCart Item": "seller = %s",
	"tabOrder": "seller = %s",
}


def _match_rows(
	table: str, column: str, urls: list[str], extra: str = "", store: str | None = None
) -> list[dict]:
	"""`urls` içindeki herhangi biri geçen satırları dön. LIKE ile, chunk'lı.

	`store` verilirse yalnız o mağazanın kayıtları taranır.
	"""
	magaza_kosulu = STORE_FILTERS.get(table) if store else None
	if store and not magaza_kosulu:
		# Mağaza bağı tanımlanmamış kaynak — satıcı bağlamında hiç taranmaz.
		return []

	out: list[dict] = []
	for chunk in _chunks(urls):
		# LOCATE: LIKE utf8mb4'te 4 baytlık karakterli satırlarda eşleşmiyor.
		vals = [v for u in chunk for v in _search_variants(u)]
		cond = " or ".join([f"locate(%s, `{column}`) > 0"] * len(vals))
		if magaza_kosulu:
			cond = f"({cond}) and {magaza_kosulu}"
			vals = [*vals, store]
		sel = f"`{column}` as _val" + (f", {extra}" if extra else "")
		try:
			out += frappe.db.sql(f"select {sel} from `{table}` where {cond}", vals, as_dict=True)
		except Exception:
			frappe.log_error(
				title=f"Usage scan failed: {table}.{column}",
				message=frappe.get_traceback(with_context=True),
			)
	return out


def extract_file_urls(value: str | None) -> set[str]:
	"""Bir metin alanında geçen TÜM dosya adresleri — tek kaynak.

	Bu mantığın dört ayrı kopyası vardı ve biri düzeltilince diğerleri geride
	kaldı: liste "kullanılmıyor", detay penceresi "kullanılıyor" diyordu. Aynı
	soruyu iki farklı yerin farklı cevaplaması, silme akışını besleyen bir
	ekranda kabul edilemez — hepsi buradan geçiyor.

	Dosya adında BOŞLUK olabiliyor ve üç yol da gerekli:

	  1. Düz alan (ana görsel, logo): alanın tamamı tek adres. Sadece desen
	     araması yapılırsa boşlukta kesiliyor ve `/files/WhatsApp Image ...jpeg`
	     adresi `/files/WhatsApp` oluyordu — ölçüm: 168 gerçek ürün görseli
	     "kullanılmıyor" görünüyor ve silme adayı listesine düşüyordu.
	  2. Tırnak içinde gömülü (JSON): tırnağa kadar oku, boşluk sorun değil.
	  3. Tırnaksız gömülü: ayraçta kes.
	"""
	if not isinstance(value, str) or "/files/" not in value:
		return set()

	metinler = [value]
	cozulmus = _decode_unicode_escapes(value)
	if cozulmus != value:
		metinler.append(cozulmus)

	found: set[str] = set()
	for metin in metinler:
		found |= set(re.findall(r"/(?:private/)?files/[^\"'\s\\,\)\]}>]+", metin))
		found |= set(re.findall(r"[\"'](/(?:private/)?files/[^\"']+)[\"']", metin))

	duz = value.strip()
	if duz.startswith("/files/") or duz.startswith("/private/files/"):
		found.add(duz)

	temiz = {u.split("?")[0] for u in found}
	return temiz - _truncation_artifacts(temiz)


def _decode_unicode_escapes(value: str) -> str:
	r"""JSON'da kaçışlı yazılmış Türkçe harfleri gerçek harfe çevir.

	`Storefront Layout.sections` JSON'u veritabanına kaçışlı yazılıyor: dosya
	adındaki `ı` harfi metinde `ı` olarak duruyor. Karşılaştırma ham metin
	üzerinde yapıldığı için `/files/Adsız tasarım.jpg` adresi hiç eşleşmiyordu.

	Sonuç YANLIŞ YÖNDEYDİ: vitrin bölümünde kullanılan Türkçe adlı görseller
	"hiçbir yerde kullanılmıyor" görünüyor, yani silme adayı listesine düşüyordu.
	Silinseler vitrin bölümü boş kalırdı.

	Çözülmüş metin ham metnin YERİNE geçmez, yanına eklenir — biri kaçırırsa
	diğeri yakalasın.
	"""
	if "\\u" not in value:
		return value
	return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value)


def _truncation_artifacts(urls: set[str]) -> set[str]:
	"""Boşlukta kesilmiş yarım adresleri ayıkla.

	1. yol (tırnaksız desen) boşlukta durduğu için `/files/2 li süzgeç.tif`
	adresinden ayrıca `/files/2` parçasını da üretiyor. 2. yol tam adresi zaten
	yakaladığı için ikisi birden sete giriyordu.

	Atma koşulu KASITEN dar tutuldu, çünkü fazladan atmak yanlış yönde hata:
	adres listeden düşerse dosya "kullanılmıyor" görünür ve silinebilir hâle
	gelir. Bu yüzden yalnız ikisi birden doğruysa atılır:

	  a) parçanın uzantısı yok — gerçek bir dosya adresi değil,
	  b) aynı metinde bu parçayla başlayıp boşlukla devam eden TAM adres var.

	Yani atılan her parçanın yerine, onu kapsayan tam adres sette duruyor.
	"""
	return {
		kisa
		for kisa in urls
		if "." not in kisa.rsplit("/", 1)[-1]
		and any(uzun.startswith(kisa + " ") for uzun in urls)
	}


def _urls_in(value: str, wanted: set[str]) -> set[str]:
	"""Alanda geçip aradığımız kümede de olan adresler."""
	return extract_file_urls(value) & wanted


def public_urls_for(pairs: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
	"""Kayıtların ziyaretçiye görünen sayfa YOLU (host olmadan).

	TUR-136 "hangi içeriklerde, hangi alanlarda ve **hangi URL'lerde**" diyor.
	İlk iki boyut vardı, üçüncüsü eksikti: bir görselin hangi sayfada göründüğü.
	SEO görünürlüğü de bu boyuttan çıkıyor.

	**Host bilerek eklenmiyor.** Mağaza vitrini backend'den ayrı bir uygulama ve
	adresi ortama göre değişiyor — yerelde ayrı port, prod'da ayrı alan adı.
	Backend bunu güvenilir biçimde bilemez; `get_url()` backend'in kendi adresini
	döndürüyor ve panelde yanlış adres çıkıyordu. Panel `VITE_STOREFRONT_URL` ile
	zaten doğru kökü biliyor, yolu onun başına ekliyor.

	Yol kurgusu SEO modülünden alınıyor (`sitemap_generator.DOCTYPE_CONFIG`);
	burada ikinci bir kurgu yazmak sitemap ile panelin ayrışması demek olurdu.

	Slug'ı olmayan kayıt için boş döner — o sayfa yayında değildir.
	"""
	if not pairs:
		return {}

	try:
		from tradehub_core.seo.sitemap_generator import DOCTYPE_CONFIG
	except Exception:
		frappe.log_error(title="media.usage public_urls import failed", message=frappe.get_traceback())
		return {}

	out: dict[tuple[str, str], str] = {}

	# Doctype başına tek sorgu — kayıt başına sorgu 22 görselli üründe 22 sorgu eder.
	by_doctype: dict[str, set[str]] = defaultdict(set)
	for doctype, name in pairs:
		by_doctype[doctype].add(name)

	for doctype, names in by_doctype.items():
		cfg = DOCTYPE_CONFIG.get(doctype)
		if not cfg:
			continue
		slug_field = cfg.get("slug_field")
		prefix = cfg.get("url_prefix") or ""
		try:
			rows = frappe.get_all(
				doctype,
				filters={"name": ["in", list(names)]},
				fields=["name", slug_field],
				limit_page_length=0,
			)
		except Exception:
			continue
		for row in rows:
			slug = row.get(slug_field)
			if not slug:
				continue
			out[(doctype, row["name"])] = (
				f"{prefix}/{slug}" if prefix else (slug if str(slug).startswith("/") else f"/{slug}")
			)

	return out


def verdicts_for(urls: list[str], deep: bool = False, store: str | None = None) -> dict[str, dict]:
	"""Toplu karar — `{url: {verdict, live, order, history}}`.

	`store` verilirse karar YALNIZ o mağazanın kayıtlarına bakar. Bu kasıtlı:
	satıcı için doğru soru "bu dosyayı BEN kullanıyor muyum" — çünkü sildiğinde
	yalnız kendi bağı kalkıyor, başka mağazanınki olduğu gibi duruyor
	(bkz. `ownership` modülü). Başka mağazanın kullanımını saymak satıcıya
	silemeyeceği bir dosya gösterir ve üstelik o mağazanın varlığını sızdırır.

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
			for row in _match_rows(table, column, list(wanted), store=store):
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
			found |= extract_file_urls(val)
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
			# Aynı alanda aynı adres iki kez geçebilir; kullanım sayısı satır
			# başına birdir, bu yüzden küme üzerinden sayılır.
			for u in extract_file_urls(val):
				counts[u] += 1

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


def resolve(file_url: str, store: str | None = None) -> dict:
	"""Tek dosyanın tam kullanım dökümü — detay penceresi bunu gösterir.

	`store` verilirse döküm YALNIZ o mağazanın kayıtlarını içerir. Satıcı
	penceresinde başka mağazanın ürün adı, mağaza adı veya sayfa adresi
	görünmez; paylaşılan dosyada bile satıcı yalnız kendi kullanımını görür.
	"""
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
		for row in _match_rows(table, column, [url], extra=extra, store=store):
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

	# TUR-136'nın üçüncü boyutu: görselin göründüğü SAYFA adresi. Hangi üründe
	# ve hangi alanda olduğunu biliyorduk ama hangi adreste yayınlandığını değil.
	sayfalar = public_urls_for({(u["doctype"], u["name"]) for u in usages if u.get("name")})
	for u in usages:
		u["page_path"] = sayfalar.get((u["doctype"], u["name"]), "")

	# ── Sipariş kopyaları ─────────────────────────────────────────────
	orders: list[dict] = []
	for table, column, kind, label in ORDER_SOURCES:
		extra = "name" if table == "tabOrder" else "parent"
		for row in _match_rows(table, column, [url], extra=extra, store=store):
			if _urls_in(row.get("_val"), wanted):
				orders.append({"kind": kind, "field": label, "name": row.get("name") or row.get("parent")})

	# ── Geçmiş izleri (sayı yeter, detay gürültü) ─────────────────────
	history: list[dict] = []
	for table, column, kind, label in HISTORY_SOURCES:
		n = sum(
			1
			for row in _match_rows(table, column, [url], store=store)
			if _urls_in(row.get("_val"), wanted)
		)
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


def images_of(doctype: str, name: str) -> dict:
	"""Ters arama — bir kaydın kullandığı TÜM medya (TUR-136).

	`resolve()` "bu dosya nerede kullanılıyor" sorusunu cevaplıyor; bu fonksiyon
	tersini yapar: "bu ürünün / mağazanın hangi görselleri var".

	Ürün sayfasını incelerken ya da bir mağazanın medya yükünü ölçerken tek tek
	dosyadan başlamak zorunda kalmamak için. Silme kararı da kolaylaşır: bir
	üründeki tüm görseller tek listede, hangisi başka ürünlerde de kullanılıyor
	yanında yazılı.
	"""
	name = (name or "").strip()
	if not name:
		frappe.throw(frappe._("Kayıt adı zorunlu."))

	# Hangi kaynak hangi doctype'a ait — ters yönde sorgu için sahiplik kolonu.
	if doctype == "Listing":
		kaynaklar = [
			("tabListing", "primary_image", "listing_main", "Ana görsel", "name"),
			("tabListing", "video_url", "listing_video", "Video", "name"),
			("tabListing Image", "image", "listing_gallery", "Galeri", "parent"),
			("tabListing Variant Item", "variant_image", "variant_main", "Varyant görseli", "parent"),
			("tabListing Variant Item", "variant_gallery", "variant_gallery", "Varyant galerisi", "parent"),
		]
	elif doctype == "Admin Seller Profile":
		kaynaklar = [
			("tabAdmin Seller Profile", "logo", "seller_logo", "Mağaza logosu", "name"),
			("tabSeller Gallery Image", "image", "seller_gallery", "Satıcı galerisi", "parent"),
		]
	elif doctype == "Storefront Layout":
		kaynaklar = [("tabStorefront Layout", "sections", "storefront", "Vitrin düzeni", "name")]
	else:
		frappe.throw(frappe._("Bu kayıt türü için medya taraması tanımlı değil: {0}").format(doctype))

	slotlar: list[dict] = []
	for table, column, kind, label, ownercol in kaynaklar:
		try:
			rows = frappe.db.sql(
				f"""select `{column}` as val, name as rowname
					from `{table}` where `{ownercol}` = %s""",  # noqa: S608 — sabit listeden
				(name,),
				as_dict=True,
			)
		except Exception:
			continue
		for row in rows:
			for url in extract_file_urls(row.get("val")):
				slotlar.append(
					{
						"file_url": url,
						"kind": kind,
						"field": label,
						"row": row["rowname"],
					}
				)

	urls = list({s["file_url"] for s in slotlar})
	# Her görselin BAŞKA yerlerde de kullanılıp kullanılmadığı: silme kararının
	# asıl belirleyicisi. Tek üründe geçen görsel silinebilir, paylaşılan değil.
	kararlar = verdicts_for(urls, deep=True) if urls else {}
	sayilar = usage_counts_all() if urls else {}

	dosyalar = frappe.get_all(
		"File",
		filters={"file_url": ["in", urls]} if urls else {"name": ["is", "not set"]},
		fields=["file_url", "file_name", "file_size", "th_media_state", "th_optimized_at"],
		limit_page_length=0,
	)
	kunye = {}
	for f in dosyalar:
		# Aynı adrese birden çok kayıt işaret edebiliyor; ilki temsilci.
		kunye.setdefault(f["file_url"], f)

	for s in slotlar:
		bilgi = kunye.get(s["file_url"], {})
		s["file_name"] = bilgi.get("file_name") or s["file_url"].rsplit("/", 1)[-1]
		s["file_size"] = bilgi.get("file_size") or 0
		s["state"] = bilgi.get("th_media_state") or ("" if bilgi else "missing")
		s["optimized"] = bool(bilgi.get("th_optimized_at"))
		# `verdicts_for` her url için sözlük döner: {verdict, live, order, history}.
		karar = kararlar.get(s["file_url"]) or {}
		s["verdict"] = karar.get("verdict") or "unused"
		s["live_usage"] = karar.get("live") or 0
		toplam = sayilar.get(s["file_url"], 0)
		s["used_elsewhere"] = max(0, toplam - 1)

	# Kaydın kendi sayfa yolu — host'u panel ekler (ortama göre değişiyor).
	sayfa = public_urls_for({(doctype, name)}).get((doctype, name), "")

	return {
		"doctype": doctype,
		"name": name,
		"page_path": sayfa,
		"slots": slotlar,
		"unique_files": len(urls),
		"total_bytes": sum(kunye.get(u, {}).get("file_size") or 0 for u in urls),
		"missing": [s["file_url"] for s in slotlar if s["state"] == "missing"],
		"shared": [s["file_url"] for s in slotlar if s["used_elsewhere"]],
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
