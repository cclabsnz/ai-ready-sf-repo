# Input checklist: story-impact

| Input | Required | Unlocks | If missing |
|---|---|---|---|
| Work item text (title, description, acceptance criteria) | Yes | Seed terms, framing | Ask once; cannot proceed |
| Work item ID | Yes | Output folder, prior-analysis lookup | Ask once |
| Linked parent feature text | No | Scope boundary | Record as unknown |
| Prior `ai-context/<id>-*/impact.md` for the same or parent item | No | Reuse, only if stamp commit matches or diff touches none of its paths | Rerun scan |
| Any attached design or data-dictionary extract | No | Field-type checks | Confidence capped at Inferred for type claims |

Attached files are copied to `ai-context/<id>-<slug>/inputs/` (git-ignored). Never move the user's original.
