# ADR-0003 — Medya motoru ayrı bir Frappe app'i değil, `tradehub_core` içinde bir kütüphanedir

**Durum:** Kabul edildi · **uygulaması karardan saptı** (aşağıda)
**Tarih:** karar `docs/sad/SAD-v1.0.md` §2.3 (S-01) · sapma 2026-08-19'da ölçüldü
**İlgili:** ADR-0004 (saf çekirdek kuralı — bu kararın korunan yarısı)

---

## Bağlam

Kaynak tasarım dokümanı ayrı bir `media_engine` Frappe app'i öngörüyordu. İstoç
tarafında medya zaten `tradehub_core` içinde bir modüldü (`tradehub_core/media/`),
ve platformun kendi kuralı (`CLAUDE.md` §4) DocType/app şişmesine karşı.

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — Ayrı `media_engine` Frappe app'i (kaynak dokümanın önerisi) | Temiz sınır, kendi `hooks.py`'si. Bedeli: **veriyi ikiye böler** (G1), tek kapı kuralını kırar (G2), iki app'in migrate sırası ve sürüm eşlemesi. |
| **B (SEÇİLEN)** — `tradehub_core`'un **yanında** duran saf Python kütüphanesi, app değil | Tek app, tek migrate, tek kapı. Kütüphane olmak test edilebilirliği artırır (G3). "Bir gün `hooks.py` + `modules.txt` eklenerek app'e terfi eder" (G4) — geri dönüş açık kalır. |
| C — Kodu doğrudan mevcut `media/` modülüne karıştır | Sınır yok; frappe'siz test imkânsız hale gelir. |

## Karar

**B.** `media_engine` ayrı bir app olmayacak. `tradehub_core/media/pipeline/__init__.py`
başlığı bunu açıkça yazıyor: *"**Bu bir Frappe app'i DEĞİLDİR.** … İstoç'ta medya
`tradehub_core` içinde bir modüldür ve bu paket onun YANINDA duran bir
kütüphanedir. Gerekçe: `docs/sad/SAD-v1.0.md` §2.3 (S-01 sapması)."*

## Gerekçe

- **G1** — Ayrı app veriyi ikiye böler (iki site tablosu kümesi, iki izin modeli).
- **G2** — Ayrı app "tek kapı" kuralını kırar: yetki, kota ve denetim tek yerden
  geçmelidir.
- **G3** — Kütüphane olmak bench/site/DB olmadan test edilebilirlik verir.
- **G4** — Geri dönüş açık: bir gün app'e terfi edebilir.

## Sonuçlar

### Olumlu — ölçüldü

G3 kanıtlandı (`docs/reports/21-t030-mimari-inceleme.md` M-01):

```
$ python3 -m unittest tradehub_core.tests.test_contracts
Ran 69 tests in 0.052s — OK          (frappe yok, site yok, bench yok)
$ python3 -m unittest tradehub_core.tests.test_policy_engine
Ran 38 tests in 1.623s — OK
```

`tradehub_core/__init__.py` yalnız `__version__` içeriyor ve `import frappe`
yapmıyor; bu yüzden paket app'in içinde olmasına rağmen frappe'siz import
edilebiliyor.

### Olumsuz — kararın uygulaması karardan saptı

Karar metni *"`tradehub_core`'un **YANINDA** duran"* diyor. Gerçekte paket
`tradehub_core`'un **içine** kondu: repo kökünde `media_engine` diye bir dizin
**yok**, paket `tradehub_core/media/pipeline/` altında (16 alt paket, 71 `.py`).
Frappe yalnız app paketinin içini yüklediği için bu konum çalışır — ama karar
metniyle aynı şey değildir.

| G# | Bugünkü konumda hâlâ geçerli mi |
|---|---|
| G1, G2 | Geçerli |
| **G3** | ✅ Hâlâ doğru — yukarıda kanıtlandı |
| **G4** | ❌ **Artık geçerli değil.** App paketinin *içindeki* bir alt paket app'e terfi edemez; önce dışarı taşınması gerekir. G4'ün savunduğu "tek yönlü olmama" özelliği kayboldu. |

Ayrıca SAD'ın kendisi tutarsız kaldı: **6 satır hâlâ `media_engine` diyor**
(SAD:66, 69, 102, 122, 167, 209), gerisi `tradehub_core/media/pipeline` diyor —
tamamlanmamış bir toplu ad değiştirmenin izi
(`docs/reports/21-t030-mimari-inceleme.md` M-01, **BLOKLAYICI**).

### Bu kararın komşusu olan ve ÇÜRÜYEN karar

Aynı karar kümesindeki **S-03 — "Yeni DocType açılmaz"** çürüdü: bugün 5 yeni
DocType kurulu (`Media Asset`, `Media Rendition`, `Media Processing Job`,
`Media Profile`, `Media Engine Settings`). Terk edilme gerekçesi bir yerde yazılı
olabilir ama **SAD'da değil**; belge kararı hâlâ yürürlükteymiş gibi anlatıyor
(`docs/reports/21-t030-mimari-inceleme.md` M-04, **BLOKLAYICI**). Bu ADR o kararı
kapsamıyor; **gerekçesi bulunamadığı için ayrı bir ADR yazılmadı.**
