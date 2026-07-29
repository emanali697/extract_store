"""
Gemini Analyzer - تحليل نصوص OCR واستخراج بيانات منظمة للمتاجر
+ إضافة درجة ثقة ومعايير "محتاج مراجعة"
"""
import json
import time
import re
from google import genai

from config import (
    GCP_PROJECT_ID, GCP_LOCATION,
    GEMINI_MODEL, GEMINI_BATCH_SIZE, GEMINI_MAX_TOKENS,
    GEMINI_TEMPERATURE, GEMINI_RETRY_COUNT, GEMINI_DELAY,
    FLAG_MIN_NAME_LENGTH, FLAG_EMPTY_CATEGORY,
    FLAG_GHOST_CATEGORIES, FLAG_NO_ARABIC,
)
from progress import emit_progress

_gemini_client = None


class GeminiPermissionError(RuntimeError):
    """The pipeline identity cannot call Vertex AI prediction."""


def get_client():
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location=GCP_LOCATION)
    return _gemini_client


def build_prompt(batch_items):
    """بناء البرومبت لـ Gemini"""
    context = ""
    for item in batch_items:
        context += f"\n--- Frame {item['frame_num']} (t={item['timestamp']:.1f}s) ---\n"
        context += f"OCR Text: {item['ocr_text']}\n"
        if item.get('lat') and item.get('lng'):
            context += f"GPS: N:{item['lat']} E:{item['lng']}\n"
        if item.get('speed'):
            context += f"Speed: {item['speed']} km/h\n"

    return f"""You are analyzing OCR text from dashcam footage of stores/shops on a street in Saudi Arabia.

{context}

Extract each unique store/shop visible in the frames. Return ONLY a valid JSON array.

Each object must have these exact keys:
"name_ar" (Arabic store name from the sign - MUST be Arabic text),
"name_en" (English name if visible, else ""),
"category" (store type in Arabic e.g. مطعم، بقالة، صيدلية، ملابس),
"phone" (phone number if visible in OCR, else ""),
"status" ("مفتوح" or "مغلق"),
"frame" (frame number where it appeared, or comma-separated range),
"lat" (from GPS data),
"lng" (from GPS data),
"notes" (brief note in Arabic about sign color/location)

IMPORTANT RULES:
- name_ar MUST be Arabic text from the actual store sign (not translated)
- Include phone numbers if they appear in the OCR text
- Ignore: traffic signs, truck ads, car brand logos (MITSUBISHI, ISUZU etc on buildings = ignore), random text on passing vehicles
- Do NOT duplicate stores across frames
- If the same store appears in multiple frames, list it once with frame range
- Keep responses focused - only real, clearly readable store signs
- If no stores are visible, return []
- NO markdown code blocks, NO explanations - JUST the JSON array
"""


def parse_gemini_response(text):
    """تنظيف ومحاولة parsing للـ JSON"""
    text = text.strip()
    # Remove markdown code blocks
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Try to extract JSON array from text
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        text = match.group(0)

    return json.loads(text)


def analyze_batch(batch_items, log_fn=print):
    """تحليل مجموعة فريمات"""
    prompt = build_prompt(batch_items)
    client = get_client()

    last_error = None
    for attempt in range(GEMINI_RETRY_COUNT):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={
                    "temperature": GEMINI_TEMPERATURE,
                    "max_output_tokens": GEMINI_MAX_TOKENS,
                },
            )
            return parse_gemini_response(response.text)
        except json.JSONDecodeError as e:
            log_fn(f"  Gemini JSON error (attempt {attempt+1}/{GEMINI_RETRY_COUNT}): {e}")
            if attempt < GEMINI_RETRY_COUNT - 1:
                time.sleep(1)
        except Exception as e:
            last_error = e
            # Network drops / 503 / timeouts are transient — retry with backoff
            # instead of giving up on the whole batch immediately.
            log_fn(f"  Gemini ERROR (attempt {attempt+1}/{GEMINI_RETRY_COUNT}): {str(e)[:160]}")
            if attempt < GEMINI_RETRY_COUNT - 1:
                time.sleep(2 * (attempt + 1))
    log_fn("  >> batch فشل بعد كل المحاولات — هنكمّل من غيره")
    if last_error:
        error_text = str(last_error)
        if (
            "PERMISSION_DENIED" in error_text
            or "aiplatform.endpoints.predict" in error_text
            or "403" in error_text
        ):
            raise GeminiPermissionError(
                "Gemini/Vertex AI permission denied. Grant roles/aiplatform.user "
                f"to the runtime service account in project {GCP_PROJECT_ID}, "
                "then start a new analysis job."
            ) from last_error
    return []


def flag_uncertainty(store):
    """
    تحديد لو المتجر "محتاج مراجعة" وإرجاع سبب الشك
    """
    flags = []
    name = (store.get('name_ar') or '').strip()
    category = (store.get('category') or '').strip()

    # اسم قصير جداً
    if len(name) < FLAG_MIN_NAME_LENGTH:
        flags.append("اسم قصير")

    # اسم فاضي
    if not name:
        flags.append("اسم فاضي")

    # تصنيف مبهم
    if FLAG_EMPTY_CATEGORY and category in FLAG_GHOST_CATEGORIES:
        flags.append("تصنيف مبهم")

    # اسم بالإنجليزي فقط
    if FLAG_NO_ARABIC and name:
        has_arabic = any('\u0600' <= c <= '\u06FF' for c in name)
        if not has_arabic:
            flags.append("الاسم مش عربي")

    # أسماء مكررة بتباين بسيط تتحدد في الـ dedup stage

    return flags


def run_analysis(processed_frames, ocr_texts, gps_data, log_fn=print):
    """
    تحليل كامل: batches → Gemini → deduplicate → flag uncertainty
    """
    # بناء items
    items = []
    for i, frame in enumerate(processed_frames):
        items.append({
            'frame_num': frame.get('final_idx', i + 1),
            'timestamp': frame.get('timestamp', 0),
            'ocr_text': ocr_texts[i] if i < len(ocr_texts) else "",
            'lat': gps_data[i].get('lat') if i < len(gps_data) else None,
            'lng': gps_data[i].get('lng') if i < len(gps_data) else None,
            'speed': gps_data[i].get('speed') if i < len(gps_data) else None,
        })

    # batching
    all_stores = []
    total = len(items)
    total_batches = (total + GEMINI_BATCH_SIZE - 1) // GEMINI_BATCH_SIZE
    emit_progress(0, total_batches, log_fn=log_fn)

    for b in range(0, total, GEMINI_BATCH_SIZE):
        batch = items[b:b + GEMINI_BATCH_SIZE]
        batch_num = b // GEMINI_BATCH_SIZE + 1
        emit_progress(batch_num, total_batches, log_fn=log_fn)
        pct = int((b + len(batch)) / total * 100)
        done = pct // 5
        bar = "#" * done + "-" * (20 - done)

        frames_in_batch = [it['frame_num'] for it in batch]
        log_fn(f"\n[{bar}] {pct}% | Batch {batch_num}/{total_batches} | "
               f"Frames {frames_in_batch[0]}-{frames_in_batch[-1]} | "
               f"Stores so far: {len(all_stores)}")

        # تخطي الـ batches الفاضية
        has_text = any(it['ocr_text'].strip() for it in batch)
        if not has_text:
            log_fn(f"  >> Empty OCR, skipping")
            continue

        stores = analyze_batch(batch, log_fn=log_fn)
        if stores:
            log_fn(f"  >> Found {len(stores)} stores")
            for s in stores:
                ph = s.get('phone', '') or '-'
                log_fn(f"     [{s.get('frame','')}] {s.get('name_ar', '?')} | {s.get('category', '?')} | tel: {ph}")
            all_stores.extend(stores)

        time.sleep(GEMINI_DELAY)

    # Attach the original OCR text(s) to each Gemini-extracted store so
    # downstream review UIs can show the raw read alongside the extracted name.
    frame_to_ocr = {it['frame_num']: (it['ocr_text'] or '').strip() for it in items}

    def _ocr_for_frame_field(field_value):
        s = str(field_value or '')
        nums = []
        for part in s.split(','):
            part = part.strip()
            if '-' in part:
                try:
                    a, b = part.split('-')
                    nums.extend(range(int(a), int(b) + 1))
                except ValueError:
                    continue
            else:
                try:
                    nums.append(int(part))
                except ValueError:
                    continue
        texts = []
        seen = set()
        for n in nums:
            t = frame_to_ocr.get(n)
            if t and t not in seen:
                seen.add(t)
                texts.append(t)
        return ' | '.join(texts)

    for store in all_stores:
        store['ocr_text'] = _ocr_for_frame_field(store.get('frame', ''))

    # deduplicate
    log_fn(f"\nRaw stores: {len(all_stores)}")
    unique = deduplicate_stores(all_stores)
    log_fn(f"Unique stores: {len(unique)}")

    # flag uncertainty
    for store in unique:
        flags = flag_uncertainty(store)
        store['review_flags'] = flags
        store['needs_review'] = bool(flags)

    flagged = sum(1 for s in unique if s['needs_review'])
    log_fn(f"Flagged for review: {flagged}")

    return unique


def deduplicate_stores(stores):
    """دمج المتاجر المكررة"""
    seen = {}
    for s in stores:
        name = (s.get('name_ar') or '').strip()
        if not name:
            continue
        if name not in seen:
            seen[name] = s.copy()
        else:
            existing = seen[name]
            ef = str(existing.get('frame', ''))
            nf = str(s.get('frame', ''))
            if nf and nf not in ef:
                existing['frame'] = f"{ef},{nf}"
            # دمج الهواتف
            ep = existing.get('phone', '') or ''
            np = s.get('phone', '') or ''
            if np and np not in ep:
                existing['phone'] = f"{ep}, {np}" if ep else np
            # دمج نصوص OCR
            eo = (existing.get('ocr_text') or '').strip()
            no = (s.get('ocr_text') or '').strip()
            if no and no not in eo:
                existing['ocr_text'] = f"{eo} | {no}" if eo else no
    return list(seen.values())
