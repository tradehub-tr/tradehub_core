"""Adaptive column resolver — 3 katmanlı kaskat (Profile → Regex → Semantic)."""

from tradehub_core.bulk_import import regex_lib
from tradehub_core.bulk_import.ingestion import profile_store, semantic


def resolve_columns(
	headers: list[str],
	seller_profile: str,
	sheet_name: str | None = None,
) -> dict:
	"""Header listesini canonical field'lara eşle.

	Returns:
		{
			"mapping": {canonical_field: header},
			"sources": {canonical_field: "profile" | "regex" | "semantic" | "manual"},
			"confidence": {canonical_field: float 0..1},
			"unmapped": [headers that couldn't be resolved],
			"profile_used": profile_name | None,
			"overall_score": float 0..1,
		}
	"""
	# Layer 1: Profile (full match)
	profile = profile_store.lookup_profile(headers, seller_profile)
	if profile and profile.get("mapping"):
		profile_store.increment_hit_count(profile["profile_name"])
		# Bu profile'ı doğrudan kullan — %100 confidence
		mapping = profile["mapping"]
		sources = {f: "profile" for f in mapping}
		confidence = {f: 1.0 for f in mapping}
		unmapped = [h for h in headers if h not in mapping.values()]
		return {
			"mapping": mapping,
			"sources": sources,
			"confidence": confidence,
			"unmapped": unmapped,
			"profile_used": profile["profile_name"],
			"overall_score": 1.0,
		}

	# Layer 2: Regex Pattern Library
	regex_mapping = regex_lib.resolve_column_mapping(headers, seller_profile)
	sources: dict[str, str] = {f: "regex" for f in regex_mapping}
	confidence: dict[str, float] = {f: 0.9 for f in regex_mapping}  # Regex match = high confidence
	mapping: dict[str, str] = dict(regex_mapping)
	used_headers: set[str] = set(regex_mapping.values())

	# Layer 3: Semantic for unmapped headers
	for header in headers:
		if header in used_headers:
			continue
		if not header or not header.strip():
			continue
		target, score = semantic.resolve_header_semantic(header)
		if target and target not in mapping:
			mapping[target] = header
			sources[target] = "semantic"
			confidence[target] = round(score, 3)
			used_headers.add(header)

	# Compute overall score
	if confidence:
		overall = sum(confidence.values()) / len(confidence)
	else:
		overall = 0.0

	unmapped = [h for h in headers if h and h not in used_headers]

	return {
		"mapping": mapping,
		"sources": sources,
		"confidence": confidence,
		"unmapped": unmapped,
		"profile_used": None,
		"overall_score": round(overall, 3),
	}
