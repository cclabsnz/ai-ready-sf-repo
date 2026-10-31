---
scope: "force-app/**/*.cls,force-app/**/*.trigger"
---
# Apex rules

Each bullet names the rule id `tools/code/check_rules.py` reports.

- Enforce FLS and CRUD with `WITH USER_MODE` in SOQL and `AccessLevel.USER_MODE` in DML. `WITH SECURITY_ENFORCED` is superseded and cannot be combined with user mode in one query. (`apex-user-mode`; not applied inside `@IsTest` classes, where test data setup runs in system mode. Every other rule applies to test classes.)
- Declare sharing explicitly on every class. `without sharing` needs a comment stating why. (`apex-sharing`)
- Bulk-safe: no SOQL or DML in loops. (`apex-no-soql-dml-in-loop`)
- Logging through the project logger; no `System.debug` left in committed code. (`apex-no-system-debug`)
- Tests assert behaviour (values, counts, exceptions); `System.assert(true)` and `SeeAllData=true` are rejected in CI, not in review. (`apex-no-assert-true`, `apex-no-seealldata`)
- Naming: project prefix + PascalCase; tests end in `_Test`. (`apex-test-naming` checks the `_Test` suffix.)
