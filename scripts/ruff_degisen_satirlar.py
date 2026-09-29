"""CI ruff kapısı — yalnız bu değişiklikte eklenen/değişen SATIRLARDAKİ ihlaller kırmızı verir.

İki denetim: `ruff check` ihlalleri ve `ruff format` farkı (biçimlendirici değişen bir satıra
dokunuyorsa). Depoda 418 dosya biçimsiz (29 Eyl 2026 ölçüldü); `ruff format --check --range`
denetim modunda aralığı yok sayıp dosyanın tamamını raporladığı için fark burada hesaplanır.
Bilinen sınır: biçimsiz bir ifadenin (örn. 136 satırlık `frozenset({...})`) İÇİNE satır eklenirse
biçimlendirici ifadenin tamamını değiştirmek istediği için kapı kırmızı verir — çare ifadeyi
biçimlemek: `ruff format --range <bas>:<son> <dosya>` (yalnız boşluk değişir).

NEDEN: Kapı eskiden değişen DOSYALARIN tamamına bakıyordu. Depoda 92 dosyada 1.221 eski ihlal
var (29 Eyl 2026, ruff 0.16.3); birleştirme commit'i bu dosyalardan birine dokununca kapı,
değişikliği yapan kişinin yazmadığı satırlar yüzünden kırmızı oluyordu — son 20 koşunun 20'si.
Kırmızı kapı kapı değildir, herkes atlar. Artık kırmızı = "bu değişiklikteki kod".

    python scripts/ruff_degisen_satirlar.py <taban> [<uc>]     # git diff <taban> <uc> (uc: çalışma ağacı)

Çıkış 1: değişen satırda ihlal var (GitHub açıklaması olarak basılır). Dokunulan dosyalardaki eski
ihlaller yalnız sayılır, kapıyı etkilemez.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def degisen_satirlar(taban: str, uc: str | None) -> dict[str, set[int]]:
	"""Dosya → bu değişiklikte eklenen/değişen satır numaraları (yeni sürümde)."""
	komut = [
		"git",
		"diff",
		"-U0",
		"--diff-filter=ACMR",
		"--no-color",
		taban,
		*([uc] if uc else []),
		"--",
		"*.py",
	]
	cikti = subprocess.run(komut, capture_output=True, text=True, check=True).stdout
	satirlar: dict[str, set[int]] = {}
	dosya = None
	for satir in cikti.splitlines():
		if satir.startswith("+++ "):
			yol = satir[4:]
			dosya = yol[2:] if yol.startswith("b/") else None
			if dosya:
				satirlar.setdefault(dosya, set())
		elif dosya and (m := HUNK.match(satir)):
			bas, adet = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
			satirlar[dosya].update(range(bas, bas + adet))
	return {d: s for d, s in satirlar.items() if s and os.path.isfile(d)}


def ruff_ihlalleri(dosyalar: list[str]) -> list[dict]:
	p = subprocess.run(
		["ruff", "check", "--output-format=json", "--exit-zero", *dosyalar], capture_output=True, text=True
	)
	if p.returncode != 0:
		sys.exit(f"ruff çalışmadı: {p.stderr.strip()}")
	return json.loads(p.stdout or "[]")


def bicim_farki_satirlari(dosya: str) -> set[int]:
	"""Biçimlendiricinin DEĞİŞTİRECEĞİ özgün satırlar (1 tabanlı)."""
	ozgun = open(dosya, encoding="utf-8").read()
	p = subprocess.run(
		["ruff", "format", "--stdin-filename", dosya, "-"], input=ozgun, capture_output=True, text=True
	)
	if p.returncode != 0:
		sys.exit(f"ruff format çalışmadı ({dosya}): {p.stderr.strip()}")
	a, b = ozgun.splitlines(), p.stdout.splitlines()
	satirlar: set[int] = set()
	for etiket, i1, i2, _j1, _j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
		if etiket != "equal":
			# Salt ekleme (i1 == i2) komşu satırı işaretler.
			satirlar.update(range(i1 + 1, max(i2, i1 + 1) + 1))
	return satirlar


def main() -> int:
	if len(sys.argv) < 2:
		sys.exit(__doc__)
	degisen = degisen_satirlar(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
	if not degisen:
		print("Değişen Python satırı yok.")
		return 0
	kok = os.getcwd()
	yeni, eski = [], 0
	for ihlal in ruff_ihlalleri(sorted(degisen)):
		dosya = os.path.relpath(ihlal["filename"], kok)
		satir = ihlal["location"]["row"]
		if satir in degisen.get(dosya, ()):
			yeni.append((dosya, satir, ihlal["location"]["column"], ihlal["code"], ihlal["message"]))
		else:
			eski += 1
	bicim, eski_bicim = [], 0
	for dosya, satirlar in sorted(degisen.items()):
		fark = bicim_farki_satirlari(dosya)
		kesisen = sorted(fark & satirlar)
		if kesisen:
			bicim.append((dosya, kesisen[0], len(kesisen)))
		elif fark:
			eski_bicim += 1
	for dosya, satir, sutun, kod, mesaj in yeni:
		print(f"::error file={dosya},line={satir},col={sutun}::{kod} {mesaj}")
	for dosya, satir, adet in bicim:
		print(
			f"::error file={dosya},line={satir}::ruff format — değişen {adet} satır biçimsiz (ruff format {dosya})"
		)
	print(
		f"{len(degisen)} dosya, {sum(map(len, degisen.values()))} değişen satır · "
		f"değişen satırlarda ihlal: {len(yeni)}, biçimsiz: {len(bicim)} dosya · "
		f"eski (kapıyı etkilemez): {eski} ihlal, {eski_bicim} biçimsiz dosya"
	)
	return 1 if yeni or bicim else 0


if __name__ == "__main__":
	sys.exit(main())
