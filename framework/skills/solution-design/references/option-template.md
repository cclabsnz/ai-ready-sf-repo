# Option template: solution-design

One entry in `options` per option. The do-nothing option is always present and has no components.

```json
{
  "id": "OPT-2",
  "title": "Extend the existing assignment service",
  "summary": "One or two sentences: what changes and where.",
  "doNothing": false,
  "components": [
    {"api": "CaseAssignmentService", "type": "ApexClass", "changeType": "modify",
     "evidence": "demo/org/force-app/main/default/classes/CaseAssignmentService.cls:10",
     "confidence": "Confirmed"},
    {"api": "Assignment_Position__c", "type": "CustomObject", "changeType": "new",
     "evidence": null, "confidence": "Inferred"}
  ],
  "tradeOffs": [
    {"criterion": "reuse", "note": "Builds on the class that already assigns cases."}
  ],
  "impactSummary": "One sentence on what this option touches."
}
```

Rules the writer enforces (`tools/designs/validate_design.py`):
- `id` is `OPT-<n>`, numbered from 1 with no gaps; two to four options in all.
- Exactly one option has `doNothing: true`, and its `components` is empty.
- Every other option lists at least one component, each `api` once per option.
- A component whose `changeType` is not `new` is a node in the index and carries `path:line` evidence (null only at confidence Unverifiable).
- A `new` component has `evidence: null` and is not already a node in the index (use `modify` or `review` for one that is).
- Every option has at least one trade-off; `criterion` comes from `trade-off-criteria.md`.

The do-nothing option:

```json
{
  "id": "OPT-1", "title": "Do nothing", "summary": "Leave the build as it is.",
  "doNothing": true, "components": [],
  "tradeOffs": [{"criterion": "reuse", "note": "State what the build already does, with path:line."}],
  "impactSummary": "No metadata changes."
}
```

The recommendation:

```json
{"optionId": "OPT-2", "reasons": ["Reuses CaseAssignmentService (CaseAssignmentService.cls:10)."]}
```
