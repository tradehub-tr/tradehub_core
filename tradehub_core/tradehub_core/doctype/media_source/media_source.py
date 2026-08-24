"""Immutable identity card for an uploaded source file."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class MediaSource(Document):
	"""A source row is append-only; corrections are represented by a new upload."""

	IMMUTABLE_FIELDS = (
		"asset",
		"file_url",
		"storage_backend",
		"bytes",
		"mime_real",
		"mime_claimed",
		"width",
		"height",
		"megapixels",
		"dpi_x",
		"dpi_y",
		"colorspace",
		"has_alpha",
		"frames",
		"duration",
		"video_codec",
		"audio_codec",
		"bitrate",
		"exif_stripped",
		"uploaded_by",
		"client_report",
	)

	def validate(self) -> None:
		if hasattr(super(), "validate"):
			super().validate()
		self._validate_measurements()
		self._guard_immutability()

	def _validate_measurements(self) -> None:
		for fieldname in ("bytes", "width", "height", "frames", "bitrate"):
			value = self.get(fieldname)
			if value is not None and int(value) < 0:
				frappe.throw(_("{0} negatif olamaz.").format(fieldname))
		for fieldname in ("megapixels", "duration"):
			value = self.get(fieldname)
			if value is not None and float(value) < 0:
				frappe.throw(_("{0} negatif olamaz.").format(fieldname))

	def _guard_immutability(self) -> None:
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		# Frappe updates audit metadata (for example ``modified``) on every save.
		# Only the source evidence itself is immutable; framework metadata must not
		# turn an otherwise valid no-op save into a false positive.
		changed = [fieldname for fieldname in self.IMMUTABLE_FIELDS if before.get(fieldname) != self.get(fieldname)]
		if changed:
			frappe.throw(_("Media Source değişmezdir; değişen alanlar: {0}").format(", ".join(changed)))
