"""Medya testleri — git'e girmeyen GERÇEK ÇEKİM fixture'ları.

`tests/fixtures/.gitignore` kararı (2026-08-20): 6 gerçek çekim (NTSC video, AdobeRGB PNG, Canon
TIFF…) betiklerle üretilemiyor ve bilerek versiyonlanmıyor; taze checkout'ta bunları isteyen
testler ATLANIR. Karar yazılmış ama hiçbir teste uygulanmamıştı — dosya yokken testler "boş
dosya" / FileNotFoundError ile KIRMIZI düşüyordu (MOGEM-685, 29 Eyl 2026: 5 modül).

Atlama `subTest` içinde `skipTest` ile yapılır: sonuçta "skipped" olarak GÖRÜNÜR, sessizce
kaybolmaz. Dosyalar gerekiyorsa manifest.json'daki köken adreslerinden getirilir.
"""

from __future__ import annotations

import unittest
from pathlib import Path

GERCEK_CEKIM_ONEKLERI = ("real_", "video_real_")


def gercek_cekim_mi(yol: str | Path) -> bool:
	return Path(yol).name.startswith(GERCEK_CEKIM_ONEKLERI)


def eksik_gercek_cekim(yol: str | Path) -> bool:
	return gercek_cekim_mi(yol) and not Path(yol).exists()


def eksikse_atla(test: unittest.TestCase, yol: str | Path) -> None:
	if eksik_gercek_cekim(yol):
		test.skipTest(f"{Path(yol).name}: gerçek çekim, git'te yok (tests/fixtures/.gitignore)")
