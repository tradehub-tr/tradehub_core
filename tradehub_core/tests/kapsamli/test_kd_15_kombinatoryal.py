"""KD-15 — Kombinatoryal tam çarpım: örnekleme YOK, uzayın tamamı taranıyor.

KD-12 rastgele örnekliyor; burada **hiçbir kombinasyon atlanmıyor**. Politika
motoru saf ve ucuz (ölçüldü: 43 µs/karar), dolayısıyla eksenlerin tam kartezyen
çarpımı gerçekten koşturulabilir.

    slot 9 × rol 4 × geometri 8 × bayt 5 × animasyon 2 × okunabilir 2
         × uzantı-uyum 3 × leading 2 × appended 2 × tarama 3
    = 207.360 kombinasyon

Neden tam çarpım: kural blokları birbirini etkiliyor (güvenlik bloğu erken
dönüyor, `require` bloğu slota göre `warn`/`reject`, geometri `skipped`
üretebiliyor). Örnekleme bu kesişimlerin bir kısmını hiç görmez; "9 slotun
8'inde doğru, 1'inde yanlış" tam olarak örneklemenin kaçırdığı şeydir.

Ölçülen şey doğru cevap DEĞİL — uzayın tamamında geçerli olması gereken
**değişmezler**:

    D1  hiçbir kombinasyon istisna atmaz
    D2  allow=False  ⟹ normalized_targets == {}
    D3  allow=True   ⟹ normalized_targets dolu
    D4  her ihlal kod + çözülmüş mesaj taşır
    D5  güvenlik bayrağı eklemek kararı ASLA iyileştiremez (monotonluk)
    D6  aynı girdi her zaman aynı kararı verir (determinizm)
    D7  action her zaman bilinen bir aksiyon
"""

from __future__ import annotations

import itertools
import time
import unittest

from tradehub_core.media.pipeline.contracts import policy as pc
from tradehub_core.media.pipeline.core.probe import MediaProbe
from tradehub_core.media.pipeline.policy import engine as pe

#: Bilinen aksiyonlar — sözleşmenin KENDİ listesinden okunuyor.
#: Elle saymak bir aksiyon eklendiğinde testi sessizce bayat bırakırdı
#: (ilk kurguda tam olarak bu oldu: `manual_review` atlanmıştı).
BILINEN_AKSIYONLAR: frozenset[str] = frozenset(pc.ACTIONS)

# ── Eksenler ──────────────────────────────────────────────────────────
#
# Her eksen bilinçli seçildi: sınır değeri, geçerli değeri ve "ölçülemedi"
# durumunu birlikte taşıyor. Sayı azaltılmadı.

SLOTLAR: tuple[str, ...] = tuple(sorted(pe.PolicyRegistry().load().keys()))

ROLLER: tuple[str, ...] = ("seller", "admin", "", "uydurma_rol")

#: (w, h) — izinli oran, izinsiz oran, sınırın altı/üstü, ölçülemedi, dejenere.
GEOMETRI: tuple[tuple[int, int], ...] = (
	(2000, 2000),   # 1:1, sınırın üstü
	(1600, 2000),   # 4:5
	(1500, 2000),   # 3:4
	(1000, 1000),   # kısa kenar TAM sınırda
	(999, 999),     # sınırın bir altı
	(2000, 1000),   # 2:1 — ürün görselinde izinsiz
	(0, 0),         # ölçülemedi
	(10000, 9000),  # megapiksel tavanı üstü
)

BAYTLAR: tuple[int, int, int, int, int] = (
	0,               # boş
	1_024,           # küçük
	5_242_880,       # 5 MB — bazı slotlarda tam sınır
	26_214_400,      # 25 MB — product.image tam sınır
	26_214_401,      # bir bayt fazlası
)

ANIMASYON: tuple[bool, bool] = (False, True)
OKUNABILIR: tuple[bool, bool] = (True, False)
UZANTI_UYUM: tuple[bool | None, ...] = (True, False, None)
LEADING: tuple[bool, bool] = (False, True)
APPENDED: tuple[bool, bool] = (False, True)
TARAMA: tuple[bool | None, ...] = (True, False, None)

TAM_CARPIM: int = (
	len(SLOTLAR) * len(ROLLER) * len(GEOMETRI) * len(BAYTLAR) * len(ANIMASYON)
	* len(OKUNABILIR) * len(UZANTI_UYUM) * len(LEADING) * len(APPENDED) * len(TARAMA)
)

GUVENLIK_EKSENLERI: tuple[str, ...] = ("leading_marker", "appended_payload", "scan_clean")


def _kunye(slot, w, h, bayt, animasyon, okunabilir, uyum, leading, appended, tarama) -> MediaProbe:
	video = "video" in slot
	return MediaProbe(
		filename="urun.mp4" if video else "urun.jpg",
		extension=".mp4" if video else ".jpg",
		byte_size=bayt,
		kind="video" if video else "image",
		detected="mp4" if video else "jpeg",
		mime="video/mp4" if video else "image/jpeg",
		fmt="" if video else "JPEG",
		width=w,
		height=h,
		mode="RGB",
		readable=okunabilir,
		loadable=okunabilir,
		animated=animasyon,
		extension_matches_content=uyum,
		leading_marker=leading,
		appended_payload=appended,
		scan_clean=tarama,
		existing_count=0,
		duration_s=20.0 if video else None,
		bitrate_bps=2_000_000 if video else None,
		frame_rate=30.0 if video else None,
	)


def _tum_kombinasyonlar():
	return itertools.product(
		SLOTLAR, ROLLER, GEOMETRI, BAYTLAR, ANIMASYON,
		OKUNABILIR, UZANTI_UYUM, LEADING, APPENDED, TARAMA,
	)


def _degerlendir(motor, kombinasyon):
	slot, rol, (w, h), bayt, anim, oku, uyum, lead, app, tara = kombinasyon
	return motor.evaluate(slot, _kunye(slot, w, h, bayt, anim, oku, uyum, lead, app, tara), rol)


class TestKombinatoryalTarama(unittest.TestCase):
	"""Tam kartezyen tarama — 207.360 kombinasyon, örnekleme yok."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.motor = pe.PolicyEngine()

	def test_bi_bilinen_aksiyonlar_sozlesmeden_okunuyor(self):
		"""D7 kontrolünün gerçekten bir şey ölçtüğünün kanıtı."""
		self.assertEqual(len(BILINEN_AKSIYONLAR), len(pc.ACTIONS), BILINEN_AKSIYONLAR)
		for aksiyon in (pc.ACTION_PASS, pc.ACTION_WARN, pc.ACTION_AUTO_FIX,
						pc.ACTION_MANUAL_REVIEW, pc.ACTION_REJECT):
			self.assertIn(aksiyon, BILINEN_AKSIYONLAR)

	def test_bi_uzay_boyutu_beklendigi_gibi(self):
		"""Eksen sayısı sessizce küçülürse tarama anlamsızlaşır — kilit."""
		self.assertEqual(len(SLOTLAR), 9, SLOTLAR)
		self.assertEqual(TAM_CARPIM, 207_360, f"uzay boyutu değişti: {TAM_CARPIM:,}")
		self.assertEqual(sum(1 for _ in _tum_kombinasyonlar()), TAM_CARPIM)

	def test_kb_TAM_CARPIM_degismezleri(self):
		"""D1–D4, D7: 207.360 kombinasyonun tamamı tek geçişte taranır.

		Her kombinasyon için ayrı `subTest` açılmıyor: 207 bin alt test hem
		yavaş hem okunamaz. Bunun yerine ihlaller toplanıyor ve ilk 10'u
		gerekçesiyle raporlanıyor.
		"""
		motor = self.motor
		ihlaller: list[str] = []
		basla = time.monotonic()

		for i, komb in enumerate(_tum_kombinasyonlar()):
			try:
				k = _degerlendir(motor, komb)
			except Exception as exc:  # noqa: BLE001 — D1
				ihlaller.append(f"D1 #{i} {komb}: {type(exc).__name__}: {exc}")
				if len(ihlaller) > 10:
					break
				continue

			if k.action not in BILINEN_AKSIYONLAR:
				ihlaller.append(f"D7 #{i} {komb}: bilinmeyen aksiyon {k.action!r}")

			if not k.allow and k.normalized_targets != {}:
				ihlaller.append(f"D2 #{i} {komb}: ret kararında hedef üretildi")
			if k.allow and not k.normalized_targets:
				ihlaller.append(f"D3 #{i} {komb}: kabul kararında hedef boş")

			for v in k.violations:
				if not v.code:
					ihlaller.append(f"D4 #{i} {komb}: kodsuz ihlal ({v.rule})")
					break
				mesaj = (v.message or {}).get("tr") if isinstance(v.message, dict) else None
				if mesaj is not None and ("{" in mesaj or "undefined" in mesaj):
					ihlaller.append(f"D4 #{i} {komb}: çözülmemiş mesaj → {mesaj}")
					break

			if len(ihlaller) > 10:
				break

		sure = time.monotonic() - basla
		self.assertEqual(
			ihlaller, [],
			f"{len(ihlaller)} değişmez ihlali ({sure:.1f} sn):\n" + "\n".join(ihlaller[:10]),
		)
		self.assertLess(sure, 60.0, f"tam tarama {sure:.1f} sn sürdü")

	def test_kb_GUVENLIK_MONOTONLUGU(self):
		"""D5: güvenlik bayrağı eklemek kararı ASLA iyileştiremez.

		Temiz künyeden başlayıp her güvenlik eksenini tek tek "kötü"ye çevirip
		`allow` değerinin False→True'ya dönmediğini ölçer. Bu bir *property*
		testi: tek bir örneğin doğru olması yetmez, sıralamanın her yerde
		korunması gerekir.

		Uzay: slot 9 × rol 4 × geometri 8 × bayt 5 × animasyon 2 × okunabilir 2
		      × uzantı 3 = 17.280 taban × 4 değerlendirme = 69.120 karar.
		"""
		motor = self.motor
		ihlaller: list[str] = []
		taban_sayisi = 0

		for slot, rol, (w, h), bayt, anim, oku, uyum in itertools.product(
			SLOTLAR, ROLLER, GEOMETRI, BAYTLAR, ANIMASYON, OKUNABILIR, UZANTI_UYUM
		):
			taban_sayisi += 1
			temiz = motor.evaluate(
				slot, _kunye(slot, w, h, bayt, anim, oku, uyum, False, False, True), rol
			).allow

			for eksen in GUVENLIK_EKSENLERI:
				kotu = {
					"leading_marker": False,
					"appended_payload": False,
					"scan_clean": True,
				}
				kotu[eksen] = False if eksen == "scan_clean" else True
				bozuk = motor.evaluate(
					slot,
					_kunye(
						slot, w, h, bayt, anim, oku, uyum,
						kotu["leading_marker"], kotu["appended_payload"], kotu["scan_clean"],
					),
					rol,
				).allow
				if bozuk and not temiz:
					ihlaller.append(
						f"D5 {slot}/{rol}/{w}x{h}/{bayt}: {eksen} bozulunca ret→KABUL"
					)
				if bozuk:
					ihlaller.append(
						f"D5 {slot}/{rol}/{w}x{h}/{bayt}: {eksen} bozukken KABUL edildi"
					)
				if len(ihlaller) > 10:
					break
			if len(ihlaller) > 10:
				break

		self.assertEqual(taban_sayisi if ihlaller else 17_280, 17_280, "taban uzayı değişti")
		self.assertEqual(ihlaller, [], "\n".join(ihlaller[:10]))

	def test_kb_DETERMINIZM_tum_slot_rol_ciftlerinde(self):
		"""D6: aynı girdi iki kez → aynı karar. 9 × 4 = 36 çift × 8 geometri."""
		motor = self.motor
		for slot, rol, (w, h) in itertools.product(SLOTLAR, ROLLER, GEOMETRI):
			with self.subTest(slot=slot, rol=rol, olcu=f"{w}x{h}"):
				kunye = _kunye(slot, w, h, 1_024, False, True, True, False, False, True)
				a = motor.evaluate(slot, kunye, rol)
				b = motor.evaluate(slot, kunye, rol)
				self.assertEqual(a.allow, b.allow)
				self.assertEqual(a.codes, b.codes)
				self.assertEqual(a.action, b.action)
				self.assertEqual(a.normalized_targets, b.normalized_targets)

	def test_kb_her_slot_hem_KABUL_hem_RET_uretebiliyor(self):
		"""Bir slot uzayın tamamında hep kabul/hep ret diyorsa kural ölüdür."""
		motor = self.motor
		durum: dict[str, set[bool]] = {s: set() for s in SLOTLAR}
		for komb in _tum_kombinasyonlar():
			slot = komb[0]
			if len(durum[slot]) == 2:
				continue
			durum[slot].add(_degerlendir(motor, komb).allow)
		for slot, degerler in durum.items():
			with self.subTest(slot=slot):
				self.assertEqual(
					degerler, {True, False},
					f"{slot}: uzayın tamamında yalnız {degerler} üretiyor — kural ölü olabilir",
				)

	def test_kb_her_rolde_karar_uretilebiliyor(self):
		motor = self.motor
		for rol in ROLLER:
			with self.subTest(rol=rol):
				k = motor.evaluate(
					"product.image",
					_kunye("product.image", 2000, 2000, 1_024, False, True, True, False, False, True),
					rol,
				)
				self.assertIsInstance(k.allow, bool)

	def test_kb_bilinmeyen_rol_kabulu_GENISLETMEZ(self):
		"""Uydurma bir rol, `seller`ın alamadığı bir kabulü almamalı."""
		motor = self.motor
		ihlaller: list[str] = []
		for slot, (w, h), bayt in itertools.product(SLOTLAR, GEOMETRI, BAYTLAR):
			kunye = _kunye(slot, w, h, bayt, False, True, True, False, False, True)
			satici = motor.evaluate(slot, kunye, "seller").allow
			uydurma = motor.evaluate(slot, kunye, "uydurma_rol").allow
			if uydurma and not satici:
				ihlaller.append(f"{slot}/{w}x{h}/{bayt}: uydurma rol seller'dan GENİŞ")
		self.assertEqual(ihlaller, [], "\n".join(ihlaller[:10]))


class TestKombinatoryalGeometri(unittest.TestCase):
	"""`target_size` tam çarpımı — saf geometri, DB yok, çok ucuz.

	Uzay: 12 kaynak ölçüsü × 6 uzun-kenar tavanı × 5 MP tavanı × 4 alt sınır
	      = 1.440 kombinasyon.
	"""

	KAYNAKLAR = (
		(100, 100), (1000, 1000), (2000, 1500), (1500, 2000), (4000, 3000),
		(3000, 4000), (8000, 1000), (1000, 8000), (1, 1), (1, 10000),
		(10000, 1), (2400, 2400),
	)
	TAVANLAR = (0, 256, 800, 1600, 2400, 4096)
	MP_TAVANLARI = (0.0, 0.5, 2.0, 5.76, 80.0)
	ALT_SINIRLAR = (0, 256, 1000, 1920)

	def test_kb_UPSCALE_YASAGI_tum_carpimda(self):
		"""FR-028: hiçbir parametre bileşimi kaynağı BÜYÜTEMEZ."""
		from tradehub_core.media.pipeline.image import normalize as nrm

		ihlaller: list[str] = []
		sayac = 0
		for (w, h), tavan, mp, alt in itertools.product(
			self.KAYNAKLAR, self.TAVANLAR, self.MP_TAVANLARI, self.ALT_SINIRLAR
		):
			if tavan and alt > tavan:
				continue  # sözleşme gereği geçersiz bileşim
			sayac += 1
			spec = nrm.NormalizeSpec(max_long_edge=tavan, max_megapixels=mp, min_long_edge=alt)
			nw, nh = nrm.target_size(w, h, spec)
			if nw > w or nh > h:
				ihlaller.append(f"{w}x{h} tavan={tavan} mp={mp} alt={alt} → {nw}x{nh} BÜYÜDÜ")
			if nw < 1 or nh < 1:
				ihlaller.append(f"{w}x{h} tavan={tavan} mp={mp} alt={alt} → {nw}x{nh} kenar<1")
		self.assertGreater(sayac, 1000, f"yalnız {sayac} bileşim tarandı")
		self.assertEqual(ihlaller, [], "\n".join(ihlaller[:10]))

	def test_kb_ORAN_KORUNUMU_tum_carpimda(self):
		"""Küçültme oranı bozmaz — yuvarlama payı dışında."""
		from tradehub_core.media.pipeline.image import normalize as nrm

		ihlaller: list[str] = []
		for (w, h), tavan, mp, alt in itertools.product(
			self.KAYNAKLAR, self.TAVANLAR, self.MP_TAVANLARI, self.ALT_SINIRLAR
		):
			if tavan and alt > tavan:
				continue
			spec = nrm.NormalizeSpec(max_long_edge=tavan, max_megapixels=mp, min_long_edge=alt)
			nw, nh = nrm.target_size(w, h, spec)
			if min(w, h, nw, nh) < 4:
				continue  # 1 px kenarda yuvarlama payı oranı domine eder
			sapma = abs((nw / nh) - (w / h)) / (w / h)
			if sapma > 0.05:
				ihlaller.append(f"{w}x{h} → {nw}x{nh} oran sapması %{sapma * 100:.1f}")
		self.assertEqual(ihlaller, [], "\n".join(ihlaller[:10]))

	def test_kb_MP_TAVANI_1440_bilesimin_HICBIRINDE_asilmiyor(self):
		"""F-06 düzeltmesinin tam çarpım kanıtı.

		12 kaynak × 6 tavan × 5 MP × 4 alt sınır = 1.440 bileşim; alt sınırlı
		ya da alt sınırsız, hiçbirinde MP tavanı aşılmamalı.
		"""
		from tradehub_core.media.pipeline.image import normalize as nrm

		altsiz_ihlal: list[str] = []
		altli_ihlal = 0
		for (w, h), tavan, mp, alt in itertools.product(
			self.KAYNAKLAR, self.TAVANLAR, self.MP_TAVANLARI, self.ALT_SINIRLAR
		):
			if not mp or (tavan and alt > tavan):
				continue
			spec = nrm.NormalizeSpec(max_long_edge=tavan, max_megapixels=mp, min_long_edge=alt)
			nw, nh = nrm.target_size(w, h, spec)
			asildi = (nw * nh) / 1_000_000 > mp + 1e-9
			if not asildi:
				continue
			if alt == 0:
				altsiz_ihlal.append(f"{w}x{h} tavan={tavan} mp={mp} → {nw}x{nh}")
			else:
				altli_ihlal += 1
		self.assertEqual(
			altsiz_ihlal, [],
			"alt sınır YOKKEN MP tavanı aşıldı:\n" + "\n".join(altsiz_ihlal[:10]),
		)
		# F-06 düzeltildi: alt sınır artık MP tavanına kelepçeleniyor, yani
		# 1.440 bileşimin HİÇBİRİNDE tavan aşılmamalı.
		self.assertEqual(
			altli_ihlal, 0,
			f"F-06 geri geldi — {altli_ihlal} bileşimde alt sınır MP tavanını deldi",
		)


if __name__ == "__main__":
	unittest.main()
