"""Medya tarih/saat standardı (TUR-124).

**Sorun, ölçümle.** Sunucu tarihleri saat dilimi işareti OLMADAN gönderiyordu:

    2026-08-14 09:39:06.911581

Tarayıcı bu dizeyi kendi yerel saati sanıyor. Ölçüldü — aynı yükleme farklı
saat dilimlerinde şöyle görünüyordu:

    İstanbul   09:39   ✓  (doğru, çünkü sunucu da İstanbul)
    Londra     09:39   ✗  (07:39 olmalıydı)
    New York   09:39   ✗  (02:39 olmalıydı)
    Tokyo      09:39   ✗  (15:39 olmalıydı)

Yani herkes aynı rakamı görüyordu. Panel dört dili destekliyor; yurtdışındaki
satıcı dosyasını saatler önce/sonra yüklenmiş sanıyordu.

**Karar.** Saklama değişmiyor — tüm sistem Frappe'nin biçimine dayalı ve onu
değiştirmek medyanın kapsamını çok aşar. Değişen yalnız **API çıktısı**: tarih
dışarı çıkarken ISO 8601 ve saat dilimi kaymasıyla birlikte veriliyor.

    2026-08-14T09:39:06+03:00

Bu biçim tek anlamlı: tarayıcı onu doğru ana çevirip kullanıcının kendi
saatiyle gösterebiliyor. Panelin biçimlendirme işi tek yerde toplanıyor
(`utils/dateFormat.js`).

**Neden mikro saniye atılıyor.** `.911581` hiçbir ekranda gösterilmiyor ve
bazı tarayıcılarda ayrıştırmayı zorlaştırıyor. Saniye yeterli.
"""

from __future__ import annotations

from datetime import datetime

import frappe

# Bu alanlar medya uçlarından dışarı çıkarken dönüştürülür. Liste açık
# tutuluyor: yeni bir tarih alanı eklendiğinde buraya yazılmazsa eski
# biçimde gider ve sessizce standart dışı kalır.
FIELDS: tuple[str, ...] = (
	"creation",
	"modified",
	"uploaded_at",
	"optimized_at",
	"trashed_at",
	"timestamp",
	"created",
	"finished",
	"started",
	# Bekletme listesi (TUR-125) taramanın başlama anını gösteriyor; listedeki
	# diğer adlarla aynı kural — kapsam dışında kalsaydı o sütun İstanbul
	# dışındaki kullanıcıda kaymış görünürdü.
	"started_at",
	"finished_at",
	"created_at",
	"captured",
	"last_execution",
)


def site_timezone() -> str:
	"""Sunucunun saat dilimi — çıktıdaki kaymanın kaynağı."""
	try:
		return frappe.utils.get_system_timezone()
	except Exception:
		return "Europe/Istanbul"


def to_iso(deger) -> str:
	"""Tek bir tarihi standart çıktı biçimine çevir.

	Boş değer boş döner: `None` yerine `""` vermek ekranın "—" gösterebilmesi
	için yeterli ve JSON'da tür değiştirmiyor.
	"""
	if not deger:
		return ""

	if isinstance(deger, str):
		# Frappe metin olarak da verebiliyor; önce nesneye çevir.
		try:
			deger = frappe.utils.get_datetime(deger)
		except Exception:
			return deger

	if not isinstance(deger, datetime):
		return str(deger)

	# Saat dilimi bilgisi yoksa sunucununki varsayılıyor — Frappe tarihleri
	# zaten sunucu saatinde saklıyor.
	if deger.tzinfo is None:
		try:
			import pytz

			deger = pytz.timezone(site_timezone()).localize(deger)
		except Exception:
			return deger.replace(microsecond=0).isoformat()

	return deger.replace(microsecond=0).isoformat()


def apply(satir: dict) -> dict:
	"""Bir satırdaki tüm tarih alanlarını standarda çevir — yerinde."""
	for alan in FIELDS:
		if alan in satir:
			satir[alan] = to_iso(satir[alan])
	return satir


def apply_all(satirlar: list[dict]) -> list[dict]:
	for s in satirlar:
		apply(s)
	return satirlar
