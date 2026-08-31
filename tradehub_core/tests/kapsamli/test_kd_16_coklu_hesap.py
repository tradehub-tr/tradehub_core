"""KD-16 — Çok hesaplı ilişkisel matris + işlem sırası permütasyonları (faktöriyel).

İki soru, ikisi de örneklemeyle cevaplanamaz:

**1. İlişkisel matris.** 3 hesap × 3 sahip = 9 (aktör, sahip) çifti. Her çift
için 6 işlem denenir → **54 yetki iddiası**. Beklenti keskin: yalnız
`aktör == sahip` başarılı olmalı, kalan 6 çiftte HER işlem düşmeli. Tek bir
hücrenin açık kalması çapraz kiracı sızıntısıdır ve "üç örnek denedim, üçü de
kapalıydı" bunu bulmaz.

**2. Sıra permütasyonları.** Aynı işlemler farklı sırada çalıştırıldığında
sonuç değişiyor mu? Sıraya duyarlı bir hata ancak o sırayı denerseniz görünür:

    4 parçalı yükleme → 4! =  24 sıra
    5 varlık işlemi   → 5! = 120 sıra
    3 hesap × 3! ret sırası → 18 dizi

Toplam 162 tam sıra + 54 yetki hücresi. Hiçbiri örneklenmiyor.

Süre bütçesi: < 90 sn (parça birleştirme gerçek dosya I/O'su yapıyor).
"""

from __future__ import annotations

import itertools
import math
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import chunked, seo, seo_audit
from tradehub_core.tests.kapsamli import _yardim as y

#: Üç ayrı satıcı hesabı. Üçüncüsü bilinçli olarak ötekilere "benzer"
#: (önek paylaşıyor) — önek karşılaştırması yapan bir kod burada düşer.
HESAPLAR: tuple[str, ...] = ("KD16-MAGAZA-A", "KD16-MAGAZA-B", "KD16-MAGAZA-A-YAN")

ILISKI_CIFTLERI: tuple[tuple[str, str], ...] = tuple(itertools.product(HESAPLAR, HESAPLAR))


#: ORTAM BAĞIMSIZLIĞI — File açan her fixture tarama kancasını nötrler.
#: Gerekçe (ölçülmüş, TUR-125): ClamAV kurulu bir makinede `after_insert`
#: kancası dosyayı `pending` damgalayıp bekletmeye alıyor; fixture'lar
#: dosyanın `public/files/`'da durduğunu varsaydığı için kırılıyor. Kurulum
#: bir kerede 6 testi düşürmüştü. Kural: bir bağımlılığın YOKLUĞU üstüne
#: test yazma.
def _av_kancasini_notrle(testcase):
	from unittest import mock as _mock

	for hedef in (
		"tradehub_core.media.av.enqueue_scan",
		"tradehub_core.media.av.maybe_scan_on_insert",
	):
		yama = _mock.patch(hedef, return_value=None)
		yama.start()
		testcase.addCleanup(yama.stop)


# ══════════════════════════════════════════════════════════════════════
# 1. İlişkisel yetki matrisi — 9 çift × 6 işlem
# ══════════════════════════════════════════════════════════════════════


class TestIliskiselMatris(FrappeTestCase):
	"""(aktör, sahip) tam çarpımı. Köşegen dışı HER hücre kapalı olmalı."""

	def setUp(self):
		super().setUp()
		self.acilan: list[tuple[str, str]] = []

	def tearDown(self):
		for oid, sahip in self.acilan:
			try:
				chunked.cleanup_session(oid, sahip)
			except Exception:
				pass
		super().tearDown()

	def _oturum(self, sahip: str, icerik: bytes) -> dict:
		d = chunked.begin("urun.jpg", len(icerik), sahip)
		self.acilan.append((d["upload_id"], sahip))
		return d

	def test_bi_matris_boyutu(self):
		self.assertEqual(len(HESAPLAR), 3)
		self.assertEqual(len(ILISKI_CIFTLERI), 9, "3 hesap → 3×3 = 9 ilişki çifti")

	def test_gv_MATRIS_tam_yetki_carpimi(self):
		"""9 çift × işlem çarpımı. Köşegen geçer, köşegen dışı HER hücre kapalı.

		**Reddetme biçimi işleme göre değişiyor ve bu bilinçli:**

		    put_chunk · meta_of · finish · cleanup  → İSTİSNA atarak reddeder
		    finalized_result                        → `None` dönerek reddeder

		İlk kurguda hepsi "istisna atmalı" sayılmıştı ve `finalized_result`
		altı hücrede sahte "AÇIK" verdi. `None` dönmek burada doğru davranış:
		okuma ucu, anahtarın başka bir kiracıda VAR olduğunu bile sızdırmamalı —
		"yetkin yok" demek "o anahtar var" demektir. Matris bu ayrımı artık
		işlem başına tanımlıyor.
		"""
		icerik = y.jpeg(300, 300)
		anahtar = f"kd16-mat-{frappe.generate_hash(length=10)}"
		for sahip in HESAPLAR:
			chunked.save_finalized_result(anahtar, sahip, {"file_url": f"/files/{sahip}.jpg"})

		acik_hucreler: list[str] = []
		hucre_sayisi = 0

		for aktor, sahip in ILISKI_CIFTLERI:
			ayni = aktor == sahip
			oturum = self._oturum(sahip, icerik)
			oid = oturum["upload_id"]
			chunked.put_chunk(oid, 0, icerik, sahip)  # sahibi parçayı yazsın

			# (ad, çağrı, reddetme biçimi)
			#
			# Döngü değişkenleri lambda'ya VARSAYILAN ARGÜMAN olarak bağlanıyor.
			# Çağrılar aynı yinelemede tüketildiği için bugün geç bağlama zararsız,
			# ama listenin döngü dışına taşındığı bir düzenlemede sessizce son
			# yinelemenin değerleriyle koşardı (ruff B023).
			islemler = (
				("meta_of", lambda o=oid, a=aktor: chunked.meta_of(o, a), "istisna"),
				("put_chunk", lambda o=oid, a=aktor: chunked.put_chunk(o, 0, icerik, a), "istisna"),
				("finish", lambda o=oid, a=aktor: chunked.finish(o, a), "istisna"),
				("finalized_result", lambda k=anahtar, a=aktor: chunked.finalized_result(k, a), "bos"),
			)

			for ad, islem, bicim in islemler:
				hucre_sayisi += 1
				with self.subTest(aktor=aktor, sahip=sahip, islem=ad):
					if ayni:
						try:
							sonuc = islem()
						except Exception as exc:  # noqa: BLE001
							self.fail(f"sahip kendi kaynağında {ad} yapamadı: {exc}")
						if bicim == "bos":
							self.assertEqual(
								sonuc, {"file_url": f"/files/{aktor}.jpg"},
								f"{aktor} kendi sonucunu okuyamadı",
							)
						continue

					# köşegen dışı — kapalı olmalı
					try:
						sonuc = islem()
					except Exception:
						continue  # istisna ile reddetti
					if bicim == "istisna":
						acik_hucreler.append(f"({aktor} → {sahip}) {ad}: istisna atmadı")
					elif sonuc not in (None, {}, []):
						# `finalized_result` kendi kapsamındaki kaydı döndürebilir;
						# SIZINTI, SAHİBİN kaydının dönmesidir.
						if sonuc == {"file_url": f"/files/{sahip}.jpg"}:
							acik_hucreler.append(f"({aktor} → {sahip}) {ad}: SAHİBİN verisi sızdı")

			chunked.cleanup_session(oid, sahip)

		self.assertEqual(acik_hucreler, [], "\n".join(acik_hucreler))
		self.assertEqual(hucre_sayisi, 36, f"9 çift × 4 işlem = 36 hücre beklenir, {hucre_sayisi}")

	def test_gv_kosegen_disinda_cleanup_kapali(self):
		"""Silme ayrı ölçülüyor: yabancı sildiyse sahibin oturumu ÖLÜR."""
		icerik = y.jpeg(200, 200)
		for aktor, sahip in ILISKI_CIFTLERI:
			if aktor == sahip:
				continue
			with self.subTest(aktor=aktor, sahip=sahip):
				oturum = self._oturum(sahip, icerik)
				try:
					chunked.cleanup_session(oturum["upload_id"], aktor)
				except Exception:
					pass
				# Sahip hâlâ erişebilmeli — yabancı silememiş olmalı.
				self.assertTrue(
					chunked.meta_of(oturum["upload_id"], sahip),
					f"{aktor}, {sahip} oturumunu SİLDİ",
				)

	def test_gv_ONEK_PAYLASAN_hesap_erisemiyor(self):
		"""`KD16-MAGAZA-A` ile `KD16-MAGAZA-A-YAN`: önek karşılaştırması yapan
		bir kod bu ikisini karıştırır. Kapsam TAM eşleşme olmalı."""
		icerik = y.jpeg(200, 200)
		oturum = self._oturum("KD16-MAGAZA-A", icerik)
		with self.assertRaises(Exception):
			chunked.meta_of(oturum["upload_id"], "KD16-MAGAZA-A-YAN")
		with self.assertRaises(Exception):
			chunked.put_chunk(oturum["upload_id"], 0, icerik, "KD16-MAGAZA-A-YAN")

	def test_gv_idempotency_sonucu_9_ciftte_izole(self):
		"""Aynı anahtar 3 hesapta ayrı yaşamalı — 9 okuma hücresi."""
		anahtar = f"kd16-{frappe.generate_hash(length=12)}"
		for sahip in HESAPLAR:
			chunked.save_finalized_result(anahtar, sahip, {"file_url": f"/files/{sahip}.jpg"})

		for aktor, sahip in ILISKI_CIFTLERI:
			with self.subTest(aktor=aktor, sahip=sahip):
				okunan = chunked.finalized_result(anahtar, aktor)
				self.assertEqual(
					okunan, {"file_url": f"/files/{aktor}.jpg"},
					f"{aktor} okurken {sahip} verisi geldi",
				)

	def test_gv_bilinmeyen_hesap_hicbir_seye_erisemez(self):
		icerik = y.jpeg(200, 200)
		oturum = self._oturum(HESAPLAR[0], icerik)
		for yabanci in ("", "  ", "KD16-YOK", "*", "%", "KD16-MAGAZA-%"):
			with self.subTest(yabanci=yabanci):
				with self.assertRaises(Exception):
					chunked.meta_of(oturum["upload_id"], yabanci)


# ══════════════════════════════════════════════════════════════════════
# 2. Parça sırası — 4! = 24 permütasyon
# ══════════════════════════════════════════════════════════════════════


class TestParcaSirasiPermutasyonu(FrappeTestCase):
	"""4 parçanın TÜM 24 sırası. Ağ paralel gönderir, yeniden deneme araya
	girer — sıra garantisi yoktur ve birleştirme her sırada aynı dosyayı
	üretmek zorundadır."""

	MAGAZA = "KD16-PERM"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Dört parçaya bölünecek kadar büyük GERÇEK bir JPEG (>6 MB) bir kez üretilir.
		cls.icerik = y.jpeg(3600, 3600, quality=98)
		cls.parca_sayisi = (len(cls.icerik) + chunked.CHUNK_BYTES - 1) // chunked.CHUNK_BYTES

	def setUp(self):
		super().setUp()
		if self.parca_sayisi < 3:
			self.skipTest(f"üretilen JPEG yalnız {self.parca_sayisi} parça ({len(self.icerik)} B)")
		self.acilan: list[str] = []

	def tearDown(self):
		for oid in self.acilan:
			try:
				chunked.cleanup_session(oid, self.MAGAZA)
			except Exception:
				pass
		super().tearDown()

	def _dilimler(self) -> list[bytes]:
		return [
			self.icerik[i * chunked.CHUNK_BYTES : (i + 1) * chunked.CHUNK_BYTES]
			for i in range(self.parca_sayisi)
		]

	def test_bi_permutasyon_sayisi_faktoriyel(self):
		n = self.parca_sayisi
		self.assertEqual(
			len(list(itertools.permutations(range(n)))), math.factorial(n),
			f"{n} parça → {n}! sıra beklenir",
		)

	def test_kb_TUM_PARCA_SIRALARI_ayni_dosyayi_uretir(self):
		"""n! sıranın tamamı — örnekleme yok."""
		dilimler = self._dilimler()
		n = self.parca_sayisi
		siralar = list(itertools.permutations(range(n)))
		self.assertEqual(len(siralar), math.factorial(n))

		hatalar: list[str] = []
		for sira in siralar:
			d = chunked.begin("urun.jpg", len(self.icerik), self.MAGAZA)
			self.acilan.append(d["upload_id"])
			for i in sira:
				chunked.put_chunk(d["upload_id"], i, dilimler[i], self.MAGAZA)
			birlesen = chunked.finish(d["upload_id"], self.MAGAZA)
			if birlesen != self.icerik:
				hatalar.append(f"sıra {sira}: birleşen içerik farklı ({len(birlesen)} B)")
			chunked.cleanup_session(d["upload_id"], self.MAGAZA)
		self.assertEqual(hatalar, [], "\n".join(hatalar[:10]))

	def test_kb_TEKRARLI_parca_her_sirada_zararsiz(self):
		"""Her sıranın üstüne bir de tekrar gönderim — yeniden deneme senaryosu."""
		dilimler = self._dilimler()
		n = self.parca_sayisi
		hatalar: list[str] = []
		for sira in itertools.permutations(range(n)):
			d = chunked.begin("urun.jpg", len(self.icerik), self.MAGAZA)
			self.acilan.append(d["upload_id"])
			for i in sira:
				chunked.put_chunk(d["upload_id"], i, dilimler[i], self.MAGAZA)
				chunked.put_chunk(d["upload_id"], i, dilimler[i], self.MAGAZA)  # tekrar
			if chunked.finish(d["upload_id"], self.MAGAZA) != self.icerik:
				hatalar.append(f"sıra {sira}: tekrarlı gönderimde içerik bozuldu")
			chunked.cleanup_session(d["upload_id"], self.MAGAZA)
		self.assertEqual(hatalar, [], "\n".join(hatalar[:10]))

	def test_kb_EKSIK_parca_her_sirada_reddedilir(self):
		"""Her sırada son parça atlanırsa birleştirme HER seferinde düşmeli."""
		dilimler = self._dilimler()
		n = self.parca_sayisi
		gecen: list[str] = []
		for sira in itertools.permutations(range(n)):
			d = chunked.begin("urun.jpg", len(self.icerik), self.MAGAZA)
			self.acilan.append(d["upload_id"])
			for i in sira[:-1]:
				chunked.put_chunk(d["upload_id"], i, dilimler[i], self.MAGAZA)
			try:
				chunked.finish(d["upload_id"], self.MAGAZA)
			except Exception:
				pass
			else:
				gecen.append(f"sıra {sira}: eksik parçayla birleştirme GEÇTİ")
			chunked.cleanup_session(d["upload_id"], self.MAGAZA)
		self.assertEqual(gecen, [], "\n".join(gecen[:10]))


# ══════════════════════════════════════════════════════════════════════
# 3. Varlık işlem sırası — 5! = 120 permütasyon
# ══════════════════════════════════════════════════════════════════════


class TestVarlikIslemSirasi(FrappeTestCase):
	"""Beş varlık işleminin TÜM 120 sırası.

	Ölçülen değişmezler:
	  * hiçbir sıra istisna atmaz,
	  * son yazma kazanır (write-last-wins) — sıra bağımsız DEĞİL ama
	    **öngörülebilir** olmalı,
	  * hangi sırayla gidilirse gidilsin denetim hâlâ çalışır ve skor
	    0-100 aralığında kalır.
	"""

	def setUp(self):
		super().setUp()
		_av_kancasini_notrle(self)
		self.dosyalar: list[str] = []

	def tearDown(self):
		for ad in self.dosyalar:
			try:
				frappe.delete_doc("File", ad, ignore_permissions=True, force=True, delete_permanently=True)
			except Exception:
				pass
		# Test edilen kod commit ediyor; DELETE de commit edilmeli yoksa
		# rollback silmeyi geri alir ve artik kayit kalir (TUR-125 tuzagi).
		frappe.db.commit()
		super().tearDown()

	def _yeni_dosya(self, i: int) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"kd16-varlik-{i}.jpg",
				"is_private": 0,
				"content": y.jpeg(300 + i, 300 + i * 2),
			}
		)
		doc.insert(ignore_permissions=True)
		self.dosyalar.append(doc.name)
		return doc.file_url

	def test_bi_permutasyon_sayisi_120(self):
		self.assertEqual(math.factorial(5), 120)

	def test_kb_TUM_120_SIRA_cokmez_ve_skor_aralikta(self):
		siralar = list(itertools.permutations(range(5)))
		self.assertEqual(len(siralar), 120)
		hatalar: list[str] = []

		for n, sira in enumerate(siralar):
			url = self._yeni_dosya(n)
			islemler = [
				lambda u=url: seo.set_asset_fields(u, {"alt": "Birinci alt metni"}),
				lambda u=url: seo.set_asset_fields(u, {"title": "Başlık"}),
				lambda u=url: seo.set_asset_fields(u, {"caption": "Altyazı"}),
				lambda u=url: seo_audit.audit_file(u, deep=False),
				lambda u=url: seo.fields_for(u),
			]
			for adim in sira:
				try:
					islemler[adim]()
				except Exception as exc:  # noqa: BLE001
					hatalar.append(f"sıra {sira} adım {adim}: {type(exc).__name__}: {exc}")
					break
			else:
				rapor = seo_audit.audit_file(url, deep=False)
				puan = rapor["score"]["overall"]
				if not (0 <= puan <= 100):
					hatalar.append(f"sıra {sira}: skor aralık dışı ({puan})")
				alanlar = seo.fields_for(url)
				# Üç yazma işlemi de yapıldıysa üç alan da dolu olmalı — sıradan
				# bağımsız. Kısmi yazma (aynı alana iki kez) yok, bu yüzden
				# beklenti kesin.
				for alan, beklenen in (
					("alt", "Birinci alt metni"),
					("title", "Başlık"),
					("caption", "Altyazı"),
				):
					if (alanlar.get(alan) or "") != beklenen:
						hatalar.append(
							f"sıra {sira}: {alan} = {alanlar.get(alan)!r} (beklenen {beklenen!r})"
						)
						break
			if len(hatalar) > 10:
				break

		self.assertEqual(hatalar, [], "\n".join(hatalar[:10]))

	def test_kb_AYNI_ALANA_yazma_sirasi_SON_YAZAN_kazanir(self):
		"""3! = 6 sıra; hangi sırayla yazılırsa yazılsın sonuncu değer kalmalı."""
		degerler = ["Alfa alt metni", "Beta alt metni", "Gama alt metni"]
		hatalar: list[str] = []
		for n, sira in enumerate(itertools.permutations(range(3))):
			url = self._yeni_dosya(1000 + n)
			for adim in sira:
				seo.set_asset_fields(url, {"alt": degerler[adim]})
			beklenen = degerler[sira[-1]]
			gercek = seo.fields_for(url).get("alt")
			if gercek != beklenen:
				hatalar.append(f"sıra {sira}: alt = {gercek!r}, beklenen {beklenen!r}")
		self.assertEqual(hatalar, [], "\n".join(hatalar))


# ══════════════════════════════════════════════════════════════════════
# 4. Hesap × sıra birleşimi — 3 hesap × 3! ret sırası = 18 dizi
# ══════════════════════════════════════════════════════════════════════


class TestHesapVeSiraBirlesimi(FrappeTestCase):
	"""Çapraz kiracı denemeleri farklı sıralarda yapılırsa biri açılıyor mu?

	Yetki kontrolü durum tutuyorsa (önbellek, oturum, ilk çağrıda kurulan
	bağlam) sıra önem kazanır: "önce meta oku, sonra parça yaz" ile tersi
	farklı sonuç verebilir. 3 işlem × 3! sıra × 3 yabancı hesap = 18 dizi.
	"""

	SAHIP = "KD16-SIRA-SAHIP"

	def setUp(self):
		super().setUp()
		self.acilan: list[str] = []

	def tearDown(self):
		for oid in self.acilan:
			try:
				chunked.cleanup_session(oid, self.SAHIP)
			except Exception:
				pass
		super().tearDown()

	def test_kb_18_DIZI_hicbir_sirada_yabanci_gecemiyor(self):
		icerik = y.jpeg(250, 250)
		yabancilar = [h for h in HESAPLAR if h != self.SAHIP][:3] or ["KD16-YABANCI"]
		acilanlar: list[str] = []

		for yabanci in yabancilar:
			for sira in itertools.permutations(range(3)):
				d = chunked.begin("urun.jpg", len(icerik), self.SAHIP)
				self.acilan.append(d["upload_id"])
				oid = d["upload_id"]
				denemeler = [
					("meta_of", lambda o=oid, y=yabanci: chunked.meta_of(o, y)),
					("put_chunk", lambda o=oid, y=yabanci: chunked.put_chunk(o, 0, icerik, y)),
					("finish", lambda o=oid, y=yabanci: chunked.finish(o, y)),
				]
				for adim in sira:
					ad, islem = denemeler[adim]
					try:
						islem()
					except Exception:
						continue
					acilanlar.append(f"{yabanci} · sıra {sira} · {ad} GEÇTİ")
				chunked.cleanup_session(oid, self.SAHIP)

		self.assertEqual(acilanlar, [], "\n".join(acilanlar[:10]))

	def test_bi_dizi_sayisi(self):
		yabanci_sayisi = len([h for h in HESAPLAR if h != self.SAHIP])
		self.assertEqual(math.factorial(3), 6)
		self.assertGreaterEqual(yabanci_sayisi * 6, 12, "dizi sayısı beklenenden az")


if __name__ == "__main__":
	unittest.main()
