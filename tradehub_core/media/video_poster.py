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
				"ffprobe",
				"-v",
				"error",
				"-show_entries",
				"format=duration",
				"-of",
				"default=noprint_wrappers=1:nokey=1",
				path,
			],
			capture_output=True,
			text=True,
			timeout=30,
			check=True,
		)
		return float(out.stdout.strip() or 0)
	except Exception:
		frappe.log_error(title="video_poster.probe_duration", message=frappe.get_traceback())
		return 0.0


# Uzun kenar (yönelime duyarlı) bütçesi: yatay/kare kaynakta genişlik, dikey
# kaynakta yükseklik dalına girer — `iw`/`ih` ffmpeg tarafından KAYNAK karenin
# gerçek boyutlarıyla değerlendirilir (Python tarafında ayrıca probe gerekmez).
# Emsal: media/pipeline/video/poster.py:460-481 `preview_scale_filter` (kısa
# kenar bütçesi) — aynı yönelim sorununu aynı if(gte(iw,ih),...) desenle çözer.
_OLCEK_FILTRESI = (
	f"scale=w='if(gte(iw,ih),min({UZUN_KENAR},iw),-2)':h='if(gte(iw,ih),-2,min({UZUN_KENAR},ih))'"
)


def _kare(path: str, baslangic: float, pencere: float) -> bytes | None:
	"""Penceredeki en temsili kareyi JPEG olarak döndür."""
	with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
		hedef = tmp.name
	try:
		subprocess.run(
			[
				"ffmpeg",
				"-y",
				"-ss",
				f"{baslangic:.2f}",
				"-t",
				f"{max(pencere, 0.5):.2f}",
				"-i",
				path,
				"-vf",
				f"thumbnail=n=120,{_OLCEK_FILTRESI}",
				"-frames:v",
				"1",
				"-q:v",
				"3",
				hedef,
			],
			capture_output=True,
			timeout=FFMPEG_TIMEOUT,
			check=True,
		)
		data = Path(hedef).read_bytes()
		return data or None
	except Exception:
		frappe.log_error(title="video_poster._kare", message=frappe.get_traceback())
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
			"File",
			name,
			{"th_media_poster_url": poster.file_url, "th_media_duration": sure},
			update_modified=False,
		)
		return poster.file_url
	except Exception:
		frappe.log_error(title="video_poster.generate", message=frappe.get_traceback())
		return None
