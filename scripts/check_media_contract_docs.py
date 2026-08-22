#!/usr/bin/env python3
"""Medya sözleşme belgeleri ↔ kod: aynı değişiklikte mi gidiyorlar?

NEDEN VAR
---------
20-21 Ağu 2026: `upload_policy.py`'de bir davranış tersine döndü (".png adlı
JPEG kabul" → ret), kod içindeki gerekçe paragrafı silindi, ama o kuralı
yazan `docs/MEDYA-YUKLEME-SOZLESMESI.md` değişmedi. Belge ile kod iki gün
çelişti; kimse fark etmedi. Bu betik o durumu mekanik olarak yakalar.

KURAL (ortak çatı, ADR-0023)
----------------------------
`tradehub_core/media/` altında bir modül değiştiyse ve o modülü yöneten
sözleşme belgesi (aşağıdaki eşleme) ya da herhangi bir `docs/adr/*.md` AYNI
değişiklik aralığında değişmemişse → uyarı. Belgeyi değiştirmek zorunlu
değil; **bilerek değiştirmediğini söylemek** zorunlu: commit mesajına
`[contract-ok]` yazınca betik susar.

İki kullanım:
    python3 scripts/check_media_contract_docs.py --range origin/version-15...HEAD
    python3 scripts/check_media_contract_docs.py --staged        # pre-commit

Çıkış kodu: 0 temiz / uyarı, 1 yalnız `--strict` ile ihlal. CI'da ilk sürüm
BLOKLAMAZ (`continue-on-error`); iki ekip ADR-0023'ü imzalayınca `--strict`e
çevrilir. Frappe'siz, stdlib; bench gerekmez.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys

# Modül deseni → yöneten sözleşme belgeleri. Eşleşen HERHANGİ bir belge ya da
# docs/adr/*.md değiştiyse yeterli. Desen glob'dur, repo köküne göredir.
GOVERNANCE: dict[str, tuple[str, ...]] = {
	"tradehub_core/media/upload_policy.py": ("docs/MEDYA-YUKLEME-SOZLESMESI.md",),
	"tradehub_core/media/chunked.py": ("docs/MEDYA-YUKLEME-SOZLESMESI.md",),
	"tradehub_core/media/pipeline/security/content_gate.py": ("docs/MEDYA-YUKLEME-SOZLESMESI.md",),
	"tradehub_core/media/timefmt.py": ("docs/MEDYA-TARIH-STANDARDI.md",),
	"tradehub_core/media/pipeline/api/envelope.py": (
		"docs/MEDYA-TARIH-STANDARDI.md",
		"docs/api/openapi.yaml",
	),
	"tradehub_core/media/pipeline/api/spec.py": ("docs/api/openapi.yaml",),
	"tradehub_core/media/av.py": ("docs/MEDYA-AV-TARAMA.md",),
	"tradehub_core/media/transcode.py": ("docs/MEDYA-ISLEME-PIPELINE.md",),
	"tradehub_core/media/jobs.py": ("docs/MEDYA-ISLEME-PIPELINE.md",),
	"tradehub_core/media/runner.py": ("docs/MEDYA-ISLEME-PIPELINE.md",),
	"tradehub_core/media/backup.py": ("docs/MEDYA-SATICI-YEDEK-SOZLESMESI.md",),
	"tradehub_core/media/restore.py": ("docs/MEDYA-SATICI-YEDEK-SOZLESMESI.md",),
	"tradehub_core/media/seller_backup*.py": ("docs/MEDYA-SATICI-YEDEK-SOZLESMESI.md",),
	"tradehub_core/media/access_level.py": ("docs/MEDYA-ERISIM-MODELI.md",),
	"tradehub_core/media/naming.py": ("docs/MEDYA-DEPOLAMA-STANDARDI.md",),
	"tradehub_core/media/states.py": ("docs/adr/*.md",),
	"tradehub_core/media/trash.py": ("docs/adr/*.md",),
	"tradehub_core/media/archive.py": ("docs/adr/*.md",),
	"tradehub_core/media/metadata.py": ("docs/MEDYA-SEO-SOZLESMESI.md",),
	"tradehub_core/media/pipeline/storage/*.py": ("docs/MEDYA-DEPOLAMA-STANDARDI.md", "docs/adr/*.md"),
	"tradehub_core/media/pipeline/policy/slots/*.json": ("docs/adr/*.md",),
	"tradehub_core/media/pipeline/policy/schema/*.json": ("docs/adr/*.md",),
}

# Her zaman kabul edilen "belge değişti" kanıtı.
ALWAYS_OK: tuple[str, ...] = ("docs/adr/*.md", "docs/closure/*.md")
ESCAPE_TOKEN = "[contract-ok]"


def _git(*args: str) -> str:
	return subprocess.run(["git", *args], check=False, capture_output=True, text=True).stdout


def changed_files(rng: str | None, staged: bool) -> list[str]:
	if staged:
		out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
	else:
		aralik = rng or "HEAD~1"
		out = _git("diff", "--name-only", "--diff-filter=ACMR", *aralik.split())
	return [line.strip() for line in out.splitlines() if line.strip()]


def commit_messages(rng: str | None, staged: bool) -> str:
	"""Kaçış anahtarının aranacağı commit mesajları.

	Çalışma ağacı karşılaştırmasında (`--range HEAD`) HENÜZ commit yoktur —
	`git log HEAD` tüm geçmişi döndürür ve içinde bir kez geçen `[contract-ok]`
	kontrolü sonsuza dek susturur. Ölçüldü: betiğin kendi tanıtım commit'i
	bunu tetikliyordu.
	"""
	if staged or not rng or rng.strip() == "HEAD":
		return ""
	return _git("log", "--format=%s%n%b", rng)


def find_violations(files: list[str]) -> list[tuple[str, tuple[str, ...]]]:
	changed = set(files)

	def any_changed(patterns: tuple[str, ...]) -> bool:
		return any(fnmatch.fnmatch(f, p) for f in changed for p in patterns)

	if any_changed(ALWAYS_OK):
		return []
	ihlaller = []
	for modul, belgeler in GOVERNANCE.items():
		dokunulan = [f for f in changed if fnmatch.fnmatch(f, modul)]
		if dokunulan and not any_changed(belgeler):
			ihlaller.append((", ".join(dokunulan), belgeler))
	return ihlaller


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--range", help="git diff aralığı, ör. origin/version-15...HEAD")
	ap.add_argument("--staged", action="store_true", help="pre-commit: index'teki dosyalar")
	ap.add_argument("--strict", action="store_true", help="ihlalde çıkış kodu 1")
	args = ap.parse_args()

	files = changed_files(args.range, args.staged)
	if not files:
		print("medya sözleşme kontrolü: değişen dosya yok")
		return 0

	if ESCAPE_TOKEN in commit_messages(args.range, args.staged):
		print(f"medya sözleşme kontrolü: {ESCAPE_TOKEN} — bilinçli atlandı")
		return 0

	ihlaller = find_violations(files)
	if not ihlaller:
		print("medya sözleşme kontrolü: temiz")
		return 0

	print("medya sözleşme kontrolü: kod değişti, yöneten belge değişmedi\n")
	for dokunulan, belgeler in ihlaller:
		print(f"  {dokunulan}")
		print(f"    → beklenen: {' | '.join(belgeler)}")
	print(
		"\nBelgeyi güncelle (davranış değiştiyse) ya da commit mesajına "
		f"`{ESCAPE_TOKEN}` yaz (davranış değişmediyse). Gerekçe: ADR-0023."
	)
	return 1 if args.strict else 0


if __name__ == "__main__":
	sys.exit(main())
