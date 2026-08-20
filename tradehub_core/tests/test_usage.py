"""T-043 — `tradehub_core/media/pipeline/core/usage.py` testleri.

Dört grup:

  1. Bağ kaydı        — açma/kapama idempotent mi, eşitleme doğru mu
  2. Erişim damgası   — zaman kovası aralıkta en fazla/en az bir yazma veriyor mu
  3. Disk öksüzü      — sistem yolları muaf mı, genç dosyalar korunuyor mu
  4. Kayıt öksüzü     — legal_hold / genç / süreçteki varlıklar raporda ÇIKMIYOR mu

Frappe gerektiren fonksiyonlar (`find_disk_orphans`, `dangling_references`,
`url_verdicts`, `reconcile`) burada test EDİLMEZ — saf mantık (`classify_orphans`,
`find_orphan_assets`, `scan_disk`) ayrı fonksiyonlara çıkarıldığı için hepsi
frappe'siz test edilebiliyor. `scan_disk` gerçek geçici dizinle koşuyor.

Çalıştırma:

    python3 -m unittest discover -s /Users/ahmet/Desktop/istoc/tradehub_core/tests -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.core import usage  # noqa: E402
from tradehub_core.media.pipeline.core.usage import (  # noqa: E402
	AccessBuffer,
	AssetSnapshot,
	DiskFile,
	UsageError,
	UsageLink,
	UsageStore,
	classify_orphans,
	find_orphan_assets,
	is_system_path,
	scan_disk,
	should_record_access,
	sync_links,
	usage_key,
)

GUN = usage.SECONDS_PER_DAY
SIMDI = 1_800_000_000.0  # sabit "şimdi" — testler saate bağlı olmasın


class AnahtarTesti(unittest.TestCase):
	def test_dortlu_birlesir(self):
		self.assertEqual(
			usage_key("MA-1", "Listing", "L-9", "primary_image"),
			"MA-1|Listing|L-9|primary_image",
		)

	def test_bos_parca_reddedilir(self):
		for eksik in (("", "a", "b", "c"), ("a", "", "b", "c"), ("a", "b", "c", "")):
			with self.subTest(eksik=eksik):
				with self.assertRaises(UsageError):
					usage_key(*eksik)

	def test_ayrac_veride_reddedilir(self):
		"""'|' veriye girerse anahtar belirsizleşir — sessizce kabul edilmemeli."""
		with self.assertRaises(UsageError):
			usage_key("MA-1", "Listing", "L|9", "image")

	def test_bosluk_kirpilir(self):
		self.assertEqual(usage_key(" MA-1 ", "Listing", "L-9", "image"),
						 "MA-1|Listing|L-9|image")


class BagKaydiTesti(unittest.TestCase):
	def _link(self, alan="primary_image", kayit="L-9"):
		return UsageLink(asset="MA-1", ref_doctype="Listing", ref_name=kayit, ref_field=alan)

	def test_acma_idempotent(self):
		depo = UsageStore()
		depo.open_link(self._link(), SIMDI)
		depo.open_link(self._link(), SIMDI + 60)
		self.assertEqual(len(depo.all_links()), 1)

	def test_ilk_gorulme_korunur(self):
		depo = UsageStore()
		depo.open_link(self._link(), SIMDI)
		depo.open_link(self._link(), SIMDI + 3600)
		row = depo.all_links()[0]
		self.assertEqual(row.first_seen, SIMDI)
		self.assertEqual(row.last_seen, SIMDI + 3600)

	def test_kapatma_silmez(self):
		"""Bağ kapatılınca kayıt DURUR — 'hiç kullanılmadı' ile karışmasın."""
		depo = UsageStore()
		depo.open_link(self._link(), SIMDI)
		depo.close_link("MA-1", "Listing", "L-9", "primary_image", SIMDI + 100)
		self.assertEqual(len(depo.all_links()), 1)
		self.assertFalse(depo.all_links()[0].is_open)
		self.assertEqual(depo.open_assets(), set())

	def test_yeniden_baglanma_ilk_gorulmeyi_silmez(self):
		depo = UsageStore()
		depo.open_link(self._link(), SIMDI)
		depo.close_link("MA-1", "Listing", "L-9", "primary_image", SIMDI + 100)
		depo.open_link(self._link(), SIMDI + 200)
		row = depo.all_links()[0]
		self.assertTrue(row.is_open)
		self.assertEqual(row.first_seen, SIMDI)

	def test_olmayan_bagi_kapatmak_hata_degil(self):
		self.assertIsNone(UsageStore().close_link("MA-9", "Listing", "L-1", "x", SIMDI))

	def test_eslestirme_fazlalari_kapatir(self):
		"""Üründen görsel çıkarıldığında ayrı bir 'kaldırıldı' olayı gerekmez."""
		depo = UsageStore()
		sync_links(depo, "MA-1", [
			{"ref_doctype": "Listing", "ref_name": "L-1", "ref_field": "primary_image"},
			{"ref_doctype": "Listing", "ref_name": "L-1", "ref_field": "gallery"},
		], SIMDI)
		self.assertEqual(len(depo.links_of("MA-1", open_only=True)), 2)

		sonuc = sync_links(depo, "MA-1", [
			{"ref_doctype": "Listing", "ref_name": "L-1", "ref_field": "primary_image"},
		], SIMDI + 60)
		self.assertEqual(len(sonuc["closed"]), 1)
		self.assertEqual(len(depo.links_of("MA-1", open_only=True)), 1)
		self.assertEqual(len(depo.all_links()), 2)  # kapanan kayıt duruyor

	def test_bos_listeyle_eslestirme_hepsini_kapatir(self):
		depo = UsageStore()
		sync_links(depo, "MA-1", [{"ref_doctype": "Listing", "ref_name": "L-1",
								   "ref_field": "primary_image"}], SIMDI)
		sync_links(depo, "MA-1", [], SIMDI + 10)
		self.assertEqual(depo.open_assets(), set())

	def test_profil_bilgisi_guncellenir(self):
		depo = UsageStore()
		depo.open_link(self._link(), SIMDI)
		depo.open_link(UsageLink("MA-1", "Listing", "L-9", "primary_image",
								 profile_used="product-main"), SIMDI + 5)
		self.assertEqual(depo.all_links()[0].profile_used, "product-main")


class ErisimDamgasiTesti(unittest.TestCase):
	def setUp(self):
		usage.reset_access_state()

	def test_ayni_kovada_bir_kez_yazilir(self):
		self.assertTrue(should_record_access("r1", SIMDI, 3600))
		self.assertFalse(should_record_access("r1", SIMDI + 1, 3600))
		self.assertFalse(should_record_access("r1", SIMDI + 60, 3600))

	def test_kova_degisince_yeniden_yazilir(self):
		self.assertTrue(should_record_access("r1", SIMDI, 3600))
		self.assertTrue(should_record_access("r1", SIMDI + 3601, 3600))

	def test_farkli_anahtarlar_bagimsiz(self):
		self.assertTrue(should_record_access("r1", SIMDI, 3600))
		self.assertTrue(should_record_access("r2", SIMDI, 3600))

	def test_nadir_erisilen_de_damgasini_alir(self):
		"""Örneklemenin aksine: tek erişimli bir rendition da yazılır.

		%1 örneklemede bu çağrının yazma olasılığı %1'di; nadir kullanılan
		türev damgasız kalıp retention taramasında 'erişilmiyor' sayılırdı.
		"""
		self.assertTrue(should_record_access("nadir-rendition", SIMDI, 3600))

	def test_yazmalar_saate_yayilir(self):
		"""Kova SINIRI anahtara göre kayar — yazmalar saat başında yığılmaz.

		Ölçülen şey kovanın numarası değil, kovanın NE ZAMAN döndüğü: her
		anahtar için bir sonraki yazma anı farklı olmalı, yoksa tüm damgalar
		aynı saniyede yazılır.
		"""
		def sonraki_yazma_ani(anahtar, aralik=3600):
			off = usage._bucket_offset(anahtar, aralik)
			kova = int((SIMDI + off) // aralik)
			return (kova + 1) * aralik - off

		anlar = {sonraki_yazma_ani(f"r{i}") for i in range(200)}
		# 200 anahtar, 3600 saniyelik pencere: çakışma olsa bile en az yüzlerce
		# farklı an beklenir. Tek bir an çıkması kaydırmanın çalışmadığı demektir.
		self.assertGreater(len(anlar), 100, f"yazma anları yayılmıyor: {len(anlar)} farklı an")
		self.assertLessEqual(max(anlar) - min(anlar), 3600)

	def test_aralik_sifirsa_hep_yazilir(self):
		self.assertTrue(should_record_access("r1", SIMDI, 0))
		self.assertTrue(should_record_access("r1", SIMDI, 0))


class TamponTesti(unittest.TestCase):
	def setUp(self):
		usage.reset_access_state()

	def test_tampon_biriktirir_ve_bosaltir(self):
		tampon = AccessBuffer(min_interval=3600, max_size=3)
		self.assertTrue(tampon.touch("a", SIMDI))
		self.assertTrue(tampon.touch("b", SIMDI))
		self.assertFalse(tampon.touch("a", SIMDI + 1))  # aynı kova
		self.assertEqual(len(tampon.pending()), 2)

		yazilan = {}
		n = tampon.flush(yazilan.update)
		self.assertEqual(n, 2)
		self.assertEqual(set(yazilan), {"a", "b"})
		self.assertEqual(tampon.pending(), {})

	def test_bos_tamponda_flush_sifir(self):
		self.assertEqual(AccessBuffer().flush(lambda _b: None), 0)

	def test_yazma_basarisizsa_tampon_korunur(self):
		"""Damgalar kaybolmasın: writer patlarsa tampon boşaltılmaz."""
		tampon = AccessBuffer()
		tampon.touch("a", SIMDI)

		def patla(_batch):
			raise RuntimeError("db down")

		with self.assertRaises(RuntimeError):
			tampon.flush(patla)
		self.assertEqual(set(tampon.pending()), {"a"})

	def test_dolu_bayragi(self):
		tampon = AccessBuffer(max_size=2)
		tampon.touch("a", SIMDI)
		self.assertFalse(tampon.is_full())
		tampon.touch("b", SIMDI)
		self.assertTrue(tampon.is_full())


class SistemYoluTesti(unittest.TestCase):
	def test_olculen_sistem_yollari(self):
		"""ÖLÇÜLDÜ: 1.334 ham disk öksüzünün 1.047'si og_cache, 11'i sitemaps."""
		self.assertTrue(is_system_path("/files/og_cache/abc.jpg"))
		self.assertTrue(is_system_path("/files/sitemaps/sitemap-categories.xml"))
		self.assertTrue(is_system_path("/private/files/media_trash/ab/x.jpg"))
		self.assertTrue(is_system_path("/files/media/MA-1/" + "a" * 64 + "/p-800.webp"))

	def test_kullanici_medyasi_sistem_degil(self):
		self.assertFalse(is_system_path("/files/ab/abcdef.jpg"))
		self.assertFalse(is_system_path("/private/files/50/xyz.jpg"))

	def test_sorgu_dizesi_yok_sayilir(self):
		self.assertTrue(is_system_path("/files/og_cache/abc.jpg?v=2"))


class DiskOksuzuTesti(unittest.TestCase):
	def _dosya(self, url, yas_gun=90, bayt=1000):
		return DiskFile(url=url, bytes=bayt, mtime=SIMDI - yas_gun * GUN)

	def test_kayitli_dosya_oksuz_degil(self):
		rapor = classify_orphans(
			[self._dosya("/files/ab/kayitli.jpg")],
			{"/files/ab/kayitli.jpg"}, now=SIMDI,
		)
		self.assertEqual(len(rapor.orphans), 0)
		self.assertEqual(rapor.scanned, 1)

	def test_kayitsiz_ve_eski_dosya_oksuz(self):
		rapor = classify_orphans([self._dosya("/files/ab/yetim.jpg", bayt=4096)],
								 set(), now=SIMDI)
		self.assertEqual(len(rapor.orphans), 1)
		self.assertEqual(rapor.orphan_bytes, 4096)

	def test_sistem_dosyasi_oksuz_sayilmaz(self):
		"""og_cache'in tabFile kaydı OLMAMASI doğrudur; silinirse önbellek gider."""
		rapor = classify_orphans([
			self._dosya("/files/og_cache/a.jpg"),
			self._dosya("/files/sitemaps/s.xml"),
			self._dosya("/files/ab/gercek-yetim.jpg"),
		], set(), now=SIMDI)
		self.assertEqual(len(rapor.orphans), 1)
		self.assertEqual(rapor.orphans[0].url, "/files/ab/gercek-yetim.jpg")
		self.assertEqual(len(rapor.system_skipped), 2)

	def test_genc_dosya_korunur(self):
		"""Yeni yüklenmiş ama henüz bağlanmamış dosya öksüz DEĞİLDİR."""
		rapor = classify_orphans([self._dosya("/files/ab/yeni.jpg", yas_gun=1)],
								 set(), now=SIMDI, min_age_days=30)
		self.assertEqual(len(rapor.orphans), 0)
		self.assertEqual(len(rapor.too_young), 1)

	def test_esik_gunu_sinirda(self):
		tam = classify_orphans([self._dosya("/files/ab/x.jpg", yas_gun=30)],
							   set(), now=SIMDI, min_age_days=30)
		self.assertEqual(len(tam.orphans), 1)

	def test_denetim_kipinde_sistem_de_sayilir(self):
		"""prefixes=() → ham sayı yeniden üretilir (1.334 ölçümünün karşılığı)."""
		rapor = classify_orphans([
			self._dosya("/files/og_cache/a.jpg"),
			self._dosya("/files/ab/gercek.jpg"),
		], set(), now=SIMDI, prefixes=())
		self.assertEqual(len(rapor.orphans), 2)

	def test_en_buyukler_siralanir(self):
		rapor = classify_orphans([
			self._dosya("/files/ab/kucuk.jpg", bayt=10),
			self._dosya("/files/ab/buyuk.jpg", bayt=9_948_888),
		], set(), now=SIMDI)
		self.assertEqual(rapor.top(1)[0]["url"], "/files/ab/buyuk.jpg")

	def test_ozet(self):
		rapor = classify_orphans([
			self._dosya("/files/ab/a.jpg", bayt=100),
			self._dosya("/files/og_cache/b.jpg", bayt=200),
			self._dosya("/files/ab/c.jpg", yas_gun=1),
		], set(), now=SIMDI)
		ozet = rapor.summary()
		self.assertEqual(ozet["scanned"], 3)
		self.assertEqual(ozet["orphans"], 1)
		self.assertEqual(ozet["orphan_bytes"], 100)
		self.assertEqual(ozet["system_skipped"], 1)
		self.assertEqual(ozet["too_young"], 1)


class DiskTaramaTesti(unittest.TestCase):
	"""`scan_disk` gerçek dosya sistemiyle — sahte değil."""

	def test_gercek_dizini_tarar(self):
		with tempfile.TemporaryDirectory() as kok:
			os.makedirs(os.path.join(kok, "ab"))
			with open(os.path.join(kok, "ab", "x.jpg"), "wb") as fh:
				fh.write(b"0123456789")
			with open(os.path.join(kok, "kok.txt"), "wb") as fh:
				fh.write(b"abc")

			bulunan = {f.url: f for f in scan_disk({"/files/": kok})}
			self.assertEqual(set(bulunan), {"/files/ab/x.jpg", "/files/kok.txt"})
			self.assertEqual(bulunan["/files/ab/x.jpg"].bytes, 10)

	def test_olmayan_kok_hata_vermez(self):
		self.assertEqual(scan_disk({"/files/": "/olmayan/dizin/xyz"}), [])

	def test_iki_kok_birlestirilir(self):
		with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
			open(os.path.join(a, "1.jpg"), "wb").close()
			open(os.path.join(b, "2.jpg"), "wb").close()
			urls = {f.url for f in scan_disk({"/files/": a, "/private/files/": b})}
			self.assertEqual(urls, {"/files/1.jpg", "/private/files/2.jpg"})


class KayitOksuzuTesti(unittest.TestCase):
	def _varlik(self, ad, yas_gun=90, **kw):
		return AssetSnapshot(name=ad, created_at=SIMDI - yas_gun * GUN, **kw)

	def test_bagi_olmayan_eski_varlik_oksuz(self):
		sonuc = find_orphan_assets([self._varlik("MA-1")], UsageStore(), now=SIMDI)
		self.assertEqual([r["asset"] for r in sonuc["orphans"]], ["MA-1"])
		self.assertFalse(sonuc["auto_delete"])

	def test_acik_bagi_olan_oksuz_degil(self):
		depo = UsageStore()
		depo.open_link(UsageLink("MA-1", "Listing", "L-1", "primary_image"), SIMDI)
		sonuc = find_orphan_assets([self._varlik("MA-1")], depo, now=SIMDI)
		self.assertEqual(sonuc["orphans"], [])

	def test_legal_hold_raporda_cikmaz(self):
		sonuc = find_orphan_assets([self._varlik("MA-1", legal_hold=True)],
								   UsageStore(), now=SIMDI)
		self.assertEqual(sonuc["orphans"], [])
		self.assertEqual(sonuc["exempt"][0]["reason"], "legal_hold")

	def test_yeni_varlik_raporda_cikmaz(self):
		sonuc = find_orphan_assets([self._varlik("MA-1", yas_gun=2)],
								   UsageStore(), now=SIMDI, min_age_days=30)
		self.assertEqual(sonuc["orphans"], [])
		self.assertEqual(sonuc["exempt"][0]["reason"], "too_young")

	def test_surecteki_durumlar_muaf(self):
		for durum in ("draft", "pending", "validating", "processing", "archived"):
			with self.subTest(durum=durum):
				sonuc = find_orphan_assets([self._varlik("MA-1", state=durum)],
										   UsageStore(), now=SIMDI)
				self.assertEqual(sonuc["orphans"], [])

	def test_bagi_kaldirilmis_varlik_isaretlenir(self):
		"""'Hiç kullanılmadı' ile 'kullanılıyordu, kaldırıldı' ayrı raporlanır."""
		depo = UsageStore()
		depo.open_link(UsageLink("MA-1", "Listing", "L-1", "primary_image"), SIMDI - 10 * GUN)
		depo.close_link("MA-1", "Listing", "L-1", "primary_image", SIMDI - 5 * GUN)
		sonuc = find_orphan_assets([self._varlik("MA-1")], depo, now=SIMDI)
		self.assertEqual(len(sonuc["orphans"]), 1)
		self.assertTrue(sonuc["orphans"][0]["ever_used"])
		self.assertEqual(sonuc["orphans"][0]["last_seen"], SIMDI - 5 * GUN)

	def test_hic_kullanilmamis_isaretlenir(self):
		sonuc = find_orphan_assets([self._varlik("MA-1")], UsageStore(), now=SIMDI)
		self.assertFalse(sonuc["orphans"][0]["ever_used"])
		self.assertIsNone(sonuc["orphans"][0]["last_seen"])

	def test_en_eskiden_siralanir(self):
		sonuc = find_orphan_assets(
			[self._varlik("MA-genc", yas_gun=40), self._varlik("MA-eski", yas_gun=400)],
			UsageStore(), now=SIMDI,
		)
		self.assertEqual([r["asset"] for r in sonuc["orphans"]], ["MA-eski", "MA-genc"])

	def test_otomatik_silme_yok(self):
		"""T-043: rapor SİLMEZ. Bayrak sözleşmenin parçası."""
		sonuc = find_orphan_assets([self._varlik("MA-1")], UsageStore(), now=SIMDI)
		self.assertIs(sonuc["auto_delete"], False)


if __name__ == "__main__":
	unittest.main(verbosity=2)
