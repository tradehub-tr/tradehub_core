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

import mimetypes
import re
from datetime import datetime, timedelta

import frappe
from frappe.query_builder import Case, DocType
from frappe.query_builder.functions import Coalesce, Count, CustomFunction, Max, Min, Sum

# MariaDB utf8mb4_unicode_ci'de LIKE, 4 baytlık karakter (emoji, matematiksel
# alfabe) içeren satırlarda EŞLEŞMİYOR — ölçüldü: `file_url like '/files/%'`
# 23 dosyayı sessizce düşürüyordu. LEFT/RIGHT karşılaştırması etkilenmiyor.
Left = CustomFunction("LEFT", ["s", "n"])
Right = CustomFunction("RIGHT", ["s", "n"])
Lower = CustomFunction("LOWER", ["s"])
Locate = CustomFunction("LOCATE", ["needle", "haystack"])
FindInSet = CustomFunction("FIND_IN_SET", ["needle", "haystack"])

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

# Satıcı kütüphanesinin filtre sözlüğü. Dosyanın MIME değeri ayrı bir kolonda
# tutulmuyor; yükleme kapısının doğruladığı uzantıdan kararlı bir MIME ailesi
# türetiliyor. Aynı sözlük hem `kind` hem `mime_types` filtresini beslediği için
# panel ile API'nin "video / belge / görsel" yorumu ayrışmıyor.
VIDEO_EXTENSIONS: frozenset[str] = frozenset({"mp4", "webm", "mov", "avi", "mkv", "m4v"})
DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
	{"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "rtf", "ppt", "pptx", "zip"}
)
IMAGE_EXTENSIONS: frozenset[str] = frozenset(
	{"jpg", "jpeg", "png", "webp", "gif", "avif", "bmp", "tif", "tiff", "heic", "heif", "svg"}
)
KIND_EXTENSIONS: dict[str, frozenset[str]] = {
	"video": VIDEO_EXTENSIONS,
	"document": DOCUMENT_EXTENSIONS,
	"image": IMAGE_EXTENSIONS,
}
MIME_EXTENSIONS: dict[str, frozenset[str]] = {
	"image/*": IMAGE_EXTENSIONS,
	"video/*": VIDEO_EXTENSIONS,
	"application/*": DOCUMENT_EXTENSIONS,
	"image/jpeg": frozenset({"jpg", "jpeg"}),
	"image/png": frozenset({"png"}),
	"image/webp": frozenset({"webp"}),
	"image/gif": frozenset({"gif"}),
	"image/avif": frozenset({"avif"}),
	"image/bmp": frozenset({"bmp"}),
	"image/tiff": frozenset({"tif", "tiff"}),
	"image/heic": frozenset({"heic"}),
	"image/heif": frozenset({"heif"}),
	"image/svg+xml": frozenset({"svg"}),
	"video/mp4": frozenset({"mp4", "m4v"}),
	"video/webm": frozenset({"webm"}),
	"video/quicktime": frozenset({"mov"}),
	"video/x-msvideo": frozenset({"avi"}),
	"video/x-matroska": frozenset({"mkv"}),
	"application/pdf": frozenset({"pdf"}),
	"text/plain": frozenset({"txt"}),
	"text/csv": frozenset({"csv"}),
	"application/rtf": frozenset({"rtf"}),
	"application/zip": frozenset({"zip"}),
	"application/msword": frozenset({"doc"}),
	"application/vnd.openxmlformats-officedocument.wordprocessingml.document": frozenset({"docx"}),
	"application/vnd.ms-excel": frozenset({"xls"}),
	"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": frozenset({"xlsx"}),
	"application/vnd.ms-powerpoint": frozenset({"ppt"}),
	"application/vnd.openxmlformats-officedocument.presentationml.presentation": frozenset({"pptx"}),
}

SIZE_BUCKETS: dict[str, tuple[int | None, int | None]] = {
	"small": (None, 500_000),
	"medium": (500_000, 5_000_000),
	"large": (5_000_000, None),
}
ORIENTATIONS: frozenset[str] = frozenset({"landscape", "portrait", "square", "other"})
FILTER_FLAGS: frozenset[str] = frozenset({"favorite", "missingalt"})
FILTER_OWNERS: frozenset[str] = frozenset({"self", "shared"})
FILTER_LIST_LIMIT: int = 20
MAX_FILTER_TEXT: int = 200
MAX_FILTER_BYTES: int = 10 * 1024**4  # 10 TiB: taşma/yanlış birim girdisine sınır.
_FORMAT_TOKEN = re.compile(r"^[a-z0-9]{1,12}$")
_DATE_TOKEN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# `only_optimizable` filtresi için — motorun gerçekten işleyebildiği formatlar
# ve Kapı 1'in alt sınırı. Uzantılar motordan türetiliyor; elle kopyalandığı
# sürece motora biçim eklenince bu süzgeç sessizce eskiyordu.
OPTIMIZABLE_EXTENSIONS: tuple[str, ...] = engine.supported_extensions()
MIN_OPTIMIZABLE_BYTES: int = 200 * 1024

# Video durumu GRUPLANMIŞ satırda toplanıyor: aynı `file_url`'e 39 kayda kadar
# işaret edebiliyor (bkz. modül docstring'i) ve bu kayıtların durumları
# AYRIŞABİLİYOR — biri `failed`, biri `processing` olabilir. Önceden `Max()`
# doğrudan metin üstünde alınıyordu; alfabetik sıra (`ready` > `processing` >
# `failed`) yüzünden başarısız bir dosya panelde "işleniyor", hatta "hazır"
# görünüyordu. Artık açık öncelik: kötü haber kazanır.
_VIDEO_STATUS_RANKS: tuple[tuple[str, int], ...] = (
	("failed", 3),
	("processing", 2),
	("ready", 1),
)
_RANK_TO_STATUS: dict[int, str] = {rank: durum for durum, rank in _VIDEO_STATUS_RANKS}


def _video_status_term(f):
	"""Grup içindeki en "kötü" video durumunu seçen toplama ifadesi."""
	ifade = Case()
	for durum, rank in _VIDEO_STATUS_RANKS:
		ifade = ifade.when(f.th_media_video_status == durum, rank)
	return Max(ifade.else_(0)).as_("video_status_rank")


# Tarama durumu (TUR-125) — video durumuyla AYNI gerekçe: aynı adrese işaret
# eden kayıtların durumları ayrışabilir ve metin üstünde `Max()` almak alfabetik
# sıraya düşer (`pending` > `infected`), yani zararlı bir dosya panelde
# "taranıyor" görünürdü. Açık öncelik: kötü haber kazanır.
_SCAN_STATUS_RANKS: tuple[tuple[str, int], ...] = (
	("infected", 4),
	("failed", 3),
	("pending", 2),
	("clean", 1),
)
_RANK_TO_SCAN: dict[int, str] = {rank: durum for durum, rank in _SCAN_STATUS_RANKS}


def _scan_status_term(f):
	"""Grup içindeki en "kötü" tarama durumunu seçen toplama ifadesi."""
	ifade = Case()
	for durum, rank in _SCAN_STATUS_RANKS:
		ifade = ifade.when(f.th_media_scan_status == durum, rank)
	return Max(ifade.else_(0)).as_("scan_status_rank")


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


def _filter_error(message: str):
	frappe.throw(frappe._(message), exc=frappe.ValidationError)


def _list_filter(
	value,
	name: str,
	*,
	allowed: frozenset[str] | set[str] | None = None,
	lower: bool = True,
	max_length: int = 80,
) -> tuple[str, ...]:
	"""HTTP dizi parametresini doğrulanmış, tekil tuple'a çevir.

	Frappe GET parametreleri JSON metni olarak gelebiliyor; elle API kullananlar
	için virgüllü biçim de geriye uyumlu kabul edilir. Bozuk JSON'u sessizce tek
	bir etikete çevirmek yerine 417 döner: istemci yanlış filtreyle eksik sonuç
	görüp bunu gerçek envanter sanmamalı.
	"""
	if value in (None, "", (), []):
		return ()
	raw = value
	if isinstance(value, str):
		text = value.strip()
		if not text:
			return ()
		if text.startswith(("[", "{")):
			try:
				raw = frappe.parse_json(text)
			except Exception:
				_filter_error(f"{name} geçerli bir JSON dizisi olmalı.")
		else:
			raw = text.split(",")
	if not isinstance(raw, list | tuple | set):
		_filter_error(f"{name} bir dizi olmalı.")
	if len(raw) > FILTER_LIST_LIMIT:
		_filter_error(f"{name} en çok {FILTER_LIST_LIMIT} değer içerebilir.")

	out: list[str] = []
	for item in raw:
		text = str(item or "").strip()
		if not text:
			continue
		if len(text) > max_length:
			_filter_error(f"{name} içindeki bir değer çok uzun.")
		if lower:
			text = text.lower()
		if allowed is not None and text not in allowed:
			_filter_error(f"{name} içinde desteklenmeyen değer var: {text}")
		if text not in out:
			out.append(text)
	return tuple(out)


def _format_filter(value) -> tuple[str, ...]:
	formats = _list_filter(value, "formats", max_length=12)
	clean: list[str] = []
	for ext in formats:
		ext = ext.removeprefix(".")
		if not _FORMAT_TOKEN.fullmatch(ext):
			_filter_error(f"Geçersiz dosya formatı: {ext}")
		clean.append(ext)
	return tuple(clean)


def _text_filter(value, name: str) -> str:
	text = str(value or "").strip()
	if len(text) > MAX_FILTER_TEXT:
		_filter_error(f"{name} en çok {MAX_FILTER_TEXT} karakter olabilir.")
	return text


def _byte_filter(value, name: str) -> int | None:
	if value in (None, ""):
		return None
	try:
		# `int(1.2)` sessizce 1 yapar; HTTP sözleşmesi yalnız tam sayı kabul eder.
		if isinstance(value, float) or not re.fullmatch(r"\d+", str(value).strip()):
			raise ValueError
		number = int(value)
	except (TypeError, ValueError):
		_filter_error(f"{name} sıfır veya pozitif bir tam sayı olmalı.")
	if number > MAX_FILTER_BYTES:
		_filter_error(f"{name} desteklenen üst sınırı aşıyor.")
	return number


def _usage_count_filter(value, name: str) -> int | None:
	if value in (None, ""):
		return None
	try:
		if not re.fullmatch(r"\d+", str(value).strip()):
			raise ValueError
		return int(value)
	except (TypeError, ValueError):
		_filter_error(f"{name} sıfır veya pozitif bir tam sayı olmalı.")


def _date_filter(value, name: str, *, upper: bool = False) -> datetime | None:
	"""YYYY-MM-DD sınırını DateTime'a çevir; üst sınır ertesi gün hariçtir."""
	if value in (None, ""):
		return None
	text = str(value).strip()
	if not _DATE_TOKEN.fullmatch(text):
		_filter_error(f"{name} YYYY-MM-DD biçiminde olmalı.")
	try:
		value_dt = datetime.strptime(text, "%Y-%m-%d")
	except ValueError:
		_filter_error(f"{name} geçerli bir tarih olmalı.")
	return value_dt + timedelta(days=1) if upper else value_dt


def normalize_list_filters(
	*,
	search: str = "",
	state: str = "",
	only_optimizable: int = 0,
	min_bytes: int | str | None = 0,
	max_bytes: int | str | None = None,
	usage: str = "",
	usage_state: str = "",
	name_search: str = "",
	kinds=None,
	formats=None,
	mime_types=None,
	orientations=None,
	size_buckets=None,
	date_from: str = "",
	date_to: str = "",
	tags=None,
	categories=None,
	flags=None,
	owners=None,
	usage_min: int | str | None = None,
	usage_max: int | str | None = None,
) -> dict:
	"""Liste filtresi HTTP sözleşmesini tek noktada doğrula ve normalize et."""
	state = str(state or "").strip().lower()
	if state not in {"", "trashed", "optimized", "pending"}:
		_filter_error(f"Geçersiz medya durumu: {state}")
	usage = str(usage or "").strip().lower()
	if usage not in {"", "multi_use", "repeat"}:
		_filter_error(f"Geçersiz kullanım tipi: {usage}")
	usage_state = str(usage_state or "").strip().lower()
	if usage_state not in {"", "in_use", "order_only", "history_only", "unused", "not_in_use"}:
		_filter_error(f"Geçersiz kullanım durumu: {usage_state}")

	try:
		optimizable_value = int(only_optimizable or 0)
	except (TypeError, ValueError):
		_filter_error("only_optimizable 0 veya 1 olmalı.")
	if optimizable_value not in {0, 1}:
		_filter_error("only_optimizable 0 veya 1 olmalı.")
	optimizable = bool(optimizable_value)

	clean_tags = _list_filter(tags, "tags", lower=False, max_length=50)
	if any("," in tag for tag in clean_tags):
		_filter_error("Etiket virgül içeremez.")
	clean_categories = _list_filter(categories, "categories", lower=False, max_length=140)
	if any("," in category for category in clean_categories):
		_filter_error("Kategori kimliği virgül içeremez.")
	clean_mimes = _list_filter(mime_types, "mime_types", allowed=set(MIME_EXTENSIONS))

	return {
		"search": _text_filter(search, "search"),
		"state": state,
		"only_optimizable": optimizable,
		"min_bytes": _byte_filter(min_bytes, "min_bytes") or 0,
		"max_bytes": _byte_filter(max_bytes, "max_bytes"),
		"usage": usage,
		"usage_state": usage_state,
		"name_search": _text_filter(name_search, "name_search"),
		"kinds": _list_filter(kinds, "kinds", allowed=set(KIND_EXTENSIONS)),
		"formats": _format_filter(formats),
		"mime_types": clean_mimes,
		"orientations": _list_filter(orientations, "orientations", allowed=set(ORIENTATIONS)),
		"size_buckets": _list_filter(size_buckets, "size_buckets", allowed=set(SIZE_BUCKETS)),
		"date_from": _date_filter(date_from, "date_from"),
		"date_to": _date_filter(date_to, "date_to", upper=True),
		"tags": clean_tags,
		"categories": clean_categories,
		"flags": _list_filter(flags, "flags", allowed=set(FILTER_FLAGS)),
		"owners": _list_filter(owners, "owners", allowed=set(FILTER_OWNERS)),
		"usage_min": _usage_count_filter(usage_min, "usage_min"),
		"usage_max": _usage_count_filter(usage_max, "usage_max"),
	}


def _or_conditions(conditions):
	result = None
	for condition in conditions:
		result = condition if result is None else (result | condition)
	return result


def _extension_condition(f, extensions: set[str] | frozenset[str] | tuple[str, ...]):
	return _or_conditions(Lower(Right(f.file_url, len(ext) + 1)) == f".{ext}" for ext in sorted(extensions))


def _kind_condition(f, kinds: tuple[str, ...]):
	"""Panelin tür semantiği: bilinen video/belge dışındaki dosya görseldir."""
	video = _extension_condition(f, VIDEO_EXTENSIONS)
	document = _extension_condition(f, DOCUMENT_EXTENSIONS)
	conditions = []
	for kind in kinds:
		if kind == "video":
			conditions.append(video)
		elif kind == "document":
			conditions.append(document)
		else:
			conditions.append(~(video | document))
	return _or_conditions(conditions)


def _metadata_query(store: str | None):
	"""Satıcıya ait üstveri URL'leri için kiracı-sınırlı alt sorgu."""
	m = DocType("File")
	query = frappe.qb.from_(m).select(m.file_url).where(m.file_url.isnotnull())
	if store:
		query = query.where(m.owner.isin(list(ownership.users_of(store)) or ["__none__"]))
	return m, query


def _matching_usage_urls(
	store: str | None,
	usage_state: str,
	usage_min: int | None,
	usage_max: int | None,
) -> tuple[str, ...]:
	"""Kullanım filtresini bir kez çöz; liste ve COUNT aynı URL kümesini kullansın."""
	from tradehub_core.media import usage as usage_mod

	if store:
		# Satıcı için genel harita kullanılamaz: başka mağazanın kullanımını hem
		# sayar hem sızdırır. Küme tenant'a SQL'de daraltıldıktan sonra taranır.
		f_s, q_s = _base_query()
		urls = [r[0] for r in ownership.scope(q_s, f_s, store).select(f_s.file_url).run()]
		verdicts = usage_mod.verdicts_for(urls, deep=True, store=store)
	else:
		global_verdicts = usage_mod.verdict_map_all(deep=True)
		counts = usage_mod.usage_counts_all()
		verdicts = {
			u: {"verdict": verdict, "live": counts.get(u, 0)} for u, verdict in global_verdicts.items()
		}

	matching = []
	for url, verdict in verdicts.items():
		if usage_state and verdict.get("verdict") != usage_state:
			continue
		live = int(verdict.get("live") or 0)
		if usage_min is not None and live < usage_min:
			continue
		if usage_max is not None and live > usage_max:
			continue
		matching.append(url)
	return tuple(matching)


def _apply_filters(
	f,
	query,
	search: str,
	state: str,
	only_optimizable: bool = False,
	min_bytes: int = 0,
	max_bytes: int | None = None,
	usage: str = "",
	usage_state: str = "",
	store: str | None = None,
	name_search: str = "",
	kinds: tuple[str, ...] = (),
	formats: tuple[str, ...] = (),
	mime_types: tuple[str, ...] = (),
	orientations: tuple[str, ...] = (),
	size_buckets: tuple[str, ...] = (),
	date_from: datetime | None = None,
	date_to: datetime | None = None,
	tags: tuple[str, ...] = (),
	categories: tuple[str, ...] = (),
	flags: tuple[str, ...] = (),
	owners: tuple[str, ...] = (),
	usage_min: int | None = None,
	usage_max: int | None = None,
	usage_urls: tuple[str, ...] | None = None,
):
	if search:
		# Serbest arama dosya adı + satıcının kendi başlık/etiket alanlarında.
		# Üstveri için ayrı, tenant-sınırlı alt sorgu şart: `ownership.scope`,
		# mağazanın ürününde kullandığı ama başka kullanıcının yüklediği dosyayı da
		# kapsar; o yabancı kaydın başlık/etiketini aramak veri sızdırırdı.
		m, metadata_urls = _metadata_query(store)
		metadata_urls = metadata_urls.where(
			(Locate(search, m.th_media_title) > 0) | (Locate(search, m.th_media_tags) > 0)
		)
		# Kategori adı da genel aramanın parçasıdır. Bağ alt sorgusu ayrıca
		# tenant'a daraltılır; yabancı mağazanın aynı URL için verdiği kategori
		# adı arama sonucunu etkileyemez.
		category = DocType("Media Category")
		assignment = DocType("Media Category Assignment")
		matching_categories = (
			frappe.qb.from_(category)
			.select(category.name)
			.where(Locate(search, category.category_name) > 0)
		)
		if store:
			matching_categories = matching_categories.where(category.store == store)
		category_urls = frappe.qb.from_(assignment).select(assignment.file_url).where(
			assignment.category.isin(matching_categories)
		)
		if store:
			category_urls = category_urls.where(assignment.store == store)
		query = query.where(
			(Locate(search, f.file_name) > 0)
			| f.file_url.isin(metadata_urls)
			| f.file_url.isin(category_urls)
		)
	if name_search:
		# Sütun filtresi serbest aramadan ayrı: yalnız görünen dosya adı.
		query = query.where(Locate(name_search, f.file_name) > 0)
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
		query = query.having((cur_state == states.STATE_ARCHIVED) | Max(f.th_optimized_at).isnotnull())
	elif state == "pending":
		query = query.having((cur_state != states.STATE_ARCHIVED) & Max(f.th_optimized_at).isnull())

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
	if max_bytes is not None:
		query = query.having(Max(f.file_size) <= max_bytes)

	# Aynı filtre içindeki seçenekler OR, farklı filtre aileleri AND. Bu ayrım
	# özellikle "small + large" gibi kesintili boyut kümelerinde tek min/max'a
	# indirgenip orta boyutların yanlışlıkla dahil edilmesini engeller.
	if size_buckets:
		bucket_conditions = []
		for bucket in size_buckets:
			lower, upper = SIZE_BUCKETS[bucket]
			condition = None
			if lower is not None:
				condition = Max(f.file_size) >= lower
			if upper is not None:
				upper_condition = Max(f.file_size) < upper
				condition = upper_condition if condition is None else (condition & upper_condition)
			bucket_conditions.append(condition)
		query = query.having(_or_conditions(bucket_conditions))

	if date_from is not None:
		query = query.having(Min(f.creation) >= date_from)
	if date_to is not None:
		# `date_to` normalize edilirken ertesi günün başlangıcına çevrilir; böylece
		# YYYY-MM-DD üst sınırı o günün 23:59:59.999 değerlerini de içerir.
		query = query.having(Min(f.creation) < date_to)

	if kinds and set(kinds) != set(KIND_EXTENSIONS):
		query = query.where(_kind_condition(f, kinds))
	if formats:
		query = query.where(_extension_condition(f, formats))
	if mime_types:
		mime_extensions: set[str] = set()
		for mime in mime_types:
			mime_extensions.update(MIME_EXTENSIONS[mime])
		query = query.where(_extension_condition(f, mime_extensions))

	if orientations:
		width = Coalesce(Max(f.th_media_width), 0)
		height = Coalesce(Max(f.th_media_height), 0)
		orientation_conditions = []
		for orientation in orientations:
			if orientation == "landscape":
				orientation_conditions.append((width > height) & (height > 0))
			elif orientation == "portrait":
				orientation_conditions.append((height > width) & (width > 0))
			elif orientation == "square":
				orientation_conditions.append((width == height) & (width > 0))
			else:
				orientation_conditions.append((width <= 0) | (height <= 0))
		query = query.having(_or_conditions(orientation_conditions))

	if tags:
		m, metadata_urls = _metadata_query(store)
		for tag in tags:
			metadata_urls = metadata_urls.where(FindInSet(tag, m.th_media_tags) > 0)
		query = query.where(f.file_url.isin(metadata_urls))

	if categories:
		# Bir aile içindeki çoklu kategori seçimi AND'dir: seçilen kategorilerin
		# tümüne sahip medya döner. Her alt sorgu tenant'a daraltılır.
		assignment = DocType("Media Category Assignment")
		for category_id in categories:
			category_urls = (
				frappe.qb.from_(assignment)
				.select(assignment.file_url)
				.where(assignment.category == category_id)
			)
			if store:
				category_urls = category_urls.where(assignment.store == store)
			query = query.where(f.file_url.isin(category_urls))

	if "favorite" in flags:
		m, favorite_urls = _metadata_query(store)
		query = query.where(f.file_url.isin(favorite_urls.where(m.th_media_favorite == 1)))
	if "missingalt" in flags:
		m, missing_alt_urls = _metadata_query(store)
		missing_alt_urls = missing_alt_urls.where(Coalesce(m.th_media_alt, "") == "")
		query = query.where(f.file_url.isin(missing_alt_urls)).where(_kind_condition(f, ("image",)))

	# Satıcı liste modeli bugün yalnız `self` üretir. `shared` tek başına
	# seçilirse ilk 200 kaydı yerelde süzüp yanlış toplam göstermek yerine SQL
	# düzeyinde dürüst boş küme döner; `self + shared` tüm mevcut kapsamdır.
	if owners and "self" not in owners:
		query = query.where(f.name == "__none__")

	# Kullanım tipi: aynı fiziksel dosyaya birden fazla `File` kaydı düşmesinin
	# iki farklı sebebi var ve kullanıcı için anlamları taban tabana zıt.
	#   multi_use → dosya birden fazla KAYITTA kullanılıyor (ör. 8 ilanda aynı görsel)
	#   repeat    → aynı görsel defalarca YÜKLENMİŞ (ör. form 39 kez denenmiş)
	# Kullanım kararı SQL'de üretilemiyor; önbellekli haritadan eşleşen URL
	# kümesi alınıp WHERE'e konur. Python'da süzmek sayfalamayı bozardı:
	# `total` yanlış çıkar ve sayfa 1'de yalnız ilk 50 SQL satırının içindeki
	# eşleşmeler görünürdü.
	if usage_state or usage_min is not None or usage_max is not None:
		matching = (
			usage_urls
			if usage_urls is not None
			else _matching_usage_urls(store, usage_state, usage_min, usage_max)
		)
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
	max_bytes: int | None = None,
	usage: str = "",
	usage_state: str = "",
	name_search: str = "",
	kinds=None,
	formats=None,
	mime_types=None,
	orientations=None,
	size_buckets=None,
	date_from: str = "",
	date_to: str = "",
	tags=None,
	categories=None,
	flags=None,
	owners=None,
	usage_min: int | None = None,
	usage_max: int | None = None,
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
	filters = normalize_list_filters(
		search=search,
		state=state,
		only_optimizable=only_optimizable,
		min_bytes=min_bytes,
		max_bytes=max_bytes,
		usage=usage,
		usage_state=usage_state,
		name_search=name_search,
		kinds=kinds,
		formats=formats,
		mime_types=mime_types,
		orientations=orientations,
		size_buckets=size_buckets,
		date_from=date_from,
		date_to=date_to,
		tags=tags,
		categories=categories,
		flags=flags,
		owners=owners,
		usage_min=usage_min,
		usage_max=usage_max,
	)
	if filters["usage_state"] or filters["usage_min"] is not None or filters["usage_max"] is not None:
		filters["usage_urls"] = _matching_usage_urls(
			store,
			filters["usage_state"],
			filters["usage_min"],
			filters["usage_max"],
		)
	f, query = _base_query()
	if store:
		query = ownership.scope(query, f, store)
	query = _apply_filters(f, query, store=store, **filters)

	# `usage` sıralaması özel: sayı SQL'de yok. Önce filtreye uyan TÜM url'ler
	# alınır, önbellekli sayıya göre sıralanır, sayfa dilimlenir; sonra yalnız o
	# sayfanın satırları çekilir. Böylece sıralama da sayfalama da doğru olur.
	sort_by = str(sort_by or "size").strip()
	if sort_by not in {*SORT_FIELDS, *COMPUTED_SORTS, "format"}:
		sort_by = "size"
	sort_dir = "asc" if str(sort_dir or "").lower() == "asc" else "desc"
	if sort_by == "usage":
		from tradehub_core.media import usage as _u

		all_urls = [r[0] for r in query.select(f.file_url).run()]
		if store:
			# Global sayaç başka mağazaların kullanımını hem sıraya yansıtır hem de
			# dolaylı bilgi sızdırır. Satıcı sırası kendi canlı kullanımına göre.
			store_usage = _u.verdicts_for(all_urls, deep=False, store=store)
			counts = {url: int(value.get("live") or 0) for url, value in store_usage.items()}
		else:
			counts = _u.usage_counts_all()
		all_urls.sort(key=lambda u: (counts.get(u, 0), u), reverse=(sort_dir == "desc"))
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
				Max(f2.th_media_video_status).as_("video_status"),
				Max(f2.th_original_size).as_("original_size"),
				Max(f2.th_media_width).as_("width"),
				Max(f2.th_media_height).as_("height"),
				Count("*").as_("record_count"),
				Count(NullIf(f2.attached_to_name, "")).distinct().as_("usage_count"),
				Max(f2.attached_to_doctype).as_("usage_doctype"),
				# Video işleme durumu (TUR-296) — panel "işleniyor/başarısız"
				# rozetini buradan okur. Grup içinde en kötü durum kazanır;
				# gerekçe `_video_status_term` yorumunda.
				_video_status_term(f2),
				# Tarama durumu (TUR-125) — karantina rozeti bunu okur.
				_scan_status_term(f2),
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
			# Dedup gruplamasında Max yeterli: durum `file_url` filtresiyle tüm
			# kayıtlara birden yazılıyor (enqueue_transcode), kopyalar ayrışmaz.
			Max(f.th_media_video_status).as_("video_status"),
			Max(f.th_original_size).as_("original_size"),
			Max(f.th_media_width).as_("width"),
			Max(f.th_media_height).as_("height"),
			Count("*").as_("record_count"),
			Count(NullIf(f.attached_to_name, "")).distinct().as_("usage_count"),
			Max(f.attached_to_doctype).as_("usage_doctype"),
			# Video işleme durumu (TUR-296) — üstteki usage-sıralı dalla aynı.
			_video_status_term(f),
			# Tarama durumu (TUR-125) — üstteki dalla aynı.
			_scan_status_term(f),
		)
		.orderby(_order_term(f, sort_by), order=frappe.qb.desc if sort_dir == "desc" else frappe.qb.asc)
		.orderby(f.file_url, order=frappe.qb.asc)
		.limit(page_size)
		.offset((page - 1) * page_size)
		.run(as_dict=True)
	)

	return _decorate(
		rows,
		_count(filters, store),
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
	from tradehub_core.media import thumbs as thumbs_mod
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
	# Küçük resimler hazır türevlerden: orijinal 1.4 MB yerine 2-6 KB'lık
	# webp. Türevi olmayan dosya haritada yoktur, ön yüz orijinale düşer.
	tmap = thumbs_mod.thumbs_for([r["file_url"] for r in rows])
	for r in rows:
		turev = tmap.get(r["file_url"]) or {}
		r["thumb_url"] = turev.get("thumb", "")
		r["preview_url"] = turev.get("preview", "")
		# MIME ayrı DB kolonu değil; yükleme politikasında doğrulanan görünen
		# addan standart değer türetilir. Filtre de aynı uzantı sözlüğünü kullanır.
		r["mime_type"] = (
			mimetypes.guess_type(r.get("file_name") or r.get("file_url") or "")[0]
			or "application/octet-stream"
		)
		r["usage_verdict"] = vmap.get(r["file_url"], "unknown")
		r["live_usage"] = counts.get(r["file_url"], 0)
		r["saved_bytes"] = max(0, (r.get("original_size") or 0) - (r.get("file_size") or 0))
		r["state"] = "optimized" if r.get("optimized_at") else "pending"
		r["usage_kind"] = _usage_kind(r.get("record_count") or 1, r.get("usage_count") or 0)
		# Sıra numarası SQL'in iç işi; ön yüz durum metni bekliyor. 0 = bu adreste
		# video durumu olan hiçbir kayıt yok (video değil ya da hiç işlenmemiş).
		r["video_status"] = _RANK_TO_STATUS.get(int(r.pop("video_status_rank", 0) or 0), "")
		# 0 = bu adreste tarama durumu olan hiçbir kayıt yok. Boş string BİLEREK
		# "temiz" değil: taranmamış dosyayı temiz göstermek bu alanın en tehlikeli
		# yanlışı olurdu (yamada backfill yapılmamasının gerekçesiyle aynı).
		r["scan_status"] = _RANK_TO_SCAN.get(int(r.pop("scan_status_rank", 0) or 0), "")
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
	if sort_by == "format":
		return Min(f.file_type)
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


def _count(filters: dict, store: str | None = None) -> int:
	"""Tekilleştirilmiş satır sayısı — GROUP BY sonucu sarmalanarak sayılır."""
	f, query = _base_query()
	if store:
		query = ownership.scope(query, f, store)
	query = _apply_filters(f, query, store=store, **filters)
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


def library_facets(store: str, state: str = "") -> dict:
	"""Kiracı envanterinin filtre seçenekleri ve filtresiz sayaçları.

	Liste sayfasının ilk 12/24 satırından seçenek üretmek, sonraki sayfadaki bir
	formatı veya etiketi menüden tamamen yok ediyordu. Bu katalog sorgusu aynı
	public/hassas-içerik/state kemerlerini kullanır. Üstveri agregatları yalnız
	mağazanın kendi kullanıcı satırlarından alınır; salt kullanım yoluyla görünen
	bir dosyanın başka sahibine ait başlığı/etiketi sızdırılmaz.
	"""
	f, query = _base_query()
	query = ownership.scope(query, f, store)
	filters = normalize_list_filters(state=state)
	query = _apply_filters(f, query, store=store, **filters)
	users = list(ownership.users_of(store)) or ["__none__"]
	own = f.owner.isin(users)
	rows = query.select(
		f.file_url,
		Min(f.file_name).as_("file_name"),
		Max(f.file_size).as_("file_size"),
		Max(Case().when(own, f.th_media_tags).else_("")).as_("tags"),
		Max(Case().when(own, f.th_media_favorite).else_(0)).as_("favorite"),
		Max(Case().when(own, f.th_media_alt).else_("")).as_("alt"),
	).run(as_dict=True)

	format_counts: dict[str, int] = {}
	tag_counts: dict[str, int] = {}
	kind_counts = {"image": 0, "video": 0, "document": 0}
	used_urls = ownership.used_urls(store)
	used = 0
	favorite = 0
	missing_alt = 0
	bytes_total = 0
	for row in rows:
		name = row.get("file_name") or row.get("file_url") or ""
		ext = name.rsplit(".", 1)[-1].upper() if "." in name else "DOSYA"
		format_counts[ext] = format_counts.get(ext, 0) + 1
		lower_ext = ext.lower()
		kind = (
			"video"
			if lower_ext in VIDEO_EXTENSIONS
			else "document"
			if lower_ext in DOCUMENT_EXTENSIONS
			else "image"
		)
		kind_counts[kind] += 1
		bytes_total += int(row.get("file_size") or 0)
		favorite += int(bool(row.get("favorite")))
		missing_alt += int(kind == "image" and not str(row.get("alt") or "").strip())
		used += int(row["file_url"] in used_urls)
		for tag in set(filter(None, str(row.get("tags") or "").split(","))):
			tag_counts[tag] = tag_counts.get(tag, 0) + 1

	from tradehub_core.media import categories as category_service

	return {
		"counts": {
			"all": len(rows),
			**kind_counts,
			"used": used,
			"unused": len(rows) - used,
			"shared": 0,
			"favorite": favorite,
			"missingAlt": missing_alt,
			"bytes": bytes_total,
		},
		"formats": [
			{"ext": ext, "count": count}
			for ext, count in sorted(format_counts.items(), key=lambda item: (-item[1], item[0]))
		],
		"tags": [
			{"tag": tag, "count": count}
			for tag, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))
		],
		"categories": category_service.category_facets(
			[row["file_url"] for row in rows], store
		),
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
	query = _apply_filters(
		f,
		query,
		search=search,
		state="optimized",
		only_optimizable=False,
		min_bytes=min_bytes,
	)
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
	query = _apply_filters(
		f,
		query,
		search=search,
		state="pending",
		only_optimizable=bool(only_optimizable),
		min_bytes=min_bytes,
	)
	q = query.select(Min(f.name).as_("name")).orderby("file_size", order=frappe.qb.desc)
	if limit:
		q = q.limit(int(limit))
	return [r["name"] for r in q.run(as_dict=True)]


# ─────────────────────────────────────────────────────────────────────────────
# T-042 — içerik SHA-256'sıyla tekilleştirme araması (yükleme ön kontrolü)
# ─────────────────────────────────────────────────────────────────────────────

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

#: `/files/` (7) + shard (2) + `/` (1) + sha256[:32] (32) = 42 karakter.
_HASHED_PREFIX_LEN: int = 42


def find_by_sha256(sha256: str, store: str) -> dict | None:
	"""İçeriğin TAM SHA-256'sıyla mağazanın kütüphanesinde dosya ara.

	Eşleşme İÇERİK-ADRESLİ ADDAN yapılır: yeni yüklemelerin adresi
	`/files/{sha[:2]}/{sha[:32]}.{uzantı}` (`media/naming.py`, TUR-141/130) ve
	istemcinin hesapladığı tam hash'ten bu adres birebir türetilebilir.

	NEDEN `content_hash` KOLONUNDAN DEĞİL (ölçüldü, 2026-08-20, canlı dev DB):
	`tabFile.content_hash` 5.047 kayıtta MD5 taşıyor — örnek `430483d1…` ≠
	`sha256[:32]`; aynı DB'de `/files/03/039731d0….mp4` adresinin gövdesi ise
	içeriğin sha256'sının ilk 32 hanesiyle BİREBİR doğrulandı. SHA-256 başka
	hiçbir kolonda saklanmıyor (`Media Asset.content_sha256` da 32 haneli
	kısaltmadır ve yalnız pipeline kapsamındaki dosyalarda dolar).

	ÜÇ KATMAN (rapor 75 kusur #2 + rapor 64 EK-2 / W7 sonrası):

	  1. İçerik-adresli dosya adı (`/files/{sha[:2]}/{sha[:32]}.…`) — SAKLANAN
	     baytları elinde tutan istemciyi yakalar (dönüşmeden saklanan türler).
	  2. `Media Version.source_hash` → `Media Asset` → kaynak `File` — boru
	     hattının İŞLEDİĞİ dosyaları, adı içerik-adresli OLMASA bile yakalar
	     (canlı ölçüm: işlenmiş 9 dosyanın 9'unun adı legacy düzende — katman 1
	     onları asla bulamazdı).
	  3. `Media Asset.original_sha256` → kaynak `File` — yükleme anında
	     DÖNÜŞTÜRÜLEN görsellerde (PNG/JPEG→WebP, `api/seller_media._kaydet`)
	     istemcinin ORİJİNAL dosyadan hesapladığı sha256. İlk iki katman bu
	     içeriklerde yapısal olarak kördü: saklanan ad da `source_hash` da
	     dönüştürülmüş baytların hash'ini taşır (canlıda 3/3 doğrulanmıştı).
	     Hash'i dönüşümden önce `files.record_original_hash` yazar.

	BİLİNÇLİ SINIRLAR (eksik uyarı kabul, yanlış pozitif edilmez):
	  * Boru hattının işlemediği ve içerik-adresli adlanmamış eski dosyalar
	    (ölçüm: 5.047 kaydın 4.961'i) hiçbir katmanda görünmez — backfill ayrı iş.
	  * Katman 3 yalnız W7 SONRASI yüklemeleri kapsar: daha önce dönüştürülmüş
	    içeriklerin orijinal baytları sunucuya bir daha hiç gelmedi, hash'leri
	    geriye dönük üretilemez.

	Kiracı sınırı: katman 1'de `ownership.scope` (envanter listesinin
	KENDİSİYLE aynı süzgeç), katman 2 ve 3'te `Media Asset.owner_seller = store`
	SQL'in içinde. Mağaza parametresi çağıranın oturumundan gelmek zorundadır
	(bkz. `api/seller_media.find_in_my_library`).
	"""
	h = (sha256 or "").strip().lower()
	if not _SHA256_HEX.match(h) or not store:
		return None
	return (
		_find_by_hashed_name(h, store)
		or _find_by_pipeline_source_hash(h, store)
		or _find_by_original_hash(h, store)
	)


def _dosya_cevabi(satir: dict) -> dict:
	return {
		"file_url": satir["file_url"],
		"file_name": satir["file_name"] or "",
		"uploaded_at": str(satir["uploaded_at"] or ""),
	}


def _find_by_hashed_name(h: str, store: str) -> dict | None:
	"""Katman 1 — içerik-adresli dosya adından eşleşme."""
	prefix = f"/files/{h[:2]}/{h[:32]}"
	f, query = _base_query()
	query = ownership.scope(query, f, store)
	rows = (
		query
		# Çöpteki dosyanın public adresi ölüdür (blob `private/media_trash/`
		# altına taşınır — `states.py`); "kütüphanenizde var" demek yanlış olur.
		.where(f.th_trashed_at.isnull())
		.where(Coalesce(f.th_media_state, "") != states.STATE_TRASHED)
		# LIKE değil LEFT: utf8mb4'te LIKE, 4 baytlık karakter içeren satırları
		# sessizce düşürüyor (modül başındaki ölçüm). Uzantısız kenar durum için
		# tam eşitlik de denenir; nokta şartı 33+ haneli gövdelerin yanlış
		# pozitifini keser.
		.where((Left(f.file_url, _HASHED_PREFIX_LEN + 1) == prefix + ".") | (f.file_url == prefix))
		.select(
			f.file_url,
			Max(f.file_name).as_("file_name"),
			Min(f.creation).as_("uploaded_at"),
		)
		.limit(1)
		.run(as_dict=True)
	)
	return _dosya_cevabi(rows[0]) if rows else None


def _find_by_pipeline_source_hash(h: str, store: str) -> dict | None:
	"""Katman 2 — boru hattının sürüm kaydından eşleşme (rapor 75 kusur #2).

	`Media Version.source_hash` kaynak dosyanın TAM 64 haneli sha256'sını taşır
	(`pipeline_bridge._ensure_version`); dosyanın ADI legacy düzende olsa bile.
	Zincir: source_hash → Media Version → Media Asset → kaynak File.

	KİRACI KEMERİ SORGUNUN İÇİNDE: `Media Asset.owner_seller = store`. Sonradan
	süzmek değil — başka satıcının varlığı sonuç kümesine hiç girmez; eşleşme
	yoksa cevap "yok"tur, varlığı sezdirilmez. Sahipsiz varlıklar
	(`owner_seller` boş — platform/yönetim yüklemeleri) hiçbir mağazaya dönmez.

	Kaynak dosya ayrıca envanterin HİJYEN kemerlerinden geçer (`_base_query`:
	public, klasörsüz, KVKK doctype eki değil, HASSAS-İKİZ maskesi) + çöp
	dışlaması — envanterin gizlediği bir dosyayı bu uç "kütüphanenizde var"
	diye geri sızdıramaz (canlı örnek: `7m7n6rs4d4`, hassas-ikiz içerik).
	"""
	v = DocType("Media Version")
	a = DocType("Media Asset")
	# Aynı içerik birden çok slotta işlenmiş olabilir (slot başına ayrı Asset);
	# hijyen kemerine takılan aday olabileceği için tek satırla yetinilmez.
	kaynaklar = (
		frappe.qb.from_(v)
		.join(a)
		.on(a.name == v.asset)
		.select(a.source_file)
		.where(v.source_hash == h)
		.where(a.owner_seller == store)
		.where(a.source_file.isnotnull())
		.limit(5)
		.run()
	)
	for (source_file,) in kaynaklar:
		cevap = _kaynak_dosya_cevabi(source_file)
		if cevap:
			return cevap
	return None


def _kaynak_dosya_cevabi(source_file: str | None) -> dict | None:
	"""Kaynak `File` docname'ini HİJYEN kemerlerinden geçirip cevaba çevirir.

	Katman 2 ve 3'ün ORTAK son adımı: `_base_query` (public, klasörsüz, KVKK
	eki değil, HASSAS-İKİZ maskesi) + çöp dışlaması. Envanterin gizlediği bir
	dosyayı hiçbir katman "kütüphanenizde var" diye geri sızdıramaz.
	"""
	if not source_file:
		return None
	url = frappe.db.get_value("File", source_file, "file_url")
	if not url:
		return None  # kaynak File silinmiş — türev/varlık kaydı kalmış olabilir
	f, query = _base_query()
	rows = (
		query.where(f.file_url == url)
		.where(f.th_trashed_at.isnull())
		.where(Coalesce(f.th_media_state, "") != states.STATE_TRASHED)
		.select(
			f.file_url,
			Max(f.file_name).as_("file_name"),
			Min(f.creation).as_("uploaded_at"),
		)
		.limit(1)
		.run(as_dict=True)
	)
	return _dosya_cevabi(rows[0]) if rows else None


def _find_by_original_hash(h: str, store: str) -> dict | None:
	"""Katman 3 — yükleme anında saklanan ORİJİNAL hash'ten eşleşme (rapor 64
	EK-2 / W7).

	`Media Asset.original_sha256` yalnız `_kaydet`in DÖNÜŞTÜRDÜĞÜ yüklemelerde
	dolar (`files.record_original_hash` — kolonun ve kaydın gerekçesi orada).
	Zincir: original_sha256 → Media Asset → kaynak File.

	KİRACI KEMERİ SORGUNUN İÇİNDE (`owner_seller = store`) — katman 2 ile aynı
	desen, aynı gerekçe: başka satıcının varlığı sonuç kümesine hiç girmez,
	eşleşme yoksa cevap "yok"tur, varlığı sezdirilmez. Sahipsiz varlıklar
	(`owner_seller` boş) hiçbir mağazaya dönmez. Kaynak dosya ayrıca
	`_kaynak_dosya_cevabi`nin hijyen kemerlerinden geçer.

	Kolon patch'i (`v15_9_34_media_asset_original_sha256`) koşmamışsa katman
	sessizce yoktur — sorgu bilinmeyen kolonla patlamasın.
	"""
	if not frappe.db.has_column("Media Asset", "original_sha256"):
		return None
	a = DocType("Media Asset")
	# Aynı orijinal içerik birden çok slota yüklenmiş olabilir (slot başına
	# ayrı Asset — katman 2'deki gerekçenin aynısı); hijyen kemerine takılan
	# aday olabileceği için tek satırla yetinilmez.
	kaynaklar = (
		frappe.qb.from_(a)
		.select(a.source_file)
		.where(a.original_sha256 == h)
		.where(a.owner_seller == store)
		.where(a.source_file.isnotnull())
		.limit(5)
		.run()
	)
	for (source_file,) in kaynaklar:
		cevap = _kaynak_dosya_cevabi(source_file)
		if cevap:
			return cevap
	return None
