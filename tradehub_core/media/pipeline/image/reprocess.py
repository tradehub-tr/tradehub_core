"""T-064 — İdempotensi: motorun kendi çıktısını TEKRAR encode etme.

**Çözdüğü problem.** Kayıplı encode geri döndürülemez. Bir WebP türevi ikinci
kez WebP'ye yazılırsa (kuyruk işi iki kez koştu, migration tekrar çalıştı,
kullanıcı türevi tekrar yükledi) piksel kaybı ÜST ÜSTE biner — "nesil kaybı".
Mevcut motorda bunun tek koruması `tradehub_core/media/gates.py` içindeki
`already_optimized` kapısıdır ve o kapı bir DB alanına (`optimized_at`) bakar:
DB kaydı yoksa koruma da yok. 4.958 dosyalık canlı korpusta 1.166 YETİM disk
dosyası var (`docs/reports/08-canli-olcum.md`) — yani DB'ye bakan koruma tam da
bu dosyalarda çalışmaz.

Bu modül korumayı **içeriğe** taşır:

  1. **Türetme anahtarı** (`derivation_key`) — (master hash, slot, profil,
     biçim, kırpma, motor sürümü) beşlisinin sha256'sı. Aynı beşli aynı
     anahtarı verir; anahtar defterdeyse üretim ATLANIR.
  2. **İçerik parmak izi** — üretilen her türevin sha256'sı deftere yazılır.
     Bir bayt dizisi deftere kayıtlıysa o KESİNLİKLE motor çıktısıdır ve
     kaynak olarak kullanılamaz.
  3. **Yapısal sezgi** (`structural_signature`) — defter yoksa bile bir dosyanın
     motor çıktısına BENZEDİĞİ söylenebilir: biçim WebP/AVIF, EXIF yok, GPS
     yok ve genişlik politikadaki profil genişliklerinden biri. Bu bir KANIT
     DEĞİLDİR ve öyle raporlanır (`confidence="heuristic"`).

**Neden yeniden yazılmadı.** Karar mantığı `gates.check_before/check_after` ile
aynı fikirdedir ve o kapılar burada TEKRAR YAZILMAZ; bu modül onların
göremediği tek şeyi ekler: dosyanın kendisi. `render.py` de sarılır, kopyalanmaz.

KULLANIM
--------
    from tradehub_core.media.pipeline.image.reprocess import RenditionLedger, render_idempotent

    defter = RenditionLedger.load("renditions.json")
    sonuc, karar = render_idempotent(master_baytlari, profil, ledger=defter)
    if karar.action == ACTION_SKIP:
        ...  # zaten üretilmiş, dokunma
    defter.save("renditions.json")
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tradehub_core.media.pipeline.image import render as render_mod
from tradehub_core.media.pipeline.image.render import (
	ENGINE_ID,
	ENGINE_VERSION,
	RenderError,
	RenditionProfile,
	RenditionResult,
)

# --- Sabitler ---------------------------------------------------------------

ACTION_RENDER: str = "render"
ACTION_SKIP: str = "skip"
ACTION_REFRESH: str = "refresh"
ACTIONS: tuple[str, ...] = (ACTION_RENDER, ACTION_SKIP, ACTION_REFRESH)

REASON_CROP_CHANGED: str = "crop_changed"
REASON_POLICY_CHANGED: str = "policy_changed"
REASON_ENGINE_UPGRADED: str = "engine_upgraded"
REPROCESS_REASONS: tuple[str, ...] = (
	REASON_CROP_CHANGED,
	REASON_POLICY_CHANGED,
	REASON_ENGINE_UPGRADED,
)

CONFIDENCE_EXACT: str = "exact"
"""Defterde bire bir içerik eşleşmesi — kanıt."""
CONFIDENCE_HEURISTIC: str = "heuristic"
"""Yapısal benzerlik — kanıt DEĞİL, uyarı."""
CONFIDENCE_NONE: str = "none"

# Motor çıktısı olabilecek biçimler. JPEG bilerek DIŞARIDA: canlı korpusun
# %75,5'i JPEG (docs/reports/08-canli-olcum.md) ve bunların ezici çoğunluğu
# kullanıcı yüklemesidir. JPEG'i "motor çıktısı" saymak, gerçek master'ları
# yanlışlıkla türev sanmaya yol açar — pahalı bir yanlış pozitif.
ENGINE_OUTPUT_FORMATS: tuple[str, ...] = ("WEBP", "AVIF")

EXIF_ORIENTATION_TAG: int = 274
EXIF_GPS_IFD_TAG: int = 34853


class ReprocessError(ValueError):
	"""İdempotensi ihlali: motor çıktısı kaynak olarak verilmeye çalışıldı."""


# --- Parmak izi -------------------------------------------------------------


def content_hash(data: bytes) -> str:
	"""İçeriğin sha256'sı — `tradehub_core/media/naming.py` ile aynı özet ailesi."""
	return hashlib.sha256(bytes(data)).hexdigest()


def crop_signature(crop_intent: Any) -> str:
	"""Kırpma niyetinin kararlı (deterministik) imzası.

	`None` → boş dize. Sözlük ise anahtarlar sıralanarak JSON'a yazılır; aynı
	niyet farklı anahtar sırasıyla gelirse aynı imzayı üretmelidir, yoksa
	idempotensi anahtarı gereksiz yere değişir ve her koşuda yeniden üretim
	tetiklenir.
	"""
	if crop_intent is None:
		return ""
	if isinstance(crop_intent, (str, bytes)):
		return hashlib.sha256(
			crop_intent.encode("utf-8") if isinstance(crop_intent, str) else crop_intent
		).hexdigest()[:16]
	try:
		metin = json.dumps(crop_intent, sort_keys=True, separators=(",", ":"), default=str)
	except Exception:
		metin = repr(crop_intent)
	return hashlib.sha256(metin.encode("utf-8")).hexdigest()[:16]


def derivation_key(
	*,
	master_sha256: str,
	slot_key: str,
	profile_name: str,
	fmt: str,
	crop_sig: str = "",
	engine_version: str = ENGINE_VERSION,
) -> str:
	"""Türevin kimliği. Bu beşliden biri değişirse türev BAYATTIR.

	`engine_version` bilerek anahtarın içindedir: encoder parametreleri
	değiştiğinde eski türev artık aynı çıktının kaydı değildir. Sürümü
	anahtarın dışında tutmak, motor güncellendikten sonra eski türevlerin
	sonsuza dek "güncel" görünmesi demek olurdu.
	"""
	ham = "|".join(
		[
			ENGINE_ID,
			engine_version,
			master_sha256,
			slot_key,
			profile_name,
			fmt.lower(),
			crop_sig,
		]
	)
	return hashlib.sha256(ham.encode("utf-8")).hexdigest()


# --- Defter -----------------------------------------------------------------


@dataclass
class RenditionRecord:
	"""Üretilmiş tek türevin kaydı. `frappe` bilmez — saf veri."""

	key: str
	master_sha256: str
	slot_key: str
	profile: str
	format: str
	width: int
	height: int
	bytes: int
	sha256: str
	quality: Any = None
	ssim: float = 0.0
	engine_version: str = ENGINE_VERSION
	crop_sig: str = ""
	created: float = 0.0
	passthrough: bool = False
	"""INV-05 fayda kapısı tüm biçimleri eledi ve KAYNAK olduğu gibi geçti. Bu
	kaydın `sha256`'sı master'ın kendisidir; içerik indeksine GİRMEZ (aşağıya
	bkz. `RenditionLedger.add`)."""

	@classmethod
	def from_result(
		cls, result: RenditionResult, *, master_sha256: str, crop_sig: str = ""
	) -> RenditionRecord:
		return cls(
			key=derivation_key(
				master_sha256=master_sha256,
				slot_key=result.slot_key,
				profile_name=result.profile.name,
				fmt=result.format,
				crop_sig=crop_sig,
			),
			master_sha256=master_sha256,
			slot_key=result.slot_key,
			profile=result.profile.name,
			format=result.format,
			width=result.width,
			height=result.height,
			bytes=result.size_bytes,
			sha256=content_hash(result.content),
			quality=result.quality,
			ssim=round(result.ssim, 6),
			engine_version=ENGINE_VERSION,
			crop_sig=crop_sig,
			created=time.time(),
			passthrough=bool(result.passthrough),
		)


@dataclass
class RenditionLedger:
	"""Türev defteri — anahtar → kayıt ve içerik özeti → kayıt.

	İki indeks tutar çünkü iki ayrı soruya cevap verir:
	  `by_key`      "bu türevi üretmiş miydim?"  (üretimi atlamak için)
	  `by_content`  "bu bayt dizisi benim çıktım mı?" (kaynağı reddetmek için)
	"""

	by_key: dict = field(default_factory=dict)
	by_content: dict = field(default_factory=dict)

	def __len__(self) -> int:
		return len(self.by_key)

	def add(self, record: RenditionRecord) -> RenditionRecord:
		"""Kaydı iki indekse de yaz — passthrough HARİÇ.

		Passthrough'da (INV-05 zinciri tükendi, kaynak olduğu gibi geçti)
		`sha256 == master_sha256`'dır. Bu kaydı içerik indeksine yazmak
		MASTER'IN KENDİSİNİ "motor çıktısı" ilan eder; bir sonraki profil
		aynı master'ı kaynak olarak verdiğinde `assert_not_engine_output`
		merdiveni ortasından koparır. Passthrough bir türev değil, kaynağın
		kendisidir; yeniden encode koruması ona uygulanmaz.
		"""
		if record.passthrough or record.sha256 == record.master_sha256:
			# Passthrough bir türev değil, yalnız değerlendirme sonucudur. Onu
			# `by_key`e de yazmak aynı profilin bir sonraki format halkasını
			# "hazır" sanıp atlatır; gerçek bir çıktı yokken idempotency iddiası
			# kurulamaz.
			return record
		self.by_key[record.key] = record
		self.by_content[record.sha256] = record
		return record

	def get(self, key: str) -> RenditionRecord | None:
		return self.by_key.get(key)

	def by_sha(self, sha: str) -> RenditionRecord | None:
		return self.by_content.get(sha)

	def records(self) -> tuple[RenditionRecord, ...]:
		return tuple(self.by_key.values())

	def for_master(self, master_sha256: str) -> tuple[RenditionRecord, ...]:
		return tuple(r for r in self.by_key.values() if r.master_sha256 == master_sha256)

	# ── kalıcılık ────────────────────────────────────────────────────

	def to_json(self) -> str:
		return json.dumps(
			{
				"engine": ENGINE_ID,
				"version": ENGINE_VERSION,
				"records": [asdict(r) for r in self.by_key.values()],
			},
			ensure_ascii=False,
			indent="\t",
			sort_keys=True,
		)

	def save(self, path) -> Path:
		p = Path(path)
		p.parent.mkdir(parents=True, exist_ok=True)
		p.write_text(self.to_json(), encoding="utf-8")
		return p

	@classmethod
	def from_json(cls, text: str) -> RenditionLedger:
		defter = cls()
		data = json.loads(text) if text.strip() else {}
		for row in data.get("records") or ():
			defter.add(RenditionRecord(**row))
		return defter

	@classmethod
	def load(cls, path) -> RenditionLedger:
		p = Path(path)
		if not p.is_file():
			return cls()
		return cls.from_json(p.read_text(encoding="utf-8"))


# --- Motor çıktısı tespiti --------------------------------------------------


@dataclass(frozen=True)
class OutputVerdict:
	"""`is_engine_output` sonucu. `confidence` kanıt gücünü söyler."""

	is_output: bool
	confidence: str
	reason: str
	record: RenditionRecord | None = None

	@property
	def proven(self) -> bool:
		return self.is_output and self.confidence == CONFIDENCE_EXACT


def _known_profile_widths() -> frozenset:
	"""Politikadaki TÜM profil genişlikleri — kodda sabit liste yok."""
	genislikler = set()
	for slot in render_mod.slot_keys():
		for p in render_mod.load_profiles(slot):
			genislikler.add(int(p.width))
	return frozenset(genislikler)


def structural_signature(content: bytes) -> dict:
	"""Dosyanın motor çıktısına benzeyip benzemediğini anlatan ölçülebilir künye.

	Hiçbir alanı tek başına kanıt değildir; `is_engine_output` üçünün birden
	tutmasını arar. Ölçtüğü şeyler ve neden:

	  `format`         motor yalnız WebP/AVIF türev yazar.
	  `has_exif`       türevlerde EXIF sıfırlanır (FR-039 GPS silme dahil).
	  `width_known`    genişlik politikadaki bir profil genişliğine eşitse
	                   dosya bir merdiven basamağı olabilir.
	"""
	Image, _ = render_mod._pil()
	import io as _io

	out = {
		"readable": False,
		"format": "",
		"width": 0,
		"height": 0,
		"has_exif": False,
		"has_gps": False,
		"width_known": False,
	}
	try:
		with Image.open(_io.BytesIO(bytes(content))) as im:
			out["readable"] = True
			out["format"] = (im.format or "").upper()
			out["width"] = im.width
			out["height"] = im.height
			try:
				exif = im.getexif()
				out["has_exif"] = bool(dict(exif))
				out["has_gps"] = EXIF_GPS_IFD_TAG in exif
			except Exception:
				pass
	except Exception:
		return out
	out["width_known"] = out["width"] in _known_profile_widths()
	return out


def is_engine_output(content: bytes, ledger: RenditionLedger | None = None) -> OutputVerdict:
	"""Bu baytlar motorun kendi çıktısı mı?

	Önce defter (kanıt), sonra yapı (sezgi). Sezgi asla `proven` sayılmaz;
	çağıran isterse yalnız `proven` olanı bloklar, sezgiyi uyarı olarak geçer.
	"""
	sha = content_hash(content)
	if ledger is not None:
		kayit = ledger.by_sha(sha)
		if kayit is not None:
			return OutputVerdict(True, CONFIDENCE_EXACT, "ledger_content_match", kayit)

	imza = structural_signature(content)
	if not imza["readable"]:
		return OutputVerdict(False, CONFIDENCE_NONE, "unreadable")
	if imza["format"] in ENGINE_OUTPUT_FORMATS and not imza["has_exif"] and imza["width_known"]:
		return OutputVerdict(
			True,
			CONFIDENCE_HEURISTIC,
			f"structural:{imza['format']}/{imza['width']}px/no_exif",
		)
	return OutputVerdict(False, CONFIDENCE_NONE, "no_match")


def assert_not_engine_output(content: bytes, ledger: RenditionLedger | None = None) -> None:
	"""Kaynak olarak motor çıktısı verilmesini KANITLI durumda engelle.

	Sezgi (heuristic) burada hata vermez: yanlış pozitif, meşru bir kullanıcı
	yüklemesini reddetmek demektir ve bu, nesil kaybından daha pahalıdır.
	"""
	karar = is_engine_output(content, ledger)
	if karar.proven:
		raise ReprocessError(
			f"İdempotensi: bu içerik motorun kendi çıktısı ({karar.record.slot_key}/"
			f"{karar.record.profile}.{karar.record.format}); kaynak olarak kullanılamaz"
		)


# --- Karar ------------------------------------------------------------------


@dataclass(frozen=True)
class ReprocessDecision:
	"""Üret / atla / tazele kararı ve gerekçesi."""

	action: str
	reason: str
	key: str = ""
	record: RenditionRecord | None = None

	@property
	def should_render(self) -> bool:
		return self.action != ACTION_SKIP


def decide(
	*,
	master_sha256: str,
	profile: RenditionProfile,
	fmt: str,
	ledger: RenditionLedger,
	crop_intent: Any = None,
	force: bool = False,
) -> ReprocessDecision:
	"""Bu türev üretilmeli mi?

	`skip`     defterde aynı motor sürümüyle üretilmiş kaydı var.
	`refresh`  aynı master+profil+biçim var ama BAŞKA motor sürümüyle üretilmiş
	           — bayat; yeniden üretilir.
	`render`   hiç üretilmemiş.
	"""
	sig = crop_signature(crop_intent)
	key = derivation_key(
		master_sha256=master_sha256,
		slot_key=profile.slot_key,
		profile_name=profile.name,
		fmt=fmt,
		crop_sig=sig,
	)
	if force:
		return ReprocessDecision(ACTION_RENDER, "force", key, ledger.get(key))

	kayit = ledger.get(key)
	if kayit is not None:
		return ReprocessDecision(ACTION_SKIP, "already_rendered", key, kayit)

	for r in ledger.for_master(master_sha256):
		if r.passthrough:
			continue
		if (
			r.profile == profile.name
			and r.format == fmt.lower()
			and r.crop_sig == sig
			and r.engine_version != ENGINE_VERSION
		):
			return ReprocessDecision(ACTION_REFRESH, f"stale_engine_version:{r.engine_version}", key, r)
	return ReprocessDecision(ACTION_RENDER, "not_rendered", key, None)


def _pixel_plan_signature(plan: render_mod.GeometryPlan) -> tuple:
	"""Encode öncesi piksel sonucunu belirleyen geometri alanları.

	`crop_method` bilerek yoktur: iki farklı niyet seviyesi aynı piksel
	penceresine çözülüyorsa yeniden encode yalnız künyeyi değiştirecek, baytı
	değiştirmeyecektir. Seçici reprocess gerçek piksel farkını ölçer.
	"""
	return (
		plan.crop_box,
		plan.inner_size,
		plan.canvas_size,
		plan.paste_at,
		plan.padded,
	)


def affected_profile_names(
	source_size: tuple[int, int],
	profiles: tuple[RenditionProfile, ...],
	old_intent: Any,
	new_intent: Any,
) -> tuple[str, ...]:
	"""Crop niyeti değişince piksel planı gerçekten değişen profiller.

	`resolve_crop` mantığı kopyalanmaz; iki taraf için de render motorunun
	`plan_geometry` girişi çağrılır. Böylece simülatör/parite düzeltmeleri bu
	seçime otomatik yansır. `contain`/`pad` odak değişikliğinden etkilenmez,
	ama zoom/güvenli-alan taban pencereyi değiştirdiğinde doğru biçimde seçilir.
	"""
	etkilenen: list[str] = []
	for profile in profiles:
		eski = render_mod.plan_geometry(source_size, profile, old_intent)
		yeni = render_mod.plan_geometry(source_size, profile, new_intent)
		if _pixel_plan_signature(eski) != _pixel_plan_signature(yeni):
			etkilenen.append(profile.name)
	return tuple(etkilenen)


def reprocess_profile_names(
	reason: str,
	*,
	source_size: tuple[int, int],
	profiles: tuple[RenditionProfile, ...],
	old_intent: Any = None,
	new_intent: Any = None,
) -> tuple[str, ...]:
	"""Yeniden işleme sebebini üretilecek profil adlarına çevir."""
	if reason not in REPROCESS_REASONS:
		raise ReprocessError(f"Bilinmeyen yeniden işleme sebebi: {reason!r}")
	if reason == REASON_CROP_CHANGED:
		return affected_profile_names(source_size, profiles, old_intent, new_intent)
	return tuple(profile.name for profile in profiles)


def render_idempotent(
	source: bytes,
	profile: RenditionProfile,
	crop_intent: Any = None,
	*,
	ledger: RenditionLedger | None = None,
	fmt: str | None = None,
	force: bool = False,
	guard_source: bool = True,
	**render_kw,
) -> tuple:
	"""`render_rendition`'ın idempotent sarmalayıcısı.

	Dönüş `(RenditionResult | None, ReprocessDecision)`. `action == "skip"` ise
	sonuç `None`'dır ve **hiç encode yapılmamıştır** — modülün varlık sebebi
	budur.

	`fmt` verilmezse profil zincirinin İLK biçimi anahtar için kullanılır; bu
	bir tahmin olduğundan, üretim sonrası gerçek kazanan biçimle kayıt AYRICA
	yazılır (INV-05 zinciri avif yerine webp'yi seçmiş olabilir).
	"""
	if ledger is None:
		ledger = RenditionLedger()
	if guard_source:
		assert_not_engine_output(source, ledger)

	master_sha = content_hash(source)
	anahtar_fmt = fmt or profile.formats[0]
	karar = decide(
		master_sha256=master_sha,
		profile=profile,
		fmt=anahtar_fmt,
		ledger=ledger,
		crop_intent=crop_intent,
		force=force,
	)
	if karar.action == ACTION_SKIP:
		return None, karar

	sonuc = render_mod.render_rendition(source, profile, crop_intent, fmt=fmt, **render_kw)
	sig = crop_signature(crop_intent)
	kayit = RenditionRecord.from_result(sonuc, master_sha256=master_sha, crop_sig=sig)
	if kayit.passthrough:
		# Faydasızlık değerlendirmesi de idempotenttir, fakat gerçek bir türev
		# olmadığı için yalnız çağrının İSTENEN anahtarında tutulur. Sonucun
		# kaynak biçiminden türeyen anahtarını yazmak format zincirinin sonraki
		# halkasını ilk koşuda yanlışlıkla atlatırdı.
		ledger.by_key[karar.key] = kayit
	else:
		ledger.add(kayit)
	if not kayit.passthrough and kayit.key != karar.key:
		# Zincir tahmin edilenden farklı bir biçimde durdu: tahmin anahtarını da
		# aynı kayda bağla ki bir sonraki koşu boşuna encode etmesin.
		ledger.by_key[karar.key] = kayit
	donen_anahtar = karar.key if kayit.passthrough else kayit.key
	return sonuc, ReprocessDecision(karar.action, karar.reason, donen_anahtar, kayit)


def render_ladder_idempotent(
	source: bytes,
	slot_key: str,
	crop_intent: Any = None,
	*,
	ledger: RenditionLedger | None = None,
	per_format: bool = True,
	force: bool = False,
	**render_kw,
) -> tuple:
	"""Merdivenin tamamını idempotent üret. Dönüş `(results, decisions)`."""
	if ledger is None:
		ledger = RenditionLedger()
	hazir, _icc, _notlar = render_mod.prepare_source(source)
	sonuclar: list = []
	kararlar: list = []
	for p in render_mod.load_profiles(slot_key):
		if not render_mod.profile_is_eligible(hazir.size, p, crop_intent):
			continue
		zincir = p.formats if per_format else (None,)
		for f in zincir:
			r, k = render_idempotent(source, p, crop_intent, ledger=ledger, fmt=f, force=force, **render_kw)
			kararlar.append(k)
			if r is not None:
				sonuclar.append(r)
	return sonuclar, kararlar


def generation_loss(
	source: bytes,
	profile: RenditionProfile,
	*,
	rounds: int = 3,
	fmt: str | None = None,
) -> list:
	"""Nesil kaybını ÖLÇ: çıktıyı tekrar tekrar kaynak yaparak SSIM'i izle.

	Bu bir üretim yolu değil, korumanın gerekliliğinin KANITIDIR. Her tur bir
	öncekinin çıktısını kaynak alır; dönen listede `ssim_vs_original` düşüyorsa
	tekrar encode gerçekten bilgi yok ediyor demektir.
	"""
	from tradehub_core.media.pipeline.quality import ssim as ssim_mod

	ilk = render_mod.render_rendition(source, profile, fmt=fmt)
	referans = ilk.content
	satirlar = [
		{
			"round": 1,
			"bytes": ilk.size_bytes,
			"format": ilk.format,
			"ssim_vs_original": 1.0,
			"quality": ilk.quality,
		}
	]
	onceki = ilk.content
	for i in range(2, rounds + 1):
		try:
			tekrar = render_mod.render_rendition(onceki, profile, fmt=ilk.format, allow_passthrough=False)
		except RenderError as exc:
			satirlar.append({"round": i, "error": str(exc)})
			break
		olcum = ssim_mod.compute_ssim(referans, tekrar.content)
		satirlar.append(
			{
				"round": i,
				"bytes": tekrar.size_bytes,
				"format": tekrar.format,
				"ssim_vs_original": round(olcum.value, 6),
				"quality": tekrar.quality,
				"backend": olcum.backend,
			}
		)
		onceki = tekrar.content
	return satirlar


__all__ = [
	"ACTION_RENDER",
	"ACTION_SKIP",
	"ACTION_REFRESH",
	"REASON_CROP_CHANGED",
	"REASON_POLICY_CHANGED",
	"REASON_ENGINE_UPGRADED",
	"REPROCESS_REASONS",
	"CONFIDENCE_EXACT",
	"CONFIDENCE_HEURISTIC",
	"CONFIDENCE_NONE",
	"ReprocessError",
	"content_hash",
	"crop_signature",
	"derivation_key",
	"RenditionRecord",
	"RenditionLedger",
	"OutputVerdict",
	"structural_signature",
	"is_engine_output",
	"assert_not_engine_output",
	"ReprocessDecision",
	"decide",
	"affected_profile_names",
	"reprocess_profile_names",
	"render_idempotent",
	"render_ladder_idempotent",
	"generation_loss",
]
