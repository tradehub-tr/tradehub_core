"""Video async transcode (VP9/Opus, WebM) — RQ `long` kuyruğu (TUR-296/297).

Görsel yolunun aksine (`engine.to_webp` — istek içinde senkron), video
transcode dakikalar sürebilir. `upload_media` içinde senkron çalıştırmak
istek thread'ini/HTTP timeout'unu patlatır (checklists.md §2, kural 9) —
bu yüzden `frappe.enqueue(..., queue="long")`.

Akış:
  1. `enqueue_transcode(file_url)` — istek thread'inde çalışır. Durumu HEMEN
     `processing` yapar (kullanıcı ekranda "işleniyor" görsün) ve gerçek işi
     `_run_transcode`'a devreder.
  2. `_run_transcode(file_url)` — worker'da çalışır. ffmpeg ile videoyu VP9/
     Opus WebM'e normalize eder, diskteki dosyanın YERİNE yazar (`file_url`
     sabit kalır — `Listing` gibi referanslar kırılmaz), durumu `ready`
     yapar. Hata olursa `failed` + `frappe.log_error`.

`ffmpeg` yoksa (dev backend imajında yok, bkz. WP2 raporu) `_run_transcode`
`FileNotFoundError` alır, bunu da `failed` dalı yakalar — worker çökmez.
"""

from __future__ import annotations

import os
import subprocess

import frappe

from tradehub_core.media import audit

VIDEO_STATUS_PROCESSING: str = "processing"
VIDEO_STATUS_READY: str = "ready"
VIDEO_STATUS_FAILED: str = "failed"

# ffmpeg zaman aşımı — kuyruk timeout'undan (1800 sn) biraz kısa tutuluyor ki
# ffmpeg kendi içinde durup "failed" yazsın, RQ'nun sert kill'i devreye girmesin.
_FFMPEG_TIMEOUT_SECONDS: int = 1700


def enqueue_transcode(file_url: str) -> None:
	"""Video yüklemesi sonrası transcode'u kuyruğa al.

	`th_media_video_status`'u hemen `processing` yapar — panel bu alanı
	okuyup "işleniyor" rozetini gösterebilsin. `enqueue_after_commit=True`:
	`upload_media` içinde `File.insert()` henüz commit edilmemişken worker
	tetiklenirse dosyayı bulamaz (race).
	"""
	frappe.db.set_value(
		"File", {"file_url": file_url}, "th_media_video_status", VIDEO_STATUS_PROCESSING
	)
	frappe.enqueue(
		"tradehub_core.media.transcode._run_transcode",
		queue="long",
		timeout=1800,
		file_url=file_url,
		enqueue_after_commit=True,
	)


def _run_transcode(file_url: str) -> None:
	"""Worker'da çalışır — ffmpeg ile videoyu normalize eder.

	Başarısızlıkta asla yarım dosya diske YAZILMAZ: ffmpeg çıktısı geçici bir
	dosyaya yazılır, yalnız süreç başarıyla bitince kaynağın YERİNE
	`os.replace` ile taşınır (atomik) — yarıda kesilen bir transcode orijinal
	videoyu bozmaz.
	"""
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		# Kuyruğa alındıktan sonra dosya bırakılmış/silinmiş olabilir — worker
		# bunun için patlamamalı.
		return

	doc = frappe.get_doc("File", name)
	src_path = doc.get_full_path()
	dst_path = f"{src_path}.transcoding.webm"

	# `nice -n 10`: transcode CPU-yoğun; worker'ın diğer kuyruklarını
	# (default/short — sipariş, ödeme gibi kullanıcı-görünür işler) aç
	# bırakmak için düşük öncelikte çalıştırılır.
	cmd = [
		"nice", "-n", "10",
		"ffmpeg", "-y",
		"-i", src_path,
		"-vf", "scale=min(1280,iw):-2",
		"-c:v", "libvpx-vp9",
		"-b:v", "0",
		"-crf", "32",
		"-c:a", "libopus",
		dst_path,
	]

	try:
		subprocess.run(cmd, check=True, capture_output=True, timeout=_FFMPEG_TIMEOUT_SECONDS)
		os.replace(dst_path, src_path)
		frappe.db.set_value("File", name, "th_media_video_status", VIDEO_STATUS_READY, update_modified=False)
		frappe.db.commit()
		audit.log_media_event(
			action=audit.ACTION_OPTIMIZE, file_url=file_url, context={"kind": "video_transcode"}
		)
	except Exception as exc:  # noqa: BLE001 — worker hiçbir koşulda kuyruğu patlatmamalı
		try:
			if os.path.exists(dst_path):
				os.remove(dst_path)
		except OSError:
			pass
		frappe.db.set_value("File", name, "th_media_video_status", VIDEO_STATUS_FAILED, update_modified=False)
		frappe.db.commit()
		frappe.log_error(title="Video transcode başarısız", message=f"{file_url}: {exc}")
		# Fix round 1, Bulgu 2: yalnız Error Log yeterli değil — transcode
		# başarısızlığı medya denetim ekranında (ADL) da görünmeli, başarı
		# dalıyla (yukarıda) AYNI desen.
		audit.log_media_event(
			action=audit.ACTION_OPTIMIZE,
			file_url=file_url,
			allowed=False,
			reason=f"video_transcode_failed:{type(exc).__name__}",
			context={"kind": "video_transcode"},
		)
