"""Öksüz dosya raporu (`api/seller_media.list_orphans`) — T-043'ün ikinci yarısı.

Bu uç bir GÖRÜNÜRLÜK raporu, silme akışı değil (rapor 57: kullanım koruması
GC yolunun yarısına bağlıydı, 3.821 dosya silinecekti). Testlerin ağırlığı
bu yüzden iki yanlış yönde:

  1. Kullanılan bir dosyanın "öksüz" görünmesi — satıcıyı kendi (ya da
     platformun) görselini bırakmaya iter. Kullanılan dosya, platform
     alanında kullanılan dosya ve çöpteki dosya testleri bunu ölçer.
  2. Başka mağazanın verisinin sızması — kiracı izolasyonu. Cross-tenant
     testi VACUITY kontrolüyle: B'nin öksüzü A'ya görünmüyor OLMASI yetmez,
     mağaza bağı gevşetilince GÖRÜNDÜĞÜ de kanıtlanır; aksi hâlde "görünmedi"
     dosyanın zaten listelenemez olmasından kaynaklanıyor olabilirdi.

Fixture'lar `SellerBrowseTestBase`'ten geliyor (iki bağımsız satıcı: kendi
kullanıcısı, ürünü, üründe duran dosyası). Dosya yaşları SQL ile geri
tarihlenir — uç "yüklenmesinin üzerinden N gün geçmiş" diye soruyor ve yeni
yüklenen dosyanın raporda ÇIKMAMASI kabul kriteri.

DEV sitesinde başka ajanlar boru hattı koşturabilir (`Media Rendition` /
`Media Version` oynar) — bu testler o tablolara hiç bakmaz; tüm kesin
sayımlar testin kendi kurduğu taze mağazaların dosyalarıyla sınırlı.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_orphans
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.utils import add_days, now_datetime

from tradehub_core.api import seller_media
from tradehub_core.media import ownership, usage
from tradehub_core.tests.test_seller_media_browse import SellerBrowseTestBase


class MediaOrphanTestBase(SellerBrowseTestBase):
	def _backdate(self, file_docname: str, days: int) -> None:
		"""Dosyanın yüklenme tarihini `days` gün geriye çek.

		`creation` standart kolon; `set_value` onu güncellemeyi reddediyor.
		Parametreli SQL — tarih kullanıcı girdisi değil, testin ürettiği değer.
		"""
		frappe.db.sql(
			"update tabFile set creation = %s where name = %s",
			(add_days(now_datetime(), -days), file_docname),
		)
		frappe.db.commit()

	def _make_orphan(self, satici: "frappe._dict", tag: str, days_old: int = 40) -> "frappe._dict":
		"""Satıcının sahibi olduğu, hiçbir kaynak alanda geçmeyen dosya."""
		doc = self._make_public_file(tag)
		frappe.db.set_value("File", doc.name, "owner", satici.email, update_modified=False)
		frappe.db.commit()
		if days_old:
			self._backdate(doc.name, days_old)
		return doc

	def _orphans(self, **kwargs) -> dict:
		return seller_media.list_orphans(**kwargs)

	def _urls(self, out: dict) -> set[str]:
		return {r["file_url"] for r in out["items"]}


class OrphanCorrectnessTests(MediaOrphanTestBase):
	def test_oksuz_dogru_bulunuyor_ve_satir_sozlesmesi_tam(self):
		"""Kullanılmayan + eşikten eski dosya listede; satır alanları tam."""
		orphan = self._make_orphan(self.a, "oksuz-bulgu", days_old=40)

		self._as_seller(self.a)
		out = self._orphans(days_unused=30)

		self.assertEqual(out["total"], 1)
		self.assertEqual(self._urls(out), {orphan.file_url})
		row = out["items"][0]
		# Sözleşme: {file_url, file_name, file_size, uploaded_at, last_checked}
		self.assertEqual(row["file_name"], orphan.file_name)
		self.assertIsInstance(row["file_size"], int)
		self.assertTrue(row["uploaded_at"])
		self.assertTrue(row["last_checked"])
		# Tarama sınırı makine okunur dönmek ZORUNDA — ekran notu buna dayanıyor.
		self.assertIn("scan", out)
		self.assertFalse(out["scan"]["history_scanned"])
		self.assertEqual(out["scan"]["failed_sources"], [])

	def test_kullanilan_dosya_listede_degil(self):
		"""Üründe duran dosya eşikten eski olsa bile öksüz DEĞİL.

		Yaş geri çekiliyor ki dışlanma sebebi yaş filtresi olmasın — aksi
		hâlde test boş yere yeşil kalırdı (vacuity).
		"""
		used_names = frappe.get_all("File", filters={"file_url": self.a.public_url}, pluck="name")
		for name in used_names:
			self._backdate(name, 40)
		orphan = self._make_orphan(self.a, "oksuz-kullanilan", days_old=40)

		self._as_seller(self.a)
		out = self._orphans(days_unused=30)

		self.assertNotIn(self.a.public_url, self._urls(out))
		self.assertEqual(self._urls(out), {orphan.file_url})

	def test_yeni_yuklenen_dosya_esik_dolmadan_gorunmez(self):
		"""Kabul kriteri: yeni yüklenen raporda çıkmaz; eşik 0 olunca çıkar."""
		taze = self._make_orphan(self.a, "oksuz-taze", days_old=0)

		self._as_seller(self.a)
		self.assertNotIn(taze.file_url, self._urls(self._orphans(days_unused=30)))
		self.assertIn(taze.file_url, self._urls(self._orphans(days_unused=0)))

	def test_copteki_dosya_listede_degil(self):
		"""Bırakılmış dosya öksüz raporuna girmez — o zaten ayrı akışta."""
		orphan = self._make_orphan(self.a, "oksuz-cop", days_old=40)
		for name in frappe.get_all("File", filters={"file_url": orphan.file_url}, pluck="name"):
			frappe.db.set_value(
				"File", name, "th_trashed_at", now_datetime(), update_modified=False
			)
		frappe.db.commit()

		self._as_seller(self.a)
		self.assertNotIn(orphan.file_url, self._urls(self._orphans(days_unused=30)))

	def test_platform_alaninda_kullanilan_dosya_oksuz_degil(self):
		"""Mağaza süzgeci OLMAYAN alanda (kategori görseli) geçen dosya öksüz
		sayılmaz — T-029 tuzağının rapor karşılığı: satıcı "öksüz" görüp
		bırakırsa ve tek sahip oysa, platformun görseli diskten giderdi."""
		doc = self._make_orphan(self.a, "oksuz-platform", days_old=40)
		frappe.db.set_value(
			"Product Category", self.a.category, "image", doc.file_url, update_modified=False
		)
		frappe.db.commit()

		self._as_seller(self.a)
		self.assertNotIn(doc.file_url, self._urls(self._orphans(days_unused=30)))

	def test_negatif_gun_esigi_reddedilir(self):
		self._as_seller(self.a)
		with self.assertRaises(frappe.ValidationError):
			self._orphans(days_unused=-1)


class OrphanIsolationTests(MediaOrphanTestBase):
	def test_baska_magazanin_oksuzu_gorunmez_ve_kontrol_gevseyince_gorunur(self):
		"""Cross-tenant + VACUITY.

		1. B'nin öksüzü, A'nın raporunda YOK.
		2. Aynı çağrıda mağaza bağı (oturumdan çözülen `_store`) B'ye
		   çevrilince dosya GÖRÜNÜYOR — yani 1'deki yokluk gerçekten mağaza
		   bağından geliyor, dosyanın listelenemez olmasından değil.
		"""
		b_orphan = self._make_orphan(self.b, "oksuz-izo-b", days_old=40)

		self._as_seller(self.a)
		out_a = self._orphans(days_unused=30)
		self.assertNotIn(b_orphan.file_url, self._urls(out_a))

		# Vacuity: tek koruma katmanı olan mağaza çözümü gevşetiliyor.
		with mock.patch.object(seller_media, "_store", return_value=self.b.store):
			out_gevsek = self._orphans(days_unused=30)
		self.assertIn(b_orphan.file_url, self._urls(out_gevsek))

	def test_toplam_sayi_baska_magazanin_dosyasini_saymaz(self):
		"""Sayı da sızıntıdır: A'nın toplamı B'nin öksüzleriyle şişmemeli."""
		a_orphan = self._make_orphan(self.a, "oksuz-sayi-a", days_old=40)
		self._make_orphan(self.b, "oksuz-sayi-b1", days_old=40)
		self._make_orphan(self.b, "oksuz-sayi-b2", days_old=40)

		self._as_seller(self.a)
		out = self._orphans(days_unused=30)
		self.assertEqual(out["total"], 1)
		self.assertEqual(self._urls(out), {a_orphan.file_url})


class OrphanPaginationTests(MediaOrphanTestBase):
	def test_sayfalama_toplami_korur_ve_sayfalar_ayrisik(self):
		d1 = self._make_orphan(self.a, "oksuz-syf-1", days_old=50)
		d2 = self._make_orphan(self.a, "oksuz-syf-2", days_old=40)
		d3 = self._make_orphan(self.a, "oksuz-syf-3", days_old=35)

		self._as_seller(self.a)
		sayfalar = [self._orphans(days_unused=30, start=i, page_length=1) for i in (0, 1, 2)]

		for s in sayfalar:
			self.assertEqual(s["total"], 3)
			self.assertEqual(len(s["items"]), 1)
		gorulen = [s["items"][0]["file_url"] for s in sayfalar]
		self.assertEqual(len(set(gorulen)), 3, "sayfalar ayrışık değil — aynı satır iki sayfada")
		self.assertEqual(set(gorulen), {d1.file_url, d2.file_url, d3.file_url})
		# Deterministik sıra: en eski en üstte — sayfalar arası çakışmanın önkoşulu.
		self.assertEqual(gorulen, [d1.file_url, d2.file_url, d3.file_url])

	def test_kume_disindaki_sayfa_bos_ama_toplam_dogru(self):
		self._make_orphan(self.a, "oksuz-syf-tas", days_old=40)

		self._as_seller(self.a)
		out = self._orphans(days_unused=30, start=10, page_length=50)
		self.assertEqual(out["items"], [])
		self.assertEqual(out["total"], 1)


class OrphanReferenceScanTests(MediaOrphanTestBase):
	def test_referans_kumesi_magaza_suzgecli_ve_global_katmanlari_birlestirir(self):
		"""`store_referenced_urls` iki katmanı da görüyor mu:
		mağaza süzgeçli alan (Listing.primary_image) + süzgeçsiz platform
		alanı (Product Category.image)."""
		platform = self._make_orphan(self.a, "ref-platform", days_old=40)
		frappe.db.set_value(
			"Product Category", self.a.category, "image", platform.file_url, update_modified=False
		)
		frappe.db.commit()
		ownership.clear_url_cache(self.a.store)

		referenced, failed = usage.store_referenced_urls(self.a.store)
		self.assertIn(self.a.public_url, referenced)  # süzgeçli katman
		self.assertIn(platform.file_url, referenced)  # global katman
		self.assertEqual(failed, [])
