"""Medya denetim kancası — kapsam ve maskeleme (TUR-140).

`media/audit.py:on_file_insert` `File.after_insert`'e bağlı ve "bu dosyayı kim
ne zaman yükledi" sorusunun tek kaynağı. Buradaki testlerin tamamı **kapsam**
sorusunu sınıyor: hangi dosya kayda giriyor, hangisi girmiyor, hassas olan
nasıl maskeleniyor.

Kapsam ölçümle genişletildi: kanca eskiden yalnız 17 görsel/video uzantısını
kaydediyordu ve 653 dosya kayıt dışı kalıyordu — içlerinde 13 KYB doğrulama
belgesi. AV taraması (TUR-125) o belgeleri tarayıp `media.scan` yazdığı için
denetimde "tarandı" satırı olan ama "yüklendi" satırı olmayan dosyalar oluşuyordu.

    docker exec -w /home/frappe/frappe-bench istoc-backend bench \
        --site tradehub.localhost run-tests \
        --module tradehub_core.tests.test_media_audit
"""

from __future__ import annotations

import contextlib
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import audit

_TUZ: str = frappe.generate_hash(length=12)


def _sil(name: str) -> None:
	"""Kaydı sil ve COMMIT et — kanca commit'lediği için rollback yetmiyor."""
	with contextlib.suppress(Exception):
		frappe.delete_doc("File", name, ignore_permissions=True, force=True)
		frappe.db.commit()


class _DenetimTemeli(FrappeTestCase):
	"""Kancayı yakalar; gerçek ADL yazımı yapılmaz.

	AV kancası da aynı insert'te koşuyor ve dosyayı bekletmeye taşıyabiliyor —
	burada ölçülen o değil, nötrleniyor.
	"""

	def setUp(self):
		self.olaylar: list[dict] = []

		def _yakala(**kwargs):
			self.olaylar.append(kwargs)
			return "ADL-TEST"

		y = mock.patch("tradehub_core.media.audit.log_media_event", side_effect=_yakala)
		y.start()
		self.addCleanup(y.stop)

		for hedef in ("maybe_scan_on_insert",):
			z = mock.patch(f"tradehub_core.media.av.{hedef}")
			z.start()
			self.addCleanup(z.stop)

	def _yukle(self, ad: str, *, private: bool = False, attached: str | None = None):
		alanlar = {
			"doctype": "File",
			"file_name": ad,
			"is_private": 1 if private else 0,
			"content": f"icerik {_TUZ} {ad}".encode(),
		}
		if attached:
			alanlar["attached_to_doctype"] = attached
			alanlar["attached_to_name"] = "TEST-KAYIT-1"
		doc = frappe.get_doc(alanlar)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: _sil(doc.name))
		return doc

	@property
	def yukleme_olaylari(self) -> list[dict]:
		return [o for o in self.olaylar if o.get("action") == audit.ACTION_UPLOAD]


class TestKapsam(_DenetimTemeli):
	"""Hangi dosya denetime giriyor."""

	def test_gorsel_kayda_girer(self):
		self._yukle(f"gorsel-{_TUZ}.mp4")
		self.assertEqual(len(self.yukleme_olaylari), 1)
		self.assertEqual(self.yukleme_olaylari[0]["context"]["kind"], "media")

	def test_BELGE_kayda_girer(self):
		"""Asıl düzeltme: belgeler eskiden hiç kaydedilmiyordu.

		Uzantı olarak `.pdf` KULLANILMIYOR: Frappe PDF içeriğini pypdf ile açıp
		gömülü JS arıyor (`check_content`) ve sahte bayt reddediliyor. Ölçülen
		şey uzantı SINIFI (medya değil → belge), dosyanın gerçekten çözülebilir
		olması değil.
		"""
		self._yukle(f"belge-{_TUZ}.txt")
		self.assertEqual(len(self.yukleme_olaylari), 1, "belge yüklemesi denetime girmeli")
		self.assertEqual(self.yukleme_olaylari[0]["context"]["kind"], "document")

	def test_bilinmeyen_uzanti_da_kayda_girer(self):
		# Kapsamı listeyle daraltmak, listeye eklenmeyen her yeni türü sessizce
		# kayıt dışı bırakırdı. Liste artık kaydı DÜŞÜRMÜYOR.
		self._yukle(f"veri-{_TUZ}.parquet")
		self.assertEqual(len(self.yukleme_olaylari), 1)
		self.assertEqual(self.yukleme_olaylari[0]["context"]["kind"], "document")

	def test_klasor_kayda_girmez(self):
		doc = frappe.get_doc(
			{"doctype": "File", "file_name": f"klasor-{_TUZ}", "is_folder": 1}
		)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: _sil(doc.name))
		self.assertEqual(self.yukleme_olaylari, [], "klasörde taranacak içerik yok")

    # Kanca best-effort: burada patlamak yüklemeyi ENGELLEMEMELİ.
	def test_kanca_patlarsa_yukleme_devam_eder(self):
		with mock.patch(
			"tradehub_core.media.audit.log_media_event", side_effect=Exception("adl düştü")
		):
			doc = self._yukle(f"dayanikli-{_TUZ}.mp4")
		self.assertTrue(frappe.db.exists("File", doc.name))


class TestMaskeleme(_DenetimTemeli):
	"""Hassas dosya KAYDA GİRER ama kimliği yazılmaz."""

	def test_private_dosya_maskeli_yazilir(self):
		self._yukle(f"gizli-{_TUZ}.txt", private=True)
		olay = self.yukleme_olaylari[0]
		self.assertTrue(olay["sensitive"], "private dosya maskelenmeli")

	def test_KYB_belgesi_kayda_girer_ve_maskelenir(self):
		"""Sistemin en hassas kategorisi: eskiden HİÇ kaydedilmiyordu."""
		from tradehub_core.media.presets import EXCLUDED_DOCTYPES

		hassas_doctype = sorted(EXCLUDED_DOCTYPES)[0]
		self._yukle(f"kyb-{_TUZ}.txt", attached=hassas_doctype)

		self.assertEqual(len(self.yukleme_olaylari), 1, "KYB belgesi denetime girmeli")
		self.assertTrue(self.yukleme_olaylari[0]["sensitive"], "adresi kayda geçmemeli")


class TestIcerikIkiziMaliyeti(_DenetimTemeli):
	"""Pahalı kontrol yalnız gerektiği yerde koşar.

	`content_hash` indeksli değil; her belge yüklemesine tam tablo taraması
	eklemek toplu içe aktarımda ölçülebilir maliyet olurdu. Kontrolün amacı
	görsel sızıntısıydı, kapsamı da orada kalıyor.

	Not: medya örneği olarak `.mp4` kullanılıyor — Frappe görsel içerik
	türlerinde `strip_exif_data` çağırıyor ve sahte bayt Pillow'da patlıyor.
	Ölçülen şey uzantı sınıfı, dosyanın gerçekten çözülebilir olması değil.
	"""

	def test_belgede_ikiz_taramasi_KOSMAZ(self):
		with mock.patch(
			"tradehub_core.media.runner._has_sensitive_twin", return_value=False
		) as ikiz:
			self._yukle(f"maliyet-{_TUZ}.txt")
		ikiz.assert_not_called()

	def test_public_eksiz_gorselde_ikiz_taramasi_kosar(self):
		with mock.patch(
			"tradehub_core.media.runner._has_sensitive_twin", return_value=False
		) as ikiz:
			self._yukle(f"maliyet-{_TUZ}.mp4")
		ikiz.assert_called_once()


if __name__ == "__main__":
	import unittest

	unittest.main()
