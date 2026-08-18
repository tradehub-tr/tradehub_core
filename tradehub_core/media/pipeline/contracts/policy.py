"""PolicyEngine sözleşmesi — slot politikası kayıt defteri ve karar kapıları.

Faz 2 çıktısı `tradehub_core/media/pipeline/policy/` zaten hazır ve şemaya uyumlu:
`schema/slot-policy.schema.json` v1.3.0 + 9 slot politikası + `content_rules.json`
+ `quota.schema.json` + `retention.schema.json`. Bu sözleşme o JSON'ları
**okuyup karara çeviren** katmanın imzasıdır; politika içeriğini yeniden
tanımlamaz.

Katmanlar (FR-001…FR-018 ile birebir)
--------------------------------------
    L0  slotsuz  — bugünkü davranış. `upload_policy.check()` slot bilmeden
                   yasak liste + boyut + magic byte uygular. KORUNUR.
    L1  accept   — dosya AÇILMADAN: mime/uzantı/bayt/megapiksel tavanı.
    L2  require  — görsel AÇILDIKTAN sonra: kısa kenar, alan, oran, adet.
    L3  master   — üretim parametreleri (ret değil, üretim kararı).
    L4  quality  — SSIM kapısı.
    L5  content  — içerik uygunluk kuralları (asenkron, FR-055).

Her katmanın ihlal aksiyonu politikadaki `on_violation.<katman>` alanından
gelir; sabit değildir. Ürün görselinde `accept`/`require` → `reject`,
`master`/`quality` → `warn`; belge slotunda geometri `warn` (FR-027).

TEK KAYNAK KURALI (FR-147)
--------------------------
İki politika seti aynı anda yürürlükte olamaz. Bugün `tradehub_core/media/pipeline/policy/slots/`
(9 dosya, şema uyumlu) ile `docs/standards/policies/` (T-024 testinin okuduğu
set) yan yana duruyor. Sözleşme tek bir kök dizin alır; hangi kökün kanonik
olduğu kurulum kararıdır ve `PolicyEngine.source_root()` ile RAPORLANIR —
sessiz kalmak bu ihlali görünmez kılardı.

İDEMPOTENSİ
-----------
Bütün metotlar SAF ve yan etkisizdir: aynı politika + aynı girdi her zaman aynı
`Decision`. Politika dosyaları çalışma anında değişmez varsayılır; `reload()`
açık bir çağrıdır ve tek yan etkili metottur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence, Tuple, runtime_checkable

from tradehub_core.media.pipeline.contracts.image import ImageProbe, MasterSpec, RenditionSpec
from tradehub_core.media.pipeline.contracts.video import VideoProbe, VideoRenditionSpec

# ── Katmanlar ───────────────────────────────────────────────────────────

LAYER_ACCEPT: str = "accept"
LAYER_REQUIRE: str = "require"
LAYER_MASTER: str = "master"
LAYER_QUALITY: str = "quality"
LAYER_CONTENT: str = "content_rules"
LAYERS: Tuple[str, ...] = (LAYER_ACCEPT, LAYER_REQUIRE, LAYER_MASTER, LAYER_QUALITY, LAYER_CONTENT)

# ── Aksiyonlar ──────────────────────────────────────────────────────────
#
# Sıra ÖNEMLİ: FR-049 birden çok kural tetiklendiğinde EN YÜKSEK aksiyonun
# uygulanmasını, uyarıların ise birikimli listelenmesini istiyor. `ACTIONS`
# listesindeki indeks o "yükseklik" tanımıdır.

ACTION_PASS: str = "pass"
ACTION_WARN: str = "warn"
ACTION_AUTO_FIX: str = "auto_fix"
ACTION_MANUAL_REVIEW: str = "manual_review"
ACTION_REJECT: str = "reject"
ACTIONS: Tuple[str, ...] = (
	ACTION_PASS,
	ACTION_WARN,
	ACTION_AUTO_FIX,
	ACTION_MANUAL_REVIEW,
	ACTION_REJECT,
)

# Politika durumu — FR-005: `active` olabilmesi için `open_questions` boş VE
# hiçbir `encoder_quality` null olmamalı.
STATUS_DRAFT: str = "draft"
STATUS_ACTIVE: str = "active"


def en_yuksek_aksiyon(aksiyonlar: Sequence[str]) -> str:
	"""FR-049 — verilen aksiyonların en yükseği. Boş liste `pass` döner."""
	sirali = [a for a in aksiyonlar if a in ACTIONS]
	if not sirali:
		return ACTION_PASS
	return max(sirali, key=ACTIONS.index)


@dataclass(frozen=True)
class Violation:
	"""Tek bir kural ihlali.

	`measured` ve `expected` alanları kullanıcı mesajının somut çözüm cümlesini
	(FR-063) üretir: "kısa kenar 640 px, en az 1000 px olmalı". `None` ise
	ölçüm YAPILAMAMIŞTIR ve mesajda sayı gösterilmez (FR-066).
	"""

	code: str
	layer: str
	sebep: str
	action: str = ACTION_REJECT
	retryable: bool = False
	message_key: str = ""
	measured: Optional[Any] = None
	expected: Optional[Any] = None
	detay: Dict[str, Any] = field(default_factory=dict)

	def __post_init__(self) -> None:
		if self.action not in ACTIONS:
			raise ValueError(f"Bilinmeyen aksiyon: {self.action!r}")
		if self.layer not in LAYERS:
			raise ValueError(f"Bilinmeyen katman: {self.layer!r}")


@dataclass(frozen=True)
class Decision:
	"""Bir kapının sonucu.

	`allowed` yalnız `action == reject` OLMADIĞINDA `True`'dur; uyarılar
	yüklemeyi durdurmaz ama yanıtta taşınır. Bu ayrım FR-060'ın ta kendisi:
	istemci metne değil `(kod, retryable)` çiftine bakar.
	"""

	slot_key: str
	action: str = ACTION_PASS
	violations: Tuple[Violation, ...] = ()
	warnings: Tuple[Violation, ...] = ()
	notes: Tuple[str, ...] = ()

	def __post_init__(self) -> None:
		if self.action not in ACTIONS:
			raise ValueError(f"Bilinmeyen aksiyon: {self.action!r}")

	@property
	def allowed(self) -> bool:
		return self.action != ACTION_REJECT

	@property
	def first_code(self) -> str:
		"""İstemcinin göstereceği tek kod — ilk RET ihlali, yoksa boş dizge."""
		return self.violations[0].code if self.violations else ""

	@property
	def retryable(self) -> bool:
		"""Ret tekrar denenebilir mi. Ret yoksa `False` (denenecek bir şey yok)."""
		return bool(self.violations) and all(v.retryable for v in self.violations)

	def merge(self, other: "Decision") -> "Decision":
		"""İki kararı birleştir — FR-049: en yüksek aksiyon, birikimli uyarılar.

		Saf: hiçbir tarafı değiştirmez, yeni `Decision` döndürür.
		"""
		if other.slot_key != self.slot_key:
			raise ValueError(f"Farklı slotlar birleştirilemez: {self.slot_key!r} / {other.slot_key!r}")
		return Decision(
			slot_key=self.slot_key,
			action=en_yuksek_aksiyon((self.action, other.action)),
			violations=self.violations + other.violations,
			warnings=self.warnings + other.warnings,
			notes=self.notes + other.notes,
		)


@dataclass(frozen=True)
class EffectiveLimits:
	"""Katmanların KESİŞİMİNDEN doğan gerçek tavanlar (FR-007, FR-076, NFR-047).

	Bir slot politikası global tavanı GEVŞETEMEZ: efektif tavan
	`min(slot, plan, platform)`'dur. Bu tipin varlık sebebi, üç sayının
	nerede kesiştiğinin tek yerde görünmesi — bugün `upload_policy.
	effective_max()` yalnız (tür, platform) kesişimini biliyor.
	"""

	max_bytes: int
	max_megapixels_hard: float = 0.0
	max_count: int = 0
	source: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SlotPolicy:
	"""Tek bir slotun politikası — JSON'un tipli sarmalayıcısı.

	Ham sözlük `raw` alanında KORUNUR: şema 20'den fazla kök anahtar taşıyor
	(`known_conflicts`, `pending_admin_decisions`, `render_box`...) ve hepsini
	dataclass alanına çevirmek, şema her büyüdüğünde bu dosyayı değiştirmek
	demekti. Tipli alanlar yalnız KARAR VEREN bloklardır.
	"""

	slot_key: str
	schema_version: str
	status: str = STATUS_DRAFT
	roles: Tuple[str, ...] = ()
	accept: Mapping[str, Any] = field(default_factory=dict)
	require: Mapping[str, Any] = field(default_factory=dict)
	master: Mapping[str, Any] = field(default_factory=dict)
	quality: Mapping[str, Any] = field(default_factory=dict)
	profiles: Tuple[Mapping[str, Any], ...] = ()
	video: Mapping[str, Any] = field(default_factory=dict)
	on_violation: Mapping[str, Any] = field(default_factory=dict)
	messages: Mapping[str, Any] = field(default_factory=dict)
	bound_to: Tuple[Mapping[str, Any], ...] = ()
	raw: Mapping[str, Any] = field(default_factory=dict)

	@property
	def is_video(self) -> bool:
		return bool(self.video)

	@property
	def error_prefix(self) -> str:
		"""`on_violation.error_code_prefix` — kod üretiminin ön eki."""
		return str(self.on_violation.get("error_code_prefix") or "media")

	def action_for(self, layer: str) -> str:
		"""Katmanın ihlal aksiyonu; tanımsızsa `on_violation.default`."""
		deger = self.on_violation.get(layer) or self.on_violation.get("default") or ACTION_REJECT
		return str(deger)


@runtime_checkable
class PolicyEngine(Protocol):
	"""Slot politikası kayıt defteri ve karar kapıları.

	Uygulamalar dosya sisteminden (üretim) ya da bellekten (test) okur.
	Hiçbir metot `frappe`'ye, veritabanına ya da ağa dokunmaz — politika
	kararı saf bir fonksiyondur ve öyle kalmalıdır, aksi hâlde aynı dosya
	iki ortamda iki farklı sonuç verirdi.
	"""

	def source_root(self) -> str:
		"""Politikaların okunduğu kanonik kök. FR-147: hangi setin yürürlükte
		olduğu her zaman raporlanabilir olmalı."""
		...

	def slots(self) -> Tuple[str, ...]:
		"""Kayıtlı slot anahtarları, alfabetik. Yan etkisiz."""
		...

	def load(self, slot_key: str) -> SlotPolicy:
		"""Slot politikasını getir. Bilinmeyen slot → `PolicyNotFound`.

		İdempotent ve önbelleklenebilir: aynı anahtar aynı nesneyi verir.
		"""
		...

	def reload(self) -> int:
		"""Politikaları diskten yeniden oku, yüklenen sayısını döndür.

		Sözleşmenin TEK yan etkili metodu. Şemaya uymayan bir dosya varsa
		`PolicyError` atar ve HİÇBİR politika değişmez (ya hep ya hiç) —
		yarım yüklenmiş bir kayıt defteri, hangi slotun eski hangisinin yeni
		olduğu bilinmeyen bir sistem demektir.
		"""
		...

	def effective_limits(self, slot_key: str, *, plan_max_bytes: int = 0) -> EffectiveLimits:
		"""Slot × plan × platform kesişimi (FR-007, FR-076).

		`plan_max_bytes=0` "plan sınırı yok" demektir ve kesişime GİRMEZ —
		`None` ile 0'ı ayırmamak bilinçli: kota tarafında `None` fail-open
		anlamına geliyor (FR-071) ve o karar burada değil kota katmanında.
		"""
		...

	def check_accept(
		self,
		slot_key: str,
		*,
		file_name: str,
		size_bytes: int,
		sniffed_type: str = "",
		declared_mime: str = "",
	) -> Decision:
		"""L1 — dosya AÇILMADAN verilen karar.

		Uzantıya değil içerik imzasına güvenilir (FR-009): `sniffed_type`
		çağıran tarafından `upload_policy.sniff()` ile doldurulur. Uyuşmazlık
		ret DEĞİL uyarıdır — bugünkü davranış korunuyor (sahadaki geçerli
		dosyaları kesmemek için), tehlikeli içerik ise zaten L0'da reddedilir.
		"""
		...

	def check_geometry(self, slot_key: str, probe: ImageProbe, *, count: int = 1) -> Decision:
		"""L2 — görsel AÇILDIKTAN sonra: kısa kenar, alan, oran, adet.

		Karşılaştırmalar `>=` ile yapılır, eşitlik GEÇERLİDİR (FR-015).
		Oran kontrolü BAĞIL toleransla: `min |r_ölçülen - r| / r <= tolerans`
		(FR-016). `probe.readable=False` ise geometri ölçülemez ve karar
		`decode_failed` ile RET olur.
		"""
		...

	def check_video(self, slot_key: str, probe: VideoProbe) -> Decision:
		"""L2 — video için süre, çözünürlük, oran, bitrate kapısı.

		`probe.measured=False` ise (ffprobe yok) karar güvenli tarafa düşer:
		ret değil, `manual_review` — dosyayı ölçemediğimiz için suçlamak
		yanlış, sessizce geçirmek riskli (NFR-043 + FR-134).
		"""
		...

	def master_spec(self, slot_key: str) -> MasterSpec:
		"""Slotun master üretim parametreleri. `master` bloğu eksikse
		`PolicyError` — master'sız bir slot üretim yapamaz."""
		...

	def rendition_specs(self, slot_key: str) -> Tuple[RenditionSpec, ...]:
		"""Görsel türev merdiveni, genişliğe göre ARTAN sırada.

		Sıra sözleşmenin parçası: `srcset` üretimi ve komşu-profil oranı
		kontrolü (FR-036, ardışık oran < 1,25 ise profiller birleştirilir)
		sıralı liste varsayar.
		"""
		...

	def video_rendition_specs(self, slot_key: str) -> Tuple[VideoRenditionSpec, ...]:
		"""Video rendition listesi. Video olmayan slotta boş demet döner —
		hata DEĞİL: çağıran `is_video` bakmak zorunda kalmasın."""
		...

	def quality_threshold(self, slot_key: str, content_class: str) -> float:
		"""`quality.target_ssim_per_class` eşiği. Sınıf tanımsızsa 0.0 döner
		ve kalite kapısı uygulanmaz (eşiksiz kapı, ölçülmemiş eşikle
		reddetmekten iyidir — FR-057)."""
		...

	def validate(self, slot_key: str = "") -> Decision:
		"""Politikanın KENDİSİNİ doğrula — şema, değişmezler, kaynak alanları.

		Boş `slot_key` tüm kayıt defterini doğrular. FR-003 bunun CI'da
		koşmasını, FR-148 tek bir çıkış koduyla sonuç vermesini istiyor:
		`Decision.allowed` o çıkış kodudur.

		Kontrol edilen değişmezler (docs/standards/README.md §6):
		  D1  `master.max_long_edge² / 1e6 >= master.max_megapixels` (FR-032)
		  D2  `min_long_edge <= max_long_edge`
		  D3  `accept.extensions` ile `accept.mime` ayrışmamalı (FR-008)
		  D4  her profilde `derived_from` dolu (FR-034)
		  D5  `status=active` ⟹ `open_questions` boş VE `encoder_quality`
		      hiçbir yerde null (FR-005)
		"""
		...


__all__ = [
	"LAYER_ACCEPT",
	"LAYER_REQUIRE",
	"LAYER_MASTER",
	"LAYER_QUALITY",
	"LAYER_CONTENT",
	"LAYERS",
	"ACTION_PASS",
	"ACTION_WARN",
	"ACTION_AUTO_FIX",
	"ACTION_MANUAL_REVIEW",
	"ACTION_REJECT",
	"ACTIONS",
	"STATUS_DRAFT",
	"STATUS_ACTIVE",
	"Violation",
	"Decision",
	"EffectiveLimits",
	"SlotPolicy",
	"PolicyEngine",
	"en_yuksek_aksiyon",
]
