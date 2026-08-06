"""Medya envanteri + optimizasyon — HTTP yüzeyi.

**Bu dosyada görsel işleme kodu YOKTUR.** Endpoint'in işi yetki kontrolü, parametre
doğrulama ve kuyruğa atmaktır; iş `tradehub_core/media/` paketinde. Aynı hatayı
`bulk_import`'ta yapıp iş mantığını API dosyasına karıştırdık, tekrarlanmıyor.

Yalnız admin: pazaryeri sahibinin sitedeki tüm görselleri tek yerden görmesi ve
optimize etmesi için. Satıcı self-service kapsam dışı (GORSEL-OPTIMIZASYON.md §6).
"""

from __future__ import annotations

import frappe
from frappe import _

from tradehub_core.media import archive, inventory, presets, runner, trash, usage

ALLOWED_ROLES: tuple[str, ...] = ("System Manager", "Marketplace Admin")

# Geri alınamaz işlemler yalnız en yüksek role açık. Arşiv silindikten sonra
# optimize edilmiş görsellerin orijinali sistemde kalmıyor — bu yetkiyi
# `Marketplace Admin` seviyesine açmak geri dönüşü olmayan bir riski yayar.
DESTRUCTIVE_ROLES: tuple[str, ...] = ("System Manager",)

# Tek seferde kuyruğa alınabilecek azami dosya — kazara "hepsini" tetiklemeye karşı.
MAX_BATCH: int = 2000


def _guard() -> None:
	frappe.only_for(list(ALLOWED_ROLES))


def _guard_destructive() -> None:
	frappe.only_for(list(DESTRUCTIVE_ROLES))


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
	return {
		"total": len(urls),
		"by_verdict": counts,
		"in_use": counts.get("in_use", 0),
		# Kullanımdakilerin kaç yerde geçtiği — "5 üründe kullanılıyor" uyarısı için.
		"live_places": sum(live.get(u, 0) for u in urls if vmap.get(u) == "in_use"),
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
		names = inventory.optimized_file_names(
			search=(search or "").strip(), min_bytes=int(min_bytes or 0)
		)
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
def trash_files(file_urls: str | list[str] | None = None, force: int = 0) -> dict:
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
			r = trash.move_to_trash(u, force=bool(int(force or 0)))
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
def delete_trashed(file_urls: str | list[str] | None = None) -> dict:
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
			r = trash.delete_permanently(u)
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
	return trash.purge_expired(retention_days=days)


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
	days = presets.ARCHIVE_RETENTION_DAYS if older_than_days is None or int(older_than_days) < 0 else int(older_than_days)
	result = archive.purge_expired(retention_days=days)
	frappe.logger("media").info(
		f"archive purge: days={days} deleted={result['deleted']} freed={result['freed_bytes']}"
	)
	return result


@frappe.whitelist()
def get_restorable_count(search: str = "", min_bytes: int = 0) -> dict:
	"""Filtreye uyan kaç dosya geri alınabilir — onay ekranı için."""
	_guard()
	names = inventory.optimized_file_names(
		search=(search or "").strip(), min_bytes=int(min_bytes or 0)
	)
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
