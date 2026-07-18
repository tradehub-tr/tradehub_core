import frappe

# Marka moru → iStoc sarısı geçişi: "violet" preset'i marka-varsayılanı olarak
# kullanılmıştı; brand preset'i eklendi. Violet'te kalan widget'lar bilinçli bir
# renk seçimi değil eski varsayılandır — topluca brand'e taşınır.
OLD_BG = "bg-violet-100 dark:bg-violet-500/10"
NEW_BG = "bg-brand-100 dark:bg-brand-500/10"
NEW_COLOR = "text-brand-600"


def execute():
	if not frappe.db.table_exists("Dashboard Widget"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabDashboard Widget`
		SET color_preset = 'brand',
			icon_bg_class = %(bg)s,
			icon_color_class = %(color)s
		WHERE COALESCE(color_preset, 'violet') = 'violet'
		""",
		{"bg": NEW_BG, "color": NEW_COLOR},
	)

	# icon_class alanı config_json içinde gömülü olan tablo hücreleri vb.
	# seed'lerden gelir; string düzeyinde güvenli değişim.
	frappe.db.sql(
		"""
		UPDATE `tabDashboard Widget`
		SET config_json = REPLACE(REPLACE(config_json, %(old_bg)s, %(new_bg)s),
			'text-violet-500', %(color)s)
		WHERE config_json LIKE '%%violet%%'
		""",
		{"old_bg": OLD_BG, "new_bg": NEW_BG, "color": NEW_COLOR},
	)
