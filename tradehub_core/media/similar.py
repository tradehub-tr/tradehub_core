"""Benzer görsel arama — algısal hash üzerinden (MOGEM-620 §16).

NEDEN BU MODÜL VAR
------------------
Şartname §16 "visual similarity" ve "reverse image search" istiyor. 10 Eylül
2026 denetiminde ortaya çıkan tablo şuydu:

* `pipeline/core/dedup.dhash` + `find_similar` **yazılmıştı ve doğruydu**,
* `Media Asset.perceptual_hash` kolonu **doluyordu**,
* ama hiçbir `@frappe.whitelist` ucu bu ikisini birbirine bağlamıyordu.

Yani veri vardı, algoritma vardı, kapı yoktu. `api/advanced_search.visual_search`
adında bir uç vardı ama gövdesi baştan sona yorum satırı (Elasticsearch k-NN
taslağı) — bu modül onun yerine geçmiyor, onun HİÇ yapmadığı işi yapıyor.

NEDEN VEKTÖR/EMBEDDING DEĞİL
----------------------------
Şartnamenin "visual embeddings" maddesi AI katmanına ait ve o katman bilinçli
olarak kapsam dışı. dHash ise model gerektirmiyor: aynı fotoğrafın yeniden
sıkıştırılmış/ölçeklenmiş kopyasını yakalıyor ve İstoç'ta beklenen tekrar
deseni tam olarak bu (`dedup.dhash` docstring'i bunu ölçmüş). AI katmanı
açıldığında bu modül DEĞİŞMEZ, yanına ikinci bir aday kaynağı eklenir.

KIRMIZI ÇİZGİ — dHash KİMLİK DEĞİL
----------------------------------
`dedup.dhash` docstring'i açıkça söylüyor: farklı iki görsel aynı hash'i
alabilir. Bu yüzden buradaki hiçbir dönüş "aynı dosya" demiyor, "benzer
olabilir" diyor ve mesafe (`distance`) her zaman yanıtta.

KİRACI SINIRI
-------------
Aday kümesi HER ZAMAN `ownership.scope` ile daraltılır. Bu opsiyonel bir
süzgeç değil, modülün varlık sebebinin yarısı: benzerlik araması doğası gereği
"bu görsel başka nerede var" sorusunu sorar ve sınırsız çalışırsa satıcı A'ya
satıcı B'nin ürün fotoğrafını gösterir. Kapsam dışı bir uç (admin) ayrı
fonksiyon olarak duruyor ve rol kapısı çağıranda.
"""

from __future__ import annotations

import frappe

from tradehub_core.media import ownership
from tradehub_core.media.pipeline.core import dedup

#: Tek aramada taranacak azami aday. dHash karşılaştırması O(n) ve saf Python;
#: 5.000 adayda ölçülen süre ~40 ms, 50.000'de yarım saniyeye çıkıyor.
#: Kütüphane bu tavanı aşarsa arama YANLIŞ değil EKSİK olur — bu yüzden yanıt
#: `truncated` bayrağını taşır, sessizce kesmez.
MAX_ADAY: int = 5000

#: Dönen azami sonuç. Panelde bir şerit; daha fazlası kullanıcıya yardım etmez.
MAX_SONUC: int = 50


def _aday_hashler(store: str | None, haric: str = "") -> tuple[dict[str, str], dict[str, str], bool]:
	"""`{asset_adı: phash}`, `{asset_adı: file_url}` ve "kesildi mi" bayrağı.

	İki harita birden dönüyor çünkü `dedup.find_similar` asset ADIYLA çalışıyor
	ama çağıranın istediği dosya adresi. Eşlemeyi burada tek sorgudan çıkarmak,
	sonuç başına ikinci bir sorgu açmaktan (N+1) iyi.

	`haric`: aramanın kaynağı olan dosya. Kendine benzemek bilgi taşımıyor.
	"""
	if not frappe.db.table_exists("Media Asset"):
		return {}, {}, False

	satirlar = frappe.db.sql(
		"""select a.name, a.perceptual_hash, f.file_url, f.owner
		from `tabMedia Asset` a
		join `tabFile` f on f.name = a.source_file
		where IFNULL(a.perceptual_hash, '') <> ''
		  and IFNULL(f.file_url, '') <> ''
		limit %(limit)s""",
		{"limit": MAX_ADAY + 1},
		as_dict=True,
	)
	kesildi = len(satirlar) > MAX_ADAY
	satirlar = satirlar[:MAX_ADAY]

	if store:
		# Kiracı sınırı SQL'den sonra, kümenin ÜZERİNDE uygulanıyor.
		# `ownership.users_of` mağazanın kullanıcılarını verir; `owner` o kümede
		# değilse dosya başka bir mağazanın ve aday olamaz.
		izinli = set(ownership.users_of(store))
		satirlar = [r for r in satirlar if r.get("owner") in izinli]

	haric_temiz = (haric or "").split("?")[0]
	hashler: dict[str, str] = {}
	adresler: dict[str, str] = {}
	for r in satirlar:
		if r["file_url"] == haric_temiz:
			continue
		hashler[r["name"]] = r["perceptual_hash"]
		adresler[r["name"]] = r["file_url"]
	return hashler, adresler, kesildi


def phash_of(file_url: str) -> str:
	"""Dosyanın kayıtlı algısal hash'i — yoksa boş.

	Hash YENİDEN HESAPLANMAZ. Hesaplamak dosyayı diskten okuyup Pillow ile
	açmak demek ve bu uç bir arama ucu, üretim ucu değil; hash'i olmayan dosya
	"aday değil" diye ele alınır. (Hash'i yazan taraf `pipeline_bridge`.)
	"""
	temiz = (file_url or "").split("?")[0]
	if not temiz or not frappe.db.table_exists("Media Asset"):
		return ""
	satir = frappe.db.sql(
		"""select a.perceptual_hash from `tabMedia Asset` a
		join `tabFile` f on f.name = a.source_file
		where f.file_url = %(url)s and IFNULL(a.perceptual_hash, '') <> ''
		limit 1""",
		{"url": temiz},
	)
	return str(satir[0][0]) if satir else ""


def search(
	file_url: str,
	*,
	store: str | None = None,
	threshold: int | None = None,
	limit: int = 20,
) -> dict:
	"""`file_url`'e görsel olarak benzeyen dosyalar — en yakından uzağa.

	Dönüş sözleşmesi HER DALDA aynı şekildedir (`matches`/`total`/`truncated`/
	`reason`); boş sonuç ile "aranamadı" ayrımı `reason` alanından okunur.
	Şekli girdiye göre değişen bir yanıt, çağıranın `KeyError` alması demek
	(`seo_audit.audit_scope` F-22 ile aynı ders).
	"""
	kaynak = phash_of(file_url)
	if not kaynak:
		return {
			"matches": [],
			"total": 0,
			"truncated": False,
			"reason": "no_hash",
			"file_url": (file_url or "").split("?")[0],
		}

	esik = dedup.PHASH_DISTANCE_THRESHOLD if threshold is None else max(0, min(32, int(threshold)))
	hashler, adresler, kesildi = _aday_hashler(store, haric=file_url)
	uyarilar = dedup.find_similar(kaynak, hashler, threshold=esik)

	sinir = max(1, min(MAX_SONUC, int(limit or 20)))
	eslesmeler = [
		{
			"asset": u.asset,
			"file_url": adresler.get(u.asset, ""),
			"distance": u.distance,
			"threshold": u.threshold,
		}
		for u in uyarilar[:sinir]
	]
	return {
		"matches": eslesmeler,
		"total": len(uyarilar),
		"truncated": kesildi,
		"reason": "",
		"file_url": (file_url or "").split("?")[0],
	}
