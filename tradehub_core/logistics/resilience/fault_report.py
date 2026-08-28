# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Yutulan arızaların KISILMIŞ raporlanması — tek desen, tek kopya.

NEDEN AYRI MODÜL:
	Desen `circuit_breaker._report_fault` içinde doğdu ve gerekçesi orada
	yazılıydı: "Redis çöktüğünde saniyede yüzlerce çağrı gelir; her birine
	`Error Log` satırı yazmak arızayı teşhis edilemez hale getirir." Kardeş
	yol (`http_client._report_log_failure`) aynı sınıf arızayı raporluyordu ama
	deseni DEVRALMAMIŞTI — ve etkisi orada KATLANIYORDU: devre AÇIKKEN
	`_enter_circuit` → `claim_open_notice()` → `_log` düşer →
	`_report_log_failure` → `release_open_notice()` anahtarı SİLER → sonraki
	istek yeniden claim eder → yine yazar. Kalıcı bir log arızasında cooldown
	başına tek satır yerine İSTEK BAŞINA satır oluşuyordu.

	Deseni kopyalamak yerine paylaşmak, `log.py::safe_log_error` ile aynı
	gerekçedir: kopyalanan bir güvenlik/gözlemlenebilirlik deseninde biri
	düzeltilip diğeri unutulur.

FRAPPE BAĞIMLILIĞI VAR (bilinçli): bu katman kalıcı `Error Log` satırı yazar,
yani zaten Frappe'ye bağlıdır. Raporlama yolunun KENDİSİ patlarsa çağrı
düşmez — bu fonksiyon her zaman bir hata yolunda koşar.

KISMA TABLOSU SÜREÇ-İÇİDİR: arızanın kaynağı çoğu zaman Redis'in kendisidir,
kısmayı orada saymak aynı arızaya bağımlı olurdu.
"""

from __future__ import annotations

import time

import frappe

__all__ = ["FAULT_WARN_WINDOW_SEC", "report_throttled", "reset_throttle", "should_report"]

#: Aynı arıza kapsamı için iki uyarı arasındaki asgari süre (saniye).
FAULT_WARN_WINDOW_SEC: float = 60.0

#: {kapsam: son uyarı zamanı} — süreç belleği.
_LAST_WARNING: dict[str, float] = {}

#: {kapsam: (pencere başlangıcı, sayaç)} — `should_report` için.
_WINDOWS: dict[str, tuple[float, int]] = {}


def report_throttled(scope: str, message: str, title: str) -> None:
	"""Yutulan bir arızayı kısılmış biçimde raporlar.

	İlk görülüşte kalıcı `Error Log` satırı, sonraki tekrarlarda
	`FAULT_WARN_WINDOW_SEC`'te bir `logistics` logger'ına uyarı.

	PENCERE "SON RAPOR"DAN ÖLÇÜLÜR, "SON OLAY"DAN DEĞİL. Zaman damgası eskiden
	HER çağrıda tazeleniyordu; sonuç, docstring'in vaadinin TERSİYDİ (ölçüldü,
	konteyner):

		200 sn kesintisiz arıza, sn'de 1 (Redis çökmüş) → TOPLAM 1 rapor
		90 sn arayla 5 seyrek arıza                     → TOPLAM 5 rapor

	Yani arıza SÜRDÜĞÜ sürece sessiz, SEYREK olunca gürültülüydü. Kesintisiz bir
	Redis çöküşünde ilk saniyeden sonra hiçbir yere hiçbir şey yazılmıyordu.
	Damga artık YALNIZ rapor yazıldığında güncellenir; kardeş yüklem
	`should_report` pencereyi zaten böyle kuruyordu.

	Damga yazma DENEMESİNDEN ÖNCE konur: `frappe.log_error` kalıcı olarak
	patlıyorsa (DB yazma katmanı çökmüş) her çağrı yeniden denemeye girip
	fırtına üretirdi — bu fonksiyonun engellemek için var olduğu şeyin ta kendisi.

	Args:
		scope: Kısma anahtarı — aynı arıza sınıfını temsil etmeli
			(ör. `carrier_code + ":" + operation`). Çok dar bir kapsam
			(ör. istek kimliği) kısmayı ETKİSİZ kılar.
		message: Rapor metni.
		title: `Error Log` başlığı.
	"""
	now = time.monotonic()
	previous = _LAST_WARNING.get(scope)
	if previous is not None and now - previous < FAULT_WARN_WINDOW_SEC:
		return
	_LAST_WARNING[scope] = now
	try:
		if previous is None:
			frappe.log_error(message, title)
		else:
			frappe.logger("logistics").warning(message)
	except Exception:  # noqa: BLE001 — raporlama yolu çağrıyı düşüremez
		# Frappe bağlamı yok ya da `Error Log` yazılamıyor: bu fonksiyon zaten
		# bir hata yolunda koşuyor, buradan çıkış yok.
		pass


def should_report(scope: str, limit: int) -> bool:
	"""Aynı cooldown penceresinde `limit` kez sonra False döner.

	`report_throttled`'dan FARKI: bu yüklem raporlamaz, KARAR verir. Bir
	arızanın yalnız RAPORU değil, tetiklediği yan etkisi de (ör. devre kesici
	"açık bildirimi" anahtarının geri verilmesi) kısılmak istendiğinde kullanılır.

	Args:
		scope: Kısma anahtarı.
		limit: Pencere başına izin verilen tekrar sayısı.

	Returns:
		Yan etki uygulanmalı mı.
	"""
	now = time.monotonic()
	first, count = _WINDOWS.get(scope, (now, 0))
	if now - first >= FAULT_WARN_WINDOW_SEC:
		first, count = now, 0
	_WINDOWS[scope] = (first, count + 1)
	return count < limit


def reset_throttle() -> None:
	"""Kısma durumunu sıfırlar. **YALNIZ TESTLER** — süreç ömrü boyunca kalıcıdır."""
	_LAST_WARNING.clear()
	_WINDOWS.clear()
