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

# F-25: Medya motorunun kendi tabloları. Yedek bunlara satır YAZMIYOR — türetilmiş
# durum (varlık kaydı, üretilen boyutlar, kırpma niyeti, SEO ezmesi, kullanım
# eşlemesi) yalnız `File` ve dosyalardan yeniden üretilebilir sayılıyor.
#
# Buna rağmen künyeye giriyorlar, çünkü künyenin iddiası "medyanın veritabanındaki
# ayak izi". Motor tabloları o ayak izinin bugün en büyük parçası ve künye onları
# hiç görmüyordu: motorun kurulu OLMADIĞI bir veritabanına geri yükleme yapılırsa
# `File` satırları dönüyor, ama üzerlerine bağlı hiçbir motor kaydı dönmüyor ve
# karşılaştırma "yapı uyumlu" diyordu. Sessiz olan buydu.
#
# `FULL_TABLES`'a KOYULMUYORLAR: oradaki sözleşme "yedek bu tablolara satır yazar"
# ve bir sütunun kaybı doğrudan veri kaybıdır. Burada kayıp zaten peşinen kabul
# edilmiş; rapor edilen şey kapsam, risk değil.
DERIVED_TABLES: tuple[str, ...] = (
	"tabMedia Asset",
	"tabMedia Rendition",
	"tabMedia Metadata Vault",
	"tabMedia Crop Intent",
	"tabMedia Crop Override",
	"tabMedia SEO Override",
	"tabMedia Usage",
	"tabMedia Version",
	"tabMedia Category Assignment",
	"tabMedia Folder Item",
	"tabMedia Processing Job",
)

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


def _row_count(table: str) -> int | None:
	"""Tablodaki satır sayısı — tablo yoksa `None` (0 ile karıştırılmamalı).

	"Motor tablosu yok" ile "motor tablosu boş" farklı iki dünya: birincisinde
	geri yükleme hedefinde motor hiç kurulu değil, ikincisinde kurulu ama veri
	yok. Künye ikisini ayırt edemezse rapor da edemez.
	"""
	# Tablo adı sorgu METNİNE giriyor — parametre olamaz. Repo kuralı #11 gereği
	# adın dışarıdan gelemeyeceği burada kanıtlanıyor, "zaten sabitten geliyor"
	# varsayımına bırakılmıyor: bir gün çağıran değişirse kapı burada kapanır.
	if table not in DERIVED_TABLES:
		raise ValueError(f"Bilinmeyen tablo: {table!r}")
	try:
		satir = frappe.db.sql(f"select count(*) from `{table}`")  # noqa: S608
	except Exception:
		return None
	return int(satir[0][0]) if satir else None


def capture() -> dict:
	"""Bugünkü medya yapısının künyesi."""
	tablolar: dict[str, dict] = {}
	for t in FULL_TABLES:
		sutunlar = _columns(t)
		tablolar[t] = {"exists": bool(sutunlar), "columns": sutunlar}

	# Türetilmiş tablolar: sütunları künyeye giriyor (yapı kayması görünsün) ve
	# ek olarak yedek ANINDAKİ satır sayısı da saklanıyor. Bu sayı geri yükleme
	# planında "bu kadar kayıt bu yedekte YOK" cümlesine dönüşüyor; yoksa kapsam
	# dışı kalanın büyüklüğü hiçbir yerde görünmüyordu.
	turetilmis: dict[str, dict] = {}
	for t in DERIVED_TABLES:
		sutunlar = _columns(t)
		turetilmis[t] = {
			"exists": bool(sutunlar),
			"columns": sutunlar,
			"rows": _row_count(t) if sutunlar else None,
		}

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
		"derived_tables": turetilmis,
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

	# Türetilmiş tablolar ayrı hesaplanıyor ve `ok` bayrağını DÜŞÜRMÜYOR: yedek
	# zaten bu satırları taşımıyor, dolayısıyla hedefte yokluğu "geri yükleme
	# başarısız olur" demek değil. Ama sessiz de kalmamalı — plan bunu ayrı bir
	# başlıkta söylüyor.
	simdiki_turetilmis = simdi.get("derived_tables") or {}
	kurulu_degil: list[str] = []
	yapisi_kaymis: list[str] = []
	tasinmayan = 0
	for tablo, kayit in (kaydedilen.get("derived_tables") or {}).items():
		tasinmayan += kayit.get("rows") or 0
		bugun = simdiki_turetilmis.get(tablo) or {}
		if kayit.get("exists") and not bugun.get("exists"):
			kurulu_degil.append(tablo)
			continue
		eski_s = kayit.get("columns") or {}
		bugun_s = bugun.get("columns") or {}
		if eski_s and bugun_s and set(eski_s) - set(bugun_s):
			yapisi_kaymis.append(tablo)

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
		# Kapsam dışı — yedek taşımıyor, `ok` bayrağını etkilemez
		"derived_known": bool(kaydedilen.get("derived_tables")),
		"derived_absent": sorted(kurulu_degil),
		"derived_drifted": sorted(yapisi_kaymis),
		"derived_rows_not_carried": tasinmayan,
	}


def _turetilmis_satirlari(fark: dict) -> list[str]:
	"""Motor tablolarının kapsam dışı kaldığını AÇIKÇA söyleyen satırlar.

	Operatör "yapı uyumlu" cümlesini okuyup her şeyin döneceğini sanıyordu.
	Dönmeyen şeyin adı ve büyüklüğü aynı ekranda yazmalı.
	"""
	if not fark.get("derived_known"):
		return ["Bilgi: bu yedek motor tablolarının künyesini taşımıyor (künye eklenmeden önce alınmış)."]

	satirlar = []
	sayi = fark.get("derived_rows_not_carried") or 0
	if sayi:
		satirlar.append(
			f"Kapsam dışı: yedek anında motor tablolarında {sayi} kayıt vardı; "
			"yedek bunları TAŞIMIYOR, dosyalardan yeniden üretilmeleri gerekir."
		)
	if fark.get("derived_absent"):
		satirlar.append(
			"Hedefte medya motoru kurulu değil — şu tablolar yok: "
			+ ", ".join(fark["derived_absent"])
		)
	if fark.get("derived_drifted"):
		satirlar.append(
			"Motor tablolarının yapısı kaymış: " + ", ".join(fark["derived_drifted"])
		)
	return satirlar


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
		satirlar.extend(_turetilmis_satirlari(fark))
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
	satirlar.extend(_turetilmis_satirlari(fark))
	return satirlar
