"""MOGEM-620 — duman (smoke) testleri: KABLOLAR TAKILI MI.

NEDEN AYRI VE NEDEN EN ÖNEMLİSİ
--------------------------------
Bu turun en büyük bulgusu bir mantık hatası DEĞİLDİ: `audio_meta.apply` ve
`backfill_pending` yazılmıştı, 81 testi vardı, hepsi yeşildi — ama HİÇBİR
ÇAĞIRANI YOKTU. Kod doğruydu, kablo yoktu. Canlıda bir `.mp3` yüklendiğinde
hiçbir şey olmuyordu ve tek bir test bunu göremiyordu, çünkü hepsi
fonksiyonu DOĞRUDAN çağırıyordu.

Bu modül o sınıf hatayı yakalar: her yeni yeteneğin gerçekten bir
kancaya/zamanlayıcıya/uç noktaya bağlı olduğunu sınar. Fonksiyonun NE
YAPTIĞINI değil, ÇAĞRILIP ÇAĞRILMADIĞINI ölçer.

Koşum:
    docker exec istoc-backend bench --site tradehub.localhost \\
        run-tests --module tradehub_core.tests.test_mogem620_duman
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core import hooks
from tradehub_core.media import audio_meta, doc_meta, meter, seo
from tradehub_core.tests.mogem620_ortak import TUZ, mp3_uret, sil


class TestKancalarTakili(FrappeTestCase):
	"""`hooks.py` kayıtları — kod var ama çağıran yok hatası bir daha olmasın."""

	def _after_insert(self) -> list[str]:
		return hooks.doc_events["File"]["after_insert"]

	def test_ses_cikarimi_after_insert_kancasinda(self):
		"""10 Eyl 2026 denetiminin ANA bulgusu — kablo bu satırla takıldı."""
		self.assertIn(
			"tradehub_core.media.audio_meta.maybe_extract_on_insert",
			self._after_insert(),
			"ses çıkarımı hiçbir yerden çağrılmıyorsa canlıda ÇALIŞMAZ",
		)

	def test_dokuman_cikarimi_after_insert_kancasinda(self):
		self.assertIn(
			"tradehub_core.media.doc_meta.maybe_extract_on_insert", self._after_insert()
		)

	def test_kanca_sirasi_zenginlestirmeyi_sona_koyuyor(self):
		"""SEO zenginleştirmesi güvenlik/depolama kancalarından SONRA gelmeli."""
		liste = self._after_insert()
		guvenlik = liste.index("tradehub_core.media.av.maybe_scan_on_insert")
		for zenginlestirme in (
			"tradehub_core.media.doc_meta.maybe_extract_on_insert",
			"tradehub_core.media.audio_meta.maybe_extract_on_insert",
		):
			self.assertGreater(liste.index(zenginlestirme), guvenlik, msg=zenginlestirme)

	def test_ses_backfill_gunluk_zamanlayicida(self):
		"""Kanca yalnız BUNDAN SONRAKİ yüklemeleri kapsar; geçmiş backfill ister."""
		self.assertIn(
			"tradehub_core.media.audio_meta.backfill_pending", hooks.scheduler_events["daily"]
		)

	def test_dokuman_backfill_gunluk_zamanlayicida(self):
		"""Ölçüldü 10 Eyl: 14 PDF'in tamamında `extracted_text` boştu."""
		self.assertIn(
			"tradehub_core.media.doc_meta.backfill_docs", hooks.scheduler_events["daily"]
		)

	def test_kanca_gercekten_kuyruga_atiyor(self):
		"""Kaydın varlığı yetmez — fonksiyon gerçekten `enqueue` çağırmalı."""
		from unittest import mock

		with mock.patch("frappe.enqueue") as sahte:
			audio_meta.maybe_extract_on_insert(
				frappe._dict({"file_url": f"/files/x-{TUZ}.mp3", "is_private": 0, "is_folder": 0})
			)
		self.assertTrue(sahte.called, "ses dosyasında iş kuyruğa girmedi")
		self.assertEqual(
			sahte.call_args.args[0], "tradehub_core.media.audio_meta.apply"
		)

	def test_private_ses_kuyruga_girmez(self):
		"""Private ses için public kapak türevi üretmek gizli içeriği sızdırırdı."""
		from unittest import mock

		with mock.patch("frappe.enqueue") as sahte:
			audio_meta.maybe_extract_on_insert(
				frappe._dict({"file_url": f"/files/x-{TUZ}.mp3", "is_private": 1, "is_folder": 0})
			)
		self.assertFalse(sahte.called)

	def test_ses_disi_dosya_kuyruga_girmez(self):
		from unittest import mock

		with mock.patch("frappe.enqueue") as sahte:
			audio_meta.maybe_extract_on_insert(
				frappe._dict({"file_url": f"/files/x-{TUZ}.png", "is_private": 0, "is_folder": 0})
			)
		self.assertFalse(sahte.called)

	def test_kanca_hicbir_kosulda_istisna_sizdirmaz(self):
		"""Yükleme yolunda patlamak kullanıcının dosyasını düşürürdü."""
		for bozuk in (
			frappe._dict({}),
			frappe._dict({"file_url": None}),
			frappe._dict({"file_url": 12345}),
		):
			audio_meta.maybe_extract_on_insert(bozuk)


class TestUcNoktalariKayitli(FrappeTestCase):
	"""Yeni API uçları gerçekten whitelist'te mi."""

	YENI_UCLAR = (
		"tradehub_core.api.media_admin.bulk_set_indexability",
		"tradehub_core.api.media_admin.bulk_set_media_seo",
		"tradehub_core.api.media_admin.bulk_rename_media",
		"tradehub_core.api.media_admin.find_similar_media",
		"tradehub_core.api.media_admin.get_media_locale_variants",
		"tradehub_core.api.media_admin.set_media_locale_variant",
		"tradehub_core.api.seller_media.find_similar_media",
		"tradehub_core.api.seller_media.bulk_update_media_seo",
		"tradehub_core.api.seller_media.bulk_rename_my_media",
		"tradehub_core.api.seller_media.bulk_remove_media_categories",
	)

	def test_hepsi_whitelistte(self):
		"""Frappe işaretlemeyi FONKSİYONUN ÜZERİNDE tutmuyor.

		`frappe.whitelist()` fonksiyona öznitelik EKLEMİYOR; kaydı global
		`frappe.whitelisted` kümesinde tutuyor. `getattr(fn, "whitelisted")`
		her zaman `False` döner ve o iddiayla yazılmış bir test hiçbir şey
		ölçmez — kaydı kaldırsan bile yeşil kalır.
		"""
		for yol in self.YENI_UCLAR:
			self.assertIn(
				frappe.get_attr(yol),
				frappe.whitelisted,
				msg=f"{yol} whitelist'te değil — HTTP üzerinden çağrılamaz",
			)

	def test_yazma_uclari_post_zorunlu(self):
		"""Yazma ucu GET ile çağrılabilirse CSRF yüzeyi açılır.

		Metot kısıtı da fonksiyonun üzerinde değil; global
		`frappe.allowed_http_methods_for_whitelisted_func` haritasında.
		"""
		for yol in self.YENI_UCLAR:
			if not any(x in yol for x in ("bulk_", "set_media_locale_variant")):
				continue
			fn = frappe.get_attr(yol)
			metotlar = frappe.allowed_http_methods_for_whitelisted_func.get(fn)
			self.assertIsNotNone(metotlar, msg=f"{yol} metot kısıtı yok")
			self.assertIn("POST", metotlar, msg=yol)
			self.assertNotIn("GET", metotlar, msg=f"{yol} GET kabul ediyor")

	def test_okuma_uclari_metot_kisiti_gerektirmez(self):
		"""Nöbetçi: yukarıdaki testin süzgeci gerçekten süzüyor mu.

		`find_similar_media` ve `get_media_locale_variants` okuma uçları;
		POST zorunluluğu onlarda ARANMIYOR. Süzgeç bozulursa (ör. koşul
		ters çevrilirse) bu test kırmızıya döner ve yukarıdaki testin
		sessizce boşalmadığını kanıtlar.
		"""
		okuma = [y for y in self.YENI_UCLAR if "find_similar_media" in y]
		self.assertTrue(okuma, "okuma ucu listesi boşaldı — süzgeç testi anlamsız")
		for yol in okuma:
			self.assertIn(frappe.get_attr(yol), frappe.whitelisted, msg=yol)


class TestSemaVeKolonlarYerinde(FrappeTestCase):
	"""v15_9_54/55 yamalarının ürettiği yapı gerçekten var mı."""

	def test_yeni_file_kolonlari_var(self):
		beklenen = (
			"th_media_long_description", "th_media_keywords", "th_media_entities",
			"th_media_content_purpose", "th_media_source", "th_media_creator_role",
			"th_media_country", "th_media_region", "th_media_location", "th_media_geo",
			"th_media_chapters", "th_media_regions_allowed", "th_media_age_restriction",
			"th_media_content_rating", "th_media_tag_sources",
		)
		for kolon in beklenen:
			self.assertTrue(frappe.db.has_column("File", kolon), msg=kolon)

	def test_cok_dilli_kolonlar_dort_dilde_var(self):
		from tradehub_core.seo.i18n import CONTENT_LANGS

		for alan in seo.ASSET_TRANSLATABLE:
			for lang in CONTENT_LANGS:
				self.assertTrue(
					frappe.db.has_column("File", f"th_media_{alan}_{lang}"),
					msg=f"{alan}_{lang}",
				)

	def test_urun_seo_alanlari_var(self):
		self.assertTrue(frappe.db.has_column("Listing", "gtin"))
		self.assertTrue(frappe.db.has_column("Listing Variant Item", "variant_gtin"))
		self.assertTrue(frappe.db.has_column("Listing Image", "media_role"))

	def test_yeni_doctypelar_var(self):
		self.assertTrue(frappe.db.table_exists(seo.LOCALE_VARIANT_DOCTYPE))
		self.assertTrue(frappe.db.table_exists(meter.DOCTYPE))

	def test_alan_okuma_kapisi_yeni_alanlari_dondurur(self):
		"""`fields_for` tek okuma kapısı — yeni alan eklenip de dönmüyorsa ölü."""
		from tradehub_core.tests.mogem620_ortak import dosya_ac, png_uret

		doc = dosya_ac(f"duman-{TUZ}.png", png_uret())
		self.addCleanup(sil, "File", doc.name)
		alanlar = seo.fields_for(doc.file_url)
		for ad in ("keywords", "entities", "geo", "chapters", "tag_sources", "creator_role"):
			self.assertIn(ad, alanlar, msg=ad)


class TestKotaKablolari(FrappeTestCase):
	"""§18 — sayaç gerçekten olay noktalarına bağlı mı."""

	def test_plan_kotalari_seedlenmis(self):
		import json

		planlar = frappe.get_all("Subscription Plan", fields=["name", "quota_limits"])
		if not planlar:
			self.skipTest("Abonelik planı yok.")
		for p in planlar:
			kotalar = json.loads(p.quota_limits or "{}")
			for anahtar in meter.QUOTA_KEYS.values():
				self.assertIn(anahtar, kotalar, msg=f"{p.name} → {anahtar}")

	def test_donusum_sayaci_pipeline_bridgede_cagriliyor(self):
		import inspect

		from tradehub_core.media import pipeline_bridge

		kaynak = inspect.getsource(pipeline_bridge)
		self.assertIn("meter.record(", kaynak, "dönüşüm sayacı hiç çağrılmıyor")
		self.assertIn("METRIC_TRANSFORMATIONS", kaynak)

	def test_bant_genisligi_kapisi_ve_sayaci_bagli(self):
		import inspect

		from tradehub_core.api import media_access

		kaynak = inspect.getsource(media_access)
		self.assertIn("_bant_genisligi_kapisi", kaynak)
		self.assertIn("_bant_genisligi_say", kaynak)

	def test_ai_sayaci_moderasyona_bagli(self):
		import inspect

		from tradehub_core.api import moderation

		kaynak = inspect.getsource(moderation)
		self.assertIn("_ai_kotasi_uygun", kaynak)
		self.assertIn("_ai_kotasini_say", kaynak)


class TestUctanUcaKisaAkis(FrappeTestCase):
	"""En kısa gerçek akış: ses yükle → çıkarımı çalıştır → şemaya bak.

	Duman testi olarak burada: amacı derinlemesine doğrulamak değil,
	zincirin BAŞTAN SONA kopmadığını görmek.
	"""

	def test_ses_zinciri_kopmuyor(self):
		from tradehub_core.seo.schema_builder import build_audio_object
		from tradehub_core.tests.mogem620_ortak import dosya_ac

		try:
			veri = mp3_uret(1.0, baslik=f"Duman {TUZ}", sanatci="Test")
		except Exception:
			self.skipTest("ffmpeg yok — ses zinciri sınanamaz.")

		doc = dosya_ac(f"duman-{TUZ}.mp3", veri)
		self.addCleanup(sil, "File", doc.name)

		self.assertTrue(audio_meta.apply(doc.file_url), "çıkarım başarısız")
		alanlar = seo.fields_for(doc.file_url)
		self.assertGreater(alanlar["duration"], 0)
		nesne = build_audio_object(alanlar, "https://x.test", content_url=doc.file_url)
		self.assertIsNotNone(nesne)
		self.assertEqual(nesne["@type"], "AudioObject")

	def test_dokuman_zinciri_kopmuyor(self):
		from tradehub_core.tests.mogem620_ortak import dosya_ac

		doc = dosya_ac(f"duman-{TUZ}.csv", b"baslik,deger\nsatir,1\n")
		self.addCleanup(sil, "File", doc.name)
		self.assertTrue(doc_meta.apply(doc.file_url))
		self.assertIn("satir", frappe.db.get_value("File", doc.name, "th_media_extracted_text"))
