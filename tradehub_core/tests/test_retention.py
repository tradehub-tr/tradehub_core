"""T-053 — Saklama politikası testleri.

Sınanan dört şey:

  1. Sayılar `tradehub_core/media/pipeline/policy/retention.schema.json` ile AYNI (ayrışma
     testi) — kodda ikinci bir "30 gün" tanımı yok.
  2. İki politika BAĞIMSIZ: orijinali süresiz tutup türevi silmek ve tersi,
     birbirini etkilemeden mümkün.
  3. `legal_hold` HER ŞEYİ bloke eder — kapı uygulanamıyorsa yıkıcı işlem
     hiç yapılmaz.
  4. Kuru koşum (dry-run) VARSAYILANDIR ve gerçekten hiçbir şeye dokunmaz;
     upstream `purge_expired` kuru koşumda ÇAĞRILMAZ.

Çalıştırma (frappe/site GEREKMEZ):

    python3 -m unittest tests.test_retention -v
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.contracts.delivery import derivative_key  # noqa: E402
from tradehub_core.media.pipeline.contracts.storage import (  # noqa: E402
	SCOPE_PRIVATE,
	SCOPE_PUBLIC,
	ObjectRef,
	key_for,
)
from tradehub_core.media.pipeline.delivery import signed as signed_urls  # noqa: E402
from tradehub_core.media.pipeline.storage import retention as ret  # noqa: E402
from tradehub_core.media.pipeline.storage.local import LocalDiskStorage  # noqa: E402

SECRET = b"retention-test-anahtari-32-bayt!!"


class YerelDepoluTest(unittest.TestCase):
	"""Gerçek disk üzerinde çalışan ortak kurulum (mtime yaşlandırılabilsin)."""

	def setUp(self) -> None:  # noqa: N802
		self.tmp = tempfile.mkdtemp(prefix="retention-")
		self.public_root = os.path.join(self.tmp, "public", "files")
		self.private_root = os.path.join(self.tmp, "private", "files")
		self.storage = LocalDiskStorage(
			self.public_root,
			self.private_root,
			signer=signed_urls.HmacUrlSigner(SECRET),
			fsync=False,
		)

	def tearDown(self) -> None:  # noqa: N802
		shutil.rmtree(self.tmp, ignore_errors=True)

	def _yol(self, ref: ObjectRef) -> str:
		kok = self.public_root if ref.scope == SCOPE_PUBLIC else self.private_root
		return os.path.join(kok, ref.key.shard, ref.key.name)

	def yaslandir(self, ref: ObjectRef, gun: float) -> None:
		eski = time.time() - gun * 86400
		os.utime(self._yol(ref), (eski, eski))

	def yaz(self, icerik: bytes, uzanti: str = ".jpg", *, scope: str = SCOPE_PUBLIC, yas: float = 0.0) -> ObjectRef:
		ref = self.storage.put(icerik, uzanti, scope=scope).ref
		if yas:
			self.yaslandir(ref, yas)
		return ref

	def turev_yaz(self, ana: ObjectRef, profil: str, icerik: bytes, *, yas: float = 0.0) -> ObjectRef:
		"""Türev dosyayı doğrudan diske koy — türev boru hattı henüz YOK.

		Anahtar `contracts/delivery.derivative_key` ile üretilir; testin
		"türev" tanımı ile motorun tanımı aynı yerden gelir.
		"""
		key = derivative_key(ana.key, profil, "webp")
		ref = ObjectRef(key=key, scope=ana.scope)
		yol = self._yol(ref)
		os.makedirs(os.path.dirname(yol), exist_ok=True)
		with open(yol, "wb") as fh:
			fh.write(icerik)
		if yas:
			self.yaslandir(ref, yas)
		return ref


# ── Şema ile ayrışma ────────────────────────────────────────────────────


class TestSemaVarsayilanlari(unittest.TestCase):
	def test_sema_dosyasi_okunuyor(self) -> None:
		self.assertTrue(os.path.isfile(ret.SCHEMA_PATH), ret.SCHEMA_PATH)
		varsayilan = ret.schema_defaults()
		self.assertIn("original_retention", varsayilan)
		self.assertIn("derivative_retention", varsayilan)

	def test_ayna_ile_sema_ayrismamis(self) -> None:
		"""`_MIRROR_DEFAULTS` şemadan sapmışsa bu test DÜŞER."""
		sema = ret.schema_defaults()
		for blok, alanlar in ret._MIRROR_DEFAULTS.items():
			for ad, deger in alanlar.items():
				with self.subTest(blok=blok, alan=ad):
					self.assertIn(blok, sema)
					self.assertEqual(sema[blok].get(ad), deger)

	def test_uretim_sabitleriyle_ayni_sayilar(self) -> None:
		"""30 / 30 / 14 / 48 — `trash.py`, `archive.py`, `backup.py` değerleri."""
		p = ret.RetentionPolicy.defaults()
		self.assertEqual(p.trash_retention_days, 30)
		self.assertEqual(p.archive_retention_days, 30)
		self.assertEqual(p.backup_keep_sets, 14)
		self.assertEqual(ret.schema_defaults()["backup"]["export_keep_hours"], 48)

	def test_varsayilan_politika_gecerli_ve_koruyucu(self) -> None:
		p = ret.RetentionPolicy.defaults()
		self.assertEqual(p.validate(), [])
		self.assertEqual(p.warnings(), [])
		self.assertTrue(p.original.keep_forever, "orijinal varsayılan SÜRESİZ")
		self.assertEqual(p.derivative.action, "notify_only", "türev varsayılanı yıkıcı değil")
		self.assertEqual(p.derivative.unused_after_days, 90)
		self.assertFalse(p.legal_hold_enabled, "legal_hold bugün YOK")

	def test_sema_dosyasi_gecerli_json(self) -> None:
		with open(ret.SCHEMA_PATH, encoding="utf-8") as fh:
			sema = json.load(fh)
		self.assertEqual(sema.get("type"), "object")
		self.assertIn("legal_hold", sema.get("required", []))


# ── Politika doğrulama ──────────────────────────────────────────────────


class TestPolitikaDogrulama(unittest.TestCase):
	def test_keep_forever_kapaliysa_local_days_zorunlu(self) -> None:
		p = ret.RetentionPolicy(original=ret.OriginalRetention(keep_forever=False))
		hatalar = p.validate()
		self.assertTrue(any("local_days" in h for h in hatalar), hatalar)

	def test_keep_forever_kapali_gecerli_kurulum(self) -> None:
		p = ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=False, local_days=365, then="s3_cold")
		)
		self.assertEqual(p.validate(), [])

	def test_bilinmeyen_hedef_reddedilir(self) -> None:
		p = ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=False, local_days=10, then="ay-a-gonder")
		)
		self.assertTrue(p.validate())

	def test_silme_plus_yeniden_uretilemezlik_uyarir(self) -> None:
		p = ret.RetentionPolicy(
			derivative=ret.DerivativeRetention(action="delete", regenerate_on_demand=False)
		)
		self.assertEqual(p.validate(), [], "geçersiz değil, ama uyarılı")
		self.assertTrue(p.warnings())
		self.assertIn("VERİ KAYBIDIR", p.warnings()[0])

	def test_gecersiz_politika_supurucu_kurulamaz(self) -> None:
		p = ret.RetentionPolicy(original=ret.OriginalRetention(keep_forever=False))
		with self.assertRaises(ret.PolicyInvalid):
			ret.RetentionSweeper(object(), p)  # type: ignore[arg-type]

	def test_from_mapping_kismi_ayari_birlestirir(self) -> None:
		p = ret.RetentionPolicy.from_mapping({"derivative_retention": {"unused_after_days": 30}})
		self.assertEqual(p.derivative.unused_after_days, 30)
		self.assertEqual(p.derivative.action, "notify_only", "verilmeyen alan varsayılanda kalır")
		self.assertTrue(p.original.keep_forever)

	def test_to_dict_yuvarlak_gider(self) -> None:
		p = ret.RetentionPolicy.from_mapping(
			{"original_retention": {"keep_forever": False, "local_days": 200, "then": "s3_cold"}}
		)
		tekrar = ret.RetentionPolicy.from_mapping(p.to_dict())
		self.assertEqual(tekrar.to_dict(), p.to_dict())


# ── Türev ayrımı ────────────────────────────────────────────────────────


class TestTurevAyrimi(unittest.TestCase):
	def test_orijinal_turev_degil(self) -> None:
		key = key_for(b"orijinal", ".jpg")
		self.assertFalse(ret.is_derivative(key))
		self.assertEqual(ret.profile_of(key), "")

	def test_turev_taninir_ve_profil_okunur(self) -> None:
		ana = key_for(b"orijinal", ".jpg")
		turev = derivative_key(ana, "w960", "webp")
		self.assertTrue(ret.is_derivative(turev))
		self.assertEqual(ret.profile_of(turev), "w960")
		self.assertEqual(turev.shard, ana.shard, "türev orijinalin yanında durur")


# ── İki politikanın bağımsızlığı ────────────────────────────────────────


class TestPolitikaBagimsizligi(YerelDepoluTest):
	def _supurucu(self, politika: ret.RetentionPolicy, **kwargs: Any) -> ret.RetentionSweeper:
		return ret.RetentionSweeper(self.storage, politika, **kwargs)

	def test_orijinal_silinirken_turev_korunur(self) -> None:
		politika = ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=False, local_days=30, then="delete"),
			derivative=ret.DerivativeRetention(unused_after_days=365, action="delete"),
		)
		ana = self.yaz(b"eski-orijinal", yas=100)
		turev = self.turev_yaz(ana, "w320", b"eski-turev", yas=100)
		s = self._supurucu(politika, usage_lookup=lambda r: ret.VERDICT_UNUSED)

		self.assertEqual(s.decide(ana).action, ret.ACTION_DELETE)
		self.assertEqual(s.decide(turev).action, ret.ACTION_KEEP)
		self.assertEqual(s.decide(turev).reason, ret.REASON_TOO_YOUNG)

	def test_turev_silinirken_orijinal_korunur(self) -> None:
		politika = ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=True),
			derivative=ret.DerivativeRetention(unused_after_days=90, action="delete"),
		)
		ana = self.yaz(b"kalici-orijinal", yas=500)
		turev = self.turev_yaz(ana, "w320", b"kullanilmayan-turev", yas=200)
		s = self._supurucu(politika, usage_lookup=lambda r: ret.VERDICT_UNUSED)

		self.assertEqual(s.decide(ana).action, ret.ACTION_KEEP)
		self.assertEqual(s.decide(ana).reason, ret.REASON_KEEP_FOREVER)
		self.assertEqual(s.decide(turev).action, ret.ACTION_DELETE)

	def test_always_keep_profili_hicbir_kosulda_silinmez(self) -> None:
		politika = ret.RetentionPolicy(
			derivative=ret.DerivativeRetention(
				unused_after_days=1, action="delete", always_keep_profiles=("w320",)
			)
		)
		ana = self.yaz(b"lcp-ana", yas=500)
		korunan = self.turev_yaz(ana, "w320", b"lcp-turev", yas=500)
		silinen = self.turev_yaz(ana, "w1920", b"buyuk-turev", yas=500)
		s = self._supurucu(politika, usage_lookup=lambda r: ret.VERDICT_UNUSED)

		self.assertEqual(s.decide(korunan).action, ret.ACTION_KEEP)
		self.assertEqual(s.decide(korunan).reason, ret.REASON_ALWAYS_KEEP)
		self.assertEqual(s.decide(silinen).action, ret.ACTION_DELETE)

	def test_kullanim_bilinmiyorsa_turev_korunur(self) -> None:
		"""Güvenli taraf (NFR-043): ölçemediğini 'kullanılmıyor' sayma."""
		politika = ret.RetentionPolicy(
			derivative=ret.DerivativeRetention(unused_after_days=1, action="delete")
		)
		ana = self.yaz(b"ana", yas=100)
		turev = self.turev_yaz(ana, "w640", b"turev", yas=100)
		s = self._supurucu(politika)  # usage_lookup YOK
		karar = s.decide(turev)
		self.assertEqual(karar.action, ret.ACTION_KEEP)
		self.assertEqual(karar.reason, ret.REASON_USAGE_UNKNOWN)

	def test_kullanimda_olan_turev_silinmez(self) -> None:
		politika = ret.RetentionPolicy(
			derivative=ret.DerivativeRetention(unused_after_days=1, action="delete")
		)
		ana = self.yaz(b"ana2", yas=100)
		turev = self.turev_yaz(ana, "w640", b"turev2", yas=100)
		s = self._supurucu(politika, usage_lookup=lambda r: ret.VERDICT_IN_USE)
		self.assertEqual(s.decide(turev).reason, ret.REASON_IN_USE)

	def test_usage_lookup_patlarsa_korunur(self) -> None:
		def patla(ref: ObjectRef) -> str:
			raise RuntimeError("usage sorgusu çöktü")

		politika = ret.RetentionPolicy(
			derivative=ret.DerivativeRetention(unused_after_days=1, action="delete")
		)
		ana = self.yaz(b"ana3", yas=100)
		turev = self.turev_yaz(ana, "w640", b"turev3", yas=100)
		s = self._supurucu(politika, usage_lookup=patla)
		self.assertEqual(s.decide(turev).reason, ret.REASON_USAGE_UNKNOWN)

	def test_yeniden_uretilemeyen_turev_silinmez_bildirilir(self) -> None:
		politika = ret.RetentionPolicy(
			derivative=ret.DerivativeRetention(
				unused_after_days=1, action="delete", regenerate_on_demand=False
			)
		)
		ana = self.yaz(b"ana4", yas=100)
		turev = self.turev_yaz(ana, "w640", b"turev4", yas=100)
		s = self._supurucu(politika, usage_lookup=lambda r: ret.VERDICT_UNUSED)
		karar = s.decide(turev)
		self.assertEqual(karar.action, ret.ACTION_NOTIFY)
		self.assertEqual(karar.reason, ret.REASON_REGENERATE_OFF)

	def test_soguk_katman_yoksa_yaslandirma_bildirime_duser(self) -> None:
		politika = ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=False, local_days=30, then="s3_cold")
		)
		ana = self.yaz(b"yaslanacak", yas=100)
		s = self._supurucu(politika)  # cold=None
		karar = s.decide(ana)
		self.assertEqual(karar.action, ret.ACTION_NOTIFY)
		self.assertEqual(karar.reason, ret.REASON_NO_COLD_TIER)

	def test_soguk_katman_varsa_yaslandirilir(self) -> None:
		class SahteSoguk:
			def __init__(self) -> None:
				self.cagrilar: list = []

			def demote(self, ref: ObjectRef, *, dry_run: bool = False) -> Any:
				self.cagrilar.append(ref.url)
				return type("Sonuc", (), {"moved": True})()

		soguk = SahteSoguk()
		politika = ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=False, local_days=30, then="s3_cold")
		)
		ana = self.yaz(b"yaslanacak2", yas=100)
		s = self._supurucu(politika, cold=soguk)
		karar = s.decide(ana)
		self.assertEqual(karar.action, ret.ACTION_DEMOTE)
		self.assertTrue(s.apply(karar, dry_run=False))
		self.assertEqual(soguk.cagrilar, [ana.url])

	def test_olmayan_nesne_kararı_korumadir(self) -> None:
		politika = ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=False, local_days=1, then="delete")
		)
		ref = ObjectRef(key=key_for(b"hic-yazilmadi", ".jpg"), scope=SCOPE_PUBLIC)
		s = self._supurucu(politika)
		karar = s.decide(ref)
		self.assertEqual(karar.action, ret.ACTION_KEEP)
		self.assertEqual(karar.reason, ret.REASON_NOT_FOUND)


# ── Kuru koşum ──────────────────────────────────────────────────────────


class TestKuruKosum(YerelDepoluTest):
	def _yikici_politika(self) -> ret.RetentionPolicy:
		return ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=False, local_days=30, then="delete")
		)

	def test_sweep_varsayilani_kuru(self) -> None:
		ref = self.yaz(b"kuru-kosum-testi", yas=100)
		s = ret.RetentionSweeper(self.storage, self._yikici_politika())
		rapor = s.sweep()  # varsayılan
		self.assertTrue(rapor.dry_run)
		self.assertEqual(rapor.deleted, 0)
		self.assertEqual(rapor.scanned, 1)
		self.assertEqual(rapor.bytes_freed, len(b"kuru-kosum-testi"))
		self.assertTrue(self.storage.exists(ref), "kuru koşum HİÇBİR ŞEYE dokunmaz")

	def test_sweep_yas_dolmayani_korur(self) -> None:
		ref = self.yaz(b"taze-dosya", yas=5)
		s = ret.RetentionSweeper(self.storage, self._yikici_politika())
		rapor = s.sweep(dry_run=False)
		self.assertEqual(rapor.kept, 1)
		self.assertEqual(rapor.deleted, 0)
		self.assertTrue(self.storage.exists(ref))

	def test_sweep_islak_kosum_siler(self) -> None:
		eski = self.yaz(b"silinecek-eski", yas=100)
		taze = self.yaz(b"kalacak-taze", yas=1)
		s = ret.RetentionSweeper(self.storage, self._yikici_politika())
		rapor = s.sweep(dry_run=False)
		self.assertEqual(rapor.deleted, 1)
		self.assertEqual(rapor.kept, 1)
		self.assertFalse(self.storage.exists(eski))
		self.assertTrue(self.storage.exists(taze))

	def test_apply_kuru_kosumda_hicbir_sey_yapmaz(self) -> None:
		ref = self.yaz(b"apply-kuru", yas=100)
		s = ret.RetentionSweeper(self.storage, self._yikici_politika())
		karar = s.decide(ref)
		self.assertEqual(karar.action, ret.ACTION_DELETE)
		self.assertFalse(s.apply(karar))  # varsayılan dry_run=True
		self.assertTrue(self.storage.exists(ref))

	def test_sweep_limit_durdurur(self) -> None:
		for i in range(5):
			self.yaz(f"limit-{i}".encode(), yas=100)
		s = ret.RetentionSweeper(self.storage, self._yikici_politika())
		rapor = s.sweep(limit=2)
		self.assertEqual(rapor.scanned, 2)

	def test_sweep_bilinmeyen_kapsam(self) -> None:
		s = ret.RetentionSweeper(self.storage, ret.RetentionPolicy.defaults())
		with self.assertRaises(ValueError):
			s.sweep(scope="arsiv")

	def test_rapor_sozlugu_kesilme_bilgisi_tasir(self) -> None:
		for i in range(60):
			self.yaz(f"rapor-{i}".encode(), yas=100)
		s = ret.RetentionSweeper(self.storage, self._yikici_politika())
		veri = s.sweep().to_dict()
		self.assertEqual(len(veri["decisions"]), 50)
		self.assertEqual(veri["decisions_truncated"], 10)
		self.assertTrue(veri["dry_run"])

	def test_varsayilan_politika_hicbir_seyi_silmez(self) -> None:
		"""Varsayılanla koşan bir süpürme üretimde davranış DEĞİŞTİRMEZ."""
		refler = [self.yaz(f"varsayilan-{i}".encode(), yas=1000) for i in range(3)]
		s = ret.RetentionSweeper(self.storage, ret.RetentionPolicy.defaults())
		rapor = s.sweep(dry_run=False)
		self.assertEqual(rapor.deleted, 0)
		self.assertEqual(rapor.kept, 3)
		for ref in refler:
			self.assertTrue(self.storage.exists(ref))


# ── Legal hold ──────────────────────────────────────────────────────────


class SahteKapi:
	"""Uygulanabilirliği testin kontrol ettiği legal hold kapısı."""

	def __init__(self, tutulan: Optional[set] = None, *, enforceable: bool = True) -> None:
		self._tutulan = tutulan or set()
		self._enforceable = enforceable

	def is_held(self, ref: ObjectRef) -> bool:
		return ref.url in self._tutulan

	@property
	def enforceable(self) -> bool:
		return self._enforceable


class TestLegalHold(YerelDepoluTest):
	def _politika(self, **kwargs: Any) -> ret.RetentionPolicy:
		return ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=False, local_days=30, then="delete"),
			derivative=ret.DerivativeRetention(unused_after_days=1, action="delete"),
			legal_hold_enabled=True,
			**kwargs,
		)

	def test_acik_ama_kapisiz_kurulum_reddedilir(self) -> None:
		with self.assertRaises(ret.PolicyInvalid):
			ret.RetentionSweeper(self.storage, self._politika())

	def test_tutulan_nesne_bloke_edilir(self) -> None:
		ref = self.yaz(b"yasal-saklama", yas=100)
		s = ret.RetentionSweeper(
			self.storage, self._politika(), legal_hold=ret.StaticLegalHold([ref.url])
		)
		karar = s.decide(ref)
		self.assertEqual(karar.action, ret.ACTION_BLOCKED)
		self.assertEqual(karar.reason, ret.REASON_LEGAL_HOLD)
		self.assertTrue(karar.held)

	def test_tutulan_nesne_islak_kosumda_da_silinmez(self) -> None:
		tutulan = self.yaz(b"tutulan-dosya", yas=100)
		serbest = self.yaz(b"serbest-dosya", yas=100)
		s = ret.RetentionSweeper(
			self.storage, self._politika(), legal_hold=ret.StaticLegalHold([tutulan.url])
		)
		rapor = s.sweep(dry_run=False)
		self.assertEqual(rapor.blocked, 1)
		self.assertEqual(rapor.deleted, 1)
		self.assertTrue(self.storage.exists(tutulan), "legal hold silmeyi durdurur")
		self.assertFalse(self.storage.exists(serbest))

	def test_legal_hold_turevi_de_kapsar(self) -> None:
		ana = self.yaz(b"ana-tutulan", yas=100)
		turev = self.turev_yaz(ana, "w640", b"turev-tutulan", yas=100)
		s = ret.RetentionSweeper(
			self.storage,
			self._politika(),
			legal_hold=ret.StaticLegalHold([turev.url]),
			usage_lookup=lambda r: ret.VERDICT_UNUSED,
		)
		self.assertEqual(s.decide(turev).action, ret.ACTION_BLOCKED)
		self.assertEqual(s.decide(ana).action, ret.ACTION_DELETE)

	def test_legal_hold_yaslandirmayi_da_bloke_eder(self) -> None:
		class SahteSoguk:
			def demote(self, ref: ObjectRef, *, dry_run: bool = False) -> Any:
				raise AssertionError("legal hold varken yaslandırma çağrılmamalı")

		ref = self.yaz(b"tutulan-yaslanmaz", yas=100)
		politika = ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=False, local_days=30, then="s3_cold"),
			legal_hold_enabled=True,
		)
		s = ret.RetentionSweeper(
			self.storage,
			politika,
			legal_hold=ret.StaticLegalHold([ref.url]),
			cold=SahteSoguk(),
		)
		rapor = s.sweep(dry_run=False)
		self.assertEqual(rapor.blocked, 1)
		self.assertEqual(rapor.demoted, 0)
		self.assertTrue(self.storage.exists(ref))

	def test_uygulanamayan_kapi_yikici_islemi_durdurur(self) -> None:
		"""Alan yoksa (bugünkü durum) hiçbir şey silinmez — sessiz iptal YOK."""
		ref = self.yaz(b"kapisiz-alan", yas=100)
		s = ret.RetentionSweeper(
			self.storage, self._politika(), legal_hold=SahteKapi(enforceable=False)
		)
		rapor = s.sweep(dry_run=False)
		self.assertEqual(rapor.deleted, 0)
		self.assertEqual(rapor.blocked, 1)
		self.assertTrue(self.storage.exists(ref))

	def test_kapali_legal_hold_kapiyi_hic_sormaz(self) -> None:
		class SormaKapisi:
			def is_held(self, ref: ObjectRef) -> bool:
				raise AssertionError("legal_hold kapalıyken kapı sorgulanmamalı")

			@property
			def enforceable(self) -> bool:
				return True

		ref = self.yaz(b"legal-hold-kapali", yas=100)
		politika = ret.RetentionPolicy(
			original=ret.OriginalRetention(keep_forever=False, local_days=30, then="delete"),
			legal_hold_enabled=False,
		)
		s = ret.RetentionSweeper(self.storage, politika, legal_hold=SormaKapisi())
		self.assertEqual(s.decide(ref).action, ret.ACTION_DELETE)

	def test_static_kapisi_sorgu_dizesini_yok_sayar(self) -> None:
		kapi = ret.StaticLegalHold(["/files/ab/abc.jpg?v=2"])
		ref = ObjectRef(key=key_for(b"x", ".jpg"), scope=SCOPE_PUBLIC)
		self.assertFalse(kapi.is_held(ref))
		kapi.add("/files/ab/abc.jpg")
		self.assertTrue(kapi.enforceable)

	def test_frappe_kapisi_frappesiz_uygulanamaz(self) -> None:
		kapi = ret.FrappeLegalHold()
		try:
			import frappe  # noqa: F401
		except Exception:
			self.assertFalse(kapi.enforceable, "frappe yokken kapı uygulanamaz sayılmalı")
			return
		self.skipTest("frappe var: kapı gerçek `File` şemasına karşı ölçülmeli (bench içinde)")

	def test_private_kapsam_da_kapsanir(self) -> None:
		ref = self.yaz(b"private-tutulan", ".pdf", scope=SCOPE_PRIVATE, yas=100)
		s = ret.RetentionSweeper(
			self.storage, self._politika(), legal_hold=ret.StaticLegalHold([ref.url])
		)
		rapor = s.sweep(scope=SCOPE_PRIVATE, dry_run=False)
		self.assertEqual(rapor.blocked, 1)
		self.assertTrue(self.storage.exists(ref))


# ── Upstream zarfı ──────────────────────────────────────────────────────


class TestUpstreamPurge(unittest.TestCase):
	"""`trash`/`archive`/`backup` purge zarfı — kuru koşumda ÇAĞRILMAZ."""

	def test_kuru_kosumda_upstream_cagrilmaz(self) -> None:
		zarf = ret.UpstreamPurge()
		for sonuc in zarf.run_all(dry_run=True):
			with self.subTest(hedef=sonuc["target"]):
				self.assertFalse(sonuc["called"])
				self.assertTrue(sonuc["dry_run"])
				self.assertFalse(sonuc["supported"])

	def test_kuru_kosum_frappe_gerektirmez(self) -> None:
		"""Bu test frappe kurulu OLMAYAN makinede de geçer — import tembel."""
		zarf = ret.UpstreamPurge()
		sonuc = zarf.purge_trash(dry_run=True)
		self.assertEqual(sonuc["target"], "trash.purge_expired")
		self.assertFalse(sonuc["called"])

	def test_legal_hold_acikken_upstream_reddedilir(self) -> None:
		politika = ret.RetentionPolicy.from_mapping({"legal_hold": {"enabled": True}})
		zarf = ret.UpstreamPurge(politika)
		for sonuc in zarf.run_all(dry_run=False):
			with self.subTest(hedef=sonuc["target"]):
				self.assertFalse(sonuc["called"])
				self.assertEqual(sonuc["blocked_by"], ret.REASON_LEGAL_HOLD)

	def test_politika_gunleri_zarfa_gecer(self) -> None:
		politika = ret.RetentionPolicy.from_mapping(
			{"soft_delete": {"trash_retention_days": 7, "archive_retention_days": 3}}
		)
		zarf = ret.UpstreamPurge(politika)
		self.assertEqual(zarf.policy.trash_retention_days, 7)
		self.assertEqual(zarf.policy.archive_retention_days, 3)

	def test_run_all_sirasi_arsiv_cop_yedek(self) -> None:
		hedefler = [s["target"] for s in ret.UpstreamPurge().run_all(dry_run=True)]
		self.assertEqual(
			hedefler, ["archive.purge_expired", "trash.purge_expired", "backup.prune"]
		)


if __name__ == "__main__":  # pragma: no cover
	unittest.main(verbosity=2)
