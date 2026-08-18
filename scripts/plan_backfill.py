#!/usr/bin/env python3
"""Medya standartlaştırma (backfill) PLANLAYICISI — SALT OKUNUR (T-028).

Bu script `docs/plans/migration.md` içindeki §2 (slot bazında uyum sayımı),
§3 (A/B/C sınıflandırması), §4.2-4.5 (batch / kapasite / disk) ve §7 (durdurma
kriteri) bölümlerinin çalıştırılabilir hâlidir.

═══════════════════════════════════════════════════════════════════════════
BU SCRIPT BACKFILL'İ ÇALIŞTIRMAZ
═══════════════════════════════════════════════════════════════════════════
Yalnız PLAN üretir: hangi dosya hangi sınıfa düşüyor, hangi batch'e giriyor,
arşiv ne kadar şişecek. `frappe.enqueue`, `runner.run_batch`, `engine.optimize`
ÇAĞRILMAZ. Backfill'i başlatan komutlar plan çıktısının sonunda METİN olarak
basılır; operatör onları elle çalıştırır.

═══════════════════════════════════════════════════════════════════════════
SALT OKUNUR GARANTİSİ
═══════════════════════════════════════════════════════════════════════════
Bu dosyada YOKTUR: `frappe.db.set_value`, `frappe.db.commit`, `doc.save`,
`doc.insert`, `frappe.enqueue`, `os.remove`, `os.rename`, `shutil.*`,
`open(..., "w"/"wb"/"a")` (tek istisna: `BACKFILL_PLAN_OUT` JSON çıktısı).
Kullanılan: `frappe.db.sql(select ...)`, `open(..., "rb")`, `os.path`.

`media/engine.py` ve `media/gates.py` fonksiyonları ÇAĞRILIR ama ikisi de saf:
`gates.check_before` `import frappe` içermez (gates.py:1), `engine.probe`
yalnız bellekteki baytları okur (engine.py:79-93). `engine.optimize` ÇAĞRILMAZ.

═══════════════════════════════════════════════════════════════════════════
NASIL ÇALIŞTIRILIR
═══════════════════════════════════════════════════════════════════════════
  # LOCAL DEV (docker açıkken)
  docker cp scripts/plan_backfill.py istoc-dev-backend-1:/tmp/plan_backfill.py
  docker exec -i istoc-dev-backend-1 bench --site istoc.localhost console <<'EOF'
  exec(open('/tmp/plan_backfill.py').read())
  main()
  EOF

  # PROD (bench kurulu makine)
  bench --site <site> console <<'EOF'
  exec(open('/path/to/plan_backfill.py').read())
  main()
  EOF

  # Kademeli — disk probe pahalıysa (3k dosyada dakikalar sürer)
  main(probe_disk=False)              # yalnız SQL: küme, kapsam, slot dağılımı
  main(sql=False, probe_limit=500)    # yalnız en büyük 500 dosyayı probe et

  # JSON çıktısı (batch listesi buradan okunur)
  BACKFILL_PLAN_OUT=/tmp/backfill_plan.json

═══════════════════════════════════════════════════════════════════════════
ÖN KOŞUL — BU SCRIPTTEN ÖNCE
═══════════════════════════════════════════════════════════════════════════
`scripts/media_stats.py` → `pii_exposure()` (migration.md §9.1 Ö1).
144+2 hassas belge public tarafta olabilir (media/presets.py:56-64, T-7).
O ölçüm yapılmadan HİÇBİR backfill batch'i enqueue edilmez.

═══════════════════════════════════════════════════════════════════════════
NEDEN SLOT SAYIMI SQL'DE ÜRETİLEMİYOR
═══════════════════════════════════════════════════════════════════════════
`File` doctype'ında slot alanı YOK ve `upload_policy.check()` slot parametresi
ALMIYOR (media/upload_policy.py:307-313). Yani sunucu bir dosyanın hangi slota
yüklendiğini bilmiyor. Slot bilgisi yalnız DOSYAYI GÖSTEREN ALANDA duruyor →
ters referans taraması gerekiyor. Eşleme `media/usage.py:31-60`'ta zaten var
(16 `(tablo, kolon, tür, etiket)` çifti); bu script onu import eder,
YENİDEN YAZMAZ.

`LIKE` KULLANILMAZ: `media/inventory.py:24-26` ölçümü — MariaDB
utf8mb4_unicode_ci'de `like '/files/%'` 4 baytlık karakterli satırlarda
eşleşmiyor, 23 dosyayı sessizce düşürüyordu. `LEFT()` ve `LOCATE()` kullanılır
(`usage._match_rows` da öyle yapıyor, usage.py:119).
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

import frappe

# ─────────────────────────────────────────────────────────────────────────
# HEDEFLER — TÜRETİLMİŞ, KARAR DEĞİL
# ─────────────────────────────────────────────────────────────────────────
# Kaynak: docs/reports/03-render-envanteri.md §3.8/§3.9 (gerçek CSS kutu
# ölçüleri ve @1x/@2x/@3x talepleri) + docs/reports/06-depolama-maliyet.md
# §1.2 (profil matrisi). İkisi de "öneridir, karar değildir" uyarısı taşıyor.
#
# Anahtar = media/usage.py'deki `kind` alanı (usage.py:31-60). Elle yeni
# anahtar EKLEMEYİN — `usage.py` kaynak listesi genişlerse buraya da eklenir,
# yoksa o slot "hedefi yok" olarak raporlanır (sessizce uyumlu SAYILMAZ).
SLOT_TARGETS: dict[str, dict] = {
	"listing_main": {
		"min_source_width": 2400,   # product-zoom (06 §1.2)
		"aspect": 1.0,              # 1:1 — ProductImageGallery aspect-square
		"note": "PD ana 512px, lightbox 636px, zoom profili 2400px ister",
	},
	"listing_gallery": {
		"min_source_width": 2400,
		"aspect": 1.0,
		"note": "aynı galeri bileşeni",
	},
	"variant_main": {
		"min_source_width": 640,    # product-card; gerçek kutu ÖLÇÜLEMEDİ
		"aspect": 1.0,
		"note": "render kutusu ölçülemedi (00-upload-slot-envanteri Tablo A) — alt sınır",
	},
	"variant_gallery": {
		"min_source_width": 640,
		"aspect": 1.0,
		"note": "JSON dizi alanı; render kutusu ölçülemedi",
	},
	"seller_gallery": {
		"min_source_width": 640,
		"aspect": 1.0,
		"note": "276x276 lg kutu, object-cover → kare değilse KIRPILIR, uyarı yok",
	},
	"seller_logo": {
		"min_source_width": 256,    # logo-square (06 §1.2)
		"aspect": None,             # object-contain → serbest
		"note": "120px kutu, object-contain",
	},
	"storefront": {
		"min_source_width": 1920,   # company-cover
		"aspect": None,             # ÇÖZÜLEMEZ — 6,7:1 … 3:1 arası değişken
		"unresolvable_aspect": True,
		"note": "slayt 180/220/320/400px yükseklikte → tek görselle karşılanamaz (§7-B2)",
	},
	# Video slotları: piksel ölçütü uygulanmaz (transcode ayrı iş, media/transcode.py)
	"listing_video": {"min_source_width": None, "aspect": None, "note": "video — kapsam dışı"},
	# Sipariş kopyaları: C sınıfı, hedef yok
	"cart_snapshot": {"min_source_width": None, "aspect": None, "note": "sistem kopyası — dokunulmaz"},
	"order_receipt": {"min_source_width": None, "aspect": None, "note": "dekont — EXCLUDED"},
}

# En-boy oranı toleransı. Kod tabanında oran kuralı HİÇ YOK — tek yazılı yer
# admin-panel OgImageUpload.vue:57 ve o da yalnız önizleme (00-upload-slot-
# envanteri §7-B2). Bu değer ÖNERİDİR.
ASPECT_TOLERANCE: float = 0.05

# Batch boyutu. Gerekçe aritmetik: api/media_admin.py:211 timeout=3600 s →
# dosya başına bütçe 3600/N. N=2000 (MAX_BATCH, media_admin.py:40) → 1,8 s/dosya
# ki 20 MP bir TIFF için gerçekçi değil. N=200 → 18 s/dosya.
# N aynı zamanda DURDURMA KRİTERİNİN ÇÖZÜNÜRLÜĞÜDÜR: run_batch batch ortasında
# abort ETMEZ (runner.py:68-93), dolayısıyla en kötü durumda N dosya işlenir.
BATCH_SIZE: int = 200

# Disk probe'unda alt boyut sınırı. Kapı 1 zaten 200 KB altını atıyor
# (media/presets.py:22 MIN_FILE_SIZE) — altını okumak boşa I/O.
PROBE_MIN_BYTES: int = 200 * 1024

# Sınıflar — docs/plans/migration.md §3
CLASS_A = "A_otomatik"          # mevcut run_batch ile düzelir
CLASS_A_PRIME = "A_kapi_disi"   # düzeltilebilir ama MEVCUT KODLA DEĞİL
CLASS_B = "B_satici_yukler"     # piksel üretilemez → satıcı eylemi
CLASS_C = "C_yok_sayilir"       # kapsam dışı
CLASS_OK = "UYUMLU"

REASONS: tuple[str, ...] = (
	# C
	"excluded_doctype", "sensitive_reverse_ref", "sensitive_content_twin",
	"trashed", "too_small", "unsupported_format", "animated", "no_target",
	# B
	"resolution_below_target", "ceiling_loss_2400", "aspect_mismatch",
	"unresolvable_aspect", "unreadable", "zero_bytes", "file_missing",
	# A
	"over_pixel_ceiling", "cmyk_outside_gate", "ext_content_mismatch",
)


# ─────────────────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────────────────


def _mb(b: float) -> float:
	return round(b / 1024 / 1024, 2)


def _excluded_placeholders() -> tuple[str, tuple[str, ...]]:
	"""`presets.EXCLUDED_DOCTYPES` için SQL yer tutucusu + parametreler.

	Liste elle KOPYALANMIYOR: `media/presets.py:44-53` tek kaynak. Kopyalansaydı
	yeni bir hassas doctype eklendiğinde bu script onu kapsam dışı saymayı
	unuturdu (aynı desen scripts/media_stats.py:137-147'de de var).
	"""
	from tradehub_core.media.presets import EXCLUDED_DOCTYPES

	return ", ".join(["%s"] * len(EXCLUDED_DOCTYPES)), tuple(EXCLUDED_DOCTYPES)


def _max_dim_ceiling() -> int:
	"""Bugünkü piksel tavanı — presets'ten OKUNUR, sabit yazılmaz."""
	from tradehub_core.media.presets import DEFAULT_PRESET, PRESETS

	return PRESETS[DEFAULT_PRESET]["max_dim"]


def _live_path(file_url: str) -> str | None:
	"""Diskteki mutlak yol. `media/trash.py:56-62` path-traversal korumalı; hata
	fırlatırsa None döner (yolu geçersiz dosya probe edilmez)."""
	from tradehub_core.media import trash

	try:
		return trash._live_path(file_url)
	except Exception:
		return None


# ─────────────────────────────────────────────────────────────────────────
# BÖLÜM 1 — ADAY KÜME (SQL)
# ─────────────────────────────────────────────────────────────────────────


def candidates() -> list[dict]:
	"""Backfill'in bakacağı TEKİLLEŞTİRİLMİŞ public küme.

	Filtreler `media/inventory.py:58-89` `_base_query()` ile birebir aynı üç
	katman: (1) `is_private=0` + `/files/` öneki, (2) `EXCLUDED_DOCTYPES`'a
	bağlı adresler dışlanır, (3) hassas bir belgeyle aynı `content_hash`'e
	sahip adresler dışlanır (ölçüm: 44 dosya, 6'sı panelde listeliydi,
	biri KYC kimlik belgesi — inventory.py:71-75).

	`inventory._base_query()` frappe.qb ile aynı işi yapıyor; burada ham SQL
	kullanıldı çünkü `th_media_state` ve `content_hash` gibi ek alanlar tek
	geçişte gerekiyor ve sonuç JSON'a yazılacak. Filtre MANTIĞI kopyalanmadı —
	`EXCLUDED_DOCTYPES` `presets`'ten okunuyor.
	"""
	ph, params = _excluded_placeholders()
	sql = f"""
	select
	  f.file_url,
	  max(f.file_size)                     as file_size,
	  count(*)                             as record_count,
	  max(coalesce(f.th_optimized_at,''))  as th_optimized_at,
	  max(coalesce(f.th_original_size,0))  as th_original_size,
	  max(coalesce(f.th_media_state,''))   as th_media_state,
	  max(coalesce(f.th_media_width,0))    as th_media_width,
	  max(coalesce(f.th_media_height,0))   as th_media_height,
	  min(f.name)                          as rep_name,
	  max(coalesce(f.content_hash,''))     as content_hash
	from tabFile f
	where f.is_folder = 0
	  and f.is_private = 0
	  and left(f.file_url, 7) = '/files/'
	  and f.file_url not in (
	        select x.file_url from tabFile x
	        where x.attached_to_doctype in ({ph}) and x.file_url is not null)
	  and (f.content_hash is null or f.content_hash = '' or f.content_hash not in (
	        select y.content_hash from tabFile y
	        where y.content_hash is not null and y.content_hash <> ''
	          and (y.is_private = 1 or y.attached_to_doctype in ({ph}))))
	group by f.file_url
	order by max(f.file_size) desc
	"""
	return frappe.db.sql(sql, params + params, as_dict=True)


def dimension_coverage() -> dict:
	"""`th_media_width` dolu olan adres oranı — disk geçişi gerekli mi.

	Sütunlar TEMBEL doldurulur: yalnız `metadata.ensure_dimensions()` bir dosya
	için çağrıldığında (media/metadata.py:159-196). Kapsam düşükse (beklenen)
	MP ölçümü ZORUNLU olarak diske iner.
	"""
	ph, params = _excluded_placeholders()
	row = frappe.db.sql(f"""
	  select count(*) as adres,
	         sum(case when w > 0 then 1 else 0 end) as dolu
	  from (
	    select f.file_url, max(coalesce(f.th_media_width,0)) as w
	    from tabFile f
	    where f.is_folder=0 and f.is_private=0 and left(f.file_url,7)='/files/'
	      and f.file_url not in (
	            select x.file_url from tabFile x
	            where x.attached_to_doctype in ({ph}) and x.file_url is not null)
	    group by f.file_url) a
	""", params, as_dict=True)[0]
	adres = int(row["adres"] or 0)
	dolu = int(row["dolu"] or 0)
	return {
		"adres": adres,
		"dolu": dolu,
		"oran": round(dolu / adres, 4) if adres else 0.0,
		"karar": "SQL yeterli" if adres and dolu / adres > 0.95 else "DISK PROBE ZORUNLU",
		"kaynak": "media/metadata.py:159-196 (tembel doldurma)",
	}


# ─────────────────────────────────────────────────────────────────────────
# BÖLÜM 2 — SLOT ATAMASI (ters referans)
# ─────────────────────────────────────────────────────────────────────────


def slot_map(urls: list[str], deep: bool = False) -> dict[str, list[str]]:
	"""`{file_url: [slot_kind, ...]}` — dosyayı GÖSTEREN alanlardan türetilir.

	`usage._match_rows` ve `usage._urls_in` YENİDEN YAZILMADI, import edildi:
	orada JSON kaçış varyantı (`_search_variants`, usage.py:71-79), 400'lük
	chunk'lama (usage.py:64) ve `LOCATE` (LIKE değil) kuralı zaten çözülmüş.

	Bir dosya BİRDEN ÇOK slotta olabilir (aynı görsel hem ana hem galeri) —
	bu yüzden liste döner, tek değer değil.

	Ölçülmüş maliyet (usage.py:295-296, 50 dosya):
	    CANLI + SİPARİŞ →   116 ms  (10 alan)
	    GEÇMİŞ          → 3.546 ms  (Version 934, Deleted 2.018, Error Log 552)
	`deep=True` geçmişi de tarar; slot ataması için GEREKMEZ (geçmiş bir slot
	değil), yalnız "hiç referansı yok mu" sorusunu ayırt etmek için.
	"""
	from tradehub_core.media import usage

	groups = [usage.LIVE_SOURCES, usage.ORDER_SOURCES]
	if deep:
		groups.append(usage.HISTORY_SOURCES)

	wanted = {u for u in urls if u}
	out: dict[str, list[str]] = defaultdict(list)
	for group in groups:
		for table, column, kind, _label in group:
			for row in usage._match_rows(table, column, list(wanted)):
				for u in usage._urls_in(row.get("_val"), wanted):
					if kind not in out[u]:
						out[u].append(kind)
	return dict(out)


def sensitive_reverse_refs(urls: list[str]) -> set[str]:
	"""`EXCLUDED_MEDIA_FIELDS` ters referans taraması — C sınıfı için.

	Neden gerekli: bazı hassas belgeler `File.attached_to_doctype` set
	EDİLMEDEN yükleniyor; yalnız EXCLUDED bir doctype'ın kendi alanından string
	olarak referanslanıyor. Canlı DB'de ölçülmüş: `Seller Application.
	identity_document` 144 dosya, `Seller Certification.document` 2 dosya
	(media/presets.py:56-64). `attached_to_doctype` kontrolü TEK BAŞINA bu 146
	PII belgesini yakalamıyor.

	⚠️ BU HARİTA EKSİK. `presets.py:70-76` KYB'nin yalnız 2 alanını sayıyor
	(`identity_document`, `bank_account_document`); `imza_sirkuleri`,
	`ticaret_sicil_gazetesi`, `faaliyet_belgesi`, `vergi_levhasi` YOK
	(00-upload-slot-envanteri.md §7-B5). Bu script eksik haritayı OLDUĞU GİBİ
	kullanır ve eksiği rapora yazar — haritayı burada elle tamamlamak, tek
	doğruluk kaynağını ikiye ayırırdı.
	"""
	from tradehub_core.media.presets import EXCLUDED_MEDIA_FIELDS

	wanted = {u for u in urls if u}
	if not wanted:
		return set()

	hits: set[str] = set()
	for doctype, fields in EXCLUDED_MEDIA_FIELDS.items():
		table = f"tab{doctype}"
		try:
			cols = set(frappe.db.get_table_columns(doctype))
		except Exception:
			continue
		for field in fields:
			if field not in cols:
				continue
			rows = frappe.db.sql(
				f"select distinct `{field}` as u from `{table}` "  # noqa: S608 — ad EXCLUDED_MEDIA_FIELDS'ten
				f"where `{field}` is not null and `{field}` <> ''",
				as_dict=True,
			)
			for r in rows:
				if r["u"] in wanted:
					hits.add(r["u"])
	return hits


# ─────────────────────────────────────────────────────────────────────────
# BÖLÜM 3 — SINIFLANDIRMA (docs/plans/migration.md §3.4 karar ağacı)
# ─────────────────────────────────────────────────────────────────────────


def _target_for(slots: list[str]) -> dict | None:
	"""Birden çok slottaki dosya için EN SIKI hedef kazanır.

	Gerekçe: aynı görsel hem `listing_gallery` (2400 px) hem `variant_main`
	(640 px) olarak kullanılıyorsa, 640'ı karşılaması yetmez — galeri onu
	bulanık gösterir. En yüksek `min_source_width` bağlayıcıdır.
	"""
	hedefler = [SLOT_TARGETS[s] for s in slots if s in SLOT_TARGETS]
	hedefler = [h for h in hedefler if h.get("min_source_width")]
	if not hedefler:
		return None
	return max(hedefler, key=lambda h: h["min_source_width"])


def classify(row: dict, slots: list[str], *, sensitive: bool, probe=None) -> dict:
	"""Tek dosya için sınıf + sebep. Karar ağacı: migration.md §3.4.

	`probe` verilmezse yalnız SQL'den bilinen alanlarla karar verilir ve
	piksel/format ölçütleri "bilinmiyor" olarak işaretlenir.

	Kapı kararı YENİDEN YAZILMADI: `gates.check_before` çağrılıyor (gates.py:42).
	O fonksiyon `import frappe` içermeyen saf bir fonksiyondur (gates.py:1).
	"""
	from tradehub_core.media import gates, presets, states
	from tradehub_core.media.pipeline import SUPPORTED_FORMATS

	url = row["file_url"]
	boyut = int(row.get("file_size") or 0)
	damga = (row.get("th_optimized_at") or "").strip()
	durum = (row.get("th_media_state") or "").strip()
	tavan = _max_dim_ceiling()

	def sonuc(sinif: str, sebep: str, **ek) -> dict:
		return {"file_url": url, "rep_name": row.get("rep_name"), "file_size": boyut,
		        "slots": slots, "class": sinif, "reason": sebep,
		        "th_optimized_at": damga or None, **ek}

	# ── C: kapsam dışı ────────────────────────────────────────────────
	if sensitive:
		return sonuc(CLASS_C, "sensitive_reverse_ref")
	if durum == states.STATE_TRASHED:
		return sonuc(CLASS_C, "trashed")
	if not slots:
		# Hiçbir kayıtlı alanda geçmiyor. DİKKAT: bu "kullanılmıyor" DEMEK
		# DEĞİL — usage.py 23 alanın yalnız 16'sını tanıyor (usage.py:8 vs
		# :31-60). Eksik olanlar 00-upload-slot-envanteri.md §7-B6'da listeli.
		return sonuc(CLASS_C, "no_target", target=None)

	hedef = _target_for(slots)
	if hedef is None:
		return sonuc(CLASS_C, "no_target", target=None)

	# ── probe yoksa burada dururuz ─────────────────────────────────────
	if probe is None:
		return sonuc("BILINMIYOR", "probe_yok", target=hedef["min_source_width"])

	if not probe.readable:
		return sonuc(CLASS_B, "unreadable", target=hedef["min_source_width"])
	if boyut == 0:
		return sonuc(CLASS_B, "zero_bytes", target=hedef["min_source_width"])

	# ── Kapıların KENDİ kararı (gates.py:42-74) ────────────────────────
	kapi = gates.check_before(
		file_size=boyut,
		probe=probe,
		optimized_at=damga or None,
		max_dim=tavan,
		min_file_size=presets.MIN_FILE_SIZE,
	)

	if probe.fmt not in SUPPORTED_FORMATS:
		return sonuc(CLASS_C, "unsupported_format", fmt=probe.fmt,
		             target=hedef["min_source_width"])
	if probe.animated:
		return sonuc(CLASS_C, "animated", target=hedef["min_source_width"])

	genislik = max(probe.width, probe.height)
	gerekli = hedef["min_source_width"]

	# ── B2: 2000 px tavanı yüzünden KALICI kayıp (migration.md §2.5) ───
	# Damgalı + tavanın altında + hedef tavanın üstünde + arşivde kopya yok
	# → 2400 px bir daha üretilemez.
	if damga and genislik <= tavan < gerekli:
		from tradehub_core.media import archive

		try:
			arsivde = archive.exists(url)
		except Exception:
			arsivde = False
		if not arsivde:
			return sonuc(CLASS_B, "ceiling_loss_2400", width=probe.width,
			             height=probe.height, target=gerekli, archived=False)
		# Arşivde duruyor → kurtarılabilir; A' olarak işaretlenir (restore + yeni tavan)
		return sonuc(CLASS_A_PRIME, "ceiling_loss_2400", width=probe.width,
		             height=probe.height, target=gerekli, archived=True)

	# ── B1: yetersiz çözünürlük (upscale YOK — engine.py:117) ──────────
	if genislik < gerekli:
		return sonuc(CLASS_B, "resolution_below_target", width=probe.width,
		             height=probe.height, target=gerekli)

	# ── B4 / B3: oran ─────────────────────────────────────────────────
	if hedef.get("unresolvable_aspect"):
		return sonuc(CLASS_B, "unresolvable_aspect", width=probe.width,
		             height=probe.height, target=gerekli)
	if hedef.get("aspect") and probe.height:
		oran = probe.width / probe.height
		sapma = abs(oran - hedef["aspect"]) / hedef["aspect"]
		if sapma > ASPECT_TOLERANCE:
			return sonuc(CLASS_B, "aspect_mismatch", width=probe.width,
			             height=probe.height, aspect=round(oran, 3),
			             target_aspect=hedef["aspect"], target=gerekli)

	# ── A: Kapı 4'ü geçen = piksel tavanı aşan ────────────────────────
	if kapi.passed:
		return sonuc(CLASS_A, "over_pixel_ceiling", width=probe.width,
		             height=probe.height, target=gerekli, ceiling=tavan)

	# ── A': düzeltilebilir ama MEVCUT KODLA DEĞİL ─────────────────────
	# CMYK: engine.py:121 `convert("RGB")` YALNIZ 6 kapıyı da geçen dosyada
	# çalışıyor. Kapı 4'e takılan CMYK bir JPEG tarayıcıya CMYK olarak gider.
	# `Probe`'da `mode` alanı YOK (engine.py:53-66) → mode ayrıca okunuyor.
	if (probe_mode := getattr(probe, "_mode", None)) in ("CMYK", "YCCK"):
		return sonuc(CLASS_A_PRIME, "cmyk_outside_gate", mode=probe_mode,
		             width=probe.width, height=probe.height, target=gerekli,
		             gate_reason=kapi.reason)

	if kapi.reason == "too_small":
		return sonuc(CLASS_C, "too_small", width=probe.width, height=probe.height)

	return sonuc(CLASS_OK, kapi.reason or "compliant", width=probe.width,
	             height=probe.height, target=gerekli)


# ─────────────────────────────────────────────────────────────────────────
# BÖLÜM 4 — DİSK GEÇİŞİ (probe)
# ─────────────────────────────────────────────────────────────────────────


class _ProbeWithMode:
	"""`engine.Probe`'u sarıp `_mode` (renk uzayı) ekler.

	`engine.Probe` frozen bir dataclass ve `mode` alanı YOK (engine.py:53-66) —
	motor CMYK'yı bilmiyor. Motoru DEĞİŞTİRMEK yerine burada sarmalanıyor;
	`gates.check_before` sarmalayıcıyı da kabul eder (yalnız `readable`, `fmt`,
	`animated`, `max_dim` okuyor).
	"""

	__slots__ = ("_p", "_mode")

	def __init__(self, p, mode: str):
		self._p = p
		self._mode = mode

	def __getattr__(self, name):
		# `_p` / `_mode` `__slots__`'ta olduğu için normalde buraya düşmez;
		# guard yalnız sonsuz özyinelemeyi (unpickle gibi durumlar) keser.
		if name in ("_p", "_mode"):
			raise AttributeError(name)
		return getattr(self._p, name)


def _probe_file(file_url: str, *, sniff_content: bool = True) -> tuple[object | None, str]:
	"""Dosyayı diskten OKU (rb) ve künyesini çıkar. Yazma yok.

	Dönüş: (probe|None, durum). `durum` ∈ {"ok", "file_missing", "bad_path",
	"read_error", "ext_content_mismatch"}.

	`engine.probe` (engine.py:79-93) ve `upload_policy.sniff` (:198-211) YENİDEN
	YAZILMADI, import edildi. `engine.optimize` ÇAĞRILMAZ.
	"""
	from tradehub_core.media import engine

	yol = _live_path(file_url)
	if yol is None:
		return None, "bad_path"
	if not os.path.isfile(yol):
		return None, "file_missing"

	try:
		with open(yol, "rb") as fh:
			icerik = fh.read()
	except OSError:
		return None, "read_error"

	p = engine.probe(icerik)

	# Renk uzayı — Probe'da yok, PIL'den ayrıca okunuyor.
	mode = ""
	if p.readable:
		try:
			import io

			from PIL import Image

			with Image.open(io.BytesIO(icerik)) as im:
				mode = im.mode or ""
		except Exception:
			mode = ""

	durum = "ok"
	if sniff_content:
		from tradehub_core.media import upload_policy

		uzanti = upload_policy.extension_of(os.path.basename(file_url))
		gercek = upload_policy.sniff(icerik)
		if gercek and not upload_policy._uyumlu(uzanti, gercek):
			durum = "ext_content_mismatch"

	return _ProbeWithMode(p, mode), durum


# ─────────────────────────────────────────────────────────────────────────
# BÖLÜM 5 — PLAN
# ─────────────────────────────────────────────────────────────────────────


def slot_compliance(rows: list[dict], slots: dict[str, list[str]],
                    sensitive: set[str], probes: dict) -> dict:
	"""Slot × sınıf dağılımı — migration.md §2 çıktısı."""
	dagilim: dict[str, Counter] = defaultdict(Counter)
	sebepler: Counter = Counter()
	kayitlar: list[dict] = []

	for row in rows:
		url = row["file_url"]
		s = slots.get(url, [])
		k = classify(row, s, sensitive=(url in sensitive), probe=probes.get(url))
		kayitlar.append(k)
		sebepler[k["reason"]] += 1
		for slot in (s or ["(slotsuz)"]):
			dagilim[slot][k["class"]] += 1

	return {
		"per_slot": {k: dict(v) for k, v in dagilim.items()},
		"reasons": dict(sebepler.most_common()),
		"records": kayitlar,
		"totals": dict(Counter(k["class"] for k in kayitlar)),
	}


def archive_growth(kayitlar: list[dict]) -> dict:
	"""Arşivin geçici şişmesi — A sınıfı dosyaların ORİJİNAL bayt toplamı.

	Mekanizma: `archive.store` her optimize edilen dosyanın orijinalini
	`private/image_originals/`'a kopyalıyor (runner.py:248; sıra kritik — arşiv
	başarısızsa dosyaya dokunulmuyor). `archive.py:11`: "Purge sonrası nihai
	kazanç gelir; o güne kadar disk geçici olarak şişer."

	Şişme penceresi = `presets.ARCHIVE_RETENTION_DAYS` (presets.py:38).
	`archive.store` üzerine YAZMAZ (archive.py:73-74) → ikinci koşu arşivi
	ikiye katlamaz, ama `purge_expired` `mtime` bazlı (archive.py:131) olduğu
	için pencere İLK yazma anından sayılır.

	NET KAZANÇ HESAPLANMAZ: yeni bayt ancak `engine.optimize` çalıştırılınca
	bilinir ve bu script optimize ÇAĞIRMAZ. Ölçümü için dry-run: migration.md §10-D1.
	"""
	from tradehub_core.media.presets import ARCHIVE_RETENTION_DAYS

	a = [k for k in kayitlar if k["class"] == CLASS_A]
	bayt = sum(int(k.get("file_size") or 0) for k in a)
	return {
		"a_sinifi_dosya": len(a),
		"arsiv_bayt": bayt,
		"arsiv_mb": _mb(bayt),
		"pencere_gun": ARCHIVE_RETENTION_DAYS,
		"net_kazanc": "HESAPLANMADI — dry-run gerekir (migration.md §10-D1)",
		"not": "Diskte yer var mı BİLİNMİYOR: backup.py:11'deki 382 GB 2026-08-13 tarihli. §10-D4",
	}


def batch_plan(kayitlar: list[dict], n: int = BATCH_SIZE) -> dict:
	"""A sınıfını `n`'lik batch'lere böl. ENQUEUE ETMEZ, liste üretir.

	Sıralama: boyuta göre azalan. Gerekçe `inventory.pending_file_names`
	docstring'i (inventory.py:436-438): "kazancın çoğu ilk birkaç yüz dosyadan
	gelir". Böylece ilk batch en yüksek getiriyi verir ve durdurma kriteri
	tetiklenirse en değerli kısım zaten yapılmış olur.
	"""
	a = sorted(
		[k for k in kayitlar if k["class"] == CLASS_A],
		key=lambda k: int(k.get("file_size") or 0),
		reverse=True,
	)
	batches = []
	for i in range(0, len(a), n):
		dilim = a[i:i + n]
		batches.append({
			"batch": i // n + 1,
			"count": len(dilim),
			"bytes": sum(int(x.get("file_size") or 0) for x in dilim),
			"file_names": [x["rep_name"] for x in dilim if x.get("rep_name")],
		})
	return {
		"batch_size": n,
		"batch_count": len(batches),
		"total_files": len(a),
		"per_file_time_budget_sec": round(3600 / n, 2),
		"timeout_sec": 3600,
		"kaynak": "timeout api/media_admin.py:211; MAX_BATCH=2000 api/media_admin.py:40",
		"batches": batches,
	}


def seller_notice(kayitlar: list[dict]) -> dict:
	"""B sınıfı dosyaların mağaza bazında dağılımı — bildirim listesi.

	Sahiplik `ownership.store_of` ile çözülür (media/ownership.py:37-45);
	ölçüm: 2.839/2.839 (%100) dosyanın yükleyeni bir mağazaya çözülebiliyor
	(ownership.py:6).

	⚠️ Bu liste `LIVE_SOURCES` genişletilmeden YAYINA ALINMAZ: 23 alanın yalnız
	16'sı tanınıyor (usage.py:8 vs :31-60), tanınmayan alanda geçen dosya
	"slotsuz" görünüp C sınıfına düşer ve satıcıya HİÇ bildirilmez
	(migration.md §2.3, R4).
	"""
	from tradehub_core.media import ownership

	b = [k for k in kayitlar if k["class"] == CLASS_B]
	per_store: dict[str, Counter] = defaultdict(Counter)
	cozulemeyen = 0

	sahipler = _owner_map([k["file_url"] for k in b])
	for k in b:
		magaza = None
		for kullanici in sahipler.get(k["file_url"], ()):
			try:
				magaza = ownership.store_of(kullanici)
			except Exception:
				magaza = None
			if magaza:
				break
		if not magaza:
			cozulemeyen += 1
			continue
		per_store[magaza][k["reason"]] += 1

	return {
		"b_sinifi_dosya": len(b),
		"etkilenen_magaza": len(per_store),
		"magaza_cozulemeyen": cozulemeyen,
		"per_store": {m: dict(c) for m, c in sorted(
			per_store.items(), key=lambda kv: -sum(kv[1].values()))},
		"onkosul": "LIVE_SOURCES 23 alanı kapsamadan yayına alınmaz (migration.md §9.1 Ö5)",
	}


def _owner_map(urls: list[str]) -> dict[str, tuple[str, ...]]:
	"""`{file_url: (owner, ...)}` — tek sorgu. `LIKE` yok."""
	if not urls:
		return {}
	out: dict[str, list[str]] = defaultdict(list)
	for i in range(0, len(urls), 400):
		dilim = urls[i:i + 400]
		ph = ", ".join(["%s"] * len(dilim))
		rows = frappe.db.sql(
			f"select file_url, owner from tabFile where file_url in ({ph})",
			tuple(dilim), as_dict=True,
		)
		for r in rows:
			if r["owner"] not in out[r["file_url"]]:
				out[r["file_url"]].append(r["owner"])
	return {k: tuple(v) for k, v in out.items()}


def stop_criterion_runbook(plan: dict) -> str:
	"""DURDURMA kriteri runbook'u — METİN döner, hiçbir şey çalıştırmaz.

	⚠️ `run_batch` batch ORTASINDA abort ETMEZ (runner.py:68-93): `errors`
	sayacı yalnız sonda `state="partial"` üretir (runner.py:98). Bu yüzden
	%2 eşiği ancak BATCH GRANÜLARİTESİNDE uygulanabilir ve en kötü durumda
	`batch_size` kadar dosya işlenmiş olur.
	"""
	n = plan["batch_size"]
	return f"""
╔══════════════════════════════════════════════════════════════════════════╗
║  DURDURMA KRİTERİ — HER BATCH'TEN SONRA, SONRAKİ ENQUEUE'DAN ÖNCE        ║
╚══════════════════════════════════════════════════════════════════════════╝

  hata_oranı = state["errors"] / state["processed"]        > %2  →  DUR

  `skipped` HATA DEĞİLDİR (runner.py:76-79). Kapı 4'e takılmak normal
  davranıştır ve backfill'in beklenen çoğunluğudur.

  ── batch arası kontrol ────────────────────────────────────────────────
  from tradehub_core.media import runner
  st = runner.read_progress(job_key)

  assert st["state"] in ("completed", "partial"), st["state"]

  oran = st["errors"] / max(st["processed"], 1)
  if oran > 0.02:
      raise SystemExit(f"DUR: hata %{{oran*100:.1f}} > %2 — kalan batch ENQUEUE EDİLMEZ")

  sr = st["skip_reasons"]
  if sr.get("file_missing", 0)  > st["processed"] * 0.01:
      raise SystemExit("DUR: file_missing > %1 → disk/DB ayrışması, media_stats Sorgu 7")
  if sr.get("decode_failed", 0) > st["processed"] * 0.01:
      raise SystemExit("DUR: decode_failed > %1 → Pillow / dosya bozulması")

  ── TTL TUZAĞI ────────────────────────────────────────────────────────
  İlerleme kaydı Redis'te ve TTL 3600 s (presets.py:28 PROGRESS_TTL).
  Okuma iş bitiminden 1 saat içinde yapılmalı. `state == "not_found"`
  (runner.py:29) bir "GEÇTİ" sonucu DEĞİLDİR — hata oranı BİLİNMİYOR
  demektir ve o durumda da DURULUR.

  ── KUYRUK ÖN KONTROLÜ (migration.md §5.3) ────────────────────────────
  Backfill ve CANLI video transcode AYNI kuyrukta: ikisi de queue="long"
  (api/media_admin.py:210 ve media/transcode.py:157). `long` kuyruğunu
  dinleyen TEK worker var (docker-compose.yml:170-175).
  → Enqueue öncesi `long` kuyruğunda bekleyen iş 0 olmalı (§10-D7).

  ── BATCH BOYUTU = DURDURMA ÇÖZÜNÜRLÜĞÜ ───────────────────────────────
  batch_size = {n}  →  eşik aşılsa bile en kötü durumda {n} dosya işlenmiş olur.
  dosya başına zaman bütçesi = 3600 / {n} = {round(3600 / n, 2)} s
"""


def enqueue_commands(plan: dict) -> str:
	"""Backfill'i BAŞLATAN komutlar — METİN. Bu script onları ÇALIŞTIRMAZ."""
	return """
╔══════════════════════════════════════════════════════════════════════════╗
║  BACKFILL BAŞLATMA — BU SCRIPT ÇALIŞTIRMAZ, OPERATÖR ELLE ÇALIŞTIRIR    ║
╚══════════════════════════════════════════════════════════════════════════╝

  ÖN KOŞULLAR (migration.md §9.1) — hepsi tamamlanmadan BAŞLAMAZ:
    Ö1  media_stats.py pii_exposure()      → 144+2 PII belgesi public'te mi
    Ö2  EXCLUDED_MEDIA_FIELDS 4 eksik KYB alanı tamamlandı mı (§7-B5)
    Ö3  media_stats.py reconcile()         → küme büyüklüğü
    Ö4  TÜREV PROFİL KARARI + gerekirse presets.py tavanı  ← R1, GERİ DÖNÜLEMEZ
    Ö6  disk boş alan tazelendi mi (§10-D4)

  1) KURU KOŞU — diske hiçbir şey yazılmaz (runner.py:61-63, :243-245)
     from tradehub_core.api import media_admin
     r = media_admin.start_image_optimization(
             file_names=BATCH["file_names"], scope="selected",
             preset="balanced", dry_run=1)

  2) İLERLEME
     from tradehub_core.media import runner
     runner.read_progress(r["job_key"])

  3) GERÇEK KOŞU — dry_run=0
     media_admin.start_image_optimization(
             file_names=BATCH["file_names"], scope="selected",
             preset="balanced", dry_run=0)

     ⚠️ scope="pending" KULLANMAYIN: api/media_admin.py:197-202 o yolda
        MAX_BATCH'i BİLEREK uygulamıyor → tüm küme TEK 3600 s'lik işe girer.

  4) GERİ ALMA (30 gün içinde — presets.py:38)
     media_admin.start_restore(scope="selected", file_names=[...])
     media_admin.start_restore(scope="optimized")     # filtreye uyan hepsi
     media_admin.restore_image(file_name)             # tek dosya, senkron

     ⚠️ th_optimized_at BOŞ olan dosya GERİ ALINAMAZ (runner.py:336-337) —
        timeout kesilmesinde oluşur (migration.md §4.2). Kontrol: §10-D2.

  5) ARŞİV PURGE'U DURDUR — backfill + 30 günlük doğrulama penceresi boyunca
     archive.purge_expired() çalışmamalı (archive.py:113-153). Hangi hook
     çağırıyor: §10-D6.
"""


# ─────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────


def main(
	*,
	sql: bool = True,
	probe_disk: bool = True,
	probe_limit: int = 0,
	probe_min_bytes: int = PROBE_MIN_BYTES,
	batch_size: int = BATCH_SIZE,
	deep_slots: bool = False,
	verbose: bool = True,
) -> dict:
	"""Planı üret, ekrana bas, (istenirse) JSON yaz. BACKFILL ÇALIŞTIRMAZ."""
	rapor: dict = {
		"site": getattr(frappe.local, "site", "?"),
		"planned_at": frappe.utils.now(),
		"config": {
			"batch_size": batch_size,
			"aspect_tolerance": ASPECT_TOLERANCE,
			"probe_min_bytes": probe_min_bytes,
			"pixel_ceiling": _max_dim_ceiling(),
			"ceiling_source": "media/presets.py:15 (balanced.max_dim)",
			"targets_source": "03-render-envanteri.md §3.8-3.9 + 06-depolama-maliyet.md §1.2 — ÖNERİ",
		},
		"slot_targets": SLOT_TARGETS,
	}

	rows: list[dict] = []
	slots: dict[str, list[str]] = {}
	sensitive: set[str] = set()
	probes: dict = {}

	if sql:
		if verbose:
			print("[1/5] Aday küme (tekilleştirilmiş public)…")
		rows = candidates()
		rapor["candidate_count"] = len(rows)
		rapor["candidate_bytes"] = sum(int(r.get("file_size") or 0) for r in rows)

		if verbose:
			print("[2/5] Çözünürlük kapsamı (SQL yeter mi)…")
		rapor["dimension_coverage"] = dimension_coverage()

		if verbose:
			print(f"[3/5] Slot ataması (ters referans, deep={deep_slots})…")
		slots = slot_map([r["file_url"] for r in rows], deep=deep_slots)
		rapor["slot_hit_count"] = len(slots)
		rapor["slot_coverage_note"] = (
			"usage.py 16 (tablo,kolon) çifti tanıyor; information_schema taraması "
			"23 alan buldu (usage.py:8) → 7 alan KAPSAM DIŞI, eksik olanlar "
			"00-upload-slot-envanteri.md §7-B6'da listeli"
		)

		if verbose:
			print("[4/5] Hassas belge ters referansı (EXCLUDED_MEDIA_FIELDS)…")
		sensitive = sensitive_reverse_refs([r["file_url"] for r in rows])
		rapor["sensitive_hit_count"] = len(sensitive)
		rapor["sensitive_map_gap"] = (
			"presets.py:70-76 KYB'nin yalnız 2 alanını sayıyor; imza_sirkuleri, "
			"ticaret_sicil_gazetesi, faaliyet_belgesi, vergi_levhasi YOK (§7-B5) → R5"
		)

	if probe_disk and rows:
		if verbose:
			print("[5/5] Disk probe (piksel / format / renk uzayı / uzantı-içerik)…")
		hedefler = [r for r in rows if int(r.get("file_size") or 0) >= probe_min_bytes]
		if probe_limit:
			hedefler = hedefler[:probe_limit]
		durumlar: Counter = Counter()
		for idx, r in enumerate(hedefler, start=1):
			p, durum = _probe_file(r["file_url"])
			durumlar[durum] += 1
			if p is not None:
				probes[r["file_url"]] = p
			if verbose and idx % 250 == 0:
				print(f"      … {idx}/{len(hedefler)}")
		rapor["probe"] = {
			"probed": len(hedefler),
			"skipped_below_min_bytes": len(rows) - len(hedefler),
			"statuses": dict(durumlar),
		}

	if rows:
		uyum = slot_compliance(rows, slots, sensitive, probes)
		kayitlar = uyum.pop("records")
		rapor["slot_compliance"] = uyum
		rapor["archive_growth"] = archive_growth(kayitlar)
		plan = batch_plan(kayitlar, n=batch_size)
		rapor["batch_plan"] = plan
		rapor["seller_notice"] = seller_notice(kayitlar)
		rapor["records"] = kayitlar

		if verbose:
			_print_summary(rapor)
			print(stop_criterion_runbook(plan))
			print(enqueue_commands(plan))

	hedef = os.environ.get("BACKFILL_PLAN_OUT")
	if hedef:
		with open(hedef, "w", encoding="utf-8") as fh:
			json.dump(rapor, fh, ensure_ascii=False, indent=2, default=str)
		print(f"\nJSON yazıldı: {hedef}")

	return rapor


def _print_summary(r: dict) -> None:
	"""migration.md tablolarına doğrudan kopyalanabilir özet."""
	print("\n" + "═" * 74)
	print(f"BACKFILL PLANI — {r.get('site')} — {r.get('planned_at')}")
	print("═" * 74)

	print(f"\nAday adres            : {r.get('candidate_count')}")
	print(f"Aday bayt             : {_mb(r.get('candidate_bytes') or 0)} MB")
	print(f"Piksel tavanı (kod)   : {r['config']['pixel_ceiling']} px  ← {r['config']['ceiling_source']}")

	dc = r.get("dimension_coverage") or {}
	print(f"\nÇözünürlük kapsamı    : {dc.get('dolu')}/{dc.get('adres')} "
	      f"(%{(dc.get('oran') or 0)*100:.1f}) → {dc.get('karar')}")

	pr = r.get("probe") or {}
	if pr:
		print(f"Probe edilen          : {pr.get('probed')}  "
		      f"(min bayt altı atlanan: {pr.get('skipped_below_min_bytes')})")
		for k, v in (pr.get("statuses") or {}).items():
			print(f"    {k:22s} {v}")

	sc = r.get("slot_compliance") or {}
	print("\n── SINIF TOPLAMLARI ─────────────────────────────────────────────")
	for k, v in sorted((sc.get("totals") or {}).items(), key=lambda kv: -kv[1]):
		print(f"    {k:16s} {v}")

	print("\n── SEBEP DAĞILIMI ───────────────────────────────────────────────")
	for k, v in (sc.get("reasons") or {}).items():
		print(f"    {k:26s} {v}")

	print("\n── SLOT × SINIF ─────────────────────────────────────────────────")
	for slot, d in (sc.get("per_slot") or {}).items():
		hedef = SLOT_TARGETS.get(slot, {}).get("min_source_width")
		print(f"    {slot:20s} hedef={hedef!s:>6s}  {d}")

	ag = r.get("archive_growth") or {}
	print("\n── ARŞİV ŞİŞMESİ (geçici) ───────────────────────────────────────")
	print(f"    A sınıfı dosya      : {ag.get('a_sinifi_dosya')}")
	print(f"    arşiv               : {ag.get('arsiv_mb')} MB  ({ag.get('pencere_gun')} gün)")
	print(f"    net kazanç          : {ag.get('net_kazanc')}")
	print(f"    {ag.get('not')}")

	bp = r.get("batch_plan") or {}
	print("\n── BATCH PLANI ──────────────────────────────────────────────────")
	print(f"    batch boyutu        : {bp.get('batch_size')}")
	print(f"    batch sayısı        : {bp.get('batch_count')}")
	print(f"    toplam dosya        : {bp.get('total_files')}")
	print(f"    dosya/zaman bütçesi : {bp.get('per_file_time_budget_sec')} s "
	      f"(timeout {bp.get('timeout_sec')} s)")

	sn = r.get("seller_notice") or {}
	print("\n── SATICI BİLDİRİMİ (B sınıfı) ──────────────────────────────────")
	print(f"    B sınıfı dosya      : {sn.get('b_sinifi_dosya')}")
	print(f"    etkilenen mağaza    : {sn.get('etkilenen_magaza')}")
	print(f"    mağazası çözülemeyen: {sn.get('magaza_cozulemeyen')}")
	print(f"    ÖN KOŞUL: {sn.get('onkosul')}")

	print("\n── KAPSAM UYARILARI ─────────────────────────────────────────────")
	print(f"    {r.get('slot_coverage_note')}")
	print(f"    {r.get('sensitive_map_gap')}")
	print("    Hedefler ÖNERİDİR, karar değil: " + r["config"]["targets_source"])
