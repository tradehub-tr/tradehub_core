# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Yeniden deneme politikası — taşıyıcı bazında DEĞİŞTİRİLEBİLİR (TUR-110).

Transport kodu (`adapters/http_client.py`) "nasıl istek atılır"ı bilir; hangi
durumun yeniden denenebilir olduğunu, kaç kez denendiğini ve ne kadar
beklendiğini BİLMEZ. O bilgi taşıyıcıya göre en çok değişen parçadır:
Yurtiçi'nin 409'u "kilit çakıştı, tekrar dene" iken UPS'inki kalıcı bir
sözleşme hatası olabilir.

Bu yüzden politika ayrı bir değerdir (immutable dataclass) ve hem istemci
yapıcısında hem tek çağrı bazında değiştirilebilir:

	policy = replace(RetryPolicy(), retriable_statuses=DEFAULT_RETRIABLE_STATUS_CODES | {409})
	client.request(..., retry_policy=policy)

Varsayılan değerler bugünkü davranışın birebir aynısıdır.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from tradehub_core.logistics.resilience.outcome import Outcome

__all__ = [
	"DEFAULT_RETRIABLE_STATUS_CODES",
	"RetryPolicy",
]

#: Yeniden denenebilir HTTP durumları. 4xx (429 hariç) ASLA denenmez:
#: isteğin kendisi hatalıdır, tekrarı aynı hatayı verir.
DEFAULT_RETRIABLE_STATUS_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
	"""Deneme bütçesi, geri çekilme ve durum sınıflandırması.

	Args:
		retriable_statuses: Yeniden denenebilir HTTP durumları.
		max_attempts: Yeniden denenebilir çağrılar için üst sınır (>=1).
		backoff_base_sec: Üstel geri çekilmenin tabanı.
		backoff_cap_sec: Tek bekleme için tavan.
		retry_after_cap_sec: `Retry-After` başlığına uyulan azami süre; üstünde
			işçi bekletilmez, deneme bırakılır.
	"""

	retriable_statuses: frozenset[int] = field(default=DEFAULT_RETRIABLE_STATUS_CODES)
	max_attempts: int = 3
	backoff_base_sec: float = 0.5
	backoff_cap_sec: float = 8.0
	retry_after_cap_sec: float = 60.0

	def __post_init__(self) -> None:
		# frozen dataclass — normalizasyon için tek yol object.__setattr__.
		object.__setattr__(self, "retriable_statuses", frozenset(self.retriable_statuses))
		object.__setattr__(self, "max_attempts", max(1, int(self.max_attempts)))

	# -------------------------------------------------------------------
	# Sınıflandırma
	# -------------------------------------------------------------------

	def classify_status(self, status: int) -> Outcome:
		"""HTTP durumunu dayanıklılık sonucuna çevirir (varsayılan sınıflandırma).

		2xx/3xx → HEALTHY, yeniden denenebilir küme → UNAVAILABLE, kalan her şey
		→ NEUTRAL (istek karşıya ulaştı ve reddedildi; hata bizde).
		"""
		if status in self.retriable_statuses:
			return Outcome.UNAVAILABLE
		if 200 <= status < 400:
			return Outcome.HEALTHY
		return Outcome.NEUTRAL

	def is_retriable(self, outcome: Outcome) -> bool:
		"""Yalnız "karşı taraf ayakta değil" sonucu yeniden denenir."""
		return outcome is Outcome.UNAVAILABLE

	# -------------------------------------------------------------------
	# Bütçe ve bekleme
	# -------------------------------------------------------------------

	def attempt_budget(self, *, idempotent: bool) -> int:
		"""Kaç deneme yapılabileceğini belirler.

		ÇİFT GÖNDERİ TUZAĞI: `create_shipment`/`cancel` gibi yan etkili
		çağrılarda zaman aşımı, isteğin karşı tarafta İŞLENMEDİĞİ anlamına
		gelmez. Körlemesine tekrar, firmada ikinci bir gönderi (ve ikinci fatura)
		açar. Bu yüzden yeniden deneme yalnızca çağıran güvenli olduğunu
		söylerse yapılır.
		"""
		return self.max_attempts if idempotent else 1

	def delay_before_retry(self, attempt_no: int, retry_after: float | None) -> float | None:
		"""Bir sonraki denemeden önce beklenecek süre; beklemek anlamsızsa None.

		`Retry-After`'a uyulur ama sınırsız değil: kötü yapılandırılmış bir firma
		"3600" derse işçi bir saat uyumamalı.
		"""
		if retry_after is not None:
			return None if retry_after > self.retry_after_cap_sec else retry_after

		# Tam jitter (AWS "Exponential Backoff and Jitter"): eşzamanlı işçiler
		# aynı anda yeniden denerse firmayı ikinci kez yere serer.
		ceiling = min(self.backoff_cap_sec, self.backoff_base_sec * (2 ** (attempt_no - 1)))
		return random.uniform(0.0, ceiling)
