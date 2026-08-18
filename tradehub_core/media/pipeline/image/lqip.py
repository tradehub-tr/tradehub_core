"""T-065 — LQIP: ThumbHash + baskın renk. Hedef <30 bayt, <30 ms.

Ne işe yarar
------------
Görselin yerine, o görsel inene kadar gösterilecek **çok küçük** bir ön izleme
üretir. Ön izleme HTML'e gömülecek kadar küçük olmalı — bir `<img>` isteği daha
açmak, çözmeye çalıştığı sorunun ta kendisidir.

Neden ThumbHash (BLURHASH DEĞİL)
--------------------------------
İkisi de aynı fikri kullanır (DCT katsayılarını birkaç bayta paketle) ama:

  * ThumbHash **alfa kanalını taşır**. Canlı korpusta 597 alfalı dosya var
    (%12,0); BlurHash bunların hepsini opak gösterir ve kesim logolarda
    beyaz/siyah kutu olarak patlar.
  * ThumbHash **en-boy oranını hash'in içinde taşır**. BlurHash'te oran ayrıca
    saklanmalıdır — yani "20 bayt" aslında 20 bayt + iki tamsayıdır.
  * ThumbHash ham **ikili**dir (21-25 bayt); BlurHash base83 metindir ve aynı
    bilgi için ~30 karakter yer kaplar.

Boyut — ÖLÇÜLDÜ
---------------
Bayt sayısı görselin İÇERİĞİNDEN bağımsızdır; yalnız iki şeye bağlıdır:
alfa var mı, ve en-boy oranı ne. Oran, saklanan parlaklık katsayısı ızgarasını
(lx × ly) belirler: kare görselde ızgara en büyüktür, uzadıkça kısa kenarın
katsayı sayısı düşer ve hash KISALIR.

TAVAN (kare görsel):

    alfasız:  5 başlık + ceil(37/2)=19          = **24 bayt**  (L 7×7 → 27 AC, P 5, Q 5)
    alfalı:   5 başlık + 1 alfa + ceil(38/2)=19 = **25 bayt**  (L 5×5 → 14 AC, A 14)

ÖLÇÜLDÜ (34 görsel fixture, yerel Pillow 11.3.0) — gerçek dağılım:

    alfasız: 17 B ×2 · 19 B ×1 · 21 B ×3 · 23 B ×2 · 24 B ×21
    alfalı:  23 B ×1 · 25 B ×4

Hepsi 30 baytın altında; `test_image_lqip.py` bunu her fixture'da doğrular.

Hız
---
Saf Python'da ayrıştırılabilir (separable) DCT kullanılır: önce satır dönüşümü
(nx·h·w çarpma), sonra sütun (nx·ny·h). Naif 2B döngü nx·ny·w·h yapardı — 32x32
girdide 7x7 katsayı için 50k yerine 8k çarpma, yaklaşık **6 kat** az iş.
`numpy` varsa (konteynerde var, yerelde YOK — ÖLÇÜLDÜ) vektörel yol seçilir.

`import frappe` YOKTUR.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

#: ThumbHash'in çalıştığı azami kenar. Referans uygulama 100'e kadar izin
#: verir; burada 32 seçildi çünkü hash yalnız 7x7 DCT katsayısı saklıyor —
#: 7 katsayı için Nyquist 14 örnek ister, 32 fazlasıyla yeter. Girdi kenarını
#: 100'den 32'ye indirmek çıktıyı DEĞİŞTİRMEZ ama işi ~10 kat azaltır.
MAX_EDGE: int = 32

#: Sözleşme sınırı — `encode()` bu sınırı aşarsa hata döner, sessizce geçmez.
MAX_HASH_BYTES: int = 30


def _r(x: float) -> int:
	"""Yarımı YUKARI yuvarla.

	Python'un `round()`'u bankacı yuvarlaması yapar (`round(0.5) == 0`);
	ThumbHash referansı JavaScript `Math.round` (yarım yukarı) kullanır.
	Bu fark tek başına hash baytlarını kaydırır ve başka dillerdeki çözücüler
	görüntüyü yanlış açar — bu yüzden yuvarlama elle yazıldı.
	"""
	return math.floor(x + 0.5)


# ── DCT ─────────────────────────────────────────────────────────────────


def _encode_channel(channel: list[float], nx: int, ny: int, w: int, h: int):
	"""Tek kanalı DCT katsayılarına indirge → (dc, ac listesi, ölçek).

	Ayrıştırılabilir uygulama: `f(cx,cy) = Σ_y fy(cy,y) · (Σ_x ch(x,y)·fx(cx,x))`
	İç toplam `cy`'den bağımsız olduğu için bir kez hesaplanıp saklanır.
	"""
	fx = [[math.cos(math.pi / w * cx * (x + 0.5)) for x in range(w)] for cx in range(nx)]
	fy = [[math.cos(math.pi / h * cy * (y + 0.5)) for y in range(h)] for cy in range(ny)]

	# Satır dönüşümü: satir[cx][y]
	satir: list[list[float]] = []
	for cx in range(nx):
		fxc = fx[cx]
		kolon: list[float] = []
		for y in range(h):
			taban = y * w
			s = 0.0
			for x in range(w):
				s += channel[taban + x] * fxc[x]
			kolon.append(s)
		satir.append(kolon)

	dc = 0.0
	ac: list[float] = []
	olcek = 0.0
	alan = float(w * h)
	for cy in range(ny):
		fyc = fy[cy]
		for cx in range(nx):
			# Referansın üçgen maskesi: yüksek frekanslı köşe atılır.
			if cx * ny >= nx * (ny - cy):
				break
			kolon = satir[cx]
			s = 0.0
			for y in range(h):
				s += kolon[y] * fyc[y]
			f = s / alan
			if cx or cy:
				ac.append(f)
				if abs(f) > olcek:
					olcek = abs(f)
			else:
				dc = f
	if olcek > 0:
		yari = 0.5 / olcek
		ac = [0.5 + yari * v for v in ac]
	return dc, ac, olcek


def _encode_channel_np(channel, nx: int, ny: int, w: int, h: int):
	"""`_encode_channel`'ın numpy yolu — aynı sayıları üretir."""
	import numpy as np

	ch = np.asarray(channel, dtype=np.float64).reshape(h, w)
	x = np.arange(w) + 0.5
	y = np.arange(h) + 0.5
	fx = np.cos(np.pi / w * np.outer(np.arange(nx), x))  # (nx, w)
	fy = np.cos(np.pi / h * np.outer(np.arange(ny), y))  # (ny, h)
	# (ny, nx): fy @ ch @ fx.T
	tam = (fy @ ch @ fx.T) / float(w * h)

	dc = 0.0
	ac: list[float] = []
	olcek = 0.0
	for cy in range(ny):
		for cx in range(nx):
			if cx * ny >= nx * (ny - cy):
				break
			f = float(tam[cy, cx])
			if cx or cy:
				ac.append(f)
				if abs(f) > olcek:
					olcek = abs(f)
			else:
				dc = f
	if olcek > 0:
		yari = 0.5 / olcek
		ac = [0.5 + yari * v for v in ac]
	return dc, ac, olcek


def _kanal_kodla(channel, nx, ny, w, h, hizli: bool):
	if hizli:
		try:
			return _encode_channel_np(channel, nx, ny, w, h)
		except Exception:
			pass
	return _encode_channel(channel, nx, ny, w, h)


def _numpy_var() -> bool:
	try:
		import numpy  # noqa: F401

		return True
	except Exception:
		return False


# ── ThumbHash ───────────────────────────────────────────────────────────


def rgba_to_thumb_hash(w: int, h: int, rgba) -> bytes:
	"""ThumbHash üret. `rgba` uzunluğu `w*h*4` olan bayt/sekizli dizisidir.

	Uygulama Evan Wallace'ın referans algoritmasına **bayt bayt uyumludur**;
	`_r()` yuvarlaması ve üçgen katsayı maskesi bilerek birebir kopyalandı ki
	tarayıcıdaki `thumbhash` çözücüsü aynı görüntüyü açsın.
	"""
	if w <= 0 or h <= 0:
		raise ValueError("ThumbHash: sıfır ölçü")
	if w > 100 or h > 100:
		raise ValueError(f"ThumbHash: girdi 100x100'ü aşamaz, {w}x{h} verildi")

	n = w * h
	hizli = _numpy_var() and n >= 256

	# 1 — alfa ile ağırlıklandırılmış ortalama renk.
	avg_r = avg_g = avg_b = avg_a = 0.0
	for i in range(n):
		j = i * 4
		alpha = rgba[j + 3] / 255.0
		avg_r += alpha / 255.0 * rgba[j]
		avg_g += alpha / 255.0 * rgba[j + 1]
		avg_b += alpha / 255.0 * rgba[j + 2]
		avg_a += alpha
	if avg_a > 0:
		avg_r /= avg_a
		avg_g /= avg_a
		avg_b /= avg_a

	has_alpha = avg_a < n
	l_limit = 5 if has_alpha else 7
	uzun = float(max(w, h))
	lx = max(1, _r(l_limit * w / uzun))
	ly = max(1, _r(l_limit * h / uzun))

	# 2 — LPQA kanallarına ayır. Saydam pikseller ortalama renge çekilir ki
	# bulanıklaştırma kenarlarda "hayalet" renk üretmesin.
	kl: list[float] = []
	kp: list[float] = []
	kq: list[float] = []
	ka: list[float] = []
	for i in range(n):
		j = i * 4
		alpha = rgba[j + 3] / 255.0
		r = avg_r * (1.0 - alpha) + alpha / 255.0 * rgba[j]
		g = avg_g * (1.0 - alpha) + alpha / 255.0 * rgba[j + 1]
		b = avg_b * (1.0 - alpha) + alpha / 255.0 * rgba[j + 2]
		kl.append((r + g + b) / 3.0)
		kp.append((r + g) / 2.0 - b)
		kq.append(r - g)
		ka.append(alpha)

	l_dc, l_ac, l_scale = _kanal_kodla(kl, max(3, lx), max(3, ly), w, h, hizli)
	p_dc, p_ac, p_scale = _kanal_kodla(kp, 3, 3, w, h, hizli)
	q_dc, q_ac, q_scale = _kanal_kodla(kq, 3, 3, w, h, hizli)
	if has_alpha:
		a_dc, a_ac, a_scale = _kanal_kodla(ka, 5, 5, w, h, hizli)
	else:
		a_dc, a_ac, a_scale = 1.0, [], 1.0

	# 3 — paketle.
	yatay = w > h
	header24 = (
		_r(63.0 * l_dc)
		| (_r(31.5 + 31.5 * p_dc) << 6)
		| (_r(31.5 + 31.5 * q_dc) << 12)
		| (_r(31.0 * l_scale) << 18)
		| ((1 if has_alpha else 0) << 23)
	)
	header16 = (
		(ly if yatay else lx)
		| (_r(63.0 * p_scale) << 3)
		| (_r(63.0 * q_scale) << 9)
		| ((1 if yatay else 0) << 15)
	)
	out = bytearray(
		[
			header24 & 255,
			(header24 >> 8) & 255,
			(header24 >> 16) & 255,
			header16 & 255,
			(header16 >> 8) & 255,
		]
	)
	if has_alpha:
		out.append(_r(15.0 * a_dc) | (_r(15.0 * a_scale) << 4))

	kanallar = [l_ac, p_ac, q_ac] + ([a_ac] if has_alpha else [])
	ac_start = len(out)
	toplam_ac = sum(len(c) for c in kanallar)
	out.extend(bytes((toplam_ac + 1) // 2))
	ac_index = 0
	for ch in kanallar:
		for f in ch:
			out[ac_start + (ac_index >> 1)] |= _r(15.0 * f) << ((ac_index & 1) * 4)
			ac_index += 1
	return bytes(out)


def thumb_hash_to_average_rgba(hash_bytes: bytes) -> tuple[float, float, float, float]:
	"""Hash'ten **çözmeden** ortalama rengi oku — ilk 3 baytta duruyor.

	Bu, "baskın renk"in bedava yoludur: görsel yeniden açılmaz. Kullanımı
	CSS `background-color` için yeterlidir; ThumbHash'i çözmeye gerek yoktur.
	"""
	if len(hash_bytes) < 5:
		raise ValueError("ThumbHash: eksik başlık")
	header = hash_bytes[0] | (hash_bytes[1] << 8) | (hash_bytes[2] << 16)
	l = (header & 63) / 63.0
	p = ((header >> 6) & 63) / 31.5 - 1.0
	q = ((header >> 12) & 63) / 31.5 - 1.0
	has_alpha = (header >> 23) != 0
	a = (hash_bytes[5] & 15) / 15.0 if has_alpha else 1.0
	b = l - 2.0 / 3.0 * p
	r = (3.0 * l - b + q) / 2.0
	g = r - q
	return (
		max(0.0, min(1.0, r)),
		max(0.0, min(1.0, g)),
		max(0.0, min(1.0, b)),
		a,
	)


# ── Sonuç ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LqipResult:
	"""LQIP çıktısı. `ok=False` ise `hash` boştur ve `reason` doludur."""

	ok: bool
	hash: bytes = b""
	#: Ortalama renk `#rrggbb` — hash'in ilk 3 baytından türetilir.
	average_hex: str = ""
	#: En çok yer kaplayan renk `#rrggbb` — nicelenmiş histogramdan.
	dominant_hex: str = ""
	#: Baskın rengin kapladığı alan oranı (0..1).
	dominant_share: float = 0.0
	has_alpha: bool = False
	width: int = 0
	height: int = 0
	reason: str = ""

	@property
	def size_bytes(self) -> int:
		return len(self.hash)

	@property
	def base64(self) -> str:
		"""HTML'e gömmeye hazır biçim (`data-thumbhash` özniteliği için)."""
		import base64

		return base64.b64encode(self.hash).decode("ascii")

	def to_dict(self) -> dict:
		return {
			"ok": self.ok,
			"hash_b64": self.base64 if self.hash else "",
			"size_bytes": self.size_bytes,
			"average_hex": self.average_hex,
			"dominant_hex": self.dominant_hex,
			"dominant_share": round(self.dominant_share, 4),
			"has_alpha": self.has_alpha,
			"width": self.width,
			"height": self.height,
			"reason": self.reason,
		}


def _hex(r: float, g: float, b: float) -> str:
	kr = max(0, min(255, _r(r * 255)))
	kg = max(0, min(255, _r(g * 255)))
	kb = max(0, min(255, _r(b * 255)))
	return f"#{kr:02x}{kg:02x}{kb:02x}"


def dominant_color(im, *, buckets: int = 16) -> tuple[str, float]:
	"""Baskın rengi nicelenmiş histogramdan bul → (`#rrggbb`, alan oranı).

	Ortalama renk baskın renk DEĞİLDİR: kırmızı-yeşil bir görselin ortalaması
	kirli sarıdır ve görselde o renkten tek piksel bulunmaz. Ön izleme fonu
	için göze doğru gelen, en çok yer kaplayan renktir.

	Saydam pikseller SAYILMAZ — kesim bir logonun baskın rengi, arkasındaki
	boşluk değil, logonun kendisidir.
	"""
	from PIL import Image

	if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
		rgba = im.convert("RGBA")
		alfa = rgba.getchannel("A")
		rgb = rgba.convert("RGB")
	else:
		rgba = None
		alfa = None
		rgb = im.convert("RGB")

	adim = 256 // buckets
	nicel = rgb.point(lambda v: min(255, (v // adim) * adim + adim // 2))
	if alfa is not None:
		# Saydamları sayım dışı bırakmak için maskeyle tek renge topla ve
		# o rengi sonuçtan düş.
		maske = alfa.point(lambda v: 255 if v >= 250 else 0)
		if maske.histogram()[255] == 0:
			return "#000000", 0.0
		bos = Image.new("RGB", rgb.size, (1, 2, 3))
		bos.paste(nicel, mask=maske)
		nicel = bos
		gecersiz = (1, 2, 3)
	else:
		gecersiz = None

	n = nicel.width * nicel.height or 1
	renkler = nicel.getcolors(maxcolors=n + 1) or []
	renkler = [(c, v) for c, v in renkler if v != gecersiz]
	if not renkler:
		return "#000000", 0.0
	sayi, renk = max(renkler)
	gecerli = sum(c for c, _ in renkler) or 1
	return f"#{renk[0]:02x}{renk[1]:02x}{renk[2]:02x}", sayi / gecerli


def encode(
	src: bytes | bytearray | str | Path,
	*,
	max_edge: int = MAX_EDGE,
) -> LqipResult:
	"""Görselden LQIP üret. İstisna ATMAZ — `ok=False` döner.

	Girdi ÖNCE `max_edge`'e küçültülür: ThumbHash zaten 7x7 katsayı saklıyor,
	tam çözünürlükte DCT almak aynı hash'i çok daha pahalıya üretir.
	"""
	try:
		from PIL import Image
	except Exception:
		return LqipResult(ok=False, reason="pillow_unavailable")

	try:
		import io

		acik = Image.open(io.BytesIO(bytes(src))) if isinstance(src, (bytes, bytearray)) else Image.open(str(src))
		# `with`: uzun ömürlü işçi süreçte kapatılmayan her açılış bir dosya
		# tanıtıcısı sızdırır. `rgba` blok içinde kopyalanır, dışarıda kullanılır.
		with acik as im:
			if (im.format or "").upper() == "JPEG":
				im.draft("RGB", (max_edge * 2, max_edge * 2))

			# Çok kareli girdide ilk kare — LQIP tek görüntüdür.
			if getattr(im, "is_animated", False):
				im.seek(0)

			alfa_var = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
			rgba = im.convert("RGBA")
		# BOX = kutu ortalama. LANCZOS keskinleştirir ve halkalanma üretir;
		# LQIP zaten bulanık bir ön izleme olduğu için keskinlik kayıp değil.
		rgba.thumbnail((max_edge, max_edge), Image.BOX)
		w, h = rgba.size
		if w < 1 or h < 1:
			return LqipResult(ok=False, reason="empty_image")

		ham = rgba.tobytes()
		h_bytes = rgba_to_thumb_hash(w, h, ham)
		if len(h_bytes) > MAX_HASH_BYTES:
			return LqipResult(ok=False, reason=f"hash_too_large:{len(h_bytes)}")

		r, g, b, _a = thumb_hash_to_average_rgba(h_bytes)
		bask, oran = dominant_color(rgba)

		return LqipResult(
			ok=True,
			hash=h_bytes,
			average_hex=_hex(r, g, b),
			dominant_hex=bask,
			dominant_share=oran,
			has_alpha=bool(alfa_var),
			width=w,
			height=h,
		)
	except Exception as exc:  # noqa: BLE001 — LQIP üretimi çağıranı patlatmaz
		return LqipResult(ok=False, reason=f"error:{type(exc).__name__}: {exc}")


# ── Çözücü (doğrulama için) ─────────────────────────────────────────────


def thumb_hash_aspect_ratio(hash_bytes: bytes) -> float:
	"""Hash'in taşıdığı yaklaşık en-boy oranı — çözmeye gerek yok.

	Oranın hash'in İÇİNDE olması ThumbHash'i BlurHash'ten ayıran şeydir:
	yer tutucu kutu, görsel inmeden önce doğru oranda çizilebilir ve sayfa
	yerleşimi kaymaz (CLS).
	"""
	if len(hash_bytes) < 5:
		raise ValueError("ThumbHash: eksik başlık")
	alfa = hash_bytes[2] & 0x80
	yatay = hash_bytes[4] & 0x80
	lx = (5 if alfa else 7) if yatay else (hash_bytes[3] & 7)
	ly = (hash_bytes[3] & 7) if yatay else (5 if alfa else 7)
	return (lx or 1) / (ly or 1)


def thumb_hash_to_rgba(hash_bytes: bytes) -> tuple[int, int, bytearray]:
	"""Hash'i küçük bir RGBA görüntüye geri aç → (w, h, baytlar).

	Üretim yolunda gerekmez (çözme tarayıcıda yapılır) ama **testin
	doğrulayabilmesi** için gerekir: hash'in gerçekten görseli temsil ettiği,
	ancak geri açıp özgün küçültülmüş görüntüyle karşılaştırarak gösterilebilir.
	Referans çözücüyle aynı katsayı sırasını ve aynı 1,25 renk ölçeğini kullanır.
	"""
	if len(hash_bytes) < 5:
		raise ValueError("ThumbHash: eksik başlık")
	header24 = hash_bytes[0] | (hash_bytes[1] << 8) | (hash_bytes[2] << 16)
	header16 = hash_bytes[3] | (hash_bytes[4] << 8)
	l_dc = (header24 & 63) / 63.0
	p_dc = ((header24 >> 6) & 63) / 31.5 - 1.0
	q_dc = ((header24 >> 12) & 63) / 31.5 - 1.0
	l_scale = ((header24 >> 18) & 31) / 31.0
	has_alpha = bool(header24 >> 23)
	p_scale = ((header16 >> 3) & 63) / 63.0
	q_scale = ((header16 >> 9) & 63) / 63.0
	yatay = bool(header16 >> 15)
	lx = max(3, (5 if has_alpha else 7) if yatay else (header16 & 7))
	ly = max(3, (header16 & 7) if yatay else (5 if has_alpha else 7))
	a_dc = (hash_bytes[5] & 15) / 15.0 if has_alpha else 1.0
	a_scale = ((hash_bytes[5] >> 4) & 15) / 15.0 if has_alpha else 1.0

	ac_start = 6 if has_alpha else 5
	durum = {"i": 0}

	def coz(nx: int, ny: int, scale: float):
		ac = []
		for cy in range(ny):
			for cx in range(nx):
				if cx * ny >= nx * (ny - cy):
					break
				if cx == 0 and cy == 0:
					continue
				i = durum["i"]
				bayt = hash_bytes[ac_start + (i >> 1)]
				deger = (((bayt >> ((i & 1) * 4)) & 15) / 7.5 - 1.0) * scale
				ac.append((cx, cy, deger))
				durum["i"] = i + 1
		return ac

	l_ac = coz(lx, ly, l_scale)
	p_ac = coz(3, 3, p_scale * 1.25)
	q_ac = coz(3, 3, q_scale * 1.25)
	a_ac = coz(5, 5, a_scale) if has_alpha else []

	oran = thumb_hash_aspect_ratio(hash_bytes)
	w = max(1, _r(32.0 if oran > 1 else 32.0 * oran))
	h = max(1, _r(32.0 / oran if oran > 1 else 32.0))

	# Kosinüs tabloları bir kez — piksel başına yeniden hesaplamak
	# çözmeyi ölçüde kareyle pahalılaştırır.
	kx = [[math.cos(math.pi / w * (x + 0.5) * cx) for x in range(w)] for cx in range(max(lx, 5, 3))]
	ky = [[math.cos(math.pi / h * (y + 0.5) * cy) for y in range(h)] for cy in range(max(ly, 5, 3))]

	out = bytearray(w * h * 4)
	for y in range(h):
		for x in range(w):
			l, p, q, a = l_dc, p_dc, q_dc, a_dc
			for cx, cy, v in l_ac:
				l += v * kx[cx][x] * ky[cy][y]
			for cx, cy, v in p_ac:
				p += v * kx[cx][x] * ky[cy][y]
			for cx, cy, v in q_ac:
				q += v * kx[cx][x] * ky[cy][y]
			for cx, cy, v in a_ac:
				a += v * kx[cx][x] * ky[cy][y]
			b = l - 2.0 / 3.0 * p
			r = (3.0 * l - b + q) / 2.0
			g = r - q
			i = (y * w + x) * 4
			out[i] = max(0, min(255, _r(r * 255)))
			out[i + 1] = max(0, min(255, _r(g * 255)))
			out[i + 2] = max(0, min(255, _r(b * 255)))
			out[i + 3] = max(0, min(255, _r(a * 255)))
	return w, h, out
