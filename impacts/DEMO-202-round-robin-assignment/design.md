# Design: DEMO-202 round-robin-assignment

Status: confirmed. Confirmed by: Product Owner. Chosen option: OPT-2. Index commit `01c0744d0f6f`, index version 0.5.0, built 2026-11-01T21:14:07+00:00.

## Options

| Option | Title | Do nothing | Summary | Impact summary |
|---|---|---|---|---|
| OPT-1 | Do nothing | yes | Leave the build as it is. The build does not meet the story: new cases are never assigned and the rotation position is not kept between transactions. | No metadata changes; the story stays unmet. |
| OPT-2 (chosen) | Insert-time assignment in CaseAssignmentService with a stored rotation position | no | Add before insert to CaseTrigger and a BEFORE_INSERT branch in CaseTriggerHandler that calls a new insert entry point on CaseAssignmentService. The entry point reuses agentPool() and reads and writes the last assigned agent on a new rotation-state record, so the next save continues the rotation. It assigns only cases whose OwnerId is still the creator, so an explicit owner is kept (AC-7, OQ-11). | Touches the Case trigger, its handler, the assignment service and both test classes, adds one rotation-state object and field, and grants access to it in two permission sets. |
| OPT-3 | Insert-time assignment that derives the next agent from the latest assigned case | no | Same trigger and handler change as OPT-2, but the new insert entry point finds the owner of the most recently created case owned by a pool member and starts the rotation after that agent, with no new metadata to hold the position. | Touches the Case trigger, its handler, the assignment service and both test classes, with no new metadata. |

## Trade-offs

### OPT-1: Do nothing

| Criterion | Note |
|---|---|
| reuse | Confirmed: CaseTrigger fires on before update and after update only (demo/org/force-app/main/default/triggers/CaseTrigger.trigger:1), so no code runs when a case is created; AC-1, AC-3, AC-4 and AC-6 are not met. |
| reuse | Confirmed: CaseAssignmentService.assign only picks cases moved back to New during an update (demo/org/force-app/main/default/classes/CaseAssignmentService.cls:21-22), and its position restarts every transaction (CaseAssignmentService.cls:7-8, :33), so AC-2 is not met. |

### OPT-2: Insert-time assignment in CaseAssignmentService with a stored rotation position

| Criterion | Note |
|---|---|
| reuse | Confirmed: reuses agentPool(), which already returns active direct users of the Escalation_Agents queue (CaseAssignmentService.cls:42-67, IsActive filter at :62) for AC-4, and the empty-pool return (CaseAssignmentService.cls:30-31) for AC-5. The service has no record-type filter (CaseAssignmentService.cls:18-67), so Premium_Support cases join the rotation (AC-6). The queue itself is in source (demo/org/force-app/main/default/queues/Escalation_Agents.queue-meta.xml:3) but has zero hits in the index, so it is not listed as a component. |
| maintainability | Inferred: assign() calls oldMap.get (CaseAssignmentService.cls:21), which fails when oldMap is null on insert, so insert needs its own entry point and the update path stays as it is (OQ-3); the existing update tests (CaseAssignmentService_Test.cls:72, CaseTriggerHandler_Test.cls:57) must keep passing. The register shows in-flight entries on these components only for DEMO-202 itself (commit 121a920, the older impact record being replaced); no other squad is changing them. |
| security | Inferred: the project rule requires user-mode DML (CaseAssignmentService.cls:51, :62 already query WITH USER_MODE), so every user who creates a case needs read and edit on Round_Robin_State__c. Service_Agent and Team_Lead grant Case create (Service_Agent.permissionset-meta.xml:44-49, Team_Lead.permissionset-meta.xml:44-49) and need the new object access. Integration or other creators outside these permission sets are Unverifiable (org-only; Salesforce Admin, OQ-8). |
| governor-limits | Inferred: per transaction one pool lookup (two queries, CaseAssignmentService.cls:47-62), one read and one write of the state record, none inside a loop, so a 200-case load (AC-3) is spread in one pass. Two saves at the same moment can read the same position unless the state read locks the record (FOR UPDATE); the locking approach is for the Tech Lead to confirm. |
| data-volume | Unverifiable: case volumes and peak bulk loads are org data and were deferred (OQ-8, Salesforce Admin); lock contention on the single state record at peak cannot be judged from the repo. |
| maintainability | Confirmed: zero hits in index for Logger, so there is no project logger to reuse for assignment failures; whether to add one is for the Tech Lead. |

### OPT-3: Insert-time assignment that derives the next agent from the latest assigned case

| Criterion | Note |
|---|---|
| reuse | Confirmed: reuses agentPool() (CaseAssignmentService.cls:42-67) and the handler dispatch (CaseTriggerHandler.cls:13-24) with no new object, field or permission set change. |
| security | Inferred: the class is with sharing and queries WITH USER_MODE (CaseAssignmentService.cls:10, :51, :62), so a creator who cannot see the latest case under the org's sharing settings gets a wrong start position and AC-2 can fail. Sharing is org configuration and Unverifiable (Salesforce Admin, OQ-8). |
| maintainability | Inferred: the latest case owner is also changed by the update-path re-assignment (CaseAssignmentService.cls:34-37) and by manual owner changes, so the derived position drifts from the rotation; behaviour is harder to reason about and to test than a stored position. |
| governor-limits | Inferred: one extra query on Case per transaction, outside any loop; concurrent saves can read the same latest case, the same race as OPT-2 but without a record to lock (Tech Lead). |

## Recommendation

Recommended option: OPT-2 (Insert-time assignment in CaseAssignmentService with a stored rotation position). Recommended by: assistant. Chosen option: OPT-2 (Insert-time assignment in CaseAssignmentService with a stored rotation position), confirmed by Product Owner at promotion.

Reasons:

- Provisional, pending confirmation by a named owner: OPT-2 is the only option that keeps the rotation position between transactions independent of record visibility, which AC-2 needs; OPT-3 depends on the creator seeing the latest case under with sharing and USER_MODE (CaseAssignmentService.cls:10, :51, :62).
- Reuses the existing pool, inactive-user filter and empty-pool behaviour (CaseAssignmentService.cls:30-31, :42-67) for AC-4 and AC-5, and the existing dispatcher (CaseTriggerHandler.cls:13-24), while leaving the update path unchanged per OQ-3.
- A stored state record gives a single row that can be locked for concurrent saves (governor-limits trade-off); the lock approach and the new permission-set access (security trade-off) remain for the Tech Lead and Salesforce Admin to confirm.

## Components

### OPT-1: Do nothing

- none: the do-nothing option changes no metadata

### OPT-2: Insert-time assignment in CaseAssignmentService with a stored rotation position

| Component | Type | Change | Evidence | Confidence |
|---|---|---|---|---|
| `CaseTrigger` | ApexTrigger | modify | `demo/org/force-app/main/default/triggers/CaseTrigger.trigger:1` | Confirmed |
| `CaseTriggerHandler` | ApexClass | modify | `demo/org/force-app/main/default/classes/CaseTriggerHandler.cls:4` | Confirmed |
| `CaseAssignmentService` | ApexClass | modify | `demo/org/force-app/main/default/classes/CaseAssignmentService.cls:10` | Confirmed |
| `CaseAssignmentService_Test` | ApexClass | modify | `demo/org/force-app/main/default/classes/CaseAssignmentService_Test.cls:2` | Confirmed |
| `CaseTriggerHandler_Test` | ApexClass | modify | `demo/org/force-app/main/default/classes/CaseTriggerHandler_Test.cls:2` | Confirmed |
| `Round_Robin_State__c` | CustomObject | new | none | Inferred |
| `Round_Robin_State__c.Last_Assigned_User__c` | CustomField | new | none | Inferred |
| `Service_Agent` | PermissionSet | modify | `demo/org/force-app/main/default/permissionsets/Service_Agent.permissionset-meta.xml:49` | Inferred |
| `Team_Lead` | PermissionSet | modify | `demo/org/force-app/main/default/permissionsets/Team_Lead.permissionset-meta.xml:49` | Inferred |

### OPT-3: Insert-time assignment that derives the next agent from the latest assigned case

| Component | Type | Change | Evidence | Confidence |
|---|---|---|---|---|
| `CaseTrigger` | ApexTrigger | modify | `demo/org/force-app/main/default/triggers/CaseTrigger.trigger:1` | Confirmed |
| `CaseTriggerHandler` | ApexClass | modify | `demo/org/force-app/main/default/classes/CaseTriggerHandler.cls:4` | Confirmed |
| `CaseAssignmentService` | ApexClass | modify | `demo/org/force-app/main/default/classes/CaseAssignmentService.cls:10` | Confirmed |
| `CaseAssignmentService_Test` | ApexClass | modify | `demo/org/force-app/main/default/classes/CaseAssignmentService_Test.cls:2` | Confirmed |
| `CaseTriggerHandler_Test` | ApexClass | modify | `demo/org/force-app/main/default/classes/CaseTriggerHandler_Test.cls:2` | Confirmed |

_Re-rendered by promote.py from the confirmed design.json. The options, trade-offs and reasons are the assistant's; the components are checked against the index; the chosen option and the confirmer are recorded at promotion._
