"""Akış tipi medya kotaları — bant genişliği, dönüşüm, AI çağrısı (§18).

DEPOLAMA KOTASIYLA İLİŞKİ
-------------------------
`files.enforce_storage_quota` DURUM ölçer (`SUM(file_size)`); bu modül AKIŞ
ölçer. İkisi bilerek ayrı: depolamanın sayacı yok çünkü gerekmiyor, bunların
sayacı zorunlu çünkü olay geçtikten sonra hesaplanamıyor. Gerekçenin uzunu
`Media Usage Meter` docstring'inde.

LİMİT SEMANTİĞİ — `entitlement.core.within_quota` İLE AYNI
----------------------------------------------------------
    -1  sınırsız
     0  devre dışı (her istek reddedilir)
    >0  gerçek sınır
    None/tanımsız → UYGULANMAZ (fail-open)

Fail-open tercihi `check_media_storage_quota`'nınkiyle AYNI ve aynı gerekçeyle:
plan seed'i koşmamış bir kurulumda bütün satıcıların medyasını kapatmak,
kotasız bırakmaktan çok daha kötü bir arıza. Kapatma kararı ürün kararıdır ve
`0` yazarak açıkça verilir.

NEDEN SAYAÇ ARTIRIMI `frappe.db.sql` İLE
----------------------------------------
`get_doc` + `save` iki gidiş dönüş ve iki eşzamanlı istek arasında kayıp
güncelleme üretir (ikisi de 100 okur, ikisi de 101 yazar). `INSERT ... ON
DUPLICATE KEY UPDATE amount = amount + N` tek atomik ifade. Bant genişliği
sayacı istek başına artıyor; burada kayıp güncelleme kotayı fiilen
uygulanamaz kılardı.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

DOCTYPE: str = "Media Usage Meter"

METRIC_BANDWIDTH: str = "bandwidth_bytes"
METRIC_TRANSFORMATIONS: str = "transformations"
METRIC_AI: str = "ai_calls"

#: Ölçüm → `Subscription Plan.quota_limits` anahtarı.
#: Anahtar adları `quota.max_storage_mb` deseniyle AYNI biçimde: `quota.max_*`.
QUOTA_KEYS: dict[str, str] = {
	METRIC_BANDWIDTH: "quota.max_bandwidth_mb_per_month",
	METRIC_TRANSFORMATIONS: "quota.max_transformations_per_month",
	METRIC_AI: "quota.max_ai_calls_per_month",
}

#: Bant genişliği kotası MB cinsinden tanımlı, sayaç BAYT tutuyor.
#: Kota MB çünkü insan okuyacak (plan ekranı); sayaç bayt çünkü olay bayt
#: üretiyor ve MB'a yuvarlamak her istekte bilgi kaybı olurdu.
_MB: int = 1024 * 1024


def period_key(when=None) -> str:
	"""`YYYY-MM` — sayacın dönem anahtarı."""
	an = when or now_datetime()
	return f"{an.year:04d}-{an.month:02d}"


def _tablo_var() -> bool:
	return frappe.db.table_exists(DOCTYPE)


def record(store: str, metric: str, amount: float) -> None:
	"""Sayacı artır. Hiçbir hata çağıranı düşürmez.

	Best-effort BİLİNÇLİ: bu fonksiyon dosya servis etme yolunda çağrılıyor
	ve sayaç yazamamak, kullanıcıya dosyayı verememekten çok daha küçük bir
	sorun. Kotanın kendisi `check` ile ayrıca uygulanıyor.
	"""
	if not store or metric not in QUOTA_KEYS or amount is None:
		return
	try:
		miktar = float(amount)
	except (TypeError, ValueError):
		# Çağıran sayı olmayan bir miktar verdi. Sayaç best-effort; burada
		# patlamak dosya servisini düşürürdü (fonksiyonun sözleşmesi).
		frappe.log_error(
			title="media.meter sayısal olmayan miktar",
			message=f"store={store} metric={metric} amount={amount!r}",
		)
		return
	# NaN ve sonsuz sayaca yazılırsa toplam bir daha ASLA anlamlı olmaz —
	# `amount + inf` sonsuz kalır ve kota kalıcı olarak kapanır.
	if miktar != miktar or abs(miktar) == float("inf"):
		return
	if miktar <= 0 or not _tablo_var():
		return
	try:
		frappe.db.sql(
			"""insert into `tabMedia Usage Meter`
				(name, store, period_key, metric, amount, last_event_at, creation, modified, owner, modified_by)
			values (%(name)s, %(store)s, %(period)s, %(metric)s, %(amount)s, %(now)s, %(now)s, %(now)s,
				%(user)s, %(user)s)
			on duplicate key update
				amount = amount + %(amount)s,
				last_event_at = %(now)s,
				modified = %(now)s""",
			{
				# Ad deterministik: (mağaza, dönem, ölçüm) üçlüsü zaten
				# tekil olmak zorunda ve `ON DUPLICATE KEY` birincil anahtara
				# dayanıyor. Ayrı bir unique index kurmak yerine anahtarı
				# adın kendisi yapmak, yarış durumunu veritabanına çözdürüyor.
				"name": f"{store}::{period_key()}::{metric}"[:140],
				"store": store,
				"period": period_key(),
				"metric": metric,
				"amount": miktar,
				"now": now_datetime(),
				"user": frappe.session.user or "Administrator",
			},
		)
	except Exception:
		frappe.log_error(title="media.meter record failed", message=frappe.get_traceback())


def consumed(store: str, metric: str, when=None) -> float:
	"""Bu dönemde tüketilen miktar."""
	if not store or not _tablo_var():
		return 0.0
	deger = frappe.db.get_value(
		DOCTYPE, {"store": store, "period_key": period_key(when), "metric": metric}, "amount"
	)
	return float(deger or 0)


def limit_for(store: str, metric: str) -> float | None:
	"""Planın bu ölçüm için tanımladığı sınır — tanımsızsa `None`.

	Bant genişliğinde plan MB der, sayaç bayt tutar: dönüşüm BURADA, tek
	yerde yapılıyor. `check` ve `summary` aynı fonksiyondan okuyor ki
	ikisinde iki farklı birim kullanılmasın (bu tam olarak sessiz bir
	1.048.576 kat hatası üretirdi).
	"""
	anahtar = QUOTA_KEYS.get(metric)
	if not anahtar:
		return None
	try:
		from tradehub_core.entitlement import core as ent_core

		ham = ent_core.get_quota_limits(store).get(anahtar)
	except Exception:
		frappe.log_error(title="media.meter limit_for failed", message=frappe.get_traceback())
		return None
	if ham is None:
		return None
	try:
		deger = float(ham)
	except (TypeError, ValueError):
		# Plan JSON'una elle "5 GB" gibi bir metin yazılmış olabilir.
		# Sayıya çevrilemeyen limit UYGULANMAZ ve GÖRÜNÜR olur: sessizce 0
		# saymak bütün mağazanın işini durdururdu, sessizce sınırsız saymak
		# kotayı fiilen kaldırırdı. Üçüncü yol yok — bu yüzden log + None.
		frappe.log_error(
			title="media.meter sayısal olmayan kota",
			message=f"store={store} metric={metric} deger={ham!r}",
		)
		return None
	# NaN her karşılaştırmada False döner ve kota kapısını sessizce açardı.
	if deger != deger:
		return None
	if metric == METRIC_BANDWIDTH and deger > 0:
		return deger * _MB
	return deger


def check(store: str, metric: str, incoming: float = 0) -> dict:
	"""Bu tüketim kotayı aşar mı — karar + gerekçe.

	`throw` ETMEZ, karar döndürür: çağıranlar farklı yerlerde farklı şey
	yapmak zorunda. Türev üretimi kuyrukta koşuyor ve orada `throw` bir
	kullanıcıya değil log'a gider; bant genişliği kapısı ise HTTP yanıtı
	üretmek zorunda. Ortak karar burada, tepki çağıranda.
	"""
	sinir = limit_for(store, metric)
	kullanilan = consumed(store, metric)
	if sinir is None:
		return {"allowed": True, "reason": "unconfigured", "used": kullanilan, "limit": None}
	if sinir < 0:
		return {"allowed": True, "reason": "unlimited", "used": kullanilan, "limit": -1}
	if sinir == 0:
		return {"allowed": False, "reason": "disabled", "used": kullanilan, "limit": 0}
	try:
		gelen = float(incoming or 0)
	except (TypeError, ValueError):
		# Çağıran sayı olmayan bir "gelen miktar" verdiyse en güvenli
		# varsayım sıfırdır: kotayı yanlışlıkla kapatmak, sayamadığımız bir
		# isteği geçirmekten daha zararlı olurdu (fail-open sözleşmesi).
		gelen = 0.0
	if gelen != gelen:
		gelen = 0.0
	asar = (kullanilan + gelen) > sinir
	return {
		"allowed": not asar,
		"reason": "exceeded" if asar else "ok",
		"used": kullanilan,
		"limit": sinir,
	}


def summary(store: str) -> dict:
	"""Üç akış kotasının bu dönemki durumu — panel/`upload_limits` için."""
	return {
		metric: {
			**check(store, metric),
			"period": period_key(),
		}
		for metric in QUOTA_KEYS
	}
