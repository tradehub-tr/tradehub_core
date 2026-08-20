"""T-133 — çok süreçli `/metrics` gövdesi: parça yaz, birleştir, tek metin üret.

SORUN — `metrics.py`'nin kendi başlığında yazılı ve çözülmemiş
=============================================================
Kayıt defteri SÜREÇ İÇİDİR. Frappe hattında en az üç süreç ailesi var ve
üçü de kendi sayacını tutar (bu makinede ölçüldü, 2026-08-19):

    istoc-dev-backend-1       gunicorn web
    istoc-dev-queue-short-1   RQ worker
    istoc-dev-queue-long-1    RQ worker
    istoc-dev-scheduler-1     scheduler

`/metrics` ucu bunlardan BİRİNDEN servis edilirse, yüklemenin web sürecinde
sayılan yarısı görünür, transcode'un worker'da sayılan yarısı görünmez. Panel
"3 yükleme" der, gerçekte 11'dir. Bu, yanlış sayı göstermekten daha kötüdür:
sayı makul göründüğü için kimse sorgulamaz.

`metrics.py` iki çıkış yolu bırakmıştı ve seçimi bu dosyaya erteledi. Seçilen:
**(2) `dump_json()` çıktısını ortak bir dizinde topla, tek uçtan render et.**

Neden (1) değil (her sürece ayrı scrape hedefi): süreç sayısı sabit değil
(RQ worker'ları ölçeklenir), her yeni worker Prometheus tarafında yeni bir
hedef tanımı ister ve `sum by (job)` her sorguya elle yazılmak zorunda kalır.
Dosya tabanlı toplama, süreç sayısından BAĞIMSIZDIR.

Neden Redis değil: `metrics.py`'nin bağımlılıksızlık kuralı. Dosya sistemi
zaten var; `prometheus_client`'ın `multiproc_dir`'i de aynı yolu kullanır —
icat edilmiş bir çözüm değil.

ÖLÜ SÜREÇ SORUNU — açıkça
=========================
Bir worker öldüğünde parçası diskte kalır ve sayaçları sonsuza dek toplamda
görünür. İki yanlıştan az zararlısı seçildi:

  * Parçayı hemen silmek → sayaç GERİ DÜŞER. Prometheus sayaç düşüşünü
    "restart" sayar ve `rate()` o aralıkta bozulur, ama bu BEKLENEN bir
    durumdur ve düzelir.
  * Parçayı sonsuza dek tutmak → ölü sürecin sayısı canlıymış gibi
    toplanır; "bugün 400 yükleme" der, aslında 40'ı dünkü ölü worker'dan.

Seçim: `max_age_s` ile YAŞ SINIRI (varsayılan kapalı, çağıran karar verir) +
`prune()` ile açık temizlik. Varsayılanı kapalı bırakmak bilinçli: yaş sınırı
scrape aralığından kısa ayarlanırsa canlı süreçlerin parçaları da düşer ve
metrikler titrer. Doğru değer dağıtım kararıdır, kütüphane kararı değil.

GÖSTERGE BİRLEŞTİRME — neden `latest`
=====================================
Sayaç ve histogram TOPLANIR; toplam anlamlıdır. Gösterge için toplam çoğu
zaman YANLIŞTIR: `media_storage_bytes` tek bir envanter işi tarafından
yazılır, iki süreç de yazarsa toplamak depoyu iki katı gösterir. Varsayılan
bu yüzden "en son yazan parça kazanır" (`latest`). Toplanması gereken bir
gösterge çıkarsa (`GAUGE_POLITIKA`) tek satırla ilan edilir — sessiz bir
varsayılan yerine açık bir sözlük.

`import frappe` YOKTUR.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import metrics as mm

#: Parça dosyalarının uzantısı — dizinde başka dosya varsa karışmasın.
UZANTI: str = ".metrics.json"

#: Toplama dizini ortam değişkeni. Ad `prometheus_client`in
#: `PROMETHEUS_MULTIPROC_DIR`ine kasten BENZER ama aynı DEĞİL: aynı adı
#: kullanmak, gerçek kütüphane bir gün kurulduğunda iki toplayıcının aynı
#: dizine yazması demekti.
DIZIN_DEGISKENI: str = "MEDIA_METRICS_DIR"

#: Gösterge birleştirme politikası: metrik adı → "latest" | "sum" | "max".
#: Listede olmayan gösterge `latest` ile birleşir (bkz. modül başlığı).
GAUGE_POLITIKA: Dict[str, str] = {}

VARSAYILAN_GAUGE_POLITIKA: str = "latest"


class ExportError(RuntimeError):
	"""Parça yazılamadı ya da dizin kullanılamaz.

	Yazma hatası SESSİZ geçilmez: parçası yazılmayan bir süreç, `/metrics`
	çıktısından tamamen kaybolur ve bunu fark ettirecek hiçbir sinyal olmaz.
	"""


def dizin(varsayilan: Optional[str] = None) -> Optional[str]:
	"""Toplama dizini — ortam değişkeni ya da verilen varsayılan."""
	return os.environ.get(DIZIN_DEGISKENI) or varsayilan


def shard_path(hedef_dizin: str, *, namespace: str = mm.NAMESPACE, pid: Optional[int] = None) -> str:
	"""Bu sürecin parça dosyası. Ad `<namespace>-<pid>` — çakışma olamaz."""
	return os.path.join(hedef_dizin, f"{namespace}-{pid or os.getpid()}{UZANTI}")


def write_shard(
	registry: Optional[mm.Registry] = None,
	*,
	hedef_dizin: Optional[str] = None,
	pid: Optional[int] = None,
) -> str:
	"""Kayıt defterini parça dosyasına yaz. ATOMİK — yarım dosya okunmaz.

	`os.replace` kullanılır: okuyucu tam dosyayı ya da eski dosyayı görür,
	yarısını asla. Yarım JSON okumak `/metrics`i tamamen düşürürdü (Prometheus
	tek hatalı satırda bütün scrape'i reddeder).
	"""
	kayit = registry or mm.REGISTRY
	yol_dizin = hedef_dizin or dizin()
	if not yol_dizin:
		raise ExportError(f"toplama dizini yok ({DIZIN_DEGISKENI} tanimsiz)")
	try:
		os.makedirs(yol_dizin, exist_ok=True)
		hedef = shard_path(yol_dizin, namespace=kayit.namespace, pid=pid)
		gecici_fd, gecici = tempfile.mkstemp(dir=yol_dizin, suffix=".tmp")
		try:
			with os.fdopen(gecici_fd, "w", encoding="utf-8") as f:
				f.write(kayit.dump_json())
			os.replace(gecici, hedef)
		except BaseException:
			# Geçici dosya kalırsa dizin sessizce şişer; scrape onu okumaz
			# ama disk dolar.
			try:
				os.unlink(gecici)
			except OSError:
				pass
			raise
	except OSError as e:
		raise ExportError(f"parca yazilamadi: {e}") from e
	return hedef


def shard_files(hedef_dizin: str, *, max_age_s: float = 0.0) -> List[str]:
	"""Dizindeki parça dosyaları — ada göre SIRALI (çıktı deterministik olsun).

	`max_age_s > 0` ise bu yaştan eski parçalar ATLANIR (ölü süreç).
	"""
	try:
		adlar = sorted(a for a in os.listdir(hedef_dizin) if a.endswith(UZANTI))
	except OSError:
		return []
	if max_age_s <= 0:
		return [os.path.join(hedef_dizin, a) for a in adlar]
	simdi = time.time()
	out: List[str] = []
	for a in adlar:
		yol = os.path.join(hedef_dizin, a)
		try:
			if simdi - os.path.getmtime(yol) <= max_age_s:
				out.append(yol)
		except OSError:
			continue
	return out


def read_shards(hedef_dizin: str, *, max_age_s: float = 0.0) -> List[Tuple[float, Dict[str, Any]]]:
	"""(mtime, ayrıştırılmış parça) listesi — ESKİDEN YENİYE sıralı.

	Sıra `latest` gösterge politikası için gereklidir: en son yazan kazansın
	diye en yeniyi EN SONA koyarız, birleştirme üzerine yazar.

	Bozuk bir parça ATLANIR, koşum düşmez: tek bir bozuk dosya yüzünden bütün
	`/metrics` çıktısını kaybetmek, o dosyanın taşıdığı sayıları kaybetmekten
	çok daha pahalı.
	"""
	out: List[Tuple[float, Dict[str, Any]]] = []
	for yol in shard_files(hedef_dizin, max_age_s=max_age_s):
		try:
			mtime = os.path.getmtime(yol)
			with open(yol, encoding="utf-8") as f:
				veri = json.load(f)
		except (OSError, ValueError):
			continue
		if isinstance(veri, dict):
			out.append((mtime, veri))
	out.sort(key=lambda p: p[0])
	return out


def merge(parcalar: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
	"""Parçaları TEK bir metrik haritasına indir.

	`metrics.merge_json`den farkı: burada etiket ADLARI ve kova SINIRLARI da
	korunur. `merge_json` yalnız sayı toplar; metin üretmek için meta veri de
	gerekir, yoksa `le=` etiketleri ve etiket adları yeniden kurulamaz.
	"""
	birlesik: Dict[str, Dict[str, Any]] = {}
	for parca in parcalar:
		for m in parca.get("metrics", []) or []:
			ad = m.get("name")
			if not ad:
				continue
			hedef = birlesik.setdefault(
				ad,
				{
					"type": m.get("type"),
					"help": m.get("help"),
					"labels": list(m.get("labels") or []),
					"buckets": list(m.get("buckets") or []),
					"series": {},
				},
			)
			tur = m.get("type")
			for anahtar, seri in (m.get("series") or {}).items():
				if tur == mm.TYPE_HISTOGRAM:
					_birlestir_histogram(hedef["series"], anahtar, seri)
				elif tur == mm.TYPE_COUNTER:
					mevcut = hedef["series"].setdefault(anahtar, {"value": 0.0})
					mevcut["value"] = float(mevcut.get("value", 0.0)) + float(seri.get("value", 0.0))
				else:
					_birlestir_gauge(hedef["series"], ad, anahtar, seri)
	return birlesik


def _birlestir_histogram(seriler: Dict[str, Any], anahtar: str, seri: Dict[str, Any]) -> None:
	kovalar = list(seri.get("buckets") or [])
	hedef = seriler.setdefault(anahtar, {"buckets": [0.0] * len(kovalar), "sum": 0.0, "count": 0.0})
	mevcut = hedef["buckets"]
	if len(mevcut) < len(kovalar):
		# Farklı sürümlerde kova sayısı değişmişse kısa olanı UZAT: kesmek,
		# üst kovaların sayısını sessizce yok etmek olurdu.
		mevcut.extend([0.0] * (len(kovalar) - len(mevcut)))
	for i, v in enumerate(kovalar):
		mevcut[i] += float(v)
	hedef["sum"] = float(hedef.get("sum", 0.0)) + float(seri.get("sum", 0.0))
	hedef["count"] = float(hedef.get("count", 0.0)) + float(seri.get("count", 0.0))


def _birlestir_gauge(seriler: Dict[str, Any], ad: str, anahtar: str, seri: Dict[str, Any]) -> None:
	politika = GAUGE_POLITIKA.get(ad, VARSAYILAN_GAUGE_POLITIKA)
	deger = float(seri.get("value", 0.0))
	mevcut = seriler.get(anahtar)
	if mevcut is None:
		seriler[anahtar] = {"value": deger}
		return
	if politika == "sum":
		mevcut["value"] = float(mevcut["value"]) + deger
	elif politika == "max":
		mevcut["value"] = max(float(mevcut["value"]), deger)
	else:
		# latest — parçalar eskiden yeniye okunduğu için üzerine yazmak
		# "en son yazan kazanır" demektir.
		mevcut["value"] = deger


def render(birlesik: Dict[str, Dict[str, Any]]) -> str:
	"""Birleştirilmiş haritadan Prometheus text format 0.0.4 üret.

	Sayı ve kaçırma biçimi `metrics.py`'nin KENDİ yardımcılarıyla yapılır
	(`_sayi`, `_kacir`, `_help_kacir`). Burada ikinci bir uygulama yazmak,
	tek süreçli `Registry.render()` çıktısı ile çok süreçli çıktının bir gün
	sessizce ayrışması demekti — altın dosya testi de o ayrışmayı görmezdi,
	çünkü iki farklı kodu doğrularlardı.
	"""
	bloklar: List[str] = []
	for ad in sorted(birlesik):
		m = birlesik[ad]
		satirlar = _satirlar(ad, m)
		if not satirlar:
			continue
		bloklar.append(
			"\n".join(
				[
					f"# HELP {ad} {mm._help_kacir(m.get('help') or ad)}",
					f"# TYPE {ad} {m.get('type') or mm.TYPE_GAUGE}",
				]
				+ satirlar
			)
		)
	govde = "\n".join(bloklar)
	return govde + "\n" if govde else ""


def _etiket_metni(adlar: Sequence[str], anahtar: str, ek: Sequence[Tuple[str, str]] = ()) -> str:
	# Seri anahtari `Metric.to_json()` icinde "\u001f" (unit separator) ile
	# birlestirilir. Kaynakta HAM kontrol karakteri yazmak yerine kacis
	# dizisi kullanilir: gorunmez bir bayt, kopyalanirken sessizce
	# kaybolabilecek tek karakterdir.
	degerler = anahtar.split("\u001f") if anahtar else []
	parcalar = [
		f'{adlar[i]}="{mm._kacir(degerler[i])}"' for i in range(min(len(adlar), len(degerler)))
	]
	parcalar += [f'{a}="{mm._kacir(d)}"' for a, d in ek]
	return "{" + ",".join(parcalar) + "}" if parcalar else ""


def _satirlar(ad: str, m: Dict[str, Any]) -> List[str]:
	adlar = list(m.get("labels") or [])
	tur = m.get("type")
	seriler = m.get("series") or {}
	out: List[str] = []
	if tur == mm.TYPE_HISTOGRAM:
		sinirlar = list(m.get("buckets") or [])
		for anahtar in sorted(seriler):
			seri = seriler[anahtar]
			kumulatif = 0.0
			for i, sinir in enumerate(sinirlar):
				kumulatif += float((seri.get("buckets") or [0.0] * len(sinirlar))[i])
				le = "+Inf" if _sonsuz(sinir) else mm._sayi(sinir)
				out.append(f"{ad}_bucket{_etiket_metni(adlar, anahtar, ek=(('le', le),))} {mm._sayi(kumulatif)}")
			temel = _etiket_metni(adlar, anahtar)
			out.append(f"{ad}_sum{temel} {mm._sayi(seri.get('sum', 0.0))}")
			out.append(f"{ad}_count{temel} {mm._sayi(seri.get('count', 0.0))}")
		return out
	for anahtar in sorted(seriler):
		out.append(f"{ad}{_etiket_metni(adlar, anahtar)} {mm._sayi(seriler[anahtar].get('value', 0.0))}")
	return out


def _sonsuz(deger: Any) -> bool:
	"""JSON'da `+Inf` metin olarak taşınır (JSON'ın Infinity'si standart değil)."""
	if isinstance(deger, str):
		return deger.strip() in ("+Inf", "Inf", "inf", "Infinity")
	try:
		return math.isinf(float(deger))
	except (TypeError, ValueError):
		return False


def collect(hedef_dizin: Optional[str] = None, *, max_age_s: float = 0.0) -> str:
	"""Dizindeki bütün parçaları birleştirip `/metrics` gövdesini üret.

	Dizin yoksa TEK SÜREÇ kabul edilir ve yerel kayıt defteri render edilir.
	Bu geri düşüş bilinçli: gözlemlenebilirlik, yapılandırma eksik diye
	tamamen kaybolmamalı — eksik yapılandırma ile eksik ölçüm arasında
	seçim varsa ikincisi tercih edilir ve `sharded=False` ile RAPORLANIR.
	"""
	yol = hedef_dizin or dizin()
	if not yol or not os.path.isdir(yol):
		return mm.REGISTRY.render()
	return render(merge(veri for _mtime, veri in read_shards(yol, max_age_s=max_age_s)))


def metrics_response(
	hedef_dizin: Optional[str] = None, *, max_age_s: float = 0.0
) -> Tuple[str, str]:
	"""(gövde, content-type) — HTTP ucunun ihtiyacı olan her şey."""
	return collect(hedef_dizin, max_age_s=max_age_s), mm.REGISTRY.content_type()


def prune(hedef_dizin: Optional[str] = None, *, max_age_s: float = 86400.0) -> Tuple[str, ...]:
	"""Yaş sınırını aşan parçaları SİL — ölü süreçlerin kalıntısı.

	Varsayılan 24 saat: bir worker'ın 24 saat boyunca hiç metrik yazmaması
	(hiç iş almamış olsa bile süreç ayakta ise periyodik yazım olmalı) ölü
	sayılması için yeterli işaret.
	"""
	yol = hedef_dizin or dizin()
	if not yol or not os.path.isdir(yol):
		return ()
	simdi = time.time()
	silinen: List[str] = []
	for ad in sorted(os.listdir(yol)):
		if not ad.endswith(UZANTI):
			continue
		tam = os.path.join(yol, ad)
		try:
			if simdi - os.path.getmtime(tam) > max_age_s:
				os.unlink(tam)
				silinen.append(ad)
		except OSError:
			continue
	return tuple(silinen)


def durum(hedef_dizin: Optional[str] = None, *, max_age_s: float = 0.0) -> Dict[str, Any]:
	"""Toplayıcının künyesi — sağlık ucu ve rapor için sayılar."""
	yol = hedef_dizin or dizin()
	if not yol or not os.path.isdir(yol):
		return {"sharded": False, "dir": yol, "shards": 0, "metrics": len(mm.REGISTRY.metrikler())}
	parcalar = read_shards(yol, max_age_s=max_age_s)
	birlesik = merge(veri for _m, veri in parcalar)
	seri_sayisi = sum(len(m.get("series") or {}) for m in birlesik.values())
	return {
		"sharded": True,
		"dir": yol,
		"shards": len(parcalar),
		"metrics": len(birlesik),
		"series": seri_sayisi,
		"oldest_shard_age_s": round(time.time() - parcalar[0][0], 1) if parcalar else None,
	}


__all__ = [
	"DIZIN_DEGISKENI",
	"GAUGE_POLITIKA",
	"UZANTI",
	"VARSAYILAN_GAUGE_POLITIKA",
	"ExportError",
	"collect",
	"dizin",
	"durum",
	"merge",
	"metrics_response",
	"prune",
	"read_shards",
	"render",
	"shard_files",
	"shard_path",
	"write_shard",
]
