# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Kargo firması adapter katmanı.

`CarrierCircuitBreaker`, `CircuitState` ve `Outcome` BURADAN YAYINLANMAZ: içerik
taşıyıcıdan tamamen bağımsız genel bir dayanıklılık primitifi ve tek kanonik
yolu `tradehub_core.logistics.resilience`. Bu paket bir süre "eski yol
kırılmasın" diye onları yeniden dışa veriyordu; oysa o yolu kullanan HİÇBİR kod
yoktu (`adapters/circuit_breaker.py` hiç yayınlanmamıştı) ve aynı üç adın iki
public yolu olması "hangisi kanonik" sorusunu belirsiz bırakıyordu.
"""
