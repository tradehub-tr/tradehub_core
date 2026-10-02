"""Ürün görseli kare — dosya/iş/geri alma entegrasyonu (spec 2026-09-29 §4.1, §6)."""

import hashlib
import io
import os
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tradehub_core.media import archive, av, kare, retro_rename, seo_url
from tradehub_core.media.seo_renderer import SeoImageRenderer

# Tarama kancası bu modülde nötrleniyor: `hold_until_clean` açıkken dosya
# insert anında public ağaçtan çıkarılıyor ve diskten okuyan testler
# `FileNotFoundError` alıyor. Gerekçe `tests/av_notr.py` başlığında; aynı
# desen `test_media_retro_rename.py`'de kullanılıyor.
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401


def _jpeg(w, h, color=(180, 40, 40), comment: bytes | None = None):
	buf = io.BytesIO()
	kw = {"comment": comment} if comment else {}
	Image.new("RGB", (w, h), color).save(buf, "JPEG", quality=90, **kw)
	return buf.getvalue()


def _webp(w, h, color=(180, 40, 40)):
	buf = io.BytesIO()
	Image.new("RGB", (w, h), color).save(buf, "WEBP", quality=85)
	return buf.getvalue()


class _Base(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.sfx = frappe.generate_hash(length=8)
		self.job = f"kare-test-{self.sfx}"
		self.addCleanup(self._temizle)

	def _dosya(self, w, h, fmt="JPEG"):
		"""İçerik-adresli public File (normal yükleme yolu, naming kancası).

		Renk yalnız `(w, h)`'den DEĞİL, `self.sfx`'ten de türetilir: brief'in ilk
		hâli rengi `w % 255` ile sabitliyordu, yani aynı `(w, h)` çifti farklı
		test metodlarında (ve farklı koşularda) AYNI JPEG baytını — dolayısıyla
		aynı içerik-adresli URL'i — üretiyordu. Sonuç: bir testin arşivlediği
		orijinal, aynı boyuttaki başka bir testin (veya önceki bir koşunun)
		dosyasıyla çakışıyor ve `archive.exists()` yanlışlıkla `True` dönüyordu
		(ölçüldü: `test_cevirir_referans_redirect_arsiv` "archived" diye atlandı).
		Test başına benzersiz `sfx` rengi karıştırınca çakışma ortadan kalkar.
		"""
		# Final review (flaky testler): tek kanallı 255 renk yetmiyordu — sızan bir
		# arşiv kaydı başka testin aynı baytlı dosyasına çarpıyordu. JPEG yorumuna
		# test kimliği + sfx yazılır: içerik (dolayısıyla içerik-adresli URL) her
		# test ve her koşu için benzersiz.
		ozgun = f"{self.id()}-{self.sfx}-{w}x{h}".encode()
		# Webp hedef yalnız piksellerden türer (yorum düşer): renk de 3 kanal
		# boyunca benzersiz olmalı, aksi hâlde iki testin hedef URL'i çakışır.
		renk = tuple(hashlib.sha1(ozgun).digest()[:3])
		webp = fmt == "WEBP"
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"kare-{self.sfx}-{w}x{h}.{'webp' if webp else 'jpg'}",
				"is_private": 0,
				"content": _webp(w, h, renk) if webp else _jpeg(w, h, renk, comment=ozgun),
			}
		).insert(ignore_permissions=True)
		self.urls = [*getattr(self, "urls", []), doc.file_url]
		return doc.file_url

	def _in_test_kapali(self):
		"""`frappe.flags.in_test`'i geçici kapat — kancaların gerçek dalını sına.

		Fix round 1'de `TestListingHook`e özel eklenmişti; fix round 2'nin yeni
		testleri (`av.release_hold` tetiklemesi) de aynı ihtiyaca sahip olunca
		`_Base`'e taşındı — tek yer, iki sınıf.
		"""
		frappe.flags.in_test = False
		self.addCleanup(lambda: setattr(frappe.flags, "in_test", True))

	def _ilan(self, primary, gallery=()):
		"""Asgari Listing — `test_media_retro_rename.py::_make_listing` deseniyle aynı.

		Brief'in ilk hâli `seller_profile`/`category` alanlarını `Admin Seller
		Profile` ve `Product Category`'den dolduruyordu; ama `Listing.category`
		alanının `options`'ı `Seller Category` (Product Category değil) ve her
		ikisi de zaten zorunlu değil (`reqd` yok) — kanıtlanmış test yardımcısı
		bu alanları hiç set etmiyor. Gerçek davranışa uymayan kısmı en aza
		indirgeyerek düzeltildi.
		"""
		doc = frappe.get_doc(
			{
				"doctype": "Listing",
				"listing_code": f"KARE-{frappe.generate_hash(length=8)}",
				"title": f"Kare Test {self.sfx}",
				"status": "Active",
				"currency": "TRY",
				"base_price": 100,
				"selling_price": 100,
				"primary_image": primary,
				"listing_images": [{"image": g} for g in gallery],
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		self.ilanlar = [*getattr(self, "ilanlar", []), doc.name]
		return doc.name

	def _temizle(self):
		frappe.db.rollback()
		for row in frappe.get_all(
			"Media URL Redirect", filters={"job_key": ["like", "kare-test-%"]}, fields=["name", "source_url"]
		):
			frappe.delete_doc("Media URL Redirect", row.name, force=True, ignore_permissions=True)
			archive.drop(row.source_url)
		# Bu testin açtığı her adresin arşiv kaydı (redirect satırı olmasa da —
		# ör. dönüşüm yarıda kaldıysa) düşürülür; sonraki koşuya sızmasın.
		for url in getattr(self, "urls", []):
			archive.drop(url)
		for ad in getattr(self, "ilanlar", []):
			if frappe.db.exists("Listing", ad):
				frappe.delete_doc("Listing", ad, force=True, ignore_permissions=True)
		# Yalnız bu testin açtığı dosyalar (ad önekiyle) — gerçek veriye dokunma.
		for ad in frappe.get_all("File", filters={"file_name": ["like", f"kare-{self.sfx}%"]}, pluck="name"):
			frappe.delete_doc("File", ad, force=True, ignore_permissions=True)
		frappe.db.commit()


class TestNormalizeOne(_Base):
	def test_cevirir_referans_redirect_arsiv(self):
		url = self._dosya(1600, 1000)
		ad = frappe.db.get_value("File", {"file_url": url}, "name")
		eski_ad = frappe.db.get_value("File", ad, "file_name")
		ilan = self._ilan(url)
		out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["status"], "converted", out)
		yeni = out["target_url"]
		self.assertTrue(yeni.endswith(".webp"))
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), yeni)
		with Image.open(retro_rename._disk_path(yeni)) as im:
			self.assertEqual(im.size, (1600, 1600))
		self.assertFalse(os.path.exists(retro_rename._disk_path(url)))  # 301 devreye girsin
		self.assertTrue(archive.exists(url))
		self.assertEqual(frappe.db.get_value("Media URL Redirect", {"source_url": url}, "target_url"), yeni)
		# I3 (fix round 1): File.content_hash yeni baytları yansıtmalı, görünen ad
		# `.webp` uzantısına geçmeli (eski gövde adı korunarak).
		with open(retro_rename._disk_path(yeni), "rb") as f:
			beklenen_hash = hashlib.md5(f.read()).hexdigest()  # noqa: S324 — Frappe'nin kendi content_hash algoritması
		yeni_ad = frappe.db.get_value("File", ad, "file_name")
		yeni_hash = frappe.db.get_value("File", ad, "content_hash")
		self.assertEqual(yeni_ad, os.path.splitext(eski_ad)[0] + ".webp")
		self.assertEqual(yeni_hash, beklenen_hash)

	def test_zaten_kare_webp_atlanir(self):
		url = self._dosya(1200, 1200, fmt="WEBP")
		self._ilan(url)
		self.assertEqual(kare.normalize_one(url, self.job, None)["reason"], "already_square")

	def test_kare_ama_webp_olmayan_ayni_olcude_webpye_tasinir(self):
		"""2026-09-30: kare + aralıkta JPEG de WebP'ye taşınır — ölçü ve dolgu değişmez."""
		url = self._dosya(1200, 1200)
		ilan = self._ilan(url)
		prova = kare.normalize_one(url, self.job, None, dry_run=True)
		self.assertEqual((prova["status"], prova["reason"]), ("converted", "dry_run"))
		self.assertTrue(os.path.exists(retro_rename._disk_path(url)))
		out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["status"], "converted", out)
		yeni = out["target_url"]
		self.assertTrue(yeni.endswith(".webp"))
		with Image.open(retro_rename._disk_path(yeni)) as im:
			self.assertEqual((im.format, im.size), ("WEBP", (1200, 1200)))
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), yeni)
		self.assertEqual(frappe.db.get_value("Media URL Redirect", {"source_url": url}, "target_url"), yeni)
		self.assertTrue(archive.exists(url))
		# Geri alma aynı yoldan çalışır.
		geri = kare.rollback_one(_redirect_row(url))
		self.assertTrue(geri["ok"], geri)
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), url)
		self.assertTrue(os.path.exists(retro_rename._disk_path(url)))

	def test_prova_diske_dokunmaz(self):
		url = self._dosya(1600, 1000)
		self._ilan(url)
		out = kare.normalize_one(url, self.job, None, dry_run=True)
		self.assertEqual((out["status"], out["reason"]), ("converted", "dry_run"))
		self.assertTrue(os.path.exists(retro_rename._disk_path(url)))
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": url}))

	def test_urun_disi_referans_atlanir(self):
		"""I5 (fix round 1): gerçek bir Brand'e dokunmak yerine kendi atılabilir
		kaydımızı açıp temizliyoruz — gerçek veriye dokunma kuralı (brief §Test data)."""
		url = self._dosya(1600, 1000)
		self._ilan(url)
		marka = frappe.get_doc(
			{
				"doctype": "Brand",
				"brand_code": f"KARE-{self.sfx}",
				"brand_name": f"Kare Test Brand {self.sfx}",
				"status": "Approved",
				"official_status": "Unverified",
				"logo": url,
			}
		)
		marka.flags.ignore_mandatory = True
		marka.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: (
				frappe.db.exists("Brand", marka.name)
				and frappe.delete_doc("Brand", marka.name, force=True, ignore_permissions=True)
			)
		)
		self.assertEqual(kare.normalize_one(url, self.job, None)["reason"], "not_product")

	def test_iki_ilan_tek_donusum(self):
		url = self._dosya(900, 700)
		a, b = self._ilan(url), self._ilan(self._dosya(1200, 1200), gallery=[url])
		out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["refs_updated"], 2, out)
		self.assertEqual(frappe.db.get_value("Listing", a, "primary_image"), out["target_url"])
		self.assertEqual(frappe.db.get_value("Listing Image", {"parent": b}, "image"), out["target_url"])

	def test_ikinci_cagri_idempotent(self):
		"""Fix round 2: ikinci çağrı artık `disk_missing` DEĞİL, `redirect_exists`
		diyerek atlanıyor — ilk çağrının bıraktığı `Media URL Redirect` satırı
		yeni eklenen erken kontrolde yakalanıyor (disk kontrolünden önce). Sonuç
		aynı ("bu adres tekrar işlenmez"), gerekçe daha doğru/daha ucuz."""
		url = self._dosya(1600, 1000)
		self._ilan(url)
		kare.normalize_one(url, self.job, None)
		self.assertEqual(kare.normalize_one(url, self.job, None)["reason"], "redirect_exists")

	def test_yol_gecisi_segmenti_atlanir(self):
		"""I2 (fix round 1): `..` segmenti içeren adres `archive.exists()`'e hiç
		ulaşmadan `not_image` ile atlanır (aksi hâlde orada `ValidationError`)."""
		out = kare.normalize_one("/files/../etc/passwd.jpg", self.job, None)
		self.assertEqual((out["status"], out["reason"]), ("skipped", "not_image"))

	def test_beklenmedik_hata_isi_dusurmez(self):
		"""I2 (fix round 1): `kareye_cevir`'den (ya da başka bir adımdan) sızan
		herhangi bir `Atla`-dışı hata `run_job`'u düşürmeden `status: error` olarak
		döner; dosya yarım bırakılmaz."""
		url = self._dosya(1600, 1000)
		self._ilan(url)
		with mock.patch.object(kare, "kareye_cevir", side_effect=RuntimeError("boom")):
			out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["status"], "error")
		self.assertEqual(out["reason"], "exception")
		self.assertTrue(os.path.exists(retro_rename._disk_path(url)))

	def test_bekletmedeki_dosya_atlanir(self):
		"""Fix round 2 hipotez doğrulaması (LST-04593, canlı E2E): kayıt kancası
		tetiklendiğinde dosya AV bekletmesindeyse `normalize_one` onu atlar —
		henüz kareye çevrilmez. Ölçülen gerçek gerekçe `disk_missing`, `quarantined`
		DEĞİL: `av.hold()` dosyayı FİZİKSEL olarak `retro_rename._disk_path(url)`
		(canlı yol) dışına taşıyor, `normalize_one`'ın İLK kontrolü
		(`os.path.isfile(old_path)`) bu yüzden `av.in_hold` kontrolüne hiç
		ulaşmadan `disk_missing` ile dönüyor — ikisi de "bu adres o an işlenemez"
		anlamına geliyor, koordinatörün hipotezi ikisini de olası saymıştı.
		Bir sonraki adım `test_bekletmeden_cikinca_kuyruga_girer`: bekletmeden
		çıkınca dosya bu durumda sonsuza kadar kalmıyor, yeniden kuyruğa giriyor.

		Boyut diğer testlerden BİLEREK farklı (1601×999): bu dosyanın içerik-adresi
		`self.sfx` + `(w, h)`'den türüyor (bkz. `_dosya` docstring'i) — (1600, 1000)
		neredeyse tüm bu dosyadaki testlerde kullanılıyor ve 255 olası renk
		değeriyle test sayısı arttıkça çarpışma ihtimali de artıyor (ölçüldü: fix
		round 2 ilk koşusunda birden çok test birbirinin `archived`/`redirect_exists`
		durumuna çarpıp farklı testler farklı koşularda kırıldı). Yeni testler bu
		yüzden kullanılmamış bir boyut seçiyor.
		"""
		url = self._dosya(1601, 999)
		self._ilan(url)
		self.assertTrue(av.hold(url))
		self.addCleanup(lambda: av.in_hold(url) and av.release_hold(url))
		out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["reason"], "disk_missing")

	def test_redirect_exists_ise_atlanir(self):
		"""Fix round 2: `Media URL Redirect.source_url` UNIQUE — bu adres için 301
		zaten varsa (dünkü retro-rename'in yönlendirdiği ama dosyası diskte kalan
		eski bir ad gibi) disk/DB işine hiç girmeden atla. Gerçek E2E'de bu kontrol
		olmadan `_uygula`'daki insert `UniqueValidationError` fırlatıp dosyayı
		`error` sayıyordu (2 gerçek dosya böyle "hata" verdi)."""
		url = self._dosya(1602, 998)
		self._ilan(url)
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": url,
				"target_url": "/files/onceden-donusturulmus-baska-dosya.webp",
				"job_key": self.job,
				"expires_at": frappe.utils.add_days(
					frappe.utils.now_datetime(), retro_rename.REDIRECT_TTL_DAYS
				),
				"file_rows": 0,
				"file_names": "[]",
				"ref_changes": "[]",
			}
		).insert(ignore_permissions=True)
		out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["reason"], "redirect_exists")
		# Diske hiç dokunulmadı — orijinal dosya hâlâ yerinde.
		self.assertTrue(os.path.exists(retro_rename._disk_path(url)))


class TestRollback(_Base):
	def test_geri_alma_hepsini_dondurur(self):
		url = self._dosya(1600, 1000)
		ad = frappe.db.get_value("File", {"file_url": url}, "name")
		eski_ad = frappe.db.get_value("File", ad, "file_name")
		eski_hash = frappe.db.get_value("File", ad, "content_hash")
		ilan = self._ilan(url)
		yeni = kare.normalize_one(url, self.job, None)["target_url"]
		row = frappe.get_all(
			"Media URL Redirect",
			filters={"source_url": url},
			fields=["name", "source_url", "target_url", "file_names", "ref_changes"],
		)[0]
		out = kare.rollback_one(row)
		self.assertTrue(out["ok"], out)
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), url)
		self.assertTrue(os.path.exists(retro_rename._disk_path(url)))
		self.assertFalse(os.path.exists(retro_rename._disk_path(yeni)))
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": url}))
		self.assertFalse(archive.exists(url))
		# I3 (fix round 1): file_name/content_hash da eski hâline dönmeli.
		self.assertEqual(frappe.db.get_value("File", ad, "file_name"), eski_ad)
		self.assertEqual(frappe.db.get_value("File", ad, "content_hash"), eski_hash)

	def test_hedef_hala_kullanimdaysa_silinmez(self):
		"""I1 (fix round 1): dönüşümden SONRA yeni adrese bağlanan bir referans
		(burada bir sepet satırı — `usage.LIVE_SOURCES`) webp'in silinmesini engellemeli;
		aksi hâlde geri alma o referansı kırık bırakırdı."""
		url = self._dosya(1600, 1000)
		ilan = self._ilan(url)
		yeni = kare.normalize_one(url, self.job, None)["target_url"]
		row = frappe.get_all(
			"Media URL Redirect",
			filters={"source_url": url},
			fields=["name", "source_url", "target_url", "file_names", "ref_changes"],
		)[0]

		sepet = frappe.get_doc({"doctype": "Cart", "buyer": f"kare-{self.sfx}@example.invalid"})
		sepet.name = f"KARE-CART-{self.sfx}"
		sepet.db_insert()
		satir = frappe.get_doc(
			{
				"doctype": "Cart Item",
				"parent": sepet.name,
				"parenttype": "Cart",
				"parentfield": "items",
				"listing": ilan,
				"quantity": 1,
				"snapshot_image": yeni,
			}
		)
		satir.name = f"KARE-CI-{self.sfx}"
		satir.db_insert()

		def _sepet_temizle():
			frappe.db.delete("Cart Item", {"name": satir.name})
			frappe.db.delete("Cart", {"name": sepet.name})
			frappe.db.commit()

		self.addCleanup(_sepet_temizle)

		out = kare.rollback_one(row)
		self.assertTrue(out["ok"], out)
		self.assertEqual(out["reason"], "target_kept_in_use")
		self.assertTrue(os.path.exists(retro_rename._disk_path(yeni)))
		# Ama sıradan İş kısımları (File/ref/redirect) yine geri alınmış olmalı.
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), url)
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": url}))


class TestNormalizeListing(_Base):
	def test_ilan_gorsellerini_cevirir(self):
		ana, gal = self._dosya(1600, 1000), self._dosya(800, 1000)
		ilan = self._ilan(ana, gallery=[gal])
		ozet = kare.normalize_listing(ilan)
		self.assertEqual(ozet["converted"], 2, ozet)
		self.assertTrue(frappe.db.get_value("Listing", ilan, "primary_image").endswith(".webp"))


class TestSeoRetiredCodeBridge(_Base):
	"""I6 (fix round 1): dönüşüm eski `seo_code`'u temizliyor; alpha'da yayında
	olan okunur adres artık 404 vermemeli, yeni dosyaya 301 vermeli."""

	def test_eski_okunur_ad_yeni_dosyaya_yonlendirir(self):
		url = self._dosya(1600, 1000)
		self._ilan(url)
		ad = frappe.db.get_value("File", {"file_url": url}, "name")
		eski_kod = frappe.db.get_value("File", ad, "seo_code")
		self.assertTrue(eski_kod, "seo_code otomatik atanmış olmalı (on_file_after_insert)")

		out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["status"], "converted", out)
		yeni = out["target_url"]

		# Kod artık HİÇBİR File satırında yok → `resolve()` "yok" dönmeli.
		self.assertFalse(frappe.db.exists("File", {"seo_code": eski_kod}))
		eski_yol = f"files/eski-slug-{eski_kod}.jpg"
		self.assertEqual(seo_url.resolve(eski_yol)["status"], "yok")

		rr = SeoImageRenderer(eski_yol)
		self.assertTrue(rr.can_render())
		yanit = rr.render()
		self.assertEqual(yanit.status_code, 301)
		beklenen = seo_url.seo_image_url(yeni, "eski-slug")
		self.assertTrue(yanit.headers["Location"].endswith(beklenen), yanit.headers["Location"])
		self.assertEqual(yanit.headers["Cache-Control"], "public, max-age=300")

	def test_kod_birden_fazla_eslesirse_koprulenmez(self):
		"""Belirsiz eşleşme (0 ya da >1 satır) 404'e düşer — asla tahmin etmez."""
		self.assertIsNone(seo_url.resolve_retired_code("files/x-00000000.jpg"))


class TestListingHook(_Base):
	"""`on_listing_update` — Listing.on_update kancası (spec §6, Task 3).

	Test izolasyonu: kanca `frappe.flags.in_test` açıkken erken çıkar (aksi
	hâlde `_Base` kullanan HER test dolaylı olarak gerçek bir `frappe.enqueue`
	tetikler). Bayrağı yalnız `on_listing_update` çağrısının etrafında kapatıp
	`addCleanup` ile geri açıyoruz — `_ilan`/`_dosya` kurulumu (SEO/validate
	gibi normalde `in_test` altında atlanan kontroller devreye girmesin diye)
	varsayılan `in_test = True` altında kalır. `frappe.enqueue` de her zaman
	mock'lanıyor ki hiçbir iş gerçekten kuyruklanmasın. `_in_test_kapali` artık
	`_Base`'de (fix round 2, bkz. oradaki docstring).
	"""

	def test_kayit_kuyruga_atar(self):
		url = self._dosya(1600, 1000)
		ilan = self._ilan(url)
		self._in_test_kapali()
		with mock.patch.object(frappe, "enqueue") as enq:
			doc = frappe.get_doc("Listing", ilan)
			kare.on_listing_update(doc)
		kw = enq.call_args.kwargs
		self.assertEqual(enq.call_args.args[0], "tradehub_core.media.kare.normalize_listing")
		self.assertEqual(kw["listing"], ilan)
		self.assertTrue(kw["enqueue_after_commit"])
		self.assertEqual(kw["job_id"], f"kare-listing-{ilan}")

	def test_gorselsiz_ilan_kuyruga_atmaz(self):
		ilan = self._ilan(None)
		self._in_test_kapali()
		with mock.patch.object(frappe, "enqueue") as enq:
			kare.on_listing_update(frappe.get_doc("Listing", ilan))
		enq.assert_not_called()

	def test_hook_kayitli(self):
		from tradehub_core import hooks

		self.assertIn("tradehub_core.media.kare.on_listing_update", hooks.doc_events["Listing"]["on_update"])

	def test_varyant_gorseli_kuyruga_atar(self):
		"""Yalnızca varyant görseli olan ilan da kuyruğa girmeli (ana/galeri boş)."""
		gorsel = self._dosya(1600, 1000)
		ilan = self._ilan(None)
		doc = frappe.get_doc("Listing", ilan)
		doc.append(
			"variant_items", {"attribute_type": "Renk", "attribute_value": "Kırmızı", "variant_image": gorsel}
		)
		doc.flags.ignore_mandatory = True
		doc.save(ignore_permissions=True)
		self._in_test_kapali()
		with mock.patch.object(frappe, "enqueue") as enq:
			kare.on_listing_update(frappe.get_doc("Listing", ilan))
		enq.assert_called_once()

	def test_kill_switch_devre_disi_birakir(self):
		url = self._dosya(1600, 1000)
		ilan = self._ilan(url)
		self._in_test_kapali()
		frappe.conf["urun_gorseli_kare_kapali"] = 1
		self.addCleanup(lambda: frappe.conf.pop("urun_gorseli_kare_kapali", None))
		with mock.patch.object(frappe, "enqueue") as enq:
			kare.on_listing_update(frappe.get_doc("Listing", ilan))
		enq.assert_not_called()

	def test_in_test_bayragi_acikken_kuyruga_atmaz(self):
		"""Varsayılan test-runner durumu (`in_test = True`) kancayı sessizce atlatır."""
		url = self._dosya(1600, 1000)
		ilan = self._ilan(url)
		self.assertTrue(frappe.flags.in_test)
		with mock.patch.object(frappe, "enqueue") as enq:
			kare.on_listing_update(frappe.get_doc("Listing", ilan))
		enq.assert_not_called()

	def test_toplu_ice_aktarim_da_kuyruga_atar(self):
		"""Fix round 1: `in_import` artık erken çıkış değil — toplu içe aktarılan
		ürünlerin görselleri de kareye çevrilmeli (kullanıcı gereksinimi: her ürün
		görseli)."""
		url = self._dosya(1600, 1000)
		ilan = self._ilan(url)
		self._in_test_kapali()
		frappe.flags.in_import = True
		self.addCleanup(lambda: setattr(frappe.flags, "in_import", False))
		with mock.patch.object(frappe, "enqueue") as enq:
			kare.on_listing_update(frappe.get_doc("Listing", ilan))
		enq.assert_called_once()


class TestReleaseHoldTrigger(_Base):
	"""Fix round 2: AV bekletmesinden çıkan dosya kareleme kuyruğuna giriyor mu.

	`av_notr.py` bu modülde yalnız OTOMATİK tetikleyicileri (`enqueue_scan`,
	`maybe_scan_on_insert`) susturuyor — `av.hold`/`av.release_hold`/`av.in_hold`
	kendileri susturulmuyor (kapsamı `av_notr.py` docstring'inde), o yüzden
	bekletme döngüsünü burada elle üretip test edebiliyoruz.
	"""

	def test_bekletmeden_cikinca_kuyruga_girer(self):
		"""`kare.enqueue_for_released_url` doğrudan — ilan başına tek iş, doğru job_id.

		Boyutlar bu sınıfın her testinde BİLEREK farklı — gerekçe
		`TestNormalizeOne.test_bekletmedeki_dosya_atlanir` docstring'inde
		(çakışma ihtimalini bu dosyanın en çok tekrar eden (1600, 1000) çiftinden
		uzak tutmak)."""
		url = self._dosya(1603, 997)
		ilan = self._ilan(url)
		self._in_test_kapali()
		with mock.patch.object(frappe, "enqueue") as enq:
			n = kare.enqueue_for_released_url(url)
		self.assertEqual(n, 1)
		kw = enq.call_args.kwargs
		self.assertEqual(enq.call_args.args[0], "tradehub_core.media.kare.normalize_listing")
		self.assertEqual(kw["listing"], ilan)
		self.assertTrue(kw["enqueue_after_commit"])
		# I6 (final review): bırakma tetiği kayıt işinden AYRI job_id taşır.
		izi = hashlib.sha1(url.encode()).hexdigest()[:10]
		self.assertEqual(kw["job_id"], f"kare-release-{ilan}-{izi}")
		self.assertNotEqual(kw["job_id"], f"kare-listing-{ilan}")
		self.assertTrue(kw["deduplicate"])

	def test_gorselsiz_url_kuyruga_atmaz(self):
		"""Hiçbir ilanın kullanmadığı adres — sessizce 0 döner, iş yaratmaz."""
		self._in_test_kapali()
		with mock.patch.object(frappe, "enqueue") as enq:
			n = kare.enqueue_for_released_url("/files/hicbir-ilanin-kullanmadigi-dosya-x.jpg")
		self.assertEqual(n, 0)
		enq.assert_not_called()

	def test_kill_switch_devre_disi_birakir(self):
		url = self._dosya(1604, 996)
		self._ilan(url)
		self._in_test_kapali()
		frappe.conf["urun_gorseli_kare_kapali"] = 1
		self.addCleanup(lambda: frappe.conf.pop("urun_gorseli_kare_kapali", None))
		with mock.patch.object(frappe, "enqueue") as enq:
			n = kare.enqueue_for_released_url(url)
		self.assertEqual(n, 0)
		enq.assert_not_called()

	def test_av_release_hold_kareyi_tetikler(self):
		"""Kökün kendisi: `av.release_hold` — bekletmeden çıkışın TEK kapısı — ürün
		görseli için kareleme işini kuyruğa alıyor mu. Bu, LST-04593'te ölçülen
		boşluğun ta kendisi: kayıt kancası dosya bekletmedeyken `quarantined` diye
		atlıyordu ve tarama bitip dosya geri konduğunda kimse yeniden
		tetiklemiyordu (bkz. `TestNormalizeOne.test_bekletmedeki_dosya_atlanir`)."""
		url = self._dosya(1605, 995)
		ilan = self._ilan(url)
		self.assertTrue(av.hold(url))
		self._in_test_kapali()
		with mock.patch.object(frappe, "enqueue") as enq:
			self.assertTrue(av.release_hold(url))
		kw = enq.call_args.kwargs
		self.assertEqual(enq.call_args.args[0], "tradehub_core.media.kare.normalize_listing")
		self.assertEqual(kw["listing"], ilan)
		self.assertTrue(kw["job_id"].startswith(f"kare-release-{ilan}-"))

	def test_serbest_kaldiktan_sonra_donusum_tamamlanir(self):
		"""Uçtan uca: bekletmeden çık → kuyruklanan işi (mock'lanmış `enqueue`'un
		yakaladığı argümanlarla) elle çalıştır → dosya gerçekten kareye döner.
		Gerçek RQ worker'ını test ortamında çalıştırmadan "released → conversion
		performed" iddiasını kanıtlıyor."""
		url = self._dosya(1606, 994)
		ilan = self._ilan(url)
		self.assertTrue(av.hold(url))
		self._in_test_kapali()
		with mock.patch.object(frappe, "enqueue") as enq:
			self.assertTrue(av.release_hold(url))
		kw = enq.call_args.kwargs
		ozet = kare.normalize_listing(kw["listing"])
		self.assertEqual(ozet["converted"], 1, ozet)
		self.assertTrue(frappe.db.get_value("Listing", ilan, "primary_image").endswith(".webp"))


def _redirect_row(url):
	return frappe.get_all(
		"Media URL Redirect",
		filters={"source_url": url},
		fields=["name", "source_url", "target_url", "file_names", "ref_changes"],
	)[0]


class TestFinalReviewC1(_Base):
	"""C1 (final review): bayat form eski adresi geri yazınca kalıcı kırık kalmasın."""

	def test_redirect_exists_canli_referansi_iyilestirir(self):
		url = self._dosya(1607, 993)
		ilan = self._ilan(url)
		yeni = kare.normalize_one(url, self.job, None)["target_url"]
		# Bayat form: ham yazım, `modified` değişmez (refs.retarget ile aynı).
		frappe.db.set_value("Listing", ilan, "primary_image", url, update_modified=False)
		out = kare.normalize_one(url, self.job, None)
		self.assertEqual((out["status"], out["reason"]), ("skipped", "healed"), out)
		self.assertEqual(out["refs_updated"], 1)
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), yeni)
		# İyileştirme provenance'a eklendi → geri alma onu da eski hâline döndürür.
		out_geri = kare.rollback_one(_redirect_row(url))
		self.assertTrue(out_geri["ok"], out_geri)
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), url)

	def test_redirect_exists_dry_run_raporlar_ama_yazmaz(self):
		"""Prova (`dry_run=True`) iyileştirme dalında da HİÇBİR ŞEY yazmamalı."""
		url = self._dosya(1609, 991)
		ilan = self._ilan(url)
		kare.normalize_one(url, self.job, None)
		frappe.db.set_value("Listing", ilan, "primary_image", url, update_modified=False)
		oncesi = _redirect_row(url)["ref_changes"]
		with mock.patch.object(kare.refs, "retarget") as retarget:
			out = kare.normalize_one(url, self.job, None, dry_run=True)
		retarget.assert_not_called()
		self.assertEqual((out["status"], out["reason"]), ("skipped", "healed"), out)
		self.assertTrue(out["dry_run"])
		self.assertEqual(out["refs_updated"], 0)
		self.assertEqual(out["refs_would_update"], 1)
		# Bayat referans yerinde kaldı, provenance değişmedi.
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), url)
		self.assertEqual(_redirect_row(url)["ref_changes"], oncesi)

	def test_run_job_healed_nedenini_sayar(self):
		url = self._dosya(1608, 992)
		ilan = self._ilan(url)
		kare.normalize_one(url, self.job, None)
		frappe.db.set_value("Listing", ilan, "primary_image", url, update_modified=False)
		frappe.db.commit()
		key = f"kare-test-run-{self.sfx}"
		with mock.patch.object(kare, "aday_urls", return_value=[url]):
			kare.run_job(key, dry_run=0)
		durum = retro_rename.read_progress(key)
		self.assertEqual(durum["skip_reasons"].get("healed"), 1, durum)
		self.assertEqual(durum["refs_updated"], 1, durum)

	def test_purge_canli_referansi_hedefe_cevirip_siler(self):
		url = self._dosya(1609, 991)
		ilan = self._ilan(url)
		yeni = kare.normalize_one(url, self.job, None)["target_url"]
		frappe.db.set_value("Listing", ilan, "primary_image", url, update_modified=False)
		row = frappe.get_all(
			"Media URL Redirect", filters={"source_url": url}, fields=["name", "source_url", "target_url"]
		)[0]
		self.assertTrue(retro_rename._hedefe_iyilestir(row))
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), yeni)

	def test_purge_hedef_yoksa_satiri_korur(self):
		url = self._dosya(1610, 990)
		ilan = self._ilan(url)
		yeni = kare.normalize_one(url, self.job, None)["target_url"]
		frappe.db.set_value("Listing", ilan, "primary_image", url, update_modified=False)
		row = frappe.get_all(
			"Media URL Redirect", filters={"source_url": url}, fields=["name", "source_url", "target_url"]
		)[0]
		with mock.patch.object(retro_rename.os.path, "isfile", return_value=False):
			self.assertFalse(retro_rename._hedefe_iyilestir(row))
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), url)
		self.assertTrue(yeni)

	def test_purge_expired_canli_satiri_silmez(self):
		"""Uçtan uca `purge_expired_redirects`: yalnız bu testin satırı süresi dolmuş
		sayılır (süzgeç yamalanmaz; `expires_at` geçmişe çekilir). Canlı referans
		var ve hedef diskte yok → satır KALIR."""
		expired = frappe.get_all(
			"Media URL Redirect", filters={"expires_at": ("<", frappe.utils.now_datetime())}, pluck="name"
		)
		if expired:
			self.skipTest("sitede süresi dolmuş gerçek 301 satırı var — gerçek veriye dokunulmaz")
		url = self._dosya(1611, 989)
		ilan = self._ilan(url)
		kare.normalize_one(url, self.job, None)
		frappe.db.set_value("Listing", ilan, "primary_image", url, update_modified=False)
		frappe.db.set_value(
			"Media URL Redirect",
			{"source_url": url},
			"expires_at",
			frappe.utils.add_days(frappe.utils.now_datetime(), -1),
		)
		with mock.patch.object(retro_rename.os.path, "isfile", return_value=False):
			silinen = retro_rename.purge_expired_redirects()
		self.assertEqual(silinen, 0)
		self.assertTrue(frappe.db.exists("Media URL Redirect", {"source_url": url}))

	def test_validate_eski_adresi_hedefe_cevirir(self):
		from tradehub_core import hooks

		self.assertIn(
			"tradehub_core.media.kare.yonlendirilmis_gorselleri_esle",
			hooks.doc_events["Listing"]["validate"],
		)
		url = self._dosya(1612, 988)
		ilan = self._ilan(url)
		yeni = kare.normalize_one(url, self.job, None)["target_url"]
		doc = frappe.get_doc("Listing", ilan)
		doc.primary_image = url
		doc.append("listing_images", {"image": url})
		doc.append(
			"variant_items",
			{
				"attribute_type": "Renk",
				"attribute_value": "Mavi",
				"variant_image": url,
				"variant_gallery": frappe.as_json([url, "/files/baska.jpg"]),
			},
		)
		doc.flags.ignore_mandatory = True
		doc.save(ignore_permissions=True)
		doc.reload()
		self.assertEqual(doc.primary_image, yeni)
		self.assertEqual(doc.listing_images[-1].image, yeni)
		self.assertEqual(doc.variant_items[-1].variant_image, yeni)
		self.assertEqual(frappe.parse_json(doc.variant_items[-1].variant_gallery), [yeni, "/files/baska.jpg"])

	def test_validate_suresi_dolmus_yonlendirmeyi_izlemez(self):
		url = self._dosya(1613, 987)
		ilan = self._ilan(url)
		kare.normalize_one(url, self.job, None)
		frappe.db.set_value(
			"Media URL Redirect",
			{"source_url": url},
			"expires_at",
			frappe.utils.add_days(frappe.utils.now_datetime(), -1),
		)
		doc = frappe.get_doc("Listing", ilan)
		doc.primary_image = url
		kare.yonlendirilmis_gorselleri_esle(doc)
		self.assertEqual(doc.primary_image, url)


class TestFinalReviewRollback(_Base):
	def test_geri_alma_kilitleri_alir(self):
		"""I2: geri alma kaynak VE hedef adres kilidini alır (dönüşümle aynı ad)."""
		import contextlib

		url = self._dosya(1614, 986)
		self._ilan(url)
		kare.normalize_one(url, self.job, None)
		row = _redirect_row(url)
		with mock.patch.object(kare, "filelock", side_effect=lambda *a, **k: contextlib.nullcontext()) as fl:
			out = kare.rollback_one(row)
		self.assertTrue(out["ok"], out)
		adlar = [c.args[0] for c in fl.call_args_list]
		self.assertIn(kare._kilit_adi(row.source_url), adlar)
		self.assertIn(kare._kilit_adi(row.target_url), adlar)

	def test_geri_alma_kilit_zaman_asimi(self):
		from frappe.utils.file_lock import LockTimeoutError

		url = self._dosya(1615, 985)
		self._ilan(url)
		kare.normalize_one(url, self.job, None)
		row = _redirect_row(url)
		with mock.patch.object(kare, "filelock", side_effect=LockTimeoutError("x")):
			out = kare.rollback_one(row)
		self.assertEqual((out["ok"], out["reason"]), (False, "lock_timeout"))
		self.assertTrue(frappe.db.exists("Media URL Redirect", {"source_url": url}))

	def test_otomatik_yol_medya_isi_aktifken_atlar(self):
		url = self._dosya(1616, 984)
		ilan = self._ilan(url)
		with (
			mock.patch.object(kare, "_medya_isi_aktif", return_value=True),
			mock.patch.object(kare, "normalize_one") as n1,
		):
			ozet = kare.normalize_listing(ilan)
		n1.assert_not_called()
		self.assertEqual(ozet.get("skipped_active_job"), 1)

	def test_medya_isi_aktif_ortak_kilidi_okur(self):
		key = f"kare-test-lock-{self.sfx}"
		if kare._medya_isi_aktif():
			self.skipTest("gerçek bir medya işi çalışıyor")
		self.assertTrue(retro_rename.claim_active(key, ttl=60))
		try:
			self.assertTrue(kare._medya_isi_aktif())
		finally:
			retro_rename.release_active(key)
		self.assertFalse(kare._medya_isi_aktif())

	def test_geri_alma_seo_kodunu_yeniden_atar(self):
		"""I4: dönüşüm `seo_code`'u boşaltır; geri alma eski adrese kodu geri verir."""
		url = self._dosya(1617, 983)
		self._ilan(url)
		ad = frappe.db.get_value("File", {"file_url": url}, "name")
		kare.normalize_one(url, self.job, None)
		out = kare.rollback_one(_redirect_row(url))
		self.assertTrue(out["ok"], out)
		self.assertEqual(frappe.db.get_value("File", ad, "file_url"), url)
		self.assertTrue(frappe.db.get_value("File", ad, "seo_code"))

	def test_optimize_damgalari_temizlenir_ve_geri_gelir(self):
		url = self._dosya(1618, 982)
		self._ilan(url)
		ad = frappe.db.get_value("File", {"file_url": url}, "name")
		damga = frappe.utils.now_datetime().replace(microsecond=0)
		frappe.db.set_value("File", ad, {"th_optimized_at": damga, "th_original_size": 12345})
		kare.normalize_one(url, self.job, None)
		self.assertIsNone(frappe.db.get_value("File", ad, "th_optimized_at"))
		self.assertFalse(frappe.db.get_value("File", ad, "th_original_size"))
		self.assertEqual(frappe.db.get_value("File", ad, "th_media_width"), 1618)
		kare.rollback_one(_redirect_row(url))
		self.assertEqual(frappe.db.get_value("File", ad, "th_original_size"), 12345)
		self.assertEqual(frappe.utils.get_datetime(frappe.db.get_value("File", ad, "th_optimized_at")), damga)

	def test_run_rollback_toplar_ve_audit_yazar(self):
		url = self._dosya(1619, 981)
		self._ilan(url)
		kare.normalize_one(url, self.job, None)
		rk = f"kare-test-rb-{self.sfx}"
		with mock.patch.object(kare.audit, "log_media_batch") as lb:
			kare.run_rollback(self.job, rk)
		durum = retro_rename.read_progress(rk)
		self.assertEqual(durum["state"], "completed", durum)
		self.assertEqual(durum["refs_updated"], 1, durum)
		lb.assert_called_once()
		self.assertEqual(lb.call_args.kwargs["job_key"], self.job)

	def test_run_rollback_beklenmedik_hata(self):
		url = self._dosya(1620, 980)
		self._ilan(url)
		kare.normalize_one(url, self.job, None)
		rk = f"kare-test-rb-{self.sfx}"
		with (
			mock.patch.object(kare, "rollback_one", side_effect=RuntimeError("boom")),
			mock.patch.object(kare.audit, "log_media_batch") as lb,
		):
			kare.run_rollback(self.job, rk)
		durum = retro_rename.read_progress(rk)
		self.assertEqual(durum["state"], "error", durum)
		self.assertTrue(durum.get("message"))
		lb.assert_called_once()
		self.assertFalse(kare._medya_isi_aktif())


class TestFinalReviewAssets(_Base):
	"""I3: eski (kare olmayan) türevler manifestten çekilir, geri almada döner."""

	def _varlik(self, ad, ek):
		v = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": "product.image",
				"media_type": "image",
				"state": "ready",
				"source_file": ad,
				"content_sha256": hashlib.sha256(f"{self.sfx}-{ek}".encode()).hexdigest()[:32],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.db.delete("Media Asset", {"name": v.name}) or frappe.db.commit())
		return v.name

	def test_varlik_emekli_edilir_ve_geri_doner(self):
		url = self._dosya(1621, 979)
		self._ilan(url)
		ad = frappe.db.get_value("File", {"file_url": url}, "name")
		eski_varlik = self._varlik(ad, "eski")
		with mock.patch("tradehub_core.media.pipeline_bridge.maybe_generate_renditions") as mgr:
			out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["status"], "converted", out)
		self.assertEqual(frappe.db.get_value("Media Asset", eski_varlik, "state"), "archived")
		mgr.assert_called_once()
		self.assertEqual(mgr.call_args.args[0].name, ad)
		row = _redirect_row(url)
		kayit = frappe.parse_json(row.file_names)[0]
		self.assertEqual(kayit["assets"], [eski_varlik])

		# Webp için pipeline'ın ürettiği varlık (bayrak açık senaryosu).
		yeni_varlik = self._varlik(ad, "yeni")
		out = kare.rollback_one(row)
		self.assertTrue(out["ok"], out)
		self.assertEqual(frappe.db.get_value("Media Asset", eski_varlik, "state"), "ready")
		self.assertEqual(frappe.db.get_value("Media Asset", yeni_varlik, "state"), "archived")


class TestFinalReviewMisc(_Base):
	def test_kare_dosya_refs_find_cagirmaz(self):
		"""I5: zaten kare WebP dosya başlıktan anlaşılır; pahalı referans taraması yok."""
		url = self._dosya(1200, 1200, fmt="WEBP")
		self._ilan(url)
		with (
			mock.patch.object(kare.refs, "find") as rf,
			mock.patch.object(kare, "kareye_cevir") as kc,
		):
			out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["reason"], "already_square")
		rf.assert_not_called()
		kc.assert_not_called()

	def test_disk_yazma_hatasi_temiz_birakir(self):
		url = self._dosya(1622, 978)
		self._ilan(url)
		with mock.patch.object(kare.archive, "store", side_effect=OSError("dolu")):
			out = kare.normalize_one(url, self.job, None)
		self.assertEqual((out["status"], out["reason"]), ("error", "disk_write"))
		self.assertFalse(os.path.exists(retro_rename._disk_path(out["target_url"])))
		self.assertFalse(archive.exists(url))
		self.assertTrue(os.path.exists(retro_rename._disk_path(url)))


class TestBackfillEskiVarliklar(_Base):
	"""I3 öncesi satır (file_names'te `assets` yok): bayat `ready` varlıklar geriye dönük emekli."""

	def _varlik(self, ad, content_sha256):
		v = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": "product.image",
				"media_type": "image",
				"state": "ready",
				"source_file": ad,
				"content_sha256": content_sha256,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.db.delete("Media Asset", {"name": v.name}) or frappe.db.commit())
		return v.name

	def _eski_satir(self, w, h, *, duz_liste=False):
		"""Gerçek dönüşüm + satırı I3 öncesi biçime indir + eski/yeni/belirsiz varlık."""
		url = self._dosya(w, h)
		self._ilan(url)
		ad = frappe.db.get_value("File", {"file_url": url}, "name")
		with mock.patch("tradehub_core.media.pipeline_bridge.maybe_generate_renditions"):
			out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["status"], "converted", out)
		row = _redirect_row(url)
		kayitlar = frappe.parse_json(row.file_names)
		eski = [ad] if duz_liste else [{k: v for k, v in x.items() if k != "assets"} for x in kayitlar]
		frappe.db.set_value("Media URL Redirect", row.name, "file_names", frappe.as_json(eski))
		kok = lambda u: os.path.splitext(os.path.basename(u))[0]  # noqa: E731
		self.varliklar = {
			"bayat": self._varlik(ad, kok(url)),  # eski jpg'nin içerik kimliği
			"guncel": self._varlik(ad, kok(out["target_url"])),  # webp'in kendisi
			"belirsiz": self._varlik(ad, ""),  # hash yok, sürüm yok → dokunulmaz
		}
		frappe.db.commit()
		return url, ad

	def _durum(self, anahtar):
		return frappe.db.get_value("Media Asset", self.varliklar[anahtar], "state")

	def test_prova_dokunmaz_uygulama_bayati_emekli_eder_ve_idempotent(self):
		url, ad = self._eski_satir(1624, 976)
		ham_once = _redirect_row(url).file_names
		with mock.patch("tradehub_core.media.pipeline_bridge.maybe_generate_renditions") as mgr:
			prova = kare.backfill_eski_varliklar(dry_run=1, job_key=self.job)
		self.assertEqual((prova["rows_checked"], prova["files"]), (1, 1), prova)
		self.assertEqual(prova["stale_assets_found"], 1, prova)
		self.assertEqual(prova["fresh_assets_kept"], 1, prova)
		self.assertEqual(prova["archived"], 0, prova)
		self.assertEqual(prova["skipped_reasons"], {"asset_undeterminable": 1}, prova)
		self.assertEqual(self._durum("bayat"), "ready")
		self.assertEqual(_redirect_row(url).file_names, ham_once)
		mgr.assert_not_called()

		with mock.patch("tradehub_core.media.pipeline_bridge.maybe_generate_renditions") as mgr:
			sonuc = kare.backfill_eski_varliklar(dry_run=0, job_key=self.job)
		self.assertEqual((sonuc["archived"], sonuc["renditions_triggered"]), (1, 1), sonuc)
		self.assertEqual(self._durum("bayat"), "archived")
		self.assertEqual(self._durum("guncel"), "ready")
		self.assertEqual(self._durum("belirsiz"), "ready")
		mgr.assert_called_once()
		self.assertEqual(mgr.call_args.args[0].name, ad)
		kayit = frappe.parse_json(_redirect_row(url).file_names)[0]
		self.assertEqual(kayit["assets"], [self.varliklar["bayat"]])
		self.assertIn("old_content_hash", kayit)  # mevcut alanlar korunur

		ikinci = kare.backfill_eski_varliklar(dry_run=0, job_key=self.job)
		self.assertEqual(ikinci["rows_checked"], 0, ikinci)
		self.assertEqual(ikinci["skipped_reasons"], {"already_new_format": 1}, ikinci)

		# Mevcut geri alma, backfill'in kaydettiği varlığı geri getirir.
		out = kare.rollback_one(_redirect_row(url))
		self.assertTrue(out["ok"], out)
		self.assertEqual(self._durum("bayat"), "ready")

	def test_duz_ad_listesi_dicte_cevrilir_ve_geri_alinabilir(self):
		url, ad = self._eski_satir(1625, 975, duz_liste=True)
		with mock.patch("tradehub_core.media.pipeline_bridge.maybe_generate_renditions"):
			sonuc = kare.backfill_eski_varliklar(dry_run=0, job_key=self.job)
		self.assertEqual(sonuc["archived"], 1, sonuc)
		self.assertEqual(
			frappe.parse_json(_redirect_row(url).file_names),
			[{"name": ad, "assets": [self.varliklar["bayat"]]}],
		)
		out = kare.rollback_one(_redirect_row(url))
		self.assertTrue(out["ok"], out)
		self.assertEqual(self._durum("bayat"), "ready")

	def test_hedefte_olmayan_file_atlanir(self):
		url, _ad = self._eski_satir(1626, 974)
		row = _redirect_row(url)
		frappe.db.set_value("Media URL Redirect", row.name, "file_names", frappe.as_json([{"name": "yok"}]))
		frappe.db.commit()
		sonuc = kare.backfill_eski_varliklar(dry_run=0, job_key=self.job)
		self.assertEqual(sonuc["skipped_reasons"], {"file_not_at_target": 1}, sonuc)
		self.assertEqual(self._durum("bayat"), "ready")
