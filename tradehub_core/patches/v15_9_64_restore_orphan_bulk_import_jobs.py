"""Silinmiş Bulk Import Job başlıklarını ilanlardan geri yaz (MOGEM-981).

Mantık `bulk_import/repair.py`'de; özet Error Log'a düşer ki her ortamda "kaç job onarıldı,
kaç ilanın kilidi açıldı, hangisi atlandı" deploy sonrası okunabilsin. İdempotent.
"""

import json

import frappe

from tradehub_core.bulk_import.repair import restore_orphan_jobs


def execute() -> None:
	result = restore_orphan_jobs()
	if result["onarildi"] or result["atlandi"]:
		frappe.log_error(title="MOGEM-981 onarım özeti", message=json.dumps(result, ensure_ascii=False))
	print(f"MOGEM-981 onarım: {result}")
