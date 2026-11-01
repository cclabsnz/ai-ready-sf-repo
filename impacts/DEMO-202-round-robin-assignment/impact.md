# Impact: DEMO-202 round-robin-assignment

Index commit `01c0744d0f6f`, index version 0.5.0, built 2026-11-01T21:14:07+00:00.

Assessed option: OPT-2 from design.json (recommended by: assistant). A named owner confirms the option at promotion.

## Framing

The story is confirmed (`impacts/DEMO-202-round-robin-assignment/story.json`, commit 01c0744, squad Service Ops) and is for a Service Ops case manager. Every newly created Case, including record type Premium_Support, whose OwnerId is still the creator gets an owner from the active users of the Escalation_Agents queue in turn. The rotation position is kept between transactions. A case created with an explicit owner other than the creator keeps that owner (AC-1 to AC-7, OQ-11). The trigger is a Case insert. Today `CaseTrigger` runs on update only (`CaseTrigger.trigger:1`). "Affected" means metadata that has to change, or be re-checked, so that before-insert assignment works without changing the existing update-path re-assignment (OQ-3).

This record sizes OPT-2 only. OPT-2 is the design's provisional recommendation (`recommendation.optionId`), and it is not confirmed until the owner promotes with `--option OPT-2`.

**Gap against the option:** a test class outside OPT-2, `CaseAccountSummaryController_Test`, inserts a Case with the default owner (`:64-65`), so insert-time assignment reaches it. The previous run also had `CaseEscalationService_Test` and `EscalationNotifier_Test` in this gap. Under AC-7 neither is affected, so both are now triaged out with reasons (below).

Inputs: the work item text and ID came from the confirmed story.json (01c0744). Design: design.json OPT-2 (written at index commit 01c0744). hops = 2 (default). Missing optional inputs are the parent feature text and a data-dictionary extract, both recorded as unknowns. No attachments were copied. Index freshness: `check-stale` reported stale=false, with index commit = HEAD = 01c0744.

## Seed terms (scan/terms.txt)

- Quoted from story seeds: `Case`, `CaseAssignmentService`, `CaseTrigger`, `CaseTriggerHandler`.
- From the OPT-2 component list: `CaseAssignmentService_Test`, `CaseTriggerHandler_Test`, `Service_Agent`, `Team_Lead`, `Round_Robin_State__c`, `Round_Robin_State__c.Last_Assigned_User__c`.
- Derived: `Escalation_Agents` (the pool, `CaseAssignmentService.cls:13`), `Case.Premium_Support` (AC-6), `Case.OwnerId` (the assigned field, and the field AC-7 tests), `Logger` (project logging rule).
- Managed-package equivalents: none. The index stamp has an empty namespaces list.
- Zero hits in the index for `Escalation_Agents`, `Case.OwnerId`, `Round_Robin_State__c`, `Round_Robin_State__c.Last_Assigned_User__c` and `Logger`. Zero consumers in the index for `CaseTrigger`, `CaseAssignmentService_Test`, `CaseTriggerHandler_Test`, `Service_Agent`, `Team_Lead` and `Case.Premium_Support`. The index results match the previous run.

## Triage (consumers dropped as false positives)

- `Case_Escalate_Premium` (Flow): runs after save on Update only (`Case_Escalate_Premium.flow-meta.xml:59-61`) and never sets the owner (story droppedSeeds).
- `Case.Escalation_Needs_Level` (ValidationRule): reads only IsEscalated and Escalation_Level__c (story droppedSeeds). An owner change cannot trip it.
- `Case.Escalation_Level__c` and `Case.Escalation_Reason__c` (CustomField): assignment neither reads nor writes them.
- `CaseEscalationService` (ApexClass): called on BEFORE_UPDATE and AFTER_UPDATE only (`CaseTriggerHandler.cls:14-19`). The insert branch does not call it.
- `Case_Agent_Console` (FlexiPage): a UI page with no part in owner assignment.
- `Sales_Rep` (PermissionSet): Case allowCreate is false (`Sales_Rep.permissionset-meta.xml:26`, `:31`).
- `CaseEscalationService_Test` (index hop 2, via `Case.Escalation_Reason__c` at `:74`): **dropped in this run.** `openCase` inserts with `OwnerId = owner.Id` (`:34-36`), where owner is a newly inserted user, and is called outside runAs (`:70`, `:89`, `:104-105`, `:120`). The owner therefore differs from the running user, and AC-7 keeps it. The later updates leave Status at Working (`:35`, `:74`, `:93`), so the update-path assign() skips them (`CaseAssignmentService.cls:22`). Inferred, because this holds only if the build implements AC-7.
- `EscalationNotifier_Test` (manual insert-path check, not in the index): **dropped in this run.** `caseFor` inserts with `OwnerId = owner.Id` (`:31-33`), where owner is a new user, and is called outside runAs (`:46-47`). AC-7 keeps the owner, so the Task-owner assertion (`:67`) still holds. Inferred, on the same AC-7 condition. That assertion also works as an existing regression guard for AC-7.

| Impact | Count |
|---|---|
| High | 2 |
| Low | 4 |
| Medium | 7 |

| Component | Layer | Type | Ownership | Change | Impact | Scale | Hop | Evidence | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| `CaseTrigger` | Automation | ApexTrigger | Custom | modify | High | S | 0 | `demo/org/force-app/main/default/triggers/CaseTrigger.trigger:1` | Confirmed |
| `CaseTriggerHandler` | Automation | ApexClass | Custom | modify | Medium | S | 0 | `demo/org/force-app/main/default/classes/CaseTriggerHandler.cls:13` | Confirmed |
| `CaseAssignmentService` | Automation | ApexClass | Custom | modify | High | M | 0 | `demo/org/force-app/main/default/classes/CaseAssignmentService.cls:10` | Confirmed |
| `CaseAssignmentService_Test` | Test | ApexClass | Custom | modify | Medium | S | 1 | `demo/org/force-app/main/default/classes/CaseAssignmentService_Test.cls:27` | Confirmed |
| `CaseTriggerHandler_Test` | Test | ApexClass | Custom | modify | Medium | S | 1 | `demo/org/force-app/main/default/classes/CaseTriggerHandler_Test.cls:61` | Confirmed |
| `Round_Robin_State__c` | Data model | CustomObject | Custom | new | Medium | S |  | `` | Inferred |
| `Round_Robin_State__c.Last_Assigned_User__c` | Data model | CustomField | Custom | new | Low | S |  | `` | Inferred |
| `Service_Agent` | Security | PermissionSet | Custom | modify | Medium | S | 1 | `demo/org/force-app/main/default/permissionsets/Service_Agent.permissionset-meta.xml:49` | Inferred |
| `Team_Lead` | Security | PermissionSet | Custom | modify | Medium | S | 1 | `demo/org/force-app/main/default/permissionsets/Team_Lead.permissionset-meta.xml:49` | Inferred |
| `Case` | Data model | CustomObject | Standard | review | Medium | M | 0 | `demo/org/force-app/main/default/triggers/CaseTrigger.trigger:1` | Confirmed |
| `Case.Premium_Support` | Data model | RecordType | Custom | review | Low | S | 1 | `demo/org/force-app/main/default/objects/Case/recordTypes/Premium_Support.recordType-meta.xml:2` | Confirmed |
| `Escalation_Agents` | Security | Queue | Custom | review | Low | S |  | `demo/org/force-app/main/default/queues/Escalation_Agents.queue-meta.xml:3` | Confirmed |
| `CaseAccountSummaryController_Test` | Test | ApexClass | Custom | review | Low | S |  | `demo/org/force-app/main/default/classes/CaseAccountSummaryController_Test.cls:64` | Inferred |

## Overlaps with other stories

- none in the register at `01c0744`

## Unverifiable

- none

## Unknowns

- OQ-8 (deferred, Salesforce Admin): case volumes per day, at peak and in bulk loads; assignee visibility under org sharing settings.
- OQ-10 (deferred, Salesforce Admin): whether case assignment rules, Omni-Channel or another tool sets the owner of new cases, and which wins.
- Unverifiable (Salesforce Admin, with OQ-10): Web-to-Case and Email-to-Case set the default owner from org settings, not from the running user, so under AC-7 those cases may never match 'owner is still the creator' and may not be round-robin assigned.
- Escalation_Agents queue membership is org data; no members in source, so the real pool size is unknown.
- Linked parent feature text was not supplied; scope boundary taken from the confirmed story only.
- No data-dictionary extract: the type of Round_Robin_State__c.Last_Assigned_User__c is assumed (User lookup) and capped at Inferred.
- CaseTrigger active status is not in the index (story EC-1).
- No managed-package namespace applies: index stamp namespaces is empty and no seed term maps to LLC_BI, nFORCE, nFUSE, nRetail or FinServ.

## Decisions required

- (Product Owner): Confirm OPT-2 as the chosen option at promotion (promote.py --option OPT-2). This record assesses the assistant's provisional recommendation only; nothing here is binding.
- (Product Owner): Residual of OQ-11/AC-7: a creator who explicitly sets themselves as owner looks the same as the default owner, so that case is round-robin assigned. Accept this, as OQ-11's wording implies, or state otherwise.
- (Tech Lead): How 'owner is still the creator' is tested in before insert (Inferred: CreatedById is not yet set there, so the check is OwnerId against UserInfo.getUserId()); new tests must cover explicit owner kept and default owner assigned.
- (Tech Lead): Locking approach for the single Round_Robin_State__c row (SELECT ... FOR UPDATE or other) so concurrent saves do not read the same position, and its contention at peak volume.
- (Tech Lead): CaseAccountSummaryController_Test.cls:64 inserts a Case with the default owner, so it runs assignment and depends on org Escalation_Agents membership: leave it, set agentPoolOverride, or set an explicit owner.
- (Salesforce Admin): Which case creators beyond Service_Agent and Team_Lead (integration, automated users) create cases with the default owner and so need access to Round_Robin_State__c under user-mode DML.
- (Salesforce Admin): Precedence against case assignment rules or Omni-Channel routing (OQ-10): assignment rules run after triggers and can overwrite the owner set in before insert.
- (Tech Lead): Zero hits in index for Logger: whether to add a project logger for assignment failures, given the apex-no-system-debug rule.

_Generated by write_report.py; the model adds framing, triage reasons and manual-check findings above the tables. The Overlaps section comes from the register and is reported as written._

## Manual checks (references/manual-checks.md)

| Check | Finding | Label |
|---|---|---|
| Order of execution | Case has one trigger, `CaseTrigger`, on before update and after update (`CaseTrigger.trigger:1`). It has one record-triggered flow, `Case_Escalate_Premium`, which runs after save on Update (`Case_Escalate_Premium.flow-meta.xml:59-61`). Neither runs on insert today, so nothing in the repo competes with a new before-insert owner write. Case assignment rules and Omni-Channel are org configuration. Assignment rules run after triggers and can overwrite the owner (OQ-10). | Confirmed (repo); Unverifiable (org rules) |
| Dynamic SOQL | Zero hits for `Database.query(` in `classes/` and `triggers/`. | Confirmed |
| `without sharing` reach | The only `without sharing` class is `LegacyCaseMerge`, and it is not a consumer of any seed term. The assignment classes are `with sharing` (`CaseAssignmentService.cls:10`, `CaseTriggerHandler.cls:4`) and query `WITH USER_MODE` (`CaseAssignmentService.cls:51`, `:62`). Because OPT-2 reads and writes Round_Robin_State__c in user mode, every creator whose case is assigned needs object and field access. | Confirmed (classes); Inferred (access need) |
| Required-field / insert-path impact (re-run for AC-7) | No new required field on Case. Every `new Case(` insert in the repo is in a test. Each of these sets `OwnerId` to a newly inserted user, outside runAs, so the owner differs from the running user and AC-7 keeps it: `CaseAssignmentService_Test.cls:49`, `CaseTriggerHandler_Test.cls:31`, `CaseEscalationService_Test.cls:34-35`, `EscalationNotifier_Test.cls:31`, `CaseAccountSummaryController_Test.cls:33`, `:54`. Only `CaseAccountSummaryController_Test.cls:64` keeps the default owner and is assigned. The other DML on Case-related objects (`CaseEscalationService.cls:85`, `EscalationNotifier.cls:49`) inserts CaseComment and Task, not Case. Zero hits for `createRecord` or Case schema imports under `lwc/`. Production insert paths (UI, Web-to-Case, Email-to-Case, integrations) are not in the repo. | Confirmed (paths); Inferred (AC-7 outcome); Unverifiable (org creators) |
| Managed-package behaviour | No managed-package component is in scope. The index stamp has an empty namespaces list. | Confirmed |

## Top risks

1. **The meaning of "still the creator" at insert.** The check is Inferred to be OwnerId against UserInfo.getUserId(), because CreatedById is not set in before insert. A creator who explicitly names themselves as owner is assigned anyway. Web-to-Case, Email-to-Case and integration creators may never match the check. Owners: Tech Lead (check and tests), Product Owner (accept the self-owner residual), Salesforce Admin (automated creators, OQ-10).
2. **Assignment rules or Omni-Channel overwrite the round-robin owner** after the trigger runs (OQ-10). Unverifiable. Owner: Salesforce Admin.
3. **Case creators without Round_Robin_State__c access** hit a user-mode DML failure that blocks the case save. Owners: Salesforce Admin (who creates cases with the default owner) and Tech Lead (failure handling).
4. **Concurrent saves read the same position**, or lock contention builds on the single state row at peak (OQ-8 volumes are unknown). Owner: Tech Lead.
