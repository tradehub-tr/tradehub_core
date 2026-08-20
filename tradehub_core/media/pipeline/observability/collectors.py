"""K-1 — Periyodik TOPLAYICILAR: ölçüm noktalarının yazamadığı göstergeleri besle.

SORUN — tanımlı ama boş 3 gösterge
==================================
`instrument.py::TOPLAYICI_GEREKTIREN` üç göstergeyi açıkça "toplayıcı bekliyor"
diye işaretliyordu ve `metrik_kapsami()` `needs_collector` ile itiraf ediyordu:

  * `media_orphan_files`           — referanssız disk dosyası sayısı
  * `media_pii_field_coverage`     — EXCLUDED doctype alan-koruma kapsamı
  * `media_pii_unprotected_files`  — public katmanda duran hassas dosya sayısı

Bunlar çağrı yolunda ÜRETİLEMEZ (bir yükleme, bir öksüz dosya "üretmez"); bir
envanter/PII taramasının PERİYODİK ölçtüğü değerlerdir. `docs/observability/
media-alerts.yml`'deki üç kritik alarm (`MediaOrphanFilesGrowing`,
`MediaUnprotectedPiiFiles`, `MediaPiiFieldCoverageGap`) tam bu üç seriye
bağlıydı ve seriler hiç yazılmadığı için üç alarm da ÖLÜYDÜ.

DESEN — `delivery/rum.py::to_metrics` ile aynı
==============================================
Toplayıcı ikiye ayrılır ve ayrım BİLİNÇLİDİR:

  * SAF sınıflandırıcı (`classify_field_coverage`) — frappe'siz, diskten/DB'den
    okumaz, yalnız verilen veriyi say. Testi bench gerektirmez.
  * SAF yazıcılar (`set_orphan_files` / `set_pii_field_coverage` /
    `set_pii_unprotected_files`) — hazır sayıyı metriğe yazar; `registry`
    parametresi RUM köprüsündeki gibi testte sahte kayıt defteri enjekte
    ettirir.
  * IO toplayıcılar (`count_*` / `discover_media_fields`) — `import frappe`
    GEÇ yapılır; frappe/diskı burada, tek yerde, açıkça dokunulur.
  * `run_scan()` — zamanlayıcının çağıracağı tek giriş; IO'yu saf yazıcılara
    bağlar.

`import frappe` MODÜL BAŞINDA YOKTUR: saf çekirdek frappe'siz test edilebilsin.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# ── Sabitler ───────────────────────────────────────────────────────────

#: `presets.EXCLUDED_MEDIA_FIELDS` bakım notunun "dosya-tutan alan" saydığı
#: Frappe fieldtype'ları. `Data` DIŞARIDA: bir Data alanı (ör. `receipt_url`)
#: dosya URL'i taşıyabilir ama meta'dan "dosya alanı" olduğu ÇIKARILAMAZ;
#: bu yüzden Data alanlarının kapsamı ters-referans yoluyla
#: `count_unprotected_pii_files()` tarafından ölçülür, kapsam sayısıyla değil.
FILE_FIELDTYPES: Tuple[str, ...] = ("Attach", "Attach Image")


# ── Saf sınıflandırıcı ─────────────────────────────────────────────────


def classify_field_coverage(
	excluded_fields_map: Mapping[str, Sequence[str]],
	discovered_fields: Mapping[str, Sequence[str]],
) -> Dict[str, Any]:
	"""EXCLUDED doctype'ların dosya alanları haritada var mı — SAF, I/O yok.

	Args:
	    excluded_fields_map: `presets.EXCLUDED_MEDIA_FIELDS` — doctype → korunan
	        alan adları.
	    discovered_fields: doctype → o doctype'ta meta'dan bulunmuş
	        Attach/Attach Image alan adları (IO tarafı `discover_media_fields`).

	Döner: `{"mapped": int, "unmapped": int, "gaps": [(doctype, field), ...]}`.
	`unmapped > 0` bir AÇIKTIR: bir dosya-tutan alan koruma haritasının dışında
	kalmış demektir (`MediaPiiFieldCoverageGap` bu sayıya bağlı). `gaps` hangi
	alanın kaçtığını insan için sıralı verir.
	"""
	mapped = 0
	unmapped = 0
	gaps: List[Tuple[str, str]] = []
	for doctype in sorted(discovered_fields):
		haritali = set(excluded_fields_map.get(doctype, ()) or ())
		for field in discovered_fields[doctype]:
			if field in haritali:
				mapped += 1
			else:
				unmapped += 1
				gaps.append((doctype, field))
	return {"mapped": mapped, "unmapped": unmapped, "gaps": sorted(gaps)}


# ── Metrik nesneleri (geç içe aktarma) ─────────────────────────────────


def _metrikler(registry: Any = None) -> Dict[str, Any]:
	"""Yazılacak metrik nesneleri. `rum.py::_metrikler` ile aynı desen.

	`registry` verilmezse süreç kayıt defterindeki gerçek nesneler; verilirse
	(test) o defterden ada göre çözülür.
	"""
	from . import metrics as mm

	if registry is None:
		return {
			"orphan": mm.ORPHAN_FILES,
			"pii_coverage": mm.PII_FIELD_COVERAGE,
			"pii_unprotected": mm.PII_UNPROTECTED_FILES,
		}
	return {
		"orphan": registry.get("media_orphan_files"),
		"pii_coverage": registry.get("media_pii_field_coverage"),
		"pii_unprotected": registry.get("media_pii_unprotected_files"),
	}


# ── Saf yazıcılar ──────────────────────────────────────────────────────


def set_orphan_files(count: int, *, registry: Any = None) -> int:
	"""Referanssız disk dosyası sayısını gauge'a yaz; yazılan sayıyı döndür."""
	_metrikler(registry)["orphan"].set(float(count))
	return int(count)


def set_pii_field_coverage(coverage: Mapping[str, Any], *, registry: Any = None) -> Dict[str, int]:
	"""`classify_field_coverage` çıktısını `{status}` etiketli gauge'a yaz.

	İKİ seri de HER ZAMAN yazılır (`mapped` ve `unmapped`) — `unmapped` 0 olsa
	bile seri render edilir, çünkü "0 kaçak" ile "hiç ölçülmedi" panelde ayırt
	edilebilmeli; alarm (`unmapped > 0`) ancak seri VARSA sessiz kalabilir.
	"""
	m = _metrikler(registry)["pii_coverage"]
	mapped = int(coverage.get("mapped", 0))
	unmapped = int(coverage.get("unmapped", 0))
	m.set(float(mapped), status="mapped")
	m.set(float(unmapped), status="unmapped")
	return {"mapped": mapped, "unmapped": unmapped}


def set_pii_unprotected_files(count: int, *, registry: Any = None) -> int:
	"""Public katmanda duran hassas dosya sayısını gauge'a yaz."""
	_metrikler(registry)["pii_unprotected"].set(float(count))
	return int(count)


# ── IO toplayıcılar — `import frappe` GEÇ ──────────────────────────────


def count_orphan_files(*, min_age_days: Optional[int] = None) -> int:
	"""Diskte olup `tabFile`'da olmayan üretim öksüzlerinin sayısı. **frappe + disk.**

	`core/usage.find_disk_orphans()` üretim davranışını (sistem yolları muaf)
	yeniden kullanır — ikinci bir tarama yazmak, birinin düzelip diğerinin
	geride kalması demekti.
	"""
	from tradehub_core.media.pipeline.core import usage

	if min_age_days is None:
		rapor = usage.find_disk_orphans()
	else:
		rapor = usage.find_disk_orphans(min_age_days=min_age_days)
	return len(rapor.orphans)


def discover_media_fields(doctypes: Iterable[str]) -> Dict[str, Tuple[str, ...]]:
	"""Verilen doctype'ların Attach/Attach Image alanlarını meta'dan çıkar. **frappe.**

	Var olmayan doctype ATLANIR (ör. bir ortamda kurulu olmayan modül): eksik
	doctype bir tarama hatası değil, o kurulumun gerçeğidir.
	"""
	import frappe

	out: Dict[str, Tuple[str, ...]] = {}
	for dt in doctypes:
		if not frappe.db.exists("DocType", dt):
			continue
		meta = frappe.get_meta(dt)
		alanlar = tuple(
			df.fieldname for df in meta.fields if df.fieldtype in FILE_FIELDTYPES
		)
		if alanlar:
			out[dt] = alanlar
	return out


def count_unprotected_pii_files() -> int:
	"""Public (`is_private=0`) katmanda duran hassas dosya sayısı. **frappe DB.**

	İki bağımsız yoldan (`access_level._is_protected_pii` ile aynı mantık):

	  1. `attached_to_doctype` `presets.EXCLUDED_DOCTYPES` içinde olan public
	     `File` kayıtları.
	  2. TERS REFERANS: `presets.EXCLUDED_MEDIA_FIELDS` haritasındaki bir alanda
	     string olarak duran, karşılığı public bir `File` olan URL'ler
	     (`attached_to_doctype` boş yüklenmiş 146 kimlik belgesi bu yoldan
	     kaçıyordu — TUR-126 §4).

	Aynı fiziksel URL iki yoldan da görünse bir kez sayılır (küme). Hedef 0;
	`> 0` bir KVKK sızıntısıdır (`MediaUnprotectedPiiFiles`).
	"""
	import frappe

	from tradehub_core.media import presets

	public_urls: set = set()

	# 1. attached_to_doctype yolu
	ekli = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": ["in", list(presets.EXCLUDED_DOCTYPES)],
			"is_private": 0,
		},
		pluck="file_url",
	)
	public_urls.update(u for u in ekli if u)

	# 2. Ters referans yolu — harita alanlarında duran URL'ler
	for doctype, fields in presets.EXCLUDED_MEDIA_FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		for field in fields:
			if not meta.has_field(field):
				continue
			# Alan/doctype adları GÜVENİLİR sabit haritadan gelir (presets),
			# kullanıcı girdisi değil; yine de yalnız o alanı distinct çekeriz.
			satirlar = frappe.get_all(
				doctype,
				filters={field: ["is", "set"]},
				pluck=field,
			)
			for url in set(satirlar):
				if not url:
					continue
				if frappe.db.exists("File", {"file_url": url, "is_private": 0}):
					public_urls.add(url)

	return len(public_urls)


# ── Zamanlayıcı girişi ─────────────────────────────────────────────────


def _export_shard() -> Optional[str]:
	"""Bu (zamanlayıcı) sürecin kayıt defterini paylaşılan parçaya yaz.

	`/metrics` ucu ÇOK SÜREÇLİ toplar: her süreç kendi parçasını yazar, uç
	hepsini birleştirir (`exporter.merge`). Toplayıcı SCHEDULER sürecinde koşar
	ve web sürecinden ayrıdır; parça yazılmazsa ölçtüğü değerler `/metrics`e
	HİÇ ulaşmaz. Dizin çözümü `api/observability.shard_dir()` ile AYNIdır:
	`MEDIA_METRICS_DIR` ortam değişkeni, yoksa `<site>/private/media-metrics`.
	Hata YUTULMAZ değil ama iş düşürmez — çağıran `run_scan` metrikleri zaten
	yazdı; parça yazımı ikincil.
	"""
	from . import exporter

	yol = exporter.dizin()
	if not yol:
		import frappe

		yol = frappe.get_site_path("private", "media-metrics")
	return exporter.write_shard(hedef_dizin=yol)


def run_scan(*, registry: Any = None, export: bool = True) -> Dict[str, Any]:
	"""Periyodik toplayıcı — üç göstergeyi ölç, yaz ve parçayı dışa aktar.

	**frappe + disk.** `hooks.py` `scheduler_events` bunu çağırmalı (frekans
	önerisi raporda). Elle de koşturulabilir: `bench execute
	tradehub_core.media.pipeline.observability.collectors.run_scan`.

	`export` yalnız gerçek kayıt defterinde (registry=None) parça yazar; testte
	sahte kayıt defteri enjekte edildiğinde diske dokunmaz. Dönüş, ölçülen
	değerlerin künyesidir (tahmin değil).
	"""
	from tradehub_core.media import presets

	orphan = count_orphan_files()
	set_orphan_files(orphan, registry=registry)

	coverage = classify_field_coverage(
		presets.EXCLUDED_MEDIA_FIELDS, discover_media_fields(presets.EXCLUDED_DOCTYPES)
	)
	set_pii_field_coverage(coverage, registry=registry)

	unprotected = count_unprotected_pii_files()
	set_pii_unprotected_files(unprotected, registry=registry)

	shard = None
	if export and registry is None:
		shard = _export_shard()

	return {
		"orphan_files": orphan,
		"pii_field_coverage": {"mapped": coverage["mapped"], "unmapped": coverage["unmapped"]},
		"pii_coverage_gaps": coverage["gaps"],
		"pii_unprotected_files": unprotected,
		"shard": shard,
	}


__all__ = [
	"FILE_FIELDTYPES",
	"classify_field_coverage",
	"set_orphan_files",
	"set_pii_field_coverage",
	"set_pii_unprotected_files",
	"count_orphan_files",
	"discover_media_fields",
	"count_unprotected_pii_files",
	"run_scan",
]
