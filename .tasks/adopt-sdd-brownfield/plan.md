# Plan — Adopt SDD Brownfield

Status: Complete
Spec: `.tasks/adopt-sdd-brownfield/spec.md`

## Approach

Adapt the useful structure of the supplied template to this repository, treat the existing application as the source for a brownfield baseline, and enforce the resulting document contract with a small Python validator and CI workflow.

## Impact Analysis

- Runtime application behavior: no change.
- Developer workflow: behavior-changing pull requests gain required SDD documents and verification evidence.
- CI: a new fast, dependency-free documentation validation job is added.
- Deployment: no Firebase or Vercel resources are changed.
- Data: no Firestore, Storage, SQLite, or traders data is read or written by the implementation.

## Steps

1. Add the root SDD entry point and brownfield baseline.
2. Add general and project-specific rules adapted to the current stack.
3. Add task templates for specification, plan, and verification.
4. Add a standard-library SDD validator with clear failures.
5. Add GitHub Actions and pull-request checklist integration.
6. Add the SDD contract to `AGENTS.md` and link it from the main README.
7. Run validator, frontend lint/build, and Python syntax checks.
8. Record verification evidence and mark this adoption task complete.

## Files to Change

Create:

- `SDD.md`
- `rules/general-rules.md`
- `rules/project-rules.md`
- `docs/sdd-workflow.md`
- `docs/brownfield-baseline.md`
- `.tasks/_templates/spec.template.md`
- `.tasks/_templates/plan.template.md`
- `.tasks/_templates/check.template.md`
- `.tasks/_templates/README.md`
- `.tasks/adopt-sdd-brownfield/check.md`
- `scripts/sdd_check.py`
- `.github/workflows/sdd-check.yml`
- `.github/pull_request_template.md`
- `CHANGELOG.md`

Modify:

- `AGENTS.md`
- `README.md`
- `.gitignore`

Delete: none.

## Tests

- `python scripts/sdd_check.py --all`
- `python -m compileall -q backend functions scripts`
- `npm run lint --prefix frontend`
- `npm run build --prefix frontend`
- Inspect `git diff --check` and ensure unrelated local files are not staged.

## Rollback Plan

Revert the SDD adoption commit. Since this task does not change runtime code, no data migration or deployment rollback is required.

## Risks

- Excessive process could slow tiny changes; the workflow therefore defines a narrow exemption.
- Documentation can become stale; the validator checks structure, while reviewers must still check technical truth.
- CI alone does not block merging until the repository owner marks the SDD check as required in branch protection.
