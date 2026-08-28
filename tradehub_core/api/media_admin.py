"""Medya envanteri + optimizasyon — HTTP yüzeyi.

**Bu dosyada görsel işleme kodu YOKTUR.** Endpoint'in işi yetki kontrolü, parametre
doğrulama ve kuyruğa atmaktır; iş `tradehub_core/media/` paketinde. Aynı hatayı
`bulk_import`'ta yapıp iş mantığını API dosyasına karıştırdık, tekrarlanmıyor.

Yalnız admin: pazaryeri sahibinin sitedeki tüm görselleri tek yerden görmesi ve
optimize etmesi için. Satıcı self-service kapsam dışı (GORSEL-OPTIMIZASYON.md §6).
"""

from __future__ import annotations

import os

import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import cint

from tradehub_core.media import (
	access_level,
	archive,
	audit,
	browse,
	inventory,
	migration_runtime,
	presets,
	refs,
	retro_rename,
	runner,
	timefmt,
	transcode,
	trash,
	usage,
)

ALLOWED_ROLES: tuple[str, ...] = ("System Manager", "Marketplace Admin")

# Geri alınamaz işlemler yalnız en yüksek role açık. Arşiv silindikten sonra
# optimize edilmiş görsellerin orijinali sistemde kalmıyor — bu yetkiyi
# `Marketplace Admin` seviyesine açmak geri dönüşü olmayan bir riski yayar.
DESTRUCTIVE_ROLES: tuple[str, ...] = ("System Manager",)

# Tek seferde kuyruğa alınabilecek azami dosya — kazara "hepsini" tetiklemeye karşı.
MAX_BATCH: int = 2000


def _guard() -> None:
	_only_for(ALLOWED_ROLES, "media_admin")


def _guard_destructive() -> None:
	_only_for(DESTRUCTIVE_ROLES, "media_destructive")


def _only_for(roles: tuple[str, ...], scope: str) -> None:
	"""Rol kontrolü + reddi denetime yazma.

	`frappe.only_for` reddettiğinde `PermissionError` fırlatır ve geriye iz
	bırakmaz. Yetkisiz erişim denemesi TUR-140'ın kapsamındaki bir güvenlik
	olayı; kimin hangi uçnoktaya erişmeye çalıştığı kayda geçmeli.

	Not: `Administrator` `only_for`'u tamamen atlar (frappe/__init__.py) —
	dolayısıyla bu kayıt Administrator için hiç tetiklenmez, onun işlemleri
	başarılı işlem kayıtlarından izlenir.
	"""
	try:
		frappe.only_for(list(roles))
	except frappe.PermissionError:
		# Denetim yazımı reddi ASLA yutmamalı. `frappe.form_dict` HTTP dışı
		# bağlamda bulunmayabilir; buradaki bir AttributeError PermissionError'ı
		# maskeleyip çağırana yanlış hata tipi döndürürdü.
		try:
			endpoint = (frappe.form_dict or {}).get("cmd")
		except Exception:
			endpoint = None
		audit.log_media_event(
			action=audit.ACTION_ACCESS_DENIED,
			allowed=False,
			reason=f"missing_role:{scope}",
			context={"required_roles": list(roles), "endpoint": endpoint},
		)
		raise


@frappe.whitelist()
def get_image_inventory(
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
) -> dict:
	"""Tekilleştirilmiş public dosya listesi + üst şerit özeti.

	`state`: "pending" | "optimized" | "" (hepsi)
	`sort_by`: "size" | "name" | "date" — `sort_dir`: "desc" | "asc"
	`only_optimizable`: 1 ise yalnız motorun işleyebildiği format + 200 KB üstü
	`min_bytes`: alt boyut sınırı (ör. yalnız 1 MB üstünü görmek için)
	`usage`: "multi_use" (birden fazla kayıtta kullanılan) | "repeat" (tekrar yüklenmiş)
	"""
	_guard()
	result = inventory.list_files(
		page=page,
		page_size=page_size,
		search=(search or "").strip(),
		state=state or "",
		sort_by=sort_by,
		sort_dir=sort_dir,
		only_optimizable=int(only_optimizable or 0),
		min_bytes=int(min_bytes or 0),
		usage=usage or "",
		usage_state=usage_state or "",
	)
	result["summary"] = inventory.summary()
	result["archive_bytes"] = archive.usage_bytes()
	result["trash_bytes"] = trash.usage_bytes()
	result["trash_days"] = trash.TRASH_RETENTION_DAYS
	result["retention_days"] = presets.ARCHIVE_RETENTION_DAYS
	return result


@frappe.whitelist()
def preview_trash(file_urls: str | list[str] | None = None) -> dict:
	"""Seçimin kullanım kırılımı — onay ekranı uyarıyı buna göre kurar."""
	_guard()
	urls = frappe.parse_json(file_urls) if isinstance(file_urls, str) else (file_urls or [])
	vmap = usage.verdict_map_all(deep=True)
	counts: dict[str, int] = {}
	for u in urls:
		v = vmap.get(u, "unknown")
		counts[v] = counts.get(v, 0) + 1
	live = usage.usage_counts_all()

	# Ortak sahiplik kırılımı (TUR-298). İçerik-adresli adlandırma aynı görseli
	# tek dosyaya indiriyor; bu yoldan yapılan silme TÜM sahipleri etkiler.
	# Onay ekranı "kaç ÜRÜNDE kullanılıyor" ile "kaç MAĞAZAYI etkiler" sorusunu
	# ayrı sormak zorunda — ikincisi başkasının verisi.
	paylasilan = [{"file_url": u, "owners": n} for u in urls if (n := trash.owner_count(u)) > 1]
	return {
		"total": len(urls),
		"by_verdict": counts,
		"in_use": counts.get("in_use", 0),
		# Kullanımdakilerin kaç yerde geçtiği — "5 üründe kullanılıyor" uyarısı için.
		"live_places": sum(live.get(u, 0) for u in urls if vmap.get(u) == "in_use"),
		"shared": paylasilan[:50],
		"shared_count": len(paylasilan),
		# Etkilenecek azami mağaza sayısı — uyarının tek cümlelik hâli için.
		"shared_max_owners": max((d["owners"] for d in paylasilan), default=0),
	}


@frappe.whitelist()
def get_file_usage(file_url: str) -> dict:
	"""Tek dosyanın tam kullanım dökümü — detay penceresi.

	Hangi üründe, ana görsel mi galeri mi varyant mı, ürün yayında mı; kaç
	`File` kaydı var ve kaçı fazla; geçmişte nerede geçmiş.
	"""
	_guard()
	return usage.resolve(file_url)


@frappe.whitelist()
def get_optimization_status(job_key: str) -> dict:
	"""Redis'teki ilerleme. Kayıt yoksa {"state": "not_found"}."""
	_guard()
	return runner.read_progress(job_key)


@frappe.whitelist(methods=["POST"])
def start_image_optimization(
	file_names: str | list[str] | None = None,
	preset: str = presets.DEFAULT_PRESET,
	scope: str = "selected",
	limit: int = 0,
	dry_run: int = 0,
	search: str = "",
	only_optimizable: int = 0,
	min_bytes: int = 0,
) -> dict:
	"""Optimizasyonu kuyruğa al ve takip anahtarı dön.

	`scope="selected"` → `file_names` işlenir.
	`scope="pending"`  → bekleyen dosyalar, **ekrandaki filtrelere göre**
	                     (boyuta azalan). `limit` verilirse ilk N tanesi — pilot.

	Senkron çalıştırma yok: tek dosya bile kuyruğa 1 elemanlı liste olarak gider
	(gerekçe `media/runner.py` docstring'i).
	"""
	_guard()

	if preset not in presets.PRESETS:
		frappe.throw(_("Geçersiz preset: {0}").format(preset))

	if scope == "pending":
		names = inventory.pending_file_names(
			limit=int(limit or 0),
			search=(search or "").strip(),
			only_optimizable=int(only_optimizable or 0),
			min_bytes=int(min_bytes or 0),
		)
	else:
		names = frappe.parse_json(file_names) if isinstance(file_names, str) else (file_names or [])
		names = [n for n in names if n]

		# MAX_BATCH yalnız istemciden gelen listeye uygulanır: amacı kaçak/şişmiş
		# bir payload'a karşı korumak. `scope="pending"` listesini sunucunun
		# kendisi ürettiği için güvenilir ve sınırlanmaz — aksi hâlde "tümünü
		# optimize et" 2.000'i aşan her sitede kalıcı olarak patlardı.
		if len(names) > MAX_BATCH:
			frappe.throw(_("Tek seferde en fazla {0} dosya seçilebilir.").format(MAX_BATCH))

	if not names:
		frappe.throw(_("İşlenecek dosya bulunamadı."))

	job_key = frappe.generate_hash(length=12)
	frappe.enqueue(
		"tradehub_core.media.runner.run_batch",
		queue="long",
		timeout=3600,
		enqueue_after_commit=True,
		file_names=names,
		preset=preset,
		job_key=job_key,
		dry_run=int(dry_run or 0),
	)
	return {"job_key": job_key, "count": len(names), "preset": preset, "dry_run": int(dry_run or 0)}


@frappe.whitelist(methods=["POST"])
def restore_image(file_name: str) -> dict:
	"""Optimize edilmiş TEK görseli arşivdeki orijinaliyle geri al (senkron)."""
	_guard()
	if not file_name:
		frappe.throw(_("Dosya adı zorunlu."))
	return runner.restore_original(file_name)


@frappe.whitelist(methods=["POST"])
def retry_transcode(file_url: str) -> dict:
	"""Dead-letter'daki videoyu yönetici eliyle yeniden kuyruğa koy (TUR-296).

	Sahiplik aranmaz — yönetim tüm envanteri görür; rol yeterli. Durum kuralı
	(`failed` dışında ret) `transcode.retry_failed` içinde.
	"""
	_guard()
	if not file_url:
		frappe.throw(_("Dosya adresi zorunlu."))
	sonuc = transcode.retry_failed(file_url)
	audit.log_media_event(
		action=audit.ACTION_OPTIMIZE,
		file_url=file_url,
		context={"kind": "video_transcode", "manual_retry": True},
	)
	return sonuc


@frappe.whitelist(methods=["POST"])
def start_restore(
	file_names: str | list[str] | None = None,
	scope: str = "selected",
	search: str = "",
	min_bytes: int = 0,
) -> dict:
	"""Toplu geri alma — optimizasyonla aynı kuyruk ve ilerleme mekanizması.

	`scope="selected"` → `file_names` geri alınır.
	`scope="optimized"` → ekrandaki filtreye uyan TÜM optimize dosyalar.
	"""
	_guard()

	if scope == "optimized":
		names = inventory.optimized_file_names(search=(search or "").strip(), min_bytes=int(min_bytes or 0))
	else:
		names = frappe.parse_json(file_names) if isinstance(file_names, str) else (file_names or [])
		names = [n for n in names if n]
		if len(names) > MAX_BATCH:
			frappe.throw(_("Tek seferde en fazla {0} dosya seçilebilir.").format(MAX_BATCH))

	if not names:
		frappe.throw(_("Geri alınacak dosya bulunamadı."))

	job_key = frappe.generate_hash(length=12)
	frappe.enqueue(
		"tradehub_core.media.runner.restore_batch",
		queue="long",
		timeout=3600,
		enqueue_after_commit=True,
		file_names=names,
		job_key=job_key,
	)
	return {"job_key": job_key, "count": len(names), "mode": "restore"}


@frappe.whitelist(methods=["POST"])
def trash_files(file_urls: str | list[str] | None = None, force: int = 0, shared_ok: int = 0) -> dict:
	"""Seçili dosyaları çöp kutusuna taşı — 30 gün sonra kalıcı silinir.

	Varsayılanda kullanımda olan dosya reddedilir. `force=1` bu engeli kaldırır;
	ekran o durumda kullanıcıya kaç dosyanın kullanımda olduğunu ve sitede
	görsellerin kırılacağını gösteren ayrı bir uyarı vermek zorunda.

	Kapsam engelleri (private, hassas doctype ekleri) `force` ile de aşılmaz.
	"""
	_guard()
	urls = frappe.parse_json(file_urls) if isinstance(file_urls, str) else (file_urls or [])
	urls = [u for u in urls if u]
	if not urls:
		frappe.throw(_("Taşınacak dosya bulunamadı."))
	if len(urls) > MAX_BATCH:
		frappe.throw(_("Tek seferde en fazla {0} dosya seçilebilir.").format(MAX_BATCH))

	moved, failed, freed = [], [], 0
	for u in urls:
		try:
			r = trash.move_to_trash(u, force=bool(int(force or 0)), shared_ok=bool(int(shared_ok or 0)))
			moved.append(u)
			freed += r["bytes"]
		except Exception as exc:  # noqa: BLE001 — biri patlarsa diğerleri devam etsin
			failed.append({"file_url": u, "error": str(exc)[:200]})

	usage.verdict_map_all(deep=True, refresh=True)
	return {"moved": len(moved), "failed": failed, "freed_bytes": freed}


@frappe.whitelist(methods=["POST"])
def restore_from_trash(file_urls: str | list[str] | None = None) -> dict:
	"""Çöpten geri al."""
	_guard()
	urls = frappe.parse_json(file_urls) if isinstance(file_urls, str) else (file_urls or [])
	urls = [u for u in urls if u]
	if not urls:
		frappe.throw(_("Geri alınacak dosya bulunamadı."))

	back, failed = [], []
	for u in urls:
		try:
			trash.restore(u)
			back.append(u)
		except Exception as exc:  # noqa: BLE001
			failed.append({"file_url": u, "error": str(exc)[:200]})

	usage.verdict_map_all(deep=True, refresh=True)
	return {"restored": len(back), "failed": failed}


@frappe.whitelist(methods=["POST"])
def delete_trashed(file_urls: str | list[str] | None = None, shared_ok: int = 0) -> dict:
	"""Çöpteki seçili dosyaları KALICI sil. Yalnız System Manager.

	Yıkıcı ve geri alınamaz; ama iki adımlı akış sayesinde dosya buraya
	gelmeden önce zaten çöpe taşınmış ve listeden düşmüş oluyor.
	"""
	_guard_destructive()
	urls = frappe.parse_json(file_urls) if isinstance(file_urls, str) else (file_urls or [])
	urls = [u for u in urls if u]
	if not urls:
		frappe.throw(_("Silinecek dosya bulunamadı."))

	deleted, freed, records, failed = 0, 0, 0, []
	for u in urls:
		try:
			r = trash.delete_permanently(u, shared_ok=bool(int(shared_ok or 0)))
			deleted += 1
			freed += r["bytes"]
			records += r["records"]
		except Exception as exc:  # noqa: BLE001
			failed.append({"file_url": u, "error": str(exc)[:200]})

	return {"deleted": deleted, "freed_bytes": freed, "records": records, "failed": failed}


@frappe.whitelist(methods=["POST"])
def purge_trash(older_than_days: int = -1) -> dict:
	"""Çöptekileri KALICI sil. Yalnız System Manager."""
	_guard_destructive()
	days = (
		trash.TRASH_RETENTION_DAYS
		if older_than_days is None or int(older_than_days) < 0
		else int(older_than_days)
	)
	# Kullanıcı düğmesinden geldi — zamanlanmış işten ayrılsın.
	return trash.purge_expired(retention_days=days, trigger="manual")


@frappe.whitelist(methods=["POST"])
def purge_archive(older_than_days: int = -1) -> dict:
	"""Arşivdeki orijinalleri sil — kazanılan alanı kalıcı hâle getirir.

	`older_than_days=-1` → varsayılan saklama süresi (günlük job ile aynı davranış).
	`older_than_days=0`  → arşivin TAMAMI silinir, geri alma imkânı biter.

	Yıkıcı ve geri alınamaz: bu noktadan sonra optimize edilmiş görsellerin
	orijinali sistemde yoktur. Ekran onay diyaloğu olmadan çağırmamalı.

	Yalnız `System Manager` — `Marketplace Admin` bu yetkiye sahip değil.
	"""
	_guard_destructive()
	days = (
		presets.ARCHIVE_RETENTION_DAYS
		if older_than_days is None or int(older_than_days) < 0
		else int(older_than_days)
	)
	result = archive.purge_expired(retention_days=days, trigger="manual")
	frappe.logger("media").info(
		f"archive purge: days={days} deleted={result['deleted']} freed={result['freed_bytes']}"
	)
	return result


@frappe.whitelist()
def get_restorable_count(search: str = "", min_bytes: int = 0) -> dict:
	"""Filtreye uyan kaç dosya geri alınabilir — onay ekranı için."""
	_guard()
	names = inventory.optimized_file_names(search=(search or "").strip(), min_bytes=int(min_bytes or 0))
	return {"count": len(names)}


@frappe.whitelist()
def get_pending_count(search: str = "", only_optimizable: int = 0, min_bytes: int = 0) -> dict:
	"""Mevcut filtrelerle kaç dosyanın işleneceği — onay ekranı bunu gösterir.

	Kullanıcı "tümünü optimize et" derken kaç dosyaya dokunacağını görmeden
	onaylamamalı; ekrandaki satır sayısı ile iş kuyruğu aynı kümeyi ifade etmeli.
	"""
	_guard()
	names = inventory.pending_file_names(
		search=(search or "").strip(),
		only_optimizable=int(only_optimizable or 0),
		min_bytes=int(min_bytes or 0),
	)
	return {"count": len(names)}


# ─── MOGEM-570 sürümlü medya migration akışı ─────────────────────────────


def _migration_plan(value: str | dict | None) -> dict:
	plan = frappe.parse_json(value) if isinstance(value, str) else value
	if not isinstance(plan, dict):
		frappe.throw(_("plan_json bir JSON nesnesi olmalıdır."))
	return plan


@frappe.whitelist(methods=["POST"])
def preflight_media_migration(plan_json: str | dict | None = None, batch_size: int = 200) -> dict:
	"""İmzalı planı yazmadan; kapsam, disk ve kuyruklar dahil doğrula."""
	_guard_destructive()
	return migration_runtime.preflight(_migration_plan(plan_json), batch_size=batch_size)


@frappe.whitelist(methods=["POST"])
def start_media_migration(
	plan_json: str | dict | None = None,
	dry_run: int = 1,
	batch_size: int = 200,
	preset: str = presets.DEFAULT_PRESET,
	approved_dry_run: str = "",
	notify_sellers: int = 0,
) -> dict:
	"""İlk batch'i başlat; varsayılan dry-run, wet-run aynı özetli onay ister."""
	_guard_destructive()
	return migration_runtime.start(
		_migration_plan(plan_json),
		dry_run=bool(cint(dry_run, 1)),
		batch_size=batch_size,
		preset=(preset or presets.DEFAULT_PRESET).strip(),
		approved_dry_run=(approved_dry_run or "").strip(),
		notify_sellers=bool(cint(notify_sellers)),
	)


@frappe.whitelist(methods=["GET"])
def get_media_migration_status(run_key: str, include_plan: int = 0) -> dict:
	_guard_destructive()
	return migration_runtime.status((run_key or "").strip(), include_plan=bool(cint(include_plan)))


@frappe.whitelist(methods=["POST"])
def stop_media_migration(run_key: str) -> dict:
	"""Çalışan batch'i yarıda kesmeden bir sonraki checkpoint'te durdur."""
	_guard_destructive()
	return migration_runtime.request_stop((run_key or "").strip())


@frappe.whitelist(methods=["POST"])
def resume_media_migration(run_key: str, acknowledge_stop: int = 0) -> dict:
	_guard_destructive()
	return migration_runtime.resume((run_key or "").strip(), acknowledge_stop=bool(cint(acknowledge_stop)))


@frappe.whitelist(methods=["POST"])
def validate_media_migration(run_key: str) -> dict:
	_guard_destructive()
	return migration_runtime.validate_run((run_key or "").strip())


@frappe.whitelist(methods=["POST"])
def rollback_media_migration(run_key: str) -> dict:
	_guard_destructive()
	return migration_runtime.start_rollback((run_key or "").strip())


@frappe.whitelist()
def get_media_audit(
	page: int = 1,
	page_size: int = 50,
	action: str = "",
	severity: str = "",
	decision: str = "",
	actor: str = "",
	tenant: str = "",
	file_url: str = "",
	search: str = "",
	days: int = 0,
	sort_by: str = "timestamp",
	sort_dir: str = "desc",
) -> dict:
	"""Medya denetim kayıtları — "kim ne zaman ne yaptı" görünümü (TUR-140).

	Yalnız medya olaylarını döndürür; `Authorization Decision Log`'un geri kalanı
	(yetkilendirme kararları) bu uçnoktanın kapsamı dışındadır. Denetim kaydını
	okumak da yetkili bir işlemdir — envanteri görebilen rol seti geçerlidir.
	"""
	_guard()
	result = audit.list_events(
		page=int(page or 1),
		page_size=int(page_size or 50),
		action=(action or "").strip(),
		severity=(severity or "").strip(),
		decision=(decision or "").strip(),
		actor=(actor or "").strip(),
		tenant=(tenant or "").strip(),
		file_url=(file_url or "").strip(),
		search=(search or "").strip(),
		days=int(days or 0),
		sort_by=(sort_by or "timestamp").strip(),
		sort_dir=(sort_dir or "desc").strip(),
	)
	result["actions"] = list(audit.MEDIA_ACTIONS)
	result["sortable"] = list(audit.SORTABLE)
	return result


@frappe.whitelist()
def get_file_references(file_url: str) -> dict:
	"""Bu dosyayı gösteren TÜM satırlar — silmeden önce etki listesi.

	`get_file_usage` "nerede kullanılıyor" sorusunu ürün diliyle cevaplıyor;
	bu uçnokta ise temizlenecek somut satırları verir (tablo, kolon, kayıt).
	"""
	_guard()
	url = (file_url or "").strip()
	return {"file_url": url, "items": refs.find(url), "preview": refs.clear(url, dry_run=True)}


@frappe.whitelist(methods=["POST"])
def set_access_level(file_url: str, make_private: int = 0) -> dict:
	"""Dosyanın erişim seviyesini public↔private çevir (TUR-126 §4).

	Fiziksel taşıma + `File.file_url`/`is_private` güncelleme + tüm referansların
	(`Listing.primary_image` vb.) yeni URL'e çevrilmesi tek işlemde yapılır —
	iş `tradehub_core/media/access_level.py`'da. KYB/KYC gibi kapsam dışı
	doctype'a bağlı dosya ASLA public yapılamaz (PII sızıntısı koruması);
	zaten hedef seviyedeyse no-op (idempotent).
	"""
	_guard()
	return access_level.set_level((file_url or "").strip(), make_private=bool(int(make_private or 0)))


@frappe.whitelist()
def get_private_files(page: int = 1, page_size: int = 50, search: str = "") -> dict:
	"""Özel (private) dosya envanteri — panel "Özel dosyalar" görünümü (TUR-126 §4.2).

	`inventory.list_files` bilinçli olarak public-only (optimize akışı private
	belge işlemez); özele taşınan bir dosyayı panelden GERİ almak ve imzalı
	link üretmek için private dosyaların da kimliğiyle listelenmesi gerekir.
	Denetim akışındaki maskeleme burada geçerli değil: bu uç `_guard()` ile
	süper-admin'e kapılı ve Desk'in File listesinin zaten gösterdiğinden
	fazlasını göstermez. PII kapsamındaki dosyalar `pii=True` bayrağıyla döner —
	bunlar public yapılamaz (backend `set_level` zorlar, UI aksiyonu gizler).
	"""
	_guard()
	page = max(1, int(page or 1))
	page_size = min(100, max(1, int(page_size or 50)))
	search = (search or "").strip()

	f = frappe.qb.DocType("File")
	base = frappe.qb.from_(f).where(f.is_private == 1).where(f.file_url.like("/private/files/%"))
	if search:
		pattern = f"%{search}%"
		base = base.where((f.file_name.like(pattern)) | (f.file_url.like(pattern)))

	total = base.select(Count(f.name)).run()[0][0]
	rows = (
		base.select(
			f.name,
			f.file_name,
			f.file_url,
			f.file_size,
			f.creation,
			f.attached_to_doctype,
			f.attached_to_name,
		)
		.orderby(f.creation, order=frappe.qb.desc)
		.limit(page_size)
		.offset((page - 1) * page_size)
		.run(as_dict=True)
	)
	for r in rows:
		# İki yönlü PII kontrolü (attached + ters referans) — access_level ile
		# aynı kaynak, liste ile toggle farklı karar vermesin.
		r["pii"] = access_level._is_protected_pii(r, r.file_url)
	return {"items": rows, "total": total, "page": page, "page_size": page_size}


@frappe.whitelist()
def browse_media(
	scope: str = "",
	store: str = "",
	category: str = "",
	group: str = "",
	sub: str = "",
	doc_field: str = "",
	page: int = 1,
	page_size: int = 50,
	search: str = "",
) -> dict:
	"""Medya Gezgini — sanal klasör ağacında bir seviye (TUR-126 devamı).

	Parametre derinliği seviyeyi belirler: hiçbiri yoksa kök (public/private),
	`scope=public` mağazalar, `+store` kategoriler, `+category` dosyalar;
	`scope=private` belge türü grupları, `+group` dosyalar — KYB/KYC gibi
	detaylı gruplarda önce mağaza alt klasörleri (`+sub`), sonra belge-alanı
	klasörleri (`+doc_field`) gelir. Klasörler sanal — disk yapısına
	dokunulmaz (bkz. `media/browse.py`).
	"""
	_guard()
	scope = (scope or "").strip()
	store = (store or "").strip()
	category = (category or "").strip()
	group = (group or "").strip()
	sub = (sub or "").strip()
	doc_field = (doc_field or "").strip()

	if not scope:
		return browse.root()
	if scope == "chat":
		if not store:
			return browse.chat_stores()
		return browse.files(
			scope="chat", store=store, page=int(page), page_size=int(page_size), search=search
		)
	if scope == "private":
		if not group:
			return browse.private_groups()
		if group in browse.DETAILED_PRIVATE_GROUPS:
			if not sub:
				return browse.private_group_stores(group)
			if not doc_field:
				return browse.private_store_fields(group, sub)
		return browse.files(
			scope="private",
			group=group,
			sub=sub,
			doc_field=doc_field,
			page=int(page),
			page_size=int(page_size),
			search=search,
		)
	if scope != "public":
		frappe.throw(_("Geçersiz kapsam: {0}").format(scope))
	if not store:
		return browse.public_stores()
	if not category and store != browse.PLATFORM_STORE:
		return browse.public_categories(store)
	return browse.files(
		scope="public",
		store=store,
		category=category,
		page=int(page),
		page_size=int(page_size),
		search=search,
	)


@frappe.whitelist()
def get_record_media(doctype: str, name: str) -> dict:
	"""Ters arama — bir ürünün/mağazanın kullandığı tüm medya (TUR-136).

	`get_file_usage` "bu dosya nerede kullanılıyor" der; bu uçnokta tersini
	yapar. Her görselin yanında başka yerlerde de kullanılıp kullanılmadığı
	yazar — silme kararının asıl belirleyicisi o.
	"""
	_guard()
	return usage.images_of((doctype or "").strip(), (name or "").strip())


@frappe.whitelist()
def get_dangling_references(limit: int = 500) -> dict:
	"""Hedefi olmayan referanslar — geçmişte bozulmuş bağların raporu."""
	_guard()
	items = refs.find_dangling(limit=int(limit or 500))
	return {"items": items, "total_rows": sum(i["rows"] for i in items)}


@frappe.whitelist(methods=["POST"])
def repair_dangling_references(dry_run: int = 1) -> dict:
	"""Kırık referansları temizle. Varsayılan kuru çalışma — yıkıcı iş sessizce
	çalışmamalı; `dry_run=0` gerçekten uygular."""
	_guard_destructive()
	return refs.repair_dangling(dry_run=bool(int(dry_run or 0)))


@frappe.whitelist()
def get_media_audit_facets(days: int = 0) -> dict:
	"""Filtre rayı sayaçları — hangi olaydan kaç tane, kaç reddedilen istek."""
	_guard()
	return audit.facets(days=int(days or 0))


@frappe.whitelist()
def get_media_audit_actors(limit: int = 50) -> dict:
	"""Denetimde geçen kullanıcı/satıcı listesi — filtre açılır kutusu için."""
	_guard()
	return {"items": audit.actors(limit=int(limit or 50))}


@frappe.whitelist()
def get_media_audit_report(name: str) -> dict:
	"""Tek denetim kaydının tam raporu — dosya künyesi, kullanım, etki, geçmiş.

	Maskeli kayıtlarda dosya ve kullanım blokları boş döner; aksi hâlde
	gizlediğimiz belge rapor üzerinden okunabilir hâle gelirdi.
	"""
	_guard()
	return audit.report((name or "").strip())


@frappe.whitelist()
def get_media_audit_targets(limit: int = 10) -> dict:
	"""En çok olay üreten dosyalar."""
	_guard()
	return {"items": audit.top_targets(limit=int(limit or 10))}


@frappe.whitelist()
def export_media_audit(
	action: str = "",
	severity: str = "",
	decision: str = "",
	actor: str = "",
	tenant: str = "",
	file_url: str = "",
	search: str = "",
	days: int = 0,
	limit: int = 5000,
) -> dict:
	"""Filtreye uyan kayıtları CSV olarak döndür.

	İstemci tarafında yalnız görünen sayfayı dışa aktarmak yanıltıcı olurdu —
	operatör "filtrelediğim her şeyi ver" bekliyor.
	"""
	_guard()
	rows = audit.export_rows(
		action=(action or "").strip(),
		severity=(severity or "").strip(),
		decision=(decision or "").strip(),
		actor=(actor or "").strip(),
		tenant=(tenant or "").strip(),
		file_url=(file_url or "").strip(),
		search=(search or "").strip(),
		days=int(days or 0),
		limit=int(limit or 5000),
	)

	import csv
	import io

	buf = io.StringIO()
	cols = [
		"timestamp",
		"action",
		"decision",
		"severity",
		"actor",
		"tenant",
		"object_name",
		"ip_address",
		"context",
	]
	writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
	writer.writeheader()
	for r in rows:
		writer.writerow({c: r.get(c) for c in cols})

	return {"csv": buf.getvalue(), "count": len(rows)}


# ─────────────────────────────────────────────────────────────────────
# Yedekleme ve geri yükleme (TUR-131)
#
# Geri yükleme YIKICI RİSK taşıyor: yanlış çalışırsa bugünkü veriyi dünkiyle
# ezer. Bu yüzden okuma uçları normal yönetim yetkisiyle, YAZAN uçlar en
# yüksek yetkiyle korunuyor — arşiv silme ile aynı seviye.
# ─────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def list_media_backups() -> dict:
	"""Alınmış yedekler + deponun kapladığı yer."""
	_guard()
	from tradehub_core.media import backup

	return {"sets": backup.list_sets(), "usage": backup.usage(), "keep": backup.KEEP_SETS}


@frappe.whitelist(methods=["POST"])
def create_media_backup(label: str = "") -> dict:
	"""Elle yedek al. Zamanlanmış görev bunu günlük çalıştırıyor."""
	_guard_destructive()
	from tradehub_core.media import backup

	return backup.snapshot(label=label)


@frappe.whitelist()
def verify_media_backup(set_id: str, deep: int = 0) -> dict:
	"""Yedek geri yüklenebilir mi — dokunmadan kontrol.

	`deep=1` havuzdaki içeriğin imzasını da yeniden hesaplar; sessiz disk
	bozulmasını ancak bu yakalar, karşılığında yavaştır.
	"""
	_guard()
	from tradehub_core.media import backup

	return backup.verify(set_id, deep=bool(int(deep or 0)))


@frappe.whitelist()
def plan_media_restore(set_id: str) -> dict:
	"""Geri yüklersem ne olur — HİÇBİR ŞEYE DOKUNMAZ.

	Uygulama ayrı uçta. Kimse tek çağrıyla geri yükleme başlatamasın diye.
	"""
	_guard()
	from tradehub_core.media import restore

	return restore.plan(set_id)


@frappe.whitelist(methods=["POST"])
def apply_media_restore(
	set_id: str,
	files: int = 1,
	records: int = 1,
	overwrite: int = 0,
	only: str | list[str] | None = None,
) -> dict:
	"""Geri yüklemeyi uygula.

	`overwrite=0` (varsayılan): içeriği değişmiş dosyalara DOKUNULMAZ, çatışma
	olarak raporlanır. `1` yapmak, bugünkü içeriği yedekteki eski hâliyle
	değiştirmeyi açıkça istemek demektir.

	Hiçbir durumda dosya ya da kayıt SİLİNMEZ.
	"""
	_guard_destructive()
	from tradehub_core.media import restore

	yollar = frappe.parse_json(only) if isinstance(only, str) else only
	return restore.apply(
		set_id,
		files=bool(int(files or 0)),
		records=bool(int(records or 0)),
		overwrite=bool(int(overwrite or 0)),
		only=yollar or None,
	)


@frappe.whitelist(methods=["POST"])
def repair_missing_media(set_id: str = "") -> dict:
	"""Kaydı olup dosyası kaybolanları en yeni yedekten geri getir.

	Felaket kurtarmanın en sık hâli: veritabanı sağlam, diskten dosya gitmiş.
	Tüm yedeği uygulamaya gerek yok, yalnız eksikler yazılır.
	"""
	_guard_destructive()
	from tradehub_core.media import restore

	return restore.repair_missing_files(set_id or None)


@frappe.whitelist(methods=["POST"])
def prune_media_backups(keep: int = 0) -> dict:
	"""Eski yedekleri ve artık kimsenin göstermediği içerikleri temizle."""
	_guard_destructive()
	from tradehub_core.media import backup

	return backup.prune(keep=int(keep) if keep else backup.KEEP_SETS)


@frappe.whitelist(methods=["POST"])
def delete_media_backup(set_id: str) -> dict:
	"""Tek bir yedeği sil.

	`set_id` istekten geliyor ve dosya yoluna giriyor — kalıp ve kök kontrolü
	`backup._set_path` içinde, bu uç onu atlayamaz.
	"""
	_guard_destructive()
	from tradehub_core.media import backup

	return backup.delete_set(set_id)


# ─────────────────────────────────────────────────────────────────────
# Dışa aktarma (TUR-131)
#
# Yedek, koruduğu medyayla aynı diskte duruyor — TUR-131'in karşılanmayan tek
# maddesi buydu. Paket indirilip başka bir yere konduğu anda yedek gerçekten
# ikinci bir yerde olur.
#
# Paket TÜM medyayı içerir, ÖZEL BELGELER dahil. Bu yüzden üç ucun da yetkisi
# en yüksek seviyede: dışa aktarma, verinin sunucuyu terk ettiği tek nokta.
# ─────────────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def start_media_backup_export(set_id: str) -> dict:
	"""Paketlemeyi başlat — hazırlık arkada sürer, bu uç beklemez."""
	_guard_destructive()
	from tradehub_core.media import backup_export

	return backup_export.start(set_id)


@frappe.whitelist()
def media_backup_export_status(set_id: str) -> dict:
	"""Paket ne durumda — ekran bunu düzenli aralıkla sorar."""
	_guard()
	from tradehub_core.media import backup_export

	return backup_export.status(set_id)


@frappe.whitelist(methods=["POST"])
def discard_media_backup_export(set_id: str) -> dict:
	"""Hazır paketi sunucudan kaldır."""
	_guard_destructive()
	from tradehub_core.media import backup_export

	return backup_export.discard(set_id)


@frappe.whitelist(methods=["GET"])
def download_media_backup_export(set_id: str):
	"""Paketi indir.

	Dosya belleğe ALINMIYOR: 1 GB'lık bir paketi yanıt gövdesine koymak süreci
	şişirirdi. Frappe'nin özel dosya göndericisi kullanılıyor — parça parça
	akıtıyor, yarıda kalan indirme kaldığı yerden devam edebiliyor.

	`set_id` istekten geliyor ve dosya yoluna giriyor; kalıp, kök ve varlık
	kontrolü `backup_export.package_path` içinde.
	"""
	_guard_destructive()
	from frappe.utils.response import send_private_file

	from tradehub_core.media import audit, backup_export

	tam = backup_export.package_path(set_id)
	audit.log_media_event(
		action=audit.ACTION_EXPORT,
		sensitive=True,
		context={"set_id": set_id, "downloaded": True},
	)

	# Gönderici site'ın private kökünden itibaren göreli yol bekliyor.
	kok = frappe.get_site_path("private")
	return send_private_file(os.path.relpath(tam, kok))


# ── Zararlı içerik taraması ve karantina (TUR-125) ──────────────────────


@frappe.whitelist()
def scan_overview() -> dict:
	"""Tarama politikasının ve envanterin özeti — panel üst bandı.

	Politikayı da döndürüyor: tarayıcı kurulu değilse panel "0 zararlı bulundu"
	yerine "tarama kapalı" demeli. İkisini aynı yeşil kutuda göstermek, hiç
	çalışmayan bir güvenlik özelliğini çalışıyor gibi sunmanın en kolay yolu.
	"""
	_guard()
	from tradehub_core.media import av

	sayimlar = {
		durum: frappe.db.count("File", {"th_media_scan_status": durum}) for durum in av.STORED_SCAN_STATUSES
	}
	# Hiç taranmamışlar: alan boş. Yamada bilerek backfill yapılmadı, bu sayı
	# "geriye dönük tarama ne kadar kaldı" sorusunun cevabı.
	# `is / not set` — NULL ve boş string'i birlikte kapsar. `["in", ["", None]]`
	# yazılırsa Frappe `IN ('', NULL)` üretir ve NULL satırları kaçırır; alan
	# sonradan eklendiği için mevcut kayıtların neredeyse tamamı NULL, yani sayı
	# 5.150 yerine 30 görünürdü (ölçüldü).
	sayimlar["unscanned"] = frappe.db.count(
		"File", {"th_media_scan_status": ["is", "not set"], "is_folder": 0}
	)
	return {"policy": av.policy(), "counts": sayimlar}


@frappe.whitelist()
def list_scan_hold(page: int = 1, page_size: int = 50) -> dict:
	"""Taraması bitmemiş, bu yüzden erişime kapalı bekleyen dosyalar.

	Karantinadan AYRI liste: karantina bir karar ("zararlı"), bekletme bir ara
	durum ("henüz bilmiyoruz"). İkisini aynı ekranda tek liste hâlinde
	göstermek, operatörün olağan bir yüklemeyi zararlı sanmasına yol açardı.

	Bu listenin uzun süre dolu kalması bir SORUN işaretidir: ya kuyruk
	çalışmıyor ya tarayıcı takılmış. Ekran bunu göstermek için var.
	"""
	_guard()
	from tradehub_core.media import av

	page = max(1, int(page or 1))
	page_size = min(200, max(1, int(page_size or 50)))
	satirlar = frappe.get_all(
		"File",
		filters={"th_media_scan_status": av.SCAN_PENDING},
		fields=[
			"name",
			"file_name",
			"file_url",
			"file_size",
			"creation",
			"th_media_scan_attempts",
			"th_media_scan_started_at",
		],
		order_by="th_media_scan_started_at asc",
		limit=page_size,
		start=(page - 1) * page_size,
	)
	for r in satirlar:
		r["scan_attempts"] = r.pop("th_media_scan_attempts", 0)
		r["started_at"] = r.pop("th_media_scan_started_at", None)
		r["in_hold"] = av.in_hold(r["file_url"])
	# Tarih standardı (TUR-124): saat dilimi işareti olmadan gönderilen damga,
	# tarayıcıda kullanıcının KENDİ saati sanılıyor — envanter uçlarıyla aynı
	# kural, güvenlik uçları istisna değil.
	timefmt.apply_all(satirlar)
	return {
		"items": satirlar,
		"total": frappe.db.count("File", {"th_media_scan_status": av.SCAN_PENDING}),
		"page": page,
		"page_size": page_size,
	}


@frappe.whitelist(methods=["POST"])
def sweep_scans() -> dict:
	"""Süpürücüyü elle tetikle — takılı kalmış taramaları topla.

	Zamanlanmış görev zaten 5 dakikada bir koşuyor; bu uç, operatörün bir
	sorunu fark ettiğinde beklemek zorunda kalmaması için var.
	"""
	_guard()
	from tradehub_core.media import av

	return av.sweep_stuck_scans()


@frappe.whitelist()
def list_quarantine(page: int = 1, page_size: int = 50) -> dict:
	"""Karantinadaki dosyalar — envanter listesinden AYRI uç.

	Envanter sorgusu public dosya ağacını tarıyor; karantinadaki dosya oradan
	fiziksel olarak çıkmış durumda ve o listede görünmez. Ayrı uç olmasaydı
	zararlı bulgular panelde hiçbir yerde görünmezdi.
	"""
	_guard()
	from tradehub_core.media import av

	page = max(1, int(page or 1))
	page_size = min(200, max(1, int(page_size or 50)))
	satirlar = frappe.get_all(
		"File",
		filters={"th_media_scan_status": ["in", [av.SCAN_INFECTED, av.SCAN_FAILED]]},
		fields=[
			"name",
			"file_name",
			"file_url",
			"file_size",
			"creation",
			"th_media_scan_status",
			"th_media_scan_attempts",
		],
		order_by="modified desc",
		limit=page_size,
		start=(page - 1) * page_size,
	)
	for r in satirlar:
		r["scan_status"] = r.pop("th_media_scan_status", "")
		r["scan_attempts"] = r.pop("th_media_scan_attempts", 0)
		r["in_quarantine"] = av.in_quarantine(r["file_url"])
	# Tarih standardı (TUR-124) — yukarıdaki bekletme listesiyle aynı gerekçe.
	timefmt.apply_all(satirlar)
	toplam = frappe.db.count("File", {"th_media_scan_status": ["in", [av.SCAN_INFECTED, av.SCAN_FAILED]]})
	return {"items": satirlar, "total": toplam, "page": page, "page_size": page_size}


@frappe.whitelist(methods=["POST"])
def retry_scan(file_url: str) -> dict:
	"""Taranamamış (`failed`) dosyayı yeniden kuyruğa koy.

	`infected` KABUL EDİLMEZ — zararlı bulgusunu yeniden tarayarak "belki bu
	sefer temiz çıkar" demek bulgunun anlamını yok eder. Oradan çıkış yalnız
	`release_quarantine`, yani açık bir insan kararıdır. Kural
	`av.retry_failed` içinde.
	"""
	_guard()
	from tradehub_core.media import av

	if not file_url:
		frappe.throw(_("Dosya adresi zorunlu."))
	return av.retry_failed(file_url)


@frappe.whitelist(methods=["POST"])
def release_quarantine(file_url: str) -> dict:
	"""Yanlış pozitifi karantinadan çıkar — dosyayı yerine koy.

	`_guard_destructive` (yalnız System Manager): bu uç, sistemin ZARARLI
	dediği bir dosyayı erişime geri açıyor. Yanlış pozitifler gerçek ve bu
	yeteneğin olmaması operasyonu kilitler; ama yetkiyi `Marketplace Admin`
	seviyesine açmak, zararlı bulgusunu tek tıkla iptal edebilecek kişi
	sayısını gereksiz büyütürdü — arşiv silmeyle aynı gerekçe.
	"""
	_guard_destructive()
	from tradehub_core.media import av

	if not file_url:
		frappe.throw(_("Dosya adresi zorunlu."))
	return av.release_from_quarantine(file_url)


@frappe.whitelist(methods=["POST"])
def scan_backfill(limit: int = 500) -> dict:
	"""Hiç taranmamış mevcut dosyaları parça parça kuyruğa al.

	Yama alanı ekliyor ama mevcut ~4.000 dosyayı taramaya sokmuyor; geriye dönük
	tarama buradan, yönetici kontrolünde ve parça parça yürür.
	"""
	_guard()
	from tradehub_core.media import av

	return av.backfill_pending(limit=min(2000, max(1, int(limit or 500))))


# ─── MOGEM-582 retro-rename ────────────────────────────────────────────────
# Eski adlı (`content_<hash>.<ext>` öncesi) dosyaları yeni adlandırma şemasına
# taşıyan araç. İş mantığı `tradehub_core/media/retro_rename.py`'de; burada
# yalnız yetki + kuyruğa alma var (dosya başlığındaki "iş mantığı karışmasın"
# kuralı).


@frappe.whitelist(methods=["GET"])
def retro_rename_count() -> dict:
	"""Taşınacak eski adlı dosya sayısı — yalnız sayaç, referans taraması YOK.

	`retro_rename_plan` tüm adaylar için referans taraması yapıyor (lokalde
	~20 sn); admin kartının açılışında yalnız sayı gerekiyor, tam plan yalnız
	"Önizle" tıklamasında istenir.

	`total` bayat satırları da sayar: `tabFile` eski adresi gösteriyor ama blob
	diskte yok (silinmiş/karantinaya taşınmış). Bunlar bu araçla TAŞINAMAZ, o
	yüzden `disk_missing`/`renamable` ayrı dönüyor — aksi hâlde kart hiç
	sıfırlanmayan bir "N dosya bekliyor" rozetinde takılı kalıyordu.
	"""
	_guard_destructive()
	return retro_rename.count_summary()


@frappe.whitelist(methods=["GET"])
def retro_rename_plan(limit: int = 200) -> dict:
	"""Eski adlı dosyaların salt okunur taşınma planı (System Manager).

	`limit` `start_retro_rename`'in `batch_size`'ı gibi KIRPILIR: `cint(limit,
	200)` sayı olmayan girdiyi sessizce varsayılana çeker, negatifi 0'a, üst
	sınır `PLAN_ITEM_LIMIT`. Kırpma olmadan `limit="abc"` çıplak `int()` içinde
	`ValueError` fırlatıp uca 500 döndürüyordu.
	"""
	_guard_destructive()
	kirpik = min(retro_rename.PLAN_ITEM_LIMIT, max(0, cint(limit, 200)))
	p = retro_rename.plan()
	p["items"] = p["items"][:kirpik]
	return p


@frappe.whitelist(methods=["POST"])
def start_retro_rename(dry_run: int = 0, batch_size: int = 200) -> dict:
	"""Retro-rename işini kuyruğa al; aynı anda tek iş."""
	_guard_destructive()
	total = len(retro_rename.legacy_urls())
	if not total:
		frappe.throw(_("Taşınacak eski adlı dosya yok."))
	job_key = frappe.generate_hash(length=12)
	clamped_batch_size = min(2000, max(1, int(batch_size or 200)))
	# Atomik SET NX EX: iki eşzamanlı POST'un ikisi de get-then-set penceresinden
	# geçemez. Kuyruk gecikmesi 120 saniyeyi aşabildiği için kilit worker timeout
	# bütçesinden uzun başlar; worker yalnız KENDİ sahipliğini tazeler/siler.
	if not retro_rename.claim_active(job_key):
		frappe.throw(_("Zaten çalışan bir yeniden adlandırma işi var."))
	try:
		frappe.enqueue(
			"tradehub_core.media.retro_rename.run_job",
			queue="long",
			timeout=4 * 3600,
			enqueue_after_commit=True,
			job_key=job_key,
			dry_run=int(dry_run or 0),
			batch_size=clamped_batch_size,
		)
	except Exception:
		retro_rename.release_active(job_key)
		raise
	return {"job_key": job_key, "total": total, "dry_run": int(dry_run or 0)}


@frappe.whitelist(methods=["GET"])
def get_retro_rename_status(job_key: str) -> dict:
	"""Redis'teki ilerleme. Kayıt yoksa `{"state": "not_found"}`."""
	_guard_destructive()
	return retro_rename.read_progress(job_key)


@frappe.whitelist(methods=["POST"])
def stop_retro_rename(job_key: str) -> dict:
	"""Bir sonraki batch sınırında durdur."""
	_guard_destructive()
	retro_rename.request_stop(job_key)
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def rollback_retro_rename(job_key: str) -> dict:
	"""Bir işin yeniden adlandırmalarını geri al (yönlendirme satırları durduğu sürece)."""
	_guard_destructive()
	rollback_key = frappe.generate_hash(length=12)
	if not retro_rename.claim_active(rollback_key):
		frappe.throw(_("Zaten çalışan bir iş var; bitmesini bekleyin."))
	try:
		frappe.enqueue(
			"tradehub_core.media.retro_rename.run_rollback",
			queue="long",
			timeout=4 * 3600,
			enqueue_after_commit=True,
			job_key=job_key,
			rollback_key=rollback_key,
		)
	except Exception:
		retro_rename.release_active(rollback_key)
		raise
	return {"job_key": rollback_key, "source_job_key": job_key}


@frappe.whitelist(methods=["GET"])
def retro_rename_history() -> dict:
	"""Geri alınabilir işler: job_key başına satır sayısı ve süre sonu."""
	_guard_destructive()
	# Tablo/kolon adları sabit (kullanıcı girdisi yok) — f-string yok, ham SQL
	# `frappe.db.sql` ile güvenli. `frappe.qb` ile `groupby` + `Min` + aggregate
	# alias üzerinden `orderby` pypika'da kırılgan; bu sorgu için düz SQL tercih
	# edildi (refactor-targets.md §2 istisnası — sabit tablo/kolon).
	rows = frappe.db.sql(  # noqa: S608 — sabit tablo/kolon, kullanıcı girdisi yok
		"""select job_key, count(*) as count, min(expires_at) as expires_at, min(creation) as first_created
			from `tabMedia URL Redirect` group by job_key order by first_created desc""",
		as_dict=True,
	)
	return {"jobs": rows}


# ── SEO alanları, üretim ve denetim (TUR-135) ───────────────────────────


@frappe.whitelist()
def get_media_seo(
	file_url: str, ref_doctype: str = "", ref_name: str = "", ref_field: str = "", lang: str = "tr"
) -> dict:
	"""Bir görselin SEO alanları — kullanım bağlamı verilirse ezme uygulanır."""
	_guard()
	from tradehub_core.media import seo, seo_index, seo_urls

	if not file_url:
		frappe.throw(_("Dosya adresi zorunlu."))
	result = seo.fields_for(
		file_url, ref_doctype=ref_doctype, ref_name=ref_name, ref_field=ref_field, lang=lang
	)
	result["usages"] = seo.usage_overrides_for(file_url, lang=lang)
	result["urls"] = seo_urls.resolve(
		file_url,
		ref_doctype=ref_doctype,
		ref_name=ref_name,
		context_doctype=ref_doctype,
		context_name=ref_name,
	)
	result["indexability"] = seo_index.decide(file_url, check_usage=False)
	return result


@frappe.whitelist(methods=["POST"])
def set_media_seo(file_url: str, values: str | dict, store: str = "") -> dict:
	"""Varlık varsayılanını yaz. Beyaz liste `media/seo.py`'de — yaşam
	döngüsü alanları buradan geçemez."""
	_guard()
	from tradehub_core.media import seo

	veri = frappe.parse_json(values) if isinstance(values, str) else (values or {})
	sayi = seo.set_asset_fields(file_url, veri, store=store or None)
	return {"file_url": file_url, "records": sayi}


@frappe.whitelist(methods=["POST"])
def set_media_seo_override(
	file_url: str, ref_doctype: str, ref_name: str, ref_field: str, values: str | dict
) -> dict:
	"""Kullanım başına ezme — aynı görsel farklı sayfada farklı alt metni."""
	_guard()
	from tradehub_core.media import seo

	veri = frappe.parse_json(values) if isinstance(values, str) else (values or {})
	ad = seo.set_override(
		file_url,
		ref_doctype=ref_doctype,
		ref_name=ref_name,
		ref_field=ref_field,
		values=veri,
		source=seo.SOURCE_HUMAN,
	)
	return {"name": ad}


@frappe.whitelist(methods=["POST"])
def clear_media_seo_override(file_url: str, ref_doctype: str, ref_name: str, ref_field: str) -> dict:
	_guard()
	from tradehub_core.media import seo

	return {
		"cleared": seo.clear_override(
			file_url, ref_doctype=ref_doctype, ref_name=ref_name, ref_field=ref_field
		)
	}


@frappe.whitelist(methods=["POST"])
def set_media_indexability(
	file_url: str, visibility: str, expires_at: str = "", robots_override: str = ""
) -> dict:
	"""Asset visibility/indexability politikasını tek yazma kapısından güncelle."""
	_guard()
	allowed = {"Public", "Private", "Unlisted", "Protected", "Temporary", "Expired", "Archived", "Deleted"}
	if visibility not in allowed:
		frappe.throw(_("Geçersiz medya görünürlüğü: {0}").format(visibility))
	if visibility == "Private":
		frappe.throw(
			_("Private geçişi fiziksel dosya taşıması gerektirir; erişim seviyesi aracını kullanın.")
		)
	robots_override = (robots_override or "").strip()
	if robots_override:
		allowed_directives = {
			"index",
			"noindex",
			"follow",
			"nofollow",
			"nosnippet",
			"max-image-preview:none",
			"max-image-preview:standard",
			"max-image-preview:large",
			"max-video-preview:0",
			"max-video-preview:-1",
		}
		parts = {p.strip().lower() for p in robots_override.split(",") if p.strip()}
		if not parts or not parts <= allowed_directives:
			frappe.throw(_("Geçersiz robots directive."))
	values = {"th_media_visibility": visibility}
	if frappe.db.has_column("File", "th_media_expires_at"):
		values["th_media_expires_at"] = expires_at or None
	if frappe.db.has_column("File", "th_media_robots_override"):
		values["th_media_robots_override"] = robots_override
	frappe.db.set_value("File", {"file_url": (file_url or "").split("?")[0]}, values, update_modified=False)
	from tradehub_core.media import seo_index

	return seo_index.decide(file_url, check_usage=False)


@frappe.whitelist(methods=["POST"])
def generate_media_alt(file_url: str, force: int = 0) -> dict:
	"""Kural zinciriyle alt metni üret. `force` insan metnini EZER — yalnız
	bilinçli kullanım için."""
	_guard()
	from tradehub_core.media import seo_generate

	return seo_generate.refresh_alt(file_url, force=bool(int(force)))


@frappe.whitelist(methods=["POST"])
def backfill_media_alt(limit: int = 500, only_listing: int = 1) -> dict:
	"""Mevcut katalogu parça parça doldur — `av.backfill_pending` deseni."""
	_guard()
	from tradehub_core.media import seo_generate

	return seo_generate.backfill(limit=limit, only_listing=bool(int(only_listing)))


@frappe.whitelist(methods=["POST"])
def backfill_media_localization(limit: int = 500) -> dict:
	"""Katalogu en/ar/ru dillerinde parça parça doldur (Dilim 8 — Bulk
	Localization). `backfill_media_alt` (tr) emsali: senkron, limit'li (L3).

	Kaynak çevirisi (`Listing.title_{lang}`) olmayan dosya/dilde
	`no_translation` sebebiyle sessizce atlanır (L1: kopyalama yasak); insan
	(`human`/`edited`) damgalı dosyanın hiçbir dil kolonuna dokunulmaz (L6).
	"""
	_guard()
	from tradehub_core.media import seo_generate

	return seo_generate.backfill_localization(limit=limit)


@frappe.whitelist()
def audit_media_seo(
	file_urls: str | list[str] | None = None,
	deep: int = 0,
	limit: int = 5000,
	scope: str = "catalog",
	page: int = 1,
	page_size: int = 50,
	code: str = "",
	q: str = "",
	refresh: int = 0,
) -> dict:
	"""SEO denetimi.

	`scope` — adres verilmediğinde HANGİ dosyaların taranacağı:

	    catalog (varsayılan)  vitrinde kullanılan ürün görselleri (1.983)
	    recent                en son yüklenenler
	    all                   tüm public dosyalar (3.267)

	Kapsamın TAMAMI denetlenip özet/skor ondan hesaplanır; `page`/`page_size`
	yalnız DÖNEN SATIRLARI sınırlar. Özeti sayfadan hesaplamak "138 eksik"
	yerine "20 eksik" derdi. Tam denetim 60 sn önbellekli (ölçüm: 3.200 dosya
	2,2 s); `refresh=1` önbelleği atlar.

	`code` bulgu süzgeci, `q` dosya adı/adres araması — ikisi de sunucuda.

	Varsayılan neden "catalog": "en yeni" ile açıldığında ekran, o gün koşan
	testlerin bıraktığı dosyaları gösteriyordu (ölçüldü 21 Ağu: ilk 10 satırın
	10'u da test videosuydu). SEO'nun konusu vitrinde görünen katalog; ar-ge
	belgesi de aynı önceliği koyuyor (§5.3 "öncelik Listing'e bağlı görseller;
	kalanının SEO değeri yok").
	"""
	_guard()
	from tradehub_core.media import seo_audit

	urls = frappe.parse_json(file_urls) if isinstance(file_urls, str) else file_urls
	if urls:
		# Açıkça adres verildiyse sayfalama/önbellek yok: çağıran ne istediğini
		# biliyor (ör. tek ürünün görselleri). `primary_urls` yine de kurulur —
		# yoksa aynı primary görsel scope görünümünde lcp_candidate_unoptimized
		# taşırken tek-dosya denetiminde bulgu sessizce kaybolur (final review).
		temiz = [(u or "").split("?")[0] for u in urls if u]
		return seo_audit.audit_batch(urls, deep=bool(int(deep)), primary_urls=_primary_urls_for(temiz))

	adaylar, primary_urls = _seo_audit_adaylari(scope, limit)
	sonuc = seo_audit.audit_scope(
		adaylar,
		deep=bool(int(deep)),
		cache_key=f"{scope}:{int(deep)}:{len(adaylar)}",
		refresh=bool(int(refresh)),
		primary_urls=primary_urls,
	)
	return seo_audit.paginate(sonuc, page=page, page_size=page_size, code=code, query=q)


def _primary_urls_for(urls: list[str]) -> set[str]:
	"""`urls` içindeki adreslerden hangileri bir `Listing.primary_image`
	(storefront_visible=1) — CWV tasarımı C5, `lcp_candidate_unoptimized` bu
	kümeyi kullanır. TEK `get_all` sorgusuyla kurulur (N+1 yasak); hem scope
	taramasında (`_seo_audit_adaylari`) hem açık `file_urls` denetiminde
	(`audit_media_seo`) aynı yardımcı kullanılır — kopyalama yok."""
	if not urls:
		return set()
	return {
		r["primary_image"]
		for r in frappe.get_all(
			"Listing",
			filters={"primary_image": ["in", urls], "storefront_visible": 1},
			fields=["primary_image"],
			limit_page_length=0,
		)
		if r.get("primary_image")
	}


def _seo_audit_adaylari(scope: str, limit: int) -> tuple[list[str], set[str]]:
	"""Denetlenecek adresler — kapsam kuralına göre. `(urls, primary_urls)` döner.

	`primary_urls` — CWV tasarımı C5: `urls` içindeki adreslerden hangileri
	bir `Listing.primary_image` (storefront_visible=1) — `lcp_candidate_
	unoptimized` bu kümeyi kullanır. Her üç scope'ta da TEK ek `get_all`
	sorgusuyla kurulur (N+1 yasak); `urls` zaten kapsam sınırıyla küçük
	(≤20.000).
	"""
	# Sınır kapsamın kendisinden geliyor (katalog 1.983, tümü 3.267); 200'lük
	# eski tavan ekranın yalnız küçük bir dilimi göstermesine yol açıyordu.
	sinir = min(20000, max(1, int(limit or 5000)))
	if scope == "catalog":
		# Sorgu ÜRÜN tarafından başlar, dosya tarafından değil. Tersi ölçüldü
		# (21 Ağu): her `File` satırı için iki EXISTS alt sorgusu — 5.336
		# dosyada **5,73 s**. Ürün tarafı zaten küçük (~2.000 adres), üstelik
		# `LIKE '/files/%'` ile dış/boş adresler daha okumadan eleniyor.
		satirlar = frappe.db.sql(
			"""
			SELECT DISTINCT img FROM (
				SELECT l.primary_image AS img
				FROM `tabListing` l
				WHERE l.storefront_visible = 1 AND l.primary_image LIKE '/files/%%'
				UNION
				SELECT li.image AS img
				FROM `tabListing Image` li
				JOIN `tabListing` l2 ON l2.name = li.parent
				WHERE l2.storefront_visible = 1 AND li.image LIKE '/files/%%'
			) k
			LIMIT %s
			""",
			(sinir,),
		)
		urls = [r[0] for r in satirlar]
	else:
		sira = "creation desc" if scope == "recent" else "file_name asc"
		urls = [
			r["file_url"]
			for r in frappe.get_all(
				"File",
				filters={"is_folder": 0, "is_private": 0},
				fields=["file_url"],
				order_by=sira,
				limit_page_length=sinir,
			)
			if r.get("file_url")
		]

	if not urls:
		return urls, set()
	# Katalog scope'ta bu sorgu, yukarıdaki UNION'un ilk bacağıyla örtüşen bir
	# doğrulamayı tekrar eder ama primary/galeri ayrımını TEK ek sorguyla
	# (recent/all ile aynı desen) kurmak, UNION'u iki ayrı SQL'e bölmekten
	# daha basit ve N+1 riski taşımıyor (tasarım C5).
	return urls, _primary_urls_for(urls)


@frappe.whitelist(methods=["POST"])
def backfill_media_dimensions(limit: int = 500) -> dict:
	"""Görsellerin gerçek çözünürlüğünü doldur — CLS düzeltmesinin ön koşulu."""
	_guard()
	from tradehub_core.media import seo_generate

	return seo_generate.backfill_dimensions(limit=limit)


@frappe.whitelist(methods=["POST"])
def start_rendition_backfill(limit: int = 100) -> dict:
	"""Güncel merdiveni olmayan vitrin görsellerini `long` kuyruğa al."""
	_guard()
	from tradehub_core.media import pipeline_bridge

	return pipeline_bridge.enqueue_catalog_backfill(limit=int(limit or 100))


@frappe.whitelist()
def get_rendition_backfill_status() -> dict:
	"""Medya SEO ekranı için katalog/kuyruk ilerlemesi."""
	_guard()
	from tradehub_core.media import pipeline_bridge

	return pipeline_bridge.rendition_backfill_status()


@frappe.whitelist(methods=["POST"])
def retry_failed_renditions(limit: int = 50) -> dict:
	"""Başarısız rendition işlerini kontrollü yeniden dene."""
	_guard()
	from tradehub_core.media import pipeline_bridge

	return pipeline_bridge.retry_failed_renditions(limit=int(limit or 50))


@frappe.whitelist(methods=["POST"])
def regenerate_video_poster(file_url: str) -> dict:
	"""Posteri sil ve yeniden üretim işini kuyruğa at (yalnız System Manager)."""
	_guard_destructive()
	from tradehub_core.media import video_poster

	adlar = frappe.get_all("File", filters={"file_url": file_url}, pluck="name")
	if not adlar:
		frappe.throw(_("Dosya bulunamadı."))
	# `video_poster.generate` idempotent: bir kardeş kayıtta poster varsa onu
	# diğerlerine kopyalayıp döner (0827db2). Yeniden üretim tetiklemek için
	# TÜM kardeş kayıtları aynı anda boşaltmak gerekiyor — tek kaydı temizlemek
	# generate'in kopyalama dalını tetikler ve eski poster geri yazılır.
	frappe.db.set_value("File", {"name": ["in", adlar]}, "th_media_poster_url", "", update_modified=False)
	frappe.enqueue(
		"tradehub_core.media.video_poster.generate",
		queue="media-maint",
		timeout=300,
		file_url=file_url,
		enqueue_after_commit=True,
	)
	return {"queued": True}


@frappe.whitelist(methods=["POST"])
def upload_video_captions(file_url: str, vtt_content: str) -> dict:
	"""WebVTT altyazı içeriğini `File` olarak kaydet ve videoya bağla."""
	_guard()
	from tradehub_core.media import seo, upload_policy

	icerik = (vtt_content or "").strip()
	icerik = icerik.lstrip("﻿")  # BOM toleransı — geçerli WebVTT bazen BOM'lu gelir
	if not icerik.startswith("WEBVTT"):
		frappe.throw(_("Geçersiz WebVTT: dosya WEBVTT ile başlamalı."))
	if upload_policy.contains_dangerous(icerik):
		# `startswith("WEBVTT")` yalnız öneke bakar — gövdenin ortasına gömülü
		# `<script>` vb. bundan sızar (derin denetim yalnız IMAGE_KINDS'ta
		# çalışıyor, VTT metin gövdesini taramıyor). Aynı işaret kümesi burada
		# tüm metin üzerinde yeniden kullanılıyor (Görev 7 düzeltme turu 1).
		frappe.throw(_("Altyazı içeriğinde izin verilmeyen işaretleme var."))
	if len(icerik.encode()) > 1024 * 1024:
		frappe.throw(_("Altyazı 1 MB sınırını aşıyor."))
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		frappe.throw(_("Dosya bulunamadı."))
	vtt = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"captions-{name}.vtt",
			"is_private": 0,
			"content": icerik.encode(),
		}
	).insert(ignore_permissions=True)  # sistem yazımı; yetki üstte _guard()
	seo.set_asset_fields(file_url, {"captions_url": vtt.file_url})
	return {"captions_url": vtt.file_url}


@frappe.whitelist(methods=["POST"])
def change_watch_slug(file_url: str, slug: str) -> dict:
	"""İzleme sayfası (`/medya/v/<slug>`) slug'ını panelden bilinçli değiştir.

	İş mantığı `watch_slug.change_slug`'da: geçersiz slug `frappe.throw` ile
	reddedilir, eski adres 301 ile yeniye köprülenir, zincir çökertme + döngü
	temizliği oradadır — burada TEKRARLANMAZ, yalnız yetki + zarf var (dosya
	başlığındaki "iş mantığı karışmasın" kuralı).
	"""
	_guard()
	from tradehub_core.media import watch_slug

	if not file_url:
		frappe.throw(_("Dosya adresi zorunlu."))
	yeni_slug = watch_slug.change_slug(file_url, slug)
	return {"slug": yeni_slug, "watchUrl": watch_slug.watch_url(yeni_slug)}
