import frappe
from frappe.model.document import Document


class RelatedProductsSettings(Document):
	"""Single DocType holding weights + thresholds for Related Products scoring.

	Batch jobs read from this doctype at compute time. Field names and defaults
	mirror the MVP constants — admin panel (Faz 2) will edit these live.
	"""

	def on_update(self):
		frappe.cache().delete_key("related_products_settings")


def get_settings() -> dict:
	"""Return settings as a plain dict, cached for 60s.

	Avoids a full DocType load on every score computation inside batch loops.
	"""
	cached = frappe.cache().get_value("related_products_settings")
	if cached:
		return cached

	doc = frappe.get_single("Related Products Settings")
	data = {
		"min_score_threshold": float(doc.min_score_threshold or 0.5),
		"max_results_per_tab": int(doc.max_results_per_tab or 8),
		"copurchase_lift_threshold": float(doc.copurchase_lift_threshold or 1.5),
		"accessory_price_ratio_threshold": float(doc.accessory_price_ratio_threshold or 0.3),
		"embedding_cosine_threshold": float(doc.embedding_cosine_threshold or 0.6),
		"similar": {
			"category": float(doc.weight_similar_category or 0.40),
			"attribute": float(doc.weight_similar_attribute or 0.35),
			"price_tier": float(doc.weight_similar_price_tier or 0.15),
			"rating": float(doc.weight_similar_rating or 0.10),
		},
		"substitute": {
			"same_category": float(doc.weight_substitute_same_category or 0.30),
			"different_seller": float(doc.weight_substitute_different_seller or 0.25),
			"attribute": float(doc.weight_substitute_attribute or 0.25),
			"price_proximity": float(doc.weight_substitute_price_proximity or 0.20),
		},
		"complementary": {
			"copurchase": float(doc.weight_complementary_copurchase or 0.50),
			"coview": float(doc.weight_complementary_coview or 0.30),
			"embedding": float(doc.weight_complementary_embedding or 0.20),
		},
		"accessory": {
			"token": float(doc.weight_accessory_token or 0.40),
			"price_ratio": float(doc.weight_accessory_price_ratio or 0.30),
			"category_pattern": float(doc.weight_accessory_category_pattern or 0.20),
			"copurchase": float(doc.weight_accessory_copurchase or 0.10),
		},
	}
	frappe.cache().set_value("related_products_settings", data, expires_in_sec=60)
	return data
