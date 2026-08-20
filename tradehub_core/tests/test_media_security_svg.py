"""T-131 — SVG sanitize'ın SALDIRI karşısındaki davranışı. **Frappe gerekmez.**

`tests/test_svg_sanitize.py` modülün sözleşmesini (politika kaynağı, tavanlar,
serileştirme, dayanıklılık) doğruluyor. Bu dosya farklı bir soruyu soruyor:
**gerçek saldırı yükleri çıktıda hayatta kalıyor mu.**

Yöntem
------
Her vektör tam bir SVG dosyası olarak kurulur, `sanitize()`'dan geçirilir ve
çıktı BAYT düzeyinde taranır. Test "şu element silindi mi" diye sormaz —
saldırının izi (script/onload/javascript/harici host…) çıktıda var mı diye
sorar. Böylece bir vektör allowlist'i atlatacak yeni bir yol bulursa
(namespace öneki, SMIL, CSS `@import`, entity kodlaması) test yakalar.

Namespace URI'leri (`http://www.w3.org/2000/svg`) meşru olarak `http://`
içerdiği için taramadan önce çıkarılır; aksi hâlde her çıktı "harici referans"
sanılırdı.

Gerçek dosyalar
---------------
`tradehub_core/public/` altında uygulamayla birlikte dağıtılan **130 SVG** var
(sertifika rozetleri + demo ürün görselleri). Bunlar sanitize'dan geçirilip
hem reddedilmedikleri hem de neyi kaybettikleri ÖLÇÜLÜR — ölçüm
`docs/reports/38-t017-guvenlik-kapisi.md` §4'te.

    python3 -m unittest tradehub_core.tests.test_media_security_svg -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.security import svg  # noqa: E402

PUBLIC = ROOT / "tradehub_core" / "public"

BAS = (
	'<svg xmlns="http://www.w3.org/2000/svg" '
	'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
)
SON = '<rect width="10" height="10" fill="#0b57a4"/></svg>'

#: Çıktıda BULUNMAMASI gereken izler. Element adı değil, saldırının kendisi.
IZLER: tuple[bytes, ...] = (
	b"<script",
	b"onload",
	b"onerror",
	b"onmouseover",
	b"javascript",
	b"vbscript",
	b"foreignobject",
	b"@import",
	b"@font-face",
	b"expression(",
	b"<iframe",
	b"kotu.example",
	b"data:text/html",
	b"etc/passwd",
	b"http://",
	b"https://",
)

#: Meşru olarak `http://` taşıyan namespace URI'leri — taramadan çıkarılır.
NAMESPACE_URI: tuple[bytes, ...] = (
	b"http://www.w3.org/2000/svg",
	b"http://www.w3.org/1999/xlink",
	b"http://www.w3.org/xml/1998/namespace",
	b"http://www.w3.org/2001/xml-events",
	b"http://www.w3.org/1999/xhtml",
)

#: Vektör → SVG kaynağı. Hepsi tam, ayrıştırılabilir dosyadır.
VEKTORLER: dict[str, str] = {
	"script_duz": BAS + "<script>alert(1)</script>" + SON,
	"script_cdata": BAS + "<script><![CDATA[alert(1)]]></script>" + SON,
	"script_namespace_onekli": (
		'<svg:svg xmlns:svg="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
		"<svg:script>alert(1)</svg:script>"
		'<svg:rect width="10" height="10"/></svg:svg>'
	),
	"onload_kok_elementinde": (
		'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" onload="alert(1)">' + SON
	),
	"onload_buyuk_harf": (
		'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" ONLOAD="alert(1)">' + SON
	),
	"onmouseover_cizimde": BAS + '<rect width="10" height="10" onmouseover="alert(1)"/>' + SON,
	"foreignobject_xhtml": (
		BAS
		+ '<foreignObject width="10" height="10">'
		+ '<div xmlns="http://www.w3.org/1999/xhtml">'
		+ '<img src="x" onerror="alert(1)"/></div></foreignObject>'
		+ SON
	),
	"a_xlink_javascript": (
		BAS + '<a xlink:href="javascript:alert(1)"><rect width="10" height="10"/></a>' + SON
	),
	"a_duz_href_javascript": (
		BAS + '<a href="javascript:alert(1)"><rect width="10" height="10"/></a>' + SON
	),
	"use_harici_dosya": BAS + '<use xlink:href="https://kotu.example/x.svg#p"/>' + SON,
	"use_goreli_yol": BAS + '<use xlink:href="../../etc/passwd"/>' + SON,
	"use_data_uri": BAS + '<use xlink:href="data:image/svg+xml;base64,PHN2Zy8+"/>' + SON,
	"image_harici_izleyici": (
		BAS + '<image href="https://kotu.example/izle.png" width="10" height="10"/>' + SON
	),
	"image_data_text_html": (
		BAS
		+ '<image href="data:text/html,&lt;script&gt;alert(1)&lt;/script&gt;" '
		+ 'width="10" height="10"/>'
		+ SON
	),
	"style_css_import": BAS + '<style>@import url("https://kotu.example/x.css");</style>' + SON,
	"style_font_face": (
		BAS + "<style>@font-face{font-family:x;src:url(https://kotu.example/f.woff)}</style>" + SON
	),
	"style_attr_expression": (
		BAS + '<rect width="10" height="10" style="width:expression(alert(1))"/>' + SON
	),
	"fill_harici_url": (
		BAS + '<rect width="10" height="10" fill="url(https://kotu.example/x.svg#g)"/>' + SON
	),
	"smil_set_onload": (
		BAS
		+ '<rect width="10" height="10"><set attributeName="onload" to="alert(1)"/></rect>'
		+ SON
	),
	"smil_animate_href": (
		BAS
		+ '<rect width="10" height="10"/>'
		+ '<animate attributeName="xlink:href" values="javascript:alert(1)"/>'
		+ SON
	),
	"xml_events_handler": (
		BAS
		+ '<handler xmlns:ev="http://www.w3.org/2001/xml-events" ev:event="load">alert(1)</handler>'
		+ SON
	),
	"iframe_gomulu": BAS + '<iframe src="https://kotu.example"></iframe>' + SON,
	"javascript_entity_kodlu": (
		BAS + '<a xlink:href="&#106;avascript:alert(1)"><rect width="10" height="10"/></a>' + SON
	),
	"javascript_bosluk_kacisi": (
		BAS + '<a xlink:href="java\tscript:alert(1)"><rect width="10" height="10"/></a>' + SON
	),
	"meta_refresh": (
		BAS + '<meta http-equiv="refresh" content="0;url=https://kotu.example"/>' + SON
	),
}

#: Ayrıştırıcıya HİÇ verilmemesi gereken girdiler — sanitize değil RET.
#: Değerler BAYT: gzip sihirli baytı (`1f 8b`) metin olarak yazılırsa UTF-8
#: kodlaması onu iki ayrı bayta çevirir ve kontrol edilen şey artık gzip olmaz.
RET_BEKLENEN: dict[str, tuple[bytes, str]] = {
	"doctype_entity": (
		b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]>'
		b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
		b'<rect width="10" height="10"/></svg>',
		svg.KOD_DTD_FORBIDDEN,
	),
	"xxe_harici_entity": (
		b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
		b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
		b'<desc>&xxe;</desc><rect width="10" height="10"/></svg>',
		svg.KOD_DTD_FORBIDDEN,
	),
	# Gerçek gzip akışı — `.svgz` yeniden adlandırılarak `.svg` diye gelirse.
	"gzip_svgz": (
		__import__("gzip").compress(
			b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
			b'<rect width="10" height="10"/></svg>'
		),
		svg.KOD_COMPRESSED,
	),
}


def _temiz_tarama(cikti: bytes) -> list[str]:
	"""Çıktıdaki saldırı izleri — namespace URI'leri düşülerek."""
	dusuk = cikti.lower()
	for uri in NAMESPACE_URI:
		dusuk = dusuk.replace(uri, b"")
	return [iz.decode() for iz in IZLER if iz in dusuk]


class AktifIcerikVektorleri(unittest.TestCase):
	"""Her vektör: sanitize sonrası çıktıda saldırının izi KALMAZ."""

	def test_hicbir_vektor_ciktida_hayatta_kalmaz(self):
		for ad, kaynak in sorted(VEKTORLER.items()):
			with self.subTest(vektor=ad):
				sonuc = svg.sanitize(kaynak.encode("utf-8"))
				iz = _temiz_tarama(sonuc.content or b"")
				self.assertEqual(iz, [], f"{ad}: çıktıda saldırı izi kaldı → {sonuc.content!r}")

	def test_vektorler_ayristirilabilir_kaldi(self):
		"""Sanitize edilmiş çıktı hâlâ geçerli XML olmalı — bozuk çıktı
		üretmek, sorunu aşağı akışa ötelemektir."""
		import xml.etree.ElementTree as ET

		for ad, kaynak in sorted(VEKTORLER.items()):
			sonuc = svg.sanitize(kaynak.encode("utf-8"))
			if not sonuc.ok or not sonuc.content:
				continue
			with self.subTest(vektor=ad):
				ET.fromstring(sonuc.content)

	def test_foreignobject_alt_agaciyla_birlikte_gider(self):
		sonuc = svg.sanitize(VEKTORLER["foreignobject_xhtml"].encode("utf-8"))
		self.assertNotIn(b"img", (sonuc.content or b"").lower())
		self.assertNotIn(b"div", (sonuc.content or b"").lower())

	def test_namespace_onekli_script_de_silinir(self):
		"""`<svg:script>` yerel adı `script`'tir; ön ek arkasına saklanamaz."""
		sonuc = svg.sanitize(VEKTORLER["script_namespace_onekli"].encode("utf-8"))
		self.assertTrue(sonuc.ok, sonuc.kod)
		self.assertNotIn(b"script", (sonuc.content or b"").lower())


class AyristiriciyaVerilmeyenler(unittest.TestCase):
	"""DTD/ENTITY/gzip: temizlenmez, REDDEDİLİR (bellek ayrıştırmadan önce gider)."""

	def test_beklenen_kodla_reddedilir(self):
		for ad, (kaynak, kod) in sorted(RET_BEKLENEN.items()):
			with self.subTest(vektor=ad):
				sonuc = svg.sanitize(kaynak)
				self.assertFalse(sonuc.ok, f"{ad} kabul edildi")
				self.assertEqual(sonuc.kod, kod)
				self.assertFalse(sonuc.content, "ret durumunda içerik dönmemeli")


class MetinIcerigi(unittest.TestCase):
	"""Kaçışlanmış metin ZARARSIZDIR ve korunur — aşırı temizlik de bir hatadır."""

	def test_desc_icindeki_kacisli_metin_kacisli_kalir(self):
		kaynak = BAS + "<desc>&lt;script&gt;alert(1)&lt;/script&gt;</desc>" + SON
		sonuc = svg.sanitize(kaynak.encode("utf-8"))
		self.assertTrue(sonuc.ok, sonuc.kod)
		cikti = sonuc.content or b""
		# Metin korunur ama KAÇIŞLI: tarayıcı bunu çalıştıramaz.
		self.assertIn(b"&lt;script&gt;", cikti)
		self.assertNotIn(b"<script", cikti)


class GercekSvgKorpusu(unittest.TestCase):
	"""Uygulamayla dağıtılan 130 SVG — meşru yol ölçülür, varsayılmaz."""

	@classmethod
	def setUpClass(cls):
		if not PUBLIC.is_dir():
			raise unittest.SkipTest(f"public dizini yok: {PUBLIC}")
		cls.dosyalar = sorted(
			p for p in PUBLIC.rglob("*") if p.is_file() and p.suffix.lower() in (".svg", ".svgz")
		)

	def test_korpus_bos_degil(self):
		self.assertGreaterEqual(len(self.dosyalar), 100, "SVG korpusu beklenenden küçük")

	def test_hicbiri_reddedilmez(self):
		for p in self.dosyalar:
			with self.subTest(dosya=p.name):
				sonuc = svg.sanitize(p.read_bytes())
				self.assertTrue(sonuc.ok, f"{p.name} reddedildi: {sonuc.kod}")

	def test_hicbirinde_aktif_icerik_yok(self):
		"""Depoda duran SVG'lerin kendisi temiz mi — tedarik zinciri kontrolü."""
		for p in self.dosyalar:
			ham = p.read_bytes().lower()
			with self.subTest(dosya=p.name):
				self.assertNotIn(b"<script", ham)
				self.assertNotIn(b"onload=", ham)
				self.assertNotIn(b"<foreignobject", ham)

	def test_metin_kaybi_olculur_ve_bilinir(self):
		"""ÖLÇÜM, iddia değil: allowlist'te `text`/`tspan` YOK. Bu korpustaki
		rozetler metin taşıyor ve sanitize onları siliyor. Sayı burada
		sabitlenir ki allowlist değişirse fark görülsün
		(`docs/reports/38-t017-guvenlik-kapisi.md` §4)."""
		silinen = 0
		for p in self.dosyalar:
			sonuc = svg.sanitize(p.read_bytes())
			silinen += sum(
				1 for b in sonuc.bulgular if b.tur == svg.TUR_ELEMENT and b.ad == "text"
			)
		self.assertGreater(
			silinen, 0, "korpus değişmiş: artık hiç <text> silinmiyor, ölçüm güncellenmeli"
		)


if __name__ == "__main__":
	unittest.main(verbosity=2)
