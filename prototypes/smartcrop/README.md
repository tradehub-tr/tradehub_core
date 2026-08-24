# T-014 smartcrop karşılaştırma prototipi

Üç yöntem production paketinde çalışır:

- `entropy_edge`
- `background_segmentation`
- `onnx_u2netp` (4,36 MiB U²-Net-P)

Canlı Listing görsellerinden kişisel/satıcı kimliği taşımayan 50 dosyalık geçici
set üretmek, modeli almak ve makine ölçümünü koşturmak için:

```bash
docker exec istoc-dev-backend-1 sh -lc 'cd /home/frappe/frappe-bench && \
  bench --site istoc.localhost execute \
  tradehub_core.media.smartcrop_dataset.export_labeling_dataset \
  --kwargs "{\"output_dir\":\"/home/frappe/frappe-bench/apps/tradehub_core/.smartcrop-work\",\"limit\":50}"'
python scripts/fetch_smartcrop_model.py
python scripts/benchmark_smartcrop.py
```

İnsan kapısı: `.smartcrop-work` içinde `python -m http.server 8765` çalıştırıp
`http://localhost:8765/annotate.html` açın. 50 odak + zemin sınıfı tamamlanınca
indirilen `ground-truth.json` ile:

```bash
python scripts/benchmark_smartcrop.py --labels .smartcrop-work/ground-truth.json
```

İnsan etiketi yokken rapor yalnız çalışma süresi/bellek/model boyutu yazar;
hata ve güven eşiğini `null` bırakır.
