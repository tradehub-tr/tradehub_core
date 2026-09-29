# Retro-rename: çift noktalı ad ve arşiv bağımlılığı — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retro-rename ön raporu çift noktalı adları ve optimizasyon arşivinde orijinali bekleyen dosyaları ayrı saysın. Arşive bağlı dosya varken gerçek (prova olmayan) toplu taşıma başlatılamasın. Panel kartı bunları göstersin.

**Architecture:** Tespit `tradehub_core/media/retro_rename.py`'de yapılır (`_inspect` → `plan`/`count_summary`). Kapı iki katmanda: API ucu `start_retro_rename` prova değilse arşive bağlı aday varken reddeder, worker `rename_one` da çalışma sırasında arşive düşen dosyayı `archived` nedeniyle atlar. Panel yalnız yeni alanları gösterir ve kapıyı düğmede yansıtır. Backend ve panel arasındaki sözleşme aşağıdaki "Sözleşme" bölümünde sabit; iki taraf paralel yazılabilir.

**Tech Stack:** Frappe v15 (Python, `FrappeTestCase`), Vue 3.5 `<script setup>` + vue-i18n, `node:test` (vitest yok).

**Spec:** Plane MOGEM-619 kabul kriterleri 1 ve 5; `docs/MEDYA-DEPOLAMA-STANDARDI.md` §7.1 madde 3 (M-A arşivi önce boşaltılmalı); `docs/reports/95-retro-rename-lokal-kosu.md` §11.3 / §14.

## Global Constraints

- Arşiv = `media/archive.py` optimizasyon geri-alma arşivi (`<site>/private/image_originals/`), dosyayı `file_url` ile adresler. `archive.exists(file_url)` → bool; geçersiz yolda `frappe.ValidationError` fırlatır.
- Saklama süresi sabiti: `tradehub_core.media.presets.ARCHIVE_RETENTION_DAYS` (mesajda sayı olarak bu kullanılır, elle yazılmaz).
- Çift nokta = dosya adı (son `/` sonrası) içinde `".."` alt dizgisi. Yol segmenti `".."` olanlar zaten `is_legacy_name` tarafından elenir; bu sayaç yalnız bilgi amaçlıdır, taşımayı engellemez.
- Prova (`dry_run=1`) her zaman serbest; kapı yalnız gerçek taşımaya uygulanır.
- Panel dört dilde: `tr.js`, `en.js`, `ru.js`, `ar.js` — anahtar eşitliği `src/i18n/__tests__/ceviriButunlugu.test.js` ile denetlenir.
- Commit YOK: kullanıcı her commit için ayrıca açık onay verir. Görevler "commit'e hazır" durumda biter.
- Backend testleri `istoc-dev-backend-1` konteynerinde koşar; kod imajda olduğundan değişen dosyalar `docker cp` ile geçici kopyalanır (kalıcı değil, imaj rebuild ayrı iş).

## Sözleşme (backend ↔ panel)

`retro_rename_plan` yanıtına eklenen alanlar:

```json
{ "double_dots": 0, "archived": 0 }
```

Her `items[i]` ögesine: `"double_dot": false, "archived": false`.

`retro_rename_count` yanıtı: `{"total", "disk_missing", "renamable", "archived"}` — `archived` yeni.

`start_retro_rename(dry_run=0)` arşive bağlı aday varken `frappe.ValidationError` fırlatır; mesaj Türkçe, sayıyı içerir.

İş ilerlemesindeki `skip_reasons` sözlüğünde yeni anahtar: `"archived"`.

## Review Focus

1. Arşiv kökü hiç yok (yeni site) → `archived` 0, taşıma serbest, hata yok. (Task 1 testi: arşivsiz aday.)
2. `archive.exists` geçersiz yol için throw eder → `_inspect` / `plan` patlamamalı, dosya "arşivde değil" sayılmalı. (Task 1 testi: `archive.exists` ValidationError mock'u.)
3. Prova başlatma arşive bağlı dosya varken de çalışmalı; yalnız gerçek başlatma reddedilmeli. (Task 2: iki test.)
4. Rapor açıkken kullanıcı prova kutusunu işaretleyince düğme açılmalı, kaldırınca kapanmalı. (Task 3: kaynak metin testi `startBlocked` hesaplaması.)
5. Eski backend `archived` alanı göndermiyorsa panel kapıyı kapalı saymamalı (`?? 0`). (Task 3: kaynak metin testi.)

---

### Task 1: Backend — tespit ve sayaçlar (`retro_rename.py`)

**Files:**
- Modify: `tradehub_core/media/retro_rename.py` (import satırı ~25; `_inspect` ~138-155; `count_summary` ~158-168; `plan` ~171-205; `rename_one` ~430-440)
- Test: `tradehub_core/tests/test_media_retro_rename.py` (`TestPlan` sınıfı, `TestRenameOne` sınıfı)

**Interfaces:**
- Produces: `retro_rename.has_double_dot(url: str) -> bool`, `retro_rename.is_archived(url: str) -> bool`, `retro_rename.archive_blockers(urls: list[str] | None = None) -> list[str]`; `plan()` yeni anahtarlar `double_dots`, `archived`; `count_summary()` yeni anahtar `archived`; `rename_one` yeni atlama nedeni `"archived"`.

- [ ] **Step 1: Başarısız testleri yaz** — `TestPlan` sonuna ekle:

```python
	def test_plan_arsive_bagli_dosyayi_sayar(self):
		from tradehub_core.media import archive

		archive.store(self.url, self.content)
		self.addCleanup(lambda: archive.drop(self.url))
		p = retro_rename.plan()
		item = next(i for i in p["items"] if i["source_url"] == self.url)
		self.assertTrue(item["archived"])
		self.assertGreaterEqual(p["archived"], 1)
		self.assertIn(self.url, retro_rename.archive_blockers())
		self.assertGreaterEqual(retro_rename.count_summary()["archived"], 1)

	def test_plan_arsivsiz_aday_arsivde_sayilmaz(self):
		p = retro_rename.plan()
		item = next(i for i in p["items"] if i["source_url"] == self.url)
		self.assertFalse(item["archived"])
		self.assertNotIn(self.url, retro_rename.archive_blockers())

	def test_arsiv_kontrolu_gecersiz_yolda_patlamaz(self):
		from tradehub_core.media import archive

		with mock.patch.object(archive, "exists", side_effect=frappe.ValidationError("x")):
			self.assertFalse(retro_rename.is_archived(self.url))
			retro_rename.plan()  # throw etmemeli

	def test_cift_noktali_ad_ayri_sayilir(self):
		ad = f"rr-nokta-{self.suffix}..jpg"
		url = _write_flat_public(ad, b"nokta")
		self.addCleanup(lambda: os.remove(os.path.join(get_files_path(is_private=0), ad)))
		d = frappe.get_doc({"doctype": "File", "file_name": ad, "file_url": url, "is_private": 0})
		d.flags.copy_from_existing_file = True
		d.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("File", d.name, force=True, ignore_permissions=True))
		frappe.db.commit()
		p = retro_rename.plan()
		item = next(i for i in p["items"] if i["source_url"] == url)
		self.assertTrue(item["double_dot"])
		self.assertGreaterEqual(p["double_dots"], 1)
		normal = next(i for i in p["items"] if i["source_url"] == self.url)
		self.assertFalse(normal["double_dot"])

	def test_has_double_dot_yalniz_dosya_adina_bakar(self):
		self.assertTrue(retro_rename.has_double_dot("/files/derin düzen..jpg"))
		self.assertFalse(retro_rename.has_double_dot("/files/a.b.jpg"))
		self.assertFalse(retro_rename.has_double_dot("/files/x/a.jpg"))
```

`TestRenameOne` sonuna ekle (`_RenameBase.setUp` taşınacak dosyayı `self.url` olarak kurar):

```python
	def test_arsive_bagli_dosya_atlanir(self):
		from tradehub_core.media import archive

		archive.store(self.url, b"orijinal")
		self.addCleanup(lambda: archive.drop(self.url))
		out = retro_rename.rename_one(self.url, "rr-arsiv", None)
		self.assertEqual(out["status"], "skipped")
		self.assertEqual(out["reason"], "archived")
		self.assertTrue(os.path.isfile(retro_rename._disk_path(self.url)))

	def test_provada_arsiv_atlama_nedeni_degil(self):
		from tradehub_core.media import archive

		archive.store(self.url, b"orijinal")
		self.addCleanup(lambda: archive.drop(self.url))
		out = retro_rename.rename_one(self.url, "rr-arsiv-prova", None, dry_run=True)
		self.assertNotEqual(out.get("reason"), "archived")
```

- [ ] **Step 2: Testleri koş, başarısız olduklarını gör**

```bash
docker cp tradehub_core/tests/test_media_retro_rename.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/tests/
docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_retro_rename
```

Beklenen: yeni testler `KeyError: 'archived'` / `AttributeError: ... has_double_dot` ile FAIL.

- [ ] **Step 3: Uygulamayı yaz**

Import satırını güncelle:

```python
from tradehub_core.media import archive, audit, naming, refs
```

`_ref_counts`'tan önce ekle:

```python
def has_double_dot(url: str) -> bool:
	"""Dosya adında gerçek `..` var mı (`derin düzen..jpg`). Yalnız bilgi amaçlı.

	Rapor 95'te bu adlar önce aday dışı kalmıştı; segment düzeyi korumadan beri
	taşınıyorlar ama operatör ayrı görmek istiyor (MOGEM-619 kabul 1).
	"""
	return ".." in (url or "").split("?")[0].rsplit("/", 1)[-1]


def is_archived(url: str) -> bool:
	"""Optimizasyon arşivinde bu adresin orijinali duruyor mu.

	`archive` orijinali ESKİ `file_url` ile adresler; taşıma onu izlemez ve
	"optimizasyonu geri al" sessizce kırılır (MEDYA-DEPOLAMA-STANDARDI §7.1/3).
	Geçersiz yolda `archive` throw eder — rapor bunun için patlamamalı.
	"""
	try:
		return archive.exists(url)
	except frappe.ValidationError:
		return False


def archive_blockers(urls: list[str] | None = None) -> list[str]:
	"""Gerçek taşımayı engelleyen adaylar: orijinali arşivde bekleyenler."""
	return [u for u in (legacy_urls() if urls is None else urls) if is_archived(u)]
```

`_inspect` içindeki `item` sözlüğüne iki alan ekle ve `disk_missing` erken dönüşünden ÖNCE doldur:

```python
		"collision": False,
		"double_dot": has_double_dot(url),
		"archived": is_archived(url),
	}
```

`count_summary` dönüşünü değiştir (docstring'deki anahtar listesine `archived` ekle):

```python
	urls = legacy_urls()
	eksik = sum(1 for u in urls if not os.path.isfile(_disk_path(u)))
	return {
		"total": len(urls),
		"disk_missing": eksik,
		"renamable": len(urls) - eksik,
		"archived": len(archive_blockers(urls)),
	}
```

`plan` içinde `out` sözlüğüne `"double_dots": 0, "archived": 0,` ekle; döngüye:

```python
		out["double_dots"] += int(it["double_dot"])
		out["archived"] += int(it["archived"])
```

`rename_one` içinde karantina kontrolünden hemen sonra:

```python
	# Orijinali optimizasyon arşivinde bekleyen dosya taşınırsa geri alma kırılır;
	# API kapısı başlatmayı engelliyor, bu satır iş sırasında arşive düşeni tutar.
	if not dry_run and is_archived(url):
		return _skip("archived")
```

- [ ] **Step 4: Testleri koş, geçtiklerini gör**

```bash
docker cp tradehub_core/media/retro_rename.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/media/
docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_retro_rename
```

Beklenen: tümü PASS (önceden geçenler dahil).

- [ ] **Step 5: Commit'e hazır bırak** — `git -C tradehub_core diff --stat` çıktısını rapora ekle; commit kullanıcı onayıyla.

---

### Task 2: Backend — başlatma kapısı (`media_admin.py`)

**Files:**
- Modify: `tradehub_core/api/media_admin.py:1248-1275` (`start_retro_rename`)
- Test: `tradehub_core/tests/test_media_admin_retro_rename.py`

**Interfaces:**
- Consumes: `retro_rename.archive_blockers(urls: list[str]) -> list[str]` (Task 1), `retro_rename.legacy_urls() -> list[str]`.
- Produces: `start_retro_rename` gerçek koşuda arşive bağlı aday varken `frappe.ValidationError`.

- [ ] **Step 1: Başarısız testleri yaz** — sınıf sonuna ekle; ayrıca `test_count_doner` beklenen sözlüğünü `{"total": 3, "disk_missing": 3, "renamable": 0, "archived": 0}` yap:

```python
	def test_arsive_bagli_varken_gercek_kosu_baslatilamaz(self):
		with (
			mock.patch.object(media_admin.frappe, "enqueue") as enq,
			mock.patch.object(retro_rename, "legacy_urls", return_value=["/files/a.jpg"]),
			mock.patch.object(retro_rename, "archive_blockers", return_value=["/files/a.jpg"]),
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				media_admin.start_retro_rename(dry_run=0)
		self.assertIn("1", str(ctx.exception))
		enq.assert_not_called()
		self.assertIsNone(frappe.cache.get_value(retro_rename.ACTIVE_KEY, expires=True))

	def test_arsive_bagli_varken_prova_baslatilabilir(self):
		with (
			mock.patch.object(media_admin.frappe, "enqueue") as enq,
			mock.patch.object(retro_rename, "legacy_urls", return_value=["/files/a.jpg"]),
			mock.patch.object(retro_rename, "archive_blockers", return_value=["/files/a.jpg"]),
		):
			out = media_admin.start_retro_rename(dry_run=1)
		self.assertTrue(out["job_key"])
		enq.assert_called_once()
```

- [ ] **Step 2: Koş, başarısız olduğunu gör**

```bash
docker cp tradehub_core/tests/test_media_admin_retro_rename.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/tests/
docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_admin_retro_rename
```

Beklenen: `test_arsive_bagli_varken_gercek_kosu_baslatilamaz` FAIL (throw yok). Task 1 henüz konteynerde değilse `archive_blockers` AttributeError verir — önce Task 1'in `retro_rename.py`'sini kopyala.

- [ ] **Step 3: Uygulamayı yaz** — `start_retro_rename` başını şöyle değiştir (kilit alınmadan ÖNCE reddedilmeli):

```python
	_guard_destructive()
	urls = retro_rename.legacy_urls()
	total = len(urls)
	if not total:
		frappe.throw(_("Taşınacak eski adlı dosya yok."))
	# MEDYA-DEPOLAMA-STANDARDI §7.1/3: optimizasyon arşivi orijinali ESKİ adla
	# tutuyor; taşıma onu izlemez, geri alma sessizce kırılır. Prova serbest.
	if not int(dry_run or 0):
		bekleyen = retro_rename.archive_blockers(urls)
		if bekleyen:
			frappe.throw(
				_(
					"{0} dosyanın optimizasyon öncesi orijinali arşivde bekliyor. "
					"Arşiv {1} günlük süresi dolup temizlenene kadar yalnız prova çalıştırılabilir."
				).format(len(bekleyen), presets.ARCHIVE_RETENTION_DAYS)
			)
```

`presets` modülü dosyada zaten import edilmiş (`from tradehub_core.media import (..., presets, ...)`); yeni import gerekmez.

- [ ] **Step 4: Koş, geçtiğini gör** — Step 2 komutlarını `media_admin.py` kopyalandıktan sonra tekrarla:

```bash
docker cp tradehub_core/api/media_admin.py istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/api/
docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_admin_retro_rename
docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_retro_rename
```

Beklenen: iki modül de tamamen PASS.

- [ ] **Step 5: Commit'e hazır bırak** — commit kullanıcı onayıyla.

---

### Task 3: Panel — kart, çeviriler, testler (admin-panel)

Task 1–2 ile paralel yürütülebilir; yalnız yukarıdaki Sözleşme'ye dayanır.

**Files:**
- Modify: `admin-panel/frontend/src/components/media/MediaRetroRenameCard.vue` (script: `refsTotal` sonrası; şablon: önizleme `<dl>` ~214-250, düğme ~258-266)
- Modify: `admin-panel/frontend/src/i18n/locales/{tr,en,ru,ar}.js` (`mediaRetroRename.stats`, `mediaRetroRename.skip`, `mediaRetroRename` kökü)
- Test: `admin-panel/frontend/src/components/media/__tests__/mediaRetroRenameCard.test.js` (bölüm 4)

**Interfaces:**
- Consumes: `r.plan.value.double_dots`, `r.plan.value.archived`, iş `skip_reasons.archived` (Sözleşme).
- Produces: i18n anahtarları `mediaRetroRename.stats.doubleDots`, `mediaRetroRename.stats.archived`, `mediaRetroRename.archiveBlocked`, `mediaRetroRename.skip.archived`.

- [ ] **Step 1: Başarısız testi yaz** — bölüm 4'e ekle:

```js
test("önizleme çift nokta ve arşiv sayaçlarını gösterir; arşiv gerçek koşuyu kilitler", () => {
  assert.match(cardSrc, /r\.plan\.value\.double_dots/);
  assert.match(cardSrc, /r\.plan\.value\.archived/);
  assert.match(cardSrc, /t\(["']mediaRetroRename\.stats\.doubleDots["']\)/);
  assert.match(cardSrc, /t\(["']mediaRetroRename\.stats\.archived["']\)/);
  // Eski backend alanı göndermezse kapı kapalı sayılmamalı.
  assert.match(cardSrc, /const archivedCount = computed\(\(\) => r\.plan\.value\?\.archived \?\? 0\)/);
  // Prova kutusu işaretliyse kapı açılır.
  assert.match(cardSrc, /const startBlocked = computed\(\(\) => archivedCount\.value > 0 && !dryRun\.value\)/);
  assert.match(cardSrc, /:disabled="!r\.plan\.value\.renamable \|\| startBlocked \|\| r\.actionLoading\.value"/);
  assert.match(cardSrc, /t\(["']mediaRetroRename\.archiveBlocked["'], \{ n: archivedCount \}\)/);
});

test("arşiv kilidi ve yeni sayaçlar dört dilde çevrili", () => {
  for (const [ad, dil] of Object.entries({ tr, en })) {
    const m = dil.mediaRetroRename;
    assert.ok(m.stats.doubleDots, `${ad}: stats.doubleDots`);
    assert.ok(m.stats.archived, `${ad}: stats.archived`);
    assert.ok(m.skip.archived, `${ad}: skip.archived`);
    assert.match(m.archiveBlocked, /\{n\}/, `${ad}: archiveBlocked {n} içermeli`);
  }
});
```

(ru/ar eşitliği `ceviriButunlugu.test.js` tarafından zaten denetlenir.)

- [ ] **Step 2: Koş, başarısız olduğunu gör**

```bash
cd admin-panel/frontend && node --test src/components/media/__tests__/mediaRetroRenameCard.test.js
```

Beklenen: iki yeni test FAIL.

- [ ] **Step 3: Kartı güncelle**

Script'te `refsTotal` tanımından sonra:

```js
  // Optimizasyon arşivi orijinali ESKİ adla tutuyor; taşıma onu izlemez. Backend
  // gerçek koşuyu zaten reddediyor — düğme de kapalı dursun, neden yazsın.
  // Prova serbest. `?? 0`: alanı göndermeyen eski backend kilitlemesin.
  const archivedCount = computed(() => r.plan.value?.archived ?? 0);
  const startBlocked = computed(() => archivedCount.value > 0 && !dryRun.value);
```

Önizleme `<dl>` içinde `refs_readonly` bloğundan sonra:

```html
          <div>
            <dt class="opacity-70">{{ t("mediaRetroRename.stats.doubleDots") }}</dt>
            <dd>
              <b>{{ r.plan.value.double_dots ?? 0 }}</b>
            </dd>
          </div>
          <div>
            <dt class="opacity-70">{{ t("mediaRetroRename.stats.archived") }}</dt>
            <dd>
              <b>{{ r.plan.value.archived ?? 0 }}</b>
            </dd>
          </div>
```

Prova `<label>`'ından sonra:

```html
        <p v-if="r.plan.value && startBlocked" class="text-sm text-amber-700 mt-2" role="alert">
          {{ t("mediaRetroRename.archiveBlocked", { n: archivedCount }) }}
        </p>
```

Başlat düğmesinin `:disabled`'ını değiştir:

```html
            :disabled="!r.plan.value.renamable || startBlocked || r.actionLoading.value"
```

- [ ] **Step 4: Çevirileri ekle** — her dosyada `mediaRetroRename.stats` sonuna, `mediaRetroRename.skip` sonuna ve `mediaRetroRename` köküne (`dryRun` satırının yanına):

`tr.js`:
```js
      doubleDots: "Çift noktalı ad",
      archived: "Orijinali arşivde",
```
```js
      archived: "Orijinali arşivde (geri alma kırılırdı)",
```
```js
    archiveBlocked:
      "{n} dosyanın optimize edilmeden önceki orijinali arşivde bekliyor. Taşıma bunların geri alınmasını bozar; arşiv süresi dolana kadar yalnız prova çalıştırılabilir.",
```

`en.js`:
```js
      doubleDots: "Double-dot name",
      archived: "Original in archive",
```
```js
      archived: "Original in archive (undo would break)",
```
```js
    archiveBlocked:
      "{n} files still have their pre-optimization original in the archive. Renaming would break undo; only a dry run is allowed until the archive expires.",
```

`ru.js`:
```js
      doubleDots: "Имя с двумя точками",
      archived: "Оригинал в архиве",
```
```js
      archived: "Оригинал в архиве (отмена сломается)",
```
```js
    archiveBlocked:
      "У {n} файлов оригинал до оптимизации ещё хранится в архиве. Переименование сломает отмену; до истечения срока архива доступен только пробный запуск.",
```

`ar.js`:
```js
      doubleDots: "اسم بنقطتين",
      archived: "الأصل في الأرشيف",
```
```js
      archived: "الأصل في الأرشيف (سيتعطل التراجع)",
```
```js
    archiveBlocked:
      "لا يزال الأصل قبل التحسين لـ {n} ملفات محفوظًا في الأرشيف. إعادة التسمية ستعطل التراجع؛ يُسمح بالتشغيل التجريبي فقط حتى انتهاء مدة الأرشيف.",
```

- [ ] **Step 5: Tüm panel testlerini koş**

```bash
cd admin-panel/frontend && npm test 2>&1 | tail -15
```

Beklenen: `fail 0`. `ceviriButunlugu` anahtar eşitliği geçmeli.

- [ ] **Step 6: Commit'e hazır bırak** — commit kullanıcı onayıyla.

---

### Task 4: Uçtan uca yerel doğrulama

**Files:** yok (yalnız doğrulama).

- [ ] **Step 1:** Konteynerde gerçek veriyle rapor ve kapıyı gör:

```bash
docker exec istoc-dev-backend-1 bench --site istoc.localhost execute tradehub_core.media.retro_rename.count_summary
docker exec istoc-dev-backend-1 bench --site istoc.localhost console <<'EOF'
from tradehub_core.media import retro_rename as r
p = r.plan(limit=0); print({k: p[k] for k in ("total","renamable","double_dots","archived")})
EOF
```

Beklenen: anahtarlar var, sayılar tutarlı (`archived` ≤ `total`).

- [ ] **Step 2:** Panel derle ve kartı gözle doğrula: `cd admin-panel/frontend && npm run build`; admin panel imajı gerekiyorsa `admin-panel-docker-image-rebuild` notuna göre yeniden kur; Sistem → Medya → Önizle'de iki yeni satır ve (arşivde dosya varsa) sarı uyarı + kapalı düğme görünmeli; prova kutusu işaretlenince düğme açılmalı.

- [ ] **Step 3:** Sonucu kullanıcıya raporla; iki reponun `git diff --stat` çıktısıyla commit onayı iste. Onaylanırsa Plane MOGEM-619'a düz metin "Yapıldı / Yapılmadı" yorumu.
