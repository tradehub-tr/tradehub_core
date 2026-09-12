# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Aylık medya tüketim sayacı (MOGEM-620 §18).

Şartname §18: "Tenant bazında storage/bandwidth/AI/transformations quota …
ayrı tutulmalı." 10 Eylül 2026 denetimi: yalnız STORAGE vardı
(`quota.max_storage_mb` + `files.enforce_storage_quota`); diğer üçünün ne
kotası ne sayacı vardı.

NEDEN DEPOLAMADAN FARKLI MODEL
------------------------------
Depolama bir DURUM: "şu an kaç bayt tutuyorsun" sorusu `tabFile` üzerinde
`SUM(file_size)` ile her seferinde YENİDEN hesaplanabiliyor
(`files.storage_usage`). Diğer üçü AKIŞ: "bu ay kaç bayt servis ettin",
"kaç türev ürettin", "kaç AI çağrısı yaptın". Akış geçmişe dönük
hesaplanamaz — olay anında sayılmazsa kaybolur.

Bu yüzden burada satır başına (mağaza, dönem, ölçüm) üçlüsü ve artan bir
sayaç var. Ayrı bir `Media Usage Event` tablosu (olay başına satır)
düşünüldü ve reddedildi: bant genişliği her dosya isteğinde artıyor, günde
yüz binlerce satır demekti; kotanın ihtiyacı olan tek şey TOPLAM.

DÖNEM ANAHTARI
--------------
`YYYY-MM`. Aylık, çünkü abonelik döngüsü aylık ve kota da öyle tanımlı.
Eski dönemlerin satırları SİLİNMİYOR: fatura itirazında "geçen ay ne
tükettim" sorusunun tek cevabı onlar.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

METRICS: tuple[str, ...] = ("bandwidth_bytes", "transformations", "ai_calls")


class MediaUsageMeter(Document):
	def validate(self) -> None:
		# Frappe v15'te `Document.validate` YOK; repo deseni bu korumalı çağrı
		# (bkz. `media_asset.py`) — taban sınıf ileride kazanırsa zincir kırılmasın.
		if hasattr(super(), "validate"):
			super().validate()
		if self.metric not in METRICS:
			frappe.throw(_("Geçersiz ölçüm: {0}").format(self.metric))
		if self.amount is None or float(self.amount) < 0:
			# Negatif tüketim yoktur; olsaydı kotayı geri kazanmanın yolu
			# olurdu ve bu tam olarak istismar edilecek şey.
			frappe.throw(_("Tüketim negatif olamaz."))
