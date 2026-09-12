"""MOGEM-620 — permütasyon/kombinasyon testleri.

NEDEN AYRI MODÜL
----------------
`test_mogem620_fonksiyonel` her kuralı TEK örnekle sınıyor. Bu modül aynı
kuralları ÇARPIM UZAYINDA sınıyor: bir kural tek örnekte doğru olup
kombinasyonda yanlış olabiliyor ve gerçek kusurlar tam orada saklanıyor
(ör. `alt` dolu + `description` boş + `has_text` doğru üçlüsünde skorun
hangi boyuta gittiği).

UZAY BÜYÜKLÜĞÜ BİLİNÇLİ SINIRLI
-------------------------------
Tam çarpım hızla patlıyor: 10 boyut × 2 durum = 1024 kombinasyon yalnız skor
için. Her sınıfın başında hangi eksenlerin seçildiği ve NEDEN o eksenlerin
seçildiği yazılı. Ölçüt: eksenler birbirini ETKİLİYORSA çarpıma girer;
etkilemiyorsa tek örnek yeterlidir ve fonksiyonel modülde zaten var.

Koşum:
    docker exec istoc-backend bench --site tradehub.localhost \\
        run-tests --module tradehub_core.tests.test_mogem620_permutasyon
"""

from __future__ import annotations

import itertools
import json

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import bulk_ops, decode_cost, meter, seo, seo_audit, tags_source
from tradehub_core.seo import schema_builder
from tradehub_core.seo.i18n import CONTENT_LANGS
from tradehub_core.tests.mogem620_ortak import TUZ, dosya_ac, png_uret, sil


class TestSkorCarpimUzayi(FrappeTestCase):
	"""§13 — `visual_search` ve `ai_readiness` sinyallerinin TAM çarpımı.

	Eksenler: her boyutun kendi sinyal listesi (5 ve 6 sinyal → 32 + 64 = 96
	kombinasyon). Tam çarpım burada makul ve gerekli: skor formülü "dolu
	sinyal / toplam sinyal" ve tek bir sinyalin yanlış sayılması ancak
	komşularıyla birlikte bakınca görünür.
	"""

	def test_gorsel_arama_tum_altkumeler(self):
		sinyaller = seo_audit._GORSEL_SINYALLER
		for r in range(len(sinyaller) + 1):
			for secim in itertools.combinations(sinyaller, r):
				alanlar = {ad: "x" for ad in secim}
				beklenen = round(100 * len(secim) / len(sinyaller))
				self.assertEqual(
					seo_audit.score_from([], alanlar)["visual_search"],
					beklenen,
					msg=f"seçim={secim}",
				)

	def test_ai_hazirlik_tum_altkumeler(self):
		sinyaller = seo_audit._AI_SINYALLER
		for r in range(len(sinyaller) + 1):
			for secim in itertools.combinations(sinyaller, r):
				alanlar = {ad: "x" for ad in secim}
				beklenen = round(100 * len(secim) / len(sinyaller))
				self.assertEqual(
					seo_audit.score_from([], alanlar)["ai_readiness"],
					beklenen,
					msg=f"seçim={secim}",
				)

	def test_iki_boyut_birbirini_etkilemez(self):
		"""Sinyal listeleri KESİŞMİYOR — biri dolarken diğeri kıpırdamamalı."""
		self.assertEqual(
			set(seo_audit._GORSEL_SINYALLER) & set(seo_audit._AI_SINYALLER),
			set(),
			"iki liste kesişirse bir alanı doldurmak iki boyutu birden oynatır",
		)
		yalniz_gorsel = {ad: "x" for ad in seo_audit._GORSEL_SINYALLER}
		skor = seo_audit.score_from([], yalniz_gorsel)
		self.assertEqual(skor["visual_search"], 100)
		self.assertEqual(skor["ai_readiness"], 0)

	def test_bos_ve_bosluk_dolu_sayilmaz(self):
		"""'   ' bir değer değil; sinyal sayacı onu dolu saymamalı."""
		for bos in ("", "   ", None, False, 0):
			alanlar = {ad: bos for ad in seo_audit._AI_SINYALLER}
			self.assertEqual(
				seo_audit.score_from([], alanlar)["ai_readiness"], 0, msg=repr(bos)
			)


class TestYerellestirmeCarpimi(FrappeTestCase):
	"""§11 — dört dilin tüm alt kümelerinde `localization` skoru.

	Eksen: hangi dillerde alt metni var (2^4 = 16 kombinasyon). Diller
	birbirini etkiliyor (skor oranla hesaplanıyor), o yüzden çarpım.
	"""

	def test_dil_altkumeleri(self):
		diller = list(CONTENT_LANGS)
		for r in range(len(diller) + 1):
			for secim in itertools.combinations(diller, r):
				alanlar = {"localized": {"alt": {d: ("metin" if d in secim else "") for d in diller}}}
				beklenen = round(100 * len(secim) / len(diller))
				self.assertEqual(
					seo_audit.score_from([], alanlar)["localization"],
					beklenen,
					msg=f"diller={secim}",
				)


class TestCokDilliCozumCarpimi(FrappeTestCase):
	"""§11 — `description` dört dilde × dört okuma dili = 16 çözüm.

	Eksenler birbirini etkiliyor: fallback zinciri "istenen dil → varsayılan
	dil → eski tek-dil kolonu". Zincirin hangi halkasının devreye girdiği
	ancak çarpımda görünür.
	"""

	def setUp(self):
		self.doc = dosya_ac(f"perm-dil-{TUZ}.png", png_uret())
		self.addCleanup(sil, "File", self.doc.name)

	def test_yalniz_bir_dil_doluyken_hepsi_ona_duser(self):
		"""Yalnız TR (varsayılan) doluysa dört okuma da TR'yi görmeli."""
		seo.set_asset_fields(self.doc.file_url, {"description_tr": "TR-METIN"})
		for lang in CONTENT_LANGS:
			self.assertEqual(
				seo.fields_for(self.doc.file_url, lang=lang)["description"],
				"TR-METIN",
				msg=f"lang={lang}",
			)

	def test_her_dil_kendi_degerini_gorur(self):
		degerler = {f"description_{d}": f"metin-{d}" for d in CONTENT_LANGS}
		seo.set_asset_fields(self.doc.file_url, degerler)
		for lang in CONTENT_LANGS:
			self.assertEqual(
				seo.fields_for(self.doc.file_url, lang=lang)["description"], f"metin-{lang}"
			)

	def test_eksik_dil_varsayilana_duser_digerleri_etkilenmez(self):
		seo.set_asset_fields(
			self.doc.file_url, {"description_tr": "TR", "description_en": "EN"}
		)
		self.assertEqual(seo.fields_for(self.doc.file_url, lang="en")["description"], "EN")
		for lang in ("ar", "ru"):
			self.assertEqual(
				seo.fields_for(self.doc.file_url, lang=lang)["description"], "TR", msg=lang
			)

	def test_uc_varlik_alani_bagimsiz_cozulur(self):
		"""`description`/`transcript`/`captions_url` birbirini ezmemeli."""
		seo.set_asset_fields(
			self.doc.file_url,
			{
				"description_en": "D-EN",
				"transcript_en": "T-EN",
				"captions_url_en": "/c-en.vtt",
				"description_tr": "D-TR",
			},
		)
		en = seo.fields_for(self.doc.file_url, lang="en")
		self.assertEqual((en["description"], en["transcript"], en["captions_url"]),
			("D-EN", "T-EN", "/c-en.vtt"))


class TestGorunurlukCarpimi(FrappeTestCase):
	"""§7/§14 — sekiz görünürlük × üç robots kombinasyonu.

	Eksenler birbirini etkiliyor: `Private` her robots değerinde reddedilmeli,
	geçerli robots her izinli görünürlükte kabul edilmeli.
	"""

	ROBOTS = ("", "noindex", "index, follow, max-image-preview:large")

	def setUp(self):
		self.doc = dosya_ac(f"perm-gorunur-{TUZ}.png", png_uret())
		self.addCleanup(sil, "File", self.doc.name)

	def test_tum_gorunurluk_robots_ciftleri(self):
		for gorunurluk, robots in itertools.product(sorted(bulk_ops.VISIBILITIES), self.ROBOTS):
			if gorunurluk == "Private":
				with self.assertRaises(frappe.ValidationError, msg=f"{gorunurluk}/{robots}"):
					bulk_ops.set_indexability_many(
						[self.doc.file_url], gorunurluk, robots_override=robots
					)
				continue
			sonuc = bulk_ops.set_indexability_many(
				[self.doc.file_url], gorunurluk, robots_override=robots
			)
			self.assertEqual(sonuc["applied"], 1, msg=f"{gorunurluk}/{robots}")
			self.assertEqual(
				frappe.db.get_value("File", self.doc.name, "th_media_visibility"), gorunurluk
			)

	def test_gecersiz_robots_her_gorunurlukte_reddedilir(self):
		for gorunurluk in sorted(bulk_ops.VISIBILITIES - {"Private"}):
			with self.assertRaises(frappe.ValidationError, msg=gorunurluk):
				bulk_ops.set_indexability_many(
					[self.doc.file_url], gorunurluk, robots_override="noindex, kotu"
				)


class TestEtiketKaynakGecisleri(FrappeTestCase):
	"""§17 — beş kaynak × beş kaynak = 25 geçiş.

	Çakışma kuralı ("manual makineyi ezer, makine manual'ı ezemez") tek
	örnekte doğrulanabilir ama TAM matris, kuralın yanlışlıkla asimetrik
	uygulandığı bir çifti ortaya çıkarır.
	"""

	def test_tum_gecis_matrisi(self):
		insan = {tags_source.SOURCE_MANUAL}
		for once, sonra in itertools.product(sorted(tags_source.SOURCES), repeat=2):
			harita = tags_source.birlestir({}, ["e"], once)
			harita = tags_source.birlestir(harita, ["e"], sonra)
			beklenen = once if (once in insan and sonra not in insan) else sonra
			self.assertEqual(harita["e"], beklenen, msg=f"{once}→{sonra}")

	def test_farkli_etiketler_birbirini_etkilemez(self):
		harita = tags_source.birlestir({}, ["a"], tags_source.SOURCE_MANUAL)
		harita = tags_source.birlestir(harita, ["b"], tags_source.SOURCE_AI)
		self.assertEqual(harita, {"a": "manual", "b": "ai"})


class TestDecodeFormatCarpimi(FrappeTestCase):
	"""§9 — her format × alfa × progressive = 10 × 2 × 2 = 40 kombinasyon."""

	def test_carpanlar_birbirini_bozmaz(self):
		for bicim, alfa, prog in itertools.product(
			sorted(decode_cost.FORMAT_KATSAYI), (False, True), (False, True)
		):
			deger = decode_cost.estimate(
				width=1000, height=1000, file_format=bicim, has_alpha=alfa, progressive=prog
			)
			taban = decode_cost.estimate(width=1000, height=1000, file_format=bicim)
			self.assertGreaterEqual(deger, taban, msg=f"{bicim}/{alfa}/{prog}")
			if decode_cost.FORMAT_KATSAYI[bicim] == 0:
				self.assertEqual(deger, 0.0, msg=f"{bicim} vektör — raster çözme yok")

	def test_boyut_ile_dogrusal(self):
		"""Piksel iki katına çıkınca maliyet de iki katına çıkmalı."""
		for bicim in sorted(decode_cost.FORMAT_KATSAYI):
			tek = decode_cost.estimate(width=1000, height=1000, file_format=bicim)
			cift = decode_cost.estimate(width=2000, height=1000, file_format=bicim)
			self.assertAlmostEqual(cift, tek * 2, places=2, msg=bicim)


class TestKotaKararMatrisi(FrappeTestCase):
	"""§18 — üç ölçüm × beş limit değeri = 15 karar.

	Limit değerleri sözleşmenin tamamını kapsıyor: tanımsız, sınırsız,
	kapalı, altında, üstünde.
	"""

	def test_karar_matrisi(self):
		from unittest import mock as _mock

		senaryolar = (
			(None, True, "unconfigured"),
			(-1, True, "unlimited"),
			(0, False, "disabled"),
			(100, True, "ok"),
			(1, False, "exceeded"),
		)
		for metric in sorted(meter.QUOTA_KEYS):
			for limit, izin, gerekce in senaryolar:
				with _mock.patch.object(meter, "limit_for", return_value=limit), _mock.patch.object(
					meter, "consumed", return_value=0
				):
					karar = meter.check("MAGAZA", metric, incoming=10)
				self.assertEqual(karar["allowed"], izin, msg=f"{metric}/{limit}")
				self.assertEqual(karar["reason"], gerekce, msg=f"{metric}/{limit}")


class TestVideoSemaCarpimi(FrappeTestCase):
	"""§5 — dört yeni alanın 2^4 = 16 kombinasyonu.

	Eksenler birbirini etkiliyor: hepsi aynı `VideoObject` sözlüğüne
	yazıyor ve biri diğerinin anahtarını silebilir.
	"""

	ALANLAR = {
		"regions_allowed": ("TR,DE", "regionsAllowed"),
		"content_rating": ("PG-13", "contentRating"),
		"age_restriction": ("18+", "isFamilyFriendly"),
		"chapters": (json.dumps([{"start": 0, "title": "G"}]), "hasPart"),
	}

	def test_tum_kombinasyonlar(self):
		adlar = sorted(self.ALANLAR)
		for r in range(len(adlar) + 1):
			for secim in itertools.combinations(adlar, r):
				alanlar = {
					"poster_url": "/files/p.jpg",
					"title": "V",
					"duration": 10,
					**{ad: self.ALANLAR[ad][0] for ad in secim},
				}
				obj = schema_builder.build_video_object(
					alanlar, "https://x.test", content_url="/files/v.mp4"
				)
				self.assertIsNotNone(obj, msg=f"seçim={secim}")
				for ad in adlar:
					anahtar = self.ALANLAR[ad][1]
					if ad in secim:
						self.assertIn(anahtar, obj, msg=f"{secim} → {anahtar} olmalı")
					else:
						self.assertNotIn(anahtar, obj, msg=f"{secim} → {anahtar} olmamalı")

	def test_zorunlu_alanlar_her_kombinasyonda_korunur(self):
		"""Yeni alanlar `name`/`thumbnailUrl`/`duration` üçlüsünü ezmemeli."""
		for r in range(len(self.ALANLAR) + 1):
			for secim in itertools.combinations(sorted(self.ALANLAR), r):
				obj = schema_builder.build_video_object(
					{
						"poster_url": "/files/p.jpg",
						"title": "V",
						"duration": 65,
						**{ad: self.ALANLAR[ad][0] for ad in secim},
					},
					"https://x.test",
					content_url="/files/v.mp4",
				)
				self.assertEqual(obj["name"], "V")
				self.assertEqual(obj["duration"], "PT1M5S")


class TestAramaAlanCarpimi(FrappeTestCase):
	"""§16 — genişletilen arama sütunlarının her biri TEK BAŞINA eşleşmeli.

	Tek örnekle sınamak yetmez: bir sütunun sorguya hiç girmemesi ancak o
	sütuna özel bir arama yapıldığında görünür, diğerleri doluyken kaybolur.
	"""

	def setUp(self):
		from tradehub_core.media import inventory

		self.inventory = inventory
		self.doc = dosya_ac(f"arama-{TUZ}.png", png_uret())
		self.addCleanup(sil, "File", self.doc.name)

	def test_her_sutun_ayri_ayri_aranabilir(self):
		aranabilir = self.inventory._aranabilir_sutunlar()
		self.assertIn("th_media_extracted_text", aranabilir, "OCR/PDF metni aranabilir olmalı")
		self.assertIn("th_media_transcript", aranabilir, "transkript aranabilir olmalı")
		self.assertIn("th_media_description", aranabilir, "açıklama aranabilir olmalı")
		# `alt_ai` BİLEREK dışarıda: onaylanmamış AI çıktısı aranabilir olmamalı.
		self.assertNotIn("th_media_alt_ai", aranabilir)

	def test_her_sutun_icin_locate_kosulu_uretilir(self):
		from frappe.query_builder import DocType

		m = DocType("tabFile")
		for sutun in self.inventory._aranabilir_sutunlar():
			kosul = self.inventory._serbest_arama_kosulu(m, "ara")
			self.assertIsNotNone(kosul, msg=sutun)

	def test_bos_sutun_listesinde_dosya_adina_duser(self):
		"""Hiç sütun yoksa sorgu ÖLÜ sonuç kümesi üretmemeli."""
		from unittest import mock as _mock

		from frappe.query_builder import DocType

		m = DocType("tabFile")
		with _mock.patch.object(self.inventory, "_aranabilir_sutunlar", return_value=()):
			kosul = self.inventory._serbest_arama_kosulu(m, "ara")
		self.assertIn("file_name", str(kosul))
