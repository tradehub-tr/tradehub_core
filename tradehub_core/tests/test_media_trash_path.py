"""`media/trash.py::_relative` — path traversal kontrolü segment bazlı olmalı.

Eski kontrol `".." in url` düz altdizge aramasıydı ve MEŞRU dosya adlarını da
reddediyordu. Canlı DB'de ölçüldü (2026-08-19): `..` içeren **19** dosyanın
hiçbiri traversal değil — hepsi ürün açıklamasının dosya adına girmesinden
(`MOİ ile derin düzen..jpg`). Bu dosyalar çöpe atılamıyor, geri alınamıyor,
arşivlenemiyor, optimize edilemiyordu.

Bu modül kontrolün **iki yönünü birden** sabitler: gerçek traversal reddedilmeye
devam ediyor, meşru ad artık geçiyor. Tek yönü test etmek yetmez — "her şeyi
reddet" de testi yeşil yapardı.

`_trash_path` / `_live_path` ayrıca `realpath` + kök öneki ile ikinci kez
doğruluyor; yani savunma tek katmana bağlı değil. Bu testler ilk katmanı ölçer.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_trash_path
"""

from __future__ import annotations

import unittest

import frappe

from tradehub_core.media import trash


class TestTrashRelativePath(unittest.TestCase):
	"""`_relative` yalnız gerçek traversal'ı reddetmeli."""

	#: Gerçek traversal — segment olarak `..` taşıyor, reddedilmeli.
	TRAVERSAL: tuple[str, ...] = (
		"/files/../etc/passwd",
		"/files/a/../../secret",
		"/files/../../../../etc/shadow",
		"/files/..",
		"/files/alt/../../ust.jpg",
	)

	#: Meşru adlar — `..` altdizge olarak var ama segment DEĞİL, geçmeli.
	MESRU: tuple[str, ...] = (
		"/files/MOİ ile derin düzen..jpg",
		"/files/Yiyeceklerinizi güvenle saklayın ve kolayca ısıtın..jpg",
		"/files/rapor..pdf",
		"/files/ab/hash..webp",
		"/files/normal.jpg",
	)

	def test_gercek_traversal_reddedilir(self) -> None:
		for url in self.TRAVERSAL:
			with self.subTest(url=url):
				with self.assertRaises(frappe.ValidationError):
					trash._relative(url)

	def test_mesru_ad_gecer(self) -> None:
		for url in self.MESRU:
			with self.subTest(url=url):
				# Fırlatmamalı ve `/files/` önekini soymalı.
				self.assertEqual(trash._relative(url), url[len("/files/") :])

	def test_files_disi_onek_reddedilir(self) -> None:
		for url in ("/private/files/x.jpg", "/assets/x.jpg", "x.jpg", "", None):
			with self.subTest(url=url):
				with self.assertRaises(frappe.ValidationError):
					trash._relative(url)  # type: ignore[arg-type]

	def test_sorgu_dizesi_soyulur(self) -> None:
		"""`?` sonrası atılır — imzalı URL'ler de çözülebilmeli."""
		self.assertEqual(trash._relative("/files/a.jpg?v=2"), "a.jpg")
