# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""Medya boru hattı özellik bayrakları — Dalga A'nın emniyet subabı (A1b).

`media/pipeline/` altındaki 71 modül çalışıyor ama ürüne bağlı değil. Bu modül,
o hattın ürüne bağlanacağı HER noktanın tek kapısı: yeni davranışa geçmeden
önce buradan izin sorulur.

İki değişmez kural:

1. **Varsayılan KAPALI.** `Media Engine Settings` okunamıyorsa (DocType henüz
   migrate edilmedi, DB yok, site bağlamı yok, alan adı yanlış) sonuç `False`.
   Fail-safe yön "kapalı"dır — bayrak okuma hatası asla yeni kod yolunu
   açmamalı, çağıranı da patlatmamalı.
2. **Ana şalter her şeyi keser.** `media_pipeline_enabled` kapalıyken alt
   bayraklar (`rendition_on_upload`, `manifest_api_enabled`) ve tüm slotlar
   `False` döner — kaydedilmiş değerleri ne olursa olsun. Böylece geri dönüş
   tek kutucuk: ana şalteri kapat, sistem bugünkü davranışına döner.

Önbellek: değer request kapsamında `frappe.local_cache` ile tutulur.

    NOT — sürüm sapması: görev metni `frappe.client_cache` diyordu, ancak bu
    kurulumdaki Frappe **v15.116.1**'de `frappe.client_cache` YOK (None olarak
    duruyor; ClientCache v16/develop ile geldi). v15'teki request-scope karşılığı
    `frappe.local_cache(namespace, key, generator)`; bu modül onu kullanıyor.
    Semantik istenenle aynı: değer istek başına bir kez okunur, istek bitince
    düşer. Cross-request önbellek BİLEREK kullanılmadı — bayrak açıldıktan sonra
    kapatmanın anında etki etmesi gerekir.

Bu modül saf yardımcıdır: DocType yazmaz, iş yapmaz, exception sızdırmaz.
"""

from __future__ import annotations

import hashlib

import frappe
from frappe.utils import cint

SETTINGS_DOCTYPE = "Media Engine Settings"

#: `is_enabled` yalnızca bu alanları okur. Beyaz liste, çağıranın yanlışlıkla
#: (ya da kötü niyetle) `Media Engine Settings` üstündeki başka bir alanı bayrak
#: gibi okumasını engeller — örn. `notes` dolu diye "açık" sanılmasın.
FLAG_FIELDS: frozenset[str] = frozenset(
	{
		"media_pipeline_enabled",
		"rendition_on_upload",
		"manifest_api_enabled",
	}
)

MASTER_FLAG = "media_pipeline_enabled"

#: `media/pipeline/policy/slots/*.json` içindeki kanonik `slot_key` değerleri.
#: Ayarlarda yazım hatası olan bir anahtar sessizce "kapalı" kalırdı; controller
#: bu kümeye bakıp kaydederken uyarıyor.
KNOWN_SLOT_KEYS: frozenset[str] = frozenset(
	{
		"brand.logo",
		"category.banner",
		"company.cover_image",
		"company.cover_video",
		"document.attachment",
		"product.image",
		"product.video",
		"seller.logo",
		"user.avatar",
	}
)

#: Tek başına yazıldığında tüm slotları açan joker.
SLOT_WILDCARD = "*"

DEFAULT_MAX_RENDITIONS = 40
DEFAULT_ROLLOUT_PERCENT = 100

_CACHE_NAMESPACE = "tradehub_media_pipeline_flags"

#: Aynı hatayı her çağrıda loglamamak için (bayrak sorgusu istek başına onlarca
#: kez çağrılabilir). Süreç ömrü boyunca alan adı başına tek kayıt — küme
#: FLAG_FIELDS + birkaç sabit anahtarla sınırlı, büyümez.
_LOGLANAN_HATALAR: set[str] = set()


def is_enabled(alan: str = MASTER_FLAG) -> bool:
	"""`alan` bayrağı açık mı. Okunamazsa / bilinmiyorsa **False**.

	Ana şalter (`media_pipeline_enabled`) kapalıyken alt bayraklar da False
	döner; tek kutucukla tüm hattı kapatabilmek için.
	"""
	if alan not in FLAG_FIELDS:
		# Bilinmeyen alan = yapılandırma hatası. Fail-safe yön kapalı.
		_hata_logla(f"bilinmeyen bayrak alanı: {alan}", anahtar=f"unknown:{alan}")
		return False

	if not _bayrak_oku(MASTER_FLAG):
		return False

	if alan == MASTER_FLAG:
		return True

	return _bayrak_oku(alan)


def is_slot_enabled(slot_key: str) -> bool:
	"""`slot_key` için boru hattı açık mı. Ana şalter kapalıysa daima False.

	`active_slots` boşsa hiçbir slot açık değildir (fail-safe); tek başına `*`
	yazılmışsa tümü açıktır.
	"""
	if not is_enabled():
		return False

	anahtar = (slot_key or "").strip().lower()
	if not anahtar:
		return False

	etkin = _etkin_slotlar()
	if SLOT_WILDCARD in etkin:
		return True
	return anahtar in etkin


def max_renditions_per_asset(varsayilan: int = DEFAULT_MAX_RENDITIONS) -> int:
	"""Varlık başına türev üst sınırı. Okunamazsa / geçersizse `varsayilan`."""
	ham = _tekil_deger("max_renditions_per_asset")
	deger = cint(ham)
	return deger if deger > 0 else varsayilan


def rollout_percent(varsayilan: int = DEFAULT_ROLLOUT_PERCENT) -> int:
	"""Aşamalı açılış yüzdesi (0–100); alan yoksa geriye uyum için `%100`.

	Ana şalter zaten varsayılan kapalıdır. Yeni rollout alanının henüz migrate
	edilmediği bir sitede, operatör ana şalteri daha önce bilinçli açmışsa hattı
	sessizce `%0`a düşürmek beklenmeyen bir kesinti olurdu. Bu yüzden yalnız
	alanın yokluğu `%100`, açıkça kaydedilmiş `0` ise gerçek canary kipidir.
	"""
	ham = _tekil_deger("rollout_percent")
	if ham is None or str(ham).strip() == "":
		return max(0, min(100, int(varsayilan)))
	return max(0, min(100, cint(ham)))


def parse_store_keys(ham: object) -> frozenset[str]:
	"""Satır/virgül ayrımlı canary mağaza adlarını kararlı biçimde normalize et."""
	if not ham:
		return frozenset()
	metin = str(ham).replace(",", "\n")
	return frozenset(parca.strip().casefold() for parca in metin.split("\n") if parca.strip())


def rollout_bucket(store_id: object) -> int:
	"""Mağazayı kararlı `0..99` kovasına yerleştir.

	Python'ın yerleşik `hash()` sonucu süreçler arasında değişir; rollout için
	kullanılamaz. SHA-256'nın ilk 64 biti tüm web/worker süreçlerinde ve yeniden
	başlatmalarda aynıdır. Yüzde büyüdükçe eski mağazalar kümeden çıkmaz.
	"""
	anahtar = str(store_id or "").strip().casefold()
	if not anahtar:
		return 100
	ozet = hashlib.sha256(anahtar.encode("utf-8")).digest()
	return int.from_bytes(ozet[:8], "big") % 100


def is_store_enabled(store_id: object) -> bool:
	"""Mağaza bu rollout aşamasında mı; ana şalter kapalıysa daima `False`.

	`rollout_stores` canary listesi yüzdeden önce gelir. Yüzde `%100` iken
	mağazası çözülemeyen sistem/platform medyası da geriye uyumlu olarak açıktır;
	kısmi rollout'ta kimliği çözülemeyen kayıtlar fail-closed dışarıda kalır.
	"""
	if not is_enabled():
		return False
	anahtar = str(store_id or "").strip().casefold()
	if anahtar and anahtar in parse_store_keys(_tekil_deger("rollout_stores")):
		return True
	yuzde = rollout_percent()
	if yuzde >= 100:
		return True
	if yuzde <= 0 or not anahtar:
		return False
	return rollout_bucket(anahtar) < yuzde


def clear_cache() -> None:
	"""Request kapsamındaki bayrak önbelleğini düşürür.

	`MediaEngineSettings.on_update` çağırır (aynı istek içinde kaydeden kullanıcı
	eski değeri görmesin) ve testler kullanır.
	"""
	try:
		frappe.local.cache.pop(_CACHE_NAMESPACE, None)
	except Exception:
		# Site bağlamı yoksa düşürülecek önbellek de yoktur; bu yol sessizce
		# geçilmeli — önbellek temizliği asla çağıranı patlatmamalı.
		pass


def _bayrak_oku(alan: str) -> bool:
	return cint(_tekil_deger(alan)) == 1


def _etkin_slotlar() -> frozenset[str]:
	ham = _tekil_deger("active_slots")
	return parse_slot_keys(ham)


def parse_slot_keys(ham: object) -> frozenset[str]:
	"""Satır ve/veya virgülle ayrılmış slot listesini normalize eder.

	DocType controller'ı da doğrulama için bunu kullanıyor — ayrıştırma kuralı
	tek yerde kalsın diye public.
	"""
	if not ham:
		return frozenset()
	metin = str(ham).replace(",", "\n")
	return frozenset(parca.strip().lower() for parca in metin.split("\n") if parca.strip())


def _tekil_deger(alan: str) -> object | None:
	"""Single değerini request kapsamında önbellekleyerek okur; hata → None."""
	try:
		return frappe.local_cache(
			_CACHE_NAMESPACE,
			alan,
			lambda: frappe.db.get_single_value(SETTINGS_DOCTYPE, alan),
		)
	except Exception:
		# DocType henüz migrate edilmemiş, DB kapalı ya da site bağlamı yok.
		# Bayrak okuma yolunun tamamı fail-safe: hiçbir koşulda exception
		# sızdırmaz, çağıran "kapalı" görür.
		_hata_logla(f"{SETTINGS_DOCTYPE}.{alan} okunamadı", anahtar=alan)
		return None


def _hata_logla(mesaj: str, anahtar: str) -> None:
	"""Hatayı süreç başına bir kez loglar; loglama da patlarsa sessiz kalır."""
	if anahtar in _LOGLANAN_HATALAR:
		return
	_LOGLANAN_HATALAR.add(anahtar)
	try:
		frappe.log_error(
			title="media pipeline flags",
			message=f"{mesaj}\n\n{frappe.get_traceback()}",
		)
	except Exception:
		# Loglama DB'ye yazar; DB yoksa/istek bağlamı yoksa burası da patlar.
		# Fail-safe yolun kendisi asla exception yükseltmemeli.
		pass
