"""Medya kuyruğu tanımlı değilse işi `long`'a düşür — iş asla kaybolmasın.

Neden var (2026-10-02, prod): Press bench'inde yalnız `short`, `default`,
`long` worker'ları koşuyor; `common_site_config.json`'da `workers` anahtarı yok.
Frappe v15 `frappe.enqueue(queue="media-image-live")` bu durumda
`ValidationError: Queue should be one of short, default, long` atıyor, kanca
bunu yutup Error Log'a yazıyor ve yüklenen görselin hiç `Media Asset`'i
oluşmuyordu (panel tepsisi %75'te kalıyordu).

Kural: kuyruk sitenin tanımlı kuyruklarındaysa ADI AYNEN döner (yerel docker
ve ayrı worker'lı ortamlarda davranış değişmez); değilse `long` döner. Düşüş
süreç başına bir kez `frappe.logger` ile yazılır — Error Log'u doldurmaz.

Kaynak: Frappe v15 `frappe.utils.background_jobs.get_queues_timeout()`
(`short/default/long` + `workers` anahtarındaki özel kuyruklar). Aynı fonksiyon
`validate_queue`'nun da kaynağı; böylece burada "tanımlı" denen kuyruk
`frappe.enqueue`'nun kabul ettiği kuyrukla birebir aynıdır.
"""

from __future__ import annotations

import frappe

#: Frappe v15'te her sitede hazır, en uzun süre tavanlı yerleşik kuyruk.
FALLBACK_QUEUE: str = "long"
_BUILTIN_QUEUES: frozenset[str] = frozenset({"short", "default", "long"})

#: Süreç başına bir kez loglanan kuyruk adları.
_LOGGED: set[str] = set()


def configured_queues() -> frozenset[str]:
	"""Bu sitede `frappe.enqueue`'nun kabul ettiği kuyruk adları."""
	try:
		from frappe.utils.background_jobs import get_queues_timeout
	except ImportError:
		# v15 dışı bir Frappe: aynı kuralı yapılandırmadan kendimiz kur.
		workers = (frappe.get_conf() or {}).get("workers") or {}
		return _BUILTIN_QUEUES | frozenset(workers)
	return frozenset(get_queues_timeout())


def is_configured(name: str) -> bool:
	"""Kuyruk tanımlı mı. Yapılandırma okunamıyorsa `True` (eski davranış korunur)."""
	try:
		return name in configured_queues()
	except Exception:  # noqa: BLE001 — conf okunamazsa karar veremeyiz; çağıranın kuyruğu kalsın
		return True


def resolve_queue(name: str) -> str:
	"""Tanımlıysa `name`, değilse `long`. Düşüş süreç başına bir kez loglanır."""
	if is_configured(name):
		return name
	if name not in _LOGGED:
		_LOGGED.add(name)
		frappe.logger("media.queue").warning(
			f"Medya kuyruğu '{name}' bu sitede tanımlı değil; işler '{FALLBACK_QUEUE}' kuyruğuna gidiyor."
		)
	return FALLBACK_QUEUE


__all__ = ["FALLBACK_QUEUE", "configured_queues", "is_configured", "resolve_queue"]
