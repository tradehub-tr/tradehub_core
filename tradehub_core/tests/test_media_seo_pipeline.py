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
