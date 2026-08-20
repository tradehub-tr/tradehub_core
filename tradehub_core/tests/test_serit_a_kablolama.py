# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Şerit A — kablolamanın ÖLÇÜMÜ (T-040 · T-043 · T-044 · T-064 · T-133).

Bu modül "kod yazıldı" ile "kod DEVREDE" arasındaki farkı ölçer. Bu depoda
bugüne kadar üç kez tam bu noktada yanılındı:

  * `reload_doc` sessizce `False` döndü, yama "koştu" yazıldı, DocType hiç
    kurulmadı (`docs/reports/32-faz8-api-kapanis.md`).
  * KYC/KYB `status` alanı JSON'da permlevel 4'tü, canlı `tabDocField`de 1'di.
  * `instrument.install()` yazılıydı ama ÇAĞIRAN satır yoktu; 24 metriğin
    hiçbiri toplanmıyordu (`docs/reports/42-t133-gozlemlenebilirlik.md` §5.1).

Bu yüzden buradaki her iddia CANLI kaynaktan ölçülür: şema dosyasından değil
`tabDocField`den, kod okumasından değil gerçek `insert`ten.
"""

from __future__ import annotations

import unittest

import frappe

from tradehub_core.api import observability as obs
from tradehub_core.media.pipeline.core import crop as crop_core
from tradehub_core.media.pipeline.core import usage as usage_core


# ── 1. Kurulum: DocType gerçekten var mı ─────────────────────────────────


class KurulumOlcumu(unittest.TestCase):
	"""`tabDocType` ve `information_schema` — iddia değil ölçüm."""

	def test_media_usage_kurulu(self) -> None:
		self.assertTrue(frappe.db.exists("DocType", "Media Usage"))
		self.assertTrue(frappe.db.table_exists("Media Usage"))

	def test_media_version_kurulu(self) -> None:
		self.assertTrue(frappe.db.exists("DocType", "Media Version"))
		self.assertTrue(frappe.db.table_exists("Media Version"))

	def test_media_usage_tekillik_kisiti_UNIQUE(self) -> None:
		"""`uk_usage_quad` UNIQUE olmazsa `on duplicate key update` HİÇ tetiklenmez.

		O ifade `core/usage.py::FrappeUsageBackend.upsert`ın idempotency'sinin
		tamamıdır: kısıt yoksa her yazma yeni satır açar, kapatılan bir bağ
		açık kopyası yüzünden hâlâ açık görünür ve öksüz kararı bozulur.
		"""
		satir = frappe.db.sql(
			"""select non_unique, group_concat(column_name order by seq_in_index) as kolonlar
			from information_schema.statistics
			where table_schema = database() and table_name = 'tabMedia Usage'
			  and index_name = 'uk_usage_quad' group by non_unique""",
			as_dict=True,
		)
		self.assertTrue(satir, "uk_usage_quad indeksi YOK")
		self.assertEqual(int(satir[0]["non_unique"]), 0, "uk_usage_quad UNIQUE değil")
		self.assertEqual(satir[0]["kolonlar"], "asset,ref_doctype,ref_name,ref_field")

	def test_active_version_alani_CANLI_tabDocFieldde(self) -> None:
		"""JSON'da doğru ≠ canlıda etkin — iddia `tabDocField`den ölçülür."""
		alan = frappe.db.get_value(
			"DocField",
			{"parent": "Media Asset", "fieldname": "active_version"},
			["fieldtype", "options", "permlevel", "read_only"],
			as_dict=True,
		)
		self.assertTrue(alan, "Media Asset.active_version `tabDocField`de YOK")
		self.assertEqual(alan["fieldtype"], "Link")
		self.assertEqual(alan["options"], "Media Version")
		# permlevel 1: "hangi sürüm yayında" bir moderasyon kararıdır.
		self.assertEqual(int(alan["permlevel"] or 0), 1)
		self.assertEqual(int(alan["read_only"] or 0), 1)

	def test_active_version_kolonu_tabloda(self) -> None:
		self.assertTrue(frappe.db.has_column("Media Asset", "active_version"))


# ── 2. Crop override kırığı — uçtan uca ──────────────────────────────────


class CropOverrideKirigi(unittest.TestCase):
	"""Kırığın kendisi: `overrides` ile kırpma niyeti kaydedilebiliyor mu.

	ÖLÇÜLEN KIRIK: `Media Crop Override.profile` Link→Media Profile idi,
	docname'ler `product.image:w1920` biçiminde; `pipeline/api/crop.py:472`
	ise `render.load_profiles()`ın verdiği KISA adı (`w1920`) doğruluyor ve
	yazıyor. İkisini birden karşılayan değer YOKTU.
	"""

	def test_alan_canlida_Data_ve_options_bos(self) -> None:
		alan = frappe.db.get_value(
			"DocField",
			{"parent": "Media Crop Override", "fieldname": "profile"},
			["fieldtype", "options"],
			as_dict=True,
		)
		self.assertTrue(alan)
		self.assertEqual(alan["fieldtype"], "Data")
		self.assertFalse(alan["options"], "Link hedefi temizlenmemiş")

	def test_politika_adi_gercekten_KAYDEDILEBILIYOR(self) -> None:
		"""Asıl ölçüm: kısa profil adıyla bir override satırı DB'ye yazılıyor mu.

		Alan Link kalsaydı `w1920` için `LinkValidationError` alınır ve testin
		tamamı kırmızı olurdu — vacuity deneyi bunu gösteriyor.
		"""
		kisa_ad = self._politika_adi("product.image")
		asset = self._asset_yarat()
		try:
			niyet = frappe.get_doc(
				{
					"doctype": "Media Crop Intent",
					"asset": asset,
					"method": "manual",
					"overrides": [
						{
							"doctype": "Media Crop Override",
							"profile": kisa_ad,
							"x": 0.1,
							"y": 0.2,
							"w": 0.5,
							"h": 0.4,
							"method": "manual",
						}
					],
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()

			okunan = frappe.get_doc("Media Crop Intent", niyet.name)
			self.assertEqual(len(okunan.overrides), 1)
			self.assertEqual(okunan.overrides[0].profile, kisa_ad)

			# Okuma tarafı da aynı kısa adı bekliyor: zincirin iki ucu buluştu.
			rect = crop_core.override_for(okunan, kisa_ad)
			self.assertIsNotNone(rect, "override_for kaydedilmiş kırpımı bulamadı")
			self.assertAlmostEqual(rect.x, 0.1, places=5)
			self.assertAlmostEqual(rect.w, 0.5, places=5)
		finally:
			frappe.db.delete("Media Crop Override", {"parent": asset})
			frappe.db.delete("Media Crop Intent", {"asset": asset})
			frappe.db.delete("Media Asset", {"name": asset})
			frappe.db.commit()

	def test_docname_yazimi_okuma_tarafinda_ESLESMEZ(self) -> None:
		"""Karşı yön: tam docname yazılsaydı okuma tarafı onu BULAMAZDI.

		Bu, Data'ya çevirmenin neden yeterli olmadığını, ADIN da doğru
		olması gerektiğini sabitler.
		"""
		kisa_ad = self._politika_adi("product.image")
		docname = f"product.image:{kisa_ad}"
		sahte_niyet = {"overrides": [{"profile": docname, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}]}
		self.assertIsNone(crop_core.override_for(sahte_niyet, kisa_ad))

	@staticmethod
	def _politika_adi(slot: str) -> str:
		from tradehub_core.media.pipeline.image import render as render_mod

		return render_mod.load_profiles(slot)[0].profile_key

	@staticmethod
	def _asset_yarat() -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": "product.image",
				"media_type": "image",
				"state": "draft",
				"content_sha256": frappe.generate_hash(length=64),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		return doc.name


# ── 3. Kullanım deposu artık KALICI ──────────────────────────────────────


class KaliciKullanimDeposu(unittest.TestCase):
	"""B3'ün "ÖLÇÜLMEDİ" listesinin 1. ve 2. maddesi burada kapanıyor.

	`FrappeUsageBackend`in SQL'i bugüne kadar HİÇ koşmadı (DocType yoktu);
	ölçülmemiş olan alan adı eşlemesi, `on duplicate key update` davranışı ve
	epoch↔Datetime dönüşümüydü. Üçü de aşağıda gerçek tabloya karşı koşuyor.
	"""

	def setUp(self) -> None:
		self.asset = CropOverrideKirigi._asset_yarat()
		self.addCleanup(self._temizle)

	def _temizle(self) -> None:
		frappe.db.delete("Media Usage", {"asset": self.asset})
		frappe.db.delete("Media Asset", {"name": self.asset})
		frappe.db.commit()

	def test_depo_kalici_secildi(self) -> None:
		durum = usage_core.usage_store_status()
		self.assertTrue(durum["installed"], durum)
		self.assertTrue(durum["persistent"], durum)
		self.assertEqual(durum["reason"], "")
		self.assertIsInstance(usage_core.get_usage_store(), usage_core.PersistentUsageStore)

	def test_upsert_idempotent_ve_first_seen_korunuyor(self) -> None:
		depo = usage_core.get_usage_store()
		bag = usage_core.UsageLink(self.asset, "Listing", "L-1", "primary_image")
		depo.open_link(bag, 1000.0)
		depo.open_link(
			usage_core.UsageLink(self.asset, "Listing", "L-1", "primary_image"), 2000.0
		)
		frappe.db.commit()

		satirlar = frappe.db.sql(
			"select usage_key, first_seen, last_seen, is_open from `tabMedia Usage` where asset=%s",
			(self.asset,),
			as_dict=True,
		)
		self.assertEqual(len(satirlar), 1, f"uk_usage_quad idempotency'yi taşımıyor: {satirlar}")
		self.assertEqual(int(satirlar[0]["is_open"]), 1)
		# Epoch → Datetime dönüşümü: ilk görülme KORUNMUŞ, son görülme ilerlemiş.
		self.assertLess(satirlar[0]["first_seen"], satirlar[0]["last_seen"])

	def test_yaris_kosulunu_VERITABANI_cozuyor(self) -> None:
		"""İki süreç aynı bağı aynı anda yazarsa tek satır kalmalı.

		`PersistentUsageStore.open_link` önce `fetch` yapıyor — yani AYNI
		süreçte tekrarlanan yazma zaten tek satır üretir ve o test kısıt
		olmadan da yeşil kalır (ölçüldü: vacuity V1'de kırmızı OLMADI).
		Kısıtın gerçekten koruduğu şey YARIŞ: iki süreç de `fetch`te boş görüp
		ikisi de `insert` eder. Aşağıdaki iki çağrı tam olarak o durumu taklit
		ediyor — `fetch` atlanıyor, backend'e doğrudan iki insert gidiyor.
		"""
		backend = usage_core.FrappeUsageBackend()
		satir = {
			"asset": self.asset,
			"ref_doctype": "Listing",
			"ref_name": "L-YARIS",
			"ref_field": "primary_image",
			"usage_key": f"{self.asset}|Listing|L-YARIS|primary_image",
			"first_seen": 1000.0,
			"last_seen": 1000.0,
			"is_open": True,
		}
		backend.upsert(dict(satir))
		backend.upsert(dict(satir, last_seen=2000.0))
		frappe.db.commit()

		kayitlar = frappe.db.sql(
			"select name from `tabMedia Usage` where asset=%s and ref_name='L-YARIS'",
			(self.asset,),
		)
		self.assertEqual(
			len(kayitlar), 1,
			"aynı bağ iki satır açtı — uk_usage_quad kısıtı yok, `on duplicate key "
			"update` hiç tetiklenmiyor ve kapatılan bağ açık kopyası yüzünden hâlâ "
			"açık görünür",
		)

	def test_kapatma_satiri_SILMEZ(self) -> None:
		"""'Hiç kullanılmadı' ile 'kullanılıyordu, kaldırıldı' ayrımı."""
		depo = usage_core.get_usage_store()
		depo.open_link(
			usage_core.UsageLink(self.asset, "Listing", "L-2", "primary_image"), 1000.0
		)
		depo.close_link(self.asset, "Listing", "L-2", "primary_image", 3000.0)
		frappe.db.commit()

		satir = frappe.db.sql(
			"select is_open from `tabMedia Usage` where asset=%s", (self.asset,), as_dict=True
		)
		self.assertEqual(len(satir), 1, "kapatma satırı SİLDİ — öksüz kararı bozulur")
		self.assertEqual(int(satir[0]["is_open"]), 0)

	def test_surec_yeniden_baslasa_da_bag_duruyor(self) -> None:
		"""Kalıcılığın tanımı: yeni bir depo örneği aynı bağı görüyor mu."""
		usage_core.get_usage_store().open_link(
			usage_core.UsageLink(self.asset, "Listing", "L-3", "primary_image"), 1000.0
		)
		frappe.db.commit()
		yeni_depo = usage_core.PersistentUsageStore(usage_core.FrappeUsageBackend())
		self.assertEqual(len(yeni_depo.links_of(self.asset)), 1)


# ── 4. Sürüm geçişi (T-064) ──────────────────────────────────────────────


class SurumGecisi(unittest.TestCase):
	"""`Media Version` + `active_version` — geçişin ölçülebilir hâli."""

	def setUp(self) -> None:
		self.asset = CropOverrideKirigi._asset_yarat()
		self.addCleanup(self._temizle)

	def _temizle(self) -> None:
		frappe.db.set_value("Media Asset", self.asset, "active_version", None)
		frappe.db.delete("Media Version", {"asset": self.asset})
		frappe.db.delete("Media Asset", {"name": self.asset})
		frappe.db.commit()

	def _surum(self, etiket: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Media Version",
				"asset": self.asset,
				"version_hash": frappe.generate_hash(length=64),
				"engine_version": etiket,
			}
		).insert(ignore_permissions=True)
		return doc.name

	def test_iki_surum_ayni_anda_var_olabiliyor(self) -> None:
		"""Geçişin ön şartı: eski sürüm, yeni sürüm üretilirken YAŞIYOR."""
		eski = self._surum("pillow-11.3.0")
		yeni = self._surum("pillow-11.4.0")
		frappe.db.commit()
		self.assertNotEqual(eski, yeni)
		self.assertEqual(frappe.db.count("Media Version", {"asset": self.asset}), 2)

	def test_gecis_tek_transactionda_tutarli(self) -> None:
		eski = self._surum("pillow-11.3.0")
		frappe.db.set_value("Media Version", eski, "is_active", 1)
		frappe.db.set_value("Media Asset", self.asset, "active_version", eski)
		yeni = self._surum("pillow-11.4.0")
		frappe.db.commit()

		# Faz 3 — geçiş
		frappe.db.sql("update `tabMedia Version` set is_active=0 where asset=%s", (self.asset,))
		frappe.db.sql("update `tabMedia Version` set is_active=1 where name=%s", (yeni,))
		frappe.db.set_value("Media Asset", self.asset, "active_version", yeni)
		frappe.db.commit()

		self.assertEqual(
			frappe.db.get_value("Media Asset", self.asset, "active_version"), yeni
		)
		aktifler = frappe.db.sql(
			"select name from `tabMedia Version` where asset=%s and is_active=1", (self.asset,)
		)
		self.assertEqual([r[0] for r in aktifler], [yeni], "aynı anda iki yayın sürümü")
		# Eski sürüm SİLİNMEDİ — geçiş boyunca erişilebilir.
		self.assertTrue(frappe.db.exists("Media Version", eski))

	def test_celiskili_is_active_REDDEDILIYOR(self) -> None:
		"""Denormalize kopya sessizce eskimemeli: çelişki yazma anında düşer."""
		eski = self._surum("pillow-11.3.0")
		frappe.db.set_value("Media Asset", self.asset, "active_version", eski)
		frappe.db.commit()
		yeni_doc = frappe.get_doc(
			{
				"doctype": "Media Version",
				"asset": self.asset,
				"version_hash": frappe.generate_hash(length=64),
				"engine_version": "pillow-11.4.0",
				"is_active": 1,
			}
		)
		with self.assertRaises(frappe.ValidationError):
			yeni_doc.insert(ignore_permissions=True)


# ── 5. Kiracı izolasyonu ─────────────────────────────────────────────────


class KiraciIzolasyonu(unittest.TestCase):
	"""Yeni iki DocType için `permission_query_conditions` + `has_permission`.

	Bugün bu depoda 4 izolasyon açığı bulundu; yeni DocType kurup kancasını
	yazmamak beşincisini doğururdu.
	"""

	def test_hooks_kaydi_var(self) -> None:
		from tradehub_core import hooks

		for dt in ("Media Usage", "Media Version"):
			self.assertIn(dt, hooks.permission_query_conditions, f"{dt} query kancası YOK")
			self.assertIn(dt, hooks.has_permission, f"{dt} has_permission kancası YOK")

	def test_guest_hicbir_satir_gormez(self) -> None:
		from tradehub_core import permissions as perm

		self.assertEqual(perm.media_usage_query_conditions("Guest"), "1=0")
		self.assertEqual(perm.media_version_query_conditions("Guest"), "1=0")
		self.assertEqual(perm.media_usage_query_conditions(None), "1=0")
		self.assertEqual(perm.media_version_query_conditions(None), "1=0")

	def test_saticisiz_kullanici_hicbir_satir_gormez(self) -> None:
		from tradehub_core import permissions as perm

		# Yeni açılmış, satıcı profili olmayan bir kullanıcı.
		self.assertEqual(perm.media_usage_query_conditions("olmayan@ornek.test"), "1=0")
		self.assertEqual(perm.media_version_query_conditions("olmayan@ornek.test"), "1=0")

	def test_satici_YAZAMAZ(self) -> None:
		"""Bağı hat yazar, sürümü geçiş protokolü — satıcı ikisini de yazamaz."""
		from tradehub_core import permissions as perm

		for fn in (perm.media_usage_has_permission, perm.media_version_has_permission):
			for ptype in ("write", "create", "delete"):
				self.assertFalse(
					fn(None, ptype, "olmayan@ornek.test"),
					f"{fn.__name__} {ptype} izni veriyor",
				)

	def test_zincir_asset_uzerinden_kuruluyor(self) -> None:
		"""Denormalize satıcı kolonu YOK — sorgu Asset alt sorgusuna zincirlenmeli."""
		from tradehub_core import permissions as perm

		# Guest/satıcısız kullanıcı "1=0" döndürdüğü için zincirin kendisini
		# alt sorgu üreticisinden ölçüyoruz — kiracı sınırı buradan geliyor.
		metin = perm._media_asset_owner_subquery("ASP-TEST")
		self.assertIn("tabMedia Asset", metin)
		self.assertIn("owner_seller", metin)
		# Ve iki kanca da bu alt sorguyu kullanıyor mu: kaynak metinde ara.
		import inspect

		for fn in (perm.media_usage_query_conditions, perm.media_version_query_conditions):
			kaynak = inspect.getsource(fn)
			self.assertIn("_media_asset_owner_subquery", kaynak, fn.__name__)
			self.assertNotIn("owner_seller`", kaynak,
							 f"{fn.__name__} denormalize satıcı kolonu okuyor")


# ── 6. `/metrics` yetkilendirmesi ────────────────────────────────────────


class _SahteIstek:
	def __init__(self, auth: str = "") -> None:
		self.headers = {"Authorization": auth} if auth else {}


class MetricsYetkilendirmesi(unittest.TestCase):
	"""Token kapısı — sabit zamanlı, fail-closed, `?token=` yok."""

	def setUp(self) -> None:
		self._eski_istek = getattr(frappe.local, "request", None)
		self.addCleanup(self._geri_al)

	def _geri_al(self) -> None:
		frappe.local.request = self._eski_istek

	def _token(self) -> str:
		return str(frappe.conf.get(obs.TOKEN_KEY) or "")

	def test_token_yapilandirilmis(self) -> None:
		"""Yama sırrı üretmiş olmalı; yoksa uç kullanılamaz (ve öyle KALMALI)."""
		self.assertTrue(self._token(), "site_config.media_metrics_token YOK")

	def test_basliksiz_istek_reddediliyor(self) -> None:
		frappe.local.request = _SahteIstek()
		self.assertFalse(obs._token_ok())

	def test_yanlis_token_reddediliyor(self) -> None:
		frappe.local.request = _SahteIstek("Bearer " + "0" * 64)
		self.assertFalse(obs._token_ok())

	def test_dogru_token_kabul_ediliyor(self) -> None:
		frappe.local.request = _SahteIstek("Bearer " + self._token())
		self.assertTrue(obs._token_ok())

	def test_yanlis_sema_reddediliyor(self) -> None:
		"""`Basic <token>` geçmemeli — şema kontrolü de kapının parçası."""
		frappe.local.request = _SahteIstek("Basic " + self._token())
		self.assertFalse(obs._token_ok())

	def test_authorize_tokensiz_403(self) -> None:
		frappe.local.request = _SahteIstek()
		eski_kullanici = frappe.session.user
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				obs._authorize()
		finally:
			frappe.set_user(eski_kullanici)

	def test_authorize_dogru_tokenla_gecer(self) -> None:
		frappe.local.request = _SahteIstek("Bearer " + self._token())
		self.assertEqual(obs._authorize(), "bearer")

	def test_content_type_charset_tekrarlanmiyor(self) -> None:
		self.assertEqual(
			obs._mimetype("text/plain; version=0.0.4; charset=utf-8"),
			"text/plain; version=0.0.4",
		)


# ── 7. Ölçüm noktaları GERÇEKTEN bağlı ───────────────────────────────────


class OlcumNoktalari(unittest.TestCase):
	def test_hooks_kaydi_var(self) -> None:
		from tradehub_core import hooks

		self.assertIn(
			"tradehub_core.api.observability.install_instrumentation",
			list(hooks.after_migrate),
			"after_migrate kaydı YOK — hiçbir metrik toplanmaz",
		)
		self.assertIn(
			"tradehub_core.api.observability.after_request_write_shard",
			list(hooks.after_request),
			"after_request kaydı YOK — web sürecinin sayaçları /metrics'e ulaşmaz",
		)
		self.assertIn(
			"tradehub_core.api.observability.authenticate_metrics_scrape",
			list(hooks.auth_hooks),
			"auth_hooks kaydı YOK — token taşıyan istek 401'de kesilir",
		)

	def test_bench_ortaminda_10_noktanin_10u_bagli(self) -> None:
		obs.ensure_instrumented()
		durum = obs.ensure_instrumented.__globals__["instrument"].durum()
		self.assertEqual(durum["points_total"], 10)
		self.assertEqual(durum["points_bound"], 10, durum)

	def test_sahipsiz_metrik_yok(self) -> None:
		from tradehub_core.media.pipeline.observability import instrument

		kapsam = instrument.metrik_kapsami()
		self.assertEqual(kapsam["unaccounted"], [], kapsam)

	def test_alarm_kurallari_tanimli_metriklere_bagli(self) -> None:
		"""Sessiz kopma sigortası: metrik adı değişip kural güncellenmezse
		Prometheus hata VERMEZ, kural hiç ateşlenmez, panel boş kalır."""
		from tradehub_core.media.pipeline.observability import alerts

		rapor = alerts.dogrula()
		self.assertEqual(rapor["unknown_metrics"], [], rapor)
		self.assertEqual(rapor["duplicate_names"], [], rapor)
		self.assertEqual(rapor["alerts"], 16)


if __name__ == "__main__":  # pragma: no cover
	unittest.main(verbosity=2)
