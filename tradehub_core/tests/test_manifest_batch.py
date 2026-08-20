# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""`api.media_manifest.manifest_batch` testleri — T-083 toplu DOSYA manifesti.

Bu dosyanın ASIL konusu KİRACI İZOLASYONU: uç, panelin dosya başına 2 REST
sorgusunu tek çağrıda toplarken izin katmanını (hooks'taki
`media_asset_query_conditions` / `media_rendition_query_conditions` +
Frappe'nin File izin süzgeci) BYPASS etmemeli. Testler bunu iki bağımsız
satıcı kurarak kanıtlıyor ve her izolasyon testinin yanına POZİTİF kontrol
koyuyor — sahibi aynı veriyi GERÇEKTEN alabiliyor ki boşluk süzgecin eseri
olsun, kırık fixture'ın değil.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_manifest_batch
"""

from __future__ import annotations

import hashlib
import json

import frappe

from tradehub_core.api import media_manifest
from tradehub_core.tests.test_media_access_level import MediaAccessLevelTestBase

#: Gerçek slot politikasının profil merdiveninden adlar (`product-image.json`).
PROFIL_KUCUK = "w384"
PROFIL_BUYUK = "w768"


class ManifestBatchTestBase(MediaAccessLevelTestBase):
	"""İki bağımsız satıcı: kullanıcı + public/özel dosya + varlık + türevler."""

	def _make_store_user(self, store: str, tag: str) -> str:
		suffix = frappe.generate_hash(length=8)
		email = f"manifest-batch-{tag}-{suffix}@test.local"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Manifest Batch",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		# `frappe.get_list` rol iznine bakar: Media Asset/Rendition okuma izni
		# "Seller" rolünde. Rol OLMADAN test, izolasyonu değil rol eksikliğini
		# ölçerdi.
		user.add_roles("Seller")
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("User", user.name))
		frappe.db.set_value("Admin Seller Profile", store, "user", email, update_modified=False)
		frappe.db.commit()
		self.addCleanup(lambda: frappe.cache().delete_value(f"tradehub:seller_for_user:{email}"))
		frappe.cache().delete_value(f"tradehub:seller_for_user:{email}")
		return email

	def _make_asset(self, store: str, file_name: str, email: str, tag: str) -> str:
		varlik = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": "product.image",
				"media_type": "image",
				"state": "ready",
				"owner_seller": store,
				"source_file": file_name,
				"content_sha256": hashlib.sha256(
					f"{tag}-{frappe.generate_hash(length=8)}".encode()
				).hexdigest(),
			}
		).insert(ignore_permissions=True)
		# Rol izni `if_owner` taşıyor; fixture'ı Administrator kurduğu için
		# sahipliği satıcıya devret — üründe de varlığı satıcının akışı yaratır.
		frappe.db.set_value("Media Asset", varlik.name, "owner", email, update_modified=False)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("Media Asset", varlik.name))
		return varlik.name

	def _make_renditions(self, asset: str) -> list[str]:
		"""2 türev: biri fayda kapısını geçmiş, biri GEÇMEMİŞ.

		Kapıyı geçmeyen de yanıtta OLMALI — panel üretim envanteri gösterir,
		vitrin manifesti değil (`manifest_batch` docstring'i).
		"""
		urls: list[str] = []
		for profil, genislik, gecti in ((PROFIL_KUCUK, 384, 1), (PROFIL_BUYUK, 768, 0)):
			url = f"/files/media/{asset}/{profil}-{genislik}.webp"
			turev = frappe.get_doc(
				{
					"doctype": "Media Rendition",
					"asset": asset,
					"profile": profil,
					"rendition_key": f"{asset}:{profil}:webp",
					"width": genislik,
					"height": genislik,
					"format": "webp",
					"file_url": url,
					"bytes": 1024,
					"ssim": 0.97,
					"generation": "lazy",
					"benefit_gate_passed": gecti,
				}
			).insert(ignore_permissions=True)
			self.addCleanup(lambda ad=turev.name: self._delete_and_commit("Media Rendition", ad))
			urls.append(url)
		frappe.db.commit()
		return urls

	def _kur_satici(self, tag: str) -> frappe._dict:
		store = self._make_seller(tag)
		email = self._make_store_user(store, tag)

		public_file = self._make_public_file(tag)
		frappe.db.set_value("File", public_file.name, "owner", email, update_modified=False)
		private_file = self._make_private_file(tag)
		frappe.db.set_value("File", private_file.name, "owner", email, update_modified=False)
		frappe.db.commit()

		public_asset = self._make_asset(store, public_file.name, email, f"{tag}-pub")
		private_asset = self._make_asset(store, private_file.name, email, f"{tag}-prv")
		return frappe._dict(
			store=store,
			email=email,
			public_file=public_file.name,
			public_url=public_file.file_url,
			public_asset=public_asset,
			public_rendition_urls=self._make_renditions(public_asset),
			private_file=private_file.name,
			private_url=private_file.file_url,
			private_asset=private_asset,
			private_rendition_urls=self._make_renditions(private_asset),
		)

	def _make_duplicate_file(self, file_url: str, email: str) -> str:
		"""Aynı `file_url`'e İKİNCİ `File` satırı.

		DEV'de ölçülen gerçeklik (69 raporu §4/§7.1): aynı adreste 5+ mükerrer
		satır var ve varlık bunlardan yalnız birine bağlı. Fixture bu
		mükerrerliği üretir ki köprü gerçek koşulda sınansın.
		"""
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_url.rsplit("/", 1)[-1],
				"file_url": file_url,
				"is_private": 0,
			}
		)
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_duplicate_entry_error = True
		doc.insert(ignore_permissions=True)
		frappe.db.set_value("File", doc.name, "owner", email, update_modified=False)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("File", doc.name))
		return doc.name

	def setUp(self):
		super().setUp()
		self.a = self._kur_satici("mb-a")
		self.b = self._kur_satici("mb-b")

	def _as_seller(self, satici: frappe._dict) -> None:
		frappe.set_user(satici.email)


class ManifestBatchShapeTests(ManifestBatchTestBase):
	def test_n_adres_tek_cagride_doner(self):
		"""2 dosya, TEK çağrı → 2 manifest. Eski akış bunun için 4 istek atardı."""
		self._as_seller(self.a)

		sonuc = media_manifest.manifest_batch([self.a.public_file, self.a.private_file])

		self.assertEqual(sonuc["requested"], 2)
		self.assertEqual(sonuc["returned"], 2)
		self.assertEqual(set(sonuc["manifests"]), {self.a.public_file, self.a.private_file})

		man = sonuc["manifests"][self.a.public_file]
		self.assertEqual(man["file"], self.a.public_file)
		self.assertEqual(man["file_url"], self.a.public_url)
		self.assertEqual(man["assets"], [self.a.public_asset])
		self.assertEqual(
			[t["file_url"] for t in man["renditions"]],
			self.a.public_rendition_urls,  # genişliğe göre artan — fixture sırası
		)

	def test_fayda_kapisini_gecmeyen_turev_de_envanterde(self):
		"""Panel üretim ENVANTERİ gösterir: gate=0 satır gizlenmez, alanla gelir."""
		self._as_seller(self.a)

		man = media_manifest.manifest_batch([self.a.public_file])["manifests"][self.a.public_file]

		kapida = [t for t in man["renditions"] if not t["benefit_gate_passed"]]
		self.assertEqual(len(kapida), 1)
		self.assertEqual(kapida[0]["profile"], PROFIL_BUYUK)

	def test_rendition_satiri_panel_sozlesmesini_tasir(self):
		"""FE eşlemesinin okuduğu alanlar (`useMediaRenditions.js`) eksiksiz."""
		self._as_seller(self.a)

		man = media_manifest.manifest_batch([self.a.public_file])["manifests"][self.a.public_file]

		beklenen = {
			"name",
			"asset",
			"profile",
			"width",
			"height",
			"format",
			"file_url",
			"bytes",
			"ssim",
			"generation",
			"benefit_gate_passed",
		}
		self.assertTrue(man["renditions"], "türev listesi boş — fixture bağlanmadı")
		self.assertLessEqual(beklenen, set(man["renditions"][0]))

	def test_adres_docname_ya_da_file_url_ile_cozulur(self):
		"""Harita İSTENEN dizgeyle anahtarlanır; docname da adres de çözülür."""
		self._as_seller(self.a)

		sonuc = media_manifest.manifest_batch([self.a.public_url])

		man = sonuc["manifests"][self.a.public_url]
		self.assertIsNotNone(man)
		self.assertEqual(man["file"], self.a.public_file)
		self.assertEqual([t["file_url"] for t in man["renditions"]], self.a.public_rendition_urls)

	def test_bos_liste_bos_harita(self):
		"""Boş girdi bir HATA değil: soru yoksa cevap da yok."""
		self._as_seller(self.a)

		for girdi in ([], None, "", "[]"):
			sonuc = media_manifest.manifest_batch(girdi)
			self.assertEqual(sonuc["manifests"], {})
			self.assertEqual(sonuc["requested"], 0)
			self.assertEqual(sonuc["returned"], 0)

	def test_tekrarlanan_adres_tekillestirilir(self):
		self._as_seller(self.a)

		sonuc = media_manifest.manifest_batch([self.a.public_file, self.a.public_file])

		self.assertEqual(sonuc["requested"], 1)
		self.assertEqual(list(sonuc["manifests"]), [self.a.public_file])


class ManifestBatchLimitTests(ManifestBatchTestBase):
	def test_tavan_asimi_reddedilir(self):
		"""`FILE_BATCH_MAX` üstü KIRPILMAZ, reddedilir — panel hatası sesli kırılır."""
		self._as_seller(self.a)
		adresler = [f"MB-TAVAN-{i:04d}" for i in range(media_manifest.FILE_BATCH_MAX + 1)]

		with self.assertRaises(frappe.ValidationError):
			media_manifest.manifest_batch(adresler)

	def test_tavan_tam_dolu_istek_kabul_edilir(self):
		"""Sınırın KENDİSİ geçerli — off-by-one tavanı 99'a düşürmesin."""
		self._as_seller(self.a)
		adresler = [f"MB-TAM-{i:04d}" for i in range(media_manifest.FILE_BATCH_MAX)]

		sonuc = media_manifest.manifest_batch(adresler)

		self.assertEqual(sonuc["requested"], media_manifest.FILE_BATCH_MAX)
		# Uydurma adresler çözülmez ama istek REDDEDİLMEZ.
		self.assertEqual(sonuc["returned"], 0)

	def test_liste_olmayan_girdi_reddedilir(self):
		self._as_seller(self.a)

		with self.assertRaises(frappe.ValidationError):
			media_manifest.manifest_batch("bu-bir-json-dizisi-degil")

	def test_guest_reddedilir(self):
		"""Uç panel içindir; vitrinin misafir akışı `get_manifest_batch`te kalır."""
		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			media_manifest.manifest_batch([self.a.public_file])


class ManifestBatchIsolationTests(ManifestBatchTestBase):
	"""Satıcı A, satıcı B'nin medya izlerini bu uçtan OKUYAMAZ."""

	def test_baskasinin_ozel_dosyasi_none_doner(self):
		"""A → B'nin özel dosyası: `None`. Olmayan dosyayla AYNI gövde —
		"var ama bakamazsın" (403) bir adresin varlığını doğrulardı."""
		self._as_seller(self.a)

		sonuc = media_manifest.manifest_batch(
			[self.b.private_file, self.b.private_url, "FILE-BOYLE-BIR-DOSYA-YOK"]
		)

		self.assertIsNone(sonuc["manifests"][self.b.private_file])
		self.assertIsNone(sonuc["manifests"][self.b.private_url])
		self.assertIsNone(sonuc["manifests"]["FILE-BOYLE-BIR-DOSYA-YOK"])
		self.assertEqual(sonuc["returned"], 0)

		# Pozitif kontrol: sahibi AYNI adresi çözebiliyor — yukarıdaki `None`
		# süzgecin eseri, kırık fixture'ın değil.
		self._as_seller(self.b)
		kendi = media_manifest.manifest_batch([self.b.private_file])
		self.assertEqual(
			[t["file_url"] for t in kendi["manifests"][self.b.private_file]["renditions"]],
			self.b.private_rendition_urls,
		)

	def test_baskasinin_public_dosyasinin_varligi_ve_turevleri_sizmiyor(self):
		"""Public dosyanın KENDİSİ herkese açık; ama varlık kaydı ve türev
		adresleri B'nin üretim envanteridir ve A'ya görünmez."""
		self._as_seller(self.a)

		sonuc = media_manifest.manifest_batch([self.b.public_file])

		man = sonuc["manifests"][self.b.public_file]
		if man is not None:
			# File katmanı public dosyayı çözebilir; kiracı sınırı varlık
			# katmanında tutmalı: boş envanter, tek bir türev adresi yok.
			self.assertEqual(man["assets"], [])
			self.assertEqual(man["renditions"], [])

		# Sızıntının SERT kanıtı: B'nin hiçbir kimliği gövdenin hiçbir
		# köşesinde geçmiyor (alan alan gezmek yerine tüm gövde taranır —
		# yarın eklenecek bir alan da bu ağa takılsın).
		govde = json.dumps(sonuc["manifests"], default=str)
		self.assertNotIn(self.b.public_asset, govde)
		for url in self.b.public_rendition_urls:
			self.assertNotIn(url, govde)

		# Pozitif kontrol: sahibi aynı dosyanın TAM envanterini alıyor.
		self._as_seller(self.b)
		kendi = media_manifest.manifest_batch([self.b.public_file])
		self.assertEqual(kendi["manifests"][self.b.public_file]["assets"], [self.b.public_asset])
		self.assertEqual(
			[t["file_url"] for t in kendi["manifests"][self.b.public_file]["renditions"]],
			self.b.public_rendition_urls,
		)

	def test_karisik_istekte_yalniz_kendininki_dolu(self):
		"""Listeleme senaryosu: A kendi + B'nin dosyalarını TEK istekte sorarsa
		yalnız kendi manifestlerini alır; istek patlamaz (kısmi başarı)."""
		self._as_seller(self.a)

		sonuc = media_manifest.manifest_batch([self.a.public_file, self.b.public_file, self.b.private_file])

		self.assertEqual(
			[t["file_url"] for t in sonuc["manifests"][self.a.public_file]["renditions"]],
			self.a.public_rendition_urls,
		)
		self.assertIsNone(sonuc["manifests"][self.b.private_file])
		govde = json.dumps(sonuc["manifests"], default=str)
		self.assertNotIn(self.b.private_asset, govde)
		for url in self.b.private_rendition_urls + self.b.public_rendition_urls:
			self.assertNotIn(url, govde)


class ManifestBatchDuplicateFileTests(ManifestBatchTestBase):
	"""69 raporu §7.1 kör noktası: mükerrer `File` satırları.

	Varlık, mükerrer satırlardan yalnız BİRİNE bağlı (`source_file` Link);
	kullanıcı ise elindeki HERHANGİ bir docname ile sorar. Docname join'i
	yazı-tura görür — köprü (`_mukerrer_dosya_koprusu`) `file_url` üzerinden
	buluşturur. Bu sınıf o köprüyü ölçer; köprü geri alınırsa KIRMIZI.
	"""

	def test_mukerrer_docname_ile_ayni_manifest_doner(self):
		"""Varlığın bağlı OLMADIĞI mükerrer docname de tam envanteri döner.

		İki AYRI çağrı bilinçli: asıl docname aynı isteğe konursa emniyet
		yedeği ("çözülen satır köprüde kalır") mükerrerin imdadına yetişir ve
		test, köprü kapalıyken bile yeşil kalırdı (ölçüldü — vacuity denemesi
		1'de yakalandı). Panel gerçekte de tek docname yollar.
		"""
		mukerrer = self._make_duplicate_file(self.a.public_url, self.a.email)
		self.assertNotEqual(mukerrer, self.a.public_file)  # gerçekten ikinci satır
		self._as_seller(self.a)

		asil = media_manifest.manifest_batch([self.a.public_file])["manifests"][self.a.public_file]
		kopya = media_manifest.manifest_batch([mukerrer])["manifests"][mukerrer]

		self.assertIsNotNone(kopya)
		# Pozitif kontrol içeride: asıl docname zaten dolu (fixture sağlam) —
		# kopya da AYNI envanteri taşımalı, "boru hattında yok" değil.
		self.assertEqual(asil["assets"], [self.a.public_asset])
		self.assertEqual(kopya["assets"], asil["assets"])
		self.assertEqual(
			[t["name"] for t in kopya["renditions"]],
			[t["name"] for t in asil["renditions"]],
		)
		self.assertEqual(
			[t["file_url"] for t in kopya["renditions"]], self.a.public_rendition_urls
		)
		# Anahtar İSTENEN dizge kalır; gövde hangi satırın çözüldüğünü söyler.
		self.assertEqual(kopya["file"], mukerrer)
		self.assertEqual(kopya["file_url"], self.a.public_url)

	def test_mukerrer_satir_varken_adresle_sorgu_da_calisir(self):
		"""69 raporu §7.1 yüz-1: adres çözümü mükerrerlerden RASTGELE birini
		tutuyordu ve varlık başka satırdaysa envanter boş dönüyordu."""
		# Not: adres çözümünün mükerrerlerden HANGİ satırı tuttuğu sırasızdır;
		# köprüsüz dünyada bu test şansla yeşil kalabilir. Deterministik
		# KIRMIZI, docname testindedir — bu test adres yüzünün düz doğruluk
		# özelliğini sabitler.
		for _i in range(3):
			self._make_duplicate_file(self.a.public_url, self.a.email)
		self._as_seller(self.a)

		sonuc = media_manifest.manifest_batch([self.a.public_url])

		man = sonuc["manifests"][self.a.public_url]
		self.assertIsNotNone(man)
		self.assertEqual(man["assets"], [self.a.public_asset])
		self.assertEqual(
			[t["file_url"] for t in man["renditions"]], self.a.public_rendition_urls
		)

	def test_mukerrer_kopru_kiraci_sinirini_acmaz(self):
		"""Köprü `get_all` kullanıyor; kiracı kapısı varlık halkasında durmalı.

		A, B'nin public dosyasının MÜKERRER satırını (sahibi A olsa bile)
		sorduğunda B'nin varlık/türev envanteri yine sızmamalı.
		"""
		mukerrer_b = self._make_duplicate_file(self.b.public_url, self.a.email)
		self._as_seller(self.a)

		sonuc = media_manifest.manifest_batch([mukerrer_b])

		man = sonuc["manifests"][mukerrer_b]
		self.assertIsNotNone(man)  # satır A'nın — çözülür
		self.assertEqual(man["assets"], [])
		self.assertEqual(man["renditions"], [])
		govde = json.dumps(sonuc["manifests"], default=str)
		self.assertNotIn(self.b.public_asset, govde)
		for url in self.b.public_rendition_urls:
			self.assertNotIn(url, govde)

		# Pozitif kontrol: B aynı mükerrer docname ile TAM envanteri alır —
		# köprü, sahibin kendi varlığını mükerrer satırın arkasından çıkarır.
		self._as_seller(self.b)
		kendi = media_manifest.manifest_batch([mukerrer_b])
		self.assertEqual(kendi["manifests"][mukerrer_b]["assets"], [self.b.public_asset])
		self.assertEqual(
			[t["file_url"] for t in kendi["manifests"][mukerrer_b]["renditions"]],
			self.b.public_rendition_urls,
		)
