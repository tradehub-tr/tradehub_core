# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""Teslim manifesti uçları — Dalga A / A3. `media/pipeline` ile Frappe arasındaki ince katman.

NEDEN AYRI BİR MODÜL
--------------------
`media/pipeline/api/delivery.py` **saf Python**tur: `@frappe.whitelist()` taşımaz,
`frappe`ye dokunmaz, site/DB olmadan test edilir. Bu bilinçli bir karardır ve
o dosya A3 kapsamında **değiştirilmemiştir**. Dışarıya bir uç açmak için gereken
her şey (whitelist, oturum, kiracı sınırı, DB okuma, bayrak) burada durur.

BAYRAK — VARSAYILAN KAPALI
--------------------------
`pipeline_flags.is_enabled("manifest_api_enabled")` False ise uç **hata
FIRLATMAZ**: boş bir manifest + bugünkü ham `file_url` (`fallback`) döner.
Storefront `renditions` boş görünce bugünkü `<img src>` davranışına düşer ve
site birebir bugünkü gibi çalışır. Bir uç noktanın "kapalıyım" demesi için 500
atması, tam olarak bayrağın engellemeye çalıştığı şeydir.

URL'LER SÖZLEŞMEDEN DEĞİL **VERİTABANINDAN** GELİR
--------------------------------------------------
`ManifestBuilder` türev adresini `derivative_key()` ile addan türetir
(`<hash>__w384.webp`). `Media Rendition` DocType'ının alan açıklaması ise başka
bir yol şeması yazıyor (`/files/media/{asset}/{version_hash}/…`). İkisi bugün
ÇELİŞİYOR ve türev üreten hat (A2) henüz tek satır yazmadı — hangi şemanın
kazanacağı belli değil.

Bu belirsizliği manifeste taşımak, tarayıcıya 404 indirtmek demektir; yani
`delivery/manifest.py`'nin başlığındaki en sert kuralın ("üretilmemiş varyant
`srcset`e girmez") ihlali. Bu yüzden bu katman `ManifestBuilder`ı **kendi
`url_for` çözücüsüyle** kurar: her varyantın adresi `Media Rendition.file_url`
kolonundan, yani gerçekten yazılmış dosyadan okunur. Merdiven sırası, biçim
önceliği, `sizes`/`loading`/`fetchpriority` kararları yine kütüphanenindir.

`benefit_gate_passed` SÜZGECİ
-----------------------------
`Media Rendition` sözleşmesi: "Geçmeyen türev üretilir ama **servis edilmez**"
— türev kaynaktan yeterince küçük değilse yayınlamak dosyayı büyütür. Süzgeç
burada uygulanır; kaç türevin bu yüzden elendiği yanıtta `suppressed` olarak
görünür, sessizce yutulmaz (aksi hâlde A2 bu bayrağı yazmayı unutursa özellik
sessizce ölü kalırdı ve kimse fark etmezdi).

ETag + gerçek koşullu HTTP
--------------------------
ETag `envelope.etag_for()` ile içerik-adresli üretilir (kanonik JSON'un
sha256'sı). Normal 200 yanıtında geriye uyum için `etag` ve `cache_control`
gövdede taşınır. Gerçek `If-None-Match` başlığı eşleştiğinde whitelist metodu
doğrudan Werkzeug `Response(status=304)` döndürür; Frappe v15 API yönlendiricisi
Response nesnesini JSON zarfına sarmadan geçirir. Böylece gövde yoktur ve
`ETag`/`Cache-Control` gerçek HTTP başlıklarıdır. Eski istemcinin
`if_none_match` sorgu parametresi ise geriye uyum için 200 + kısa gövdeyi
sürdürür.

KİRACI SINIRI
-------------
`get_manifest` guest'e açıktır (vitrin oturumsuz basılır) ama yalnız
**vitrinde görünen** (`storefront_visible = 1`) ilanın görselini gösterir;
taslak/arşiv/reddedilmiş ya da satıcının gizlediği ilan boş manifest alır —
404 değil, çünkü 404 ile boş manifest arasındaki fark "bu ilan var ama
yayında değil" bilgisini sızdırır. Ayrıca aynı `File` birden çok `Media Asset`e
hizmet edebildiği için varlık seçimi `owner_seller == listing.seller_profile`
ile daraltılır: başka satıcının varlığı, aynı dosyayı paylaşsa bile seçilmez.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import frappe
from frappe import _
from werkzeug.wrappers import Response

from tradehub_core.api import media_access
from tradehub_core.api.rate_limit import rate_limit
from tradehub_core.media import pipeline_flags
from tradehub_core.media.pipeline.api import delivery as pipeline_delivery
from tradehub_core.media.pipeline.api import envelope as env
from tradehub_core.media.pipeline.contracts.delivery import RenderManifest
from tradehub_core.media.pipeline.contracts.errors import NoProfileAvailable
from tradehub_core.media.pipeline.contracts.storage import (
	SCOPE_PRIVATE,
	SCOPE_PUBLIC,
	SHARD_LENGTH,
	ObjectKey,
	ObjectRef,
)
from tradehub_core.media.pipeline.delivery import manifest as manifest_mod
from tradehub_core.tradehub_core.doctype.media_version.media_version import (
	version_enrichment_for_assets,
)

#: Bayrak adı — `pipeline_flags.FLAG_FIELDS` içindeki alt bayrak.
FLAG_FIELD: str = "manifest_api_enabled"

#: Varsayılan slot. Ürün detay ve listeleme sayfalarının tamamı bu slotu basıyor.
DEFAULT_SLOT: str = "product.image"

#: W7 — İLAN bazlı uçların VİDEO servis ettiği slotlar. `company.cover_video`
#: BİLEREK dışarıda: o slot ilana değil şirket profiline bağlı (`bound_to`)
#: ve bu uçların anahtarı `Listing` adıdır; ilan üzerinden sorgulanamaz.
VIDEO_SLOTS: frozenset[str] = frozenset({"product.video"})

#: Video türev profil sözleşmesi — `media/pipeline_bridge.py` W7 sabitleriyle
#: AYNI adlar (oradan import edilmiyor: bu modül köprünün worker bağımlılıklarını
#: yüklememeli; adlar iki uçta da sözleşme yorumuyla sabitlendi).
VIDEO_PRIMARY_PROFILE: str = "h264"
VIDEO_POSTER_PROFILE: str = "poster"
VIDEO_HLS_PROFILE: str = "hls"
VIDEO_PREVIEW_PROFILE: str = "preview"

#: Birincil video türevinin MIME'ı. Köprü yalnız mp4 (H.264/AAC) üretir;
#: passthrough kaynaklar da karar tablosu gereği mp4 kabındadır (mp4 dışı
#: kap REMUX kuralına takılır) — tek sabit yeterli.
VIDEO_MIME: str = "video/mp4"

#: Tek `get_manifest_batch` çağrısında işlenecek azami ilan. Aşan istek
#: REDDEDİLMEZ, **kırpılır**: listeleme sayfası 60 kart bastığında hata almak
#: yerine ilk 50'nin manifestini alıp kalanını `fallback`e bırakmalı.
#: `pipeline/api/delivery.MAX_BATCH` (100) varlık sayısıdır; buradaki 50 ilan
#: sayısıdır ve bir ilan ortalama 3-12 görsel taşır.
MAX_BATCH_LISTINGS: int = 50

#: Tek istekte AYRIŞTIRILACAK azami kimlik — `MAX_BATCH_LISTINGS`in 10 katı.
#: `MAX_BATCH_LISTINGS` yalnız DB'ye giden listeyi kelepçeliyordu; ayrıştırma
#: ve `skipped` yankısı sınırsızdı, yani 10.000 kimlik gönderen bir çağıran
#: sorgu atmadan da CPU ve yanıt gövdesi harcatabiliyordu. Vitrin istemcisi
#: zaten 50'lik parçalar hâlinde istiyor (`lib/media/manifest.ts:MAX_BATCH`),
#: yani meşru bir çağıran bu tavanı asla görmez. `_pagination.normalize_*`
#: ile aynı savunmacı üslup: her iki uçtan kelepçele, REDDETME.
MAX_REQUEST_LISTINGS: int = 500

#: Ham girdi dizgesinin azami uzunluğu. 500 kimlik × ~40 karakter üst sınır.
#: Aşan kısım kesilir; kesilen JSON `_listeyi_coz` içindeki virgüllü-liste
#: yoluna düşer ve zaten tavana kadar kırpılır.
MAX_INPUT_CHARS: int = 20_000

#: Toplu ucun hız sınırı. DİKKAT: `api/rate_limit._bucket_key` kovayı
#: `frappe.session.user`a bağlıyor; TÜM misafirler tek kovayı paylaşır. Bu
#: yüzden değer "çağıran başına" değil **toplam** bir tavandır ve kasten
#: yüksek tutuldu — düşük bir sayı tek bir kötü niyetliyi durdururken tüm
#: vitrini de kilitlerdi. Kova anahtarını IP'ye taşımak `rate_limit.py`nin
#: işi (bu görevin kapsamı dışında).
BATCH_RATE_LIMIT_CALLS: int = 600
BATCH_RATE_LIMIT_WINDOW: int = 60

#: Manifest gövdesinin önbellek başlığı — kütüphaneyle aynı değer.
CACHE_CONTROL: str = env.CACHE_MANIFEST

#: Vitrin görünürlüğünün KANONİK yüklemi `storefront_visible = 1`'dir
#: (`api/listing.py` baştan sona bunu kullanıyor: :423, :425, :1657, :2278,
#: :2640, …). Kolon `Listing.validate` içinde `is_visible AND status IN
#: STOREFRONT_VISIBLE_STATUSES` olarak hesaplanır
#: (`doctype/listing/listing.py:_set_storefront_visible`) ve arşivleme üçünü
#: birden 0'lar (`api/listing.py:4505`). Tek başına `status` süzmek satıcının
#: `is_visible = 0` ile gizlediği ürünün TÜM galerisini misafire açıyordu.
VISIBLE_LISTING_FILTER: dict[str, Any] = {"storefront_visible": 1}

#: `storefront_visible` YANINDA duran ikinci katman (savunmada derinlik):
#: denormalize kolon `db.set_value` yollarında sürüklenirse (drift) durum
#: süzgeci yine tutar. `storefront_visible` "Out of Stock"u da içerdiği için
#: bu tuple onu KAPSAMAZ — stoksuz ürün bugün de manifest almıyor, davranış
#: bilinçli olarak değiştirilmedi.
STATUS_GUARD: tuple[str, ...] = ("Active",)

#: Manifeste giren varlık durumu. Faz 3 durum makinesinde teslime hazır tek
#: durum budur; `processing`/`review` varlığın türevleri yarım olabilir.
READY_STATE: str = "ready"

#: `manifest_batch` (dosya bazlı, panel) tek istekte kabul edilen azami adres.
#: Sayı şartnamede yazmıyor; `pipeline/api/delivery.MAX_BATCH` (100) ile AYNI
#: tutuluyor ki iki toplu ucun tavanı sessizce ayrışmasın. İlan bazlı
#: `get_manifest_batch`in aksine aşım KIRPILMAZ, REDDEDİLİR: orası guest'e
#: açık bir vitrin ucu (hata = boş vitrin), burası oturumlu bir panel ucu —
#: paneldeki bir programlama hatası sesli kırılmalı, sessizce eksik veri
#: göstermemeli.
FILE_BATCH_MAX: int = pipeline_delivery.MAX_BATCH

#: Dosya başına okunacak en yeni varlık sayısı. Panelin bugüne kadarki REST
#: sorgusuyla aynı değer (`useMediaRenditions.js: limit_page_length: 5`) —
#: davranış toplu uca taşınırken DEĞİŞTİRİLMEDİ.
FILE_BATCH_ASSETS_PER_FILE: int = 5

#: Dosya başına türev tavanı. Panelin eski `MAX_RENDITIONS` (60) değeri:
#: aynı dosyanın merdiveni dar bir kümedir, sayfalama yerine makul bir tavan.
FILE_BATCH_RENDITIONS_PER_FILE: int = 60

#: Bir dosya adresinin azami uzunluğu (`File.file_url` yol + ad taşır;
#: docname 140 ile sınırlı ama adres daha uzun olabilir).
FILE_BATCH_MAX_ENTRY_CHARS: int = 500


# ── whitelist uçları ────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True)
def get_manifest(listing: str = "", slot: str = DEFAULT_SLOT, if_none_match: str = "") -> dict:
	"""Tek ilanın teslim manifesti.

	Args:
	    listing: `Listing` adı (ör. `LST-00201`).
	    slot: Slot politikası anahtarı; varsayılan `product.image`.
	    if_none_match: Önceki yanıtın `etag`i. Eşleşirse gövdesiz yanıt döner.

	Returns:
	    Bayrak kapalı, ilan görünmez ya da türev yoksa:
	    `{"renditions": [], "images": [], "fallback": "<ham file_url>", ...}`.
	    Hiçbir durumda istisna fırlatmaz — vitrin bir manifest hatası yüzünden
	    kırılmamalı.
	"""
	# Bayrak İLK: hiçbir DB işine girmeden, `media/pipeline_bridge.py` ile
	# aynı desende sorulur ve tek bir kez okunup aşağı taşınır (eskiden iki
	# sorgudan SONRA, üstelik `_bos_manifest` içinde tekrar tekrar okunuyordu).
	# Kapalıyken tam kısa devre YAPILMAZ: bugünkü gövde `fallback` alanında
	# ham `file_url`u taşıyor ve sözleşme değişmemeli — bayrak yalnız varlık
	# ve türev sorgularını (2 sorgu) tümden kapatır.
	acik = _bayrak_acik()
	ilan = _temiz(listing, 140)
	slot_key = _temiz(slot, 64) or DEFAULT_SLOT
	if not ilan:
		return _finalize(_bos_manifest("", slot_key, acik), if_none_match)

	try:
		govde = _manifest_icin(ilan, slot_key, acik)
	except Exception:
		# Manifest bir SÜSLEMEDİR: üretilemezse ilan yine ham `src` ile basılır.
		# Bu uç guest'e açık ve her ürün sayfasında çağrılıyor; bir kenar
		# durumun tüm vitrini 500'e düşürmesine izin verilemez.
		frappe.log_error(
			title="media manifest",
			message=f"get_manifest({ilan!r}, {slot_key!r}) başarısız\n\n{frappe.get_traceback()}",
		)
		govde = _bos_manifest(ilan, slot_key, acik)

	return _finalize(govde, if_none_match)


@frappe.whitelist(allow_guest=True)
@rate_limit(
	max_calls=BATCH_RATE_LIMIT_CALLS,
	window_seconds=BATCH_RATE_LIMIT_WINDOW,
	scope="media_manifest_batch",
)
def get_manifest_batch(listings: str = "", slot: str = DEFAULT_SLOT, if_none_match: str = "") -> dict:
	"""Çok ilan, tek istek — listeleme sayfası için.

	Args:
	    listings: JSON dizisi (`["LST-1","LST-2"]`) ya da virgülle ayrılmış
	        liste. HTTP GET üzerinden geldiği için dizge kabul edilir.
	    slot: Slot politikası anahtarı.
	    if_none_match: Önceki yanıtın `etag`i.

	Returns:
	    `{"manifests": {<ilan>: {...}}, "missing": [], "requested": n,
	    "returned": n, "truncated": bool, ...}`

	`MAX_BATCH_LISTINGS` üstü **kırpılır**, reddedilmez. N+1 yoktur: ilan,
	galeri, varlık ve türev okumalarının her biri tek sorgudur (toplam 4).
	"""
	# Bayrak İLK — gerekçe `get_manifest`te.
	acik = _bayrak_acik()
	slot_key = _temiz(slot, 64) or DEFAULT_SLOT
	istenen = _listeyi_coz(listings)
	kirpildi = len(istenen) > MAX_BATCH_LISTINGS
	secilen = istenen[:MAX_BATCH_LISTINGS]

	govde: dict[str, Any] = {
		"slot": slot_key,
		"enabled": acik,
		"manifests": {},
		# DAİMA BOŞ. Eskiden bulunamayan kimlikleri sayardı; uç `allow_guest`
		# olduğu için bu, oturumsuz bir çağırana "denediğin kimliklerden
		# hangileri gerçek" diye cevap veren bir numaralandırma kehanetiydi.
		# Alan sözleşme uyumu için duruyor (vitrin istemcisi okumuyor:
		# `tradehubfront/src/lib/media/manifest.ts` yalnız `enabled` ve
		# `manifests` alanlarına bakıyor). Kimliğe göre DEĞİŞMİYOR, çünkü
		# yanıt `public, max-age=60` ile önbelleklenebilir — oturuma göre
		# farklılaşan bir gövde paylaşılan önbellekte karışırdı.
		"missing": [],
		"requested": len(istenen),
		"returned": 0,
		"truncated": kirpildi,
		"max_batch": MAX_BATCH_LISTINGS,
	}

	if secilen:
		try:
			manifestler = _manifest_batch_icin(secilen, slot_key, acik)
		except Exception:
			frappe.log_error(
				title="media manifest",
				message=f"get_manifest_batch({len(secilen)} ilan, {slot_key!r}) başarısız"
				f"\n\n{frappe.get_traceback()}",
			)
			manifestler = {}
		govde["manifests"] = manifestler
		govde["returned"] = len(manifestler)
	# `skipped` bir kehanet DEĞİL, çağıranın KENDİ girdisinin yankısıdır:
	# sınırı aşan kimlikler geri verilir ki çağıran ikinci bir istek atsın.
	# `MAX_REQUEST_LISTINGS` tavanı sayesinde en çok 450 eleman taşır.
	govde["skipped"] = istenen[MAX_BATCH_LISTINGS:]

	return _finalize(govde, if_none_match)


@frappe.whitelist()
def get_signed_url(file_url: str, ttl_seconds: int = media_access.DEFAULT_TTL_SECONDS) -> dict:
	"""Private bir medya dosyası için süreli, imzalı adres.

	**Guest çağıramaz** (`allow_guest` YOK) ve içeride ikinci bir kapı daha
	var — whitelist bayrağı bir gün gevşetilirse bile oturumsuz imza üretilmez.

	Kripto burada YAZILMAZ: doğrudan `api/media_access.get_signed_url`e
	devredilir (Frappe `verified_command` / site secret + HMAC-SHA512).
	Bu uç yeni bir yetenek açmaz, yalnız medya API yüzeyini tek modülde
	toplar — bu yüzden bayrak arkasında değildir: bayrak kapalıyken de
	çağıran zaten `media_access` ucunu doğrudan çağırabiliyor.

	Args:
	    file_url: `/private/files/...` ile başlayan dosya adresi.
	    ttl_seconds: Geçerlilik süresi; `media_access` sınırlarına clamp'lenir.

	Returns:
	    `{"url": ..., "exp": <unix ts>, "ttl_seconds": ..., "cache_control": ...}`

	Raises:
	    frappe.PermissionError: Oturum yoksa ya da dosyaya read yetkisi yoksa.
	"""
	if frappe.session.user in ("Guest", "", None):
		frappe.throw(_("Bu işlem için giriş yapmalısınız."), frappe.PermissionError)

	sonuc = dict(media_access.get_signed_url(file_url, ttl_seconds))
	# Yetki denetimi ve imza BAŞARILI olduktan sonra aynı kaynağa bağlı, bu
	# kullanıcının görebildiği varlıkların lazy merdivenini ısıt. Yardımcı kendi
	# içinde best-effort'tur; imza üretimi bir görüntü encode hatası yüzünden
	# bozulmaz. Özel kaynaklar bugün public türev hattına girmediği için köprü
	# onları güvenli biçimde `private_source` durumuyla atlar.
	_lazy_renditions_for_file_url(file_url)
	# İmzalı yanıt ASLA paylaşılan önbelleğe girmemeli; aksi hâlde bir
	# kullanıcının imzası başkasına servis edilir (`envelope.CACHE_NEVER`).
	sonuc["cache_control"] = env.CACHE_NEVER
	return sonuc


# ── T-083 toplu DOSYA manifesti (yönetim paneli) ────────────────────────


@frappe.whitelist()
def manifest_batch(file_urls: list | str | None = None) -> dict:
	"""N dosya adresi → `{adres: manifest}` haritası — panelin türev tablosu için.

	`get_manifest_batch` ile KARIŞTIRMAYIN: o uç İLAN bazlıdır, guest'e açıktır
	ve vitrinin `srcset` manifestini üretir. Bu uç DOSYA bazlıdır, oturum ister
	ve panelin "bu dosyadan hangi türevler üretildi" envanterini verir. Panel
	bu veriyi bugüne kadar dosya başına 2 genel REST sorgusuyla çekiyordu
	(`File` docname → `Media Asset` → `Media Rendition`,
	`admin-panel/.../useMediaRenditions.js`); bu uç AYNI zinciri tek çağrıda,
	N dosya için toplu yürütür. Yeni bir manifest üretici YAZILMADI:
	`ManifestBuilder` vitrinin `srcset`/`sizes` kararlarını verir ve fayda
	kapısını geçmeyen türevi gizler — panel ise üretim envanterini olduğu
	gibi (elenenler dâhil) göstermek zorunda, o yüzden burada ham türev
	satırları döner.

	Args:
	    file_urls: `File` docname'lerinin ya da `file_url` adreslerinin listesi
	        (JSON dizisi de kabul edilir — HTTP üzerinden dizge gelebilir).
	        Panel docname yollar (`Media Asset.source_file` bir Link ve docname
	        tutar); adresle de çözülür ki çağıranın elindeki kimlik türü
	        önemli olmasın.

	Returns:
	    `{"manifests": {<istenen adres>: manifest | None}, "requested": n,
	    "returned": n, "max_batch": FILE_BATCH_MAX}`

	    Manifest: `{"file": docname, "file_url": adres, "assets": [ad, ...],
	    "renditions": [{name, asset, profile, width, height, format, file_url,
	    bytes, ssim, generation, benefit_gate_passed}, ...]}`

	    **Erişilemeyen adres `None` döner, hata DEĞİL** — "yok", "silinmiş" ve
	    "başka satıcının özel dosyası" üçü de aynı `None`dır; ayrıştırmak bir
	    adresin VARLIĞINI sızdırır (`pipeline/api/delivery.py` kural 2).

	Raises:
	    frappe.PermissionError: Oturum yoksa.
	    frappe.ValidationError: `FILE_BATCH_MAX` üstü istek — kırpılmaz,
	        reddedilir (gerekçe `FILE_BATCH_MAX` sabitinin üstünde).
	"""
	if frappe.session.user in ("Guest", "", None):
		frappe.throw(_("Bu işlem için giriş yapmalısınız."), frappe.PermissionError)

	istenen = _dosya_listesi_coz(file_urls)
	if len(istenen) > FILE_BATCH_MAX:
		frappe.throw(
			_("Tek istekte en fazla {0} dosya istenebilir ({1} istendi).").format(
				FILE_BATCH_MAX, len(istenen)
			),
			frappe.ValidationError,
		)

	govde: dict[str, Any] = {
		"manifests": dict.fromkeys(istenen),
		"requested": len(istenen),
		"returned": 0,
		"max_batch": FILE_BATCH_MAX,
	}
	if not istenen:
		return govde

	# 1/3 — adresleri `File` kaydına çöz. `get_list` BİLİNÇLİ: Frappe'nin File
	# izin katmanı devrede kalır; başkasının özel dosyası burada hiç çözülmez
	# ve haritada `None` kalır (olmayan dosyayla ayırt edilemez).
	dosyalar = frappe.get_list(
		"File",
		or_filters=[["name", "in", istenen], ["file_url", "in", istenen]],
		fields=["name", "file_url"],
		limit_page_length=0,
	)
	ada_gore = {d["name"]: d for d in dosyalar}
	adrese_gore = {d["file_url"]: d for d in dosyalar if d.get("file_url")}
	cozulen: dict[str, dict[str, Any]] = {}
	for adres in istenen:
		dosya = ada_gore.get(adres) or adrese_gore.get(adres)
		if dosya:
			cozulen[adres] = dosya

	# 2/3 — mükerrer File köprüsü. Fiziksel dosyanın kimliği docname DEĞİL,
	# `file_url`: aynı adreste 5+ mükerrer `File` satırı ölçüldü
	# (`docs/reports/69-w3b-boru-hatti-e2e.md` §7.1) ve varlık bunlardan
	# yalnız BİRİNE bağlı. Docname join'i panelde yazı-tura görür — köprü
	# çözülen adresi taşıyan TÜM satırları toplar; ilan tarafının
	# `_varliklari_getir`i zaten aynı sebeple `file_url` join'i kullanıyor.
	kopru = _mukerrer_dosya_koprusu(list(cozulen.values()))
	varliklar = _dosya_varliklari(kopru)
	varlik_adlari = [v["name"] for grup in varliklar.values() for v in grup]
	aktif_surumler = {
		v["name"]: str(v.get("active_version") or "") for grup in varliklar.values() for v in grup
	}
	# İlk panel okuması gerçek üretim kapısıdır: lazy profil DB/disk cache'inde
	# yoksa distributed singleflight altında üretilir; aşağıdaki sorgu aynı
	# istekte yeni satırları görür. İkinci okuma yalnız persistent cache'i okur.
	_ensure_lazy_renditions(varlik_adlari)
	turevler = _varlik_turevleri(varlik_adlari, aktif_surumler)
	# T-061/062/065: panel kalite/detay yüzeyleri sürüm zenginleştirmesini
	# `manifest.version` anahtarından okur (rapor 73 §3.3). Tek sorgu, N+1 yok.
	zengin = version_enrichment_for_assets(sorted({v["name"] for grup in varliklar.values() for v in grup}))

	for adres, dosya in cozulen.items():
		secili = varliklar.get(_dosya_anahtari(dosya)) or []
		satirlar = [t for v in secili for t in turevler.get(v["name"]) or []]
		satirlar.sort(key=lambda t: (int(t.get("width") or 0), str(t.get("format") or "")))
		govde["manifests"][adres] = {
			"file": dosya["name"],
			"file_url": dosya.get("file_url") or "",
			"assets": [v["name"] for v in secili],
			"renditions": satirlar[:FILE_BATCH_RENDITIONS_PER_FILE],
			# İlk zenginleştirilmiş sürüm — varlık seçim sırası `secili` ile aynı.
			"version": next((zengin[v["name"]] for v in secili if v["name"] in zengin), None),
		}

	govde["returned"] = sum(1 for m in govde["manifests"].values() if m is not None)
	return govde


def _dosya_anahtari(dosya: Mapping[str, Any]) -> str:
	"""Bir File satırının varlık-arama anahtarı: `file_url`, yoksa docname."""
	return str(dosya.get("file_url") or "") or str(dosya["name"])


def _mukerrer_dosya_koprusu(dosyalar: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
	"""Çözülen File satırları → `{anahtar: [aynı adresi taşıyan TÜM docname'ler]}`.

	Varlık `source_file` Link'i mükerrer satırlardan HERHANGİ birine bağlı
	olabilir (yükleme anında `frappe.db.get_value` sırasız ilk satırı seçiyor);
	kullanıcı ise elindeki HERHANGİ bir docname ile sorar. Köprü ikisini
	`file_url` üzerinden buluşturur.

	`frappe.get_all` BİLİNÇLİ (izin süzgeçsiz) ve burada güvenli — gerekçe:
	  1. Girdi adresler ZATEN izinli: köprüye yalnız 1. adımın (`File`
	     `get_list`i, Frappe izin süzgeçli) çözdüğü satırların adresi girer.
	     Aynı `file_url` aynı fiziksel dosyadır — kullanıcı o dosyayı
	     görebildiğini kanıtladı, mükerrer satır yeni bilgi taşımaz.
	  2. Çıktı docname'ler yanıta YAZILMAZ; yalnız varlık sorgusunun
	     `source_file in (...)` süzgecini genişletir.
	  3. Kiracı sınırı bir sonraki halkada duruyor: `_dosya_varliklari`
	     `get_list` ile `media_asset_query_conditions`tan geçer — köprü
	     başka satıcının varlığını GÖSTEREMEZ, yalnız kullanıcının kendi
	     varlığını mükerrer satırın arkasından çıkarır.
	Köprüyü izinli `get_list`e çevirmek kör noktayı GERİ GETİRİR: mükerrer
	satırın sahibi başka bir kullanıcı olabilir (aynı public görsel iki kez
	yüklenmiş) ve satır süzülünce varlık yine bulunamazdı.
	"""
	kopru: dict[str, list[str]] = {}
	adresler: set[str] = set()
	for dosya in dosyalar:
		if dosya.get("file_url"):
			adresler.add(str(dosya["file_url"]))
		else:
			# Adressiz File kaydı: köprü kurulamaz, kendi docname'iyle sınırlı.
			grup = kopru.setdefault(_dosya_anahtari(dosya), [])
			if dosya["name"] not in grup:
				grup.append(str(dosya["name"]))
	if adresler:
		for satir in frappe.get_all(
			"File",
			filters={"file_url": ["in", sorted(adresler)]},
			fields=["name", "file_url"],
			limit_page_length=0,
		):
			kopru.setdefault(satir["file_url"], []).append(satir["name"])
	# Emniyet: çözülen satırın kendisi her koşulda köprüde kalsın.
	for dosya in dosyalar:
		anahtar = _dosya_anahtari(dosya)
		grup = kopru.setdefault(anahtar, [])
		if dosya["name"] not in grup:
			grup.append(str(dosya["name"]))
	return kopru


def _dosya_varliklari(kopru: Mapping[str, Sequence[str]]) -> dict[str, list[dict[str, Any]]]:
	"""Adres → en yeni ≤5 varlık. TEK sorgu; kiracı süzgeci `get_list`te.

	`get_list` BİLİNÇLİ (`get_all` DEĞİL): `hooks.py`'deki
	`media_asset_query_conditions` ancak böyle devreye girer ve satıcı yalnız
	kendi varlıklarını görür. Panelin eski REST akışı da aynı katmandan
	geçiyordu — izolasyon istemciye taşınmadı, yerinde bırakıldı. Burayı
	`get_all`/`ignore_permissions` yapmak kiracı sınırını KALDIRIR
	(`tests/test_manifest_batch.py` bunu kırmızıya düşürür).

	Gruplama docname değil KÖPRÜ ANAHTARIYLA (`file_url`) yapılır: varlığın
	bağlı olduğu docname, kullanıcının verdiği docname olmayabilir
	(mükerrer File satırları — `_mukerrer_dosya_koprusu`).
	"""
	anahtar_of: dict[str, str] = {}
	for anahtar, adlar in kopru.items():
		for ad in adlar:
			anahtar_of[str(ad)] = anahtar
	if not anahtar_of:
		return {}
	cikti: dict[str, list[dict[str, Any]]] = {}
	for satir in frappe.get_list(
		"Media Asset",
		filters={"source_file": ["in", sorted(anahtar_of)]},
		fields=["name", "source_file", "active_version"],
		order_by="creation desc",
		limit_page_length=0,
	):
		anahtar = anahtar_of.get(satir["source_file"])
		if anahtar is None:
			continue
		grup = cikti.setdefault(anahtar, [])
		if len(grup) < FILE_BATCH_ASSETS_PER_FILE:
			grup.append(satir)
	return cikti


def _varlik_turevleri(
	varlik_adlari: Sequence[str],
	aktif_surumler: Mapping[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
	"""Varlık → türev satırları. TEK sorgu; kiracı süzgeci `get_list`te.

	`benefit_gate_passed` süzülmez: vitrin manifestinin aksine panel üretim
	ENVANTERİNİ gösterir — kapıda elenen türev de üretilmiştir ve satıcı onu
	görmeli (alan yanıtta açık, çağıran isterse ayrıştırır).
	"""
	if not varlik_adlari:
		return {}
	if aktif_surumler is None:
		aktif_surumler = {
			row["name"]: str(row.get("active_version") or "")
			for row in frappe.get_list(
				"Media Asset",
				filters={"name": ["in", list(varlik_adlari)]},
				fields=["name", "active_version"],
				limit_page_length=0,
			)
		}
	cikti: dict[str, list[dict[str, Any]]] = {}
	for satir in frappe.get_list(
		"Media Rendition",
		filters={"asset": ["in", list(varlik_adlari)]},
		fields=[
			"name",
			"asset",
			"state",
			"version_hash",
			"profile",
			"width",
			"height",
			"format",
			"file_url",
			"bytes",
			"ssim",
			"generation",
			"benefit_gate_passed",
		],
		order_by="width asc",
		limit_page_length=0,
	):
		if str(satir.get("state") or "ready") != "ready":
			continue
		aktif = str(aktif_surumler.get(satir["asset"]) or "")
		satir_surum = str(satir.get("version_hash") or "")
		if (aktif and satir_surum != aktif) or (not aktif and satir_surum):
			continue
		cikti.setdefault(satir["asset"], []).append(satir)
	return cikti


def _dosya_listesi_coz(ham: Any) -> list[str]:
	"""JSON dizisi ya da liste → tekilleştirilmiş adres listesi.

	`_listeyi_coz`dan farkı: virgüllü dizge YOK (dosya adında virgül geçebilir)
	ve tavan kırpma YOK — aşım `manifest_batch` içinde REDDEDİLİR, bu yüzden
	burada liste olduğu gibi sayılmalı.
	"""
	if ham is None:
		return []
	if isinstance(ham, str):
		metin = ham.strip()
		if not metin:
			return []
		try:
			ham = frappe.parse_json(metin)
		except Exception:
			frappe.throw(_("`file_urls` bir JSON dizisi olmalı."), frappe.ValidationError)
	if not isinstance(ham, (list, tuple)):
		frappe.throw(_("`file_urls` bir liste olmalı."), frappe.ValidationError)

	cikti: list[str] = []
	gorulen: set[str] = set()
	for parca in ham:
		adres = _temiz(parca, FILE_BATCH_MAX_ENTRY_CHARS)
		if adres and adres not in gorulen:
			gorulen.add(adres)
			cikti.append(adres)
	return cikti


# ── manifest kurulumu ───────────────────────────────────────────────────


@dataclass
class _CiftSuzgecliBuilder(manifest_mod.ManifestBuilder):
	"""`available` süzgecini profil değil **(profil, biçim)** çiftine indirir.

	`ManifestBuilder.build_image(available_profiles=…)` profil adına bakar.
	Ama DB'de üretilmişlik çift bazındadır: `w768` profilinin WebP türevi
	fayda kapısını geçmiş, AVIF türevi geçmemiş olabilir. Kütüphanenin
	süzgeciyle bu durumda AVIF de "üretilmiş" sayılır ve `srcset`e girer —
	tarayıcı AVIF'i tercih eder, diskte olmayan dosyaya 404 gider ve görsel
	HİÇ görünmez. Tam olarak `delivery/manifest.py` başlığının uyardığı hata.

	Süzgeç kütüphanede genişletilebilirdi ama `pipeline/` A3 kapsamında
	DEĞİŞTİRİLMİYOR; bu yüzden daraltma burada, alt sınıfta yapılıyor.
	Sıralama/gruplama kararları (biçim önceliği, artan genişlik, orta basamak
	`src`) yine kütüphaneye ait — `_sources` / `_fallback_url` yeniden
	yazılmıyor, miras alınıyor.
	"""

	#: Servis edilebilir `(profil, biçim)` çiftleri — `Media Rendition` satırları.
	servis_edilir: frozenset[tuple[str, str]] = frozenset()

	def build_image(self, slot_key: str, base: ObjectRef, **kwargs: Any) -> RenderManifest:
		man = super().build_image(slot_key, base, **kwargs)
		varyantlar = tuple(
			replace(v, available=(v.profile, v.fmt.lower()) in self.servis_edilir) for v in man.variants
		)
		uretilmis = [v for v in varyantlar if v.available]
		if not uretilmis:
			raise NoProfileAvailable(
				f"`{slot_key}` için servis edilebilir hiçbir türev yok.",
				detay={"slot_key": slot_key},
			)
		return replace(
			man,
			variants=varyantlar,
			sources=self._sources(uretilmis, man.sizes),
			fallback_url=self._fallback_url(uretilmis),
		)


def _manifest_icin(ilan: str, slot_key: str, acik: bool) -> dict[str, Any]:
	"""Tek ilanın manifest gövdesi. Görünmezse/bayrak kapalıysa boş gövde."""
	sonuc = _manifest_batch_icin([ilan], slot_key, acik)
	return sonuc.get(ilan) or _bos_manifest(ilan, slot_key, acik)


def _manifest_batch_icin(ilanlar: Sequence[str], slot_key: str, acik: bool) -> dict[str, dict[str, Any]]:
	"""N ilan → N manifest. Toplam 4 sorgu; ilan sayısından bağımsız.

	`acik` DIŞARIDAN gelir: bayrak uçta, ilk satırda okunmuştur. Kapalıyken
	varlık ve türev sorguları hiç çalışmaz.
	"""
	# W7: video slotu AYRI kurulur — `Listing Image` galerisi değil
	# `Listing.video_url` okunur ve gövde `video` bloğu taşır. Rapor 81 §7'nin
	# ölçtüğü kusur tam buradaydı: slot ne olursa olsun görseller dönüyordu.
	if slot_key in VIDEO_SLOTS:
		return _video_manifest_batch_icin(ilanlar, slot_key, acik)

	satirlar = _gorunur_ilanlar(ilanlar)
	if not satirlar:
		return {}

	gorseller = _ilan_gorselleri(satirlar)

	varliklar: dict[str, dict[str, Any]] = {}
	turevler: dict[str, list[dict[str, Any]]] = {}
	if acik:
		tum_url = sorted({g["file_url"] for gs in gorseller.values() for g in gs})
		varliklar = _varliklari_getir(tum_url, slot_key)
		# Aynı fiziksel URL başka satıcılarda da varlık taşıyabilir. Guest isteği
		# yalnız görünür ilanın sahibine seçilen varlığı üretmeli; bütün adayları
		# çalıştırmak kiracı-dışı bir mutasyon olurdu.
		secili_varlik_adlari = sorted(
			{
				varlik["name"]
				for ilan in satirlar
				for gorsel in gorseller.get(ilan["name"]) or ()
				if (
					varlik := _varlik_sec(
						varliklar.get(gorsel["file_url"]) or {},
						str(ilan.get("seller_profile") or ""),
					)
				)
			}
		)
		_ensure_lazy_renditions(secili_varlik_adlari)
		# `varliklar` iki katmanlı: {file_url: {owner_seller: varlık}}.
		aktif_surumler = {
			v["name"]: str(v.get("active_version") or "")
			for grup in varliklar.values()
			for v in grup.values()
		}
		turevler = _turevleri_getir(secili_varlik_adlari, aktif_surumler)

	# T-061/062/065 (W4-3, rapor 73 §3.3): sürüm zenginleştirmesi (lqip,
	# dominant renk, dpi/renk uzayı/alpha, sınıflandırma) tek sorguyla — N+1 yok.
	zengin: dict[str, dict[str, Any]] = (
		version_enrichment_for_assets(
			sorted({v["name"] for grup in varliklar.values() for v in grup.values()})
		)
		if acik
		else {}
	)

	cikti: dict[str, dict[str, Any]] = {}
	for satir in satirlar:
		ad = satir["name"]
		cikti[ad] = _tek_ilan_govdesi(
			satir, gorseller.get(ad) or [], slot_key, varliklar, turevler, acik, zengin
		)
	return cikti


def _tek_ilan_govdesi(
	ilan: dict[str, Any],
	gorseller: list[dict[str, Any]],
	slot_key: str,
	varliklar: dict[str, dict[str, Any]],
	turevler: dict[str, list[dict[str, Any]]],
	acik: bool,
	zengin: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
	"""Bir ilanın manifest gövdesi — görsel başına merdiven + düz türev listesi."""
	govde = _bos_manifest(ilan["name"], slot_key, acik)
	govde["fallback"] = (gorseller[0]["file_url"] if gorseller else "") or ""

	if not gorseller:
		return govde

	sahip = str(ilan.get("seller_profile") or "")
	duz: list[dict[str, Any]] = []
	elenen = 0

	for sira, gorsel in enumerate(gorseller):
		ham_url = gorsel["file_url"]
		kayit: dict[str, Any] = {
			"file_url": ham_url,
			"alt_text": gorsel.get("alt_text") or "",
			"primary": bool(gorsel.get("primary")),
			"asset": "",
			"manifest": None,
		}
		if not acik:
			govde["images"].append(kayit)
			continue

		varlik = _varlik_sec(varliklar.get(ham_url) or {}, sahip)
		if not varlik:
			govde["images"].append(kayit)
			continue

		kayit["asset"] = varlik["name"]
		servis_edilir, gate_elenen = _servis_edilebilir(turevler.get(varlik["name"]) or [])
		elenen += gate_elenen
		if not servis_edilir:
			govde["images"].append(kayit)
			continue

		man = _render_manifest(
			slot_key,
			ham_url,
			servis_edilir,
			alt=kayit["alt_text"],
			is_lcp=(sira == 0),
			version_meta=(zengin or {}).get(varlik["name"]),
		)
		if man is None:
			govde["images"].append(kayit)
			continue

		kayit["manifest"] = man
		govde["images"].append(kayit)
		for tur in servis_edilir:
			duz.append(
				{
					"source": ham_url,
					"asset": varlik["name"],
					"profile": tur["profile"],
					"url": tur["file_url"],
					"width": int(tur.get("width") or 0),
					"height": int(tur.get("height") or 0),
					"format": tur["format"],
					"bytes": int(tur.get("bytes") or 0),
				}
			)

	govde["renditions"] = duz
	govde["suppressed"] = elenen
	# Türev varsa `<img src>` de türevden gelmeli; yoksa ham dosya kalır.
	ilk = next((k for k in govde["images"] if k.get("manifest")), None)
	if ilk:
		govde["fallback"] = ilk["manifest"].get("src") or govde["fallback"]
	return govde


# ── W7: video manifesti ─────────────────────────────────────────────────


def _video_manifest_batch_icin(
	ilanlar: Sequence[str], slot_key: str, acik: bool
) -> dict[str, dict[str, Any]]:
	"""N ilan → N VİDEO manifesti. Toplam 4 sorgu; ilan sayısından bağımsız.

	Görsel yoluyla aynı iskelet (görünürlük → varlık → türev), iki fark:
	  1. Kaynak `Listing Image` galerisi değil `Listing.video_url` kolonudur
	     (`product-video.json` `bound_to`). Alan `Data`: yerel dosya adresi de
	     YouTube adresi de taşıyabilir; yalnız yerel adres varlığa çözülür.
	  2. Gövde `srcset` merdiveni değil `MediaVideo.vue`'nun beklediği tek
	     `video` bloğunu taşır: `{src, hlsSrc, poster, width, height, lqip,
	     duration_s, type}` (rapor 81 §7 eşleşme tablosu satır satır).
	"""
	satirlar = _gorunur_ilanlar(ilanlar)
	if not satirlar:
		return {}

	varliklar: dict[str, dict[str, Any]] = {}
	turevler: dict[str, list[dict[str, Any]]] = {}
	surumler: dict[str, dict[str, Any]] = {}
	if acik:
		adresler = sorted({u for u in (_yerel_url(s.get("video_url")) for s in satirlar) if u})
		varliklar = _varliklari_getir(adresler, slot_key)
		varlik_adlari = sorted({v["name"] for grup in varliklar.values() for v in grup.values()})
		aktif_surumler = {
			v["name"]: str(v.get("active_version") or "")
			for grup in varliklar.values()
			for v in grup.values()
		}
		turevler = _turevleri_getir(varlik_adlari, aktif_surumler)
		surumler = _video_surumleri(varlik_adlari, aktif_surumler)

	cikti: dict[str, dict[str, Any]] = {}
	for satir in satirlar:
		cikti[satir["name"]] = _tek_video_govdesi(satir, slot_key, varliklar, turevler, surumler, acik)
	return cikti


def _tek_video_govdesi(
	ilan: dict[str, Any],
	slot_key: str,
	varliklar: dict[str, dict[str, Any]],
	turevler: dict[str, list[dict[str, Any]]],
	surumler: dict[str, dict[str, Any]],
	acik: bool,
) -> dict[str, Any]:
	"""Bir ilanın video manifest gövdesi.

	`fallback` HAM yerel adresi taşır (görsel yoluyla aynı sözleşme: bayrak
	kapalıyken bile bugünkü `videoUrl` davranışı manifestten okunabilir).
	Dış adres (YouTube/Vimeo) manifeste GİRMEZ — o adresin türevi bizde yok
	ve olamaz; vitrin onu bugünkü gibi `get_listing_detail.videoUrl`dan alır.
	"""
	govde = _bos_manifest(ilan["name"], slot_key, acik)
	govde["video"] = None
	yerel = _yerel_url(ilan.get("video_url"))
	govde["fallback"] = yerel

	if not (acik and yerel):
		return govde

	varlik = _varlik_sec(varliklar.get(yerel) or {}, str(ilan.get("seller_profile") or ""))
	if not varlik:
		return govde

	servis_edilir, elenen = _servis_edilebilir(turevler.get(varlik["name"]) or [])
	govde["suppressed"] = elenen
	profile_gore = {str(t.get("profile") or ""): t for t in servis_edilir}
	birincil = profile_gore.get(VIDEO_PRIMARY_PROFILE)
	poster_fallback = profile_gore.get(VIDEO_POSTER_PROFILE)
	poster_turevleri = [t for t in servis_edilir if str(t.get("profile") or "").startswith("poster_")]
	# Crop intent yalnız slot poster profillerinde uygulanır; bu yüzden profil
	# merdiveni varsa ham/base posteri değil en geniş WebP basamağını seç.
	poster = (
		max(
			poster_turevleri,
			key=lambda t: (
				int(t.get("width") or 0),
				1 if str(t.get("format") or "").lower() == "webp" else 0,
			),
		)
		if poster_turevleri
		else poster_fallback
	)
	hls = profile_gore.get(VIDEO_HLS_PROFILE)
	onizleme = profile_gore.get(VIDEO_PREVIEW_PROFILE)
	surum = surumler.get(varlik["name"]) or {}

	# Ölçü önceliği: sürüm kaydı (teslim künyesi) → birincil türev → poster.
	# Poster en sonda: `scale='min(1280,iw)'` oranı korur, yani ölçüsü CLS
	# için doğru ORANI verir — passthrough'ta elde başka ölçü kaynağı yok.
	genislik = (
		int(surum.get("width") or 0)
		or int((birincil or {}).get("width") or 0)
		or int((poster or {}).get("width") or 0)
	)
	yukseklik = (
		int(surum.get("height") or 0)
		or int((birincil or {}).get("height") or 0)
		or int((poster or {}).get("height") or 0)
	)

	govde["video"] = {
		"asset": varlik["name"],
		# PASSTHROUGH'ta birincil türev YOKTUR (kaynak zaten teslim edilebilir);
		# `src` ham dosyadır — rapor 81 §7'deki eşleşme tablosunun ilk satırı.
		"src": (birincil or {}).get("file_url") or yerel,
		"type": VIDEO_MIME,
		"hlsSrc": (hls or {}).get("file_url") or "",
		"poster": (poster or {}).get("file_url") or "",
		"posterSrcset": [
			{
				"url": t.get("file_url") or "",
				"width": int(t.get("width") or 0),
				"height": int(t.get("height") or 0),
				"format": str(t.get("format") or ""),
				"profile": str(t.get("profile") or ""),
			}
			for t in sorted(
				poster_turevleri,
				key=lambda x: (int(x.get("width") or 0), str(x.get("format") or "")),
			)
		],
		# W8 — hareketli önizleme klibi (3-6 sn, sessiz, ≤1 MB). Üretim
		# `pipeline_bridge._produce_video_preview`; klip best-effort olduğundan
		# (kapıdan düşebilir, eski varlıklarda hiç yok) alan boş kalabilir.
		"previewSrc": (onizleme or {}).get("file_url") or "",
		"width": genislik,
		"height": yukseklik,
		"duration_s": float(surum.get("duration_s") or 0.0),
		"lqip": str(surum.get("lqip_data_uri") or "") or str(surum.get("dominant_color") or ""),
		"reducedMotion": {
			"poster": (poster or {}).get("file_url") or "",
			"src": "",
			"hlsSrc": "",
			"previewSrc": "",
		},
	}
	govde["renditions"] = [
		{
			"source": yerel,
			"asset": varlik["name"],
			"profile": t["profile"],
			"url": t["file_url"],
			"width": int(t.get("width") or 0),
			"height": int(t.get("height") or 0),
			"format": t["format"],
			"bytes": int(t.get("bytes") or 0),
		}
		for t in servis_edilir
	]
	if birincil:
		govde["fallback"] = birincil.get("file_url") or yerel
	return govde


def _video_surumleri(
	varlik_adlari: Sequence[str], aktif_surumler: Mapping[str, str]
) -> dict[str, dict[str, Any]]:
	"""Varlık → yalnız ``active_version`` künyesi. TEK sorgu.

	Yeni crop/reprocess sürümü hazırlanırken daha yeni ``creation`` taşıyabilir;
	aktiflik filtresiz okuma onu tam promote öncesi görünür kılardı.
	"""
	if not varlik_adlari:
		return {}
	adlar = [str(aktif_surumler.get(a) or "") for a in varlik_adlari]
	adlar = [a for a in adlar if a]
	if not adlar:
		return {}
	cikti: dict[str, dict[str, Any]] = {}
	for satir in frappe.get_all(
		"Media Version",
		filters={"name": ["in", adlar]},
		fields=["name", "asset", "width", "height", "duration_s", "lqip_data_uri", "dominant_color"],
		order_by="creation desc",
		limit_page_length=0,
		ignore_permissions=True,
	):
		cikti.setdefault(satir["asset"], satir)
	return cikti


def video_bloklari(ilanlar: Sequence[str]) -> dict[str, dict[str, Any] | None]:
	"""İlan(lar) → manifest `video` bloğu. LISTING API'nin alt-katman girişi (W8).

	`api/listing.py::get_listing_detail` video alanlarını (poster/hlsSrc/
	previewSrc) manifest mantığını KOPYALAMADAN buradan okur. Görünürlük,
	bayrak ve sızıntı kuralları `_video_manifest_batch_icin`in kendisinde —
	burada ek kural YOK: bayrak kapalıysa/ilan görünmezse/türev yoksa blok
	`None` döner ve çağıranın bugünkü ham `videoUrl` davranışı değişmez.
	Whitelist DEĞİL: HTTP yüzü `get_manifest`; bu, süreç-içi çağrı içindir.
	"""
	adlar = [str(a) for a in ilanlar if a]
	if not adlar:
		return {}
	slot_key = next(iter(VIDEO_SLOTS))
	govdeler = _video_manifest_batch_icin(adlar, slot_key, _bayrak_acik())
	return {ad: (govdeler.get(ad) or {}).get("video") for ad in adlar}


def _render_manifest(
	slot_key: str,
	ham_url: str,
	servis_edilir: list[dict[str, Any]],
	*,
	alt: str,
	is_lcp: bool,
	version_meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
	"""`ManifestBuilder`ı DB'den gelen adreslerle çalıştır.

	`url_for` kapaması bu fonksiyonun tek özgün işi: kütüphane varyant adresini
	addan türetirken (`<hash>__w384.webp`) biz `Media Rendition.file_url`
	kolonundaki gerçek adresi veriyoruz. Modül başlığı §3'e bakın.
	"""
	adres = {(t["profile"], str(t["format"]).lower()): t["file_url"] for t in servis_edilir}
	olculer = {
		(t["profile"], str(t["format"]).lower()): (int(t.get("width") or 0), int(t.get("height") or 0))
		for t in servis_edilir
	}

	def url_for(ref: ObjectRef) -> str:
		anahtar = _profil_ve_bicim(ref)
		return adres.get(anahtar) or ref.url

	base = _base_ref(ham_url)
	if base is None:
		return None

	builder = _CiftSuzgecliBuilder(url_for=url_for, servis_edilir=frozenset(adres))
	try:
		man = builder.build_image(
			slot_key,
			base,
			alt=alt,
			available_profiles=tuple({t["profile"] for t in servis_edilir}),
			is_lcp_candidate=is_lcp,
			intrinsic=_intrinsic(olculer),
			version_meta=version_meta,
		)
	except Exception:
		# `NoProfileAvailable` (slot politikası yok / üretilmiş profil yok) ve
		# politika ayrıştırma hataları buraya düşer. Görsel ham `src` ile basılır.
		frappe.log_error(
			title="media manifest",
			message=f"build_image({slot_key!r}, {ham_url!r}) başarısız\n\n{frappe.get_traceback()}",
		)
		return None

	sozluk = man.to_dict()
	# Yalnız GERÇEKTEN üretilmiş varyantlar dışarı çıkar. `available=False`
	# olanların adresi sözleşme adından türetilmiştir ve diskte yoktur;
	# yanıta koymak, birinin onu `srcset`e yazma riskini taşır.
	sozluk["variants"] = [
		{
			"profile": v.profile,
			"url": v.url,
			"width": v.width,
			# Yükseklik politikada çoğu profil için yazılı değil (0); gerçek
			# değer üretilmiş dosyadadır. DB varsa o kazanır.
			"height": olculer.get((v.profile, v.fmt.lower()), (0, v.height))[1] or v.height,
			"format": v.fmt,
			"type": v.mime,
		}
		for v in man.variants
		if v.available
	]
	# `man.extra["missing_profiles"]` üst sınıfın PROFİL bazlı süzgecinden kalır;
	# biz (profil, biçim) çiftine indirdiğimiz için yeniden hesaplanıyor.
	# "Eksik" = bu profilin HİÇBİR biçimi servis edilemiyor.
	uygun_profiller = {v.profile for v in man.variants if v.available}
	sozluk["missing_profiles"] = sorted({v.profile for v in man.variants} - uygun_profiller)
	sozluk["missing_variants"] = sorted(
		f"{v.profile}.{v.fmt}" for v in man.variants if not v.available and v.profile in uygun_profiller
	)
	sozluk["sizes_source"] = man.extra.get("sizes_source") or ""
	return sozluk


def _profil_ve_bicim(ref: ObjectRef) -> tuple[str, str]:
	"""Türev anahtarından `(profil, biçim)` çıkar — `<gövde>__w384.webp`."""
	from tradehub_core.media.pipeline.contracts.delivery import VARIANT_SEPARATOR

	govde, uzanti = os.path.splitext(ref.key.name)
	_, _, profil = govde.rpartition(VARIANT_SEPARATOR)
	return profil, uzanti.lstrip(".").lower()


def _base_ref(file_url: str) -> ObjectRef | None:
	"""`file_url` → `ObjectRef`. Shard'sız eski yollar için sentetik anahtar.

	Bugünkü dosyaların çoğu içerik-adresli değil (`/files/067-1 GRİ.jpg`) ve
	`ref_from_url` onları reddediyor. Sentetik anahtar yalnız `derivative_key`
	adlandırmasını besler; ÜRETİLMİŞ varyantların adresi zaten `url_for` ile
	DB'den geliyor, üretilmemiş olanlar da yanıta hiç girmiyor — yani bu
	sentetik ad hiçbir yerde servis edilmez.
	"""
	try:
		return manifest_mod.ref_from_url(file_url)
	except ValueError:
		pass
	except Exception:
		frappe.log_error(
			title="media manifest",
			message=f"ref_from_url({file_url!r}) beklenmedik hata\n\n{frappe.get_traceback()}",
		)
		return None

	ad = os.path.basename((file_url or "").split("?")[0])
	if not ad:
		return None
	kapsam = SCOPE_PRIVATE if file_url.startswith(media_access.PRIVATE_PREFIX) else SCOPE_PUBLIC
	try:
		return ObjectRef(key=ObjectKey(shard=ad[:SHARD_LENGTH], name=ad), scope=kapsam)
	except ValueError:
		return None


def _intrinsic(olculer: dict[tuple[str, str], tuple[int, int]]) -> tuple[int, int]:
	"""CLS koruması için içsel ölçü — EN BÜYÜK türevin ölçüsü.

	Master ölçüsü `Media Asset`te tutulmuyor (A1a kapsamı dışıydı). En büyük
	türev oranı doğru verir; oran bilinmiyorsa (0,0) döner ve `RenderManifest`
	`aspect_ratio=0` yazar — sözleşme gereği çağıran sayı UYDURMAZ.
	"""
	adaylar = [wh for wh in olculer.values() if wh[0] > 0 and wh[1] > 0]
	if not adaylar:
		return (0, 0)
	return max(adaylar, key=lambda wh: wh[0])


def _servis_edilebilir(turevler: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
	"""Servis edilebilir türevler + fayda kapısında elenen sayısı."""
	uygun: list[dict[str, Any]] = []
	elenen = 0
	for tur in turevler:
		if not tur.get("file_url"):
			continue
		if not tur.get("benefit_gate_passed"):
			# "Türev kaynaktan yeterince küçük mü" — geçmeyen üretilir ama
			# SERVİS EDİLMEZ (Media Rendition alan açıklaması).
			elenen += 1
			continue
		uygun.append(tur)
	return uygun, elenen


def _varlik_sec(adaylar: dict[str, Any], seller_profile: str) -> dict[str, Any] | None:
	"""Aynı dosyayı paylaşan varlıklar arasından bu ilanın satıcısınınkini seç.

	Bir `File` birden çok `Media Asset`e hizmet edebilir (DocType açıklaması).
	Satıcı eşleşmesi olmadan başka bir kiracının varlık kaydı (ve türev
	adresleri) bu ilana bağlanabilirdi — kiracı sızıntısının tam tanımı.
	"""
	if not adaylar:
		return None
	if seller_profile and seller_profile in adaylar:
		return adaylar[seller_profile]
	# Sistem üretimi varlıklarda `owner_seller` boştur; onları herkes okur.
	return adaylar.get("") or None


# ── DB okumaları — her biri TEK sorgu ───────────────────────────────────


def _gorunur_ilanlar(ilanlar: Sequence[str]) -> list[dict[str, Any]]:
	"""Yalnız vitrinde görünen ilanlar. Görünmeyen sessizce düşer (404 değil).

	`frappe.get_all` bilinçli: uç `allow_guest` ve Guest rolünün `Listing`
	üzerinde read izni yok — `frappe.get_list` boş dönerdi ve tüm vitrin
	manifestsiz kalırdı. Görünürlük kararı bu yüzden burada AÇIKÇA veriliyor,
	izin motoruna devredilmiyor: kanonik `storefront_visible = 1` yüklemi +
	ikinci katman olarak `status`. Yalnız `status` süzmek, satıcının vitrinden
	kaldırdığı (`is_visible = 0`, dolayısıyla `storefront_visible = 0`) ama
	hâlâ `Active` duran ilanın tüm galerisini misafire açıyordu.
	"""
	if not ilanlar:
		return []
	return frappe.get_all(
		"Listing",
		filters={
			"name": ["in", list(ilanlar)],
			**VISIBLE_LISTING_FILTER,
			"status": ["in", list(STATUS_GUARD)],
		},
		# `video_url` W7'de eklendi: video slotu manifesti bu kolonu okur.
		# Görsel yolu alanı yok sayar — fazladan kolonun sorguya maliyeti yok.
		fields=["name", "seller_profile", "primary_image", "video_url"],
		limit_page_length=len(ilanlar),
		ignore_permissions=True,
	)


def _ilan_gorselleri(ilanlar: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
	"""İlan → sıralı görsel listesi. Galeri TEK sorguda okunur (N+1 yok).

	Sıra: önce `primary_image`, sonra `Listing Image.idx`. Birinci görsel LCP
	adayıdır; sırayı bozmak `fetchpriority=high`ı yanlış görsele verir.
	"""
	adlar = [i["name"] for i in ilanlar]
	galeri: dict[str, list[dict[str, Any]]] = {}
	if adlar:
		# Alt tablo; sahiplik üst dokümandan geliyor ve üst doküman zaten
		# görünürlük süzgecinden geçti — `ignore_permissions` bu yüzden güvenli.
		for satir in frappe.get_all(
			"Listing Image",
			filters={"parent": ["in", adlar], "parenttype": "Listing"},
			fields=["parent", "image", "alt_text", "idx"],
			order_by="parent asc, idx asc",
			limit_page_length=0,
			ignore_permissions=True,
		):
			galeri.setdefault(satir["parent"], []).append(satir)

	cikti: dict[str, list[dict[str, Any]]] = {}
	for ilan in ilanlar:
		sirali: list[dict[str, Any]] = []
		gorulen: set[str] = set()
		birincil = _yerel_url(ilan.get("primary_image"))
		if birincil:
			sirali.append({"file_url": birincil, "alt_text": "", "primary": True})
			gorulen.add(birincil)
		for satir in galeri.get(ilan["name"]) or []:
			url = _yerel_url(satir.get("image"))
			if not url or url in gorulen:
				continue
			gorulen.add(url)
			sirali.append({"file_url": url, "alt_text": satir.get("alt_text") or "", "primary": False})
		cikti[ilan["name"]] = sirali
	return cikti


def _varliklari_getir(file_urls: Sequence[str], slot_key: str) -> dict[str, dict[str, Any]]:
	"""`file_url` → {owner_seller: varlık}. `File` join'i TEK sorguda.

	`Media Asset.source_file` bir `File` Link'idir; ilan ise ham `file_url`
	taşır. Eşleştirme bu yüzden `File.file_url` üzerinden yapılır.
	"""
	if not file_urls:
		return {}

	# Sistem tablosu okuması: `Media Asset` kullanıcıya ait bir kayıt olsa da
	# burada kiracı süzgeci ÜST katmanda (`_varlik_sec`) ve ilan görünürlüğünde
	# uygulanıyor; `get_list` guest bağlamında hiçbir şey döndürmez.
	satirlar = frappe.db.sql(
		"""
		SELECT ma.name, ma.owner_seller, ma.slot_key, ma.state, ma.active_version, f.file_url
		FROM `tabMedia Asset` ma
		INNER JOIN `tabFile` f ON f.name = ma.source_file
		WHERE ma.slot_key = %(slot)s
		  AND ma.state = %(state)s
		  AND f.file_url IN %(urls)s
		""",
		{"slot": slot_key, "state": READY_STATE, "urls": tuple(file_urls)},
		as_dict=True,
	)

	cikti: dict[str, dict[str, Any]] = {}
	for satir in satirlar:
		cikti.setdefault(satir["file_url"], {})[str(satir.get("owner_seller") or "")] = satir
	return cikti


def _turevleri_getir(
	varlik_adlari: Sequence[str],
	aktif_surumler: Mapping[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
	"""Varlık → türev listesi. TEK sorgu; genişliğe göre artan."""
	if not varlik_adlari:
		return {}
	if aktif_surumler is None:
		aktif_surumler = {
			row["name"]: str(row.get("active_version") or "")
			for row in frappe.get_all(
				"Media Asset",
				filters={"name": ["in", list(varlik_adlari)]},
				fields=["name", "active_version"],
				limit_page_length=0,
			)
		}
	cikti: dict[str, list[dict[str, Any]]] = {}
	for satir in frappe.get_all(
		"Media Rendition",
		filters={"asset": ["in", list(varlik_adlari)]},
		fields=[
			"name",
			"asset",
			"version_hash",
			"profile",
			"width",
			"height",
			"format",
			"file_url",
			"bytes",
			"benefit_gate_passed",
		],
		order_by="asset asc, width asc",
		limit_page_length=0,
		ignore_permissions=True,
	):
		aktif = str(aktif_surumler.get(satir["asset"]) or "")
		satir_surum = str(satir.get("version_hash") or "")
		if (aktif and satir_surum != aktif) or (not aktif and satir_surum):
			continue
		cikti.setdefault(satir["asset"], []).append(satir)
	return cikti


def _ensure_lazy_renditions(varlik_adlari: Iterable[str]) -> None:
	"""Yetkilendirilmiş varlıkların lazy türevlerini ilk okumada üret.

	Köprü geç import edilir: manifest modülünün normal (cache-hit / bayrak
	kapalı) yoluna worker motoru bağımlılıklarını taşımayız. Her varlık bağımsız
	best-effort'tur; bir bozuk kaynak diğer manifestleri ve ham fallback'i
	engellemez. Tekilleştirme sıra korur ve aynı dosyanın galeri tekrarlarında
	köprüye ikinci kez girmez.
	"""
	adlar = tuple(dict.fromkeys(str(ad) for ad in varlik_adlari if ad))
	if not adlar:
		return
	from tradehub_core.media import pipeline_bridge

	for asset_name in adlar:
		try:
			pipeline_bridge.ensure_lazy_renditions(asset_name)
		except Exception:
			frappe.log_error(
				title="media manifest lazy rendition",
				message=f"{asset_name}\n\n{frappe.get_traceback()}",
			)


def _lazy_renditions_for_file_url(file_url: str) -> None:
	"""Yetkisi doğrulanmış private kaynak URL'sini lazy varlıklarına bağla.

	`get_signed_url` bu yardımcıyı yalnız `media_access` read kontrolünden sonra
	çağırır. Aynı fiziksel URL'nin mükerrer File satırları olabilir; varlık
	seçimi izin-süzgeçli `_dosya_varliklari` üzerinden yapıldığı için başka
	satıcının asset kimliği ne üretilir ne de yanıta sızar.
	"""
	try:
		dosyalar = frappe.get_all(
			"File",
			filters={"file_url": file_url},
			fields=["name", "file_url"],
			limit_page_length=0,
		)
		if not dosyalar:
			return
		kopru = _mukerrer_dosya_koprusu(dosyalar)
		varliklar = _dosya_varliklari(kopru)
		_ensure_lazy_renditions(v["name"] for grup in varliklar.values() for v in grup)
	except Exception:
		frappe.log_error(
			title="media signed url lazy rendition",
			message=f"{file_url}\n\n{frappe.get_traceback()}",
		)


# ── küçük yardımcılar ───────────────────────────────────────────────────


def _bayrak_acik() -> bool:
	"""Manifest ucu açık mı. Okuma hatası → KAPALI (fail-safe)."""
	try:
		return bool(pipeline_flags.is_enabled(FLAG_FIELD))
	except Exception:
		frappe.log_error(
			title="media manifest",
			message=f"bayrak okunamadı: {FLAG_FIELD}\n\n{frappe.get_traceback()}",
		)
		return False


def _bos_manifest(ilan: str, slot_key: str, acik: bool) -> dict[str, Any]:
	"""Bayrak kapalı / görünmez ilan / türev yok — hepsinin ortak yanıtı.

	Ayırt EDİLMEZ: "yayında değil" ile "türevi yok" arasındaki farkı guest'e
	söylemek yayın takvimini sızdırır (`pipeline/api/delivery.py` kural 2).

	`acik` parametre olarak alınır: bayrak uçta bir kez okunur, burada her
	çağrıda yeniden sorulmaz.

	Video slotunda gövde ek olarak `video: None` taşır — anahtar kümesi slot
	türüne göre SABİT kalmalı ki çağıran `"video" in yanit` ile tür ayrımı
	yapabilsin. Görsel slotlarının gövdesi (ve ETag'i) DEĞİŞMEDİ.
	"""
	govde: dict[str, Any] = {
		"listing": ilan,
		"slot": slot_key,
		"enabled": acik,
		"fallback": "",
		"renditions": [],
		"images": [],
		"suppressed": 0,
	}
	if slot_key in VIDEO_SLOTS:
		govde["video"] = None
	return govde


def _finalize(govde: dict[str, Any], if_none_match: str) -> dict[str, Any] | Response:
	"""İçerik-adresli ETag; gerçek başlıkta 304, eski parametrede kısa 200."""
	try:
		etag = env.etag_for(govde)
	except Exception:
		# ETag üretilemezse yanıt yine dönmeli — önbellek kaybı, hata değil.
		frappe.log_error(
			title="media manifest",
			message=f"etag üretilemedi\n\n{frappe.get_traceback()}",
		)
		return dict(govde, etag="", cache_control=CACHE_CONTROL)

	baslik_etagi = _istek_etagi()
	istemci = baslik_etagi or _temiz(if_none_match, 200)
	if istemci and env.etag_matches(etag, istemci):
		if baslik_etagi:
			return Response(
				status=304,
				headers={"ETag": etag, "Cache-Control": CACHE_CONTROL},
			)
		return {"not_modified": True, "etag": etag, "cache_control": CACHE_CONTROL}

	return dict(govde, etag=etag, cache_control=CACHE_CONTROL)


def _istek_etagi() -> str:
	"""HTTP `If-None-Match` başlığı; istek bağlamı yoksa boş."""
	try:
		if frappe.request is None:
			return ""
		return str(frappe.request.headers.get("If-None-Match") or "")
	except Exception:
		# `frappe.request` yalnız HTTP bağlamında var; test/kuyruk yolunda yok.
		return ""


def _listeyi_coz(ham: Any) -> list[str]:
	"""JSON dizisi ya da virgüllü dizge → tekilleştirilmiş ilan listesi.

	Sıra KORUNUR: `manifests` sözlüğü sırasız olsa da `skipped` listesinin
	hangi ilanların kırpıldığını doğru göstermesi sıraya bağlıdır.

	Çıktı `MAX_REQUEST_LISTINGS` ile SERT tavanlıdır: `MAX_BATCH_LISTINGS`
	yalnız DB'ye giden dilimi sınırlıyordu, ayrıştırma ve `skipped` yankısı
	sınırsızdı.
	"""
	if ham is None:
		return []
	parcalar: Iterable[Any]
	if isinstance(ham, (list, tuple)):
		parcalar = ham[:MAX_REQUEST_LISTINGS]
	else:
		# Ham dizge de kelepçelenir: tavanın üstündeki kısım hiç ayrıştırılmaz.
		# Kesilen JSON `parse_json`dan geçemez ve aşağıdaki virgüllü-liste
		# yoluna düşer — sonuç yine tavana kadar kırpılmış bir listedir.
		metin = str(ham).strip()[:MAX_INPUT_CHARS]
		if not metin:
			return []
		if metin.startswith("["):
			try:
				cozulen = frappe.parse_json(metin)
			except Exception:
				# Bozuk JSON'u hata yapmak yerine virgüllü liste gibi okuruz;
				# vitrin bir tırnak hatası yüzünden manifestsiz kalmamalı.
				cozulen = metin
			parcalar = cozulen if isinstance(cozulen, (list, tuple)) else str(cozulen).split(",")
		else:
			parcalar = metin.split(",")

	cikti: list[str] = []
	gorulen: set[str] = set()
	for parca in parcalar:
		if len(cikti) >= MAX_REQUEST_LISTINGS:
			break
		ad = _temiz(parca, 140)
		if ad and ad not in gorulen:
			gorulen.add(ad)
			cikti.append(ad)
	return cikti


def _yerel_url(deger: Any) -> str:
	"""Yalnız bu sitede duran dosya adresleri manifeste girer.

	Bugünkü verinin bir kısmı dış CDN adresi (`https://cdn.dummyjson.com/...`)
	taşıyor; onların türevi bizde yok ve olamaz. `..` içeren yol da reddedilir
	(`key_from_url` ile aynı savunma).
	"""
	url = str(deger or "").split("?")[0].strip()
	if not url or ".." in url:
		return ""
	if url.startswith("/files/") or url.startswith(media_access.PRIVATE_PREFIX):
		return url
	return ""


def _temiz(deger: Any, azami: int) -> str:
	"""Boşluk kırp, uzunluk sınırla. `str(None) == "None"` tuzağına düşmez."""
	if deger is None:
		return ""
	metin = str(deger).strip()
	return metin[:azami]


__all__ = [
	"CACHE_CONTROL",
	"DEFAULT_SLOT",
	"FILE_BATCH_ASSETS_PER_FILE",
	"FILE_BATCH_MAX",
	"FILE_BATCH_RENDITIONS_PER_FILE",
	"FLAG_FIELD",
	"MAX_BATCH_LISTINGS",
	"MAX_REQUEST_LISTINGS",
	"STATUS_GUARD",
	"VISIBLE_LISTING_FILTER",
	"get_manifest",
	"get_manifest_batch",
	"get_signed_url",
	"manifest_batch",
]
