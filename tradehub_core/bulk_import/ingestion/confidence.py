"""Confidence aggregator — dry-run preview için kullanıcıya sunulan rapor."""


def build_confidence_report(resolve_result: dict, total_rows: int) -> dict:
	"""Resolve sonucundan kullanıcıya gösterilecek rapor."""
	mapping = resolve_result.get("mapping", {})
	sources = resolve_result.get("sources", {})
	confidence = resolve_result.get("confidence", {})
	unmapped = resolve_result.get("unmapped", [])

	by_source = {"profile": 0, "regex": 0, "semantic": 0, "manual": 0}
	for src in sources.values():
		by_source[src] = by_source.get(src, 0) + 1

	# Confidence band: 0.75 altındaki field'lar manuel onay ister
	low_confidence_fields = [f for f, c in confidence.items() if c < 0.75]

	return {
		"overall_score": resolve_result.get("overall_score", 0.0),
		"by_source": by_source,
		"total_mapped": len(mapping),
		"total_unmapped": len(unmapped),
		"total_rows": total_rows,
		"low_confidence_fields": low_confidence_fields,
		"unmapped_headers": unmapped,
		"profile_used": resolve_result.get("profile_used"),
		"needs_manual_intervention": len(unmapped) > 0 or len(low_confidence_fields) > 0,
	}
