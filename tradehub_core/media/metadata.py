"""Satıcının dosyaya eklediği üstveri — başlık, alternatif metin, açıklama,
etiket, favori ve gerçek çözünürlük.

**Neden KAYIT düzeyinde, dosya düzeyinde değil.**

Durum (`states`) bilerek dosyaya ait: bir dosya aynı anda hem aktif hem çöpte
olamaz. Üstveri tam tersi. Aynı görsel iki mağazaya birden ait olabiliyor
(ölçüm: 30 adres) ve her mağazanın kendi alternatif metnini yazması GEREKİR —
alternatif metin arama motoruna o mağazanın ürününü anlatır. Dosya düzeyinde
tutulsaydı iki satıcı birbirinin metnini ezerdi ve biri diğerinin ürün
tanımını okuyabilirdi.

Bu yüzden buradaki her yazma, YALNIZ o mağazanın kullanıcılarının açtığı
`File` kayıtlarına uygulanır. Aynı adresin başka mağazaya ait kayıtlarına
dokunulmaz.

Çözünürlük ayrı: o dosyanın fiziksel gerçeği, mağazaya göre değişmez. Yine de
kayıt düzeyinde saklanıyor çünkü ayrı bir tablo açmaya değmez; her kayda aynı
değer yazılır.
"""

from __future__ import annotations

import os

import frappe

from tradehub_core.media import ownership, tags_source

# Satıcının serbestçe yazabildiği alanlar. Beyaz liste: gelen sözlükte başka
# bir anahtar olursa yok sayılır — istek gövdesine `th_media_state` yazıp
# durumu değiştirmeye çalışan bir çağrı buradan geçemez.
EDITABLE: frozenset[str] = frozenset(
	{"title", "alt", "description", "tags", "favorite"}
)

_FIELD_MAP: dict[str, str] = {
	"title": "th_media_title",
	"alt": "th_media_alt",
	"description": "th_media_description",
	"tags": "th_media_tags",
	"favorite": "th_media_favorite",
	"width": "th_media_width",
	"height": "th_media_height",
}

MAX_TEXT = 500
MAX_TAGS = 20


def _records(file_url: str, store: str) -> list[str]:
	kullanicilar = ownership.users_of(store)
	if not kullanicilar:
		return []
	return frappe.get_all(
		"File",
		filters={"file_url": file_url, "owner": ["in", list(kullanicilar)]},
		pluck="name",
	)


def _clean_tags(value) -> str:
	"""Etiketleri virgüllü tek metne indir.

	Ayrı bir alt tablo açılmadı: etiket sayısı küçük, sorgulama ihtiyacı
	"içinde geçiyor mu" düzeyinde. Tablo açmak burada bakım maliyetini
	getirisinden fazla artırırdı.
	"""
	if isinstance(value, str):
		value = value.split(",")
	temiz = []
	for t in value or []:
		t = str(t).strip()
		if t and t not in temiz:
			temiz.append(t[:50])
	return ",".join(temiz[:MAX_TAGS])


def read(file_url: str, store: str) -> dict:
	"""Bu mağazanın bu dosya için yazdığı üstveri."""
	kayitlar = _records(file_url, store)
	if not kayitlar:
		return {}
	row = frappe.db.get_value(
		"File", kayitlar[0], list(_FIELD_MAP.values()), as_dict=True
	) or {}
	etiket = row.get("th_media_tags") or ""
	etiketler = [t for t in etiket.split(",") if t]
	# §17 — etiketin YANINDA kaynağı. Ayrı uç açılmadı: panel etiketi ve
	# kaynağını her zaman birlikte gösteriyor, iki çağrı iki gidiş dönüş
	# ve arada tutarsız bir an demekti.
	kaynaklar = tags_source.senkronla(tags_source.read(file_url, store), etiketler)
	return {
		"title": row.get("th_media_title") or "",
		"alt": row.get("th_media_alt") or "",
		"description": row.get("th_media_description") or "",
		"tags": etiketler,
		"tag_sources": kaynaklar,
		"tag_source_summary": tags_source.ozet(kaynaklar),
		"favorite": bool(row.get("th_media_favorite")),
		"width": row.get("th_media_width") or None,
		"height": row.get("th_media_height") or None,
	}


def read_many(file_urls: list[str], store: str) -> dict[str, dict]:
	"""Toplu okuma — liste ekranı için tek sorgu.

	Satır başına ayrı sorgu, 200 satırlık bir sayfada 200 gidiş dönüş demekti.
	"""
	kullanicilar = ownership.users_of(store)
	if not kullanicilar or not file_urls:
		return {}

	rows = frappe.get_all(
		"File",
		filters={"file_url": ["in", file_urls], "owner": ["in", list(kullanicilar)]},
		fields=["file_url", *_FIELD_MAP.values()],
	)
	out: dict[str, dict] = {}
	for r in rows:
		# Aynı adrese ait birden çok kayıt olabilir; ilk dolu değer kazanır.
		if r["file_url"] in out and not any(r.get(f) for f in _FIELD_MAP.values()):
			continue
		etiket = r.get("th_media_tags") or ""
		out[r["file_url"]] = {
			"title": r.get("th_media_title") or "",
			"alt": r.get("th_media_alt") or "",
			"description": r.get("th_media_description") or "",
			"tags": [t for t in etiket.split(",") if t],
			"favorite": bool(r.get("th_media_favorite")),
			"width": r.get("th_media_width") or None,
			"height": r.get("th_media_height") or None,
		}
	return out


def write(file_url: str, store: str, patch: dict) -> dict:
	"""Üstveriyi güncelle — yalnız bu mağazanın kayıtlarına."""
	ownership.assert_owns(store, file_url)

	kayitlar = _records(file_url, store)
	if not kayitlar:
		frappe.throw(frappe._("Dosya bulunamadı."), frappe.DoesNotExistError)

	degerler: dict[str, object] = {}
	yeni_etiketler: list[str] | None = None
	for anahtar, deger in (patch or {}).items():
		if anahtar not in EDITABLE:
			continue
		alan = _FIELD_MAP[anahtar]
		if anahtar == "tags":
			degerler[alan] = _clean_tags(deger)
			yeni_etiketler = [t for t in str(degerler[alan]).split(",") if t]
		elif anahtar == "favorite":
			degerler[alan] = 1 if deger else 0
		else:
			degerler[alan] = str(deger or "")[:MAX_TEXT]

	if not degerler:
		return read(file_url, store)

	frappe.db.set_value("File", {"name": ["in", kayitlar]}, degerler, update_modified=False)
	# §17 — etiket kaynağı. Bu yol satıcının kendi panelinden geçtiği için
	# kaynak her zaman `manual`; makine yolları (`categories.suggest`,
	# kural motoru) kendi kaynaklarıyla `tags_source.write`'ı ayrıca çağırır.
	# Etiket YAZILMADIYSA haritaya dokunulmuyor: başlık düzenlemesi etiket
	# kaynaklarını sıfırlamamalı.
	if yeni_etiketler is not None:
		tags_source.write(kayitlar, yeni_etiketler, tags_source.SOURCE_MANUAL)
	frappe.db.commit()
	return read(file_url, store)


def ensure_dimensions(file_url: str, store: str) -> dict:
	"""Çözünürlüğü diskten oku ve sakla — bir kez.

	Ekran genişlik/yükseklik gösteriyordu ama değerler uydurmaydı. Gerçeği
	dosyayı açmadan bilinemiyor; her listede açmak da pahalı. Bu yüzden ilk
	sorulduğunda okunup saklanıyor.
	"""
	kayitlar = _records(file_url, store)
	if not kayitlar:
		return {}

	mevcut = frappe.db.get_value("File", kayitlar[0], ["th_media_width", "th_media_height"], as_dict=True)
	if mevcut and mevcut.get("th_media_width"):
		return {"width": mevcut["th_media_width"], "height": mevcut["th_media_height"]}

	from tradehub_core.media import engine, trash

	yol = trash._live_path(file_url)
	if not os.path.isfile(yol):
		return {}
	try:
		with open(yol, "rb") as fh:
			probe = engine.probe(fh.read())
	except Exception:
		# Bozuk ya da desteklenmeyen dosya — ölçü yok, hata da yok. Ekran
		# "—" gösterir; bir çözünürlük uydurmaktan iyidir.
		return {}
	if not probe or not probe.readable:
		return {}

	frappe.db.set_value(
		"File",
		{"name": ["in", kayitlar]},
		{"th_media_width": probe.width, "th_media_height": probe.height},
		update_modified=False,
	)
	frappe.db.commit()
	return {"width": probe.width, "height": probe.height}


def all_tags(store: str) -> list[str]:
	"""Mağazanın kullandığı tüm etiketler — filtre listesi için."""
	kullanicilar = ownership.users_of(store)
	if not kullanicilar:
		return []
	rows = frappe.get_all(
		"File",
		filters={"owner": ["in", list(kullanicilar)], "th_media_tags": ["!=", ""]},
		pluck="th_media_tags",
	)
	etiketler: set[str] = set()
	for r in rows:
		etiketler.update(t for t in (r or "").split(",") if t)
	return sorted(etiketler)
