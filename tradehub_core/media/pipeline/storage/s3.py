"""T-051 — S3 uyumlu nesne deposu. `boto3` YOKSA import EDİLMEZ.

ÖLÇÜLEN GERÇEK
--------------
Bugün üretimde S3 YOK. `docs/standards/retention.md` §5.3'te taranmış hâliyle:
`tradehub_core/` altında `boto3`/`s3_bucket`/`minio` geçen tek satır
`audit/__init__.py:23`'teki bir YORUM. `requirements.txt` üç satır ve içinde
S3 istemcisi yok. Bütün saklama tek yerel diskte.

Bu modül o gerçeği değiştirmiyor, sadece kapıyı açıyor. İki katı kural:

  1. **`s3_enabled=0` iken hiçbir kod S3 varlığını varsaymaz.** `S3Config.
     enabled` `False` ise `S3Storage` KURULAMAZ (`StorageError`). Fabrika
     (`storage/__init__.py`) bu durumda yerel depoya düşer ve düşüşü
     `StoragePlan.downgraded_from` ile RAPORLAR — sessiz düşüş yok.
  2. **`import boto3` modül düzeyinde YOK.** Bu dosya boto3 kurulu olmayan
     bir makinede sorunsuz import edilir; `boto3` yalnız ilk istemci
     ihtiyacında, `_client()` içinde import edilir. `boto3_available()`
     import bile etmeden `importlib.util.find_spec` ile bakar.

Ölçüldü (2026-08-18): `boto3` yerelde YOK, `istoc-dev-backend-1`
konteynerinde VAR. Yani bu modülün gerçek boto3 ile çalıştığı tek yer
konteyner; testler sahte istemciyle koşuyor (bkz. `tests/
test_storage_adapters.py` — sahte istemci gerçek S3 semantiğini taklit eder,
GERÇEK S3'e karşı ÖLÇÜLMEDİ).

ANAHTAR YERLEŞİMİ
-----------------
    <prefix>/<scope>/<shard>/<ad>

`scope` anahtarın parçasıdır çünkü aynı içerik hem public hem private
kapsamda bulunabilir (sözleşme: "aynı anahtar farklı kökte durabilir") ve
`move()` kapsamlar arası taşımadır. Tek bucket + kapsam öneki, iki ayrı
bucket'tan daha ucuz yönetilir; kapsam ayrımı bucket policy yerine
`url_for` (public → CDN, private → presigned) tarafında uygulanır.

İÇERİK DOĞRULAMA
----------------
ETag S3'te içerik hash'i DEĞİLDİR: çok parçalı yüklemede `-N` sonekli bir
özet olur, SSE-KMS ile de MD5 olmaktan çıkar. Bu yüzden tam sha256
`x-amz-meta-sha256` metadata alanında saklanır ve `stat()` onu döner.
Metadata'sı olmayan (bu motordan önce yüklenmiş) nesnede `content_hash` boş
döner ve `extra["hash_unknown"]=True` işaretlenir — uydurma değer üretilmez.
"""

from __future__ import annotations

import importlib.util
import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, Mapping, Optional

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
	key_for_digest,
)
from tradehub_core.media.pipeline.delivery import signed as signed_urls

#: sha256'nın taşındığı kullanıcı metadata anahtarı. boto3 `Metadata` sözlüğüne
#: verilen anahtarlar `x-amz-meta-` önekiyle gönderilir; okurken önek düşer.
META_SHA256: str = "sha256"

#: "yok" anlamına gelen S3 hata kodları. Farklı uygulamalar (MinIO, Ceph, AWS)
#: aynı durumu farklı kodla döndürüyor.
NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound", "NoSuchBucket"})

#: Presigned URL üst sınırı — imza v4'ün mutlak tavanı 7 gün. `delivery/signed`
#: kelepçesi (86400 sn) zaten daha dar; ikisi de uygulanır, dar olan kazanır.
S3_PRESIGN_MAX_SECONDS: int = 604800


class S3ObjectMissing(Exception):
	"""Sahte/gerçek istemciden gelen "nesne yok" durumunun ortak biçimi."""


def boto3_available() -> bool:
	"""`boto3` kurulu mu — IMPORT ETMEDEN bak.

	`find_spec` modülü çalıştırmaz; boto3'ün import maliyeti (~0,3 sn) ve yan
	etkileri (credential zinciri okuma) ödenmeden cevap alınır.
	"""
	try:
		return importlib.util.find_spec("boto3") is not None
	except (ImportError, ValueError):  # pragma: no cover - bozuk kurulum
		return False


@dataclass(frozen=True)
class S3Config:
	"""S3 bağlantı ayarları. `enabled=False` varsayılan — bilinçli açılır."""

	enabled: bool = False
	bucket: str = ""
	region: str = ""
	endpoint_url: str = ""
	prefix: str = "media"
	access_key_id: str = ""
	secret_access_key: str = ""
	#: Nesne sınıfı. `s3_cold` katmanı için `GLACIER_IR`/`DEEP_ARCHIVE`.
	storage_class: str = "STANDARD"
	#: Public kapsamda dönecek taban URL (CDN origin). Boşsa sözleşmedeki
	#: `file_url` döner — yol yapısı zaten CDN origin olarak temiz
	#: (`docs/MEDYA-DEPOLAMA-STANDARDI.md` §8).
	public_base_url: str = ""
	addressing_style: str = "auto"
	server_side_encryption: str = "none"
	multipart_threshold_bytes: int = 64 * 1024 * 1024
	max_concurrency: int = 4
	extra: Dict[str, Any] = field(default_factory=dict)

	@classmethod
	def from_mapping(cls, conf: Mapping[str, Any]) -> "S3Config":
		"""`site_config.json` benzeri düz sözlükten oku.

		Anahtar adları `s3_` önekli: `s3_enabled`, `s3_bucket`, ... Bu ad
		şeması görev tanımındaki `s3_enabled=0` bayrağıyla birebir aynıdır.
		"""

		def _al(ad: str, varsayilan: Any = "") -> Any:
			return conf.get(f"s3_{ad}", varsayilan)

		return cls(
			enabled=bool(int(conf.get("s3_enabled", 0) or 0)),
			bucket=str(_al("bucket") or ""),
			region=str(_al("region") or ""),
			endpoint_url=str(_al("endpoint_url") or ""),
			prefix=str(_al("prefix", "media") or "media").strip("/"),
			access_key_id=str(_al("access_key_id") or ""),
			secret_access_key=str(_al("secret_access_key") or ""),
			storage_class=str(_al("storage_class", "STANDARD") or "STANDARD"),
			public_base_url=str(_al("public_base_url") or "").rstrip("/"),
			addressing_style=str(_al("addressing_style", "auto") or "auto"),
			server_side_encryption=str(_al("server_side_encryption", "none") or "none"),
			multipart_threshold_bytes=max(
				5 * 1024 * 1024,
				int(_al("multipart_threshold_mb", 64) or 64) * 1024 * 1024,
			),
			max_concurrency=max(1, int(_al("max_concurrency", 4) or 4)),
		)

	def problems(self) -> list:
		"""Kullanılamaz yapan eksikler. Boş liste = kullanılabilir."""
		eksik = []
		if not self.enabled:
			eksik.append("s3_enabled=0")
		if self.enabled and not self.bucket:
			eksik.append("s3_bucket boş")
		if self.enabled and not boto3_available():
			eksik.append("boto3 kurulu değil")
		return eksik

	@property
	def usable(self) -> bool:
		return not self.problems()


class S3Storage:
	"""S3 uyumlu `StorageAdapter`.

	Args:
	    config: `enabled=False` ise kurulum REDDEDİLİR.
	    client_factory: İstemci üreten çağrılabilir. `None` ise `boto3`
	        tembel import edilir. Testler burayı sahte istemciyle doldurur;
	        üretim yolu değişmez.
	    signer: private kapsamda presigned URL yerine kendi imzalayıcımızı
	        kullanmak istenirse. `None` ise `generate_presigned_url`.
	"""

	def __init__(
		self,
		config: S3Config,
		*,
		client_factory: Optional[Callable[[], Any]] = None,
		signer: Optional[signed_urls.UrlSigner] = None,
		alarm: Optional[Callable[[Dict[str, Any]], None]] = None,
	) -> None:
		if not config.enabled:
			# Görev şartı: s3_enabled=0 iken hiçbir kod S3 varlığını
			# varsaymamalı. En sert uygulama, nesnenin hiç kurulamaması.
			raise StorageError(
				"S3 kapalı (s3_enabled=0) — S3Storage kurulamaz.",
				detay={"problems": config.problems()},
				retryable=False,
			)
		if client_factory is None and not boto3_available():
			raise StorageError(
				"boto3 kurulu değil — S3Storage kurulamaz.",
				detay={"problems": config.problems()},
				retryable=False,
			)
		if not config.bucket:
			raise StorageError("s3_bucket tanımlı değil.", detay={"problems": config.problems()})
		self._config = config
		self._client_factory = client_factory
		self._signer = signer
		self._alarm = alarm
		self._cached_client: Any = None

	# ── istemci ────────────────────────────────────────────────────────

	@property
	def config(self) -> S3Config:
		return self._config

	def _client(self) -> Any:
		"""İstemciyi tembel kur. `import boto3` YALNIZ burada."""
		if self._cached_client is not None:
			return self._cached_client
		if self._client_factory is not None:
			self._cached_client = self._client_factory()
			return self._cached_client
		import boto3  # noqa: PLC0415 - bilinçli tembel import
		from botocore.config import Config as BotoConfig  # noqa: PLC0415

		kwargs: Dict[str, Any] = {
			"config": BotoConfig(
				s3={"addressing_style": self._config.addressing_style},
				# İmzalı URL sürümü AÇIKÇA sabitlenir. botocore varsayılanı
				# ortama göre SigV2'ye düşebiliyor; MinIO SigV2'yi kabul eder
				# ama 2014 sonrası açılan AWS bölgeleri ETMEZ — o durumda özel
				# dosya teslimi tamamen kırılır. MinIO ile ölçüldü (T-051,
				# docs/reports/23-t051-s3-adaptor.md B-01): s3v4 çalışıyor.
				signature_version="s3v4",
				retries={"max_attempts": 5, "mode": "standard"},
			),
		}
		if self._config.region:
			kwargs["region_name"] = self._config.region
		if self._config.endpoint_url:
			kwargs["endpoint_url"] = self._config.endpoint_url
		if self._config.access_key_id:
			kwargs["aws_access_key_id"] = self._config.access_key_id
			kwargs["aws_secret_access_key"] = self._config.secret_access_key
		self._cached_client = boto3.client("s3", **kwargs)
		return self._cached_client

	# ── anahtar eşlemesi ───────────────────────────────────────────────

	def object_key(self, ref: ObjectRef) -> str:
		"""`ObjectRef` → S3 anahtarı."""
		onek = f"{self._config.prefix}/" if self._config.prefix else ""
		return f"{onek}{ref.scope}/{ref.key.relative}"

	def _scope_prefix(self, scope: str) -> str:
		onek = f"{self._config.prefix}/" if self._config.prefix else ""
		return f"{onek}{scope}/"

	# ── hata çevirisi ──────────────────────────────────────────────────

	@staticmethod
	def _is_missing(hata: BaseException) -> bool:
		"""İstisna "nesne yok" mu — boto3 ClientError ve sahte istemci için."""
		if isinstance(hata, S3ObjectMissing):
			return True
		yanit = getattr(hata, "response", None)
		if isinstance(yanit, dict):
			kod = str(yanit.get("Error", {}).get("Code", ""))
			durum = str(yanit.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
			return kod in NOT_FOUND_CODES or durum == "404"
		return False

	def _wrap(self, hata: BaseException, ref: ObjectRef, islem: str) -> StorageError:
		if self._is_missing(hata):
			return ObjectNotFound("Nesne bulunamadı", detay={"url": ref.url, "op": islem})
		wrapped = StorageError(
			"S3 işlemi başarısız", detay={"url": ref.url, "op": islem, "error": str(hata)}
		)
		if self._alarm is not None:
			try:
				self._alarm(
					{
						"type": "s3_error",
						"operation": islem,
						"url": ref.url,
						"error_type": type(hata).__name__,
					}
				)
			except Exception:
				pass
		return wrapped

	def _put_extra_args(self, digest: str) -> Dict[str, Any]:
		args: Dict[str, Any] = {
			"Metadata": {META_SHA256: digest},
			"StorageClass": self._config.storage_class,
		}
		encryption = str(self._config.server_side_encryption or "none")
		if encryption in {"AES256", "aws:kms"}:
			args["ServerSideEncryption"] = encryption
		return args

	# ── StorageAdapter ─────────────────────────────────────────────────

	def put(self, content: bytes, extension: str, *, scope: str = SCOPE_PUBLIC) -> PutResult:
		if scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {scope!r}")
		key = key_for(content, extension)
		ref = ObjectRef(key=key, scope=scope)
		ozet = content_hash(content)

		mevcut = self._head(ref)
		if mevcut is not None:
			bilinen = (mevcut.get("Metadata") or {}).get(META_SHA256, "")
			if bilinen and bilinen != ozet:
				raise StorageConflict(
					"Aynı anahtarda farklı içerik var",
					detay={"url": ref.url, "on_s3_sha256": bilinen},
				)
			if not bilinen and int(mevcut.get("ContentLength", -1)) != len(content):
				# Metadata yok (eski nesne) — boyut bile tutmuyorsa çakışma
				# kesin. Boyut tutuyorsa içeriği indirip karşılaştırmak
				# gerekirdi; bu maliyet bilinçli olarak ödenmiyor ve durum
				# `created=False` olarak raporlanıyor.
				raise StorageConflict(
					"Aynı anahtarda farklı boyutta nesne var",
					detay={"url": ref.url, "on_s3_size": mevcut.get("ContentLength")},
				)
			return PutResult(ref=ref, created=False, stat=self._stat_from_head(mevcut))

		try:
			self._client().put_object(
				Bucket=self._config.bucket,
				Key=self.object_key(ref),
				Body=content,
				**self._put_extra_args(ozet),
			)
		except Exception as hata:
			raise self._wrap(hata, ref, "put") from hata

		kunye = self._head(ref)
		if kunye is None:  # pragma: no cover - yazdıktan sonra yok olması
			raise StorageError("Yazılan nesne okunamadı", detay={"url": ref.url})
		return PutResult(ref=ref, created=True, stat=self._stat_from_head(kunye))

	def put_stream(
		self,
		chunks: Iterable[bytes],
		extension: str,
		*,
		scope: str = SCOPE_PUBLIC,
	) -> PutResult:
		"""Akışı diskte geçici spool'a al, hashle ve S3'e streaming yükle.

		İçerik adresi yüklemeden önce bilinmek zorunda olduğu için tek geçişli
		bir ağ upload'u mümkün değildir. Spool bellekte değil geçici dosyadadır;
		böylece 2 GB girişte Python tepe belleği parça boyutuna bağlı kalır.
		"""
		if scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {scope!r}")
		digest = hashlib.sha256()
		total = 0
		with tempfile.TemporaryFile(prefix="media-s3-stream-") as spool:
			for raw in chunks:
				if not isinstance(raw, (bytes, bytearray, memoryview)):
					raise TypeError("put_stream parçaları bytes-benzeri olmalıdır")
				part = bytes(raw)
				if not part:
					continue
				digest.update(part)
				total += len(part)
				spool.write(part)
			key = key_for_digest(digest.hexdigest(), extension)
			ref = ObjectRef(key=key, scope=scope)
			mevcut = self._head(ref)
			if mevcut is not None:
				known = (mevcut.get("Metadata") or {}).get(META_SHA256, "")
				if known and known != digest.hexdigest():
					raise StorageConflict("Aynı anahtarda farklı içerik var", detay={"url": ref.url})
				if not known and int(mevcut.get("ContentLength", -1)) != total:
					raise StorageConflict("Aynı anahtarda farklı boyutta nesne var", detay={"url": ref.url})
				return PutResult(ref=ref, created=False, stat=self._stat_from_head(mevcut))

			spool.seek(0)
			client = self._client()
			extra = self._put_extra_args(digest.hexdigest())
			try:
				if hasattr(client, "upload_fileobj"):
					from boto3.s3.transfer import TransferConfig  # noqa: PLC0415 - yalnız S3 açıkken

					transfer = TransferConfig(
						multipart_threshold=self._config.multipart_threshold_bytes,
						multipart_chunksize=max(5 * 1024 * 1024, self._config.multipart_threshold_bytes),
						max_concurrency=self._config.max_concurrency,
						use_threads=self._config.max_concurrency > 1,
					)
					client.upload_fileobj(
						spool,
						self._config.bucket,
						self.object_key(ref),
						ExtraArgs=extra,
						Config=transfer,
					)
				else:
					# Enjekte edilen küçük test istemcileri transfer manager yüzeyini
					# sunmayabilir; Body file-like kaldığı için bu yol da streaming'dir.
					client.put_object(
						Bucket=self._config.bucket,
						Key=self.object_key(ref),
						Body=spool,
						**extra,
					)
			except Exception as hata:
				raise self._wrap(hata, ref, "put_stream") from hata

		kunye = self._head(ref)
		if kunye is None:
			raise StorageError("Yazılan nesne okunamadı", detay={"url": ref.url})
		return PutResult(ref=ref, created=True, stat=self._stat_from_head(kunye))

	def get(self, ref: ObjectRef) -> bytes:
		try:
			yanit = self._client().get_object(Bucket=self._config.bucket, Key=self.object_key(ref))
		except Exception as hata:
			raise self._wrap(hata, ref, "get") from hata
		govde = yanit["Body"]
		try:
			return govde.read()
		finally:
			kapat = getattr(govde, "close", None)
			if callable(kapat):
				kapat()

	def iter_bytes(self, ref: ObjectRef, *, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
		if int(chunk_size) < 1:
			raise ValueError("chunk_size pozitif olmalıdır")
		try:
			yanit = self._client().get_object(Bucket=self._config.bucket, Key=self.object_key(ref))
		except Exception as hata:
			raise self._wrap(hata, ref, "get_stream") from hata
		body = yanit["Body"]
		try:
			while True:
				part = body.read(int(chunk_size))
				if not part:
					break
				yield part
		finally:
			close = getattr(body, "close", None)
			if callable(close):
				close()

	def exists(self, ref: ObjectRef) -> bool:
		"""Yan etkisiz. Ağ hatası da `False` döner — sözleşme "hata atmaz" diyor.

		Bu, ağ kesintisinde "nesne yok" cevabı üretir ve çağıran onu yeniden
		yazmayı deneyebilir; içerik-adresli olduğu için yeniden yazmak zararsız.

		`_head` "yok" DIŞINDAKİ hataları `StorageError` olarak fırlatır (bunu
		`stat()` istiyor). Burada onu yutmak ZORUNLU: aksi hâlde bu fonksiyon
		hem Protocol sözleşmesini hem yukarıdaki kendi vaadini çiğniyordu.
		Ölçüldü (T-051, B-02): MinIO kapalıyken 8,9 sn sonra fırlatıyordu ve
		`TieredStorage.url_for()` `cold.exists()` çağırdığı için soğuk katman
		düştüğünde render kırılıyordu.
		"""
		try:
			return self._head(ref) is not None
		except StorageError:
			return False

	def stat(self, ref: ObjectRef) -> ObjectStat:
		kunye = self._head(ref)
		if kunye is None:
			raise ObjectNotFound("Nesne bulunamadı", detay={"url": ref.url})
		return self._stat_from_head(kunye)

	def delete(self, ref: ObjectRef) -> bool:
		"""İdempotent. S3 `delete_object` olmayan anahtarda da başarılı döner,
		bu yüzden önce `head` ile varlık ölçülür."""
		if self._head(ref) is None:
			return False
		try:
			self._client().delete_object(Bucket=self._config.bucket, Key=self.object_key(ref))
		except Exception as hata:
			raise self._wrap(hata, ref, "delete") from hata
		return True

	def move(self, source: ObjectRef, target_scope: str) -> ObjectRef:
		"""Kapsam değiştir — S3'te taşıma yok, kopyala + sil.

		Kopya BAŞARILI olmadan kaynak silinmez. Sıra tersine dönerse tek bir
		ağ hatası veri kaybı olur.
		"""
		if target_scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {target_scope!r}")
		hedef = ObjectRef(key=source.key, scope=target_scope)
		kaynak_kunye = self._head(source)
		if kaynak_kunye is None:
			raise ObjectNotFound("Nesne bulunamadı", detay={"url": source.url})
		if source.scope == target_scope:
			return hedef

		hedef_kunye = self._head(hedef)
		if hedef_kunye is not None:
			kaynak_ozet = (kaynak_kunye.get("Metadata") or {}).get(META_SHA256, "")
			hedef_ozet = (hedef_kunye.get("Metadata") or {}).get(META_SHA256, "")
			if kaynak_ozet and hedef_ozet and kaynak_ozet != hedef_ozet:
				raise StorageConflict("Hedefte farklı içerik var", detay={"url": hedef.url})
			self.delete(source)
			return hedef

		try:
			self._client().copy_object(
				Bucket=self._config.bucket,
				Key=self.object_key(hedef),
				CopySource={"Bucket": self._config.bucket, "Key": self.object_key(source)},
				MetadataDirective="COPY",
			)
		except Exception as hata:
			raise self._wrap(hata, source, "move") from hata
		self.delete(source)
		return hedef

	def iter_keys(self, *, scope: str = SCOPE_PUBLIC, prefix: str = "") -> Iterator[ObjectKey]:
		"""Sayfalayarak dolaş — tüm listeyi belleğe almadan."""
		if scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {scope!r}")
		kok = self._scope_prefix(scope)
		istemci = self._client()
		sayfalayici = istemci.get_paginator("list_objects_v2")
		for sayfa in sayfalayici.paginate(Bucket=self._config.bucket, Prefix=kok + (prefix or "")):
			for nesne in sayfa.get("Contents") or []:
				goreli = str(nesne["Key"])[len(kok) :]
				parcalar = goreli.split("/")
				if len(parcalar) != 2 or not parcalar[1]:
					continue
				yield ObjectKey(shard=parcalar[0], name=parcalar[1])

	def url_for(self, ref: ObjectRef, *, ttl_seconds: Optional[int] = None) -> str:
		"""Public'te CDN/origin URL'i, private'ta süreli imzalı URL."""
		if ref.scope != SCOPE_PRIVATE:
			if self._config.public_base_url:
				return f"{self._config.public_base_url}{ref.url}"
			return ref.url
		ttl = signed_urls.clamp_ttl(ttl_seconds)
		ttl = min(ttl, S3_PRESIGN_MAX_SECONDS)
		if self._signer is not None:
			return self._signer.sign(ref.url, ttl_seconds=ttl).url
		try:
			return self._client().generate_presigned_url(
				"get_object",
				Params={"Bucket": self._config.bucket, "Key": self.object_key(ref)},
				ExpiresIn=ttl,
			)
		except Exception as hata:
			raise self._wrap(hata, ref, "url_for") from hata

	# ── yardımcılar ────────────────────────────────────────────────────

	def _head(self, ref: ObjectRef) -> Optional[Dict[str, Any]]:
		"""`head_object` — yoksa `None`. Diğer hatalar `StorageError`."""
		try:
			return dict(
				self._client().head_object(Bucket=self._config.bucket, Key=self.object_key(ref))
			)
		except Exception as hata:
			if self._is_missing(hata):
				return None
			raise self._wrap(hata, ref, "head") from hata

	@staticmethod
	def _stat_from_head(kunye: Mapping[str, Any]) -> ObjectStat:
		metadata = dict(kunye.get("Metadata") or {})
		ozet = metadata.get(META_SHA256, "")
		degistirme = kunye.get("LastModified")
		zaman = 0.0
		if degistirme is not None:
			zaman_fn = getattr(degistirme, "timestamp", None)
			zaman = float(zaman_fn()) if callable(zaman_fn) else float(degistirme)
		return ObjectStat(
			size_bytes=int(kunye.get("ContentLength", 0)),
			content_hash=ozet,
			modified_at=zaman,
			extra={
				"backend": "s3",
				"etag": str(kunye.get("ETag", "")).strip('"'),
				"storage_class": kunye.get("StorageClass", "STANDARD"),
				# Uydurma değer üretmemek için: metadata yoksa açıkça işaretle.
				"hash_unknown": not ozet,
			},
		)

	def __len__(self) -> int:
		return sum(1 for scope in SCOPES for _ in self.iter_keys(scope=scope))


def config_from_env(env: Optional[Mapping[str, str]] = None) -> S3Config:
	"""Ortam değişkenlerinden ayar üret — `MEDIA_ENGINE_S3_*`.

	`site_config.json` okumak `frappe` gerektirir; bu paket frappe'siz
	kalmak zorunda. `api/` katmanı `S3Config.from_mapping(frappe.conf)`
	çağırır, saf katman ortamı okur.
	"""
	kaynak = os.environ if env is None else env
	duz: Dict[str, Any] = {}
	for anahtar, deger in kaynak.items():
		if anahtar.startswith("MEDIA_ENGINE_S3_"):
			duz["s3_" + anahtar[len("MEDIA_ENGINE_S3_") :].lower()] = deger
	return S3Config.from_mapping(duz)


__all__ = [
	"S3Config",
	"S3Storage",
	"S3ObjectMissing",
	"boto3_available",
	"config_from_env",
	"META_SHA256",
	"S3_PRESIGN_MAX_SECONDS",
]
