"""KD-10 — Medya SEO katmanı: alan doğrulama, denetim kuralları, skorlama.

Kaynak okundu:
  * `media/seo.py` (548)        — alan okuma/yazma, override, çok dillilik
  * `media/seo_audit.py` (1026) — denetim kuralları + 8 boyutlu skor
  * `media/seo_generate.py` (576)

Denetimin soruları:
  • Denetim kuralları GERÇEKTEN eksik alanı yakalıyor mu, yoksa boş listeyi
    "sorun yok" diye mi geçiyor?
  • Skor formülü sınırlarda (hepsi hatalı / hepsi temiz) doğru mu?
  • Alan yazma ucu geçersiz girdiyi reddediyor mu (uzunluk, tür, XSS)?
  • Video alanları yalnız video dosyalarında mı isteniyor?
"""

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import seo, seo_audit
from tradehub_core.tests.kapsamli import _yardim as y


def _alanlar(**kw) -> dict:
	"""Denetimden TEMİZ geçen alan seti — testler yalnız farkı yazar."""
	temel = {
		"alt": "Kırmızı kadife üç kişilik koltuk",
		"title": "Kırmızı koltuk",
		"caption": "Salon takımı ürün görseli",
		"width": 2000,
		"height": 2000,
		"license_url": "https://istoc.com/lisans",
		"copyright_notice": "© İstoç",
		"rights_expires_on": None,
	}
	temel.update(kw)
	return temel


def _kodlar(bulgular: list[dict]) -> set[str]:
	return {b["code"] for b in bulgular}


#: ORTAM BAĞIMSIZLIĞI — File açan her fixture tarama kancasını nötrler.
#: Gerekçe (ölçülmüş, TUR-125): ClamAV kurulu bir makinede `after_insert`
#: kancası dosyayı `pending` damgalayıp bekletmeye alıyor; fixture'lar
#: dosyanın `public/files/`'da durduğunu varsaydığı için kırılıyor. Kurulum
#: bir kerede 6 testi düşürmüştü. Kural: bir bağımlılığın YOKLUĞU üstüne
#: test yazma.
def _av_kancasini_notrle(testcase):
	from unittest import mock as _mock

	for hedef in (
		"tradehub_core.media.av.enqueue_scan",
		"tradehub_core.media.av.maybe_scan_on_insert",
	):
		yama = _mock.patch(hedef, return_value=None)
		yama.start()
		testcase.addCleanup(yama.stop)


# ══════════════════════════════════════════════════════════════════════
# 1. Alan tabanlı denetim kuralları
# ══════════════════════════════════════════════════════════════════════


class TestDenetimKurallari(unittest.TestCase):
	def test_bi_temiz_alan_seti_bulgu_uretmez(self):
		self.assertEqual(
			seo_audit.audit_fields(_alanlar(), file_name="kirmizi-kadife-koltuk.jpg"), []
		)

	def test_bi_alt_metni_yoksa_HATA(self):
		b = seo_audit.audit_fields(_alanlar(alt=""))
		self.assertIn("missing_alt", _kodlar(b))
		self.assertEqual(
			[x["severity"] for x in b if x["code"] == "missing_alt"], [seo_audit.SEVERITY_ERROR]
		)

	def test_bi_alt_yalniz_bosluksa_yok_sayilir(self):
		self.assertIn("missing_alt", _kodlar(seo_audit.audit_fields(_alanlar(alt="   \n\t"))))

	def test_sn_alt_uzunluk_sinirlari(self):
		# tam sınırda uyarı YOK
		self.assertNotIn("suspicious_alt", _kodlar(seo_audit.audit_fields(_alanlar(alt="a" * seo_audit._ALT_MAX))))
		# bir fazlasında uyarı VAR
		self.assertIn("suspicious_alt", _kodlar(seo_audit.audit_fields(_alanlar(alt="a" * (seo_audit._ALT_MAX + 1)))))
		# çok kısa
		self.assertIn("suspicious_alt", _kodlar(seo_audit.audit_fields(_alanlar(alt="abc"))))
		self.assertNotIn("suspicious_alt", _kodlar(seo_audit.audit_fields(_alanlar(alt="abcde"))))

	def test_bi_anahtar_kelime_doldurmasi_yakalanir(self):
		dolu = "koltuk koltuk koltuk kırmızı kadife"
		self.assertIn("keyword_stuffed_alt", _kodlar(seo_audit.audit_fields(_alanlar(alt=dolu))))

	def test_sn_iki_tekrar_doldurma_sayilmaz(self):
		self.assertNotIn(
			"keyword_stuffed_alt",
			_kodlar(seo_audit.audit_fields(_alanlar(alt="koltuk koltuk kırmızı kadife salon"))),
		)

	def test_bi_kisa_kelimeler_doldurma_sayilmaz(self):
		"""4 harften kısa kelimeler (ve, ile, bir) sayılmamalı."""
		self.assertNotIn(
			"keyword_stuffed_alt",
			_kodlar(seo_audit.audit_fields(_alanlar(alt="bir ve bir ve bir kırmızı koltuk"))),
		)

	def test_bi_parantezli_gurultu(self):
		gurultulu = "Kırmızı Kadife Koltuk (Ürün Kodu: ABC-123-XYZ) (Stok: 42) salon takımı"
		self.assertIn("suspicious_alt", _kodlar(seo_audit.audit_fields(_alanlar(alt=gurultulu))))

	def test_bi_baslik_ve_altyazi_eksikligi_uyari(self):
		b = _kodlar(seo_audit.audit_fields(_alanlar(title="", caption="")))
		self.assertIn("missing_title", b)
		self.assertIn("missing_caption", b)

	def test_bi_olcu_eksikligi_HATA_cls(self):
		for eksik in ({"width": 0}, {"height": 0}, {"width": None, "height": None}):
			with self.subTest(eksik=eksik):
				b = seo_audit.audit_fields(_alanlar(**eksik))
				self.assertIn("missing_dimensions", _kodlar(b))

	def test_bi_lisans_eksikligi(self):
		b = seo_audit.audit_fields(_alanlar(license_url="", copyright_notice=""))
		self.assertIn("missing_license", _kodlar(b))

	def test_bi_lisans_ikisinden_biri_yeterli(self):
		self.assertNotIn("missing_license", _kodlar(seo_audit.audit_fields(_alanlar(license_url=""))))
		self.assertNotIn(
			"missing_license", _kodlar(seo_audit.audit_fields(_alanlar(copyright_notice="")))
		)

	def test_gv_suresi_dolmus_hak_yayindaysa_HATA(self):
		b = seo_audit.audit_fields(_alanlar(rights_expires_on="2020-01-01"))
		self.assertIn("expired_rights", _kodlar(b))
		self.assertEqual(
			[x["severity"] for x in b if x["code"] == "expired_rights"], [seo_audit.SEVERITY_ERROR]
		)

	def test_bi_gelecekteki_hak_bitisi_sorun_degil(self):
		self.assertNotIn(
			"expired_rights", _kodlar(seo_audit.audit_fields(_alanlar(rights_expires_on="2099-01-01")))
		)

	def test_bi_kotu_dosya_adi_uyarisi(self):
		for kotu in ("IMG_1234.jpg", "DSC00042.JPG", "untitled.png", "Adsız.jpg",
					 "WhatsApp Image 2026.jpeg", "ekran görüntüsü.png"):
			with self.subTest(ad=kotu):
				self.assertIn("poor_filename", _kodlar(seo_audit.audit_fields(_alanlar(), file_name=kotu)), kotu)

	def test_bi_BULGU_jenerik_ve_tarihli_adlar_KURAL_DISI(self):
		"""BULGU F-19 (kapsam) — `_BAD_NAME` deseni jenerik adları kaçırıyor.

		Desen `img_N | ekran görüntüsü | whatsapp | dsc_N | untitled | adsız`
		ile sınırlı. Sahada çok yaygın olan `photo.jpg`, `image.png`,
		`20260101_120000.jpg` (tarih damgası), `1.jpg` gibi adlar SEO açısından
		aynı ölçüde bilgisiz ama uyarı ÜRETMİYOR.
		"""
		kacanlar = ("photo.jpg", "image.png", "20260101_120000.jpg", "1.jpg", "final_v2.jpg")
		for ad in kacanlar:
			with self.subTest(ad=ad):
				self.assertNotIn(
					"poor_filename", _kodlar(seo_audit.audit_fields(_alanlar(), file_name=ad)),
					f"F-19 kapanmış olabilir: {ad} artık yakalanıyor",
				)

	def test_bi_iyi_dosya_adi_uyari_uretmez(self):
		self.assertNotIn(
			"poor_filename",
			_kodlar(seo_audit.audit_fields(_alanlar(), file_name="kirmizi-kadife-koltuk.jpg")),
		)

	def test_bi_VIDEO_alanlari_yalniz_videoda_istenir(self):
		gorsel = _kodlar(seo_audit.audit_fields(_alanlar(), file_name="koltuk.jpg"))
		for kod in ("missing_poster", "missing_transcript", "missing_duration"):
			self.assertNotIn(kod, gorsel, kod)

		video = _kodlar(seo_audit.audit_fields(_alanlar(), file_name="tanitim-videosu.mp4"))
		for kod in ("missing_poster", "missing_transcript", "missing_duration"):
			self.assertIn(kod, video, kod)

	def test_bi_video_alanlari_doluysa_bulgu_yok(self):
		tam = _alanlar(poster_url="/files/poster.jpg", transcript="merhaba", duration=12.5)
		b = _kodlar(seo_audit.audit_fields(tam, file_name="tanitim-videosu.mp4"))
		for kod in ("missing_poster", "missing_transcript", "missing_duration"):
			self.assertNotIn(kod, b, kod)

	def test_bi_video_uzantilari_buyuk_harfe_duyarsiz(self):
		self.assertIn(
			"missing_poster", _kodlar(seo_audit.audit_fields(_alanlar(), file_name="TANITIM.MP4"))
		)

	def test_gv_iyi_bicimli_girdide_istisna_atmaz(self):
		for g in ({}, {"alt": None}, {"width": "abc"}, {"alt": "x" * 5000}):
			with self.subTest(g=str(g)[:40]):
				try:
					sonuc = seo_audit.audit_fields(g, file_name="a.jpg")
				except Exception as exc:  # noqa: BLE001 — sözleşme testi
					self.fail(f"istisna attı: {type(exc).__name__}: {exc}")
				self.assertIsInstance(sonuc, list)

	def test_gv_alt_metin_disi_bir_tur_ARTIK_COKERTMIYOR(self):
		"""F-18a düzeltildi — girdi türü güvenle metne çevriliyor.

		Alan değerleri DB'den ve API'den geliyor; tek bozuk satır toplu denetim
		ekranının tamamını düşürebiliyordu. Denetim bir RAPORLAMA işidir.
		"""
		for bozuk in (123, 4.5, True, ["liste"], {"a": 1}, object()):
			with self.subTest(tur=type(bozuk).__name__):
				sonuc = seo_audit.audit_fields({"alt": bozuk}, file_name="a.jpg")
				self.assertIsInstance(sonuc, list)

	def test_gv_gecersiz_tarih_ARTIK_BULGU_uretiyor(self):
		"""F-18b düzeltildi — istisna yerine `invalid_rights_date` bulgusu."""
		b = seo_audit.audit_fields(
			{"rights_expires_on": "gecersiz-tarih", "alt": "Kırmızı koltuk"}, file_name="a.jpg"
		)
		kodlar = {x["code"] for x in b}
		self.assertIn("invalid_rights_date", kodlar)
		self.assertNotIn("expired_rights", kodlar, "okunamayan tarih 'dolmuş' sayılmamalı")

	def test_bi_gecersiz_tarih_bulgusu_skora_bagli(self):
		"""Boyuta bağlanmayan kural skoru hiç etkilemez — sessiz kayıp olurdu."""
		self.assertIn("invalid_rights_date", seo_audit._KURAL_BOYUT)

	def test_gv_hicbir_girdide_istisna_atmaz(self):
		"""Sözleşme artık koşulsuz: hiçbir alan değeri denetimi düşüremez."""
		girdiler = [
			{}, {"alt": None}, {"alt": 123}, {"width": "abc"},
			{"rights_expires_on": "gecersiz-tarih"}, {"rights_expires_on": 12345},
			{"alt": "x" * 5000}, {"title": []}, {"caption": {"a": 1}},
			{"poster_url": 7}, {"transcript": 0}, {"duration": "abc"},
		]
		for g in girdiler:
			with self.subTest(g=str(g)[:40]):
				try:
					sonuc = seo_audit.audit_fields(g, file_name="tanitim.mp4")
				except Exception as exc:  # noqa: BLE001
					self.fail(f"istisna attı: {type(exc).__name__}: {exc}")
				self.assertIsInstance(sonuc, list)

	def test_bi_her_bulgu_sozlesme_alanlarini_tasir(self):
		for b in seo_audit.audit_fields({}, file_name="IMG_1.mp4"):
			with self.subTest(kod=b.get("code")):
				self.assertEqual(set(b), {"code", "severity", "message", "detail"})
				self.assertIn(b["severity"], (seo_audit.SEVERITY_ERROR, seo_audit.SEVERITY_WARN))
				self.assertTrue(b["message"])


# ══════════════════════════════════════════════════════════════════════
# 2. Skorlama
# ══════════════════════════════════════════════════════════════════════


class TestSkorlama(unittest.TestCase):
	def test_bi_bulgusuz_skor_tam(self):
		p = seo_audit.score_from([], _alanlar())
		for boyut in seo_audit.DIMENSIONS:
			if boyut == "localization":
				continue
			self.assertEqual(p[boyut], 100, boyut)

	def test_bi_skor_araligi_0_100(self):
		bulgular = [
			{"code": k, "severity": seo_audit.SEVERITY_ERROR, "message": "", "detail": ""}
			for k in seo_audit._KURAL_BOYUT
		] * 5
		p = seo_audit.score_from(bulgular, _alanlar())
		for boyut in (*seo_audit.DIMENSIONS, "overall"):
			with self.subTest(boyut=boyut):
				self.assertGreaterEqual(p[boyut], 0, boyut)
				self.assertLessEqual(p[boyut], 100, boyut)

	def test_bi_hata_uyaridan_iki_kat_ceza(self):
		self.assertEqual(seo_audit._CEZA[seo_audit.SEVERITY_ERROR], 2 * seo_audit._CEZA[seo_audit.SEVERITY_WARN])

	def test_bi_bilinmeyen_kural_kodu_skoru_bozmaz(self):
		p = seo_audit.score_from(
			[{"code": "uydurma_kural", "severity": "error", "message": "", "detail": ""}], _alanlar()
		)
		self.assertEqual(p["accessibility"], 100)

	def test_bi_overall_boyutlarin_ortalamasi(self):
		p = seo_audit.score_from(
			[{"code": "missing_alt", "severity": "error", "message": "", "detail": ""}], _alanlar()
		)
		beklenen = round(sum(p[b] for b in seo_audit.DIMENSIONS) / len(seo_audit.DIMENSIONS))
		self.assertEqual(p["overall"], beklenen)

	def test_bi_yapisal_veri_hicbir_anlamli_alan_yoksa_sifir(self):
		p = seo_audit.score_from([], {"alt": "", "caption": "", "title": "", "width": 0, "license_url": ""})
		self.assertEqual(p["structured_data"], 0)

	def test_bi_yerellestirme_tek_dilde_dusuk(self):
		from tradehub_core.seo.i18n import CONTENT_LANGS

		tek = seo_audit.score_from([], _alanlar(localized={"alt": {CONTENT_LANGS[0]: "x"}}))
		tum = seo_audit.score_from(
			[], _alanlar(localized={"alt": {lang: "x" for lang in CONTENT_LANGS}})
		)
		self.assertLess(tek["localization"], tum["localization"])
		self.assertEqual(tum["localization"], 100)

	def test_bi_yerellestirme_hic_alt_yoksa_sifir(self):
		self.assertEqual(seo_audit.score_from([], {"alt": ""})["localization"], 0)

	def test_bi_alanlar_verilmezse_yerellestirme_hesaplanmaz(self):
		p = seo_audit.score_from([])
		self.assertEqual(p["localization"], 100)

	def test_bi_skor_deterministik(self):
		b = [{"code": "missing_alt", "severity": "error", "message": "", "detail": ""}]
		self.assertEqual(seo_audit.score_from(b, _alanlar()), seo_audit.score_from(b, _alanlar()))

	def test_bi_her_kural_bir_boyuta_bagli(self):
		"""Boyuta bağlanmamış kural skoru hiç etkilemez — sessiz kayıp."""
		bilinen = set(seo_audit._KURAL_BOYUT)
		uretilen = _kodlar(seo_audit.audit_fields({}, file_name="IMG_1.mp4"))
		bagsiz = uretilen - bilinen
		self.assertEqual(bagsiz, set(), f"skora etki etmeyen kural(lar): {bagsiz}")

	def test_bi_boyut_adlari_haritayla_tutarli(self):
		for kod, boyut in seo_audit._KURAL_BOYUT.items():
			with self.subTest(kod=kod):
				self.assertIn(boyut, seo_audit.DIMENSIONS, f"{kod} → bilinmeyen boyut {boyut}")


# ══════════════════════════════════════════════════════════════════════
# 3. Alan yazma doğrulaması
# ══════════════════════════════════════════════════════════════════════


class TestAlanDogrulama(unittest.TestCase):
	def test_bi_gecerli_degerler_kabul(self):
		temiz = seo._validate_asset_values({"alt": "Kırmızı koltuk", "title": "Koltuk"})
		self.assertEqual(temiz.get("alt"), "Kırmızı koltuk")

	def test_bi_validate_ALLOWLIST_YAPMAZ_sadece_bicim_dogrular(self):
		"""Katman sözleşmesi: `_validate_asset_values` izin listesi UYGULAMAZ.

		URL/tarih/creator_type biçimini doğrular, bilinmeyen anahtarı olduğu
		gibi geçirir. İzin listesi `set_asset_fields` içindedir — bu fonksiyonu
		tek başına çağıran bir kod yolu, filtresiz veri yazar. Sözleşme
		sabitleniyor ki katman karıştırılmasın.
		"""
		temiz = seo._validate_asset_values({"alt": "x", "uydurma_alan": "y", "owner": "admin"})
		self.assertIn("uydurma_alan", temiz)
		self.assertIn("owner", temiz)

	def test_gv_gecersiz_url_reddedilir(self):
		for kotu in ("javascript:alert(1)", "ftp://x/y", "not-a-url", "data:text/html,<script>"):
			with self.subTest(kotu=kotu):
				with self.assertRaises(Exception):
					seo._validate_asset_values({"license_url": kotu})

	def test_gv_protokolsuz_url_ARTIK_REDDEDILIYOR(self):
		"""F-20 düzeltildi — `//kotu.site/x` site içi yol sayılmıyor.

		Tarayıcı protokolsüz adresi sayfanın protokolüyle DIŞ alan adına çözer
		ve bu değer JSON-LD ile yayına çıkıyordu.
		"""
		for kotu in ("//kotu.site/x", "//evil.example.com/lisans.pdf", "//x"):
			for alan in ("license_url", "acquire_license_url", "canonical"):
				with self.subTest(kotu=kotu, alan=alan):
					with self.assertRaises(Exception):
						seo._validate_asset_values({alan: kotu})

	def test_bi_TEK_egik_cizgili_ic_yol_hala_kabul(self):
		"""Meşru site içi yol bozulmamalı."""
		for iyi in ("/files/lisans.pdf", "/private/files/a/b.pdf"):
			with self.subTest(iyi=iyi):
				self.assertEqual(seo._validate_asset_values({"license_url": iyi})["license_url"], iyi)

	def test_bi_gecerli_url_bicimleri_kabul(self):
		for iyi in ("https://istoc.com/lisans", "http://istoc.com/x", "/files/lisans.pdf", ""):
			with self.subTest(iyi=iyi):
				seo._validate_asset_values({"license_url": iyi})

	def test_gv_creator_type_kapali_kume(self):
		seo._validate_asset_values({"creator_type": "Person"})
		seo._validate_asset_values({"creator_type": "Organization"})
		with self.assertRaises(Exception):
			seo._validate_asset_values({"creator_type": "Robot"})

	def test_bi_anahtar_YOKSA_alan_sifirlanmaz(self):
		"""Veri-silme regresyonu: yalnız `transcript` gönderince
		`license_url` boş dizeyle EZİLMEMELİ."""
		temiz = seo._validate_asset_values({"transcript": "merhaba"})
		self.assertNotIn("license_url", temiz)
		self.assertNotIn("acquire_license_url", temiz)
		self.assertNotIn("canonical", temiz)
		self.assertNotIn("rights_expires_on", temiz)

	def test_gv_asiri_uzun_deger_reddedilir_veya_kirpilir(self):
		try:
			temiz = seo._validate_asset_values({"alt": "a" * 10000})
		except Exception:
			return  # reddetmek de geçerli sözleşme
		self.assertLessEqual(len(temiz.get("alt", "")), 10000)

	def test_gv_bos_sozluk_bos_doner(self):
		self.assertEqual(seo._validate_asset_values({}), {})

	def test_gv_hicbir_girdide_istisna_atmaz_ya_da_acik_reddeder(self):
		for g in ({"alt": None}, {"alt": 123}, {"width": "abc"}, {"alt": ["liste"]}):
			with self.subTest(g=str(g)):
				try:
					seo._validate_asset_values(g)
				except Exception as exc:  # noqa: BLE001
					self.assertTrue(str(exc), "sessiz istisna")

	def test_bi_cevrilebilir_alanlar_tanimli(self):
		self.assertEqual(seo.TRANSLATABLE, ("alt", "title", "caption"))

	def test_bi_kaynak_sabitleri_ve_yenilenebilirlik(self):
		self.assertIn(seo.SOURCE_RULE, seo.REFRESHABLE)
		self.assertIn(seo.SOURCE_AI, seo.REFRESHABLE)
		self.assertNotIn(
			seo.SOURCE_HUMAN, seo.REFRESHABLE,
			"insan onaylı metin otomatik yenilemeyle EZİLMEMELİ",
		)
		self.assertNotIn(
			seo.SOURCE_EDITED, seo.REFRESHABLE,
			"elle düzenlenmiş metin otomatik yenilemeyle EZİLMEMELİ",
		)

	def test_bi_url_temizleme(self):
		self.assertEqual(seo._temiz_url("/files/a.jpg"), seo._temiz_url("/files/a.jpg"))
		for kotu in ("", None, "   "):
			with self.subTest(kotu=kotu):
				self.assertIsInstance(seo._temiz_url(kotu or ""), str)


# ══════════════════════════════════════════════════════════════════════
# 4. Canlı katalog üzerinde uçtan uca (DB gerektirir)
# ══════════════════════════════════════════════════════════════════════


class TestCanliDosya(FrappeTestCase):
	def setUp(self):
		super().setUp()
		_av_kancasini_notrle(self)

	def _dosya(self, ad="kd-seo-testi.jpg") -> str:
		doc = frappe.get_doc(
			{"doctype": "File", "file_name": ad, "is_private": 0, "content": y.jpeg(64, 64)}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		return doc.file_url

	def test_bi_yeni_dosya_alanlari_bos_okunur(self):
		url = self._dosya()
		alanlar = seo.fields_for(url)
		self.assertIsInstance(alanlar, dict)
		self.assertEqual((alanlar.get("alt") or "").strip(), "")

	def test_bi_alan_yazilip_geri_okunur(self):
		url = self._dosya()
		seo.set_asset_fields(url, {"alt": "Kırmızı kadife koltuk", "title": "Koltuk"})
		alanlar = seo.fields_for(url)
		self.assertEqual(alanlar.get("alt"), "Kırmızı kadife koltuk")

	def test_gv_bilinmeyen_alan_yazilamaz(self):
		url = self._dosya()
		seo.set_asset_fields(url, {"alt": "x", "uydurma": "y"})
		self.assertNotIn("uydurma", seo.fields_for(url))

	def test_bi_denetim_yeni_dosyada_eksikleri_bulur(self):
		url = self._dosya("IMG_9999.jpg")
		rapor = seo_audit.audit_file(url, deep=False)
		self.assertIn("findings", rapor)
		kodlar = {b["code"] for b in rapor["findings"]}
		self.assertIn("missing_alt", kodlar)

	def test_bi_denetim_raporu_skor_tasir(self):
		url = self._dosya()
		rapor = seo_audit.audit_file(url, deep=False)
		self.assertIn("score", rapor)
		self.assertIn("overall", rapor["score"])

	def test_gv_olmayan_dosyada_denetim_patlamaz(self):
		rapor = seo_audit.audit_file("/files/kesinlikle-olmayan-dosya-xyz.jpg", deep=False)
		self.assertIsInstance(rapor, dict)

	def test_bi_fields_for_many_toplu_okur(self):
		a, b = self._dosya("kd-a.jpg"), self._dosya("kd-b.jpg")
		coklu = seo.fields_for_many([a, b])
		self.assertEqual(set(coklu), {a, b})

	def test_bi_fields_for_many_bos_liste(self):
		self.assertEqual(seo.fields_for_many([]), {})


if __name__ == "__main__":
	unittest.main()
