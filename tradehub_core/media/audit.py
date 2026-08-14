"""Medya olaylarının denetim kaydı — TUR-140.

Neden yeni bir DocType değil: `Authorization Decision Log` (ADL) zaten hash
zinciri, 90 günlük sıcak saklama ve anomali kuralları ile geliyor. Aynı modüldeki
`log_pii_reveal` de authz olmayan bir olayı (PII görüntüleme) bu tabloya yazıyor —
emsal var. Yeni tablo açmak CLAUDE.md §4'teki "DocType bloat" kuralına da aykırı
olurdu.

**Kayıt granülerliği bilinçli olarak iki farklı:**

  - Yıkıcı ve tekil işlemler (çöpe taşı, geri al, kalıcı sil) → **dosya başına**.
    Bunlar geri dönüşü zor kararlar; "hangi dosyayı kim sildi" sorusu dosya
    seviyesinde cevaplanabilmeli.
  - Toplu ve tekrarlanabilir işlemler (optimize, arşivden geri yükleme, purge)
    → **iş başına özet**. 2.800 dosyalık bir optimizasyonda dosya başına kayıt
    atmak ADL'i tek işte şişirir ve zinciri okunamaz hâle getirir; kazanç yok,
    çünkü optimizasyon geri alınabilir bir işlem.

Reddedilen istekler her zaman tekil kaydedilir — kapsam ihlali güvenlik olayıdır.
"""

from __future__ import annotations

import hashlib
from typing import Any

import frappe
from frappe.query_builder import DocType, Order
from frappe.query_builder.functions import Count, CustomFunction, Max

from tradehub_core.audit import (
	DECISION_ALLOW,
	DECISION_DENY,
	LAYER_L2,
	SEVERITY_HIGH,
	SEVERITY_NORMAL,
	log_decision,
)
from tradehub_core.media import timefmt

# Kritik olay listesi — TUR-140 kabul kriteri 1.
# İsimlendirme mevcut ADL kuralına uyar: "<alan>.<eylem>".
ACTION_UPLOAD: str = "media.upload"
ACTION_OPTIMIZE: str = "media.optimize"
ACTION_RESTORE: str = "media.restore"
ACTION_TRASH: str = "media.trash"
ACTION_UNTRASH: str = "media.untrash"
ACTION_DELETE: str = "media.delete"
ACTION_PURGE_TRASH: str = "media.purge_trash"
ACTION_PURGE_ARCHIVE: str = "media.purge_archive"
ACTION_SCOPE_DENIED: str = "media.scope_denied"
ACTION_ACCESS_DENIED: str = "media.access_denied"
# Satıcı kendi sahipliğini bıraktı. Silmeden ayrı bir olay: dosya diskte
# duruyor olabilir (başka mağaza da sahipse). "Sildim ama dosya duruyor"
# durumunun denetimde açıkça görünmesi gerekiyor.
ACTION_RELEASE: str = "media.release"
ACTION_RECLAIM: str = "media.reclaim"
# Yedek paketi sunucudan dışarı çıkarıldı. Paket TÜM medyayı içeriyor, özel
# belgeler dahil — verinin sunucuyu terk ettiği tek nokta bu. Kimin ne zaman
# dışarı aktardığı iz bırakmadan gerçekleşmemeli.
ACTION_EXPORT: str = "media.export"
# TUR-126 — private dosya imzalı süreli link ile (girişsiz) indirildi.
# `media_access.download`'ın tek başarı kaydı: kim/ne zaman değil (link
# giriş gerektirmiyor), hangi dosyanın hangi imzalı linkle dışarı çıktığı.
ACTION_SIGNED_ACCESS: str = "media.signed_access"

MEDIA_ACTIONS: tuple[str, ...] = (
	ACTION_UPLOAD,
	ACTION_OPTIMIZE,
	ACTION_RESTORE,
	ACTION_TRASH,
	ACTION_UNTRASH,
	ACTION_DELETE,
	ACTION_PURGE_TRASH,
	ACTION_PURGE_ARCHIVE,
	ACTION_SCOPE_DENIED,
	ACTION_ACCESS_DENIED,
	ACTION_RELEASE,
	ACTION_RECLAIM,
	ACTION_EXPORT,
	ACTION_SIGNED_ACCESS,
)

# Geri dönüşü olmayan ya da güvenlik anlamı taşıyan olaylar HIGH ile işaretlenir;
# operasyonel inceleme bunlara severity ile filtre atabilsin.
_HIGH_SEVERITY_ACTIONS: frozenset[str] = frozenset(
	{
		ACTION_DELETE,
		ACTION_PURGE_TRASH,
		ACTION_PURGE_ARCHIVE,
		ACTION_SCOPE_DENIED,
		ACTION_ACCESS_DENIED,
		# Geri alınamaz değil ama güvenlik anlamı taşıyor: veri sunucudan çıktı.
		ACTION_EXPORT,
	}
)


def fingerprint(value: str) -> str:
	"""Maskelenmiş dosya için kararlı, geri döndürülemez kimlik.

	Aynı dosyaya yapılan tekrar denemeler aynı parmak izini üretir; operatör
	"bu dosyaya 5 kez denendi" diyebilir ama dosyayı açamaz.
	"""
	return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:12]


def log_media_event(
	*,
	action: str,
	file_url: str = "",
	allowed: bool = True,
	reason: str = "",
	sensitive: bool = False,
	tenant: str | None = None,
	commit: bool = True,
	context: dict[str, Any] | None = None,
) -> str | None:
	"""Tek medya olayını ADL'ye yaz.

	`log_decision` best-effort'tur — yazım patlasa bile exception fırlatmaz.
	Bu bilinçli: denetim kaydı yazılamadı diye kullanıcının silme işlemi
	başarısız olmamalı, ama hata `Error Log`'a düşer.

	Args:
	    action: `MEDIA_ACTIONS` içinden bir değer.
	    file_url: Etkilenen dosya (toplu işlerde boş bırakılır).
	    allowed: İşlem gerçekleşti mi; False ise DENY olarak kaydedilir.
	    reason: Reddedilme gerekçesi ya da atlama sebebi.
	    sensitive: Dosya kapsam dışı olduğu için reddedildiyse True. Bu durumda
	        URL ve dosya adı KAYDEDİLMEZ, yerine parmak izi yazılır — aksi hâlde
	        panelden gizlediğimiz KYC/dekont adresleri denetim penceresinden
	        geri sızıyordu (ölçüldü: 4 kayıtta tam public URL görünüyordu).
	    tenant: İşi yapan satıcının `Admin Seller Profile` adı. Yükleme
	        kayıtlarında "hangi satıcı" sorusunu bu alan cevaplar.
	    commit: Kaydı hemen kalıcı yap. Yükleme kancasında False geçilir —
	        orada audit satırı `File` insert'i ile aynı transaction'da yazılır,
	        her dosya için ayrı commit toplu içe aktarımı dize dize yavaşlatırdı.
	    context: İşe özel sayılar (kaç dosya, kaç bayt kazanç vb.).
	"""
	payload: dict[str, Any] = dict(context or {})
	if reason:
		payload["reason"] = reason

	if sensitive:
		# Dosyayı tanımlayan hiçbir alan kayda girmemeli.
		for key in ("file_name", "file_url", "attached_to_doctype"):
			payload.pop(key, None)
		payload["masked"] = True
		file_url = f"masked:{fingerprint(file_url)}"
	elif file_url:
		payload["file_url"] = file_url

	return _persist(
		commit=commit,
		action=action,
		decision=DECISION_ALLOW if allowed else DECISION_DENY,
		# `File` kaydı silinmiş olabileceği için object_name'e kayıt adı değil
		# dosya yolu yazılır — kayıt gitse de olayın hangi dosyaya ait olduğu kalır.
		object_doctype="File" if file_url else None,
		object_name=file_url or None,
		tenant=tenant,
		# Reddedilen istekler yetkilendirme katmanının kararıdır; başarılı
		# operasyonlar bir authz kararı değil, bu yüzden layer boş bırakılır.
		layer=LAYER_L2 if not allowed else None,
		rule_id="media.scope" if action == ACTION_SCOPE_DENIED else None,
		severity=SEVERITY_HIGH if action in _HIGH_SEVERITY_ACTIONS or not allowed else SEVERITY_NORMAL,
		context=payload,
	)


def log_media_batch(
	*,
	action: str,
	job_key: str = "",
	summary: dict[str, Any] | None = None,
) -> str | None:
	"""Toplu işin sonucunu TEK kayıt olarak yaz.

	Kısmi başarı da burada görünür: `summary` içindeki `errors` ve `skipped`
	sayaçları işin tamamının başarılı olmadığını gösterir (TUR-140 kapsam
	maddesi: "toplu işlemler ve başarısız iş akışları için olay kaydı").
	"""
	payload: dict[str, Any] = dict(summary or {})
	if job_key:
		payload["job_key"] = job_key

	# Hiç dosya işlenmediyse ya da hata varsa işin tamamı "başarılı" sayılmaz.
	errors = int(payload.get("errors") or 0)

	return _persist(
		action=action,
		decision=DECISION_ALLOW,
		severity=SEVERITY_HIGH if action in _HIGH_SEVERITY_ACTIONS or errors else SEVERITY_NORMAL,
		context=payload,
	)


def _persist(commit: bool = True, **kwargs: Any) -> str | None:
	"""`log_decision` + commit.

	`log_decision` kaydı insert eder ama commit ETMEZ. Denetim kaydı için bu
	yetmiyor, iki nedenle:

	  1. Red yolunda `_deny()` çağrısını hemen `frappe.throw()` izliyor; throw
	     transaction'ı geri alır ve tam da saklamak istediğimiz güvenlik kaydı
	     silinir. Ölçtük: `media.untrash` kaydı bu yüzden kayboluyordu.
	  2. Worker'da iş sonundaki özet, son `commit`'ten sonra yazılıyor —
	     commit'siz kalırsa job bitince düşüyor.

	Fazladan commit güvenli: tüm çağrı noktalarında ya işlemin kendi commit'i
	zaten yapılmış durumda ya da (red yolunda) henüz hiçbir yazma yok.
	"""
	name = log_decision(**kwargs)
	if name and commit:
		try:
			frappe.db.commit()
		except Exception:
			# Denetim yazımı best-effort — commit patlarsa iş akışı durmamalı.
			frappe.log_error(
				title="media.audit commit failed",
				message=frappe.get_traceback(with_context=True),
			)
	return name


# Yükleme kaydı yalnız medya için tutulur — issue "medya sistemi" diyor ve
# toplu içe aktarımda PDF/Excel/sistem dosyalarını da yazmak ADL'i şişirir.
MEDIA_EXTENSIONS: frozenset[str] = frozenset(
	{
		".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg", ".avif", ".heic",
		".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v",
	}
)


def on_file_insert(doc, method: str | None = None) -> None:
	"""`File.after_insert` kancası — medya yüklemesini denetime yazar.

	"Bu görseli hangi satıcı yükledi" sorusunu bu kayıt cevaplar: `actor`
	oturum kullanıcısı, `tenant` ise satıcının `Admin Seller Profile` adı.

	Best-effort: burada patlamak kullanıcının dosya yüklemesini engellememeli.

	Maskeleme: private dosyalar ve hassas doctype ekleri kimliksiz yazılır.
	İçerik-ikizi kontrolü YALNIZ public+eksiz dosyalarda yapılır — `content_hash`
	indeksli değil (ölçüldü: `tabFile` üzerinde yalnız 5 indeks var, content_hash
	yok), toplu içe aktarımda her ürün görseli için tam tarama yapmak pahalıya
	gelirdi. Sızan 44 kopyanın tamamı zaten public+eksiz desenindeydi.
	"""
	try:
		if doc.get("is_folder"):
			return

		file_name = doc.get("file_name") or ""
		if not any(file_name.lower().endswith(ext) for ext in MEDIA_EXTENSIONS):
			return

		from tradehub_core.media.presets import EXCLUDED_DOCTYPES

		attached = doc.get("attached_to_doctype")
		sensitive = bool(doc.get("is_private")) or attached in EXCLUDED_DOCTYPES

		if not sensitive and not attached and doc.get("content_hash"):
			from tradehub_core.media.runner import _has_sensitive_twin

			sensitive = _has_sensitive_twin(doc.content_hash)

		log_media_event(
			action=ACTION_UPLOAD,
			file_url=doc.get("file_url") or "",
			sensitive=sensitive,
			tenant=_current_tenant(),
			commit=False,
			context={
				"file_name": file_name,
				"bytes": doc.get("file_size") or 0,
				"is_private": bool(doc.get("is_private")),
				"attached_to_doctype": attached,
				"attached_to_name": doc.get("attached_to_name"),
			},
		)
	except Exception:
		frappe.log_error(
			title="media.audit on_file_insert failed",
			message=frappe.get_traceback(with_context=True),
		)


def _current_tenant() -> str | None:
	"""Yükleyen satıcının `Admin Seller Profile` adı; admin yüklemesinde None."""
	try:
		from tradehub_core.utils.tenant import get_current_seller_profile

		return get_current_seller_profile()
	except Exception:
		return None


# Tablo başlığından sıralanabilecek kolonlar. İstemciden gelen ad bu haritadan
# geçmeden sorguya girmez.
SORTABLE: dict[str, str] = {
	"timestamp": "timestamp",
	"action": "action",
	"actor": "actor",
	"tenant": "tenant",
	"severity": "severity",
	"decision": "decision",
	"target": "object_name",
}

ROW_FIELDS: tuple[str, ...] = (
	"name",
	"timestamp",
	"actor",
	"actor_role",
	"tenant",
	"action",
	"decision",
	"severity",
	"object_name",
	"context",
	"ip_address",
)

# Serbest metin araması `LIKE` ile yapılmaz: MariaDB'nin utf8mb4_unicode_ci
# collation'ında 4 baytlık karakter içeren satırlarda LIKE hatalı sonuç veriyor
# (envanterde ölçüldü, 23 dosya sessizce düşüyordu). `LOCATE` etkilenmiyor.
Locate = CustomFunction("LOCATE", ["needle", "haystack"])


def _base_query():
	adl = DocType("Authorization Decision Log")
	return adl, frappe.qb.from_(adl).where(adl.action.isin(list(MEDIA_ACTIONS)))


def _apply_filters(adl, q, *, action, severity, decision, actor, tenant, file_url, search, days):
	if action:
		if action not in MEDIA_ACTIONS:
			frappe.throw(frappe._("Bilinmeyen medya olayı: {0}").format(action))
		q = q.where(adl.action == action)
	if severity:
		q = q.where(adl.severity == severity)
	if decision:
		q = q.where(adl.decision == decision)
	if actor:
		q = q.where(adl.actor == actor)
	if tenant:
		q = q.where(adl.tenant == tenant)
	if file_url:
		q = q.where(adl.object_name == file_url)
	if days:
		cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -abs(int(days)))
		q = q.where(adl.timestamp >= cutoff)
	if search:
		# Dosya yolunda ya da bağlam JSON'ında geçsin — operatör hem dosya adı
		# hem gerekçe ("sensitive_content_twin") arayabilmeli.
		q = q.where((Locate(search, adl.object_name) > 0) | (Locate(search, adl.context) > 0))
	return q


def list_events(
	*,
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
	"""Sayfalı medya olay listesi — TUR-140 kabul kriteri 4.

	Yalnız `MEDIA_ACTIONS` kapsamındaki kayıtları döndürür; ADL'nin geri kalanı
	(yetkilendirme kararları) bu görünümün dışındadır.
	"""
	page = max(1, int(page or 1))
	page_size = max(1, min(int(page_size or 50), 200))

	adl, q = _base_query()
	q = _apply_filters(
		adl,
		q,
		action=action,
		severity=severity,
		decision=decision,
		actor=actor,
		tenant=tenant,
		file_url=file_url,
		search=search,
		days=days,
	)

	total = (q.select(Count("*")).run() or [[0]])[0][0]

	# Sıralama kolonu whitelist'ten seçilir — istemciden gelen ad doğrudan
	# sorguya girerse kolon enjeksiyonu olur.
	column = SORTABLE.get((sort_by or "timestamp").strip(), "timestamp")
	order = Order.asc if (sort_dir or "desc").lower() == "asc" else Order.desc
	q = q.select(*[getattr(adl, f) for f in ROW_FIELDS]).orderby(getattr(adl, column), order=order)
	# İkincil sıralama: aynı saniyede yazılmış kayıtlar (toplu iş) sayfalar
	# arasında yer değiştirmesin, sayfalama kararlı olsun.
	if column != "timestamp":
		q = q.orderby(adl.timestamp, order=Order.desc)

	rows = q.limit(page_size).offset((page - 1) * page_size).run(as_dict=True)
	_decorate_targets(rows)
	_decorate_actors(rows)

	# TUR-124 — tarih standart biçimde çıkıyor.
	timefmt.apply_all(rows)

	return {"items": rows, "total": total, "page": page, "page_size": page_size}


# Tarayıcının çizebildiği uzantılar. TIFF ve SVG kasten dışarıda: TIFF çoğu
# tarayıcıda açılmıyor, SVG ise kullanıcı yüklemesi olduğu için inline gösterimi
# XSS yüzeyi (bkz. utils/security.reject_unsafe_files).
RENDERABLE_EXT: frozenset[str] = frozenset(
	{".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp"}
)


def _decorate_actors(rows: list[dict]) -> None:
	"""Her satıra `actor_name` ekle — kullanıcının görünen adı.

	Liste `actor` (e-posta) gösterirken rapor `full_name` gösteriyordu ve aynı
	kişi iki farklı isimle görünüyordu: `bora.aydeger@turksab.com` ile "Mogem"
	aynı hesap. İkisi de aynı kaynaktan gelsin, ekranlar çelişmesin.

	Tek sorgu: satır başına `get_value` çağırmak 50 satırda 50 sorgu demek.
	"""
	emails = {r["actor"] for r in rows if r.get("actor")}
	names: dict[str, str] = {}
	if emails:
		for u in frappe.get_all(
			"User",
			filters={"name": ["in", list(emails)]},
			fields=["name", "full_name"],
			limit_page_length=0,
		):
			if u.get("full_name"):
				names[u["name"]] = u["full_name"]

	# Mağaza adının yetkili kaynağı `Admin Seller Profile.seller_name`.
	# `User.full_name` alanına da mağaza adı girilmiş (ölçüldü: SEL-00002'nin
	# kullanıcısında full_name = "Mogem"), ama orası kişi alanı — mağaza adını
	# oradan okumak yanlış kaynağa güvenmek olur.
	tenants = {r["tenant"] for r in rows if r.get("tenant")}
	stores: dict[str, str] = {}
	if tenants:
		for p in frappe.get_all(
			"Admin Seller Profile",
			filters={"name": ["in", list(tenants)]},
			fields=["name", "seller_name"],
			limit_page_length=0,
		):
			if p.get("seller_name"):
				stores[p["name"]] = p["seller_name"]

	for r in rows:
		store = stores.get(r.get("tenant"))
		person = names.get(r.get("actor"))
		r["tenant_name"] = store
		# `actor` her zaman hesabın kendisi (e-posta) — tek ve kesin kimlik.
		# `User.full_name` alanına mağaza adı girilmiş hesaplar var, onu kimlik
		# olarak göstermek "Mogem" ile "bora.aydeger@turksab.com"u iki ayrı kişi
		# gibi gösteriyordu. Görünen ad ayrı alanda, yalnız farklıysa taşınır.
		r["actor_name"] = r.get("actor")
		r["actor_display"] = person if (person and person != r.get("actor") and person != store) else None


def _decorate_targets(rows: list[dict]) -> None:
	"""Her satıra `target_state` ekle — önizleme neden çıkmıyor sorusunun cevabı.

	Ölçüm: 28 kaydın 11'inde hedef dosya YOK (toplu iş özeti), 4'ü maskeli,
	2'sinin dosyası sonradan silinmiş. Panel bunları sessizce boş kutu olarak
	gösteriyordu; artık her biri gerekçesiyle ayrışıyor.

	Durumlar:
	    none        — olayın dosyası yok (toplu iş, yetki reddi)
	    masked      — kimliği gizlenmiş hassas belge
	    unsupported — tarayıcının çizemediği format
	    deleted     — `File` kaydı yok, dosya silinmiş
	    trashed     — çöp kutusunda, public URL 404 döner
	    ok          — çizilebilir
	"""
	urls = {
		r["object_name"]
		for r in rows
		if r.get("object_name") and str(r["object_name"]).startswith("/files/")
	}
	# Tek sorgu: satır başına ayrı `exists` çağırmak 50 satırda 50 sorgu demek.
	known: dict[str, object] = {}
	if urls:
		for row in frappe.get_all(
			"File",
			filters={"file_url": ["in", list(urls)]},
			fields=["file_url", "th_media_state", "th_trashed_at"],
			limit_page_length=0,
		):
			# Aynı dosyaya birden çok kayıt işaret edebiliyor; biri bile canlıysa
			# dosya canlıdır. Durum `th_media_state`'ten okunur; alan boşsa damgaya
			# düşülür (TUR-138 patch'i öncesi kayıtlar).
			prev = known.get(row["file_url"], "missing")
			from tradehub_core.media.states import STATE_TRASHED

			is_trashed = (row.get("th_media_state") == STATE_TRASHED) or bool(row.get("th_trashed_at"))
			state = "trashed" if is_trashed else "live"
			known[row["file_url"]] = "live" if "live" in (prev, state) else state

	for r in rows:
		url = str(r.get("object_name") or "")
		if not url:
			r["target_state"] = "none"
		elif url.startswith("masked:"):
			r["target_state"] = "masked"
		elif not url.startswith("/files/"):
			r["target_state"] = "none"
		elif "." + url.rsplit(".", 1)[-1].lower() not in RENDERABLE_EXT:
			r["target_state"] = "unsupported"
		else:
			r["target_state"] = {"live": "ok", "trashed": "trashed"}.get(
				known.get(url, "missing"), "deleted"
			)


def facets(*, days: int = 0) -> dict:
	"""Filtre rayındaki sayaçlar — hangi olaydan kaç tane var.

	Tek sorguda toplanır; her seçenek için ayrı `count` atmak filtre çekmecesini
	açarken 10+ sorgu demek olurdu.
	"""
	adl, q = _base_query()
	if days:
		cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -abs(int(days)))
		q = q.where(adl.timestamp >= cutoff)

	by_action = {
		r["action"]: r["n"]
		for r in q.select(adl.action, Count("*").as_("n")).groupby(adl.action).run(as_dict=True)
	}

	adl2, q2 = _base_query()
	if days:
		cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -abs(int(days)))
		q2 = q2.where(adl2.timestamp >= cutoff)
	by_severity = {
		r["severity"]: r["n"]
		for r in q2.select(adl2.severity, Count("*").as_("n")).groupby(adl2.severity).run(as_dict=True)
	}

	return {
		"actions": by_action,
		"severity": by_severity,
		"denied": sum(by_action.get(a, 0) for a in (ACTION_SCOPE_DENIED, ACTION_ACCESS_DENIED)),
		"total": sum(by_action.values()),
	}


def report(name: str) -> dict:
	"""Tek denetim kaydının tam raporu — popup'ta gösterilen her şey.

	Bir olay satırı tek başına "kim ne yaptı" der ama "bu neden önemli" demez.
	Rapor altı bloğu birleştirir:

	  1. olay      — kaydın kendisi
	  2. dosya     — künye: boyut, format, içerik imzası, kaç kez yüklenmiş
	  3. kullanım  — hangi üründe, hangi alanda, varyant mı (mevcut `usage`
	                 çözümleyicisi yeniden kullanılıyor, ikinci bir uygulama yok)
	  4. etki      — silinseydi kaç ürün etkilenirdi
	  5. geçmiş    — aynı dosyaya ait tüm olaylar, sırasıyla
	  6. aktör     — rolleri, mağazası, son 24 saatteki hareketliliği
	  7. bütünlük  — hash zincirindeki yeri ve doğrulaması

	Maskeli kayıtlarda dosya/kullanım blokları BOŞ döner: kimliği gizlediğimiz
	belgeyi rapor üzerinden geri sızdırmak, maskelemenin amacını ortadan kaldırır.
	"""
	row = frappe.db.get_value(
		"Authorization Decision Log",
		name,
		["name", *ROW_FIELDS[1:], "prev_hash", "entry_hash", "creation"],
		as_dict=True,
	)
	if not row or row.get("action") not in MEDIA_ACTIONS:
		frappe.throw(frappe._("Denetim kaydı bulunamadı: {0}").format(name))

	url = str(row.get("object_name") or "")
	masked = url.startswith("masked:")
	out: dict[str, Any] = {
		"event": row,
		"masked": masked,
		"file": None,
		"usage": None,
		"impact": None,
		"history": _file_history(url) if url and not masked else [],
		"actor": _actor_profile(row.get("actor"), row.get("tenant")),
		"integrity": _integrity(row),
		"retention": {
			"hot_days": 90,
			"deleted": False,
			"note": frappe._("Denetim kayıtları silinmez; 90 gün sonra soğuk arşive işaretlenir."),
		},
	}

	if masked or not url.startswith("/files/"):
		return out

	out["file"] = _file_card(url)
	try:
		from tradehub_core.media import usage

		detail = usage.resolve(url)
		out["usage"] = detail
		# Etki: kaç ayrı ürün kayda bağlı — silme kararının tek sayısal karşılığı.
		products = {f"{u.get('doctype')}:{u.get('name')}" for u in (detail.get("usages") or [])}
		out["impact"] = {
			"live_products": len(products),
			"order_copies": len(detail.get("orders") or []),
			"verdict": detail.get("verdict"),
			"redundant_records": detail.get("redundant_records") or 0,
		}
	except Exception:
		# Kullanım çözümleyicisi patlarsa rapor tamamen kaybolmasın.
		frappe.log_error(title="media.audit report usage failed", message=frappe.get_traceback())

	return out


def _file_card(url: str) -> dict | None:
	"""Dosya künyesi — aynı yolu gösteren tüm `File` kayıtları özetlenir."""
	rows = frappe.get_all(
		"File",
		filters={"file_url": url},
		fields=[
			"name",
			"file_name",
			"file_size",
			"content_hash",
			"is_private",
			"attached_to_doctype",
			"attached_to_name",
			"creation",
			"th_optimized_at",
			"th_original_size",
			"th_trashed_at",
		],
		order_by="creation asc",
		limit_page_length=0,
	)
	if not rows:
		return {"exists": False, "url": url}

	first = rows[0]
	return {
		"exists": True,
		"url": url,
		"file_name": first.get("file_name"),
		"file_size": first.get("file_size"),
		"content_hash": first.get("content_hash"),
		"created": first.get("creation"),
		"optimized_at": first.get("th_optimized_at"),
		"original_size": first.get("th_original_size"),
		"trashed_at": first.get("th_trashed_at"),
		# Aynı dosyanın kaç kez yüklendiği: 1'den büyükse gereksiz kopya var.
		"record_count": len(rows),
		"attachments": [
			{"doctype": r["attached_to_doctype"], "name": r["attached_to_name"]}
			for r in rows
			if r.get("attached_to_doctype")
		],
	}


def _file_history(url: str) -> list[dict]:
	"""Bu dosyaya ait tüm olaylar — yüklendi → optimize → çöpe taşındı zinciri."""
	adl, q = _base_query()
	return (
		q.select(adl.name, adl.timestamp, adl.action, adl.decision, adl.severity, adl.actor)
		.where(adl.object_name == url)
		.orderby(adl.timestamp, order=Order.desc)
		.limit(50)
		.run(as_dict=True)
	)


def _actor_profile(actor: str | None, tenant: str | None) -> dict:
	"""Aktörün kimliği ve hareketliliği — "bu kullanıcı normalde ne yapar"."""
	if not actor:
		return {}
	profile: dict[str, Any] = {"user": actor, "tenant": tenant}
	try:
		profile["roles"] = sorted(frappe.get_roles(actor))
		profile["full_name"] = frappe.db.get_value("User", actor, "full_name")
	except Exception:
		profile["roles"] = []

	# Mağaza adı `Admin Seller Profile`'dan gelir; kullanıcı kaydındaki isimden
	# değil. İkisi aynıysa kişi adı gösterilmez, tekrar olurdu.
	if tenant:
		profile["tenant_name"] = frappe.db.get_value("Admin Seller Profile", tenant, "seller_name")
		if profile.get("full_name") and profile["full_name"] == profile.get("tenant_name"):
			profile["full_name"] = None

	adl, q = _base_query()
	cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -1)
	rows = (
		q.select(adl.decision, Count("*").as_("n"))
		.where(adl.actor == actor)
		.where(adl.timestamp >= cutoff)
		.groupby(adl.decision)
		.run(as_dict=True)
	)
	profile["last24h"] = {r["decision"]: int(r["n"]) for r in rows}
	profile["last24h_total"] = sum(profile["last24h"].values())
	return profile


def _integrity(row: dict) -> dict:
	"""Kaydın hash zincirindeki yeri — sonradan değiştirilmiş mi.

	Özet, `ADL_HASH_FIELDS`'in TAMAMI üzerinden hesaplanır. Eksik alanla yeniden
	hesaplamak farklı bir kanonik metin üretir ve sağlam bir kaydı "değiştirilmiş"
	gösterir — denetim ekranında bundan yanıltıcı bir şey olamaz. Bu yüzden kayıt
	burada baştan, tam alan setiyle okunur.
	"""
	try:
		from tradehub_core.audit.log import ADL_HASH_FIELDS, adl_entry_hash

		full = frappe.db.get_value(
			"Authorization Decision Log",
			row.get("name"),
			[*ADL_HASH_FIELDS, "prev_hash", "entry_hash"],
			as_dict=True,
		)
		if not full:
			return {"entry_hash": row.get("entry_hash"), "intact": None}

		expected = adl_entry_hash(full, full.get("prev_hash"))
		return {
			"entry_hash": full.get("entry_hash"),
			"prev_hash": full.get("prev_hash"),
			# entry_hash boşsa "doğrulanamadı" demektir; "kurcalanmış" DEĞİL.
			"intact": (expected == full.get("entry_hash")) if full.get("entry_hash") else None,
		}
	except Exception:
		frappe.log_error(title="media.audit integrity check failed", message=frappe.get_traceback())
		return {"entry_hash": row.get("entry_hash"), "intact": None}


def top_targets(limit: int = 10) -> list[dict]:
	"""En çok olay üreten dosyalar — "hangi dosya başımızı ağrıtıyor"."""
	adl, q = _base_query()
	rows = (
		q.select(adl.object_name, Count("*").as_("n"))
		.where(adl.object_name.isnotnull())
		.where(adl.object_name != "")
		.groupby(adl.object_name)
		.orderby(Count("*"), order=Order.desc)
		.limit(max(1, min(int(limit or 10), 50)))
		.run(as_dict=True)
	)
	return rows


def export_rows(*, limit: int = 5000, **filters) -> list[dict]:
	"""Filtreye uyan kayıtların tamamı — CSV dışa aktarma için.

	Sayfalama yok ama üst sınır var: filtresiz bir dışa aktarma isteği tüm
	denetim tablosunu belleğe almasın.
	"""
	filters.pop("page", None)
	filters.pop("page_size", None)
	return list_events(page=1, page_size=max(1, min(int(limit or 5000), 5000)), **filters)["items"]


def actors(limit: int = 50) -> list[dict]:
	"""Denetimde geçen kullanıcılar ve satıcılar — filtre açılır listesi için."""
	adl, q = _base_query()
	# Aktöre göre gruplanır, (aktör, mağaza) çiftine göre DEĞİL: aynı kullanıcı
	# bazı olaylarda mağaza bağlamıyla, bazılarında bağlamsız kaydediliyor ve
	# filtre listesinde iki kez görünüyordu.
	rows = (
		q.select(adl.actor, Max(adl.tenant).as_("tenant"), Count("*").as_("n"))
		.groupby(adl.actor)
		.orderby(Count("*"), order=Order.desc)
		.limit(max(1, min(int(limit or 50), 200)))
		.run(as_dict=True)
	)
	rows = [r for r in rows if r.get("actor")]
	# Filtre listesinde de mağaza kodu değil adı görünsün.
	_decorate_actors(rows)
	return rows
