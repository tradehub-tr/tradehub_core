"""Medya referans zinciri — silinen dosyanın geride bıraktığı bağları temizler.

Sorun ölçüldü: bir dosya kalıcı silindiğinde `File` kaydı ve fiziksel dosya
gidiyor ama onu gösteren alanlar (`Listing Image.image`, `Listing.primary_image`,
varyant görselleri, mağaza logosu...) DEĞİŞMİYOR. Sonuç: üründe boş bir görsel
yuvası kalıyor, kullanıcı önce o boşluğu silip sonra yeniden yüklemek zorunda.

    /files/hannibal8height-marble-1664442_1920.jpg
      File kaydı            → yok (silindi)
      Listing Image.image   → hâlâ işaret ediyor   ← kırık referans

Bu modül üç şey yapar:

  1. `find(url)`      — dosyayı gösteren TÜM satırları bulur (hangi tablo, hangi
                        kolon, hangi kayıt)
  2. `clear(url)`     — o bağları temizler: satır bir galeri/varyant satırıysa
                        SİLİNİR, tekil bir alansa BOŞALTILIR
  3. `find_dangling()`— hedefi olmayan referansları tarar (geçmişte bozulanlar)

Neden satır silme ile alan boşaltma ayrı: `Listing Image` bir child table satırı
ve tek işi bir görseli taşımak — görsel gidince satırın varlık sebebi kalmıyor,
boş bırakmak üründe boş kutu gösterir. `Listing.primary_image` ise ürünün bir
alanı; ürünü silemeyiz, alanı boşaltırız.
"""

from __future__ import annotations

import json
import re

import frappe

from tradehub_core.media import usage
from tradehub_core.media.usage import LIVE_SOURCES, ORDER_SOURCES

# Görsel gidince satırın varlık sebebi kalmayan child table'lar. Bunlarda satır
# silinir; diğerlerinde yalnız alan boşaltılır.
ROW_OWNED_TABLES: frozenset[str] = frozenset(
	{"tabListing Image", "tabListing Variant Item", "tabSeller Gallery Image"}
)

# Sipariş kaynakları TEMİZLENMEZ: geçmiş siparişin kaydı, o anki görüntüyü
# saklamak için var. Referansı silmek geçmişi değiştirmek olur — yalnız
# raporlanır.
READONLY_TABLES: frozenset[str] = frozenset(t for t, _c, _k, _l in ORDER_SOURCES)


def _sources() -> tuple[tuple[str, str, str, str], ...]:
	return LIVE_SOURCES + ORDER_SOURCES


# Yazma yolunda tablo/kolon adı sorguya doğrudan giriyor. Bugün bu adlar yalnız
# sabit listeden geliyor, ama `clear()` DELETE/UPDATE çalıştırıyor — dolaylı
# güvenliğe bel bağlamak yerine izin listesi burada açıkça kontrol ediliyor.
# Kaynak listesi genişlerse otomatik genişler; dışarıdan gelen bir ad geçemez.
_WRITABLE: frozenset[tuple[str, str]] = frozenset((table, column) for table, column, _k, _l in LIVE_SOURCES)


def _assert_writable(table: str, column: str) -> None:
	if (table, column) not in _WRITABLE:
		frappe.throw(frappe._("Bu alan üzerinde yazma yetkisi yok: {0}.{1}").format(table, column))


def find(file_url: str, store: str | None = None) -> list[dict]:
	"""Bu dosyayı gösteren tüm satırlar.

	`sections` gibi JSON/metin alanlarında URL gömülü geçebiliyor; tam eşitlik
	yetmez, `LOCATE` ile içerik araması yapılır. LIKE kullanılmaz — MariaDB'nin
	utf8mb4 collation'ında 4 baytlık karakterli satırlarda hatalı sonuç veriyor.

	`store` verilirse yalnız o mağazanın kayıtları taranır. Satıcı bir dosyayı
	bıraktığında YALNIZ kendi bağları temizlenmeli; aynı dosyayı kullanan başka
	mağazanın ürünü olduğu gibi kalmalı.
	"""
	url = (file_url or "").split("?")[0]
	if not url:
		return []

	# Adres JSON alanlarında kaçışlı yazılabiliyor (`ı` → `ı`); yalnız ham
	# yazım aranırsa vitrin bölümündeki bağ hiç bulunmuyor ve dosya silindikten
	# sonra bölümde kırık görsel kalıyor. İki yazım da aranır.
	yazimlar = usage._search_variants(url)
	kosul = " or ".join(["LOCATE(%s, `{col}`) > 0"] * len(yazimlar))

	out: list[dict] = []
	for table, column, kind, label in _sources():
		# `parent`/`parenttype` yalnız child table'larda var. Eskiden koşulsuz
		# seçiliyordu ve ana tablolar "Unknown column 'parent'" hatası veriyordu;
		# hata da sessizce yutulduğu için `Listing.primary_image` gibi TEKİL
		# alanlar referans zincirine hiç girmiyordu. Dosya kalıcı silinince
		# ürünün ana görsel alanı geride kırık kalıyordu — zincirin varlık sebebi
		# tam olarak buydu.
		try:
			sutunlar = set(frappe.db.get_table_columns(table[3:]))
		except Exception:
			continue
		if column not in sutunlar:
			continue

		ek = ", parent, parenttype" if {"parent", "parenttype"} <= sutunlar else ""

		tam_kosul = kosul.format(col=column)
		degerler = list(yazimlar)
		if store:
			magaza = usage.STORE_FILTERS.get(table)
			if not magaza:
				# Mağaza bağı tanımlanmamış kaynak — satıcı bağlamında hiç
				# dokunulmaz. Bilmediğimiz bir tabloda satır silmektense o
				# tabloyu atlamak doğru yön.
				continue
			tam_kosul = f"({tam_kosul}) and {magaza}"
			degerler.append(store)

		try:
			rows = frappe.db.sql(
				f"""select name, `{column}` as val{ek}
					from `{table}` where {tam_kosul}""",  # noqa: S608 — tablo/kolon sabit listeden
				degerler,
				as_dict=True,
			)
		except Exception:
			# Buraya düşmek artık bir sürüm farkı değil, gerçek bir hata —
			# sessizce yutmak bu modülün ilk kusuruydu.
			frappe.log_error(
				title=f"Referans taramasi basarisiz: {table}.{column}",
				message=frappe.get_traceback(with_context=True),
			)
			continue

		for row in rows:
			out.append(
				{
					"table": table,
					"column": column,
					"kind": kind,
					"label": label,
					"row": row["name"],
					"owner": row.get("parent") or row["name"],
					"owner_doctype": row.get("parenttype") or table[3:],
					"exact": (row.get("val") or "").strip() == url,
					"readonly": table in READONLY_TABLES,
					"row_owned": table in ROW_OWNED_TABLES,
				}
			)
	return out


def clear(file_url: str, *, dry_run: bool = False, store: str | None = None) -> dict:
	"""Dosyayı gösteren bağları temizle.

	Yalnız TAM EŞLEŞEN alanlara dokunulur. `sections` gibi gömülü metinlerde
	URL'i kesip atmak JSON'u bozabilir; onlar raporlanır ama değiştirilmez —
	yanlış temizlik, kırık referanstan daha kötüdür.

	`store` verilirse yalnız o mağazanın kayıtlarındaki bağlar temizlenir.
	"""
	silinen_satir: list[str] = []
	bosaltilan: list[str] = []
	atlanan: list[str] = []

	for ref in find(file_url, store=store):
		hedef = f"{ref['owner_doctype']}:{ref['owner']}·{ref['column']}"
		if ref["readonly"]:
			atlanan.append(f"{hedef} (sipariş geçmişi)")
			continue
		if not ref["exact"]:
			atlanan.append(f"{hedef} (gömülü metin)")
			continue

		if dry_run:
			(silinen_satir if ref["row_owned"] else bosaltilan).append(hedef)
			continue

		_assert_writable(ref["table"], ref["column"])

		if ref["row_owned"]:
			# Child satırı: görsel gidince satırın varlık sebebi kalmıyor.
			frappe.db.sql(f"delete from `{ref['table']}` where name=%s", (ref["row"],))  # noqa: S608
			silinen_satir.append(hedef)
		else:
			frappe.db.sql(  # noqa: S608
				f"update `{ref['table']}` set `{ref['column']}`='' where name=%s", (ref["row"],)
			)
			bosaltilan.append(hedef)

	if not dry_run and (silinen_satir or bosaltilan):
		frappe.db.commit()

	return {
		"file_url": file_url,
		"rows_deleted": silinen_satir,
		"fields_cleared": bosaltilan,
		"skipped": atlanan,
		"total": len(silinen_satir) + len(bosaltilan),
	}


def _replace_embedded(value: str, old_url: str, new_url: str) -> str | None:
	"""Gömülü değerde adresi değiştir. JSON ise yapısal, değilse tam-dize.
	Değişiklik yoksa ya da JSON bozuksa None."""
	if not value:
		return None
	yazimlar = usage._search_variants(old_url)
	stripped = value.lstrip()
	if stripped[:1] in "[{":
		try:
			data = json.loads(value)
		except ValueError:
			return None

		# Yalnız string DEĞERLER yeniden yazılır; dict KEY'leri hiç
		# dokunulmadan geçer — key'ler alan adı (örn. "cover_image"),
		# hiçbir zaman URL değil.
		def walk(node):
			if isinstance(node, str):
				return new_url if node == old_url else node
			if isinstance(node, list):
				return [walk(x) for x in node]
			if isinstance(node, dict):
				return {k: walk(v) for k, v in node.items()}
			return node

		yeni = walk(data)
		if yeni == data:
			return None
		return json.dumps(yeni, ensure_ascii=True)
	# Sınır-farkında değiştirme: `y` bir URL-gövdesi karakteriyle devam
	# ediyorsa (örn. `/files/x.jpg` → `/files/x.jpg.webp` ya da
	# `/files/x.jpg2` içindeki önek) atlanır — yalnız gerçek URL'in bittiği
	# yerlerde (tırnak, boşluk, `)`, `>`, `?`, `#`, dize sonu) değiştirilir.
	yeni = value
	for y in yazimlar:
		# `new_url` yerine `lambda m: new_url` — `re.sub` replacement string'i
		# `\1`/`\g<...>` gibi geri-referans olarak yorumlar; URL'de kaçış
		# karakteri OLMASA da bu yorumlamayı devre dışı bırakmak daha güvenli.
		yeni = re.sub(re.escape(y) + r"(?![A-Za-z0-9._~-])", lambda m: new_url, yeni)
	return None if yeni == value else yeni


def retarget(old_url: str, new_url: str) -> dict:
	"""Dosyanın URL'i değiştiğinde (erişim-seviyesi toggle, TUR-126 §4) onu
	gösteren referansları yeni URL'e çevir.

	Tam eşleşen alanlar doğrudan güncellenir. Gömülü referanslar (`sections`
	gibi JSON alanları, ya da URL'i düz metin içinde taşıyan kolonlar) da artık
	taşınır: JSON yapısal olarak yürünüp değiştirilir, düz metinde tam-dize
	(ham ve JSON-kaçışlı yazım) değiştirilir; parse edilemeyen JSON atlanır.
	Sipariş kaynakları (`READONLY_TABLES`) hiç dokunulmaz — geçmiş siparişin
	görüntüsü o anki hâli yansıtmalı, taşıma geçmişi değiştirmemeli.

	Satır silinmez (dosya hâlâ var, yalnız yeri değişti); galeri/varyant
	satırları da tekil alanlar (`Listing.primary_image`) da aynı şekilde
	kolonu yeni URL'e günceller.
	"""
	guncellenen: list[str] = []
	atlanan: list[str] = []

	for ref in find(old_url):
		hedef = f"{ref['owner_doctype']}:{ref['owner']}·{ref['column']}"
		if ref["readonly"]:
			atlanan.append(f"{hedef} (sipariş geçmişi)")
			continue

		if not ref["exact"]:
			_assert_writable(ref["table"], ref["column"])
			mevcut = frappe.db.get_value(ref["table"][3:], ref["row"], ref["column"])
			yeni = _replace_embedded(mevcut or "", old_url, new_url)
			if yeni is None:
				atlanan.append(f"{hedef} (gömülü metin)")
				continue
			frappe.db.sql(  # noqa: S608 — tablo/kolon _WRITABLE allow-list'inden
				f"update `{ref['table']}` set `{ref['column']}`=%s where name=%s",
				(yeni, ref["row"]),
			)
			guncellenen.append(hedef)
			continue

		_assert_writable(ref["table"], ref["column"])
		frappe.db.sql(  # noqa: S608 — tablo/kolon _WRITABLE allow-list'inden
			f"update `{ref['table']}` set `{ref['column']}`=%s where name=%s",
			(new_url, ref["row"]),
		)
		guncellenen.append(hedef)

	return {
		"old_url": old_url,
		"new_url": new_url,
		"updated": guncellenen,
		"skipped": atlanan,
		"total": len(guncellenen),
	}


def find_dangling(limit: int = 500) -> list[dict]:
	"""Hedefi olmayan referansları tara — geçmişte bozulmuş bağlar.

	Bu tarama olmadan kırık referanslar yalnız kullanıcı ürüne bakınca fark
	ediliyordu. Ölçüm: `hannibal8height-marble-1664442_1920.jpg` silindikten
	sonra `Listing Image` satırı geride kalmıştı.
	"""
	out: list[dict] = []
	for table, column, _kind, label in LIVE_SOURCES:
		try:
			rows = frappe.db.sql(
				f"""select t.`{column}` as url, count(*) as n
					from `{table}` t
					where LEFT(t.`{column}`, 7) = '/files/'
					  and not exists (select 1 from tabFile f where f.file_url = t.`{column}`)
					group by t.`{column}` limit %s""",  # noqa: S608 — tablo/kolon sabit listeden
				(limit,),
				as_dict=True,
			)
		except Exception:
			continue
		for r in rows:
			out.append({"table": table, "column": column, "label": label, "url": r["url"], "rows": r["n"]})
	return out


def repair_dangling(*, dry_run: bool = True) -> dict:
	"""Tespit edilen kırık referansları temizle.

	Varsayılan `dry_run=True`: ne yapılacağını gösterir, dokunmaz. Yıkıcı bir
	işlem varsayılan olarak sessizce çalışmamalı.
	"""
	kirik = find_dangling()
	sonuc = [clear(item["url"], dry_run=dry_run) for item in {i["url"]: i for i in kirik}.values()]
	return {
		"dangling_urls": len(sonuc),
		"dry_run": dry_run,
		"details": sonuc,
	}
