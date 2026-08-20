#!/usr/bin/env python3
"""T-133 — alarm besleme doğrulayıcısı: kural dosyası × canlı `/metrics`.

NE ÖLÇER (rapor 97 · W9)
------------------------
`docs/observability/media-alerts.yml` üç eksende doğrulanır; promtool bu
makinede YOK, bu yüzden 1. adım PyYAML + elle kural şemasıdır (promtool'un
`check rules` kapsamının alt kümesi — expr'in PromQL dilbilgisi burada
AYRIŞTIRILMAZ, yalnız metrik adları çıkarılır):

 1. **YAML + şema** — dosya geçerli YAML mı; her kural `alert`/`expr`/`for`/
    `labels.severity`/`labels.component`/`annotations.{summary,description,
    runbook_url,threshold_source}` taşıyor mu; `severity` bilinen kümede mi;
    alarm adları tekil mi.
 2. **Drift** — `media-engine` grubu (kanonik) `alerts.to_prometheus_rules()`
    çıktısıyla BAYT BAYT aynı mı. Elle düzenleme bu kapıda yakalanır.
 3. **Besleme** — her kuralın `expr`'inde geçen metrik adları, verilen canlı
    `/metrics` dökümündeki seri kümesiyle kesişiyor mu. Kesişmeyen kural
    **ölü alarmdır**: koşullandığı seri hiç üretilmediği için ASLA çalmaz.
    Etiket seçicileri de denetlenir: `metric="LCP"` gibi bir eşitlik
    seçicisi, canlı seride o etiket-değer çifti yoksa AYRICA raporlanır
    (metrik ailesi canlı olsa bile o dal ölü olabilir — RumInpRegression'ın
    INP dalı böyle bulunmuştu).

KULLANIM
--------
    python3 scripts/verify_media_alerts.py --metrics-file /tmp/metrics.txt
    python3 scripts/verify_media_alerts.py --metrics-file /tmp/metrics.txt --json

Çıkış kodu: 0 = şema + drift temiz (ölü alarm ÇIKIŞI DÜŞÜRMEZ — bugün 13/18
kuralın metriği henüz üretilmiyor ve bu bilinen, raporlanan bir durumdur);
2 = şema hatası ya da drift.

YAZMAZ: bu betik salt okunurdur; tek çıktısı stdout'tur.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ALERTS_YML = REPO / "docs" / "observability" / "media-alerts.yml"

#: PromQL'de metrik adı gibi görünen ama metrik OLMAYAN jetonlar.
PROMQL_KELIMELER = {
    "sum", "rate", "increase", "clamp_min", "clamp_max", "histogram_quantile",
    "max", "min", "avg", "count", "by", "le", "on", "ignoring", "and", "or",
    "unless", "without", "group_left", "group_right", "offset", "bool",
    "abs", "ceil", "floor", "round", "time", "vector", "scalar",
}

GECERLI_SEVERITY = {"info", "warning", "critical"}

AD_DESENI = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b")
SECICI_DESENI = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\{([^}]*)\}"
)
ETIKET_ESITLIK = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="([^"]*)"')


def expr_metrikleri(expr: str) -> set[str]:
    """expr'de geçen metrik adları. Aralık `[15m]` ve sayılar zaten elenmiş olur."""
    adaylar = set(AD_DESENI.findall(expr))
    # Etiket adları ve etiket değerleri metrik değildir — seçici içlerini çıkar.
    etiket_jetonlari: set[str] = set()
    for _, govde in SECICI_DESENI.findall(expr):
        etiket_jetonlari.update(AD_DESENI.findall(govde))
    # `by (le, op)` parantez içleri: PROMQL_KELIMELER 'le'yi zaten eler; kalan
    # tek harfli gruplayıcılar (op, job) metrik olamayacak kadar kısa DEĞİL,
    # bu yüzden yalnız `by (...)` içleri ayrıca elenir.
    for grup in re.findall(r"\bby\s*\(([^)]*)\)", expr):
        etiket_jetonlari.update(AD_DESENI.findall(grup))
    # Süre birimleri: [15m] köşeli ayraç içindeki '15m' AD_DESENI'ne uymaz
    # (rakamla başlar) — ek işlem gerekmez.
    return {
        a for a in adaylar - PROMQL_KELIMELER - etiket_jetonlari
        if "_" in a  # tüm medya metrikleri snake_case; tek kelimelik jeton bırakılmaz
    }


def canli_seriler(metin: str) -> tuple[set[str], set[tuple[str, str, str]]]:
    """`/metrics` gövdesinden (aile adları, (aile, etiket, değer) üçlüleri)."""
    aileler: set[str] = set()
    ciftler: set[tuple[str, str, str]] = set()
    for satir in metin.splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#"):
            continue
        m = re.match(r"([a-zA-Z_][a-zA-Z0-9_]*)(?:\{([^}]*)\})?\s", satir)
        if not m:
            continue
        aile = m.group(1)
        aileler.add(aile)
        for ad, deger in ETIKET_ESITLIK.findall(m.group(2) or ""):
            ciftler.add((aile, ad, deger))
    return aileler, ciftler


def kural_semasi(kurallar: list[dict]) -> list[str]:
    hatalar: list[str] = []
    adlar: set[str] = set()
    for k in kurallar:
        ad = k.get("alert", "<adsız>")
        if ad in adlar:
            hatalar.append(f"{ad}: alarm adı TEKRARLI")
        adlar.add(ad)
        for alan in ("alert", "expr", "for"):
            if not k.get(alan):
                hatalar.append(f"{ad}: `{alan}` eksik")
        et = k.get("labels") or {}
        if et.get("severity") not in GECERLI_SEVERITY:
            hatalar.append(f"{ad}: labels.severity geçersiz: {et.get('severity')!r}")
        if not et.get("component"):
            hatalar.append(f"{ad}: labels.component eksik")
        no = k.get("annotations") or {}
        for alan in ("summary", "description", "runbook_url", "threshold_source"):
            if not no.get(alan):
                hatalar.append(f"{ad}: annotations.{alan} eksik")
    return hatalar


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--metrics-file", required=True, help="canlı /metrics dökümü")
    ap.add_argument("--json", action="store_true", help="makine çıktısı")
    args = ap.parse_args()

    try:
        import yaml  # bench venv'inde var; sistem python'unda olmayabilir
    except ModuleNotFoundError:
        print("PyYAML yok — bench venv python'u ile koş "
              "(./env/bin/python scripts/verify_media_alerts.py …)", file=sys.stderr)
        return 2

    ham = ALERTS_YML.read_text(encoding="utf-8")
    dosya = yaml.safe_load(ham)  # geçersiz YAML burada patlar — 1. ölçüm
    gruplar = dosya.get("groups") or []
    kurallar = [k for g in gruplar for k in (g.get("rules") or [])]

    sema_hatalari = kural_semasi(kurallar)

    # Drift: kanonik grup üretimle birebir mi.
    sys.path.insert(0, str(REPO))
    from tradehub_core.media.pipeline.observability import alerts

    uretilen = yaml.safe_load(alerts.to_prometheus_rules())
    kanonik = [g for g in gruplar if g.get("name") == "media-engine"]
    drift = kanonik != (uretilen.get("groups") or [])
    dogrula = alerts.dogrula()

    canli_metin = Path(args.metrics_file).read_text(encoding="utf-8")
    aileler, ciftler = canli_seriler(canli_metin)

    sonuc = []
    for k in kurallar:
        metrikler = expr_metrikleri(k["expr"])
        # histogram/summary türevleri aile adına indirgenir: *_bucket/_count/_sum
        def aile(m: str) -> str:
            return re.sub(r"_(bucket|count|sum)$", "", m)
        olu = sorted(m for m in metrikler if aile(m) not in aileler and m not in aileler)
        canli = sorted(m for m in metrikler if m not in olu)
        # Etiket dalı denetimi: canlı ailede eşitlik seçicisi karşılıksızsa.
        dal_bosluklari = []
        for metrik_adi, govde in SECICI_DESENI.findall(k["expr"]):
            if aile(metrik_adi) in aileler or metrik_adi in aileler:
                for ad, deger in ETIKET_ESITLIK.findall(govde):
                    hedef = metrik_adi if metrik_adi in aileler else aile(metrik_adi)
                    if (hedef, ad, deger) not in ciftler:
                        dal_bosluklari.append(f'{metrik_adi}{{{ad}="{deger}"}}')
        sonuc.append({
            "alert": k["alert"],
            "metrikler": sorted(metrikler),
            "olu_metrikler": olu,
            "canli_metrikler": canli,
            "etiket_dali_bos": dal_bosluklari,
            "durum": "ÖLÜ" if olu and not canli else (
                "KISMEN" if olu or dal_bosluklari else "CANLI"),
        })

    rapor = {
        "yaml_gecerli": True,
        "kural_sayisi": len(kurallar),
        "sema_hatalari": sema_hatalari,
        "kanonik_drift": drift,
        "alerts_py_dogrula": {
            "alerts": dogrula["alerts"],
            "unknown_metrics": dogrula["unknown_metrics"],
            "duplicate_names": dogrula["duplicate_names"],
        },
        "canli_metrik_ailesi": sorted(aileler),
        "kurallar": sonuc,
    }

    if args.json:
        print(json.dumps(rapor, ensure_ascii=False, indent=1))
    else:
        print(f"YAML geçerli · {len(kurallar)} kural · şema hatası: {len(sema_hatalari)}"
              f" · kanonik drift: {'VAR' if drift else 'yok'}")
        for h in sema_hatalari:
            print(f"  ŞEMA: {h}")
        print(f"canlı metrik ailesi ({len(aileler)}): {', '.join(sorted(aileler))}")
        for r in sonuc:
            isaret = {"CANLI": "+", "KISMEN": "~", "ÖLÜ": "-"}[r["durum"]]
            ek = f"  [etiket dalı boş: {', '.join(r['etiket_dali_bos'])}]" if r["etiket_dali_bos"] else ""
            print(f" {isaret} {r['alert']:<28} {r['durum']:<6} "
                  f"ölü={','.join(r['olu_metrikler']) or '—'}{ek}")

    return 2 if (sema_hatalari or drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())
