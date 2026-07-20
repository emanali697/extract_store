"""
Push ALL extracted stores from the given jobs into a NEW collection inside the
store-extract Firestore project.

Per the user's choice: same project (store-extract), but a brand-new collection
so the dashcam data stays separate from the old `stores` collection.

Schema written (the fields the user asked for + useful metadata):
    name_ar, name_en, category,
    phones[]         (split + normalized list),
    location         GeoPoint(lat,lng)         ← from Google Places or dashcam
    lat, lng         (strings, for convenience),
    location_source  google_places | dashcam_frame | unknown,
    location_accuracy_m,
    google_place_id,
    street, city, district,
    source_video, source_job,
    review_decision, tier,
    extracted_at     (server timestamp).

Usage:
    python push_all_to_newdb.py <job_id> [<job_id> ...]
        [--collection stores_dashcam] [--include-rejected] [--dry-run]

By default, stores the auto-reviewer marked `auto_rejected` (OCR garbage) are
skipped. Pass --include-rejected to push everything.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from config import JOBS_DIR, BASE_DIR

NEWDB_KEY = BASE_DIR / "newdb_key.json"


def _split_phones(raw) -> list[str]:
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,،;]+", str(raw))]
    return [p for p in parts if p]


def _job_meta(job_id: str) -> dict:
    """Pull street/city/district/video from db row if present."""
    import db
    db.init()
    for r in db.load_all_jobs():
        if r["job_id"] == job_id:
            return r
    return {}


def _load_stores(job_id: str) -> list[dict]:
    p = JOBS_DIR / job_id / "stores_v6_final.json"
    if not p.exists():
        print(f"  ⚠️ {job_id}: stores_v6_final.json not found — skipping")
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def _map_doc(s: dict, meta: dict, job_id: str):
    v5 = s.get("v5") or {}
    cand = v5.get("candidate") or {}
    auto = s.get("auto_review") or {}

    name = s.get("name_ar") or cand.get("name") or ""
    lat = s.get("lat") or cand.get("lat")
    lng = s.get("lng") or cand.get("lng")

    # Phones live in several places depending on which pipeline stage found them:
    #   s["phone"], s["places"]["phone"], v5.candidate["phone"],
    #   auto_review["phones_clean"] (already normalized).
    # Union them all so we don't drop numbers (places.phone was being missed).
    places = s.get("places") or {}
    phone_pool = []
    phone_pool += (auto.get("phones_clean") or [])          # cleaned first
    phone_pool += _split_phones(s.get("phone"))
    phone_pool += _split_phones(places.get("phone"))
    phone_pool += _split_phones(cand.get("phone"))
    phones = list(dict.fromkeys(p for p in phone_pool if p))  # dedup, keep order

    doc = {
        "name_ar": name,
        "name_en": s.get("name_en") or "",
        "category": s.get("category") or cand.get("category") or "",
        "phones": phones,
        "phone": ", ".join(phones),
        "lat": str(lat) if lat else "",
        "lng": str(lng) if lng else "",
        "location_source": s.get("location_source") or "unknown",
        "location_accuracy_m": s.get("location_accuracy_m"),
        "google_place_id": s.get("google_place_id") or cand.get("place_id") or "",
        "street": meta.get("street_name", ""),
        "city": meta.get("city", ""),
        "district": meta.get("district", ""),
        "source_video": Path(meta.get("video_path", "")).name,
        "source_job": job_id,
        "review_decision": auto.get("decision"),
        "tier": (s.get("status_check") or {}).get("tier"),
    }
    return doc, lat, lng


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_ids", nargs="+")
    ap.add_argument("--collection", default="stores_dashcam")
    ap.add_argument("--include-rejected", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # ---- gather ----
    all_rows = []  # (doc, lat, lng)
    per_job = {}
    for jid in args.job_ids:
        meta = _job_meta(jid)
        stores = _load_stores(jid)
        kept = 0
        for s in stores:
            auto = s.get("auto_review") or {}
            if not args.include_rejected and auto.get("decision") == "auto_rejected":
                continue
            doc, lat, lng = _map_doc(s, meta, jid)
            if not doc["name_ar"]:
                continue
            all_rows.append((doc, lat, lng))
            kept += 1
        per_job[jid] = (len(stores), kept)

    print(f"\n=== سيتم الرفع لكولكشن '{args.collection}' في مشروع store-extract ===")
    for jid, (tot, kept) in per_job.items():
        print(f"  {jid}: {kept}/{tot} متجر")
    print(f"  الإجمالي: {len(all_rows)} متجر")
    with_phones = sum(1 for d, _, _ in all_rows if d["phones"])
    with_loc = sum(1 for d, la, ln in all_rows if la and ln)
    print(f"  بأرقام: {with_phones} | بموقع: {with_loc}")

    if args.dry_run:
        print("\n--dry-run: مفيش كتابة فعلية. عيّنة أول متجرين:")
        for d, _, _ in all_rows[:2]:
            print(json.dumps(d, ensure_ascii=False, indent=2))
        return

    # ---- push ----
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not NEWDB_KEY.exists():
        print(f"ERROR: {NEWDB_KEY} not found")
        sys.exit(2)

    # distinct app name to avoid colliding with the backend's default app
    names = {a.name for a in firebase_admin._apps.values()}
    if "newdb" in names:
        app = firebase_admin.get_app("newdb")
    else:
        cred = credentials.Certificate(str(NEWDB_KEY))
        app = firebase_admin.initialize_app(cred, name="newdb")
    db_fs = firestore.client(app)
    coll = db_fs.collection(args.collection)
    server_ts = firestore.SERVER_TIMESTAMP

    written = 0
    errors = []
    for doc, lat, lng in all_rows:
        try:
            if lat and lng:
                try:
                    doc["location"] = firestore.GeoPoint(float(lat), float(lng))
                except (TypeError, ValueError):
                    pass
            doc["extracted_at"] = server_ts
            ref = coll.document()
            doc["id"] = ref.id
            ref.set(doc)
            written += 1
        except Exception as e:
            errors.append(f"{doc.get('name_ar','?')}: {e}")

    print(f"\n✅ اترفع {written}/{len(all_rows)} متجر لكولكشن '{args.collection}'")
    if errors:
        print(f"⚠️ أخطاء ({len(errors)}):")
        for e in errors[:5]:
            print("   ", e)


if __name__ == "__main__":
    main()
