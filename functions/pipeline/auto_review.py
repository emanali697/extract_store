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
MULTIMODAL_RETRIES = 2
MULTIMODAL_DELAY = 0.3


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


MM_PROMPT = """دي صورة لافتة محل في شارع سعودي مأخوذة من كاميرا داش كام.

استخرج المعلومات الواضحة في الصورة فقط:
- name: اسم المحل بالعربي (لو ظاهر، وإلا "")
- phone: رقم الهاتف (10 أرقام تبدأ بـ 05 للجوال، أو "")
- category: التصنيف (مطعم/بقالة/صيدلية/مغسلة/إلخ، أو "")
- raw_text: النص الكامل اللي تشوفه على اللافتة كله سواء واضح أو لأ
- image_clarity: عدد بين 0.0 و 1.0

أرجع كائن JSON واحد فقط، بدون أي شرح أو markdown."""


# Schema we'll pin Gemini to — guarantees parseable JSON.
MM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "name": {"type": "STRING"},
        "phone": {"type": "STRING"},
        "category": {"type": "STRING"},
        "raw_text": {"type": "STRING"},
        "image_clarity": {"type": "NUMBER"},
    },
    "required": ["name", "phone", "category", "raw_text", "image_clarity"],
}


def _multimodal_one(sign_path: Path, log_fn):
    """Single multimodal call for one sign image. Uses JSON response mode."""
    from analyzer import get_client
    from config import GEMINI_MODEL

    try:
        from google.genai import types as _types
    except ImportError:
        return None

    try:
        # نفس حل الـ OCR: نصغّر اللوحات الضخمة (8K ≈ 12MB) قبل ما نبعتها لـ Gemini.
        # من غير كده كل صورة بتاخد ~80 ثانية بدل ~5.
        from ocr import _read_content_downscaled
        img_bytes = _read_content_downscaled(str(sign_path))
    except Exception as e:
        try:
            img_bytes = sign_path.read_bytes()
        except Exception as e2:
            log_fn(f"  mm: read failed for {sign_path.name}: {e2}")
            return None

    client = get_client()
    image_part = _types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")

    cfg = {
        "temperature": 0.0,
        # Larger budget — Arabic raw_text can be long and getting truncated
        # mid-string was the source of every "Unterminated string" parse error.
        "max_output_tokens": 2048,
        "response_mime_type": "application/json",
        "response_schema": MM_SCHEMA,
    }

    for attempt in range(MULTIMODAL_RETRIES):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[image_part, MM_PROMPT],
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
            log_fn(f"  mm err ({attempt + 1}): {str(e)[:80]}")
        time.sleep(MULTIMODAL_DELAY * (attempt + 1))
    return None


def multimodal_verify(stores, signs_dir: Path, log_fn=print):
    """Run multimodal Gemini for each store with a sign image; attach to store."""
    if not MULTIMODAL_ENABLED:
        return

    total = len(stores)
    log_fn(f"\nMultimodal verify on {total} stores")
    emit_progress(0, max(1, total), log_fn=log_fn)
    done = 0
    matched = 0

    for s in stores:
        done += 1
        # v3 now reads every storefront directly with Gemini and preserves the
        # exact visual result. Do not pay for (or risk conflicting with) a
        # second read of the same sign during Tier-3 review.
        existing = s.get("multimodal") or {}
        if existing.get("name") and existing.get("sign_image"):
            matched += 1
            emit_progress(done, total, log_fn=log_fn)
            continue
        sign_path = _pick_sign_image(s, signs_dir)
        if not sign_path:
            emit_progress(done, total, log_fn=log_fn)
            continue

        result = _multimodal_one(sign_path, log_fn=log_fn)
        if result:
            s["multimodal"] = {
                "name": (result.get("name") or "").strip(),
                "phone": (result.get("phone") or "").strip(),
                "category": (result.get("category") or "").strip(),
                "raw_text": (result.get("raw_text") or "").strip(),
                "image_clarity": float(result.get("image_clarity", 0.5) or 0.5),
                "sign_image": sign_path.name,
            }
            if s["multimodal"]["name"]:
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
    return overlap >= 0.5


# ----------  Final decision  ----------

def _decide(store):
    judge = store.get("_judge") or {}
    conf = float(judge.get("confidence", 0.5) or 0.5)
    reason = judge.get("reason", "")
    phones = store.get("_phones_clean", [])
    name = (store.get("name_ar") or "").strip()
    mm = store.get("multimodal") or {}
    mm_name = (mm.get("name") or "").strip()
    mm_phone = (mm.get("phone") or "").strip()

    if not name and not mm_name:
        return "auto_rejected", conf, "اسم فاضي حتى في الصورة", phones

    multi_word = len(name.split()) >= 2
    mm_agrees = mm_name and _names_agree(name, mm_name)

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
    tier3 = [s for s in stores if (s.get("status_check") or {}).get("tier") == 3]
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
