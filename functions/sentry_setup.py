"""Privacy-conscious Sentry initialization for Firebase Functions."""

from __future__ import annotations

import os
import re
from typing import Any

import sentry_sdk


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
_TOKEN_RE = re.compile(r"\b(?:Bearer\s+)?(?:sntrys_|gho_|AIza)[A-Za-z0-9._-]+\b", re.IGNORECASE)
_VIDEO_PATH_RE = re.compile(
    r"(?:[A-Z]:[\\/]|/)[^\s\"'<>]*\.(?:mp4|mov|avi|mkv|webm)",
    re.IGNORECASE,
)


def _redact_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    value = _EMAIL_RE.sub("[email]", value)
    value = _PHONE_RE.sub("[phone]", value)
    value = _TOKEN_RE.sub("[token]", value)
    return _VIDEO_PATH_RE.sub("[video_path]", value)


def _before_send(event: dict, _hint: dict) -> dict:
    """Remove request/user payloads and redact sensitive exception text."""
    for key in ("request", "server_name", "extra"):
        event.pop(key, None)
    event["user"] = {"ip_address": "0.0.0.0"}
    if event.get("message"):
        event["message"] = _redact_text(event["message"])
    for value in event.get("exception", {}).get("values", []):
        value["value"] = _redact_text(value.get("value"))
        for frame in value.get("stacktrace", {}).get("frames", []):
            frame.pop("vars", None)
    for breadcrumb in event.get("breadcrumbs", {}).get("values", []):
        breadcrumb["message"] = _redact_text(breadcrumb.get("message"))
        breadcrumb.pop("data", None)
    return event


def _sample_rate(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if 0 <= value <= 1 else default


def init_sentry(runtime: str) -> bool:
    """Initialize Sentry when SENTRY_DSN is configured; otherwise do nothing."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        release=os.environ.get("SENTRY_RELEASE") or None,
        traces_sample_rate=_sample_rate("SENTRY_TRACES_SAMPLE_RATE", 0.1),
        send_default_pii=False,
        include_local_variables=False,
        before_send=_before_send,
    )
    sentry_sdk.set_tag("app_runtime", runtime)
    return True


def capture_pipeline_failure(stage: str, job_id: str, exit_code: int) -> None:
    """Report a terminal pipeline failure without video or result data."""
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("app_runtime", "firebase-functions")
        scope.set_tag("pipeline_stage", stage)
        scope.set_context("job", {"job_id": job_id, "exit_code": exit_code})
        scope.fingerprint = ["pipeline-failure", "firebase-functions", stage]
        sentry_sdk.capture_message(f"Pipeline stage {stage} failed", level="error")


def capture_unexpected_exception(exc: BaseException, operation: str, job_id: str) -> None:
    """Report an unexpected cloud job exception with minimal safe context."""
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("app_runtime", "firebase-functions")
        scope.set_tag("operation", operation)
        scope.set_context("job", {"job_id": job_id})
        sentry_sdk.capture_exception(exc)
