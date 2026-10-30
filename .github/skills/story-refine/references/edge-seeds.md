# Edge seeds

`python3 tools/index/query.py edge-seeds <api> [<api>...]` prints `{"seeds": [...], "unresolved": [...]}`. Each seed is `{category, component, detail, evidence, confidence}`, built from index edges and node attributes only. Save the output as `ai-context/<id>-<slug>/scan/edge-seeds.json`; the eval checks `edges_from_seeds_only` and `seeds_accounted` read it. A seed is identified by its (component, category, detail).

## Scope

- A field seed covers the field and its object.
- An object seed covers the object only, not all of its fields.
- `unresolved` lists apis the index does not hold: planned new components, or typos. They produce no seeds.

## Categories

| Category | Emitted for | Typical criterion |
|---|---|---|
| `blank` | A field that is not required | What happens when the value is empty |
| `picklist-value` | Each picklist value, inactive values marked; a global value set gives one `Unverifiable` seed | Behaviour for each value that matters, including retired ones on old records |
| `field-access` | Each permission set that grants the field, read or edit | What a user with read-only access sees |
| `record-type` | Each record type of the object | Behaviour per record type |
| `automation` | Validation rules, record-triggered flows and triggers on the object | The story's change meets the rule or automation |
| `bulk` | Every object: "a bulk change of 200 records or more" | A data load or mass update |
| `integration-user` | A permission set whose name contains "integration" and grants a field on the object (`Inferred`) | A write from an integration user |

## Judging

- Account for every seed: each one is either an edge case or a dropped seed.
- Keep a seed as an edge case when the story's change can meet it. Copy `category`, `component`, `detail`, `evidence` and `confidence` from the seed verbatim; never edit them.
- Drop a seed with a one-line reason when the story cannot meet it (`droppedSeeds`: `category`, `component` and `detail` copied verbatim, plus `reason`).
- Never add an edge case that is not a seed. A risk the index cannot see goes into `openQuestions` with an owner role.
- Few or no seeds is a valid result for a greenfield story. Say so; do not invent seeds to fill the table.
