import frappe
from frappe import _
from frappe.model.document import Document


class EmailPreferenceCategory(Document):
	def validate(self):
		self._validate_unique_item_keys()

	def _validate_unique_item_keys(self):
		seen = set()
		for item in self.items:
			if item.item_key in seen:
				frappe.throw(
					_("Bu kategori içinde tekrarlanan anahtar: {0}").format(item.item_key)
				)
			seen.add(item.item_key)

		# Diğer kategorilerdeki anahtarlarla çakışma kontrolü — tek sorgu
		if not self.items:
			return

		keys = [item.item_key for item in self.items]
		conflicts = frappe.db.sql(
			"""
			SELECT item_key, parent FROM `tabEmail Preference Item`
			WHERE item_key IN %s AND parent != %s
			""",
			(keys, self.name),
			as_dict=True,
		)
		if conflicts:
			c = conflicts[0]
			frappe.throw(
				_("'{0}' anahtarı zaten '{1}' kategorisinde kullanılıyor.").format(
					c.item_key, c.parent
				)
			)
