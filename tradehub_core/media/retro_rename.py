"""Medya retro-rename — eski tahmin edilebilir adların içerik-adresli ada taşınması.

Spec: docs/superpowers/specs/2026-08-21-medya-retro-rename-design.md

Üç aşama: `plan()` (salt okunur rapor) → `run_job()` (kuyruk; dosya başına
disk `os.replace` → `tabFile.file_url` → `refs.retarget` → `Media URL Redirect`
→ commit; hata → rollback + ters taşıma) → `run_rollback()` (job_key'in
satırlarını ters oynatır). Şablon `media/access_level.py::set_level`.

İdempotent: `is_legacy_name` yeni adı tanımaz → ikinci koşu aday bulmaz.
"""

from __future__ import annotations

import hashlib
import os
import re

import frappe
from frappe import _
from frappe.utils import add_days, get_files_path, now_datetime

from tradehub_core.media import audit, naming, refs

PUBLIC_PREFIX = "/files/"
MEDIA_PREFIX = "/files/media/"
REDIRECT_TTL_DAYS = 90
ERROR_RATE_STOP = 0.02
DEFAULT_BATCH = 200
PLAN_ITEM_LIMIT = 5000
PROGRESS_TTL = 3600

_HASHED_SHARDED = re.compile(r"^/files/[0-9a-f]{2}/[0-9a-f]{32}\.[a-z0-9]+$")


def is_legacy_name(file_url: str) -> bool:
	"""`/files/` altında, `/files/media/` dışında, hash+shard biçiminde OLMAYAN adres."""
	url = (file_url or "").split("?")[0]
	if not url.startswith(PUBLIC_PREFIX) or url.startswith(MEDIA_PREFIX):
		return False
	if ".." in url or url.endswith("/"):
		return False
	return not _HASHED_SHARDED.match(url)


def _disk_path(file_url: str) -> str:
	rel = file_url[len(PUBLIC_PREFIX) :]
	return os.path.join(get_files_path(is_private=0), rel)


def target_url(file_url: str) -> str:
	"""Diskteki GÜNCEL bayt'lardan hedef adres. Dosya yoksa `FileNotFoundError`."""
	path = _disk_path(file_url)
	with open(path, "rb") as f:
		content = f.read()
	hashed = naming._hashed_name(os.path.basename(file_url), content)
	return f"{PUBLIC_PREFIX}{naming._shard(hashed)}/{hashed}"


def _content_sha(path: str) -> str:
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for chunk in iter(lambda: f.read(1 << 20), b""):
			h.update(chunk)
	return h.hexdigest()


def legacy_urls() -> list[str]:
	"""`tabFile`'daki distinct public, hash-dışı adresler (scripts/media_stats.py ile aynı SQL)."""
	rows = frappe.db.sql(
		"""select file_url from `tabFile`
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			  and left(file_url,13) <> '/files/media/'
			  and substring_index(substring_index(file_url,'/',-1),'.',1) not regexp '^[0-9a-f]{32}$'
			group by file_url order by file_url""",
		as_list=True,
	)
	return [r[0] for r in rows if is_legacy_name(r[0])]


def _ref_counts(url: str) -> tuple[int, int, int]:
	exact = readonly = embedded = 0
	for ref in refs.find(url):
		if ref["readonly"]:
			readonly += 1
		elif ref["exact"]:
			exact += 1
		else:
			embedded += 1
	return exact, readonly, embedded


def _inspect(url: str) -> dict:
	path = _disk_path(url)
	item = {
		"source_url": url,
		"target_url": None,
		"file_rows": frappe.db.count("File", {"file_url": url}),
		"refs_exact": 0,
		"refs_readonly": 0,
		"refs_embedded": 0,
		"orphan": False,
		"disk_missing": not os.path.isfile(path),
		"collision": False,
	}
	item["refs_exact"], item["refs_readonly"], item["refs_embedded"] = _ref_counts(url)
	item["orphan"] = not (item["refs_exact"] or item["refs_readonly"] or item["refs_embedded"])
	if item["disk_missing"]:
		return item
	item["target_url"] = target_url(url)
	hedef = _disk_path(item["target_url"])
	if os.path.isfile(hedef) and _content_sha(hedef) != _content_sha(path):
		item["collision"] = True
	return item


def plan(limit: int | None = None) -> dict:
	"""Salt okunur rapor. Hiçbir şey yazmaz.

	Sayaçlar (`renamable`, `orphans`, ...) HER ZAMAN tüm aday listesi üzerinden
	hesaplanır — `limit` yalnız dönen `items` listesinin boyutunu sınırlar.
	Aksi hâlde `truncated=True` olduğunda sayaçlar eksik raporlanırdı.
	`limit=0` → boş `items`, ama sayaçlar yine tam.
	"""
	urls = legacy_urls()
	cap = PLAN_ITEM_LIMIT if limit is None else min(max(0, limit), PLAN_ITEM_LIMIT)
	all_items = [_inspect(u) for u in urls]
	out = {
		"total": len(urls),
		"truncated": len(urls) > cap,
		"renamable": 0,
		"orphans": 0,
		"disk_missing": 0,
		"collisions": 0,
		"refs_exact": 0,
		"refs_readonly": 0,
		"refs_embedded": 0,
		"file_rows": 0,
		"items": all_items[:cap],
	}
	for it in all_items:
		out["orphans"] += int(it["orphan"])
		out["disk_missing"] += int(it["disk_missing"])
		out["collisions"] += int(it["collision"])
		out["refs_exact"] += it["refs_exact"]
		out["refs_readonly"] += it["refs_readonly"]
		out["refs_embedded"] += it["refs_embedded"]
		out["file_rows"] += it["file_rows"]
		if not it["disk_missing"] and not it["collision"]:
			out["renamable"] += 1
	return out


# ── İş durumu (ilerleme + durdurma bayrağı) ─────────────────────────────
# Aynı anda tek retro-rename işi çalışmalı: iş anahtarı Redis'te tutulur,
# çağıran uç (`api/media_admin.py`) yeni iş kuyruğa vermeden önce bu anahtara
# bakar. Kilidi worker'ın kendisi koyar/kaldırır — kuyruk gecikmesinde bile
# "çalışıyor" görünmemesi için TTL'li.
ACTIVE_KEY = "tradehub:retro_rename:active"


def progress_key(job_key: str) -> str:
	return f"tradehub_media_retro:{job_key}"


def _stop_key(job_key: str) -> str:
	return f"tradehub_media_retro_stop:{job_key}"


def read_progress(job_key: str) -> dict:
	return frappe.cache.get_value(progress_key(job_key)) or {"state": "not_found"}


def _write_progress(job_key: str, payload: dict) -> None:
	frappe.cache.set_value(progress_key(job_key), payload, expires_in_sec=PROGRESS_TTL)


def request_stop(job_key: str) -> None:
	"""Durdurma isteği — worker bir sonraki batch sınırında görür."""
	frappe.cache.set_value(_stop_key(job_key), 1, expires_in_sec=PROGRESS_TTL)


def _stop_requested(job_key: str) -> bool:
	return bool(frappe.cache.get_value(_stop_key(job_key)))


def _new_state(total: int, mode: str, dry_run: bool, expires_at=None) -> dict:
	return {
		"state": "running",
		"mode": mode,
		"dry_run": bool(dry_run),
		"total": total,
		"processed": 0,
		"renamed": 0,
		"skipped": 0,
		"errors": 0,
		"skip_reasons": {},
		"expires_at": str(expires_at) if expires_at else None,
		"message": "",
	}


def _skip(reason: str, **extra) -> dict:
	return {
		"status": "skipped",
		"reason": reason,
		"target_url": None,
		"refs_updated": 0,
		"refs_skipped": 0,
		**extra,
	}


def _invalidate_url_caches(*urls: str) -> None:
	"""`file_isolation._url_is_ambiguous` cache'i URL başına anahtarlanmış.

	Taşımadan sonra eski adreste hiç satır kalmaz, yeni adreste N satır olur —
	ikisinin de cache'lenmiş cevabı artık yanlış. Ucuz bir silme; bayat cevap
	private teslimatta yanlış karar demek.
	"""
	for url in urls:
		if url:
			frappe.cache.delete_value(f"tradehub:file_url_ambiguous:{url}")


def rename_one(url: str, job_key: str, expires_at, *, dry_run: bool = False) -> dict:
	"""Tek dosya: disk → `File` → referanslar → 301 satırı → commit.

	Sıra `media/access_level.py::set_level` ile aynı gerekçeye dayanır: geri
	alınabilir TEK adım disk taşıması, o yüzden önce o yapılır; DB adımlarından
	biri patlarsa transaction geri alınır VE dosya eski adına geri taşınır.
	Aksi hâlde dosya yeni adında, `File.file_url` eski adı gösterir — kırık
	referans.

	Returns:
	    `{status: renamed|skipped|error, reason, target_url, refs_updated, refs_skipped}`
	"""
	from tradehub_core.media import av

	if not is_legacy_name(url):
		return _skip("not_legacy")
	old_path = _disk_path(url)
	if not os.path.isfile(old_path):
		# İkinci koşuda buraya düşülür (ad artık hash'li, dosya eski adında yok)
		# — idempotentliğin ikinci savunma hattı.
		return _skip("disk_missing")
	# Tarama/karantina dosyayı canlı ağacın DIŞINA taşımış olabilir (TUR-125);
	# iki mekanizma aynı dosyayı taşımak için yarışmamalı (access_level dersi).
	if av.in_quarantine(url) or av.in_hold(url):
		return _skip("quarantined")

	# Disk okuma/taşıma DOSYA BAŞINA hata olarak raporlanır, işi düşürmez:
	# `isfile` ile `open` arasında dosya taşınmış olabilir (tarama/karantina
	# akışı dosyaları canlı ağacın dışına taşıyor) ya da izin/G-Ç hatası
	# çıkabilir. 15 bin dosyalık bir işin tek `EACCES` yüzünden 4.000. dosyada
	# ölmesi yerine sayaca "error" yazılır; eşiği aşarsa `_run_job` zaten durur.
	try:
		new_url = target_url(url)
		new_path = _disk_path(new_url)
		dedup = False
		if os.path.isfile(new_path):
			if _content_sha(new_path) != _content_sha(old_path):
				# Aynı hedef ad, FARKLI içerik: hash çakışması ya da yarım kalmış
				# bir taşıma. Üzerine yazmak veri kaybıdır — operatöre bırakılır.
				return _skip("collision", target_url=new_url)
			dedup = True
	except OSError:
		frappe.log_error(
			title=f"Retro-rename disk read failed for {url}",
			message=frappe.get_traceback(with_context=True),
		)
		return {
			"status": "error",
			"reason": "disk_read",
			"target_url": None,
			"refs_updated": 0,
			"refs_skipped": 0,
		}
	if dry_run:
		return {
			"status": "renamed",
			"reason": "dry_run",
			"target_url": new_url,
			"refs_updated": 0,
			"refs_skipped": 0,
		}

	# DEDUP dalında diske burada DOKUNULMAZ. Hedefte bit-birebir aynı içerik
	# zaten var, yani DB'nin doğru olması için eski kopyanın gitmesi gerekmiyor;
	# fazlalık kopya commit'ten SONRA silinir. Brief'in "önce disk" sırası
	# taşıma (`os.replace`) için doğru — geri alınabilir tek adım odur — ama
	# silme geri alınamaz: eski adı silip DB patlarsa geri getirmenin tek yolu
	# hedefi eski ada KOPYALAMAKTI ve o kopyalama da (disk dolu, izin) patlarsa
	# `File` satırları diskte olmayan bir adresi gösterir → kırık görsel.
	# Sırayı çevirince bu başarısızlık modu tamamen ortadan kalkıyor.
	try:
		frappe.create_folder(os.path.dirname(new_path))
		if not dedup:
			os.replace(old_path, new_path)
	except OSError:
		# Henüz hiçbir DB yazımı yok; geri alınacak bir şey de yok.
		frappe.log_error(
			title=f"Retro-rename disk move failed for {url}",
			message=frappe.get_traceback(with_context=True),
		)
		return {
			"status": "error",
			"reason": "disk_move",
			"target_url": new_url,
			"refs_updated": 0,
			"refs_skipped": 0,
		}

	try:
		# Rollback'in "bu satırın kaç `File` kaydı vardı" sorusuna cevabı;
		# güncellemeden ÖNCE ölçülmeli.
		file_rows = frappe.db.count("File", {"file_url": url})
		frappe.db.set_value("File", {"file_url": url}, {"file_url": new_url}, update_modified=False)
		ref_result = refs.retarget(url, new_url)
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": url,
				"target_url": new_url,
				"job_key": job_key,
				"expires_at": expires_at,
				"file_rows": file_rows,
			}
		).insert(ignore_permissions=True)  # sistem işi; çağıran uç System Manager kapısından geçti
		_invalidate_url_caches(url, new_url)
	except Exception:
		# `source_url` tekil: yarım kalmış bir koşudan satır kaldıysa insert
		# burada patlar ve dosya eski adına geri döner — sessizce üzerine
		# yazmak, hangi hedefe yönlendirildiği bilinmeyen bir 301 bırakırdı.
		frappe.db.rollback()
		if not dedup:
			# Dedup dalında geri alınacak bir disk adımı YOK (yukarıdaki nota bak).
			try:
				os.replace(new_path, old_path)
			except OSError:
				frappe.log_error(
					title=f"Retro-rename disk revert failed for {url}",
					message=frappe.get_traceback(with_context=True),
				)
		frappe.log_error(
			title=f"Retro-rename failed for {url}", message=frappe.get_traceback(with_context=True)
		)
		return {
			"status": "error",
			"reason": "exception",
			"target_url": new_url,
			"refs_updated": 0,
			"refs_skipped": 0,
		}

	frappe.db.commit()
	if dedup:
		# Artık fazlalık: DB kalıcı olarak hedefi gösteriyor, içerik hedefte
		# duruyor. Silme patlarsa yalnız bir artık dosya kalır (kayıp yok) —
		# bu yüzden işin sonucunu etkilemez, sadece loglanır.
		try:
			os.remove(old_path)
		except OSError:
			frappe.log_error(
				title=f"Retro-rename: dedup artığı silinemedi {url}",
				message=frappe.get_traceback(with_context=True),
			)
	audit.log_media_event(
		action=audit.ACTION_RETRO_RENAME,
		file_url=new_url,
		context={
			"operation": "retro_rename",
			"old_url": url,
			"job_key": job_key,
			"refs_updated": ref_result["total"],
			"refs_skipped": len(ref_result["skipped"]),
			"dedup": dedup,
		},
	)
	return {
		"status": "renamed",
		"reason": "dedup" if dedup else "",
		"target_url": new_url,
		"refs_updated": ref_result["total"],
		"refs_skipped": len(ref_result["skipped"]),
	}


def run_job(job_key: str, dry_run: int = 0, batch_size: int = DEFAULT_BATCH) -> None:
	"""Kuyruk girişi. Her batch sınırında durdurma bayrağı ve hata oranı kontrol edilir."""
	frappe.cache.set_value(ACTIVE_KEY, job_key, expires_in_sec=PROGRESS_TTL)
	try:
		_run_job(job_key, bool(dry_run), max(1, int(batch_size or DEFAULT_BATCH)))
	except Exception:
		durum = read_progress(job_key)
		if durum.get("state") == "not_found":
			# Aday listesi alınamadan patladı — panelin okuyacağı bir iskelet bırak.
			durum = _new_state(0, "rename", bool(dry_run))
		durum["state"] = "error"
		durum["message"] = _("İşlem tamamlanamadı.")
		_write_progress(job_key, durum)
		frappe.log_error(
			title=f"Retro-rename job failed: {job_key}", message=frappe.get_traceback(with_context=True)
		)
	finally:
		frappe.cache.delete_value(ACTIVE_KEY)
		# Bayrak tüketildi: aynı `job_key` yeniden kuyruğa verilirse (operatör
		# tekrar denemesi) eski durdurma isteği yeni koşuyu anında öldürmesin.
		frappe.cache.delete_value(_stop_key(job_key))


def _run_job(job_key: str, dry_run: bool, batch_size: int) -> None:
	urls = legacy_urls()
	expires_at = add_days(now_datetime(), REDIRECT_TTL_DAYS)
	durum = _new_state(len(urls), "rename", dry_run, expires_at)
	_write_progress(job_key, durum)

	for i, url in enumerate(urls):
		# `i == 0` de bir batch sınırıdır: iş kuyrukta beklerken verilen
		# durdurma isteği İLK dosyaya dokunmadan görülmeli (aksi hâlde
		# batch_size=1 ile ilk dosya her zaman taşınırdı).
		if i % batch_size == 0:
			if _stop_requested(job_key):
				durum["state"] = "stopped"
				durum["message"] = _("Operatör durdurdu.")
				_write_progress(job_key, durum)
				break
			if durum["processed"] and durum["errors"] / durum["processed"] > ERROR_RATE_STOP:
				durum["state"] = "partial"
				durum["message"] = _("Hata oranı eşiği aşıldı; iş durduruldu.")
				_write_progress(job_key, durum)
				break
		out = rename_one(url, job_key, expires_at, dry_run=dry_run)
		durum["processed"] += 1
		if out["status"] == "renamed":
			durum["renamed"] += 1
		elif out["status"] == "skipped":
			durum["skipped"] += 1
			durum["skip_reasons"][out["reason"]] = durum["skip_reasons"].get(out["reason"], 0) + 1
		else:
			durum["errors"] += 1
		if durum["processed"] % 25 == 0:
			_write_progress(job_key, durum)
	else:
		durum["state"] = "partial" if durum["errors"] else "completed"

	_write_progress(job_key, durum)
	audit.log_media_batch(action=audit.ACTION_RETRO_RENAME, job_key=job_key, summary=dict(durum))


def run_rollback(job_key: str, rollback_key: str) -> None:
	"""`job_key` ile yazılmış yönlendirme satırlarını ters oynatır."""
	# Sistem işi: satırları iş anahtarına göre okur, kullanıcı verisi değil.
	rows = frappe.get_all(
		"Media URL Redirect",
		filters={"job_key": job_key},
		fields=["name", "source_url", "target_url", "file_rows"],
		order_by="creation desc",
	)
	durum = _new_state(len(rows), "rollback", False)
	_write_progress(rollback_key, durum)
	frappe.cache.set_value(ACTIVE_KEY, rollback_key, expires_in_sec=PROGRESS_TTL)
	try:
		for row in rows:
			ok = _rollback_one(row)
			durum["processed"] += 1
			durum["renamed" if ok else "errors"] += 1
			if durum["processed"] % 25 == 0:
				_write_progress(rollback_key, durum)
		durum["state"] = "partial" if durum["errors"] else "completed"
	finally:
		frappe.cache.delete_value(ACTIVE_KEY)
	_write_progress(rollback_key, durum)
	audit.log_media_batch(action=audit.ACTION_RETRO_ROLLBACK, job_key=job_key, summary=dict(durum))


def _rollback_one(row) -> bool:
	new_path = _disk_path(row.target_url)
	old_path = _disk_path(row.source_url)
	if not os.path.isfile(new_path):
		frappe.log_error(title=f"Retro-rollback: hedef diskte yok {row.target_url}")
		return False
	# Aynı hedefi paylaşan başka yönlendirme satırı varsa (dedup) dosya
	# KOPYALANIR, taşınmaz: hedef hâlâ diğer eski adın geri dönüş kaynağı.
	# Sırayla ilerledikçe sayaç düşer, en son satır dosyayı gerçekten taşır.
	paylasan = frappe.db.count("Media URL Redirect", {"target_url": row.target_url}) > 1
	frappe.create_folder(os.path.dirname(old_path))
	if paylasan:
		with open(new_path, "rb") as src, open(old_path, "wb") as dst:
			dst.write(src.read())
	else:
		os.replace(new_path, old_path)
	try:
		# Dedup'ta birden çok eski ad aynı hedefe gitmiş olabilir — yalnız bu
		# satırın kendi `File` kayıtları kadarı geri çevrilir (`file_rows`).
		# `file_rows == 0` ise taşımada hiç `File` satırı güncellenmemiştir;
		# rollback'te de hiçbirine dokunulmaz.
		adlar = frappe.get_all(
			"File", filters={"file_url": row.target_url}, pluck="name", order_by="creation asc"
		)
		for ad in adlar[: int(row.file_rows or 0)]:
			frappe.db.set_value("File", ad, "file_url", row.source_url, update_modified=False)
		refs.retarget(row.target_url, row.source_url)
		frappe.delete_doc("Media URL Redirect", row.name, ignore_permissions=True, force=True)
		_invalidate_url_caches(row.source_url, row.target_url)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		try:
			if paylasan:
				os.remove(old_path)
			else:
				os.replace(old_path, new_path)
		except OSError:
			frappe.log_error(
				title=f"Retro-rollback disk revert failed {row.source_url}",
				message=frappe.get_traceback(with_context=True),
			)
		frappe.log_error(
			title=f"Retro-rollback failed {row.source_url}", message=frappe.get_traceback(with_context=True)
		)
		return False
	return True
