"""Slot politikaları (VERİ) + PolicyEngine (KOD).

Dizin yerleşimi:
    schema/slot-policy.schema.json   sürüm 1.3.0 — politikaların şeması
    slots/*.json                     9 slot politikası (9/9 şema uyumlu)
    content_rules.json               içerik kuralları + ölçüm/kalibrasyon durumu
    quota.schema.json                kota şeması
    retention.schema.json            saklama şeması
    engine.py                        PolicyEngine — kararı veren tek yer

TASARIM KURALI: yeni bir slot eklemek `slots/` altına bir JSON koymaktır.
`engine.py` DEĞİŞMEZ. Kod yalnız yeni bir KISIT TÜRÜ (şemada olmayan bir alan)
eklenirken değişir.

TEK DOĞRULUK KAYNAĞI
---------------------
`slots/*.json`, yükleme ve yürütme kararlarının kanonik politika setidir.
`docs/standards/policies/*.json` eski bir rakip motor değildir; DPI/teslim
belgelerinin alan-bazlı ölçüm izdüşümüdür ve çalışma zamanında okunmaz. Bu
ayrım kodla da sabitlenir ki iki klasör yeniden eşdeğer politika kaynağı gibi
yorumlanmasın.
"""

from __future__ import annotations

from pathlib import Path

POLICY_DIR: Path = Path(__file__).resolve().parent
SLOT_DIR: Path = POLICY_DIR / "slots"
SCHEMA_PATH: Path = POLICY_DIR / "schema" / "slot-policy.schema.json"
CONTENT_RULES_PATH: Path = POLICY_DIR / "content_rules.json"

CANONICAL_POLICY_SET: str = "tradehub_core.media.pipeline.policy.slots"
DOCUMENTATION_PROJECTION_GLOB: str = "docs/standards/policies/*.json"

__all__ = [
	"CANONICAL_POLICY_SET",
	"CONTENT_RULES_PATH",
	"DOCUMENTATION_PROJECTION_GLOB",
	"POLICY_DIR",
	"SCHEMA_PATH",
	"SLOT_DIR",
]
