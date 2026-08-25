"""T-055 — Faz 5 kapanış: depolama kabul testleri.

Şartname: docs/42-faz5-depolama-s3-cdn.html · T-055 — "Faz 5 kabul testlerini
yaz ve koştur: tests/acceptance/test_storage_acceptance.py". Senaryolar dört
depolama kipini (local · s3 · mirror · tiered) kapsar.

BU DOSYANIN DÜRÜSTLÜK SÖZLEŞMESİ
--------------------------------
- **Local kipi GERÇEKTEN koşar.** Bugünkü üretim davranışı içerik-adresli
  yerel depodur (`media/naming.py` + `pipeline/storage/local.py`); bu
  senaryolar canlı koddur, mock değildir.
- **S3 / Mirror / Tiered kipleri `skipUnless(ortam)` ile atlanır.** Gerekçe:
  üretimde `s3_enabled=0` (bkz. docs/reports/23-t051-s3-adaptor.md) ve kabul
  koşumu hedef ortamı VARSAYMAZ — dev MinIO'ya örtük bağlanıp yeşil yakmak
  kabul kanıtı sayılmaz. Bu kipleri koşturmak için `MEDIA_ENGINE_S3_*`
  ortam değişkenleri açıkça verilmelidir. Sahte yeşil YOK: koşulmayan
  senaryo `skipped` görünür, `passed` değil.
- HTTP katmanı (403, Cache-Control, nginx başlıkları) bu dosyanın kapsamı
  DIŞINDA ölçülür: docs/reports/27-t052-cdn-teslim.md ve
  docs/reports/70-w3c-medya-csp.md. Burada adaptör + imza sözleşmesi test
  edilir.

ÇALIŞTIRMA
----------
Backend konteynerinde (Pillow/ffmpeg/frappe site GEREKMEZ):

    docker exec istoc-dev-backend-1 bash -c \\
      "cd /home/frappe/frappe-bench/apps/tradehub_core && \\
       python3 -m unittest tradehub_core.tests.acceptance.test_storage_acceptance -v"

S3'lü kipleri de koşturmak için (kabul ortamında, bilinçli):

    MEDIA_ENGINE_S3_ENDPOINT_URL=... MEDIA_ENGINE_S3_BUCKET=... \\
    MEDIA_ENGINE_S3_ACCESS_KEY_ID=... MEDIA_ENGINE_S3_SECRET_ACCESS_KEY=... \\
    python3 -m unittest tradehub_core.tests.acceptance.test_storage_acceptance -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.contracts.storage import (  # noqa: E402
	HASH_LENGTH,
	SCOPE_PRIVATE,
	SCOPE_PUBLIC,
	content_hash,
)
from tradehub_core.media.pipeline.delivery.signed import HmacUrlSigner  # noqa: E402
from tradehub_core.media.pipeline.storage import (  # noqa: E402
	MODE_LOCAL,
	MODE_MIRROR,
	MODE_S3,
	MODE_TIERED,
	StorageSettings,
	build_storage,
)
from tradehub_core.media.pipeline.storage.local import TEMP_PREFIX, LocalDiskStorage  # noqa: E402
from tradehub_core.media.pipeline.storage.retention import (  # noqa: E402
	RetentionSweeper,
)

SECRET = b"kabul-testi-imza-anahtari-32byte"

#: S3'lü kiplerin koşulabilmesi için ZORUNLU ortam değişkenleri. Varsayılan
#: YOK — `test_storage_adapters_minio.py`'nin aksine burada dev MinIO'ya
#: örtük düşüş bilinçli olarak kapatıldı (kabul ≠ dev smoke).
_S3_ENV_KEYS = (
	"MEDIA_ENGINE_S3_ENDPOINT_URL",
	"MEDIA_ENGINE_S3_BUCKET",
	"MEDIA_ENGINE_S3_ACCESS_KEY_ID",
	"MEDIA_ENGINE_S3_SECRET_ACCESS_KEY",
)


def _s3_env_ready() -> bool:
	return all(os.environ.get(anahtar) for anahtar in _S3_ENV_KEYS)


S3_SKIP_GEREKCE = (
	"S3 kabul ortamı tanımlı değil (MEDIA_ENGINE_S3_* boş). Üretimde s3_enabled=0; "
	"kabul koşumu hedef S3'ü varsaymaz, dev MinIO'ya örtük bağlanmaz. "
	"Sözleşme düzeyi S3 doğrulaması için bkz. tests/test_storage_adapters.py (sahte istemci) "
	"ve tests/test_storage_adapters_minio.py (MinIO'ya karşı, kendi skip mantığıyla)."
)


class _LocalKurulum(unittest.TestCase):
	"""Ortak kurulum: geçici köklerde gerçek yerel depo."""

	def setUp(self) -> None:
		self._tmp = tempfile.mkdtemp(prefix="t055-kabul-")
		self.public_root = os.path.join(self._tmp, "public", "files")
		self.private_root = os.path.join(self._tmp, "private", "files")
		self.signer = HmacUrlSigner(SECRET)
		self.store = LocalDiskStorage(self.public_root, self.private_root, signer=self.signer)
		self.addCleanup(self._temizle)

	def _temizle(self) -> None:
		import shutil

		shutil.rmtree(self._tmp, ignore_errors=True)

	def _kalinti_gecici_dosyalar(self) -> list:
		kalinti = []
		for kok in (self.public_root, self.private_root):
			for dizin, _alt, dosyalar in os.walk(kok):
				kalinti.extend(os.path.join(dizin, ad) for ad in dosyalar if ad.startswith(TEMP_PREFIX))
		return kalinti


class TestKabul1LocalUctanUca(_LocalKurulum):
	"""Senaryo 1 (kip=local): yükleme → içerik-adresli saklama → teslim URL'i.

	Şartname maddesi: "Dört depolama modunda uçtan uca yükleme→teslim
	senaryosu geçiyor." Bu sınıf LOCAL kipini kapatır; diğer üç kip
	aşağıdaki skip'li sınıflarda.
	"""

	ICERIK = b"\xff\xd8\xff\xe0" + b"t055-kabul-jpeg-govdesi" * 64  # JPEG magic + gövde

	def test_yukleme_teslim_uctan_uca(self) -> None:
		sonuc = self.store.put(self.ICERIK, ".jpg")
		self.assertTrue(sonuc.created)

		# İçerik-adresli ad: sha256(içerik)[:32] + uzantı, shard = ilk 2 hex
		beklenen_ad = content_hash(self.ICERIK)[:HASH_LENGTH] + ".jpg"
		self.assertEqual(sonuc.ref.key.name, beklenen_ad)
		self.assertEqual(sonuc.ref.key.shard, beklenen_ad[:2])

		# Teslim URL'i file_url sözleşmesiyle birebir (NFR-044)
		self.assertEqual(sonuc.ref.url, f"/files/{beklenen_ad[:2]}/{beklenen_ad}")
		self.assertEqual(self.store.url_for(sonuc.ref), sonuc.ref.url)

		# Geri okuma bayt-bayt aynı; künye tam hash taşıyor
		self.assertEqual(self.store.get(sonuc.ref), self.ICERIK)
		self.assertEqual(self.store.stat(sonuc.ref).content_hash, content_hash(self.ICERIK))

	def test_idempotent_ikinci_yukleme_dedup(self) -> None:
		ilk = self.store.put(self.ICERIK, ".jpg")
		ikinci = self.store.put(self.ICERIK, ".jpg")
		self.assertTrue(ilk.created)
		self.assertFalse(ikinci.created, "Aynı içerik ikinci kez 'yeni' sayılmamalı (dedup)")
		self.assertEqual(ilk.ref, ikinci.ref)
		self.assertEqual(len(self.store), 1)

	def test_atomik_yazim_kalinti_birakmaz(self) -> None:
		for i in range(5):
			self.store.put(self.ICERIK + bytes([i]), ".jpg")
		self.assertEqual(self._kalinti_gecici_dosyalar(), [])

	def test_public_private_tasima_anahtar_korunur(self) -> None:
		sonuc = self.store.put(self.ICERIK, ".jpg")
		hedef = self.store.move(sonuc.ref, SCOPE_PRIVATE)
		self.assertEqual(hedef.key, sonuc.ref.key, "Taşımada shard + ad korunmalı")
		self.assertTrue(hedef.url.startswith("/private/files/"))
		self.assertFalse(self.store.exists(sonuc.ref))
		self.assertTrue(self.store.exists(hedef))

	def test_private_imzali_url_ve_dogrulama(self) -> None:
		sonuc = self.store.put(self.ICERIK, ".jpg", scope=SCOPE_PRIVATE)
		imzali = self.store.url_for(sonuc.ref, ttl_seconds=60)
		self.assertNotEqual(imzali, sonuc.ref.url, "Private URL imzasız dönmemeli")

		gecerli = self.signer.verify(imzali)
		self.assertTrue(gecerli.valid, f"Taze imza doğrulanmalı: {gecerli}")

		kurcalanmis = imzali.replace(sonuc.ref.key.shard, "zz", 1)
		self.assertFalse(self.signer.verify(kurcalanmis).valid, "Kurcalanmış imza geçmemeli")

	def test_imzalayicisiz_private_url_reddedilir(self) -> None:
		from tradehub_core.media.pipeline.contracts.errors import StorageError

		imzasiz_depo = LocalDiskStorage(self.public_root, self.private_root, signer=None)
		sonuc = imzasiz_depo.put(self.ICERIK, ".jpg", scope=SCOPE_PRIVATE)
		with self.assertRaises(StorageError):
			imzasiz_depo.url_for(sonuc.ref)


class TestKabul2S3KapaliykenTamIslevsel(_LocalKurulum):
	"""Senaryo 2: "S3 ve CDN kapalıyken sistem tam işlevsel; hiçbir S3 çağrısı yok".

	İki gerçek ölçüm:
	- local kip uçtan uca çalışırken `boto3` SÜREÇTE HİÇ import edilmiyor
	  (taze alt süreçte `sys.modules` kontrolü — şartnamedeki lazy-import
	  kanıtı deseni).
	- `build_storage` üretim fabrikası mode=local için S3'süz plan kuruyor.
	"""

	def test_local_kip_boto3_import_etmez(self) -> None:
		betik = textwrap.dedent(
			f"""
			import sys
			sys.path.insert(0, {str(ROOT)!r})
			import tempfile, os
			from tradehub_core.media.pipeline.storage.local import LocalDiskStorage
			kok = tempfile.mkdtemp()
			depo = LocalDiskStorage(os.path.join(kok, "pub"), os.path.join(kok, "prv"))
			r = depo.put(b"t055-purity", ".bin")
			assert depo.get(r.ref) == b"t055-purity"
			assert "boto3" not in sys.modules, "local kip boto3 import etti!"
			print("PURITY-OK")
			"""
		)
		cikti = subprocess.run(
			[sys.executable, "-c", betik], capture_output=True, text=True, timeout=60
		)
		self.assertEqual(cikti.returncode, 0, cikti.stderr)
		self.assertIn("PURITY-OK", cikti.stdout)

	def test_build_storage_local_plan(self) -> None:
		ayar = StorageSettings(
			mode=MODE_LOCAL,
			public_root=self.public_root,
			private_root=self.private_root,
			signing_secret=SECRET.decode("utf-8"),
		)
		plan = build_storage(ayar)
		self.assertEqual(plan.mode, MODE_LOCAL)
		self.assertFalse(plan.degraded)
		sonuc = plan.adapter.put(b"t055-plan", ".bin")
		self.assertEqual(plan.adapter.get(sonuc.ref), b"t055-plan")


class TestKabul3GracefulDegradation(_LocalKurulum):
	"""Senaryo 3 (yerel ölçülebilen yarısı): S3 istenmiş ama KULLANILAMIYORSA
	sistem yerelde çalışmaya devam eder ve sebep raporlar.

	Şartnamedeki tam senaryo (S3 açık + kimlik bilgisi HATALI + kopyalama
	başarısız + alarm) canlı bir S3 ucu gerektirir — o yarısı
	`TestKabulS3Kipleri.test_s3_yanlis_kimlik_yerel_calisir` altında ve
	ortam yoksa atlanır. Burada ölçülen: fabrikanın düşüş (downgrade)
	sözleşmesi.
	"""

	def test_s3_istenmis_ama_kapali_yerel_dusus(self) -> None:
		ayar = StorageSettings(
			mode=MODE_S3,
			public_root=self.public_root,
			private_root=self.private_root,
			signing_secret=SECRET.decode("utf-8"),
		)  # s3=S3Config() → enabled=False, bucket boş
		plan = build_storage(ayar)
		self.assertEqual(plan.requested_mode, MODE_S3)
		self.assertEqual(plan.mode, MODE_LOCAL, "S3 kurulamıyorsa yerel'e düşmeli")
		self.assertTrue(plan.degraded)
		self.assertTrue(plan.reasons, "Düşüş sebepsiz olmamalı — alarm bu sebeplerden üretilir")
		# Düşmüş plan yine de tam işlevsel:
		sonuc = plan.adapter.put(b"t055-degraded", ".bin")
		self.assertEqual(plan.adapter.get(sonuc.ref), b"t055-degraded")


class TestKabul4CdnToggle(_LocalKurulum):
	"""CDN aç/kapat yalnız teslim origin'ini değiştirir; varlık kimliği aynıdır."""

	def test_ayni_varlik_origin_ve_cdn_uzerinden_teslim_ediliyor(self) -> None:
		from tradehub_core.media.pipeline.storage.s3 import S3Config, S3Storage

		ref = self.store.put(b"t055-cdn-ayni-varlik", ".jpg").ref
		client_calls: list[bool] = []

		def istemci_kurulmamali():
			client_calls.append(True)
			raise AssertionError("public URL üretimi S3 istemcisi kurmamalı")

		ortak = dict(
			enabled=True,
			bucket="t055",
			access_key_id="not-used",
			secret_access_key="not-used",
		)
		origin = S3Storage(S3Config(**ortak), client_factory=istemci_kurulmamali)
		cdn = S3Storage(
			S3Config(**ortak, public_base_url="https://cdn.example.test"),
			client_factory=istemci_kurulmamali,
		)

		self.assertEqual(origin.url_for(ref), ref.url)
		self.assertEqual(cdn.url_for(ref), f"https://cdn.example.test{ref.url}")
		self.assertEqual(len(self.store), 1)
		self.assertEqual(self.store.get(ref), b"t055-cdn-ayni-varlik")
		self.assertEqual(client_calls, [], "CDN toggle nesne deposuna gereksiz ağ çağrısı yaptı")


class TestKabul6RetentionKuruKosum(_LocalKurulum):
	"""Senaryo 6: "Saklama kuru çalıştırması: hiçbir dosya silinmiyor, rapor doğru".

		`RetentionSweeper` varsayılanı dry-run'dır; bu saf adaptör testi varsayılan politikayla
		süpürmenin (a) hiçbir nesneyi silmediğini, (b) raporun dry_run=True ve
		nesne sayımıyla tutarlı olduğunu ölçer. İnsan onay kapısı gerçek
		Frappe sitesi üzerinde `test_retention_gc.py` tarafından kanıtlanır.
	"""

	def test_kuru_kosum_hicbir_sey_silmez(self) -> None:
		for i in range(3):
			self.store.put(b"t055-retention-%d" % i, ".jpg")
		onceki = len(self.store)

		supurucu = RetentionSweeper(self.store)  # politika: şema varsayılanları
		rapor = supurucu.sweep(scope=SCOPE_PUBLIC)  # dry_run varsayılan True

		self.assertTrue(rapor.dry_run)
		self.assertEqual(len(self.store), onceki, "Kuru koşum dosya silmiş!")
		self.assertEqual(self._kalinti_gecici_dosyalar(), [])


@unittest.skipUnless(_s3_env_ready(), S3_SKIP_GEREKCE)
class TestKabulS3Kipleri(unittest.TestCase):
	"""Senaryolar 1 (s3/mirror/tiered), 3 (canlı yanlış-kimlik) ve 5 (tiered göç).

	ORTAM GEREKTİRİR — `MEDIA_ENGINE_S3_*` tanımlı değilse atlanır (gerekçe
	sınıf dekoratöründe). Bu gövdelere sahte istemci KONMADI: sahte yeşil,
	skip'ten daha kötüdür.
	"""

	def setUp(self) -> None:
		from tradehub_core.media.pipeline.storage.s3 import boto3_available

		if not boto3_available():
			self.skipTest("boto3 kurulu değil — S3 kipleri koşulamaz")
		self._tmp = tempfile.mkdtemp(prefix="t055-s3-")
		self._s3_prefix = f"t055-kabul/{uuid.uuid4().hex}"
		import shutil

		self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))

	def _ayar(self, kip: str, **s3_degisiklik: object) -> StorageSettings:
		from tradehub_core.media.pipeline.storage.s3 import S3Config

		s3_alanlar = dict(
			enabled=True,
			endpoint_url=os.environ["MEDIA_ENGINE_S3_ENDPOINT_URL"],
			bucket=os.environ["MEDIA_ENGINE_S3_BUCKET"],
			access_key_id=os.environ["MEDIA_ENGINE_S3_ACCESS_KEY_ID"],
			secret_access_key=os.environ["MEDIA_ENGINE_S3_SECRET_ACCESS_KEY"],
			region=os.environ.get("MEDIA_ENGINE_S3_REGION", "us-east-1"),
			prefix=f"{self._s3_prefix}/{kip}",
			addressing_style=os.environ.get("MEDIA_ENGINE_S3_ADDRESSING_STYLE", "path"),
		)
		s3_alanlar.update(s3_degisiklik)
		return StorageSettings(
			mode=kip,
			public_root=os.path.join(self._tmp, kip, "pub"),
			private_root=os.path.join(self._tmp, kip, "prv"),
			signing_secret=SECRET.decode("utf-8"),
			s3=S3Config(**s3_alanlar),
			tier_age_days=14,
		)

	def _uctan_uca(self, kip: str) -> None:
		plan = build_storage(self._ayar(kip))
		self.assertEqual(plan.mode, kip, f"{kip} kipi kurulamadı: {plan.reasons}")
		icerik = f"t055-{kip}-uctan-uca".encode()
		sonuc = plan.adapter.put(icerik, ".jpg")
		self.assertEqual(plan.adapter.get(sonuc.ref), icerik)
		self.assertTrue(plan.adapter.exists(sonuc.ref))
		plan.adapter.delete(sonuc.ref)
		self.assertFalse(plan.adapter.exists(sonuc.ref))

	def test_s3_primary_uctan_uca(self) -> None:
		self._uctan_uca(MODE_S3)

	def test_mirror_uctan_uca(self) -> None:
		self._uctan_uca(MODE_MIRROR)

	def test_tiered_uctan_uca_ve_goc(self) -> None:
		"""Senaryo 5: saati kaydırarak 14 gün eşiğini beklemeden doğrula."""
		plan = build_storage(self._ayar(MODE_TIERED))
		self.assertEqual(plan.mode, MODE_TIERED, f"tiered kurulamadı: {plan.reasons}")
		icerik = b"t055-tiered-goc"
		sonuc = plan.adapter.put(icerik, ".jpg")
		try:
			mtime = plan.adapter.stat(sonuc.ref).modified_at
			henuz_degil = plan.adapter.sweep(
				dry_run=True, now=mtime + 14 * 86400 - 1
			)
			self.assertEqual(henuz_degil.eligible, 0)
			self.assertEqual(plan.adapter.location(sonuc.ref), "hot")
			goc = plan.adapter.sweep(dry_run=False, now=mtime + 14 * 86400 + 1)
			self.assertEqual(goc.eligible, 1)
			self.assertEqual(goc.demoted, 1)
			self.assertEqual(plan.adapter.location(sonuc.ref), "cold")
			self.assertEqual(
				plan.adapter.get(sonuc.ref), icerik, "Sıcakta olmayan nesne soğuktan (S3) okunmalı"
			)
		finally:
			plan.adapter.delete(sonuc.ref)

	def test_s3_yanlis_kimlik_yerel_calisir(self) -> None:
		"""Senaryo 3 (canlı yarısı): mirror + bozuk kimlik → yerel yazma BAŞARILI,
		S3 kopyası başarısız; alarm üretilir ve kullanıcıya hata sızmaz."""
		from tradehub_core.media.pipeline.storage.mirror import InlineMirrorQueue

		alarmlar: list[dict] = []
		plan = build_storage(
			self._ayar(MODE_MIRROR, access_key_id="bozuk", secret_access_key="bozuk"),
			queue_factory=lambda worker: InlineMirrorQueue(worker),
			alarm=alarmlar.append,
		)
		icerik = b"t055-bozuk-kimlik"
		sonuc = plan.adapter.put(icerik, ".jpg")  # yerel taraf senkron → başarılı olmalı
		self.assertEqual(plan.adapter.get(sonuc.ref), icerik, "Yerel kopya her koşulda okunmalı")
		self.assertGreater(plan.adapter.counters()["failed"], 0)
		self.assertTrue(plan.adapter.failed_tasks())
		self.assertTrue(alarmlar, "S3 kimlik hatası alarm üretmedi")


if __name__ == "__main__":
	unittest.main()
