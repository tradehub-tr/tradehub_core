import frappe
from frappe import _
from frappe.model.document import Document

PUBLIC_PREFIX = "/files/"


class MediaURLRedirect(Document):
	"""İş mantığı `media/retro_rename.py` ve `media/redirect_renderer.py`.

	Buradaki tek davranış giriş doğrulama: satırlar 301 `Location` başlığına
	dönüşüyor, yani kontrolsüz bir `target_url` açık yönlendirme (open redirect)
	ya da yol-geçişi demek.
	"""

	def validate(self):
		# Frappe v15'te `Document.validate` YOK — `media_storage_settings.py`
		# ile aynı korumalı çağrı (ileride eklenirse zinciri kırmasın).
		super().validate() if hasattr(super(), "validate") else None
		for alan in ("source_url", "target_url"):
			self._dogrula_adres(self.get(alan))

	@staticmethod
	def _dogrula_adres(url: str | None) -> None:
		"""Yalnız site-içi public medya adresi: `/files/` altı, `..` segmenti yok.

		`https://kotu.example/x` gibi mutlak bir hedef `redirect_renderer`
		tarafından olduğu gibi `Location`'a yazılırdı — açık yönlendirme.
		`..` segmenti ise `retro_rename._disk_path`'in dosya sistemi kökü
		dışına çıkmasına zemin hazırlar (`is_legacy_name` ile aynı segment
		düzeyi kontrol: `derin düzen..jpg` gibi gerçek dosya adları geçerli).
		"""
		temiz = (url or "").split("?")[0]
		gecerli = (
			temiz.startswith(PUBLIC_PREFIX)
			and not temiz.endswith("/")
			and not any(seg in (".", "..") for seg in temiz.split("/"))
		)
		if not gecerli:
			frappe.throw(_("Geçersiz yönlendirme adresi: {0}").format(url or ""))
