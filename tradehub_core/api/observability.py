# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""T-133 · Medya motoru gözlemlenebilirlik KABLOLAMASI — `/metrics` ucu.

Bu dosya YENİ ÖLÇÜM TANIMLAMAZ. Kütüphane tarafı (24 metrik, 10 ölçüm noktası,
çok süreçli toplayıcı, 16 alarm kuralı) `media/pipeline/observability/` altında
zaten yazılı ve 183 testle ölçülü. Eksik olan tek şey KABLOLAMAYDI:

  * `instrument.install()` çağıran satır YOKTU  → bugün hiçbir metrik yazılmıyordu
  * `/metrics` HTTP ucu YOKTU                   → yazılsa bile kimse okuyamazdı

`docs/reports/42-t133-gozlemlenebilirlik.md` §1.3'ün en dürüst cümlesi buydu:
"bugün hâlâ tek bir metrik toplanmıyor". Bu dosya o cümleyi kapatır.

ÜÇ SÜREÇ AİLESİ, ÜÇ AYRI SAYAÇ
==============================
`backend` (gunicorn), `queue-short`/`queue-long` (RQ) ve `scheduler` ayrı
süreçlerdir ve her biri KENDİ `metrics.REGISTRY` nesnesini taşır. `/metrics`
birinden servis edilse diğerlerinin sayısı görünmez — ve sayı makul göründüğü
için kimse sorgulamaz. `observability/exporter.py` bunu parça dosyalarıyla
çözüyor; buradaki iş yalnız o parçaların NEREYE yazılacağına karar vermek.

TOPLAMA DİZİNİ — neden `sites/` altında
=======================================
`exporter.DIZIN_DEGISKENI` (`MEDIA_METRICS_DIR`) tanımlıysa o kullanılır.
Tanımlı DEĞİLSE varsayılan `sites/<site>/private/media-metrics`. Gerekçe
ÖLÇÜLDÜ: `istoc-dev_sites` volume'ü backend, scheduler, queue-short ve
queue-long konteynerlerinin DÖRDÜNE birden `rw` bağlı (docker inspect,
2026-08-19). Yani çok süreçli toplama, `docker/` altında hiçbir şey
değiştirmeden bugün çalışır. Ortam değişkeni yolu bilerek KORUNDU: dağıtım
ayrı bir volume vermek isterse tek değişkenle alır.

Dizin `private/` altındadır ve `files/` DEĞİLDİR — nginx yalnız
`private/files`i (o da X-Accel + yetki ile) servis eder, bu dizine hiçbir
web yolu ulaşmaz.

UÇ NEDEN BEARER TOKEN İSTİYOR
=============================
Metrik gövdesi slot adlarını, ret sebeplerini, yükleme/hata sayılarını ve
depolama büyüklüğünü sızdırır. Kişisel veri değil ama iş verisi ve iç yapı
bilgisi — yani uç KORUMALI olmak zorunda.

Prometheus AYRI BİR SUNUCUDA koşuyor ve bir Frappe oturumu açamaz; dolayısıyla
`frappe.only_for` tek başına ucu kullanılamaz kılardı. Seçim:

  * **Bearer token** (seçilen) — `site_config.json`daki `media_metrics_token`.
    Prometheus `authorization.credentials_file` / `bearer_token_file` ile
    gönderir. Sır istek GÖVDESİNE değil BAŞLIĞA girer.
  * `?token=` sorgu parametresi (REDDEDİLDİ) — sorgu dizesi nginx access
    log'una, `Referer` başlığına ve tarayıcı geçmişine yazılır; sır, onu
    koruması gereken günlüğe sızardı.

Karşılaştırma `hmac.compare_digest` ile SABİT ZAMANLIDIR: `==` ilk farklı
bayta kadar çalışır ve süre farkı token'ı bayt bayt tahmin ettirir.

Sır ne log'a, ne hata mesajına, ne de yanıt gövdesine yazılır. `status()`
yalnız sırrın YAPILANDIRILMIŞ OLUP OLMADIĞINI söyler.

İkinci ve isteğe bağlı yol, oturum açmış bir `System Manager` /
`Media Superadmin` kullanıcısıdır — insan hata ayıklaması için. Bu yol
token yolunu ZAYIFLATMAZ; token yoksa oturumsuz istek yine 403 alır.
"""

from __future__ import annotations

import hmac
import os
import time
from typing import Any

import frappe
from frappe import _

from tradehub_core.media.pipeline.core import queues as media_queues
from tradehub_core.media.pipeline.observability import exporter, instrument
from tradehub_core.media.pipeline.observability import metrics as mm

#: `/metrics`i OTURUMLA okuyabilecek roller (insan / hata ayıklama yolu).
#: `_is_platform_full_access` BİLEREK kullanılmadı — Compliance Officer /
#: Platform Finance gibi geniş OKUMA rollerinin işletim metriklerinde işi yok
#: (Media Storage Settings emsali).
METRICS_ROLES: tuple = ("System Manager", "Media Superadmin")

#: Scrape sırrının `site_config.json`daki anahtarı. Sır DB'de değil site
#: yapılandırmasında: `Media Storage Settings` gibi bir DocType'a koymak, sırrı
#: bir DocPerm satırının arkasına saklamak olurdu — oysa bu sırrı okuyan taraf
#: hiç oturum açmıyor.
TOKEN_KEY: str = "media_metrics_token"

#: Kabul edilen tek şema. `?token=` sorgu parametresi BİLEREK desteklenmiyor:
#: sorgu dizesi nginx access log'una, `Referer` başlığına ve tarayıcı
#: geçmişine yazılır — yani sır, onu koruması gereken günlüğe sızar.
AUTH_SCHEME: str = "Bearer "

#: Scrape kimliği. Frappe'nin oturum modeli bir KULLANICI ister; token tek
#: başına oturum açamaz (aşağıdaki `authenticate_metrics_scrape` gerekçesi).
#: Bu kullanıcı bir Website User'dır ve TEK rolü aşağıdakidir — hiçbir DocType
#: üzerinde DocPerm satırı YOKTUR.
SCRAPER_USER: str = "media-metrics@tradehub.local"
SCRAPER_ROLE: str = "Media Metrics Scraper"

#: Parça dosyasının varsayılan dizini (site göreli).
SHARD_DIRNAME: str = "media-metrics"

#: İki parça yazımı arasındaki en kısa süre (sn). Her istekte kayıt defterini
#: JSON'a dökmek okuma yolunu gereksiz yavaşlatır; scrape aralığı (tipik 15-60
#: sn) altında bir tazelik zaten ölçülemez.
SHARD_MIN_INTERVAL_S: float = 15.0

#: Bu SÜREÇTE en son ne zaman parça yazıldı. Süreç yerel — paylaşılmaz.
_son_yazim: float = 0.0

#: Bu süreçte ölçüm noktaları bağlandı mı. `install()` zaten idempotent; bu
#: bayrak yalnız kilit alma maliyetini istek yolundan çıkarır.
_bagli: bool = False


def shard_dir() -> str:
	"""Parça dosyalarının dizini — ortam değişkeni ya da site altı varsayılan."""
	ortam = exporter.dizin()
	if ortam:
		return os.path.abspath(ortam)
	return os.path.abspath(frappe.get_site_path("private", SHARD_DIRNAME))


def ensure_instrumented() -> dict[str, Any]:
	"""Ölçüm noktalarını BU SÜREÇTE bağla. Idempotent, istisna fırlatmaz.

	`after_migrate` tek başına yetmez: migrate ayrı bir süreçtir ve
	sarmalayıcılar süreç belleğinde yaşar. Web ve worker süreçleri kendi
	kurulumlarını yapmak zorunda.
	"""
	global _bagli
	if _bagli:
		return {"already": True}
	rapor = instrument.install()
	_bagli = True
	return rapor.to_dict()


def install_instrumentation() -> dict[str, Any]:
	"""`after_migrate` kancası — kurulumu ÖLÇÜLEBİLİR biçimde raporlar.

	Migrate'i düşürmez: bağlanamayan nokta bir hata değildir (bkz.
	`instrument.install` docstring'i). Ama sessiz de kalmaz — kapsam 1.0'ın
	altına düşerse `Error Log`da görünür, çünkü "metrik var" ile "metrik
	doluyor" arasındaki farkı ölçen tek sayı budur.
	"""
	sonuc = ensure_instrumented()
	kapsam = sonuc.get("coverage")
	if kapsam is not None and kapsam < 1.0:
		frappe.log_error(
			title="media.observability.instrument",
			message=frappe.as_json(sonuc),
		)
	return sonuc


def write_shard(force: bool = False) -> str | None:
	"""Bu sürecin kayıt defterini paylaşılan dizine yaz. Hatayı YUTAR.

	Yutmanın gerekçesi dar: bu fonksiyon istek yolundan ve zamanlayıcıdan
	çağrılıyor. Metrik yazamamak, ölçtüğü işi düşürmek için bir sebep değil.
	Sessizliği telafi eden şey `durum()` ucudur: parça sayısı 0 ise ya da
	`oldest_shard_age_s` büyürse toplayıcı bunu görür.
	"""
	global _son_yazim
	simdi = time.time()
	if not force and (simdi - _son_yazim) < SHARD_MIN_INTERVAL_S:
		return None
	_son_yazim = simdi
	try:
		return exporter.write_shard(hedef_dizin=shard_dir())
	except exporter.ExportError:
		return None
	except OSError:
		return None


def after_request_write_shard(response=None, request=None) -> None:
	"""Frappe `after_request` kancası — ölçümü bu süreçten dışarı taşır.

	İsteği ASLA düşürmez ve yanıta dokunmaz. `response`/`request` imzası
	`frappe.app.run_after_request_hooks` tarafından dayatılıyor.
	"""
	try:
		ensure_instrumented()
		write_shard()
	except Exception:  # noqa: BLE001
		# Gözlemlenebilirlik kancası, gözlemlediği isteği düşüremez. Burada
		# `log_error` de çağrılmıyor: hata her istekte tekrarlanacaksa Error
		# Log'u tek başına doldurur ve asıl arızayı gömer.
		return


def _configured_token() -> str:
	"""`site_config.json`daki scrape sırrı. Yoksa boş dizge."""
	return str(frappe.conf.get(TOKEN_KEY) or "")


def _bearer_of_request() -> str:
	"""`Authorization: Bearer <token>` başlığından sırrı çıkar. Yoksa boş dizge."""
	istek = getattr(frappe.local, "request", None)
	ham = (istek.headers.get("Authorization") if istek is not None else None) or ""
	if not ham.startswith(AUTH_SCHEME):
		return ""
	return ham[len(AUTH_SCHEME) :].strip()


def _token_ok() -> bool:
	"""Sunulan sır, yapılandırılmış sırla EŞİT mi (sabit zamanlı).

	`hmac.compare_digest`: `==` karşılaştırması ilk farklı bayta kadar
	çalışır ve süre farkı token'ı bayt bayt tahmin ettirir. Sır
	yapılandırılmamışsa DAİMA `False` — yapılandırma eksikliği, ucu herkese
	açmanın gerekçesi olamaz (fail-closed).
	"""
	beklenen = _configured_token()
	sunulan = _bearer_of_request()
	if not beklenen or not sunulan:
		return False
	return hmac.compare_digest(beklenen, sunulan)


def authenticate_metrics_scrape() -> None:
	"""Frappe `auth_hooks` kancası — scrape sırrını OTURUMA çevirir.

	NEDEN GEREKİYOR — ÖLÇÜLDÜ (2026-08-19, canlı HTTP)
	--------------------------------------------------
	`Authorization` başlığı iki parçalıysa `frappe.auth.validate_auth`
	SONUNDA şunu yapıyor:

	    if len(authorization_header) == 2 and frappe.session.user in ("", "Guest"):
	        raise frappe.AuthenticationError

	Yani başlıkla gelen HİÇBİR istek, bir kullanıcı ATANMADAN uç fonksiyonuna
	ULAŞAMAZ — 401'de kesilir. Ölçüldü: doğru token ile de 401 alınıyordu.
	`validate_oauth` yalnız `OAuth Bearer Token` tablosuna bakar, `?token=`
	ise bilinçli olarak reddedildi (modül başlığı). Geriye Frappe'nin bu iş
	için tuttuğu tek genişleme noktası kalıyor: `auth_hooks`.

	NE KADAR YETKİ VERİYOR
	----------------------
	Kancanın atadığı kullanıcı bir **Website User**dır ve tek rolü
	`Media Metrics Scraper`dır; o rolün HİÇBİR DocType'ta DocPerm satırı
	yoktur. Yani token'ı ele geçiren biri "oturum açmış" olur ama hiçbir
	kayda erişemez. `/metrics` erişimi ayrıca uç içinde token'ın KENDİSİNE
	bağlıdır (`_token_ok`), role değil — yani bu rol tek başına metrik de
	okutmaz. İki kat, ve ikisi de aynı sırra bağlı.

	Kanca SESSİZDİR: eşleşmeyen başlıkta hiçbir şey yapmaz, istisna atmaz,
	log yazmaz. Aksi hâlde her API anahtarlı istek bu kancadan bir hata
	kaydı üretirdi.
	"""
	if not _token_ok():
		return
	if not frappe.db.exists("User", SCRAPER_USER):
		# Kullanıcı yoksa oturum açılmaz; uç 403 döner ve sebebi `status()`
		# üzerinden görülür. Var olmayan bir kullanıcıya `set_user` demek
		# isteği anlaşılmaz bir hatayla düşürürdü.
		return
	frappe.set_user(SCRAPER_USER)


def _session_role_ok() -> bool:
	"""Oturum açmış bir insan bu ucu okuyabilir mi (ikinci, İSTEĞE BAĞLI yol)."""
	kullanici = getattr(frappe.session, "user", None)
	if not kullanici or kullanici == "Guest":
		return False
	return bool(set(frappe.get_roles(kullanici)) & set(METRICS_ROLES))


def _authorize() -> str:
	"""İki yoldan biri geçmezse 403. Dönen değer, geçen YOLUN adıdır.

	Hata mesajı hangi yolun neden düştüğünü SÖYLEMEZ ve sırrın hiçbir parçasını
	taşımaz: "token yanlış" ile "token yok" ayrımı, saldırgana yapılandırma
	hakkında bilgi verir.
	"""
	if _token_ok():
		return "bearer"
	if _session_role_ok():
		return "session"
	# `frappe.throw` + PermissionError → HTTP 403. Guest için 401 dönmek
	# Frappe'nin oturum modeliyle çelişirdi; Prometheus ikisini de "scrape
	# başarısız" sayar ve `up` serisi 0'a düşer — sinyal aynı.
	raise frappe.PermissionError(_("Bu uç yetkilendirme gerektirir."))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def metrics() -> None:
	"""Prometheus text exposition format 0.0.4 — bütün süreçlerin BİRLEŞİMİ.

	`allow_guest=True` bir GEVŞETME DEĞİL: Prometheus AYRI BİR SUNUCUDA koşuyor
	ve Frappe oturumu açamaz, yani rol tabanlı kapı tek başına ucu kullanılamaz
	kılardı. Yetki kapısı `_authorize()`dedir ve oturumsuz istek için TEK yol
	`Authorization: Bearer <site_config.media_metrics_token>`tır. Sır
	yapılandırılmamışsa uç oturumsuz isteğe DAİMA 403 döner.

	Yanıt tipi `download` (yani `response.as_raw`) — ÖLÇÜLDÜ: `binary`
	`application/octet-stream` + `Content-Disposition: attachment` DAYATIR,
	ikisi de bir scrape ucu için yanlıştır. `as_raw` ise `content_type`ı ve
	`display_content_as`ı olduğu gibi kullanır. Tip adı `"raw"` DEĞİL
	`"download"`dır: `response_type_map` sözlüğünde anahtar budur ve `"raw"`
	yazmak `KeyError` ile HTTP 500 verir (ölçüldü).
	"""
	_authorize()
	ensure_instrumented()
	collect_queue_metrics()
	# Kendi parçamızı ZORLA yaz: bu isteği karşılayan süreç, kendi sayaçlarını
	# gövdeye dahil etmezse `/metrics` kendi ölçümünü eksik döndürürdü.
	write_shard(force=True)
	govde, ct = exporter.metrics_response(shard_dir())
	frappe.local.response.update(
		{
			"type": "download",
			"filename": "metrics",
			"filecontent": govde.encode("utf-8"),
			"content_type": _mimetype(ct),
			"display_content_as": "inline",
		}
	)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def status() -> dict[str, Any]:
	"""Toplayıcının künyesi — SAYIYLA, tahminle değil.

	Üç soruyu birden cevaplar: kaç süreç parça yazıyor, kaç seri toplanıyor,
	ölçüm noktalarının kaçı bağlı. `/metrics` boş dönerse arıza bu üç sayıdan
	birindedir. Yetki kapısı `/metrics` ile AYNI — künye de iç yapı bilgisidir.

	Sırrın KENDİSİ değil, YAPILANDIRILMIŞ OLUP OLMADIĞI raporlanır: bir
	operatör "token yok mu, yanlış mı" sorusunu sırrı ekrana basmadan
	cevaplayabilmeli.
	"""
	yol = _authorize()
	ensure_instrumented()
	kuyruklar = collect_queue_metrics()
	write_shard(force=True)
	return {
		"auth": yol,
		"token_configured": bool(_configured_token()),
		"exporter": exporter.durum(shard_dir()),
		"instrument": instrument.durum(),
		"coverage": instrument.metrik_kapsami(),
		"shard_dir": shard_dir(),
		"content_type": mm.REGISTRY.content_type(),
		"media_queues": kuyruklar,
	}


def collect_queue_metrics() -> list[dict[str, Any]]:
	"""Read the five canonical queues and publish low-cardinality gauges.

	A transport error is reported as ``available=False``; it is never converted
	to a fabricated zero because zero means the queue was reached and empty.
	"""
	from frappe.utils.background_jobs import get_queue

	statuses = ("queued", "running", "success", "failed", "dead")
	db_counts: dict[tuple[str, str], int] = {}
	if frappe.db.table_exists("Media Processing Job"):
		for queue, job_status, count in frappe.db.sql(
			"""SELECT queue, status, COUNT(*) FROM `tabMedia Processing Job`
			WHERE queue IN %(queues)s GROUP BY queue, status""",
			{"queues": media_queues.QUEUE_NAMES},
		):
			db_counts[(str(queue), str(job_status))] = int(count or 0)

	out: list[dict[str, Any]] = []
	for spec in media_queues.QUEUE_SPECS:
		row: dict[str, Any] = {
			"queue": spec.name,
			"timeout_seconds": spec.timeout_seconds,
			"max_attempts": spec.max_attempts,
			"available": False,
		}
		try:
			depth = int(get_queue(spec.name).count)
			mm.MEDIA_QUEUE_DEPTH.set(depth, queue=spec.name)
			row.update({"available": True, "depth": depth})
		except Exception as exc:  # noqa: BLE001 — metrics cannot break the scrape
			row["error"] = type(exc).__name__
		for job_status in statuses:
			count = db_counts.get((spec.name, job_status), 0)
			mm.MEDIA_QUEUE_JOBS.set(count, queue=spec.name, status=job_status)
			row[job_status] = count
		out.append(row)
	return out


@frappe.whitelist(methods=["GET"])
def media_queue_status() -> list[dict[str, Any]]:
	"""Authenticated operational JSON view of the same queue metrics."""
	_authorize()
	return collect_queue_metrics()


def write_shard_now() -> str | None:
	"""Kuyruğa atılan en küçük iş: bu worker sürecinin parçasını yaz.

	Ayrı bir fonksiyon olmasının sebebi ölçülebilir: `frappe.enqueue` işi
	HANGİ worker sürecinin alacağını seçmez, ama işi ALAN süreç kendi
	sayaçlarını dosyaya indirir. Yani bu iş yeterince sık koşarsa her worker
	süreci er ya da geç kendi parçasını yazar.
	"""
	ensure_instrumented()
	return write_shard(force=True)


def write_metrics_shard() -> dict[str, Any]:
	"""Zamanlayıcı işi — worker süreçlerinin sayaçlarını da dosyaya indirir.

	`after_request` yalnız WEB süreçlerini kapsar. Kuyruk süreçlerinde istek
	yoktur; oradaki sayaçlar bu iş koşmazsa `/metrics`e hiç ulaşmaz. Bu yüzden
	iş kendi parçasını yazmakla kalmaz, `short` ve `long` kuyruklarına birer
	yazma işi DAHA atar — zamanlayıcı işi tek bir kuyrukta koşar ve o kuyruğun
	worker'ı dışındaki süreçler aksi hâlde hiç görünmezdi.

	ÖLÇÜLMEDİ: `scheduler` sürecinin KENDİ kayıt defteri. O süreç yalnız iş
	kuyruğa atar, ölçülen medya modüllerinden hiçbirini çağırmaz — sayaçları
	boş olurdu. Parçasını yazmayan tek süreç ailesi budur ve bu bilinçlidir.

	Ölü süreçlerin parçaları da burada budanır (varsayılan 24 saat).
	"""
	ensure_instrumented()
	yol = write_shard(force=True)
	kuyruklar: list = []
	for kuyruk in ("short", "long", *media_queues.QUEUE_NAMES):
		try:
			frappe.enqueue(
				"tradehub_core.api.observability.write_shard_now",
				queue=kuyruk,
				# `job_id` ZORUNLU — `deduplicate=True` tek başına
				# `ValidationError` atıyor (ölçüldü: "`job_id` paramater is
				# required for deduplication"). Tekilleştirme burada gerçekten
				# gerekli: 5 dakikada bir kuyruğa iş atan bir ölçüm işi,
				# kuyruk tıkalıysa gerçek işin önünde birikir.
				job_id=f"media_metrics_shard_{kuyruk}",
				deduplicate=True,
			)
			kuyruklar.append(kuyruk)
		except Exception as hata:  # noqa: BLE001
			frappe.log_error(
				title="media.observability.enqueue_shard",
				message=f"{kuyruk}: {type(hata).__name__}: {hata}",
			)
	budanan = exporter.prune(shard_dir())
	return {"shard": yol, "queued": kuyruklar, "pruned": list(budanan)}


def _mimetype(content_type: str) -> str:
	"""`charset` parametresini AT — werkzeug onu kendisi ekler.

	ÖLÇÜLDÜ: `as_raw` değeri `response.mimetype`e atıyor ve werkzeug `text/*`
	için `; charset=utf-8` ekliyor; kayıt defterinin content_type'ı zaten
	charset taşıdığı için yanıt `charset=utf-8; charset=utf-8` ile çıkıyordu.
	Prometheus bunu tolere eder ama bozuk bir başlık, bozuk bir başlıktır.
	"""
	parcalar = [p.strip() for p in content_type.split(";")]
	return "; ".join(p for p in parcalar if p and not p.lower().startswith("charset="))
