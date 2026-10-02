# Ürün Görseli Kare (1000–2000, beyaz dolgu) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ürüne bağlı her görsel kare, 1000–2000 px, beyaz dolgulu WebP olsun. Yeni görseller ürün kaydında, eskiler panel kartından toplu olarak çevrilsin. Eski adres 301 ile yeni adrese gitsin; işlem geri alınabilsin.

**Architecture:** `media/kare.py` iki katmanlı:
- **Saf görsel dönüşümü:** `kare_boyutu`, `kareye_cevir`.
- **Dosya başına taşıma:** `normalize_one` / `rollback_one`. Retro-rename'in kilit, ilerleme, 301 ve referans altyapısını (`retro_rename`, `refs`, `archive`) yeniden kullanır; kopyalamaz.

Tetikler: `Listing.on_update` → kuyruk (`normalize_listing`), panel → `run_job` / `run_rollback`.

**Tech Stack:** Frappe v15, Python 3.12, Pillow, MariaDB, Redis (RQ), Vue 3.5 `<script setup>`, vue-i18n, Node `node:test`.

**Spec:** `tradehub_core/docs/superpowers/specs/2026-09-29-urun-gorseli-kare-design.md`

## Global Constraints

- Hedef kenar: `S = max(1000, min(2000, uzun_kenar))`. Uzun kenar 2000'i aşıyorsa 2000'e küçültülür. **Upscale YOK.**
- Zaten kare ve `1000 ≤ kenar ≤ 2000` olan görsel **dokunulmaz**.
- Tuval beyaz (`#FFFFFF`), görsel ortalı. Alfa kanalı beyaza düzlenir. Çıktı WebP, quality 85.
- Kapsam yalnız ürün görselleri: `Listing.primary_image`, `Listing Image.image`, `Listing Variant Item.variant_image`, `Listing Variant Item.variant_gallery`. Dosyaya ürün dışı bir canlı kaynak (logo, banner, marka, kategori, satıcı galerisi, OG) bağlıysa dosya **atlanır**.
- Eski adres için `Media URL Redirect` (301, 90 gün, `retro_rename.REDIRECT_TTL_DAYS`). Orijinal `media.archive` içinde 30 gün kalır.
- Sipariş geçmişi (`Order Item.image` gibi READONLY kaynaklar) eski adresi gösteriyorsa eski dosya diskten **SİLİNMEZ**: sipariş ekranı eski görseli göstermeye devam eder.
- Backend: tab indent, Ruff line-length 110, `frappe.throw(_("…"))`, `ignore_permissions=True` yalnız sistem işi ve gerekçe yorumlu. Yeni whitelist uçları `_guard_destructive()` ile korunur.
- Frontend: `<script setup>`, SCSS `@use`, `api.callMethod*` dışında fetch yok. i18n 4 dil (tr, en, ru, ar); anahtarlarda nokta yok.
- Commit: kullanıcının açık onayı olmadan commit **YOK**. Görevlerdeki commit adımları "diff hazır, commit etme" olarak uygulanır, yalnız kontrolcü commit'e karar verir.

## Review Focus

1. Aynı dosya iki üründe ve bir sepette kullanılıyor: tek dönüşüm, üç referans birden yeni adrese geçmeli (Task 2 testi).
2. Dosyayı aynı anda hem ürün-kaydı işi hem toplu iş işliyor: ikinci işlem `disk_missing` ya da `already_square` ile atlamalı, çift dosya ya da kırık referans üretmemeli (Task 2 kilit testi).
3. Aynı görsel mağaza logosu olarak da kullanılıyor: dosya atlanmalı, logo kareye dönmemeli (Task 2 testi).
4. Geri alma sonrası eski adres 200, yeni adres ve redirect satırı yok, ürün alanı eski adreste (Task 2 testi).
5. Şeffaf PNG, CMYK JPEG, EXIF döndürmeli JPEG ve animasyonlu GIF: ilk üçü doğru kare, sonuncusu atlanır (Task 1 testi).

---

## File Structure

| Dosya | Sorumluluk |
|---|---|
| `tradehub_core/media/kare.py` (yeni) | Saf dönüşüm + `normalize_one`, `rollback_one`, `aday_urls`, `run_job`, `run_rollback`, `normalize_listing`, `on_listing_update` |
| `tradehub_core/tests/test_media_kare.py` (yeni) | Saf dönüşüm birim testleri |
| `tradehub_core/tests/test_media_kare_job.py` (yeni) | Dosya/iş/geri alma entegrasyon testleri |
| `tradehub_core/hooks.py` | `Listing.on_update` listesine `tradehub_core.media.kare.on_listing_update` eklenir |
| `tradehub_core/api/media_admin.py` | `square_count`, `start_square`, `get_square_status`, `stop_square`, `rollback_square` |
| `tradehub_core/tests/test_media_admin_square.py` (yeni) | Uç yetki ve kuyruğa alma testleri |
| `tradehub_core/media/pipeline/policy/slots/product-image.json` | Reddetme kuralları kaldırılır, master 1000–2000 |
| `admin-panel/frontend/src/lib/media/policy/vendor/*` | `npm run sync:policy` ile üretilir (elle değil) |
| `admin-panel/frontend/src/composables/useMediaSquare.js` (yeni) | API sarmalayıcı + durum makinesi |
| `admin-panel/frontend/src/components/media/MediaSquareCard.vue` (yeni) | Panel kartı |
| `admin-panel/frontend/src/views/system/MediaOptimizeView.vue` | Kartı `MediaRetroRenameCard`'ın altına ekler |
| `admin-panel/frontend/src/i18n/locales/{tr,en,ru,ar}.js` | `media.square.*` anahtarları |

---

### Task 1: Saf kare dönüşümü

**Files:**
- Create: `tradehub_core/tradehub_core/media/kare.py`
- Test: `tradehub_core/tradehub_core/tests/test_media_kare.py`

**Interfaces:**
- Produces:
  - `MIN_KENAR = 1000`, `MAX_KENAR = 2000`
  - `kare_boyutu(w: int, h: int) -> int | None`
  - `kareye_cevir(icerik: bytes) -> tuple[bytes, int]`: `(webp_bayt, S)`
  - `class Atla(Exception)`: `reason: str`; değerler `animated`, `unreadable`, `already_square`

- [ ] **Step 1: Failing testleri yaz**

```python
"""Ürün görseli kare dönüşümü — saf fonksiyonlar (spec 2026-09-29 §1)."""

import io

from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tradehub_core.media import kare


def _img(w, h, mode="RGB", color=(200, 30, 30), fmt="JPEG", **save):
	im = Image.new(mode, (w, h), color)
	buf = io.BytesIO()
	im.save(buf, fmt, **save)
	return buf.getvalue()


def _ac(b):
	return Image.open(io.BytesIO(b))


class TestKareBoyutu(FrappeTestCase):
	def test_ornek_tablo(self):
		self.assertEqual(kare.kare_boyutu(3068, 2547), 2000)
		self.assertEqual(kare.kare_boyutu(800, 1000), 1000)
		self.assertEqual(kare.kare_boyutu(600, 500), 1000)
		self.assertEqual(kare.kare_boyutu(1500, 900), 1500)
		self.assertEqual(kare.kare_boyutu(2000, 2000), None)
		self.assertEqual(kare.kare_boyutu(1200, 1200), None)
		self.assertEqual(kare.kare_boyutu(1000, 1000), None)
		self.assertEqual(kare.kare_boyutu(800, 800), 1000)
		self.assertEqual(kare.kare_boyutu(2500, 2500), 2000)

	def test_gecersiz(self):
		self.assertIsNone(kare.kare_boyutu(0, 100))


class TestKareyeCevir(FrappeTestCase):
	def test_buyuk_yatay_2000_kare(self):
		out, s = kare.kareye_cevir(_img(3068, 2547))
		im = _ac(out)
		self.assertEqual((s, im.format, im.size), (2000, "WEBP", (2000, 2000)))
		# Üst kenar dolgu: beyaz; merkez: ürün rengi.
		self.assertEqual(im.convert("RGB").getpixel((1000, 5)), (255, 255, 255))
		r, g, b = im.convert("RGB").getpixel((1000, 1000))
		self.assertTrue(r > 150 and g < 90)

	def test_kucuk_buyutulmez_1000_tuval(self):
		out, s = kare.kareye_cevir(_img(600, 500))
		im = _ac(out).convert("RGB")
		self.assertEqual((s, im.size), (1000, (1000, 1000)))
		# Görsel 600 px genişlikte kalır: x=150 beyaz, x=250 kırmızı.
		self.assertEqual(im.getpixel((150, 500)), (255, 255, 255))
		self.assertTrue(im.getpixel((250, 500))[0] > 150)

	def test_dikey_800x1000(self):
		out, s = kare.kareye_cevir(_img(800, 1000))
		im = _ac(out).convert("RGB")
		self.assertEqual(im.size, (1000, 1000))
		self.assertEqual(im.getpixel((50, 500)), (255, 255, 255))

	def test_seffaf_png_beyaz(self):
		out, _s = kare.kareye_cevir(_img(1200, 600, "RGBA", (0, 0, 0, 0), "PNG"))
		im = _ac(out)
		self.assertNotIn("A", im.mode)
		self.assertEqual(im.convert("RGB").getpixel((600, 600)), (255, 255, 255))

	def test_cmyk_jpeg(self):
		out, s = kare.kareye_cevir(_img(1200, 900, "CMYK", (0, 0, 0, 0)))
		self.assertEqual(_ac(out).size, (1200, 1200))

	def test_exif_dondurme(self):
		im = Image.new("RGB", (1600, 1000), (10, 200, 10))
		exif = im.getexif()
		exif[0x0112] = 6  # 90° döndür → 1000x1600
		buf = io.BytesIO()
		im.save(buf, "JPEG", exif=exif)
		out, s = kare.kareye_cevir(buf.getvalue())
		self.assertEqual(s, 1600)
		# Döndürülmüş görsel dikey: sol kenar beyaz dolgu.
		self.assertEqual(_ac(out).convert("RGB").getpixel((5, 800)), (255, 255, 255))

	def test_zaten_kare_atlar(self):
		with self.assertRaises(kare.Atla) as c:
			kare.kareye_cevir(_img(1200, 1200))
		self.assertEqual(c.exception.reason, "already_square")

	def test_animasyonlu_gif_atlar(self):
		frames = [Image.new("P", (1200, 800), i) for i in range(2)]
		buf = io.BytesIO()
		frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:])
		with self.assertRaises(kare.Atla) as c:
			kare.kareye_cevir(buf.getvalue())
		self.assertEqual(c.exception.reason, "animated")

	def test_bozuk_icerik(self):
		with self.assertRaises(kare.Atla) as c:
			kare.kareye_cevir(b"not an image")
		self.assertEqual(c.exception.reason, "unreadable")
```

- [ ] **Step 2: Kırmızıyı doğrula**

Önce test dosyası konteynere kopyalanır:

```bash
docker cp tradehub_core/tradehub_core/tests/test_media_kare.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/tests/
```

Sonra testler çalıştırılır:

```bash
docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_kare"
```

Beklenen: `ModuleNotFoundError: tradehub_core.media.kare`.

- [ ] **Step 3: Uygula**

```python
"""Ürün görseli: kare, 1000–2000 px, beyaz dolgu.

Spec: docs/superpowers/specs/2026-09-29-urun-gorseli-kare-design.md

Saf katman (bu bölüm) diske/DB'ye dokunmaz; taşıma katmanı aşağıda (Task 2).
"""

from __future__ import annotations

import io

MIN_KENAR = 1000
MAX_KENAR = 2000
WEBP_QUALITY = 85
BEYAZ = (255, 255, 255)


class Atla(Exception):
	"""Dosya bu işlemin konusu değil — hata değil, gerekçeli atlama."""

	def __init__(self, reason: str):
		super().__init__(reason)
		self.reason = reason


def kare_boyutu(w: int, h: int) -> int | None:
	"""Hedef kare kenarı; dokunulmayacaksa `None` (spec §1)."""
	if w <= 0 or h <= 0:
		return None
	if w == h and MIN_KENAR <= w <= MAX_KENAR:
		return None
	return max(MIN_KENAR, min(MAX_KENAR, max(w, h)))


def kareye_cevir(icerik: bytes) -> tuple[bytes, int]:
	"""`(webp, S)`. Görsel asla büyütülmez; beyaz S×S tuvalin ortasına konur."""
	from PIL import Image, ImageOps, UnidentifiedImageError

	try:
		im = Image.open(io.BytesIO(icerik))
		im.load()
	except (UnidentifiedImageError, OSError, ValueError) as exc:
		raise Atla("unreadable") from exc
	if getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1:
		raise Atla("animated")

	im = ImageOps.exif_transpose(im)
	s = kare_boyutu(im.width, im.height)
	if s is None:
		raise Atla("already_square")

	# Alfa (RGBA, LA, şeffaf P) beyaz zemine düzlenir; CMYK/L vb. RGB'ye.
	if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
		rgba = im.convert("RGBA")
		zemin = Image.new("RGB", rgba.size, BEYAZ)
		zemin.paste(rgba, mask=rgba.getchannel("A"))
		im = zemin
	elif im.mode != "RGB":
		im = im.convert("RGB")

	im.thumbnail((MAX_KENAR, MAX_KENAR))  # yalnız küçültür
	tuval = Image.new("RGB", (s, s), BEYAZ)
	tuval.paste(im, ((s - im.width) // 2, (s - im.height) // 2))

	buf = io.BytesIO()
	tuval.save(buf, "WEBP", quality=WEBP_QUALITY, method=4)
	return buf.getvalue(), s
```

- [ ] **Step 4: Yeşili doğrula**

`kare.py` konteynere kopyalanır:

```bash
docker cp tradehub_core/tradehub_core/media/kare.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/media/
```

Step 2'deki test komutu tekrar çalıştırılır. Beklenen: 11 test OK.

- [ ] **Step 5: Lint**

```bash
cd tradehub_core && uvx ruff check tradehub_core/media/kare.py tradehub_core/tests/test_media_kare.py && uvx ruff format --check tradehub_core/media/kare.py tradehub_core/tests/test_media_kare.py
```

Commit etme; diff hazır bırakılır.

---

### Task 2: Dosya başına taşıma, iş ve geri alma

**Files:**
- Modify: `tradehub_core/tradehub_core/media/kare.py` (Task 1'in altına ekle)
- Test: `tradehub_core/tradehub_core/tests/test_media_kare_job.py`

**Interfaces:**
- Consumes (Task 1): `kareye_cevir`, `kare_boyutu`, `Atla`.
- Consumes (mevcut):
  - `retro_rename`: `_disk_path`, `_clear_404_cache`, `_invalidate_url_caches`, `claim_active`, `acquire_or_refresh_active`, `release_active`, `read_progress`, `_write_progress`, `request_stop`, `_stop_requested`, `_new_state`, `_heartbeat`, `_bump_reason`, `REDIRECT_TTL_DAYS`, `ERROR_RATE_STOP`, `DEFAULT_BATCH`.
  - `refs`: `find`, `retarget`, `restore_retarget_changes`.
  - `archive`: `store`, `read`, `drop`, `exists`.
  - `naming`: `_hashed_name`, `_shard`.
  - `seo_url.assign_code`, `av.in_quarantine`, `av.in_hold`.
- Produces:
  - `URUN_KINDS: frozenset[str]` = `{"listing_main", "listing_gallery", "variant_main", "variant_gallery", "cart_snapshot", "favorite_snapshot", "storefront"}`
  - `JOB_PREFIX = "kare-"`, `AUTO_JOB_KEY = "kare-auto"`
  - `urun_gorseli_mi(url: str) -> tuple[bool, bool]`: `(urun_mu, siparis_referansi_var_mi)`
  - `aday_urls() -> list[str]`
  - `normalize_one(url: str, job_key: str, expires_at, *, dry_run: bool = False) -> dict`: `{status: converted|skipped|error, reason, target_url, refs_updated, refs_skipped}`
  - `rollback_one(row: frappe._dict) -> dict`: `{ok, reason, refs_updated, refs_skipped}`
  - `run_job(job_key: str, dry_run: int = 0, batch_size: int = 200) -> None`
  - `run_rollback(job_key: str, rollback_key: str) -> None`
  - `normalize_listing(listing: str) -> dict`

- [ ] **Step 1: Failing entegrasyon testlerini yaz**

```python
"""Ürün görseli kare — dosya/iş/geri alma entegrasyonu (spec 2026-09-29 §4.1, §6)."""

import io
import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tradehub_core.media import archive, kare, retro_rename


def _jpeg(w, h, color=(180, 40, 40)):
	buf = io.BytesIO()
	Image.new("RGB", (w, h), color).save(buf, "JPEG", quality=90)
	return buf.getvalue()


class _Base(FrappeTestCase):
	def setUp(self):
		self.sfx = frappe.generate_hash(length=8)
		self.job = f"kare-test-{self.sfx}"
		self.addCleanup(self._temizle)

	def _dosya(self, w, h):
		"""İçerik-adresli public File (normal yükleme yolu, naming kancası)."""
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"kare-{self.sfx}-{w}x{h}.jpg",
				"is_private": 0,
				"content": _jpeg(w, h, (w % 255, 40, 40)),
			}
		).insert(ignore_permissions=True)
		self.urls = [*getattr(self, "urls", []), doc.file_url]
		return doc.file_url

	def _ilan(self, primary, gallery=()):
		seller = frappe.get_all("Admin Seller Profile", pluck="name", limit=1)[0]
		category = frappe.get_all("Product Category", pluck="name", limit=1)[0]
		doc = frappe.get_doc(
			{
				"doctype": "Listing",
				"title": f"Kare Test {self.sfx}",
				"seller_profile": seller,
				"category": category,
				"primary_image": primary,
				"listing_images": [{"image": g} for g in gallery],
			}
		)
		doc.flags.ignore_validate = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		self.ilanlar = [*getattr(self, "ilanlar", []), doc.name]
		return doc.name

	def _temizle(self):
		for row in frappe.get_all(
			"Media URL Redirect", filters={"job_key": ["like", "kare-test-%"]}, fields=["name", "source_url"]
		):
			frappe.delete_doc("Media URL Redirect", row.name, force=True, ignore_permissions=True)
			archive.drop(row.source_url)
		for ad in getattr(self, "ilanlar", []):
			frappe.delete_doc("Listing", ad, force=True, ignore_permissions=True)
		# Yalnız bu testin açtığı dosyalar (ad önekiyle) — gerçek veriye dokunma.
		for ad in frappe.get_all("File", filters={"file_name": ["like", f"kare-{self.sfx}%"]}, pluck="name"):
			frappe.delete_doc("File", ad, force=True, ignore_permissions=True)
		frappe.db.commit()


class TestNormalizeOne(_Base):
	def test_cevirir_referans_redirect_arsiv(self):
		url = self._dosya(1600, 1000)
		ilan = self._ilan(url)
		out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["status"], "converted", out)
		yeni = out["target_url"]
		self.assertTrue(yeni.endswith(".webp"))
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), yeni)
		with Image.open(retro_rename._disk_path(yeni)) as im:
			self.assertEqual(im.size, (1600, 1600))
		self.assertFalse(os.path.exists(retro_rename._disk_path(url)))  # 301 devreye girsin
		self.assertTrue(archive.exists(url))
		self.assertEqual(frappe.db.get_value("Media URL Redirect", {"source_url": url}, "target_url"), yeni)

	def test_zaten_kare_atlanir(self):
		url = self._dosya(1200, 1200)
		self._ilan(url)
		self.assertEqual(kare.normalize_one(url, self.job, None)["reason"], "already_square")

	def test_prova_diske_dokunmaz(self):
		url = self._dosya(1600, 1000)
		self._ilan(url)
		out = kare.normalize_one(url, self.job, None, dry_run=True)
		self.assertEqual((out["status"], out["reason"]), ("converted", "dry_run"))
		self.assertTrue(os.path.exists(retro_rename._disk_path(url)))
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": url}))

	def test_urun_disi_referans_atlanir(self):
		url = self._dosya(1600, 1000)
		self._ilan(url)
		brand = frappe.get_all("Brand", pluck="name", limit=1)
		if not brand:
			self.skipTest("Brand yok")
		eski = frappe.db.get_value("Brand", brand[0], "logo")
		frappe.db.set_value("Brand", brand[0], "logo", url)
		self.addCleanup(lambda: frappe.db.set_value("Brand", brand[0], "logo", eski))
		self.assertEqual(kare.normalize_one(url, self.job, None)["reason"], "not_product")

	def test_iki_ilan_tek_donusum(self):
		url = self._dosya(900, 700)
		a, b = self._ilan(url), self._ilan(self._dosya(1200, 1200), gallery=[url])
		out = kare.normalize_one(url, self.job, None)
		self.assertEqual(out["refs_updated"], 2, out)
		self.assertEqual(frappe.db.get_value("Listing", a, "primary_image"), out["target_url"])
		self.assertEqual(
			frappe.db.get_value("Listing Image", {"parent": b}, "image"), out["target_url"]
		)

	def test_ikinci_cagri_idempotent(self):
		url = self._dosya(1600, 1000)
		self._ilan(url)
		kare.normalize_one(url, self.job, None)
		self.assertEqual(kare.normalize_one(url, self.job, None)["reason"], "disk_missing")


class TestRollback(_Base):
	def test_geri_alma_hepsini_dondurur(self):
		url = self._dosya(1600, 1000)
		ilan = self._ilan(url)
		yeni = kare.normalize_one(url, self.job, None)["target_url"]
		row = frappe.get_all(
			"Media URL Redirect",
			filters={"source_url": url},
			fields=["name", "source_url", "target_url", "file_names", "ref_changes"],
		)[0]
		out = kare.rollback_one(row)
		self.assertTrue(out["ok"], out)
		self.assertEqual(frappe.db.get_value("Listing", ilan, "primary_image"), url)
		self.assertTrue(os.path.exists(retro_rename._disk_path(url)))
		self.assertFalse(os.path.exists(retro_rename._disk_path(yeni)))
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": url}))
		self.assertFalse(archive.exists(url))


class TestNormalizeListing(_Base):
	def test_ilan_gorsellerini_cevirir(self):
		ana, gal = self._dosya(1600, 1000), self._dosya(800, 1000)
		ilan = self._ilan(ana, gallery=[gal])
		ozet = kare.normalize_listing(ilan)
		self.assertEqual(ozet["converted"], 2, ozet)
		self.assertTrue(frappe.db.get_value("Listing", ilan, "primary_image").endswith(".webp"))
```

- [ ] **Step 2: Kırmızıyı doğrula**

Task 1'deki `docker cp` ve `bench run-tests --module tradehub_core.tests.test_media_kare_job` kalıbıyla çalıştırılır. Beklenen: `AttributeError: module 'tradehub_core.media.kare' has no attribute 'normalize_one'`.

- [ ] **Step 3: Uygula** (`kare.py` sonuna)

```python
# ─── Taşıma katmanı ────────────────────────────────────────────────────────
# (Uygulayıcı: bu import'ları dosyanın başındaki import bloğuna taşı — Ruff I001.)
import hashlib
import json
import os

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime
from frappe.utils.synchronization import filelock

from tradehub_core.media import archive, audit, naming, refs, retro_rename, seo_url

URUN_KINDS = frozenset(
	{"listing_main", "listing_gallery", "variant_main", "variant_gallery", "cart_snapshot",
	 "favorite_snapshot", "storefront"}
)
JOB_PREFIX = "kare-"
AUTO_JOB_KEY = "kare-auto"
_GORSEL_UZANTI = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".gif", ".bmp")


def _skip(reason: str, **extra) -> dict:
	return {"status": "skipped", "reason": reason, "target_url": None, "refs_updated": 0,
			"refs_skipped": 0, **extra}


def urun_gorseli_mi(url: str) -> tuple[bool, bool]:
	"""`(urun_mu, siparis_var_mi)`. Ürün dışı canlı kaynak varsa ürün sayılmaz."""
	bulunan = refs.find(url)
	canli = [r for r in bulunan if not r["readonly"]]
	urun = bool(canli) and all(r["kind"] in URUN_KINDS for r in canli) and any(
		r["kind"] in ("listing_main", "listing_gallery", "variant_main", "variant_gallery") for r in canli
	)
	return urun, any(r["readonly"] for r in bulunan)


def _gorsel_url(url: str | None) -> bool:
	u = (url or "").split("?")[0].lower()
	return (
		u.startswith(retro_rename.PUBLIC_PREFIX)
		and not u.startswith(retro_rename.MEDIA_PREFIX)
		and u.endswith(_GORSEL_UZANTI)
	)


def _listing_urls(listings: list[str] | None = None) -> list[str]:
	"""İlan görsel alanlarındaki distinct adresler; `listings` verilirse yalnız onlar."""
	f_ana = {"name": ["in", listings]} if listings else {}
	f_cocuk = {"parent": ["in", listings]} if listings else {}
	urls = set(frappe.get_all("Listing", filters=f_ana, pluck="primary_image"))
	urls |= set(frappe.get_all("Listing Image", filters=f_cocuk, pluck="image"))
	for row in frappe.get_all(
		"Listing Variant Item", filters=f_cocuk, fields=["variant_image", "variant_gallery"]
	):
		urls.add(row.variant_image)
		try:
			galeri = json.loads(row.variant_gallery or "[]")
		except (TypeError, ValueError):
			galeri = []
		urls |= {g for g in galeri if isinstance(g, str)}
	return sorted(u for u in urls if _gorsel_url(u))


def aday_urls() -> list[str]:
	"""Tüm ilanlardaki ürün görseli adresleri (toplu işin girdisi)."""
	return _listing_urls()


def normalize_one(url: str, job_key: str, expires_at, *, dry_run: bool = False) -> dict:
	"""Tek dosya: kare içerik yeni adrese → File/ref → 301 → arşiv → eski diskten kalkar."""
	from tradehub_core.media import av

	if not _gorsel_url(url):
		return _skip("not_image")
	# Aynı dosyayı ürün-kaydı işi ile toplu iş aynı anda işlemesin.
	# `frappe.generate_hash(txt)` v15'te metni YOK SAYAR (rastgele) — kilit adı deterministik olmalı.
	with filelock(f"kare-{hashlib.sha1(url.encode()).hexdigest()[:16]}", timeout=120):
		old_path = retro_rename._disk_path(url)
		if not os.path.isfile(old_path):
			return _skip("disk_missing")
		if av.in_quarantine(url) or av.in_hold(url):
			return _skip("quarantined")
		if archive.exists(url):
			# Optimize arşivi bu adla dolu: üzerine yazamayız, geri alma kırılır.
			return _skip("archived")
		urun, siparis = urun_gorseli_mi(url)
		if not urun:
			return _skip("not_product")
		with open(old_path, "rb") as f:
			eski = f.read()
		try:
			yeni_icerik, _s = kareye_cevir(eski)
		except Atla as a:
			return _skip(a.reason)
		stem = os.path.splitext(os.path.basename(url))[0]
		hashed = naming._hashed_name(f"{stem}.webp", yeni_icerik)
		new_url = f"{retro_rename.PUBLIC_PREFIX}{naming._shard(hashed)}/{hashed}"
		if dry_run:
			return {"status": "converted", "reason": "dry_run", "target_url": new_url,
					"refs_updated": 0, "refs_skipped": 0}
		return _uygula(url, new_url, old_path, eski, yeni_icerik, job_key, expires_at, siparis)


def _uygula(url, new_url, old_path, eski, yeni_icerik, job_key, expires_at, siparis) -> dict:
	new_path = retro_rename._disk_path(new_url)
	yeni_yazildi = False
	try:
		frappe.create_folder(os.path.dirname(new_path))
		if not os.path.isfile(new_path):
			with open(new_path, "wb") as f:
				f.write(yeni_icerik)
			yeni_yazildi = True
		archive.store(url, eski)
	except OSError:
		frappe.log_error(title=f"Kare: disk yazılamadı {url}", message=frappe.get_traceback())
		if yeni_yazildi:
			os.remove(new_path)
		return {"status": "error", "reason": "disk_write", "target_url": new_url,
				"refs_updated": 0, "refs_skipped": 0}
	try:
		adlar = frappe.get_all("File", filters={"file_url": url}, pluck="name")
		for ad in adlar:
			frappe.db.set_value(
				"File", ad,
				{"file_url": new_url, "file_size": len(yeni_icerik), "seo_code": None},
				update_modified=False,
			)
		ref_result = refs.retarget(url, new_url)
		try:
			seo_url.assign_code(new_url)
		except Exception:
			frappe.log_error(title=f"SEO kodu atanamadı: {new_url}", message=frappe.get_traceback())
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": url,
				"target_url": new_url,
				"job_key": job_key,
				"expires_at": expires_at or add_days(now_datetime(), retro_rename.REDIRECT_TTL_DAYS),
				"file_rows": len(adlar),
				"file_names": json.dumps(adlar),
				"ref_changes": json.dumps(ref_result.get("changes") or [], ensure_ascii=True),
			}
		).insert(ignore_permissions=True)  # sistem işi: çağıran System Manager kapısı ya da kuyruk
		retro_rename._invalidate_url_caches(url, new_url)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		if yeni_yazildi:
			try:
				os.remove(new_path)
			except OSError:
				pass
		archive.drop(url)
		frappe.log_error(title=f"Kare başarısız {url}", message=frappe.get_traceback())
		return {"status": "error", "reason": "exception", "target_url": new_url,
				"refs_updated": 0, "refs_skipped": 0}

	reason = ""
	if siparis:
		# Sipariş geçmişi eski adresi gösteriyor: dosya yerinde kalır (spec Global Constraints).
		reason = "kept_for_orders"
	else:
		try:
			os.remove(old_path)
		except OSError:
			reason = "leftover"
			frappe.log_error(title=f"Kare: eski dosya silinemedi {url}", message=frappe.get_traceback())
	retro_rename._clear_404_cache()
	audit.log_media_event(
		action=audit.ACTION_RETRO_RENAME,
		file_url=new_url,
		context={"operation": "kare", "old_url": url, "job_key": job_key,
				 "refs_updated": ref_result["total"], "kept": bool(siparis)},
	)
	return {"status": "converted", "reason": reason, "target_url": new_url,
			"refs_updated": ref_result["total"], "refs_skipped": len(ref_result["skipped"])}


def rollback_one(row: frappe._dict) -> dict:
	"""Arşivdeki orijinali geri koy, File/ref'leri eski adrese döndür, 301'i sil."""
	basarisiz = {"ok": False, "reason": "rollback_failed", "refs_updated": 0, "refs_skipped": 0}
	old_path = retro_rename._disk_path(row.source_url)
	new_path = retro_rename._disk_path(row.target_url)
	yazildi = False
	try:
		if not os.path.isfile(old_path):
			eski = archive.read(row.source_url)
			frappe.create_folder(os.path.dirname(old_path))
			with open(old_path, "wb") as f:
				f.write(eski)
			yazildi = True
	except Exception:
		frappe.log_error(title=f"Kare geri alma: arşiv yok {row.source_url}", message=frappe.get_traceback())
		return {**basarisiz, "reason": "archive_missing"}
	try:
		adaylar = json.loads(row.file_names or "[]")
		geri = frappe.get_all(
			"File", filters={"file_url": row.target_url, "name": ["in", adaylar or [""]]}, pluck="name"
		)
		boyut = os.path.getsize(old_path)
		for ad in geri:
			frappe.db.set_value(
				"File", ad, {"file_url": row.source_url, "file_size": boyut, "seo_code": None},
				update_modified=False,
			)
		ref_result = refs.restore_retarget_changes(json.loads(row.ref_changes or "[]"))
		frappe.delete_doc("Media URL Redirect", row.name, ignore_permissions=True, force=True)
		retro_rename._invalidate_url_caches(row.source_url, row.target_url)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		if yazildi:
			os.remove(old_path)
		frappe.log_error(title=f"Kare geri alma başarısız {row.source_url}", message=frappe.get_traceback())
		return {**basarisiz, "reason": "db_restore"}

	kalan = frappe.db.count("File", {"file_url": row.target_url})
	paylasan = frappe.db.count("Media URL Redirect", {"target_url": row.target_url})
	if not kalan and not paylasan and os.path.isfile(new_path):
		try:
			os.remove(new_path)
		except OSError:
			frappe.log_error(title=f"Kare geri alma: hedef silinemedi {row.target_url}")
	archive.drop(row.source_url)
	retro_rename._clear_404_cache()
	return {"ok": True, "reason": "", "refs_updated": ref_result["total"],
			"refs_skipped": len(ref_result["skipped"])}


def run_job(job_key: str, dry_run: int = 0, batch_size: int = retro_rename.DEFAULT_BATCH) -> None:
	"""Toplu iş (panel). Kilit ve ilerleme retro-rename ile ORTAK: ikisi aynı anda çalışmaz."""
	if not retro_rename.acquire_or_refresh_active(job_key):
		durum = retro_rename._new_state(0, "kare", bool(dry_run))
		durum.update(state="error", message=_("Başka bir medya işi aktif; bu iş çalıştırılmadı."))
		retro_rename._write_progress(job_key, durum)
		return
	try:
		urls = aday_urls()
		expires_at = add_days(now_datetime(), retro_rename.REDIRECT_TTL_DAYS)
		durum = retro_rename._new_state(len(urls), "kare", bool(dry_run), expires_at)
		retro_rename._write_progress(job_key, durum)
		batch = max(1, int(batch_size or retro_rename.DEFAULT_BATCH))
		for i, url in enumerate(urls):
			if i % batch == 0:
				if retro_rename._stop_requested(job_key):
					durum.update(state="stopped", message=_("Operatör durdurdu."))
					break
				if durum["processed"] and durum["errors"] / durum["processed"] > retro_rename.ERROR_RATE_STOP:
					durum.update(state="partial", message=_("Hata oranı eşiği aşıldı; iş durduruldu."))
					break
			out = normalize_one(url, job_key, expires_at, dry_run=bool(dry_run))
			durum["processed"] += 1
			durum["refs_updated"] += int(out.get("refs_updated") or 0)
			durum["refs_skipped"] += int(out.get("refs_skipped") or 0)
			if out["status"] == "converted":
				durum["renamed"] += 1
				if out["reason"] in ("kept_for_orders", "leftover"):
					retro_rename._bump_reason(durum, out["reason"])
			elif out["status"] == "skipped":
				durum["skipped"] += 1
				retro_rename._bump_reason(durum, out["reason"])
			else:
				durum["errors"] += 1
				retro_rename._bump_reason(durum, out["reason"])
			if durum["processed"] % 25 == 0:
				retro_rename._heartbeat(job_key, durum)
		else:
			durum["state"] = "partial" if durum["errors"] else "completed"
		retro_rename._write_progress(job_key, durum)
	except Exception:
		durum = retro_rename.read_progress(job_key)
		durum.update(state="error", message=_("İşlem tamamlanamadı."))
		retro_rename._write_progress(job_key, durum)
		frappe.log_error(title=f"Kare işi başarısız: {job_key}", message=frappe.get_traceback())
	finally:
		retro_rename.release_active(job_key)
		frappe.cache.delete_value(retro_rename._stop_key(job_key))
		retro_rename._clear_404_cache()


def run_rollback(job_key: str, rollback_key: str) -> None:
	rows = frappe.get_all(
		"Media URL Redirect",
		filters={"job_key": job_key},
		fields=["name", "source_url", "target_url", "file_names", "ref_changes"],
		order_by="creation desc",
	)
	durum = retro_rename._new_state(len(rows), "rollback", False)
	retro_rename._write_progress(rollback_key, durum)
	if not retro_rename.acquire_or_refresh_active(rollback_key):
		durum.update(state="error", message=_("Başka bir medya işi aktif; geri alma çalıştırılmadı."))
		retro_rename._write_progress(rollback_key, durum)
		return
	try:
		for row in rows:
			out = rollback_one(row)
			durum["processed"] += 1
			durum["renamed" if out["ok"] else "errors"] += 1
			if not out["ok"]:
				retro_rename._bump_reason(durum, out["reason"])
			if durum["processed"] % 25 == 0:
				retro_rename._heartbeat(rollback_key, durum)
		durum["state"] = "partial" if durum["errors"] else "completed"
	finally:
		retro_rename.release_active(rollback_key)
		retro_rename._clear_404_cache()
	retro_rename._write_progress(rollback_key, durum)


def normalize_listing(listing: str) -> dict:
	"""Tek ilanın görselleri (ürün kaydı kancasından kuyrukla çağrılır)."""
	ozet = {"converted": 0, "skipped": 0, "errors": 0}
	for url in _listing_urls([listing]):
		out = normalize_one(url, AUTO_JOB_KEY, None)
		ozet[{"converted": "converted", "skipped": "skipped"}.get(out["status"], "errors")] += 1
	return ozet
```

Not: `retro_rename._new_state` `mode` parametresini yalnız yüke yazıyor; `"kare"` değeri paneli etkilemez. Yine de uygulayıcı `_new_state` imzasını kontrol etmeli. `_stop_key` retro_rename'de mevcut.

- [ ] **Step 4: Yeşili doğrula** — 8 test OK. Ayrıca `test_media_retro_rename` modülü de çalıştırılır (ortak yardımcılar bozulmadı mı).
- [ ] **Step 5: Lint** (Task 1'deki komut, iki dosya). Commit etme.

---

### Task 3: Ürün kaydı tetiği

**Files:**
- Modify: `tradehub_core/tradehub_core/media/kare.py` (en sona)
- Modify: `tradehub_core/tradehub_core/hooks.py` (`doc_events["Listing"]["on_update"]` listesinin SONUNA ekle; silme/yeniden yazma yok)
- Test: `tradehub_core/tradehub_core/tests/test_media_kare_job.py` (`TestListingHook` sınıfı eklenir)

**Interfaces:**
- Consumes: `normalize_listing` (Task 2).
- Produces: `on_listing_update(doc, method=None) -> None`.

- [ ] **Step 1: Failing test**

```python
from unittest.mock import patch


class TestListingHook(_Base):
	def test_kayit_kuyruga_atar(self):
		url = self._dosya(1600, 1000)
		ilan = self._ilan(url)
		with patch("frappe.enqueue") as enq:
			doc = frappe.get_doc("Listing", ilan)
			kare.on_listing_update(doc)
		kw = enq.call_args.kwargs
		self.assertEqual(enq.call_args.args[0], "tradehub_core.media.kare.normalize_listing")
		self.assertEqual(kw["listing"], ilan)
		self.assertTrue(kw["enqueue_after_commit"])
		self.assertEqual(kw["job_id"], f"kare-listing-{ilan}")

	def test_gorselsiz_ilan_kuyruga_atmaz(self):
		ilan = self._ilan(None)
		with patch("frappe.enqueue") as enq:
			kare.on_listing_update(frappe.get_doc("Listing", ilan))
		enq.assert_not_called()

	def test_hook_kayitli(self):
		from tradehub_core import hooks

		self.assertIn(
			"tradehub_core.media.kare.on_listing_update", hooks.doc_events["Listing"]["on_update"]
		)
```

- [ ] **Step 2: Kırmızı.**
- [ ] **Step 3: Uygula**

```python
def on_listing_update(doc, method=None) -> None:
	"""Ürün kaydı: görsel varsa kareleme kuyruğa (commit sonrası, ilan başına tek iş)."""
	if frappe.flags.in_import or frappe.flags.in_migrate:
		return
	gorseller = [doc.get("primary_image")]
	gorseller += [r.get("image") for r in doc.get("listing_images") or []]
	if not any(_gorsel_url(u) for u in gorseller) and not doc.get("variants"):
		return
	frappe.enqueue(
		"tradehub_core.media.kare.normalize_listing",
		queue="default",
		timeout=600,
		enqueue_after_commit=True,
		job_id=f"kare-listing-{doc.name}",
		deduplicate=True,
		listing=doc.name,
	)
```

`hooks.py` içinde `"on_update": [ ... ]` listesinin son öğesinden sonra şu satır eklenir. Yorum:

```python
# 2026-09-29 — ürün görselini kare 1000–2000 beyaz dolguya çevir (spec urun-gorseli-kare)
```

Eklenecek satır:

```python
"tradehub_core.media.kare.on_listing_update",
```

Uygulayıcı önce child table alan adını doğrular: `listing_images` doğru; varyant tablosunun alanı `variants` değilse `frappe.get_meta("Listing")` ile gerçek adı bulup koda yazar.

- [ ] **Step 4: Yeşil.** `hooks.py` konteynere kopyalanır, ardından `bench --site istoc.localhost clear-cache` çalıştırılır.
- [ ] **Step 5: Lint.** Commit etme.

---

### Task 4: Yönetici uçları

**Files:**
- Modify: `tradehub_core/tradehub_core/api/media_admin.py` (retro-rename bölümünün altına yeni bölüm)
- Test: `tradehub_core/tradehub_core/tests/test_media_admin_square.py`

**Interfaces:**
- Consumes: `kare.aday_urls`, `kare.run_job`, `kare.run_rollback`, `retro_rename.claim_active` / `release_active` / `read_progress` / `request_stop`.
- Produces (whitelist, `tradehub_core.api.media_admin.`):
  - `square_count()` GET → `{"total": int}`
  - `start_square(dry_run=0, batch_size=200)` POST → `{"job_key", "total", "dry_run"}`
  - `get_square_status(job_key)` GET → progress dict
  - `stop_square(job_key)` POST → `{"ok": True}`
  - `rollback_square(job_key)` POST → `{"job_key", "source_job_key"}`

- [ ] **Step 1: Failing test** (kalıp `test_media_admin_retro_rename.py` ile aynı: Guest ve System Manager olmayan kullanıcı `PermissionError`, System Manager enqueue çağrısı `patch` ile yakalanır)

```python
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_admin
from tradehub_core.media import retro_rename


class TestSquareEndpoints(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_yetkisiz(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			media_admin.square_count()

	def test_start_kuyruga_atar_ve_kilidi_alir(self):
		with patch("tradehub_core.media.kare.aday_urls", return_value=["/files/aa/x.jpg"]), patch(
			"frappe.enqueue"
		) as enq:
			out = media_admin.start_square(dry_run=1)
		self.addCleanup(retro_rename.release_active, out["job_key"])
		self.assertEqual(enq.call_args.args[0], "tradehub_core.media.kare.run_job")
		self.assertEqual(enq.call_args.kwargs["dry_run"], 1)
		self.assertEqual(out["total"], 1)

	def test_aday_yoksa_hata(self):
		with patch("tradehub_core.media.kare.aday_urls", return_value=[]):
			with self.assertRaises(frappe.ValidationError):
				media_admin.start_square()

	def test_rollback_kuyruga_atar(self):
		with patch("frappe.enqueue") as enq:
			out = media_admin.rollback_square("kare-abc")
		self.addCleanup(retro_rename.release_active, out["job_key"])
		self.assertEqual(enq.call_args.args[0], "tradehub_core.media.kare.run_rollback")
		self.assertEqual(enq.call_args.kwargs["job_key"], "kare-abc")

	def test_rollback_yalniz_kare_isi(self):
		with self.assertRaises(frappe.ValidationError):
			media_admin.rollback_square("retro123")
```

- [ ] **Step 2: Kırmızı.**
- [ ] **Step 3: Uygula**

```python
# ─── 2026-09-29 ürün görseli kare (spec urun-gorseli-kare) ──────────────────
# İş mantığı `media/kare.py`; kilit ve ilerleme retro-rename ile ortak.


@frappe.whitelist(methods=["GET"])
def square_count() -> dict:
	_guard_destructive()
	from tradehub_core.media import kare

	return {"total": len(kare.aday_urls())}


@frappe.whitelist(methods=["POST"])
def start_square(dry_run: int = 0, batch_size: int = 200) -> dict:
	_guard_destructive()
	from tradehub_core.media import kare

	total = len(kare.aday_urls())
	if not total:
		frappe.throw(_("Kareye çevrilecek ürün görseli yok."))
	job_key = f"{kare.JOB_PREFIX}{frappe.generate_hash(length=12)}"
	if not retro_rename.claim_active(job_key):
		frappe.throw(_("Zaten çalışan bir medya işi var."))
	try:
		frappe.enqueue(
			"tradehub_core.media.kare.run_job",
			queue="long",
			timeout=4 * 3600,
			enqueue_after_commit=True,
			job_key=job_key,
			dry_run=int(dry_run or 0),
			batch_size=min(2000, max(1, int(batch_size or 200))),
		)
	except Exception:
		retro_rename.release_active(job_key)
		raise
	return {"job_key": job_key, "total": total, "dry_run": int(dry_run or 0)}


@frappe.whitelist(methods=["GET"])
def get_square_status(job_key: str) -> dict:
	_guard_destructive()
	return retro_rename.read_progress(job_key)


@frappe.whitelist(methods=["POST"])
def stop_square(job_key: str) -> dict:
	_guard_destructive()
	retro_rename.request_stop(job_key)
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def rollback_square(job_key: str) -> dict:
	_guard_destructive()
	from tradehub_core.media import kare

	if not (job_key or "").startswith(kare.JOB_PREFIX):
		frappe.throw(_("Yalnız kare işleri buradan geri alınabilir."))
	rollback_key = frappe.generate_hash(length=12)
	if not retro_rename.claim_active(rollback_key):
		frappe.throw(_("Zaten çalışan bir iş var; bitmesini bekleyin."))
	try:
		frappe.enqueue(
			"tradehub_core.media.kare.run_rollback",
			queue="long",
			timeout=4 * 3600,
			enqueue_after_commit=True,
			job_key=job_key,
			rollback_key=rollback_key,
		)
	except Exception:
		retro_rename.release_active(rollback_key)
		raise
	return {"job_key": rollback_key, "source_job_key": job_key}
```

- [ ] **Step 4: Yeşil** (5 test). `test_media_admin_retro_rename` de çalıştırılır.
- [ ] **Step 5: Lint.** Commit etme.

---

### Task 5: Politika — küçük ve oranı tutmayan ürün görseli reddedilmesin

**Files:**
- Modify: `tradehub_core/tradehub_core/media/pipeline/policy/slots/product-image.json`
- Regenerate: `admin-panel/frontend/src/lib/media/policy/vendor/*` (`npm run sync:policy`)
- Modify: politika testlerinde `product.image` için "küçük kenar", "alan" ya da "oran" reddi bekleyen vektörler ve testler. Bulmak için:

```bash
grep -rn "product.image" tradehub_core/tradehub_core/tests admin-panel/frontend/src/lib/media --include=*.py --include=*.js --include=*.json
```

- Modify: `admin-panel/frontend/src/components/media/upload/PreflightPanel.vue` (bilgi satırı) + 4 dil

- [ ] **Step 1:** `product-image.json` değişiklikleri:
  - `require` içinden `min_short_edge`, `min_area`, `allowed_ratios` ve `ratio_tolerance` silinir.
  - `master` bloğu: `"max_long_edge": 2000`, `"min_long_edge": 1000`, `"max_megapixels": 4.0`.
  - `description` sonuna şu cümle eklenir: " Ürüne bağlanan görsel kare 1000–2000 px beyaz dolguya çevrilir (media/kare.py)."
- [ ] **Step 2:** Politika motoru testleri çalıştırılır:
  - Python: `bench run-tests --module tradehub_core.tests.test_media_policy_engine` ve `grep -l policy tradehub_core/tests` ile bulunan diğer modüller.
  - Node: `node --test src/lib/media/policy/__tests__/*.test.js`.
  - `product.image` 800×1000 / 600×500 / 3068×2547 reddi bekleyen vektörler, beklenen sonuç "kabul" (uyarı olabilir) olacak şekilde güncellenir. Vektörü silmek yasak; beklenti güncellenir ve yanına `"not": "2026-09-29 kare kuralı: reddetme yok"` yazılır.
- [ ] **Step 3:** `cd admin-panel/frontend && npm run sync:policy && npm run sync:policy:check`. Beklenen: temiz.
- [ ] **Step 4:** `PreflightPanel.vue`: `slotKey === 'product.image'` iken görsel kare değilse ya da uzun kenarı 1000–2000 dışındaysa bir bilgi satırı gösterilir, `t("media.preflight.squareNote")`:
  - tr: "Görsel kareye tamamlanacak, arka plan beyaz olacak (1000–2000 px)."
  - en: "The image will be made square with a white background (1000–2000 px)."
  - ru: "Изображение будет дополнено до квадрата с белым фоном (1000–2000 px)."
  - ar: "ستُكمَل الصورة إلى مربع بخلفية بيضاء (1000–2000 بكسل)."

  Uygulayıcı bileşenin mevcut uyarı listesi kalıbını okuyup aynı yapıyla ekler.
- [ ] **Step 5:** `npm test` (tüm frontend testleri) ve Python politika testleri yeşil; `npx eslint` ve `prettier --check` değişen dosyalarda. Commit etme.

---

### Task 6: Panel kartı "Ürün görsellerini kareye çevir"

**Files:**
- Create: `admin-panel/frontend/src/composables/useMediaSquare.js`
- Create: `admin-panel/frontend/src/components/media/MediaSquareCard.vue`
- Create: `admin-panel/frontend/src/components/media/__tests__/mediaSquareCard.test.js`
- Modify: `admin-panel/frontend/src/views/system/MediaOptimizeView.vue` (satır ~1262: `<MediaRetroRenameCard …/>` altına `<MediaSquareCard v-if="auth.userRoles?.includes('System Manager')" />` + import)
- Modify: `src/i18n/locales/{tr,en,ru,ar}.js` (`media.square` bloğu)

**Interfaces:**
- Consumes (Task 4): `square_count`, `start_square`, `get_square_status`, `stop_square`, `rollback_square`. Durum yükü retro-rename ile aynı şekilde: `{state, total, processed, renamed, skipped, errors, reasons: {…}, dry_run, message}`.

- [ ] **Step 1:** `useMediaRetroRename.js` ve `MediaRetroRenameCard.vue` okunur; aynı desen izlenir, kopya değil sadeleştirilmiş sürüm yazılır.
  - Sayaç rozeti: "N ürün görseli".
  - "Prova": `start_square(dry_run=1)` → sonuçlar. Etiketler: "Çevrilecek" (`renamed`), "Zaten uygun" (`reasons.already_square`), "Atlanacak" (diğer nedenler, gerekçe dökümüyle).
  - "Başlat": onay penceresi "Görseller kareye çevrilecek; eski adresler 90 gün yönlenecek, orijinaller 30 gün geri alınabilir." → `start_square(dry_run=0)`.
  - İlerleme çubuğu: 2 sn aralıklı `get_square_status`.
  - "Durdur" ve "Geri al": son gerçek işin `job_key`'i `localStorage` anahtarı `th:media:square:lastJob`'da tutulur. try/catch ile sarılır.
  - Yükleniyor ikonu ve kapalı düğme görünümü `MediaRetroRenameCard` ile aynı sınıflarla yapılır.
- [ ] **Step 2:** i18n anahtarları (tr; diğer 3 dile karşılıkları):
  - `title`: "Ürün görsellerini kareye çevir"
  - `desc`: "Ürün görselleri 1000–2000 px kareye tamamlanır, boşluklar beyaz olur. Eski adresler yeni görsele yönlenir."
  - `count`: "{n} ürün görseli"
  - `preview`: "Prova"
  - `start`: "Başlat"
  - `stop`: "Durdur"
  - `rollback`: "Geri al"
  - `willConvert`: "Çevrilecek"
  - `alreadyOk`: "Zaten uygun"
  - `willSkip`: "Atlanacak"
  - `converted`: "Çevrildi"
  - `confirm`: yukarıdaki onay metni
  - `done`: "Tamamlandı"
  - `reason_not_product`: "Ürün dışı kullanım var"
  - `reason_archived`: "Optimize arşivinde"
  - `reason_animated`: "Hareketli görsel"
  - `reason_unreadable`: "Okunamadı"
  - `reason_disk_missing`: "Dosya diskte yok"
  - `reason_kept_for_orders`: "Siparişte kullanıldığı için eski dosya korundu"
- [ ] **Step 3:** `mediaSquareCard.test.js` (`node:test`, `mediaRetroRenameCard.test.js` kalıbı). Test edilecekler:
  - Prova yükü "Çevrilecek / Zaten uygun / Atlanacak" sayılarını doğru eşliyor.
  - Bilinmeyen neden anahtarı ham gösterilmiyor, "Atlanacak" altında genel etiket alıyor.
- [ ] **Step 4:** `npm test`, `npx eslint`, `prettier --check`. Ardından `cd docker && docker compose build admin-panel && docker compose up -d --no-deps admin-panel` ve tarayıcıda kart görünür mü kontrolü (kontrolcü yapar). Commit etme.

---

### Task 7: Lokal uçtan uca (kontrolcü)

- [ ] Backend dosyaları dört konteynere `docker cp` ile kopyalanır: `backend`, `queue-long`, `queue-short`, `scheduler`. Ayrıca `default` kuyruğunu işleyen worker'a da kopyalanır; bunu `docker ps` ile belirle. Sonra `clear-cache` ve `frappe-frontend` restart.
- [ ] Panel → Sistem → Medya → kart: Prova, sayılar kaydedilir.
- [ ] Gerçek koşu. `UR 3373 - yesil.jpg` (3068×2547) kontrolü:
  - Detay panelinde 2000×2000.
  - Eski adres 301 veriyor.
  - Vitrin ürün sayfası, sepet ve favoride kare görünüyor; konsolda kırık görsel yok.
- [ ] Ürün formundan 800×1000 bir görsel yüklenip kaydedilir; birkaç saniye sonra 1000×1000 beyaz dolgulu olmalı.
- [ ] Geri alma denenir: bir test işi geri alınır, adresler eski haline döner. Ardından gerçek koşu tekrar yapılır.
- [ ] Son bütünsel inceleme (en güçlü model) → bulgular düzeltilir → kullanıcıya rapor. Commit kullanıcı onayıyla yapılır.
