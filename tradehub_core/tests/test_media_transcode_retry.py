"""Video transcode retry + dead-letter + görünürlük testleri (TUR-296).

Kapsam — istenen test eksenlerine göre:

  Unit          : sayaç artışı, retry kuyruklama, dead-letter eşiği,
                  `retry_failed` durum kuralları, `enqueue_transcode` sıfırlama
  Integration   : `inventory.list_files` çıktısında `video_status`
  API           : `seller_media.retry_video`, `media_admin.retry_transcode`
  Database      : sayaç kalıcılığı, patch idempotency
  Auth          : uçlar `@frappe.whitelist` — Guest'e kapalı (varsayılan)
  Authorization : sahiplik (satıcı) ve rol (yönetici) reddi
  Validation    : failed olmayan durumda ret, olmayan/bozuk dosya adresi (monkey)
  E2E           : upload → processing → 3 hata → failed → elle retry → ready
  Error/recovery: ffmpeg yokluğu, geçici dosya temizliği, kuyruktayken silinen dosya

`subprocess.run` ve `frappe.enqueue` HER ZAMAN mock'lanır: gerçek ffmpeg
çağrılmaz, gerçek RQ kuyruğuna iş atılmaz (dev konteynerdeki worker'lar test
dosyasını gerçekten işlemeye kalkardı).

    docker exec -w /home/frappe/frappe-bench istoc-backend bench \
        --site tradehub.localhost run-tests \
        --module tradehub_core.tests.test_media_transcode_retry
"""

from __future__ import annotations

import contextlib
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from tradehub_core.api import media_admin, seller_media
from tradehub_core.media import inventory, jobs, transcode

# Koşum başına benzersiz tuz. Dosya adına göre türetmek YETMİYOR: içerik-adresli
# adlandırma (WP4, `media/naming.py`) aynı baytları aynı `file_url`'e eşliyor ve
# testler `frappe.db.commit()` çağıran kod yollarına (transcode, süpürücü)
# girdiği için kayıtlar veritabanında KALICI oluyor. Tuz olmadan bir sonraki
# koşum, geçen koşumun artığıyla aynı adresi paylaşıyor ve "kuyruktayken silinen
# dosya" gibi testler eski kaydı buluyordu (yaşandı: 29 artık kayıt birikmişti).
_KOSUM_TUZU: str = frappe.generate_hash(length=12)


def _yeni_video_dosyasi(file_name: str, content: bytes | None = None):
	icerik = (
		content
		if content is not None
		else f"sahte video icerigi {_KOSUM_TUZU} {file_name}".encode()
	)
	doc = frappe.get_doc(
		{"doctype": "File", "file_name": file_name, "is_private": 0, "content": icerik}
	)
	doc.insert(ignore_permissions=True)
	return doc


_SUPURUCU_ALANLARI: tuple[str, ...] = (
	"th_media_video_status",
	"th_media_transcode_attempts",
	"th_media_transcode_next_at",
	"th_media_transcode_started_at",
)


@contextlib.contextmanager
def _supurucu_izole(*korunacak: str):
	"""Süpürücüyü koştur ama TEST KAYITLARININ DIŞINDAKİ satırları geri koy.

	Süpürücü tanımı gereği tüm envanteri tarar ve `frappe.db.commit()` çağırır —
	yani bir test koşumu, o an gerçekten işlenmeyi bekleyen dosyaların
	damgalarını da değiştirir. Üstüne testte `frappe.enqueue` mock'lu olduğu
	için o dosyalar "kuyruğa kondu" diye işaretlenip aslında kuyruğa hiç
	girmez; kayıp iş eşiğine (45 dk) kadar askıda kalırlar. Yaşandı: local'de
	elle tetiklenmiş iki retry test koşumunda kaybolmuştu.

	`FrappeTestCase`'in teardown rollback'i burada işe yaramıyor: süpürücünün
	kendi commit'i değişikliği kalıcı yapıyor.
	"""
	korunan = set(korunacak)
	oncesi = {
		r.name: {alan: r.get(alan) for alan in _SUPURUCU_ALANLARI}
		for r in frappe.get_all(
			"File",
			filters={"th_media_video_status": transcode.VIDEO_STATUS_PROCESSING},
			fields=["name", *_SUPURUCU_ALANLARI],
			limit=500,
		)
		if r.name not in korunan
	}
	try:
		with mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue:
			yield mock_enqueue
	finally:
		for ad, degerler in oncesi.items():
			frappe.db.set_value("File", ad, degerler, update_modified=False)
		frappe.db.commit()


def _durum(name: str) -> str | None:
	return frappe.db.get_value("File", name, "th_media_video_status")


def _deneme(name: str) -> int:
	return int(frappe.db.get_value("File", name, "th_media_transcode_attempts") or 0)



def _av_notr(test):
	"""Bu birim testleri transcode MEKANİĞİNİ sınar; AV kesişimi ayrı kapsamda.

	Konteynerde ClamAV kurulu olduğunda `hold_until_clean` gerçekten aktif ve
	testin yüklediği dosya insert ANINDA bekletmeye taşınıyor — `_run_transcode`
	de (doğru davranarak) işi erteliyor, ffmpeg mock'una hiç ulaşılmıyor.
	Kesişim davranışının kendi testleri var (`test_media_av.TestModulKesisimleri`);
	burada nötrlenir ki bu dosya tarayıcının kurulu olup olmamasına göre iki
	farklı sonuç vermesin.
	"""
	for hedef in ("in_hold", "in_quarantine"):
		y = mock.patch(f"tradehub_core.media.av.{hedef}", return_value=False)
		y.start()
		test.addCleanup(y.stop)

class TestRetrySayaci(FrappeTestCase):
	"""Unit — başarısız denemeler sayılır, hak bitince dead-letter."""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("retry-sayac-1.mp4")
		_av_notr(self)
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def _basarisiz_calistir(self):
		with (
			mock.patch(
				"tradehub_core.media.transcode.subprocess.run",
				side_effect=Exception("ffmpeg patladı"),
			),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue,
		):
			transcode._run_transcode(self.doc.file_url)
		return mock_enqueue

	def test_ilk_hata_sayaci_bir_yapar_ve_processing_tutar(self):
		self._basarisiz_calistir()
		self.assertEqual(_deneme(self.doc.name), 1)
		self.assertNotEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_FAILED)

	def test_hata_kuyruga_ANINDA_geri_koymaz_deneme_planlar(self):
		"""Backoff: hata anında `enqueue` çağrılmaz, `next_at` damgası yazılır.

		`frappe.enqueue`'un gecikme parametresi yok (v15); bekleme damga
		üzerinden yürütülüyor ve işi süpürücü alıyor. Anında kuyruğa koymak
		üç hakkı saniyeler içinde yakardı.
		"""
		mock_enqueue = self._basarisiz_calistir()
		mock_enqueue.assert_not_called()

		next_at = frappe.db.get_value("File", self.doc.name, "th_media_transcode_next_at")
		self.assertTrue(next_at, "ilk hatadan sonra deneme planlanmalı")
		# Damga geleceğe bakmalı — geçmişse süpürücü onu hemen alır, backoff yok olur.
		self.assertFalse(jobs.is_due(next_at))

	def test_backoff_denemeyle_birlikte_uzuyor(self):
		# Politika: ikinci bekleme birinciden uzun (hâlâ düzelmediyse sistemsel).
		self.assertGreater(jobs.backoff_seconds(2), jobs.backoff_seconds(1))
		# Liste bitse bile IndexError yok — son değer tekrarlanır.
		self.assertEqual(
			jobs.backoff_seconds(99), jobs.backoff_seconds(len(jobs.BACKOFF_SECONDS))
		)

	def test_hak_bitince_failed_yazilir_ve_kuyruga_geri_konmaz(self):
		# Son deneme: sayaç MAX-1'de → bu hata dead-letter'a düşürmeli.
		frappe.db.set_value(
			"File",
			self.doc.name,
			"th_media_transcode_attempts",
			transcode.MAX_TRANSCODE_ATTEMPTS - 1,
		)
		mock_enqueue = self._basarisiz_calistir()
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_FAILED)
		self.assertEqual(_deneme(self.doc.name), transcode.MAX_TRANSCODE_ATTEMPTS)
		mock_enqueue.assert_not_called()

	def test_dead_letter_audit_kaydinda_deneme_sayisi_var(self):
		frappe.db.set_value(
			"File",
			self.doc.name,
			"th_media_transcode_attempts",
			transcode.MAX_TRANSCODE_ATTEMPTS - 1,
		)
		with (
			mock.patch(
				"tradehub_core.media.transcode.subprocess.run",
				side_effect=Exception("ffmpeg patladı"),
			),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
			mock.patch("tradehub_core.media.transcode.audit.log_media_event") as mock_audit,
		):
			transcode._run_transcode(self.doc.file_url)

		mock_audit.assert_called_once()
		_args, kwargs = mock_audit.call_args
		self.assertIn("video_transcode_failed", kwargs.get("reason") or "")
		self.assertEqual(
			(kwargs.get("context") or {}).get("attempts"), transcode.MAX_TRANSCODE_ATTEMPTS
		)

	def test_enqueue_transcode_sayaci_sifirlar(self):
		# Önceki işten sayaç kalmış olsun — yeni yükleme temiz başlamalı.
		frappe.db.set_value("File", self.doc.name, "th_media_transcode_attempts", 2)
		with (
			mock.patch("tradehub_core.media.transcode.needs_transcode", return_value=True),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
		):
			transcode.enqueue_transcode(self.doc.file_url)
		self.assertEqual(_deneme(self.doc.name), 0)

	def test_basarili_calistirma_sayaca_dokunmaz_ready_yazar(self):
		# Regresyon: başarı yolu retry eklendikten sonra da aynı.
		def _sahte_ffmpeg(cmd, **kwargs):
			dst = cmd[-1]
			with open(dst, "wb") as f:
				f.write(b"sahte transcode edilmis veri")
			return mock.Mock(returncode=0)

		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run", side_effect=_sahte_ffmpeg
		):
			transcode._run_transcode(self.doc.file_url)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_READY)


class TestRetryFailedElleTetikleme(FrappeTestCase):
	"""Unit + validation — `retry_failed` yalnız dead-letter'ı kabul eder."""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("retry-elle-1.mp4")
		_av_notr(self)
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def test_failed_dosya_sifirlanip_kuyruga_konur(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_FAILED
		)
		frappe.db.set_value(
			"File",
			self.doc.name,
			"th_media_transcode_attempts",
			transcode.MAX_TRANSCODE_ATTEMPTS,
		)
		with mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue:
			sonuc = transcode.retry_failed(self.doc.file_url)

		self.assertEqual(sonuc["status"], transcode.VIDEO_STATUS_PROCESSING)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_PROCESSING)
		self.assertEqual(_deneme(self.doc.name), 0)
		mock_enqueue.assert_called_once()

	def test_processing_dosya_reddedilir(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_PROCESSING
		)
		with self.assertRaises(frappe.ValidationError):
			transcode.retry_failed(self.doc.file_url)

	def test_ready_dosya_reddedilir(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_READY
		)
		with self.assertRaises(frappe.ValidationError):
			transcode.retry_failed(self.doc.file_url)

	def test_durumu_bos_dosya_reddedilir(self):
		# Video değil ya da hiç kuyruğa girmemiş — "yeniden dene" anlamsız.
		with self.assertRaises(frappe.ValidationError):
			transcode.retry_failed(self.doc.file_url)

	def test_olmayan_dosya_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			transcode.retry_failed("/files/boyle-bir-dosya-yok.mp4")

	def test_monkey_bozuk_adresler_kontrollu_hata_verir(self):
		# Monkey: anlamsız girdiler sessizce yutulmamalı, kontrolsüz de
		# patlamamalı — hepsi frappe.ValidationError ile reddedilmeli.
		for bozuk in ("", "   ", "../../etc/passwd", "/files/", "%00", "/files/😀.mp4"):
			with self.assertRaises(frappe.ValidationError, msg=f"girdi: {bozuk!r}"):
				transcode.retry_failed(bozuk)


class TestInventoryVideoStatus(FrappeTestCase):
	"""Integration + database — durum alanı envanter çıktısına akar."""

	def setUp(self):
		# Dosya ADINDA da tuz var: içerik tuzu adresi benzersiz yapıyor ama ADI
		# değil. Aynı adla biriken artıklar (testler commit'leyen kod yollarına
		# giriyor) aramada onlarca satır üretiyor ve aranan dosya sayfaya
		# sığmıyordu — test AV işiyle birlikte koşulunca düştü, sebebi artık
		# birikimiydi. Ada tuz koyunca arama yalnız BU koşumun dosyasını buluyor.
		self.arama = f"inv-video-status-{_KOSUM_TUZU}"
		self.doc = _yeni_video_dosyasi(f"{self.arama}.mp4")
		_av_notr(self)
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def test_list_files_video_status_dondurur(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_FAILED
		)
		sonuc = inventory.list_files(page=1, page_size=10, search=self.arama)
		satirlar = [r for r in sonuc["items"] if r["file_url"] == self.doc.file_url]
		self.assertEqual(len(satirlar), 1)
		self.assertEqual(satirlar[0].get("video_status"), transcode.VIDEO_STATUS_FAILED)

	def test_sayac_db_de_kalici(self):
		frappe.db.set_value("File", self.doc.name, "th_media_transcode_attempts", 2)
		# Doc yeniden yüklendiğinde de aynı değer okunmalı (alan gerçekten
		# şemada, bellekte değil).
		yeniden = frappe.get_doc("File", self.doc.name)
		self.assertEqual(int(yeniden.get("th_media_transcode_attempts") or 0), 2)

	def test_patch_iki_kez_calisinca_kirilmaz(self):
		# Idempotency: alanlar zaten var — patch'ler yeniden koşulduğunda hata
		# yok ve "created" boş dönmeli.
		from tradehub_core.patches import v15_9_18_media_transcode_attempts as patch_sayac
		from tradehub_core.patches import v15_9_19_media_transcode_schedule as patch_zaman

		self.assertEqual(patch_sayac.execute().get("created"), [])
		self.assertEqual(patch_zaman.execute().get("created"), [])


class TestSellerRetryVideoAPI(FrappeTestCase):
	"""API + authorization — satıcı ucu sahiplik ister."""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("api-satici-video.mp4")
		_av_notr(self)
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_FAILED
		)

	def test_kendi_dosyasinda_retry_calisir_ve_audit_yazar(self):
		with (
			mock.patch(
				"tradehub_core.api.seller_media.ownership.current_store",
				return_value="MAGAZA-001",
			),
			mock.patch("tradehub_core.api.seller_media.ownership.assert_owns"),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
			mock.patch("tradehub_core.api.seller_media.audit.log_media_event") as mock_audit,
		):
			sonuc = seller_media.retry_video(self.doc.file_url)

		self.assertEqual(sonuc["status"], transcode.VIDEO_STATUS_PROCESSING)
		mock_audit.assert_called_once()
		_args, kwargs = mock_audit.call_args
		self.assertEqual(kwargs.get("tenant"), "MAGAZA-001")
		self.assertTrue((kwargs.get("context") or {}).get("manual_retry"))

	def test_baskasinin_dosyasinda_sahiplik_reddi(self):
		with (
			mock.patch(
				"tradehub_core.api.seller_media.ownership.current_store",
				return_value="MAGAZA-001",
			),
			mock.patch(
				"tradehub_core.api.seller_media.ownership.assert_owns",
				side_effect=frappe.PermissionError("dosya bu mağazanın değil"),
			),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue,
		):
			with self.assertRaises(frappe.PermissionError):
				seller_media.retry_video(self.doc.file_url)
		# Yetki düşerken kuyruğa hiçbir şey gitmemeli.
		mock_enqueue.assert_not_called()

	def test_magazasiz_oturum_reddedilir(self):
		# Auth: mağazası olmayan oturum satıcı ucuna giremez (`_store` reddi).
		with mock.patch(
			"tradehub_core.api.seller_media.ownership.current_store",
			side_effect=frappe.PermissionError("mağaza yok"),
		):
			with self.assertRaises(frappe.PermissionError):
				seller_media.retry_video(self.doc.file_url)


class TestAdminRetryTranscodeAPI(FrappeTestCase):
	"""API + authorization — yönetici ucu rol ister."""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("api-yonetici-video.mp4")
		_av_notr(self)
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_FAILED
		)

	def test_rolu_olmayan_kullanici_reddedilir(self):
		# `frappe.only_for` hem Administrator'ı hem `flags.in_test`'i atlar
		# (frappe/__init__.py:953) — rol reddini gerçekten sınamak için ikisi de
		# geçici olarak kapatılır.
		frappe.set_user("Guest")
		self.addCleanup(lambda: frappe.set_user("Administrator"))
		onceki = frappe.flags.in_test
		frappe.flags.in_test = False
		self.addCleanup(lambda: setattr(frappe.flags, "in_test", onceki))
		with mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue:
			with self.assertRaises(frappe.PermissionError):
				media_admin.retry_transcode(self.doc.file_url)
		mock_enqueue.assert_not_called()

	def test_bos_adres_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			media_admin.retry_transcode("")

	def test_yonetici_retry_calisir(self):
		with (
			mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue,
			mock.patch("tradehub_core.api.media_admin.audit.log_media_event") as mock_audit,
		):
			sonuc = media_admin.retry_transcode(self.doc.file_url)
		self.assertEqual(sonuc["status"], transcode.VIDEO_STATUS_PROCESSING)
		mock_enqueue.assert_called_once()
		mock_audit.assert_called_once()


class TestSupurucu(FrappeTestCase):
	"""Unit + error/recovery — süpürücü planlı denemeleri ve kayıp işleri toplar.

	Süpürücünün iki ayrı görevi var ve ikisi de kendi başına bir kusuru kapatıyor:
	backoff süresi dolmuş retry'ı kuyruğa koymak, ve sert kill yüzünden
	`processing`de asılı kalmış işi başarısızlık saymak.
	"""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("supur-video.mp4")
		_av_notr(self)
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def _kur(self, *, next_at=None, started_at=None, attempts=0):
		frappe.db.set_value(
			"File",
			self.doc.name,
			{
				"th_media_video_status": transcode.VIDEO_STATUS_PROCESSING,
				"th_media_transcode_next_at": next_at,
				"th_media_transcode_started_at": started_at,
				"th_media_transcode_attempts": attempts,
			},
			update_modified=False,
		)
		frappe.db.commit()

	def _supur(self):
		with _supurucu_izole(self.doc.name) as mock_enqueue:
			sonuc = transcode.sweep_stuck_transcodes()
		return sonuc, mock_enqueue

	def test_zamani_gelmis_planli_deneme_kuyruga_konur(self):
		self._kur(next_at=add_to_date(now_datetime(), seconds=-60), started_at=now_datetime())
		_sonuc, mock_enqueue = self._supur()

		cagrilar = [
			c for c in mock_enqueue.call_args_list if c.kwargs.get("file_url") == self.doc.file_url
		]
		self.assertEqual(len(cagrilar), 1)
		# Plan tüketildi: damga temizlenmezse süpürücü aynı dosyayı her turda
		# yeniden kuyruğa koyar ve iki worker aynı dosyaya yazar.
		self.assertFalse(frappe.db.get_value("File", self.doc.name, "th_media_transcode_next_at"))

	def test_zamani_gelmemis_deneme_beklemede_kalir(self):
		self._kur(next_at=add_to_date(now_datetime(), seconds=600), started_at=now_datetime())
		_sonuc, mock_enqueue = self._supur()

		cagrilar = [
			c for c in mock_enqueue.call_args_list if c.kwargs.get("file_url") == self.doc.file_url
		]
		self.assertEqual(cagrilar, [])
		self.assertTrue(frappe.db.get_value("File", self.doc.name, "th_media_transcode_next_at"))

	def test_gercekten_calisan_is_kayip_sayilmaz(self):
		# Az önce başlamış bir transcode dakikalarca sürebilir — dokunulmamalı.
		self._kur(started_at=now_datetime())
		_sonuc, mock_enqueue = self._supur()

		self.assertEqual(_deneme(self.doc.name), 0)
		cagrilar = [
			c for c in mock_enqueue.call_args_list if c.kwargs.get("file_url") == self.doc.file_url
		]
		self.assertEqual(cagrilar, [])

	def test_birakilmis_is_basarisizlik_sayilir_ve_yeniden_planlanir(self):
		# Sert kill senaryosu: `except` hiç çalışmadı, damga eskidi.
		self._kur(
			started_at=add_to_date(now_datetime(), seconds=-(jobs.STALE_AFTER_SECONDS + 60))
		)
		sonuc, _mock_enqueue = self._supur()

		# Sayıya değil KENDİ kaydımıza bakılıyor: süpürücü tüm envanteri
		# tarıyor ve aynı koşumdaki başka testlerin `processing` kayıtları da
		# sayaca giriyor.
		self.assertGreaterEqual(sonuc["abandoned"], 1)
		self.assertEqual(_deneme(self.doc.name), 1)
		# Hakkı var → dead-letter DEĞİL, yeni deneme planlandı.
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_PROCESSING)
		self.assertTrue(frappe.db.get_value("File", self.doc.name, "th_media_transcode_next_at"))

	def test_birakilmis_is_hak_bitmisse_dead_lettera_duser(self):
		self._kur(
			started_at=add_to_date(now_datetime(), seconds=-(jobs.STALE_AFTER_SECONDS + 60)),
			attempts=transcode.MAX_TRANSCODE_ATTEMPTS - 1,
		)
		sonuc, _mock_enqueue = self._supur()

		self.assertGreaterEqual(sonuc["abandoned"], 1)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_FAILED)
		# Dead-letter süpürücünün kapsamından TAMAMEN çıkmalı.
		self.assertFalse(frappe.db.get_value("File", self.doc.name, "th_media_transcode_next_at"))

	def test_dead_letter_bir_daha_supurulmez(self):
		# Sonsuz döngü koruması: `failed` durumundaki dosya taramaya hiç girmez.
		frappe.db.set_value(
			"File",
			self.doc.name,
			{
				"th_media_video_status": transcode.VIDEO_STATUS_FAILED,
				"th_media_transcode_started_at": add_to_date(now_datetime(), seconds=-99999),
			},
			update_modified=False,
		)
		frappe.db.commit()
		_sonuc, mock_enqueue = self._supur()

		cagrilar = [
			c for c in mock_enqueue.call_args_list if c.kwargs.get("file_url") == self.doc.file_url
		]
		self.assertEqual(cagrilar, [])
		self.assertEqual(_deneme(self.doc.name), 0)

	def test_damgasiz_kayit_kayip_sayilir(self):
		# Kör nokta olmasın: damgayı yazamadan düşen worker ya da alan eklenmeden
		# önceki kayıt da yakalanmalı.
		self._kur(started_at=None)
		sonuc, _mock_enqueue = self._supur()
		self.assertGreaterEqual(sonuc["abandoned"], 1)
		self.assertEqual(_deneme(self.doc.name), 1)


class TestPaylasilanAdresteKayitHedefleme(FrappeTestCase):
	"""Aynı `file_url`'e birden çok `File` kaydı düştüğünde doğru kayıt işlenir.

	İçerik-adresli adlandırma yüzünden bir adrese 39 kayda kadar işaret
	edilebiliyor. Süpürücü KAYIT bazında çalışıyor; iş kuyruğa yalnız adresle
	konsaydı worker o adresteki İLK kaydı bulur, sayaç başka kayıtta artar ve
	süpürücünün hedef kaydı sonsuza kadar `processing`de kalırdı.
	"""

	def setUp(self):
		_av_notr(self)
		self.birinci = _yeni_video_dosyasi("paylasilan-adres.mp4")
		# Aynı içerik → AYNI file_url, ayrı kayıt.
		self.ikinci = _yeni_video_dosyasi(
			"paylasilan-adres-2.mp4", content=self.birinci.file_name.encode() + b"-ayni"
		)
		frappe.db.set_value(
			"File", self.ikinci.name, "file_url", self.birinci.file_url, update_modified=False
		)
		frappe.db.commit()
		for ad in (self.birinci.name, self.ikinci.name):
			self.addCleanup(
				lambda ad=ad: frappe.delete_doc(
					"File", ad, ignore_permissions=True, force=True
				)
			)

	def _hedef_kayit(self) -> str:
		"""Adresten çözüldüğünde hangi kayıt bulunuyor — testin anlamlı olması
		için hedefimiz DİĞERİ olmalı."""
		return frappe.db.get_value("File", {"file_url": self.birinci.file_url}, "name")

	def test_sayac_verilen_kayitta_artar_adresten_cozulende_degil(self):
		bulunan = self._hedef_kayit()
		hedef = self.ikinci.name if bulunan == self.birinci.name else self.birinci.name
		diger = bulunan

		with (
			mock.patch(
				"tradehub_core.media.transcode.subprocess.run",
				side_effect=Exception("ffmpeg patladı"),
			),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
		):
			transcode._run_transcode(self.birinci.file_url, name=hedef)

		self.assertEqual(_deneme(hedef), 1, "sayaç verilen kayıtta artmalı")
		self.assertEqual(_deneme(diger), 0, "adresten çözülen kayda dokunulmamalı")

	def test_silinmis_kayit_adi_verilirse_adresten_cozmeye_duser(self):
		# Geriye dönük uyumluluk + dayanıklılık: kuyrukta bekleyen iş, kaydı
		# silinmiş olabilir. Worker patlamamalı.
		with (
			mock.patch(
				"tradehub_core.media.transcode.subprocess.run",
				side_effect=Exception("ffmpeg patladı"),
			),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
		):
			transcode._run_transcode(self.birinci.file_url, name="BOYLE-BIR-KAYIT-YOK")

		# Adresten çözülen kayıtta sayaç artmış olmalı — iş sessizce düşmemeli.
		self.assertEqual(_deneme(self._hedef_kayit()), 1)

	def test_supurucu_kuyruga_kayit_adini_koyar(self):
		frappe.db.set_value(
			"File",
			self.birinci.name,
			{
				"th_media_video_status": transcode.VIDEO_STATUS_PROCESSING,
				"th_media_transcode_next_at": add_to_date(now_datetime(), seconds=-60),
				"th_media_transcode_started_at": now_datetime(),
			},
			update_modified=False,
		)
		frappe.db.commit()
		with _supurucu_izole(self.birinci.name, self.ikinci.name) as mock_enqueue:
			transcode.sweep_stuck_transcodes()

		cagrilar = [
			c for c in mock_enqueue.call_args_list if c.kwargs.get("name") == self.birinci.name
		]
		self.assertEqual(len(cagrilar), 1, "süpürücü hedef kaydın adını taşımalı")


class TestVideoDurumToplama(FrappeTestCase):
	"""Integration — aynı adreste durumlar ayrışırsa panelde KÖTÜ haber kazanır.

	Önceden `Max()` doğrudan metin üstünde alınıyordu; alfabetik sırada
	`ready` > `processing` > `failed` olduğu için başarısız bir dosya panelde
	"hazır" görünebiliyordu.
	"""

	def setUp(self):
		_av_notr(self)
		self.a = _yeni_video_dosyasi("toplama-a.mp4")
		self.b = _yeni_video_dosyasi("toplama-b.mp4")
		frappe.db.set_value("File", self.b.name, "file_url", self.a.file_url, update_modified=False)
		frappe.db.commit()
		for ad in (self.a.name, self.b.name):
			self.addCleanup(
				lambda ad=ad: frappe.delete_doc(
					"File", ad, ignore_permissions=True, force=True
				)
			)

	def _durum_satiri(self) -> str | None:
		sonuc = inventory.list_files(page=1, page_size=20, search="toplama-")
		for r in sonuc["items"]:
			if r["file_url"] == self.a.file_url:
				return r.get("video_status")
		return None

	def _yaz(self, a_durum: str, b_durum: str) -> None:
		frappe.db.set_value("File", self.a.name, "th_media_video_status", a_durum,
		                    update_modified=False)
		frappe.db.set_value("File", self.b.name, "th_media_video_status", b_durum,
		                    update_modified=False)
		frappe.db.commit()

	def test_failed_ready_i_yener(self):
		self._yaz(transcode.VIDEO_STATUS_READY, transcode.VIDEO_STATUS_FAILED)
		self.assertEqual(self._durum_satiri(), transcode.VIDEO_STATUS_FAILED)

	def test_failed_processing_i_yener(self):
		self._yaz(transcode.VIDEO_STATUS_PROCESSING, transcode.VIDEO_STATUS_FAILED)
		self.assertEqual(self._durum_satiri(), transcode.VIDEO_STATUS_FAILED)

	def test_processing_ready_i_yener(self):
		self._yaz(transcode.VIDEO_STATUS_READY, transcode.VIDEO_STATUS_PROCESSING)
		self.assertEqual(self._durum_satiri(), transcode.VIDEO_STATUS_PROCESSING)

	def test_durum_yoksa_bos_doner(self):
		# Video olmayan/hiç işlenmemiş kayıt: ön yüz rozet göstermemeli.
		self._yaz("", "")
		self.assertEqual(self._durum_satiri(), "")


class TestZamanAsimiMerdiveni(FrappeTestCase):
	"""Unit — zaman aşımı sıralaması bozulursa hata yolu tamamen kaybolur."""

	def test_merdiven_artan_sirada(self):
		self.assertLess(transcode._FFPROBE_TIMEOUT_SECONDS, transcode._FFMPEG_TIMEOUT_SECONDS)
		self.assertLess(transcode._FFMPEG_TIMEOUT_SECONDS, transcode.QUEUE_TIMEOUT_SECONDS)
		# Kayıp eşiği kuyruk timeout'undan büyük olmalı: küçük olsaydı hâlâ
		# çalışan bir transcode "kayıp" ilan edilip ikinci kez kuyruğa girerdi.
		self.assertLess(transcode.QUEUE_TIMEOUT_SECONDS, jobs.STALE_AFTER_SECONDS)


class TestUctanUcaVeToparlanma(FrappeTestCase):
	"""E2E + error/recovery — yaşam döngüsünün tamamı tek senaryoda.

	upload sonrası: processing → 3 ardışık hata → failed (dead-letter) →
	elle retry → başarılı çalıştırma → ready. Her adımda durum ve sayaç
	doğrulanır; geçici dosya hata dallarında diskte kalmamalı.
	"""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("e2e-video.mp4")
		_av_notr(self)
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def _hata_turu(self, exc):
		with (
			mock.patch("tradehub_core.media.transcode.subprocess.run", side_effect=exc),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
		):
			transcode._run_transcode(self.doc.file_url)

	def test_tam_dongu(self):
		# 1) Yükleme sonrası kuyruğa giriş.
		with (
			mock.patch("tradehub_core.media.transcode.needs_transcode", return_value=True),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
		):
			transcode.enqueue_transcode(self.doc.file_url)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_PROCESSING)
		self.assertEqual(_deneme(self.doc.name), 0)

		# 2) Üç farklı hata türü — recovery davranışı hepsinde aynı olmalı:
		#    ffmpeg imajdan kalkmış, ffmpeg çökmüş, zaman aşımı.
		import subprocess as sp

		self._hata_turu(FileNotFoundError("ffmpeg yok"))
		self.assertEqual(_deneme(self.doc.name), 1)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_PROCESSING)

		self._hata_turu(sp.CalledProcessError(1, ["ffmpeg"]))
		self.assertEqual(_deneme(self.doc.name), 2)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_PROCESSING)

		self._hata_turu(sp.TimeoutExpired(["ffmpeg"], 1700))
		self.assertEqual(_deneme(self.doc.name), 3)
		# 3) Hak bitti — dead-letter.
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_FAILED)

		# 4) Geçici dosya hata dallarından artakalmamış olmalı.
		import os

		src = frappe.get_doc("File", self.doc.name).get_full_path()
		self.assertFalse(os.path.exists(f"{src}.transcoding.webm"))

		# 5) İnsan devreye girer: elle retry → tekrar processing, sayaç 0.
		with mock.patch("tradehub_core.media.transcode.frappe.enqueue"):
			transcode.retry_failed(self.doc.file_url)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_PROCESSING)
		self.assertEqual(_deneme(self.doc.name), 0)

		# 6) Bu kez ffmpeg çalışır → ready.
		def _sahte_ffmpeg(cmd, **kwargs):
			dst = cmd[-1]
			with open(dst, "wb") as f:
				f.write(b"sahte transcode edilmis veri")
			return mock.Mock(returncode=0)

		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run", side_effect=_sahte_ffmpeg
		):
			transcode._run_transcode(self.doc.file_url)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_READY)

	def test_kuyruktayken_silinen_dosya_worker_i_dusurmez(self):
		# Recovery: iş kuyruğa girdikten sonra satıcı dosyayı bırakabilir.
		frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		with mock.patch("tradehub_core.media.transcode.subprocess.run") as mock_run:
			transcode._run_transcode(self.doc.file_url)  # patlamamalı
		mock_run.assert_not_called()


if __name__ == "__main__":
	import unittest

	unittest.main()
