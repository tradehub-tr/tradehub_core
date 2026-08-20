# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Media Processing Job — yeni medya hattının iş kayıt defteri.

Bir kuyruk işinin ne zaman başladığı, kaç kez denendiği, neyle bittiği burada
durur. Kuyruk tavanları ve backoff politikası burada TEKRAR TANIMLANMAZ.

MEVCUT `media/jobs.py` İLE İLİŞKİ — ÇAKIŞMA YOK
-----------------------------------------------
`tradehub_core/media/jobs.py` (TUR-296) medyadaki dört arka plan işi için
ORTAK SÖZLEŞMEyi tanımlar: durum sözlüğü (running / completed / partial /
error), `MAX_ATTEMPTS = 3`, `BACKOFF_SECONDS = (300, 900)`, `STALE_AFTER_SECONDS
= 2700` ve süpürücü periyodu. O modül **kayıt tutmaz**: durumu her iş kendi
taşıma katmanında saklar — video transcode `File.th_media_video_status`
alanında, görsel optimize Redis sözlüğünde, yedek paketleme disk üstünde.
Yani `media/jobs.py` **File** ekseninde çalışır ve DEĞİŞTİRİLMEDİ.

Bu DocType **Media Asset** ekseninde çalışır ve eksik olanı ekler: kalıcı,
sorgulanabilir bir iş geçmişi. İki sözlük farklıdır ve bilerek ayrı tutulur:

    media/jobs.py            Media Processing Job.status
    ---------------------    -----------------------------
    (kuyrukta)               queued
    running                  running
    completed                success
    partial                  success  (+ error_code ile işaretlenir)
    error                    failed → tavan aşılırsa dead

Eşleme tek yönlüdür: `dead` durumunun `media/jobs.py` tarafında karşılığı
yoktur (orada tavan aşılınca iş yalnız `error` kalır). Yeni hat dead-letter'ı
ayrı bir durum olarak tutar ki süpürücü onu tekrar almasın.

Deneme tavanı kuyruğa göre değişir (Faz 3 kuyruk tasarımı):
media-image-live 3, media-image-bulk 2, media-video 2, media-ai 1,
media-maint 1. `media/jobs.py:MAX_ATTEMPTS` (3) bu tavanların ÜST sınırıdır.

DALGA A notu: `media_pipeline_enabled` bayrağı kapalıyken bu tabloya iş
yazılmaz; mevcut kuyruk davranışı birebir aynı kalır.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

# Kuyruk başına toplam deneme hakkı (ilk çalıştırma dahil).
_QUEUE_MAX_ATTEMPTS: dict[str, int] = {
	"media-image-live": 3,
	"media-image-bulk": 2,
	"media-video": 2,
	"media-ai": 1,
	"media-maint": 1,
}

_TERMINAL_STATUSES: frozenset[str] = frozenset({"success", "failed", "dead"})


class MediaProcessingJob(Document):
	def validate(self) -> None:
		# Document taban sınıfında `validate` yok; repo deseni bu korumalı çağrı.
		if hasattr(super(), "validate"):
			super().validate()
		self._validate_attempt()
		self._validate_timing()
		self._validate_failure_has_code()

	def _validate_attempt(self) -> None:
		"""Deneme sayısı negatif olamaz ve kuyruk tavanını aşamaz."""
		attempt = int(self.attempt or 0)
		if attempt < 0:
			frappe.throw(_("Deneme sayısı negatif olamaz."))
		tavan = _QUEUE_MAX_ATTEMPTS.get(self.queue)
		if tavan is not None and attempt > tavan:
			frappe.throw(
				_("'{0}' kuyruğunda en fazla {1} deneme yapılabilir (verilen: {2}).").format(
					self.queue, tavan, attempt
				)
			)

	def _validate_timing(self) -> None:
		"""Bitiş başlangıçtan önce olamaz; biten iş terminal durumda olmalı."""
		if self.started_at and self.finished_at:
			from frappe.utils import get_datetime

			if get_datetime(self.finished_at) < get_datetime(self.started_at):
				frappe.throw(_("Bitiş zamanı başlangıçtan önce olamaz."))
		if self.finished_at and self.status not in _TERMINAL_STATUSES:
			frappe.throw(_("Bitiş zamanı yazılmış ama durum terminal değil: {0}").format(self.status))

	def _validate_failure_has_code(self) -> None:
		"""Başarısız iş sebepsiz kapatılamaz — hata kodu olmadan teşhis edilemez."""
		if self.status in ("failed", "dead") and not (self.error_code or "").strip():
			frappe.throw(_("Başarısız iş için hata kodu zorunludur."))

	# --- Public API ---

	def max_attempts(self) -> int:
		"""Bu işin kuyruğundaki deneme tavanı (bilinmeyen kuyrukta media/jobs.py varsayılanı)."""
		from tradehub_core.media.jobs import MAX_ATTEMPTS

		return _QUEUE_MAX_ATTEMPTS.get(self.queue, MAX_ATTEMPTS)

	def is_terminal(self) -> bool:
		"""İş bitti mi (başarılı, başarısız ya da dead-letter)?"""
		return self.status in _TERMINAL_STATUSES
