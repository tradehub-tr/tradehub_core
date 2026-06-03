"""Sprint 5 Faz 3 son düzeltme — non-privileged role'lerin permlevel 2 read'ini sıfırla.

Sorun:
  v15_6_7'den sonra DocType migration side-effect olarak "Seller" ve
  "Marketplace Seller" gibi non-privileged role'lere Custom DocPerm
  permlevel=2 read=1, write=1 satırları eklendi. Bu sub-user'ların PII
  field'ları görmesini engellemez.

Çözüm:
  Privileged role listesinde olmayan tüm role'lerin permlevel 2 read/write
  izinlerini 0'a çek. Custom DocPerm satırı silinmez — sadece read=0/write=0
  set edilir (Frappe Desk başka bir kontrole düşmesin).

İdempotent.
"""

from __future__ import annotations


def execute() -> dict:
	from tradehub_core.setup.pii_permlevel_setup import (
		revoke_non_privileged_permlevel_reads,
	)

	return revoke_non_privileged_permlevel_reads(target_permlevel=2)
