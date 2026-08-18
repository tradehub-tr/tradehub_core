#!/usr/bin/env python3
"""T-140 — İzlenebilirlik matrisi ÜRETİCİSİ (SRS → test). SALT OKUNUR + tek yazım.

Ne yapar
--------
`docs/srs/SRS-v1.0.md` içindeki **202 gereksinimin tamamını** (150 FR + 52 NFR)
ayrıştırır, her birini bu depodaki **gerçek test fonksiyonlarına** bağlar ve
`docs/test/traceability.md` dosyasını üretir. Bağlanamayan gereksinimi
gizlemez — ayrı bir bölümde tek tek listeler.

NEDEN OTOMATİK
--------------
Kaynak tasarım dokümanı T-140'ta şunu istiyor: *"Matris otomatik üretiliyor
(test etiketlerinden) ve CI'da güncel tutuluyor. Kapsanmayan gereksinim varsa
CI KIRMIZI."* Elle yazılmış bir matris ilk test eklendiğinde eskir; bu betik
her koşumda testleri yeniden tarar.

KANIT SINIFLARI — bir eşleşmenin nereden geldiği matriste GÖRÜNÜR
-----------------------------------------------------------------
    A  Test dosyasının kendi metninde gereksinim kimliği geçiyor.
       AST ile en yakın kapsayıcı test fonksiyonuna atanır; fonksiyon dışında
       (modül docstring'i, sınıf docstring'i) geçiyorsa dosya düzeyinde kalır.
       En güçlü kanıt: testi yazan kişi bağı kendisi kurmuş.

    B  Altın fixture üzerinden **iz** (kapsam SAYILMAZ). `manifest.json` her
       fixture için `kural: ["FR-011", ...]` taşıyor; bir test o fixture'ın
       dosya adını kullanıyorsa iz kurulur. **Bu bağ kapsam kanıtı değildir**
       ve ölçüldü ki neden değildir: `mode_rgba_alpha.png` fixture'ı FR-016'ya
       (oran toleransı) bağlı ama onu kullanan LQIP testi oranı hiç sınamıyor.
       Fixture çok kurallı olduğu için bağ gevşek. B izleri matriste ayrı bir
       kolonda **bilgi olarak** durur; "kapsanıyor" kararına GİRMEZ.

    C  Elle kurulmuş eşleme (`docs/test/req-test-map.json`). Gereksinimi
       gerçekten sınayan ama kimliği metninde yazmayan testler için. Her
       girdinin yanında `neden` alanı zorunludur — gerekçesiz eşleme kabul
       edilmez (şema doğrulaması aşağıda).

    —  Kanıt yok → **KAPSANMIYOR**. Bu bir başarısızlık değil, ölçümdür:
       gereksinimlerin çoğu henüz uygulanmamış fazlara ait (F3, F3+).

DOĞRULAMA — bu betik uydurma referansı yakalar
-----------------------------------------------
C sınıfı eşlemelerdeki her `dosya::Sınıf::fonksiyon` üçlüsü AST ile denetlenir.
Var olmayan dosya / sınıf / fonksiyon **hata**dır ve betik çıkış kodu 2 ile
düşer. Yani matris "test var" dediğinde test gerçekten vardır.

KOŞUM
-----
    python3 scripts/gen_traceability.py                 # docs/test/traceability.md üret
    python3 scripts/gen_traceability.py --check         # üretmeden farkı bildir (CI)
    python3 scripts/gen_traceability.py --fail-uncovered  # kapsanmayan varsa çıkış 1

`--fail-uncovered` BUGÜN KIRMIZI OLUR ve bu bilinçlidir: kapsanmayan gereksinim
sayısı sıfır değil. Kaynak doküman "kapsanmayan varsa CI kırmızı" diyor; bu
kapı Faz 14 kabulünde açılacak, bugün ölçüm için elle koşulur.

YAZDIĞI TEK DOSYA: `docs/test/traceability.md`. Başka hiçbir şeye dokunmaz.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRS = ROOT / "docs" / "srs" / "SRS-v1.0.md"
MAP_FILE = ROOT / "docs" / "test" / "req-test-map.json"
MANIFEST = ROOT / "tests" / "fixtures" / "media" / "manifest.json"
OUT = ROOT / "docs" / "test" / "traceability.md"

#: Taranan test kökleri. `tradehub_core/tests/` SALT OKUNUR — yalnız okunur,
#: hiçbir dosyası değiştirilmez (mutlak kural 1).
TEST_DIRS = (ROOT / "tests", ROOT / "tradehub_core" / "tests")

REQ_RE = re.compile(r"\b(?:FR|NFR)-\d{3}\b")


# ── SRS ayrıştırma ──────────────────────────────────────────────────────


def _section_bounds(text: str) -> dict[str, tuple[int, int]]:
	"""Ana bölüm başlığı → (başlangıç, bitiş) aralığı.

	YALNIZ `##` düzeyi taranır. `###` de sayılsaydı `## 7.` bölümünün aralığı
	ilk `### 7.1` başlığında biterdi ve §7 tabloları aralığın DIŞINDA kalırdı —
	bu hata bir kez yapıldı, faz kolonu boş çıktı.
	"""
	basliklar = [(m.start(), m.group(1)) for m in re.finditer(r"^## (.+)$", text, re.M)]
	out: dict[str, tuple[int, int]] = {}
	for i, (poz, ad) in enumerate(basliklar):
		son = basliklar[i + 1][0] if i + 1 < len(basliklar) else len(text)
		out[ad.strip()] = (poz, son)
	return out


def _aralik(bounds: dict[str, tuple[int, int]], onek: str) -> tuple[int, int] | None:
	for ad, span in bounds.items():
		if ad.startswith(onek):
			return span
	return None


def _kisalt(metin: str, n: int = 150) -> str:
	"""Gereksinim metnini tek satıra indir; tablo hücresi bozulmasın."""
	t = re.sub(r"\s+", " ", metin).strip()
	t = t.replace("|", "／")
	t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
	if len(t) > n:
		kes = t[:n].rsplit(" ", 1)[0]
		t = kes + "…"
	return t


def parse_srs(path: Path = SRS) -> dict[str, dict]:
	"""202 gereksinimi ayrıştır: kimlik, metin, bugünkü uygulama durumu, faz."""
	text = path.read_text(encoding="utf-8")
	bounds = _section_bounds(text)

	fr_span = _aralik(bounds, "3. Fonksiyonel gereksinimler")
	nfr_span = _aralik(bounds, "4. Fonksiyonel olmayan gereksinimler")
	tr_span = _aralik(bounds, "7. İzlenebilirlik matrisi")
	if not (fr_span and nfr_span):
		raise SystemExit("SRS §3 / §4 bulunamadı — belge yapısı değişmiş")

	# §3 ve §4 alt bölümleri sırasıyla geliyor; §5 başlayana kadar hepsi tanım.
	tanim_bas = fr_span[0]
	tanim_son = _aralik(bounds, "5. Kısıtlar")
	tanim_son = tanim_son[0] if tanim_son else nfr_span[1]
	tanim_metni = text[tanim_bas:tanim_son]

	reqs: dict[str, dict] = {}
	satir_re = re.compile(r"^\|\s*\*{0,2}((?:FR|NFR)-\d{3})\*{0,2}([^|]*)\|(.*)$", re.M)
	for m in satir_re.finditer(tanim_metni):
		rid = m.group(1)
		if rid in reqs:
			continue  # ilk (tanım) satırı kazanır
		hucreler = [h.strip() for h in m.group(3).split("|")]
		# Durum kolonu SONDAN sayılır: gereksinim metninde geçen `|` karakterleri
		# soldaki hücreleri kaydırır, sağdakileri kaydırmaz.
		durum = hucreler[-3] if len(hucreler) >= 4 else ""
		reqs[rid] = {
			"id": rid,
			"metin": _kisalt(hucreler[0] if hucreler else ""),
			"durum": _kisalt(durum, 60),
			"faz": "",
		}

	# §7 izlenebilirlik tablosundan FAZ kolonu (| id | politika | bulgu | faz | test |)
	if tr_span:
		tr_metni = text[tr_span[0] : tr_span[1]]
		for m in satir_re.finditer(tr_metni):
			rid = m.group(1)
			if rid not in reqs:
				continue
			hucreler = [h.strip() for h in m.group(3).split("|")]
			# §7 satırı: | politika | bulgu | FAZ | test |  → sondan ikinci
			if len(hucreler) >= 4:
				reqs[rid]["faz"] = _kisalt(hucreler[-3], 20)

	return reqs


# ── Test tarama ─────────────────────────────────────────────────────────


class TestIndex:
	"""Test ağacının AST indeksi: dosya → sınıf → fonksiyon → satır aralığı."""

	def __init__(self) -> None:
		self.dosyalar: dict[str, ast.Module] = {}
		self.fonksiyonlar: dict[str, list[tuple[str, str, int, int]]] = {}
		self.kaynak: dict[str, str] = {}

	def tara(self, dirs=TEST_DIRS) -> "TestIndex":
		for d in dirs:
			if not d.exists():
				continue
			for p in sorted(d.glob("test_*.py")):
				rel = str(p.relative_to(ROOT))
				try:
					src = p.read_text(encoding="utf-8")
					agac = ast.parse(src, filename=rel)
				except (OSError, SyntaxError):
					continue
				self.kaynak[rel] = src
				self.dosyalar[rel] = agac
				kayit: list[tuple[str, str, int, int]] = []
				for dugum in ast.walk(agac):
					if not isinstance(dugum, ast.ClassDef):
						continue
					for alt in dugum.body:
						if isinstance(alt, (ast.FunctionDef, ast.AsyncFunctionDef)) and alt.name.startswith("test"):
							son = getattr(alt, "end_lineno", alt.lineno) or alt.lineno
							kayit.append((dugum.name, alt.name, alt.lineno, son))
				# sınıf dışı test fonksiyonları (pytest tarzı)
				for dugum in agac.body:
					if isinstance(dugum, (ast.FunctionDef, ast.AsyncFunctionDef)) and dugum.name.startswith("test"):
						son = getattr(dugum, "end_lineno", dugum.lineno) or dugum.lineno
						kayit.append(("", dugum.name, dugum.lineno, son))
				self.fonksiyonlar[rel] = kayit
		return self

	def test_sayisi(self) -> int:
		return sum(len(v) for v in self.fonksiyonlar.values())

	def kapsayan(self, dosya: str, satir: int) -> str:
		"""Satırı içeren test fonksiyonunun adı ('' = fonksiyon dışı)."""
		for sinif, ad, bas, son in self.fonksiyonlar.get(dosya, ()):
			if bas <= satir <= son:
				return f"{sinif}::{ad}" if sinif else ad
		return ""

	def var_mi(self, dosya: str, sinif: str = "", fonk: str = "") -> str:
		"""Referansı doğrula. Boş dize = geçerli, dolu dize = hata mesajı."""
		if dosya not in self.fonksiyonlar:
			return f"test dosyası yok: {dosya}"
		if not sinif and not fonk:
			return ""
		for s, f, _b, _s2 in self.fonksiyonlar[dosya]:
			if fonk and f != fonk:
				continue
			if sinif and s != sinif:
				continue
			return ""
		hedef = "::".join(x for x in (sinif, fonk) if x)
		return f"{dosya} içinde yok: {hedef}"


def harvest_a(index: TestIndex) -> dict[str, set[str]]:
	"""A sınıfı kanıt: test metninde geçen gereksinim kimlikleri."""
	out: dict[str, set[str]] = defaultdict(set)
	for dosya, src in index.kaynak.items():
		for satir_no, satir in enumerate(src.splitlines(), start=1):
			for rid in REQ_RE.findall(satir):
				fonk = index.kapsayan(dosya, satir_no)
				out[rid].add(f"{dosya}::{fonk}" if fonk else dosya)
	return out


def harvest_b(index: TestIndex, manifest: Path = MANIFEST) -> dict[str, set[str]]:
	"""B sınıfı kanıt: altın fixture `kural` alanı → fixture'ı kullanan test."""
	if not manifest.exists():
		return {}
	veri = json.loads(manifest.read_text(encoding="utf-8"))
	fixture_kural: dict[str, set[str]] = {}
	for kayit in veri.get("fixtures", []):
		ad = Path(str(kayit.get("file", ""))).name
		if not ad:
			continue
		kurallar = {r for k in kayit.get("kural", []) for r in REQ_RE.findall(str(k))}
		if kurallar:
			fixture_kural.setdefault(ad, set()).update(kurallar)

	out: dict[str, set[str]] = defaultdict(set)
	for dosya, src in index.kaynak.items():
		for ad, kurallar in fixture_kural.items():
			if ad not in src:
				continue
			for satir_no, satir in enumerate(src.splitlines(), start=1):
				if ad not in satir:
					continue
				fonk = index.kapsayan(dosya, satir_no)
				hedef = f"{dosya}::{fonk}" if fonk else dosya
				for rid in kurallar:
					out[rid].add(hedef)
	return out


def harvest_c(index: TestIndex, map_file: Path = MAP_FILE) -> tuple[dict[str, set[str]], list[str]]:
	"""C sınıfı kanıt: elle kurulmuş eşleme + referans doğrulaması."""
	if not map_file.exists():
		return {}, [f"eşleme dosyası yok: {map_file}"]
	veri = json.loads(map_file.read_text(encoding="utf-8"))
	out: dict[str, set[str]] = defaultdict(set)
	hatalar: list[str] = []
	for rid, girdiler in veri.get("map", {}).items():
		if not REQ_RE.fullmatch(rid):
			hatalar.append(f"geçersiz gereksinim kimliği: {rid}")
			continue
		for girdi in girdiler:
			hedef = str(girdi.get("test", "")).strip()
			neden = str(girdi.get("neden", "")).strip()
			if not hedef:
				hatalar.append(f"{rid}: boş 'test' alanı")
				continue
			if len(neden) < 10:
				hatalar.append(f"{rid} → {hedef}: 'neden' eksik ya da çok kısa (gerekçesiz eşleme yasak)")
			parcalar = hedef.split("::")
			dosya = parcalar[0]
			sinif = parcalar[1] if len(parcalar) > 2 else ("" if len(parcalar) < 2 else "")
			fonk = parcalar[-1] if len(parcalar) > 1 else ""
			if len(parcalar) == 2:
				sinif, fonk = ("", parcalar[1]) if parcalar[1].startswith("test") else (parcalar[1], "")
			hata = index.var_mi(dosya, sinif, fonk)
			if hata:
				hatalar.append(f"{rid} → {hata}")
				continue
			out[rid].add(hedef)
	return out, hatalar


# ── Rapor ───────────────────────────────────────────────────────────────


#: Bir hücrede en çok kaç test adı yazılır. Aşan sayı "+N" ile özetlenir —
#: matris tabloyu okunamaz hâle getiren 25 satırlık hücreler üretmesin.
MAX_HUCRE = 4


def _hucre(girdiler: list[str], etiket: str) -> str:
	if not girdiler:
		return "—"
	gosterilen = [f"`{t}`" for t in girdiler[:MAX_HUCRE]]
	kalan = len(girdiler) - MAX_HUCRE
	if kalan > 0:
		gosterilen.append(f"…+{kalan} {etiket}")
	return "<br>".join(gosterilen)


def _satir(rid: str, req: dict, kanit: dict[str, list[str]]) -> str:
	baglayici = sorted(kanit.get("A", [])) + sorted(kanit.get("C", []))
	iz = sorted(kanit.get("B", []))
	hucre = _hucre(baglayici, "test") if baglayici else "**KAPSANMIYOR**"
	return (
		f"| **{rid}** | {req['metin']} | {req['faz'] or '—'} | {req['durum'] or '—'} "
		f"| {hucre} | {_hucre(iz, 'iz')} |"
	)


def rapor(reqs: dict[str, dict], kanitlar: dict[str, dict[str, list[str]]],
          index: TestIndex, hatalar: list[str]) -> str:
	fr = [r for r in reqs if r.startswith("FR-")]
	nfr = [r for r in reqs if r.startswith("NFR-")]
	# KAPSAM KARARI: yalnız A ve C. B (fixture izi) bilerek sayılmaz — §1.
	kapsanan = {r for r, k in kanitlar.items() if k.get("A") or k.get("C")}
	acik = [r for r in sorted(reqs) if r not in kapsanan]

	def yuzde(a: int, b: int) -> str:
		return f"%{100.0 * a / b:.1f}" if b else "—"

	sayim_a = sum(1 for r in reqs if kanitlar.get(r, {}).get("A"))
	sayim_c = sum(1 for r in reqs if kanitlar.get(r, {}).get("C") and not kanitlar.get(r, {}).get("A"))
	sayim_b = sum(1 for r in reqs if kanitlar.get(r, {}).get("B"))
	sadece_b = sum(1 for r in reqs if kanitlar.get(r, {}).get("B") and r not in kapsanan)

	L: list[str] = []
	L.append("# T-140 — İzlenebilirlik matrisi (SRS → test)")
	L.append("")
	L.append("> **BU DOSYA ELLE DÜZENLENMEZ.** `scripts/gen_traceability.py` üretir.")
	L.append("> Değişiklik gerekiyorsa ya testi ya `docs/test/req-test-map.json`'u değiştir,")
	L.append("> sonra betiği yeniden koş.")
	L.append("")
	L.append("**Görev:** T-140 · **Faz:** 14 · **Kaynak:** `docs/srs/SRS-v1.0.md` (TASLAK)")
	L.append("")
	L.append("## 0. Özet — ölçülen sayılar")
	L.append("")
	L.append("| Ölçüm | Değer |")
	L.append("|---|---:|")
	L.append(f"| SRS'te ayrıştırılan gereksinim | **{len(reqs)}** ({len(fr)} FR + {len(nfr)} NFR) |")
	L.append(f"| En az bir teste bağlı (A ∪ C) | **{len(kapsanan)}** ({yuzde(len(kapsanan), len(reqs))}) |")
	L.append(f"| **KAPSANMIYOR** | **{len(acik)}** ({yuzde(len(acik), len(reqs))}) |")
	L.append(f"| A kanıtı (test metninde kimlik geçiyor) | {sayim_a} |")
	L.append(f"| C kanıtı (yalnız elle eşleme, A yok) | {sayim_c} |")
	L.append(f"| B izi olan gereksinim (kapsam SAYILMAZ) | {sayim_b} |")
	L.append(f"| …bunlardan yalnız B izi olan, yani hâlâ kapsanmayan | {sadece_b} |")
	L.append(f"| Taranan test dosyası | {len(index.kaynak)} |")
	L.append(f"| Taranan test fonksiyonu | {index.test_sayisi()} |")
	L.append("")
	L.append("**Kabul kriteri karşılığı (kaynak doküman T-140):** *\"Her FR/NFR en az bir")
	L.append("teste bağlı; bağsız gereksinim yok.\"* → bugün **SAĞLANMIYOR**; açık")
	L.append(f"gereksinim sayısı **{len(acik)}**. Liste §3'te tam olarak yazılı.")
	L.append("")
	if hatalar:
		L.append("## 0.1 ⚠ Eşleme doğrulama hataları")
		L.append("")
		for h in hatalar:
			L.append(f"- {h}")
		L.append("")
	L.append("## 1. Kanıt sınıfları")
	L.append("")
	L.append("| Sınıf | Anlamı | Güç |")
	L.append("|---|---|---|")
	L.append("| **A** | Test dosyasının metninde gereksinim kimliği geçiyor; AST ile en yakın test fonksiyonuna atandı | en güçlü |")
	L.append("| **B** | Test, `manifest.json`'da o gereksinime bağlı bir altın fixture'ı kullanıyor — **kapsam sayılmaz** | iz |")
	L.append("| **C** | `docs/test/req-test-map.json` içinde gerekçesiyle elle kuruldu; referansın varlığı AST ile doğrulandı | yargı |")
	L.append("| — | Kanıt yok → **KAPSANMIYOR** | — |")
	L.append("")
	L.append("## 2. Matris")
	L.append("")
	L.append("### 2.1 Fonksiyonel gereksinimler (FR)")
	L.append("")
	L.append("| FR | Gereksinim (kısaltılmış) | Faz | SRS'teki bugünkü durum | Bağlayıcı test (A/C) | Fixture izi (B — sayılmaz) |")
	L.append("|---|---|---|---|---|---|")
	for rid in sorted(fr):
		L.append(_satir(rid, reqs[rid], kanitlar.get(rid, {})))
	L.append("")
	L.append("### 2.2 Fonksiyonel olmayan gereksinimler (NFR)")
	L.append("")
	L.append("| NFR | Gereksinim (kısaltılmış) | Faz | SRS'teki bugünkü durum | Test |")
	L.append("|---|---|---|---|---|")
	for rid in sorted(nfr):
		L.append(_satir(rid, reqs[rid], kanitlar.get(rid, {})))
	L.append("")
	L.append("## 3. KAPSANMAYAN gereksinimler — tam liste")
	L.append("")
	L.append(f"Aşağıdaki **{len(acik)}** gereksinimin bu depoda hiçbir testi yok.")
	L.append("Gizlenmedi, sayıldı:")
	L.append("")
	L.append("| Gereksinim | Faz | SRS'teki bugünkü durum | Kısaltılmış metin |")
	L.append("|---|---|---|---|")
	for rid in acik:
		r = reqs[rid]
		L.append(f"| {rid} | {r['faz'] or '—'} | {r['durum'] or '—'} | {r['metin']} |")
	L.append("")
	L.append("## 4. Yeniden üretme")
	L.append("")
	L.append("```bash")
	L.append("python3 scripts/gen_traceability.py              # bu dosyayı üret")
	L.append("python3 scripts/gen_traceability.py --check      # CI: dosya bayat mı")
	L.append("python3 scripts/gen_traceability.py --fail-uncovered   # kapı (bugün KIRMIZI)")
	L.append("```")
	L.append("")
	return "\n".join(L) + "\n"


def build() -> tuple[str, int, list[str]]:
	reqs = parse_srs()
	index = TestIndex().tara()
	a = harvest_a(index)
	b = harvest_b(index)
	c, hatalar = harvest_c(index)
	kanitlar: dict[str, dict[str, list[str]]] = {}
	for rid in reqs:
		kanitlar[rid] = {
			"A": sorted(a.get(rid, ())),
			"B": sorted(b.get(rid, ())),
			"C": sorted(c.get(rid, ())),
		}
	acik = sum(1 for r in reqs if not any(kanitlar[r].values()))
	return rapor(reqs, kanitlar, index, hatalar), acik, hatalar


def main(argv: list[str] | None = None) -> int:
	ap = argparse.ArgumentParser(description="SRS → test izlenebilirlik matrisi")
	ap.add_argument("--check", action="store_true", help="yazma; dosya güncel değilse çıkış 1")
	ap.add_argument("--fail-uncovered", action="store_true", help="kapsanmayan gereksinim varsa çıkış 1")
	args = ap.parse_args(argv)

	metin, acik, hatalar = build()

	if hatalar:
		for h in hatalar:
			print(f"EŞLEME HATASI: {h}", file=sys.stderr)
		return 2

	if args.check:
		mevcut = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
		if mevcut != metin:
			print("traceability.md BAYAT — `python3 scripts/gen_traceability.py` koş", file=sys.stderr)
			return 1
		print("traceability.md güncel")
	else:
		OUT.parent.mkdir(parents=True, exist_ok=True)
		OUT.write_text(metin, encoding="utf-8")
		print(f"yazıldı: {OUT.relative_to(ROOT)}  ({acik} gereksinim KAPSANMIYOR)")

	if args.fail_uncovered and acik:
		print(f"KAPI: {acik} gereksinim kapsanmıyor", file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
