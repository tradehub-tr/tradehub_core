"""Sözleşmelerin bellek-içi sahte uygulamaları — yalnız test içindir.

Neden sahte uygulama yazılıyor
------------------------------
Bir `Protocol` tek başına hiçbir şeyi garanti etmez: imzayı karşılayan ama
sözleşmeyi (idempotensi, hata tipi, sıra) ihlal eden bir uygulama sessizce
kabul edilir. Sahte uygulamalar sözleşmenin **yürütülebilir tanımıdır**:
`tests/test_contracts.py` aynı testleri hem sahteye hem (ileride) gerçek
uygulamaya uygular; sahte geçip gerçek geçmiyorsa kusur gerçek uygulamadadır.

Gerçek olan ne, sahte olan ne
-----------------------------
  `InMemoryStorage`    tamamen sahte — sözlük tabanlı, disk yok.
  `FakeImageEngine`    sentetik biçimle çalışır (`FIMG1|…`): Pillow gerekmez,
                       dolayısıyla sözleşme testi bağımlılıksız koşar. Piksel
                       doğruluğunu DEĞİL, sözleşme davranışını doğrular.
  `FakeVideoEngine`    aynı desen (`FVID1|…`); ffmpeg gerekmez.
  `InMemoryPolicyEngine` **gerçek politika JSON'larını okur** (`from_directory`)
                       ya da bellekten kurulur. Politika mantığı sahte değil,
                       referans uygulamadır.
  `SimpleDeliveryManifest` politikadan `srcset` üreten referans uygulama.
"""

from tradehub_core.media.pipeline.fakes.delivery import SimpleDeliveryManifest
from tradehub_core.media.pipeline.fakes.image import FakeImageEngine, sentetik_gorsel
from tradehub_core.media.pipeline.fakes.policy import InMemoryPolicyEngine
from tradehub_core.media.pipeline.fakes.storage import InMemoryStorage
from tradehub_core.media.pipeline.fakes.video import FakeVideoEngine, sentetik_video

__all__ = [
	"InMemoryStorage",
	"FakeImageEngine",
	"sentetik_gorsel",
	"FakeVideoEngine",
	"sentetik_video",
	"InMemoryPolicyEngine",
	"SimpleDeliveryManifest",
]
