# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Çağrı sonucunun DAYANIKLILIK anlamı — HTTP durum kodundan bağımsız (TUR-110).

Devre kesicinin sorduğu soru "istek başarılı mıydı" DEĞİL, "karşı taraf ayakta
mı"dır. Bu ikisi aynı şey değil ve karıştırıldığında devre kesici işlevsizleşir:

* **HEALTHY** — taşıyıcı yanıt verdi ve yanıt bizim beklediğimizdi. Sayaç sıfırlanır.
* **UNAVAILABLE** — taşıyıcı erişilemedi ya da kendi hatasını bildirdi (5xx, timeout,
  bağlantı reddi, SOAP zarfında "sistem bakımda"). Sayaç ARTAR.
* **NEUTRAL** — istek karşıya ULAŞTI ve reddedildi; hata BİZDE (400/404, geçersiz
  alan, bulunamayan takip numarası). Sayaç ne artar NE DE sıfırlanır.

NEUTRAL'ın var olma sebebi ölçülmüş bir arıza: kalıcı 4xx'i "başarı" sayan bir
devre kesici, karışık trafikte (bir kuyruk 400 üreten hatalı payload, diğeri 503
alan gerçek çöküş) devreyi HİÇ açmaz — 400'ler sayacı sürekli sıfırlar.
"""

from __future__ import annotations

import enum

__all__ = ["Outcome"]


class Outcome(enum.Enum):
	"""Bir çağrının devre kesici açısından anlamı."""

	HEALTHY = "healthy"
	UNAVAILABLE = "unavailable"
	NEUTRAL = "neutral"
