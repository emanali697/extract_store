"""
Adapter for the `traders-data-live` Firestore project's `stores` collection.

Their schema is richer than ours — many fields we don't have (campaigns,
operating hours, social media…). We map our extracted store data onto the
fields we *can* fill and leave the rest empty so the user can complete
them later in their own system.

Two modes:
    preview_push(stores)  → returns the JSON we *would* send, no writes
    push_to_traders(stores) → actually writes to Firestore
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

from config import TRADERS_KEY_PATH, TRADERS_COLLECTION

_log = logging.getLogger("traders_firebase")

_app = None
_db = None
_init_error: str | None = None


def _ensure_init() -> bool:
    global _app, _db, _init_error
    if _db is not None:
        return True
    if _init_error:
        return False
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as e:
        _init_error = f"firebase-admin not installed: {e}"
        return False
    if not TRADERS_KEY_PATH.exists():
        _init_error = f"traders key not found at {TRADERS_KEY_PATH}"
        return False
    try:
        # Distinct app name so we don't collide with the existing store-extract app
        existing = {a.name for a in firebase_admin._apps.values()}
        if "traders" not in existing:
            cred = credentials.Certificate(str(TRADERS_KEY_PATH))
            _app = firebase_admin.initialize_app(cred, name="traders")
        else:
            _app = firebase_admin.get_app("traders")
        _db = firestore.client(_app)
        return True
    except Exception as e:
        _init_error = f"traders init failed: {e}"
        _log.exception(_init_error)
        return False


def is_ready() -> bool:
    return _ensure_init()


def status() -> dict:
    ok = _ensure_init()
    return {
        "ready": ok,
        "error": _init_error,
        "collection": TRADERS_COLLECTION,
        "project_id": (_app.project_id if _app else None),
    }


# ----------  Schema mapping  ----------

# Our status (نشط/مقفول/غير محدد) → their `storeStatus` controlled vocab
STATUS_MAP = {
    "نشط":       "نشط",
    "مقفول":     "مغلق نهائيا",
    "غير محدد":  "",
}


def _normalize(s: str) -> str:
    s = (s or "").strip()
    return s


def _city_map(value: str) -> dict:
    """Their cities collection has id-based lookups. We leave id empty for the
    user to wire later in their system."""
    v = _normalize(value)
    return {"id": "", "value": v, "valueLower": v.lower() if v else ""}


def _neighborhood_map(value: str) -> dict:
    v = _normalize(value)
    return {"id": "", "value": v, "valueLower": v.lower() if v else ""}


def _street_map(value: str) -> dict:
    v = _normalize(value)
    return {"id": "", "value": v, "valueLower": v.lower() if v else ""}


def _phones_to_array(phone_str: str) -> list[str]:
    if not phone_str:
        return []
    raw = [p.strip() for p in phone_str.replace("،", ",").split(",")]
    return [p for p in raw if p]


def _build_geo_link(lat, lng) -> str:
    if lat is None or lng is None:
        return ""
    return f"https://www.google.com/maps?q={lat},{lng}"


def map_store(s: dict, order_idx: int, source_job_id: str) -> dict:
    """Map ONE extracted store to the traders-data-live schema."""
    name = s.get("name_ar") or s.get("name") or ""
    status_word = ""
    sc = s.get("status_check") or {}
    if sc.get("status"):
        status_word = STATUS_MAP.get(sc["status"], sc["status"])

    lat = s.get("lat") or ""
    lng = s.get("lng") or ""

    return {
        "VideoMin": "",
        "adminPhones": [],
        "campaignInteractionList": [],
        "categories": [s.get("category")] if s.get("category") else [],
        "city": _city_map(s.get("city") or ""),
        "completionPercentage": 50,  # we provide ~half the fields, user fills the rest
        "copy": {
            "commercialName": "",
            "id": "",
            "internalName": "",
            "label": "",
            "releaseLink": "",
        },
        "customerPhones": _phones_to_array(s.get("phone") or ""),
        "dataCompleted": False,
        "geoLocationLink": _build_geo_link(lat, lng),
        "hasDelivery": "",
        "hasWhatsApp": "",
        # `id` and `order` will be filled by caller
        "isForRent": False,
        "latitude": str(lat) if lat else "",
        "longitude": str(lng) if lng else "",
        "neighborhood": _neighborhood_map(s.get("district") or ""),
        "notes": s.get("notes") or "",
        "numberOfRentals": "",
        "offersData": [],
        "operatingHours": "",
        "order": order_idx,
        "socialMedia": [],
        "storeImageUrl": "",
        "storeLink": "",
        "storeName": name,
        "storeStatus": status_word,
        "street": _street_map(s.get("street") or ""),
        "subscriptionRenewalMonth": "",
        "technicalSupportData": {},
        "updateNotes": f"تم الاستخراج تلقائياً من فيديو داش كاميرا (job {source_job_id})",
        "videoSec": "",
        "videoUrl": "",
    }


# ----------  Push / preview  ----------

def preview_push(stores: list[dict], source_job_id: str) -> list[dict]:
    """Return the list of documents we WOULD write, without touching Firestore."""
    return [map_store(s, idx, source_job_id) for idx, s in enumerate(stores, start=1)]


def push_to_traders(stores: list[dict], source_job_id: str) -> dict:
    """Actually write the mapped stores to traders-data-live/stores."""
    if not _ensure_init():
        return {"written": 0, "error": _init_error}

    from firebase_admin import firestore as _fs

    coll = _db.collection(TRADERS_COLLECTION)
    server_ts = _fs.SERVER_TIMESTAMP

    written = 0
    errors: list[str] = []

    for idx, s in enumerate(stores, start=1):
        try:
            doc = map_store(s, idx, source_job_id)
            doc["createdAt"] = server_ts
            doc["updatedAt"] = server_ts
            doc_ref = coll.document()
            doc["id"] = doc_ref.id
            doc_ref.set(doc)
            written += 1
        except Exception as e:
            errors.append(f"{s.get('name_ar', '?')}: {e}")

    return {
        "written": written,
        "skipped": len(stores) - written,
        "errors": errors[:5],
        "collection": TRADERS_COLLECTION,
        "project": "traders-data-live",
    }
