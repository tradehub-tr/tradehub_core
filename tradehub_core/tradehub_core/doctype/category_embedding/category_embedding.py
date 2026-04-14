from frappe.model.document import Document


class CategoryEmbedding(Document):
    """Cached vector representation of a Product Category's name.

    Used by the Complementary scorer as a cold-start fallback when there is
    insufficient co-purchase data: semantically close but non-identical
    categories are paired (e.g. "Kazak" ↔ "Pantolon").

    Vector column stores a JSON array of floats. `model_version` tracks which
    embedding pipeline wrote it (enables lazy re-embedding after upgrades).
    """
    pass
