"""Liste küçük resimleri — hazır türevlerden (Media Rendition) URL haritası.

Panel listeleri önizleme için ORİJİNAL dosyayı çekiyordu; 1.4 MB'lık orijinal
× 50 satır hem bant genişliği israfı hem tarayıcıda çözümleme teklemesi
(ölçüldü 2026-08-31: aynı özellikteki iki dosyadan biri kırık gelebiliyor,
kırık satır yüklemeden yüklemeye geziyor). Boru hattı zaten w96'dan başlayan
webp türevleri üretiyor — küçük resim onlardan servis edilir.

Sorgu yalnız EKRANDAKİ sayfanın adresleri için koşar (≤ ~200 satır) ve türev
yolları içerik adresli (hash'li dizin) olduğundan cache damgası gerektirmez.
"""

import frappe
from frappe.query_builder import DocType

#: Liste küçük resmi için üst sınır — daha genişi zaten "önizleme" işi.
THUMB_MAX_WIDTH = 768

#: <img>'e konulabilecek türev biçimleri. Video dosyalarının mp4 türevleri de
#: Media Rendition'da yaşıyor (preview-480.mp4 gibi) — ölçüldü 2026-08-31:
#: filtresiz sorgu videonun mp4'ünü küçük resim sanıp kırık <img> üretiyordu.
#: Videonun poster-*.webp türevi bu filtreden geçer, satır poster karesi alır.
IMAGE_FORMATS: tuple[str, ...] = ("webp", "jpeg", "jpg", "png", "avif")


def thumbs_for(file_urls: list[str] | tuple[str, ...]) -> dict[str, dict[str, str]]:
	"""`file_url` → `{"thumb": en küçük hazır türev, "preview": ≤768px'in en büyüğü}`.

	Türevi olmayan (henüz optimize edilmemiş) dosya haritada yer almaz;
	çağıran orijinale düşer. Yalnız `ready` durumundaki türevler kullanılır —
	üretimi bitmemiş ya da temizlenmiş türev URL'i ekrana sızmasın.
	"""
	urls = [u for u in dict.fromkeys(file_urls or []) if u]
	if not urls:
		return {}

	file_dt = DocType("File")
	asset = DocType("Media Asset")
	rendition = DocType("Media Rendition")
	rows = (
		frappe.qb.from_(file_dt)
		.join(asset)
		.on(asset.source_file == file_dt.name)
		.join(rendition)
		.on(rendition.asset == asset.name)
		.select(file_dt.file_url.as_("src"), rendition.file_url.as_("url"), rendition.width)
		.where(file_dt.file_url.isin(urls))
		.where(rendition.state == "ready")
		.where(rendition.width <= THUMB_MAX_WIDTH)
		.where(rendition.format.isin(list(IMAGE_FORMATS)))
		.where(rendition.file_url.isnotnull())
		.orderby(rendition.width)
		.run(as_dict=True)
	)

	out: dict[str, dict[str, str]] = {}
	for row in rows:
		entry = out.setdefault(row.src, {})
		# Genişliğe göre artan sırada geliyor: ilk görülen en küçük (thumb),
		# son görülen ≤768 içindeki en büyük (preview).
		entry.setdefault("thumb", row.url)
		entry["preview"] = row.url
	return out
