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
  - BE-5 (AC-10): restore kota-kontrollüdür — `quota.max_products` sonluysa
    formül sonrası vitrinde en yeni N ürün kalır, fazlası gizlenir; limit
    tanımsız/-1 iken davranış bugünkü gibidir (trim yok, güvenli taraf).
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

# BE-5 (AC-10): restore'da uygulanacak vitrin kotası anahtarı.
# entitlement.core.get_quota_limits sözleşmesi (kodda doğrulandı):
#   - operasyonel abonelik yoksa {} döner → anahtar yok → sınırsız kabul
#   - within_quota semantiği: -1 = sınırsız; 0 = devre dışı; >0 = üst sınır
QUOTA_MAX_PRODUCTS_KEY = "quota.max_products"


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

	BE-5 (AC-10) — kota-kontrollü restore: formül UPDATE'inden sonra
	`quota.max_products` sonluysa vitrindeki satır sayısı limitle karşılaştırılır;
	fazlası creation DESC sırayla ilk N'in DIŞINDA kalanlardan 0'a çekilir
	(en yeni N kalır). Limit tanımsız/None/-1 → trim yok (güvenli taraf,
	bugünkü davranış birebir). Trim NET değişiklik ürettiyse mağaza sahibine
	tek bilgi bildirimi + audit kaydı düşülür; ikinci koşu aynı seti üretir,
	bildirim TEKRARLAMAZ.
	"""
	# Lazy import: api/listing.py büyük bir modül; controller'daki
	# _set_storefront_visible ile aynı desen (import döngüsü riski yok).
	from tradehub_core.api.listing import STOREFRONT_VISIBLE_STATUSES

	if not store:
		frappe.throw(_("Mağaza (store) parametresi zorunludur."))

	# Kota limiti formül UPDATE'inden ÖNCE okunur (cache'li, ucuz) çünkü limit
	# sonluysa çağrı BAŞINDAKİ vitrin seti fotoğraflanmalı: formül UPDATE'i
	# trim'lenmiş satırları her koşuda yeniden 1'e çevirdiğinden, "bu koşu net
	# değişiklik üretti mi?" sorusu (bildirim idempotency'si) ancak ön-durum
	# fotoğrafıyla cevaplanabilir. Formül UPDATE'inin kendisi DEĞİŞMEZ.
	limit = _get_max_products_limit(store)
	pre_visible: set[str] | None = None
	if limit is not None:
		pre_visible = {
			row[0]
			for row in frappe.db.sql(
				"SELECT name FROM `tabListing` WHERE seller_profile = %s AND storefront_visible = 1",
				(store,),
			)
		}

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

	if limit is not None and pre_visible is not None:
		_apply_quota_trim(store, limit, pre_visible)

	_invalidate_storefront_cache()


def _get_max_products_limit(store: str) -> int | None:
	"""Mağazanın vitrin kotasını (quota.max_products) oku; None = trim yok.

	entitlement.core.get_quota_limits (kodda doğrulandı): operasyonel abonelik
	yoksa {} döner → anahtar yok. Dönüş semantiği:
	  None → tanımsız / None / -1 (sınırsız) → trim uygulanmaz (güvenli taraf)
	  >=0  → üst sınır (0 dahil: plan vitrini tamamen kapatmış demektir)
	"""
	# Lazy import — servis, entitlement çekirdeğine yalnız bu noktada bağımlı.
	from tradehub_core.entitlement.core import get_quota_limits

	limit = get_quota_limits(store).get(QUOTA_MAX_PRODUCTS_KEY)
	if limit is None:
		return None
	try:
		limit_int = int(limit)
	except (TypeError, ValueError):
		# Bozuk kota değeri: trim'i sessizce zorlamak yerine güvenli tarafa
		# düş (trim yok) ve iz bırak.
		frappe.log_error(
			f"quota.max_products parse edilemedi: {limit!r} (store={store})",
			"storefront_visibility.quota",
		)
		return None
	if limit_int < 0:
		return None  # -1 = sınırsız (within_quota semantiği)
	return limit_int


def _apply_quota_trim(store: str, limit: int, pre_visible: set[str]) -> None:
	"""Vitrindeki satır sayısı limiti aşıyorsa en yeni N dışındakileri gizle.

	Sıralama deterministik: creation DESC, eşitlikte name DESC — ikinci koşu
	aynı keep set'ini üretir (veri idempotent). Bildirim yalnız bu koşu NET
	değişiklik ürettiyse (final set != çağrı başındaki set) gider; formülün
	geri açıp trim'in yeniden kapattığı satırlar net değişiklik DEĞİLDİR.
	Spec'teki "trim rowcount>0 → bildir" ifadesinden bilinçli sapma: formül
	UPDATE'i trim'lenmiş satırları HER koşuda yeniden 1'e çevirdiği için trim
	rowcount ikinci koşuda da >0 olur — rowcount kriteri her koşuda bildirim
	tekrarı demektir. Net-değişiklik kriteri AC-10'un asıl amacını (tek
	bildirim, tekrar yok) sağlar; uç sonucu: ön-durum zaten kota-uyumluysa
	(örn. tam-gizli vitrin + limit 0) hiçbir koşu bildirim üretmez.
	"""
	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabListing`
		WHERE seller_profile = %s AND storefront_visible = 1
		ORDER BY creation DESC, name DESC
		""",
		(store,),
	)
	visible = [row[0] for row in rows]
	if len(visible) <= limit:
		return

	keep = visible[:limit]
	trim = visible[limit:]
	# Parametreli IN listesi — placeholder'lar yalnız %s, tüm adlar parametre.
	placeholders = ", ".join(["%s"] * len(trim))
	frappe.db.sql(
		f"""
		UPDATE `tabListing`
		SET storefront_visible = 0
		WHERE seller_profile = %s AND storefront_visible = 1 AND name IN ({placeholders})
		""",
		(store, *trim),
	)

	if set(keep) == pre_visible:
		# İkinci koşu / zaten kota-tutarlı durum: veri net değişmedi →
		# bildirim ve audit TEKRARLAMAZ (AC-10 idempotency).
		return
	_notify_quota_trim(store, limit, len(trim))


def _notify_quota_trim(store: str, limit: int, trimmed_count: int) -> None:
	"""Trim bilgilendirmesi: audit kaydı + mağaza sahibine TEK in-app bildirim.

	Best-effort: bildirim/audit hatası restore akışını (dunning recovery)
	asla kırmaz — notify zaten kendi içinde hata yutar, log_decision
	best-effort'tur; import hatasına karşı entitlement.core'daki desenle
	sarılır.
	"""
	try:
		# Lazy import — entitlement.core'daki audit deseniyle aynı (circular önlemi).
		from tradehub_core.audit import DECISION_DENY, LAYER_L0, SEVERITY_NORMAL, log_decision

		log_decision(
			action="storefront.restore.quota_trim",
			decision=DECISION_DENY,
			rule_id=f"entitlement.quota.{QUOTA_MAX_PRODUCTS_KEY}",
			layer=LAYER_L0,
			tenant=store,
			# ADL skalası LOW/NORMAL/HIGH (audit/log.py) — MEDIUM yok; mevcut
			# entitlement kota deny kayıtlarıyla tutarlı olarak NORMAL.
			severity=SEVERITY_NORMAL,
			context={"limit": limit, "trimmed_count": trimmed_count},
		)
	except Exception:
		frappe.log_error("storefront quota trim audit log failed", "storefront_visibility.quota")

	owner = frappe.db.get_value("Admin Seller Profile", store, "user")
	if not owner:
		# Owner yoksa bildirim SESSİZCE atlanır (notify hata-yutma deseni);
		# audit kaydı yukarıda zaten düşüldü.
		return

	from tradehub_core.utils.notify import notify

	notify(
		recipient_user=owner,
		recipient_role="seller",
		# Platform Notification.type Select'inde "subscription" yok → "system"
		# (subscription_lifecycle.py ile aynı tercih).
		type="system",
		title=_("Plan kotası: bazı ürünler vitrine dönmedi"),
		message=_(
			"{0} ürününüz plan kotası nedeniyle vitrine dönmedi; "
			"kota artırmak için paketinizi yükseltebilirsiniz."
		).format(trimmed_count),
		action_url="/abonelik",
		reference_doctype="Admin Seller Profile",
		reference_name=store,
	)


def _invalidate_storefront_cache() -> None:
	"""Toplu vitrin değişikliği sonrası storefront liste cache'lerini düşür.

	invalidate_listing_cache doc=None ile güvenle çağrılabilir (fonksiyonun
	kendi sözleşmesi) ve tüm liste/arama/facet pattern'lerini kapsar.
	Per-listing detay cache'i (tradehub:listing_detail:*) doc-bazlı düşürülür;
	toplu işlemde kısa TTL'e bırakılır — spec riski olarak kabul edildi.
	"""
	from tradehub_core.api.listing import invalidate_listing_cache

	invalidate_listing_cache()
