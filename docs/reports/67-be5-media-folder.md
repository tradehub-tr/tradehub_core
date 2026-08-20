# 67 · BE5 — Gerçek satıcı klasörleri (T-094)

**Tarih:** 2026-08-20 · **Kapsam:** Media Folder DocType + satıcı klasör uçları + panel gezgini klasör CRUD/taşıma · **Şartname:** `~/Desktop/imageoptimization/docs/60-faz9-media-library.html` (T-094)

Başlangıç ölçümü: `grep -rln "Media Folder"` → 0. Gezgin (`SellerMediaExplorerView.vue`)
yalnız SANAL ağaçla (kategori/üründen türetilen `browse_my_media`) çalışıyordu;
kullanıcının açtığı klasör, taşıma, yeniden adlandırma yoktu.

---

## 1. DocType'lar — canlı ölçümle

Migrate sonrası `tabDocField` sayımı (JSON'da doğru ≠ canlıda etkin):

```sql
select parent, count(*) from tabDocField
 where parent in ('Media Folder','Media Folder Item') group by parent;
-- [["Media Folder", 3], ["Media Folder Item", 3]]
-- Media Folder alanları (idx sırasıyla): folder_name (Data), store (Link), parent_folder (Link)
```

### Media Folder
`tradehub_core/tradehub_core/doctype/media_folder/`

| Alan | Tip | Not |
|---|---|---|
| `folder_name` | Data | zorunlu, ≤100, `/` yasak |
| `store` | Link → Admin Seller Profile | zorunlu, read_only, search_index — sunucu oturumdan yazar |
| `parent_folder` | Link → Media Folder | boş = kök; boş değer her zaman `""` normalize edilir (NULL/`""` ikiliği benzersizliği delerdi) |

- **autoname: `hash`** — klasör adı docname'e yazılsaydı hem çakışır hem başka mağazaların klasör adları kimlik uzayından keşfedilirdi (TUR-141 ilkesi).
- **Benzersizlik:** aynı `store` + aynı `parent_folder` altında aynı `folder_name` → `DuplicateEntryError` (controller `validate`; rename de aynı yoldan geçer).
- **Derinlik tavanı = 5.** Şartname sayı vermiyor ("ağaç yapısı, nested set veya parent link"). Gerekçe: sanal ağacın en derin hâli 3 seviye (kök→kategori→ürün) — kullanıcı alışkanlığına iki kat pay; her doğrulama ata zincirini yürüdüğünden tavan sorgu sayısını da sınırlar; kırıntı şeridi 5 seviyeyi mobilde hâlâ okunur basar. Tavan `list_folders` yanıtında (`max_depth`) ekrana da bildirilir — ekran ayrı bir sabit tutmaz.
- **Döngü koruması:** ata zinciri yürüyüşünde kendine/görülene rastlama → ret. Taşınan klasörün ALT ağacı da tavana sayılır (`_subtree_depth`).
- **Dolu klasör silme = RET** (`on_trash`): alt klasörü ya da dosyası olan klasör silinemez. Şartname yalnız "silme (içerik varsa uyarı)" diyor, davranış seçmiyor; köke taşıma sessiz bir yan etki olurdu (kullanıcı 500 dosyanın nereye gittiğini arar), ret ise içeriği bilerek taşımaya zorlar ve hiçbir şey kaybolmaz. Ekran sunucunun ret mesajını aynen gösterir.

### Media Folder Item (dosya-klasör bağı) — KARAR
`tradehub_core/tradehub_core/doctype/media_folder_item/` · alanlar: `folder` (Link), `file_url` (Data 500), `store` (Link)

**Karar: `tabFile`'a custom field DEĞİL, ayrı bağlantı DocType'ı.** Ölçülen üç sebep:

1. **Aynı adres birden çok mağazada** (ölçüm: 30 adres iki mağazada, `media/ownership.py`). Klasör mağazanın kendi düzeni; `tabFile.th_media_folder` gibi tek alan iki mağazanın aynı dosyayı FARKLI klasöre koymasını temsil edemez.
2. **Sahiplik "kim kullanıyor" ile de kurulur** (`ownership.owners_of`): kullanım yoluyla sahip olunan dosyanın `File` satırı başka mağazanın kullanıcısına ait. Custom field'a yazmak ya o satırı kirletir ya da (metadata modülü deseniyle yalnız kendi satırına yazınca) satır bulunamaz ve taşıma sessizce kaybolur.
3. **Türevler `File` kaydı açmıyor** (MEDYA-DEPOLAMA-STANDARDI.md §3.2 + mimari not) — `tabFile` şemasına bağlanan özellik bu dosyalar için baştan çalışmaz; bağ `file_url` üzerinden ayrı tabloda `File` satırının varlığına yaslanmaz.

Ek kazanç: **custom field patch'i gerekmedi** — patch dosyası yazılmadı, `patches.txt` satırı yok.

Benzersizlik (bir dosya bir mağazada en çok bir klasörde): `validate` + taşıma ucunda sil-sonra-yaz. Birleşik DB unique indeksi kurulmadı — `file_url` 500 karakter, utf8mb4'te indeks boyu sınırına dayanır.

---

## 2. Uçlar (`tradehub_core/api/seller_media.py`, mevcut modüle EK)

Hepsi dosyadaki desenle: mağaza **her uçta oturumdan** (`_store()`), istemciden asla; klasör kimliği tek kapıdan (`_my_folder`) doğrulanır; başka mağazanın klasörü **"bulunamadı"** ile reddedilir ("yetkin yok" varlığı doğrular).

| Uç | Metot | İş |
|---|---|---|
| `list_folders()` | GET | mağazanın tüm klasörleri (düz liste) + klasör başına dosya sayısı (tek GROUP BY) + `max_depth` |
| `create_folder(folder_name, parent_folder="")` | POST | kural DocType'ta, uç tekrar etmez |
| `rename_folder(folder, new_name)` | POST | kimlik değişmez |
| `delete_folder(folder)` | POST | dolu → ret (`on_trash`) |
| `move_media(file_urls, folder="")` | POST | toplu; `folder=""` köke (bağ silinir); sahip olunmayan `skipped` (adres dönülmez — `archive_media` gerekçesi); `MAX_BATCH=200` |
| `list_folder_media(folder, page, page_size, search)` | GET | `get_my_media` satır biçimi + `metadata.read_many`; aynı adresin çoklu `File` satırı `group_by=file_url` ile teklenir |

## 3. Cross-tenant ölçümü

Konteynerde (`istoc-dev-backend-1`, site `istoc.localhost`):

```
bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_folder
Ran 20 tests ... OK        (2 kez: migrate sonrası ve RED kanıtı geri alındıktan sonra)
```

- **Uç-içi katman (yeşil):** B, A'nın klasörünü listede göremez; `rename/delete/list_folder_media/create(parent)/move` beşi de `DoesNotExistError`; B'nin `move_media`'sı A'nın dosyasını `skipped=1` sayar, bağ yazılmaz.
- **Vacuity / KIRMIZI kanıtı (iki düzeyde):**
  1. Konteynerdeki `seller_media.py`'de `_my_folder`'ın mağaza karşılaştırması fiilen gevşetildi (`if not satir or satir.store != store` → `if not satir`), yalnız cross-tenant testi koşuldu: **`FAILED (failures=1)` — "AssertionError: DoesNotExistError not raised"**. Dosya geri yüklendi, modül yine 20/20 yeşil. Yani yeşil geçen izolasyon testleri tam da o kontrole yaslanıyor.
  2. Kalıcı test `test_kontrol_gevsetilince_sizinti_gercekten_olur`: `_my_folder` mock ile gevşetilince B'nin rename'i BAŞARILI oluyor — sızıntının kontrol yokken gerçekten oluştuğu her koşuda yeniden kanıtlanır.
- **Çerçeve katmanı:** `get_permission_query_conditions(B)` SQL'i A'nın klasörünü dışarıda bırakıyor (testte gerçek sorguyla ölçüldü); `has_permission` A'ya True / B'ye ve Guest'e False / yöneticide True; mağazasız kullanıcı ve Guest → `"1=0"`.
- **Kayıt öncesi pencere kapalı:** DocPerm yalnız System Manager (+ Marketplace Admin read) — satıcı rolünde satır YOK, dolayısıyla `frappe.get_list("Media Folder")` satıcıya `PermissionError` (testte sabit: `test_genel_uc_kayit_oncesi_saticilara_kapali`). hooks kaydı gecikirse genel uçlardan sızıntı penceresi oluşmaz; hook'lar ileride bir satıcı rolüne DocPerm verilirse devreye girecek emniyet kemeri.

## 4. hooks.py / patches.txt satırları (BEN EKLEMEDİM — sen ekleyeceksin)

`hooks.py` → `permission_query_conditions` sözlüğüne:

```python
"Media Folder": "tradehub_core.tradehub_core.doctype.media_folder.media_folder.get_permission_query_conditions",
"Media Folder Item": "tradehub_core.tradehub_core.doctype.media_folder_item.media_folder_item.get_permission_query_conditions",
```

`hooks.py` → `has_permission` sözlüğüne:

```python
"Media Folder": "tradehub_core.tradehub_core.doctype.media_folder.media_folder.has_permission",
"Media Folder Item": "tradehub_core.tradehub_core.doctype.media_folder_item.media_folder_item.has_permission",
```

`patches.txt`: **satır yok** — custom field kullanılmadı, patch dosyası gerekmedi.

## 5. Panel (FE)

| Dosya | Değişiklik |
|---|---|
| `src/composables/useSellerMedia.js` | `listFolders / createFolder / renameFolder / deleteFolder / moveToFolder / folderMedia` — klasör satırları `bicimle` ile kütüphane biçimine çevrilir; hiçbir çağrı `store` göndermez |
| `src/views/seller/SellerMediaExplorerView.vue` | Kök ızgarada sanal köklerin yanında gerçek kök klasörler; gerçek klasör modu (alt klasör ızgarası + dosya listesi + arama + sayfalama); klasör oluştur (kökte ve klasör içinde, tavana dayanınca gizlenir), adı değiştir, sil (`confirm`, dolu klasörü sunucu reddeder ve mesajı toast'a düşer); dosya satırlarında seçim kutuları; kırıntı iki ağacı tek dille gezer |
| `src/components/media/MediaBulkBar.vue` | YALNIZ taşıma eklendi: `folders` prop'u (verilmezse kontrol hiç çizilmez — kütüphane etkilenmez) + `move` emit'i + `moveOnly` prop'u (gezginde diğer düğmeler gizli); kısmi sonuç dökümü mevcut `report` mekanizmasıyla ("48 başarılı, 2 atlandı") |
| `src/components/media/MediaFolderGrid.vue` / `MediaCrumbs.vue` | Kod değişikliği YOK — gerçek veriye view'daki `realGridItem` / `crumbItems` ile bağlandı (ikisi de veri-körü bileşen) |

### i18n anahtarları (locale dosyalarına DOKUNULMADI — `t(key, {}, "TR varsayılan")` ile)

| Anahtar | TR varsayılan |
|---|---|
| `sellerMediaExplorer.folderOps.new` | Yeni klasör |
| `sellerMediaExplorer.folderOps.createPrompt` | Yeni klasörün adı: |
| `sellerMediaExplorer.folderOps.rename` | Adı değiştir |
| `sellerMediaExplorer.folderOps.renamePrompt` | Klasörün yeni adı: |
| `sellerMediaExplorer.folderOps.delete` | Klasörü sil |
| `sellerMediaExplorer.folderOps.deleteConfirm` | '{name}' klasörü silinsin mi? İçinde dosya ya da alt klasör varsa sunucu silmeyi reddeder. |
| `sellerMediaExplorer.folderOps.created` | Klasör oluşturuldu |
| `sellerMediaExplorer.folderOps.renamed` | Klasör adı değiştirildi |
| `sellerMediaExplorer.folderOps.deleted` | Klasör silindi |
| `sellerMediaExplorer.folderOps.failed` | İşlem tamamlanamadı |
| `sellerMediaExplorer.folderOps.moved` | {n} dosya taşındı |
| `sellerMediaExplorer.selectFile` | Dosyayı seç: {name} |
| `media.bulk.move` | Taşı |
| `media.bulk.moveTarget` | Hedef klasör |
| `media.bulk.moveRoot` | Kök — klasörsüz |

(3-argümanlı `t(key, named, defaultMsg)` overload'u kurulu vue-i18n 11'de mevcut — `vue-i18n.d.ts:1356` doğrulandı.)

## 6. Test dökümü (yalnız bu görevin dosyaları)

| Dosya | Sonuç |
|---|---|
| `tradehub_core/tests/test_media_folder.py` (yeni) | **20/20 OK** konteynerde — CRUD, boş ad, benzersizlik ×4, derinlik ×3 (tavan/alt-ağaç/döngü), taşıma ×2, dolu silme ×2, cross-tenant ×2, vacuity, pqc, has_permission, genel-uç-kapalı |
| `admin-panel/frontend/src/composables/__tests__/sellerMediaFolders.test.js` (yeni, + 2 fixture stub) | **8/8 pass** (`node --test`) — uç adları/parametre adları, `message` sarmalı, `bicimle` dönüşümü, "hiçbir çağrı store göndermez" sözleşmesi |

Ayrıca: `npm run build` ✓ (7.6s), `eslint` + `prettier` temiz. FE testleri KOŞULARAK doğrulandı; süre iddiası yok, "geçti" denilen her şey yukarıdaki komutlarla koşuldu.

## 7. Dokunulan dosyalar

**Yeni (BE):** `doctype/media_folder/{__init__.py,media_folder.json,media_folder.py}` · `doctype/media_folder_item/{__init__.py,media_folder_item.json,media_folder_item.py}` · `tests/test_media_folder.py`
**Değişen (BE):** `api/seller_media.py` (yalnız EK bölüm — mevcut uçlara dokunulmadı)
**Yeni (FE):** `src/composables/__tests__/sellerMediaFolders.test.js` · `__tests__/fixtures/sellerMediaApiStub.js` · `__tests__/fixtures/sellerMediaPipelineStub.js`
**Değişen (FE):** `src/composables/useSellerMedia.js` · `src/views/seller/SellerMediaExplorerView.vue` · `src/components/media/MediaBulkBar.vue`
**Dokunulmayan yasaklılar:** `hooks.py`, `patches.txt`, `permissions.py`, `MediaLibraryView.vue`, `i18n/locales`, router/navigation, upload/crop/simulator, mevcut testler, `docker/`.

## 8. Bilinen sınırlar

- Şartnamedeki "sürükle-bırak taşıma" yerine seçim + hedef klasör (MediaBulkBar) kuruldu — klavyeyle de tamamlanabilir (T-095 WCAG şartı); sürükle-bırak ayrı bir iyileştirme olarak eklenebilir.
- `list_folder_media` araması `File.file_name` üzerinde; başlık/etiket araması kütüphane ekranının işi.
- Klasör içeriği sunucuda `creation desc` sabit sıralı; sıralama seçici eklenmedi (şartname istemiyor).
