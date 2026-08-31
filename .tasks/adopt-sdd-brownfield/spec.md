# Adopt SDD Brownfield

Status: Complete
Owner: Store Extractor team
Type: Engineering process

## Context

The repository already contains a working React, FastAPI, and Firebase system, but behavior-changing work is not consistently preceded by an approved specification and implementation plan. The supplied SDD template targets a different Node/AWS stack and has no deterministic validation, so copying it directly would create incorrect project guidance.

## Current Behavior

- Requirements and implementation decisions are distributed across chat history, `AGENTS.md`, deployment documentation, and code.
- There is no standard task folder that links requirements, implementation steps, and verification evidence.
- Pull requests are not automatically checked for SDD document completeness.
- The supplied template's project rules conflict with this repository's Python/Firebase/Vercel architecture.

## Requirements

- Establish a repository-native Specify, Plan, Implement, Check workflow for behavior changes, bug fixes, and refactors.
- Preserve `AGENTS.md` as the detailed technical reference and add a short SDD entry point.
- Document the current brownfield architecture and known constraints before future changes are specified.
- Provide reusable specification, plan, and verification templates.
- Add a dependency-free validator suitable for local use and GitHub Actions.
- Add pull-request guidance that makes the relevant SDD task and validation evidence visible.
- Keep runtime behavior unchanged.

## Constraints

- The rules must describe the actual React 19, FastAPI, Firebase Functions, Cloud Tasks, Firestore, Cloud Storage, and Vercel stack.
- Existing local environment edits and generated analysis outputs must not be included.
- Service-account files and environment secrets must never be committed.
- Writes to `traders-data-live` remain disabled unless the user explicitly authorizes enabling them in a separate task.
- The SDD validator must run with the Python standard library only.

## Acceptance Criteria

- A developer can create a new task from repository templates and follow a documented four-stage workflow.
- Every non-template task directory is machine-checked for `spec.md` and `plan.md`.
- A completed task is rejected unless it also contains a passed `check.md`.
- GitHub Actions runs the SDD validator on pull requests and pushes to `main`.
- The pull-request template asks for the task path and verification evidence.
- Project rules accurately describe local and Firebase production execution.
- Existing frontend and backend runtime files are not changed by this task.

## Edge Cases

- Draft specifications are valid while requirements are still being discussed, but implementation must not begin from a draft.
- Emergency fixes may create the SDD documents in the same pull request, but may not omit them.
- Documentation-only, comment-only, dependency-lock-only, and generated-file changes may use the documented exemption.
- A task marked complete without verification evidence must fail validation.

## Out of Scope

- Refactoring application runtime code.
- Adding application unit or integration tests.
- Changing Firebase, Vercel, Firestore, Storage, or GitHub repository settings.
- Enabling writes to the traders database.
- Importing Claude-only commands that do not run in Codex.
