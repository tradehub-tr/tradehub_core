"""Sohbet eki künyesi.

Dosyanın kendisi teamslike'ta (dış chat servisi) durur — burada yalnız
kim/ne/nereye bilgisi tutulur. Medya Gezgini "Sohbet ekleri" ağacını bu
kayıtlardan kurar; dosya baytı kopyalanmaz (bilinçli karar: depolama
ikilenmesin, KVKK'da tek kopya kalsın).
"""

from frappe.model.document import Document


class ChatAttachment(Document):
	pass
