"""StorageAdapter sözleşmesi — içerik-adresli nesne deposu.

Bu sözleşme SIFIRDAN tasarlanmadı: çalışan motorun disk davranışını sözleşme
hâline getirir. Kaynaklar ve korunması gereken davranışlar:

  - `tradehub_core/media/naming.py` — ad `sha256(içerik)[:32] + uzantı`,
    dizin `adın ilk 2 hex karakteri` (shard). Aynı içerik → aynı anahtar
    (NFR-050: aynı içerik tek fiziksel dosya; NFR-019: ad tahmin edilemez;
    NFR-051: dizin başına dosya sayısı ölçeklenebilir kalır).
  - `tradehub_core/media/access_level.py` — public ↔ private taşıma tek
    atomik `os.replace` ile yapılır, shard ve ad KORUNUR.
  - `tradehub_core/media/trash.py` / `archive.py` — canlı, çöp ve arşiv
    ayrı köklerdir; aynı anahtar farklı kökte durabilir.

`file_url` sözleşmesi (NFR-044): `<prefix>/<shard>/<ad>` — public için
`/files`, private için `/private/files`. URL SABİT kalır; optimize edilen
dosya kendi yerine yazılır, referanslar kırılmaz.

İDEMPOTENSİ (bu sözleşmenin çekirdeği)
--------------------------------------
`put()` içerik-adresli olduğu için **doğal idempotenttir**: aynı baytları
ikinci kez yazmak diski değiştirmez, aynı `ObjectRef`'i döndürür ve
`created=False` işaretler. Anahtar aynı ama içerik farklıysa `StorageConflict`
atılır — sessizce üzerine yazmak iki farklı dosyayı tek dosyaya çökertirdi.

`delete()` de idempotenttir: olmayan nesneyi silmek hata değildir, `False`
döner. `move()` idempotent DEĞİLDİR (kaynak bir kez tüketilir) ama hedef
zaten kaynakla aynı içerikteyse no-op sayılır.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional, Protocol, Tuple, runtime_checkable

# Depolama kapsamları. `public` web sunucusundan doğrudan servis edilir,
# `private` yalnız yetki kontrolünden geçen uçtan (NFR-018).
SCOPE_PUBLIC: str = "public"
SCOPE_PRIVATE: str = "private"
SCOPES: Tuple[str, ...] = (SCOPE_PUBLIC, SCOPE_PRIVATE)

# Anahtar gövdesinin uzunluğu — `naming._hashed_name` ile AYNI (sha256'nın
# ilk 32 hex karakteri). Değiştirmek üretimdeki tüm adları geçersiz kılar.
HASH_LENGTH: int = 32

# Shard prefiks uzunluğu — `naming._shard` ile AYNI (256 alt dizin).
SHARD_LENGTH: int = 2

URL_PREFIX: Dict[str, str] = {SCOPE_PUBLIC: "/files", SCOPE_PRIVATE: "/private/files"}


@dataclass(frozen=True)
class ObjectKey:
	"""İçerik-adresli anahtar: `<shard>/<ad>`.

	`shard` her zaman `ad`'ın ilk 2 karakteridir; ikisi ayrı alan olarak
	tutuluyor çünkü depo uygulamaları (disk, S3 prefix) shard'ı dizin olarak
	kullanır ve her seferinde yeniden dilimlemek sessiz bir tutarsızlık
	kaynağıydı.
	"""

	shard: str
	name: str

	def __post_init__(self) -> None:
		if not self.name:
			raise ValueError("ObjectKey.name boş olamaz")
		if self.shard != self.name[:SHARD_LENGTH]:
			raise ValueError(f"shard ({self.shard!r}) ad ile uyumsuz: {self.name!r}")

	@property
	def relative(self) -> str:
		"""Kök dizine göreli yol — `ab/<hash>.jpg`."""
		return posixpath.join(self.shard, self.name)

	@property
	def extension(self) -> str:
		"""Küçük harfli uzantı, nokta dâhil; uzantısız anahtarda boş dizge."""
		return os.path.splitext(self.name)[1].lower()


@dataclass(frozen=True)
class ObjectRef:
	"""Bir nesnenin tam adresi: anahtar + kapsam.

	`url` türetilmiş bir alandır, ayrıca saklanmaz — `file_url` ile birebir
	aynı olmak zorunda (NFR-044).
	"""

	key: ObjectKey
	scope: str = SCOPE_PUBLIC

	def __post_init__(self) -> None:
		if self.scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {self.scope!r}")

	@property
	def url(self) -> str:
		return f"{URL_PREFIX[self.scope]}/{self.key.relative}"

	@property
	def is_private(self) -> bool:
		return self.scope == SCOPE_PRIVATE


@dataclass(frozen=True)
class ObjectStat:
	"""Nesnenin künyesi — içeriği okumadan alınabilen bilgiler."""

	size_bytes: int
	content_hash: str
	modified_at: float = 0.0
	extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PutResult:
	"""`put()` sonucu.

	`created=False` aynı içeriğin zaten depoda olduğunu söyler — çağıran bunu
	"dedup oldu" olarak raporlar, hata olarak DEĞİL.
	"""

	ref: ObjectRef
	created: bool
	stat: ObjectStat


def content_hash(content: bytes) -> str:
	"""Tam sha256 (64 hex). Anahtar bunun ilk `HASH_LENGTH` karakterini kullanır."""
	return hashlib.sha256(content).hexdigest()


def key_for(content: bytes, extension: str) -> ObjectKey:
	"""İçerikten anahtar üret — `naming._hashed_name` + `_shard` ile AYNI sonuç.

	Saf ve deterministik: aynı içerik + aynı uzantı her zaman aynı anahtar.
	Bu fonksiyon sözleşmenin parçasıdır; bir depo uygulaması kendi ad şemasını
	uyduramaz, aksi hâlde iki uygulama arasında dosya taşınamazdı.
	"""
	ext = (extension or "").lower()
	if ext and not ext.startswith("."):
		ext = f".{ext}"
	name = f"{content_hash(content)[:HASH_LENGTH]}{ext}"
	return ObjectKey(shard=name[:SHARD_LENGTH], name=name)


def key_from_url(url: str) -> Tuple[ObjectKey, str]:
	"""`file_url`'i anahtar + kapsama ayrıştır. Yol geçişi burada reddedilir.

	İki bağımsız savunma katmanının ilki (NFR-020); ikincisi disk uygulamasının
	kendi `realpath` kontrolüdür.
	"""
	clean = (url or "").split("?")[0]
	if not clean or ".." in clean:
		raise ValueError(f"Geçersiz dosya yolu: {url!r}")
	for scope, prefix in URL_PREFIX.items():
		if clean.startswith(f"{prefix}/"):
			rel = clean[len(prefix) + 1 :]
			parts = rel.split("/")
			if len(parts) != 2:
				raise ValueError(f"Shard'lı olmayan yol: {url!r}")
			return ObjectKey(shard=parts[0], name=parts[1]), scope
	raise ValueError(f"Desteklenmeyen dosya yolu: {url!r}")


@runtime_checkable
class StorageAdapter(Protocol):
	"""İçerik-adresli nesne deposu.

	Uygulamalar: yerel disk (üretim, bugünkü davranış), bellek (test),
	ileride nesne deposu. Sözleşme hiçbir yerde POSIX yolu vaat etmez —
	`ObjectRef` tek adres birimidir.

	Tüm metotlar hata durumunda `contracts.errors` hiyerarşisinden atar;
	`FileNotFoundError`/`OSError` sızdırmak sözleşme ihlalidir.
	"""

	def put(self, content: bytes, extension: str, *, scope: str = SCOPE_PUBLIC) -> PutResult:
		"""Baytları yaz, `ObjectRef` döndür.

		İdempotent: aynı içerik + uzantı + kapsam ikinci kez yazıldığında disk
		değişmez, `created=False` döner. Anahtar var ama içerik farklıysa
		`StorageConflict` atılır.

		Yazma ATOMİK olmalıdır (geçici dosya + `os.replace` deseni): yarıda
		kesilen bir yazma yarım dosya bırakmaz (NFR-041).
		"""
		...

	def get(self, ref: ObjectRef) -> bytes:
		"""Nesnenin tamamını oku. Yoksa `ObjectNotFound`."""
		...

	def exists(self, ref: ObjectRef) -> bool:
		"""Nesne var mı. Yan etkisiz, hata atmaz."""
		...

	def stat(self, ref: ObjectRef) -> ObjectStat:
		"""Künye — içeriği okumadan boyut ve hash. Yoksa `ObjectNotFound`."""
		...

	def delete(self, ref: ObjectRef) -> bool:
		"""Nesneyi sil. İdempotent: yoktu ise `False`, silindi ise `True`."""
		...

	def move(self, source: ObjectRef, target_scope: str) -> ObjectRef:
		"""Nesneyi kapsamlar arası taşı — anahtar (shard + ad) KORUNUR.

		`access_level.set_level` davranışı: tek atomik işlem. Kaynak yoksa
		`ObjectNotFound`. Hedefte aynı içerik zaten varsa kaynak silinir ve
		hedef döndürülür (no-op birleşme) — çakışma sayılmaz.

		İdempotent DEĞİLDİR: ikinci çağrıda kaynak artık yoktur. Çağıran,
		"zaten hedefte mi" kontrolünü `exists()` ile yapmalıdır.
		"""
		...

	def iter_keys(self, *, scope: str = SCOPE_PUBLIC, prefix: str = "") -> Iterator[ObjectKey]:
		"""Depodaki anahtarları dolaş — yetim/kırık kayıt uzlaştırması için (FR-107).

		Sıra GARANTİ EDİLMEZ. Uygulama tembel (lazy) olmalıdır: 4.958 dosyalık
		bir depoyu belleğe almak zorunda kalmadan taranabilmelidir.
		"""
		...

	def url_for(self, ref: ObjectRef, *, ttl_seconds: Optional[int] = None) -> str:
		"""Servis edilebilir URL.

		Public kapsamda düz `file_url` döner ve `ttl_seconds` YOK SAYILIR.
		Private kapsamda imzalı ve süreli URL üretilir (FR-112); TTL çağıranın
		verdiği değerle değil, uygulamanın clamp'lediği değerle sınırlıdır
		(FR-113) — sözleşme üst sınırı dayatmaz, clamp'lenmesini şart koşar.
		"""
		...


__all__ = [
	"SCOPE_PUBLIC",
	"SCOPE_PRIVATE",
	"SCOPES",
	"HASH_LENGTH",
	"SHARD_LENGTH",
	"URL_PREFIX",
	"ObjectKey",
	"ObjectRef",
	"ObjectStat",
	"PutResult",
	"StorageAdapter",
	"content_hash",
	"key_for",
	"key_from_url",
]
