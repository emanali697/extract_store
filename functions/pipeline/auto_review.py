"""
Auto-review for Tier 3 stores.

For each "يحتاج تحقق ميداني" store, run cheap automated checks before
sending it to a human reviewer:

1. **Phone validation** — normalize Arabic digits and validate Saudi formats
   without guessing or repairing any digit.
2. **Gemini-as-judge** — a single batched call asks Gemini to score how
   plausible the extracted name is (0.0 = OCR garbage, 1.0 = clearly a
   real Arabic store name). Cheap because we send up to 20 stores per call.
3. **Decision**
       confidence ≥ 0.85  AND  has a valid phone   →  auto_passed (Tier 2)
       confidence  < 0.30  OR   empty/garbage name →  auto_rejected
       otherwise                                    →  needs_human

The function mutates each Tier-3 store dict to add an `auto_review` block:

    {
        "phones_clean":      ["0541234567", ...],
        "gemini_confidence": 0.82,
        "gemini_reason":     "...",
        "decision":          "auto_passed" | "auto_rejected" | "needs_human",
    }

If `auto_passed`, the store's `status_check` is also rewritten so it shows
up as Tier 2 in the rest of the pipeline.
"""
from __future__ import annotations
import json
import re
import time
from difflib import SequenceMatcher
from typing import Iterable

from pathlib import Path

from progress import emit_progress
from phone_utils import classify_phone


# Thresholds (tune freely)
#
# Two-tier auto-pass policy:
#   STRONG: Gemini ≥ 0.90 alone is enough evidence (name is unambiguously a
#           real Arabic store name on a visually read sign).
#   SOFT:   Gemini ≥ 0.70 + at least one secondary signal — a valid Saudi
#           phone OR a multi-word name. Multi-word names are much less likely
#           to be visual-reading noise than single tokens.
AUTO_PASS_CONF_STRONG = 0.90
AUTO_PASS_CONF_SOFT = 0.70
AUTO_REJECT_CONF = 0.40
GEMINI_BATCH_SIZE = 20
GEMINI_RETRIES = 2

# Multimodal verification settings
MULTIMODAL_ENABLED = True
MULTIMODAL_RETRIES = 4
MULTIMODAL_DELAY = 2.0


# ----------  Phone cleanup  ----------

def _split_phones(raw):
    """A 'phone' field may hold a comma-separated list — split + dedup."""
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,،;]+", str(raw))]
    return [p for p in parts if p]


def clean_store_phones(store, extra_text=""):
    """Return a list of normalized valid phones for one store.
    `extra_text` lets us also scan additional text (e.g. multimodal output)
    for phones present in Gemini's visible-text transcription."""
    raw_phones = _split_phones(store.get("phone"))

    # Also scan extra_text for any Saudi-looking sequence of digits
    if extra_text:
        for m in re.finditer(r"[\d٠-٩]{7,15}", extra_text):
            raw_phones.append(m.group(0))

    arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    pool = [re.sub(r"\D", "", str(p).translate(arabic_digits)) for p in raw_phones]
    pool = [p for p in pool if p]

    clean = []
    seen = set()
    for digits in pool:
        digit_counts = {digit: digits.count(digit) for digit in set(digits)}
        if digit_counts and max(digit_counts.values()) >= len(digits) - 2:
            continue
        ascending = "01234567890123456789"
        descending = "98765432109876543210"
        if any(digits[index:index + 6] in ascending or
               digits[index:index + 6] in descending
               for index in range(max(0, len(digits) - 5))):
            continue
        formatted, _kind = classify_phone(digits)
        if formatted and formatted not in seen:
            seen.add(formatted)
            clean.append(formatted)
    return clean


# ----------  Gemini judge  ----------

def _build_judge_prompt(batch):
    lines = []
    for i, s in enumerate(batch, 1):
        name = (s.get("name_ar") or "").strip()
        cat = (s.get("category") or "").strip()
        phones = s.get("_phones_clean", [])
        origs = s.get("original_names") or []
        orig_str = " | ".join(origs[:3]) if origs else ""
        lines.append(
            f"{i}. name={name!r}  category={cat!r}  "
            f"phones={phones}  raw_variants={orig_str!r}"
        )
    body = "\n".join(lines)

    return f"""You are validating store names read visually by Gemini from dashcam footage on a Saudi street.

For each entry below, decide how plausible it is that the name is a REAL store/business (not visual-reading noise, not a road sign, not random letters).

Score 0.0 to 1.0:
  1.0 → Clearly a plausible Arabic business name (مطعم/بقالة/كافيه/صيدلية...)
  0.5 → Maybe a real name but fragmented or category-only ("بقالة" alone)
  0.0 → Looks like visual-reading noise (random letters, single chars, sign noise)

Bonus if the entry has a valid Saudi phone number — that's strong evidence it's real.

Entries:
{body}

Return ONLY a JSON array, one object per entry:
[
  {{"id": 1, "confidence": 0.85, "reason": "short Arabic reason"}},
  ...
]
NO markdown, NO explanations outside the JSON."""


def _gemini_judge_one_batch(batch, log_fn):
    from analyzer import get_client, parse_gemini_response
    from config import GEMINI_MODEL, GEMINI_TEMPERATURE, GEMINI_MAX_TOKENS

    prompt = _build_judge_prompt(batch)
    client = get_client()

    for attempt in range(GEMINI_RETRIES):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={
                    "temperature": 0.0,
                    "max_output_tokens": GEMINI_MAX_TOKENS,
                },
            )
            parsed = parse_gemini_response(resp.text)
            if isinstance(parsed, list) and len(parsed) == len(batch):
                return parsed
            log_fn(f"  judge batch returned wrong length: got {len(parsed)} need {len(batch)}")
        except json.JSONDecodeError as e:
            log_fn(f"  judge JSON error (attempt {attempt+1}): {e}")
        except Exception as e:
            log_fn(f"  judge error (attempt {attempt+1}): {e}")
        time.sleep(1)

    # Fallback: neutral score, will route to human
    return [{"id": i + 1, "confidence": 0.5, "reason": "judge unavailable"}
            for i in range(len(batch))]


def gemini_judge(stores, log_fn):
    """Batch-judge Tier 3 stores; mutates each with confidence/reason."""
    total = len(stores)
    if total == 0:
        return
    log_fn(f"\nGemini judge: {total} متجر")
    emit_progress(0, total, log_fn=log_fn)
    done = 0

    for start in range(0, total, GEMINI_BATCH_SIZE):
        batch = stores[start:start + GEMINI_BATCH_SIZE]
        verdicts = _gemini_judge_one_batch(batch, log_fn=log_fn)
        for s, v in zip(batch, verdicts):
            s["_judge"] = v
        done += len(batch)
        emit_progress(done, total, log_fn=log_fn)
        log_fn(f"  judge: {done}/{total}")
        time.sleep(0.3)


# ----------  Multimodal (image) verification  ----------

def _parse_frame_field(field_value):
    """'1-5,7' → [1,2,3,4,5,7]"""
    if not field_value:
        return []
    nums = []
    for part in str(field_value).split(","):
        part = part.strip()
        if "-" in part:
            try:
                a, b = part.split("-")
                nums.extend(range(int(a), int(b) + 1))
            except ValueError:
                continue
        else:
            try:
                nums.append(int(part))
            except ValueError:
                continue
    return sorted(set(nums))


def _pick_sign_image(store, signs_dir: Path):
    """Pick the first frame's sign image — most likely to show the front of the sign."""
    frame_nums = _parse_frame_field(store.get("frame", ""))
    for n in frame_nums:
        p = signs_dir / f"sign_{n:04d}.jpg"
        if p.exists():
            return p
    return None


MM_PROMPT = """Verify one candidate storefront using the supplied adjacent dashcam images.
The candidate from the first visual pass is: {target!r}.

Rules:
- visible is true only if this exact candidate storefront/sign is present in the images.
- same_store is true only if the images support that the candidate and exact_name are the same business.
- Each image may contain several neighboring storefronts. Attribute text and phone numbers only to the
  physical sign/facade carrying exact_name; never copy a number from a nearby business.
- exact_name must copy the sign exactly. Do not autocorrect or complete hidden letters.
- If the candidate contains missing/uncertain letters, keep exact_name empty unless every added letter is legible.
- phone must contain only complete digits clearly visible on this storefront. Never guess digits.
- Never emit placeholders such as 0500000000 or 0555555555.
- entity_type must be one of: store, service_business, institution, advertisement, unknown.
- Schools, government buildings, and unrelated advertisements are not stores.
- raw_text must include only text visibly belonging to this candidate.
- Keep raw_text under 250 characters and reason under 160 characters.
- image_clarity is 0..1 for exact name/phone readability, not business-name plausibility.
"""


# Schema we'll pin Gemini to — guarantees parseable JSON.
MM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "visible": {"type": "BOOLEAN"},
        "same_store": {"type": "BOOLEAN"},
        "exact_name": {"type": "STRING"},
        "phone": {"type": "STRING"},
        "category": {"type": "STRING"},
        "raw_text": {"type": "STRING"},
        "image_clarity": {"type": "NUMBER"},
        "entity_type": {"type": "STRING"},
        "reason": {"type": "STRING"},
    },
    "required": [
        "visible", "same_store", "exact_name", "phone", "category",
        "raw_text", "image_clarity", "entity_type", "reason",
    ],
}


def _candidate_sign_images(store, signs_dir: Path):
    names = list((store.get("visual_evidence") or {}).get("sign_images") or [])
    paths = []
    for name in names:
        safe_name = Path(name).name
        if not safe_name.startswith("sign_"):
            continue
        path = signs_dir / safe_name
        if path.is_file() and path not in paths:
            paths.append(path)
    if not paths:
        fallback = _pick_sign_image(store, signs_dir)
        return [fallback] if fallback else []

    # The first visual pass records its strongest frame. Prefer that frame and
    # its nearest neighbors. Evenly spaced frames can cross into the next shop
    # as the dashcam moves, which can assign a neighboring phone to this store.
    primary_name = Path((store.get("multimodal") or {}).get("sign_image") or "").name
    primary = signs_dir / primary_name if primary_name.startswith("sign_") else None
    if primary not in paths:
        primary = paths[0]

    def _frame_number(path):
        match = re.search(r"(\d+)", path.stem)
        return int(match.group(1)) if match else 0

    primary_number = _frame_number(primary)
    ordered = sorted(paths, key=lambda path: (abs(_frame_number(path) - primary_number),
                                               _frame_number(path)))
    return ordered[:3]


def _multimodal_one(store, sign_paths, log_fn):
    """Targeted independent verification using up to three evidence images."""
    from analyzer import _image_bytes, get_client
    from config import GEMINI_MODEL

    try:
        from google.genai import types as _types
    except ImportError:
        return None

    client = get_client()
    target = (
        store.get("name_ar") or store.get("name_en")
        or store.get("raw_visible_text") or store.get("raw_text") or ""
    ).strip()
    parts = [_types.Part.from_text(text=MM_PROMPT.format(target=target))]
    for index, sign_path in enumerate(sign_paths, 1):
        try:
            img_bytes = _image_bytes(str(sign_path))
        except Exception as error:
            log_fn(f"  mm: read failed for {sign_path.name}: {error}")
            continue
        parts.append(_types.Part.from_text(text=f"Evidence image {index}: {sign_path.name}"))
        parts.append(_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
    if len(parts) == 1:
        return None

    cfg = {
        "temperature": 0.0,
        # Larger budget — Arabic raw_text can be long and getting truncated
        # mid-string was the source of every "Unterminated string" parse error.
        "max_output_tokens": 4096,
        "response_mime_type": "application/json",
        "response_schema": MM_SCHEMA,
    }


    # قراءة التحقق المستقل تستحق دقة وسائط عالية (الهاتف/الحروف الصغيرة)،
    # لكن النموذج لا يدعم HIGH إلا لطلبات الصورة الواحدة؛ نفعّلها حينها فقط
    # ونتجاهل الإعداد بصمت على نسخ SDK الأقدم التي لا تعرفه.
    image_parts = (len(parts) - 1) // 2  # أول Part هو البرومبت ثم (نص+صورة) لكل دليل
    if image_parts == 1:
        try:
            cfg["media_resolution"] = _types.MediaResolution.MEDIA_RESOLUTION_HIGH
        except AttributeError:
            pass

    for attempt in range(MULTIMODAL_RETRIES):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[_types.Content(role="user", parts=parts)],
                config=cfg,
            )
            text = (resp.text or "").strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # Last-resort: strip code fences and retry parsing
                cleaned = text.strip().lstrip("`").rstrip("`")
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()
                parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list) and parsed:
                return parsed[0]
        except json.JSONDecodeError as e:
            log_fn(f"  mm json err ({attempt + 1}): {e}")
        except Exception as e:
            err_text = str(e)
            if "INVALID_ARGUMENT" in err_text and "media resolution" in err_text \
                    and cfg.pop("media_resolution", None) is not None:
                log_fn("  mm: media_resolution مرفوضة لهذا الطلب — إعادة بدونها")
                continue
            log_fn(f"  mm err ({attempt + 1}): {err_text[:80]}")
        time.sleep(MULTIMODAL_DELAY * (attempt + 1))
    return None


def multimodal_verify(stores, signs_dir: Path, log_fn=print):
    """Independently verify every candidate and apply strict visual fields."""
    if not MULTIMODAL_ENABLED:
        return

    total = len(stores)
    log_fn(f"\nMultimodal verify on {total} stores")
    emit_progress(0, max(1, total), log_fn=log_fn)
    done = 0
    matched = 0

    for s in stores:
        done += 1
        name = (s.get("name_ar") or s.get("name_en") or "").strip()
        category = (s.get("category") or "").strip().lower()
        institution_markers = (
            "مدرسة", "المدرسة", "جامعة", "كلية",
            "school", "university", "college",
        )
        if category in {"school", "kindergarten", "university", "college"} or any(
            marker in name.lower() for marker in institution_markers
        ):
            s["excluded_from_results"] = True
            s["exclusion_reason"] = "جهة تعليمية وليست متجرًا"
            emit_progress(done, total, log_fn=log_fn)
            continue
        existing = s.get("multimodal") or {}
        if existing.get("verification_pass"):
            matched += 1
            emit_progress(done, total, log_fn=log_fn)
            continue
        sign_paths = _candidate_sign_images(s, signs_dir)
        if not sign_paths:
            raise RuntimeError(
                "Independent visual verification cannot run because no sign "
                f"evidence image exists for '{name or 'unknown'}'."
            )

        result = _multimodal_one(s, sign_paths, log_fn=log_fn)
        if not result:
            raise RuntimeError(
                "Gemini independent visual verification failed for "
                f"'{s.get('name_ar') or s.get('name_en') or 'unknown'}' after "
                f"{MULTIMODAL_RETRIES} attempts. No final results were produced."
            )

        if result:
            from analyzer import sanitize_phone_field

            initial_name = (
                s.get("name_ar") or s.get("name_en")
                or s.get("raw_visible_text") or s.get("raw_text") or ""
            ).strip()
            raw_text = (result.get("raw_text") or "").strip()
            exact_name = (result.get("exact_name") or "").strip()
            clarity = float(result.get("image_clarity", 0) or 0)
            phone = sanitize_phone_field(result.get("phone"), raw_text)
            entity_type = (result.get("entity_type") or "unknown").strip()
            s["multimodal"] = {
                "name": exact_name,
                "phone": phone,
                "category": (result.get("category") or "").strip(),
                "raw_text": raw_text,
                "image_clarity": clarity,
                "sign_image": sign_paths[0].name,
                "verification_pass": True,
                "visible": bool(result.get("visible")),
                "same_store": bool(result.get("same_store")),
                "entity_type": entity_type,
                "reason": (result.get("reason") or "").strip(),
                "initial_name": initial_name,
            }
            visual = dict(s.get("visual_evidence") or {})
            visual["independent_verification"] = s["multimodal"]
            s["visual_evidence"] = visual

            if not result.get("visible") or not result.get("same_store"):
                s["excluded_from_results"] = True
                s["exclusion_reason"] = "لم يتأكد ظهور المتجر في صور الدليل"
            elif entity_type in {"institution", "advertisement"}:
                s["excluded_from_results"] = True
                s["exclusion_reason"] = f"نوع المنشأة غير تجاري: {entity_type}"
            else:
                if exact_name:
                    s["name_ar"] = exact_name
                    if not any("\u0600" <= char <= "\u06ff" for char in exact_name):
                        s["name_en"] = exact_name
                previous_phone = (s.get("phone") or "").strip()
                if previous_phone and previous_phone != phone:
                    s["phone_first_pass"] = previous_phone
                s["phone"] = phone
                s["phone_source"] = "gemini_visual_verified" if phone else "not_visible"
                if s["multimodal"]["category"]:
                    s["category"] = s["multimodal"]["category"]
                s["confidence"] = clarity
                if clarity < 0.85 or not exact_name or entity_type == "unknown":
                    s["needs_review"] = True
                    flags = list(s.get("review_flags") or [])
                    if "التحقق البصري المستقل يحتاج مراجعة" not in flags:
                        flags.append("التحقق البصري المستقل يحتاج مراجعة")
                    s["review_flags"] = flags
                else:
                    matched += 1

        emit_progress(done, total, log_fn=log_fn)
        if done % 5 == 0 or done == total:
            log_fn(f"  mm: {done}/{total} (named: {matched})")
        time.sleep(MULTIMODAL_DELAY)


# ----------  Cross-validation helpers  ----------

def _normalize_for_compare(s):
    """Strip diacritics, normalize hamza/yaa/taa marbuta for fuzzy name comparison."""
    if not s:
        return ""
    s = re.sub(r"[ً-ْٰ]", "", s)
    s = s.replace("ة", "ه").replace("ى", "ي")
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ؤ", "و").replace("ئ", "ي")
    return re.sub(r"\s+", " ", s).strip()


def _names_agree(a, b):
    """Two names 'agree' if their normalized forms share ≥ 50% of words."""
    na, nb = _normalize_for_compare(a), _normalize_for_compare(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    wa, wb = set(na.split()), set(nb.split())
    if not wa or not wb:
        return False
    overlap = len(wa & wb) / max(len(wa | wb), 1)
    char_ratio = SequenceMatcher(None, na, nb).ratio()
    return overlap >= 0.5 or char_ratio >= 0.78


def _name_is_incomplete(name):
    normalized = (name or "").strip().lower()
    markers = ("...", "…", "غير واضح", "unknown", "unclear")
    return not normalized or any(marker in normalized for marker in markers)


# ----------  Field-level verification  ----------

def _normalized_phone_digits(value):
    """أرقام فقط بصيغة محلية (0...) لمقارنة حتمية بين المصادر المستقلة."""
    arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    digits = re.sub(r"\D", "", str(value or "").translate(arabic_digits))
    if digits.startswith("00966"):
        digits = "0" + digits[5:]
    elif digits.startswith("966") and len(digits) >= 11:
        digits = "0" + digits[3:]
    return digits


def compute_phone_sources(store):
    """
    يجمع كل رقم هاتف نُسب للمتجر ومن أي مصدر مستقل جاء:
      gemini_first  — القراءة البصرية الأولى (phone_first_pass أو phone الحالي)
      gemini_verify — التحقق البصري المستقل (multimodal.phone)
      ocr_votes     — تصويت Cloud Vision عبر ≥2 فريم (phones_all)
      places        — هاتف مرشح Google Places المطابق
    يرجع {normalized_phone: {source, ...}}.
    """
    sources = {}

    def _add(value, source):
        digits = _normalized_phone_digits(value)
        if len(digits) < 7:
            return
        sources.setdefault(digits, set()).add(source)

    mm = store.get("multimodal") or {}
    first_pass = (store.get("phone_first_pass") or "").strip()
    if first_pass:
        _add(first_pass, "gemini_first")
    elif store.get("phone_source") == "gemini_visual":
        _add(store.get("phone"), "gemini_first")
    _add(mm.get("phone"), "gemini_verify")
    for entry in store.get("phones_all") or []:
        try:
            votes = int(entry.get("votes") or 0)
        except (TypeError, ValueError, AttributeError):
            votes = 0
        if votes >= 2:
            _add(entry.get("phone"), "ocr_votes")
    candidate = (store.get("v5") or {}).get("candidate") or {}
    _add(candidate.get("phone"), "places")
    return sources


def compute_field_verification(store):
    """
    بوابة تحقق لكل حقل على حدة (لا ترفض المتجر كله بسبب حقل واحد):
      name     — اتفاق القراءة الأولى مع التحقق المستقل أو مطابقة v5 مؤكدة.
      phone    — None لو لا هاتف أصلًا؛ True لو كل رقم معروض جاء من مصدرين
                 مستقلين متفقين على كل الأرقام؛ False لو مصدر واحد أو اختلاف.
      location — مرشح Google Places أو median GPS من عينتين فأكثر.
    """
    mm = store.get("multimodal") or {}
    mm_name = (mm.get("name") or "").strip()
    initial_name = (mm.get("initial_name") or store.get("name_ar") or "").strip()
    name_verified = bool(mm_name and _names_agree(initial_name, mm_name))
    v5_status = (store.get("v5") or {}).get("status")
    if v5_status in ("confirmed_high", "confirmed_medium"):
        name_verified = True

    sources = compute_phone_sources(store)
    verified_phones = {phone for phone, src in sources.items() if len(src) >= 2}
    phones = store.get("_phones_clean")
    if phones is None:
        phones = [
            digits for digits in
            (_normalized_phone_digits(part) for part in _split_phones(store.get("phone")))
            if len(digits) >= 7
        ]
    if phones:
        phone_verified = all(
            _normalized_phone_digits(phone) in verified_phones for phone in phones
        )
    else:
        phone_verified = None

    location_verified = (
        v5_status in ("confirmed_high", "confirmed_medium")
        or store.get("location_source") == "google_places"
    )
    if not location_verified and store.get("location_source") in (None, "dashcam_frame"):
        try:
            location_verified = int(store.get("gps_samples") or 0) >= 2
        except (TypeError, ValueError):
            location_verified = False

    return {
        "name": name_verified,
        "phone": phone_verified,
        "location": location_verified,
        "phone_sources": {
            phone: sorted(src) for phone, src in sorted(sources.items())
        },
    }


# ----------  Final decision  ----------

def _decide_name_path(store):
    judge = store.get("_judge") or {}
    conf = float(judge.get("confidence", 0.5) or 0.5)
    reason = judge.get("reason", "")
    phones = store.get("_phones_clean", [])
    name = (store.get("name_ar") or "").strip()
    mm = store.get("multimodal") or {}
    mm_name = (mm.get("name") or "").strip()
    initial_name = (mm.get("initial_name") or name).strip()

    if store.get("excluded_from_results"):
        return "auto_rejected", 0.0, store.get("exclusion_reason") or "مستبعد بصريًا", phones

    if not name and not mm_name:
        return "auto_rejected", conf, "اسم فاضي حتى في الصورة", phones

    multi_word = len(name.split()) >= 2
    mm_agrees = bool(mm_name and _names_agree(initial_name, mm_name))

    if mm.get("verification_pass"):
        visual_conf = float(mm.get("image_clarity", 0) or 0)
        if not mm.get("visible") or not mm.get("same_store"):
            return "auto_rejected", 0.0, "لم يتأكد ظهور المتجر في صور الدليل", phones
        initial_words = _normalize_for_compare(initial_name).split()
        mixed_scripts = (
            bool(re.search(r"[\u0600-\u06ff]", mm_name or initial_name))
            and bool(re.search(r"[A-Za-z]", mm_name or initial_name))
        )
        weak_single_word = (
            len(initial_words) == 1
            and len(initial_words[0]) <= 5
            and not phones
        )
        if mixed_scripts:
            return "needs_human", min(visual_conf, conf), \
                "الاسم يجمع حروفًا عربية ولاتينية وقد يحتوي حروفًا متشابهة؛ يحتاج مراجعة بشرية", phones
        if _name_is_incomplete(initial_name) or weak_single_word:
            return "needs_human", min(visual_conf, conf), \
                "القراءة الأولى ناقصة أو اسم عام قصير ويحتاج تأكيدًا بشريًا", phones
        if visual_conf >= 0.90 and conf >= 0.85 and mm_agrees:
            final_conf = min(visual_conf, conf)
            return "auto_passed", final_conf, \
                f"قراءتان بصريتان متفقتان على '{mm_name}'", phones
        return "needs_human", min(visual_conf, conf), \
            mm.get("reason") or "الاسم أو الهاتف يحتاج مراجعة بشرية", phones

    # === STRONGEST: multimodal independently confirms the same name ===
    if mm_agrees:
        return "auto_passed", max(conf, 0.95), \
            f"تأكيد بصري: Gemini شاف '{mm_name}' في الصورة", phones

    # === STRONG: very high text confidence alone ===
    if conf >= AUTO_PASS_CONF_STRONG:
        return "auto_passed", conf, \
            reason or f"ثقة عالية جداً ({conf:.2f}) — اسم متجر واضح", phones

    # === SOFT: good confidence + secondary signal ===
    if conf >= AUTO_PASS_CONF_SOFT and (phones or multi_word):
        signals = []
        if phones:
            signals.append(f"رقم سعودي ({len(phones)})")
        if multi_word:
            signals.append("اسم متعدد الكلمات")
        return "auto_passed", conf, \
            reason or f"ثقة {conf:.2f} + " + " + ".join(signals), phones

    # === Multimodal-only: text was uncertain but image clearly shows a name ===
    if mm_name and mm.get("image_clarity", 0) >= 0.7:
        return "auto_passed", 0.80, \
            f"الاسم النصي غير واضح، لكن Gemini شاف '{mm_name}' بوضوح في الصورة", phones

    if conf < AUTO_REJECT_CONF and not mm_name:
        return "auto_rejected", conf, reason or "ثقة منخفضة + لا اسم مرئي", phones

    return "needs_human", conf, reason or "ثقة متوسطة — مراجعة بشرية", phones


def _decide(store):
    """قرار المتجر: مسار الاسم الحالي + بوابة تحقق الهاتف المستقلة.

    رقم هاتف موجود من مصدر واحد فقط (أو بمصادر متعارضة) يمنع auto_passed
    ويحوّل المتجر للمراجعة البشرية لتأكيد الرقم؛ غياب الهاتف لا يمنع القبول.
    """
    decision, conf, reason, phones = _decide_name_path(store)
    if decision != "auto_passed":
        return decision, conf, reason, phones
    verification = compute_field_verification(store)
    if verification["phone"] is False:
        return (
            "needs_human",
            min(float(conf or 0), 0.84),
            "الهاتف مقروء من مصدر واحد فقط أو يختلف بين المصادر؛ يحتاج تأكيدًا بشريًا",
            phones,
        )
    return decision, conf, reason, phones


# ----------  Main entry  ----------

def auto_review(stores, log_fn=print, signs_dir=None):
    """
    Multi-pass automated review:
      1) Phone cleanup (Saudi normalization + OCR repair)
      2) Multimodal Gemini on the sign image — independent name/phone extraction
      3) Gemini text-judge — scores plausibility of the original name
      4) Regex phone extraction from multimodal raw_text
      5) Cross-validation → auto_passed / auto_rejected / needs_human

    Mutates each Tier-3 store; promoted stores get a new Tier-2 status_check.
    `signs_dir` is the folder containing sign_NNNN.jpg files; if None, the
    multimodal pass is skipped.
    """
    tier3 = [
        s for s in stores
        if (s.get("status_check") or {}).get("tier") == 3
        and not s.get("excluded_from_results")
    ]
    if not tier3:
        log_fn("auto_review: لا توجد متاجر Tier 3")
        return stores

    log_fn(f"auto_review: بدء على {len(tier3)} متجر Tier 3")

    # --- 1) Phone cleanup ---
    log_fn("  1) تنظيف أرقام الهاتف")
    for s in tier3:
        s["_phones_clean"] = clean_store_phones(s)

    # --- 2) Multimodal Gemini on sign images ---
    if signs_dir and MULTIMODAL_ENABLED:
        signs_path = Path(signs_dir)
        if signs_path.exists():
            log_fn("  2) Multimodal Gemini على صور اللوحات")
            multimodal_verify(tier3, signs_path, log_fn=log_fn)
        else:
            log_fn(f"  2) skip multimodal — لم يُعثر على {signs_path}")

    # --- 3) Gemini text judge ---
    log_fn("  3) Gemini judge النصي")
    gemini_judge(tier3, log_fn=log_fn)

    # --- 4) Re-scan phones using multimodal raw_text ---
    log_fn("  4) إعادة استخراج الأرقام من النص المرئي")
    for s in tier3:
        mm = s.get("multimodal") or {}
        extra = " ".join([mm.get("raw_text", ""), mm.get("phone", "")])
        s["_phones_clean"] = clean_store_phones(s, extra_text=extra)

    # --- 5) Decide + apply ---
    counts = {"auto_passed": 0, "auto_rejected": 0, "needs_human": 0}
    for s in tier3:
        decision, conf, reason, phones = _decide(s)
        if s.get("possible_duplicates"):
            decision = "needs_human"
            conf = min(float(conf or 0), 0.79)
            duplicate_names = ", ".join(
                item.get("name", "") for item in s["possible_duplicates"]
                if item.get("name")
            )
            reason = f"احتمال تكرار غير محسوم مع: {duplicate_names}"
        counts[decision] += 1

        verification = compute_field_verification(s)
        s["name_verified"] = verification["name"]
        s["phone_verified"] = verification["phone"]
        s["location_verified"] = verification["location"]

        mm = s.get("multimodal") or {}
        s["auto_review"] = {
            "phones_clean": phones,
            "gemini_confidence": round(conf, 2),
            "gemini_reason": reason,
            "decision": decision,
            "multimodal_name": mm.get("name", ""),
            "multimodal_raw": mm.get("raw_text", ""),
            "multimodal_clarity": mm.get("image_clarity"),
            "sign_image": mm.get("sign_image"),
            "field_verification": verification,
        }
        if decision == "auto_passed":
            # Prefer the multimodal name when it's clearer than the OCR one
            if mm.get("name") and len(mm["name"]) >= len((s.get("name_ar") or "")):
                s["name_ar"] = mm["name"]
            # Prefer the multimodal phone when text had none
            if phones and not (s.get("phone") or "").strip():
                s["phone"] = ", ".join(phones)
            s["status_check"] = {
                "tier": 2,
                "status": "نشط",
                "source": "مراجعة AI آلية",
                "evidence": reason,
            }
        # cleanup internals
        s.pop("_judge", None)
        s.pop("_phones_clean", None)

    log_fn(
        f"auto_review summary: "
        f"auto_passed={counts['auto_passed']} | "
        f"auto_rejected={counts['auto_rejected']} | "
        f"needs_human={counts['needs_human']}"
    )
    return stores
