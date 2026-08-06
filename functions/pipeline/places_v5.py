"""
v5 matcher - استراتيجية واقعية:
- البحث بالاسم في Google Places مع تطبيع عربي
- قبول المطابقة بس لو distance ≤ 50م AND name_overlap ≥ 0.5
- لو مفيش مطابقة موثوقة → نستخدم إحداثيات الفريم من الداش كام ونعلم الموقع كـ "تقريبي"
"""
import re
import time

from places_v4 import search_text_biased, search_by_phone, normalize_place, to_e164
from osm import haversine

PLACES_DELAY = 0.1


def normalize_arabic(text):
    if not text:
        return ""
    text = re.sub(r'[ً-ْٰ]', '', text)
    text = text.replace('ة', 'ه').replace('ى', 'ي')
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    text = text.replace('ؤ', 'و').replace('ئ', 'ي')
    return re.sub(r'\s+', ' ', text).strip()


def name_overlap(a, b):
    aw = set(normalize_arabic(a).split())
    bw = set(normalize_arabic(b).split())
    if not aw or not bw:
        return 0.0
    aw -= {'ال', 'في', 'و', 'من'}
    bw -= {'ال', 'في', 'و', 'من'}
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / min(len(aw), len(bw))


def name_variants(name):
    base = (name or '').strip()
    if not base:
        return []
    out = [base]
    n = normalize_arabic(base)
    if n != base:
        out.append(n)
    no_filler = re.sub(r'\b(المدينه|المدينة|الجديده|الجديدة|للأسر|للاسر)\b', '', base).strip()
    no_filler = re.sub(r'\s+', ' ', no_filler)
    if no_filler and no_filler not in out:
        out.append(no_filler)
    words = base.split()
    if len(words) >= 3:
        out.append(' '.join(words[:2]))
    return list(dict.fromkeys(out))


def find_best_match(store_name, lat, lng, phone=None, log_fn=print):
    """
    رجّع dict موحد فيه:
      status: 'confirmed_high' | 'confirmed_medium' | 'frame_only'
      candidate: dict (لو في مطابقة) أو None
      score: 0..1
      reason: نص توضيحي
    """
    if not store_name or not lat or not lng:
        return _frame_only("اسم/إحداثيات ناقصة")

    best = None
    best_score = 0.0

    # 1) بحث بالاسم بكذا variant
    for v in name_variants(store_name):
        try:
            results = search_text_biased(v, lat, lng, radius=300, max_results=5)
        except Exception as e:
            log_fn(f"     places err: {e}")
            results = []
        time.sleep(PLACES_DELAY)
        for p in results:
            np = normalize_place(p)
            d = np.get('distance_m') or 9999
            if d > 80:
                continue
            ov = name_overlap(store_name, np['name'])
            if ov < 0.3:
                continue
            score = ov * 0.7 + max(0, (50 - d) / 50) * 0.3
            if score > best_score:
                best_score = score
                best = (np, ov, d, v)

    # 2) لو في تليفون، نتأكد بالبحث بيه (الأقوى لما يطابق)
    phone_match = None
    if phone:
        e164 = to_e164(phone.split(',')[0].strip() if ',' in phone else phone.strip())
        if e164:
            try:
                ph_results = search_by_phone(e164)
                time.sleep(PLACES_DELAY)
                for p in ph_results:
                    np = normalize_place(p)
                    if not np.get('lat') or not np.get('lng'):
                        continue
                    d = int(haversine(lat, lng, np['lat'], np['lng']))
                    np['distance_m'] = d
                    if d <= 100:
                        phone_match = np
                        break
            except Exception:
                pass

    # 3) قرار
    if phone_match and best:
        # لو الاتنين متفقين على نفس الـ place_id → ثقة عالية جداً
        if best[0].get('place_id') and best[0]['place_id'] == phone_match.get('place_id'):
            return {
                'status': 'confirmed_high',
                'candidate': best[0],
                'score': min(1.0, best_score + 0.2),
                'reason': f"اسم + تليفون يطابقوا (overlap={best[1]:.0%}, مسافة={best[2]}م)"
            }

    if best:
        np, ov, d, v_used = best
        if ov >= 0.75 and d <= 50:
            return {
                'status': 'confirmed_high',
                'candidate': np,
                'score': best_score,
                'reason': f"تطابق اسم قوي (overlap={ov:.0%}, مسافة={d}م)"
            }
        elif ov >= 0.5 and d <= 50:
            return {
                'status': 'confirmed_medium',
                'candidate': np,
                'score': best_score,
                'reason': f"تطابق اسم متوسط (overlap={ov:.0%}, مسافة={d}م)"
            }

    if phone_match:
        return {
            'status': 'confirmed_medium',
            'candidate': phone_match,
            'score': 0.6,
            'reason': f"تطابق تليفون (مسافة={phone_match['distance_m']}م)"
        }

    return _frame_only("مفيش مطابقة موثوقة في Google Places")


def _frame_only(reason):
    return {
        'status': 'frame_only',
        'candidate': None,
        'score': 0.0,
        'reason': reason,
    }


def match_all_stores(stores, log_fn=print):
    from progress import emit_progress
    n = len(stores)
    log_fn(f"\nv5 matching: {n} متجر\n")
    emit_progress(0, max(1, n), log_fn=log_fn)
    counts = {'confirmed_high': 0, 'confirmed_medium': 0, 'frame_only': 0}

    for i, s in enumerate(stores, 1):
        emit_progress(i, max(1, n), log_fn=log_fn)
        evidence = s.get('visual_evidence') or {}
        if not evidence.get('verified') or s.get('source_visible_in_video') is not True:
            result = _frame_only("مستبعد: لا يوجد دليل بصري مؤكد من الفيديو")
            s['v5'] = result
            s['excluded_from_results'] = True
            s['needs_review'] = True
            flags = list(s.get('review_flags') or [])
            if "لا يوجد دليل بصري مؤكد من الفيديو" not in flags:
                flags.append("لا يوجد دليل بصري مؤكد من الفيديو")
            s['review_flags'] = flags
            counts['frame_only'] += 1
            log_fn(f"  [{i:>2}/{n}] skipped: no verified video evidence")
            continue
        name = s.get('name_ar', '') or ''
        lat = s.get('lat')
        lng = s.get('lng')
        phone = s.get('phone', '') or ''

        try:
            lat_f = float(lat) if lat else None
            lng_f = float(lng) if lng else None
        except (TypeError, ValueError):
            lat_f, lng_f = None, None

        result = find_best_match(name, lat_f, lng_f, phone, log_fn=log_fn)
        s['v5'] = result
        counts[result['status']] += 1

        status_icon = {'confirmed_high': '✅', 'confirmed_medium': '🟡', 'frame_only': '📍'}[result['status']]
        match_name = result['candidate']['name'] if result['candidate'] else '(GPS من الفيديو)'
        log_fn(f"  [{i:>2}/{n}] {status_icon} {name[:30]:30} → {match_name[:35]}")

    log_fn(f"\nملخص v5:")
    log_fn(f"  ✅ مؤكد قوي:    {counts['confirmed_high']}")
    log_fn(f"  🟡 مؤكد متوسط:  {counts['confirmed_medium']}")
    log_fn(f"  📍 GPS الفيديو: {counts['frame_only']}")
    return stores
