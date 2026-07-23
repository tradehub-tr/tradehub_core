"""Resim eşleştirme — folder + filename hibrit auto-detect.

ZIP içinden resimleri File DocType'a yükler ve `SKU → [file_url, ...]` haritası döndürür.
"""

import os
import re
import zipfile

import frappe
from frappe import _

ALLOWED_EXT: set[str] = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

SKU_FILENAME_RE = re.compile(
	# SKU: harf/rakam/tire/nokta (greedy). "_" sınırlayıcı olarak idx için ayrıldı.
	r"^(?P<sku>[A-Z0-9][A-Z0-9\-.]*)"
	# Opsiyonel idx: _<sayı> veya _<tag> (main/detay/on/arka/front/back).
	r"(?:_(?P<idx>\d+|main|detay|on|arka|front|back))?"
	r"\.(?P<ext>jpe?g|png|webp|gif|bmp)$",
	re.IGNORECASE,
)

MAX_FILES_IN_ZIP = 50_000
MAX_UNCOMPRESSED_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB

# SKU eşleştirme anahtarı için Türkçe-fold — resolver/semantic ile aynı tablo.
# Excel'deki SKU ile ZIP dosya/klasör adı arasında büyük/küçük harf ve Türkçe
# karakter farkı sessiz eşleşme kaybına yol açmasın.
_TR_FOLD = str.maketrans(
	{
		"ı": "i",
		"İ": "i",
		"ş": "s",
		"Ş": "s",
		"ğ": "g",
		"Ğ": "g",
		"ü": "u",
		"Ü": "u",
		"ö": "o",
		"Ö": "o",
		"ç": "c",
		"Ç": "c",
	}
)

# magic-number imzaları — uzantıya güvenmeyip içeriği doğrula.
_IMAGE_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM")

# Web için en uzun kenar — büyük orijinaller depolama/bant şişirmesin.
MAX_IMAGE_DIM = 1600


def optimize_image(content: bytes) -> bytes:
	"""Görseli web boyutuna küçült (en uzun kenar MAX_IMAGE_DIM) + yeniden sıkıştır.

	FORMAT KORUNUR (PNG→PNG, JPEG→JPEG, WEBP→WEBP). Yalnız küçültür (upscale yok).
	Açılamayan / animasyonlu / GIF-BMP / zaten küçük görselde orijinali döndürür —
	görsel asla kaybedilmez (başarısızlık güvenli).
	"""
	try:
		import io

		from PIL import Image

		im = Image.open(io.BytesIO(content))
		fmt = (im.format or "").upper()
		if fmt not in ("JPEG", "PNG", "WEBP"):
			return content  # GIF/BMP → dokunma
		if getattr(im, "is_animated", False):
			return content  # animasyon → bozma
		im.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))  # yalnız downscale
		buf = io.BytesIO()
		if fmt == "JPEG":
			im.convert("RGB").save(buf, "JPEG", quality=85, optimize=True, progressive=True)
		elif fmt == "PNG":
			im.save(buf, "PNG", optimize=True)
		else:  # WEBP
			im.save(buf, "WEBP", quality=85)
		out = buf.getvalue()
		# Yalnız gerçekten küçülttüyse kullan (küçük görseli şişirme).
		return out if out and len(out) < len(content) else content
	except Exception:
		frappe.log_error("Image optimize failed, returning original", "bulk_import.image_matcher")
		return content


def normalize_sku_key(sku) -> str:
	"""SKU eşleştirme anahtarı — strip + Türkçe-fold + lowercase."""
	return (str(sku) if sku is not None else "").strip().translate(_TR_FOLD).lower()


def _natural_key(name: str) -> list:
	"""Doğal sıralama anahtarı — '1,2,…,10' (leksikografik '1,10,2' hatasını önler)."""
	return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _looks_like_image(content: bytes) -> bool:
	"""İçerik magic-number ile gerçekten görsel mi (uzantı sahte olabilir)."""
	if not content or len(content) < 12:
		return False
	if content.startswith(_IMAGE_SIGNATURES):
		return True
	# webp: RIFF....WEBP
	return content[:4] == b"RIFF" and content[8:12] == b"WEBP"


# Klasör/dosya adının başındaki kod token'ı: "325 LOGOSUZ"→"325", "308-1"→"308".
_LEADING_CODE_RE = re.compile(r"^\s*(\d+[A-Za-z]?)")


def _leading_code(segment: str) -> str | None:
	m = _LEADING_CODE_RE.match(str(segment))
	return normalize_sku_key(m.group(1)) if m else None


def _match_sku_in_path(norm_name: str, known: set[str], seller_profile: str) -> str | None:
	"""Yol segmentlerini (klasörler derinden sığa + dosya adı kökü) bilinen SKU
	kümesiyle eşle. Önce TAM normalize eşleşme (tüm segmentler), sonra baş-kod
	token'ı, en son satıcıya özel SKU dosya-adı deseni. Belirsizliği önlemek için
	tam eşleşme token eşleşmesinden önce gelir (örn. derinde '308' varken üstteki
	'307 sehpa'nın '307' token'ını ezmesin)."""
	parts = norm_name.split("/")
	folders = parts[:-1]
	stem = os.path.splitext(parts[-1])[0]
	# En derin klasör önce (dosyanın doğrudan üst klasörü = en olası SKU), sonra dosya adı.
	segments = [*reversed(folders), stem]

	for seg in segments:  # pass 1: tam eşleşme (varyant SKU'ları da burada)
		key = normalize_sku_key(seg)
		if key in known:
			return key
	for seg in segments:  # pass 2: baş-kod token'ı
		tok = _leading_code(seg)
		if tok and tok in known:
			return tok

	# pass 3: satıcıya özel "SKU Filename" deseni (Faz 4.2) → bilinen SKU mu?
	from tradehub_core.bulk_import import regex_lib

	extracted = regex_lib.extract_sku_from_filename(parts[-1], seller_profile)
	if extracted and normalize_sku_key(extracted) in known:
		return normalize_sku_key(extracted)
	return None


def build_image_index(
	zip_path: str,
	seller_profile: str,
	known_skus: set[str] | list[str] | None = None,
	image_overrides: dict[str, str] | None = None,
) -> tuple[dict[str, list[str]], list[str]]:
	"""ZIP'i aç ve (SKU → [File URLs], yetim_dosyalar) döndür.

	known_skus verilirse (önerilen): SKU'yu **yolun herhangi bir derinliğinde**,
	gerçek ürün SKU listesine göre eşler — derin yuvalama, kategori sarmalı,
	"325 LOGOSUZ" eki, "308-1" varyantı belirsizlik olmadan çözülür.
	known_skus boşsa: geriye uyumlu eski davranış (üst-klasör=SKU + SKU.jpg).
	image_overrides: {klasör_anahtarı: sku | "__ignore__"} — kullanıcının 'Görseller'
	adımında yaptığı manuel atama; otomatik eşleştirmeyi ezer.
	SKU anahtarları normalize edilir; orphans = hiçbir SKU'ya eşleşmeyen dosyalar.
	"""
	index: dict[str, list[str]] = {}
	orphans: list[str] = []
	known = {normalize_sku_key(s) for s in (known_skus or []) if s}
	overrides = image_overrides or {}

	with zipfile.ZipFile(zip_path, "r") as zf:
		names = zf.namelist()
		if len(names) > MAX_FILES_IN_ZIP:
			frappe.throw(_("ZIP'te {0}'den fazla dosya var").format(MAX_FILES_IN_ZIP))

		total_size = sum(z.file_size for z in zf.infolist())
		if total_size > MAX_UNCOMPRESSED_SIZE:
			frappe.throw(_("ZIP açıldığında 2 GB'ı aşıyor — zip bomb riski"))

		# Geçerli görsel girişlerini topla (macosx/dizin/uzantı/traversal filtresi).
		valid: list[tuple[str, str]] = []  # (orijinal_ad, normalize_yol)
		for name in names:
			if name.startswith("__MACOSX/") or name.startswith("._") or "/._" in name:
				continue
			if name.endswith("/"):
				continue
			if os.path.splitext(name)[1].lower() not in ALLOWED_EXT:
				continue
			norm = os.path.normpath(name).replace("\\", "/")
			if norm.startswith("..") or norm.startswith("/") or os.path.isabs(norm):
				continue
			valid.append((name, norm))

		if known:
			# SKU-küme-bilinçli, derinlik-bağımsız eşleştirme.
			groups: dict[str, list[str]] = {}
			for name, norm in valid:
				# Kullanıcı manuel atama yaptıysa (Görseller adımı) otomatiği ez.
				ov = overrides.get(_orphan_key(norm)[0])
				if ov == "__ignore__":
					continue  # bilinçli yoksay
				if ov:
					groups.setdefault(normalize_sku_key(ov), []).append(name)
					continue
				sku = _match_sku_in_path(norm, known, seller_profile)
				if sku:
					groups.setdefault(sku, []).append(name)
				else:
					orphans.append(os.path.basename(name))
			for sku, files in groups.items():
				files.sort(key=lambda n: _natural_key(n))
				for f in files:
					url = _extract_and_save(zf, f, seller_profile)
					if url:
						index.setdefault(sku, []).append(url)
			return index, orphans

		# ── Geriye uyum: known_skus yok → eski üst-klasör/dosya-adı davranışı ──
		from tradehub_core.bulk_import import regex_lib

		folder_groups: dict[str, list[str]] = {}
		top_level_files: list[str] = []
		for name, norm in valid:
			parts = norm.split("/")
			if len(parts) == 1:
				top_level_files.append(name)
			else:
				folder_groups.setdefault(parts[0], []).append(name)

		for sku, files in folder_groups.items():
			files.sort(key=_natural_key)
			uploaded: list[str] = []
			for f in files:
				url = _extract_and_save(zf, f, seller_profile)
				if url:
					uploaded.append(url)
			if uploaded:
				index.setdefault(normalize_sku_key(sku), []).extend(uploaded)

		for name in top_level_files:
			filename = os.path.basename(name)
			m = SKU_FILENAME_RE.match(filename)
			sku = m.group("sku") if m else regex_lib.extract_sku_from_filename(filename, seller_profile)
			if not sku:
				orphans.append(filename)
				continue
			url = _extract_and_save(zf, name, seller_profile)
			if url:
				index.setdefault(normalize_sku_key(sku), []).append(url)

	return index, orphans


def _extract_and_save(
	zf: zipfile.ZipFile,
	zip_entry: str,
	seller_profile: str,
) -> str | None:
	"""ZIP içindeki bir dosyayı File DocType'a kaydet, URL döndür."""
	try:
		content = zf.read(zip_entry)
		# Uzantı .jpg olsa da içerik gerçekten görsel mi — sahte/bozuk dosyayı File'a yazma.
		if not _looks_like_image(content):
			return None
		# Web boyutuna küçült + yeniden sıkıştır (format korunur; başarısızsa orijinal).
		content = optimize_image(content)
		filename = os.path.basename(zip_entry)
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"content": content,
				"is_private": 0,
				"decode": False,
			}
		)
		file_doc.insert(ignore_permissions=True)
		return file_doc.file_url
	except Exception as e:
		frappe.log_error(
			f"Image extract failed {zip_entry}: {e}",
			"bulk_import.image_matcher",
		)
		return None


def _orphan_key(norm_name: str) -> tuple[str, str]:
	"""Yetim dosya için (override anahtarı, görünen etiket).

	Klasör altıysa: anahtar = tam üst klasör yolu, etiket = son segment.
	Top-level ise: anahtar = dosya adı, etiket = dosya adı.
	"""
	if "/" in norm_name:
		folder = norm_name.rsplit("/", 1)[0]
		return folder, folder.rsplit("/", 1)[-1]
	return norm_name, norm_name


def _thumb_data_url(zf: zipfile.ZipFile, entry: str, px: int = 80) -> str | None:
	"""ZIP içindeki görseli küçük base64 data-URL thumbnail'a çevir (File kaydetmeden)."""
	try:
		import base64
		import io

		from PIL import Image

		content = zf.read(entry)
		if not _looks_like_image(content):
			return None
		im = Image.open(io.BytesIO(content))
		if getattr(im, "is_animated", False):
			im.seek(0)
		im = im.convert("RGB")
		im.thumbnail((px, px))
		buf = io.BytesIO()
		im.save(buf, "JPEG", quality=70)
		return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
	except Exception:
		frappe.log_error("Thumbnail generation failed", "bulk_import.image_matcher")
		return None


def preview_zip_grouping(
	zip_path: str,
	known_skus: set[str] | list[str] | None,
	seller_profile: str,
	max_thumbs_per_group: int = 6,
) -> dict:
	"""Önizleme: ZIP'i SKU'lara eşle — File KAYDETMEDEN — eşleşen/yetim grupları +
	base64 thumbnail döndür. Sihirbazın 'Görseller' adımı bunu kullanır.

	Returns:
		{
			"matched": [{"sku", "count", "thumb"}],
			"orphans": [{"folder", "label", "count", "thumbs": [data-url, ...]}],
			"total_images": int,
		}
	"""
	known = {normalize_sku_key(s) for s in (known_skus or []) if s}
	matched_groups: dict[str, list[str]] = {}
	orphan_groups: dict[str, dict] = {}  # key -> {label, files}

	with zipfile.ZipFile(zip_path, "r") as zf:
		names = zf.namelist()
		if len(names) > MAX_FILES_IN_ZIP:
			frappe.throw(_("ZIP'te {0}'den fazla dosya var").format(MAX_FILES_IN_ZIP))

		for name in names:
			if name.startswith("__MACOSX/") or name.startswith("._") or "/._" in name:
				continue
			if name.endswith("/"):
				continue
			if os.path.splitext(name)[1].lower() not in ALLOWED_EXT:
				continue
			norm = os.path.normpath(name).replace("\\", "/")
			if norm.startswith("..") or norm.startswith("/") or os.path.isabs(norm):
				continue

			sku = _match_sku_in_path(norm, known, seller_profile) if known else None
			if sku:
				matched_groups.setdefault(sku, []).append(name)
			else:
				key, label = _orphan_key(norm)
				grp = orphan_groups.setdefault(key, {"label": label, "files": []})
				grp["files"].append(name)

		matched = []
		for sku, files in sorted(matched_groups.items()):
			files.sort(key=_natural_key)
			matched.append({"sku": sku, "count": len(files), "thumb": _thumb_data_url(zf, files[0])})

		orphans = []
		for key, grp in sorted(orphan_groups.items()):
			files = sorted(grp["files"], key=_natural_key)
			thumbs = [t for t in (_thumb_data_url(zf, f) for f in files[:max_thumbs_per_group]) if t]
			orphans.append({"folder": key, "label": grp["label"], "count": len(files), "thumbs": thumbs})

	total = sum(m["count"] for m in matched) + sum(o["count"] for o in orphans)
	# skus: yetim atama dropdown'ı için bu yüklemedeki tüm SKU'lar (sıralı).
	return {"matched": matched, "orphans": orphans, "total_images": total, "skus": sorted(known)}
