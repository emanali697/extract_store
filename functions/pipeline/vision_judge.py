"""
Gemini Vision Judge.
بياخد:
- صورة لافتة المتجر من الفيديو
- candidates من مصادر مختلفة (Google Places, OSM, ...)
- (اختياري) صورة Street View

يرجع: best candidate index + confidence (0-1) + سبب
"""
import json
import os
import re
from google import genai
from google.genai import types

from config import GCP_PROJECT_ID, GCP_LOCATION, GEMINI_MODEL, GEMINI_TEMPERATURE


_judge_client = None


def get_client():
    global _judge_client
    if _judge_client is None:
        _judge_client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location=GCP_LOCATION)
    return _judge_client


def _read_image_bytes(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        return f.read()


def judge_candidates(store, candidates, sign_image_path=None,
                    street_view_paths=None, log_fn=print):
    """
    store: dict فيه name_ar, category, phone (إن وجد)
    candidates: قائمة dicts (من sources مختلفة) مع name, category, phone, distance_m, _source
    sign_image_path: صورة اللافتة من الفيديو (اختياري)
    street_view_paths: dict {candidate_index: path} (اختياري)

    يرجع: {best_index, confidence, reasoning, all_scores}
    """
    if not candidates:
        return {
            'best_index': None,
            'confidence': 0.0,
            'reasoning': 'لا يوجد candidates',
            'all_scores': [],
        }

    if len(candidates) == 1:
        # candidate واحد بس → نقيّمه بسرعة
        return _single_candidate_judge(store, candidates[0], sign_image_path, log_fn)

    # بناء البرومبت
    parts = []

    sign_bytes = _read_image_bytes(sign_image_path)
    if sign_bytes:
        parts.append(types.Part.from_bytes(data=sign_bytes, mime_type='image/jpeg'))
        parts.append(types.Part.from_text(
            text="^ هذه صورة لافتة المتجر من فيديو الداش كام.\n"
        ))

    candidates_text = ""
    for i, c in enumerate(candidates):
        candidates_text += (
            f"\n[{i}] الاسم: {c.get('name', '')}\n"
            f"    التصنيف: {c.get('category', '')}\n"
            f"    التليفون: {c.get('phone', '')}\n"
            f"    المسافة: {c.get('distance_m', '?')}م\n"
            f"    المصدر: {c.get('_source', '?')}\n"
        )

    extracted = (
        f"البيانات المستخرجة من الفيديو:\n"
        f"  - الاسم: {store.get('name_ar', '')}\n"
        f"  - التصنيف: {store.get('category', '')}\n"
        f"  - التليفون: {store.get('phone', '')}\n"
    )

    prompt = (
        "أنت محكم خبير في مطابقة المتاجر السعودية.\n\n"
        + extracted +
        f"\nالـ candidates من قواعد البيانات:{candidates_text}\n\n"
        "اختر أفضل candidate يطابق المتجر في الصورة (إن وجدت)/البيانات المستخرجة.\n"
        "اعتمد على: تطابق الاسم، التصنيف، التليفون، قرب المسافة، وتطابق صورة اللافتة لو متوفرة.\n\n"
        "أرجع JSON فقط بهذا الشكل (بدون markdown):\n"
        '{"best_index": <رقم>, "confidence": <0.0-1.0>, "reasoning": "<سبب مختصر بالعربي>", '
        '"per_candidate": [{"index": 0, "score": 0.0-1.0, "reason": "..."}]}\n\n'
        "إذا لا يوجد candidate يصلح، رجّع best_index: null و confidence: 0\n"
    )

    parts.append(types.Part.from_text(text=prompt))

    try:
        resp = get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=[types.Content(role='user', parts=parts)],
            config={
                'temperature': 0.1,
                'max_output_tokens': 1024,
            },
        )
        text = resp.text.strip()
        if text.startswith('```'):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)

        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            return {
                'best_index': data.get('best_index'),
                'confidence': float(data.get('confidence', 0)),
                'reasoning': data.get('reasoning', ''),
                'all_scores': data.get('per_candidate', []),
            }
    except Exception as e:
        log_fn(f"  Vision Judge error: {e}")

    # fallback: candidate واحد
    return {
        'best_index': 0,
        'confidence': 0.5,
        'reasoning': 'fallback - judge لم يجاوب',
        'all_scores': [],
    }


def _single_candidate_judge(store, candidate, sign_image_path, log_fn):
    """تقييم candidate واحد فقط: هل يطابق ولا لأ؟"""
    parts = []

    sign_bytes = _read_image_bytes(sign_image_path)
    if sign_bytes:
        parts.append(types.Part.from_bytes(data=sign_bytes, mime_type='image/jpeg'))

    prompt = (
        "هل هذا الـ candidate يطابق المتجر؟\n\n"
        f"المتجر من الفيديو:\n"
        f"  الاسم: {store.get('name_ar', '')}\n"
        f"  التصنيف: {store.get('category', '')}\n"
        f"  التليفون: {store.get('phone', '')}\n\n"
        f"الـ Candidate:\n"
        f"  الاسم: {candidate.get('name', '')}\n"
        f"  التصنيف: {candidate.get('category', '')}\n"
        f"  التليفون: {candidate.get('phone', '')}\n"
        f"  المسافة: {candidate.get('distance_m', '?')}م\n\n"
        'أرجع JSON: {"match": true/false, "confidence": 0.0-1.0, "reasoning": "..."}\n'
    )
    parts.append(types.Part.from_text(text=prompt))

    try:
        resp = get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=[types.Content(role='user', parts=parts)],
            config={'temperature': 0.1, 'max_output_tokens': 512},
        )
        text = resp.text.strip()
        if text.startswith('```'):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            match = data.get('match', False)
            return {
                'best_index': 0 if match else None,
                'confidence': float(data.get('confidence', 0)) if match else 0.0,
                'reasoning': data.get('reasoning', ''),
                'all_scores': [],
            }
    except Exception as e:
        log_fn(f"  Vision Judge (single) error: {e}")

    return {
        'best_index': 0,
        'confidence': 0.4,
        'reasoning': 'تقييم تلقائي - candidate وحيد',
        'all_scores': [],
    }
