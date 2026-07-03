# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Subscription Plan DocType controller.

Bir planın yetenek bayrakları (capability_flags) ve kotalarını (quota_limits)
JSON olarak tutar. Süper Admin yeni plan ekleyebilir veya mevcut planın
detaylarını panelden değiştirebilir.

Detay: docs/yetki/03-doctype-sablonlari.md §2, docs/yetki/01-karar-dosyasi.md §1
"""

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document

# Hem UPPERCASE (eski seed — FREE/STARTER/PRO/ENTERPRISE) hem lowercase
# (fixture/yeni custom plan'lar — pro-annual, premium) kabul. Mixed case (PrO)
# yasak — tutarlı görünüm için her plan kendi konvansiyonunda kalır.
_PLAN_CODE_PATTERN = re.compile(r"^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$")

# Kota metni → int limit için "sınırsız" eşdeğerleri (-1).
_UNLIMITED_TOKENS = frozenset({"sınırsız", "sinirsiz", "limitsiz", "unlimited", "∞", "-1"})


def _quota_value_from_row(row) -> int | None:
	"""pricing_features quota.* satırından int limit (saf).

	Semantik: is_included=0 → 0 (devre dışı); 'Sınırsız' → -1; sayısal → N.
	Parse edilemezse None → çağıran mevcut quota_limits değerini KORUR (bozulmaz).
	"""
	if not row.get("is_included"):
		return 0
	tv = (row.get("text_value") or "").strip().lower()
	if not tv:
		return None  # dahil ama değer yok → belirsiz, dokunma
	if tv in _UNLIMITED_TOKENS:
		return -1
	cleaned = tv.replace(".", "").replace(",", "").replace("%", "").replace(" ", "")
	try:
		return int(cleaned)
	except ValueError:
		return None


def merge_matrix_into_entitlement(rows, caps: dict, quotas: dict, valid_keys: set) -> tuple[dict, dict, bool]:
	"""pricing_features satırlarını capability_flags/quota_limits'e MERGE eder (saf).

	MERGE semantiği: matris satırı OLAN key'ler güncellenir (feature.* → is_included
	bool; quota.* → parse int); matris satırı OLMAYAN mevcut key'ler KORUNUR (veri
	kaybı yok). Yalnız `valid_keys` (Feature Catalog tanımlı, deprecated-olmayan)
	işlenir. (caps, quotas, changed) döner.
	"""
	caps = dict(caps)
	quotas = dict(quotas)
	changed = False
	for row in rows:
		fkey = (row.get("feature_key") or "").strip()
		if not fkey or fkey not in valid_keys:
			continue
		if fkey.startswith("feature."):
			caps[fkey] = bool(row.get("is_included"))
			changed = True
		elif fkey.startswith("quota."):
			qv = _quota_value_from_row(row)
			if qv is not None:
				quotas[fkey] = qv
				changed = True
	return caps, quotas, changed


class SubscriptionPlan(Document):
	def validate(self) -> None:
		self._normalize_plan_code()
		# Matris (pricing_features) → capability_flags/quota_limits senkronu
		# VALİDASYONDAN ÖNCE: admin "Paket İçeriği" matrisinde bir özelliği
		# işaretleyince entitlement (has_feature/within_quota) ANINDA yansısın.
		# Önceden pricing_features yalnız storefront gösterimini besliyordu;
		# capability_flags JSON'a bağlı DEĞİLDİ → işaret entitlement'a ulaşmıyordu.
		self._sync_entitlement_from_matrix()
		self._validate_capability_flags()
		self._validate_quota_limits()
		self._validate_pricing()
		self._sanitize_rich_text_fields()

	def _sync_entitlement_from_matrix(self) -> None:
		"""pricing_features (admin matris) → capability_flags + quota_limits JSON.

		Yalnız Feature Catalog'ta tanımlı + deprecated-olmayan key'leri işler
		(validasyon patlamasın). Asıl birleştirme saf `merge_matrix_into_entitlement`
		fonksiyonunda (test edilebilir).
		"""
		rows = self.get("pricing_features") or []
		if not rows:
			return
		valid = {
			r.name
			for r in frappe.get_all("Feature Catalog", filters={"is_deprecated": 0}, fields=["name"])
		}
		caps, quotas, changed = merge_matrix_into_entitlement(
			rows, self.get_capability_flags(), self.get_quota_limits(), valid
		)
		if changed:
			self.capability_flags = json.dumps(caps, ensure_ascii=False, sort_keys=True)
			self.quota_limits = json.dumps(quotas, ensure_ascii=False, sort_keys=True)

	def _sanitize_rich_text_fields(self) -> None:
		"""Faz H.2 — HTML/Long Text alanları XSS'e karşı sanitize et.

		`description`, `short_tagline` storefront pricing card'larında render
		ediliyor. Süper admin (veya Marketplace Admin) `<script>` veya
		`<img onerror>` payload'ı kaydederse storefront tarafında çalışabilir.
		Frappe'nin built-in `sanitize_html` allowlist-based filtre uygular —
		`p`, `br`, `strong`, `em`, `ul/ol/li`, `a[href]` gibi temel tag'ler
		korunur, `<script>` ve event handler'lar (onclick, onerror) düşer.
		"""
		from frappe.utils import sanitize_html

		for field in ("description", "short_tagline", "badge_label", "cta_label"):
			raw = self.get(field)
			if raw and isinstance(raw, str):
				self.set(field, sanitize_html(raw))

	def _normalize_plan_code(self) -> None:
		"""plan_code tutarlı tek-case (lowercase veya UPPERCASE) içermeli.

		Mevcut DB'de hem UPPERCASE (eski seed) hem lowercase (fixture) plan'lar
		var; pattern her ikisini de kabul eder (Faz I fix). `_normalize` artık
		case'i ZORLA değiştirmez — sadece whitespace strip + pattern validate.
		"""
		if not self.plan_code:
			return
		code = self.plan_code.strip()
		if not _PLAN_CODE_PATTERN.match(code):
			frappe.throw(
				_(
					"Plan Code lowercase VEYA UPPERCASE (mixed case değil) olarak "
					"yazılmalı; sadece harf/rakam/tire/alt-çizgi içerebilir "
					"(örn. 'free', 'pro-annual', 'ENTERPRISE')."
				)
			)
		self.plan_code = code

	def _validate_capability_flags(self) -> None:
		"""capability_flags geçerli JSON olmalı, key'ler Feature Catalog'ta tanımlı olmalı."""
		flags = self._parse_json_field("capability_flags")
		if not flags:
			return
		if not isinstance(flags, dict):
			frappe.throw(_("Capability Flags JSON nesnesi (dict) olmalı."))

		# Her key Feature Catalog'ta tanımlı VE deprecated olmamalı.
		# Faz E.2 — deprecated key sızıntısına karşı koruma: önceden sadece
		# var/yok kontrol ediliyordu, `is_deprecated=1` key (örn. eski
		# `feature.rfq_module`) sessizce kabul ediliyordu.
		# Planda HALİHAZIRDA kayıtlı capability key'leri — bunlar deprecated olsa
		# bile (sonradan deprecate edildiyse) korunur; aksi halde komisyon gibi
		# başka bir alanı değiştirmek bile imkânsız olurdu. Sadece YENİ eklenen
		# deprecated key reddedilir.
		existing_keys: set[str] = set()
		before = self.get_doc_before_save()
		if before:
			try:
				existing_keys = set((json.loads(before.capability_flags or "{}") or {}).keys())
			except (ValueError, TypeError):
				existing_keys = set()

		unknown_keys = []
		deprecated_keys = []
		for key, value in flags.items():
			if not key.startswith("feature."):
				frappe.throw(_("Capability flag key 'feature.' ile başlamalı: '{0}'").format(key))
			if not isinstance(value, bool):
				frappe.throw(
					_("Capability flag '{0}' değeri boolean olmalı (true/false), şu an: {1}").format(
						key, type(value).__name__
					)
				)
			fc = frappe.db.get_value("Feature Catalog", key, ["is_deprecated"], as_dict=True)
			if not fc:
				unknown_keys.append(key)
			elif fc.get("is_deprecated") and key not in existing_keys:
				deprecated_keys.append(key)

		if unknown_keys:
			frappe.throw(
				_("Capability flag key'leri Feature Catalog'ta tanımlı olmalı. Tanımsız key'ler: {0}").format(
					", ".join(unknown_keys)
				),
				title=_("Tanımsız Feature Key"),
			)
		if deprecated_keys:
			frappe.throw(
				_("Şu Feature Catalog key'leri deprecated olarak işaretli ve plan'a yazılamaz: {0}").format(
					", ".join(deprecated_keys)
				),
				title=_("Deprecated Feature Key"),
			)

	def _validate_quota_limits(self) -> None:
		"""quota_limits geçerli JSON, key'ler 'quota.', değerler integer olmalı."""
		quotas = self._parse_json_field("quota_limits")
		if not quotas:
			return
		if not isinstance(quotas, dict):
			frappe.throw(_("Quota Limits JSON nesnesi (dict) olmalı."))

		for key, value in quotas.items():
			if not key.startswith("quota."):
				frappe.throw(_("Quota key 'quota.' ile başlamalı: '{0}'").format(key))
			if not isinstance(value, int) or isinstance(value, bool):
				# bool subclass of int, exclude
				frappe.throw(
					_("Quota '{0}' değeri tam sayı olmalı, şu an: {1}").format(key, type(value).__name__)
				)
			if value < -1:
				# -1 = sınırsız, 0 = devre dışı, pozitif = limit
				frappe.throw(_("Quota '{0}' değeri -1 (sınırsız) veya >= 0 olmalı.").format(key))

	def _validate_pricing(self) -> None:
		"""Fiyat negatif olmamalı."""
		if (self.monthly_price or 0) < 0:
			frappe.throw(_("Monthly Price negatif olamaz."))
		if (self.yearly_price or 0) < 0:
			frappe.throw(_("Yearly Price negatif olamaz."))
		if (self.trial_days or 0) < 0:
			frappe.throw(_("Trial Days negatif olamaz."))

	def _parse_json_field(self, fieldname: str):
		"""JSON field'ını parse et — string ya da dict olabilir."""
		val = self.get(fieldname)
		if not val:
			return None
		if isinstance(val, dict | list):
			return val
		try:
			return json.loads(val)
		except (json.JSONDecodeError, TypeError) as e:
			frappe.throw(_("{0} geçerli JSON değil: {1}").format(fieldname, str(e)))

	def get_capability_flags(self) -> dict:
		"""Capability flags dict olarak döner."""
		return self._parse_json_field("capability_flags") or {}

	def get_quota_limits(self) -> dict:
		"""Quota limits dict olarak döner."""
		return self._parse_json_field("quota_limits") or {}

	def get_allowed_region_codes(self) -> list[str]:
		"""İzin verilen Region code listesi."""
		return [row.region for row in (self.allowed_regions or [])]

	def has_capability(self, feature_key: str) -> bool:
		"""Bu plan verilen capability'ye sahip mi?"""
		return bool(self.get_capability_flags().get(feature_key, False))

	def get_quota(self, quota_key: str, default: int = 0) -> int:
		"""Bu plan için verilen quota değeri (-1 = sınırsız)."""
		return int(self.get_quota_limits().get(quota_key, default))


def reconcile_all_plans(dry_run: int | bool = 1) -> dict:
	"""Geriye-dönük backfill — mevcut planların capability_flags/quota_limits'ini
	pricing_features matrisi ile hizalar (yeni senkron mantığını uygular).

	dry_run=1 (varsayılan): HİÇBİR ŞEY KAYDETMEZ, yalnız plan-başına farkı raporlar
	(gained = matriste işaretli artık entitlement'a gelen; lost = matriste işaretsiz
	olduğu için kalkacak). dry_run=0 → farkı uygular + kaydeder + cache flush.

	Çağrı: bench execute tradehub_core...subscription_plan.reconcile_all_plans
	       --kwargs '{"dry_run": 1}'
	"""
	dry_run = bool(int(dry_run))
	report: dict[str, dict] = {}
	for pn in frappe.get_all("Subscription Plan", pluck="name"):
		plan = frappe.get_doc("Subscription Plan", pn)
		before = {k: v for k, v in plan.get_capability_flags().items() if v}
		plan._sync_entitlement_from_matrix()
		after = {k: v for k, v in plan.get_capability_flags().items() if v}
		gained = sorted(k for k in after if k not in before)
		lost = sorted(k for k in before if k not in after)
		report[pn] = {"gained": gained, "lost": lost, "changed": bool(gained or lost)}
		if not dry_run and (gained or lost):
			plan.save(ignore_permissions=True)
	if not dry_run:
		frappe.db.commit()
	report["_meta"] = {"dry_run": dry_run, "plans": len([k for k in report if k != "_meta"])}
	return report
