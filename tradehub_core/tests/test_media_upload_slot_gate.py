# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""W7 — `upload_media` slot politikası kapısı (rapor 78 W5-2).

Ölçülen açık: slot kuralları (min kısa kenar 1000, min alan 1 MP, oran) yalnız
İSTEMCİDE koşuyordu; `upload_media`ya doğrudan istek atan 900×900 PNG sunucudan
200 alıyordu (panel E2E S1b bunu `test.fail` ile görünür tutuyordu). Kapı artık
sunucuda: `upload_policy.check_slot` → `pipeline/policy/engine.py::evaluate`.

Testlerin ağırlık merkezi ÜÇ iddia:

  * slot BEYAN EDİLİNCE engelleyici ihlal 417 + kodla reddedilir ve dosya
    YARATILMAZ;
  * slot verilmeyince (genel yükleme) davranış DEĞİŞMEZ — aynı 900×900 kabul
    edilir. Bu aynı zamanda ret testinin KIRMIZI KANITIDIR: reddi üreten tek
    şey slot kapısı, kapı kalkarsa ret testi kırmızıya döner (vacuity);
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

	def test_900x900_product_image_slotunda_reddedilir(self):
		"""S1b'nin sunucu yarısı: 1000×1000 altı + slot → 417 sözleşmesiyle ret.

		Kod `product_image_short_edge_too_small` — panel bu koda bakarak
		düzeltici yönlendirme gösterir; metne bağlanmak çeviriyle kırılırdı.
		"""
		ad = f"w7-under-{self.suffix}.png"
		with self.assertRaises(upload_policy.UploadRejected) as ctx:
			self._yukle(900, 900, slot="product.image", ad=ad)

		# Mesajın sonundaki `[kod]` markörü ve yanıt sözlüğü — istemci sözleşmesi
		# (`upload_policy.reddet` ikisini birden taşır; UploadRejected → HTTP 417).
		self.assertIn("[product_image_short_edge_too_small]", str(ctx.exception))
		self.assertEqual(
			frappe.local.response.get("upload_error"),
			"product_image_short_edge_too_small",
		)
		# Ölçülen ve gereken değer mesajda (düzeltici yönlendirme, S1 sözleşmesi).
		self.assertIn("900", str(ctx.exception))
		self.assertIn("1000", str(ctx.exception))

		# Ret kayıt AÇILMADAN geldi: dosya kütüphaneye girmedi (.png ya da .webp).
		self.assertFalse(
			frappe.get_all("File", filters={"file_name": ["like", f"w7-under-{self.suffix}%"]})
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

		1200×1200: kısa kenar ≥1000, alan ≥1 MP, oran 1:1 → engelleyici ihlal
		yok. Uzun kenar 1200 < `master.min_long_edge` 2000 → `master_under_spec`
		ÜRETİLİR ama aksiyonu `warn` (product-image.json `on_violation.master`)
		— motor kararında `allow=True` kalır, yükleme geçer. Kapı warn'ı redde
		çevirmeye başlarsa bu test kırmızıya döner.
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
