"""T-043 kriter 1 — kullanım bağının KALICI kaydı.

Kaynak metin: "DocType alanına bağlanınca/kopunca **Media Usage kaydı**
güncellenir". `UsageStore` bunu sağlamıyordu: sözleşme doğruydu ama depo
bellek içiydi ve süreç yeniden başlayınca bağ tablosu sıfırlanıyordu. Öksüz
kararının tamamı ("hiç bağlanmamış mı, bağı kaldırılmış mı") bu tabloya
dayandığı için, süreç ömrü kadar yaşayan bir tablo kriteri karşılamıyor.

Bu modül `PersistentUsageStore`'un davranışını bellek içi depoyla **aynı
senaryolardan** geçirir; ikisi ayrışırsa DocType kurulduğu gün üretimde
farklı davranırdı.

Frappe gerekmez: kalıcı deponun mantığı `UsageBackend` arayüzünün arkasında
ve testte sözlük tabanlı bir backend kullanılıyor. `FrappeUsageBackend`'in
SQL'i burada ÖLÇÜLMEZ — `Media Usage` DocType'ı bugün kurulu değil
(`usage_doctype_installed()` → False, ölçüldü 2026-08-19). Bu ayrım rapora
da böyle yazıldı.

Çalıştırma (frappe'siz):

    cd /Users/ahmet/Desktop/istoc/tradehub_core
    python3 -m unittest tradehub_core.tests.test_media_usage_store -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.core.usage import (  # noqa: E402
	AssetSnapshot,
	PersistentUsageStore,
	UsageBackend,
	UsageError,
	UsageLink,
	UsageStore,
	find_orphan_assets,
	sync_links,
	usage_store_status,
)

GUN = 86400.0


class SozlukBackend(UsageBackend):
	"""Bellekte duran ama `PersistentUsageStore`'un DIŞINDA yaşayan depo.

	Kritik nokta: iki ayrı `PersistentUsageStore` örneği aynı `SozlukBackend`'i
	paylaşabilir. "Süreç yeniden başladı" senaryosu tam olarak budur — depo
	nesnesi gider, tablo kalır.

	`usage_key` üzerinde UNIQUE kısıtın karşılığı: sözlük anahtarı. İkinci
	yazma yeni satır AÇMAZ, mevcudu günceller (`on duplicate key update`).
	"""

	def __init__(self) -> None:
		self.rows: dict[str, dict] = {}
		self.write_count = 0

	def fetch(self, key: str) -> dict | None:
		satir = self.rows.get(key)
		return dict(satir) if satir else None

	def upsert(self, row: dict) -> None:
		self.write_count += 1
		self.rows[row["usage_key"]] = dict(row)

	def rows_for(self, asset: str) -> list[dict]:
		return [dict(r) for r in self.rows.values() if r.get("asset") == asset]

	def open_asset_names(self) -> set:
		return {r["asset"] for r in self.rows.values() if r.get("is_open")}


def _link(asset: str = "A1", field: str = "primary_image", ref: str = "L1") -> UsageLink:
	return UsageLink(asset=asset, ref_doctype="Listing", ref_name=ref, ref_field=field)


class DepoDavranisiOrtak:
	"""İki depo gerçeklemesinin de geçmesi gereken senaryolar."""

	def depo(self) -> UsageStore:
		raise NotImplementedError

	def test_bag_acilinca_kayit_olusuyor(self) -> None:
		d = self.depo()
		bag = d.open_link(_link(), now=100.0)
		self.assertTrue(bag.is_open)
		self.assertEqual(bag.first_seen, 100.0)
		self.assertEqual(bag.last_seen, 100.0)
		self.assertEqual(len(d.links_of("A1")), 1)

	def test_ayni_bag_ikinci_kez_yeni_satir_acmiyor(self) -> None:
		d = self.depo()
		d.open_link(_link(), now=100.0)
		ikinci = d.open_link(_link(), now=500.0)
		self.assertEqual(len(d.links_of("A1")), 1, "idempotent değil — ikinci satır açıldı")
		self.assertEqual(ikinci.first_seen, 100.0)
		self.assertEqual(ikinci.last_seen, 500.0)

	def test_kapatma_kaydi_silmiyor(self) -> None:
		d = self.depo()
		d.open_link(_link(), now=100.0)
		kapali = d.close_link("A1", "Listing", "L1", "primary_image", now=200.0)
		self.assertIsNotNone(kapali)
		self.assertFalse(kapali.is_open)
		self.assertEqual(len(d.links_of("A1")), 1, "kapatma kaydı sildi")
		self.assertEqual(d.links_of("A1", open_only=True), [])

	def test_kapali_bag_yeniden_acilinca_first_seen_korunuyor(self) -> None:
		d = self.depo()
		d.open_link(_link(), now=100.0)
		d.close_link("A1", "Listing", "L1", "primary_image", now=200.0)
		yeniden = d.open_link(_link(), now=900.0)
		self.assertTrue(yeniden.is_open)
		self.assertEqual(yeniden.first_seen, 100.0,
			"yeniden bağlanma ilk bağlanma anını sildi")
		self.assertEqual(yeniden.last_seen, 900.0)

	def test_olmayan_bagi_kapatmak_none_donuyor(self) -> None:
		self.assertIsNone(self.depo().close_link("A1", "Listing", "L1", "x", now=1.0))

	def test_acik_varliklar_yalniz_acik_baglari_sayiyor(self) -> None:
		d = self.depo()
		d.open_link(_link(asset="A1"), now=1.0)
		d.open_link(_link(asset="A2", ref="L2"), now=1.0)
		self.assertEqual(d.open_assets(), {"A1", "A2"})
		d.close_link("A2", "Listing", "L2", "primary_image", now=2.0)
		self.assertEqual(d.open_assets(), {"A1"})

	def test_sync_links_listede_olmayani_kapatiyor(self) -> None:
		d = self.depo()
		sync_links(d, "A1", [
			{"ref_doctype": "Listing", "ref_name": "L1", "ref_field": "primary_image"},
			{"ref_doctype": "Listing", "ref_name": "L1", "ref_field": "video_url"},
		], now=100.0)
		self.assertEqual(len(d.links_of("A1", open_only=True)), 2)

		sonuc = sync_links(d, "A1", [
			{"ref_doctype": "Listing", "ref_name": "L1", "ref_field": "primary_image"},
		], now=200.0)
		self.assertEqual(len(sonuc["closed"]), 1)
		self.assertEqual(len(d.links_of("A1", open_only=True)), 1)
		self.assertEqual(len(d.links_of("A1")), 2, "kapatılan bağ silinmiş")

	def test_oksuz_karari_kapali_bagi_gorebiliyor(self) -> None:
		""""Hiç kullanılmadı" ile "kullanılıyordu, kaldırıldı" ayrımı."""
		d = self.depo()
		d.open_link(_link(asset="A1"), now=0.0)
		d.close_link("A1", "Listing", "L1", "primary_image", now=10.0)
		rapor = find_orphan_assets(
			[AssetSnapshot(name="A1", created_at=0.0), AssetSnapshot(name="A2", created_at=0.0)],
			d, now=100 * GUN, min_age_days=30,
		)
		kayit = {r["asset"]: r for r in rapor["orphans"]}
		self.assertTrue(kayit["A1"]["ever_used"], "kapalı bağ görülmedi")
		self.assertFalse(kayit["A2"]["ever_used"])
		self.assertFalse(rapor["auto_delete"], "öksüz raporu otomatik silme açmış")


class TestBellekIciDepo(DepoDavranisiOrtak, unittest.TestCase):
	def depo(self) -> UsageStore:
		return UsageStore()

	def test_kalici_degil(self) -> None:
		self.assertFalse(UsageStore().is_persistent)


class TestKaliciDepo(DepoDavranisiOrtak, unittest.TestCase):
	def setUp(self) -> None:
		self.backend = SozlukBackend()

	def depo(self) -> UsageStore:
		return PersistentUsageStore(self.backend)

	def test_kalici(self) -> None:
		self.assertTrue(self.depo().is_persistent)

	def test_surec_yeniden_baslayinca_baglar_duruyor(self) -> None:
		"""T-043 kriter 1'in tam karşılığı — bellek içi depoda GEÇMEYEN test."""
		once = PersistentUsageStore(self.backend)
		once.open_link(_link(), now=100.0)

		sonra = PersistentUsageStore(self.backend)  # yeni süreç, aynı tablo
		baglar = sonra.links_of("A1")
		self.assertEqual(len(baglar), 1, "bağ süreç sınırını geçemedi")
		self.assertEqual(baglar[0].first_seen, 100.0)
		self.assertEqual(sonra.open_assets(), {"A1"})

	def test_bellek_ici_depo_ayni_senaryoda_bagi_kaybediyor(self) -> None:
		"""Karşı yön: kalıcılığın gerçekten yeni bir şey olduğunun kanıtı."""
		UsageStore().open_link(_link(), now=100.0)
		self.assertEqual(UsageStore().links_of("A1"), [],
			"bellek içi depo beklenmedik biçimde paylaşımlı")

	def test_ikinci_yazma_satir_sayisini_artirmiyor(self) -> None:
		d = self.depo()
		d.open_link(_link(), now=100.0)
		d.open_link(_link(), now=200.0)
		self.assertEqual(len(self.backend.rows), 1)
		self.assertEqual(self.backend.write_count, 2, "ikinci bildirim hiç yazmadı")

	def test_all_links_kalici_depoda_reddediliyor(self) -> None:
		"""Tüm tabloyu belleğe çekmek kalıcı depoda bir hata; sessizce yapılmaz."""
		with self.assertRaises(UsageError):
			self.depo().all_links()

	def test_anahtar_dortlusu_eksikse_yazma_olmuyor(self) -> None:
		with self.assertRaises(UsageError):
			self.depo().open_link(
				UsageLink(asset="A1", ref_doctype="Listing", ref_name="", ref_field="x"),
				now=1.0,
			)
		self.assertEqual(self.backend.rows, {})


class TestDepoSecimi(unittest.TestCase):
	def test_durum_raporu_alanlari(self) -> None:
		"""`usage_store_status()` frappe yokken de cevap vermeli (kurulu değil)."""
		durum = usage_store_status()
		self.assertEqual(durum["doctype"], "Media Usage")
		self.assertIn("installed", durum)
		self.assertIn("persistent", durum)
		self.assertEqual(durum["installed"], durum["persistent"])
		if not durum["installed"]:
			self.assertTrue(durum["reason"], "kurulu değilse gerekçe yazılmalı")


if __name__ == "__main__":  # pragma: no cover
	unittest.main(verbosity=2)
