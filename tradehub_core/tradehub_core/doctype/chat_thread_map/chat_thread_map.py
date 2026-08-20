"""Sohbet konuşması → mağaza eşlemesi.

Sohbet dış serviste (teamslike) yaşar; hangi konuşmanın hangi mağazayla
olduğu ancak thread yaratılırken bilinir (`chat.start_or_get_thread`).
Bu künye o anı yakalar ki sohbet ekleri (Chat Attachment) Medya Gezgini'nde
mağaza klasörlerine düşebilsin.
"""

from frappe.model.document import Document


class ChatThreadMap(Document):
	pass
