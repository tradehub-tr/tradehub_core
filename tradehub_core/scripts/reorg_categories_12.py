"""
Kategori ağacını 12 ana kategoriye yeniden düzenler (2026-09-03 kararı).

Eski 7 sektör (Sağlık, Gıda, Elektronik, Hizmet, Endüstri, Sanat, Perakende) →
12 ana kategori:
  Sağlık · Gıda · Tarım · Elektronik · Ev & Bahçe · Moda · Ofis & Kırtasiye ·
  Hobi & Sanat · Makine · Yapı & Hırdavat · Otomotiv · Hizmet

İlkeler
- İlanlar yaprak kategorilere bağlıdır; hiçbir ilan kopmaz. Bir düğüm birleştirilip
  pasife alınıyorsa üzerindeki ilanlar hedef düğüme taşınır.
- Mevcut sektör kayıtları mümkün olduğunca yeniden kullanılır (id sabit kalır):
  Perakende → Ev & Bahçe, Endüstri → Makine, Sanat → Hobi & Sanat.
- Kopya gruplar ad eşleşmesiyle özyinelemeli birleştirilir (Ev → Ev & Yaşam vb.).
- Boşalan grup düğümleri silinmez, is_active=0 yapılır.
- Sonunda nested set yeniden kurulur.

Çalıştırma:
  bench --site <site> execute tradehub_core.scripts.reorg_categories_12.run
  bench --site <site> execute tradehub_core.scripts.reorg_categories_12.run --kwargs '{"dry_run": 1}'
Betik yeniden çalıştırılabilir: yapılmış adımlar atlanır.
"""

import uuid

import frappe
from frappe.utils.nestedset import rebuild_tree

PC = "Product Category"

# (ad, en, ar, ru, icon_class, sort_order)
TOPS = [
	("Sağlık", "Health", "الصحة", "Здоровье", "heart-pulse", 1),
	("Gıda", "Food", "الغذاء", "Продукты", "utensils-crossed", 2),
	("Tarım", "Agriculture", "الزراعة", "Сельское хозяйство", "sprout", 3),
	("Elektronik", "Electronics", "الإلكترونيات", "Электроника", "cpu", 4),
	("Ev & Bahçe", "Home & Garden", "المنزل والحديقة", "Дом и сад", "home", 5),
	("Moda", "Fashion", "الموضة", "Мода", "shirt", 6),
	("Ofis & Kırtasiye", "Office & Stationery", "المكتب والقرطاسية", "Офис и канцелярия", "briefcase", 7),
	("Hobi & Sanat", "Hobby & Art", "الهوايات والفنون", "Хобби и искусство", "paintbrush", 8),
	("Makine", "Machinery", "الآلات", "Машины и оборудование", "cog", 9),
	("Yapı & Hırdavat", "Construction & Hardware", "البناء والأدوات", "Строительство и инструменты", "hard-hat", 10),
	("Otomotiv", "Automotive", "السيارات", "Автомобили", "car", 11),
	("Hizmet", "Services", "الخدمات", "Услуги", "wrench", 12),
]

# Eski sektör → yeni ad (kayıt yeniden kullanılır)
RENAMES = {"Perakende": "Ev & Bahçe", "Endüstri": "Makine", "Sanat": "Hobi & Sanat"}

_log = []


def log(msg):
	_log.append(msg)
	print(msg)


def _slug(name, ident):
	tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")
	import re

	base = re.sub(r"[^a-z0-9]+", "-", name.translate(tr_map).lower()).strip("-")
	return f"{base}-{ident[:8]}"


def top(name):
	return frappe.db.get_value(
		PC, {"category_name": name, "parent_product_category": ("is", "not set"), "is_active": 1}, "name"
	)


def child(parent, name):
	return frappe.db.get_value(
		PC, {"category_name": name, "parent_product_category": parent, "is_active": 1}, "name"
	)


def children(node):
	return frappe.get_all(PC, filters={"parent_product_category": node, "is_active": 1}, fields=["name", "category_name"])


def set_parent(node, parent):
	frappe.db.set_value(PC, node, "parent_product_category", parent, update_modified=True)


def move_listings(src, dst):
	n = frappe.db.count("Listing", {"product_category": src})
	if n:
		frappe.db.sql("update `tabListing` set product_category=%s where product_category=%s", (dst, src))
		log(f"    {n} ilan taşındı: {src[:8]} → {dst[:8]}")


def set_name(node, name):
	"""Ad + Türkçe çeviri alanı birlikte; API adı category_name_tr üzerinden çözer."""
	frappe.db.set_value(PC, node, {"category_name": name, "category_name_tr": name}, update_modified=True)


def deactivate(node):
	frappe.db.set_value(PC, node, "is_active", 0, update_modified=True)


def merge(src, dst, label=""):
	"""src'nin alt ağacını ad eşleşmesiyle dst'ye katar, src'yi pasife alır."""
	for ch in children(src):
		twin = child(dst, ch.category_name)
		if twin:
			merge(ch.name, twin, f"{label}/{ch.category_name}")
		else:
			set_parent(ch.name, dst)
	move_listings(src, dst)
	deactivate(src)


def promote(group, new_parent):
	"""Grubun çocuklarını new_parent altına çıkarır, grubu pasife alır."""
	for ch in children(group):
		set_parent(ch.name, new_parent)
	move_listings(group, new_parent)
	deactivate(group)


def ensure_top(name, en, ar, ru, icon, sort):
	node = top(name)
	if node:
		frappe.db.set_value(
			PC,
			node,
			{
				"category_name_tr": name,
				"category_name_en": en,
				"category_name_ar": ar,
				"category_name_ru": ru,
				"icon_class": icon,
				"sort_order": sort,
			},
			update_modified=True,
		)
		return node
	ident = str(uuid.uuid4())
	doc = frappe.get_doc(
		{
			"doctype": PC,
			"external_id": ident,
			"category_name": name,
			"category_name_en": en,
			"category_name_ar": ar,
			"category_name_ru": ru,
			"icon_class": icon,
			"sort_order": sort,
			"is_active": 1,
			"url_slug": _slug(name, ident),
		}
	)
	doc.insert(ignore_permissions=True)
	log(f"  yeni ana kategori: {name} ({doc.name[:8]})")
	return doc.name


def run(dry_run=0):
	dry_run = frappe.utils.cint(dry_run)
	frappe.flags.ignore_permissions = True

	# 0) Eski sektörleri yeniden adlandır (kayıt korunur)
	for old, new in RENAMES.items():
		node = top(old)
		if node:
			set_name(node, new)
			frappe.db.set_value(PC, node, "url_slug", _slug(new, node), update_modified=True)
			log(f"  yeniden adlandırıldı: {old} → {new} ({node[:8]})")

	# 1) 12 ana kategoriyi hazırla
	T = {}
	for name, en, ar, ru, icon, sort in TOPS:
		T[name] = ensure_top(name, en, ar, ru, icon, sort)

	# 2) Gıda › Tarım → Tarım (ana)
	g = child(T["Gıda"], "Tarım")
	if g:
		log("Tarım grubunu ana kategoriye çıkar")
		promote(g, T["Tarım"])

	# 3) Perakende (→ Ev & Bahçe) dağılımı
	ev_bahce = T["Ev & Bahçe"]
	ev = child(ev_bahce, "Ev")
	ev_yasam = child(ev_bahce, "Ev & Yaşam")
	if ev and ev_yasam:
		log("Ev → Ev & Yaşam birleştir")
		merge(ev, ev_yasam)
	if ev_yasam:
		log("Ev & Yaşam gruplarını Ev & Bahçe altına çıkar")
		promote(ev_yasam, ev_bahce)

	moda = child(ev_bahce, "Moda")
	if moda:
		log("Moda → Moda (ana)")
		promote(moda, T["Moda"])

	ofis = child(ev_bahce, "Ofis")
	ofis_k = child(ev_bahce, "Ofis & Kırtasiye")
	if ofis and ofis_k:
		log("Ofis → Ofis & Kırtasiye birleştir")
		merge(ofis, ofis_k)
	if ofis_k:
		for src_name, dst_name in (("Yazıcı & Sarf", "Yazıcı & Baskı"), ("Mobilya", "Ofis Mobilya")):
			s, d = child(ofis_k, src_name), child(ofis_k, dst_name)
			if s and d:
				log(f"  {src_name} → {dst_name} birleştir")
				merge(s, d)
		log("Ofis & Kırtasiye gruplarını ana kategoriye çıkar")
		promote(ofis_k, T["Ofis & Kırtasiye"])
	kitap = child(ev_bahce, "Kitap & Medya")
	if kitap:
		set_parent(kitap, T["Ofis & Kırtasiye"])
		log("Kitap & Medya → Ofis & Kırtasiye")

	spor, spor_o = child(ev_bahce, "Spor"), child(ev_bahce, "Spor & Outdoor")
	if spor and spor_o:
		log("Spor → Spor & Outdoor birleştir")
		merge(spor, spor_o)
	oyuncak, oyuncak_h = child(ev_bahce, "Oyuncak"), child(ev_bahce, "Oyuncak & Hobi")
	if oyuncak and oyuncak_h:
		log("Oyuncak → Oyuncak & Hobi birleştir")
		merge(oyuncak, oyuncak_h)
	for name in ("Spor & Outdoor", "Oyuncak & Hobi", "Müzik"):
		n = child(ev_bahce, name)
		if n:
			set_parent(n, T["Hobi & Sanat"])
			log(f"{name} → Hobi & Sanat")

	oto = child(ev_bahce, "Oto Aksesuar")
	if oto:
		set_parent(oto, T["Otomotiv"])
		log("Oto Aksesuar → Otomotiv")

	# 4) Endüstri (→ Makine) dağılımı
	makine = T["Makine"]
	yapi = child(makine, "Yapı")
	if yapi:
		log("Yapı gruplarını Yapı & Hırdavat altına çıkar")
		promote(yapi, T["Yapı & Hırdavat"])
	for name in ("Güvenlik", "Malzeme"):
		n = child(makine, name)
		if n:
			set_parent(n, T["Yapı & Hırdavat"])
			log(f"{name} → Yapı & Hırdavat")
	imalat = child(makine, "Makine")
	if imalat:
		set_name(imalat, "İmalat Makineleri")
		log("Makine › Makine grubu → İmalat Makineleri")
	malzeme = child(T["Yapı & Hırdavat"], "Malzeme")
	if malzeme:
		set_name(malzeme, "Hammadde & Malzeme")
		log("Malzeme grubu → Hammadde & Malzeme")
	for parent, name in ((makine, "İmalat Makineleri"), (T["Yapı & Hırdavat"], "Hammadde & Malzeme")):
		n = child(parent, name)
		if n:
			set_name(n, name)
	# Mega menü sütunu 200px; en uzun grup adı tek satıra sığsın diye kısaltma.
	masa = child(T["Ofis & Kırtasiye"], "Masa Üstü & Organizasyon")
	if masa:
		set_name(masa, "Masa Organizasyonu")
		log("Masa Üstü & Organizasyon → Masa Organizasyonu")
	tasit = child(makine, "Taşıtlar")
	if tasit:
		log("Taşıtlar gruplarını Otomotiv altına çıkar")
		promote(tasit, T["Otomotiv"])

	# 5) Ağacı yeniden kur
	rebuild_tree(PC, "parent_product_category")

	# Özet
	tops = frappe.get_all(
		PC,
		filters={"parent_product_category": ("is", "not set"), "is_active": 1},
		fields=["category_name", "sort_order"],
		order_by="sort_order asc",
	)
	log("Ana kategoriler: " + " · ".join(f"{t.category_name}" for t in tops))
	for t in frappe.get_all(PC, filters={"parent_product_category": ("is", "not set"), "is_active": 1}, fields=["name", "category_name"], order_by="sort_order asc"):
		grp = [c.category_name for c in children(t.name)]
		log(f"  {t.category_name} ({len(grp)}): {', '.join(grp)}")

	if dry_run:
		frappe.db.rollback()
		log("DRY RUN — geri alındı")
	else:
		frappe.db.commit()
		frappe.clear_cache()
		log("Kaydedildi")
	return _log
