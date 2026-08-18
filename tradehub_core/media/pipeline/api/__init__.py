"""Dış sınır — uç noktalar. FAZ 8'DE UYGULANDI (T-080…T-085).

Bu paket saf Python fonksiyonları barındırır: hiçbiri `@frappe.whitelist()`
taşımaz, hiçbiri `frappe.local.response`'a yazmaz, hepsi bir
`envelope.ApiResponse` **döndürür**. `media_engine` bir Frappe app'i değil,
bir kütüphanedir; Frappe'ye bağlama noktası tek bir ince katmandır ve
`docs/api/README.md` §3'te anlatılır.

Bunun karşılığı, uç noktaların site/bench/DB olmadan test edilebilmesidir —
`tests/test_api_contracts.py` konteyner dışında da koşar.

MODÜLLER
--------
    envelope.py   yanıt biçimi, HTTP eşlemesi, ETag, yetki kapısı
    spec.py       T-080 · OpenAPI 3.1 belgesi (TEK DOĞRULUK KAYNAĞI) + YAML yazıcı
    upload.py     T-081 · create_session / put_chunk / status / finalize / abort
    crop.py       T-082 · get_intent / save_intent / suggest_focal / preview
    delivery.py   T-083 · manifest / manifest_batch / signed_url
    admin.py      T-084 · media_admin.py'de KARŞILIĞI OLMAYAN dokuz yönetim ucu

SARILAN — YENİDEN YAZILMAYAN
----------------------------
    tradehub_core/media/chunked.py       parçalı yükleme oturumları  → api/upload.py
    tradehub_core/api/media_access.py    imzalı private erişim       → delivery/signed.py
    tradehub_core/api/media_admin.py     39 yönetim ucu              → api/admin.py (yalnız EKSİK olanlar)
    tradehub_core/media/pipeline/core/crop.py            kırpma öncelik zinciri      → api/crop.py
    tradehub_core/media/pipeline/image/render.py         türev merdiveni             → delivery/manifest.py

FAZ 3'TEKİ AÇIK KAPANDI: SLOT KİMLİĞİ
-------------------------------------
`upload_policy.check()` imzasında slot parametresi yok
(`docs/reports/00-upload-slot-envanteri.md` §7-B B1); sunucu bir yüklemenin
hangi slota ait olduğunu bilmiyor. `api/upload.py::create_session` slot
anahtarını **ilk adımda** alır, oturum künyesine yazar ve `finalize`'da
`PolicyEngine.evaluate()`'a taşır. İstemci tarafı (storefront + admin panel)
SALT OKUNUR olduğu için o depolarda karşılık kodu bu fazda yazılamadı;
sözleşme `docs/api/openapi.yaml` ile ilan edilir.
"""

from __future__ import annotations

IMPLEMENTED = True

#: Faz 8 görev haritası — hangi görev hangi modülde.
TASKS: dict[str, str] = {
	"T-080": "tradehub_core/media/pipeline/api/spec.py + docs/api/openapi.yaml",
	"T-081": "tradehub_core/media/pipeline/api/upload.py",
	"T-082": "tradehub_core/media/pipeline/api/crop.py",
	"T-083": "tradehub_core/media/pipeline/api/delivery.py + tradehub_core/media/pipeline/delivery/manifest.py",
	"T-084": "tradehub_core/media/pipeline/api/admin.py",
	"T-085": "docs/api/README.md",
}

__all__ = ["IMPLEMENTED", "TASKS"]
