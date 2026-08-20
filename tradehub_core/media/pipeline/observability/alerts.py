"""T-133 — alarm kuralları ve gösterge paneli: METİN olarak üretilir, kurulmaz.

DÜRÜSTLÜK NOTU — bu dosya bir kurulum DEĞİLDİR
==============================================
Bu depoda Prometheus da Grafana da **kurulu değildir** (ölçüldü, 2026-08-19:
`deploy/grafana/` yok, `docker/` altında prometheus servisi yok ve `docker/`
bu görevin kapsamı dışında). Dolayısıyla burada üretilen kurallar bugün
**hiçbir yerde yüklü değil** ve hiçbir alarm ateşlemez.

O hâlde neden var: T-133'ün alarm kriterinin iki yarısı var ve yalnız biri
altyapıya bağlı.

    üretilebilir  → kural ifadesi, eşik, `for` süresi, runbook bağlantısı,
                    paneller — hepsi metrik adlarına bağlı ve bu depoda yaşar
    üretilemez    → Prometheus'un o kuralı yüklemesi, Alertmanager'ın
                    bildirmesi, Grafana'nın paneli çizmesi

Eşikler ve ifadeler metrik adlarıyla birlikte VERSİYONLANMALIDIR: metrik adı
değiştiğinde kural sessizce boşalır. Kuralı ayrı bir depoya (ya da elle
Grafana arayüzüne) koymak, tam olarak bu sessiz kopmayı üretir. `dogrula()`
bunu makine ile kontrol eder — bir kural var olmayan bir metriğe atıf
yapıyorsa test KIRMIZI olur.

EŞİKLER NEREDEN GELDİ
=====================
Uydurulmuş sayı yok; her eşiğin kaynağı `kaynak` alanında yazılı. Kaynağı
"dış standart" olanlar (CWV) bu projede ölçülmedi ve öyle işaretlendi.

RUNBOOK
=======
Her alarmın bir `runbook` slug'ı vardır ve beklenen dosya yolu
`docs/ops/runbooks/<slug>.md`'dir. **Bugün `docs/ops/` dizini YOKTUR**
(ölçüldü). Runbook metinlerinin bir kısmı `docs/plans/faz14-golive.md` §5
içinde duruyor ama ayrı dosya olarak değil. `runbook_gaps()` eksik dosyaları
sayar; rapor bu sayıyı verir, gizlemez.

`import frappe` YOKTUR; PyYAML de içe aktarılmaz (kural metni elle üretilir,
bkz. `to_prometheus_rules`).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import metrics as mm

#: Runbook dosyalarının beklendiği dizin (depo köküne göre).
RUNBOOK_DIZINI: str = "docs/ops/runbooks"

SEVERITY_CRITICAL: str = "critical"
SEVERITY_WARNING: str = "warning"

#: Kural grubunun adı — Prometheus `groups[].name`.
GRUP_ADI: str = "media-engine"

#: Değerlendirme aralığı. 30 sn'lik bir scrape aralığında 1 dakikalık
#: değerlendirme, kuralın her scrape'te değil her iki scrape'te bir
#: çalışması demektir; alarmın kendisi bir yük kaynağı olmamalı.
DEGERLENDIRME_ARALIGI: str = "1m"


@dataclass(frozen=True)
class Alarm:
	"""Tek alarm kuralı. Eşik + gerekçe + runbook AYRILMAZ üçlüdür.

	Gerekçesiz eşik, altı ay sonra kimsenin dokunmaya cesaret edemediği bir
	sayıdır; runbook'suz alarm ise gece 3'te uyandırdığı kişiye ne yapacağını
	söylemez ve birkaç kez sonra susturulur.
	"""

	ad: str
	ifade: str
	sure: str
	severity: str
	ozet: str
	aciklama: str
	runbook: str
	#: Bu kuralın okuduğu metrik adları — `dogrula()` varlıklarını kontrol eder.
	metrikler: Tuple[str, ...]
	#: Eşiğin kaynağı: ölçüm raporu, kod sabiti ya da dış standart.
	kaynak: str

	def to_dict(self) -> Dict[str, Any]:
		return {
			"alert": self.ad,
			"expr": self.ifade,
			"for": self.sure,
			"labels": {"severity": self.severity, "component": "media"},
			"annotations": {
				"summary": self.ozet,
				"description": self.aciklama,
				"runbook_url": f"{RUNBOOK_DIZINI}/{self.runbook}.md",
				"threshold_source": self.kaynak,
			},
		}


ALARMLAR: Tuple[Alarm, ...] = (
	Alarm(
		ad="MediaUploadRejectionSpike",
		ifade=(
			'sum(rate(media_upload_total{outcome="rejected"}[15m]))'
			" / clamp_min(sum(rate(media_upload_total[15m])), 0.001) > 0.30"
		),
		sure="10m",
		severity=SEVERITY_WARNING,
		ozet="Yükleme reddi oranı %30'u aştı",
		aciklama=(
			"Slot politikası yüklemelerin üçte birinden fazlasını reddediyor. Ya bir "
			"politika fazla sıkı ayarlandı ya da bir istemci bozuk dosya gönderiyor. "
			"`reason` etiketine göre kırılım al: tek bir kod baskınsa politika, "
			"dağınıksa istemci sorunudur."
		),
		runbook="media-upload-rejection",
		metrikler=("media_upload_total",),
		kaynak="operasyonel eşik — reddin normal seviyesi henüz ÖLÇÜLMEDİ, ilk hafta sonrası ayarlanmalı",
	),
	Alarm(
		ad="MediaMalwareDetected",
		ifade='increase(media_scan_total{status="infected"}[10m]) > 0',
		sure="0m",
		severity=SEVERITY_CRITICAL,
		ozet="Zararlı içerik bulundu ve karantinaya alındı",
		aciklama=(
			"AV taraması en az bir dosyayı `infected` işaretledi. Dosya erişimin "
			"dışına taşındı (`media/av.py` karantina). Denetim kaydından "
			"(`media.quarantine`) yükleyen kiracıyı bul; aynı kiracıdan gelen diğer "
			"yüklemeleri gözden geçir."
		),
		runbook="media-malware",
		metrikler=("media_scan_total",),
		kaynak="sıfır tolerans — tek olay bile incelenir",
	),
	Alarm(
		ad="MediaScanFailing",
		ifade=(
			'sum(rate(media_scan_total{status="failed"}[15m]))'
			" / clamp_min(sum(rate(media_scan_total[15m])), 0.001) > 0.10"
		),
		sure="15m",
		severity=SEVERITY_CRITICAL,
		ozet="AV taraması başarısız oluyor — dosyalar taranmadan geçiyor olabilir",
		aciklama=(
			"`failed` bir güvenlik olayıdır: 'tarandı ve temiz' ile 'hiç taranmadı' "
			"arasındaki farkı kaybediyoruz. Tarayıcı ikilisi (`scanner_available()`) "
			"ve karantina dizininin yazılabilirliği kontrol edilmeli."
		),
		runbook="media-scan-failure",
		metrikler=("media_scan_total",),
		kaynak="operasyonel eşik",
	),
	Alarm(
		ad="MediaIsolationFailures",
		ifade='sum(increase(media_isolation_total{reason!="ok"}[15m])) > 5',
		sure="10m",
		severity=SEVERITY_WARNING,
		ozet="İzole çalıştırma tekrar tekrar başarısız",
		aciklama=(
			"`reason` etiketi sebebi söyler: `isolation_timeout` (60 sn duvar "
			"saati aşıldı), `isolation_memory` (1,5 GB adres alanı — dekompresyon "
			"bombası şüphesi), `isolation_cpu`. Bomba şüphesinde dosyayı yükleyen "
			"kiracıya bak; hepsi timeout ise makine yükünü kontrol et."
		),
		runbook="media-isolation",
		metrikler=("media_isolation_total",),
		kaynak="`security/isolation.py` SEBEP_OK = 'ok'; 15 dakikada 5 arıza normal dışı",
	),
	Alarm(
		ad="MediaImageProcessingSlow",
		ifade=(
			"histogram_quantile(0.95, sum by (le, op)"
			"(rate(media_image_process_duration_seconds_bucket[15m]))) > 5"
		),
		sure="15m",
		severity=SEVERITY_WARNING,
		ozet="Görsel işleme p95 süresi 5 saniyeyi aştı",
		aciklama=(
			"Ölçülen dağılımın tamamı ilk dört kovaya düşüyordu (72,71 MP → 1,05 s). "
			"p95'in 5 sn'yi aşması ya alışılmadık büyüklükte dosyalar geldiğini ya "
			"da makinenin doygun olduğunu gösterir; `media_source_megapixels` "
			"histogramıyla birlikte oku."
		),
		runbook="media-slow-processing",
		metrikler=("media_image_process_duration_seconds",),
		kaynak="`metrics.py` kova gerekçesi — ölçülen en kötü süre 1,05 s, 5 sn ~5 kat pay",
	),
	Alarm(
		ad="MediaSvgRejected",
		ifade='sum(increase(media_svg_sanitize_total{code!="ok"}[1h])) > 0',
		sure="0m",
		severity=SEVERITY_WARNING,
		ozet="SVG sanitize bir dosyayı reddetti ya da içeriğini değiştirdi",
		aciklama=(
			"`code` etiketine bak: `svg_compressed_forbidden` / "
			"`logo_svg_dtd_forbidden` bilinen saldırı desenleridir (billion laughs). "
			"SVG yükleme kapıları bugün KAPALI olduğu için bu sayacın artması, "
			"kapının açıldığı ya da başka bir yoldan SVG geldiği anlamına gelir."
		),
		runbook="media-svg",
		metrikler=("media_svg_sanitize_total",),
		kaynak="`security/svg.py` KOD_OK = 'ok'; sıfır tolerans",
	),
	Alarm(
		ad="MediaOrphanFilesGrowing",
		ifade="media_orphan_files > 1200",
		sure="1h",
		severity=SEVERITY_WARNING,
		ozet="Referanssız disk dosyası sayısı ölçülen taban çizgisini aştı",
		aciklama=(
			"Canlı ölçümde 1.166 yetim dosya bulundu ve hedef bu sayının DÜŞMESİ. "
			"Artıyorsa çöp toplama (`storage/retention.py`) ya çalışmıyor ya da bir "
			"silme yolu `File` kaydını bırakıp diski temizlemiyor."
		),
		runbook="media-orphans",
		metrikler=("media_orphan_files",),
		kaynak="canlı ölçüm: 1.166 yetim dosya (metrics.py ORPHAN_FILES notu)",
	),
	Alarm(
		ad="MediaUnprotectedPiiFiles",
		ifade="media_pii_unprotected_files > 0",
		sure="0m",
		severity=SEVERITY_CRITICAL,
		ozet="Hassas bir dosya public katmanda duruyor",
		aciklama=(
			"KVKK olayı. 2026-08-19'da bu sayı 3 ölçüldü (Order / Payment "
			"Transaction `receipt_url`) ve dosyalar private'a taşındı; sıfırdan "
			"büyük her değer aynı sınıf sızıntının tekrarıdır. "
			"`docs/security/kvkk.md` §4 müdahale adımlarını verir."
		),
		runbook="media-pii-exposure",
		metrikler=("media_pii_unprotected_files",),
		kaynak="`19-d2-hash-ortusme.md` — 4 dosya bulundu, 4'ü kapatıldı; hedef 0",
	),
	Alarm(
		ad="MediaPiiFieldCoverageGap",
		ifade='media_pii_field_coverage{status="unmapped"} > 0',
		sure="30m",
		severity=SEVERITY_CRITICAL,
		ozet="PII koruma haritasında kapsanmayan alan var",
		aciklama=(
			"`presets.EXCLUDED_MEDIA_FIELDS` haritası bir doctype'ın dosya tutan "
			"alanını kaçırıyor. Kaçan alan, `set_level()` public'e geçiş korumasının "
			"DIŞINDA kalır — 146 kimlik belgesi tam bu boşluktan geçmişti."
		),
		runbook="media-pii-coverage",
		metrikler=("media_pii_field_coverage",),
		kaynak="`presets.py` KVKK bakım notu + T-132 F-03",
	),
	Alarm(
		ad="MediaAuditWritesStopped",
		ifade=(
			"sum(rate(media_audit_event_total[1h])) == 0"
			" and sum(rate(media_upload_total[1h])) > 0"
		),
		sure="1h",
		severity=SEVERITY_CRITICAL,
		ozet="Yükleme var ama denetim kaydı yazılmıyor",
		aciklama=(
			"`media/audit.py` best-effort'tur ve yazamadığında istisna FIRLATMAZ. "
			"Bu kural o sessizliğin tek panzehiri: trafik varken denetim satırı "
			"üretilmiyorsa ADL yazımı kırılmıştır (izin, tablo ya da commit "
			"hatası). KVKK m.12 işleme kaydı yükümlülüğü bu sürede karşılanmıyor."
		),
		runbook="media-audit-gap",
		metrikler=("media_audit_event_total", "media_upload_total"),
		kaynak="`media/audit.py` `_persist` best-effort davranışı",
	),
	Alarm(
		ad="MediaInstrumentationErrors",
		ifade="sum(increase(media_instrumentation_errors_total[1h])) > 0",
		sure="0m",
		severity=SEVERITY_WARNING,
		ozet="Ölçüm noktası hata yutuyor — metrikler eksik toplanıyor",
		aciklama=(
			"`observability/instrument.py` kayıt fonksiyonu istisna aldı ve yuttu "
			"(ölçüm, ölçtüğü işi düşüremez). Sonuç: ilgili metrik EKSİK sayıyor. "
			"Panelde 'sorun yok' görünmesinin en sinsi sebebi budur."
		),
		runbook="media-instrumentation",
		metrikler=("media_instrumentation_errors_total",),
		kaynak="sıfır tolerans — sarmalayıcı hatası her zaman bir kod hatasıdır",
	),
	Alarm(
		ad="MediaVideoTranscodeErrors",
		ifade=(
			'sum(rate(media_video_transcode_duration_seconds_count{outcome="error"}[30m]))'
			" / clamp_min(sum(rate(media_video_transcode_duration_seconds_count[30m])), 0.001) > 0.20"
		),
		sure="30m",
		severity=SEVERITY_WARNING,
		ozet="Video dönüşümlerinin beşte birinden fazlası hata veriyor",
		aciklama=(
			"`outcome=error` ffmpeg'in düşmesidir; `outcome=rejected` ise çıktının "
			"fayda kapısını geçememesidir ve NORMALDİR. Kural yalnız `error` dalına "
			"bakar — ikisini karıştıran bir alarm her gereksiz dönüşümde çalardı."
		),
		runbook="media-transcode",
		metrikler=("media_video_transcode_duration_seconds",),
		kaynak="operasyonel eşik — hata oranı taban çizgisi ÖLÇÜLMEDİ",
	),
	Alarm(
		ad="RumLcpRegression",
		ifade='max(media_rum_p75_milliseconds{metric="LCP"}) > 2500',
		sure="1h",
		severity=SEVERITY_WARNING,
		ozet="Saha LCP p75 'iyi' eşiğini aştı",
		aciklama=(
			"Core Web Vitals 'iyi' sınırı 2500 ms. Rota kırılımına bak: lab "
			"ölçümünde /urun/:slug 919 ms, /urunler 1062 ms idi — saha değeri lab'ın "
			"çok üstündeyse fark cihaz/ağ dağılımından gelir, kod regresyonundan "
			"değil. `lcp_profile` etiketi hangi türevin indirildiğini söyler."
		),
		runbook="rum-lcp",
		metrikler=("media_rum_p75_milliseconds",),
		kaynak="DIŞ STANDART — web.dev CWV eşiği; bu projede ÖLÇÜLMEDİ (rum.RATING_THRESHOLDS)",
	),
	Alarm(
		ad="RumClsRegression",
		ifade="max(media_rum_cls_p75) > 0.25",
		sure="1h",
		severity=SEVERITY_WARNING,
		ozet="Saha CLS p75 'kötü' bölgesinde",
		aciklama=(
			"Lab ölçümünde /urunler zaten 0,51 ile kötü bölgedeydi (eşik 0,25); yani "
			"bu alarm ateşlendiğinde şaşırmak yerine bilinen bir borcun sahada da "
			"göründüğü doğrulanmış olur. Kaynak: ölçü verilmeyen görsel kutuları."
		),
		runbook="rum-cls",
		metrikler=("media_rum_cls_p75",),
		kaynak="DIŞ STANDART (CWV) + lab ölçümü: /urunler CLS 0,51 (rum.LAB_BASELINE_CLS)",
	),
	Alarm(
		ad="RumInpRegression",
		ifade='max(media_rum_p75_milliseconds{metric="INP"}) > 200',
		sure="1h",
		severity=SEVERITY_WARNING,
		ozet="Saha INP p75 'iyi' eşiğini aştı",
		aciklama=(
			"INP bu projede HİÇ ölçülemedi (`03-performans-taban-cizgisi.md` §6.3): "
			"lab ortamında etkileşim üretilemiyor. Bu yüzden ilk saha verisi aynı "
			"zamanda ilk INP ölçümüdür ve alarm eşiği dış standarttır."
		),
		runbook="rum-inp",
		metrikler=("media_rum_p75_milliseconds",),
		kaynak="DIŞ STANDART — web.dev CWV eşiği; projede hiç ölçülmedi",
	),
	Alarm(
		ad="RumRejectedSpike",
		ifade="sum(increase(media_rum_rejected_total[15m])) > 10",
		sure="15m",
		severity=SEVERITY_WARNING,
		ozet="RUM gövdeleri reddediliyor",
		aciklama=(
			"`reason` etiketi ayırır: `pii_field` bir istemcinin sözleşmeyi delip "
			"kimlik alanı göndermesidir (güvenlik olayı), diğerleri istemci "
			"sürümünün şemadan sapmasıdır. İlkinde storefront sürümü derhal "
			"incelenmeli."
		),
		runbook="rum-rejected",
		metrikler=("media_rum_rejected_total",),
		kaynak="operasyonel eşik — saha trafiği henüz YOK, ilk hafta sonrası ayarlanmalı",
	),
)


# ── Prometheus kural dosyası ────────────────────────────────────────────


def _yaml_metin(deger: str) -> str:
	"""YAML dizgi değeri — HER ZAMAN çift tırnaklı.

	PyYAML içe aktarılmıyor (`metrics.py` bağımlısızlık kuralı) ve bu, elle
	üretimin tek riskini doğuruyor: kaçırma hatası. Risk, "koşulla kaçır"
	yerine "her zaman tırnakla" ile kapatıldı — PromQL ifadeleri `{`, `}`,
	`"` ve `:` içerir ve bunların hepsi tırnaksız YAML'da anlam taşır.
	"""
	kacirilmis = str(deger).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
	return f'"{kacirilmis}"'


def to_prometheus_rules(alarmlar: Sequence[Alarm] = ALARMLAR, *, grup: str = GRUP_ADI) -> str:
	"""Prometheus kural dosyası (YAML) — deterministik metin.

	Çıktı `promtool check rules` ile doğrulanmalıdır; bu depoda `promtool`
	KURULU DEĞİL ve doğrulama YAPILMADI (raporda böyle yazılı).
	"""
	satirlar: List[str] = [
		"# ÜRETİLMİŞ DOSYA — kaynağı:",
		"#   tradehub_core/media/pipeline/observability/alerts.py",
		"# Elle düzenleme, bir sonraki üretimde kaybolur ve metrik adlarıyla",
		"# birlikte versiyonlanma güvencesini bozar.",
		"groups:",
		f"  - name: {_yaml_metin(grup)}",
		f"    interval: {_yaml_metin(DEGERLENDIRME_ARALIGI)}",
		"    rules:",
	]
	for a in alarmlar:
		veri = a.to_dict()
		satirlar.append(f"      - alert: {_yaml_metin(veri['alert'])}")
		satirlar.append(f"        expr: {_yaml_metin(veri['expr'])}")
		satirlar.append(f"        for: {_yaml_metin(veri['for'])}")
		satirlar.append("        labels:")
		for k in sorted(veri["labels"]):
			satirlar.append(f"          {k}: {_yaml_metin(veri['labels'][k])}")
		satirlar.append("        annotations:")
		for k in sorted(veri["annotations"]):
			satirlar.append(f"          {k}: {_yaml_metin(veri['annotations'][k])}")
	return "\n".join(satirlar) + "\n"


# ── Grafana panosu ──────────────────────────────────────────────────────

#: Panel satırları: (başlık, PromQL, birim). Panelin metrik adlarına bağlı
#: olması bilinçli — pano da kural gibi metrikle birlikte versiyonlanır.
PANELLER: Tuple[Tuple[str, str, str], ...] = (
	("Yükleme sonucu (kabul / ret)", "sum by (outcome) (rate(media_upload_total[5m]))", "ops"),
	("Ret sebepleri", 'topk(5, sum by (reason) (rate(media_upload_total{outcome="rejected"}[15m])))', "ops"),
	(
		"Görsel işleme p95",
		"histogram_quantile(0.95, sum by (le, op) (rate(media_image_process_duration_seconds_bucket[5m])))",
		"s",
	),
	("Kaynak çözünürlük dağılımı", "sum by (le) (rate(media_source_megapixels_bucket[1h]))", "short"),
	("AV tarama sonucu", "sum by (status) (rate(media_scan_total[15m]))", "ops"),
	("İzolasyon sebebi", 'sum by (reason) (increase(media_isolation_total{reason!="ok"}[1h]))', "short"),
	("Denetim olayı", "sum by (action) (rate(media_audit_event_total[15m]))", "ops"),
	("Korumasız hassas dosya", "media_pii_unprotected_files", "short"),
	("Yetim dosya", "media_orphan_files", "short"),
	("Depolama", "sum by (tier) (media_storage_bytes)", "bytes"),
	("RUM p75 (ms)", "media_rum_p75_milliseconds", "ms"),
	("RUM CLS p75", "media_rum_cls_p75", "short"),
)


def grafana_dashboard(*, baslik: str = "Medya Motoru — T-133") -> Dict[str, Any]:
	"""Grafana pano tanımı (JSON'a çevrilebilir sözlük).

	`uid` SABİTTİR: pano her üretimde aynı adrese içe aktarılsın, her seferinde
	yeni bir kopya oluşmasın. Panel `id`leri sıradan verilir; Grafana'nın
	kendi düzenleyicisinde yapılan değişiklikler bu üretimle EZİLİR — pano da
	kod, kaynağı bu dosyadır.
	"""
	paneller: List[Dict[str, Any]] = []
	for i, (ad, ifade, birim) in enumerate(PANELLER):
		paneller.append(
			{
				"id": i + 1,
				"title": ad,
				"type": "timeseries",
				"gridPos": {"h": 8, "w": 12, "x": (i % 2) * 12, "y": (i // 2) * 8},
				"fieldConfig": {"defaults": {"unit": birim}, "overrides": []},
				"targets": [{"expr": ifade, "refId": "A", "legendFormat": "{{__name__}}"}],
			}
		)
	return {
		"uid": "media-engine-t133",
		"title": baslik,
		"tags": ["media", "t-133"],
		"timezone": "browser",
		"schemaVersion": 39,
		"refresh": "1m",
		"time": {"from": "now-6h", "to": "now"},
		"panels": paneller,
	}


def grafana_dashboard_json(**kw: Any) -> str:
	"""Panonun JSON metni — deterministik (anahtarlar sıralı)."""
	return json.dumps(grafana_dashboard(**kw), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ── Doğrulama ───────────────────────────────────────────────────────────


def runbook_paths(alarmlar: Sequence[Alarm] = ALARMLAR) -> Tuple[str, ...]:
	"""Her alarmın beklediği runbook dosya yolu — tekrarsız ve sıralı."""
	return tuple(sorted({f"{RUNBOOK_DIZINI}/{a.runbook}.md" for a in alarmlar}))


def runbook_gaps(repo_koku: str, alarmlar: Sequence[Alarm] = ALARMLAR) -> Tuple[str, ...]:
	"""Var OLMAYAN runbook dosyaları. Boş dönmesi kriterin karşılandığı demek."""
	return tuple(y for y in runbook_paths(alarmlar) if not os.path.isfile(os.path.join(repo_koku, y)))


def dogrula(
	alarmlar: Sequence[Alarm] = ALARMLAR, *, registry: Optional[mm.Registry] = None
) -> Dict[str, Any]:
	"""Kural ↔ metrik tutarlılığı. Bu fonksiyon T-133'ün sessiz kopma sigortası.

	Üç şey kontrol edilir:

	  1. Her kuralın atıf yaptığı metrik GERÇEKTEN tanımlı mı (yoksa kural
	     hiç ateşlenmez ve bunu kimse fark etmez),
	  2. Alarm adları tekil mi (Prometheus tekrarı kabul eder ve ikisi de
	     ateşler — gürültü),
	  3. Hangi metriklerin hiç alarmı yok (bilgi; her metriğin alarmı OLMAK
	     ZORUNDA değil, ama listenin görünmesi karar vermeyi sağlar).
	"""
	kayit = registry or mm.REGISTRY
	tanimli = {m.ad for m in kayit.metrikler()}
	bilinmeyen: List[Tuple[str, str]] = []
	alarmli: set = set()
	adlar: List[str] = []
	for a in alarmlar:
		adlar.append(a.ad)
		for metrik in a.metrikler:
			alarmli.add(metrik)
			if metrik not in tanimli:
				bilinmeyen.append((a.ad, metrik))
	tekrar = sorted({ad for ad in adlar if adlar.count(ad) > 1})
	return {
		"alerts": len(alarmlar),
		"unknown_metrics": bilinmeyen,
		"duplicate_names": tekrar,
		"metrics_with_alert": sorted(alarmli & tanimli),
		"metrics_without_alert": sorted(tanimli - alarmli),
		"runbooks": list(runbook_paths(alarmlar)),
	}


__all__ = [
	"ALARMLAR",
	"DEGERLENDIRME_ARALIGI",
	"GRUP_ADI",
	"PANELLER",
	"RUNBOOK_DIZINI",
	"SEVERITY_CRITICAL",
	"SEVERITY_WARNING",
	"Alarm",
	"dogrula",
	"grafana_dashboard",
	"grafana_dashboard_json",
	"runbook_gaps",
	"runbook_paths",
	"to_prometheus_rules",
]
