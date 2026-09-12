"""MOGEM-620 — uçtan uca akışlar.

NE ÖLÇÜYOR
----------
Diğer modüller PARÇALARI ölçüyor. Bu modül ZİNCİRİ ölçüyor: kullanıcının
gerçekten yaptığı iş baştan sona yürüyor mu ve her halkanın çıktısı bir
sonrakinin girdisiyle uyuşuyor mu.

Her sınıf bir KABUL KRİTERİNE karşılık geliyor ve docstring'inde hangisi
olduğu yazılı — kriter metni Plane'deki MOGEM-620 kaydından.

Koşum:
    docker exec istoc-backend bench --site tradehub.localhost \\
        run-tests --module tradehub_core.tests.test_mogem620_e2e
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_admin, seller_media
from tradehub_core.media import bulk_ops, inventory, metadata, meter, ownership, seo, seo_audit, tags_source
from tradehub_core.seo import schema_builder
from tradehub_core.tests.mogem620_ortak import (
	TUZ,
	dosya_ac,
	kullanici,
	magaza_bul,
	mp3_uret,
	png_uret,
	sil,
)


def _satici_ve_magaza() -> tuple[str, str] | tuple[None, None]:
	magaza = magaza_bul()
	if not magaza:
		return None, None
	for u in ownership.users_of(magaza):
		if u and u not in ("Administrator", "Guest"):
			return u, magaza
	return None, None


class TestSesUctanUca(FrappeTestCase):
	"""Kabul kriteri 18 — "PDF, audio ve ofis dokümanı örneklerinde türüne
	uygun metadata, text extraction/transcript, preview/thumbnail,
	accessibility ve indexability alanları üretilebilir."

	ZİNCİR: yükle → kanca kuyruğa atar → çıkarım → okuma kapısı → AudioObject.
	"""

	def setUp(self):
		try:
			self.veri = mp3_uret(1.0, baslik=f"E2E {TUZ}", sanatci="Sanatçı")
		except Exception:
			self.skipTest("ffmpeg yok.")

	def test_yukleme_kancayi_tetikler_ve_cikarim_semayi_doldurur(self):
		from unittest import mock

		# 1. Yükleme — kanca GERÇEKTEN çağrılıyor mu (mock'lanmamış hâliyle).
		with mock.patch("tradehub_core.media.av.enqueue_scan"), mock.patch(
			"frappe.enqueue"
		) as kuyruk:
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"e2e-ses-{TUZ}.mp3",
					"is_private": 0,
					"content": self.veri,
					"decode": False,
				}
			)
			doc.flags.ignore_permissions = True
			doc.insert()
		self.addCleanup(sil, "File", doc.name)

		cagrilar = [c.args[0] for c in kuyruk.call_args_list if c.args]
		self.assertIn(
			"tradehub_core.media.audio_meta.apply",
			cagrilar,
			"yükleme ses çıkarımını kuyruğa ATMADI — 10 Eyl bulgusu geri geldi",
		)

		# 2. Worker'ın yapacağı işi burada senkron yapıyoruz.
		from tradehub_core.media import audio_meta

		self.assertTrue(audio_meta.apply(doc.file_url))

		# 3. Okuma kapısı çıkarımı görüyor mu.
		alanlar = seo.fields_for(doc.file_url)
		self.assertGreater(alanlar["duration"], 0)
		self.assertEqual(alanlar["artist"], "Sanatçı")

		# 4. Yapısal veri üretilebiliyor mu.
		nesne = schema_builder.build_audio_object(
			alanlar, "https://x.test", content_url=doc.file_url
		)
		self.assertEqual(nesne["@type"], "AudioObject")
		# `author` düz metin DEĞİL: `build_audio_object` onu `Person`
		# nesnesine sarıyor — schema.org'da `author` bir `Person`/`Organization`
		# bekliyor ve düz metin geçersiz yapısal veri olurdu.
		self.assertEqual(nesne["author"], {"@type": "Person", "name": "Sanatçı"})


class TestAramaUctanUca(FrappeTestCase):
	"""Kabul kriteri 13 — "Filename, metadata, OCR/transcript, semantic/vector/
	entity ve visual similarity dahil tanımlanan arama türleri uygun yetki ve
	tenant sınırları içinde sonuç döndürür."

	ZİNCİR: metin yaz → kütüphanede o metinle ara → dosya gelsin.
	"""

	def setUp(self):
		self.user, self.magaza = _satici_ve_magaza()
		if not self.user:
			self.skipTest("Mağazalı satıcı yok.")
		self.iğne = f"benzersizkelime{TUZ}"

	def _magaza_dosyasi(self, ad: str, veri: bytes):
		doc = dosya_ac(ad, veri, owner=self.user)
		self.addCleanup(sil, "File", doc.name)
		return doc

	def test_aciklamada_arama_calisir(self):
		doc = self._magaza_dosyasi(f"ara-aciklama-{TUZ}.png", png_uret())
		seo.set_asset_fields(doc.file_url, {"description_tr": f"içinde {self.iğne} geçen açıklama"})
		with kullanici(self.user):
			sonuc = inventory.list_files(search=self.iğne, store=self.magaza, page_size=50)
		adresler = [s["file_url"] for s in sonuc["items"]]
		self.assertIn(doc.file_url, adresler, "açıklama araması dosyayı bulmalı (§16)")

	def test_cikarilan_metinde_arama_calisir(self):
		"""OCR/PDF metni — 10 Eyl öncesi bu sütun HİÇ aranmıyordu."""
		doc = self._magaza_dosyasi(f"ara-metin-{TUZ}.csv", f"baslik\n{self.iğne}\n".encode())
		from tradehub_core.media import doc_meta

		self.assertTrue(doc_meta.apply(doc.file_url))
		with kullanici(self.user):
			sonuc = inventory.list_files(search=self.iğne, store=self.magaza, page_size=50)
		self.assertIn(doc.file_url, [s["file_url"] for s in sonuc["items"]])

	def test_transkriptte_arama_calisir(self):
		doc = self._magaza_dosyasi(f"ara-transkript-{TUZ}.png", png_uret())
		seo.set_asset_fields(doc.file_url, {"transcript": f"konuşma metni {self.iğne} burada"})
		with kullanici(self.user):
			sonuc = inventory.list_files(search=self.iğne, store=self.magaza, page_size=50)
		self.assertIn(doc.file_url, [s["file_url"] for s in sonuc["items"]])

	def test_ilgisiz_kelime_sonuc_dondurmez(self):
		"""Nöbetçi: arama her şeyi döndürüyorsa yukarıdaki üç test anlamsız."""
		self._magaza_dosyasi(f"ara-negatif-{TUZ}.png", png_uret())
		with kullanici(self.user):
			sonuc = inventory.list_files(
				search=f"hicbiryerdeyok{TUZ}", store=self.magaza, page_size=50
			)
		self.assertEqual(sonuc["items"], [], "arama alakasız kelimede boş dönmeli")


class TestTopluIslemUctanUca(FrappeTestCase):
	"""Kabul kriteri 17 — "Tanımlanan bulk işlemler seçili asset'lerde toplu
	uygulanır; yetki kontrolü, hata özeti ve kısmi başarısızlık sonucu
	görünürdür."

	ZİNCİR: seç → uygula → denetimde etkisini gör.
	"""

	def setUp(self):
		self.dosyalar = [
			dosya_ac(f"e2e-toplu-{TUZ}-{i}.png", png_uret()) for i in range(3)
		]
		for d in self.dosyalar:
			self.addCleanup(sil, "File", d.name)
		self.urls = [d.file_url for d in self.dosyalar]

	def test_toplu_lisans_denetim_bulgusunu_kapatir(self):
		"""Toplu yazmanın SONUCU denetimde görünmeli — yoksa iş yarım."""
		once = seo_audit.audit_scope(self.urls)
		self.assertGreater(once["summary"].get("missing_license", 0), 0)

		bulk_ops.set_fields_many(self.urls, {"license_url": "https://ornek.test/lisans"})

		sonra = seo_audit.audit_scope(self.urls, refresh=True)
		self.assertEqual(sonra["summary"].get("missing_license", 0), 0)

	def test_toplu_gorunurluk_index_kararini_degistirir(self):
		from tradehub_core.media import seo_index

		bulk_ops.set_indexability_many(self.urls, "Unlisted")
		karar = seo_index.decide(self.urls[0], check_usage=False)
		self.assertFalse(karar["indexable"], "Unlisted dosya indexlenebilir görünmemeli")

	def test_kismi_basarisizlik_ozeti_dondurulur(self):
		sonuc = bulk_ops.set_indexability_many(
			[*self.urls, f"/files/yok-{TUZ}.png"], "Public"
		)
		self.assertEqual(sonuc["applied"], 4, "olmayan adres de yazma denemesi alır")
		self.assertEqual(set(sonuc), {"applied", "files", "skipped", "failed"})


class TestEtiketKaynagiUctanUca(FrappeTestCase):
	"""Kabul kriteri 19 — "Folder, Category ve Tag veri modelleri birbirine
	karışmadan çalışır; tag kaynağı AI/System/Manual olarak izlenir."
	"""

	def setUp(self):
		self.user, self.magaza = _satici_ve_magaza()
		if not self.user:
			self.skipTest("Mağazalı satıcı yok.")
		self.doc = dosya_ac(f"e2e-etiket-{TUZ}.png", png_uret(), owner=self.user)
		self.addCleanup(sil, "File", self.doc.name)

	def test_panelden_yazilan_etiket_manual_isaretlenir(self):
		metadata.write(self.doc.file_url, self.magaza, {"tags": ["kirmizi", "koltuk"]})
		okunan = metadata.read(self.doc.file_url, self.magaza)
		self.assertEqual(sorted(okunan["tags"]), ["kirmizi", "koltuk"])
		self.assertEqual(okunan["tag_sources"]["kirmizi"], "manual")
		self.assertEqual(okunan["tag_source_summary"]["manual"], 2)

	def test_makine_etiketi_insan_etiketini_ezmez(self):
		metadata.write(self.doc.file_url, self.magaza, {"tags": ["kirmizi"]})
		kayitlar = frappe.get_all("File", filters={"file_url": self.doc.file_url}, pluck="name")
		tags_source.write(kayitlar, ["kirmizi"], tags_source.SOURCE_AI)
		self.assertEqual(
			metadata.read(self.doc.file_url, self.magaza)["tag_sources"]["kirmizi"], "manual"
		)

	def test_silinen_etiketin_kaynagi_da_dusar(self):
		metadata.write(self.doc.file_url, self.magaza, {"tags": ["a", "b"]})
		metadata.write(self.doc.file_url, self.magaza, {"tags": ["a"]})
		kaynaklar = metadata.read(self.doc.file_url, self.magaza)["tag_sources"]
		self.assertIn("a", kaynaklar)
		self.assertNotIn("b", kaynaklar, "yetim kaynak birikmemeli")

	def test_etiket_kategori_klasor_ayri_kavramlar(self):
		"""Üçü birbirine karışmamalı — kriter 19'un ilk yarısı."""
		metadata.write(self.doc.file_url, self.magaza, {"tags": ["etiket-x"]})
		okunan = metadata.read(self.doc.file_url, self.magaza)
		self.assertEqual(okunan["tags"], ["etiket-x"])
		# Üçü ÜÇ AYRI depoda: etiket `File` kolonunda, klasör ve kategori
		# kendi bağ tablolarında. Aynı yerde tutulsalardı "kategoriye göre
		# filtrele" ile "etikete göre filtrele" aynı sorgu olurdu.
		self.assertTrue(frappe.db.table_exists("Media Folder Item"), "klasör bağı ayrı tablo")
		self.assertTrue(
			frappe.db.table_exists("Media Category Assignment"), "kategori bağı ayrı tablo"
		)
		self.assertTrue(frappe.db.has_column("File", "th_media_tags"), "etiket File kolonunda")


class TestLocaleMedyaUctanUca(FrappeTestCase):
	"""Kabul kriteri 14 — "Locale bazlı alt/title/caption/description ile
	transcript/subtitle değerleri saklanır; locale-specific media override'ı
	çalışır."
	"""

	def setUp(self):
		self.kaynak = dosya_ac(f"e2e-locale-{TUZ}.png", png_uret(renk="red"))
		self.arapca = dosya_ac(f"e2e-locale-ar-{TUZ}.png", png_uret(renk="green"))
		self.addCleanup(sil, "File", self.kaynak.name)
		self.addCleanup(sil, "File", self.arapca.name)

	def test_dort_alan_dort_dilde_saklanir_ve_medya_ezmesi_calisir(self):
		seo.set_asset_fields(
			self.kaynak.file_url,
			{
				"alt_ar": "نص بديل",
				"title_ar": "عنوان",
				"caption_ar": "تعليق",
				"description_ar": "وصف",
				"transcript_ar": "نص",
				"captions_url_ar": "/c/ar.vtt",
			},
		)
		ar = seo.fields_for(self.kaynak.file_url, lang="ar")
		self.assertEqual(
			(ar["alt"], ar["title"], ar["caption"], ar["description"]),
			("نص بديل", "عنوان", "تعليق", "وصف"),
		)
		self.assertEqual(ar["transcript"], "نص")
		self.assertEqual(ar["captions_url"], "/c/ar.vtt")

		media_admin.set_media_locale_variant(
			file_url=self.kaynak.file_url, locale="ar", variant_url=self.arapca.file_url
		)
		self.addCleanup(
			lambda: [
				sil(seo.LOCALE_VARIANT_DOCTYPE, n)
				for n in frappe.get_all(
					seo.LOCALE_VARIANT_DOCTYPE,
					filters={"file_url": self.kaynak.file_url},
					pluck="name",
				)
			]
		)
		cozum = seo.resolve_media_for_locale(self.kaynak.file_url, lang="ar")
		self.assertEqual(cozum["file_url"], self.arapca.file_url)
		self.assertTrue(cozum["overridden"])

		# Diğer diller etkilenmemeli.
		self.assertEqual(
			seo.resolve_media_for_locale(self.kaynak.file_url, lang="tr")["file_url"],
			self.kaynak.file_url,
		)

	def test_ezme_silinince_kaynaga_doner(self):
		media_admin.set_media_locale_variant(
			file_url=self.kaynak.file_url, locale="en", variant_url=self.arapca.file_url
		)
		media_admin.set_media_locale_variant(
			file_url=self.kaynak.file_url, locale="en", variant_url=""
		)
		self.assertFalse(
			seo.resolve_media_for_locale(self.kaynak.file_url, lang="en")["overridden"]
		)


class TestDenetimSkoruUctanUca(FrappeTestCase):
	"""Kabul kriteri 16 — "Audit motoru … toplam puan ile 10 alt puanı ayrı
	gösterir."
	"""

	def setUp(self):
		self.doc = dosya_ac(f"e2e-skor-{TUZ}.png", png_uret())
		self.addCleanup(sil, "File", self.doc.name)

	def test_kapsam_denetimi_on_alt_puan_dondurur(self):
		sonuc = seo_audit.audit_scope([self.doc.file_url], refresh=True)
		for boyut in (*seo_audit.DIMENSIONS, "overall"):
			self.assertIn(boyut, sonuc["score"], msg=boyut)
		self.assertEqual(len(seo_audit.DIMENSIONS), 10)

	def test_alan_doldukca_skor_yukselir(self):
		once = seo_audit.audit_scope([self.doc.file_url], refresh=True)["score"]["ai_readiness"]
		seo.set_asset_fields(
			self.doc.file_url,
			{
				"description_tr": "Ayrıntılı açıklama",
				"caption_tr": "Altyazı",
				"canonical": "/urun/x",
				"license_url": "/lisans",
				"creator": "Fotoğrafçı",
			},
		)
		sonra = seo_audit.audit_scope([self.doc.file_url], refresh=True)["score"]["ai_readiness"]
		self.assertGreater(sonra, once)

	def test_cozme_maliyeti_bulgusu_uretilebiliyor(self):
		"""§9 dördüncü bileşen denetimde GÖRÜNÜR olmalı."""
		frappe.db.set_value(
			"File",
			self.doc.name,
			{"th_media_width": 6000, "th_media_height": 5000},
			update_modified=False,
		)
		sonuc = seo_audit.audit_scope([self.doc.file_url], refresh=True)
		kodlar = {b["code"] for d in sonuc["files"] for b in d["findings"]}
		self.assertIn("expensive_decode", kodlar)


class TestKotaUctanUca(FrappeTestCase):
	"""Kabul kriteri 20 — "Tenant kotaları, politikaları ve erişim sınırları
	tenant'lar arasında veri sızıntısı olmadan uygulanır."
	"""

	def setUp(self):
		self.user, self.magaza = _satici_ve_magaza()
		if not self.user:
			self.skipTest("Mağazalı satıcı yok.")
		self.addCleanup(self._temizle)

	def _temizle(self):
		for ad in frappe.get_all(
			meter.DOCTYPE, filters={"store": self.magaza, "period_key": meter.period_key()},
			pluck="name",
		):
			sil(meter.DOCTYPE, ad)

	def test_sayac_tuketimi_ozette_gorunur(self):
		meter.record(self.magaza, meter.METRIC_TRANSFORMATIONS, 7)
		ozet = meter.summary(self.magaza)
		self.assertEqual(ozet[meter.METRIC_TRANSFORMATIONS]["used"], 7)

	def test_upload_limits_akis_kotalarini_tasir(self):
		with kullanici(self.user):
			limitler = seller_media.upload_limits()
		self.assertIn("flow_quotas", limitler)
		self.assertEqual(set(limitler["flow_quotas"]), set(meter.QUOTA_KEYS))

	def test_sayac_magazaya_ozel(self):
		"""Bir mağazanın tüketimi diğerinin sayacında GÖRÜNMEMELİ."""
		digerleri = [
			m for m in frappe.get_all("Admin Seller Profile", pluck="name", limit=3)
			if m != self.magaza
		]
		if not digerleri:
			self.skipTest("İkinci mağaza yok.")
		meter.record(self.magaza, meter.METRIC_AI, 5)
		self.assertEqual(meter.consumed(digerleri[0], meter.METRIC_AI), 0)


class TestUrunSemasiUctanUca(FrappeTestCase):
	"""Kabul kriteri 15 — "E-commerce özellikleri etkinleştirildiğinde
	product/variant/SKU/GTIN ilişkileri, media rolleri ve Product/ProductGroup
	structured data bağlantısı çalışır."
	"""

	def test_gercek_ilanda_sema_uretilebiliyor(self):
		ilan = frappe.get_all(
			"Listing", filters={"storefront_visible": 1}, fields=["name"], limit=1
		)
		if not ilan:
			self.skipTest("Vitrinde ilan yok.")
		listing = frappe.get_doc("Listing", ilan[0]["name"]).as_dict()
		semalar = schema_builder.compose_for_listing(listing, {}, "https://x.test")
		urun = next(s for s in semalar if str(s.get("@id", "")).endswith("#product"))
		self.assertIn(urun["@type"], ("Product", "ProductGroup"))
		if urun["@type"] == "ProductGroup":
			self.assertIn("hasVariant", urun)
			for varyant in urun["hasVariant"]:
				self.assertTrue(
					varyant.get("sku") or varyant.get("gtin"),
					"kimliksiz varyant yapısal veriye girmemeli",
				)

	def test_medya_rolu_semaya_yansiyor(self):
		"""Birincil görsel `representativeOfPage` taşımalı."""
		ilan = frappe.get_all(
			"Listing",
			filters={"storefront_visible": 1, "primary_image": ["is", "set"]},
			fields=["name"],
			limit=1,
		)
		if not ilan:
			self.skipTest("Birincil görselli ilan yok.")
		listing = frappe.get_doc("Listing", ilan[0]["name"]).as_dict()
		semalar = schema_builder.compose_for_listing(listing, {}, "https://x.test")
		urun = next(s for s in semalar if str(s.get("@id", "")).endswith("#product"))
		gorseller = [g for g in (urun.get("image") or []) if isinstance(g, dict)]
		if not gorseller:
			self.skipTest("ImageObject üretilmedi (alan yok) — rol sınanamaz.")
		self.assertTrue(
			any(g.get("representativeOfPage") for g in gorseller),
			"birincil görsel işaretlenmemiş",
		)


class TestBolumlerUctanUca(FrappeTestCase):
	"""§5 — bölüm yaz → doğrula → Clip listesi olarak şemada gör."""

	def setUp(self):
		self.doc = dosya_ac(f"e2e-bolum-{TUZ}.png", png_uret())
		self.addCleanup(sil, "File", self.doc.name)

	def test_bolumler_yazilir_ve_semaya_doner(self):
		seo.set_asset_fields(
			self.doc.file_url,
			{
				"chapters": json.dumps(
					[{"start": 30, "title": "Detay"}, {"start": 0, "title": "Giriş"}]
				),
				"regions_allowed": "TR,DE",
				"content_rating": "PG",
				"age_restriction": "18+",
			},
		)
		alanlar = seo.fields_for(self.doc.file_url)
		alanlar["poster_url"] = "/files/p.jpg"
		alanlar["title"] = "Video"
		obj = schema_builder.build_video_object(
			alanlar, "https://x.test", content_url="/files/v.mp4"
		)
		self.assertEqual([c["name"] for c in obj["hasPart"]], ["Giriş", "Detay"])
		self.assertEqual(obj["regionsAllowed"], ["TR", "DE"])
		self.assertEqual(obj["contentRating"], "PG")
		self.assertIs(obj["isFamilyFriendly"], False)
