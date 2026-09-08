"""Ses dosyası metadata çıkarımı — `audio_meta` (MOGEM-620 §15).

Bu dosyanın sabitlediği kurallar:
  1. `th_media_artist` kolonu `File`'da var (patch v15_9_53)
  2. `fields_for` `artist` ve `cover_url` anahtarlarını döndürür
  3. `cover_url` AYRI KOLON DEĞİL — `poster_url`in ses tarafındaki adı
  4. `artist` beyaz listede DEĞİL: `set_asset_fields`'tan yazılamaz
     (duration/poster_url/page_count ile aynı özel-durum deseni)
  5. `extract` desteklenmeyen uzantıda ve okunamayan dosyada İSTİSNA ATMAZ
  6. `apply` başarısız çıkarımda anti-açlık damgası (-1) yazar
  7. Negatif süre dışarıya SIZMAZ — `fields_for` 0'a kırpar
  8. `apply` DOLU başlığı/sanatçıyı ezmez

Gerçek ffprobe koşuluyor: kapsayıcı içinde ffmpeg kurulu (29 Ağu'dan beri).
Ses dosyası ffmpeg ile ÜRETİLİYOR — repoya ikili dosya eklemiyoruz.

Koşum:
    docker exec istoc-backend bench --site tradehub.localhost \\
        run-tests --module tradehub_core.tests.test_media_audio_meta
"""

from __future__ import annotations

import subprocess
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import audio_meta, seo

_TUZ: str = frappe.generate_hash(length=10)


def _mp3_uret(saniye: float = 2.0, *, baslik: str = "", sanatci: str = "") -> bytes:
	"""ffmpeg ile gerçek MP3 üret — sessiz ton, istenirse ID3 etiketli."""
	import tempfile
	from pathlib import Path

	with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
		komut = [
			"ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
			"-t", str(saniye), "-c:a", "libmp3lame", "-b:a", "32k",
		]
		if baslik:
			komut += ["-metadata", f"title={baslik}"]
		if sanatci:
			komut += ["-metadata", f"artist={sanatci}"]
		komut.append(tmp.name)
		subprocess.run(komut, capture_output=True, timeout=60, check=True)
		return Path(tmp.name).read_bytes()


def _dosya(ad: str, veri: bytes):
	"""Gerçek `File` — tarama kancası nötr (test_media_seo deseni)."""
	with mock.patch("tradehub_core.media.av.enqueue_scan"):
		doc = frappe.get_doc(
			{"doctype": "File", "file_name": ad, "is_private": 0, "content": veri, "decode": False}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
	return doc


class TestSemaVeTekKapi(FrappeTestCase):
	def test_a_artist_kolonu_var(self):
		self.assertTrue(frappe.db.has_column("File", "th_media_artist"))

	def test_b_fields_for_artist_ve_cover_url_donduruyor(self):
		doc = _dosya(f"ses-b-{_TUZ}.mp3", _mp3_uret(0.5))
		alanlar = seo.fields_for(doc.file_url)
		self.assertIn("artist", alanlar)
		self.assertIn("cover_url", alanlar)

	def test_c_cover_url_poster_url_ile_ayni_deger(self):
		"""Ayrı kolon değil, aynı gerçeğin ses tarafındaki adı."""
		doc = _dosya(f"ses-c-{_TUZ}.mp3", _mp3_uret(0.5))
		frappe.db.set_value("File", doc.name, "th_media_poster_url", "/files/k.jpg")
		alanlar = seo.fields_for(doc.file_url)
		self.assertEqual(alanlar["cover_url"], "/files/k.jpg")
		self.assertEqual(alanlar["cover_url"], alanlar["poster_url"])

	def test_d_artist_set_asset_fields_ten_yazilamaz(self):
		"""Sistem alanı — yalnız üretim hattı yazar (duration/poster ile aynı).

		`set_asset_fields` bilinmeyen anahtarda İSTİSNA ATMAZ, sessizce 0
		döner (beyaz liste dışı anahtarlar `izinli` sözlüğüne hiç girmez).
		Testi ilk hâlinde `assertRaises` ile yazmıştım — kodu okuyunca yanlış
		olduğu görüldü; sözleşme sessiz reddetmek.
		"""
		doc = _dosya(f"ses-d-{_TUZ}.mp3", _mp3_uret(0.5))
		self.assertEqual(seo.set_asset_fields(doc.file_url, {"artist": "Korsan"}), 0)
		self.assertFalse(frappe.db.get_value("File", doc.name, "th_media_artist"))


class TestCikarim(FrappeTestCase):
	def test_e_desteklenmeyen_uzanti_sessiz_reddedilir(self):
		doc = _dosya(f"ses-e-{_TUZ}.txt", b"duz metin")
		sonuc = audio_meta.extract(doc.file_url)
		self.assertFalse(sonuc["ok"])
		self.assertEqual(sonuc["reason"], "desteklenmeyen uzantı")

	def test_f_olmayan_dosya_istisna_atmaz(self):
		sonuc = audio_meta.extract("/files/hic-yok-" + _TUZ + ".mp3")
		self.assertFalse(sonuc["ok"])
		self.assertEqual(sonuc["reason"], "dosya bulunamadı")

	def test_g_sure_okunur(self):
		doc = _dosya(f"ses-g-{_TUZ}.mp3", _mp3_uret(2.0))
		sonuc = audio_meta.extract(doc.file_url)
		self.assertTrue(sonuc["ok"])
		self.assertGreater(sonuc["duration"], 1.5)
		self.assertLess(sonuc["duration"], 3.0)

	def test_h_etiketler_okunur(self):
		doc = _dosya(f"ses-h-{_TUZ}.mp3", _mp3_uret(1.0, baslik="Bölüm 7", sanatci="Ayşe Yıldız"))
		sonuc = audio_meta.extract(doc.file_url)
		self.assertEqual(sonuc["title"], "Bölüm 7")
		self.assertEqual(sonuc["artist"], "Ayşe Yıldız")

	def test_i_gomulu_kapak_yoksa_none(self):
		"""Kapaksız ses OLAĞAN — hata değil, sessiz None."""
		doc = _dosya(f"ses-i-{_TUZ}.mp3", _mp3_uret(1.0))
		self.assertIsNone(audio_meta.extract_cover(doc.file_url))


class TestUygula(FrappeTestCase):
	def test_j_apply_sure_ve_etiketleri_yazar(self):
		doc = _dosya(f"ses-j-{_TUZ}.mp3", _mp3_uret(2.0, baslik="Kayıt J", sanatci="Sanatçı J"))
		self.assertTrue(audio_meta.apply(doc.file_url))
		alanlar = seo.fields_for(doc.file_url)
		self.assertGreater(alanlar["duration"], 1.5)
		self.assertEqual(alanlar["title"], "Kayıt J")
		self.assertEqual(alanlar["artist"], "Sanatçı J")

	def test_k_dolu_baslik_ezilmez(self):
		"""Elle girilmiş değeri makine çıkarımı ASLA ezmez."""
		doc = _dosya(f"ses-k-{_TUZ}.mp3", _mp3_uret(1.0, baslik="Makine", sanatci="Makine"))
		frappe.db.set_value("File", doc.name, "th_media_title", "Elle Girilen")
		audio_meta.apply(doc.file_url)
		self.assertEqual(seo.fields_for(doc.file_url)["title"], "Elle Girilen")

	def test_l_basarisiz_cikarim_anti_aclik_damgasi_yazar(self):
		doc = _dosya(f"ses-l-{_TUZ}.mp3", b"bu gecerli bir mp3 degil")
		self.assertFalse(audio_meta.apply(doc.file_url))
		self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_duration"), -1)

	def test_m_negatif_sure_disari_sizmaz(self):
		"""-1 İÇ sözleşme; JSON-LD'ye "PT-1S" basılmamalı."""
		doc = _dosya(f"ses-m-{_TUZ}.mp3", _mp3_uret(0.5))
		frappe.db.set_value("File", doc.name, "th_media_duration", -1)
		self.assertEqual(seo.fields_for(doc.file_url)["duration"], 0)

	def test_n_kardes_kayitlarin_ikisine_de_yazilir(self):
		"""Aynı adrese işaret eden tüm `File`lar güncellenir (doc_meta deseni).

		Kardeş, `file_url`i elle verilen bir bağ kaydıyla DEĞİL, AYNI baytları
		ikinci kez yükleyerek üretilir — içerik-adresli adlandırma ikisini de
		aynı adrese düşürür. İlk yazımda elle kayıt kurmuştum; o kayıt diske
		yazılmadığı için `get_full_path` çözülemeyen bir yol döndürüyordu ve
		test kodu değil kendini ölçüyordu (`test_file_manager_seo` senaryo h
		bu deseni zaten kurmuş).
		"""
		veri = _mp3_uret(2.0, baslik="Kardeş")
		ilk = _dosya(f"ses-n1-{_TUZ}.mp3", veri)
		ikinci = _dosya(f"ses-n2-{_TUZ}.mp3", veri)
		self.assertEqual(ikinci.file_url, ilk.file_url, "aynı içerik aynı adrese düşmeli")

		self.assertTrue(audio_meta.apply(ilk.file_url))
		for ad in (ilk.name, ikinci.name):
			self.assertGreater(frappe.db.get_value("File", ad, "th_media_duration"), 1.5, ad)

	def test_o_backfill_islenen_sayisi_doner(self):
		_dosya(f"ses-o-{_TUZ}.mp3", _mp3_uret(1.0))
		self.assertGreaterEqual(audio_meta.backfill_pending(limit=5), 1)
