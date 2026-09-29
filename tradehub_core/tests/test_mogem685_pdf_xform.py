"""MOGEM-685 F-07 — PDF XForm patlaması: `doc_meta` metin çıkarımı sınırlı kalır.

NEDEN VAR: Public PDF yüklemesinde `media/doc_meta.py` her sayfada pypdf
`extract_text()` çağırıyor. Birbirini iki kez çizen 20 katman Form XObject
(4,4 KB) 2^21 çizim yolu eder; pypdf 6.8.0 (kurulu) ve Frappe v15.121.1'in
sabitlediği 6.15.0 bunu > 60 sn dolaşıyordu (CVE-2026-84311, düzeltme 6.16.1)
ve `media-maint` işçisi 180 sn'lik zaman aşımına kadar meşgul kalıyordu.
Frappe yükseltmesi kapatmıyor; önlem `doc_meta._cizim_yolu`.

Ölçüt: 118 gerçek PDF'te sayfa başına en yüksek 2.517 çizim yolu, en derin
2 katman (29 Eyl 2026) — eşik 50.000.
"""

from __future__ import annotations

import time
from unittest import mock

from frappe.tests.utils import FrappeTestCase
from pypdf import PdfReader

from tradehub_core.media import doc_meta
from tradehub_core.tests.test_file_manager_seo import _TUZ, _belge, _sil


def _xform_pdf(katman: int, *, sayfa_sayisi: int = 1, tekrar: int = 2, dongu: bool = False) -> bytes:
	"""Her sayfa `SAYFA<n>` yazar ve bir Form XObject zinciri çizer.

	Zincirde her Form bir sonrakini `tekrar` kez çiziyor; en içteki Form metin
	yazıyor. `dongu=True` iken en içteki Form ilk Form'u çağırır (sonsuz zincir).
	Ham PDF baytı elle kuruluyor — `PdfWriter` Form XObject kurmayı kolaylaştırmıyor
	ve kötü niyetli bir dosya zaten böyle elle yazılır.
	"""
	nesneler: list[bytes] = []

	def ekle(govde: bytes) -> int:
		nesneler.append(govde)
		return len(nesneler)

	def akis(sozluk: bytes, veri: bytes) -> bytes:
		return b"<< " + sozluk + b" /Length %d >>\nstream\n" % len(veri) + veri + b"\nendstream"

	font = ekle(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
	formlar = [0] * (katman + 1)
	# Döngüde ilk Form'un numarası önceden bilinmeli: nesneler sondan başa ekleniyor,
	# X0 en son eklenecek → numarası font + katman + 1.
	x0_no = font + katman + 1
	ic_veri = b"BT /F1 12 Tf 10 10 Td (A) Tj ET" + (b" q /Y Do Q" if dongu else b"")
	ic_kaynak = b"/Font << /F1 %d 0 R >>" % font + (b" /XObject << /Y %d 0 R >>" % x0_no if dongu else b"")
	formlar[katman] = ekle(
		akis(
			b"/Type /XObject /Subtype /Form /BBox [0 0 100 100] /Resources << " + ic_kaynak + b" >>", ic_veri
		)
	)
	for i in range(katman - 1, -1, -1):
		veri = b" ".join([b"q /X Do Q"] * tekrar)
		formlar[i] = ekle(
			akis(
				b"/Type /XObject /Subtype /Form /BBox [0 0 100 100] /Resources << /XObject << /X %d 0 R >> >>"
				% formlar[i + 1],
				veri,
			)
		)
	if not (formlar[0] == x0_no):
		raise RuntimeError("_xform_pdf nesne numarası tutarsız")

	sayfa_nolari = []
	sayfalar_no = len(nesneler) + 2 * sayfa_sayisi + 2
	for n in range(1, sayfa_sayisi + 1):
		veri = b"BT /F1 12 Tf 10 150 Td (SAYFA%d) Tj ET q /X Do Q" % n
		icerik = ekle(akis(b"", veri))
		sayfa_nolari.append(
			ekle(
				b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 200 200] /Contents %d 0 R"
				b" /Resources << /Font << /F1 %d 0 R >> /XObject << /X %d 0 R >> >> >>"
				% (sayfalar_no, icerik, font, formlar[0])
			)
		)
	katalog = ekle(b"<< /Type /Catalog /Pages %d 0 R >>" % sayfalar_no)
	kids = b" ".join(b"%d 0 R" % s for s in sayfa_nolari)
	if not (ekle(b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % sayfa_sayisi) == sayfalar_no):
		raise RuntimeError("_xform_pdf nesne numarası tutarsız")

	cikti = b"%PDF-1.7\n"
	konumlar = []
	for i, govde in enumerate(nesneler, 1):
		konumlar.append(len(cikti))
		cikti += b"%d 0 obj\n" % i + govde + b"\nendobj\n"
	xref = len(cikti)
	cikti += b"xref\n0 %d\n0000000000 65535 f \n" % (len(nesneler) + 1)
	cikti += b"".join(b"%010d 00000 n \n" % k for k in konumlar)
	cikti += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
		len(nesneler) + 1,
		katalog,
		xref,
	)
	return cikti


def _ilk_sayfa_yolu(pdf: bytes, tavan: int) -> int:
	import io

	sayfa = PdfReader(io.BytesIO(pdf)).pages[0]
	return doc_meta._cizim_yolu(sayfa.get_contents().get_data(), sayfa.get("/Resources"), tavan)


class TestCizimYoluSayimi(FrappeTestCase):
	"""`_cizim_yolu` saydığı şeyi doğru sayıyor mu — eşik ancak böyle anlamlı."""

	def test_zincir_katlanarak_sayiliyor(self):
		# Sayfa 1 + X0; X_i = 1 + 2·X_(i+1); en içteki 1 → sayfa = 2^(katman+1).
		for katman in (1, 5, 12):
			self.assertEqual(_ilk_sayfa_yolu(_xform_pdf(katman), 10**9), 2 ** (katman + 1), katman)

	def test_tekrarsiz_zincir_dogrusal(self):
		# Gerçek belgelerdeki desen (logo Form'u içinde başka Form): tekrar 1 → katman + 2.
		self.assertEqual(_ilk_sayfa_yolu(_xform_pdf(8, tekrar=1), 10**9), 10)

	def test_dongu_tavanin_ustunde_sayilir(self):
		# Kendini çağıran zincir pypdf'te sonsuz dolaşma demek — sınırsız kabul edilmeli.
		self.assertGreater(_ilk_sayfa_yolu(_xform_pdf(3, dongu=True), 1000), 1000)

	def test_patlama_hesaplanmadan_kesiliyor(self):
		# 40 katman = 2^41 yol; sayım tavanı aşınca durmalı (patlamanın kendisini hesaplamamalı).
		basla = time.monotonic()
		self.assertGreater(_ilk_sayfa_yolu(_xform_pdf(40), doc_meta.CIZIM_YOLU_SAYFA_TAVANI), 50_000)
		self.assertLess(time.monotonic() - basla, 2.0)


class TestDocMetaXformPatlamasi(FrappeTestCase):
	"""Uçtan uca: gerçek `File` kaydı → `doc_meta.extract` → `apply`."""

	def test_patlama_metni_atlar_sayfa_sayisi_ve_hiz_korunur(self):
		# Ölçülen saldırı dosyası (20 katman): korumasız pypdf 6.8.0 > 60 sn.
		doc = _belge(f"xform-patlama-{_TUZ}.pdf", _xform_pdf(20))
		self.addCleanup(_sil, "File", doc.name)

		basla = time.monotonic()
		sonuc = doc_meta.extract(doc.file_url)
		sure = time.monotonic() - basla

		self.assertLess(sure, 5.0, f"extract {sure:.1f} sn sürdü — XForm koruması çalışmıyor")
		self.assertTrue(sonuc["ok"])
		self.assertTrue(sonuc["metin_atlandi"])
		self.assertEqual(sonuc["page_count"], 1)
		self.assertEqual(sonuc["text"], "")

		# apply sayfa sayısını yazar — dosya "okunamadı" (-1) damgası YEMEZ.
		self.assertTrue(doc_meta.apply(doc.file_url))

	def test_normal_xform_kullanimi_etkilenmez(self):
		# Logo benzeri kullanım: tek katman, 20 kez tekrar → 42 yol; metin çıkarılmalı.
		doc = _belge(f"xform-normal-{_TUZ}.pdf", _xform_pdf(1, tekrar=20, sayfa_sayisi=2))
		self.addCleanup(_sil, "File", doc.name)

		sonuc = doc_meta.extract(doc.file_url)
		self.assertTrue(sonuc["ok"])
		self.assertFalse(sonuc["metin_atlandi"])
		self.assertEqual(sonuc["page_count"], 2)
		self.assertIn("SAYFA1", sonuc["text"])
		self.assertIn("SAYFA2", sonuc["text"])

	def test_bolunmus_saldiri_belge_toplamiyla_kesilir(self):
		# Her sayfa tavanın ALTINDA ama toplam üstünde: 3 sayfa × 2^11 = 6.144 > 5.000.
		doc = _belge(f"xform-bolunmus-{_TUZ}.pdf", _xform_pdf(10, sayfa_sayisi=3))
		self.addCleanup(_sil, "File", doc.name)

		with mock.patch.object(doc_meta, "CIZIM_YOLU_BELGE_TAVANI", 5_000):
			sonuc = doc_meta.extract(doc.file_url)

		self.assertTrue(sonuc["metin_atlandi"])
		self.assertEqual(sonuc["page_count"], 3)
		self.assertIn("SAYFA1", sonuc["text"])
		self.assertIn("SAYFA2", sonuc["text"])
		self.assertNotIn("SAYFA3", sonuc["text"])
