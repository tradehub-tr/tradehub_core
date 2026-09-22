"""TETİKLEYİCİ DENETİMİ — yazılan bir veri rutini gerçekten KOŞUYOR mu?

NEDEN VAR (ölçülmüş bir vaka):
`catalog/category_i18n.py` 16 Eylül 2026'da commit'lendi (`e5bb810`): 273
satırlık modül, 801 kayıtlık sözlük tohumu ve 374 satır test birlikte geldi.
16 birim testinin hepsi yeşildi. Ama hattı ÇAĞIRAN hiçbir şey yoktu —
`patches.txt`'te satır yok, `hooks.py`'de kanca yok, başka modülde referans yok.

Beş gün sonra ölçüldü (21 Eyl 2026, canlı): `get_categories` dört dilde de
Türkçe dönüyordu. Arayüz dört dilliydi, katalog tek dilliydi. Kimse fark
etmemişti çünkü testler fonksiyonun DOĞRU ÇALIŞTIĞINI ölçüyordu; hiçbiri
"bunu çağıran var mı" diye sormuyordu.

Kontrol listesi unutulur, denetim TEST olur (kök `CLAUDE.md` §4.15c).

KURAL: tek seferlik bir veri rutini şunlardan BİRİNE bağlı olmalı —
  1. `patches.txt` (migrate'te koşar; tüm ortamlara kendiliğinden gider)
  2. `hooks.py` (kanca ya da zamanlanmış görev)
  3. Repo içinde başka bir modülden çağrı
  4. `MUAFIYETLER` — GEREKÇESİYLE, çağıran ekranın adıyla

`@frappe.whitelist()` TEK BAŞINA yeterli sayılmaz: `category_i18n` üç adet
whitelist ucu taşıyordu (`run_seed`, `run_backfill`, `get_coverage`) ve yine
de hiç koşmadı. Ucu çağıran ekran kardeş repoda (`admin-panel`) yaşıyor ve bu
repo onu göremez — o yüzden çağıran ekran MUAFIYETLER'e elle yazılır.
"""

import re
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]

#: Tek seferlik veri rutini sayılan fonksiyon adları.
DESEN = re.compile(r"^def ((?:seed|backfill|repair)_?\w*|apply_\w*_seed|rebuild_all)\s*\(", re.M)

#: Bağı repo dışında olan modüller — her biri GEREKÇESİYLE.
#: Muafiyet bayatlarsa (modül gerçekten bağlanırsa) test bunu söyler.
MUAFIYETLER: dict[str, str] = {
	"api/media_admin.py": (
		"Whitelist uçları; panelden `MediaSeoView.vue` çağırıyor (ölçüldü 21 Eyl 2026). "
		"Çağıran ekran kardeş repoda olduğu için buradan görünmez."
	),
	"media/watch_slug.py": (
		"`backfill_slugs` BİLİNÇLİ elle araç — kendi docstring'i 'bench execute için' "
		"diyor ve ffmpeg maliyeti olmadığı için senkron koşuyor. Ölçüldü (21 Eyl 2026): "
		"repoda ve panelde çağıranı yok, tek geçtiği yer kendi dosyasındaki bir yorum."
	),
	"seed_demo_data.py": (
		"`seed_homepage_content` demo verisi kurar; docstring'i çalıştırma komutunu "
		"veriyor (`bench --site <site> execute ...`). Üretimde otomatik koşmaMALI — "
		"demo içeriği canlı veriyi ezerdi. Ölçüldü (21 Eyl 2026): patch/hook bağı yok."
	),
}


def _test_mi(gorece_yol: str, ad: str) -> bool:
	return gorece_yol.startswith("tests/") or "/tests/" in gorece_yol or ad.startswith("test_")


def _aday_dosyalar() -> list[Path]:
	"""Rutin ARANACAK dosyalar — patch'ler hariç (patch'in kendisi tetikleyicidir)."""
	return [
		p
		for p in KOK.rglob("*.py")
		if not p.relative_to(KOK).as_posix().startswith("patches/")
		and not _test_mi(p.relative_to(KOK).as_posix(), p.name)
	]


def _cagiran_dosyalar() -> list[Path]:
	"""Çağrı ARANACAK dosyalar — patch'ler DAHİL.

	Bu ayrım bir kez atlandı ve denetim üç sahte yetim üretti: `seed_role_profiles`
	gerçekte `v15_log037_seed_logistics_role_profiles` patch'inden çağrılıyordu,
	ama patch dosyaları taramanın dışındaydı. Tetikleyicinin en yaygın biçimini
	görmeyen bir tetikleyici denetimi işe yaramaz.
	"""
	return [p for p in KOK.rglob("*.py") if not _test_mi(p.relative_to(KOK).as_posix(), p.name)]


def _rutin_tasiyan_moduller() -> dict[str, list[str]]:
	bulunan: dict[str, list[str]] = {}
	for p in _aday_dosyalar():
		icerik = p.read_text(encoding="utf-8", errors="ignore")
		adlar = [m.group(1) for m in DESEN.finditer(icerik)]
		if adlar:
			bulunan[p.relative_to(KOK).as_posix()] = adlar
	return bulunan


_YORUM = re.compile(r"#.*$", re.M)
_DIZE = re.compile(r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')')


def _kod(icerik: str) -> str:
	"""Yorumları ve üç tırnaklı dizeleri soy.

	TUZAK (ölçüldü): ham metinde arama sahte yeşil üretir. `seed_demo_data`
	modülü iki ayrı docstring'de ve bir patch'in açıklamasında geçiyordu; denetim
	onu "bağlı" saydı, oysa çağrılan fonksiyon BAŞKAYDI (`cleanup`). Aynı tuzak
	`src/i18n/__tests__/e2eDilKurulumuDenetimi.test.ts`'te de kayıtlı.
	"""
	return _YORUM.sub("", _DIZE.sub("", icerik))


def _bagli_mi(gorece_yol: str, fonksiyonlar: list[str]) -> list[str]:
	"""Bağ FONKSİYON ADIYLA aranır, modül adıyla değil.

	Modülden başka bir fonksiyon içe aktarılmış olması, bu rutini çağıran bir
	şey olduğu anlamına GELMEZ — ölçüldü: `v15_9_53_purge_demo_data`
	`seed_demo_data`den `cleanup`i alıyor, `seed_homepage_content`i değil.
	"""
	hooks = _kod((KOK / "hooks.py").read_text(encoding="utf-8"))
	baglar = []
	if any(re.search(rf"\b{re.escape(fn)}\b", hooks) for fn in fonksiyonlar):
		baglar.append("hooks.py")
	for q in _cagiran_dosyalar():
		qr = q.relative_to(KOK).as_posix()
		if qr == gorece_yol:
			continue
		t = _kod(q.read_text(encoding="utf-8", errors="ignore"))
		if any(re.search(rf"\b{re.escape(fn)}\b", t) for fn in fonksiyonlar):
			baglar.append(f"kod:{qr}")
			break
	return baglar


class TestTetikleyiciDenetimi(unittest.TestCase):
	def test_tarama_gercekten_calisiyor(self):
		"""Denetimin kendisi sessizce boşa düşmesin."""
		moduller = _rutin_tasiyan_moduller()
		self.assertGreater(len(moduller), 8, "tarama rutin bulamadı — desen bozulmuş olabilir")

	def test_her_tek_seferlik_rutinin_tetikleyicisi_var(self):
		yetimler = []
		for yol, fonksiyonlar in sorted(_rutin_tasiyan_moduller().items()):
			if yol in MUAFIYETLER:
				continue
			if not _bagli_mi(yol, fonksiyonlar):
				yetimler.append(f"{yol} ({', '.join(fonksiyonlar)})")
		self.assertEqual(
			yetimler,
			[],
			"Bu modüllerdeki veri rutinini ÇAĞIRAN hiçbir şey yok — yazıldılar ama "
			"hiçbir ortamda koşmayacaklar. patches.txt'e satır ekleyin, hooks'a "
			"bağlayın ya da gerekçesiyle MUAFIYETLER'e yazın:\n  " + "\n  ".join(yetimler),
		)

	def test_muafiyetler_bayatlamadi(self):
		"""Muafiyet listesi çöplüğe dönmesin: bağı kurulan modül listeden düşer."""
		moduller = _rutin_tasiyan_moduller()
		bayat = []
		for yol, gerekce in MUAFIYETLER.items():
			if yol not in moduller:
				bayat.append(f"{yol} — artık böyle bir rutin yok, muafiyeti silin")
				continue
			if _bagli_mi(yol, moduller[yol]):
				bayat.append(f"{yol} — bağı kurulmuş, muafiyeti silin ({gerekce[:40]}…)")
		self.assertEqual(bayat, [], "Bayat muafiyet:\n  " + "\n  ".join(bayat))

	def test_her_muafiyetin_gerekcesi_var(self):
		for yol, gerekce in MUAFIYETLER.items():
			with self.subTest(yol=yol):
				self.assertGreater(
					len(gerekce.strip()),
					40,
					f"{yol} muafiyeti gerekçesiz — hangi ekran çağırıyor, nasıl ölçüldü?",
				)


if __name__ == "__main__":
	unittest.main()
