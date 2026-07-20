"""
Maps the pipeline's stdout STAGE markers to UI stage indices.

The pipeline (pipeline/main.py) emits lines like:
    --- STAGE 1: Raw frame extraction ---
    --- STAGE 2: Reading GPS + speed from raw frames ---
    ...

The frontend has 9 stages (see frontend/src/data/stages.js). The mapping is
not 1:1 because the backend pipeline has 10 "STAGE" labels while the UI has 9
visual rows; STAGE 7 (auto-detect center) does not have its own UI row and
is folded into STAGE 8 (Places).
"""
import re

# pipeline STAGE number -> UI stage index (0-based)
PIPELINE_STAGE_TO_UI = {
    1: 0,   # frame extraction
    2: 1,   # GPS read
    3: 2,   # filter by speed
    4: 3,   # crop signs
    5: 4,   # OCR
    6: 5,   # Gemini
    # 7 is auto-detect center → no UI row
    8: 6,   # Places
    11: 7,  # v5 matching (Google candidates) — folds into "تحديد الحالة"
    13: 7,  # advanced dedupe        ↑
    14: 7,  # Tier 1 status check    ↑
    15: 7,  # additional merges + Tier 2/3 ↑
    17: 7,  # auto-review (Gemini judge) ↑
    16: 8,  # Excel v6 export
    # legacy: STAGE 9/10 in main.py also fall through to final step
    9: 8,
    10: 8,
    12: 8,
}

STAGE_LINE_RE = re.compile(r"---\s*STAGE\s+(\d+):", re.IGNORECASE)


def parse_stage_line(line: str):
    """Return UI stage index for a STAGE marker line, or None."""
    m = STAGE_LINE_RE.search(line)
    if not m:
        return None
    pipeline_stage = int(m.group(1))
    return PIPELINE_STAGE_TO_UI.get(pipeline_stage)


STRUCTURED_PROGRESS_RE = re.compile(
    r"__PROGRESS__\s+current=(\d+)\s+total=(\d+)"
)
LOOSE_PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def parse_progress_hint(line: str):
    """
    Return (current, total) if line carries progress info.

    Prefers the structured `__PROGRESS__ current=X total=Y` format emitted by
    pipeline/progress.py. Falls back to a loose "X/Y" pattern for older logs.
    """
    m = STRUCTURED_PROGRESS_RE.search(line)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = LOOSE_PROGRESS_RE.search(line)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None
