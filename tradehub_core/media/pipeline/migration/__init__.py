"""Faz 14 · T-143 — geriye dönük standartlaştırma (backfill) orkestratörü.

`docs/plans/migration.md` §4.1 planın tek yeni kod kalemini şöyle tanımlıyor:

    "Yazılacak tek şey: orkestratör. Batch'leri kesen, aralarda hata oranını
     okuyan, eşik aşılırsa enqueue etmeyi bırakan ince bir katman."

Bu paket o katmandır. Toplu işleyiciyi, kapıları, arşivi, geri almayı YENİDEN
YAZMAZ — hepsi `tradehub_core/media/` içinde çalışıyor ve oraya dokunulmuyor.
Orkestratör onları PORT arkasından çağırır (`BatchRunner` protokolü); üretim
adaptörü `frappe`'yi yalnız çağrı anında, fonksiyon içinde import eder.

`backfill.py` modül düzeyinde `import frappe` İÇERMEZ; bench/site/DB olmadan
test edilir (`tests/test_migration_backfill.py`).
"""

IMPLEMENTED = True
