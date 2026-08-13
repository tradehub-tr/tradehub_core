"""Medyanın veritabanındaki ayak izi — yedekle veritabanı örtüşüyor mu (TUR-131).

**Sorun.** Medya yedeği dosyaları ve `File` kayıtlarını taşıyor. Ama o kayıtlar
veritabanının BUGÜNKÜ yapısına göre yazıldı: başlık, alternatif metin, etiket,
durum, çöp damgası gibi alanları biz sonradan bir yamayla ekledik. Yedek başka
bir veritabanının üzerine açılırsa iki taraf ayrışabilir:

    yedek yeni, veritabanı eski   → beklenen sütun yok, alanlar sessizce düşer
    yedek eski, veritabanı yeni   → yeni alanlar boş gelir, kimse fark etmez

İkisi de sessiz. "Geri yükledim, çalışıyor gibi" deyip aylar sonra alternatif
metinlerin hiç dönmediğini görmek en kötü hâli.

**Çözüm.** Her yedek, alındığı andaki medya yapısının künyesini de saklar:
`File` tablosunun sütunları, medya adresi tutan tüm tablo/sütun çiftleri,
denetim tablosunun sütunları ve uygulanmış medya yamaları. Geri yükleme planı
bunu bugünkü yapıyla karşılaştırıp farkı ÖNCEDEN söyler.

**Neden tablo listesi elle değil.** Medya adresinin geçtiği yerler zaten
`usage.py` içinde tanımlı; buraya ikinci bir kopya yazmak, zamanla ayrışan iki
liste demekti. Yeni bir alan oraya eklendiğinde künye kendiliğinden büyür.
"""

from __future__ import annotations

import frappe

from tradehub_core.media import usage

# Künyesi tam çıkarılan tablolar: medya kayıtlarının kendisi ve denetim izi.
# Bunlarda TÜM sütunlar önemli, çünkü yedek bu tablolara satır yazıyor.
FULL_TABLES: tuple[str, ...] = ("tabFile", "tabAuthorization Decision Log")

# Medya yamaları — hedef veritabanında çalışmışlar mı. Çalışmadıysa `th_media_*`
# sütunları hiç yoktur ve geri yükleme o alanları yazamaz.
PATCH_MARKERS: tuple[str, ...] = ("media",)


def _columns(table: str) -> dict[str, str]:
	"""Tablonun sütunları ve tipleri — tablo yoksa boş.

	Tablo adı parametre olarak gidiyor, sorgu metnine gömülmüyor: adlar bizim
	sabit listelerimizden gelse de tablo adını metne eklemek kalıbı normalleştirir
	ve bir gün dışarıdan gelen bir adla aynı yoldan geçilir.

	Ad OLDUĞU GİBİ sorulur. `tab` öneki Frappe'nin doctype adını tabloya
	çevirme kuralı değil, tablonun gerçek adının parçası; kırpmak sessizce boş
	künye üretiyordu ve karşılaştırma her şeyi "uyumlu" sanıyordu.
	"""
	try:
		satirlar = frappe.db.sql(
			"""select column_name, column_type
				from information_schema.columns
				where table_schema = database() and table_name = %s""",
			(table,),
			as_dict=True,
		)
	except Exception:
		return {}
	# MariaDB sürümüne göre anahtar adı büyük/küçük harf değişebiliyor.
	return {
		(r.get("column_name") or r.get("COLUMN_NAME")): (r.get("column_type") or r.get("COLUMN_TYPE"))
		for r in satirlar
		if (r.get("column_name") or r.get("COLUMN_NAME"))
	}


def _media_sources() -> list[tuple[str, str, str]]:
	"""Medya adresi tutan tüm tablo/sütun çiftleri — tek kaynaktan."""
	out: list[tuple[str, str, str]] = []
	for kapsam, kaynak in (
		("live", usage.LIVE_SOURCES),
		("order", usage.ORDER_SOURCES),
		("history", usage.HISTORY_SOURCES),
	):
		for table, column, *_ in kaynak:
			out.append((kapsam, table, column))
	return out


def _media_patches() -> list[str]:
	try:
		hepsi = frappe.get_all("Patch Log", pluck="patch", limit_page_length=0)
	except Exception:
		return []
	return sorted(
		{p for p in hepsi if p and any(im in p.lower() for im in PATCH_MARKERS)}
	)


def capture() -> dict:
	"""Bugünkü medya yapısının künyesi."""
	tablolar: dict[str, dict] = {}
	for t in FULL_TABLES:
		sutunlar = _columns(t)
		tablolar[t] = {"exists": bool(sutunlar), "columns": sutunlar}

	# Adres tutan tablolarda YALNIZ ilgili sütun künyeye giriyor. Tamamını almak
	# künyeyi ürün şemasının kopyasına çevirirdi; buradaki soru "medya bağı
	# duruyor mu", "ürün tablosu ne kadar değişti" değil.
	baglar: list[dict] = []
	onbellek: dict[str, dict[str, str]] = {}
	for kapsam, table, column in _media_sources():
		if table not in onbellek:
			onbellek[table] = _columns(table)
		sutunlar = onbellek[table]
		baglar.append(
			{
				"scope": kapsam,
				"table": table,
				"column": column,
				"exists": column in sutunlar,
				"type": sutunlar.get(column, ""),
			}
		)

	from tradehub_core import __version__ as surum

	return {
		"captured": frappe.utils.now(),
		"site": frappe.local.site,
		"app_version": surum,
		"frappe_version": frappe.__version__,
		"tables": tablolar,
		"media_links": baglar,
		"patches": _media_patches(),
	}


def compare(kaydedilen: dict | None) -> dict:
	"""Yedekteki künye ile bugünkü yapı — fark ne.

	Yön önemli: "yedekte var, bugün yok" veri KAYBI riskidir (geri yükleme o
	alanı yazamaz). "Bugün var, yedekte yok" yalnız boş kalır. İkisi ayrı
	raporlanıyor ki uyarı gürültüye boğulmasın.
	"""
	if not kaydedilen:
		# Künye yamadan önce alınmış eski yedekler için. Sessizce "uyumlu"
		# demek yanlış olurdu: bilmiyoruz, bilmediğimizi söylüyoruz.
		return {"known": False, "ok": None, "reason": "Bu yedekte yapı künyesi yok."}

	# BOŞ KÜNYE "UYUMLU" SAYILMAZ. Künye alınırken sorgu sessizce boş dönerse
	# (bir kez oldu: tablo adı yanlış soruluyordu) iki taraf da boş çıkar ve
	# karşılaştırma hiçbir fark bulamayıp "her şey yolunda" derdi. Yapı
	# kontrolünün en tehlikeli hâli, çalışmadığı hâlde çalışıyor görünmesi.
	if not ((kaydedilen.get("tables") or {}).get("tabFile") or {}).get("columns"):
		return {
			"known": False,
			"ok": None,
			"reason": "Yedekteki yapı künyesi boş, karşılaştırma yapılamaz.",
		}

	simdi = capture()
	if not (simdi["tables"].get("tabFile") or {}).get("columns"):
		return {
			"known": False,
			"ok": None,
			"reason": "Bugünkü yapı okunamadı, karşılaştırma yapılamaz.",
		}

	eksik_sutun: list[str] = []
	yeni_sutun: list[str] = []
	tip_degisen: list[dict] = []
	eksik_tablo: list[str] = []

	for tablo, kayit in (kaydedilen.get("tables") or {}).items():
		bugun = (simdi["tables"].get(tablo) or {}).get("columns") or {}
		if not bugun:
			if kayit.get("exists"):
				eksik_tablo.append(tablo)
			continue
		eski = kayit.get("columns") or {}
		for ad, tur in eski.items():
			if ad not in bugun:
				eksik_sutun.append(f"{tablo}.{ad}")
			elif bugun[ad] != tur:
				tip_degisen.append({"column": f"{tablo}.{ad}", "was": tur, "now": bugun[ad]})
		for ad in bugun:
			if ad not in eski:
				yeni_sutun.append(f"{tablo}.{ad}")

	# Medya bağları: yedek alındığında var olan bir bağ bugün yoksa, o alandaki
	# kullanım bilgisi geri yüklenemez.
	simdiki_baglar = {(b["table"], b["column"]): b for b in simdi["media_links"]}
	kopan_bag: list[str] = []
	for b in kaydedilen.get("media_links") or []:
		if not b.get("exists"):
			continue
		bugun = simdiki_baglar.get((b["table"], b["column"]))
		if not bugun or not bugun.get("exists"):
			kopan_bag.append(f"{b['table']}.{b['column']}")

	eski_yamalar = set(kaydedilen.get("patches") or [])
	yeni_yamalar = set(simdi.get("patches") or [])
	eksik_yama = sorted(eski_yamalar - yeni_yamalar)

	sorunlu = bool(eksik_sutun or eksik_tablo or kopan_bag or eksik_yama)

	return {
		"known": True,
		"ok": not sorunlu,
		"captured": kaydedilen.get("captured"),
		"app_version_then": kaydedilen.get("app_version"),
		"app_version_now": simdi.get("app_version"),
		# Veri kaybı riski taşıyanlar
		"missing_columns": sorted(eksik_sutun),
		"missing_tables": sorted(eksik_tablo),
		"broken_links": sorted(kopan_bag),
		"missing_patches": eksik_yama,
		# Yalnız bilgi
		"new_columns": sorted(yeni_sutun),
		"type_changed": tip_degisen,
	}


def summary_lines(fark: dict) -> list[str]:
	"""Karşılaştırmanın okunabilir hâli — pakete ve rapora aynı metin gider."""
	if not fark.get("known"):
		return ["Yapı künyesi yok — bu yedek künye eklenmeden önce alınmış."]

	satirlar = [
		f"Yedeğin alındığı sürüm : {fark.get('app_version_then') or '—'}",
		f"Bugünkü sürüm          : {fark.get('app_version_now') or '—'}",
	]
	if fark.get("ok"):
		satirlar.append("Yapı uyumlu — yedekteki tüm alanların bugün karşılığı var.")
		if fark.get("new_columns"):
			satirlar.append(
				f"Bilgi: yedekten sonra {len(fark['new_columns'])} yeni sütun eklenmiş, "
				"bunlar boş gelecek."
			)
		return satirlar

	satirlar.append("DİKKAT — yapı örtüşmüyor:")
	for baslik, anahtar in (
		("Bugün olmayan sütun", "missing_columns"),
		("Bugün olmayan tablo", "missing_tables"),
		("Kopmuş medya bağı", "broken_links"),
		("Çalışmamış yama", "missing_patches"),
	):
		liste = fark.get(anahtar) or []
		if liste:
			satirlar.append(f"  {baslik} ({len(liste)}): {', '.join(liste[:12])}")
			if len(liste) > 12:
				satirlar.append(f"    … ve {len(liste) - 12} tane daha")
	satirlar.append("  Bu alanlar geri yüklenemez; önce veritabanını güncelleyin.")
	return satirlar
