# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Region DocType controller.

Bir bölgeyi (TR, EU, MENA, CIS ülkeleri, GLOBAL) ve onun yargı/dil/para
varsayılanlarını tutar. Faz 1.2'de Subscription Plan ve Listing.allowed_regions
tarafından referans verilir.

Detay: docs/yetki/03-doctype-sablonlari.md §5
"""

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document

# ISO 3166-1 alpha-2 ülke kodu regex (iki büyük harf)
_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")


class Region(Document):
	def validate(self) -> None:
		self._normalize_region_code()
		self._validate_countries()
		self._validate_pii_policy()

	def _normalize_region_code(self) -> None:
		"""region_code uppercase, alfanumerik."""
		if not self.region_code:
			return
		code = self.region_code.strip().upper()
		if not re.match(r"^[A-Z0-9_]+$", code):
			frappe.throw(
				_("Region Code yalnızca büyük harf, rakam ve alt çizgi içerebilir (örn. TR, EU, MENA).")
			)
		self.region_code = code

	def _validate_countries(self) -> None:
		"""countries field'ı virgülle ayrılmış ISO ülke kodları olmalı."""
		if not self.countries:
			return
		raw = self.countries.strip()
		codes = [c.strip().upper() for c in raw.split(",") if c.strip()]
		invalid = [c for c in codes if not _COUNTRY_CODE_RE.match(c)]
		if invalid:
			frappe.throw(
				_(
					"Geçersiz ülke kodu/kodları: {0}. ISO 3166-1 alpha-2 formatı kullanın (örn. TR, DE, SA)."
				).format(", ".join(invalid))
			)
		# Normalize edilmiş halde yaz
		self.countries = ",".join(codes)

	def _validate_pii_policy(self) -> None:
		"""pii_masking_policy geçerli JSON olmalı."""
		if not self.pii_masking_policy:
			return
		if isinstance(self.pii_masking_policy, str):
			try:
				json.loads(self.pii_masking_policy)
			except json.JSONDecodeError as e:
				frappe.throw(_("PII Masking Policy geçerli JSON değil: {0}").format(str(e)))

	def get_country_list(self) -> list[str]:
		"""Bu bölgenin ülke kodları listesi."""
		if not self.countries:
			return []
		return [c.strip() for c in self.countries.split(",") if c.strip()]

	def get_pii_policy_dict(self) -> dict:
		"""PII policy JSON'ı dict olarak döner."""
		if not self.pii_masking_policy:
			return {}
		if isinstance(self.pii_masking_policy, dict):
			return self.pii_masking_policy
		try:
			return json.loads(self.pii_masking_policy)
		except (json.JSONDecodeError, TypeError):
			return {}
