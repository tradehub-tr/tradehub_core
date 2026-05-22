# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ListingViewCounter(Document):
	"""Per-listing rolling 24-hour view counter.

	Managed by the record_view endpoint (UPSERT). Reset hourly by
	reset_view_counters_rolling_24h scheduler when last_event ages past 24h.
	"""

	pass
