# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-042 — tekilleştirme arama ucu: `api/seller_media.find_in_my_library`.

Ucun tek işi, istemcinin tarayıcıda hesapladığı SHA-256 için "bu dosya SENİN
kütüphanende var mı" sorusuna cevap vermek. Buradaki testlerin ağırlık merkezi
KİRACI İZOLASYONU ve o izolasyon testinin BOŞ DOĞRU (vacuous) olmadığının
kanıtıdır:

  * B'nin dosyası A'nın sorgusunda görünmez        (izolasyon)
  * AYNI hash B'nin kendi sorgusunda görünür        (vacuity kanıtı: dosya
    gerçekten bulunabilir durumda — A'daki "yok" cevabı boş bir doğru değil)
  * İzolasyon süzgeci (`ownership.scope`) ATLANIRSA aynı sorgu dosyayı BULUR
    (kırmızı kanıt: A'yı koruyan tek şey o süzgeç; süzgeç gevşetilirse test
    kırmızıya döner)

Gerçek DB kullanılır (`FrappeTestCase`): eşleşme `tabFile.file_url` üzerinden,
içerik-adresli adlandırma (`media/naming.py` write_file hook'u) ile yapılıyor;
hook'un gerçekten devrede olduğu her testin ÖN KOŞULU olarak ayrıca doğrulanır
— hook düşmüşse test sessizce geçmek yerine kurulumda patlar.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_dedup_endpoint
"""

from __future__ import annotations

import base64
import hashlib
import io
import os

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import CustomFunction
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import seller_media as uc
from tradehub_core.media import inventory, pipeline_bridge, pipeline_flags
from tradehub_core.utils.tenant import clear_seller_cache_for_user

Left = CustomFunction("LEFT", ["s", "n"])


def _jpeg_baytlari(suffix: str) -> bytes:
	"""Koşu başına benzersiz, GERÇEK bir JPEG.

	Benzersizlik EOI'den sonra eklenen kuyrukla sağlanıyor: JPEG geçerli kalır
	(içerik denetimi geçer), hash her koşuda değişir — önceki koşudan kalan
	kayıt/blob ile karışmaz.
	"""
	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, "JPEG")
	return buf.getvalue() + f"dedup-{suffix}".encode()


class _DedupUcuTesti(FrappeTestCase):
	"""Ortak fixture: satıcı A + satıcı B, kullanıcı/oturum temizliği."""

	# -- fixture yardımcıları --------------------------------------------------

	def _drop(self, doctype: str, name: str) -> None:
		# `File.insert` diske yazıp commit ediyor; temizlik de kalıcı olmalı.
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def _user(self, tag: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"t042-{tag}-{self.suffix}@test.local",
				"first_name": tag,
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": "Marketplace Seller"}],
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
				"seller_code": f"T042{tag}{self.suffix}",
				"seller_name": f"T042 {tag} {self.suffix}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Admin Seller Profile", doc.name))
		return doc.name

	def _dosya_yukle(self, kullanici: str, icerik: bytes, ad: str) -> frappe.model.document.Document:
		"""Dosyayı O KULLANICININ oturumuyla yükler (sahiplik yükleyenden türer)."""
		frappe.set_user(kullanici)
		try:
			doc = frappe.get_doc(
				{"doctype": "File", "file_name": ad, "is_private": 0, "content": icerik}
			).insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("File", doc.name))
		return doc

	# -- kurulum ----------------------------------------------------------------

	def setUp(self) -> None:
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)

		self.a_owner = self._user("a")
		self.tenant_a = self._seller("A", self.a_owner)
		self.b_owner = self._user("b")
		self.tenant_b = self._seller("B", self.b_owner)


class TestFindInMyLibrary(_DedupUcuTesti):
	def setUp(self) -> None:
		super().setUp()
		# B'nin dosyası — izolasyonun sınanacağı hedef.
		self.icerik_b = _jpeg_baytlari(f"b-{self.suffix}")
		self.sha_b = hashlib.sha256(self.icerik_b).hexdigest()
		self.dosya_b = self._dosya_yukle(self.b_owner, self.icerik_b, "t042-b.jpg")

		# ÖN KOŞUL — içerik-adresli adlandırma gerçekten devrede. Devrede
		# değilse eşleşme mekanizmasının tamamı anlamsız: burada PATLA,
		# aşağıdaki "bulunamadı" iddiaları boş doğruya dönmesin.
		beklenen = f"/files/{self.sha_b[:2]}/{self.sha_b[:32]}.jpg"
		self.assertEqual(
			self.dosya_b.file_url,
			beklenen,
			"write_file hook'u (media/naming.py) devrede değil — eşleşme ön koşulu düştü",
		)

	# -- kiracı izolasyonu -------------------------------------------------------

	def test_baska_saticinin_dosyasi_gorunmez_ve_kanit_bos_dogru_degil(self):
		"""B'nin dosyası A'ya görünmez; aynı hash B'de görünür (vacuity kanıtı)."""
		# 1) İzolasyon: A sorar, "yok" alır — dosyanın VARLIĞI da sızmaz.
		frappe.set_user(self.a_owner)
		sonuc_a = uc.find_in_my_library(self.sha_b)
		self.assertEqual(sonuc_a, {"found": False, "file": None})

		# 2) Vacuity kanıtı: AYNI hash, sahibin oturumunda BULUNUR. Bu geçmezse
		#    (1) hiçbir şey ölçmüyor demektir — dosya kimseye görünmüyordur.
		frappe.set_user(self.b_owner)
		sonuc_b = uc.find_in_my_library(self.sha_b)
		self.assertTrue(sonuc_b["found"])
		self.assertEqual(sonuc_b["file"]["file_url"], self.dosya_b.file_url)
		self.assertEqual(sonuc_b["file"]["file_name"], "t042-b.jpg")
		self.assertTrue(sonuc_b["file"]["uploaded_at"])

	def test_kirmizi_kanit_izolasyon_suzgeci_olmadan_dosya_bulunur(self):
		"""Kontrol gevşetilince KIRMIZI: `ownership.scope` atlanırsa B'nin
		dosyası sorguda VARDIR.

		Bu test, izolasyon testinin neyi ölçtüğünü kanıtlar: A'nın "yok" cevabı
		veritabanında satır olmadığından değil, süzgeç onu A'dan sakladığından.
		Süzgeç bir gün sessizce gevşetilirse önce bu varsayım görünür kalsın.
		"""
		prefix = f"/files/{self.sha_b[:2]}/{self.sha_b[:32]}"
		f, sorgu = inventory._base_query()  # noqa: SLF001 — bilinçli: süzgeçSİZ taban sorgu
		satirlar = (
			sorgu.where(Left(f.file_url, len(prefix) + 1) == prefix + ".")
			.select(f.file_url)
			.run(as_dict=True)
		)
		self.assertEqual(
			[s["file_url"] for s in satirlar],
			[self.dosya_b.file_url],
			"süzgeçsiz sorgu dosyayı bulmalıydı — izolasyon testi boş doğru olurdu",
		)

		# Aynı taban sorguya İZOLASYON eklenince (A adına) satır kaybolur.
		f2, sorgu2 = inventory._base_query()
		from tradehub_core.media import ownership

		daralt = ownership.scope(sorgu2, f2, self.tenant_a)
		satirlar_a = (
			daralt.where(Left(f2.file_url, len(prefix) + 1) == prefix + ".")
			.select(f2.file_url)
			.run(as_dict=True)
		)
		self.assertEqual(satirlar_a, [])

	# -- sözleşme ----------------------------------------------------------------

	def test_gecersiz_hash_reddedilir(self):
		frappe.set_user(self.a_owner)
		for bozuk in ("", "abc", "z" * 64, self.sha_b[:63], self.sha_b + "0"):
			with self.assertRaises(frappe.ValidationError):
				uc.find_in_my_library(bozuk)

	def test_buyuk_harfli_hash_normalize_edilir(self):
		frappe.set_user(self.b_owner)
		sonuc = uc.find_in_my_library(self.sha_b.upper())
		self.assertTrue(sonuc["found"])

	def test_magazasiz_kullanici_reddedilir(self):
		"""Mağazası olmayan oturum uca hiç giremez (boş liste bile dönmez)."""
		yalin = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"t042-yalin-{self.suffix}@test.local",
				"first_name": "yalin",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("User", yalin.name))
		frappe.set_user(yalin.name)
		with self.assertRaises(frappe.PermissionError):
			uc.find_in_my_library(self.sha_b)

	def test_eski_adlandirmali_dosya_kapsam_disi(self):
		"""İçerik-adresli olmayan (TUR-141 öncesi) adres SAHİBİNE bile dönmez.

		Bilinçli sınır (bkz. `inventory.find_by_sha256`): SHA-256 eski
		kayıtların hiçbir kolonunda yok (`content_hash` MD5 — ölçüldü);
		addan eşleşmeyen dosya için uyarı ÜRETİLMEZ, yanlış pozitif üretilmez.
		"""
		icerik = _jpeg_baytlari(f"eski-{self.suffix}")
		sha = hashlib.sha256(icerik).hexdigest()
		dosya = self._dosya_yukle(self.b_owner, icerik, "t042-eski.jpg")
		# Eski düzeni taklit et: kayıt hash'siz bir adresi gösteriyor.
		frappe.db.set_value("File", dosya.name, "file_url", f"/files/t042-eski-{self.suffix}.jpg")
		frappe.db.commit()

		frappe.set_user(self.b_owner)
		self.assertEqual(uc.find_in_my_library(sha), {"found": False, "file": None})

	def test_copteki_dosya_bulunmaz(self):
		"""Çöpe bırakılan dosyanın public adresi ölüdür; 'kütüphanenizde' denmez."""
		icerik = _jpeg_baytlari(f"cop-{self.suffix}")
		sha = hashlib.sha256(icerik).hexdigest()
		dosya = self._dosya_yukle(self.b_owner, icerik, "t042-cop.jpg")

		frappe.set_user(self.b_owner)
		self.assertTrue(uc.find_in_my_library(sha)["found"])  # önce bulunuyor

		frappe.set_user("Administrator")
		frappe.db.set_value("File", dosya.name, "th_trashed_at", frappe.utils.now_datetime())
		frappe.db.commit()

		frappe.set_user(self.b_owner)
		self.assertEqual(uc.find_in_my_library(sha), {"found": False, "file": None})


class TestKatman2SourceHash(_DedupUcuTesti):
	"""Rapor 75 kusur #2 — katman 2: `Media Version.source_hash` üzerinden eşleşme.

	Ölçülen kusur: sunucu görselleri yükleme anında dönüştürüyor (PNG→WebP,
	`api/seller_media._kaydet`), saklanan içeriğin adı/hash'i istemcinin
	ORİJİNAL dosyadan hesapladığı sha256'dan ayrışıyor → katman 1 (içerik-adresli
	ad) görsellerde ölü. Katman 2, boru hattının İŞLEDİĞİ dosyaları
	`source_hash` kaydından yakalar — dosyanın adı legacy düzende olsa bile
	(canlı ölçüm: işlenmiş 9 dosyanın 9'u legacy adlı).

	Fixture GERÇEK yoldan kurulur: `upload_media` (gerçek PNG→WebP dönüşümü) →
	Listing'e bağla → `_run_rendition_job` (gerçek Media Asset + Media Version) →
	dosya adı legacy düzene çevrilir (katman 1 bilerek köreltilir; W3-B'nin
	9 dosyasının dünyası birebir bu).
	"""

	SLOT = "product.image"
	_BAYRAKLAR = ("media_pipeline_enabled", "rendition_on_upload", "active_slots")

	def _png_baytlari(self) -> bytes:
		"""Koşu başına benzersiz PİKSELLİ gerçek PNG.

		Benzersizlik kuyruk baytıyla DEĞİL piksellerle sağlanır: içerik WebP'ye
		yeniden kodlanacak, kuyruk baytı dönüşümü sağ çıkamaz — pikseller çıkar.
		"""
		from PIL import Image

		tohum = hashlib.sha256(self.suffix.encode()).digest()
		im = Image.new("RGB", (64, 64))
		px = im.load()
		for y in range(64):
			for x in range(64):
				px[x, y] = (
					(x * tohum[0] + 7) % 256,
					(y * tohum[1] + 11) % 256,
					((x + y) * tohum[2] + 13) % 256,
				)
		buf = io.BytesIO()
		im.save(buf, "PNG")
		return buf.getvalue()

	def setUp(self) -> None:
		super().setUp()

		# Boru hattı bayrakları: aç, test sonunda ESKİ değerlere döndür.
		orijinal = {a: frappe.db.get_single_value(pipeline_flags.SETTINGS_DOCTYPE, a) for a in self._BAYRAKLAR}

		def _bayraklari_geri_al() -> None:
			for alan, deger in orijinal.items():
				frappe.db.set_single_value(pipeline_flags.SETTINGS_DOCTYPE, alan, deger)
			frappe.db.commit()
			pipeline_flags.clear_cache()

		self.addCleanup(_bayraklari_geri_al)
		frappe.db.set_single_value(pipeline_flags.SETTINGS_DOCTYPE, "media_pipeline_enabled", 1)
		frappe.db.set_single_value(pipeline_flags.SETTINGS_DOCTYPE, "rendition_on_upload", 1)
		frappe.db.set_single_value(pipeline_flags.SETTINGS_DOCTYPE, "active_slots", self.SLOT)
		pipeline_flags.clear_cache()

		# 1) GERÇEK yükleme yolu: PNG gönder, sunucu WebP'ye dönüştürür.
		self.orijinal_png = self._png_baytlari()
		self.sha_orijinal = hashlib.sha256(self.orijinal_png).hexdigest()
		frappe.set_user(self.b_owner)
		try:
			sonuc = uc.upload_media(
				file_name=f"katman2-{self.suffix}.png",
				content=base64.b64encode(self.orijinal_png).decode(),
			)
		finally:
			frappe.set_user("Administrator")
		self.stored_url = sonuc["file_url"]
		self.dosya_adi = frappe.db.get_value("File", {"file_url": self.stored_url}, "name")
		self.addCleanup(lambda: self._drop("File", self.dosya_adi))
		# W7: `_kaydet` dönüşümde orijinal hash için `library.upload` slotlu bir
		# Media Asset açıyor (`files.record_original_hash`) — o da temizlenmeli.
		# LIFO: `_boru_hatti_temizle` (aşağıda kaydediliyor) önce koşar ve boru
		# hattı varlığını çocuklarıyla düşürür; bu genel süpürme kalanı alır.
		self.addCleanup(
			lambda: [
				self._drop("Media Asset", ad)
				for ad in frappe.get_all(
					"Media Asset", filters={"source_file": self.dosya_adi}, pluck="name"
				)
			]
		)

		disk_yolu = frappe.get_site_path("public", self.stored_url.lstrip("/"))
		with open(disk_yolu, "rb") as fh:
			self.saklanan = fh.read()
		self.sha_stored = hashlib.sha256(self.saklanan).hexdigest()

		# ÖN KOŞUL — kusurun kökü gerçekten var: dönüşüm baytları AYIRDI.
		# Ayırmadıysa (to_webp düştü, orijinal saklandı) bu sınıf hiçbir şey
		# ölçmez; burada patla.
		self.assertNotEqual(self.sha_stored, self.sha_orijinal, "dönüşüm olmadı — fixture geçersiz")
		self.assertIn(self.sha_stored[:32], self.stored_url, "saklanan ad içerik-adresli değil")

		# 2) Boru hattı: Listing görseli olarak işle → Media Asset + Version.
		frappe.db.set_value(
			"File",
			self.dosya_adi,
			{"attached_to_doctype": "Listing", "attached_to_field": "primary_image"},
		)
		frappe.db.commit()
		pipeline_bridge._run_rendition_job(self.stored_url)

		self.asset = frappe.db.get_value(
			"Media Asset", {"source_file": self.dosya_adi, "slot_key": self.SLOT}, "name"
		)
		self.assertTrue(self.asset, "boru hattı Media Asset açmadı — fixture geçersiz")
		self.addCleanup(lambda: self._boru_hatti_temizle(self.asset))
		self.assertEqual(
			frappe.db.get_value("Media Asset", self.asset, "owner_seller"),
			self.tenant_b,
			"varlık B'ye yazılmadı — kiracı kemeri ölçülemez",
		)
		self.surum_kaynak_hash = frappe.db.get_value(
			"Media Version", {"asset": self.asset}, "source_hash"
		)
		self.assertEqual(self.surum_kaynak_hash, self.sha_stored)

		# 3) Katman 1'i KÖRELT: adı legacy düzene çevir (W3-B'nin 9 dosyası
		# gibi). Artık ad hash taşımıyor; eşleşme ancak katman 2'den gelebilir.
		self.legacy_url = f"/files/katman2-legacy-{self.suffix}.webp"
		frappe.db.set_value("File", self.dosya_adi, "file_url", self.legacy_url)
		frappe.db.commit()

	def _boru_hatti_temizle(self, asset: str) -> None:
		for rend in frappe.get_all("Media Rendition", filters={"asset": asset}, fields=["name", "file_url"]):
			yol = frappe.get_site_path("public", (rend.file_url or "").lstrip("/"))
			if rend.file_url and os.path.exists(yol):
				os.remove(yol)
			self._drop("Media Rendition", rend.name)
		for job in frappe.get_all("Media Processing Job", filters={"asset": asset}, pluck="name"):
			self._drop("Media Processing Job", job)
		for surum in frappe.get_all("Media Version", filters={"asset": asset}, pluck="name"):
			self._drop("Media Version", surum)
		self._drop("Media Asset", asset)

	# -- ölçümler ---------------------------------------------------------------

	def test_orijinal_hash_artik_ucuncu_katmanda_bulunur(self):
		"""Dönüştürülen görselde ORİJİNAL PNG'nin sha256'sı ARTIK bulunuyor (W7).

		Bu test 2026-08-20'ye kadar boşluğu SABİTLİYORDU ("hiçbir katmanda yok"
		— rapor 64 EK-2) ve kendi docstring'i kırıldığında ne yapılacağını
		söylüyordu: "biri orijinal hash'i saklamaya başlamış demektir; test
		güncellenmeli." O gün geldi — bu bir GEVŞETME değil, davranış değişti:
		`_kaydet` orijinal sha256'yı dönüşümden önce hesaplayıp
		`Media Asset.original_sha256`ya yazıyor (`files.record_original_hash`)
		ve `inventory.find_by_sha256` üçüncü katman olarak oradan arıyor
		(docs/reports/86-w7-upload-kapisi.md).

		İlk iki katman bu fixture'da bilerek kör: ad legacy düzende (katman 1),
		`source_hash` saklanan WebP'nin hash'i (katman 2, kurulumda doğrulandı:
		`sha_stored != sha_orijinal`). Bulan YALNIZ katman 3 olabilir.
		"""
		frappe.set_user(self.b_owner)
		sonuc = uc.find_in_my_library(self.sha_orijinal)
		self.assertTrue(sonuc["found"], "orijinal hash üçüncü katmanda bulunmalıydı")
		self.assertEqual(sonuc["file"]["file_url"], self.legacy_url)
		self.assertTrue(sonuc["file"]["uploaded_at"])

	def test_katman2_islenmis_legacy_dosyayi_bulur(self):
		"""E2E: işlenmiş görselin SAKLANAN baytlarının sha256'sı → found:true.

		Ad legacy düzende (hash taşımıyor) → katman 1 eşleşemez; bulan katman 2.
		Legacy dosyalarda saklanan baytlar = satıcının elindeki orijinal
		(dönüşümsüz saklandılar) — W3-B'nin 9 gerçek dosyası tam bu sınıf.
		"""
		self.assertNotIn(self.sha_stored[:32], self.legacy_url)  # katman 1 kör — ön koşul
		frappe.set_user(self.b_owner)
		sonuc = uc.find_in_my_library(self.sha_stored)
		self.assertTrue(sonuc["found"], "katman 2 işlenmiş dosyayı bulmalıydı")
		self.assertEqual(sonuc["file"]["file_url"], self.legacy_url)
		self.assertTrue(sonuc["file"]["uploaded_at"])

	def test_katman2_kiraci_izolasyonu_vacuity_ve_kirmizi_kanit(self):
		"""B'nin source_hash'i A'ya kapalı; kemer SQL'deki tek engel."""
		# 1) İzolasyon: A sorar, "yok" alır.
		frappe.set_user(self.a_owner)
		self.assertEqual(uc.find_in_my_library(self.sha_stored), {"found": False, "file": None})

		# 2) Vacuity: aynı hash B'de BULUNUR — (1) boş doğru değil.
		frappe.set_user(self.b_owner)
		self.assertTrue(uc.find_in_my_library(self.sha_stored)["found"])

		# 3) Kırmızı kanıt: owner_seller kemeri OLMADAN aynı join satırı bulur —
		#    yani A'yı koruyan tek şey o kemer; gevşetilirse (1) kırmızıya döner.
		frappe.set_user("Administrator")
		v = DocType("Media Version")
		a = DocType("Media Asset")
		kemersiz = (
			frappe.qb.from_(v)
			.join(a)
			.on(a.name == v.asset)
			.select(a.source_file)
			.where(v.source_hash == self.sha_stored)
			.run()
		)
		self.assertEqual(
			[r[0] for r in kemersiz],
			[self.dosya_adi],
			"kemersiz sorgu satırı bulmalıydı — izolasyon testi boş doğru olurdu",
		)
		# Aynı yardımcı, kemerle: A'ya None, B'ye kayıt.
		self.assertIsNone(inventory._find_by_pipeline_source_hash(self.sha_stored, self.tenant_a))  # noqa: SLF001
		self.assertIsNotNone(inventory._find_by_pipeline_source_hash(self.sha_stored, self.tenant_b))  # noqa: SLF001

	def test_katman2_hassas_ikiz_maskesini_deler_mi(self):
		"""Katman 2, envanterin hassas-ikiz maskesini DELEMEZ.

		Saklanan içeriğin private bir ikizi doğunca (canlı örnek: `7m7n6rs4d4`,
		nf.jpg) envanter dosyayı gizler; bu uç da 'kütüphanenizde var' diyerek
		varlığını geri sızdırmamalı — sahibine bile.
		"""
		ikiz = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"katman2-ikiz-{self.suffix}.webp",
				"is_private": 1,
				"content": self.saklanan,
			}
		)
		ikiz.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("File", ikiz.name))

		frappe.set_user(self.b_owner)
		self.assertEqual(uc.find_in_my_library(self.sha_stored), {"found": False, "file": None})
