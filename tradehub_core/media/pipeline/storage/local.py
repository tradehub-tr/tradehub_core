"""T-050 — Yerel disk `StorageAdapter`. Atomik yazma: temp + fsync + rename.

BUGÜNKÜ DAVRANIŞ KORUNUYOR
--------------------------
Yerleşim `tradehub_core/media/naming.py` ile birebir aynı: ad
`sha256(içerik)[:32] + uzantı`, dizin adın ilk 2 hex karakteri. Kapsam kökleri
`docs/MEDYA-DEPOLAMA-STANDARDI.md` §3.1'deki iki kök:

    public   <site>/public/files/<ab>/<hash>.<ext>     → nginx doğrudan servis
    private  <site>/private/files/<ab>/<hash>.<ext>    → yetki kapısından geçer

`move()` `access_level.set_level`'ın disk adımının aynısıdır: tek `os.replace`,
shard ve ad KORUNUR. Bu modül `File` kaydına, referanslara ve PII kapısına
DOKUNMAZ — onlar `access_level.py`'nin işi ve orada kalıyor. Buradaki `move`
yalnız baytları taşır.

NEDEN ATOMİK YAZMA (NFR-041)
----------------------------
Üretimdeki `naming._write_file_legacy` doğrudan hedefe yazıyor
(`open(disk_path, "wb+")`). Yazma yarıda kesilirse (OOM kill, disk dolu,
konteyner restart) diskte YARIM bir dosya kalır ve adı içerik-adresli olduğu
için "bu içerik zaten var" sanılır: bozuk dosya kalıcılaşır ve bir daha
düzeltilmez. Buradaki sıra bunu imkânsız kılar:

    1. aynı dizinde gizli geçici dosyaya yaz      (.tmp-XXXX.part)
    2. flush + os.fsync(fd)                        baytlar diskte
    3. os.chmod                                    izin son hâlinde
    4. os.replace(tmp, hedef)                      ATOMİK yer değiştirme
    5. os.fsync(dizin)                             ad da diskte

Aynı dizinde geçici dosya kullanmak şart: `os.replace` yalnız aynı dosya
sistemi içinde atomiktir. `/tmp`'e yazıp taşımak sessizce kopyala-sil'e döner
ve atomiklik kaybolur.

Adım 5 olmadan 4 yeterli DEĞİL: `os.replace` dizin girdisini değiştirir ama
ext4 varsayılan (`data=ordered`) ayarında dizin girdisi 5 saniyeye kadar
yalnız bellekte durabilir. Güç kesintisinde dosya içeriği diskte, adı
kayıptır. `fsync` desteklemeyen dosya sistemlerinde (bazı overlay/NFS
kurulumları) bu adım sessizce atlanır ve `fsync_supported` bayrağıyla
raporlanır — sessiz atlama değil, ölçülebilir atlama.

İKİNCİ SAVUNMA KATMANI (NFR-020)
--------------------------------
`ObjectKey.__post_init__` yalnız `shard == name[:2]` kontrol eder. Bu tek
başına yol geçişini durdurmaz: `ObjectKey(shard="..", name="../../etc/passwd")`
sözleşme doğrulamasından GEÇER (`"../../etc/passwd"[:2] == ".."`). Bu yüzden
disk uygulaması kendi kontrolünü yapar — `_SAFE_NAME` deseni + çözülmüş yolun
kök altında kaldığının `os.path.realpath` ile doğrulanması
(`access_level._disk_path` ile aynı desen).
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from typing import Any, Dict, Iterator, Optional, Tuple

from tradehub_core.media.pipeline.contracts.errors import ObjectNotFound, StorageConflict, StorageError
from tradehub_core.media.pipeline.contracts.storage import (
	SCOPE_PRIVATE,
	SCOPE_PUBLIC,
	SCOPES,
	ObjectKey,
	ObjectRef,
	ObjectStat,
	PutResult,
	content_hash,
	key_for,
)
from tradehub_core.media.pipeline.delivery import signed as signed_urls

#: Kabul edilen dosya adı. İçerik-adresli adlar `[0-9a-f]{32}\.<ext>` biçiminde;
#: desen biraz daha geniş tutuldu ki eski (migrate edilmemiş) `0505.jpg` gibi
#: adlar da okunabilsin — `docs/MEDYA-DEPOLAMA-STANDARDI.md` §6: "mevcut
#: `file_url`'ler KIRILMAZ". Ayırıcı, boşluk, `..` ve gizli dosya YOK.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: Akışlı hash parçası — `core/dedup.CHUNK_SIZE` ile aynı gerekçe: 500 MB'lık
#: bir videoda bellek ayak izi sabit kalsın.
CHUNK_SIZE: int = 1024 * 1024

#: Geçici dosya öneki. Nokta ile başlar → `iter_keys` taramasında ve nginx
#: `location /files/` altında görünmez; `_SAFE_NAME` de reddeder.
TEMP_PREFIX: str = ".tmp-"
TEMP_SUFFIX: str = ".part"

DEFAULT_FILE_MODE: int = 0o644
DEFAULT_DIR_MODE: int = 0o755


class LocalDiskStorage:
	"""Yerel dosya sisteminde içerik-adresli nesne deposu.

	Args:
	    public_root: `<site>/public/files` karşılığı dizin.
	    private_root: `<site>/private/files` karşılığı dizin.
	    signer: private kapsamda `url_for` için imzalayıcı. `None` ise
	        private URL istendiğinde `StorageError` atılır — sessizce
	        imzasız URL döndürmek, private dosyayı imzalıymış gibi göstermek
	        olurdu.
	    fsync: `False` yalnız testte. Üretimde kapatmak NFR-041'i iptal eder.
	"""

	def __init__(
		self,
		public_root: str,
		private_root: str,
		*,
		signer: Optional[signed_urls.UrlSigner] = None,
		fsync: bool = True,
		file_mode: int = DEFAULT_FILE_MODE,
		dir_mode: int = DEFAULT_DIR_MODE,
	) -> None:
		self._roots: Dict[str, str] = {
			SCOPE_PUBLIC: os.path.abspath(public_root),
			SCOPE_PRIVATE: os.path.abspath(private_root),
		}
		self._signer = signer
		self._fsync = bool(fsync)
		self._file_mode = int(file_mode)
		self._dir_mode = int(dir_mode)
		#: `os.fsync` dizin üzerinde desteklenmiyorsa `False`'a düşer ve
		#: raporlanır. Sessizce atlanmaz.
		self.fsync_supported: bool = True

	# ── yol çözümleme ──────────────────────────────────────────────────

	def root(self, scope: str) -> str:
		"""Kapsamın kök dizini."""
		if scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {scope!r}")
		return self._roots[scope]

	def _path(self, ref: ObjectRef) -> str:
		"""`ObjectRef` → mutlak disk yolu. Kök dışına çıkan yol reddedilir."""
		kok = self.root(ref.scope)
		ad = ref.key.name
		shard = ref.key.shard
		if not _SAFE_NAME.match(ad) or not _SAFE_NAME.match(shard):
			raise StorageError(
				"Güvensiz nesne adı", detay={"name": ad, "shard": shard}, retryable=False
			)
		hedef = os.path.realpath(os.path.join(kok, shard, ad))
		if hedef != kok and not hedef.startswith(os.path.realpath(kok) + os.sep):
			raise StorageError("Nesne yolu kök dizinin dışında", detay={"url": ref.url})
		return hedef

	# ── yardımcılar ────────────────────────────────────────────────────

	@staticmethod
	def _file_sha256(path: str) -> str:
		"""Dosyanın tam sha256'sı — akışlı, bellek ayak izi sabit."""
		ozet = hashlib.sha256()
		with open(path, "rb") as fh:
			for parca in iter(lambda: fh.read(CHUNK_SIZE), b""):
				ozet.update(parca)
		return ozet.hexdigest()

	def _fsync_dir(self, path: str) -> None:
		"""Dizin girdisini kalıcılaştır. Desteklenmeyen FS'te sessizce değil,
		`fsync_supported=False` bırakarak geçilir."""
		if not self._fsync:
			return
		try:
			fd = os.open(path, os.O_RDONLY)
		except OSError:
			self.fsync_supported = False
			return
		try:
			os.fsync(fd)
		except OSError:
			self.fsync_supported = False
		finally:
			os.close(fd)

	def _ensure_dir(self, path: str) -> None:
		os.makedirs(path, mode=self._dir_mode, exist_ok=True)

	def _atomic_write(self, path: str, content: bytes) -> None:
		"""temp + fsync + rename. Yarım dosya bırakmaz (NFR-041)."""
		dizin = os.path.dirname(path)
		self._ensure_dir(dizin)
		fd, gecici = tempfile.mkstemp(dir=dizin, prefix=TEMP_PREFIX, suffix=TEMP_SUFFIX)
		try:
			with os.fdopen(fd, "wb") as fh:
				fh.write(content)
				fh.flush()
				if self._fsync:
					os.fsync(fh.fileno())
			os.chmod(gecici, self._file_mode)
			os.replace(gecici, path)
		except BaseException:
			# Geçici dosya HER hata dalında temizlenir; aksi hâlde shard
			# dizini `.tmp-*.part` çöpüyle dolar ve kimse fark etmez.
			try:
				os.unlink(gecici)
			except OSError:
				pass
			raise
		self._fsync_dir(dizin)

	def _copy_across(self, src: str, dst: str) -> None:
		"""Farklı dosya sistemleri arası kopyala + fsync + rename.

		`os.replace` yalnız aynı dosya sistemi içinde çalışır (EXDEV).
		public ve private kökleri farklı mount'ta olan kurulumlarda bu dal
		devreye girer ve atomikliği HEDEF tarafında korur: kopya önce
		geçici ada yazılır, sonra rename edilir.
		"""
		dizin = os.path.dirname(dst)
		self._ensure_dir(dizin)
		fd, gecici = tempfile.mkstemp(dir=dizin, prefix=TEMP_PREFIX, suffix=TEMP_SUFFIX)
		try:
			with os.fdopen(fd, "wb") as hedef, open(src, "rb") as kaynak:
				for parca in iter(lambda: kaynak.read(CHUNK_SIZE), b""):
					hedef.write(parca)
				hedef.flush()
				if self._fsync:
					os.fsync(hedef.fileno())
			os.chmod(gecici, self._file_mode)
			os.replace(gecici, dst)
		except BaseException:
			try:
				os.unlink(gecici)
			except OSError:
				pass
			raise
		self._fsync_dir(dizin)

	# ── StorageAdapter ─────────────────────────────────────────────────

	def put(self, content: bytes, extension: str, *, scope: str = SCOPE_PUBLIC) -> PutResult:
		"""Baytları yaz. İçerik-adresli olduğu için doğal idempotent."""
		if scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {scope!r}")
		key = key_for(content, extension)
		ref = ObjectRef(key=key, scope=scope)
		yol = self._path(ref)

		if os.path.isfile(yol):
			mevcut = self._file_sha256(yol)
			if mevcut != content_hash(content):
				# Aynı anahtar, farklı içerik. Bu bir sha256 çakışması değil;
				# neredeyse her zaman diskteki dosyanın bozulduğu (yarım
				# yazılmış, elle değiştirilmiş) anlamına gelir. Sessizce
				# üzerine yazmak kanıtı yok eder.
				raise StorageConflict(
					"Aynı anahtarda farklı içerik var",
					detay={"url": ref.url, "on_disk_sha256": mevcut},
				)
			return PutResult(ref=ref, created=False, stat=self.stat(ref))

		try:
			self._atomic_write(yol, content)
		except OSError as hata:
			raise StorageError(
				"Nesne diske yazılamadı", detay={"url": ref.url, "errno": hata.errno}
			) from hata
		return PutResult(ref=ref, created=True, stat=self.stat(ref))

	def get(self, ref: ObjectRef) -> bytes:
		yol = self._path(ref)
		try:
			with open(yol, "rb") as fh:
				return fh.read()
		except FileNotFoundError:
			raise ObjectNotFound("Nesne bulunamadı", detay={"url": ref.url}) from None
		except OSError as hata:
			raise StorageError(
				"Nesne okunamadı", detay={"url": ref.url, "errno": hata.errno}
			) from hata

	def exists(self, ref: ObjectRef) -> bool:
		"""Yan etkisiz, hata atmaz — güvensiz ad da `False` döner."""
		try:
			return os.path.isfile(self._path(ref))
		except (StorageError, ValueError):
			return False

	def stat(self, ref: ObjectRef) -> ObjectStat:
		"""Künye. `content_hash` diskten AKIŞLI hesaplanır.

		Sözleşme "içeriği okumadan" diyor; disk uygulamasında bu tam olarak
		mümkün değil — ad yalnız hash'in ilk 32 hex'ini taşır, `ObjectStat.
		content_hash` ise tam 64 hex. Alternatif (adın 32 hex'ini uydurup
		tam hash yerine koymak) `PutResult` ve `mirror` doğrulamasını sessizce
		yalanlardı. Maliyet ölçüldü ve kabul edildi: en büyük tek görsel
		2,35 MB (`docs/reports/08-canli-olcum.md`), 1 MiB parçalarla akışlı
		okuma. Videolarda (23 dosya) maliyet daha yüksek; çağıran sık
		`stat()` yapacaksa `stat_fast()` kullanmalı.
		"""
		yol = self._path(ref)
		try:
			kunye = os.stat(yol)
		except FileNotFoundError:
			raise ObjectNotFound("Nesne bulunamadı", detay={"url": ref.url}) from None
		if not os.path.isfile(yol):
			raise ObjectNotFound("Nesne bulunamadı", detay={"url": ref.url})
		return ObjectStat(
			size_bytes=kunye.st_size,
			content_hash=self._file_sha256(yol),
			modified_at=kunye.st_mtime,
			extra={"backend": "local", "path_exists": True},
		)

	def stat_fast(self, ref: ObjectRef) -> ObjectStat:
		"""Hash HESAPLAMADAN künye — `content_hash` adın 32 hex'inden türetilir.

		Sözleşmenin parçası DEĞİLDİR (protokolde yok). Retention süpürmesi
		gibi binlerce dosyayı gezen işler için var: orada tek gereken boyut
		ve mtime. Döndürülen `content_hash` **kısaltılmış** (32 hex) ve
		`extra["hash_truncated"] = True` ile işaretlidir — tam hash sanılıp
		karşılaştırmaya sokulmasın.
		"""
		yol = self._path(ref)
		try:
			kunye = os.stat(yol)
		except FileNotFoundError:
			raise ObjectNotFound("Nesne bulunamadı", detay={"url": ref.url}) from None
		govde = os.path.splitext(ref.key.name)[0]
		return ObjectStat(
			size_bytes=kunye.st_size,
			content_hash=govde,
			modified_at=kunye.st_mtime,
			extra={"backend": "local", "hash_truncated": True},
		)

	def delete(self, ref: ObjectRef) -> bool:
		"""İdempotent: yoktu ise `False`."""
		yol = self._path(ref)
		try:
			os.unlink(yol)
			return True
		except FileNotFoundError:
			return False
		except OSError as hata:
			raise StorageError(
				"Nesne silinemedi", detay={"url": ref.url, "errno": hata.errno}
			) from hata

	def move(self, source: ObjectRef, target_scope: str) -> ObjectRef:
		"""Kapsamlar arası taşı — anahtar korunur, tek `os.replace`."""
		if target_scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {target_scope!r}")
		hedef = ObjectRef(key=source.key, scope=target_scope)
		kaynak_yol = self._path(source)
		hedef_yol = self._path(hedef)

		if source.scope == target_scope:
			# Aynı kapsama taşımak no-op; kaynak yoksa yine de hata.
			if not os.path.isfile(kaynak_yol):
				raise ObjectNotFound("Nesne bulunamadı", detay={"url": source.url})
			return hedef

		if not os.path.isfile(kaynak_yol):
			raise ObjectNotFound("Nesne bulunamadı", detay={"url": source.url})

		if os.path.isfile(hedef_yol):
			# Hedefte aynı içerik varsa birleşme (sözleşme: çakışma DEĞİL).
			if self._file_sha256(hedef_yol) == self._file_sha256(kaynak_yol):
				os.unlink(kaynak_yol)
				return hedef
			raise StorageConflict("Hedefte farklı içerik var", detay={"url": hedef.url})

		self._ensure_dir(os.path.dirname(hedef_yol))
		try:
			os.replace(kaynak_yol, hedef_yol)
		except OSError as hata:
			if hata.errno != 18:  # EXDEV — farklı dosya sistemi
				raise StorageError(
					"Nesne taşınamadı", detay={"url": source.url, "errno": hata.errno}
				) from hata
			self._copy_across(kaynak_yol, hedef_yol)
			os.unlink(kaynak_yol)
		self._fsync_dir(os.path.dirname(hedef_yol))
		self._fsync_dir(os.path.dirname(kaynak_yol))
		return hedef

	def iter_keys(self, *, scope: str = SCOPE_PUBLIC, prefix: str = "") -> Iterator[ObjectKey]:
		"""Tembel tarama — `os.scandir`, tüm ağacı belleğe almadan.

		Geçici dosyalar (`.tmp-*.part`) ve `_SAFE_NAME`'e uymayan adlar
		atlanır: yarım yazılmış bir dosyayı "nesne" saymak, uzlaştırma
		görevine sahte yetim raporlatırdı.
		"""
		kok = self.root(scope)
		if not os.path.isdir(kok):
			return
		try:
			shardlar = sorted(os.listdir(kok))
		except OSError:
			return
		for shard in shardlar:
			shard_yol = os.path.join(kok, shard)
			if not os.path.isdir(shard_yol) or not _SAFE_NAME.match(shard):
				continue
			try:
				with os.scandir(shard_yol) as girisler:
					for giris in girisler:
						ad = giris.name
						if not giris.is_file() or not _SAFE_NAME.match(ad):
							continue
						if shard != ad[: len(shard)]:
							# Shard dizini adın önekiyle uyuşmuyor: taşınmış
							# ya da elle konmuş dosya. Anahtar üretilemez.
							continue
						goreli = f"{shard}/{ad}"
						if prefix and not goreli.startswith(prefix):
							continue
						yield ObjectKey(shard=shard, name=ad)
			except OSError:
				continue

	def url_for(self, ref: ObjectRef, *, ttl_seconds: Optional[int] = None) -> str:
		"""Servis edilebilir URL. Public'te TTL yok sayılır, private'ta imzalanır."""
		if ref.scope != SCOPE_PRIVATE:
			return ref.url
		if self._signer is None:
			raise StorageError(
				"Private URL imzalanamıyor: imzalayıcı tanımlı değil.",
				detay={"url": ref.url, "reason": "no_signer"},
				retryable=False,
			)
		return self._signer.sign(ref.url, ttl_seconds=ttl_seconds).url

	# ── sözleşme dışı yardımcılar ──────────────────────────────────────

	def __len__(self) -> int:
		"""Her iki kapsamdaki toplam nesne sayısı — test kolaylığı."""
		return sum(1 for scope in SCOPES for _ in self.iter_keys(scope=scope))

	def usage_bytes(self, *, scope: Optional[str] = None) -> int:
		"""Kapsamın (ya da hepsinin) kapladığı bayt — retention raporu için."""
		kapsamlar: Tuple[str, ...] = SCOPES if scope is None else (scope,)
		toplam = 0
		for s in kapsamlar:
			for key in self.iter_keys(scope=s):
				try:
					toplam += os.path.getsize(self._path(ObjectRef(key=key, scope=s)))
				except OSError:
					continue
		return toplam

	def sweep_temp_files(self, *, older_than_seconds: float = 3600.0) -> Dict[str, Any]:
		"""Kalıntı `.tmp-*.part` dosyalarını temizle.

		`_atomic_write` her hata dalında kendi geçicisini siler, ama süreç
		SIGKILL alırsa (OOM) `finally` çalışmaz. Bu süpürücü o tek boşluğu
		kapatır ve `media/jobs.py`'nin takılı-iş süpürücüsüyle aynı
		mantıktadır: yaş eşiği olmadan çalışan bir yazmanın geçicisini
		silme riski var.
		"""
		import time as _time

		esik = _time.time() - float(older_than_seconds)
		silinen = 0
		bayt = 0
		for scope in SCOPES:
			kok = self._roots[scope]
			if not os.path.isdir(kok):
				continue
			for dizin, _alt, dosyalar in os.walk(kok):
				for ad in dosyalar:
					if not ad.startswith(TEMP_PREFIX):
						continue
					yol = os.path.join(dizin, ad)
					try:
						if os.path.getmtime(yol) >= esik:
							continue
						boyut = os.path.getsize(yol)
						os.unlink(yol)
						silinen += 1
						bayt += boyut
					except OSError:
						continue
		return {"deleted": silinen, "freed_bytes": bayt}


def from_site_path(site_path: str, **kwargs: Any) -> LocalDiskStorage:
	"""`<site>` kökünden depo kur — `frappe.get_site_path()` çıktısı beklenir.

	`frappe` import EDİLMEZ; çağıran yolu verir. Böylece aynı sınıf bench
	içinde ve dışında aynı biçimde kurulur.
	"""
	return LocalDiskStorage(
		os.path.join(site_path, "public", "files"),
		os.path.join(site_path, "private", "files"),
		**kwargs,
	)


__all__ = ["LocalDiskStorage", "from_site_path", "CHUNK_SIZE", "TEMP_PREFIX"]
