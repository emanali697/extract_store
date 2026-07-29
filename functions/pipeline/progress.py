"""
Structured progress marker emitted by pipeline modules so the FastAPI runner
can build a fine-grained progress bar for each stage in the UI.

Format on stdout (one line):
    __PROGRESS__ current=42 total=224

Backend (backend/stages.py) parses this and forwards it as a stage update.
The marker is harmless when the pipeline runs standalone — it just looks like
extra log noise.
"""
from __future__ import annotations


def emit_progress(current: int, total: int, log_fn=print) -> None:
    """Emit a single structured progress line."""
    try:
        log_fn(f"__PROGRESS__ current={int(current)} total={int(total)}")
    except Exception:
        # never let progress reporting break the pipeline
        pass


def progress_ticker(total: int, log_fn=print, every: int = 1):
    """
    Return a function `tick(current)` that calls emit_progress only when
    `current` crosses an `every`-step boundary, plus at the very end.
    Useful inside tight loops where emitting every iteration would be noisy.
    """
    state = {"last": -1}

    def tick(current: int) -> None:
        if current >= total or current - state["last"] >= every or current == 0:
            emit_progress(current, total, log_fn=log_fn)
            state["last"] = current

    return tick
