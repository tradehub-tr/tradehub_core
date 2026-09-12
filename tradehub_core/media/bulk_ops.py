"""Seçime uygulanan toplu medya işlemleri (MOGEM-620 §14).

NEDEN AYRI MODÜL
----------------
10 Eylül 2026 denetimi §14'ün dört öbeğinden birini eksik buldu:

    toplu taşı/etiketle/indir/yeniden işle/arşivle/sil   VARDI
    toplu ALT/yerelleştirme/boyut/optimizasyon/göç       VARDI (backfill'ler)
    toplu telif · lisans · görünürlük · index/noindex    YOKTU
    toplu yeniden adlandırma                             YOKTU

Eksik olanların ortak yanı, hepsinin `api/media_admin.py` içinde **tek dosya**
alan bir uçtan geçiyor olmasıydı (`set_media_seo`, `set_media_indexability`).
Panelden 200 dosya seçen operatör 200 istek atmak zorundaydı.

NEDEN BACKFILL'LERİN YANINA DEĞİL
---------------------------------
`backfill_media_alt` / `backfill_media_localization` KATALOG genelinde çalışır
ve adayını kendisi seçer. Buradakiler **operatörün seçtiği** kümede çalışır.
İkisi farklı sözleşme: birinde "hangi dosyalar" sorusunun cevabı koddadır,
diğerinde kullanıcıdadır. Aynı modüle koymak o ayrımı silerdi.

KISMİ BAŞARISIZLIK SÖZLEŞMESİ
-----------------------------
Kabul kriteri "yetki kontrolü, hata özeti ve kısmi başarısızlık sonucu
görünürdür" diyor. Bu yüzden HİÇBİR fonksiyon ilk hatada durmaz ve hiçbiri
sessizce atlamaz; `categories.add_to_many`'nin şekli aynen sürdürülüyor:

    {"applied": int, "files": int, "skipped": int, "failed": [{"file_url", "error"}]}

`skipped` ile `failed` AYRI: birincisi yetki/sahiplik yüzünden dokunulmayan
(beklenen), ikincisi yazma sırasında patlayan (beklenmeyen) dosya. Tek sayıya
indirmek operatöre "200'ün 50'si olmadı" der ama nedenini söylemez.

İŞLEM SINIRI
------------
Her dosya kendi `try` bloğunda; biri patlarsa öncekiler geri alınmaz. Bunun
alternatifi (hepsi-ya-hiç) 200 dosyalık bir işte tek bozuk kayıt yüzünden 199
başarılı yazmayı çöpe atardı ve operatör hangisinin bozuk olduğunu göremezdi.
"""

from __future__ import annotations

import os
import re

import frappe
from frappe import _

from tradehub_core.media import ownership, seo

#: `api/seller_media.MAX_BATCH` ile AYNI sayı, bilerek kopyalanmadı —
#: oradan içe aktarmak `api` katmanına ters bağımlılık olurdu (`media`
#: modülleri `api`'yi tanımaz). Değişirse iki yerde değişmeli; testte
#: eşitlikleri sınanıyor.
MAX_BATCH: int = 200

#: Toplu yeniden adlandırmada üretilen adın azami uzunluğu
#: (`upload_policy.MAX_NAME` ile aynı gerekçe: dosya sistemi + URL sınırı).
MAX_NAME: int = 140

#: `set_indexability_many`'nin kabul ettiği görünürlükler.
#: `api/media_admin.set_media_indexability`'deki kümeyle AYNI ve o kümenin
#: kaynağı artık burası — orada ikinci bir literal bırakmak iki listeyi
#: zamanla ayrıştırırdı.
VISIBILITIES: frozenset[str] = frozenset(
	{"Public", "Private", "Unlisted", "Protected", "Temporary", "Expired", "Archived", "Deleted"}
)

#: İzin verilen robots yönergeleri. Serbest metin KABUL EDİLMEZ: buradan
#: yazılan değer doğrudan `<meta name="robots">` ve `X-Robots-Tag` içine
#: giriyor; süzgeçsiz bırakmak operatöre arama motoruna keyfi direktif
#: gönderme yetkisi verirdi.
ROBOTS_DIRECTIVES: frozenset[str] = frozenset(
	{
		"index",
		"noindex",
		"follow",
		"nofollow",
		"nosnippet",
		"max-image-preview:none",
		"max-image-preview:standard",
		"max-image-preview:large",
		"max-video-preview:0",
		"max-video-preview:-1",
	}
)

#: Toplu düzenlemeye AÇIK varlık alanları — §14'ün "bulk copyright, license"
#: maddesi. `seo.SINGLE`'ın tamamı DEĞİL: `slug`, `canonical` ve
#: `seo_filename` her dosyada BENZERSİZ olmak zorunda ve toplu yazma onları
#: 200 dosyada aynı değere eşitlerdi — kanonik adres çakışması demek.
#: `alt_source` da dışarıda: onu insan değil üretim zinciri yazar.
BULK_FIELDS: frozenset[str] = frozenset(
	{
		"description",
		"tags",
		"creator",
		"creator_type",
		"credit_text",
		"copyright_notice",
		"license_url",
		"acquire_license_url",
		"usage_rights",
		"rights_expires_on",
	}
)


def normalize_urls(file_urls) -> tuple[str, ...]:
	"""Tekilleştirilmiş, sorgu dizesi kırpılmış adresler + tavan kontrolü."""
	urls = tuple(
		dict.fromkeys(
			str(url or "").split("?", 1)[0].strip() for url in (file_urls or []) if str(url or "").strip()
		)
	)
	if len(urls) > MAX_BATCH:
		frappe.throw(_("Tek seferde en çok {0} dosya işlenebilir.").format(MAX_BATCH))
	return urls


def _sonuc(applied: int, urls: tuple[str, ...], skipped: int, failed: list[dict]) -> dict:
	return {
		"applied": applied,
		"files": len(urls) - skipped - len(failed),
		"skipped": skipped,
		"failed": failed,
	}


def _dokunulabilir(store: str | None, url: str) -> bool:
	"""Kiracı sınırı. `store` None ise çağıran yönetici kapısından geçmiştir."""
	return True if store is None else ownership.owns(store, url)


# ── Görünürlük / indexability ────────────────────────────────────────────


def validate_robots(robots_override: str) -> str:
	"""Robots direktif dizesini doğrula; geçersizse `throw`.

	Tekil uç (`set_media_indexability`) ile toplu uç AYNI doğrulayıcıdan
	geçiyor — iki farklı süzgeç, tek dosyada yasak olanın toplu yolda serbest
	kalması demekti.
	"""
	temiz = (robots_override or "").strip()
	if not temiz:
		return ""
	parcalar = {p.strip().lower() for p in temiz.split(",") if p.strip()}
	if not parcalar or not parcalar <= ROBOTS_DIRECTIVES:
		frappe.throw(_("Geçersiz robots directive."))
	return temiz


def set_indexability_many(
	file_urls,
	visibility: str,
	*,
	expires_at: str = "",
	robots_override: str = "",
	store: str | None = None,
) -> dict:
	"""Seçili dosyaların görünürlük/indexability politikasını topluca yaz.

	`Private` BURADA DA yasak ve gerekçe tekil uçtakiyle birebir aynı: private
	geçişi dosyanın diskte taşınmasını gerektiriyor (`access_level`), yalnız
	alan yazmak dosyayı public bırakıp kaydı "private" göstererek denetimi
	kör ederdi. Toplu yolda bu daha da tehlikeli olurdu — 200 dosyada tek
	hamlede.
	"""
	if visibility not in VISIBILITIES:
		frappe.throw(_("Geçersiz medya görünürlüğü: {0}").format(visibility))
	if visibility == "Private":
		frappe.throw(
			_("Private geçişi fiziksel dosya taşıması gerektirir; erişim seviyesi aracını kullanın.")
		)
	robots = validate_robots(robots_override)
	urls = normalize_urls(file_urls)

	degerler: dict[str, object] = {"th_media_visibility": visibility}
	if frappe.db.has_column("File", "th_media_expires_at"):
		degerler["th_media_expires_at"] = expires_at or None
	if frappe.db.has_column("File", "th_media_robots_override"):
		degerler["th_media_robots_override"] = robots

	applied = 0
	skipped = 0
	failed: list[dict] = []
	for url in urls:
		if not _dokunulabilir(store, url):
			skipped += 1
			continue
		try:
			frappe.db.set_value("File", {"file_url": url}, degerler, update_modified=False)
			applied += 1
		except Exception as exc:
			frappe.log_error(title="media.bulk_ops set_indexability_many", message=frappe.get_traceback())
			failed.append({"file_url": url, "error": str(exc)})
	return _sonuc(applied, urls, skipped, failed)


# ── Telif / lisans / künye ───────────────────────────────────────────────


def set_fields_many(file_urls, values: dict, *, store: str | None = None) -> dict:
	"""Seçili dosyalara ortak varlık alanları yaz (telif, lisans, künye…).

	Beyaz liste `BULK_FIELDS`; dışarıdaki her anahtar SESSİZCE DÜŞMEZ, hata
	verir. Sessiz düşürme burada `metadata.EDITABLE`'daki gibi olamaz: orada
	çağıran bir satıcı formu ve fazladan anahtar tarayıcıdan gelen gürültü;
	burada çağıran bir operatör ve "canonical'ı 200 dosyaya yazdım sandım,
	yazılmamış" sessiz bir veri hatası olurdu.
	"""
	temiz_degerler = {k: v for k, v in (values or {}).items() if str(k or "").strip()}
	if not temiz_degerler:
		frappe.throw(_("Yazılacak alan yok."))
	yasak = set(temiz_degerler) - BULK_FIELDS
	if yasak:
		frappe.throw(_("Bu alanlar toplu yazılamaz: {0}").format(", ".join(sorted(yasak))))

	urls = normalize_urls(file_urls)
	applied = 0
	skipped = 0
	failed: list[dict] = []
	for url in urls:
		if not _dokunulabilir(store, url):
			skipped += 1
			continue
		try:
			# Tek dosya yolu (`seo.set_asset_fields`) ile AYNI kapı: doğrulama,
			# kardeş kayıt yayılımı ve mağaza sınırı orada tek yerde duruyor.
			applied += 1 if seo.set_asset_fields(url, dict(temiz_degerler), store=store) else 0
		except Exception as exc:
			frappe.log_error(title="media.bulk_ops set_fields_many", message=frappe.get_traceback())
			failed.append({"file_url": url, "error": str(exc)})
	return _sonuc(applied, urls, skipped, failed)


# ── Toplu yeniden adlandırma ─────────────────────────────────────────────

#: Desende izin verilen yer tutucular. Serbest format dizesi değil sabit
#: küme: `{}` ile gelen keyfi bir Python format ifadesi (`{0.__class__}`)
#: sunucuda nesne gezdirebilirdi.
RENAME_TOKENS: frozenset[str] = frozenset({"{ad}", "{sira}", "{uzanti}"})

_SIRA_DESEN = re.compile(r"\{sira(?::(\d+))?\}")


def render_name(pattern: str, *, taban: str, sira: int, uzanti: str) -> str:
	"""Deseni tek dosya için çöz. Saf fonksiyon — DB'ye dokunmaz.

	`{sira:3}` → `001`. Dolgu genişliği desende; varsayılan dolgusuz.
	Uzantı deseni içermiyorsa SONUNA eklenir: operatörün uzantıyı unutması
	200 dosyayı uzantısız bırakırdı ve `upload_policy.kind_of` hepsini
	"other" sayardı.
	"""
	cikti = pattern.replace("{ad}", taban).replace("{uzanti}", uzanti)
	cikti = _SIRA_DESEN.sub(lambda m: str(sira).zfill(int(m.group(1) or 0)), cikti)
	if uzanti and not cikti.lower().endswith(uzanti.lower()):
		cikti = f"{cikti}{uzanti}"
	return cikti[:MAX_NAME]


def validate_pattern(pattern: str) -> str:
	"""Deseni doğrula; geçersizse `throw`."""
	temiz = (pattern or "").strip()
	if not temiz:
		frappe.throw(_("Adlandırma deseni gerekli."))
	if len(temiz) > MAX_NAME:
		frappe.throw(_("Adlandırma deseni en çok {0} karakter olabilir.").format(MAX_NAME))
	# Yol kaçışı: desen dosya ADI üretir, yol değil. `/` ya da `..` içeren bir
	# desen `File.file_name` üzerinden dizin dışına yazma denemesi olurdu.
	if "/" in temiz or "\\" in temiz or ".." in temiz:
		frappe.throw(_("Adlandırma deseninde yol ayracı kullanılamaz."))
	bilinmeyen = set(re.findall(r"\{[a-zA-Z]+", temiz)) - {t[:-1] for t in RENAME_TOKENS}
	if bilinmeyen:
		frappe.throw(
			_("Bilinmeyen yer tutucu: {0}. Kullanılabilir: {1}").format(
				", ".join(sorted(b + "}" for b in bilinmeyen)), ", ".join(sorted(RENAME_TOKENS))
			)
		)
	return temiz


def rename_many(file_urls, pattern: str, *, start: int = 1, store: str | None = None) -> dict:
	"""Seçili dosyaların GÖRÜNEN adını desene göre topluca değiştir.

	KIRMIZI ÇİZGİ — `file_url` DEĞİŞMEZ. Bu işlem yalnız `File.file_name`'i
	yazar; fiziksel dosya ve adres yerinde kalır. Gerekçe kabul kriterinde:
	"metadata ve filename değişiklikleri Stable Asset ID'yi bozmaz". Adresi de
	değiştiren iş ayrı ve zaten var (`retro_rename`), 301 köprüsü kuruyor ve
	geri alınabiliyor; burada aynı işi ikinci kez, köprüsüz yapmak mevcut
	sayfalardaki 200 görseli birden kırardı.
	"""
	temiz_desen = validate_pattern(pattern)
	urls = normalize_urls(file_urls)
	applied = 0
	skipped = 0
	failed: list[dict] = []
	sira = max(0, int(start or 1))

	for url in urls:
		if not _dokunulabilir(store, url):
			skipped += 1
			continue
		try:
			adlar = frappe.get_all("File", filters={"file_url": url}, pluck="name")
			if not adlar:
				failed.append({"file_url": url, "error": _("Dosya kaydı yok")})
				continue
			mevcut = frappe.db.get_value("File", adlar[0], "file_name") or ""
			taban, uzanti = os.path.splitext(mevcut)
			yeni = render_name(temiz_desen, taban=taban, sira=sira, uzanti=uzanti)
			if not yeni.strip():
				failed.append({"file_url": url, "error": _("Desen boş ad üretti")})
				continue
			frappe.db.set_value("File", {"name": ["in", adlar]}, "file_name", yeni, update_modified=False)
			applied += 1
			sira += 1
		except Exception as exc:
			frappe.log_error(title="media.bulk_ops rename_many", message=frappe.get_traceback())
			failed.append({"file_url": url, "error": str(exc)})
	return _sonuc(applied, urls, skipped, failed)
