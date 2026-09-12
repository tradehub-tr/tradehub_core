"""Etiket kaynağı — hangi etiketi kim koydu (MOGEM-620 §17).

ŞARTNAME NE İSTİYOR
-------------------
§17 son madde: "AI generated, System ve Manual tag kaynakları ayırt edilmeli."
Kabul kriteri 18: "tag kaynağı AI/System/Manual olarak izlenir."

10 Eylül 2026 denetiminde durum: KATEGORİ atamasında kaynak vardı
(`Media Category Assignment.assignment_source` — manual/suggestion/rule/ai/
system), ETİKETTE yoktu. `th_media_tags` düz virgüllü metin ve kim yazdığı
hiçbir yerde durmuyordu.

NEDEN `th_media_tags`'IN ŞEKLİ DEĞİŞMEDİ
---------------------------------------
En doğrudan çözüm etiketleri alt tabloya taşımaktı (`Media Tag Assignment`,
kategorinin birebir eşi). Yapılmadı, çünkü `th_media_tags` bugün ALTI ayrı
yerden okunuyor: kütüphane listesi, serbest arama (`inventory`), etiket
süzgeci, `all_tags` sayacı, yedek/geri yükleme ve panel. Şekli değiştirmek
altısını da aynı anda kırardı ve kazanç yalnız "kaynağı biliyoruz" olurdu.

Bunun yerine YAN KOLON: `th_media_tag_sources`, `{etiket: kaynak}` JSON'u.
Etiketin kendisi eski yerinde kalıyor; kaynak yanına yazılıyor. İkisi
arasındaki tutarlılığı `senkronla()` sağlıyor — etiket silinince kaynağı da
düşer, yetim kaynak birikmez.

KAYNAK DEĞERLERİ
----------------
`Media Category Assignment.assignment_source` ile AYNI kelimeler kullanılıyor
(`manual`/`ai`/`system`/`rule`/`suggestion`). Etikete iki, kategoriye beş
farklı kaynak adı vermek aynı kavramı iki sözlükle anlatmak olurdu.

ÇAKIŞMA KURALI
--------------
Bir etiket zaten varsa ve YENİ kaynak `manual` ise kaynak GÜNCELLENİR:
insan, makinenin koyduğu etiketi onaylamış sayılır. Tersi olmaz — `manual`
bir etiketin kaynağını `ai` ezemez. Bu, `seo.REFRESHABLE`'ın alt metni için
koyduğu kuralın etiket karşılığı: insan girdisi makine tarafından geri
alınmaz.
"""

from __future__ import annotations

import json

import frappe

SOURCE_MANUAL: str = "manual"
SOURCE_AI: str = "ai"
SOURCE_SYSTEM: str = "system"
SOURCE_RULE: str = "rule"
SOURCE_SUGGESTION: str = "suggestion"

#: Kabul edilen kaynaklar. Beyaz liste: serbest metin kaynak adı, panelde
#: gruplanamayan ve iki yazımı ("AI"/"ai") iki ayrı kaynak sayılan bir alan
#: üretirdi.
SOURCES: frozenset[str] = frozenset(
	{SOURCE_MANUAL, SOURCE_AI, SOURCE_SYSTEM, SOURCE_RULE, SOURCE_SUGGESTION}
)

#: İnsan kaynaklı sayılanlar — makine bunların kaynağını ezemez.
_INSAN: frozenset[str] = frozenset({SOURCE_MANUAL})

COLUMN: str = "th_media_tag_sources"


def _kolon_var() -> bool:
	return frappe.db.has_column("File", COLUMN)


def parse(ham: object) -> dict[str, str]:
	"""Kolon değerini `{etiket: kaynak}` sözlüğüne çevir — bozuksa boş.

	Bozuk JSON'da PATLAMAZ: bu veri okuma yolunda (liste ekranı, dışa
	aktarma) da kullanılıyor ve tek bozuk satır yüzünden bütün sayfayı
	düşürmek orantısız. Yazma yolu zaten geçerli JSON üretiyor.
	"""
	if not ham:
		return {}
	if isinstance(ham, dict):
		veri: object = ham
	elif isinstance(ham, (str, bytes, bytearray)):
		try:
			veri = json.loads(ham)
		except ValueError:
			return {}
	else:
		return {}
	if not isinstance(veri, dict):
		return {}
	return {
		str(k): str(v) for k, v in veri.items() if str(v) in SOURCES and str(k or "").strip()
	}


def birlestir(mevcut: dict[str, str], etiketler: list[str], kaynak: str) -> dict[str, str]:
	"""Yeni etiketlerin kaynağını mevcut haritaya işle. Saf fonksiyon.

	Çakışma kuralı modül docstring'inde: `manual` makineyi ezer, makine
	`manual`ı ezemez.
	"""
	if kaynak not in SOURCES:
		raise ValueError(f"Bilinmeyen etiket kaynağı: {kaynak!r}")
	out = dict(mevcut or {})
	for etiket in etiketler or []:
		ad = str(etiket or "").strip()
		if not ad:
			continue
		onceki = out.get(ad)
		if onceki in _INSAN and kaynak not in _INSAN:
			continue
		out[ad] = kaynak
	return out


def senkronla(mevcut: dict[str, str], etiketler: list[str]) -> dict[str, str]:
	"""Haritayı GÜNCEL etiket listesine daralt — yetim kaynak bırakma.

	Etiket silindiğinde kaynağı da düşmeli. Düşmezse iki sorun birden:
	harita sonsuza kadar büyür ve aynı etiket ileride başka bir kaynakla
	geri geldiğinde eski (yanlış) kaynağını taşır.
	"""
	gecerli = {str(t or "").strip() for t in (etiketler or []) if str(t or "").strip()}
	return {k: v for k, v in (mevcut or {}).items() if k in gecerli}


def read(file_url: str, store: str | None = None) -> dict[str, str]:
	"""Dosyanın etiket kaynağı haritası.

	`store` verilirse yalnız o mağazanın kaydından okunur — etiketler
	`media/metadata.py` gereği KAYIT düzeyinde ve iki mağaza aynı dosyaya
	farklı etiket yazabiliyor.
	"""
	from tradehub_core.media import ownership

	if not _kolon_var():
		return {}
	url = (file_url or "").split("?")[0]
	filtre: dict = {"file_url": url}
	if store:
		kullanicilar = list(ownership.users_of(store))
		if not kullanicilar:
			return {}
		filtre["owner"] = ["in", kullanicilar]
	satir = frappe.db.get_value("File", filtre, COLUMN)
	return parse(satir)


def write(kayitlar: list[str], etiketler: list[str], kaynak: str) -> dict[str, str]:
	"""Etiket kaynaklarını `kayitlar`daki tüm `File` satırlarına yaz.

	Çağıran kayıt listesini KENDİ çözüyor (`metadata._records`) — bu modül
	kiracı sınırını yeniden hesaplamıyor. İki yerde iki sahiplik mantığı
	olması, ikisinin ayrışması demekti.
	"""
	if not _kolon_var() or not kayitlar:
		return {}
	mevcut = parse(frappe.db.get_value("File", kayitlar[0], COLUMN))
	harita = senkronla(birlestir(mevcut, etiketler, kaynak), etiketler)
	frappe.db.set_value(
		"File",
		{"name": ["in", kayitlar]},
		COLUMN,
		json.dumps(harita, ensure_ascii=False),
		update_modified=False,
	)
	return harita


def ozet(harita: dict[str, str]) -> dict[str, int]:
	"""Kaynak başına etiket sayısı — panel rozetleri için."""
	out = {k: 0 for k in sorted(SOURCES)}
	for kaynak in (harita or {}).values():
		if kaynak in out:
			out[kaynak] += 1
	return out
