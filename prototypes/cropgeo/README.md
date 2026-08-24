# T-010 cropgeo prototipi

Çalışan prototip tek bir algoritmayı iki dilde taşır:

- Python çekirdeği: `tradehub_core/media/pipeline/core/crop.py` ve
  `crop_geometry.py`
- TypeScript ikizi: `crop_geometry.ts`
- Kanonik kabul vektörü: `tests/vectors/crop-vectors.json`

Dosyalar buraya kopyalanıp üçüncü bir uygulama yaratılmaz. Resmi
`prototypes/cropgeo/` çıktı yolu bu haritayı taşır; koşan kaynak production
paketidir. Vektörü üretim fixture'ından senkronlamak ve drift'i denetlemek:

```bash
python scripts/sync_faz1_cropgeo.py
python scripts/sync_faz1_cropgeo.py --check
python -m unittest \
  tradehub_core.tests.test_crop \
  tradehub_core.tests.test_crop_geometry -v
```

Panel ikizi ayrıca `admin-panel/frontend/scripts/sync-crop-geometry.mjs
--check` ve crop parite testleriyle kilitlidir.
