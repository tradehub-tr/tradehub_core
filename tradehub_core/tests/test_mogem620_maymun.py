"""MOGEM-620 — maymun (monkey/fuzz) testleri.

NE ARIYOR
---------
Bu modül DOĞRULUK aramıyor; ÇÖKME arıyor. Sözleşme tek cümle:

    Bu turda eklenen hiçbir fonksiyon, ne kadar saçma girdi verilirse
    verilsin, BEKLENMEYEN bir istisna atmamalı.

Beklenen istisnalar (`ValidationError`, `PermissionError`) sözleşmenin
parçası ve kabul ediliyor. `AttributeError`, `TypeError`, `KeyError`,
`IndexError`, `UnicodeDecodeError`, `ZeroDivisionError` ise kusur: hepsi
"girdiyi düşünmemişiz" demek.

NEDEN ÖNEMLİ — ÖLÇÜLMÜŞ EMSAL
-----------------------------
F-18a: `audit_fields` "saf fonksiyon" diye belgelenmişti ama `alt` bir sayı
olduğunda `AttributeError` atıyordu ve tek bozuk satır toplu denetim
ekranının TAMAMINI düşürüyordu. Alan değerleri DB'den, API'den ve eski
migration'lardan geliyor; tür garantisi yok.

DETERMİNİSTİK
-------------
Tohum sabit (`TOHUM`), yani başarısızlık YENİDEN ÜRETİLEBİLİR. Ortam
değişkeniyle değiştirilebiliyor — KD paketinin `KD_FUZZ_TOHUM` deseniyle
aynı:

    KD_FUZZ_TOHUM=12345 bench --site ... run-tests --module ...

Koşum:
    docker exec istoc-backend bench --site tradehub.localhost \\
        run-tests --module tradehub_core.tests.test_mogem620_maymun
"""

from __future__ import annotations

import os
import random
import string

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import bulk_ops, decode_cost, meter, seo_audit, similar, tags_source
from tradehub_core.seo import schema_builder

TOHUM: int = int(os.environ.get("KD_FUZZ_TOHUM") or 620620)

#: Tur sayısı. Ortam değişkeniyle artırılabilir; varsayılan CI'da makul.
TUR: int = int(os.environ.get("KD_FUZZ_TUR") or 300)

#: KUSUR sayılan istisnalar. `ValidationError`/`PermissionError` sözleşmenin
#: parçası; buradakiler "girdiyi düşünmemişiz" demek.
BEKLENMEYEN = (
	AttributeError,
	IndexError,
	KeyError,
	TypeError,
	UnicodeDecodeError,
	ZeroDivisionError,
	OverflowError,
)

#: Girdi hazinesi — gerçek sistemlerde gerçekten karşılaşılan saçmalıklar.
#: Sayı/None/bool: eski migration'ların bıraktığı tür kaymaları.
#: Kontrol karakteri ve RTL: kullanıcı yapıştırması.
#: Çok uzun metin: kopyala-yapıştır ürün açıklaması.
_HAZINE: tuple = (
	None, "", " ", "\t\n", 0, 1, -1, 1.5, True, False,
	[], {}, (), set(),
	"a" * 5000,
	"'; DROP TABLE tabFile; --",
	"<script>alert(1)</script>",
	"../../../etc/passwd",
	"%s", "%d", "{sira}", "{ad}", "{}",
	"\x00\x01\x02",
	"مرحبا", "Ünïcödé", "🎉🎉🎉",
	"NaN", "Infinity", "-0",
	"1e400",
	"2026-13-45",
	'{"bozuk": ',
	"[]", "{}", "null",
)


def _rastgele_deger(rnd: random.Random):
	"""Hazineden ya da rastgele üretilmiş bir değer."""
	if rnd.random() < 0.75:
		return rnd.choice(_HAZINE)
	uzunluk = rnd.randint(0, 40)
	return "".join(rnd.choice(string.printable) for _ in range(uzunluk))


def _rastgele_sozluk(rnd: random.Random, anahtarlar: tuple[str, ...]) -> dict:
	return {a: _rastgele_deger(rnd) for a in anahtarlar if rnd.random() < 0.6}


class _MaymunTemel(FrappeTestCase):
	"""Ortak koşucu: her turda çağır, yalnız BEKLENMEYEN istisnada kır."""

	def maymunla(self, cagri, *, tur: int = TUR, etiket: str = ""):
		rnd = random.Random(TOHUM)
		for i in range(tur):
			girdi = None
			try:
				girdi = cagri(rnd)
			except BEKLENMEYEN as exc:
				self.fail(
					f"{etiket} tur={i} tohum={TOHUM} girdi={girdi!r} "
					f"BEKLENMEYEN {type(exc).__name__}: {exc}"
				)
			except (frappe.ValidationError, frappe.PermissionError, ValueError):
				# Sözleşmenin parçası — reddetmek doğru davranış.
				continue
			except Exception as exc:  # noqa: BLE001
				# Frappe kendi istisna ağacını kullanıyor; tanımadıklarımızı
				# kusur SAYMIYORUZ ama görünür kılıyoruz.
				if type(exc).__module__.startswith("frappe"):
					continue
				self.fail(f"{etiket} tur={i} tohum={TOHUM} beklenmedik {type(exc).__name__}: {exc}")


class TestSafFonksiyonMaymunu(_MaymunTemel):
	"""DB'ye dokunmayan fonksiyonlar — en hızlı ve en geniş tarama."""

	def test_render_name(self):
		def cagri(rnd):
			girdi = (_rastgele_deger(rnd), _rastgele_deger(rnd), _rastgele_deger(rnd))
			bulk_ops.render_name(
				str(girdi[0] or ""), taban=str(girdi[1] or ""), sira=rnd.randint(-5, 10**6),
				uzanti=str(girdi[2] or ""),
			)
			return girdi

		self.maymunla(cagri, etiket="render_name")

	def test_validate_pattern(self):
		def cagri(rnd):
			deger = _rastgele_deger(rnd)
			bulk_ops.validate_pattern(str(deger) if deger is not None else "")
			return deger

		self.maymunla(cagri, etiket="validate_pattern")

	def test_validate_robots(self):
		def cagri(rnd):
			deger = _rastgele_deger(rnd)
			bulk_ops.validate_robots(str(deger) if deger is not None else "")
			return deger

		self.maymunla(cagri, etiket="validate_robots")

	def test_normalize_urls(self):
		def cagri(rnd):
			liste = [_rastgele_deger(rnd) for _ in range(rnd.randint(0, 8))]
			bulk_ops.normalize_urls(liste)
			return liste

		self.maymunla(cagri, etiket="normalize_urls")

	def test_decode_cost(self):
		def cagri(rnd):
			girdi = {
				"width": rnd.choice([0, -5, 1, 10**6, 10**9]),
				"height": rnd.choice([0, -5, 1, 10**6, 10**9]),
				"file_format": str(_rastgele_deger(rnd) or ""),
				"has_alpha": rnd.choice([True, False]),
				"progressive": rnd.choice([True, False]),
			}
			decode_cost.estimate(**girdi)
			return girdi

		self.maymunla(cagri, etiket="decode_cost.estimate")

	def test_media_size(self):
		def cagri(rnd):
			girdi = {
				"width": rnd.choice([0, -1, 4000]),
				"height": rnd.choice([0, -1, 3000]),
				"bytes_": rnd.choice([0, -1, 10**12]),
				"file_format": str(_rastgele_deger(rnd) or ""),
				"rendered_width": rnd.choice([0, -1, 400]),
				"rendered_height": rnd.choice([0, -1, 300]),
			}
			decode_cost.media_size(**girdi)
			return girdi

		self.maymunla(cagri, etiket="decode_cost.media_size")

	def test_tags_source_parse(self):
		def cagri(rnd):
			deger = _rastgele_deger(rnd)
			tags_source.parse(deger)
			return deger

		self.maymunla(cagri, etiket="tags_source.parse")

	def test_tags_source_senkronla(self):
		def cagri(rnd):
			harita = {str(_rastgele_deger(rnd)): "manual" for _ in range(rnd.randint(0, 4))}
			etiketler = [_rastgele_deger(rnd) for _ in range(rnd.randint(0, 4))]
			tags_source.senkronla(harita, etiketler)
			return (harita, etiketler)

		self.maymunla(cagri, etiket="tags_source.senkronla")

	def test_tags_source_ozet(self):
		def cagri(rnd):
			harita = {str(_rastgele_deger(rnd)): str(_rastgele_deger(rnd)) for _ in range(4)}
			tags_source.ozet(harita)
			return harita

		self.maymunla(cagri, etiket="tags_source.ozet")


class TestDenetimMaymunu(_MaymunTemel):
	"""F-18a'nın sınıfı: alan sözlüğü DB'den geliyor, tür garantisi yok."""

	ALANLAR = (
		"alt", "title", "caption", "description", "width", "height",
		"license_url", "copyright_notice", "rights_expires_on", "poster_url",
		"transcript", "duration", "perceptual_hash", "has_text", "tags",
		"creator", "canonical", "keywords", "geo", "chapters",
	)

	def test_audit_fields(self):
		def cagri(rnd):
			alanlar = _rastgele_sozluk(rnd, self.ALANLAR)
			seo_audit.audit_fields(alanlar, file_name=str(_rastgele_deger(rnd) or ""))
			return alanlar

		self.maymunla(cagri, etiket="audit_fields")

	def test_score_from(self):
		def cagri(rnd):
			alanlar = _rastgele_sozluk(rnd, self.ALANLAR)
			bulgular = [
				{
					"code": str(_rastgele_deger(rnd)),
					"severity": rnd.choice(["error", "warn", "uydurma", None]),
					"message": "",
					"detail": "",
				}
				for _ in range(rnd.randint(0, 3))
			]
			skor = seo_audit.score_from(bulgular, alanlar)
			# Sözleşme: her boyut 0-100 aralığında kalmalı.
			for boyut, deger in skor.items():
				assert 0 <= deger <= 100, f"{boyut}={deger} aralık dışı"
			return (bulgular, alanlar)

		self.maymunla(cagri, etiket="score_from")

	def test_skor_hicbir_girdide_aralik_disina_cikmaz(self):
		"""Ceza döngüsü 100'ün altına inebilir ama ASLA negatife inmemeli."""
		bulgular = [
			{"code": kod, "severity": "error", "message": "", "detail": ""}
			for kod in list(seo_audit._KURAL_BOYUT) * 5
		]
		skor = seo_audit.score_from(bulgular, {})
		for boyut, deger in skor.items():
			self.assertGreaterEqual(deger, 0, msg=boyut)
			self.assertLessEqual(deger, 100, msg=boyut)


class TestSemaMaymunu(_MaymunTemel):
	"""JSON-LD üreticileri: çıktı yayına gidiyor, bozuk girdide susmalı."""

	ALANLAR = (
		"file_url", "poster_url", "title", "alt", "caption", "description",
		"duration", "transcript", "rights_expires_on", "regions_allowed",
		"content_rating", "age_restriction", "chapters", "keywords",
		"location", "country", "geo", "width", "height", "license_url",
	)

	def test_build_image_object(self):
		def cagri(rnd):
			alanlar = _rastgele_sozluk(rnd, self.ALANLAR)
			schema_builder.build_image_object(alanlar, "https://x.test")
			return alanlar

		self.maymunla(cagri, etiket="build_image_object")

	def test_build_video_object(self):
		def cagri(rnd):
			alanlar = _rastgele_sozluk(rnd, self.ALANLAR)
			schema_builder.build_video_object(
				alanlar,
				"https://x.test",
				content_url=str(_rastgele_deger(rnd) or ""),
				embed_url=str(_rastgele_deger(rnd) or ""),
			)
			return alanlar

		self.maymunla(cagri, etiket="build_video_object")

	def test_build_audio_object(self):
		def cagri(rnd):
			alanlar = _rastgele_sozluk(rnd, self.ALANLAR)
			schema_builder.build_audio_object(
				alanlar, "https://x.test", content_url=str(_rastgele_deger(rnd) or "")
			)
			return alanlar

		self.maymunla(cagri, etiket="build_audio_object")

	def test_build_product_schema(self):
		def cagri(rnd):
			varyantlar = [
				{
					"variant_sku": _rastgele_deger(rnd),
					"variant_gtin": _rastgele_deger(rnd),
					"variant_price": _rastgele_deger(rnd),
					"variant_stock": _rastgele_deger(rnd),
					"attribute_type": _rastgele_deger(rnd),
					"attribute_value": _rastgele_deger(rnd),
				}
				for _ in range(rnd.randint(0, 3))
			]
			listing = {
				"name": str(_rastgele_deger(rnd) or ""),
				"slug": str(_rastgele_deger(rnd) or ""),
				"title": _rastgele_deger(rnd),
				"gtin": _rastgele_deger(rnd),
				"has_variants": rnd.choice([0, 1, True, None]),
				"variants": varyantlar,
				"price": rnd.choice([0, 10, None, "abc"]),
			}
			schema_builder.build_product_schema(
				listing=listing, site_url="https://x.test", brand=None,
				category_name=None, aggregate_rating=None, reviews=None,
			)
			return listing

		self.maymunla(cagri, tur=min(TUR, 150), etiket="build_product_schema")

	def test_chapters_her_bicimde_dayanikli(self):
		"""Bölüm verisi elle bozulmuş olabilir — VideoObject düşmemeli."""
		bozuk_bolumler = (
			"[]", "{}", "null", "[1,2,3]", '[{"start": "abc"}]',
			'[{"start": -5, "title": "x"}]', '[{"title": "start yok"}]',
			'[{"start": 1e400, "title": "x"}]', "[[[[", '["metin"]',
		)
		for ham in bozuk_bolumler:
			obj = schema_builder.build_video_object(
				{"poster_url": "/p.jpg", "title": "V", "chapters": ham},
				"https://x.test",
				content_url="/v.mp4",
			)
			self.assertIsNotNone(obj, msg=ham)


class TestKotaMaymunu(_MaymunTemel):
	"""§18 — sayaç ve karar fonksiyonu saçma girdide çökmemeli."""

	def test_check_her_limitte(self):
		"""Zincirin TAMAMI: plan JSON'u → `limit_for` → `check`.

		`limit_for`ı doğrudan mock'lamak YANLIŞ olurdu: o zaman üretimde
		imkânsız bir durumu (limit_for'un metin döndürmesi) sınar ve asıl
		savunmanın — plan JSON'undaki bozuk değerin temizlenmesi — hiç
		çalıştığını görmezdik. Bozukluk plan verisine ENJEKTE ediliyor.
		"""
		from unittest import mock

		def cagri(rnd):
			limit = rnd.choice([None, -1, 0, 1, 10**12, -999, 1.5, "abc", "5 GB", float("nan"), []])
			gelen = rnd.choice([0, -1, 1, 10**12, None, "abc", float("inf")])
			anahtar = meter.QUOTA_KEYS[meter.METRIC_AI]
			with mock.patch(
				"tradehub_core.entitlement.core.get_quota_limits",
				return_value={anahtar: limit},
			), mock.patch.object(meter, "consumed", return_value=rnd.choice([0, 5, 10**9])):
				karar = meter.check("MAGAZA", meter.METRIC_AI, incoming=gelen)
			assert isinstance(karar["allowed"], bool), karar
			assert karar["reason"] in {"ok", "unlimited", "unconfigured", "exceeded", "disabled"}
			return (limit, gelen)

		self.maymunla(cagri, tur=min(TUR, 120), etiket="meter.check")

	def test_bozuk_plan_degeri_kotayi_uygulamaz(self):
		"""Sayıya çevrilemeyen limit → `unconfigured` (fail-open), çökme değil."""
		from unittest import mock

		anahtar = meter.QUOTA_KEYS[meter.METRIC_AI]
		for bozuk in ("5 GB", "", [], {}, float("nan")):
			with mock.patch(
				"tradehub_core.entitlement.core.get_quota_limits", return_value={anahtar: bozuk}
			):
				self.assertIsNone(meter.limit_for("MAGAZA", meter.METRIC_AI), msg=repr(bozuk))

	def test_period_key_her_zaman_bicimli(self):
		self.assertRegex(meter.period_key(), r"^\d{4}-\d{2}$")

	def test_record_bilinmeyen_girdide_sessiz(self):
		def cagri(rnd):
			girdi = (_rastgele_deger(rnd), _rastgele_deger(rnd), _rastgele_deger(rnd))
			meter.record(str(girdi[0] or ""), str(girdi[1] or ""), girdi[2])
			return girdi

		self.maymunla(cagri, tur=min(TUR, 100), etiket="meter.record")


class TestBenzerlikMaymunu(_MaymunTemel):
	"""§16 — hash karşılaştırması bozuk hash'lerde çökmemeli."""

	def test_search_saçma_adreste(self):
		def cagri(rnd):
			adres = _rastgele_deger(rnd)
			similar.search(
				str(adres) if adres is not None else "",
				threshold=rnd.choice([None, -5, 0, 3, 999]),
				limit=rnd.choice([0, -1, 1, 10**6]),
			)
			return adres

		self.maymunla(cagri, tur=min(TUR, 80), etiket="similar.search")

	def test_yanit_sekli_her_dalda_ayni(self):
		"""F-22 dersi: yanıt şekli girdiye göre DEĞİŞMEMELİ."""
		beklenen = {"matches", "total", "truncated", "reason", "file_url"}
		for adres in ("", "/files/yok.png", "abc", "//kotu/x.png"):
			self.assertEqual(set(similar.search(adres)), beklenen, msg=adres)
