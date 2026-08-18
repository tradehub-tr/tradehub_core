"""Medya motorunun saf çekirdeği.

`crop` ve `dedup` modüllerinde `import frappe` YOKTUR: site, bench ve veritabanı
olmadan çalışır ve test edilirler. `usage` frappe'ye ihtiyaç duyar ama onu da
MODÜL DÜZEYİNDE import etmez — böylece paket her ortamda import edilebilir ve
saf mantığı (öksüz kararı, örnekleme) frappe'siz test edilir.
"""
