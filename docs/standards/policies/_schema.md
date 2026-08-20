# Slot policy JSON — alan sözleşmesi

Bu klasördeki her `<slot_key>.json` dosyası **bir** upload slotunun çözünürlük ve
DPI kuralını taşır. Dosya adı `slot_key` ile birebir aynıdır (`00-upload-slot-envanteri.md`
§8'de önerilen `<alan>.<slot>` biçimi).

Kod tabanında bu dosyaları **okuyan bir kod henüz yoktur** — dosyalar T-024'ün
çıktısıdır ve `tests/test_policy_dpi.py` tarafından doğrulanır. Uygulama (L3
katmanı) yazılmadı; bkz. `docs/standards/dpi-ve-cozunurluk.md` §6.

| alan | tip | zorunlu | anlam |
|---|---|---|---|
| `slot_key` | string | ✔ | Kanonik slot anahtarı; dosya adıyla aynı olmalı |
| `doctype_field` | string | ✔ | `<DocType>.<fieldname>` — kaynağı |
| `kind` | `"image"` \| `"video"` \| `"document"` | ✔ | `media/upload_policy.py` KIND_* ile aynı sözlük |
| `is_product_slot` | bool | ✔ | `true` ise ürün ailesi tabanı (`min_long_edge >= 2000`) zorunlu |
| `min_long_edge` | int > 0 | ✔ | Kabul edilen **asgari** uzun kenar (px). Pipeline çıktısı bunun ALTINA inemez |
| `max_long_edge` | int > 0 | ✔ | Uygulanan uzun kenar **tavanı** (px). `>= min_long_edge` |
| `target_long_edge` | int | ✔ | Optimizasyonun hedeflediği uzun kenar; `min <= target <= max` |
| `aspect_ratio` | string \| `"free"` | ✔ | `"1:1"`, `"1.91:1"`, `"4:1"` ya da `"free"` |
| `aspect_tolerance` | float \| null | ✔ | Oranda kabul edilen sapma; `"free"` ise `null` |
| `fit` | `"contain"` \| `"cover"` | ✔ | Render davranışı — `cover` ise kırpma uyarısı gösterilmeli |
| `dpi_policy.output_dpi` | int | ✔ | Her zaman `72` |
| `dpi_policy.strip_input_dpi` | bool | ✔ | Girdi DPI metadata'sı düşürülür mü |
| `dpi_policy.pixels_preserved` | bool | ✔ | **Her zaman `true`** — DPI değişimi piksel silmez |
| `olcum` | object | ✔ | Her sayının nereden geldiği. `render_box_css_px: null` = ölçülemedi |
| `olcum.uretimde_dogrulanmali` | bool | — | `true` ise sayı tarayıcıda doğrulanmadı |
