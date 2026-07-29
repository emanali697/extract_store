"""
Vision-based status check.
بياخد صور الفريمات اللي ظهر فيها المتجر، يبعتها لـ Gemini Vision،
ويسأله يحدد حالة المتجر بناءً على شواهد بصرية:
- shutter مفتوح/مقفول
- إضاءة شغالة
- يافطات إيجار/بيع
- حالة عامة (نشط/مهجور)
"""
import json
import os
import re

from google import genai
from google.genai import types

from config import GCP_PROJECT_ID, GCP_LOCATION, GEMINI_MODEL


_client = None


def get_client():
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location=GCP_LOCATION)
    return _client


def _read_image(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        return f.read()


def _parse_frame_field(frame_str):
    """
    'frame' field: '1,2,3,4,5' أو '2,3,4,6-9' → list of ints
    """
    if not frame_str:
        return []
    out = []
    for part in str(frame_str).split(','):
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


def pick_status_frames(frame_list, frames_dir, max_frames=2):
    """
    من قائمة فريمات المتجر، اختار 1-2 منهم لفحص الحالة.
    بنفضل الفريم في المنتصف (المتجر يبقى قبالة الكاميرا).
    """
    if not frame_list:
        return []
    # اختر middle و near-middle
    n = len(frame_list)
    if n == 1:
        picks = [frame_list[0]]
    elif n == 2:
        picks = frame_list
    else:
        mid = n // 2
        picks = [frame_list[mid]]
        if max_frames >= 2 and n >= 4:
            picks.append(frame_list[mid - 1] if mid > 0 else frame_list[0])

    paths = []
    for fnum in picks[:max_frames]:
        p = os.path.join(frames_dir, f"frame_{fnum:04d}.jpg")
        if os.path.exists(p):
            paths.append(p)
    return paths


STATUS_PROMPT = """
أنت خبير تحليل مرئي للمحلات التجارية في السعودية.

في الصورة دي فريم من داش كام لشارع، وفي متجر اسمه: "{name}" تصنيفه: "{category}".

شوف المتجر ده بالظبط (مش الجيران)، وحدد حالته:

1. هل الـ shutter (الباب الحديدي) مفتوح ولا مقفول؟
2. هل في إضاءة على اللوحة أو من جوه المحل؟
3. هل في يافطة "للإيجار" / "للبيع" / "تحت التجديد" / "مغلق"؟
4. هل اللوحة شكلها متهتك أو مهجور؟
5. هل في علامات إنه شغّال (زباين، منتجات معروضة، حركة)؟

ارجع JSON بس (بدون markdown):
{{
  "status": "نشط" | "مقفول مؤقت" | "مقفول دائم" | "غير محدد",
  "confidence": 0.0-1.0,
  "shutter": "مفتوح" | "مقفول" | "غير ظاهر",
  "lights": "شغالة" | "مطفية" | "غير ظاهر",
  "closure_signs": "نعم" | "لا" | "غير ظاهر",
  "abandoned_look": true/false,
  "evidence": "وصف مختصر لما شفته في الصورة"
}}

ملاحظات مهمة:
- "نشط" = الـ shutter مفتوح والمحل واضح إنه شغّال
- "مقفول مؤقت" = shutter مقفول لكن المحل سليم (عادي بعد ساعات العمل)
- "مقفول دائم" = يافطة إيجار/بيع، لوحة متهتكة، مهجور بصرياً
- "غير محدد" = الصورة مش واضحة أو المتجر مش ظاهر بشكل كافي
- لو الصورة فيها أكتر من متجر، ركز على المتجر اللي اسمه "{name}" فقط
"""


def check_store_status(store, frames_dir, log_fn=print):
    """
    لمتجر واحد: ارجع dict {status, confidence, evidence, ...}
    """
    name = (store.get('name_ar') or '').strip()
    category = (store.get('category') or '').strip()
    frame_field = store.get('frame', '')
    frame_nums = _parse_frame_field(frame_field)
    image_paths = pick_status_frames(frame_nums, frames_dir, max_frames=2)

    if not image_paths:
        return {
            'status': 'غير محدد',
            'confidence': 0.0,
            'evidence': 'مفيش صور فريمات متاحة',
            'frames_used': [],
        }

    parts = []
    for p in image_paths:
        img = _read_image(p)
        if img:
            parts.append(types.Part.from_bytes(data=img, mime_type='image/jpeg'))

    if not parts:
        return {
            'status': 'غير محدد',
            'confidence': 0.0,
            'evidence': 'فشل قراءة الصور',
            'frames_used': image_paths,
        }

    parts.append(types.Part.from_text(
        text=STATUS_PROMPT.format(name=name, category=category)
    ))

    try:
        resp = get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=[types.Content(role='user', parts=parts)],
            config={'temperature': 0.1, 'max_output_tokens': 600},
        )
        text = resp.text.strip()
        if text.startswith('```'):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            return {
                'status': data.get('status', 'غير محدد'),
                'confidence': float(data.get('confidence', 0)),
                'shutter': data.get('shutter', ''),
                'lights': data.get('lights', ''),
                'closure_signs': data.get('closure_signs', ''),
                'abandoned_look': data.get('abandoned_look', False),
                'evidence': data.get('evidence', ''),
                'frames_used': [os.path.basename(p) for p in image_paths],
            }
    except Exception as e:
        log_fn(f"  Vision status error for {name}: {e}")

    return {
        'status': 'غير محدد',
        'confidence': 0.0,
        'evidence': 'خطأ في Gemini Vision',
        'frames_used': [os.path.basename(p) for p in image_paths],
    }


def check_all_stores_status(stores, frames_dir, log_fn=print):
    """
    تحقق من حالة كل المتاجر. يضع النتيجة في store['vision_status'].
    """
    n = len(stores)
    log_fn(f"\nVision status check: {n} متجر")
    counts = {'نشط': 0, 'مقفول مؤقت': 0, 'مقفول دائم': 0, 'غير محدد': 0}

    for i, s in enumerate(stores, 1):
        result = check_store_status(s, frames_dir, log_fn=log_fn)
        s['vision_status'] = result
        counts[result['status']] = counts.get(result['status'], 0) + 1
        icon = {'نشط': '✅', 'مقفول مؤقت': '🟡', 'مقفول دائم': '🔴', 'غير محدد': '⚪'}.get(result['status'], '?')
        log_fn(f"  [{i:>2}/{n}] {icon} {s.get('name_ar', '')[:30]:30} → {result['status']:13} (ثقة={result['confidence']:.0%}) | {result['evidence'][:60]}")

    log_fn(f"\nملخص الحالة:")
    for k, v in counts.items():
        log_fn(f"  {k}: {v}")
    return stores
