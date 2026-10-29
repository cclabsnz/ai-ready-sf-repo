# Demo org

A synthetic Sales/Service org used to exercise the index, story-impact and the evals. Nothing here
comes from a real org; names are fictional. Nothing was deployed anywhere.

## Layout

- `demo/org/force-app/`: the metadata. A hand-written story core (Case, Entitlement, escalation and
  customer-tier chains, including one deliberately aged legacy class) plus generated filler.
- `demo/stories/DEMO-*.md`: the story text a squad would hand to story-impact.
- `demo/stories/DEMO-*.answer.json`: the reviewed answer key for each story.

## What the index models

Beyond the original nodes and edges: validation rules, record types, triggers to their objects, Apex
class to class, invocable and `@AuraEnabled` methods (the LWC Apex import edge has `auraEnabled` true
or false, or null when the class is not indexed), flow Apex actions and trigger objects, FlexiPages,
and permission-set object and class access. `consumers` goes to 3 hops.

## Answer keys

- **Index components** (`source` "index", the default): `hop` is the minimum index hop. It is
  index-derived, so scoring must not treat hop as independent human truth.
- **Judgement components** (`source` "judgement"): things the index cannot see. Each carries file
  evidence and a null hop.
- **Assumptions and decisions**: decisions name an owner role.
- `python3 tools/demo/check_answers.py --index <dir> demo/stories/DEMO-101.answer.json ...` checks
  that the index finds exactly what each key lists.

## Filler generator

`tools/demo/generate_filler.py --seed 2026 --out demo/org` is seeded and deterministic. It only adds
files that are missing, and `--check` writes nothing and fails if the committed filler differs. The
filler is isolated from the story core: it never references a core API name and never touches Case
or Entitlement, so the answer keys stay exact.

## Building an index of the demo

`build_index.py --out` resolves relative to `--root`, and so does the default (`index`), which would
write `demo/org/index` inside the scanned tree. Always pass an absolute `--out`.

## Line endings

The demo's line endings are pinned to LF (`demo/org/** text eol=lf` in `.gitattributes`, delivered as
`ai-context/ws1/patches/gitattributes-ws1.patch`) so the filler `--check`, which compares bytes,
passes on a Windows checkout.

## Before deploying (Unverifiable here; nothing was deployed)

- Entitlement Management must be enabled in the target org.
- Case field history must be enabled.
- Agents may need the "Transfer Cases" permission for the owner change.
- User visibility settings can shrink the assignment pool.
- Escalation on insert is not handled; the logic runs on update only.
- Demo class names carry no project prefix; the prefix becomes a per-project setting in WS8.
