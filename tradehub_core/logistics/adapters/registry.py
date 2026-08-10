# Copyright (c) 2024, Istoc.com and contributors
# For license information, please see license.txt

"""Carrier adapter registry — yeni tasiyici ekleme plug-and-play."""

from __future__ import annotations

from typing import Any, Optional

from frappe import _

from tradehub_core.logistics.adapters.base import BaseCarrierAdapter
from tradehub_core.logistics.exceptions import CarrierNotFoundError


_CARRIER_REGISTRY: dict[str, type[BaseCarrierAdapter]] = {}


def register_carrier(
	carrier_code: str,
	adapter_class: type[BaseCarrierAdapter],
) -> None:
	"""Yeni bir kargo adapter sinifini registry'ye kaydet.

	Idempotent: ayni carrier_code ile AYNI sinif tekrar kaydedilirse sessiz
	no-op (cift import senaryosu); ayni kodla FARKLI sinif gelirse hata.

	Args:
		carrier_code: Benzersiz kargo firma kodu (orn. "yurtici", "aras").
		adapter_class: BaseCarrierAdapter'dan turetilmis adapter sinifi.

	Raises:
		TypeError: adapter_class, BaseCarrierAdapter'dan turetilmemisse.
		ValueError: carrier_code farkli bir sinifla zaten kayitliysa.
	"""
	if not isinstance(carrier_code, str) or not carrier_code.strip():
		raise ValueError(_("carrier_code bos olamaz."))

	carrier_code = carrier_code.strip().lower()

	if not (isinstance(adapter_class, type) and issubclass(adapter_class, BaseCarrierAdapter)):
		raise TypeError(
			_("{0} sinifi BaseCarrierAdapter'dan turetilmelidir.").format(
				getattr(adapter_class, "__name__", adapter_class)
			)
		)

	existing: type[BaseCarrierAdapter] | None = _CARRIER_REGISTRY.get(carrier_code)
	if existing is not None:
		if existing is adapter_class:
			return  # Idempotent no-op — ayni sinif tekrar kaydediliyor (cift import)
		raise ValueError(
			_("{0} kargo kodu farkli bir sinifla ({1}) zaten kayitli.").format(
				carrier_code, existing.__name__
			)
		)

	_CARRIER_REGISTRY[carrier_code] = adapter_class


def get_adapter(
	carrier_code: str,
	credential_doc: Optional[dict[str, Any]] = None,
	environment: str = "production",
) -> BaseCarrierAdapter:
	"""Kayitli bir adapter'in yeni bir instance'ini dondur.

	Args:
		carrier_code: Kargo firma kodu.
		credential_doc: Kimlik bilgileri dokumani.
		environment: Ortam ("production" veya "sandbox").

	Returns:
		BaseCarrierAdapter instance.

	Raises:
		CarrierNotFoundError: carrier_code kayitli degilse (HTTP 404).
	"""
	carrier_code = carrier_code.strip().lower()

	if carrier_code not in _CARRIER_REGISTRY:
		raise CarrierNotFoundError(
			_("{0} kargo kodu kayitli degil. Kayitli kodlar: {1}").format(
				carrier_code,
				", ".join(sorted(_CARRIER_REGISTRY.keys())) or "-",
			)
		)

	adapter_class: type[BaseCarrierAdapter] = _CARRIER_REGISTRY[carrier_code]
	return adapter_class(credential_doc=credential_doc, environment=environment)


def list_registered_carriers() -> list[dict[str, Any]]:
	"""Tum kayitli kargo firmalarinin bilgilerini dondur.

	Returns:
		Her biri carrier_code, name, display_name ve capabilities iceren dict listesi.
	"""
	result: list[dict[str, Any]] = []
	for code, adapter_class in sorted(_CARRIER_REGISTRY.items()):
		result.append({
			"carrier_code": code,
			"name": getattr(adapter_class, "name", code),
			"display_name": getattr(adapter_class, "display_name", code),
			"capabilities": [
				cap.value for cap in getattr(adapter_class, "capabilities", set())
			],
		})
	return result


def is_carrier_registered(carrier_code: str) -> bool:
	"""Belirtilen kargo kodunun kayitli olup olmadigini kontrol et.

	Args:
		carrier_code: Kargo firma kodu.

	Returns:
		True ise kayitli, False ise degil.
	"""
	return carrier_code.strip().lower() in _CARRIER_REGISTRY
