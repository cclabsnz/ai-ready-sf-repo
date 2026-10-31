---
topic: Profile, permission set and custom permission model
owner: Platform guild lead
last_verified: 2026-10-20
verified_by: xml-parse
---
# Permissions model

- Entitlements are granted through permission sets only; profiles are login/licence shells. (Confirmed: `force-app/main/default/profiles/*` carry no object permissions.)
- A permission set that grants a required field must not carry a `fieldPermissions` entry for it; the deploy fails with "cannot deploy to a required field". Correction recorded 2026-08-24: an earlier note said the opposite.
- Persona-to-permission-set mapping lives in `force-app/main/default/customMetadata/Persona_Matrix.*`; the identity provider owns assignment in production, admins assign ad hoc in sandboxes.

For counts of profiles or permission sets, run `python3 tools/index/query.py type <name>` or read `index/inventory.json`.
