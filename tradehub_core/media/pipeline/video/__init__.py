"""Video motoru — FAZ 7 (T-070…T-075). GERÇEK KOD.

    probe.py      T-070  ffprobe künyesi: karar için gereken TÜM değişkenler
    decision.py   T-071  karar tablosu (JSON'dan) — PASSTHROUGH/REMUX/TRANSCODE/REJECT
    transcode.py  T-072  H.264 High + AAC 128k + faststart, INV-05 fayda kapısı
    poster.py     T-073  ilk ANLAMLI kare + 3-6 sn sessiz önizleme klibi
    hls.py        T-074  360p→1080p merdiveni, tek ffmpeg koşumu

**SARMALANAN, YENİDEN YAZILMAYAN.** `tradehub_core/media/transcode.py` çalışan
bir hattır ve olduğu yerde kalıyor: `frappe.enqueue(queue="long")`, deneme
sayacı + backoff (`media/jobs.py`), dead-letter, takılı iş süpürücüsü, AV
karantina kesişimi. Bu paket o hattın KUYRUK tarafına hiç dokunmaz; yalnız
KARAR ve DÖNÜŞÜM tarafını yerine koyar. Bu paketteki hiçbir modül `frappe`
import etmez.

Mevcut hattan devralınanlar (yeniden icat edilmedi):
  * zaman aşımı merdiveni  ffprobe 20 < ffmpeg 1700 < kuyruk 1800 < kayıp 2700
  * `nice -n 10` öncelik düşürme
  * geçici dosya + `os.replace` atomikliği
  * `scale='min(1280,iw)':-2` tek tırnak tuzağı
  * eşikler 1280 px / 2,5 Mbps — karar tablosunda AYNI SAYIYLA duruyor

Mevcut hattan AYRILANLAR (her biri gerekçesiyle belgeli):
  1. Çıktı kodeği VP9/Opus/WebM → H.264/AAC/mp4
     (`video_decision.json` targets.h264_primary.why_h264_not_vp9)
  2. Karar iki değerli (`needs_transcode` bool) → dört aksiyonlu tablo;
     REMUX bugün YOK.
  3. Fayda kapısı YOK → INV-05 (%10) uygulanıyor, geçemeyen çıktı ATILIYOR.
  4. Ölçülemeyen künye TRANSCODE → REJECT (`probe_unavailable` kuralı,
     `diverges_from_today` alanında yazılı, tek satırla geri alınabilir).
"""

from __future__ import annotations

IMPLEMENTED = True

__all__ = ["IMPLEMENTED"]
