## Summary

<!-- What changed for the user/system? -->

## SDD

- SDD Task: `.tasks/<task-name>/`
- Spec status: Complete / Approved
- Plan status: Complete / Approved
- Check status: Passed / Pending

<!-- For a truly non-behavioral change only, use the exemption field described in SDD.md. -->

## Verification

- [ ] `python scripts/sdd_check.py --all`
- [ ] Relevant automated tests passed
- [ ] Relevant manual flow was checked
- [ ] Acceptance criteria are evidenced in `check.md`

## Safety and deployment

- [ ] No secrets, `.env`, service-account files, videos, or generated job data were committed
- [ ] No write to `traders-data-live` occurred or was enabled
- [ ] Deployment/configuration steps and rollback are documented when applicable
