"""T-051 — Katmanlı depo: N gün sonra S3'e yaslandırma, okuma yedeği.

AYNA İLE FARKI
--------------
`mirror.py` iki kopya tutar; katmanlı depo **tek** kopya tutar ve o kopyanın
YERİNİ zamanla değiştirir:

    yeni dosya         → sıcak katman (yerel disk)
    N günden eski      → soğuk katman (S3), sıcaktan SİLİNİR
    okuma              → önce sıcak, yoksa soğuk (okuma yedeği)

Amaç yedekleme değil **maliyet**: `docs/reports/06-depolama-maliyet.md`'nin
konusu. Yedeklilik istiyorsan `mirror`, disk maliyeti düşürmek istiyorsan
`tiered`. İkisini birlikte istiyorsan soğuk katman ayrıca versiyonlu bir
bucket olmalı — bu modül onu VARSAYMAZ.

YASLANDIRMA SIRASI (veri kaybına karşı tek savunma)
---------------------------------------------------
    1. soğuğa yaz          cold.put(içerik)
    2. DOĞRULA             cold.stat().content_hash == kaynak sha256
    3. sıcaktan sil        hot.delete()

2. adım atlanırsa "yazdım sandım, yazamamışım" durumu sessiz veri kaybına
döner. Doğrulama başarısızsa sıcak kopyaya DOKUNULMAZ ve
`demote()` `verified=False` ile döner. Soğuk depo `content_hash` üretemiyorsa
(S3'te metadata'sı olmayan eski nesne — bkz. `s3.py` "İÇERİK DOĞRULAMA")
boyut karşılaştırmasına düşülür ve bu durum `verify_mode="size"` ile
RAPORLANIR; sessizce "doğrulandı" sayılmaz.

YAŞ NEREDEN OKUNUYOR
--------------------
`ObjectStat.modified_at` — yani dosya sisteminin mtime'ı. Bu, `trash.
purge_expired` ve `archive.purge_expired`'ın kullandığı ölçütün AYNISI
(`trash.py:281`, `archive.py:120`: `os.path.getmtime(path) >= cutoff`).
Bilinen zayıflığı da aynı: `rsync -a` olmadan yapılan bir kopyalama/restore
tüm mtime'ları bugüne çeker ve yaş sıfırlanır. Bu yüzden `sweep()` her
zaman önce `dry_run=True` ile koşturulabilir ve kaç dosyanın taşınacağını
söyler.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from tradehub_core.media.pipeline.contracts.errors import ObjectNotFound, StorageError
from tradehub_core.media.pipeline.contracts.storage import (
	SCOPE_PUBLIC,
	SCOPES,
	ObjectKey,
	ObjectRef,
	ObjectStat,
	PutResult,
	StorageAdapter,
	content_hash,
)

#: Varsayılan yaslandırma eşiği. ÖLÇÜLMEDİ — bu sayının kaynağı bir ölçüm
#: değil, bir varsayılan seçimidir. `docs/standards/retention.md` §6.2'deki
#: `unused_after_days: 90` ile aynı büyüklük sırasında tutuldu ki iki
#: pencere birbiriyle çelişmesin. Üretimde açmadan önce erişim log'undan
#: "yüklendikten N gün sonra hâlâ istenen dosya oranı" ölçülmeli.
DEFAULT_AGE_DAYS: int = 90

VERIFY_HASH: str = "hash"
VERIFY_SIZE: str = "size"
VERIFY_NONE: str = "none"


@dataclass(frozen=True)
class DemoteResult:
	"""Tek nesnenin yaslandırma sonucu."""

	ref: ObjectRef
	moved: bool
	verified: bool
	verify_mode: str
	bytes_freed: int = 0
	reason: str = ""

	def to_dict(self) -> Dict[str, Any]:
		return {
			"url": self.ref.url,
			"moved": self.moved,
			"verified": self.verified,
			"verify_mode": self.verify_mode,
			"bytes_freed": self.bytes_freed,
			"reason": self.reason,
		}


@dataclass
class SweepReport:
	"""Süpürme özeti — `dry_run` ayrımı raporun içinde durur."""

	scope: str
	dry_run: bool
	age_days: int
	scanned: int = 0
	eligible: int = 0
	demoted: int = 0
	failed: int = 0
	bytes_freed: int = 0
	details: List[Dict[str, Any]] = field(default_factory=list)

	def to_dict(self) -> Dict[str, Any]:
		return {
			"scope": self.scope,
			"dry_run": self.dry_run,
			"age_days": self.age_days,
			"scanned": self.scanned,
			"eligible": self.eligible,
			"demoted": self.demoted,
			"failed": self.failed,
			"bytes_freed": self.bytes_freed,
			# İlk 50 satır; tamamı denetim bağlamını şişirir (`trash.py:329`
			# ile aynı sınır ve aynı gerekçe).
			"details": self.details[:50],
			"details_truncated": max(0, len(self.details) - 50),
		}


class TieredStorage:
	"""Sıcak (yerel) + soğuk (S3) katmanlı depo.

	Args:
	    hot: Sıcak katman — yeni yazmalar buraya gider.
	    cold: Soğuk katman — yaşlananlar buraya yaslanır.
	    age_days: Yaslandırma eşiği (gün).
	    clock: Zaman kaynağı; test için enjekte edilebilir.
	    keep_scopes: Yalnız bu kapsamlar yaslanır. Varsayılan yalnız
	        `public`: private dosyalar KYB/KYC belgeleridir ve onları üçüncü
	        bir tarafın altyapısına taşımak KVKK açısından ayrı bir karar
	        (`presets.EXCLUDED_DOCTYPES` mantığının depolama karşılığı).
	        Bilinçli olarak varsayılan DIŞINDA bırakıldı.
	"""

	def __init__(
		self,
		hot: StorageAdapter,
		cold: StorageAdapter,
		*,
		age_days: int = DEFAULT_AGE_DAYS,
		clock: Optional[Any] = None,
		keep_scopes: Tuple[str, ...] = (SCOPE_PUBLIC,),
	) -> None:
		self._hot = hot
		self._cold = cold
		self._age_days = int(age_days)
		self._clock = clock if clock is not None else time.time
		self._demotable_scopes = tuple(keep_scopes)

	# ── StorageAdapter ─────────────────────────────────────────────────

	def put(self, content: bytes, extension: str, *, scope: str = SCOPE_PUBLIC) -> PutResult:
		"""Yeni içerik HER ZAMAN sıcak katmana yazılır.

		Soğukta zaten varsa (daha önce yaslanmış aynı içerik) sıcağa yeniden
		yazmak yerine soğuktaki kaydı döndürmek CAZİP ama yanlış olurdu:
		çağıran az önce yüklenen dosyayı hemen okuyacak ve o okuma ağa
		çıkacaktı. İçerik-adresli olduğu için iki katmanda aynı anda
		bulunması zararsız; `sweep()` bir sonraki turda sıcak kopyayı
		temizler.
		"""
		return self._hot.put(content, extension, scope=scope)

	def get(self, ref: ObjectRef) -> bytes:
		try:
			return self._hot.get(ref)
		except ObjectNotFound:
			return self._cold.get(ref)

	def exists(self, ref: ObjectRef) -> bool:
		return self._hot.exists(ref) or self._cold.exists(ref)

	def stat(self, ref: ObjectRef) -> ObjectStat:
		try:
			return self._hot.stat(ref)
		except ObjectNotFound:
			return self._cold.stat(ref)

	def delete(self, ref: ObjectRef) -> bool:
		"""İKİ katmandan da siler. Tek katmandan silmek, yaslanmış bir
		dosyanın silinmiş sanılıp soğukta yaşamaya devam etmesi demekti —
		KVKK silme talebi açısından gerçek bir risk."""
		sicak = self._hot.delete(ref)
		soguk = self._cold.delete(ref)
		return sicak or soguk

	def move(self, source: ObjectRef, target_scope: str) -> ObjectRef:
		"""Nerede duruyorsa orada taşır. İki katmanda da varsa ikisi de taşınır."""
		sicakta = self._hot.exists(source)
		sogukta = self._cold.exists(source)
		if not sicakta and not sogukta:
			raise ObjectNotFound("Nesne bulunamadı", detay={"url": source.url})
		hedef = ObjectRef(key=source.key, scope=target_scope)
		if sicakta:
			hedef = self._hot.move(source, target_scope)
		if sogukta:
			hedef = self._cold.move(source, target_scope)
		return hedef

	def iter_keys(self, *, scope: str = SCOPE_PUBLIC, prefix: str = "") -> Iterator[ObjectKey]:
		"""İki katmanın BİRLEŞİMİ, tekrarsız.

		Sıcakta görülen anahtarlar bir kümede tutulur — bu, tarama boyunca
		bellekte tutulan tek şey ve anahtar başına ~40 bayt. 4.958 dosyalık
		bugünkü depoda ~200 KB; milyon dosyada ~40 MB. Milyon ölçeğinde bu
		yöntem değiştirilmeli (sıralı iki akışın birleştirilmesi), bugünkü
		ölçekte gereksiz karmaşıklık.
		"""
		gorulen = set()
		for key in self._hot.iter_keys(scope=scope, prefix=prefix):
			gorulen.add(key.relative)
			yield key
		for key in self._cold.iter_keys(scope=scope, prefix=prefix):
			if key.relative not in gorulen:
				yield key

	def url_for(self, ref: ObjectRef, *, ttl_seconds: Optional[int] = None) -> str:
		"""Nesne nerede duruyorsa o katmanın URL'ini döndürür.

		Yaslanmış bir dosya için sıcak katmanın URL'ini döndürmek 404
		üretirdi; bu yüzden varlık kontrolü URL üretiminden ÖNCE yapılır.
		Maliyeti bir `exists()` çağrısıdır ve public kapsamda yerel diskte
		bu bir `os.path.isfile`.
		"""
		if self._hot.exists(ref):
			return self._hot.url_for(ref, ttl_seconds=ttl_seconds)
		if self._cold.exists(ref):
			return self._cold.url_for(ref, ttl_seconds=ttl_seconds)
		# Hiçbirinde yok: sözleşme `url_for` için "yoksa hata" demiyor.
		# Sıcak katmanın URL'i döner — çağıran zaten 404 alacak ve bu,
		# istisna atıp render'ı kırmaktan daha az zararlı.
		return self._hot.url_for(ref, ttl_seconds=ttl_seconds)

	# ── katman yönetimi ────────────────────────────────────────────────

	@property
	def age_days(self) -> int:
		return self._age_days

	def location(self, ref: ObjectRef) -> str:
		"""`hot` | `cold` | `both` | `missing` — teşhis için."""
		sicak = self._hot.exists(ref)
		soguk = self._cold.exists(ref)
		if sicak and soguk:
			return "both"
		if sicak:
			return "hot"
		if soguk:
			return "cold"
		return "missing"

	def is_eligible(self, ref: ObjectRef, *, now: Optional[float] = None) -> bool:
		"""Nesne yaslandırma yaşına geldi mi."""
		if ref.scope not in self._demotable_scopes:
			return False
		try:
			kunye = self._hot.stat(ref)
		except ObjectNotFound:
			return False
		simdi = float(self._clock() if now is None else now)
		return (simdi - float(kunye.modified_at)) >= self._age_days * 86400

	def demote(self, ref: ObjectRef, *, dry_run: bool = False) -> DemoteResult:
		"""Tek nesneyi soğuğa yasla: yaz → DOĞRULA → sıcaktan sil.

		`dry_run=True` hiçbir şeye dokunmaz; ne olacağını söyler.
		"""
		try:
			kunye = self._hot.stat(ref)
		except ObjectNotFound:
			return DemoteResult(ref, False, False, VERIFY_NONE, reason="not_in_hot")

		if dry_run:
			return DemoteResult(
				ref, False, False, VERIFY_NONE, bytes_freed=kunye.size_bytes, reason="dry_run"
			)

		icerik = self._hot.get(ref)
		beklenen = content_hash(icerik)

		try:
			self._cold.put(icerik, ref.key.extension, scope=ref.scope)
		except StorageError as hata:
			return DemoteResult(
				ref, False, False, VERIFY_NONE, reason=f"cold_put_failed:{hata.kod}"
			)

		mod, dogru = self._verify_cold(ref, beklenen, len(icerik))
		if not dogru:
			# Soğuk kopya doğrulanamadı → sıcak kopyaya DOKUNULMAZ.
			return DemoteResult(ref, False, False, mod, reason="verification_failed")

		self._hot.delete(ref)
		return DemoteResult(
			ref, True, True, mod, bytes_freed=kunye.size_bytes, reason="demoted"
		)

	def _verify_cold(self, ref: ObjectRef, beklenen_hash: str, beklenen_boyut: int) -> Tuple[str, bool]:
		"""Soğuk kopyayı doğrula. `(mod, sonuc)` döner; uydurma "geçti" yok."""
		try:
			kunye = self._cold.stat(ref)
		except ObjectNotFound:
			return VERIFY_NONE, False
		if kunye.content_hash:
			return VERIFY_HASH, kunye.content_hash == beklenen_hash
		# Hash yok (metadata'sız eski nesne). Boyut karşılaştırması ZAYIF bir
		# doğrulamadır ve öyle raporlanır.
		return VERIFY_SIZE, int(kunye.size_bytes) == int(beklenen_boyut)

	def promote(self, ref: ObjectRef) -> bool:
		"""Soğuktaki nesneyi sıcağa geri getir (yeniden popülerleşen dosya).

		Soğuk kopya SİLİNMEZ: geri getirme genelde geçicidir ve soğuktan
		silmek bir sonraki `sweep()` turunda aynı transferi yeniden ödetirdi.
		"""
		if self._hot.exists(ref):
			return False
		icerik = self._cold.get(ref)
		self._hot.put(icerik, ref.key.extension, scope=ref.scope)
		return True

	def sweep(
		self,
		*,
		scope: str = SCOPE_PUBLIC,
		dry_run: bool = True,
		limit: int = 0,
		now: Optional[float] = None,
	) -> SweepReport:
		"""Yaşı dolanları yasla. **Varsayılan `dry_run=True`.**

		Varsayılanın kuru koşum olması bilinçli: bu fonksiyon veri taşır ve
		yanlış yapılandırılmış bir yaş eşiği (ör. `age_days=0`) tüm depoyu
		tek turda S3'e gönderebilir. Silmeye/taşımaya varsayılan olarak izin
		veren bir API, ilk yanlış çağrıda geri alınamaz sonuç doğurur.
		"""
		rapor = SweepReport(scope=scope, dry_run=dry_run, age_days=self._age_days)
		if scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {scope!r}")
		if scope not in self._demotable_scopes:
			return rapor

		for key in self._hot.iter_keys(scope=scope):
			rapor.scanned += 1
			ref = ObjectRef(key=key, scope=scope)
			if not self.is_eligible(ref, now=now):
				continue
			rapor.eligible += 1
			sonuc = self.demote(ref, dry_run=dry_run)
			rapor.details.append(sonuc.to_dict())
			if dry_run:
				rapor.bytes_freed += sonuc.bytes_freed
			elif sonuc.moved:
				rapor.demoted += 1
				rapor.bytes_freed += sonuc.bytes_freed
			else:
				rapor.failed += 1
			if limit and rapor.eligible >= limit:
				break
		return rapor

	def __len__(self) -> int:
		return sum(1 for scope in SCOPES for _ in self.iter_keys(scope=scope))


__all__ = [
	"TieredStorage",
	"DemoteResult",
	"SweepReport",
	"DEFAULT_AGE_DAYS",
	"VERIFY_HASH",
	"VERIFY_SIZE",
	"VERIFY_NONE",
]
