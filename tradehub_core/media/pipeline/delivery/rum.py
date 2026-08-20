"""T-123 — Gerçek kullanıcı ölçümü (RUM) toplama şeması. PII YOK, örneklemli.

NEDEN
-----
`docs/reports/03-performans-taban-cizgisi.md` §6.2 açıkça yazıyor:
**"Gerçek kullanıcı (field) verisi — ÖLÇÜLEMEDİ"**. Elimizdeki tüm LCP/CLS
sayıları laboratuvar (lab) ölçümüdür: tek makine, emüle edilmiş Slow 4G, sıcak
ya da temizlenmiş önbellek. Aynı belge §6.3'te INP'nin de ölçülemediğini
kaydediyor.

Faz 12'nin iddiası "ürün detay 13,14 MB → X MB" biçiminde. Bu iddia lab'da
kanıtlanabilir ama **doğrulanamaz**: gerçek kullanıcıların cihaz kırılımı, ağı
ve önbellek durumu bilinmiyor. Bu modül, o doğrulamanın veri sözleşmesidir.

BU MODÜL NE YAPAR, NE YAPMAZ
----------------------------
YAPAR : gelen ölçüm kaydını **doğrular**, PII taşıyan alanları **reddeder**,
        örneklem kararını **deterministik** verir, p75 toplar.
YAPMAZ: HTTP ucu açmaz, veritabanına yazmaz, `frappe` içe aktarmaz. Uç
        (`api/`) ve saklama (DocType) ayrı görevlerdir; bu modül ikisinin de
        altında duran saf çekirdektir ve bench olmadan test edilir.

PII KORUMASI — ÜÇ SERT KURAL
----------------------------
1. **Tam URL ASLA kabul edilmez.** Yalnız *rota şablonu* saklanır
   (`/urun/:slug`). Gerekçe ölçülmüş: `docs/reports/08-canli-olcum.md` §6 aynı
   depoda gerçek veride PII sızıntısı buldu; arama sorgusu ve sipariş
   parametresi taşıyan bir URL'i "performans verisi" diye saklamak aynı hatanın
   tekrarıdır. `route_template()` sorgu dizgesini ve yol parametrelerini SİLER.
2. **Kimlik alanı yok.** `user`, `email`, `ip`, `session_id`, `cookie`,
   `user_agent` alanları gelirse kayıt REDDEDİLİR (sessizce düşürülmez —
   gönderen taraf hatasını görmeli). Cihaz bilgisi yalnız kaba kova olarak
   (`device_class`, `viewport_bucket`, `dpr`) tutulur.
3. **Ham User-Agent saklanmaz.** İstemci `navigator.userAgentData` benzeri bir
   kaynaktan çıkardığı KABA sınıfı gönderir; serbest metin gelirse reddedilir.

ÖRNEKLEM
--------
Her kayıt `sample_rate` taşır ve toplayıcı bunu **bölerek** genelleştirir; oran
kayda yazılmazsa toplanan sayı anlamsızdır. Karar `decide()` ile
**deterministiktir**: aynı oturum tokeni aynı oranda hep aynı kararı alır, yoksa
tek bir oturumun bazı metrikleri düşer ve p75 çarpıtılır.

EŞİKLER
-------
`RATING_THRESHOLDS` web.dev'in yayımladığı Core Web Vitals eşikleridir
(iyi / geliştirilmeli / kötü). Buradaki sayılar bu projede ÖLÇÜLMEDİ; dış
standarttır ve kaynağı `SOURCES` altında yazılıdır.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

# ── Sabitler ───────────────────────────────────────────────────────────

#: Toplanan metrikler. `web-vitals` kütüphanesinin adlarıyla birebir.
METRICS: Tuple[str, ...] = ("LCP", "CLS", "INP", "FCP", "TTFB")

#: Birimsiz metrikler — geri kalanı milisaniyedir.
UNITLESS: Tuple[str, ...] = ("CLS",)

#: web.dev Core Web Vitals eşikleri: (iyi_üst_sınır, geliştirilmeli_üst_sınır).
#: DIŞ STANDART — bu projede ölçülmedi.
RATING_THRESHOLDS: Dict[str, Tuple[float, float]] = {
	"LCP": (2500.0, 4000.0),
	"CLS": (0.1, 0.25),
	"INP": (200.0, 500.0),
	"FCP": (1800.0, 3000.0),
	"TTFB": (800.0, 1800.0),
}

RATING_GOOD: str = "good"
RATING_NEEDS_IMPROVEMENT: str = "needs-improvement"
RATING_POOR: str = "poor"

#: Ölçülen taban çizgisi — `docs/reports/03-performans-taban-cizgisi.md` §7,
#: mobil profil (Slow 4G + 4× CPU, önbellek temizlenmiş). LAB değeridir; RUM
#: p75'i ile karşılaştırırken bu fark akılda tutulmalı.
LAB_BASELINE_MS: Dict[str, float] = {
	"/": 776.0,
	"/urunler": 1062.0,
	"/urun/:slug": 919.0,
	"/magaza/:code": 740.0,
}

#: Aynı ölçümün CLS tarafı. Ürün listeleme 0,51 ile "kötü" (eşik 0,25).
LAB_BASELINE_CLS: Dict[str, float] = {
	"/": 0.01,
	"/urunler": 0.51,
	"/urun/:slug": 0.00,
	"/magaza/:code": 0.00,
}

#: Kabul edilen rota şablonları. Serbest rota kabul EDİLMEZ: bilinmeyen bir yol
#: gelirse `other` kovasına düşer; böylece hiçbir kullanıcıya özel yol
#: (`/hesabim/siparis/SO-00042`) veri tabanına giremez.
ROUTE_TEMPLATES: Tuple[str, ...] = (
	"/",
	"/urunler",
	"/urun/:slug",
	"/magaza/:code",
	"/kategori/:slug",
	"/marka/:slug",
	"/sepet",
	"other",
)

#: Kaba cihaz sınıfları — `simulator/devices.json` ile aynı sözlük.
DEVICE_CLASSES: Tuple[str, ...] = ("phone", "tablet", "desktop")

#: Ağ sınıfı: `navigator.connection.effectiveType`. `unknown` her zaman geçerli.
CONNECTION_TYPES: Tuple[str, ...] = ("slow-2g", "2g", "3g", "4g", "unknown")

#: Viewport kovaları (CSS px, alt sınır dâhil). Ham genişlik SAKLANMAZ:
#: nadir bir genişlik tek başına parmak izi olabilir.
VIEWPORT_BUCKETS: Tuple[int, ...] = (0, 360, 390, 430, 480, 640, 768, 1024, 1280, 1440, 1536, 1920)

#: ASLA kabul edilmeyen alan adları. Gelirse kayıt reddedilir.
FORBIDDEN_FIELDS: Tuple[str, ...] = (
	"user", "user_id", "email", "phone", "ip", "ip_address", "remote_addr",
	"session_id", "cookie", "cookies", "user_agent", "ua", "referrer",
	"url", "href", "query", "search", "customer", "order", "cart_id",
)

#: Örneklem tokeninin kabul edilen biçimi — 16-64 hex. İstemci her OTURUMDA
#: yeniden üretir; kalıcı kimlik değildir ve sunucuya ham hâliyle YAZILMAZ.
_TOKEN = re.compile(r"^[0-9a-f]{16,64}$")

#: Slot/bölge anahtarı: `sayfa/bölge` (placements.json ile aynı).
_REGION = re.compile(r"^[a-z0-9_]+/[a-z0-9_]+$")

#: Türev profil adı: `w96`, `w1280`… ya da `original` (türev seçilmedi).
_PROFILE = re.compile(r"^(w\d{2,4}|original|unknown)$")

SOURCES: Dict[str, str] = {
	"thresholds": "https://web.dev/articles/vitals — dış standart, bu projede ölçülmedi",
	"lab_baseline": "docs/reports/03-performans-taban-cizgisi.md §7",
	"pii_precedent": "docs/reports/08-canli-olcum.md §6",
	"routes": "docs/reports/03-performans-taban-cizgisi.md §2 — ölçülen dört URL",
}


#: Ret sebeplerinin KARARLI kodları. Mesaj metni insan içindir ve
#: değişebilir; metrik etiketi ise bir API'dir — panel ve alarm kuralı ona
#: bağlanır. İkisini ayırmadan `reason=<mesaj>` yazmak, mesajı düzelten ilk
#: commit'te alarmı sessizce boşaltırdı.
SEBEP_PII_ALAN: str = "pii_field"
SEBEP_GOVDE: str = "malformed_body"
SEBEP_METRIK: str = "unknown_metric"
SEBEP_DEGER: str = "invalid_value"
SEBEP_CIHAZ: str = "invalid_device_class"
SEBEP_BAGLANTI: str = "invalid_connection"
SEBEP_DPR: str = "invalid_dpr"
SEBEP_ORAN: str = "invalid_sample_rate"
SEBEP_VIEWPORT: str = "invalid_viewport"
SEBEP_TOKEN: str = "invalid_session_token"
SEBEP_BOLGE: str = "invalid_lcp_region"
SEBEP_PROFIL: str = "invalid_lcp_profile"
SEBEP_TOPLAMA: str = "aggregation_error"

REJECT_REASONS: Tuple[str, ...] = (
	SEBEP_PII_ALAN,
	SEBEP_GOVDE,
	SEBEP_METRIK,
	SEBEP_DEGER,
	SEBEP_CIHAZ,
	SEBEP_BAGLANTI,
	SEBEP_DPR,
	SEBEP_ORAN,
	SEBEP_VIEWPORT,
	SEBEP_TOKEN,
	SEBEP_BOLGE,
	SEBEP_PROFIL,
	SEBEP_TOPLAMA,
)


class RumError(ValueError):
	"""Ölçüm kaydı şemaya uymuyor ya da PII taşıyor.

	`kod` metrik etiketi olarak kullanılan KARARLI sebeptir; `str(hata)`
	insan için yazılmış açıklamadır. Varsayılan `SEBEP_GOVDE` — kodsuz
	fırlatılan eski çağrılar da metrikte bir kovaya düşsün, sessizce
	kaybolmasın.
	"""

	def __init__(self, mesaj: str, kod: str = SEBEP_GOVDE) -> None:
		super().__init__(mesaj)
		self.kod: str = kod


# ── Yardımcılar ────────────────────────────────────────────────────────


def rating(metric: str, value: float) -> str:
	"""Metriği web.dev eşiklerine göre sınıfla."""
	ad = (metric or "").upper()
	if ad not in RATING_THRESHOLDS:
		raise RumError(f"Bilinmeyen metrik: {metric!r} (beklenen: {list(METRICS)})", SEBEP_METRIK)
	iyi, orta = RATING_THRESHOLDS[ad]
	if value <= iyi:
		return RATING_GOOD
	if value <= orta:
		return RATING_NEEDS_IMPROVEMENT
	return RATING_POOR


def route_template(path: str) -> str:
	"""Ham yolu rota şablonuna indirge. Sorgu dizgesi ve kimlik SİLİNİR.

	`/urun/bonny-erzak-saklama-kabi-1-lt?utm_source=x` → `/urun/:slug`

	Tanınmayan yol `other`'a düşer — beyaz liste dışına çıkan hiçbir yol
	saklanmaz. Bu, "performans verisi" kılığında kullanıcıya özel yol
	toplanmasını yapısal olarak imkânsız kılar.
	"""
	ham = (path or "").split("?")[0].split("#")[0].strip()
	if not ham:
		return "other"
	if not ham.startswith("/"):
		ham = "/" + ham
	ham = ham.rstrip("/") or "/"
	if ham in ("/", "/urunler", "/sepet"):
		return ham
	parcalar = [p for p in ham.split("/") if p]
	if len(parcalar) == 2:
		aday = {"urun": "/urun/:slug", "magaza": "/magaza/:code",
				"kategori": "/kategori/:slug", "marka": "/marka/:slug"}.get(parcalar[0])
		if aday:
			return aday
	return "other"


def viewport_bucket(width: int) -> int:
	"""Viewport genişliğini kovaya indirge (kovanın ALT sınırı döner)."""
	try:
		w = int(width)
	except (TypeError, ValueError):
		raise RumError(f"viewport_width sayı olmalı: {width!r}", SEBEP_VIEWPORT)
	if w <= 0:
		raise RumError(f"viewport_width pozitif olmalı: {w}", SEBEP_VIEWPORT)
	uygun = [b for b in VIEWPORT_BUCKETS if b <= w]
	return max(uygun) if uygun else 0


def token_hash(token: str, *, salt: str = "") -> str:
	"""Oturum tokenini tek yönlü özetler — ham token SAKLANMAZ.

	Örneklem kararı ile saklanan kayıt arasındaki bağı koparmak için: karar ham
	tokenle verilir, kayda yalnız özetin ilk 12 hex'i (kaba, çakışmaya açık)
	yazılır. Kaba olması bilinçlidir; amaç aynı sayfa yüklemesinin metriklerini
	gruplamak, kullanıcıyı yeniden tanımak değil.
	"""
	if not _TOKEN.match(token or ""):
		raise RumError("Oturum tokeni 16-64 hex olmalı (istemci her oturumda üretir)", SEBEP_TOKEN)
	return hashlib.sha256(f"{salt}:{token}".encode()).hexdigest()[:12]


def decide(token: str, rate: float) -> bool:
	"""Bu oturum örnekleme giriyor mu — DETERMİNİSTİK.

	`rate` 0..1. Aynı token + aynı oran → hep aynı karar; böylece bir oturumun
	LCP'si alınıp INP'si düşmez (yarım oturum p75'i çarpıtır).
	"""
	oran = float(rate)
	if not 0.0 <= oran <= 1.0:
		raise RumError(f"sample_rate 0..1 aralığında olmalı: {rate!r}", SEBEP_ORAN)
	if oran == 0.0:
		return False
	if oran == 1.0:
		return True
	if not _TOKEN.match(token or ""):
		raise RumError("Oturum tokeni 16-64 hex olmalı", SEBEP_TOKEN)
	# İlk 8 hex → [0,1) — kriptografik değil, dağılım için yeterli.
	birim = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
	return birim < oran


# ── Kayıt ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RumSample:
	"""Tek bir metrik ölçümü. PII taşımaz — taşıyamaz, alanı yok.

	`lcp_region` / `lcp_profile` yalnız `metric == "LCP"` iken anlamlıdır ve
	Faz 12'nin asıl sorusunu cevaplar: *LCP öğesi hangi render bölgesiydi ve
	tarayıcı hangi türevi indirdi?* Bugün bu soru sorulamıyor; ölçülen dört
	sayfada LCP görselinin dördü de tek boy master.
	"""

	metric: str
	value: float
	route: str
	device_class: str
	viewport_bucket: int
	dpr: float
	connection: str
	sample_rate: float
	rating: str
	navigation_type: str = "navigate"
	session_bucket: str = ""
	lcp_region: str = ""
	lcp_profile: str = ""
	lcp_format: str = ""
	engine_version: str = ""

	def to_dict(self) -> Dict[str, Any]:
		"""Saklanacak düz sözlük — alan adları DocType alanlarıyla aynı olacak."""
		return {
			"metric": self.metric,
			"value": self.value,
			"rating": self.rating,
			"route": self.route,
			"device_class": self.device_class,
			"viewport_bucket": self.viewport_bucket,
			"dpr": self.dpr,
			"connection": self.connection,
			"navigation_type": self.navigation_type,
			"sample_rate": self.sample_rate,
			"session_bucket": self.session_bucket,
			"lcp_region": self.lcp_region,
			"lcp_profile": self.lcp_profile,
			"lcp_format": self.lcp_format,
			"engine_version": self.engine_version,
		}


def validate(payload: Mapping[str, Any], *, salt: str = "") -> RumSample:
	"""Ham istemci gövdesini doğrula ve `RumSample`'a çevir.

	Raises:
	    RumError: yasak alan varsa, metrik/rota/cihaz tanınmıyorsa, değer
	        sayı değilse. Kayıt SESSİZCE DÜZELTİLMEZ — gönderen taraf hatasını
	        görmeli, yoksa bozuk veri sessizce p75'e karışır.
	"""
	if not isinstance(payload, Mapping):
		raise RumError("Gövde sözlük olmalı", SEBEP_GOVDE)

	yasak = sorted(set(payload) & set(FORBIDDEN_FIELDS))
	if yasak:
		raise RumError(f"PII taşıyan alan(lar) reddedildi: {yasak}", SEBEP_PII_ALAN)

	metrik = str(payload.get("metric", "")).upper()
	if metrik not in METRICS:
		raise RumError(f"Bilinmeyen metrik: {payload.get('metric')!r}", SEBEP_METRIK)

	try:
		deger = float(payload["value"])
	except (KeyError, TypeError, ValueError):
		raise RumError("`value` sayı olmalı", SEBEP_DEGER)
	if math.isnan(deger) or math.isinf(deger) or deger < 0:
		raise RumError(f"`value` geçersiz: {deger!r}", SEBEP_DEGER)

	rota = str(payload.get("route") or payload.get("path") or "")
	rota = rota if rota in ROUTE_TEMPLATES else route_template(rota)

	cihaz = str(payload.get("device_class", "")).lower()
	if cihaz not in DEVICE_CLASSES:
		raise RumError(f"device_class {DEVICE_CLASSES} içinde olmalı: {cihaz!r}", SEBEP_CIHAZ)

	baglanti = str(payload.get("connection", "unknown")).lower()
	if baglanti not in CONNECTION_TYPES:
		raise RumError(f"connection {CONNECTION_TYPES} içinde olmalı: {baglanti!r}", SEBEP_BAGLANTI)

	try:
		dpr = round(float(payload.get("dpr", 1.0)), 2)
	except (TypeError, ValueError):
		raise RumError("`dpr` sayı olmalı", SEBEP_DPR)
	if not 0.5 <= dpr <= 6.0:
		raise RumError(f"`dpr` makul aralıkta değil: {dpr}", SEBEP_DPR)

	oran = float(payload.get("sample_rate", 1.0))
	if not 0.0 < oran <= 1.0:
		raise RumError(f"sample_rate (0,1] aralığında olmalı: {oran!r}", SEBEP_ORAN)

	kova = viewport_bucket(payload.get("viewport_width", 0))

	bolge = str(payload.get("lcp_region", ""))
	if bolge and not _REGION.match(bolge):
		raise RumError(f"lcp_region `sayfa/bölge` biçiminde olmalı: {bolge!r}", SEBEP_BOLGE)
	profil = str(payload.get("lcp_profile", ""))
	if profil and not _PROFILE.match(profil):
		raise RumError(f"lcp_profile tanınmadı: {profil!r}", SEBEP_PROFIL)

	token = str(payload.get("session_token", ""))
	kovacik = token_hash(token, salt=salt) if token else ""

	return RumSample(
		metric=metrik,
		value=round(deger, 4) if metrik in UNITLESS else round(deger, 1),
		route=rota,
		device_class=cihaz,
		viewport_bucket=kova,
		dpr=dpr,
		connection=baglanti,
		sample_rate=oran,
		rating=rating(metrik, deger),
		navigation_type=str(payload.get("navigation_type", "navigate")),
		session_bucket=kovacik,
		lcp_region=bolge,
		lcp_profile=profil,
		lcp_format=str(payload.get("lcp_format", "")),
		engine_version=str(payload.get("engine_version", "")),
	)


# ── Toplama ────────────────────────────────────────────────────────────


def percentile(values: Sequence[float], q: float) -> float:
	"""Yüzdelik — CWV raporlaması p75 kullanır. Boş dizide 0.0.

	Doğrusal interpolasyon YOK: en yakın sıra istatistiği alınır. Gerekçe:
	CWV eşikleri sınıflandırma içindir, interpolasyon iki ölçüm arasında hiç
	gözlenmemiş bir değer üretir.
	"""
	if not values:
		return 0.0
	sirali = sorted(values)
	if not 0.0 < q < 1.0:
		raise RumError(f"q (0,1) aralığında olmalı: {q!r}", SEBEP_TOPLAMA)
	idx = min(len(sirali) - 1, max(0, math.ceil(q * len(sirali)) - 1))
	return sirali[idx]


@dataclass
class Aggregate:
	"""Bir kova için toplanmış sonuç."""

	key: Tuple[str, ...]
	metric: str
	count: int
	p75: float
	rating: str
	good_ratio: float
	estimated_population: float

	def to_dict(self) -> Dict[str, Any]:
		return {
			"key": list(self.key),
			"metric": self.metric,
			"count": self.count,
			"p75": self.p75,
			"rating": self.rating,
			"good_ratio": round(self.good_ratio, 4),
			"estimated_population": round(self.estimated_population, 1),
		}


def aggregate(
	samples: Iterable[RumSample],
	*,
	group_by: Sequence[str] = ("route", "device_class"),
) -> List[Aggregate]:
	"""Örneklemleri kovalayıp p75 hesapla.

	`estimated_population` her kaydın `sample_rate`inin TERSİ toplanarak
	bulunur; oranı yok sayıp ham sayıyı raporlamak, %1 örneklemde gerçek
	trafiğin yüzde birini "toplam" diye sunmak olurdu.
	"""
	gecerli = [a for a in group_by if a not in ("value", "rating")]
	if len(gecerli) != len(group_by):
		raise RumError("`group_by` ölçüm değerini içeremez", SEBEP_TOPLAMA)

	kovalar: Dict[Tuple[str, ...], List[RumSample]] = {}
	for s in samples:
		anahtar = tuple([s.metric] + [str(getattr(s, alan)) for alan in group_by])
		kovalar.setdefault(anahtar, []).append(s)

	out: List[Aggregate] = []
	for anahtar, grup in sorted(kovalar.items()):
		degerler = [s.value for s in grup]
		p = percentile(degerler, 0.75)
		iyi = sum(1 for s in grup if s.rating == RATING_GOOD)
		out.append(
			Aggregate(
				key=anahtar[1:],
				metric=anahtar[0],
				count=len(grup),
				p75=round(p, 4 if anahtar[0] in UNITLESS else 1),
				rating=rating(anahtar[0], p),
				good_ratio=iyi / len(grup),
				estimated_population=sum(1.0 / s.sample_rate for s in grup),
			)
		)
	return out


def compare_to_lab(aggregates: Sequence[Aggregate]) -> List[Dict[str, Any]]:
	"""RUM p75'ini lab taban çizgisiyle karşılaştır — Faz 12 kabul girdisi.

	Lab ile alan verisi AYNI ŞEY DEĞİLDİR (lab tek cihaz + emüle ağ). Bu
	fonksiyon farkı gizlemez, `note` alanında söyler.
	"""
	out: List[Dict[str, Any]] = []
	for a in aggregates:
		rota = a.key[0] if a.key else ""
		taban = LAB_BASELINE_MS.get(rota) if a.metric == "LCP" else (
			LAB_BASELINE_CLS.get(rota) if a.metric == "CLS" else None
		)
		out.append({
			"metric": a.metric,
			"route": rota,
			"rum_p75": a.p75,
			"lab_baseline": taban,
			"delta": (round(a.p75 - taban, 4) if taban is not None else None),
			"note": "lab = tek cihaz + emüle Slow 4G; RUM = alan. Doğrudan eşitlenemez.",
		})
	return out


# ── İstemci sözleşmesi ─────────────────────────────────────────────────

#: İstemcinin göndereceği gövdenin JSON Şeması. Storefront SALT OKUNUR olduğu
#: için buradaki şema **belgedir**: frontend ekibi bu sözleşmeye göre yazar,
#: sunucu `validate()` ile aynı kuralı UYGULAR.
SCHEMA: Dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "media-engine RUM örneklemi",
	"type": "object",
	"additionalProperties": False,
	"required": ["metric", "value", "route", "device_class", "viewport_width", "sample_rate"],
	"properties": {
		"metric": {"enum": list(METRICS)},
		"value": {"type": "number", "minimum": 0},
		"route": {"enum": list(ROUTE_TEMPLATES)},
		"device_class": {"enum": list(DEVICE_CLASSES)},
		"viewport_width": {"type": "integer", "minimum": 1, "maximum": 10000},
		"dpr": {"type": "number", "minimum": 0.5, "maximum": 6},
		"connection": {"enum": list(CONNECTION_TYPES)},
		"navigation_type": {"enum": ["navigate", "reload", "back-forward", "prerender"]},
		"sample_rate": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
		"session_token": {"type": "string", "pattern": "^[0-9a-f]{16,64}$"},
		"lcp_region": {"type": "string", "pattern": "^[a-z0-9_]+/[a-z0-9_]+$"},
		"lcp_profile": {"type": "string", "pattern": "^(w\\d{2,4}|original|unknown)$"},
		"lcp_format": {"type": "string", "maxLength": 8},
		"engine_version": {"type": "string", "maxLength": 32},
	},
	"$comment": (
		"`additionalProperties: false` KASITLI: şemada olmayan her alan reddedilir. "
		"Yasak alanları tek tek saymak yerine beyaz liste kullanmak, ileride eklenen "
		"bir PII alanının sessizce geçmesini engeller."
	),
}


def schema_forbids_pii() -> Tuple[str, ...]:
	"""Şemanın gerçekten PII geçirmediğini kanıtla — hangi alanlar reddedilir."""
	izinli = set(SCHEMA["properties"])
	return tuple(sorted(alan for alan in FORBIDDEN_FIELDS if alan not in izinli))


# ── Saklama tasarımı — `Media RUM Sample` (KURULMADI) ──────────────────
#
# `docs/reports/36-dogrulama-faz12-14.md` ölçtü: `Media RUM Sample` DocType
# YOK, dolayısıyla saha verisi bugün hiçbir yere yazılamıyor. DocType kurulumu
# bu görevin kapsamı DIŞINDA (patch + migrate gerektirir). Buraya konan şey
# kurulum değil, kurulacak şemanın SÖZLEŞMESİ — ve `RumSample.to_dict()` ile
# aynı alan kümesini taşıdığı testle doğrulanır.
#
# Neden burada duruyor: DocType JSON'u ayrı bir dosyada tek başına yazılırsa,
# `validate()`'in ürettiği alan kümesiyle sessizce ayrışır ve ayrışmayı hiçbir
# test görmez. Şemayı doğrulayan kodun yanında tutmak o ayrışmayı imkânsız
# kılar.

#: (alan adı, Frappe fieldtype, seçenek/uzunluk notu, indeks mi)
DOCTYPE_FIELDS: Tuple[Tuple[str, str, str, bool], ...] = (
	("metric", "Select", "\n".join(METRICS), True),
	("value", "Float", "", False),
	("rating", "Select", "\n".join((RATING_GOOD, RATING_NEEDS_IMPROVEMENT, RATING_POOR)), False),
	("route", "Select", "\n".join(ROUTE_TEMPLATES), True),
	("device_class", "Select", "\n".join(DEVICE_CLASSES), True),
	("viewport_bucket", "Int", "", False),
	("dpr", "Float", "", False),
	("connection", "Select", "\n".join(CONNECTION_TYPES), False),
	("navigation_type", "Data", "maxlength 16", False),
	("sample_rate", "Float", "", False),
	("session_bucket", "Data", "maxlength 12 — token ÖZETİ, ham token değil", False),
	("lcp_region", "Data", "maxlength 64", False),
	("lcp_profile", "Data", "maxlength 16", False),
	("lcp_format", "Data", "maxlength 8", False),
	("engine_version", "Data", "maxlength 32", False),
)

#: DocType'ın taşıması gereken tasarım kararları. Sayılar gerekçelidir:
#: `Link`/`Dynamic Link` YOK — kayıt hiçbir kullanıcıya ya da belgeye
#: bağlanamamalı; bağlanabilseydi "PII yok" iddiası şemayla değil, disiplinle
#: korunuyor olurdu.
DOCTYPE_DESIGN: Dict[str, Any] = {
	"name": "Media RUM Sample",
	"module": "Tradehub Core",
	"naming": "hash",
	"is_submittable": 0,
	"track_changes": 0,
	"editable_grid": 0,
	# Kullanıcıya ait hiçbir alan yok; kayıt kimseye ait değildir. `owner`
	# alanı Frappe tarafından zorunlu olarak yazılır ve GUEST olur — uç
	# `ignore_permissions` ile yazacağı için `owner` bilgi taşımaz.
	"permissions": [{"role": "System Manager", "read": 1, "delete": 1}],
	"indexes": [f[0] for f in DOCTYPE_FIELDS if f[3]] + ["creation"],
	# Saklama: ham örneklem 30 gün, sonrası yalnız `Aggregate` özeti. Gerekçe
	# KVKK m.4/2-d (ölçülü ve sınırlı süre): p75 raporlaması için 30 günlük
	# pencere yeterli, ham satırı süresiz tutmanın hiçbir analitik karşılığı
	# yok ve her satır bir cihaz parmak izi parçası taşır.
	"retention_days": 30,
	"forbidden_fields": list(FORBIDDEN_FIELDS),
}


def doctype_field_names() -> Tuple[str, ...]:
	return tuple(f[0] for f in DOCTYPE_FIELDS)


def doctype_matches_sample() -> Tuple[str, ...]:
	"""DocType alanları ile `RumSample.to_dict()` arasındaki FARK.

	Boş dönmesi "şema ile saklama aynı şeyi söylüyor" demektir. Boş
	dönmemesi, DocType kurulmadan önce düzeltilmesi gereken bir ayrışmadır.
	"""
	ornek = RumSample(
		metric="LCP", value=0.0, route="/", device_class="phone", viewport_bucket=0,
		dpr=1.0, connection="unknown", sample_rate=1.0, rating=RATING_GOOD,
	).to_dict()
	return tuple(sorted(set(ornek) ^ set(doctype_field_names())))


# ── Metrik köprüsü — p75'i Prometheus'a taşı ───────────────────────────


def _metrikler(registry: Any = None) -> Dict[str, Any]:
	"""Kullanılacak metrik nesneleri. İçe aktarma GEÇ yapılır.

	`observability.metrics` bağımlılıksızdır, yani modül başında da içe
	aktarılabilirdi. Yapılmıyor: `delivery/rum.py` bugün gözlemlenebilirlik
	katmanını TANIMIYOR ve bu köprü onun tek bağı. Geç içe aktarma, bağın
	yalnız köprü çağrıldığında kurulmasını ve modülün geri kalanının
	bağımsız kalmasını sağlar.
	"""
	from ..observability import metrics as mm

	if registry is None:
		return {
			"p75_ms": mm.RUM_P75_MS,
			"cls": mm.RUM_CLS_P75,
			"samples": mm.RUM_SAMPLES_TOTAL,
			"population": mm.RUM_ESTIMATED_POPULATION,
			"rejected": mm.RUM_REJECTED_TOTAL,
		}
	return {
		"p75_ms": registry.get("media_rum_p75_milliseconds"),
		"cls": registry.get("media_rum_cls_p75"),
		"samples": registry.get("media_rum_samples_total"),
		"population": registry.get("media_rum_estimated_population"),
		"rejected": registry.get("media_rum_rejected_total"),
	}


#: Köprünün beklediği kova anahtarı. Etiketler metrik tanımında SABİT olduğu
#: için `group_by` bundan farklıysa etiket kümesi tutmaz ve `MetricError`
#: fırlardı; hatayı burada, anlaşılır bir mesajla vermek daha iyidir.
METRIC_GROUP_BY: Tuple[str, ...] = ("route", "device_class")


def to_metrics(aggregates: Sequence[Aggregate], *, registry: Any = None) -> int:
	"""Toplanmış p75'leri metrik kayıt defterine yaz; yazılan seri sayısını döndür.

	`aggregate(samples, group_by=("route", "device_class"))` çıktısı beklenir.
	Milisaniyelik metrikler ile CLS AYRI metriklere yazılır — birimleri farklı
	olan iki değeri tek metrik adı altında toplamak, `sum()`u anlamsız ve
	paneli tek eksende çizilemez yapardı.

	**Sayaç DAVRANIŞI:** `samples` bir sayaçtır ve her çağrıda toplanan kova
	adedi kadar ARTAR. Yani bu fonksiyon aynı toplamayla iki kez çağrılırsa
	örnek sayısı iki katına çıkar. Çağıran, her toplama penceresini BİR kez
	geçirmelidir; gösterge (`p75`, `population`) için bu sorun değildir
	(üzerine yazılır), sayaç için kritiktir.
	"""
	m = _metrikler(registry)
	yazilan = 0
	for a in aggregates:
		if len(a.key) != len(METRIC_GROUP_BY):
			raise RumError(
				f"to_metrics {METRIC_GROUP_BY} kovalamasi bekler, gelen: {a.key!r}", SEBEP_TOPLAMA
			)
		rota, cihaz = a.key[0], a.key[1]
		if a.metric in UNITLESS:
			m["cls"].set(a.p75, route=rota, device_class=cihaz)
		else:
			m["p75_ms"].set(a.p75, metric=a.metric, route=rota, device_class=cihaz)
		m["population"].set(
			a.estimated_population, metric=a.metric, route=rota, device_class=cihaz
		)
		m["samples"].inc(
			a.count, metric=a.metric, route=rota, device_class=cihaz, rating=a.rating
		)
		yazilan += 1
	return yazilan


def record_rejection(hata: BaseException, *, registry: Any = None) -> str:
	"""Reddedilen gövdeyi sayaca yaz ve kullanılan sebep kodunu döndür.

	`RumError` olmayan bir istisna da sayılır (`malformed_body`): uç noktada
	beklenmeyen bir hata olduğunda kaydın sessizce düşmesi, "veri hiç gelmedi"
	ile "veri geldi ama işleyemedik" ayrımını yok ederdi.
	"""
	kod = getattr(hata, "kod", None)
	if kod not in REJECT_REASONS:
		kod = SEBEP_GOVDE
	_metrikler(registry)["rejected"].inc(reason=kod)
	return kod


__all__ = [
	"DOCTYPE_DESIGN",
	"DOCTYPE_FIELDS",
	"METRICS",
	"METRIC_GROUP_BY",
	"REJECT_REASONS",
	"UNITLESS",
	"RATING_THRESHOLDS",
	"RATING_GOOD",
	"RATING_NEEDS_IMPROVEMENT",
	"RATING_POOR",
	"LAB_BASELINE_MS",
	"LAB_BASELINE_CLS",
	"ROUTE_TEMPLATES",
	"DEVICE_CLASSES",
	"CONNECTION_TYPES",
	"VIEWPORT_BUCKETS",
	"FORBIDDEN_FIELDS",
	"SOURCES",
	"SCHEMA",
	"RumError",
	"RumSample",
	"Aggregate",
	"rating",
	"route_template",
	"viewport_bucket",
	"token_hash",
	"decide",
	"validate",
	"percentile",
	"aggregate",
	"compare_to_lab",
	"schema_forbids_pii",
	"doctype_field_names",
	"doctype_matches_sample",
	"to_metrics",
	"record_rejection",
]
