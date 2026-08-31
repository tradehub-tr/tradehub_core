"""Testlerde virüs taraması kancasını nötrleyen ortak yardımcı.

**Neden gerekli.** `hold_until_clean` açıkken (tarayıcı kuruluysa varsayılan)
`File.after_insert` kancası dosyayı public/private ağaçtan FİZİKSEL olarak
`media_scan_hold` dizinine taşır. `file_url` değişmez, dosya yer değiştirir.
Dosyayı yazıp sonra diskten okuyan her test bu yüzden `FileNotFoundError`
alır — ölçtüğü davranışla hiç ilgisi olmayan bir sebeple.

**Neden bir "ortam sorunu" değil.** Testler bugüne kadar geçiyordu çünkü
container'da ClamAV kurulu DEĞİLDİ; kurulunca dört modül birden kırmızıya
döndü (ölçüldü 2026-08-28: `media_av_enabled=0` yapıldığında
`test_media_access_blob_binding` ve `test_media_retro_rename` tamamen
yeşile döndü). Üretimde tarayıcı KURULU; yani testler, üretimde geçerli
olmayan bir varsayıma yaslanıyordu. Doğru düzeltme tarayıcıyı kaldırmak
değil, testi tarama durumundan BAĞIMSIZ kılmak.

**Kapsam.** Yalnız kancayı susturur; `av` modülünün kendi davranışını sınayan
testler (`test_media_av`, `kapsamli/test_kd_18_carpisma`) bunu KULLANMAZ,
orada tarama ölçülen şeyin ta kendisidir.

Kullanım — modül düzeyinde tek satır, o modüldeki TÜM sınıfları kapsar:

    from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401
"""

from __future__ import annotations

from unittest import mock

_HEDEFLER: tuple[str, ...] = (
	"tradehub_core.media.av.enqueue_scan",
	"tradehub_core.media.av.maybe_scan_on_insert",
)

_yamalar: list = []


def basla() -> None:
	"""Kancayı sustur — çağıran `bitir()` ile geri almalı."""
	for hedef in _HEDEFLER:
		yama = mock.patch(hedef, return_value=None)
		yama.start()
		_yamalar.append(yama)


def bitir() -> None:
	"""Kancayı geri ver. Sıra ters: iç içe yamalar doğru çözülsün."""
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


def notrle(testcase) -> None:
	"""Tek bir test için nötrleme — modül düzeyi uygun değilse."""
	for hedef in _HEDEFLER:
		yama = mock.patch(hedef, return_value=None)
		yama.start()
		testcase.addCleanup(yama.stop)
