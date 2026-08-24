# ADR-0023 — Kavram başına tek sahip: medya çekirdeği ↔ medya motoru

**Durum:** ÖNERİLDİ · **imza bekliyor** (Metin — çekirdek · Ahmet — motor)
**Tarih:** 2026-08-21 · **Yazan:** ortak çatı denetimi
**İlgili:** ADR-0004 (saf çekirdek), ADR-0009 (türevler File açmaz), ADR-0016
(politika veridir), ADR-0022 (kota — karar bekliyor)

---

## Bağlam

İki ekip aynı `tradehub_core/media/` ağacında paralel çalıştı:

- **Çekirdek** (Metin, 3–20 Ağu): `File` üstünde yaşam döngüsü, çöp/arşiv,
  sahiplik, yedek, denetim, AV, kota, kullanım eşleme, dedup, tarih standardı —
  9 Linear işi Done (TUR-123/124/125/131/136/138/139/140/296/298).
- **Motor** (Ahmet, 20 Ağu): `media/pipeline/` — türev, sürüm, politika, HLS,
  depolama katmanı, 16 DocType; **bayrak arkasında, varsayılan kapalı**.

Motor çekirdeği **yeniden yazmadı, üstüne koydu** — 14 çekirdek modülünü
import ediyor, yaşam döngüsünü ayna alıyor (`pipeline/core/state.py`:
"GEÇERSİZ KILMAZ, üstüne koyar"), sahipliği `ownership.store_of`'tan okuyor,
denetimi `audit.py`'ye yazıyor. Yine de 21 Ağu denetiminde **dört ayrışma**
ölçüldü — hiçbiri kötü niyet değil, hepsi "bu kavramın sahibi kim" sorusunun
yazılı cevabı olmamasından:

| # | Ayrışma | Kanıt |
|:-:|---|---|
| 1 | Yükleme sözleşmesi (`.png` adlı JPEG kabul) kodda tersine döndü, md değişmedi | `content_gate.py` vs `MEDYA-YUKLEME-SOZLESMESI.md` §3 (düzeltildi 21 Ağu) |
| 2 | Motor API'si tarihi epoch float verdi, standart ISO+kayma | `pipeline/api/crop.py:455`, `delivery.py:368` (düzeltildi 21 Ağu) |
| 3 | Türevler kotaya girmiyor; K7 "girsin" diyor | ADR-0022 (karar bekliyor) |
| 4 | Çöp süpürücü `legal_hold` bilmiyordu; motor zarfla çağrıyı reddediyordu | `trash.purge_expired` (düzeltildi 21 Ağu: `legal_hold_reason`) |

Bayrak açıldığı gün ikinci bir soru dalgası doğacak: durum iki tabloda
(`File.th_media_state` / `Media Asset.state`), yedek yalnız `File` taşıyor,
metadata'nın (alt/lisans) evi belirsiz.

## Seçenekler

| # | Seçenek | Bedel |
|---|---|---|
| A | Hiçbir şey yazma; "ekle, değiştirme" görgü kuralına güven | 21 Ağu'ya kadar böyleydi; 4 ayrışma üretti |
| **B (SEÇİLEN)** | **Kavram başına tek sahip tablosu** + sözleşme değişikliği md ile aynı PR'da + sözleşmeler test olarak | Tek sayfa belge, bir betik, bir test dosyası. Hiçbir modül taşınmaz, hiçbir davranış değişmez |
| C | Motoru ayrı app'e böl, sınır paket sınırı olsun | ADR-0003 bunu zaten reddetti; sorun paket değil, sahiplik |

## Karar

### 1. Kavram başına tek sahip

| Kavram | Tek kaynak | Diğeri ne yapar |
|---|---|---|
| **Yaşam döngüsü** (Active/Archived/Trashed/Deleted) | Çekirdek — `File.th_media_state`, `media/states.py` | Motor **ayna alır, yazmaz** (`pipeline/core/state.py`, testle kilitli) |
| **Alım hattı** (received → accepted → master → renditions ready) | Motor — `Media Asset.state` (ingest ekseni) | Çekirdek bilmez, bilmesi gerekmez |
| **Sahiplik** (hangi mağaza) | Çekirdek — `ownership.owners_of` (küme; ortak sahiplik) | Motor `owner_seller` = ilk yükleyen, **yalnız gösterim**; karar `ownership`'ten |
| **İçerik kimliği** | Çekirdek — `naming.py` (sha256+shard), `File.content_hash` | Motor `content_sha256` aynı değer; `perceptual_hash` yalnız motorda (benzerlik) |
| **Tarih biçimi** (API çıktısı) | Çekirdek — `MEDYA-TARIH-STANDARDI.md` (ISO 8601 + kayma) | Motor saf çekirdekte `envelope.iso_time` (stdlib) ile aynı biçim; iç saklama epoch kalabilir |
| **Denetim** | Çekirdek — `audit.py` → ADL | Motor yeni olay tipi **ekler**, ayrı tablo açmaz |
| **Yükleme kabul kuralı** | Çekirdek sözleşmesi (`MEDYA-YUKLEME-SOZLESMESI.md`) | Motor derin denetimi (`content_gate`) **uygular**; davranış değişirse md aynı PR'da |
| **Türev / sürüm / politika / teslimat** | Motor — `Media Rendition/Version/Policy`, `delivery/*` | Çekirdek türev üretmez (ADR-0009) |
| **Yasal tutma** | Motor — `Media Asset.legal_hold` | Çekirdek süpürücüleri **okur** (`trash.legal_hold_reason`); tutulan silinmez |
| **Kota** | Çekirdek sayacı (TUR-139) + motor türev baytları | **ADR-0022 D** — iki sayaç, tek toplam (karar bekliyor) |
| **Yedek** | Çekirdek — `backup.py` (dosya + kayıt) | Bayrak açılmadan önce `Media Asset/Version/Rendition` **kapsama girer**; motorun S3 aynası dosyayı kopyalar, kaydı değil |
| **Metadata evi** (alt/caption/lisans/SEO) | **Bayrak öncesi karar** — bugün `File.th_media_*` (5.873 kayıt, canlı); motor tabloları dolunca taşıma (`MEDYA-SEO-SOZLESMESI.md` §9 "Yol A/B") | |

### 2. Sözleşme değişikliği md ile aynı PR'da

`tradehub_core/media/` altında davranış değişiyorsa, o davranışı yazan
`docs/MEDYA-*.md` (ya da bir ADR) aynı PR'da değişir. Bilerek değişmiyorsa
commit mesajı `[contract-ok]` taşır. Mekanizma:
`scripts/check_media_contract_docs.py` — pre-commit (uyarı) + CI
(`continue-on-error`). **Bu ADR imzalanınca `--strict`e çevrilir.**

### 3. Sözleşmeler test olarak yaşar

`tests/test_media_contracts.py`: tarih biçimi, tür uyuşmazlığı (varsayılan
ret / `warn` slot bayrağı / tehlikeli her zaman ret), yasal tutma. Motor
tarafında `pipeline/core/state.py` aynası zaten testli. Yeni sözleşme → yeni
test; kim bozarsa CI söyler.

### 4. Ayrışmayı politika yap, kod değil (ADR-0016'nın uygulaması)

Zararsız tür uyuşmazlığı `accept.type_mismatch: reject|warn` ile slot
politikasına taşındı (`slot-policy.schema.json`, varsayılan `reject`). İki
tarafın gerekçesi de yaşıyor: güvenlik varsayılanda, esneklik veride.

## Bayrak açılmadan önce (zorunlu ön koşul)

`Media Engine Settings.media_pipeline_enabled` şunlar bitmeden açılmaz:

1. **ADR-0022** kota kararı (D önerildi)
2. **Yedek kapsamı** — `backup.py` + yapı künyesi motor tablolarını taşır
3. **Metadata evi** kararı — Yol A/B

Gerekçe: üçü de "iki sistem birbirini görmüyor" sınıfı; bayrak kapalıyken
görünmez, açılınca veri kaybı (yedek) ya da yanlış sayım (kota) olarak çıkar.

## Sonuçlar

- Hiçbir Done iş geri açılmaz; kabul kriterleri daralmaz (tek kod değişikliği
  çekirdek tarafında: `trash.legal_hold_reason`, genişletme).
- Motorun davranışı değişmez: tarih çıkışı biçim değişikliği (tüketen yok),
  AV kapısı (`access_level`), test fixture'ları (ClamAV'li makine), hepsi ekleme.
- İki ekip aynı ağaçta çalışmaya devam eder; sınır dizin değil, **tablo**.

## Kanıt

21 Ağu ortak çatı denetimi: `git diff 62b052a..HEAD -- tradehub_core/media`
(motorun çekirdeğe eklediği satırlar), `pipeline_bridge.py` import listesi
(14 çekirdek modülü), `pipeline/core/state.py` başlığı, korpus ölçümü
(tür uyuşmazlığı: 0 dosya / 5.594), test koşumları (çekirdek 13 paket yeşil,
motor `access_level` 15/15 ve `dedup_endpoint` 11/11 — fixture düzeltmesi
sonrası).

## Geri dönüş yolu

**İmza bekliyor.** Sahiplik değişikliği sözleşme testini veya import yönünü
kırarsa bayrak açılmaz ve son tek-sahip haritasına dönülür. Bir kavramı iki
pakette tekrar sahiplenmek ancak bağımsız deployment ihtiyacı ve açık API
sınırı ölçülürse yeniden değerlendirilir.
