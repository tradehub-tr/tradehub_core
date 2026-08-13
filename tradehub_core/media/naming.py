"""Yükleme sırasında içerik-adresli dosya adlandırma (TUR-141/130).

Amaç: yeni yüklenen dosyaların adı URL'den tahmin edilemesin
(<sha256(içerik)[:32]>.<ext>). Mevcut file_url'ler korunur; yalnız yeni
yüklemelere uygulanır. WP4 gerçek write_file hook implementasyonunu koyacak.
"""


def write_file_hashed(*args, **kwargs):
	raise NotImplementedError("WP4 dolduracak — Faz 0 stub")
