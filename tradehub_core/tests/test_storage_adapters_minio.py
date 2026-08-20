"""T-051 — Dört depolama kipi GERÇEK bir S3 uyumlu servise (MinIO) karşı.

NİYE AYRI DOSYA
---------------
`test_storage_adapters.py` aynı dört kipi **sahte** istemciyle koşturur ve
kendi doküman başlığında sınırını yazar: "sahte istemci gerçek S3
semantiğini taklit eder ama GERÇEK S3'e karşı ÖLÇÜLMEDİ". Bu dosya o
boşluğu kapatır ve sahte istemcili dosyaya DOKUNMAZ: sözleşme gövdesi
(`StorageContractMixin`) oradan İTHAL edilir, yeniden yazılmaz. Yani iki
koşum arasında test metni farkı yoktur — yalnız arka uç değişir.

ÇALIŞTIRMA (backend konteynerinde, `boto3` gerekir)
---------------------------------------------------
    # sözleşme koşumu
    env/bin/python -m unittest tradehub_core.tests.test_storage_adapters_minio -v

    # ölçüm tablosu (rapor için)
    env/bin/python -m tradehub_core.tests.test_storage_adapters_minio --measure

    # servis kapalıyken hata yolu
    env/bin/python -m tradehub_core.tests.test_storage_adapters_minio --failure

MinIO ulaşılamazsa testler ATLANIR (skip), DÜŞMEZ: bu dosya CI'da S3
zorunluluğu getirmemeli — üretimde S3 yok ve yokluğu bir hata değil.

AYAR
----
`MEDIA_ENGINE_S3_*` ortam değişkenleri (`s3.config_from_env` ile aynı ad
şeması). Varsayılanlar `docker/docker-compose.yml`'daki `minio` servisine
göredir; o servis medya hattına BAĞLI DEĞİLDİR ve `s3_enabled` üretimde 0
kalır.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.contracts.errors import (  # noqa: E402
	MediaEngineError,
	ObjectNotFound,
	StorageError,
)
from tradehub_core.media.pipeline.contracts.storage import (  # noqa: E402
	SCOPE_PRIVATE,
	SCOPE_PUBLIC,
	ObjectRef,
	content_hash,
)
from tradehub_core.media.pipeline.storage import (  # noqa: E402
	MODE_LOCAL,
	MODE_MIRROR,
	MODE_S3,
	MODE_TIERED,
)
from tradehub_core.media.pipeline.storage.mirror import inline_mirror  # noqa: E402
from tradehub_core.media.pipeline.storage.s3 import S3Config, S3Storage, boto3_available  # noqa: E402
from tradehub_core.media.pipeline.storage.tiered import TieredStorage  # noqa: E402
from tradehub_core.tests.test_storage_adapters import (  # noqa: E402
	Harness,
	LocalHarness,
	StorageContractMixin,
)

ENDPOINT: str = os.environ.get("MEDIA_ENGINE_S3_ENDPOINT_URL", "http://minio:9000")
ACCESS_KEY: str = os.environ.get("MEDIA_ENGINE_S3_ACCESS_KEY_ID", "minioadmin")
SECRET_KEY: str = os.environ.get("MEDIA_ENGINE_S3_SECRET_ACCESS_KEY", "minioadmin")
BUCKET: str = os.environ.get("MEDIA_ENGINE_S3_BUCKET", "istoc-medya-test")
REGION: str = os.environ.get("MEDIA_ENGINE_S3_REGION", "us-east-1")

#: MinIO yol-tarzı adresleme ister; `auto` sanal-host'a kayıp
#: `bucket.minio:9000` çözmeye çalışır ve DNS'te yoktur.
ADDRESSING: str = "path"


def minio_config(prefix: str) -> S3Config:
	"""Gerçek MinIO'ya bakan ayar. Her koşum kendi `prefix`ini kullanır."""
	return S3Config(
		enabled=True,
		bucket=BUCKET,
		region=REGION,
		endpoint_url=ENDPOINT,
		prefix=prefix,
		access_key_id=ACCESS_KEY,
		secret_access_key=SECRET_KEY,
		addressing_style=ADDRESSING,
	)


def raw_client(**kwargs: Any) -> Any:
	"""Ölçüm/temizlik için düz boto3 istemcisi (adaptörün dışında)."""
	import boto3
	from botocore.config import Config as BotoConfig

	conf: Dict[str, Any] = {"s3": {"addressing_style": ADDRESSING}}
	conf.update(kwargs)
	return boto3.client(
		"s3",
		endpoint_url=ENDPOINT,
		region_name=REGION,
		aws_access_key_id=ACCESS_KEY,
		aws_secret_access_key=SECRET_KEY,
		config=BotoConfig(**conf),
	)


def minio_reachable() -> Tuple[bool, str]:
	"""MinIO ayakta mı + bucket hazır mı. Sebebi de döner (skip mesajı)."""
	if not boto3_available():
		return False, "boto3 kurulu değil"
	try:
		from botocore.config import Config as BotoConfig  # noqa: F401

		istemci = raw_client(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})
		istemci.list_buckets()
		try:
			istemci.head_bucket(Bucket=BUCKET)
		except Exception:
			istemci.create_bucket(Bucket=BUCKET)
		return True, ""
	except Exception as hata:  # pragma: no cover - ortama bağlı
		return False, f"MinIO ulaşılamadı ({ENDPOINT}): {type(hata).__name__}"


MINIO_OK, MINIO_SKIP = minio_reachable()


def purge_prefix(prefix: str) -> int:
	"""Koşum sonrası bucket'ı temiz bırak. Silinen nesne sayısını döner."""
	if not MINIO_OK:
		return 0
	istemci = raw_client()
	silinen = 0
	sayfalayici = istemci.get_paginator("list_objects_v2")
	for sayfa in sayfalayici.paginate(Bucket=BUCKET, Prefix=prefix + "/"):
		anahtarlar = [{"Key": n["Key"]} for n in (sayfa.get("Contents") or [])]
		if anahtarlar:
			istemci.delete_objects(Bucket=BUCKET, Delete={"Objects": anahtarlar})
			silinen += len(anahtarlar)
	return silinen


# ── Gerçek-S3 koşum kurulumları ────────────────────────────────────────
#
# `Harness._s3()` TEK noktadan gerçek istemciye çevrilir; kip kurulumları
# (`_build`) sahte istemcili dosyadakiyle AYNI kalır. Böylece "aynı
# sözleşme, farklı arka uç" iddiası koddan okunabilir.


class MinioHarnessMixin:
	"""`_s3()`'ü gerçek MinIO'ya bağlar ve prefix'i koşuma özel yapar.

	`signer` bilinçli olarak verilmez: S3 kipinde `url_for(private)` gerçek
	`generate_presigned_url` yolundan geçsin diye. Sahte istemcili dosyada
	HMAC imzalayıcı veriliyordu ve presign yolu hiç koşmuyordu.
	"""

	def __init__(self, ad: str) -> None:
		self.prefix = f"t051/{ad}/{uuid.uuid4().hex[:8]}"
		super().__init__(ad)

	def _s3(self) -> S3Storage:
		return S3Storage(minio_config(self.prefix), signer=None)

	def teardown(self) -> None:
		purge_prefix(self.prefix)
		super().teardown()


class MinioS3Harness(MinioHarnessMixin, Harness):
	def _build(self):
		self.s3 = self._s3()
		return self.s3

	def corrupt(self, ref: ObjectRef, content: bytes) -> None:
		"""Aynı anahtara YANLIŞ sha256 metadata'sıyla nesne koy.

		İçerik-adresli API'den üretilemeyen durum; gerçek MinIO'da da
		alttan yazmak gerekir.
		"""
		raw_client().put_object(
			Bucket=BUCKET,
			Key=f"{self.prefix}/{ref.scope}/{ref.key.relative}",
			Body=content,
			Metadata={"sha256": content_hash(content)},
		)


class MinioMirrorHarness(MinioHarnessMixin, Harness):
	def _build(self):
		self.primary = self._local()
		self.secondary = self._s3()
		return inline_mirror(self.primary, self.secondary)

	def corrupt(self, ref: ObjectRef, content: bytes) -> None:
		LocalHarness.corrupt(self, ref, content)  # birincil = yerel disk

	def _disk_path(self, ref: ObjectRef) -> str:
		return LocalHarness._disk_path(self, ref)


class MinioTieredHarness(MinioHarnessMixin, Harness):
	def _build(self):
		self.hot = self._local()
		self.cold = self._s3()
		return TieredStorage(self.hot, self.cold, age_days=30, keep_scopes=(SCOPE_PUBLIC,))

	def corrupt(self, ref: ObjectRef, content: bytes) -> None:
		LocalHarness.corrupt(self, ref, content)  # sıcak katman = yerel disk

	def _disk_path(self, ref: ObjectRef) -> str:
		return LocalHarness._disk_path(self, ref)


MINIO_HARNESSES: Tuple[Tuple[str, Callable[[], Harness]], ...] = (
	(MODE_LOCAL, lambda: LocalHarness(MODE_LOCAL)),
	(MODE_S3, lambda: MinioS3Harness(MODE_S3)),
	(MODE_MIRROR, lambda: MinioMirrorHarness(MODE_MIRROR)),
	(MODE_TIERED, lambda: MinioTieredHarness(MODE_TIERED)),
)


@unittest.skipUnless(MINIO_OK, MINIO_SKIP)
class _MinioContractBase(StorageContractMixin):
	"""Sahte istemcili dosyadaki gövdenin AYNISI, gerçek MinIO ile."""


class PresignTtlUyarlamasi:
	"""BULGU B-01'in test tarafı: gerçek presigned URL SigV4 DEĞİL.

	Ortak sözleşme gövdesindeki `test_url_for_private_ttl_kelepcelenir`
	yalnız iki biçim tanıyor: HMAC imzalayıcının `iat`/`exp` çifti ve
	SigV4'ün `X-Amz-Expires`'ı. Sahte istemci ikincisini UYDURUYOR
	(`generate_presigned_url` elle `?X-Amz-Expires=` yazıyor), bu yüzden
	sahte koşumda test yeşil.

	Gerçek boto3 `signature_version` verilmediğinde ve endpoint tanınmayan
	bir host olduğunda **SigV2** üretiyor: `AWSAccessKeyId`, `Signature`,
	`Expires`. `Expires` MUTLAK epoch'tur, süre değil. Kelepçe UYGULANIYOR
	(ölçüldü: 10 günlük istek → `Expires - now = 86400`), ama ortak gövde
	onu okuyamadığı için TTL'i 0 sanıp düşüyor.

	Bu override kelepçeyi ÜÇ biçimde de doğrular. Ortak dosya
	DEĞİŞTİRİLMEDİ; s3.py `signature_version="s3v4"` ile düzeltildiğinde
	bu override gereksizleşir ve silinmelidir.
	"""

	def test_url_for_private_ttl_kelepcelenir(self) -> None:  # type: ignore[override]
		import urllib.parse

		ref = self.storage.put(b"ttl-kelepce", ".pdf", scope=SCOPE_PRIVATE).ref
		url = self.storage.url_for(ref, ttl_seconds=10 * 86400)
		params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
		if "X-Amz-Expires" in params:  # SigV4
			ttl = int(params["X-Amz-Expires"][0])
		elif "Expires" in params:  # SigV2 — mutlak epoch
			ttl = int(params["Expires"][0]) - int(time.time())
		else:  # HMAC imzalayıcı
			ttl = int(params["exp"][0]) - int(params["iat"][0])
		self.assertLessEqual(ttl, 86400, "TTL üst sınırı aşıldı (FR-113)")
		self.assertGreater(ttl, 0)


def _sinif(ad: str, fabrika: Callable[[], Harness]) -> type:
	tabanlar: Tuple[type, ...] = (_MinioContractBase, unittest.TestCase)
	if ad == MODE_S3:
		tabanlar = (PresignTtlUyarlamasi, _MinioContractBase, unittest.TestCase)
	return type(
		f"TestMinio{ad.capitalize()}StorageContract",
		tabanlar,
		{"HARNESS_FACTORY": staticmethod(fabrika)},
	)


for _ad, _fabrika in MINIO_HARNESSES:
	globals()[f"TestMinio{_ad.capitalize()}StorageContract"] = _sinif(_ad, _fabrika)


@unittest.skipUnless(MINIO_OK, MINIO_SKIP)
class TestMinioGercekDavranis(unittest.TestCase):
	"""Sahte istemcinin taklit ETMEDİĞİ, yalnız gerçek serviste görülenler."""

	def setUp(self) -> None:  # noqa: N802
		self.h = MinioS3Harness("gercek")
		self.storage = self.h.storage

	def tearDown(self) -> None:  # noqa: N802
		self.h.teardown()

	def test_presigned_url_gercekten_indirilebilir(self) -> None:
		"""İmzalı URL'i HTTP ile çek — imza MinIO tarafından DOĞRULANIR."""
		import urllib.request

		icerik = b"presigned-gercek-indirme"
		ref = self.storage.put(icerik, ".pdf", scope=SCOPE_PRIVATE).ref
		url = self.storage.url_for(ref, ttl_seconds=120)
		self.assertTrue(
			("X-Amz-Signature" in url) or ("Signature=" in url),
			f"URL imzasız döndü: {url}",
		)
		# Konteyner içinden `minio:9000` çözülür; imza host adına bağlıdır.
		with urllib.request.urlopen(url, timeout=10) as yanit:  # noqa: S310
			self.assertEqual(yanit.status, 200)
			self.assertEqual(yanit.read(), icerik)

	def test_presign_imza_surumu_sigv4(self) -> None:
		"""B-01 REGRESYONU — `s3.py` presign'i SigV4 üretmeli.

		`_client()` eskiden `signature_version` VERMİYORDU; tanınmayan bir
		endpoint (MinIO) için botocore eski `s3` imzalayıcısına (SigV2)
		düşüyordu. MinIO kabul ediyor, AWS S3'ün 2014 sonrası bölgeleri ETMİYOR
		— yani özel dosya teslimi AWS'de tamamen kırılırdı.

		B-01 DÜZELTİLDİ (2026-08-19): `s3.py::_client()` artık
		`signature_version="s3v4"` sabitliyor. Bu test o düzeltmeyi KORUR —
		geri alınırsa SigV2'ye düşer ve burası kırmızıya döner.
		"""
		import urllib.parse

		ref = self.storage.put(b"imza-surumu", ".pdf", scope=SCOPE_PRIVATE).ref
		params = urllib.parse.parse_qs(
			urllib.parse.urlparse(self.storage.url_for(ref, ttl_seconds=300)).query
		)
		self.assertEqual(
			params.get("X-Amz-Algorithm"), ["AWS4-HMAC-SHA256"],
			"SigV2'ye geri düşülmüş — B-01 regresyonu",
		)
		self.assertIn("X-Amz-Signature", params)
		self.assertNotIn("AWSAccessKeyId", params, "SigV2 parametresi görünüyor")

	def test_s3v4_enjekte_edilince_calisiyor(self) -> None:
		"""B-01'in düzeltmesi ÇALIŞIR: `signature_version="s3v4"` yeterli.

		Adaptörün kendi `client_factory` kancasından geçirilir; `s3.py`
		değiştirilmeden düzeltmenin işe yaradığı ölçülür.
		"""
		import urllib.parse
		import urllib.request

		import boto3
		from botocore.config import Config as BotoConfig

		def fabrika() -> Any:
			return boto3.client(
				"s3",
				endpoint_url=ENDPOINT,
				region_name=REGION,
				aws_access_key_id=ACCESS_KEY,
				aws_secret_access_key=SECRET_KEY,
				config=BotoConfig(signature_version="s3v4", s3={"addressing_style": ADDRESSING}),
			)

		icerik = b"s3v4-dogrulama"
		ref = self.storage.put(icerik, ".pdf", scope=SCOPE_PRIVATE).ref
		v4 = S3Storage(minio_config(self.h.prefix), client_factory=fabrika, signer=None)
		url = v4.url_for(ref, ttl_seconds=10 * 86400)
		params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
		self.assertIn("X-Amz-Signature", params)
		self.assertEqual(int(params["X-Amz-Expires"][0]), 86400, "kelepçe SigV4'te de uygulanır")
		with urllib.request.urlopen(url, timeout=10) as yanit:  # noqa: S310
			self.assertEqual(yanit.read(), icerik)

	def test_suresi_dolmus_imza_reddedilir(self) -> None:
		"""Süre dolduğunda MinIO 403 veriyor — imza gerçekten dayatılıyor.

		`url_for` TTL'i alt sınıra (60 sn) yükselttiği için burada ham
		istemci kullanılır; ölçülen şey servisin dayatması.
		"""
		import urllib.error
		import urllib.request

		ref = self.storage.put(b"suresi-dolan", ".pdf", scope=SCOPE_PRIVATE).ref
		anahtar = f"{self.h.prefix}/{ref.scope}/{ref.key.relative}"
		url = raw_client().generate_presigned_url(
			"get_object", Params={"Bucket": BUCKET, "Key": anahtar}, ExpiresIn=2
		)
		self.assertEqual(urllib.request.urlopen(url, timeout=10).status, 200)  # noqa: S310
		time.sleep(3)
		with self.assertRaises(urllib.error.HTTPError) as kutu:
			urllib.request.urlopen(url, timeout=10)  # noqa: S310
		self.assertEqual(kutu.exception.code, 403)

	def test_imzasiz_erisim_reddedilir(self) -> None:
		"""Bucket public değil: imzasız istek 403 alır."""
		import urllib.error
		import urllib.request

		ref = self.storage.put(b"imzasiz-erisim", ".pdf", scope=SCOPE_PRIVATE).ref
		duz = f"{ENDPOINT}/{BUCKET}/{self.h.prefix}/{ref.scope}/{ref.key.relative}"
		with self.assertRaises(urllib.error.HTTPError) as kutu:
			urllib.request.urlopen(duz, timeout=10)  # noqa: S310
		self.assertIn(kutu.exception.code, (403, 401))

	def test_metadata_sha256_gercekten_donuyor(self) -> None:
		"""`x-amz-meta-sha256` MinIO'da yaşıyor ve `stat()` onu okuyor."""
		icerik = b"metadata-tasima-testi"
		ref = self.storage.put(icerik, ".jpg").ref
		kunye = self.storage.stat(ref)
		self.assertEqual(kunye.content_hash, content_hash(icerik))
		self.assertFalse(kunye.extra["hash_unknown"])
		self.assertTrue(kunye.extra["etag"])

	def test_sayfalama_gercek_list_objects(self) -> None:
		"""Sayfalayıcı gerçek `list_objects_v2` ile de doğru anahtar üretir."""
		for i in range(12):
			self.storage.put(f"sayfalama-{i}".encode(), ".bin")
		anahtarlar = list(self.storage.iter_keys(scope=SCOPE_PUBLIC))
		self.assertEqual(len(anahtarlar), 12)
		self.assertTrue(all(k.shard == k.name[:2] for k in anahtarlar))


# ── Ölçüm koşumu ───────────────────────────────────────────────────────


PAYLOADS: Tuple[Tuple[str, int], ...] = (
	("1 KiB", 1024),
	("256 KiB", 256 * 1024),
	("4 MiB", 4 * 1024 * 1024),
)


def _payload(boyut: int, tohum: str) -> bytes:
	"""Sıkışmayan, ölçüme özel bayt dizisi (her koşumda benzersiz)."""
	tekrar = (tohum.encode() + os.urandom(64)) * (boyut // 64 + 1)
	return tekrar[:boyut]


def _olc(fn: Callable[[], Any]) -> Tuple[Any, float, Optional[BaseException]]:
	basla = time.perf_counter()
	try:
		sonuc = fn()
	except BaseException as hata:  # noqa: BLE001 - ölçüm; hata da veridir
		return None, (time.perf_counter() - basla) * 1000.0, hata
	return sonuc, (time.perf_counter() - basla) * 1000.0, None


class Olcum:
	"""Tek kipin ölçüm satırlarını toplar."""

	def __init__(self, kip: str) -> None:
		self.kip = kip
		self.satirlar: List[Dict[str, Any]] = []

	def kaydet(self, islem: str, boyut_adi: str, bayt: int, ms: float, sonuc: str) -> None:
		self.satirlar.append(
			{"kip": self.kip, "islem": islem, "boyut": boyut_adi, "bayt": bayt, "ms": ms, "sonuc": sonuc}
		)

	def calis(self, islem: str, boyut_adi: str, bayt: int, fn: Callable[[], Any], bicim=None) -> Any:
		deger, ms, hata = _olc(fn)
		if hata is not None:
			self.kaydet(islem, boyut_adi, bayt, ms, f"HATA {type(hata).__name__}: {hata}")
			return None
		self.kaydet(islem, boyut_adi, bayt, ms, bicim(deger) if bicim else "ok")
		return deger


def _kip_olc(ad: str, fabrika: Callable[[], Harness]) -> Olcum:
	"""Tek kipi tüm işlemler + tüm boyutlarla ölç."""
	o = Olcum(ad)
	h = fabrika()
	depo = h.storage
	try:
		for boyut_adi, boyut in PAYLOADS:
			icerik = _payload(boyut, f"{ad}-{boyut_adi}")
			ozet = content_hash(icerik)

			sonuc = o.calis(
				"put (ilk yazma)", boyut_adi, boyut, lambda: depo.put(icerik, ".bin"),
				lambda r: f"created={r.created}",
			)
			if sonuc is None:
				continue
			ref = sonuc.ref

			o.calis(
				"put (aynı içerik, dedup)", boyut_adi, boyut, lambda: depo.put(icerik, ".bin"),
				lambda r: f"created={r.created}",
			)
			o.calis("exists", boyut_adi, 0, lambda: depo.exists(ref), lambda r: f"{r}")
			o.calis(
				"stat", boyut_adi, 0, lambda: depo.stat(ref),
				lambda r: f"boyut={r.size_bytes} hash={'tam' if r.content_hash == ozet else 'FARKLI/BOŞ'}",
			)
			o.calis(
				"get", boyut_adi, boyut, lambda: depo.get(ref),
				lambda r: f"{len(r)} bayt, içerik {'aynı' if r == icerik else 'FARKLI'}",
			)
			o.calis(
				"url_for (public)", boyut_adi, 0, lambda: depo.url_for(ref),
				lambda r: ("imzasız düz URL" if r == ref.url else f"{r[:48]}…"),
			)

			gizli = o.calis(
				"put (private)", boyut_adi, boyut,
				lambda: depo.put(icerik, ".bin", scope=SCOPE_PRIVATE), lambda r: f"created={r.created}",
			)
			if gizli is not None:
				o.calis(
					"url_for (private, imzalı)", boyut_adi, 0,
					lambda: depo.url_for(gizli.ref, ttl_seconds=300),
					lambda r: ("İMZASIZ!" if r == gizli.ref.url else f"imzalı ({len(r)} krkt)"),
				)
				o.calis(
					"delete (private)", boyut_adi, 0, lambda: depo.delete(gizli.ref),
					lambda r: f"{r}",
				)

			o.calis(
				"move (public→private)", boyut_adi, boyut,
				lambda: depo.move(ref, SCOPE_PRIVATE), lambda r: f"anahtar korundu={r.key == ref.key}",
			)
			gizli_ref = ObjectRef(key=ref.key, scope=SCOPE_PRIVATE)
			o.calis("delete", boyut_adi, 0, lambda: depo.delete(gizli_ref), lambda r: f"silindi={r}")
			o.calis(
				"delete (tekrar, idempotens)", boyut_adi, 0,
				lambda: depo.delete(gizli_ref), lambda r: f"silindi={r}",
			)
			o.calis("exists (silinmiş)", boyut_adi, 0, lambda: depo.exists(gizli_ref), lambda r: f"{r}")

		# — kipe özgü ek ölçümler —
		if ad == MODE_MIRROR:
			icerik = _payload(256 * 1024, "ayna-ikincil")
			ref = depo.put(icerik, ".bin").ref
			depo.drain(5.0)
			o.calis(
				"ayna: ikincilde var mı", "256 KiB", 0,
				lambda: h.secondary.exists(ref), lambda r: f"{r} (sayaçlar={depo.counters()})",
			)
			o.calis(
				"ayna: reconcile", "-", 0, lambda: depo.reconcile(scope=SCOPE_PUBLIC),
				lambda r: f"tarandı={r['scanned']} eksik={r['missing']} kuyruğa={r['queued']}",
			)
		if ad == MODE_TIERED:
			icerik = _payload(256 * 1024, "katman-yaslandirma")
			ref = depo.put(icerik, ".bin").ref
			o.calis(
				"katman: demote (yaz→doğrula→sil)", "256 KiB", len(icerik),
				lambda: depo.demote(ref),
				lambda r: f"taşındı={r.moved} doğrulama={r.verify_mode} serbest={r.bytes_freed}B",
			)
			o.calis("katman: konum", "-", 0, lambda: depo.location(ref), lambda r: r)
			o.calis(
				"katman: soğuktan get", "256 KiB", len(icerik), lambda: depo.get(ref),
				lambda r: f"{len(r)} bayt, içerik {'aynı' if r == icerik else 'FARKLI'}",
			)
			o.calis("katman: promote", "256 KiB", 0, lambda: depo.promote(ref), lambda r: f"{r}")
			o.calis("katman: konum (promote sonrası)", "-", 0, lambda: depo.location(ref), lambda r: r)
	finally:
		kapat = getattr(depo, "close", None)
		if callable(kapat):
			kapat()
		h.teardown()
	return o


def _medyan_olc(ad: str, fabrika: Callable[[], Harness], *, tekrar: int = 5) -> List[Dict[str, Any]]:
	"""Isınmış ölçüm: her işlem `tekrar` kez, medyan/en düşük/en yüksek.

	Tek geçişli tablo İLK çağrının maliyetini de içeriyor — `S3Storage`
	istemciyi tembel kuruyor (`import boto3` + bağlantı), bu yüzden ilk
	`put` diğerlerinin 3-5 katı çıkıyor ve koşumdan koşuma 100 ms'den fazla
	oynuyor. Bu tablo o çarpıklığı ayırır: önce ısınma, sonra tekrarlar.

	Her tekrar BENZERSİZ içerik kullanır — aynı baytları tekrar yazmak
	içerik-adresli depoda dedup yoluna girer ve yazmayı ölçmez.
	"""
	import statistics

	h = fabrika()
	depo = h.storage
	olculen: Dict[str, List[float]] = {}
	try:
		# ısınma: istemci kurulumu + bağlantı bu çağrıda ödenir
		isinma = depo.put(_payload(1024, f"isinma-{ad}"), ".bin")
		depo.delete(isinma.ref)

		for i in range(tekrar):
			icerik = _payload(256 * 1024, f"{ad}-medyan-{i}")
			_, ms, _ = _olc(lambda: depo.put(icerik, ".bin"))
			olculen.setdefault("put 256 KiB", []).append(ms)
			ref = depo.put(icerik, ".bin").ref
			for islem, fn in (
				("get 256 KiB", lambda: depo.get(ref)),
				("exists", lambda: depo.exists(ref)),
				("stat", lambda: depo.stat(ref)),
			):
				_, ms, _ = _olc(fn)
				olculen.setdefault(islem, []).append(ms)
			_, ms, _ = _olc(lambda: depo.delete(ref))
			olculen.setdefault("delete", []).append(ms)

		return [
			{
				"kip": ad,
				"islem": islem,
				"medyan": statistics.median(v),
				"min": min(v),
				"max": max(v),
				"n": len(v),
			}
			for islem, v in olculen.items()
		]
	finally:
		kapat = getattr(depo, "close", None)
		if callable(kapat):
			kapat()
		h.teardown()


def _ayna_asenkron_olc() -> Olcum:
	"""Ayna kipini ÜRETİM kuyruğuyla (`ThreadMirrorQueue`) ölç.

	Yukarıdaki `mirror` tablosu `inline_mirror` kullanıyor — sözleşme
	testiyle aynı kurulum, ama S3 yazması `put()` içinde SENKRON. Modül
	dokümanının asıl iddiası bunun tersi: "yükleme yolu S3'e bağlanmaz".
	Bu ölçüm o iddiayı sınar: aynı bayt, aynı MinIO, tek fark kuyruk.
	"""
	from tradehub_core.media.pipeline.storage.mirror import MirrorStorage

	o = Olcum("mirror (ThreadMirrorQueue)")
	h = MinioMirrorHarness("mirror-async")
	# `_build` inline kuyruk kurdu; onu bırakıp aynı katmanlarla asenkron kur.
	h.storage.close()
	depo = MirrorStorage(h.primary, h.secondary)
	h.storage = depo
	try:
		for boyut_adi, boyut in PAYLOADS:
			icerik = _payload(boyut, f"ayna-async-{boyut_adi}")
			sonuc = o.calis(
				"put (çağıranın gördüğü süre)", boyut_adi, boyut,
				lambda: depo.put(icerik, ".bin"), lambda r: f"created={r.created}",
			)
			o.calis("drain (ayna kuyruğu boşalana kadar)", boyut_adi, boyut,
				lambda: depo.drain(30.0), lambda r: "kuyruk boş")
			if sonuc is not None:
				o.calis("ikincilde var mı (drain sonrası)", boyut_adi, 0,
					lambda: h.secondary.exists(sonuc.ref), lambda r: f"{r}")
		o.calis("ayna sayaçları", "-", 0, lambda: depo.counters(), lambda r: f"{r}")
	finally:
		depo.close()
		h.teardown()
	return o


def measure() -> int:
	"""Dört kipi ölç, markdown tablosu bas."""
	if not MINIO_OK:
		print(f"ATLANDI: {MINIO_SKIP}")
		return 2
	print(f"# T-051 ölçüm — endpoint={ENDPOINT} bucket={BUCKET} boto3=var\n")
	for ad, fabrika in MINIO_HARNESSES:
		o = _kip_olc(ad, fabrika)
		print(f"\n## kip: {ad}\n")
		print("| işlem | boyut | bayt | süre (ms) | sonuç |")
		print("|---|---|---:|---:|---|")
		for s in o.satirlar:
			print(f"| {s['islem']} | {s['boyut']} | {s['bayt']} | {s['ms']:.2f} | {s['sonuc']} |")
	o = _ayna_asenkron_olc()
	print(f"\n## kip: {o.kip}\n")
	print("| işlem | boyut | bayt | süre (ms) | sonuç |")
	print("|---|---|---:|---:|---|")
	for s in o.satirlar:
		print(f"| {s['islem']} | {s['boyut']} | {s['bayt']} | {s['ms']:.2f} | {s['sonuc']} |")

	print("\n## ısınmış ölçüm — 5 tekrar, medyan (ms)\n")
	print("| kip | işlem | medyan | en düşük | en yüksek | n |")
	print("|---|---|---:|---:|---:|---:|")
	for ad, fabrika in MINIO_HARNESSES:
		for r in _medyan_olc(ad, fabrika):
			print(
				f"| {r['kip']} | {r['islem']} | {r['medyan']:.2f} | "
				f"{r['min']:.2f} | {r['max']:.2f} | {r['n']} |"
			)
	return 0


def failure_probe() -> int:
	"""S3 KAPALIYKEN her kipin davranışı: fail-safe mi, fail-open mı.

	Ölçülen: birincil/yerel yazma hâlâ çalışıyor mu, hangi işlem istisna
	atıyor, istisna sözleşme hiyerarşisinden mi (`MediaEngineError`) yoksa
	ham `botocore` istisnası mı SIZIYOR, ve düşüş kaç saniye sürüyor.
	"""
	print(f"# T-051 hata yolu — endpoint={ENDPOINT} (servis KAPALI olmalı)\n")
	print("| kip | işlem | süre (ms) | sonuç |")
	print("|---|---|---:|---|")
	icerik = _payload(64 * 1024, "hata-yolu")

	for ad, fabrika in MINIO_HARNESSES:
		if ad == MODE_LOCAL:
			continue
		try:
			h = fabrika()
		except BaseException as hata:  # noqa: BLE001
			print(f"| {ad} | kurulum | - | HATA {type(hata).__name__}: {hata} |")
			continue
		depo = h.storage
		o = Olcum(ad)

		sonuc = o.calis("put", "64 KiB", len(icerik), lambda: depo.put(icerik, ".bin"),
			lambda r: f"created={r.created} (BİRİNCİL YAZMA GEÇTİ)")
		ref = sonuc.ref if sonuc is not None else None
		if ref is not None:
			if ad == MODE_MIRROR:
				o.calis("get (birincilden)", "64 KiB", len(icerik), lambda: depo.get(ref),
					lambda r: f"{len(r)} bayt")
				o.calis("ayna sayaçları", "-", 0, lambda: depo.counters(), lambda r: f"{r}")
				o.calis("düşen görevler", "-", 0, lambda: depo.failed_tasks()[:1],
					lambda r: f"{r[0]['reason'] if r else 'yok'}")
			o.calis("exists", "-", 0, lambda: depo.exists(ref), lambda r: f"{r}")
			o.calis("stat", "-", 0, lambda: depo.stat(ref), lambda r: f"boyut={r.size_bytes}")
			o.calis("delete", "-", 0, lambda: depo.delete(ref), lambda r: f"{r}")
		if ad == MODE_TIERED:
			ref2 = ObjectRef(key=depo.put(icerik, ".bin").ref.key, scope=SCOPE_PUBLIC)
			o.calis("demote (soğuk kapalı)", "64 KiB", len(icerik), lambda: depo.demote(ref2),
				lambda r: f"taşındı={r.moved} sebep={r.reason} (sıcak kopya duruyor)")
			o.calis("sıcak kopya hâlâ var mı", "-", 0, lambda: h.hot.exists(ref2), lambda r: f"{r}")

		for s in o.satirlar:
			hiyerarsi = ""
			if s["sonuc"].startswith("HATA "):
				hiyerarsi = " ← SÖZLEŞME DIŞI" if "StorageError" not in s["sonuc"] and "ObjectNotFound" not in s["sonuc"] else " ← sözleşme istisnası"
			print(f"| {ad} | {s['islem']} | {s['ms']:.1f} | {s['sonuc']}{hiyerarsi} |")
		kapat = getattr(depo, "close", None)
		if callable(kapat):
			kapat()
		try:
			h.teardown()
		except BaseException:  # noqa: BLE001, S110
			pass
	return 0


if __name__ == "__main__":
	if "--measure" in sys.argv:
		raise SystemExit(measure())
	if "--failure" in sys.argv:
		raise SystemExit(failure_probe())
	unittest.main(argv=[sys.argv[0], "-v"])
