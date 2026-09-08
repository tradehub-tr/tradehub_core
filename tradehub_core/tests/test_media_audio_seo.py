"""Ses dosyası SEO — `AudioObject` şeması (MOGEM-620 §6 · §15).

MOGEM-620 kabul kriteri 7 dört şema türü istiyor: ImageObject, VideoObject,
AudioObject, DigitalDocument. Denetimde (4 Eyl 2026) üçü vardı, **AudioObject
yoktu** — bu dosya onu sabitliyor.

Bu dosyanın sabitlediği kurallar:
  1. `build_audio_object` adı olmayan girdide `None` döner (geçersiz yapısal
     veri hiç üretilmez — `build_video_object`/`build_digital_document` ile
     aynı ilke)
  2. Ad `title`'dan, yoksa dosya adı gövdesinden türetilir
  3. Sanatçı `byArtist`e DEĞİL `author`a yazılır (`byArtist` MusicRecording
     alanı; genel ses dosyasında geçersiz olurdu)
  4. `author` ile `creator` birlikte basılabilir — farklı şeylerdir
  5. Süre ISO-8601 (`PT3M25S`), boşsa anahtar hiç girmez
  6. Göreli kapak URL'si mutlaklaştırılır

Koşum:
    docker exec istoc-backend bench --site tradehub.localhost \\
        run-tests --module tradehub_core.tests.test_media_audio_seo
"""

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from tradehub_core.seo.schema_builder import build_audio_object

_SITE = "https://istoc.example"


class TestAudioObjectIskeleti(FrappeTestCase):
	def test_a_bos_content_url_none_doner(self):
		"""Adres yoksa nesne yok — düz URL'ye düşmek bile anlamsız."""
		self.assertIsNone(build_audio_object({"title": "Bölüm 1"}, _SITE, content_url=""))

	def test_b_ad_turetilemiyorsa_none_doner(self):
		"""`title` boş VE dosya adı gövdesi boşsa nesne üretilmez.

		`/files/.mp3` gibi bir adreste gövde boş kalır; `{"name": ""}` basmak
		Google'ın geçersiz saydığı yapısal veridir.
		"""
		self.assertIsNone(build_audio_object({}, _SITE, content_url="/files/.mp3"))

	def test_c_ad_dosya_adindan_turetilir(self):
		obj = build_audio_object({}, _SITE, content_url="/files/roportaj-3.mp3")
		self.assertEqual(obj["name"], "roportaj-3")

	def test_d_baslik_dosya_adini_ezer(self):
		obj = build_audio_object({"title": "Röportaj — 3. Bölüm"}, _SITE, content_url="/files/x.mp3")
		self.assertEqual(obj["name"], "Röportaj — 3. Bölüm")

	def test_e_url_ve_content_url_ayni_mutlak_adres(self):
		obj = build_audio_object({"title": "S"}, _SITE, content_url="/files/a.mp3")
		self.assertEqual(obj["url"], f"{_SITE}/files/a.mp3")
		self.assertEqual(obj["contentUrl"], obj["url"])

	def test_f_tip_audio_object(self):
		obj = build_audio_object({"title": "S"}, _SITE, content_url="/files/a.mp3")
		self.assertEqual(obj["@type"], "AudioObject")


class TestAudioObjectAlanlari(FrappeTestCase):
	def test_g_uzanti_verilince_mime_cozulur(self):
		"""Çıplak uzantı `mimetypes` tarafından gizli dosya sanılır —
		`build_digital_document`taki sahte dosya adı hilesi burada da çalışmalı."""
		obj = build_audio_object({"title": "S"}, _SITE, content_url="/files/a", uzanti=".mp3")
		self.assertEqual(obj["encodingFormat"], "audio/mpeg")

	def test_h_uzanti_yoksa_adresten_cozulur(self):
		obj = build_audio_object({"title": "S"}, _SITE, content_url="/files/a.wav")
		self.assertEqual(obj["encodingFormat"], "audio/x-wav")

	def test_i_sure_iso8601(self):
		obj = build_audio_object({"title": "S", "duration": 205}, _SITE, content_url="/files/a.mp3")
		self.assertEqual(obj["duration"], "PT3M25S")

	def test_j_sifir_sure_anahtar_basmaz(self):
		obj = build_audio_object({"title": "S", "duration": 0}, _SITE, content_url="/files/a.mp3")
		self.assertNotIn("duration", obj)

	def test_k_sanatci_author_olur_byartist_degil(self):
		"""`byArtist` MusicRecording alanı — genel ses dosyasında geçersiz."""
		obj = build_audio_object(
			{"title": "S", "artist": "Ayşe Yıldız"}, _SITE, content_url="/files/a.mp3"
		)
		self.assertEqual(obj["author"], {"@type": "Person", "name": "Ayşe Yıldız"})
		self.assertNotIn("byArtist", obj)

	def test_l_author_ve_creator_birlikte_basilabilir(self):
		"""Farklı şeyler: `creator` hakları tutan kurum, `author` sesi üreten kişi."""
		obj = build_audio_object(
			{"title": "S", "artist": "Ayşe Yıldız", "creator": "iStoc A.Ş."},
			_SITE,
			content_url="/files/a.mp3",
		)
		self.assertEqual(obj["author"]["name"], "Ayşe Yıldız")
		self.assertEqual(obj["creator"], {"@type": "Organization", "name": "iStoc A.Ş."})

	def test_m_kapak_mutlaklastirilir(self):
		obj = build_audio_object(
			{"title": "S", "cover_url": "/files/kapak.jpg"}, _SITE, content_url="/files/a.mp3"
		)
		self.assertEqual(obj["thumbnailUrl"], f"{_SITE}/files/kapak.jpg")

	def test_n_mutlak_kapak_yeniden_yazilmaz(self):
		obj = build_audio_object(
			{"title": "S", "cover_url": "https://cdn.example/k.jpg"},
			_SITE,
			content_url="/files/a.mp3",
		)
		self.assertEqual(obj["thumbnailUrl"], "https://cdn.example/k.jpg")

	def test_o_dil_inlanguage(self):
		obj = build_audio_object({"title": "S", "language": "tr"}, _SITE, content_url="/files/a.mp3")
		self.assertEqual(obj["inLanguage"], "tr")

	def test_p_aciklama_caption_oncelikli(self):
		obj = build_audio_object(
			{"title": "S", "caption": "Kısa tarif", "description": "Uzun tarif"},
			_SITE,
			content_url="/files/a.mp3",
		)
		self.assertEqual(obj["description"], "Kısa tarif")

	def test_r_lisans_besligi_ortak_yardimcidan_gelir(self):
		"""`ImageObject`/`DigitalDocument` ile AYNI beşli — mükerrer kod yok."""
		obj = build_audio_object(
			{
				"title": "S",
				"credit_text": "Foto: iStoc",
				"copyright_notice": "© 2026",
				"license_url": "/lisans",
				"acquire_license_url": "/lisans-al",
			},
			_SITE,
			content_url="/files/a.mp3",
		)
		self.assertEqual(obj["creditText"], "Foto: iStoc")
		self.assertEqual(obj["copyrightNotice"], "© 2026")
		self.assertEqual(obj["license"], f"{_SITE}/lisans")
		self.assertEqual(obj["acquireLicensePage"], f"{_SITE}/lisans-al")

	def test_s_bos_alanlar_anahtar_basmaz(self):
		"""Boş dize taşıyan anahtar yapısal veriyi kirletir — hiç basılmamalı."""
		obj = build_audio_object(
			{"title": "S", "artist": "", "cover_url": "", "language": "", "transcript": ""},
			_SITE,
			content_url="/files/a.mp3",
		)
		for anahtar in ("author", "thumbnailUrl", "inLanguage", "transcript"):
			self.assertNotIn(anahtar, obj)


class TestKapakGeriDususu(FrappeTestCase):
	"""`fields_for` kapağı `poster_url` kolonunda tutuyor; şema ikisini de okur."""

	def test_t_poster_url_kapak_olarak_okunur(self):
		obj = build_audio_object(
			{"title": "S", "poster_url": "/files/p.jpg"}, _SITE, content_url="/files/a.mp3"
		)
		self.assertEqual(obj["thumbnailUrl"], f"{_SITE}/files/p.jpg")

	def test_u_cover_url_poster_url_u_ezer(self):
		obj = build_audio_object(
			{"title": "S", "cover_url": "/files/k.jpg", "poster_url": "/files/p.jpg"},
			_SITE,
			content_url="/files/a.mp3",
		)
		self.assertEqual(obj["thumbnailUrl"], f"{_SITE}/files/k.jpg")
