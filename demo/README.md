# Demo org

A synthetic Sales/Service org used to exercise the index, story-refine, solution-design, story-impact and the evals,
plus an empty greenfield skeleton. Nothing here
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
- `demo/greenfield/`: the empty greenfield skeleton (see below).

## The greenfield skeleton

`demo/greenfield/` is what greenfield onboarding creates for a repo with no code yet:
`sfdx-project.json` (`packageDirectories` of `force-app` as the default, and `sourceApiVersion`
`62.0`, matching `demo/org/sfdx-project.json`) and `force-app/main/default/` with a `.gitkeep`
in `classes`, `objects`, `lwc`, `flows` and `permissionsets`. It holds no metadata, so its index
is empty: `query.py exists`, `consumers` and `edge-seeds` on it exit 0 with empty results
(`case_empty_source_root_indexes` in `tools/onboard/test_onboard.py`).

It was generated, not hand-written, and is committed as generated:

```sh
python3 tools/onboard/onboard.py --starting-point greenfield --source-root demo/greenfield
```

That run leaves the repo's `.ai-framework.json` (`sourceRoot` `demo/org`) as it is, because it
has no `--write-config`. It replaces `index/` with the empty greenfield index, so rebuild the
demo index afterwards with `python3 tools/index/build_index.py --from-config`.

solution-design's eval case 002 (`framework/skills/solution-design/evals/cases/002-greenfield-warranty.json`,
story DEMO-301, a warranty claim object) runs against this skeleton. Its `indexRoot` is
`demo/greenfield`, so the operator builds that index with `--root demo/greenfield` and an absolute
`--out` of their choosing and passes it to `run_skill.py` as `--index`. `write_design.py` and
`promote.py` take the same `--index`, and `write_design.py` takes `--source-root demo/greenfield`
so the design records the root it was written for. The repo's `--from-config` index covers only
`demo/org`. Against the empty index, every component of every option must be `new`. That
includes the standard object `Case`, which has no node in an empty index: link to it through a
`new` field such as `Warranty_Claim__c.Case__c`. DEMO-301 has no story file or answer key under
`demo/stories/`; the case's input holds the story text.

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

`impacts/DEMO-202-round-robin-assignment/` holds DEMO-202's confirmed story, design and impact and
its build package. It gives the overlap checks a real story to find, and the code walkthrough a
package to build from. It came through the real pipeline, once:

1. story-refine drafted the story, and the owner answered or deferred its open questions and ran
   `tools/impacts/promote.py --story`.
2. solution-design drafted the options, and story-impact assessed the option the owner chose.
   The owner ran `promote.py --option OPT-2 --replace`, which replaced an earlier record derived
   from the answer key; that one stays in git history.
3. A maintainer ran `tools/impacts/package.py DEMO-202` and committed the package.

The assistant did not run a promotion or supply a confirmation. This is **one run with the owner's
answers along the way**, not a measure of the assistant. The answer key predates the design, so
the record scores low precision against it (`demo/measure/README.md`).

`demo/org` stays unimplemented for this story on `main`, so you can run the build yourself
(`demo/WALKTHROUGH.md` step 6).

Its `impact.md` says `none in the register` under "Overlaps with other stories". That is correct
for when it was written: the overlap section is a snapshot taken at write time, and the register
held only DEMO-202 then. A DEMO-201 draft written now lists DEMO-202 (README quick start step 7).
The overlaps there are watches, not conflicts, because DEMO-201's key marks the shared components
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
Each uses plain SOQL and DML with no user-mode enforcement, as code from before user mode would.
Their tests stay on the current API and match them.

**The rule baseline.** `tools/code/baseline.json` records the findings `tools/code/check_rules.py`
reports on `demo/org`, so `python3 tools/code/check_rules.py --from-config` exits 0 with nothing
new. The demo files are not edited to clear them: committed records and pasted output cite their
lines. A run lists, by rule and class:

- **`apex-user-mode`** in the sign-of-age classes above: SOQL without `WITH USER_MODE` and DML
  without `as user` in `RenewalOutlookService` and `ContractTermService`, and the plain DML in
  `LegacyCaseMerge`. This is the debt the header comments describe.
- **`apex-sharing`** on inner wrapper classes that declare no sharing keyword, in classes that are
  not legacy: `CaseAccountSummaryController.AccountSummary`, `CaseEscalationService.EscalationState`,
  and `EscalationNotifier.Request` and `EscalationNotifier.Result`. Apex inner classes do not inherit
  the outer class's sharing, so the rule applies to them as written. Limiting `apex-sharing` to
  top-level classes would be an owner choice; it is not made.

`LegacyCaseMerge` declares `without sharing` with a comment on the lines above it saying why
(`demo/org/force-app/main/default/classes/LegacyCaseMerge.cls:3-6`), so `apex-sharing` does not flag
it. Test classes get no `apex-user-mode` finding: the rule is not applied inside an `@IsTest`
class, because test data setup runs in system mode. To see the current list, run the command above
and read `baselined`.

`Account.Service_Level__c` keeps a retired picklist value, `Legacy Bronze`, marked
`<isActive>false</isActive>` (`demo/org/force-app/main/default/objects/Account/fields/Service_Level__c.field-meta.xml:27-29`).
It is a deliberate sign of age: records created before the value was retired can still hold it,
while Salesforce no longer offers it for new selections (Inferred from platform behaviour; nothing
here was deployed). `query.py edge-seeds Account.Service_Level__c` lists it as
`Legacy Bronze (inactive)`, so story refinement has a real inactive value to judge. The answer
keys are unaffected: a picklist value is a field attribute in the index, not a node or an edge.

## Building an index of the demo

`python3 tools/index/build_index.py --from-config` builds it: `.ai-framework.json` names
`demo/org` as the source root, and `--from-config` always writes `index/` at the repo root.

A manual build with `--root demo/org` is different. `--out` resolves relative to `--root`, and so
does the default (`index`), which would write `demo/org/index` inside the scanned tree. Pass an
absolute `--out` there.

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
- Demo class names carry no project prefix. `check_rules.py`'s naming rule (`apex-test-naming`)
  checks only that a test class ends in `_Test`; no project-prefix setting or check exists.
