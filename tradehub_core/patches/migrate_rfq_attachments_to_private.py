"""Migrate existing RFQ file attachments from public to private.

Until this patch, RFQ uploads landed in sites/{site}/public/files/ with
is_private=0, which made them downloadable by anyone who guessed the URL.
This patch moves every existing RFQ-attached File into private storage and
flips is_private + file_url so the access-control hook (RFQ.has_permission)
gates downloads going forward.

Idempotent — files already in private/files are skipped.
"""

from __future__ import annotations

import os
import shutil

import frappe
from frappe.utils import get_files_path


def execute():
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "RFQ", "is_private": 0},
		fields=["name", "file_name", "file_url"],
		limit_page_length=0,
	)
	if not files:
		print("[migrate_rfq_attachments_to_private] No public RFQ files found — skip.")
		return

	public_root = get_files_path(is_private=0)
	private_root = get_files_path(is_private=1)
	os.makedirs(private_root, exist_ok=True)

	moved = 0
	missing = 0
	already_private = 0

	for f in files:
		file_name = f.file_name or ""
		old_url = f.file_url or ""
		if not file_name or not old_url:
			continue

		# Resolve disk paths. Frappe URL: /files/{name} → public/files/{name}
		basename = os.path.basename(old_url) if old_url.startswith("/files/") else file_name
		src = os.path.join(public_root, basename)
		dst = os.path.join(private_root, basename)
		new_url = f"/private/files/{basename}"

		if os.path.exists(dst) and not os.path.exists(src):
			# Already migrated on a previous run — just ensure DB is in sync.
			frappe.db.set_value("File", f.name, {"is_private": 1, "file_url": new_url}, update_modified=False)
			already_private += 1
			continue

		if not os.path.exists(src):
			print(f"[migrate_rfq_attachments_to_private] WARN: source missing for {f.name} ({src})")
			missing += 1
			continue

		# Move (overwrite-safe — dst doesn't exist per check above)
		shutil.move(src, dst)
		frappe.db.set_value("File", f.name, {"is_private": 1, "file_url": new_url}, update_modified=False)
		moved += 1

	frappe.db.commit()
	print(
		f"[migrate_rfq_attachments_to_private] moved={moved} already_private={already_private} missing={missing}"
	)
