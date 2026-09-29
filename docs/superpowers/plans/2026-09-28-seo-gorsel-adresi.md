# SEO'lu görsel adresi — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ürün görselleri `/files/<ürün-adı-slug>-<8 karakter kod>.<uzantı>` adresiyle servis edilsin ve Google'a açılsın. Disk ve veritabanı kayıtları taşınmasın. Aynı işte sepet/favori görselleri ile vitrin önbellek hatası da düzeltilsin.

**Architecture:** Kısa kod `File.seo_code` alanında tutulur (yüklemede ve yamayla doldurulur, çakışırsa 12/16 karaktere uzar). API'ler kayıttaki `/files/xx/<32hash>.ext` adresini çıktı anında `seo_url.seo_image_url(url, başlık)` ile okunur adrese çevirir. Okunur adres diskte olmadığı için istek Frappe'ye düşer; yeni `SeoImageRenderer` kodu çözer ve dosyayı `X-Accel-Redirect: /protected/public/files/…` ile nginx'e verdirir, slug eskiyse 301, bulunamazsa 404. Vitrin nginx'i okunur adreslere `noindex` basmaz.

**Tech Stack:** Frappe v15 (Python, FrappeTestCase), MariaDB; tradehubfront (Vite + Alpine + TS, TanStack query-core, nginx şablonu); admin-panel (Vue 3, node:test).

**Spec:** `docs/superpowers/specs/2026-09-28-seo-gorsel-adresi-design.md`

## Global Constraints

- Adres biçimi: `/files/<slug>-<kod>[__<türev>].<uzantı>`; slug `seo.slugify.slugify_tr` ile, en fazla 60 karakter, kelime ortasında kesilmez, boşsa `gorsel`.
- Kod: `sha256[:32]` hash'in ilk 8 hex karakteri; başka **farklı** dosya aynı kodu kullanıyorsa 12, sonra 16, sonra 32.
- Disk, `naming._hashed_name`, dedup, S3 anahtarları, retro-rename akışı DEĞİŞMEZ. Veritabanındaki `file_url` / `primary_image` değerleri DEĞİŞMEZ.
- `seo_image_url` üretemediği her durumda girdiyi AYNEN döndürür (geri düşüş).
- Okunur adres yanıtı: `Cache-Control: public, max-age=31536000, immutable`; `X-Robots-Tag` yok. Diğer `/files/` yanıtları bugünkü gibi `noindex`.
- Press ve lokal backend nginx'inde `location ~ ^/protected/(.*) { internal; try_files /<site>/$1 =404; }` var (2026-09-28 doğrulandı). X-Accel yolu: `/protected/public/files/<xx>/<hash>[__türev].<ext>`.
- Commit YOK — kullanıcı her commit için ayrıca onay verir. Değişiklikler `ahmet` dalında çalışma ağacında kalır. `git checkout/stash/reset` yasak.
- Backend testleri: değişen dosyaları `docker cp` ile `istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/...` altına kopyala, `docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module <modül>`. Şema değişikliği için `bench --site istoc.localhost migrate`.
- Python: tab girinti, satır 110, tip ipuçları, yorumlar Türkçe; ruff: `uvx ruff check <dosyalar>`. TS/JS: 2 boşluk, Prettier; testler `node --test`/`npm test`.

## Review Focus

1. Aynı fotoğraf iki farklı üründe → her ürün kendi slug'ıyla adres alır, ikisi de 200 döner (başka ürünün slug'ı 301 ile güncele gitmez, çünkü ikisi de geçerli). Test: Task 2.
2. Türev (küçük boy) adresi → uzantısı orijinalden farklı olabilir (`.jpg` → `.webp`); çözümleme türev dosyasını bulur. Test: Task 2.
3. Eski adlı ya da `/files/media/` adresli görsel → `seo_image_url` dokunmaz, adres aynen döner. Test: Task 1.
4. `seo_code` henüz yazılmamış görsel → API bugünkü adresi verir, hata olmaz. Test: Task 1.
5. Kod tanımadığı bir 8 karakter → 404, sunucu hatası değil. Test: Task 2.

---

### Task 1: Çekirdek — `seo_url` modülü, `File.seo_code`, kod atama

**Files:**
- Create: `tradehub_core/media/seo_url.py`
- Create: `tradehub_core/patches/v15_9_61_file_seo_code.py`
- Modify: `tradehub_core/patches.txt` (sona satır)
- Modify: `tradehub_core/hooks.py` (`doc_events["File"]` içine `after_insert` ekle — mevcut listeyi silme, append)
- Modify: `tradehub_core/media/retro_rename.py` (`rename_one` başarılı dalında yeni adrese kod ata)
- Test: `tradehub_core/tests/test_media_seo_url.py`

**Interfaces:**
- Produces:
  - `seo_url.HASHED_RE`, `seo_url.SEO_RE` (derlenmiş regex)
  - `seo_url.make_slug(title: str | None) -> str`
  - `seo_url.assign_code(file_url: str) -> str | None` — yazma yapar
  - `seo_url.codes_for(file_urls: list[str]) -> dict[str, str]` — `{hash32: kod}`, tek sorgu, salt okuma
  - `seo_url.seo_image_url(file_url: str | None, title: str | None, codes: dict[str, str] | None = None) -> str`
  - `seo_url.on_file_after_insert(doc, method=None) -> None`

- [ ] **Step 1: Failing testleri yaz** — `tests/test_media_seo_url.py`:

```python
"""SEO'lu görsel adresi — çekirdek (spec 2026-09-28-seo-gorsel-adresi-design.md).

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_seo_url
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import seo_url


def _file_row(url: str) -> str:
	d = frappe.get_doc({"doctype": "File", "file_name": url.rsplit("/", 1)[-1], "file_url": url, "is_private": 0})
	d.flags.copy_from_existing_file = True
	d.flags.ignore_seo_code = True  # kod atamasını test kendisi yapsın
	d.insert(ignore_permissions=True)
	return d.name


class TestSlug(FrappeTestCase):
	def test_turkce_ve_kisaltma(self):
		self.assertEqual(seo_url.make_slug("4 Katlı Siyah Ayakkabılık"), "4-katli-siyah-ayakkabilik")
		uzun = "Çok " * 40
		s = seo_url.make_slug(uzun)
		self.assertLessEqual(len(s), 60)
		self.assertFalse(s.endswith("-"))
		self.assertTrue(set(s.split("-")) <= {"cok"})

	def test_bos_ad(self):
		self.assertEqual(seo_url.make_slug(""), "gorsel")
		self.assertEqual(seo_url.make_slug(None), "gorsel")
		self.assertEqual(seo_url.make_slug("!!!"), "gorsel")


class TestCode(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.h1 = "abcdef01" + "1" * 24
		self.h2 = "abcdef01" + "2" * 24  # ilk 8'i aynı, içerik farklı
		self.u1 = f"/files/{self.h1[:2]}/{self.h1}.jpg"
		self.u2 = f"/files/{self.h2[:2]}/{self.h2}.jpg"

	def test_sekiz_karakter_sonra_cakismada_uzar(self):
		_file_row(self.u1)
		_file_row(self.u2)
		self.assertEqual(seo_url.assign_code(self.u1), self.h1[:8])
		self.assertEqual(seo_url.assign_code(self.u2), self.h2[:12])
		# İkinci çağrı kaydı değiştirmez
		self.assertEqual(seo_url.assign_code(self.u1), self.h1[:8])

	def test_eski_ad_kod_almaz(self):
		self.assertIsNone(seo_url.assign_code("/files/0585.jpg"))
		self.assertIsNone(seo_url.assign_code("/files/media/x/y.jpg"))

	def test_codes_for_tek_sorgu_ve_turev(self):
		_file_row(self.u1)
		seo_url.assign_code(self.u1)
		turev = f"/files/{self.h1[:2]}/{self.h1}__w384.webp"
		self.assertEqual(seo_url.codes_for([self.u1, turev, "/files/0585.jpg"]), {self.h1: self.h1[:8]})


class TestSeoImageUrl(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.h = "fedcba98" + "3" * 24
		self.u = f"/files/{self.h[:2]}/{self.h}.jpg"
		_file_row(self.u)
		seo_url.assign_code(self.u)

	def test_okunur_adres(self):
		self.assertEqual(
			seo_url.seo_image_url(self.u, "Ahşap Raf"), f"/files/ahsap-raf-{self.h[:8]}.jpg"
		)

	def test_turev_son_eki_korunur(self):
		turev = f"/files/{self.h[:2]}/{self.h}__w384.webp"
		self.assertEqual(seo_url.seo_image_url(turev, "Ahşap Raf"), f"/files/ahsap-raf-{self.h[:8]}__w384.webp")

	def test_geri_dusus(self):
		for girdi in ["/files/0585.jpg", "", None, "https://cdn.example.com/a.jpg", "/files/media/a/b.jpg"]:
			self.assertEqual(seo_url.seo_image_url(girdi, "X"), girdi or "")
		kodsuz = "/files/11/" + "1" * 32 + ".jpg"
		self.assertEqual(seo_url.seo_image_url(kodsuz, "X"), kodsuz)

	def test_query_string_atilir(self):
		self.assertEqual(seo_url.seo_image_url(self.u + "?v=1", "A"), f"/files/a-{self.h[:8]}.jpg")
```

- [ ] **Step 2: Koş, FAIL gör** — `docker cp` test dosyası; `run-tests --module tradehub_core.tests.test_media_seo_url` → `ModuleNotFoundError: seo_url` / `seo_code` kolonu yok.

- [ ] **Step 3: Yamayı yaz** — `patches/v15_9_61_file_seo_code.py`:

```python
"""File.seo_code — SEO'lu görsel adresinin kısa kodu (spec 2026-09-28-seo-gorsel-adresi).

İdempotent: alan create_custom_fields(update=True); doldurma yalnız boş satırlara.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "seo_code",
			"label": "SEO Code",
			"fieldtype": "Data",
			"length": 32,
			"hidden": 1,
			"no_copy": 1,
			"search_index": 1,
			"module": "Tradehub Core",
		}
	]
}


def execute() -> None:
	create_custom_fields(FIELDS, update=True)
	frappe.db.commit()
	from tradehub_core.media import seo_url

	urls = frappe.db.sql(
		"""select distinct file_url from `tabFile`
			where is_folder=0 and ifnull(seo_code,'')='' and file_url regexp '^/files/[0-9a-f]{2}/[0-9a-f]{32}\\\\.'""",
		pluck=True,
	)
	for url in urls:
		seo_url.assign_code(url)
	frappe.db.commit()
```

`patches.txt` sonuna: `tradehub_core.patches.v15_9_61_file_seo_code`

- [ ] **Step 4: Modülü yaz** — `media/seo_url.py`:

```python
"""SEO'lu görsel adresi: `/files/<slug>-<kısa kod>[__türev].<uzantı>`.

Spec: docs/superpowers/specs/2026-09-28-seo-gorsel-adresi-design.md

Disk ve DB kayıtları içerik-kodlu (`/files/xx/<sha256[:32]>.ext`) kalır; okunur
adres yalnız API çıktısında üretilir, `SeoImageRenderer` geri çözer. Kısa kod
`File.seo_code`'da tutulur: 8 hex, başka FARKLI dosya aynı kodu kullanıyorsa 12/16/32.
"""

from __future__ import annotations

import re

import frappe

from tradehub_core.seo.slugify import slugify_tr

HASHED_RE = re.compile(r"^/files/([0-9a-f]{2})/([0-9a-f]{32})((?:__[a-z0-9]+)?)\.([a-z0-9]+)$")
SEO_RE = re.compile(r"^/?files/([a-z0-9-]+)-([0-9a-f]{8,32})((?:__[a-z0-9]+)?)\.([a-z0-9]+)$")
SLUG_MAX = 60
CODE_LENGTHS = (8, 12, 16, 32)
FALLBACK_SLUG = "gorsel"


def make_slug(title: str | None) -> str:
	s = slugify_tr(title or "")
	if len(s) > SLUG_MAX:
		kesik = s[:SLUG_MAX]
		s = kesik.rsplit("-", 1)[0] if "-" in kesik else kesik
	return s.strip("-") or FALLBACK_SLUG


def _hash_of(file_url: str | None) -> re.Match | None:
	return HASHED_RE.match((file_url or "").split("?")[0])


def _like(h32: str) -> str:
	return f"/files/{h32[:2]}/{h32}.%"


def assign_code(file_url: str) -> str | None:
	"""Kodu yoksa ata ve aynı adresli tüm `File` satırlarına yaz; varsa aynen döndür."""
	m = _hash_of(file_url)
	if not m or m.group(3):  # türev kendi kodunu almaz, orijinalinkini kullanır
		return None
	h32 = m.group(2)
	var = frappe.db.get_value("File", {"file_url": ["like", _like(h32)], "seo_code": ["is", "set"]}, "seo_code")
	if var:
		return var
	for n in CODE_LENGTHS:
		kod = h32[:n]
		cakisan = frappe.db.get_value(
			"File", {"seo_code": kod, "file_url": ["not like", _like(h32)]}, "name"
		)
		if not cakisan:
			frappe.db.sql(
				"update `tabFile` set seo_code=%s where file_url like %s", (kod, _like(h32))
			)
			return kod
	return None


def codes_for(file_urls: list[str]) -> dict[str, str]:
	"""`{hash32: kod}` — tek sorgu. Türev adresleri orijinalin hash'iyle eşlenir."""
	hashler = {m.group(2) for u in file_urls if (m := _hash_of(u))}
	if not hashler:
		return {}
	rows = frappe.db.sql(
		"""select substring(file_url, 11, 32) as h, seo_code from `tabFile`
			where seo_code is not null and seo_code != '' and substring(file_url, 11, 32) in %(h)s""",
		{"h": tuple(hashler)},
		as_dict=True,
	)
	return {r.h: r.seo_code for r in rows}


def seo_image_url(file_url: str | None, title: str | None, codes: dict[str, str] | None = None) -> str:
	m = _hash_of(file_url)
	if not m:
		return file_url or ""
	h32, turev, uzanti = m.group(2), m.group(3), m.group(4)
	kod = (codes if codes is not None else codes_for([file_url])).get(h32)
	if not kod:
		return (file_url or "").split("?")[0]
	return f"/files/{make_slug(title)}-{kod}{turev}.{uzanti}"


def on_file_after_insert(doc, method=None) -> None:
	# Yükleme yolunu asla düşürmez: kod atanamazsa API bugünkü adresi verir.
	if getattr(doc.flags, "ignore_seo_code", False):
		return
	try:
		assign_code(doc.file_url)
	except Exception:
		frappe.log_error(title="seo_code atanamadı", message=frappe.get_traceback())
```

`test_geri_dusus` beklentisi: `seo_image_url(kodsuz)` query string'siz girdiyi döner — kod yukarıdaki gibi.

- [ ] **Step 5: Kancalar** — `hooks.py` `doc_events["File"]` sözlüğüne (mevcut anahtarları silmeden) `"after_insert"` listesine ekle: `"tradehub_core.media.seo_url.on_file_after_insert"`. `after_insert` zaten liste ise sona ekle; string ise listeye çevir.
  `retro_rename.py` `rename_one` içinde başarı dalında (DB güncellemeleri commit'ten önce, `refs.retarget`'ten sonra) `seo_url.assign_code(new_url)` çağır; import `from tradehub_core.media import seo_url`.

- [ ] **Step 6: Migrate + testler PASS**

```bash
for f in media/seo_url.py patches/v15_9_61_file_seo_code.py patches.txt hooks.py media/retro_rename.py tests/test_media_seo_url.py; do docker cp tradehub_core/$f istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/$f; done
docker exec istoc-dev-backend-1 bench --site istoc.localhost migrate
docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_seo_url
docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_retro_rename
```
Beklenen: ikisi de OK. Migrate sonrası kontrol: `select count(*) from tabFile where seo_code is not null` > 0.

- [ ] **Step 7:** ruff temiz; commit YOK.

---

### Task 2: `SeoImageRenderer` — okunur adresi çöz ve servis et

**Files:**
- Create: `tradehub_core/media/seo_renderer.py`
- Modify: `tradehub_core/media/seo_url.py` (`resolve` + `owner_slugs` ekle)
- Modify: `tradehub_core/hooks.py:374` (`page_renderer` listesine SeoImageRenderer'ı MediaRedirectRenderer'dan ÖNCE ekle)
- Test: `tradehub_core/tests/test_media_seo_renderer.py`

**Interfaces:**
- Consumes: Task 1 `SEO_RE`, `make_slug`, `_like` deseni.
- Produces: `seo_url.resolve(path: str) -> dict` → `{"status": "ok"|"slug_eski"|"yok", "disk_url": str|None, "canonical": str|None}`; `seo_url.owner_slugs(file_url: str) -> list[str]`.

- [ ] **Step 1: Failing testler** — `tests/test_media_seo_renderer.py`: gerçek küçük dosya diske yazılır (`get_files_path()` altında `xx/hash.jpg`), `File` satırı + `Listing`? Listing kurmak ağır; `owner_slugs` yerine test `mock.patch.object(seo_url, "owner_slugs", return_value=["ahsap-raf"])` kullanır. Senaryolar:

```python
	def test_ok(self):  # /files/ahsap-raf-<kod>.jpg
		r = seo_url.resolve(f"files/ahsap-raf-{self.kod}.jpg")
		self.assertEqual(r["status"], "ok"); self.assertEqual(r["disk_url"], self.u)
	def test_ikinci_urunun_slugi_da_ok(self):  # owner_slugs iki slug döndürür
	def test_slug_eski_301(self):  # "eski-ad" → status slug_eski, canonical /files/ahsap-raf-<kod>.jpg
	def test_sahipsiz_dosya_her_slugla_ok(self):  # owner_slugs [] → ok
	def test_bilinmeyen_kod_yok(self):  # files/x-00000000.jpg → yok
	def test_uzanti_uyusmazsa_yok(self):  # .png istenirse, disk .jpg → yok
	def test_turev(self):  # diske hash__w384.webp yaz, files/ahsap-raf-<kod>__w384.webp → ok, disk_url türev
	def test_renderer_basliklari(self):
		# SeoImageRenderer(path).can_render() True; render() → 200, X-Accel-Redirect
		# "/protected/public/files/xx/hash.jpg", Cache-Control immutable, X-Robots-Tag yok
	def test_renderer_301(self):  # slug_eski → 301 Location canonical
	def test_renderer_baska_yol_ilgilenmez(self):  # "urun/abc", "files/0585.jpg" → can_render False
```
(Her testin tam gövdesi bu kalıpla yazılır; dosya/satır temizliği `addCleanup` + `frappe.db.commit` cleanup'ı ile, bkz. `test_media_retro_rename.TestPlan.setUp`.)

- [ ] **Step 2: FAIL gör.**

- [ ] **Step 3: `seo_url.py`'ye ekle:**

```python
import os
from frappe.utils import get_files_path


def owner_slugs(file_url: str) -> list[str]:
	"""Dosyayı kullanan ilanların slug'ları (birincil + galeri). Boşsa: sahipsiz."""
	basliklar = frappe.db.sql(
		"""select l.title from `tabListing` l where l.primary_image=%(u)s
			union select l.title from `tabListing Image` li join `tabListing` l on l.name=li.parent
			where li.image=%(u)s""",
		{"u": file_url},
		pluck=True,
	)
	return list(dict.fromkeys(make_slug(b) for b in basliklar if b))


def resolve(path: str) -> dict:
	yok = {"status": "yok", "disk_url": None, "canonical": None}
	m = SEO_RE.match((path or "").split("?")[0])
	if not m:
		return yok
	slug, kod, turev, uzanti = m.groups()
	urls = frappe.get_all("File", filters={"seo_code": kod}, pluck="file_url", distinct=True)
	if len(set(urls)) != 1:
		return yok
	asil = HASHED_RE.match(urls[0])
	if not asil:
		return yok
	h32 = asil.group(2)
	if not turev and uzanti != asil.group(4):
		return yok
	disk_url = f"/files/{h32[:2]}/{h32}{turev}.{uzanti}"
	if not os.path.isfile(os.path.join(get_files_path(is_private=0), h32[:2], f"{h32}{turev}.{uzanti}")):
		return yok
	sluglar = owner_slugs(urls[0])
	if sluglar and slug not in sluglar:
		return {"status": "slug_eski", "disk_url": disk_url, "canonical": f"/files/{sluglar[0]}-{kod}{turev}.{uzanti}"}
	return {"status": "ok", "disk_url": disk_url, "canonical": None}
```

- [ ] **Step 4: `media/seo_renderer.py`:**

```python
"""Okunur görsel adresi → X-Accel ile nginx'e servis (spec 2026-09-28-seo-gorsel-adresi §5.4).

Diskte olmayan `/files/…` istekleri buraya düşer (backend nginx `try_files … @webserver`).
Baytları nginx gönderir; burada yalnız tek indeksli sorgu + dosya varlık kontrolü var.
"""

from __future__ import annotations

import frappe
from frappe.website.page_renderers.redirect_page import RedirectPage
from werkzeug.wrappers import Response

from tradehub_core.media import seo_url


class SeoImageRenderer:
	def __init__(self, path: str, http_status_code: int | None = None) -> None:
		self.path = path or ""
		self.http_status_code = http_status_code
		self.sonuc: dict | None = None

	def can_render(self) -> bool:
		if not self.path.startswith("files/") or not seo_url.SEO_RE.match(self.path.split("?")[0]):
			return False
		self.sonuc = seo_url.resolve(self.path)
		return self.sonuc["status"] != "yok"

	def render(self):
		if self.sonuc["status"] == "slug_eski":
			frappe.flags.redirect_location = self.sonuc["canonical"]
			return RedirectPage(self.path, 301).render()
		yanit = Response()
		yanit.headers["X-Accel-Redirect"] = "/protected/public" + self.sonuc["disk_url"]
		yanit.headers["Cache-Control"] = "public, max-age=31536000, immutable"
		yanit.headers["Content-Type"] = ""  # nginx dosya uzantısından belirler
		return yanit
```
Not: `Content-Type` boş bırakıldığında nginx'in uzantıdan belirlediği lokalde doğrulanır; doğrulanamazsa `mimetypes.guess_type` ile doldur. `yok` durumunda `can_render` False döner, Frappe kendi 404'ünü verir; `MediaRedirectRenderer` okunur adresle eşleşmez (tablo kaydı yok).

- [ ] **Step 5:** `hooks.py`: `page_renderer = ["tradehub_core.media.seo_renderer.SeoImageRenderer", "tradehub_core.media.redirect_renderer.MediaRedirectRenderer"]`.

- [ ] **Step 6: PASS + gerçek istek** — testler; sonra backend + `istoc-dev-frappe-frontend-1` yeniden başlat (`docker restart istoc-dev-backend-1 && docker restart istoc-dev-frappe-frontend-1`) ve:
```bash
docker exec -i istoc-dev-backend-1 bench --site istoc.localhost console <<'EOF'
def _t():
	import frappe
	from tradehub_core.media import seo_url
	u = frappe.db.get_value("Listing", {"primary_image": ["like", "/files/__/%"]}, ["title", "primary_image"], as_dict=True)
	print("URL", seo_url.seo_image_url(u.primary_image, u.title))
_t()
EOF
curl -sI http://istoc.localhost<URL> | grep -iE "^(HTTP|content-type|cache-control|x-robots)"
```
Beklenen: `HTTP 200`, `content-type: image/…`, `cache-control: public, max-age=31536000, immutable`, `x-robots-tag` yok. Slug'ı değiştir → 301; kodu bozan → 404.

- [ ] **Step 7:** ruff; commit YOK.

---

### Task 3: API çıktıları okunur adres verir

**Files (Modify):** `tradehub_core/api/listing.py` (`_format_listing_card` ~3614, `get_listing_detail` ~1334-1761, top ranking ~2805-2838), `api/cart.py` (~620-721 `skuImage`, ~1452), `api/favorites.py` (~179), `api/order.py` (~88-102, ~298), `api/media_manifest.py` (türev adresleri + `fallback`), `seo/schema_builder.py` (Product JSON-LD `image`), `seo/meta_builder.py` (`og:image` — ürün görseli kullanılıyorsa), `seo/sitemap_generator.py` (`_image_entries_for_listing`, ~305). `_format_listing_card` çağıranlar (`api/brand.py`, `api/tailored.py`, `api/cart.py`, `doctype/listing/listing.py`) tek noktadan kapsanır.
**Test:** `tradehub_core/tests/test_media_seo_url_api.py`

**Interfaces:** Consumes Task 1 `seo_image_url(url, title, codes)`, `codes_for(urls)`.

**Kural:** Her uçta önce çıktıya girecek tüm görsel adresleri toplanır, `codes = seo_url.codes_for(tümü)` tek sorguyla alınır, sonra her adres `seo_image_url(url, ilan_başlığı, codes)` ile çevrilir. N+1 yok. İlan başlığı: kartta/detayda ilanın `title`'ı (dil çevirisi değil, orijinal TR başlık — slug her dilde aynı kalsın); sepet/favori/siparişte satırın ilanının `title`'ı; ilan silinmişse satırdaki ad; hiçbiri yoksa `None` (slug `gorsel`).

**Sipariş:** `Order Item.image` eski adsa ve ilan hâlâ varsa görsel ilanın güncel `primary_image`'ından üretilir (spec §5.3); ilan yoksa satırdaki adres aynen.

- [ ] **Step 1: Failing testler** — her uç için en az bir test: içerik-kodlu `primary_image`'lı bir ilan (`_make_listing` yardımcı: `tests/test_media_retro_rename.py` içindeki desen) kurulur, `assign_code` çağrılır, uç çağrılır, çıktıdaki görselin `seo_url.SEO_RE` ile eşleştiği ve slug'ın ilan başlığından geldiği doğrulanır. Kapsanacak: `get_listings` kartı, `get_listing_detail` (`images` tümü), `cart.get_cart` (`skuImage`), `favorites.get_my_favorites`, `order.get_my_orders`, `media_manifest.get_manifest` (renditions + fallback), schema builder Product `image`, sitemap `_image_entries_for_listing`. Ayrıca bir geri düşüş testi: eski adlı `primary_image` → çıktı aynen.
- [ ] **Step 2: FAIL gör.**
- [ ] **Step 3: Uygula** — her dosyada çıktı sözlüğü kurulmadan hemen önce yukarıdaki kural. `_format_listing_card` tek kart aldığı için imzasına isteğe bağlı `codes: dict | None = None` eklenir; liste çağıranları kodları önceden bir kez alıp geçirir, tek çağıranlar `None` geçer (fonksiyon kendi tek sorgusunu yapar).
- [ ] **Step 4: PASS** — yeni test modülü + mevcut modüller: `test_media_retro_rename`, `test_media_admin_retro_rename` ve `grep -l "_format_listing_card\|get_cart\|get_listing_detail" tradehub_core/tests/*.py` ile bulunan test modülleri.
- [ ] **Step 5:** ruff; commit YOK.

---

### Task 4: Sepet/favori görselleri taşımaya dahil + tek seferlik düzeltme yaması

**Files:**
- Modify: `tradehub_core/media/usage.py` (`("tabCart Item","snapshot_image",…)` ve `("tabBuyer Favorite Item","snapshot_image",…)` satırlarını `ORDER_SOURCES`'tan `LIVE_SOURCES`'a taşı)
- Create: `tradehub_core/patches/v15_9_62_retarget_cart_favorite_snapshots.py`
- Modify: `tradehub_core/patches.txt`
- Test: `tradehub_core/tests/test_media_retro_rename.py` (yeni test sınıfı `TestCartFavoriteRetarget`)

- [ ] **Step 1: Failing test** — bir `Cart Item` (ya da `Buyer Favorite Item`) `snapshot_image` = eski adla kurulur; `rename_one` sonrası alan yeni adresi göstermeli; `run_rollback` sonrası eski adrese dönmeli. Kurulum için mevcut `_make_listing` + doctype'ın zorunlu alanları (`frappe.get_meta("Cart Item").get_valid_columns()` ile kontrol) kullanılır.
- [ ] **Step 2: FAIL gör** (bugün `readonly` sayıldığı için değişmez).
- [ ] **Step 3: `usage.py`'de satırları taşı.** `refs.READONLY_TABLES` ORDER_SOURCES'tan türediği için otomatik güncellenir; `_WRITABLE` LIVE_SOURCES'tan türediği için yazma izni otomatik gelir.
- [ ] **Step 4: Yama:**

```python
"""Taşıması yapılmış ortamlarda sepet/favori görsel kopyalarını yeni adrese çevir.

Retro-rename bu alanları eskiden "geçmiş kaydı" sayıp güncellemedi; 90 gün sonra
Media URL Redirect satırları silinince görseller kırılırdı. İdempotent: yalnız
hâlâ eski adres gösteren satırlar ve hâlâ duran yönlendirmeler.
"""

from __future__ import annotations

import frappe

TABLOLAR = ("tabCart Item", "tabBuyer Favorite Item")


def execute() -> None:
	for tablo in TABLOLAR:
		frappe.db.sql(
			f"""update `{tablo}` t join `tabMedia URL Redirect` r on r.source_url = t.snapshot_image
				set t.snapshot_image = r.target_url"""  # noqa: S608 — sabit tablo adı
		)
	frappe.db.commit()
```
`patches.txt` sonuna ekle.
- [ ] **Step 5: PASS** — `test_media_retro_rename` tamamı; migrate; lokalde `select count(*) from tabCart Item where snapshot_image regexp '^/files/[^/]+$'` yama sonrası 0 (dosyası taşınmış olanlar için).
- [ ] **Step 6:** ruff; commit YOK.

---

### Task 5: Vitrin — noindex istisnası, önbellek düzeltmesi, LCP deseni

**Files:**
- Modify: `tradehubfront/nginx.conf.template` (`location ^~ /files/` bloğu ~42774)
- Modify: `tradehubfront/src/lib/query/queryClient.ts`
- Modify: `tradehubfront/src/lib/rum/lcpAsset.js:54`, `admin-panel/frontend/src/lib/media/rum/lcpAsset.js:48`
- Test: `tradehubfront/src/lib/query/queryClient.test.ts` (yoksa oluştur), iki `lcpAsset` testi (varsa mevcut test dosyasına ekle)

- [ ] **Step 1: nginx** — `location ^~ /files/` içindeki `add_header X-Robots-Tag "noindex" always;` satırını değişkenle değiştir; `http` seviyesinde (şablonda `map` blokları nerede ise oraya) ekle:

```nginx
map $uri $files_robots {
    ~^/files/[a-z0-9-]+-[0-9a-f]{8,32}(__[a-z0-9]+)?\.[a-z0-9]+$  "";
    default                                                        "noindex";
}
```
ve blokta `add_header X-Robots-Tag $files_robots always;` (boş değerli `add_header` nginx'te başlığı hiç basmaz). `limit_req` ve diğer başlıklar aynen.
  Doğrulama: `docker run --rm -v $PWD/nginx.conf.template:/t nginx:1.29 sh -c "envsubst < /t > /etc/nginx/conf.d/default.conf && nginx -t"` ya da şablonun mevcut test/derleme yolu (`DEPLOYMENT.md`).

- [ ] **Step 2: Önbellek** — önce kurulu sürümün dokümanı: `grep '"@tanstack/query-persist-client-core"' package.json` ve context7 ile `experimental_createQueryPersister` seçenekleri (sürümü sorguda belirt). Hedef: `listings` ile başlayan anahtarlar IndexedDB'ye yazılmaz, bellekte `staleTime` 60 sn geçerli. Beklenen uygulama (doküman teyit ederse): `persisterFn` yerine sorgu bazında persister — `queryFetch` `key[0] === "listings"` ise `persister: undefined` geçer:

```ts
// queryFetch.ts — fetchQuery/prefetchQuery seçeneklerine:
persister: NON_PERSISTED.has(String(key[0])) ? undefined : persister.persisterFn,
```
ve `queryClient.ts`'ten `persister`'ı export et, `defaultOptions.queries.persister`'ı kaldır; `NON_PERSISTED = new Set(["listings"])`. Test: `listings` anahtarlı `queryFetch` sonrası IndexedDB adaptörüne (`idbStorage` mock) yazma çağrısı olmadığını, `categories` anahtarında olduğunu doğrula.

- [ ] **Step 3: LCP deseni** — iki dosyada regex'e okunur biçimi ekle:

```js
/(?:^|\/)files\/(?:[0-9a-f]{2}\/[0-9a-f]{32}|[a-z0-9-]+-[0-9a-f]{8,32})(?:__[a-z0-9]+)?\.(?:avif|webp|jpe?g|png)$/i;
```
Test: iki biçimin de eşleştiği, `/files/0585.jpg`'nin eşleşmediği.

- [ ] **Step 4:** `cd tradehubfront && npm test` (ve varsa lint); `cd admin-panel/frontend && npm test`. Beklenen: yeni testler geçer, önceden var olan hatalar dışında yeni hata yok. Commit YOK.

---

### Task 6: Uçtan uca lokal doğrulama (kontrolcü)

- [ ] Backend kodu `docker cp` + migrate + backend/frappe-frontend restart; storefront imajını `--no-deps` ile yeniden kur (`cd docker && docker compose build storefront && docker compose up -d --no-deps storefront`), sonra frappe-frontend restart (hafıza: bayat upstream).
- [ ] http://istoc.localhost ana sayfa, ürün detay, sepet, `/pages/order/checkout.html`, favoriler, siparişler: `<img src>` okunur biçimde; `curl -sI` ile 200 + `noindex` yok; slug değiştir → 301; kod boz → 404; `/files/xx/<hash>.jpg` hâlâ 200 + `noindex`; eski ad hâlâ 301.
- [ ] Site haritası ürün parçasında `<image:loc>` okunur adres.
- [ ] Sonuç, kullanıcıya sırayla test listesiyle raporlanır; commit onayı istenir.
