"""Kategori adlarının çok dilli doldurulması — sözlük tohumu + çeviri hattı.

NEDEN: Ölçüldü (16 Eyl 2026) — 23.511 aktif kategorinin `category_name_en`,
`category_name_ar` ve `category_name_ru` sütunları TAMAMEN boştu. Arayüz dört
dilde çalışıyor ama kategori adları her dilde Türkçe görünüyordu; `get_mega_menu`
`resolve_content_field` ile çözdüğü için sessizce `category_name`e düşüyordu.

İKİ YOL, TEK YAZMA NOKTASI:

  `apply_name_seed()`     — elde hazır sözlükten yazar (insan/model çevirisi).
  `backfill_names()`      — Translation Settings sağlayıcısıyla çevirir.

İkisi de `_yaz()` üzerinden geçer, yani idempotenttir: dolu bir alanın üzerine
yazılmaz, ikinci koşum 0 yazar. Rapor biçimi `media/seo_generate.backfill_
localization` ile aynı (`scanned/written/skipped/reasons/by_lang`) — dil başına
doğruluk tek toplamdan dürüsttür.

STUB KORUMASI — bu modülün en önemli kuralı:
`api/translation.translate()` sağlayıcı yokken sessizce STUB'a düşer ve
`"[tr→en] Oyuncak"` gibi bir metin döndürür (`_translate_stub`). O metin
veritabanına yazılırsa katalog çöple dolar ve kusur ancak vitrinde görülür.
Bu yüzden `backfill_names()` `translator` alanını denetler: `stub`, `stub-quota`
ve `noop` çıktıları YAZILMAZ, `stub_provider` sebebiyle atlanır. Yani API
anahtarı tanımlanmadan bu hat hiçbir şey yazmaz — kasıtlı.

EŞLEME ADA GÖRE: tohum `{türkçe ad: {en, ar, ru}}` biçimindedir; aynı ad farklı
dallarda tekrar ettiğinde hepsi tek kayıttan dolar. Ölçüldü: menünün üst iki
seviyesindeki 803 kategori 800 benzersiz ad taşıyor, bu adlar katalogda 868
kategoriye karşılık geliyor.

COLLATION TUZAĞI — `_adaylar` SQL'i ile `_yaz` sözlüğü AYNI ADI FARKLI GÖRÜR:
MariaDB varsayılan `utf8mb4_general_ci` altında `c` ile `ç`, `s` ile `ş` eşit
sayılır. Ölçüldü (16 Eyl 2026): `category_name IN (...)` süzgeci hem
"Saç Şekillendirme" (hair styling) hem "Sac Şekillendirme" (sheet metal forming)
kaydını getirdi, oysa tohumda yalnız ilki vardı.

Bu yüzden karşılık SQL'den değil, PYTHON SÖZLÜĞÜNDEN okunur: `tohum.get(ad)`
birebir eşleşme arar. Aksi hâlde metal şekillendirme kategorisine "Hair Styling"
yazılırdı — ekranda doğru görünen, anlamı tamamen yanlış bir çeviri. Eşleşmeyen
kayıt sessizce geçilmez, `empty_value` sebebiyle raporlanır; o sayacın sıfırdan
büyük olması "tohumda eksik ad var" demektir.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe

from tradehub_core.seo.i18n import CONTENT_LANGS, DEFAULT_LANG, normalize_lang

DOCTYPE = "Product Category"
ALAN = "category_name"

#: Türkçe kaynak dil; doldurulacak diller bunun dışındakiler.
CEVRILEN_DILLER: tuple[str, ...] = tuple(d for d in CONTENT_LANGS if d != DEFAULT_LANG)

#: Sağlayıcı gerçekten çeviri yapmadığında dönen etiketler — bunlar yazılmaz.
SAHTE_CEVIRMENLER = ("stub", "stub-quota", "noop")

_TOHUM_YOLU = Path(__file__).parent / "data" / "category_names_seed.json"


def tohum_yukle() -> dict[str, dict[str, str]]:
	"""Sözlük tohumunu diskten oku. Dosya yoksa boş sözlük — hat yine çalışır."""
	if not _TOHUM_YOLU.exists():
		return {}
	with _TOHUM_YOLU.open(encoding="utf-8") as f:
		return json.load(f)


def _alan(lang: str) -> str:
	return f"{ALAN}_{lang}"


def _yaz(name: str, lang: str, deger: str) -> dict:
	"""Tek kaydın tek dil alanını doldur.

	İdempotent: alan doluysa dokunulmaz. Boş/yalnız boşluk değer yazılmaz —
	"çevrildi ama boş" hâli ekranda ham Türkçeden daha kötüdür, çünkü
	`resolve_content_field` boş değeri de "dolu" sayar mı diye bakmaz; dolu
	sayarsa fallback zinciri kırılır.
	"""
	deger = (deger or "").strip()
	if not deger:
		return {"written": False, "reason": "empty_value"}

	mevcut = frappe.db.get_value(DOCTYPE, name, _alan(lang))
	if (mevcut or "").strip():
		return {"written": False, "reason": "already_filled"}

	frappe.db.set_value(DOCTYPE, name, _alan(lang), deger, update_modified=False)
	return {"written": True, "reason": ""}


def _adaylar(lang: str, limit: int, adlar: list[str] | None = None) -> list[dict]:
	"""O dilde adı boş olan aktif kategoriler.

	`adlar` verilirse yalnız o Türkçe adları taşıyanlar — tohum uygulaması
	katalogun tamamını taramasın diye.
	"""
	kosullar = {"is_active": 1, _alan(lang): ["in", ["", None]]}
	if adlar is not None:
		if not adlar:
			return []
		kosullar[ALAN] = ["in", adlar]
	return frappe.get_all(
		DOCTYPE,
		filters=kosullar,
		fields=["name", ALAN],
		limit_page_length=limit,
	)


def _bos_rapor() -> dict:
	return {"scanned": 0, "written": 0, "skipped": 0, "reasons": {}, "by_lang": {}}


def _dilleri_ayikla(langs) -> tuple[list[str], dict]:
	"""Bilinmeyen dil kodlarını AYIR.

	`normalize_lang` tanımadığı kodu sessizce `tr`'ye çevirir; korunmasız
	bırakılırsa çağıran "de" istediğini sanırken hat ikinci kez Türkçeyi
	tekrarlar ve rapor yalancı bir "de yazıldı" gösterir.
	"""
	gecerli: list[str] = []
	by_lang: dict[str, dict] = {}
	for ham in langs or ():
		# Kaynak dil ile tanınmayan kod AYRI sebeplerdir: ilki "zaten dolu,
		# çevrilecek bir şey yok", ikincisi çağıranın hatası.
		sebep = "source_lang" if ham == DEFAULT_LANG else "unknown_lang"
		if ham not in CONTENT_LANGS or ham == DEFAULT_LANG:
			by_lang[ham] = {"scanned": 0, "written": 0, "skipped": 0, "reasons": {sebep: 1}}
			continue
		gecerli.append(normalize_lang(ham))
	return gecerli, by_lang


def apply_name_seed(
	tohum: dict[str, dict[str, str]] | None = None,
	langs: tuple[str, ...] = CEVRILEN_DILLER,
	limit: int = 5000,
) -> dict:
	"""Hazır sözlükten kategori adlarını doldur.

	`tohum` verilmezse diskteki `data/category_names_seed.json` okunur.
	Sözlükte karşılığı olmayan kategori ATLANIR — hat onları `backfill_names`
	için bırakır.
	"""
	tohum = tohum if tohum is not None else tohum_yukle()
	limit = max(1, min(50000, int(limit or 5000)))
	gecerli, by_lang = _dilleri_ayikla(langs)

	toplam = _bos_rapor()
	toplam["by_lang"] = by_lang
	for ayrilan in by_lang.values():
		for sebep, adet in ayrilan["reasons"].items():
			toplam["reasons"][sebep] = toplam["reasons"].get(sebep, 0) + adet

	tohum_adlari = list(tohum.keys())
	for lang in gecerli:
		yazilan = atlanan = 0
		sebepler: dict[str, int] = {}
		adaylar = _adaylar(lang, limit, adlar=tohum_adlari)
		for kayit in adaylar:
			karsilik = (tohum.get(kayit[ALAN]) or {}).get(lang, "")
			sonuc = _yaz(kayit["name"], lang, karsilik)
			if sonuc["written"]:
				yazilan += 1
			else:
				atlanan += 1
				sebepler[sonuc["reason"]] = sebepler.get(sonuc["reason"], 0) + 1
				toplam["reasons"][sonuc["reason"]] = toplam["reasons"].get(sonuc["reason"], 0) + 1

		by_lang[lang] = {
			"scanned": len(adaylar),
			"written": yazilan,
			"skipped": atlanan,
			"reasons": sebepler,
		}
		toplam["scanned"] += len(adaylar)
		toplam["written"] += yazilan
		toplam["skipped"] += atlanan

	frappe.db.commit()
	return toplam


def backfill_names(limit: int = 500, langs: tuple[str, ...] = CEVRILEN_DILLER) -> dict:
	"""Kalan kategori adlarını çeviri sağlayıcısıyla doldur.

	`limit` HER DİL için ayrı uygulanır, toplam tavan değildir.

	Sağlayıcı yapılandırılmamışsa (Translation Settings `provider=stub` ya da
	API anahtarı boş) hiçbir şey yazılmaz: her aday `stub_provider` sebebiyle
	atlanır. Bu, hattın "çalıştı" görünüp katalogu `[tr→en] …` ile doldurmasını
	engeller.
	"""
	from tradehub_core.api.translation import translate

	limit = max(1, min(5000, int(limit or 500)))
	gecerli, by_lang = _dilleri_ayikla(langs)

	toplam = _bos_rapor()
	toplam["by_lang"] = by_lang

	for lang in gecerli:
		yazilan = atlanan = 0
		sebepler: dict[str, int] = {}
		adaylar = _adaylar(lang, limit)
		for kayit in adaylar:
			sonuc_ceviri = translate(kayit[ALAN], lang, DEFAULT_LANG)
			cevirmen = sonuc_ceviri.get("translator", "")
			if cevirmen in SAHTE_CEVIRMENLER or cevirmen.startswith("stub"):
				atlanan += 1
				sebepler["stub_provider"] = sebepler.get("stub_provider", 0) + 1
				toplam["reasons"]["stub_provider"] = toplam["reasons"].get("stub_provider", 0) + 1
				continue

			sonuc = _yaz(kayit["name"], lang, sonuc_ceviri.get("text", ""))
			if sonuc["written"]:
				yazilan += 1
			else:
				atlanan += 1
				sebepler[sonuc["reason"]] = sebepler.get(sonuc["reason"], 0) + 1
				toplam["reasons"][sonuc["reason"]] = toplam["reasons"].get(sonuc["reason"], 0) + 1

		by_lang[lang] = {
			"scanned": len(adaylar),
			"written": yazilan,
			"skipped": atlanan,
			"reasons": sebepler,
		}
		toplam["scanned"] += len(adaylar)
		toplam["written"] += yazilan
		toplam["skipped"] += atlanan

	frappe.db.commit()
	return toplam


def coverage() -> dict:
	"""Dil başına doluluk — koşum öncesi/sonrası tek bakışta karşılaştırmak için."""
	toplam = frappe.db.count(DOCTYPE, {"is_active": 1})
	sonuc = {"total": toplam, "by_lang": {}}
	for lang in CEVRILEN_DILLER:
		dolu = frappe.db.sql(
			f"""SELECT COUNT(*) FROM `tab{DOCTYPE}`
			    WHERE is_active=1 AND {_alan(lang)} IS NOT NULL AND TRIM({_alan(lang)}) <> ''"""
		)[0][0]
		sonuc["by_lang"][lang] = {"filled": dolu, "missing": toplam - dolu}
	return sonuc


@frappe.whitelist()
def run_seed(limit: int = 5000) -> dict:
	"""Panelden/bench'ten tohum uygulaması. Yalnız yetkili kullanıcı."""
	frappe.only_for("System Manager")
	return apply_name_seed(limit=int(limit))


@frappe.whitelist()
def run_backfill(limit: int = 500) -> dict:
	"""Panelden/bench'ten sağlayıcı ile doldurma. Yalnız yetkili kullanıcı."""
	frappe.only_for("System Manager")
	return backfill_names(limit=int(limit))


@frappe.whitelist()
def get_coverage() -> dict:
	frappe.only_for("System Manager")
	return coverage()
