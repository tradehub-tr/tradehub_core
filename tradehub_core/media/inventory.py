"""Medya envanteri — `tabFile` üzerinden salt okunur listeleme.

Kaynak neden `tabFile`: dosya hangi yoldan yüklenirse yüklensin (Attach, uploader,
API, bulk import) mutlaka bir `File` kaydı oluşur. Yeni bir DocType açmak 4.800
kaydı taşıyan bir backfill patch'i gerektirirdi; bu da prod'da ilk kez çalışan,
local'de hiç test edilmemiş bir kod yolu demekti.

**Tekilleştirme zorunlu:** Frappe `content_hash` ile aynı içeriği tekrar yüklediğinde
yeni fiziksel dosya yazmaz, mevcut dosyayı gösteren yeni bir `File` kaydı açar.
Ölçüm: 938 URL'ye 2.860 kayıt; `/files/515804-5.jpg` için 39 kayıt. Bu yüzden liste
ve toplamlar `file_url` bazında gruplanır — aksi hâlde aynı görsel ızgarada onlarca
kez çıkar ve depolama raporu 1,06 GB yerine 1,49 GB gösterir.

Kapsam: yalnız **public** dosyalar. Private = hassas (KYB/KYC evrakı) ve
`GORSEL-OPTIMIZASYON.md` §7.3 ile kapsam dışı.
"""

from __future__ import annotations

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Coalesce, Count, CustomFunction, Max, Min, Sum

# MariaDB utf8mb4_unicode_ci'de LIKE, 4 baytlık karakter (emoji, matematiksel
# alfabe) içeren satırlarda EŞLEŞMİYOR — ölçüldü: `file_url like '/files/%'`
# 23 dosyayı sessizce düşürüyordu. LEFT/RIGHT karşılaştırması etkilenmiyor.
Left = CustomFunction("LEFT", ["s", "n"])
Right = CustomFunction("RIGHT", ["s", "n"])
Lower = CustomFunction("LOWER", ["s"])
Locate = CustomFunction("LOCATE", ["needle", "haystack"])

# `attached_to_name` boş string olabiliyor; COUNT(DISTINCT ...) boş string'i bir
# değer sayar. NULLIF ile boşu NULL'a çevirip gerçek bağlantı sayısını buluruz.
NullIf = CustomFunction("NULLIF", ["expr", "value"])

# Kapsam dışı doctype listesi `presets`te — `usage` da aynısını kullanıyor.
from tradehub_core.media import engine, ownership, states, timefmt  # noqa: E402
from tradehub_core.media.presets import EXCLUDED_DOCTYPES  # noqa: E402

SORT_FIELDS: dict[str, str] = {
	"size": "file_size",
	"name": "file_name",
	"date": "creation",
}

# Hesaplanmış sütunlar kolon adıyla sıralanamaz; ifadeleri `_order_term` kurar.
COMPUTED_SORTS: tuple[str, ...] = ("saved", "state", "usage")

MAX_PAGE_SIZE: int = 200

# `only_optimizable` filtresi için — motorun gerçekten işleyebildiği formatlar
# ve Kapı 1'in alt sınırı. Uzantılar motordan türetiliyor; elle kopyalandığı
# sürece motora biçim eklenince bu süzgeç sessizce eskiyordu.
OPTIMIZABLE_EXTENSIONS: tuple[str, ...] = engine.supported_extensions()
MIN_OPTIMIZABLE_BYTES: int = 200 * 1024


def _base_query():
	"""Tekilleştirilmiş public dosya sorgusu — filtre/sayfalama bunun üstüne biner."""
	f = DocType("File")
	excluded = (
		frappe.qb.from_(f)
		.select(f.file_url)
		.where(f.attached_to_doctype.isin(EXCLUDED_DOCTYPES))
		.where(f.file_url.isnotnull())
	)

	# ÜÇÜNCÜ emniyet kemeri — içerik bazlı. `is_private` ve `attached_to`
	# kontrolleri KAYIT bazında çalışıyor; aynı belgenin ayrı bir public kaydı
	# varsa ikisi de onu yakalamıyor. Ölçüm: 44 public dosya bir private/hassas
	# belgeyle aynı `content_hash`'e sahip, 6'sı panelde listeleniyordu —
	# bunlardan biri bir KYC kimlik belgesiydi.
	sensitive_hashes = (
		frappe.qb.from_(f)
		.select(f.content_hash)
		.where(f.content_hash.isnotnull())
		.where(f.content_hash != "")
		.where((f.is_private == 1) | f.attached_to_doctype.isin(EXCLUDED_DOCTYPES))
	)

	return f, (
		frappe.qb.from_(f)
		.where(f.is_folder == 0)
		.where(f.is_private == 0)
		.where(Left(f.file_url, 7) == "/files/")
		.where(f.file_url.notin(excluded))
		.where(f.content_hash.isnull() | f.content_hash.notin(sensitive_hashes))
		.groupby(f.file_url)
	)


def _apply_filters(
	f,
	query,
	search: str,
	state: str,
	only_optimizable: bool = False,
	min_bytes: int = 0,
	usage: str = "",
	usage_state: str = "",
	store: str | None = None,
):
	if search:
		# LIKE yerine LOCATE: 4 baytlık karakter içeren dosya adları aksi hâlde
		# aramada hiç çıkmıyor.
		query = query.where(Locate(search, f.file_name) > 0)
	# Durum filtresi `th_media_state` üzerinden (TUR-138). Damga koşulu yedek
	# olarak duruyor: alanı henüz dolmamış kayıtlar (patch öncesi ya da dışarıdan
	# eklenen) filtreden sessizce düşmesin.
	# NULL tuzağı: `Max(state) != 'Trashed'` alan boşken SQL'de NULL döner ve
	# HAVING NULL'ı doğru saymaz — durumu henüz dolmamış kayıtlar listeden
	# sessizce düşüyordu (test T10 yakaladı). COALESCE ile boş değer "" olur.
	# Damgada `Min` kullanılıyor, `Max` değil. Satıcı bir dosyayı bıraktığında
	# YALNIZ kendi kayıtları damgalanıyor (paylaşılan dosyada diğer mağazanınki
	# olduğu gibi kalıyor). `Max` ile bakılırsa tek bir mağazanın bırakması
	# dosyayı yönetim listesinde de çöpe düşürürdü — oysa dosya hâlâ canlı,
	# başka mağaza kullanıyor. `Min` "hepsi bırakmış mı" diye sorar.
	#
	# Yönetimin kendi çöp akışı damgayı zaten TÜM kayıtlara birden yazıyor,
	# dolayısıyla orada `Min` ile `Max` aynı sonucu verir.
	cur_state = Coalesce(Max(f.th_media_state), "")
	if state == "trashed":
		query = query.having((cur_state == states.STATE_TRASHED) | Min(f.th_trashed_at).isnotnull())
	else:
		query = query.having((cur_state != states.STATE_TRASHED) & Min(f.th_trashed_at).isnull())

	if state == "optimized":
		query = query.having(
			(cur_state == states.STATE_ARCHIVED) | Max(f.th_optimized_at).isnotnull()
		)
	elif state == "pending":
		query = query.having(
			(cur_state != states.STATE_ARCHIVED) & Max(f.th_optimized_at).isnull()
		)

	if only_optimizable:
		# Kapı 2 ve 1'in liste karşılığı: yalnız motorun işleyebildiği formatlar ve
		# 200 KB üstü. Kapı 4 (`already_small`) çözünürlük gerektirdiği için burada
		# uygulanamaz — o dosyalar listede görünüp koşuda atlanır.
		ext_filter = None
		for ext in OPTIMIZABLE_EXTENSIONS:
			cond = Lower(Right(f.file_url, len(ext))) == ext
			ext_filter = cond if ext_filter is None else (ext_filter | cond)
		query = query.where(ext_filter)
		query = query.having(Max(f.file_size) >= MIN_OPTIMIZABLE_BYTES)

	if min_bytes:
		query = query.having(Max(f.file_size) >= int(min_bytes))

	# Kullanım tipi: aynı fiziksel dosyaya birden fazla `File` kaydı düşmesinin
	# iki farklı sebebi var ve kullanıcı için anlamları taban tabana zıt.
	#   multi_use → dosya birden fazla KAYITTA kullanılıyor (ör. 8 ilanda aynı görsel)
	#   repeat    → aynı görsel defalarca YÜKLENMİŞ (ör. form 39 kez denenmiş)
	# Kullanım kararı SQL'de üretilemiyor; önbellekli haritadan eşleşen URL
	# kümesi alınıp WHERE'e konur. Python'da süzmek sayfalamayı bozardı:
	# `total` yanlış çıkar ve sayfa 1'de yalnız ilk 50 SQL satırının içindeki
	# eşleşmeler görünürdü.
	if usage_state:
		from tradehub_core.media import usage as usage_mod

		if store:
			# Satıcı için önbellekli GENEL harita kullanılamaz: o harita kararı
			# tüm mağazaların kullanımına göre veriyor. Satıcı kendi kapsamındaki
			# kararı görmeli — başka mağaza kullandığı için "kullanılıyor" yazsa
			# hem yanlış olur hem o mağazanın varlığını ele verir.
			# Küme küçük (mağaza başına yüzlerce dosya), anında hesaplanabilir.
			f_s, q_s = _base_query()
			kendi = [r[0] for r in ownership.scope(q_s, f_s, store).select(f_s.file_url).run()]
			kararlar = usage_mod.verdicts_for(kendi, deep=True, store=store)
			matching = [u for u, v in kararlar.items() if v.get("verdict") == usage_state]
		else:
			matching = [u for u, v in usage_mod.verdict_map_all(deep=True).items() if v == usage_state]
		query = query.where(f.file_url.isin(matching or ["__none__"]))

	if usage == "multi_use":
		query = query.having(Count(NullIf(f.attached_to_name, "")).distinct() > 1)
	elif usage == "repeat":
		query = query.having(Count("*") > 1)
		query = query.having(Count(NullIf(f.attached_to_name, "")).distinct() <= 1)

	return query


def list_files(
	*,
	page: int = 1,
	page_size: int = 50,
	search: str = "",
	state: str = "",
	sort_by: str = "size",
	sort_dir: str = "desc",
	only_optimizable: int = 0,
	min_bytes: int = 0,
	usage: str = "",
	usage_state: str = "",
	store: str | None = None,
) -> dict:
	"""Sayfalı, tekilleştirilmiş dosya listesi.

	`store` verilirse yalnız o mağazanın yüklediği dosyalar döner. Süzgeç
	sorgunun EN BAŞINA giriyor; sayfalama, sıralama ve toplam sayı hepsi
	daraltılmış küme üzerinde hesaplanıyor. Sonradan filtrelenseydi toplam
	sayı başka mağazaların dosya adedini sızdırırdı.
	"""
	page = max(1, int(page or 1))
	page_size = min(MAX_PAGE_SIZE, max(1, int(page_size or 50)))
	f, query = _base_query()
	if store:
		query = ownership.scope(query, f, store)
	query = _apply_filters(
		f, query, search, state, bool(only_optimizable), min_bytes, usage, usage_state, store
	)

	# `usage` sıralaması özel: sayı SQL'de yok. Önce filtreye uyan TÜM url'ler
	# alınır, önbellekli sayıya göre sıralanır, sayfa dilimlenir; sonra yalnız o
	# sayfanın satırları çekilir. Böylece sıralama da sayfalama da doğru olur.
	if sort_by == "usage":
		from tradehub_core.media import usage as _u

		all_urls = [r[0] for r in query.select(f.file_url).run()]
		counts = _u.usage_counts_all()
		all_urls.sort(key=lambda u: counts.get(u, 0), reverse=(sort_dir == "desc"))
		total = len(all_urls)
		page_urls = all_urls[(page - 1) * page_size : page * page_size]
		if not page_urls:
			return {"items": [], "total": total, "page": page, "page_size": page_size}
		f2, q2 = _base_query()
		if store:
			q2 = ownership.scope(q2, f2, store)
		rows = (
			q2.where(f2.file_url.isin(page_urls))
			.select(
				Min(f2.name).as_("name"),
				f2.file_url,
				Min(f2.file_name).as_("file_name"),
				Max(f2.file_size).as_("file_size"),
				Min(f2.creation).as_("creation"),
				Max(f2.th_optimized_at).as_("optimized_at"),
				Max(f2.th_original_size).as_("original_size"),
				Count("*").as_("record_count"),
				Count(NullIf(f2.attached_to_name, "")).distinct().as_("usage_count"),
				Max(f2.attached_to_doctype).as_("usage_doctype"),
			)
			.run(as_dict=True)
		)
		order = {u: i for i, u in enumerate(page_urls)}
		rows.sort(key=lambda r: order.get(r["file_url"], 0))
		return _decorate(rows, total, page, page_size, counts, store=store)

	rows = (
		query.select(
			Min(f.name).as_("name"),
			f.file_url,
			Min(f.file_name).as_("file_name"),
			Max(f.file_size).as_("file_size"),
			Min(f.creation).as_("creation"),
			Max(f.th_optimized_at).as_("optimized_at"),
			Max(f.th_original_size).as_("original_size"),
			Count("*").as_("record_count"),
			Count(NullIf(f.attached_to_name, "")).distinct().as_("usage_count"),
			Max(f.attached_to_doctype).as_("usage_doctype"),
		)
		.orderby(_order_term(f, sort_by), order=frappe.qb.desc if sort_dir == "desc" else frappe.qb.asc)
		.limit(page_size)
		.offset((page - 1) * page_size)
		.run(as_dict=True)
	)


	return _decorate(
		rows,
		_count(search, state, bool(only_optimizable), min_bytes, usage, usage_state, store),
		page,
		page_size,
		store=store,
	)


def _decorate(
	rows: list[dict],
	total: int,
	page: int,
	page_size: int,
	counts: dict | None = None,
	store: str | None = None,
) -> dict:
	"""Satırlara karar/kazanç/kullanım alanlarını ekler.

	`store` verilirse karar ve kullanım sayısı O MAĞAZANIN kapsamında
	hesaplanır. Önbellekli genel harita satıcıya verilemez: başka mağaza
	kullandığı için "kullanılıyor" yazardı — hem satıcı için yanlış bilgi,
	hem o mağazanın varlığının sızması.
	"""
	from tradehub_core.media import usage as usage_mod

	if store:
		# Yalnız EKRANDAKİ satırlar için hesaplanıyor (sayfa başına en çok 200),
		# genel harita gibi tüm envanteri taramıyor.
		urls = [r["file_url"] for r in rows]
		kararlar = usage_mod.verdicts_for(urls, deep=True, store=store)
		vmap = {u: v.get("verdict") for u, v in kararlar.items()}
		counts = {u: v.get("live", 0) for u, v in kararlar.items()}
	else:
		vmap = usage_mod.verdict_map_all(deep=True)
		counts = counts if counts is not None else usage_mod.usage_counts_all()
	for r in rows:
		r["usage_verdict"] = vmap.get(r["file_url"], "unknown")
		r["live_usage"] = counts.get(r["file_url"], 0)
		r["saved_bytes"] = max(0, (r.get("original_size") or 0) - (r.get("file_size") or 0))
		r["state"] = "optimized" if r.get("optimized_at") else "pending"
		r["usage_kind"] = _usage_kind(r.get("record_count") or 1, r.get("usage_count") or 0)
	# Tarihler standart çıktı biçimine çevriliyor (TUR-124): saat dilimi
	# işareti olmadan gönderilen tarih, tarayıcıda kullanıcının kendi saati
	# sanılıyordu — İstanbul dışındaki her kullanıcı saatleri kaymış görüyordu.
	timefmt.apply_all(rows)

	return {"items": rows, "total": total, "page": page, "page_size": page_size}


def _order_term(f, sort_by: str):
	"""Sıralama terimi — düz kolon ya da hesaplanmış ifade.

	`saved` ve `state` ekranda gösterilen ama `tabFile`'da kolon karşılığı olmayan
	değerler; GROUP BY sonucundaki agregattan türetilir.
	"""
	if sort_by == "saved":
		return Max(f.th_original_size) - Max(f.file_size)
	if sort_by == "state":
		return Max(f.th_optimized_at)
	# NOT: "usage" burada YOK — gerçek kullanım sayısı SQL'de üretilemiyor,
	# `list_files` onu önbellekli haritayla Python tarafında sıralıyor.
	return SORT_FIELDS.get(sort_by, "file_size")


def _usage_kind(record_count: int, usage_count: int) -> str:
	"""Satırın rozetini belirler — "kullanılıyor" ile "tekrar yüklenmiş" ayrımı."""
	if usage_count > 1:
		return "multi_use"
	if record_count > 1:
		return "repeat"
	return "single"


def _count(
	search: str,
	state: str,
	only_optimizable: bool = False,
	min_bytes: int = 0,
	usage: str = "",
	usage_state: str = "",
	store: str | None = None,
) -> int:
	"""Tekilleştirilmiş satır sayısı — GROUP BY sonucu sarmalanarak sayılır."""
	f, query = _base_query()
	if store:
		query = ownership.scope(query, f, store)
	query = _apply_filters(f, query, search, state, only_optimizable, min_bytes, usage, usage_state, store)
	sub = query.select(f.file_url)
	rows = frappe.qb.from_(sub).select(Count("*")).run()
	return rows[0][0] if rows else 0


def summary() -> dict:
	"""Üst şerit özeti — dosya adedi, toplam boyut, optimize edilmiş adet, kazanç.

	Tüm değerler tekilleştirilmiş küme üzerinden; `tabFile` satırları toplanmaz.
	"""
	f, query = _base_query()
	sub = query.select(
		f.file_url,
		Max(f.file_size).as_("size"),
		Max(f.th_optimized_at).as_("opt_at"),
		Max(f.th_original_size).as_("orig_size"),
	)

	rows = (
		frappe.qb.from_(sub)
		.select(
			Count("*").as_("count"),
			Sum(sub.size).as_("total_bytes"),
			Sum(sub.orig_size).as_("original_bytes"),
		)
		.run(as_dict=True)
	)
	agg = rows[0] if rows else {}

	opt_rows = (
		frappe.qb.from_(sub)
		.select(Count("*").as_("count"), Sum(sub.size).as_("bytes"))
		.where(sub.opt_at.isnotnull())
		.run(as_dict=True)
	)
	opt = opt_rows[0] if opt_rows else {}

	original_bytes = int(agg.get("original_bytes") or 0)
	optimized_current = int(opt.get("bytes") or 0)
	saved = max(0, original_bytes - optimized_current) if original_bytes else 0

	return {
		"count": int(agg.get("count") or 0),
		"total_bytes": int(agg.get("total_bytes") or 0),
		"optimized_count": int(opt.get("count") or 0),
		"saved_bytes": saved,
	}


def optimized_file_names(
	limit: int = 0,
	*,
	search: str = "",
	min_bytes: int = 0,
) -> list[str]:
	"""Optimize edilmiş dosyaların temsilci `File.name` listesi — toplu geri alma için.

	Filtreler ekrandakiyle aynı; kullanıcı listeyi daralttıysa geri alma da o
	kümeye uygulanır.
	"""
	f, query = _base_query()
	query = _apply_filters(f, query, search, "optimized", False, min_bytes)
	q = query.select(Min(f.name).as_("name")).orderby("file_size", order=frappe.qb.desc)
	if limit:
		q = q.limit(int(limit))
	return [r["name"] for r in q.run(as_dict=True)]


def pending_file_names(
	limit: int = 0,
	*,
	search: str = "",
	only_optimizable: int = 0,
	min_bytes: int = 0,
) -> list[str]:
	"""Henüz optimize edilmemiş dosyaların temsilci `File.name` listesi.

	"Tümünü optimize et" ve "Tahmin et" akışları bunu kullanır. Boyuta göre azalan
	sıralıdır — kazancın çoğu ilk birkaç yüz dosyadan gelir (GORSEL-OPTIMIZASYON.md §2.1).

	Filtreler ekrandakiyle aynıdır: kullanıcı listeyi "1 MB üstü + optimize
	edilebilir"e daralttıysa toplu işlem de o kümeye uygulanır. Aksi hâlde ekranda
	209 satır görüp 2.826 dosyalık iş başlatmış olurdu.
	"""
	f, query = _base_query()
	query = _apply_filters(f, query, search, "pending", bool(only_optimizable), min_bytes)
	q = query.select(Min(f.name).as_("name")).orderby("file_size", order=frappe.qb.desc)
	if limit:
		q = q.limit(int(limit))
	return [r["name"] for r in q.run(as_dict=True)]
