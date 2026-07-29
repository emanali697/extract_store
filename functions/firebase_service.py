"""Firebase Admin SDK wrapper for Cloud Functions."""
from __future__ import annotations

import logging
from typing import Any

import firebase_admin
from firebase_admin import firestore as _fs

from config import FIRESTORE_COLLECTION

_log = logging.getLogger("firebase_service")
_db = None


def _get_db():
    global _db
    if _db is None:
        _db = firebase_admin.firestore.client()
    return _db


def status() -> dict:
    try:
        app = firebase_admin.get_app()
        return {
            "ready": True,
            "error": None,
            "collection": FIRESTORE_COLLECTION,
            "project_id": app.project_id,
        }
    except Exception as e:
        return {"ready": False, "error": str(e), "collection": FIRESTORE_COLLECTION, "project_id": None}


def is_ready() -> bool:
    return status()["ready"]


def _store_to_doc(s: dict, job_id: str, server_ts: Any) -> dict:
    """Map app-layer store dict → Firestore document."""
    lat = s.get("lat")
    lng = s.get("lng")
    location = None
    if lat is not None and lng is not None:
        try:
            location = _fs.GeoPoint(float(lat), float(lng))
        except (TypeError, ValueError):
            location = None

    doc = {
        "name_ar": s.get("name_ar") or s.get("name") or "",
        "name_en": s.get("name_en") or "",
        "category": s.get("category") or "",
        "phone": s.get("phone") or "",
        "status": s.get("status") or "غير محدد",
        "tier": s.get("tier") or 3,
        "location_source": s.get("location_source") or "dashcam_frame",
        "location_accuracy_m": s.get("location_accuracy_m"),
        "google_place_id": s.get("google_place_id") or None,
        "rating": s.get("rating"),
        "review_count": s.get("review_count"),
        "street": s.get("street") or "",
        "city": s.get("city") or "",
        "district": s.get("district") or "",
        "extracted_from_job": job_id,
        "extracted_at": server_ts,
        "approved_by_user": True,
    }
    if location is not None:
        doc["location"] = location
    return doc


def push_stores(stores: list[dict], job_id: str) -> dict:
    """Write approved stores to Firestore."""
    if not is_ready():
        return {"written": 0, "error": status().get("error")}

    db = _get_db()
    coll = db.collection(FIRESTORE_COLLECTION)
    server_ts = _fs.SERVER_TIMESTAMP

    written = 0
    skipped = 0
    errors: list[str] = []

    for s in stores:
        try:
            doc = _store_to_doc(s, job_id, server_ts)
            place_id = s.get("google_place_id")
            if place_id:
                coll.document(place_id).set(doc, merge=True)
            else:
                coll.add(doc)
            written += 1
        except Exception as e:
            skipped += 1
            errors.append(str(e))

    return {
        "written": written,
        "skipped": skipped,
        "errors": errors[:5],
        "collection": FIRESTORE_COLLECTION,
    }
