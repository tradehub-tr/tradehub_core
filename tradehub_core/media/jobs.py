"""Medya kuyruk işleri için ortak sözleşme — durum, deneme, backoff (TUR-296).

Medyada dört ayrı arka plan işi var ve üçü kendi durum sözlüğünü kullanıyordu:

  - video transcode  → `File.th_media_video_status` (kayıt başına)
  - görsel optimize  → Redis ilerleme sözlüğü (iş başına)
  - geri alma        → aynı Redis sözlüğü
  - yedek paketleme  → disk üstünde durum dosyası

Kelimeler ayrıştığı için "iş başarısız oldu" her yerde başka bir şeye
benziyordu. Bu modül ortak sözlüğü ve retry politikasını TEK yerde tanımlar;
işler kendi taşıma katmanını (alan / cache / dosya) korur, yalnız anlamı
paylaşır. Ayrıntılı gerekçe: `docs/MEDYA-ISLEME-PIPELINE.md`.

Politika üç sayıdan ibaret:

  MAX_ATTEMPTS    Toplam deneme hakkı (ilk çalıştırma dahil).
  BACKOFF_SECONDS Başarısız denemeden sonra beklenecek süre.
  STALE_AFTER     Bu kadar süredir "çalışıyor" görünen iş kayıp sayılır.

`STALE_AFTER`, kuyruk timeout'undan BÜYÜK olmak zorunda: aksi halde hâlâ
gerçekten çalışan uzun bir transcode "kayıp" ilan edilip ikinci kez kuyruğa
girer ve aynı dosyayı iki worker birden yazar.
"""

from __future__ import annotations

from frappe.utils import add_to_date, get_datetime, now_datetime

# --- ortak durum sözlüğü ----------------------------------------------------
# İş "çalışıyor" (kuyrukta ya da worker'da), "bitti", "kısmen bitti"
# (dosya bazında hata var ama iş yürüdü) ya da "başarısız" (iş bir bütün olarak
# yürümedi). Dördü de TERMİNAL değildir: yalnız son üçü terminaldir.
STATE_RUNNING: str = "running"
STATE_COMPLETED: str = "completed"
STATE_PARTIAL: str = "partial"
STATE_ERROR: str = "error"

TERMINAL_STATES: frozenset[str] = frozenset({STATE_COMPLETED, STATE_PARTIAL, STATE_ERROR})

# --- retry politikası -------------------------------------------------------
# 3 seçildi: geçici hatalar (disk dolu, OOM, kuyruk restart'ı) genelde ilk
# tekrarda geçer; 3'te de geçmeyen hata neredeyse her zaman dosyanın
# kendisindedir ve insan bakmadan düzelmez.
MAX_ATTEMPTS: int = 3

# Deneme başına bekleme. Hemen tekrar denemek işe yaramıyor: disk dolduysa ya
# da ffmpeg imajdan kalktıysa saniyeler içinde düzelmez — üç hak saniyeler
# içinde yanar ve dosya boşuna dead-letter'a düşer. İlk tekrar 5 dk, ikincisi
# 15 dk sonra. Liste `MAX_ATTEMPTS - 1` uzunluğunda: son denemeden sonra
# beklenecek bir şey yok.
BACKOFF_SECONDS: tuple[int, ...] = (300, 900)

# Kuyruk timeout'u (1800 sn) + ffmpeg'in kendi payı + süpürücünün periyodu.
# Bu süredir `processing` görünen iş worker tarafından bırakılmış sayılır.
STALE_AFTER_SECONDS: int = 2700

# Süpürücünün çalışma sıklığı (hooks.py cron ile TUTARLI tutulmalı). Backoff
# çözünürlüğü bundan daha ince olamaz: 60 sn'lik bir backoff yazsak bile
# gerçekte bir sonraki süpürmede işlenirdi.
SWEEP_EVERY_SECONDS: int = 300


def backoff_seconds(attempt: int) -> int:
	"""`attempt` numaralı başarısız denemeden sonra beklenecek süre.

	`attempt` 1-tabanlıdır (ilk başarısızlık = 1). Liste biterse son değer
	tekrarlanır — politika değişip `MAX_ATTEMPTS` büyütülürse burası sessizce
	IndexError vermesin.
	"""
	if attempt < 1:
		return BACKOFF_SECONDS[0]
	return BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS)) - 1]


def next_attempt_at(attempt: int):
	"""Bir sonraki denemenin en erken zamanı (DB'ye yazılabilir damga).

	`as_string` KULLANILMIYOR: Frappe'nin `add_to_date`'i `as_string=True` ile
	`as_datetime` verilmezse yalnız TARİHİ döndürür, saat düşer — 5 dakikalık
	bir backoff sessizce "bugün 00:00"a çöker ve süpürücü işi hemen alır
	(yaşandı). `datetime` nesnesi olarak dönüp yazmak bu tuzağı kapatıyor.
	"""
	return add_to_date(now_datetime(), seconds=backoff_seconds(attempt))


def is_due(next_at) -> bool:
	"""Planlanan deneme zamanı geldi mi. Boş damga "hemen" demektir."""
	if not next_at:
		return True
	return get_datetime(next_at) <= now_datetime()


def is_stale(started_at, *, stale_after: int = STALE_AFTER_SECONDS) -> bool:
	"""İş bırakılmış mı — bu kadar süredir "çalışıyor" ama bitmemiş.

	Damga hiç yoksa STALE SAYILIR: alanı olmayan eski kayıtlar ya da damga
	yazılamadan düşen bir worker, süpürücünün göremediği kör nokta olurdu.
	"""
	if not started_at:
		return True
	esik = add_to_date(now_datetime(), seconds=-stale_after)
	return get_datetime(started_at) < esik


# --- metrik köprüsü (K-1) ----------------------------------------------------
# `media_job_total` / `media_job_attempts` göstergeleri bugüne kadar TANIMLI ama
# hiç yazılmıyordu; `MediaJobFailureRatio` ve `MediaJobRetryExhaustion` alarmları
# bu iki seriye bağlı ve seri boş olduğu için ÖLÜYDÜ. Sayaç, işin sonucunu ÇAĞRI
# yerinde (iş terminal olduğunda) yazar — periyodik bir toplayıcı değil: bir işin
# "başarısız bittiği" ancak o iş bittiğinde bilinir.


def record_terminal(job: str, state: str, *, attempts: int = 1) -> None:
	"""İş TERMİNAL bir duruma ulaştığında metriğe yaz — best-effort, iş düşmez.

	`instrument.py` sözleşmesiyle aynı ilke: ölçüm, ölçtüğü işi DÜŞÜREMEZ.
	Metrik içe aktarımı ve yazımı `try/except` içinde; hata sessizce yutulur
	(sarmalayıcının `INSTRUMENT_ERRORS_TOTAL`i burada devrede değil çünkü bu
	doğrudan çağrıdır, enstrümantasyon noktası değil).

	Terminal OLMAYAN durum (`running`) yazılmaz: sayaç yalnız SONUÇ sayar.
	`state` `media_job_total{state=...}` etiketine birebir gider — kanonik
	değerler `completed` / `partial` / `error`'dır (`TERMINAL_STATES`).
	`attempts` iş başına deneme sayısıdır; tek seferlik batch işleri için 1'dir,
	retry'lı işler (transcode/av) gerçek deneme sayısını geçmelidir.
	"""
	if state not in TERMINAL_STATES:
		return
	try:
		from tradehub_core.media.pipeline.observability import metrics as mm

		mm.JOB_TOTAL.inc(job=job, state=state)
		mm.JOB_ATTEMPTS.observe(float(max(1, int(attempts))), job=job)
	except Exception:
		# Metrik yazımı arızası işi düşürmemeli; sessiz kalması bilinçli.
		pass
