"""Sözleşme imzalarının makinece toplanması — T-031 kabul kriteri 4.

`inspect.signature` çıktısı `signatures.golden.json` ile karşılaştırılır
(`tests/test_contracts.py::SignatureGoldenTest`). Bir `Protocol` metodunun
imzası ya da bir değer nesnesinin alanları sessizce değişirse test kırılır —
"dondurulmuş sözleşme" ifadesinin uygulanabilir hâli budur.

Altın dosyayı BİLEREK değiştirmek için:

    python3 -m tradehub_core.media.pipeline.contracts.signatures --write

Bu komut sözleşmeyi değiştirmez, yalnız yeni hâli kaydeder; değişikliğin
gerekçesi commit mesajında ve `docs/sad/interfaces.md` sürüm notunda durmalıdır.
"""

from __future__ import annotations

import inspect
import json
import os
from typing import Any, Dict

from tradehub_core.media.pipeline.contracts import CORE_PROTOCOLS, delivery, image, policy, storage, video

GOLDEN_PATH: str = os.path.join(os.path.dirname(__file__), "signatures.golden.json")

# Sözleşmenin parçası olan değer nesneleri. Protokol imzaları bunlara atıf
# yaptığı için alanları da dondurulmuş sayılır: `ImageProbe`'a zorunlu bir alan
# eklemek, imzası değişmemiş bir metodu bile kırar.
VALUE_TYPES = (
	storage.ObjectKey,
	storage.ObjectRef,
	storage.ObjectStat,
	storage.PutResult,
	image.ImageProbe,
	image.MasterSpec,
	image.RenditionSpec,
	image.EncodedImage,
	image.QualityReport,
	video.VideoSource,
	video.VideoProbe,
	video.VideoRenditionSpec,
	video.PosterSpec,
	video.PreviewClipSpec,
	video.VideoArtifact,
	policy.Violation,
	policy.Decision,
	policy.EffectiveLimits,
	policy.SlotPolicy,
	delivery.Variant,
	delivery.SourceSet,
	delivery.RenderManifest,
)


def _protokol_imzalari(protokol: Any) -> Dict[str, str]:
	"""Bir `Protocol`'ün genel metot imzaları — alfabetik, kararlı."""
	cikti: Dict[str, str] = {}
	for ad, uye in sorted(vars(protokol).items()):
		if ad.startswith("_") or not callable(uye):
			continue
		cikti[ad] = str(inspect.signature(uye))
	return cikti


def topla() -> Dict[str, Any]:
	"""Tüm sözleşme imzalarını tek sözlükte topla."""
	return {
		"protocols": {p.__name__: _protokol_imzalari(p) for p in CORE_PROTOCOLS},
		"value_types": {t.__name__: str(inspect.signature(t)) for t in VALUE_TYPES},
	}


def oku_golden() -> Dict[str, Any]:
	with open(GOLDEN_PATH, encoding="utf-8") as f:
		return json.load(f)


def yaz_golden() -> str:
	"""Altın dosyayı güncelle ve yolunu döndür."""
	with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
		json.dump(topla(), f, ensure_ascii=False, indent="\t", sort_keys=True)
		f.write("\n")
	return GOLDEN_PATH


if __name__ == "__main__":  # pragma: no cover
	import sys

	if "--write" in sys.argv:
		print(f"yazildi: {yaz_golden()}")
	else:
		print(json.dumps(topla(), ensure_ascii=False, indent="\t", sort_keys=True))
