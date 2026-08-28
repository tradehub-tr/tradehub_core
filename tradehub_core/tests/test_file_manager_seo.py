"""Dosya Yöneticisi SEO — `Listing Document` child + `File` doküman alanları (Task 1).

Karar belgesi: `.superpowers/sdd/2026-08-27-file-manager-seo/task-1-brief.md`.

Bu dosyanın sabitlediği kurallar:
  1. `th_media_page_count`/`th_media_extracted_text` kolonları `File`'da var
  2. `fields_for` bu iki anahtarı (`page_count`, `extracted_text`) döndürür
  3. İkisi de beyaz listede DEĞİL — `set_asset_fields`'tan yazılamaz
     (width/height, duration/poster_url ile aynı özel-durum deseni)
  4. `Listing Document` child'ı mevcut bir `Listing`'e append+save ile yazılabilir

Koşum:
    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_file_manager_seo
"""

from __future__ import annotations

import contextlib
import io
import struct
import tempfile
import zipfile
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import doc_meta, seo, seo_audit
from tradehub_core.tests.test_media_video_seo import _iki_gorunur_ilan
from tradehub_core.tests.test_media_watch import _gorunur_ilan

_TUZ: str = frappe.generate_hash(length=10)


def _dosya(ad: str, *, icerik: bytes | None = None):
	"""Gerçek `File` — tarama kancası nötr (test_media_seo deseni)."""
	veri = icerik if icerik is not None else f"filedoc {_TUZ} {ad}".encode()
	with mock.patch("tradehub_core.media.av.enqueue_scan"):
		doc = frappe.get_doc({"doctype": "File", "file_name": ad, "is_private": 0, "content": veri})
		doc.insert(ignore_permissions=True)
	return doc


def _belge(ad: str, icerik: bytes):
	"""Doküman fixture'ı — `_dosya` ile aynı gerekçe (tarama kancası nötr) +
	`frappe.enqueue`'u da nötrler: `doc_meta.maybe_extract_on_insert` artık
	`.pdf/.docx/.xlsx/.pptx` uzantısında gerçek kuyruğa iş atıyor
	(`enqueue_after_commit=True` — test transaction'ı commit etmediği sürece
	zaten tetiklenmez, ama açıkça mock'lamak testi bu varsayıma bağımlı
	bırakmıyor)."""
	with mock.patch("tradehub_core.media.av.enqueue_scan"), mock.patch("frappe.enqueue"):
		doc = frappe.get_doc({"doctype": "File", "file_name": ad, "is_private": 0, "content": icerik})
		doc.insert(ignore_permissions=True)
	return doc


def _pdf_bytes(sayfa_metinleri: list[str], *, title: str | None = None, encrypt: str | None = None) -> bytes:
	"""Gerçek, ayrıştırılabilir PDF — `pypdf.PdfWriter` ile (Step 1 fixture'ı,
	`tests/test_media_inventory_filters.py:96` örneğinin genişletilmişi).

	`PdfWriter.add_blank_page` metin YAZMAZ; her sayfaya elle bir içerik akışı
	(`BT ... Tj ET`) ekleniyor ki `extract_text()` gerçekten bir şey döndürsün.
	Metinler yalnız ASCII — PDF string literal'i (parantez/backslash) ve
	latin-1 kodlaması karmaşıklaştırmasın diye.
	"""
	from pypdf import PdfWriter
	from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

	writer = PdfWriter()
	for metin in sayfa_metinleri:
		sayfa = writer.add_blank_page(width=300, height=300)
		font = DictionaryObject()
		font[NameObject("/Type")] = NameObject("/Font")
		font[NameObject("/Subtype")] = NameObject("/Type1")
		font[NameObject("/BaseFont")] = NameObject("/Helvetica")
		font_ref = writer._add_object(font)
		fontlar = DictionaryObject()
		fontlar[NameObject("/F1")] = font_ref
		kaynaklar = DictionaryObject()
		kaynaklar[NameObject("/Font")] = fontlar
		sayfa[NameObject("/Resources")] = kaynaklar

		icerik = f"BT /F1 12 Tf 10 100 Td ({metin}) Tj ET".encode("latin-1")
		akis = DecodedStreamObject()
		akis.set_data(icerik)
		sayfa.replace_contents(akis)

	if title:
		writer.add_metadata({"/Title": title})
	if encrypt:
		writer.encrypt(encrypt)

	buf = io.BytesIO()
	writer.write(buf)
	return buf.getvalue()


_DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_CONTENT_TYPES_XML = (
	'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
	'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
	'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
	'<Default Extension="xml" ContentType="application/xml"/>'
	"</Types>"
)


def _docx_bytes(paragraflar: list[str]) -> bytes:
	"""Minimal geçerli docx — `[Content_Types].xml` + `word/document.xml`
	(Step 1 fixture tarifi: `w:t` namespace'li düğümler, N paragraf)."""
	govde = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraflar)
	document = (
		'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
		f'<w:document xmlns:w="{_DOCX_NS}"><w:body>{govde}</w:body></w:document>'
	)
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w") as zf:
		zf.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
		zf.writestr("word/document.xml", document)
	return buf.getvalue()


def _xlsx_bytes(dizgiler: list[str]) -> bytes:
	"""Minimal geçerli xlsx — `xl/sharedStrings.xml` (Step 1 fixture tarifi:
	N string, namespace'li `t` düğümleri)."""
	ogeler = "".join(f"<si><t>{s}</t></si>" for s in dizgiler)
	shared = (
		'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
		f'<sst xmlns="{_XLSX_NS}" count="{len(dizgiler)}" uniqueCount="{len(dizgiler)}">{ogeler}</sst>'
	)
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w") as zf:
		zf.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
		zf.writestr("xl/sharedStrings.xml", shared)
	return buf.getvalue()


_PPTX_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PPTX_PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _pptx_bytes(slayt_metinleri: list[str]) -> bytes:
	"""Minimal geçerli pptx — `ppt/slides/slideN.xml` (namespace'li `a:t`
	düğümleri, minor (b) — düzeltme turu 1)."""
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w") as zf:
		zf.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
		for i, metin in enumerate(slayt_metinleri, start=1):
			slide = (
				'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
				f'<p:sld xmlns:a="{_PPTX_DRAWING_NS}" xmlns:p="{_PPTX_PRESENTATION_NS}">'
				"<p:cSld><p:spTree><p:sp><p:txBody>"
				f"<a:p><a:r><a:t>{metin}</a:t></a:r></a:p>"
				"</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
			)
			zf.writestr(f"ppt/slides/slide{i}.xml", slide)
	return buf.getvalue()


def _zip_bomb_docx(uye_boyutu: int) -> bytes:
	"""Sıkıştırılmış hâli küçük, decompress'te `uye_boyutu` bayta şişen sahte
	docx — klasik zip-bomb (tekrarlı sıfır bloğu, `ZIP_DEFLATED` ile bayt
	sayısı diskte küçük kalır). IMPORTANT #1 — düzeltme turu 1."""
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
		zf.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
		zf.writestr("word/document.xml", b"\x00" * uye_boyutu)
	return buf.getvalue()


def _zip_bomb_spoofed_docx(gercek_boyut: int, beyan_boyut: int = 100) -> bytes:
	"""Sahte-küçük BEYAN edilmiş, gerçek boyutu devasa bir docx — IMPORTANT #1
	turu 2'de re-review'un CANLI KANITLADIĞI bypass'ın ta kendisi.

	`zf.getinfo(member).file_size` (local file header + merkezi dizin
	kaydındaki "uncompressed size" alanı) saldırganın kontrolündeki, doğrulanmamış
	metadata'dır. Burada `struct.pack_into` ile elle `beyan_boyut`'a küçültülüyor;
	gerçek deflate akışı ise `gercek_boyut` bayta şişiyor (PKZIP spec: bu alan
	her iki kayıtta da dosya adından hemen ÖNCE — local header'da -8, merkezi
	dizin kaydında -22 bayt ofsette, 4 bayt little-endian)."""
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
		zf.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
		zf.writestr("word/document.xml", b"\x00" * gercek_boyut)
	veri = bytearray(buf.getvalue())

	hedef = b"word/document.xml"
	yerel_ad = veri.find(hedef)
	struct.pack_into("<I", veri, yerel_ad - 8, beyan_boyut)
	merkezi_ad = veri.find(hedef, yerel_ad + len(hedef))
	struct.pack_into("<I", veri, merkezi_ad - 22, beyan_boyut)
	return bytes(veri)


def _entity_bomb_docx() -> bytes:
	"""DOCTYPE/ENTITY bildirimi taşıyan sahte docx — billion-laughs önlemi
	ayrıştırmadan ÖNCE reddetmeli. IMPORTANT #1 — düzeltme turu 1."""
	document = (
		'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
		'<!DOCTYPE lolz [<!ENTITY lol "lol">]>'
		f'<w:document xmlns:w="{_DOCX_NS}"><w:body><w:p><w:r><w:t>&lol;</w:t></w:r></w:p></w:body></w:document>'
	)
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w") as zf:
		zf.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
		zf.writestr("word/document.xml", document)
	return buf.getvalue()


def _sil(doctype: str, name: str) -> None:
	with contextlib.suppress(Exception):
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		frappe.db.commit()


class TestDosyaSemasi(FrappeTestCase):
	def test_kolonlar_var(self):
		"""`v15_9_52_file_doc_fields` yaması sonrası kolonlar `File`'da olmalı."""
		self.assertTrue(frappe.db.has_column("File", "th_media_page_count"))
		self.assertTrue(frappe.db.has_column("File", "th_media_extracted_text"))

	def test_fields_for_iki_anahtari_donduruyor(self):
		doc = _dosya(f"belge-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		frappe.db.set_value(
			"File",
			doc.name,
			{"th_media_page_count": 12, "th_media_extracted_text": "merhaba dünya"},
			update_modified=False,
		)

		alanlar = seo.fields_for(doc.file_url)
		self.assertEqual(alanlar["page_count"], 12)
		self.assertEqual(alanlar["extracted_text"], "merhaba dünya")

	def test_bos_belgede_varsayilan_sifir_ve_bos_dize(self):
		doc = _dosya(f"bos-belge-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)

		alanlar = seo.fields_for(doc.file_url)
		self.assertEqual(alanlar["page_count"], 0)
		self.assertEqual(alanlar["extracted_text"], "")

	def test_negatif_page_count_disari_sizmiyor(self):
		"""Denetim düzeltme turu 1 — nöbetçi sızıntısı: `doc_meta.apply` başarısız
		çıkarımda kolona -1 yazıyor (İÇ anti-açlık damgası, `doc_meta.py`
		docstring'inde gerekçe); `fields_for` bunu dışarıya ASLA negatif
		göstermemeli — `_birlestir`'in `max(0, cint(...))` kırpması burada
		doğrudan `seo.fields_for` üzerinden doğrulanıyor."""
		doc = _dosya(f"negatif-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		frappe.db.set_value("File", doc.name, "th_media_page_count", -1, update_modified=False)

		alanlar = seo.fields_for(doc.file_url)
		self.assertEqual(alanlar["page_count"], 0)

	def test_set_asset_fields_page_count_ve_extracted_text_yazilamaz(self):
		"""Beyaz liste: yalnız `description` yazılır — diğer iki anahtar yok sayılır."""
		doc = _dosya(f"koru-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)

		sayi = seo.set_asset_fields(
			doc.file_url, {"page_count": 5, "extracted_text": "x", "description": "d"}
		)
		self.assertEqual(sayi, 1)

		guncel = frappe.db.get_value(
			"File",
			doc.name,
			["th_media_description", "th_media_page_count", "th_media_extracted_text"],
			as_dict=True,
		)
		self.assertEqual(guncel["th_media_description"], "d")
		self.assertFalse(guncel["th_media_page_count"])
		self.assertFalse(guncel["th_media_extracted_text"])


class TestTopluYolMetniTasimaz(FrappeTestCase):
	"""Düzeltme turu 1 — denetim bulgusu: `th_media_extracted_text` (Long Text)
	toplu sorgu yoluna (`fields_for_many`) girmemeli; `audit_batch`/sitemap
	ön-yüklemesi 100+ dosyada N×64KB taşımasın. `page_count` (Int) küçük — kalır.
	"""

	def test_asset_columns_toplu_yolda_metni_disarida_birakir(self):
		"""Üretilen SQL'i yakalamak için `frappe.db.has_column` mock'lamak yerine
		`_asset_columns`'ın döndürdüğü kolon listesini doğrudan denetliyoruz —
		gerçek şema üstünde çalışır, mock'un maskeleyebileceği bir yanlış
		pozitife (has_column hep True/False dönerse testin anlamsızlaşması) açık
		değildir; pratik ve doğrudan olan bu."""
		varsayilan = seo._asset_columns()
		tam = seo._asset_columns(include_text=True)
		self.assertNotIn("th_media_extracted_text", varsayilan)
		self.assertIn("th_media_page_count", varsayilan)
		self.assertIn("th_media_extracted_text", tam)

	def test_fields_for_many_extracted_text_bos_donuyor(self):
		"""Toplu okumada `extracted_text` her zaman `""` — kolon sorguya
		girmediği için `_birlestir`'in `.get(...) or ""` toleransı devreye
		girer. `page_count` toplu yolda da doğru değeri taşımaya devam eder."""
		doc = _dosya(f"toplu-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		frappe.db.set_value(
			"File",
			doc.name,
			{"th_media_page_count": 7, "th_media_extracted_text": "uzun metin"},
			update_modified=False,
		)

		toplu = seo.fields_for_many([doc.file_url])
		self.assertEqual(toplu[doc.file_url]["page_count"], 7)
		self.assertEqual(toplu[doc.file_url]["extracted_text"], "")

		# Tekil yol (`fields_for`) etkilenmedi — davranış değişmez.
		self.assertEqual(seo.fields_for(doc.file_url)["extracted_text"], "uzun metin")


class TestListingDocumentChild(FrappeTestCase):
	def test_append_ve_save_ile_yazilabiliyor(self):
		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = frappe.get_doc("Listing", ilan["name"])
		onceki_sayi = len(doc.get("documents") or [])
		doc.append(
			"documents",
			{
				"file": "/files/test-katalog.pdf",
				"title": "Test Katalog",
				"doc_type": "Katalog",
				"language": "tr",
			},
		)
		doc.save()

		def _geri_al():
			d = frappe.get_doc("Listing", ilan["name"])
			d.set("documents", (d.get("documents") or [])[:onceki_sayi])
			d.save()

		self.addCleanup(_geri_al)

		yeniden = frappe.get_doc("Listing", ilan["name"])
		satirlar = yeniden.get("documents") or []
		self.assertEqual(len(satirlar), onceki_sayi + 1)
		eklenen = satirlar[-1]
		self.assertEqual(eklenen.file, "/files/test-katalog.pdf")
		self.assertEqual(eklenen.title, "Test Katalog")
		self.assertEqual(eklenen.doc_type, "Katalog")
		self.assertEqual(eklenen.language, "tr")


class TestDocMetaExtract(FrappeTestCase):
	"""Task 2 — çıkarım motoru (`extract`). Senaryolar brief §Step 1 (a)-(g)."""

	def test_a_pdf_iki_sayfa_metin_ve_bos_baslik_metadata_ile_dolar(self):
		pdf = _pdf_bytes(
			["Sayfa bir metni test icerik", "Sayfa iki metni test icerik"],
			title="Ornek Sozlesme Basligi",
		)
		doc = _belge(f"sozlesme-{_TUZ}.pdf", pdf)
		self.addCleanup(_sil, "File", doc.name)

		sonuc = doc_meta.extract(doc.file_url)
		self.assertTrue(sonuc["ok"])
		self.assertEqual(sonuc["page_count"], 2)
		self.assertIn("Sayfa bir metni", sonuc["text"])
		self.assertIn("Sayfa iki metni", sonuc["text"])
		self.assertEqual(sonuc["title"], "Ornek Sozlesme Basligi")

		self.assertTrue(doc_meta.apply(doc.file_url))
		guncel = frappe.db.get_value(
			"File",
			doc.name,
			["th_media_page_count", "th_media_extracted_text", "th_media_title"],
			as_dict=True,
		)
		self.assertEqual(guncel["th_media_page_count"], 2)
		self.assertIn("Sayfa bir metni", guncel["th_media_extracted_text"])
		self.assertEqual(guncel["th_media_title"], "Ornek Sozlesme Basligi")

	def test_b_dolu_baslik_ezilmez(self):
		pdf = _pdf_bytes(["Tek sayfa metni"], title="Cikarilan Baslik")
		doc = _belge(f"dolu-baslik-{_TUZ}.pdf", pdf)
		self.addCleanup(_sil, "File", doc.name)
		frappe.db.set_value("File", doc.name, "th_media_title", "Elle Girilmis Baslik", update_modified=False)

		self.assertTrue(doc_meta.apply(doc.file_url))
		self.assertEqual(
			frappe.db.get_value("File", doc.name, "th_media_title"),
			"Elle Girilmis Baslik",
		)
		# Sayfa/metin yine de yazılır — yalnız başlık korunuyor.
		self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_page_count"), 1)

	def test_c_sifreli_pdf_guvenli_reddedilir(self):
		pdf = _pdf_bytes(["gizli icerik"], encrypt="parola123")
		doc = _belge(f"sifreli-{_TUZ}.pdf", pdf)
		self.addCleanup(_sil, "File", doc.name)

		sonuc = doc_meta.extract(doc.file_url)  # exception fırlatmamalı
		self.assertFalse(sonuc["ok"])
		self.assertEqual(sonuc["reason"], "encrypted")
		self.assertEqual(sonuc["page_count"], 0)
		self.assertEqual(sonuc["text"], "")
		self.assertEqual(sonuc["title"], "")

	def test_c2_basarisiz_cikarim_anti_aclik_damgasi_yazar(self):
		"""`apply()` başarısızlıkta `-1` yazar — `backfill_docs`'un aynı okunamayan
		dosyayı HER turda yeniden seçmesini önler (`video_poster.generate` ile
		aynı gerekçe, modül docstring'inde). Bu davranış brief'in Step 1 tablosunda
		açıkça senaryolanmadı ama `backfill_docs`'un `IFNULL(page_count,0)=0`
		süzgeciyle tutarlılığı için gerekli — burada ayrıca doğrulanıyor."""
		pdf = _pdf_bytes(["gizli icerik"], encrypt="parola123")
		doc = _belge(f"sifreli-apply-{_TUZ}.pdf", pdf)
		self.addCleanup(_sil, "File", doc.name)

		self.assertFalse(doc_meta.apply(doc.file_url))
		self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_page_count"), -1)
		self.assertFalse(frappe.db.get_value("File", doc.name, "th_media_extracted_text"))

	def test_d_docx_metni_cikarilir(self):
		docx = _docx_bytes(["Birinci paragraf metni", "Ikinci paragraf metni"])
		doc = _belge(f"belge-{_TUZ}.docx", docx)
		self.addCleanup(_sil, "File", doc.name)

		sonuc = doc_meta.extract(doc.file_url)
		self.assertTrue(sonuc["ok"])
		self.assertIn("Birinci paragraf metni", sonuc["text"])
		self.assertIn("Ikinci paragraf metni", sonuc["text"])

	def test_e_xlsx_sharedstrings_metni_cikarilir(self):
		xlsx = _xlsx_bytes(["Hucre bir", "Hucre iki", "Hucre uc"])
		doc = _belge(f"tablo-{_TUZ}.xlsx", xlsx)
		self.addCleanup(_sil, "File", doc.name)

		sonuc = doc_meta.extract(doc.file_url)
		self.assertTrue(sonuc["ok"])
		for beklenen in ("Hucre bir", "Hucre iki", "Hucre uc"):
			self.assertIn(beklenen, sonuc["text"])

	def test_d2_pptx_slayt_metni_ve_sayisi_cikarilir(self):
		"""Minor (b) — düzeltme turu 1: brief'in 9 senaryosunda pptx yoktu,
		ama `DOC_UZANTILAR` onu içeriyor ve `_extract_pptx` test edilmemişti.

		NOT (keşif): `.pptx` `media/upload_policy.EXTENSIONS` haritasında YOK
		ve `media/naming.py::_ALLOWED_EXTENSIONS` doğrudan o haritadan
		besleniyor — yani bugün platformda bir `.pptx` `File` kaydı olarak HİÇ
		YÜKLENEMİYOR (`write_file_hashed` her denemede `ValueError` fırlatıyor,
		ölçüldü). Bu, Task 2'nin kapsamı dışında bir platform kısıtı —
		`naming.py`'ye dokunulmadı (brief'in KORUNAN listesine yakın bir
		çekirdek dosya). Bu yüzden `_extract_pptx` `File`/`extract()` üzerinden
		değil, doğrudan gerçek bir disk yoluna karşı test ediliyor; zip/xml
		ayrıştırma mantığının kendisi bu platform kısıtından etkilenmiyor.
		"""
		pptx = _pptx_bytes(["Slayt bir metni", "Slayt iki metni"])
		with tempfile.NamedTemporaryFile(suffix=".pptx") as tmp:
			tmp.write(pptx)
			tmp.flush()
			sonuc = doc_meta._extract_pptx(tmp.name)

		self.assertTrue(sonuc["ok"])
		self.assertEqual(sonuc["page_count"], 2)
		self.assertIn("Slayt bir metni", sonuc["text"])
		self.assertIn("Slayt iki metni", sonuc["text"])

	def test_f_eski_doc_uzantisi_legacy_format_doner(self):
		doc = _belge(f"eski-{_TUZ}.doc", b"gercek .doc biti degil, uzantiya bakiliyor")
		self.addCleanup(_sil, "File", doc.name)

		sonuc = doc_meta.extract(doc.file_url)
		self.assertFalse(sonuc["ok"])
		self.assertEqual(sonuc["reason"], "legacy_format")
		self.assertEqual(sonuc["page_count"], 0)
		self.assertEqual(sonuc["text"], "")

	def test_g_64kb_tavaninda_kesilir(self):
		uzun_parca = "kesme testi icin tekrar eden uzun metin blogu doldurma amacli. " * 40
		sayfalar = [uzun_parca] * 30  # ~30*2500 karakter > 64 KB
		pdf = _pdf_bytes(sayfalar)
		doc = _belge(f"uzun-{_TUZ}.pdf", pdf)
		self.addCleanup(_sil, "File", doc.name)

		sonuc = doc_meta.extract(doc.file_url)
		self.assertTrue(sonuc["ok"])
		self.assertEqual(sonuc["page_count"], 30)
		self.assertLessEqual(len(sonuc["text"]), doc_meta.TEXT_TAVAN)
		self.assertGreater(len(sonuc["text"]), 0)


class TestDocMetaApplySiblings(FrappeTestCase):
	"""Senaryo (h) — aynı `file_url`'e işaret eden kardeş `File` kayıtları."""

	def test_h_kardes_kayitlarin_ikisine_de_yazilir(self):
		pdf = _pdf_bytes(["Paylasilan icerik metni"], title="Paylasilan Baslik")
		ilk = _belge(f"paylasim-{_TUZ}.pdf", pdf)
		self.addCleanup(_sil, "File", ilk.name)

		# İçerik-adresli adlandırma: byte-birebir aynı içerik aynı file_url'e
		# düşer (bkz. `test_media_seller_backup.py` "ikiz" deseni).
		ikinci = _belge(f"paylasim-ikinci-{_TUZ}.pdf", pdf)
		self.addCleanup(_sil, "File", ikinci.name)
		self.assertEqual(ikinci.file_url, ilk.file_url, "aynı içerik aynı adrese düşmeli")

		self.assertTrue(doc_meta.apply(ilk.file_url))
		for name in (ilk.name, ikinci.name):
			guncel = frappe.db.get_value(
				"File",
				name,
				["th_media_page_count", "th_media_extracted_text", "th_media_title"],
				as_dict=True,
			)
			self.assertEqual(guncel["th_media_page_count"], 1, name)
			self.assertIn("Paylasilan icerik metni", guncel["th_media_extracted_text"])
			self.assertEqual(guncel["th_media_title"], "Paylasilan Baslik")


class TestDocMetaBackfillIdempotent(FrappeTestCase):
	"""Senaryo (i) — `backfill_docs` ikinci turda aynı adayı bir daha seçmemeli."""

	def test_i_backfill_ikinci_turda_ayni_dosyalari_secmez(self):
		doc1 = _belge(f"yedek-bir-{_TUZ}.pdf", _pdf_bytes(["Yedek bir metni"], title="Yedek Bir"))
		self.addCleanup(_sil, "File", doc1.name)
		doc2 = _belge(f"yedek-iki-{_TUZ}.pdf", _pdf_bytes(["Yedek iki metni"], title="Yedek Iki"))
		self.addCleanup(_sil, "File", doc2.name)

		ilk_tur = doc_meta.backfill_docs(limit=500)
		self.assertGreaterEqual(ilk_tur, 2)
		for doc in (doc1, doc2):
			self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_page_count"), 1)

		# Kendi fixture'larımıza özel kontrol: artık boş-alan filtresine
		# UYMUYORLAR, bir daha aday olamazlar (`IFNULL(...,0)=0` yakalamaz).
		# Minor (c) — düzeltme turu 1: ikinci turun GLOBAL dönüşünün de 0
		# olduğunu iddia eden ortama bağımlı assert kaldırıldı (gerçek site
		# verisi zamanla değişebilir, test kırılgan olmamalı) — yalnız kendi
		# fixture'larımıza özgü, scope'lu kontrol kalıyor.
		kalan = frappe.db.sql(
			"""SELECT name FROM `tabFile` WHERE name IN (%s, %s)
			AND IFNULL(th_media_page_count, 0) = 0 AND IFNULL(th_media_extracted_text, '') = ''""",
			(doc1.name, doc2.name),
		)
		self.assertEqual(len(kalan), 0)

		# İkinci tur kendi dosyalarımızı bir daha ENQUEUE/apply ETMEMELİ —
		# `backfill_docs`'un döndürdüğü sayı içinde bizim `file_url`'lerimiz
		# olmamalı (global sayı ortam verisine bağımlı olabileceği için
		# doğrudan `== 0` iddia edilmiyor, yalnız KENDİ adaylarımız kontrol
		# ediliyor).
		doc_meta.backfill_docs(limit=500)
		kalan_ikinci_tur = frappe.db.sql(
			"""SELECT name FROM `tabFile` WHERE name IN (%s, %s)
			AND IFNULL(th_media_page_count, 0) = 0 AND IFNULL(th_media_extracted_text, '') = ''""",
			(doc1.name, doc2.name),
		)
		self.assertEqual(len(kalan_ikinci_tur), 0)


class TestDocMetaZipGuards(FrappeTestCase):
	"""IMPORTANT #1 — düzeltme turu 1 + 2: zip-bomb + entity genişletme önlemi."""

	def test_zip_bomb_uye_siniri_reddedilir(self):
		"""Dürüst-büyük beyan — `getinfo().file_size` UCUZ ön-elemesi bunu tek
		bayt okumadan keser (`_ZIP_MEMBER_LIMIT` aşımı)."""
		asiri = doc_meta._ZIP_MEMBER_LIMIT + (1024 * 1024)  # 21 MB > 20 MB tavan
		docx = _zip_bomb_docx(asiri)
		doc = _belge(f"bomba-{_TUZ}.docx", docx)
		self.addCleanup(_sil, "File", doc.name)

		sonuc = doc_meta.extract(doc.file_url)
		self.assertFalse(sonuc["ok"])
		self.assertEqual(sonuc["reason"], "zip_icerik_asiri")
		self.assertEqual(sonuc["text"], "")

	def test_zip_bomb_sahte_beyan_bypass_bellek_sinirli_kalir(self):
		"""IMPORTANT #1 turu 2 — re-review'un CANLI KANITLADIĞI bypass:
		`getinfo().file_size` saldırganın yazdığı zip metadata'sı; 200 MB
		sıfıra şişen bir üye header'da 100 bayt beyan ediyor. Ön-eleme (100 <
		20 MB) bunu geçiriyor — asıl savunma artık AKIŞLI okumanın kendisi.

		Fix ÖNCESİ (re-review'un ölçtüğü): `zf.read(member)` tüm 200 MB'ı
		decompress ediyor, CRC hatası iş bittikten SONRA geliyor, mevcut
		`except Exception` bunu sessizce `container_invalid`'e çeviriyor —
		~200 MB RSS artışı. Fix SONRASI: `_ZipButce.oku` `zf.open(member)` +
		`fh.read(65536)` kullanıyor; bu testte doğrudan ölçülüyor.

		NOT (`reason` gerekçesi): burada `reason` `"zip_icerik_asiri"` DEĞİL,
		`"container_invalid"` — spoofed beyan (100 bayt) benim 20 MB üye
		tavanımdan zaten KÜÇÜK olduğu için, `zipfile.ZipExtFile._read1`
		beyan edilen boyut (`_left`) sıfırlanınca kendi CRC doğrulamasını
		tetikleyip `BadZipFile` fırlatıyor — benim `_ZipButce` sayaç kontrolüm
		bu değere hiç ULAŞAMIYOR (spoofed her zaman ≤ benim tavanım olmak
		ZORUNDA, yoksa ön-eleme onu zaten baştan keserdi). İKİ yol da bellek
		güvenli: `_read1`'e SINIRLI `n` (64 KB) verildiği için decompressor
		tek seferde en fazla ~64 KB üretiyor, beyan edilen/gerçek boyuttan
		bağımsız. Bu yüzden asıl regresyon güvencesi `reason` DEĞİL, aşağıdaki
		BELLEK ÖLÇÜMÜ — reason string'i fix öncesinde de aynıydı (ikisi de
		`except Exception` üstünden `container_invalid`'e düşüyordu), yalnız
		bellek farklıydı."""
		gercek_boyut = 200 * 1024 * 1024
		docx = _zip_bomb_spoofed_docx(gercek_boyut, beyan_boyut=100)
		doc = _belge(f"sahte-bomba-{_TUZ}.docx", docx)
		self.addCleanup(_sil, "File", doc.name)

		try:
			import resource

			once = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
		except ImportError:  # pragma: no cover — yalnız POSIX dışı ortamlarda
			once = None

		sonuc = doc_meta.extract(doc.file_url)

		self.assertFalse(sonuc["ok"])
		self.assertLess(len(sonuc.get("text") or ""), 1024, "200 MB'lık tampon dönmemeli")

		if once is not None:
			sonra = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
			artis_kb = sonra - once
			# Fix ÖNCESİ ölçüm (bu rapordaki komutla ayrıca doğrulandı): ~200
			# MB (≈204800 KB) RSS artışı. Fix SONRASI bu testte ölçülen: ~0.
			# Eşik cömert (50 MB) — GC/fragmentation gürültüsüne tolerans
			# tanır ama 200 MB'lık bir kaçağı KESİNLİKLE yakalar.
			self.assertLess(artis_kb, 50 * 1024, f"decompress bellek artışı çok yüksek: {artis_kb} KB")

	def test_doctype_entity_bildirimi_reddedilir(self):
		"""Sahte docx — DOCTYPE/ENTITY imzası ayrıştırmadan ÖNCE yakalanmalı."""
		docx = _entity_bomb_docx()
		doc = _belge(f"entity-{_TUZ}.docx", docx)
		self.addCleanup(_sil, "File", doc.name)

		sonuc = doc_meta.extract(doc.file_url)
		self.assertFalse(sonuc["ok"])
		self.assertEqual(sonuc["reason"], "xml_entity_reddi")
		self.assertEqual(sonuc["text"], "")


class TestDocMetaHookRegistration(FrappeTestCase):
	"""Kanca gerçekten `hooks.py`'ye bağlı mı — regresyon güvenlik ağı."""

	def test_hook_kaydi_var(self):
		kancalar = frappe.get_hooks("doc_events") or {}
		file_hooks = (kancalar.get("File") or {}).get("after_insert") or []
		self.assertIn("tradehub_core.media.doc_meta.maybe_extract_on_insert", file_hooks)

	def test_public_pdfde_enqueue_tam_parametrelerle_cagrilir(self):
		"""IMPORTANT #2 — pozitif kanca testi (düzeltme turu 1). Emsal:
		`test_video_poster.py:201` — yalnız "enqueue edildi mi" değil, DOĞRU
		kuyruk/timeout/parametrelerle edildiği de doğrulanmalı."""
		with mock.patch("tradehub_core.media.av.enqueue_scan"), mock.patch("frappe.enqueue") as sahte:
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"pozitif-{_TUZ}.pdf",
					"is_private": 0,
					"content": _pdf_bytes(["pozitif kanca testi"]),
				}
			)
			doc.insert(ignore_permissions=True)
		self.addCleanup(_sil, "File", doc.name)

		bizim_cagri = next(
			(c for c in sahte.call_args_list if c.kwargs.get("file_url") == doc.file_url),
			None,
		)
		self.assertIsNotNone(bizim_cagri, "public .pdf enqueue edilenler arasında değil")
		self.assertEqual(bizim_cagri.args, ("tradehub_core.media.doc_meta.apply",))
		self.assertEqual(bizim_cagri.kwargs.get("queue"), "media-maint")
		self.assertEqual(bizim_cagri.kwargs.get("timeout"), 180)
		self.assertTrue(bizim_cagri.kwargs.get("enqueue_after_commit"))

	def test_private_dosyada_enqueue_edilmez(self):
		with mock.patch("tradehub_core.media.av.enqueue_scan"), mock.patch("frappe.enqueue") as sahte:
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"gizli-{_TUZ}.pdf",
					"is_private": 1,
					"content": _pdf_bytes(["gizli"]),
				}
			)
			doc.insert(ignore_permissions=True)
		self.addCleanup(_sil, "File", doc.name)
		self.assertFalse(
			any(c.kwargs.get("file_url") == doc.file_url for c in sahte.call_args_list),
			"private dosya doc_meta kuyruğuna girmemeli",
		)

	def test_desteklenmeyen_uzantida_enqueue_edilmez(self):
		with mock.patch("tradehub_core.media.av.enqueue_scan"), mock.patch("frappe.enqueue") as sahte:
			doc = _dosya(f"resim-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		self.assertFalse(
			any(c.kwargs.get("file_url") == doc.file_url for c in sahte.call_args_list),
			".txt DOC_UZANTILAR'da değil — enqueue edilmemeli",
		)


# ── Task 3 — `doc_indexable` + sitemap doküman girdileri + DigitalDocument ──
#
# Karar belgesi: `.superpowers/sdd/2026-08-27-file-manager-seo/task-3-brief.md`.


def _ilan_belge_baglar(ilan_adi: str, file_url: str, *, title: str = "Test Katalog") -> None:
	"""`Listing.documents` (child `Listing Document`) child'ına bir satır ekler
	— `TestListingDocumentChild.test_append_ve_save_ile_yazilabiliyor` (Task 1)
	ile AYNI append+save deseni, modül seviyesinde paylaşılan yardımcı."""
	doc = frappe.get_doc("Listing", ilan_adi)
	onceki_sayi = len(doc.get("documents") or [])
	doc.append(
		"documents",
		{"file": file_url, "title": title, "doc_type": "Katalog", "language": "tr"},
	)
	doc.save()

	def _geri_al():
		guncel = frappe.get_doc("Listing", ilan_adi)
		guncel.set("documents", (guncel.get("documents") or [])[:onceki_sayi])
		guncel.save()

	return _geri_al


class TestDocIndexable(FrappeTestCase):
	"""`doc_indexable` — `watch_indexable`'ın doküman ikizi (brief Step 1a).

	Üç koşul: `seo_index.decide` (private dahil) + uzantı `DOC_UZANTILAR`
	içinde mi + en az bir vitrinde görünen ilana bağlı mı."""

	def test_uc_kosul_da_saglaninca_true(self):
		from tradehub_core.api import media_public

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"di-tam-{_TUZ}.pdf", _pdf_bytes(["indexlenebilir belge icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url))

		self.assertTrue(media_public.doc_indexable(doc.file_url))

	def test_ilana_baglanmamis_belge_false(self):
		from tradehub_core.api import media_public

		doc = _belge(f"di-baglanmamis-{_TUZ}.pdf", _pdf_bytes(["hicbir ilana bagli degil"]))
		self.addCleanup(_sil, "File", doc.name)

		self.assertFalse(media_public.doc_indexable(doc.file_url))

	def test_private_belge_false(self):
		from tradehub_core.api import media_public

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		with mock.patch("tradehub_core.media.av.enqueue_scan"), mock.patch("frappe.enqueue"):
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"di-private-{_TUZ}.pdf",
					"is_private": 1,
					"content": _pdf_bytes(["gizli belge icerigi"]),
				}
			)
			doc.insert(ignore_permissions=True)
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url))

		self.assertFalse(media_public.doc_indexable(doc.file_url))

	def test_desteklenmeyen_uzanti_false(self):
		"""İkinci koşul: `Listing Document.file` serbest bir `Attach` — gerçek
		bir PDF/Office olmayan (`.txt`) dosya, ilana bağlı olsa bile indexlenmez."""
		from tradehub_core.api import media_public

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _dosya(f"di-uzanti-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url))

		self.assertFalse(media_public.doc_indexable(doc.file_url))

	def test_disaridan_verilen_listings_tekrar_hesaplanmaz(self):
		"""`watch_indexable`'ın ikizi imza sözleşmesi: `listings` verilirse
		`_document_listings` hiç çağrılmaz."""
		from tradehub_core.api import media_public

		doc = _belge(f"di-parametre-{_TUZ}.pdf", _pdf_bytes(["parametre testi"]))
		self.addCleanup(_sil, "File", doc.name)

		with mock.patch.object(media_public, "_document_listings") as sahte:
			sonuc = media_public.doc_indexable(doc.file_url, listings=[{"name": "X"}])

		sahte.assert_not_called()
		self.assertTrue(sonuc)


class TestBuildDigitalDocument(FrappeTestCase):
	"""`build_digital_document` — brief Step 1b: tam/adsız-None/lisanslı."""

	def test_tam_alanli_digital_document(self):
		from tradehub_core.seo.schema_builder import build_digital_document

		nesne = build_digital_document(
			{"title": "Ürün Kataloğu 2026", "date_created": "2026-08-27"},
			"https://istoc.localhost",
			content_url="/files/katalog.pdf",
		)

		self.assertEqual(nesne["@type"], "DigitalDocument")
		self.assertEqual(nesne["name"], "Ürün Kataloğu 2026")
		self.assertEqual(nesne["url"], "https://istoc.localhost/files/katalog.pdf")
		self.assertEqual(nesne["contentUrl"], "https://istoc.localhost/files/katalog.pdf")
		self.assertEqual(nesne["encodingFormat"], "application/pdf")
		self.assertEqual(nesne["dateCreated"], "2026-08-27")

	def test_baslik_yoksa_dosya_adi_govdesi_kullanilir(self):
		from tradehub_core.seo.schema_builder import build_digital_document

		nesne = build_digital_document({}, "https://istoc.localhost", content_url="/files/teknik-fon.pdf")
		self.assertEqual(nesne["name"], "teknik-fon")

	def test_ad_ve_adres_yoksa_none(self):
		from tradehub_core.seo.schema_builder import build_digital_document

		self.assertIsNone(build_digital_document({}, "https://istoc.localhost", content_url=""))

	def test_lisansli_digital_document(self):
		from tradehub_core.seo.schema_builder import build_digital_document

		alanlar = {
			"title": "Sertifika",
			"creator": "İstoç",
			"credit_text": "İstoç Medya",
			"copyright_notice": "© İstoç",
			"license_url": "https://example.com/lisans",
			"acquire_license_url": "https://example.com/lisans-al",
		}
		nesne = build_digital_document(alanlar, "https://istoc.localhost", content_url="/files/sertifika.pdf")

		self.assertEqual(nesne["creator"], {"@type": "Organization", "name": "İstoç"})
		self.assertEqual(nesne["creditText"], "İstoç Medya")
		self.assertEqual(nesne["copyrightNotice"], "© İstoç")
		self.assertEqual(nesne["license"], "https://example.com/lisans")
		self.assertEqual(nesne["acquireLicensePage"], "https://example.com/lisans-al")

	def test_uzanti_verilirse_encoding_format_ondan_cozulur(self):
		"""`content_url`'in kendisi uzantısız olabilir — `uzanti` verilirse
		`encodingFormat` ondan çözülür (hash-adresli dosya senaryosu).

		Düzeltme turu 1: parametre adı `doc_type` DEĞİL `uzanti` — `Listing
		Document.doc_type` (kategori Select'i, "Katalog/Sertifika/...") ile
		isim çakışması kalktı, burası dosya UZANTISI (".xlsx" vb.)."""
		from tradehub_core.seo.schema_builder import build_digital_document

		nesne = build_digital_document(
			{"title": "Fiyat Listesi"},
			"https://istoc.localhost",
			content_url="/files/hashli-adres-uzantisiz",
			uzanti=".xlsx",
		)
		self.assertEqual(
			nesne["encodingFormat"],
			"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		)


class TestBuildProductSchemaSubjectOf(FrappeTestCase):
	"""`build_product_schema(media_documents=...)` — `subjectOf` (pure, DB'siz)."""

	def _cekirdek_listing(self) -> dict:
		return {
			"slug": "test-urun",
			"title": "Test Ürün",
			"name": "LST-TEST",
			"currency": "TRY",
			"selling_price": 100,
		}

	def test_media_documents_verilirse_subjectof_basilir(self):
		from tradehub_core.seo.schema_builder import build_product_schema

		belge = {"@type": "DigitalDocument", "name": "Katalog", "url": "https://s/files/k.pdf"}
		schema = build_product_schema(
			listing=self._cekirdek_listing(),
			site_url="https://istoc.localhost",
			brand=None,
			category_name=None,
			aggregate_rating=None,
			reviews=None,
			media_documents=[belge],
		)
		self.assertEqual(schema["subjectOf"], [belge])

	def test_media_documents_yoksa_subjectof_hic_girmez(self):
		from tradehub_core.seo.schema_builder import build_product_schema

		schema = build_product_schema(
			listing=self._cekirdek_listing(),
			site_url="https://istoc.localhost",
			brand=None,
			category_name=None,
			aggregate_rating=None,
			reviews=None,
		)
		self.assertNotIn("subjectOf", schema)


class TestListingDigitalDocumentJsonLd(FrappeTestCase):
	"""Task 4 — ürün JSON-LD `subjectOf`, `compose_for_listing` zincirinde
	`media_videos` deseninin YANINDA: `schema_builder._listing_document_objects`
	artık GERÇEK `Listing.documents` child'ından `DigitalDocument` üretiyor
	(önceki Task 3 sürümü yalnız `listing.get("media_documents")` pass-through'unu
	sınıyordu — o zincir hâlâ burada, ama artık gerçek veriyle besleniyor)."""

	def test_media_documents_varsa_product_schema_subjectof_tasir(self):
		from tradehub_core.seo.schema_builder import compose_for_listing

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"jsonld-katalog-{_TUZ}.pdf", _pdf_bytes(["jsonld katalog icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url, title="Ürün Kataloğu"))

		listing = frappe.get_doc("Listing", ilan["name"]).as_dict()
		schemas = compose_for_listing(listing, {}, "https://istoc.localhost")
		product = next(s for s in schemas if s["@type"] == "Product")

		self.assertIn("subjectOf", product)
		belge = product["subjectOf"][0]
		self.assertEqual(belge["@type"], "DigitalDocument")
		self.assertEqual(belge["name"], "Ürün Kataloğu")
		self.assertEqual(belge["contentUrl"], f"https://istoc.localhost{doc.file_url}")

	def test_media_documents_yoksa_product_schema_subjectof_tasimaz(self):
		from tradehub_core.seo.schema_builder import compose_for_listing

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		listing = frappe.get_doc("Listing", ilan["name"]).as_dict()
		schemas = compose_for_listing(listing, {}, "https://istoc.localhost")
		product = next(s for s in schemas if s["@type"] == "Product")

		self.assertNotIn("subjectOf", product)

	def test_ilana_baglanmamis_belge_subjectof_hic_girmez(self):
		"""`Listing.documents`'a HİÇ eklenmemiş bir dosya (ör. başka bir ilanın
		belgesi) bu ilanın şemasına karışmamalı — `listing.get("documents")`
		yalnız KENDİ child satırlarını taşır, ekstra bir filtre gerekmez ama
		davranış açıkça sabitleniyor."""
		from tradehub_core.seo.schema_builder import compose_for_listing

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"jsonld-baglanmamis-{_TUZ}.pdf", _pdf_bytes(["baglanmamis belge"]))
		self.addCleanup(_sil, "File", doc.name)

		listing = frappe.get_doc("Listing", ilan["name"]).as_dict()
		schemas = compose_for_listing(listing, {}, "https://istoc.localhost")
		product = next(s for s in schemas if s["@type"] == "Product")

		self.assertNotIn("subjectOf", product)

	def test_private_belge_subjectof_disinda_kalir(self):
		"""`_listing_video_objects`/`_listing_image_objects` ile AYNI kapı:
		private dosya `seo_index.decide` üzerinden elenir, JSON-LD'ye girmez."""
		from tradehub_core.seo.schema_builder import compose_for_listing

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		with mock.patch("tradehub_core.media.av.enqueue_scan"), mock.patch("frappe.enqueue"):
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"jsonld-private-{_TUZ}.pdf",
					"is_private": 1,
					"content": _pdf_bytes(["private belge icerigi"]),
				}
			)
			doc.insert(ignore_permissions=True)
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url))

		listing = frappe.get_doc("Listing", ilan["name"]).as_dict()
		schemas = compose_for_listing(listing, {}, "https://istoc.localhost")
		product = next(s for s in schemas if s["@type"] == "Product")

		self.assertNotIn("subjectOf", product)

	def test_desteklenmeyen_uzantili_belge_subjectof_disinda_kalir(self):
		"""Düzeltme turu 1 — sitemap'in `doc_indexable` tanımıyla BİRLİK:
		`Listing Document.file` serbest bir `Attach`; `DOC_UZANTILAR` dışındaki
		(`.txt` gibi) bir dosya sitemap'e girmediği gibi JSON-LD `subjectOf`'a
		da girmemeli — tanım iki yerde ayrışmasın."""
		from tradehub_core.seo.schema_builder import compose_for_listing

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _dosya(f"jsonld-desteklenmeyen-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url))

		listing = frappe.get_doc("Listing", ilan["name"]).as_dict()
		schemas = compose_for_listing(listing, {}, "https://istoc.localhost")
		product = next(s for s in schemas if s["@type"] == "Product")

		self.assertNotIn("subjectOf", product)

	def test_ayni_dosya_iki_satirda_tek_subjectof(self):
		"""Final review — küçük düzeltme: aynı fiziksel dosya iki child
		satırıyla bağlıysa `subjectOf`'a yalnız BİR kez girer —
		`api/listing.py::_listing_belgeleri` ile AYNI dedup gerekçesi."""
		from tradehub_core.seo.schema_builder import compose_for_listing

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"jsonld-dedup-{_TUZ}.pdf", _pdf_bytes(["jsonld dedup icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url, title="Birinci"))
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url, title="İkinci"))

		listing = frappe.get_doc("Listing", ilan["name"]).as_dict()
		schemas = compose_for_listing(listing, {}, "https://istoc.localhost")
		product = next(s for s in schemas if s["@type"] == "Product")

		eslesenler = [b for b in product.get("subjectOf", []) if b["contentUrl"].endswith(doc.file_url)]
		self.assertEqual(len(eslesenler), 1)


class TestSitemapDocEntries(FrappeTestCase):
	"""Brief Step 1c — `_doc_entries_for_rows`: indexlenebilir doküman `<url>`
	üretir, görünmez üründe üretmez, iki üründe aynı dosya → tek girdi."""

	def test_indexable_belge_url_uretir(self):
		from tradehub_core.seo import sitemap_generator as sg

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"sitemap-belge-{_TUZ}.pdf", _pdf_bytes(["sitemap belge icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url))

		row = {"name": ilan["name"], "slug": "ilgisiz-belge-slug-1", "modified": "2020-01-01"}
		girdiler = sg._entries_for_rows([row], sg.DOCTYPE_CONFIG["Listing"], "https://s")

		belge_girdileri = [g for g in girdiler if g["loc"] == f"https://s{doc.file_url}"]
		self.assertEqual(len(belge_girdileri), 1)
		self.assertNotIn("videos", belge_girdileri[0])
		self.assertNotIn("images", belge_girdileri[0])

	def test_gorunmez_urunde_belge_uretmez(self):
		from tradehub_core.seo import sitemap_generator as sg

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"sitemap-belge-gizli-{_TUZ}.pdf", _pdf_bytes(["gizli urun belgesi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url))

		eski_gorunurluk = frappe.db.get_value("Listing", ilan["name"], "storefront_visible")
		frappe.db.set_value("Listing", ilan["name"], "storefront_visible", 0, update_modified=False)
		self.addCleanup(
			lambda: frappe.db.set_value(
				"Listing", ilan["name"], "storefront_visible", eski_gorunurluk, update_modified=False
			)
		)

		row = {"name": ilan["name"], "slug": "ilgisiz-belge-slug-2", "modified": "2020-01-01"}
		girdiler = sg._entries_for_rows([row], sg.DOCTYPE_CONFIG["Listing"], "https://s")

		belge_girdileri = [g for g in girdiler if g["loc"] == f"https://s{doc.file_url}"]
		self.assertEqual(belge_girdileri, [])

	def test_iki_urunde_ayni_dosya_tek_girdi(self):
		from tradehub_core.seo import sitemap_generator as sg

		ilanlar = _iki_gorunur_ilan()
		if len(ilanlar) < 2:
			self.skipTest("Vitrinde görünen en az 2 ilan yok — dedup fixture'ı kurulamaz.")
		ilan_a, ilan_b = ilanlar[0]["name"], ilanlar[1]["name"]

		doc = _belge(f"sitemap-belge-paylasim-{_TUZ}.pdf", _pdf_bytes(["paylasimli belge icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan_a, doc.file_url))
		self.addCleanup(_ilan_belge_baglar(ilan_b, doc.file_url))

		rows = [
			{"name": ilan_a, "slug": "ilgisiz-belge-slug-a", "modified": "2020-01-01"},
			{"name": ilan_b, "slug": "ilgisiz-belge-slug-b", "modified": "2020-01-01"},
		]
		girdiler = sg._entries_for_rows(rows, sg.DOCTYPE_CONFIG["Listing"], "https://s")

		belge_girdileri = [g for g in girdiler if g["loc"] == f"https://s{doc.file_url}"]
		self.assertEqual(len(belge_girdileri), 1, "aynı dosya İKİ kez doküman girdisi üretmemeli")


# ── Task 4 — `get_listing_detail` `documents` alanı + JSON-LD `media_documents` ──
#
# Karar belgesi: `.superpowers/sdd/2026-08-27-file-manager-seo/task-4-brief.md`.


class TestListingBelgeleriAPI(FrappeTestCase):
	"""`api.listing._listing_belgeleri` — API `documents` alanı sözleşmesi:
	`[{url, title, docType, language, sizeBytes}]`."""

	def test_dolu_liste_beklenen_alanlari_tasir(self):
		from tradehub_core.api.listing import _listing_belgeleri

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"api-katalog-{_TUZ}.pdf", _pdf_bytes(["api katalog icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url, title="API Kataloğu"))

		listing = frappe.get_doc("Listing", ilan["name"])
		belgeler = _listing_belgeleri(listing)

		eklenen = next(b for b in belgeler if b["url"] == doc.file_url)
		self.assertEqual(eklenen["title"], "API Kataloğu")
		self.assertEqual(eklenen["docType"], "Katalog")
		self.assertEqual(eklenen["language"], "tr")
		self.assertEqual(eklenen["sizeBytes"], frappe.db.get_value("File", doc.name, "file_size"))
		self.assertGreater(eklenen["sizeBytes"], 0)

	def test_baslik_bossa_dosya_seo_basligina_duser(self):
		"""Child satırında `title` boşsa dosyanın SEO başlığına (Task 2 PDF
		`/Title` çıkarımı) düşülür — dosya adı gövdesinden ÖNCE."""
		from tradehub_core.api.listing import _listing_belgeleri

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"api-baslik-{_TUZ}.pdf", _pdf_bytes(["seo baslik dusme testi"]))
		self.addCleanup(_sil, "File", doc.name)
		frappe.db.set_value(
			"File", doc.name, "th_media_title", "Çıkarılan SEO Başlığı", update_modified=False
		)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url, title=""))

		listing = frappe.get_doc("Listing", ilan["name"])
		belgeler = _listing_belgeleri(listing)
		eklenen = next(b for b in belgeler if b["url"] == doc.file_url)
		self.assertEqual(eklenen["title"], "Çıkarılan SEO Başlığı")

	def test_baslik_ve_seo_basligi_yoksa_dosya_adi_govdesi(self):
		from tradehub_core.api.listing import _listing_belgeleri

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"api-govde-{_TUZ}.pdf", _pdf_bytes(["dosya adi govdesi testi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url, title=""))

		listing = frappe.get_doc("Listing", ilan["name"])
		belgeler = _listing_belgeleri(listing)
		eklenen = next(b for b in belgeler if b["url"] == doc.file_url)
		dosya_adi = doc.file_url.rsplit("/", 1)[-1]
		beklenen = dosya_adi.rsplit(".", 1)[0] if "." in dosya_adi else dosya_adi
		self.assertEqual(eklenen["title"], beklenen)

	def test_bos_listede_bos_liste_doner(self):
		from tradehub_core.api.listing import _listing_belgeleri

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		listing = frappe.get_doc("Listing", ilan["name"])
		if listing.get("documents"):
			self.skipTest("İlanda zaten belge var — temiz senaryo kurulamıyor.")

		self.assertEqual(_listing_belgeleri(listing), [])

	def test_sizebytes_tek_toplu_sorguyla_cozulur(self):
		"""N+1 yok — birden çok belgenin boyutu TEK `File` sorgusuyla çözülür
		(anti-patterns.md §6)."""
		from tradehub_core.api.listing import _listing_belgeleri

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc1 = _belge(f"api-toplu-1-{_TUZ}.pdf", _pdf_bytes(["toplu belge bir"]))
		self.addCleanup(_sil, "File", doc1.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc1.file_url, title="Belge Bir"))
		doc2 = _belge(f"api-toplu-2-{_TUZ}.pdf", _pdf_bytes(["toplu belge iki, biraz daha uzun"]))
		self.addCleanup(_sil, "File", doc2.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc2.file_url, title="Belge İki"))

		listing = frappe.get_doc("Listing", ilan["name"])
		with mock.patch("frappe.get_all", wraps=frappe.get_all) as sahte:
			belgeler = _listing_belgeleri(listing)
			dosya_cagrilari = [c for c in sahte.call_args_list if c.args[:1] == ("File",)]

		self.assertEqual(len(dosya_cagrilari), 1, "sizeBytes TEK toplu File sorgusuyla çözülmeli")
		for beklenen_doc in (doc1, doc2):
			eklenen = next(b for b in belgeler if b["url"] == beklenen_doc.file_url)
			self.assertGreater(eklenen["sizeBytes"], 0)

	def test_private_belge_disari_sizmaz(self):
		"""Final review — kritik düzeltme: spec §10.7 "private dokümanlar
		hiçbir yüzeye sızmaz". `documents` çıktısında yalnız public belge
		kalmalı, private child satırı tamamen elenmeli."""
		from tradehub_core.api.listing import _listing_belgeleri

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		public_doc = _belge(f"api-public-{_TUZ}.pdf", _pdf_bytes(["public belge icerigi"]))
		self.addCleanup(_sil, "File", public_doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], public_doc.file_url, title="Public Belge"))

		with mock.patch("tradehub_core.media.av.enqueue_scan"), mock.patch("frappe.enqueue"):
			private_doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"api-private-{_TUZ}.pdf",
					"is_private": 1,
					"content": _pdf_bytes(["private belge icerigi"]),
				}
			)
			private_doc.insert(ignore_permissions=True)
		self.addCleanup(_sil, "File", private_doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], private_doc.file_url, title="Private Belge"))

		listing = frappe.get_doc("Listing", ilan["name"])
		belgeler = _listing_belgeleri(listing)
		urls = [b["url"] for b in belgeler]

		self.assertIn(public_doc.file_url, urls)
		self.assertNotIn(private_doc.file_url, urls)

	def test_ayni_dosya_iki_satirda_tek_girdi(self):
		"""Final review — küçük düzeltme: aynı `file_url` birden fazla child
		satırıyla bağlıysa (admin'in yanlışlıkla iki kez eklemesi) çıktıya
		yalnız İLKİ girer."""
		from tradehub_core.api.listing import _listing_belgeleri

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"api-dedup-{_TUZ}.pdf", _pdf_bytes(["dedup belge icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url, title="Birinci Başlık"))
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url, title="İkinci Başlık"))

		listing = frappe.get_doc("Listing", ilan["name"])
		belgeler = _listing_belgeleri(listing)
		eslesenler = [b for b in belgeler if b["url"] == doc.file_url]

		self.assertEqual(len(eslesenler), 1)
		self.assertEqual(eslesenler[0]["title"], "Birinci Başlık")

	def test_karantinadaki_belge_disari_sizmaz(self):
		"""Tamirat: private olmayan ama AV taramasınca karantinaya alınmış
		(`th_media_scan_status=infected`) bir dosyanın metadata'sı da guest
		`documents` çıktısına sızmamalı — `seo_index.BLOCKED_SCAN_STATUSES`."""
		from tradehub_core.api.listing import _listing_belgeleri
		from tradehub_core.media import seo_index

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		public_doc = _belge(f"api-karantina-public-{_TUZ}.pdf", _pdf_bytes(["temiz belge icerigi"]))
		self.addCleanup(_sil, "File", public_doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], public_doc.file_url, title="Temiz Belge"))

		infected_doc = _belge(f"api-karantina-{_TUZ}.pdf", _pdf_bytes(["karantina belge icerigi"]))
		self.addCleanup(_sil, "File", infected_doc.name)
		frappe.db.set_value(
			"File", infected_doc.name, "th_media_scan_status", "infected", update_modified=False
		)
		self.assertIn("infected", seo_index.BLOCKED_SCAN_STATUSES)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], infected_doc.file_url, title="Karantina Belge"))

		listing = frappe.get_doc("Listing", ilan["name"])
		belgeler = _listing_belgeleri(listing)
		urls = [b["url"] for b in belgeler]

		self.assertIn(public_doc.file_url, urls)
		self.assertNotIn(infected_doc.file_url, urls)


class TestGetListingDetailDocumentsField(FrappeTestCase):
	"""`get_listing_detail` — `documents` alanı `videoWatchUrl` deseniyle AYNI
	ilke: liste boşsa anahtar HİÇ girmez."""

	def test_documents_varsa_dogru_sekilde_basilir(self):
		from tradehub_core.api import listing as listing_api

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"detay-belge-{_TUZ}.pdf", _pdf_bytes(["detay ucu belge icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar(ilan["name"], doc.file_url, title="Detay Kataloğu"))
		frappe.cache.delete_value(f"{listing_api._LISTING_DETAIL_CACHE_PREFIX}{ilan['name']}:tr")

		data = listing_api.get_listing_detail(ilan["name"])["data"]

		self.assertIn("documents", data)
		eklenen = next(d for d in data["documents"] if d["url"] == doc.file_url)
		self.assertEqual(eklenen["title"], "Detay Kataloğu")
		self.assertEqual(eklenen["docType"], "Katalog")
		self.assertEqual(eklenen["language"], "tr")
		self.assertGreater(eklenen["sizeBytes"], 0)

	def test_documents_boyken_anahtar_hic_girmez(self):
		from tradehub_core.api import listing as listing_api

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		mevcut = frappe.get_doc("Listing", ilan["name"]).get("documents") or []
		if mevcut:
			self.skipTest("İlanda zaten belge var — temiz senaryo kurulamıyor.")

		frappe.cache.delete_value(f"{listing_api._LISTING_DETAIL_CACHE_PREFIX}{ilan['name']}:tr")
		data = listing_api.get_listing_detail(ilan["name"])["data"]
		self.assertNotIn("documents", data)


class TestListingDocumentObjectsNoneEleme(FrappeTestCase):
	"""`schema_builder._listing_document_objects` — `build_digital_document`'in
	`None` dönüşü (ad/adres tamamen anlamsız, `TestBuildDigitalDocument.
	test_ad_ve_adres_yoksa_none` ile AYNI koşul) listeye HİÇ girmemeli;
	`_listing_video_objects`'in `if nesne: out.append(nesne)` deseniyle AYNI."""

	def test_none_donen_satir_elenir_digeri_kalir(self):
		from tradehub_core.media import seo_index
		from tradehub_core.seo import schema_builder

		listing = {
			"name": "TEST-LISTING-NONE-ELEME",
			"documents": [
				{"name": "row-anlamsiz", "file": "/files/anlamsiz.pdf", "title": ""},
				{"name": "row-gecerli", "file": "/files/gecerli.pdf", "title": "Geçerli Belge"},
			],
		}
		gecerli_nesne = {"@type": "DigitalDocument", "name": "Geçerli Belge"}
		with (
			mock.patch.object(seo_index, "decide", return_value={"indexable": True}),
			mock.patch.object(schema_builder, "build_digital_document") as sahte,
		):
			sahte.side_effect = [None, gecerli_nesne]
			sonuc = schema_builder._listing_document_objects(listing, "https://istoc.localhost")

		self.assertEqual(sonuc, [gecerli_nesne])
		self.assertEqual(sahte.call_count, 2)


class TestUploadPolicyPptxKabul(FrappeTestCase):
	"""Task 5 koordinatör kararı — `.pptx` bugüne kadar `upload_policy.EXTENSIONS`
	haritasında yoktu; `doc_meta.py` (Task 2) çıkarımı `.pptx`'i destekliyor
	olsa da `naming.py::_ALLOWED_EXTENSIONS` bu haritadan beslendiği için
	hiçbir `.pptx` dosyası `File` kaydı olarak yüklenemiyordu (Task 2 raporu,
	minor (b): "ölü kod"). Bu test `.pptx` içeriğinin artık `upload_policy.
	check()`'ten (kanca yolu, `media_endpoint=False`) geçtiğini doğruluyor."""

	def test_pptx_icerigi_check_ten_gecer(self):
		from tradehub_core.media import upload_policy

		pptx = _pptx_bytes(["Slayt bir metni", "Slayt iki metni"])
		karar = upload_policy.check(f"sunum-{_TUZ}.pptx", content=pptx, size=len(pptx))

		self.assertEqual(karar.kind, upload_policy.KIND_DOCUMENT)
		self.assertEqual(karar.file_name, f"sunum-{_TUZ}.pptx")

	def test_pptx_gercek_file_kaydi_olarak_yuklenebilir(self):
		"""Regresyon — Task 2'nin bayrakladığı "ölü kod" burada kapanıyor:
		`.pptx` artık `File.insert()` ile gerçekten kaydediliyor (önceden
		`naming.py`'nin hash adlandırma kapısında `ValueError` fırlatıyordu)."""
		pptx = _pptx_bytes(["Slayt bir metni"])
		doc = _belge(f"sunum-kayit-{_TUZ}.pptx", pptx)
		self.addCleanup(_sil, "File", doc.name)

		self.assertTrue(doc.file_url.endswith(".pptx"))


# ── Task 6 — Denetim kuralları: `missing_doc_title`/`missing_doc_text`/       ──
# ── `missing_doc_language` (`seo_audit._doc_bulgulari`)                       ──
#
# Karar belgesi: `.superpowers/sdd/2026-08-27-file-manager-seo/task-6-brief.md`.


def _ilan_belge_baglar_ozel(ilan_adi: str, file_url: str, *, title: str = "", language: str = ""):
	"""`_ilan_belge_baglar` (Task 3) ile AYNI append+save deseni, ama `title`/
	`language` parametrik. Paylaşılan `_ilan_belge_baglar` sabit `language="tr"`
	kullanıyor — onu değiştirmek diğer görevlerin (Task 3-5) testlerini
	etkileyebilirdi, bu yüzden Task 6'nın boş-dil/boş-başlık senaryoları için
	ayrı, dar kapsamlı bir yardımcı."""
	doc = frappe.get_doc("Listing", ilan_adi)
	onceki_sayi = len(doc.get("documents") or [])
	doc.append(
		"documents",
		{"file": file_url, "title": title, "doc_type": "Katalog", "language": language},
	)
	doc.save()

	def _geri_al():
		guncel = frappe.get_doc("Listing", ilan_adi)
		guncel.set("documents", (guncel.get("documents") or [])[:onceki_sayi])
		guncel.save()

	return _geri_al


class TestDocSeoBulgular(FrappeTestCase):
	"""`seo_audit._doc_bulgulari` — üç kural (title/text/language), yalnız
	`audit_file`'ın (`deep=True`) tekil yolunda ve yalnız DOC_UZANTILAR +
	vitrinde görünen bir ilana bağlı dosyalarda çalışmalı."""

	def test_bagli_belgede_uc_kural_da_warn_verir(self):
		"""Başlıksız, metni çıkarılmamış (mock'lu enqueue — `apply()` hiç
		çalışmadı) ve dili boş bırakılmış bir PDF, vitrinde görünen bir ilana
		bağlıyken üç kuralın ÜÇÜ de tetiklenmeli."""
		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"denetim-tam-{_TUZ}.pdf", _pdf_bytes(["denetim icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar_ozel(ilan["name"], doc.file_url, title="", language=""))

		sonuc = seo_audit.audit_file(doc.file_url, deep=True)
		kodlar = {b["code"] for b in sonuc["findings"]}

		self.assertIn("missing_doc_title", kodlar)
		self.assertIn("missing_doc_text", kodlar)
		self.assertIn("missing_doc_language", kodlar)

		# `_KURAL_BOYUT` haritası — brief'in boyut sözleşmesi.
		self.assertEqual(seo_audit._KURAL_BOYUT["missing_doc_title"], "metadata")
		self.assertEqual(seo_audit._KURAL_BOYUT["missing_doc_text"], "discoverability")
		self.assertEqual(seo_audit._KURAL_BOYUT["missing_doc_language"], "metadata")

	def test_alanlari_dolu_belgede_hicbir_kural_tetiklenmez(self):
		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"denetim-dolu-{_TUZ}.pdf", _pdf_bytes(["denetim icerigi dolu"]))
		self.addCleanup(_sil, "File", doc.name)
		frappe.db.set_value(
			"File",
			doc.name,
			{"th_media_title": "Dolu Başlık", "th_media_extracted_text": "dolu metin"},
			update_modified=False,
		)
		self.addCleanup(
			_ilan_belge_baglar_ozel(ilan["name"], doc.file_url, title="Dolu Başlık", language="tr")
		)

		sonuc = seo_audit.audit_file(doc.file_url, deep=True)
		kodlar = {b["code"] for b in sonuc["findings"]}

		self.assertNotIn("missing_doc_title", kodlar)
		self.assertNotIn("missing_doc_text", kodlar)
		self.assertNotIn("missing_doc_language", kodlar)

	#: 1x1 saydam PNG (gerçek, ayrıştırılabilir) — Frappe `File.save_file`
	#: EXIF temizliği için `Image.open` ile açmayı DENER; sahte/rastgele bayt
	#: `PIL.UnidentifiedImageError` fırlatır, bu yüzden `_dosya`'nın varsayılan
	#: metin içeriği burada KULLANILAMAZ.
	_PNG_1X1 = bytes.fromhex(
		"89504e470d0a1a0a0000000d494844520000000100000001080600000"
		"01f15c4890000000a49444154789c6300010000050001"
		"0d0a2db40000000049454e44ae426082"
	)

	def test_gorsel_uzantida_kurallar_calismaz(self):
		"""Uzantı `DOC_UZANTILAR` dışında (`.png`) — `Listing Document.file`
		serbest bir `Attach` olduğu için ilana bağlansa bile ilk koşul (uzantı)
		kapıyı kapatır (`TestDocIndexable.test_desteklenmeyen_uzanti_false`
		ile aynı koşul çifti)."""
		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _dosya(f"denetim-gorsel-{_TUZ}.png", icerik=self._PNG_1X1)
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar_ozel(ilan["name"], doc.file_url, title="", language=""))

		sonuc = seo_audit.audit_file(doc.file_url, deep=True)
		kodlar = {b["code"] for b in sonuc["findings"]}

		self.assertNotIn("missing_doc_title", kodlar)
		self.assertNotIn("missing_doc_text", kodlar)
		self.assertNotIn("missing_doc_language", kodlar)

	def test_baglanmamis_belgede_kurallar_calismaz(self):
		"""Hiçbir `Listing Document`'a bağlı değil — ikinci koşul (bağlılık)
		kapıyı kapatır, başlık/metin/dil boş olsa bile bulgu üretilmez."""
		doc = _belge(f"denetim-bagsiz-{_TUZ}.pdf", _pdf_bytes(["bagsiz icerik"]))
		self.addCleanup(_sil, "File", doc.name)

		sonuc = seo_audit.audit_file(doc.file_url, deep=True)
		kodlar = {b["code"] for b in sonuc["findings"]}

		self.assertNotIn("missing_doc_title", kodlar)
		self.assertNotIn("missing_doc_text", kodlar)
		self.assertNotIn("missing_doc_language", kodlar)

	def test_deep_false_ta_calismaz(self):
		"""`_watch_slug_bulgusu` ile AYNI sınır: `deep=False` (toplu denetimin
		ucuz yolu) bu üçünü de hiç çağırmaz."""
		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"denetim-sig-{_TUZ}.pdf", _pdf_bytes(["sig denetim icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar_ozel(ilan["name"], doc.file_url, title="", language=""))

		sonuc = seo_audit.audit_file(doc.file_url, deep=False)
		kodlar = {b["code"] for b in sonuc["findings"]}

		self.assertNotIn("missing_doc_title", kodlar)
		self.assertNotIn("missing_doc_text", kodlar)
		self.assertNotIn("missing_doc_language", kodlar)

	def test_audit_batch_deep_true_de_calismaz(self):
		"""`audit_batch` (toplu yol) `deep=True` olsa bile `_doc_bulgulari`'yı
		HİÇ çağırmaz — `_watch_slug_bulgusu` için zaten geçerli olan aynı
		maliyet gerekçesi (fonksiyon docstring'i + `audit_file` içindeki yorum)."""
		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = _belge(f"denetim-toplu-{_TUZ}.pdf", _pdf_bytes(["toplu denetim icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar_ozel(ilan["name"], doc.file_url, title="", language=""))

		sonuc = seo_audit.audit_batch([doc.file_url], deep=True)
		satir = next(r for r in sonuc["files"] if r["file_url"] == doc.file_url)
		kodlar = {b["code"] for b in satir["findings"]}

		self.assertNotIn("missing_doc_title", kodlar)
		self.assertNotIn("missing_doc_text", kodlar)
		self.assertNotIn("missing_doc_language", kodlar)

	def test_iki_ilanli_belge_birinde_bos_dil_varsa_warn_verir(self):
		"""Düzeltme turu 1 — `_doc_bulgulari` docstring'inin "dosya birden çok
		ilana bağlıysa HERHANGİ birinde boşsa WARN" iddiası bugüne kadar yalnız
		TEK ilanlı senaryolarla test edilmişti. Aynı dosya iki vitrinde görünen
		ilana bağlanıyor — biri dolu (`tr`), diğeri boş dil ile — ve kuralın
		HERHANGİ bir satırı yakaladığı burada doğrudan doğrulanıyor."""
		ilanlar = _iki_gorunur_ilan()
		if len(ilanlar) < 2:
			self.skipTest("Vitrinde görünen en az 2 ilan yok — çok-ilan fixture'ı kurulamaz.")
		ilan_a, ilan_b = ilanlar[0]["name"], ilanlar[1]["name"]

		doc = _belge(f"denetim-coklu-bosdil-{_TUZ}.pdf", _pdf_bytes(["coklu ilan bos dil icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar_ozel(ilan_a, doc.file_url, title="Ortak Başlık", language="tr"))
		self.addCleanup(_ilan_belge_baglar_ozel(ilan_b, doc.file_url, title="Ortak Başlık", language=""))

		sonuc = seo_audit.audit_file(doc.file_url, deep=True)
		kodlar = {b["code"] for b in sonuc["findings"]}

		self.assertIn("missing_doc_language", kodlar)

	def test_iki_ilanli_belge_ikisinde_de_dil_doluysa_warn_yok(self):
		"""Aynı çok-ilan kurulumunun ters ucu: HER iki bağlı satırda da dil
		doluysa (`tr`/`en`) `missing_doc_language` hiç tetiklenmemeli."""
		ilanlar = _iki_gorunur_ilan()
		if len(ilanlar) < 2:
			self.skipTest("Vitrinde görünen en az 2 ilan yok — çok-ilan fixture'ı kurulamaz.")
		ilan_a, ilan_b = ilanlar[0]["name"], ilanlar[1]["name"]

		doc = _belge(f"denetim-coklu-doludil-{_TUZ}.pdf", _pdf_bytes(["coklu ilan dolu dil icerigi"]))
		self.addCleanup(_sil, "File", doc.name)
		self.addCleanup(_ilan_belge_baglar_ozel(ilan_a, doc.file_url, title="Ortak Başlık", language="tr"))
		self.addCleanup(_ilan_belge_baglar_ozel(ilan_b, doc.file_url, title="Ortak Başlık", language="en"))

		sonuc = seo_audit.audit_file(doc.file_url, deep=True)
		kodlar = {b["code"] for b in sonuc["findings"]}

		self.assertNotIn("missing_doc_language", kodlar)
