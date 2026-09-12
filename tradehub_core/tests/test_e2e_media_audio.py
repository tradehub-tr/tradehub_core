"""E2E — ses medyası, uçtan uca ve ÇOK HESAPLI (MOGEM-620 §6 · §15).

`test_media_audio_seo` (saf şema) ve `test_media_audio_meta` (tek hesap,
modül seviyesi) ses özelliğini PARÇA parça sınıyor. Bu dosya onları
BİRLEŞTİRİP gerçek uçlardan ve GERÇEK OTURUMLARDAN geçiriyor: aynı işlem
altı farklı kimlikle denenir ve her birinde beklenen sonuç ayrı ayrı
sabitlenir.

NEDEN ÇOK HESAP
---------------
Ses özelliğinin tek hesapla ölçülen her davranışı doğruydu; ürünün gerçek
riski orada değil: bir satıcının yüklediği sesin metadata'sını BAŞKA bir
satıcı ezebilir mi, mağazası olmayan bir kullanıcı yükleyebilir mi, admin
başkasının dosyasını görebilir mi. Tek hesaplı test bunların hiçbirini
göremez.

Kimlikler (`test_file_multirow_isolation` harness'ı ile aynı desen):

    A-sahip    Marketplace Seller, A kiracısının sahibi
    A-personel Marketplace Seller, AYNI kiracının ikinci kullanıcısı
    B-sahip    Marketplace Seller, B kiracısı — saldırgan
    alıcı      mağazası YOK
    admin      Marketplace Admin
    Guest      oturumsuz

KAPSAM
------
    A. Yükleme kapısı (6 senaryo × kimlik)
    B. Çıkarım doğruluğu ve idempotanslık
    C. SEO alan erişim denetimi (kiracı sızıntısı)
    D. Şema çıktısı — gerçek `fields_for` verisiyle
    E. Yaşam döngüsü (çöp/geri yükleme, kota, backfill)
    F. İçerik-adresli çakışma — iki kiracı AYNI baytı yüklerse

`File.insert()` gerçek commit yapıyor; teardown rollback'i geri alamaz —
her fixture kendi `addCleanup`'ını taşır (harness deseni).

Koşum:
    docker exec istoc-backend bench --site tradehub.localhost \\
        run-tests --module tradehub_core.tests.test_e2e_media_audio
"""

from __future__ import annotations

import base64
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_admin, seller_media
from tradehub_core.media import audio_meta, seo, upload_policy
from tradehub_core.seo.schema_builder import build_audio_object
from tradehub_core.utils.tenant import clear_seller_cache_for_user
from tradehub_core.tests.zenginlestirme_notr import (  # noqa: F401
	setUpModule,
	tearDownModule,
)

_SITE = "https://istoc.example"


# ── ses üreteçleri ───────────────────────────────────────────────────────
#
# Repoya ikili dosya EKLEMİYORUZ: her ses ffmpeg ile koşum anında üretilir.
# `_TUZ` her koşuda farklı olduğu için içerik-adresli URL de farklı olur ve
# önceki koşumdan kalan blob yeni koşumun sonucunu boyamaz.


def _mp3(saniye: float = 1.0, *, baslik: str = "", sanatci: str = "", tuz: str = "") -> bytes:
	"""Gerçek MP3 — sessiz ton, istenirse ID3 etiketli.

	`tuz` yorum etiketine yazılır: aynı süre/etiketle üretilen iki dosyanın
	bayt-birebir AYNI olmasını istemediğimiz senaryolarda ayrıştırır
	(içerik-adresli adlandırma aksi hâlde ikisini tek URL'e indirir).
	"""
	with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
		komut = [
			"ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
			"-t", str(saniye), "-c:a", "libmp3lame", "-b:a", "32k",
		]
		if baslik:
			komut += ["-metadata", f"title={baslik}"]
		if sanatci:
			komut += ["-metadata", f"artist={sanatci}"]
		if tuz:
			komut += ["-metadata", f"comment={tuz}"]
		komut.append(tmp.name)
		subprocess.run(komut, capture_output=True, timeout=60, check=True)
		return Path(tmp.name).read_bytes()


def _mp3_kapakli(saniye: float = 1.0, *, tuz: str = "") -> bytes:
	"""Gömülü kapak görseli TAŞIYAN MP3 — `attached_pic` yolu için."""
	with (
		tempfile.NamedTemporaryFile(suffix=".png", delete=True) as png,
		tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as mp3,
	):
		subprocess.run(
			["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1", png.name],
			capture_output=True, timeout=60, check=True,
		)
		komut = [
			"ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
			"-i", png.name, "-t", str(saniye), "-map", "0:a", "-map", "1:v",
			"-c:a", "libmp3lame", "-b:a", "32k", "-c:v", "copy",
			"-disposition:v:0", "attached_pic",
		]
		if tuz:
			komut += ["-metadata", f"comment={tuz}"]
		komut.append(mp3.name)
		subprocess.run(komut, capture_output=True, timeout=60, check=True)
		return Path(mp3.name).read_bytes()


def _png(tuz: str = "") -> bytes:
	with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
		subprocess.run(
			["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=8x8:d=1", "-frames:v", "1", tmp.name],
			capture_output=True, timeout=60, check=True,
		)
		return Path(tmp.name).read_bytes() + tuz.encode()


@contextmanager
def gercek_yetki():
	"""Rol kapılarını GERÇEKTEN çalıştır.

	`frappe.only_for` testte hiçbir şey yapmıyor — kaynağın ilk satırı:

	    if local.flags.in_test or local.session.user == "Administrator":
	        return

	Yani `FrappeTestCase` altında yazılan her "bu rol reddedilmeli" iddiası
	KENDİLİĞİNDEN geçer ve hiçbir şey ölçmez. Bu dosyanın ilk koşumunda tam
	olarak bu oldu: üç yetki testi "açık bulundu" diye yeşil-yanlış verdi;
	`frappe/__init__.py` okunmasa gerçek olmayan bir güvenlik açığı rapor
	edilecekti.

	Bayrak yalnız ölçülen çağrının etrafında ve DAR kapsamda indiriliyor:
	`in_test` başka davranışları da (e-posta, arka plan işi) etkiliyor.
	"""
	onceki = frappe.flags.in_test
	frappe.flags.in_test = False
	try:
		yield
	finally:
		frappe.flags.in_test = onceki


class MediaAudioE2E(FrappeTestCase):
	"""Ortak kurulum — altı kimlik, iki kiracı."""

	# -- fixture yardımcıları -------------------------------------------

	def _drop(self, doctype: str, name: str) -> None:
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def _user(self, tag: str, roles: tuple[str, ...] = ()) -> str:
		email = f"ses-{tag}-{self.suffix}@test.local"
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": tag,
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("User", doc.name))
		self.addCleanup(lambda: clear_seller_cache_for_user(doc.name))
		return doc.name

	def _seller(self, tag: str, user: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_code": f"SES{tag}{self.suffix}",
				"seller_name": f"Ses {tag} {self.suffix}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Admin Seller Profile", doc.name))
		return doc.name

	def _dosya(self, ad: str, veri: bytes, *, private: int = 0):
		"""Doğrudan `File` — uç kapısını atlayıp çıkarım/şema yolunu sınamak için."""
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": ad,
					"is_private": private,
					"content": veri,
					"decode": False,
				}
			)
			doc.flags.ignore_permissions = True
			doc.insert()
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("File", doc.name))
		return doc

	def _yukle(self, ad: str, veri: bytes) -> dict:
		"""Gerçek satıcı yükleme ucundan geçir (oturum kimin ise onun adına)."""
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			sonuc = seller_media.upload_media(file_name=ad, content=base64.b64encode(veri).decode())
		frappe.db.commit()
		url = (sonuc or {}).get("file_url")
		if url:
			for ad_ in frappe.get_all("File", filters={"file_url": url}, pluck="name"):
				self.addCleanup(lambda n=ad_: self._drop("File", n))
		return sonuc or {}

	# -- kurulum ---------------------------------------------------------

	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)

		self.a_owner = self._user("aowner", ("Marketplace Seller", "Verified Seller"))
		self.a_staff = self._user("astaff", ("Marketplace Seller",))
		self.tenant_a = self._seller("A", self.a_owner)
		frappe.db.set_value("User", self.a_staff, "tradehub_tenant", self.tenant_a)
		frappe.db.commit()
		clear_seller_cache_for_user(self.a_staff)

		self.b_owner = self._user("bowner", ("Marketplace Seller",))
		self.tenant_b = self._seller("B", self.b_owner)

		self.buyer = self._user("buyer", ("Buyer",))
		self.admin = self._user("admin", ("Marketplace Admin",))


# ══════════════════════════════════════════════════════════════════════
# A. Yükleme kapısı
# ══════════════════════════════════════════════════════════════════════


class TestAYuklemeKapisi(MediaAudioE2E):
	def test_a1_ses_politikada_tanimli(self):
		"""`.mp3` yüklenebilir bir tür olarak haritada OLMALI.

		Bu satır olmadan `naming._hashed_name` beyaz listeyi bulamıyor ve
		hiçbir ses dosyası diske yazılamıyordu (`.pptx` ile aynı kusur).
		"""
		for uzanti in upload_policy.AUDIO_EXTENSIONS:
			self.assertEqual(
				upload_policy.EXTENSIONS.get(uzanti), upload_policy.KIND_AUDIO, uzanti
			)

	def test_a2_ses_medya_ucunun_dar_kapisindan_gecer(self):
		"""Medya uçları `MEDIA_KINDS` + `MEDIA_EXTRA_EXTENSIONS` kabul ediyor.

		Ses bu kapıdan geçmezse `upload_media` onu reddeder: şema, çıkarım ve
		denetim yazılmış ama satıcı dosyayı YÜKLEYEMİYOR olurdu.
		"""
		self.assertIn(".mp3", seller_media.UPLOAD_EXTENSIONS)

	def test_a3_satici_ses_yukleyebilir(self):
		frappe.set_user(self.a_owner)
		sonuc = self._yukle(f"a3-{self.suffix}.mp3", _mp3(1.0, tuz=f"a3{self.suffix}"))
		self.assertTrue(sonuc.get("file_url", "").endswith(".mp3"), sonuc)

	def test_a4_ayni_kiracinin_ikinci_kullanicisi_da_yukleyebilir(self):
		frappe.set_user(self.a_staff)
		sonuc = self._yukle(f"a4-{self.suffix}.mp3", _mp3(1.0, tuz=f"a4{self.suffix}"))
		self.assertTrue(sonuc.get("file_url"), sonuc)

	def test_a5_magazasiz_kullanici_yukleyemez(self):
		"""`_store()` oturumdan mağaza çözemezse uç reddetmeli."""
		frappe.set_user(self.buyer)
		with self.assertRaises(Exception):
			self._yukle(f"a5-{self.suffix}.mp3", _mp3(0.5, tuz=f"a5{self.suffix}"))

	def test_a6_izin_verilmeyen_ses_uzantisi_reddedilir(self):
		"""`.mid` ses ama izin listesinde YOK — kapı uzantıya bakar.

		`check()` reddi `ok=False` DÖNDÜRMEZ, `reddet()` ile İSTİSNA ATAR.
		İlk yazımda dönüş değerine bakmıştım; kodu okuyunca sözleşmenin bu
		olduğu görüldü.
		"""
		with self.assertRaises(Exception):
			upload_policy.check("melodi.mid", content=b"MThd", media_endpoint=True)

	def test_a7_iyi_huylu_uyusmazlik_uyari_uretir_ret_degil(self):
		"""`.mp3` adıyla gelen PNG REDDEDİLMEZ, UYARI olarak kaydedilir.

		İlk yazımda "reddedilmeli" diye ölçmüştüm; kodu okuyunca sözleşmenin
		bilinçli olarak farklı olduğu görüldü (`upload_policy.check`, T-017):
		TEHLİKELİ uyuşmazlığı `_derin_denetim` zaten yukarıda reddediyor;
		buraya yalnız hareketsiz kap uyuşmazlığı düşüyor ve ölçümle
		gerekçelendirilmiş (4.584 public dosyada 1 adet `.mp4` içinde webm —
		tarayıcı MediaRecorder çıktısında yaygın). Ret yerine uyarı.

		Test bu sözleşmeyi SABİTLİYOR: biri sessizce rette çevirirse meşru
		yüklemeler kırılır ve burada görülür.
		"""
		karar = upload_policy.check(
			f"sahte-{self.suffix}.mp3", content=_png(self.suffix), media_endpoint=True
		)
		self.assertTrue(
			any("uzanti=.mp3" in u for u in karar.warnings), karar.warnings
		)

	def test_a7b_tehlikeli_icerik_ses_adiyla_da_reddedilir(self):
		"""Asıl güvenlik iddiası: `.mp3` adı tehlikeli içeriği aklamaz.

		`a7`'nin uyarı sözleşmesi bir boşluk DEĞİL — çünkü gerçek saldırı
		(kap içinde çalıştırılabilir işaretleme) daha yukarıdaki kapıdan
		dönüyor. Bu test o kapının ses uzantısında da kapalı olduğunu
		kanıtlıyor; ikisi birlikte okunmalı.
		"""
		zararli = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>'
		with self.assertRaises(Exception):
			upload_policy.check(
				f"zararli-{self.suffix}.mp3", content=zararli, media_endpoint=True
			)

	def test_a9_gecerli_ses_kapidan_gecer(self):
		"""Negatifin karşılığı: doğru ses doğru türle geçmeli."""
		karar = upload_policy.check(
			f"a9-{self.suffix}.mp3", content=_mp3(0.5, tuz=self.suffix), media_endpoint=True
		)
		self.assertEqual(karar.kind, upload_policy.KIND_AUDIO)

	def test_a8_ses_tavani_gorsel_tavanindan_yuksek(self):
		"""Yarım saatlik bir kayıt 50 MB'ı aşıyor; doküman tavanı yetmezdi."""
		self.assertGreater(
			upload_policy.MAX_BYTES[upload_policy.KIND_AUDIO],
			upload_policy.MAX_BYTES[upload_policy.KIND_DOCUMENT],
		)


# ══════════════════════════════════════════════════════════════════════
# B. Çıkarım
# ══════════════════════════════════════════════════════════════════════


class TestBCikarim(MediaAudioE2E):
	def test_b1_etiket_ve_sure_yazilir(self):
		frappe.set_user(self.a_owner)
		doc = self._dosya(
			f"b1-{self.suffix}.mp3", _mp3(2.0, baslik="B1 Kayıt", sanatci="B1 Sanatçı")
		)
		frappe.set_user("Administrator")
		self.assertTrue(audio_meta.apply(doc.file_url))
		alanlar = seo.fields_for(doc.file_url)
		self.assertEqual(alanlar["title"], "B1 Kayıt")
		self.assertEqual(alanlar["artist"], "B1 Sanatçı")
		self.assertGreater(alanlar["duration"], 1.5)

	def test_b2_gomulu_kapak_cikarilir_ve_bagalanir(self):
		doc = self._dosya(f"b2-{self.suffix}.mp3", _mp3_kapakli(1.0, tuz=f"b2{self.suffix}"))
		self.assertTrue(audio_meta.apply(doc.file_url))
		alanlar = seo.fields_for(doc.file_url)
		self.assertTrue(alanlar["cover_url"], "gömülü kapak bağlanmalı")
		self.assertEqual(alanlar["cover_url"], alanlar["poster_url"])
		for ad in frappe.get_all("File", filters={"file_url": alanlar["cover_url"]}, pluck="name"):
			self.addCleanup(lambda n=ad: self._drop("File", n))

	def test_b3_ikinci_apply_kapagi_cogaltmaz(self):
		"""Backfill her turda aynı kapağı yeniden yazsaydı depo şişerdi."""
		doc = self._dosya(f"b3-{self.suffix}.mp3", _mp3_kapakli(1.0, tuz=f"b3{self.suffix}"))
		audio_meta.apply(doc.file_url)
		ilk = seo.fields_for(doc.file_url)["cover_url"]
		audio_meta.apply(doc.file_url)
		self.assertEqual(seo.fields_for(doc.file_url)["cover_url"], ilk)
		self.assertEqual(len(frappe.get_all("File", filters={"file_url": ilk})), 1)
		for ad in frappe.get_all("File", filters={"file_url": ilk}, pluck="name"):
			self.addCleanup(lambda n=ad: self._drop("File", n))

	def test_b4_elle_girilen_baslik_ezilmez(self):
		doc = self._dosya(f"b4-{self.suffix}.mp3", _mp3(1.0, baslik="Makine", sanatci="Makine"))
		frappe.db.set_value("File", doc.name, "th_media_title", "Elle Girilen")
		frappe.db.commit()
		audio_meta.apply(doc.file_url)
		self.assertEqual(seo.fields_for(doc.file_url)["title"], "Elle Girilen")

	def test_b5_bozuk_dosya_anti_aclik_damgasi_alir(self):
		doc = self._dosya(f"b5-{self.suffix}.mp3", b"bu gecerli bir mp3 degil " + self.suffix.encode())
		self.assertFalse(audio_meta.apply(doc.file_url))
		self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_duration"), -1)

	def test_b6_damga_disari_sizmaz(self):
		doc = self._dosya(f"b6-{self.suffix}.mp3", b"bozuk " + self.suffix.encode())
		audio_meta.apply(doc.file_url)
		self.assertEqual(seo.fields_for(doc.file_url)["duration"], 0)


# ══════════════════════════════════════════════════════════════════════
# C. SEO alan erişim denetimi
# ══════════════════════════════════════════════════════════════════════


class TestCErisimDenetimi(MediaAudioE2E):
	def setUp(self):
		super().setUp()
		frappe.set_user(self.a_owner)
		self.dosya_a = self._dosya(f"c-{self.suffix}.mp3", _mp3(1.0, tuz=f"c{self.suffix}"))
		frappe.set_user("Administrator")

	def test_c1_admin_seo_alani_yazabilir(self):
		frappe.set_user(self.admin)
		media_admin.set_media_seo(self.dosya_a.file_url, {"alt": "Admin yazdı"})
		frappe.db.commit()
		self.assertEqual(seo.fields_for(self.dosya_a.file_url)["alt"], "Admin yazdı")

	def test_c2_artist_sistem_alani_ucdan_yazilamaz(self):
		"""`th_media_artist` beyaz listede DEĞİL — yalnız üretim hattı yazar."""
		frappe.set_user(self.admin)
		sonuc = media_admin.set_media_seo(self.dosya_a.file_url, {"artist": "Korsan"})
		frappe.db.commit()
		self.assertEqual(sonuc["records"], 0)
		self.assertFalse(frappe.db.get_value("File", self.dosya_a.name, "th_media_artist"))

	def test_c3_duration_ucdan_yazilamaz(self):
		frappe.set_user(self.admin)
		sonuc = media_admin.set_media_seo(self.dosya_a.file_url, {"duration": 9999})
		frappe.db.commit()
		self.assertEqual(sonuc["records"], 0)

	def test_c4_magazasiz_kullanici_seo_yazamaz(self):
		frappe.set_user(self.buyer)
		with gercek_yetki(), self.assertRaises(frappe.PermissionError):
			media_admin.set_media_seo(self.dosya_a.file_url, {"alt": "Alıcı yazdı"})

	def test_c5_rakip_satici_seo_yazamaz(self):
		"""B kiracısı A'nın dosyasının alt metnini değiştirememeli.

		Uç `Marketplace Admin`/`System Manager` istiyor; satıcı rolü oraya
		hiç giremez. İKİ ŞEY birden ölçülüyor: çağrı reddedildi Mİ ve —daha
		önemlisi— değer DEĞİŞMEDİ mi. Yalnız istisnaya bakmak, reddin
		yazımdan SONRA gelmesi hâlinde sızıntıyı kaçırırdı.
		"""
		frappe.set_user(self.b_owner)
		with gercek_yetki(), self.assertRaises(frappe.PermissionError):
			media_admin.set_media_seo(self.dosya_a.file_url, {"alt": "B ezdi"})
		frappe.set_user("Administrator")
		self.assertNotEqual(seo.fields_for(self.dosya_a.file_url)["alt"], "B ezdi")

	def test_c6_guest_seo_okuyamaz(self):
		frappe.set_user("Guest")
		with gercek_yetki(), self.assertRaises(frappe.PermissionError):
			media_admin.get_media_seo(self.dosya_a.file_url)

	def test_c7_yetki_kapisi_testte_gercekten_kosuyor(self):
		"""NÖBETÇİ TEST — `gercek_yetki()` bozulursa C grubu sessizce boşalır.

		Bu dosyanın en kritik testi: yukarıdaki üç iddia `only_for`un testte
		devre dışı olmasından ötürü yeşil-yanlış verebiliyor. Bu test bayrağın
		gerçekten indiğini ve kapının gerçekten reddettiğini ayrıca kanıtlar;
		biri `gercek_yetki`yi kaldırırsa BU test kırılır ve neden kırıldığı
		belli olur.
		"""
		frappe.set_user(self.buyer)
		# Bayrak açıkken (varsayılan test davranışı) kapı hiç çalışmaz:
		media_admin.get_media_seo(self.dosya_a.file_url)
		# Bayrak indirilince aynı çağrı reddedilir:
		with gercek_yetki(), self.assertRaises(frappe.PermissionError):
			media_admin.get_media_seo(self.dosya_a.file_url)


# ══════════════════════════════════════════════════════════════════════
# D. Şema çıktısı — gerçek veriyle
# ══════════════════════════════════════════════════════════════════════


class TestDSemaCiktisi(MediaAudioE2E):
	def test_d1_gercek_alanlardan_gecerli_audioobject(self):
		"""Şema saf fonksiyonu, `fields_for` çıktısıyla BİRLİKTE çalışmalı.

		Birim testi ikisini ayrı ayrı doğruluyor; burada zincirin tamamı
		koşuyor — anahtar adı uyuşmazlığı ancak burada yakalanır.
		"""
		doc = self._dosya(
			f"d1-{self.suffix}.mp3", _mp3(3.0, baslik="D1 Bölüm", sanatci="D1 Sanatçı")
		)
		audio_meta.apply(doc.file_url)
		alanlar = seo.fields_for(doc.file_url)
		obj = build_audio_object(alanlar, _SITE, content_url=doc.file_url)

		self.assertEqual(obj["@type"], "AudioObject")
		self.assertEqual(obj["name"], "D1 Bölüm")
		self.assertEqual(obj["author"], {"@type": "Person", "name": "D1 Sanatçı"})
		self.assertTrue(obj["duration"].startswith("PT"))
		self.assertTrue(obj["contentUrl"].startswith(_SITE))
		self.assertEqual(obj["encodingFormat"], "audio/mpeg")

	def test_d2_kapak_zincirden_gecer(self):
		doc = self._dosya(f"d2-{self.suffix}.mp3", _mp3_kapakli(1.0, tuz=f"d2{self.suffix}"))
		audio_meta.apply(doc.file_url)
		alanlar = seo.fields_for(doc.file_url)
		for ad in frappe.get_all("File", filters={"file_url": alanlar["cover_url"]}, pluck="name"):
			self.addCleanup(lambda n=ad: self._drop("File", n))
		obj = build_audio_object(alanlar, _SITE, content_url=doc.file_url)
		self.assertTrue(obj["thumbnailUrl"].startswith(_SITE))

	def test_d3_bos_alanlar_semayi_kirletmez(self):
		"""Hiç işlenmemiş dosya: yalnız zorunlu anahtarlar basılmalı."""
		doc = self._dosya(f"d3-{self.suffix}.mp3", _mp3(1.0, tuz=f"d3{self.suffix}"))
		obj = build_audio_object(seo.fields_for(doc.file_url), _SITE, content_url=doc.file_url)
		for anahtar in ("author", "thumbnailUrl", "duration", "description"):
			self.assertNotIn(anahtar, obj, anahtar)

	def test_d4_lisans_alanlari_uctan_yazilinca_semaya_gecer(self):
		doc = self._dosya(f"d4-{self.suffix}.mp3", _mp3(1.0, tuz=f"d4{self.suffix}"))
		frappe.set_user(self.admin)
		media_admin.set_media_seo(
			doc.file_url,
			{"creator": "iStoc A.Ş.", "credit_text": "Ses: iStoc", "license_url": "/lisans"},
		)
		frappe.db.commit()
		frappe.set_user("Administrator")
		obj = build_audio_object(seo.fields_for(doc.file_url), _SITE, content_url=doc.file_url)
		self.assertEqual(obj["creator"], {"@type": "Organization", "name": "iStoc A.Ş."})
		self.assertEqual(obj["creditText"], "Ses: iStoc")
		self.assertEqual(obj["license"], f"{_SITE}/lisans")


# ══════════════════════════════════════════════════════════════════════
# E. Yaşam döngüsü
# ══════════════════════════════════════════════════════════════════════


class TestEYasamDongusu(MediaAudioE2E):
	def test_e1_backfill_islenmemisi_secer(self):
		doc = self._dosya(f"e1-{self.suffix}.mp3", _mp3(1.5, tuz=f"e1{self.suffix}"))
		self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_duration") or 0, 0)
		self.assertGreaterEqual(audio_meta.backfill_pending(limit=20), 1)
		self.assertGreater(frappe.db.get_value("File", doc.name, "th_media_duration"), 1.0)

	def test_e2_backfill_islenmisi_tekrar_secmez(self):
		"""İdempotanslık: aynı dosya iki turda iki kez işlenmemeli."""
		doc = self._dosya(f"e2-{self.suffix}.mp3", _mp3(1.5, tuz=f"e2{self.suffix}"))
		audio_meta.apply(doc.file_url)
		once = frappe.db.get_value("File", doc.name, "th_media_duration")
		audio_meta.backfill_pending(limit=20)
		self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_duration"), once)

	def test_e3_bozuk_dosya_backfilli_kilitlemez(self):
		"""Anti-açlık: -1 damgalı dosya bir daha aday olmamalı."""
		doc = self._dosya(f"e3-{self.suffix}.mp3", b"bozuk e3 " + self.suffix.encode())
		audio_meta.apply(doc.file_url)
		adaylar = frappe.get_all(
			"File", filters={"th_media_duration": 0, "file_url": doc.file_url}, pluck="name"
		)
		self.assertNotIn(doc.name, adaylar)

	def test_e4_limit_uygulanir(self):
		for i in range(3):
			self._dosya(f"e4-{i}-{self.suffix}.mp3", _mp3(1.0, tuz=f"e4{i}{self.suffix}"))
		self.assertLessEqual(audio_meta.backfill_pending(limit=2), 2)

	def test_e5_ozel_dosyada_da_calisir(self):
		"""`_yerel_yol` private/public ayrımını `get_full_path` üzerinden çözer."""
		doc = self._dosya(f"e5-{self.suffix}.mp3", _mp3(1.5, tuz=f"e5{self.suffix}"), private=1)
		self.assertTrue(audio_meta.apply(doc.file_url))
		self.assertGreater(frappe.db.get_value("File", doc.name, "th_media_duration"), 1.0)


# ══════════════════════════════════════════════════════════════════════
# F. İçerik-adresli çakışma — iki kiracı aynı sesi yüklerse
# ══════════════════════════════════════════════════════════════════════


class TestFIcerikCakismasi(MediaAudioE2E):
	def test_f1_ayni_bayt_tek_adrese_duser(self):
		veri = _mp3(1.0, baslik="Ortak", tuz=f"f1{self.suffix}")
		frappe.set_user(self.a_owner)
		a = self._yukle(f"f1-a-{self.suffix}.mp3", veri)
		frappe.set_user(self.b_owner)
		b = self._yukle(f"f1-b-{self.suffix}.mp3", veri)
		self.assertEqual(a["file_url"], b["file_url"], "içerik-adresli: aynı bayt aynı adres")

	def test_f2_cakismada_her_kiracinin_kendi_satiri_var(self):
		"""Tek URL, iki `File` satırı — kiracı izolasyonu satır seviyesinde."""
		veri = _mp3(1.0, tuz=f"f2{self.suffix}")
		frappe.set_user(self.a_owner)
		a = self._yukle(f"f2-a-{self.suffix}.mp3", veri)
		frappe.set_user(self.b_owner)
		self._yukle(f"f2-b-{self.suffix}.mp3", veri)
		frappe.set_user("Administrator")
		satirlar = frappe.get_all("File", filters={"file_url": a["file_url"]}, pluck="owner")
		self.assertIn(self.a_owner, satirlar)
		self.assertIn(self.b_owner, satirlar)

	def test_f3_cikarim_cakisan_satirlarin_hepsine_yazar(self):
		veri = _mp3(2.0, baslik="Çakışma", tuz=f"f3{self.suffix}")
		frappe.set_user(self.a_owner)
		a = self._yukle(f"f3-a-{self.suffix}.mp3", veri)
		frappe.set_user(self.b_owner)
		self._yukle(f"f3-b-{self.suffix}.mp3", veri)
		frappe.set_user("Administrator")
		self.assertTrue(audio_meta.apply(a["file_url"]))
		for ad in frappe.get_all("File", filters={"file_url": a["file_url"]}, pluck="name"):
			self.assertGreater(frappe.db.get_value("File", ad, "th_media_duration"), 1.5, ad)


# ══════════════════════════════════════════════════════════════════════
# G. Erişim seviyesi — özel ses gerçekten özel mi
# ══════════════════════════════════════════════════════════════════════


class TestGErisimSeviyesi(MediaAudioE2E):
	def test_g1_public_ses_indexlenebilir(self):
		from tradehub_core.media import seo_index

		doc = self._dosya(f"g1-{self.suffix}.mp3", _mp3(1.0, tuz=f"g1{self.suffix}"))
		karar = seo_index.decide(doc.file_url, check_usage=False)
		self.assertTrue(karar["indexable"], karar)

	def test_g2_ozel_ses_indexlenemez(self):
		"""Özel dosya arama motoruna ASLA verilmemeli — robots.txt'e güvenmeden."""
		from tradehub_core.media import seo_index

		doc = self._dosya(f"g2-{self.suffix}.mp3", _mp3(1.0, tuz=f"g2{self.suffix}"), private=1)
		karar = seo_index.decide(doc.file_url, check_usage=False)
		self.assertFalse(karar["indexable"], karar)

	def test_g3_public_ozele_cevrilince_index_kararı_doner(self):
		"""Seviye değişimi indexlenebilirliği ANINDA etkilemeli."""
		from tradehub_core.media import seo_index

		doc = self._dosya(f"g3-{self.suffix}.mp3", _mp3(1.0, tuz=f"g3{self.suffix}"))
		self.assertTrue(seo_index.decide(doc.file_url, check_usage=False)["indexable"])

		frappe.set_user(self.admin)
		sonuc = media_admin.set_access_level(doc.file_url, make_private=1)
		frappe.db.commit()
		frappe.set_user("Administrator")

		yeni_url = sonuc.get("file_url") or doc.file_url
		for ad in frappe.get_all("File", filters={"file_url": yeni_url}, pluck="name"):
			self.addCleanup(lambda n=ad: self._drop("File", n))
		self.assertFalse(seo_index.decide(yeni_url, check_usage=False)["indexable"])

	def test_g4_ozele_tasinan_seste_cikarim_calismaya_devam_eder(self):
		"""Taşıma sonrası `get_full_path` private ağacı çözebilmeli.

		Yolu elle kuran ilk sürüm burada da kırılırdı; bu test onun
		regresyonunu kalıcı olarak kapatıyor.
		"""
		doc = self._dosya(f"g4-{self.suffix}.mp3", _mp3(2.0, tuz=f"g4{self.suffix}"))
		frappe.set_user(self.admin)
		sonuc = media_admin.set_access_level(doc.file_url, make_private=1)
		frappe.db.commit()
		frappe.set_user("Administrator")

		yeni_url = sonuc.get("file_url") or doc.file_url
		for ad in frappe.get_all("File", filters={"file_url": yeni_url}, pluck="name"):
			self.addCleanup(lambda n=ad: self._drop("File", n))
		self.assertTrue(audio_meta.apply(yeni_url), "özel dosyada çıkarım çalışmalı")
		self.assertGreater(seo.fields_for(yeni_url)["duration"], 1.5)


# ══════════════════════════════════════════════════════════════════════
# H. Denetim motoru sesi görüyor mu
# ══════════════════════════════════════════════════════════════════════


class TestHDenetim(MediaAudioE2E):
	def test_h1_alt_metni_olmayan_ses_bulgu_uretir(self):
		from tradehub_core.media import seo_audit

		doc = self._dosya(f"h1-{self.suffix}.mp3", _mp3(1.0, tuz=f"h1{self.suffix}"))
		bulgular = seo_audit.audit_file(doc.file_url)["findings"]
		kodlar = {b["code"] for b in bulgular}
		self.assertIn("missing_alt", kodlar, kodlar)

	def test_h2_alt_yazilinca_bulgu_kaybolur(self):
		from tradehub_core.media import seo_audit

		doc = self._dosya(f"h2-{self.suffix}.mp3", _mp3(1.0, tuz=f"h2{self.suffix}"))
		frappe.set_user(self.admin)
		media_admin.set_media_seo(doc.file_url, {"alt": "Podcast bölüm kaydı"})
		frappe.db.commit()
		frappe.set_user("Administrator")
		kodlar = {b["code"] for b in seo_audit.audit_file(doc.file_url)["findings"]}
		self.assertNotIn("missing_alt", kodlar, kodlar)

	def test_h3_skor_alt_boyutlari_donuyor(self):
		from tradehub_core.media import seo_audit

		doc = self._dosya(f"h3-{self.suffix}.mp3", _mp3(1.0, tuz=f"h3{self.suffix}"))
		puan = seo_audit.score_from(seo_audit.audit_file(doc.file_url)["findings"], seo.fields_for(doc.file_url))
		for boyut in seo_audit.DIMENSIONS:
			self.assertIn(boyut, puan, boyut)
		self.assertIn("overall", puan)


# ══════════════════════════════════════════════════════════════════════
# I. Eş zamanlılık ve tekrar
# ══════════════════════════════════════════════════════════════════════


class TestIEsZamanlilik(MediaAudioE2E):
	def test_i1_ard_arda_uc_apply_tek_sonuc_uretir(self):
		"""Kuyruk aynı işi iki kez alabilir; ikinci koşum bozmamalı."""
		doc = self._dosya(f"i1-{self.suffix}.mp3", _mp3_kapakli(1.0, tuz=f"i1{self.suffix}"))
		for _ in range(3):
			audio_meta.apply(doc.file_url)
		alanlar = seo.fields_for(doc.file_url)
		kapaklar = frappe.get_all("File", filters={"file_url": alanlar["cover_url"]}, pluck="name")
		for ad in kapaklar:
			self.addCleanup(lambda n=ad: self._drop("File", n))
		self.assertEqual(len(kapaklar), 1, "kapak çoğaltılmamalı")

	def test_i2_cikarim_bozuk_dosyada_kuyrugu_dusurmez(self):
		"""Sözleşme: hiçbir hata çağıranı patlatmaz — kuyruk işi ölmez."""
		doc = self._dosya(f"i2-{self.suffix}.mp3", b"bozuk i2 " + self.suffix.encode())
		try:
			sonuc = audio_meta.apply(doc.file_url)
		except Exception as e:  # noqa: BLE001 — testin ölçtüğü şey tam olarak bu
			self.fail(f"apply istisna atmamalı: {e}")
		self.assertFalse(sonuc)

	def test_i3_olmayan_adres_sessiz_false(self):
		self.assertFalse(audio_meta.apply(f"/files/yok-{self.suffix}.mp3"))

	def test_i4_bos_adres_sessiz_false(self):
		self.assertFalse(audio_meta.apply(""))
		self.assertEqual(audio_meta.extract("")["reason"], "dosya bulunamadı")


# ══════════════════════════════════════════════════════════════════════
# J. Envanter tür filtresi — panel sesi görebiliyor mu
# ══════════════════════════════════════════════════════════════════════


class TestJEnvanterTuru(MediaAudioE2E):
	def test_j1_audio_turu_haritada_var(self):
		"""`upload_policy` sesi tanıyorsa envanter de tanımalı.

		İkisi ayrışırsa ses yüklenebilir ama panelde süzülemez olur — kusur
		tam olarak buydu (6 Eyl denetimi).
		"""
		from tradehub_core.media import inventory

		self.assertIn("audio", inventory.KIND_EXTENSIONS)

	def test_j2_uzanti_listesi_tek_kaynaktan_turuyor(self):
		"""İki liste tutmak, biri değişince sessizce ayrışan iki kural demek."""
		from tradehub_core.media import inventory

		self.assertEqual(
			inventory.AUDIO_EXTENSIONS,
			frozenset(e.lstrip(".") for e in upload_policy.AUDIO_EXTENSIONS),
		)

	def test_j3_ses_turu_ile_suzulebiliyor(self):
		"""Ses süzgeci sesi getirir AMA görseli getirmez.

		İkinci iddia şart: ilk yazımda yalnız "sesi getiriyor mu" diye
		sormuştum ve test YEŞİL-YANLIŞ geçti — `_kind_condition`ın yakalayıcı
		dalı "video/belge olmayan her şey" dediği için ses oraya düşüyor ve
		doğru sonucu yanlış sebeple veriyordu. Görselin dışarıda kaldığını da
		ölçmek dalı ayırmayı zorunlu kılıyor.
		"""
		from tradehub_core.media import inventory

		ses = self._dosya(f"j3-{self.suffix}.mp3", _mp3(1.0, tuz=f"j3{self.suffix}"))
		gorsel = self._dosya(f"j3-{self.suffix}.png", _png(f"j3{self.suffix}"))
		sonuc = inventory.list_files(kinds=["audio"], page_size=200, name_search=f"j3-{self.suffix}")
		adresler = {s.get("file_url") for s in sonuc.get("rows", sonuc.get("items", []))}
		self.assertIn(ses.file_url, adresler, sonuc)
		self.assertNotIn(gorsel.file_url, adresler, sonuc)

	def test_j4_gorsel_suzgeci_sesi_getirmez(self):
		"""Karşı yön: ses artık 'sınıfsız' değil, görsel de sayılmıyor."""
		from tradehub_core.media import inventory

		doc = self._dosya(f"j4-{self.suffix}.mp3", _mp3(1.0, tuz=f"j4{self.suffix}"))
		sonuc = inventory.list_files(kinds=["image"], page_size=200, name_search=f"j4-{self.suffix}")
		adresler = {s.get("file_url") for s in sonuc.get("rows", sonuc.get("items", []))}
		self.assertNotIn(doc.file_url, adresler, sonuc)

	def test_j5_mime_ailesi_ile_suzulebiliyor(self):
		from tradehub_core.media import inventory

		doc = self._dosya(f"j5-{self.suffix}.mp3", _mp3(1.0, tuz=f"j5{self.suffix}"))
		sonuc = inventory.list_files(
			mime_types=["audio/*"], page_size=200, name_search=f"j5-{self.suffix}"
		)
		adresler = {s.get("file_url") for s in sonuc.get("rows", sonuc.get("items", []))}
		self.assertIn(doc.file_url, adresler, sonuc)
