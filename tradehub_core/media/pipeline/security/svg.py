"""T-131 — SVG sanitize: script / handler / harici referans / gömülü font temizliği.

BU MODÜL YENİ BİR POLİTİKA TASARLAMAZ
=====================================
Kural zaten yazılı ve ölçülmüş durumda; bu dosya onun KOD KARŞILIĞIDIR:

    docs/standards/logo.md §6.2            SVG-1…SVG-10 (10 madde)
    tradehub_core/media/pipeline/policy/slots/brand-logo.json   `logo.svg_policy` bloğu
    tradehub_core/media/pipeline/policy/slots/seller-logo.json  aynı blok (`identical_to` notu)

Sabitler (izinli element/attribute listeleri, 256 düğüm, 32 KiB) buraya elle
kopyalanmadı: mümkünse slot JSON'undan OKUNUR (`policy_yukle()`), okunamazsa
modül içindeki ayna kullanılır ve `tests/test_svg_sanitize.py` ayrışmayı
düşürür. İki yerde iki liste tutmak, "sanitize'in iki kod yolu olması"dır ve
`brand-logo.json` bunu açıkça "bu güvenlik açığının klasik doğuş yeri" diye
işaretlemiş.

BUGÜN SVG KABUL EDİLMİYOR — bu modül onu AÇMAZ
==============================================
Üretimde iki bağımsız kapı SVG'yi reddediyor ve **bu modül ikisine de
dokunmaz**:

    tradehub_core/utils/security.py:27-44   `_DENIED_EXTENSIONS` ∋ ".svg", ".svgz"
    tradehub_core/media/upload_policy.py:190 `_DANGEROUS_MARKERS` ∋ b"<svg"

`logo.md` SVG-1: kapılar ancak slot kayıt defteri kurulduktan sonra ve YALNIZ
`seller.logo` / `brand.logo` kapsamında birlikte açılır. `brand-logo.json`
`svg_policy.enabled = false`. Bu modül o açılışın ÖN KOŞULUDUR: sanitize
olmadan kapı açılamaz. Bugünkü değeri iki yerde:

  1. `data:image/svg+xml;base64,…` kanalı (SVG-10). `seed_demo_data.py:231-245`
     SVG'yi alan değerine yazıyor, `File` kaydı açılmadığı için iki kapı da
     devre dışı. Bu içerik BUGÜN denetlenebilir: `sanitize_data_uri()`.
  2. Denetim/rapor: `scan()` bir SVG'nin hangi kuralları ihlal ettiğini
     dosyayı değiştirmeden söyler.

TASARIM — neden "temizle", neden "reddet"
=========================================
İki farklı karar var ve `logo.md` ikisini ayırmış:

    REDDET (sanitize bile edilmez)   DTD/ENTITY, .svgz, bozuk XML, tavan aşımı
    TEMİZLE (dosya kabul, içerik kırpılır)   element/attribute allowlist ihlali

Gerekçe SVG-5'te yazılı: entity genişletmesi (billion laughs) sanitize
edilmeden ÖNCE bellek tüketir — temizlemeye çalışmak yerine reddetmek doğru
SIRADIR. Allowlist ihlali ise kullanıcı hatasıdır (Illustrator'ın eklediği
`<metadata>`), dosyayı reddetmek gereksiz sürtünme olurdu.

**Ayrıştırıcı.** `defusedxml` proje bağımlılığıdır (`pyproject.toml`
`defusedxml>=0.7`) ve konteynerde 0.7.1 kurulu ÖLÇÜLDÜ. Yoksa modül yine
çalışır ama `SvgSanitizeResult.parser == "stdlib"` döner ve DTD/ENTITY savunması
YALNIZ ham bayt ön taramasına dayanır. Bu fark sonuç nesnesinde açıkça taşınır —
"güvenli sanıldı ama zayıf ayrıştırıcıydı" durumu sessiz kalmaz.

**Gömülü font.** `logo.md` allowlist'i `font`, `font-face`, `font-face-src`,
`font-face-uri`, `glyph`, `missing-glyph` elementlerinin HİÇBİRİNİ içermez →
izin listesi bunları zaten siler. Ayrıca `@font-face` yalnız `<style>` içinde
ya da `style` attribute'unda taşınabilir; ikisi de allowlist dışıdır. Yani
"gömülü font yasak" kuralı üç kez birden karşılanır; `FONT_ELEMENTS` sabiti
raporlamada ayrı sayılsın diye tutuluyor (operatör "font silindi" görsün).

`import frappe` YOKTUR — `media_engine` çekirdek kuralı.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import xml.etree.ElementTree as StdET
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

try:  # pragma: no cover - konteynerde kurulu (0.7.1 ÖLÇÜLDÜ), yerelde olmayabilir
	from defusedxml.ElementTree import fromstring as _defused_fromstring

	DEFUSEDXML_AVAILABLE: bool = True
except Exception:  # pragma: no cover
	_defused_fromstring = None  # type: ignore[assignment]
	DEFUSEDXML_AVAILABLE = False

SVG_NS: str = "http://www.w3.org/2000/svg"
XLINK_NS: str = "http://www.w3.org/1999/xlink"
XML_NS: str = "http://www.w3.org/XML/1998/namespace"

#: `logo.md` §6.2 SVG-4 izinli element listesi. Slot JSON'undan okunamazsa ayna.
_AYNA_ELEMENTS: Tuple[str, ...] = (
	"svg",
	"g",
	"path",
	"rect",
	"circle",
	"ellipse",
	"line",
	"polyline",
	"polygon",
	"defs",
	"linearGradient",
	"radialGradient",
	"stop",
	"clipPath",
	"mask",
	"use",
	"title",
	"desc",
	"symbol",
)

#: `logo.md` §6.2 SVG-4 izinli attribute listesi (ayna).
_AYNA_ATTRIBUTES: Tuple[str, ...] = (
	"viewBox",
	"xmlns",
	"width",
	"height",
	"d",
	"x",
	"y",
	"x1",
	"y1",
	"x2",
	"y2",
	"cx",
	"cy",
	"r",
	"rx",
	"ry",
	"points",
	"transform",
	"fill",
	"fill-rule",
	"fill-opacity",
	"stroke",
	"stroke-width",
	"stroke-linecap",
	"stroke-linejoin",
	"stroke-dasharray",
	"stroke-opacity",
	"opacity",
	"offset",
	"stop-color",
	"stop-opacity",
	"gradientUnits",
	"gradientTransform",
	"clip-path",
	"mask",
	"id",
	"class",
)

#: Ölçülen tavanlar — `logo.md` §6.2 SVG-9 tablosu.
_AYNA_MAX_BYTES: int = 32768
_AYNA_MAX_NODES: int = 256

#: `<use>` dışındaki hiçbir elementte href'e ihtiyaç yok; `use` allowlist'te ve
#: `#id` referansı olmadan işe yaramaz. SVG-4 attribute tablosunda `href`
#: GEÇMİYOR ama aynı maddenin `href_rule` satırı "yalnız '#' ile başlayan değer
#: korunur" diyor. En DAR okuma budur: href yalnız `use` üzerinde ve yalnız
#: `#…` değeriyle yaşar. Bu bilinçli yorum; `tests/test_svg_sanitize.py`
#: davranışı kilitliyor.
HREF_ALLOWED_ELEMENTS: FrozenSet[str] = frozenset({"use"})
HREF_ATTRIBUTES: FrozenSet[str] = frozenset({"href", f"{{{XLINK_NS}}}href"})

#: Yalnız RAPORLAMA için ayrı sayılan gruplar. İzin listesi bunları zaten
#: siler; ayrı sayılmalarının nedeni operatörün "ne silindi" sorusuna
#: "aktif içerik" / "harici referans" / "gömülü font" diye cevap alabilmesi.
SCRIPT_ELEMENTS: FrozenSet[str] = frozenset({"script", "handler", "listener"})
EXTERNAL_ELEMENTS: FrozenSet[str] = frozenset(
	{"image", "foreignObject", "iframe", "embed", "object", "video", "audio", "feImage", "use"}
)
FONT_ELEMENTS: FrozenSet[str] = frozenset(
	{
		"font",
		"font-face",
		"font-face-src",
		"font-face-uri",
		"font-face-name",
		"font-face-format",
		"glyph",
		"missing-glyph",
		"hkern",
		"vkern",
		"altGlyph",
		"altGlyphDef",
		"altGlyphItem",
	}
)
ANIMATION_ELEMENTS: FrozenSet[str] = frozenset(
	{"animate", "animateTransform", "animateMotion", "animateColor", "set", "discard", "mpath"}
)
STYLE_ELEMENTS: FrozenSet[str] = frozenset({"style"})

#: Çizim üreten elementler. Sanitize sonrası bunlardan HİÇBİRİ kalmadıysa
#: dosya "temizlendikten sonra çizilecek bir şey kalmadı" sayılır
#: (`brand-logo.json` messages.tr.svg_empty_after_sanitize).
DRAWING_ELEMENTS: FrozenSet[str] = frozenset(
	{"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "use", "stop"}
)

# ── Ret kodları ─────────────────────────────────────────────────────────
#
# `logo.md` SVG-5 kodu birebir korunuyor: `logo_svg_dtd_forbidden`. Geri
# kalanlar `brand-logo.json` `messages` anahtarlarıyla eşleşir ki kullanıcıya
# gösterilecek metin veri dosyasında kalsın, kodda değil.

KOD_OK: str = "ok"
KOD_DTD_FORBIDDEN: str = "logo_svg_dtd_forbidden"
KOD_NOT_WELL_FORMED: str = "svg_not_well_formed"
KOD_NOT_SVG: str = "svg_root_not_svg"
KOD_COMPRESSED: str = "svg_compressed_forbidden"
KOD_TOO_COMPLEX: str = "svg_too_complex"
KOD_TOO_LARGE: str = "svg_too_large"
KOD_INPUT_TOO_LARGE: str = "svg_input_too_large"
KOD_VIEWBOX_MISSING: str = "svg_viewbox_missing"
KOD_EMPTY_AFTER_SANITIZE: str = "svg_empty_after_sanitize"

#: Ret kodu → `brand-logo.json` `messages.<dil>` anahtarı. Kodun kendisi
#: anahtar olmayanlar için köprü; metin veri dosyasında kalır.
MESAJ_ANAHTARI: Dict[str, str] = {
	KOD_DTD_FORBIDDEN: "svg_dtd_forbidden",
	KOD_NOT_WELL_FORMED: "svg_dtd_forbidden",
	KOD_TOO_COMPLEX: "svg_too_complex",
	KOD_EMPTY_AFTER_SANITIZE: "svg_empty_after_sanitize",
}

#: `#` ile başlamayan her href değeri silinir (SVG-4 `href_rule`). Bu desen
#: yalnız RAPORLAMA için: kararı `#` kontrolü verir, desen "neden silindi"
#: sorusunu cevaplar.
_TEHLIKELI_SEMA = re.compile(
	rb"^\s*(javascript|vbscript|data|file|http|https|ftp)\s*:", re.IGNORECASE
)

#: Ham bayt ön taraması (SVG-5). Yorum içinde geçen bir `<!DOCTYPE` de
#: reddedilir — YANLIŞ POZİTİF bilinçlidir: fail-closed. Meşru bir logo
#: dosyasında DOCTYPE bulunmaz; Illustrator'ın eskiden yazdığı DTD satırı
#: "sade SVG olarak yeniden dışa aktar" ile çözülür ve kullanıcı mesajı
#: (`svg_dtd_forbidden`) tam olarak bunu söylüyor.
_DTD_DESENI = re.compile(rb"<!\s*(DOCTYPE|ENTITY|ELEMENT|ATTLIST|NOTATION)", re.IGNORECASE)
_GZIP_MAGIC: bytes = b"\x1f\x8b"


@dataclass(frozen=True)
class SvgPolicy:
	"""Sanitize parametreleri — kaynağı `tradehub_core/media/pipeline/policy/slots/*.json`."""

	allowed_elements: FrozenSet[str] = frozenset(_AYNA_ELEMENTS)
	allowed_attributes: FrozenSet[str] = frozenset(_AYNA_ATTRIBUTES)
	max_bytes: int = _AYNA_MAX_BYTES
	max_nodes: int = _AYNA_MAX_NODES
	require_viewbox: bool = True
	allow_svgz: bool = False
	#: SVG-9 tavanları ÇIKTI üzerinde ölçülür; girdiye ayrı bir tavan gerekir,
	#: yoksa 50 MB'lık bir dosya ayrıştırıcıya kadar gider. `max_bytes`'ın 8
	#: katı: sanitize gerçekten çok şey siliyorsa (Illustrator metadata'sı)
	#: meşru dosya bu payın içinde kalır. Bu tavan `logo.md`'de YOKTUR, bu
	#: modülün EKLEDİĞİ savunmadır ve raporlanır.
	max_input_bytes: int = _AYNA_MAX_BYTES * 8
	#: Kaynak künyesi — sabitler JSON'dan mı geldi ayna mı.
	kaynak: str = "ayna"

	def with_(self, **degisiklik: Any) -> "SvgPolicy":
		from dataclasses import replace

		return replace(self, **degisiklik)


@dataclass(frozen=True)
class Bulgu:
	"""Tek bir temizleme/ret olayı. `tur` makine okur, `ayrinti` insan okur."""

	tur: str  # element | attribute | href | dtd | limit | namespace | text
	ad: str
	ayrinti: str = ""

	def to_dict(self) -> Dict[str, str]:
		return {"kind": self.tur, "name": self.ad, "detail": self.ayrinti}


TUR_ELEMENT: str = "element"
TUR_ATTRIBUTE: str = "attribute"
TUR_HREF: str = "href"
TUR_DTD: str = "dtd"
TUR_LIMIT: str = "limit"
TUR_NAMESPACE: str = "namespace"


@dataclass
class SvgSanitizeResult:
	"""Sanitize sonucu. `ok=False` ise `content` BOŞTUR — yarım çıktı verilmez."""

	ok: bool
	kod: str = KOD_OK
	content: bytes = b""
	node_count: int = 0
	bytes_in: int = 0
	bytes_out: int = 0
	bulgular: List[Bulgu] = field(default_factory=list)
	parser: str = "none"
	#: Silinen grupların sayacı — operatör raporu için.
	sayac: Dict[str, int] = field(default_factory=dict)

	@property
	def temizlendi(self) -> bool:
		"""Dosya kabul edildi ama İÇERİĞİ değiştirildi mi."""
		return self.ok and bool(self.bulgular)

	@property
	def mesaj_anahtari(self) -> str:
		return MESAJ_ANAHTARI.get(self.kod, self.kod)

	def to_dict(self) -> Dict[str, Any]:
		return {
			"ok": self.ok,
			"code": self.kod,
			"message_key": self.mesaj_anahtari,
			"node_count": self.node_count,
			"bytes_in": self.bytes_in,
			"bytes_out": self.bytes_out,
			"parser": self.parser,
			"sanitized": self.temizlendi,
			"counters": dict(self.sayac),
			"findings": [b.to_dict() for b in self.bulgular],
		}


# ── Politika yükleme ────────────────────────────────────────────────────


def _slot_dosyasi(slot: str) -> str:
	return os.path.join(os.path.dirname(os.path.dirname(__file__)), "policy", "slots", f"{slot}.json")


def policy_yukle(slot: str = "brand-logo") -> SvgPolicy:
	"""Slot JSON'undaki `logo.svg_policy` bloğunu `SvgPolicy`'ye çevirir.

	Dosya yoksa/bozuksa AYNA döner (`kaynak="ayna"`), istisna fırlatmaz — bir
	JSON hatası sanitize'i devre dışı bırakamaz. Ayrışma testle yakalanır.
	"""
	yol = _slot_dosyasi(slot)
	try:
		with open(yol, encoding="utf-8") as f:
			veri = json.load(f)
	except Exception:
		return SvgPolicy()

	blok = ((veri.get("logo") or {}).get("svg_policy")) or {}
	kabul = veri.get("accept") or {}
	elemanlar = blok.get("allowed_elements") or list(_AYNA_ELEMENTS)
	attrler = blok.get("allowed_attributes") or list(_AYNA_ATTRIBUTES)
	max_b = int(kabul.get("max_bytes_svg") or _AYNA_MAX_BYTES)

	# Düğüm tavanı JSON'da bir `on_violation` kuralının içinde (`svg_node_count`);
	# yapısı slotlar arasında değişebildiği için sayı BULUNAMAZSA aynaya düşülür.
	max_n = _AYNA_MAX_NODES
	for kural in _kurallari_gez(veri):
		if kural.get("rule") == "svg_node_count":
			for anahtar in ("max", "max_nodes", "limit", "threshold", "value"):
				if isinstance(kural.get(anahtar), int):
					max_n = int(kural[anahtar])
					break
	return SvgPolicy(
		allowed_elements=frozenset(str(e) for e in elemanlar),
		allowed_attributes=frozenset(str(a) for a in attrler),
		max_bytes=max_b,
		max_nodes=max_n,
		require_viewbox=bool(blok.get("viewbox_required", True)),
		allow_svgz=bool(blok.get("svgz_allowed", False)),
		max_input_bytes=max_b * 8,
		kaynak=f"slot:{slot}",
	)


def _kurallari_gez(o: Any):
	"""JSON ağacındaki `{"rule": …}` sözlüklerini yüzeye çıkarır."""
	if isinstance(o, dict):
		if "rule" in o:
			yield o
		for v in o.values():
			yield from _kurallari_gez(v)
	elif isinstance(o, list):
		for v in o:
			yield from _kurallari_gez(v)


DEFAULT_POLICY: SvgPolicy = SvgPolicy()


# ── Yardımcılar ─────────────────────────────────────────────────────────


def _yerel_ad(etiket: Any) -> str:
	"""`{ns}tag` → `tag`. Namespace'siz etiket olduğu gibi döner."""
	if not isinstance(etiket, str):
		return ""
	return etiket.rsplit("}", 1)[-1] if etiket.startswith("{") else etiket


def _namespace(etiket: Any) -> str:
	if isinstance(etiket, str) and etiket.startswith("{"):
		return etiket[1:].split("}", 1)[0]
	return ""


def is_svg(content: bytes) -> bool:
	"""İçerik SVG'ye BENZİYOR mu — kesin karar değil, ucuz ön eleme."""
	bas = (content or b"")[:1024].lstrip(b" \t\r\n\xef\xbb\xbf").lower()
	return bas.startswith(b"<svg") or (bas.startswith(b"<?xml") and b"<svg" in bas)


def _ust_haritasi(kok: StdET.Element) -> Dict[int, StdET.Element]:
	"""`id(cocuk) → ebeveyn`. ElementTree'de `getparent()` yok."""
	harita: Dict[int, StdET.Element] = {}
	yigin = [kok]
	while yigin:
		el = yigin.pop()
		for cocuk in list(el):
			harita[id(cocuk)] = el
			yigin.append(cocuk)
	return harita


# ── Ana giriş ───────────────────────────────────────────────────────────


def sanitize(content: bytes, *, policy: Optional[SvgPolicy] = None) -> SvgSanitizeResult:
	"""SVG'yi `logo.md` §6.2 boru hattına göre temizler.

	Sıra `logo.md` SVG-3'teki adım listesiyle BİREBİR aynıdır (adım 1 slot
	kontrolü ve adım 8-9 `File` yazımı bu modülün DIŞINDA, çağıranın işi):

	    2. .svgz mi                → RET  KOD_COMPRESSED
	    3. XML iyi biçimli mi      → RET  KOD_NOT_WELL_FORMED
	    4. DTD / ENTITY var mı     → RET  KOD_DTD_FORBIDDEN
	    5. allowlist sanitize
	    6. düğüm sayısı ≤ max_nodes → RET  KOD_TOO_COMPLEX
	    7. çıktı ≤ max_bytes        → RET  KOD_TOO_LARGE

	Adım 4 adım 3'ten SONRA listelenmiş olsa da ham bayt ön taraması
	ayrıştırmadan ÖNCE çalışır: billion-laughs'ı ayrıştırıcıya vermek, ret
	kararını bellek tükendikten sonra almak olurdu (SVG-5 gerekçesi).

	İstisna fırlatmaz.
	"""
	pol = policy or DEFAULT_POLICY
	ham = content or b""
	sonuc = SvgSanitizeResult(ok=False, bytes_in=len(ham))
	bulgular = sonuc.bulgular

	# Adım 2 — .svgz (SVG-6)
	if ham.startswith(_GZIP_MAGIC) and not pol.allow_svgz:
		bulgular.append(Bulgu(TUR_LIMIT, "gzip", "svgz sanitize edilmeden reddedilir (SVG-6)"))
		sonuc.kod = KOD_COMPRESSED
		return sonuc

	if not ham.strip():
		sonuc.kod = KOD_NOT_WELL_FORMED
		bulgular.append(Bulgu(TUR_LIMIT, "empty", "icerik bos"))
		return sonuc

	# Girdi tavanı — bu modülün EKLEDİĞİ savunma (bkz. SvgPolicy.max_input_bytes)
	if len(ham) > pol.max_input_bytes:
		bulgular.append(
			Bulgu(TUR_LIMIT, "input_bytes", f"{len(ham)} > {pol.max_input_bytes}")
		)
		sonuc.kod = KOD_INPUT_TOO_LARGE
		return sonuc

	# Adım 4 (öne alındı) — DTD / ENTITY (SVG-5)
	m = _DTD_DESENI.search(ham)
	if m:
		bulgular.append(Bulgu(TUR_DTD, m.group(1).decode("ascii", "replace").upper(), "SVG-5"))
		sonuc.kod = KOD_DTD_FORBIDDEN
		return sonuc

	# Adım 3 — ayrıştırma
	kok, parser_adi, hata = _ayristir(ham)
	sonuc.parser = parser_adi
	if kok is None:
		bulgular.append(Bulgu(TUR_LIMIT, "parse", (hata or "")[:200]))
		sonuc.kod = KOD_NOT_WELL_FORMED
		return sonuc

	if _yerel_ad(kok.tag) != "svg" or _namespace(kok.tag) not in ("", SVG_NS):
		bulgular.append(Bulgu(TUR_NAMESPACE, str(kok.tag)[:80], "kok element svg degil"))
		sonuc.kod = KOD_NOT_SVG
		return sonuc

	# Adım 5 — allowlist sanitize
	sayac: Dict[str, int] = {}
	dugum = _temizle(kok, pol, bulgular, sayac)
	sonuc.sayac = sayac
	sonuc.node_count = dugum

	# Adım 6 — düğüm tavanı. viewBox kontrolünden ÖNCE: ikisi de SVG-9'da ama
	# `logo.md` SVG-3 boru hattı düğüm sayısını 6. adım olarak sayıyor ve
	# ölçülen karşı örnek (`public/icons/ui.svg`, 463 düğüm) için doğru ret
	# kodu `svg_too_complex`'tir — "viewBox eksik" demek kullanıcıyı yanlış
	# düzeltmeye yönlendirirdi.
	if dugum > pol.max_nodes:
		bulgular.append(Bulgu(TUR_LIMIT, "node_count", f"{dugum} > {pol.max_nodes}"))
		sonuc.kod = KOD_TOO_COMPLEX
		return sonuc

	# viewBox (SVG-9)
	if pol.require_viewbox and not _viewbox_var(kok):
		bulgular.append(Bulgu(TUR_ATTRIBUTE, "viewBox", "zorunlu (SVG-9)"))
		sonuc.kod = KOD_VIEWBOX_MISSING
		return sonuc

	# Çizilecek bir şey kaldı mı
	if not _cizim_var(kok):
		bulgular.append(Bulgu(TUR_LIMIT, "drawing", "sanitize sonrasi cizim elementi yok"))
		sonuc.kod = KOD_EMPTY_AFTER_SANITIZE
		return sonuc

	cikti = _serilestir(kok)
	sonuc.bytes_out = len(cikti)

	# Adım 7 — bayt tavanı (ÇIKTI üzerinde — SVG-9)
	if len(cikti) > pol.max_bytes:
		bulgular.append(Bulgu(TUR_LIMIT, "output_bytes", f"{len(cikti)} > {pol.max_bytes}"))
		sonuc.kod = KOD_TOO_LARGE
		return sonuc

	sonuc.ok = True
	sonuc.kod = KOD_OK
	sonuc.content = cikti
	return sonuc


def scan(content: bytes, *, policy: Optional[SvgPolicy] = None) -> SvgSanitizeResult:
	"""Salt okunur denetim — `sanitize()` ile aynı kararı verir, çıktı üretmez.

	Envanter taraması ve `data:` URI denetimi (SVG-10) için: dosyayı
	değiştirmeden "bu dosya kabul edilir miydi, neyi silinirdi" sorusunu
	cevaplar. Ayrı bir kod yolu DEĞİLDİR — `sanitize()`'i çağırır ve yalnız
	içeriği düşürür; ikinci bir uygulama, ayrışan ikinci bir kural demekti.
	"""
	sonuc = sanitize(content, policy=policy)
	sonuc.content = b""
	return sonuc


_DATA_URI_DESENI = re.compile(
	r"^\s*data:image/svg\+xml\s*(;[^,]*)?,", re.IGNORECASE
)


def sanitize_data_uri(deger: str, *, policy: Optional[SvgPolicy] = None) -> SvgSanitizeResult:
	"""`data:image/svg+xml;base64,…` değerini çözüp sanitize eder (SVG-10).

	`seed_demo_data.py:231-245` kanalıyla DB'ye yazılan logolar `File` kaydı
	açmadığı için iki yükleme kapısının da DIŞINDA kalıyor. Bu fonksiyon o
	içeriği BUGÜN denetlenebilir kılar; alan değerini değiştirmek çağıranın
	kararıdır.
	"""
	m = _DATA_URI_DESENI.match(deger or "")
	if not m:
		sonuc = SvgSanitizeResult(ok=False, kod=KOD_NOT_SVG, bytes_in=len(deger or ""))
		sonuc.bulgular.append(Bulgu(TUR_LIMIT, "data_uri", "data:image/svg+xml degil"))
		return sonuc

	govde = (deger or "")[m.end() :]
	base64_mi = ";base64" in (m.group(1) or "").lower()
	try:
		if base64_mi:
			ham = base64.b64decode(govde, validate=False)
		else:
			from urllib.parse import unquote_to_bytes

			ham = unquote_to_bytes(govde)
	except (binascii.Error, ValueError) as exc:
		sonuc = SvgSanitizeResult(ok=False, kod=KOD_NOT_WELL_FORMED, bytes_in=len(deger or ""))
		sonuc.bulgular.append(Bulgu(TUR_LIMIT, "data_uri_decode", str(exc)[:120]))
		return sonuc
	return sanitize(ham, policy=policy)


# ── İç uygulama ─────────────────────────────────────────────────────────


def _ayristir(ham: bytes) -> Tuple[Optional[StdET.Element], str, str]:
	"""`(kok, parser_adi, hata)`. `defusedxml` varsa o kullanılır."""
	if DEFUSEDXML_AVAILABLE and _defused_fromstring is not None:
		try:
			return _defused_fromstring(ham), "defusedxml", ""
		except Exception as exc:
			return None, "defusedxml", f"{type(exc).__name__}: {exc}"
	try:
		# Ham bayt ön taraması DTD/ENTITY'yi zaten reddetti; stdlib burada
		# yalnız iyi-biçimlilik kontrolü yapıyor. Yine de `parser` alanı
		# "stdlib" döner ki çağıran savunmanın zayıf olduğunu bilsin.
		return StdET.fromstring(ham), "stdlib", ""
	except Exception as exc:
		return None, "stdlib", f"{type(exc).__name__}: {exc}"


def _grup_say(ad: str, sayac: Dict[str, int]) -> None:
	if ad in SCRIPT_ELEMENTS:
		sayac["script"] = sayac.get("script", 0) + 1
	if ad in FONT_ELEMENTS:
		sayac["font"] = sayac.get("font", 0) + 1
	if ad in ANIMATION_ELEMENTS:
		sayac["animation"] = sayac.get("animation", 0) + 1
	if ad in STYLE_ELEMENTS:
		sayac["style"] = sayac.get("style", 0) + 1
	if ad in EXTERNAL_ELEMENTS:
		sayac["external"] = sayac.get("external", 0) + 1
	if ad.startswith("fe") and len(ad) > 2 and ad[2:3].isupper():
		sayac["filter"] = sayac.get("filter", 0) + 1


def _temizle(
	kok: StdET.Element, pol: SvgPolicy, bulgular: List[Bulgu], sayac: Dict[str, int]
) -> int:
	"""Ağacı YERİNDE temizler; kalan düğüm sayısını döndürür.

	Yaklaşım izin listesidir: izinli olmayan element ALT AĞACIYLA BİRLİKTE
	silinir. Yalnız elementi silip çocuklarını yukarı taşımak, `<foreignObject>`
	içindeki `<iframe>`'i kurtarmak olurdu.
	"""
	sayi = 0
	yigin: List[StdET.Element] = [kok]
	while yigin:
		el = yigin.pop()
		sayi += 1
		_attribute_temizle(el, pol, bulgular, sayac)
		# Metin dışı içerik: `<title>`/`<desc>` metni zararsız, ötekiler zaten
		# silindiği için ayrıca dokunulmuyor.
		for cocuk in list(el):
			ad = _yerel_ad(cocuk.tag)
			ns = _namespace(cocuk.tag)
			if not isinstance(cocuk.tag, str):  # yorum / PI (özel parser'da)
				el.remove(cocuk)
				bulgular.append(Bulgu(TUR_ELEMENT, "comment_or_pi", "silindi"))
				continue
			if ns not in ("", SVG_NS):
				el.remove(cocuk)
				bulgular.append(Bulgu(TUR_NAMESPACE, ad, f"ns={ns}"))
				sayac["namespace"] = sayac.get("namespace", 0) + 1
				continue
			if ad not in pol.allowed_elements:
				el.remove(cocuk)
				bulgular.append(Bulgu(TUR_ELEMENT, ad, "izin listesinde yok"))
				sayac["element"] = sayac.get("element", 0) + 1
				_grup_say(ad, sayac)
				continue
			yigin.append(cocuk)
	return sayi


def _attribute_temizle(
	el: StdET.Element, pol: SvgPolicy, bulgular: List[Bulgu], sayac: Dict[str, int]
) -> None:
	ad = _yerel_ad(el.tag)
	for anahtar in list(el.attrib):
		yerel = _yerel_ad(anahtar)
		ns = _namespace(anahtar)
		deger = el.attrib.get(anahtar, "")

		# `xml:` namespace'i (xml:space, xml:lang) izin listesinde yok → silinir.
		# href ise özel kuralla değerlendirilir (SVG-4 href_rule).
		if anahtar in HREF_ATTRIBUTES or (yerel == "href" and ns in ("", XLINK_NS)):
			if ad in HREF_ALLOWED_ELEMENTS and deger.startswith("#"):
				continue
			del el.attrib[anahtar]
			bulgular.append(
				Bulgu(
					TUR_HREF,
					yerel,
					_href_sebebi(ad, deger),
				)
			)
			sayac["href"] = sayac.get("href", 0) + 1
			continue

		# `on*` ikinci tarama (SVG-4: "isim-öneki kuralıyla ikinci kez taranır").
		# İzin listesi bunu zaten siler; ayrı sayılması operatör raporu için.
		if yerel.lower().startswith("on"):
			del el.attrib[anahtar]
			bulgular.append(Bulgu(TUR_ATTRIBUTE, yerel, "olay isleyici"))
			sayac["handler"] = sayac.get("handler", 0) + 1
			continue

		if ns not in ("",) or yerel not in pol.allowed_attributes:
			del el.attrib[anahtar]
			bulgular.append(Bulgu(TUR_ATTRIBUTE, yerel, "izin listesinde yok"))
			sayac["attribute"] = sayac.get("attribute", 0) + 1
			if yerel.lower() == "style":
				sayac["style"] = sayac.get("style", 0) + 1
			continue

		# İzinli attribute'un DEĞERİ hâlâ tehlikeli olabilir: `fill="url(http…)"`
		# harici istek atar. `url(#…)` (aynı dosya içi gradient/mask) meşrudur.
		if _deger_tehlikeli(deger):
			del el.attrib[anahtar]
			bulgular.append(Bulgu(TUR_ATTRIBUTE, yerel, "deger harici referans/sema"))
			sayac["external_value"] = sayac.get("external_value", 0) + 1


def _href_sebebi(element: str, deger: str) -> str:
	if element not in HREF_ALLOWED_ELEMENTS:
		return f"href yalnız <use> uzerinde (bulundu: <{element}>)"
	m = _TEHLIKELI_SEMA.match(deger.encode("utf-8", "replace"))
	if m:
		return f"sema={m.group(1).decode('ascii', 'replace').lower()}:"
	return "'#' ile baslamiyor"


_URL_FONKSIYONU = re.compile(r"url\(\s*['\"]?([^'\")]*)", re.IGNORECASE)


def _deger_tehlikeli(deger: str) -> bool:
	"""İzinli bir attribute'un değeri harici istek ya da kod taşıyor mu."""
	if not deger:
		return False
	ham = deger.encode("utf-8", "replace")
	if _TEHLIKELI_SEMA.match(ham):
		return True
	dusuk = deger.lower()
	if "javascript:" in dusuk or "vbscript:" in dusuk or "expression(" in dusuk:
		return True
	for m in _URL_FONKSIYONU.finditer(deger):
		hedef = (m.group(1) or "").strip()
		if not hedef.startswith("#"):
			return True
	return False


def _viewbox_var(kok: StdET.Element) -> bool:
	for anahtar, deger in kok.attrib.items():
		if _yerel_ad(anahtar) == "viewBox" and (deger or "").strip():
			return True
	return False


def _cizim_var(kok: StdET.Element) -> bool:
	for el in kok.iter():
		if _yerel_ad(el.tag) in DRAWING_ELEMENTS:
			return True
	return False


def _serilestir(kok: StdET.Element) -> bytes:
	"""Temiz ağacı bayta çevirir. `xmlns` ön eki olmadan yazılır.

	`register_namespace("", SVG_NS)` GLOBAL bir kayıttır; `tostring` çağrısı
	sırasında kısa süreliğine ayarlanıp geri alınır ki bu modülü import eden
	başka bir kodun serileştirmesi etkilenmesin.
	"""
	onceki = dict(StdET._namespace_map)  # type: ignore[attr-defined]
	try:
		StdET.register_namespace("", SVG_NS)
		StdET.register_namespace("xlink", XLINK_NS)
		metin = StdET.tostring(kok, encoding="unicode")
	finally:
		StdET._namespace_map.clear()  # type: ignore[attr-defined]
		StdET._namespace_map.update(onceki)  # type: ignore[attr-defined]
	return metin.encode("utf-8")


__all__ = [
	"ANIMATION_ELEMENTS",
	"DEFAULT_POLICY",
	"DEFUSEDXML_AVAILABLE",
	"DRAWING_ELEMENTS",
	"EXTERNAL_ELEMENTS",
	"FONT_ELEMENTS",
	"HREF_ALLOWED_ELEMENTS",
	"KOD_COMPRESSED",
	"KOD_DTD_FORBIDDEN",
	"KOD_EMPTY_AFTER_SANITIZE",
	"KOD_INPUT_TOO_LARGE",
	"KOD_NOT_SVG",
	"KOD_NOT_WELL_FORMED",
	"KOD_OK",
	"KOD_TOO_COMPLEX",
	"KOD_TOO_LARGE",
	"KOD_VIEWBOX_MISSING",
	"SCRIPT_ELEMENTS",
	"SVG_NS",
	"XLINK_NS",
	"Bulgu",
	"SvgPolicy",
	"SvgSanitizeResult",
	"is_svg",
	"policy_yukle",
	"sanitize",
	"sanitize_data_uri",
	"scan",
]
