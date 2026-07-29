"""
دمج المتاجر المكررة (نفس المتجر بقراءات OCR مختلفة).
معايير التكرار:
- ≥1 كلمة جوهرية مشتركة + Jaccard ≥ 0.5 على الكلمات الجوهرية
- المسافة بين الفريمات ≤ 8

استراتيجية الدمج:
- الاسم: الأطول/الأكمل (لو متساويين، اللي فيه تليفون)
- التليفون: union من كل القراءات
- الفريمات: union
- التصنيف: الأكثر تكراراً
- الموقع: أحسن v5 match (confirmed_high > confirmed_medium > frame_only)
- ملاحظات: union
"""
import re
from collections import Counter


STOP_WORDS = {
    'مطعم', 'مطاعم', 'بوفية', 'بوفيه', 'كفتيريا', 'كفتريا',
    'محل', 'محلات', 'تموينات', 'بقالة', 'عصيرات',
    'فول', 'تميس', 'تفسيس', 'مغاسل',
    'و', 'ال', 'في', 'للأسر', 'للاسر',
    'المدينه', 'المدينة', 'الجديده', 'الجديدة',
}


def normalize_arabic(text):
    if not text:
        return ""
    text = re.sub(r'[ً-ْٰ]', '', text)
    text = text.replace('ة', 'ه').replace('ى', 'ي')
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    text = text.replace('ؤ', 'و').replace('ئ', 'ي')
    return re.sub(r'\s+', ' ', text).strip()


def core_words(text):
    words = normalize_arabic(text).split()
    return set(w for w in words if w not in STOP_WORDS and len(w) >= 3)


def parse_frames(s):
    if not s:
        return []
    out = []
    for part in str(s).split(','):
        part = part.strip()
        if '-' in part:
            try:
                a, b = part.split('-')
                out.extend(range(int(a), int(b) + 1))
            except ValueError:
                continue
        else:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return sorted(set(out))


def frame_distance(f1, f2):
    if not f1 or not f2:
        return 999
    if set(f1) & set(f2):
        return 0
    return min(abs(a - b) for a in f1 for b in f2)


def is_duplicate(s1, s2, max_frame_gap=8, min_jaccard=0.5):
    c1 = core_words(s1.get('name_ar', ''))
    c2 = core_words(s2.get('name_ar', ''))
    if not c1 or not c2:
        return False
    common = c1 & c2
    if not common:
        return False
    jac = len(common) / len(c1 | c2)
    if jac < min_jaccard:
        return False
    fd = frame_distance(parse_frames(s1.get('frame', '')), parse_frames(s2.get('frame', '')))
    return fd <= max_frame_gap


def find_duplicate_groups(stores):
    """Union-Find لتجميع المتاجر المكررة."""
    n = len(stores)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if is_duplicate(stores[i], stores[j]):
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(stores[i])
    return list(groups.values())


def pick_best_name(group):
    """أحسن اسم: الأطول، ولو متساويين، اللي فيه تليفون."""
    def score(s):
        name = (s.get('name_ar') or '').strip()
        return (len(name), 1 if s.get('phone') else 0, len(name.split()))
    return sorted(group, key=score, reverse=True)[0].get('name_ar', '')


def merge_phones(group):
    """جمع كل الأرقام الفريدة."""
    phones = set()
    for s in group:
        raw = s.get('phone', '') or ''
        for p in raw.split(','):
            p = p.strip()
            if p:
                phones.add(p)
    return ', '.join(sorted(phones))


def merge_frames(group):
    """جمع كل الفريمات وعرضها كـ ranges."""
    all_frames = set()
    for s in group:
        all_frames.update(parse_frames(s.get('frame', '')))
    if not all_frames:
        return ''
    sorted_f = sorted(all_frames)
    # compress to ranges
    ranges = []
    start = sorted_f[0]
    prev = start
    for f in sorted_f[1:]:
        if f == prev + 1:
            prev = f
        else:
            ranges.append(f"{start}-{prev}" if start != prev else str(start))
            start = f
            prev = f
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ','.join(ranges)


def merge_category(group):
    cats = [s.get('category', '') for s in group if s.get('category')]
    if not cats:
        return ''
    return Counter(cats).most_common(1)[0][0]


def pick_best_location(group):
    """أفضل مطابقة v5: confirmed_high > confirmed_medium > frame_only."""
    priority = {'confirmed_high': 3, 'confirmed_medium': 2, 'frame_only': 1}
    def score(s):
        v5 = s.get('v5', {}) or {}
        st = v5.get('status', 'frame_only')
        conf = v5.get('confidence', 0)
        return (priority.get(st, 0), conf)
    return sorted(group, key=score, reverse=True)[0]


def merge_notes(group):
    notes = [s.get('notes', '') for s in group if s.get('notes')]
    seen = set()
    out = []
    for n in notes:
        if n not in seen:
            seen.add(n); out.append(n)
    return ' | '.join(out)


def merge_ocr_texts(group):
    """Union of all raw OCR strings from the merged group."""
    chunks = []
    seen = set()
    for s in group:
        raw = (s.get('ocr_text') or '').strip()
        if not raw:
            continue
        # The single store may itself already hold a pipe-joined list
        for part in raw.split(' | '):
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                chunks.append(part)
    return ' | '.join(chunks)


def merge_group(group):
    """دمج مجموعة من المتاجر المكررة في واحد."""
    if len(group) == 1:
        s = dict(group[0])
        s['merged_from'] = 1
        s['original_names'] = [s.get('name_ar', '')]
        return s

    base = pick_best_location(group)
    merged = dict(base)
    merged['name_ar'] = pick_best_name(group)
    merged['phone'] = merge_phones(group)
    merged['frame'] = merge_frames(group)
    merged['category'] = merge_category(group) or merged.get('category', '')
    merged['notes'] = merge_notes(group)
    merged['ocr_text'] = merge_ocr_texts(group)
    merged['merged_from'] = len(group)
    merged['original_names'] = [s.get('name_ar', '') for s in group]
    return merged


def dedupe_stores(stores, log_fn=print):
    """الواجهة الرئيسية: ياخد قائمة، يرجع قائمة بعد الدمج."""
    groups = find_duplicate_groups(stores)
    merged = [merge_group(g) for g in groups]
    n_dupes = sum(1 for g in groups if len(g) > 1)
    log_fn(f"Dedupe: {len(stores)} → {len(merged)} متجر ({n_dupes} مجموعات اتدمجت)")
    return merged
