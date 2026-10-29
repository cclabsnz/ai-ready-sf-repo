---
applyTo: "force-app/**/*.cls,force-app/**/*.trigger"
---
# Apex rules

- Enforce FLS and CRUD with `WITH USER_MODE` in SOQL and `AccessLevel.USER_MODE` in DML. `WITH SECURITY_ENFORCED` is superseded and cannot be combined with user mode in one query.
- Declare sharing explicitly on every class. `without sharing` needs a comment stating why.
- Bulk-safe: no SOQL or DML in loops.
- Logging through the project logger; no `System.debug` left in committed code.
- Tests assert behaviour (values, counts, exceptions); `System.assert(true)` and `SeeAllData=true` are rejected in CI, not in review.
- Naming: project prefix + PascalCase; tests end in `_Test`.
