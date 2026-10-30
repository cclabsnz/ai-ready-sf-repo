# Input checklist: story-refine

| Input | Required | Unlocks | If missing |
|---|---|---|---|
| Story text (title, description, any criteria already written) | Yes | Persona, goal, benefit, seed terms | Ask once; cannot proceed |
| Story ID | Yes | Output folder `ai-context/<id>-<slug>/` | Ask once |
| Squad | Yes | `squad` in `story.json`; must be listed in `impacts/squads.json` | Ask once |
| Persona and benefit, when the text does not state them | No | `persona`, `benefit` | Write the likeliest reading and add an open question for the Product Owner |
| Known exclusions | No | `outOfScope` | Add an open question for the Product Owner |
| Non-functional needs (volumes, timing, access) | No | `nonFunctional` and criteria with numbers | Add an open question; never invent a number |
| Prior `ai-context/<id>-*/story.json` for the same item | No | Reuse of judged seeds | Rerun the scan |
| Any attached design or data-dictionary extract | No | Picklist values and field rules not yet in the repo | Record the gap as an open question |

Attached files are copied to `ai-context/<id>-<slug>/inputs/` (git-ignored). Never move the user's original.
