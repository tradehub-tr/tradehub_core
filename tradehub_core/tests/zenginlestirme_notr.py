"""Testlerde medya ZENGİNLEŞTİRME kancalarını nötrleyen ortak yardımcı.

**Neden gerekli.** `File.after_insert` kancaları (`doc_meta` ve 10 Eyl
2026'dan beri `audio_meta`) dosyayı `media-maint` kuyruğuna atar. Container'da
canlı bir worker koşuyorsa iş test ile AYNI ANDA aynı `File` satırına
dokunur: `apply()` `set_value` yaparken test aynı satırı siliyor ve iki taraf
da `Lock wait timeout exceeded` alıyor.

**Neden bir "ortam sorunu" değil, neden kanca da kaldırılmıyor.**
`av_notr.py`'nin ölçtüğü tabloyla birebir aynı: üretimde worker KOŞUYOR ve
kanca DOĞRU. Testler bugüne kadar geçiyordu çünkü ses tarafında kanca hiç
yoktu (denetim bulgusu: `apply` yazılmış ama hiçbir çağıranı yok). Kanca
takılınca ses testleri kırmızıya döndü — ölçüldü 10 Eyl 2026: yalnız
`hooks.py` geri alınınca `test_e2e_media_audio` 51/51 yeşil. Doğru düzeltme
kancayı geri almak değil, testi kuyruk durumundan BAĞIMSIZ kılmak.

**Kapsam.** Yalnız `after_insert` kancasını susturur. `apply()`,
`extract()` ve `backfill_pending()` DOKUNULMAZ — testlerin ölçtüğü şey
onlar ve hepsi doğrudan çağrılıyor. Yani bu yardımcı "çıkarımı kapatmıyor",
"çıkarımın arkadan ikinci kez, kontrolsüz koşmasını" kapatıyor.

Kullanım — modül düzeyinde tek satır, o modüldeki TÜM sınıfları kapsar:

    from tradehub_core.tests.zenginlestirme_notr import setUpModule, tearDownModule  # noqa: F401

`av_notr` ile birlikte kullanılacaksa ikisinin `setUpModule`'ü aynı ada
sahip olduğu için doğrudan iki kez içe aktarılamaz; `birlesik_kur()`
yardımcısı ikisini tek çağrıda kurar.
"""

from __future__ import annotations

from unittest import mock

_HEDEFLER: tuple[str, ...] = (
	"tradehub_core.media.audio_meta.maybe_extract_on_insert",
	"tradehub_core.media.doc_meta.maybe_extract_on_insert",
)

_yamalar: list = []


def basla() -> None:
	"""Kancaları sustur — çağıran `bitir()` ile geri almalı."""
	for hedef in _HEDEFLER:
		yama = mock.patch(hedef, return_value=None)
		yama.start()
		_yamalar.append(yama)


def bitir() -> None:
	"""Kancaları geri ver. Sıra ters: iç içe yamalar doğru çözülsün."""
	while _yamalar:
		try:
			_yamalar.pop().stop()
		except RuntimeError:
			# Yama zaten durdurulmuşsa temizlik akışı kesilmemeli.
			pass


def setUpModule() -> None:
	basla()


def tearDownModule() -> None:
	bitir()
