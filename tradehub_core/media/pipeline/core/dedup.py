"""T-042 — Tekilleştirme, sürüm hash'i ve değişmez rendition adresleri.

Üç ayrı kimlik vardır ve karıştırılmaları pahalıya patlar:

    content_sha256   KAYNAK dosyanın kimliği    → aynı dosya iki kez yüklenmez
    version_hash     NORMALIZE MASTER'ın kimliği → politika/crop değişince değişir
    perceptual_hash  GÖRÜNTÜNÜN benzerliği       → kimlik DEĞİL, uyarı üretir

Neden üçü ayrı: bir satıcı aynı fotoğrafı yeniden yüklerse `content_sha256`
eşleşir ve yeni dosya yazılmaz (`INV-06`, idempotency). Ama aynı dosyadan
politika değişince ÜRETİLEN master farklıdır; türev adresleri değişmek
ZORUNDADIR yoksa CDN eski görseli sonsuza kadar servis eder (`INV-09`).
`perceptual_hash` ikisinin de cevaplayamadığı soruyu sorar: "bu, aynı ürünün
zaten yüklenmiş bir başka fotoğrafı mı?"

**MEVCUT MOTOR YENİDEN YAZILMADI.** `tradehub_core/media/naming.py` içerik-adresli
adlandırmayı (sha256[:32] + 2 haneli shard) zaten üretimde uyguluyor. Bu modül
onu SARAR:

  * `content_name()` / `shard_of()` aynı sözleşmeyi frappe'siz ifade eder,
  * `verify_naming_contract()` frappe varken iki uygulamayı BİREBİR karşılaştırır
    ve ayrışırlarsa hata verir — sessiz ayrışma bu modülün tek gerçek riski.

Mevcut motorun yapmadığı ve burada eklenen tek şey **akışlı** hash'tir:
`naming._hashed_name()` içeriğin TAMAMINI bellekte ister. Ölçülen gerçek: canlıda
tek bir görsel 72,71 MP / 2,35 MB, videolarda ise 500 MB'a kadar tavan var —
parçalı yüklemede (`tradehub_core/media/chunked.py`) dosyayı belleğe almak
gerekmiyor, gerekmemeli de.

`import frappe` ve `import PIL` modül düzeyinde YOKTUR; ikisi de yalnız
ihtiyaç duyulan fonksiyonun içinden, açıkça import edilir.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Tuple

# ── Sabitler: mevcut motorun sözleşmesi ─────────────────────────────────
#
# Bu iki sayı `tradehub_core/media/naming.py` ile AYNI olmak zorundadır.
# `verify_naming_contract()` bunu çalışma anında kanıtlar.
HASH_PREFIX_LEN: int = 32
SHARD_LEN: int = 2

#: Akışlı okuma parçası. 1 MiB: disk/ağ okumasında blok başı maliyeti amorti
#: eder, 500 MB'lık bir videoda bile bellek ayak izi sabit kalır.
CHUNK_SIZE: int = 1024 * 1024

#: Rendition adresleri içerik-adreslidir; içerik değişince adres değişir
#: (INV-09). Bu yüzden sonsuz önbellek güvenlidir.
CACHE_CONTROL_IMMUTABLE: str = "public, max-age=31536000, immutable"

#: `version_hash` üretim biçiminin etiketi. Formül değişirse bu etiket de
#: değişir ve eski hash'lerin neden farklı üretildiği kayıtta kalır.
VERSION_HASH_ALGO: str = "sha256-v1"

#: Alan ayracı. Kaynak doküman formülü "source_hash + canonical_json(policy) +
#: canonical_json(crop) + engine_version" diye düz BİRLEŞTİRME olarak yazıyor.
#: SAPMA (bilinçli): düz birleştirme belirsizdir — ("ab", "c") ile ("a", "bc")
#: aynı diziyi üretir ve farklı iki girdi aynı hash'i alabilir. Araya baytta
#: geçemeyen bir ayraç (ASCII 0x1F, Unit Separator) konur. Girdi kümesi
#: dokümandakiyle AYNI; yalnız kodlaması belirsizlikten arındırıldı.
_SEP: str = "\x1f"

#: pHash mesafe eşiği — bu değerin ALTINDAKİ çiftler "tekrar görsel" uyarısı
#: alır. **ÖLÇÜLMEDİ.** Kalibrasyon için İstoç korpusunda gerçek tekrar
#: çiftlerinin mesafe dağılımı çıkarılmalı; bu yapılmadan üretimde
#: zorlanmamalıdır. Media Engine Settings.phash_distance_threshold doldurulunca
#: o kazanır.
PHASH_DISTANCE_THRESHOLD: int = 5

#: dHash ızgarası. 8x8 karşılaştırma → 8x9 örnekleme, 64 bit çıktı.
_DHASH_SIZE: int = 8

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class DedupError(ValueError):
	"""Tekilleştirme girdisi geçersiz ya da sözleşme ihlali var."""


# ─────────────────────────────────────────────────────────────────────────────
# 1. Akışlı içerik hash'i
# ─────────────────────────────────────────────────────────────────────────────


def _iter_chunks(source: Any, chunk_size: int) -> Iterable[bytes]:
	"""Kaynağı parça parça ver. Yol, dosya nesnesi, bytes ya da bytes üreteci."""
	if isinstance(source, (bytes, bytearray, memoryview)):
		data = bytes(source)
		for i in range(0, len(data), chunk_size):
			yield data[i : i + chunk_size]
		return
	if isinstance(source, (str, os.PathLike)):
		with open(source, "rb") as fh:
			while True:
				block = fh.read(chunk_size)
				if not block:
					return
				yield block
	if hasattr(source, "read"):
		while True:
			block = source.read(chunk_size)
			if not block:
				return
			yield block if isinstance(block, bytes) else bytes(block)
	if hasattr(source, "__iter__"):
		for block in source:
			if isinstance(block, str):
				raise DedupError("Akış metin döndürdü; ikili (binary) mod gerekiyor.")
			yield bytes(block)
		return
	raise DedupError(f"Hash'lenebilir bir kaynak değil: {type(source).__name__}")


@dataclass(frozen=True)
class StreamHash:
	"""Akışlı hash sonucu — hash ve okunan bayt birlikte döner.

	Bayt sayısı hash'in yanında olmalı: `Media Source.bytes` alanı zaten
	gerekiyor ve dosyayı ikinci kez okumak (veya `os.path.getsize` ile ayrı bir
	sistem çağrısı yapmak) parçalı yüklemede kaynağın hâlâ var olmasına bel
	bağlar.
	"""

	sha256: str
	bytes: int


def stream_sha256(source: Any, chunk_size: int = CHUNK_SIZE) -> StreamHash:
	"""Dosyayı belleğe almadan SHA-256'sını hesapla.

	`source`: dosya yolu, açık ikili dosya nesnesi, `bytes` ya da `bytes` üreten
	bir yineleyici. Üçünün de desteklenmesi tesadüf değil: yükleme yolunda
	parçalar ağdan üreteç olarak gelir (`chunked.py`), yeniden işleme yolunda
	diskten okunur, testte `bytes` verilir.
	"""
	if chunk_size <= 0:
		raise DedupError(f"Parça boyutu pozitif olmalı: {chunk_size}")
	digest = hashlib.sha256()
	total = 0
	for block in _iter_chunks(source, chunk_size):
		digest.update(block)
		total += len(block)
	return StreamHash(sha256=digest.hexdigest(), bytes=total)


def sha256_bytes(content: bytes) -> str:
	"""Bellekteki içeriğin hash'i — `stream_sha256`'nın kısayolu."""
	return stream_sha256(content).sha256


# ─────────────────────────────────────────────────────────────────────────────
# 2. İçerik-adresli adlandırma — mevcut naming.py sözleşmesinin sarmalayıcısı
# ─────────────────────────────────────────────────────────────────────────────


def content_name(sha256_hex: str, extension: str) -> str:
	"""`<sha256[:32]><.uzantı>` — `naming._hashed_name()` ile AYNI çıktı."""
	h = _require_hex(sha256_hex)
	ext = (extension or "").lower()
	if ext and not ext.startswith("."):
		ext = "." + ext
	return f"{h[:HASH_PREFIX_LEN]}{ext}"


def shard_of(hashed_name: str) -> str:
	"""Hash-prefix shard dizini — `naming._shard()` ile AYNI çıktı."""
	if len(hashed_name) < SHARD_LEN:
		raise DedupError(f"Shard için ad çok kısa: {hashed_name!r}")
	return hashed_name[:SHARD_LEN]


def content_url(sha256_hex: str, extension: str, *, is_private: bool = False) -> str:
	"""Yeni yüklemenin `file_url`'i — mevcut motorun ürettiğiyle birebir aynı."""
	name = content_name(sha256_hex, extension)
	prefix = "/private/files" if is_private else "/files"
	return f"{prefix}/{shard_of(name)}/{name}"


def verify_naming_contract(content: bytes = b"tradehub-media-engine-contract") -> dict:
	"""Bu modül ile üretimdeki `naming.py` hâlâ aynı adı mı üretiyor?

	İki uygulama ayrışırsa yeni motor, mevcut dosyaların yanına aynı içeriği
	FARKLI adla yazmaya başlar: dedup sessizce çalışmaz olur. Bu fonksiyon o
	sessizliği bir hataya çevirir.

	`frappe` yoksa doğrulama yapılamaz; `{"checked": False}` döner — sahte bir
	"geçti" cevabı vermez.
	"""
	try:
		from tradehub_core.media import naming  # noqa: PLC0415 — bilinçli geç import
	except Exception as exc:  # noqa: BLE001 — frappe yoksa da bu modül çalışmalı
		return {"checked": False, "reason": f"{type(exc).__name__}: {exc}"}

	beklenen_ad = naming._hashed_name("ornek.jpg", content)
	bizim_ad = content_name(sha256_bytes(content), ".jpg")
	beklenen_shard = naming._shard(beklenen_ad)
	bizim_shard = shard_of(bizim_ad)

	if beklenen_ad != bizim_ad or beklenen_shard != bizim_shard:
		raise DedupError(
			"Adlandırma sözleşmesi ayrıştı — üretim motoru ile media_engine farklı "
			f"ad üretiyor: naming.py={beklenen_shard}/{beklenen_ad} "
			f"media_engine={bizim_shard}/{bizim_ad}"
		)
	return {"checked": True, "name": bizim_ad, "shard": bizim_shard}


def _require_hex(value: str) -> str:
	h = (value or "").strip().lower()
	if not _HEX64.match(h):
		raise DedupError(f"64 haneli onaltılık SHA-256 bekleniyordu: {value!r}")
	return h


# ─────────────────────────────────────────────────────────────────────────────
# 3. Kanonik JSON ve version_hash
# ─────────────────────────────────────────────────────────────────────────────


def canonical_json(value: Any) -> str:
	"""Hash'lenebilir, deterministik JSON.

	Kurallar ve sebepleri:
	  * `sort_keys=True` — sözlük sırası Python sürümüne/ekleme sırasına göre
	    değişir; hash girdisi olamaz.
	  * ayraçlarda boşluk yok — biçimlendirme farkı hash'i değiştirmemeli.
	  * `ensure_ascii=False` — Türkçe karakter `\\u0131` olarak kaçırılırsa aynı
	    politika iki farklı metin, dolayısıyla iki farklı hash üretir.
	  * `allow_nan=False` — NaN/Infinity geçerli JSON değil ve NaN != NaN
	    olduğu için hash girdisi olarak anlamsız; sessizce geçmesindense hata.
	"""
	return json.dumps(
		value,
		sort_keys=True,
		separators=(",", ":"),
		ensure_ascii=False,
		allow_nan=False,
		default=_json_default,
	)


def _json_default(obj: Any) -> Any:
	"""JSON'a çevrilemeyen tipler için son çare.

	`set` sıralanır (sırasız koleksiyon deterministik olmalı), tarih/karar
	nesneleri metne indirgenir. Bilinmeyen bir tip sessizce `repr`'ine
	düşürülmez — `repr` bellek adresi taşıyabilir ve hash'i çalıştırmadan
	çalıştırmaya değiştirir.
	"""
	if isinstance(obj, (set, frozenset)):
		return sorted(obj, key=lambda v: (type(v).__name__, str(v)))
	if isinstance(obj, (tuple, list)):
		return list(obj)
	if hasattr(obj, "isoformat"):
		return obj.isoformat()
	if hasattr(obj, "as_dict"):
		return obj.as_dict()
	raise DedupError(f"Kanonik JSON'a çevrilemeyen tip: {type(obj).__name__}")


def version_hash(
	source_hash: str,
	policy_snapshot: Any,
	crop_intent: Any,
	engine_version: str,
) -> str:
	"""`Media Version.version_hash` — normalize master'ın kimliği.

	Dört girdiden herhangi biri değişince hash değişir; hiçbiri değişmeden aynı
	kalır. Bu, `INV-06` (idempotency) ve `INV-09` (değişmez URL) değişmezlerinin
	tek dayanağıdır: rendition adresi bu hash'i taşır.

	`crop_intent` normalize edilir (`normalize_crop_intent`): DocType'tan gelen
	kayıt `None`, `""`, `0` ve eksik alan karışımı taşır ve bunlar aynı niyeti
	farklı hash'lerle temsil ederdi — aynı görsel her kaydedişte yeniden
	işlenirdi.
	"""
	h = _require_hex(source_hash)
	parts = (
		VERSION_HASH_ALGO,
		h,
		canonical_json(policy_snapshot),
		canonical_json(normalize_crop_intent(crop_intent)),
		str(engine_version or ""),
	)
	return hashlib.sha256(_SEP.join(parts).encode("utf-8")).hexdigest()


#: `version_hash` girdisine giren kırpma alanları. Listede OLMAYAN alan hash'i
#: etkilemez — `previewed_placements` (kullanıcının simülatörde neye baktığı) ya
#: da `algorithm_version` gibi alanlar üretilen pikseli değiştirmez, girmemeli;
#: girerse her önizleme tüm türevleri yeniden ürettirir.
CROP_HASH_FIELDS: Tuple[str, ...] = (
	"focal_x", "focal_y", "safe_x", "safe_y", "safe_w", "safe_h",
	# Zoom üçlüsü pencereyi değiştirir (`core/crop.py::zoom_region_of`), yani
	# pikseli değiştirir — hash'e GİRMELİ. Guard aşağıda: zoom < 1 "yazılmamış"
	# demektir (Frappe Float NOT NULL DEFAULT 0) ve üçlü o durumda hash'ten
	# atılır; atılmasaydı ham DocType satırından okuyan bir çağıran, eski
	# niyetlerin TAMAMININ hash'ini değiştirir ve her türev yeniden üretilirdi.
	"zoom", "center_x", "center_y",
	"method", "suggested_x", "suggested_y", "suggested_w", "suggested_h",
)

CROP_OVERRIDE_HASH_FIELDS: Tuple[str, ...] = ("profile", "x", "y", "w", "h", "method")


def normalize_crop_intent(intent: Any) -> Optional[dict]:
	"""Kırpma niyetini hash'lenebilir kanonik biçime indir.

	`None` girdisi `None` döner (kırpma niyeti YOK) — boş sözlük değil: "niyet
	yok" ile "niyet var ama tüm alanları boş" farklı şeylerdir ve farklı hash
	almalıdırlar.
	"""
	if intent is None:
		return None

	def _read(obj: Any, key: str) -> Any:
		if isinstance(obj, Mapping):
			return obj.get(key)
		return getattr(obj, key, None)

	out: dict = {}
	for name in CROP_HASH_FIELDS:
		value = _read(intent, name)
		if value in (None, ""):
			continue
		out[name] = round(float(value), 6) if name != "method" else str(value)

	# Zoom < 1 (0 dahil) yazılmamıştır ve merkez ancak zoom ile anlamlıdır —
	# CROP_HASH_FIELDS içindeki gerekçe. `ZOOM_MIN=1` (`core/crop.py`).
	if float(out.get("zoom") or 0.0) < 1.0:
		out.pop("zoom", None)
		out.pop("center_x", None)
		out.pop("center_y", None)

	overrides = _read(intent, "overrides") or _read(intent, "crop_overrides") or []
	if isinstance(overrides, Mapping):
		overrides = [
			dict(v, profile=k) if isinstance(v, Mapping) else v for k, v in overrides.items()
		]
	rows = []
	for row in overrides:
		item: dict = {}
		for name in CROP_OVERRIDE_HASH_FIELDS:
			value = _read(row, name)
			if value in (None, ""):
				continue
			item[name] = str(value) if name in ("profile", "method") else round(float(value), 6)
		if item:
			rows.append(item)
	if rows:
		# Satır SIRASI hash'i etkilememeli: child table'da satırları sürüklemek
		# kadrajı değiştirmez.
		out["overrides"] = sorted(rows, key=lambda r: r.get("profile", ""))
	return out or {}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Rendition adresleri (INV-09)
# ─────────────────────────────────────────────────────────────────────────────

RENDITION_ROOT: str = "/files/media"

_RENDITION_RE = re.compile(
	r"^/files/media/(?P<asset>[^/]+)/(?P<version_hash>[0-9a-f]{64})/"
	r"(?P<profile>[^/]+)-(?P<width>\d+)\.(?P<ext>[a-z0-9]+)$"
)


def rendition_path(asset: str, version_hash_hex: str, profile: str, width: int, ext: str) -> str:
	"""`/files/media/{asset}/{version_hash}/{profile}-{width}.{ext}`

	Adres `version_hash` taşır; içerik değişmeden adres değişmez, içerik
	değişince adres zorunlu değişir (INV-09). Bu yüzden
	`CACHE_CONTROL_IMMUTABLE` ile bir yıl önbelleklenebilir ve CDN'de
	geçersizleştirme (purge) hiç gerekmez.
	"""
	a = _safe_segment(asset, "asset")
	v = _require_hex(version_hash_hex)
	p = _safe_segment(profile, "profile")
	if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
		raise DedupError(f"Genişlik pozitif tam sayı olmalı: {width!r}")
	e = (ext or "").lower().lstrip(".")
	if not e.isalnum():
		raise DedupError(f"Geçersiz uzantı: {ext!r}")
	return f"{RENDITION_ROOT}/{a}/{v}/{p}-{width}.{e}"


def parse_rendition_path(url: str) -> Optional[dict]:
	"""`rendition_path`'in tersi. Eşleşmezse `None`.

	Ters çevirim gerçekten gerekiyor: erişim damgası (`last_access_at`) günlük
	dosyalarından üretilecekse, elimizde yalnız URL olur (T-043)."""
	m = _RENDITION_RE.match((url or "").split("?")[0])
	if not m:
		return None
	d = m.groupdict()
	d["width"] = int(d["width"])
	return d


def _safe_segment(value: str, label: str) -> str:
	v = str(value or "").strip()
	if not _SAFE_SEGMENT.match(v):
		raise DedupError(f"Yol parçası olarak güvenli değil ({label}): {value!r}")
	return v


# ─────────────────────────────────────────────────────────────────────────────
# 5. Yükleme kararı ve yarış koşulu
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DedupOutcome:
	"""Bir yüklemenin tekilleştirme kararı."""

	content_sha256: str
	is_duplicate: bool
	asset: Optional[str] = None
	#: Kullanıcıya gösterilecek Türkçe bilgi. Bir HATA değil: yükleme başarılı
	#: sayılır, yalnız yeni dosya yazılmaz.
	message: str = ""
	#: Dosya diske yazılmalı mı. `False` ise çağıran yazma adımını ATLAR —
	#: karar burada verilir, çağıranın yeniden yorumlamasına bırakılmaz.
	should_store: bool = True

	def as_dict(self) -> dict:
		return {
			"content_sha256": self.content_sha256,
			"is_duplicate": self.is_duplicate,
			"asset": self.asset,
			"message": self.message,
			"should_store": self.should_store,
		}


DUPLICATE_MESSAGE = "Bu dosya zaten kütüphanenizde; yeniden yüklenmedi."


def resolve_upload(content_sha256: str, find_existing: Callable[[str], Optional[str]]) -> DedupOutcome:
	"""Bu içerik daha önce yüklenmiş mi — yükleme yolunun karar noktası.

	`find_existing(sha) -> asset_adı | None` çağrılabilirdir; veritabanı erişimi
	çağırana bırakılır, böylece bu fonksiyon frappe'siz test edilir.
	"""
	h = _require_hex(content_sha256)
	mevcut = find_existing(h)
	if mevcut:
		return DedupOutcome(
			content_sha256=h,
			is_duplicate=True,
			asset=str(mevcut),
			message=DUPLICATE_MESSAGE,
			should_store=False,
		)
	return DedupOutcome(content_sha256=h, is_duplicate=False, should_store=True)


def idempotent_create(
	key: str,
	create: Callable[[], Any],
	find: Callable[[str], Optional[Any]],
	is_conflict: Callable[[BaseException], bool],
) -> Tuple[Any, bool]:
	"""Tekillik kısıtına karşı yarış koşulunu çöz. Dönüş: `(kayıt, yeni_mi)`.

	İki eşzamanlı `finalize_upload` aynı dosya için aynı anda gelebilir. "Önce
	bak, yoksa yaz" deseninin ikisi de kontrolü geçer ve ikisi de yazmaya
	çalışır; ikincisi UNIQUE kısıta çarpar. **Doğru davranış hata döndürmek
	değil, mevcut kaydı döndürmektir** — kullanıcı açısından iki istek de
	başarılıdır (INV-06).

	Kısıt ihlalini tanımak veritabanına bağlı olduğu için `is_conflict`
	dışarıdan verilir (Frappe'de `frappe.exceptions.DuplicateEntryError` ya da
	`pymysql` 1062).
	"""
	mevcut = find(key)
	if mevcut is not None:
		return (mevcut, False)
	try:
		return (create(), True)
	except BaseException as exc:
		if not is_conflict(exc):
			raise
		# Yarışı diğer istek kazandı — onun yazdığı kaydı döndür.
		mevcut = find(key)
		if mevcut is None:
			# Kısıt ihlali var ama kayıt bulunamıyor: bu bir tutarsızlıktır,
			# yutulmamalı.
			raise DedupError(
				f"Tekillik ihlali alındı ama kayıt bulunamadı (key={key!r}); "
				"okuma tutarlılığı ya da kısıt tanımı hatalı."
			)
		return (mevcut, False)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Algısal hash (pHash) — benzer görsel uyarısı
# ─────────────────────────────────────────────────────────────────────────────


def dhash(content: bytes, size: int = _DHASH_SIZE) -> str:
	"""Fark hash'i (dHash) — 64 bit, 16 onaltılık hane.

	Neden dHash: yatay komşu piksel farkının işaretine bakar, ortalamaya değil.
	Bu onu **yeniden sıkıştırmaya, ölçeklemeye ve genel parlaklık kaymasına**
	karşı dayanıklı yapar; İstoç'ta beklenen tekrar deseni tam olarak budur
	(aynı fotoğrafın farklı boyda/kalitede yeniden yüklenmesi).

	Kırmızı çizgi: dHash bir KİMLİK değildir. Farklı iki görsel aynı dHash'i
	alabilir. Tekilleştirme kararı ASLA buna dayandırılmaz — yalnız uyarı üretir.
	"""
	from PIL import Image  # noqa: PLC0415 — Pillow yalnız bu yolda gerekiyor

	with Image.open(io.BytesIO(content)) as im:
		im = im.convert("L").resize((size + 1, size), Image.LANCZOS)
		px = list(im.getdata())

	bits = 0
	for row in range(size):
		base = row * (size + 1)
		for col in range(size):
			bits <<= 1
			if px[base + col] > px[base + col + 1]:
				bits |= 1
	return f"{bits:0{size * size // 4}x}"


def hamming_distance(a: str, b: str) -> int:
	"""İki onaltılık hash arasındaki bit farkı. Uzunluklar eşit olmalı."""
	if len(a) != len(b):
		raise DedupError(f"Hash uzunlukları farklı: {len(a)} vs {len(b)}")
	return bin(int(a, 16) ^ int(b, 16)).count("1")


@dataclass(frozen=True)
class SimilarityWarning:
	"""'Bu görselin benzeri zaten var' uyarısı."""

	asset: str
	distance: int
	threshold: int

	@property
	def message(self) -> str:
		return (
			f"Bu görsel, kütüphanedeki {self.asset} ile çok benzer "
			f"(fark {self.distance}/{self.threshold}). Aynı fotoğrafın başka bir "
			"kopyası olabilir."
		)


def find_similar(
	phash: str,
	candidates: Mapping[str, str],
	threshold: int = PHASH_DISTANCE_THRESHOLD,
) -> list:
	"""Eşiğin altındaki benzerleri, en yakından uzağa döndür.

	`candidates`: `{asset_adı: phash}` — genelde aynı ürünün diğer görselleri.
	Tüm kütüphaneyi taramak O(n) karşılaştırma demektir ve 4.958 dosyada bunu
	her yüklemede yapmak gereksiz; kapsamı çağıran daraltır.
	"""
	out = []
	for asset, other in (candidates or {}).items():
		if not other:
			continue
		try:
			d = hamming_distance(phash, other)
		except DedupError:
			continue
		if d <= threshold:
			out.append(SimilarityWarning(asset=str(asset), distance=d, threshold=threshold))
	return sorted(out, key=lambda w: w.distance)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Kolaylık: bir yüklemenin tüm kimlikleri tek çağrıda
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UploadIdentity:
	"""Bir yüklemenin ürettiği tüm kimlikler."""

	content_sha256: str
	bytes: int
	file_url: str
	perceptual_hash: str = ""
	warnings: tuple = field(default_factory=tuple)

	def as_dict(self) -> dict:
		return {
			"content_sha256": self.content_sha256,
			"bytes": self.bytes,
			"file_url": self.file_url,
			"perceptual_hash": self.perceptual_hash,
			"warnings": [w.message for w in self.warnings],
		}


def identify_upload(
	content: bytes,
	extension: str,
	*,
	is_private: bool = False,
	similar_candidates: Optional[Mapping[str, str]] = None,
	threshold: int = PHASH_DISTANCE_THRESHOLD,
) -> UploadIdentity:
	"""Bellekteki bir yükleme için kimlikleri üret.

	Yalnız `bytes` alır (akış değil) çünkü pHash görüntünün TAMAMINI ister;
	akışlı yolda `stream_sha256` + ayrı bir pHash adımı kullanılır. İkisini tek
	imzada birleştirmek, akışlı yolda sessizce belleğe alma yapmak olurdu.
	"""
	sh = stream_sha256(content)
	ph = ""
	warnings: list = []
	try:
		ph = dhash(content)
	except Exception:
		# Video, PDF ya da bozuk görsel: algısal hash yok. Kimlik yine geçerli —
		# pHash bir ek, bir zorunluluk değil.
		ph = ""
	if ph and similar_candidates:
		warnings = find_similar(ph, similar_candidates, threshold=threshold)
	return UploadIdentity(
		content_sha256=sh.sha256,
		bytes=sh.bytes,
		file_url=content_url(sh.sha256, extension, is_private=is_private),
		perceptual_hash=ph,
		warnings=tuple(warnings),
	)
