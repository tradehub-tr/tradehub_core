"""Satıcının kendi medya kütüphanesi — HTTP yüzeyi.

`media_admin` ile aynı iş mantığını kullanır ama iki temel farkla:

  1. **Yetki rol değil sahiplik.** Yönetim uçları rol istiyor ("System Manager"
     misin?). Burada rol yetmez: giriş yapmış her satıcı kendi kütüphanesini
     görür, ama YALNIZ kendisininkini. Her çağrı oturumdan mağazayı çözer ve
     sorguya o mağazayı geçirir. Mağaza parametre olarak DIŞARIDAN alınmaz —
     alınsaydı satıcı başkasının mağaza kodunu yazıp verisini görebilirdi.

  2. **Silme yıkıcı değil, bırakmadır.** Aynı dosya birden çok mağazaya ait
     olabiliyor; satıcının silmesi diğerinin ürününü kırmamalı. Ayrıntı
     `media/seller_media.py` başlığında.

Bu dosyada iş mantığı YOKTUR: yetki, parametre doğrulama, çağırma. Aynı kural
`media_admin` için de geçerli.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re

import frappe
from frappe.utils import cint

from tradehub_core.api._pagination import normalize_pagination
from tradehub_core.media import (
	audit,
	browse,
	chunked,
	engine,
	files,
	inventory,
	metadata,
	ownership,
	pipeline_bridge,
	seller_backup,
	seller_backup_export,
	timefmt,
	transcode,
	upload_policy,
	usage,
)
from tradehub_core.media import seller_media as islem

# Tek istekte işlenebilecek azami dosya — kazara "hepsini" tetiklemeye karşı.
MAX_BATCH: int = 200
MAX_REPROCESS_BATCH: int = 500


def _store() -> str:
	"""Oturumdaki satıcının mağazası.

	Reddi denetime yazar: mağazası olmayan bir oturumun satıcı medya uçlarına
	gelmesi ya yanlış yapılandırma ya da deneme; ikisi de görünür olmalı.
	"""
	try:
		return ownership.current_store()
	except frappe.PermissionError:
		try:
			endpoint = (frappe.form_dict or {}).get("cmd")
		except Exception:
			endpoint = None
		audit.log_media_event(
			action=audit.ACTION_ACCESS_DENIED,
			allowed=False,
			reason="no_store",
			context={"endpoint": endpoint},
		)
		raise


def _urls(file_urls: str | list[str] | None) -> list[str]:
	liste = frappe.parse_json(file_urls) if isinstance(file_urls, str) else (file_urls or [])
	if len(liste) > MAX_BATCH:
		frappe.throw(frappe._("Tek seferde en çok {0} dosya işlenebilir.").format(MAX_BATCH))
	return [u for u in liste if u]


@frappe.whitelist()
def get_my_media(
	page: int = 1,
	page_size: int = 50,
	search: str = "",
	state: str = "",
	sort_by: str = "date",
	sort_dir: str = "desc",
	usage_state: str = "",
) -> dict:
	"""Satıcının kendi dosyaları — sayfalı liste.

	`state`: "" (aktif) | "trashed" (bıraktıkları) | "optimized" | "pending"
	`usage_state`: kendi kapsamındaki kullanım kararı
	"""
	store = _store()
	sonuc = inventory.list_files(
		page=page,
		page_size=page_size,
		search=search,
		state=state,
		sort_by=sort_by,
		sort_dir=sort_dir,
		usage_state=usage_state,
		store=store,
	)

	# Üstveri tek sorguda ekleniyor. Satır başına ayrı çağrı, 200 satırlık bir
	# sayfada 200 gidiş dönüş demekti.
	ustveri = metadata.read_many([i["file_url"] for i in sonuc["items"]], store)
	zengin = _lqip_by_url([i["file_url"] for i in sonuc["items"]], store)
	for i in sonuc["items"]:
		i.update(ustveri.get(i["file_url"]) or {})
		i.update(zengin.get(i["file_url"]) or {})
	return sonuc


def _lqip_by_url(file_urls: list[str], store: str) -> dict[str, dict]:
	"""T-065 FE beslemesi: adres → `{lqip_data_uri, dominant_color}`. 2 sorgu.

	File↔Asset bağı docname üzerinden ve aynı adreste MÜKERRER File satırları
	var (rapor 66 §9) — köprü bu yüzden `file_url` join'iyle kurulur; docname
	eşlemesi panelde yazı-tura görürdü. Kiracı sınırı: yalnız BU MAĞAZANIN
	varlıkları (`owner_seller = store`) — satır listesi zaten mağaza-scoped
	ama varlık katmanında ikinci kemer ucuz ve `_owns_listing`'deki ders
	burada da geçerli.
	"""
	adresler = sorted({u for u in (file_urls or []) if u})
	if not adresler or not store:
		return {}
	# frappe.get_all BİLİNÇLİ: girdiler mağazanın kendi liste sayfasından,
	# çıktı yalnız adres→görsel-özeti; owner_seller süzgeci kiracı kemeri.
	varliklar = frappe.get_all(
		"Media Asset",
		filters={"owner_seller": store, "state": "ready"},
		or_filters=[],
		fields=["name", "source_file"],
	)
	if not varliklar:
		return {}
	dosya_url = {
		f["name"]: f["file_url"]
		for f in frappe.get_all(
			"File",
			filters={"name": ["in", [v["source_file"] for v in varliklar]]},
			fields=["name", "file_url"],
		)
		if f.get("file_url") in set(adresler)
	}
	secili = {v["name"]: dosya_url[v["source_file"]] for v in varliklar if v["source_file"] in dosya_url}
	if not secili:
		return {}
	from tradehub_core.tradehub_core.doctype.media_version.media_version import (
		version_enrichment_for_assets,
	)

	zengin = version_enrichment_for_assets(sorted(secili))
	cikti: dict[str, dict] = {}
	for varlik_adi, url in secili.items():
		v = zengin.get(varlik_adi) or {}
		if url not in cikti and (v.get("lqip_data_uri") or v.get("dominant_color")):
			cikti[url] = {
				"lqip_data_uri": v.get("lqip_data_uri") or "",
				"dominant_color": v.get("dominant_color") or "",
			}
	return cikti


def _owns_listing(store: str, listing: str) -> bool:
	"""İlan gerçekten bu mağazanın mı.

	`listing` istemciden geliyor ve klasör yolunun bir parçası. Ağaç zaten
	mağazaya göre kuruluyor, ama doğrulama BURADA da yapılıyor: tek katmanlı
	izolasyon, o katmanı bir gün kimse fark etmeden gevşetince sessizce
	sızıntıya döner. `Payment Transaction` açığı tam olarak böyle oluşmuştu.
	"""
	if not store or not listing:
		return False
	return frappe.db.get_value("Listing", listing, "seller_profile") == store


@frappe.whitelist()
def browse_my_media(
	scope: str = "",
	category: str = "",
	listing: str = "",
	page: int = 1,
	page_size: int = 50,
	search: str = "",
) -> dict:
	"""Satıcının KENDİ medyası — sanal klasör ağacında bir seviye.

	Parametre derinliği seviyeyi belirler:

	    (yok)                              kök klasörler
	    scope=public                       kategori klasörleri
	    scope=public&category=X            o kategorideki ürün klasörleri
	    scope=public&category=X&listing=L  o ürünün dosyaları
	    scope=public&category=__unused__   hiçbir üründe durmayan yüklemeler
	    scope=private                      kendi özel dosyaları
	    scope=chat                         kendi sohbet ekleri

	`store` parametresi YOKTUR ve EKLENMEYECEK. Mağaza her çağrıda oturumdan
	`_store()` ile türetilir; izolasyonun tek ve mutlak dayanağı bu. İstemciden
	gelen bir mağaza değeri kabul edilseydi satıcı başkasının mağaza kodunu
	yazıp bütün kütüphanesini okurdu.

	Bulunamayan kategori/ürün için hata değil BOŞ sonuç dönülür: "yok" ile
	"senin değil" ayrımı, başka mağazanın kategori ve ürün kimliklerini deneme
	yoluyla keşfetmeye kapı açardı.
	"""
	store = _store()
	scope = (scope or "").strip()
	category = (category or "").strip()
	listing = (listing or "").strip()
	search = (search or "").strip()
	page, page_size, _start = normalize_pagination(
		page, page_size, default_page_size=50, max_page_size=browse.MAX_PAGE_SIZE
	)

	if not scope:
		return browse.seller_root(store)
	if scope == "chat":
		# Sohbet künyesi zaten mağazaya göre süzülüyor (`Chat Attachment.seller`).
		return browse.files(
			scope="chat", store=store, page=page, page_size=page_size, search=search
		)
	if scope == "private":
		return browse.seller_private_files(
			store, page=page, page_size=page_size, search=search
		)
	if scope != "public":
		frappe.throw(frappe._("Geçersiz kapsam: {0}").format(scope))

	if not category:
		return browse.seller_public_categories(store)
	if listing and not _owns_listing(store, listing):
		return {"items": [], "total": 0}
	if listing or category == browse.UNUSED:
		return browse.seller_public_files(
			store,
			category=category,
			listing=listing,
			page=page,
			page_size=page_size,
			search=search,
		)
	return browse.seller_listings(store, category)


@frappe.whitelist()
def get_my_usage(file_url: str) -> dict:
	"""Bu dosyayı KENDİ hangi ürünlerimde kullanıyorum.

	Başka mağazanın kullanımı yanıtta hiç geçmez — ne ürün adı, ne sayı, ne
	mağaza. Satıcının bilmesi gereken tek şey kendi vitrininin ne olacağı.
	"""
	store = _store()
	ownership.assert_owns(store, file_url)
	return usage.resolve(file_url, store=store)


_HISTORY_LIMIT: int = 50


def _safe_audit_history(rows: list[dict]) -> list[dict]:
	"""Denetim satırını satıcının görebileceği küçük sözleşmeye indir.

	Authorization Decision Log satırında IP, ham bağlam ve aktör e-postası da
	bulunur. Bunlar platform içi ayrıntılardır; dosyanın sahibine işlem
	zamanını/sonucunu göstermek için gerekli değildir. Geçmiş ekranı tam olay
	dizisini gösterir, fakat bu hassas alanları taşımaz.
	"""
	izinli = ("name", "timestamp", "action", "decision", "severity", "actor_name")
	return [{alan: satir.get(alan) for alan in izinli if satir.get(alan) not in (None, "")} for satir in rows]


@frappe.whitelist(methods=["GET"])
def get_my_media_history(file_url: str) -> dict:
	"""Bir dosyanın sürüm, işleme ve denetim geçmişi — yalnız sahibi için.

	Sahiplik önce ``File`` adresinde, sonra ``Media Asset.owner_seller``
	üzerinden ikinci kez zorlanır. Aynı URL'ye bağlı birden fazla ``File`` ve
	asset olabilir; hiçbir sorgu yalnız URL'ye güvenerek kiracı sınırını aşmaz.
	İşlerin ``error_trace`` alanı ve denetimin IP/ham bağlamı özellikle dışarı
	verilmez.
	"""
	store = _store()
	url = str(file_url or "").split("?", 1)[0].strip()
	if not url:
		frappe.throw(frappe._("Dosya adresi zorunlu."))
	ownership.assert_owns(store, url)

	file_names = frappe.get_all("File", filters={"file_url": url}, pluck="name")
	assets = (
		frappe.get_all(
			"Media Asset",
			filters={"owner_seller": store, "source_file": ["in", file_names]},
			fields=["name", "media_type", "state", "source_file", "creation"],
			order_by="creation desc",
			limit_page_length=0,
		)
		if file_names
		else []
	)
	asset_names = [row["name"] for row in assets]

	versions: list[dict] = []
	jobs: list[dict] = []
	version_total = 0
	job_total = 0
	if asset_names:
		asset_filter = {"asset": ["in", asset_names]}
		version_total = frappe.db.count("Media Version", asset_filter)
		job_total = frappe.db.count("Media Processing Job", asset_filter)
		versions = frappe.get_all(
			"Media Version",
			filters=asset_filter,
			fields=[
				"name",
				"asset",
				"version_hash",
				"is_active",
				"width",
				"height",
				"dpi",
				"colorspace",
				"classification",
				"engine_version",
				"created_at",
				"creation",
			],
			order_by="creation desc",
			limit_page_length=_HISTORY_LIMIT,
		)
		jobs = frappe.get_all(
			"Media Processing Job",
			filters=asset_filter,
			fields=[
				"name",
				"asset",
				"job_type",
				"queue",
				"status",
				"attempt",
				"started_at",
				"finished_at",
				"duration_ms",
				"error_code",
				"creation",
			],
			order_by="creation desc",
			limit_page_length=_HISTORY_LIMIT,
		)

	audit_result = audit.list_events(
		file_url=url,
		tenant=store,
		page=1,
		page_size=_HISTORY_LIMIT,
		sort_by="timestamp",
		sort_dir="desc",
	)
	timefmt.apply_all(assets)
	timefmt.apply_all(versions)
	timefmt.apply_all(jobs)
	return {
		"file_url": url,
		"assets": assets,
		"versions": versions,
		"jobs": jobs,
		"audit": _safe_audit_history(audit_result.get("items") or []),
		"totals": {
			"assets": len(assets),
			"versions": version_total,
			"jobs": job_total,
			"audit": int(audit_result.get("total") or 0),
		},
		"truncated": {
			"versions": version_total > _HISTORY_LIMIT,
			"jobs": job_total > _HISTORY_LIMIT,
			"audit": int(audit_result.get("total") or 0) > _HISTORY_LIMIT,
		},
	}


def _reprocess_urls(file_urls: str | list[str] | None) -> list[str]:
	"""Toplu yeniden işleme girdisi — sıralı, tekil ve en çok 500 URL."""
	try:
		raw = frappe.parse_json(file_urls) if isinstance(file_urls, str) else (file_urls or [])
	except Exception:
		frappe.throw(frappe._("Dosya listesi okunamadı."))
	if not isinstance(raw, list):
		frappe.throw(frappe._("Dosya listesi bir dizi olmalıdır."))
	urls = list(
		dict.fromkeys(str(url or "").split("?", 1)[0].strip() for url in raw if str(url or "").strip())
	)
	if len(urls) > MAX_REPROCESS_BATCH:
		frappe.throw(
			frappe._("Tek seferde en çok {0} medya yeniden işlenebilir.").format(
				MAX_REPROCESS_BATCH
			)
		)
	return urls


def _seller_reprocess_meta_key(token: str) -> str:
	return f"media:seller-reprocess:{token}:meta"


def _save_seller_reprocess_meta(token: str, meta: dict) -> None:
	frappe.cache().set_value(
		_seller_reprocess_meta_key(token),
		frappe.as_json(meta),
		expires_in_sec=pipeline_bridge.BULK_STATUS_SECONDS,
	)


def _read_seller_reprocess_meta(token: str, store: str) -> dict:
	raw = frappe.cache().get_value(_seller_reprocess_meta_key(str(token)), expires=True)
	if isinstance(raw, bytes):
		raw = raw.decode("utf-8", "replace")
	try:
		meta = frappe.parse_json(raw) if raw else {}
	except Exception:
		meta = {}
	# Token rastgele olsa da tek başına yetki değildir. Yanlış mağaza ile
	# bilinmeyen token aynı "yok" cevabına iner; işin varlığı sızmaz.
	if not isinstance(meta, dict) or meta.get("store") != store:
		frappe.throw(frappe._("Yeniden işleme işi bulunamadı."), frappe.DoesNotExistError)
	return meta


def _seller_reprocess_response(token: str, meta: dict) -> dict:
	status = pipeline_bridge.policy_reprocess_status(token)
	asset_to_url = meta.get("asset_to_url") or {}
	preflight = list(meta.get("preflight_failures") or [])
	worker_failures: list[dict] = []
	for row in status.get("failures") or []:
		url = asset_to_url.get(str(row.get("asset") or ""))
		if url:
			worker_failures.append(
				{
					"file_url": url,
					"error_code": "processing_failed",
					"error": frappe._("Yeniden işleme başarısız."),
				}
			)

	queued_total = int(status.get("total") or 0)
	processed = int(status.get("processed") or 0)
	worker_failed = int(status.get("failed") or 0)
	return {
		"token": token,
		"status": status.get("status") or "unknown",
		"requested": int(meta.get("requested") or 0),
		"queued": queued_total,
		"total": queued_total + len(preflight),
		"processed": processed + len(preflight),
		"succeeded": max(0, processed - worker_failed),
		"failed": worker_failed + len(preflight),
		"failures": preflight + worker_failures,
		"skipped": int(meta.get("skipped") or 0),
		"cancelled": bool(status.get("cancelled")),
	}


@frappe.whitelist(methods=["POST"])
def start_media_reprocess(file_urls: str | list[str] | None = None) -> dict:
	"""En çok 500 satıcı varlığını ayrı düşük-öncelikli işlere dağıt.

	URL'ler önce toplu sahiplik süzgecinden, sonra ``Media Asset.owner_seller``
	kemerinden geçer. Bir dosyanın başka mağazaya ait asset'i aynı kaynağı
	kullansa bile bu koşuma giremez.
	"""
	store = _store()
	urls = _reprocess_urls(file_urls)
	owned = ownership.owned_urls(store, urls)
	skipped = len(urls) - len(owned)

	files = (
		frappe.get_all(
			"File",
			filters={"file_url": ["in", sorted(owned)]},
			fields=["name", "file_url"],
			limit_page_length=0,
		)
		if owned
		else []
	)
	file_to_url = {str(row["name"]): str(row["file_url"]) for row in files}
	assets = (
		frappe.get_all(
			"Media Asset",
			filters={
				"owner_seller": store,
				"media_type": "image",
				"source_file": ["in", sorted(file_to_url)],
			},
			fields=["name", "source_file"],
			limit_page_length=0,
		)
		if file_to_url
		else []
	)
	asset_names = list(dict.fromkeys(str(row["name"]) for row in assets))
	if len(asset_names) > MAX_REPROCESS_BATCH:
		frappe.throw(
			frappe._("Seçim {0} varlıktan fazlasına bağlanıyor; seçimi daraltın.").format(
				MAX_REPROCESS_BATCH
			)
		)
	asset_to_url = {
		str(row["name"]): file_to_url.get(str(row.get("source_file") or ""), "")
		for row in assets
	}
	mapped_urls = {url for url in asset_to_url.values() if url}
	preflight_failures = [
		{
			"file_url": url,
			"error_code": "image_asset_missing",
			"error": frappe._("İşlenebilir görsel varlığı bulunamadı."),
		}
		for url in sorted(owned - mapped_urls)
	]

	queued = pipeline_bridge.enqueue_policy_reprocess(
		asset_names,
		limit=MAX_REPROCESS_BATCH,
		rate_per_minute=60,
	)
	token = str(queued["token"])
	meta = {
		"store": store,
		"requested": len(urls),
		"skipped": skipped,
		"preflight_failures": preflight_failures,
		"asset_to_url": asset_to_url,
	}
	_save_seller_reprocess_meta(token, meta)
	return _seller_reprocess_response(token, meta)


@frappe.whitelist(methods=["GET"])
def get_media_reprocess_status(token: str) -> dict:
	store = _store()
	meta = _read_seller_reprocess_meta(token, store)
	return _seller_reprocess_response(str(token), meta)


@frappe.whitelist(methods=["POST"])
def cancel_media_reprocess(token: str) -> dict:
	store = _store()
	meta = _read_seller_reprocess_meta(token, store)
	pipeline_bridge.cancel_policy_reprocess(str(token))
	return _seller_reprocess_response(str(token), meta)


@frappe.whitelist()
def list_orphans(days_unused: int = 30, start: int = 0, page_length: int = 50) -> dict:
	"""ÖKSÜZ dosyalarım — hiçbir taranan kaynak alanda geçmeyen ve
	yüklenmesinin üzerinden en az `days_unused` gün geçmiş dosyalar (T-043).

	YALNIZ LİSTELER. Bu uçtan silme yapılamaz ve yapılmayacak: silme mevcut
	çöp akışının (`preview_release` → `archive_media` → `purge_media`) işi;
	görünürlük ile silme aynı uca konursa tarama listesindeki bir eksik
	doğrudan veri kaybına döner (bkz. rapor 57 — GC 3.821 dosyayı silecekti).

	Mağaza parametre DEĞİL, oturumdan çözülür (modül başlığındaki kural).
	Kullanım kararı `media/usage.py`'deki TEK kaynak listesinden gelir;
	yanıttaki `scan` alanı taramanın neyi GÖRMEDİĞİNİ de söyler ve ekran
	bunu göstermek zorundadır.
	"""
	store = _store()
	return usage.store_orphans(
		store,
		days_unused=cint(days_unused),
		start=cint(start),
		page_length=cint(page_length),
	)


@frappe.whitelist()
def preview_release(file_urls: str | list[str] | None = None) -> dict:
	"""Bırakmadan önce özet — onay ekranı uyarıyı buna göre kurar.

	Kullanımdaki dosya sayısı ayrı veriliyor ki ekran "3 görsel şu an
	ürünlerinizde kullanılıyor" diyebilsin. Uyarısız toplu silme, satıcının
	kendi vitrinini tek tıkla bozması demek.
	"""
	store = _store()
	urls = _urls(file_urls)
	sahip_olunan = [u for u in urls if ownership.owns(store, u)]
	kararlar = usage.verdicts_for(sahip_olunan, deep=True, store=store)

	sayim: dict[str, int] = {}
	for v in kararlar.values():
		k = v.get("verdict", "unknown")
		sayim[k] = sayim.get(k, 0) + 1

	return {
		"total": len(urls),
		"owned": len(sahip_olunan),
		"by_verdict": sayim,
		"in_use": sayim.get("in_use", 0),
	}


@frappe.whitelist()
def archive_media(file_urls: str | list[str] | None = None) -> dict:
	"""Seçili dosyaları ARŞİVLE — geri alınabilir.

	Diske dokunulmaz, hiçbir kayıt silinmez. Kalıcı silme ayrı uçta
	(`purge_media`) ve yalnız arşivdeki dosyaya uygulanıyor.

	Zorlama seçeneği YOK: kullanımdaki dosyayı arka taraf reddediyor ve bu
	hiçbir parametreyle aşılamıyor — ekrandaki kapalı düğme tek başına koruma
	sayılmaz, konsoldan istek atılabilir.

	Sahibi olmadığı dosya sessizce atlanmaz, `skipped` altında sayılır; ama
	hangi dosya olduğu dönülmez — sahibi olmadığı bir adresin varlığını
	doğrulamak keşif kapısı açar.
	"""
	return _toplu(file_urls, islem.archive, "archived")


@frappe.whitelist()
def unarchive_media(file_urls: str | list[str] | None = None) -> dict:
	"""Arşivden çıkar — dosya aktif listeye döner."""
	return _toplu(file_urls, islem.unarchive, "unarchived")


@frappe.whitelist()
def purge_media(file_urls: str | list[str] | None = None) -> dict:
	"""KALICI SİL — geri alınamaz.

	Satıcının payı tamamen kalkar. Dosya diskten yalnız SON sahip de
	sildiğinde silinir; o ana kadar diğer mağazalar için olduğu gibi durur.

	Yalnız arşivdeki dosyaya uygulanır; arka taraf değilse reddeder.
	"""
	return _toplu(file_urls, islem.purge, "purged")


def _toplu(file_urls, fn, sayac_adi: str) -> dict:
	"""Toplu işlem iskeleti — üç uç da aynı yetki ve hata davranışını paylaşır.

	Tek yerde durması önemli: sahiplik kontrolü ya da hata yutma davranışı
	uçlar arasında ayrışırsa biri diğerinden gevşek kalır.
	"""
	store = _store()
	urls = _urls(file_urls)

	basarili: list[dict] = []
	hatali: list[dict] = []
	atlanan = 0

	for url in urls:
		if not ownership.owns(store, url):
			atlanan += 1
			continue
		try:
			basarili.append(fn(url, store))
		except Exception as e:
			hatali.append({"file_url": url, "error": str(e)})

	return {
		sayac_adi: len(basarili),
		"failed": hatali,
		"skipped": atlanan,
		"details": basarili,
	}


@frappe.whitelist()
def get_my_summary() -> dict:
	"""Üst şerit — dosya adedi, gerçek depolama kullanımı, bırakılan adedi.

	`quota_bytes` yapılandırılmamışsa `null` döner ve ekran sınır göstermez.
	Uydurma bir sınır göstermek, satıcıya var olmayan bir kısıt olduğunu
	düşündürürdü (gerçek kota modeli TUR-139).
	"""
	store = _store()
	aktif = inventory.list_files(page=1, page_size=1, store=store)
	cop = inventory.list_files(page=1, page_size=1, state="trashed", store=store)
	depolama = files.storage_usage(store)
	return {
		"store": store,
		"active": aktif["total"],
		"trashed": cop["total"],
		"bytes": depolama["bytes"],
		"quota_bytes": depolama["quota_bytes"],
		"tags": metadata.all_tags(store),
	}


# Kabul edilen türler ve boyut sınırları artık `media.upload_policy` içinde —
# TEK yerde (TUR-123).
#
# Buradaki listeler bu ucun kuralıydı ve yalnız bu uçta geçerliydi; panelde
# yükleme yapan diğer 22 ekran Frappe'nin genel ucundan geçiyor ve hiçbirini
# tanımıyordu. Kural tek modüle taşındı, hem bu uç hem `File` kancası oradan
# soruyor. İki kopya tutmak, biri değişince sessizce ayrışan iki kural demekti.
#
# Adlar geriye dönük uyumluluk için duruyor; değer politikadan geliyor.
UPLOAD_EXTENSIONS: frozenset[str] = frozenset(
	e
	for e, t in upload_policy.EXTENSIONS.items()
	if t in upload_policy.MEDIA_KINDS or e in upload_policy.MEDIA_EXTRA_EXTENSIONS
)
MAX_UPLOAD_BYTES: int = upload_policy.MAX_BYTES[upload_policy.KIND_IMAGE]

# Sunucu garanti-WebP (TUR-128) yalnız `engine.to_webp`'in açabildiği raster
# biçimlere uygulanır. Politikanın izin listesinden DAR: `.webp` (zaten hedef
# biçim, çift sıkıştırma yok) ve `.gif` kasıtlı DIŞARIDA — `engine.optimize` de
# animasyonlu GIF'i atlıyor (`OptimizeResult(reason="animated")`), aynı davranış
# burada da korunuyor; tek kare WebP'ye çevirmek animasyonu kırar.
IMAGE_TO_WEBP_EXTENSIONS: frozenset[str] = frozenset(
	{".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".avif", ".heic"}
)


@frappe.whitelist()
def upload_media(
	file_name: str = "",
	content: str = "",
	slot: str = "",
	client_report: str | dict | None = None,
) -> dict:
	"""Satıcı kütüphanesine dosya yükle.

	Frappe'nin genel yükleme ucu yerine bu uç kullanılıyor, çünkü orada bu
	kütüphanenin tür ve boyut kuralları yok. İçerik base64 gelir; bu kurulumda
	çok parçalı gönderim oturum katmanında CSRF uyuşmazlığı üretiyor.

	`slot` (W7 — rapor 78 W5-2): yüklemenin hangi slot politikasına tabi olduğu
	(`product.image` gibi). Verilirse slot kuralları SUNUCUDA uygulanır
	(`upload_policy.check_slot` → `pipeline/policy/engine.py`); istemcideki ön
	kontrol aynı politikanın kopyası değil ÖNİZLEMESİDİR ve atlatılabilir.
	Verilmezse (genel kütüphane yüklemesi) bugünkü davranış korunur.
	"""
	store = _store()

	if not content:
		upload_policy.reddet(upload_policy.CONTENT_EMPTY, frappe._("Dosya içeriği boş."))
	ham = content.split(",", 1)[-1] if content.startswith("data:") else content
	try:
		icerik = base64.b64decode(ham, validate=True)
	except Exception:
		upload_policy.reddet(
			upload_policy.CONTENT_UNREADABLE, frappe._("Dosya içeriği okunamadı.")
		)

	return _kaydet(
		file_name,
		icerik,
		store,
		via="seller_library",
		slot=slot,
		client_report=client_report,
	)


def _client_telemetry(raw: str | dict | None) -> dict:
	"""İstemci ölçümünü yalnız telemetriye uygun küçük bir kümeye indir.

	Bu veri politika kararına HİÇ GİRMEZ. Boyut/tür/geometri sunucuda yeniden
	ölçülür; istemci raporuna güvenmek kapıyı bir JSON alanıyla atlatmak olurdu.
	"""
	try:
		veri = frappe.parse_json(raw) if isinstance(raw, str) else (raw or {})
	except Exception:
		return {}
	if not isinstance(veri, dict):
		return {}
	izinli = {
		"width",
		"height",
		"duration_s",
		"mime",
		"device_class",
		"connection",
		"compression",
		"client_sha256",
	}
	cikti: dict = {}
	for anahtar in izinli:
		deger = veri.get(anahtar)
		if isinstance(deger, (int, float, bool)):
			cikti[anahtar] = deger
		elif isinstance(deger, str):
			cikti[anahtar] = deger[:160]
	return cikti


def _kaydet(
	file_name: str,
	icerik: bytes,
	store: str,
	*,
	via: str,
	slot: str = "",
	client_report: str | dict | None = None,
) -> dict:
	"""Politikadan geçir, kaydı aç, denetime yaz.

	Tek parça ve parçalı yükleme aynı kuyruğa buradan giriyor. İki ayrı yerde
	kayıt açmak, ikinci kapıda denetim ya da sahiplik adımının unutulması
	demekti — yeni kapı açmanın klasik bedeli. WebP dönüşümü ve video transcode
	de bu yüzden burada: parçalı yükleme aynı garantileri kendiliğinden alır.
	"""
	karar = upload_policy.check(file_name, content=icerik, media_endpoint=True)

	# W7 — slot politikası kapısı (rapor 78 W5-2). Genel denetimden SONRA,
	# dönüşümden ÖNCE ve ORİJİNAL içerik üstünde: satıcının yüklediği dosya
	# neyse politika onu ölçer. Slot boşsa hiçbir şey yapmaz (eski davranış).
	# Bu uca gelen herkes oturumdan mağazaya çözülmüş bir satıcıdır (`_store`).
	upload_policy.check_slot(slot, karar.file_name, icerik, role="seller")

	video_mi = karar.kind == upload_policy.KIND_VIDEO

	# Sunucu garanti-WebP (TUR-128): Safari/iOS/Capacitor `canvas.toBlob(
	# 'image/webp')` desteklemiyor, client bu ortamlarda JPEG/PNG fallback'i
	# gönderir. `.webp` uzantısıyla gelen içerik zaten WebP'yse dokunulmaz —
	# çift sıkıştırma yok. Politika denetimi ORİJİNAL içerik üstünde yapıldı;
	# dönüşüm ancak ondan sonra.
	#
	# W7 (rapor 64 EK-2): dönüşüm istemcinin elindeki baytları YOK EDİYOR —
	# orijinalin sha256'sı dönüşümden ÖNCE hesaplanır ve kayıt açıldıktan sonra
	# `files.record_original_hash` ile saklanır; tekilleştirme araması
	# (`inventory.find_by_sha256` katman 3) aynı dosyanın ikinci yüklemesini
	# ancak böyle yakalayabilir.
	orijinal_sha256: str | None = None
	if upload_policy.extension_of(karar.file_name) in IMAGE_TO_WEBP_EXTENSIONS:
		try:
			donusen = engine.to_webp(icerik)
			if donusen != icerik:
				orijinal_sha256 = hashlib.sha256(icerik).hexdigest()
			icerik = donusen
			karar.file_name = os.path.splitext(karar.file_name)[0] + ".webp"
		except Exception as exc:
			# `to_webp` Pillow'un açamadığı bir biçimle (ör. bazı HEIC varyantları)
			# karşılaşırsa orijinal içerikle devam edilir — yükleme reddedilmez,
			# yalnız Safari-fallback tamamlanmamış olur. Orijinal baytlar bu
			# durumda OLDUĞU GİBİ saklandığı için hash kaydına gerek yok:
			# içerik-adresli ad (katman 1) onları zaten bulur.
			frappe.log_error(
				title="upload_media to_webp başarısız", message=f"{karar.file_name}: {exc}"
			)

	doc = frappe.get_doc(
		{"doctype": "File", "file_name": karar.file_name, "is_private": 0, "content": icerik}
	)
	# `reject_unsafe_files` kancası burada da çalışır — politika onun yerine
	# geçmiyor, üstüne biniyor.
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	if orijinal_sha256:
		try:
			files.record_original_hash(doc, store, orijinal_sha256, slot=slot)
		except Exception:
			# Best-effort: hash kaydı düşerse yükleme DÜŞMEZ — dedup uyarısı
			# eksik kalır, satıcının dosyası kalmaz. Sebep görünür olmalı.
			frappe.log_error(
				title="upload_media orijinal hash kaydedilemedi",
				message=f"{doc.file_url}\n\n{frappe.get_traceback()}",
			)

	telemetri = _client_telemetry(client_report)
	audit.log_media_event(
		action=audit.ACTION_UPLOAD,
		file_url=doc.file_url,
		tenant=store,
		context={
			"bytes": len(icerik),
			"via": via,
			"kind": karar.kind,
			# Slot beyanı denetime yazılır: kapının sahada hangi slotlarla
			# çağrıldığı ancak ölçülerek bilinir (uyarı izleriyle aynı gerekçe).
			**({"slot": slot} if slot else {}),
			# Zararsız tür uyuşmazlığı reddedilmiyor ama iz bırakıyor: sahada
			# ne kadar sık olduğunu ancak ölçerek bilebiliriz.
			**({"warnings": karar.warnings} if karar.warnings else {}),
			# İstemcinin raporu yalnız gözlem içindir; yukarıdaki iki sunucu kapısının
			# hiçbirine girmedi. Alan adı bunu denetimde de açık tutar.
			**({"client_telemetry_untrusted": telemetri} if telemetri else {}),
		},
	)

	if video_mi:
		# Video normalize'i dakikalar sürebilir — istek içinde SENKRON
		# çalıştırılmaz (checklists.md §2 kural 9). `enqueue_transcode` durumu
		# hemen `processing` yapıp gerçek işi `long` kuyruğa devreder.
		transcode.enqueue_transcode(doc.file_url)

	return {
		"file_url": doc.file_url,
		"file_name": doc.file_name,
		"bytes": doc.file_size,
		# Panel yükleme anında rozet gösterebilsin diye durum dönüşe ekleniyor.
		# `enqueue_transcode` durumu doc'a değil DB'ye yazdı — taze okunmalı;
		# video değilse alan hiç yazılmadı, None döner.
		"video_status": (
			frappe.db.get_value("File", doc.name, "th_media_video_status") if video_mi else None
		),
	}


@frappe.whitelist()
def upload_limits() -> dict:
	"""Sunucunun uyguladığı sınırlar — istemci aynısını uygulasın diye.

	İstemci sınırları kendi içine YAZMIYOR, buradan alıyor. İki tarafa ayrı
	sabit koymak, biri değişince sessizce ayrışan iki kural demekti: kullanıcı
	ekranda kabul edilen dosyanın sunucuda reddedildiğini görürdü.
	"""
	_store()
	return upload_policy.limits()


def _request_idempotency_key(body_value: str = "") -> str:
	"""HTTP ``Idempotency-Key`` ile gövde yedeğini tek değere indir.

	Frappe form argümanlarını gövdeden bağladığı için eski taşıma katmanları
	anahtarı ``idempotency_key`` alanında gönderebilir. Yeni istemci gerçek HTTP
	başlığını da yollar. İkisi farklıysa sessizce birini seçmek retry zincirini
	iki ayrı kimliğe böler; açık makine koduyla reddedilir.
	"""
	try:
		baslik = str(frappe.get_request_header("Idempotency-Key") or "").strip()
	except Exception:
		baslik = ""
	govde = str(body_value or "").strip()
	if baslik and govde and baslik != govde:
		upload_policy.reddet(
			upload_policy.IDEMPOTENCY_CONFLICT,
			frappe._("Başlık ve gövdedeki Idempotency-Key değerleri eşleşmiyor."),
		)
	return chunked.normalize_idempotency_key(baslik or govde)


def _existing_upload_result(mevcut: dict, content_sha256: str, *, deduplicated: bool) -> dict:
	"""Envanter eşleşmesini normal upload yanıt şekline getir."""
	url = str((mevcut or {}).get("file_url") or "")
	satir = (
		frappe.db.get_value(
			"File",
			{"file_url": url},
			["file_name", "file_size", "th_media_video_status"],
			as_dict=True,
		)
		if url
		else None
	)
	return {
		"file_url": url,
		"file_name": str((satir or {}).get("file_name") or (mevcut or {}).get("file_name") or ""),
		"bytes": int((satir or {}).get("file_size") or 0),
		"video_status": (satir or {}).get("th_media_video_status"),
		"content_sha256": content_sha256,
		"deduplicated": bool(deduplicated),
		"idempotent_replay": False,
	}


@frappe.whitelist(methods=["POST"])
def upload_begin(
	file_name: str = "",
	total_bytes: int = 0,
	slot: str = "",
	content_sha256: str = "",
	idempotency_key: str = "",
) -> dict:
	"""Parçalı yükleme oturumu aç.

	Büyük dosya tek istekte gönderilemiyor: base64 içeriği %33 şişiriyor ve
	tamamı iki tarafın belleğinde duruyor. Ad ve boyut daha ilk adımda
	denetleniyor — 150 parçayı alıp sonunda "çok büyük" demek boşa iş olurdu.
	"""
	store = _store()
	tekrar_anahtari = _request_idempotency_key(idempotency_key)
	ilan_hash = chunked.normalize_content_sha256(content_sha256)

	# Sunucu önceki finalize'ı bitirdi ama HTTP yanıtı yolda kaybolduysa aynı
	# anahtarla yeni bir oturum açılmaz; önceki TAM yanıt geri verilir.
	if tekrar_anahtari:
		onceki = chunked.finalized_result(tekrar_anahtari, store)
		if onceki:
			return {
				"upload_id": "",
				"completed": True,
				"idempotent_replay": True,
				"idempotency_key": tekrar_anahtari,
				"result": dict(onceki, idempotent_replay=True),
			}

	boyut = int(total_bytes or 0)
	kota = files.storage_usage(store)
	limit = kota.get("quota_bytes")
	kalan = None if limit is None else max(0, int(limit) - int(kota.get("bytes") or 0))
	if kalan is not None and boyut > kalan:
		upload_policy.reddet(
			upload_policy.QUOTA_EXCEEDED,
			frappe._("Depolama kotanızda bu yükleme için yeterli alan yok."),
		)

	# İstemci hash gönderdiyse K1: aynı mağazada içerik zaten varsa tek bayt
	# kabul edilmez. Finalize aynı kontrolü GERÇEK baytların hashiyle yineler.
	if ilan_hash:
		mevcut = inventory.find_by_sha256(ilan_hash, store)
		if mevcut:
			sonuc = _existing_upload_result(mevcut, ilan_hash, deduplicated=True)
			if tekrar_anahtari:
				chunked.save_finalized_result(tekrar_anahtari, store, sonuc)
			return {
				"upload_id": "",
				"completed": True,
				"duplicate": True,
				"idempotent_replay": False,
				"idempotency_key": tekrar_anahtari,
				"quota_remaining": kalan,
				"result": sonuc,
			}

	sonuc = chunked.begin(
		file_name,
		boyut,
		store,
		slot=slot,
		content_sha256=ilan_hash,
		idempotency_key=tekrar_anahtari,
	)
	sonuc["quota_remaining"] = kalan
	return sonuc


@frappe.whitelist(methods=["POST"])
def upload_chunk(upload_id: str = "", index: int = 0, content: str = "") -> dict:
	"""Tek parçayı gönder. Parçalar sırasız gelebilir."""
	store = _store()
	if not content:
		upload_policy.reddet(upload_policy.CONTENT_EMPTY, frappe._("Parça boş."))
	ham = content.split(",", 1)[-1] if content.startswith("data:") else content
	try:
		veri = base64.b64decode(ham, validate=True)
	except Exception:
		upload_policy.reddet(upload_policy.CONTENT_UNREADABLE, frappe._("Parça okunamadı."))
	return chunked.put_chunk(upload_id, int(index or 0), veri, store)


@frappe.whitelist(methods=["POST"])
def upload_finish(
	upload_id: str = "",
	idempotency_key: str = "",
	client_report: str | dict | None = None,
) -> dict:
	"""Parçaları birleştir ve dosyayı kaydet.

	Politika birleşimden SONRA uygulanıyor: ilk parça geçerli bir görsel
	başlığı taşıyıp devamı bambaşka bir içerik olabilirdi.
	"""
	store = _store()
	verilen_anahtar = _request_idempotency_key(idempotency_key)
	if verilen_anahtar:
		onceki = chunked.finalized_result(verilen_anahtar, store)
		if onceki:
			return dict(onceki, idempotent_replay=True)

	meta = chunked.meta_of(upload_id, store)
	oturum_anahtari = str(meta.get("idempotency_key") or "")
	if verilen_anahtar and oturum_anahtari and verilen_anahtar != oturum_anahtari:
		upload_policy.reddet(
			upload_policy.IDEMPOTENCY_CONFLICT,
			frappe._("Idempotency-Key bu yükleme oturumuyla eşleşmiyor."),
		)
	tekrar_anahtari = verilen_anahtar or oturum_anahtari
	if tekrar_anahtari:
		onceki = chunked.finalized_result(tekrar_anahtari, store)
		if onceki:
			return dict(onceki, idempotent_replay=True)

	icerik = chunked.finish(upload_id, store)
	gercek_hash = hashlib.sha256(icerik).hexdigest()
	ilan_hash = str(meta.get("content_sha256") or "")
	if ilan_hash and ilan_hash != gercek_hash:
		upload_policy.reddet(
			upload_policy.CONTENT_HASH_MISMATCH,
			frappe._("Yüklenen içerik ilan edilen SHA-256 ile eşleşmiyor."),
		)

	# Aynı içerikli iki eşzamanlı finalize da tek kayıt üretmeli. Redis kilidi
	# mağaza + gerçek içerik hashi üstündedir; kilit içinde hem idempotency sonucu
	# hem envanter yeniden okunur (TOCTOU kapısı).
	kilit_adi = f"media:upload-finalize:{hashlib.sha256(store.encode()).hexdigest()[:16]}:{gercek_hash}"
	kilit = frappe.cache().lock(kilit_adi, timeout=300, blocking_timeout=60)
	with kilit:
		if tekrar_anahtari:
			onceki = chunked.finalized_result(tekrar_anahtari, store)
			if onceki:
				chunked.cleanup_session(upload_id)
				return dict(onceki, idempotent_replay=True)

		mevcut = inventory.find_by_sha256(gercek_hash, store)
		if mevcut:
			sonuc = _existing_upload_result(mevcut, gercek_hash, deduplicated=True)
		else:
			sonuc = _kaydet(
				meta["file_name"],
				icerik,
				store,
				via="seller_library_chunked",
				slot=str(meta.get("slot") or ""),
				client_report=client_report,
			)
			sonuc.update(
				{
					"content_sha256": gercek_hash,
					"deduplicated": False,
					"idempotent_replay": False,
				}
			)
		if tekrar_anahtari:
			sonuc["idempotency_key"] = tekrar_anahtari
			chunked.save_finalized_result(
				tekrar_anahtari, store, sonuc, upload_id=upload_id
			)

	# Yalnız kalıcı sonuç yazıldıktan sonra parçaları kaldır. Geçici DB/depo
	# hatasında oturumu anında silmek resumable sözleşmesini kırardı; günlük
	# scheduler altı saat sonra kalanları temizler.
	chunked.cleanup_session(upload_id)
	return sonuc


@frappe.whitelist(methods=["POST"])
def upload_abort(upload_id: str = "") -> dict:
	"""Yarıda bırakılan yüklemeyi temizle — iptal gerçekten iptal olsun."""
	store = _store()
	chunked.cleanup_session(upload_id, store)
	return {"upload_id": upload_id, "aborted": True}


@frappe.whitelist()
def upload_status(upload_id: str = "") -> dict:
	"""Oturumun durumu — kopan yükleme kaldığı yerden sürebilsin."""
	return chunked.meta_of(upload_id, _store())


@frappe.whitelist()
def update_media(file_url: str, patch: str | dict | None = None) -> dict:
	"""Başlık, alternatif metin, açıklama, etiket, favori güncelle.

	Yalnız beyaz listedeki alanlar yazılır; gövdeye başka bir alan konursa yok
	sayılır (bkz. `metadata.EDITABLE`).
	"""
	store = _store()
	veri = frappe.parse_json(patch) if isinstance(patch, str) else (patch or {})
	return metadata.write(file_url, store, veri)


@frappe.whitelist()
def toggle_favorite(file_url: str) -> dict:
	"""Favoriyi ters çevir. Favori mağaza bazında — paylaşılan dosyada
	her mağaza kendi işaretini taşır."""
	store = _store()
	mevcut = metadata.read(file_url, store)
	return metadata.write(file_url, store, {"favorite": not mevcut.get("favorite")})


@frappe.whitelist()
def add_tag(file_urls: str | list[str] | None = None, tag: str = "") -> dict:
	"""Seçili dosyalara etiket ekle."""
	store = _store()
	temiz = (tag or "").strip()
	if not temiz:
		frappe.throw(frappe._("Etiket boş olamaz."))

	n = 0
	for url in _urls(file_urls):
		if not ownership.owns(store, url):
			continue
		mevcut = metadata.read(url, store).get("tags", [])
		if temiz in mevcut:
			continue
		metadata.write(url, store, {"tags": [*mevcut, temiz]})
		n += 1
	return {"tagged": n}


@frappe.whitelist()
def get_dimensions(file_url: str) -> dict:
	"""Gerçek çözünürlük — ilk soruluşta diskten okunup saklanır."""
	store = _store()
	ownership.assert_owns(store, file_url)
	return metadata.ensure_dimensions(file_url, store)


@frappe.whitelist(methods=["POST"])
def retry_video(file_url: str) -> dict:
	"""Başarısız (dead-letter) video işlemesini yeniden başlat (TUR-296).

	Yalnız kendi dosyası: sahiplik doğrulanmadan kuyruk tetiklenemez —
	`file_url` tahmin edilebilir olsaydı bile başka mağazanın videosu buradan
	yeniden işletilemez. Durum kuralı (`failed` dışında ret) `transcode`
	modülünde; burada tekrar edilmiyor.
	"""
	store = _store()
	ownership.assert_owns(store, file_url)
	sonuc = transcode.retry_failed(file_url)
	audit.log_media_event(
		action=audit.ACTION_OPTIMIZE,
		file_url=file_url,
		tenant=store,
		context={"kind": "video_transcode", "manual_retry": True},
	)
	return sonuc


@frappe.whitelist()
def rename_media(file_url: str, new_name: str) -> dict:
	"""Görünen adı değiştir. Dosyanın YOLU değişmez — değişseydi onu gösteren
	her ürün, vitrin ve sipariş kaydı kırılırdı."""
	return files.rename(file_url, _store(), new_name)


@frappe.whitelist()
def duplicate_media(file_url: str) -> dict:
	"""Dosyanın gerçek bir kopyasını üret."""
	return files.duplicate(file_url, _store())


@frappe.whitelist()
def replace_media(file_url: str, content: str = "", file_name: str = "") -> dict:
	"""Dosyanın içeriğini değiştir — yolu ve tüm bağları korunur.

	İçerik base64 olarak JSON gövdesinde gelir, çok parçalı gönderim ile DEĞİL.
	Bu kurulumda çok parçalı istek Frappe'nin oturum katmanında yan etki
	yaratıp CSRF uyuşmazlığı üretiyor (aynı ders `api.js/uploadCertDocument`
	yorumunda kayıtlı).
	"""
	store = _store()
	if not content:
		frappe.throw(frappe._("Dosya gönderilmedi."))

	# `data:...;base64,` öneki varsa ayıkla.
	ham = content.split(",", 1)[-1] if content.startswith("data:") else content
	try:
		icerik = base64.b64decode(ham, validate=True)
	except Exception:
		frappe.throw(frappe._("Dosya içeriği okunamadı."))

	return files.replace(file_url, store, icerik, file_name)


# --- Yedekleme (TUR-131) ----------------------------------------------------
#
# Yönetimdeki `media_admin` yedek uçlarıyla AYNI şeyi yapmazlar: orası platform
# çapında çalışır (tüm dosyalar, tüm `File` satırları), burası yalnız oturumdaki
# mağazanın kapsamında. Mağaza dışarıdan parametre olarak ALINMAZ — alınsaydı
# satıcı başkasının mağaza kodunu yazıp yedeğine erişirdi.


@frappe.whitelist(methods=["POST"])
def create_backup(label: str = "") -> dict:
	"""Mağazanın medyasının anlık görüntüsünü al."""
	store = _store()
	return seller_backup.create(store, label=(label or "").strip()[:60])


@frappe.whitelist()
def list_backups() -> dict:
	"""Mağazanın yedekleri + disk kullanımı."""
	store = _store()
	return {"sets": seller_backup.list_sets(store), "usage": seller_backup.usage(store)}


@frappe.whitelist()
def verify_backup(set_id: str, deep: int = 0) -> dict:
	"""Yedek geri yüklenebilir mi — hiçbir şeye dokunmadan kontrol."""
	store = _store()
	return seller_backup.verify(store, set_id, deep=bool(int(deep or 0)))


@frappe.whitelist()
def plan_backup_restore(set_id: str) -> dict:
	"""Geri yükleme yapılsa ne olurdu — rapor, uygulama değil."""
	store = _store()
	return seller_backup.plan(store, set_id)


@frappe.whitelist(methods=["POST"])
def apply_backup_restore(
	set_id: str,
	with_files: int = 1,
	with_records: int = 1,
	overwrite: int = 0,
	only: str | list[str] | None = None,
) -> dict:
	"""Geri yüklemeyi uygula.

	`overwrite` VARSAYILAN OLARAK KAPALI: içeriği değişmiş dosyaya dokunulmaz.
	Açmak ayrı ve bilinçli bir seçim olmalı — dosya optimize edilmiş ya da
	yenisiyle değiştirilmiş olabilir.
	"""
	store = _store()
	yollar = frappe.parse_json(only) if isinstance(only, str) else (only or [])
	if yollar and len(yollar) > MAX_BATCH:
		frappe.throw(frappe._("Tek seferde en çok {0} dosya işlenebilir.").format(MAX_BATCH))
	return seller_backup.apply(
		store,
		set_id,
		files=bool(int(with_files or 0)),
		records=bool(int(with_records or 0)),
		overwrite=bool(int(overwrite or 0)),
		only=[y for y in yollar if y] or None,
	)


@frappe.whitelist(methods=["POST"])
def delete_backup(set_id: str) -> dict:
	"""Bir yedeği sil. Son yedek silinemez (kural `seller_backup`te)."""
	store = _store()
	return seller_backup.delete_set(store, set_id)


@frappe.whitelist(methods=["POST"])
def start_backup_export(set_id: str) -> dict:
	"""Yedeği indirilebilir pakete dönüştürmeyi başlat (arkada çalışır)."""
	store = _store()
	return seller_backup_export.start(store, set_id)


@frappe.whitelist()
def backup_export_status(set_id: str) -> dict:
	"""Paket hazır mı — ekran bunu yokluyor."""
	store = _store()
	return seller_backup_export.status(store, set_id)


@frappe.whitelist(methods=["POST"])
def discard_backup_export(set_id: str) -> dict:
	"""Paketi sunucudan kaldır. Yedeğin kendisine dokunulmaz."""
	store = _store()
	return seller_backup_export.discard(store, set_id)


@frappe.whitelist()
def download_backup_export(set_id: str):
	"""Paketi indir.

	Dosya belleğe ALINMIYOR: yüzlerce MB'lık bir paketi yanıt gövdesine koymak
	süreci şişirirdi. Frappe'nin özel dosya göndericisi parça parça akıtıyor.

	Yol kurma ve varlık kontrolü `seller_backup_export.package_path` içinde;
	mağaza oturumdan çözülüyor, istekten DEĞİL.
	"""
	from frappe.utils.response import send_private_file

	store = _store()
	tam = seller_backup_export.package_path(store, set_id)
	audit.log_media_event(
		action=audit.ACTION_EXPORT,
		tenant=store,
		sensitive=True,
		context={"set_id": set_id, "downloaded": True},
	)
	# Gönderici site'ın private kökünden itibaren göreli yol bekliyor.
	return send_private_file(os.path.relpath(tam, frappe.get_site_path("private")))


# --- Gerçek klasörler (T-094) ------------------------------------------------
#
# Buraya kadarki gezgin ağacı SANALDI (kategori/üründen türetilir, `browse`).
# Aşağısı satıcının KENDİ kurduğu ağaç: `Media Folder` + `Media Folder Item`.
#
# İzolasyon deseni dosyanın geri kalanıyla aynı: mağaza HER uçta oturumdan
# (`_store()`) çözülür, istemciden asla alınmaz; klasör kimliği istemciden
# gelir ve `_my_folder` ile mağazaya karşı doğrulanır. Başka mağazanın klasörü
# "yetkin yok" değil "bulunamadı" ile reddedilir — varlığını doğrulamak kimlik
# uzayını deneme yoluyla keşfe açar (`ownership.assert_owns` ile aynı ilke).


def _my_folder(folder: str, store: str) -> dict:
	"""Klasör bu mağazanın mı — değilse ya da yoksa 'bulunamadı'.

	Klasör uçlarının TAMAMI buradan geçer. Kontrol tek yerde: uçlar arasında
	ayrışırsa biri diğerinden gevşek kalır (`_toplu` ile aynı gerekçe).
	"""
	satir = frappe.db.get_value(
		"Media Folder", folder, ["name", "folder_name", "parent_folder", "store"], as_dict=True
	)
	if not satir or satir.store != store:
		frappe.throw(frappe._("Klasör bulunamadı."), frappe.DoesNotExistError)
	return satir


@frappe.whitelist()
def list_folders() -> dict:
	"""Mağazanın TÜM klasörleri (düz liste, `parent_folder` ile ağaç kurulur)
	+ klasör başına dosya sayısı.

	Sayılar tek GROUP BY sorgusuyla gelir; klasör başına ayrı COUNT, 50
	klasörlük bir kütüphanede 50 gidiş dönüş demekti.
	"""
	store = _store()
	klasorler = frappe.get_all(
		"Media Folder",
		filters={"store": store},
		fields=["name", "folder_name", "parent_folder"],
		order_by="folder_name asc",
		limit_page_length=0,
	)
	sayilar = {
		s.folder: s.n
		for s in frappe.get_all(
			"Media Folder Item",
			filters={"store": store},
			fields=["folder", "count(name) as n"],
			group_by="folder",
		)
	}
	for k in klasorler:
		k["file_count"] = sayilar.get(k["name"], 0)

	from tradehub_core.tradehub_core.doctype.media_folder.media_folder import MAX_DEPTH

	return {"folders": klasorler, "max_depth": MAX_DEPTH}


@frappe.whitelist(methods=["POST"])
def create_folder(folder_name: str = "", parent_folder: str = "") -> dict:
	"""Klasör aç. Ad/derinlik/benzersizlik kuralları DocType'ta
	(`media_folder.py`) — burada tekrar edilmez, ikinci kopya ayrışır."""
	store = _store()
	if parent_folder:
		_my_folder(parent_folder, store)
	doc = frappe.get_doc(
		{
			"doctype": "Media Folder",
			"folder_name": folder_name,
			"parent_folder": parent_folder or "",
			"store": store,
		}
	).insert(ignore_permissions=True)
	return {
		"name": doc.name,
		"folder_name": doc.folder_name,
		"parent_folder": doc.parent_folder or "",
	}


@frappe.whitelist(methods=["POST"])
def rename_folder(folder: str = "", new_name: str = "") -> dict:
	"""Klasörün adını değiştir. Kimlik (`name`) değişmez — değişseydi alt
	klasörlerin ve dosya bağlarının tuttuğu bağlar kırılırdı."""
	store = _store()
	_my_folder(folder, store)
	doc = frappe.get_doc("Media Folder", folder)
	doc.folder_name = new_name
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "folder_name": doc.folder_name}


@frappe.whitelist(methods=["POST"])
def delete_folder(folder: str = "") -> dict:
	"""Klasörü sil. DOLU klasör reddedilir (alt klasör ya da dosya varsa) —
	davranışın gerekçesi `media_folder.py:on_trash` docstring'inde."""
	store = _store()
	_my_folder(folder, store)
	# Ret `on_trash`'te; buradan silinen her yol aynı korumadan geçer.
	frappe.delete_doc("Media Folder", folder, ignore_permissions=True)
	return {"deleted": folder}


@frappe.whitelist(methods=["POST"])
def move_media(file_urls: str | list[str] | None = None, folder: str = "") -> dict:
	"""Seçili dosyaları klasöre taşı — `folder` boşsa köke (bağ silinir).

	Bir dosya bir mağazada en çok BİR klasörde durur: eski bağ silinir, yenisi
	yazılır. Sahibi olunmayan dosya sessizce atlanmaz, `skipped` altında
	sayılır; hangi dosya olduğu dönülmez (`archive_media` ile aynı gerekçe).
	"""
	store = _store()
	if folder:
		_my_folder(folder, store)
	urls = _urls(file_urls)

	tasindi = 0
	hatali: list[dict] = []
	atlanan = 0
	for url in urls:
		url = (url or "").split("?")[0]
		if not ownership.owns(store, url):
			atlanan += 1
			continue
		try:
			for eski in frappe.get_all(
				"Media Folder Item",
				filters={"store": store, "file_url": url},
				pluck="name",
			):
				frappe.delete_doc(
					"Media Folder Item", eski, ignore_permissions=True, force=True
				)
			if folder:
				frappe.get_doc(
					{
						"doctype": "Media Folder Item",
						"folder": folder,
						"file_url": url,
						"store": store,
					}
				).insert(ignore_permissions=True)
			tasindi += 1
		except Exception as e:
			hatali.append({"file_url": url, "error": str(e)})

	return {"moved": tasindi, "failed": hatali, "skipped": atlanan}


@frappe.whitelist()
def list_folder_media(
	folder: str = "", page: int = 1, page_size: int = 50, search: str = ""
) -> dict:
	"""Bir klasördeki dosyalar — `get_my_media` satırlarıyla aynı biçimde,
	ekran iki ucu tek kodla çizebilsin diye.

	Aynı adrese ait birden çok `File` satırı olabilir (bkz. `ownership`);
	`group_by` ile adres başına TEK satır dönülür.
	"""
	store = _store()
	_my_folder(folder, store)
	page, page_size, start = normalize_pagination(
		page, page_size, default_page_size=50, max_page_size=200
	)

	urls = frappe.get_all(
		"Media Folder Item", filters={"folder": folder, "store": store}, pluck="file_url"
	)
	if not urls:
		return {"items": [], "total": 0}

	filtre: dict = {"file_url": ["in", urls]}
	if (search or "").strip():
		filtre["file_name"] = ["like", f"%{search.strip()}%"]

	toplam = len(
		frappe.get_all("File", filters=filtre, fields=["file_url"], group_by="file_url")
	)
	satirlar = frappe.get_all(
		"File",
		filters=filtre,
		fields=["name", "file_url", "file_name", "file_size", "creation"],
		group_by="file_url",
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_size,
	)

	ustveri = metadata.read_many([s["file_url"] for s in satirlar], store)
	for s in satirlar:
		s.update(ustveri.get(s["file_url"]) or {})
	return {"items": satirlar, "total": toplam}


@frappe.whitelist()
def find_in_my_library(sha256: str) -> dict:
	"""Yükleme ön kontrolü için tekilleştirme araması (T-042).

	İstemci dosyanın SHA-256'sını tarayıcıda hesaplar (WebCrypto) ve yüklemeye
	başlamadan sorar; eşleşme varsa panel "bu dosya kütüphanenizde" uyarısı
	gösterir. Bu bir UYARI ucudur, engel değil — yükleme yine yapılabilir.

	Eşleşme ÜÇ katmanda aranır (`inventory.find_by_sha256` — katman ayrıntısı
	ve bilinçli sınırlar orada): (1) içerik-adresli dosya adı, (2) boru
	hattının `Media Version.source_hash` kaydı üzerinden kaynak dosya
	(rapor 75 kusur #2: işlenmiş legacy adlı görseller katman 1'de görünmezdi),
	(3) yükleme anında dönüştürülen (PNG→WebP) görsellerin ORİJİNAL
	baytlarının hash'i — `Media Asset.original_sha256` (rapor 64 EK-2 / W7).

	Kiracı sınırı: mağaza OTURUMDAN çözülür (`_store`), parametreyle mağaza
	ALINMAZ ve sorgu `ownership.scope`'tan geçer — başka satıcının dosyası ne
	döner ne de varlığı sezdirilir: eşleşme yoksa ve başka mağazada varsa cevap
	AYNI `{"found": false}`tır (deneme yoluyla envanter keşfine kapı yok).

	Dönen alanlar bilinçli olarak üçle sınırlı: `file_url`, `file_name`,
	`uploaded_at`. Sahip/kullanım bilgisi bu uca taşınmaz.
	"""
	store = _store()
	h = (sha256 or "").strip().lower()
	if not re.fullmatch(r"[0-9a-f]{64}", h):
		frappe.throw(frappe._("64 haneli onaltılık SHA-256 bekleniyor."))
	eslesen = inventory.find_by_sha256(h, store)
	return {"found": bool(eslesen), "file": eslesen}
