# Demo org

A synthetic Sales/Service org used to exercise the index, story-refine, story-impact and the evals. Nothing here
comes from a real org; names are fictional. Nothing was deployed anywhere.

## Layout

- `demo/org/force-app/`: the metadata. A hand-written story core (Case, Entitlement, escalation and
  customer-tier chains, including one deliberately aged legacy class) plus generated filler.
- `demo/stories/DEMO-*.md`: the story text a squad would hand to story-impact.
- `demo/stories/DEMO-*.answer.json`: the reviewed answer key for each story.
- `demo/stories/DEMO-101.vague-example.story.json`: a hand-written draft `story.json` for DEMO-101
  whose criteria are vague on purpose. It passes `tools/stories/validate_story.py` and fails
  `tools/stories/check_ac.py`, to show what that check reports (README quick start step 9). It is
  not story-refine output: the skill's writer refuses vague criteria.

## What the index models

Beyond the original nodes and edges: validation rules, record types, triggers to their objects, Apex
class to class, invocable and `@AuraEnabled` methods (the LWC Apex import edge has `auraEnabled` true
or false, or null when the class is not indexed), flow Apex actions and trigger objects, FlexiPages,
and permission-set object and class access. `consumers` goes to 3 hops. Since index version
`0.5.0`, fields also carry their picklist values (with an active flag and the value's line), a
global value set's name, and a formula flag; `query.py edge-seeds` reads them.

## Stories

- **DEMO-101** (Customer Tier on the Case page): a new field plus the existing places that show
  account data to agents, and the overlapping tier and segment concepts a person must weigh.
- **DEMO-201** (premium case escalation): seeded only from `Account.Service_Level__c`, the field that
  defines "premium customers", at hops 3. From that field, the escalation flow
  (`Case_Escalate_Premium`), the agent page (`Case_Agent_Console`) and the trigger (`CaseTrigger`) are
  three hops away, through the escalation service and the classes and component that call it. None
  of them names the field, so a field search finds none of them; only the reference chain does.
  Eval case 004 asks for exactly those.
- **DEMO-202** (round-robin assignment of new cases): shares `CaseTriggerHandler` with DEMO-201.
  It is on the register; see below.

## The DEMO-202 impact record

`impacts/DEMO-202-round-robin-assignment/` holds DEMO-202's promoted impact record (`impact.json`)
and its report (`impact.md`). It gives the overlap checks a real story to find. It came through
the real pipeline:

1. `tools/demo/answer_to_draft.py --key demo/stories/DEMO-202.answer.json --slug round-robin-assignment --index index`
   turned the reviewed answer key into `classified.json` and `meta.json` and ran story-impact's
   writer, `write_report.py`, which wrote the draft to `ai-context/DEMO-202-round-robin-assignment/`.
2. The owner reviewed the draft and ran `tools/impacts/promote.py` on it, confirming it with
   their own `--confirmed-by`. The assistant did not run the promotion or supply the confirmation.

The record is **key-derived, not a model run**: its `provenance.model` reads
`none (derived from reviewed answer key)` and `provenance.assistantVersion` reads `n/a`. Its
components, change types and hops come from the key.

- **Evidence:** index components take their evidence from the index. The judgement component
  `Escalation_Agents` takes the key's own cite. `:1` is added only when that cite has no line
  number.
- **Impact and confidence:** the script maps them (`tools/demo/answer_to_draft.py:37`,
  `:84-87`). `modify` gives Medium and `review` gives Low. A judgement component is Inferred and
  an index component Confirmed.

Its `impact.md` says `none in the register` under "Overlaps with other stories". That is correct
for when it was written: the overlap section is a snapshot taken at write time, and the register
was empty then. A DEMO-201 draft written now lists DEMO-202 (README quick start step 7). The
overlaps there are watches, not conflicts, because DEMO-201's key marks the shared components
`review`.

## Answer keys

- **Seeds** anchor the check: the checker expands them through the index. They are not given to
  the AI; story-impact gets only the story text. DEMO-101's seeds are themselves answer components,
  by ruling, so they are listed at hop 0.
- **changeType**: `modify` means the story requires a change to the component; `review` means it
  may need one, or the component must be confirmed unaffected; `new` means it does not exist yet.
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

The generated tests run their record work as a user holding the area permission set, because fields
deployed through the Metadata API grant field access to nobody. Flows stamp a status field that no
generated service stamps, so a flow firing during a test never changes a field the test asserts.

**Determinism.** CI pins Python 3.12 (`.github/workflows/framework-ci.yml:13`). The generator uses
`random`, whose output may differ across Python minor versions, so regenerate and run `--check` with
Python 3.12.

## Signs of age

These classes are deliberately aged, and each says so in a header comment: `LegacyCaseMerge` (old
API, `without sharing`), and the filler `RenewalOutlookService` and `ContractTermService` (old API).
Each uses plain SOQL and DML with no user-mode enforcement, as code from before user mode would;
the WS8 rule baseline records that debt. Their tests stay on the current API and match them.

`Account.Service_Level__c` keeps a retired picklist value, `Legacy Bronze`, marked
`<isActive>false</isActive>` (`demo/org/force-app/main/default/objects/Account/fields/Service_Level__c.field-meta.xml:27-29`).
It is a deliberate sign of age: records created before the value was retired can still hold it,
while Salesforce no longer offers it for new selections (Inferred from platform behaviour; nothing
here was deployed). `query.py edge-seeds Account.Service_Level__c` lists it as
`Legacy Bronze (inactive)`, so story refinement has a real inactive value to judge. The answer
keys are unaffected: a picklist value is a field attribute in the index, not a node or an edge.

## Building an index of the demo

`build_index.py --out` resolves relative to `--root`, and so does the default (`index`), which would
write `demo/org/index` inside the scanned tree. Always pass an absolute `--out`.

## Index limits on a real org

The demo is built to avoid these; a real org will not be.

- A short field name such as `X__c` in Apex links to every object's field with that name.
- Apex name matching is case-sensitive, though Apex itself is not.
- A relationship name that equals an unrelated object's name can resolve to that object.

## Line endings and owner patches

The demo's line endings are pinned to LF (`demo/org/** text eol=lf` in `.gitattributes`, delivered as
`ai-context/ws1/patches/gitattributes-ws1.patch`) so the filler `--check`, which compares bytes,
passes on a Windows checkout. Apply that patch together with `ai-context/ws1/patches/ci-ws1.patch`:
the CI patch adds the `--check` step to the Windows job, which fails without the LF pin.

## Before deploying (Unverifiable here; nothing was deployed)

- Entitlement Management must be enabled in the target org.
- Case field history must be enabled.
- Agents may need the "Transfer Cases" permission for the owner change.
- User visibility settings can shrink the assignment pool.
- Escalation on insert is not handled; the logic runs on update only.
- The Automated Case User needs field access to `Account.Service_Level__c` and
  `Entitlement.Premium_SLA_Hours__c`: `CaseEscalationService` reads them `WITH USER_MODE`
  (`CaseEscalationService.cls:48`, `:51`) when the trigger runs as that user.
- Case assignment rules that run on insert may override the owner DEMO-202 sets (also a DEMO-202
  assumption).
- The assignment test counts the members of the shared `Escalation_Agents` queue, so members
  already in the target org's queue change what it sees.
- A test adds an inactive user as a queue member.
- Demo class names carry no project prefix; the prefix becomes a per-project setting in WS8.
