# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Entegrasyon logu saklama politikası — süresi dolan kayıtları temizler (09-BE A).

POLİTİKA (Bora'nın kararı): varsayılan 90 gün, `Logistics Settings.
integration_log_retention_days` ile ayarlanabilir. 0 veya negatif değer
"saklama uygulanmasın" demektir ve iş hiçbir şey silmeden döner.

FEATURE FLAG KARARI — bu iş `logistics_enabled` KAPALIYKEN DE ÇALIŞIR:
	Bayrak yeni trafiği durdurur, geçmiş veriyi dondurmaz. Modül kapatıldığında
	temizlik de dursaydı, elde tutma süresi dolmuş kayıtlar süresiz saklanırdı —
	saklama politikası bir özellik değil, bir veri yükümlülüğüdür. (Aynı
	gerekçe `audit.tasks.run_data_retention_enforcement` ve
	`media.trash.purge_expired` işlerinde de geçerli: ikisi de bayrak
	arkasında değil.)

TAVAN NEDEN "KAYIT" DEĞİL "SÜRE":
	Eski sürüm koşum başına en fazla 5000 kayıt siliyor ve günde bir kez
	tetikleniyordu. Sevkiyat başına create + label + track döngüsü düşünülünce
	5000 mütevazı bir sayı: günde 5000'den fazla süresi dolan kayıt üreten bir
	sitede iş ASLA yetişmez ve tablo sınırsız büyür — üstelik SESSİZCE, çünkü
	tavana dayanmak bir hata değildi. Artık tavan `MAX_RUNTIME_SECONDS`'lık bir
	SÜRE bütçesi: iş bütçe dolana kadar chunk chunk siler, dolduğunda kalan işi
	`long` kuyruğuna yeniden kuyruklatır ve UYARI loglar. Dönüşteki `remaining`
	alanı geride kalınıp kalınmadığını ölçülebilir kılar.

KİLİT SÜRESİ: silme `DELETE_CHUNK_SIZE`'lık parçalara bölünüp her parçadan
sonra commit edilir. Bir milyon satırlık birikmiş log tek DELETE ile silinseydi
tablo dakikalarca kilitli kalır ve o sırada yazan her adapter bloke olurdu.

GÜVENLİ LOGLAMA DESENİ — `log.py`'DEN IMPORT EDİLİR, KOPYALANMAZ:
	Bu modül `frappe.get_traceback()`'i güvenli sarmalayıcının ARGÜMANI olarak
	çıplak çağırıyordu. O konumda koruma işlemez: `get_traceback()` fırlatırsa
	istisna sarmalayıcıya hiç girmeden dışarı sızar ve aynı `daily` listesindeki
	SONRAKİ scheduler işleri düşer (Frappe hepsini tek job içinde sırayla
	koşturur).

	Düzeltmenin İLK turu yalnız `traceback_text`'i import etti ve
	`_safe_log_error`'ı AYNEN yeniden yazdı — yani `log.py`'nin "kopyalanırsa
	biri düzeltilip diğeri unutulur" uyarısı, uyarıyı yazan turda gerçekleşti.
	Artık İKİSİ de `log.py`'den gelir; `carrier_integration_log.py` de aynı
	kaynağı kullanıyor, üç tüketici tek desende.
"""

from __future__ import annotations

import time

import frappe
from frappe.utils import add_to_date, now_datetime

from tradehub_core.logistics.integration.log import (
	INTEGRATION_LOG_DOCTYPE,
	safe_log_error,
	traceback_text,
)

#: Ayar okunamazsa / boşsa uygulanan varsayılan saklama süresi.
DEFAULT_RETENTION_DAYS: int = 90

#: Tek koşumun SÜRE bütçesi (saniye). Tavan budur — kayıt sayısı değil.
MAX_RUNTIME_SECONDS: float = 60.0

#: Mutlak güvenlik tavanı: bütçe ölçümü bozulsa bile koşum burada durur.
#: (Eski `MAX_DELETE_PER_RUN = 5000` anlamı değişti — artık günlük kota değil,
#: sonsuz döngü sigortası.)
MAX_DELETE_PER_RUN: int = 500_000

#: Tek DELETE ifadesine giren azami kayıt (kilit süresini kısa tutar).
DELETE_CHUNK_SIZE: int = 500

#: Saklama süresini taşıyan `Logistics Settings` alanı.
RETENTION_FIELD: str = "integration_log_retention_days"

#: Kalan iş yeniden kuyruklanırken kullanılan kuyruk ve iş adı.
_REQUEUE_QUEUE: str = "long"
_REQUEUE_METHOD: str = "tradehub_core.logistics.jobs.integration_log_retention.purge_expired_integration_logs"
_REQUEUE_JOB_ID: str = "tc:logistics:integration_log_retention"


def get_retention_days() -> int:
	"""Yürürlükteki saklama süresini gün cinsinden döndürür.

	`Logistics Settings` henüz migrate edilmemişse (yeni kurulum, patch öncesi)
	varsayılana düşer — bu iş ayar eksikliği yüzünden patlamamalı.
	"""
	try:
		configured = frappe.db.get_single_value("Logistics Settings", RETENTION_FIELD)
	except Exception:  # noqa: BLE001 — alan/DocType yoksa varsayılan geçerli
		safe_log_error(traceback_text(), "logistics.integration_log_retention.settings_read")
		return DEFAULT_RETENTION_DAYS

	if configured is None or configured == "":
		return DEFAULT_RETENTION_DAYS

	try:
		return int(configured)
	except (TypeError, ValueError):
		return DEFAULT_RETENTION_DAYS


def purge_expired_integration_logs(
	limit: int | None = None,
	*,
	time_budget: float | None = None,
	requeue: bool = True,
) -> dict[str, object]:
	"""Saklama süresi dolmuş entegrasyon logu kayıtlarını siler.

	Args:
		limit: Silinecek azami kayıt. None ise kayıt tavanı YOK; süre bütçesi
			ve `MAX_DELETE_PER_RUN` sigortası geçerlidir.
		time_budget: Süre bütçesi (sn). None ise `MAX_RUNTIME_SECONDS`.
		requeue: Bütçe dolduğunda kalan iş `long` kuyruğuna kuyruklansın mı.
			Testlerde ve elle koşumda kapatılabilir.

	Returns:
		{"deleted": int, "retention_days": int, "cutoff": str|None,
		 "skipped": str|None, "remaining": int, "budget_exhausted": bool,
		 "requeued": bool}
	"""
	retention_days = get_retention_days()
	if retention_days <= 0:
		# 0/negatif = saklama kapalı. Sessizce silmemek, "ayarı sıfırladım ama
		# veri yine gitti" sürprizini engeller.
		return _result(0, retention_days, None, skipped="retention_disabled")

	if limit is not None and int(limit) <= 0:
		return _result(0, retention_days, None, skipped="zero_limit")

	cutoff = add_to_date(now_datetime(), days=-retention_days)
	hard_cap = MAX_DELETE_PER_RUN if limit is None else min(int(limit), MAX_DELETE_PER_RUN)
	deadline = time.monotonic() + (MAX_RUNTIME_SECONDS if time_budget is None else float(time_budget))

	deleted = 0
	budget_exhausted = False

	while deleted < hard_cap:
		chunk_size = min(DELETE_CHUNK_SIZE, hard_cap - deleted)
		# get_all GEREKÇESİ: sistem bakım işi. Bu iş bir kullanıcı oturumunda
		# değil scheduler'da koşar; permission_query_conditions uygulansaydı
		# (Guest/None oturum) hiçbir kayıt dönmez ve saklama politikası sessizce
		# hiç işlemezdi.
		names: list[str] = frappe.get_all(
			INTEGRATION_LOG_DOCTYPE,
			filters={"creation": ["<", cutoff]},
			pluck="name",
			order_by="creation asc",
			limit=chunk_size,
		)
		if not names:
			break

		# frappe.db.delete GEREKÇESİ: DocType'ın child tablosu, dosya eki ve
		# on_trash mantığı YOK; doc-başına delete_doc yalnız meta yükleme
		# maliyeti eklerdi. Toplu DELETE aynı sonucu verir.
		frappe.db.delete(INTEGRATION_LOG_DOCTYPE, {"name": ["in", names]})
		frappe.db.commit()
		deleted += len(names)

		if len(names) < chunk_size:
			break
		if time.monotonic() >= deadline:
			budget_exhausted = True
			break

	remaining = _count_expired(cutoff)
	requeued = False
	# ÇAĞIRAN AÇIKÇA `limit` verdiyse kısmi koşum İSTENMİŞTİR — geride kalmak
	# arıza değil. Uyarı ve yeniden kuyruklama yalnız İŞİN KENDİ tavanına
	# (süre bütçesi ya da sonsuz döngü sigortası) dayandığında devreye girer.
	capped_by_job = budget_exhausted or (limit is None and deleted >= hard_cap)
	if remaining and capped_by_job:
		# SESSİZCE GERİ KALMAK EN KÖTÜSÜ: tavana dayanıldığında hem uyarı
		# loglanır hem kalan iş yeniden kuyruklanır. Aksi halde tablo her gün
		# biraz daha büyür ve bunu kimse fark etmez.
		safe_log_error(
			f"Entegrasyon logu temizliği tavana dayandı: silinen={deleted}, kalan={remaining}, "
			f"cutoff={cutoff}. Kalan iş `{_REQUEUE_QUEUE}` kuyruğuna alınıyor: {requeue}",
			"logistics.integration_log_retention.backlog",
		)
		if requeue:
			requeued = _enqueue_remaining()

	return _result(
		deleted,
		retention_days,
		cutoff,
		remaining=remaining,
		budget_exhausted=budget_exhausted,
		requeued=requeued,
	)


def _count_expired(cutoff: object) -> int:
	"""Süresi dolmuş kalan kayıt sayısı — geride kalma ölçülebilir olsun."""
	try:
		return int(frappe.db.count(INTEGRATION_LOG_DOCTYPE, {"creation": ["<", cutoff]}))
	except Exception:  # noqa: BLE001 — ölçüm başarısız olsa da silme geçerli
		safe_log_error(traceback_text(), "logistics.integration_log_retention.count")
		return 0


def _enqueue_remaining() -> bool:
	"""Kalan işi `long` kuyruğuna alır; kuyruk yoksa sessizce vazgeçer.

	`job_id` sabit: aynı iş üst üste kuyruklanıp worker'ı doldurmasın.
	"""
	try:
		frappe.enqueue(
			_REQUEUE_METHOD,
			queue=_REQUEUE_QUEUE,
			job_id=_REQUEUE_JOB_ID,
			deduplicate=True,
			timeout=1800,
		)
		return True
	except Exception:  # noqa: BLE001 — kuyruk yoksa bir sonraki daily koşum devralır
		safe_log_error(traceback_text(), "logistics.integration_log_retention.enqueue")
		return False


def _result(
	deleted: int,
	retention_days: int,
	cutoff: object,
	*,
	skipped: str | None = None,
	remaining: int = 0,
	budget_exhausted: bool = False,
	requeued: bool = False,
) -> dict[str, object]:
	return {
		"deleted": deleted,
		"retention_days": retention_days,
		"cutoff": None if cutoff is None else str(cutoff),
		"skipped": skipped,
		"remaining": remaining,
		"budget_exhausted": budget_exhausted,
		"requeued": requeued,
	}


def run_scheduled() -> dict[str, object]:
	"""Scheduler girişi — `hooks.py::scheduler_events["daily"]` buraya bağlıdır.

	Hatayı YUTAR: saklama işinin çökmesi aynı `daily` listesindeki sonraki
	işleri düşürmemeli (Frappe tek job içinde sırayla koşturur).
	"""
	try:
		return purge_expired_integration_logs()
	except Exception:  # noqa: BLE001 — bakım işi diğer daily işlerini düşürmemeli
		safe_log_error(traceback_text(), "logistics.integration_log_retention")
		return _result(0, 0, None, skipped="error")


__all__ = [
	"DEFAULT_RETENTION_DAYS",
	"DELETE_CHUNK_SIZE",
	"MAX_DELETE_PER_RUN",
	"MAX_RUNTIME_SECONDS",
	"get_retention_days",
	"purge_expired_integration_logs",
	"run_scheduled",
]
