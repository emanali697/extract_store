"""
Multi-source aggregator + confidence scoring.
يجمع candidates من Google + OSM (و HERE/معروف لو متاحين)،
ويستدعي Vision Judge لاختيار الأفضل.
"""
import os
import time

from osm import search_osm_for_store, haversine
from places_v4 import lookup_store_candidates
from street_view import fetch_street_view, check_metadata
from vision_judge import judge_candidates


def collect_candidates(store, log_fn=print):
    """
    لكل متجر، نجمع candidates من كل المصادر.
    """
    name = (store.get('name_ar') or '').strip()
    lat = store.get('lat')
    lng = store.get('lng')
    phone = store.get('phone', '')

    try:
        lat_f = float(lat) if lat else None
        lng_f = float(lng) if lng else None
    except (TypeError, ValueError):
        lat_f, lng_f = None, None

    if lat_f is None or lng_f is None:
        return []

    candidates = []

    # Google Places (متعدد الاستراتيجيات)
    google_cands = lookup_store_candidates(name, lat_f, lng_f, phone=phone, log_fn=log_fn)
    candidates.extend(google_cands)

    # OSM
    osm_cands = search_osm_for_store(name, lat_f, lng_f, radius_m=120, log_fn=log_fn)
    for c in osm_cands[:5]:
        candidates.append({
            'name': c['name'],
            'address': '',
            'lat': c['lat'],
            'lng': c['lng'],
            'phone': c.get('phone', ''),
            'rating': None,
            'reviews': None,
            'maps_url': '',
            'business_status': '',
            'category': c.get('category', ''),
            'types': [],
            'place_id': c.get('osm_id', ''),
            'distance_m': c.get('distance_m'),
            '_source': 'osm',
            'name_similarity': c.get('name_similarity', 0),
        })

    return candidates


def score_candidate(store, candidate):
    """
    Heuristic scoring قبل ما نستدعي Vision Judge (للترشيح المسبق).
    """
    score = 0.0

    # المسافة
    dist = candidate.get('distance_m') or 9999
    if dist < 30:
        score += 0.4
    elif dist < 80:
        score += 0.3
    elif dist < 200:
        score += 0.15
    elif dist < 500:
        score += 0.05

    # تطابق التليفون
    s_phone = (store.get('phone') or '').replace(' ', '')
    c_phone_raw = (candidate.get('phone') or '').replace(' ', '').replace('+966', '0').replace('-', '')
    if s_phone and c_phone_raw and s_phone in c_phone_raw or c_phone_raw in s_phone:
        if s_phone and c_phone_raw:
            score += 0.4

    # تشابه الاسم (لـ OSM لو محسوب)
    if 'name_similarity' in candidate:
        score += candidate['name_similarity'] * 0.3

    # التصنيف
    s_cat = (store.get('category') or '').strip()
    c_cat = (candidate.get('category') or '').strip()
    if s_cat and c_cat:
        # مقارنة بسيطة بمعجم محدود
        cat_match = {
            'مطعم': ['restaurant', 'food', 'fast_food', 'مطعم'],
            'بقالة': ['supermarket', 'convenience', 'grocery', 'بقالة'],
            'صيدلية': ['pharmacy', 'صيدلية'],
            'ملحمة': ['butcher', 'ملحمة'],
            'كافيه': ['cafe', 'coffee', 'كافيه', 'قهوة'],
            'اتصالات': ['telecom', 'mobile_phone', 'اتصالات'],
            'بنك': ['bank', 'atm', 'بنك'],
        }
        keywords = cat_match.get(s_cat, [s_cat])
        if any(k.lower() in c_cat.lower() for k in keywords):
            score += 0.2

    # تنوع المصادر (لو candidate نفسه ظاهر في sources متعددة → ثقة أعلى)
    sources = candidate.get('sources', [candidate.get('_source', '')])
    if len(sources) >= 2:
        score += 0.1

    return min(score, 1.0)


def filter_top_candidates(store, candidates, top_k=5):
    """رتب وارجع أفضل K candidates للـ Vision Judge"""
    scored = [(score_candidate(store, c), c) for c in candidates]
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:top_k]]


def adjudicate_store(store, output_dir, use_vision=True, use_street_view=False, log_fn=print):
    """
    لكل متجر:
    1. اجمع candidates
    2. رتبهم بـ heuristic
    3. (اختياري) Street View للأعلى مرتبة
    4. Vision Judge → اختار الأفضل + confidence
    5. ارجع dict موحد
    """
    name = (store.get('name_ar') or '').strip()
    log_fn(f"  → adjudicating: {name or '(no name)'}")

    candidates = collect_candidates(store, log_fn=log_fn)
    if not candidates:
        return {
            'final_match': None,
            'confidence': 0.0,
            'reasoning': 'لم يُعثر على candidates',
            'all_candidates': [],
            'judge_scores': [],
        }

    log_fn(f"     {len(candidates)} candidates")

    top = filter_top_candidates(store, candidates, top_k=5)

    # Street View للـ best heuristic candidate
    street_view_paths = {}
    if use_street_view and top:
        sv_dir = os.path.join(output_dir, "street_view")
        os.makedirs(sv_dir, exist_ok=True)
        for i, c in enumerate(top[:1]):  # واحد بس عشان التكلفة
            if c.get('lat') and c.get('lng'):
                meta = check_metadata(c['lat'], c['lng'])
                if meta and meta.get('status') == 'OK':
                    sv_path = os.path.join(sv_dir, f"sv_{c.get('place_id', i)[:30]}.jpg")
                    if not os.path.exists(sv_path):
                        fetch_street_view(c['lat'], c['lng'], sv_path, log_fn=log_fn)
                    if os.path.exists(sv_path):
                        street_view_paths[i] = sv_path

    # Vision Judge
    if use_vision:
        result = judge_candidates(
            store, top,
            sign_image_path=store.get('_sign_image'),
            street_view_paths=street_view_paths,
            log_fn=log_fn,
        )
    else:
        # heuristic فقط
        if top:
            result = {
                'best_index': 0,
                'confidence': score_candidate(store, top[0]),
                'reasoning': 'heuristic فقط (vision معطل)',
                'all_scores': [],
            }
        else:
            result = {'best_index': None, 'confidence': 0, 'reasoning': '', 'all_scores': []}

    best_idx = result.get('best_index')
    final_match = top[best_idx] if best_idx is not None and best_idx < len(top) else None

    return {
        'final_match': final_match,
        'confidence': result.get('confidence', 0),
        'reasoning': result.get('reasoning', ''),
        'all_candidates': candidates,
        'top_candidates': top,
        'judge_scores': result.get('all_scores', []),
    }


def adjudicate_all_stores(stores, output_dir, use_vision=True, use_street_view=False,
                          log_fn=print):
    """
    شغّل adjudicate_store على كل المتاجر وحط النتيجة في store['v4'].
    """
    n = len(stores)
    log_fn(f"\nAdjudicating {n} stores against multi-source candidates")
    log_fn(f"  Vision Judge: {'ON' if use_vision else 'OFF'}")
    log_fn(f"  Street View: {'ON' if use_street_view else 'OFF'}")

    for i, store in enumerate(stores, 1):
        log_fn(f"\n[{i}/{n}] {store.get('name_ar', '?')}")
        try:
            result = adjudicate_store(store, output_dir, use_vision, use_street_view, log_fn)
            store['v4'] = result

            fm = result['final_match']
            conf = result['confidence']
            if fm:
                log_fn(f"     → MATCH ({conf:.0%}): {fm.get('name', '')} "
                       f"[{fm.get('_source', '?')}, {fm.get('distance_m', '?')}م]")
            else:
                log_fn(f"     → NO MATCH ({conf:.0%}): {result.get('reasoning', '')}")
        except Exception as e:
            log_fn(f"     ERROR: {e}")
            store['v4'] = {
                'final_match': None,
                'confidence': 0,
                'reasoning': f'خطأ: {e}',
                'all_candidates': [],
                'top_candidates': [],
                'judge_scores': [],
            }

        time.sleep(0.5)  # rate limit

    return stores
