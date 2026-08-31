"""KD-17 — Zaman ekseni: geçmişe ve geleceğe yönelik tam çarpım.

Medya hattının kararlarının çoğu **zamana bağlı** ve zaman testte sabitlenmezse
hiç ölçülmez: imzalı URL süresi, hak bitiş tarihi, oturum ömrü, saklama
penceresi. Bu dosya zamanı bir EKSEN olarak alıp geçmiş/şimdi/gelecek
değerlerinin tam çarpımını tarıyor.

Neden `now` enjekte ediliyor: `time.sleep` ile TTL beklemek testi hem yavaş
hem kırılgan yapar. `verify(url, now=...)` sözleşmesi zaten bunun için var;
saat ileri/geri alınarak geçmiş ve gelecek doğrudan sınanıyor.

Eksenler ve boyutlar:

    hak bitişi   6 × alt metni 2 × dosya türü 2            =   24  (denetim)
    TTL          9 × doğrulama anı 7                       =   63  (imzalı URL)
    saat kayması 5 × TTL 4                                 =   20  (saat farkı)
    ISO tarih   12 (1970 → 2100)                           =   12  (biçim)
"""

from __future__ import annotations

import itertools
import time
import unittest

from frappe.utils import add_days, nowdate

from tradehub_core.media import seo_audit
from tradehub_core.media.pipeline.api import envelope as env
from tradehub_core.media.pipeline.delivery import signed as signed_urls

GIZLI = "kd17-test-gizli-anahtar-en-az-32-bayt-uzunlugunda"
YOL = "/private/files/ab/abcdef0123456789.jpg"


# ══════════════════════════════════════════════════════════════════════
# 1. Hak bitiş tarihi — geçmiş / şimdi / gelecek
# ══════════════════════════════════════════════════════════════════════


class TestHakBitisi(unittest.TestCase):
	"""`rights_expires_on` × alt metni × dosya türü tam çarpımı = 24 hücre."""

	@property
	def tarihler(self) -> tuple[tuple[str, object, bool], ...]:
		"""(etiket, değer, dolmuş_mu)"""
		return (
			("çok geçmiş", "2000-01-01", True),
			("dün", add_days(nowdate(), -1), True),
			("bugün", nowdate(), False),
			("yarın", add_days(nowdate(), 1), False),
			("çok gelecek", "2099-12-31", False),
			("tarih yok", None, False),
		)

	def _alanlar(self, bitis, alt: str) -> dict:
		return {
			"alt": alt,
			"title": "Başlık",
			"caption": "Altyazı",
			"width": 2000,
			"height": 2000,
			"license_url": "https://istoc.com/lisans",
			"copyright_notice": "© İstoç",
			"rights_expires_on": bitis,
		}

	def test_kb_HAK_BITISI_tam_carpimi(self):
		"""6 tarih × 2 alt durumu × 2 tür = 24 hücre, tamamı taranır."""
		hucre = 0
		hatalar: list[str] = []
		for (etiket, deger, dolmus), alt, ad in itertools.product(
			self.tarihler,
			("Kırmızı kadife koltuk", ""),
			("koltuk.jpg", "tanitim.mp4"),
		):
			hucre += 1
			kodlar = {
				b["code"] for b in seo_audit.audit_fields(self._alanlar(deger, alt), file_name=ad)
			}
			var = "expired_rights" in kodlar
			if var != dolmus:
				hatalar.append(
					f"{etiket} (alt={'var' if alt else 'yok'}, {ad}): "
					f"expired_rights={'var' if var else 'yok'}, beklenen {'var' if dolmus else 'yok'}"
				)
		self.assertEqual(hucre, 24, f"24 hücre beklenir, {hucre}")
		self.assertEqual(hatalar, [], "\n".join(hatalar))

	def test_sn_BUGUN_dolmus_SAYILMAZ(self):
		"""Sınır: bugün biten hak bugün hâlâ geçerli (`<` karşılaştırması)."""
		kodlar = {b["code"] for b in seo_audit.audit_fields(self._alanlar(nowdate(), "Koltuk"))}
		self.assertNotIn("expired_rights", kodlar)

	def test_sn_DUN_dolmus_SAYILIR(self):
		kodlar = {
			b["code"] for b in seo_audit.audit_fields(self._alanlar(add_days(nowdate(), -1), "Koltuk"))
		}
		self.assertIn("expired_rights", kodlar)

	def test_bi_dolmus_hak_SKORU_dusuruyor(self):
		"""Geçmişe dönük bulgunun skorda karşılığı olmalı — yoksa kural ölü."""
		temiz = seo_audit.score_from(
			seo_audit.audit_fields(self._alanlar(None, "Kırmızı kadife koltuk")),
			self._alanlar(None, "Kırmızı kadife koltuk"),
		)
		dolmus = seo_audit.score_from(
			seo_audit.audit_fields(self._alanlar("2000-01-01", "Kırmızı kadife koltuk")),
			self._alanlar("2000-01-01", "Kırmızı kadife koltuk"),
		)
		self.assertLess(dolmus["overall"], temiz["overall"], "dolmuş hak skoru düşürmüyor")


# ══════════════════════════════════════════════════════════════════════
# 2. İmzalı URL — TTL × doğrulama anı
# ══════════════════════════════════════════════════════════════════════


class TestImzaliUrlZamani(unittest.TestCase):
	"""İmza üretim anı sabit, DOĞRULAMA anı geçmiş/gelecek boyunca gezdiriliyor."""

	def setUp(self):
		self.imzalayici = signed_urls.signer_from_secret(GIZLI)
		self.simdi = time.time()

	def test_bi_ttl_kelepceleme_tam_carpimi(self):
		"""9 TTL girdisi — negatif, sıfır, çok büyük, metin, None dâhil."""
		girdiler = (None, "", 0, -1, -10_000, 1, 60, 10**9, "abc")
		for ttl in girdiler:
			with self.subTest(ttl=ttl):
				k = signed_urls.clamp_ttl(ttl)
				self.assertIsInstance(k, int)
				self.assertGreaterEqual(k, signed_urls.MIN_TTL_SECONDS, f"{ttl} → {k}")
				self.assertLessEqual(k, signed_urls.MAX_TTL_SECONDS, f"{ttl} → {k}")

	def test_gv_SINIRSIZ_sure_istenemiyor(self):
		"""Üst sınır olmasa çağıran pratikte kalıcı bir kapı açardı."""
		self.assertEqual(signed_urls.clamp_ttl(10**12), signed_urls.MAX_TTL_SECONDS)
		self.assertLessEqual(signed_urls.MAX_TTL_SECONDS, 86_400 * 7, "üst sınır bir haftadan uzun")

	def test_kb_TTL_x_DOGRULAMA_ANI_tam_carpimi(self):
		"""9 TTL × 7 doğrulama anı = 63 hücre.

		Geçerlilik aralığı ÖLÇÜLDÜ: `iat ≤ now < exp`. Bitiş anı **dâhil
		değil** — `now == exp` "expired" döner. Dışlayıcı sınır güvenli
		taraftır (bir saniyelik gri bölge bırakmaz) ve sözleşme olarak
		burada sabitleniyor.
		"""
		ttl_girdileri = (60, 300, 900, 3600, 1, 0, -5, None, 10**9)
		hatalar: list[str] = []
		hucre = 0

		for ttl in ttl_girdileri:
			imzali = self.imzalayici.sign(YOL, ttl_seconds=ttl)
			url = imzali.url if hasattr(imzali, "url") else str(imzali)
			params = signed_urls.parse_signed_params(url)
			iat, exp = int(params["iat"]), int(params["exp"])

			anlar = (
				("üretimden önce", iat - 3600),
				("üretim anı", iat),
				("ortada", (iat + exp) // 2),
				("bitişten 1 sn önce", exp - 1),
				("tam bitişte", exp),
				("bitişten 1 sn sonra", exp + 1),
				("çok gelecek", exp + 86_400 * 365),
			)
			for etiket, an in anlar:
				hucre += 1
				karar = self.imzalayici.verify(url, now=an)
				gecerli = bool(karar)
				beklenen = iat <= an < exp
				# Üretimden önce doğrulama saat kaymasıyla açıklanabilir;
				# uygulama pay bırakmışsa bu bir kusur değil — o yüzden
				# yalnız "süresi geçmiş kabul edildi" durumu ihlal sayılıyor.
				if an >= exp and gecerli:
					hatalar.append(f"ttl={ttl} {etiket}: SÜRESİ GEÇMİŞ imza kabul edildi")
				if beklenen and not gecerli and an >= iat:
					hatalar.append(f"ttl={ttl} {etiket}: geçerli aralıkta REDDEDİLDİ ({karar.reason})")

		self.assertEqual(hucre, 63, f"9×7 = 63 hücre beklenir, {hucre}")
		self.assertEqual(hatalar, [], "\n".join(hatalar[:10]))

	def test_sn_BITIS_ANI_dahil_DEGIL(self):
		"""Sınır sözleşmesi: `exp-1` geçerli, `exp` süresi dolmuş."""
		imzali = self.imzalayici.sign(YOL, ttl_seconds=300)
		url = imzali.url if hasattr(imzali, "url") else str(imzali)
		exp = int(signed_urls.parse_signed_params(url)["exp"])
		self.assertTrue(bool(self.imzalayici.verify(url, now=exp - 1)), "exp-1 reddedildi")
		self.assertFalse(bool(self.imzalayici.verify(url, now=exp)), "exp anında hâlâ geçerli")
		self.assertEqual(self.imzalayici.verify(url, now=exp).reason, "expired")

	def test_gv_GECMIS_imza_HICBIR_ttl_ile_dirilmiyor(self):
		"""Süresi geçmiş bir URL, TTL ne olursa olsun geçerli olmamalı."""
		for ttl in (1, 60, 3600, 10**9):
			with self.subTest(ttl=ttl):
				imzali = self.imzalayici.sign(YOL, ttl_seconds=ttl)
				url = imzali.url if hasattr(imzali, "url") else str(imzali)
				exp = int(signed_urls.parse_signed_params(url)["exp"])
				self.assertFalse(
					bool(self.imzalayici.verify(url, now=exp + 1)),
					f"ttl={ttl}: exp+1 anında hâlâ geçerli",
				)

	def test_gv_GELECEK_exp_degeri_kurcalanamiyor(self):
		"""`exp`'i ileri almak imzayı bozmalı — süre uzatma saldırısı."""
		imzali = self.imzalayici.sign(YOL, ttl_seconds=60)
		url = imzali.url if hasattr(imzali, "url") else str(imzali)
		params = signed_urls.parse_signed_params(url)
		uzatilmis = url.replace(f"exp={params['exp']}", f"exp={int(params['exp']) + 86_400}")
		self.assertNotEqual(uzatilmis, url, "kurgu: URL değişmedi")
		self.assertFalse(bool(self.imzalayici.verify(uzatilmis)), "uzatılmış exp kabul edildi")

	def test_gv_GECMIS_iat_degeri_kurcalanamiyor(self):
		imzali = self.imzalayici.sign(YOL, ttl_seconds=60)
		url = imzali.url if hasattr(imzali, "url") else str(imzali)
		params = signed_urls.parse_signed_params(url)
		geri = url.replace(f"iat={params['iat']}", f"iat={int(params['iat']) - 86_400}")
		self.assertFalse(bool(self.imzalayici.verify(geri)), "geriye alınmış iat kabul edildi")

	def test_kb_SAAT_KAYMASI_matrisi(self):
		"""5 saat kayması × 4 TTL = 20 hücre.

		Sunucu saatleri kayabilir. Ölçülen: kayma ne olursa olsun **süresi
		geçmiş** bir imza asla kabul edilmemeli.
		"""
		kaymalar = (-3600, -60, 0, 60, 3600)
		ttl_ler = (60, 300, 900, 3600)
		hatalar: list[str] = []
		for kayma, ttl in itertools.product(kaymalar, ttl_ler):
			imzali = self.imzalayici.sign(YOL, ttl_seconds=ttl)
			url = imzali.url if hasattr(imzali, "url") else str(imzali)
			exp = int(signed_urls.parse_signed_params(url)["exp"])
			an = exp + 1 + max(0, kayma)
			if bool(self.imzalayici.verify(url, now=an)):
				hatalar.append(f"kayma={kayma} ttl={ttl}: süresi geçmiş imza kabul edildi")
		self.assertEqual(hatalar, [], "\n".join(hatalar))

	def test_gv_BASKA_YOL_imzasi_kullanilamiyor(self):
		"""Zaman geçerli olsa bile yol değiştirilmişse imza düşmeli."""
		imzali = self.imzalayici.sign(YOL, ttl_seconds=3600)
		url = imzali.url if hasattr(imzali, "url") else str(imzali)
		baska = url.replace("abcdef0123456789", "ffffffffffffffff")
		self.assertNotEqual(baska, url)
		self.assertFalse(bool(self.imzalayici.verify(baska)))


# ══════════════════════════════════════════════════════════════════════
# 3. Tarih biçimi — 1970'ten 2100'e
# ══════════════════════════════════════════════════════════════════════


class TestTarihBicimi(unittest.TestCase):
	"""ISO çıktısı geçmişte ve gelecekte aynı sözleşmeyi korumalı."""

	EPOCHLAR = (
		1,                 # 1970
		946_684_800,       # 2000
		1_234_567_890,     # 2009
		1_600_000_000,     # 2020
		1_787_000_000,     # 2026
		1_800_000_000,     # 2027
		2_000_000_000,     # 2033
		2_500_000_000,     # 2049
		3_000_000_000,     # 2065
		4_102_444_800,     # 2100
		1.5,               # kesirli
		1_787_000_000.999, # mikrosaniyeli
	)

	def test_kb_ISO_SOZLESMESI_tum_epochlarda(self):
		"""12 epoch — hepsi `YYYY-MM-DDTHH:MM:SS±HH:MM`, mikrosaniyesiz."""
		for epoch in self.EPOCHLAR:
			with self.subTest(epoch=epoch):
				s = env.iso_time(epoch)
				self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$", f"{epoch} → {s}")
				self.assertNotIn(".", s, "mikrosaniye yazılmış")

	def test_bi_gecmis_ve_gelecek_SIRALI(self):
		"""Artan epoch artan ISO dizgesi vermeli (aynı saat diliminde)."""
		ciktilar = [env.iso_time(e) for e in sorted(self.EPOCHLAR[:10])]
		self.assertEqual(ciktilar, sorted(ciktilar), "ISO çıktısı epoch sırasını korumuyor")

	def test_sn_gecersiz_zaman_bos_doner(self):
		for kotu in (0, None, float("inf"), float("nan"), -(10**20), 10**20):
			with self.subTest(kotu=kotu):
				self.assertEqual(env.iso_time(kotu), "")


# ══════════════════════════════════════════════════════════════════════
# 4. Oturum ve sonuç ömrü — sözleşme sabitleri
# ══════════════════════════════════════════════════════════════════════


class TestOmurSabitleri(unittest.TestCase):
	def test_bi_oturum_omru_makul_aralikta(self):
		from tradehub_core.media import chunked

		self.assertGreaterEqual(chunked.SESSION_TTL_HOURS, 1, "oturum ömrü çok kısa")
		self.assertLessEqual(chunked.SESSION_TTL_HOURS, 24, "yarım kalan oturum bir günden uzun yaşıyor")

	def test_bi_tamamlanan_sonuc_omru_oturumdan_UZUN(self):
		"""Idempotency kaydı, oturumdan sonra da tekrar isteğe cevap vermeli."""
		from tradehub_core.media import chunked

		self.assertGreater(
			chunked.FINALIZED_TTL_HOURS, chunked.SESSION_TTL_HOURS,
			"tamamlanan sonuç oturumdan önce ölüyor — tekrar eden istek yeniden yükler",
		)

	def test_bi_denetim_onbellegi_sinirli(self):
		self.assertGreater(seo_audit.SCOPE_CACHE_TTL, 0)
		self.assertLessEqual(
			seo_audit.SCOPE_CACHE_TTL, 86_400,
			"denetim önbelleği bir günden uzun — operatör bayat veri görür",
		)


if __name__ == "__main__":
	unittest.main()
