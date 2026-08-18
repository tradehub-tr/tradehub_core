"""Medya yaşam döngüsü — durum modeli ve geçişler (TUR-138).

Önce durum ayrı damgalardan türetiliyordu: `th_trashed_at` doluysa çöpte,
`th_optimized_at` doluysa optimize. Çalışıyordu ama iki sorunu vardı:

  1. Yeni bir durum eklemek her filtreyi tek tek değiştirmeyi gerektiriyordu.
  2. Durum "hesaplanan" bir şeydi; iki damga çelişirse hangisinin doğru olduğuna
     karar verecek tek bir yer yoktu.

Bu modül durumu **açık bir alana** taşır (`th_media_state`) ve tüm geçişleri tek
kapıdan geçirir. Damgalar KALDIRILMADI — ikisi farklı soruyu cevaplıyor:

    th_media_state   → dosya ŞU AN hangi durumda
    th_trashed_at    → çöpe NE ZAMAN gitti
    th_optimized_at  → NE ZAMAN optimize edildi

Rapor "ne zaman"ı gösteriyor, filtreler "hangi durumda"yı kullanıyor. Damgayı
silmek denetim raporundaki tarih satırlarını boşaltırdı.

Durumlar
--------
    Active     Dosya canlı, orijinal hâlinde.
    Archived   Optimize edilmiş; orijinali `private/image_originals/` altında,
               30 gün içinde geri alınabilir. Issue'daki "arşivlenmiş".
    Trashed    Çöpte; fiziksel dosya `private/media_trash/` altında, public URL
               404 döner. 30 gün içinde geri alınabilir.
    Deleted    Kalıcı silinmiş. `File` kaydı yok olduğu için BU DURUM DİSKTE
               SAKLANMAZ — yalnız denetim kaydında (`media.delete`) yaşar.
               Terminal durum: buradan dönüş yok.

Geçişler
--------
    Active   ──optimize──→  Archived
    Archived ──restore───→  Active
    Active   ──trash─────→  Trashed
    Archived ──trash─────→  Trashed
    Trashed  ──untrash───→  Active | Archived   (optimize damgasına göre)
    Trashed  ──delete────→  Deleted             (terminal)

`Active → Deleted` yoktur: kalıcı silme yalnız çöpten yapılır. Bu iki adımlı
akış, tek yanlış tıklamanın geri dönüşü olmayan sonuç doğurmasını engeller.
"""

from __future__ import annotations

import frappe

STATE_ACTIVE: str = "Active"
STATE_ARCHIVED: str = "Archived"
STATE_TRASHED: str = "Trashed"
STATE_DELETED: str = "Deleted"

# Diskte saklanabilen durumlar. `Deleted` listede yok: kaydı olmayan dosyanın
# durumu da olmaz, o bilgi denetim kaydında durur.
STORED_STATES: tuple[str, ...] = (STATE_ACTIVE, STATE_ARCHIVED, STATE_TRASHED)
ALL_STATES: tuple[str, ...] = (*STORED_STATES, STATE_DELETED)

# Hangi durumdan hangisine geçilebilir. Tanımsız geçiş reddedilir — sessizce
# yanlış duruma düşmek, yanlış durumu göstermekten daha kötü.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
	STATE_ACTIVE: frozenset({STATE_ARCHIVED, STATE_TRASHED}),
	STATE_ARCHIVED: frozenset({STATE_ACTIVE, STATE_TRASHED}),
	STATE_TRASHED: frozenset({STATE_ACTIVE, STATE_ARCHIVED, STATE_DELETED}),
	STATE_DELETED: frozenset(),
}


def derive(row: dict) -> str:
	"""Damgalardan durumu türet — alan boş olan eski kayıtlar için yedek yol.

	Sıra önemli: çöp, optimizasyondan baskındır. Optimize edilmiş bir dosya çöpe
	taşındığında iki damga da doludur; kullanıcı için anlamlı olan çöpte olması.
	"""
	if row.get("th_trashed_at"):
		return STATE_TRASHED
	if row.get("th_optimized_at"):
		return STATE_ARCHIVED
	return STATE_ACTIVE


def current(file_url: str) -> str:
	"""Dosyanın şu anki durumu.

	Aynı `file_url`'e birden çok `File` kaydı işaret edebiliyor (ölçüm: tek
	fiziksel dosyaya 39 kayda kadar). Durum dosyanın kendisine ait, kayda değil —
	bu yüzden ilk kayıt temsilci alınır ve yazma tüm kayıtlara uygulanır.
	"""
	row = frappe.db.get_value(
		"File",
		{"file_url": file_url},
		["th_media_state", "th_trashed_at", "th_optimized_at"],
		as_dict=True,
	)
	if not row:
		# Kayıt yoksa dosya kalıcı silinmiştir; denetim kaydı bunu doğrular.
		return STATE_DELETED
	return row.get("th_media_state") or derive(row)


def can_transition(source: str, target: str) -> bool:
	return target in ALLOWED_TRANSITIONS.get(source, frozenset())


def transition(file_url: str, target: str, *, commit: bool = False) -> dict:
	"""Durumu değiştir — tek kapı.

	`trash.py` ve `runner.py` damgayı yazdıktan sonra buraya uğrar; durum ile
	damganın ayrışması böylece imkânsız hâle gelir. Ayrışma gerçek bir riskti:
	denetim ekranı `target_state`'i damgadan okuyor, biri diğerinden şaşarsa
	satır yanlış ikon gösterirdi.
	"""
	if target not in ALL_STATES:
		frappe.throw(frappe._("Bilinmeyen medya durumu: {0}").format(target))

	source = current(file_url)
	if source == target:
		return {"file_url": file_url, "from": source, "to": target, "changed": False}

	if not can_transition(source, target):
		frappe.throw(
			frappe._("Geçersiz durum geçişi: {0} → {1} ({2})").format(source, target, file_url)
		)

	if target != STATE_DELETED:
		# `Deleted` yazılmaz — o noktada `File` kaydı zaten silinmiş oluyor.
		frappe.db.set_value(
			"File", {"file_url": file_url}, {"th_media_state": target}, update_modified=False
		)
		if commit:
			frappe.db.commit()

	return {"file_url": file_url, "from": source, "to": target, "changed": True}


def state_after_untrash(file_url: str) -> str:
	"""Çöpten çıkan dosya hangi duruma döner.

	Optimize edilmiş bir dosya çöpten çıkınca `Active` değil `Archived` olmalı —
	orijinali hâlâ arşivde duruyor ve geri alınabilir.
	"""
	row = frappe.db.get_value("File", {"file_url": file_url}, ["th_optimized_at"], as_dict=True)
	return STATE_ARCHIVED if (row or {}).get("th_optimized_at") else STATE_ACTIVE


def on_file_insert(doc, method: str | None = None) -> None:
	"""`File.after_insert` kancası — yeni dosya `Active` başlar.

	Patch mevcut kayıtları doldurur ama insert yolunu kapsamaz; bu kanca
	olmadan her yeni yükleme durumu BOŞ kalıyordu (monkey test yakaladı).
	Boş durum, filtrelerin yedek damga koşuluna düşmesine ve modelin yeni
	dosyalara hiç uygulanmamasına yol açardı.

	Klasörler kapsam dışı: durum dosyaya ait bir kavram.

	Best-effort — burada patlamak kullanıcının yüklemesini engellememeli.
	`db_set` değil `db.set_value`: `after_insert` içinde doc.save() tetiklemek
	sonsuz döngü riski taşır.
	"""
	try:
		if doc.get("is_folder"):
			return
		# Durumu ZATEN olan kayıt ezilmez. Normal yüklemede alan hiç dolu
		# gelmez; dolu gelmesinin tek yolu geri yüklemedir (`media/restore.py`,
		# `media/seller_backup.py`) ve orada yedekteki durum korunmalıdır.
		# Bu satır olmadan çöpteki bir dosya yedekten Active dönüyordu — dosya
		# çöp süresini atlayıp listeye geri sızıyordu (TUR-138 × TUR-131,
		# dayanıklılık koşumunda yakalandı, 14 Ağustos'tan beri açık kusurdu).
		if doc.get("th_media_state"):
			return
		frappe.db.set_value(
			"File", doc.name, "th_media_state", STATE_ACTIVE, update_modified=False
		)
	except Exception:
		frappe.log_error(
			title="media.states on_file_insert failed", message=frappe.get_traceback()
		)


def backfill(limit: int = 0) -> dict:
	"""Alanı boş olan kayıtları damgalardan doldur.

	Patch bunu bir kez çağırır; sonradan elle de çalıştırılabilir. Idempotent:
	dolu alanlara dokunmaz.
	"""
	filters = {"th_media_state": ["in", ["", None]], "is_folder": 0}
	rows = frappe.get_all(
		"File",
		filters=filters,
		fields=["name", "th_trashed_at", "th_optimized_at"],
		limit_page_length=limit or 0,
	)
	counts: dict[str, int] = {}
	for row in rows:
		state = derive(row)
		frappe.db.set_value("File", row["name"], "th_media_state", state, update_modified=False)
		counts[state] = counts.get(state, 0) + 1

	frappe.db.commit()
	return {"updated": len(rows), "by_state": counts}
