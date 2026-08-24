"""FAZ 5 — Depolama adaptörleri: DÖRT KİP DE AYNI SÖZLEŞME TESTİNDEN GEÇER.

Test sözleşmeye bakar, uygulamaya değil. `ADAPTER_CASES` listesindeki her
kurulum (`local`, `s3`, `mirror`, `tiered`) aynı `StorageContractTests`
gövdesini koşar. Bir kip sözleşmeyi kırarsa yalnız o kipin testi düşer ve
hangi kip olduğu test adında görünür.

Çalıştırma (Pillow/ffmpeg/frappe/site/boto3 GEREKMEZ):

    python3 -m unittest discover -s /Users/ahmet/Desktop/istoc/tradehub_core/tests -v
    python3 -m unittest tests.test_storage_adapters -v

S3 kipi **sahte istemciyle** koşar (`FakeS3Client`). Sahte istemci gerçek S3
semantiğini taklit eder (404 kodu, `Metadata`, sayfalama, `copy_object`) ama
GERÇEK S3'e karşı ÖLÇÜLMEDİ — `boto3` yerelde kurulu değil, konteynerde var.
Bu testin kanıtladığı şey: adaptörün S3 istemcisiyle kurduğu sözleşme
tutarlıdır; kanıtlamadığı şey: AWS/MinIO'nun bu sözleşmeye uyduğu.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.contracts.errors import ObjectNotFound, StorageConflict, StorageError  # noqa: E402
from tradehub_core.media.pipeline.contracts.storage import (  # noqa: E402
	SCOPE_PRIVATE,
	SCOPE_PUBLIC,
	ObjectKey,
	ObjectRef,
	StorageAdapter,
	content_hash,
	key_for,
	key_from_url,
)
from tradehub_core.media.pipeline.delivery import signed as signed_urls  # noqa: E402
from tradehub_core.media.pipeline.storage import (  # noqa: E402
	MODE_LOCAL,
	MODE_MIRROR,
	MODE_S3,
	MODE_TIERED,
	StoragePlan,
	StorageSettings,
	build_storage,
)
from tradehub_core.media.pipeline.storage.local import TEMP_PREFIX, LocalDiskStorage  # noqa: E402
from tradehub_core.media.pipeline.storage.mirror import MirrorStorage, inline_mirror  # noqa: E402
from tradehub_core.media.pipeline.storage.s3 import S3Config, S3ObjectMissing, S3Storage  # noqa: E402
from tradehub_core.media.pipeline.storage.tiered import TieredStorage  # noqa: E402

SECRET = b"test-imzalama-anahtari-32-bayt!!"


# ── Sahte S3 istemcisi ──────────────────────────────────────────────────


class FakeS3Client:
	"""boto3 `s3` istemcisinin bu adaptörün kullandığı yüzeyi.

	Gerçek S3 davranışından taklit edilenler: olmayan anahtarda `404` kodlu
	istisna, `Metadata` sözlüğünün korunması, `list_objects_v2` sayfalaması,
	`copy_object`'in metadata'yı taşıması.
	"""

	def __init__(self, *, page_size: int = 2) -> None:
		self.objects: Dict[str, Dict[str, Any]] = {}
		self.page_size = page_size
		self.calls: List[str] = []

	# — yardımcı —
	def _al(self, key: str) -> Dict[str, Any]:
		nesne = self.objects.get(key)
		if nesne is None:
			raise S3ObjectMissing(key)
		return nesne

	def bozunmus_yaz(self, key: str, content: bytes, sha256: str) -> None:
		"""Testin bilinçli olarak yanlış içerik yerleştirmesi için."""
		self.objects[key] = {
			"Body": content,
			"Metadata": {"sha256": sha256},
			"ContentLength": len(content),
			"LastModified": time.time(),
			"ETag": "bozuk",
			"StorageClass": "STANDARD",
		}

	# — istemci yüzeyi —
	def put_object(
		self,
		*,
		Bucket: str,
		Key: str,
		Body: Any,
		Metadata: Dict[str, str],
		StorageClass: str = "STANDARD",
		**_kwargs: Any,
	) -> Dict[str, Any]:
		self.calls.append(f"put:{Key}")
		content = Body.read() if hasattr(Body, "read") else bytes(Body)
		self.objects[Key] = {
			"Body": content,
			"Metadata": dict(Metadata),
			"ContentLength": len(content),
			"LastModified": time.time(),
			"ETag": '"{}"'.format(Metadata.get("sha256", "")[:32]),
			"StorageClass": StorageClass,
		}
		return {"ETag": self.objects[Key]["ETag"]}

	def get_object(self, *, Bucket: str, Key: str) -> Dict[str, Any]:
		self.calls.append(f"get:{Key}")
		nesne = self._al(Key)
		return {"Body": io.BytesIO(nesne["Body"]), "Metadata": nesne["Metadata"]}

	def head_object(self, *, Bucket: str, Key: str) -> Dict[str, Any]:
		self.calls.append(f"head:{Key}")
		nesne = self._al(Key)
		return {k: v for k, v in nesne.items() if k != "Body"}

	def delete_object(self, *, Bucket: str, Key: str) -> Dict[str, Any]:
		self.calls.append(f"delete:{Key}")
		self.objects.pop(Key, None)
		return {}

	def copy_object(self, *, Bucket: str, Key: str, CopySource: Dict[str, str], MetadataDirective: str = "COPY") -> Dict[str, Any]:
		self.calls.append(f"copy:{Key}")
		kaynak = self._al(CopySource["Key"])
		self.objects[Key] = dict(kaynak)
		return {}

	def generate_presigned_url(self, op: str, *, Params: Dict[str, str], ExpiresIn: int) -> str:
		self.calls.append(f"presign:{Params['Key']}:{ExpiresIn}")
		return f"https://sahte-s3.local/{Params['Bucket']}/{Params['Key']}?X-Amz-Expires={ExpiresIn}"

	def get_paginator(self, ad: str) -> "FakeS3Paginator":
		return FakeS3Paginator(self, self.page_size)


class FakeS3Paginator:
	"""`list_objects_v2` sayfalayıcısı — küçük sayfa boyu ile sayfalama sınanır."""

	def __init__(self, client: FakeS3Client, page_size: int) -> None:
		self._client = client
		self._page_size = max(1, page_size)

	def paginate(self, *, Bucket: str, Prefix: str = ""):
		anahtarlar = sorted(k for k in self._client.objects if k.startswith(Prefix))
		for i in range(0, len(anahtarlar), self._page_size):
			dilim = anahtarlar[i : i + self._page_size]
			yield {"Contents": [{"Key": k, "Size": self._client.objects[k]["ContentLength"]} for k in dilim]}
		if not anahtarlar:
			yield {}


def s3_config(**kwargs: Any) -> S3Config:
	return S3Config(enabled=True, bucket="istoc-medya", prefix="media", **kwargs)


# ── Kurulum fabrikaları: dört kip ───────────────────────────────────────


class Harness:
	"""Tek bir depolama kipinin test kurulumu.

	`corrupt` sözleşme testinin ihtiyaç duyduğu tek arka-uca-özel yetenektir:
	"aynı anahtar, farklı içerik" durumu içerik-adresli bir API üzerinden
	ÜRETİLEMEZ (anahtar içerikten türer), dolayısıyla depoya alttan
	müdahale gerekir.
	"""

	def __init__(self, ad: str) -> None:
		self.ad = ad
		self.tmp = tempfile.mkdtemp(prefix=f"media-{ad}-")
		self.public_root = os.path.join(self.tmp, "public", "files")
		self.private_root = os.path.join(self.tmp, "private", "files")
		self.signer = signed_urls.HmacUrlSigner(SECRET)
		self.client = FakeS3Client()
		self.storage: StorageAdapter = self._build()

	def _local(self, *, fsync: bool = False) -> LocalDiskStorage:
		return LocalDiskStorage(self.public_root, self.private_root, signer=self.signer, fsync=fsync)

	def _s3(self) -> S3Storage:
		return S3Storage(s3_config(), client_factory=lambda: self.client, signer=self.signer)

	def _build(self) -> StorageAdapter:
		raise NotImplementedError

	def corrupt(self, ref: ObjectRef, content: bytes) -> None:
		raise NotImplementedError

	def teardown(self) -> None:
		shutil.rmtree(self.tmp, ignore_errors=True)


class LocalHarness(Harness):
	def _build(self) -> StorageAdapter:
		return self._local()

	def _disk_path(self, ref: ObjectRef) -> str:
		kok = self.public_root if ref.scope == SCOPE_PUBLIC else self.private_root
		return os.path.join(kok, ref.key.shard, ref.key.name)

	def corrupt(self, ref: ObjectRef, content: bytes) -> None:
		yol = self._disk_path(ref)
		os.makedirs(os.path.dirname(yol), exist_ok=True)
		with open(yol, "wb") as fh:
			fh.write(content)


class S3Harness(Harness):
	def _build(self) -> StorageAdapter:
		return self._s3()

	def corrupt(self, ref: ObjectRef, content: bytes) -> None:
		anahtar = f"media/{ref.scope}/{ref.key.relative}"
		self.client.bozunmus_yaz(anahtar, content, content_hash(content))


class MirrorHarness(Harness):
	def _build(self) -> StorageAdapter:
		self.primary = self._local()
		self.secondary = self._s3()
		return inline_mirror(self.primary, self.secondary)

	def corrupt(self, ref: ObjectRef, content: bytes) -> None:
		LocalHarness.corrupt(self, ref, content)  # birincil = yerel disk

	def _disk_path(self, ref: ObjectRef) -> str:
		return LocalHarness._disk_path(self, ref)


class TieredHarness(Harness):
	def _build(self) -> StorageAdapter:
		self.hot = self._local()
		self.cold = self._s3()
		return TieredStorage(self.hot, self.cold, age_days=30, keep_scopes=(SCOPE_PUBLIC,))

	def corrupt(self, ref: ObjectRef, content: bytes) -> None:
		LocalHarness.corrupt(self, ref, content)  # sıcak katman = yerel disk

	def _disk_path(self, ref: ObjectRef) -> str:
		return LocalHarness._disk_path(self, ref)


HARNESSES: Tuple[Tuple[str, Callable[[], Harness]], ...] = (
	(MODE_LOCAL, lambda: LocalHarness(MODE_LOCAL)),
	(MODE_S3, lambda: S3Harness(MODE_S3)),
	(MODE_MIRROR, lambda: MirrorHarness(MODE_MIRROR)),
	(MODE_TIERED, lambda: TieredHarness(MODE_TIERED)),
)


# ── Ortak sözleşme testleri ─────────────────────────────────────────────


class StorageContractMixin:
	"""Dört kipin de geçmesi gereken gövde. `HARNESS_FACTORY` alt sınıfta."""

	HARNESS_FACTORY: Callable[[], Harness]

	def setUp(self) -> None:  # noqa: N802 - unittest API
		self.h = type(self).HARNESS_FACTORY()
		self.storage: StorageAdapter = self.h.storage

	def tearDown(self) -> None:  # noqa: N802
		kapat = getattr(self.storage, "close", None)
		if callable(kapat):
			kapat()
		self.h.teardown()

	# — put —

	def test_put_iceri_adresli_ve_idempotent(self) -> None:
		icerik = b"idempotent-test-icerigi"
		ilk = self.storage.put(icerik, ".jpg")
		ikinci = self.storage.put(icerik, ".jpg")
		self.assertTrue(ilk.created)
		self.assertFalse(ikinci.created, "aynı içeriğin ikinci yazımı `created=False` olmalı")
		self.assertEqual(ilk.ref, ikinci.ref)
		self.assertEqual(ilk.ref.key, key_for(icerik, ".jpg"))
		self.assertEqual(ilk.stat.content_hash, content_hash(icerik))
		self.assertEqual(ilk.stat.size_bytes, len(icerik))

	def test_put_url_sozlesmeye_uyar(self) -> None:
		sonuc = self.storage.put(b"url-sozlesmesi", ".png")
		self.assertTrue(sonuc.ref.url.startswith("/files/"))
		key, scope = key_from_url(sonuc.ref.url)
		self.assertEqual(key, sonuc.ref.key)
		self.assertEqual(scope, SCOPE_PUBLIC)

	def test_put_private_kapsam_ayri_adres(self) -> None:
		icerik = b"ayni-icerik-iki-kapsam"
		acik = self.storage.put(icerik, ".jpg", scope=SCOPE_PUBLIC)
		gizli = self.storage.put(icerik, ".jpg", scope=SCOPE_PRIVATE)
		self.assertEqual(acik.ref.key, gizli.ref.key, "anahtar kapsamdan bağımsız")
		self.assertNotEqual(acik.ref.url, gizli.ref.url)
		self.assertTrue(gizli.ref.url.startswith("/private/files/"))

	def test_put_bilinmeyen_kapsam_reddedilir(self) -> None:
		with self.assertRaises(ValueError):
			self.storage.put(b"x", ".jpg", scope="gizli-gizli")

	def test_ayni_anahtar_farkli_icerik_catisir(self) -> None:
		icerik = b"catisma-testi"
		ref = ObjectRef(key=key_for(icerik, ".jpg"), scope=SCOPE_PUBLIC)
		self.h.corrupt(ref, b"tamamen-baska-baytlar")
		with self.assertRaises(StorageConflict):
			self.storage.put(icerik, ".jpg")

	# — get / exists / stat —

	def test_get_yazilan_baytlari_dondurur(self) -> None:
		icerik = b"\x00\x01\x02 ikili icerik \xff"
		ref = self.storage.put(icerik, ".bin").ref
		self.assertEqual(self.storage.get(ref), icerik)

	def test_olmayan_nesne_ObjectNotFound(self) -> None:
		ref = ObjectRef(key=key_for(b"hic-yazilmadi", ".jpg"), scope=SCOPE_PUBLIC)
		with self.assertRaises(ObjectNotFound):
			self.storage.get(ref)
		with self.assertRaises(ObjectNotFound):
			self.storage.stat(ref)
		self.assertFalse(self.storage.exists(ref))

	def test_exists_hata_atmaz(self) -> None:
		ref = self.storage.put(b"var-mi-testi", ".jpg").ref
		self.assertTrue(self.storage.exists(ref))
		yok = ObjectRef(key=key_for(b"yok", ".jpg"), scope=SCOPE_PRIVATE)
		self.assertFalse(self.storage.exists(yok))

	def test_stat_kunyesi(self) -> None:
		icerik = b"kunye-testi" * 32
		ref = self.storage.put(icerik, ".jpg").ref
		kunye = self.storage.stat(ref)
		self.assertEqual(kunye.size_bytes, len(icerik))
		self.assertEqual(kunye.content_hash, content_hash(icerik))
		self.assertGreater(kunye.modified_at, 0.0)

	# — delete —

	def test_delete_idempotent(self) -> None:
		ref = self.storage.put(b"silinecek", ".jpg").ref
		self.assertTrue(self.storage.delete(ref))
		self.assertFalse(self.storage.delete(ref), "olmayanı silmek hata değil, False")
		self.assertFalse(self.storage.exists(ref))

	# — move —

	def test_move_anahtari_korur(self) -> None:
		icerik = b"tasinacak-icerik"
		ref = self.storage.put(icerik, ".jpg", scope=SCOPE_PUBLIC).ref
		hedef = self.storage.move(ref, SCOPE_PRIVATE)
		self.assertEqual(hedef.key, ref.key, "shard ve ad KORUNUR")
		self.assertEqual(hedef.scope, SCOPE_PRIVATE)
		self.assertTrue(self.storage.exists(hedef))
		self.assertFalse(self.storage.exists(ref))
		self.assertEqual(self.storage.get(hedef), icerik)

	def test_move_olmayan_kaynak(self) -> None:
		ref = ObjectRef(key=key_for(b"tasinamaz", ".jpg"), scope=SCOPE_PUBLIC)
		with self.assertRaises(ObjectNotFound):
			self.storage.move(ref, SCOPE_PRIVATE)

	def test_move_ayni_icerik_hedefte_varsa_birlesir(self) -> None:
		icerik = b"birlesme-testi"
		acik = self.storage.put(icerik, ".jpg", scope=SCOPE_PUBLIC).ref
		gizli = self.storage.put(icerik, ".jpg", scope=SCOPE_PRIVATE).ref
		hedef = self.storage.move(acik, SCOPE_PRIVATE)
		self.assertEqual(hedef, gizli)
		self.assertTrue(self.storage.exists(gizli))
		self.assertFalse(self.storage.exists(acik), "kaynak tüketilir")

	def test_move_bilinmeyen_kapsam(self) -> None:
		ref = self.storage.put(b"kapsam-hatasi", ".jpg").ref
		with self.assertRaises(ValueError):
			self.storage.move(ref, "arsiv")

	# — iter_keys —

	def test_iter_keys_yazilanlari_dolasir(self) -> None:
		refler = [self.storage.put(f"icerik-{i}".encode(), ".jpg").ref for i in range(5)]
		bulunan = {k.relative for k in self.storage.iter_keys(scope=SCOPE_PUBLIC)}
		for ref in refler:
			self.assertIn(ref.key.relative, bulunan)

	def test_iter_keys_kapsam_ayirir(self) -> None:
		acik = self.storage.put(b"acik-nesne", ".jpg", scope=SCOPE_PUBLIC).ref
		gizli = self.storage.put(b"gizli-nesne", ".jpg", scope=SCOPE_PRIVATE).ref
		acik_liste = {k.relative for k in self.storage.iter_keys(scope=SCOPE_PUBLIC)}
		gizli_liste = {k.relative for k in self.storage.iter_keys(scope=SCOPE_PRIVATE)}
		self.assertIn(acik.key.relative, acik_liste)
		self.assertNotIn(acik.key.relative, gizli_liste)
		self.assertIn(gizli.key.relative, gizli_liste)

	def test_iter_keys_prefix_suzer(self) -> None:
		ref = self.storage.put(b"prefix-testi", ".jpg").ref
		esleyen = list(self.storage.iter_keys(scope=SCOPE_PUBLIC, prefix=ref.key.shard))
		self.assertIn(ref.key.relative, {k.relative for k in esleyen})
		eslemeyen = list(self.storage.iter_keys(scope=SCOPE_PUBLIC, prefix="zz-hicbir-sey"))
		self.assertEqual(eslemeyen, [])

	def test_iter_keys_tembeldir(self) -> None:
		"""Üreteç döndürür — çağrı anında tüm depoyu belleğe almaz."""
		self.storage.put(b"tembellik", ".jpg")
		akis = self.storage.iter_keys(scope=SCOPE_PUBLIC)
		self.assertTrue(hasattr(akis, "__next__"), "iter_keys üreteç/iteratör olmalı")

	# — url_for —

	def test_url_for_public_duz_url_ttl_yok_sayilir(self) -> None:
		ref = self.storage.put(b"public-url", ".jpg").ref
		self.assertEqual(self.storage.url_for(ref), ref.url)
		self.assertEqual(self.storage.url_for(ref, ttl_seconds=60), ref.url)

	def test_url_for_private_imzali_ve_farkli(self) -> None:
		ref = self.storage.put(b"private-url", ".pdf", scope=SCOPE_PRIVATE).ref
		url = self.storage.url_for(ref, ttl_seconds=300)
		self.assertNotEqual(url, ref.url, "private URL imzasız dönmemeli")
		self.assertIn("=", url, "imzalı URL sorgu parametresi taşır")

	def test_url_for_private_ttl_kelepcelenir(self) -> None:
		"""On günlük TTL isteği üst sınırı AŞMAZ (FR-113)."""
		ref = self.storage.put(b"ttl-kelepce", ".pdf", scope=SCOPE_PRIVATE).ref
		url = self.storage.url_for(ref, ttl_seconds=10 * 86400)
		params = signed_urls.parse_signed_params(url)
		if signed_urls.PARAM_EXPIRES in params:  # HMAC imzalayıcı yolu
			ttl = int(params[signed_urls.PARAM_EXPIRES]) - int(params[signed_urls.PARAM_ISSUED])
		else:  # S3 presigned yolu
			ttl = int(params.get("X-Amz-Expires", "0"))
		self.assertLessEqual(ttl, signed_urls.MAX_TTL_SECONDS)
		self.assertGreater(ttl, 0)


def _test_sinifi(ad: str, fabrika: Callable[[], Harness]) -> type:
	"""Her kip için ayrı `TestCase` sınıfı üret — düşen test kipini söyler."""
	return type(
		f"Test{ad.capitalize()}StorageContract",
		(StorageContractMixin, unittest.TestCase),
		{"HARNESS_FACTORY": staticmethod(fabrika)},
	)


for _ad, _fabrika in HARNESSES:
	globals()[f"Test{_ad.capitalize()}StorageContract"] = _test_sinifi(_ad, _fabrika)


# ── Kipe özgü davranışlar ───────────────────────────────────────────────


class TestLocalDiskDavranisi(unittest.TestCase):
	"""Yalnız yerel diskin garantileri: atomik yazma, yol geçişi, süpürme."""

	def setUp(self) -> None:  # noqa: N802
		self.h = LocalHarness("local-ozel")
		self.storage: LocalDiskStorage = self.h.storage  # type: ignore[assignment]

	def tearDown(self) -> None:  # noqa: N802
		self.h.teardown()

	def test_yazma_gecici_dosya_birakmaz(self) -> None:
		self.storage.put(b"atomik-yazma", ".jpg")
		kalinti = [
			ad
			for kok, _d, dosyalar in os.walk(self.h.tmp)
			for ad in dosyalar
			if ad.startswith(TEMP_PREFIX)
		]
		self.assertEqual(kalinti, [], "başarılı yazmadan sonra .tmp kalıntısı olmamalı")

	def test_yol_gecisi_reddedilir(self) -> None:
		"""`ObjectKey` doğrulaması yol geçişini durdurmaz; disk katmanı durdurur."""
		kotu = ObjectKey(shard="..", name="../../etc/passwd")
		ref = ObjectRef(key=kotu, scope=SCOPE_PUBLIC)
		with self.assertRaises(StorageError):
			self.storage.get(ref)
		self.assertFalse(self.storage.exists(ref), "exists yol geçişinde de hata atmaz")

	def test_symlink_ile_kok_disina_cikilamaz(self) -> None:
		"""İkinci savunma katmanı: ad deseninden GEÇEN ama kök dışına çözülen yol.

		`_SAFE_NAME` `../` gibi adları zaten reddediyor; bu test onun
		yakalayamayacağı durumu (shard dizininin kök dışına bakan bir
		sembolik bağ olması) `realpath` kontrolüne bırakıyor.
		"""
		disarisi = os.path.join(self.h.tmp, "kok-disi")
		os.makedirs(disarisi, exist_ok=True)
		os.makedirs(self.h.public_root, exist_ok=True)
		bag = os.path.join(self.h.public_root, "ab")
		os.symlink(disarisi, bag)
		with open(os.path.join(disarisi, "abcdef.jpg"), "wb") as fh:
			fh.write(b"kok disindaki dosya")
		ref = ObjectRef(key=ObjectKey(shard="ab", name="abcdef.jpg"), scope=SCOPE_PUBLIC)
		with self.assertRaises(StorageError):
			self.storage.get(ref)
		self.assertFalse(self.storage.exists(ref))

	def test_sweep_temp_files_kalintiyi_temizler(self) -> None:
		shard_dizin = os.path.join(self.h.public_root, "ab")
		os.makedirs(shard_dizin, exist_ok=True)
		kalinti = os.path.join(shard_dizin, f"{TEMP_PREFIX}olu.part")
		with open(kalinti, "wb") as fh:
			fh.write(b"yarim yazilmis")
		eski = time.time() - 7200
		os.utime(kalinti, (eski, eski))
		sonuc = self.storage.sweep_temp_files(older_than_seconds=3600)
		self.assertEqual(sonuc["deleted"], 1)
		self.assertFalse(os.path.exists(kalinti))

	def test_sweep_temp_files_taze_dosyaya_dokunmaz(self) -> None:
		shard_dizin = os.path.join(self.h.public_root, "cd")
		os.makedirs(shard_dizin, exist_ok=True)
		taze = os.path.join(shard_dizin, f"{TEMP_PREFIX}calisan.part")
		with open(taze, "wb") as fh:
			fh.write(b"su an yaziliyor")
		sonuc = self.storage.sweep_temp_files(older_than_seconds=3600)
		self.assertEqual(sonuc["deleted"], 0)
		self.assertTrue(os.path.exists(taze))

	def test_iter_keys_gecici_dosyayi_saymaz(self) -> None:
		ref = self.storage.put(b"gercek-nesne", ".jpg").ref
		shard_dizin = os.path.join(self.h.public_root, ref.key.shard)
		with open(os.path.join(shard_dizin, f"{TEMP_PREFIX}yarim.part"), "wb") as fh:
			fh.write(b"yarim")
		adlar = {k.name for k in self.storage.iter_keys(scope=SCOPE_PUBLIC)}
		self.assertEqual(adlar, {ref.key.name})

	def test_imzalayicisiz_private_url_hata(self) -> None:
		depo = LocalDiskStorage(self.h.public_root, self.h.private_root, signer=None, fsync=False)
		ref = depo.put(b"imzasiz", ".pdf", scope=SCOPE_PRIVATE).ref
		with self.assertRaises(StorageError):
			depo.url_for(ref)
		# Public tarafta imzalayıcı gerekmez.
		acik = depo.put(b"imzasiz-public", ".jpg").ref
		self.assertEqual(depo.url_for(acik), acik.url)

	def test_stat_fast_hash_hesaplamaz_ve_isaretler(self) -> None:
		ref = self.storage.put(b"hizli-kunye", ".jpg").ref
		hizli = self.storage.stat_fast(ref)
		self.assertTrue(hizli.extra.get("hash_truncated"))
		self.assertEqual(len(hizli.content_hash), 32)
		self.assertTrue(content_hash(b"hizli-kunye").startswith(hizli.content_hash))

	def test_usage_bytes_toplami(self) -> None:
		self.storage.put(b"a" * 100, ".jpg")
		self.storage.put(b"b" * 250, ".jpg", scope=SCOPE_PRIVATE)
		self.assertEqual(self.storage.usage_bytes(scope=SCOPE_PUBLIC), 100)
		self.assertEqual(self.storage.usage_bytes(), 350)


class TestS3Davranisi(unittest.TestCase):
	"""S3 adaptörünün kendine özgü kuralları."""

	def setUp(self) -> None:  # noqa: N802
		self.h = S3Harness("s3-ozel")
		self.storage: S3Storage = self.h.storage  # type: ignore[assignment]

	def tearDown(self) -> None:  # noqa: N802
		self.h.teardown()

	def test_s3_kapaliyken_kurulamaz(self) -> None:
		with self.assertRaises(StorageError):
			S3Storage(S3Config(enabled=False, bucket="x"), client_factory=lambda: FakeS3Client())

	def test_bucket_yoksa_kurulamaz(self) -> None:
		with self.assertRaises(StorageError):
			S3Storage(S3Config(enabled=True, bucket=""), client_factory=lambda: FakeS3Client())

	def test_anahtar_kapsam_onekli(self) -> None:
		ref = self.storage.put(b"anahtar-yerlesimi", ".jpg").ref
		self.assertEqual(
			self.storage.object_key(ref), f"media/public/{ref.key.shard}/{ref.key.name}"
		)

	def test_sha256_metadataya_yazilir(self) -> None:
		icerik = b"metadata-testi"
		ref = self.storage.put(icerik, ".jpg").ref
		nesne = self.h.client.objects[self.storage.object_key(ref)]
		self.assertEqual(nesne["Metadata"]["sha256"], content_hash(icerik))

	def test_metadatasiz_nesnede_hash_unknown(self) -> None:
		icerik = b"eski-nesne"
		ref = ObjectRef(key=key_for(icerik, ".jpg"), scope=SCOPE_PUBLIC)
		anahtar = self.storage.object_key(ref)
		self.h.client.objects[anahtar] = {
			"Body": icerik,
			"Metadata": {},
			"ContentLength": len(icerik),
			"LastModified": time.time(),
			"ETag": '"x"',
			"StorageClass": "STANDARD",
		}
		kunye = self.storage.stat(ref)
		self.assertEqual(kunye.content_hash, "", "uydurma hash üretilmez")
		self.assertTrue(kunye.extra["hash_unknown"])

	def test_sayfalama_tum_anahtarlari_dondurur(self) -> None:
		beklenen = {self.storage.put(f"sayfa-{i}".encode(), ".jpg").ref.key.relative for i in range(7)}
		bulunan = {k.relative for k in self.storage.iter_keys(scope=SCOPE_PUBLIC)}
		self.assertEqual(beklenen, bulunan)

	def test_presigned_ttl_kelepcelenir(self) -> None:
		depo = S3Storage(s3_config(), client_factory=lambda: self.h.client, signer=None)
		ref = depo.put(b"presign", ".pdf", scope=SCOPE_PRIVATE).ref
		url = depo.url_for(ref, ttl_seconds=999999)
		self.assertIn(f"X-Amz-Expires={signed_urls.MAX_TTL_SECONDS}", url)

	def test_public_base_url_cdn_onekini_ekler(self) -> None:
		depo = S3Storage(
			s3_config(public_base_url="https://cdn.istoc.local"),
			client_factory=lambda: self.h.client,
		)
		ref = depo.put(b"cdn", ".jpg").ref
		self.assertEqual(depo.url_for(ref), f"https://cdn.istoc.local{ref.url}")


class TestMirrorDavranisi(unittest.TestCase):
	"""Ayna: ikincil hiçbir koşulda birincili düşürmez."""

	def setUp(self) -> None:  # noqa: N802
		self.h = MirrorHarness("mirror-ozel")
		self.storage: MirrorStorage = self.h.storage  # type: ignore[assignment]

	def tearDown(self) -> None:  # noqa: N802
		self.h.teardown()

	def test_put_ikincile_de_yazar(self) -> None:
		ref = self.storage.put(b"aynalanacak", ".jpg").ref
		self.assertTrue(self.h.primary.exists(ref))
		self.assertTrue(self.h.secondary.exists(ref))

	def test_ikincil_patlarsa_birincil_ayakta(self) -> None:
		class PatlayanIkincil:
			def put(self, *a: Any, **k: Any) -> Any:
				raise StorageError("ikincil çöktü")

			def exists(self, *a: Any, **k: Any) -> bool:
				return False

			def delete(self, *a: Any, **k: Any) -> bool:
				raise StorageError("ikincil çöktü")

			def move(self, *a: Any, **k: Any) -> Any:
				raise StorageError("ikincil çöktü")

			def get(self, *a: Any, **k: Any) -> bytes:
				raise ObjectNotFound("yok")

			def stat(self, *a: Any, **k: Any) -> Any:
				raise ObjectNotFound("yok")

			def iter_keys(self, **k: Any):
				return iter(())

			def url_for(self, *a: Any, **k: Any) -> str:
				raise StorageError("ikincil çöktü")

		ayna = inline_mirror(self.h.primary, PatlayanIkincil())
		sonuc = ayna.put(b"ikincil-coktu", ".jpg")
		self.assertTrue(sonuc.created, "birincil yazma başarılı olmalı")
		self.assertEqual(ayna.get(sonuc.ref), b"ikincil-coktu")
		self.assertGreaterEqual(ayna.counters().get("failed", 0), 1, "hata sayaca yazılmalı")
		self.assertTrue(ayna.failed_tasks(), "düşen görev görünür olmalı")

	def test_okuma_yedegi_ve_onarim(self) -> None:
		ref = self.storage.put(b"okuma-yedegi", ".jpg").ref
		self.h.primary.delete(ref)  # birincilden düştü
		self.assertEqual(self.storage.get(ref), b"okuma-yedegi")
		self.assertTrue(self.h.primary.exists(ref), "read-repair birincile geri yazmalı")

	def test_reconcile_eksikleri_kuyruga_alir(self) -> None:
		ref = self.storage.put(b"uzlastirma", ".jpg").ref
		self.h.secondary.delete(ref)
		rapor = self.storage.reconcile(scope=SCOPE_PUBLIC)
		self.assertEqual(rapor["missing"], 1)
		self.assertEqual(rapor["queued"], 1)
		self.assertTrue(self.h.secondary.exists(ref), "inline kuyruk hemen telafi eder")


class TestTieredDavranisi(unittest.TestCase):
	"""Katmanlı depo: yaz → DOĞRULA → sıcaktan sil."""

	def setUp(self) -> None:  # noqa: N802
		self.h = TieredHarness("tiered-ozel")
		self.storage: TieredStorage = self.h.storage  # type: ignore[assignment]

	def tearDown(self) -> None:  # noqa: N802
		self.h.teardown()

	def _yaslandir(self, ref: ObjectRef, gun: float) -> None:
		yol = self.h._disk_path(ref)
		eski = time.time() - gun * 86400
		os.utime(yol, (eski, eski))

	def test_yeni_dosya_sicakta_kalir(self) -> None:
		ref = self.storage.put(b"yeni-dosya", ".jpg").ref
		self.assertEqual(self.storage.location(ref), "hot")
		self.assertFalse(self.storage.is_eligible(ref))

	def test_yaslanan_dosya_sogugua_yaslanir(self) -> None:
		ref = self.storage.put(b"yaslanan-dosya", ".jpg").ref
		self._yaslandir(ref, 100)
		self.assertTrue(self.storage.is_eligible(ref))
		sonuc = self.storage.demote(ref, dry_run=False)
		self.assertTrue(sonuc.moved)
		self.assertTrue(sonuc.verified)
		self.assertEqual(sonuc.verify_mode, "hash")
		self.assertEqual(self.storage.location(ref), "cold")
		self.assertEqual(self.storage.get(ref), b"yaslanan-dosya", "okuma yedeği soğuktan okur")

	def test_dogrulama_basarisizsa_sicak_kopya_durur(self) -> None:
		ref = self.storage.put(b"dogrulanamaz", ".jpg").ref
		self._yaslandir(ref, 100)

		class BozukSoguk:
			def __init__(self, gercek: Any) -> None:
				self._g = gercek

			def put(self, icerik: bytes, uzanti: str, *, scope: str = SCOPE_PUBLIC) -> Any:
				return self._g.put(icerik, uzanti, scope=scope)

			def stat(self, r: ObjectRef) -> Any:
				kunye = self._g.stat(r)
				return type(kunye)(
					size_bytes=kunye.size_bytes,
					content_hash="0" * 64,  # yanlış hash
					modified_at=kunye.modified_at,
					extra=dict(kunye.extra),
				)

			def __getattr__(self, ad: str) -> Any:
				return getattr(self._g, ad)

		katmanli = TieredStorage(self.h.hot, BozukSoguk(self.h.cold), age_days=30)
		sonuc = katmanli.demote(ref, dry_run=False)
		self.assertFalse(sonuc.moved)
		self.assertFalse(sonuc.verified)
		self.assertTrue(self.h.hot.exists(ref), "doğrulanamayan yaslandırmada sıcak kopya SİLİNMEZ")

	def test_sweep_varsayilan_kuru_kosum(self) -> None:
		ref = self.storage.put(b"kuru-kosum", ".jpg").ref
		self._yaslandir(ref, 200)
		rapor = self.storage.sweep()  # varsayılan dry_run=True
		self.assertTrue(rapor.dry_run)
		self.assertEqual(rapor.eligible, 1)
		self.assertEqual(rapor.demoted, 0)
		self.assertTrue(self.h.hot.exists(ref), "kuru koşum hiçbir şeye dokunmaz")

	def test_sweep_private_kapsama_dokunmaz(self) -> None:
		ref = self.storage.put(b"private-yaslanmaz", ".pdf", scope=SCOPE_PRIVATE).ref
		self._yaslandir(ref, 500)
		rapor = self.storage.sweep(scope=SCOPE_PRIVATE, dry_run=False)
		self.assertEqual(rapor.eligible, 0)
		self.assertTrue(self.h.hot.exists(ref), "private varsayılan olarak yaslanmaz (KVKK)")

	def test_promote_geri_getirir(self) -> None:
		ref = self.storage.put(b"geri-gelen", ".jpg").ref
		self._yaslandir(ref, 100)
		self.storage.demote(ref, dry_run=False)
		self.assertTrue(self.storage.promote(ref))
		self.assertEqual(self.storage.location(ref), "both", "soğuk kopya silinmez")

	def test_delete_iki_katmandan_da_siler(self) -> None:
		ref = self.storage.put(b"kvkk-silme", ".jpg").ref
		self._yaslandir(ref, 100)
		self.storage.demote(ref, dry_run=False)
		self.h.hot.put(b"kvkk-silme", ".jpg")  # iki katmanda da var
		self.assertTrue(self.storage.delete(ref))
		self.assertEqual(self.storage.location(ref), "missing")


# ── Fabrika (T-055) ─────────────────────────────────────────────────────


class TestStorageFactory(unittest.TestCase):
	"""Fabrika: sessiz düşüş YOK."""

	def setUp(self) -> None:  # noqa: N802
		self.tmp = tempfile.mkdtemp(prefix="media-factory-")
		self.settings = StorageSettings(
			public_root=os.path.join(self.tmp, "public", "files"),
			private_root=os.path.join(self.tmp, "private", "files"),
			signing_secret="fabrika-test-anahtari",
			fsync=False,
		)

	def tearDown(self) -> None:  # noqa: N802
		shutil.rmtree(self.tmp, ignore_errors=True)

	def _plan(self, **kwargs: Any) -> StoragePlan:
		return build_storage(StorageSettings(**{**self.settings.__dict__, **kwargs}))

	def test_local_kip(self) -> None:
		plan = self._plan(mode=MODE_LOCAL)
		self.assertEqual(plan.mode, MODE_LOCAL)
		self.assertFalse(plan.degraded)
		self.assertIsInstance(plan.adapter, LocalDiskStorage)

	def test_s3_kapaliyken_locale_duser_ve_raporlar(self) -> None:
		for kip in (MODE_S3, MODE_MIRROR, MODE_TIERED):
			with self.subTest(kip=kip):
				plan = self._plan(mode=kip)
				self.assertEqual(plan.mode, MODE_LOCAL)
				self.assertTrue(plan.degraded)
				self.assertEqual(plan.downgraded_from, kip)
				self.assertIn("s3_enabled=0", plan.reasons)
				self.assertIsInstance(plan.adapter, LocalDiskStorage)

	def test_s3_acik_bucket_yoksa_duser(self) -> None:
		plan = build_storage(
			StorageSettings(
				**{**self.settings.__dict__, "mode": MODE_MIRROR, "s3": S3Config(enabled=True, bucket="")}
			),
			s3_client_factory=lambda: FakeS3Client(),
		)
		self.assertEqual(plan.mode, MODE_LOCAL)
		self.assertIn("s3_bucket boş", plan.reasons)

	def test_mirror_kurulur(self) -> None:
		plan = build_storage(
			StorageSettings(**{**self.settings.__dict__, "mode": MODE_MIRROR, "s3": s3_config()}),
			s3_client_factory=lambda: FakeS3Client(),
			queue_factory=lambda worker: __import__(
				"tradehub_core.media.pipeline.storage.mirror", fromlist=["InlineMirrorQueue"]
			).InlineMirrorQueue(worker),
		)
		self.assertEqual(plan.mode, MODE_MIRROR)
		self.assertFalse(plan.degraded)
		self.assertIsInstance(plan.adapter, MirrorStorage)

	def test_tiered_kurulur(self) -> None:
		plan = build_storage(
			StorageSettings(
				**{**self.settings.__dict__, "mode": MODE_TIERED, "s3": s3_config(), "tier_age_days": 45}
			),
			s3_client_factory=lambda: FakeS3Client(),
		)
		self.assertEqual(plan.mode, MODE_TIERED)
		self.assertIsInstance(plan.adapter, TieredStorage)
		self.assertEqual(plan.adapter.age_days, 45)

	def test_s3_kipi_kurulur(self) -> None:
		plan = build_storage(
			StorageSettings(**{**self.settings.__dict__, "mode": MODE_S3, "s3": s3_config()}),
			s3_client_factory=lambda: FakeS3Client(),
		)
		self.assertEqual(plan.mode, MODE_S3)
		self.assertIsInstance(plan.adapter, S3Storage)

	def test_imzalayici_yoksa_sebep_yazilir(self) -> None:
		ortam = os.environ.pop("MEDIA_ENGINE_SIGNING_KEY", None)
		try:
			plan = build_storage(
				StorageSettings(
					public_root=self.settings.public_root,
					private_root=self.settings.private_root,
					signing_secret="",
					fsync=False,
				)
			)
		finally:
			if ortam is not None:
				os.environ["MEDIA_ENGINE_SIGNING_KEY"] = ortam
		if signed_urls.UPSTREAM_AVAILABLE:  # bench içinde frappe imzalayıcısı bulunur
			self.assertTrue(plan.signer_available)
		else:
			self.assertFalse(plan.signer_available)
			self.assertTrue(any(s.startswith("no_signer") for s in plan.reasons))

	def test_bilinmeyen_kip_locale_duser(self) -> None:
		plan = self._plan(mode="kuantum-depo")
		self.assertEqual(plan.mode, MODE_LOCAL)
		self.assertEqual(plan.requested_mode, MODE_LOCAL)

	def test_kok_cozulemezse_hata(self) -> None:
		with self.assertRaises(StorageError):
			build_storage(StorageSettings(mode=MODE_LOCAL))

	def test_from_mapping_site_config_deseni(self) -> None:
		ayar = StorageSettings.from_mapping(
			{
				"media_storage_mode": "tiered",
				"media_site_path": self.tmp,
				"s3_enabled": 1,
				"s3_bucket": "kova",
				"media_tier_age_days": 120,
			}
		)
		self.assertEqual(ayar.mode, MODE_TIERED)
		self.assertTrue(ayar.s3.enabled)
		self.assertEqual(ayar.s3.bucket, "kova")
		self.assertEqual(ayar.tier_age_days, 120)
		self.assertEqual(ayar.roots()[0], os.path.join(self.tmp, "public", "files"))

	def test_from_doctype_alan_adlari(self) -> None:
		ayar = StorageSettings.from_doctype(
			{
				"backend": "mirror",
				"s3_bucket": "kova",
				"s3_endpoint": "https://s3.local",
				"s3_access_key": "ak",
				"s3_secret_key": "sk",
				"cdn_base_url": "https://cdn.istoc.local/",
				"signed_url_ttl_seconds": 600,
			},
			site_path=self.tmp,
		)
		self.assertEqual(ayar.mode, MODE_MIRROR)
		self.assertTrue(ayar.s3.enabled)
		self.assertEqual(ayar.s3.endpoint_url, "https://s3.local")
		self.assertEqual(ayar.s3.public_base_url, "https://cdn.istoc.local")
		self.assertEqual(ayar.signed_url_ttl_seconds, 600)

	def test_from_doctype_local_s3yi_kapatir(self) -> None:
		ayar = StorageSettings.from_doctype({"backend": "local", "s3_bucket": "kova"})
		self.assertFalse(ayar.s3.enabled)


# ── İmzalı URL (T-052) ──────────────────────────────────────────────────


class TestSignedUrl(unittest.TestCase):
	"""HMAC imzalı URL: TTL kelepçesi iki yerde, sabit-zamanlı karşılaştırma."""

	def setUp(self) -> None:  # noqa: N802
		self.signer = signed_urls.HmacUrlSigner(SECRET)

	def test_imzala_ve_dogrula(self) -> None:
		imzali = self.signer.sign("/private/files/ab/abc.pdf", ttl_seconds=300)
		karar = self.signer.verify(imzali.url)
		self.assertTrue(karar)
		self.assertEqual(karar.reason, signed_urls.REASON_OK)
		self.assertEqual(karar.path, "/private/files/ab/abc.pdf")
		self.assertEqual(imzali.ttl_seconds, 300)

	def test_public_yol_imzalanmaz(self) -> None:
		with self.assertRaises(signed_urls.SignedUrlError):
			self.signer.sign("/files/ab/abc.jpg")

	def test_yol_gecisi_imzalanmaz(self) -> None:
		with self.assertRaises(signed_urls.SignedUrlError):
			self.signer.sign("/private/files/../../site_config.json")

	def test_ttl_kelepcesi_imzalamada(self) -> None:
		uzun = self.signer.sign("/private/files/ab/abc.pdf", ttl_seconds=10**9)
		self.assertEqual(uzun.ttl_seconds, signed_urls.MAX_TTL_SECONDS)
		kisa = self.signer.sign("/private/files/ab/abc.pdf", ttl_seconds=1)
		self.assertEqual(kisa.ttl_seconds, signed_urls.MIN_TTL_SECONDS)

	def test_ttl_kelepcesi_dogrulamada_da_var(self) -> None:
		"""İmzalayıcı ele geçse bile doğrulayıcı uzun TTL'i reddeder."""
		sahte = signed_urls.HmacUrlSigner(SECRET, max_ttl=10**9)
		uzun = sahte.sign("/private/files/ab/abc.pdf", ttl_seconds=10**8)
		karar = self.signer.verify(uzun.url)  # normal kelepçeli doğrulayıcı
		self.assertFalse(karar)
		self.assertEqual(karar.reason, signed_urls.REASON_TTL_EXCEEDED)

	def test_kurcalanan_imza_reddedilir(self) -> None:
		imzali = self.signer.sign("/private/files/ab/abc.pdf")
		bozuk = imzali.url.replace(imzali.signature, "0" * len(imzali.signature))
		karar = self.signer.verify(bozuk)
		self.assertFalse(karar)
		self.assertEqual(karar.reason, signed_urls.REASON_INVALID_SIGNATURE)

	def test_kurcalanan_yol_reddedilir(self) -> None:
		imzali = self.signer.sign("/private/files/ab/abc.pdf")
		bozuk = imzali.url.replace("abc.pdf", "baskasi.pdf")
		self.assertFalse(self.signer.verify(bozuk))

	def test_suresi_gecen_reddedilir(self) -> None:
		imzali = self.signer.sign("/private/files/ab/abc.pdf", ttl_seconds=60)
		karar = self.signer.verify(imzali.url, now=imzali.expires_at + 1)
		self.assertFalse(karar)
		self.assertEqual(karar.reason, signed_urls.REASON_EXPIRED)

	def test_imzasiz_ve_bozuk_girdi_istisna_atmaz(self) -> None:
		for girdi in ("", "cop", "/private/files/ab/abc.pdf", "?exp=1&sig="):
			with self.subTest(girdi=girdi):
				karar = self.signer.verify(girdi)
				self.assertFalse(karar)
				self.assertIsInstance(karar.reason, str)

	def test_baska_anahtar_dogrulayamaz(self) -> None:
		digeri = signed_urls.HmacUrlSigner(b"tamamen-baska-bir-anahtar-32bayt")
		imzali = self.signer.sign("/private/files/ab/abc.pdf")
		self.assertFalse(digeri.verify(imzali.url))

	def test_bos_anahtar_reddedilir(self) -> None:
		with self.assertRaises(signed_urls.SignedUrlError):
			signed_urls.HmacUrlSigner(b"")

	def test_default_signer_anahtarsiz_rastgele_uretmez(self) -> None:
		ortam = os.environ.pop("MEDIA_ENGINE_SIGNING_KEY", None)
		try:
			if signed_urls.UPSTREAM_AVAILABLE:
				self.assertIsInstance(signed_urls.default_signer(), signed_urls.FrappeSignedUrl)
			else:
				with self.assertRaises(signed_urls.SignedUrlError):
					signed_urls.default_signer()
		finally:
			if ortam is not None:
				os.environ["MEDIA_ENGINE_SIGNING_KEY"] = ortam

	def test_ttl_sabitleri_uretimle_ayrismamis(self) -> None:
		"""`media_access.py` ile ayna değerleri aynı mı — frappe yoksa ATLANIR."""
		sonuc = signed_urls.verify_ttl_contract()
		if not sonuc["available"]:
			self.skipTest("frappe yok: üretim TTL sabitleri okunamıyor (sahte 'geçti' verilmez)")
		self.assertTrue(sonuc["matches"], f"TTL sabitleri ayrıştı: {sonuc}")


if __name__ == "__main__":  # pragma: no cover
	unittest.main(verbosity=2)
