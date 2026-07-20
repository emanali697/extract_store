"""
Re-snapshot ANY job's results from its stores_v6_final.json into state.db.

Usage:
    python _resnapshot_any.py <job_id>

After this, restart the backend so it hydrates the refreshed results.
Used when we re-run run_v6 standalone (e.g. with --skip-status) outside the
normal backend flow and need the API/UI to reflect the new output.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from jobs import Job
from config import JOBS_DIR
import db

if len(sys.argv) < 2:
    print("usage: python _resnapshot_any.py <job_id>")
    sys.exit(1)

JOB_ID = sys.argv[1]
JOB_DIR = JOBS_DIR / JOB_ID

db.init()
rows = {r["job_id"]: r for r in db.load_all_jobs()}
prev = rows.get(JOB_ID, {})

final_json = JOB_DIR / "stores_v6_final.json"
if not final_json.exists():
    print(f"ERROR: {final_json} not found")
    sys.exit(2)

raw = json.loads(final_json.read_text(encoding="utf-8"))

stores = []
active = phones = precise = 0
auto_passed = auto_rejected = needs_human = 0
review = []

for i, s in enumerate(raw, start=1):
    sc = s.get("status_check") or {}
    v5 = s.get("v5") or {}
    cand = v5.get("candidate") or {}
    auto_rev = s.get("auto_review") or {}
    ar = auto_rev.get("decision")
    if ar == "auto_passed":
        auto_passed += 1
    elif ar == "auto_rejected":
        auto_rejected += 1
    elif ar == "needs_human":
        needs_human += 1

    phone = s.get("phone") or cand.get("phone") or ""
    tier = sc.get("tier") or (1 if v5.get("status") == "confirmed_high"
                              else 2 if v5.get("status") == "confirmed_medium" else 3)
    name = s.get("name_ar") or cand.get("name") or "—"
    category = s.get("category") or cand.get("category") or "—"
    loc_source = s.get("location_source") or ("google_places" if cand.get("lat")
                                              else "dashcam_frame" if s.get("lat")
                                              else "unknown")
    loc_acc = s.get("location_accuracy_m")
    status_word = sc.get("status")
    status_label = ("✅ نشط" if status_word == "نشط" or tier == 1
                    else "🚫 مقفول" if status_word and "مغلق" in status_word
                    else "⚪ غير محدد" if status_word == "غير محدد"
                    else "⚠️ غير مؤكد" if tier == 2 else "⚪ يحتاج تحقق")

    if status_word == "نشط" or tier == 1:
        active += 1
    if phone:
        phones += 1
    if s.get("lat") or cand.get("lat"):
        precise += 1

    stores.append({
        "id": i, "name": name, "name_ar": name, "name_en": s.get("name_en") or "",
        "category": category, "phone": phone, "status": status_label, "tier": tier,
        "lat": s.get("lat") or cand.get("lat"), "lng": s.get("lng") or cand.get("lng"),
        "location_source": loc_source, "location_accuracy_m": loc_acc,
        "google_place_id": s.get("google_place_id") or cand.get("place_id"),
        "rating": sc.get("rating"), "review_count": sc.get("review_count"),
        "evidence": sc.get("evidence"), "source": sc.get("source"),
        "distance": f"{int(loc_acc)}م" if loc_acc else "—",
        "street": prev.get("street_name", ""), "city": prev.get("city", ""),
        "district": prev.get("district", ""),
        "auto_review_decision": ar,
        "auto_review_confidence": auto_rev.get("gemini_confidence"),
    })

    if ar == "needs_human" or (ar is None and (tier == 3 or s.get("needs_review"))):
        review.append({
            "id": f"r{i}", "suggestedName": name,
            "rawOcr": auto_rev.get("multimodal_raw") or s.get("raw_text") or s.get("ocr_text") or "",
            "multimodalName": auto_rev.get("multimodal_name") or "",
            "category": category, "phone": phone,
            "confidence": auto_rev.get("gemini_confidence") or s.get("confidence") or 0.5,
            "tier": tier,
            "signImageUrl": f"/jobs/{JOB_ID}/sign/{auto_rev.get('sign_image')}" if auto_rev.get("sign_image") else "",
            "note": auto_rev.get("gemini_reason") or s.get("review_note") or "",
        })

results = {
    "summary": {"total": len(stores), "active": active, "phones": phones,
                "precise": precise, "source": "v6",
                "auto_passed": auto_passed, "auto_rejected": auto_rejected,
                "needs_human": needs_human},
    "stores": stores, "review": review,
}

job = Job(
    job_id=JOB_ID,
    video_path=prev.get("video_path", ""),
    street_name=prev.get("street_name", ""),
    city=prev.get("city", ""),
    district=prev.get("district", ""),
    speed_mode=prev.get("speed_mode", "auto"),
    enable_places=bool(prev.get("enable_places", True)),
    enable_status=bool(prev.get("enable_status", True)),
    status="done",
    output_dir=prev.get("output_dir", str(JOB_DIR)),
    stages=prev.get("stages", {}),
    results=results,
)
db.upsert_job(job)
print(f"OK — refreshed {JOB_ID}: {len(stores)} stores | phones={phones} | "
      f"precise={precise} | auto_passed={auto_passed} | needs_human={needs_human}")
