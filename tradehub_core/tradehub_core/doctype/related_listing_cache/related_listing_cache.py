from frappe.model.document import Document


class RelatedListingCache(Document):
	"""Pre-computed recommendation scores for a (source_listing, target_listing, relation_type) triple.

	Populated by the nightly batch in tradehub_core.recommendations.tasks.
	Read by the storefront API in tradehub_core.api.listing.get_related_listings_grouped.
	"""

	pass
