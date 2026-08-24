"""T-051 (şartname) — Medya Depolama Ayarları: şifreleme, izolasyon, sızıntı.

Bu modül dört soruyu GERÇEK veritabanına sorar (`FrappeTestCase`); sınanan şey
Frappe'nin şifreleme ve izin motorlarıdır, stub'lanamaz.

  1. **Şifreleme.** `Password` fieldtype'ı sırrı gerçekten şifreliyor mu —
     `tabSingles` ve `__Auth` ham okunduğunda düz metin görünüyor mu.
  2. **İzolasyon ÜÇ YÖNLÜ.** Media Superadmin okur+yazar · satıcı OKUYAMAZ
     (yalnız yazamaz değil) · Guest reddedilir.
  3. **Sızıntı yok.** Bağlantı testinin yanıtında ve durum ucunun çıktısında
     sır geçmiyor.
  4. **Alan adları fabrikayla uyumlu.** DocType alanı yeniden adlandırılırsa
     `StorageSettings.from_doctype` sessizce boş ayar üretirdi; test bunu
     düşürür.

VACUITY: 5. gruptaki testler izin kancası/DocPerm kaldırıldığında KIRMIZI
olmak zorundadır. Ölçüldü — bkz. docs/reports/25-t051-depolama-ayarlari.md §5.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_media_storage_settings
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core import permissions
from tradehub_core.media.pipeline.storage import MODE_LOCAL, StorageSettings
from tradehub_core.tradehub_core.doctype.media_storage_settings import (
	media_storage_settings as mss,
)

DOCTYPE = mss.DOCTYPE
ENGINE_DOCTYPE = "Media Engine Settings"

#: Testin yazdığı sır. DB'de bu dizenin ham hâliyle görünmesi = başarısızlık.
PROBE_SECRET = "TH-PROBE-SECRET-6f2b9c41d7e8"
PROBE_IMG_KEY = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
PROBE_IMG_SALT = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


class MediaStorageSettingsTests(FrappeTestCase):
	# -- fixture --------------------------------------------------------

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(lambda: frappe.set_user("Administrator"))
		self._snapshot = self._read_singles()
		self.addCleanup(self._restore_singles)

	def _read_singles(self) -> dict:
		rows = frappe.db.sql(
			"SELECT `field`, `value` FROM `tabSingles` WHERE `doctype` = %s", (DOCTYPE,)
		)
		return dict(rows)

	def _restore_singles(self) -> None:
		"""Ayarı test öncesi hâline döndür + test sırlarını `__Auth`'tan sil."""
		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", (DOCTYPE,))
		for alan, deger in self._snapshot.items():
			frappe.db.sql(
				"INSERT INTO `tabSingles` (`doctype`, `field`, `value`) VALUES (%s, %s, %s)",
				(DOCTYPE, alan, deger),
			)
		frappe.db.sql("DELETE FROM `__Auth` WHERE doctype = %s", (DOCTYPE,))
		frappe.clear_document_cache(DOCTYPE, DOCTYPE)
		frappe.db.commit()

	def _user(self, tag: str, roles: tuple[str, ...]) -> str:
		email = f"t051-{tag}-{frappe.generate_hash(length=8)}@test.local"
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": tag,
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop_user(doc.name))
		return doc.name

	def _drop_user(self, name: str) -> None:
		if frappe.db.exists("User", name):
			frappe.delete_doc("User", name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def _write_settings(self, **alanlar) -> "frappe.Document":
		doc = frappe.get_single(DOCTYPE)
		doc.backend = MODE_LOCAL
		doc.s3_endpoint = "http://minio:9000"
		doc.s3_region = "us-east-1"
		doc.s3_bucket = "t051-probe"
		doc.s3_access_key = "probe-access-key"
		doc.s3_secret_key = PROBE_SECRET
		doc.imgproxy_key = PROBE_IMG_KEY
		doc.imgproxy_salt = PROBE_IMG_SALT
		for alan, deger in alanlar.items():
			setattr(doc, alan, deger)
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return doc

	# -- 1. Şifreleme ---------------------------------------------------

	def test_gizli_anahtar_veritabaninda_duz_metin_degil(self):
		self._write_settings()

		singles = frappe.db.sql(
			"SELECT `value` FROM `tabSingles` WHERE `doctype` = %s AND `field` = %s",
			(DOCTYPE, "s3_secret_key"),
		)
		ham_singles = singles[0][0] if singles else ""
		self.assertNotIn(PROBE_SECRET, ham_singles or "", "sır tabSingles'ta DÜZ METİN")

		auth = frappe.db.sql(
			"SELECT `password` FROM `__Auth` WHERE doctype = %s AND fieldname = %s",
			(DOCTYPE, "s3_secret_key"),
		)
		self.assertTrue(auth, "__Auth satırı yazılmamış — sır hiç saklanmamış olabilir")
		self.assertNotIn(PROBE_SECRET, auth[0][0] or "", "sır __Auth'ta DÜZ METİN")

		# Şifrelendi ama GERİ OKUNABİLİYOR olmalı; aksi hâlde ayar işe yaramaz.
		doc = frappe.get_single(DOCTYPE)
		self.assertEqual(doc.get_password("s3_secret_key"), PROBE_SECRET)

	def test_tum_sirlar_password_fieldtype(self):
		meta = frappe.get_meta(DOCTYPE)
		for alan in mss.SECRET_FIELDS:
			self.assertEqual(
				meta.get_field(alan).fieldtype,
				"Password",
				f"{alan} Password değil — Data olsaydı düz metin dönerdi",
			)

	# -- 2. İzolasyon (üç yönlü) ----------------------------------------

	def test_media_superadmin_okur_ve_yazar(self):
		user = self._user("super", ("Media Superadmin",))
		self.assertTrue(frappe.has_permission(DOCTYPE, "read", user=user))
		self.assertTrue(frappe.has_permission(DOCTYPE, "write", user=user))
		frappe.set_user(user)
		self.assertIn("plan", mss.get_storage_status())

	def test_satici_OKUYAMAZ(self):
		"""Yalnız 'yazamaz' değil — sır taşıyan ekranda okuma da kapalı."""
		for rol in ("Marketplace Seller", "Seller", "Seller Owner", "Buyer", "Customer"):
			user = self._user(rol.replace(" ", "-").lower(), (rol,))
			self.assertFalse(
				frappe.has_permission(DOCTYPE, "read", user=user),
				f"{rol} ayarı OKUYABİLİYOR",
			)
			self.assertFalse(frappe.has_permission(DOCTYPE, "write", user=user))
			self.assertFalse(
				permissions.media_storage_settings_has_permission(None, "read", user),
				f"{rol} için has_permission kancası True döndü",
			)

	def test_satici_rest_ucundan_da_okuyamaz(self):
		user = self._user("seller-rest", ("Marketplace Seller",))
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			frappe.client.get(DOCTYPE, DOCTYPE)

	def test_satici_whitelist_uclarindan_reddedilir(self):
		user = self._user("seller-api", ("Marketplace Seller",))
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			mss.get_storage_status()
		with self.assertRaises(frappe.PermissionError):
			mss.test_connection("s3")

	def test_guest_reddedilir(self):
		self.assertFalse(frappe.has_permission(DOCTYPE, "read", user="Guest"))
		self.assertFalse(permissions.media_storage_settings_has_permission(None, "read", "Guest"))
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			mss.get_storage_status()

	def test_docperm_listesinde_yalnizca_media_superadmin_var(self):
		roller = {
			p.role for p in frappe.get_meta(DOCTYPE).permissions
		}
		self.assertEqual(roller, set(mss.ALLOWED_ROLES))
		self.assertNotIn("Marketplace Seller", roller)
		self.assertNotIn("Buyer", roller)

	def test_iki_settings_single_ayni_kesin_rol_kapisini_kullanir(self):
		"""T-040: System Manager dahil yalnız Media Superadmin dışarıda kalır."""
		for doctype in (DOCTYPE, ENGINE_DOCTYPE):
			with self.subTest(doctype=doctype):
				self.assertEqual(
					{p.role for p in frappe.get_meta(doctype).permissions},
					{"Media Superadmin"},
				)

		superadmin = self._user("settings-super", ("Media Superadmin",))
		system_manager = self._user("settings-system", ("System Manager",))
		seller = self._user("settings-seller", ("Marketplace Seller",))
		for doctype in (DOCTYPE, ENGINE_DOCTYPE):
			with self.subTest(doctype=doctype, role="Media Superadmin"):
				self.assertTrue(frappe.has_permission(doctype, "read", user=superadmin))
			with self.subTest(doctype=doctype, role="System Manager"):
				self.assertFalse(frappe.has_permission(doctype, "read", user=system_manager))
			with self.subTest(doctype=doctype, role="Marketplace Seller"):
				self.assertFalse(frappe.has_permission(doctype, "read", user=seller))

	# -- 3. Sızıntı yok --------------------------------------------------

	def test_baglanti_testi_sir_dondurmez(self):
		self._write_settings()
		frappe.set_user("Administrator")
		for hedef in ("s3", "cdn", "imgproxy"):
			sonuc = mss.test_connection(hedef)
			govde = json.dumps(sonuc, ensure_ascii=False)
			self.assertNotIn(PROBE_SECRET, govde, f"{hedef} yanıtında S3 sırrı var")
			self.assertNotIn(PROBE_IMG_KEY, govde, f"{hedef} yanıtında imgproxy anahtarı var")
			self.assertNotIn(PROBE_IMG_SALT, govde, f"{hedef} yanıtında imgproxy tuzu var")

	def test_durum_ucu_sir_dondurmez(self):
		self._write_settings()
		govde = json.dumps(mss.get_storage_status(), ensure_ascii=False, default=str)
		self.assertNotIn(PROBE_SECRET, govde)
		self.assertNotIn(PROBE_IMG_KEY, govde)

	def test_maskeleme_sirri_gercekten_siler(self):
		"""Uçtan uca testler sırrı hiç üretmeyebilir; süzgeç ayrıca sınanır."""
		govde = {"steps": [{"detail": f"SignatureDoesNotMatch key={PROBE_SECRET}"}]}
		temiz = mss._maskele(govde, (PROBE_SECRET, PROBE_IMG_KEY))
		self.assertNotIn(PROBE_SECRET, json.dumps(temiz))
		self.assertIn("***", temiz["steps"][0]["detail"])

	def test_hata_yolunda_sir_ne_yanita_ne_loga_dusmez(self):
		"""Fabrika sırrı taşıyan bir istisna atarsa yanıt ve Error Log temiz kalmalı."""
		self._write_settings()
		orijinal = mss.build_storage

		def _patlat(*args, **kwargs):
			raise RuntimeError(f"boto3 imza hatasi: secret={PROBE_SECRET}")

		mss.build_storage = _patlat
		self.addCleanup(lambda: setattr(mss, "build_storage", orijinal))

		sonuc = mss.get_storage_status()
		self.assertNotIn(PROBE_SECRET, json.dumps(sonuc, ensure_ascii=False, default=str))
		self.assertIn("***", sonuc["plan"]["error"])

		frappe.db.commit()
		loglar = frappe.db.sql(
			"""SELECT error FROM `tabError Log` ORDER BY creation DESC LIMIT 10""",
		)
		self.assertNotIn(PROBE_SECRET, " ".join((r[0] or "") for r in loglar), "sır Error Log'a düştü")

	def test_denetim_kaydi_yazilir_ve_sir_tasimaz(self):
		self._write_settings(change_reason="T-051 testi")
		satirlar = frappe.db.sql(
			"""SELECT context FROM `tabAuthorization Decision Log`
			   WHERE action = %s ORDER BY creation DESC LIMIT 5""",
			(mss.ACTION_STORAGE_SETTINGS,),
			as_dict=True,
		)
		self.assertTrue(satirlar, "ayar değişikliği denetim kaydına yazılmadı")
		birlesik = " ".join((r.get("context") or "") for r in satirlar)
		self.assertNotIn(PROBE_SECRET, birlesik, "denetim kaydında sır var")
		self.assertIn("s3_bucket", birlesik, "değişen alanlar kayda girmemiş")

	# -- 4. Alan adları fabrikayla uyumlu -------------------------------

	def test_alan_adlari_fabrikanin_okudugu_adlar(self):
		doc = self._write_settings()
		ayar = StorageSettings.from_doctype(doc.storage_mapping(), site_path="/tmp/t051")
		self.assertEqual(ayar.mode, MODE_LOCAL)
		self.assertEqual(ayar.s3.bucket, "t051-probe")
		self.assertEqual(ayar.s3.region, "us-east-1")
		self.assertEqual(ayar.s3.endpoint_url, "http://minio:9000")
		self.assertEqual(ayar.s3.access_key_id, "probe-access-key")
		self.assertEqual(ayar.s3.secret_access_key, PROBE_SECRET)

	def test_saklama_alanlari_politikaya_baglanir(self):
		from tradehub_core.media.pipeline.storage.retention import RetentionPolicy

		doc = self._write_settings(
			keep_originals=0,
			original_local_days=45,
			original_then_action="delete",
			derivative_unused_days=120,
			trash_retention_days=7,
		)
		politika = RetentionPolicy.from_mapping(doc.retention_mapping())
		self.assertFalse(politika.original.keep_forever)
		self.assertEqual(politika.original.local_days, 45)
		self.assertEqual(politika.original.then, "delete")
		self.assertEqual(politika.derivative.unused_after_days, 120)
		self.assertEqual(politika.trash_retention_days, 7)

	# -- 5. Doğrulama kapıları ------------------------------------------

	def test_s3_kipi_onay_kutusu_olmadan_kaydedilemez(self):
		with self.assertRaises(frappe.ValidationError):
			self._write_settings(backend="s3", blocker_ack=0)

	def test_s3_kipi_kovasiz_kaydedilemez(self):
		with self.assertRaises(frappe.ValidationError):
			self._write_settings(backend="s3", blocker_ack=1, s3_bucket="")

	def test_saklama_politikasi_tutarsizsa_reddedilir(self):
		# keep_forever=0 iken local_days>=1 zorunlu (OriginalRetention.validate).
		with self.assertRaises(frappe.ValidationError):
			self._write_settings(keep_originals=0, original_local_days=0)

	def test_imgproxy_anahtari_tuzsuz_kaydedilemez(self):
		with self.assertRaises(frappe.ValidationError):
			self._write_settings(imgproxy_salt="")
