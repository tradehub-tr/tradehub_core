"""Medya SEO şeması ve okuma kapısı — TUR-135 Dilim 1.

Karar belgesi: `docs/MEDYA-SEO-SOZLESMESI.md` · mimari: ADR-0023.

Bu dosyanın sabitlediği kurallar:
  1. Üç katman ve SIRASI: kullanım ezmesi → varlık varsayılanı → boş
  2. Çok dil fallback zinciri `resolve_content_field` ile aynı
  3. Ortak sahiplikte yazma sınırı (başka mağazanın metni ezilmez)
  4. Beyaz liste: yaşam döngüsü alanları SEO yazma yolundan geçemez
  5. Ezme anahtarı tekil (aynı kullanım için iki ezme olamaz)
  6. Yedek yeni alanları taşır (geri yüklemede SEO emeği kaybolmaz)
  7. **Doğrudan `th_media_alt` okuyan kod yazılmaz** — herkes `fields_for`'dan
     geçer; taşıma günü (metadata evi) tüketiciler değişmesin diye

Koşum:
    docker exec -w /home/frappe/frappe-bench istoc-backend bench \\
        --site tradehub.localhost run-tests \\
        --module tradehub_core.tests.test_media_seo
"""

from __future__ import annotations

import contextlib
import pathlib
import re
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import seo

_TUZ: str = frappe.generate_hash(length=10)


def _dosya(ad: str, *, icerik: bytes | None = None, kullanici: str | None = None):
	"""Gerçek `File` — tarama kancası nötr (test_media_av deseni)."""
	veri = icerik if icerik is not None else f"seo {_TUZ} {ad}".encode()
	with mock.patch("tradehub_core.media.av.enqueue_scan"):
		if kullanici:
			frappe.set_user(kullanici)
		try:
			doc = frappe.get_doc({"doctype": "File", "file_name": ad, "is_private": 0, "content": veri})
			doc.insert(ignore_permissions=True)
		finally:
			if kullanici:
				frappe.set_user("Administrator")
	return doc


def _kod_govdesi(yol: pathlib.Path) -> str:
	"""Dosyanın YORUM ve DOCSTRING'siz hâli.

	Ham metinde aramak yanlış alarm veriyordu: bu depoda kolon adları
	açıklama amacıyla yorumlarda geçiyor ("`th_media_alt` doğrudan okunmamalı"
	uyarısının kendisi bile eşleşiyordu). Kural KODU bağlar, belgeyi değil.
	"""
	import ast
	import io
	import tokenize

	ham = yol.read_text()
	try:
		# Yorumları at.
		parcalar = []
		for tok in tokenize.generate_tokens(io.StringIO(ham).readline):
			if tok.type != tokenize.COMMENT:
				parcalar.append(tok.string)
		govde = " ".join(parcalar)
		# Docstring'leri at (modül/sınıf/fonksiyon).
		agac = ast.parse(ham)
		for dugum in ast.walk(agac):
			if isinstance(dugum, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
				metin = ast.get_docstring(dugum, clean=False)
				if metin:
					govde = govde.replace(metin, "")
		return govde
	except (SyntaxError, tokenize.TokenError):
		return ham


def _sil(doctype: str, name: str) -> None:
	with contextlib.suppress(Exception):
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		frappe.db.commit()


class TestVarlikVarsayilani(FrappeTestCase):
	def test_bos_url_bos_sozluk(self):
		self.assertEqual(seo.fields_for(""), {})

	def test_yazilan_deger_okunur(self):
		doc = _dosya(f"varsayilan-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		seo.set_asset_fields(doc.file_url, {"alt": "kırmızı çanta", "creator": "Mağaza A"})

		alanlar = seo.fields_for(doc.file_url)
		self.assertEqual(alanlar["alt"], "kırmızı çanta")
		self.assertEqual(alanlar["creator"], "Mağaza A")
		self.assertFalse(alanlar["overridden"])

	def test_hicbir_katmanda_yoksa_bos_dize(self):
		"""Boş, yanlıştan iyidir: uydurma metin üretilmez, `None` da dönmez."""
		doc = _dosya(f"bos-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		alanlar = seo.fields_for(doc.file_url)
		self.assertEqual(alanlar["alt"], "")
		self.assertEqual(alanlar["caption"], "")
		self.assertEqual(alanlar["license_url"], "")

	def test_beyaz_liste_yasam_dongusunu_korur(self):
		"""`th_media_state` SEO yazma yolundan geçemez (metadata.py deseni)."""
		doc = _dosya(f"beyaz-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		onceki = frappe.db.get_value("File", doc.name, "th_media_state")

		seo.set_asset_fields(doc.file_url, {"state": "Trashed", "th_media_state": "Trashed"})

		self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_state"), onceki)

	def test_olculer_okunur(self):
		"""REGRESYON: `width/height` sorguya alınmazsa hep 0 döner.

		Yaşandı — 4.776 dosyanın ölçüsü doldurulduktan SONRA bile denetim
		"çözünürlük bilinmiyor" diyordu, çünkü kolonlar `SINGLE` listesinde
		olmadığı için hiç çekilmiyordu. Vitrin de sabit 800×800 basmaya
		devam ediyordu (CLS düzeltmesi kâğıt üstünde kalıyordu).
		"""
		doc = _dosya(f"olcu-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		frappe.db.set_value(
			"File", doc.name, {"th_media_width": 497, "th_media_height": 645}, update_modified=False
		)
		alanlar = seo.fields_for(doc.file_url)
		self.assertEqual(alanlar["width"], 497)
		self.assertEqual(alanlar["height"], 645)
		# Toplu okuma da aynı değeri vermeli (iki ayrı sorgu yolu var).
		toplu = seo.fields_for_many([doc.file_url])
		self.assertEqual(toplu[doc.file_url]["height"], 645)

	def test_bilinmeyen_alan_yok_sayilir(self):
		doc = _dosya(f"bilinmeyen-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		self.assertEqual(seo.set_asset_fields(doc.file_url, {"uydurma_alan": "x"}), 0)


class TestCokDil(FrappeTestCase):
	def test_istenen_dil_dolu_ise_o(self):
		doc = _dosya(f"dil1-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		seo.set_asset_fields(doc.file_url, {"alt_tr": "kırmızı çanta", "alt_en": "red bag"})

		self.assertEqual(seo.fields_for(doc.file_url, lang="en")["alt"], "red bag")
		self.assertEqual(seo.fields_for(doc.file_url, lang="tr")["alt"], "kırmızı çanta")

	def test_eksik_dil_varsayilana_duser(self):
		"""`resolve_content_field` ile AYNI zincir: istenen → varsayılan → eski kolon."""
		doc = _dosya(f"dil2-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		seo.set_asset_fields(doc.file_url, {"alt_tr": "yalnız türkçe"})

		self.assertEqual(seo.fields_for(doc.file_url, lang="ar")["alt"], "yalnız türkçe")

	def test_eski_tek_dil_kolonu_son_care(self):
		"""Yama öncesi yazılmış tek dilli değer kaybolmaz."""
		doc = _dosya(f"dil3-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		frappe.db.set_value("File", doc.name, "th_media_alt", "eski değer", update_modified=False)

		self.assertEqual(seo.fields_for(doc.file_url, lang="en")["alt"], "eski değer")


class TestKullanimEzmesi(FrappeTestCase):
	def _kur(self, etiket: str):
		doc = _dosya(f"{etiket}-{_TUZ}.txt")
		self.addCleanup(_sil, "File", doc.name)
		seo.set_asset_fields(doc.file_url, {"alt_tr": "varlık varsayılanı"})
		return doc

	def test_ezme_varsayilani_bastirir(self):
		"""§4.3 — aynı görsel, iki sayfa, iki alt metni."""
		doc = self._kur("ezme1")
		ad = seo.set_override(
			doc.file_url,
			ref_doctype="Listing",
			ref_name=f"LST-{_TUZ}",
			ref_field="primary_image",
			values={"alt": "ürün sayfası metni"},
		)
		self.addCleanup(_sil, seo.OVERRIDE_DOCTYPE, ad)

		urun = seo.fields_for(
			doc.file_url, ref_doctype="Listing", ref_name=f"LST-{_TUZ}", ref_field="primary_image"
		)
		self.assertEqual(urun["alt"], "ürün sayfası metni")
		self.assertTrue(urun["overridden"])

		# Başka kullanım — ezme YOK, varsayılan basılır
		blog = seo.fields_for(
			doc.file_url, ref_doctype="Blog Post", ref_name=f"BLG-{_TUZ}", ref_field="image"
		)
		self.assertEqual(blog["alt"], "varlık varsayılanı")
		self.assertFalse(blog["overridden"])

		# Bağlamsız okuma da varsayılanı verir
		self.assertEqual(seo.fields_for(doc.file_url)["alt"], "varlık varsayılanı")

	def test_ezmede_bos_alan_varsayilana_duser(self):
		"""Ezme yalnız YAZDIĞI alanı bastırır; caption boşsa varsayılan gelir."""
		doc = self._kur("ezme2")
		seo.set_asset_fields(doc.file_url, {"caption_tr": "varlık altyazısı"})
		ad = seo.set_override(
			doc.file_url,
			ref_doctype="Listing",
			ref_name=f"LST2-{_TUZ}",
			ref_field="image",
			values={"alt": "yalnız alt ezildi"},
		)
		self.addCleanup(_sil, seo.OVERRIDE_DOCTYPE, ad)

		alanlar = seo.fields_for(
			doc.file_url, ref_doctype="Listing", ref_name=f"LST2-{_TUZ}", ref_field="image"
		)
		self.assertEqual(alanlar["alt"], "yalnız alt ezildi")
		self.assertEqual(alanlar["caption"], "varlık altyazısı")

	def test_ayni_kullanim_icin_iki_ezme_olamaz(self):
		doc = self._kur("ezme3")
		anahtar = {"ref_doctype": "Listing", "ref_name": f"LST3-{_TUZ}", "ref_field": "image"}
		ad = seo.set_override(doc.file_url, **anahtar, values={"alt": "ilk"})
		self.addCleanup(_sil, seo.OVERRIDE_DOCTYPE, ad)
		# İkinci çağrı YENİ kayıt açmaz, mevcudu günceller
		ad2 = seo.set_override(doc.file_url, **anahtar, values={"alt": "ikinci"})
		self.assertEqual(ad, ad2)
		self.assertEqual(seo.fields_for(doc.file_url, **anahtar)["alt"], "ikinci")

		# Elle ikinci kayıt açmak controller tarafından reddedilir
		ikiz = frappe.get_doc({"doctype": seo.OVERRIDE_DOCTYPE, "file_url": doc.file_url, **anahtar})
		with self.assertRaises(frappe.DuplicateEntryError):
			ikiz.insert(ignore_permissions=True)

	def test_ezme_kaldirilinca_varsayilana_donulur(self):
		doc = self._kur("ezme4")
		anahtar = {"ref_doctype": "Listing", "ref_name": f"LST4-{_TUZ}", "ref_field": "image"}
		seo.set_override(doc.file_url, **anahtar, values={"alt": "geçici"})
		self.assertTrue(seo.clear_override(doc.file_url, **anahtar))

		self.assertEqual(seo.fields_for(doc.file_url, **anahtar)["alt"], "varlık varsayılanı")
		self.assertFalse(seo.clear_override(doc.file_url, **anahtar))

	def test_eksik_kullanim_bilgisi_reddedilir(self):
		doc = self._kur("ezme5")
		with self.assertRaises(frappe.ValidationError):
			seo.set_override(doc.file_url, ref_doctype="Listing", ref_name="", ref_field="image", values={})

	def test_ezme_kaynagi_alt_source_ezer(self):
		doc = self._kur("ezme6")
		anahtar = {"ref_doctype": "Listing", "ref_name": f"LST6-{_TUZ}", "ref_field": "image"}
		ad = seo.set_override(doc.file_url, **anahtar, values={"alt": "insan"}, source=seo.SOURCE_HUMAN)
		self.addCleanup(_sil, seo.OVERRIDE_DOCTYPE, ad)
		self.assertEqual(seo.fields_for(doc.file_url, **anahtar)["alt_source"], seo.SOURCE_HUMAN)


class TestOrtakSahiplik(FrappeTestCase):
	def test_store_verilince_baska_magazanin_metni_ezilmez(self):
		"""Aynı adrese ait iki kayıt; yazma yalnız hedef mağazaya (TUR-298 dersi)."""
		icerik = f"ortak {_TUZ}".encode()
		a = _dosya(f"ortak-a-{_TUZ}.txt", icerik=icerik)
		self.addCleanup(_sil, "File", a.name)
		b = frappe.get_doc(
			{"doctype": "File", "file_name": f"ortak-b-{_TUZ}.txt", "is_private": 0, "file_url": a.file_url}
		)
		b.flags.ignore_mandatory = True
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			b.insert(ignore_permissions=True)
		self.addCleanup(_sil, "File", b.name)

		# store=None → aynı adresteki TÜM kayıtlara yazar
		sayi = seo.set_asset_fields(a.file_url, {"alt_tr": "ortak metin"})
		self.assertEqual(sayi, 2)

		# Var olmayan mağaza → hiçbir kayda yazılmaz
		with mock.patch("tradehub_core.media.ownership.store_of", return_value="BASKA-MAGAZA"):
			self.assertEqual(seo.set_asset_fields(a.file_url, {"alt_tr": "x"}, store="HEDEF"), 0)
		self.assertEqual(frappe.db.get_value("File", a.name, "th_media_alt_tr"), "ortak metin")

	def test_dolu_metinli_kayit_tercih_edilir(self):
		"""Boş bir ikiz yüzünden dolu alt metni kaybolmaz."""
		icerik = f"tercih {_TUZ}".encode()
		a = _dosya(f"tercih-a-{_TUZ}.txt", icerik=icerik)
		self.addCleanup(_sil, "File", a.name)
		b = frappe.get_doc(
			{"doctype": "File", "file_name": f"tercih-b-{_TUZ}.txt", "is_private": 0, "file_url": a.file_url}
		)
		b.flags.ignore_mandatory = True
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			b.insert(ignore_permissions=True)
		self.addCleanup(_sil, "File", b.name)
		# Yalnız İKİNCİ kayıtta metin var
		frappe.db.set_value("File", b.name, "th_media_alt_tr", "yalnız b'de", update_modified=False)

		self.assertEqual(seo.fields_for(a.file_url)["alt"], "yalnız b'de")


class TestYedekKapsami(FrappeTestCase):
	def test_yeni_alanlar_yedek_listesinde(self):
		"""Yedeklenmeyen alan = geri yüklemede kaybolan insan emeği."""
		from tradehub_core.media import backup

		alanlar = set(backup.FIELDS) if hasattr(backup, "FIELDS") else set()
		if not alanlar:
			# Alan listesi modül düzeyinde başka adla duruyorsa metinden oku.
			kaynak = pathlib.Path(backup.__file__).read_text()
			alanlar = set(re.findall(r'"(th_media_[a-z_]+)"', kaynak))
		for beklenen in (
			"th_media_caption",
			"th_media_alt_source",
			"th_media_creator",
			"th_media_license_url",
			"th_media_scan_status",
		):
			self.assertIn(beklenen, alanlar, f"{beklenen} yedek kapsamında değil")

	def test_dil_kolonlari_yedege_uretiliyor(self):
		from tradehub_core.media import backup

		kaynak = pathlib.Path(backup.__file__).read_text()
		self.assertIn('f"th_media_{alan}_{lang}"', kaynak)


class TestTekKapiKurali(FrappeTestCase):
	def test_tuketiciler_dogrudan_kolon_okumaz(self):
		"""ADR-0023: SEO alanları TEK kapıdan okunur.

		Metadata evi taşındığı gün (File → Media Asset) yalnız `media/seo.py`
		değişsin; ImageObject üreticisi, sitemap, API ve vitrin değişmesin.
		Bu test o kuralı mekanik hale getirir: `media/seo.py`, `metadata.py`
		(satıcının kendi düzenleme yüzü), `inventory.py`/`backup.py`
		(alan listesi taşıyıcıları) ve yamalar dışında hiçbir modül
		`th_media_alt` kolonunu doğrudan anmamalı.
		"""
		kok = pathlib.Path(seo.__file__).resolve().parents[1]
		muaf = {
			"media/seo.py",
			"media/metadata.py",
			"media/backup.py",
			"media/backup_export.py",
			"media/seller_backup.py",
			"media/seller_backup_export.py",
			"media/inventory.py",
			# Geri doldurma ADAYLARINI SQL'de süzüyor ("alt metni boş olanlar"):
			# 5.873 dosyayı tek tek `fields_for`'dan geçirmek N+1 olurdu
			# (anti-patterns.md §6). Okuma değil SEÇME; yazma yine kapıdan.
			"media/seo_generate.py",
		}
		ihlal = []
		for yol in kok.rglob("*.py"):
			bag = yol.relative_to(kok).as_posix()
			if bag.startswith(("patches/", "tests/")) or bag in muaf:
				continue
			if "th_media_alt" in _kod_govdesi(yol):
				ihlal.append(bag)
		self.assertEqual(ihlal, [], f"doğrudan th_media_alt okuyan modüller: {ihlal}")
