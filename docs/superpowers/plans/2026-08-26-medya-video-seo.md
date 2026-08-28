# Medya Video SEO (Dilim 4) — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ürün videolarına poster + süre + transcript/altyazı alanları kazandırıp bunları `VideoObject` JSON-LD, video sitemap, Listing API ve panel/vitrin yüzeylerine bağlamak.

**Architecture:** Poster üretimi CANLI yoldan (`media/transcode.py` akışına eklenen `media/video_poster.py`, ffmpeg "ilk anlamlı kare"); tüm okuma tek kapıdan (`media/seo.fields_for`); dış yüzey mevcut desenlerin kardeşi (ImageObject→VideoObject, `image:image`→`video:video`, imageMeta genişlemesi). Pipeline'ın flag arkasındaki poster'ı AÇILMAZ.

**Tech Stack:** Frappe v15 (FrappeTestCase), ffmpeg/ffprobe (imajda mevcut — `transcode.py` kullanıyor), Pillow (luma kapısı), Vue 3 + node:test (admin-panel), Alpine/TS + Vitest (tradehubfront).

**Spec:** `docs/superpowers/specs/2026-08-26-medya-video-seo-design.md`

## Global Constraints

- Frappe **v15** — `frappe.qb`/`get_list`; `get_all` yalnız system-only bağlamda. Tab indent, line-length 110 (Ruff), type annotation zorunlu, `frappe.throw(_("..."))`.
- Backend testleri `FrappeTestCase`; çalıştırma: `docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.<modül>`.
- Kod dosyaları imaja `docker cp` ile GEÇİCİ taşınır (hafıza notu: recreate bayat kodu geri getirir); kalıcılık için imaj rebuild ayrı adım.
- Admin panel: `node:test` (`npm test`), ESLint (`npm run lint`), i18n `tr`+`en` zorunlu. Vitrin: `npm test` (Vitest).
- SEO alanı okuyan HİÇBİR kod `th_media_*` kolonunu doğrudan okumaz — yalnız `media/seo.fields_for[_many]` (TUR-135 kuralı).
- Commit mesajları Türkçe, conventional prefix. **İş dalı:** `feature/media-video-seo` (üç repoda da; tradehub_core taban: `ahmet`).
- Spec'ten sapma yok; tek plan-düzeyi netleştirme: poster'ı OLMAYAN video için `VideoObject` üretilmez (Google `thumbnailUrl`'ü zorunlu sayar; geçersiz yapısal veri hiç üretmemekten kötü) — denetim `missing_poster` ile uyarır. Galeri videolarının künyesi ayrı `videoMeta` listesi yerine mevcut `imageMeta` satırlarına `poster/durationSec/captionsUrl` anahtarları eklenerek taşınır (aynı dizin hizası, ikinci liste sözleşmesi açılmaz); promo video için üst düzey `videoPoster` fallback'i kullanılır.

---

### Task 1: Şema patch'i + okuma kapısı genişlemesi

**Files:**
- Create: `tradehub_core/patches/v15_9_49_media_video_seo.py`
- Modify: `tradehub_core/patches.txt` (sona ekle)
- Modify: `tradehub_core/media/seo.py` (`SINGLE`, `_asset_columns`, `_birlestir`)
- Test: `tradehub_core/tests/test_media_video_seo.py` (yeni)

**Interfaces:**
- Produces: `File` kolonları `th_media_duration` (Float), `th_media_poster_url` (Data), `th_media_transcript` (Long Text), `th_media_captions_url` (Data). `fields_for(url)` dönüşüne `duration`, `poster_url`, `transcript`, `captions_url` anahtarları eklenir. `transcript`/`captions_url` `set_asset_fields` ile yazılabilir (SINGLE'da); `duration`/`poster_url` yalnız sistem yazar (SINGLE'a GİRMEZ — `_asset_columns`/`_birlestir`'de width/height gibi özel durum).

- [ ] **Step 1: Failing test yaz**

```python
# tradehub_core/tradehub_core/tests/test_media_video_seo.py
"""Video SEO şeması ve okuma kapısı — Dilim 4 (spec 2026-08-26)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import seo


class TestVideoSeoSchema(FrappeTestCase):
	def test_video_kolonlari_var(self):
		for kolon in (
			"th_media_duration",
			"th_media_poster_url",
			"th_media_transcript",
			"th_media_captions_url",
		):
			self.assertTrue(frappe.db.has_column("File", kolon), kolon)

	def test_fields_for_video_alanlarini_dondurur(self):
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "test-video-seo.webm",
				"file_url": "/files/test-video-seo.webm",
				"is_private": 0,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		frappe.db.set_value(
			"File",
			doc.name,
			{
				"th_media_duration": 12.5,
				"th_media_poster_url": "/files/poster-abc.jpg",
				"th_media_transcript": "merhaba",
				"th_media_captions_url": "/files/cap.vtt",
			},
			update_modified=False,
		)
		alanlar = seo.fields_for("/files/test-video-seo.webm")
		self.assertEqual(alanlar["duration"], 12.5)
		self.assertEqual(alanlar["poster_url"], "/files/poster-abc.jpg")
		self.assertEqual(alanlar["transcript"], "merhaba")
		self.assertEqual(alanlar["captions_url"], "/files/cap.vtt")

	def test_duration_ve_poster_disaridan_yazilamaz(self):
		# set_asset_fields beyaz listesi: sistem alanları istekten geçmez.
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "test-video-seo2.webm",
				"file_url": "/files/test-video-seo2.webm",
				"is_private": 0,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		n = seo.set_asset_fields(
			"/files/test-video-seo2.webm",
			{"duration": 99, "poster_url": "/files/x.jpg", "transcript": "t1"},
		)
		self.assertEqual(n, 1)  # transcript yazıldı, diğer ikisi elendi
		self.assertFalse(frappe.db.get_value("File", doc.name, "th_media_duration"))
		self.assertFalse(frappe.db.get_value("File", doc.name, "th_media_poster_url"))
		self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_transcript"), "t1")
```

- [ ] **Step 2: Testi çalıştır, FAIL doğrula**

Run: `docker cp` ile dosyaları imaja kopyala, sonra
`docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_video_seo`
Expected: FAIL — kolonlar yok.

- [ ] **Step 3: Patch'i yaz**

```python
# tradehub_core/tradehub_core/patches/v15_9_49_media_video_seo.py
"""Video SEO alanları — poster, süre, transcript, altyazı (Dilim 4).

Karar belgesi: docs/superpowers/specs/2026-08-26-medya-video-seo-design.md §3.
Başlık/açıklama/caption için YENİ kolon YOK — v15_9_37'nin 4 dilli alanları
videoda da geçerli (K3). transcript tek dil (video dilindedir).
İdempotent: create_custom_fields(update=True).
"""

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_media_duration",
			"label": "TH Media Duration (s)",
			"fieldtype": "Float",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_poster_url",
			"label": "TH Media Poster URL",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_transcript",
			"label": "TH Media Transcript",
			"fieldtype": "Long Text",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_captions_url",
			"label": "TH Media Captions URL (WebVTT)",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"module": "Tradehub Core",
		},
	]
}


def execute() -> None:
	create_custom_fields(FIELDS, update=True)
```

`patches.txt` sonuna ekle (yorumla birlikte):

```
# --- Dilim 4 · video SEO: poster + süre + transcript/altyazı ---
tradehub_core.patches.v15_9_49_media_video_seo
```

- [ ] **Step 4: `media/seo.py`'yi genişlet**

`SINGLE` tuple'ına iki satır ekle (yazılabilir alanlar):

```python
	"transcript",
	"captions_url",
```

`_asset_columns` içinde width/height satırının hemen ALTINA ekle (sistem
alanları — SINGLE'a girmez, yazma kapısından geçmez):

```python
	# Video sistem alanları da width/height gibi: SEO metni değil, dosyanın
	# fiziksel gerçeği. SINGLE'a koymamak bilinçli — set_asset_fields'tan
	# yazılamazlar (poster'ı/süreyi yalnız üretim hattı yazar).
	adaylar.extend(("th_media_duration", "th_media_poster_url"))
```

`_birlestir` fonksiyonunda width/height'ın döndürüldüğü yeri bul
(`grep -n "width" tradehub_core/media/seo.py`) ve aynı desenle ekle:

```python
	out["duration"] = kayit.get("th_media_duration") or 0
	out["poster_url"] = kayit.get("th_media_poster_url") or ""
```

(`transcript`/`captions_url` SINGLE'da olduğu için otomatik akar — ekstra kod gerekmez.)

- [ ] **Step 5: Patch'i koştur + testleri çalıştır, PASS doğrula**

```bash
docker cp tradehub_core/tradehub_core/patches/v15_9_49_media_video_seo.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/patches/
docker cp tradehub_core/tradehub_core/media/seo.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/media/
docker cp tradehub_core/tradehub_core/tests/test_media_video_seo.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/tests/
docker exec istoc-dev-backend-1 bench --site istoc.localhost execute tradehub_core.patches.v15_9_49_media_video_seo.execute
docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_video_seo
```
Expected: 3 test PASS.

- [ ] **Step 6: Mevcut SEO regresyonu**

Run: `docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_seo`
Expected: PASS (okuma kapısı genişledi, kırılmadı).

- [ ] **Step 7: Commit**

```bash
git checkout -b feature/media-video-seo
git add tradehub_core/patches/v15_9_49_media_video_seo.py tradehub_core/patches.txt tradehub_core/media/seo.py tradehub_core/tests/test_media_video_seo.py
git commit -m "feat(media): video SEO şeması — poster/süre/transcript/altyazı alanları (Dilim 4)"
```

---

### Task 2: Poster üretimi — `media/video_poster.py`

**Files:**
- Create: `tradehub_core/media/video_poster.py`
- Test: `tradehub_core/tests/test_video_poster.py` (yeni)

**Interfaces:**
- Consumes: Task 1 kolonları; `media/naming.py` hook'u (File insert'te içerik-hash'li ad otomatik).
- Produces: `generate(file_url: str) -> str | None` — poster üretir, `th_media_poster_url` + `th_media_duration` yazar, poster URL döndürür (üretilemezse None). `probe_duration(path: str) -> float`. `backfill_pending(limit: int = 50) -> int` (Task 3 bağlar). İdempotent: poster doluysa ve video değişmediyse no-op.

- [ ] **Step 1: Fixture videoları üret** (test kurulumunda, ffmpeg ile — repo'ya binary koymuyoruz)

```python
# tradehub_core/tradehub_core/tests/test_video_poster.py
"""Poster üretimi — kare seçimi, luma kapısı, idempotens (Dilim 4 spec §4)."""

import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import video_poster


def _yap_video(yol: Path, *, sure: int = 4, siyah_giris: bool = False) -> None:
	"""Küçük test videosu: renkli test deseni; istenirse ilk 1 sn siyah."""
	if siyah_giris:
		filtre = f"color=black:s=320x240:d=1[a];testsrc=s=320x240:d={sure - 1}[b];[a][b]concat"
		cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "nullsrc=s=320x240:d=0.1", "-filter_complex", filtre, "-r", "10", str(yol)]
	else:
		cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=s=320x240:d={sure}", "-r", "10", str(yol)]
	subprocess.run(cmd, check=True, capture_output=True)


class TestVideoPoster(FrappeTestCase):
	def _file_kaydi(self, yol: Path) -> "frappe.model.document.Document":
		with open(yol, "rb") as f:
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": yol.name,
					"is_private": 0,
					"content": f.read(),
				}
			).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		return doc

	def test_normal_videoda_poster_uretilir(self):
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "renkli.mp4"
			_yap_video(v)
			doc = self._file_kaydi(v)
			url = video_poster.generate(doc.file_url)
			self.assertTrue(url and url.endswith(".jpg"))
			self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_poster_url"), url)
			self.assertGreater(float(frappe.db.get_value("File", doc.name, "th_media_duration")), 3.0)
			# Poster dosyası gerçekten var ve public File kaydı açılmış
			self.assertTrue(frappe.db.exists("File", {"file_url": url}))

	def test_siyah_giriste_kare_penceresi_atlar(self):
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "siyah.mp4"
			_yap_video(v, siyah_giris=True)
			doc = self._file_kaydi(v)
			url = video_poster.generate(doc.file_url)
			self.assertTrue(url)  # luma kapısı siyah kareyi elemeli, retry penceresi tutmalı

	def test_idempotent(self):
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "idem.mp4"
			_yap_video(v)
			doc = self._file_kaydi(v)
			ilk = video_poster.generate(doc.file_url)
			ikinci = video_poster.generate(doc.file_url)
			self.assertEqual(ilk, ikinci)  # yeniden üretmez, mevcut URL döner

	def test_bozuk_dosya_none_doner_ve_yayini_dusurmez(self):
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "bozuk.mp4",
				"is_private": 0,
				"content": b"bu bir video degil",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		self.assertIsNone(video_poster.generate(doc.file_url))
```

- [ ] **Step 2: FAIL doğrula** — `run-tests --module tradehub_core.tests.test_video_poster` → "module ... has no attribute" / ImportError.

- [ ] **Step 3: Modülü yaz**

```python
# tradehub_core/tradehub_core/media/video_poster.py
"""Video poster — "ilk anlamlı kare" (Dilim 4, spec §4; kural pipeline
poster.py'den UYARLANDI, kod paylaşılmaz — K1: canlı yol, flag'e bağlanmaz).

Kare seçimi:
  1. Pencere [0.5 sn, min(5 sn, süre × 0.25)]
  2. ffmpeg `thumbnail=n=120` — histogramca en temsili kare
  3. Luma kapısı: ortalama %6–%94; düşerse [süre×0.25, süre×0.50] bir kez daha
  4. O da düşerse poster YOK — video yayında kalır, denetim uyarır.

Hata poster'ı değil videoyu ASLA düşürmez: her hata log + None (spec §4).
"""

from __future__ import annotations

import io
import subprocess
import tempfile
from pathlib import Path

import frappe
from PIL import Image, ImageStat

JPEG_KALITE: int = 82
UZUN_KENAR: int = 1280
LUMA_ALT: float = 255 * 0.06
LUMA_UST: float = 255 * 0.94
FFMPEG_TIMEOUT: int = 120


def probe_duration(path: str) -> float:
	"""ffprobe ile saniye cinsinden süre; okunamazsa 0."""
	try:
		out = subprocess.run(
			[
				"ffprobe", "-v", "error", "-show_entries", "format=duration",
				"-of", "default=noprint_wrappers=1:nokey=1", path,
			],
			capture_output=True, text=True, timeout=30, check=True,
		)
		return float(out.stdout.strip() or 0)
	except Exception:
		return 0.0


def _kare(path: str, baslangic: float, pencere: float) -> bytes | None:
	"""Penceredeki en temsili kareyi JPEG olarak döndür."""
	with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
		hedef = tmp.name
	try:
		subprocess.run(
			[
				"ffmpeg", "-y", "-ss", f"{baslangic:.2f}", "-t", f"{max(pencere, 0.5):.2f}",
				"-i", path,
				"-vf", f"thumbnail=n=120,scale='min({UZUN_KENAR},iw)':-2",
				"-frames:v", "1", "-q:v", "3", hedef,
			],
			capture_output=True, timeout=FFMPEG_TIMEOUT, check=True,
		)
		data = Path(hedef).read_bytes()
		return data or None
	except Exception:
		return None
	finally:
		Path(hedef).unlink(missing_ok=True)


def _luma_ok(jpeg: bytes) -> bool:
	ort = ImageStat.Stat(Image.open(io.BytesIO(jpeg)).convert("L")).mean[0]
	return LUMA_ALT <= ort <= LUMA_UST


def generate(file_url: str) -> str | None:
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		return None
	mevcut = frappe.db.get_value("File", name, "th_media_poster_url")
	if mevcut:
		return mevcut  # idempotent — yeniden üretim regenerate ucundan (Task 7)
	try:
		doc = frappe.get_doc("File", name)
		path = doc.get_full_path()
		sure = probe_duration(path)
		if sure <= 0:
			return None
		jpeg = _kare(path, 0.5, min(5.0, sure * 0.25))
		if jpeg is None or not _luma_ok(jpeg):
			jpeg = _kare(path, sure * 0.25, sure * 0.25)
		if jpeg is None or not _luma_ok(jpeg):
			frappe.db.set_value("File", name, "th_media_duration", sure, update_modified=False)
			return None
		# Yeniden sıkıştırma: kalite sabitle (q:v 3 kaba; hedef ~82)
		img = Image.open(io.BytesIO(jpeg)).convert("RGB")
		cikti = io.BytesIO()
		img.save(cikti, format="JPEG", quality=JPEG_KALITE, progressive=True)
		poster = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"poster-{name}.jpg",
				"is_private": 0,
				"content": cikti.getvalue(),
			}
		).insert(ignore_permissions=True)  # sistem üretimi — kullanıcı akışı değil
		frappe.db.set_value(
			"File", name,
			{"th_media_poster_url": poster.file_url, "th_media_duration": sure},
			update_modified=False,
		)
		return poster.file_url
	except Exception:
		frappe.log_error(title="video_poster.generate", message=frappe.get_traceback())
		return None
```

- [ ] **Step 4: PASS doğrula** — `docker cp` + `run-tests --module tradehub_core.tests.test_video_poster` → 4 test PASS.

- [ ] **Step 5: Commit** — `git add tradehub_core/media/video_poster.py tradehub_core/tests/test_video_poster.py && git commit -m "feat(media): video poster üretimi — ilk anlamlı kare (canlı yol)"`

---

### Task 3: Transcode entegrasyonu + geri doldurma + scheduler

**Files:**
- Modify: `tradehub_core/media/transcode.py` (`enqueue_transcode` hızlı yol, `_run_transcode` başarı sonu)
- Modify: `tradehub_core/media/video_poster.py` (`backfill_pending` ekle)
- Modify: `tradehub_core/hooks.py` (scheduler_events daily)
- Test: `tradehub_core/tests/test_video_poster.py` (ekleme)

**Interfaces:**
- Consumes: `video_poster.generate` (Task 2).
- Produces: her yeni video (transcode'lu ya da değil) poster işi alır; `video_poster.backfill_pending(limit=50) -> int` günlük `media-maint` kuyruğunda koşar.

- [ ] **Step 1: Failing testler ekle** (`test_video_poster.py`'ye)

```python
class TestVideoPosterBackfill(FrappeTestCase):
	def test_backfill_yalniz_postersiz_videolari_alir(self):
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "bf.mp4"
			_yap_video(v)
			with open(v, "rb") as f:
				doc = frappe.get_doc(
					{"doctype": "File", "file_name": "bf.mp4", "is_private": 0, "content": f.read()}
				).insert(ignore_permissions=True)
			self.addCleanup(doc.delete, ignore_permissions=True)
			islenen = video_poster.backfill_pending(limit=10)
			self.assertGreaterEqual(islenen, 1)
			self.assertTrue(frappe.db.get_value("File", doc.name, "th_media_poster_url"))
			# İkinci tur: aynı dosya tekrar işlenmez
			self.assertEqual(video_poster.backfill_pending(limit=10), 0)
```

- [ ] **Step 2: FAIL doğrula** — `backfill_pending` yok → AttributeError.

- [ ] **Step 3: `backfill_pending` yaz** (`video_poster.py` sonuna)

```python
#: Yalnız video uzantıları — upload_policy._SIGNATURES ile uyumlu küme.
VIDEO_UZANTILAR: tuple[str, ...] = (".mp4", ".webm", ".mov", ".m4v", ".mkv")


def backfill_pending(limit: int = 50) -> int:
	"""Postersiz videoları parça parça doldur — av.backfill_pending deseni.

	`media-maint` kuyruğunda günlük koşar (hooks.py). Turda ≤ `limit` video:
	video başına ffmpeg maliyeti görselden büyük, kuyruk boğulmasın (spec §4).
	"""
	kosul = " OR ".join(f"file_url LIKE '%%{u}'" for u in VIDEO_UZANTILAR)
	satirlar = frappe.db.sql(
		f"""SELECT name, file_url FROM `tabFile`
		WHERE is_private = 0 AND ({kosul})
		AND IFNULL(th_media_poster_url, '') = ''
		AND IFNULL(th_media_duration, 0) = 0
		ORDER BY creation DESC LIMIT %(limit)s""",
		{"limit": limit},
		as_dict=True,
	)  # sabit uzantı listesi — kullanıcı girdisi değil, f-string güvenli
	islenen = 0
	for satir in satirlar:
		if generate(satir.file_url):
			islenen += 1
		else:
			# Poster üretilemedi ama duration yazıldıysa tekrar seçilmez;
			# bozuk dosyada ikisi de boş kalır — sonraki turda yine denenir,
			# limit sayesinde kuyruk boğulmaz.
			pass
	return islenen
```

- [ ] **Step 4: Transcode kancaları** — `transcode.py`:

`enqueue_transcode` içindeki `needs_transcode(...)` False dalında, `VIDEO_STATUS_READY` yazımından SONRA ekle:

```python
		frappe.enqueue(
			"tradehub_core.media.video_poster.generate",
			queue="media-maint",
			timeout=300,
			file_url=file_url,
			enqueue_after_commit=True,
		)
```

`_run_transcode` başarı yolunun sonunda (durum `ready` yazıldıktan sonra; `grep -n "VIDEO_STATUS_READY" tradehub_core/media/transcode.py` ile yeri bul) — worker zaten arka planda, doğrudan çağır:

```python
	from tradehub_core.media import video_poster

	video_poster.generate(file_url)  # hata içeride yutulur; transcode'u düşürmez
```

- [ ] **Step 5: Scheduler kaydı** — `hooks.py` `scheduler_events` → `daily` listesine (mevcut medya girdilerinin yanına, `grep -n "backfill_pending" tradehub_core/hooks.py` ile desen bul):

```python
		"tradehub_core.media.video_poster.backfill_pending",
```

- [ ] **Step 6: PASS doğrula** — `run-tests --module tradehub_core.tests.test_video_poster` (tamamı) + `run-tests --module tradehub_core.tests.test_media_transcode` (varsa; `ls tradehub_core/tests | grep transcode` ile bul) → PASS.

- [ ] **Step 7: Commit** — `git commit -m "feat(media): poster üretimi transcode akışına ve günlük geri doldurmaya bağlandı"`

---

### Task 4: `VideoObject` builder — `seo/schema_builder.py`

**Files:**
- Modify: `tradehub_core/seo/schema_builder.py`
- Test: `tradehub_core/tests/test_media_video_seo.py` (ekleme)

**Interfaces:**
- Consumes: `fields_for` çıktısı (Task 1: `duration`, `poster_url`, `transcript` anahtarları dahil).
- Produces: `build_video_object(seo_fields: dict, site_url: str, *, content_url: str = "", embed_url: str = "", upload_date: str = "") -> dict | None` — poster yoksa **None** (Global Constraints'teki netleştirme). `_iso8601_sure(saniye: float) -> str` (`"PT1M5S"`).

- [ ] **Step 1: Failing testler**

```python
class TestVideoObject(FrappeTestCase):
	def test_tam_alanli_video_object(self):
		from tradehub_core.seo.schema_builder import build_video_object

		alanlar = {
			"title": "Ürün tanıtımı",
			"alt": "",
			"caption": "Kısa tanıtım",
			"description": "",
			"poster_url": "/files/poster.jpg",
			"duration": 65.0,
			"transcript": "merhaba dünya",
			"rights_expires_on": "",
		}
		obj = build_video_object(
			alanlar, "https://istoc.localhost",
			content_url="/files/video.webm", upload_date="2026-08-01 10:00:00",
		)
		self.assertEqual(obj["@type"], "VideoObject")
		self.assertEqual(obj["name"], "Ürün tanıtımı")
		self.assertEqual(obj["thumbnailUrl"], "https://istoc.localhost/files/poster.jpg")
		self.assertEqual(obj["contentUrl"], "https://istoc.localhost/files/video.webm")
		self.assertEqual(obj["duration"], "PT1M5S")
		self.assertEqual(obj["transcript"], "merhaba dünya")
		self.assertEqual(obj["uploadDate"], "2026-08-01")
		self.assertNotIn("embedUrl", obj)

	def test_postersiz_video_none(self):
		from tradehub_core.seo.schema_builder import build_video_object

		self.assertIsNone(
			build_video_object(
				{"title": "x", "poster_url": "", "duration": 5},
				"https://istoc.localhost", content_url="/files/v.mp4",
			)
		)

	def test_embed_video(self):
		from tradehub_core.seo.schema_builder import build_video_object

		obj = build_video_object(
			{"title": "Promo", "poster_url": "/files/p.jpg", "duration": 0},
			"https://istoc.localhost", embed_url="https://www.youtube.com/embed/abc",
		)
		self.assertEqual(obj["embedUrl"], "https://www.youtube.com/embed/abc")
		self.assertNotIn("contentUrl", obj)
		self.assertNotIn("duration", obj)  # 0 süre basılmaz
```

- [ ] **Step 2: FAIL doğrula.**

- [ ] **Step 3: Builder'ı yaz** — `schema_builder.py`'ye (`build_image_object`'in altına; `_mutlak` benzeri URL yardımcıları bu dosyada varsa onları kullan, yoksa `seo_urls._absolute` deseni):

```python
def _iso8601_sure(saniye: float) -> str:
	"""65.0 → "PT1M5S"; 0 → "" (basılmaz)."""
	toplam = int(saniye or 0)
	if toplam <= 0:
		return ""
	dk, sn = divmod(toplam, 60)
	sa, dk = divmod(dk, 60)
	parca = "PT"
	if sa:
		parca += f"{sa}H"
	if dk:
		parca += f"{dk}M"
	if sn or parca == "PT":
		parca += f"{sn}S"
	return parca


def build_video_object(
	seo_fields: dict,
	site_url: str,
	*,
	content_url: str = "",
	embed_url: str = "",
	upload_date: str = "",
) -> dict | None:
	"""Tek video için VideoObject — poster yoksa None.

	Google `thumbnailUrl` + `name` + `uploadDate`'i zorunlu sayar; geçersiz
	yapısal veri hiç üretmemekten kötüdür (spec netleştirmesi). Poster'ı
	olmayan video JSON-LD'ye ve video sitemap'e GİRMEZ, denetim uyarır.
	"""
	poster = str(seo_fields.get("poster_url") or "").strip()
	if not poster or not (content_url or embed_url):
		return None

	def _abs(u: str) -> str:
		return u if u.startswith(("http://", "https://")) else f"{site_url.rstrip('/')}/{u.lstrip('/')}"

	ad = str(seo_fields.get("title") or seo_fields.get("alt") or "").strip()
	if not ad:
		return None
	obj: dict = {"@type": "VideoObject", "name": ad, "thumbnailUrl": _abs(poster)}
	aciklama = str(seo_fields.get("caption") or seo_fields.get("description") or "").strip()
	if aciklama:
		obj["description"] = aciklama
	if content_url:
		obj["contentUrl"] = _abs(content_url)
	if embed_url:
		obj["embedUrl"] = embed_url
	sure = _iso8601_sure(float(seo_fields.get("duration") or 0))
	if sure:
		obj["duration"] = sure
	if upload_date:
		obj["uploadDate"] = str(upload_date)[:10]
	transcript = str(seo_fields.get("transcript") or "").strip()
	if transcript:
		obj["transcript"] = transcript
	biter = str(seo_fields.get("rights_expires_on") or "").strip()
	if biter:
		obj["expires"] = biter
	return obj
```

- [ ] **Step 4: PASS doğrula + Commit** — `git commit -m "feat(seo): VideoObject builder — poster zorunlu, embed/dosya ayrımı"`

---

### Task 5: Video sitemap — `seo/sitemap_generator.py`

**Files:**
- Modify: `tradehub_core/seo/sitemap_generator.py`
- Test: `tradehub_core/tests/test_media_video_seo.py` (ekleme)

**Interfaces:**
- Consumes: `fields_for_many` (Task 1 alanları), `media/seo_index.decide` (mevcut), `_image_entries_for_listing` deseni (satır ~274).
- Produces: `VIDEO_NS` sabiti; url girdilerinde `videos: list[dict]` anahtarı (`thumbnail_loc`, `title`, `description`, `content_loc` | `player_loc`, `duration`, `publication_date`, `expiration_date`); `build_urlset_xml` `<video:video>` üretir; `_video_entries_for_listing(row: dict, site: str) -> list[dict]`.

- [ ] **Step 1: Failing test**

```python
class TestVideoSitemap(FrappeTestCase):
	def test_urlset_video_girdisi(self):
		from tradehub_core.seo.sitemap_generator import build_urlset_xml

		xml = build_urlset_xml(
			[
				{
					"loc": "https://s/urun/x",
					"lastmod": "2026-08-26",
					"videos": [
						{
							"thumbnail_loc": "https://s/files/p.jpg",
							"title": "Tanıtım",
							"description": "Kısa",
							"content_loc": "https://s/files/v.webm",
							"duration": 65,
							"publication_date": "2026-08-01",
						}
					],
				}
			]
		)
		self.assertIn('xmlns:video="http://www.google.com/schemas/sitemap-video/1.1"', xml)
		self.assertIn("<video:video>", xml)
		self.assertIn("<video:thumbnail_loc>https://s/files/p.jpg</video:thumbnail_loc>", xml)
		self.assertIn("<video:duration>65</video:duration>", xml)

	def test_videosuz_urlset_namespace_almaz(self):
		from tradehub_core.seo.sitemap_generator import build_urlset_xml

		xml = build_urlset_xml([{"loc": "https://s/", "lastmod": "2026-08-26"}])
		self.assertNotIn("xmlns:video", xml)
```

- [ ] **Step 2: FAIL doğrula.**

- [ ] **Step 3: Uygula** — `sitemap_generator.py`:

Üste sabit (IMAGE_NS'in yanına):

```python
VIDEO_NS: str = "http://www.google.com/schemas/sitemap-video/1.1"
```

`build_urlset_xml` içinde: image ns eklendiği koşulun yanına aynı desenle
`any(u.get("videos") for u in urls)` → `xmlns += f' xmlns:video="{VIDEO_NS}"'`;
`<image:image>` bloğunun altına aynı desenle:

```python
		for video in u.get("videos") or []:
			lines.append("    <video:video>")
			lines.append(f"      <video:thumbnail_loc>{escape(video['thumbnail_loc'])}</video:thumbnail_loc>")
			lines.append(f"      <video:title>{escape(video['title'])}</video:title>")
			lines.append(f"      <video:description>{escape(video.get('description') or video['title'])}</video:description>")
			if video.get("content_loc"):
				lines.append(f"      <video:content_loc>{escape(video['content_loc'])}</video:content_loc>")
			if video.get("player_loc"):
				lines.append(f"      <video:player_loc>{escape(video['player_loc'])}</video:player_loc>")
			if video.get("duration"):
				lines.append(f"      <video:duration>{int(video['duration'])}</video:duration>")
			if video.get("publication_date"):
				lines.append(f"      <video:publication_date>{escape(video['publication_date'])}</video:publication_date>")
			if video.get("expiration_date"):
				lines.append(f"      <video:expiration_date>{escape(video['expiration_date'])}</video:expiration_date>")
			lines.append("    </video:video>")
```

`_video_entries_for_listing(row, site)` — `_image_entries_for_listing`'in (satır 274) birebir kardeşi: ilanın video dosyalarını bul (Listing Image + `video_url`), `fields_for_many` ile alanları çek, `seo_index.decide` indexable olmayanı ele, poster'ı olmayanı ele, sözlükleri üret. `_entry_for_row` çağrı zincirinde `_image_entries_for_listing`'in bağlandığı yere aynı şekilde bağla (`grep -n "_image_entries_for_listing" tradehub_core/seo/sitemap_generator.py`).

- [ ] **Step 4: PASS doğrula + mevcut sitemap regresyonu** — `run-tests --module tradehub_core.tests.test_media_video_seo` ve sitemap test modülü (`ls tradehub_core/tests | grep sitemap`) → PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(seo): video sitemap — xmlns:video + ilan video girdileri"`

---

### Task 6: Listing API — `videoPoster` fallback + `imageMeta` video anahtarları + JSON-LD

**Files:**
- Modify: `tradehub_core/api/listing.py` (`_gorsel_kunyeleri` ~1046, `get_listing_detail` sonuç sözlüğü ~1487, JSON-LD üretim noktası)
- Test: `tradehub_core/tests/test_media_video_seo.py` (ekleme)

**Interfaces:**
- Consumes: `fields_for_many` (poster_url/duration/captions_url dahil), `build_video_object` (Task 4), mevcut `_video_manifest_blogu` (~997).
- Produces: `imageMeta` satırlarında video dosyaları için `poster`, `durationSec`, `captionsUrl` anahtarları; sonuçta `videoPoster` (manifest || `th_media_poster_url`), `videoDurationSec`, `videoCaptionsUrl`; JSON-LD `Product` yanında video varsa `VideoObject`.

- [ ] **Step 1: Failing test** — mevcut listing test desenine bak (`ls tradehub_core/tests | grep listing`; fixture ilan kurulumunu oradan kopyala). Test: video dosyalı ilanda `imageMeta[i]["poster"]` dolu; `videoPoster` manifest boşken `th_media_poster_url`'den gelir.

```python
class TestListingVideoMeta(FrappeTestCase):
	def test_gorsel_kunyesi_video_anahtarlari(self):
		from tradehub_core.api.listing import _gorsel_kunyeleri

		# Kurulum: mevcut test_listing* modüllerindeki fixture desenini kullan —
		# bir Listing + galeriye .webm dosyası ekle; File kaydına
		# th_media_poster_url="/files/p.jpg", th_media_duration=30 yaz.
		# (Fixture yardımcı fonksiyonunu o modülden import et ya da kopyala.)
		...  # kurulumdan sonra:
		kunyeler = _gorsel_kunyeleri(listing, ["/files/test-video.webm"], "tr")
		self.assertEqual(kunyeler[0]["poster"], "/files/p.jpg")
		self.assertEqual(kunyeler[0]["durationSec"], 30)
```

(`...` yerine seçilen fixture kurulum kodu yazılacak — mevcut listing testinden birebir; bu adımda test dosyasına gerçek kurulum girer, plan yürütücüsü `grep -rn "class TestListing" tradehub_core/tests/` ile en yakın örneği bulur.)

- [ ] **Step 2: FAIL doğrula.**

- [ ] **Step 3: Uygula**

`_gorsel_kunyeleri` içinde satır üretilirken (fonksiyonu oku; `fields_for_many` zaten çağrılıyor) video uzantısı tespiti ekle:

```python
from tradehub_core.media.video_poster import VIDEO_UZANTILAR

def _video_mu(url: str) -> bool:
	return url.lower().split("?")[0].endswith(VIDEO_UZANTILAR)
```

ve satır sözlüğüne koşullu anahtarlar:

```python
		if _video_mu(url):
			satir["poster"] = alanlar.get("poster_url") or ""
			satir["durationSec"] = alanlar.get("duration") or 0
			satir["captionsUrl"] = alanlar.get("captions_url") or ""
```

`get_listing_detail` sonuç sözlüğünde `videoUrl` civarına (~1556):

```python
		# Poster fallback (Dilim 4): manifest (bayraklı motor) > canlı yol
		# üretimi. Bayrak kapalıyken de vitrin kapak görür.
		"videoPoster": _video_blogu.get("poster")
		or (_video_seo_alanlari.get("poster_url") if _video_yerel else ""),
		"videoDurationSec": _video_seo_alanlari.get("duration") or 0,
		"videoCaptionsUrl": _video_seo_alanlari.get("captions_url") or "",
```

`_video_seo_alanlari` hazırlığı (sonuç sözlüğünden önce):

```python
	_video_yerel = bool(listing.video_url and str(listing.video_url).startswith("/files/"))
	_video_seo_alanlari = (
		seo.fields_for(listing.video_url, ref_doctype="Listing", ref_name=listing.name, ref_field="video_url", lang=lang)
		if _video_yerel
		else {}
	)
```

(`from tradehub_core.media import seo` importu dosyada zaten var mı `grep` ile bak; yoksa ekle.)

JSON-LD: `grep -n "build_product_schema\|media_images" tradehub_core/api/listing.py` ile üretim noktasını bul; `build_video_object` çağrısı ekle — galerideki her yerel video + promo:

```python
	video_nesneleri = []
	for url in [u for u in images if _video_mu(u)] + ([listing.video_url] if _video_yerel else []):
		alanlar = seo.fields_for(url, ref_doctype="Listing", ref_name=listing.name, ref_field="image", lang=lang)
		nesne = build_video_object(alanlar, site_url, content_url=url, upload_date=str(listing.creation))
		if nesne:
			video_nesneleri.append(nesne)
	if listing.video_url and not _video_yerel:  # YouTube/Vimeo embed
		nesne = build_video_object(
			{**_video_seo_alanlari, "title": _video_seo_alanlari.get("title") or _title},
			site_url, embed_url=listing.video_url, upload_date=str(listing.creation),
		)
		if nesne:
			video_nesneleri.append(nesne)
```

ve `build_product_schema` çağrısına `media_videos=video_nesneleri` parametresi ekle (schema_builder'da: `if media_videos: schema["video"] = media_videos`).

- [ ] **Step 4: PASS + listing regresyonu** — video test modülü + mevcut listing test modülleri → PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(listing): videoPoster fallback, imageMeta video anahtarları, JSON-LD VideoObject"`

---

### Task 7: Admin API uçları + denetim kuralları

**Files:**
- Modify: `tradehub_core/api/media_admin.py` (SEO bölümünün sonu, ~1360)
- Modify: `tradehub_core/media/seo_audit.py` (`audit_fields`, `SKOR_KIRILIMI` haritası ~200)
- Test: `tradehub_core/tests/test_media_video_seo.py` (ekleme)

**Interfaces:**
- Consumes: `video_poster.generate` (Task 2), `seo.set_asset_fields` (transcript/captions_url Task 1'de yazılabilir).
- Produces: `regenerate_video_poster(file_url: str) -> dict` (whitelist, System Manager; mevcut posteri temizler + `media-maint`'e iş atar), `upload_video_captions(file_url: str, vtt_content: str) -> dict` (WEBVTT doğrulamalı, ≤ 1 MB, File yaratır, `captions_url` yazar). Denetim kodları: `missing_poster` (performance), `missing_transcript` (accessibility), `missing_duration` (structured_data) — yalnız video dosyalarında, hepsi WARN.

- [ ] **Step 1: Failing testler**

```python
class TestVideoAuditVeUclar(FrappeTestCase):
	def test_video_denetim_kurallari(self):
		from tradehub_core.media.seo_audit import audit_fields

		bulgular = audit_fields(
			{"alt": "x", "title": "x", "poster_url": "", "transcript": "", "duration": 0},
			file_name="tanitim.webm",
		)
		kodlar = {b["code"] for b in bulgular}
		self.assertIn("missing_poster", kodlar)
		self.assertIn("missing_transcript", kodlar)
		self.assertIn("missing_duration", kodlar)

	def test_gorselde_video_kurali_calismaz(self):
		from tradehub_core.media.seo_audit import audit_fields

		bulgular = audit_fields({"alt": "x"}, file_name="foto.jpg")
		kodlar = {b["code"] for b in bulgular}
		self.assertNotIn("missing_poster", kodlar)

	def test_vtt_yukleme_dogrulama(self):
		from tradehub_core.api.media_admin import upload_video_captions

		frappe.set_user("Administrator")
		doc = frappe.get_doc(
			{"doctype": "File", "file_name": "v.webm", "file_url": "/files/v-cap.webm", "is_private": 0}
		).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			upload_video_captions("/files/v-cap.webm", "bu vtt degil")
		sonuc = upload_video_captions("/files/v-cap.webm", "WEBVTT\n\n00:00.000 --> 00:02.000\nMerhaba")
		self.assertTrue(sonuc["captions_url"].endswith(".vtt"))
```

- [ ] **Step 2: FAIL doğrula.**

- [ ] **Step 3: Denetim kuralları** — `seo_audit.py`:

```python
from tradehub_core.media.video_poster import VIDEO_UZANTILAR


def _video_mu(file_name: str) -> bool:
	return file_name.lower().endswith(VIDEO_UZANTILAR)
```

`audit_fields` sonuna (mevcut kural bloklarının deseniyle):

```python
	if _video_mu(file_name):
		if not (alanlar.get("poster_url") or "").strip():
			bulgular.append(_kural("missing_poster", SEVERITY_WARN, "Video posteri yok"))
		if not (alanlar.get("transcript") or "").strip():
			bulgular.append(_kural("missing_transcript", SEVERITY_WARN, "Transcript yok"))
		if not alanlar.get("duration"):
			bulgular.append(_kural("missing_duration", SEVERITY_WARN, "Video süresi bilinmiyor"))
```

`SKOR_KIRILIMI` haritasına (satır ~200):

```python
	"missing_poster": "performance",
	"missing_transcript": "accessibility",
	"missing_duration": "structured_data",
```

- [ ] **Step 4: API uçları** — `media_admin.py` SEO bölümünün sonuna (mevcut `_only_for`/`_guard` yetki desenini aynen kullan — `grep -n "_only_for\|_guard(" tradehub_core/api/media_admin.py | head`):

```python
@frappe.whitelist()
def regenerate_video_poster(file_url: str) -> dict:
	"""Posteri sil ve yeniden üretim işini kuyruğa at (System Manager)."""
	_only_for()  # dosyadaki mevcut yetki yardımcısının birebir çağrısı
	from tradehub_core.media import video_poster

	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		frappe.throw(frappe._("Dosya bulunamadı."))
	frappe.db.set_value("File", name, "th_media_poster_url", "", update_modified=False)
	frappe.enqueue(
		"tradehub_core.media.video_poster.generate",
		queue="media-maint", timeout=300, file_url=file_url, enqueue_after_commit=True,
	)
	return {"queued": True}


@frappe.whitelist()
def upload_video_captions(file_url: str, vtt_content: str) -> dict:
	"""WebVTT altyazı içeriğini File olarak kaydet ve videoya bağla."""
	_only_for()
	from tradehub_core.media import seo

	icerik = (vtt_content or "").strip()
	if not icerik.startswith("WEBVTT"):
		frappe.throw(frappe._("Geçersiz WebVTT: dosya WEBVTT ile başlamalı."))
	if len(icerik.encode()) > 1024 * 1024:
		frappe.throw(frappe._("Altyazı 1 MB sınırını aşıyor."))
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		frappe.throw(frappe._("Dosya bulunamadı."))
	vtt = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"captions-{name}.vtt",
			"is_private": 0,
			"content": icerik.encode(),
		}
	).insert(ignore_permissions=True)  # sistem yazımı; yetki üstte _only_for
	seo.set_asset_fields(file_url, {"captions_url": vtt.file_url})
	return {"captions_url": vtt.file_url}
```

(İnsert `reject_unsafe_files` hook'una takılırsa — test söyler — o yardımcıya `.vtt` uzantısını ekle; ayrı commit satırı olarak işaretle.)

- [ ] **Step 5: PASS + audit regresyonu** — video modülü + mevcut `test_media_seo_pipeline` → PASS.

- [ ] **Step 6: Commit** — `git commit -m "feat(media): video denetim kuralları + poster yeniden üretme ve VTT yükleme uçları"`

---

### Task 8: Panel (MediaSeoDrawer) + vitrin (poster/track) + i18n

**Files:**
- Modify: `admin-panel/frontend/src/components/media/MediaSeoDrawer.vue`
- Modify: `admin-panel/frontend/src/composables/useMediaSeo.js`
- Modify: `admin-panel/frontend/src/i18n/tr.json` + `en.json` (mediaSeo.* anahtarları — dosya adlarını `grep -rn "mediaSeo.field.alt" admin-panel/frontend/src/i18n/` ile doğrula)
- Modify: `tradehubfront/src/services/listingService.ts` (~1352 `imageMeta` eşlemesi, ~1380 promo)
- Modify: `tradehubfront/src/types/product.ts` (`ProductImage`)
- Modify: `tradehubfront/src/components/product/ProductImageGallery.ts` (video slayt markup'ı — `grep -n "<video" ...` ile yer)
- Test: `admin-panel/frontend/src/composables/__tests__/mediaSeoVideo.test.js` (yeni), `tradehubfront/src/services/listingService.test.ts` (varsa ekleme; yoksa `mapListingDetail` için yeni test)

**Interfaces:**
- Consumes: `get_media_seo` (Task 1 ile yeni alanları otomatik döndürür), `set_media_seo` (transcript), `upload_video_captions`, `regenerate_video_poster` (Task 7); Listing API `imageMeta.poster/durationSec/captionsUrl` + `videoPoster/videoCaptionsUrl` (Task 6).
- Produces: panelde video dosyaları için transcript/altyazı/poster yönetimi; vitrinde `<video poster>` + `<track kind="captions">`.

- [ ] **Step 1: Panel failing test** (`node:test` deseni — mevcut `composables/__tests__/` örneğinden şablon al):

```js
// admin-panel/frontend/src/composables/__tests__/mediaSeoVideo.test.js
import test from "node:test";
import assert from "node:assert/strict";
import { isVideoFile } from "../useMediaSeo.js";

test("isVideoFile uzantıdan video tanır", () => {
	assert.equal(isVideoFile("/files/a.webm"), true);
	assert.equal(isVideoFile("/files/a.mp4?x=1"), true);
	assert.equal(isVideoFile("/files/a.jpg"), false);
});
```

- [ ] **Step 2: FAIL doğrula** — `cd admin-panel/frontend && npm test`.

- [ ] **Step 3: Composable + drawer**

`useMediaSeo.js`'e ekle:

```js
const VIDEO_EXTS = [".mp4", ".webm", ".mov", ".m4v", ".mkv"];
export function isVideoFile(url) {
	const temiz = String(url || "").split("?")[0].toLowerCase();
	return VIDEO_EXTS.some((u) => temiz.endsWith(u));
}
```

ve mevcut save/load akışına `transcript` alanını kat (kayıt `set_media_seo`
üzerinden — alan adı `transcript`); iki yeni eylem:

```js
async function regeneratePoster(row) {
	await api.callMethod(`${M}.regenerate_video_poster`, { file_url: row.file_url });
}
async function uploadCaptions(row, vttText) {
	const r = await api.callMethod(`${M}.upload_video_captions`, {
		file_url: row.file_url, vtt_content: vttText,
	});
	return r?.captions_url || "";
}
```

`MediaSeoDrawer.vue`: `isVideoFile(row.file_url)` doğruysa görünen bölüm —
poster önizleme (`<img :src="fields.poster_url">` boşsa "poster yok" notu +
"Yeniden üret" butonu → `regeneratePoster`), transcript `<textarea>` (mevcut
alan bileşenlerinin sınıf/etiket deseniyle), `.vtt` dosya seçici
(`FileReader.readAsText` → `uploadCaptions`). i18n anahtarları (tr+en):
`mediaSeo.field.transcript`, `mediaSeo.field.captions`, `mediaSeo.video.poster`,
`mediaSeo.video.regenerate`, `mediaSeo.video.noPoster`.

- [ ] **Step 4: Panel testleri + lint** — `npm test && npm run lint` → PASS.

- [ ] **Step 5: Vitrin failing test**

```ts
// mapListingDetail: video slayta poster/captions taşınır
const detail = mapListingDetail({
	title: "X",
	images: ["/files/v.webm"],
	imageMeta: [{ alt: "video", poster: "/files/p.jpg", durationSec: 30, captionsUrl: "/files/c.vtt" }],
});
expect(detail.images[0].poster).toBe("/files/p.jpg");
expect(detail.images[0].captionsUrl).toBe("/files/c.vtt");
```

- [ ] **Step 6: Vitrini uygula**

`types/product.ts` `ProductImage`'e: `poster?: string; captionsUrl?: string; durationSec?: number;`
`listingService.ts` galeri eşlemesine (~1362 bloğu):

```ts
			poster: m.poster || undefined,
			captionsUrl: m.captionsUrl || undefined,
			durationSec: m.durationSec || undefined,
```

(promo slayt zaten `raw.videoPoster` okuyor — Task 6 fallback'i sayesinde bayrak kapalıyken de dolacak; ek koda gerek yok. `captionsUrl` promo için `raw.videoCaptionsUrl`'dan eklenir.)

`ProductImageGallery.ts` video slayt şablonunda `<video ...>` etiketine
`poster` niteliği ve içine track ekle (mevcut şablon değişkenleriyle):

```html
<video ... :poster="img.poster || null">
	<track v-if="img.captionsUrl" kind="captions" :src="img.captionsUrl" default />
</video>
```

(Şablon Alpine string template ise aynı anlamda `${img.poster ? `poster="${img.poster}"` : ""}` deseni — dosyadaki mevcut interpolasyon stilini birebir izle.)

- [ ] **Step 7: Vitrin testleri** — `cd tradehubfront && npm test` → PASS. `npm run build` (HMR yok — dist imajda; canlı doğrulama imaj rebuild ister, bu ayrı adım).

- [ ] **Step 8: Commit'ler** (iki repo ayrı):

```bash
cd admin-panel && git checkout -b feature/media-video-seo && git add -A && git commit -m "feat(media): SEO çekmecesine video bölümü — transcript, VTT, poster yönetimi"
cd ../tradehubfront && git checkout -b feature/media-video-seo && git add -A && git commit -m "feat(product): video slaytlarına poster ve altyazı track'i"
```

---

### Task 9: Uçtan uca ölçüm + kapanış

**Files:**
- Create: `docs/reports/<sıradaki-no>-video-seo-olcum.md` (`ls docs/reports | tail -1` ile numara)
- Modify: `CHANGELOG.md` ([Unreleased])

**Interfaces:**
- Consumes: tüm önceki görevler.

- [ ] **Step 1: Tam paket regresyon** — `run-tests --module` ile: `test_media_video_seo`, `test_video_poster`, `test_media_seo`, `test_media_seo_pipeline` → hepsi PASS.

- [ ] **Step 2: Geri doldurmayı lokalde koştur ve ölç**

```bash
docker exec istoc-dev-backend-1 bench --site istoc.localhost execute tradehub_core.media.video_poster.backfill_pending --kwargs "{'limit': 200}"
docker exec istoc-dev-backend-1 bench --site istoc.localhost execute frappe.db.sql --args "[\"SELECT COUNT(*) FROM tabFile WHERE th_media_poster_url != ''\"]"
```

Önce/sonra sayıları (poster'lı video, VideoObject üretilebilen ilan, sitemap video girdisi) rapora yaz — TUR-135 §9.1 tablo deseni.

- [ ] **Step 3: CHANGELOG** — `[Unreleased]` altına `feat` satırı: "Medya video SEO: poster üretimi, VideoObject, video sitemap, transcript/altyazı alanları (Dilim 4)".

- [ ] **Step 4: Commit + Plane güncelle** — `git commit -m "docs: video SEO ölçüm raporu + changelog"`; MOGEM-620'ye ilerleme yorumu (düz metin, emoji yok — Plane yorum kuralı).

---

## Self-Review Notları

- **Spec kapsaması:** §3→Task 1, §4→Task 2-3, §5→Task 4-5, §6→Task 6, §7→Task 8, §8→Task 7, §9→her taskın test adımları + Task 9 ölçüm. Kapsam dışı liste korunuyor.
- **Spec'ten bilinçli sapmalar (Global Constraints'te ilan edildi):** postersiz videoya VideoObject üretilmez; videoMeta ayrı liste yerine imageMeta genişlemesi + videoPoster fallback.
- **Tip tutarlılığı:** `VIDEO_UZANTILAR` tek yerde (`video_poster.py`) tanımlanır; `seo_audit` (Task 7) ve `listing` (Task 6) oradan import eder. `fields_for` anahtarları: `duration`, `poster_url`, `transcript`, `captions_url` — tüm görevlerde bu adlar.
