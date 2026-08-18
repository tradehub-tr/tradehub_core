"""Slot politikaları (VERİ) + PolicyEngine (KOD).

Dizin yerleşimi:
    schema/slot-policy.schema.json   sürüm 1.3.0 — politikaların şeması
    slots/*.json                     9 slot politikası (9/9 şema uyumlu)
    content_rules.json               içerik uygunluk kuralları (KALİBRE EDİLMEDİ)
    quota.schema.json                kota şeması
    retention.schema.json            saklama şeması
    engine.py                        PolicyEngine — kararı veren tek yer

TASARIM KURALI: yeni bir slot eklemek `slots/` altına bir JSON koymaktır.
`engine.py` DEĞİŞMEZ. Kod yalnız yeni bir KISIT TÜRÜ (şemada olmayan bir alan)
eklenirken değişir.
"""

from __future__ import annotations

from pathlib import Path

POLICY_DIR: Path = Path(__file__).resolve().parent
SLOT_DIR: Path = POLICY_DIR / "slots"
SCHEMA_PATH: Path = POLICY_DIR / "schema" / "slot-policy.schema.json"
CONTENT_RULES_PATH: Path = POLICY_DIR / "content_rules.json"

__all__ = ["POLICY_DIR", "SLOT_DIR", "SCHEMA_PATH", "CONTENT_RULES_PATH"]
