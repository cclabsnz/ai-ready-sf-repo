# Input checklist: solution-design

| Input | Required | Unlocks | If missing |
|---|---|---|---|
| Story text (title, description, criteria already written) | Yes | Seed terms, options | Ask once; cannot proceed |
| Story ID | Yes | Output folder `ai-context/<id>-<slug>/` | Ask once |
| Refined story `ai-context/<id>-<slug>/story.json` (from `story-refine`) | No | Criteria and edge cases each option must meet | Work from the story text; note in the trade-offs that criteria are unrefined |
| Impact framing (`impact.md` for this story, if one exists) | No | What "affected" means for this story | Frame it from the story text |
| Constraints (licences, data volumes, deadlines, platform limits) | No | `licence-fit`, `data-volume` and `governor-limits` trade-offs | Record the gap in the trade-off note with an owner role; never invent a number |
| Options the requester already has in mind | No | Options to include and compare | Derive options from the index |
| Any attached design or data-dictionary extract | No | Components not yet in the repo | Record the gap as an open point |

Attached files are copied to `ai-context/<id>-<slug>/inputs/` (git-ignored). Never move the user's original.
