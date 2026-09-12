"""MOGEM-620 — birim/fonksiyon testleri (10 Eylül 2026 teslimatı).

Kapsam: bu turda eklenen HER modülün sözleşmesi.

    media/bulk_ops.py       §14 toplu işlemler
    media/similar.py        §16 görsel benzerlik
    media/tags_source.py    §17 etiket kaynağı
    media/decode_cost.py    §9  çözme maliyeti
    media/meter.py          §18 akış kotaları
    media/seo.py            §2/§11 alan seti + çok dilli + locale ezmesi
    media/seo_audit.py      §13 on alt skor
    media/doc_meta.py       §15 CSV/TXT
    seo/schema_builder.py   §5/§12 bölüm, bölge, GTIN, ProductGroup

Saf fonksiyonlar DB'siz sınanıyor; DB gerektirenler gerçek kayıt açıyor.
Mock YALNIZ kancalarda (`mogem620_ortak.dosya_ac` gerekçesi orada).

Koşum:
    docker exec istoc-backend bench --site tradehub.localhost \\
        run-tests --module tradehub_core.tests.test_mogem620_fonksiyonel
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import bulk_ops, decode_cost, doc_meta, meter, seo, seo_audit, tags_source
from tradehub_core.seo import schema_builder
from tradehub_core.tests.mogem620_ortak import TUZ, dosya_ac, magaza_bul, sil

# ── §14 · Toplu işlemler ────────────────────────────────────────────────


class TestBulkOpsSaf(FrappeTestCase):
	"""`bulk_ops`ın DB'ye dokunmayan tarafı: desen ve doğrulayıcılar."""

	def test_desen_ad_uretir(self):
		self.assertEqual(
			bulk_ops.render_name("{ad}-{sira}", taban="kapak", sira=3, uzanti=".jpg"),
			"kapak-3.jpg",
		)

	def test_sira_dolgusu_uygulanir(self):
		self.assertEqual(
			bulk_ops.render_name("urun-{sira:3}", taban="x", sira=7, uzanti=".png"),
			"urun-007.png",
		)

	def test_uzanti_desende_yoksa_sona_eklenir(self):
		"""Operatörün uzantıyı unutması 200 dosyayı uzantısız bırakmamalı."""
		self.assertTrue(
			bulk_ops.render_name("yeni-ad", taban="x", sira=1, uzanti=".webp").endswith(".webp")
		)

	def test_uzanti_zaten_varsa_iki_kez_eklenmez(self):
		self.assertEqual(
			bulk_ops.render_name("{ad}{uzanti}", taban="a", sira=1, uzanti=".jpg"), "a.jpg"
		)

	def test_ad_tavani_asilmaz(self):
		uzun = bulk_ops.render_name("{ad}", taban="x" * 500, sira=1, uzanti=".jpg")
		self.assertLessEqual(len(uzun), bulk_ops.MAX_NAME)

	def test_yol_ayraci_reddedilir(self):
		"""Desen dosya ADI üretir, yol değil — `..` ve `/` dizin dışına yazma denemesi."""
		for kotu in ("../{ad}", "a/b", "a\\b", "..{ad}"):
			with self.assertRaises(frappe.ValidationError, msg=kotu):
				bulk_ops.validate_pattern(kotu)

	def test_bilinmeyen_yer_tutucu_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			bulk_ops.validate_pattern("{marka}-{sira}")

	def test_bos_desen_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			bulk_ops.validate_pattern("   ")

	def test_robots_beyaz_listesi(self):
		self.assertEqual(bulk_ops.validate_robots("noindex, nofollow"), "noindex, nofollow")
		with self.assertRaises(frappe.ValidationError):
			bulk_ops.validate_robots("noindex, evil-directive")

	def test_bos_robots_bos_doner(self):
		self.assertEqual(bulk_ops.validate_robots("  "), "")

	def test_tavan_asan_secim_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			bulk_ops.normalize_urls([f"/files/{i}.jpg" for i in range(bulk_ops.MAX_BATCH + 1)])

	def test_tekillestirme_ve_sorgu_kirpma(self):
		urls = bulk_ops.normalize_urls(["/files/a.jpg?v=1", "/files/a.jpg", " /files/b.jpg "])
		self.assertEqual(urls, ("/files/a.jpg", "/files/b.jpg"))

	def test_private_gorunurluk_reddedilir(self):
		"""Private geçişi dosyayı diskte taşımayı gerektiriyor; toplu yolda
		yalnız alan yazmak dosyayı public bırakıp kaydı 'private' gösterirdi."""
		with self.assertRaises(frappe.ValidationError):
			bulk_ops.set_indexability_many(["/files/x.jpg"], "Private")

	def test_gecersiz_gorunurluk_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			bulk_ops.set_indexability_many(["/files/x.jpg"], "Yayında")

	def test_beyaz_liste_disi_alan_sessizce_dusmez(self):
		"""`canonical` toplu yazılamaz VE bunu HATA olarak söylemeli.

		Sessiz düşürme burada veri hatasıdır: operatör 200 dosyaya
		canonical yazdığını sanır, yazılmamıştır ve hiçbir uyarı görmez.
		"""
		with self.assertRaises(frappe.ValidationError):
			bulk_ops.set_fields_many(["/files/x.jpg"], {"canonical": "/a"})

	def test_bos_deger_sozlugu_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			bulk_ops.set_fields_many(["/files/x.jpg"], {})


class TestBulkOpsDb(FrappeTestCase):
	"""Gerçek `File` üzerinde toplu yazma ve kısmi başarısızlık sözleşmesi."""

	def setUp(self):
		from tradehub_core.tests.mogem620_ortak import png_uret

		self.dosyalar = []
		for i in range(3):
			d = dosya_ac(f"bulk-{TUZ}-{i}.png", png_uret())
			self.dosyalar.append(d)
			self.addCleanup(sil, "File", d.name)

	def _urls(self):
		return [d.file_url for d in self.dosyalar]

	def test_gorunurluk_toplu_yazilir(self):
		sonuc = bulk_ops.set_indexability_many(self._urls(), "Unlisted")
		self.assertEqual(sonuc["applied"], 3)
		self.assertEqual(sonuc["failed"], [])
		for d in self.dosyalar:
			self.assertEqual(
				frappe.db.get_value("File", d.name, "th_media_visibility"), "Unlisted"
			)

	def test_lisans_alanlari_toplu_yazilir(self):
		sonuc = bulk_ops.set_fields_many(
			self._urls(), {"copyright_notice": f"© Test {TUZ}", "license_url": "/lisans"}
		)
		self.assertEqual(sonuc["applied"], 3)
		alanlar = seo.fields_for(self.dosyalar[0].file_url)
		self.assertEqual(alanlar["copyright_notice"], f"© Test {TUZ}")
		self.assertEqual(alanlar["license_url"], "/lisans")

	def test_toplu_yeniden_adlandirma_adresi_bozmaz(self):
		"""Kabul kriteri: metadata/filename değişikliği Stable Asset ID'yi bozmaz."""
		onceki_url = self.dosyalar[0].file_url
		sonuc = bulk_ops.rename_many(self._urls(), "urun-{sira:2}", start=1)
		self.assertEqual(sonuc["applied"], 3)
		self.assertEqual(
			frappe.db.get_value("File", self.dosyalar[0].name, "file_url"),
			onceki_url,
			"file_url DEĞİŞMEMELİ — 301 köprüsü kuran iş `retro_rename`",
		)
		self.assertEqual(
			frappe.db.get_value("File", self.dosyalar[0].name, "file_name"), "urun-01.png"
		)

	def test_sira_dosya_basina_artar(self):
		bulk_ops.rename_many(self._urls(), "s-{sira}", start=5)
		adlar = sorted(
			frappe.db.get_value("File", d.name, "file_name") for d in self.dosyalar
		)
		self.assertEqual(adlar, ["s-5.png", "s-6.png", "s-7.png"])

	def test_olmayan_dosya_failed_listesine_girer(self):
		"""Kısmi başarısızlık GÖRÜNÜR olmalı — kabul kriteri 17."""
		sonuc = bulk_ops.rename_many(
			[*self._urls(), f"/files/hic-yok-{TUZ}.png"], "x-{sira}"
		)
		self.assertEqual(sonuc["applied"], 3)
		self.assertEqual(len(sonuc["failed"]), 1)
		self.assertIn("hic-yok", sonuc["failed"][0]["file_url"])

	def test_sonuc_sozlesmesi_dort_anahtar(self):
		sonuc = bulk_ops.set_indexability_many(self._urls(), "Public")
		self.assertEqual(set(sonuc), {"applied", "files", "skipped", "failed"})


# ── §17 · Etiket kaynağı ────────────────────────────────────────────────


class TestEtiketKaynagi(FrappeTestCase):
	def test_manuel_makineyi_ezer(self):
		harita = tags_source.birlestir({}, ["a"], tags_source.SOURCE_AI)
		harita = tags_source.birlestir(harita, ["a"], tags_source.SOURCE_MANUAL)
		self.assertEqual(harita["a"], "manual")

	def test_makine_manueli_ezemez(self):
		"""İnsan girdisi makine tarafından geri alınmaz — `seo.REFRESHABLE` kuralının etiket karşılığı."""
		harita = tags_source.birlestir({}, ["a"], tags_source.SOURCE_MANUAL)
		harita = tags_source.birlestir(harita, ["a"], tags_source.SOURCE_AI)
		self.assertEqual(harita["a"], "manual")

	def test_bilinmeyen_kaynak_reddedilir(self):
		with self.assertRaises(ValueError):
			tags_source.birlestir({}, ["a"], "uydurma")

	def test_silinen_etiketin_kaynagi_dusar(self):
		harita = tags_source.birlestir({}, ["a", "b"], tags_source.SOURCE_SYSTEM)
		self.assertEqual(tags_source.senkronla(harita, ["a"]), {"a": "system"})

	def test_bozuk_json_bos_doner_patlamaz(self):
		self.assertEqual(tags_source.parse("{bozuk"), {})
		self.assertEqual(tags_source.parse(None), {})
		self.assertEqual(tags_source.parse(12345), {})

	def test_bilinmeyen_kaynak_degeri_okumada_suzulur(self):
		self.assertEqual(tags_source.parse('{"a": "uydurma", "b": "ai"}'), {"b": "ai"})

	def test_ozet_tum_kaynaklari_kapsar(self):
		ozet = tags_source.ozet({"a": "manual", "b": "ai", "c": "ai"})
		self.assertEqual(ozet["manual"], 1)
		self.assertEqual(ozet["ai"], 2)
		self.assertEqual(set(ozet), set(tags_source.SOURCES))


# ── §9 · Çözme maliyeti ─────────────────────────────────────────────────


class TestDecodeCost(FrappeTestCase):
	def test_avif_jpegden_pahali(self):
		"""Modülün varlık sebebi: bayt düşerken çözme maliyeti YÜKSELEBİLİR."""
		jpeg = decode_cost.estimate(width=2000, height=2000, file_format="jpg")
		avif = decode_cost.estimate(width=2000, height=2000, file_format="avif")
		self.assertGreater(avif, jpeg)

	def test_bilinmeyen_format_tabanda(self):
		self.assertEqual(
			decode_cost.estimate(width=1000, height=1000, file_format="xyz"),
			decode_cost.estimate(width=1000, height=1000, file_format="jpg"),
		)

	def test_boyutsuz_sifir_doner(self):
		"""'Bilinmiyor' ile 'ucuz' AYNI şey değil — 0 açıkça 'ölçülemedi' demek."""
		self.assertEqual(decode_cost.estimate(width=0, height=0, file_format="jpg"), 0.0)

	def test_alfa_ve_progressive_carpani(self):
		taban = decode_cost.estimate(width=1000, height=1000, file_format="jpg")
		self.assertGreater(
			decode_cost.estimate(width=1000, height=1000, file_format="jpg", has_alpha=True), taban
		)
		self.assertGreater(
			decode_cost.estimate(width=1000, height=1000, file_format="jpg", progressive=True), taban
		)

	def test_media_size_dort_bileseni_tasir(self):
		"""§9: byte + pixel + decode + render size BİRLİKTE."""
		olcum = decode_cost.media_size(
			width=4000, height=3000, bytes_=1_500_000, file_format="jpg",
			rendered_width=400, rendered_height=300,
		)
		self.assertEqual(olcum["bytes"], 1_500_000)
		self.assertEqual(olcum["megapixels"], 12.0)
		self.assertGreater(olcum["decode_cost"], 0)
		self.assertEqual(olcum["oversize_ratio"], 100.0)

	def test_render_boyutu_yoksa_oran_none(self):
		"""Sıfır yazmak 'hiç büyütülmemiş' iddiası olurdu — o yanlış."""
		olcum = decode_cost.media_size(width=100, height=100, bytes_=10, file_format="jpg")
		self.assertIsNone(olcum["oversize_ratio"])

	def test_format_of(self):
		self.assertEqual(decode_cost.format_of("a/b/c.JPG"), "jpg")
		self.assertEqual(decode_cost.format_of("uzantisiz"), "")

	def test_denetim_kurali_boyuta_bagli(self):
		self.assertEqual(seo_audit._KURAL_BOYUT["expensive_decode"], "performance")


# ── §13 · On alt skor ───────────────────────────────────────────────────


class TestOnBoyut(FrappeTestCase):
	def test_on_boyut_var(self):
		"""Kabul kriteri 16: toplam puan + 10 alt puan."""
		self.assertEqual(len(seo_audit.DIMENSIONS), 10)
		self.assertIn("visual_search", seo_audit.DIMENSIONS)
		self.assertIn("ai_readiness", seo_audit.DIMENSIONS)

	def test_skor_tum_boyutlari_dondurur(self):
		skor = seo_audit.score_from([], {"alt": "x"})
		for boyut in (*seo_audit.DIMENSIONS, "overall"):
			self.assertIn(boyut, skor)
			self.assertGreaterEqual(skor[boyut], 0)
			self.assertLessEqual(skor[boyut], 100)

	def test_gorsel_arama_sinyalle_yukselir(self):
		bos = seo_audit.score_from([], {})["visual_search"]
		dolu = seo_audit.score_from(
			[], {"perceptual_hash": "abc", "width": 100, "alt": "a", "tags": "t", "has_text": True}
		)["visual_search"]
		self.assertEqual(bos, 0)
		self.assertEqual(dolu, 100)

	def test_ai_hazirlik_sinyalle_yukselir(self):
		bos = seo_audit.score_from([], {})["ai_readiness"]
		dolu = seo_audit.score_from(
			[],
			{
				"description": "d", "caption": "c", "canonical": "/x",
				"license_url": "/l", "creator": "k", "transcript": "t",
			},
		)["ai_readiness"]
		self.assertEqual(bos, 0)
		self.assertEqual(dolu, 100)

	def test_alt_ai_hazirliga_girmez(self):
		"""§3: erişilebilirlik ALT'ı ile SEO açıklaması AYRI amaçlar."""
		self.assertEqual(seo_audit.score_from([], {"alt": "uzun bir alt metni"})["ai_readiness"], 0)

	def test_transkript_gorsel_aramaya_girmez(self):
		"""Transkript sesin metni; görselin tanınabilirliğine katkısı yok."""
		self.assertEqual(seo_audit.score_from([], {"transcript": "uzun metin"})["visual_search"], 0)

	def test_overall_on_boyutun_ortalamasi(self):
		skor = seo_audit.score_from([], {"alt": "x", "width": 10})
		beklenen = round(sum(skor[b] for b in seo_audit.DIMENSIONS) / len(seo_audit.DIMENSIONS))
		self.assertEqual(skor["overall"], beklenen)


# ── §2 / §11 · Alan seti ve çok dillilik ────────────────────────────────


class TestAlanSeti(FrappeTestCase):
	def setUp(self):
		from tradehub_core.tests.mogem620_ortak import png_uret

		self.doc = dosya_ac(f"alan-{TUZ}.png", png_uret())
		self.addCleanup(sil, "File", self.doc.name)

	def test_yeni_alanlar_yazilip_okunur(self):
		seo.set_asset_fields(
			self.doc.file_url,
			{
				"long_description": "uzun",
				"keywords": "a,b",
				"entities": "BMW",
				"content_purpose": "katalog",
				"source": "ajans",
				"creator_role": "photographer",
			},
		)
		alanlar = seo.fields_for(self.doc.file_url)
		self.assertEqual(alanlar["keywords"], "a,b")
		self.assertEqual(alanlar["creator_role"], "photographer")
		self.assertEqual(alanlar["entities"], "BMW")

	def test_description_dile_gore_cozulur(self):
		"""§11: description artık locale bazında."""
		seo.set_asset_fields(
			self.doc.file_url, {"description_tr": "Türkçe", "description_en": "English"}
		)
		self.assertEqual(seo.fields_for(self.doc.file_url, lang="tr")["description"], "Türkçe")
		self.assertEqual(seo.fields_for(self.doc.file_url, lang="en")["description"], "English")

	def test_eksik_dil_varsayilana_duser(self):
		seo.set_asset_fields(self.doc.file_url, {"description_tr": "Yalnız TR"})
		self.assertEqual(seo.fields_for(self.doc.file_url, lang="ru")["description"], "Yalnız TR")

	def test_transkript_ve_altyazi_cok_dilli(self):
		seo.set_asset_fields(
			self.doc.file_url,
			{"transcript_en": "hello", "captions_url_en": "/c/en.vtt", "captions_url_tr": "/c/tr.vtt"},
		)
		en = seo.fields_for(self.doc.file_url, lang="en")
		self.assertEqual(en["transcript"], "hello")
		self.assertEqual(en["captions_url"], "/c/en.vtt")
		self.assertEqual(seo.fields_for(self.doc.file_url, lang="tr")["captions_url"], "/c/tr.vtt")

	def test_localized_sozlugu_varlik_alanlarini_da_tasir(self):
		seo.set_asset_fields(self.doc.file_url, {"description_en": "E"})
		alanlar = seo.fields_for(self.doc.file_url)
		self.assertEqual(alanlar["localized"]["description"]["en"], "E")

	def test_varlik_alani_kullanim_ezmesi_olarak_yazilamaz(self):
		"""Sessizce düşürmek yerine HATA: çağıran kaydedildiğini sanmasın."""
		with self.assertRaises(frappe.ValidationError):
			seo.set_override(
				self.doc.file_url,
				ref_doctype="Listing",
				ref_name="X",
				ref_field="primary_image",
				values={"description_en": "olmaz"},
			)

	def test_geo_bicimi_dogrulanir(self):
		seo.set_asset_fields(self.doc.file_url, {"geo": "41.0082, 28.9784"})
		self.assertEqual(seo.fields_for(self.doc.file_url)["geo"], "41.0082,28.9784")
		for kotu in ("41.0", "abc", "41.0;28.9"):
			with self.assertRaises(frappe.ValidationError, msg=kotu):
				seo.set_asset_fields(self.doc.file_url, {"geo": kotu})

	def test_geo_araligi_dogrulanir(self):
		with self.assertRaises(frappe.ValidationError):
			seo.set_asset_fields(self.doc.file_url, {"geo": "95.0,0.0"})

	def test_ulke_kodu_iki_harf(self):
		seo.set_asset_fields(self.doc.file_url, {"country": "tr"})
		self.assertEqual(seo.fields_for(self.doc.file_url)["country"], "TR")
		with self.assertRaises(frappe.ValidationError):
			seo.set_asset_fields(self.doc.file_url, {"country": "TUR"})

	def test_yas_siniri_yalniz_18arti(self):
		seo.set_asset_fields(self.doc.file_url, {"age_restriction": "18+"})
		with self.assertRaises(frappe.ValidationError):
			seo.set_asset_fields(self.doc.file_url, {"age_restriction": "16 yaş"})

	def test_bolumler_json_dogrulanir_ve_siralanir(self):
		seo.set_asset_fields(
			self.doc.file_url,
			{"chapters": json.dumps([{"start": 60, "title": "B"}, {"start": 0, "title": "A"}])},
		)
		bolumler = json.loads(seo.fields_for(self.doc.file_url)["chapters"])
		self.assertEqual([b["title"] for b in bolumler], ["A", "B"])

	def test_bozuk_bolum_json_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			seo.set_asset_fields(self.doc.file_url, {"chapters": "{bozuk"})
		with self.assertRaises(frappe.ValidationError):
			seo.set_asset_fields(self.doc.file_url, {"chapters": json.dumps([{"title": "start yok"}])})

	def test_izinli_bolgeler_normallesir(self):
		seo.set_asset_fields(self.doc.file_url, {"regions_allowed": "tr, de ,tr"})
		self.assertEqual(seo.fields_for(self.doc.file_url)["regions_allowed"], "TR,DE")


class TestLocaleMedyaEzmesi(FrappeTestCase):
	def setUp(self):
		from tradehub_core.tests.mogem620_ortak import png_uret

		self.kaynak = dosya_ac(f"kaynak-{TUZ}.png", png_uret())
		self.arapca = dosya_ac(f"arapca-{TUZ}.png", png_uret(renk="blue"))
		self.addCleanup(sil, "File", self.kaynak.name)
		self.addCleanup(sil, "File", self.arapca.name)

	def _ezme(self, locale="ar", **kw):
		doc = frappe.get_doc(
			{
				"doctype": seo.LOCALE_VARIANT_DOCTYPE,
				"file_url": self.kaynak.file_url,
				"locale": locale,
				"variant_url": kw.get("variant_url", self.arapca.file_url),
				**{k: v for k, v in kw.items() if k != "variant_url"},
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(sil, seo.LOCALE_VARIANT_DOCTYPE, doc.name)
		return doc

	def test_ezme_yoksa_kaynak_doner(self):
		sonuc = seo.resolve_media_for_locale(self.kaynak.file_url, lang="ar")
		self.assertEqual(sonuc["file_url"], self.kaynak.file_url)
		self.assertFalse(sonuc["overridden"])

	def test_ezme_varsa_o_dilde_baska_dosya_doner(self):
		"""Kabul kriteri 14: locale-specific media override ÇALIŞIR."""
		self._ezme()
		sonuc = seo.resolve_media_for_locale(self.kaynak.file_url, lang="ar")
		self.assertEqual(sonuc["file_url"], self.arapca.file_url)
		self.assertTrue(sonuc["overridden"])

	def test_ezme_baska_dili_etkilemez(self):
		self._ezme(locale="ar")
		self.assertEqual(
			seo.resolve_media_for_locale(self.kaynak.file_url, lang="en")["file_url"],
			self.kaynak.file_url,
		)

	def test_kaynagin_kendisi_ezme_olamaz(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": seo.LOCALE_VARIANT_DOCTYPE,
					"file_url": self.kaynak.file_url,
					"locale": "en",
					"variant_url": self.kaynak.file_url,
				}
			).insert(ignore_permissions=True)

	def test_bos_ezme_reddedilir(self):
		"""İkisi de boş satır 'ezme tanımlı' yanılsaması üretirdi."""
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": seo.LOCALE_VARIANT_DOCTYPE,
					"file_url": self.kaynak.file_url,
					"locale": "en",
				}
			).insert(ignore_permissions=True)

	def test_ayni_dosya_dil_ikili_kaydi_reddedilir(self):
		self._ezme(locale="ru")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": seo.LOCALE_VARIANT_DOCTYPE,
					"file_url": self.kaynak.file_url,
					"locale": "ru",
					"variant_url": self.arapca.file_url,
				}
			).insert(ignore_permissions=True)

	def test_gecersiz_dil_reddedilir(self):
		with self.assertRaises(Exception):
			frappe.get_doc(
				{
					"doctype": seo.LOCALE_VARIANT_DOCTYPE,
					"file_url": self.kaynak.file_url,
					"locale": "zz",
					"variant_url": self.arapca.file_url,
				}
			).insert(ignore_permissions=True)


# ── §5 / §12 · Yapısal veri ─────────────────────────────────────────────


class TestVideoSemasiYeniAlanlar(FrappeTestCase):
	def _temel(self, **ek):
		return {
			"poster_url": "/files/p.jpg",
			"title": "Tanıtım",
			"duration": 90,
			**ek,
		}

	def test_izinli_bolgeler_dizi_olur(self):
		obj = schema_builder.build_video_object(
			self._temel(regions_allowed="TR,DE"), "https://x.test", content_url="/files/v.mp4"
		)
		self.assertEqual(obj["regionsAllowed"], ["TR", "DE"])

	def test_yas_siniri_isfamilyfriendly_false_uretir(self):
		obj = schema_builder.build_video_object(
			self._temel(age_restriction="18+"), "https://x.test", content_url="/files/v.mp4"
		)
		self.assertIs(obj["isFamilyFriendly"], False)

	def test_yas_siniri_yoksa_anahtar_hic_girmez(self):
		obj = schema_builder.build_video_object(
			self._temel(), "https://x.test", content_url="/files/v.mp4"
		)
		self.assertNotIn("isFamilyFriendly", obj)

	def test_bolumler_clip_listesine_donusur(self):
		obj = schema_builder.build_video_object(
			self._temel(chapters=json.dumps([{"start": 0, "title": "Giriş"}, {"start": 30, "title": "Detay"}])),
			"https://x.test",
			content_url="/files/v.mp4",
		)
		self.assertEqual(len(obj["hasPart"]), 2)
		self.assertEqual(obj["hasPart"][0]["@type"], "Clip")
		self.assertEqual(obj["hasPart"][1]["startOffset"], 30)
		self.assertTrue(obj["hasPart"][1]["url"].endswith("?t=30"))

	def test_bozuk_bolum_tum_nesneyi_dusurmez(self):
		"""Yamadan önce yazılmış/elle bozulmuş satır VideoObject'i öldürmemeli."""
		obj = schema_builder.build_video_object(
			self._temel(chapters="{bozuk"), "https://x.test", content_url="/files/v.mp4"
		)
		self.assertIsNotNone(obj)
		self.assertNotIn("hasPart", obj)

	def test_baslıksiz_bolum_atlanir(self):
		obj = schema_builder.build_video_object(
			self._temel(chapters=json.dumps([{"start": 5}, {"start": 10, "title": "Var"}])),
			"https://x.test",
			content_url="/files/v.mp4",
		)
		self.assertEqual(len(obj["hasPart"]), 1)


class TestSemantikAlanlar(FrappeTestCase):
	def test_anahtar_kelimeler_dizi_olur(self):
		nesne = schema_builder.build_image_object(
			{"file_url": "/files/a.jpg", "alt": "x", "keywords": "bmw, x5 , suv"}, "https://x.test"
		)
		self.assertEqual(nesne["keywords"], ["bmw", "x5", "suv"])

	def test_konum_place_olur(self):
		nesne = schema_builder.build_image_object(
			{"file_url": "/files/a.jpg", "alt": "x", "location": "İstoç", "country": "TR", "geo": "41.0,28.9"},
			"https://x.test",
		)
		yer = nesne["contentLocation"]
		self.assertEqual(yer["@type"], "Place")
		self.assertEqual(yer["name"], "İstoç")
		self.assertEqual(yer["geo"]["latitude"], 41.0)
		self.assertEqual(yer["address"]["addressCountry"], "TR")

	def test_bozuk_koordinat_nesneyi_dusurmez(self):
		nesne = schema_builder.build_image_object(
			{"file_url": "/files/a.jpg", "alt": "x", "location": "İstoç", "geo": "bozuk"},
			"https://x.test",
		)
		self.assertEqual(nesne["contentLocation"]["name"], "İstoç")
		self.assertNotIn("geo", nesne["contentLocation"])

	def test_konum_verisi_yoksa_anahtar_girmez(self):
		nesne = schema_builder.build_image_object(
			{"file_url": "/files/a.jpg", "alt": "x"}, "https://x.test"
		)
		self.assertNotIn("contentLocation", nesne)


class TestProductGroup(FrappeTestCase):
	def _listing(self, **ek):
		return {
			"name": "LST-TEST",
			"slug": "test",
			"title": "Test",
			"price": 10,
			"currency": "TRY",
			**ek,
		}

	def _sema(self, listing):
		return schema_builder.build_product_schema(
			listing=listing, site_url="https://x.test", brand=None,
			category_name=None, aggregate_rating=None, reviews=None,
		)

	def test_gtin_basilir(self):
		self.assertEqual(self._sema(self._listing(gtin="8690000000001"))["gtin"], "8690000000001")

	def test_varyantsiz_ilan_product_kalir(self):
		self.assertEqual(self._sema(self._listing())["@type"], "Product")

	def test_varyantli_ilan_productgroup_olur(self):
		"""§12: varyantlı ürün `ProductGroup`; her varyant bir `Product`."""
		sema = self._sema(
			self._listing(
				has_variants=1,
				variants=[
					{"attribute_type": "Renk", "attribute_value": "Kırmızı", "variant_sku": "K1"},
					{"attribute_type": "Renk", "attribute_value": "Mavi", "variant_sku": "M1"},
				],
			)
		)
		self.assertEqual(sema["@type"], "ProductGroup")
		self.assertEqual(len(sema["hasVariant"]), 2)
		self.assertEqual(sema["variesBy"], ["Renk"])
		self.assertEqual(sema["hasVariant"][0]["sku"], "K1")

	def test_kimliksiz_varyant_semaya_girmez(self):
		"""SKU'su ve GTIN'i olmayan varyantı tüketici eşleştiremez."""
		sema = self._sema(
			self._listing(has_variants=1, variants=[{"attribute_value": "Kırmızı"}])
		)
		self.assertEqual(sema["@type"], "Product")

	def test_varyant_gtini_basilir(self):
		sema = self._sema(
			self._listing(has_variants=1, variants=[{"variant_gtin": "8690000000002"}])
		)
		self.assertEqual(sema["hasVariant"][0]["gtin"], "8690000000002")

	def test_stoksuz_varyant_outofstock(self):
		sema = self._sema(
			self._listing(
				has_variants=1,
				variants=[{"variant_sku": "S1", "variant_price": 5, "variant_stock": 0}],
			)
		)
		self.assertIn("OutOfStock", sema["hasVariant"][0]["offers"]["availability"])

	def test_urun_kimligi_tipten_bagimsiz(self):
		"""`@id` her iki tipte de `#product` — tüketiciler kimliğe bakmalı."""
		for listing in (
			self._listing(),
			self._listing(has_variants=1, variants=[{"variant_sku": "A"}]),
		):
			self.assertTrue(self._sema(listing)["@id"].endswith("#product"))


# ── §15 · CSV / TXT ─────────────────────────────────────────────────────


class TestDuzMetinCikarimi(FrappeTestCase):
	def test_csv_uzantisi_desteklenir(self):
		self.assertIn(".csv", doc_meta.DOC_UZANTILAR)
		self.assertIn(".txt", doc_meta.DOC_UZANTILAR)

	def test_csv_metni_ve_basligi_cikar(self):
		icerik = b"urun,fiyat\nkalem,10\n"
		doc = dosya_ac(f"katalog-{TUZ}.csv", icerik)
		self.addCleanup(sil, "File", doc.name)
		sonuc = doc_meta.extract(doc.file_url)
		self.assertTrue(sonuc["ok"])
		self.assertIn("kalem", sonuc["text"])
		self.assertEqual(sonuc["title"], "urun,fiyat")

	def test_sayfa_sayisi_eksi_bir(self):
		"""Düz metinde 'sayfa' yok; 0 yazmak backfill'i sonsuz döngüye sokardı."""
		doc = dosya_ac(f"not-{TUZ}.txt", b"tek satir")
		self.addCleanup(sil, "File", doc.name)
		self.assertEqual(doc_meta.extract(doc.file_url)["page_count"], -1)

	def test_bos_dosya_ok_false(self):
		doc = dosya_ac(f"bos-{TUZ}.txt", b"   \n  ")
		self.addCleanup(sil, "File", doc.name)
		sonuc = doc_meta.extract(doc.file_url)
		self.assertFalse(sonuc["ok"])
		self.assertEqual(sonuc["reason"], "bos_dosya")

	def test_utf8_olmayan_kodlama_metni_kaybetmez(self):
		"""Türkçe Excel CSV'si cp1254 — bir kodlama hatası tüm metni yutmamalı."""
		doc = dosya_ac(f"tr-{TUZ}.csv", "ürün;fiyat\nçekiç;20\n".encode("cp1254"))
		self.addCleanup(sil, "File", doc.name)
		sonuc = doc_meta.extract(doc.file_url)
		self.assertTrue(sonuc["ok"])
		self.assertIn("fiyat", sonuc["text"])

	def test_metin_tavanda_kesilir(self):
		doc = dosya_ac(f"buyuk-{TUZ}.txt", b"a" * (doc_meta.TEXT_TAVAN * 2))
		self.addCleanup(sil, "File", doc.name)
		self.assertLessEqual(len(doc_meta.extract(doc.file_url)["text"]), doc_meta.TEXT_TAVAN)

	def test_apply_metni_kalici_yazar(self):
		doc = dosya_ac(f"uygula-{TUZ}.txt", b"aranabilir icerik")
		self.addCleanup(sil, "File", doc.name)
		self.assertTrue(doc_meta.apply(doc.file_url))
		self.assertIn(
			"aranabilir", frappe.db.get_value("File", doc.name, "th_media_extracted_text")
		)


# ── §18 · Akış kotaları ─────────────────────────────────────────────────


class TestMeter(FrappeTestCase):
	def setUp(self):
		self.store = magaza_bul()
		if not self.store:
			self.skipTest("Mağaza yok — kota testi kurulamaz.")
		self.addCleanup(self._temizle)

	def _temizle(self):
		for ad in frappe.get_all(
			meter.DOCTYPE, filters={"store": self.store, "period_key": meter.period_key()}, pluck="name"
		):
			sil(meter.DOCTYPE, ad)

	def test_donem_anahtari_bicimi(self):
		self.assertRegex(meter.period_key(), r"^\d{4}-\d{2}$")

	def test_sayac_artar_ve_birikir(self):
		meter.record(self.store, meter.METRIC_TRANSFORMATIONS, 3)
		meter.record(self.store, meter.METRIC_TRANSFORMATIONS, 2)
		self.assertEqual(meter.consumed(self.store, meter.METRIC_TRANSFORMATIONS), 5)

	def test_negatif_ve_sifir_sayilmaz(self):
		"""Negatif tüketim kotayı geri kazanmanın yolu olurdu."""
		meter.record(self.store, meter.METRIC_AI, -5)
		meter.record(self.store, meter.METRIC_AI, 0)
		self.assertEqual(meter.consumed(self.store, meter.METRIC_AI), 0)

	def test_bilinmeyen_olcum_yazilmaz(self):
		meter.record(self.store, "uydurma_olcum", 10)
		self.assertEqual(
			frappe.db.count(meter.DOCTYPE, {"store": self.store, "metric": "uydurma_olcum"}), 0
		)

	def test_tanimsiz_kota_fail_open(self):
		"""Yeni bir kotanın ilk etkisi 'herkesin işi durdu' olmamalı."""
		from unittest import mock as _mock

		with _mock.patch.object(meter, "limit_for", return_value=None):
			karar = meter.check(self.store, meter.METRIC_TRANSFORMATIONS, incoming=10**9)
		self.assertTrue(karar["allowed"])
		self.assertEqual(karar["reason"], "unconfigured")

	def test_sifir_kota_reddeder(self):
		from unittest import mock as _mock

		with _mock.patch.object(meter, "limit_for", return_value=0):
			karar = meter.check(self.store, meter.METRIC_AI, incoming=1)
		self.assertFalse(karar["allowed"])
		self.assertEqual(karar["reason"], "disabled")

	def test_eksi_bir_sinirsiz(self):
		from unittest import mock as _mock

		with _mock.patch.object(meter, "limit_for", return_value=-1):
			karar = meter.check(self.store, meter.METRIC_AI, incoming=10**9)
		self.assertTrue(karar["allowed"])
		self.assertEqual(karar["reason"], "unlimited")

	def test_asim_tespit_edilir(self):
		from unittest import mock as _mock

		meter.record(self.store, meter.METRIC_AI, 9)
		with _mock.patch.object(meter, "limit_for", return_value=10):
			self.assertTrue(meter.check(self.store, meter.METRIC_AI, incoming=1)["allowed"])
			self.assertFalse(meter.check(self.store, meter.METRIC_AI, incoming=2)["allowed"])

	def test_bant_genisligi_mb_bayta_cevrilir(self):
		"""Plan MB der, sayaç bayt tutar — dönüşüm TEK yerde."""
		from unittest import mock as _mock

		with _mock.patch(
			"tradehub_core.entitlement.core.get_quota_limits",
			return_value={"quota.max_bandwidth_mb_per_month": 5},
		):
			self.assertEqual(meter.limit_for(self.store, meter.METRIC_BANDWIDTH), 5 * 1024 * 1024)

	def test_ozet_uc_olcumu_kapsar(self):
		ozet = meter.summary(self.store)
		self.assertEqual(set(ozet), set(meter.QUOTA_KEYS))
		for deger in ozet.values():
			self.assertIn("period", deger)
