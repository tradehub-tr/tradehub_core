"""Media Quality Report kiracı izolasyonu — Frappe bağlamında davranış testleri."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tradehub_core import permissions as perm


class MediaQualityReportPermissionAAA(unittest.TestCase):
	def test_guest_and_profileless_user_see_nothing(self) -> None:
		self.assertEqual(perm.media_quality_report_query_conditions("Guest"), "1=0")
		with (
			patch.object(perm, "_is_platform_full_access", return_value=False),
			patch.object(perm, "_get_seller_profile_name", return_value=None),
		):
			self.assertEqual(perm.media_quality_report_query_conditions("buyer@example.test"), "1=0")
			self.assertFalse(
				perm.media_quality_report_has_permission(
					{"report_type": "asset", "asset": "MA-1"},
					"read",
					"buyer@example.test",
				)
			)

	def test_seller_only_reads_own_asset_report_and_never_monthly(self) -> None:
		# Arrange
		with (
			patch.object(perm, "_is_platform_full_access", return_value=False),
			patch.object(perm, "_get_seller_profile_name", return_value="ASP-1"),
			patch.object(
				perm,
				"_media_asset_owner_subquery",
				return_value="SELECT name FROM `tabMedia Asset` WHERE owner_seller='ASP-1'",
			),
			patch.object(
				perm,
				"_media_asset_owner_of",
				side_effect=lambda asset: "ASP-1" if asset == "MA-1" else "ASP-2",
			),
		):
			# Act
			condition = perm.media_quality_report_query_conditions("seller@example.test")
			own = perm.media_quality_report_has_permission(
				{"report_type": "asset", "asset": "MA-1"}, "read", "seller@example.test"
			)
			foreign = perm.media_quality_report_has_permission(
				{"report_type": "asset", "asset": "MA-2"}, "read", "seller@example.test"
			)
			monthly = perm.media_quality_report_has_permission(
				{"report_type": "monthly", "asset": None}, "read", "seller@example.test"
			)
			write = perm.media_quality_report_has_permission(
				{"report_type": "asset", "asset": "MA-1"}, "write", "seller@example.test"
			)

		# Assert
		self.assertIn("report_type", condition)
		self.assertIn("asset` IN", condition)
		self.assertTrue(own)
		self.assertFalse(foreign)
		self.assertFalse(monthly)
		self.assertFalse(write)


if __name__ == "__main__":
	unittest.main(verbosity=2)
