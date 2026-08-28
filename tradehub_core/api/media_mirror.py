"""Medya aynasının RQ worker ve salt-okunur yönetim yüzeyi.

İş mantığı ``media.mirror_runtime`` içindedir. Bu modül yalnız
``StorageSettings.DEFAULT_MIRROR_METHOD`` sözleşmesindeki yolu karşılar.
Fonksiyon bilerek ``frappe.whitelist`` edilmez; HTTP ucu değildir.
"""

import frappe

from tradehub_core.media import mirror_runtime

run_mirror_task = mirror_runtime.run_mirror_task


@frappe.whitelist()
def get_mirror_status(file_url: str = "") -> dict:
	"""Media Superadmin için tek nesnenin ayna durumunu döndür; bayt/sır yok."""
	from tradehub_core.tradehub_core.doctype.media_storage_settings.media_storage_settings import (
		_require_superadmin,
	)

	_require_superadmin("read")
	return mirror_runtime.mirror_status(file_url)

__all__ = ["run_mirror_task", "get_mirror_status"]
