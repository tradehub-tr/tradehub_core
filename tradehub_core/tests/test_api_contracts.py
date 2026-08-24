"""Faz 8 — API sözleşme testi (T-080…T-085).

Bu dosya iki ayrı işi yapar ve ikisini karıştırmamak önemlidir:

  1. **Sözleşme kilidi.** `docs/api/openapi.yaml` ile `tradehub_core/media/pipeline/api/spec.py`
     arasındaki sapmayı ve belge ↔ kod arasındaki İKİ YÖNLÜ eşleşmeyi
     doğrular. Belgede olup kodda olmayan da, kodda olup belgede olmayan da
     testi düşürür.
  2. **Davranış kanıtı.** Sözleşmenin sert cümlelerinin gerçekten uygulandığını
     ölçer: "aynı içerik hashi ile ikinci finalize yeni varlık ÜRETMEZ",
     "manifest yalnız üretilmiş genişlikleri gösterir", "yayınlanmamış → 404",
     "0-1 dışındaki koordinat REDDEDİLİR".

BAĞIMLILIKLAR
-------------
`frappe` GEREKMEZ — `tradehub_core/media/pipeline/api/` altındaki hiçbir modül `import frappe`
yapmaz. Gerçek görsel gerektiren testler `tradehub_core/tests/fixtures/media/images/`
altındaki altın fixture'ları kullanır; Pillow yoksa o testler ATLANIR (sahte
"geçti" verilmez).

`PyYAML` yerelde kurulu değil, bench ortamında var (6.0.3 — ÖLÇÜLDÜ). Bu
yüzden YAML doğrulaması iki katmanlıdır: bayt eşitliği HER ZAMAN koşar,
ayrıştırma doğrulaması yalnız PyYAML varsa.

Koşum:

    python3 -m unittest tests.test_api_contracts -v
"""

from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
	sys.path.insert(0, str(KOK))

from tradehub_core.media.pipeline.api import admin as admin_api  # noqa: E402
from tradehub_core.media.pipeline.api import crop as crop_api  # noqa: E402
from tradehub_core.media.pipeline.api import delivery as delivery_api  # noqa: E402
from tradehub_core.media.pipeline.api import envelope as env  # noqa: E402
from tradehub_core.media.pipeline.api import spec  # noqa: E402
from tradehub_core.media.pipeline.api import upload as upload_api  # noqa: E402
from tradehub_core.media.pipeline.contracts import errors as cerr  # noqa: E402
from tradehub_core.media.pipeline.delivery import manifest as manifest_mod  # noqa: E402
from tradehub_core.media.pipeline.delivery import signed as signed_mod  # noqa: E402
from tradehub_core.media.pipeline.image import render as render_mod  # noqa: E402
from tradehub_core.media.pipeline.image import reprocess as reprocess_mod  # noqa: E402

FIXTURE_DIR = KOK / "tradehub_core" / "tests" / "fixtures" / "media" / "images"
KOTU_DIR = KOK / "tradehub_core" / "tests" / "fixtures" / "malicious"
URUN_GORSELI = FIXTURE_DIR / "ok_product_1x1_2400.jpg"

SATICI = env.Principal(user="satici@ornek.com", roles=("Seller",), store="SELLER-001")
BASKA_SATICI = env.Principal(user="rakip@ornek.com", roles=("Seller",), store="SELLER-002")
YONETICI = env.Principal(user="admin@ornek.com", roles=("Marketplace Admin",), store="")
MISAFIR = env.ANONYMOUS


def pyyaml_var() -> bool:
	try:
		import yaml  # noqa: F401

		return True
	except Exception:
		return False


def pillow_var() -> bool:
	try:
		from PIL import Image  # noqa: F401

		return True
	except Exception:
		return False


# ═══════════════════════════════════════════════════════════════════════
# 1. T-080 — OpenAPI belgesi
# ═══════════════════════════════════════════════════════════════════════


class OpenApiBelgesiTesti(unittest.TestCase):
	"""Belgenin kendisi geçerli mi ve koda bağlı mı."""

	@classmethod
	def setUpClass(cls):
		cls.doc = spec.build_document()

	def test_yapisal_dogrulama_temiz(self):
		"""Kırık `$ref`, tekrarlı `operationId`, yanıtsız uç YOK."""
		bulgular = spec.validate_document(self.doc)
		self.assertEqual(bulgular, [], f"OpenAPI bulguları: {bulgular}")

	def test_surum_3_1(self):
		self.assertEqual(self.doc["openapi"], "3.1.0")
		self.assertEqual(self.doc["info"]["version"], spec.API_VERSION)

	def test_her_ucun_hata_yaniti_var(self):
		"""Her uç en az 400/401/403/404/500 tanımlar — istemci kör kalmaz."""
		for yol, yontem, op in spec.operations(self.doc):
			for kod in ("400", "401", "403", "404", "500"):
				self.assertIn(kod, op["responses"], f"{yontem.upper()} {yol}: {kod} yok")

	def test_hata_kodu_katalogu_zarfla_uyumlu(self):
		"""Katalogdaki her HTTP durumu, zarfın ürettiği bir durumdur."""
		self.assertGreaterEqual(len(self.doc["x-error-codes"]), 15)
		for satir in self.doc["x-error-codes"]:
			self.assertIn("code", satir)
			self.assertIn("retryable", satir)
			self.assertIsInstance(satir["status"], int)

	def test_guvenlik_semasi_var(self):
		semalar = self.doc["components"]["securitySchemes"]
		self.assertIn("frappeToken", semalar)
		self.assertIn("frappeSession", semalar)


class YamlSapmaTesti(unittest.TestCase):
	"""Diskteki YAML ile üretilen belge AYNI mı."""

	def test_dosya_var(self):
		self.assertTrue(spec.yaml_path().is_file(), f"{spec.yaml_path()} yok — `spec.write_yaml()` çalıştırın")

	def test_bayt_esitligi(self):
		"""ELLE DÜZENLENMİŞ ya da ESKİMİŞ YAML testi düşürür.

		Bu testin kırılması bir hata değil, bir HATIRLATMADIR: `spec.py`
		değişti, `docs/api/openapi.yaml` yeniden üretilmedi. Çözüm:
		`python3 -c "from tradehub_core.media.pipeline.api import spec; spec.write_yaml()"`
		"""
		diskte = spec.yaml_path().read_text(encoding="utf-8")
		uretilen = spec.dump_yaml(spec.build_document())
		self.assertEqual(
			diskte,
			uretilen,
			"docs/api/openapi.yaml güncel değil; `spec.write_yaml()` ile yeniden üretin.",
		)

	def test_uretim_deterministik(self):
		"""Aynı belge iki kez basıldığında aynı baytlar."""
		self.assertEqual(spec.dump_yaml(spec.build_document()), spec.dump_yaml(spec.build_document()))

	@unittest.skipUnless(pyyaml_var(), "PyYAML kurulu değil (yerelde yok, bench'te var)")
	def test_gercek_yaml_ayristiricisiyla_tur_atlar(self):
		"""Kendi yazıcımızın çıktısı PyYAML ile OKUNDUĞUNDA belgeyle aynı mı.

		Kendi yazıcımızı kendi okuyucumuzla doğrulamak bir şey kanıtlamazdı;
		bağımsız bir ayrıştırıcı gerekir.
		"""
		import yaml

		okunan = yaml.safe_load(spec.yaml_path().read_text(encoding="utf-8"))
		beklenen = json.loads(json.dumps(spec.build_document(), ensure_ascii=False))
		self.assertEqual(okunan, beklenen)


class BelgeKodBagiTesti(unittest.TestCase):
	"""`x-python` hedefleri ile gerçek kod arasındaki İKİ YÖNLÜ kilit."""

	API_SINIFLARI = (
		("tradehub_core.media.pipeline.api.upload.UploadApi", upload_api.UploadApi),
		("tradehub_core.media.pipeline.api.crop.CropApi", crop_api.CropApi),
		("tradehub_core.media.pipeline.api.delivery.DeliveryApi", delivery_api.DeliveryApi),
		("tradehub_core.media.pipeline.api.admin.AdminApi", admin_api.AdminApi),
	)

	def test_her_ucun_python_hedefi_cozulur(self):
		for yol, yontem, op in spec.operations():
			hedef = op["x-python"]
			modul_yolu, sinif_adi, metot = hedef.rsplit(".", 2)
			modul = importlib.import_module(modul_yolu)
			sinif = getattr(modul, sinif_adi, None)
			self.assertIsNotNone(sinif, f"{hedef}: sınıf yok ({yontem.upper()} {yol})")
			fn = getattr(sinif, metot, None)
			self.assertTrue(callable(fn), f"{hedef}: çağrılabilir metot yok ({yontem.upper()} {yol})")

	def test_koddaki_her_uc_belgede(self):
		"""Kodda uç var, belgede yok → sözleşme dışı yüzey. Testi düşürür."""
		belgedekiler = {op["x-python"] for _y, _m, op in spec.operations()}
		for tam_ad, sinif in self.API_SINIFLARI:
			for metot in sinif.ENDPOINTS:
				self.assertIn(
					f"{tam_ad}.{metot}",
					belgedekiler,
					f"{tam_ad}.{metot} kodda var ama `docs/api/openapi.yaml`'da yok",
				)

	def test_belgedeki_her_uc_ENDPOINTS_listesinde(self):
		"""Belgede uç var, `ENDPOINTS` listesinde yok → liste eskimiş."""
		listelenen = {
			f"{tam_ad}.{m}" for tam_ad, sinif in self.API_SINIFLARI for m in sinif.ENDPOINTS
		}
		for _yol, _yontem, op in spec.operations():
			self.assertIn(op["x-python"], listelenen, f"{op['x-python']} ENDPOINTS listesinde yok")

	def test_uc_sayisi(self):
		"""21 uç: 5 yükleme + 4 kırpma + 3 teslim + 9 yönetim."""
		self.assertEqual(len(spec.operations()), 21)


# ═══════════════════════════════════════════════════════════════════════
# 2. Zarf — HTTP eşlemesi, ETag, yetki
# ═══════════════════════════════════════════════════════════════════════


class ZarfTesti(unittest.TestCase):
	def test_hata_hiyerarsisi_http_esler(self):
		beklenen = [
			(cerr.PolicyViolation("x"), 422),
			(cerr.PolicyNotFound("x"), 404),
			(cerr.ObjectNotFound("x"), 404),
			(cerr.StorageConflict("x"), 409),
			(cerr.StorageError("x"), 503),
			(cerr.OversizedImage("x"), 413),
			(cerr.UnsupportedFormat("x"), 415),
			(cerr.DecodeError("x"), 400),
			(cerr.ProbeUnavailable("x"), 503),
			(cerr.NoProfileAvailable("x"), 404),
		]
		for hata, durum in beklenen:
			self.assertEqual(env.http_status_for(hata), durum, type(hata).__name__)

	def test_bilinmeyen_istisna_500_ve_mesaj_sizmaz(self):
		yanit = env.error_response(RuntimeError("/home/frappe/gizli/yol.jpg"))
		self.assertEqual(yanit.status, 500)
		self.assertNotIn("gizli", json.dumps(yanit.body, ensure_ascii=False))
		self.assertEqual(yanit.body["error_code"], "media_internal")

	def test_retryable_http_durumundan_bagimsiz(self):
		"""503 yeniden denenir, 422 denenmez — karar bayrakta, durumda değil."""
		self.assertTrue(env.error_response(cerr.ProbeUnavailable("x")).body["retryable"])
		self.assertFalse(env.error_response(cerr.PolicyViolation("x")).body["retryable"])

	def test_etag_anahtar_sirasindan_bagimsiz(self):
		a = {"x": 1, "y": [1, 2], "z": {"b": 2, "a": 1}}
		b = {"z": {"a": 1, "b": 2}, "y": [1, 2], "x": 1}
		self.assertEqual(env.etag_for(a), env.etag_for(b))

	def test_etag_icerik_degisince_degisir(self):
		self.assertNotEqual(env.etag_for({"x": 1}), env.etag_for({"x": 2}))

	def test_etag_eslesmesi_zayif_ve_yildiz(self):
		e = env.etag_for({"x": 1})
		self.assertTrue(env.etag_matches(e, e))
		self.assertTrue(env.etag_matches(e, "W/" + e))
		self.assertTrue(env.etag_matches(e, "*"))
		self.assertTrue(env.etag_matches(e, f'"başka", {e}'))
		self.assertFalse(env.etag_matches(e, '"başka"'))
		self.assertFalse(env.etag_matches(e, ""))

	def test_conditional_get_304_gövdesiz_ama_etagli(self):
		govde = {"a": 1}
		ilk = env.conditional_get(govde, "")
		self.assertEqual(ilk.status, 200)
		ikinci = env.conditional_get(govde, ilk.headers["ETag"])
		self.assertEqual(ikinci.status, 304)
		self.assertIsNone(ikinci.body)
		self.assertEqual(ikinci.headers["ETag"], ilk.headers["ETag"])

	def test_etag_basligi_dogru_yazimla(self):
		"""`Etag` değil `ETag`. İstemci sözlükten ADIYLA okur."""
		self.assertIn("ETag", env.ok({"a": 1}, etag='"x"').headers)
		self.assertIn("Cache-Control", env.ok({"a": 1}, cache_control="no-store").headers)

	def test_normalize_koordinat_zorunlu(self):
		self.assertEqual(env.require_unit(0.5, "focal_x"), 0.5)
		for kotu in (1.5, -0.1, 1200, "abc", None):
			with self.assertRaises(env.BadRequest):
				env.require_unit(kotu, "focal_x")

	def test_rol_kapisi_ve_denetim_kancasi(self):
		kayitlar = []
		with self.assertRaises(env.Forbidden):
			env.require_roles(
				SATICI, env.ADMIN_ROLES, scope="test",
				on_denied=lambda p, r, s: kayitlar.append((p.user, tuple(r), s)),
			)
		self.assertEqual(kayitlar, [(SATICI.user, env.ADMIN_ROLES, "test")])

	def test_misafir_401_yetkisiz_403(self):
		with self.assertRaises(env.Unauthorized):
			env.require_auth(MISAFIR)
		with self.assertRaises(env.Forbidden):
			env.require_roles(SATICI, env.ADMIN_ROLES)

	def test_sayfa_boyutu_kelepceleniyor(self):
		self.assertEqual(env.page_params(1, 100000), (1, env.MAX_PAGE_SIZE))

	def test_call_istisnayi_yanita_cevirir(self):
		def patla():
			raise cerr.PolicyNotFound("yok")

		yanit = env.call(patla)
		self.assertEqual(yanit.status, 404)
		self.assertFalse(yanit.ok)


# ═══════════════════════════════════════════════════════════════════════
# 3. T-081 — Yükleme
# ═══════════════════════════════════════════════════════════════════════


@unittest.skipUnless(URUN_GORSELI.is_file(), "fixture yok")
@unittest.skipUnless(pillow_var(), "Pillow yok — künye çıkarılamaz")
class YuklemeTesti(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.icerik = URUN_GORSELI.read_bytes()

	def kur(self):
		sessions = upload_api.InMemorySessionStore(chunk_bytes=256 * 1024)
		assets = upload_api.InMemoryAssetRepository()
		return upload_api.UploadApi(sessions=sessions, assets=assets), assets

	def yukle(self, api, principal=SATICI, ad="urun.jpg", icerik=None):
		"""Tam yükleme akışı: oturum → parçalar → finalize."""
		veri = self.icerik if icerik is None else icerik
		r = api.create_session(principal, slot_key="product.image", file_name=ad, total_bytes=len(veri))
		if r.body.get("duplicate"):
			return r
		uid, cb = r.body["upload_id"], r.body["chunk_bytes"]
		for i in range(r.body["chunk_count"]):
			api.put_chunk(principal, uid, i, veri[i * cb : (i + 1) * cb])
		return api.finalize(principal, uid)

	# ── mutlu yol ──────────────────────────────────────────────────────

	def test_yukleme_varlik_uretir(self):
		api, assets = self.kur()
		r = self.yukle(api)
		self.assertEqual(r.status, 201)
		self.assertTrue(r.body["created"])
		self.assertFalse(r.body["duplicate"])
		self.assertTrue(r.body["decision"]["allow"])
		self.assertEqual(len(assets.rows), 1)

	def test_slot_kaydediliyor(self):
		"""Faz 3'ün açık bıraktığı boşluk: yükleme artık slot taşıyor."""
		api, assets = self.kur()
		r = self.yukle(api)
		kayit = assets.rows[r.body["asset"]]
		self.assertEqual(kayit["slot_key"], "product.image")

	def test_cozunurluk_yaziliyor(self):
		"""Canlı ölçüm: `th_media_width` dolu olan kayıt 2853'te 0. Artık dolu."""
		api, assets = self.kur()
		r = self.yukle(api)
		self.assertGreater(r.body["width"], 0)
		self.assertGreater(r.body["height"], 0)
		self.assertEqual(assets.rows[r.body["asset"]]["width"], r.body["width"])

	def test_durum_eksik_parcalari_bildirir(self):
		api, _ = self.kur()
		r = api.create_session(SATICI, slot_key="product.image", file_name="u.jpg", total_bytes=len(self.icerik))
		uid, cb = r.body["upload_id"], r.body["chunk_bytes"]
		api.put_chunk(SATICI, uid, 0, self.icerik[:cb])
		st = api.status(SATICI, uid)
		self.assertEqual(st.body["received"], [0])
		self.assertEqual(st.body["missing"][0], 1)
		self.assertFalse(st.body["complete"])

	def test_durum_etag_ilerlemeyle_degisir(self):
		api, _ = self.kur()
		r = api.create_session(SATICI, slot_key="product.image", file_name="u.jpg", total_bytes=len(self.icerik))
		uid, cb = r.body["upload_id"], r.body["chunk_bytes"]
		e1 = api.status(SATICI, uid).headers["ETag"]
		self.assertEqual(api.status(SATICI, uid, if_none_match=e1).status, 304)
		api.put_chunk(SATICI, uid, 0, self.icerik[:cb])
		self.assertEqual(api.status(SATICI, uid, if_none_match=e1).status, 200)

	# ── İDEMPOTENSİ: üç kapı ───────────────────────────────────────────

	def test_kapi1_bilinen_hash_oturum_acmaz(self):
		"""K1 — `content_sha256` verilirse ve kayıtlıysa HİÇBİR BAYT taşınmaz."""
		api, assets = self.kur()
		ilk = self.yukle(api)
		sha = ilk.body["content_sha256"]
		r = api.create_session(
			SATICI, slot_key="product.image", file_name="kopya.jpg",
			total_bytes=len(self.icerik), content_sha256=sha,
		)
		self.assertEqual(r.status, 200)
		self.assertTrue(r.body["duplicate"])
		self.assertEqual(r.body["upload_id"], "")
		self.assertEqual(r.body["asset"], ilk.body["asset"])
		self.assertEqual(len(assets.rows), 1)

	def test_kapi2_ayni_oturum_ikinci_finalize(self):
		"""K2 — ağ koptu, istemci `finalize`'ı tekrarladı: aynı varlık, 200."""
		api, assets = self.kur()
		r = api.create_session(SATICI, slot_key="product.image", file_name="u.jpg", total_bytes=len(self.icerik))
		uid, cb = r.body["upload_id"], r.body["chunk_bytes"]
		for i in range(r.body["chunk_count"]):
			api.put_chunk(SATICI, uid, i, self.icerik[i * cb : (i + 1) * cb])
		ilk = api.finalize(SATICI, uid)
		ikinci = api.finalize(SATICI, uid)
		self.assertEqual(ilk.status, 201)
		self.assertEqual(ikinci.status, 200)
		self.assertFalse(ikinci.body["created"])
		self.assertEqual(ikinci.body["asset"], ilk.body["asset"])
		self.assertEqual(len(assets.rows), 1)

	def test_kapi3_farkli_oturum_ayni_icerik(self):
		"""K3 — hash bildirilmeden, ayrı oturumdan aynı dosya: YENİ VARLIK YOK."""
		api, assets = self.kur()
		ilk = self.yukle(api, ad="urun.jpg")
		ikinci = self.yukle(api, ad="bambaska-ad.jpg")
		self.assertEqual(ikinci.status, 200)
		self.assertFalse(ikinci.body["created"])
		self.assertTrue(ikinci.body["duplicate"])
		self.assertEqual(ikinci.body["asset"], ilk.body["asset"])
		self.assertEqual(len(assets.rows), 1, "aynı içerik ikinci kaydı açtı")

	def test_yaris_kosulunda_tek_varlik(self):
		"""İki eşzamanlı `finalize` — ikisi de aynı varlığı görür (INV-06).

		`create` tekillik ihlali atar; `idempotent_create` bunu hata değil,
		"diğer istek kazandı" olarak yorumlamalı.
		"""
		api, assets = self.kur()
		ilk = self.yukle(api)
		sha = ilk.body["content_sha256"]
		asil = assets.find_by_content_hash

		# Yarışı taklit et: "yok" de, sonra yazmaya çalışırken çakış.
		cagri = {"n": 0}

		def yaris(h, *, store=""):
			cagri["n"] += 1
			if cagri["n"] == 1:
				return None
			return asil(h, store=store)

		assets.find_by_content_hash = yaris
		try:
			kayit, yeni = __import__(
				"tradehub_core.media.pipeline.core.dedup", fromlist=["dedup"]
			).idempotent_create(
				sha,
				lambda: assets.create({"content_sha256": sha}),
				lambda h: assets.find_by_content_hash(h),
				assets.is_conflict,
			)
		finally:
			assets.find_by_content_hash = asil
		self.assertFalse(yeni)
		self.assertEqual(kayit, ilk.body["asset"])
		self.assertEqual(len(assets.rows), 1)

	# ── ret yolları ────────────────────────────────────────────────────

	def test_bilinmeyen_slot_404(self):
		api, _ = self.kur()
		yanit = env.call(
			api.create_session, SATICI, slot_key="olmayan.slot", file_name="u.jpg", total_bytes=10
		)
		self.assertEqual(yanit.status, 404)
		self.assertEqual(yanit.body["error_code"], "media_policy_not_found")

	def test_boyut_tavani_oturum_acilmadan(self):
		"""413 — 26 MB tavanı aşan dosyanın tek baytı bile taşınmaz."""
		api, _ = self.kur()
		yanit = env.call(
			api.create_session, SATICI, slot_key="product.image",
			file_name="dev.jpg", total_bytes=500 * 1024 * 1024,
		)
		self.assertEqual(yanit.status, 413)
		self.assertTrue(yanit.body["error_code"].startswith("product_image_"))

	def test_politika_ihlali_422_ve_slot_onekli_kod(self):
		kotu = KOTU_DIR / "polyglot_png_as.jpg"
		if not kotu.is_file():
			self.skipTest("kötücül fixture yok")
		api, assets = self.kur()
		r = api.create_session(
			SATICI, slot_key="product.image", file_name="kotu.jpg", total_bytes=kotu.stat().st_size
		)
		uid, cb = r.body["upload_id"], r.body["chunk_bytes"]
		veri = kotu.read_bytes()
		for i in range(r.body["chunk_count"]):
			api.put_chunk(SATICI, uid, i, veri[i * cb : (i + 1) * cb])
		yanit = env.call(api.finalize, SATICI, uid)
		self.assertEqual(yanit.status, 422)
		self.assertTrue(yanit.body["error_code"].startswith("product_image_"))
		self.assertFalse(yanit.body["retryable"])
		self.assertTrue(yanit.body["details"]["violations"])
		self.assertEqual(len(assets.rows), 0, "reddedilen dosya kayıt açtı")

	def test_hash_uyusmazligi_400(self):
		api, _ = self.kur()
		sahte = "0" * 64
		r = api.create_session(
			SATICI, slot_key="product.image", file_name="u.jpg",
			total_bytes=len(self.icerik), content_sha256=sahte,
		)
		uid, cb = r.body["upload_id"], r.body["chunk_bytes"]
		for i in range(r.body["chunk_count"]):
			api.put_chunk(SATICI, uid, i, self.icerik[i * cb : (i + 1) * cb])
		yanit = env.call(api.finalize, SATICI, uid)
		self.assertEqual(yanit.status, 400)
		self.assertEqual(yanit.body["error_code"], "media_hash_mismatch")

	def test_baska_magaza_oturuma_dokunamaz(self):
		api, _ = self.kur()
		r = api.create_session(SATICI, slot_key="product.image", file_name="u.jpg", total_bytes=len(self.icerik))
		uid = r.body["upload_id"]
		self.assertEqual(env.call(api.status, BASKA_SATICI, uid).status, 404)
		self.assertEqual(env.call(api.finalize, BASKA_SATICI, uid).status, 404)

	def test_magazasiz_kullanici_403(self):
		api, _ = self.kur()
		yanit = env.call(
			api.create_session, env.Principal(user="x@y", roles=("Seller",)),
			slot_key="product.image", file_name="u.jpg", total_bytes=10,
		)
		self.assertEqual(yanit.status, 403)
		self.assertEqual(yanit.body["error_code"], "media_store_required")

	def test_misafir_401(self):
		api, _ = self.kur()
		yanit = env.call(
			api.create_session, MISAFIR, slot_key="product.image", file_name="u.jpg", total_bytes=10
		)
		self.assertEqual(yanit.status, 401)

	# ── abort ──────────────────────────────────────────────────────────

	def test_abort_idempotent(self):
		api, _ = self.kur()
		r = api.create_session(SATICI, slot_key="product.image", file_name="u.jpg", total_bytes=len(self.icerik))
		uid = r.body["upload_id"]
		self.assertEqual(api.abort(SATICI, uid).status, 204)
		self.assertEqual(api.abort(SATICI, uid).status, 204, "ikinci iptal hata verdi")
		self.assertEqual(api.abort(SATICI, "a" * 24).status, 204, "bilinmeyen oturum hata verdi")

	def test_abort_gövdesiz(self):
		api, _ = self.kur()
		r = api.create_session(SATICI, slot_key="product.image", file_name="u.jpg", total_bytes=len(self.icerik))
		self.assertIsNone(api.abort(SATICI, r.body["upload_id"]).body)

	def test_tamamlanmis_oturum_iptal_edilemez(self):
		api, _ = self.kur()
		r = self.yukle(api)
		yanit = env.call(api.abort, SATICI, r.body["upload_id"])
		self.assertEqual(yanit.status, 409)
		self.assertEqual(yanit.body["error_code"], "media_already_finalized")


# ═══════════════════════════════════════════════════════════════════════
# 4. T-082 — Kırpma
# ═══════════════════════════════════════════════════════════════════════


class KirpmaTesti(unittest.TestCase):
	def kur(self, *, icerik=None):
		assets = crop_api.InMemoryAssetReader(
			rows={
				"MA-1": {
					"slot_key": "product.image",
					"width": 2400,
					"height": 2400,
					"owner_store": "SELLER-001",
				}
			},
			blobs={"MA-1": icerik} if icerik else {},
		)
		return crop_api.CropApi(assets=assets, intents=crop_api.InMemoryCropIntents())

	def test_niyet_yoksa_404_degil_ortuk_merkez(self):
		api = self.kur()
		r = api.get_intent(SATICI, "MA-1")
		self.assertEqual(r.status, 200)
		self.assertFalse(r.body["exists"])
		self.assertIsNone(r.body["intent"]["focal_x"])
		self.assertTrue(r.body["windows"])
		self.assertEqual(r.body["windows"][0]["method"], "center")

	def test_her_profil_icin_pencere(self):
		api = self.kur()
		r = api.get_intent(SATICI, "MA-1")
		self.assertEqual(len(r.body["windows"]), len(render_mod.load_profiles("product.image")))
		for p in r.body["windows"]:
			self.assertIsNotNone(p["pixels"])
			self.assertGreater(p["pixels"]["width"], 0)

	def test_odak_yazinca_yontem_degisir(self):
		api = self.kur()
		r = api.save_intent(SATICI, "MA-1", focal_x=0.3, focal_y=0.7)
		self.assertEqual(r.status, 200)
		self.assertAlmostEqual(r.body["intent"]["focal_x"], 0.3)
		self.assertEqual(r.body["windows"][0]["method"], "focal")

	def test_piksel_koordinati_reddedilir(self):
		"""INV-10 — 1200 gibi bir değer düzeltilmez, REDDEDİLİR."""
		api = self.kur()
		yanit = env.call(api.save_intent, SATICI, "MA-1", focal_x=1200, focal_y=800)
		self.assertEqual(yanit.status, 400)
		self.assertEqual(yanit.body["details"]["field"], "focal_x")

	def test_yarim_odak_reddedilir(self):
		api = self.kur()
		self.assertEqual(env.call(api.save_intent, SATICI, "MA-1", focal_x=0.5).status, 400)

	def test_if_match_iyimser_kilit(self):
		api = self.kur()
		ilk = api.get_intent(SATICI, "MA-1")
		etag = ilk.headers["ETag"]
		# Araya başka bir yazma girer.
		api.save_intent(SATICI, "MA-1", focal_x=0.1, focal_y=0.1)
		yanit = env.call(api.save_intent, SATICI, "MA-1", focal_x=0.9, focal_y=0.9, if_match=etag)
		self.assertEqual(yanit.status, 412)

	def test_bilinmeyen_profil_override_reddedilir(self):
		api = self.kur()
		yanit = env.call(
			api.save_intent, SATICI, "MA-1",
			overrides=[{"profile": "olmayan", "x": 0, "y": 0, "w": 0.5, "h": 0.5}],
		)
		self.assertEqual(yanit.status, 400)

	def test_override_kadraji_kazanir(self):
		api = self.kur()
		r = api.save_intent(
			SATICI, "MA-1",
			overrides=[{"profile": "w96", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
		)
		w96 = next(w for w in r.body["windows"] if w["profile"] == "w96")
		self.assertEqual(w96["method"], "override")
		self.assertEqual(w96["priority"], 1)

	def test_guvenli_alan_disari_tasarsa_reddedilir(self):
		api = self.kur()
		yanit = env.call(
			api.save_intent, SATICI, "MA-1",
			safe_area={"x": 0.8, "y": 0.8, "w": 0.5, "h": 0.5},
		)
		self.assertEqual(yanit.status, 400)

	def test_baska_magaza_404(self):
		api = self.kur()
		self.assertEqual(env.call(api.get_intent, BASKA_SATICI, "MA-1").status, 404)

	def test_olmayan_varlik_404(self):
		api = self.kur()
		self.assertEqual(env.call(api.get_intent, SATICI, "YOK").status, 404)

	# ── odak önerisi ───────────────────────────────────────────────────

	def test_kaynak_yoksa_olculmedi_der_hata_vermez(self):
		api = self.kur()
		r = api.suggest_focal(SATICI, "MA-1")
		self.assertEqual(r.status, 200)
		self.assertFalse(r.body["suggestion"]["measured"])
		self.assertEqual(r.body["suggestion"]["confidence"], 0.0)
		self.assertIn(r.body["suggestion"]["reason"], ("source_unavailable", "pillow_unavailable"))

	def test_oneri_kaydedilmez(self):
		api = self.kur(icerik=URUN_GORSELI.read_bytes() if URUN_GORSELI.is_file() else None)
		r = api.suggest_focal(SATICI, "MA-1")
		self.assertFalse(r.body["applied"])
		self.assertFalse(api.get_intent(SATICI, "MA-1").body["exists"])

	@unittest.skipUnless(pillow_var() and URUN_GORSELI.is_file(), "Pillow ya da fixture yok")
	def test_gercek_gorselde_odak_olculur(self):
		api = self.kur(icerik=URUN_GORSELI.read_bytes())
		s = api.suggest_focal(SATICI, "MA-1").body["suggestion"]
		self.assertTrue(s["measured"])
		self.assertEqual(s["reason"], "measured")
		self.assertGreaterEqual(s["focal_x"], 0.0)
		self.assertLessEqual(s["focal_x"], 1.0)
		self.assertFalse(s["threshold_calibrated"], "eşik ÖLÇÜLMEDİ olarak işaretli kalmalı")

	@unittest.skipUnless(pillow_var(), "Pillow yok")
	def test_duz_renkte_kenar_enerjisi_yok(self):
		import io

		from PIL import Image

		tampon = io.BytesIO()
		Image.new("RGB", (64, 64), (200, 200, 200)).save(tampon, format="PNG")
		oneri = crop_api.focal_from_bytes(tampon.getvalue())
		self.assertFalse(oneri.measured)
		self.assertEqual(oneri.reason, crop_api.REASON_FLAT)

	@unittest.skipUnless(pillow_var(), "Pillow yok")
	def test_sol_ustteki_desen_odagi_sola_ceker(self):
		"""Ölçüm gerçekten içeriğe bakıyor mu — kontrol edilebilir bir görselle."""
		import io

		from PIL import Image

		im = Image.new("RGB", (128, 128), (255, 255, 255))
		for y in range(8, 40):
			for x in range(8, 40):
				if (x + y) % 2 == 0:
					im.putpixel((x, y), (0, 0, 0))
		tampon = io.BytesIO()
		im.save(tampon, format="PNG")
		oneri = crop_api.focal_from_bytes(tampon.getvalue())
		self.assertTrue(oneri.measured)
		self.assertLess(oneri.x, 0.5, "odak sola çekilmedi")
		self.assertLess(oneri.y, 0.5, "odak yukarı çekilmedi")

	# ── önizleme ───────────────────────────────────────────────────────

	def test_onizleme_pencere_dondurur(self):
		api = self.kur()
		r = api.preview(SATICI, "MA-1", profile="w96")
		self.assertEqual(r.status, 200)
		self.assertEqual(r.body["window"]["profile"], "w96")
		self.assertIsNone(r.body["image"])

	def test_onizleme_kaydedilmemis_niyeti_kullanir(self):
		api = self.kur()
		r = api.preview(SATICI, "MA-1", profile="w96", intent={"focal_x": 0.2, "focal_y": 0.2})
		self.assertEqual(r.body["window"]["method"], "focal")
		self.assertFalse(api.get_intent(SATICI, "MA-1").body["exists"], "önizleme yazma yaptı")

	def test_bilinmeyen_profil_404(self):
		api = self.kur()
		self.assertEqual(env.call(api.preview, SATICI, "MA-1", profile="yok").status, 404)

	@unittest.skipUnless(pillow_var() and URUN_GORSELI.is_file(), "Pillow ya da fixture yok")
	def test_onizleme_gorsel_uretir(self):
		api = self.kur(icerik=URUN_GORSELI.read_bytes())
		r = api.preview(SATICI, "MA-1", profile="w96", include_image=True)
		self.assertTrue((r.body["image"] or "").startswith("data:image/"))
		self.assertEqual(r.body["image_reason"], "measured")

	def test_gorsel_uretilemezse_pencere_yine_doner(self):
		"""Kadraj saf aritmetiktir; kodlayıcı yoksa da cevap verilebilmeli."""
		api = self.kur()
		r = api.preview(SATICI, "MA-1", profile="w96", include_image=True)
		self.assertEqual(r.status, 200)
		self.assertIsNone(r.body["image"])
		self.assertTrue(r.body["image_reason"])


# ═══════════════════════════════════════════════════════════════════════
# 5. T-083 — Teslim
# ═══════════════════════════════════════════════════════════════════════


PROFILLER = [p.name for p in render_mod.load_profiles("product.image")]
PUBLIC_URL = "/files/ab/abcdef0123456789abcdef0123456789.jpg"
PRIVATE_URL = "/private/files/cd/cdef010203040506070809101112131a.jpg"


class TeslimTesti(unittest.TestCase):
	def kur(self, *, signer=None):
		repo = delivery_api.InMemoryDeliveryRepository(
			rows={
				"MA-TAM": {
					"slot_key": "product.image", "file_url": PUBLIC_URL, "published": True,
					"kind": "image", "width": 2400, "height": 2400, "alt_text": "Ürün",
					"owner_store": "SELLER-001", "available_profiles": list(PROFILLER),
					"version_hash": "v1",
				},
				"MA-KISMI": {
					"slot_key": "product.image", "file_url": PUBLIC_URL, "published": True,
					"kind": "image", "width": 2400, "height": 2400,
					"owner_store": "SELLER-001", "available_profiles": PROFILLER[:2],
				},
				"MA-TASLAK": {
					"slot_key": "product.image", "file_url": PUBLIC_URL, "published": False,
					"kind": "image", "width": 2400, "height": 2400,
					"owner_store": "SELLER-001", "available_profiles": list(PROFILLER),
				},
				"MA-TUREVSIZ": {
					"slot_key": "product.image", "file_url": PUBLIC_URL, "published": True,
					"kind": "image", "width": 2400, "height": 2400,
					"owner_store": "SELLER-001", "available_profiles": [],
				},
				"MA-GIZLI": {
					"slot_key": "document.attachment", "file_url": PRIVATE_URL, "published": True,
					"kind": "image", "width": 1200, "height": 800,
					"owner_store": "SELLER-001", "available_profiles": ["doc_thumb_512"],
				},
			}
		)
		return delivery_api.DeliveryApi(repo=repo, signer=signer)

	# ── kural 1: yalnız üretilmiş genişlikler ──────────────────────────

	def test_manifest_yalnizca_uretilmis_genislikleri_gosterir(self):
		api = self.kur()
		r = api.manifest(MISAFIR, "MA-KISMI")
		self.assertEqual(r.status, 200)
		self.assertEqual(sorted(r.body["available_profiles"]), sorted(PROFILLER[:2]))
		basilan = {v["profile"] for v in r.body["variants"] if v["available"]}
		self.assertEqual(basilan, set(PROFILLER[:2]))
		for kaynak in r.body["sources"]:
			for parca in kaynak["srcset"].split(","):
				url = parca.strip().split(" ")[0]
				self.assertTrue(
					any(f"__{p}." in url for p in PROFILLER[:2]),
					f"üretilmemiş genişlik srcset'e girdi: {url}",
				)

	def test_uretilmemis_genislik_srcsette_yok(self):
		api = self.kur()
		r = api.manifest(MISAFIR, "MA-KISMI")
		tum_srcset = " ".join(k["srcset"] for k in r.body["sources"])
		for p in PROFILLER[2:]:
			self.assertNotIn(f"__{p}.", tum_srcset)

	def test_hic_turev_yoksa_404(self):
		"""Boş `srcset` yazmak yerine hata: sessiz başarısızlık daha kötü."""
		api = self.kur()
		yanit = env.call(api.manifest, MISAFIR, "MA-TUREVSIZ")
		self.assertEqual(yanit.status, 404)
		self.assertEqual(yanit.body["error_code"], "media_no_profile")

	# ── kural 2: yayınlanmamış → 404 ───────────────────────────────────

	def test_yayinlanmamis_404(self):
		api = self.kur()
		yanit = env.call(api.manifest, MISAFIR, "MA-TASLAK")
		self.assertEqual(yanit.status, 404)
		self.assertNotEqual(yanit.status, 403, "403 varlığın var olduğunu doğrular")

	def test_sahip_kendi_taslagini_gorur(self):
		api = self.kur()
		self.assertEqual(api.manifest(SATICI, "MA-TASLAK").status, 200)

	def test_baska_magaza_taslagi_goremez(self):
		api = self.kur()
		self.assertEqual(env.call(api.manifest, BASKA_SATICI, "MA-TASLAK").status, 404)

	def test_private_varlik_misafire_kapali(self):
		api = self.kur()
		self.assertEqual(env.call(api.manifest, MISAFIR, "MA-GIZLI").status, 404)
		self.assertEqual(api.manifest(SATICI, "MA-GIZLI").status, 200)

	# ── kural 3: ETag ──────────────────────────────────────────────────

	def test_etag_ve_304(self):
		api = self.kur()
		ilk = api.manifest(MISAFIR, "MA-TAM")
		self.assertIn("ETag", ilk.headers)
		self.assertEqual(ilk.headers["Cache-Control"], env.CACHE_MANIFEST)
		ikinci = api.manifest(MISAFIR, "MA-TAM", if_none_match=ilk.headers["ETag"])
		self.assertEqual(ikinci.status, 304)
		self.assertIsNone(ikinci.body)

	def test_turev_listesi_degisince_etag_degisir(self):
		api = self.kur()
		e1 = api.manifest(MISAFIR, "MA-TAM").headers["ETag"]
		e2 = api.manifest(MISAFIR, "MA-KISMI").headers["ETag"]
		self.assertNotEqual(e1, e2)

	# ── manifest içeriği ───────────────────────────────────────────────

	def test_icsel_olcu_tasiniyor(self):
		"""CLS koruması (FR-124): kutu oranı bu iki sayıdan rezerve edilir."""
		api = self.kur()
		r = api.manifest(MISAFIR, "MA-TAM")
		self.assertEqual(r.body["width"], 2400)
		self.assertEqual(r.body["height"], 2400)
		self.assertAlmostEqual(r.body["aspect_ratio"], 1.0)

	def test_lcp_adayi_eager(self):
		api = self.kur()
		normal = api.manifest(MISAFIR, "MA-TAM")
		lcp = api.manifest(MISAFIR, "MA-TAM", is_lcp_candidate=True)
		self.assertEqual(normal.body["loading"], "lazy")
		self.assertEqual(lcp.body["loading"], "eager")
		self.assertEqual(lcp.body["fetchpriority"], "high")

	def test_sizes_olculmedigi_soylenir(self):
		"""Boş `sizes` bir eksiklik BİLDİRİMİDİR, varsayılan değil."""
		api = self.kur()
		r = api.manifest(MISAFIR, "MA-TAM")
		self.assertEqual(r.body["sizes"], "")
		self.assertEqual(r.body["sizes_source"], manifest_mod.SIZES_SOURCE_UNMEASURED)

	def test_cagiran_sizes_verebilir(self):
		api = self.kur()
		r = api.manifest(MISAFIR, "MA-TAM", sizes="(min-width: 640px) 296px, 50vw")
		self.assertEqual(r.body["sizes_source"], manifest_mod.SIZES_SOURCE_CALLER)
		self.assertEqual(r.body["sources"][0]["sizes"], "(min-width: 640px) 296px, 50vw")

	def test_bicim_sirasi_avif_once(self):
		api = self.kur()
		r = api.manifest(MISAFIR, "MA-TAM")
		turler = [k["type"] for k in r.body["sources"]]
		self.assertEqual(turler[0], "image/avif")
		self.assertIn("image/webp", turler)

	def test_fallback_orta_basamak(self):
		"""En büyük basamağı `src` yapmak, srcset'siz istemciye en pahalıyı gönderirdi."""
		api = self.kur()
		r = api.manifest(MISAFIR, "MA-TAM")
		self.assertTrue(r.body["src"])
		en_buyuk = f"__{PROFILLER[-1]}."
		self.assertNotIn(en_buyuk, r.body["src"])

	# ── toplu ──────────────────────────────────────────────────────────

	def test_toplu_kismi_basari(self):
		api = self.kur()
		r = api.manifest_batch(MISAFIR, ["MA-TAM", "MA-TASLAK", "YOK"])
		self.assertEqual(r.status, 200)
		self.assertEqual(list(r.body["manifests"]), ["MA-TAM"])
		self.assertEqual(sorted(r.body["missing"]), ["MA-TASLAK", "YOK"])
		self.assertEqual(r.body["requested"], 3)

	def test_toplu_eksik_sebebi_sizdirmaz(self):
		api = self.kur()
		r = api.manifest_batch(MISAFIR, ["MA-TASLAK", "YOK"])
		govde = json.dumps(r.body, ensure_ascii=False)
		self.assertNotIn("published", govde)
		self.assertNotIn("SELLER-001", govde)

	def test_toplu_tekrarlar_tekillesir(self):
		api = self.kur()
		r = api.manifest_batch(MISAFIR, ["MA-TAM", "MA-TAM", "MA-TAM"])
		self.assertEqual(r.body["returned"], 1)
		self.assertEqual(r.body["requested"], 3)

	def test_toplu_tavan(self):
		api = self.kur()
		yanit = env.call(api.manifest_batch, MISAFIR, ["MA-TAM"] * (delivery_api.MAX_BATCH + 1))
		self.assertEqual(yanit.status, 400)
		self.assertEqual(yanit.body["error_code"], "media_batch_too_large")

	def test_toplu_bos_liste_400(self):
		api = self.kur()
		self.assertEqual(env.call(api.manifest_batch, MISAFIR, []).status, 400)

	def test_toplu_lcp_yalniz_bir_varliga(self):
		api = self.kur()
		r = api.manifest_batch(MISAFIR, ["MA-TAM", "MA-KISMI"], lcp_asset="MA-TAM")
		self.assertEqual(r.body["manifests"]["MA-TAM"]["fetchpriority"], "high")
		self.assertEqual(r.body["manifests"]["MA-KISMI"]["fetchpriority"], "")

	# ── imzalı URL ─────────────────────────────────────────────────────

	def test_public_varlik_imzalanmaz(self):
		api = self.kur(signer=signed_mod.signer_from_secret(b"test-anahtari"))
		yanit = env.call(api.signed_url, SATICI, "MA-TAM")
		self.assertEqual(yanit.status, 400)
		self.assertEqual(yanit.body["error_code"], "media_not_private")

	def test_private_varlik_imzalanir_ve_onbelleklenmez(self):
		api = self.kur(signer=signed_mod.signer_from_secret(b"test-anahtari"))
		r = api.signed_url(SATICI, "MA-GIZLI", ttl_seconds=600)
		self.assertEqual(r.status, 200)
		self.assertEqual(r.headers["Cache-Control"], env.CACHE_NEVER)
		self.assertEqual(r.body["ttl_seconds"], 600)
		self.assertIn("sig=", r.body["url"])

	def test_ttl_kelepceleniyor(self):
		api = self.kur(signer=signed_mod.signer_from_secret(b"test-anahtari"))
		uzun = api.signed_url(SATICI, "MA-GIZLI", ttl_seconds=10 ** 9)
		self.assertEqual(uzun.body["ttl_seconds"], signed_mod.MAX_TTL_SECONDS)
		kisa = api.signed_url(SATICI, "MA-GIZLI", ttl_seconds=1)
		self.assertEqual(kisa.body["ttl_seconds"], signed_mod.MIN_TTL_SECONDS)

	def test_imza_dogrulanabilir(self):
		imzalayici = signed_mod.signer_from_secret(b"test-anahtari")
		api = self.kur(signer=imzalayici)
		r = api.signed_url(SATICI, "MA-GIZLI")
		self.assertTrue(imzalayici.verify(r.body["url"]))

	def test_baskasinin_yolu_imzalanmaz(self):
		api = self.kur(signer=signed_mod.signer_from_secret(b"test-anahtari"))
		yanit = env.call(
			api.signed_url, SATICI, "MA-GIZLI", path="/private/files/ff/ffffffffffffffffffffffffffffffff.jpg"
		)
		self.assertEqual(yanit.status, 403)

	def test_kendi_turevi_imzalanir(self):
		api = self.kur(signer=signed_mod.signer_from_secret(b"test-anahtari"))
		turev = "/private/files/cd/cdef010203040506070809101112131a__doc_thumb_512.webp"
		r = api.signed_url(SATICI, "MA-GIZLI", path=turev)
		self.assertEqual(r.status, 200)
		self.assertEqual(r.body["path"], turev)

	def test_anahtar_yoksa_sahte_imza_uretilmez(self):
		api = self.kur(signer=None)
		yanit = env.call(api.signed_url, SATICI, "MA-GIZLI")
		self.assertEqual(yanit.status, 503)
		self.assertEqual(yanit.body["error_code"], "media_no_signing_key")

	def test_imza_ucunda_misafir_401(self):
		api = self.kur(signer=signed_mod.signer_from_secret(b"test-anahtari"))
		self.assertEqual(env.call(api.signed_url, MISAFIR, "MA-GIZLI").status, 401)


class ManifestUreticiTesti(unittest.TestCase):
	"""`ManifestBuilder` — sözleşme uygulaması olarak."""

	def setUp(self):
		self.b = manifest_mod.build_default()
		self.base = manifest_mod.ref_from_url(PUBLIC_URL)

	def test_delivery_manifest_protokolunu_karsilar(self):
		from tradehub_core.media.pipeline.contracts.delivery import DeliveryManifest

		self.assertIsInstance(self.b, DeliveryManifest)

	def test_turev_anahtari_shard_korur(self):
		from tradehub_core.media.pipeline.contracts.delivery import derivative_key

		anahtar = derivative_key(self.base.key, "w96", "webp")
		self.assertEqual(anahtar.shard, self.base.key.shard)
		self.assertTrue(anahtar.name.endswith("__w96.webp"))

	def test_pick_hedefi_karsilayan_en_kucugu_secer(self):
		"""Merdiven: 96, 192, 384, 640, 768, 1280, 1920."""
		self.assertEqual(self.b.pick("product.image", 100, dpr=1.0).width, 192)
		self.assertEqual(self.b.pick("product.image", 96, dpr=1.0).width, 96, "tam denk gelen basamak")
		self.assertEqual(self.b.pick("product.image", 192, dpr=2.0).width, 384, "384 = 192×2")
		self.assertEqual(self.b.pick("product.image", 200, dpr=2.0).width, 640, "400 > 384 → bir üst basamak")

	def test_pick_hicbiri_yetmezse_en_buyugu(self):
		"""Büyütme yerine yetersiz servis — FR-028 ile tutarlı."""
		self.assertEqual(self.b.pick("product.image", 5000, dpr=3.0).width, 1920)

	def test_overshoot_tavana_karsi_olculebilir(self):
		"""Politikadaki `max_overshoot` (1,85) bu sayının tavanı."""
		oran = self.b.overshoot("product.image", 100, dpr=1.0)
		self.assertAlmostEqual(oran, 192 / 100)
		self.assertEqual(self.b.overshoot("product.image", 0), 0.0)

	def test_sizes_bilinmeyen_baglamda_bos(self):
		self.assertEqual(self.b.sizes_attribute("product.image", context="pdp"), "")

	def test_video_manifesti_poster_tasir(self):
		man = self.b.build_video(
			"company.cover_video",
			manifest_mod.ref_from_url("/files/ab/abcdef0123456789abcdef0123456789.mp4"),
			available_renditions=[r.id for r in manifest_mod.video_renditions("company.cover_video")],
		)
		self.assertTrue(man.poster_url)
		self.assertEqual(man.extra["poster_reason"], "derived_from_policy")
		self.assertEqual(man.sources[0].fmt, "webm", "WebM önce gelmeli (role: primary)")

	def test_uretilmemis_video_turevi_404(self):
		with self.assertRaises(cerr.NoProfileAvailable):
			self.b.build_video(
				"company.cover_video",
				manifest_mod.ref_from_url("/files/ab/abcdef0123456789abcdef0123456789.mp4"),
				available_renditions=[],
			)


# ═══════════════════════════════════════════════════════════════════════
# 6. T-084 — Yönetim
# ═══════════════════════════════════════════════════════════════════════


class YonetimTesti(unittest.TestCase):
	def kur(self, **kw):
		return admin_api.AdminApi(**kw)

	def test_dokuz_ucun_hepsi_rol_kapili(self):
		api = self.kur(
			coverage=admin_api.InMemoryCoverageRepository(),
			ledger=reprocess_mod.RenditionLedger(),
			storage_conf={"media_storage_mode": "local", "media_site_path": "/tmp"},
			guard=object(),
		)
		cagrilar = {
			"list_slot_policies": {},
			"get_slot_policy": {"slot_key": "product.image"},
			"validate_policies": {},
			"rendition_matrix": {},
			"evaluate_policy": {"slot_key": "product.image", "probe": {}},
			"delivery_coverage": {},
			"plan_reprocess": {"slot_key": "product.image", "master_sha256": "a" * 64},
			"job_status": {"kind": "media.derive", "target": "x"},
			"storage_plan": {},
		}
		self.assertEqual(set(cagrilar), set(admin_api.AdminApi.ENDPOINTS))
		for ad, kwargs in cagrilar.items():
			fn = getattr(api, ad)
			pozisyonel = (SATICI,) if ad in ("list_slot_policies", "validate_policies",
											 "rendition_matrix", "storage_plan",
											 "delivery_coverage", "evaluate_policy",
											 "plan_reprocess", "job_status") else (SATICI,)
			if ad == "get_slot_policy":
				yanit = env.call(fn, SATICI, kwargs["slot_key"])
			else:
				yanit = env.call(fn, *pozisyonel, **kwargs)
			self.assertEqual(yanit.status, 403, f"{ad} rol kapısı yok")

	def test_politika_listesi_dokuz_slot(self):
		r = self.kur().list_slot_policies(YONETICI)
		self.assertEqual(r.status, 200)
		self.assertEqual(r.body["count"], 9)
		anahtarlar = {s["slot_key"] for s in r.body["slots"]}
		self.assertIn("product.image", anahtarlar)
		self.assertIn("product.video", anahtarlar)

	def test_politika_detayi_kaynak_notlarini_tasir(self):
		r = self.kur().get_slot_policy(YONETICI, "product.image")
		self.assertIn("sources", r.body["policy"])
		self.assertIn("ETag", r.headers)

	def test_bilinmeyen_slot_404(self):
		yanit = env.call(self.kur().get_slot_policy, YONETICI, "yok.slot")
		self.assertEqual(yanit.status, 404)

	def test_dogrulama_gercek_json_semasini_calistirir(self):
		"""Kurulu Draft 2020-12 doğrulayıcısı dokuz politikayı gerçekten okur."""
		r = self.kur().validate_policies(YONETICI)
		self.assertTrue(r.body["schema_validated"])
		self.assertTrue(r.body["schema_note"])
		self.assertEqual(r.body["slot_count"], 9)
		self.assertNotIn("schema_validation", {f["code"] for f in r.body["findings"]})

	def test_dogrulama_gercek_bulgu_uretiyor(self):
		"""Bugünkü politika dosyalarında `en` mesajları eksik — test bunu KİLİTLER.

		Bulgular giderilirse bu test kırılır ve o KIRILMA DOĞRUDUR: sayı
		düştüğünde beklentiyi güncellemek, sessizce "0 bulgu" görmekten iyidir.
		"""
		r = self.kur().validate_policies(YONETICI)
		kodlar = {f["code"] for f in r.body["findings"]}
		self.assertIn("message_parity", kodlar)
		self.assertFalse(r.body["ok"])
		self.assertGreater(r.body["finding_count"], 0)

	def test_matris_toplami(self):
		r = self.kur().rendition_matrix(YONETICI)
		beklenen = sum(len(render_mod.rendition_matrix(s)) for s in render_mod.slot_keys())
		self.assertEqual(r.body["total_renditions"], beklenen)

	def test_matris_olculmus_avif_kalitesini_isaretler(self):
		r = self.kur().rendition_matrix(YONETICI, slot_key="product.image")
		satirlar = r.body["slots"][0]["renditions"]
		avif = [s for s in satirlar if s["format"] == "avif"]
		self.assertTrue(avif)
		self.assertTrue(all(s["quality_calibrated"] for s in avif))
		self.assertEqual({s["quality"] for s in avif}, {61})

	def test_kuru_calistirma_kucuk_gorseli_reddeder(self):
		r = self.kur().evaluate_policy(
			YONETICI,
			slot_key="product.image",
			probe={
				"width": 500, "height": 500, "extension": ".jpg", "kind": "image",
				"detected": "jpeg", "fmt": "JPEG", "readable": True, "byte_size": 10_000,
			},
		)
		self.assertFalse(r.body["allow"])
		self.assertIn("product_image_short_edge_too_small", [v["code"] for v in r.body["violations"]])

	def test_kuru_calistirma_tanimayan_alani_bildirir(self):
		r = self.kur().evaluate_policy(
			YONETICI, slot_key="product.image", probe={"width": 2400, "height": 2400, "uydurma": 1}
		)
		self.assertIn("uydurma", r.body["ignored_fields"])
		self.assertIn("width", r.body["accepted_fields"])

	def test_kapsam_kaynagi_yoksa_503(self):
		yanit = env.call(self.kur().delivery_coverage, YONETICI)
		self.assertEqual(yanit.status, 503)

	def test_kapsam_olcumu(self):
		tam = list(PROFILLER)
		repo = admin_api.InMemoryCoverageRepository(
			rows=[
				{"slot_key": "product.image", "available_profiles": tam},
				{"slot_key": "product.image", "available_profiles": tam[:2]},
				{"slot_key": "product.image", "available_profiles": []},
			]
		)
		r = self.kur(coverage=repo).delivery_coverage(YONETICI)
		self.assertEqual(r.body["total"], 3)
		self.assertEqual(r.body["complete"], 1)
		kova = r.body["by_slot"]["product.image"]
		self.assertEqual(kova["partial"], 1)
		self.assertEqual(kova["empty"], 1)
		self.assertGreater(kova["missing_profile_counts"][PROFILLER[-1]], 0)

	def test_yeniden_isleme_plani_bos_defterde_hepsi_render(self):
		r = self.kur(ledger=reprocess_mod.RenditionLedger()).plan_reprocess(
			YONETICI, slot_key="product.image", master_sha256="a" * 64
		)
		toplam = len(render_mod.rendition_matrix("product.image"))
		self.assertEqual(r.body["counts"]["render"], toplam)
		self.assertEqual(r.body["work_units"], toplam)
		self.assertTrue(all(s["should_render"] for s in r.body["plan"]))

	def test_yeniden_isleme_defteri_yoksa_503(self):
		yanit = env.call(
			self.kur().plan_reprocess, YONETICI, slot_key="product.image", master_sha256="a" * 64
		)
		self.assertEqual(yanit.status, 503)

	def test_is_anahtari_sunucu_uretir_ve_kararlidir(self):
		api = self.kur(guard=__import__("tradehub_core.media.pipeline.core.jobs", fromlist=["jobs"]).InMemoryGuard())
		a = api.job_status(YONETICI, kind="media.derive", target="/files/x.jpg")
		b = api.job_status(YONETICI, kind="media.derive", target="/files/x.jpg")
		self.assertEqual(a.body["key"], b.body["key"])
		self.assertEqual(len(a.body["key"]), 32)

	def test_ayni_icerik_farkli_ad_ayni_anahtar(self):
		api = self.kur(guard=__import__("tradehub_core.media.pipeline.core.jobs", fromlist=["jobs"]).InMemoryGuard())
		a = api.job_status(YONETICI, kind="media.derive", target="/files/a.jpg", content_hash="c" * 64)
		b = api.job_status(YONETICI, kind="media.derive", target="/files/b.jpg", content_hash="c" * 64)
		self.assertEqual(a.body["key"], b.body["key"])

	def test_bilinmeyen_is_turu_400(self):
		api = self.kur(guard=object())
		self.assertEqual(env.call(api.job_status, YONETICI, kind="uydurma", target="x").status, 400)

	def test_depolama_plani_bozulmayi_bildirir(self):
		"""S3 istendi ama `boto3` yok → yerel diske DÜŞÜLDÜ ve bu raporlanıyor."""
		import tempfile

		with tempfile.TemporaryDirectory() as gecici:
			r = self.kur(
				storage_conf={"media_storage_mode": "s3", "media_site_path": gecici}
			).storage_plan(YONETICI)
		self.assertEqual(r.status, 200)
		self.assertEqual(r.body["requested_mode"], "s3")
		self.assertTrue(r.body["degraded"], "boto3 yokken bozulma bildirilmedi")
		self.assertEqual(r.body["mode"], "local")

	def test_depolama_koku_cozulemezse_503(self):
		"""`StorageError` sözleşme hiyerarşisindedir → 503, çıplak istisna değil."""
		yanit = env.call(self.kur(storage_conf={"media_storage_mode": "local"}).storage_plan, YONETICI)
		self.assertEqual(yanit.status, 503)
		# `StorageError` varsayılanı `retryable=True` ama kök çözümü hatası
		# bilinçli olarak `False` işaretli (storage/__init__.py:123): yanlış
		# yapılandırmayı yeniden denemek aynı sonucu verir.
		self.assertFalse(yanit.body["retryable"])

	def test_depolama_ayari_yoksa_503(self):
		self.assertEqual(env.call(self.kur().storage_plan, YONETICI).status, 503)


# ═══════════════════════════════════════════════════════════════════════
# 7. Katman disiplini
# ═══════════════════════════════════════════════════════════════════════


class KatmanDisiplinTesti(unittest.TestCase):
	"""`media_engine` bench'siz çalışabilmeli — `api/` dâhil."""

	API_DOSYALARI = (
		"envelope.py", "spec.py", "upload.py", "crop.py", "delivery.py", "admin.py",
	)

	def test_modul_duzeyinde_frappe_importu_yok(self):
		import ast

		for ad in self.API_DOSYALARI:
			yol = KOK / "tradehub_core" / "media" / "pipeline" / "api" / ad
			agac = ast.parse(yol.read_text(encoding="utf-8"))
			for dugum in agac.body:  # YALNIZ modül düzeyi
				if isinstance(dugum, ast.Import):
					for n in dugum.names:
						self.assertNotEqual(n.name.split(".")[0], "frappe", f"{ad}: {n.name}")
				elif isinstance(dugum, ast.ImportFrom):
					self.assertNotEqual(
						(dugum.module or "").split(".")[0], "frappe", f"{ad}: {dugum.module}"
					)

	def test_whitelist_dekoratoru_yok(self):
		"""`media_engine` bir kütüphanedir; whitelist bağlama katmanının işidir.

		Aranan şey METİN DEĞİL, gerçek dekoratör kullanımıdır: modül
		dokümanları "`@frappe.whitelist()` taşımaz" cümlesini bilerek
		içeriyor ve düz metin araması o cümleyi ihlal sanardı.
		"""
		import re

		desen = re.compile(r"^\s*@frappe\.whitelist", re.M)
		for ad in self.API_DOSYALARI:
			metin = (KOK / "tradehub_core" / "media" / "pipeline" / "api" / ad).read_text(encoding="utf-8")
			self.assertIsNone(desen.search(metin), f"{ad} whitelist dekoratörü taşıyor")

	def test_api_paketi_uygulandi_isaretli(self):
		import tradehub_core.media.pipeline as media_engine
		from tradehub_core.media.pipeline import api as api_paketi

		self.assertTrue(api_paketi.IMPLEMENTED)
		self.assertTrue(media_engine.IMPLEMENTED["api"])
		self.assertTrue(media_engine.IMPLEMENTED["delivery"])


if __name__ == "__main__":
	unittest.main(verbosity=2)
