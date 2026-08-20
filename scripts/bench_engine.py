#!/usr/bin/env python3
"""T-007 — Görsel işleme kütüphanesi benchmark'ı: Pillow vs pyvips vs ffmpeg.

Kapanış raporu K-11'in istediği ölçüm. Tek bir normalize edilmiş işlem zinciri
her motorda aynı semantikle koşturulur:

    oku → sRGB'ye çevir → EXIF yönünü uygula → uzun kenarı `--long-edge`'e
    küçült (yalnız downscale) → JPEG q85 / WebP q80 olarak kodla

ÖLÇÜLEN
  * `inner_s`      — yalnız işlem zinciri (import maliyeti hariç), perf_counter
  * `outer_s`      — fork + import + işlem (ebeveynden görülen duvar saati)
  * `peak_rss_kb`  — çocuğun tepe RSS'i, `os.wait4` → `ru_maxrss` (Linux: KB)
  * `rss_over_import_kb` — tepe RSS eksi o motorun "yalnız import" taban çizgisi
  * `out_bytes`    — üretilen baytlar

NEDEN FORK
  `resource.getrusage(RUSAGE_SELF).ru_maxrss` süreç ömrü boyunca yüksek-su-işareti
  tutar; hiç düşmez. Aynı süreçte arka arkaya ölçüm yapılırsa ilk büyük dosya
  sonraki tüm ölçümleri kirletir. Bu yüzden HER koşum ayrı bir fork'ta çalışır ve
  tepe bellek `os.wait4` ile o çocuğa özel okunur.

KULLANIM
    python3 bench_engine.py --out /tmp/bench.csv
    python3 bench_engine.py --engines pillow,pyvips --repeats 5 --long-edge 2400

    # konteynerde:
    docker cp scripts/bench_engine.py istoc-dev-backend-1:/home/frappe/bench/
    docker exec -w /home/frappe/bench istoc-dev-backend-1 \
        ../frappe-bench/env/bin/python bench_engine.py --out /home/frappe/bench/bench.csv

ÖNKOŞUL
    pyvips + libvips konteynerde KALICI DEĞİL (bkz. docs/reports/05-kutuphane-benchmark.md §1).
    Kurulum:
      apt-get install -y libvips-dev && pip install pyvips
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

# ---------------------------------------------------------------------------
# Test korpusu — canlı `istoc.localhost` verisinden seçilmiş 10 gerçek dosya.
# Yollar site köküne görelidir; --files-root ile taşınabilir.
# Seçim ölçütü: format / renk modu / megapiksel / bayt ekseninde uçları ve
# medyanı birlikte kapsamak (bkz. rapor §2).
# ---------------------------------------------------------------------------
CORPUS: list[tuple[str, str]] = [
	("public/files/00d54ac2006fcef07a9eebf4914b2878.jpg", "JPEG RGB 72,7 MP — korpusun en büyük megapikseli"),
	("public/files/305 SİYAH.jpg", "JPEG CMYK 36,2 MP — CMYK + yüksek MP"),
	("public/files/Toplu resim-Kapaklı-Desenli-3.png", "PNG RGBA 36,3 MP + ICC — alfa, ICC, yüksek MP"),
	("private/files/av-120.tif", "TIFF RGB 18,3 MP / 22,1 MB — korpusun en büyük baytı"),
	("public/files/323-9.png", "PNG RGBA 17,3 MP — tipik alfalı PNG"),
	("public/files/323-9 (1).webp", "WEBP RGBA 17,3 MP — aynı görselin WebP'si"),
	("public/files/20250407160713_d33fff.webp", "WEBP RGB 6,3 MP — tipik WebP"),
	("public/files/AV157G.jpg", "JPEG CMYK 2,1 MP — tipik CMYK ürün görseli"),
	("public/files/110401-1.jpg", "JPEG RGB 1,7 MP — medyan civarı ürün görseli"),
	("public/files/0158.jpg", "JPEG RGB 1,44 MP / 82 KB — p50 bayt/MP örneği"),
]

DEFAULT_ROOT = "/home/frappe/frappe-bench/sites/istoc.localhost"
ALL_ENGINES = ("pillow", "pillow_draft", "pyvips", "pyvips_c1", "pyvips_tuned", "ffmpeg")


# ===========================================================================
# Ortak yardımcılar
# ===========================================================================
def _probe(path: str) -> dict:
	"""Kaynağın künyesi. Ölçümün dışında, tek sefer çağrılır."""
	from PIL import Image

	Image.MAX_IMAGE_PIXELS = None
	out = {"src_fmt": "", "src_mode": "", "src_w": 0, "src_h": 0, "src_mp": 0.0,
	       "src_bytes": 0, "src_icc": 0, "src_exif_orient": 0}
	try:
		out["src_bytes"] = os.path.getsize(path)
	except OSError:
		return out
	try:
		with Image.open(path) as im:
			out["src_fmt"] = im.format or ""
			out["src_mode"] = im.mode
			out["src_w"], out["src_h"] = im.size
			out["src_mp"] = round(im.width * im.height / 1e6, 3)
			out["src_icc"] = 1 if im.info.get("icc_profile") else 0
			try:
				out["src_exif_orient"] = int(im.getexif().get(274) or 0)
			except Exception:
				pass
	except Exception:
		pass
	return out


# ===========================================================================
# Motor zincirleri — hepsi aynı sözleşmeyi uygular, `inner_s` içeride ölçülür
# ===========================================================================
def _chain_pillow(path: str, out_fmt: str, long_edge: int, q: int, draft: bool) -> dict:
	from PIL import Image, ImageCms, ImageOps

	Image.MAX_IMAGE_PIXELS = None
	t0 = time.perf_counter()

	im = Image.open(path)
	src_fmt = (im.format or "").upper()
	icc = im.info.get("icc_profile")

	# draft(): JPEG'de DCT ölçekli çözme — kareyi tam boyutta rastere açmadan
	# 1/2, 1/4, 1/8 çözer. Yalnız JPEG'de etkisi vardır.
	if draft and src_fmt == "JPEG":
		im.draft(None, (long_edge, long_edge))
	im.load()

	# 1) EXIF yönü — pikselleri fiziksel döndürür
	im = ImageOps.exif_transpose(im)

	# 2) sRGB'ye çevir
	if icc:
		try:
			src_p = ImageCms.ImageCmsProfile(io.BytesIO(icc))
			dst_p = ImageCms.createProfile("sRGB")
			mode = "RGBA" if im.mode in ("RGBA", "LA") else "RGB"
			im = ImageCms.profileToProfile(im, src_p, dst_p, outputMode=mode)
		except Exception:
			icc = None
	if not icc:
		if im.mode == "P":
			im = im.convert("RGBA" if "transparency" in im.info else "RGB")
		elif im.mode not in ("RGB", "RGBA"):
			im = im.convert("RGB")

	# 3) uzun kenarı küçült — yalnız downscale
	im.thumbnail((long_edge, long_edge), Image.LANCZOS)

	# 4) kodla
	buf = io.BytesIO()
	if out_fmt == "jpeg":
		im.convert("RGB").save(buf, "JPEG", quality=q, optimize=True, progressive=True)
	else:
		im.save(buf, "WEBP", quality=q, method=4)
	data = buf.getvalue()

	inner = time.perf_counter() - t0
	return {"inner_s": inner, "out_bytes": len(data), "out_w": im.width, "out_h": im.height}


def _chain_pyvips(path: str, out_fmt: str, long_edge: int, q: int) -> dict:
	import pyvips

	t0 = time.perf_counter()

	# thumbnail(): libvips'in "shrink-on-load" yolu. JPEG'de DCT ölçekli,
	# WebP/TIFF/PNG'de akış tabanlı çözer — tam raster hiç kurulmaz.
	# auto_rotate varsayılan True (EXIF yönü), export_profile="srgb" renk çevrimi.
	im = pyvips.Image.thumbnail(
		path, long_edge, height=long_edge, size="down", export_profile="srgb"
	)

	if out_fmt == "jpeg":
		if im.hasalpha():
			im = im.flatten(background=[255, 255, 255])
		data = im.write_to_buffer(f".jpg[Q={q},optimize_coding=true,interlace=true,strip=true]")
	else:
		data = im.write_to_buffer(f".webp[Q={q},strip=true]")

	inner = time.perf_counter() - t0
	return {"inner_s": inner, "out_bytes": len(data), "out_w": im.width, "out_h": im.height}


def _chain_pyvips_tuned(path: str, out_fmt: str, long_edge: int, q: int) -> dict:
	"""pyvips — elle ayarlanmış zincir. `thumbnail()`'in iki tuzağını atlatır.

	TUZAK 1 — CMYK JPEG'de shrink-on-load YOK.
	  `thumbnail()` bir CMYK JPEG'i tam çözünürlükte açıp CMYK uzayında ölçekler.
	  36,2 MP'lik `305 SİYAH.jpg` üzerinde ölçüldü (rapor §5.2):
	      thumbnail() naif ................ 2.865 ms
	      önce sRGB, sonra ölçek .......... 1.931 ms
	      DCT shrink-on-load + sRGB ..........568 ms   ← bu zincir
	  Yani darboğaz renk çevrimi (244 ms) değil, tam çözünürlükte 4 bantlı
	  yeniden örnekleme (2.606 ms).

	TUZAK 2 — `export_profile="srgb"` koşulsuz verilirse ICC'siz sRGB görselleri
	  gereksiz yere dönüştürür ve pikselleri kaydırır (`0158.jpg`: ortalama
	  |fark| 5,45 / maks 25; profil verilmeyince fark 0). Bu yüzden renk çevrimi
	  yalnız gerçekten gerektiğinde yapılır.
	"""
	import pyvips

	t0 = time.perf_counter()

	hdr = pyvips.Image.new_from_file(path)
	src_long = max(hdr.width, hdr.height)
	is_jpeg = (hdr.get("vips-loader") or "").startswith("jpegload")

	if is_jpeg and src_long > long_edge:
		# libjpeg yalnız 1/2, 1/4, 1/8 DCT ölçeği verir; hedefin altına düşme.
		shrink = 1
		for cand in (8, 4, 2):
			if src_long / cand >= long_edge:
				shrink = cand
				break
		im = pyvips.Image.jpegload(path, shrink=shrink, access="sequential")
	else:
		im = pyvips.Image.new_from_file(path, access="sequential")

	im = im.autorot()                                  # EXIF yönü
	if im.interpretation != "srgb":                    # yalnız gerekiyorsa
		im = im.colourspace("srgb")
	if max(im.width, im.height) > long_edge:           # yalnız downscale
		im = im.thumbnail_image(long_edge)

	if out_fmt == "jpeg":
		if im.hasalpha():
			im = im.flatten(background=[255, 255, 255])
		data = im.write_to_buffer(f".jpg[Q={q},optimize_coding=true,interlace=true,strip=true]")
	else:
		data = im.write_to_buffer(f".webp[Q={q},strip=true]")

	inner = time.perf_counter() - t0
	return {"inner_s": inner, "out_bytes": len(data), "out_w": im.width, "out_h": im.height}


def _chain_ffmpeg(path: str, out_fmt: str, long_edge: int, q: int) -> dict:
	"""ffmpeg görsel yolu.

	UYARI — bu zincir diğer ikisiyle SEMANTİK OLARAK EŞDEĞER DEĞİLDİR:
	  * ICC profili okunmaz/uygulanmaz (CMYK swscale ile kabaca çevrilir)
	  * durağan görselde EXIF yönü uygulanmaz
	  * mjpeg `-q:v` ölçeği 2..31'dir, Pillow/libvips'in 0..100 `quality`si DEĞİLDİR
	Sayılar bu kısıtlarla okunmalı (rapor §6).
	"""
	t0 = time.perf_counter()
	suffix = ".jpg" if out_fmt == "jpeg" else ".webp"
	fd, outp = tempfile.mkstemp(suffix=suffix)
	os.close(fd)
	try:
		vf = (f"scale='min({long_edge},iw)':'min({long_edge},ih)'"
		      f":force_original_aspect_ratio=decrease:flags=lanczos")
		cmd = ["/usr/bin/ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", path,
		       "-vf", vf, "-frames:v", "1"]
		if out_fmt == "jpeg":
			cmd += ["-c:v", "mjpeg", "-q:v", "3"]
		else:
			cmd += ["-c:v", "libwebp", "-quality", str(q), "-compression_level", "4"]
		cmd += [outp]
		p = subprocess.run(cmd, capture_output=True)
		if p.returncode != 0:
			raise RuntimeError((p.stderr or b"").decode()[:200] or "ffmpeg failed")
		n = os.path.getsize(outp)
		w = h = 0
		try:
			from PIL import Image

			Image.MAX_IMAGE_PIXELS = None
			with Image.open(outp) as im:
				w, h = im.size
		except Exception:
			pass
		inner = time.perf_counter() - t0
		return {"inner_s": inner, "out_bytes": n, "out_w": w, "out_h": h}
	finally:
		try:
			os.unlink(outp)
		except OSError:
			pass


def _import_only(engine: str) -> dict:
	"""Taban çizgisi: yalnız kütüphaneyi içe aktar, iş yapma."""
	t0 = time.perf_counter()
	if engine.startswith("pillow"):
		import PIL.Image  # noqa: F401
	elif engine.startswith("pyvips"):
		import pyvips  # noqa: F401
	else:
		import PIL.Image  # noqa: F401
	return {"inner_s": time.perf_counter() - t0, "out_bytes": 0, "out_w": 0, "out_h": 0}


def _dispatch(engine: str, path: str, out_fmt: str, long_edge: int, q: int) -> dict:
	if engine == "pillow":
		return _chain_pillow(path, out_fmt, long_edge, q, draft=False)
	if engine == "pillow_draft":
		return _chain_pillow(path, out_fmt, long_edge, q, draft=True)
	if engine in ("pyvips", "pyvips_c1"):
		return _chain_pyvips(path, out_fmt, long_edge, q)
	if engine == "pyvips_tuned":
		return _chain_pyvips_tuned(path, out_fmt, long_edge, q)
	if engine == "ffmpeg":
		return _chain_ffmpeg(path, out_fmt, long_edge, q)
	raise ValueError(f"bilinmeyen motor: {engine}")


# ===========================================================================
# Yalıtılmış koşum — fork + wait4 ile o çocuğa özel tepe RSS
# ===========================================================================
def run_isolated(fn, *args, env: dict | None = None) -> dict:
	r_fd, w_fd = os.pipe()
	t0 = time.perf_counter()
	pid = os.fork()
	if pid == 0:  # ---- çocuk ----
		os.close(r_fd)
		try:
			if env:
				os.environ.update(env)
			try:
				res = fn(*args)
				payload = json.dumps({"ok": 1, **res})
			except BaseException as exc:  # noqa: BLE001
				payload = json.dumps({"ok": 0, "err": f"{type(exc).__name__}: {exc}"[:300]})
			os.write(w_fd, payload.encode())
			os.close(w_fd)
		finally:
			os._exit(0)

	# ---- ebeveyn ----
	os.close(w_fd)
	chunks = []
	while True:
		b = os.read(r_fd, 65536)
		if not b:
			break
		chunks.append(b)
	os.close(r_fd)
	_, _status, ru = os.wait4(pid, 0)
	outer = time.perf_counter() - t0

	try:
		res = json.loads(b"".join(chunks) or b"{}")
	except Exception:
		res = {"ok": 0, "err": "cocuk cikti okunamadi"}
	res["outer_s"] = outer
	res["peak_rss_kb"] = int(ru.ru_maxrss)  # Linux: kilobayt
	return res


# ===========================================================================
# SSIM — numpy ile, gaussian 11x11 σ=1.5 (Wang et al. 2004)
# ===========================================================================
def _gauss_kernel(size: int = 11, sigma: float = 1.5):
	import numpy as np

	ax = np.arange(size, dtype=np.float64) - (size - 1) / 2.0
	k = np.exp(-(ax ** 2) / (2 * sigma ** 2))
	return k / k.sum()


def _sep_conv(img, k):
	"""Ayrılabilir konvolüsyon ('valid'), sliding_window_view ile."""
	import numpy as np
	from numpy.lib.stride_tricks import sliding_window_view

	n = k.size
	tmp = sliding_window_view(img, n, axis=1) @ k          # yatay geçiş
	return np.einsum("ijk,k->ij", sliding_window_view(tmp, n, axis=0), k)  # dikey geçiş


def ssim(a, b) -> float:
	"""Gri tonlamalı iki numpy dizisi arasında ortalama SSIM."""
	import numpy as np

	a = a.astype(np.float64)
	b = b.astype(np.float64)
	k = _gauss_kernel()
	C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
	mu_a, mu_b = _sep_conv(a, k), _sep_conv(b, k)
	mu_a2, mu_b2, mu_ab = mu_a * mu_a, mu_b * mu_b, mu_a * mu_b
	s_a = _sep_conv(a * a, k) - mu_a2
	s_b = _sep_conv(b * b, k) - mu_b2
	s_ab = _sep_conv(a * b, k) - mu_ab
	num = (2 * mu_ab + C1) * (2 * s_ab + C2)
	den = (mu_a2 + mu_b2 + C1) * (s_a + s_b + C2)
	return float(np.mean(num / den))


def _to_gray(data: bytes):
	import numpy as np
	from PIL import Image

	Image.MAX_IMAGE_PIXELS = None
	with Image.open(io.BytesIO(data)) as im:
		return np.asarray(im.convert("L"))


def quality_compare(path: str, long_edge: int, jq: int, wq: int) -> dict:
	"""Pillow ve pyvips çıktılarının SSIM karşılaştırması.

	İki ölçüm verilir:
	  ssim_pil_vs_vips  — iki motorun JPEG çıktısı birbirine ne kadar yakın
	  ssim_*_encode     — motorun KENDİ kodlama kaybı (kayıpsız PNG referansına karşı)
	Böylece "hangisi doğru" tartışması yerine "kim ne kadar kaybediyor" ölçülür.
	"""
	import numpy as np
	from PIL import Image, ImageCms, ImageOps

	Image.MAX_IMAGE_PIXELS = None
	out: dict = {"rel": path}

	# --- Pillow: ölçekli raster (referans) + JPEG ---
	im = Image.open(path)
	icc = im.info.get("icc_profile")
	im.load()
	im = ImageOps.exif_transpose(im)
	if icc:
		try:
			im = ImageCms.profileToProfile(
				im, ImageCms.ImageCmsProfile(io.BytesIO(icc)), ImageCms.createProfile("sRGB"),
				outputMode="RGBA" if im.mode in ("RGBA", "LA") else "RGB")
		except Exception:
			icc = None
	if not icc and im.mode not in ("RGB", "RGBA"):
		im = im.convert("RGB")
	im.thumbnail((long_edge, long_edge), Image.LANCZOS)
	# pyvips kolu alfayı beyaza flatten ediyor; SSIM'in adil olması için Pillow
	# kolu da aynısını yapmalı (yoksa şeffaf pikseller iki motorda farklı okunur).
	if im.mode in ("RGBA", "LA"):
		bg = Image.new("RGB", im.size, (255, 255, 255))
		bg.paste(im, mask=im.getchannel("A"))
		im = bg
	pil_ref = np.asarray(im.convert("L"))
	b = io.BytesIO()
	im.convert("RGB").save(b, "JPEG", quality=jq, optimize=True, progressive=True)
	pil_jpg = _to_gray(b.getvalue())
	out["pil_size"] = f"{im.width}x{im.height}"

	# --- pyvips: ölçekli raster (referans) + JPEG ---
	try:
		import pyvips

		v = pyvips.Image.thumbnail(path, long_edge, height=long_edge, size="down",
		                          export_profile="srgb")
		if v.hasalpha():
			v = v.flatten(background=[255, 255, 255])
		# thumbnail() SIRALI erişimli tembel bir boru hattı döndürür; aynı görüntü
		# iki kez yazılamaz ("out of order read"). Belleğe alarak iki kez okunur yap.
		v = v.copy_memory()
		vips_ref = _to_gray(v.write_to_buffer(".png[compression=1]"))
		vips_jpg = _to_gray(v.write_to_buffer(
			f".jpg[Q={jq},optimize_coding=true,interlace=true,strip=true]"))
		out["vips_size"] = f"{v.width}x{v.height}"
	except Exception as exc:  # noqa: BLE001
		out["err"] = f"pyvips: {type(exc).__name__}: {exc}"[:200]
		return out

	def crop(*arrs):
		h = min(a.shape[0] for a in arrs)
		w = min(a.shape[1] for a in arrs)
		return [a[:h, :w] for a in arrs]

	pr, pj = crop(pil_ref, pil_jpg)
	vr, vj = crop(vips_ref, vips_jpg)
	out["ssim_pillow_encode"] = round(ssim(pr, pj), 5)
	out["ssim_pyvips_encode"] = round(ssim(vr, vj), 5)
	a, bb = crop(pil_jpg, vips_jpg)
	out["ssim_pil_vs_vips"] = round(ssim(a, bb), 5)
	ar, br = crop(pil_ref, vips_ref)
	out["ssim_ref_pil_vs_vips"] = round(ssim(ar, br), 5)
	return out


# ===========================================================================
# Ana akış
# ===========================================================================
def main() -> int:
	ap = argparse.ArgumentParser(description="T-007 kütüphane benchmark'ı")
	ap.add_argument("--files-root", default=DEFAULT_ROOT)
	ap.add_argument("--out", default="bench.csv")
	ap.add_argument("--repeats", type=int, default=3)
	ap.add_argument("--long-edge", type=int, default=2400)
	ap.add_argument("--jpeg-q", type=int, default=85)
	ap.add_argument("--webp-q", type=int, default=80)
	ap.add_argument("--engines", default=",".join(ALL_ENGINES))
	ap.add_argument("--no-ssim", action="store_true")
	args = ap.parse_args()

	engines = [e.strip() for e in args.engines.split(",") if e.strip()]
	for e in engines:
		if e not in ALL_ENGINES:
			print(f"bilinmeyen motor: {e}", file=sys.stderr)
			return 2

	# --- motor kullanılabilirliği ---
	avail: dict[str, str] = {}
	for e in engines:
		if e.startswith("pyvips"):
			try:
				import pyvips

				avail[e] = "pyvips %s / libvips %s" % (
					pyvips.__version__,
					".".join(str(pyvips.base.version(i)) for i in range(3)))
			except Exception as exc:  # noqa: BLE001
				avail[e] = f"YOK — {type(exc).__name__}: {exc}"[:160]
		elif e == "ffmpeg":
			avail[e] = "VAR" if shutil.which("ffmpeg") or os.path.exists("/usr/bin/ffmpeg") else "YOK"
		else:
			import PIL

			avail[e] = f"Pillow {PIL.__version__}"
	print("== Motorlar ==")
	for e, v in avail.items():
		print(f"  {e:<14} {v}")
	engines = [e for e in engines if not avail[e].startswith("YOK")]
	if not engines:
		print("Hiçbir motor kullanılabilir değil.", file=sys.stderr)
		return 1

	# --- korpus ---
	files = []
	for rel, note in CORPUS:
		p = os.path.join(args.files_root, rel)
		if not os.path.exists(p):
			print(f"  ATLANDI (diskte yok): {rel}")
			continue
		files.append((rel, p, note, _probe(p)))
	print(f"\n== Korpus: {len(files)}/{len(CORPUS)} dosya bulundu ==")
	for rel, _p, note, pr in files:
		print(f"  {pr['src_fmt']:<5} {pr['src_mode']:<5} {pr['src_mp']:>7.2f} MP "
		      f"{pr['src_bytes']/1048576:>6.2f} MB  icc={pr['src_icc']} exif={pr['src_exif_orient']}  {rel}")
	if not files:
		return 1

	# --- import taban çizgileri ---
	print("\n== Import taban çizgisi (tepe RSS) ==")
	base: dict[str, int] = {}
	for e in engines:
		env = {"VIPS_CONCURRENCY": "1"} if e == "pyvips_c1" else None
		vals = [run_isolated(_import_only, e, env=env)["peak_rss_kb"] for _ in range(3)]
		base[e] = min(vals)
		print(f"  {e:<14} {base[e]/1024:7.1f} MB")

	# --- ölçüm ---
	rows: list[dict] = []
	total = len(files) * len(engines) * 2 * args.repeats
	done = 0
	print(f"\n== Ölçüm: {total} koşum ==")
	for rel, path, note, pr in files:
		for out_fmt in ("jpeg", "webp"):
			q = args.jpeg_q if out_fmt == "jpeg" else args.webp_q
			for e in engines:
				env = {"VIPS_CONCURRENCY": "1"} if e == "pyvips_c1" else None
				for rep in range(args.repeats):
					res = run_isolated(_dispatch, e, path, out_fmt, args.long_edge, q, env=env)
					done += 1
					rows.append({
						"engine": e, "rel": rel, "note": note, "out_fmt": out_fmt,
						"quality": q, "long_edge": args.long_edge, "repeat": rep,
						"ok": res.get("ok", 0),
						"inner_s": round(res.get("inner_s", 0.0), 5),
						"outer_s": round(res.get("outer_s", 0.0), 5),
						"peak_rss_kb": res.get("peak_rss_kb", 0),
						"rss_over_import_kb": res.get("peak_rss_kb", 0) - base.get(e, 0),
						"out_bytes": res.get("out_bytes", 0),
						"out_w": res.get("out_w", 0), "out_h": res.get("out_h", 0),
						"err": res.get("err", ""),
						**pr,
					})
				last = rows[-1]
				flag = "" if last["ok"] else f"  HATA: {last['err']}"
				print(f"  [{done:>4}/{total}] {e:<14} {out_fmt:<4} "
				      f"{last['inner_s']:7.3f}s {last['peak_rss_kb']/1024:7.1f}MB "
				      f"{last['out_bytes']/1024:8.1f}KB  {rel[:48]}{flag}")

	# --- CSV ---
	cols = ["engine", "rel", "note", "out_fmt", "quality", "long_edge", "repeat", "ok",
	        "inner_s", "outer_s", "peak_rss_kb", "rss_over_import_kb", "out_bytes",
	        "out_w", "out_h", "src_fmt", "src_mode", "src_w", "src_h", "src_mp",
	        "src_bytes", "src_icc", "src_exif_orient", "err"]
	with open(args.out, "w", newline="", encoding="utf-8") as fh:
		w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
		w.writeheader()
		w.writerows(rows)
	print(f"\nHam ölçüm yazıldı: {args.out}  ({len(rows)} satır)")

	# --- özet ---
	print("\n== ÖZET: medyan inner_s / tepe RSS / çıktı baytı ==")
	for out_fmt in ("jpeg", "webp"):
		print(f"\n-- {out_fmt.upper()} --")
		hdr = f"{'dosya':<44}" + "".join(f"{e:>26}" for e in engines)
		print(hdr)
		for rel, _p, _n, _pr in files:
			line = f"{rel.split('/')[-1][:43]:<44}"
			for e in engines:
				sel = [r for r in rows if r["rel"] == rel and r["engine"] == e
				       and r["out_fmt"] == out_fmt and r["ok"]]
				if not sel:
					line += f"{'HATA':>26}"
					continue
				ms = statistics.median(r["inner_s"] for r in sel) * 1000
				mb = max(r["peak_rss_kb"] for r in sel) / 1024
				kb = statistics.median(r["out_bytes"] for r in sel) / 1024
				line += f"{ms:>8.0f}ms{mb:>7.0f}MB{kb:>8.0f}KB"
			print(line)

	print("\n== TOPLAM (korpus geneli, medyanların toplamı) ==")
	for out_fmt in ("jpeg", "webp"):
		for e in engines:
			tot_s = tot_kb = 0.0
			peak = 0
			nok = 0
			for rel, _p, _n, _pr in files:
				sel = [r for r in rows if r["rel"] == rel and r["engine"] == e
				       and r["out_fmt"] == out_fmt and r["ok"]]
				if not sel:
					continue
				nok += 1
				tot_s += statistics.median(r["inner_s"] for r in sel)
				tot_kb += statistics.median(r["out_bytes"] for r in sel) / 1024
				peak = max(peak, max(r["peak_rss_kb"] for r in sel))
			print(f"  {out_fmt:<5} {e:<14} {nok}/{len(files)} ok  "
			      f"toplam {tot_s:7.3f}s  tepe {peak/1024:7.1f}MB  çıktı {tot_kb/1024:7.2f}MB")

	# --- SSIM ---
	if not args.no_ssim:
		print("\n== SSIM (kalite) ==")
		try:
			import numpy  # noqa: F401
		except Exception as exc:  # noqa: BLE001
			print(f"  ÖLÇÜLEMEDİ — numpy yok: {exc}")
		else:
			print(f"  {'dosya':<44}{'pil_enc':>10}{'vips_enc':>10}{'pil~vips':>10}{'ref~ref':>10}")
			for rel, path, _n, _pr in files:
				r = quality_compare(path, args.long_edge, args.jpeg_q, args.webp_q)
				if "err" in r:
					print(f"  {rel.split('/')[-1][:43]:<44} ÖLÇÜLEMEDİ: {r['err']}")
					continue
				print(f"  {rel.split('/')[-1][:43]:<44}"
				      f"{r['ssim_pillow_encode']:>10.4f}{r['ssim_pyvips_encode']:>10.4f}"
				      f"{r['ssim_pil_vs_vips']:>10.4f}{r['ssim_ref_pil_vs_vips']:>10.4f}"
				      f"   {r['pil_size']} / {r['vips_size']}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
