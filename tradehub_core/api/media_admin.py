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

from tradehub_core.media import access_level, archive, audit, inventory, presets, refs, runner, trash, usage

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
	days = presets.ARCHIVE_RETENTION_DAYS if older_than_days is None or int(older_than_days) < 0 else int(older_than_days)
	result = archive.purge_expired(retention_days=days, trigger="manual")
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
	cols = ["timestamp", "action", "decision", "severity", "actor", "tenant", "object_name", "ip_address", "context"]
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
