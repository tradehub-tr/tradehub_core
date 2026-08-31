"""Alt üretimi, indexability, işaretleme ve denetim — TUR-135 Dilim 2+3.

Karar belgesi: `docs/MEDYA-SEO-SOZLESMESI.md` §5, §6.

Sabitlenen kurallar:
  1. Üretim zinciri sırası ve "boş, yanlıştan iyidir" ilkesi
  2. İnsan yazdığı metin otomatik EZİLMEZ (`alt_source` kapısı)
  3. Sıra numarası ilk görselde YOK, sonrakilerde okunabilir biçimde
  4. Indexability: private/çöp/karantina/süresi dolmuş → noindex
  5. Render ipuçları: tek LCP adayı, gerisi lazy
  6. ImageObject yalnız anlamlı alan varsa; yoksa düz URL (çıktı şişmesin)
  7. Görsel sitemap namespace'i yalnız görsel varsa bildirilir
  8. Denetim kuralları ve alt kırılımlı skor

Koşum:
    docker exec -w /home/frappe/frappe-bench istoc-backend bench \\
        --site tradehub.localhost run-tests \\
        --module tradehub_core.tests.test_media_seo_pipeline
"""

from __future__ import annotations

import contextlib
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_admin
from tradehub_core.media import seo, seo_audit, seo_generate, seo_index, seo_render
from tradehub_core.seo import schema_builder, sitemap_generator

_TUZ: str = frappe.generate_hash(length=10)
_SITE: str = "https://ornek.test"


def _dosya(ad: str):
	with mock.patch("tradehub_core.media.av.enqueue_scan"):
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": ad,
				"is_private": 0,
				"content": f"pipeline {_TUZ} {ad}".encode(),
			}
		)
		doc.insert(ignore_permissions=True)
	return doc


def _sil(doctype: str, name: str) -> None:
	with contextlib.suppress(Exception):
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		frappe.db.commit()


class TestAltUretimi(FrappeTestCase):
	def test_baglam_yoksa_bos_birakilir(self):
		"""§5.1 adım 5 — dosya adından metin türetilmez."""
		doc = _dosya(f"IMG_4821-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		self.assertEqual(seo_generate.generate_alt(doc.file_url), "")

		sonuc = seo_generate.refresh_alt(doc.file_url)
		self.assertFalse(sonuc["written"])
		self.assertEqual(sonuc["reason"], "no_context")

	def test_dosya_kaydi_yoksa_yazdim_demez(self):
		"""`set_asset_fields` 0 satır güncelleyince `written=True` dönüyordu;
		panel sonsuz "alt metni yok → üret → yok" döngüsüne giriyordu."""
		hayalet = f"/files/hayalet-{_TUZ}.jpg"
		with mock.patch.object(seo_generate, "_listing_baglami", return_value=("Ürün", 1)):
			sonuc = seo_generate.refresh_alt(hayalet)
		self.assertFalse(sonuc["written"])
		self.assertEqual(sonuc["reason"], "no_file")
		self.assertEqual(sonuc["alt"], "Ürün")

	def test_listing_zinciri(self):
		doc = _dosya(f"urun-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		with mock.patch.object(seo_generate, "_listing_baglami", return_value=("Kırmızı Çanta — Marka X", 1)):
			self.assertEqual(seo_generate.generate_alt(doc.file_url), "Kırmızı Çanta — Marka X")

	def test_sira_numarasi_ilk_gorselde_yok(self):
		"""Tek görselli üründe "(1. görsel)" hiçbir şey ifade etmiyor."""
		doc = _dosya(f"sira-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		with mock.patch.object(seo_generate, "_listing_baglami", return_value=("Ürün", 1)):
			self.assertEqual(seo_generate.generate_alt(doc.file_url), "Ürün")
		with mock.patch.object(seo_generate, "_listing_baglami", return_value=("Ürün", 3)):
			# Çıplak "- 3" DEĞİL: ekran okuyucu onu "eksi üç" diye okuyor.
			self.assertEqual(seo_generate.generate_alt(doc.file_url), "Ürün (3. görsel)")

	def test_insan_metni_ezilmez(self):
		doc = _dosya(f"insan-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		seo.set_asset_fields(doc.file_url, {"alt_tr": "insanın yazdığı", "alt_source": seo.SOURCE_HUMAN})
		with mock.patch.object(seo_generate, "_listing_baglami", return_value=("Kural metni", 1)):
			sonuc = seo_generate.refresh_alt(doc.file_url)
		self.assertFalse(sonuc["written"])
		self.assertIn("human", sonuc["reason"])
		self.assertEqual(seo.fields_for(doc.file_url)["alt"], "insanın yazdığı")

	def test_kural_metni_yenilenebilir(self):
		doc = _dosya(f"kural-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		with mock.patch.object(seo_generate, "_listing_baglami", return_value=("İlk metin", 1)):
			seo_generate.refresh_alt(doc.file_url)
		self.assertEqual(seo.fields_for(doc.file_url)["alt"], "İlk metin")

		with mock.patch.object(seo_generate, "_listing_baglami", return_value=("Yeni metin", 1)):
			sonuc = seo_generate.refresh_alt(doc.file_url)
		self.assertTrue(sonuc["written"])
		self.assertEqual(seo.fields_for(doc.file_url)["alt"], "Yeni metin")

	def test_force_insan_metnini_ezer(self):
		doc = _dosya(f"force-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		seo.set_asset_fields(doc.file_url, {"alt_tr": "insan", "alt_source": seo.SOURCE_HUMAN})
		with mock.patch.object(seo_generate, "_listing_baglami", return_value=("kural", 1)):
			sonuc = seo_generate.refresh_alt(doc.file_url, force=True)
		self.assertTrue(sonuc["written"])

	# ── Dilim 8 (Bulk Localization) — dil parametresi ──────────────────────

	def test_en_uretim_title_en_doluysa(self):
		"""Kabul kriteri 1: `title_en` dolu bir ilanın görseli `alt_en` kazanır."""
		dosya = _dosya(f"en-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		ilan = _ilan_olustur(f"TR Başlık {_TUZ}", dosya.file_url)
		self.addCleanup(_sil, "Listing", ilan)
		frappe.db.set_value("Listing", ilan, "title_en", f"EN Title {_TUZ}")

		self.assertEqual(seo_generate.generate_alt(dosya.file_url, lang="en"), f"EN Title {_TUZ}")
		sonuc = seo_generate.refresh_alt(dosya.file_url, lang="en")
		self.assertTrue(sonuc["written"])
		self.assertEqual(seo.fields_for(dosya.file_url, lang="en")["alt"], f"EN Title {_TUZ}")
		# tr çağrısı etkilenmedi — mevcut davranış birebir korunur.
		self.assertEqual(seo_generate.generate_alt(dosya.file_url), f"TR Başlık {_TUZ}")

	def test_no_translation_title_en_bos(self):
		"""Kabul kriteri 2: `title_en` boş ilanın görseline `alt_en` YAZILMAZ —
		kopyalama yok (L1)."""
		dosya = _dosya(f"notr-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		ilan = _ilan_olustur(f"Yalnız TR {_TUZ}", dosya.file_url)
		self.addCleanup(_sil, "Listing", ilan)

		self.assertEqual(seo_generate.generate_alt(dosya.file_url, lang="en"), "")
		sonuc = seo_generate.refresh_alt(dosya.file_url, lang="en")
		self.assertFalse(sonuc["written"])
		self.assertEqual(sonuc["reason"], "no_translation")

	def test_insan_damgasi_dil_korlukle_korunur(self):
		"""Kabul kriteri 3 / L6: insan damgalı dosyanın `alt_en` kolonuna da
		yazılmaz — damga dil-körü, tr'de yazılmışsa en için de geçerli."""
		dosya = _dosya(f"insan-en-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		ilan = _ilan_olustur(f"İnsan Testi {_TUZ}", dosya.file_url)
		self.addCleanup(_sil, "Listing", ilan)
		frappe.db.set_value("Listing", ilan, "title_en", f"Human EN {_TUZ}")
		seo.set_asset_fields(dosya.file_url, {"alt_tr": "insanın yazdığı", "alt_source": seo.SOURCE_HUMAN})

		sonuc = seo_generate.refresh_alt(dosya.file_url, lang="en")
		self.assertFalse(sonuc["written"])
		self.assertIn("human", sonuc["reason"])
		self.assertFalse(frappe.db.get_value("File", {"file_url": dosya.file_url}, "th_media_alt_en"))

	def test_force_ile_en_insan_metnini_ezer(self):
		"""`force` yalnız yönetici aracı için — REFRESHABLE gate'i lang'den
		bağımsız olarak aşar."""
		dosya = _dosya(f"force-en-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		ilan = _ilan_olustur(f"Force EN {_TUZ}", dosya.file_url)
		self.addCleanup(_sil, "Listing", ilan)
		frappe.db.set_value("Listing", ilan, "title_en", f"Force EN Title {_TUZ}")
		seo.set_asset_fields(dosya.file_url, {"alt_en": "insan en", "alt_source": seo.SOURCE_HUMAN})

		sonuc = seo_generate.refresh_alt(dosya.file_url, lang="en", force=True)
		self.assertTrue(sonuc["written"])
		self.assertEqual(sonuc["alt"], f"Force EN Title {_TUZ}")

	def test_ar_ru_kategori_sabit_ek_cevirisi(self):
		"""ar/ru: kategori adı `category_name_{lang}`'den, sabit ek
		(`translate_platform_term`) ile çevrilir."""
		dosya = _dosya(f"kat-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		kategori = frappe.get_doc(
			{
				"doctype": "Product Category",
				"external_id": f"CAT-{_TUZ}",
				"category_name": f"Elektronik {_TUZ}",
				"image": dosya.file_url,
			}
		)
		kategori.flags.ignore_mandatory = True
		kategori.insert(ignore_permissions=True)
		self.addCleanup(_sil, "Product Category", kategori.name)
		frappe.db.set_value("Product Category", kategori.name, "category_name_ar", "إلكترونيات")
		frappe.db.set_value("Product Category", kategori.name, "category_name_ru", "Электроника")

		self.assertEqual(seo_generate.generate_alt(dosya.file_url, lang="ar"), "إلكترونيات فئة")
		self.assertEqual(seo_generate.generate_alt(dosya.file_url, lang="ru"), "Электроника категория")

	def test_seller_category_sufix_kolon_yoksa_no_translation(self):
		"""Düzeltme turu 1 (Critical): `Seller Category`'de dil sufix kolonu
		HİÇ yok — TR adını okuyup çevrili sabit ekle birleştirmek L1 ihlali
		olurdu. lang=en → boş/no_translation; lang=tr → mevcut davranış korunur."""
		dosya = _dosya(f"selcat-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		kategori = frappe.get_doc(
			{
				"doctype": "Seller Category",
				# `seller` Link zorunlu ama kategori adı çözümü doğrudan `image`
				# eşleşmesiyle çalışıyor — sentetik referans yeterli.
				"seller": f"SENTETIK-SELLER-{_TUZ}",
				"category_name": f"Satıcı Kategorisi {_TUZ}",
				"status": "Active",
				"image": dosya.file_url,
			}
		)
		kategori.flags.ignore_mandatory = True
		kategori.flags.ignore_links = True
		kategori.insert(ignore_permissions=True)
		self.addCleanup(_sil, "Seller Category", kategori.name)

		self.assertEqual(seo_generate.generate_alt(dosya.file_url, lang="en"), "")
		sonuc = seo_generate.refresh_alt(dosya.file_url, lang="en")
		self.assertFalse(sonuc["written"])
		self.assertEqual(sonuc["reason"], "no_translation")

		self.assertEqual(
			seo_generate.generate_alt(dosya.file_url, lang="tr"),
			f"Satıcı Kategorisi {_TUZ} kategorisi",
		)

	def test_gorunmeyen_taslak_varken_gorunur_ilan_secilir(self):
		"""[Final review düzeltmesi, Important] Aynı dosya iki Listing'e bağlı:
		biri görünmez taslak (`storefront_visible=0`, çeviri YOK), biri görünür
		(çeviri VAR). `_listing_baglami` görünmezi seçseydi `refresh_alt(lang=
		"en")` `no_translation` ile atlardı — denetim (`seo_audit.
		_missing_localized_alt_bulgusu`) yalnız GÖRÜNÜR Listing'i saydığı için
		bu, panelden asla kapatılamayan bir bulgu doğururdu."""
		dosya = _dosya(f"coklu-baglam-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)

		taslak = frappe.get_doc(
			{
				"doctype": "Listing",
				"listing_code": f"DRAFT-{frappe.generate_hash(length=8)}",
				"title": f"Taslak TR {_TUZ}",
				"status": "Draft",
				"currency": "TRY",
				"base_price": 100,
				"selling_price": 100,
				"primary_image": dosya.file_url,
				"storefront_visible": 0,
			}
		)
		taslak.flags.ignore_mandatory = True
		taslak.insert(ignore_permissions=True)
		self.addCleanup(_sil, "Listing", taslak.name)

		gorunur = _ilan_olustur(f"Görünür TR {_TUZ}", dosya.file_url)
		self.addCleanup(_sil, "Listing", gorunur)
		frappe.db.set_value("Listing", gorunur, "title_en", f"Visible EN {_TUZ}")

		sonuc = seo_generate.refresh_alt(dosya.file_url, lang="en")
		self.assertTrue(sonuc["written"])
		self.assertEqual(sonuc["alt"], f"Visible EN {_TUZ}")

	def test_kanca_urun_kaydetmeyi_dusurmez(self):
		"""Alt üretimi yan etkidir; patlasa bile ürün kaydedilmeli."""
		sahte = frappe._dict({"primary_image": "/files/yok.jpg", "images": []})
		with mock.patch.object(seo_generate, "refresh_alt", side_effect=RuntimeError("patla")):
			seo_generate.on_reference_change(sahte)  # istisna sızmamalı


class TestIndexability(FrappeTestCase):
	def test_public_aktif_kullanilan_indexlenir(self):
		doc = _dosya(f"idx-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		karar = seo_index.decide(doc.file_url, check_usage=False)
		self.assertTrue(karar["indexable"])
		self.assertIn("max-image-preview:large", karar["robots"])

	def test_private_noindex(self):
		doc = _dosya(f"idx-priv-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		frappe.db.set_value("File", doc.name, "is_private", 1, update_modified=False)
		karar = seo_index.decide(doc.file_url, check_usage=False)
		self.assertFalse(karar["indexable"])
		self.assertEqual(karar["reason"], seo_index.REASON_PRIVATE)

	def test_cope_atilan_noindex(self):
		doc = _dosya(f"idx-cop-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		frappe.db.set_value("File", doc.name, "th_media_state", "Trashed", update_modified=False)
		karar = seo_index.decide(doc.file_url, check_usage=False)
		self.assertFalse(karar["indexable"])
		self.assertTrue(karar["reason"].startswith(seo_index.REASON_STATE))

	def test_karantina_noindex(self):
		doc = _dosya(f"idx-kar-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		with mock.patch("tradehub_core.media.av.in_quarantine", return_value=True):
			karar = seo_index.decide(doc.file_url, check_usage=False)
		self.assertFalse(karar["indexable"])
		self.assertEqual(karar["reason"], seo_index.REASON_QUARANTINE)

	def test_hakki_dolan_noindex(self):
		doc = _dosya(f"idx-hak-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		seo.set_asset_fields(doc.file_url, {"rights_expires_on": "2020-01-01"})
		karar = seo_index.decide(doc.file_url, check_usage=False)
		self.assertFalse(karar["indexable"])
		self.assertTrue(karar["reason"].startswith(seo_index.REASON_EXPIRED))

	def test_olmayan_dosya(self):
		self.assertFalse(seo_index.decide("/files/hicyok.jpg")["indexable"])


class TestRenderIpuclari(FrappeTestCase):
	def test_galeride_tek_lcp_adayi(self):
		ilk = seo_render.hints(0, context="gallery")
		self.assertEqual(ilk["loading"], "eager")
		self.assertEqual(ilk["fetchpriority"], "high")
		for i in (1, 2, 40):
			digeri = seo_render.hints(i, context="gallery")
			self.assertEqual(digeri["loading"], "lazy")
			self.assertEqual(digeri["fetchpriority"], "")

	def test_izgarada_hicbirine_high_verilmez(self):
		"""Kart ızgarasında tek bir LCP adayı yok."""
		for i in range(6):
			self.assertEqual(seo_render.hints(i, context="grid")["fetchpriority"], "")
		self.assertEqual(seo_render.hints(0, context="grid")["loading"], "eager")
		self.assertEqual(seo_render.hints(9, context="grid")["loading"], "lazy")

	def test_payload_html_nitelik_adlarini_tasir(self):
		yuk = seo_render.image_payload(
			{"file_url": "/files/x.jpg", "alt": "a", "width": 100, "height": 50}, index=0
		)
		for anahtar in ("url", "alt", "width", "height", "loading", "decoding", "fetchpriority"):
			self.assertIn(anahtar, yuk)


class TestImageObject(FrappeTestCase):
	def test_anlamsiz_alanlarda_duz_url(self):
		"""Hiç alan yoksa `ImageObject` düz URL'den fazlasını söylemiyor."""
		sonuc = schema_builder.build_image_object({"file_url": "/files/x.jpg"}, _SITE)
		self.assertEqual(sonuc, f"{_SITE}/files/x.jpg")

	def test_alanlar_varsa_nesne(self):
		sonuc = schema_builder.build_image_object(
			{
				"file_url": "/files/x.jpg",
				"alt": "kırmızı çanta",
				"width": 497,
				"height": 645,
				"creator": "Mağaza A",
				"license_url": "/lisans",
			},
			_SITE,
		)
		self.assertIsInstance(sonuc, dict)
		self.assertEqual(sonuc["@type"], "ImageObject")
		self.assertEqual(sonuc["caption"], "kırmızı çanta")
		self.assertEqual(sonuc["width"], 497)
		self.assertEqual(sonuc["creator"], {"@type": "Organization", "name": "Mağaza A"})
		self.assertEqual(sonuc["license"], f"{_SITE}/lisans")

	def test_caption_yoksa_alt_kullanilir(self):
		sonuc = schema_builder.build_image_object({"file_url": "/files/x.jpg", "alt": "yalnız alt"}, _SITE)
		self.assertEqual(sonuc["caption"], "yalnız alt")

	def test_bos_url_bos_doner(self):
		self.assertEqual(schema_builder.build_image_object({}, _SITE), "")


class TestGorselSitemap(FrappeTestCase):
	def test_namespace_yalniz_gorsel_varsa(self):
		gorselsiz = sitemap_generator.build_urlset_xml([{"loc": "https://x/y"}])
		self.assertNotIn("sitemap-image", gorselsiz)

		gorselli = sitemap_generator.build_urlset_xml(
			[{"loc": "https://x/y", "images": [{"loc": "https://x/a.jpg"}]}]
		)
		self.assertIn("sitemap-image", gorselli)
		self.assertIn("<image:loc>https://x/a.jpg</image:loc>", gorselli)

	def test_caption_ve_lisans_basilir(self):
		xml = sitemap_generator.build_urlset_xml(
			[
				{
					"loc": "https://x/y",
					"images": [
						{
							"loc": "https://x/a.jpg",
							"caption": "kırmızı çanta",
							"title": "Çanta",
							"license": "https://x/lisans",
						}
					],
				}
			]
		)
		self.assertIn("<image:caption>kırmızı çanta</image:caption>", xml)
		self.assertIn("<image:title>Çanta</image:title>", xml)
		self.assertIn("<image:license>https://x/lisans</image:license>", xml)

	def test_locsuz_gorsel_atlanir(self):
		xml = sitemap_generator.build_urlset_xml([{"loc": "https://x/y", "images": [{"caption": "loc yok"}]}])
		self.assertNotIn("image:image", xml)


class TestDenetim(FrappeTestCase):
	def test_bos_alt_hata(self):
		bulgular = seo_audit.audit_fields({"width": 10, "height": 10})
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("missing_alt", kodlar)
		self.assertEqual(
			next(b for b in bulgular if b["code"] == "missing_alt")["severity"],
			seo_audit.SEVERITY_ERROR,
		)

	def test_uzun_alt_supheli(self):
		bulgular = seo_audit.audit_fields({"alt": "x" * 200, "width": 1, "height": 1})
		self.assertIn("suspicious_alt", [b["code"] for b in bulgular])

	def test_anahtar_kelime_yigini(self):
		bulgular = seo_audit.audit_fields({"alt": "çanta çanta çanta deri", "width": 1, "height": 1})
		self.assertIn("keyword_stuffed_alt", [b["code"] for b in bulgular])

	def test_kotu_dosya_adi(self):
		bulgular = seo_audit.audit_fields(
			{"alt": "iyi metin", "width": 1, "height": 1}, file_name="Ekran Görüntüsü 2026.png"
		)
		self.assertIn("poor_filename", [b["code"] for b in bulgular])

	def test_olcu_eksik_hata(self):
		bulgular = seo_audit.audit_fields({"alt": "metin"})
		kod = next(b for b in bulgular if b["code"] == "missing_dimensions")
		self.assertEqual(kod["severity"], seo_audit.SEVERITY_ERROR)

	def test_hakki_dolmus_hata(self):
		bulgular = seo_audit.audit_fields(
			{"alt": "m", "width": 1, "height": 1, "rights_expires_on": "2020-01-01"}
		)
		self.assertIn("expired_rights", [b["code"] for b in bulgular])

	def test_temiz_varlik_bulgusuz(self):
		bulgular = seo_audit.audit_fields(
			{
				"alt": "kırmızı deri çanta",
				"title": "Çanta",
				"caption": "Ürün görseli",
				"width": 800,
				"height": 600,
				"license_url": "/lisans",
			},
			file_name="kirmizi-canta.jpg",
		)
		self.assertEqual(bulgular, [])


class TestSkor(FrappeTestCase):
	def test_bulgusuz_tam_puan(self):
		skor = seo_audit.score_from([], {"alt": "metin", "width": 1, "height": 1, "license_url": "/x"})
		self.assertEqual(skor["accessibility"], 100)
		self.assertEqual(skor["rights"], 100)
		self.assertGreater(skor["overall"], 0)

	def test_hata_warndan_agir(self):
		hata = seo_audit.score_from([{"code": "missing_alt", "severity": "error"}])
		uyari = seo_audit.score_from([{"code": "suspicious_alt", "severity": "warn"}])
		self.assertLess(hata["accessibility"], uyari["accessibility"])

	def test_alt_kirilim_ayri(self):
		"""Erişilebilirlik düşerken haklar etkilenmemeli."""
		skor = seo_audit.score_from([{"code": "missing_alt", "severity": "error"}])
		self.assertEqual(skor["rights"], 100)
		self.assertLess(skor["accessibility"], 100)

	def test_yapisal_veri_alansiz_sifir(self):
		skor = seo_audit.score_from([], {"alt": "", "caption": "", "title": ""})
		self.assertEqual(skor["structured_data"], 0)


class TestTopluDenetim(FrappeTestCase):
	def test_toplu_ozet_ve_ortalama(self):
		a = _dosya(f"denetim-a-{_TUZ}.txt")
		b = _dosya(f"denetim-b-{_TUZ}.txt")
		self.addCleanup(_sil, "File", a.name)
		self.addCleanup(_sil, "File", b.name)
		seo.set_asset_fields(a.file_url, {"alt_tr": "iyi metin", "title": "T", "caption": "C"})

		sonuc = seo_audit.audit_batch([a.file_url, b.file_url])
		self.assertEqual(sonuc["total"], 2)
		self.assertIn("missing_alt", sonuc["summary"])
		self.assertEqual(sonuc["summary"]["missing_alt"], 1)
		self.assertIn("overall", sonuc["score"])

	def test_bos_liste(self):
		self.assertEqual(seo_audit.audit_batch([])["files"], [])

	def test_dosya_kaydi_yoksa_tek_bulgu(self):
		"""Katalog `/files/…` gösteriyor ama `File` yok (22 Ağu: 4 üründe 3 bozuk
		adres). Alt/title bulguları anlamsız; tek bulgu `missing_file`, yük
		metnin kendisini ve 0 boyutu taşır."""
		hayalet = f"/files/hayalet-{_TUZ}.jpg"
		sonuc = seo_audit.audit_batch([hayalet])
		satir = sonuc["files"][0]
		self.assertEqual([f["code"] for f in satir["findings"]], ["missing_file"])
		self.assertEqual(satir["file_size"], 0)
		self.assertEqual(satir["alt"], "")
		self.assertEqual(sonuc["summary"], {"missing_file": 1})

	def test_yuk_alt_metni_tasir(self):
		"""Panel yalnız ✓/— gösterince "Metin üret" bir şey yaptı mı görünmüyordu."""
		a = _dosya(f"yuk-{_TUZ}.txt")
		self.addCleanup(_sil, "File", a.name)
		seo.set_asset_fields(a.file_url, {"alt_tr": "görünür metin", "alt_source": seo.SOURCE_HUMAN})
		satir = seo_audit.audit_batch([a.file_url])["files"][0]
		self.assertEqual(satir["alt"], "görünür metin")
		self.assertEqual(satir["alt_source"], seo.SOURCE_HUMAN)
		self.assertGreater(satir["file_size"], 0)

	# ── CWV kuralları (Dilim 7 Task 1): format/merdiven + cache sürümleme ──

	@staticmethod
	def _policy_cache_temizle():
		"""`_slot_policy` istek-içi memosu test süreci boyunca yaşar — sızmasın."""
		if hasattr(frappe.local, seo_audit._POLICY_LOCAL_KEY):
			delattr(frappe.local, seo_audit._POLICY_LOCAL_KEY)

	@staticmethod
	def _sahte_turev(
		profile: str, fmt: str, width: int, height: int | None = None, state: str = "ready", gate: int = 1
	) -> dict:
		return {
			"asset": "MA-CWV",
			"profile": profile,
			"format": fmt,
			"width": width,
			"height": width if height is None else height,
			"state": state,
			"benefit_gate_passed": gate,
		}

	def _cwv_bulgular(
		self,
		renditions,
		*,
		width: int = 200,
		height: int | None = None,
		url: str = "/files/cwv-test.jpg",
		primary: bool = False,
	) -> list:
		"""`_technical_findings`'i temiz bir bağlamla doğrudan çağır: diğer
		teknik kurallar (broken_url, oversized, duplicate…) tetiklenmesin ki
		yalnız yeni kuralların davranışı ölçülsün.

		`primary=True` → `url`, `primary_urls` kümesine konur (LCP testleri)."""
		self._policy_cache_temizle()
		self.addCleanup(self._policy_cache_temizle)
		alanlar = {"alt": "metin", "width": width, "height": width if height is None else height}
		return seo_audit._technical_findings(
			url,
			alanlar,
			{"file_size": 1000},
			url_count=1,
			asset={"name": "MA-CWV"},
			rendition_assets={"MA-CWV"},
			associated=True,
			renditions=renditions,
			primary_urls=frozenset({url}) if primary else frozenset(),
		)

	def test_modern_format_varsa_tetiklenmez(self):
		bulgular = self._cwv_bulgular([self._sahte_turev("w96", "avif", 96)])
		self.assertNotIn("missing_modern_format", [b["code"] for b in bulgular])

	def test_yalniz_jpeg_turevde_modern_format_uyarisi(self):
		bulgular = self._cwv_bulgular(
			[self._sahte_turev("w96", "jpeg", 96), self._sahte_turev("w192", "jpeg", 192)]
		)
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("missing_modern_format", kodlar)
		bulgu = next(b for b in bulgular if b["code"] == "missing_modern_format")
		self.assertEqual(bulgu["severity"], seo_audit.SEVERITY_WARN)

	def test_servis_edilemeyen_modern_turev_sayilmaz(self):
		"""AVIF üretilmiş ama gate-fail/ready-değil: servis EDİLEMEZ, uyarı kalır."""
		bulgular = self._cwv_bulgular(
			[
				self._sahte_turev("w96", "jpeg", 96),
				self._sahte_turev("w96", "avif", 96, gate=0),
				self._sahte_turev("w192", "avif", 192, state="failed"),
			]
		)
		self.assertIn("missing_modern_format", [b["code"] for b in bulgular])

	def test_merdiven_eksigi_detayda_profil_adiyla(self):
		bulgular = self._cwv_bulgular(
			[
				self._sahte_turev("w96", "webp", 96),
				self._sahte_turev("w192", "webp", 192),
				self._sahte_turev("w384", "webp", 384),
			],
			width=1000,
		)
		bulgu = next(b for b in bulgular if b["code"] == "incomplete_rendition_ladder")
		self.assertEqual(bulgu["severity"], seo_audit.SEVERITY_WARN)
		self.assertIn("w640", bulgu["detail"])
		self.assertIn("w768", bulgu["detail"])
		self.assertNotIn("w1280", bulgu["detail"])  # 1000 px kaynaktan upscale beklenmez

	def test_kucuk_kaynakta_buyuk_basamak_beklenmez(self):
		"""w=200 kaynaktan yalnız w96+w192 beklenir; merdiven tam sayılır."""
		bulgular = self._cwv_bulgular(
			[self._sahte_turev("w96", "webp", 96), self._sahte_turev("w192", "webp", 192)]
		)
		self.assertNotIn("incomplete_rendition_ladder", [b["code"] for b in bulgular])

	def test_hic_turev_yoksa_yeni_kurallar_susar(self):
		"""Ayrık küme: hiç türevi olmayan asset `missing_responsive_variants`'a
		kalır — yeni kurallar aynı dosyada onunla birlikte tetiklenmez."""
		bulgular = seo_audit._technical_findings(
			"/files/cwv-bos.jpg",
			{"alt": "metin", "width": 2000, "height": 2000},
			{"file_size": 1000},
			url_count=1,
			asset={"name": "MA-BOS"},
			rendition_assets=set(),
			associated=True,
			renditions=None,
		)
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("missing_responsive_variants", kodlar)
		self.assertNotIn("missing_modern_format", kodlar)
		self.assertNotIn("incomplete_rendition_ladder", kodlar)

	def test_hic_turev_yoksa_primary_gorselde_lcp_de_tetiklenir(self):
		"""Devir notu (Görev 3→4, mini iş a): renditions tamamen YOK olan bir
		primary görselde `missing_responsive_variants` ("hiç türev yok") VE
		`lcp_candidate_unoptimized`'ın modern-format bacağı ("modern format
		yok") BİRLİKTE tetiklenir — bu bir bug DEĞİL, kasıtlı çift-sinyal.
		`_rendition_bulgulari` kendi ayrık-küme kapısına sahip (`not renditions`
		→ []), ama `_lcp_bulgusu` aynı kapıyı taşımıyor: `renditions or []`
		boş listede `_servis_edilebilir` de boş döner, modern-format kümesiyle
		kesişim boş kalır ve "modern format yok" nedeni eklenir. LCP adayında
		iki sinyal ayrı anlam taşır — biri "hiç türev üretilmedi", diğeri
		"servis edilebilir modern format yok" — aynı dosyada birlikte
		görünmeleri beklenen davranıştır."""
		bulgular = seo_audit._technical_findings(
			"/files/cwv-lcp-bos.jpg",
			{"alt": "metin", "width": 2000, "height": 2000},
			{"file_size": 1000},
			url_count=1,
			asset={"name": "MA-LCP-BOS"},
			rendition_assets=set(),
			associated=True,
			renditions=None,
			primary_urls=frozenset({"/files/cwv-lcp-bos.jpg"}),
		)
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("missing_responsive_variants", kodlar)
		self.assertIn("lcp_candidate_unoptimized", kodlar)
		bulgu = next(b for b in bulgular if b["code"] == "lcp_candidate_unoptimized")
		self.assertIn("modern format yok", bulgu["detail"])

	def test_gorsel_disi_uzantida_yeni_kurallar_susar(self):
		bulgular = self._cwv_bulgular([self._sahte_turev("w96", "jpeg", 96)], url="/files/cwv-video.mp4")
		kodlar = [b["code"] for b in bulgular]
		self.assertNotIn("missing_modern_format", kodlar)
		self.assertNotIn("incomplete_rendition_ladder", kodlar)

	# ── unserved_renditions + aspect_ratio_mismatch (Dilim 7 Task 2) ──

	def test_hepsi_servis_edilemezse_unserved_ve_format_ladder_susar(self):
		"""Kök neden `unserved_renditions`: format/merdiven kuralları o dosya
		için hiç ÜRETİLMEZ — ikisi de yanlış alarm olurdu."""
		bulgular = self._cwv_bulgular(
			[
				self._sahte_turev("w96", "jpeg", 96, gate=0),
				self._sahte_turev("w192", "avif", 192, state="failed"),
			],
			width=1000,
		)
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("unserved_renditions", kodlar)
		self.assertNotIn("missing_modern_format", kodlar)
		self.assertNotIn("incomplete_rendition_ladder", kodlar)
		self.assertNotIn("aspect_ratio_mismatch", kodlar)
		bulgu = next(b for b in bulgular if b["code"] == "unserved_renditions")
		self.assertEqual(bulgu["severity"], seo_audit.SEVERITY_WARN)

	def test_karisik_durumda_biri_servis_edilebilirse_unserved_susar(self):
		"""1 servis edilebilir + 1 gate-fail: kök neden yok, unserved susar."""
		bulgular = self._cwv_bulgular(
			[
				self._sahte_turev("w96", "webp", 96, gate=1),
				self._sahte_turev("w192", "jpeg", 192, gate=0),
			],
		)
		self.assertNotIn("unserved_renditions", [b["code"] for b in bulgular])

	def test_oran_uyumluysa_mismatch_yok(self):
		"""Oran-koruyan (contain-fit) w1920 türevi kaynakla AYNI oranda (16:9)."""
		bulgular = self._cwv_bulgular(
			[self._sahte_turev("w1920", "webp", 1920, 1080)],
			width=1600,
			height=900,
		)
		self.assertNotIn("aspect_ratio_mismatch", [b["code"] for b in bulgular])

	def test_oran_uyumsuzsa_mismatch_tetiklenir(self):
		"""Kaynak 4:3 (1200x900), en büyük servis edilebilir türev 16:9 (1920x1080)."""
		bulgular = self._cwv_bulgular(
			[self._sahte_turev("w1920", "webp", 1920, 1080)],
			width=1200,
			height=900,
		)
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("aspect_ratio_mismatch", kodlar)
		bulgu = next(b for b in bulgular if b["code"] == "aspect_ratio_mismatch")
		self.assertEqual(bulgu["severity"], seo_audit.SEVERITY_WARN)

	def test_pad_fit_turevde_oran_kontrolu_atlanir(self):
		"""Review bulgusu #1 (Critical) repro: en büyük servis edilebilir türev
		yalnız PAD-fit (w768, kare dolgulu) — policy-izinli 4:5 kaynakla
		kıyaslamak her zaman yanlış pozitif üretirdi. Oran-koruyan aday
		olmadığı için kural SESSİZ kalmalı."""
		bulgular = self._cwv_bulgular(
			[self._sahte_turev("w768", "webp", 768, 768)],
			width=800,
			height=1000,  # 4:5 — policy `allowed_ratios` içinde
		)
		self.assertNotIn("aspect_ratio_mismatch", [b["code"] for b in bulgular])

	def test_contain_turevle_gercek_oran_bozulmasi_tespit_edilir(self):
		"""Listede pad-fit bir türev de olsa (w384), tek oran-koruyan aday
		(w1280, contain) gerçek CLS riskini yakalamalı."""
		bulgular = self._cwv_bulgular(
			[
				self._sahte_turev("w384", "webp", 384, 384),
				self._sahte_turev("w1280", "webp", 1280, 960),  # 4:3
			],
			width=800,
			height=1000,  # 4:5 kaynak
		)
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("aspect_ratio_mismatch", kodlar)
		bulgu = next(b for b in bulgular if b["code"] == "aspect_ratio_mismatch")
		self.assertIn("1280x960", bulgu["detail"])

	def test_olcusuz_dosyada_mismatch_susar(self):
		"""`missing_dimensions` zaten kendi kuralında var; burada kıyaslanacak
		bir oran olmadığı için sessiz kalmalı."""
		bulgular = self._cwv_bulgular(
			[self._sahte_turev("w1920", "webp", 1920, 1080)],
			width=0,
			height=0,
		)
		self.assertNotIn("aspect_ratio_mismatch", [b["code"] for b in bulgular])

	def test_policy_okunamazsa_bulgu_yok_log_var(self):
		bulgular = None
		with (
			mock.patch(
				"tradehub_core.media.pipeline.quality.ssim._slot_politikalari",
				side_effect=RuntimeError("policy patladı"),
			),
			mock.patch.object(frappe, "log_error") as log_mock,
		):
			bulgular = self._cwv_bulgular([self._sahte_turev("w96", "jpeg", 96)])
		kodlar = [b["code"] for b in bulgular]
		self.assertNotIn("missing_modern_format", kodlar)
		self.assertNotIn("incomplete_rendition_ladder", kodlar)
		log_mock.assert_called()

	def test_kural_boyut_haritasinda_cwv_kodlari(self):
		self.assertEqual(seo_audit._KURAL_BOYUT["missing_modern_format"], "performance")
		self.assertEqual(seo_audit._KURAL_BOYUT["incomplete_rendition_ladder"], "performance")
		self.assertEqual(seo_audit._KURAL_BOYUT["aspect_ratio_mismatch"], "performance")
		self.assertEqual(seo_audit._KURAL_BOYUT["unserved_renditions"], "technical_health")
		self.assertEqual(seo_audit._KURAL_BOYUT["lcp_candidate_unoptimized"], "performance")
		# Bütünlük: harita 34 kuralı kapsıyor (Dilim 8: + missing_localized_alt;
		# F-18b: + invalid_rights_date) ve her value gerçek bir DIMENSIONS üyesi
		# — yazım hatası ("performnace" gibi) skor toplamında sessizce yutulur.
		self.assertEqual(len(seo_audit._KURAL_BOYUT), 34)
		# F-18b: okunamayan `rights_expires_on` eskiden denetimin TAMAMINI
		# çökertiyordu; artık bulgu üretiyor. Boyuta bağlanmayan kural skoru
		# hiç etkilemez, o yüzden haritada olması sözleşmenin parçası.
		self.assertEqual(seo_audit._KURAL_BOYUT["invalid_rights_date"], "rights")
		self.assertLessEqual(set(seo_audit._KURAL_BOYUT.values()), set(seo_audit.DIMENSIONS))
		self.assertEqual(seo_audit._KURAL_BOYUT["missing_localized_alt"], "localization")

	# ── lcp_candidate_unoptimized (Dilim 7 Task 3): primary ayrımı ──

	def test_lcp_primary_modern_format_yoksa_tetiklenir(self):
		"""Primary görselde yalnız jpeg türev var — LCP adayı optimize değil."""
		bulgular = self._cwv_bulgular(
			[self._sahte_turev("w96", "jpeg", 96), self._sahte_turev("w192", "jpeg", 192)],
			primary=True,
		)
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("lcp_candidate_unoptimized", kodlar)
		bulgu = next(b for b in bulgular if b["code"] == "lcp_candidate_unoptimized")
		self.assertEqual(bulgu["severity"], seo_audit.SEVERITY_WARN)
		self.assertIn("modern format yok", bulgu["detail"])

	def test_lcp_ayni_durumda_galeri_gorseli_tetiklemez(self):
		"""AYNI eksik (yalnız jpeg) ama `primary_urls` içinde değil — galeri
		görseli LCP adayı sayılmaz, yanlış pozitif üretmemeli."""
		bulgular = self._cwv_bulgular(
			[self._sahte_turev("w96", "jpeg", 96), self._sahte_turev("w192", "jpeg", 192)],
			primary=False,
		)
		self.assertNotIn("lcp_candidate_unoptimized", [b["code"] for b in bulgular])
		# Kontrol: format eksikliği kendi kuralında zaten var, LCP'ye özgü değil.
		self.assertIn("missing_modern_format", [b["code"] for b in bulgular])

	def test_lcp_format_ve_olcu_tamsa_tetiklenmez(self):
		bulgular = self._cwv_bulgular([self._sahte_turev("w96", "avif", 96)], primary=True)
		self.assertNotIn("lcp_candidate_unoptimized", [b["code"] for b in bulgular])

	def test_lcp_olcusuz_primary_tetiklenir(self):
		"""Format tam ama boyut bilgisi eksik — ikinci bacak tek başına yeterli."""
		bulgular = self._cwv_bulgular(
			[self._sahte_turev("w96", "avif", 96)], width=0, height=0, primary=True
		)
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("lcp_candidate_unoptimized", kodlar)
		bulgu = next(b for b in bulgular if b["code"] == "lcp_candidate_unoptimized")
		self.assertIn("boyut bilgisi eksik", bulgu["detail"])
		self.assertNotIn("modern format yok", bulgu["detail"])

	def test_lcp_unserved_durumunda_yalniz_boyut_bacagiyla_degerlendirilir(self):
		"""`unserved_renditions` tetiklendiğinde modern-format bacağı ona
		bırakılır — LCP kuralı yalnız boyut-eksik bacağıyla değerlendirilir,
		aynı kök neden iki koddan raporlanmaz (çifte gürültü önlemi)."""
		unserved_renditions = [
			self._sahte_turev("w96", "jpeg", 96, gate=0),
			self._sahte_turev("w192", "avif", 192, state="failed"),
		]
		# Boyut tam: unserved kapısı devredeyken LCP de sessiz kalmalı.
		bulgular = self._cwv_bulgular(unserved_renditions, primary=True)
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("unserved_renditions", kodlar)
		self.assertNotIn("lcp_candidate_unoptimized", kodlar)

		# Boyut eksik: LCP yalnız boyut bacağıyla tetiklenir, "modern format
		# yok" alt nedeni detayda GÖRÜNMEZ (unserved zaten o sinyali taşıyor).
		bulgular = self._cwv_bulgular(unserved_renditions, width=0, height=0, primary=True)
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("unserved_renditions", kodlar)
		self.assertIn("lcp_candidate_unoptimized", kodlar)
		bulgu = next(b for b in bulgular if b["code"] == "lcp_candidate_unoptimized")
		self.assertEqual(bulgu["detail"], "boyut bilgisi eksik")

	def test_primary_urls_verilmeyen_eski_cagri_lcp_uretmez(self):
		"""`primary_urls` YENİ kwarg — eski çağıran hiç geçmiyor (varsayılan
		boş küme), davranış kırılmaz: hem format hem boyut eksik olsa da
		LCP kuralı hiç üretilmez."""
		bulgular = seo_audit._technical_findings(
			"/files/cwv-test.jpg",
			{"alt": "metin", "width": 0, "height": 0},
			{"file_size": 1000},
			url_count=1,
			asset={"name": "MA-CWV"},
			rendition_assets={"MA-CWV"},
			associated=True,
			renditions=[self._sahte_turev("w96", "jpeg", 96)],
		)
		self.assertNotIn("lcp_candidate_unoptimized", [b["code"] for b in bulgular])

	def test_audit_batch_primary_urls_verilmeden_eski_davranis(self):
		"""`audit_batch` de aynı geriye uyumluluğu sağlamalı — imza değişti
		ama `primary_urls` verilmeyen çağrı eski davranışı korur."""
		a = _dosya(f"lcp-eski-{_TUZ}.txt")
		self.addCleanup(_sil, "File", a.name)
		sonuc = seo_audit.audit_batch([a.file_url])
		kodlar = [f["code"] for f in sonuc["files"][0]["findings"]]
		self.assertNotIn("lcp_candidate_unoptimized", kodlar)

	def test_cache_anahtari_surumlendi_eski_cache_okunmaz(self):
		"""C7: kural seti değişti — eski anahtarla yazılmış cache dönmemeli."""
		self.assertTrue(seo_audit.SCOPE_CACHE_KEY.endswith("_v2"))
		eski_anahtar = f"tradehub_media_seo_audit:tk-{_TUZ}"
		yeni_anahtar = f"{seo_audit.SCOPE_CACHE_KEY}:tk-{_TUZ}"
		frappe.cache().set_value(eski_anahtar, {"files": "BAYAT"}, expires_in_sec=60)
		self.addCleanup(frappe.cache().delete_value, eski_anahtar)
		self.addCleanup(frappe.cache().delete_value, yeni_anahtar)
		sonuc = seo_audit.audit_scope([], cache_key=f"tk-{_TUZ}")
		self.assertNotEqual(sonuc.get("files"), "BAYAT")


def _ilan_olustur(baslik: str, primary_image: str, *, galeri_url: str | None = None) -> str:
	"""Asgari Listing + tek galeri satırı — `_seo_audit_adaylari` primary/galeri
	ayrımı testleri için (`test_media_retro_rename._make_listing` deseni).

	`galeri_url` ikinci bir görsel olarak eklenir (`sort_order=1`) — `primary_
	image` zaten doluysa `Listing._ensure_primary_image` galeri satırını ana
	görsele YÜKSELTMEZ (yalnız `primary_image` boşken devreye girer); bu
	yüzden `galeri_url` gerçekten "sadece galeri" kalır."""
	doc = frappe.get_doc(
		{
			"doctype": "Listing",
			"listing_code": f"CWV-{frappe.generate_hash(length=8)}",
			"title": baslik,
			"status": "Active",
			"currency": "TRY",
			"base_price": 100,
			"selling_price": 100,
			"primary_image": primary_image,
			"storefront_visible": 1,
			"listing_images": [{"image": galeri_url, "sort_order": 1}] if galeri_url else [],
		}
	)
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


class TestSeoAuditAdaylariPrimaryAyrimi(FrappeTestCase):
	"""`_seo_audit_adaylari` primary/galeri ayrımı — Dilim 7 Task 3 (tasarım C5)."""

	def test_catalog_primary_ve_galeri_ayrisir(self):
		"""Bir ilan: `primary_image` P, ikinci galeri görseli G — `primary_urls`
		yalnız P'yi içermeli, G'yi (yanlış pozitif) İÇERMEMELİ. `primary_image`
		zaten dolu olduğundan `_ensure_primary_image` G'yi yükseltmez."""
		primary = _dosya(f"cwv-primary-{_TUZ}.txt")
		galeri = _dosya(f"cwv-galeri-{_TUZ}.txt")
		self.addCleanup(_sil, "File", primary.name)
		self.addCleanup(_sil, "File", galeri.name)

		ilan = _ilan_olustur(f"CWV Primary {_TUZ}", primary.file_url, galeri_url=galeri.file_url)
		self.addCleanup(_sil, "Listing", ilan)
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), primary.file_url)

		urls, primary_urls = media_admin._seo_audit_adaylari("catalog", 20000)
		self.assertIn(primary.file_url, urls)
		self.assertIn(galeri.file_url, urls)
		self.assertIn(primary.file_url, primary_urls)
		self.assertNotIn(galeri.file_url, primary_urls)

	def test_bos_katalogda_bos_kume_doner(self):
		"""`urls` boşsa ek `Listing` sorgusu hiç çalıştırılmamalı (guard) — dev
		seed verisinden bağımsız olsun diye UNION SQL'i boş dönecek şekilde
		sahtelenir."""
		with (
			mock.patch.object(frappe.db, "sql", return_value=[]),
			mock.patch.object(frappe, "get_all", side_effect=AssertionError("get_all çağrılmamalı")),
		):
			urls, primary_urls = media_admin._seo_audit_adaylari("catalog", 20000)
		self.assertEqual(urls, [])
		self.assertEqual(primary_urls, set())

	def test_acik_file_urls_ile_primary_gorselde_lcp_bulgusu_gorunur(self):
		"""Final review Minor #1: `audit_media_seo`'ya AÇIKÇA `file_urls`
		verildiğinde de `primary_urls` kurulmalı — yoksa aynı primary görsel
		scope taramasında `lcp_candidate_unoptimized` üretirken tek-dosya
		denetiminde (ör. tek ürünün görselleri) bulgu sessizce kaybolurdu."""
		primary = _dosya(f"cwv-acik-primary-{_TUZ}.txt")
		self.addCleanup(_sil, "File", primary.name)
		ilan = _ilan_olustur(f"CWV Açık Primary {_TUZ}", primary.file_url)
		self.addCleanup(_sil, "Listing", ilan)

		sonuc = media_admin.audit_media_seo(file_urls=[primary.file_url])
		kodlar = [b["code"] for b in sonuc["files"][0]["findings"]]
		self.assertIn("lcp_candidate_unoptimized", kodlar)


# ── Dilim 8 (Bulk Localization) Task 2 — aday sorgusu + backfill + kural ────


class TestBackfillAdaylariDilDuyarli(FrappeTestCase):
	def test_alt_en_bos_olani_bulur_doluyu_bulmaz(self):
		"""Aday sorgusu dil-duyarlı: `alt_en` boş olan Listing'e bağlı dosyayı
		bulur, dolu olanı bulmaz."""
		bos = _dosya(f"bfl-bos-{_TUZ}.txt")
		dolu = _dosya(f"bfl-dolu-{_TUZ}.txt")
		self.addCleanup(_sil, "File", bos.name)
		self.addCleanup(_sil, "File", dolu.name)
		ilan = _ilan_olustur(f"BFL Aday {_TUZ}", bos.file_url, galeri_url=dolu.file_url)
		self.addCleanup(_sil, "Listing", ilan)
		seo.set_asset_fields(dolu.file_url, {"alt_en": "zaten var"})

		# Büyük limit — dev/test katalogundaki mevcut adaylar arasında bizim
		# satırımız kaybolmasın (`_seo_audit_adaylari("catalog", 20000)` ile
		# aynı desen, bu dosyada zaten kurulu).
		adaylar = seo_generate._backfill_adaylari(20000, lang="en", only_listing=True)
		self.assertIn(bos.file_url, adaylar)
		self.assertNotIn(dolu.file_url, adaylar)

	def test_tr_varsayilani_mevcut_davranisi_korur(self):
		"""`lang` verilmezse imza eskisiyle (varsayılan tr) uyumlu kalır."""
		adaylar = seo_generate._backfill_adaylari(1, only_listing=True)
		self.assertIsInstance(adaylar, list)


class TestBackfillLocalization(FrappeTestCase):
	def test_by_lang_sayaclari_ve_idempotent(self):
		"""Kabul kriteri 5: idempotent — ikinci koşum 0 yazar. `_backfill_adaylari`
		SAHTELENİYOR: gerçek sorgu tüm katalogu tarar ve `frappe.db.commit()`
		gerçekten committer — dev/test verisindeki alakasız satırları yazmak
		riskli (bkz. `test_media_av.TestNullDurumSuzgeci` docstring'i, aynı
		tuzak). Sahte aday listesi yalnız bu testin kendi dosyasını döner;
		yazma/okuma zinciri (`refresh_alt`) GERÇEK çalışır."""
		dosya = _dosya(f"bfl-loc-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		ilan = _ilan_olustur(f"BFL Loc {_TUZ}", dosya.file_url)
		self.addCleanup(_sil, "Listing", ilan)
		frappe.db.set_value("Listing", ilan, "title_en", f"BFL EN {_TUZ}")
		frappe.db.set_value("Listing", ilan, "title_ru", f"BFL RU {_TUZ}")
		# title_ar bilerek boş — no_translation yolu sınanıyor.

		with mock.patch.object(seo_generate, "_backfill_adaylari", return_value=[dosya.file_url]):
			sonuc = seo_generate.backfill_localization(limit=500, langs=("en", "ar", "ru"))

		self.assertEqual(sonuc["by_lang"]["en"]["written"], 1)
		self.assertEqual(sonuc["by_lang"]["ru"]["written"], 1)
		self.assertEqual(sonuc["by_lang"]["ar"]["written"], 0)
		self.assertEqual(sonuc["by_lang"]["ar"]["reasons"].get("no_translation"), 1)
		self.assertEqual(sonuc["written"], 2)
		self.assertEqual(seo.fields_for(dosya.file_url, lang="en")["alt"], f"BFL EN {_TUZ}")
		self.assertEqual(seo.fields_for(dosya.file_url, lang="ru")["alt"], f"BFL RU {_TUZ}")

		with mock.patch.object(seo_generate, "_backfill_adaylari", return_value=[dosya.file_url]):
			ikinci = seo_generate.backfill_localization(limit=500, langs=("en", "ar", "ru"))
		self.assertEqual(ikinci["written"], 0)

	def test_bilinmeyen_dil_sessizce_tr_ye_donmez(self):
		"""[Final review düzeltmesi, Minor] `normalize_lang` bilinmeyen kodu
		sessizce `tr`'ye çevirdiği için korumasız döngü "de" istendiğinde
		aslında TR koşumunu TEKRARLARDI. Bilinmeyen dil hiç sorgulanmamalı,
		aday sorgusu/`refresh_alt` hiç çağrılmamalı — yalnız `unknown_lang`
		sebebiyle izlenmeli."""
		with mock.patch.object(seo_generate, "_backfill_adaylari") as adaylar_mock:
			sonuc = seo_generate.backfill_localization(langs=("de",))
		adaylar_mock.assert_not_called()
		self.assertEqual(sonuc["scanned"], 0)
		self.assertEqual(sonuc["written"], 0)
		self.assertEqual(sonuc["reasons"].get("unknown_lang"), 1)
		self.assertEqual(sonuc["by_lang"]["de"]["reasons"], {"unknown_lang": 1})


class TestBackfillMediaLocalizationWhitelistUcu(FrappeTestCase):
	def test_whitelist_guard_ve_senkron_delege(self):
		"""`backfill_media_alt` emsali: whitelist, `_guard()`, senkron delege
		(kuyruk YOK, `frappe.enqueue` çağrılmaz)."""
		self.assertIn(media_admin.backfill_media_localization, frappe.whitelisted)
		with (
			mock.patch.object(media_admin, "_guard") as guard,
			mock.patch.object(
				seo_generate,
				"backfill_localization",
				return_value={"scanned": 0, "written": 0, "skipped": 0, "reasons": {}, "by_lang": {}},
			) as delege,
		):
			sonuc = media_admin.backfill_media_localization(limit=250)
		guard.assert_called_once()
		delege.assert_called_once_with(limit=250)
		self.assertEqual(sonuc["by_lang"], {})


class TestMissingLocalizedAlt(FrappeTestCase):
	"""L4 — "çevrilebilirdi ama çevrilmedi" sinyali; batch katmanı (`_technical_findings`)."""

	def test_kaynak_cevirisi_varken_bos_ise_warn(self):
		dosya = _dosya(f"mla-warn-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		ilan = _ilan_olustur(f"MLA Warn {_TUZ}", dosya.file_url)
		self.addCleanup(_sil, "Listing", ilan)
		frappe.db.set_value("Listing", ilan, "title_en", f"MLA EN {_TUZ}")
		seo.set_asset_fields(dosya.file_url, {"alt_tr": "taban metin"})

		sonuc = seo_audit.audit_batch([dosya.file_url])
		bulgular = sonuc["files"][0]["findings"]
		kodlar = [b["code"] for b in bulgular]
		self.assertIn("missing_localized_alt", kodlar)
		bulgu = next(b for b in bulgular if b["code"] == "missing_localized_alt")
		self.assertEqual(bulgu["severity"], seo_audit.SEVERITY_WARN)
		self.assertIn("en", bulgu["detail"])

	def test_kaynak_cevirisi_yokken_susar(self):
		"""L1/L4 tutarlılığı: `title_en/ar/ru` boşsa kural hiç tetiklenmez."""
		dosya = _dosya(f"mla-susar-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		ilan = _ilan_olustur(f"MLA Susar {_TUZ}", dosya.file_url)
		self.addCleanup(_sil, "Listing", ilan)
		seo.set_asset_fields(dosya.file_url, {"alt_tr": "taban metin"})

		sonuc = seo_audit.audit_batch([dosya.file_url])
		kodlar = [b["code"] for b in sonuc["files"][0]["findings"]]
		self.assertNotIn("missing_localized_alt", kodlar)

	def test_alt_lang_doluysa_susar(self):
		dosya = _dosya(f"mla-dolu-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		ilan = _ilan_olustur(f"MLA Dolu {_TUZ}", dosya.file_url)
		self.addCleanup(_sil, "Listing", ilan)
		frappe.db.set_value("Listing", ilan, "title_en", f"MLA EN Dolu {_TUZ}")
		seo.set_asset_fields(dosya.file_url, {"alt_tr": "taban metin", "alt_en": "zaten çevrilmiş"})

		sonuc = seo_audit.audit_batch([dosya.file_url])
		kodlar = [b["code"] for b in sonuc["files"][0]["findings"]]
		self.assertNotIn("missing_localized_alt", kodlar)

	def test_taban_alt_bossa_susar(self):
		"""`missing_alt` zaten var — `missing_localized_alt` tekrar etmez.

		`_ilan_olustur` kendisi `on_reference_change` kancasını tetikler ve
		`alt_tr`'yi Listing başlığından otomatik doldurur; taban alt'ı GERÇEKTEN
		boş bırakmak için insan damgasıyla açıkça boşaltılıyor (REFRESHABLE
		olmayan damga — `refresh_alt` bir daha dokunmaz)."""
		dosya = _dosya(f"mla-bosalt-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		ilan = _ilan_olustur(f"MLA Bos Alt {_TUZ}", dosya.file_url)
		self.addCleanup(_sil, "Listing", ilan)
		frappe.db.set_value("Listing", ilan, "title_en", f"MLA EN Bos {_TUZ}")
		seo.set_asset_fields(dosya.file_url, {"alt_tr": "", "alt_source": seo.SOURCE_HUMAN})

		sonuc = seo_audit.audit_batch([dosya.file_url])
		kodlar = [b["code"] for b in sonuc["files"][0]["findings"]]
		self.assertNotIn("missing_localized_alt", kodlar)

	def test_gorunmeyen_listing_susar(self):
		"""`storefront_visible=0` — kural görünmeyen ilan yüzünden yanlış alarm
		vermez (batch preload yalnız görünür Listing'i haritalar)."""
		dosya = _dosya(f"mla-gizli-{_TUZ}.txt")
		self.addCleanup(_sil, "File", dosya.name)
		ilan = _ilan_olustur(f"MLA Gizli {_TUZ}", dosya.file_url)
		self.addCleanup(_sil, "Listing", ilan)
		frappe.db.set_value("Listing", ilan, "title_en", f"MLA EN Gizli {_TUZ}")
		frappe.db.set_value("Listing", ilan, "storefront_visible", 0)
		seo.set_asset_fields(dosya.file_url, {"alt_tr": "taban metin"})

		sonuc = seo_audit.audit_batch([dosya.file_url])
		kodlar = [b["code"] for b in sonuc["files"][0]["findings"]]
		self.assertNotIn("missing_localized_alt", kodlar)
