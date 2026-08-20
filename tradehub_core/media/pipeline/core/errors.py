"""Ortak ihlal/hata sözleşmesi — makine kodu + iki dilde mesaj + düzeltme ipucu.

Neden ayrı bir sözleşme: bugün üretimde iki ayrı ret dili var.

    tradehub_core/media/upload_policy.py:99  `Kod(kod, retryable)` — düz kod
    tradehub_core/media/gates.py:31          `GateResult(passed, reason)` — düz sebep

İkisi de doğru çalışıyor ama ikisi de kullanıcıya NE YAPACAĞINI söylemiyor;
istemci kodu metne değil koda bakmak zorunda olduğu için metin de tek dilde
kalıyor. Bu modül üçünü tek nesnede birleştirir:

    code      makine okur       "product_image_short_edge_too_small"
    message   insan okur        {"tr": …, "en": …}
    hint      insan uygular     {"tr": "Fotoğrafı en yüksek…", "en": …}

`retryable` alanı upload_policy.py:93-97'deki kuralı KORUR: kullanıcının
dosyasıyla ilgili hatalar tekrar denenmez (aynı dosya aynı sonucu verir),
geçici sistem hataları denenir. Politika ihlallerinin tamamı kullanıcı
dosyasıyla ilgilidir → `retryable=False`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Aksiyonlar ──────────────────────────────────────────────────────────
#
# Slot politikalarındaki `on_violation` bloğu bu dört değeri kullanır. Sıralama
# ANLAMLIDIR: bir dosyada birden çok ihlal olursa en yüksek aksiyon kazanır
# (content_rules.json `decision_model.aggregation` ile aynı kural).
ACTION_PASS: str = "pass"
ACTION_IGNORE: str = "ignore"
ACTION_WARN: str = "warn"
ACTION_AUTO_FIX: str = "auto_fix"
ACTION_REVIEW: str = "review"
ACTION_REJECT: str = "reject"

#: `manual_review` ile `review` AYNI ŞEYDİR, iki dosyada iki türlü yazılmış:
#: slot politikaları `review` diyor (product-image.json `text_area_ratio`,
#: product-video.json `ffprobe_readable`, 12 kural), `content_rules.json`
#: `decision_model.actions` ise `manual_review` diyor. İkisini ayrı aksiyon
#: saymak, aynı kararın sıralamada farklı yükseklik almasına yol açardı —
#: `manual_review` bilinmeyen sayılıp `pass` seviyesine düşerdi ve moderasyon
#: kuyruğuna gitmesi gereken dosya sessizce geçerdi. Tek yazıma indirgemek
#: veri dosyalarını değiştirmeyi gerektirir; kapanış raporunda R-02 olarak
#: kayıtlı. O yapılana kadar ikisi aynı sıraya bağlanır.
ACTION_MANUAL_REVIEW: str = "manual_review"

ACTION_RANK: dict[str, int] = {
	ACTION_PASS: 0,
	# `ignore`: kural değerlendirildi, tetiklendi, ama politika "bunu umursama"
	# diyor (category-banner.json `bottom_third_text_overlap`). `pass` ile aynı
	# yükseklikte ama AYRI bir değer: raporda "hiç bakılmadı" ile "bakıldı,
	# önemsenmedi" karışmasın.
	ACTION_IGNORE: 0,
	ACTION_WARN: 1,
	ACTION_AUTO_FIX: 2,
	ACTION_REVIEW: 3,
	ACTION_MANUAL_REVIEW: 3,
	ACTION_REJECT: 4,
}

#: Yüklemeyi DURDURAN aksiyonlar. `auto_fix` ve `warn` durdurmaz: ilki sunucu
#: düzeltir, ikincisi kullanıcıya gösterilir ve kayıt yine oluşur.
BLOCKING_ACTIONS: frozenset[str] = frozenset(
	{ACTION_REVIEW, ACTION_MANUAL_REVIEW, ACTION_REJECT}
)

#: Kullanıcıya HİÇ gösterilmeyen aksiyonlar — ihlal listesine girmez.
SILENT_ACTIONS: frozenset[str] = frozenset({ACTION_PASS, ACTION_IGNORE})


def highest_action(actions) -> str:
	"""En yüksek aksiyon. Boş girdide `pass`."""
	best = ACTION_PASS
	for a in actions:
		if ACTION_RANK.get(a, 0) > ACTION_RANK[best]:
			best = a
	return best


@dataclass(frozen=True)
class Violation:
	"""Tek bir kural ihlali.

	`block` politikanın hangi bölümünden geldiğini söyler (`accept`, `require`,
	`master`, `quality`, `content_rules`, `video`, `security`, `policy`).
	`on_violation` sözlüğü aksiyonu blok bazında belirlediği için bu alan
	dekoratif değil, kararın girdisidir.
	"""

	code: str
	rule: str
	block: str
	action: str
	message: dict[str, str] = field(default_factory=dict)
	hint: dict[str, str] = field(default_factory=dict)
	observed: object = None
	expected: object = None
	retryable: bool = False
	source: str = ""

	@property
	def blocking(self) -> bool:
		return self.action in BLOCKING_ACTIONS

	def to_dict(self) -> dict:
		return {
			"code": self.code,
			"rule": self.rule,
			"block": self.block,
			"action": self.action,
			"message": dict(self.message),
			"hint": dict(self.hint),
			"observed": self.observed,
			"expected": self.expected,
			"retryable": self.retryable,
			"source": self.source,
		}


@dataclass(frozen=True)
class SkippedRule:
	"""Değerlendirilemeyen kural — sessizce "geçti" saymamak için kayda geçer.

	content_rules.json `preprocessing.skip_if` bunu zaten istiyor: ölçülemeyen
	metrik `pass` döner ve sebebi `not_measurable` olarak loglanır. Sessiz
	geçiş, kalibre edilmemiş bir eşiğin "çalışıyor" sanılmasının yoludur.
	"""

	rule: str
	block: str
	reason: str
	missing_input: str = ""

	def to_dict(self) -> dict:
		return {
			"rule": self.rule,
			"block": self.block,
			"reason": self.reason,
			"missing_input": self.missing_input,
		}
