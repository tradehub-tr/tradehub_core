"""T-120 doğrulaması — `<picture>` üretiminin ölçülen boşluklara karşı sınanması.

Bu dosyanın sınadığı şey estetik değil, `docs/reports/03-performans-taban-cizgisi.md`
§2.2'nin ölçtüğü tablodur. Bugünkü ölçüm (aynı belge §7, sabitlenen taban çizgisi):

    srcset          0/22 · 0/51 · 0/31 · 0/26
    sizes           0/22 · 0/51 · 0/31 · 0/26
    <picture>       0/22 · 0/51 · 0/31 · 0/26
    fetchpriority   0/22 · 0/51 · 0/31 · 0/26

Aşağıdaki testler, üretilen işaretlemede bu dört satırın da **dolu** olduğunu ve
`width`/`height`'in HER `<img>`'de bulunduğunu (CLS=0 koşulu) doğrular.

Çalıştırma (bench/site/DB GEREKMEZ):

    cd /Users/ahmet/Desktop/istoc/tradehub_core
    python3 -m unittest tests.test_delivery_picture -v
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.contracts.delivery import (  # noqa: E402
	LOADING_LAZY,
	RenderManifest,
	SourceSet,
	Variant,
)
from tradehub_core.media.pipeline.contracts.storage import ObjectKey, ObjectRef  # noqa: E402
from tradehub_core.media.pipeline.delivery import picture as P  # noqa: E402
from tradehub_core.media.pipeline.delivery.manifest import build_default  # noqa: E402

# Deterministik sahte anahtar: `ObjectKey` shard'ın adın ilk 2 karakteri
# olmasını zorunlu kılar (contracts/storage.py:72).
HASH = "ab" + "c" * 30
KEY = ObjectKey(shard="ab", name=f"{HASH}.jpg")
REF = ObjectRef(key=KEY, scope="public")

#: Ölçülen ürün detay sayfasının gerçek `sizes`i — `delivery/sizes.py`
#: `product_detail/main_image` bölgesi için üretiyor.
PDP_SIZES = "(min-width: 1536px) 502px, (min-width: 1280px) 377px, (min-width: 1024px) 300px, 100vw"


def kart_manifesti(**kw) -> RenderManifest:
	"""`product.image` slotundan gerçek politika ile manifest kur."""
	varsayilan = dict(
		intrinsic=(2400, 2400),
		alt="Bonny erzak saklama kabı 1 lt",
		available_profiles=["w384", "w640", "w768"],
	)
	varsayilan.update(kw)
	return build_default().build_image("product.image", REF, **varsayilan)


def el_manifesti(**kw) -> RenderManifest:
	"""Politikadan bağımsız, elle kurulmuş manifest — sınır durumları için."""
	varsayilan = dict(
		slot_key="test.slot",
		fallback_url="/files/ab/x__w640.jpeg",
		variants=(
			Variant(profile="w320", url="/files/ab/x__w320.jpeg", width=320, height=320, fmt="jpeg"),
			Variant(profile="w640", url="/files/ab/x__w640.jpeg", width=640, height=640, fmt="jpeg"),
		),
		sources=(
			SourceSet(fmt="avif", srcset="/files/ab/x__w320.avif 320w, /files/ab/x__w640.avif 640w"),
			SourceSet(fmt="webp", srcset="/files/ab/x__w320.webp 320w, /files/ab/x__w640.webp 640w"),
			SourceSet(fmt="jpeg", srcset="/files/ab/x__w320.jpeg 320w, /files/ab/x__w640.jpeg 640w"),
		),
		sizes="100vw",
		intrinsic_width=1200,
		intrinsic_height=1200,
		alt="deneme",
	)
	varsayilan.update(kw)
	return RenderManifest(**varsayilan)


class OlculenBosluk(unittest.TestCase):
	"""§2.2 tablosunun dört boş satırı gerçekten doluyor mu."""

	def test_srcset_sizes_picture_fetchpriority_hepsi_var(self):
		m = kart_manifesti()
		html = P.render_picture(m, P.PictureOptions(sizes=PDP_SIZES, priority=True))
		olcum = P.audit(html)
		self.assertEqual(olcum["picture"], 1, "bugün 0/31 — `<picture>` sarmalı üretilmedi")
		self.assertGreaterEqual(olcum["srcset"], 1, "bugün 0/31 — `srcset` yok")
		self.assertGreaterEqual(olcum["sizes"], 1, "bugün 0/31 — `sizes` yok")
		self.assertEqual(olcum["fetchpriority_high"], 1, "bugün 0/31 — LCP önceliği verilmiyor")
		self.assertEqual(olcum["eksik_boyut"], 0, "her `<img>` width+height taşımalı (CLS)")

	def test_bicim_sirasi_avif_once(self):
		"""Tarayıcı İLK desteklediğini seçer; AVIF WebP'den önce gelmeli."""
		html = P.render_picture(el_manifesti())
		sira = re.findall(r'type="image/([a-z]+)"', html)
		self.assertEqual(sira, ["avif", "webp"], "yedek biçim `<img>`e taşınır, `<source>`ta olmaz")
		# Yedek (jpeg) `<img srcset>` üzerinde.
		img = re.search(r"<img [^>]*>", html).group(0)
		self.assertIn("__w640.jpeg", img)
		self.assertNotIn(".avif", img)

	def test_srcset_genislik_tanimlayicisi_artan(self):
		html = P.render_picture(kart_manifesti())
		for srcset in re.findall(r'srcset="([^"]+)"', html):
			genislikler = [int(g) for g in re.findall(r"(\d+)w", srcset)]
			self.assertEqual(genislikler, sorted(genislikler), f"srcset sırası bozuk: {srcset}")
			self.assertEqual(len(genislikler), len(set(genislikler)), "srcset'te yinelenen genişlik")


class BoyutVeCLS(unittest.TestCase):
	"""`width`/`height` HER ZAMAN — yoksa üretim durur."""

	def test_intrinsic_manifestten(self):
		self.assertEqual(P.intrinsic_size(kart_manifesti()), (2400, 2400))

	def test_intrinsic_pad_profilinden_turetilir(self):
		"""`fit: pad` + `target_ratio: 1:1` → yükseklik hesaptır, varsayım değil."""
		m = kart_manifesti(intrinsic=(0, 0), available_profiles=["w96", "w192"])
		self.assertEqual(P.intrinsic_size(m), (192, 192))

	def test_olcu_yoksa_hata(self):
		m = el_manifesti(
			intrinsic_width=0,
			intrinsic_height=0,
			variants=(Variant(profile="w640", url="/files/ab/x__w640.jpeg", width=0, fmt="jpeg"),),
		)
		with self.assertRaises(P.PictureError):
			P.render_picture(m)

	def test_her_img_boyut_tasir(self):
		html = P.render_many([kart_manifesti() for _ in range(5)], first_is_priority=True)
		olcum = P.audit(html)
		self.assertEqual(olcum["img"], 5)
		self.assertEqual(olcum["eksik_boyut"], 0)


class OncelikDavranisi(unittest.TestCase):
	"""`priority=True` → `loading` HİÇ yazılmaz, `fetchpriority=high`."""

	def test_oncelikli_img_loading_tasimaz(self):
		html = P.render_picture(kart_manifesti(), P.PictureOptions(priority=True))
		self.assertNotIn("loading=", html)
		self.assertIn('fetchpriority="high"', html)
		self.assertIn('decoding="sync"', html)

	def test_onceliksiz_img_lazy(self):
		html = P.render_picture(kart_manifesti(), P.PictureOptions(priority=False))
		self.assertIn(f'loading="{LOADING_LAZY}"', html)
		self.assertNotIn("fetchpriority", html)
		self.assertIn('decoding="async"', html)

	def test_oncelik_manifestten_okunur(self):
		m = kart_manifesti(is_lcp_candidate=True)
		self.assertTrue(P.is_priority(m))
		self.assertNotIn("loading=", P.render_picture(m))

	def test_karusel_ilk_slayt_eager_kalani_lazy(self):
		"""Galeri kuralı: ilk slayt öncelikli, kalanı lazy (faz12-lcp.md §3)."""
		html = P.render_many([kart_manifesti() for _ in range(4)], first_is_priority=True)
		self.assertEqual(P.audit(html)["fetchpriority_high"], 1)
		self.assertEqual(P.audit(html)["loading_lazy"], 3)


class Lqip(unittest.TestCase):
	def test_duz_renk(self):
		html = P.render_picture(kart_manifesti(), P.PictureOptions(lqip="#e8e4dc"))
		self.assertIn('style="background-color:#e8e4dc"', html)

	def test_data_uri(self):
		uri = "data:image/webp;base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA="
		html = P.render_picture(kart_manifesti(), P.PictureOptions(lqip=uri))
		self.assertIn("background-image:url(data:image/webp;base64,", html)
		self.assertIn("background-size:cover", html)

	def test_serbest_metin_reddedilir(self):
		"""`style` içine serbest metin yazmak öznitelik kaçışıdır."""
		for kotu in ('url(javascript:alert(1))', 'red;} body{display:none', "#zzzzzz"):
			with self.assertRaises(P.PictureError, msg=kotu):
				P.lqip_style(kotu)


class Guvenlik(unittest.TestCase):
	def test_javascript_semasi_reddedilir(self):
		m = el_manifesti(fallback_url="javascript:alert(1)")
		with self.assertRaises(P.PictureError):
			P.render_picture(m)

	def test_alt_metni_kacisla_yazilir(self):
		m = kart_manifesti(alt='Kırmızı "orta" 12\'li <b>set</b> & kapak')
		html = P.render_picture(m)
		self.assertIn("&lt;b&gt;", html)
		self.assertIn("&quot;orta&quot;", html)
		self.assertNotIn("<b>", html)

	def test_bos_alt_dusurulmez(self):
		"""`alt=""` dekoratif işaretidir; düşerse ekran okuyucu URL okur."""
		html = P.render_picture(kart_manifesti(alt=""))
		self.assertIn('alt=""', html)

	def test_require_alt_bos_alti_reddeder(self):
		with self.assertRaises(P.PictureError):
			P.render_picture(kart_manifesti(alt=""), P.PictureOptions(require_alt=True))


class TekBicim(unittest.TestCase):
	"""Tek biçimde `<picture>` sarmalı üretilmez — boş kabuk olurdu."""

	def test_webp_tek_basina_img_uretir(self):
		m = kart_manifesti(available_profiles=["w96", "w192"])
		html = P.render_picture(m)
		self.assertTrue(html.startswith("<img "), html[:40])
		self.assertNotIn("<picture", html)
		self.assertIn("srcset=", html)


class Preload(unittest.TestCase):
	"""Dört sayfada da LCP görseli 'ilk belgede keşfedilebilir' testinden düşüyor."""

	def test_imagesrcset_ve_imagesizes_birlikte(self):
		m = kart_manifesti()
		link = P.preload_link(m, P.PictureOptions(sizes=PDP_SIZES))
		self.assertIn('rel="preload"', link)
		self.assertIn('as="image"', link)
		self.assertIn("imagesrcset=", link)
		self.assertIn("imagesizes=", link)
		self.assertIn('fetchpriority="high"', link)
		self.assertIn('type="image/avif"', link)

	def test_olmayan_bicim_hata(self):
		with self.assertRaises(P.PictureError):
			P.preload_link(kart_manifesti(), fmt="jxl")


class CiktiKararliligi(unittest.TestCase):
	"""Aynı girdi → aynı bayt. ETag ve anlık görüntü testleri buna bağlı."""

	def test_idempotent(self):
		m = kart_manifesti()
		opt = P.PictureOptions(sizes=PDP_SIZES, lqip="#ffffff", priority=True)
		self.assertEqual(P.render_picture(m, opt), P.render_picture(m, opt))

	def test_beklenen_html_birebir(self):
		"""Frontend ekibine verilecek referans çıktı — değişirse bilerek değişsin."""
		m = kart_manifesti(available_profiles=["w384", "w640"])
		html = P.render_picture(m, P.PictureOptions(sizes="(min-width: 768px) 172px, 50vw"))
		beklenen = (
			'<picture>'
			'<source type="image/avif" '
			f'srcset="/files/ab/{HASH}__w384.avif 384w, /files/ab/{HASH}__w640.avif 640w" '
			'sizes="(min-width: 768px) 172px, 50vw">'
			'<img '
			# `src` merdivenin ORTA basamağı — manifest.py `_fallback_url`
			# gerekçesi: en büyüğü fallback yapmak `srcset` desteklemeyen
			# istemciye en pahalı dosyayı gönderirdi.
			f'src="/files/ab/{HASH}__w640.webp" '
			f'srcset="/files/ab/{HASH}__w384.webp 384w, /files/ab/{HASH}__w640.webp 640w" '
			'sizes="(min-width: 768px) 172px, 50vw" '
			'alt="Bonny erzak saklama kabı 1 lt" width="2400" height="2400" '
			'loading="lazy" decoding="async">'
			'</picture>'
		)
		self.assertEqual(html, beklenen)


class ManifestleUyum(unittest.TestCase):
	"""Üretilmemiş türev `srcset`e GİRMEZ — 404 = görsel hiç görünmez."""

	def test_uretilmemis_profil_srcsette_yok(self):
		m = kart_manifesti(available_profiles=["w384"])
		html = P.render_picture(m)
		self.assertIn("__w384.", html)
		for eksik in ("__w640.", "__w768.", "__w1280.", "__w1920."):
			self.assertNotIn(eksik, html, f"üretilmemiş {eksik} `srcset`e sızdı")


if __name__ == "__main__":  # pragma: no cover
	unittest.main(verbosity=2)
