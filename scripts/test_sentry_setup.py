"""Deterministic privacy and disabled-mode checks for both Python runtimes."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_scrubbed(module) -> None:
    event = {
        "user": {"email": "owner@example.com"},
        "request": {"url": "https://example.test/video.mp4"},
        "extra": {"phone": "+966 55 123 4567"},
        "message": "owner@example.com +966 55 123 4567 Bearer sntrys_SECRET C:\\uploads\\private.mp4",
        "exception": {
            "values": [{
                "value": "owner@example.com called +966 55 123 4567",
                "stacktrace": {"frames": [{"vars": {"token": "secret"}}]},
            }],
        },
        "breadcrumbs": {
            "values": [{
                "message": "owner@example.com +966 55 123 4567",
                "data": {"video": "private.mp4"},
            }],
        },
    }
    scrubbed = module._before_send(event, {})
    serialized = repr(scrubbed)
    for secret in ("owner@example.com", "+966 55 123 4567", "sntrys_SECRET", "private.mp4"):
        assert secret not in serialized, f"sensitive value remained: {secret}"
    for removed in ("request", "extra"):
        assert removed not in scrubbed
    assert scrubbed["user"] == {"ip_address": "0.0.0.0"}


def main() -> None:
    previous_dsn = os.environ.pop("SENTRY_DSN", None)
    try:
        for runtime in ("backend", "functions"):
            module = load_module(
                f"{runtime}_sentry_setup",
                ROOT / runtime / "sentry_setup.py",
            )
            assert module.init_sentry(f"test-{runtime}") is False
            assert_scrubbed(module)
    finally:
        if previous_dsn is not None:
            os.environ["SENTRY_DSN"] = previous_dsn
    print("Sentry disabled-mode and privacy checks passed for backend and functions.")


if __name__ == "__main__":
    main()
