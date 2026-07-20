"""
Recovery script — overwrite the corrupted auto_review/status_check in
stores_v6_final.json using the GOOD results saved in state.db.

This preserves all original v6 fields (frame, v5.candidate, lat/lng, notes)
but replaces the polluted decision data with the good run's output.
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, ".")
from config import JOBS_DIR, BASE_DIR

JOB_ID = "29f2c13926b3"

# 1. Pull the good results from state.db
conn = sqlite3.connect(str(BASE_DIR / "state.db"))
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT results_json FROM jobs WHERE job_id = ?", (JOB_ID,)).fetchone()
conn.close()
if not row or not row["results_json"]:
    sys.exit("no results in state.db")
good_results = json.loads(row["results_json"])
good_stores = good_results.get("stores", [])
print(f"state.db: {len(good_stores)} good stores")

# 2. Build a lookup by name_ar (state.db uses 'name' as display)
good_by_name = {}
for s in good_stores:
    key = (s.get("name_ar") or s.get("name") or "").strip()
    if key:
        good_by_name[key] = s

# 3. Read the current (corrupted) stores_v6_final.json
job_dir = Path(r"D:/sharea elnassim/extract stores/backend/jobs") / JOB_ID
final_path = job_dir / "stores_v6_final.json"
stores = json.loads(final_path.read_text(encoding="utf-8"))
print(f"on-disk: {len(stores)} stores")

# 4. Merge — overwrite tier/status fields with state.db's good values
restored = 0
for s in stores:
    name = (s.get("name_ar") or "").strip()
    good = good_by_name.get(name)
    if not good:
        continue
    tier = good.get("tier", 3)
    sc = s.get("status_check") or {}
    sc["tier"] = tier
    if tier == 1:
        # leave Google evidence intact
        sc.setdefault("status", "نشط")
    elif tier == 2:
        sc["status"] = "نشط"
        sc["source"] = good.get("source") or "مراجعة AI آلية"
        sc["evidence"] = good.get("evidence") or "تأكيد من المراجعة الآلية"
    else:
        sc["status"] = "غير محدد"
        sc["source"] = "يحتاج تحقق ميداني"
        sc["evidence"] = "غير مؤكد"
    s["status_check"] = sc

    # Rebuild auto_review block from the good decision
    ar = s.get("auto_review") or {}
    if tier <= 2 and tier != 1:
        ar["decision"] = "auto_passed"
        ar["gemini_confidence"] = good.get("auto_review_confidence") or 0.9
    elif tier == 3:
        ar["decision"] = "needs_human"
        ar["gemini_confidence"] = good.get("auto_review_confidence") or 0.5
    s["auto_review"] = ar
    restored += 1

# 5. Save
final_path.write_text(
    json.dumps(stores, ensure_ascii=False, indent=2, default=str),
    encoding="utf-8",
)
print(f"restored {restored} stores' tier/status from state.db → {final_path.name}")
