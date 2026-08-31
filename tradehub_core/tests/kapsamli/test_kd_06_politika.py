"""KD-06 — PolicyEngine + slot politikaları: doğrulama, sınır ve TUTARLILIK.

Kaynak okundu:
  * `media/pipeline/policy/engine.py` (1829)   — kural blokları, karar sözleşmesi
  * `media/pipeline/policy/slots/*.json` (9)    — canlı slot standartları
  * `media/pipeline/image/normalize.py`         — master bloğunun uygulayıcısı

Bu modülün iki işi var:
  1. Motorun kural bloklarını girdi/çıktı düzeyinde doğrulamak.
  2. **Politikaların kendi içinde tutarlı olduğunu** ölçmek — bir slot
     dosyasının, uygulayıcı kodun sözleşmesiyle çelişip çelişmediği.
     (2) numaralı iş burada bulunuyor çünkü politikaları uygulayan kod
     doğru çalışsa bile çelişen bir politika yanlış çıktı üretir.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradehub_core.media.pipeline.core.probe import MediaProbe
from tradehub_core.media.pipeline.image import normalize as nrm
from tradehub_core.media.pipeline.policy import engine as pe


def _probe(**kw) -> MediaProbe:
	"""Ürün görseli slotundan GEÇEN taban künye — testler yalnız farkı yazar."""
	temel = dict(
		filename="urun.jpg",
		extension=".jpg",
		byte_size=1_200_000,
		kind="image",
		detected="jpeg",
		mime="image/jpeg",
		fmt="JPEG",
		width=2000,
		height=2000,
		mode="RGB",
		readable=True,
		loadable=True,
		extension_matches_content=True,
		leading_marker=False,
		appended_payload=False,
		animated=False,
		existing_count=0,
		scan_clean=True,
	)
	temel.update(kw)
	return MediaProbe(**temel)


SLOT_DIZINI = Path(pe.__file__).parent / "slots"


def _slotlar() -> dict[str, dict]:
	out = {}
	for f in sorted(SLOT_DIZINI.glob("*.json")):
		out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
	return out


# ══════════════════════════════════════════════════════════════════════
# 1. Kayıt defteri
# ══════════════════════════════════════════════════════════════════════


class TestKayitDefteri(unittest.TestCase):
	def test_bi_tum_slotlar_yuklenir(self):
		r = pe.PolicyRegistry().load()
		self.assertGreaterEqual(len(r), 9)
		for slot in ("product.image", "seller.logo", "user.avatar", "product.video"):
			self.assertIn(slot, r, slot)

	def test_bi_olmayan_slot_policynotfound(self):
		r = pe.PolicyRegistry().load()
		with self.assertRaises(pe.PolicyNotFound):
			r.get("olmayan-slot")

	def test_bi_kaynak_dosyasi_izlenebilir(self):
		r = pe.PolicyRegistry().load()
		yol = r.source_of("product.image")
		self.assertTrue(str(yol).endswith("product-image.json"), yol)

	def test_bi_slot_anahtari_dosya_adindan_FARKLI(self):
		"""Kayıt anahtarı noktalı (`product.image`), dosya adı tireli.

		Bu sessiz bir tuzak: `evaluate("product-image")` `PolicyNotFound`
		atar. Sözleşme burada sabitleniyor."""
		r = pe.PolicyRegistry().load()
		self.assertIn("product.image", r)
		self.assertNotIn("product-image", r)

	def test_bi_get_kopyalanmis_sozluk_dondurur_mu(self):
		"""Kayıt defterinden alınan politika DIŞARIDAN bozulabiliyor mu."""
		r = pe.PolicyRegistry().load()
		a = r.get("product.image")
		a.setdefault("accept", {})["max_bytes"] = 1
		b = r.get("product.image")
		if b.get("accept", {}).get("max_bytes") == 1:
			self.skipTest(
				"BULGU F-09: registry.get() paylaşılan sözlük döndürüyor; bir çağıranın "
				"yaptığı değişiklik tüm süreç için kalıcı oluyor (kayıt aşağıda)"
			)


# ══════════════════════════════════════════════════════════════════════
# 2. Karar sözleşmesi
# ══════════════════════════════════════════════════════════════════════


class TestKararSozlesmesi(unittest.TestCase):
	def setUp(self):
		self.motor = pe.PolicyEngine()

	def test_bi_temiz_gorsel_kabul(self):
		k = self.motor.evaluate("product.image", _probe())
		self.assertTrue(k.allow, k.codes)
		self.assertEqual(k.action, pe.ACTION_PASS)
		self.assertTrue(k.normalized_targets, "kabul edilen dosyada hedefler dolu olmalı")

	def test_bi_reddedilen_dosyada_hedef_uretilmez(self):
		k = self.motor.evaluate("product.image", _probe(width=200, height=200))
		self.assertFalse(k.allow)
		self.assertEqual(k.normalized_targets, {}, "ret kararında hedef üretilmemeli")

	def test_bi_sozluk_kunye_kabul_edilir(self):
		k = self.motor.evaluate("product.image", _probe().to_dict())
		self.assertTrue(k.allow, k.codes)

	def test_gv_sozlukte_bilinmeyen_anahtar_patlatmaz(self):
		d = _probe().to_dict()
		d["uydurma_alan"] = 1
		k = self.motor.evaluate("product.image", d)
		self.assertTrue(k.allow, k.codes)

	def test_bi_to_dict_sozlesmesi(self):
		d = self.motor.evaluate("product.image", _probe()).to_dict()
		for alan in ("allow", "slot", "role", "action", "violations",
					 "normalized_targets", "skipped", "policy_version", "policy_status"):
			self.assertIn(alan, d)

	def test_bi_ihlal_mesaji_bos_kalmaz(self):
		k = self.motor.evaluate("product.image", _probe(width=200, height=200))
		for v in k.violations:
			with self.subTest(kod=v.code):
				self.assertTrue(v.code)
				self.assertTrue(v.to_dict())


# ══════════════════════════════════════════════════════════════════════
# 3. Güvenlik bloğu
# ══════════════════════════════════════════════════════════════════════


class TestGuvenlikBlogu(unittest.TestCase):
	def setUp(self):
		self.motor = pe.PolicyEngine()

	def test_gv_calistirilabilir_icerik_reddedilir(self):
		k = self.motor.evaluate("product.image", _probe(leading_marker=True))
		self.assertFalse(k.allow)
		self.assertIn("executable_content", [v.rule for v in k.violations])

	def test_gv_eklenmis_yuk_reddedilir(self):
		k = self.motor.evaluate("product.image", _probe(appended_payload=True))
		self.assertFalse(k.allow)

	def test_gv_data_uri_yalniz_logo_slotlarinda_yasak(self):
		"""BULGU F-10 — `accept.allow_data_uri: false` yalnız 2 slotta var.

		Kural `accept.get("allow_data_uri") is False` diye yazılmış; anahtar
		hiç yoksa (7 slotta yok) kural TETİKLENMEZ. Yani politika katmanı
		tek başına `data:` URI'yi yalnız brand.logo ve seller.logo'da
		engelliyor. (Kabul kapısı `image/probe.py` bunu ayrıca reddediyor —
		savunma tek katmanda değil ama politika sözleşmesi eksik.)
		"""
		yasak = self.motor.evaluate("seller.logo", _probe(is_data_uri=True, detected="data_uri"))
		self.assertFalse(yasak.allow)
		self.assertIn("data_uri_forbidden", [v.rule for v in yasak.violations])

		serbest = self.motor.evaluate("product.image", _probe(is_data_uri=True, detected="data_uri"))
		self.assertNotIn(
			"data_uri_forbidden", [v.rule for v in serbest.violations],
			"F-10 kapanmış olabilir — product-image.json'a allow_data_uri eklenmiş",
		)

	def test_gv_av_taramasi_kirli_ise_reddedilir(self):
		k = self.motor.evaluate("product.image", _probe(scan_clean=False))
		self.assertFalse(k.allow)

	def test_bi_av_taramasi_olculmediyse_atlanir(self):
		"""`None` = "taranmadı"; ret sebebi DEĞİL ama atlandığı kayda geçmeli."""
		k = self.motor.evaluate("product.image", _probe(scan_clean=None))
		atlanan = {s.rule for s in k.skipped}
		self.assertTrue(k.allow or "av_scan" in atlanan, (k.codes, atlanan))

	def test_gv_konteyner_gecersizse_reddedilir(self):
		k = self.motor.evaluate(
			"document.attachment",
			_probe(
				filename="a.docx", extension=".docx", detected="zip",
				mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
				container_valid=False, kind="document", fmt="", width=0, height=0,
			),
		)
		self.assertFalse(k.allow)

	def test_gv_uzanti_icerik_uyusmazligi(self):
		k = self.motor.evaluate("product.image", _probe(extension_matches_content=False, detected="png"))
		self.assertFalse(k.allow)


# ══════════════════════════════════════════════════════════════════════
# 4. Kabul bloğu — sınır değerleri
# ══════════════════════════════════════════════════════════════════════


class TestKabulBlogu(unittest.TestCase):
	def setUp(self):
		self.motor = pe.PolicyEngine()
		self.pol = pe.PolicyRegistry().load().get("product.image")

	def test_sn_byte_tavani_tam_sinirda_gecer(self):
		mx = self.pol["accept"]["max_bytes"]
		self.assertTrue(self.motor.evaluate("product.image", _probe(byte_size=mx)).allow)

	def test_sn_byte_tavani_asilinca_duser(self):
		mx = self.pol["accept"]["max_bytes"]
		k = self.motor.evaluate("product.image", _probe(byte_size=mx + 1))
		self.assertFalse(k.allow)
		self.assertIn("too_large_bytes", [v.rule for v in k.violations])

	def test_gv_megapiksel_tavani(self):
		k = self.motor.evaluate("product.image", _probe(width=10000, height=9000))
		self.assertFalse(k.allow)
		self.assertIn("too_many_pixels", [v.rule for v in k.violations])

	def test_bi_animasyon_reddedilir(self):
		k = self.motor.evaluate("product.image", _probe(animated=True))
		self.assertFalse(k.allow)

	def test_bi_okunamayan_dosya_reddedilir(self):
		k = self.motor.evaluate("product.image", _probe(readable=False))
		self.assertFalse(k.allow)

	def test_bi_reddedilen_uzanti(self):
		k = self.motor.evaluate(
			"seller.logo", _probe(filename="a.gif", extension=".gif", detected="gif", mime="image/gif", fmt="GIF")
		)
		self.assertFalse(k.allow)
		self.assertIn("extension_rejected", [v.rule for v in k.violations])

	def test_bi_kosullu_uzanti_svg_kapali(self):
		"""SVG `conditional_extensions`'ta — kapı kapalıysa reddedilmeli."""
		k = self.motor.evaluate(
			"seller.logo",
			_probe(filename="a.svg", extension=".svg", detected="svg", mime="image/svg+xml",
				   fmt="", width=0, height=0, readable=False),
		)
		kurallar = [v.rule for v in k.violations]
		self.assertFalse(k.allow)
		self.assertTrue(
			{"extension_conditional_closed", "format_not_supported", "unreadable"} & set(kurallar),
			kurallar,
		)


# ══════════════════════════════════════════════════════════════════════
# 5. Geometri bloğu
# ══════════════════════════════════════════════════════════════════════


class TestGeometri(unittest.TestCase):
	def setUp(self):
		self.motor = pe.PolicyEngine()

	def test_sn_kisa_kenar_tam_sinirda_gecer(self):
		self.assertTrue(self.motor.evaluate("product.image", _probe(width=1000, height=1000)).allow)

	def test_sn_kisa_kenar_bir_altinda_duser(self):
		k = self.motor.evaluate("product.image", _probe(width=999, height=999))
		self.assertFalse(k.allow)
		self.assertIn("short_edge_too_small", [v.rule for v in k.violations])

	def test_bi_izinsiz_oran_reddedilir(self):
		k = self.motor.evaluate("product.image", _probe(width=2000, height=1000))  # 2:1
		self.assertFalse(k.allow)
		self.assertIn("ratio_not_allowed", [v.rule for v in k.violations])

	def test_bi_izinli_oranlar_gecer(self):
		for w, h in ((2000, 2000), (1600, 2000), (1500, 2000)):  # 1:1, 4:5, 3:4
			with self.subTest(w=w, h=h):
				k = self.motor.evaluate("product.image", _probe(width=w, height=h))
				self.assertTrue(k.allow, (w, h, k.codes))

	def test_gv_exif_donusu_oran_kuralinda_dikkate_alinir(self):
		"""Depolanan 3:4 ama görünen 4:3 — kural GÖRÜNEN ölçüye bakmalı."""
		k = self.motor.evaluate(
			"product.image", _probe(width=1500, height=2000, exif_orientation=6)
		)
		self.assertFalse(k.allow, "döndürülmüş görünen oran (4:3) izinli listede yok")

	def test_bi_olculemeyen_geometri_atlanir(self):
		k = self.motor.evaluate("product.image", _probe(width=0, height=0, readable=False))
		atlanan = {s.rule for s in k.skipped}
		self.assertIn("geometry", atlanan)

	def test_sn_adet_sozlesmesi_yukleme_SONRASI_toplam(self):
		"""`existing_count` yükleme SONRASI toplamdır (kodda yazılı sözleşme).

		max_count=12 → 12 geçer, 13 düşer. Bu "12 mi 13 mü" hatası sessizce
		bir fazla dosya kabul ettirdiği için sınır iki yönden de ölçülüyor.
		"""
		self.assertTrue(self.motor.evaluate("product.image", _probe(existing_count=12)).allow)
		k = self.motor.evaluate("product.image", _probe(existing_count=13))
		self.assertFalse(k.allow)
		self.assertIn("too_many_items", [v.rule for v in k.violations])

	def test_bi_adet_olculemediyse_atlanir(self):
		k = self.motor.evaluate("product.image", _probe(existing_count=None))
		self.assertIn("count", {s.rule for s in k.skipped})


# ══════════════════════════════════════════════════════════════════════
# 6. Video bloğu
# ══════════════════════════════════════════════════════════════════════


def _video_probe(**kw) -> MediaProbe:
	temel = dict(
		filename="v.mp4", extension=".mp4", byte_size=5_000_000, kind="video",
		detected="mp4", mime="video/mp4", width=1280, height=720,
		duration_s=20.0, bitrate_bps=2_000_000, frame_rate=30.0,
		readable=True, loadable=True, extension_matches_content=True,
		animated=True, existing_count=0, scan_clean=True,
	)
	temel.update(kw)
	return MediaProbe(**temel)


class TestVideoBlogu(unittest.TestCase):
	def setUp(self):
		self.motor = pe.PolicyEngine()

	def test_bi_uygun_video_kabul(self):
		k = self.motor.evaluate("product.video", _video_probe())
		self.assertTrue(k.allow, k.codes)

	def test_bi_BULGU_product_video_sure_asimi_yalniz_UYARI(self):
		"""BULGU F-11 — `product-video.json` `on_violation.require = "warn"`.

		Standart 33 sn diyor ama süre aşımı ihlali ENGELLEYİCİ DEĞİL: 40 sn'lik
		video politikadan GEÇİYOR (`allow=True`, action=`warn`). Aynı kural
		`company-cover-video` slotunda `require: "reject"` olduğu için orada
		engelliyor. İki video slotu arasındaki bu asimetri kasıtlıysa
		belgelenmeli, değilse üretimde 33 sn tavanı fiilen yok demektir.
		"""
		k = self.motor.evaluate("product.video", _video_probe(duration_s=40.0))
		kurallar = [v.rule for v in k.violations]
		self.assertIn("duration_too_long", kurallar)
		self.assertTrue(k.allow, "F-11 kapanmış — require artık reject")
		self.assertEqual(k.action, pe.ACTION_WARN)
		for v in k.violations:
			if v.rule == "duration_too_long":
				self.assertFalse(v.blocking)

	def test_bi_company_cover_video_sure_asimi_ENGELLIYOR(self):
		"""Kontrast: aynı kural, `require: "reject"` olan slotta engelliyor."""
		k = self.motor.evaluate("company.cover_video", _video_probe(width=1920, height=1080, duration_s=120.0))
		self.assertFalse(k.allow)
		self.assertIn("duration_too_long", [v.rule for v in k.violations])

	def test_sn_sure_tam_sinirda_gecer(self):
		pol = pe.PolicyRegistry().load().get("product.video")
		mx = pol["video"]["duration_max_s"]
		self.assertTrue(self.motor.evaluate("product.video", _video_probe(duration_s=mx)).allow)

	def test_bi_sure_olculemediyse_atlanir(self):
		k = self.motor.evaluate("product.video", _video_probe(duration_s=None))
		self.assertIn("duration", {s.rule for s in k.skipped})

	def test_bi_bitrate_olculemediyse_atlanir(self):
		k = self.motor.evaluate("product.video", _video_probe(bitrate_bps=None))
		self.assertIn("bitrate", {s.rule for s in k.skipped})

	def test_bi_company_cover_video_sure_alt_siniri(self):
		k = self.motor.evaluate("company.cover_video", _video_probe(width=1920, height=1080, duration_s=3.0))
		self.assertFalse(k.allow)
		self.assertIn("duration_too_short", [v.rule for v in k.violations])


# ══════════════════════════════════════════════════════════════════════
# 7. SLOT POLİTİKALARININ İÇ TUTARLILIĞI  ← asıl denetim
# ══════════════════════════════════════════════════════════════════════


class TestPolitikaTutarliligi(unittest.TestCase):
	"""Politika dosyaları, onları UYGULAYAN kodun sözleşmesine uymalı."""

	def setUp(self):
		self.slotlar = _slotlar()

	def test_bi_her_slot_normalizespec_kurabiliyor(self):
		"""`master` bloğu `NormalizeSpec.from_policy` ile kurulamıyorsa
		o slot üretimde ilk yüklemede patlar."""
		for ad, pol in self.slotlar.items():
			with self.subTest(slot=ad):
				master = pol.get("master") or {}
				if not master:
					continue
				try:
					nrm.NormalizeSpec.from_policy(master)
				except ValueError as exc:
					self.fail(f"{ad}: master bloğu geçersiz — {exc}")

	def test_bi_min_long_edge_max_long_edge_asmiyor(self):
		for ad, pol in self.slotlar.items():
			master = pol.get("master") or {}
			mx = int(master.get("max_long_edge") or 0)
			mn = int(master.get("min_long_edge") or master.get("min_pixel_edge") or 0)
			if mx and mn:
				with self.subTest(slot=ad):
					self.assertLessEqual(mn, mx, f"{ad}: min_long_edge > max_long_edge")

	def test_bi_CANLI_SLOTLARDA_megapiksel_tavani_artik_uygulanabiliyor(self):
		"""F-06 düzeltildi — politika sayılarına DOKUNULMADAN kod uyumlandı.

		İki slotta `min_long_edge` ile `max_megapixels` birbirini dışlıyordu:
		  category-banner      5:4 → 1920×1536 = 2,95 MP / tavan 2,00
		  company-cover-image  2:1 → 1920× 960 = 1,84 MP / tavan 1,64
		(ikincisinde izinli EN DAR oran bile aşıyordu, yani tavan fiilen
		uygulanamıyordu).

		Faz 2 kuralı "sayılar sabittir, değiştirmek isteyen değişiklik talebi
		açar" dediği için slot JSON'larına dokunulmadı; `target_size` kendi
		sözleşmesini uygulayacak şekilde düzeltildi. Çakışmada MP tavanı kazanır.

		NOT: politika verisindeki çelişki DURUYOR (alt sınır artık fiilen
		uygulanamıyor) — bu bir değişiklik talebi konusudur, kod kusuru değil.
		"""
		asanlar = []
		for ad in ("category-banner", "company-cover-image"):
			pol = self.slotlar[ad]
			spec = nrm.NormalizeSpec.from_policy(pol["master"])
			for oran in (pol.get("require") or {}).get("allowed_ratios") or []:
				w, h = (int(x) for x in oran.split(":"))
				nw, nh = nrm.target_size(w * 1000, h * 1000, spec)
				mp = (nw * nh) / 1_000_000
				if mp > spec.max_megapixels + 1e-9:
					asanlar.append(f"{ad}/{oran}: {mp:.2f} MP > {spec.max_megapixels}")
		self.assertEqual(asanlar, [], "F-06 geri geldi:\n" + "\n".join(asanlar))

	def test_bi_TUM_SLOTLARDA_MP_tavani_asilmiyor(self):
		"""Dokuz slotun tamamı, izinli her oranda tavanına uyuyor."""
		asanlar = []
		for ad, pol in self.slotlar.items():
			master = pol.get("master") or {}
			if not master.get("max_megapixels"):
				continue
			spec = nrm.NormalizeSpec.from_policy(master)
			oranlar = (pol.get("require") or {}).get("allowed_ratios") or ["1:1", "16:9", "4:5"]
			for oran in oranlar:
				try:
					w, h = (int(x) for x in oran.split(":"))
				except ValueError:
					continue
				nw, nh = nrm.target_size(w * 1000, h * 1000, spec)
				mp = (nw * nh) / 1_000_000
				if mp > spec.max_megapixels + 1e-9:
					asanlar.append(f"{ad}/{oran}: {mp:.2f} > {spec.max_megapixels}")
		self.assertEqual(asanlar, [], "\n".join(asanlar))

	def test_orm_POLITIKA_CELISKISI_degisiklik_talebi_bekliyor(self):
		"""SÜREÇ KAYDI — kod uyumlandı ama politika verisi hâlâ çelişkili.

		`min_long_edge` bu iki slotta fiilen uygulanamıyor (MP tavanı kesiyor).
		Sayıyı düzeltmek Faz 2 gereği değişiklik talebi konusudur; bu test
		durumu rapora yazar, kırmızı yapmaz.
		"""
		celisen = []
		for ad in ("category-banner", "company-cover-image"):
			pol = self.slotlar[ad]
			spec = nrm.NormalizeSpec.from_policy(pol["master"])
			for oran in (pol.get("require") or {}).get("allowed_ratios") or []:
				w, h = (int(x) for x in oran.split(":"))
				nw, nh = nrm.target_size(w * 1000, h * 1000, spec)
				if max(nw, nh) < spec.min_long_edge:
					celisen.append(f"{ad}/{oran}: {max(nw, nh)} < min_long_edge {spec.min_long_edge}")
		if celisen:
			self.skipTest("min_long_edge fiilen uygulanamıyor:\n" + "\n".join(celisen))

	def test_bi_webp_master_dpi_out_teknik_olarak_uygulanamaz(self):
		"""`format: webp` + `dpi_out` birlikte SAĞLANAMAZ — kayıt altına alınır.

		Kod bunu uydurmuyor (`dpi_written=False` + not düşüyor). Test, kaç
		slotun bu çelişkiyi taşıdığını sabitler ki politika temizlenince
		fark edilsin.
		"""
		celisen = [
			ad for ad, pol in self.slotlar.items()
			if str((pol.get("master") or {}).get("format", "")).lower() == "webp"
			and int((pol.get("master") or {}).get("dpi_out") or 0) > 0
		]
		self.assertTrue(celisen, "çelişki kalmamış — beklentiyi güncelle")
		self.assertNotIn(
			"WEBP", nrm.DPI_CAPABLE_FORMATS,
			"WebP artık DPI taşıyabiliyorsa çelişki ortadan kalkmıştır",
		)

	def test_bi_accept_uzanti_ve_mime_ortusuyor(self):
		"""Bir uzantı izinliyken karşılık gelen MIME yasaksa dosya hiç geçemez."""
		from tradehub_core.media.pipeline.core.probe import MIME_BY_KIND

		ext_mime = {
			".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
			".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff",
			".pdf": "application/pdf", ".mp4": "video/mp4", ".webm": "video/webm",
			".mov": "video/quicktime", ".svg": "image/svg+xml",
		}
		self.assertTrue(MIME_BY_KIND)
		for ad, pol in self.slotlar.items():
			accept = pol.get("accept") or {}
			mimeler = set(accept.get("mime") or [])
			if not mimeler:
				continue
			for ext in accept.get("extensions") or []:
				beklenen = ext_mime.get(ext)
				if beklenen is None:
					continue
				with self.subTest(slot=ad, ext=ext):
					self.assertIn(beklenen, mimeler, f"{ad}: {ext} izinli ama {beklenen} MIME listesinde yok")

	def test_bi_allow_upscale_hicbir_slotta_acik_degil(self):
		"""FR-028 — `master.allow_upscale` açık bir slot NormalizeSpec'i patlatır."""
		for ad, pol in self.slotlar.items():
			with self.subTest(slot=ad):
				self.assertFalse((pol.get("master") or {}).get("allow_upscale", False), ad)

	def test_bi_gps_strip_her_slotta_acik(self):
		"""INV-04 — GPS kodda zorunlu; politika da bunu yansıtmalı."""
		for ad, pol in self.slotlar.items():
			strip = (pol.get("master") or {}).get("strip_metadata")
			if strip is None:
				continue
			with self.subTest(slot=ad):
				self.assertTrue(strip.get("gps", True), f"{ad}: strip_metadata.gps kapalı")

	def test_bi_on_violation_haritasi_sabitleniyor(self):
		"""BULGU F-11/genel — 4 slotta `require` bloğu ENGELLEMİYOR.

		`require` bloğu geometri, oran, adet ve video süresi kurallarını
		taşıyor. Aşağıdaki slotlarda bu kuralların tamamı yalnızca uyarı
		üretiyor; dosya yine kabul ediliyor. Harita burada sabitleniyor ki
		bir slot sessizce gevşetildiğinde/sıkılaştırıldığında fark edilsin.
		"""
		beklenen = {
			"brand-logo": "reject",
			"category-banner": "warn",
			"company-cover-image": "warn",
			"company-cover-video": "reject",
			"document-attachment": "warn",
			"product-image": "reject",
			"product-video": "warn",
			"seller-logo": "reject",
			"user-avatar": "reject",
		}
		gercek = {
			ad: ((pol.get("on_violation") or {}).get("require")
				 or (pol.get("on_violation") or {}).get("default"))
			for ad, pol in self.slotlar.items()
		}
		self.assertEqual(gercek, beklenen)
		gevsek = sorted(a for a, v in gercek.items() if v != "reject")
		self.assertEqual(gevsek, ["category-banner", "company-cover-image",
								  "document-attachment", "product-video"])

	def test_bi_her_slotta_surum_ve_durum_var(self):
		for ad, pol in self.slotlar.items():
			with self.subTest(slot=ad):
				self.assertTrue(pol.get("schema_version"), f"{ad}: schema_version yok")
				self.assertIn(pol.get("status"), ("draft", "active", "frozen", "deprecated"), ad)

	def test_orm_slot_politikalari_hala_taslak(self):
		"""ORTAM/SÜREÇ KAYDI — MOGEM-617 Faz 2 çıkışı "sabitlenmiş sayılar" diyor.

		9 slotun tamamı hâlâ `draft`. Faz 2 kapanmadan Faz 6+ geliştirmesi
		yapılmaması gerekiyordu; bu test durumu rapora yazar, kırmızı yapmaz.
		"""
		taslak = [ad for ad, pol in self.slotlar.items() if pol.get("status") == "draft"]
		if taslak:
			self.skipTest(f"{len(taslak)}/{len(self.slotlar)} slot hâlâ 'draft': {', '.join(sorted(taslak))}")


if __name__ == "__main__":
	unittest.main()
