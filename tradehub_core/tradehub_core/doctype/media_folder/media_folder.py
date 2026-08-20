"""Satıcının GERÇEK medya klasörü (T-094).

Bugüne kadarki gezgin ağacı SANALDI: kategori/ürün üzerinden türetiliyordu,
kullanıcı kendi klasörünü açamıyordu. Bu DocType satıcının kendi elleriyle
kurduğu ağaçtır — `parent_folder` bağıyla (nested set değil: ağaç küçük,
taşıma/yeniden adlandırma sık; nested set her taşımada yarım tabloyu
güncellerdi).

**Ad `hash` ile üretilir.** Klasör adları (`folder_name`) satıcının seçtiği
serbest metin; docname'e yazılsaydı hem çakışırdı hem de URL'de başka
mağazaların klasör adları tahmin yoluyla keşfedilebilirdi (TUR-141 ile aynı
ilke).

**Tenant izolasyonu iki katmanlıdır:**

  1. Uç-içi: `api/seller_media.py` her klasör ucunda mağazayı OTURUMDAN çözer
     ve klasörün `store` alanıyla karşılaştırır (`_my_folder`).
  2. Çerçeve: aşağıdaki `get_permission_query_conditions` + `has_permission`
     fonksiyonları. Bunlar hooks.py'a KAYITLI DEĞİL (hooks.py bu görevde
     yasak); kayıt satırları görev raporunda. Kayıt yapılana kadar DocPerm
     tablosu yalnız System Manager / Marketplace Admin içerdiği için genel
     uçlar (`frappe.client.get_list` vb.) satıcıya zaten kapalıdır — hook,
     ileride bir satıcı rolüne DocPerm verilirse sızıntıyı önleyecek emniyet
     kemeridir.

Derinlik tavanı 5: şartname (60-faz9-media-library.html, T-094) sayı vermiyor,
yalnız "ağaç yapısı" diyor. 5 seçildi çünkü (a) sanal ağacın en derin hali 3
seviye (kök→kategori→ürün) — kullanıcı alışkanlığının iki katı pay bırakır,
(b) her doğrulama ata zincirini yürüdüğünden tavan sorgu sayısını da sınırlar,
(c) kırıntı şeridi (MediaCrumbs) 5 seviyeyi mobil ekranda hâlâ okunur basar.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

# Kökün derinliği 1'dir; en derin klasör 5. seviyede durabilir.
MAX_DEPTH: int = 5

# Klasör adı sınırı — Data alanı 140 karakter taşır ama ekranda 100'den
# uzunu zaten kırpılıyor; sınırı yazmak sessiz kesilmeden iyidir.
MAX_NAME_LEN: int = 100

_ADMIN_ROLES: tuple[str, ...] = ("System Manager", "Marketplace Admin")


class MediaFolder(Document):
	def validate(self) -> None:
		# Boş ebeveyn her zaman "" olarak saklanır. NULL ile "" karışırsa
		# benzersizlik süzgeci kök klasörleri iki ayrı kümede arar ve aynı ad
		# köke iki kez açılabilirdi.
		self.parent_folder = (self.parent_folder or "").strip()
		self._clean_name()
		self._validate_parent()
		self._validate_depth()
		self._validate_unique()

	def _clean_name(self) -> None:
		ad = (self.folder_name or "").strip()
		if not ad:
			frappe.throw(_("Klasör adı boş olamaz."))
		if len(ad) > MAX_NAME_LEN:
			frappe.throw(_("Klasör adı en çok {0} karakter olabilir.").format(MAX_NAME_LEN))
		if "/" in ad:
			# Yol ayracı ada girerse kırıntı ve ileride dışa aktarma yolları
			# iki klasörü tek klasörden ayırt edemez.
			frappe.throw(_("Klasör adında '/' kullanılamaz."))
		self.folder_name = ad

	def _validate_parent(self) -> None:
		if not self.parent_folder:
			return
		if self.parent_folder == self.name:
			frappe.throw(_("Klasör kendi altına taşınamaz."))
		ust = frappe.db.get_value(
			"Media Folder", self.parent_folder, ["store"], as_dict=True
		)
		if not ust:
			frappe.throw(_("Üst klasör bulunamadı."), frappe.DoesNotExistError)
		# Mesaj bilerek "bulunamadı": başka mağazanın klasör kimliğinin VAR
		# olduğunu doğrulamak, kimlik uzayını deneme yoluyla keşfe açar
		# (ownership.assert_owns ile aynı ilke).
		if ust.store != self.store:
			frappe.throw(_("Üst klasör bulunamadı."), frappe.DoesNotExistError)

	def _validate_depth(self) -> None:
		"""Derinlik tavanı + döngü koruması tek yürüyüşte.

		Ata zinciri yürünür; kendi adına rastlanırsa döngü var demektir
		(A→B→A), tavan aşılırsa reddedilir. İki kontrol aynı yürüyüşte çünkü
		ikisinin de girdisi aynı zincir.
		"""
		gorulen: set[str] = set()
		ata = self.parent_folder
		derinlik = 1
		while ata:
			if ata == self.name or ata in gorulen:
				frappe.throw(_("Klasör kendi alt klasörünün altına taşınamaz."))
			gorulen.add(ata)
			derinlik += 1
			if derinlik > MAX_DEPTH:
				frappe.throw(
					_("Klasörler en çok {0} seviye derinlikte olabilir.").format(MAX_DEPTH)
				)
			ata = frappe.db.get_value("Media Folder", ata, "parent_folder")

		# Taşınan klasörün ALTINDA ağaç varsa, o ağacın en derin yaprağı da
		# tavanı aşmamalı.
		if not self.is_new():
			alt_derinlik = self._subtree_depth(self.name, gorulen)
			if derinlik + alt_derinlik - 1 > MAX_DEPTH:
				frappe.throw(
					_("Klasörler en çok {0} seviye derinlikte olabilir.").format(MAX_DEPTH)
				)

	def _subtree_depth(self, kok: str, gorulen: set[str]) -> int:
		"""`kok` dahil alt ağacın yüksekliği (yalnız kök ise 1)."""
		cocuklar = frappe.get_all(
			"Media Folder", filters={"parent_folder": kok}, pluck="name"
		)
		if not cocuklar:
			return 1
		en_derin = 1
		for c in cocuklar:
			if c in gorulen:
				continue  # döngü — üstteki kontrol zaten reddedecek
			en_derin = max(en_derin, 1 + self._subtree_depth(c, gorulen | {c}))
		return en_derin

	def _validate_unique(self) -> None:
		"""Aynı mağazada, aynı ebeveyn altında aynı ad ikinci kez açılamaz."""
		filtre = {
			"store": self.store,
			"parent_folder": self.parent_folder or "",
			"folder_name": self.folder_name,
			"name": ["!=", self.name],
		}
		if frappe.db.exists("Media Folder", filtre):
			frappe.throw(
				_("Bu klasörde '{0}' adında bir klasör zaten var.").format(self.folder_name),
				frappe.DuplicateEntryError,
			)

	def on_trash(self) -> None:
		"""Dolu klasör silinemez — şartname yalnız 'içerik varsa uyarı' diyor,
		davranışı seçmiyor. REDDET seçildi: köke taşımak sessiz bir yan etki
		olurdu (kullanıcı 500 dosyanın nereye gittiğini sormak zorunda kalır);
		ret ise kullanıcıyı önce içeriği bilerek taşımaya zorlar ve hiçbir şey
		kaybolmaz."""
		if frappe.db.exists("Media Folder", {"parent_folder": self.name}):
			frappe.throw(_("Klasörün alt klasörleri var. Önce onları silin ya da taşıyın."))
		if frappe.db.exists("Media Folder Item", {"folder": self.name}):
			frappe.throw(_("Klasör boş değil. Önce dosyaları başka bir klasöre taşıyın."))


# ── Çerçeve izolasyonu — hooks.py kaydı RAPORDA, burada yalnız fonksiyonlar ──


def _store_of(user: str | None) -> str | None:
	from tradehub_core.media import ownership

	return ownership.store_of(user)


def get_permission_query_conditions(user: str | None = None) -> str:
	"""Desk listesi / frappe.get_list süzgeci: satıcı yalnız kendi mağazasının
	klasörlerini görür. hooks.py kaydı (raporda):

	    "Media Folder": "tradehub_core.tradehub_core.doctype.media_folder.media_folder.get_permission_query_conditions"
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"
	roller = frappe.get_roles(user)
	if any(r in roller for r in _ADMIN_ROLES):
		return ""
	store = _store_of(user)
	if not store:
		return "1=0"
	return f"`tabMedia Folder`.`store` = {frappe.db.escape(store)}"


def has_permission(doc, user: str | None = None, permission_type: str = "") -> bool:
	"""Tek kayıt kontrolü. hooks.py kaydı (raporda):

	    "Media Folder": "tradehub_core.tradehub_core.doctype.media_folder.media_folder.has_permission"
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	roller = frappe.get_roles(user)
	if any(r in roller for r in _ADMIN_ROLES):
		return True
	store = _store_of(user)
	return bool(store) and getattr(doc, "store", None) == store
