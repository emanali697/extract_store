"""
Saudi Phone Number Validator + Corrector
- يفهم صيغ الجوال/الأرضي/الموحد السعودية
- بيصلح أخطاء OCR شائعة (8↔., 0↔O, 6↔G)
- voting من قراءات متعددة لنفس المتجر
"""
import re
from collections import Counter


SAUDI_MOBILE_PREFIXES = {'050', '053', '055', '054', '056', '057', '058', '059', '051'}
LANDLINE_AREA_CODES = {'011', '012', '013', '014', '016', '017'}  # الرياض، مكة/جدة، الشرقية، تبوك، عسير، حائل
UNIFIED_PREFIXES = {'920', '800', '8200'}

OCR_DIGIT_FIXES = {
    'O': '0', 'o': '0', 'D': '0',
    'I': '1', 'l': '1', '|': '1',
    'Z': '2',
    'B': '8',
    'G': '6', 'b': '6',
    'S': '5', 's': '5',
    'g': '9', 'q': '9',
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
    '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
}


def normalize_digits(text):
    """تحويل الأرقام العربية وأخطاء OCR لأرقام عادية"""
    if not text:
        return ''
    out = []
    for c in str(text):
        out.append(OCR_DIGIT_FIXES.get(c, c))
    return ''.join(out)


def extract_digits(text):
    """استخراج أرقام فقط بعد التطبيع"""
    return re.sub(r'\D', '', normalize_digits(text))


def classify_phone(digits):
    """
    تحديد نوع الرقم وصياغته الموحدة.
    ترجع: (formatted, kind) أو (None, None) لو غير صالح
    kind: 'mobile' | 'landline' | 'unified' | 'international'
    """
    if not digits:
        return None, None

    # دولي +966
    if digits.startswith('00966'):
        digits = '0' + digits[5:]
    elif digits.startswith('966') and len(digits) >= 11:
        digits = '0' + digits[3:]

    # موحد (920, 800)
    for pfx in UNIFIED_PREFIXES:
        if digits.startswith(pfx):
            if len(digits) == 9:
                return digits, 'unified'
            return None, None

    # جوال
    if len(digits) == 10:
        prefix = digits[:3]
        if prefix in SAUDI_MOBILE_PREFIXES:
            return digits, 'mobile'
        if prefix in LANDLINE_AREA_CODES:
            return digits, 'landline'

    # أرضي 9 أرقام (بدون 0)
    if len(digits) == 9 and digits[0] in '0' and digits[:3] in LANDLINE_AREA_CODES:
        return digits, 'landline'

    # أرضي 8 أرقام (بدون كود) — مش هنقبلها بدون كود
    return None, None


def correct_ocr_error(digits, candidates_pool):
    """
    لو الرقم غير صالح، نحاول نصلحه باستبدال رقم واحد كل مرة
    candidates_pool: قراءات تانية موجودة لنفس المتجر، نشوف لو في rooted
    """
    if not digits or len(digits) < 9:
        return None

    formatted, kind = classify_phone(digits)
    if formatted:
        return formatted

    # نجرب نستبدل أول حرف بـ 0 (لو كان شيء غريب)
    if not digits.startswith('0'):
        f, k = classify_phone('0' + digits[1:] if len(digits) >= 10 else '0' + digits)
        if f:
            return f
        f, k = classify_phone('0' + digits)
        if f:
            return f

    # قرب من قراءة تانية بـ Levenshtein
    for cand in candidates_pool:
        if cand and len(cand) == len(digits) and levenshtein(digits, cand) <= 1:
            return cand

    return None


def levenshtein(a, b):
    """مسافة ليفنشتاين بين سلسلتين"""
    if len(a) < len(b):
        return levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,
                curr[j] + 1,
                prev[j] + (ca != cb),
            ))
        prev = curr
    return prev[-1]


PHONE_REGEX = re.compile(
    r'(?:\+?966|00966)?\s*'
    r'(?:0|\(0\))?\s*'
    r'([1-9]\d{1,2})'
    r'[\s\-\.]?(\d{3})'
    r'[\s\-\.]?(\d{3,4})'
)


def find_phones_in_text(text):
    """
    استخراج كل الأرقام السعودية الصالحة من نص واحد.
    ترجع قائمة [(formatted, kind)] - بدون تكرار substrings.
    """
    if not text:
        return []

    normalized = normalize_digits(text)
    found = []
    seen = set()

    # نقطع النص لـ chunks بتاع أرقام (مفصولة بحروف/فواصل)
    # كل chunk يحتمل يكون فيه رقم، نسمح بفواصل خفيفة داخله
    # Pattern: تتابعات من أرقام + فواصل (شرطة/نقطة/مسافة) - حد أقصى 25 حرف
    for m in re.finditer(r'(?:\+?\d|\d)[\d\s\-\.\(\)]{6,24}\d', normalized):
        digits = re.sub(r'\D', '', m.group(0))
        if len(digits) < 8:
            continue

        # نجرب صيغة دولية الأول (12 رقم: 966XXXXXXXXX)
        consumed = [False] * len(digits)
        if len(digits) >= 12:
            for start in range(0, len(digits) - 11):
                sub = digits[start:start + 12]
                f, kind = classify_phone(sub)
                if f and f not in seen:
                    seen.add(f)
                    found.append((f, kind))
                    for k in range(start, start + 12):
                        consumed[k] = True
                    break

        # نجرب لكل بداية، نشوف لو بتشكل رقم صالح بطول 10 أو 9
        for length in (10, 9):
            start = 0
            while start <= len(digits) - length:
                if any(consumed[start:start + length]):
                    start += 1
                    continue
                sub = digits[start:start + length]
                f, kind = classify_phone(sub)
                if f and f not in seen:
                    seen.add(f)
                    found.append((f, kind))
                    for k in range(start, start + length):
                        consumed[k] = True
                    start += length
                else:
                    start += 1

    return found


def vote_phones(phone_lists):
    """
    دمج قراءات تليفونات من فريمات متعددة لنفس المتجر بالتصويت.

    phone_lists: قائمة قوائم (كل واحدة من فريم)
    ترجع: قائمة [(phone, kind, votes)] مرتبة بعدد الأصوات
    """
    counter = Counter()
    kinds = {}

    for plist in phone_lists:
        seen_in_frame = set()
        for phone, kind in plist:
            if phone in seen_in_frame:
                continue
            seen_in_frame.add(phone)
            counter[phone] += 1
            kinds[phone] = kind

    # ادمج الأرقام اللي تختلف برقم واحد (OCR error محتمل) لصالح الأكثر تكراراً
    phones_sorted = sorted(counter.keys(), key=lambda p: -counter[p])
    merged = {}
    for p in phones_sorted:
        absorbed = False
        for kept in merged:
            if len(kept) == len(p) and levenshtein(kept, p) == 1 and counter[kept] > counter[p]:
                merged[kept] += counter[p]
                absorbed = True
                break
        if not absorbed:
            merged[p] = counter[p]

    return [(p, kinds[p], v) for p, v in sorted(merged.items(), key=lambda x: -x[1])]


def format_phone_display(phone):
    """صياغة الرقم للعرض: 05X XXX XXXX"""
    if not phone:
        return ''
    if len(phone) == 10 and phone.startswith('0'):
        return f"{phone[:4]} {phone[4:7]} {phone[7:]}"
    if len(phone) == 9 and phone.startswith(('920', '800')):
        return f"{phone[:3]} {phone[3:6]} {phone[6:]}"
    return phone
