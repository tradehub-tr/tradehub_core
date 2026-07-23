"""
Migration Patch: Addresses.state ASCII → Türkçe diakritikli normalizasyon.

Frontend (storefront + admin-panel) il listesi proper Türkçe karakterlere çevrildi
(Adiyaman → Adıyaman, Istanbul → İstanbul, Sanliurfa → Şanlıurfa, vb.). Mevcut
DB'deki eski ASCII değerler dropdown'da "varsayılan değer" olarak match olmaz
ve ilçe listesi exact-match lookup'ında çözülemez (`districtsByProvince[state]`).

Bu patch, `Addresses.state` kolonundaki bilinen 31 ASCII varyantı tek SQL UPDATE
seti ile diakritikli versiyona çevirir. Idempotent — zaten diakritikli olanlar
tekrar yazılmaz çünkü WHERE state = ASCII filtresi onları dışlar.
"""

import frappe

# ASCII → Diakritikli Türkçe il adı eşlemesi.
# Sadece farkı olan 31 il listelendi; diğer 50 il (Adana, Ankara, vb.) zaten ASCII
# ile diakritikli aynı yazılıyor, dokunmaya gerek yok.
ASCII_TO_DIACRITIC = {
	"Adiyaman": "Adıyaman",
	"Agri": "Ağrı",
	"Aydin": "Aydın",
	"Balikesir": "Balıkesir",
	"Bingol": "Bingöl",
	"Canakkale": "Çanakkale",
	"Cankiri": "Çankırı",
	"Corum": "Çorum",
	"Diyarbakir": "Diyarbakır",
	"Elazig": "Elazığ",
	"Eskisehir": "Eskişehir",
	"Gumushane": "Gümüşhane",
	"Istanbul": "İstanbul",
	"Izmir": "İzmir",
	"Kirklareli": "Kırklareli",
	"Kirsehir": "Kırşehir",
	"Kutahya": "Kütahya",
	"Kahramanmaras": "Kahramanmaraş",
	"Mugla": "Muğla",
	"Mus": "Muş",
	"Nevsehir": "Nevşehir",
	"Nigde": "Niğde",
	"Tekirdag": "Tekirdağ",
	"Sanliurfa": "Şanlıurfa",
	"Usak": "Uşak",
	"Kirikkale": "Kırıkkale",
	"Sirnak": "Şırnak",
	"Bartin": "Bartın",
	"Igdir": "Iğdır",
	"Karabuk": "Karabük",
	"Duzce": "Düzce",
}


def execute():
	if not frappe.db.exists("DocType", "Addresses"):
		# Henüz Addresses doctype'ı oluşturulmamış (fresh install öncesi); pas geç.
		return

	updated = 0
	for ascii_name, diacritic_name in ASCII_TO_DIACRITIC.items():
		_ = frappe.db.sql(
			"""
			UPDATE `tabAddresses`
			SET state = %(new)s
			WHERE state = %(old)s
			""",
			{"old": ascii_name, "new": diacritic_name},
		)
		# frappe.db.sql for UPDATE returns nothing; count via separate query
		count = frappe.db.count("Addresses", {"state": diacritic_name})
		if count:
			updated += 1

	frappe.db.commit()
	frappe.logger("patches").info(f"normalize_address_provinces_diacritics: {len(ASCII_TO_DIACRITIC)} il varyantı tarandı")
