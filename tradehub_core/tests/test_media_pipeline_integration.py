"""Medya pipeline (WP2+WP3+WP4) uçtan uca ENTEGRASYON testi.

Dört iş paketi tek tek doğrulandı (`test_media_quota.py` — stub'lu, `test_media_naming.py`
ve `test_media_transcode.py` — gerçek DB ama izole). Bu dosya DÖRDÜNÜN AYNI upload
zincirinde BİRLİKTE çalıştığını doğrular:

  - WP4 isimlendirme: `media/naming.py:write_file_hashed` (Frappe `write_file` hook)
  - WP3 kota: `entitlement/checks.py:check_media_storage_quota` (`File.before_insert`)
  - WP2 görsel: `media/engine.py:to_webp` (sunucu garanti-WebP)
  - WP2 video: `media/transcode.py:enqueue_transcode` (async kuyruk)
  - Giriş noktası: `api/seller_media.py:upload_media`

Gerçek DB, gerçek `Admin Seller Profile` + `Subscription Plan` + `Store Subscription`,
gerçek `File.insert()` hook zinciri kullanılır. Yalnız ffmpeg'in GERÇEK çalışması
engellenir (dev backend imajında ffmpeg kurulu değil, `_run_transcode` `subprocess.run`
çağırıyor) — `frappe.enqueue`'ı mock'layarak `_run_transcode`'un worker'da hiç
tetiklenmemesi sağlanıyor; WP2'nin kendi testi (`test_media_transcode.py`) da aynı
deseni kullanıyor.

`upload_media` içinde `frappe.db.commit()` GERÇEKTEN çağrılıyor — bu, Frappe test
runner'ının class-teardown'daki `frappe.db.rollback()`'ini atlar (yalnız commit
edilmemiş işlemler geri alınır). Bu yüzden her test kendi satıcı/plan/subscription/
File kayıtlarını `addCleanup` ile TEK TEK siliyor.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_pipeline_integration
"""

from __future__ import annotations

import base64
import io
import json
import os
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_files_path, now_datetime

from tradehub_core.api import seller_media
from tradehub_core.media import engine, naming, transcode
from tradehub_core.media import files as media_files


def _jpeg_bytes(color: tuple[int, int, int] = (200, 30, 30), size: tuple[int, int] = (64, 64)) -> bytes:
	"""Gerçek, PIL'in açabildiği bir JPEG üretir (küçük, tek renk kare)."""
	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", size, color).save(buf, "JPEG", quality=90)
	return buf.getvalue()


def _b64(data: bytes) -> str:
	return base64.b64encode(data).decode()


class _MediaPipelineIntegrationBase(FrappeTestCase):
	"""Ortak yardımcılar — throwaway satıcı/plan/subscription kurulum + temizlik."""

	def _delete_and_commit(self, doctype: str, name: str) -> None:
		"""Sil VE commit et.

		KRİTİK: `upload_media` başarılı olduğunda içeride GERÇEKTEN `frappe.db.
		commit()` çağırıyor — bu, o ana kadar AÇIK olan tüm transaction'ı (test
		başında kurulan store/plan/subscription/user insert'leri DAHİL) kalıcı
		hale getiriyor. FrappeTestCase'in class-teardown'ı yalnız `frappe.db.
		rollback()` yapıyor — COMMIT EDİLMİŞ hiçbir şeyi geri alamaz. Silme de
		kendi commit'ini yapmazsa, class-teardown'daki rollback SİLMEYİ geri
		alır ama orijinal (zaten commit edilmiş) satır kalıcı artık olarak
		DB'de kalır — ilk denemede tam olarak bu oldu (bkz. entegrasyon
		raporu). Bu yüzden her silme kendi commit'ini taşıyor.
		"""
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def _make_store(self, *, quota_mb: int, tag: str) -> tuple[str, str]:
		"""Gerçek User + Admin Seller Profile + Subscription Plan + Store Subscription
		kurar, `addCleanup` ile (LIFO sırayla: subscription → plan → store → user) siler.

		Döner: (store_name, user_email).
		"""
		suffix = frappe.generate_hash(length=8)
		email = f"medya-entegrasyon-{tag}-{suffix}@test.local"

		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Medya",
				"last_name": "Entegrasyon",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: self._delete_and_commit("User", user.name))

		store = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_name": f"Medya Entegrasyon Satıcı {tag}",
				"seller_code": frappe.generate_hash(length=10),
				"user": email,
				"email": email,
				"status": "Active",
			}
		).insert(ignore_permissions=True, ignore_mandatory=True)
		self.addCleanup(lambda: self._delete_and_commit("Admin Seller Profile", store.name))

		plan = frappe.get_doc(
			{
				"doctype": "Subscription Plan",
				"plan_code": f"medya-entegrasyon-{tag}-{suffix}",
				"plan_name": f"Medya Entegrasyon Plan {tag}",
				"currency": "TRY",
				"monthly_price": 0,
				"capability_flags": "{}",
				"quota_limits": json.dumps({"quota.max_storage_mb": quota_mb}),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: self._delete_and_commit("Subscription Plan", plan.name))

		sub = frappe.get_doc(
			{
				"doctype": "Store Subscription",
				"store": store.name,
				"plan": plan.name,
				"status": "active",
				"started_at": now_datetime(),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: self._delete_and_commit("Store Subscription", sub.name))

		return store.name, email

	def _as_seller(self, email: str) -> None:
		"""Oturumu satıcıya çevirir, test bitince Administrator'a geri döner."""
		frappe.set_user(email)
		self.addCleanup(lambda: frappe.set_user("Administrator"))

	def _cleanup_file(self, file_url: str) -> None:
		"""`file_url`'e bağlı TÜM File kayıtlarını siler (dedup nedeniyle birden
		fazla kayıt aynı url'i gösterebilir — WP4 dedup senaryosu). Her silme
		`_delete_and_commit` üzerinden kendi commit'ini yapar (yukarıdaki not)."""
		if not file_url:
			return
		names = frappe.get_all("File", filters={"file_url": file_url}, pluck="name")
		for name in names:
			self._delete_and_commit("File", name)


class TestGorselZinciri(_MediaPipelineIntegrationBase):
	"""Senaryo 1 — görsel zinciri: upload_media(jpg) → hash isim + .webp + gerçek
	WebP disk içeriği + storage_usage artışı, TEK bir upload'ta birlikte."""

	def test_upload_media_jpg_hash_webp_disk_ve_kullanim_artisi(self):
		store, email = self._make_store(quota_mb=100, tag="img")
		self._as_seller(email)

		once_bytes = media_files.storage_usage(store)["bytes"]

		jpeg = _jpeg_bytes()
		result = seller_media.upload_media(file_name="foto.jpg", content=_b64(jpeg))
		self.addCleanup(lambda: self._cleanup_file(result["file_url"]))

		# (a) hash isimli — 32 hex karakter, orijinal ad ("foto") sızmıyor
		base_name = os.path.basename(result["file_url"])
		stem, ext = os.path.splitext(base_name)
		self.assertEqual(len(stem), 32, f"dosya adı 32 karakter değil: {stem}")
		try:
			int(stem, 16)
		except ValueError:
			self.fail(f"dosya adı hex değil (içerik-hash bekleniyor): {stem}")
		self.assertNotIn("foto", result["file_url"])
		# NOT: `file_name` (görünen ad) kasıtlı olarak DEĞİŞMEZ — yalnız disk
		# adı + file_url içerik-hash'lidir (bkz. media/naming.py başlığı).
		# Görünen ad burada "foto.webp" olmalı (gövde korunur, uzantı .webp'ye
		# döner); URL'de ise hash dışında hiçbir şey görünmemeli (yukarıda).
		self.assertEqual(result["file_name"], "foto.webp")

		# (b) .webp uzantılı — JPEG sunucuda WebP'ye çevrildi (TUR-128)
		self.assertEqual(ext, ".webp")
		self.assertEqual(os.path.splitext(result["file_name"])[1], ".webp")

		# (c) diskteki dosya GERÇEK WebP (RIFF/WEBP header)
		#
		# Yol `av.current_path` ile çözülüyor, `public/files/` sabit değil:
		# tarama açıkken yeni dosya, taraması bitene kadar `media_scan_hold`
		# altında bekletiliyor (TUR-125, kabul kriteri 4). Bu test görsel
		# zincirini sınıyor — dosyanın HANGİ kökte durduğu bekletmenin konusu ve
		# kendi testleri var (`TestBekletme`); burada önemli olan içeriğin
		# gerçekten WebP olması.
		#
		# Yedek yol hash-prefix shard'lı olmalı (TUR-130): public/files/<ab>/<hash>.webp
		# — shard'sız yedek, tarama kapalıyken dosyayı bulamazdı.
		from tradehub_core.media import av

		disk_path = av.current_path(result["file_url"]) or os.path.join(
			get_files_path(is_private=0), base_name[:2], base_name
		)
		self.assertTrue(os.path.isfile(disk_path), f"diskte yok: {disk_path}")
		with open(disk_path, "rb") as f:
			header = f.read(12)
		self.assertEqual(header[0:4], b"RIFF", f"RIFF header yok: {header!r}")
		self.assertEqual(header[8:12], b"WEBP", f"WEBP fourcc yok: {header!r}")

		# (d) storage_usage(store)["bytes"] upload sonrası ARTTI
		sonraki_bytes = media_files.storage_usage(store)["bytes"]
		self.assertGreater(sonraki_bytes, once_bytes)


class TestKotaReddi(_MediaPipelineIntegrationBase):
	"""Senaryo 2 — kota reddi: planda quota.max_storage_mb=0 → before_insert
	kota kapısı devrede, upload frappe.ValidationError ile reddedilir."""

	def test_dusuk_kotada_upload_reddedilir(self):
		store, email = self._make_store(quota_mb=0, tag="quota-deny")
		self._as_seller(email)

		jpeg = _jpeg_bytes(color=(10, 10, 200))
		# Reddedilen yüklemenin diskte bıraktığı olası artığı (write_file hook
		# quota kontrolünden ÖNCE çalışıyor — bkz. test_media_quota.py docstring'i)
		# temizlemek için beklenen hash'li adı önceden hesaplıyoruz.
		beklenen_webp = engine.to_webp(jpeg)
		beklenen_ad = naming._hashed_name("x.webp", beklenen_webp)
		self.addCleanup(
			lambda: os.path.exists(os.path.join(get_files_path(is_private=0), beklenen_ad))
			and os.remove(os.path.join(get_files_path(is_private=0), beklenen_ad))
		)

		with self.assertRaises(frappe.ValidationError) as ctx:
			seller_media.upload_media(file_name="reddedilecek.jpg", content=_b64(jpeg))
		self.assertIn("kota", str(ctx.exception).lower())

		# Reddedilen upload DB'ye File kaydı BIRAKMADI.
		self.assertFalse(frappe.db.exists("File", {"file_url": ["like", f"%{beklenen_ad}"]}))


class TestKotaMuafiyeti(_MediaPipelineIntegrationBase):
	"""Senaryo 3 — kota muafiyeti: attached_to_doctype='KYB Verification' olan
	File insert'i, satıcının kotası (0 MB) aşılsa BİLE reddedilmez."""

	def test_kyb_dosyasi_kota_asiminda_bile_kabul_edilir(self):
		store, email = self._make_store(quota_mb=0, tag="quota-exempt")
		self._as_seller(email)

		icerik = _jpeg_bytes(color=(30, 200, 30))
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "kyb-belge.jpg",
				"is_private": 0,
				"content": icerik,
				"attached_to_doctype": "KYB Verification",
				"attached_to_name": "KYB-ENTEGRASYON-TEST-YOK",
			}
		)
		# throw ATMAMALI — EXCLUDED_DOCTYPES muafiyeti before_insert kota
		# kontrolünden ÖNCE devreye giriyor.
		doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: self._cleanup_file(doc.file_url))

		self.assertTrue(doc.file_url)
		self.assertTrue(frappe.db.exists("File", doc.name))


class TestVideoDali(_MediaPipelineIntegrationBase):
	"""Senaryo 4 — video dalı: upload_media(mp4) → th_media_video_status=processing
	+ transcode.enqueue_transcode gerçekten çağrılır (ffmpeg'in kendisi hiç
	tetiklenmez — frappe.enqueue mock'lu, WP2'nin kendi testiyle aynı desen)."""

	def test_video_upload_processing_isaretler_ve_transcode_kuyruklanir(self):
		store, email = self._make_store(quota_mb=100, tag="video")
		self._as_seller(email)

		# Gerçek çözülebilir bir mp4 olmasına GEREK YOK: to_webp bu uzantıya hiç
		# uygulanmıyor (VIDEO_EXTENSIONS dalı), ffmpeg de mock'landığı için
		# içerik hiç decode edilmiyor.
		video_bytes = b"\x00\x00\x00\x18ftypmp42" + os.urandom(256)

		with mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue:
			result = seller_media.upload_media(file_name="klip.mp4", content=_b64(video_bytes))
		self.addCleanup(lambda: self._cleanup_file(result["file_url"]))

		# .webp'ye ÇEVRİLMEDİ — video dalı image_to_webp'ten muaf
		self.assertTrue(result["file_url"].endswith(".mp4"))
		# hash isimli — 32 hex + .mp4
		stem = os.path.splitext(os.path.basename(result["file_url"]))[0]
		self.assertEqual(len(stem), 32)

		# Yükleme artık İKİ iş kuyruklıyor: video transcode (TUR-296) ve zararlı
		# içerik taraması (TUR-125). `frappe.enqueue` her iki modülde de AYNI
		# modül nesnesi olduğu için tek mock ikisini birden yakalıyor.
		#
		# Bu yüzden çağrı SAYISI değil, aranan çağrının kendisi doğrulanıyor:
		# sayıya bakmak, pipeline'a eklenen her yeni adımda bu testi konusuyla
		# ilgisiz biçimde kırardı (yaşandı — TUR-125 eklenince `assert_called_once`
		# düştü, oysa transcode dalında değişen hiçbir şey yoktu).
		transcode_cagrilari = [
			c
			for c in mock_enqueue.call_args_list
			if c.args and str(c.args[0]).endswith("transcode._run_transcode")
		]
		self.assertEqual(len(transcode_cagrilari), 1)
		kwargs = transcode_cagrilari[0].kwargs
		self.assertEqual(kwargs.get("queue"), "long")
		self.assertEqual(kwargs.get("file_url"), result["file_url"])
		self.assertTrue(kwargs.get("enqueue_after_commit"))

		durum = frappe.db.get_value("File", {"file_url": result["file_url"]}, "th_media_video_status")
		self.assertEqual(durum, transcode.VIDEO_STATUS_PROCESSING)

	def test_video_status_upload_donusunde_ve_listede_gorunur(self):
		"""Video durumu uçlardan dönmeli (TUR video-durum düzeltmesi): panel rozeti
		hem `upload_media` dönüşünden (yükleme anında "işleniyor") hem
		`get_my_media` listesinden (kütüphane ızgarası) besleniyor."""
		store, email = self._make_store(quota_mb=100, tag="video-status")
		self._as_seller(email)

		video_bytes = b"\x00\x00\x00\x18ftypmp42" + os.urandom(256)

		with mock.patch("tradehub_core.media.transcode.frappe.enqueue"):
			result = seller_media.upload_media(file_name="rozet.mp4", content=_b64(video_bytes))
		self.addCleanup(lambda: self._cleanup_file(result["file_url"]))

		# (a) upload dönüşü — panel "Video yüklendi" toast'ı yerine duruma bakabilsin
		self.assertEqual(result.get("video_status"), transcode.VIDEO_STATUS_PROCESSING)

		# (b) liste ucu — kütüphane ızgarasındaki her satırda durum var
		liste = seller_media.get_my_media()
		satir = next((i for i in liste["items"] if i["file_url"] == result["file_url"]), None)
		self.assertIsNotNone(satir, f"yüklenen video listede yok: {result['file_url']}")
		self.assertEqual(satir.get("video_status"), transcode.VIDEO_STATUS_PROCESSING)

		# (c) video olmayan satırlar patlamıyor — alan boş/None dönebilir, KeyError değil
		jpeg = _jpeg_bytes(color=(120, 120, 40))
		r_img = seller_media.upload_media(file_name="gorsel.jpg", content=_b64(jpeg))
		self.addCleanup(lambda: self._cleanup_file(r_img["file_url"]))
		self.assertFalse(r_img.get("video_status"))


class TestHashDedup(_MediaPipelineIntegrationBase):
	"""Senaryo 5 — hash dedup: aynı JPEG içeriği iki AYRI upload_media çağrısıyla
	yüklenince, içerik-adresli isimlendirme (WP4) her ikisini de AYNI file_url'e
	çözer (dedup korunur) — iki ayrı File KAYDI olsa bile disk adresi tek."""

	def test_ayni_icerik_iki_kez_yuklenince_ayni_file_url_uretir(self):
		store, email = self._make_store(quota_mb=100, tag="dedup")
		self._as_seller(email)

		jpeg = _jpeg_bytes(color=(90, 60, 220))
		r1 = seller_media.upload_media(file_name="birinci.jpg", content=_b64(jpeg))
		r2 = seller_media.upload_media(file_name="ikinci-farkli-ad.jpg", content=_b64(jpeg))
		self.addCleanup(lambda: self._cleanup_file(r1["file_url"]))

		self.assertEqual(r1["file_url"], r2["file_url"])

		kayitlar = frappe.get_all("File", filters={"file_url": r1["file_url"]}, pluck="name")
		self.assertEqual(
			len(kayitlar), 2, "iki ayrı upload_media çağrısı iki ayrı File kaydı bırakmalı"
		)


if __name__ == "__main__":
	import unittest

	unittest.main()
