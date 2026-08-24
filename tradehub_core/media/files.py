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
import re
import shutil

import frappe

from tradehub_core.media import audit, ownership, quota_model, trash
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


# ── Orijinal içerik hash'i (W7 — rapor 64 EK-2) ─────────────────────────

#: Slot beyan edilmeden yapılan kütüphane yüklemelerinin `Media Asset.slot_key`
#: değeri. `slot_key` şemada zorunlu ve boş olamaz; bu değer KASITLI olarak
#: `pipeline_flags.KNOWN_SLOT_KEYS` DIŞINDA — boru hattı bu varlıkları hiçbir
#: slot süzgecinde görmez, türev üretimi ve idempotency sorguları etkilenmez.
LIBRARY_UPLOAD_SLOT: str = "library.upload"

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def record_original_hash(doc, store: str, original_sha256: str, slot: str = "") -> str | None:
	"""Dönüştürülen yüklemenin ORİJİNAL baytlarının sha256'sını kalıcılaştır.

	Sorun (rapor 64 EK-2): `api/seller_media._kaydet` PNG/JPEG'i `File.insert`ten
	ÖNCE WebP'ye çeviriyor; istemcinin elindeki dosyanın hash'i hiçbir kayda
	yazılmıyordu ve tekilleştirme araması (`inventory.find_by_sha256`) bu
	içerikleri hiçbir katmanda bulamıyordu.

	NEREYE YAZILIYOR — `Media Asset.original_sha256` (custom field, patch
	`v15_9_34_media_asset_original_sha256`). Gerekçe:

	  * Şartnamenin ham-yükleme künyesi `Media Source`tur ama o DocType bu
	    app'te BİLİNÇLİ olarak kurulu değil (doctype_specs/_index.json:
	    "Media Source DocType'ı bu app'te KURULU DEĞİL" — `has_alpha` da aynı
	    gerekçeyle Media Version'a taşınmıştı). Tek alan için DocType kurmak
	    o kararı devirmek olurdu.
	  * `tabFile`'a custom field bilinçli İSTENMEDİ (görev sınırı) — File her
	    yüklemede açılan genel bir kayıt, medya-özel alanlar zaten şişmiş durumda.
	  * Kurulu medya DocType'ları içinde (owner_seller, içerik, kaynak File)
	    üçlüsünü taşıyan TEK kayıt `Media Asset`; kiracı kemeri (`owner_seller`)
	    ve `source_file` bağı orada hazır, `state="draft"` tam bu "yüklendi ama
	    işlenmedi" durumu için tanımlı (media_asset.py `_derive_asset_key`
	    yorumu). `Media Version` işleme ANI kaydıdır ve `asset` zorunludur —
	    yükleme anında var olamaz.

	Best-effort ÇAĞRILMALI: bu kayıt düşerse yükleme DÜŞMEMELİ (çağıran sarar).
	Patch koşmamışsa (kolon yok) sessizce atlanır — dedup uyarısı eksik kalır,
	yükleme kalmaz.

	Dönüş: yazılan/güncellenen `Media Asset` adı, ya da atlandıysa `None`.
	"""
	if not frappe.db.has_column("Media Asset", "original_sha256"):
		return None

	h = (original_sha256 or "").strip().lower()
	if not _SHA256_HEX.match(h) or not store:
		return None

	# Saklanan içeriğin kimliği (sha256[:32]) — `Media Asset.content_sha256`
	# sözleşmesiyle birebir; ad içerik-adresliyse dosya yeniden OKUNMAZ.
	from tradehub_core.media import pipeline_bridge

	kisa = pipeline_bridge.content_fingerprint(doc)
	if not kisa:
		return None

	slot_key = (slot or "").strip().lower() or LIBRARY_UPLOAD_SLOT
	filtre = {"owner_seller": store, "slot_key": slot_key, "content_sha256": kisa}
	# Sistem sorgusu: satıcı oturumunun Media Asset okuma izni yok; kiracı
	# kemeri filtrenin kendisinde (`owner_seller = store`).
	mevcut = frappe.db.get_value("Media Asset", filtre, "name")
	if mevcut:
		frappe.db.set_value("Media Asset", mevcut, "original_sha256", h, update_modified=False)
		frappe.db.commit()
		return mevcut

	varlik = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"slot_key": slot_key,
			"media_type": "image",
			"state": "draft",
			"owner_seller": store,
			"source_file": doc.name,
			"content_sha256": kisa,
			"original_sha256": h,
		}
	)
	try:
		# Sistem kaydı: yükleme akışının yan ürünü; sahiplik yukarıda oturumdan
		# çözülmüş `store` ile yazılıyor, kullanıcı girdisiyle değil.
		varlik.insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		# Yarış: `asset_key` unique — kazananın kaydına alan yazılır (INV-06 deseni).
		mevcut = frappe.db.get_value("Media Asset", filtre, "name")
		if mevcut:
			frappe.db.set_value("Media Asset", mevcut, "original_sha256", h, update_modified=False)
		frappe.db.commit()
		return mevcut
	frappe.db.commit()
	return varlik.name


def storage_usage(store: str, *, include_activity: bool = False) -> dict:
	"""Mağazanın gerçek depolama kullanımı — orijinaller + türevler.

	Sayım tekilleştirilmiş: aynı dosyaya birden çok kayıt düşebiliyor, satır
	toplamak kullanımı olduğundan büyük gösterirdi (yönetim panelinde ölçüldü:
	1,06 GB yerine 1,49 GB).

	`bytes` iki kalemin TOPLAMIDIR (ADR-0022, rapor 105-D2):
	  - **orijinaller** (`original_bytes`): satıcının yüklediği `File` kayıtları
	    (`is_private=0`, `/files/`), `file_url` bazında tekilleştirilmiş.
	  - **türevler** (`rendition_bytes`): sistemin ürettiği küçültülmüş kopyalar
	    (`Media Rendition`). Türev AYRI bir `File` kaydı AÇMAZ (içerik-adresli,
	    `dedup.rendition_path`) — bu yüzden orijinaller sorgusunda hiç görünmez
	    ve ölçülene kadar kotaya girmiyordu. Gerçek disk kullanımı ikisinin
	    toplamıdır; ADR-0022 ile türevler de satıcının kotasına sayılır.

	İki kalem ayrı alanlarda da dönülür ki ekran/rapor dökümü gösterebilsin;
	`bytes` geriye dönük olarak toplamı taşımayı sürdürür (enforcement ve FE
	göstergesi aynı alanı okuyor). Kota durumu da burada üretilir: plan limiti
	mağaza argümanından çözülür; yüzde 80 uyarı, yüzde 100 tükenme sınırıdır.

	``include_activity`` yalnız satıcı özet/rapor ucunda açılır. Her File
	yüklemesindeki kota kapısı aylık iş hacmi sorgusunu gereksiz yere çalıştırmaz.
	"""
	kullanicilar = ownership.users_of(store)
	orijinal_bytes = 0
	dosya_sayisi = 0
	if kullanicilar:
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
		orijinal_bytes = int(row[0] or 0)
		dosya_sayisi = int(row[1] or 0)

	# Türev baytları store'a (Media Asset.owner_seller) bağlı; File.owner'a
	# DEĞİL. Bu yüzden `users_of` boş olsa bile (mağazanın hiç kullanıcısı
	# çözülemese) türevleri ayrıca say — orijinaller sıfır, türevler var olabilir.
	turev = rendition_stats(store)
	toplam = orijinal_bytes + turev["bytes"]
	kota_modu, kota_bayt = _quota_config(store)

	sonuc = {
		"bytes": toplam,
		"original_bytes": orijinal_bytes,
		"rendition_bytes": turev["bytes"],
		"files": dosya_sayisi,
		"renditions": turev["count"],
		"quota_bytes": kota_bayt,
		**quota_model.summarize(toplam, kota_bayt, kota_modu),
		"scope": {
			"public_originals": True,
			"private_originals": False,
			"renditions": True,
		},
	}
	if include_activity:
		sonuc.update(monthly_processing_usage(store))
	return sonuc


def rendition_stats(store: str) -> dict[str, int]:
	"""Tenant'ın türev bayt ve mantıksal rendition adedi — tek agregat."""
	if not store:
		return {"bytes": 0, "count": 0}

	from frappe.query_builder import DocType
	from frappe.query_builder.functions import Coalesce, Count, Sum

	Rendition = DocType("Media Rendition")
	Asset = DocType("Media Asset")
	q = (
		frappe.qb.from_(Rendition)
		.inner_join(Asset)
		.on(Rendition.asset == Asset.name)
		.where(Asset.owner_seller == store)
		.select(Coalesce(Sum(Rendition.bytes), 0), Count(Rendition.name))
	)
	row = q.run()[0]
	return {"bytes": int(row[0] or 0), "count": int(row[1] or 0)}


def rendition_usage(store: str) -> int:
	"""Satıcının türev (`Media Rendition`) baytları — TEK toplu sorgu.

	Türevler orijinaller gibi `File` kaydı açmaz; asset zinciriyle mağazaya
	bağlanır: `Media Rendition.asset` → `Media Asset.owner_seller = store`.
	`SUM(bytes)` tek `frappe.qb` agregatıyla toplanır — satır başına sorgu (N+1)
	YOK.

	Kiracı kemeri: YALNIZ bu mağazanın varlıklarının türevleri
	(`owner_seller == store`). Filtre gevşetilirse başka satıcının türevleri bu
	satıcının kotasını şişirir — `test_media_quota` tenant senaryosu tam olarak
	bunu kırmızıya düşürüp doğruluyor.
	"""
	return rendition_stats(store)["bytes"]


def monthly_processing_usage(store: str) -> dict:
	"""Bu takvim ayındaki tenant medya işi adedi ve toplam çalışma süresi.

	Bu metrik raporlamadır; ticari plan değerleri kararlaştırılmadığı için kota
	kapısına girmez. İş → Asset → ``owner_seller`` zinciri kiracı izolasyonunu
	DB sorgusunun içinde uygular.
	"""
	from frappe.query_builder import DocType
	from frappe.query_builder.functions import Coalesce, Count, Sum
	from frappe.utils import get_first_day, nowdate

	period_start = str(get_first_day(nowdate()))
	if not store:
		return {
			"processing_period_start": period_start,
			"processing_jobs_month": 0,
			"processing_duration_ms_month": 0,
		}

	Job = DocType("Media Processing Job")
	Asset = DocType("Media Asset")
	q = (
		frappe.qb.from_(Job)
		.inner_join(Asset)
		.on(Job.asset == Asset.name)
		.where((Asset.owner_seller == store) & (Job.creation >= period_start))
		.select(Count(Job.name), Coalesce(Sum(Job.duration_ms), 0))
	)
	row = q.run()[0]
	return {
		"processing_period_start": period_start,
		"processing_jobs_month": int(row[0] or 0),
		"processing_duration_ms_month": int(row[1] or 0),
	}


def enforce_storage_quota(store: str, incoming_bytes: int) -> dict:
	"""Yazma öncesi kota kapısı; güncel kullanım özetini de döndürür.

	``File.before_insert`` güvenlik ağı olarak kalır. Satıcı medya uçları bu
	fonksiyonu ``File.insert``ten önce çağırarak kotası yetersiz dosyayı diske
	yazmadan reddeder.
	"""
	usage = storage_usage(store)
	if quota_model.would_exceed(
		usage["bytes"], incoming_bytes, usage.get("quota_bytes")
	):
		from tradehub_core.media import upload_policy

		kalan_mb = round(int(usage.get("remaining_bytes") or 0) / quota_model.MIB, 1)
		gerekli_mb = round(max(0, int(incoming_bytes or 0)) / quota_model.MIB, 1)
		upload_policy.reddet(
			upload_policy.QUOTA_EXCEEDED,
			frappe._(
				"Depolama kotanızda bu yükleme için yeterli alan yok. "
				"Kalan: {0} MB, gerekli: {1} MB."
			).format(kalan_mb, gerekli_mb),
		)
	return usage


def _quota_config(store: str = "") -> tuple[str, int | None]:
	"""Mağazanın plan değerini saf kota modelinin mod/bayt çiftine çevir."""
	from tradehub_core.entitlement.core import get_quota_limits

	tenant = (store or get_current_seller_profile() or "").strip()
	if not tenant:
		return quota_model.MODE_UNCONFIGURED, None
	return quota_model.resolve_limit_mb(
		get_quota_limits(tenant).get("quota.max_storage_mb")
	)


def _quota(store: str = "") -> int | None:
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

	``store`` verildiğinde limit o tenant için çözülür; önceki uygulama argümanı
	yok sayıp oturum mağazasını okuyordu. Admin raporu veya sistem işi başka bir
	tenant'ı ölçerken kullanım ile limitin farklı mağazalardan gelmesi böylece
	engellenir.
	"""
	return _quota_config(store)[1]
