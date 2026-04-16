from frappe.model.document import Document


class CategoryNeighbourCache(Document):
	"""Pre-computed similarity edges between Product Categories.

	Populated by `tradehub_core.recommendations.neighbour_cache.rebuild_all`
	after every Category Embedding rebuild. Enables the Complementary
	cold-start fallback to look up "similar categories" via an indexed SQL
	select instead of scanning every embedding per listing.

	Composite index `(category, similarity DESC)` is added by the patch
	`add_category_neighbour_cache_indexes` for hot-path lookups.
	"""

	pass
