"""Daily scheduled task: enforce data retention policies by anonymizing expired records."""

import hashlib

import frappe
from frappe.utils import add_to_date, now_datetime

_BATCH_SIZE = 100
_LOCK_KEY = "data_retention_enforcement"
_LOCK_TTL = 3600


def enforce_data_retention() -> None:
    """Process all active retention policies."""
    lock = frappe.cache.lock(_LOCK_KEY, timeout=_LOCK_TTL)
    if not lock.acquire(blocking=False):
        frappe.logger().info("Data retention job already running, skipping")
        return

    try:
        _run_enforcement()
    finally:
        lock.release()


def _run_enforcement() -> None:
    policies = frappe.get_all(
        "Data Retention Policy",
        filters={"is_active": 1},
        fields=["name", "ref_doctype", "retention_days", "date_field"],
    )

    for policy in policies:
        try:
            _enforce_single_policy(policy)
        except Exception:
            frappe.log_error(f"Retention enforcement failed for {policy.name}")


def _enforce_single_policy(policy: dict) -> None:
    cutoff = add_to_date(None, days=-policy.retention_days)

    field_rules = frappe.get_all(
        "Retention Anonymize Field",
        filters={"parent": policy.name, "parenttype": "Data Retention Policy"},
        fields=["fieldname", "anonymize_strategy"],
    )
    if not field_rules:
        return

    total_processed = 0
    while True:
        conditions = [f"`{policy.date_field}` < %s"]
        params = [str(cutoff)]

        for rule in field_rules:
            conditions.append(f"`{rule['fieldname']}` IS NOT NULL")

        expired_names = frappe.db.sql(
            f"""SELECT name FROM `tab{policy.ref_doctype}`
                WHERE {' AND '.join(conditions)}
                LIMIT {_BATCH_SIZE}""",
            params,
            pluck="name",
        )

        if not expired_names:
            break

        for doc_name in expired_names:
            try:
                _anonymize_record(policy.ref_doctype, doc_name, field_rules)
                total_processed += 1
            except Exception:
                frappe.log_error(
                    f"Anonymize failed: {policy.ref_doctype}/{doc_name}"
                )

        frappe.db.commit()

    frappe.db.set_value(
        "Data Retention Policy",
        policy.name,
        {
            "last_run": now_datetime(),
            "records_processed": total_processed,
        },
        update_modified=False,
    )
    frappe.db.commit()

    if total_processed:
        frappe.logger().info(
            f"Retention: anonymized {total_processed} records in {policy.ref_doctype}"
        )


def _anonymize_record(doctype: str, name: str, field_rules: list[dict]) -> None:
    update_map = {}

    for rule in field_rules:
        fn = rule["fieldname"]
        strategy = rule["anonymize_strategy"]

        current_val = frappe.db.get_value(doctype, name, fn)
        if current_val is None:
            continue

        update_map[fn] = _apply_strategy(strategy, current_val)

    if not update_map:
        return

    frappe.db.set_value(doctype, name, update_map, update_modified=False)

    try:
        from tradehub_core.audit.log import log_decision, DECISION_ALLOW, LAYER_L3

        log_decision(
            actor="System",
            action="retention_anonymize",
            decision=DECISION_ALLOW,
            rule_id=f"retention:{doctype}",
            layer=LAYER_L3,
            object_doctype=doctype,
            object_name=name,
            context={"fields_anonymized": list(update_map.keys())},
        )
    except Exception:
        pass


def _apply_strategy(strategy: str, value) -> object:
    s = str(value)
    if strategy == "null":
        return None
    if strategy == "hash":
        return hashlib.sha256(s.encode()).hexdigest()[:16]
    if strategy == "placeholder":
        return "[ANONYMIZED]"
    if strategy == "mask":
        if len(s) <= 2:
            return "**"
        return s[0] + "*" * (len(s) - 2) + s[-1]
    return None
