# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-043 (09-BE A): Carrier Integration Log index'leri + saklama ayarı.

DocType'ın KENDİSİ patch işi değil — `carrier_integration_log.json` migrate
sırasında Frappe tarafından kurulur. Patch'in iki işi var:

1. **Bileşik index'ler.** DocType JSON'u yalnız tek kolon index'i (`search_index`)
   ifade edebiliyor; log listesinin gerçek sorguları iki-üç kolonlu
   (taşıyıcı + başarı + tarih) ve saklama işi tek başına `creation` tarıyor.
   Bunlar ancak `ALTER TABLE` ile kurulur.
2. **Singleton varsayılanı.** `Logistics Settings` `issingle` olduğu için
   JSON'daki `default` YALNIZ yeni kurulumda değil, hiçbir zaman mevcut
   `tabSingles` satırına yazılmaz — mevcut sitede alan boş kalırdı ve saklama
   işi 90 günlük varsayılana düşerdi (doğru davranış ama ayar ekranında boş
   görünürdü). Değeri açıkça yazıyoruz.

İDEMPOTENT: index varlığı `information_schema` üzerinden, ayar değeri
"boşsa yaz" ile kontrol edilir; ikinci koşum hiçbir şey değiştirmez.
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe

_DOCTYPE: str = "Carrier Integration Log"
# DİKKAT: `frappe.db.table_exists` DOCTYPE adı bekler ("tab" önekini kendisi
# koyar); tablo adını geçirmek sessizce False döndürür ve patch hiçbir index
# kurmadan "çalıştı" olarak işaretlenirdi. SQL için ayrı sabit tutuluyor.
_TABLE: str = f"tab{_DOCTYPE}"


@dataclass(frozen=True)
class IndexSpec:
	name: str
	columns: tuple[str, ...]


#: Sorgu desenleri:
#:   - operasyon paneli: taşıyıcıya göre filtre + başarısızları öne al + tarih sırası
#:   - sevkiyat detayı: tek sevkiyatın entegrasyon geçmişi (tarih sırasıyla)
#:   - saklama işi: `creation < cutoff` taraması (tek kolon, sıralı okuma)
INDEXES: tuple[IndexSpec, ...] = (
	IndexSpec("ix_cil_carrier_succeeded_creation", ("carrier", "succeeded", "creation")),
	IndexSpec("ix_cil_shipment_creation", ("shipment", "creation")),
	IndexSpec("ix_cil_creation", ("creation",)),
)


def execute() -> None:
	"""Index'leri ve saklama ayarını idempotent şekilde kurar."""
	# Patch, DocType henüz migrate edilmemişken de çağrılabilir.
	frappe.reload_doc("tradehub_core", "doctype", "carrier_integration_log")
	frappe.reload_doc("tradehub_core", "doctype", "logistics_settings")

	if frappe.db.table_exists(_DOCTYPE, cached=False):
		for spec in INDEXES:
			_ensure_index(spec)
	else:
		# Tablo yoksa sessizce geçmek, patch'in "çalıştı" işaretlenip index'lerin
		# hiç kurulmaması demek olurdu. Görünür bırakıyoruz.
		frappe.log_error(
			f"{_DOCTYPE} tablosu yok — index'ler kurulamadı, patch yeniden çalıştırılmalı.",
			"v15_log043_carrier_integration_log",
		)

	retention = frappe.db.get_single_value("Logistics Settings", "integration_log_retention_days")
	if retention is None or retention == "":
		# Boş -> Bora'nın kararı olan 90 gün. Operatör 0 yazdıysa (saklama
		# kapalı) DOKUNMUYORUZ: 0 bilinçli bir tercihtir, eksik değer değil.
		frappe.db.set_single_value("Logistics Settings", "integration_log_retention_days", 90)

	frappe.db.commit()


def _ensure_index(spec: IndexSpec) -> None:
	"""Index yoksa oluşturur."""
	if _index_exists(spec.name):
		return
	columns = ", ".join(f"`{column}`" for column in spec.columns)
	# Tablo ve index adları bu modülde SABİT (kullanıcı girdisi değil) — f-string
	# burada enjeksiyon yüzeyi açmaz; DDL zaten parametre kabul etmez.
	frappe.db.sql(f"ALTER TABLE `{_TABLE}` ADD KEY `{spec.name}` ({columns})")


def _index_exists(index_name: str) -> bool:
	return bool(
		frappe.db.sql(
			"""select 1 from information_schema.statistics
			where table_schema = database() and table_name = %s and index_name = %s
			limit 1""",
			(_TABLE, index_name),
		)
	)
