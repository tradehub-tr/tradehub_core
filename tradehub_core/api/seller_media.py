"""Satıcının kendi medya kütüphanesi — HTTP yüzeyi.

`media_admin` ile aynı iş mantığını kullanır ama iki temel farkla:

  1. **Yetki rol değil sahiplik.** Yönetim uçları rol istiyor ("System Manager"
     misin?). Burada rol yetmez: giriş yapmış her satıcı kendi kütüphanesini
     görür, ama YALNIZ kendisininkini. Her çağrı oturumdan mağazayı çözer ve
     sorguya o mağazayı geçirir. Mağaza parametre olarak DIŞARIDAN alınmaz —
     alınsaydı satıcı başkasının mağaza kodunu yazıp verisini görebilirdi.

  2. **Silme yıkıcı değil, bırakmadır.** Aynı dosya birden çok mağazaya ait
     olabiliyor; satıcının silmesi diğerinin ürününü kırmamalı. Ayrıntı
     `media/seller_media.py` başlığında.

Bu dosyada iş mantığı YOKTUR: yetki, parametre doğrulama, çağırma. Aynı kural
`media_admin` için de geçerli.
"""

from __future__ import annotations

import frappe

from tradehub_core.media import audit, engine, files, inventory, metadata, ownership, transcode, usage
from tradehub_core.media import seller_media as islem

# Tek istekte işlenebilecek azami dosya — kazara "hepsini" tetiklemeye karşı.
MAX_BATCH: int = 200


def _store() -> str:
	"""Oturumdaki satıcının mağazası.

	Reddi denetime yazar: mağazası olmayan bir oturumun satıcı medya uçlarına
	gelmesi ya yanlış yapılandırma ya da deneme; ikisi de görünür olmalı.
	"""
	try:
		return ownership.current_store()
	except frappe.PermissionError:
		try:
			endpoint = (frappe.form_dict or {}).get("cmd")
		except Exception:
			endpoint = None
		audit.log_media_event(
			action=audit.ACTION_ACCESS_DENIED,
			allowed=False,
			reason="no_store",
			context={"endpoint": endpoint},
		)
		raise


def _urls(file_urls: str | list[str] | None) -> list[str]:
	liste = frappe.parse_json(file_urls) if isinstance(file_urls, str) else (file_urls or [])
	if len(liste) > MAX_BATCH:
		frappe.throw(frappe._("Tek seferde en çok {0} dosya işlenebilir.").format(MAX_BATCH))
	return [u for u in liste if u]


@frappe.whitelist()
def get_my_media(
	page: int = 1,
	page_size: int = 50,
	search: str = "",
	state: str = "",
	sort_by: str = "date",
	sort_dir: str = "desc",
	usage_state: str = "",
) -> dict:
	"""Satıcının kendi dosyaları — sayfalı liste.

	`state`: "" (aktif) | "trashed" (bıraktıkları) | "optimized" | "pending"
	`usage_state`: kendi kapsamındaki kullanım kararı
	"""
	store = _store()
	sonuc = inventory.list_files(
		page=page,
		page_size=page_size,
		search=search,
		state=state,
		sort_by=sort_by,
		sort_dir=sort_dir,
		usage_state=usage_state,
		store=store,
	)

	# Üstveri tek sorguda ekleniyor. Satır başına ayrı çağrı, 200 satırlık bir
	# sayfada 200 gidiş dönüş demekti.
	ustveri = metadata.read_many([i["file_url"] for i in sonuc["items"]], store)
	for i in sonuc["items"]:
		i.update(ustveri.get(i["file_url"]) or {})
	return sonuc


@frappe.whitelist()
def get_my_usage(file_url: str) -> dict:
	"""Bu dosyayı KENDİ hangi ürünlerimde kullanıyorum.

	Başka mağazanın kullanımı yanıtta hiç geçmez — ne ürün adı, ne sayı, ne
	mağaza. Satıcının bilmesi gereken tek şey kendi vitrininin ne olacağı.
	"""
	store = _store()
	ownership.assert_owns(store, file_url)
	return usage.resolve(file_url, store=store)


@frappe.whitelist()
def preview_release(file_urls: str | list[str] | None = None) -> dict:
	"""Bırakmadan önce özet — onay ekranı uyarıyı buna göre kurar.

	Kullanımdaki dosya sayısı ayrı veriliyor ki ekran "3 görsel şu an
	ürünlerinizde kullanılıyor" diyebilsin. Uyarısız toplu silme, satıcının
	kendi vitrinini tek tıkla bozması demek.
	"""
	store = _store()
	urls = _urls(file_urls)
	sahip_olunan = [u for u in urls if ownership.owns(store, u)]
	kararlar = usage.verdicts_for(sahip_olunan, deep=True, store=store)

	sayim: dict[str, int] = {}
	for v in kararlar.values():
		k = v.get("verdict", "unknown")
		sayim[k] = sayim.get(k, 0) + 1

	return {
		"total": len(urls),
		"owned": len(sahip_olunan),
		"by_verdict": sayim,
		"in_use": sayim.get("in_use", 0),
	}


@frappe.whitelist()
def archive_media(file_urls: str | list[str] | None = None) -> dict:
	"""Seçili dosyaları ARŞİVLE — geri alınabilir.

	Diske dokunulmaz, hiçbir kayıt silinmez. Kalıcı silme ayrı uçta
	(`purge_media`) ve yalnız arşivdeki dosyaya uygulanıyor.

	Zorlama seçeneği YOK: kullanımdaki dosyayı arka taraf reddediyor ve bu
	hiçbir parametreyle aşılamıyor — ekrandaki kapalı düğme tek başına koruma
	sayılmaz, konsoldan istek atılabilir.

	Sahibi olmadığı dosya sessizce atlanmaz, `skipped` altında sayılır; ama
	hangi dosya olduğu dönülmez — sahibi olmadığı bir adresin varlığını
	doğrulamak keşif kapısı açar.
	"""
	return _toplu(file_urls, islem.archive, "archived")


@frappe.whitelist()
def unarchive_media(file_urls: str | list[str] | None = None) -> dict:
	"""Arşivden çıkar — dosya aktif listeye döner."""
	return _toplu(file_urls, islem.unarchive, "unarchived")


@frappe.whitelist()
def purge_media(file_urls: str | list[str] | None = None) -> dict:
	"""KALICI SİL — geri alınamaz.

	Satıcının payı tamamen kalkar. Dosya diskten yalnız SON sahip de
	sildiğinde silinir; o ana kadar diğer mağazalar için olduğu gibi durur.

	Yalnız arşivdeki dosyaya uygulanır; arka taraf değilse reddeder.
	"""
	return _toplu(file_urls, islem.purge, "purged")


def _toplu(file_urls, fn, sayac_adi: str) -> dict:
	"""Toplu işlem iskeleti — üç uç da aynı yetki ve hata davranışını paylaşır.

	Tek yerde durması önemli: sahiplik kontrolü ya da hata yutma davranışı
	uçlar arasında ayrışırsa biri diğerinden gevşek kalır.
	"""
	store = _store()
	urls = _urls(file_urls)

	basarili: list[dict] = []
	hatali: list[dict] = []
	atlanan = 0

	for url in urls:
		if not ownership.owns(store, url):
			atlanan += 1
			continue
		try:
			basarili.append(fn(url, store))
		except Exception as e:
			hatali.append({"file_url": url, "error": str(e)})

	return {
		sayac_adi: len(basarili),
		"failed": hatali,
		"skipped": atlanan,
		"details": basarili,
	}


@frappe.whitelist()
def get_my_summary() -> dict:
	"""Üst şerit — dosya adedi, gerçek depolama kullanımı, bırakılan adedi.

	`quota_bytes` yapılandırılmamışsa `null` döner ve ekran sınır göstermez.
	Uydurma bir sınır göstermek, satıcıya var olmayan bir kısıt olduğunu
	düşündürürdü (gerçek kota modeli TUR-139).
	"""
	store = _store()
	aktif = inventory.list_files(page=1, page_size=1, store=store)
	cop = inventory.list_files(page=1, page_size=1, state="trashed", store=store)
	depolama = files.storage_usage(store)
	return {
		"store": store,
		"active": aktif["total"],
		"trashed": cop["total"],
		"bytes": depolama["bytes"],
		"quota_bytes": depolama["quota_bytes"],
		"tags": metadata.all_tags(store),
	}


# Satıcı medya kütüphanesine kabul edilen türler — İZİN listesi.
#
# Sistemde zaten bir YASAK listesi var (`utils.security.reject_unsafe_files`)
# ve çalıştırılabilir/betik dosyalarını engelliyor. Ama ekran "sadece görsel,
# video ve PDF" diyor; yasak listesi bunu karşılamıyor — arada kalan her tür
# (zip, docx, exe olmayan her şey) geçebiliyordu. Ekrandaki kural sunucuda da
# olmalı, yoksa ekranı baypas eden istek onu tanımaz.
#
# Yasak listesi KALDIRILMADI, bu onun ÜSTÜNE biniyor: orası tüm sistemi
# koruyan güvenlik kararı, burası bu kütüphanenin içerik kuralı.
UPLOAD_EXTENSIONS: frozenset[str] = frozenset(
	{
		".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif", ".heic",
		".mp4", ".webm", ".mov", ".m4v",
		".pdf",
	}
)

# Sunucu garanti-WebP (TUR-128) yalnız `engine.to_webp`'in açabildiği raster
# biçimlere uygulanır. GIF kasıtlı DIŞARIDA: `engine.optimize` de animasyonlu
# GIF'i atlıyor (`OptimizeResult(reason="animated")`), aynı davranış burada da
# korunuyor — tek kare WebP'ye çevirmek animasyonu kırar.
IMAGE_TO_WEBP_EXTENSIONS: frozenset[str] = frozenset(
	{".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".avif", ".heic"}
)

VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".webm", ".mov", ".m4v"})

# Tek dosya üst sınırı. Sınır olmaması, tek istekle diski doldurmayı mümkün
# kılardı. Depolama kotası ayrı bir iş (TUR-139); bu yalnız tek dosya kalkanı.
MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024


@frappe.whitelist()
def upload_media(file_name: str = "", content: str = "") -> dict:
	"""Satıcı kütüphanesine dosya yükle.

	Frappe'nin genel yükleme ucu yerine bu uç kullanılıyor, çünkü orada bu
	kütüphanenin tür ve boyut kuralları yok. İçerik base64 gelir; bu kurulumda
	çok parçalı gönderim oturum katmanında CSRF uyuşmazlığı üretiyor.
	"""
	import base64
	import os

	store = _store()

	ad = (file_name or "").strip()
	if not ad:
		frappe.throw(frappe._("Dosya adı zorunlu."))
	if any(k in ad for k in ("/", "\\", "\0")):
		frappe.throw(frappe._("Dosya adında yol karakteri kullanılamaz."))

	uzanti = os.path.splitext(ad)[1].lower()
	if uzanti not in UPLOAD_EXTENSIONS:
		frappe.throw(
			frappe._("Bu dosya türü kabul edilmiyor: {0}. Görsel, video veya PDF yükleyin.").format(
				uzanti or "?"
			)
		)

	if not content:
		frappe.throw(frappe._("Dosya içeriği boş."))
	ham = content.split(",", 1)[-1] if content.startswith("data:") else content
	try:
		icerik = base64.b64decode(ham, validate=True)
	except Exception:
		frappe.throw(frappe._("Dosya içeriği okunamadı."))

	if len(icerik) > MAX_UPLOAD_BYTES:
		frappe.throw(
			frappe._("Dosya çok büyük: en fazla {0} MB.").format(MAX_UPLOAD_BYTES // (1024 * 1024))
		)

	video_mi = uzanti in VIDEO_EXTENSIONS

	# Sunucu garanti-WebP (TUR-128): Safari/iOS/Capacitor `canvas.toBlob(
	# 'image/webp')` desteklemiyor, client bu ortamlarda JPEG/PNG fallback'i
	# gönderir. `.webp` uzantısıyla gelen içerik zaten WebP'yse dokunulmaz —
	# çift sıkıştırma yok.
	if uzanti in IMAGE_TO_WEBP_EXTENSIONS:
		try:
			icerik = engine.to_webp(icerik)
			ad = os.path.splitext(ad)[0] + ".webp"
		except Exception as exc:
			# `to_webp` Pillow'un açamadığı bir biçimle (ör. bazı HEIC varyantları)
			# karşılaşırsa orijinal içerikle devam edilir — yükleme reddedilmez,
			# yalnız Safari-fallback tamamlanmamış olur.
			frappe.log_error(title="upload_media to_webp başarısız", message=f"{ad}: {exc}")

	doc = frappe.get_doc(
		{"doctype": "File", "file_name": ad[: files.MAX_NAME], "is_private": 0, "content": icerik}
	)
	# `reject_unsafe_files` kancası burada da çalışır — izin listesi onun yerine
	# geçmiyor, üstüne biniyor.
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	audit.log_media_event(
		action=audit.ACTION_UPLOAD,
		file_url=doc.file_url,
		tenant=store,
		context={"bytes": len(icerik), "via": "seller_library"},
	)

	if video_mi:
		# Video normalize'i dakikalar sürebilir — istek içinde SENKRON
		# çalıştırılmaz (checklists.md §2 kural 9). `enqueue_transcode` durumu
		# hemen `processing` yapıp gerçek işi `long` kuyruğa devreder.
		transcode.enqueue_transcode(doc.file_url)

	return {"file_url": doc.file_url, "file_name": doc.file_name, "bytes": doc.file_size}


@frappe.whitelist()
def update_media(file_url: str, patch: str | dict | None = None) -> dict:
	"""Başlık, alternatif metin, açıklama, etiket, favori güncelle.

	Yalnız beyaz listedeki alanlar yazılır; gövdeye başka bir alan konursa yok
	sayılır (bkz. `metadata.EDITABLE`).
	"""
	store = _store()
	veri = frappe.parse_json(patch) if isinstance(patch, str) else (patch or {})
	return metadata.write(file_url, store, veri)


@frappe.whitelist()
def toggle_favorite(file_url: str) -> dict:
	"""Favoriyi ters çevir. Favori mağaza bazında — paylaşılan dosyada
	her mağaza kendi işaretini taşır."""
	store = _store()
	mevcut = metadata.read(file_url, store)
	return metadata.write(file_url, store, {"favorite": not mevcut.get("favorite")})


@frappe.whitelist()
def add_tag(file_urls: str | list[str] | None = None, tag: str = "") -> dict:
	"""Seçili dosyalara etiket ekle."""
	store = _store()
	temiz = (tag or "").strip()
	if not temiz:
		frappe.throw(frappe._("Etiket boş olamaz."))

	n = 0
	for url in _urls(file_urls):
		if not ownership.owns(store, url):
			continue
		mevcut = metadata.read(url, store).get("tags", [])
		if temiz in mevcut:
			continue
		metadata.write(url, store, {"tags": [*mevcut, temiz]})
		n += 1
	return {"tagged": n}


@frappe.whitelist()
def get_dimensions(file_url: str) -> dict:
	"""Gerçek çözünürlük — ilk soruluşta diskten okunup saklanır."""
	store = _store()
	ownership.assert_owns(store, file_url)
	return metadata.ensure_dimensions(file_url, store)


@frappe.whitelist()
def rename_media(file_url: str, new_name: str) -> dict:
	"""Görünen adı değiştir. Dosyanın YOLU değişmez — değişseydi onu gösteren
	her ürün, vitrin ve sipariş kaydı kırılırdı."""
	return files.rename(file_url, _store(), new_name)


@frappe.whitelist()
def duplicate_media(file_url: str) -> dict:
	"""Dosyanın gerçek bir kopyasını üret."""
	return files.duplicate(file_url, _store())


@frappe.whitelist()
def replace_media(file_url: str, content: str = "", file_name: str = "") -> dict:
	"""Dosyanın içeriğini değiştir — yolu ve tüm bağları korunur.

	İçerik base64 olarak JSON gövdesinde gelir, çok parçalı gönderim ile DEĞİL.
	Bu kurulumda çok parçalı istek Frappe'nin oturum katmanında yan etki
	yaratıp CSRF uyuşmazlığı üretiyor (aynı ders `api.js/uploadCertDocument`
	yorumunda kayıtlı).
	"""
	import base64

	store = _store()
	if not content:
		frappe.throw(frappe._("Dosya gönderilmedi."))

	# `data:...;base64,` öneki varsa ayıkla.
	ham = content.split(",", 1)[-1] if content.startswith("data:") else content
	try:
		icerik = base64.b64decode(ham, validate=True)
	except Exception:
		frappe.throw(frappe._("Dosya içeriği okunamadı."))

	return files.replace(file_url, store, icerik, file_name)
