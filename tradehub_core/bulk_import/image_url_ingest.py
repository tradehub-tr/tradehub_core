"""Uzak görsel URL'lerini indirip Frappe File olarak barındırma.

Feed/import satırındaki uzak görsel URL'leri (ör. `https://cdn.../foo.jpg`)
doğrudan Listing'e referanslamak yerine sunucuya indirilir, doğrulanır ve
yerel bir File DocType olarak saklanır; böylece dış host kaybolsa bile görsel
korunur ve hotlink/SSRF yüzeyi kapanır.

Güvenlik:
- Her URL `feed_security.validate_feed_url` ile SSRF'e (iç-IP/loopback/metadata)
  karşı doğrulanır.
- İndirme `feed_security.fetch_feed` ile boyut limiti (varsayılan 5 MB) ve
  timeout altında yapılır.
- İndirilen bayt'ın türü magic-number ile sniff edilir (sunucu Content-Type'ı
  yalan söyleyebileceği için header'a güvenilmez); yalnızca jpg/jpeg/png/webp.

Hata politikası: geçersiz/erişilemeyen URL bir HATA değil UYARI'dır — atlanır,
çağırana uyarı mesajı döndürülür (raise edilmez). Satır yine yüklenir.

Dedup: aynı URL feed her çekildiğinde tekrar indirilmesin diye URL-hash'li bir
cache (Redis) tutulur (key: img_ingest:<sha1(url)> → yerel File URL).
"""

import hashlib

import frappe
from frappe import _

from tradehub_core.bulk_import import feed_security

# Plan #1 whitelist: gif/bmp DAHİL DEĞİL (image_matcher'dan daha dar).
ALLOWED_EXT: dict[str, str] = {
	"jpg": ".jpg",
	"jpeg": ".jpg",
	"png": ".png",
	"webp": ".webp",
}

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB / görsel (plan limiti)
FETCH_TIMEOUT = 30
CACHE_PREFIX = "img_ingest:"
CACHE_TTL = 7 * 24 * 60 * 60  # 7 gün — feed'ler periyodik çekildiği için


def _detect_image_kind(content: bytes) -> str | None:
	"""Bayt imzasından görsel türünü döndür (jpg/png/webp) veya None.

	Content-Type header'ı yerine magic-number kullanılır; bazı CDN'ler yanlış
	veya genel (application/octet-stream) tür bildirir.
	"""
	if len(content) < 12:
		return None
	# JPEG: FF D8 FF
	if content[:3] == b"\xff\xd8\xff":
		return "jpg"
	# PNG: 89 50 4E 47 0D 0A 1A 0A
	if content[:8] == b"\x89PNG\r\n\x1a\n":
		return "png"
	# WEBP: "RIFF" .... "WEBP"
	if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
		return "webp"
	return None


def _cache_key(url: str) -> str:
	return CACHE_PREFIX + hashlib.sha1(url.encode("utf-8")).hexdigest()


def _save_file(content: bytes, kind: str, url: str, seller_profile: str) -> str:
	"""İndirilen bayt'ı public File olarak kaydet, file_url döndür.

	image_matcher._extract_and_save desenini yansıtır (public, ignore_permissions);
	dosya adı URL-hash'inden türetilir (dedup ve tahmin edilemez ad için).
	"""
	# Web boyutuna küçült + yeniden sıkıştır (format korunur; başarısızsa orijinal).
	from tradehub_core.bulk_import.image_matcher import optimize_image

	content = optimize_image(content)
	digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
	file_name = f"{digest}{ALLOWED_EXT[kind]}"
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": 0,
			"decode": False,
		}
	)
	# Arka plan içe aktarma işi; satıcı kimliği doğrulanmış, seller_profile
	# açıkça set edili. Rol-bazlı File create izni düşmesin diye ignore_permissions.
	file_doc.insert(ignore_permissions=True)
	return file_doc.file_url


def ingest_image_urls(
	urls: list[str],
	seller_profile: str,
	warnings: list[str] | None = None,
) -> list[str]:
	"""Uzak görsel URL'lerini indirip yerel File URL listesine çevir.

	Args:
	    urls: İndirilecek uzak http(s) görsel URL'leri.
	    seller_profile: Satıcı kapsamı (loglama/sahiplik için).
	    warnings: Doluysa, atlanan URL'ler için uyarı mesajları buraya eklenir.

	Returns:
	    Başarıyla barındırılan görsellerin yerel File URL listesi (sıra korunur).
	    Geçersiz/erişilemeyen URL'ler sessizce atlanır (warnings'e yazılır).
	"""
	local_urls: list[str] = []
	seen: set[str] = set()

	for raw in urls:
		url = (raw or "").strip()
		if not url or url in seen:
			continue
		seen.add(url)

		# Dedup cache — aynı URL daha önce indirildiyse yeniden indirme.
		# expires=True ZORUNLU: bu key setex (expires_in_sec) ile yazılıyor; o yol
		# frappe.local.cache'i doldurmaz. expires=False ile okursak miss anında
		# get_value local cache'e None yazar (redis_wrapper.get_value), sonraki
		# set_value yalnızca Redis'e yazdığı için aynı request içinde tekrar eden
		# URL stale None okur → dedup çalışmaz, görsel yeniden indirilir.
		cache_key = _cache_key(url)
		cached = frappe.cache.get_value(cache_key, expires=True)
		if cached:
			local_urls.append(cached)
			continue

		try:
			feed_security.validate_feed_url(url)
			content = feed_security.fetch_feed(
				url,
				max_bytes=MAX_IMAGE_BYTES,
				timeout=FETCH_TIMEOUT,
			)
		except frappe.ValidationError as e:
			# validate_feed_url / fetch_feed frappe.throw eder — UYARI'ya çevir,
			# satırı düşürme.
			if warnings is not None:
				warnings.append(_("Görsel indirilemedi ({0}): {1}").format(url, str(e)))
			continue
		except Exception as e:
			frappe.log_error(
				f"Image URL ingest failed {url}: {e}",
				"bulk_import.image_url_ingest",
			)
			if warnings is not None:
				warnings.append(_("Görsel indirilemedi: {0}").format(url))
			continue

		kind = _detect_image_kind(content)
		if not kind:
			if warnings is not None:
				warnings.append(_("Görsel türü desteklenmiyor (yalnızca jpg/png/webp): {0}").format(url))
			continue

		try:
			file_url = _save_file(content, kind, url, seller_profile)
		except Exception as e:
			frappe.log_error(
				f"Image URL save failed {url}: {e}",
				"bulk_import.image_url_ingest",
			)
			if warnings is not None:
				warnings.append(_("Görsel kaydedilemedi: {0}").format(url))
			continue

		frappe.cache.set_value(cache_key, file_url, expires_in_sec=CACHE_TTL)
		local_urls.append(file_url)

	return local_urls
