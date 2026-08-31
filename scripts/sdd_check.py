#!/usr/bin/env python3
"""Validate the repository's SDD task contract without third-party packages."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = ROOT / ".tasks"
TASK_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STATUS_RE = re.compile(r"^Status:\s*(.+?)\s*$", re.MULTILINE)
PLACEHOLDER_RE = re.compile(r"<(?:Task Name|Owner|task-name|Feature \| Bug \| Refactor \| Infrastructure)>")

SPEC_HEADINGS = (
    "Context",
    "Current Behavior",
    "Requirements",
    "Constraints",
    "Acceptance Criteria",
    "Edge Cases",
    "Out of Scope",
)
PLAN_HEADINGS = (
    "Approach",
    "Impact Analysis",
    "Steps",
    "Files to Change",
    "Tests",
    "Rollback Plan",
    "Risks",
)
CHECK_HEADINGS = (
    "Scope Verified",
    "Automated Checks",
    "Manual Checks",
    "Acceptance Criteria",
    "Residual Risks",
    "Verdict",
)
SPEC_STATUSES = {"Draft", "Approved", "Complete"}
PLAN_STATUSES = {"Draft", "Approved", "Complete"}
CHECK_STATUSES = {"Pending", "Passed", "Failed"}


def read_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: cannot read UTF-8 text ({exc})")
        return ""


def get_status(path: Path, text: str, allowed: set[str], errors: list[str]) -> str:
    match = STATUS_RE.search(text)
    if not match:
        errors.append(f"{path.relative_to(ROOT)}: missing 'Status:' field")
        return ""
    status = match.group(1).strip()
    if status not in allowed:
        choices = ", ".join(sorted(allowed))
        errors.append(f"{path.relative_to(ROOT)}: invalid status '{status}' (use {choices})")
    return status


def require_headings(path: Path, text: str, headings: tuple[str, ...], errors: list[str]) -> None:
    for heading in headings:
        if not re.search(rf"^##\s+{re.escape(heading)}\s*$", text, re.MULTILINE):
            errors.append(f"{path.relative_to(ROOT)}: missing heading '## {heading}'")


def reject_placeholders(path: Path, text: str, errors: list[str]) -> None:
    if PLACEHOLDER_RE.search(text):
        errors.append(f"{path.relative_to(ROOT)}: unresolved template placeholder")


def validate_task(task_dir: Path) -> list[str]:
    errors: list[str] = []
    if not TASK_NAME_RE.fullmatch(task_dir.name):
        errors.append(f"{task_dir.relative_to(ROOT)}: task folder must use kebab-case")

    spec_path = task_dir / "spec.md"
    plan_path = task_dir / "plan.md"
    for required in (spec_path, plan_path):
        if not required.is_file():
            errors.append(f"{required.relative_to(ROOT)}: required file is missing")
    if errors:
        return errors

    spec_text = read_text(spec_path, errors)
    plan_text = read_text(plan_path, errors)
    spec_status = get_status(spec_path, spec_text, SPEC_STATUSES, errors)
    plan_status = get_status(plan_path, plan_text, PLAN_STATUSES, errors)
    require_headings(spec_path, spec_text, SPEC_HEADINGS, errors)
    require_headings(plan_path, plan_text, PLAN_HEADINGS, errors)
    reject_placeholders(spec_path, spec_text, errors)
    reject_placeholders(plan_path, plan_text, errors)

    expected_spec = f".tasks/{task_dir.name}/spec.md"
    if expected_spec not in plan_text:
        errors.append(f"{plan_path.relative_to(ROOT)}: must link Spec: `{expected_spec}`")

    if plan_status in {"Approved", "Complete"} and spec_status == "Draft":
        errors.append(f"{plan_path.relative_to(ROOT)}: plan cannot be {plan_status} while spec is Draft")

    completed = spec_status == "Complete" or plan_status == "Complete"
    if completed and not (spec_status == "Complete" and plan_status == "Complete"):
        errors.append(f"{task_dir.relative_to(ROOT)}: spec and plan must both be Complete")

    check_path = task_dir / "check.md"
    if completed and not check_path.is_file():
        errors.append(f"{check_path.relative_to(ROOT)}: completed task requires verification evidence")
    if check_path.is_file():
        check_text = read_text(check_path, errors)
        check_status = get_status(check_path, check_text, CHECK_STATUSES, errors)
        require_headings(check_path, check_text, CHECK_HEADINGS, errors)
        reject_placeholders(check_path, check_text, errors)
        expected_plan = f".tasks/{task_dir.name}/plan.md"
        if expected_spec not in check_text or expected_plan not in check_text:
            errors.append(f"{check_path.relative_to(ROOT)}: must link the task spec and plan")
        if completed and check_status != "Passed":
            errors.append(f"{check_path.relative_to(ROOT)}: completed task must have Status: Passed")
        if check_status == "Passed" and not completed:
            errors.append(f"{check_path.relative_to(ROOT)}: Passed requires spec and plan to be Complete")

    return errors


def task_directories() -> list[Path]:
    if not TASKS_DIR.is_dir():
        return []
    return sorted(path for path in TASKS_DIR.iterdir() if path.is_dir() and path.name != "_templates")


def changed_paths(base: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git diff failed for base {base}")
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def needs_sdd(path: str) -> bool:
    if path.startswith((".tasks/", "docs/", "rules/")):
        return False
    if path.endswith((".md", "package-lock.json")):
        return False
    return True


def changed_task_names(paths: list[str]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        parts = Path(path).parts
        if len(parts) >= 3 and parts[0] == ".tasks" and parts[1] != "_templates":
            names.add(parts[1])
    return names


def exemption_reason() -> str:
    body = os.environ.get("SDD_PR_BODY", "")
    body_without_comments = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    match = re.search(
        r"^SDD-Exempt:\s*(\S.*)$",
        body_without_comments,
        re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--all", action="store_true", help="validate all task directories (default)")
    scope.add_argument("--task", help="validate one kebab-case task name")
    parser.add_argument("--changed-base", help="require a changed SDD task for behavior-changing files")
    args = parser.parse_args()

    errors: list[str] = []
    if args.task:
        selected = [TASKS_DIR / args.task]
        if not selected[0].is_dir():
            errors.append(f".tasks/{args.task}: task directory does not exist")
    else:
        selected = task_directories()
        if not selected:
            errors.append(".tasks: no SDD task directories found")

    for task_dir in selected:
        if task_dir.is_dir():
            errors.extend(validate_task(task_dir))

    if args.changed_base:
        try:
            paths = changed_paths(args.changed_base)
        except RuntimeError as exc:
            errors.append(str(exc))
        else:
            behavior_paths = [path for path in paths if needs_sdd(path)]
            changed_tasks = changed_task_names(paths)
            reason = exemption_reason()
            if behavior_paths and not changed_tasks and not reason:
                errors.append(
                    "behavior-changing files are present but no .tasks/<task-name>/ documents changed; "
                    "add an SDD task or a justified 'SDD-Exempt:' line to the PR body"
                )
            if reason:
                print(f"SDD exemption declared: {reason}")

    if errors:
        print("SDD validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"SDD validation passed for {len(selected)} task(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
