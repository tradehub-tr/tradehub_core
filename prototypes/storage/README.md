# T-018 depolama prototipi

Prototip ayrı ve sürüklenebilecek bir adapter kopyası üretmez; çalışan üretim
sözleşmesini ve uygulamalarını doğrudan kullanır:

- `tradehub_core/media/pipeline/contracts/storage.py`
- `tradehub_core/media/pipeline/storage/{local,s3,mirror,tiered}.py`
- `tradehub_core/media/pipeline/delivery/{cdn,imgproxy,signed}.py`

Sözleşme koşumu:

```bash
python -m unittest tradehub_core.tests.test_storage_adapters -v
python -m unittest tradehub_core.tests.test_storage_adapters_minio -v
python -m unittest tradehub_core.tests.test_cdn_delivery tradehub_core.tests.test_imgproxy_delivery -v
```

MinIO yoksa gerçek-servis paketi açıkça skip olur; sahte istemci sonucu gerçek
S3 ölçümü diye sunulmaz. `s3_enabled=0` varsayılandır ve fabrika local adapter
döndürür.
