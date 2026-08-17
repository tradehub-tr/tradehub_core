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

import base64
import os

import frappe

from tradehub_core.media import audit, engine, files, inventory, metadata, ownership, transcode, usage
from tradehub_core.media import seller_backup, seller_backup_export
from tradehub_core.media import seller_media as islem
from tradehub_core.media import chunked, upload_policy

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


# Kabul edilen türler ve boyut sınırları artık `media.upload_policy` içinde —
# TEK yerde (TUR-123).
#
# Buradaki listeler bu ucun kuralıydı ve yalnız bu uçta geçerliydi; panelde
# yükleme yapan diğer 22 ekran Frappe'nin genel ucundan geçiyor ve hiçbirini
# tanımıyordu. Kural tek modüle taşındı, hem bu uç hem `File` kancası oradan
# soruyor. İki kopya tutmak, biri değişince sessizce ayrışan iki kural demekti.
#
# Adlar geriye dönük uyumluluk için duruyor; değer politikadan geliyor.
UPLOAD_EXTENSIONS: frozenset[str] = frozenset(
	e
	for e, t in upload_policy.EXTENSIONS.items()
	if t in upload_policy.MEDIA_KINDS or e in upload_policy.MEDIA_EXTRA_EXTENSIONS
)
MAX_UPLOAD_BYTES: int = upload_policy.MAX_BYTES[upload_policy.KIND_IMAGE]

# Sunucu garanti-WebP (TUR-128) yalnız `engine.to_webp`'in açabildiği raster
# biçimlere uygulanır. Politikanın izin listesinden DAR: `.webp` (zaten hedef
# biçim, çift sıkıştırma yok) ve `.gif` kasıtlı DIŞARIDA — `engine.optimize` de
# animasyonlu GIF'i atlıyor (`OptimizeResult(reason="animated")`), aynı davranış
# burada da korunuyor; tek kare WebP'ye çevirmek animasyonu kırar.
IMAGE_TO_WEBP_EXTENSIONS: frozenset[str] = frozenset(
	{".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".avif", ".heic"}
)


@frappe.whitelist()
def upload_media(file_name: str = "", content: str = "") -> dict:
	"""Satıcı kütüphanesine dosya yükle.

	Frappe'nin genel yükleme ucu yerine bu uç kullanılıyor, çünkü orada bu
	kütüphanenin tür ve boyut kuralları yok. İçerik base64 gelir; bu kurulumda
	çok parçalı gönderim oturum katmanında CSRF uyuşmazlığı üretiyor.
	"""
	store = _store()

	if not content:
		upload_policy.reddet(upload_policy.CONTENT_EMPTY, frappe._("Dosya içeriği boş."))
	ham = content.split(",", 1)[-1] if content.startswith("data:") else content
	try:
		icerik = base64.b64decode(ham, validate=True)
	except Exception:
		upload_policy.reddet(
			upload_policy.CONTENT_UNREADABLE, frappe._("Dosya içeriği okunamadı.")
		)

	return _kaydet(file_name, icerik, store, via="seller_library")


def _kaydet(file_name: str, icerik: bytes, store: str, *, via: str) -> dict:
	"""Politikadan geçir, kaydı aç, denetime yaz.

	Tek parça ve parçalı yükleme aynı kuyruğa buradan giriyor. İki ayrı yerde
	kayıt açmak, ikinci kapıda denetim ya da sahiplik adımının unutulması
	demekti — yeni kapı açmanın klasik bedeli. WebP dönüşümü ve video transcode
	de bu yüzden burada: parçalı yükleme aynı garantileri kendiliğinden alır.
	"""
	karar = upload_policy.check(file_name, content=icerik, media_endpoint=True)

	video_mi = karar.kind == upload_policy.KIND_VIDEO

	# Sunucu garanti-WebP (TUR-128): Safari/iOS/Capacitor `canvas.toBlob(
	# 'image/webp')` desteklemiyor, client bu ortamlarda JPEG/PNG fallback'i
	# gönderir. `.webp` uzantısıyla gelen içerik zaten WebP'yse dokunulmaz —
	# çift sıkıştırma yok. Politika denetimi ORİJİNAL içerik üstünde yapıldı;
	# dönüşüm ancak ondan sonra.
	if upload_policy.extension_of(karar.file_name) in IMAGE_TO_WEBP_EXTENSIONS:
		try:
			icerik = engine.to_webp(icerik)
			karar.file_name = os.path.splitext(karar.file_name)[0] + ".webp"
		except Exception as exc:
			# `to_webp` Pillow'un açamadığı bir biçimle (ör. bazı HEIC varyantları)
			# karşılaşırsa orijinal içerikle devam edilir — yükleme reddedilmez,
			# yalnız Safari-fallback tamamlanmamış olur.
			frappe.log_error(
				title="upload_media to_webp başarısız", message=f"{karar.file_name}: {exc}"
			)

	doc = frappe.get_doc(
		{"doctype": "File", "file_name": karar.file_name, "is_private": 0, "content": icerik}
	)
	# `reject_unsafe_files` kancası burada da çalışır — politika onun yerine
	# geçmiyor, üstüne biniyor.
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	audit.log_media_event(
		action=audit.ACTION_UPLOAD,
		file_url=doc.file_url,
		tenant=store,
		context={
			"bytes": len(icerik),
			"via": via,
			"kind": karar.kind,
			# Zararsız tür uyuşmazlığı reddedilmiyor ama iz bırakıyor: sahada
			# ne kadar sık olduğunu ancak ölçerek bilebiliriz.
			**({"warnings": karar.warnings} if karar.warnings else {}),
		},
	)

	if video_mi:
		# Video normalize'i dakikalar sürebilir — istek içinde SENKRON
		# çalıştırılmaz (checklists.md §2 kural 9). `enqueue_transcode` durumu
		# hemen `processing` yapıp gerçek işi `long` kuyruğa devreder.
		transcode.enqueue_transcode(doc.file_url)

	return {"file_url": doc.file_url, "file_name": doc.file_name, "bytes": doc.file_size}


@frappe.whitelist()
def upload_limits() -> dict:
	"""Sunucunun uyguladığı sınırlar — istemci aynısını uygulasın diye.

	İstemci sınırları kendi içine YAZMIYOR, buradan alıyor. İki tarafa ayrı
	sabit koymak, biri değişince sessizce ayrışan iki kural demekti: kullanıcı
	ekranda kabul edilen dosyanın sunucuda reddedildiğini görürdü.
	"""
	_store()
	return upload_policy.limits()


@frappe.whitelist(methods=["POST"])
def upload_begin(file_name: str = "", total_bytes: int = 0) -> dict:
	"""Parçalı yükleme oturumu aç.

	Büyük dosya tek istekte gönderilemiyor: base64 içeriği %33 şişiriyor ve
	tamamı iki tarafın belleğinde duruyor. Ad ve boyut daha ilk adımda
	denetleniyor — 150 parçayı alıp sonunda "çok büyük" demek boşa iş olurdu.
	"""
	return chunked.begin(file_name, int(total_bytes or 0), _store())


@frappe.whitelist(methods=["POST"])
def upload_chunk(upload_id: str = "", index: int = 0, content: str = "") -> dict:
	"""Tek parçayı gönder. Parçalar sırasız gelebilir."""
	store = _store()
	if not content:
		upload_policy.reddet(upload_policy.CONTENT_EMPTY, frappe._("Parça boş."))
	ham = content.split(",", 1)[-1] if content.startswith("data:") else content
	try:
		veri = base64.b64decode(ham, validate=True)
	except Exception:
		upload_policy.reddet(upload_policy.CONTENT_UNREADABLE, frappe._("Parça okunamadı."))
	return chunked.put_chunk(upload_id, int(index or 0), veri, store)


@frappe.whitelist(methods=["POST"])
def upload_finish(upload_id: str = "") -> dict:
	"""Parçaları birleştir ve dosyayı kaydet.

	Politika birleşimden SONRA uygulanıyor: ilk parça geçerli bir görsel
	başlığı taşıyıp devamı bambaşka bir içerik olabilirdi.
	"""
	store = _store()
	icerik = chunked.finish(upload_id, store)
	meta = chunked.meta_of(upload_id, store)
	try:
		return _kaydet(meta["file_name"], icerik, store, via="seller_library_chunked")
	finally:
		# Kayıt açılsa da açılmasa da parçalar gitmeli; başarısız bir yüklemenin
		# artıkları diskte birikirse depo sessizce şişer.
		chunked.cleanup_session(upload_id)


@frappe.whitelist(methods=["POST"])
def upload_abort(upload_id: str = "") -> dict:
	"""Yarıda bırakılan yüklemeyi temizle — iptal gerçekten iptal olsun."""
	store = _store()
	chunked.cleanup_session(upload_id, store)
	return {"upload_id": upload_id, "aborted": True}


@frappe.whitelist()
def upload_status(upload_id: str = "") -> dict:
	"""Oturumun durumu — kopan yükleme kaldığı yerden sürebilsin."""
	return chunked.meta_of(upload_id, _store())


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


@frappe.whitelist(methods=["POST"])
def retry_video(file_url: str) -> dict:
	"""Başarısız (dead-letter) video işlemesini yeniden başlat (TUR-296).

	Yalnız kendi dosyası: sahiplik doğrulanmadan kuyruk tetiklenemez —
	`file_url` tahmin edilebilir olsaydı bile başka mağazanın videosu buradan
	yeniden işletilemez. Durum kuralı (`failed` dışında ret) `transcode`
	modülünde; burada tekrar edilmiyor.
	"""
	store = _store()
	ownership.assert_owns(store, file_url)
	sonuc = transcode.retry_failed(file_url)
	audit.log_media_event(
		action=audit.ACTION_OPTIMIZE,
		file_url=file_url,
		tenant=store,
		context={"kind": "video_transcode", "manual_retry": True},
	)
	return sonuc


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


# --- Yedekleme (TUR-131) ----------------------------------------------------
#
# Yönetimdeki `media_admin` yedek uçlarıyla AYNI şeyi yapmazlar: orası platform
# çapında çalışır (tüm dosyalar, tüm `File` satırları), burası yalnız oturumdaki
# mağazanın kapsamında. Mağaza dışarıdan parametre olarak ALINMAZ — alınsaydı
# satıcı başkasının mağaza kodunu yazıp yedeğine erişirdi.


@frappe.whitelist(methods=["POST"])
def create_backup(label: str = "") -> dict:
	"""Mağazanın medyasının anlık görüntüsünü al."""
	store = _store()
	return seller_backup.create(store, label=(label or "").strip()[:60])


@frappe.whitelist()
def list_backups() -> dict:
	"""Mağazanın yedekleri + disk kullanımı."""
	store = _store()
	return {"sets": seller_backup.list_sets(store), "usage": seller_backup.usage(store)}


@frappe.whitelist()
def verify_backup(set_id: str, deep: int = 0) -> dict:
	"""Yedek geri yüklenebilir mi — hiçbir şeye dokunmadan kontrol."""
	store = _store()
	return seller_backup.verify(store, set_id, deep=bool(int(deep or 0)))


@frappe.whitelist()
def plan_backup_restore(set_id: str) -> dict:
	"""Geri yükleme yapılsa ne olurdu — rapor, uygulama değil."""
	store = _store()
	return seller_backup.plan(store, set_id)


@frappe.whitelist(methods=["POST"])
def apply_backup_restore(
	set_id: str,
	with_files: int = 1,
	with_records: int = 1,
	overwrite: int = 0,
	only: str | list[str] | None = None,
) -> dict:
	"""Geri yüklemeyi uygula.

	`overwrite` VARSAYILAN OLARAK KAPALI: içeriği değişmiş dosyaya dokunulmaz.
	Açmak ayrı ve bilinçli bir seçim olmalı — dosya optimize edilmiş ya da
	yenisiyle değiştirilmiş olabilir.
	"""
	store = _store()
	yollar = frappe.parse_json(only) if isinstance(only, str) else (only or [])
	if yollar and len(yollar) > MAX_BATCH:
		frappe.throw(frappe._("Tek seferde en çok {0} dosya işlenebilir.").format(MAX_BATCH))
	return seller_backup.apply(
		store,
		set_id,
		files=bool(int(with_files or 0)),
		records=bool(int(with_records or 0)),
		overwrite=bool(int(overwrite or 0)),
		only=[y for y in yollar if y] or None,
	)


@frappe.whitelist(methods=["POST"])
def delete_backup(set_id: str) -> dict:
	"""Bir yedeği sil. Son yedek silinemez (kural `seller_backup`te)."""
	store = _store()
	return seller_backup.delete_set(store, set_id)


@frappe.whitelist(methods=["POST"])
def start_backup_export(set_id: str) -> dict:
	"""Yedeği indirilebilir pakete dönüştürmeyi başlat (arkada çalışır)."""
	store = _store()
	return seller_backup_export.start(store, set_id)


@frappe.whitelist()
def backup_export_status(set_id: str) -> dict:
	"""Paket hazır mı — ekran bunu yokluyor."""
	store = _store()
	return seller_backup_export.status(store, set_id)


@frappe.whitelist(methods=["POST"])
def discard_backup_export(set_id: str) -> dict:
	"""Paketi sunucudan kaldır. Yedeğin kendisine dokunulmaz."""
	store = _store()
	return seller_backup_export.discard(store, set_id)


@frappe.whitelist()
def download_backup_export(set_id: str):
	"""Paketi indir.

	Dosya belleğe ALINMIYOR: yüzlerce MB'lık bir paketi yanıt gövdesine koymak
	süreci şişirirdi. Frappe'nin özel dosya göndericisi parça parça akıtıyor.

	Yol kurma ve varlık kontrolü `seller_backup_export.package_path` içinde;
	mağaza oturumdan çözülüyor, istekten DEĞİL.
	"""
	from frappe.utils.response import send_private_file

	store = _store()
	tam = seller_backup_export.package_path(store, set_id)
	audit.log_media_event(
		action=audit.ACTION_EXPORT,
		tenant=store,
		sensitive=True,
		context={"set_id": set_id, "downloaded": True},
	)
	# Gönderici site'ın private kökünden itibaren göreli yol bekliyor.
	return send_private_file(os.path.relpath(tam, frappe.get_site_path("private")))
