"""Gemini multimodal storefront reader and structured-data extractor."""
from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter
from google import genai
from google.genai import types

from config import (
    FLAG_EMPTY_CATEGORY,
    FLAG_GHOST_CATEGORIES,
    FLAG_MIN_NAME_LENGTH,
    FLAG_NO_ARABIC,
    GCP_LOCATION,
    GCP_PROJECT_ID,
    GEMINI_BATCH_SIZE,
    GEMINI_DELAY,
    GEMINI_MAX_TOKENS,
    GEMINI_MODEL,
    GEMINI_RETRY_COUNT,
    GEMINI_TEMPERATURE,
)
from progress import emit_progress

_gemini_client = None


class GeminiPermissionError(RuntimeError):
    """The pipeline identity cannot call Vertex AI prediction."""


class GeminiBatchError(RuntimeError):
    """A visual batch could not be read after all retry attempts."""


def get_client():
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(
            vertexai=True,
            project=GCP_PROJECT_ID,
            location=GCP_LOCATION,
        )
    return _gemini_client


VISUAL_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "name_ar": {"type": "STRING"},
            "name_en": {"type": "STRING"},
            "category": {"type": "STRING"},
            "phone": {"type": "STRING"},
            "status": {"type": "STRING"},
            "evidence_frames": {
                "type": "ARRAY",
                "items": {"type": "INTEGER"},
            },
            "raw_visible_text": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
            "notes": {"type": "STRING"},
        },
        "required": [
            "name_ar",
            "name_en",
            "category",
            "phone",
            "status",
            "evidence_frames",
            "raw_visible_text",
            "confidence",
            "notes",
        ],
    },
}


VISUAL_PROMPT = """You are reading storefront signs from consecutive Saudi dashcam frames.
The text label before each image gives its exact frame number and timestamp.

Return only stores whose storefront or sign is actually visible in one or more supplied images.
Never invent a store from general knowledge, GPS, Google Maps, or nearby businesses.
Never output vehicle advertisements, road signs, billboards, or brand text unrelated to a storefront.

For every visible store:
- Transcribe the Arabic name exactly as the sign shows it; do not translate, autocorrect, or complete missing letters.
- Transcribe a phone only when its digits are visibly readable. Never guess a missing digit.
- Use several adjacent images as supporting evidence when they show the same storefront.
- Put all supporting frame numbers in evidence_frames.
- raw_visible_text must contain only text actually visible on the sign.
- confidence is 0..1 for the accuracy of name and phone transcription.
- If two images conflict, preserve the safest visible reading, lower confidence, and explain the conflict in notes.
- If no useful store name is readable, omit that store. If no storefront is visible, return [].
"""


def _image_bytes(path: str) -> bytes:
    """Prepare a sharp, bounded JPEG for fast multimodal requests."""
    with Image.open(path) as image:
        image = image.convert("RGB")
        max_width = 1800
        if image.width > max_width:
            height = max(1, round(image.height * max_width / image.width))
            image = image.resize((max_width, height), Image.Resampling.LANCZOS)
        image = ImageEnhance.Contrast(image).enhance(1.15)
        image = image.filter(ImageFilter.UnsharpMask(radius=1.5, percent=80, threshold=3))
        output = io.BytesIO()
        image.save(output, "JPEG", quality=88, optimize=True)
        return output.getvalue()


def _build_contents(batch_items):
    parts = [types.Part.from_text(text=VISUAL_PROMPT)]
    for item in batch_items:
        parts.append(types.Part.from_text(
            text=(
                f"Frame {item['frame_num']} at {item['timestamp']:.1f}s. "
                "The next image is evidence from this frame."
            )
        ))
        parts.append(types.Part.from_bytes(
            data=_image_bytes(item["sign_path"]),
            mime_type="image/jpeg",
        ))
    return [types.Content(role="user", parts=parts)]


def _parse_response(text: str):
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, list):
        raise ValueError("Gemini visual response must be a JSON array")
    return parsed


def parse_gemini_response(text: str):
    """Compatibility parser used by the later text-only review stage."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    return json.loads(match.group(0) if match else cleaned)


def analyze_batch(batch_items, log_fn=print):
    """Read one group of consecutive sign images with Gemini Vision."""
    contents = _build_contents(batch_items)
    last_error = None
    for attempt in range(GEMINI_RETRY_COUNT):
        try:
            response = get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config={
                    "temperature": GEMINI_TEMPERATURE,
                    "max_output_tokens": GEMINI_MAX_TOKENS,
                    "response_mime_type": "application/json",
                    "response_schema": VISUAL_SCHEMA,
                },
            )
            return _parse_response(response.text)
        except Exception as error:
            last_error = error
            log_fn(
                f"  Gemini visual error (attempt {attempt + 1}/{GEMINI_RETRY_COUNT}): "
                f"{str(error)[:180]}"
            )
            if attempt < GEMINI_RETRY_COUNT - 1:
                time.sleep(2 * (attempt + 1))

    error_text = str(last_error or "unknown Gemini error")
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
    raise GeminiBatchError(
        "Gemini could not read a storefront image batch after all retries; "
        "the job was stopped so incomplete results are not shown as complete."
    ) from last_error


def flag_uncertainty(store):
    flags = []
    name = (store.get("name_ar") or "").strip()
    category = (store.get("category") or "").strip()
    confidence = float(store.get("confidence", 0) or 0)
    if len(name) < FLAG_MIN_NAME_LENGTH:
        flags.append("اسم المتجر قصير أو غير واضح")
    if not name:
        flags.append("اسم المتجر غير مقروء")
    if FLAG_EMPTY_CATEGORY and category in FLAG_GHOST_CATEGORIES:
        flags.append("التصنيف غير واضح")
    if FLAG_NO_ARABIC and name and not any("\u0600" <= c <= "\u06ff" for c in name):
        flags.append("الاسم العربي غير ظاهر")
    if confidence < 0.8:
        flags.append("قراءة Gemini تحتاج مراجعة")
    if not (store.get("phone") or "").strip():
        flags.append("رقم الهاتف غير ظاهر بوضوح")
    return flags


def _frame_numbers(value):
    if isinstance(value, list):
        values = value
    else:
        values = re.findall(r"\d+", str(value or ""))
    out = []
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number not in out:
            out.append(number)
    return out


def run_analysis(processed_frames, _legacy_ocr_texts, gps_data, log_fn=print):
    """Read signs directly from images, attach evidence, then deduplicate."""
    items = []
    for index, frame in enumerate(processed_frames):
        sign_path = frame.get("sign_path")
        if not sign_path or not Path(sign_path).is_file():
            continue
        items.append({
            "frame_num": int(frame.get("final_idx", index + 1)),
            "timestamp": float(frame.get("timestamp", 0) or 0),
            "sign_path": sign_path,
            "lat": gps_data[index].get("lat") if index < len(gps_data) else None,
            "lng": gps_data[index].get("lng") if index < len(gps_data) else None,
            "speed": gps_data[index].get("speed") if index < len(gps_data) else None,
        })

    if not items:
        raise RuntimeError("No processed sign images were available for Gemini visual reading")

    item_by_frame = {item["frame_num"]: item for item in items}
    all_stores = []
    total_batches = (len(items) + GEMINI_BATCH_SIZE - 1) // GEMINI_BATCH_SIZE
    emit_progress(0, total_batches, log_fn=log_fn)

    for offset in range(0, len(items), GEMINI_BATCH_SIZE):
        batch = items[offset:offset + GEMINI_BATCH_SIZE]
        batch_num = offset // GEMINI_BATCH_SIZE + 1
        emit_progress(batch_num, total_batches, log_fn=log_fn)
        frames = [item["frame_num"] for item in batch]
        log_fn(
            f"Gemini visual batch {batch_num}/{total_batches} | "
            f"frames {frames[0]}-{frames[-1]} | stores so far: {len(all_stores)}"
        )
        stores = analyze_batch(batch, log_fn=log_fn)
        allowed_frames = set(frames)
        for store in stores:
            evidence_frames = [
                frame for frame in _frame_numbers(store.get("evidence_frames"))
                if frame in allowed_frames
            ]
            if not evidence_frames:
                log_fn("  Skipped a Gemini result without valid visual evidence")
                continue
            evidence = [item_by_frame[frame] for frame in evidence_frames]
            best = evidence[0]
            store["evidence_frames"] = evidence_frames
            store["frame"] = ",".join(str(frame) for frame in evidence_frames)
            store["lat"] = best.get("lat")
            store["lng"] = best.get("lng")
            store["ocr_text"] = (store.get("raw_visible_text") or "").strip()
            store["raw_text"] = store["ocr_text"]
            store["visual_evidence"] = {
                "verified": True,
                "frames": evidence_frames,
                "sign_images": [Path(item["sign_path"]).name for item in evidence],
                "reader": GEMINI_MODEL,
            }
            store["multimodal"] = {
                "name": (store.get("name_ar") or "").strip(),
                "phone": (store.get("phone") or "").strip(),
                "category": (store.get("category") or "").strip(),
                "raw_text": store["ocr_text"],
                "image_clarity": float(store.get("confidence", 0) or 0),
                "sign_image": Path(best["sign_path"]).name,
            }
            store["source_visible_in_video"] = True
            store["name_source"] = "gemini_visual"
            store["phone_source"] = "gemini_visual" if store.get("phone") else "not_visible"
            all_stores.append(store)
        time.sleep(GEMINI_DELAY)

    from dedupe import dedupe_stores

    log_fn(f"Gemini visual stores before dedupe: {len(all_stores)}")
    unique = dedupe_stores(all_stores, log_fn=log_fn)
    for store in unique:
        flags = list(store.get("review_flags") or [])
        for flag in flag_uncertainty(store):
            if flag not in flags:
                flags.append(flag)
        store["review_flags"] = flags
        store["needs_review"] = bool(flags)
    log_fn(f"Gemini visual stores after dedupe: {len(unique)}")
    return unique


def deduplicate_stores(stores):
    """Compatibility wrapper for older callers."""
    from dedupe import dedupe_stores
    return dedupe_stores(stores)
