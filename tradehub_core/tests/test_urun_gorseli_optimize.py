"""Ürün görsellerini tek düğmeyle optimize et — orkestratör (2026-09-30)."""

import io
import json
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tradehub_core.api import media_admin
from tradehub_core.media import kare, magaza_gorseli, retro_rename
from tradehub_core.media import urun_gorseli_optimize as opt

# AV bekletmesi dosyayı public ağaçtan çıkarmasın (bkz. tests/av_notr.py).
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401

_TAMAM = [{"key": "profiles_enabled", "ok": True, "message": "ok"}]
_HATALI = [{"key": "profiles_enabled", "ok": False, "message": "product.image profili kapalı: w192"}]


class TestUrunGorseliOptimize(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.sfx = frappe.generate_hash(length=8)
		self._eski_kayit = frappe.db.get_value(
			"DefaultValue", {"parent": "__global", "defkey": opt.RUNS_KEY}, "defvalue"
		)
		self.addCleanup(self._temizle)
		self.anahtarlar: list[str] = []

	def _temizle(self):
		for k in self.anahtarlar:
			retro_rename.release_active(k)
			frappe.cache.delete_value(retro_rename._stop_key(k))
		opt._kosulari_yaz(self._eski_kayit)
		frappe.db.commit()

	def _anahtar(self) -> str:
		k = f"{opt.JOB_PREFIX}t{self.sfx}{len(self.anahtarlar)}"
		self.anahtarlar.append(k)
		return k

	def _kosu_hazirla(self, dry_run: bool) -> str:
		k = self._anahtar()
		opt._kaydet(opt._yeni_durum(k, dry_run))
		self.assertTrue(retro_rename.claim_active(k, ttl=120))
		return k

	def _sahte_adimlar(self, kayit: list, **ozel):
		def yap(ad):
			def f(durum):
				kayit.append(ad)
				if ad in ozel:
					ozel[ad](durum)
				else:
					opt._adim(durum, ad)["state"] = "done"

			return f

		return mock.patch.dict(opt._ADIM_FONKSIYONLARI, {a: yap(a) for a in opt.ADIMLAR[1:]})

	# ── sıra ──

	def test_adimlar_sirayla_kosar(self):
		kayit: list = []
		k = self._kosu_hazirla(dry_run=False)
		with self._sahte_adimlar(kayit), mock.patch.object(opt, "on_kontroller", return_value=_TAMAM):
			opt.run_job(k, dry_run=0)
		self.assertEqual(kayit, ["kare", "magaza", "seo_ad", "meta", "turev", "magaza_turev"])
		durum = opt.kosu(k)
		self.assertEqual(durum["state"], "completed")
		self.assertEqual([a["key"] for a in durum["steps"]], list(opt.ADIMLAR))
		self.assertTrue(all(a["state"] == "done" for a in durum["steps"]))
		# Kilit bırakıldı.
		self.assertFalse(frappe.cache.exists(retro_rename.ACTIVE_KEY))

	# ── kuyruk düşüşü (prod: medya kuyrukları tanımsız) ──

	def test_bulk_kuyrugu_tanimsizken_turevler_bu_iste_uretilir(self):
		"""Ebeveyn `long`'da; çocukları `long`'a atıp beklemek tek worker'da kilitlenirdi."""
		k = self._kosu_hazirla(dry_run=False)
		durum = opt.kosu(k)
		dosya = frappe._dict(name="F-1", file_url="/files/a.webp", owner="x@example.com")
		with (
			mock.patch.object(opt.queue_fallback, "is_configured", return_value=False),
			mock.patch.object(opt, "_kuyrugun_bosalmasini_bekle", return_value=True),
			mock.patch.object(opt, "_urun_dosyalari", return_value=[dosya]),
			mock.patch.object(opt, "_slotta_mi", return_value=("would_generate", "")),
			mock.patch.object(
				opt.rendition_backfill, "_process_file", return_value=("generated", "")
			) as uret,
			mock.patch.object(frappe, "enqueue") as kuyruk,
		):
			opt._turevleri_uret(durum, "turev", ["/files/a.webp"], (opt.SLOT,))
		kuyruk.assert_not_called()
		uret.assert_called_once_with("F-1", slot_only=(opt.SLOT,))
		adim = opt._adim(durum, "turev")
		self.assertEqual((adim["changed"], adim["failed"], adim["state"]), (1, 0, "done"))

	def test_worker_kontrolu_dusus_kuyrugunu_sayar(self):
		with (
			mock.patch.object(opt.queue_fallback, "resolve_queue", return_value="long"),
			mock.patch.object(opt, "_worker_sayisi", return_value=2),
		):
			kontroller = {k["key"]: k for k in opt.on_kontroller()}
		live = kontroller["workers_media_image_live"]
		self.assertTrue(live["ok"])
		self.assertIn("media-image-live → long", live["message"])

	# ── ön kontrol ──

	def test_on_kontrol_hatasi_gercek_kosuyu_durdurur(self):
		kayit: list = []
		k = self._kosu_hazirla(dry_run=False)
		with self._sahte_adimlar(kayit), mock.patch.object(opt, "on_kontroller", return_value=_HATALI):
			opt.run_job(k, dry_run=0)
		self.assertEqual(kayit, [])
		durum = opt.kosu(k)
		self.assertEqual(durum["state"], "error")
		self.assertIn("w192", durum["message"])
		self.assertTrue(all(a["state"] == "skipped" for a in durum["steps"][1:]))

	def test_on_kontrol_hatasi_provayi_durdurmaz_ama_raporlar(self):
		kayit: list = []
		k = self._kosu_hazirla(dry_run=True)
		with self._sahte_adimlar(kayit), mock.patch.object(opt, "on_kontroller", return_value=_HATALI):
			opt.run_job(k, dry_run=1)
		self.assertEqual(kayit, ["kare", "magaza", "seo_ad", "meta", "turev", "magaza_turev"])
		durum = opt.kosu(k)
		self.assertEqual(durum["state"], "partial")
		self.assertEqual(durum["steps"][0]["state"], "error")
		self.assertEqual(durum["steps"][0]["reasons"], {"profiles_enabled": 1})

	def test_baslat_on_kontrol_hatasinda_is_acmaz(self):
		prova = self._kosu_hazirla(dry_run=True)
		retro_rename.release_active(prova)
		d = opt.kosu(prova)
		d.update(state="completed", finished_at=str(frappe.utils.now_datetime()))
		opt._kaydet(d)
		with (
			mock.patch.object(opt, "on_kontroller", return_value=_HATALI),
			mock.patch.object(frappe, "enqueue") as kuyruk,
		):
			with self.assertRaises(frappe.ValidationError):
				opt.baslat(dry_run=False, prova_key=prova)
		kuyruk.assert_not_called()
		self.assertFalse(frappe.cache.exists(retro_rename.ACTIVE_KEY))

	def test_prova_olmadan_gercek_kosu_reddedilir(self):
		with mock.patch.object(frappe, "enqueue") as kuyruk:
			with self.assertRaises(frappe.ValidationError):
				opt.baslat(dry_run=False, prova_key="")
			with self.assertRaises(frappe.ValidationError):
				opt.baslat(dry_run=False, prova_key="kare-opt-yok")
		kuyruk.assert_not_called()

	def test_profil_kontrolu_politikadaki_profillere_bakar(self):
		kontroller = opt.on_kontroller()
		profil = next(c for c in kontroller if c["key"] == "profiles_enabled")
		politika = opt._politika_profilleri()
		self.assertEqual(politika, {"w192", "w384", "w768", "w1280"})
		acik = set(
			frappe.get_all(
				"Media Profile", filters={"slot_key": "product.image", "enabled": 1}, pluck="policy_profile"
			)
		)
		self.assertEqual(profil["ok"], politika <= acik)
		# Kill switch kontrolü conf'u okur.
		frappe.conf[opt.KILL_SWITCH] = 1
		self.addCleanup(lambda: frappe.conf.pop(opt.KILL_SWITCH, None))
		kill = next(c for c in opt.on_kontroller() if c["key"] == "kill_switch")
		self.assertFalse(kill["ok"])

	# ── prova hiçbir şey yazmaz (gerçek adım fonksiyonları) ──

	def test_prova_hicbir_sey_yazmaz(self):
		buf = io.BytesIO()
		Image.new("RGB", (1200, 800), (10, 20, 30)).save(buf, "JPEG", quality=90, comment=self.sfx.encode())
		f = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"opt-prova-{self.sfx}.jpg",
				"content": buf.getvalue(),
				"is_private": 0,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("File", f.name, {"th_media_width": 0, "th_media_height": 0})
		frappe.db.commit()
		self.addCleanup(lambda: frappe.delete_doc("File", f.name, force=True, ignore_permissions=True))
		urls = [f.file_url, f"/files/opt-yok-{self.sfx}.jpg"]
		redirect_oncesi = frappe.db.count("Media URL Redirect")
		file_oncesi = frappe.db.get_value("File", f.name, ["file_url", "modified"], as_dict=True)
		k = self._kosu_hazirla(dry_run=True)
		with (
			mock.patch.object(kare, "aday_urls", return_value=urls),
			mock.patch.object(magaza_gorseli, "aday_urls", return_value=urls),
			mock.patch.object(opt, "_worker_sayisi", return_value=1),
			mock.patch.object(frappe, "enqueue") as kuyruk,
		):
			opt.run_job(k, dry_run=1)
		kuyruk.assert_not_called()
		self.assertEqual(frappe.db.count("Media URL Redirect"), redirect_oncesi)
		sonra = frappe.db.get_value("File", f.name, ["file_url", "modified", "th_media_width"], as_dict=True)
		self.assertEqual(sonra.file_url, file_oncesi.file_url)
		self.assertEqual(sonra.modified, file_oncesi.modified)
		self.assertEqual(int(sonra.th_media_width or 0), 0)
		durum = opt.kosu(k)
		self.assertTrue(durum["dry_run"])
		self.assertIn(durum["state"], ("completed", "partial"))
		kare_adim = opt._adim(durum, "kare")
		self.assertEqual(kare_adim["total"], 2)
		# Ürüne bağlı değil + diskte yok: ikisi de atlanır, hiçbiri çevrilmez.
		self.assertEqual(kare_adim["changed"], 0)
		self.assertEqual(kare_adim["reasons"], {"not_product": 1, "disk_missing": 1})
		# Mağaza adımı aynı adresleri kendi kuralıyla sayar: mağaza görseli değil + diskte yok.
		magaza_adim = opt._adim(durum, "magaza")
		self.assertEqual(magaza_adim["changed"], 0)
		self.assertEqual(magaza_adim["reasons"], {"not_store_image": 1, "disk_missing": 1})
		meta = opt._adim(durum, "meta")
		self.assertEqual(meta["changed"], 1)  # ölçü YAZILACAK ama yazılmadı
		self.assertLessEqual(set(opt._adim(durum, "seo_ad")["reasons"]), {"handled_by_kare"})

	# ── durdur ──

	def test_durdur_sonraki_adimlari_atlar(self):
		kayit: list = []
		k = self._kosu_hazirla(dry_run=False)

		def kare_durdur(durum):
			opt.durdur(durum["job_key"])
			opt._adim(durum, "kare")["state"] = "done"

		with (
			self._sahte_adimlar(kayit, kare=kare_durdur),
			mock.patch.object(opt, "on_kontroller", return_value=_TAMAM),
		):
			opt.run_job(k, dry_run=0)
		self.assertEqual(kayit, ["kare"])
		durum = opt.kosu(k)
		self.assertEqual(durum["state"], "stopped")
		self.assertEqual([a["state"] for a in durum["steps"][2:]], ["skipped"] * (len(opt.ADIMLAR) - 2))
		# Durdurma bayrağı tüketildi.
		self.assertFalse(retro_rename._stop_requested(k))

	# ── geri al ──

	def _gercek_kosu(self, degisen: int) -> str:
		k = self._anahtar()
		d = opt._yeni_durum(k, False)
		d["state"] = "completed"
		d["finished_at"] = str(frappe.utils.now_datetime())
		for a in d["steps"]:
			a["state"] = "done"
		opt._adim(d, "kare")["changed"] = degisen
		opt._kaydet(d)
		return k

	def test_geri_al_adimlari_ters_sirada_kendi_geri_almasiyla(self):
		k = self._gercek_kosu(degisen=3)
		cagrilar: list = []

		def sahte_kare_rollback(job_key, rollback_key):
			cagrilar.append(("kare", job_key, rollback_key))
			self.assertTrue(retro_rename.acquire_or_refresh_active(rollback_key))
			retro_rename._write_progress(
				rollback_key, {"state": "completed", "renamed": 3, "errors": 0, "skip_reasons": {}}
			)
			retro_rename.release_active(rollback_key)

		def hemen(method, **kw):
			self.anahtarlar.append(kw.get("rollback_key"))
			frappe.get_attr(method)(**{a: kw[a] for a in ("job_key", "rollback_key")})

		with (
			mock.patch.object(kare, "run_rollback", side_effect=sahte_kare_rollback),
			mock.patch.object(frappe, "enqueue", side_effect=hemen),
		):
			sonuc = opt.geri_al(k)
		# Önce mağaza adımının (`<iş>-mg` etiketli) satırları, sonra kare satırları.
		self.assertEqual(
			cagrilar,
			[("kare", opt.magaza_satir_anahtari(k), sonuc["job_key"]), ("kare", k, sonuc["job_key"])],
		)
		rb = opt.kosu(sonuc["job_key"])
		self.assertEqual(rb["mode"], "rollback")
		self.assertEqual(rb["state"], "completed")
		# Geri alınabilir adımlar ADIMLAR sırasının tersinde.
		sira = [a["key"] for a in rb["steps"]]
		self.assertEqual(sira, sorted(sira, key=opt.ADIMLAR.index, reverse=True))
		self.assertEqual(opt.kosu(k)["rolled_back_by"], sonuc["job_key"])
		with self.assertRaises(frappe.ValidationError):
			opt.geri_al(k)  # ikinci kez geri alınmaz

	def test_prova_ve_degisiksiz_kosu_geri_alinamaz(self):
		prova = self._kosu_hazirla(dry_run=True)
		retro_rename.release_active(prova)
		self.assertFalse(opt.geri_alinabilir(opt.kosu(prova)))
		self.assertFalse(opt.geri_alinabilir(opt.kosu(self._gercek_kosu(degisen=0))))
		self.assertTrue(opt.geri_alinabilir(opt.kosu(self._gercek_kosu(degisen=1))))

	# ── ortak kilit ──

	def test_kilit_tekil_islerle_ortak(self):
		# Kare kartı işi kilidi tutarken tek düğme başlamaz…
		baska = f"kare-test-{self.sfx}"
		self.anahtarlar.append(baska)
		self.assertTrue(retro_rename.claim_active(baska, ttl=60))
		with mock.patch.object(frappe, "enqueue") as kuyruk:
			with self.assertRaises(frappe.ValidationError):
				opt.baslat(dry_run=True)
		kuyruk.assert_not_called()
		retro_rename.release_active(baska)

		# …tek düğme kilidi tutarken de kare / retro-rename kartları başlamaz.
		with mock.patch.object(frappe, "enqueue"):
			sonuc = opt.baslat(dry_run=True)
		self.anahtarlar.append(sonuc["job_key"])
		with (
			mock.patch.object(kare, "aday_urls", return_value=["/files/x.jpg"]),
			mock.patch.object(retro_rename, "legacy_urls", return_value=["/files/x.jpg"]),
			mock.patch.object(frappe, "enqueue") as kuyruk,
		):
			with self.assertRaises(frappe.ValidationError):
				media_admin.start_square(dry_run=1)
			with self.assertRaises(frappe.ValidationError):
				media_admin.start_retro_rename(dry_run=1)
		kuyruk.assert_not_called()

		# İş, kilidi başka sahip tutuyorsa hiçbir adım koşmadan hata yazar.
		retro_rename.release_active(sonuc["job_key"])
		self.assertTrue(retro_rename.claim_active(baska, ttl=60))
		kayit: list = []
		with self._sahte_adimlar(kayit):
			opt.run_job(sonuc["job_key"], dry_run=1)
		self.assertEqual(kayit, [])
		self.assertEqual(opt.kosu(sonuc["job_key"])["state"], "error")

	def test_durum_ucu_son_kosuyu_ve_geri_alinabilirligi_dondurur(self):
		k = self._gercek_kosu(degisen=2)
		d = media_admin.get_product_image_optimize_status()
		self.assertEqual(d["run"]["job_key"], k)
		self.assertEqual(d["last_real"]["job_key"], k)
		self.assertTrue(d["rollback_available"])
		self.assertEqual(json.loads(json.dumps(d))["run"]["steps"][1]["changed"], 2)
