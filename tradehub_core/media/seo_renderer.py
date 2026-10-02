"""Okunur görsel adresi → servis (spec 2026-09-28-seo-gorsel-adresi §5.4).

Diskte olmayan `/files/…` istekleri buraya düşer (backend nginx `try_files … @webserver`).
Final review I-2: Frappe'nin kendi kuralı (`frappe.utils.response.send_private_file`)
izlenir — X-Accel YALNIZ istek `X-Use-X-Accel-Redirect` başlığını taşıyorsa (backend
nginx `proxy_set_header X-Use-X-Accel-Redirect True` basıyor) kullanılır; o zaman
baytları nginx gönderir (`/protected/` iç konumu). Başlık yoksa (doğrudan gunicorn,
`bench serve`, X-Accel işlemeyen bir vekil) baytlar BURADAN akıtılır — boş gövdeli
200'ün CDN'de bir yıl önbelleğe girmesi imkânsız olur.

`yok` durumunda da bu renderer yanıtı KENDİSİ verir (Frappe'nin `NotFoundPage`'ine
bırakmaz): `NotFoundPage.render` isteği `website_404` negatif önbelleğine yazar ve
`PathResolver.resolve` o önbelleğe renderer'lardan ÖNCE bakar. Türevi henüz
üretilmemiş ya da kodu henüz atanmamış bir görsel bir kez 404 alırsa, dosya sonra
gelse bile adres önbellek temizlenene kadar 404 kalırdı. Burada 404 kısa ömürlü ve
önbelleğe yazılmadan döner. Okunur desene uyan eski-ad dosyaları için (ör.
`urun-20240101.jpg`) önce `MediaRedirectRenderer`'a sorulur — 301 köprüsü kaybolmaz.
"""

from __future__ import annotations

import os

import frappe
from frappe.website.page_renderers.redirect_page import RedirectPage
from werkzeug.utils import send_file
from werkzeug.wrappers import Response

from tradehub_core.media import seo_url
from tradehub_core.media.redirect_renderer import MediaRedirectRenderer

CACHE_CONTROL = "public, max-age=31536000, immutable"
# 404 kısa ömürlü: dosya/türev birazdan gelebilir; CDN/tarayıcı uzun tutmasın.
CACHE_CONTROL_404 = "public, max-age=60"
# Final review M-2: A→B→A yeniden adlandırmada CDN'deki eski 301 ile origin'in yeni
# 301'i bir saat döngü kurabilirdi — 5 dakikaya indirildi.
CACHE_CONTROL_301 = "public, max-age=300"


class SeoImageRenderer:
	def __init__(self, path: str, http_status_code: int | None = None) -> None:
		self.path = path or ""
		self.http_status_code = http_status_code
		self.sonuc: dict | None = None

	def can_render(self) -> bool:
		if not self.path.startswith("files/") or not seo_url.SEO_RE.match(self.path.split("?")[0]):
			return False
		self.sonuc = seo_url.resolve(self.path)
		return True

	def render(self) -> Response:
		_cerezleri_bastir()
		if self.sonuc is None:
			self.sonuc = seo_url.resolve(self.path)
		if self.sonuc["status"] == "yok":
			return self._bulunamadi()
		if self.sonuc["status"] == "slug_eski":
			frappe.flags.redirect_location = self.sonuc["canonical"]
			yanit = RedirectPage(self.path, 301).render()
			# Review M-5: Frappe 301'e `no-store` basıyor; eski slug isteği her seferinde
			# backend'e gelirdi. Kanonik slug ürün adı değişince değişebilir → kısa ömür.
			yanit.headers["Cache-Control"] = CACHE_CONTROL_301
			return yanit
		disk_url = self.sonuc["disk_url"]
		istek = getattr(frappe.local, "request", None)
		if istek is not None and istek.headers.get("X-Use-X-Accel-Redirect"):
			yanit = Response(status=200)
			yanit.headers["X-Accel-Redirect"] = "/protected/public" + disk_url
			yanit.headers["Accept-Ranges"] = "bytes"
		else:
			yanit = _akit(disk_url, istek)
		yanit.headers["Cache-Control"] = CACHE_CONTROL
		# nginx X-Accel'de upstream'in Content-Type'ını korur; werkzeug varsayılanı
		# (`text/plain`) kalırsa görsel yanlış tipte gider — uzantıdan açıkça yazılır.
		yanit.headers["Content-Type"] = seo_url.mime_of(disk_url)
		return yanit

	def _bulunamadi(self) -> Response:
		# I6 (fix round 1, kare dönüşümü): kod artık `File.seo_code`'da yok ama
		# eski içerik-adresli adres kare/retro-rename ile taşınmış olabilir —
		# `Media URL Redirect` üzerinden yeni dosyaya 301. `MediaRedirectRenderer`
		# bunu YAKALAYAMAZ: o yalnız `source_url`'in TIPKISINI (`self.path`) arıyor,
		# oysa buradaki eski adres hash'li bir içerik-adresi, okunur slug değil.
		hedef = seo_url.resolve_retired_code(self.path)
		if hedef:
			frappe.flags.redirect_location = hedef
			yanit = RedirectPage(self.path, 301).render()
			# Review M-5 ile aynı gerekçe: kanonik adres değişebilir, CDN uzun tutmasın.
			yanit.headers["Cache-Control"] = CACHE_CONTROL_301
			return yanit
		kopru = MediaRedirectRenderer(self.path, self.http_status_code)
		if kopru.can_render():
			return kopru.render()
		yanit = Response("Not Found", status=404, content_type="text/plain; charset=utf-8")
		yanit.headers["Cache-Control"] = CACHE_CONTROL_404
		return yanit


def _akit(disk_url: str, istek) -> Response:
	"""X-Accel yokken dosyayı werkzeug ile akıt (koşullu istek / Range desteğiyle).

	`disk_url` `resolve`'dan gelir: hash + regex'ten geçmiş türev/uzantı — istekteki
	slug'dan KURULMAZ, yol geçişi mümkün değil.
	"""
	from frappe.utils import get_files_path

	yol = os.path.join(get_files_path(is_private=0), disk_url[len("/files/") :])
	if istek is not None:
		ortam = istek.environ
	else:
		from werkzeug.test import EnvironBuilder

		ortam = EnvironBuilder().get_environ()
	return send_file(yol, environ=ortam, mimetype=seo_url.mime_of(disk_url), conditional=True)


def _cerezleri_bastir() -> None:
	"""Görsel yanıtında `Set-Cookie` olmasın.

	Frappe her yanıta (misafire bile) `sid=Guest`, `full_name`, `user_id`… çerezlerini
	basıyor (`app.process_response` → `CookieManager.flush_cookies`). Çerezli yanıtı
	CDN'ler (Cloudflare vb.) önbelleğe almaz; `immutable` başlığı boşa gider. Görsel
	isteğinin oturumla işi yok: bu istekte yazılacak çerezler düşürülür (oturum
	süresinin bu istekte uzatılmaması zararsız). `to_delete` (çıkış temizliği) korunur.
	"""
	yonetici = getattr(frappe.local, "cookie_manager", None)
	if yonetici is not None:
		yonetici.cookies = {}
