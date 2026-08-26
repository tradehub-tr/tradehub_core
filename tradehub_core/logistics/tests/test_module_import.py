# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""TUR-102: Lojistik modul import smoke testi.

Logistics alt-modulunun doğru yuklendigini ve public API'nin
erisilebilir oldugunu dogrular. Frappe runtime gerektirmez.
"""

from __future__ import annotations

import unittest


class TestLogisticsModuleImport(unittest.TestCase):
	"""Lojistik paket ve alt-modul import kontrolleri."""

	def test_logistics_package_importable(self) -> None:
		"""tradehub_core.logistics paketi import edilebilmeli."""
		import tradehub_core.logistics  # noqa: F401

	def test_is_enabled_importable(self) -> None:
		"""is_enabled fonksiyonu import edilebilmeli ve callable olmali."""
		from tradehub_core.logistics import is_enabled

		self.assertTrue(callable(is_enabled))

	def test_constants_importable(self) -> None:
		"""Sabit degerler modulu import edilebilmeli."""
		from tradehub_core.logistics.constants import (  # noqa: F401
			ALLOWED_TRANSITIONS,
			LOGISTICS_FEATURE_FLAGS,
			SHIPMENT_NAMING_SERIES,
			TERMINAL_STATUSES,
			ShipmentStatus,
		)

	def test_exceptions_importable(self) -> None:
		"""Exception siniflari import edilebilmeli."""
		from tradehub_core.logistics.exceptions import (  # noqa: F401
			CarrierAPIError,
			CarrierCapabilityError,
			CarrierTimeoutError,
			IdempotencyConflictError,
			LogisticsError,
			ShipmentStateError,
			SplitInvariantError,
			TrackingNotFoundError,
		)

	def test_adapter_base_importable(self) -> None:
		"""Adapter taban sinifi ve CarrierCapability import edilebilmeli."""
		from tradehub_core.logistics.adapters.base import (  # noqa: F401
			BaseCarrierAdapter,
			CarrierCapability,
		)

	def test_adapter_registry_importable(self) -> None:
		"""Adapter registry fonksiyonlari import edilebilmeli."""
		from tradehub_core.logistics.adapters.registry import (  # noqa: F401
			get_adapter,
			list_registered_carriers,
			register_carrier,
		)

	def test_mock_carrier_importable(self) -> None:
		"""MockCarrierAdapter import edilebilmeli."""
		from tradehub_core.logistics.adapters.carriers.mock_carrier import (  # noqa: F401
			MockCarrierAdapter,
		)

	def test_masking_importable(self) -> None:
		"""Maskeleme saf modulu Frappe olmadan da import edilebilmeli."""
		from tradehub_core.logistics.integration.masking import (  # noqa: F401
			MASK,
			build_secret_variants,
			is_sensitive_key,
			mask_headers,
			mask_payload,
			redact_text,
		)

	def test_integration_log_importable(self) -> None:
		"""Log yazicisi ve tip sozlesmesi import edilebilmeli."""
		from tradehub_core.logistics.integration.log import (  # noqa: F401
			MASKED_LOG_FIELDS,
			IntegrationLogWriter,
			write_integration_log,
		)

	def test_secret_collection_importable(self) -> None:
		"""Sir toplayicisi paylasilan modulden gelmeli — kopya dogmasin."""
		from tradehub_core.logistics.constants import CREDENTIAL_SECRET_FIELDS  # noqa: F401
		from tradehub_core.logistics.integration.secrets import (  # noqa: F401
			collect_secret_values,
			is_password_placeholder,
		)

	def test_integration_log_retention_importable(self) -> None:
		"""Saklama job'i import edilebilmeli."""
		from tradehub_core.logistics.jobs.integration_log_retention import (  # noqa: F401
			purge_expired_integration_logs,
			run_scheduled,
		)

	def test_integration_log_choices_are_single_sourced(self) -> None:
		"""Select kumeleri constants'tan gelmeli — dort ayri kopya kalmadi."""
		from tradehub_core.logistics.constants import (
			INTEGRATION_LOG_DIRECTIONS,
			INTEGRATION_LOG_OPERATIONS,
		)
		from tradehub_core.logistics.integration.log import VALID_DIRECTIONS, VALID_OPERATIONS

		self.assertIs(VALID_OPERATIONS, INTEGRATION_LOG_OPERATIONS)
		self.assertIs(VALID_DIRECTIONS, INTEGRATION_LOG_DIRECTIONS)


if __name__ == "__main__":
	unittest.main()
