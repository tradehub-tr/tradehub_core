"""T-133 — Prometheus text exposition format 0.0.4 üreten metrik kayıt defteri.

NEDEN KENDİ UYGULAMASI
======================
`prometheus_client` konteynerde KURULU DEĞİL (2026-08-18 ölçümü:
`ModuleNotFoundError: No module named 'prometheus_client'`). Yeni bir runtime
bağımlılığı eklemek üç şey getirirdi: imaj yeniden derlemesi, çoklu-süreç
modunda (`gunicorn` + RQ worker'ları) `multiproc_dir` yapılandırması ve
`media_engine`'in "frappe'siz, bağımlılıksız test edilebilir" kuralının
delinmesi. Bu dosya ~400 satırdır ve karşılığında paket sıfır bağımlılıkla
kalır.

**Uyum sınırı — açıkça:** üretilen çıktı Prometheus **text format 0.0.4**'tür.
OpenMetrics (`# EOF`, `_created` satırları, exemplar) ÜRETİLMEZ. Prometheus
scrape'i 0.0.4'ü kabul eder; OpenMetrics gerekiyorsa bu dosya değil, gerçek
kütüphane kullanılmalıdır.

ÇOK SÜREÇLİ ORTAM — bilinen sınır, gizlenmiyor
==============================================
Kayıt defteri SÜREÇ İÇİDİR. Frappe hattında en az üç süreç ailesi var
(`gunicorn` web, `queue-short`, `queue-long`) ve her biri kendi sayacını
tutar. `/metrics` ucu tek süreçten servis edilirse yalnız o sürecin sayıları
görünür. İki geçerli çözüm var, ikisi de bu modülün DIŞINDA:

  1. her sürece ayrı scrape hedefi (Prometheus tarafında `sum by (job)`),
  2. `dump_json()` çıktısını Redis'te toplayıp tek uçtan render etmek.

`dump_json()` ve `merge_json()` ikinci yolu MÜMKÜN kılmak için var; hangisinin
seçileceği dağıtım kararıdır ve burada verilmez.

METRİK SEÇİMİ — ölçülmüş gerçeklerden türedi
============================================
Kovalar (`buckets`) uydurma değil; canlı envanter ve bu makinedeki ölçümlerden:

  * `media_image_process_duration_seconds` kovaları
    (0,05 · 0,1 · 0,25 · 0,5 · 1 · 2,5 · 5 · 10 · 30 · 60):
    ölçülen `engine.optimize()` süreleri 1,56 MP → 0,07 s, 5,01 MP → 0,23 s,
    29,21 MP → 0,58 s, 72,71 MP → 1,05 s. Yani BUGÜNKÜ dağılımın tamamı ilk
    dört kovaya düşer; üst kovalar "arıza" bölgesidir ve
    `security/isolation.py` `IMAGE_LIMITS.wall_timeout_s = 60` ile hizalıdır.
  * `media_source_bytes` kovaları (64 KB … 25 MB): 4.958 dosya / 1.559 MB.
    25 MB üst kova `upload_policy.MAX_BYTES[image]` ile aynı — tavanı aşan
    dosya zaten kabul edilmiyor, o kovanın dolması politika ihlali demektir.
  * `media_source_megapixels` kovaları (1 · 2 · 5 · 10 · 20 · 30 · 50 · 80):
    ölçülen p50=1,56 · p90=5,01 · p99=29,21 · MAX=72,71 ve "179 dosya > 20 MP"
    anomalisi. 20 MP kovası bu anomalinin doğrudan göstergesidir.

ADLANDIRMA
==========
Prometheus sözleşmesi: `<namespace>_<subsystem>_<isim>_<birim>`. Ad alanı
`media`. Sayaçlar `_total` ile biter (bu modül eki KENDİ ekler — çağıran
`media_upload_total` DEĞİL `media_upload` yazar; iki yerde ek eklemek çift
`_total_total` üretirdi).

`import frappe` YOKTUR.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

TYPE_COUNTER: str = "counter"
TYPE_GAUGE: str = "gauge"
TYPE_HISTOGRAM: str = "histogram"

#: Prometheus veri modeli — ad ve etiket adı deseni.
_AD_DESENI = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_ETIKET_DESENI = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

#: `le` histogramın kendi etiketi, `quantile` summary'nin — kullanıcı etiketi
#: olarak kabul edilmez, aksi hâlde üretilen çıktı bozulur.
AYRILMIS_ETIKETLER: frozenset = frozenset({"le", "quantile"})

NAMESPACE: str = "media"


class MetricError(ValueError):
	"""Geçersiz metrik/etiket adı ya da tutarsız etiket kümesi.

	Bu SINIF bilinçli olarak fırlatılır (sonuç nesnesi değil): yanlış adlı bir
	metrik, üretimde sessizce bozuk bir `/metrics` çıktısı demektir ve bozuk
	çıktıyı Prometheus TAMAMEN reddeder — tek bir hatalı satır bütün scrape'i
	düşürür. Hata geliştirme anında yüzeye çıkmalı.
	"""


def _ad_dogrula(ad: str) -> str:
	if not _AD_DESENI.match(ad or ""):
		raise MetricError(f"gecersiz metrik adi: {ad!r}")
	return ad


def _etiket_adlari_dogrula(adlar: Sequence[str]) -> tuple[str, ...]:
	temiz: list[str] = []
	for a in adlar:
		if not _ETIKET_DESENI.match(a or ""):
			raise MetricError(f"gecersiz etiket adi: {a!r}")
		if a in AYRILMIS_ETIKETLER:
			raise MetricError(f"ayrilmis etiket adi: {a!r}")
		temiz.append(a)
	if len(set(temiz)) != len(temiz):
		raise MetricError(f"tekrar eden etiket adi: {adlar!r}")
	return tuple(temiz)


def _kacir(deger: str) -> str:
	"""Etiket DEĞERİ kaçırma — 0.0.4 kuralı: `\\`, `\"`, yeni satır."""
	return str(deger).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _help_kacir(metin: str) -> str:
	"""HELP kaçırma — 0.0.4'te yalnız `\\` ve yeni satır kaçırılır (tırnak DEĞİL)."""
	return str(metin).replace("\\", "\\\\").replace("\n", "\\n")


def _sayi(deger: float) -> str:
	"""Prometheus sayı biçimi. `inf`/`nan` özel yazılır, tam sayı sade kalır."""
	if isinstance(deger, bool):
		return "1" if deger else "0"
	f = float(deger)
	if math.isnan(f):
		return "NaN"
	if math.isinf(f):
		return "+Inf" if f > 0 else "-Inf"
	if f == int(f) and abs(f) < 1e15:
		return str(int(f))
	return repr(f)


@dataclass
class _Seri:
	"""Tek bir etiket kombinasyonunun durumu."""

	deger: float = 0.0
	#: Histogram için: kova sayaçları (kümülatif DEĞİL, ham) + toplam + adet
	kovalar: list[float] = field(default_factory=list)
	toplam: float = 0.0
	adet: float = 0.0


class Metric:
	"""Sayaç / gösterge / histogram için ortak taban.

	Etiket kümesi metrik tanımında SABİTLENİR: `labels()` çağrısında eksik ya
	da fazla etiket `MetricError` verir. Prometheus'ta aynı metrik adının
	farklı etiket kümeleriyle görünmesi geçersizdir; hatayı yazan tarafta
	yakalamak, scrape'te yakalamaktan iyidir.
	"""

	tur: str = TYPE_GAUGE

	def __init__(
		self,
		ad: str,
		aciklama: str,
		*,
		etiketler: Sequence[str] = (),
		namespace: str = NAMESPACE,
		kilit: threading.Lock | None = None,
	) -> None:
		tam = f"{namespace}_{ad}" if namespace else ad
		self.ad: str = _ad_dogrula(tam)
		self.aciklama: str = aciklama or ad
		self.etiketler: tuple[str, ...] = _etiket_adlari_dogrula(etiketler)
		self._seriler: dict[tuple[str, ...], _Seri] = {}
		self._kilit: threading.Lock = kilit or threading.Lock()

	# ── etiket çözümü ──
	def _anahtar(self, etiket_degerleri: Mapping[str, Any]) -> tuple[str, ...]:
		verilen = set(etiket_degerleri)
		beklenen = set(self.etiketler)
		if verilen != beklenen:
			eksik = sorted(beklenen - verilen)
			fazla = sorted(verilen - beklenen)
			raise MetricError(f"{self.ad}: etiket kumesi uyusmuyor (eksik={eksik}, fazla={fazla})")
		return tuple(str(etiket_degerleri[a]) for a in self.etiketler)

	def _seri(self, anahtar: tuple[str, ...]) -> _Seri:
		seri = self._seriler.get(anahtar)
		if seri is None:
			seri = self._yeni_seri()
			self._seriler[anahtar] = seri
		return seri

	def _yeni_seri(self) -> _Seri:
		return _Seri()

	def temizle(self) -> None:
		"""Tüm serileri sıfırla — yalnız testler ve süreç yeniden başlatması içindir."""
		with self._kilit:
			self._seriler.clear()

	def seri_sayisi(self) -> int:
		with self._kilit:
			return len(self._seriler)

	# ── render ──
	def _etiket_metni(self, anahtar: tuple[str, ...], ek: Sequence[tuple[str, str]] = ()) -> str:
		# `zip` yerine indeks: etiket adı ile değer sayısı `_anahtar()` tarafından
		# zaten eşitlenmiş durumda; `zip(strict=)` ise Python 3.10+ gerektiriyor
		# ve bu paket 3.9 ile de test ediliyor.
		parcalar = [f'{self.etiketler[i]}="{_kacir(anahtar[i])}"' for i in range(len(anahtar))]
		parcalar += [f'{ad}="{_kacir(deg)}"' for ad, deg in ek]
		return "{" + ",".join(parcalar) + "}" if parcalar else ""

	def satirlar(self) -> list[str]:  # pragma: no cover - alt sınıflar uygular
		raise NotImplementedError

	def render(self) -> str:
		govde = self.satirlar()
		if not govde:
			return ""
		bas = [
			f"# HELP {self.ad} {_help_kacir(self.aciklama)}",
			f"# TYPE {self.ad} {self.tur}",
		]
		return "\n".join(bas + govde)

	def to_json(self) -> dict[str, Any]:  # pragma: no cover - alt sınıflar genişletir
		with self._kilit:
			return {
				"name": self.ad,
				"type": self.tur,
				"help": self.aciklama,
				"labels": list(self.etiketler),
				"series": {"\u001f".join(k): {"value": s.deger} for k, s in self._seriler.items()},
			}


class Counter(Metric):
	"""Yalnız ARTAN sayaç. Ad otomatik `_total` ile biter."""

	tur = TYPE_COUNTER

	def __init__(self, ad: str, aciklama: str, **kw: Any) -> None:
		if ad.endswith("_total"):
			# Ek iki yerde eklenirse `_total_total` çıkar; tek sahibi bu sınıf.
			ad = ad[: -len("_total")]
		super().__init__(f"{ad}_total", aciklama, **kw)

	def inc(self, miktar: float = 1.0, **etiketler: Any) -> None:
		if miktar < 0:
			raise MetricError(f"{self.ad}: sayac azaltilamaz ({miktar})")
		anahtar = self._anahtar(etiketler)
		with self._kilit:
			self._seri(anahtar).deger += float(miktar)

	def deger(self, **etiketler: Any) -> float:
		anahtar = self._anahtar(etiketler)
		with self._kilit:
			seri = self._seriler.get(anahtar)
			return seri.deger if seri else 0.0

	def satirlar(self) -> list[str]:
		with self._kilit:
			ogeler = sorted(self._seriler.items())
		return [f"{self.ad}{self._etiket_metni(k)} {_sayi(s.deger)}" for k, s in ogeler]


class Gauge(Metric):
	"""Artıp azalabilen anlık değer (kuyruk derinliği, disk kullanımı)."""

	tur = TYPE_GAUGE

	def set(self, deger: float, **etiketler: Any) -> None:
		anahtar = self._anahtar(etiketler)
		with self._kilit:
			self._seri(anahtar).deger = float(deger)

	def inc(self, miktar: float = 1.0, **etiketler: Any) -> None:
		anahtar = self._anahtar(etiketler)
		with self._kilit:
			self._seri(anahtar).deger += float(miktar)

	def dec(self, miktar: float = 1.0, **etiketler: Any) -> None:
		self.inc(-miktar, **etiketler)

	def deger(self, **etiketler: Any) -> float:
		anahtar = self._anahtar(etiketler)
		with self._kilit:
			seri = self._seriler.get(anahtar)
			return seri.deger if seri else 0.0

	def satirlar(self) -> list[str]:
		with self._kilit:
			ogeler = sorted(self._seriler.items())
		return [f"{self.ad}{self._etiket_metni(k)} {_sayi(s.deger)}" for k, s in ogeler]


#: Süre kovaları — gerekçe modül başlığındaki ölçüm tablosunda.
DURATION_BUCKETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
#: Bayt kovaları — 25 MB üst kova `upload_policy.MAX_BYTES[image]` ile aynı.
BYTE_BUCKETS: tuple[float, ...] = (
	64 * 1024.0,
	256 * 1024.0,
	1024 * 1024.0,
	4 * 1024 * 1024.0,
	16 * 1024 * 1024.0,
	25 * 1024 * 1024.0,
)
#: Megapiksel kovaları — 20 MP kovası "179 dosya > 20 MP" anomalisinin göstergesi.
MEGAPIXEL_BUCKETS: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 50.0, 80.0)


class Histogram(Metric):
	"""Kümülatif histogram: `_bucket{le=…}`, `_sum`, `_count`.

	Kovalar ARTAN sırada olmalı ve `+Inf` OTOMATİK eklenir — elle eklenmiş bir
	`+Inf` iki kez yazılırdı.
	"""

	tur = TYPE_HISTOGRAM

	def __init__(
		self, ad: str, aciklama: str, *, buckets: Sequence[float] = DURATION_BUCKETS, **kw: Any
	) -> None:
		super().__init__(ad, aciklama, **kw)
		sinirlar = [float(b) for b in buckets if not math.isinf(float(b))]
		if not sinirlar:
			raise MetricError(f"{self.ad}: en az bir kova gerekli")
		if sinirlar != sorted(sinirlar):
			raise MetricError(f"{self.ad}: kovalar artan sirada olmali: {buckets!r}")
		if len(set(sinirlar)) != len(sinirlar):
			raise MetricError(f"{self.ad}: tekrar eden kova siniri: {buckets!r}")
		self.buckets: tuple[float, ...] = tuple(sinirlar) + (float("inf"),)

	def _yeni_seri(self) -> _Seri:
		return _Seri(kovalar=[0.0] * len(self.buckets))

	def observe(self, deger: float, **etiketler: Any) -> None:
		anahtar = self._anahtar(etiketler)
		v = float(deger)
		with self._kilit:
			seri = self._seri(anahtar)
			seri.toplam += v
			seri.adet += 1.0
			for i, sinir in enumerate(self.buckets):
				if v <= sinir:
					seri.kovalar[i] += 1.0
					break

	def zamanla(self, **etiketler: Any) -> _Zamanlayici:
		"""`with hist.zamanla(op="optimize"): ...` — süreyi otomatik yazar."""
		return _Zamanlayici(self, etiketler)

	def ozet(self, **etiketler: Any) -> dict[str, float]:
		anahtar = self._anahtar(etiketler)
		with self._kilit:
			seri = self._seriler.get(anahtar)
			if seri is None:
				return {"count": 0.0, "sum": 0.0}
			return {"count": seri.adet, "sum": seri.toplam}

	def satirlar(self) -> list[str]:
		with self._kilit:
			ogeler = sorted(self._seriler.items())
			cikti: list[str] = []
			for anahtar, seri in ogeler:
				kumulatif = 0.0
				for i, sinir in enumerate(self.buckets):
					kumulatif += seri.kovalar[i]
					le = "+Inf" if math.isinf(sinir) else _sayi(sinir)
					etiket = self._etiket_metni(anahtar, ek=(("le", le),))
					cikti.append(f"{self.ad}_bucket{etiket} {_sayi(kumulatif)}")
				temel = self._etiket_metni(anahtar)
				cikti.append(f"{self.ad}_sum{temel} {_sayi(seri.toplam)}")
				cikti.append(f"{self.ad}_count{temel} {_sayi(seri.adet)}")
		return cikti

	def to_json(self) -> dict[str, Any]:
		with self._kilit:
			return {
				"name": self.ad,
				"type": self.tur,
				"help": self.aciklama,
				"labels": list(self.etiketler),
				"buckets": [("+Inf" if math.isinf(b) else b) for b in self.buckets],
				"series": {
					"\u001f".join(k): {
						"buckets": list(s.kovalar),
						"sum": s.toplam,
						"count": s.adet,
					}
					for k, s in self._seriler.items()
				},
			}


class _Zamanlayici:
	"""`Histogram.zamanla()` bağlam yöneticisi. İSTİSNADA DA yazar."""

	def __init__(self, hist: Histogram, etiketler: Mapping[str, Any]) -> None:
		self._hist = hist
		self._etiketler = dict(etiketler)
		self._t0 = 0.0

	def __enter__(self) -> _Zamanlayici:
		self._t0 = time.perf_counter()
		return self

	def __exit__(self, *_exc: Any) -> bool:
		# İstisna yutulmaz (False döner): ölçüm, hata yolunu GİZLEMEK için
		# değil, hata yolunun SÜRESİNİ görmek için var.
		self._hist.observe(time.perf_counter() - self._t0, **self._etiketler)
		return False


class Registry:
	"""Metrik kayıt defteri. Aynı adı iki kez kaydetmek hatadır."""

	def __init__(self, namespace: str = NAMESPACE) -> None:
		self.namespace: str = namespace
		self._metrikler: dict[str, Metric] = {}
		self._kilit = threading.Lock()

	def _kaydet(self, metrik: Metric) -> Metric:
		with self._kilit:
			if metrik.ad in self._metrikler:
				raise MetricError(f"metrik zaten kayitli: {metrik.ad}")
			self._metrikler[metrik.ad] = metrik
		return metrik

	def counter(self, ad: str, aciklama: str, *, etiketler: Sequence[str] = ()) -> Counter:
		return self._kaydet(Counter(ad, aciklama, etiketler=etiketler, namespace=self.namespace))  # type: ignore[return-value]

	def gauge(self, ad: str, aciklama: str, *, etiketler: Sequence[str] = ()) -> Gauge:
		return self._kaydet(Gauge(ad, aciklama, etiketler=etiketler, namespace=self.namespace))  # type: ignore[return-value]

	def histogram(
		self,
		ad: str,
		aciklama: str,
		*,
		etiketler: Sequence[str] = (),
		buckets: Sequence[float] = DURATION_BUCKETS,
	) -> Histogram:
		return self._kaydet(  # type: ignore[return-value]
			Histogram(ad, aciklama, etiketler=etiketler, buckets=buckets, namespace=self.namespace)
		)

	def get(self, ad: str) -> Metric | None:
		with self._kilit:
			return self._metrikler.get(ad)

	def metrikler(self) -> list[Metric]:
		with self._kilit:
			return [self._metrikler[a] for a in sorted(self._metrikler)]

	def render(self) -> str:
		"""Text exposition format 0.0.4. Çıktı DETERMİNİSTİKTİR (ada göre sıralı).

		Determinizm bir tercih değil test edilebilirlik koşulu: sözlük
		sırasına bağlı bir çıktı, altın-dosya karşılaştırmasını imkânsız
		kılardı.
		"""
		bloklar = [m.render() for m in self.metrikler()]
		govde = "\n".join(b for b in bloklar if b)
		return govde + "\n" if govde else ""

	def content_type(self) -> str:
		"""HTTP `Content-Type` başlığı — Prometheus'un beklediği tam metin."""
		return "text/plain; version=0.0.4; charset=utf-8"

	def dump_json(self) -> str:
		"""Çok süreçli toplama için ara biçim (bkz. modül başlığı)."""
		return json.dumps(
			{"namespace": self.namespace, "metrics": [m.to_json() for m in self.metrikler()]},
			sort_keys=True,
		)

	def temizle(self) -> None:
		for m in self.metrikler():
			m.temizle()


def merge_json(dokumler: Iterable[str]) -> dict[str, Any]:
	"""Birden çok sürecin `dump_json()` çıktısını TOPLAR.

	Sayaç ve histogram TOPLANIR (süreçler arası toplam anlamlıdır); gösterge
	için toplam anlamsız olabileceğinden hem `sum` hem `max` verilir ve KARAR
	çağırana bırakılır: "kuyruk derinliği" toplanır, "disk doluluk oranı"
	toplanmaz.
	"""
	sonuc: dict[str, Any] = {}
	for ham in dokumler:
		try:
			veri = json.loads(ham)
		except Exception:
			continue
		for m in veri.get("metrics", []):
			ad = m.get("name")
			if not ad:
				continue
			hedef = sonuc.setdefault(ad, {"type": m.get("type"), "help": m.get("help"), "series": {}})
			for anahtar, seri in (m.get("series") or {}).items():
				h = hedef["series"].setdefault(anahtar, {})
				if m.get("type") == TYPE_HISTOGRAM:
					kovalar = h.setdefault("buckets", [0.0] * len(seri.get("buckets", [])))
					for i, v in enumerate(seri.get("buckets", [])):
						if i < len(kovalar):
							kovalar[i] += float(v)
					h["sum"] = h.get("sum", 0.0) + float(seri.get("sum", 0.0))
					h["count"] = h.get("count", 0.0) + float(seri.get("count", 0.0))
				else:
					v = float(seri.get("value", 0.0))
					h["sum"] = h.get("sum", 0.0) + v
					h["max"] = max(h.get("max", v), v)
	return sonuc


# ── Medya hattının standart metrikleri ──────────────────────────────────
#
# Bu blok bir ÖNERİ değil sözleşmedir: metrik adı bir API'dir, gösterge paneli
# ve uyarı kuralı ona bağlanır. Ad değişimi panelin sessizce boşalması demek.
# Etiket kardinalitesi bilinçli DAR tutuldu — `file_url`, `user`, `seller`
# gibi yüksek kardinaliteli değerler ETİKET OLARAK KULLANILMAZ (Prometheus'ta
# seri patlaması + `logging.py`'deki PII maskeleme sözleşmesinin ihlali).

REGISTRY: Registry = Registry(NAMESPACE)

#: Yükleme sonucu. `outcome` ∈ {accepted, rejected, quarantined}
#: `reason` `upload_policy.Kod.kod` ya da `contracts/errors.SEBEP_*` değeri.
UPLOAD_TOTAL: Counter = REGISTRY.counter(
	"upload", "Yukleme denemesi sayisi", etiketler=("slot", "kind", "outcome", "reason")
)

#: Görsel işleme süresi. `op` ∈ {probe, optimize, to_webp, render, lqip}
IMAGE_PROCESS_DURATION: Histogram = REGISTRY.histogram(
	"image_process_duration_seconds",
	"Gorsel isleme suresi (saniye)",
	etiketler=("op", "format"),
	buckets=DURATION_BUCKETS,
)

#: Kaynak dosya boyutu dağılımı.
SOURCE_BYTES: Histogram = REGISTRY.histogram(
	"source_bytes", "Kaynak dosya boyutu (bayt)", etiketler=("kind",), buckets=BYTE_BUCKETS
)

#: Kaynak çözünürlük dağılımı — ">20 MP" anomalisi buradan izlenir.
SOURCE_MEGAPIXELS: Histogram = REGISTRY.histogram(
	"source_megapixels", "Kaynak gorsel cozunurlugu (MP)", buckets=MEGAPIXEL_BUCKETS
)

#: Optimizasyonda kazanılan bayt. `outcome` ∈ {written, skipped_gate}
BYTES_SAVED_TOTAL: Counter = REGISTRY.counter(
	"bytes_saved", "Optimizasyonla kazanilan bayt", etiketler=("preset", "outcome")
)

#: T-066 kalite raporu üretilen varlık. Varlık kimliği etiket DEĞİLDİR:
#: kardinaliteyi patlatır ve rapor DocType'ındaki ayrıntıyı Prometheus'a taşır.
MEDIA_PROCESSED_TOTAL: Counter = REGISTRY.counter(
	"processed", "Kalite raporu uretilen medya varligi", etiketler=("slot", "outcome")
)

#: T-066 iş süresi. `job=image_render`; `outcome` rapor kararı ya da `failed`.
MEDIA_JOB_DURATION_SECONDS: Histogram = REGISTRY.histogram(
	"job_duration_seconds",
	"Medya isleme isi suresi (saniye)",
	etiketler=("job", "outcome"),
	buckets=DURATION_BUCKETS,
)

#: T-066 rapor üretilemeden biten işler. `reason` düşük kardinaliteli makine kodudur.
MEDIA_JOB_FAILURES_TOTAL: Counter = REGISTRY.counter(
	"job_failures", "Basarisiz medya isleme isi", etiketler=("job", "reason")
)

#: Kuyruk işi sonucu. `state` `tradehub_core/media/jobs.py` sözlüğünden.
JOB_TOTAL: Counter = REGISTRY.counter("job", "Kuyruk isi sonucu", etiketler=("job", "state"))

#: Deneme sayısı dağılımı — backoff politikasının işe yarayıp yaramadığı.
JOB_ATTEMPTS: Histogram = REGISTRY.histogram(
	"job_attempts", "Is basina deneme sayisi", etiketler=("job",), buckets=(1.0, 2.0, 3.0)
)

#: T-034 — beş ayrık RQ kuyruğunun anlık derinliği. ``queue`` etiketi
#: ``core/queues.py::QUEUE_NAMES`` kapalı kümesidir; kullanıcı/veri etiketi yok.
MEDIA_QUEUE_DEPTH: Gauge = REGISTRY.gauge(
	"queue_depth", "Bekleyen medya RQ isi", etiketler=("queue",)
)

#: Media Processing Job kayıt defterindeki durumlar. RQ derinliği yalnız
#: bekleyeni görür; çalışan/başarısız/dead işler bu ayrı seride tutulur.
MEDIA_QUEUE_JOBS: Gauge = REGISTRY.gauge(
	"queue_jobs", "Duruma gore medya is kaydi", etiketler=("queue", "status")
)

#: İzolasyon sonucu — `security/isolation.py` `SEBEP_*` değerleri.
ISOLATION_TOTAL: Counter = REGISTRY.counter(
	"isolation", "Izole calistirma sonucu", etiketler=("profile", "reason")
)

#: AV tarama sonucu — `media/av.py` durumları (clean/infected/failed).
SCAN_TOTAL: Counter = REGISTRY.counter("scan", "Zararli icerik taramasi sonucu", etiketler=("status",))

#: SVG sanitize sonucu — `security/svg.py` `KOD_*` değerleri.
SVG_SANITIZE_TOTAL: Counter = REGISTRY.counter(
	"svg_sanitize", "SVG sanitize sonucu", etiketler=("slot", "code")
)

#: Politika ihlali — `contracts/errors.py` sebep + aksiyon.
POLICY_VIOLATION_TOTAL: Counter = REGISTRY.counter(
	"policy_violation", "Slot politikasi ihlali", etiketler=("slot", "reason", "action")
)

#: Depolama kullanımı — envanter işinin yazdığı anlık değerler.
STORAGE_BYTES: Gauge = REGISTRY.gauge("storage_bytes", "Depolanan bayt", etiketler=("tier", "access"))
STORAGE_OBJECTS: Gauge = REGISTRY.gauge(
	"storage_objects", "Depolanan nesne sayisi", etiketler=("tier", "access")
)

#: Yetim dosya sayısı — canlı ölçümde 1.166 bulundu; sıfıra inmesi hedef.
ORPHAN_FILES: Gauge = REGISTRY.gauge("orphan_files", "Referanssiz disk dosyasi sayisi")

#: PII koruma haritası kapsamı — `docs/security/faz13-tehdit-modeli.md` T-132.
#: `status` ∈ {mapped, unmapped}. `unmapped > 0` bir AÇIKTIR, uyarı kuralı buna bağlanır.
PII_FIELD_COVERAGE: Gauge = REGISTRY.gauge(
	"pii_field_coverage", "EXCLUDED doctype alan kapsami", etiketler=("status",)
)

#: Korumasız hassas dosya — bugün ÖLÇÜLDÜ: 3 (Order/Payment Transaction receipt_url).
PII_UNPROTECTED_FILES: Gauge = REGISTRY.gauge(
	"pii_unprotected_files", "Haritasiz alanda duran public hassas dosya sayisi"
)

#: Denetim (ADL) olayı — `media/audit.py` `log_media_event` / `log_media_batch`
#: her çağrıldığında artar. Sayaç ADL'nin YERİNE geçmez, ONU İZLER: denetim
#: yazımı sessizce durursa (best-effort olduğu için istisna fırlatmaz) bugün
#: bunu fark ettirecek hiçbir sinyal yok. `action` ADL'nin kendi eylem adı,
#: `decision` allow/deny, `severity` normal/high. Aktör, kiracı ve dosya
#: ETİKET DEĞİLDİR — yüksek kardinalite + PII (bkz. `logging.py` sözleşmesi).
AUDIT_EVENT_TOTAL: Counter = REGISTRY.counter(
	"audit_event", "Denetim kaydina yazilan medya olayi", etiketler=("action", "decision", "severity")
)

#: Video dönüşüm süresi. Görsel kovaları burada işe yaramaz: `transcode.py`
#: `FFMPEG_TIMEOUT_SECONDS = 1700` ile çalışıyor, yani 60 sn'lik üst kova
#: neredeyse her işi `+Inf`e atardı ve histogram bilgi taşımazdı.
VIDEO_DURATION_BUCKETS: tuple[float, ...] = (1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 900.0, 1700.0)

#: `action` `video/decision.py` aksiyonu (transcode/remux/copy), `outcome`
#: ∈ {accepted, rejected, error} — "ffmpeg patladı" ile "çıktı fayda kapısını
#: geçemedi" AYNI ŞEY DEĞİL (`TranscodeResult` docstring'i bunu vurguluyor) ve
#: tek bir "başarısız" kovasına düşerlerse alarm yanlış yere bakar.
VIDEO_TRANSCODE_DURATION: Histogram = REGISTRY.histogram(
	"video_transcode_duration_seconds",
	"Video donusum suresi (saniye)",
	etiketler=("action", "outcome"),
	buckets=VIDEO_DURATION_BUCKETS,
)

#: Ölçüm noktası sarmalayıcısının KENDİ hatası (`instrument.py`). Sıfırdan
#: büyük olması "metrikler eksik toplanıyor" demektir; sarmalayıcı hatayı
#: yutmak zorunda (ölçüm, ölçtüğü işi düşüremez) ama SESSİZ kalmamalı.
INSTRUMENT_ERRORS_TOTAL: Counter = REGISTRY.counter(
	"instrumentation_errors", "Olcum noktasinda yutulan hata", etiketler=("point",)
)

# ── T-123 · gerçek kullanıcı ölçümü (RUM) ───────────────────────────────
#
# Birim ayrımı bilinçli: LCP/INP/FCP/TTFB milisaniye, CLS BİRİMSİZ. İkisini
# tek metrik adı altında toplamak Prometheus'ta anlamsız bir toplam üretir
# (`sum(rum_p75)` = "2500 ms + 0,1" gibi) ve panelde ölçek tek eksende
# çizilemez. Bu yüzden iki ayrı ad var.

#: p75 — CWV raporlamasının standart yüzdeliği. `rum.aggregate()` üretir.
RUM_P75_MS: Gauge = REGISTRY.gauge(
	"rum_p75_milliseconds",
	"Gercek kullanici p75 degeri (milisaniye)",
	etiketler=("metric", "route", "device_class"),
)

#: CLS birimsizdir — ayrı ad. `route` ve `device_class` etiketleri aynı.
RUM_CLS_P75: Gauge = REGISTRY.gauge(
	"rum_cls_p75", "Gercek kullanici CLS p75 degeri (birimsiz)", etiketler=("route", "device_class")
)

#: Kabul edilen örneklem sayısı. `rating` ∈ {good, needs-improvement, poor}.
RUM_SAMPLES_TOTAL: Counter = REGISTRY.counter(
	"rum_samples",
	"Kabul edilen RUM olcumu sayisi",
	etiketler=("metric", "route", "device_class", "rating"),
)

#: Örneklem oranıyla genelleştirilmiş tahmini kullanıcı sayısı. Ham sayı
#: ile tahmin AYRI tutulur: %1 örneklemde ham sayıyı "toplam" diye sunmak
#: `rum.aggregate()` docstring'inin açıkça uyardığı hatadır.
RUM_ESTIMATED_POPULATION: Gauge = REGISTRY.gauge(
	"rum_estimated_population",
	"Orneklem oraniyla genellestirilmis tahmini olcum sayisi",
	etiketler=("metric", "route", "device_class"),
)

#: Reddedilen gövde — `reason` `RumError` sınıfı (pii_field, unknown_metric…).
#: Sıfırdan büyük ve ARTIYORSA ya istemci sözleşmeyi bozdu ya biri PII
#: göndermeye çalışıyor; ikisi de görünmeli.
RUM_REJECTED_TOTAL: Counter = REGISTRY.counter(
	"rum_rejected", "Reddedilen RUM govdesi", etiketler=("reason",)
)


def render() -> str:
	"""Varsayılan kayıt defterinin `/metrics` gövdesi."""
	return REGISTRY.render()


def content_type() -> str:
	return REGISTRY.content_type()


__all__ = [
	"AUDIT_EVENT_TOTAL",
	"AYRILMIS_ETIKETLER",
	"BYTE_BUCKETS",
	"BYTES_SAVED_TOTAL",
	"DURATION_BUCKETS",
	"IMAGE_PROCESS_DURATION",
	"INSTRUMENT_ERRORS_TOTAL",
	"ISOLATION_TOTAL",
	"JOB_ATTEMPTS",
	"JOB_TOTAL",
	"MEDIA_JOB_DURATION_SECONDS",
	"MEDIA_JOB_FAILURES_TOTAL",
	"MEDIA_PROCESSED_TOTAL",
	"MEDIA_QUEUE_DEPTH",
	"MEDIA_QUEUE_JOBS",
	"MEGAPIXEL_BUCKETS",
	"NAMESPACE",
	"ORPHAN_FILES",
	"PII_FIELD_COVERAGE",
	"PII_UNPROTECTED_FILES",
	"POLICY_VIOLATION_TOTAL",
	"REGISTRY",
	"RUM_CLS_P75",
	"RUM_ESTIMATED_POPULATION",
	"RUM_P75_MS",
	"RUM_REJECTED_TOTAL",
	"RUM_SAMPLES_TOTAL",
	"SCAN_TOTAL",
	"SOURCE_BYTES",
	"SOURCE_MEGAPIXELS",
	"STORAGE_BYTES",
	"STORAGE_OBJECTS",
	"SVG_SANITIZE_TOTAL",
	"TYPE_COUNTER",
	"TYPE_GAUGE",
	"TYPE_HISTOGRAM",
	"UPLOAD_TOTAL",
	"VIDEO_DURATION_BUCKETS",
	"VIDEO_TRANSCODE_DURATION",
	"Counter",
	"Gauge",
	"Histogram",
	"Metric",
	"MetricError",
	"Registry",
	"content_type",
	"merge_json",
	"render",
]
