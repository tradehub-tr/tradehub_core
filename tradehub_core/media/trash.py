"""Çöp kutusu — silmeden önce 30 gün bekleyen ara durak.

Doğrudan silme yok. Bir dosya "çöpe taşındığında":

  1. Fiziksel dosya `private/media_trash/` altına taşınır → siteden erişilemez
     hâle gelir (public URL 404 döner), yani gerçekten silinmiş gibi davranır
  2. `File` kayıtları SİLİNMEZ, `th_trashed_at` damgası basılır
  3. `TRASH_RETENTION_DAYS` gün sonra günlük job hem dosyayı hem kayıtları siler

Neden bu sıra: "kullanılmıyor" taraması yalnız veritabanını kapsıyor. Frontend
kodunda sabit yazılmış ya da dışarıdan link verilmiş bir görsel taramada
"kullanılmıyor" görünür ama sitede kırılır. Çöp kutusu bu hatayı geri
alınabilir kılar — 30 gün içinde fark edilirse tek tıkla geri gelir.

Aynı gerekçe optimizasyon arşivinde de geçerli (`archive.py`); ikisi ayrı
klasörlerde durur çünkü biri "eski hâli", diğeri "dosyanın kendisi".
"""

from __future__ import annotations

import os
import shutil
import time

import frappe

from tradehub_core.media import audit, refs, states
from tradehub_core.media.presets import EXCLUDED_DOCTYPES

TRASH_DIRNAME: str = "media_trash"
TRASH_RETENTION_DAYS: int = 30

# Çöpe taşınabilecek kullanım kararları. `in_use` asla — sitede kırılma yaratır.
TRASHABLE_VERDICTS: frozenset[str] = frozenset({"unused", "history_only"})


def _root() -> str:
	return frappe.get_site_path("private", TRASH_DIRNAME)


def _relative(file_url: str) -> str:
	url = (file_url or "").split("?")[0]
	if not url.startswith("/files/") or ".." in url:
		frappe.throw(frappe._("Geçersiz dosya yolu: {0}").format(file_url))
	return url[len("/files/") :]


def _trash_path(file_url: str) -> str:
	root = os.path.realpath(_root())
	target = os.path.realpath(os.path.join(root, _relative(file_url)))
	if not target.startswith(root + os.sep):
		frappe.throw(frappe._("Çöp yolu kök dizinin dışında: {0}").format(file_url))
	return target


def _live_path(file_url: str) -> str:
	root = os.path.realpath(frappe.get_site_path("public", "files"))
	target = os.path.realpath(os.path.join(root, _relative(file_url)))
	if not target.startswith(root + os.sep):
		frappe.throw(frappe._("Dosya yolu kök dizinin dışında: {0}").format(file_url))
	return target


def _assert_trashable(file_url: str, force: bool = False) -> None:
	"""Kapsam ve kullanım kontrolü — istemciden gelen listeye güvenme.

	`force=True` yalnız kullanım engelini kaldırır: kullanıcı ekranda "bu dosya
	{n} üründe kullanılıyor, görselleri kırılacak" uyarısını görüp onayladığında
	gelir. Kapsam engelleri (private, hassas doctype) `force` ile de aşılamaz —
	onlar gizlilik kararı, kullanıcı tercihi değil.
	"""
	rows = frappe.get_all(
		"File",
		filters={"file_url": file_url},
		fields=["is_private", "attached_to_doctype", "content_hash"],
		limit_page_length=0,
	)
	if not rows:
		frappe.throw(frappe._("Dosya kaydı bulunamadı: {0}").format(file_url))
	if any(r.get("is_private") for r in rows):
		_deny(file_url, "private")
		frappe.throw(frappe._("Private dosya çöpe taşınamaz: {0}").format(file_url))
	if any(r.get("attached_to_doctype") in EXCLUDED_DOCTYPES for r in rows):
		_deny(file_url, "excluded_doctype")
		frappe.throw(frappe._("Kapsam dışı doctype eki çöpe taşınamaz: {0}").format(file_url))

	# İçerik bazlı kontrol — hassas bir belgenin public kopyası olabilir.
	from tradehub_core.media.runner import _has_sensitive_twin

	if any(_has_sensitive_twin(r["content_hash"]) for r in rows if r.get("content_hash")):
		_deny(file_url, "sensitive_content_twin")
		frappe.throw(
			frappe._("Bu dosya hassas bir belgenin kopyası, çöpe taşınamaz: {0}").format(file_url)
		)

	from tradehub_core.media import usage

	if force:
		return

	verdict = usage.verdict_map_all(deep=True).get(file_url)
	if verdict not in TRASHABLE_VERDICTS:
		_deny(file_url, f"in_use:{verdict or 'unknown'}", sensitive=False)
		frappe.throw(
			frappe._("Bu dosya sitede kullanılıyor, çöpe taşınamaz ({0}): {1}").format(
				verdict or "bilinmiyor", file_url
			)
		)


def _deny(file_url: str, reason: str, *, sensitive: bool = True) -> None:
	"""Reddedilen silme isteğini denetime yaz.

	Kapsam engelleri (`private`, `excluded_doctype`, `sensitive_content_twin`)
	`force` ile de aşılamaz; buraya düşen kayıt istemcinin kapsam dışı bir
	dosyayı silmeye çalıştığını gösterir. Bu durumda URL maskelenir — dosya
	zaten panelde görünmemesi gereken bir belge.

	`in_use` farklı: sıradan bir ürün görseli, gizlenecek bir şey yok. Orada
	`sensitive=False` geçilir ki operatör hangi dosyanın silinmek istendiğini
	görebilsin.
	"""
	audit.log_media_event(
		action=audit.ACTION_SCOPE_DENIED,
		file_url=file_url,
		allowed=False,
		reason=reason,
		sensitive=sensitive,
		context={"operation": "trash"},
	)


def move_to_trash(file_url: str, force: bool = False) -> dict:
	"""Dosyayı çöpe taşı — geri alınabilir.

	`force=True` kullanımdaki dosyaya da izin verir; çağıran tarafın kullanıcıya
	sonucu (sitede kırılacak görseller) açıkça göstermiş olması gerekir.
	"""
	_assert_trashable(file_url, force=force)

	src = _live_path(file_url)
	if not os.path.isfile(src):
		frappe.throw(frappe._("Dosya diskte bulunamadı: {0}").format(file_url))

	dst = _trash_path(file_url)
	size = os.path.getsize(src)

	# Önce DB, sonra disk: disk hatasında rollback ile ikisi tek işleme bağlanır
	# (aynı gerekçe `runner.restore_original`'da kayıtlı).
	try:
		frappe.db.set_value(
			"File", {"file_url": file_url}, {"th_trashed_at": frappe.utils.now()}, update_modified=False
		)
		# Damga ile durum aynı transaction'da yazılır; ayrışmaları imkânsız (TUR-138).
		states.transition(file_url, states.STATE_TRASHED)
		os.makedirs(os.path.dirname(dst), exist_ok=True)
		shutil.move(src, dst)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(
			title=f"Trash failed for {file_url}", message=frappe.get_traceback(with_context=True)
		)
		raise

	frappe.db.commit()
	# `force` ayrıca kaydedilir: kullanımdaki bir dosyanın uyarı onaylanarak
	# silinmesi ile kullanılmayan bir dosyanın silinmesi denetimde ayrılmalı.
	audit.log_media_event(
		action=audit.ACTION_TRASH, file_url=file_url, context={"bytes": size, "forced": bool(force)}
	)
	return {"file_url": file_url, "bytes": size}


def restore(file_url: str) -> dict:
	"""Çöpten geri al — dosya yerine döner, damga temizlenir."""
	src = _trash_path(file_url)
	if not os.path.isfile(src):
		frappe.throw(frappe._("Çöpte bulunamadı: {0}").format(file_url))

	dst = _live_path(file_url)
	size = os.path.getsize(src)
	try:
		# Optimize edilmiş dosya çöpten Active'e değil Archived'a döner —
		# orijinali hâlâ arşivde ve geri alınabilir.
		hedef = states.state_after_untrash(file_url)
		frappe.db.set_value(
			"File", {"file_url": file_url}, {"th_trashed_at": None}, update_modified=False
		)
		states.transition(file_url, hedef)
		os.makedirs(os.path.dirname(dst), exist_ok=True)
		shutil.move(src, dst)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(
			title=f"Trash restore failed for {file_url}",
			message=frappe.get_traceback(with_context=True),
		)
		raise

	frappe.db.commit()
	audit.log_media_event(action=audit.ACTION_UNTRASH, file_url=file_url, context={"bytes": size})
	return {"file_url": file_url, "bytes": size}


def delete_permanently(file_url: str) -> dict:
	"""Çöpteki TEK dosyayı kalıcı sil — dosya + tüm `File` kayıtları.

	Yalnız çöpteki dosyalara uygulanır: canlı bir dosyayı buradan silmek
	mümkün değil, önce çöpe taşınması gerekir. Bu iki adımlı akış, tek bir
	yanlış tıklamanın geri dönüşü olmayan sonuç doğurmasını engelliyor.
	"""
	path = _trash_path(file_url)
	if not os.path.isfile(path):
		frappe.throw(frappe._("Çöpte bulunamadı: {0}").format(file_url))

	size = os.path.getsize(path)
	records = frappe.get_all("File", filters={"file_url": file_url}, pluck="name")

	# Referans zinciri: dosya gidince onu gösteren alanlar da temizlenmeli.
	# Aksi hâlde üründe boş bir görsel yuvası kalıyor ve kullanıcı önce o boşluğu
	# silip sonra yeniden yüklemek zorunda kalıyor (ölçüldü).
	temizlik = refs.clear(file_url)

	for name in records:
		frappe.delete_doc("File", name, force=True, ignore_permissions=True, delete_permanently=True)
	os.remove(path)
	frappe.db.commit()
	# Geri dönüşü YOK — HIGH severity ile kaydedilir. Silinen `File` kayıtlarının
	# adları da yazılır; kayıt gittikten sonra tek iz bu olur.
	audit.log_media_event(
		action=audit.ACTION_DELETE,
		file_url=file_url,
		context={
			"bytes": size,
			"records": records,
			"refs_cleared": temizlik["total"],
			"refs_detail": (temizlik["rows_deleted"] + temizlik["fields_cleared"])[:10],
			"refs_skipped": temizlik["skipped"][:10],
		},
	)
	return {
		"file_url": file_url,
		"bytes": size,
		"records": len(records),
		"refs_cleared": temizlik["total"],
	}


def usage_bytes() -> int:
	root = _root()
	if not os.path.isdir(root):
		return 0
	total = 0
	for dirpath, _dirs, files in os.walk(root):
		for name in files:
			try:
				total += os.path.getsize(os.path.join(dirpath, name))
			except OSError:
				continue
	return total


def purge_expired(
	retention_days: int = TRASH_RETENTION_DAYS, trigger: str = "scheduled"
) -> dict:
	"""Süresi dolanları KALICI sil — hem dosya hem `File` kayıtları.

	İki yerden çağrılır ve ikisi farklı işlemdir:

	  scheduled — günlük job, yalnız 30 günü dolanları siler
	  manual    — kullanıcı "Çöpü boşalt" dedi, çöpün TAMAMI hemen silinir

	Denetim kaydında ikisi aynı olay adıyla görünüyordu ve "çöp temizliği"
	ifadesi bakım işi gibi okunuyordu; `trigger` bu ikisini ayırır.
	"""
	root = _root()
	if not os.path.isdir(root):
		return {"deleted": 0, "freed_bytes": 0, "records": 0}

	cutoff = time.time() - retention_days * 86400
	deleted = freed = records = 0
	# Hangi dosyaların silindiği kayda geçmeli. Önce yalnız sayı yazılıyordu ve
	# "çöpü boşalt" sonrası kaybolan dosyayı bulmak için media.trash olaylarını
	# elle karşılaştırmak gerekiyordu (ölçüldü).
	silinenler: list[str] = []
	temizlenen_ref = 0

	for dirpath, _dirs, files in os.walk(root, topdown=False):
		for name in files:
			path = os.path.join(dirpath, name)
			try:
				if os.path.getmtime(path) >= cutoff:
					continue
				rel = os.path.relpath(path, root)
				url = "/files/" + rel.replace(os.sep, "/")
				size = os.path.getsize(path)
				# Referans zinciri: dosya gidince onu gösteren alanlar da
				# temizlenmeli, yoksa üründe boş görsel yuvası kalıyor.
				temizlenen_ref += refs.clear(url)["total"]
				for r in frappe.get_all("File", filters={"file_url": url}, pluck="name"):
					frappe.delete_doc("File", r, force=True, ignore_permissions=True, delete_permanently=True)
					records += 1
				os.remove(path)
				deleted += 1
				freed += size
				silinenler.append(url)
			except Exception:
				frappe.log_error(
					title="Trash purge failed", message=frappe.get_traceback(with_context=True)
				)
				continue

	frappe.db.commit()
	# Zamanlanmış iş — aktörü Administrator görünür. Hiçbir şey silinmediyse de
	# kayıt atılır: "purge çalıştı mı" sorusu denetimden cevaplanabilmeli.
	audit.log_media_batch(
		action=audit.ACTION_PURGE_TRASH,
		summary={
			"trigger": trigger,
			"retention_days": retention_days,
			"deleted": deleted,
			"freed_bytes": freed,
			"records": records,
			"refs_cleared": temizlenen_ref,
			# İlk 50 dosya; tamamı bağlam alanını şişirirdi (5 KB sınırı var).
			"files": silinenler[:50],
			"files_truncated": max(0, len(silinenler) - 50),
		},
	)
	return {
		"deleted": deleted,
		"freed_bytes": freed,
		"records": records,
		"files": silinenler,
		"refs_cleared": temizlenen_ref,
	}
