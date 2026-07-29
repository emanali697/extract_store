"""
Google Places API - البحث عن مواقع المتاجر مع تحديد المنطقة
"""
import time
import requests
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from config import (
    GCP_CREDENTIALS, PLACES_RADIUS_METERS,
    PLACES_NEARBY_THRESHOLD, PLACES_MAX_RESULTS, PLACES_DELAY,
)
from progress import emit_progress

_creds = None


def get_creds():
    global _creds
    if _creds is None:
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        if GCP_CREDENTIALS:
            _creds = service_account.Credentials.from_service_account_file(
                GCP_CREDENTIALS,
                scopes=scopes,
            )
        else:
            _creds, _ = google_auth_default(scopes=scopes)
    if not _creds.valid:
        _creds.refresh(Request())
    return _creds


def search_place(store_name, center_lat, center_lng, radius=None):
    """
    البحث عن متجر بالاسم داخل دائرة حول الإحداثيات المركزية
    """
    if radius is None:
        radius = PLACES_RADIUS_METERS

    creds = get_creds()
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json',
        'X-Goog-FieldMask': ','.join([
            'places.displayName',
            'places.formattedAddress',
            'places.location',
            'places.nationalPhoneNumber',
            'places.internationalPhoneNumber',
            'places.rating',
            'places.userRatingCount',
            'places.googleMapsUri',
            'places.businessStatus',
        ])
    }

    data = {
        'textQuery': store_name,
        'languageCode': 'ar',
        'maxResultCount': PLACES_MAX_RESULTS,
        'locationBias': {
            'circle': {
                'center': {'latitude': center_lat, 'longitude': center_lng},
                'radius': radius
            }
        }
    }

    try:
        resp = requests.post(
            'https://places.googleapis.com/v1/places:searchText',
            headers=headers,
            json=data,
            timeout=30
        )
        if resp.status_code == 200:
            result = resp.json()
            if 'places' in result and len(result['places']) > 0:
                # اختار أقرب نتيجة
                return select_best_match(result['places'], center_lat, center_lng)
        return None
    except Exception as e:
        return None


def select_best_match(places, center_lat, center_lng):
    """اختيار أقرب نتيجة من قائمة Places"""
    best = None
    best_dist = 999999
    for p in places:
        loc = p.get('location', {})
        plat = loc.get('latitude', 0)
        plng = loc.get('longitude', 0)
        # تقدير المسافة بالمتر
        dist = ((plat - center_lat) ** 2 + (plng - center_lng) ** 2) ** 0.5 * 111000
        if dist < best_dist:
            best_dist = dist
            best = {**p, '_distance_m': int(dist)}
    return best


def enrich_stores(stores, center_lat, center_lng, log_fn=print):
    """
    إضافة بيانات Places API لكل متجر
    """
    log_fn(f"\nPlaces lookup: {len(stores)} stores, center {center_lat},{center_lng}")
    total = max(1, len(stores))
    emit_progress(0, total, log_fn=log_fn)

    for i, store in enumerate(stores, 1):
        emit_progress(i, total, log_fn=log_fn)
        name = store.get('name_ar', '').strip()
        if not name:
            continue

        pct = int(i / len(stores) * 100)
        log_fn(f"  [{pct}%] {i}/{len(stores)}: {name}")

        place = search_place(name, center_lat, center_lng)

        if place:
            dist = place.get('_distance_m', 99999)
            nearby = dist < PLACES_NEARBY_THRESHOLD

            store['places'] = {
                'name': place.get('displayName', {}).get('text', ''),
                'address': place.get('formattedAddress', ''),
                'lat': str(place.get('location', {}).get('latitude', '')),
                'lng': str(place.get('location', {}).get('longitude', '')),
                'phone': place.get('nationalPhoneNumber', '') or place.get('internationalPhoneNumber', ''),
                'rating': str(place.get('rating', '')),
                'reviews': str(place.get('userRatingCount', '')),
                'maps_url': place.get('googleMapsUri', ''),
                'business_status': place.get('businessStatus', ''),
                'distance_m': dist,
                'match_status': 'مطابق' if nearby else 'بعيد',
            }

            if nearby:
                log_fn(f"     >> MATCH: {place.get('displayName', {}).get('text', '')} ({dist}m)")
            else:
                log_fn(f"     >> FAR: {place.get('displayName', {}).get('text', '')} ({dist}m)")
        else:
            store['places'] = {'match_status': 'غير موجود'}
            log_fn(f"     >> NOT FOUND")

        time.sleep(PLACES_DELAY)

    return stores
