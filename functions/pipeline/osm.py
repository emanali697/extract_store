"""
OpenStreetMap Overpass API - بحث مجاني عن POIs حول إحداثيات.
تغطية جدة/مكة في OSM ممتازة (مشاريع رسم الحرم).
"""
import re
import requests
from math import radians, sin, cos, sqrt, atan2

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_TIMEOUT = 25


def query_pois_near(lat, lng, radius_m=80, log_fn=print):
    """
    بحث عن كل POIs اللي ليها اسم/تصنيف في دائرة nصف قطرها radius_m.
    يرجع قائمة dicts: {name, name_ar, name_en, category, lat, lng, distance_m, phone, osm_id}
    """
    query = f"""
    [out:json][timeout:{OSM_TIMEOUT}];
    (
      node(around:{radius_m},{lat},{lng})["shop"];
      node(around:{radius_m},{lat},{lng})["amenity"~"restaurant|cafe|fast_food|pharmacy|bank|fuel|atm|clinic|hospital"];
      node(around:{radius_m},{lat},{lng})["office"];
      way(around:{radius_m},{lat},{lng})["shop"];
      way(around:{radius_m},{lat},{lng})["amenity"~"restaurant|cafe|fast_food|pharmacy|bank|fuel|atm|clinic|hospital"];
    );
    out center tags;
    """

    try:
        resp = requests.post(OVERPASS_URL, data={'data': query}, timeout=OSM_TIMEOUT + 5)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception as e:
        log_fn(f"  OSM error: {e}")
        return []

    results = []
    for el in data.get('elements', []):
        tags = el.get('tags', {})
        if 'center' in el:
            plat, plng = el['center']['lat'], el['center']['lon']
        else:
            plat, plng = el.get('lat'), el.get('lon')

        if plat is None:
            continue

        name = tags.get('name') or tags.get('name:ar') or tags.get('name:en')
        if not name:
            continue

        category = tags.get('shop') or tags.get('amenity') or tags.get('office', '')

        # تقدير المسافة بالمتر (haversine مبسط)
        dist = haversine(lat, lng, plat, plng)

        results.append({
            'name': name,
            'name_ar': tags.get('name:ar', ''),
            'name_en': tags.get('name:en', ''),
            'category': category,
            'lat': plat,
            'lng': plng,
            'distance_m': int(dist),
            'phone': tags.get('phone') or tags.get('contact:phone', ''),
            'website': tags.get('website') or tags.get('contact:website', ''),
            'osm_id': f"{el.get('type')}/{el.get('id')}",
            '_source': 'osm',
        })

    return sorted(results, key=lambda r: r['distance_m'])


def haversine(lat1, lng1, lat2, lng2):
    """مسافة هافرسين بالمتر"""
    R = 6371000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlam = radians(lng2 - lng1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlam / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def search_osm_for_store(store_name, lat, lng, radius_m=120, log_fn=print):
    """
    بحث في OSM عن متجر بالاسم ضمن دائرة.
    يرجع candidates مرتبة بالتشابه + المسافة.
    """
    if not lat or not lng:
        return []

    pois = query_pois_near(lat, lng, radius_m, log_fn=log_fn)
    if not pois:
        return []

    # نسبة تشابه بسيطة
    name_norm = (store_name or '').strip()
    candidates = []
    for p in pois:
        names_to_check = [p['name'], p.get('name_ar', ''), p.get('name_en', '')]
        max_sim = 0
        for n in names_to_check:
            if not n:
                continue
            sim = name_similarity(name_norm, n)
            if sim > max_sim:
                max_sim = sim
        candidates.append({**p, 'name_similarity': max_sim})

    return sorted(candidates,
                  key=lambda c: (-c['name_similarity'], c['distance_m']))


def name_similarity(a, b):
    """تشابه الأسماء (Jaccard على الكلمات)"""
    if not a or not b:
        return 0.0
    aw = set(re.findall(r'\w+', a.lower()))
    bw = set(re.findall(r'\w+', b.lower()))
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / len(aw | bw)
