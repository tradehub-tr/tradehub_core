# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""`api.media_manifest` testleri — Dalga A / A3.

En kritik test `test_bayrak_kapaliyken_bos_manifest`: bayrak kapalıyken uç
HATA FIRLATMAZ, boş bir manifest + bugünkü ham `file_url` döner. Dalga A'nın
"bayrak kapalıyken sistem birebir bugünküdür" güvencesi buna yaslanıyor.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_manifest_api
"""

from __future__ import annotations

import unittest

import frappe

from tradehub_core.api import media_manifest
from tradehub_core.media import pipeline_flags

FLAG_DOCTYPE = pipeline_flags.SETTINGS_DOCTYPE
KORUNAN_BAYRAKLAR = ("media_pipeline_enabled", "manifest_api_enabled", "active_slots")

#: Fixture'lar gerçek slot politikasının profil merdiveninden seçildi
#: (`policy/slots/product-image.json`). Politikada olmayan bir profil adı
#: `available_profiles` süzgecinden geçemez ve `srcset`e hiç girmez.
PROFIL_W384 = "w384"
PROFIL_W768 = "w768"


class TestMediaManifestApi(unittest.TestCase):
	"""Gerçek bir Active ilan üzerinden uçtan uca."""

	@classmethod
	def setUpClass(cls) -> None:
		cls.ilan = _gercek_ilan()

	def setUp(self) -> None:
		if not self.ilan:
			self.skipTest("Yerel /files/ görseli olan Active ilan yok — fixture kurulamaz.")
		self._orijinal = {
			alan: frappe.db.get_single_value(FLAG_DOCTYPE, alan) for alan in KORUNAN_BAYRAKLAR
		}
		self._temizlenecek: list[tuple[str, str]] = []
		pipeline_flags.clear_cache()

	def tearDown(self) -> None:
		for doctype, ad in reversed(self._temizlenecek):
			try:
				frappe.delete_doc(doctype, ad, force=True, ignore_permissions=True)
			except Exception:
				# Test temizliği başarısız olsa bile diğer testler koşmalı;
				# artık kayıt bir sonraki koşuda `_fixture_kur` tarafından bulunur.
				frappe.log_error(title="test_media_manifest_api temizlik", message=frappe.get_traceback())
		for alan, deger in self._orijinal.items():
			frappe.db.set_single_value(FLAG_DOCTYPE, alan, deger)
		pipeline_flags.clear_cache()
		frappe.db.commit()  # nosemgrep — test fixture'ı kalıcı silinsin
		pipeline_flags.clear_cache()

	# --- bayrak kapalı --------------------------------------------------

	def test_bayrak_kapaliyken_bos_manifest(self) -> None:
		"""Bayrak 0 → boş rendition listesi + bugünkü ham `file_url` (fallback)."""
		self._bayrak(media_pipeline_enabled=0, manifest_api_enabled=0)
		self._fixture_kur()

		sonuc = media_manifest.get_manifest(self.ilan["name"])

		self.assertFalse(sonuc["enabled"])
		self.assertEqual(sonuc["renditions"], [])
		self.assertEqual(sonuc["fallback"], self.ilan["primary_image"])
		self.assertTrue(all(g["manifest"] is None for g in sonuc["images"]))

	def test_ana_salter_kapaliyken_alt_bayrak_ise_yaramaz(self) -> None:
		"""Alt bayrak 1 olsa bile ana şalter kapalıysa manifest boş kalır."""
		self._bayrak(media_pipeline_enabled=0, manifest_api_enabled=1)
		self._fixture_kur()

		sonuc = media_manifest.get_manifest(self.ilan["name"])

		self.assertFalse(sonuc["enabled"])
		self.assertEqual(sonuc["renditions"], [])

	# --- bayrak açık ----------------------------------------------------

	def test_bayrak_acikken_gercek_rendition_listesi(self) -> None:
		"""Bayrak 1 → türevler DB'den gelir; adresler `Media Rendition.file_url`."""
		self._bayrak(media_pipeline_enabled=1, manifest_api_enabled=1)
		beklenen = self._fixture_kur()

		sonuc = media_manifest.get_manifest(self.ilan["name"])

		self.assertTrue(sonuc["enabled"])
		self.assertTrue(sonuc["renditions"], "türev listesi boş — fixture bağlanmadı")
		self.assertEqual(
			sorted(t["url"] for t in sonuc["renditions"]),
			sorted(beklenen["servis_edilir"]),
		)
		# Fayda kapısını geçmeyen türev SERVİS EDİLMEZ ama sayılır.
		self.assertEqual(sonuc["suppressed"], 1)
		self.assertNotIn(beklenen["elenen"], [t["url"] for t in sonuc["renditions"]])

		birincil = sonuc["images"][0]
		self.assertEqual(birincil["file_url"], self.ilan["primary_image"])
		man = birincil["manifest"]
		self.assertIsNotNone(man, "birincil görselin manifesti kurulamadı")
		self.assertEqual(man["slot_key"], media_manifest.DEFAULT_SLOT)
		# İlk görsel LCP adayıdır.
		self.assertEqual(man["loading"], "eager")
		self.assertEqual(man["fetchpriority"], "high")
		# srcset yalnız üretilmiş adresleri taşır — 404 indirtmez.
		tum_srcset = " ".join(k["srcset"] for k in man["sources"])
		for url in beklenen["servis_edilir"]:
			self.assertIn(url, tum_srcset)
		self.assertNotIn(beklenen["elenen"], tum_srcset)

	def test_gorunmez_ilan_bos_manifest_doner(self) -> None:
		"""Yayınlanmamış/olmayan ilan 404 DEĞİL boş manifest — sızıntı olmasın."""
		self._bayrak(media_pipeline_enabled=1, manifest_api_enabled=1)

		yok = media_manifest.get_manifest("LST-BOYLE-BIR-ILAN-YOK")

		self.assertEqual(yok["renditions"], [])
		self.assertEqual(yok["images"], [])
		self.assertEqual(yok["fallback"], "")

	def test_storefront_visible_kapali_ilan_misafire_bos_doner(self) -> None:
		"""B-1 regresyonu: `storefront_visible = 0` ilan misafire manifest VERMEZ.

		Satıcı ürünü vitrinden kaldırdığında (`is_visible = 0`) `status` alanı
		`Active` KALABİLİYOR; yalnız `status` süzen eski sorgu bu ürünün tüm
		galerisini oturumsuz çağırana açıyordu. Kanonik yüklem
		`storefront_visible = 1` (`api/listing.py` baştan sona bunu kullanır).
		"""
		self._bayrak(media_pipeline_enabled=1, manifest_api_enabled=1)

		onceki_kullanici = frappe.session.user
		onceki_gorunurluk = frappe.db.get_value("Listing", self.ilan["name"], "storefront_visible")
		try:
			frappe.set_user("Guest")
			# Pozitif kontrol: ilan vitrindeyken galeri GERÇEKTEN dönüyor —
			# yani aşağıdaki boş gövde süzgecin eseri, kırık fixture'ın değil.
			gorunur = media_manifest.get_manifest(self.ilan["name"])
			frappe.set_user(onceki_kullanici)
			frappe.db.set_value(
				"Listing", self.ilan["name"], "storefront_visible", 0, update_modified=False
			)
			frappe.set_user("Guest")
			gizli = media_manifest.get_manifest(self.ilan["name"])
		finally:
			frappe.set_user(onceki_kullanici)
			frappe.db.set_value(
				"Listing",
				self.ilan["name"],
				"storefront_visible",
				onceki_gorunurluk,
				update_modified=False,
			)

		self.assertEqual(gorunur["fallback"], self.ilan["primary_image"])
		self.assertTrue(gorunur["images"])

		self.assertEqual(gizli["renditions"], [])
		self.assertEqual(gizli["images"], [])
		# Gizlenmiş ilan ile HİÇ OLMAYAN ilan aynı gövdeyi almalı (ayırt edilemez).
		self.assertEqual(gizli["fallback"], "")

	def test_etag_icerik_hashine_dayali(self) -> None:
		"""Aynı gövde aynı ETag; `if_none_match` tutunca gövdesiz yanıt."""
		self._bayrak(media_pipeline_enabled=1, manifest_api_enabled=1)
		self._fixture_kur()

		birinci = media_manifest.get_manifest(self.ilan["name"])
		ikinci = media_manifest.get_manifest(self.ilan["name"])
		self.assertTrue(birinci["etag"])
		self.assertEqual(birinci["etag"], ikinci["etag"])
		self.assertEqual(birinci["cache_control"], media_manifest.CACHE_CONTROL)

		ucuncu = media_manifest.get_manifest(self.ilan["name"], if_none_match=birinci["etag"])
		self.assertTrue(ucuncu["not_modified"])
		self.assertNotIn("renditions", ucuncu)

	# --- batch ----------------------------------------------------------

	def test_60_ilan_50ye_kirpilir(self) -> None:
		"""Sınır aşımı REDDEDİLMEZ, kırpılır: 60 istendi → 50 işlendi, 10 skipped."""
		self._bayrak(media_pipeline_enabled=1, manifest_api_enabled=1)
		adlar = [f"LST-TEST-{i:05d}" for i in range(60)]

		sonuc = media_manifest.get_manifest_batch(",".join(adlar))

		self.assertEqual(sonuc["requested"], 60)
		self.assertTrue(sonuc["truncated"])
		self.assertEqual(sonuc["max_batch"], media_manifest.MAX_BATCH_LISTINGS)
		self.assertEqual(len(sonuc["skipped"]), 10)
		self.assertEqual(sonuc["skipped"], adlar[50:])
		# B-5: `missing` artık DAİMA boş. Bulunamayan kimlikleri saymak, guest'e
		# açık bir uçta "denediğin kimliklerden hangileri gerçek" sorusuna
		# cevap veren bir numaralandırma kehanetiydi.
		self.assertEqual(sonuc["missing"], [])

	def test_girdi_sert_tavanda_kirpilir(self) -> None:
		"""B-3: 10.000 kimlik gönderen çağıran `MAX_REQUEST_LISTINGS`te durur."""
		self._bayrak(media_pipeline_enabled=1, manifest_api_enabled=1)
		adlar = [f"LST-FLOOD-{i:06d}" for i in range(10_000)]

		sonuc = media_manifest.get_manifest_batch(",".join(adlar))

		self.assertEqual(sonuc["requested"], media_manifest.MAX_REQUEST_LISTINGS)
		self.assertTrue(sonuc["truncated"])
		self.assertEqual(
			len(sonuc["skipped"]),
			media_manifest.MAX_REQUEST_LISTINGS - media_manifest.MAX_BATCH_LISTINGS,
		)

	def test_batch_gercek_ilani_dondurur(self) -> None:
		"""Batch tek ilanla aynı gövdeyi üretir (JSON dizi girdisiyle)."""
		self._bayrak(media_pipeline_enabled=1, manifest_api_enabled=1)
		self._fixture_kur()

		sonuc = media_manifest.get_manifest_batch(frappe.as_json([self.ilan["name"]]))

		self.assertEqual(sonuc["returned"], 1)
		self.assertEqual(sonuc["missing"], [])
		self.assertTrue(sonuc["manifests"][self.ilan["name"]]["renditions"])

	# --- imzalı URL -----------------------------------------------------

	def test_guest_signed_url_permission_error(self) -> None:
		"""Guest imza ÜRETEMEZ — bu modülün tek kritik güvenlik kuralı."""
		onceki = frappe.session.user
		try:
			frappe.set_user("Guest")
			with self.assertRaises(frappe.PermissionError):
				media_manifest.get_signed_url("/private/files/herhangi.jpg")
		finally:
			frappe.set_user(onceki)

	def test_public_yol_imzalanmaz(self) -> None:
		"""Public dosya için imza istemek reddedilir (mevcut `media_access` kuralı)."""
		with self.assertRaises(frappe.ValidationError):
			media_manifest.get_signed_url("/files/herhangi.jpg")

	# --- yardımcılar ----------------------------------------------------

	def _bayrak(self, **degerler: object) -> None:
		for alan, deger in degerler.items():
			frappe.db.set_single_value(FLAG_DOCTYPE, alan, deger)
		pipeline_flags.clear_cache()

	def _fixture_kur(self) -> dict:
		"""İlanın birincil görseli için Asset + 3 türev (1'i fayda kapısında elenir)."""
		for profil, genislik in ((PROFIL_W384, 384), (PROFIL_W768, 768)):
			# `Media Profile` docname'i `{slot_key}:{policy_profile}` biçiminde
			# (profil adları slotlar arası çakıştığı için); kütüphanenin beklediği
			# HAM ad `policy_profile` alanında durur ve `Media Rendition.profile`
			# kolonuna o yazılır. Kurulu sitede bu kayıtları
			# `patches/v15_9_23_media_profile_seed` zaten üretiyor.
			profil_adi = f"{media_manifest.DEFAULT_SLOT}:{profil}"
			if not frappe.db.exists("Media Profile", profil_adi):
				# `fit`/`aspect_ratio` gerçek politikadan (product-image.json):
				# pad + 1:1. `fit='cover'` oran zorunlu kılıyor.
				doc = frappe.get_doc(
					{
						"doctype": "Media Profile",
						"profile_key": profil_adi,
						"policy_profile": profil,
						"slot_key": media_manifest.DEFAULT_SLOT,
						"enabled": 1,
						"fit": "pad",
						"aspect_ratio": "1:1",
						"widths": frappe.as_json([genislik]),
						"formats": frappe.as_json(["avif", "webp"]),
					}
				).insert(ignore_permissions=True)
				self._temizlenecek.append(("Media Profile", doc.name))

		varlik = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": media_manifest.DEFAULT_SLOT,
				"media_type": "image",
				"state": "ready",
				"owner_seller": self.ilan["seller_profile"],
				"source_file": self.ilan["file_name"],
				"content_sha256": "a3" * 32,
			}
		).insert(ignore_permissions=True)
		self._temizlenecek.append(("Media Asset", varlik.name))

		servis_edilir: list[str] = []
		elenen = ""
		for profil, genislik, bicim, gecti in (
			(PROFIL_W384, 384, "webp", 1),
			(PROFIL_W768, 768, "webp", 1),
			(PROFIL_W768, 768, "avif", 0),  # fayda kapısını geçemedi → servis edilmez
		):
			url = f"/files/media/{varlik.name}/{profil}-{genislik}.{bicim}"
			turev = frappe.get_doc(
				{
					"doctype": "Media Rendition",
					"asset": varlik.name,
					# `Media Rendition.profile` artık `Data`: HAM politika adı
					# ("w384") yazılır, docname (`product.image:w384`) DEĞİL.
					# `api/media_manifest` bu kolonu `available_profiles` olarak
					# politika adıyla eşleştirir; docname yazılırsa hiçbir varyant
					# eşleşmez ve manifest sessizce boş döner.
					"profile": profil,
					"width": genislik,
					"height": genislik,
					"format": bicim,
					"file_url": url,
					"bytes": 1024,
					"benefit_gate_passed": gecti,
				}
			).insert(ignore_permissions=True)
			self._temizlenecek.append(("Media Rendition", turev.name))
			if gecti:
				servis_edilir.append(url)
			else:
				elenen = url

		frappe.db.commit()  # nosemgrep — `frappe.db.sql` ile okunacak, aynı işlemde görünmeli
		return {"asset": varlik.name, "servis_edilir": servis_edilir, "elenen": elenen}


def _gercek_ilan() -> dict | None:
	"""Yerel `/files/` görseli olan, VİTRİNDE GÖRÜNEN bir ilan + `File` kaydı.

	`storefront_visible = 1` koşulu şart: manifest ucunun görünürlük yüklemi
	budur, `status` yalnız ikinci katmandır.

	Fixture ilanı ÜRETİLMİYOR: `Listing` onlarca zorunlu alan ve bağlı doküman
	istiyor; testin ölçtüğü şey ilan kurulumu değil, manifest kurulumu.

	İZOLASYON (2026-08-20): görseli için HALİHAZIRDA `Media Asset` bulunan
	ilanlar dışlanır. Boru hattı DEV'de artık gerçek türev üretiyor (W3-B,
	rapor 69); testin sabit `ORDER BY l.name` seçimi tam da işlenmiş bir
	ilana (nf.jpg) denk gelince beklenen liste DB'deki gerçek envanterle
	karıştı ve iki test kırıldı. Test kendi fixture'ını kendi kurar; temiz
	bir görsel seçmek, DB'yi temizlemekten hem güvenli hem deterministtir.
	(Tüm görseller işlenmiş olursa satır kalmaz → setUp zaten skipTest der.)
	"""
	satirlar = frappe.db.sql(
		"""
		SELECT l.name, l.seller_profile, l.primary_image, f.name AS file_name
		FROM `tabListing` l
		INNER JOIN `tabFile` f ON f.file_url = l.primary_image
		WHERE l.storefront_visible = 1
		  AND l.status = 'Active'
		  AND l.primary_image LIKE '/files/%%'
		  AND l.seller_profile IS NOT NULL AND l.seller_profile != ''
		  AND NOT EXISTS (
			-- Dışlama URL üzerinden: aynı file_url'de 5'e kadar MÜKERRER File
			-- satırı var (rapor 66 §9) ve varlık, seçilen f.name'e değil başka
			-- bir mükerrer satıra bağlı olabilir. f.name ile dışlamak kör kalır
			-- — ilk deneme tam böyle kırıldı.
			SELECT 1
			FROM `tabMedia Asset` ma
			INNER JOIN `tabFile` f2 ON ma.source_file = f2.name
			WHERE f2.file_url = l.primary_image
		  )
		ORDER BY l.name ASC
		LIMIT 1
		""",
		as_dict=True,
	)
	return satirlar[0] if satirlar else None
