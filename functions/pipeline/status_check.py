"""
Status determination في 3 طبقات:

طبقة 1 - Google Places Details API:
  للمتاجر اللي عندها place_id من v5 (المؤكدين في Google).
  ترجع business_status: OPERATIONAL / CLOSED_TEMPORARILY / CLOSED_PERMANENTLY
  + recent reviews count + opening hours.

طبقة 2 - Web search by phone:
  للمتاجر اللي معاها رقم تليفون لكن مش مؤكدين في Google.
  نشوف لو موجودين في منصات التوصيل أو الأدلة → نشط.

طبقة 3 - Field verification needed:
  للمتاجر اللي مفيش معاها لا place_id ولا تليفون.
  بنحطها 'يحتاج تحقق ميداني'.
"""
import time
import requests

from places_v4 import get_creds


PLACE_DETAILS_FIELDS = [
    'businessStatus',
    'currentOpeningHours.openNow',
    'regularOpeningHours.weekdayDescriptions',
    'rating',
    'userRatingCount',
    'reviews.publishTime',
]


def fetch_place_details(place_id):
    """جلب تفاصيل place من Google Places Details API."""
    if not place_id or not place_id.startswith('ChIJ'):
        return None
    url = f"https://places.googleapis.com/v1/places/{place_id}"
    try:
        creds = get_creds()
        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/json',
            'X-Goog-FieldMask': ','.join(PLACE_DETAILS_FIELDS),
        }
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
        return {'_error': f'http {r.status_code}: {r.text[:120]}'}
    except Exception as e:
        return {'_error': str(e)}


STATUS_MAP = {
    'OPERATIONAL': 'نشط',
    'CLOSED_TEMPORARILY': 'مقفول مؤقت',
    'CLOSED_PERMANENTLY': 'مقفول دائم',
}


def tier1_google_details(store, log_fn=print):
    """
    إرجاع dict: {tier, status, source, evidence, raw}
    """
    v5 = store.get('v5') or {}
    cand = v5.get('candidate') or {}
    place_id = cand.get('place_id', '')

    if not place_id:
        return None  # not eligible for tier 1

    details = fetch_place_details(place_id)
    if not details or details.get('_error'):
        return {
            'tier': 1,
            'status': 'غير محدد',
            'source': 'Google Places Details',
            'evidence': f"خطأ: {details.get('_error', 'unknown') if details else 'مفيش رد'}",
            'raw': details,
        }

    biz_status = details.get('businessStatus', '')
    status_ar = STATUS_MAP.get(biz_status, 'غير محدد')

    rating = details.get('rating')
    review_count = details.get('userRatingCount')
    open_now = (details.get('currentOpeningHours') or {}).get('openNow')

    evidence_parts = [f"Google: {biz_status}"]
    if review_count: evidence_parts.append(f"{review_count} تقييم")
    if rating: evidence_parts.append(f"rating={rating}")
    if open_now is not None: evidence_parts.append(f"الآن: {'مفتوح' if open_now else 'مقفول'}")

    return {
        'tier': 1,
        'status': status_ar,
        'source': 'Google Places Details',
        'evidence': ' | '.join(evidence_parts),
        'business_status_raw': biz_status,
        'rating': rating,
        'review_count': review_count,
        'open_now': open_now,
        'opening_hours': (details.get('regularOpeningHours') or {}).get('weekdayDescriptions', []),
    }


def run_tier1(stores, log_fn=print):
    """شغّل tier 1 على كل المتاجر اللي عندها place_id."""
    eligible = [s for s in stores if ((s.get('v5') or {}).get('candidate') or {}).get('place_id')]
    log_fn(f"\n=== Tier 1: Google Places Details ===")
    log_fn(f"  Eligible: {len(eligible)} متجر معاهم place_id")

    counts = {}
    for i, s in enumerate(eligible, 1):
        result = tier1_google_details(s, log_fn=log_fn)
        if result:
            s['status_check'] = result
            st = result['status']
            counts[st] = counts.get(st, 0) + 1
            log_fn(f"  [{i:>2}/{len(eligible)}] {s['name_ar'][:30]:30} → {st:13} | {result['evidence']}")
        time.sleep(0.2)

    log_fn(f"\nملخص Tier 1:")
    for k, v in counts.items():
        log_fn(f"  {k}: {v}")
    return stores
