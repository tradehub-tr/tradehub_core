"""KATEGORİ ADI ÇEVİRİ HATTI SÖZLEŞMESİ.

Korunan üç iddia:

1. **Sahte çeviri veritabanına YAZILMAZ.** `api/translation.translate()`
   sağlayıcı yapılandırılmamışken sessizce STUB'a düşer ve `"[tr→en] Oyuncak"`
   döndürür. Bu metin yazılırsa 23.511 kategorilik katalog çöple dolar ve kusur
   ancak vitrinde görülür. Ölçüldü (16 Eyl 2026, lokal): `Translation Settings`
   → `provider=stub`, `openai_api_key` ve `deepl_api_key` NULL.

2. **Hat idempotenttir.** Dolu bir alanın üzerine yazılmaz; ikinci koşum 0 yazar.
   Toplu iş yarıda kesilip tekrar başlatılabilsin diye.

3. **Bilinmeyen dil sessizce Türkçeye düşmez.** `normalize_lang` tanımadığı kodu
   `tr`'ye çevirir; korunmasız bırakılırsa çağıran "de" istediğini sanırken hat
   Türkçeyi tekrarlar ve rapor yalancı bir "de yazıldı" gösterir.

Frappe runtime stub'lanıyor — bench kabuğu gerekmez.

Çalıştırma:
    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_category_i18n
"""

from __future__ import annotations

import json
import re
import sys
import types
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


class SahteDb:
	"""Asgari `frappe.db` — bellekte kayıt tutar."""

	def __init__(self, kayitlar: dict[str, dict]):
		self.kayitlar = kayitlar
		self.commit_sayisi = 0

	def get_value(self, _doctype, name, alan):
		return (self.kayitlar.get(name) or {}).get(alan)

	def set_value(self, _doctype, name, alan, deger, update_modified=True):  # noqa: ARG002
		self.kayitlar.setdefault(name, {})[alan] = deger

	def commit(self):
		self.commit_sayisi += 1

	def count(self, _doctype, _filters=None):
		return len(self.kayitlar)

	def sql(self, _q):
		return [[0]]


def _ci_esit(a: str, b: str) -> bool:
	"""MariaDB `utf8mb4_general_ci` taklidi: `ç→c`, `ş→s`, `ı→i` ayrımı yok."""
	katla = str.maketrans("çÇşŞıİğĞüÜöÖ", "cCsSiIgGuUoO")
	return a.translate(katla).lower() == b.translate(katla).lower()


def _install_frappe_stub(db: SahteDb, collation_ci: bool = False) -> types.ModuleType:
	"""`collation_ci=True` ise ad süzgeci veritabanı gibi harf-duyarsız eşleşir."""
	frappe_stub = types.ModuleType("frappe")

	def whitelist(*_a, **_k):
		def decorator(fn):
			return fn

		return decorator

	def get_all(_doctype, filters=None, fields=None, limit_page_length=None):  # noqa: ARG001
		filters = filters or {}
		bos_alan = next(
			(k for k, v in filters.items() if isinstance(v, list) and v[0] == "in" and v[1] == ["", None]),
			None,
		)
		ad_suzgeci = filters.get("category_name")
		cikti = []
		for name, kayit in db.kayitlar.items():
			if bos_alan and (kayit.get(bos_alan) or "").strip():
				continue
			if isinstance(ad_suzgeci, list) and ad_suzgeci[0] == "in":
				ad = kayit.get("category_name")
				if collation_ci:
					if not any(_ci_esit(ad, aday) for aday in ad_suzgeci[1]):
						continue
				elif ad not in ad_suzgeci[1]:
					continue
			cikti.append({"name": name, "category_name": kayit.get("category_name")})
		return cikti[: limit_page_length or len(cikti)]

	frappe_stub.whitelist = whitelist
	frappe_stub.get_all = get_all
	# `api/translation` modül düzeyinde `from frappe import _` yapıyor.
	frappe_stub._ = lambda metin, *_a, **_k: metin
	frappe_stub.log_error = lambda *_a, **_k: None
	frappe_stub.get_single = lambda *_a, **_k: None
	frappe_stub.conf = {}
	frappe_stub.utils = types.SimpleNamespace(now_datetime=lambda: None)
	sys.modules["frappe.utils"] = types.ModuleType("frappe.utils")
	sys.modules["frappe.utils"].now_datetime = lambda: None
	frappe_stub.db = db
	frappe_stub.only_for = lambda *_a, **_k: None
	frappe_stub.request = None
	sys.modules["frappe"] = frappe_stub
	return frappe_stub


def _kategoriler() -> dict[str, dict]:
	return {
		"CAT-1": {"category_name": "Oyuncak ve Oyun"},
		"CAT-2": {"category_name": "Gıda ve İçecek"},
		# Aynı ad başka bir dalda tekrar ediyor — tohum ADA göre eşleştiği için
		# tek kayıttan ikisi de dolmalı.
		"CAT-3": {"category_name": "Oyuncak ve Oyun"},
	}


TOHUM = {
	"Oyuncak ve Oyun": {"en": "Toys & Games", "ar": "الألعاب", "ru": "Игрушки и игры"},
	"Gıda ve İçecek": {"en": "Food & Beverage", "ar": "الأغذية والمشروبات", "ru": "Еда и напитки"},
}


class KategoriCeviriHattiTesti(unittest.TestCase):
	def setUp(self) -> None:
		# `sys.modules`'tan silmek YETMEZ: `tradehub_core.catalog` paketi cache'te
		# kaldığı sürece `category_i18n` onun ATTRIBUTE'u olarak duruyor ve
		# `from ... import` eski modülü (eski frappe stub'ıyla birlikte) döndürüyor.
		# Ölçüldü: testler tek tek geçerken hep birlikte koşunca düşüyordu.
		sys.modules.pop("frappe", None)
		sys.modules.pop("frappe.utils", None)
		sys.modules.pop("tradehub_core.catalog.category_i18n", None)
		# `translation` BİLEREK pop EDİLMİYOR: testler onu import edip
		# `translate`i değiştiriyor. Pop edilirse `backfill_names` içindeki
		# `from ... import translate` modülü yeniden yükler ve ORİJİNAL
		# fonksiyonu alır — yamanın etkisi kaybolur, gerçek sağlayıcı çağrılır.
		paket = sys.modules.get("tradehub_core.catalog")
		if paket is not None and hasattr(paket, "category_i18n"):
			delattr(paket, "category_i18n")

		self.db = SahteDb(_kategoriler())
		_install_frappe_stub(self.db)
		from tradehub_core.catalog import category_i18n

		self.modul = category_i18n

	# ── 1) Tohum ───────────────────────────────────────────────────────────

	def test_tohum_ada_gore_tum_kopyalari_doldurur(self) -> None:
		rapor = self.modul.apply_name_seed(TOHUM, langs=("en",))

		self.assertEqual(rapor["written"], 3, rapor)
		self.assertEqual(self.db.kayitlar["CAT-1"]["category_name_en"], "Toys & Games")
		self.assertEqual(self.db.kayitlar["CAT-3"]["category_name_en"], "Toys & Games")
		self.assertEqual(self.db.kayitlar["CAT-2"]["category_name_en"], "Food & Beverage")

	def test_tohum_idempotent(self) -> None:
		self.modul.apply_name_seed(TOHUM, langs=("en",))
		ikinci = self.modul.apply_name_seed(TOHUM, langs=("en",))

		self.assertEqual(ikinci["written"], 0, "ikinci koşum yazmamalı")

	def test_tohum_uc_dili_ayri_raporlar(self) -> None:
		rapor = self.modul.apply_name_seed(TOHUM, langs=("en", "ar", "ru"))

		self.assertEqual(rapor["by_lang"]["ar"]["written"], 3)
		self.assertEqual(self.db.kayitlar["CAT-1"]["category_name_ar"], "الألعاب")
		self.assertEqual(self.db.kayitlar["CAT-2"]["category_name_ru"], "Еда и напитки")

	def test_tohumda_olmayan_ad_atlanir(self) -> None:
		self.db.kayitlar["CAT-9"] = {"category_name": "Tohumda Yok"}

		rapor = self.modul.apply_name_seed(TOHUM, langs=("en",))

		self.assertNotIn("category_name_en", self.db.kayitlar["CAT-9"])
		self.assertEqual(rapor["written"], 3)

	def test_bos_deger_yazilmaz(self) -> None:
		rapor = self.modul.apply_name_seed({"Oyuncak ve Oyun": {"en": "   "}}, langs=("en",))

		self.assertEqual(rapor["written"], 0)
		self.assertEqual(rapor["reasons"].get("empty_value"), 2)

	# ── 2) Sağlayıcı hattı — STUB KORUMASI ─────────────────────────────────

	def test_stub_cevirisi_yazilmaz(self) -> None:
		"""Bu testin düştüğü gün katalog `[tr→en] …` ile dolar."""
		from tradehub_core.api import translation

		orijinal = translation.translate
		translation.translate = lambda metin, hedef, kaynak=None: {
			"text": f"[{kaynak}→{hedef}] {metin}",
			"translator": "stub",
		}
		try:
			rapor = self.modul.backfill_names(limit=10, langs=("en",))
		finally:
			translation.translate = orijinal

		self.assertEqual(rapor["written"], 0, "stub çıktısı YAZILMAMALI")
		self.assertEqual(rapor["reasons"].get("stub_provider"), 3)
		for kayit in self.db.kayitlar.values():
			self.assertNotIn("category_name_en", kayit)

	def test_kota_asiminda_da_yazilmaz(self) -> None:
		"""Kota dolunca `translate` `stub-quota` döndürür — o da sahtedir."""
		from tradehub_core.api import translation

		orijinal = translation.translate
		translation.translate = lambda metin, hedef, kaynak=None: {
			"text": f"[{kaynak}→{hedef}] {metin}",
			"translator": "stub-quota",
		}
		try:
			rapor = self.modul.backfill_names(limit=10, langs=("en",))
		finally:
			translation.translate = orijinal

		self.assertEqual(rapor["written"], 0)
		self.assertEqual(rapor["reasons"].get("stub_provider"), 3)

	def test_gercek_saglayici_yazar(self) -> None:
		from tradehub_core.api import translation

		orijinal = translation.translate
		translation.translate = lambda metin, hedef, kaynak=None: {
			"text": f"EN::{metin}",
			"translator": "openai/gpt-4o-mini",
		}
		try:
			rapor = self.modul.backfill_names(limit=10, langs=("en",))
		finally:
			translation.translate = orijinal

		self.assertEqual(rapor["written"], 3)
		self.assertEqual(self.db.kayitlar["CAT-1"]["category_name_en"], "EN::Oyuncak ve Oyun")

	# ── 3) Dil doğrulaması ─────────────────────────────────────────────────

	def test_bilinmeyen_dil_turkceye_dusmez(self) -> None:
		rapor = self.modul.apply_name_seed(TOHUM, langs=("de",))

		self.assertEqual(rapor["written"], 0)
		self.assertEqual(rapor["by_lang"]["de"]["reasons"], {"unknown_lang": 1})
		for kayit in self.db.kayitlar.values():
			self.assertNotIn("category_name_de", kayit)
			self.assertNotIn("category_name_tr", kayit)

	def test_kaynak_dil_ayri_sebeple_ayrilir(self) -> None:
		"""`tr` bilinmeyen değil, çevrilecek bir şeyi olmayan kaynak dildir."""
		rapor = self.modul.apply_name_seed(TOHUM, langs=("tr",))

		self.assertEqual(rapor["by_lang"]["tr"]["reasons"], {"source_lang": 1})


if __name__ == "__main__":
	unittest.main()


class TohumDosyasiTesti(unittest.TestCase):
	"""Diskteki sözlük tohumunun kendi bütünlüğü.

	Tohum elle büyüyor (bugün 800 kayıt). Bir kaydın dili eksik kalırsa hat onu
	`empty_value` sebebiyle atlar ve kategori sessizce Türkçe görünmeye devam
	eder — ekranda hata çıkmaz, kimse fark etmez.

	Yazı sistemi denetimi de burada: ölçüldü (16 Eyl 2026, panel çevirisi
	sırasında) Arapça bir metnin ortasına Kiril harf, Rusça bir metne CJK
	karakter kaçmıştı. İkisi de gözle okunmuyor, tarayıcıda bozuk görünüyor.
	"""

	BEKLENEN_DILLER = {"en", "ar", "ru"}
	CJK = re.compile(r"[　-鿿豈-﫿]")
	ARAP = re.compile(r"[؀-ۿݐ-ݿ]")
	KIRIL = re.compile(r"[Ѐ-ӿ]")

	@classmethod
	def setUpClass(cls) -> None:
		yol = Path(__file__).resolve().parents[1] / "catalog" / "data" / "category_names_seed.json"
		cls.tohum = json.loads(yol.read_text(encoding="utf-8"))

	def test_tohum_beklenen_buyuklukte(self) -> None:
		# Küçülme, bir kaydın yanlışlıkla silindiğini gösterir.
		self.assertGreaterEqual(len(self.tohum), 800, f"tohum {len(self.tohum)} kayıt")

	def test_her_kayit_uc_dilde_dolu(self) -> None:
		eksik = [
			ad
			for ad, karsilik in self.tohum.items()
			if set(karsilik) != self.BEKLENEN_DILLER or any(not str(d).strip() for d in karsilik.values())
		]
		self.assertEqual(eksik[:10], [], f"{len(eksik)} kayıtta dil eksik veya boş")

	def test_yazi_sistemi_kacagi_yok(self) -> None:
		kacaklar = []
		for ad, karsilik in self.tohum.items():
			# `.get` ile okunuyor: dili eksik bir kayıt varsa bu test KeyError ile
			# düşmemeli — o kusuru `test_her_kayit_uc_dilde_dolu` raporluyor.
			ru = karsilik.get("ru", "")
			ar = karsilik.get("ar", "")
			if self.CJK.search(ru) or self.ARAP.search(ru):
				kacaklar.append(f"{ad} → ru: {ru}")
			if self.CJK.search(ar) or self.KIRIL.search(ar):
				kacaklar.append(f"{ad} → ar: {ar}")
		self.assertEqual(kacaklar[:10], [], f"{len(kacaklar)} kayıtta yazı sistemi kaçağı")

	def test_turkce_karsilik_kopyalanmamis(self) -> None:
		"""Çeviri yerine Türkçe adın kopyalanması sessiz bir boşluktur."""
		kopya = [
			ad
			for ad, karsilik in self.tohum.items()
			if any(d.strip() == ad.strip() for d in karsilik.values())
		]
		self.assertEqual(kopya[:10], [], f"{len(kopya)} kayıtta Türkçe ad kopyalanmış")


class CollationTuzagiTesti(unittest.TestCase):
	"""`c/ç` çifti aynı sayıldığında YANLIŞ çeviri yazılmamalı.

	MariaDB `utf8mb4_general_ci` altında "Sac Şekillendirme" (sheet metal) ile
	"Saç Şekillendirme" (hair styling) eşit sayılıyor; aday sorgusu ikisini de
	getiriyor. Karşılık SQL'den okunsaydı metal kategorisine "Hair Styling"
	yazılırdı — ekranda düzgün görünen, anlamı tamamen yanlış bir kayıt.
	"""

	def setUp(self) -> None:
		sys.modules.pop("frappe", None)
		sys.modules.pop("tradehub_core.catalog.category_i18n", None)
		paket = sys.modules.get("tradehub_core.catalog")
		if paket is not None and hasattr(paket, "category_i18n"):
			delattr(paket, "category_i18n")

		# Aday sorgusunu collation gibi davrandır: iki kaydı da döndür.
		self.db = SahteDb(
			{
				"CAT-HAIR": {"category_name": "Saç Şekillendirme"},
				"CAT-METAL": {"category_name": "Sac Şekillendirme"},
			}
		)
		_install_frappe_stub(self.db, collation_ci=True)
		from tradehub_core.catalog import category_i18n

		self.modul = category_i18n

	def test_yalnizca_birebir_eslesen_yazilir(self) -> None:
		tohum = {"Saç Şekillendirme": {"en": "Hair Styling"}}

		rapor = self.modul.apply_name_seed(tohum, langs=("en",))

		self.assertEqual(self.db.kayitlar["CAT-HAIR"]["category_name_en"], "Hair Styling")
		self.assertNotIn(
			"category_name_en",
			self.db.kayitlar["CAT-METAL"],
			"metal kategorisine saç çevirisi yazılmamalı",
		)
		self.assertEqual(rapor["reasons"].get("empty_value"), 1, "eşleşmeyen kayıt raporlanmalı")

	def test_iki_ad_da_tohumdaysa_dogru_karsiliklar_yazilir(self) -> None:
		tohum = {
			"Saç Şekillendirme": {"en": "Hair Styling"},
			"Sac Şekillendirme": {"en": "Sheet Metal Forming"},
		}

		self.modul.apply_name_seed(tohum, langs=("en",))

		self.assertEqual(self.db.kayitlar["CAT-HAIR"]["category_name_en"], "Hair Styling")
		self.assertEqual(self.db.kayitlar["CAT-METAL"]["category_name_en"], "Sheet Metal Forming")
