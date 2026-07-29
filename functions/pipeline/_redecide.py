"""Re-apply the auto_review decision logic on an existing v6 output,
without burning more Gemini calls. Reads stored confidence/reason."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from auto_review import _decide

if len(sys.argv) != 2:
    print("usage: _redecide.py <output_dir>"); sys.exit(2)

out = Path(sys.argv[1])
final = out / "stores_v6_final.json"
stores = json.loads(final.read_text(encoding="utf-8"))

counts = {"auto_passed": 0, "auto_rejected": 0, "needs_human": 0, "untouched": 0}

for s in stores:
    rev = s.get("auto_review") or {}
    if not rev:
        counts["untouched"] += 1
        continue
    # Reconstruct the data _decide expects
    s["_judge"] = {
        "confidence": rev.get("gemini_confidence", 0.5),
        "reason": rev.get("gemini_reason", ""),
    }
    s["_phones_clean"] = rev.get("phones_clean", [])

    decision, conf, reason, phones = _decide(s)
    counts[decision] += 1

    s["auto_review"] = {
        "phones_clean": phones,
        "gemini_confidence": round(conf, 2),
        "gemini_reason": reason,
        "decision": decision,
    }
    if decision == "auto_passed":
        s["status_check"] = {
            "tier": 2,
            "status": "نشط",
            "source": "مراجعة AI آلية",
            "evidence": f"ثقة Gemini {conf:.2f}" + (
                f" + رقم سعودي ({len(phones)})" if phones else ""
            ),
        }
    s.pop("_judge", None)
    s.pop("_phones_clean", None)

final.write_text(json.dumps(stores, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("re-decision counts:", counts)
