"""Medya durum makinesi — mevcut yaşam döngüsünü GEÇERSİZ KILMAZ, üstüne koyar.

MEVCUT DURUM (OKUNDU, DEĞİŞTİRİLMEDİ)
-------------------------------------
`tradehub_core/media/states.py` dosyanın YAŞAM DÖNGÜSÜNÜ tanımlıyor ve tek
kapıdan geçiriyor (`transition()`):

    Active   ──optimize──→  Archived
    Archived ──restore───→  Active
    Active   ──trash─────→  Trashed
    Archived ──trash─────→  Trashed
    Trashed  ──untrash───→  Active | Archived
    Trashed  ──delete────→  Deleted            (terminal)

`Active → Deleted` yoktur; kalıcı silme yalnız çöpten yapılır. Bu iki adımlı
akış bilinçli bir karardır ve BURADA KORUNUR.

İki komşu sözlük daha var, ikisi de ayrı eksende:

    av.py:93-96          pending / clean / infected / failed   (tarama sonucu)
    transcode.py:72-74   processing / ready / failed           (video işi)

BU MODÜLÜN EKLEDİĞİ
-------------------
Yukarıdaki üç sözlüğün hiçbiri "dosya kabul edildi mi, master üretildi mi,
türevler hazır mı" sorusunu cevaplamıyor. `Active` bugün hem "az önce yüklendi,
hiç işlenmedi" hem de "master + 7 türev hazır" anlamına geliyor — canlı ölçüm
bunu doğruluyor: `th_media_width` dolu olan kayıt sayısı 2853'te 0.

Bu modül DÖRDÜNCÜ bir eksen açar: **ingest** (alım hattı). Yaşam döngüsü
ekseniyle DİK'tir, onu ezmez:

    Received ──screen──→ Screened ──evaluate──→ Validated ──master──→ Mastered
                │                    │                                  │
                │                    └──reject──→ Rejected (terminal)   ├─derive→ Ready
                └──infected──→ Quarantined (terminal)                   └─fail──→ Failed
    Failed ──retry──→ Screened

İKİ EKSENİN İLİŞKİSİ (sözleşme)
-------------------------------
    ingest=Ready        ⟺  lifecycle ∈ {Active, Archived}
    ingest=Rejected     ⟹  lifecycle kaydı HİÇ OLUŞMAZ (File yazılmadan önce)
    ingest=Quarantined  ⟹  lifecycle=Trashed ya da kayıt yok; dosya
                            `private/media_quarantine/` altında (av.py:103)
    ingest ∈ {Received, Screened, Validated, Mastered, Failed}
                        ⟹  lifecycle=Active (dosya duruyor, henüz hazır değil)

`allowed_lifecycle_for()` bu tabloyu makine olarak döndürür; `consistent()`
bir çiftin geçerli olup olmadığını söyler. Sözleşmeyi yorumda bırakmak, iki
ekseni farklı yerlerde farklı yorumlamanın kapısını açık bırakırdı.

AYNA VE DOĞRULAMA
-----------------
`tradehub_core/media/states.py` modül düzeyinde `import frappe` yapıyor; bu
paket frappe'siz olmak zorunda olduğu için yaşam döngüsü tablosu burada
AYNALANIR. Ayna sessizce eskiyebilir — bu yüzden `tests/test_state_machine.py`
kaynak dosyayı `ast` ile ayrıştırıp tabloyu bire bir karşılaştırır; ayrışma
testi düşürür. Frappe varsa `lifecycle_transition()` gerçek modüle DELEGE eder,
kendi kopyasını kullanmaz.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Eksen 1: yaşam döngüsü (AYNA — kaynak: tradehub_core/media/states.py) ──

LIFECYCLE_ACTIVE: str = "Active"
LIFECYCLE_ARCHIVED: str = "Archived"
LIFECYCLE_TRASHED: str = "Trashed"
LIFECYCLE_DELETED: str = "Deleted"

LIFECYCLE_STORED: tuple[str, ...] = (LIFECYCLE_ACTIVE, LIFECYCLE_ARCHIVED, LIFECYCLE_TRASHED)
LIFECYCLE_ALL: tuple[str, ...] = (*LIFECYCLE_STORED, LIFECYCLE_DELETED)

#: states.py:63-68 `ALLOWED_TRANSITIONS` aynası. TESTLE DOĞRULANIR.
LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
	LIFECYCLE_ACTIVE: frozenset({LIFECYCLE_ARCHIVED, LIFECYCLE_TRASHED}),
	LIFECYCLE_ARCHIVED: frozenset({LIFECYCLE_ACTIVE, LIFECYCLE_TRASHED}),
	LIFECYCLE_TRASHED: frozenset({LIFECYCLE_ACTIVE, LIFECYCLE_ARCHIVED, LIFECYCLE_DELETED}),
	LIFECYCLE_DELETED: frozenset(),
}

# ── Eksen 2: tarama (AYNA — kaynak: tradehub_core/media/av.py:93-96) ──

SCAN_PENDING: str = "pending"
SCAN_CLEAN: str = "clean"
SCAN_INFECTED: str = "infected"
SCAN_FAILED: str = "failed"
SCAN_ALL: tuple[str, ...] = (SCAN_PENDING, SCAN_CLEAN, SCAN_INFECTED, SCAN_FAILED)

# ── Eksen 3: alım hattı (YENİ) ──

INGEST_RECEIVED: str = "Received"
INGEST_SCREENED: str = "Screened"
INGEST_VALIDATED: str = "Validated"
INGEST_MASTERED: str = "Mastered"
INGEST_READY: str = "Ready"
INGEST_REJECTED: str = "Rejected"
INGEST_QUARANTINED: str = "Quarantined"
INGEST_FAILED: str = "Failed"

INGEST_ALL: tuple[str, ...] = (
	INGEST_RECEIVED,
	INGEST_SCREENED,
	INGEST_VALIDATED,
	INGEST_MASTERED,
	INGEST_READY,
	INGEST_REJECTED,
	INGEST_QUARANTINED,
	INGEST_FAILED,
)

#: Terminal alım durumları. `Rejected` ve `Quarantined` KARARDIR, dönüşü yoktur
#: (karantinadan çıkarmak `av.release_from_quarantine()` ile YENİ bir alımdır,
#: aynı kaydın durum değişimi değil). `Ready` de terminaldir: oradan sonrası
#: yaşam döngüsü ekseninin işidir.
INGEST_TERMINAL: frozenset[str] = frozenset(
	{INGEST_READY, INGEST_REJECTED, INGEST_QUARANTINED}
)

INGEST_TRANSITIONS: dict[str, frozenset[str]] = {
	# Yüklendi, henüz hiçbir şey bilinmiyor.
	INGEST_RECEIVED: frozenset({INGEST_SCREENED, INGEST_QUARANTINED, INGEST_FAILED}),
	# Tarama temiz; künye çıkarıldı. Politika değerlendirmesi sırada.
	INGEST_SCREENED: frozenset(
		{INGEST_VALIDATED, INGEST_REJECTED, INGEST_QUARANTINED, INGEST_FAILED}
	),
	# Politika geçildi; master üretimi sırada.
	INGEST_VALIDATED: frozenset({INGEST_MASTERED, INGEST_FAILED}),
	# Master hazır; türevler sırada. Türev yoksa doğrudan Ready.
	INGEST_MASTERED: frozenset({INGEST_READY, INGEST_FAILED}),
	# `Failed` geçicidir: kuyruk yeniden dener (core/jobs.py MAX_ATTEMPTS).
	# Tarama zaten yapıldığı için yeniden deneme `Screened`'a döner, başa değil.
	INGEST_FAILED: frozenset({INGEST_SCREENED, INGEST_REJECTED}),
	INGEST_READY: frozenset(),
	INGEST_REJECTED: frozenset(),
	INGEST_QUARANTINED: frozenset(),
}

#: İki eksenin sözleşmesi. Modül başlığındaki tablonun makine hâli.
INGEST_TO_LIFECYCLE: dict[str, frozenset[str]] = {
	INGEST_RECEIVED: frozenset({LIFECYCLE_ACTIVE}),
	INGEST_SCREENED: frozenset({LIFECYCLE_ACTIVE}),
	INGEST_VALIDATED: frozenset({LIFECYCLE_ACTIVE}),
	INGEST_MASTERED: frozenset({LIFECYCLE_ACTIVE}),
	INGEST_FAILED: frozenset({LIFECYCLE_ACTIVE}),
	INGEST_READY: frozenset({LIFECYCLE_ACTIVE, LIFECYCLE_ARCHIVED}),
	# Kayıt hiç oluşmaz; "yok" durumu `None` ile ifade edilir.
	INGEST_REJECTED: frozenset(),
	INGEST_QUARANTINED: frozenset({LIFECYCLE_TRASHED}),
}


class InvalidTransition(ValueError):
	"""Tanımsız geçiş. Sessizce yanlış duruma düşmek, hata vermekten kötüdür."""


@dataclass(frozen=True)
class TransitionResult:
	axis: str
	source: str
	target: str
	changed: bool

	def to_dict(self) -> dict:
		return {
			"axis": self.axis,
			"from": self.source,
			"to": self.target,
			"changed": self.changed,
		}


def _guard(table: dict[str, frozenset[str]], axis: str, source: str, target: str) -> TransitionResult:
	if target not in table:
		raise InvalidTransition(f"Bilinmeyen {axis} durumu: {target!r}")
	if source not in table:
		raise InvalidTransition(f"Bilinmeyen {axis} durumu: {source!r}")
	if source == target:
		return TransitionResult(axis, source, target, False)
	if target not in table[source]:
		raise InvalidTransition(f"Geçersiz {axis} geçişi: {source} → {target}")
	return TransitionResult(axis, source, target, True)


def can_ingest(source: str, target: str) -> bool:
	return target in INGEST_TRANSITIONS.get(source, frozenset())


def ingest_transition(source: str, target: str) -> TransitionResult:
	"""Alım ekseninde geçiş. Geçersizse `InvalidTransition`."""
	return _guard(INGEST_TRANSITIONS, "ingest", source, target)


def can_lifecycle(source: str, target: str) -> bool:
	"""Yaşam döngüsü geçişi izinli mi.

	Frappe varsa KAYNAK modüle sorar; yoksa aynaya bakar. Böylece üretimde tek
	doğruluk kaynağı `tradehub_core/media/states.py` olarak kalır.
	"""
	try:
		from tradehub_core.media.states import can_transition

		return bool(can_transition(source, target))
	except Exception:
		return target in LIFECYCLE_TRANSITIONS.get(source, frozenset())


def lifecycle_transition(source: str, target: str) -> TransitionResult:
	"""Yaşam döngüsü geçişinin geçerliliğini DOĞRULAR — yazma YAPMAZ.

	Yazma `tradehub_core.media.states.transition()`'ın işidir ve orada kalır:
	`File` kaydına yazan tek kapı bir tane olmalı. Bu fonksiyon o kapıya
	gitmeden önce kararı frappe'siz doğrulamak içindir.
	"""
	if source not in LIFECYCLE_ALL:
		raise InvalidTransition(f"Bilinmeyen lifecycle durumu: {source!r}")
	if target not in LIFECYCLE_ALL:
		raise InvalidTransition(f"Bilinmeyen lifecycle durumu: {target!r}")
	if source == target:
		return TransitionResult("lifecycle", source, target, False)
	if not can_lifecycle(source, target):
		raise InvalidTransition(f"Geçersiz lifecycle geçişi: {source} → {target}")
	return TransitionResult("lifecycle", source, target, True)


def allowed_lifecycle_for(ingest: str) -> frozenset[str]:
	"""Verilen alım durumunda hangi yaşam döngüsü durumları meşru."""
	if ingest not in INGEST_TO_LIFECYCLE:
		raise InvalidTransition(f"Bilinmeyen ingest durumu: {ingest!r}")
	return INGEST_TO_LIFECYCLE[ingest]


def consistent(ingest: str, lifecycle: str | None) -> bool:
	"""İki eksenin çifti geçerli mi. `lifecycle=None` "kayıt yok" demektir."""
	izinli = allowed_lifecycle_for(ingest)
	if lifecycle is None:
		return not izinli or ingest == INGEST_QUARANTINED
	return lifecycle in izinli


def ingest_from_decision(allow: bool, scan: str = SCAN_CLEAN) -> str:
	"""PolicyEngine kararı + tarama sonucu → alım durumu.

	Sıra ANLAMLIDIR: enfekte dosya, politikayı geçse bile karantinaya gider.
	Güvenlik kararı politika kararını EZER.
	"""
	if scan == SCAN_INFECTED:
		return INGEST_QUARANTINED
	if not allow:
		return INGEST_REJECTED
	return INGEST_VALIDATED


def terminal(ingest: str) -> bool:
	return ingest in INGEST_TERMINAL
