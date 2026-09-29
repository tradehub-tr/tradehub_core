"""C6 + C7 + MOGEM-685 F-02 — Sepet/sipariş kupon güvenlik testleri.

api/cart._reserve_coupon (sipariş anında kuponu AYIRIR):
  - kupon satırı kilitli okunur (for_update), kişi başı sayım kilitli okumayla
  - percent/fixed indirim server'da koddan hesaplanır, YALNIZ ürün toplamına uygulanır;
    `shipping` kuponu kargo ücretini düşer (ön yüzle aynı kural — Adım 3, 28 Eyl:
    eskiden taban ürün+kargoydu, ekranda gösterilen ≠ tahsil edilen)
  - minimum tutar kargo hariç ürün toplamına bakar (ön yüz `checkout.ts` ile aynı)
  - geçersiz / süresi dolmuş / sınırı dolmuş / min tutar / kişi başı kullanılmış →
    sipariş REDDEDİLİR (eskiden indirim sessizce 0'a düşüyordu — kullanıcı kararı
    28 Eyl: indirimli fiyatı görüp tam fiyat ödeme olmasın)
  - used_count kilit altında artırılır; indirim 0 ise artırılmaz
  - kod normalize döner (baştaki boşluk kişi başı sayımı atlatmasın)
Gerçek eşzamanlılık (iki bağlantı) test_coupon_race.py'de, bench ile.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_cart_price_tampering
"""

from __future__ import annotations

import datetime
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


class _ValidationError(Exception):
	pass


# Test kupon kayıtları: code → dict
_COUPONS: dict = {}
# Kişi başı kullanım: (buyer, coupon_code) → iptal edilmemiş sipariş sayısı
_USAGE: dict = {}
# Gözlem: kilitli okumalar ve çalışan SQL'ler
_LOCKS: list = []
_SQL: list = []


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.ValidationError = _ValidationError
	frappe._ = lambda s: s
	frappe.throw = lambda msg, exc=_ValidationError: (
		(_ for _ in ()).throw(exc(msg)) if False else (_raise(exc, msg))
	)

	def _get_value(doctype, filters=None, fieldname=None, as_dict=False, **kw):
		if kw.get("for_update"):
			_LOCKS.append(doctype)
		if doctype == "Coupon" and isinstance(filters, dict):
			code = filters.get("code")
			c = _COUPONS.get(code)
			if not c:
				return None
			if as_dict:
				return SimpleNamespace(**c)
			return c.get(fieldname)
		return None

	def _count(doctype, filters=None, **kw):
		if doctype == "Order" and isinstance(filters, dict):
			return _USAGE.get((filters.get("buyer"), filters.get("coupon_code")), 0)
		return 0

	def _sql(query, values=None, **kw):
		_SQL.append((" ".join(query.split()).lower(), values))
		if "count(*)" in query.lower() and "taborder" in query.lower():
			buyer, code = values
			return ((_USAGE.get((buyer, code), 0),),)
		return ()

	def _get_all(doctype, filters=None, fields=None, **kw):
		_SQL.append((f"get_all {doctype}".lower(), filters))
		if doctype == "Order":
			buyer = (filters or {}).get("buyer")
			return [kod for (b, kod), n in _USAGE.items() if b == buyer and n > 0]
		if doctype != "Coupon":
			return []
		return [SimpleNamespace(**{"code": c, **v}) for c, v in _COUPONS.items() if v.get("is_active", 1)]

	frappe.db = SimpleNamespace(get_value=_get_value, count=_count, sql=_sql)
	frappe.get_all = _get_all
	frappe.session = SimpleNamespace(user="Guest")
	# cart.py 23 Tem 2026'dan beri `from frappe.utils import flt` yapıyor; bu alt
	# modül stub'da yokken import düşüyor ve 8 testin 8'i sessizce SKIP oluyordu.
	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda v, precision=None: (
		round(float(v or 0), precision) if precision is not None else float(v or 0)
	)
	frappe.utils = utils
	sys.modules["frappe.utils"] = utils
	frappe.whitelist = lambda *a, **k: a[0] if (a and callable(a[0])) else (lambda fn: fn)


def _raise(exc, msg):
	raise exc(msg)


_install_frappe_stub()
# Bu dosyanın frappe stub'ını sakla — testler birlikte koşulduğunda başka bir test
# sys.modules['frappe']'i değiştirse de hedef modülün frappe'sini buna geri bağlarız.
_FRAPPE_STUB = sys.modules["frappe"]

# cart.py geniş; importunu kolaylaştırmak için iç bağımlılıkları stub'la.
# NOT: `tradehub_core.api._input` STUB'LANMAZ — gerçek modül hafif (yalnız frappe.throw
# kullanır) ve başka testler (seller) `safe_float`'a ihtiyaç duyar; eksik stub sızıntısı
# import kırardı. Gerçek modül stub frappe altında sorunsuz import edilir.
for _mod, _attrs in {
	"tradehub_core.api.rate_limit": {"rate_limit": lambda *a, **k: lambda fn: fn},
	"tradehub_core.utils.auth_guards": {"require_verified_email": lambda fn: fn},
	"tradehub_core.utils.stock": {
		"deduct_stock_for_order": lambda *a, **k: None,
		"reserve_stock_for_order": lambda *a, **k: None,
	},
}.items():
	m = types.ModuleType(_mod)
	for k, v in _attrs.items():
		setattr(m, k, v)
	sys.modules[_mod] = m


def _try_import_cart():
	"""cart.py'yi bu dosyanın stub'ları aktifken bir kez import et.

	Hata YUTULMAZ, saklanır: eskiden `None` dönüp testleri skip'e düşürüyordu ve
	import 23 Tem–28 Eyl 2026 arası kırıkken kimse fark etmedi (MOGEM-685).
	"""
	try:
		from tradehub_core.api import cart as cart_mod

		return cart_mod, None
	except Exception as exc:  # noqa: BLE001 — setUp'ta test HATASI olarak raporlanır
		return None, exc


# Modül seviyesinde TEK SEFER import et (bu dosyanın stub'ları aktifken). Lazy/setUp
# içinde re-import edilirse, başka bir testin contaminated frappe'siyle import patlar
# ve test skip olur. Bu referansı sakla; setUp yalnızca frappe'yi geri bağlar.
_CART_MOD, _CART_IMPORT_ERROR = _try_import_cart()


def _kupon(**alan):
	"""Varsayılanları dolu bir kupon kaydı — testte yalnız farkı yaz."""
	return {
		"name": "c",
		"coupon_type": "fixed",
		"value": 10,
		"min_order": 0,
		"max_uses": 0,
		"used_count": 0,
		"description": "",
		"expires_at": None,
		**alan,
	}


class _Temel(unittest.TestCase):
	def setUp(self):
		_COUPONS.clear()
		_USAGE.clear()
		_LOCKS.clear()
		_SQL.clear()
		if _CART_MOD is None:
			self.fail(f"cart modülü stub ortamında import edilemedi: {_CART_IMPORT_ERROR!r}")
		self.cart = _CART_MOD
		# İzolasyon: cart başka bir testin frappe stub'ına bağlı kalmış olabilir.
		self.cart.frappe = _FRAPPE_STUB
		_FRAPPE_STUB.session.user = "Guest"

	def _artis(self):
		return [q for q, _v in _SQL if q.startswith("update `tabcoupon`")]


class TestCouponReservation(_Temel):
	"""_reserve_coupon — sipariş anında kupon ayırma (F-02)."""

	ALICI = "alici@test.local"

	def _ayir(self, kod, tutar=100, kargo=0):
		return self.cart._reserve_coupon(kod, tutar, kargo, self.ALICI)

	def _red(self, kod, tutar=100, kargo=0):
		with self.assertRaises(_ValidationError) as ctx:
			self._ayir(kod, tutar, kargo)
		self.assertEqual(self._artis(), [], "reddedilen kuponda sayaç ARTMAMALI")
		return str(ctx.exception)

	def test_sabit_indirim_kilitli_okunur_ve_sayac_artar(self):
		_COUPONS["SAVE10"] = _kupon(value=10)
		self.assertEqual(self._ayir("save10"), ("SAVE10", 10.0))
		self.assertEqual(_LOCKS, ["Coupon"], "kupon satırı for_update ile okunmalı")
		self.assertEqual(len(self._artis()), 1)

	def test_yuzde_indirim(self):
		_COUPONS["P20"] = _kupon(coupon_type="percent", value=20)
		self.assertEqual(self._ayir("p20"), ("P20", 20.0))

	def test_indirim_tutari_asamaz(self):
		_COUPONS["HUGE"] = _kupon(value=999999)
		self.assertEqual(self._ayir("huge", 50), ("HUGE", 50.0))

	def test_kod_normalize_doner(self):
		# Sipariş bu kodu saklar: baştaki boşlukla kişi başı sayım atlatılamasın.
		_COUPONS["SAVE10"] = _kupon(value=10)
		self.assertEqual(self._ayir("  save10 ")[0], "SAVE10")

	def test_bulunamayan_kupon_reddedilir(self):
		msg = self._red("NOPE")
		self.assertIn("Geçersiz veya süresi dolmuş", msg)
		self.assertIn("sipariş oluşturulmadı", msg)

	def test_sinir_dolmus_reddedilir(self):
		_COUPONS["DONE"] = _kupon(max_uses=5, used_count=5)
		self.assertIn("maksimum kullanım", self._red("done"))

	def test_minimum_tutar_reddedilir(self):
		_COUPONS["MIN"] = _kupon(min_order=200)
		self.assertIn("minimum sipariş tutarı", self._red("min"))

	def test_suresi_dolmus_reddedilir(self):
		_COUPONS["OLD"] = _kupon(expires_at=datetime.date(2000, 1, 1))
		self.assertIn("süresi dolmuş", self._red("old"))

	def test_kisi_basi_kullanilmis_reddedilir_ve_sayim_kilitli(self):
		_COUPONS["TEK"] = _kupon(max_uses=100)
		_USAGE[(self.ALICI, "TEK")] = 1
		self.assertIn("daha önce kullandınız", self._red("tek"))
		sayim = [q for q, _v in _SQL if "count(*)" in q]
		self.assertTrue(sayim and "lock in share mode" in sayim[0], f"kilitsiz sayım: {sayim}")

	# ── Adım 3: indirim tabanı (1.000 ₺ ürün + 30 ₺ kargo) ─────────────────
	def test_yuzde_kupon_kargoyu_haric_tutar(self):
		_COUPONS["P10"] = _kupon(coupon_type="percent", value=10)
		self.assertEqual(self._ayir("p10", 1000, 30), ("P10", 100.0))

	def test_sabit_kupon_urun_toplamini_asamaz(self):
		_COUPONS["F1020"] = _kupon(value=1020)
		self.assertEqual(self._ayir("f1020", 1000, 30), ("F1020", 1000.0))

	def test_kargo_kuponu_kargo_ucretini_duser(self):
		_COUPONS["KARGO"] = _kupon(coupon_type="shipping", value=0)
		self.assertEqual(self._ayir("kargo", 1000, 30), ("KARGO", 30.0))
		self.assertEqual(len(self._artis()), 1)

	def test_kargo_kuponu_degeri_yok_sayilir(self):
		# value=50 iken eskiden 50 ₺ sabit indirim uyguluyordu (ekranda 30 ₺ görünürken).
		_COUPONS["KARGO50"] = _kupon(coupon_type="shipping", value=50)
		self.assertEqual(self._ayir("kargo50", 1000, 30), ("KARGO50", 30.0))

	def test_kargo_kuponu_ucretsiz_kargoda_sifir(self):
		_COUPONS["KARGO"] = _kupon(coupon_type="shipping", value=0)
		self.assertEqual(self._ayir("kargo", 1000, 0), ("KARGO", 0.0))
		self.assertEqual(self._artis(), [])

	def test_minimum_tutar_kargo_haric(self):
		_COUPONS["MIN1000"] = _kupon(min_order=1000)
		self.assertIn("minimum sipariş tutarı", self._red("min1000", 990, 30))

	def test_sifir_indirimde_sayac_artmaz(self):
		_COUPONS["BOS"] = _kupon(value=0)
		self.assertEqual(self._ayir("bos"), ("BOS", 0.0))
		self.assertEqual(self._artis(), [])


class TestCouponSplit(_Temel):
	"""_split_coupon_discount — çok satıcılı siparişte orantılı dağıtım."""

	def test_orantili(self):
		# Eşit bölmede 100 ₺ ürünlü siparişe 150 ₺ indirim düşüp toplam eksiye gidiyordu.
		self.assertEqual(self.cart._split_coupon_discount(300, [100, 900]), [30.0, 270.0])

	def test_kurus_farki_sonuncuya(self):
		payler = self.cart._split_coupon_discount(100, [1, 1, 1])
		self.assertEqual(payler, [33.33, 33.33, 33.34])
		self.assertAlmostEqual(sum(payler), 100.0)

	def test_taban_sifirsa_indirim_yok(self):
		self.assertEqual(self.cart._split_coupon_discount(30, [0, 0]), [0.0, 0.0])


class TestCouponRulesCharacterization(_Temel):
	"""validate_coupon + get_buyer_coupons — sepetteki önizleme ve liste."""

	def _hata(self, kod, tutar=100):
		with self.assertRaises(_ValidationError) as ctx:
			self.cart.validate_coupon(kod, tutar)
		return str(ctx.exception)

	def test_validate_bulunamayan_kupon(self):
		self.assertIn("Geçersiz veya süresi dolmuş", self._hata("YOK"))

	def test_validate_suresi_dolmus(self):
		_COUPONS["ESKI"] = _kupon(expires_at=datetime.date(2000, 1, 1))
		self.assertIn("süresi dolmuş", self._hata("ESKI"))

	def test_validate_kullanim_siniri_dolmus(self):
		_COUPONS["BITTI"] = _kupon(max_uses=1, used_count=1)
		self.assertIn("maksimum kullanım", self._hata("BITTI"))

	def test_validate_minimum_tutar(self):
		_COUPONS["MIN"] = _kupon(min_order=500)
		self.assertIn("minimum sipariş tutarı: 500", self._hata("MIN", 100))

	def test_validate_gecerli_sabit_kupon_tutara_kirpilir(self):
		_COUPONS["BUYUK"] = _kupon(code="BUYUK", value=300)
		sonuc = self.cart.validate_coupon("buyuk", 120)
		self.assertEqual((sonuc["code"], sonuc["type"], sonuc["value"]), ("BUYUK", "fixed", 120))

	def test_validate_gecerli_yuzde_kupon(self):
		_COUPONS["YUZDE"] = _kupon(code="YUZDE", coupon_type="percent", value=15, min_order=50)
		sonuc = self.cart.validate_coupon("YUZDE", 100)
		self.assertEqual((sonuc["value"], sonuc["minOrder"]), (15, 50.0))

	def test_validate_kisi_basi_kullanilmis(self):
		# F-02 kararı: sepette "geçerli" görünüp siparişte reddedilmesin.
		_FRAPPE_STUB.session.user = "alici@test.local"
		_COUPONS["TEK"] = _kupon(code="TEK", max_uses=100)
		_USAGE[("alici@test.local", "TEK")] = 1
		self.assertIn("daha önce kullandınız", self._hata("tek"))

	def test_validate_misafirde_kisi_basi_atlanir(self):
		_COUPONS["TEK"] = _kupon(code="TEK")
		_USAGE[("Guest", "TEK")] = 1
		self.assertEqual(self.cart.validate_coupon("tek", 100)["code"], "TEK")


class TestBuyerCouponCount(_Temel):
	"""get_buyer_coupons — panodaki "Kuponlar: N" sayacı (MOGEM-685 Adım 4).

	Eskiden her alıcıya TÜM aktif kupon KODLARINI döndürüyordu (ön yüz yalnız sayıyı
	kullanıyordu) ve alıcının zaten kullandığı kuponu da "available" sayıyordu.
	"""

	ALICI = "alici@test.local"

	def setUp(self):
		super().setUp()
		_FRAPPE_STUB.session.user = self.ALICI
		_COUPONS["A"] = _kupon(code="A")
		_COUPONS["E"] = _kupon(code="E", expires_at=datetime.date(2000, 1, 1))
		_COUPONS["U"] = _kupon(code="U", max_uses=2, used_count=2)
		_COUPONS["K"] = _kupon(code="K", max_uses=100)

	def test_yalniz_sayi_doner_kod_donmez(self):
		yanit = self.cart.get_buyer_coupons()
		self.assertEqual(set(yanit), {"available"})
		for kod in _COUPONS:
			self.assertNotIn(f"'{kod}'", repr(yanit))

	def test_suresi_sinir_ve_kisi_basi_haric(self):
		_USAGE[(self.ALICI, "K")] = 1  # K'yi bu alıcı zaten kullandı
		self.assertEqual(self.cart.get_buyer_coupons(), {"available": 1})  # yalnız A

	def test_kisi_basi_tek_sorgu(self):
		self.cart.get_buyer_coupons()
		siparis_sorgulari = [q for q, _v in _SQL if "order" in q]
		self.assertEqual(len(siparis_sorgulari), 1, siparis_sorgulari)


if __name__ == "__main__":
	unittest.main()
