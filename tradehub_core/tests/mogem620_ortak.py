"""MOGEM-620 test paketinin ortak yardımcıları.

Altı test modülü (fonksiyonel, permütasyon, yetki, e2e, maymun, duman)
aynı fixture'ları kullanıyor. Kopyalamak yerine tek dosya: fixture davranışı
değişince altı modülde altı farklı düzeltme yapılmasın.

BURADA HİÇ TEST YOK. `FrappeTestCase` alt sınıfı da yok — bu dosya test
keşfine takılmamalı, yoksa aynı yardımcılar altı kez daha koşar.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import frappe

#: Her koşumda benzersiz ek. Fixture adlarının çakışması, testler arası
#: sızıntının en sinsi biçimi (`medya-kod-tuzaklari` bulgusu: LIKE'ta `_`
#: joker ve aynı adlı artık dosyalar).
TUZ: str = frappe.generate_hash(length=10)


@contextmanager
def gercek_yetki():
	"""`frappe.only_for` kapısını test içinde GERÇEKTEN çalıştır.

	`frappe/__init__.py:954` — `local.flags.in_test` açıkken `only_for`
	ilk satırda döner. Yani `FrappeTestCase` altında yazılan her "bu rol
	reddedilmeli" iddiası kendiliğinden geçer ve HİÇBİR ŞEY ölçmez.

	Bu tuzak 6 Eylül 2026'da neredeyse sahte bir güvenlik açığı raporuna yol
	açtı (bkz. `test_e2e_media_audio` docstring'i). Bayrak yalnız ölçülen
	çağrının etrafında ve DAR kapsamda indiriliyor: `in_test` e-posta
	gönderimi ve arka plan işleri gibi başka davranışları da etkiliyor.
	"""
	onceki = frappe.flags.in_test
	frappe.flags.in_test = False
	try:
		yield
	finally:
		frappe.flags.in_test = onceki


@contextmanager
def kullanici(user: str):
	"""Oturumu geçici olarak `user`a çevir — çok kiracılı sızıntı testleri için."""
	onceki = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(onceki)


#: `png_uret` çağrı sayacı — her çağrıda farklı piksel üretmek için.
_png_sayac: list[int] = [0]


def png_uret(
	genislik: int = 8, yukseklik: int = 8, *, renk: str | None = None, bicim: str = "PNG"
) -> bytes:
	"""Gerçek raster üret — repoya ikili dosya eklemiyoruz.

	VARSAYILAN OLARAK HER ÇAĞRIDA FARKLI İÇERİK. Sebebi bir kez ısırdı:
	adlandırma İÇERİK-ADRESLİ (`naming._hashed_name`), yani aynı baytları iki
	kez yüklemek TEK bir `file_url` üretir. Aynı 8×8 kırmızı PNG'den üç dosya
	açan bir test, üç ayrı dosya sandığı şeyle aslında tek adres üzerinde
	çalışır ve toplu işlem testleri "3 bekledim, 1 geldi" der.

	`renk` açıkça verilirse o kullanılır — içeriğin belirli olması gereken
	testler (ör. locale ezmesinde iki ayrı görsel) için.
	"""
	from PIL import Image

	if renk is None:
		_png_sayac[0] += 1
		# Sayaçtan türetilen renk: çakışmayan içerik, okunabilir kaynak.
		n = _png_sayac[0]
		renk_ucu = ((n * 37) % 256, (n * 91) % 256, (n * 53) % 256)
	else:
		renk_ucu = renk
	tampon = io.BytesIO()
	Image.new("RGB", (genislik, yukseklik), renk_ucu).save(tampon, bicim)
	return tampon.getvalue()


def mp3_uret(saniye: float = 1.0, *, baslik: str = "", sanatci: str = "") -> bytes:
	"""ffmpeg ile gerçek MP3 — `test_media_audio_meta` ile aynı üretici."""
	with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
		komut = [
			"ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
			"-t", str(saniye), "-c:a", "libmp3lame", "-b:a", "32k",
		]
		if baslik:
			komut += ["-metadata", f"title={baslik}"]
		if sanatci:
			komut += ["-metadata", f"artist={sanatci}"]
		komut.append(tmp.name)
		subprocess.run(komut, capture_output=True, timeout=60, check=True)
		return Path(tmp.name).read_bytes()


def dosya_ac(ad: str, veri: bytes, *, private: int = 0, owner: str | None = None):
	"""Gerçek `File` kaydı — AV ve zenginleştirme kancaları nötr.

	Kancaların nötrlenmesi test ortamı hilesi DEĞİL, izolasyon: bu paketin
	ölçtüğü şey kancaların kendisi değil (`test_..._duman` onları ayrıca
	ölçüyor) ve canlı worker aynı satıra dokununca `Lock wait timeout`
	alınıyor (10 Eyl ölçümü — `zenginlestirme_notr` docstring'i).
	"""
	with mock.patch("tradehub_core.media.av.enqueue_scan"), mock.patch(
		"tradehub_core.media.audio_meta.maybe_extract_on_insert"
	), mock.patch("tradehub_core.media.doc_meta.maybe_extract_on_insert"):
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": ad,
				"is_private": private,
				"content": veri,
				"decode": False,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
	if owner and doc.owner != owner:
		# `doc.owner` INSERT ÖNCESİ atanamıyor: Frappe `owner`ı oturumdan
		# yazıyor ve verilen değeri sessizce eziyor. Sahiplik testleri
		# (`ownership.owns` → `File.owner`) bu yüzden hep başarısız oluyordu.
		# Insert SONRASI doğrudan yazmak tek yol; `update_modified=False`
		# çünkü bu bir fixture düzeltmesi, bir kullanıcı eylemi değil.
		frappe.db.set_value("File", doc.name, "owner", owner, update_modified=False)
		doc.owner = owner
		# Sahiplik önbelleği eski değeri tutuyor olabilir.
		from tradehub_core.media import ownership

		ownership.clear_url_cache()
	return doc


def sil(doctype: str, name: str) -> None:
	"""Temizlik — kilit çakışmasında testi düşürmeden geç.

	`Lock wait timeout` temizlik aşamasında ölçülen davranışla ilgisiz bir
	sebeple testi kırmıştı (10 Eyl). Temizlik en iyi çabadır; artık kayıt
	bırakmak, yeşil bir testi kırmızıya çevirmekten iyidir.
	"""
	try:
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
	except Exception:
		frappe.clear_last_message()


def magaza_bul() -> str | None:
	"""Testlerde kullanılabilecek gerçek bir mağaza — yoksa None."""
	satir = frappe.get_all("Admin Seller Profile", pluck="name", limit=1)
	return satir[0] if satir else None
