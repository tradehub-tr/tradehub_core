#!/usr/bin/env python3
"""Üretim medya istatistiği — SALT OKUNUR ölçüm scripti (T-003).

Bu script `docs/reports/02-medya-istatistigi.md` içindeki "ÜRETİMDE
ÇALIŞTIRILACAK SORGULAR" bölümünün çalıştırılabilir hâlidir. Rapor, elde olan
belgelerden çıkarılan sayıları tablolar; bu script o sayıları ÜRETİMDE
doğrulayan ve eksik olanları (p50/p90/p99, >20MP, CMYK, 0 bayt, uzantı-içerik
uyuşmazlığı) ilk kez ölçen koddur.

═══════════════════════════════════════════════════════════════════════════
SALT OKUNUR GARANTİSİ
═══════════════════════════════════════════════════════════════════════════
Bu dosyada `frappe.db.set_value`, `frappe.db.commit`, `doc.save`, `doc.insert`,
`os.remove`, `shutil.*` ÇAĞRISI YOKTUR. Yalnız `frappe.db.sql(select ...)`,
`open(..., "rb")` ve `os.path`/`os.walk` kullanılır. Bir yazma çağrısı eklemek
bu garantiyi bozar — eklemeden önce raporun ilgili bölümünü güncelleyin.

═══════════════════════════════════════════════════════════════════════════
NASIL ÇALIŞTIRILIR
═══════════════════════════════════════════════════════════════════════════
Frappe context'i gerekiyor (`frappe.db` bağlı olmalı). Üç yol:

  # 1) LOCAL DEV (docker) — önerilen
  docker cp scripts/media_stats.py istoc-dev-backend-1:/tmp/media_stats.py
  docker exec -i istoc-dev-backend-1 bench --site istoc.localhost console <<'EOF'
  exec(open('/tmp/media_stats.py').read())
  main()
  EOF

  # 2) PROD / bench kurulu makine
  bench --site <site> console <<'EOF'
  exec(open('/path/to/media_stats.py').read())
  main()
  EOF

  # 3) Kademeli koşu (disk probe pahalıysa — 3k dosyada dakikalar sürer)
  #    Önce yalnız SQL bölümü, disk probe kapalı:
  main(probe_disk=False)
  #    Sonra yalnız en büyük 500 dosyayı probe et:
  main(sql=False, probe_limit=500)

Çıktı hem ekrana basılır hem `MEDIA_STATS_OUT` ortam değişkeni doluysa oraya
JSON yazılır (tek yazma işlemi budur ve rapor dosyasınadır, veritabanına değil):

  MEDIA_STATS_OUT=/tmp/media_stats.json

═══════════════════════════════════════════════════════════════════════════
NEDEN BAZI METRİKLER SQL'DE ÜRETİLEMİYOR
═══════════════════════════════════════════════════════════════════════════
- **Çözünürlük / megapiksel:** `tabFile`'da `th_media_width` / `th_media_height`
  sütunları VAR (media/metadata.py:37-45) ama TEMBEL doldurulur — yalnız
  `metadata.ensure_dimensions()` bir dosya için çağrıldığında (media/metadata.py:
  159-196). Yani sütunun dolu olma oranı bilinmiyor; `where th_media_width > ...`
  ile ölçmek sessizce çoğu dosyayı atlar. Bu yüzden önce KAPSAM ölçülür
  (`dimension_coverage`), sonra gerçek MP diskten okunur.
- **Renk uzayı (CMYK):** `media/engine.py:53-66` `Probe` dataclass'ında `mode`
  alanı YOK. Motor CMYK'yı bilmiyor. Diskten PIL ile doğrudan okunur.
- **Gerçek içerik türü:** `media/upload_policy.py:198-211` (`sniff`) ve
  `:374-395` (`_UYUM`) bu işi zaten yapıyor. YENİDEN YAZILMADI, import edildi.

PIL `Image.open(path)` tembeldir: `size` ve `mode` başlıktan okunur, pikseller
decode edilmez. Bu yüzden binlerce dosyada bile kabul edilebilir hızda çalışır.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict

import frappe

# ─────────────────────────────────────────────────────────────────────────
# Sabitler — eşikler. Görev tanımındaki anomali eşikleri.
# ─────────────────────────────────────────────────────────────────────────

# >20 MP. Kıyas: `media/presets.py:13-17` balanced preset max_dim=2000 →
# optimize edilmiş bir görsel en fazla 2000x2000 = 4 MP olabilir. Yani 20 MP
# üstü bir dosya, Kapı 4'ü (`already_small`, media/gates.py:70-72) geçmiş ama
# HENÜZ optimize edilmemiş bir dosyadır.
MP_THRESHOLD: int = 20_000_000

# >20 MB. Kıyas: `media/upload_policy.py:68` görsel tavanı 25 MB, yani 20-25 MB
# arası dosya BUGÜN GEÇERLİDİR (reddedilmez). upload_policy.py:45-46'daki ölçüm
# "en büyük 21 MB'lık bir TIFF" diyor → en az 1 dosyanın bu eşiği aşması beklenir.
BYTES_THRESHOLD: int = 20 * 1024 * 1024

# Diskten probe edilecek en küçük dosya. 0 = hepsi. Küçük dosyalarda MP/CMYK
# riski pratikte yok; kademeli koşuda bu değeri yükseltin.
PROBE_MIN_BYTES: int = 0

# Beklenen anomali listesi — raporda karşılığı olan anahtarlar.
ANOMALY_KEYS: tuple[str, ...] = (
	"zero_byte_db",
	"zero_byte_disk",
	"missing_on_disk",
	"orphan_on_disk",
	"over_bytes",
	"over_megapixels",
	"cmyk",
	"ext_content_mismatch",
	"dangerous_content",
	"unreadable",
)


# ─────────────────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────────────────


def _percentile(sorted_vals: list[int], p: float) -> float:
	"""Doğrusal enterpolasyonlu persentil (NumPy `linear` yöntemiyle aynı).

	Neden Python'da, SQL'de değil: `PERCENTILE_CONT` MariaDB 10.3.3+ window
	fonksiyonu; sürüm garanti edilemiyor ve bir sürüm farkında sorgu sessizce
	sözdizimi hatası verir. Küme birkaç bin satır — Python'da almak bedava.
	`_size_list()` zaten TEKİLLEŞTİRİLMİŞ (file_url bazında MAX) değer döndürür.
	"""
	if not sorted_vals:
		return 0.0
	if len(sorted_vals) == 1:
		return float(sorted_vals[0])
	k = (len(sorted_vals) - 1) * p
	alt = math.floor(k)
	ust = math.ceil(k)
	if alt == ust:
		return float(sorted_vals[int(k)])
	return sorted_vals[alt] + (sorted_vals[ust] - sorted_vals[alt]) * (k - alt)


def _mb(b: float) -> float:
	return round(b / 1024 / 1024, 2)


def _excluded_placeholders() -> tuple[str, tuple[str, ...]]:
	"""`presets.EXCLUDED_DOCTYPES` için SQL yer tutucusu + parametreler.

	Liste elle KOPYALANMIYOR: `media/presets.py:44-53` tek kaynak. Kopyalansaydı
	yeni bir hassas doctype eklendiğinde bu script onu kapsam dışı saymayı
	unuturdu ve KYB/KYC belgelerini "public medya" olarak raporlardı.
	"""
	from tradehub_core.media.presets import EXCLUDED_DOCTYPES

	return ", ".join(["%s"] * len(EXCLUDED_DOCTYPES)), tuple(EXCLUDED_DOCTYPES)


def _files_root(private: bool) -> str:
	return frappe.get_site_path("private" if private else "public", "files")


# ─────────────────────────────────────────────────────────────────────────
# BÖLÜM 1 — MUTABAKAT: belgelerdeki sayılar hangisiyle örtüşüyor
# ─────────────────────────────────────────────────────────────────────────


def reconcile() -> dict:
	"""Belgelerdeki çelişen sayıların hangi tanıma karşılık geldiğini bulur.

	Rapor §3'te işaretlenen tutarsızlıklar (2.858 / 2.860 / 2.826 / 2839 /
	4003 / 4.007 / 4.195 / 4.324 / 4.800 / 4900) tek bir sayının farklı
	tanımları mı, yoksa gerçekten farklı zamanların ölçümleri mi — bu blok
	cevaplar. Her satır o tanımın BUGÜNKÜ değeridir.
	"""
	ph, params = _excluded_placeholders()

	def tek(sql: str, args=()) -> int:
		row = frappe.db.sql(sql, args)
		return int(row[0][0] or 0) if row else 0

	out: dict[str, int] = {}

	# A) Ham satır sayıları — hiçbir filtre yok.
	out["rows_all"] = tek("select count(*) from tabFile")
	out["rows_not_folder"] = tek("select count(*) from tabFile where is_folder=0")
	out["rows_public"] = tek(
		"select count(*) from tabFile where is_folder=0 and is_private=0"
	)
	out["rows_private"] = tek(
		"select count(*) from tabFile where is_folder=0 and is_private=1"
	)

	# B) TEKİL adres sayıları. `media/inventory.py:9-12` bu ayrımı zaten
	#    belgeliyor: 938 URL'ye 2.860 kayıt, tek bir adreste 39 kayıt.
	#    LIKE değil LEFT: `media/inventory.py:24-26` — utf8mb4_unicode_ci'de
	#    LIKE 4 baytlık karakter içeren satırlarda eşleşmiyor, 23 dosya
	#    sessizce düşüyordu.
	out["urls_public"] = tek(
		"""select count(*) from (select file_url from tabFile
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			group by file_url) x"""
	)
	out["urls_private"] = tek(
		"""select count(*) from (select file_url from tabFile
			where is_folder=0 and is_private=1
			and left(file_url,15)='/private/files/' group by file_url) x"""
	)

	# C) Panelin GERÇEKTEN gördüğü küme — `media/inventory.py:58-89`
	#    `_base_query()` ile birebir aynı üç filtre (is_private=0 + EXCLUDED
	#    doctype + hassas content_hash). Panel sayacı ile disk sayısı
	#    arasındaki farkın kaynağı budur.
	out["urls_inventory_scope"] = tek(
		f"""select count(*) from (
			select file_url from tabFile
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			  and file_url not in (
				select file_url from tabFile
				where attached_to_doctype in ({ph}) and file_url is not null)
			  and (content_hash is null or content_hash not in (
				select content_hash from tabFile where ifnull(content_hash,'')<>''
				  and (is_private=1 or attached_to_doctype in ({ph}))))
			group by file_url) x""",
		params * 2,
	)

	# D) DİSKTEKİ fiziksel dosya sayısı. `docs/MEDYA-DEPOLAMA-STANDARDI.md:31-32`
	#    (2.858 / 192) muhtemelen budur — DB değil disk. Türev dosyalar
	#    (`<hash>_thumb.webp`, MEDYA-DEPOLAMA-STANDARDI.md:118-125) de sayılır,
	#    bu yüzden diskteki sayı DB'dekinden BÜYÜK olabilir.
	for private in (False, True):
		kok = _files_root(private)
		anahtar = "disk_private" if private else "disk_public"
		adet = 0
		if os.path.isdir(kok):
			for _dizin, _alt, dosyalar in os.walk(kok):
				adet += len(dosyalar)
		out[anahtar] = adet

	# E) Shard geçişinin ilerlemesi — `MEDYA-DEPOLAMA-STANDARDI.md:89-104`
	#    yeni yüklemeler `/files/<ab>/<hash>.<ext>` olmalı. Kaç dosya hâlâ düz?
	out["urls_public_flat"] = tek(
		"""select count(*) from (select file_url from tabFile
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			  and file_url not regexp '^/files/[0-9a-f]{2}/'
			group by file_url) x"""
	)
	# F) Tahmin edilebilir eski ad — `MEDYA-DEPOLAMA-STANDARDI.md:150` (2.166).
	#    Tanım: dosya adının gövdesi 32 hex DEĞİL. Hash ismi 32 hex
	#    (`MEDYA-DEPOLAMA-STANDARDI.md:77-80`).
	out["urls_public_non_hashed"] = tek(
		"""select count(*) from (select file_url from tabFile
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			  and substring_index(substring_index(file_url,'/',-1),'.',1)
			      not regexp '^[0-9a-f]{32}$'
			group by file_url) x"""
	)

	# G) Toplam boyut — TEKİLLEŞTİRİLMİŞ. `media/files.py:225-251`
	#    `storage_usage()` ile aynı desen. Satır toplamak 1,06 GB yerine
	#    1,49 GB gösteriyordu (media/inventory.py:11-12).
	row = frappe.db.sql(
		"""select coalesce(sum(boyut),0), count(*) from (
			select max(file_size) boyut from tabFile
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			group by file_url) x"""
	)
	out["bytes_public_dedup"] = int(row[0][0] or 0) if row else 0
	out["bytes_public_raw"] = tek(
		"""select coalesce(sum(file_size),0) from tabFile
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'"""
	)
	return out


def private_breakdown() -> dict:
	"""`docs/MEDYA-ERISIM-MODELI.md:47-48` dağılımının doğrulaması.

	Belgedeki liste: KYB 489, owner-only 71, Bulk Import 29, KYC 9, Brand 4,
	Seller Application 3 → toplam 605. Aynı belgenin atıf yaptığı
	MEDYA-DEPOLAMA-STANDARDI.md:32 ise 192 diyor. Hipotez (rapor §3.1):
	605 = KAYIT sayısı, 192 = DİSKTEKİ dosya sayısı. Bu fonksiyon ikisini de
	ayrı ayrı üretir; hipotez doğruysa `by_doctype_rows` toplamı ~605,
	`by_doctype_urls` toplamı ise diskteki 192'ye yakın çıkar.
	"""
	satirlar = frappe.db.sql(
		"""select coalesce(nullif(attached_to_doctype,''),'__owner_only__') dt,
			count(*) kayit, count(distinct file_url) adres
		from tabFile
		where is_folder=0 and is_private=1
		group by dt order by kayit desc""",
		as_dict=True,
	)
	return {
		"by_doctype_rows": {r["dt"]: int(r["kayit"]) for r in satirlar},
		"by_doctype_urls": {r["dt"]: int(r["adres"]) for r in satirlar},
		"total_rows": sum(int(r["kayit"]) for r in satirlar),
		"total_urls": sum(int(r["adres"]) for r in satirlar),
	}


def pii_exposure() -> dict:
	"""PUBLIC tarafta duran PII belgesi var mı — güvenlik anomalisi.

	İki bilinen sızıntı yolu, ikisi de kodda ölçümle belgeli:

	1. `media/presets.py:56-64` + `media/access_level.py:72-84`: bazı hassas
	   belgeler `attached_to_doctype` BOŞ yükleniyor, yalnız EXCLUDED bir
	   doctype'ın Data/Attach alanında string olarak duruyor. Ölçüm:
	   `Seller Application.identity_document` 144, `Seller Certification.
	   document` 2 → 146 kimlik/PII belgesi.
	2. `media/inventory.py:68-79`: 44 public dosya bir private/hassas belgeyle
	   AYNI `content_hash`'e sahip; 6'sı panelde listeleniyordu, biri KYC
	   kimlik belgesiydi.

	Bu fonksiyon ikisini de bugünkü veriyle yeniden sayar.
	"""
	from tradehub_core.media.presets import EXCLUDED_MEDIA_FIELDS

	ph, params = _excluded_placeholders()

	ters_referans: dict[str, int] = {}
	for doctype, alanlar in EXCLUDED_MEDIA_FIELDS.items():
		for alan in alanlar:
			try:
				row = frappe.db.sql(
					f"""select count(*) from `tab{doctype}` d
						join tabFile f on f.file_url = d.`{alan}`
						where ifnull(d.`{alan}`,'')<>''
						  and f.is_private=0
						  and ifnull(f.attached_to_doctype,'')=''""",  # noqa: S608
				)
			except Exception as exc:  # tablo/sütun yoksa sessiz geçme, RAPORLA
				ters_referans[f"{doctype}.{alan}"] = f"HATA: {type(exc).__name__}"
				continue
			ters_referans[f"{doctype}.{alan}"] = int(row[0][0] or 0) if row else 0

	hash_row = frappe.db.sql(
		f"""select count(distinct f.file_url) from tabFile f
			where f.is_folder=0 and f.is_private=0 and ifnull(f.content_hash,'')<>''
			  and f.content_hash in (
				select content_hash from tabFile
				where ifnull(content_hash,'')<>''
				  and (is_private=1 or attached_to_doctype in ({ph})))""",
		params,
	)
	return {
		"reverse_ref_public_pii": ters_referans,
		"public_sharing_sensitive_hash": int(hash_row[0][0] or 0) if hash_row else 0,
	}


# ─────────────────────────────────────────────────────────────────────────
# BÖLÜM 2 — BOYUT DAĞILIMI (p50 / p90 / p99)
# ─────────────────────────────────────────────────────────────────────────


def _size_list(scope: str = "inventory") -> list[int]:
	"""Tekilleştirilmiş dosya boyutları, artan sıralı.

	`scope`:
	  "inventory" → panelin gördüğü küme (media/inventory.py:58-89 ile aynı)
	  "public"    → tüm public dosyalar, EXCLUDED filtresi YOK
	  "private"   → private dosyalar
	"""
	if scope == "private":
		sql = """select max(file_size) b from tabFile
			where is_folder=0 and is_private=1
			  and left(file_url,15)='/private/files/'
			group by file_url"""
		args: tuple = ()
	elif scope == "public":
		sql = """select max(file_size) b from tabFile
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			group by file_url"""
		args = ()
	else:
		ph, params = _excluded_placeholders()
		sql = f"""select max(file_size) b from tabFile
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			  and file_url not in (
				select file_url from tabFile
				where attached_to_doctype in ({ph}) and file_url is not null)
			  and (content_hash is null or content_hash not in (
				select content_hash from tabFile where ifnull(content_hash,'')<>''
				  and (is_private=1 or attached_to_doctype in ({ph}))))
			group by file_url"""
		args = params * 2
	return sorted(int(r[0] or 0) for r in frappe.db.sql(sql, args))


def size_distribution() -> dict:
	"""p50/p90/p99 + eşik üstü sayılar, üç kapsam için ayrı.

	Üç kapsam ayrı raporlanıyor çünkü rapor §3.2'de işaretlenen ~2.8k / ~4.0k
	ayrışmasının kaynağı tam olarak bu kapsam farkı olabilir. Aynı persentili
	iki farklı kümede görmek hangi belgenin hangi kümeyi ölçtüğünü söyler.
	"""
	sonuc: dict[str, dict] = {}
	for kapsam in ("inventory", "public", "private"):
		vals = _size_list(kapsam)
		if not vals:
			sonuc[kapsam] = {"count": 0}
			continue
		sonuc[kapsam] = {
			"count": len(vals),
			"sum_bytes": sum(vals),
			"sum_mb": _mb(sum(vals)),
			"min_bytes": vals[0],
			"p50_bytes": int(_percentile(vals, 0.50)),
			"p90_bytes": int(_percentile(vals, 0.90)),
			"p99_bytes": int(_percentile(vals, 0.99)),
			"max_bytes": vals[-1],
			"p50_mb": _mb(_percentile(vals, 0.50)),
			"p90_mb": _mb(_percentile(vals, 0.90)),
			"p99_mb": _mb(_percentile(vals, 0.99)),
			"max_mb": _mb(vals[-1]),
			# Politika kıyasları — media/upload_policy.py:67-72 ve
			# media/presets.py:22 (MIN_FILE_SIZE = 200 KB, Kapı 1).
			"zero_byte": sum(1 for v in vals if v == 0),
			"under_200kb": sum(1 for v in vals if v < 200 * 1024),
			"over_20mb": sum(1 for v in vals if v > BYTES_THRESHOLD),
			"over_25mb": sum(1 for v in vals if v > 25 * 1024 * 1024),
		}
	return sonuc


def dimension_coverage() -> dict:
	"""`th_media_width` KAÇ satırda dolu — MP'yi SQL'de ölçmenin ön koşulu.

	`media/metadata.py:159-196` alanı yalnız `ensure_dimensions()` çağrıldığında
	doldurur. Kapsam düşükse (beklenen) SQL ile MP ölçmek anlamsızdır ve
	`probe_images()` zorunlu hâle gelir. Bu sayı raporun "neden diske inmek
	zorundayız" iddiasının kanıtıdır.
	"""
	row = frappe.db.sql(
		"""select count(distinct file_url),
			count(distinct case when ifnull(th_media_width,0)>0 then file_url end)
		from tabFile
		where is_folder=0 and is_private=0 and left(file_url,7)='/files/'"""
	)
	toplam = int(row[0][0] or 0) if row else 0
	dolu = int(row[0][1] or 0) if row else 0
	# Alanı dolu olanlarda MP dağılımı — kapsam düşükse TEMSİLİ DEĞİLDİR.
	mp = frappe.db.sql(
		f"""select count(distinct file_url) from tabFile
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			  and ifnull(th_media_width,0)*ifnull(th_media_height,0) > {MP_THRESHOLD}"""
	)
	return {
		"urls_total": toplam,
		"urls_with_dimensions": dolu,
		"coverage_pct": round(100.0 * dolu / toplam, 1) if toplam else 0.0,
		"over_20mp_in_db_only": int(mp[0][0] or 0) if mp else 0,
		"note": (
			"coverage_pct düşükse over_20mp_in_db_only ALT SINIRDIR, gerçek sayı değil. "
			"Gerçek sayı için probe_images() çalıştırın."
		),
	}


# ─────────────────────────────────────────────────────────────────────────
# BÖLÜM 3 — DİSK PROBE: MP, CMYK, 0 bayt, uzantı-içerik uyuşmazlığı
# ─────────────────────────────────────────────────────────────────────────


def _rows_for_probe(limit: int = 0, min_bytes: int = PROBE_MIN_BYTES) -> list[dict]:
	"""Probe edilecek tekilleştirilmiş satırlar — büyükten küçüğe."""
	sql = """select file_url, max(file_size) file_size,
			min(file_name) file_name, min(name) name
		from tabFile
		where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
		group by file_url
		having max(file_size) >= %s
		order by max(file_size) desc"""
	if limit:
		sql += f" limit {int(limit)}"
	return frappe.db.sql(sql, (int(min_bytes),), as_dict=True)


def probe_images(limit: int = 0, min_bytes: int = PROBE_MIN_BYTES, verbose: bool = True) -> dict:
	"""Diskten okuyarak anomali tespiti — SQL'in ulaşamadığı her şey.

	Ölçülenler:
	  >20 MP            → width*height (PIL, tembel — piksel decode edilmez)
	  CMYK              → PIL `im.mode` (engine.Probe'da bu alan YOK, bkz. modül başlığı)
	  0 bayt            → diskteki gerçek boyut (DB'deki file_size yalan söyleyebilir)
	  diskte yok        → `File` kaydı var, dosya yok (media/gates.py:36-38 "file_missing")
	  uzantı-içerik     → media/upload_policy.py `sniff` + `_UYUM` (YENİDEN YAZILMADI)
	  tehlikeli içerik  → media/upload_policy.py `is_dangerous` — .jpg adlı <svg>

	DB'deki `file_size` ile diskteki gerçek boyut ayrı raporlanır: ikisinin
	ayrışması kota (`media/files.py:225-251`) ve depolama raporunun yanlış
	olduğu anlamına gelir.
	"""
	from PIL import Image

	from tradehub_core.media import upload_policy

	satirlar = _rows_for_probe(limit=limit, min_bytes=min_bytes)
	kok = _files_root(private=False)

	bulgular: dict[str, list] = {k: [] for k in ANOMALY_KEYS}
	mod_sayaci: Counter = Counter()
	format_sayaci: Counter = Counter()
	mp_listesi: list[int] = []
	boyut_sapmasi: list[dict] = []
	incelenen = 0

	for i, r in enumerate(satirlar):
		if verbose and i and i % 200 == 0:
			print(f"  … {i}/{len(satirlar)} dosya incelendi")

		rel = (r["file_url"] or "")[len("/files/") :]
		yol = os.path.join(kok, rel)
		if not os.path.isfile(yol):
			bulgular["missing_on_disk"].append({"file_url": r["file_url"], "db_size": r["file_size"]})
			continue

		gercek_boyut = os.path.getsize(yol)
		incelenen += 1
		if gercek_boyut == 0:
			bulgular["zero_byte_disk"].append({"file_url": r["file_url"]})
			continue
		if int(r["file_size"] or 0) != gercek_boyut:
			boyut_sapmasi.append(
				{"file_url": r["file_url"], "db": int(r["file_size"] or 0), "disk": gercek_boyut}
			)
		if gercek_boyut > BYTES_THRESHOLD:
			bulgular["over_bytes"].append({"file_url": r["file_url"], "bytes": gercek_boyut})

		# İçerik imzası — ilk 512 bayt yeter (upload_policy.sniff 32, is_dangerous 512).
		try:
			with open(yol, "rb") as fh:
				bas = fh.read(512)
		except OSError as exc:
			bulgular["unreadable"].append({"file_url": r["file_url"], "error": str(exc)})
			continue

		if upload_policy.is_dangerous(bas):
			bulgular["dangerous_content"].append({"file_url": r["file_url"]})

		uzanti = upload_policy.extension_of(r["file_url"])
		gercek_tur = upload_policy.sniff(bas)
		if gercek_tur and uzanti and not upload_policy._uyumlu(uzanti, gercek_tur):
			bulgular["ext_content_mismatch"].append(
				{"file_url": r["file_url"], "ext": uzanti, "content": gercek_tur}
			)

		# Görsel künyesi — tembel açılış, piksel decode YOK.
		try:
			with Image.open(yol) as im:
				w, h = im.size
				mod = im.mode
				fmt = (im.format or "").upper()
		except Exception:
			# Görsel olmayan dosyalar (pdf, zip, mp4) buraya düşer — anomali DEĞİL.
			if uzanti in upload_policy.EXTENSIONS and upload_policy.EXTENSIONS[uzanti] == "image":
				bulgular["unreadable"].append({"file_url": r["file_url"], "error": "decode_failed"})
			continue

		mod_sayaci[mod] += 1
		format_sayaci[fmt] += 1
		mp = w * h
		mp_listesi.append(mp)
		if mp > MP_THRESHOLD:
			bulgular["over_megapixels"].append(
				{"file_url": r["file_url"], "w": w, "h": h, "megapixels": round(mp / 1e6, 1)}
			)
		# CMYK: `media/engine.py:121` JPEG'i convert("RGB") ile düzeltir AMA
		# yalnız tüm kapıları geçen dosyada. `media/engine.py:127-131` TIFF'i
		# bilerek çevirmez (alpha/renk yönetimi korunsun diye). Yani Kapı 4'e
		# takılan bir CMYK dosyası tarayıcıya CMYK olarak gider.
		if mod in ("CMYK", "YCbCr", "LAB"):
			bulgular["cmyk"].append({"file_url": r["file_url"], "mode": mod, "format": fmt})

	mp_listesi.sort()
	return {
		"examined": incelenen,
		"candidates": len(satirlar),
		"modes": dict(mod_sayaci),
		"formats": dict(format_sayaci),
		"megapixels": {
			"count": len(mp_listesi),
			"p50": round(_percentile(mp_listesi, 0.50) / 1e6, 2),
			"p90": round(_percentile(mp_listesi, 0.90) / 1e6, 2),
			"p99": round(_percentile(mp_listesi, 0.99) / 1e6, 2),
			"max": round((mp_listesi[-1] if mp_listesi else 0) / 1e6, 2),
		},
		"db_disk_size_mismatch": boyut_sapmasi[:50],
		"db_disk_size_mismatch_count": len(boyut_sapmasi),
		"anomalies": {k: v for k, v in bulgular.items()},
		"anomaly_counts": {k: len(v) for k, v in bulgular.items()},
	}


def orphan_files(limit: int = 200) -> dict:
	"""Diskte duran ama `File` kaydı olmayan dosyalar.

	`MEDYA-DEPOLAMA-STANDARDI.md:57-66`'daki üç medya-özel kök
	(`image_originals`, `media_trash`, `media-backups`) BİLEREK `File` kaydı
	üretmez ve burada sayılmaz — onlar `public/files` altında değil.
	`public/files` altındaki kayıtsız bir dosya ise ya türev
	(`<hash>_thumb.webp`) ya da gerçek yetimdir.
	"""
	kok = _files_root(private=False)
	if not os.path.isdir(kok):
		return {"root_missing": kok}

	diskte: set[str] = set()
	for dizin, _alt, dosyalar in os.walk(kok):
		rel_dir = os.path.relpath(dizin, kok)
		for d in dosyalar:
			rel = d if rel_dir == "." else f"{rel_dir}/{d}"
			diskte.add(f"/files/{rel}")

	kayitli = {
		r[0]
		for r in frappe.db.sql(
			"""select distinct file_url from tabFile
				where is_folder=0 and is_private=0 and left(file_url,7)='/files/'"""
		)
	}
	yetim = sorted(diskte - kayitli)
	# Türev deseni — MEDYA-DEPOLAMA-STANDARDI.md:118-125 (`<hash>_thumb.webp`).
	turev = [u for u in yetim if "_" in os.path.basename(u)]
	return {
		"disk_count": len(diskte),
		"db_url_count": len(kayitli),
		"orphan_count": len(yetim),
		"orphan_looks_like_derivative": len(turev),
		"orphan_sample": yetim[:limit],
		"db_url_without_disk_file": len(kayitli - diskte),
	}


# ─────────────────────────────────────────────────────────────────────────
# BÖLÜM 4 — Tekrar yükleme / çoklu kullanım (mevcut kodun ölçtüğü metrikler)
# ─────────────────────────────────────────────────────────────────────────


def duplication() -> dict:
	"""Aynı adrese kaç kayıt düşüyor — `media/inventory.py:9-12`'deki 39'luk
	uç değerin bugünkü karşılığı.

	`_usage_kind` (media/inventory.py:339-345) ayrımını da üretir:
	  multi_use → dosya birden çok KAYITTA kullanılıyor
	  repeat    → aynı görsel defalarca YÜKLENMİŞ
	"""
	satirlar = frappe.db.sql(
		"""select file_url, count(*) kayit,
			count(distinct nullif(attached_to_name,'')) bagli
		from tabFile
		where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
		group by file_url""",
		as_dict=True,
	)
	kayit_sayilari = sorted(int(r["kayit"]) for r in satirlar)
	tipler: Counter = Counter()
	for r in satirlar:
		if int(r["bagli"]) > 1:
			tipler["multi_use"] += 1
		elif int(r["kayit"]) > 1:
			tipler["repeat"] += 1
		else:
			tipler["single"] += 1
	en_cok = sorted(satirlar, key=lambda r: -int(r["kayit"]))[:20]
	return {
		"urls": len(satirlar),
		"rows": sum(kayit_sayilari),
		"amplification": round(sum(kayit_sayilari) / len(satirlar), 2) if satirlar else 0,
		"records_per_url": {
			"p50": _percentile(kayit_sayilari, 0.50),
			"p90": _percentile(kayit_sayilari, 0.90),
			"p99": _percentile(kayit_sayilari, 0.99),
			"max": kayit_sayilari[-1] if kayit_sayilari else 0,
		},
		"kinds": dict(tipler),
		"top_repeated": [{"file_url": r["file_url"], "records": int(r["kayit"])} for r in en_cok],
	}


def extension_mix() -> dict:
	"""Uzantı dağılımı + hangi uzantılar motorun işleyebildiği kümede.

	`media/engine.py:38-42` `supported_extensions()` tek kaynak — liste elle
	kopyalanmıyor (kopyalanınca sessizce eskiyor, engine.py:23-26 notu).
	"""
	from tradehub_core.media import engine

	satirlar = frappe.db.sql(
		"""select lower(substring_index(file_url,'.',-1)) uzanti,
			count(*) adet, coalesce(sum(boyut),0) bayt
		from (select file_url, max(file_size) boyut from tabFile
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			group by file_url) x
		group by uzanti order by adet desc""",
		as_dict=True,
	)
	desteklenen = {e.lstrip(".") for e in engine.supported_extensions()}
	return {
		"by_extension": [
			{
				"ext": r["uzanti"],
				"count": int(r["adet"]),
				"mb": _mb(int(r["bayt"])),
				"engine_supported": r["uzanti"] in desteklenen,
			}
			for r in satirlar
		],
		"engine_supported_extensions": sorted(desteklenen),
	}


# ─────────────────────────────────────────────────────────────────────────
# Ana akış
# ─────────────────────────────────────────────────────────────────────────


def main(
	*,
	sql: bool = True,
	probe_disk: bool = True,
	probe_limit: int = 0,
	probe_min_bytes: int = PROBE_MIN_BYTES,
	verbose: bool = True,
) -> dict:
	"""Tüm ölçümleri çalıştır, sözlük döndür ve ekrana özet bas."""
	rapor: dict = {
		"site": getattr(frappe.local, "site", "?"),
		"measured_at": frappe.utils.now(),
		"thresholds": {
			"megapixels": MP_THRESHOLD,
			"bytes": BYTES_THRESHOLD,
			"probe_min_bytes": probe_min_bytes,
		},
	}

	if sql:
		if verbose:
			print("[1/6] Mutabakat (belgelerdeki sayılar hangi tanıma karşılık geliyor)…")
		rapor["reconcile"] = reconcile()
		if verbose:
			print("[2/6] Private dağılımı…")
		rapor["private_breakdown"] = private_breakdown()
		if verbose:
			print("[3/6] PII maruziyeti…")
		rapor["pii_exposure"] = pii_exposure()
		if verbose:
			print("[4/6] Boyut dağılımı (p50/p90/p99)…")
		rapor["size_distribution"] = size_distribution()
		rapor["dimension_coverage"] = dimension_coverage()
		rapor["duplication"] = duplication()
		rapor["extension_mix"] = extension_mix()

	if probe_disk:
		if verbose:
			print("[5/6] Disk probe (MP / CMYK / 0 bayt / uzantı-içerik)…")
		rapor["probe"] = probe_images(
			limit=probe_limit, min_bytes=probe_min_bytes, verbose=verbose
		)
		if verbose:
			print("[6/6] Yetim dosyalar…")
		rapor["orphans"] = orphan_files()

	if verbose:
		_print_summary(rapor)

	hedef = os.environ.get("MEDIA_STATS_OUT")
	if hedef:
		with open(hedef, "w", encoding="utf-8") as fh:
			json.dump(rapor, fh, ensure_ascii=False, indent=2, default=str)
		print(f"\nJSON yazıldı: {hedef}")

	return rapor


def _print_summary(r: dict) -> None:
	"""Rapor tablolarına doğrudan kopyalanabilir özet."""
	print("\n" + "═" * 72)
	print(f"MEDYA İSTATİSTİĞİ — {r.get('site')} — {r.get('measured_at')}")
	print("═" * 72)

	rec = r.get("reconcile") or {}
	if rec:
		print("\n── MUTABAKAT ─────────────────────────────────────────────")
		for k in (
			"rows_all",
			"rows_public",
			"rows_private",
			"urls_public",
			"urls_private",
			"urls_inventory_scope",
			"disk_public",
			"disk_private",
			"urls_public_flat",
			"urls_public_non_hashed",
		):
			print(f"  {k:<28} {rec.get(k, '—')}")
		print(f"  {'bytes_public_dedup (MB)':<28} {_mb(rec.get('bytes_public_dedup', 0))}")
		print(f"  {'bytes_public_raw   (MB)':<28} {_mb(rec.get('bytes_public_raw', 0))}")

	pb = r.get("private_breakdown") or {}
	if pb:
		print("\n── PRIVATE DAĞILIMI (kayıt / adres) ──────────────────────")
		for dt, adet in sorted(pb.get("by_doctype_rows", {}).items(), key=lambda x: -x[1]):
			print(f"  {dt:<28} {adet:>5} / {pb.get('by_doctype_urls', {}).get(dt, 0)}")
		print(f"  {'TOPLAM':<28} {pb.get('total_rows')} / {pb.get('total_urls')}")

	sd = r.get("size_distribution") or {}
	if sd:
		print("\n── BOYUT DAĞILIMI (MB) ───────────────────────────────────")
		print(f"  {'kapsam':<12}{'n':>7}{'p50':>9}{'p90':>9}{'p99':>9}{'max':>9}{'>20MB':>8}{'0B':>5}")
		for kapsam, d in sd.items():
			if not d.get("count"):
				continue
			print(
				f"  {kapsam:<12}{d['count']:>7}{d['p50_mb']:>9}{d['p90_mb']:>9}"
				f"{d['p99_mb']:>9}{d['max_mb']:>9}{d['over_20mb']:>8}{d['zero_byte']:>5}"
			)

	dc = r.get("dimension_coverage") or {}
	if dc:
		print(
			f"\n── ÇÖZÜNÜRLÜK KAPSAMI ─ th_media_width dolu: "
			f"{dc.get('urls_with_dimensions')}/{dc.get('urls_total')} "
			f"(%{dc.get('coverage_pct')})"
		)

	pr = r.get("probe") or {}
	if pr:
		print("\n── ANOMALİLER (disk probe) ───────────────────────────────")
		print(f"  incelenen dosya: {pr.get('examined')} / aday {pr.get('candidates')}")
		for k, v in (pr.get("anomaly_counts") or {}).items():
			isaret = "!!" if v else "  "
			print(f"  {isaret} {k:<26} {v}")
		mp = pr.get("megapixels") or {}
		print(
			f"  MP  p50={mp.get('p50')} p90={mp.get('p90')} "
			f"p99={mp.get('p99')} max={mp.get('max')}"
		)
		print(f"  renk modları: {pr.get('modes')}")
		print(f"  DB↔disk boyut sapması: {pr.get('db_disk_size_mismatch_count')}")

	pii = r.get("pii_exposure") or {}
	if pii:
		print("\n── PII MARUZİYETİ ────────────────────────────────────────")
		for alan, adet in (pii.get("reverse_ref_public_pii") or {}).items():
			print(f"  !! {alan:<40} {adet}")
		print(f"  !! public/hassas aynı content_hash        {pii.get('public_sharing_sensitive_hash')}")

	orp = r.get("orphans") or {}
	if orp:
		print("\n── YETİM DOSYALAR ────────────────────────────────────────")
		print(f"  diskte {orp.get('disk_count')} / DB'de {orp.get('db_url_count')}")
		print(
			f"  kayıtsız disk dosyası: {orp.get('orphan_count')} "
			f"(türev görünümlü: {orp.get('orphan_looks_like_derivative')})"
		)
		print(f"  dosyasız DB kaydı:     {orp.get('db_url_without_disk_file')}")
	print("\n" + "═" * 72)


if __name__ == "__main__":
	main()
