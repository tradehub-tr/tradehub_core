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

Ortak sahiplik (TUR-298)
------------------------
İçerik-adresli adlandırma (TUR-130) aynı görseli tek dosyaya indiriyor: iki
satıcı aynı logoyu yüklerse diskte tek dosya, `File` tarafında iki kayıt olur.
Bu iyi bir şey — 100 satıcının aynı ikonu diski 100 kat şişirmiyor. Bedeli
şu: **bu yoldan yapılan silme TÜM sahipleri etkiler.**

Satıcı tarafı bunu zaten kapsam ayrımıyla çözüyor (`seller_media.purge` yalnız
kendi kayıtlarını siler, kalan sahip varsa dosyaya dokunmaz). Yönetici tarafı
bunu YAPAMAZ ve yapmamalı: platform sahibinin yasal kaldırma ya da zararlı
içerik durumunda dosyayı herkesten kaldırabilmesi gerekir.

Bu yüzden burada engel değil **bilinçli onay** var: birden çok mağaza sahipse
işlem `shared_ok` verilmeden reddedilir. Amaç yöneticiyi durdurmak değil, kaç
mağazayı etkilediğini görmeden tıklamasını önlemek — `force`tan AYRI bir kapı,
çünkü farklı bir risk: `force` "kendi sitemdeki görseller kırılacak", bu ise
"başka satıcıların verisi gidecek".
"""

from __future__ import annotations

import os
import shutil
import time

import frappe

from tradehub_core.media import audit, ownership, refs, states
from tradehub_core.media.presets import EXCLUDED_DOCTYPES

TRASH_DIRNAME: str = "media_trash"
TRASH_RETENTION_DAYS: int = 30

# Çöpe taşınabilecek kullanım kararları. `in_use` asla — sitede kırılma yaratır.
TRASHABLE_VERDICTS: frozenset[str] = frozenset({"unused", "history_only"})


def _root() -> str:
	return frappe.get_site_path("private", TRASH_DIRNAME)


def _relative(file_url: str) -> str:
	"""`/files/<yol>` → `<yol>`. Path traversal reddedilir.

	Traversal kontrolü **segment bazlı**: `".." in url` düz altdizge araması
	meşru dosya adlarını da yakalıyordu. Canlı DB'de ölçüldü (2026-08-19):
	`..` içeren 19 dosyanın **hiçbiri** traversal değil — hepsi ürün
	açıklamasının dosya adına girmesinden (`MOİ ile derin düzen..jpg`).
	Bu dosyalar çöpe atılamıyor, geri alınamıyor, arşivlenemiyordu.
	Segment kontrolü gerçek traversal'ı (`/files/../etc`) aynen reddeder;
	ayrıca `_trash_path`/`_live_path` `realpath` + kök öneki ile ikinci kez
	doğruluyor, yani savunma tek katmana bağlı değil.
	"""
	url = (file_url or "").split("?")[0]
	if not url.startswith("/files/") or ".." in url.split("/"):
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


def owner_count(file_url: str) -> int:
	"""Bu dosyaya sahip mağaza sayısı — yükleyen VE kullanan.

	`ownership.owners_of` docstring'i bu senaryoyu zaten tarif ediyor: tek değer
	döndürseydi ikinci sahip görünmez olur ve silme akışı onun ürününü kırardı.
	Burada o uyarının yönetici tarafındaki karşılığı kuruluyor.
	"""
	try:
		return len(ownership.owners_of(file_url))
	except Exception:
		# Sahiplik çözülemiyorsa işlemi durdurmuyoruz ama "tek sahip" de
		# demiyoruz: 0 dönmek çağıranın onay kapısını atlamasına yol açardı.
		frappe.log_error(title="media.trash owner_count failed", message=frappe.get_traceback())
		return 0


def _assert_not_shared(file_url: str, shared_ok: bool) -> int:
	"""Birden çok mağaza sahipse açık onay iste. Sahip sayısını döndürür.

	Onay verilmişse hiçbir şey yapmaz — yönetici kaç mağazayı etkilediğini
	görmüş demektir.
	"""
	sayi = owner_count(file_url)
	if sayi > 1 and not shared_ok:
		_deny(file_url, f"shared_owners:{sayi}", sensitive=False)
		frappe.throw(
			frappe._(
				"Bu dosyayı {0} mağaza kullanıyor. Silinirse hepsinin görseli kaybolur; "
				"devam etmek için onay gerekiyor."
			).format(sayi)
		)
	return sayi


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
		frappe.throw(frappe._("Bu dosya hassas bir belgenin kopyası, çöpe taşınamaz: {0}").format(file_url))

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


def in_trash(file_url: str) -> bool:
	"""Dosya fiziksel olarak çöp klasöründe mi."""
	return os.path.isfile(_trash_path(file_url))


def move_to_trash(file_url: str, force: bool = False, shared_ok: bool = False) -> dict:
	"""Dosyayı çöpe taşı — geri alınabilir.

	`force=True` kullanımdaki dosyaya da izin verir; çağıran tarafın kullanıcıya
	sonucu (sitede kırılacak görseller) açıkça göstermiş olması gerekir.

	`shared_ok=True` dosyayı birden çok mağazanın kullandığı durumda devam eder
	(TUR-298). `force`tan AYRI tutuluyor: `force` kendi sitendeki kırılmayı,
	bu ise BAŞKA satıcıların verisinin gitmesini göze almak demek. Birini
	onaylamak diğerini onaylamış saymaz.
	"""
	_assert_trashable(file_url, force=force)
	sahip = _assert_not_shared(file_url, shared_ok)

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
		action=audit.ACTION_TRASH,
		file_url=file_url,
		# `owners`: kaç mağazayı etkilediği (TUR-298). Tek sahipli sıradan bir
		# silme ile çok sahipli bir silme denetimde ayrılabilmeli.
		context={"owners": sahip, "bytes": size, "forced": bool(force)},
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
		frappe.db.set_value("File", {"file_url": file_url}, {"th_trashed_at": None}, update_modified=False)
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


def delete_permanently(file_url: str, shared_ok: bool = False) -> dict:
	"""Çöpteki TEK dosyayı kalıcı sil — dosya + tüm `File` kayıtları.

	Yalnız çöpteki dosyalara uygulanır: canlı bir dosyayı buradan silmek
	mümkün değil, önce çöpe taşınması gerekir. Bu iki adımlı akış, tek bir
	yanlış tıklamanın geri dönüşü olmayan sonuç doğurmasını engelliyor.
	"""
	path = _trash_path(file_url)
	if not os.path.isfile(path):
		frappe.throw(frappe._("Çöpte bulunamadı: {0}").format(file_url))

	# Kalıcı silme geri alınamaz; sahip sayısı burada TEKRAR sorulur. Çöpe
	# taşımadaki onay yeterli değil: iki adım arasında yeni bir mağaza dosyayı
	# kullanmaya başlamış olabilir ve o mağaza ilk onayda görünmüyordu.
	sahip = _assert_not_shared(file_url, shared_ok)

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
			# Kaç mağazayı etkilediği kayda giriyor (TUR-298). Silme geri
			# alınamaz; "bu dosya neden gitti, kimi etkiledi" sorusunun tek
			# cevabı bu satır olacak.
			"owners": sahip,
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


def legal_hold_reason(file_url: str) -> str:
	"""Dosya yasal tutma altındaysa sebebi, değilse boş dize.

	İki kaynak okunur, ikisi de bugün OPSİYONEL — tablo/kolon yoksa sessizce
	"tutulmuyor" denmez, o kaynak atlanır:

	  1. `Media Asset.legal_hold` (medya motoru, `Media Source.file_url` üzerinden)
	  2. `File.th_legal_hold` (retention politikasının öngördüğü kolon; henüz yok)

	Neden burada: `purge_expired` diskteki mtime'a bakarak siliyordu ve hiçbir
	kayıt alanı okumuyordu. Medya motorunun retention zarfı bu yüzden çağrıyı
	REDDEDİYORDU ("legal hold açıkken tutulan dosyayı silebilir"). Kural zarfta
	değil süpürücünün kendisinde olmalı: süpürücüyü kim çağırırsa çağırsın
	tutulan dosya silinmez.
	"""
	url = (file_url or "").split("?")[0]
	if not url:
		return ""
	try:
		# Medya motorunun varlık kaydı dosyaya `source_file` (File Link) ile
		# bağlı — ölçüldü (21 Ağu): spec JSON'daki `Media Source` DocType'ı DB'de
		# henüz YOK, gerçek alan `Media Asset.source_file`. İki yol da denenir ki
		# motor şemasını tamamladığında burası değişmesin.
		if frappe.db.table_exists("Media Asset") and frappe.db.has_column("Media Asset", "legal_hold"):
			ma = frappe.qb.DocType("Media Asset")
			f = frappe.qb.DocType("File")
			if frappe.db.has_column("Media Asset", "source_file"):
				tutulan = (
					frappe.qb.from_(ma)
					.join(f)
					.on(f.name == ma.source_file)
					.select(ma.name)
					.where(f.file_url == url)
					.where(ma.legal_hold == 1)
					.limit(1)
				).run()
				if tutulan:
					return f"media_asset:{tutulan[0][0]}"
			if frappe.db.table_exists("Media Source"):
				ms = frappe.qb.DocType("Media Source")
				tutulan = (
					frappe.qb.from_(ms)
					.join(ma)
					.on(ma.name == ms.asset)
					.select(ma.name)
					.where(ms.file_url == url)
					.where(ma.legal_hold == 1)
					.limit(1)
				).run()
				if tutulan:
					return f"media_asset:{tutulan[0][0]}"
		if frappe.db.has_column("File", "th_legal_hold") and frappe.db.exists(
			"File", {"file_url": url, "th_legal_hold": 1}
		):
			return "file:th_legal_hold"
	except Exception:
		# Tutma bilgisi okunamıyorsa "tutulmuyor" DENMEZ — silme geri alınamaz,
		# belirsizlikte dosya yerinde kalır. Hata kaydının kendisi de DB ister;
		# o da patlarsa sonuç yine "bilinmiyor" olmalı, ikinci bir istisna değil.
		try:
			frappe.log_error(title="media.trash legal_hold_reason failed", message=frappe.get_traceback())
		except Exception:
			pass
		return "unknown:lookup_failed"
	return ""


def purge_expired(retention_days: int = TRASH_RETENTION_DAYS, trigger: str = "scheduled") -> dict:
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
	tutulanlar: list[str] = []
	temizlenen_ref = 0

	for dirpath, _dirs, files in os.walk(root, topdown=False):
		for name in files:
			path = os.path.join(dirpath, name)
			try:
				if os.path.getmtime(path) >= cutoff:
					continue
				rel = os.path.relpath(path, root)
				url = "/files/" + rel.replace(os.sep, "/")
				# Yasal tutma süreyi ezer: süresi dolmuş olsa da dosya ve kaydı
				# yerinde kalır, raporda ayrı sayılır (bkz. `legal_hold_reason`).
				if legal_hold_reason(url):
					tutulanlar.append(url)
					continue
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
				frappe.log_error(title="Trash purge failed", message=frappe.get_traceback(with_context=True))
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
			"legal_hold_skipped": len(tutulanlar),
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
		"legal_hold_skipped": tutulanlar,
	}
