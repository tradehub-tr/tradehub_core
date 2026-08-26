"""Medya izleme sayfası (`/medya/v/<slug>`) slug/canonical üretimi + 301 köprüsü.

`File.th_media_slug`/`th_media_canonical` `v15_9_37` yamasıyla zaten açılmış
SINGLE alanlar (`media/seo.py::SINGLE`) — bu modül onlara YAZAN tek yer,
`seo.fields_for` onları OKUYAN tek kapı (aynı "tek kapı" ilkesi).

Slug bir kez üretildikten sonra kendiliğinden DEĞİŞMEZ — başlık sonradan
düzenlense bile indexlenmiş `/medya/v/<slug>` adresi SEO değeri taşır,
sessizce kaymamalı (`ensure_slug` idempotent). Bilinçli değişiklik
`change_slug` ile yapılır ve eski adresi yeniye `Media URL Redirect` ile
köprüler — doctype/alan deseni `media/retro_rename.py`'den (source_url,
target_url, job_key, expires_at).

`ensure_slug` kendi hatalarını yutar (poster ilkesiyle aynı —
`media/video_poster.py` docstring'i: "hata poster'ı değil videoyu ASLA
düşürmez"): burada da slug üretimi videonun/poster akışının yayınını asla
düşürmemeli, `video_poster.generate` başarı yolunda TEK satır çağrılır.
"""

from __future__ import annotations

from pathlib import Path

import frappe
from frappe.utils import add_days, now_datetime

from tradehub_core.media import seo
from tradehub_core.media.video_poster import VIDEO_UZANTILAR
from tradehub_core.seo.slugify import slugify_tr

#: 301 satırının ömrü — `media/retro_rename.py::REDIRECT_TTL_DAYS` ile aynı
#: fikir: eski adres süresiz yönlendirilmez, cron sonunda (`purge_expired_redirects`) 404'e döner.
REDIRECT_TTL_DAYS: int = 365
REDIRECT_JOB_KEY: str = "watch-slug"


def watch_url(slug: str) -> str:
	"""Slug'dan izleme sayfası adresi üretir. Slug boşsa boş döner."""
	return f"/medya/v/{slug}" if slug else ""


def _temiz(file_url: str) -> str:
	return (file_url or "").split("?")[0].strip()


def _yerel_mi(url: str) -> bool:
	"""Yalnız `/files/` altındaki dosyalar aday: embed (YouTube vb.) ve dış
	adresler izleme sayfası kavramına girmiyor — köprülenecek bir `File` kaydı yok."""
	return bool(url) and url.startswith("/files/")


def _hash6(name: str) -> str:
	"""İçerik hash'inin son 6 karakteri — Frappe çekirdeğinin dosya adı
	çakışma-önleme deseniyle AYNI kural (`file.py`: `content_hash[-6:]`),
	burada slug çakışma ekinde tekrarlanıyor."""
	content_hash = frappe.db.get_value("File", name, "content_hash") or ""
	if content_hash:
		return content_hash[-6:]
	# content_hash boş olabilir (remote file, eski kayıt) — o zaman rastgele
	# 6 karakter tekilliği sağlar; deterministik olması gerekmiyor, tek amaç
	# aynı adı ikinci kez üretmemek.
	return frappe.generate_hash(length=6)


def _kardes_kayitlar(adlar: list[str]) -> list[frappe._dict]:
	return frappe.get_all(
		"File", filters={"name": ["in", adlar]}, fields=["name", "th_media_slug", "file_name"]
	)


def _essiz_slug(taban: str, kendi_adlar: list[str], hash6: str) -> str:
	"""Aday slug başka bir `File`'da (kendi kardeşleri hariç) kullanılıyorsa
	içerik hash'i ekler."""
	if not frappe.db.exists("File", {"th_media_slug": taban, "name": ["not in", kendi_adlar]}):
		return taban
	return f"{taban}-{hash6}"


def _ensure_slug(url: str) -> str:
	adlar = frappe.get_all("File", filters={"file_url": url}, pluck="name")
	if not adlar:
		return ""

	kayitlar = _kardes_kayitlar(adlar)
	mevcut = next((k.th_media_slug for k in kayitlar if k.th_media_slug), None)
	if mevcut:
		eksik = [k.name for k in kayitlar if not k.th_media_slug]
		if eksik:
			# video_poster.generate'in çoklu-kayıt dersi: kardeş kayıt slug'sız
			# kalırsa `backfill_slugs` onu sonsuza dek yeniden seçer.
			frappe.db.set_value(
				"File",
				{"name": ["in", eksik]},
				{"th_media_slug": mevcut, "th_media_canonical": watch_url(mevcut)},
				update_modified=False,
			)
		return mevcut

	alanlar = seo.fields_for(url)
	govde = Path(kayitlar[0].file_name).stem if kayitlar[0].file_name else ""
	hash6 = _hash6(adlar[0])
	taban = slugify_tr(alanlar.get("title") or alanlar.get("alt") or govde)
	if not taban:
		taban = f"video-{hash6}"
	aday = _essiz_slug(taban, adlar, hash6)
	canonical = watch_url(aday)
	frappe.db.set_value(
		"File",
		{"name": ["in", adlar]},
		{"th_media_slug": aday, "th_media_canonical": canonical},
		update_modified=False,
	)
	return aday


def ensure_slug(file_url: str) -> str:
	"""Slug boşsa üretir + canonical yazar; doluysa mevcut slug'ı döner.

	`/files/` dışı (embed, dış adres) ya da hiç `File` kaydı yoksa hiçbir
	alana yazılmadan `""` döner. Hata durumunda da `""` döner — `video_poster.
	generate`'in başarı yolundan çağrıldığında bir slug üretim hatası videonun
	yayınını ASLA düşürmemeli (poster ilkesiyle aynı).
	"""
	url = _temiz(file_url)
	if not _yerel_mi(url):
		return ""
	try:
		return _ensure_slug(url)
	except Exception:
		frappe.log_error(title="watch_slug.ensure_slug", message=frappe.get_traceback())
		return ""


def change_slug(file_url: str, yeni: str) -> str:
	"""Slug'ı bilinçli değiştirir ve eski adresi yeniye 301 ile köprüler.

	Eski slug yoksa (ilk atama) köprü açılmaz — bağlanacak eski adres yok.
	Bu fonksiyon admin akışından çağrılır (`ensure_slug`'ın aksine) hatalar
	yutulmaz; çağıran uç kapıdan geçmiş yetkili bir işlem yapıyor.
	"""
	url = _temiz(file_url)
	yeni_slug = slugify_tr(yeni) or (yeni or "").strip()
	if not _yerel_mi(url) or not yeni_slug:
		return ""
	adlar = frappe.get_all("File", filters={"file_url": url}, pluck="name")
	if not adlar:
		return ""

	kayitlar = _kardes_kayitlar(adlar)
	eski = next((k.th_media_slug for k in kayitlar if k.th_media_slug), None)
	if eski == yeni_slug:
		return yeni_slug

	canonical = watch_url(yeni_slug)
	frappe.db.set_value(
		"File",
		{"name": ["in", adlar]},
		{"th_media_slug": yeni_slug, "th_media_canonical": canonical},
		update_modified=False,
	)
	if eski:
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": watch_url(eski),
				"target_url": canonical,
				"job_key": REDIRECT_JOB_KEY,
				"expires_at": add_days(now_datetime(), REDIRECT_TTL_DAYS),
			}
		).insert(ignore_permissions=True)  # sistem işi — çağıran uç admin yetki kapısından geçti
	return yeni_slug


def backfill_slugs(limit: int = 200) -> int:
	"""Posterli ama slug'sız videoları SENKRON işler — `bench execute` için.

	`video_poster.backfill_pending`'in aksine ffmpeg maliyeti yok (metin
	işlemi), bu yüzden kuyruğa atmaya gerek duymadan senkron çalıştırılabilir.
	Dönüş değeri işlenen aday sayısıdır.
	"""
	kosul = " OR ".join(f"file_url LIKE '%%{u}'" for u in VIDEO_UZANTILAR)
	satirlar = frappe.db.sql(
		f"""SELECT DISTINCT file_url FROM `tabFile`
		WHERE is_private = 0 AND ({kosul})
		AND IFNULL(th_media_poster_url, '') != ''
		AND IFNULL(th_media_slug, '') = ''
		ORDER BY creation DESC LIMIT %(limit)s""",
		{"limit": limit},
		as_dict=True,
	)  # sabit uzantı listesi — kullanıcı girdisi değil, f-string güvenli (video_poster.backfill_pending ile aynı gerekçe)
	islenen = 0
	for satir in satirlar:
		ensure_slug(satir.file_url)
		islenen += 1
	return islenen
