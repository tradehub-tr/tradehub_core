"""Çeviri CSV'leri Frappe'nin okuyucusunun kabul ettiği biçimde mi? (MOGEM-638 §4.6)

`frappe.translate.get_translation_dict_from_file` her satırı `len(row) in (2, 3)`
ile süzer; yorum (`# ...`) ve boş satırlar bu kurala girmez ve her biri için
"Error in translation file" başlıklı bir Error Log yazılır. tr.csv'de 35 yorum +
33 boş satır vardı; 30 günde 59.034 hata kaydının kaynağı buydu. Bu test o
satırların geri gelmesini CI'da yakalar — Frappe okuyucusunu değil, aynı kuralı
uygular ki site açmadan (unittest ile) koşabilsin.
"""

import csv
import glob
import os
import unittest

TRANSLATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "translations")


class TestCeviriCSVBicimi(unittest.TestCase):
	def _dosyalar(self) -> list[str]:
		dosyalar = sorted(glob.glob(os.path.join(TRANSLATIONS_DIR, "*.csv")))
		self.assertTrue(dosyalar, f"çeviri dosyası bulunamadı: {TRANSLATIONS_DIR}")
		return dosyalar

	def test_her_satir_iki_veya_uc_sutun(self):
		"""Frappe'nin kuralı: `len(row) in (2, 3)`; aksi satır başına bir Error Log."""
		bozuk: list[str] = []
		for yol in self._dosyalar():
			with open(yol, newline="", encoding="utf-8") as f:
				for satir_no, row in enumerate(csv.reader(f), start=1):
					if len(row) not in (2, 3):
						bozuk.append(f"{os.path.basename(yol)}:{satir_no} ({len(row)} sütun): {row[:1]}")
		self.assertEqual(bozuk, [], "Frappe'nin reddedeceği satırlar:\n" + "\n".join(bozuk))

	def test_yorum_satiri_yok(self):
		"""`# ...` satırı virgül içeriyorsa 3 sütun sayılır ve 'çeviri' olarak yüklenir —
		sütun testi onu yakalamaz; ayrıca yasaklanmalı."""
		yorumlar: list[str] = []
		for yol in self._dosyalar():
			with open(yol, encoding="utf-8") as f:
				for satir_no, satir in enumerate(f, start=1):
					if satir.lstrip().startswith("#"):
						yorumlar.append(f"{os.path.basename(yol)}:{satir_no}")
		self.assertEqual(yorumlar, [], "yorum satırları: " + ", ".join(yorumlar))

	def test_kaynak_metin_bos_degil(self):
		"""Boş kaynak metin çeviri sözlüğüne `"" → x` girer; anlamsız ve gizli hata."""
		bos: list[str] = []
		for yol in self._dosyalar():
			with open(yol, newline="", encoding="utf-8") as f:
				for satir_no, row in enumerate(csv.reader(f), start=1):
					if row and not row[0].strip():
						bos.append(f"{os.path.basename(yol)}:{satir_no}")
		self.assertEqual(bos, [], "boş kaynak metin: " + ", ".join(bos))
