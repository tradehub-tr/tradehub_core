"""Optimizasyon worker'ı — sırayı kurar, ilerleme yazar, commit'ler.

İş mantığı burada DEĞİL: karar `gates`, dönüşüm `engine`, yedek `archive`,
listeleme `inventory` modüllerinde. Bu dosya yalnız orkestrasyon yapar.

Bu fonksiyonlar **whitelisted değildir** — HTTP'den doğrudan çağrılamaz.
`api/media_admin.py` yetki kontrolünü yapıp `frappe.enqueue` ile buraya devreder.

Neden senkron endpoint yok: HTTP request context'inde `File` yazmak
`MEDYA-BACKEND.md` §7.1'deki 417 EXPECTATION FAILED hatasını tetikliyor. Worker'da
HTTP yanıtı olmadığı için o tuzak yok — tek dosya bile aynı kuyruğa 1 elemanlı
liste olarak gider.
"""

from __future__ import annotations

import os

import frappe

from tradehub_core.media import archive, audit, engine, gates, presets


def progress_key(job_key: str) -> str:
	return f"tradehub_media_optimize:{job_key}"


def read_progress(job_key: str) -> dict:
	return frappe.cache.get_value(progress_key(job_key)) or {"state": "not_found"}


def _write_progress(job_key: str, payload: dict) -> None:
	frappe.cache.set_value(progress_key(job_key), payload, expires_in_sec=presets.PROGRESS_TTL)


def _new_state(total: int, preset: str, dry_run: bool) -> dict:
	return {
		"state": "running",
		"preset": preset,
		"dry_run": bool(dry_run),
		"total": total,
		"processed": 0,
		"optimized": 0,
		"skipped": 0,
		"errors": 0,
		"original_bytes": 0,
		"new_bytes": 0,
		"skip_reasons": {},
		"message": "",
	}


def run_batch(
	file_names: list[str],
	preset: str = presets.DEFAULT_PRESET,
	job_key: str = "",
	dry_run: int = 0,
) -> dict:
	"""Verilen `File` kayıtlarını sırayla işler. Worker girişi.

	`dry_run=1` iken kapılar ve dönüşüm çalışır ama **diske hiçbir şey yazılmaz** —
	beklenen kazancı doğrulamak için (GORSEL-OPTIMIZASYON.md §10.1 Adım 1).
	"""
	cfg = presets.resolve(preset)
	state = _new_state(len(file_names), preset, dry_run)
	_write_progress(job_key, state)

	for index, name in enumerate(file_names, start=1):
		try:
			outcome = _process_one(name, cfg, bool(dry_run))
			state["processed"] += 1
			state["original_bytes"] += outcome.get("original_bytes", 0)
			state["new_bytes"] += outcome.get("new_bytes", 0)
			if outcome["status"] == "optimized":
				state["optimized"] += 1
			else:
				state["skipped"] += 1
				reason = outcome.get("reason") or "unknown"
				state["skip_reasons"][reason] = state["skip_reasons"].get(reason, 0) + 1
		except Exception:
			state["processed"] += 1
			state["errors"] += 1
			# Frappe imzası log_error(title, message) — ters verirsek traceback
			# kaybolur, Error Log'da yalnız başlık kalır ve hata teşhis edilemez.
			frappe.log_error(
				title=f"Media optimize failed for {name}",
				message=frappe.get_traceback(with_context=True),
			)

		if index % presets.COMMIT_EVERY == 0:
			if not dry_run:
				frappe.db.commit()
			_write_progress(job_key, state)

	if not dry_run:
		frappe.db.commit()

	state["state"] = "completed" if not state["errors"] else "partial"
	_write_progress(job_key, state)

	# İş sonunda TEK özet log — 1000 hatada Error Log şişmesin.
	frappe.logger("media").info(
		f"media optimize {job_key}: optimized={state['optimized']} "
		f"skipped={state['skipped']} errors={state['errors']} "
		f"saved={state['original_bytes'] - state['new_bytes']}"
	)

	# Denetim kaydı iş başına: dosya başına yazmak 2.800'lük bir işte ADL'i
	# şişirir ve zinciri okunamaz kılar (bkz. media/audit.py docstring).
	# `dry_run` diske dokunmadığı için ayrıca işaretlenir — denetimde "bu iş
	# gerçekten dosya değiştirdi mi" sorusu buradan cevaplanır.
	audit.log_media_batch(
		action=audit.ACTION_OPTIMIZE,
		job_key=job_key,
		summary={
			"preset": preset,
			"dry_run": bool(dry_run),
			"total": state["total"],
			"optimized": state["optimized"],
			"skipped": state["skipped"],
			"errors": state["errors"],
			"saved_bytes": state["original_bytes"] - state["new_bytes"],
			"skip_reasons": state["skip_reasons"],
		},
	)
	return state


def _assert_in_scope(doc) -> None:
	"""Dosya optimizasyon kapsamında mı — istemciden gelen listeye GÜVENME.

	`inventory` bu dosyaları listeden dışlıyor ama `start_image_optimization`
	`file_names` parametresiyle herhangi bir `File` adı kabul ediyor. Kontrol
	yalnız listede kalsaydı, elle istek gönderen bir admin private bir KYB
	ekini ya da bir Payment Transaction dekontunu işletebilirdi (ölçüm: 27
	dosya tüm kapıları geçiyordu). Kapsam kararı burada, yazma yolunun
	üzerinde tekrar uygulanır.
	"""
	from tradehub_core.media.inventory import EXCLUDED_DOCTYPES

	if doc.is_private or not (doc.file_url or "").startswith("/files/"):
		_deny(doc, "private_or_outside_files")
		frappe.throw(frappe._("Private dosya optimizasyon kapsamı dışında: {0}").format(doc.file_url))

	if doc.attached_to_doctype in EXCLUDED_DOCTYPES:
		_deny(doc, f"excluded_doctype:{doc.attached_to_doctype}")
		frappe.throw(
			frappe._("{0} eki optimizasyon kapsamı dışında: {1}").format(
				doc.attached_to_doctype, doc.file_name
			)
		)

	# İçerik bazlı kontrol: aynı belgenin ayrı bir public kaydı olabiliyor.
	# `is_private`/`attached_to` KAYIT bazında çalıştığı için o kopyayı
	# yakalamıyor — ölçümde 44 böyle dosya çıktı, biri KYC kimlik belgesiydi.
	if doc.content_hash and _has_sensitive_twin(doc.content_hash):
		_deny(doc, "sensitive_content_twin")
		frappe.throw(
			frappe._("Bu dosya hassas bir belgenin kopyası, kapsam dışında: {0}").format(doc.file_name)
		)


def _deny(doc, reason: str) -> None:
	"""Kapsam ihlalini denetime yaz — bu bir güvenlik olayı, sessiz geçilmez.

	Buraya düşmek istemci listesinin manipüle edildiği anlamına gelir: `inventory`
	bu dosyaları zaten listelemiyor, dolayısıyla normal kullanımda tetiklenmez.
	Tekil kaydedilir (toplu özet değil) çünkü tek bir ihlal bile incelenmeli.

	`sensitive=True`: buraya düşen her dosya tanım gereği kapsam dışıdır (private,
	hassas doctype eki ya da hassas belgenin kopyası). URL'ini kayda yazmak,
	panelden gizlediğimiz adresi denetim penceresinden geri sızdırır.
	"""
	audit.log_media_event(
		action=audit.ACTION_SCOPE_DENIED,
		file_url=doc.file_url or "",
		allowed=False,
		reason=reason,
		sensitive=True,
	)


def _has_sensitive_twin(content_hash: str) -> bool:
	"""Aynı içeriğin private ya da hassas doctype'a bağlı bir kaydı var mı."""
	from tradehub_core.media.inventory import EXCLUDED_DOCTYPES as EXC

	rows = frappe.db.sql(
		"""select 1 from tabFile where content_hash=%s
		and (is_private=1 or attached_to_doctype in %s) limit 1""",
		(content_hash, tuple(EXC)),
	)
	return bool(rows)


def _process_one(file_name: str, cfg: dict, dry_run: bool) -> dict:
	"""Tek dosya: kapsam → oku → kapılar → optimize → arşivle → yaz → künye."""
	doc = frappe.get_doc("File", file_name)

	# Kapsam ihlali sessiz atlama DEĞİL: istemci listesi manipüle edilmiş
	# demektir, Error Log'a düşmesi ve işin "partial" görünmesi gerekir.
	_assert_in_scope(doc)

	# `File` kaydı var ama dosya diskte yok olabilir: DB yedeği ile dosya yedeği
	# farklı anlara ait olduğunda ya da dosya elle silindiğinde oluşur. Bu bir
	# hata değil, envanterin bilmesi gereken bir durum — `errors` sayacını
	# şişirip işi "partial" göstermesin, `skipped` olarak raporlansın.
	try:
		content = doc.get_content()
	except Exception:
		return {"status": "skipped", "reason": "file_missing", "original_bytes": 0, "new_bytes": 0}

	if not content:
		return {"status": "skipped", "reason": "file_missing", "original_bytes": 0, "new_bytes": 0}

	original_size = len(content)

	probe = engine.probe(content)
	gate = gates.check_before(
		file_size=original_size,
		probe=probe,
		optimized_at=doc.get("th_optimized_at"),
		max_dim=cfg["max_dim"],
		min_file_size=presets.MIN_FILE_SIZE,
	)
	if not gate.passed:
		return {"status": "skipped", "reason": gate.reason, "original_bytes": original_size,
		        "new_bytes": original_size}

	result = engine.optimize(content, max_dim=cfg["max_dim"], quality=cfg["quality"])
	if not result.ok:
		return {"status": "skipped", "reason": result.reason, "original_bytes": original_size,
		        "new_bytes": original_size}

	after = gates.check_after(
		original_size=original_size,
		new_size=len(result.content),
		min_saving_ratio=presets.MIN_SAVING_RATIO,
	)
	if not after.passed:
		return {"status": "skipped", "reason": after.reason, "original_bytes": original_size,
		        "new_bytes": original_size}

	if dry_run:
		return {"status": "optimized", "original_bytes": original_size,
		        "new_bytes": len(result.content)}

	# Sıra kritik: önce arşiv, sonra yazma. Arşiv başarısızsa dosyaya dokunulmaz.
	archive.store(doc.file_url, content)
	_write_original(doc, result.content)
	_update_metadata(doc.file_url, new_size=len(result.content), original_size=original_size)

	return {"status": "optimized", "original_bytes": original_size, "new_bytes": len(result.content)}


def _write_original(doc, content: bytes) -> None:
	"""Optimize edilmiş içeriği dosyanın kendi yoluna yaz — `file_url` değişmez.

	`doc.get_full_path()` site kökünden çözer; ham yol birleştirme yapılmaz
	(`bulk_import/runner.py:673` içindeki güvensiz helper kopyalanmamalı).
	"""
	path = doc.get_full_path()
	if not os.path.isfile(path):
		frappe.throw(frappe._("Dosya diskte bulunamadı: {0}").format(doc.file_url))
	with open(path, "wb") as f:
		f.write(content)


def _update_metadata(file_url: str, *, new_size: int, original_size: int) -> None:
	"""Aynı `file_url`'i gösteren TÜM `File` kayıtlarını güncelle.

	Tek fiziksel dosyaya 39 kayda kadar işaret edebiliyor (bkz. inventory modülü
	docstring'i). Yalnız temsilciyi güncellersek diğer kayıtlar eski `file_size` ile
	kalır ve envanter toplamı bozulur.

	`doc.save()` değil `db.set_value` — `File.on_update`'in klasör boyutu yeniden
	hesaplama / thumbnail üretme yan etkilerinden ve `tabVersion` şişmesinden kaçınır.
	"""
	frappe.db.set_value(
		"File",
		{"file_url": file_url},
		{
			"file_size": new_size,
			"th_optimized_at": frappe.utils.now(),
			"th_original_size": original_size,
		},
		update_modified=False,
	)


def restore_batch(file_names: list[str], job_key: str = "") -> dict:
	"""Birden fazla dosyayı arşivdeki orijinaline döndür — worker girişi.

	Optimizasyonla aynı ilerleme mekanizmasını kullanır; ekran aynı çubuğu gösterir.
	Bir dosyanın başarısız olması diğerlerini durdurmaz.
	"""
	state = _new_state(len(file_names), "restore", False)
	state["mode"] = "restore"
	_write_progress(job_key, state)

	for index, name in enumerate(file_names, start=1):
		try:
			result = restore_original(name)
			state["processed"] += 1
			state["optimized"] += 1  # ekranda "geri alınan" sayacı
			state["new_bytes"] += result.get("size", 0)
		except Exception:
			state["processed"] += 1
			state["errors"] += 1
			frappe.log_error(f"Restore failed for {name}", "media.runner.restore_batch")

		if index % presets.COMMIT_EVERY == 0:
			_write_progress(job_key, state)

	state["state"] = "completed" if not state["errors"] else "partial"
	_write_progress(job_key, state)
	audit.log_media_batch(
		action=audit.ACTION_RESTORE,
		job_key=job_key,
		summary={
			"total": state["total"],
			"restored": state["optimized"],
			"errors": state["errors"],
			"bytes": state["new_bytes"],
		},
	)
	return state


def restore_original(file_name: str) -> dict:
	"""Arşivdeki orijinali geri yaz ve optimizasyon işaretini temizle."""
	doc = frappe.get_doc("File", file_name)
	_assert_in_scope(doc)  # geri alma da diske yazar — aynı kapsam kuralı geçerli
	if not doc.get("th_optimized_at"):
		frappe.throw(frappe._("Bu dosya optimize edilmemiş: {0}").format(doc.file_name))

	content = archive.read(doc.file_url)

	# Sıra kritik: ÖNCE DB, SONRA disk. Tersi denendiğinde (disk→DB) DB adımı
	# patlarsa dosya orijinale dönmüş ama kayıt hâlâ "optimize" görünüyordu —
	# envanter yalan söylüyor ve dosya bir daha işlenemiyordu. DB'yi önce yazıp
	# disk hatasında rollback etmek bu ikiliyi tek işleme bağlar.
	#
	# `th_original_size` Int kolonudur ve MariaDB'de NOT NULL — None yazmak
	# IntegrityError verir. Sıfırlama değeri 0'dır; Kapı 5 yalnız
	# `th_optimized_at`e bakar, dolayısıyla dosya yeniden işlenebilir hâle gelir.
	try:
		frappe.db.set_value(
			"File",
			{"file_url": doc.file_url},
			{"file_size": len(content), "th_optimized_at": None, "th_original_size": 0},
			update_modified=False,
		)
		_write_original(doc, content)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(f"Restore failed for {doc.file_url}", "media.runner.restore_original")
		raise

	frappe.db.commit()
	archive.drop(doc.file_url)
	return {"restored": doc.file_name, "size": len(content)}
