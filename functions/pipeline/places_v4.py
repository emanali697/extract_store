"""
Google Places API v4:
- بحث per-store بإحداثيات المتجر (مش مركز الفيديو)
- locationRestriction (صارم) بدل locationBias (تلميح)
- reverse geocoding على الإحداثيات
- بحث بالتليفون
"""
import time
import requests
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from config import GCP_CREDENTIALS, PLACES_DELAY
from osm import haversine

_creds = None

PLACES_BASE_FIELDS = [
    'places.id',
    'places.displayName',
    'places.formattedAddress',
    'places.location',
    'places.types',
    'places.nationalPhoneNumber',
    'places.internationalPhoneNumber',
    'places.rating',
    'places.userRatingCount',
    'places.googleMapsUri',
    'places.businessStatus',
    'places.primaryType',
    'places.primaryTypeDisplayName',
]


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


def _headers(field_mask=None):
    creds = get_creds()
    return {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json',
        'X-Goog-FieldMask': ','.join(field_mask or PLACES_BASE_FIELDS),
    }


def search_text_strict(query, lat, lng, radius=80, max_results=5):
    """
    بحث نصي بـ locationRestriction صارم — مفيش fallback عالمي.
    radius 80م = ضمن الشارع نفسه.
    """
    data = {
        'textQuery': query,
        'languageCode': 'ar',
        'regionCode': 'SA',
        'maxResultCount': max_results,
        'locationRestriction': {
            'circle': {
                'center': {'latitude': lat, 'longitude': lng},
                'radius': radius
            }
        }
    }
    try:
        resp = requests.post(
            'https://places.googleapis.com/v1/places:searchText',
            headers=_headers(),
            json=data,
            timeout=30,
        )
        if resp.status_code == 200:
            return _annotate_distance(resp.json().get('places', []), lat, lng)
        return []
    except Exception:
        return []


def search_text_biased(query, lat, lng, radius=200, max_results=5):
    """
    بحث نصي بـ locationBias (مرن) — للحالات اللي الـ strict مرجعش حاجة.
    """
    data = {
        'textQuery': query,
        'languageCode': 'ar',
        'regionCode': 'SA',
        'maxResultCount': max_results,
        'locationBias': {
            'circle': {
                'center': {'latitude': lat, 'longitude': lng},
                'radius': radius
            }
        }
    }
    try:
        resp = requests.post(
            'https://places.googleapis.com/v1/places:searchText',
            headers=_headers(),
            json=data,
            timeout=30,
        )
        if resp.status_code == 200:
            return _annotate_distance(resp.json().get('places', []), lat, lng)
        return []
    except Exception:
        return []


def search_nearby(lat, lng, radius=80, included_types=None, max_results=20):
    """
    بحث جغرافي خالص (مفيش query) - يرجع كل الـ POIs في الدائرة.
    مفيد للـ reverse geocoding بشكل غير مباشر.
    """
    data = {
        'maxResultCount': max_results,
        'languageCode': 'ar',
        'regionCode': 'SA',
        'locationRestriction': {
            'circle': {
                'center': {'latitude': lat, 'longitude': lng},
                'radius': radius
            }
        }
    }
    if included_types:
        data['includedTypes'] = included_types

    try:
        resp = requests.post(
            'https://places.googleapis.com/v1/places:searchNearby',
            headers=_headers(),
            json=data,
            timeout=30,
        )
        if resp.status_code == 200:
            return _annotate_distance(resp.json().get('places', []), lat, lng)
        return []
    except Exception:
        return []


def search_by_phone(phone_e164):
    """
    بحث بالتليفون (الأقوى مطابقة لما الرقم متاح).
    phone_e164: +9665XXXXXXXX
    """
    data = {
        'textQuery': phone_e164,
        'languageCode': 'ar',
        'regionCode': 'SA',
        'maxResultCount': 3,
    }
    try:
        resp = requests.post(
            'https://places.googleapis.com/v1/places:searchText',
            headers=_headers(),
            json=data,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get('places', [])
        return []
    except Exception:
        return []


def _annotate_distance(places, lat, lng):
    """إضافة _distance_m لكل result + ترتيب"""
    out = []
    for p in places:
        loc = p.get('location') or {}
        plat = loc.get('latitude')
        plng = loc.get('longitude')
        if plat is None or plng is None:
            continue
        dist = int(haversine(lat, lng, plat, plng))
        out.append({**p, '_distance_m': dist})
    return sorted(out, key=lambda p: p['_distance_m'])


def to_e164(phone_local):
    """0512345678 → +966512345678"""
    if not phone_local:
        return None
    if phone_local.startswith('0') and len(phone_local) == 10:
        return '+966' + phone_local[1:]
    if phone_local.startswith('966'):
        return '+' + phone_local
    return phone_local


def normalize_place(p, source='google'):
    """تحويل response لشكل موحد"""
    loc = p.get('location') or {}
    name_obj = p.get('displayName') or {}
    primary_obj = p.get('primaryTypeDisplayName') or {}

    return {
        'name': name_obj.get('text', '') if isinstance(name_obj, dict) else str(name_obj),
        'address': p.get('formattedAddress', ''),
        'lat': loc.get('latitude'),
        'lng': loc.get('longitude'),
        'phone': p.get('nationalPhoneNumber') or p.get('internationalPhoneNumber', ''),
        'rating': p.get('rating'),
        'reviews': p.get('userRatingCount'),
        'maps_url': p.get('googleMapsUri', ''),
        'business_status': p.get('businessStatus', ''),
        'category': primary_obj.get('text', '') if isinstance(primary_obj, dict) else '',
        'types': p.get('types', []),
        'place_id': p.get('id', ''),
        'distance_m': p.get('_distance_m'),
        '_source': source,
    }


def lookup_store_candidates(store_name, lat, lng, phone=None, log_fn=print):
    """
    لكل متجر، نجمع candidates من Google Places بطرق متعددة:
    1. بحث صارم بالاسم في 80م
    2. لو فاضي، صارم في 200م
    3. لو فيه تليفون → بحث بالتليفون
    4. reverse: nearby search على الإحداثية الدقيقة (يلتقط POIs مش متطابقة بالاسم)
    """
    candidates = []

    if not lat or not lng:
        return candidates

    # 1. اسم + 80م صارم
    if store_name:
        results = search_text_strict(store_name, lat, lng, radius=80, max_results=3)
        for p in results:
            candidates.append(normalize_place(p, 'google_strict_80m'))

        time.sleep(PLACES_DELAY)

        # 2. لو مفيش، اسم + 200م
        if not results:
            results = search_text_strict(store_name, lat, lng, radius=200, max_results=3)
            for p in results:
                candidates.append(normalize_place(p, 'google_strict_200m'))
            time.sleep(PLACES_DELAY)

    # 3. بحث بالتليفون
    if phone:
        e164 = to_e164(phone)
        if e164:
            results = search_by_phone(e164)
            for p in results:
                norm = normalize_place(p, 'google_phone')
                # حساب المسافة من إحداثيات المتجر
                if norm['lat'] and norm['lng']:
                    norm['distance_m'] = int(haversine(lat, lng, norm['lat'], norm['lng']))
                candidates.append(norm)
            time.sleep(PLACES_DELAY)

    # 4. nearby reverse على الإحداثيات (يلتقط POIs قريبة جداً مهما كان اسمها)
    nearby = search_nearby(lat, lng, radius=40, max_results=10)
    for p in nearby:
        candidates.append(normalize_place(p, 'google_nearby_40m'))

    # دمج المكررات بنفس place_id
    seen = {}
    for c in candidates:
        pid = c.get('place_id')
        if not pid:
            continue
        if pid not in seen:
            seen[pid] = c
            seen[pid]['sources'] = [c['_source']]
        else:
            if c['_source'] not in seen[pid]['sources']:
                seen[pid]['sources'].append(c['_source'])

    return list(seen.values())
