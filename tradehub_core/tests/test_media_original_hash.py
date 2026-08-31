# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""W7 — orijinal içerik hash'i: kayıt (`files.record_original_hash`) ve arama
(`inventory._find_by_original_hash`, tekilleştirmenin 3. katmanı).

Kapatılan boşluk (rapor 64 EK-2): `_kaydet` görseli `File.insert`ten ÖNCE
WebP'ye çeviriyor; istemcinin ORİJİNAL dosyadan hesapladığı sha256 hiçbir
kayıtta yoktu — dönüştürülen her görselde tekilleştirme uyarısı yapısal olarak
imkânsızdı. Artık hash dönüşümden önce hesaplanıp `Media Asset.original_sha256`
alanına yazılıyor (alanın YER seçiminin gerekçesi `files.record_original_hash`
docstring'inde) ve `find_by_sha256` üçüncü katman olarak oradan arıyor.

Desen `test_media_dedup_endpoint` ile aynı: izolasyon + vacuity kanıtı +
kırmızı kanıt (kemersiz sorgu bulur) — boş doğru test yok.

BORU HATTI BAYRAKLARINA DOKUNULMAZ: bu katman bayraktan bağımsız çalışmak
zorunda (dedup uyarısı, operatör türev üretimini kapattı diye ölmemeli) —
testler bayrak açmadan koşar ve bu bağımsızlığın kendisini ölçer.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_original_hash
"""

from __future__ import annotations

import base64
import hashlib
import io

import frappe
from frappe.query_builder import DocType

from tradehub_core.api import seller_media as uc
from tradehub_core.media import files, inventory

# Tarama kancası bu modülde nötrleniyor: `hold_until_clean` açıkken dosya
# insert anında public ağaçtan çıkarılıyor ve diskten okuyan testler
# `FileNotFoundError` alıyor. Gerekçe `tests/av_notr.py` başlığında.
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401
from tradehub_core.tests.test_media_dedup_endpoint import _DedupUcuTesti


def _pikselli_png(tohum_metni: str) -> bytes:
	"""Koşu başına benzersiz PİKSELLİ PNG — benzersizlik kuyruk baytıyla değil
	piksellerle: içerik WebP'ye yeniden kodlanacak, kuyruk baytı dönüşümü sağ
	çıkamaz (test_media_dedup_endpoint._png_baytlari ile aynı gerekçe)."""
	from PIL import Image

	tohum = hashlib.sha256(tohum_metni.encode()).digest()
	im = Image.new("RGB", (48, 48))
	px = im.load()
	for y in range(48):
		for x in range(48):
			px[x, y] = (
				(x * tohum[0] + 3) % 256,
				(y * tohum[1] + 5) % 256,
				((x + y) * tohum[2] + 7) % 256,
			)
	buf = io.BytesIO()
	im.save(buf, "PNG")
	return buf.getvalue()


class TestOrijinalHashKatman3(_DedupUcuTesti):
	def setUp(self) -> None:
		super().setUp()

		# GERÇEK yükleme yolu, SLOTSUZ (genel kütüphane yüklemesi): PNG gönder,
		# sunucu WebP'ye dönüştürür. Boru hattı bayrakları AÇILMAZ.
		self.orijinal_png = _pikselli_png(f"w7-{self.suffix}")
		self.sha_orijinal = hashlib.sha256(self.orijinal_png).hexdigest()
		frappe.set_user(self.b_owner)
		try:
			sonuc = uc.upload_media(
				file_name=f"w7-orijinal-{self.suffix}.png",
				content=base64.b64encode(self.orijinal_png).decode(),
			)
		finally:
			frappe.set_user("Administrator")
		self.stored_url = sonuc["file_url"]
		self.dosya_adi = frappe.db.get_value("File", {"file_url": self.stored_url}, "name")
		self.addCleanup(lambda: self._varliklari_temizle(self.dosya_adi))
		# Aynı adrese birden çok File kaydı düşebilir (ikinci-yükleme testi;
		# Frappe içerik imzası eşleşince yeni fiziksel dosya yazmaz) — adresle süpür.
		self.addCleanup(
			lambda: [
				self._drop("File", ad)
				for ad in frappe.get_all("File", filters={"file_url": self.stored_url}, pluck="name")
			]
		)

		# ÖN KOŞUL 1 — dönüşüm baytları gerçekten ayırdı; ayırmadıysa katman 1
		# orijinali addan bulur ve bu sınıf hiçbir şey ölçmez.
		with open(frappe.get_site_path("public", self.stored_url.lstrip("/")), "rb") as fh:
			self.saklanan = fh.read()
		self.assertNotEqual(
			hashlib.sha256(self.saklanan).hexdigest(),
			self.sha_orijinal,
			"dönüşüm olmadı — fixture geçersiz",
		)

		# ÖN KOŞUL 2 — kolon var (patch koşmuş); yoksa kayıt da arama da
		# bilinçli no-op ve testler yanlış sebepten kırmızı olur.
		self.assertTrue(
			frappe.db.has_column("Media Asset", "original_sha256"),
			"original_sha256 kolonu yok — v15_9_34 patch'i koşmamış",
		)

	def _varliklari_temizle(self, dosya_adi: str) -> None:
		for ad in frappe.get_all("Media Asset", filters={"source_file": dosya_adi}, pluck="name"):
			self._drop("Media Asset", ad)

	def _varlik(self) -> dict | None:
		satirlar = frappe.get_all(
			"Media Asset",
			filters={"source_file": self.dosya_adi, "slot_key": files.LIBRARY_UPLOAD_SLOT},
			fields=["name", "state", "owner_seller", "content_sha256", "original_sha256"],
		)
		return satirlar[0] if satirlar else None

	# -- kayıt --------------------------------------------------------------------

	def test_kayit_dogru_varliga_dogru_alanlarla_yazildi(self):
		"""`record_original_hash` sözleşmesi: draft varlık, kiracı kemeri, iki
		ayrı kimlik (orijinal 64 hex / saklanan 32 hex) karışmadan."""
		varlik = self._varlik()
		self.assertIsNotNone(varlik, "yükleme Media Asset açmadı")
		self.assertEqual(varlik["state"], "draft")
		self.assertEqual(varlik["owner_seller"], self.tenant_b)
		self.assertEqual(varlik["original_sha256"], self.sha_orijinal)
		self.assertEqual(
			varlik["content_sha256"],
			hashlib.sha256(self.saklanan).hexdigest()[:32],
			"content_sha256 SAKLANAN baytların kısaltması olmalı — kimlikler karışmış",
		)

	def test_ayni_iceriginin_ikinci_yuklemesi_ikinci_varlik_acmaz(self):
		"""Upsert: aynı (satıcı, slot, içerik) üçlüsü tek varlıkta kalır —
		`asset_key` tekilliği ve yarış dalı (`INV-06` deseni) boş doğru değil."""
		frappe.set_user(self.b_owner)
		try:
			uc.upload_media(
				file_name=f"w7-tekrar-{self.suffix}.png",
				content=base64.b64encode(self.orijinal_png).decode(),
			)
		finally:
			frappe.set_user("Administrator")
		# İkinci yükleme aynı içerik-adresli adrese düşer; yeni File kaydı da
		# aynı source-of-truth'u gösterir. Varlık sayısı hâlâ 1 olmalı.
		varliklar = frappe.get_all(
			"Media Asset",
			filters={
				"owner_seller": self.tenant_b,
				"slot_key": files.LIBRARY_UPLOAD_SLOT,
				"original_sha256": self.sha_orijinal,
			},
			pluck="name",
		)
		self.assertEqual(len(varliklar), 1, f"üçlü tekilliği kırıldı: {varliklar}")

	# -- arama (katman 3) ----------------------------------------------------------

	def test_orijinal_hash_ile_bulunur(self):
		"""E2E: ORİJİNAL baytların sha256'sı → found:true, saklanan adres.

		Katman 1 kör (ad SAKLANAN hash'i taşıyor, orijinali değil), katman 2 yok
		(boru hattı koşmadı, Media Version açılmadı) — bulan yalnız katman 3.
		"""
		self.assertNotIn(self.sha_orijinal[:32], self.stored_url)  # katman 1 kör — ön koşul
		self.assertFalse(
			frappe.get_all("Media Version", filters={"source_hash": self.sha_orijinal})
		)  # katman 2 kör — ön koşul

		frappe.set_user(self.b_owner)
		sonuc = uc.find_in_my_library(self.sha_orijinal)
		self.assertTrue(sonuc["found"], "orijinal hash 3. katmanda bulunmalıydı")
		self.assertEqual(sonuc["file"]["file_url"], self.stored_url)
		self.assertTrue(sonuc["file"]["uploaded_at"])

	def test_kiraci_izolasyonu_vacuity_ve_kirmizi_kanit(self):
		"""B'nin orijinal hash'i A'ya kapalı; kemer SQL'deki tek engel."""
		# 1) İzolasyon: A sorar, "yok" alır — varlığı da sızmaz.
		frappe.set_user(self.a_owner)
		self.assertEqual(
			uc.find_in_my_library(self.sha_orijinal), {"found": False, "file": None}
		)

		# 2) Vacuity: aynı hash B'de BULUNUR — (1) boş doğru değil.
		frappe.set_user(self.b_owner)
		self.assertTrue(uc.find_in_my_library(self.sha_orijinal)["found"])

		# 3) Kırmızı kanıt: owner_seller kemeri OLMADAN aynı sorgu satırı bulur —
		#    A'yı koruyan tek şey o kemer; gevşetilirse (1) kırmızıya döner.
		frappe.set_user("Administrator")
		a = DocType("Media Asset")
		kemersiz = (
			frappe.qb.from_(a)
			.select(a.source_file)
			.where(a.original_sha256 == self.sha_orijinal)
			.run()
		)
		self.assertEqual(
			[r[0] for r in kemersiz],
			[self.dosya_adi],
			"kemersiz sorgu satırı bulmalıydı — izolasyon testi boş doğru olurdu",
		)
		# Aynı yardımcı, kemerle: A'ya None, B'ye kayıt.
		self.assertIsNone(inventory._find_by_original_hash(self.sha_orijinal, self.tenant_a))  # noqa: SLF001
		self.assertIsNotNone(inventory._find_by_original_hash(self.sha_orijinal, self.tenant_b))  # noqa: SLF001

	def test_copteki_dosya_bulunmaz(self):
		"""Çöpe bırakılan dosyayı katman 3 de geri sızdırmaz — hijyen kemeri
		(`_kaynak_dosya_cevabi`) katman 2 ile ortak, kanıtı bu test."""
		frappe.set_user(self.b_owner)
		self.assertTrue(uc.find_in_my_library(self.sha_orijinal)["found"])  # önce bulunuyor

		frappe.set_user("Administrator")
		frappe.db.set_value("File", self.dosya_adi, "th_trashed_at", frappe.utils.now_datetime())
		frappe.db.commit()

		frappe.set_user(self.b_owner)
		self.assertEqual(
			uc.find_in_my_library(self.sha_orijinal), {"found": False, "file": None}
		)

	def test_hassas_ikiz_maskesini_delmez(self):
		"""Saklanan içeriğin private ikizi doğunca katman 3 de susar — envanterin
		gizlediği dosyayı 'kütüphanenizde var' diye geri sızdırmak sızıntıdır
		(katman 2'deki canlı örnekle aynı kural: `7m7n6rs4d4`)."""
		ikiz = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"w7-ikiz-{self.suffix}.webp",
				"is_private": 1,
				"content": self.saklanan,
			}
		)
		ikiz.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("File", ikiz.name))

		frappe.set_user(self.b_owner)
		self.assertEqual(
			uc.find_in_my_library(self.sha_orijinal), {"found": False, "file": None}
		)
