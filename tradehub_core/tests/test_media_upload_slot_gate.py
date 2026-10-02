# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""W7 — `upload_media` slot politikası kapısı (rapor 78 W5-2).

Ölçülen açık: slot kuralları (min kısa kenar 1000, min alan 1 MP, oran) yalnız
İSTEMCİDE koşuyordu; `upload_media`ya doğrudan istek atan 900×900 PNG sunucudan
200 alıyordu (panel E2E S1b bunu `test.fail` ile görünür tutuyordu). Kapı artık
sunucuda: `upload_policy.check_slot` → `pipeline/policy/engine.py::evaluate`.

GÜNCELLENDİ 2026-09-29 (kare kuralı): `product.image` slotunda kısa kenar/alan/
oran RET kapısı (`require.{min_short_edge,min_area,allowed_ratios,ratio_tolerance}`)
KALDIRILDI — ürüne bağlanan görsel artık kare 1000–2000 px beyaz dolguya
otomatik çevriliyor (media/kare.py), küçük/oransız girdiyi reddetmenin gerekçesi
kalmadı. 900×900 artık `product.image` slotuyla da KABUL edilir (aşağıdaki
`test_900x900_product_image_slotunda_artik_kabul_edilir`). Kapının VACUOUS
olmadığının kanıtı artık boyut değil biçim kapısıdır (`test_gif_product_image_slotunda_reddedilir`)
ve bilinmeyen slot reddi (`test_bilinmeyen_slot_reddedilir`).

Testlerin ağırlık merkezi ÜÇ iddia:

  * slot BEYAN EDİLİNCE hâlâ engelleyici bir ihlal olursa (biçim, decompression-
    bomb, bilinmeyen slot, ...) 417 + kodla reddedilir ve dosya YARATILMAZ;
  * slot verilmeyince (genel yükleme) davranış DEĞİŞMEZ — aynı 900×900 kabul
    edilir;
  * `warn` aksiyonlu ihlal (ör. `master_under_spec`) REDDETMEZ.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_upload_slot_gate
"""

from __future__ import annotations

import base64
import io

import frappe

from tradehub_core.api import seller_media as uc
from tradehub_core.media import upload_policy
from tradehub_core.tests.test_media_dedup_endpoint import _DedupUcuTesti


def _png(w: int, h: int) -> bytes:
	"""Verilen ölçüde gerçek bir PNG — kapının ölçeceği şey başlıktaki ölçü."""
	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", (w, h), (120, 40, 200)).save(buf, "PNG")
	return buf.getvalue()


class TestUploadSlotKapisi(_DedupUcuTesti):
	"""Fixture `_DedupUcuTesti`den (satıcı A/B + temizlik) — kopya değil, ortak."""

	def _yukle(self, w: int, h: int, *, slot: str = "", ad: str = "") -> dict:
		frappe.set_user(self.b_owner)
		try:
			return uc.upload_media(
				file_name=ad or f"w7-gate-{w}x{h}-{self.suffix}.png",
				content=base64.b64encode(_png(w, h)).decode(),
				slot=slot,
			)
		finally:
			frappe.set_user("Administrator")

	def _dosya_temizle(self, file_url: str) -> None:
		"""Yüklemenin File kaydı + W7'nin açtığı Media Asset kayıtları."""
		for ad in frappe.get_all("File", filters={"file_url": file_url}, pluck="name"):
			for varlik in frappe.get_all("Media Asset", filters={"source_file": ad}, pluck="name"):
				self._drop("Media Asset", varlik)
			self._drop("File", ad)

	# -- ret: sunucu kapısı ------------------------------------------------------

	def test_900x900_product_image_slotunda_artik_kabul_edilir(self):
		"""2026-09-29 kare kuralı: reddetme yok. ÖNCEDEN (S1b sunucu yarısı) bu
		1000×1000 altı + slot → 417 `product_image_short_edge_too_small` ile
		reddediliyordu. Ürüne bağlanan görsel artık kare 1000–2000 px beyaz
		dolguya otomatik çevrildiği için (media/kare.py) bu ret kapısı
		kaldırıldı; vektör (900×900 PNG + `product.image` slotu) SİLİNMEDİ,
		yalnız beklenen sonuç KABUL'e çevrildi.
		"""
		ad = f"w7-under-{self.suffix}.png"
		sonuc = self._yukle(900, 900, slot="product.image", ad=ad)
		self.assertTrue(sonuc["file_url"])
		self.addCleanup(lambda: self._dosya_temizle(sonuc["file_url"]))

	def test_gif_product_image_slotunda_reddedilir(self):
		"""Sunucu kapısının hâlâ VACUOUS olmadığının kanıtı (bkz. modül dosya
		başı notu): boyut/oran RET'i kaldırıldı ama biçim kapısı (accept.mime/
		extensions) duruyor — product-image.json GIF kabul etmiyor.
		"""
		from PIL import Image

		buf = io.BytesIO()
		Image.new("RGB", (1200, 1200), (10, 200, 40)).save(buf, "GIF")
		ad = f"w7-format-{self.suffix}.gif"
		frappe.set_user(self.b_owner)
		try:
			with self.assertRaises(upload_policy.UploadRejected) as ctx:
				uc.upload_media(
					file_name=ad,
					content=base64.b64encode(buf.getvalue()).decode(),
					slot="product.image",
				)
		finally:
			frappe.set_user("Administrator")
		self.assertIn("product_image_", str(ctx.exception))
		self.assertFalse(
			frappe.get_all("File", filters={"file_name": ["like", f"w7-format-{self.suffix}%"]})
		)

	def test_bilinmeyen_slot_reddedilir(self):
		"""Bozuk slot beyanı kapıyı ATLAMAZ — açık ret (`upload_slot_unknown`).

		Sessizce yok saymak, `slot=xyz` yazan bir istemcinin tüm slot kurallarını
		devre dışı bırakması demekti.
		"""
		with self.assertRaises(upload_policy.UploadRejected) as ctx:
			self._yukle(1200, 1200, slot="boyle.bir.slot.yok")
		self.assertIn("[upload_slot_unknown]", str(ctx.exception))

	# -- kabul: eski davranış + warn --------------------------------------------

	def test_slotsuz_yukleme_eski_davranista_kirmizi_kanit(self):
		"""AYNI 900×900 dosya slot beyanı olmadan KABUL edilir.

		İki şeyi birden ölçer: (1) genel kütüphane yüklemesinin davranışı
		değişmedi; (2) yukarıdaki ret testi boş doğru değil — 900×900'ü düşüren
		tek şey slot kapısı. `check_slot` çağrısı `_kaydet`ten kaldırılırsa ret
		testi kırmızıya döner, bu test yeşil kalır.
		"""
		sonuc = self._yukle(900, 900)
		self.assertTrue(sonuc["file_url"])
		self.addCleanup(lambda: self._dosya_temizle(sonuc["file_url"]))

	def test_1200x1200_slotla_kabul_ve_warn_reddetmez(self):
		"""Kurala uyan dosya slotla da kabul edilir; `warn` engel değildir.

		GÜNCELLENDİ 2026-09-29 (kare kuralı): `master.min_long_edge` 2000 → 1000
		indi, bu yüzden 1200 px artık `master_under_spec` bile ÜRETMİYOR — direkt
		`allow=True`, sessiz kabul. Testin kendisi hâlâ geçerli bir 'warn asla
		reddetmez' kanıtıdır (bkz. `test_900x900_product_image_slotunda_artik_kabul_edilir`
		için de artık aynı hikâye geçerli); yalnız docstring'teki eski 'master_under_spec
		ÜRETİLİR' iddiası artık YANLIŞ olduğu için düzeltildi.
		"""
		sonuc = self._yukle(1200, 1200, slot="product.image")
		self.assertTrue(sonuc["file_url"])
		self.addCleanup(lambda: self._dosya_temizle(sonuc["file_url"]))

	# -- motor girdisi -----------------------------------------------------------

	def test_kunye_pillow_suz_ve_dogru_olculu(self):
		"""Kapının künyesi başlıktan gelir (`declared_dimensions`) — decode yok.

		Motorun reddi de kabulü de bu ölçüye dayandığı için ölçünün kendisi ayrı
		doğrulanır; yanlış ölçü kapıyı sessizce köreltirdi.
		"""
		kunye = upload_policy._slot_probe("t.png", _png(900, 640))  # noqa: SLF001 — bilinçli: kapının kendi künyesi
		self.assertEqual((kunye["width"], kunye["height"]), (900, 640))
		self.assertEqual(kunye["detected"], "png")
		self.assertEqual(kunye["mime"], "image/png")
