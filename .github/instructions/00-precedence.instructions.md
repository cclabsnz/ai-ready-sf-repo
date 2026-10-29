---
applyTo: "**"
---
# Precedence and evidence

- The checked-out build (`force-app/`, `pkg-*/`, `manifest/`) is the only source of truth.
- Knowledge files are leads to re-verify, never evidence.
- Anything countable comes from `tools/index/query.py` at a stated commit. Never type a count into a file or a report.
- Every claim carries evidence: `path:line`, or "zero hits for pattern X" (a negative finding is still a finding).
- Every claim carries one of three labels: **Confirmed** (evidence in the build), **Inferred** (reasoned from evidence, not directly shown), **Unverifiable** (managed-package internals, org-only config, missing input).
- Outputs go to `ai-context/<work-item-id>-<slug>/`. Nothing else is written.
- The assistant never approves, votes, deploys, pushes or decides. It produces evidence, options, and decisions required with an owner role.
