"""Satıcının dosya üzerindeki işlemleri — adlandırma, kopyalama, değiştirme, kota.

Bu üç işlem ekranda vardı ama hiçbiri kalıcı değildi. Gerçeğe bağlarken üç
tehlike ayrı ayrı ele alındı:

**Yeniden adlandırma dosyanın YOLUNU değiştirmez.** Yol (`file_url`) ürünlerde,
vitrinde, sipariş kayıtlarında ve arama motorunun indeksinde geçiyor.
Değiştirmek görünen her yerde kırık görsel bırakırdı. Değişen yalnız görünen
ad. Kullanıcı için fark yok: listede gördüğü ad değişiyor.

**Kopyalama gerçek bir kopya üretir.** Aynı yolu gösteren ikinci bir kayıt
açmak "kopya" olmazdı — biri düzenlenince ikisi birden değişirdi.

**Değiştirme paylaşılan dosyada REDDEDİLİR.** Aynı görseli başka bir mağaza da
kullanıyorsa, içeriği değiştirmek onun ürününde bambaşka bir görsel çıkarırdı.
Sessizce yapmak yerine açıkça reddedilip yeni dosya yüklemesi öneriliyor —
"her mağazanın görseli kendisinindir" kuralının doğal sonucu.
"""

from __future__ import annotations

import os
import shutil

import frappe

from tradehub_core.media import audit, ownership, trash
from tradehub_core.utils.tenant import get_current_seller_profile

# `File.file_name` sütununun sınırı. Ad kırpması bu değere UZANTI DAHİL
# uyar; aksi hâlde veritabanı ham "Data too long" hatası veriyor ve kullanıcı
# sebebini göremiyor.
MAX_NAME: int = 140

# Dosya sisteminin ad sınırı (çoğu Linux dosya sisteminde 255 BAYT). Türkçe
# harfler 2 bayt olduğu için karakter sayısı bunun yarısına kadar inebilir;
# güvenli tarafta kalmak için 120 karakter kabul ediliyor.
MAX_FS_NAME: int = 120


def _unique_path(govde: str, uzanti: str) -> tuple[str, str]:
	"""Çakışmayan bir dosya adı ve tam yolu üret.

	Ad zaten varsa sayı eklenir. Rastgele bir son ek de kullanılabilirdi ama
	kullanıcı listede "-kopya", "-kopya-2" görmeyi bekler; anlamsız bir karakter
	dizisi hangi kopyanın hangisi olduğunu gizlerdi.

	Ad UZUNLUK SINIRINA göre kısaltılır. Kopyanın kopyası alındıkça "-kopya"
	eki üst üste biniyor ve ad sınırsız büyüyordu; yeterince tekrarlanınca
	dosya sistemi "File name too long" hatası veriyor, kullanıcı da sebebini
	göremiyordu. Maymun testi bunu yakaladı.
	"""
	dizin = os.path.dirname(trash._live_path("/files/x"))

	def _kis(g: str, ek: str) -> str:
		# Sınır hem veritabanı sütunu hem dosya sistemi için geçerli olmalı;
		# küçük olan bağlar.
		yer = min(MAX_NAME, MAX_FS_NAME) - len(ek) - len(uzanti)
		return f"{g[:max(1, yer)]}{ek}{uzanti}"

	aday = _kis(govde, "-kopya")
	n = 2
	while os.path.exists(os.path.join(dizin, aday)):
		aday = _kis(govde, f"-kopya-{n}")
		n += 1
		if n > 999:
			frappe.throw(frappe._("Çok fazla kopya var, önce bazılarını silin."))
	return aday, os.path.join(dizin, aday)


def rename(file_url: str, store: str, new_name: str) -> dict:
	"""Görünen adı değiştir — dosyanın yolu KORUNUR."""
	ownership.assert_owns(store, file_url)

	temiz = (new_name or "").strip()
	if not temiz:
		frappe.throw(frappe._("Dosya adı boş olamaz."))
	if any(k in temiz for k in ("/", "\\", "\0")):
		frappe.throw(frappe._("Dosya adında yol karakteri kullanılamaz."))

	# Uzantı korunuyor: kullanıcı uzantıyı silerse dosya türü kaybolmuş gibi
	# görünür, önizleme ve süzgeçler yanlış çalışır.
	mevcut = frappe.db.get_value("File", {"file_url": file_url}, "file_name") or ""
	uzanti = os.path.splitext(mevcut)[1]

	# Kırpma UZANTI DAHİL yapılıyor. Önce 140'a kırpıp sonra uzantı
	# eklendiğinde toplam sınırı aşıyor ve veritabanı ham bir hata
	# döndürüyordu ("Data too long"); kullanıcı sebebini göremiyordu.
	# Sınır testi bunu yakaladı.
	govde = temiz[: MAX_NAME - len(uzanti)] if uzanti else temiz[:MAX_NAME]
	if uzanti and not temiz.lower().endswith(uzanti.lower()):
		temiz = f"{os.path.splitext(govde)[0] or govde}{uzanti}"
	else:
		temiz = govde
	temiz = temiz[:MAX_NAME]

	kullanicilar = ownership.users_of(store)
	kayitlar = frappe.get_all(
		"File",
		filters={"file_url": file_url, "owner": ["in", list(kullanicilar)]},
		pluck="name",
	)
	frappe.db.set_value(
		"File", {"name": ["in", kayitlar]}, {"file_name": temiz}, update_modified=False
	)
	frappe.db.commit()
	return {"file_url": file_url, "file_name": temiz}


def duplicate(file_url: str, store: str) -> dict:
	"""Dosyanın gerçek bir kopyasını üret.

	Kopya bağımsız: kaynağı silinse de yaşar, üstverisi ayrı yazılır. Kopyanın
	hiçbir üründe kullanımı yoktur — kullanım bağı kopyalanmaz, çünkü ürün
	hangi kopyayı göstereceğini bilemez.
	"""
	ownership.assert_owns(store, file_url)

	kaynak = trash._live_path(file_url)
	if not os.path.isfile(kaynak):
		frappe.throw(frappe._("Dosya diskte bulunamadı."))

	ad = frappe.db.get_value("File", {"file_url": file_url}, "file_name") or "dosya"
	govde, uzanti = os.path.splitext(ad)

	# Frappe'nin normal yükleme yolu KULLANILAMAZ: aynı içeriği tekrar
	# yazmıyor, mevcut dosyayı gösteren ikinci bir kayıt açıyor (imza eşleşmesi
	# — bkz. inventory.py başlığı). Sonuç "kopya" olmazdı: iki kayıt tek dosyayı
	# gösterir, biri silinince diğeri de kırılırdı.
	#
	# Bu yüzden fiziksel kopya elle yazılıyor ve kayıt doğrudan yeni yola
	# bağlanıyor. İmza kasten aynı bırakılıyor: hassas belgenin public kopyasını
	# yakalayan koruma imza eşleşmesine dayanıyor, bozulmamalı.
	yeni_ad, yeni_yol = _unique_path(govde, uzanti)
	shutil.copy2(kaynak, yeni_yol)

	doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": yeni_ad,
			"file_url": f"/files/{yeni_ad}",
			"is_private": 0,
			"file_size": os.path.getsize(yeni_yol),
			"content_hash": frappe.db.get_value("File", {"file_url": file_url}, "content_hash"),
		}
	)
	doc.flags.ignore_duplicate_entry_error = True
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	audit.log_media_event(
		action=audit.ACTION_UPLOAD,
		file_url=doc.file_url,
		tenant=store,
		context={"source": file_url, "duplicated": True},
	)
	return {"file_url": doc.file_url, "file_name": doc.file_name, "bytes": doc.file_size}


def replace(file_url: str, store: str, content: bytes, file_name: str = "") -> dict:
	"""Dosyanın içeriğini değiştir — yolu ve tüm bağları korunur.

	Paylaşılan dosyada REDDEDİLİR: aynı yolu gösteren başka bir mağaza varsa
	onun ürününde bambaşka bir görsel çıkardı.
	"""
	ownership.assert_owns(store, file_url)

	digerleri = ownership.owners_of(file_url) - {store}
	if digerleri:
		frappe.throw(
			frappe._(
				"Bu görsel başka bir mağazada da kullanılıyor, içeriği değiştirilemez. "
				"Yeni bir dosya yükleyip ürününüzde onu kullanın."
			)
		)

	if not content:
		frappe.throw(frappe._("Dosya içeriği boş."))

	# YENİ içerik de yükleme sözleşmesinden geçer (TUR-123 × TUR-125). Bu satır
	# olmadan replace, upload kapılarının tamamını atlayan bir arka kapıydı:
	# temiz bir .jpg yükleyip içeriğini sonradan HTML/çalıştırılabilir baytlarla
	# değiştirmek mümkündü — magic-byte kontrolü yalnız ilk yüklemede koşuyordu.
	from tradehub_core.media import upload_policy

	upload_policy.check(
		file_name or os.path.basename(file_url), content=content, media_endpoint=True
	)

	hedef = trash._live_path(file_url)
	if not os.path.isfile(hedef):
		frappe.throw(frappe._("Dosya diskte bulunamadı."))

	# Önce yedek, sonra yazma: yazma yarıda kalırsa eski içerik geri konur.
	# Yedeksiz yazmak, hata durumunda ürünün görselini yok ederdi.
	yedek = f"{hedef}.replacing"
	shutil.copy2(hedef, yedek)
	try:
		with open(hedef, "wb") as fh:
			fh.write(content)
		boyut = os.path.getsize(hedef)
		frappe.db.set_value(
			"File",
			{"file_url": file_url},
			{
				"file_size": boyut,
				# Çözünürlük ve optimizasyon geçmişi artık geçersiz.
				"th_media_width": 0,
				"th_media_height": 0,
				"th_optimized_at": None,
				"th_original_size": 0,
			},
			update_modified=False,
		)
		frappe.db.commit()
	except Exception:
		shutil.move(yedek, hedef)
		frappe.log_error(
			title=f"Media replace failed for {file_url}",
			message=frappe.get_traceback(with_context=True),
		)
		raise
	else:
		os.remove(yedek)

	# Eski içeriğin damgaları yeni içeriği AKLAMAZ (TUR-125 × TUR-296). Tarama
	# kuralı `av.rescan_after_write`'ta — üç yazma yolu (replace, platform geri
	# yükleme, satıcı geri yüklemesi) aynı kuralı paylaşsın diye tek yerde.
	from tradehub_core.media import av, transcode

	av.rescan_after_write([file_url], reason="replace")

	# Video durumu da sıfırlanır ki değiştirilen video "hazır" görünmeye devam
	# etmesin. Best-effort: buradaki aksaklık yazılmış içeriği geri almaz.
	try:
		frappe.db.set_value(
			"File", {"file_url": file_url}, {"th_media_video_status": ""},
			update_modified=False,
		)
		frappe.db.commit()
		if upload_policy.kind_of(file_name or file_url) == upload_policy.KIND_VIDEO:
			transcode.enqueue_transcode(file_url)
	except Exception:
		frappe.log_error(
			title=f"Media replace: video yeniden kuyruklanamadi {file_url}",
			message=frappe.get_traceback(with_context=True),
		)

	audit.log_media_event(
		action=audit.ACTION_UPLOAD,
		file_url=file_url,
		tenant=store,
		context={"replaced": True, "bytes": boyut, "file_name": file_name},
	)
	return {"file_url": file_url, "bytes": boyut}


def storage_usage(store: str) -> dict:
	"""Mağazanın gerçek depolama kullanımı.

	Sayım tekilleştirilmiş: aynı dosyaya birden çok kayıt düşebiliyor, satır
	toplamak kullanımı olduğundan büyük gösterirdi (yönetim panelinde ölçüldü:
	1,06 GB yerine 1,49 GB).
	"""
	kullanicilar = ownership.users_of(store)
	if not kullanicilar:
		return {"bytes": 0, "files": 0, "quota_bytes": None}

	yer_tutucu = ", ".join(["%s"] * len(kullanicilar))
	row = frappe.db.sql(
		f"""select coalesce(sum(boyut), 0), count(*) from (
			select max(file_size) boyut from tabFile
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			  and owner in ({yer_tutucu})
			group by file_url
		) x""",  # noqa: S608 — yer tutucular parametreli
		list(kullanicilar),
	)[0]

	return {
		"bytes": int(row[0] or 0),
		"files": int(row[1] or 0),
		"quota_bytes": _quota(),
	}


def _quota() -> int | None:
	"""Oturumdaki mağazanın entitlement kotası (bayt) — tanımsızsa None.

	TUR-139/WP3 öncesi burada tek bir global `Marketplace Settings.
	media_storage_quota_bytes` okunuyordu (tüm satıcılar aynı sınırı görürdü).
	Gerçek kota modeli plan-bazlı: `entitlement.core.get_quota_limits`'ten
	`quota.max_storage_mb` okunur. `-1` (sınırsız) veya tanımsız → None (sınır
	gösterilmez, `entitlement.checks.check_media_storage_quota` da aynı
	semantiği paylaşıyor — bkz. o fonksiyonun docstring'i).

	NOT (metin'e): bu fonksiyon `media/files.py`'nin parçası ama artık
	`entitlement` paketine bağımlı — WP3 enforcement'ının (checks.py) kaynağı
	burasıyla aynı `get_quota_limits` çağrısı.
	"""
	from tradehub_core.entitlement.core import get_quota_limits

	store = get_current_seller_profile()
	if not store:
		return None

	limit_mb = get_quota_limits(store).get("quota.max_storage_mb")
	if limit_mb is None:
		return None
	limit_mb = int(limit_mb)
	if limit_mb == -1:
		return None
	return limit_mb * 1024 * 1024
