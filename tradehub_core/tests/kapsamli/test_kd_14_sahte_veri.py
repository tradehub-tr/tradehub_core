"""KD-14 — Ölçekli sahte veri korpusu: toplu yollar gerçek katalogda kırılıyor mu.

KD-12 tek dosyayı zorluyor; burada **katalog** zorlanıyor. Tek dosyada doğru
çalışan kod, 120 dosyalık bir kapsamda sayfalama hatası, N+1 sorgu, kiracı
sızıntısı ya da özet/sayfa tutarsızlığı üretebilir — bunlar ancak korpusla
görünür.

Korpus GERÇEKÇİ dağılımla üretiliyor: eksik alt metinli, kötü adlı, videolu,
özel, çok kısa alt metinli ve tamamen temiz kayıtlar karışık. Hepsi sahte;
hiçbir üretim verisine dokunulmuyor ve her kayıt sınıf sonunda siliniyor.

**Neden tek sınıf:** `FrappeTestCase` her testi işlem (transaction) içine alıp
geri sarıyor. Korpus `setUpClass` içinde açıkça `commit` edilmezse ilk testten
sonra kayboluyor — ilk kurguda tam olarak bu oldu (120 kayıt, 219 düşen alt
test). Korpus bir kez kurulup commit ediliyor, sınıf sonunda siliniyor.

Süre bütçesi: korpus kurulumu dâhil < 40 sn.
"""

from __future__ import annotations

import random
import time
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import seo, seo_audit
from tradehub_core.tests.kapsamli import _yardim as y

TOHUM: int = 20260828
KORPUS: int = 120

#: Toplu yolun ürettiği ama tekil yolun ÜRETMEDİĞİ kurallar (F-21).
BATCH_FAZLASI: frozenset[str] = frozenset({"missing_association", "missing_structured_data"})


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


class TestSahteKorpus(FrappeTestCase):
	korpus: list[dict] = []
	_kurulan: list[str] = []
	_toplu: dict = {}

	# ── korpus kurulumu ────────────────────────────────────────────────

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Korpus `setUpClass` icinde aciliyor; yama da sinif duzeyinde olmali.
		from unittest import mock as _mock

		for hedef in (
			"tradehub_core.media.av.enqueue_scan",
			"tradehub_core.media.av.maybe_scan_on_insert",
		):
			yama = _mock.patch(hedef, return_value=None)
			yama.start()
			cls.addClassCleanup(yama.stop)

		rng = random.Random(TOHUM)
		cls.korpus, cls._kurulan = [], []

		kotu_adlar = ["IMG_{}.jpg", "DSC{}.JPG", "untitled-{}.png", "Adsız {}.jpg"]
		iyi_adlar = [
			"kirmizi-kadife-koltuk-{}.jpg",
			"mese-yemek-masasi-{}.jpg",
			"celik-raf-sistemi-{}.png",
		]
		video_adlar = ["urun-tanitim-{}.mp4", "montaj-videosu-{}.webm"]

		for i in range(KORPUS):
			tur = i % 6
			if tur == 5:
				ad = rng.choice(video_adlar).format(i)
			elif tur in (0, 1):
				ad = rng.choice(kotu_adlar).format(i)
			else:
				ad = rng.choice(iyi_adlar).format(i)

			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"kd14-{ad}",
					"is_private": 1 if tur == 4 else 0,
					# Ölçü İNDEKSE bağlı: içerik-adresli depolama aynı baytları tek
					# adrese indiriyor. İlk kurguda üç ölçü kullanılmıştı ve 120
					# kayıt 17 ADRESE düştü — korpus sessizce küçüldü, testler
					# "ürün hatası" gibi görünen sonuçlar verdi. Ölçü artık tekil.
					"content": y.jpeg(200 + i * 7 + rng.randrange(3), 200 + i * 5),
				}
			)
			doc.insert(ignore_permissions=True)
			cls._kurulan.append(doc.name)

			# Alan dağılımı: bir bölümü boş, bir bölümü kısmi, bir bölümü dolu.
			if tur in (2, 3):
				seo.set_asset_fields(
					doc.file_url,
					{
						"alt": "Kırmızı kadife üç kişilik koltuk",
						"title": "Koltuk",
						"caption": "Salon takımı ürün görseli",
					},
				)
			elif tur == 1:
				seo.set_asset_fields(doc.file_url, {"alt": "kol"})  # çok kısa → uyarı

			cls.korpus.append(
				{"name": doc.name, "url": doc.file_url, "file_name": doc.file_name, "tur": tur}
			)

		# Testler işlem içinde koşup geri sarılıyor; korpus kalıcı olmalı.
		frappe.db.commit()
		cls._toplu = seo_audit.audit_batch([k["url"] for k in cls.korpus])

	@classmethod
	def tearDownClass(cls):
		for ad in cls._kurulan:
			try:
				frappe.delete_doc(
					"File", ad, ignore_permissions=True, force=True, delete_permanently=True
				)
			except Exception:
				pass
		frappe.db.commit()
		super().tearDownClass()

	@property
	def urls(self) -> list[str]:
		return [k["url"] for k in self.korpus]

	# ── 1. korpus sağlığı ──────────────────────────────────────────────

	def test_bi_korpus_kuruldu_ve_cesitli(self):
		self.assertEqual(len(self.korpus), KORPUS)
		self.assertEqual(len({k["url"] for k in self.korpus}), KORPUS, "adresler tekil olmalı")
		self.assertGreaterEqual(len({k["tur"] for k in self.korpus}), 5, "korpus yeterince çeşitli değil")

	def test_bi_alanlar_toplu_okunabiliyor(self):
		alanlar = seo.fields_for_many(self.urls)
		self.assertEqual(set(alanlar), set(self.urls))

	# ── 2. toplu denetim ───────────────────────────────────────────────

	def test_bi_batch_tum_korpusu_kapsiyor(self):
		self.assertEqual(self._toplu["total"], KORPUS)
		self.assertEqual(len(self._toplu["files"]), KORPUS)

	def test_bi_toplu_ve_tekil_denetim_ARTIK_AYNI(self):
		"""F-21 düzeltildi — tekil yol toplu yola delege ediyor.

		Önce: `audit_batch` satır bağlamıyla `missing_association` ve
		`missing_structured_data` üretiyor, `audit_file` üretmiyordu. Panelde
		liste 7 bulgu gösterirken satıra tıklayınca 5'e düşüyor ve skor
		değişiyordu.

		Parite artık YAPISAL: tekil denetim toplu yolu tek adres için çalıştırıp
		üstüne yalnız tekil-özel kuralları ekliyor. İki uygulama tutmak,
		zamanla yeniden ayrışan iki liste demekti.
		"""
		toplu = {
			r["file_url"]: {f["code"] for f in (r.get("findings") or [])}
			for r in self._toplu["files"]
		}
		ayrisanlar: list[str] = []
		for k in self.korpus[:20]:
			tekil = {f["code"] for f in seo_audit.audit_file(k["url"], deep=False)["findings"]}
			eksik = toplu[k["url"]] - tekil
			fazla = tekil - toplu[k["url"]]
			if eksik or fazla:
				ayrisanlar.append(f"{k['file_name']}: eksik={sorted(eksik)} fazla={sorted(fazla)}")
		self.assertEqual(ayrisanlar, [], "F-21 geri geldi:\n" + "\n".join(ayrisanlar[:6]))

	def test_bi_deep_bayragi_iki_yolda_da_orphan_asset_ekliyor(self):
		"""Kontrast: `deep` farkı TUTARLI, F-21'den ayrı bir eksen."""
		u = self.korpus[2]["url"]
		sig = {f["code"] for f in seo_audit.audit_file(u, deep=False)["findings"]}
		derin = {f["code"] for f in seo_audit.audit_file(u, deep=True)["findings"]}
		self.assertIn("orphan_asset", derin - sig)

	def test_bi_skor_iki_yolda_AYNI(self):
		"""F-21'in operatöre görünen sonucu düzeldi: aynı dosya, aynı skor."""
		farklar: list[str] = []
		for k in self.korpus[:12]:
			tekil = seo_audit.audit_file(k["url"], deep=False)["score"]["overall"]
			satir = next(r for r in self._toplu["files"] if r["file_url"] == k["url"])
			toplu = (satir.get("score") or {}).get("overall")
			if toplu is not None and tekil != toplu:
				farklar.append(f"{k['file_name']}: tekil={tekil} toplu={toplu}")
		self.assertEqual(farklar, [], "F-21 geri geldi:\n" + "\n".join(farklar))

	def test_bi_ozet_sayaclari_satirlarla_tutarli(self):
		gercek: dict[str, int] = {}
		for r in self._toplu["files"]:
			for f in r.get("findings") or []:
				gercek[f["code"]] = gercek.get(f["code"], 0) + 1
		ozet = self._toplu.get("summary") or {}
		for kod, sayi in gercek.items():
			if kod in ozet:
				with self.subTest(kod=kod):
					self.assertEqual(ozet[kod], sayi, f"{kod}: özet {ozet[kod]} ≠ gerçek {sayi}")

	def test_bi_eksik_alt_gercekten_sayiliyor(self):
		eksik = sum(
			1
			for r in self._toplu["files"]
			if any(f["code"] == "missing_alt" for f in (r.get("findings") or []))
		)
		self.assertGreater(eksik, 0, "korpusta eksik alt metni var ama denetim bulmuyor")
		self.assertLess(eksik, KORPUS, "hepsi eksik görünüyor — dolu alanlar okunmuyor")

	def test_bi_kisa_alt_metni_uyari_uretiyor(self):
		supheli = sum(
			1
			for r in self._toplu["files"]
			if any(f["code"] == "suspicious_alt" for f in (r.get("findings") or []))
		)
		self.assertGreater(supheli, 0, "3 harflik alt metinleri var ama uyarı yok")

	def test_bi_skor_0_100_araliginda(self):
		for boyut, puan in (self._toplu.get("score") or {}).items():
			with self.subTest(boyut=boyut):
				self.assertGreaterEqual(puan, 0, boyut)
				self.assertLessEqual(puan, 100, boyut)

	def test_bi_bos_kapsam_AYNI_bicimde_donuyor(self):
		"""F-22 düzeltildi — yanıt şekli girdiye göre değişmiyor."""
		bos = seo_audit.audit_batch([])
		self.assertEqual(bos["files"], [])
		self.assertEqual(bos["total"], 0, "F-22 geri geldi")
		self.assertEqual(set(bos), set(self._toplu) & set(bos), "anahtar kümesi ayrıştı")
		for anahtar in ("files", "summary", "score", "total"):
			self.assertIn(anahtar, bos, anahtar)
			self.assertIn(anahtar, self._toplu, anahtar)

	def test_gv_olmayan_adresler_karisirsa_patlamaz(self):
		karisik = self.urls[:10] + [f"/files/kd14-olmayan-{i}.jpg" for i in range(10)]
		self.assertIsInstance(seo_audit.audit_batch(karisik)["files"], list)

	def test_gv_tekrar_eden_adres_ciftlenmez(self):
		sonuc = seo_audit.audit_batch(self.urls[:10] + self.urls[:10])
		adresler = [r["file_url"] for r in sonuc["files"]]
		self.assertEqual(len(adresler), len(set(adresler)), "aynı dosya iki kez raporlandı")

	# ── 3. sayfalama ───────────────────────────────────────────────────

	def test_bi_sayfalar_birlesince_TAM_korpus(self):
		boyut, toplanan, sayfa = 25, [], 1
		while True:
			p = seo_audit.paginate(self._toplu, page=sayfa, page_size=boyut)
			toplanan += [r["file_url"] for r in p["files"]]
			if sayfa >= p["page_count"]:
				break
			sayfa += 1
		self.assertEqual(len(toplanan), KORPUS, "sayfalar birleşince korpus tamamlanmıyor")
		self.assertEqual(len(set(toplanan)), KORPUS, "sayfalar arasında tekrar var")

	def test_bi_ozet_ve_skor_SAYFAYA_gore_degismez(self):
		a = seo_audit.paginate(self._toplu, page=1, page_size=10)
		b = seo_audit.paginate(self._toplu, page=5, page_size=10)
		self.assertEqual(a["summary"], b["summary"])
		self.assertEqual(a["score"], b["score"])
		self.assertEqual(a["total"], b["total"])
		self.assertEqual(a["total"], KORPUS)

	def test_sn_sayfa_sinirlari(self):
		for sayfa, boyut in ((0, 10), (-5, 10), (10**6, 10), (1, 0), (1, -1), (1, 10**6)):
			with self.subTest(sayfa=sayfa, boyut=boyut):
				p = seo_audit.paginate(self._toplu, page=sayfa, page_size=boyut)
				self.assertGreaterEqual(p["page"], 1)
				self.assertGreaterEqual(p["page_size"], 1)
				self.assertLessEqual(p["page_size"], 200, "sayfa boyutu tavanı yok")
				self.assertLessEqual(len(p["files"]), p["page_size"])

	def test_bi_kod_suzgeci_SUNUCUDA_uygulaniyor(self):
		p = seo_audit.paginate(self._toplu, page=1, page_size=200, code="missing_alt")
		self.assertGreater(p["filtered_total"], 0)
		self.assertLess(p["filtered_total"], KORPUS)
		for r in p["files"]:
			self.assertTrue(any(f["code"] == "missing_alt" for f in (r.get("findings") or [])))

	def test_bi_ad_aramasi_calisir(self):
		p = seo_audit.paginate(self._toplu, page=1, page_size=200, query="koltuk")
		self.assertGreater(p["filtered_total"], 0)
		for r in p["files"]:
			self.assertIn("koltuk", (r["file_name"] + r["file_url"]).lower())

	def test_gv_eslesmeyen_suzgec_bos_sayfa_verir_patlamaz(self):
		p = seo_audit.paginate(self._toplu, page=1, page_size=50, code="kesinlikle_olmayan_kod")
		self.assertEqual(p["files"], [])
		self.assertEqual(p["filtered_total"], 0)
		self.assertEqual(p["page_count"], 1)
		self.assertEqual(p["total"], KORPUS, "süzgeç toplam sayıyı bozmamalı")

	def test_gv_arama_ozel_karakterlerle_patlamaz(self):
		for q in ("%", "_", "'", '"', "\\", "%%", "..", "<script>", "ü", "🎉"):
			with self.subTest(q=q):
				self.assertIsInstance(
					seo_audit.paginate(self._toplu, page=1, page_size=10, query=q)["files"], list
				)

	def test_gv_LIKE_jokerleri_arama_sonucunu_sismesin(self):
		"""`%` ve `_` SQL jokeri değil, düz metin olarak aranmalı."""
		p = seo_audit.paginate(self._toplu, page=1, page_size=200, query="%")
		self.assertEqual(
			p["filtered_total"], 0,
			"'%' tüm korpusu getirdi — joker olarak yorumlanıyor",
		)

	# ── 4. ölçek davranışı ─────────────────────────────────────────────

	def test_perf_toplu_denetim_DOGRUSAL_olceklenir(self):
		"""20 → 120 dosyada süre kareyle büyümemeli (N+1 dedektörü)."""
		basla = time.monotonic()
		seo_audit.audit_batch(self.urls[:20])
		t_kucuk = time.monotonic() - basla

		basla = time.monotonic()
		seo_audit.audit_batch(self.urls)
		t_buyuk = time.monotonic() - basla

		if t_kucuk < 0.01:
			self.skipTest(f"küçük koşum ölçülemeyecek kadar hızlı ({t_kucuk * 1000:.1f} ms)")
		oran = t_buyuk / t_kucuk
		self.assertLess(
			oran, 12.0,
			f"6× dosya için {oran:.1f}× süre — N+1 ya da karesel yol olabilir "
			f"({t_kucuk * 1000:.0f} ms → {t_buyuk * 1000:.0f} ms)",
		)

	def test_perf_toplu_denetim_sure_butcesi(self):
		basla = time.monotonic()
		seo_audit.audit_batch(self.urls)
		sure = time.monotonic() - basla
		self.assertLess(sure, 15.0, f"{KORPUS} dosya {sure:.1f} sn sürdü")

	def test_bi_deep_dosya_kumesini_degistirmez(self):
		sig = seo_audit.audit_batch(self.urls[:15], deep=False)
		derin = seo_audit.audit_batch(self.urls[:15], deep=True)
		self.assertEqual(
			[r["file_url"] for r in sig["files"]],
			[r["file_url"] for r in derin["files"]],
			"deep bayrağı dosya kümesini değiştirmemeli, yalnız bulguyu zenginleştirmeli",
		)

	# ── 5. maymun: rastgele operatör davranışı ─────────────────────────

	def test_maymun_rastgele_islem_dizisi_cokmez(self):
		"""Operatör sayfa değiştirir, süzgeç açar, arama yazar — rastgele sırada.

		Hiçbir dizi çökmemeli ve değişmezler bozulmamalı:
		özet = kapsam · sayfa ⊆ süzgeç · süzülen ≤ toplam.
		"""
		rng = random.Random(TOHUM)
		kodlar = sorted({f["code"] for r in self._toplu["files"] for f in (r.get("findings") or [])})
		aramalar = ["", "koltuk", "IMG", "kd14", "olmayan", "%", "ü", "mp4", "raf"]

		for adim in range(300):
			p = seo_audit.paginate(
				self._toplu,
				page=rng.randrange(-2, 8),
				page_size=rng.choice([0, 1, 7, 25, 200, 500]),
				code=rng.choice(kodlar + ["", "uydurma_kod"]),
				query=rng.choice(aramalar),
			)
			if (
				not isinstance(p["files"], list)
				or len(p["files"]) > p["page_size"]
				or p["filtered_total"] > p["total"]
				or p["total"] != KORPUS
			):
				ozet = {k: p[k] for k in ("page", "page_size", "filtered_total", "total")}
				self.fail(f"adım {adim}: değişmez bozuldu → {ozet}")

	def test_maymun_rastgele_alan_yazimi_denetimi_bozmaz(self):
		rng = random.Random(TOHUM + 1)
		degerler = [
			"", " ", "a", "a" * 300, "Kırmızı koltuk", "koltuk koltuk koltuk koltuk",
			"<script>alert(1)</script>", "🎉🎉🎉", "ürün (kod: ABC-123) (stok: 5) salon",
			"  boşluklu  ", "\n\t", "Ürün — em dash & ampersand < >", "'; DROP TABLE tabFile; --",
		]
		for k in [x for x in self.korpus if x["tur"] in (2, 3)][:12]:
			deger = rng.choice(degerler)
			with self.subTest(ad=k["file_name"], deger=deger[:20]):
				try:
					seo.set_asset_fields(k["url"], {"alt": deger})
				except Exception as exc:  # noqa: BLE001 — açık ret kabul
					self.assertTrue(str(exc), "sessiz istisna")
					continue
				rapor = seo_audit.audit_file(k["url"], deep=False)
				self.assertGreaterEqual(rapor["score"]["overall"], 0)
				self.assertLessEqual(rapor["score"]["overall"], 100)

	def test_gv_maymun_SQL_enjeksiyonu_katalogu_bozmaz(self):
		"""Alan değeri olarak gelen SQL, korpusu etkilememeli."""
		hedef = self.korpus[3]
		seo.set_asset_fields(hedef["url"], {"alt": "'; DROP TABLE `tabFile`; --"})
		self.assertEqual(
			len(seo.fields_for_many(self.urls)), KORPUS, "korpus SQL yazımından sonra bozuldu"
		)

	def test_gv_maymun_yazimi_XSS_ham_donuyor_kacislama_TUKETICIDE(self):
		"""Sözleşmeyi sabitler: API ham döndürüyor, kaçışlama tüketicinin işi.

		Değişirse (API kaçışlamaya başlarsa) panelde ÇİFT kaçışlama görünür;
		bu test o değişikliği yakalar.
		"""
		hedef = self.korpus[2]
		seo.set_asset_fields(hedef["url"], {"alt": "<script>alert(1)</script>"})
		self.assertEqual(seo.fields_for(hedef["url"]).get("alt"), "<script>alert(1)</script>")

	# ── 6. kiracı izolasyonu ───────────────────────────────────────────

	def test_bi_var_olmayan_adres_ACIK_missing_file_bulgusu_uretiyor(self):
		"""Bilinmeyen adres uydurma bir "her şey eksik" satırına dönüşmüyor.

		Beklenen kusur buydu: bayat bir adres listesiyle çalışan panelin
		olmayan dosyaları `missing_alt` olarak sayıp kapsam özetini şişirmesi.
		ÖLÇÜLDÜ — kod bunu yapmıyor: var olmayan adres için TEK ve AÇIK bir
		`missing_file` bulgusu üretiliyor, alan bulguları hiç çalıştırılmıyor.
		Doğru davranış; test onu sabitliyor.
		"""
		yabanci = ["/private/files/kd14-hic-olmayan-dosya.jpg", "/files/kd14-yok.png"]
		satirlar = seo_audit.audit_batch(self.urls[:5] + yabanci)["files"]
		hedefler = [r for r in satirlar if r["file_url"] in yabanci]
		self.assertEqual(len(hedefler), len(yabanci), "bilinmeyen adres hiç raporlanmadı")
		for r in hedefler:
			kodlar = {f["code"] for f in (r.get("findings") or [])}
			self.assertEqual(kodlar, {"missing_file"}, f"{r['file_url']}: {kodlar}")
			self.assertFalse((r.get("alt") or "").strip(), "var olmayan adres için içerik döndü")

	def test_gv_bilinmeyen_adres_ozet_sayaclarini_sismiyor(self):
		"""`missing_alt` sayacı olmayan dosyalarla şişmemeli."""
		temiz = seo_audit.audit_batch(self.urls[:20])
		kirli = seo_audit.audit_batch(self.urls[:20] + [f"/files/kd14-yok-{i}.jpg" for i in range(15)])
		a = (temiz.get("summary") or {}).get("missing_alt", 0)
		b = (kirli.get("summary") or {}).get("missing_alt", 0)
		self.assertEqual(a, b, "olmayan dosyalar missing_alt sayacını şişirdi")

	def test_gv_yol_kacisi_deseni_kapsama_sokulamaz(self):
		"""`../` içeren adres denetimden gerçek bir dosya çıkarmamalı."""
		kacis = "/files/../../etc/passwd"
		satirlar = seo_audit.audit_batch([kacis])["files"]
		for r in satirlar:
			self.assertFalse(
				(r.get("alt") or r.get("title") or "").strip(),
				"yol kaçışı adresi gerçek içerik döndürdü",
			)

	def test_gv_alan_yazimi_olmayan_dosyada_sessizce_basarili_olmaz(self):
		try:
			yazilan = seo.set_asset_fields("/files/kd14-kesinlikle-olmayan.jpg", {"alt": "x"})
		except Exception:
			return  # açık ret — doğru davranış
		self.assertEqual(yazilan, 0, "olmayan dosyaya yazım 'başarılı' raporladı")

	def test_gv_ozel_dosyalar_korpusta_isaretli(self):
		ozel = [k for k in self.korpus if k["tur"] == 4]
		self.assertGreater(len(ozel), 0, "kurgu: korpusta özel dosya olmalı")
		for k in ozel[:5]:
			with self.subTest(ad=k["file_name"]):
				self.assertIn("/private/", k["url"], "is_private=1 dosya public adreste")


if __name__ == "__main__":
	unittest.main()
