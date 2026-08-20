"""T-053 — Saklama/çöp toplama işlerinin ÜRETİM envanteri üzerindeki davranışı.

`tests/test_retention.py` politikayı ve `RetentionSweeper`'ı frappe'siz,
geçici disk üzerinde ölçer. Bu modül farklı bir soruyu sorar: iş gerçek
`File` / `Media Asset` / `Media Rendition` envanteri üzerinde koştuğunda
gerçekten hiçbir şeye dokunmuyor mu, legal hold gerçekten koruyor mu.

Beş kanıt, beşi de İKİ YÖNLÜ ölçülür — "hiçbir şey silmiyor" tek başına
"kod hiç çalışmıyor" ile aynı sonucu verir, o yüzden her korumanın
kaldırıldığında aday ÜRETTİĞİ de gösterilir:

  1. Kuru koşum      — öncesi/sonrası `File` sayısı ve disk boyutu birebir aynı
  2. Legal hold      — hold=1 bloke; hold=0 AYNI iş aynı dosyayı aday görüyor
  3. Eksik dosya     — diskte karşılığı olmayan `File` kaydı GC'yi düşürmüyor
  4. `Brand.logo`    — artık `usage.LIVE_SOURCES` görüyor (T-043, 2026-08-19);
                       emniyet ağı da yerinde duruyor
  5. Boş küme        — `Media Rendition` boşken türev işi 0 satırla doğru koşuyor
  7. Kullanım kapısı — orijinal süpürücüsü kullanımdaki dosyayı aday görmüyor;
                       kullanım ölçülemezse hiçbir şeyi aday görmüyor
  8. Ayrı işler      — orijinal/türev ayrı bayrak, ayrı kilit, ayrı rapor

Çalıştırma:

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_retention_gc
"""

from __future__ import annotations

import os
import time
import unittest

import frappe

from tradehub_core.media.pipeline.storage import retention as ret

#: Testin diskte bıraktığı dosyaların ön eki — temizlik bunu arar.
PREFIX = "t053gc"

#: Yaşlandırma penceresi: politikanın `local_days=1` eşiğini kesin aşsın.
YAS_GUN = 30


def _politika(**ust) -> ret.RetentionPolicy:
	"""Silmeye İSTEKLİ politika. Varsayılan (`keep_forever`) hiçbir aday üretmez.

	Kuru koşumun bir şey söylediğini gösterebilmek için politikayı bilinçli
	olarak agresif kuruyoruz: her koşum yine de `dry_run=True` olduğu için
	tek bir dosya bile silinmez, ama "aday" sayacı sıfırdan farklı olur.
	"""
	conf = {
		"original_retention": {"keep_forever": False, "local_days": 1, "then": "delete"},
		"legal_hold": {"enabled": True, "field": ret.LEGAL_HOLD_DOCFIELD},
	}
	conf.update(ust)
	return ret.RetentionPolicy.from_mapping(conf)


class GcTemeli(unittest.TestCase):
	"""Ortak kurulum: gerçek `File` kaydı + gerçek disk dosyası."""

	def setUp(self) -> None:
		self.olusturulan_dosyalar: list[str] = []
		self.olusturulan_varliklar: list[str] = []

	def tearDown(self) -> None:
		for ad in self.olusturulan_varliklar:
			if frappe.db.exists(ret.MEDIA_ASSET, ad):
				frappe.delete_doc(ret.MEDIA_ASSET, ad, force=True, ignore_permissions=True)
		for ad in self.olusturulan_dosyalar:
			if frappe.db.exists("File", ad):
				frappe.delete_doc("File", ad, force=True, ignore_permissions=True,
					delete_permanently=True)
		frappe.db.commit()

	def dosya_yarat(self, etiket: str, yas_gun: float = YAS_GUN) -> dict:
		"""`File` kaydı + diskte gerçek dosya; mtime `yas_gun` kadar geriye alınır."""
		doc = frappe.get_doc({
			"doctype": "File",
			"file_name": f"{PREFIX}-{etiket}-{frappe.generate_hash(length=8)}.txt",
			"is_private": 0,
			"content": f"t053 {etiket}",
		})
		doc.insert(ignore_permissions=True)
		self.olusturulan_dosyalar.append(doc.name)
		yol = ret.disk_path_for(doc.file_url)
		self.assertIsNotNone(yol, "test dosyası disk yoluna çözülemedi")
		eski = time.time() - yas_gun * 86400
		os.utime(yol, (eski, eski))
		return {"name": doc.name, "file_url": doc.file_url, "path": yol}

	def varlik_yarat(self, dosya_adi: str, legal_hold: int) -> str:
		doc = frappe.get_doc({
			"doctype": ret.MEDIA_ASSET,
			"slot_key": "product-image",
			"media_type": "image",
			"state": "ready",
			"source_file": dosya_adi,
			ret.LEGAL_HOLD_DOCFIELD: legal_hold,
		})
		doc.insert(ignore_permissions=True)
		self.olusturulan_varliklar.append(doc.name)
		return doc.name

	def hold_ayarla(self, varlik: str, deger: int) -> None:
		"""`legal_hold` permlevel 1 — form yolu değil, doğrudan kolon yazılır."""
		frappe.db.set_value(ret.MEDIA_ASSET, varlik, ret.LEGAL_HOLD_DOCFIELD, deger)
		frappe.db.commit()


# ── 1. Kuru koşum hiçbir şeye dokunmuyor ───────────────────────────────


def _envanter_olcumu() -> tuple[int, int]:
	"""(`File` satır sayısı, public dosya dizininin toplam baytı)."""
	sayi = frappe.db.count("File")
	kok = os.path.join(frappe.get_site_path(), "public", "files")
	toplam = 0
	for dizin, _alt, dosyalar in os.walk(kok):
		for ad in dosyalar:
			try:
				toplam += os.path.getsize(os.path.join(dizin, ad))
			except OSError:
				continue
	return sayi, toplam


class TestKuruKosumDokunmuyor(GcTemeli):
	def test_agresif_politikayla_bile_hicbir_sey_silinmiyor(self) -> None:
		"""Ölçüm: koşum öncesi/sonrası dosya sayısı ve disk boyutu BİREBİR aynı."""
		self.dosya_yarat("kuru")
		once = _envanter_olcumu()
		rapor = ret.run_maintenance(policy=_politika(), dry_run=True)
		sonra = _envanter_olcumu()
		self.assertEqual(once, sonra, "kuru koşum envanteri değiştirdi")
		self.assertTrue(rapor["dry_run"])
		self.assertEqual(rapor["totals"]["deleted"], 0)
		self.assertEqual(rapor["totals"]["bytes_freed"], 0)

	def test_kuru_kosum_yine_de_aday_uretiyor(self) -> None:
		"""Karşı yön: "hiçbir şey silmedi" ile "hiç çalışmadı" aynı şey değil."""
		self.dosya_yarat("aday")
		rapor = ret.run_maintenance(policy=_politika(), dry_run=True)
		self.assertGreater(rapor["totals"]["candidates"], 0)
		self.assertGreater(rapor["totals"]["bytes_candidate"], 0)

	def test_varsayilan_politika_tek_aday_bile_uretmiyor(self) -> None:
		"""Şema varsayılanı `keep_forever` — üretimde koşan iş budur."""
		self.dosya_yarat("varsayilan")
		rapor = ret.run_maintenance(dry_run=True)
		self.assertEqual(rapor["totals"]["candidates"], 0)
		self.assertEqual(rapor["totals"]["deleted"], 0)
		self.assertIn(ret.REASON_KEEP_FOREVER, rapor["totals"]["skipped_by_reason"])

	def test_zamanlanmis_is_bayrak_kapaliyken_kuru(self) -> None:
		"""`site_config` bayrağı yokken zamanlanmış iş ıslak koşamaz."""
		self.assertFalse(frappe.conf.get(ret.ENFORCE_FLAG), "test ortamında bayrak açık olmamalı")
		once = _envanter_olcumu()
		rapor = ret.run_scheduled_gc()
		self.assertTrue(rapor["dry_run"])
		self.assertEqual(once, _envanter_olcumu())


# ── 2. Legal hold — iki yönlü ──────────────────────────────────────────


class TestLegalHold(GcTemeli):
	def test_tutulan_dosya_bloke_ediliyor(self) -> None:
		dosya = self.dosya_yarat("hold")
		self.varlik_yarat(dosya["name"], legal_hold=1)
		bolum = ret.sweep_originals(policy=_politika(), dry_run=True)
		karar = self._karar(bolum, dosya["file_url"])
		self.assertEqual(karar["action"], ret.ACTION_BLOCKED)
		self.assertEqual(karar["reason"], ret.REASON_LEGAL_HOLD)
		self.assertTrue(karar["held"])
		self.assertTrue(os.path.exists(dosya["path"]))

	def test_hold_kalkinca_ayni_is_ayni_dosyayi_aday_goruyor(self) -> None:
		"""Korumanın legal hold'dan geldiğinin kanıtı: tek değişken `legal_hold`."""
		dosya = self.dosya_yarat("hold-off")
		varlik = self.varlik_yarat(dosya["name"], legal_hold=1)

		tutuluyken = self._karar(ret.sweep_originals(policy=_politika(), dry_run=True),
			dosya["file_url"])
		self.hold_ayarla(varlik, 0)
		serbestken = self._karar(ret.sweep_originals(policy=_politika(), dry_run=True),
			dosya["file_url"])

		self.assertEqual(tutuluyken["action"], ret.ACTION_BLOCKED)
		self.assertEqual(serbestken["action"], ret.ACTION_DELETE)
		self.assertFalse(serbestken["held"])
		self.assertTrue(os.path.exists(dosya["path"]), "kuru koşum yine de silmemeli")

	def test_kapi_gercek_alandan_okuyor(self) -> None:
		"""`Media Asset.legal_hold` VAR, `File.th_legal_hold` YOK — ölçülmüş fark."""
		kapi = ret.MediaAssetLegalHold()
		self.assertTrue(kapi.enforceable, "Media Asset.legal_hold kolonu bulunamadı")
		self.assertFalse(ret.FrappeLegalHold().enforceable,
			"File.th_legal_hold beklenmedik biçimde var — kapı kaynağı gözden geçirilmeli")

	def test_tutulan_varlik_turevlerini_de_kapsiyor(self) -> None:
		dosya = self.dosya_yarat("hold-turev")
		varlik = self.varlik_yarat(dosya["name"], legal_hold=1)
		kapi = ret.MediaAssetLegalHold()
		self.assertIn(varlik, kapi.held_asset_names())
		self.assertIn(dosya["file_url"], kapi.held_urls())

	def test_kapi_uygulanamazsa_yikici_islem_durur(self) -> None:
		"""Kapı ölçülemiyorsa aday yine üretilir ama BLOKE sayılır — sessiz iptal yok."""

		class Kapisiz(ret.MediaAssetLegalHold):
			@property
			def enforceable(self) -> bool:
				return False

			def held_urls(self) -> set:
				return set()

		self.dosya_yarat("kapisiz")
		bolum = ret.sweep_originals(policy=_politika(), gate=Kapisiz(), dry_run=False)
		self.assertEqual(bolum.deleted, 0)
		self.assertGreater(bolum.blocked, 0)
		self.assertIn(ret.REASON_GATE_UNENFORCEABLE, bolum.skips)

	def _karar(self, bolum: ret.GcSection, url: str) -> dict:
		for ornek in bolum.samples:
			if ornek["url"] == url:
				return ornek
		self.fail(f"{url} için karar üretilmedi (taranan={bolum.scanned})")


# ── 3. Diskte olmayan `File` kaydı ─────────────────────────────────────


class TestEksikDosyaDayanikliligi(GcTemeli):
	def test_diskte_olmayan_kayit_gcyi_dusurmuyor(self) -> None:
		dosyalar = [self.dosya_yarat(f"eksik-{i}") for i in range(3)]
		for d in dosyalar:
			os.remove(d["path"])

		bolum = ret.sweep_originals(policy=_politika(), dry_run=True)
		self.assertGreaterEqual(bolum.skips.get(ret.REASON_MISSING_ON_DISK, 0), 3)
		for d in dosyalar:
			self.assertNotIn(d["file_url"], [s["url"] for s in bolum.samples],
				"diskte olmayan dosya aday listesine girdi")

	def test_canli_envanterde_eksik_kayit_zaten_var(self) -> None:
		"""Ölçüm doğrulaması: temiz kurulumda bile eksik kayıt var, senaryo kurgu değil."""
		bolum = ret.sweep_originals(dry_run=True)
		self.assertGreater(bolum.scanned, 0)
		self.assertIn(ret.REASON_MISSING_ON_DISK, bolum.skips)

	def test_bozuk_adres_karar_uretiyor_ama_patlamiyor(self) -> None:
		for adres in ("", "http://dis/kaynak.jpg", "/files/../../etc/passwd"):
			with self.subTest(adres=adres):
				aday = ret._original_candidate({"file_url": adres}, _politika(), set(), time.time())
				self.assertEqual(aday.action, ret.ACTION_KEEP)
				self.assertEqual(aday.reason, ret.REASON_NOT_A_FILE_URL)


# ── 4. `usage.py` kör noktası — `Brand.logo` ───────────────────────────


class TestKorNokta(unittest.TestCase):
	def test_brand_logo_artik_usage_listesinde(self) -> None:
		"""T-029 tuzağı KAPANDI: `Brand.logo` artık canlı kaynak (T-043, 2026-08-19).

		Bu test önceden tersini iddia ediyordu (`assertNotIn`) ve o gün doğruydu:
		`usage.py` alanı görmüyordu, koruma yalnız `retention.BLIND_SPOT_SOURCES`
		emniyet ağından geliyordu. Emniyet ağı GC'yi kurtarıyordu ama panel ve
		`trash.py` yolunu kurtarmıyordu — onlar `usage.verdict_map_all`'a bakıyor.
		Kalıcı çözüm `LIVE_SOURCES`'a eklemekti; emniyet ağı yerinde duruyor
		(aynı adresi iki kez korumak sorun değil).
		"""
		from tradehub_core.media import usage

		alanlar = {(t, c) for t, c, _k, _l in usage.LIVE_SOURCES}
		self.assertIn(("tabBrand", "logo"), alanlar)
		for beklenen in (
			("tabBrand", "hero_banner"),
			("tabProduct Category", "image"),
			("tabSeller Category", "image"),
			("tabAdmin Seller Profile", "banner_image"),
			("tabStatic Page SEO", "og_image"),
			("tabVerification Source", "icon"),
			("tabSeller Gallery Image", "poster_image"),
			("tabSeller Gallery Image", "video_url"),
		):
			self.assertIn(beklenen, alanlar, f"kör nokta kapanmamış: {beklenen}")

	def test_brand_logosu_kullanim_kararinda_in_use(self) -> None:
		"""Kararın kendisi düzeldi mi — emniyet ağı değil, `usage.py` cevabı."""
		from tradehub_core.media.usage import extract_file_urls, verdicts_for

		logolar = frappe.db.sql(
			"select logo from `tabBrand` where locate('/files/', logo) > 0", pluck=True)
		if not logolar:
			self.skipTest("bu sitede dosya adresli marka logosu yok")
		adresler = sorted({u for ham in logolar for u in extract_file_urls(ham)})
		kararlar = verdicts_for(adresler, deep=True)
		for url in adresler:
			self.assertEqual(kararlar[url]["verdict"], "in_use",
				f"marka logosu hâlâ kullanılmıyor görünüyor: {url}")

	def test_brand_logolari_koruma_kumesinde(self) -> None:
		korunan = ret.blind_spot_urls()
		logolar = frappe.db.sql(
			"select logo from `tabBrand` where locate('/files/', logo) > 0", pluck=True)
		if not logolar:
			self.skipTest("bu sitede dosya adresli marka logosu yok")
		from tradehub_core.media.usage import extract_file_urls

		for ham in logolar:
			for url in extract_file_urls(ham):
				self.assertIn(url, korunan, f"marka logosu koruma kümesinde değil: {url}")

	def test_kor_nokta_karari_kullanim_kararini_eziyor(self) -> None:
		"""`usage` "unused" dese bile türev politikası KORUMAYA düşüyor."""
		satir = {"name": "R1", "asset": "A1", "profile": "w96", "file_url": "/files/ab/x.webp",
			"bytes": 10, "generated_at": "2020-01-01 00:00:00"}
		aday = ret._derivative_candidate(
			satir,
			ret.RetentionPolicy.from_mapping({"derivative_retention": {"action": "delete"}}),
			set(),
			{"/files/ab/x.webp": ret.VERDICT_UNUSED},
			{"/files/ab/x.webp"},
			time.time(),
		)
		self.assertEqual(aday.action, ret.ACTION_KEEP)
		self.assertEqual(aday.reason, ret.REASON_BLIND_SPOT)

	def test_koruma_kumesi_disinda_ayni_satir_aday_oluyor(self) -> None:
		"""Karşı yön: koruma gerçekten kör nokta kümesinden geliyor."""
		satir = {"name": "R1", "asset": "A1", "profile": "w96", "file_url": "/files/ab/x.webp",
			"bytes": 10, "generated_at": "2020-01-01 00:00:00"}
		aday = ret._derivative_candidate(
			satir,
			ret.RetentionPolicy.from_mapping({"derivative_retention": {"action": "delete"}}),
			set(),
			{"/files/ab/x.webp": ret.VERDICT_UNUSED},
			set(),
			time.time(),
		)
		self.assertEqual(aday.action, ret.ACTION_DELETE)


# ── 5. Türev işi boş kümede ────────────────────────────────────────────


class TestTurevBosKume(unittest.TestCase):
	def test_rendition_tablosu_bos_ve_is_sifir_satirla_kosuyor(self) -> None:
		self.assertEqual(frappe.db.count(ret.MEDIA_RENDITION), 0,
			"tablo artık boş değil — bu testin varsayımı güncellenmeli")
		bolum = ret.sweep_derivatives(dry_run=True)
		self.assertEqual(bolum.scanned, 0)
		self.assertEqual(bolum.candidates, 0)
		self.assertEqual(bolum.to_dict()["skipped_by_reason"], {})

	def test_bakim_raporu_iki_bolum_ve_katman_bilgisi_tasiyor(self) -> None:
		rapor = ret.run_maintenance(dry_run=True, limit=25)
		self.assertEqual([b["policy"] for b in rapor["sections"]],
			[ret.POLICY_ORIGINAL, ret.POLICY_DERIVATIVE])
		self.assertIn("tiers", rapor)
		self.assertEqual(rapor["tiers"]["transitions"], {}, "kuru koşumda katman geçişi olmamalı")
		self.assertEqual(rapor["legal_hold"]["source"],
			f"{ret.MEDIA_ASSET}.{ret.LEGAL_HOLD_DOCFIELD}")

	def test_politika_bagimsiz_kaliyor(self) -> None:
		"""Orijinali silmeye açmak türev kararını DEĞİŞTİRMEMELİ (`retention.md` §6)."""
		pol = _politika()
		self.assertEqual(pol.derivative.action, ret.ACTION_NOTIFY)
		self.assertTrue(pol.derivative.regenerate_on_demand)


# ── 6. "İstendiğinde yeniden üret" sözü tutulabiliyor mu ───────────────


class TestYenidenUretim(unittest.TestCase):
	"""Silme kararı, türevin geri gelebilmesine BAĞLI olmalı."""

	SATIR = {"name": "R1", "asset": "A1", "profile": "w96", "file_url": "/files/ab/x.webp",
		"bytes": 10, "generated_at": "2020-01-01 00:00:00"}
	POLITIKA = ret.RetentionPolicy.from_mapping({"derivative_retention": {"action": "delete"}})

	def _karar(self, uretilebilir: bool) -> ret.GcCandidate:
		return ret._derivative_candidate(
			self.SATIR, self.POLITIKA, set(),
			{self.SATIR["file_url"]: ret.VERDICT_UNUSED}, set(), time.time(), uretilebilir,
		)

	def test_uretim_yolu_yoksa_silme_bildirime_dusuyor(self) -> None:
		aday = self._karar(False)
		self.assertEqual(aday.action, ret.ACTION_NOTIFY)
		self.assertEqual(aday.reason, ret.REASON_NO_REGENERATION)

	def test_uretim_yolu_varsa_silme_kararı_kaliyor(self) -> None:
		"""Karşı yön: düşüş gerçekten yeniden-üretilebilirlikten geliyor."""
		self.assertEqual(self._karar(True).action, ret.ACTION_DELETE)

	def test_bugun_uretim_yolu_kapali(self) -> None:
		"""Ölçüm: bayraklar kapalı — bu sitede türev yeniden üretilemez."""
		self.assertFalse(ret.regeneration_available(),
			"boru hattı bayrağı açılmış — türev silme politikası gözden geçirilmeli")


# ── 7. Orijinal tarafında kullanım kapısı (T-043/T-053, 2026-08-19) ────


class TestOrijinalKullanimKapisi(GcTemeli):
	"""Orijinal süpürücüsü önceden YALNIZ yaşa bakıyordu.

	`keep_forever=false` yazıldığı an, kullanımda olup olmadığına bakılmaksızın
	envanterin tamamı silme adayı oluyordu. Kör nokta koruması yalnız TÜREV
	tarafında vardı. Dört yön ölçülüyor: koruma var / koruma yok, ve ölçüm
	yapılamadığında ne oluyor.
	"""

	SATIR = {"file_url": "/files/kapı-testi.jpg", "file_size": 10}

	def _karar(self, **kw) -> ret.GcCandidate:
		return ret._original_candidate(self.SATIR, _politika(), set(), time.time(), **kw)

	def test_kullanimdaki_dosya_aday_olmuyor(self) -> None:
		aday = self._karar(in_use={self.SATIR["file_url"]})
		self.assertEqual(aday.action, ret.ACTION_KEEP)
		self.assertEqual(aday.reason, ret.REASON_IN_USE)

	def test_kor_nokta_kumesindeki_dosya_aday_olmuyor(self) -> None:
		aday = self._karar(guard={self.SATIR["file_url"]})
		self.assertEqual(aday.action, ret.ACTION_KEEP)
		self.assertEqual(aday.reason, ret.REASON_BLIND_SPOT)

	def test_kullanim_olculemezse_hicbir_sey_aday_olmuyor(self) -> None:
		"""Fail-safe: tarama patlarsa "hiçbir şey kullanılmıyor" varsayılamaz."""
		aday = self._karar(usage_known=False)
		self.assertEqual(aday.action, ret.ACTION_KEEP)
		self.assertEqual(aday.reason, ret.REASON_USAGE_UNKNOWN)

	def test_kapisiz_ayni_satir_yasina_gore_ilerliyor(self) -> None:
		"""Karşı yön: koruma gerçekten bu üç kapıdan geliyor, yaştan değil."""
		aday = self._karar()
		self.assertNotIn(aday.reason,
			(ret.REASON_IN_USE, ret.REASON_BLIND_SPOT, ret.REASON_USAGE_UNKNOWN))

	def test_kullanimdaki_gercek_dosya_agresif_politikada_bile_korunuyor(self) -> None:
		"""Canlı envanterde ölçüm: bir ürünün ana görseli aday listesine giremez."""
		adres = frappe.db.sql(
			"""select primary_image from `tabListing`
			where locate('/files/', primary_image) > 0 limit 1""", pluck=True)
		if not adres:
			self.skipTest("bu sitede dosya adresli ürün ana görseli yok")
		from tradehub_core.media.usage import extract_file_urls

		urls = extract_file_urls(adres[0])
		self.assertTrue(urls, "ana görsel adresi ayrıştırılamadı")
		kullanilan, olculdu = ret.live_usage_urls()
		self.assertTrue(olculdu, "kullanım taraması ölçülemedi")
		# Not: dosya `File` envanterinde olmayabilir (private/hariç doctype);
		# ölçülen şey kullanım kümesinin o adresi TAŞIDIĞI.
		self.assertTrue(urls & kullanilan,
			f"canlı ürün görseli kullanım kümesinde yok: {sorted(urls)}")

	def test_canli_envanterde_kullanimdaki_dosya_keep_in_use_aliyor(self) -> None:
		"""Uçtan uca: gerçek `File` satırı + gerçek kullanım kümesi + agresif politika.

		Bu testin yalnız `live_usage_urls()`'a bakan kardeşinden farkı, kararın
		kendisini ölçmesi: küme doğru olsa bile kapı `_original_candidate`
		içinde bağlanmamış olabilir.
		"""
		kullanilan, olculdu = ret.live_usage_urls()
		self.assertTrue(olculdu)
		satir = None
		for aday in ret._file_rows(limit=0):
			if str(aday.get("file_url") or "").split("?")[0] in kullanilan:
				satir = aday
				break
		if satir is None:
			self.skipTest("GC kapsamında kullanımda olan dosya yok")

		koruma = ret.blind_spot_urls()
		karar = ret._original_candidate(
			satir, _politika(), set(), time.time(),
			guard=koruma, in_use=kullanilan, usage_known=True)
		self.assertEqual(karar.action, ret.ACTION_KEEP)
		self.assertIn(karar.reason, (ret.REASON_IN_USE, ret.REASON_BLIND_SPOT))

		# Karşı yön: aynı satır, kapılar kapalı → korunma sebebi ortadan kalkıyor.
		kapisiz = ret._original_candidate(satir, _politika(), set(), time.time())
		self.assertNotIn(kapisiz.reason, (ret.REASON_IN_USE, ret.REASON_BLIND_SPOT))

	def test_kullanim_kumesi_bos_degil(self) -> None:
		"""Vacuity: kapının koruduğu bir şey gerçekten var mı."""
		kullanilan, olculdu = ret.live_usage_urls()
		self.assertTrue(olculdu)
		self.assertGreater(len(kullanilan), 0, "hiçbir dosya kullanımda görünmüyor — tarama şüpheli")


# ── 8. Orijinal ve türev için AYRI zamanlanmış işler (T-053 kriter 1) ──


class TestAyriZamanlanmisIsler(GcTemeli):
	def test_iki_is_ayri_bayrak_ve_ayri_kilit_kullaniyor(self) -> None:
		self.assertNotEqual(ret.ENFORCE_FLAG_ORIGINALS, ret.ENFORCE_FLAG_DERIVATIVES)
		self.assertNotEqual(ret.LOCK_ORIGINALS, ret.LOCK_DERIVATIVES)
		self.assertNotIn(ret.LOCK_ALL, (ret.LOCK_ORIGINALS, ret.LOCK_DERIVATIVES))

	def test_bayraklar_bugun_kapali(self) -> None:
		"""Talimat: bayraklar 0 kalsın. Ölçüm, iddia değil."""
		for bayrak in (ret.ENFORCE_FLAG, ret.ENFORCE_FLAG_ORIGINALS, ret.ENFORCE_FLAG_DERIVATIVES):
			self.assertFalse(frappe.conf.get(bayrak), f"{bayrak} açık")

	def test_orijinal_isi_tek_politika_raporluyor_ve_kuru_kosuyor(self) -> None:
		self.dosya_yarat("ayri-orijinal")
		once = _envanter_olcumu()
		rapor = ret.run_scheduled_gc_originals()
		self.assertEqual(rapor["policy_name"], ret.POLICY_ORIGINAL)
		self.assertEqual([b["policy"] for b in rapor["sections"]], [ret.POLICY_ORIGINAL])
		self.assertTrue(rapor["dry_run"])
		self.assertEqual(rapor["totals"]["deleted"], 0)
		self.assertEqual(once, _envanter_olcumu(), "orijinal işi envanteri değiştirdi")

	def test_turev_isi_tek_politika_raporluyor_ve_kuru_kosuyor(self) -> None:
		once = _envanter_olcumu()
		rapor = ret.run_scheduled_gc_derivatives()
		self.assertEqual(rapor["policy_name"], ret.POLICY_DERIVATIVE)
		self.assertEqual([b["policy"] for b in rapor["sections"]], [ret.POLICY_DERIVATIVE])
		self.assertTrue(rapor["dry_run"])
		self.assertEqual(rapor["totals"]["deleted"], 0)
		self.assertEqual(once, _envanter_olcumu(), "türev işi envanteri değiştirdi")

	def test_kilit_tutulunca_is_atlaniyor(self) -> None:
		"""Eşzamanlılık: aynı iş iki kez koşamaz."""
		frappe.cache().set_value(ret.LOCK_ORIGINALS, 1, expires_in_sec=30)
		try:
			rapor = ret.run_scheduled_gc_originals()
			self.assertEqual(rapor.get("skipped"), "locked")
		finally:
			frappe.cache().delete_value(ret.LOCK_ORIGINALS)

	def test_bir_isin_kilidi_digerini_engellemiyor(self) -> None:
		"""Karşı yön: kilitler gerçekten ayrı."""
		frappe.cache().set_value(ret.LOCK_ORIGINALS, 1, expires_in_sec=30)
		try:
			rapor = ret.run_scheduled_gc_derivatives()
			self.assertNotEqual(rapor.get("skipped"), "locked")
		finally:
			frappe.cache().delete_value(ret.LOCK_ORIGINALS)

	def test_ayri_gc_isleri_hooks_pyde_kayitli(self) -> None:
		"""Şerit A kaydı YAPILDI — testin yönü ters çevrildi.

		Bu test önce kaydın OLMADIĞINI sabitliyordu (`test_hooks_kaydi_henuz_yok`):
		"kayıt yapıldığı gün kırmızı olsun ve raporun güncellenmesi gerektiğini
		söylesin". Kayıt 2026-08-19'da yapıldı, test kırmızı oldu ve yönü
		çevrildi — el sıkışma tam olarak böyle çalışmalıydı
		(docs/reports/50-serit-a-kablolama.md).

		Birleşik iş BİLEREK duruyor: `hooks.py` diff'i 0 silme kuralı altında
		çalışıldı ve üç iş de varsayılan kuru koşumda. Islak koşuma geçilirken
		birleşik kayıt kaldırılmalı — o gün bu testin son satırı da düşer.
		"""
		from tradehub_core import hooks

		gunluk = list(hooks.scheduler_events.get("daily", []))
		for is_adi in ("run_scheduled_gc_originals", "run_scheduled_gc_derivatives"):
			self.assertIn(
				f"tradehub_core.media.pipeline.storage.retention.{is_adi}", gunluk,
				f"{is_adi} hooks.py'de kayıtlı DEĞİL — ayrı GC işi hiç koşmaz")
		self.assertIn(
			"tradehub_core.media.pipeline.storage.retention.run_scheduled_gc", gunluk,
			"birleşik iş kaydı silinmiş — `hooks.py` 0 silme kuralı bozuldu ya da "
			"ıslak koşuma geçildi; ikincisiyse bu satır kaldırılmalı")

	def test_uc_gc_isinin_bayraklari_ayri(self) -> None:
		"""Üç işin bayrağı ve kilidi AYRI olmalı — biri diğerini açmamalı.

		`hooks.py`ye üç iş birden kayıtlı; ortak bayrak/kilit olsaydı kayıt
		kararı sessizce "hepsini aç" anlamına gelirdi.
		"""
		from tradehub_core.media.pipeline.storage import retention as ret

		bayraklar = {ret.ENFORCE_FLAG, ret.ENFORCE_FLAG_ORIGINALS,
					 ret.ENFORCE_FLAG_DERIVATIVES}
		kilitler = {ret.LOCK_ALL, ret.LOCK_ORIGINALS, ret.LOCK_DERIVATIVES}
		self.assertEqual(len(bayraklar), 3, f"bayraklar ayrışmıyor: {bayraklar}")
		self.assertEqual(len(kilitler), 3, f"kilitler ayrışmıyor: {kilitler}")


if __name__ == "__main__":  # pragma: no cover
	unittest.main(verbosity=2)
