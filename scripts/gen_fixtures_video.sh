#!/bin/sh
# T-006 — video fixture üreteci. Konteynerin ffmpeg'i ile çalışır.
set -e
OUT=/tmp/fixvid
rm -rf "$OUT"; mkdir -p "$OUT"
FF="ffmpeg -hide_banner -loglevel error -y"

# 1) Verimli H.264: canlıdaki p50 bitrate 746 kbps (rapor 08 §7).
$FF -f lavfi -i "testsrc2=size=1280x720:rate=30:duration=10" \
    -f lavfi -i "sine=frequency=440:duration=10" \
    -c:v libx264 -preset medium -b:v 750k -maxrate 750k -bufsize 1500k \
    -pix_fmt yuv420p -c:a aac -b:a 96k -movflags +faststart \
    "$OUT/video_efficient_720p_750k.mp4"

# 2) Şişirilmiş: AYNI kaynak içerik, 8 Mbps. transcode.py'nin 2,5 Mbps
#    eşiğini geçen tek fixture — canlı korpusta böyle bir dosya YOK.
$FF -f lavfi -i "testsrc2=size=1280x720:rate=30:duration=10" \
    -f lavfi -i "sine=frequency=440:duration=10" \
    -c:v libx264 -preset medium -b:v 8000k -maxrate 8000k -bufsize 16000k \
    -pix_fmt yuv420p -c:a aac -b:a 320k -movflags +faststart \
    "$OUT/video_bloated_720p_8m.mp4"

# 3) Sessiz: ses akışı HİÇ yok. Canlıda 19/23 böyle.
$FF -f lavfi -i "testsrc2=size=1280x720:rate=25:duration=8" \
    -an -c:v libx264 -preset medium -b:v 800k -pix_fmt yuv420p \
    -movflags +faststart "$OUT/video_silent_noaudio_720p.mp4"

# 4) 9:16 dikey — canlıda ölçülen 720x1280.
$FF -f lavfi -i "testsrc2=size=720x1280:rate=30:duration=8" \
    -f lavfi -i "sine=frequency=330:duration=8" \
    -c:v libx264 -preset medium -b:v 900k -pix_fmt yuv420p \
    -c:a aac -b:a 96k -movflags +faststart "$OUT/video_vertical_9x16.mp4"

# 5) 540 sn — canlıdaki MAKSİMUM süre (9 dk). Korpusu küçük tutmak için
#    çözünürlük düşürüldü, SÜRE korundu.
$FF -f lavfi -i "testsrc2=size=320x240:rate=10:duration=540" \
    -an -c:v libx264 -preset ultrafast -b:v 60k -maxrate 60k -bufsize 120k \
    -pix_fmt yuv420p -movflags +faststart "$OUT/video_long_540s_320x240.mp4"

# 6) 352x352 — canlıdaki EN DÜŞÜK çözünürlük.
$FF -f lavfi -i "testsrc2=size=352x352:rate=25:duration=6" \
    -an -c:v libx264 -preset medium -b:v 400k -pix_fmt yuv420p \
    -movflags +faststart "$OUT/video_square_352.mp4"

# 7) 16:9 1080p — canlıda ölçülen 1920x1080; product.video master 1280'e
#    indirmeli (auto_fix yolu).
$FF -f lavfi -i "testsrc2=size=1920x1080:rate=25:duration=6" \
    -an -c:v libx264 -preset medium -b:v 1500k -pix_fmt yuv420p \
    -movflags +faststart "$OUT/video_16x9_1080p.mp4"

ls -l "$OUT"
