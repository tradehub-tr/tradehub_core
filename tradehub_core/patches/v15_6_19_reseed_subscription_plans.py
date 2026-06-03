"""Faz I retry — Subscription Plan seed'i Patch Log'u baypas ederek tekrar çalıştır.

v15_6_18 beta DB'sinde `LinkValidationError: Region: TR` ile abort oldu; Frappe
patch'i yine de "ran" olarak işaretledi → sonraki `bench migrate` skip etti,
plan'lar boş kaldı (`get_pricing_plans` → []).

Bu patch v15_6_19 ismiyle yeni Patch Log entry yaratır, böylece migrate skip
etmez ve v15_6_18'in ignore_links fix'li seed logic'ini yeniden çalıştırır.

Idempotent: v15_6_18.execute() kendisi mevcut plan'ları skip eder; iki kez
çalışsa bile DB'de duplicate oluşmaz.
"""

from __future__ import annotations

from tradehub_core.patches.v15_6_18_seed_subscription_plans import execute as _seed_v15_6_18


def execute() -> dict:
	return _seed_v15_6_18()
