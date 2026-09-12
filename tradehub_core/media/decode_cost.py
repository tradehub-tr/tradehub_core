"""Görsel çözme (decode) maliyeti — §9'un eksik dördüncü bileşeni.

ŞARTNAME NE İSTİYOR
-------------------
§9: "Media Size değerlendirmesi byte, pixel, decode complexity ve render size
bileşenlerini birlikte kullanmalı." Kabul kriteri 11 aynısını tekrarlıyor.

10 Eylül 2026 denetimi: byte (`oversized_image`), pixel (`th_media_width/
height`) ve render size (`aspect_ratio_mismatch`, `unserved_renditions`)
ölçülüyordu; `decode` kelimesi kod tabanının TAMAMINDA geçmiyordu.

NEDEN BAYT YETMİYOR
-------------------
Bayt indirme maliyetini ölçer, çözme maliyetini DEĞİL. İkisi ters yönde
çalışabiliyor: AVIF aynı görseli JPEG'in yarısı baytta taşır ama çözmesi
belirgin biçimde pahalıdır. Yalnız bayta bakan bir denetim "AVIF'e geç,
her şey iyileşir" der; düşük uçlu bir telefonda LCP'nin kötüleştiğini
göremez. `oversized_image` kuralının tek başına yanılttığı yer tam burası.

MODEL — ÖLÇÜM DEĞİL, TAHMİN
---------------------------
Gerçek decode süresi cihaza bağlı ve sunucuda ölçülemez. Buradaki sayı bir
TAHMİN ve birimi milisaniye DEĞİL, "referans megapiksel" (RMP):

    RMP = megapiksel × format_katsayısı × alfa_katsayısı × progressive_katsayısı

Katsayılar Chrome'un yayımlanmış decode karşılaştırmalarının BÜYÜKLÜK
SIRASINI yansıtıyor, birebir sayısını değil — bu yüzden eşik de mutlak bir
süre değil, kendi katalogumuza göre kalibre edilmiş bir sınır.

Neden yine de değerli: aynı ölçekte iki görseli karşılaştırabiliyor ve
"bu 12 MP AVIF, şu 12 MP JPEG'den ~2 kat pahalı" diyebiliyor. Denetimin
ihtiyacı olan da bu — mutlak süre değil, hangi varlığın sorunlu olduğu.
"""

from __future__ import annotations

#: Format → göreli çözme katsayısı. Taban JPEG = 1.0.
#:
#: PNG < JPEG: kayıpsız ama zlib çözme, DCT'den ucuz. WebP JPEG'in biraz
#: üstünde (VP8 anahtar karesi). AVIF belirgin biçimde pahalı (AV1 intra).
#: Bilinmeyen format 1.0 sayılır — cezalandırmak da ödüllendirmek de
#: uydurma olurdu.
FORMAT_KATSAYI: dict[str, float] = {
	"jpg": 1.0,
	"jpeg": 1.0,
	"png": 0.8,
	"gif": 0.7,
	"bmp": 0.3,
	"webp": 1.3,
	"avif": 2.6,
	"heic": 2.4,
	"tif": 0.9,
	"tiff": 0.9,
	"svg": 0.0,  # vektör: raster çözme yok, maliyet ayrı bir konu (rasterize)
}

#: Alfa kanalı çözmeye ek bant ve kompozisyon getirir.
ALFA_KATSAYI: float = 1.15

#: Progressive JPEG çok geçişli çözülür — tek geçişliye göre pahalı.
PROGRESSIVE_KATSAYI: float = 1.35

#: Uyarı eşiği (RMP). 8 MP JPEG (~8.0 RMP) sınırda; 4 MP AVIF (~10.4 RMP)
#: aşıyor. Ölçüm temeli: katalogdaki görsellerin %95'i 4 MP altında
#: (rapor: medya-cozunurluk-olcumu), yani bu eşik normal içeriği değil
#: yalnız aykırı değerleri yakalar.
UYARI_ESIGI: float = 8.0


def format_of(file_name: str) -> str:
	"""Dosya adından format anahtarı — noktasız, küçük harf."""
	return (file_name or "").rsplit(".", 1)[-1].lower() if "." in (file_name or "") else ""


def estimate(
	*,
	width: int,
	height: int,
	file_format: str = "",
	has_alpha: bool = False,
	progressive: bool = False,
) -> float:
	"""Referans megapiksel cinsinden çözme maliyeti tahmini.

	Boyut bilinmiyorsa 0.0 döner — "bilinmiyor" ile "ucuz" ayrımı çağıranın
	işi; burada uydurma bir varsayılan üretmek denetimi yanıltırdı
	(`missing_dimensions` zaten ayrı bir bulgu).
	"""
	genislik = max(0, int(width or 0))
	yukseklik = max(0, int(height or 0))
	if not (genislik and yukseklik):
		return 0.0

	megapiksel = (genislik * yukseklik) / 1_000_000.0
	maliyet = megapiksel * FORMAT_KATSAYI.get((file_format or "").lower(), 1.0)
	if has_alpha:
		maliyet *= ALFA_KATSAYI
	if progressive:
		maliyet *= PROGRESSIVE_KATSAYI
	return round(maliyet, 3)


def media_size(
	*,
	width: int,
	height: int,
	bytes_: int,
	file_format: str = "",
	rendered_width: int = 0,
	rendered_height: int = 0,
	has_alpha: bool = False,
	progressive: bool = False,
) -> dict:
	"""Şartnamenin istediği DÖRT bileşeni tek sözlükte topla (§9).

	`rendered_*` verilmezse `oversize_ratio` hesaplanmaz (None) — sıfır
	yazmak "hiç büyütülmemiş" demek olurdu ve o yanlış bir iddia.
	"""
	megapiksel = round((max(0, int(width or 0)) * max(0, int(height or 0))) / 1_000_000.0, 3)
	cozme = estimate(
		width=width,
		height=height,
		file_format=file_format,
		has_alpha=has_alpha,
		progressive=progressive,
	)

	oran = None
	render_piksel = max(0, int(rendered_width or 0)) * max(0, int(rendered_height or 0))
	if render_piksel and megapiksel:
		oran = round((megapiksel * 1_000_000.0) / render_piksel, 2)

	return {
		"bytes": max(0, int(bytes_ or 0)),
		"megapixels": megapiksel,
		"decode_cost": cozme,
		"decode_over_budget": cozme > UYARI_ESIGI,
		"rendered_pixels": render_piksel,
		"oversize_ratio": oran,
	}
