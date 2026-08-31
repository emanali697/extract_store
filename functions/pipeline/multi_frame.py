"""
Multi-frame OCR aggregation.
نفس المتجر بيظهر في عدة فريمات → نجمع كل القراءات ونصوّت على الأدق.
"""
import re
from collections import Counter
from phone_utils import find_phones_in_text, vote_phones


def parse_frame_range(frame_str):
    """
    'frame': '1,2,3,4,5' أو '6-9' → [1,2,3,4,5]
    """
    if not frame_str:
        return []
    indices = []
    for part in str(frame_str).split(','):
        part = part.strip()
        if '-' in part:
            try:
                a, b = part.split('-', 1)
                indices.extend(range(int(a), int(b) + 1))
            except ValueError:
                continue
        else:
            try:
                indices.append(int(part))
            except ValueError:
                continue
    return indices


def aggregate_store_signals(store, ocr_texts, gps_data, processed_frames):
    """
    لكل متجر، نجمع OCR وGPS من كل الفريمات اللي ظهر فيها.

    Returns dict مع:
    - phones_voted: قائمة [(phone, kind, votes)] من كل القراءات
    - gps_points: قائمة [(lat, lng)] من كل الفريمات
    - gps_best: أحسن (lat, lng) للمتجر (median)
    - frame_indices: الفريمات اللي ظهر فيها
    - ocr_combined: نص OCR مدمج
    """
    frame_indices = parse_frame_range(store.get('frame', ''))
    if not frame_indices:
        return {
            'phones_voted': [],
            'gps_points': [],
            'gps_best': (None, None),
            'frame_indices': [],
            'ocr_combined': '',
        }

    # Map: final_idx → array index في processed_frames
    idx_to_pos = {}
    for pos, pf in enumerate(processed_frames):
        idx_to_pos[pf.get('final_idx', pos + 1)] = pos

    phone_lists = []
    gps_points = []
    ocr_chunks = []

    for fi in frame_indices:
        pos = idx_to_pos.get(fi)
        if pos is None:
            continue

        # OCR قد يكون معطلًا (قائمة فارغة)؛ لا نمنع حينها GPS median.
        text = ocr_texts[pos] if pos < len(ocr_texts) else ''
        if text:
            ocr_chunks.append(text)
            phones = find_phones_in_text(text)
            if phones:
                phone_lists.append(phones)

        gps = gps_data[pos] if pos < len(gps_data) else {}
        lat, lng = gps.get('lat'), gps.get('lng')
        if lat and lng:
            gps_points.append((float(lat), float(lng)))

    # تليفونات: تصويت
    phones_voted = vote_phones(phone_lists)

    # GPS: median (مقاوم للقيم الشاذة)
    gps_best = (None, None)
    if gps_points:
        lats = sorted(p[0] for p in gps_points)
        lngs = sorted(p[1] for p in gps_points)
        m = len(lats) // 2
        gps_best = (lats[m], lngs[m])

    return {
        'phones_voted': phones_voted,
        'gps_points': gps_points,
        'gps_best': gps_best,
        'frame_indices': frame_indices,
        'ocr_combined': '\n---\n'.join(ocr_chunks),
    }


def best_sign_image(store_signals, processed_frames):
    """
    اختار أحسن صورة لافتة للمتجر للتحقق البصري لاحقاً.
    معيار بسيط: الفريم اللي في النص (أوضح زاوية عادة).
    """
    indices = store_signals.get('frame_indices', [])
    if not indices:
        return None

    middle = indices[len(indices) // 2]
    for pf in processed_frames:
        if pf.get('final_idx') == middle:
            return pf.get('sign_path')
    return None


def enrich_stores_with_aggregates(stores, ocr_texts, gps_data, processed_frames):
    """
    إضافة الـ multi-frame aggregation لكل متجر:
    - تصويت تليفونات OCR (دليل مستقل) دون استبدال هاتف Gemini المقروء بصريًا
    - median GPS (مقاوم لقفزات OCR)
    - نص OCR المدمج كدليل (`vision_ocr_text`)
    - أحسن صورة لافتة
    """
    for store in stores:
        signals = aggregate_store_signals(store, ocr_texts, gps_data, processed_frames)

        # تليفونات OCR: تصويت عبر الفريمات كدليل مستقل.
        # هاتف Gemini البصري له الأولوية؛ OCR يملأ الهاتف فقط لو كان فارغًا.
        phones_voted = signals['phones_voted']
        if phones_voted:
            top = phones_voted[0]
            store['phone_votes'] = top[2]
            store['phones_all'] = [
                {'phone': p, 'kind': k, 'votes': v} for p, k, v in phones_voted
            ]
            if not (store.get('phone') or '').strip():
                store['phone'] = top[0]
                store['phone_kind'] = top[1]
                store['phone_source'] = 'cloud_vision_ocr'
        else:
            store['phones_all'] = []

        if signals['ocr_combined']:
            store['vision_ocr_text'] = signals['ocr_combined']

        # GPS: استخدم median من فريمات المتجر فعلاً
        lat, lng = signals['gps_best']
        if lat and lng:
            store['lat'] = f"{lat:.5f}"
            store['lng'] = f"{lng:.5f}"
            store['gps_samples'] = len(signals['gps_points'])

        store['_sign_image'] = best_sign_image(signals, processed_frames)
        store['_ocr_combined'] = signals['ocr_combined']

    return stores
