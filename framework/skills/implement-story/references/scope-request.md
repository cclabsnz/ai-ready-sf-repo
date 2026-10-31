# Scope request: implement-story

Written to `ai-context/<id>-<slug>/scope-request.md` when the change needs a component outside the build package scope. The skill stops after writing it. Nothing outside scope is written, and the package is never edited by the assistant.

Template (the three `- Field:` lines are parsed; keep them on one line each):

```markdown
# Scope request: DEMO-202 round-robin-assignment

- Component: `Escalation_Agents`
- Reason: one sentence on why the criterion cannot be met inside the current scope.
- Evidence: `demo/org/force-app/main/default/queues/Escalation_Agents.queue-meta.xml:1`
- Criterion: AC-2
- Owner role: Service Ops lead

The scope changes only through a re-assessed impact and a new build package, made by a human.
```

Rules:
- `Component` is the API name or the repo-relative path, and is not already in `scope.modify`, `scope.create` or `scope.tests`.
- `Evidence` is a backticked `path:line` that exists, or a negative finding ("zero hits for `Assignment_Log__c` in the index").
- `Criterion` and `Owner role` are optional; name the owner role who decides on the re-assessment.
- One request per component. Neutral wording: state the finding and the owner role; the human decides.
