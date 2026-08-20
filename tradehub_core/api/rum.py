"""T-123 — RUM (gerçek kullanıcı ölçümü) toplama ucu.

Zincir: istemci toplayıcı (storefront `src/lib/rum/`) → BU UÇ →
`Media RUM Sample` DocType → `rum.aggregate()`/`to_metrics()` → panel/alarm.
Uç tarifi `docs/reports/60-fe3-rum.md` §5'ten alındı; doğrulama çekirdeği
`media/pipeline/delivery/rum.py` (bu dosya onu DEĞİŞTİRMEZ, yalnız çağırır).

GÖVDE
-----
`Content-Type: text/plain;charset=UTF-8` + JSON gövde: `{"samples": [...]}`.
`text/plain` BİLİNÇLİ (rapor 60 §5.2): `application/json` "basit istek"
olmadığı için CORS ön-kontrolü tetikler ve sayfa kapanırken `sendBeacon`
ölçümü kaybederdi. Frappe `text/plain` gövdesini ayrıştırmaz; burada
`frappe.request.get_data()` ile elle okunur.

CSRF MUAFİYETİ — GEREKÇE (rapor 60 §2, §5.4)
--------------------------------------------
`navigator.sendBeacon` başlık GÖNDEREMEZ — `X-Frappe-CSRF-Token` eklenemez ve
istek `utils/api` benzeri bir fetch sarmalayıcısından geçirilemez (ayrı
tarayıcı API'si). Frappe'de CSRF denetimi (frappe/auth.py
`validate_csrf_token`) oturumda kayıtlı token YOKSA atlanır; misafir
oturumlarında kayıtlı CSRF tokeni bulunmadığı için misafir beacon'ları
framework tarafından doğal olarak muaftır — global `ignore_csrf` AÇILMADI.
Risk kabulü: bu uç yalnız YAZAR, hiçbir şey okumaz/değiştirmez ve gövdesi
14 alanlık kapalı bir şemadır (`additionalProperties: false`).
ÖLÇÜLMÜŞ SINIR: oturum AÇMIŞ bir kullanıcının beacon'ı CSRF tokeni
taşıyamadığı için framework tarafından 400 ile reddedilir ve o örneklem
kaybolur; istemci devresi 400'ü geçici sayar ve sessiz kalır. Storefront
trafiğinin misafir ağırlıklı olması nedeniyle kabul edildi.

GÜVENLİK DURUŞU
---------------
- Geçersiz örnek SESSİZCE düşürülür ve uç yine 200 döner: telemetri ucu bir
  şema keşif oraklına dönüşmesin diye hata ayrıntısı istemciye SIZDIRILMAZ
  (ret sebebi yalnız `media_rum_rejected_total` sayacına yazılır).
  `sendBeacon` yanıtı zaten okuyamaz (rapor 60 §5.3 madde 4).
- Tek bozuk örnek gövdeyi düşürmez: geçerliler yazılır, bozuklar sayaca
  gider (rapor 60 §5.3 madde 2).
- Hız sınırı ZORUNLU (rapor 60 §5.4): kimliksiz + CSRF'siz bir yazma ucu
  sınırsız bırakılırsa tabloyu şişirmeye açıktır. Depodaki mevcut desen
  kullanıldı: `tradehub_core.api.rate_limit` (misafir kovası istemci
  IP'sine bağlanır, IP saklanmadan — T9 düzeltmesi).
- Günlük kayıt tavanı: hız sınırı tek IP'yi frenler ama dağıtık trafiği
  frenlemez; `DAILY_SAMPLE_CAP` tablo büyümesini yapısal olarak sınırlar.
- Örneklem kararı SUNUCUDA YENİDEN VERİLMEZ (rapor 60 §5.3 madde 5): karar
  istemcide verildi ve `sample_rate` kayda yazıldı; ikinci bir kapı
  `estimated_population` (1/oran toplamı) hesabını bozardı.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import add_days, add_to_date, cint, now_datetime, today

from tradehub_core.api.rate_limit import rate_limit
from tradehub_core.media.pipeline.delivery import rum

DOCTYPE: str = "Media RUM Sample"

#: Tek gövdede işlenen en fazla örnek — istemci sınırı MAX_BATCH=20 ile aynı
#: (rapor 60 §5.2). Fazlası sessizce düşürülür: istemcimiz zaten 20'de
#: keser, 20'den fazlası ancak elle kurcalanmış bir gövdedir.
MAX_BATCH: int = 20

#: Gövde boyutu tavanı (rapor 60 §5.4): 20 örnek × ~250 bayt tavanın çok
#: altında; 16 KB üstü gövde ancak kötü niyet ya da hatadır.
MAX_BODY_BYTES: int = 16 * 1024

#: Hız sınırı penceresi (rapor 60 §5.4: "IP başına dakikalık sınır").
#: Bir sayfa yüklemesi en çok 1-2 beacon üretir (kuyruk, sayfa gizlenince
#: boşalır); dakikada 30 gövde tek bir gerçek kullanıcının çok üstündedir.
RATE_LIMIT_MAX_CALLS: int = 30
RATE_LIMIT_WINDOW_SECONDS: int = 60

#: Günlük kayıt tavanı varsayılanı — `site_config.rum_daily_sample_cap` ile
#: ezilebilir. ÖLÇÜLMEDİ: gerçek trafik hacmi bilinmiyor (uç bu görevle
#: açılıyor); 50k/gün, %10 örneklemde ~125k sayfa yüklemesi/gün demektir ve
#: ilk gerçek veriden sonra yeniden değerlendirilmelidir.
DEFAULT_DAILY_SAMPLE_CAP: int = 50_000

#: Ham örneklemin saklama süresi — rum.DOCTYPE_DESIGN kararı (30 gün, KVKK
#: m.4/2-d gerekçesiyle). Buradan okumak, iki dosyanın sessizce ayrışmasını
#: engeller.
RETENTION_DAYS: int = cint(rum.DOCTYPE_DESIGN["retention_days"])

_QUOTA_TTL_SECONDS: int = 2 * 86_400  # gün dönümünde eski anahtar kendiliğinden ölsün


def _salt() -> str:
	"""`token_hash` tuzu — YAPILANDIRMADAN gelir ve asla dışarı çıkmaz.

	Öncelik `site_config.rum_token_salt`; yoksa sitenin `encryption_key`'i
	kullanılır (her sitede zorunlu olarak var). Tuz sabit kalmalı: aynı
	oturumun örnekleri aynı `session_bucket`'ta gruplansın diye.
	"""
	return str(frappe.conf.get("rum_token_salt") or frappe.conf.get("encryption_key") or "")


def _daily_cap() -> int:
	return cint(frappe.conf.get("rum_daily_sample_cap")) or DEFAULT_DAILY_SAMPLE_CAP


def _quota_key() -> str:
	return f"rum:daily:{today()}"


def _quota_used() -> int:
	try:
		return cint(frappe.cache().get_value(_quota_key()))
	except Exception:
		# Redis erişilemezse kota SAYILAMAZ; hız sınırıyla aynı takas
		# (api/rate_limit.py F-004): fail-open, sistemi kilitleme.
		frappe.log_error(title="rum.collect: günlük kota okunamadı", message=_quota_key())
		return 0


def _quota_add(n: int) -> None:
	"""Günlük sayacı artır. Oku-yaz yarışı OLABİLİR — bu bir yumuşak tavandır:

	amaç kayıt-hassas bir kota değil, tablonun sınırsız büyümemesi. Frappe
	`RedisWrapper.set_value` var olan anahtarı ezmediği için delete+set
	deseni kullanılır (api/rate_limit.py'deki ölçülmüş not ile aynı).
	"""
	if n <= 0:
		return
	try:
		key = _quota_key()
		cache = frappe.cache()
		current = cint(cache.get_value(key))
		cache.delete_value(key)
		cache.set_value(key, current + n, expires_in_sec=_QUOTA_TTL_SECONDS)
	except Exception:
		frappe.log_error(title="rum.collect: günlük kota yazılamadı", message=_quota_key())


def _record_rejection(err: BaseException) -> None:
	"""Ret sebebini `media_rum_rejected_total` sayacına yaz — asla fırlatma.

	Sayaç yazımı telemetri ucunu 500'e düşürmemeli: "veri geldi ama
	işleyemedik" bilgisini kaybetmek, isteği kaybetmekten iyidir.
	"""
	try:
		rum.record_rejection(err)
	except Exception:
		frappe.log_error(title="rum.collect: ret sayacı yazılamadı", message=repr(err))


def _raw_body() -> str:
	"""İstek gövdesini ham metin olarak oku (Content-Type'tan bağımsız)."""
	req = getattr(frappe.local, "request", None)
	if req is None or not hasattr(req, "get_data"):
		return ""
	try:
		return req.get_data(as_text=True) or ""
	except Exception:
		# Bozuk transfer/encoding — telemetri için istek düşer, sayfa düşmez.
		frappe.log_error(title="rum.collect: gövde okunamadı")
		return ""


def _parse_samples(text: str) -> list[Any]:
	"""Gövdeyi çöz; biçimsizse `RumError` fırlat (sebep: malformed_body)."""
	if not text:
		raise rum.RumError("Boş gövde", rum.SEBEP_GOVDE)
	if len(text.encode("utf-8", errors="replace")) > MAX_BODY_BYTES:
		raise rum.RumError(f"Gövde {MAX_BODY_BYTES} baytı aşıyor", rum.SEBEP_GOVDE)
	try:
		data = json.loads(text)
	except ValueError:
		raise rum.RumError("Gövde JSON değil", rum.SEBEP_GOVDE)
	if not isinstance(data, dict) or not isinstance(data.get("samples"), list):
		raise rum.RumError("Gövde {'samples': [...]} biçiminde olmalı", rum.SEBEP_GOVDE)
	return data["samples"]


def _ingest(text: str) -> dict[str, int]:
	"""Gövdeyi doğrula ve geçerli örnekleri yaz. HTTP kaygısı taşımaz.

	Dönen sayılar yalnız test/iç kullanım içindir — HTTP yanıtına
	YAZILMAZLAR (hata ayrıntısı sızdırmama kararı, modül başlığı).
	"""
	kabul = ret = kota_dusen = 0
	try:
		samples = _parse_samples(text)
	except rum.RumError as e:
		_record_rejection(e)
		return {"accepted": 0, "rejected": 1, "quota_dropped": 0}

	tuz = _salt()
	kalan_kota = _daily_cap() - _quota_used()
	for raw in samples[:MAX_BATCH]:
		try:
			sample = rum.validate(raw, salt=tuz)
		except rum.RumError as e:
			_record_rejection(e)
			ret += 1
			continue
		if kalan_kota <= 0:
			kota_dusen += 1
			continue
		doc = frappe.get_doc({"doctype": DOCTYPE, **sample.to_dict()})
		# ignore_permissions gerekçesi: uç misafire açık ve DocType'ta hiçbir
		# role create izni YOK (tek yazma yolu burası). Gövde kullanıcı girdisi
		# ama `rum.validate()` kapalı şemadan geçirdi: yazılan her alan
		# beyaz-listeli, kırpılmış ve PII'siz (rapor 60 §5.3 madde 3).
		doc.insert(ignore_permissions=True)
		kalan_kota -= 1
		kabul += 1

	_quota_add(kabul)
	return {"accepted": kabul, "rejected": ret, "quota_dropped": kota_dusen}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(
	max_calls=RATE_LIMIT_MAX_CALLS,
	window_seconds=RATE_LIMIT_WINDOW_SECONDS,
	per_user=True,
	scope="media_rum_collect",
)
def collect() -> dict[str, bool]:
	"""RUM örneklem gövdesini kabul et — `POST /api/method/tradehub_core.api.rum.collect`.

	Yanıt gövdesi bilinçli olarak BOŞA YAKIN: `sendBeacon` yanıtı okuyamaz
	(rapor 60 §5.3 madde 4) ve geçersiz örnek sayısını/nedenini istemciye
	söylemek yalnız şema keşfine yarar. Geçerli/geçersiz her gövde 200 alır;
	tek istisna hız sınırı (429 — istemci devresi 4xx'i geçici sayar).
	"""
	_ingest(_raw_body())
	return {"ok": True}


def purge_expired_samples() -> int:
	"""`RETENTION_DAYS`'ten (30 gün) eski ham örneklemleri sil; silinen sayıyı döndür.

	SCHEDULER KAYDI GEREKLİ — hooks.py bu görevde YASAK (orkestratör ekler):

		scheduler_events["daily"].append("tradehub_core.api.rum.purge_expired_samples")

	Scheduler kaydı eklenene kadar tablo yine sınırsız büyümez: `collect`
	içindeki günlük kayıt tavanı (`DAILY_SAMPLE_CAP`) büyümeyi
	gün-başına-tavan ile yapısal olarak sınırlar. `frappe.db.count/delete`
	kullanımı sistem işi (kullanıcı verisi sorgusu değil, telemetri bakım
	işi) — get_list'in permission katmanına ihtiyaç yok.
	"""
	sinir = add_days(now_datetime(), -RETENTION_DAYS)
	eski = cint(frappe.db.count(DOCTYPE, {"creation": ("<", sinir)}))
	if eski:
		frappe.db.delete(DOCTYPE, {"creation": ("<", sinir)})
	return eski


# ── T-133/T-124 — toplama koşucusu: ham örneklem → p75 metrikleri ──────
#
# `rum.aggregate()` + `rum.to_metrics()` bugüne kadar YAZILMIŞ ama hiçbir
# yerden ÇAĞRILMIYORDU (rapor 63 §6.3). Bu bölüm o iki fonksiyonu değiştirmeden
# çağıran koşucudur. Pencere sözleşmesi `to_metrics` docstring'inden geliyor:
# "Çağıran, her toplama penceresini BİR kez geçirmelidir" — `samples` bir
# SAYAÇTIR ve aynı pencere iki kez geçirilirse örnek sayısı katlanır.

#: İşlenen son pencere damgasının kalıcı anahtarı. `tabDefaultValue`
#: (`frappe.db.set_global`) SEÇİLDİ çünkü: (a) Settings alanı eklemek bu
#: görevde yasak, (b) Redis (`frappe.cache`) `clear-cache`/yeniden başlatmada
#: uçar ve uçtuğu anda aynı pencere ikinci kez işlenip SAYAÇLARI ŞİŞİRİRDİ —
#: idempotens iddiası kalıcı bir damga ister, DB'deki global bunu şemasız verir.
AGGREGATE_HIGH_WATER_KEY: str = "rum_aggregate_high_water"

#: Pencere sonunu "şimdi"den bu kadar geriye çek. `creation` uygulama saatiyle
#: yazılır ama satır COMMIT'i sorgudan sonra görünür olabilir; damganın hemen
#: kıyısındaki bir satırı sonsuza dek kaçırmamak için küçük bir emniyet payı.
AGGREGATE_SAFETY_LAG_SECONDS: int = 5

#: Toplamanın okuduğu alanlar — `rum.aggregate()`'in kullandıklarından İBARET
#: (metric/value p75 için, rating good_ratio için, sample_rate popülasyon
#: için, kalan ikisi `rum.METRIC_GROUP_BY` kovası). `fields=["*"]` bilinçli
#: olarak YOK: 15 alanlık satırdan 6'sı kullanılıyor.
_AGGREGATE_FIELDS: tuple[str, ...] = (
	"metric",
	"value",
	"route",
	"device_class",
	"rating",
	"sample_rate",
)


def _high_water() -> str:
	"""İşlenen son pencere damgası (yoksa boş dizge)."""
	return str(frappe.db.get_global(AGGREGATE_HIGH_WATER_KEY) or "")


def _row_to_sample(row: dict[str, Any]) -> rum.RumSample | None:
	"""DB satırını `RumSample`'a geri sar; toplanamayacak satırda `None`.

	Satırlar yazılırken `rum.validate()`ten geçti — burada yeniden doğrulama
	YAPILMAZ, yalnız `aggregate()`'i düşürebilecek iki şey savunulur:
	`sample_rate ∉ (0,1]` (1/oran bölmesi) ve sayı olmayan `value`.
	Okunmayan alanlar toplamada kullanılmadığı için varsayılanda bırakılır.
	"""
	try:
		oran = float(row["sample_rate"])
		deger = float(row["value"])
	except (KeyError, TypeError, ValueError):
		return None
	if not 0.0 < oran <= 1.0:
		return None
	return rum.RumSample(
		metric=str(row.get("metric") or ""),
		value=deger,
		route=str(row.get("route") or ""),
		device_class=str(row.get("device_class") or ""),
		viewport_bucket=0,
		dpr=1.0,
		connection="unknown",
		sample_rate=oran,
		rating=str(row.get("rating") or ""),
	)


def aggregate_samples(pencere_sonu: str | None = None, parcayi_yaz: bool = True) -> dict[str, Any]:
	"""Son penceredeki ham örneklemi p75 metriklerine işle — IDEMPOTENT.

	Pencere: `(işlenen son damga, pencere_sonu]`. Damga `tabDefaultValue`'da
	kalıcı tutulur ve yalnız satır işlendiğinde ilerler; pencereler ayrıktır,
	dolayısıyla her satır `to_metrics()` sayacına EN FAZLA bir kez girer
	(aynı pencere ikinci kez istenirse iş sıfırdır, sayaç şişmez).

	`pencere_sonu` normalde verilmez (şimdi − emniyet payı); test ve elle
	koşumda `"YYYY-MM-DD HH:MM:SS[.ffffff]"` biçiminde sabitlenebilir.
	`parcayi_yaz=False` yalnız test içindir: test sürecinin kayıt defteri
	paylaşılan parça dizinine yazılıp `/metrics`i kirletmesin.

	SCHEDULER KAYDI GEREKLİ — hooks.py bu görevde YASAK (orkestratör ekler):

		scheduler_events["hourly"].append("tradehub_core.api.rum.aggregate_samples")

	Eklenene kadar elle koşulabilir:

		bench --site <site> execute tradehub_core.api.rum.aggregate_samples

	`frappe.get_all` gerekçesi: sistem/telemetri işi — `Media RUM Sample`
	kullanıcı verisi değildir, hiçbir role create/write izni yoktur ve
	scheduler bağlamında oturum kullanıcısı da yoktur; permission katmanının
	(get_list) burada süzeceği bir şey yok.
	"""
	onceki = _high_water()
	son = str(pencere_sonu or add_to_date(now_datetime(), seconds=-AGGREGATE_SAFETY_LAG_SECONDS))
	sonuc: dict[str, Any] = {
		"pencere_baslangic": onceki,
		"pencere_sonu": son,
		"okunan": 0,
		"atlanan": 0,
		"seri": 0,
		"parca": None,
	}
	# Aynı (ya da daha eski) pencere ikinci kez istenirse İŞ YOK — sayaçlar
	# tam da bu erken çıkış sayesinde şişmez. Dizge karşılaştırması yeterli:
	# her iki damga da sabit "YYYY-MM-DD HH:MM:SS[.ffffff]" biçiminde.
	if onceki and son <= onceki:
		return sonuc

	filtreler: list[list[str]] = [["creation", "<=", son]]
	if onceki:
		filtreler.append(["creation", ">", onceki])
	satirlar = frappe.get_all(  # gerekçe: docstring — sistem işi, perm katmanı gereksiz
		DOCTYPE,
		filters=filtreler,
		fields=list(_AGGREGATE_FIELDS),
		limit_page_length=0,
	)
	if not satirlar:
		# Boş pencerede damga İLERLETİLMEZ: hiçbir satır işlenmedi, işlenmiş
		# gibi işaretlemenin tek etkisi bir sonraki sorguyu daraltmak olurdu
		# ve `creation` indeksli tabloda buna değmez.
		return sonuc

	ornekler: list[rum.RumSample] = []
	for satir in satirlar:
		ornek = _row_to_sample(satir)
		if ornek is None:
			# Yazım yolunda doğrulanmış satırın buraya düşmesi beklenmez;
			# düşerse sessiz kaybolmasın — ret sayacında görünsün.
			_record_rejection(rum.RumError("toplanamayan satır", rum.SEBEP_TOPLAMA))
			sonuc["atlanan"] += 1
			continue
		ornekler.append(ornek)
	sonuc["okunan"] = len(ornekler)

	if ornekler:
		toplamalar = rum.aggregate(ornekler, group_by=rum.METRIC_GROUP_BY)
		sonuc["seri"] = rum.to_metrics(toplamalar)

	# Damga, `to_metrics` BAŞARDIKTAN sonra ilerler: tersi sırada to_metrics
	# hatası pencereyi sonsuza dek kaybettirirdi. Bu sırada kalan tek pencere
	# riski "to_metrics yazdı, damga yazılamadı" (DB çökmesi) — o durumda tüm
	# iş zaten düşer ve tekrar koşum sayaçta bir kerelik fazlalık bırakabilir;
	# yumuşak tavanlı telemetri için kabul edilen takas.
	frappe.db.set_global(AGGREGATE_HIGH_WATER_KEY, son)

	if parcayi_yaz:
		# Geç içe aktarma: observability modülü exporter/instrument zincirini
		# yüklüyor; `collect` sıcak yolunun buna ihtiyacı yok. Parça yazılmazsa
		# bu sürecin sayaçları `/metrics` birleşimine hiç girmezdi (scheduler
		# ve `bench execute` süreçleri `after_request` kancasından geçmez).
		from tradehub_core.api import observability as obs

		sonuc["parca"] = obs.write_shard(force=True)
	return sonuc
