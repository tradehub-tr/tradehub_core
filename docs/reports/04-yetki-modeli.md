# 04 — Medya yetki modeli: rol kapıları, satıcı izolasyonu, PII, imzalı URL

**Görev:** T-005 · **Tarih:** 2026-08-17 · **Branch:** `medya-motoru-faz0-faz2`
**Kapsam:** Medya uçlarına kimin erişebildiği; satıcının başka satıcının dosyasına
erişememesini sağlayan tam kod yolu; PII/KVKK koruması; imzalı süreli URL modeli.

> Bu rapor **mevcut kodu belgeler**. Sayıların her biri `dosya:satır` ile işaretlidir.
> Ölçüm gerektirip yapılamayanlar §9'da.

---

## 1. Modelin özeti: dört bağımsız katman

Medyada tek bir yetki mekanizması yok, dört ayrı katman üst üste biniyor. Hangi katmanın
hangi soruyu cevapladığını karıştırmak, bu kod tabanında en kolay yapılacak hata:

| # | Katman | Soru | Uygulandığı yer |
|---|---|---|---|
| L0 | **Frappe DocType izni** | Bu kullanıcı `File` kaydını okuyabilir mi? | `frappe/core/doctype/file/file.py:872-911` (`has_permission`), `:914-927` (query conditions) |
| L1 | **Rol kapısı** | Bu kullanıcı yönetim ucunu çağırabilir mi? | `api/media_admin.py:43-78` (`_guard` / `_guard_destructive`) |
| L2 | **Kiracı (mağaza) izolasyonu** | Bu dosya bu mağazanın mı? | `media/ownership.py` (tamamı, 273 satır) |
| L3 | **PII / KVKK kapısı** | Bu dosya herkese açık YAPILABİLİR mi? | `media/access_level.py:72-92` + `media/presets.py:44-76` |

L1 ve L2 **birbirinin yerine geçmez.** Yönetim uçları rol sorar, satıcı uçları rol
sormaz — sahiplik sorar. Bu ayrım `api/seller_media.py:5-10` başlığında açıkça yazılı:

> *"Yetki rol değil sahiplik. Yönetim uçları rol istiyor. Burada rol yetmez: giriş yapmış
> her satıcı kendi kütüphanesini görür, ama YALNIZ kendisininkini. Mağaza parametre
> olarak DIŞARIDAN alınmaz — alınsaydı satıcı başkasının mağaza kodunu yazıp verisini
> görebilirdi."*

---

## 2. L1 — Yönetim uçlarının rol kapıları

### 2.1 İki rol kümesi

`api/media_admin.py:32-37`:

```python
ALLOWED_ROLES: tuple[str, ...] = ("System Manager", "Marketplace Admin")   # :32
# Geri alınamaz işlemler yalnız en yüksek role açık.
DESTRUCTIVE_ROLES: tuple[str, ...] = ("System Manager",)                   # :37
```

`_guard()` (`:43-44`) → `ALLOWED_ROLES`; `_guard_destructive()` (`:47-48`) → `DESTRUCTIVE_ROLES`.
İkisi de `_only_for()` (`:51-78`) üzerinden geçer:

```python
def _only_for(roles, scope):
    try:
        frappe.only_for(list(roles))          # :66
    except frappe.PermissionError:
        ...
        audit.log_media_event(
            action=audit.ACTION_ACCESS_DENIED,  # :74
            allowed=False,
            reason=f"missing_role:{scope}",
            context={"required_roles": list(roles), "endpoint": endpoint},
        )
        raise                                   # :80
```

Üç tasarım kararı burada:

1. **Reddediş kayda geçer.** `frappe.only_for` tek başına iz bırakmaz (`:55-57` yorumu).
2. **Denetim yazımı reddi yutamaz.** `frappe.form_dict` HTTP dışı bağlamda yoksa oradaki
   `AttributeError` `PermissionError`'ı maskeleyip çağırana **yanlış hata tipi**
   döndürürdü — bu yüzden ayrı `try/except` (`:68-71`).
3. **`Administrator` bu kapıdan hiç geçmez.** `frappe.only_for` Administrator'ı tamamen
   atlar (`:59-62` yorumu) — dolayısıyla Administrator için ret kaydı hiç oluşmaz,
   işlemleri yalnız başarı kayıtlarından izlenir.

### 2.2 Uç dağılımı (sayım)

`grep -n "_guard()\|_guard_destructive()" tradehub_core/api/media_admin.py | wc -l`

| Kapı | Uç sayısı | Örnekler |
|---|---:|---|
| `_guard()` — System Manager **veya** Marketplace Admin | **27** | `get_image_inventory` (:102), `browse_media` (:541), `set_access_level` (:470), `get_private_files` (:486), `export_media_audit` (:667), `plan_media_restore` (:739) |
| `_guard_destructive()` — yalnız System Manager | **12** | `delete_trashed` (:328), `purge_trash` (:350), `purge_archive` (:372), `repair_dangling_references` (:614), `apply_media_restore` (:761), `delete_media_backup` (:803), `download_media_backup_export` (:859) |
| **Toplam whitelisted** | **39** | — |

`api/media_admin.py` içindeki **her** `@frappe.whitelist()` ucu bir kapı çağırıyor —
kapısız uç yok (`grep` ile doğrulandı: 39 whitelist, 39 guard çağrısı).

### 2.3 `_guard_destructive` sınırının gerekçesi

`api/media_admin.py:34-36`:

> *"Arşiv silindikten sonra optimize edilmiş görsellerin orijinali sistemde kalmıyor —
> bu yetkiyi `Marketplace Admin` seviyesine açmak geri dönüşü olmayan bir riski yayar."*

Yani ayrım "okuma/yazma" değil, **geri alınabilirlik**. `trash_files` (`:279`) geri
alınabilir olduğu için `_guard()`; `delete_trashed` (`:328`) geri alınamaz olduğu için
`_guard_destructive()`.

---

## 3. L2 — Satıcı izolasyonu: "başkasının dosyasına erişemez" tam olarak nerede

Bu, T-005'in çekirdek sorusu. Cevap **tek satır değil, dört savunma katmanı**.

### 3.1 Katman A — Mağaza dışarıdan alınmaz, oturumdan çözülür

`api/seller_media.py:34-54`:

```python
def _store() -> str:
    try:
        return ownership.current_store()        # :41
    except frappe.PermissionError:
        ...
        audit.log_media_event(
            action=audit.ACTION_ACCESS_DENIED,  # :47
            allowed=False, reason="no_store",
        )
        raise
```

`ownership.current_store()` (`media/ownership.py:47-58`):

```python
def current_store() -> str:
    store = store_of()                          # :55
    if not store:
        frappe.throw(_("Bu işlem için bir mağaza hesabı gerekiyor."),
                     frappe.PermissionError)    # :57
    return store
```

`store_of()` (`ownership.py:37-44`) `utils/tenant._get_seller_profile_for_user()`'ı
çağırır (`:44`). Çözüm sırası (`utils/tenant.py:143-149`):

1. `User.tradehub_tenant` — alt kullanıcı davetiyle set edilen mağaza
2. `Admin Seller Profile.user = session.user` + `status = "Active"`
3. `Admin Seller Profile.user = session.user` (status'suz)
4. `Admin Seller Profile.email = session.user` (legacy)

`Guest` ve `Administrator` bu fonksiyondan **her zaman `None`** alır
(`utils/tenant.py:129-130`) → `current_store()` `PermissionError` atar → **Administrator
bile satıcı uçlarını kullanamaz.**

> **Sessiz boş liste yerine açık ret.** `ownership.py:50-53`: *"boş liste dönmek yerine
> açıkça reddediliyor, çünkü sessiz boş liste 'hiç dosyam yok' gibi okunur ve gerçek bir
> yetki sorununu gizler."*

**Sonuç:** `api/seller_media.py` içindeki **21 whitelisted ucun tamamı** `_store()`
çağırıyor (doğrudan ya da `_toplu` üzerinden — `:172`). `store` hiçbir uçta parametre
değil. `grep -c "@frappe.whitelist" api/seller_media.py` → 21.

### 3.2 Katman B — Tek dosya işlemleri: `assert_owns`

`media/ownership.py:218-226`:

```python
def assert_owns(store: str, file_url: str) -> None:
    if not owns(store, file_url):
        frappe.throw(frappe._("Dosya bulunamadı."), frappe.DoesNotExistError)   # :226
```

**Hata mesajı bilinçli olarak "bulunamadı" diyor, "yetkiniz yok" demiyor**
(`ownership.py:221-223`): ikincisi dosyanın VAR olduğunu doğrular ve başka satıcının
dosya adlarını deneme yoluyla keşfetmeye kapı bırakır.

`owns()` (`:213-215`) → `store in owners_of(file_url)`.

`owners_of()` (`:151-171`) **küme** döndürür, tek değer değil:

```python
sahipler = frappe.db.get_all("File", filters={"file_url": url},
                             pluck="owner", distinct=True)      # :166-168
magazalar = {s for s in (store_of(k) for k in sahipler) if s}   # :169  YÜKLEYEN
magazalar |= _stores_using(url)                                 # :170  KULLANAN
```

İki sahiplik yolu var ve ikisi de gerekli:

| Yol | Neden | Kaynak |
|---|---|---|
| **Yükleyen** | Hiçbir yere eklenmemiş dosyanın da sahibi olmalı | `ownership.py:5-12` |
| **Kullanan** | Satıcının ürününde duran ama yönetimin/toplu içe aktarımın yüklediği görsel, satıcının kütüphanesinde görünmeli | `ownership.py:106-116`, `:158-160` |

`_stores_using()` (`:174-198`) `usage.LIVE_SOURCES` tablolarında `_STORE_COLUMN`
haritasıyla (`:203-210`) ters arama yapar:

```python
_STORE_COLUMN = {
    "tabListing": "seller_profile",
    "tabListing Image": "(select seller_profile from tabListing l where l.name=parent)",
    "tabListing Variant Item": "(select seller_profile from tabListing l where l.name=parent)",
    "tabStorefront Layout": "seller_profile",
    "tabSeller Gallery Image": "parent",
    "tabAdmin Seller Profile": "name",
}
```

**Kullanıldığı yerler** (tek dosya işlemleri):

| Uç | Satır | Koruma |
|---|---|---|
| `get_my_usage` | `api/seller_media.py:106` | `ownership.assert_owns` |
| `get_dimensions` | `api/seller_media.py:457` | `ownership.assert_owns` |
| `rename` | `media/files.py:73` | `ownership.assert_owns` |
| `replace` | `media/files.py:166` | `ownership.assert_owns` + paylaşım reddi (`:168-175`) |
| `archive` | `media/seller_media.py:84` | `ownership.assert_owns` |
| `unarchive` | `media/seller_media.py:114` | `ownership.assert_owns` |
| `purge` | `media/seller_media.py:157` | `ownership.assert_owns` |

### 3.3 Katman C — Toplu işlemler: sessiz atlama, ifşasız

`api/seller_media.py:172-201` (`_toplu`):

```python
store = _store()
urls  = _urls(file_urls)                # MAX_BATCH = 200 (:31)
for url in urls:
    if not ownership.owns(store, url):  # :186
        atlanan += 1                    # :187
        continue
```

Sahibi olunmayan dosya `skipped` sayacına düşer ama **hangi dosya olduğu dönülmez**
(`api/seller_media.py:148-150`): *"sahibi olmadığı bir adresin varlığını doğrulamak keşif
kapısı açar."*

### 3.4 Katman D — Liste sorguları: SQL seviyesinde daraltma

`media/ownership.py:229-264` (`scope`) — bu, izolasyonun en kritik ve en incelikli parçası:

```python
kullanicilar = list(users_of(store))    # :241
adresler     = list(used_urls(store))   # :242

if not kullanicilar and not adresler:
    return query.where(f.owner.isin([""]))         # :245  ← FAIL-CLOSED
if not adresler:
    return query.where(f.owner.isin(kullanicilar)) # :247
if not kullanicilar:
    return query.where(f.file_url.isin(adresler))  # :249

kendi_kayitlari = frappe.qb.from_(f).select(f.file_url).where(f.owner.isin(kullanicilar))
return query.where(
    f.owner.isin(kullanicilar)
    | (f.file_url.isin(adresler) & f.file_url.notin(kendi_kayitlari))   # :261-263
)
```

Üç şey burada özellikle önemli:

1. **Fail-closed.** Mağazanın ne kullanıcısı ne kullanımı varsa sorgu `owner IN ("")` ile
   **hiçbir şey döndürmeyecek** hâle getirilir (`:244-245`). Süzgeci atlayıp tüm envanteri
   döndürmek, bir yapılandırma eksiğini doğrudan veri sızıntısına çevirirdi.
2. **`notin(kendi_kayitlari)` şartı bir regresyon düzeltmesi.** Yorumda (`:251-259`) kayıtlı:
   düz "VEYA" yazıldığında, mağaza A dosyayı bıraktığında B'nin listesinden de düşüyordu
   — çünkü liste satırları gruplayıp damgaların en küçüğüne bakıyor. Testler yakaladı.
3. `users_of()` (`:61-94`) mağazanın **alt kullanıcılarını da** kapsar
   (`User.tradehub_tenant` ile, `:87-89`) — aksi hâlde operasyon/finans kullanıcısının
   yüklediği her dosya kimsesiz görünürdü.

**Kullanıldığı yer:** `media/inventory.py:209` ve `:229` — `list_files(store=...)`
verildiğinde sorgu daraltılır. `api/seller_media.py:78-87` (`get_my_media`) bu yoldan geçer.

### 3.5 Katman E — Parçalı yükleme oturumları

`media/chunked.py:86-98`:

```python
def _read_meta(upload_id: str, store: str) -> dict:
    ...
    if meta.get("store") != store:     # :98
```

Oturum kimliği tahmin edilse bile başka mağazanın oturumuna parça eklenemez
(`chunked.py:25-26`). Kapsam **her adımda** yeniden doğrulanır: `put_chunk` (`:172`),
`finish` (`:207`), `cleanup_session` (`:235`), `meta_of` (`:241`).

### 3.6 Satıcının GÖREMEDİĞİ şeyler

`media/seller_media.py:28-29`: *"Satıcı diğer mağazaların varlığını hiçbir yanıtta
görmez — ne adı, ne sayısı, ne ürünü. Yalnız 'kaç sahip kaldı' sayısı denetim kaydına
yazılır."*

Uygulama:

- `get_my_usage` (`api/seller_media.py:99-107`) → `usage.resolve(file_url, store=store)`;
  başka mağazanın kullanımı yanıtta hiç geçmez (`:104-106` yorumu)
- `_assert_not_in_use` (`media/seller_media.py:56-68`) yalnız **kendi** kapsamındaki
  kullanımı sayar (`:59-61`)
- `purge` dönüşündeki `remaining_owners` (`media/seller_media.py:194`) bir **sayı**;
  mağaza adı değil

### 3.7 Silme = "bırakma", yıkım değil

Aynı dosyanın birden çok sahibi olabildiği için (`ownership.py:14-18`: *"30 adres iki
mağazaya birden ait"* — kod yorumundaki ölçüm, bu raporda tazelenmedi), satıcının silmesi
diğerinin ürününü kırmamalı:

`media/seller_media.py:157-185` (`purge`):

1. `assert_owns` + `_assert_not_in_use` (`:157-158`)
2. `refs.clear(file_url, store=store)` — **yalnız o mağazanın** kayıtlarındaki bağlar
   (`media/refs.py:154`)
3. Yalnız `_own_records()` (`:39-48`) ile bulunan **kendi** `File` kayıtları silinir
   (`:167-168`)
4. `owners_of()` tekrar sorulur; **sahip kalmadıysa** disk temizlenir (`:171-178`)

---

## 4. Rol → izin matrisi

Aşağıdaki matris kod okumasından türetilmiştir. Sütunlardaki roller:
`Administrator` (Frappe süper kullanıcı), `SM` = System Manager,
`MA` = Marketplace Admin, `Satıcı` = mağazası çözülen oturum (owner veya alt kullanıcı),
`Kayıtlı` = giriş yapmış ama mağazası olmayan kullanıcı, `Guest` = anonim.

### 4.1 Yönetim medya uçları (`api/media_admin.py`)

| Yetenek | Administrator | SM | MA | Satıcı | Kayıtlı | Guest | Kapı |
|---|:--:|:--:|:--:|:--:|:--:|:--:|---|
| Envanter listele / ara | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | `_guard` (:102) |
| Dosya kullanımını gör | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | `_guard` (:150) |
| Optimizasyon başlat | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | `_guard` (:181) |
| Arşivden geri yükle | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | `_guard` (:224, :242) |
| Çöpe taşı / çöpten çıkar | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | `_guard` (:279, :303) |
| **Private dosya listesi** | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | `_guard` (:486) |
| **Erişim seviyesi değiştir** | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | `_guard` (:470) + PII kapısı |
| Medya denetim kaydını oku | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | `_guard` (:428) |
| Denetim kaydını dışa aktar | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | `_guard` (:667) |
| Yedek listele / doğrula / planla | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | `_guard` (:705,:727,:739) |
| **Çöpten kalıcı sil** | ✔ | ✔ | ✖ | ✖ | ✖ | ✖ | `_guard_destructive` (:328) |
| **Çöp / arşiv purge** | ✔ | ✔ | ✖ | ✖ | ✖ | ✖ | `_guard_destructive` (:350,:372) |
| **Kırık referans onar** | ✔ | ✔ | ✖ | ✖ | ✖ | ✖ | `_guard_destructive` (:614) |
| **Yedek al / geri yükle / sil** | ✔ | ✔ | ✖ | ✖ | ✖ | ✖ | `_guard_destructive` (:714,:761,:803) |
| **Yedek dışa aktarımını indir** | ✔ | ✔ | ✖ | ✖ | ✖ | ✖ | `_guard_destructive` (:859) |

> `Administrator` sütunundaki ✔'lerin gerekçesi: `frappe.only_for` Administrator'ı atlar
> (`api/media_admin.py:59-60`). Bu, **ret denetim kaydının Administrator için hiç
> oluşmadığı** anlamına da gelir.

### 4.2 Satıcı medya uçları (`api/seller_media.py`)

| Yetenek | Administrator | SM | MA | Satıcı | Kayıtlı | Guest | Kapı |
|---|:--:|:--:|:--:|:--:|:--:|:--:|---|
| Kendi kütüphanesini listele | ✖¹ | ✖¹ | ✖¹ | ✔ (yalnız kendi) | ✖ | ✖ | `_store` + `ownership.scope` |
| Dosya yükle (tek atış) | ✖¹ | ✖¹ | ✖¹ | ✔ | ✖ | ✖ | `_store` (:255) |
| Parçalı yükleme | ✖¹ | ✖¹ | ✖¹ | ✔ | ✖ | ✖ | `_store` + `chunked` kapsamı |
| Arşivle / arşivden çıkar | ✖¹ | ✖¹ | ✖¹ | ✔ (yalnız kendi) | ✖ | ✖ | `_toplu` → `ownership.owns` |
| Kalıcı sil (bırak) | ✖¹ | ✖¹ | ✖¹ | ✔ (yalnız kendi) | ✖ | ✖ | `_toplu` → `ownership.owns` |
| Yeniden adlandır | ✖¹ | ✖¹ | ✖¹ | ✔ (yalnız kendi) | ✖ | ✖ | `assert_owns` (`files.py:73`) |
| İçeriği değiştir | ✖¹ | ✖¹ | ✖¹ | ✔ (paylaşılmıyorsa) | ✖ | ✖ | `assert_owns` + paylaşım reddi |
| Başka satıcının dosyası | ✖ | ✖ | ✖ | **✖** | ✖ | ✖ | `assert_owns` → "Dosya bulunamadı" |

¹ Rol yüksek olsa bile `_get_seller_profile_for_user` mağaza çözemezse
`current_store()` `PermissionError` atar. `Administrator` özel olarak dışlanmıştır
(`utils/tenant.py:129-130`). Yani **yönetici satıcı arayüzünü kullanamaz** — ayrı bir
yönetim arayüzü var (§4.1).

### 4.3 Dosya servis yolları

| Yol | Administrator | SM/MA | Satıcı | Kayıtlı | Guest | Kaynak |
|---|:--:|:--:|:--:|:--:|:--:|---|
| `/files/...` (public) | ✔ | ✔ | ✔ | ✔ | ✔ | nginx doğrudan proxy; `file.py:880-881` `is_private=0` + read → True |
| `/private/files/...` (oturumlu) | ✔ | delegasyona bağlı | delegasyona bağlı | delegasyona bağlı | ✖ (403) | `file.py:872-911` |
| `api/media_access.get_signed_url` | ✔ | read yetkisi varsa | read yetkisi varsa | read yetkisi varsa | **✖** | `media_access.py:118-131` |
| `api/media_access.download` (imzalı) | — | — | — | — | **✔ (imza + süre geçerliyse)** | `media_access.py:144-202` |

---

## 5. L0 — Frappe'nin `File` izin kuralı (özelleştirilmemiş)

`tradehub_core/hooks.py` içinde `has_permission` haritasında (`:790-8xx`) ve
`permission_query_conditions` haritasında (`:719-78x`) **`"File"` anahtarı YOKTUR**
(`grep -n '"File"' tradehub_core/hooks.py` → tek sonuç: `:231`, yani `doc_events`).

Dolayısıyla Frappe varsayılanı geçerli (`frappe/hooks.py:116` ve `:132`):

`file.py:872-911` — `has_permission(doc, ptype, user)` karar sırası:

```python
if user == "Administrator":                       return True   # :875-876
if ptype == "create":     → frappe.has_permission("File","create")  # :877-878
if not doc.is_private and ptype in ("read","select"): return True   # :880-881  ← PUBLIC HERKESE AÇIK
if user != "Guest" and doc.owner == user:         return True   # :883-884
if user != "Guest" and ptype in [read,write,share,submit] and DocShare: return True  # :885-892
if doc.attached_to_doctype and doc.attached_to_name:            # :894
    ref_doc = frappe.get_doc(attached_to_doctype, attached_to_name)
    if ptype in ["write","create","delete"]: return ref_doc.has_permission("write")  # :906-907
    else:                                    return ref_doc.has_permission("read")   # :909
return False                                                     # :911
```

`get_permission_query_conditions` (`file.py:914-927`):

```python
if user == "Administrator":                 return ""                       # :916-917
if SYSTEM_USER_ROLE not in frappe.get_roles(user):
    return "`tabFile`.`owner` = <user>"                                     # :919-920
return """(is_private = 0)
       OR (attached_to_doctype IS NULL AND owner = <user>)
       OR (attached_to_doctype IN (<okunabilir doctype'lar>))"""            # :923-927
```

### 5.1 Bunun iki sonucu

**(a) Bağlı-doküman delegasyonu izolasyonun bir parçası.** `attached_to_doctype = "Listing"`
olan private bir dosyada erişim kararı `Listing`'in kendi izin kuralına devrolur —
`tradehub_core/hooks.py:793` `listing_has_permission`. Yani `File` üzerinde ayrı bir
tenant kuralı yazmaya gerek kalmamış; Listing'in tenant izolasyonu miras alınıyor.

**(b) `attached_to_doctype` boş private dosya yalnız owner'ına açık** (`file.py:883-884`),
başka hiç kimseye. `docs/MEDYA-ERISIM-MODELI.md:2.2` bu dağılımı kaydediyor
(*"KYB 489, owner-only 71, Bulk Import 29, KYC 9, Brand 4, Seller Application 3"* —
belgedeki ölçüm, bu raporda tazelenmedi).

---

## 6. L3 — PII / KVKK koruması

### 6.1 Kural: kapsam dışı doctype'a bağlı dosya ASLA public yapılamaz

`media/access_level.py:116-125`:

```python
if not make_private and _is_protected_pii(file_doc, url):
    audit.log_media_event(
        action=audit.ACTION_SCOPE_DENIED,   # :118
        allowed=False, reason="excluded_doctype_public",
        sensitive=True,
    )
    frappe.throw(_("Bu belge herkese açık yapılamaz (KVKK/PII)."))   # :125
```

Modül başlığı (`access_level.py:14-15`): *"PII sızıntısı koruması, **rol seviyesiyle de
aşılamaz**."* Private yapmak serbest; public yapmak yasak. `force` benzeri hiçbir
parametre yok (`:107-108`).

### 6.2 İki bağımsız tespit yolu — ve neden ikisi de şart

`media/access_level.py:72-92`:

```python
def _is_protected_pii(file_doc, url) -> bool:
    if file_doc.attached_to_doctype in presets.EXCLUDED_DOCTYPES:   # :86  YOL 1
        return True
    for doctype, fields in presets.EXCLUDED_MEDIA_FIELDS.items():   # :88  YOL 2
        for field in fields:
            if frappe.db.exists(doctype, {field: url}):             # :90  TERS REFERANS
                return True
    return False
```

**Yol 2 bir CRITICAL bulgu düzeltmesidir.** `presets.py:56-64` ve `access_level.py:77-84`
aynı olayı kaydediyor: bazı hassas belgeler `attached_to_doctype` set edilmeden
yükleniyor, yalnız bir Attach/Data alanında string olarak duruyor. Kod yorumundaki ölçüm:
`Seller Application.identity_document` 144 dosya + `Seller Certification.document` 2 dosya
= **146 kimlik/PII belgesi** (TC kimlik taraması dahil) yalnız Yol 1 ile public
yapılabiliyordu. *(Bu sayılar kod yorumundan alınmıştır; bu raporda tazelenmedi — §9.4.)*

### 6.3 Kapsam listeleri

`media/presets.py:44-53` — `EXCLUDED_DOCTYPES` (8 doctype):

```
KYB Verification · KYC Verification · Seller Certification · Seller Verification
Seller Application · Order · Payment Transaction · Data Export Request
```

`media/presets.py:70-76` — `EXCLUDED_MEDIA_FIELDS` (5 doctype, 7 alan):

| Doctype | Alan(lar) |
|---|---|
| KYC Verification | `identity_document` |
| Seller Application | `identity_document` |
| KYB Verification | `identity_document`, `bank_account_document` |
| Seller Certification | `document` |
| Seller Verification | `document` |

> **BAKIM TUZAĞI (kodda yazılı, `presets.py:66-69`):** `EXCLUDED_DOCTYPES`'e yeni bir
> doctype eklenip `EXCLUDED_MEDIA_FIELDS` güncellenmezse, o doctype'ın dosyaları toggle
> korumasından **sessizce kaçar**. İki liste elle senkronlanıyor; otomatik doğrulama yok.
> Bkz. §8-A.

### 6.4 Aynı kaynak, iki tüketici

`api/media_admin.py:513-516` (`get_private_files`) listeleme sırasında **aynı**
`access_level._is_protected_pii` fonksiyonunu çağırıp her satıra `pii` bayrağı basıyor:

> *"İki yönlü PII kontrolü (attached + ters referans) — access_level ile aynı kaynak,
> liste ile toggle farklı karar vermesin."*

Yani UI aksiyonu gizler, backend `set_level` zorlar — iki katman, tek kaynak.

### 6.5 Kota tarafındaki aynı liste

`entitlement/checks.py:246` — `EXCLUDED_DOCTYPES` kotadan da muaf: satıcı, hiç göremediği
bir sayaç yüzünden KYB belgesi yükleyemez duruma düşmesin (`:219-222` gerekçesi).

### 6.6 Denetim kaydında maskeleme

`media/audit.py:150-158`:

```python
if sensitive:
    for key in ("file_name", "file_url", "attached_to_doctype"):
        payload.pop(key, None)                    # :152-153
    payload["masked"] = True
    file_url = f"masked:{fingerprint(file_url)}"  # :155
```

`fingerprint()` (`audit.py:105-111`) = `sha256(value)[:12]` — geri döndürülemez ama
kararlı: operatör "bu dosyaya 5 kez denendi" diyebilir, dosyayı açamaz.

**Bilinen tuzak, kodda çözülmüş:** maskeleme yalnız **sabit üç anahtarı** siler. Çağıran
kendi özel anahtarını (`old_url` gibi) koyarsa ham yol context'ten geri sızar. Bu yüzden
`access_level.py:179-189` hassas durumda ham yolu context'e **hiç koymaz**, yalnız
parmak izi (`old_url_fp`) yazar.

Ölçüm (kod yorumundan, `audit.py:139-141`): *"aksi hâlde panelden gizlediğimiz
KYC/dekont adresleri denetim penceresinden geri sızıyordu (ölçüldü: 4 kayıtta tam public
URL görünüyordu)."*

---

## 7. İmzalı URL modeli (`api/media_access.py`)

### 7.1 Kripto: kendi kriptomuz yazılmadı

`media_access.py:5-6`: Frappe'nin `frappe.utils.verified_command` primitifi
(site secret ile HMAC-SHA512). `get_signed_params` / `verify_request` (`:39` import).

### 7.2 Üretim ucu — tek kritik güvenlik kuralı

`media_access.py:102-141` (`get_signed_url`):

```python
if frappe.session.user == "Guest":                       # :118
    frappe.throw(..., frappe.PermissionError)
file_url = _require_private_path(file_url)               # :121
file_doc = frappe.get_doc("File", {"file_url": file_url})
if not file_doc.has_permission("read"):                  # :124  ← L0'a delege
    audit.log_media_event(ACTION_ACCESS_DENIED, reason="signed_url_denied")  # :125-130
    frappe.throw(..., frappe.PermissionError)            # :131
ttl = _clamp_ttl(ttl_seconds)                            # :133
exp = int(time.time()) + ttl
signed = get_signed_params({"file": file_url, "exp": exp})  # :135
```

**Yetkisiz kullanıcı için imza ÜRETİLMEZ** (`:13`). İmza yetkiyi yaratmaz, sadece
imza anındaki yetkiyi taşır.

`_require_private_path` (`:66-76`) iki reddi tek yerde toplar: path traversal (`..`) ve
public yol. **Public dosyalar imzalanamaz** (`:43-45`): public zaten girişsiz açık, imza
gereksiz ve "public path'i private gibi imzalatıp meşrulaştırmak" anlamsız.

### 7.3 TTL sınırları

`media_access.py:48-50`:

| Ayar | Değer | Kaynak |
|---|---:|---|
| Varsayılan | 900 sn (15 dk) | `:48` |
| Alt sınır | 60 sn | `:49` |
| Üst sınır | 86 400 sn (24 saat) | `:50` |

`_clamp_ttl` (`:53-63`) sessizce clamp'ler; parse edilemeyen değer varsayılana düşer.
Gerekçe (`:56-58`): üst sınır olmadan link isteyen taraf pratikte **sınırsız süreli bir
kapı** açabilir.

### 7.4 İndirme ucu — guest'e açık, altı doğrulama

`media_access.py:144-202` (`download`, `allow_guest=True`) sırası:

| # | Kontrol | Satır | Ret nedeni |
|---|---|---|---|
| 1 | `verify_request()` — HMAC | `:159` | `invalid_signature` |
| 2 | `_require_private_path` | `:164` | `bad_path` |
| 3 | `int(exp)` parse | `:171` | `malformed_exp` |
| 4 | `exp <= now` | `:178` | `expired` |
| 5 | `check_path_safety` (2. katman) | `:189` | `bad_path` |
| 6 | `send_private_file(relative)` | `:193` | — |

**Her red dalı denetime yazılır** (`_log_denied`, `:79-99`). Gerekçe (`:83-86`): guest'e
açık bir uçta imzasız/süresi geçmiş/bozuk link denemeleri (brute-force, probe) aksi hâlde
**hiç iz bırakmadan** geçerdi.

**`download_private_file` bilinçli olarak KULLANILMIYOR** (`:15-22`): o `Guest` için
Forbidden döndürüyor, imzalı link tam olarak oturumsuz erişim için var. Yerine alt seviye
`send_private_file` (aynı X-Accel-Redirect deseni) + kendi path-safety kontrolümüz.

`claimed_file` (`:157`) yalnız **kayıt amaçlı** okunur; serve kararı asla bu ham değere
dayanmaz — her adım kendi başına yeniden doğrular (`:155-156`).

### 7.5 Modelin kabul edilmiş sınırı

`media_access.py:24-26`: *"İmza yalnız imza anındaki yetkilendirmeyi taşır: link'i alan,
süre boyunca o dosyaya erişir (bilinçli — paylaşım özelliğinin amacı bu)."*

Yani **iptal (revocation) yok.** İmza üretildikten sonra kullanıcının yetkisi alınsa bile
link TTL boyunca çalışır. Tek fren: 24 saatlik üst sınır. Bu bir eksik değil, belgelenmiş
bir karar — ama operasyonel sonucu (§8-C) bilinmeli.

---

## 8. Eksikler ve genişletme noktaları

### A — `EXCLUDED_DOCTYPES` ↔ `EXCLUDED_MEDIA_FIELDS` senkronu doğrulanmıyor

`presets.py:44-53` 8 doctype listeliyor; `presets.py:70-76` yalnız **5**'i için alan
haritası veriyor. Eksik 3: `Order`, `Payment Transaction`, `Data Export Request`.

| Artı (bir test eklemenin) | Eksi |
|---|---|
| `presets.py:66-69`'daki bakım tuzağı sessiz olmaktan çıkar | Eksik 3 doctype'ta gerçekten dosya-tutan alan olup olmadığı **doğrulanmadı** (§9.5) |
| Test saf veri üzerinde çalışır, DB gerektirmez (`gates.py` deseni) | Alan adları elle bakım ister; DocType meta'sından türetmek daha sağlam ama daha kırılgan |

### B — `File` için tenant-aware `permission_query_conditions` yok

Frappe varsayılanı (`file.py:919-920`) System User olmayan kullanıcıyı `owner = user`'a
kilitler. Ama **System User rolü olan bir satıcı alt kullanıcısı** `:923-927` dalına düşer
ve `attached_to_doctype IN (okunabilir doctype'lar)` koşuluyla geniş bir küme görebilir.

| Artı (hook eklemenin) | Eksi |
|---|---|
| Desk / genel `frappe.get_list("File")` çağrıları da mağaza sınırına girer | Medya uçları zaten `ownership.scope` ile korunuyor — bu ek katman yalnız Desk yüzeyini kapatır |
| `ownership.users_of` + `used_urls` hazır | Query condition'da alt sorgu maliyeti; `used_urls` şu an 60 sn cache'li (`ownership.py:147`) ama SQL'e gömülemez |
| Tek yerde tanımlanır | Frappe'nin kendi File akışlarını (attachment listesi, Desk sidebar) kırma riski gerçek |

**Önce ölçülmeli:** satıcı alt kullanıcılarında `System User` rolü var mı (§9.2).

### C — İmzalı link iptali yok

§7.5. Bir çalışan işten ayrıldığında ya da bir link yanlış kişiye gittiğinde geri alınamaz.

| Artı (iptal listesi eklemenin) | Eksi |
|---|---|
| Cache'te `revoked:<fingerprint>` seti + `download`'da tek `get_value` — ucuz | İmza tasarımının sadeliğini bozar; `verified_command` durumsuzdu, durumlu hâle gelir |
| Denetimde zaten `ACTION_SIGNED_ACCESS` kaydı var (`media_access.py:196`), kimin ne indirdiği izlenebilir | Cache uçarsa iptal kaybolur — kalıcılık için DocType gerekir |
| TTL üst sınırını düşürmek (24 saat → 4 saat) sıfır kod maliyetiyle riski küçültür | Meşru paylaşım senaryolarını (belgeyi muhasebeciye gönderme) zorlaştırır |

### D — `Administrator` reddi denetime hiç yazılmıyor

`api/media_admin.py:59-62`. Administrator `only_for`'u atladığı için `_only_for`'un
`except` dalı hiç çalışmaz.

| Artı (açık Administrator kaydı eklemenin) | Eksi |
|---|---|
| "Kim ne yaptı" sorusunda Administrator kör nokta olmaktan çıkar | Administrator zaten her şeyi yapabilir; kayıt caydırıcı, engelleyici değil |
| Başarılı işlem kayıtları zaten var (`log_media_event`) — yalnız ret tarafı boş | Yeni kod = yeni hata yüzeyi; mevcut çözüm (başarı kayıtları) çoğu soruşturmayı zaten karşılıyor |

---

## 9. ÜRETİMDE DOĞRULANMALI

Docker kapalı; üretim veritabanına ve canlı siteye erişim yok. Aşağıdakiler bu raporda
**ölçülmemiştir**.

### 9.1 Rol kapılarının canlıda gerçekten kapalı olduğu

```bash
# Marketplace Admin rolüne sahip bir test kullanıcısıyla:
bench --site <site> console
>>> import frappe
>>> frappe.set_user("<marketplace-admin-kullanici>")
>>> from tradehub_core.api import media_admin
>>> media_admin.get_image_inventory()      # Beklenen: ÇALIŞIR
>>> media_admin.purge_trash()              # Beklenen: frappe.PermissionError
>>> frappe.set_user("Administrator")
>>> frappe.get_all("Authorization Decision Log",
...     filters={"action": "media.access_denied"},
...     fields=["name","creation","context"], order_by="creation desc", limit=5)
# Beklenen: reason "missing_role:media_destructive" içeren bir kayıt
```

### 9.2 Satıcı alt kullanıcılarının rolleri (§8-B için belirleyici)

```bash
bench --site <site> mariadb
> SELECT hr.role, COUNT(DISTINCT u.name) AS kullanici
  FROM `tabUser` u
  JOIN `tabHas Role` hr ON hr.parent = u.name
  WHERE u.tradehub_tenant IS NOT NULL AND u.tradehub_tenant != ''
  GROUP BY hr.role ORDER BY kullanici DESC;
# "System User" satırı VARSA §8-B gerçek bir açıktır; yoksa Frappe varsayılanı
# (owner = user) zaten kilitliyor demektir.
```

### 9.3 Satıcı izolasyonunun uçtan uca doğrulanması

```bash
bench --site <site> console
>>> import frappe
>>> from tradehub_core.api import seller_media
>>> from tradehub_core.media import ownership
>>> # A mağazasının bir dosyası:
>>> a_url = frappe.db.get_value("File", {"is_private": 0}, "file_url")
>>> print(ownership.owners_of(a_url))          # {"<A>"} bekleniyor
>>> frappe.set_user("<B-magazasi-kullanicisi>")
>>> print(ownership.current_store())           # <B>
>>> seller_media.get_my_usage(a_url)           # Beklenen: DoesNotExistError "Dosya bulunamadı."
>>> seller_media.purge_media([a_url])          # Beklenen: {"purged":0,"skipped":1}
>>> r = seller_media.get_my_media(page_size=200)
>>> print(any(i["file_url"] == a_url for i in r["items"]))   # Beklenen: False
```

### 9.4 PII korumasının canlı verideki kapsamı

Kod yorumlarındaki "144 + 2 = 146 dosya" ölçümü (`presets.py:57-64`) bu raporda
tazelenmedi.

```bash
bench --site <site> mariadb
> SELECT 'Seller Application' d, COUNT(*) FROM `tabSeller Application`
  WHERE ifnull(identity_document,'') != ''
UNION ALL SELECT 'Seller Certification', COUNT(*) FROM `tabSeller Certification`
  WHERE ifnull(document,'') != ''
UNION ALL SELECT 'KYB Verification', COUNT(*) FROM `tabKYB Verification`
  WHERE ifnull(identity_document,'') != '' OR ifnull(bank_account_document,'') != ''
UNION ALL SELECT 'KYC Verification', COUNT(*) FROM `tabKYC Verification`
  WHERE ifnull(identity_document,'') != ''
UNION ALL SELECT 'Seller Verification', COUNT(*) FROM `tabSeller Verification`
  WHERE ifnull(document,'') != '';

# Kaçı attached_to_doctype BOŞ (yani yalnız ters referansla yakalanabiliyor):
> SELECT COUNT(*) FROM `tabFile` f
  WHERE ifnull(f.attached_to_doctype,'') = ''
    AND f.file_url IN (SELECT identity_document FROM `tabSeller Application`);

# En kritik kontrol — PII dosyası PUBLIC mi:
> SELECT f.name, f.file_url FROM `tabFile` f
  WHERE f.is_private = 0
    AND (f.file_url IN (SELECT identity_document FROM `tabSeller Application`)
      OR f.file_url IN (SELECT document FROM `tabSeller Certification`)
      OR f.file_url IN (SELECT identity_document FROM `tabKYC Verification`));
# Beklenen: BOŞ. Dolu çıkarsa AKTİF KVKK OLAYI.
```

### 9.5 §8-A için: eksik 3 doctype'ta dosya alanı var mı

```bash
bench --site <site> console
>>> import frappe
>>> for dt in ("Order", "Payment Transaction", "Data Export Request"):
...     m = frappe.get_meta(dt)
...     print(dt, [f.fieldname for f in m.fields
...                if f.fieldtype in ("Attach", "Attach Image")])
# Boş dönerse EXCLUDED_MEDIA_FIELDS'ta olmamaları doğru.
```

### 9.6 İmzalı URL uçtan uca

```bash
# 1) Yetkisiz kullanıcı imza alamıyor mu:
bench --site <site> console
>>> frappe.set_user("<baska-satici>")
>>> from tradehub_core.api import media_access
>>> media_access.get_signed_url("/private/files/<baskasinin-dosyasi>")
# Beklenen: PermissionError + ADL'de reason="signed_url_denied"

# 2) Guest imzasız erişemiyor mu:
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://<backend>/api/method/tradehub_core.api.media_access.download?file=/private/files/x.pdf"
# Beklenen: 403/417 (imza yok)

# 3) Süresi dolmuş link:
>>> u = media_access.get_signed_url("/private/files/<kendi-dosyam>", ttl_seconds=60)
# 61 sn bekle, sonra curl → beklenen: hata + ADL'de reason="expired"

# 4) Reddedilen denemeler kayda giriyor mu:
>>> frappe.get_all("Authorization Decision Log",
...   filters={"action": ["in", ["media.access_denied","media.signed_access"]]},
...   fields=["action","decision","object_name","creation"],
...   order_by="creation desc", limit=10)
# object_name "masked:<12 hex>" biçiminde olmalı (hassas kayıtlarda)
```

### 9.7 Private dosya doğrudan erişim (nginx katmanı)

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://istoc.com/private/files/<bilinen>.pdf
# Beklenen: 403 (Guest → Forbidden, docs/MEDYA-ERISIM-MODELI.md §2.2)
# 200 dönerse private dizin web'e açılmış demektir — KRİTİK.
```

### 9.8 Ölçülemeyen kalemler

| Bilinmeyen | Neden |
|---|---|
| Gerçek rol dağılımı (kaç SM, kaç MA) | DB yok |
| Aynı dosyayı paylaşan mağaza sayısı (kod yorumu: 30 adres) | DB yok |
| `media.access_denied` kayıtlarının günlük hacmi | ADL'ye erişim yok |
| İmzalı link kullanım oranı | Log yok |
| DocShare üzerinden `File` paylaşımı yapılıp yapılmadığı | DB yok — `file.py:885-892` bu yolu açık bırakıyor |

---

## 10. Kaynaklar

| Kısaltma | Tam yol |
|---|---|
| `api/media_admin.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/api/media_admin.py` (873 satır) |
| `api/seller_media.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/api/seller_media.py` (494 satır) |
| `api/media_access.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/api/media_access.py` (202 satır) |
| `media/ownership.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/ownership.py` (273 satır) |
| `media/access_level.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/access_level.py` (209 satır) |
| `media/presets.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/presets.py` (81 satır) |
| `media/seller_media.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/seller_media.py` (204 satır) |
| `media/audit.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/audit.py` (804 satır) |
| `media/chunked.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/chunked.py` (293 satır) |
| `media/files.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/files.py` (280 satır) |
| `utils/tenant.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/utils/tenant.py` |
| `entitlement/checks.py` | `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/entitlement/checks.py` |
| `file.py` | `/Users/ahmet/OrbStack/docker/containers/istoc-dev-backend-1/home/frappe/frappe-bench/apps/frappe/frappe/core/doctype/file/file.py` |
| `frappe/hooks.py` | `.../apps/frappe/frappe/hooks.py` |

İlgili belgeler: `docs/MEDYA-ERISIM-MODELI.md` (TUR-126),
`docs/reports/01-dosya-akisi.md` (T-002 — dosya akışı, aynı kod tabanı).
