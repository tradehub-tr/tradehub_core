# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Media Version — normalize master'ın SÜRÜMÜ (T-040 / T-064).

Politika, kırpma niyeti, kaynak dosya ya da motor sürümü değişince YENİ bir
sürüm üretilir; eski sürüm SİLİNMEZ. `autoname = field:version_hash`, yani
kaydın adı içeriğinin hash'idir — aynı girdi ikinci kez üretilemez (INV-06).

NEDEN GEÇİŞ BU TABLOYLA ATOMİK OLUR
-----------------------------------
`core/dedup.py::rendition_path` türev adresine `version_hash`i koyar
(INV-09), yani yeni sürümün dosyaları eskilerin ÜSTÜNE hiçbir zaman yazmaz;
ayrı dizine düşer. Atomik olmayan tek şey "hangi sürüm yayında" sorusunun
cevabıydı. `Media Asset.active_version` + bu tablonun `is_active` alanı o
cevabı tek transaction'da çevrilebilir hâle getirir:

    update `tabMedia Version` set is_active = 0 where asset = %s
    update `tabMedia Version` set is_active = 1 where name = %s
    update `tabMedia Asset`   set active_version = %s where name = %s

Okuyucu ya eski sürümü ya yeni sürümü görür; yarısını asla.

`is_active` DENORMALİZE — ve neden
----------------------------------
Doğruluğun tek kaynağı `Media Asset.active_version`. `is_active` onun kopyası
ve sorgu kolaylığı içindir: saklama/öksüz taraması Asset'e join etmeden
"yayında olmayan sürümler" diye filtreleyebilsin. Kopya alan sessizce eskiyen
bir kaynaktır; bu yüzden tutarlılık burada `validate` içinde ÖLÇÜLÜR ve
çeliştiğinde yazma REDDEDİLİR — sessizce düzeltmek, hangi tarafın doğru
olduğuna kod adına karar vermek olurdu.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

#: T-061/062/065 — zenginleştirmenin yazdığı alanlar. Manifest/panel uçlarının
#: alt katman okuması (`version_enrichment_for_assets`) da bu listeyi seçer;
#: iki taraf tek listeden beslenir ki alan ekleyince ikisi birden görsün.
ENRICHMENT_FIELDS: tuple[str, ...] = (
	"width",
	"height",
	"dpi",
	"colorspace",
	"has_alpha",
	"classification",
	"classification_confidence",
	"format_chain",
	"lqip",
	"lqip_data_uri",
	"dominant_color",
)


class MediaVersion(Document):
	def before_insert(self) -> None:
		"""T-061/062/065 üretim yolu — sürüm açılırken künye TEK okumada dolar.

		Sürüm kaydını AÇAN tek yer `media/pipeline_bridge.py::_ensure_version`
		(worker, kuyruk `long`); zenginleştirme bu kancayla o hattın İÇİNDE
		koşar ama köprüye dokunmaz. Best-effort: kaynak okunamıyor ya da
		görüntü çözülemiyorsa sürüm YİNE açılır, alanlar boş kalır ve sebep
		loglanır — türev üretimini bir ön izleme süslemesi engelleyemez.
		"""
		if hasattr(super(), "before_insert"):
			super().before_insert()
		self._enrich_from_source()

	def validate(self) -> None:
		if hasattr(super(), "validate"):
			super().validate()
		self._validate_hash()
		self._validate_geometry()
		self._stamp_created_at()
		self._validate_active_consistency()

	def _validate_hash(self) -> None:
		if not (self.version_hash or "").strip():
			frappe.throw(_("Sürüm hash'i zorunlu — kaydın adı bu değerdir."))

	def _validate_geometry(self) -> None:
		for alan in ("width", "height", "dpi"):
			deger = self.get(alan)
			if deger is not None and int(deger or 0) < 0:
				frappe.throw(_("`{0}` negatif olamaz.").format(alan))

	def _stamp_created_at(self) -> None:
		if not self.created_at:
			self.created_at = now_datetime()

	def _validate_active_consistency(self) -> None:
		"""`is_active=1` ile Asset'in `active_version`ı çelişemez.

		Çelişkiyi sessizce düzeltmek YASAK: hangi tarafın doğru olduğu bu
		sınıfın bilebileceği bir şey değil. Geçiş protokolü ikisini AYNI
		transaction'da yazar; buraya çelişkili bir değer geliyorsa geçiş
		yarıda kalmış demektir ve bunu görmek gerekir.
		"""
		if not self.is_active or not self.asset:
			return
		aktif = frappe.db.get_value("Media Asset", self.asset, "active_version")
		if aktif and aktif != self.name:
			frappe.throw(
				_(
					"Sürüm yayında işaretli ama varlığın yayındaki sürümü başka: "
					"{0} (varlık: {1}, bu sürüm: {2}). Geçiş tek transaction'da yapılmalı."
				).format(aktif, self.asset, self.name)
			)

	# ── T-061/062/065: zenginleştirme ───────────────────────────────────

	def _enrich_from_source(self) -> None:
		"""Kaynak baytlardan probe + sınıf + LQIP çıkar, alanlara yaz.

		Hesap `media/pipeline/image/enrich.py`'de (saf, frappe'siz); burada
		yalnız kaynak okuma ve alan ataması var. İdempotent: `lqip` doluysa
		hiçbir şey yapılmaz — aynı sürümün yeniden işlenmesi (INV-06) kayıtlı
		künyeyi yeniden hesaplamaz.
		"""
		if (self.lqip or "").strip():
			return
		kaynak = self._source_bytes()
		if not kaynak:
			return
		try:
			from tradehub_core.media.pipeline.image import enrich as enrich_mod

			kunye = enrich_mod.enrich(kaynak)
		except Exception:
			frappe.log_error(
				title="media version enrichment",
				message=f"{self.asset} / {self.version_hash}\n\n{frappe.get_traceback()}",
			)
			return
		if not kunye.ok:
			frappe.log_error(
				title="media version enrichment",
				message=f"{self.asset} / {self.version_hash}: {kunye.reason}",
			)
			return

		# Geometri yalnız BOŞKEN yazılır: köprü bir gün normalize master'ın
		# gerçek ölçüsünü yazmaya başlarsa bu kanca onu ezmemeli.
		if not int(self.width or 0):
			self.width = kunye.width
		if not int(self.height or 0):
			self.height = kunye.height
		if not int(self.dpi or 0):
			self.dpi = kunye.dpi
		if not (self.colorspace or "").strip():
			self.colorspace = kunye.colorspace
		self.has_alpha = 1 if kunye.has_alpha else 0
		if kunye.classification:
			self.classification = kunye.classification
			self.classification_confidence = kunye.classification_confidence
		if kunye.format_chain:
			self.format_chain = frappe.as_json([dict(a) for a in kunye.format_chain])
		self.lqip = kunye.lqip
		self.lqip_data_uri = kunye.lqip_data_uri
		self.dominant_color = kunye.dominant_color

	def _source_bytes(self) -> bytes | None:
		"""Varlığın kaynak dosya içeriği; okunamıyorsa `None` (sessiz değil, loglu)."""
		if not self.asset:
			return None
		try:
			source_file = frappe.db.get_value("Media Asset", self.asset, "source_file")
			if not source_file or not frappe.db.exists("File", source_file):
				return None
			icerik = frappe.get_doc("File", source_file).get_content()
			if isinstance(icerik, str):
				icerik = icerik.encode()
			return icerik or None
		except Exception:
			frappe.log_error(
				title="media version enrichment",
				message=f"kaynak okunamadı: {self.asset}\n\n{frappe.get_traceback()}",
			)
			return None


# ── modül seviyesi yardımcılar ──────────────────────────────────────────


def enrich_version(name: str, *, force: bool = False) -> bool:
	"""Mevcut bir sürümün künyesini doldur (backfill / yeniden işleme).

	Köprüdeki idempotency kapısı (`_renditions_exist`) aynı içeriği ikinci kez
	İŞLEMEZ; yani alan eklenmeden önce açılmış sürümler kancadan hiç geçmez.
	Bu fonksiyon o kayıtlar için aynı üretim yolunu (controller'ın kendi
	`_enrich_from_source`'u) çağırır ve doğrudan DB'ye yazar.

	Returns:
	    True — en az bir alan yazıldı; False — kaynak yok/çözülemedi ya da
	    kayıt zaten dolu (`force=False`).
	"""
	doc = frappe.get_doc("Media Version", name)
	if (doc.lqip or "").strip() and not force:
		return False
	doc.lqip = ""
	doc._enrich_from_source()
	if not (doc.lqip or doc.classification):
		return False
	frappe.db.set_value(
		"Media Version",
		name,
		{alan: doc.get(alan) for alan in ENRICHMENT_FIELDS},
		update_modified=False,
	)
	return True


def version_enrichment_for_assets(assets: Sequence[str]) -> dict[str, dict[str, Any]]:
	"""Varlık → YAYINDAKİ sürümün T-061/062/065 alanları. İki sorgu.

	Seçim kuralı, doğruluğun tek kaynağıyla hizalıdır:

	  1. `Media Asset.active_version` DOLUYSA → **yalnız** o sürüm kabul edilir.
	     Başka bir satır (daha yeni bile olsa) onu maskeleyemez; aktif sürümün
	     alanları boşsa boş döner — "yayında olan bu" bilgisi, yanlışlıkla daha
	     dolu bir sürümü göstermekten önce gelir.
	  2. `active_version` BOŞSA → geriye uyum için bugünkü davranış korunur:
	     `is_active desc, creation desc` sırasında ilk satır (yayındaki sürüm
	     varsa o, yoksa en yenisi). Boru hattı henüz `active_version` yazmayan
	     eski varlıklar bu daldan geçer.

	Bu, "en yeni maskeleme"yi gerçek aktif-sürüm seçimine çevirir: `active_version`
	kurulduğu an okuma yolu geçişin (`promote_version`) yazdığı sürümü görür.

	Manifest/panel uçlarının alt katman okuması: `api/media_manifest.py` (ya da
	başka bir teslim ucu) bu sözlüğü `ManifestBuilder.build_image(...,
	version_meta=...)`'ya geçirir; sıralama/eleme kararı yine kütüphanenin.
	`format_chain` JSON'u burada ÇÖZÜLÜR — çağıranın elinde dizge değil liste
	olsun, iki uç iki farklı ayrıştırma yazmasın.

	Sistem okuması (`frappe.get_all`): kiracı süzgeci çağıran uçtadır — buraya
	yalnız o ucun ZATEN görmeye yetkili olduğu varlık adları gelir.
	"""
	adlar = [a for a in (assets or []) if a]
	if not adlar:
		return {}
	# `active_version` DOLU olan varlıklar için gerçek aktif sürümü öğren; boş
	# olanlar haritaya girmez ve fallback dalına düşer.
	aktif_harita: dict[str, str] = {
		satir["name"]: satir["active_version"]
		for satir in frappe.get_all(
			"Media Asset",
			filters={"name": ["in", adlar]},
			fields=["name", "active_version"],
			limit_page_length=0,
		)
		if satir.get("active_version")
	}
	cikti: dict[str, dict[str, Any]] = {}
	for satir in frappe.get_all(
		"Media Version",
		filters={"asset": ["in", adlar]},
		fields=["asset", "name", "version_hash", "is_active", *ENRICHMENT_FIELDS],
		order_by="is_active desc, creation desc",
		limit_page_length=0,
	):
		asset = satir["asset"]
		tercih = aktif_harita.get(asset)
		if tercih is not None:
			# active_version VAR: yalnız o sürüm; başka satır maskeleyemez.
			if satir["name"] != tercih:
				continue
		elif asset in cikti:
			# active_version YOK: ilk satır kazanır (is_active/creation fallback).
			continue
		try:
			satir["format_chain"] = frappe.parse_json(satir.get("format_chain") or "[]") or []
		except Exception:
			satir["format_chain"] = []
		satir["has_alpha"] = bool(satir.get("has_alpha"))
		# `name` seçim içindi; dışa `version_hash` sözleşmesi korunur (name == hash).
		satir.pop("name", None)
		cikti[satir.pop("asset")] = satir
	return cikti


# ── sürüm geçişi: atomik yayına-alma (promote) ve geri-alma (rollback) ──────
#
# NEDEN BURADA: Yazan taraf, doğruluğun kaynağını (`_validate_active_consistency`)
# ve okuyan tarafı (`version_enrichment_for_assets`) ile AYNI dosyada durur —
# üçü tek sözleşmeyi paylaşır. Çekirdek (`pipeline/core/`) bilinçli frappe'siz;
# transaction/DB gerektiren bu yazar oraya konamaz.
#
# Denetim eylemleri `media/audit.py`'nin "media.<eylem>" desenini izler ama o
# dosyaya bağımlılık kurmadan (sahiplik sınırı) burada tanımlanır.

#: Sürüm yayına alındı — from/to `context`'te; rollback geçmişi bundan okur.
ACTION_VERSION_PROMOTE: str = "media.version_promote"
#: Önceki yayına dönüldü (promote'un tersi).
ACTION_VERSION_ROLLBACK: str = "media.version_rollback"


def promote_version(asset: str, version: str, *, commit: bool = True) -> str | None:
	"""`version`'ı `asset`in YAYINDAKİ sürümü yap — atomik (T-042/INV-08).

	Protokol (media_version.py modül başlığındaki tasarımın kodu):
	  1. Doğrula: sürüm var, `asset`e ait, ve varlık `ready` (servis edilebilir).
	  2. TEK transaction'da, arada commit OLMADAN:
	         eski `is_active=0`  →  `Media Asset.active_version = version`  →
	         yeni `is_active=1`
	  3. Tutarlılık geçmeli (`_validate_active_consistency` + tam-bir-aktif).
	  4. Denetim izi yazılır (aynı transaction).

	"Geçiş sırasında eski sürüm erişilebilir kalır": üç yazma tek transaction'da
	olduğundan, başka bir bağlantıdaki okuma yolu (`version_enrichment_for_assets`)
	ya geçişten ÖNCEKİ ya SONRAKİ durumu görür — yarı-durumu (sıfır aktif ya da
	çift aktif) asla. Türev dosyaları `version_hash` taşıyan ayrı adreslerde
	durduğu için (INV-09) eski sürümün baytları geçiş boyunca yerinde kalır.

	Args:
	    asset: `Media Asset` adı.
	    version: `Media Version` adı (== version_hash).
	    commit: True → geçişi tek commit ile kalıcı yapar. Köprü gibi kendi
	        commit'ini yöneten çağıranlar False geçer.

	Returns:
	    Denetim kaydının adı; sürüm zaten yayındaysa (idempotent no-op) None.
	"""
	return _apply_active_version(asset, version, action=ACTION_VERSION_PROMOTE, commit=commit)


def rollback_version(asset: str, *, commit: bool = True) -> str:
	"""`asset`i önceki yayına döndür — promote'un tersi (denetim izi ile).

	Önceki sürüm DB'den tek başına çıkarılamaz: sürümler silinmez (INV-06) ve
	"hangi is_active=0 sürüm bir önceki aktifti" bilgisini yalnız yayın geçmişi
	taşır. Bu yüzden hedef, bu varlığın en son promote/rollback DENETİM kaydının
	`from` alanından okunur (promote geçişi denetimi aynı transaction'da
	commit'ler, dolayısıyla yayınlanmış her geçişin izi vardır).

	Returns:
	    Dönülen (önceki) sürümün adı.

	Raises:
	    Yayın geçmişi yoksa ya da hedef sürüm artık bu varlığa ait değilse throw.
	"""
	hedef = _previous_active_version(asset)
	if not hedef:
		frappe.throw(_("Geri alınacak önceki yayın bulunamadı (varlık: {0}).").format(asset))
	_apply_active_version(asset, hedef, action=ACTION_VERSION_ROLLBACK, commit=commit)
	return hedef


def _apply_active_version(asset: str, version: str, *, action: str, commit: bool) -> str | None:
	"""promote ve rollback'in ortak atomik gövdesi."""
	meta = frappe.db.get_value("Media Version", version, ["asset"], as_dict=True)
	if not meta:
		frappe.throw(_("Sürüm bulunamadı: {0}").format(version))
	if meta.asset != asset:
		frappe.throw(
			_("Sürüm bu varlığa ait değil: {0} (varlık: {1}, sürümün varlığı: {2}).").format(
				version, asset, meta.asset
			)
		)
	durum = frappe.db.get_value("Media Asset", asset, "state")
	if durum != "ready":
		frappe.throw(
			_("Varlık yayına hazır değil (durum: {0}); sürüm yayına alınamaz.").format(durum or "?")
		)

	onceki = frappe.db.get_value("Media Asset", asset, "active_version")
	if onceki == version:
		# Zaten yayında — idempotent no-op; sahte bir geçiş kaydı yazma.
		return None

	_write_active_version_atomic(asset, version)
	_assert_active_consistent(asset, version)
	adl = _audit_version_transition(asset, action=action, from_version=onceki, to_version=version)
	if commit:
		frappe.db.commit()
	return adl


def _write_active_version_atomic(asset: str, version: str) -> None:
	"""Docstring'deki 3 cümle — TEK transaction, arada commit YOK.

	Sıra anlamlı: önce eski bayrak(lar) sıfırlanır, sonra doğruluğun kaynağı
	(`active_version`) yazılır, en son denormalize `is_active=1`. Araya bir
	`frappe.db.commit()` girerse atomiklik bozulur ve okuma yolu yarı-durum
	görebilir — `test_media_version_promote` bunu kırmızıyla yakalar.
	"""
	frappe.db.set_value(
		"Media Version", {"asset": asset, "is_active": 1}, "is_active", 0, update_modified=False
	)
	frappe.db.set_value("Media Asset", asset, "active_version", version, update_modified=False)
	frappe.db.set_value("Media Version", version, "is_active", 1, update_modified=False)


def _assert_active_consistent(asset: str, version: str) -> None:
	"""Geçiş sonrası: TAM bir aktif sürüm ve o da `active_version`.

	Controller'ın kendi kapısı (`_validate_active_consistency`) da çağrılır —
	sözleşmenin tek kaynağı orası; yazar onu atlamamalı, doğrulamalı.
	"""
	aktif = frappe.db.get_value("Media Asset", asset, "active_version")
	if aktif != version:
		frappe.throw(
			_("Geçiş tutarsız: varlığın aktif sürümü {0}, beklenen {1}.").format(aktif, version)
		)
	isaretli = frappe.get_all("Media Version", filters={"asset": asset, "is_active": 1}, pluck="name")
	if isaretli != [version]:
		frappe.throw(
			_("Geçiş tutarsız: aktif işaretli sürümler {0}, beklenen yalnız [{1}].").format(
				isaretli, version
			)
		)
	frappe.get_doc("Media Version", version)._validate_active_consistency()


def _previous_active_version(asset: str) -> str | None:
	"""Bu varlığın en son yayın geçişinin `from` sürümü (hâlâ geçerliyse)."""
	kayitlar = frappe.get_all(
		"Authorization Decision Log",
		filters={
			"object_doctype": "Media Asset",
			"object_name": asset,
			"action": ["in", [ACTION_VERSION_PROMOTE, ACTION_VERSION_ROLLBACK]],
		},
		fields=["context"],
		order_by="timestamp desc, creation desc",
		limit_page_length=1,
	)
	if not kayitlar:
		return None
	try:
		ctx = frappe.parse_json(kayitlar[0].get("context") or "{}") or {}
	except Exception:
		return None
	hedef = ctx.get("from")
	if hedef and frappe.db.get_value("Media Version", hedef, "asset") == asset:
		return hedef
	return None


def _audit_version_transition(
	asset: str, *, action: str, from_version: str | None, to_version: str
) -> str | None:
	"""Geçişi ADL'ye yaz. Commit ETMEZ — çağıranın transaction'ıyla birlikte
	kalıcı olur ki yayınlanmış her geçişin izi de yayınlanmış olsun."""
	from tradehub_core.audit import DECISION_ALLOW, SEVERITY_NORMAL, log_decision

	return log_decision(
		action=action,
		decision=DECISION_ALLOW,
		object_doctype="Media Asset",
		object_name=asset,
		tenant=frappe.db.get_value("Media Asset", asset, "owner_seller") or None,
		severity=SEVERITY_NORMAL,
		context={"from": from_version, "to": to_version},
	)
