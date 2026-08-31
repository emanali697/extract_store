"""
Cloud Vision OCR — قراءة النصوص من صور اللوحات الإعلانية.

التحسينات:
1. نستخدم DOCUMENT_TEXT_DETECTION كأساسي (أفضل للعربي والنصوص الكثيفة على اللوحات).
2. fallback على TEXT_DETECTION لو DOCUMENT فشل أو رجّع فاضي.
3. معالجة صور قوية (CLAHE + denoise + unsharp mask) قبل OCR.
4. retry ذكي: لو صورة رجّع نص فاضي، نعيدها بمعالجة مختلفة.
5. دقة أعلى: MAX_OCR_WIDTH 3000 بدل 2048 عشان نحافظ على تفاصيل الخطوط الصغيرة.
6. عدد أقل من الـ parallel batches عشان نتجنب rate limits وفقدان الاستجابات.
"""
import io
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import vision
from PIL import Image, ImageEnhance, ImageFilter

from config import (
    CLOUD_VISION_BATCH_DELAY,  # kept for compat (currently unused)
    OCR_SIGN_LANGUAGE_HINTS,
)
from extractor import parse_gps_text
from progress import emit_progress, progress_ticker

_vision_client = None

# Cloud Vision حدود:
#   batch_annotate_images = أقصى 16 صورة في الطلب الواحد
BATCH_SIZE = 16
PARALLEL_BATCHES = 2         # قلّلناها من 4 لـ 2 عشان نتجنب rate limits
BATCH_RETRIES = 3
BATCH_BACKOFF = 2.0

# دقة أعلى للوحات اللي فيها خط صغير. لو الصورة أكبر من كده بنصغّرها.
# Cloud Vision بيتحمل صور لحد ~20MB، و2048px كان بيفقد تفاصيل خطوط صغيرة.
MAX_OCR_WIDTH = 3000


def _read_content(path):
    """اقرأ الصورة كـ bytes."""
    with open(path, 'rb') as f:
        return f.read()


def _pil_to_bytes(pil_img, quality=92):
    """حوّل PIL Image لـ JPEG bytes."""
    buf = io.BytesIO()
    # لو صورة RGBA حوّلها RGB
    if pil_img.mode in ('RGBA', 'LA', 'P'):
        pil_img = pil_img.convert('RGB')
    pil_img.save(buf, 'JPEG', quality=quality, optimize=True)
    return buf.getvalue()


def _open_image(path):
    """افتح الصورة وارجع PIL Image."""
    raw = _read_content(path)
    try:
        return Image.open(io.BytesIO(raw))
    except Exception:
        return None


def _resize_if_needed(pil_img):
    """صغّر الصورة لو عرضها أكبر من MAX_OCR_WIDTH."""
    w, h = pil_img.size
    if w > MAX_OCR_WIDTH:
        nh = int(h * MAX_OCR_WIDTH / w)
        return pil_img.resize((MAX_OCR_WIDTH, nh), Image.LANCZOS)
    return pil_img


def _preprocess_for_ocr(pil_img, mode='standard'):
    """
    معالجة الصورة قبل OCR.

    modes:
      'standard'  → CLAHE + denoise + unsharp mask (الأفضل للوحات).
      'soft'      → CLAHE خفيف + denoise بس.
      'sharp'     → تباين عالي + sharpness عالي.
    """
    # تأكد إنها RGB
    if pil_img.mode != 'RGB':
        pil_img = pil_img.convert('RGB')

    pil_img = _resize_if_needed(pil_img)

    if mode == 'standard':
        # CLAHE عبر PIL: نرفع contrast ونعمل sharpen
        enhancer = ImageEnhance.Contrast(pil_img)
        pil_img = enhancer.enhance(1.4)
        enhancer = ImageEnhance.Sharpness(pil_img)
        pil_img = enhancer.enhance(1.6)
        # unsharp mask بسيط
        pil_img = pil_img.filter(ImageFilter.UnsharpMask(radius=2, percent=100, threshold=3))

    elif mode == 'soft':
        enhancer = ImageEnhance.Contrast(pil_img)
        pil_img = enhancer.enhance(1.2)
        enhancer = ImageEnhance.Sharpness(pil_img)
        pil_img = enhancer.enhance(1.2)

    elif mode == 'sharp':
        enhancer = ImageEnhance.Contrast(pil_img)
        pil_img = enhancer.enhance(1.8)
        enhancer = ImageEnhance.Sharpness(pil_img)
        pil_img = enhancer.enhance(2.2)
        pil_img = pil_img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))

    return _pil_to_bytes(pil_img)


def get_client():
    global _vision_client
    if _vision_client is None:
        _vision_client = vision.ImageAnnotatorClient()
    return _vision_client


def _extract_text(response):
    """اسحب النص الأكمل من استجابة Cloud Vision."""
    if response.error and response.error.message:
        return ""
    if response.full_text_annotation and response.full_text_annotation.text:
        return response.full_text_annotation.text.strip()
    if response.text_annotations:
        return response.text_annotations[0].description.strip()
    return ""


def _ocr_single_with_fallback(image_bytes):
    """
    OCR لصورة واحدة. نجرب DOCUMENT_TEXT_DETECTION الأول،
    لو فشل أو رجّع فاضي نجرب TEXT_DETECTION.
    """
    client = get_client()
    image = vision.Image(content=image_bytes)

    # محاولة 1: DOCUMENT_TEXT_DETECTION (أفضل للعربي واللوحات)
    try:
        doc_feature = vision.Feature(type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION)
        resp = client.annotate_image(request={'image': image, 'features': [doc_feature]})
        text = _extract_text(resp)
        if text:
            return text
    except Exception:
        pass

    # محاولة 2: TEXT_DETECTION fallback
    try:
        text_feature = vision.Feature(type_=vision.Feature.Type.TEXT_DETECTION)
        resp = client.annotate_image(request={'image': image, 'features': [text_feature]})
        return _extract_text(resp)
    except Exception:
        return ""


def ocr_image(image_path):
    """OCR لصورة واحدة — للاستخدام الـ standalone فقط."""
    pil_img = _open_image(image_path)
    if pil_img is None:
        return ""

    content = _preprocess_for_ocr(pil_img, mode='standard')
    text = _ocr_single_with_fallback(content)

    # retry لو فاضي
    if not text.strip():
        content = _preprocess_for_ocr(pil_img, mode='sharp')
        text = _ocr_single_with_fallback(content)

    return text


def _load_batch_requests(paths, mode='standard', feature_type=None, language_hints=None):
    """تحويل قائمة مسارات لـ AnnotateImageRequest list (مع معالجة مسبقة).

    feature_type الافتراضي DOCUMENT_TEXT_DETECTION (السلوك الحالي لمسار GPS)،
    وlanguage_hints تُمرر كـ ImageContext عند توفرها.
    """
    if feature_type is None:
        feature_type = vision.Feature.Type.DOCUMENT_TEXT_DETECTION
    image_context = None
    if language_hints:
        image_context = vision.ImageContext(language_hints=list(language_hints))

    requests = []
    for p in paths:
        pil_img = _open_image(p)
        if pil_img is None:
            # لو مقدرناش نفتحها، نبعت request فاضي هيتعامل معاه على إنه فاضي
            image = vision.Image(content=b'')
            feature = vision.Feature(type_=feature_type)
            requests.append(vision.AnnotateImageRequest(
                image=image, features=[feature], image_context=image_context,
            ))
            continue
        content = _preprocess_for_ocr(pil_img, mode=mode)
        image = vision.Image(content=content)
        feature = vision.Feature(type_=feature_type)
        requests.append(vision.AnnotateImageRequest(
            image=image, features=[feature], image_context=image_context,
        ))
    return requests


def _run_one_batch(batch_idx, paths, feature_type=None, language_hints=None):
    """
    شغّل دفعة واحدة (≤16 صورة) عن طريق batch_annotate_images.
    يرجع (batch_idx, results_list_in_order) — نفس ترتيب الـ paths.
    لو فشل بعد كل المحاولات، الصور هترجع نص فاضي.
    """
    requests = _load_batch_requests(
        paths, mode='standard',
        feature_type=feature_type, language_hints=language_hints,
    )
    last_err = None

    for attempt in range(BATCH_RETRIES):
        try:
            resp = get_client().batch_annotate_images(requests=requests)
            results = [_extract_text(r) for r in resp.responses]
            return batch_idx, results
        except Exception as e:
            last_err = e
            err_str = str(e)
            transient = any(s in err_str for s in (
                '503', 'Connection', 'timeout', 'WSARecv', 'WSASend', '429',
            ))
            if not transient or attempt == BATCH_RETRIES - 1:
                break
            time.sleep(BATCH_BACKOFF * (attempt + 1))

    # كل المحاولات فشلت
    print(f"  ⚠️ OCR batch {batch_idx} فشل بعد {BATCH_RETRIES} محاولات: "
          f"{type(last_err).__name__}: {str(last_err)[:160]}", file=sys.stderr, flush=True)
    return batch_idx, ["" for _ in paths]


def _retry_empty_results(paths, first_results):
    """
    للصور اللي رجّعت نص فاضي في المرة الأولى، نعيدها بمعالجة 'sharp'.
    """
    retry_indices = [i for i, text in enumerate(first_results) if not text.strip()]
    if not retry_indices:
        return first_results

    retry_paths = [paths[i] for i in retry_indices]
    requests = _load_batch_requests(retry_paths, mode='sharp')

    try:
        resp = get_client().batch_annotate_images(requests=requests)
        retry_texts = [_extract_text(r) for r in resp.responses]
        for idx, text in zip(retry_indices, retry_texts):
            if text.strip():
                first_results[idx] = text
    except Exception as e:
        print(f"  ⚠️ OCR retry للصور الفاضية فشل: {str(e)[:160]}", file=sys.stderr, flush=True)

    return first_results


def batch_ocr(image_paths, log_fn=print, workers=PARALLEL_BATCHES,
              feature_type=None, language_hints=None):
    """
    قراءة مجموعة صور — ترجع قائمة النصوص بنفس ترتيب الصور.

    المعمارية:
      نقسم الصور لمجموعات من 16، ونشغّل `workers` مجموعة في نفس الوقت.
      بعد كل الـ batches، نعيد الصور الفاضية بمعالجة أقوى.
      feature_type/language_hints يختاران نوع الكشف (الافتراضي DOCUMENT).
    """
    n = len(image_paths)
    if n == 0:
        return []

    # قسّم لـ batches
    batches = []
    for start in range(0, n, BATCH_SIZE):
        chunk = image_paths[start:start + BATCH_SIZE]
        batches.append((start, chunk))

    log_fn(f"  OCR (batch API, DOCUMENT_TEXT): {n} صورة × {len(batches)} دفعة × {workers} متوازي")
    tick = progress_ticker(n, log_fn=log_fn, every=1)
    tick(0)

    results = [""] * n
    completed_images = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _run_one_batch, start, paths,
                feature_type=feature_type, language_hints=language_hints,
            ): (start, len(paths))
            for start, paths in batches
        }
        for future in as_completed(futures):
            start, batch_results = future.result()
            for i, text in enumerate(batch_results):
                results[start + i] = text
            completed_images += futures[future][1]
            tick(completed_images)
            log_fn(f"  OCR batch: {completed_images}/{n}")

    # retry للصور الفاضية بمعالجة sharp
    empty_before = sum(1 for t in results if not t.strip())
    if empty_before > 0:
        log_fn(f"  OCR retry للصور الفاضية: {empty_before} صورة")
        results = _retry_empty_results(image_paths, results)
        empty_after = sum(1 for t in results if not t.strip())
        log_fn(f"  OCR retry انتهى: فاضية قبل={empty_before} → بعد={empty_after}")

    return results


def read_signs_text(image_paths, log_fn=print):
    """
    قراءة نص اللافتات كقارئ مستقل بجانب Gemini.

    نستخدم TEXT_DETECTION (المناسب للافتات/النصوص المتناثرة في المشهد) مع
    language hints عربي/إنجليزي، والصور الفارغة تعاد تلقائيًا بوضع
    DOCUMENT_TEXT_DETECTION + معالجة sharp داخل batch_ocr.
    """
    log_fn(f"Reading sign text from {len(image_paths)} images "
           "(TEXT_DETECTION, ar/en hints)...")
    return batch_ocr(
        image_paths,
        log_fn=log_fn,
        feature_type=vision.Feature.Type.TEXT_DETECTION,
        language_hints=OCR_SIGN_LANGUAGE_HINTS,
    )


def read_gps_from_images(gps_image_paths, log_fn=print):
    """قراءة GPS من صور الـ overlay بنفس الـ batch API."""
    log_fn(f"Reading GPS from {len(gps_image_paths)} images (batch API)...")
    texts = batch_ocr(gps_image_paths, log_fn=log_fn)
    return [parse_gps_text(t) for t in texts]
