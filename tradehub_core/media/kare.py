"""Ürün görseli: kare, 1000–2000 px, beyaz dolgu.

Spec: docs/superpowers/specs/2026-09-29-urun-gorseli-kare-design.md

Saf katman (bu bölüm) diske/DB'ye dokunmaz; taşıma katmanı aşağıda (Task 2).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from collections.abc import Callable
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.core.doctype.file.utils import get_content_hash
from frappe.utils import add_days, now_datetime
from frappe.utils.file_lock import LockTimeoutError
from frappe.utils.synchronization import filelock

from tradehub_core.media import archive, audit, naming, refs, retro_rename, seo_url
from tradehub_core.media.pipeline.image import dpi as dpi_mod
from tradehub_core.media.pipeline.image import normalize as normalize_mod

MIN_KENAR = 1000
MAX_KENAR = 2000
WEBP_QUALITY = 85
VARSAYILAN_DPI = 72  # kaynak DPI beyan etmiyorsa (normalize.DEFAULT_DPI_OUT ile aynı)
BEYAZ = (255, 255, 255)


class Atla(Exception):
	"""Dosya bu işlemin konusu değil — hata değil, gerekçeli atlama."""

	def __init__(self, reason: str):
		super().__init__(reason)
		self.reason = reason


def kare_boyutu(w: int, h: int) -> int | None:
	"""Hedef kare kenarı; dokunulmayacaksa `None` (spec §1)."""
	if w <= 0 or h <= 0:
		return None
	if w == h and MIN_KENAR <= w <= MAX_KENAR:
		return None
	return max(MIN_KENAR, min(MAX_KENAR, max(w, h)))


def kaynagi_ac(icerik: bytes):
	"""`(im, kaynak_bicim, kaynak_dpi)` — sRGB'ye taşınmış, EXIF yönü uygulanmış görsel.

	Kare (ürün) ve mağaza görseli dönüşümlerinin ORTAK girişi
	(`magaza_gorseli.webp_cevir`). Hareketli, okunamayan ya da piksel bombası
	dosya `Atla` ile reddedilir. Alfa KORUNUR (`normalize.to_srgb`); düzleme
	kararı çağıranındır.
	"""
	from PIL import Image, ImageOps, UnidentifiedImageError

	try:
		im = Image.open(io.BytesIO(icerik))
		im.load()
	except Image.DecompressionBombError as exc:
		raise Atla("too_large") from exc
	except (UnidentifiedImageError, OSError, ValueError) as exc:
		raise Atla("unreadable") from exc
	if getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1:
		raise Atla("animated")

	kaynak_bicim = (im.format or "").upper()
	# Künye: DPI ve ICC `exif_transpose`tan ÖNCE okunur — dönen yeni `Image`
	# `info`yu taşımayabilir (render.prepare_source ile aynı tuzak).
	kaynak_icc = im.info.get("icc_profile")
	kaynak_dpi = _kaynak_dpi(icerik)
	im = ImageOps.exif_transpose(im)
	# Gömülü profil sRGB değilse (Adobe RGB, Display P3, CMYK profili…) piksel
	# profil üzerinden sRGB'ye taşınır; çıktıya sRGB profili gömüleceği için
	# dönüşümsüz bırakmak renkleri yanlış etiketlemek olurdu.
	im, _ = normalize_mod.to_srgb(im, kaynak_icc, [])
	return im, kaynak_bicim, kaynak_dpi


def webp_yaz(im, kaynak_dpi: int, quality: int = WEBP_QUALITY) -> bytes:
	"""Künyeli WebP: EXIF çözünürlük etiketi (kaynak DPI, yoksa 72) + sRGB ICC.

	WebP DPI'ı yalnız EXIF çözünürlük etiketlerinde tutar (Pillow `dpi=`'yi yok
	sayar). EXIF'e çözünürlük dışında HİÇBİR etiket yazılmaz (GPS vb. yok).
	RGBA görselde alfa kanalı korunur (WebP alfa kayıpsız saklanır).
	"""
	kw: dict = {"exif": _cozunurluk_exif(kaynak_dpi or VARSAYILAN_DPI)}
	srgb = _srgb_icc()
	if srgb:
		kw["icc_profile"] = srgb
	buf = io.BytesIO()
	im.save(buf, "WEBP", quality=quality, method=4, **kw)
	return buf.getvalue()


def kareye_cevir(icerik: bytes) -> tuple[bytes, int]:
	"""`(webp, S)`. Görsel asla büyütülmez; beyaz S×S tuvalin ortasına konur.

	2026-09-30 (kullanıcı kararı — tüm ürün görselleri WebP): zaten kare ve
	1000–2000 aralığındaki görsel, biçimi WebP DEĞİLSE (jpg/png…) aynı ölçüde
	WebP'ye çevrilir — dolgu ya da ölçek değişmez. Yalnız kare+aralıkta+WebP
	olan görsel `already_square` ile atlanır.
	"""
	from PIL import Image

	im, kaynak_bicim, kaynak_dpi = kaynagi_ac(icerik)
	s = kare_boyutu(im.width, im.height)
	if s is None:
		if kaynak_bicim == "WEBP":
			raise Atla("already_square")
		# Kare ve aralıkta ama WebP değil: yalnız biçim değişir, S = mevcut kenar.
		s = im.width

	# Alfa (RGBA, LA, şeffaf P) beyaz zemine düzlenir; CMYK/L vb. RGB'ye.
	if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
		rgba = im.convert("RGBA")
		zemin = Image.new("RGB", rgba.size, BEYAZ)
		zemin.paste(rgba, mask=rgba.getchannel("A"))
		im = zemin
	elif im.mode != "RGB":
		im = im.convert("RGB")

	im.thumbnail((MAX_KENAR, MAX_KENAR))  # yalnız küçültür
	tuval = Image.new("RGB", (s, s), BEYAZ)
	tuval.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
	return webp_yaz(tuval, kaynak_dpi), s


def _kaynak_dpi(icerik: bytes) -> int:
	"""Kaynağın beyan ettiği DPI (konteyner ya da EXIF); yoksa 0."""
	try:
		bilgi = dpi_mod.read_dpi(icerik)
	except Exception:
		return 0
	if not bilgi.dpi:
		return 0
	try:
		return max(0, round(float(bilgi.dpi[0])))
	except (TypeError, ValueError):
		return 0


def _cozunurluk_exif(dpi: int) -> bytes:
	from fractions import Fraction

	from PIL import Image

	exif = Image.Exif()
	exif[dpi_mod.EXIF_X_RESOLUTION] = Fraction(int(dpi), 1)
	exif[dpi_mod.EXIF_Y_RESOLUTION] = Fraction(int(dpi), 1)
	exif[dpi_mod.EXIF_RESOLUTION_UNIT] = dpi_mod.RESOLUTION_UNIT_INCH
	return exif.tobytes()


def _srgb_icc() -> bytes | None:
	try:
		from PIL import ImageCms

		return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
	except Exception:
		return None


# ─── Taşıma katmanı ────────────────────────────────────────────────────────

URUN_KINDS = frozenset(
	{
		"listing_main",
		"listing_gallery",
		"variant_main",
		"variant_gallery",
		"cart_snapshot",
		"favorite_snapshot",
		"storefront",
	}
)
JOB_PREFIX = "kare-"
AUTO_JOB_KEY = "kare-auto"
_GORSEL_UZANTI = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".gif", ".bmp")


def _skip(reason: str, **extra) -> dict:
	return {
		"status": "skipped",
		"reason": reason,
		"target_url": None,
		"refs_updated": 0,
		"refs_skipped": 0,
		**extra,
	}


def urun_gorseli_mi(url: str) -> tuple[bool, bool]:
	"""`(urun_mu, siparis_var_mi)`. Ürün dışı canlı kaynak varsa ürün sayılmaz."""
	bulunan = refs.find(url)
	canli = [r for r in bulunan if not r["readonly"]]
	urun = (
		bool(canli)
		and all(r["kind"] in URUN_KINDS for r in canli)
		and any(
			r["kind"] in ("listing_main", "listing_gallery", "variant_main", "variant_gallery") for r in canli
		)
	)
	return urun, any(r["readonly"] for r in bulunan)


def _kare_olculu(icerik: bytes) -> tuple[bytes, tuple[int, int]]:
	veri, kenar = kareye_cevir(icerik)
	return veri, (kenar, kenar)


@dataclass(frozen=True)
class DonusumKurali:
	"""Bir görsel ailesinin master dönüşüm kuralı — taşıma katmanı ortaktır.

	Kare (ürün) ve mağaza görselleri AYNI taşıma yolunu kullanır: yeni
	içerik-adresli adres, `Media URL Redirect` 301, 30 gün arşiv, referans
	yeniden hedefleme ve geri alma. Değişen yalnız üç karar: dosya zaten uygun
	mu (yalnız başlıktan), bu dosya bu ailenin mi, ve piksel dönüşümü.

	Alanlar modül fonksiyonlarını ÇAĞRI anında çözen sarmalayıcılardır; testler
	`mock.patch.object(kare, "kareye_cevir")` gibi yamaları sürdürebilsin.
	"""

	ad: str
	hazir: Callable[[int, int, str], bool]
	hazir_nedeni: str
	kapsam: Callable[[str], tuple[bool, bool]]
	kapsam_disi_nedeni: str
	cevir: Callable[[bytes], tuple[bytes, tuple[int, int]]]


URUN_KURALI = DonusumKurali(
	ad="kare",
	hazir=lambda w, h, bicim: kare_boyutu(w, h) is None and bicim == "WEBP",
	hazir_nedeni="already_square",
	kapsam=lambda url: urun_gorseli_mi(url),
	kapsam_disi_nedeni="not_product",
	cevir=lambda icerik: _kare_olculu(icerik),
)


def _gorsel_url(url: str | None) -> bool:
	"""Ürün görseli adayı mı — path-geçişi segmentleri (I2, fix round 1) de burada elenir.

	`retro_rename.is_legacy_name` ile aynı savunma: `.`/`..` tam segment olarak
	reddedilir (cümle sonu nokta gibi gerçek dosya adı parçaları etkilenmez).
	Bu kontrol olmadan `../../etc/passwd.jpg` gibi bir adres `archive.exists()`'e
	kadar ilerleyip orada `frappe.ValidationError` fırlatıyordu — burada erkenden
	`not_image` ile atlanınca o hata yoluna hiç girilmiyor.
	"""
	ham = (url or "").split("?")[0]
	if any(seg in (".", "..") for seg in ham.split("/")):
		return False
	u = ham.lower()
	return (
		u.startswith(retro_rename.PUBLIC_PREFIX)
		and not u.startswith(retro_rename.MEDIA_PREFIX)
		and u.endswith(_GORSEL_UZANTI)
	)


def _listing_urls(listings: list[str] | None = None) -> list[str]:
	"""İlan görsel alanlarındaki distinct adresler; `listings` verilirse yalnız onlar."""
	f_ana = {"name": ["in", listings]} if listings else {}
	f_cocuk = {"parent": ["in", listings]} if listings else {}
	urls = set(frappe.get_all("Listing", filters=f_ana, pluck="primary_image"))
	urls |= set(frappe.get_all("Listing Image", filters=f_cocuk, pluck="image"))
	for row in frappe.get_all(
		"Listing Variant Item", filters=f_cocuk, fields=["variant_image", "variant_gallery"]
	):
		urls.add(row.variant_image)
		try:
			galeri = json.loads(row.variant_gallery or "[]")
		except (TypeError, ValueError):
			galeri = []
		urls |= {g for g in galeri if isinstance(g, str)}
	return sorted(u for u in urls if _gorsel_url(u))


def aday_urls() -> list[str]:
	"""Tüm ilanlardaki ürün görseli adresleri (toplu işin girdisi)."""
	return _listing_urls()


def _hata_kodu(exc: Exception) -> str:
	"""Beklenmedik hatayı kısa, panelde/audit'te okunur bir gerekçeye çevirir."""
	if isinstance(exc, LockTimeoutError):
		return "lock_timeout"
	if isinstance(exc, ValueError):
		# `naming._hashed_name`: yol/URL ayraçlı ya da izin verilmeyen uzantılı ad.
		return "invalid_name"
	if isinstance(exc, frappe.ValidationError):
		# `archive.*`/`retro_rename._disk_path`: beklenmeyen yol biçimi.
		return "invalid_path"
	return "exception"


def _kilit_adi(url: str) -> str:
	"""Adres başına dosya kilidi — dönüşüm ve geri alma AYNI adı kullanır (I2).

	`frappe.generate_hash(txt)` v15'te metni YOK SAYAR (rastgele) — kilit adı
	deterministik olmalı.
	"""
	return f"kare-{hashlib.sha1(url.encode()).hexdigest()[:16]}"


def _diskte(url: str | None) -> bool:
	if not url:
		return False
	try:
		return os.path.isfile(retro_rename._disk_path(url))
	except Exception:
		return False


def _baslik_boyutu(path: str) -> tuple[int, int, str] | None:
	"""Yalnız görsel başlığından `(w, h, biçim)`; okunamazsa `None` (tam yol karar verir)."""
	from PIL import Image

	try:
		with Image.open(path) as im:
			return im.width, im.height, (im.format or "").upper()
	except Exception:
		return None


def _json_liste(ham) -> list:
	try:
		deger = json.loads(ham or "[]")
	except (TypeError, ValueError):
		return []
	return deger if isinstance(deger, list) else []


def _iyilestir(url: str, row, *, dry_run: bool = False) -> dict:
	"""C1 (final review): 301'i olan eski adrese geri yazılmış canlı referansları onar.

	`refs.retarget` ham UPDATE — `modified` değişmiyor. Dönüşümden önce açılmış
	bir ürün formu kaydedilince eski adres (A) geri yazılıyor; A için 301 zaten
	var, bu yüzden dosya bir daha işlenmiyordu ve 90 gün sonra 301 silinince
	ilan kayıp dosyayı gösterecekti. Hedef diskte duruyorsa canlı referanslar
	hedefe çevrilir; değişiklikler satırın `ref_changes` provenance'ına eklenir
	ki geri alma bunları da eski hâline döndürsün.

	`dry_run=True` (prova) HİÇBİR ŞEY YAZMAZ: iyileştirilecek referans sayısı
	raporlanır, `refs.retarget`/provenance/cache/commit adımlarına girilmez.
	Eskiden bu dal prova bayrağını görmüyordu ve prova koşusu gerçek veriyi
	değiştiriyordu (2026-09-30 düzeltmesi).
	"""
	hedef = row.get("target_url")
	canli = [r for r in refs.find(url) if not r["readonly"]]
	if not canli or not _diskte(hedef):
		return _skip("redirect_exists")
	if dry_run:
		return _skip("healed", target_url=hedef, dry_run=True, refs_would_update=len(canli))
	sonuc = refs.retarget(url, hedef)
	if not sonuc["total"]:
		return _skip("redirect_exists", refs_skipped=len(sonuc["skipped"]))
	frappe.db.set_value(
		"Media URL Redirect",
		row.get("name"),
		"ref_changes",
		json.dumps(_json_liste(row.get("ref_changes")) + list(sonuc["changes"]), ensure_ascii=True),
		update_modified=False,
	)
	retro_rename._invalidate_url_caches(url, hedef)
	frappe.db.commit()
	return _skip(
		"healed",
		target_url=hedef,
		refs_updated=sonuc["total"],
		refs_skipped=len(sonuc["skipped"]),
	)


def normalize_one(
	url: str, job_key: str, expires_at, *, dry_run: bool = False, kural: DonusumKurali | None = None
) -> dict:
	"""Tek dosya: dönüşmüş içerik yeni adrese → File/ref → 301 → arşiv → eski diskten kalkar.

	`kural` verilmezse ürün (kare) kuralı; mağaza görselleri `magaza_gorseli.KURAL`.

	I2 (fix round 1): `normalize_one` toplu işin (`run_job`) İÇİNDEN döngüyle
	çağrılıyor — kilit zaman aşımı, adlandırma reddi (`naming._hashed_name`
	`ValueError`) ya da başka beklenmedik bir hata tek dosyada kalmalı, TÜM
	işi düşürmemeli. Bu yüzden `not_image` erken çıkışı dışındaki her şey tek
	bir `try` altında: hiçbir zaman `raise` etmez, en kötü ihtimalle
	`status: error` döner.
	"""
	from tradehub_core.media import av

	kural = kural or URUN_KURALI
	if not _gorsel_url(url):
		return _skip("not_image")
	try:
		# Aynı dosyayı ürün-kaydı işi ile toplu iş aynı anda işlemesin.
		# `frappe.generate_hash(txt)` v15'te metni YOK SAYAR (rastgele) — kilit adı deterministik olmalı.
		with filelock(_kilit_adi(url), timeout=120):
			yonlendirme = frappe.db.get_value(
				"Media URL Redirect",
				{"source_url": url},
				["name", "target_url", "ref_changes"],
				as_dict=True,
			)
			if yonlendirme:
				# Fix round 2: `source_url` UNIQUE — bu adres için 301 zaten var
				# (örn. dünkü retro-rename bu adı yönlendirdi ama dosya diskte
				# kaldı — "leftover" ya da "kept_for_orders" nedeniyle). Disk/DB
				# işine hiç girmeden atla; aksi hâlde `_uygula`'daki insert
				# `UniqueValidationError` fırlatıp dosyayı `error` sayıyordu
				# (ölçüldü: E2E round 2, iki gerçek dosya bu yüzden hata verdi).
				# C1 (final review): bayat bir form eski adresi geri yazmış
				# olabilir — canlı referans varsa hedefe iyileştirilir.
				return _iyilestir(url, yonlendirme, dry_run=dry_run)
			old_path = retro_rename._disk_path(url)
			if not os.path.isfile(old_path):
				return _skip("disk_missing")
			if av.in_quarantine(url) or av.in_hold(url):
				return _skip("quarantined")
			if archive.exists(url):
				# Optimize arşivi bu adla dolu: üzerine yazamayız, geri alma kırılır.
				return _skip("archived")
			# I5 (final review): her ürün kaydı bu yoldan geçiyor — zaten kare olan
			# dosya için `refs.find` (çok tablolu tarama) ve tam decode pahalı.
			# `Image.open` yalnız başlığı okur; `kare_boyutu` simetrik olduğu için
			# EXIF döndürmesi sonucu değiştirmez.
			# 2026-09-30: kare+aralıkta olsa da WebP olmayan dosya artık dönüşüme
			# girer (tüm ürün görselleri WebP); yalnız kare WebP atlanır.
			boyut = _baslik_boyutu(old_path)
			if boyut and kural.hazir(boyut[0], boyut[1], boyut[2]):
				return _skip(kural.hazir_nedeni)
			kapsamda, siparis = kural.kapsam(url)
			if not kapsamda:
				return _skip(kural.kapsam_disi_nedeni)
			with open(old_path, "rb") as f:
				eski = f.read()
			try:
				yeni_icerik, olcu = kural.cevir(eski)
			except Atla as a:
				return _skip(a.reason)
			stem = os.path.splitext(os.path.basename(url))[0]
			hashed = naming._hashed_name(f"{stem}.webp", yeni_icerik)
			new_url = f"{retro_rename.PUBLIC_PREFIX}{naming._shard(hashed)}/{hashed}"
			if dry_run:
				return {
					"status": "converted",
					"reason": "dry_run",
					"target_url": new_url,
					"refs_updated": 0,
					"refs_skipped": 0,
				}
			return _uygula(
				url, new_url, old_path, eski, yeni_icerik, job_key, expires_at, siparis, olcu, kural.ad
			)
	except Atla as a:
		# `kareye_cevir` kendi `try/except`iyle yakalıyor ama teorik olarak dışarı
		# taşarsa (ör. ileride eklenecek bir çağrı) burada da atlama sayılır.
		return _skip(a.reason)
	except Exception as exc:
		frappe.log_error(title=f"{kural.ad}: dosya işlenemedi {url}", message=frappe.get_traceback())
		return {
			"status": "error",
			"reason": _hata_kodu(exc),
			"target_url": None,
			"refs_updated": 0,
			"refs_skipped": 0,
		}


# `File` üzerindeki medya alanları: dönüşüm eski değerleri satır başına
# saklar, geri alma aynen yazar (minor, final review).
_FILE_META = (
	"th_optimized_at",
	"th_original_size",
	"th_media_state",
	"th_media_width",
	"th_media_height",
	# Görsel künyesi (DPI / renk uzayı / alfa) — içerik değişince yeniden ölçülür,
	# geri almada eski değerler aynen yazılır.
	"th_media_dpi",
	"th_media_colorspace",
	"th_media_alpha",
	"th_media_facts",
)
_ASSET_SUPERSEDED = "archived"  # öksüz taramasından muaf (usage.ORPHAN_EXEMPT_STATES)


def _file_meta_alanlari() -> list[str]:
	return [a for a in _FILE_META if frappe.db.has_column("File", a)]


def _yeni_kunye(icerik: bytes, meta_alanlari: list[str]) -> dict:
	"""Kare WebP baytlarından ölçülen DPI / renk uzayı / alfa (File alanları)."""
	from tradehub_core.media import image_facts
	from tradehub_core.media.pipeline.image import facts as facts_mod

	olcum = facts_mod.measure(icerik)
	durum = (
		{"status": image_facts.STATUS_OK, **olcum.to_dict()}
		if olcum.ok
		else {"status": image_facts.STATUS_UNREADABLE}
	)
	return {k: v for k, v in image_facts.file_values(durum).items() if k in meta_alanlari}


def _varliklari_emekli_et(adlar: list[str]) -> dict[str, list[str]]:
	"""I3 (final review): dönüşen `File`'ların `ready` Media Asset'lerini `archived` yap.

	`Media Asset.source_file` `File` docname'ine bağlı; `file_url` artık kare
	webp'i gösteriyor ama eski varlığın türevleri kare değil. Manifest
	(`media_manifest._varliklari_getir`) yalnız `ready` varlıkları okuyor, bu
	yüzden eski varlık vitrinden çekilir; yeni türevler `pipeline_bridge`
	bayrakları açıksa yeniden üretilir. Döndürülen `{file: [asset]}` geri alma
	için `file_names` JSON'unda saklanır.
	"""
	if not adlar:
		return {}
	cikti: dict[str, list[str]] = {}
	for v in frappe.get_all(
		"Media Asset",
		filters={"source_file": ["in", adlar], "state": "ready"},
		fields=["name", "source_file"],
	):
		_varligi_emekli_et(v.name)
		cikti.setdefault(v.source_file, []).append(v.name)
	return cikti


def _varligi_emekli_et(ad: str) -> None:
	"""Tek varlığı `archived` yap — I3 ve eski satır backfill'inin ortak yazımı."""
	frappe.db.set_value("Media Asset", ad, "state", _ASSET_SUPERSEDED, update_modified=False)


def _turevleri_tetikle(adlar: list[str]) -> None:
	"""Kare dosya için türev üretimini (bayraklar açıksa) kuyruğa al — best-effort."""
	from tradehub_core.media import pipeline_bridge

	for ad in adlar:
		try:
			pipeline_bridge.maybe_generate_renditions(frappe.get_doc("File", ad))
		except Exception:
			frappe.log_error(title=f"Kare: türev tetiklenemedi {ad}", message=frappe.get_traceback())


def _uygula(
	url, new_url, old_path, eski, yeni_icerik, job_key, expires_at, siparis, olcu=None, islem="kare"
) -> dict:
	"""`olcu`: yeni içeriğin `(genişlik, yükseklik)`ı; kare için `(S, S)`.

	`islem` denetim kaydındaki `operation` adıdır (`kare` / `magaza`).
	"""
	if isinstance(olcu, int):
		olcu = (olcu, olcu)
	new_path = retro_rename._disk_path(new_url)
	yeni_yazildi = False
	try:
		frappe.create_folder(os.path.dirname(new_path))
		if not os.path.isfile(new_path):
			with open(new_path, "wb") as f:
				f.write(yeni_icerik)
			yeni_yazildi = True
		archive.store(url, eski)
	except OSError:
		frappe.log_error(title=f"Kare: disk yazılamadı {url}", message=frappe.get_traceback())
		if yeni_yazildi:
			try:
				os.remove(new_path)
			except OSError:
				frappe.log_error(title=f"Kare: yeni dosya geri silinemedi {new_url}")
		# `archive.exists(url)` yukarıda False idi — varsa yarım kayıt bizimdir.
		try:
			archive.drop(url)
		except Exception:
			frappe.log_error(title=f"Kare: arşiv kaydı düşürülemedi {url}", message=frappe.get_traceback())
		return {
			"status": "error",
			"reason": "disk_write",
			"target_url": new_url,
			"refs_updated": 0,
			"refs_skipped": 0,
		}
	try:
		# I3 (fix round 1): dönüşüm içeriği değiştiriyor — `content_hash` YENİ
		# baytları yansıtmalı (aksi hâlde Frappe'nin kendi dedup/entegrite
		# kontrolleri eski içeriğin izini taşımaya devam eder) ve görünen ad
		# `.webp` uzantısına geçmeli (uzantı hâlâ `.jpg` ama disk baytları webp
		# olunca indirilen dosya bozuk açılır). Eski değerler `file_names`
		# JSON'unda satır başına saklanır — rollback bunları aynen geri yazar;
		# bu alan yalnız kare.py'nin kendi satırları için (job_key `kare-*`)
		# üretiliyor, retro_rename.py'nin düz isim listesiyle karışmıyor.
		meta_alanlari = _file_meta_alanlari()
		eski_satirlar = frappe.get_all(
			"File",
			filters={"file_url": url},
			fields=["name", "file_name", "content_hash", *meta_alanlari],
		)
		yeni_hash = get_content_hash(yeni_icerik)
		kunye = _yeni_kunye(yeni_icerik, meta_alanlari)
		for satir in eski_satirlar:
			stem_ad = os.path.splitext(satir.file_name or "")[0]
			degerler = {
				"file_url": new_url,
				"file_size": len(yeni_icerik),
				"seo_code": None,
				"content_hash": yeni_hash,
				"file_name": f"{stem_ad}.webp",
			}
			# Optimize damgaları eski içeriği anlatıyor; yeni webp optimize edilmedi.
			if "th_optimized_at" in meta_alanlari:
				degerler["th_optimized_at"] = None
			if "th_original_size" in meta_alanlari:
				degerler["th_original_size"] = 0  # Int, NOT NULL
			if "th_media_state" in meta_alanlari and satir.get("th_media_state") == "Archived":
				degerler["th_media_state"] = "Active"
			if olcu and "th_media_width" in meta_alanlari:
				degerler["th_media_width"] = olcu[0]
			if olcu and "th_media_height" in meta_alanlari:
				degerler["th_media_height"] = olcu[1]
			degerler.update(kunye)
			frappe.db.set_value("File", satir.name, degerler, update_modified=False)
		adlar = [s.name for s in eski_satirlar]
		emekli = _varliklari_emekli_et(adlar)
		ref_result = refs.retarget(url, new_url)
		try:
			seo_url.assign_code(new_url)
		except Exception:
			frappe.log_error(title=f"SEO kodu atanamadı: {new_url}", message=frappe.get_traceback())
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": url,
				"target_url": new_url,
				"job_key": job_key,
				"expires_at": expires_at or add_days(now_datetime(), retro_rename.REDIRECT_TTL_DAYS),
				"file_rows": len(adlar),
				"file_names": json.dumps(
					[
						{
							"name": s.name,
							"old_file_name": s.file_name,
							"old_content_hash": s.content_hash,
							"old_meta": {a: s.get(a) for a in meta_alanlari},
							"assets": emekli.get(s.name, []),
						}
						for s in eski_satirlar
					],
					default=str,
				),
				"ref_changes": json.dumps(ref_result.get("changes") or [], ensure_ascii=True),
			}
		).insert(ignore_permissions=True)  # sistem işi: çağıran System Manager kapısı ya da kuyruk
		retro_rename._invalidate_url_caches(url, new_url)
		# `enqueue_after_commit` — iş ancak aşağıdaki commit'le kuyruğa girer.
		_turevleri_tetikle(adlar)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		if yeni_yazildi:
			try:
				os.remove(new_path)
			except OSError:
				pass
		archive.drop(url)
		frappe.log_error(title=f"Kare başarısız {url}", message=frappe.get_traceback())
		return {
			"status": "error",
			"reason": "exception",
			"target_url": new_url,
			"refs_updated": 0,
			"refs_skipped": 0,
		}

	reason = ""
	if siparis:
		# Sipariş geçmişi eski adresi gösteriyor: dosya yerinde kalır (spec Global Constraints).
		reason = "kept_for_orders"
	else:
		try:
			os.remove(old_path)
		except OSError:
			reason = "leftover"
			frappe.log_error(title=f"Kare: eski dosya silinemedi {url}", message=frappe.get_traceback())
	retro_rename._clear_404_cache()
	audit.log_media_event(
		action=audit.ACTION_RETRO_RENAME,
		file_url=new_url,
		context={
			"operation": islem,
			"old_url": url,
			"job_key": job_key,
			"refs_updated": ref_result["total"],
			"kept": bool(siparis),
		},
	)
	return {
		"status": "converted",
		"reason": reason,
		"target_url": new_url,
		"refs_updated": ref_result["total"],
		"refs_skipped": len(ref_result["skipped"]),
	}


def rollback_one(row: frappe._dict) -> dict:
	"""Arşivdeki orijinali geri koy, File/ref'leri eski adrese döndür, 301'i sil.

	I2 (final review): dönüşümle AYNI adres kilidini (`_kilit_adi(source_url)`)
	ve hedef adresin kilidini alır — geri alma sürerken bir ürün kaydının
	tetiklediği otomatik iş aynı dosyayı yeniden dönüştüremez. Otomatik tetik
	(`normalize_listing`) ayrıca ortak medya iş kilidi doluyken hiç çalışmaz.
	Yine de geri almadan ÖNCE `site_config.json`'da `urun_gorseli_kare_kapali`
	açılmalı: aksi hâlde geri alma bittikten sonraki ilk ürün kaydı görseli
	yeniden kareye çevirir.
	"""
	try:
		with (
			filelock(_kilit_adi(row.source_url), timeout=120),
			filelock(_kilit_adi(row.target_url), timeout=120),
		):
			return _rollback_one_kilitli(row)
	except LockTimeoutError:
		return {"ok": False, "reason": "lock_timeout", "refs_updated": 0, "refs_skipped": 0}


def _asset_durumlarini_geri_al(kayitlar: list[dict], geri: list[str]) -> None:
	"""I3: dönüşümün emekliye ayırdığı varlıkları `ready`'ye döndür; webp için
	sonradan üretilmiş `ready` varlıkları emekliye ayır (manifest aynı `File`
	için iki `ready` varlık görmesin)."""
	if not geri or not any("assets" in k for k in kayitlar):
		# Final review öncesi satırlar varlık durumunu hiç değiştirmedi — dokunma.
		return
	bizim = {a for k in kayitlar if k.get("name") in geri for a in (k.get("assets") or [])}
	for v in frappe.get_all(
		"Media Asset",
		filters={"source_file": ["in", geri]},
		fields=["name", "state"],
	):
		if v.name in bizim:
			if v.state == _ASSET_SUPERSEDED:
				frappe.db.set_value("Media Asset", v.name, "state", "ready", update_modified=False)
		elif v.state == "ready":
			frappe.db.set_value("Media Asset", v.name, "state", _ASSET_SUPERSEDED, update_modified=False)


def _rollback_one_kilitli(row: frappe._dict) -> dict:
	basarisiz = {"ok": False, "reason": "rollback_failed", "refs_updated": 0, "refs_skipped": 0}
	old_path = retro_rename._disk_path(row.source_url)
	new_path = retro_rename._disk_path(row.target_url)
	yazildi = False
	try:
		if not os.path.isfile(old_path):
			eski = archive.read(row.source_url)
			frappe.create_folder(os.path.dirname(old_path))
			with open(old_path, "wb") as f:
				f.write(eski)
			yazildi = True
	except Exception:
		frappe.log_error(title=f"Kare geri alma: arşiv yok {row.source_url}", message=frappe.get_traceback())
		return {**basarisiz, "reason": "archive_missing"}
	try:
		# I3 (fix round 1): `file_names` artık düz ad listesi değil, satır başına
		# `{"name", "old_file_name", "old_content_hash", "old_meta", "assets"}` —
		# `_uygula`'nın yazdığı biçim. Bu alanı yalnız kare.py üretiyor/okuyor
		# (job_key `kare-*`); `old_meta`/`assets` final review'da eklendi, eski
		# satırlarda yoksa atlanır.
		kayitlar = json.loads(row.file_names or "[]")
		adaylar = [k["name"] for k in kayitlar]
		eski_meta = {k["name"]: k for k in kayitlar}
		geri = frappe.get_all(
			"File", filters={"file_url": row.target_url, "name": ["in", adaylar or [""]]}, pluck="name"
		)
		boyut = os.path.getsize(old_path)
		meta_alanlari = set(_file_meta_alanlari())
		for ad in geri:
			meta = eski_meta.get(ad) or {}
			degerler = {"file_url": row.source_url, "file_size": boyut, "seo_code": None}
			if meta.get("old_file_name"):
				degerler["file_name"] = meta["old_file_name"]
			if meta.get("old_content_hash"):
				degerler["content_hash"] = meta["old_content_hash"]
			for alan, deger in (meta.get("old_meta") or {}).items():
				if alan in meta_alanlari:
					degerler[alan] = deger
			frappe.db.set_value("File", ad, degerler, update_modified=False)
		_asset_durumlarini_geri_al(kayitlar, geri)
		ref_result = refs.restore_retarget_changes(json.loads(row.ref_changes or "[]"))
		frappe.delete_doc("Media URL Redirect", row.name, ignore_permissions=True, force=True)
		retro_rename._invalidate_url_caches(row.source_url, row.target_url)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		if yazildi:
			try:
				os.remove(old_path)
			except OSError:
				frappe.log_error(title=f"Kare geri alma: geri konan dosya silinemedi {row.source_url}")
		frappe.log_error(title=f"Kare geri alma başarısız {row.source_url}", message=frappe.get_traceback())
		return {**basarisiz, "reason": "db_restore"}

	# I4 (final review): dönüşüm `seo_code`'u boşaltmıştı; eski adrese dönen
	# satırlar okunur SEO adresini yeniden alsın (`_uygula` ile aynı desen).
	try:
		seo_url.assign_code(row.source_url)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title=f"SEO kodu atanamadı: {row.source_url}", message=frappe.get_traceback())

	kalan = frappe.db.count("File", {"file_url": row.target_url})
	paylasan = frappe.db.count("Media URL Redirect", {"target_url": row.target_url})
	# I1 (fix round 1): dönüşümden SONRA yeni adrese bağlanmış bir referans olabilir
	# (yeni bir sipariş satırı, sepet/favori anlık görüntüsü — hiçbiri `ref_changes`
	# provenance'ında YOK çünkü kare dönüşümünden sonra oluşturuldu). `refs.find`
	# TÜM referansları (readonly dahil) döner; biri bile varsa webp silinirse o
	# referans kırık kalır.
	kullanimda = bool(refs.find(row.target_url))
	reason = "target_kept_in_use" if kullanimda else ""
	if not kullanimda and not kalan and not paylasan and os.path.isfile(new_path):
		try:
			os.remove(new_path)
		except OSError:
			frappe.log_error(title=f"Kare geri alma: hedef silinemedi {row.target_url}")
	archive.drop(row.source_url)
	retro_rename._clear_404_cache()
	return {
		"ok": True,
		"reason": reason,
		"refs_updated": ref_result["total"],
		"refs_skipped": len(ref_result["skipped"]),
	}


def run_job(job_key: str, dry_run: int = 0, batch_size: int = retro_rename.DEFAULT_BATCH) -> None:
	"""Toplu iş (panel). Kilit ve ilerleme retro-rename ile ORTAK: ikisi aynı anda çalışmaz."""
	if not retro_rename.acquire_or_refresh_active(job_key):
		durum = retro_rename._new_state(0, "kare", bool(dry_run))
		durum.update(state="error", message=_("Başka bir medya işi aktif; bu iş çalıştırılmadı."))
		retro_rename._write_progress(job_key, durum)
		return
	try:
		toplu_donustur(job_key, dry_run=bool(dry_run), batch_size=batch_size)
	except Exception:
		durum = retro_rename.read_progress(job_key)
		durum.update(state="error", message=_("İşlem tamamlanamadı."))
		retro_rename._write_progress(job_key, durum)
		frappe.log_error(title=f"Kare işi başarısız: {job_key}", message=frappe.get_traceback())
	finally:
		retro_rename.release_active(job_key)
		frappe.cache.delete_value(retro_rename._stop_key(job_key))
		retro_rename._clear_404_cache()


def toplu_donustur(
	job_key: str,
	*,
	dry_run: bool = False,
	batch_size: int = retro_rename.DEFAULT_BATCH,
	urls: list[str] | None = None,
	kural: DonusumKurali | None = None,
	satir_anahtari: str | None = None,
) -> dict:
	"""Toplu kare dönüşümünün gövdesi — kilit YÖNETMEZ, çağıran ortak kilidi tutar.

	`run_job` (Kare kartı) ve `urun_gorseli_optimize` (tek düğme) aynı gövdeyi
	kullanır. İlerleme `retro_rename.progress_key(job_key)`'e yazılır; heartbeat
	ortak kilidi `job_key` adına tazeler, yani çağıran kilidi AYNI anahtarla
	almış olmalı. Beklenmedik hata yukarı taşar (çağıran `error` yazar).

	`urls`/`kural`: başka görsel ailesi (mağaza görselleri) aynı gövdeyle koşar.
	`satir_anahtari`: 301 satırlarının `job_key` etiketi (verilmezse `job_key`) —
	tek düğme mağaza adımını ayrı geri alabilsin diye; kilit/durdurma/ilerleme
	yine `job_key` üzerindendir.
	"""
	if urls is None:
		urls = aday_urls()
	ek = {"kural": kural} if kural is not None else {}
	expires_at = add_days(now_datetime(), retro_rename.REDIRECT_TTL_DAYS)
	durum = retro_rename._new_state(len(urls), (kural or URUN_KURALI).ad, bool(dry_run), expires_at)
	retro_rename._write_progress(job_key, durum)
	batch = max(1, int(batch_size or retro_rename.DEFAULT_BATCH))
	for i, url in enumerate(urls):
		if i % batch == 0:
			if retro_rename._stop_requested(job_key):
				durum.update(state="stopped", message=_("Operatör durdurdu."))
				break
			if durum["processed"] and durum["errors"] / durum["processed"] > retro_rename.ERROR_RATE_STOP:
				durum.update(state="partial", message=_("Hata oranı eşiği aşıldı; iş durduruldu."))
				break
		out = normalize_one(url, satir_anahtari or job_key, expires_at, dry_run=bool(dry_run), **ek)
		durum["processed"] += 1
		durum["refs_updated"] += int(out.get("refs_updated") or 0)
		durum["refs_skipped"] += int(out.get("refs_skipped") or 0)
		if out["status"] == "converted":
			durum["renamed"] += 1
			if out["reason"] in ("kept_for_orders", "leftover"):
				retro_rename._bump_reason(durum, out["reason"])
		elif out["status"] == "skipped":
			durum["skipped"] += 1
			retro_rename._bump_reason(durum, out["reason"])
		else:
			durum["errors"] += 1
			retro_rename._bump_reason(durum, out["reason"])
		if durum["processed"] % 25 == 0:
			retro_rename._heartbeat(job_key, durum)
	else:
		durum["state"] = "partial" if durum["errors"] else "completed"
	retro_rename._write_progress(job_key, durum)
	return durum


def run_rollback(job_key: str, rollback_key: str) -> None:
	"""`job_key` ile yazılmış kare satırlarını ters oynatır.

	Geri almadan ÖNCE `site_config.json`'da `urun_gorseli_kare_kapali` açılmalı
	(bkz. `rollback_one`). I7 (final review): beklenmedik hata işi "running"
	bırakmaz; refs toplamı ve audit retro-rename'in `run_rollback`'iyle aynı.
	"""
	rows = frappe.get_all(
		"Media URL Redirect",
		filters={"job_key": job_key},
		fields=["name", "source_url", "target_url", "file_names", "ref_changes"],
		order_by="creation desc",
	)
	durum = retro_rename._new_state(len(rows), "rollback", False)
	retro_rename._write_progress(rollback_key, durum)
	if not retro_rename.acquire_or_refresh_active(rollback_key):
		durum.update(state="error", message=_("Başka bir medya işi aktif; geri alma çalıştırılmadı."))
		retro_rename._write_progress(rollback_key, durum)
		return
	try:
		for row in rows:
			out = rollback_one(row)
			durum["processed"] += 1
			durum["renamed" if out["ok"] else "errors"] += 1
			durum["refs_updated"] += int(out.get("refs_updated") or 0)
			durum["refs_skipped"] += int(out.get("refs_skipped") or 0)
			if not out["ok"]:
				retro_rename._bump_reason(durum, out.get("reason") or "rollback_failed")
			if durum["processed"] % 25 == 0:
				retro_rename._heartbeat(rollback_key, durum)
		durum["state"] = "partial" if durum["errors"] else "completed"
	except Exception:
		durum["state"] = "error"
		durum["message"] = _("Geri alma tamamlanamadı.")
		frappe.log_error(title=f"Kare geri alma işi başarısız: {job_key}", message=frappe.get_traceback())
	finally:
		retro_rename.release_active(rollback_key)
		retro_rename._clear_404_cache()
	retro_rename._write_progress(rollback_key, durum)
	audit.log_media_batch(
		action=audit.ACTION_RETRO_ROLLBACK,
		job_key=job_key,
		summary={**durum, "operation": "kare", "rollback_key": rollback_key},
	)


# ─── Tek seferlik backfill: I3 öncesi satırlar ─────────────────────────────


def _neden(sayac: dict, reason: str) -> None:
	sayac["skipped_reasons"][reason] = sayac["skipped_reasons"].get(reason, 0) + 1


def _kayit_adi(kayit) -> str | None:
	"""`file_names` girdisi: ilk sürüm düz ad (str), sonraki sürümler dict."""
	if isinstance(kayit, str):
		return kayit
	if isinstance(kayit, dict) and isinstance(kayit.get("name"), str):
		return kayit["name"]
	return None


def _i3_oncesi_mi(kayitlar: list) -> bool:
	"""I3'ten önce yazılmış satır: hiçbir girdide `assets` anahtarı yok."""
	return not any(isinstance(k, dict) and "assets" in k for k in kayitlar)


def _disk_sha256(url: str) -> str | None:
	"""Hedef webp'in diskteki GERÇEK baytlarının tam sha256'sı (adına güvenmeden)."""
	try:
		path = retro_rename._disk_path(url)
	except Exception:
		return None
	if not os.path.isfile(path):
		return None
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for parca in iter(lambda: f.read(1 << 20), b""):
			h.update(parca)
	return h.hexdigest()


def _varlik_bayat_mi(varlik, webp_sha: str, webp_boyut: tuple[int, int] | None) -> bool | None:
	"""Varlık ESKİ içerik için mi üretilmiş? `None` = karar verilemedi (dokunma).

	Birincil ölçüt `Media Asset.content_sha256` — saklanan baytların
	sha256 kısaltması (`pipeline_bridge.content_fingerprint`, 32 hane; eski
	kayıtlarda 64 hane olabilir, önek karşılaştırması ikisini de kapsar).
	Hash yoksa etkin `Media Version` boyutu webp'in boyutuyla kıyaslanır.
	"""
	hash_ = (varlik.content_sha256 or "").strip().lower()
	if hash_:
		return not webp_sha.startswith(hash_)
	if not varlik.active_version or not webp_boyut:
		return None
	surum = frappe.db.get_value("Media Version", varlik.active_version, ["width", "height"], as_dict=True)
	if not surum or not surum.width or not surum.height:
		return None
	return (surum.width, surum.height) != tuple(webp_boyut)


def _bayat_varliklar(adlar: list[str], hedef_url: str, sayac: dict) -> dict[str, list[str]] | None:
	"""`{file: [bayat varlık]}`; hedef diskte yoksa `None` (satır atlanır)."""
	webp_sha = _disk_sha256(hedef_url)
	if not webp_sha:
		return None
	baslik = _baslik_boyutu(retro_rename._disk_path(hedef_url))
	webp_boyut = baslik[:2] if baslik else None
	cikti: dict[str, list[str]] = {}
	for v in frappe.get_all(
		"Media Asset",
		filters={"source_file": ["in", adlar], "state": "ready"},
		fields=["name", "source_file", "content_sha256", "active_version"],
	):
		karar = _varlik_bayat_mi(v, webp_sha, webp_boyut)
		if karar is None:
			_neden(sayac, "asset_undeterminable")
		elif karar:
			cikti.setdefault(v.source_file, []).append(v.name)
		else:
			sayac["fresh_assets_kept"] += 1
	return cikti


def _backfill_satir(row, kayitlar: list, sayac: dict, dry_run: bool) -> None:
	adlar = [a for a in (_kayit_adi(k) for k in kayitlar) if a]
	hedefte = frappe.get_all(
		"File", filters={"file_url": row.target_url, "name": ["in", adlar or [""]]}, pluck="name"
	)
	if not hedefte:
		_neden(sayac, "file_not_at_target")
		return
	bayat = _bayat_varliklar(hedefte, row.target_url, sayac)
	if bayat is None:
		_neden(sayac, "target_missing")
		return
	sayac["files"] += len(hedefte)
	sayac["stale_assets_found"] += sum(len(v) for v in bayat.values())
	if dry_run:
		return
	for varliklar in bayat.values():
		for ad in varliklar:
			_varligi_emekli_et(ad)
			sayac["archived"] += 1
	# Rollback'in okuduğu biçim: düz ad listesi de dict'e çevrilir (eski
	# `_rollback_one_kilitli` str girdide `k["name"]`'de patlıyordu).
	yeni = [
		{**(k if isinstance(k, dict) else {"name": k}), "assets": bayat.get(_kayit_adi(k), [])}
		for k in kayitlar
		if _kayit_adi(k)
	]
	frappe.db.set_value(
		"Media URL Redirect", row.name, "file_names", json.dumps(yeni, default=str), update_modified=False
	)
	retro_rename._invalidate_url_caches(row.source_url, row.target_url)
	_turevleri_tetikle(hedefte)
	sayac["renditions_triggered"] += len(hedefte)
	frappe.db.commit()


def _rendition_bayraklari() -> dict:
	from tradehub_core.media import pipeline_flags

	try:
		return {
			"rendition_on_upload": pipeline_flags.is_enabled("rendition_on_upload"),
			"product_image_slot": pipeline_flags.is_slot_enabled("product.image"),
			"rollout_percent": pipeline_flags.rollout_percent(),
		}
	except Exception:
		frappe.log_error(title="Kare backfill: bayrak okunamadı", message=frappe.get_traceback())
		return {"error": True}


def backfill_eski_varliklar(
	dry_run: int = 1, job_key: str | None = None, *, ortak_kilit_bende: bool = False
) -> dict:
	"""Tek seferlik: I3 öncesi `kare-*` satırlarının bayat `ready` varlıklarını emekli et.

	I3'ten önce dönüşen dosyaların Media Asset'leri hâlâ `ready` ve ESKİ
	(kare olmayan) içeriği anlatıyor. Bu yordam `_uygula`'nın I3 adımını
	geriye dönük uygular: yalnız webp'e UYMAYAN varlıkları arşivler, adlarını
	satırın `file_names` JSON'una `assets` olarak yazar (geri alma onları
	geri getirir) ve türev üretimini tetikler. İdempotent: işlenen satır
	`assets` anahtarını kazanır ve sonraki koşuda atlanır. `job_key` testte
	kapsamı daraltır; verilmezse tüm `kare-*` satırları.

	`ortak_kilit_bende`: çağıran (tek düğme orkestratörü) ortak medya kilidini
	zaten kendisi tutuyor — kilit doluluğu bu durumda "başka iş var" demek değil.
	"""
	dry = bool(int(dry_run))
	sayac = {
		"dry_run": dry,
		"rows_checked": 0,
		"files": 0,
		"stale_assets_found": 0,
		"fresh_assets_kept": 0,
		"archived": 0,
		"renditions_triggered": 0,
		"skipped_reasons": {},
		"flags": _rendition_bayraklari(),
	}
	if not ortak_kilit_bende and _medya_isi_aktif():
		_neden(sayac, "media_job_active")
		return sayac
	filtre = {"job_key": job_key} if job_key else {"job_key": ["like", f"{JOB_PREFIX}%"]}
	for row in frappe.get_all(
		"Media URL Redirect",
		filters=filtre,
		fields=["name", "source_url", "target_url", "file_names"],
		order_by="creation asc",
	):
		kayitlar = _json_liste(row.file_names)
		if not _i3_oncesi_mi(kayitlar):
			_neden(sayac, "already_new_format")
			continue
		sayac["rows_checked"] += 1
		if not kayitlar:
			_neden(sayac, "no_file_names")
			continue
		try:
			with filelock(_kilit_adi(row.source_url), timeout=30):
				_backfill_satir(row, kayitlar, sayac, dry)
		except Exception as exc:
			frappe.db.rollback()
			_neden(sayac, f"error_{_hata_kodu(exc)}")
			frappe.log_error(title=f"Kare backfill başarısız {row.name}", message=frappe.get_traceback())
	return sayac


def _medya_isi_aktif() -> bool:
	"""Ortak medya iş kilidi (retro-rename/kare toplu işi ya da geri alma) dolu mu."""
	try:
		return bool(frappe.cache.exists(retro_rename.ACTIVE_KEY))
	except Exception:
		return False


def normalize_listing(listing: str) -> dict:
	"""Tek ilanın görselleri (ürün kaydı kancasından kuyrukla çağrılır).

	I2 (final review): ortak medya iş kilidi doluyken (toplu kare/retro işi ya
	da geri alma sürüyor) otomatik yol hiç çalışmaz — geri almanın hemen
	arkasından aynı dosyayı yeniden dönüştürmesin. Frappe v15 `enqueue`
	gecikmeli kuyruklamayı desteklemediği için yeniden kuyruklanmaz; atlanır
	ve loglanır (bir sonraki ürün kaydı ya da toplu iş yakalar).
	"""
	ozet = {"converted": 0, "skipped": 0, "errors": 0}
	if _medya_isi_aktif():
		frappe.logger("kare").info(f"kare: medya işi aktif, {listing} otomatik kareleme atlandı")
		ozet["skipped_active_job"] = 1
		return ozet
	for url in _listing_urls([listing]):
		out = normalize_one(url, AUTO_JOB_KEY, None)
		ozet[{"converted": "converted", "skipped": "skipped"}.get(out["status"], "errors")] += 1
	return ozet


def _enqueue_listing(listing: str, job_id: str | None = None) -> None:
	"""`normalize_listing`'i ilan başına tek iş olarak kuyruğa al — tek yer.

	Ürün kaydı `kare-listing-<ilan>` ile deduplicate ediliyor. I6 (final
	review): AV bekletmesinden çıkış kendi `job_id`'sini verir — RQ
	`deduplicate` çalışan (STARTED) işi de "var" sayıyor; kayıt işi o anda
	çalışıyorsa (ve dosya bekletmede olduğu için atladıysa) bırakma tetiği
	sessizce düşüyordu.
	"""
	frappe.enqueue(
		"tradehub_core.media.kare.normalize_listing",
		queue="default",
		timeout=600,
		enqueue_after_commit=True,
		job_id=job_id or f"kare-listing-{listing}",
		deduplicate=True,
		listing=listing,
	)


def _listings_for_url(url: str) -> list[str]:
	"""Bu adresi ürün görseli olarak kullanan İlan'lar — ana, galeri, varyant."""
	if not _gorsel_url(url):
		return []
	ilanlar = set(frappe.get_all("Listing", filters={"primary_image": url}, pluck="name"))
	ilanlar |= set(frappe.get_all("Listing Image", filters={"image": url}, pluck="parent"))
	ilanlar |= set(frappe.get_all("Listing Variant Item", filters={"variant_image": url}, pluck="parent"))
	for row in frappe.get_all(
		"Listing Variant Item",
		filters={"variant_gallery": ["like", f"%{url}%"]},
		fields=["parent", "variant_gallery"],
	):
		try:
			galeri = json.loads(row.variant_gallery or "[]")
		except (TypeError, ValueError):
			continue
		if url in galeri:
			ilanlar.add(row.parent)
	return sorted(ilanlar)


def enqueue_for_released_url(url: str) -> int:
	"""AV bekletmesinden çıkan dosya bir ürün görseliyse kareleme kuyruğa (fix round 2).

	`av.release_hold` tek kapı: hem temiz tarama hem `fail_closed=False`
	altında taranamayan dosyanın geri konduğu yol buradan geçiyor. `on_listing_
	update` kayıt ANINDA tetikleniyor ama dosya o an hâlâ bekletmede olabiliyor
	(tarama ayrı bir kuyruk işi, iki işin sırası garanti değil) — `normalize_
	one` o anda `quarantined` diyip atlıyor ve dosya bir daha asla kuyruğa
	girmiyordu (ölçüldü: LST-04593, canlı E2E). Bu fonksiyon boşluğu, dosyanın
	canlıya DÖNDÜĞÜ an kapatıyor.

	Aynı kill-switch/`in_test`/`in_migrate` kapıları `on_listing_update` ile
	birebir; `in_import` burada da KASITLI OLARAK atlanmıyor (fix round 1 ile
	aynı gerekçe). Sonsuz döngü riski yok: `normalize_one` dosyayı YENİ bir
	adrese taşıyor, o yeni adres için `File.after_insert` hiç tetiklenmiyor
	(mevcut `File` satırı güncelleniyor, yeni kayıt açılmıyor), dolayısıyla
	yeni bir AV taraması / bekletme döngüsü başlamıyor.
	"""
	if frappe.conf.get("urun_gorseli_kare_kapali") or frappe.flags.in_test or frappe.flags.in_migrate:
		return 0
	ilanlar = _listings_for_url(url)
	url_izi = hashlib.sha1(url.encode()).hexdigest()[:10]
	for ilan in ilanlar:
		_enqueue_listing(ilan, job_id=f"kare-release-{ilan}-{url_izi}")
	# Mağaza görseli (logo/kapak/vitrin) aynı boşluğa düşer; kuralı `magaza_gorseli`nde.
	from tradehub_core.media import magaza_gorseli

	return len(ilanlar) + magaza_gorseli.enqueue_for_released_url(url)


def on_listing_update(doc, method=None) -> None:
	"""Ürün kaydı: görsel varsa kareleme kuyruğa (commit sonrası, ilan başına tek iş).

	Kill switch: `site_config.json`'da `urun_gorseli_kare_kapali` açıksa hiç
	çalışmaz. Test izolasyonu: test runner içinde (`frappe.flags.in_test`)
	gerçek kuyruğa atmaz — `test_media_kare_job.py`'deki `_Base` yardımcıları
	bu kancanın tetiklediği İlan'ları kapsıyor, aksi hâlde her test gerçek bir
	iş kuyruklar. `frappe.flags.in_import` KASITLI OLARAK atlanmıyor (fix round
	1): toplu içe aktarılan ürünlerin görselleri de kareye çevrilmeli — "her
	ürün görseli" gereksinimi import kaynaklı ilanları da kapsıyor.
	"""
	if frappe.conf.get("urun_gorseli_kare_kapali"):
		return
	if frappe.flags.in_test or frappe.flags.in_migrate:
		return
	gorseller = [doc.get("primary_image")]
	gorseller += [r.get("image") for r in doc.get("listing_images") or []]
	for varyant in doc.get("variant_items") or []:
		gorseller.append(varyant.get("variant_image"))
		try:
			gorseller += json.loads(varyant.get("variant_gallery") or "[]")
		except (TypeError, ValueError):
			pass
	if not any(_gorsel_url(u) for u in gorseller if isinstance(u, str)):
		return
	_enqueue_listing(doc.name)


def yonlendirilmis_gorselleri_esle(doc, method=None) -> None:
	"""`Listing.validate`: 301'i olan eski görsel adresini hedefine çevir (C1, final review).

	Dönüşümden önce açılmış bir ürün formu kaydedildiğinde eski adres (A) geri
	yazılır. Süresi dolmamış bir `Media URL Redirect` A'yı gösteriyorsa değer
	kayıt ANINDA hedefe çevrilir — 90 gün sonra 301 silindiğinde ilan kayıp
	dosyayı göstermesin. Ana görsel, galeri, varyant görseli ve varyant galerisi
	(JSON) kapsanır. Kill switch'ten bağımsızdır: yönlendirmeyi izlemek her
	zaman doğru.
	"""
	varyantlar = doc.get("variant_items") or []
	galeriler = {}
	adaylar = {doc.get("primary_image")}
	adaylar |= {r.get("image") for r in doc.get("listing_images") or []}
	for v in varyantlar:
		adaylar.add(v.get("variant_image"))
		ham = v.get("variant_gallery")
		if ham:
			galeri = _json_liste(ham)
			galeriler[id(v)] = galeri
			adaylar |= {g for g in galeri if isinstance(g, str)}
	adaylar = [u for u in adaylar if isinstance(u, str) and u.startswith(retro_rename.PUBLIC_PREFIX)]
	if not adaylar:
		return
	harita = {
		r.source_url: r.target_url
		for r in frappe.get_all(
			"Media URL Redirect",
			filters={"source_url": ["in", adaylar], "expires_at": [">", now_datetime()]},
			fields=["source_url", "target_url"],
		)
		if r.target_url
	}
	if not harita:
		return
	if doc.get("primary_image") in harita:
		doc.primary_image = harita[doc.primary_image]
	for r in doc.get("listing_images") or []:
		if r.get("image") in harita:
			r.image = harita[r.image]
	for v in varyantlar:
		if v.get("variant_image") in harita:
			v.variant_image = harita[v.variant_image]
		galeri = galeriler.get(id(v))
		if galeri and any(isinstance(g, str) and g in harita for g in galeri):
			v.variant_gallery = json.dumps(
				[harita.get(g, g) if isinstance(g, str) else g for g in galeri], ensure_ascii=False
			)
