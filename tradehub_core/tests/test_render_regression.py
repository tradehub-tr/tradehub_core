"""T-067 — Türev üretiminin REGRESYON kilidi.

Bu dosya `test_render.py`den farklı bir iş yapar. Orası davranışı sentetik
görsellerle DOĞRULAR; burası gerçek fixture üzerinde ÖLÇÜLMÜŞ sayıları
KİLİTLER. Amaç tek bir soruya cevap vermek: "bugün yaptığım değişiklik türev
merdivenini sessizce bozdu mu?"

Kilitlenen değerler üç sınıfa ayrılır ve HER BİRİ FARKLI SIKILIKTA kontrol
edilir — hepsini aynı katılıkta kilitlemek testi kırılgan yapardı:

  1. **Geometri** — saf aritmetik, ortamdan bağımsız. TAM eşitlik.
  2. **Matris** — politikadaki profil × biçim sayısı. TAM eşitlik. Bir slot
     dosyasına profil eklenirse test kırılır; kırılması DOĞRUDUR.
  3. **Bayt / SSIM** — encoder ve SSIM arka ucuna bağlı. TOLERANSLI, ve YALNIZ
     üretim yapılandırmasında (numpy kurulu) koşar.

ÜRETİM YAPILANDIRMASI NEDİR — VE NEDEN ÖNEMLİ
---------------------------------------------
Bayt temel çizgisi **konteynerden** alındı, yerel makineden değil:

    istoc-dev-backend-1 · Pillow 12.2.0 · Python 3.11.6 · numpy 2.4.6 · aarch64

Sebebi ölçüldü. `quality/ssim.py::compute_ssim` numpy YOKSA her iki görseli de
`PURE_MAX_PIXELS` (512×512) altına indirip öyle ölçer. Küçültme sıkıştırma
artefaktlarını siler, SSIM İYİMSER çıkar ve adaptif kalite arama gereğinden
DÜŞÜK kalite seçer. Aynı fixture, aynı kod, iki ortam:

    profil   numpy VAR (üretim)        numpy YOK (vekil SSIM)
    w768     q70 · 39.689 B · 0,9747   q70 · 28.456 B · 0,9882
    w1280    q82 · 258.309 B · 0,9604  q70 ·  53.131 B · 0,9913   ← 4,9 kat
    w1920    q82 · 722.296 B · 0,9626  q70 · 289.860 B · 0,9950   ← 2,5 kat

Sapma tam da `PURE_MAX_PIXELS` eşiğinin üstünde başlıyor (w768 tuvali 589.824
piksel > 262.144). Yani numpy'siz ortamda ölçülen SSIM ile üretimde ölçülen
SSIM AYNI SAYI DEĞİLDİR ve kalite kapısı sessizce gevşer. `render.py` bunu
artık künyeye yazıyor (`ssim_proxy`, `NOTE_SSIM_PROXY`) ve rapor UYARI basıyor;
bu dosya da bayt temel çizgisini vekil ortamda koşmayı REDDEDER.

Ham çıktılar:
    docs/data/t063-render-olcum.json                 (konteyner, üretim)
    docs/data/t063-render-olcum-yerel-vekilssim.json (yerel, vekil — karşılaştırma)
Koşum betiği: `scripts/measure_render_t063.py`

Koşum:

    python3 -m unittest tests.test_render_regression -v
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
if str(KOK) not in sys.path:
	sys.path.insert(0, str(KOK))

from tradehub_core.media.pipeline.image import render as R  # noqa: E402
from tradehub_core.media.pipeline.image import report as REP  # noqa: E402

FIXTURE = KOK / "tradehub_core" / "tests" / "fixtures" / "media" / "images" / "ok_product_1x1_2400.jpg"
SLOT = "product.image"


def _numpy_var() -> bool:
	try:
		import numpy  # noqa: F401

		return True
	except Exception:
		return False


NUMPY_VAR = _numpy_var()
URETIM_YAPILANDIRMASI = (
	"bayt/SSIM temel çizgisi numpy KURULU ortamda ölçüldü (konteyner). numpy yoksa "
	"SSIM küçültülmüş vekil üzerinden ölçülür, adaptif kalite başka bir kalite seçer "
	"ve baytlar 4,9 kata kadar sapar — bu testler o ortamda anlamlı değildir."
)

# --- Temel çizgi (ÖLÇÜLDÜ, uydurulmadı) -------------------------------------

KAYNAK_BAYT = 1_070_387
KAYNAK_OLCU = (2400, 2400)

BAYT_TOLERANSI = 0.15
"""Encoder sürümü değişince baytlar kayar. ÖLÇÜLDÜ: aynı numpy'li yapılandırmada
libavif sürüm farkı w384'te %14 bayt farkı üretti. ±%15 dışına çıkan sapma bir
HATA DEĞİL bir HABERDİR: encoder değişmiş, temel çizgi yeniden ölçülmeli."""

#: `product.image` üretim zinciri — konteyner (numpy 2.4.6 · Pillow 12.2.0),
#: 2026-08-18. (profil, kazanan biçim, genişlik, bayt, kalite, SSIM)
URETIM_ZINCIRI = (
	("w96", "webp", 96, 3_484, 80, 0.96716),
	("w192", "webp", 192, 7_144, 70, 0.96039),
	("w384", "avif", 384, 17_138, 70, 0.99141),
	("w640", "avif", 640, 30_114, 70, 0.98254),
	("w768", "avif", 768, 39_689, 70, 0.97467),
	("w1280", "avif", 1280, 258_309, 82, 0.96036),
	("w1920", "avif", 1920, 722_296, 82, 0.96262),
)
URETIM_TOPLAM_BAYT = 1_078_174
URETIM_KAYNAGA_ORAN = 1.007
"""ÖLÇÜM — merdivenin tamamı kaynağın 1,007 KATI. Yani 7 basamaklı `srcset`
BEDAVA DEĞİLDİR: varlık başına master kadar daha yer ister. Bugünkü tek çıktı
(engine.to_webp, 303.670 bayt) ile karşılaştırıldığında depolama 3,55 kat artar.
Bu bir kusur değil, planlanması gereken bir maliyettir."""

BUGUNKU_TEK_CIKTI_BAYT = 303_670
"""`tradehub_core/media/pipeline.py::to_webp` — bugün varlık başına üretilen TEK
çıktı, aynı fixture, aynı konteyner."""

#: 2400×2400 kaynaktan beklenen tuval ölçüleri. Saf aritmetik — TAM eşitlik.
GEOMETRI_ALTIN = {
	"w96": (96, 96),
	"w192": (192, 192),
	"w384": (384, 384),
	"w640": (640, 640),
	"w768": (768, 768),
	"w1280": (1280, 1280),
	"w1920": (1920, 1920),
}

#: Politika matrisi — slot başına tanımlı rendition sayısı (profil × biçim).
#:
#: 2026-08-19: `brand.logo` ve `seller.logo` 5 → 6 (toplam 48 → 50). Sebep,
#: logo K3 kararının ÖLÇÜMLE B'ye dönmesi: 18 gerçek logoda w512 rung'unun
#: baytı ölçüldü (p50 27.162 B ≈ referans 27.128 B, max 109.172 B, **5/18
#: dosya 40 KiB tavanını AŞIYOR**), tetik ateşledi ve iki politikaya `w384`
#: rung'u eklendi. Ayrıntı: `docs/standards/logo.md` §13-K3.
#: Bu kilit çalıştığı için değişiklik yakalandı — matrisin sessizce kaymasını
#: engellemesi tam olarak amacı.
MATRIS_ALTIN = {
	"brand.logo": 6,
	"category.banner": 6,
	"company.cover_image": 10,
	"company.cover_video": 3,
	"document.attachment": 1,
	"product.image": 12,
	"product.video": 3,
	"seller.logo": 6,
	"user.avatar": 3,
	"_toplam": 50,
}


def _tolerans_icinde(gelen: int, temel: int, oran: float = BAYT_TOLERANSI) -> bool:
	return abs(gelen - temel) <= temel * oran


def _kucuk_kaynak() -> bytes:
	"""Her slotun EN GENİŞ profilinden dar bir kaynak — upscale yasağı için."""
	from PIL import Image

	im = Image.new("RGB", (48, 48))
	pks = im.load()
	for y in range(48):
		for x in range(48):
			pks[x, y] = (x * 5 % 256, 128, y * 5 % 256)
	buf = io.BytesIO()
	im.save(buf, "PNG")
	return buf.getvalue()


@unittest.skipUnless(FIXTURE.is_file(), "fixture yok")
class FixtureYapisiTesti(unittest.TestCase):
	"""Gerçek fixture — ORTAMDAN BAĞIMSIZ olanlar. Her yerde koşar.

	Burada bayt YOKTUR: basamak sayısı, kazanan biçim, ölçü, artan genişlik,
	determinizm ve INV-05 gibi encoder sürümünden etkilenmeyen şeyler."""

	@classmethod
	def setUpClass(cls):
		cls.kaynak = FIXTURE.read_bytes()
		cls.sonuclar = R.render_ladder(cls.kaynak, SLOT)
		cls.isim = {r.profile.name: r for r in cls.sonuclar}

	def test_fixture_degismedi(self):
		"""Temel çizgi bu dosyaya ait — fixture değiştiyse sayılar da geçersizdir."""
		self.assertEqual(len(self.kaynak), KAYNAK_BAYT)
		im, _icc, _n = R.prepare_source(self.kaynak)
		self.assertEqual(im.size, KAYNAK_OLCU)

	def test_merdiven_basamak_sayisi(self):
		self.assertEqual(len(self.sonuclar), len(URETIM_ZINCIRI))
		self.assertEqual([r.profile.name for r in self.sonuclar], [x[0] for x in URETIM_ZINCIRI])

	def test_kazanan_bicimler_degismedi(self):
		"""INV-05 zincirinin hangi biçimde durduğu davranıştır — sessizce kaymamalı."""
		for ad, bicim, _w, _b, _q, _s in URETIM_ZINCIRI:
			self.assertEqual(self.isim[ad].format, bicim, f"{ad}: kazanan biçim değişti")

	def test_genislikler_tam_eslesir(self):
		for ad, _f, w, _b, _q, _s in URETIM_ZINCIRI:
			r = self.isim[ad]
			self.assertEqual((r.width, r.height), (w, w), f"{ad}: ölçü değişti")



	def test_ssim_hedefin_altina_dusmez(self):
		"""Kalite kapısı: her basamak politikadaki hedefi TUTMALI."""
		for r in self.sonuclar:
			self.assertGreater(r.ssim_target, 0.0, f"{r.name}: hedef okunamadı")
			self.assertGreaterEqual(
				r.ssim, r.ssim_target,
				f"{r.name}: SSIM {r.ssim:.5f} < hedef {r.ssim_target}",
			)


	def test_encode_butcesi_asilmadi(self):
		for r in self.sonuclar:
			self.assertLessEqual(r.encodes, R.DEFAULT_MAX_ENCODES, f"{r.name}: {r.encodes} encode")

	def test_inv05_hicbir_turev_kaynaktan_buyuk_degil(self):
		for r in self.sonuclar:
			self.assertLess(r.size_bytes, len(self.kaynak), f"{r.name} kaynaktan büyük")


	def test_hicbir_basamak_passthrough_degil(self):
		for r in self.sonuclar:
			self.assertFalse(r.passthrough, f"{r.name} passthrough'a düştü")

	def test_upscale_yok(self):
		for r in self.sonuclar:
			self.assertLessEqual(r.width, KAYNAK_OLCU[0])
			self.assertFalse(r.upscale_blocked)

	def test_ciktilar_gercekten_acilabilir(self):
		from PIL import Image

		for r in self.sonuclar:
			with Image.open(io.BytesIO(r.content)) as im:
				self.assertEqual(im.size, (r.width, r.height), f"{r.name} ölçü uyuşmuyor")

	def test_srcset_uretilebilir(self):
		"""Görevin varlık sebebi: tek genişlikle `srcset` yazılamıyordu.

		Canlı ölçüm: 31 görselin 0'ında `srcset` var (docs/reports/03-render-envanteri.md).
		Merdiven ARTAN ve TEKİL genişlikler vermeli, yoksa `srcset` anlamsızdır.
		"""
		genislikler = [r.width for r in self.sonuclar]
		self.assertEqual(genislikler, sorted(genislikler), "genişlikler artan değil")
		self.assertEqual(len(genislikler), len(set(genislikler)), "yinelenen genişlik var")
		self.assertGreaterEqual(len(genislikler), 5, "srcset için basamak sayısı yetersiz")

	def test_determinizm_ayni_bayt(self):
		"""Aynı (kaynak, profil, biçim) her zaman AYNI baytları vermeli."""
		p = R.profile_for(SLOT, "w192")
		self.assertEqual(R.render(self.kaynak, p, None), R.render(self.kaynak, p, None))
		self.assertEqual(R.render(self.kaynak, p, None), self.isim["w192"].content)





@unittest.skipUnless(FIXTURE.is_file(), "fixture yok")
@unittest.skipUnless(NUMPY_VAR, URETIM_YAPILANDIRMASI)
class BaytTemelCizgisiTesti(unittest.TestCase):
	"""Bayt ve SSIM temel çizgisi — YALNIZ üretim yapılandırmasında (numpy kurulu).

	numpy'siz ortamda bu sınıf atlanır. Atlanması bir eksiklik değil, doğru
	davranıştır: orada ölçülen SSIM küçültülmüş vekile aittir ve adaptif kalite
	başka bir kalite seçer; o sayıları kilitlemek yanlış bir temel çizgiyi
	standart hâline getirirdi (ÖLÇÜLDÜ: w1280'de 4,9 kat bayt farkı).
	"""

	@classmethod
	def setUpClass(cls):
		cls.kaynak = FIXTURE.read_bytes()
		cls.sonuclar = R.render_ladder(cls.kaynak, SLOT)
		cls.isim = {r.profile.name: r for r in cls.sonuclar}

	def test_ssim_vekil_uzerinde_olculmedi(self):
		"""Bu sınıfın ön koşulu: hiçbir türev vekil SSIM ile ölçülmemiş olmalı."""
		for r in self.sonuclar:
			self.assertFalse(r.ssim_proxy, f"{r.name}: SSIM vekil üzerinde ölçüldü")
			self.assertEqual(r.ssim_backend, "numpy", f"{r.name}: arka uç {r.ssim_backend}")

	def test_baytlar_tolerans_icinde(self):
		for ad, _f, _w, temel, _q, _s in URETIM_ZINCIRI:
			gelen = self.isim[ad].size_bytes
			self.assertTrue(
				_tolerans_icinde(gelen, temel),
				f"{ad}: {gelen} bayt, temel çizgi {temel} (±%{BAYT_TOLERANSI * 100:.0f} dışında)",
			)

	def test_secilen_kaliteler_degismedi(self):
		"""Adaptif kalite aramasının vardığı kalite davranıştır — sessizce kaymamalı."""
		for ad, _f, _w, _b, temel_q, _s in URETIM_ZINCIRI:
			self.assertEqual(self.isim[ad].quality, temel_q, f"{ad}: seçilen kalite değişti")

	def test_ssim_temel_cizgiden_belirgin_sapmaz(self):
		for ad, _f, _w, _b, _q, temel in URETIM_ZINCIRI:
			self.assertAlmostEqual(
				self.isim[ad].ssim, temel, delta=0.01, msg=f"{ad}: SSIM temel çizgiden saptı"
			)

	def test_toplam_bayt_tolerans_icinde(self):
		toplam = sum(r.size_bytes for r in self.sonuclar)
		self.assertTrue(
			_tolerans_icinde(toplam, URETIM_TOPLAM_BAYT),
			f"merdiven toplamı {toplam} bayt, temel çizgi {URETIM_TOPLAM_BAYT}",
		)

	def test_merdiven_kaynak_kadar_yer_kapliyor_OLCUM(self):
		"""ÖLÇÜM — merdiven BEDAVA DEĞİL: kaynağın ~1,007 katı yer istiyor.

		Bu test bir hedef değil, bir GERÇEĞİN kilidi. Erken bir taslakta "toplam
		kaynaktan küçüktür" diye yazılmıştı ve yerelde geçiyordu; geçmesinin
		sebebi vekil SSIM'in kaliteyi olduğundan düşük seçmesiydi. Üretim
		yapılandırmasında oran 1,007. Depolama planı bu sayıya göre yapılır.
		"""
		toplam = sum(r.size_bytes for r in self.sonuclar)
		oran = toplam / len(self.kaynak)
		self.assertAlmostEqual(oran, URETIM_KAYNAGA_ORAN, delta=0.15, msg=f"oran {oran:.3f}")

	def test_bugunku_tek_ciktiya_gore_depolama_artisi(self):
		"""ÖLÇÜM — 7 basamak, bugünkü tek çıktının 3,55 katı yer kaplıyor."""
		toplam = sum(r.size_bytes for r in self.sonuclar)
		kat = toplam / BUGUNKU_TEK_CIKTI_BAYT
		self.assertGreater(kat, 2.0, "beklenen depolama artışı kaybolmuş — temel çizgiyi doğrula")
		self.assertLess(kat, 6.0, f"depolama artışı beklenenin çok üstünde: {kat:.2f}×")

	def test_en_ust_basamak_merdivenin_cogunu_yiyor(self):
		"""ÖLÇÜM — w1920 tek başına toplamın %67'si. Optimizasyon önce oraya bakmalı."""
		toplam = sum(r.size_bytes for r in self.sonuclar)
		pay = self.isim["w1920"].size_bytes / toplam
		self.assertGreater(pay, 0.5, f"w1920 payı {pay:.2%} — dağılım değişmiş")

	def test_rapor_karari_ok(self):
		rapor = REP.build_report(self.kaynak, self.sonuclar, slot_key=SLOT)
		self.assertEqual(rapor["verdict"], "ok", rapor["summary_tr"])
		self.assertEqual(rapor["quality"]["below_target"], [])
		self.assertEqual(rapor["quality"]["backend"], "numpy")
		self.assertEqual(rapor["quality"]["proxy_measured"], 0)


@unittest.skipUnless(FIXTURE.is_file(), "fixture yok")
@unittest.skipIf(NUMPY_VAR, "yalnız numpy YOKKEN anlamlı")
class VekilSsimUyarisiTesti(unittest.TestCase):
	"""numpy yoksa motor SUSMAMALI — künye ve rapor bunu söylemeli."""

	def test_buyuk_tuvalde_vekil_bayragi_kalkar(self):
		kaynak = FIXTURE.read_bytes()
		r = R.render_rendition(kaynak, R.profile_for(SLOT, "w1280"))
		self.assertTrue(r.ssim_proxy, "vekil ölçüm sessizce geçti")
		self.assertEqual(r.ssim_backend, "pure")
		self.assertIn(R.NOTE_SSIM_PROXY, r.notes)
		rapor = REP.build_report(kaynak, [r], slot_key=SLOT)
		kodlar = {f["code"] for f in rapor["findings"]}
		self.assertIn("ssim_proxy", kodlar)
		self.assertEqual(rapor["verdict"], "warn")


class MatrisKilidiTesti(unittest.TestCase):
	"""Politika dosyalarına sessiz profil eklenmesini/çıkarılmasını yakalar."""

	def test_matris_sayilari(self):
		self.assertEqual(R.matrix_size(), MATRIS_ALTIN)

	def test_slot_listesi(self):
		self.assertEqual(set(R.slot_keys()), set(MATRIS_ALTIN) - {"_toplam"})

	def test_toplam_tutarli(self):
		self.assertEqual(
			MATRIS_ALTIN["_toplam"], sum(v for k, v in MATRIS_ALTIN.items() if k != "_toplam")
		)

	def test_matris_bugunku_tek_ciktidan_buyuk(self):
		"""Görevin özü: bugün varlık başına 1 çıktı var, politika 12 istiyor."""
		self.assertEqual(MATRIS_ALTIN["product.image"], 12)
		self.assertGreater(MATRIS_ALTIN["product.image"], 1)


class GeometriKilidiTesti(unittest.TestCase):
	"""Encode YOK — bu testler ortamdan bağımsızdır, TAM eşitlik aranır."""

	def test_2400lik_kaynaktan_tuval_olculeri(self):
		for p in R.load_profiles(SLOT):
			plan = R.plan_geometry(KAYNAK_OLCU, p)
			self.assertEqual(plan.canvas_size, GEOMETRI_ALTIN[p.name], f"{p.name} ölçüsü kaydı")

	def test_hicbir_slotta_upscale_yok(self):
		"""48 rendition tanımının HİÇBİRİ 48×48 kaynağı büyütmemeli (FR-028)."""
		for slot in R.slot_keys():
			for p in R.load_profiles(slot):
				plan = R.plan_geometry((48, 48), p)
				self.assertLessEqual(plan.scale, 1.0 + 1e-9, f"{slot}/{p.name} büyüttü")
				self.assertLessEqual(max(plan.inner_size), 48, f"{slot}/{p.name} içerik büyüdü")

	def test_pad_profillerinde_oran_her_zaman_korunur(self):
		for slot in R.slot_keys():
			for p in R.load_profiles(slot):
				if p.fit != R.FIT_PAD or not p.target_ratio_value:
					continue
				for kaynak in ((2400, 2400), (2400, 800), (300, 1200), (48, 48)):
					plan = R.plan_geometry(kaynak, p)
					w, h = plan.canvas_size
					self.assertAlmostEqual(
						w / h, p.target_ratio_value, delta=0.02,
						msg=f"{slot}/{p.name} @ {kaynak}: oran bozuldu ({w}×{h})",
					)

	def test_cover_profilleri_hedef_orana_kirpar(self):
		for slot in R.slot_keys():
			for p in R.load_profiles(slot):
				if p.fit != R.FIT_COVER or not p.target_ratio_value:
					continue
				plan = R.plan_geometry((3000, 1000), p)
				_l, _t, cw, ch = plan.crop_box
				self.assertAlmostEqual(
					cw / ch, p.target_ratio_value, delta=0.02,
					msg=f"{slot}/{p.name}: kırpma penceresi hedef oranda değil",
				)


class TumSlotlarDavranisTesti(unittest.TestCase):
	"""Küçük bir kaynakla 9 slotun tamamı — çökme ve büyütme taraması."""

	@classmethod
	def setUpClass(cls):
		cls.kaynak = _kucuk_kaynak()

	def test_her_slot_uretilebilir_ve_buyutmez(self):
		for slot in R.slot_keys():
			sonuc = R.render_ladder(self.kaynak, slot)
			self.assertEqual(len(sonuc), len(R.load_profiles(slot)), f"{slot}: eksik basamak")
			for r in sonuc:
				self.assertLessEqual(r.width, 48, f"{slot}/{r.profile.name} büyüttü")
				self.assertLessEqual(
					r.size_bytes, len(self.kaynak), f"{slot}/{r.profile.name} kaynaktan büyük"
				)

	def test_kismi_merdiven_yok(self):
		"""Bir basamak üretilemezse RenderError yükselir; yarım `srcset` 404 demektir."""
		for slot in R.slot_keys():
			sonuc = R.render_ladder(self.kaynak, slot)
			self.assertTrue(all(r.content for r in sonuc), f"{slot}: boş içerik")


if __name__ == "__main__":
	unittest.main(verbosity=2)
