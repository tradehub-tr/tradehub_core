# Copyright (c) 2024, TradeHub Team and contributors
# For license information, please see license.txt

"""
ECA (Event-Condition-Action) Rule Dispatcher.
Evaluates and executes ECA rules based on document events.

The ECA system allows defining rules that:
- Trigger on specific DocType events (e.g., on_submit, on_update)
- Evaluate conditions against document fields
- Execute actions (email, webhook, field updates, etc.)
"""

import frappe
from frappe.utils import cint, flt, getdate, now_datetime


class ECARejectionError(Exception):
	"""reject_row aksiyonu satırı reddetti — bulk import bunu yakalayıp skip eder.

	validate fazında fırlatılır; doc.insert() DB yazımından önce iptal olur
	(hiçbir şey yazılmaz). Bulk runner bu istisnayı yakalayıp satırı 'eca_rejected'
	olarak raporlar (genel 'system' hatasından ayrı).
	"""


def evaluate_rules(doc, method=None):
	"""
	Evaluate all active ECA rules for a document event.

	This is the main entry point for ECA rule processing.
	Called from doc_events hooks for each document operation.

	Args:
	    doc: The Frappe document that triggered the event.
	    method (str, optional): The doc event method name
	        (e.g., 'on_submit', 'on_update', 'before_save').

	Example:
	    # In hooks.py
	    doc_events = {
	        "*": {
	            "on_update": "tradehub_core.eca.dispatcher.evaluate_rules",
	            "on_submit": "tradehub_core.eca.dispatcher.evaluate_rules",
	        }
	    }
	"""
	if not method:
		return

	# Anti-recursion: Skip system log doctypes
	if doc.doctype in [
		"Error Log",
		"Log",
		"Console Log",
		"Access Log",
		"Activity Log",
		"ECA Rule Log",
		"Prepared Report",
		"Version",
		"Scheduled Job Log",
	]:
		return

	# Skip if ECA is disabled globally
	if not _is_eca_enabled():
		return

	# Get applicable rules for this DocType and event
	rules = _get_applicable_rules(doc.doctype, method)

	if not rules:
		return

	for rule in rules:
		try:
			_process_rule(doc, rule, method)
		except Exception as e:
			_log_rule_error(rule, doc, method, e)


def _is_eca_enabled():
	"""
	Check if ECA rule processing is enabled globally.

	Analytics Settings doctype yoksa default ON — ECA bulk-only context
	zaten frappe.flags.in_bulk_import ile koruma altında.

	Returns:
	    bool: True if ECA is enabled, False otherwise.
	"""
	try:
		if not frappe.db.exists("DocType", "Analytics Settings"):
			return 1  # Analytics Settings yok → default ON
		val = frappe.db.get_single_value("Analytics Settings", "enable_eca_rules")
		# None (hiç set edilmemiş) → default ON; explicit 0 → OFF
		return 1 if val is None else cint(val)
	except Exception:
		# Prevent recursion by suppressing error logging here
		frappe.log_error("_is_eca_enabled: Analytics Settings check failed", "eca_dispatcher")
		return 1


def _get_applicable_rules(doctype, event):
	"""
	Get all active ECA rules applicable to a DocType and event.

	Args:
	    doctype (str): The DocType name.
	    event (str): The event name (e.g., 'on_update', 'on_submit').

	Returns:
	    list: List of ECA Rule documents.
	"""
	cache_key = f"eca_rules:{doctype}:{event}"
	rules = frappe.cache().get_value(cache_key)

	if rules is None:
		rules = frappe.get_all(
			"ECA Rule",
			filters={"doctype_name": doctype, "event": event, "enabled": 1},
			fields=["name", "condition", "action_type", "action_template", "priority"],
			order_by="priority asc",
		)
		# Cache for 5 minutes
		frappe.cache().set_value(cache_key, rules, expires_in_sec=300)

	return rules


def _process_rule(doc, rule, event):
	"""
	Process a single ECA rule against a document.

	Args:
	    doc: The document to evaluate.
	    rule (dict): The ECA Rule data.
	    event (str): The event name.
	"""
	# Load full rule document for detailed processing
	rule_doc = frappe.get_cached_doc("ECA Rule", rule.name)

	# Evaluate condition
	if not _evaluate_condition(doc, rule_doc):
		return

	# Execute action
	_execute_action(doc, rule_doc, event)

	# Log successful execution
	_log_rule_execution(rule_doc, doc, event, success=True)


def _evaluate_condition(doc, rule):
	"""
	Evaluate the condition expression of an ECA rule.

	Args:
	    doc: The document to evaluate against.
	    rule: The ECA Rule document.

	Returns:
	    bool: True if condition is met, False otherwise.
	"""
	condition = rule.get("condition")

	# No condition means always execute
	if not condition or condition.strip() == "":
		return True

	try:
		# Create evaluation context with document data
		context = _get_evaluation_context(doc)

		# Evaluate the condition
		result = frappe.safe_eval(condition, context)
		return bool(result)

	except Exception as e:
		frappe.log_error(
			message=f"ECA Rule condition evaluation failed: {e}\nCondition: {condition}",
			title=f"ECA Rule Error: {rule.name}",
		)
		return False


def _get_evaluation_context(doc):
	"""
	Build the evaluation context for condition expressions.

	Args:
	    doc: The document being evaluated.

	Returns:
	    dict: Context dictionary for safe_eval.
	"""
	return {
		"doc": doc.as_dict(),
		"frappe": frappe._dict(
			{
				"utils": frappe._dict(
					{"getdate": getdate, "now_datetime": now_datetime, "cint": cint, "flt": flt}
				),
				"session": frappe._dict({"user": frappe.session.user}),
			}
		),
		"True": True,
		"False": False,
		"None": None,
	}


def _execute_action(doc, rule, event):
	"""
	Execute the action defined in an ECA rule.

	Args:
	    doc: The document that triggered the rule.
	    rule: The ECA Rule document.
	    event (str): The event name.
	"""
	action_type = rule.get("action_type")

	if action_type == "Email":
		_execute_email_action(doc, rule)
	elif action_type == "Webhook":
		_execute_webhook_action(doc, rule)
	elif action_type == "Field Update":
		_execute_field_update_action(doc, rule)
	elif action_type == "Custom Script":
		_execute_custom_script_action(doc, rule)
	elif action_type == "Create Document":
		_execute_create_document_action(doc, rule)
	else:
		frappe.log_error(message=f"Unknown action type: {action_type}", title=f"ECA Rule Error: {rule.name}")


def _execute_email_action(doc, rule):
	"""
	Execute an email notification action.

	Args:
	    doc: The source document.
	    rule: The ECA Rule with email configuration.
	"""
	template_name = rule.get("action_template")
	if not template_name:
		return

	try:
		template = frappe.get_cached_doc("ECA Action Template", template_name)

		# Build recipient list
		recipients = _get_recipients(doc, template)

		if not recipients:
			return

		# Render email content
		context = {"doc": doc.as_dict()}
		subject = frappe.render_template(template.get("subject") or "", context)
		message = frappe.render_template(template.get("message") or "", context)

		# Send email
		frappe.sendmail(
			recipients=recipients,
			subject=subject,
			message=message,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
			now=True,
		)

	except Exception as e:
		frappe.log_error(message=f"Email action failed: {e}", title=f"ECA Rule Email Error: {rule.name}")


def _execute_webhook_action(doc, rule):
	"""
	Execute a webhook action.

	Args:
	    doc: The source document.
	    rule: The ECA Rule with webhook configuration.
	"""
	template_name = rule.get("action_template")
	if not template_name:
		return

	try:
		template = frappe.get_cached_doc("ECA Action Template", template_name)
		webhook_url = template.get("webhook_url")

		if not webhook_url:
			return

		import json

		# Prepare payload
		payload = {
			"doctype": doc.doctype,
			"name": doc.name,
			"data": doc.as_dict(),
			"event": rule.get("event"),
		}

		headers = {"Content-Type": "application/json"}

		# Add custom headers if specified
		custom_headers = template.get("webhook_headers")
		if custom_headers:
			try:
				headers.update(json.loads(custom_headers))
			except json.JSONDecodeError:
				pass

		# Make request in background
		frappe.enqueue(
			"tradehub_core.eca.dispatcher._send_webhook",
			queue="short",
			url=webhook_url,
			payload=payload,
			headers=headers,
		)

	except Exception as e:
		frappe.log_error(message=f"Webhook action failed: {e}", title=f"ECA Rule Webhook Error: {rule.name}")


def _send_webhook(url, payload, headers):
	"""
	Send webhook request (called in background).

	Args:
	    url (str): Webhook URL.
	    payload (dict): Request payload.
	    headers (dict): Request headers.
	"""
	import json

	import requests

	# F-022: SSRF koruması — private/reserved IP aralıklarını engelle
	try:
		from tradehub_core.utils.feed_security import validate_feed_url

		validate_feed_url(url)
	except Exception as e:
		frappe.log_error(message=f"Webhook URL SSRF validation failed: {url} — {e}", title="ECA Webhook SSRF Block")
		return

	try:
		response = requests.post(url, data=json.dumps(payload, default=str), headers=headers, timeout=30)
		response.raise_for_status()
	except Exception as e:
		frappe.log_error(message=f"Webhook request failed: {e}\nURL: {url}", title="ECA Webhook Error")


def _execute_field_update_action(doc, rule):
	"""
	Execute a field update action on the document.

	Args:
	    doc: The document to update.
	    rule: The ECA Rule with field update configuration.
	"""
	template_name = rule.get("action_template")
	if not template_name:
		return

	try:
		template = frappe.get_cached_doc("ECA Action Template", template_name)
		updates = template.get("field_updates") or []

		for update in updates:
			fieldname = update.get("fieldname")
			value_type = update.get("value_type", "Static")
			value = update.get("value")

			if not fieldname:
				continue

			if value_type == "Expression":
				context = _get_evaluation_context(doc)
				value = frappe.safe_eval(value, context)

			# Update the document field
			doc.db_set(fieldname, value, update_modified=False)

	except Exception as e:
		frappe.log_error(
			message=f"Field update action failed: {e}", title=f"ECA Rule Field Update Error: {rule.name}"
		)


def _execute_custom_script_action(doc, rule):
	"""
	Execute a custom Python script action defined on an ECA Rule.

	Güvenlik: önceki implementasyon `exec(script, context)` kullanıyordu —
	`context` içinde `frappe` modülü ve `doc` mevcut olduğundan rule'a yazma
	yetkisi olan herhangi bir kullanıcı arbitrary Python (DB, file system,
	subprocess) çalıştırabilirdi. Yeni davranış:

	1. Sadece System Manager veya Marketplace Admin rolüne sahip kullanıcı
	   tarafından son düzenlenmiş kurallar çalıştırılır.
	2. Kod Frappe'nin RestrictedPython tabanlı `safe_exec`'inden geçirilir
	   (server_script_enabled site config'i zorunlu).
	3. server_script_enabled aktif değilse no-op + log.
	"""
	script = rule.get("custom_script")
	if not script:
		return

	# (1) Rule'a son dokunan kullanıcının yetkisini doğrula
	modified_by = rule.get("modified_by") or rule.get("owner")
	if modified_by and modified_by != "Administrator":
		roles = set(frappe.get_roles(modified_by))
		if not roles & {"System Manager", "Marketplace Admin"}:
			frappe.log_error(
				message=(
					f"ECA Rule {rule.name} custom_script reddedildi: rule sahibi "
					f"{modified_by} System Manager / Marketplace Admin değil."
				),
				title="ECA Rule Script Permission Denied",
			)
			return

	# (2) Server scripts global olarak kapalıysa çalıştırma
	try:
		from frappe.utils.safe_exec import is_safe_exec_enabled, safe_exec
	except ImportError:
		frappe.log_error(message="frappe.utils.safe_exec import edilemedi", title="ECA safe_exec missing")
		return

	if not is_safe_exec_enabled():
		frappe.log_error(
			message=(
				f"ECA Rule {rule.name} custom_script atlandı: site config'inde "
				"`server_script_enabled` aktif değil."
			),
			title="ECA Rule Script Skipped",
		)
		return

	# (3) safe_exec sandbox'ında çalıştır
	try:
		context = _get_evaluation_context(doc)
		context["doc"] = doc  # Document instance — safe_exec writable methods kısıtlı
		safe_exec(script, _globals=context, _locals=None)
	except Exception as e:
		frappe.log_error(
			message=f"Custom script action failed: {e}\nScript: {script[:500]}",
			title=f"ECA Rule Script Error: {rule.name}",
		)


def _execute_create_document_action(doc, rule):
	"""
	Execute a create document action.

	Args:
	    doc: The source document.
	    rule: The ECA Rule with document creation config.
	"""
	template_name = rule.get("action_template")
	if not template_name:
		return

	try:
		template = frappe.get_cached_doc("ECA Action Template", template_name)
		target_doctype = template.get("target_doctype")

		if not target_doctype:
			return

		# Build new document from template
		new_doc_data = {"doctype": target_doctype}

		# Map fields from source to target
		field_mappings = template.get("field_mappings") or []
		for mapping in field_mappings:
			source_field = mapping.get("source_field")
			target_field = mapping.get("target_field")

			if source_field and target_field:
				value = doc.get(source_field)
				if value is not None:
					new_doc_data[target_field] = value

		# Create and insert new document
		new_doc = frappe.get_doc(new_doc_data)
		new_doc.flags.ignore_permissions = True
		new_doc.insert()

	except Exception as e:
		frappe.log_error(
			message=f"Create document action failed: {e}", title=f"ECA Rule Create Doc Error: {rule.name}"
		)


def _get_recipients(doc, template):
	"""
	Get email recipients based on template configuration.

	Args:
	    doc: The source document.
	    template: The ECA Action Template.

	Returns:
	    list: List of email addresses.
	"""
	recipients = []

	# Static recipients
	static_recipients = template.get("recipients")
	if static_recipients:
		recipients.extend([r.strip() for r in static_recipients.split(",") if r.strip()])

	# Dynamic recipients from document field
	recipient_field = template.get("recipient_field")
	if recipient_field and doc.get(recipient_field):
		field_value = doc.get(recipient_field)
		if isinstance(field_value, str):
			recipients.extend([r.strip() for r in field_value.split(",") if r.strip()])

	# Recipients from linked user/contact
	recipient_link_field = template.get("recipient_link_field")
	if recipient_link_field and doc.get(recipient_link_field):
		linked_user = doc.get(recipient_link_field)
		email = frappe.db.get_value("User", linked_user, "email")
		if email:
			recipients.append(email)

	return list(set(recipients))  # Remove duplicates


def _log_rule_execution(rule, doc, event, success=True):
	"""
	Log ECA rule execution for auditing.

	Args:
	    rule: The ECA Rule document.
	    doc: The document that triggered the rule.
	    event (str): The event name.
	    success (bool): Whether execution was successful.
	"""
	try:
		log = frappe.get_doc(
			{
				"doctype": "ECA Rule Log",
				"eca_rule": rule.name,
				"reference_doctype": doc.doctype,
				"reference_name": doc.name,
				"event": event,
				"status": "Success" if success else "Failed",
				"execution_time": now_datetime(),
			}
		)
		log.flags.ignore_permissions = True
		log.insert()
	except Exception:
		frappe.log_error("_log_rule_execution: failed to insert ECA Rule Log", "eca_dispatcher")
		pass  # Don't fail the main operation for logging issues


def _log_rule_error(rule, doc, event, error):
	"""
	Log ECA rule execution error.

	Args:
	    rule (dict): The ECA Rule data.
	    doc: The document that triggered the rule.
	    event (str): The event name.
	    error: The exception that occurred.
	"""
	frappe.log_error(
		message=f"ECA Rule execution failed\nRule: {rule.name}\nDocType: {doc.doctype}\nDoc: {doc.name}\nEvent: {event}\nError: {error}",
		title=f"ECA Rule Error: {rule.name}",
	)

	# Also log to ECA Rule Log
	try:
		log = frappe.get_doc(
			{
				"doctype": "ECA Rule Log",
				"eca_rule": rule.name,
				"reference_doctype": doc.doctype,
				"reference_name": doc.name,
				"event": event,
				"status": "Failed",
				"error_message": str(error)[:2000],
				"execution_time": now_datetime(),
			}
		)
		log.flags.ignore_permissions = True
		log.insert()
	except Exception:
		frappe.log_error("_log_rule_error: failed to insert ECA Rule Log for failed rule", "eca_dispatcher")
		pass


def clear_eca_cache(doctype=None, event=None):
	"""
	Clear ECA rule cache.

	Args:
	    doctype (str, optional): Specific DocType to clear cache for.
	    event (str, optional): Specific event to clear cache for.
	"""
	if doctype and event:
		frappe.cache().delete_value(f"eca_rules:{doctype}:{event}")
	elif doctype:
		# Clear all events for this DocType
		events = ["on_update", "on_submit", "on_cancel", "before_save", "after_insert"]
		for evt in events:
			frappe.cache().delete_value(f"eca_rules:{doctype}:{evt}")
	else:
		# Clear all ECA cache
		frappe.cache().delete_keys("eca_rules:*")


# ===========================================================================
# BULK IMPORT TWO-PHASE EXTENSION
# ===========================================================================
# Bulk import için: Seller Phase → Admin Phase. Sadece frappe.flags.in_bulk_import
# True iken fire eder. Single-edit flow regresyon almaz.

import time  # noqa: E402

from tradehub_core.eca.safe_regex import RegexError, SafeRegex  # noqa: E402
from tradehub_core.eca.validators import (  # noqa: E402
	filter_doc_for_seller,
	is_action_allowed,
	is_field_writable,
)


def evaluate_rules_two_phase(doc, method=None):
	"""Two-phase ECA execution — bulk import için tek giriş noktası.

	Faz 1: Seller Phase
	Faz 2: Admin Phase (gate-keeper)
	"""
	if not getattr(frappe.flags, "in_bulk_import", False):
		return  # single-edit flow → no-op
	try:
		if not _is_eca_enabled():
			return
	except Exception:
		frappe.log_error("evaluate_rules_two_phase: _is_eca_enabled check failed", "eca_dispatcher")
		return

	doctype = getattr(doc, "doctype", None)
	if not doctype:
		return
	event = method or "before_save"

	# Faz 1: Seller Phase
	seller_rules = _get_phase_rules_v2(doctype, event, "Seller Phase", doc)
	for rule in seller_rules:
		_process_rule_v2(doc, rule, event)
	# Faz 2: Admin Phase
	admin_rules = _get_phase_rules_v2(doctype, event, "Admin Phase", doc)
	for rule in admin_rules:
		_process_rule_v2(doc, rule, event)

	# reject_row aksiyonu flag set ettiyse insert'i burada (per-rule try/except
	# DIŞINDA) iptal et → DB yazımından ÖNCEKİ event'te fırlatınca hiçbir şey
	# yazılmaz, bulk runner ECARejectionError'ı yakalayıp satırı skip olarak
	# raporlar. after_insert/on_update'te raise ETME (doc zaten yazılı → orphan).
	if getattr(doc.flags, "eca_rejected", False) and event in ("validate", "before_save", "before_insert"):
		raise ECARejectionError(
			getattr(doc.flags, "eca_reject_reason", "") or "ECA kuralı tarafından reddedildi"
		)


def _get_phase_rules_v2(doctype: str, event: str, phase: str, doc) -> list:
	"""Belirli faz için uygulanabilir kurallar — 5 dk cache."""
	cache_key = f"eca_rules_v2:{doctype}:{event}:{phase}"
	cached = frappe.cache.get_value(cache_key)
	if cached is None:
		cached = frappe.get_all(
			"ECA Rule",
			filters={
				"reference_doctype": doctype,
				"event": event,
				"execution_phase": phase,
				"enabled": 1,
			},
			fields=[
				"name",
				"rule_scope",
				"seller_profile",
				"owner_role",
				"priority",
				"condition",
				"action_type",
				"action_template",
				"context_filter",
			],
			order_by="priority asc",
		)
		frappe.cache.set_value(cache_key, cached, expires_in_sec=300)
	return _filter_rules_for_doc_v2(cached, doc)


def _filter_rules_for_doc_v2(rules: list, doc) -> list:
	"""Per-seller kurallarda doc sahibine göre filtrele + context_filter."""
	doc_seller = getattr(doc, "seller_profile", None)
	out = []
	for r in rules:
		cf = r.get("context_filter") or ""
		if cf == "bulk_import" and not getattr(frappe.flags, "in_bulk_import", False):
			continue
		if r.get("rule_scope") == "Per-Seller":
			if not doc_seller or r.get("seller_profile") != doc_seller:
				continue
		out.append(r)
	return out


def _process_rule_v2(doc, rule: dict, event: str) -> None:
	"""Bir kuralı izole çalıştır — log + exception izolasyonu."""
	start = time.time()
	log = {
		"eca_rule": rule.get("name"),
		"reference_doctype": getattr(doc, "doctype", ""),
		"reference_name": getattr(doc, "name", "") or "",
		"event": event,
		"execution_phase": ("Seller Phase" if rule.get("owner_role") == "Seller" else "Admin Phase"),
	}
	if hasattr(frappe.flags, "get"):
		log["bulk_import_job"] = frappe.flags.get("bulk_import_job")

	try:
		if hasattr(doc, "as_dict"):
			try:
				log["doc_snapshot_before"] = frappe.as_json(doc.as_dict())[:2000]
			except Exception:
				frappe.log_error("_process_rule_v2: doc_snapshot_before serialization failed", "eca_dispatcher")
				pass

		cond_ok = _evaluate_condition_v2(doc, rule)
		log["condition_result"] = bool(cond_ok)
		if not cond_ok:
			log["status"] = "condition_false"
			return

		action_ok = _execute_action_v2(doc, rule)
		log["action_executed"] = bool(action_ok)
		log["status"] = "success" if action_ok else "action_failed"

		if hasattr(doc, "as_dict"):
			try:
				log["doc_snapshot_after"] = frappe.as_json(doc.as_dict())[:2000]
			except Exception:
				frappe.log_error("_process_rule_v2: doc_snapshot_after serialization failed", "eca_dispatcher")
				pass
	except Exception as e:
		log["status"] = "error"
		log["error_message"] = str(e)[:500]
		frappe.log_error(
			title=f"ECA rule {rule.get('name')} error",
			message=frappe.get_traceback(),
		)
	finally:
		log["execution_time_ms"] = int((time.time() - start) * 1000)
		_write_log_v2(log)


def _evaluate_condition_v2(doc, rule: dict) -> bool:
	"""Condition Python eval — role-aware field görünürlüğü + SafeRegex."""
	cond_str = (rule.get("condition") or "").strip()
	if not cond_str:
		return True

	owner_role = rule.get("owner_role", "Seller")
	doc_dict = doc.as_dict() if hasattr(doc, "as_dict") else dict(doc)
	if owner_role == "Seller":
		doc_dict = filter_doc_for_seller(doc_dict, doctype=getattr(doc, "doctype", "Listing"))

	context = {
		"doc": doc_dict,
		"re": SafeRegex,
		"frappe": {
			"utils": {
				"cint": frappe.utils.cint,
				"flt": frappe.utils.flt,
				"getdate": frappe.utils.getdate,
				"now_datetime": frappe.utils.now_datetime,
			},
			"session": {"user": frappe.session.user},
		},
		"cint": frappe.utils.cint,
		"flt": frappe.utils.flt,
		"True": True,
		"False": False,
		"None": None,
	}

	try:
		return bool(frappe.safe_eval(cond_str, context))
	except RegexError as e:
		frappe.log_error(
			title=f"ECA SafeRegex blocked: {rule.get('name')}",
			message=f"Pattern: {cond_str[:200]}\nError: {e}",
		)
		return False
	except Exception as e:
		frappe.log_error(
			title=f"ECA condition eval error: {rule.get('name')}",
			message=f"Condition: {cond_str[:200]}\nError: {e}",
		)
		return False


def _execute_action_v2(doc, rule: dict) -> bool:
	"""Action execution — role whitelist + rate limit + dispatch."""
	action_type = rule.get("action_type")
	owner_role = rule.get("owner_role", "Seller")

	if not is_action_allowed(action_type, owner_role):
		frappe.log_error(
			title=f"ECA action denied: {rule.get('name')}",
			message=f"Owner role {owner_role} cannot use action {action_type}",
		)
		return False

	if action_type in ("email", "webhook"):
		if not _check_rate_limit_v2(rule):
			return False

	template_name = rule.get("action_template")
	if not template_name:
		return False
	try:
		template = frappe.get_doc("ECA Action Template", template_name)
	except Exception:
		frappe.log_error(f"_execute_action_v2: failed to load ECA Action Template '{template_name}'", "eca_dispatcher")
		return False

	if action_type == "field_update":
		return _do_field_update_v2(doc, rule, template, owner_role)
	if action_type == "reject_row":
		return _do_reject_row_v2(doc, rule, template)
	if action_type == "email":
		return _do_email_v2(doc, rule, template)
	if action_type == "webhook":
		return _do_webhook_v2(doc, rule, template)
	if action_type == "create_document":
		return _do_create_document_v2(doc, rule, template)
	if action_type == "custom_script":
		return _do_custom_script_v2(doc, rule, template)
	return False


def _check_rate_limit_v2(rule: dict) -> bool:
	"""Per-rule per-hour rate limit."""
	template_name = rule.get("action_template")
	if not template_name:
		return True
	limit = (
		frappe.db.get_value(
			"ECA Action Template",
			template_name,
			"rate_limit_per_hour",
		)
		or 50
	)
	bucket = frappe.utils.now_datetime().strftime("%Y%m%d%H")
	key = f"eca_ratelimit_v2:{rule.get('name')}:{bucket}"
	current = frappe.cache.get_value(key) or 0
	if current >= limit:
		return False
	frappe.cache.set_value(key, current + 1, expires_in_sec=3700)
	return True


def _do_field_update_v2(doc, rule, template, owner_role) -> bool:
	"""Field update — whitelist guard."""
	import json

	try:
		updates = json.loads(template.field_updates or "[]")
	except Exception:
		frappe.log_error(f"_do_field_update_v2: failed to parse field_updates JSON for template '{template.name}'", "eca_dispatcher")
		return False
	if not isinstance(updates, list):
		return False
	changed = False
	for upd in updates:
		if not isinstance(upd, dict):
			continue
		fieldname = upd.get("fieldname")
		value_expr = upd.get("value")
		if not fieldname:
			continue
		if not is_field_writable(
			fieldname,
			owner_role,
			doctype=getattr(doc, "doctype", "Listing"),
		):
			frappe.log_error(
				title=f"ECA field write blocked: {rule.get('name')}",
				message=f"Role {owner_role} cannot write {fieldname}",
			)
			continue
		try:
			value = _eval_value_expr_v2(value_expr, doc)
			setattr(doc, fieldname, value)
			changed = True
		except Exception as e:
			frappe.log_error(f"ECA field set failed: {e}", "_do_field_update_v2")
	return changed


def _eval_value_expr_v2(expr, doc):
	"""Field update value Python eval — SafeRegex injected."""
	if expr is None:
		return None
	if not isinstance(expr, str):
		return expr
	if not expr.strip():
		return expr
	ctx = {
		"doc": doc.as_dict() if hasattr(doc, "as_dict") else dict(doc),
		"cint": frappe.utils.cint,
		"flt": frappe.utils.flt,
		"re": SafeRegex,
	}
	try:
		return frappe.safe_eval(expr, ctx)
	except Exception:
		frappe.log_error(f"_eval_value_expr_v2: safe_eval failed for expr '{expr[:200]}', falling back to literal", "eca_dispatcher")
		return expr  # literal fallback


def _do_reject_row_v2(doc, rule, template) -> bool:
	"""Reject — bulk runner bu flag'i görür ve row'u skip eder."""
	reason = template.reject_reason or "ECA kuralı tarafından reddedildi"
	doc.flags.eca_rejected = True
	doc.flags.eca_reject_reason = reason
	return True


def _do_email_v2(doc, rule, template) -> bool:
	if not template.email_recipients:
		return False
	try:
		ctx = {"doc": doc.as_dict() if hasattr(doc, "as_dict") else dict(doc)}
		subject = frappe.render_template(template.email_subject_template or "", ctx)
		body = frappe.render_template(template.email_body_template or "", ctx)
		recipients = [r.strip() for r in template.email_recipients.split(",") if r.strip()]
		frappe.sendmail(recipients=recipients, subject=subject, message=body, now=False)
		return True
	except Exception as e:
		frappe.log_error(f"ECA email failed: {e}", "_do_email_v2")
		return False


def _do_webhook_v2(doc, rule, template) -> bool:
	if not template.webhook_url:
		return False
	try:
		ctx = {"doc": doc.as_dict() if hasattr(doc, "as_dict") else dict(doc)}
		body = frappe.render_template(template.webhook_body_template or "{}", ctx)
		frappe.enqueue(
			"tradehub_core.eca.dispatcher._send_webhook_v2",
			queue="short",
			url=template.webhook_url,
			method=template.webhook_method or "POST",
			body=body,
		)
		return True
	except Exception as e:
		frappe.log_error(f"ECA webhook failed: {e}", "_do_webhook_v2")
		return False


_ALLOWED_WEBHOOK_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


def _send_webhook_v2(url: str, method: str, body: str) -> None:
	import requests

	# F-022: HTTP method whitelist doğrulaması
	method_upper = (method or "POST").upper()
	if method_upper not in _ALLOWED_WEBHOOK_METHODS:
		frappe.log_error(f"Invalid webhook method: {method}", "_send_webhook_v2")
		return

	# F-022: SSRF koruması — private/reserved IP aralıklarını engelle
	try:
		from tradehub_core.utils.feed_security import validate_feed_url

		validate_feed_url(url)
	except Exception as e:
		frappe.log_error(f"Webhook URL SSRF validation failed: {url} — {e}", "_send_webhook_v2")
		return

	try:
		requests.request(
			method=method_upper,
			url=url,
			data=body,
			headers={"Content-Type": "application/json"},
			timeout=10,
		)
	except Exception as e:
		frappe.log_error(f"webhook send failed {url}: {e}", "_send_webhook_v2")


def _do_create_document_v2(doc, rule, template) -> bool:
	import json

	from tradehub_core.eca.api import CREATABLE_DOCTYPES

	if not template.create_doctype:
		return False
	# Çalışma anı son savunma: ignore_permissions ile insert edileceği için yalnız
	# allowlist'teki kayıt türleri + allowlist'teki alanlar yazılabilir (rastgele
	# DocType/alan yaratımı engellenir). get_rule_schema + _compile_action ile aynı sabit.
	meta = CREATABLE_DOCTYPES.get(template.create_doctype)
	if not meta:
		frappe.log_error(
			f"ECA create_document allowlist dışı doctype: {template.create_doctype}",
			"_do_create_document_v2",
		)
		return False
	allowed_fields = {f["key"] for f in meta["fields"]}
	try:
		mappings = json.loads(template.create_field_mappings or "{}")
		new_doc = frappe.new_doc(template.create_doctype)
		for field, expr in mappings.items():
			if field not in allowed_fields:
				continue
			new_doc.set(field, _eval_value_expr_v2(expr, doc))
		new_doc.insert(ignore_permissions=True)
		return True
	except Exception as e:
		frappe.log_error(f"ECA create_document failed: {e}", "_do_create_document_v2")
		return False


def _do_custom_script_v2(doc, rule, template) -> bool:
	"""Custom script — sadece admin (validators katmanı zaten guard'lıyor)."""
	if not template.script_body:
		return False
	try:
		from frappe.utils.safe_exec import safe_exec

		safe_exec(template.script_body, _locals={"doc": doc, "frappe": frappe})
		return True
	except Exception as e:
		frappe.log_error(f"ECA custom_script failed: {e}", "_do_custom_script_v2")
		return False


def _write_log_v2(log_data: dict) -> None:
	"""ECA Rule Log oluştur — log yazımı flow'u kırmaz."""
	try:
		if not frappe.db.exists("DocType", "ECA Rule Log"):
			return
		log = frappe.new_doc("ECA Rule Log")
		log.triggered_at = frappe.utils.now_datetime()
		for k, v in log_data.items():
			if hasattr(log, k):
				setattr(log, k, v)
		log.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error("_write_log_v2: failed to insert ECA Rule Log", "eca_dispatcher")
		pass
