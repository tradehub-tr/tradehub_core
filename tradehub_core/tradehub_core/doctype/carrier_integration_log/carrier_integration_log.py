# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Carrier Integration Log — taşıyıcı API trafiğinin salt-okunur günlüğü (09-BE A).

Şema `logistics/contract.py::INTEGRATION_LOG_FIELDS` ile bağlıdır.

KARAR — `created_at` alanı AÇILMADI:
	Sözleşme `created_at (Datetime, required)` diyor; Frappe her tabloya zaten
	indeksli bir `creation` sütunu koyuyor. İkinci bir zaman damgası tutmak iki
	sorun üretirdi: (a) hangisinin doğru olduğu belirsizleşir — kayıt kuyrukta
	beklerse ikisi sapar, (b) saklama işi hangi sütunu tarayacağına karar
	vermek zorunda kalır ve yanlış seçim eski kayıtları hiç silmez. Bu yüzden
	`created_at` sözleşme düzeyinde `creation`'a EŞLENİR; okuma yüzeyi
	(rapor/endpoint) alanı `creation` üzerinden sunar. Sözleşme dosyasına
	dokunulmadı çünkü `integration_log` hâlâ `PROVISIONAL_ENTITIES` içinde ve
	üreteç bu varlık için DocType'a bakmıyor — bir sapma raporlanmıyor. Varlık
	provisional'dan çıkarılırken bu eşleme `contract.py`'ye yazılmalı.

APPEND-ONLY:
	Hiçbir role `create`/`write` DocPerm'i verilmedi ve DocType `in_create`
	işaretli — kayıt yalnız `logistics/integration/log.py` üzerinden
	(`ignore_permissions=True`) oluşur. `validate` bunu bir kez daha kapatır ki
	`frappe.get_doc(...).save()` çağıran yeni bir kod yolu sessizce geçmesin.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.logistics.integration.log import (
	CONTROLLER_MASKED_FIELDS,
	safe_log_error,
	traceback_text,
)
from tradehub_core.logistics.integration.masking import MASK, mask_payload


class CarrierIntegrationLog(Document):
	def before_insert(self) -> None:
		"""Derinlemesine savunma: maskelenen alanları bir kez daha maskeden geçir.

		`write_integration_log` zaten maskeliyor. Bu ikinci geçiş, DocType'a
		yazıcıyı ATLAYARAK gelen bir kod yolu (test fixture'ı, veri taşıma
		script'i, ileride eklenecek bir webhook alıcısı) için ağdır. Maskeleme
		idempotenttir — `***` tekrar maskelendiğinde `***` kalır — bu yüzden
		iki kez uygulanması veriyi bozmaz.

		ALAN LİSTESİ TEK KAYNAKTAN: `integration/log.py::CONTROLLER_MASKED_FIELDS`
		(sözleşme demeti `MASKED_LOG_FIELDS`'ten TÜRETİLİR, elle kopyalanmaz).
		Liste burada elle kopyalanıyordu ve iki katman aynı kör noktayı
		paylaşıyordu — `error_message` ikisinde de yoktu, `error_code` ise
		yalnız yazıcı yolunda maskeleniyordu.

		NEDEN TRY/EXCEPT — ölçülmüş çökme yüzeyi:
			Döngü `mask_payload`'ı korumasız çağırıyordu. Derin bir gövde
			`RecursionError` fırlattığında (3 KB'lık iç içe JSON yetiyordu)
			derinlemesine-savunma katmanının kendisi INSERT'İ DÜŞÜREN bir çökme
			yüzeyine dönüşüyordu — yazıcıyı atlayan yolda log satırı tamamen
			kayboluyordu. Artık alan başına yakalanır ve FAIL-CLOSED davranılır:
			maskeleme patlarsa alan `***` olur. Ham değeri bırakmak da, insert'i
			düşürmek de yasak.
		"""
		for fieldname in CONTROLLER_MASKED_FIELDS:
			value = self.get(fieldname)
			if not value:
				continue
			try:
				masked = mask_payload(value)
				self.set(fieldname, masked if isinstance(masked, str) else str(masked))
			except Exception:  # noqa: BLE001 — savunma katmanı çökme yüzeyi OLAMAZ
				# FAIL-CLOSED: ham değer ASLA sütuna yazılmaz.
				self.set(fieldname, MASK)
				safe_log_error(
					f"{fieldname} maskelenemedi, alan fail-closed olarak `{MASK}` yazıldı.\n"
					f"{traceback_text()}",
					"logistics.integration.before_insert_masking",
				)

	def validate(self) -> None:
		# super().validate() yok — Frappe v15 Document sınıfı validate tanımlamaz
		# (shipment_event / carrier_account emsali).
		if not self.is_new():
			frappe.throw(_("Entegrasyon logu kayıtları append-only'dir; güncellenemez."))
