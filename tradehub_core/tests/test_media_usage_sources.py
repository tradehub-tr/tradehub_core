"""T-043 — `usage.py` kaynak listelerinin CANLI ŞEMAYLA uyumu.

`tests/test_usage.py` saf mantığı (öksüz kararı, zaman kovası) frappe'siz
ölçüyor. Bu modül farklı bir soruyu sorar ve **site gerektirir**: listedeki
her (tablo, kolon) gerçekten var mı, `resolve()` her kaynaktan doğru kolonu
seçebiliyor mu, ve bugün '/files/' taşıyan hangi alanlar hâlâ hiçbir listede
değil.

Neden ayrı bir test: `_match_rows` sorgu hatasını YUTUYOR (`except` +
`log_error`). Yani listeye yanlış yazılmış bir kolon adı ya da ana tablodan
`parent` seçmeye çalışan bir `resolve()` çağrısı, hata vermek yerine sessizce
"bu dosya hiçbir yerde kullanılmıyor" der. Yanlış yön silme yönüdür. Sessiz
başarısızlığı ancak şemaya karşı ölçen bir test yakalar.

Çalıştırma:

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_usage_sources
"""

from __future__ import annotations

import unittest

import frappe

from tradehub_core.media import usage

#: Bilerek hiçbir listeye alınmayan alanlar ve sebepleri. Kör nokta taraması
#: bunları "eksik" saymaz — ama listede olmayan YENİ bir alan çıkarsa uyarır.
#:
#: KVKK belgeleri: `presets.EXCLUDED_DOCTYPES` bu doctype'lara bağlı ekleri
#: aday kümesinden zaten çıkarıyor; kaynak listesine eklemek kimlik belgesinin
#: varlığını medya panelinin kullanım dökümünde sızdırırdı
#: (bkz. docs/reports/24-kyc-izolasyon.md).
BILINCLI_DISARIDA: dict[tuple[str, str], str] = {
	("tabKYB Verification", "bank_account_document"): "KVKK",
	("tabKYB Verification", "faaliyet_belgesi"): "KVKK",
	("tabKYB Verification", "identity_document"): "KVKK",
	("tabKYB Verification", "imza_sirkuleri"): "KVKK",
	("tabKYB Verification", "ticaret_sicil_gazetesi"): "KVKK",
	("tabKYB Verification", "vergi_levhasi"): "KVKK",
	("tabKYC Verification", "identity_document"): "KVKK",
	("tabSeller Application", "identity_document"): "KVKK",
	("tabSeller Certification", "document"): "KVKK",
	("tabSeller Verification", "document"): "KVKK",
	("tabFile", "file_url"): "envanterin kendisi",
	# Türev adresi bir KULLANIM değil, boru hattının kendi ürünüdür: satıcının
	# içeriği bir alanda "geçtiği" için değil, motorun onu ürettiği için
	# oradadır. Kaynak sayılsaydı her türevli dosya sonsuza dek "kullanımda"
	# görünür, öksüz raporu hiç öksüz bulamazdı. Türevlerin yaşam döngüsü
	# varlığa (Media Asset) bağlıdır ve GC oradan yönetilir. (İlk gerçek
	# üretim 2026-08-20 W3-B koşusunda 88 satır yazınca bu alan taramada
	# ortaya çıktı — docs/reports/69 §bulgular.)
	("tabMedia Rendition", "file_url"): "boru hattı ürünü, kullanım değil",
	("tabDocField", "description"): "Frappe meta verisi",
	("tabAuthorization Decision Log", "context"): "denetim kaydı",
	("tabAuthorization Decision Log", "object_name"): "denetim kaydı",
	("tabVersion", "data"): "HISTORY_SOURCES",
	("tabDeleted Document", "data"): "HISTORY_SOURCES",
	("tabComment", "content"): "HISTORY_SOURCES",
	("tabError Log", "error"): "HISTORY_SOURCES",
	("tabBulk Import Job Error", "raw_row_json"): "HISTORY_SOURCES",
	("tabBulk Import Job", "data_file"): "HISTORY_SOURCES",
}


def _tum_kaynaklar() -> tuple[tuple[str, str, str, str], ...]:
	return usage.LIVE_SOURCES + usage.ORDER_SOURCES + usage.HISTORY_SOURCES


def _kolonlar(tablo: str) -> set[str]:
	return {
		r[0]
		for r in frappe.db.sql(
			"""select column_name from information_schema.columns
			where table_schema = database() and table_name = %s""",
			(tablo,),
		)
	}


class TestKaynakSemasi(unittest.TestCase):
	def test_her_kaynak_kolonu_gercekten_var(self) -> None:
		eksik = []
		for tablo, kolon, _k, _l in _tum_kaynaklar():
			if kolon not in _kolonlar(tablo):
				eksik.append(f"{tablo}.{kolon}")
		self.assertEqual(eksik, [], f"kaynak listesinde olmayan alan(lar): {eksik}")

	def test_child_tablolar_gercekten_child(self) -> None:
		"""`CHILD_TABLES` şemayla uyuşmalı — `resolve()` kolon seçimi buna bağlı."""
		for tablo in usage.CHILD_TABLES:
			with self.subTest(tablo=tablo):
				kol = _kolonlar(tablo)
				self.assertTrue(kol, f"{tablo} tablosu yok")
				self.assertLessEqual({"parent", "idx"}, kol, f"{tablo} child table değil")

	def test_child_olmayan_kaynaklarda_parent_yok(self) -> None:
		"""Karşı yön: listede olmayan bir kaynak gerçekten ana tablo mu.

		Yalnız CANLI + SİPARİŞ kaynakları denetleniyor: `resolve()` yalnız o iki
		grupta ek kolon seçiyor. GEÇMİŞ grubu (`tabBulk Import Job Error` gibi
		child tablolar da içeriyor) `_match_rows`'a `extra` vermeden çağrılıyor,
		yani `parent` hiç seçilmiyor ve sınıflandırma kararı değiştirmiyor.
		"""
		for tablo, _c, _k, _l in usage.LIVE_SOURCES + usage.ORDER_SOURCES:
			if tablo in usage.CHILD_TABLES:
				continue
			with self.subTest(tablo=tablo):
				self.assertNotIn("parent", _kolonlar(tablo),
					f"{tablo} child table görünüyor ama CHILD_TABLES'ta yok")

	def test_resolve_kolon_secimi_her_kaynak_icin_gecerli(self) -> None:
		"""`_extra_columns` seçtiği her kolon o tabloda gerçekten var mı.

		Bu doğrulanmazsa `resolve()` sorgusu "Unknown column" ile patlar, hata
		yutulur ve dosya "kullanılmıyor" görünür.
		"""
		for tablo, _c, _k, _l in usage.LIVE_SOURCES:
			with self.subTest(tablo=tablo):
				kol = _kolonlar(tablo)
				istenen = {p.strip() for p in usage._extra_columns(tablo).split(",")}
				self.assertLessEqual(istenen, kol, f"{tablo}: {istenen - kol} yok")

	def test_her_kaynak_tablosunun_doctype_karsiligi_var(self) -> None:
		for tablo, _c, _k, _l in usage.LIVE_SOURCES + usage.ORDER_SOURCES:
			with self.subTest(tablo=tablo):
				self.assertIn(tablo, usage.SOURCE_DOCTYPE)

	def test_store_filtresi_olan_tablonun_kolonu_var(self) -> None:
		"""Mağaza süzgeci yanlış kolona bakarsa satıcı kendi dosyasını göremez."""
		for tablo, kosul in usage.STORE_FILTERS.items():
			with self.subTest(tablo=tablo):
				kol = _kolonlar(tablo)
				self.assertTrue(kol, f"{tablo} tablosu yok")
				ilk = kosul.split()[0].strip("(`")
				if ilk in ("parent", "name", "seller", "seller_profile"):
					self.assertIn(ilk, kol, f"{tablo}.{ilk} yok")


class TestKorNoktaTaramasi(unittest.TestCase):
	"""Bugün '/files/' taşıyan hangi alan hâlâ hiçbir listede değil."""

	def _files_tasiyan_alanlar(self) -> set[tuple[str, str]]:
		kolonlar = frappe.db.sql(
			"""select table_name, column_name from information_schema.columns
			where table_schema = database()
			  and data_type in ('varchar','text','mediumtext','longtext','json')""",
			as_dict=True,
		)
		bulunan: set[tuple[str, str]] = set()
		for r in kolonlar:
			try:
				sayi = frappe.db.sql(
					f"select count(*) from `{r.table_name}` "  # noqa: S608 — şemadan gelen ad
					f"where locate('/files/', `{r.column_name}`) > 0"
				)[0][0]
			except Exception:
				continue
			if sayi:
				bulunan.add((r.table_name, r.column_name))
		return bulunan

	def test_kapsanmayan_alan_kalmadi(self) -> None:
		kapsanan = {(t, c) for t, c, _k, _l in _tum_kaynaklar()}
		acikta = self._files_tasiyan_alanlar() - kapsanan - set(BILINCLI_DISARIDA)
		self.assertEqual(
			sorted(acikta), [],
			"'/files/' taşıyan ama hiçbir kaynak listesinde olmayan alan(lar) var; "
			"ya LIVE/ORDER/HISTORY_SOURCES'a ekleyin ya BILINCLI_DISARIDA'ya gerekçeyle yazın",
		)

	def test_tarama_bos_donmuyor(self) -> None:
		"""Vacuity: tarama gerçekten alan buluyor mu."""
		self.assertGreater(len(self._files_tasiyan_alanlar()), 20)


class TestKapananKorNoktalar(unittest.TestCase):
	"""Ölçülmüş beş kör noktanın kararı gerçekten değişti mi — iki yönlü."""

	ALANLAR = (
		("tabAdmin Seller Profile", "banner_image"),
		("tabProduct Category", "image"),
		("tabSeller Category", "image"),
		("tabStatic Page SEO", "og_image"),
		("tabVerification Source", "icon"),
	)

	def _adresler(self, tablo: str, kolon: str) -> list[str]:
		ham = frappe.db.sql(
			f"select `{kolon}` from `{tablo}` where locate('/files/', `{kolon}`) > 0",  # noqa: S608
			pluck=True,
		)
		return sorted({u for d in ham for u in usage.extract_file_urls(d)})

	def test_kor_nokta_alanlari_in_use_dondu(self) -> None:
		for tablo, kolon in self.ALANLAR:
			with self.subTest(alan=f"{tablo}.{kolon}"):
				adresler = self._adresler(tablo, kolon)
				if not adresler:
					self.skipTest(f"{tablo}.{kolon} bu sitede dosya adresi taşımıyor")
				kararlar = usage.verdicts_for(adresler, deep=True)
				for url in adresler:
					self.assertEqual(kararlar[url]["verdict"], "in_use", url)

	def test_alan_listeden_cikarilinca_ayni_adres_unused_oluyor(self) -> None:
		"""Vacuity: karar gerçekten bu alanların eklenmiş olmasından geliyor.

		Düzeltme geçici olarak geri alınır (`LIVE_SOURCES` daraltılır), karar
		`unused`'a döner, sonra geri konur.
		"""
		hedef = None
		for tablo, kolon in self.ALANLAR:
			adresler = self._adresler(tablo, kolon)
			if adresler:
				hedef = (tablo, kolon, adresler[0])
				break
		if hedef is None:
			self.skipTest("ölçülebilir kör nokta adresi yok")
		tablo, kolon, url = hedef

		orijinal = usage.LIVE_SOURCES
		try:
			usage.LIVE_SOURCES = tuple(
				k for k in orijinal if (k[0], k[1]) != (tablo, kolon)
			)
			karar = usage.verdicts_for([url], deep=True)[url]["verdict"]
		finally:
			usage.LIVE_SOURCES = orijinal
		self.assertNotEqual(karar, "in_use",
			f"{tablo}.{kolon} listeden çıkarıldığı hâlde karar değişmedi — "
			"koruma başka bir yerden geliyor olabilir")
		self.assertEqual(usage.verdicts_for([url], deep=True)[url]["verdict"], "in_use",
			"liste geri konduğu hâlde karar dönmedi")


class TestResolveYeniKaynaklar(unittest.TestCase):
	def test_marka_logosu_kullanim_dokumune_dogru_doctype_ile_giriyor(self) -> None:
		ham = frappe.db.sql(
			"select logo from `tabBrand` where locate('/files/', logo) > 0 limit 1", pluck=True)
		if not ham:
			self.skipTest("bu sitede dosya adresli marka logosu yok")
		url = sorted(usage.extract_file_urls(ham[0]))[0]
		sonuc = usage.resolve(url)
		self.assertEqual(sonuc["verdict"], "in_use")
		doctypelar = {u["doctype"] for u in sonuc["usages"]}
		self.assertIn("Brand", doctypelar,
			f"marka logosu yanlış doctype ile raporlandı: {doctypelar}")

	def test_kategori_gorseli_kullanim_dokumune_giriyor(self) -> None:
		ham = frappe.db.sql(
			"select image from `tabProduct Category` where locate('/files/', image) > 0 limit 1",
			pluck=True)
		if not ham:
			self.skipTest("bu sitede dosya adresli kategori görseli yok")
		url = sorted(usage.extract_file_urls(ham[0]))[0]
		sonuc = usage.resolve(url)
		self.assertEqual(sonuc["verdict"], "in_use")
		self.assertIn("Product Category", {u["doctype"] for u in sonuc["usages"]})


if __name__ == "__main__":  # pragma: no cover
	unittest.main(verbosity=2)
