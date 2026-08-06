"""Arabic-aware store deduplication with Gemini adjudication for borderline pairs."""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from difflib import SequenceMatcher


STOP_WORDS = {
    "مطعم", "مطاعم", "بوفيه", "كافتيريا", "محل", "محلات", "تموينات",
    "بقالة", "عصيرات", "للتجارة", "للمقاولات", "و", "في", "من", "على",
}


def normalize_arabic(text):
    text = str(text or "").strip().lower()
    text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
    text = text.translate(str.maketrans({
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
        "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي",
    }))
    text = re.sub(r"[^\u0600-\u06ff0-9a-z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def core_words(text):
    return {
        word for word in normalize_arabic(text).split()
        if word not in STOP_WORDS and len(word) >= 2
    }


def parse_frames(value):
    if isinstance(value, list):
        values = value
    else:
        values = re.findall(r"\d+", str(value or ""))
    frames = set()
    for value in values:
        try:
            frames.add(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(frames)


def frame_distance(first, second):
    first_frames = parse_frames(first.get("evidence_frames") or first.get("frame"))
    second_frames = parse_frames(second.get("evidence_frames") or second.get("frame"))
    if not first_frames or not second_frames:
        return None
    if set(first_frames) & set(second_frames):
        return 0
    return min(abs(a - b) for a in first_frames for b in second_frames)


def _coordinates(store):
    try:
        lat = float(store.get("lat"))
        lng = float(store.get("lng"))
        return lat, lng
    except (TypeError, ValueError):
        return None


def gps_distance(first, second):
    a = _coordinates(first)
    b = _coordinates(second)
    if not a or not b:
        return None
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(value))


def _phone_digits(store):
    phones = set()
    for part in re.split(r"[,|/]", str(store.get("phone") or "")):
        digits = re.sub(r"\D", "", part)
        if 7 <= len(digits) <= 15:
            phones.add(digits)
    return phones


def pair_metrics(first, second):
    name1 = normalize_arabic(first.get("name_ar"))
    name2 = normalize_arabic(second.get("name_ar"))
    char_similarity = SequenceMatcher(None, name1, name2).ratio() if name1 and name2 else 0.0
    words1, words2 = core_words(name1), core_words(name2)
    token_similarity = (
        len(words1 & words2) / len(words1 | words2)
        if words1 and words2 else 0.0
    )
    return {
        "char_similarity": char_similarity,
        "token_similarity": token_similarity,
        "frame_gap": frame_distance(first, second),
        "distance_m": gps_distance(first, second),
        "same_phone": bool(_phone_digits(first) & _phone_digits(second)),
    }


def _nearby(metrics):
    frame_gap = metrics["frame_gap"]
    distance_m = metrics["distance_m"]
    return (
        (frame_gap is not None and frame_gap <= 12)
        or (distance_m is not None and distance_m <= 80)
    )


def _strong_duplicate(metrics):
    if not _nearby(metrics):
        return False
    if metrics["same_phone"]:
        return True
    if metrics["char_similarity"] >= 0.9:
        return True
    return (
        metrics["char_similarity"] >= 0.8
        and metrics["token_similarity"] >= 0.5
    )


def _borderline(metrics):
    return _nearby(metrics) and (
        metrics["char_similarity"] >= 0.55
        or metrics["token_similarity"] >= 0.34
    )


PAIR_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "pair_id": {"type": "INTEGER"},
            "same_store": {"type": "BOOLEAN"},
            "confidence": {"type": "NUMBER"},
            "reason": {"type": "STRING"},
        },
        "required": ["pair_id", "same_store", "confidence", "reason"],
    },
}


def _gemini_pair_decisions(pairs, log_fn):
    if not pairs:
        return {}
    try:
        from analyzer import get_client
        from config import GEMINI_MODEL
    except Exception as error:
        log_fn(f"Dedupe Gemini unavailable: {error}")
        return {}

    decisions = {}
    for offset in range(0, len(pairs), 20):
        chunk = pairs[offset:offset + 20]
        payload = []
        for pair_id, _first_index, _second_index, first, second, metrics in chunk:
            payload.append({
                "pair_id": pair_id,
                "first": {
                    "name": first.get("name_ar", ""),
                    "phone": first.get("phone", ""),
                    "visible_text": first.get("raw_visible_text", ""),
                },
                "second": {
                    "name": second.get("name_ar", ""),
                    "phone": second.get("phone", ""),
                    "visible_text": second.get("raw_visible_text", ""),
                },
                "metrics": metrics,
            })
        prompt = (
            "Decide whether each pair is the same physical storefront seen in adjacent dashcam frames. "
            "Be tolerant of one or two Arabic letter-reading differences, hamza/yaa/taa-marbuta variants, "
            "but do not merge neighboring stores or branches merely because their category words match. "
            "Return one decision per pair_id. Data:\n" + json.dumps(payload, ensure_ascii=False)
        )
        try:
            response = get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={
                    "temperature": 0.0,
                    "max_output_tokens": 4096,
                    "response_mime_type": "application/json",
                    "response_schema": PAIR_SCHEMA,
                },
            )
            for item in json.loads(response.text or "[]"):
                decisions[int(item["pair_id"])] = item
        except Exception as error:
            log_fn(f"Dedupe Gemini adjudication failed: {str(error)[:160]}")
        time.sleep(0.2)
    return decisions


def _merge_unique_text(values, separator=" | "):
    output = []
    for value in values:
        for part in str(value or "").split(separator):
            part = part.strip()
            if part and part not in output:
                output.append(part)
    return separator.join(output)


def _merge_group(group):
    def quality(store):
        return (
            float(store.get("confidence", 0) or 0),
            bool(store.get("phone")),
            len(str(store.get("name_ar") or "")),
        )

    best = max(group, key=quality)
    merged = dict(best)
    frames = sorted({
        frame for store in group
        for frame in parse_frames(store.get("evidence_frames") or store.get("frame"))
    })
    phones = []
    for store in group:
        for phone in _phone_digits(store):
            if phone not in phones:
                phones.append(phone)
    evidence_images = []
    for store in group:
        for image in (store.get("visual_evidence") or {}).get("sign_images", []):
            if image not in evidence_images:
                evidence_images.append(image)
    flags = []
    for store in group:
        for flag in store.get("review_flags") or []:
            if flag not in flags:
                flags.append(flag)

    merged["frame"] = ",".join(map(str, frames))
    merged["evidence_frames"] = frames
    merged["phone"] = ", ".join(phones)
    merged["ocr_text"] = _merge_unique_text(store.get("ocr_text") for store in group)
    merged["raw_visible_text"] = merged["ocr_text"]
    merged["review_flags"] = flags
    merged["needs_review"] = bool(flags)
    merged["merged_from"] = len(group)
    merged["original_names"] = [store.get("name_ar", "") for store in group]
    visual = dict(merged.get("visual_evidence") or {})
    visual.update({"verified": True, "frames": frames, "sign_images": evidence_images})
    merged["visual_evidence"] = visual
    if merged.get("multimodal"):
        merged["multimodal"] = dict(merged["multimodal"])
        if evidence_images:
            merged["multimodal"]["sign_image"] = evidence_images[0]
    return merged


def dedupe_stores(stores, log_fn=print):
    count = len(stores)
    parent = list(range(count))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first, second):
        root_a, root_b = find(first), find(second)
        if root_a != root_b:
            parent[root_b] = root_a

    borderline_pairs = []
    pair_id = 0
    for first_index in range(count):
        for second_index in range(first_index + 1, count):
            metrics = pair_metrics(stores[first_index], stores[second_index])
            if _strong_duplicate(metrics):
                union(first_index, second_index)
            elif _borderline(metrics):
                borderline_pairs.append((
                    pair_id,
                    first_index,
                    second_index,
                    stores[first_index],
                    stores[second_index],
                    metrics,
                ))
                pair_id += 1

    decisions = _gemini_pair_decisions(borderline_pairs, log_fn)
    manual_pairs = 0
    for pair in borderline_pairs:
        current_id, first_index, second_index, first, second, _metrics = pair
        decision = decisions.get(current_id)
        if decision and decision.get("same_store") and float(decision.get("confidence", 0) or 0) >= 0.8:
            union(first_index, second_index)
            continue
        if decision and not decision.get("same_store") and float(decision.get("confidence", 0) or 0) >= 0.8:
            continue
        manual_pairs += 1
        reason = (decision or {}).get("reason") or "تشابه أسماء غير محسوم آليًا"
        for store, other in ((first, second), (second, first)):
            possible = list(store.get("possible_duplicates") or [])
            possible.append({"name": other.get("name_ar", ""), "reason": reason})
            store["possible_duplicates"] = possible
            flags = list(store.get("review_flags") or [])
            if "احتمال تكرار يحتاج مراجعة" not in flags:
                flags.append("احتمال تكرار يحتاج مراجعة")
            store["review_flags"] = flags
            store["needs_review"] = True

    groups = {}
    for index, store in enumerate(stores):
        groups.setdefault(find(index), []).append(store)
    merged = [_merge_group(group) for group in groups.values()]
    merged_groups = sum(1 for group in groups.values() if len(group) > 1)
    log_fn(
        f"Dedupe: {len(stores)} -> {len(merged)} stores | "
        f"merged groups={merged_groups} | manual pairs={manual_pairs}"
    )
    return merged
