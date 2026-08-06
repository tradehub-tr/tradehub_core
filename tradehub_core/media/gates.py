"""Optimizasyon kapıları — saf fonksiyonlar, `import frappe` YOKTUR.

Yedek tutulsa da (arşiv) her kapı zorunludur: biri bile başarısızsa dosyaya
dokunulmaz ve `skipped` sayılır. Kapı listesi ve gerekçeleri
`GORSEL-OPTIMIZASYON.md` §8'de.

Kapı 4 (`already_small`) bu işin kalbidir: en uzun kenarı `max_dim`'i AŞMAYAN
dosya hiç işlenmez. 4.007 dosyanın yalnız ~300'ü bu kapıyı geçer; kalan 3.700
dosya bit düzeyinde aynı kalır, dolayısıyla onlarda kalite kaybı riski sıfırdır.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradehub_core.media.engine import SUPPORTED_FORMATS, Probe


@dataclass(frozen=True)
class GateResult:
	"""`passed=False` ise `reason` skip sebebidir (UI'da sayaç olarak gösterilir)."""

	passed: bool
	reason: str = ""


# UI'ın gösterdiği skip sebepleri — frontend i18n anahtarları bunlarla eşleşir.
SKIP_REASONS: tuple[str, ...] = (
	"too_small",
	"unsupported_format",
	"animated",
	"already_small",
	"already_optimized",
	"gain_below_threshold",
	"decode_failed",
	# Kapı değil, `runner` tarafından üretilir: `File` kaydı var ama dosya diskte
	# yok. DB yedeği ile dosya yedeği farklı anlara aitse doğal olarak oluşur.
	"file_missing",
)


def check_before(
	*,
	file_size: int,
	probe: Probe,
	optimized_at: str | None,
	max_dim: int,
	min_file_size: int,
) -> GateResult:
	"""Dosya okunduktan sonra, optimize edilmeden ÖNCE çalışan kapılar (1-5)."""
	# Kapı 5 en başta: bir kez işlenmiş dosya artık küçük ya da düşük çözünürlüklü
	# olabilir; sonraki kapılara takılırsa rapor "çok küçük" der ve "bu dosyaya
	# neden dokunulmadı" sorusunu yanlış cevaplar. Nesil kaybı koruması olarak
	# işlevi her sırada aynı, fark yalnız raporun doğruluğunda.
	if optimized_at:
		return GateResult(False, "already_optimized")

	if not file_size or file_size < min_file_size:
		return GateResult(False, "too_small")

	if not probe.readable:
		return GateResult(False, "decode_failed")

	if probe.fmt not in SUPPORTED_FORMATS:
		return GateResult(False, "unsupported_format")

	if probe.animated:
		return GateResult(False, "animated")

	# Kapı 4 — hedefli yaklaşımın tek uygulama noktası.
	if probe.max_dim <= max_dim:
		return GateResult(False, "already_small")

	return GateResult(True)


def check_after(*, original_size: int, new_size: int, min_saving_ratio: float) -> GateResult:
	"""Optimize edildikten SONRA çalışan kapı (6) — kazanç eşiği."""
	if not new_size:
		return GateResult(False, "decode_failed")

	if new_size >= original_size * (1 - min_saving_ratio):
		return GateResult(False, "gain_below_threshold")

	return GateResult(True)
