"""Görsel işaretleme ipuçları — `<img>` niteliklerinin kaynağı (TUR-135 §6.2).

Karar belgesi: `docs/MEDYA-SEO-SOZLESMESI.md` §6.2 · örnek §7.

NE İŞE YARIYOR
--------------
Vitrin bugün `alt` metnini ham ürün başlığından türetiyor ve `width`/`height`
niteliklerini SABİT `800×800` basıyor (ölçüm §7.1: gerçek dosya 497×645).
Yanlış ölçü tarayıcıya yanlış yer ayırttırıyor, sayfa yüklenirken zıplıyor
(CLS cezası) — üstelik doğru değerler `th_media_width/height` alanlarında
zaten duruyor.

Bu modül her görsel için işaretlemenin veri tarafını üretir: metin, gerçek
ölçüler ve YÜKLEME İPUCU. HTML üretmez — vitrin Alpine, panel Vue; işaretleme
kararını sözleşmeye gömmek aynı kuralı iki şablon motoruna mahkûm ederdi
(medya motorunun `delivery/picture.py` docstring'i aynı gerekçeyi taşıyor).

LCP İPUCU — HERKESE `high` VERİLMEZ
-----------------------------------
`fetchpriority="high"` bir ÖNCELİK bildirimidir: her görsele verilirse hiçbir
görsele verilmemiş gibi olur, üstelik gerçek LCP adayının önüne geçen istekler
doğar. Kural: sayfanın ilk (kahraman) görseli `eager` + `high`; galerideki
diğerleri `lazy`. Liste ekranlarında ilk satır `eager`, gerisi `lazy` —
kart ızgarasında ilk dört kart genelde ekranda.
"""

from __future__ import annotations

from typing import Any

#: Liste/ızgara ekranlarında kaç kart ekranda varsayılıyor. Ölçüm yerine
#: muhafazakâr bir sayı: fazlası "hepsi eager" demeye yaklaşır.
ABOVE_FOLD_COUNT: int = 4


def hints(index: int, *, context: str = "gallery") -> dict[str, Any]:
	"""Sıraya ve bağlama göre yükleme ipuçları.

	`context`:
	    "gallery" — ürün sayfası; ilk görsel LCP adayı
	    "grid"    — kart ızgarası; ilk `ABOVE_FOLD_COUNT` kart ekranda
	    "thumb"   — küçük önizleme; hiçbiri öncelikli değil
	"""
	if context == "thumb":
		return {"loading": "lazy", "decoding": "async", "fetchpriority": ""}

	if context == "grid":
		erken = index < ABOVE_FOLD_COUNT
		return {
			"loading": "eager" if erken else "lazy",
			"decoding": "async",
			# Izgarada TEK bir LCP adayı yok; hiçbirine `high` verilmiyor.
			"fetchpriority": "",
		}

	ilk = index == 0
	return {
		"loading": "eager" if ilk else "lazy",
		"decoding": "async",
		"fetchpriority": "high" if ilk else "",
	}


def image_payload(
	seo_fields: dict,
	*,
	index: int = 0,
	context: str = "gallery",
) -> dict[str, Any]:
	"""Tek görselin işaretleme yükü — `media/seo.fields_for` çıktısından.

	Dönen anahtarlar HTML özniteliklerinin adıyla aynı (`alt`, `width`,
	`loading`, `fetchpriority`): çeviri katmanı olmasın, frontend `:attr`
	ile doğrudan bağlasın.

	`width`/`height` 0 ise anahtar YİNE döner: frontend "0 ise basma" kararını
	verebilsin. Boş nitelik basmak (`width="0"`) yanlış ölçü basmakla aynı
	kapıya çıkar.
	"""
	ipuclari = hints(index, context=context)
	return {
		"url": seo_fields.get("file_url", ""),
		"alt": seo_fields.get("alt", ""),
		"caption": seo_fields.get("caption", ""),
		"title": seo_fields.get("title", ""),
		"width": seo_fields.get("width") or 0,
		"height": seo_fields.get("height") or 0,
		**ipuclari,
	}


def gallery_payload(seo_fields_list: list[dict], *, context: str = "gallery") -> list[dict[str, Any]]:
	"""Sıralı görsel listesi — ipuçları sıraya göre üretilir."""
	return [
		image_payload(alanlar, index=i, context=context) for i, alanlar in enumerate(seo_fields_list or [])
	]
