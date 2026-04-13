import json
import re
import frappe
from frappe import _


def _slugify(text):
    """Türkçe karakterleri dönüştürüp URL slug üretir."""
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")
    text = text.translate(tr_map).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


# ──────────────────────────── Public ──────────────────────────────────────────

@frappe.whitelist(allow_guest=True)
def get_mega_menu():
    """
    Mega menu için üst 2 seviye kategoriyi döndürür.
    "Marketplace" gibi tek bir virtual root varsa onun çocukları döndürülür.
    Returns: [{ id, name, slug, children: [{ id, name, slug }] }]
    """
    cats = frappe.get_all(
        "Product Category",
        filters={"is_active": 1},
        fields=["name", "category_name", "parent_product_category", "url_slug", "sort_order", "lft", "rgt", "image", "icon_class"],
        order_by="sort_order asc, lft asc",
    )

    if not cats:
        return []

    active_ids = {c.name for c in cats}

    # Virtual root'ları bul (parent'ı olmayan veya aktif olmayan)
    virtual_roots = [c for c in cats if not c.parent_product_category or c.parent_product_category not in active_ids]

    # Eğer tek bir virtual root varsa (ör: "Marketplace"), onun çocuklarını al
    if len(virtual_roots) == 1:
        top_parent = virtual_roots[0].name
        top_cats = [c for c in cats if c.parent_product_category == top_parent]
    else:
        top_cats = virtual_roots

    result = []
    for top in top_cats:
        children = [c for c in cats if c.parent_product_category == top.name]
        result.append({
            "id": top.name,
            "name": top.category_name,
            "slug": top.url_slug or _slugify(top.category_name),
            "image": top.image or None,
            "icon_class": top.icon_class or None,
            "children": [
                {
                    "id": ch.name,
                    "name": ch.category_name,
                    "slug": ch.url_slug or _slugify(ch.category_name),
                    "image": ch.image or None,
                }
                for ch in children
            ],
        })

    return result


# ──────────────────────────── Seller / Public ─────────────────────────────────

@frappe.whitelist()
def get_platform_category_tree(parent=None):
    """
    Satıcıların ürün yüklerken platform kategorisi seçmesi için.
    Giriş yapmış herkes (satıcı dahil) çağırabilir; yalnızca aktif kategoriler döner.
    parent=None → kök kategoriler; parent=<id> → o kategorinin aktif çocukları.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)

    filters = {"is_active": 1}
    if parent:
        filters["parent_product_category"] = parent
    else:
        filters["parent_product_category"] = ["is", "not set"]

    cats = frappe.get_all(
        "Product Category",
        filters=filters,
        fields=["name", "category_name", "parent_product_category", "url_slug", "sort_order", "image", "icon_class"],
        order_by="sort_order asc, lft asc",
    )
    for c in cats:
        c["child_count"] = frappe.db.count(
            "Product Category",
            {"parent_product_category": c.name, "is_active": 1},
        )
    return cats


@frappe.whitelist()
def get_category_ancestors(name):
    """
    Verilen kategori ID'si için kök'e kadar tüm ata listesini döndürür.
    Satıcının seçtiği kategorinin tam yolunu (breadcrumb) göstermek için kullanılır.
    Döner: [{ name, category_name }, ...] — kökten yaprağa sıralı
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)

    path = []
    current = name
    seen = set()
    while current and current not in seen:
        seen.add(current)
        row = frappe.db.get_value(
            "Product Category", current,
            ["name", "category_name", "parent_product_category"],
            as_dict=True,
        )
        if not row:
            break
        path.append({"name": row.name, "category_name": row.category_name})
        current = row.parent_product_category

    path.reverse()
    return path


# ──────────────────────────── Admin CRUD ──────────────────────────────────────

@frappe.whitelist()
def get_category_tree(parent=None):
    """
    Admin panel için kategori ağacı.
    parent=None → kök kategoriler; parent=<id> → o kategorinin çocukları
    """
    _require_admin()
    filters = {"parent_product_category": parent or ["is", "not set"]}
    cats = frappe.get_all(
        "Product Category",
        filters=filters,
        fields=["name", "category_name", "parent_product_category", "is_active", "sort_order", "url_slug", "lft", "rgt"],
        order_by="sort_order asc, lft asc",
    )
    # Her kategorinin çocuk sayısını ekle
    for c in cats:
        c["child_count"] = frappe.db.count("Product Category", {"parent_product_category": c.name})
    return cats


@frappe.whitelist()
def create_category(category_name, parent_id=None, sort_order=0, is_active=1, icon_class=None, url_slug=None, image=None):
    _require_admin()
    import uuid
    ext_id = str(uuid.uuid4())
    base_slug = url_slug or _slugify(category_name)

    # Slug unique kontrolü — çakışırsa sona sayaç ekle
    slug = base_slug
    counter = 1
    while frappe.db.exists("Product Category", {"url_slug": slug}):
        slug = f"{base_slug}-{counter}"
        counter += 1

    doc = frappe.new_doc("Product Category")
    doc.external_id = ext_id
    doc.category_name = category_name
    doc.parent_product_category = parent_id or None
    doc.sort_order = int(sort_order)
    doc.is_active = int(is_active)
    doc.icon_class = icon_class or ""
    doc.url_slug = slug
    if image is not None:
        doc.image = image
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name, "external_id": ext_id, "url_slug": slug}


@frappe.whitelist()
def update_category(name, category_name=None, parent_id=None, sort_order=None, is_active=None, icon_class=None, url_slug=None, image=None):
    _require_admin()
    doc = frappe.get_doc("Product Category", name)
    if category_name is not None:
        doc.category_name = category_name
    if parent_id is not None:
        doc.parent_product_category = parent_id or None
    if sort_order is not None:
        doc.sort_order = int(sort_order)
    if is_active is not None:
        doc.is_active = int(is_active)
    if icon_class is not None:
        doc.icon_class = icon_class
    if url_slug is not None:
        # Başka bir kategoride aynı slug var mı?
        existing = frappe.db.get_value("Product Category", {"url_slug": url_slug}, "name")
        if existing and existing != name:
            frappe.throw(_("Bu URL slug başka bir kategoride kullanılıyor: {0}").format(existing))
        doc.url_slug = url_slug
    if image is not None:
        doc.image = image
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True}


@frappe.whitelist()
def delete_category(name):
    _require_admin()
    child_count = frappe.db.count("Product Category", {"parent_product_category": name})
    if child_count > 0:
        frappe.throw(_("Bu kategorinin {0} alt kategorisi var. Önce onları silin.").format(child_count))
    frappe.delete_doc("Product Category", name, ignore_permissions=True)
    frappe.db.commit()
    return {"success": True}


def _delete_single(name):
    """Tek bir kategoriyi linkleri görmezden gelerek kalıcı siler."""
    # force=1 + ignore_on_trash=True link/submit kontrollerini atlar (v15)
    frappe.delete_doc(
        "Product Category",
        name,
        force=1,
        ignore_permissions=True,
        ignore_on_trash=True,
        delete_permanently=True,
    )


def _delete_cascade(name):
    """Verilen kategoriyi ve tüm alt ağacını yapraktan köke doğru siler."""
    children = frappe.get_all(
        "Product Category",
        filters={"parent_product_category": name},
        pluck="name",
    )
    for child in children:
        _delete_cascade(child)
    _delete_single(name)


@frappe.whitelist()
def bulk_delete_categories(names):
    """
    Verilen kategori ID listesini ve alt ağaçlarını siler.
    names: JSON string veya liste — ["cat1", "cat2", ...]
    """
    _require_admin()
    if isinstance(names, str):
        try:
            names = json.loads(names)
        except (ValueError, TypeError):
            frappe.throw(_("Geçersiz kategori listesi"))
    if not isinstance(names, list) or not names:
        frappe.throw(_("Silinecek kategori seçilmedi"))

    # Seçilenler arasında biri diğerinin alt öğesiyse sadece üst olanı sil
    # (çünkü cascade zaten alt ağacı götürecek)
    to_delete = set(names)
    remaining = []
    for name in to_delete:
        if not frappe.db.exists("Product Category", name):
            continue
        ancestor = frappe.db.get_value("Product Category", name, "parent_product_category")
        skip = False
        while ancestor:
            if ancestor in to_delete:
                skip = True
                break
            ancestor = frappe.db.get_value("Product Category", ancestor, "parent_product_category")
        if not skip:
            remaining.append(name)

    deleted = 0
    errors = []
    for name in remaining:
        try:
            _delete_cascade(name)
            frappe.db.commit()
            deleted += 1
        except Exception as e:
            frappe.db.rollback()
            errors.append(f"{name}: {str(e)[:120]}")

    return {"success": True, "deleted": deleted, "errors": errors[:5]}


@frappe.whitelist()
def delete_all_categories():
    """Tüm Product Category kayıtlarını yapraktan köke doğru siler."""
    _require_admin()
    # lft desc sırası yapraklardan başlatır (NSM tree güvenliği)
    rows = frappe.get_all(
        "Product Category",
        fields=["name"],
        order_by="lft desc",
    )
    deleted = 0
    errors = []
    for r in rows:
        try:
            _delete_single(r.name)
            frappe.db.commit()
            deleted += 1
        except Exception as e:
            frappe.db.rollback()
            errors.append(f"{r.name}: {str(e)[:120]}")
    return {"success": True, "deleted": deleted, "errors": errors[:5]}


# ──────────────────────────── Import ──────────────────────────────────────────

@frappe.whitelist()
def import_categories(json_data):
    """
    JSON formatındaki kategori ağacını içe aktarır.
    Format: [{ id, name, parent_id, ... }]
    Mevcut kategorilerin üzerine yazar (external_id eşleşmesiyle).
    """
    _require_admin()

    if isinstance(json_data, str):
        try:
            items = json.loads(json_data)
        except (ValueError, TypeError):
            frappe.throw(_("Geçersiz JSON verisi"))
    else:
        items = json_data

    if not isinstance(items, list):
        frappe.throw(_("JSON bir liste olmalı"))

    # id → item mapping
    by_id = {item["id"]: item for item in items}

    # Root'u bul (parent_id=null)
    roots = [item for item in items if not item.get("parent_id")]
    if not roots:
        frappe.throw(_("Kök kategori bulunamadı (parent_id=null olan kayıt yok)"))

    # Mevcut external_id'leri çek
    existing = {
        row.external_id: row.name
        for row in frappe.get_all("Product Category", fields=["name", "external_id"])
        if row.external_id
    }

    inserted = 0
    updated = 0
    skipped = 0

    # BFS sırasıyla işle (parent'lar önce eklensin)
    from collections import deque
    queue = deque(roots)
    visited = set()

    while queue:
        item = queue.popleft()
        item_id = item["id"]

        if item_id in visited:
            continue
        visited.add(item_id)

        # Parent henüz işlenmediyse sona at
        parent_id = item.get("parent_id")
        if parent_id and parent_id not in visited and parent_id in by_id:
            queue.append(item)
            # Sonsuz döngüyü önle
            if len(visited) + len(queue) > len(items) * 2:
                skipped += 1
                continue
            continue

        # Frappe parent adı: parent'ın external_id'si = parent'ın name'i
        frappe_parent = parent_id if parent_id and parent_id in by_id else None

        cat_name = (item.get("name") or "").strip()
        if not cat_name:
            skipped += 1
            continue

        # url_slug: unique olması için UUID'nin ilk 8 karakterini ekle
        slug = _slugify(cat_name) + "-" + item_id[:8]

        if item_id in existing:
            # Güncelle
            try:
                doc = frappe.get_doc("Product Category", existing[item_id])
                doc.category_name = cat_name
                doc.parent_product_category = frappe_parent
                doc.url_slug = slug
                doc.is_active = 1
                doc.save(ignore_permissions=True)
                updated += 1
            except Exception:
                skipped += 1
        else:
            # Yeni ekle
            try:
                doc = frappe.new_doc("Product Category")
                doc.external_id = item_id
                doc.category_name = cat_name
                doc.parent_product_category = frappe_parent
                doc.url_slug = slug
                doc.is_active = 1
                doc.sort_order = 0
                doc.insert(ignore_permissions=True)
                existing[item_id] = doc.name
                inserted += 1
            except Exception as e:
                frappe.log_error(f"Category import error: {item_id} / {cat_name}: {e}")
                skipped += 1

        # Çocukları kuyruğa ekle
        for child in items:
            if child.get("parent_id") == item_id and child["id"] not in visited:
                queue.append(child)

    frappe.db.commit()

    # NSM ağacını yeniden oluştur
    rebuild_warning = None
    try:
        frappe.utils.nestedset.rebuild_tree("Product Category", "parent_product_category")
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"rebuild_tree error: {e}")
        rebuild_warning = _("Kategori ağacı yeniden oluşturulurken hata oluştu. Kategori sıralaması bozuk olabilir, lütfen sayfayı yenileyin.")

    result = {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "total": len(items),
    }
    if rebuild_warning:
        result["warning"] = rebuild_warning
    return result


# ──────────────────────────── Async Import ───────────────────────────────────

def _import_cache_key(job_key):
    return f"tradehub_category_import:{job_key}"


def _update_progress(job_key, **fields):
    key = _import_cache_key(job_key)
    current = frappe.cache.get_value(key) or {}
    current.update(fields)
    frappe.cache.set_value(key, current, expires_in_sec=3600)


def _run_category_import(json_str, job_key):
    """
    Background worker: büyük kategori JSON'unu import eder.
    İlerleme cache'e yazılır, frontend polling ile okur.
    """
    try:
        items = json.loads(json_str) if isinstance(json_str, str) else json_str
        total = len(items)

        # O(n) child index — eski kod her item için tüm listeyi tarıyordu
        children_by_parent = {}
        for item in items:
            children_by_parent.setdefault(item.get("parent_id"), []).append(item)

        by_id = {item["id"]: item for item in items}

        existing = {
            row.external_id: row.name
            for row in frappe.get_all("Product Category", fields=["name", "external_id"])
            if row.external_id
        }

        _update_progress(
            job_key,
            state="running", total=total,
            inserted=0, updated=0, skipped=0, processed=0,
        )

        from collections import deque
        queue = deque(children_by_parent.get(None, []))
        visited = set()
        inserted = updated = skipped = 0
        last_flush = 0

        while queue:
            item = queue.popleft()
            item_id = item["id"]
            if item_id in visited:
                continue
            visited.add(item_id)

            parent_id = item.get("parent_id")
            frappe_parent = parent_id if parent_id and parent_id in by_id else None
            cat_name = (item.get("name") or "").strip()

            if not cat_name:
                skipped += 1
            else:
                slug = _slugify(cat_name) + "-" + item_id[:8]
                try:
                    if item_id in existing:
                        doc = frappe.get_doc("Product Category", existing[item_id])
                        doc.category_name = cat_name
                        doc.parent_product_category = frappe_parent
                        doc.url_slug = slug
                        doc.is_active = 1
                        doc.save(ignore_permissions=True)
                        updated += 1
                    else:
                        doc = frappe.new_doc("Product Category")
                        doc.external_id = item_id
                        doc.category_name = cat_name
                        doc.parent_product_category = frappe_parent
                        doc.url_slug = slug
                        doc.is_active = 1
                        doc.sort_order = 0
                        doc.insert(ignore_permissions=True)
                        existing[item_id] = doc.name
                        inserted += 1
                except Exception as e:
                    frappe.log_error(f"Category import error: {item_id} / {cat_name}: {e}")
                    skipped += 1

            for child in children_by_parent.get(item_id, []):
                if child["id"] not in visited:
                    queue.append(child)

            processed = inserted + updated + skipped
            if processed - last_flush >= 100:
                frappe.db.commit()
                _update_progress(
                    job_key, state="running",
                    inserted=inserted, updated=updated, skipped=skipped,
                    processed=processed, total=total,
                )
                last_flush = processed

        frappe.db.commit()

        warning = None
        try:
            frappe.utils.nestedset.rebuild_tree("Product Category", "parent_product_category")
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"rebuild_tree error: {e}")
            warning = _("Kategori ağacı yeniden oluşturulurken hata oluştu. Sıralama bozuk olabilir.")

        _update_progress(
            job_key, state="done",
            inserted=inserted, updated=updated, skipped=skipped,
            processed=total, total=total, warning=warning,
        )
    except Exception as e:
        frappe.log_error(f"_run_category_import error: {e}")
        _update_progress(job_key, state="error", error=str(e)[:500])


@frappe.whitelist()
def start_category_import(json_data):
    """JSON içe aktarmayı background job olarak başlatır ve job_key döner."""
    _require_admin()

    if isinstance(json_data, str):
        try:
            items = json.loads(json_data)
            json_str = json_data
        except (ValueError, TypeError):
            frappe.throw(_("Geçersiz JSON verisi"))
    else:
        items = json_data
        json_str = json.dumps(items)

    if not isinstance(items, list) or not items:
        frappe.throw(_("JSON bir liste olmalı ve boş olmamalı"))

    import uuid
    job_key = uuid.uuid4().hex[:16]

    _update_progress(
        job_key, state="queued", total=len(items),
        inserted=0, updated=0, skipped=0, processed=0,
    )

    frappe.enqueue(
        "tradehub_core.api.category._run_category_import",
        queue="long",
        timeout=1800,
        json_str=json_str,
        job_key=job_key,
    )

    return {"job_key": job_key, "total": len(items)}


@frappe.whitelist()
def get_category_import_status(job_key):
    """Background import job'unun durumunu döner."""
    _require_admin()
    val = frappe.cache.get_value(_import_cache_key(job_key))
    if not val:
        return {"state": "not_found"}
    return val


# ──────────────────────────── Helper ──────────────────────────────────────────

def _require_admin():
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)
    roles = frappe.get_roles(user)
    if "System Manager" not in roles and user != "Administrator":
        frappe.throw(_("Bu işlem için yönetici yetkisi gerekiyor"), frappe.PermissionError)
