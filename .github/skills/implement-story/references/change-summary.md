# Change summary: implement-story

The draft at `ai-context/<id>-<slug>/scan/change-draft.json`. `write_change.py` validates it against the build package and writes `change.json` and `change.md`.

```json
{
  "storyId": "DEMO-202",
  "files": [
    {"path": "demo/org/force-app/main/default/classes/CaseAssignmentService.cls",
     "component": "CaseAssignmentService", "changeType": "modify",
     "evidence": "demo/org/force-app/main/default/classes/CaseAssignmentService.cls:12",
     "confidence": "Confirmed"}
  ],
  "criteriaToTests": {
    "AC-1": ["demo/org/force-app/main/default/classes/CaseAssignmentService_Test.cls#assignsInTurnOnInsert"]
  },
  "done": [
    {"command": "python3 tools/code/check_trace.py --skeletons DEMO-202", "exit": 0}
  ]
}
```

Rules the writer enforces:
- `files`: every path written, once each. A path is in `scope.modify` (`changeType: modify`), a `scope.create` path (`changeType: new`, `component` equal to that entry's `api`), or `scope.tests` (`modify` or `new`). Anything else is refused.
- `evidence` is `<the file's own path>:<line>`, a line inside the file as written. `confidence` is Confirmed, Inferred or Unverifiable.
- `criteriaToTests`: every package criterion id, and only those, each mapped to at least one `<path>#<method>`. The path is in `scope.tests` and is not a `-meta.xml` file; the file holds the method name and the id (the `// AC-n` comment).
- `done`: every package `done[]` command exactly once, with its integer exit code. A non-zero exit is recorded as it is; `change.md` lists it as not done. The exit codes are the session's own report: `write_change.py` never runs or re-runs the commands, so `change.md` labels them Inferred, and CI re-runs them.

The draft never carries `schemaVersion`, `slug` or `package`: the writer fills them in, with the package path and its sha1.
