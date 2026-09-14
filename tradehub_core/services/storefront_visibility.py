# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Vitrin görünürlüğü toplu servisi (Dunning BE-1).

Store Subscription dunning akışının vitrin kolu: mağaza 'suspended' olduğunda
tüm listing'lerinin KANONİK vitrin kolonu `Listing.storefront_visible` toplu
0'a çekilir (hide); ödeme sonrası 'active'e dönüşte formülden deterministik
yeniden hesaplanır (restore). Tüm storefront sorguları bu kolonu filtrelediği
için başka hiçbir sorguya dokunmak gerekmez.

Tasarım notları:
  - `status` ve `is_visible` alanlarına DOKUNULMAZ — restore, bu iki alandan
    `storefront_visible = (status IN STOREFRONT_VISIBLE_STATUSES AND is_visible)`
    formülüyle yeniden hesap yapar (add_storefront_visible_flag patch'indeki
    backfill deseni); satıcının kendi gizlediği (is_visible=0) ürün restore
    sonrasında da gizli kalır (AC-6).
  - Her iki işlem idempotenttir: ikinci çağrı veri durumunu değiştirmez.
  - Çağıran taraf (suspend job'ı / Store Subscription on_update) çok ürünlü
    mağaza için frappe.enqueue(queue="long") kullanır — bu modül enqueue
    YAPMAZ, scheduler/job bağlamında senkron çalışır.
  - Perm bypass gerekçesi: toplu UPDATE'ler Frappe permission katmanını
    bilinçli atlar — işlem kullanıcı girdisiyle değil, dunning state machine
    kararının (Store Subscription status geçişi) zorunlu sistem sonucudur;
    scheduler/job bağlamında kullanıcı oturumu yoktur ve parametreli
    `seller_profile = %s` WHERE koşulu tenant sınırını SQL seviyesinde korur.
"""

from __future__ import annotations

import frappe
from frappe import _


def hide_store_listings(store: str) -> None:
	"""Mağazanın TÜM listing'lerini vitrinden düşür: storefront_visible=0 (AC-4).

	`status`/`is_visible` alanlarına dokunmaz; satıcının kendi tercihleri
	restore_store_listings ile geri hesaplanabilsin diye yalnız denormalize
	vitrin kolonu sıfırlanır. İdempotent: ikinci koşu no-op'tur.
	"""
	if not store:
		frappe.throw(_("Mağaza (store) parametresi zorunludur."))

	# Parametreli sorgu — değer enjeksiyonu yok (f-string SQL yasak).
	# `storefront_visible = 1` koşulu ikinci koşuyu no-op yapar (idempotent)
	# ve satır kilidini yalnız gerçekten değişecek satırlara daraltır.
	frappe.db.sql(
		"""
		UPDATE `tabListing`
		SET storefront_visible = 0
		WHERE seller_profile = %s AND storefront_visible = 1
		""",
		(store,),
	)
	_invalidate_storefront_cache()


def restore_store_listings(store: str) -> None:
	"""Mağazanın vitrinini formülden yeniden hesapla (AC-6).

	storefront_visible = (status IN STOREFRONT_VISIBLE_STATUSES AND is_visible)
	— add_storefront_visible_flag patch'indeki backfill deseninin mağaza-scoped
	kopyası. Satıcının kendi gizlediği (is_visible=0) ürün gizli KALIR.
	İdempotent: formül deterministik, ikinci koşu aynı sonucu verir.
	"""
	# Lazy import: api/listing.py büyük bir modül; controller'daki
	# _set_storefront_visible ile aynı desen (import döngüsü riski yok).
	from tradehub_core.api.listing import STOREFRONT_VISIBLE_STATUSES

	if not store:
		frappe.throw(_("Mağaza (store) parametresi zorunludur."))

	# Placeholder'lar yalnızca %s — status değerleri modül sabiti, mağaza adı
	# dahil tüm değerler parametre olarak gider (değer enjeksiyonu yok).
	placeholders = ", ".join(["%s"] * len(STOREFRONT_VISIBLE_STATUSES))
	frappe.db.sql(
		f"""
		UPDATE `tabListing`
		SET storefront_visible = IF(is_visible = 1 AND status IN ({placeholders}), 1, 0)
		WHERE seller_profile = %s
		""",
		(*STOREFRONT_VISIBLE_STATUSES, store),
	)
	_invalidate_storefront_cache()


def _invalidate_storefront_cache() -> None:
	"""Toplu vitrin değişikliği sonrası storefront liste cache'lerini düşür.

	invalidate_listing_cache doc=None ile güvenle çağrılabilir (fonksiyonun
	kendi sözleşmesi) ve tüm liste/arama/facet pattern'lerini kapsar.
	Per-listing detay cache'i (tradehub:listing_detail:*) doc-bazlı düşürülür;
	toplu işlemde kısa TTL'e bırakılır — spec riski olarak kabul edildi.
	"""
	from tradehub_core.api.listing import invalidate_listing_cache

	invalidate_listing_cache()
