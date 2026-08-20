"""T-112 doğrulaması — 13 cihaz × 5 sayfa = 65 kombinasyonun tamamı.

Bu dosya üç ayrı soruyu ayrı ayrı cevaplar:

1. **Veri sağlam mı** — `devices.json` 13 cihaz, `placements.json` 5 sayfa;
   her bölgenin slotu politika kayıt defterinde tanımlı, her kutu kuralının
   `min_vw: 0` tabanı var.
2. **Hesap raporla uyuşuyor mu** — `docs/reports/03-render-envanteri.md`
   §3.1–§3.8'de ELLE hesaplanmış 19 kutu genişliği, buradaki kural motoruyla
   BİREBİR yeniden üretilir. Uyuşmazlık ya raporun ya motorun yanlış olduğunu
   söyler; ikisinin sessizce ayrışmasına izin verilmez.
3. **Merdiven yetiyor mu** — 65 kombinasyonun tamamı için seçilen türev
   hesaplanır, TABLOLANIR ve kaynak yetersizliği sayılır.

Çalıştırma (bench/site/DB GEREKMEZ, `import frappe` yok):

    cd /Users/ahmet/Desktop/istoc/tradehub_core
    python3 -m unittest tests.test_simulator_srcset -v

Tabloyu görmek için:

    python3 -m unittest tests.test_simulator_srcset.SimulatorTablosu -v
    # ya da doğrudan:
    PYTHONPATH=. python3 -m tradehub_core.media.pipeline.simulator.srcset --all --sizes
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.policy.engine import PolicyRegistry  # noqa: E402
from tradehub_core.media.pipeline.simulator import DEVICES_PATH, PLACEMENTS_PATH  # noqa: E402
from tradehub_core.media.pipeline.simulator.srcset import (  # noqa: E402
	WARN_OVERSHOOT,
	WARN_SOURCE_INSUFFICIENT,
	WARN_ZOOM_INSUFFICIENT,
	Device,
	Rendition,
	box_width,
	format_table,
	load_devices,
	load_layout,
	renditions_for,
	select_rendition,
	simulate_matrix,
	sizes_attribute,
	srcset_attribute,
	summarize,
)

# Canlıda ölçülen kısa kenar yüzdelikleri (docs/reports/02-medya-istatistigi.md):
# p50 = 1.120 px, p90 = 2.160 px. Kaynak genişliği bunlarla kelepçelenerek
# "gerçek korpusla ne olurdu" sorusu ölçülür.
KAYNAK_P50 = 1120
KAYNAK_P90 = 2160


def sahte_cihaz(css_width: int, css_height: int = 900, dpr: float = 1.0) -> Device:
	"""Rapor doğrulaması için tek genişlikli yardımcı cihaz."""
	return Device(
		id=f"vw{css_width}",
		label=f"vw{css_width}",
		device_class="test",
		css_width=css_width,
		css_height=css_height,
		dpr=dpr,
		physical_width=round(css_width * dpr),
		physical_height=round(css_height * dpr),
	)


class VeriButunlugu(unittest.TestCase):
	"""T-110 / T-111 çıktılarının kendi içinde tutarlılığı."""

	@classmethod
	def setUpClass(cls) -> None:
		cls.devices = load_devices()
		cls.layout = load_layout()
		cls.registry = PolicyRegistry()

	def test_13_cihaz_var_ve_kimlikler_tekil(self):
		self.assertEqual(len(self.devices), 13)
		kimlikler = [d.id for d in self.devices]
		self.assertEqual(len(set(kimlikler)), 13, f"tekrar eden cihaz kimliği: {kimlikler}")

	def test_cihaz_sinifi_ve_dpr_makul(self):
		siniflar = {"phone", "tablet", "laptop", "desktop"}
		for d in self.devices:
			with self.subTest(cihaz=d.id):
				self.assertIn(d.device_class, siniflar)
				self.assertGreater(d.dpr, 0)
				self.assertGreater(d.css_width, 0)
				self.assertGreater(d.css_height, 0)
				self.assertTrue(d.source, "her cihaz değerinin kaynağı yazılmalı")

	def test_fiziksel_piksel_css_carpi_dpr(self):
		"""`physical` alanı elle yazıldı — `round(css × dpr)` ile tutmalı."""
		for d in self.devices:
			with self.subTest(cihaz=d.id):
				self.assertEqual((d.physical_width, d.physical_height), d.hesaplanan_fiziksel)

	def test_tam_sayi_olmayan_dpr_temsil_ediliyor(self):
		"""1,75 ve 1,5 gibi kesirli DPR'ler merdivende yarım basamağa denk gelir."""
		kesirli = [d.id for d in self.devices if d.dpr != int(d.dpr)]
		self.assertGreaterEqual(len(kesirli), 2, f"kesirli DPR temsili yetersiz: {kesirli}")

	def test_5_sayfa_ve_birincil_bolge_tanimli(self):
		self.assertEqual(len(self.layout.pages), 5)
		for p in self.layout.pages:
			with self.subTest(sayfa=p.page):
				self.assertTrue(p.regions)
				self.assertIsNotNone(p.primary)

	def test_her_bolgenin_slotu_politikada_var(self):
		for r in self.layout.all_regions():
			with self.subTest(bolge=r.key):
				self.assertIn(r.slot_key, self.registry, f"{r.key} → tanımsız slot {r.slot_key}")

	def test_her_kutu_kuralinin_taban_adimi_var(self):
		"""`min_vw: 0` yoksa dar bir cihazda kural çözülemez."""
		for r in self.layout.all_regions():
			with self.subTest(bolge=r.key):
				self.assertIn(0, [int(a.get("min_vw", 0)) for a in r.box])

	def test_her_bolge_turetim_kaynagini_tasiyor(self):
		"""Sayı uydurulmadığının kanıtı: her bölge dosya:satır referansı taşır."""
		for r in self.layout.all_regions():
			with self.subTest(bolge=r.key):
				self.assertTrue(r.derived_from.strip(), f"{r.key} `derived_from` boş")
				self.assertTrue(r.render_point.strip(), f"{r.key} `render_point` boş")

	def test_dislanan_bolgeler_gerekcesiyle_yazilmis(self):
		"""Hesaplanamayan bölge sessizce atlanmaz; gerekçesi dosyada durur."""
		ham = json.loads(PLACEMENTS_PATH.read_text(encoding="utf-8"))
		dislanan = ham.get("excluded_regions") or []
		self.assertTrue(dislanan)
		for d in dislanan:
			with self.subTest(bolge=d.get("region")):
				self.assertTrue(d.get("reason", "").strip())

	#: T-115 (2026-08-20) drift ölçümünün DOKUNMADIĞI bölgeler. Bunların kutuları
	#: hâlâ yalnız CSS'ten aritmetik türetme; katalog bunu gizlememeli.
	DOGRULANMAMIS_BOLGELER = (
		"home/tailored_grid",
		"listing/brand_grid",
		"product_detail/related_slider",
		"product_detail/lightbox_thumb",
		"cart_checkout/sku_row",
		"cart_checkout/product_item",
		"cart_checkout/drawer_thumb",
	)

	def test_olcum_durumu_ilan_edilmis(self):
		"""Emüle/hesaplanmış değerler 'ölçüldü' gibi sunulmamalı.

		2026-08-20'de 15 bölgenin 8'i gerçek tarayıcıda doğrulandı, 7'si
		DOĞRULANMADI. Eski hâlde bu test kataloğun "hiç doğrulanmadı" demesini
		şart koşuyordu; artık bu YANLIŞ olurdu. Yeni kural iki yönlü: katalog
		ne tam doğrulanmış numarası yapabilir, ne de doğrulanmamış bölgeleri
		saklayabilir.
		"""
		cihaz_ham = json.loads(DEVICES_PATH.read_text(encoding="utf-8"))
		yer_ham = json.loads(PLACEMENTS_PATH.read_text(encoding="utf-8"))
		self.assertIn("OLCULMEDI", cihaz_ham["measurement_status"])

		durum = yer_ham["measurement_status"]
		not_metni = yer_ham["measurement_note"]
		self.assertIn("KISMEN_DOGRULANDI", durum, "kısmi doğrulama durumu ilan edilmeli")
		# Doğrulanmamış her bölge notta ADIYLA geçmeli — sessizce kapsam dışı kalmasın.
		for bolge in self.DOGRULANMAMIS_BOLGELER:
			with self.subTest(bolge=bolge):
				self.assertIn(bolge, not_metni)


class RaporDogrulamasi(unittest.TestCase):
	"""§3'te elle hesaplanmış kutular, kural motoruyla birebir çıkmalı."""

	# (sayfa, bölge, viewport, rapordaki kutu, rapor bölümü)
	BEKLENEN = (
		# ── T-115 DÜZELTMESİ (2026-08-20) ────────────────────────────────
		# Aşağıdaki beş satır §3.2/§3.3'ün yazdığı sayılar DEĞİL. Rapor 03'ün
		# tabloları kataloğu üreten AYNI statik yöntemle (Tailwind sınıflarından
		# aritmetik) çıkarılmıştı; ikisi de aynı iki şeyi kaçırıyordu: kartın
		# 1px×2 kenarlığı ve TopDeals bölüm dolgusu. Gerçek tarayıcı ölçümü
		# (13 cihaz, docs/reports/59) farkı gösterdi, katalog düzeltildi.
		# T-110 kabul ölçütü §3: "sapma varsa uygulama CSS'i kaynak kabul edilir".
		# Yani burada rapor değil ÖLÇÜM esas alındı; §3.2/§3.3 bu bölgeler için
		# artık bayat.
		("home", "hero_showcase_grid", 360, 154.0, "§3.2 → T-115 ölçümü (kart kenarlığı −2px)"),
		("home", "hero_showcase_grid", 1536, 194.571, "§3.2 → T-115 ölçümü (kart kenarlığı −2px)"),
		("home", "hero_showcase_grid", 1920, 238.0, "§3.2 → T-115 ölçümü (kart kenarlığı −2px)"),
		("home", "top_deals", 640, 188.667, "§3.3 → T-115 ölçümü (bölüm dolgusu −6px)"),
		("home", "top_deals", 1920, 277.75, "§3.3 → T-115 ölçümü (bölüm dolgusu −4,92px)"),
		("home", "tailored_grid", 1024, 185.6, "§3.4"),
		("home", "tailored_grid", 1920, 342.4, "§3.4"),
		("listing", "card_grid", 640, 296.0, "§3.1"),
		("listing", "card_grid", 768, 146.667, "§3.1 (monoton olmayan kırılım)"),
		("listing", "card_grid", 1920, 286.4, "§3.1"),
		("listing", "brand_grid", 1920, 342.4, "§3.4 notu"),
		("product_detail", "main_image", 390, 390.0, "§3.6"),
		("product_detail", "main_image", 1024, 300.0, "§3.5"),
		("product_detail", "main_image", 1280, 377.0, "§3.5"),
		("product_detail", "main_image", 1536, 502.0, "§3.5"),
		("product_detail", "related_slider", 1024, 157.0, "§3.7"),
		("product_detail", "related_slider", 1280, 145.2, "§3.7"),
		("product_detail", "related_slider", 1440, 177.2, "§3.7"),
		("product_detail", "related_slider", 1920, 236.4, "§3.7"),
	)

	@classmethod
	def setUpClass(cls) -> None:
		cls.layout = load_layout()

	def test_rapordaki_19_kutu_birebir_uretiliyor(self):
		for sayfa, bolge, vw, beklenen, kaynak in self.BEKLENEN:
			with self.subTest(bolge=f"{sayfa}/{bolge}", viewport=vw, rapor=kaynak):
				bulunan = box_width(self.layout.region_of(sayfa, bolge), sahte_cihaz(vw), self.layout)
				self.assertAlmostEqual(bulunan, beklenen, places=2)

	def test_lightbox_yukseklige_bagli(self):
		"""§3.8: 1080p ekranda min(82vh,720)−84 = 636px."""
		bolge = self.layout.region_of("product_detail", "lightbox_main")
		self.assertAlmostEqual(box_width(bolge, sahte_cihaz(1920, 1080), self.layout), 636.0, places=2)
		# Kısa ekranda 82vh tavanı devreye girmez → kutu küçülür.
		self.assertLess(box_width(bolge, sahte_cihaz(390, 844), self.layout), 636.0)

	def test_listeleme_kutusu_monoton_degil(self):
		"""§3.1 anomalisi: 640 → 768 geçişinde kutu BÜYÜMEZ, küçülür."""
		bolge = self.layout.region_of("listing", "card_grid")
		self.assertGreater(
			box_width(bolge, sahte_cihaz(640), self.layout),
			box_width(bolge, sahte_cihaz(768), self.layout),
		)


class SecimKurali(unittest.TestCase):
	"""Tarayıcı taklidi: en küçük yeterli aday; yoksa en büyük."""

	MERDIVEN = (
		Rendition("w96", 96),
		Rendition("w192", 192),
		Rendition("w384", 384),
		Rendition("w640", 640),
	)

	def test_tam_esitlik_o_basamagi_secer(self):
		self.assertEqual(select_rendition(self.MERDIVEN, 384).name, "w384")

	def test_bir_piksel_fazla_ust_basamaga_ciker(self):
		self.assertEqual(select_rendition(self.MERDIVEN, 385).name, "w640")

	def test_hicbiri_yetmezse_en_buyuk_doner(self):
		secilen = select_rendition(self.MERDIVEN, 5000)
		self.assertEqual(secilen.name, "w640")
		self.assertLess(secilen.width, 5000)

	def test_bos_merdiven_none(self):
		self.assertIsNone(select_rendition((), 100))

	def test_sirasiz_merdiven_de_dogru_secer(self):
		karisik = tuple(reversed(self.MERDIVEN))
		self.assertEqual(select_rendition(karisik, 200).name, "w384")


class UpscaleYasagi(unittest.TestCase):
	"""FR-028 — kaynak küçükse üst basamaklar üretilemez, kelepçelenir."""

	def test_kaynak_kelepceler_ve_tekillestirir(self):
		basamaklar = renditions_for("product.image", source_width=800)
		self.assertTrue(all(r.width <= 800 for r in basamaklar))
		genislikler = [r.width for r in basamaklar]
		self.assertEqual(len(genislikler), len(set(genislikler)), "kelepçelenen basamaklar tekilleşmedi")
		self.assertTrue(any(r.clamped for r in basamaklar), "kelepçelenen basamak işaretlenmedi")

	def test_kaynak_sinirsizsa_politika_aynen_gecer(self):
		politika = PolicyRegistry().get("product.image")
		beklenen = [int(p["width"]) for p in politika["profiles"]]
		self.assertEqual([r.width for r in renditions_for("product.image")], sorted(beklenen))

	def test_kelepcelenmis_merdiven_kaynak_yetersizligi_uretir(self):
		"""p50 kaynakla (1.120px) ürün detay ana görseli açık kalır."""
		layout = load_layout()
		cihazlar = load_devices()
		sonuc = simulate_matrix(
			cihazlar, layout.primary_regions(), layout, source_width=KAYNAK_P50
		)
		yetersiz = [s for s in sonuc if WARN_SOURCE_INSUFFICIENT in s.warnings]
		self.assertTrue(yetersiz, "p50 kaynakla hiç yetersizlik çıkmıyorsa kelepçe çalışmıyor")
		self.assertTrue(all(s.region.region == "main_image" for s in yetersiz))


class SizesUretimi(unittest.TestCase):
	"""`sizes` dizgesi CSS'ten üretilir; elle yazılmaz."""

	@classmethod
	def setUpClass(cls) -> None:
		cls.layout = load_layout()

	def test_her_bolge_sizes_uretebiliyor(self):
		for r in self.layout.all_regions():
			with self.subTest(bolge=r.key):
				s = sizes_attribute(r, self.layout)
				self.assertTrue(s)
				self.assertNotIn("nan", s.lower())
				self.assertNotIn("None", s)

	def test_son_parca_kosulsuz_olmali(self):
		"""`sizes` zincirinin sonunda koşulsuz bir taban değer ZORUNLU."""
		for r in self.layout.all_regions():
			with self.subTest(bolge=r.key):
				son = sizes_attribute(r, self.layout).split(", ")[-1]
				self.assertFalse(son.startswith("("), f"{r.key} tabansız: {son}")

	def test_kosullar_azalan_sirada(self):
		"""Tarayıcı ilk eşleşeni alır: `min-width` koşulları büyükten küçüğe olmalı."""
		for r in self.layout.all_regions():
			with self.subTest(bolge=r.key):
				esikler = [
					int(p.split("min-width: ")[1].split("px")[0])
					for p in sizes_attribute(r, self.layout).split(", ")
					if p.startswith("(min-width")
				]
				self.assertEqual(esikler, sorted(esikler, reverse=True))

	def test_container_padding_kirilimi_ayri_bant_uretiyor(self):
		"""`boxed` 1536'da 32→64 padding değiştirir; `sizes` bunu ayırmalı."""
		s = sizes_attribute(self.layout.region_of("home", "hero_showcase_grid"), self.layout)
		self.assertIn("(min-width: 1536px)", s)
		self.assertIn("64px", s)

	def test_srcset_dizgesi_artan_genislikte(self):
		basamaklar = renditions_for("product.image")
		girdiler = srcset_attribute(basamaklar).split(", ")
		w = [int(g.rsplit(" ", 1)[1].rstrip("w")) for g in girdiler]
		self.assertEqual(w, sorted(w))
		self.assertEqual(len(w), len(basamaklar))


class SimulatorTablosu(unittest.TestCase):
	"""13 cihaz × 5 sayfa (birincil bölge) = 65 kombinasyonun tamamı."""

	@classmethod
	def setUpClass(cls) -> None:
		cls.devices = load_devices()
		cls.layout = load_layout()
		cls.birincil = cls.layout.primary_regions()
		cls.sonuc = simulate_matrix(cls.devices, cls.birincil, cls.layout)
		cls.ozet = summarize(cls.sonuc)

	def test_tam_65_kombinasyon(self):
		self.assertEqual(len(self.devices) * len(self.birincil), 65)
		self.assertEqual(len(self.sonuc), 65)

	def test_her_kombinasyon_bir_basamak_secti(self):
		for s in self.sonuc:
			with self.subTest(kombinasyon=f"{s.device.id}×{s.region.key}"):
				self.assertIsNotNone(s.chosen)
				self.assertGreater(s.required_px, 0)
				self.assertGreater(s.css_box_px, 0)

	def test_sinirsiz_kaynakta_yetersizlik_yok(self):
		"""Politikadaki merdiven, 65 kombinasyonun HEPSİNİ karşılamalı.

		Bu, Faz 2'de seçilen genişliklerin (96…1920) yeterliliğinin makine
		kanıtıdır. Bir gün yeni bir cihaz ya da bölge eklenip merdiven
		yetmezse bu test kırılır — sessizce bulanık görsel servis edilmez.
		"""
		yetersiz = [f"{s.device.id}×{s.region.key}" for s in self.sonuc if not s.sufficient]
		self.assertEqual(yetersiz, [], f"merdiven yetmiyor: {yetersiz}")

	def test_zoom_acigi_yalniz_urun_detay_masaustunde(self):
		"""1,85× hover-zoom, `sizes` ile seçilen türevin ötesinde piksel ister."""
		zoom = [s for s in self.sonuc if WARN_ZOOM_INSUFFICIENT in s.warnings]
		self.assertTrue(zoom, "zoom açığı hiç çıkmıyorsa çarpan uygulanmıyor demektir")
		for s in zoom:
			with self.subTest(kombinasyon=f"{s.device.id}×{s.region.key}"):
				self.assertEqual(s.region.key, "product_detail/main_image")
				self.assertGreaterEqual(s.device.css_width, 1024)

	def test_asiri_servis_tavani_asan_kombinasyonlar_bilinen_kume(self):
		"""`max_overshoot` (1,85) aşımı — merdivenin ALT ucunda basamak eksik."""
		asan = sorted(f"{s.device.id}×{s.region.key}" for s in self.sonuc if WARN_OVERSHOOT in s.warnings)
		# 2026-08-20'de 1'den 3'e çıktı — bu bir GERİLEME DEĞİL, bir ORTAYA
		# ÇIKMA: katalog mağaza ürün ızgarasını 260px sanıyordu, gerçek kutu
		# 199,5px (sol kenar çubuğu düşülmüyordu). Kutu düzeltilince aynı
		# merdiven basamağı artık fazla iniyor; yani aşırı servis zaten VARDI,
		# katalog onu göremiyordu. Düzeltilmesi merdivenin alt ucuna basamak
		# eklemeyi gerektirir — ayrı bir iş.
		self.assertEqual(
			asan,
			[
				"desktop-1080p×seller_shop/product_grid",
				"desktop-1440p×seller_shop/product_grid",
				"moto-g-power×cart_checkout/summary_strip",
			],
		)

	def test_determinist(self):
		tekrar = simulate_matrix(self.devices, self.birincil, self.layout)
		self.assertEqual([s.to_dict() for s in tekrar], [s.to_dict() for s in self.sonuc])

	def test_tablo_basar(self):
		"""Tabloyu üretir ve stdout'a yazar — T-112'nin gözle okunan çıktısı."""
		tablo = format_table(self.sonuc)
		self.assertEqual(len(tablo.splitlines()), 65 + 2)  # başlık + sınır + 65 satır

		print("\n\n=== 13 CİHAZ × 5 SAYFA (birincil bölge) = 65 KOMBİNASYON ===\n")
		print(tablo)
		print()
		print(
			f"toplam={self.ozet['toplam']}  "
			f"kaynak_yetersiz={self.ozet['kaynak_yetersiz']}  "
			f"asiri_servis={self.ozet['asiri_servis']}  "
			f"zoom_yetersiz={self.ozet['zoom_yetersiz']}  "
			f"ort_fazlalik={self.ozet['ortalama_fazlalik']:.2f}×  "
			f"en_yuksek_fazlalik={self.ozet['en_yuksek_fazlalik']:.2f}×"
		)
		print(f"seçilen basamak dağılımı: {self.ozet['secilen_dagilim']}")

		for kaynak in (KAYNAK_P50, KAYNAK_P90):
			alt = summarize(
				simulate_matrix(self.devices, self.birincil, self.layout, source_width=kaynak)
			)
			print(
				f"kaynak genişliği {kaynak}px ile: kaynak_yetersiz={alt['kaynak_yetersiz']} "
				f"→ {alt['kaynak_yetersiz_liste']}"
			)

	def test_tum_bolgeler_de_cozulebiliyor(self):
		"""15 bölgenin tamamı (195 kombinasyon) hata vermeden çözülmeli."""
		hepsi = simulate_matrix(self.devices, self.layout.all_regions(), self.layout)
		self.assertEqual(len(hepsi), 13 * 15)
		self.assertTrue(all(s.chosen is not None for s in hepsi))


if __name__ == "__main__":
	unittest.main(verbosity=2)
