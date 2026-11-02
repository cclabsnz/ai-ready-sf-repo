# Build package: DEMO-202 round-robin-assignment

Assembled by tools/impacts/package.py from the confirmed story, design and impact. The agent builds from build-package.json; this file is the readable copy.

## Criteria

### AC-1

- Given: The agent pool holds 2 active users, "Agent A" and "Agent B"
- When: A user creates 2 cases in one save
- Then: The 2 cases are owned by 2 different agents from the pool.
- Examples: Pool: "Agent A", "Agent B". Cases "Synthetic Case 1" and "Synthetic Case 2" created together. Owners: "Agent A" for one case, "Agent B" for the other.

### AC-2

- Given: The agent pool holds 2 active users, "Agent A" and "Agent B", and the last case assigned went to "Agent A"
- When: A user creates 1 case in a later, separate save
- Then: The case is owned by "Agent B".
- Examples: Save 1 creates "Synthetic Case 10", owned by "Agent A". Save 2 creates "Synthetic Case 11", owned by "Agent B".

### AC-3

- Given: The agent pool holds 2 active users, "Agent A" and "Agent B", with no prior assignments
- When: A data load creates 200 cases in one transaction
- Then: Each of the 2 agents owns 100 of the 200 cases.
- Examples: 200 cases "Synthetic Bulk 1" to "Synthetic Bulk 200" loaded together. "Agent A" owns 100. "Agent B" owns 100.

### AC-4

- Given: The agent pool holds active user "Agent A" and inactive user "Agent C"
- When: A user creates 3 cases in one save
- Then: No case is owned by "Agent C".
- Examples: Cases "Synthetic Case 21" to "Synthetic Case 23" created together. All 3 owned by "Agent A".

### AC-5

- Given: The agent pool holds only inactive user "Agent C"
- When: A user creates 1 case
- Then: The case is saved with its default owner.
- Examples: "Synthetic Case 31" created by "Creator X" with no active pool member. Owner stays "Creator X" and no error is shown.

### AC-6

- Given: The agent pool holds 2 active users, "Agent A" and "Agent B"
- When: A user creates 2 cases of record type "Premium_Support" in one save
- Then: The 2 cases are owned by 2 different agents from the pool.
- Examples: "Synthetic Premium 1" and "Synthetic Premium 2" created together. Owners: "Agent A" for one case, "Agent B" for the other.

### AC-7

- Given: The agent pool holds 2 active users, "Agent A" and "Agent B"
- When: "Creator X" creates 1 case with owner set to "Agent Z"
- Then: The case is owned by "Agent Z".
- Examples: "Synthetic Case 41" created by "Creator X" with owner "Agent Z". Owner stays "Agent Z".

### EC-1

- Given: Case
- When: automation
- Then: trigger CaseTrigger (status not in index)
- Examples: demo/org/force-app/main/default/triggers/CaseTrigger.trigger:1

## Design

Chosen option: OPT-2

Reasons:
- Provisional, pending confirmation by a named owner: OPT-2 is the only option that keeps the rotation position between transactions independent of record visibility, which AC-2 needs; OPT-3 depends on the creator seeing the latest case under with sharing and USER_MODE (CaseAssignmentService.cls:10, :51, :62).
- Reuses the existing pool, inactive-user filter and empty-pool behaviour (CaseAssignmentService.cls:30-31, :42-67) for AC-4 and AC-5, and the existing dispatcher (CaseTriggerHandler.cls:13-24), while leaving the update path unchanged per OQ-3.
- A stored state record gives a single row that can be locked for concurrent saves (governor-limits trade-off); the lock approach and the new permission-set access (security trade-off) remain for the Tech Lead and Salesforce Admin to confirm.

Options not chosen:
- OPT-1: Do nothing
- OPT-3: Insert-time assignment that derives the next agent from the latest assigned case

## Scope

### Modify

- `demo/org/force-app/main/default/classes/CaseAssignmentService.cls`
- `demo/org/force-app/main/default/classes/CaseAssignmentService.cls-meta.xml`
- `demo/org/force-app/main/default/classes/CaseTriggerHandler.cls`
- `demo/org/force-app/main/default/classes/CaseTriggerHandler.cls-meta.xml`
- `demo/org/force-app/main/default/permissionsets/Service_Agent.permissionset-meta.xml`
- `demo/org/force-app/main/default/permissionsets/Team_Lead.permissionset-meta.xml`
- `demo/org/force-app/main/default/triggers/CaseTrigger.trigger`
- `demo/org/force-app/main/default/triggers/CaseTrigger.trigger-meta.xml`

### Create

- `demo/org/force-app/main/default/objects/Round_Robin_State__c/Round_Robin_State__c.object-meta.xml` (CustomObject Round_Robin_State__c)
- `demo/org/force-app/main/default/objects/Round_Robin_State__c/fields/Last_Assigned_User__c.field-meta.xml` (CustomField Round_Robin_State__c.Last_Assigned_User__c)

### Tests

- `demo/org/force-app/main/default/classes/CaseAssignmentService_Test.cls` (exists)
- `demo/org/force-app/main/default/classes/CaseAssignmentService_Test.cls-meta.xml` (exists)
- `demo/org/force-app/main/default/classes/CaseTriggerHandler_Test.cls` (exists)
- `demo/org/force-app/main/default/classes/CaseTriggerHandler_Test.cls-meta.xml` (exists)

## Rules

- apex-sharing: `python3 tools/code/check_rules.py`
- apex-user-mode: `python3 tools/code/check_rules.py`
- apex-no-soql-dml-in-loop: `python3 tools/code/check_rules.py`
- apex-no-system-debug: `python3 tools/code/check_rules.py`
- apex-no-seealldata: `python3 tools/code/check_rules.py`
- apex-no-assert-true: `python3 tools/code/check_rules.py`
- apex-test-naming: `python3 tools/code/check_rules.py`

## Done

Each command exits 0, in this order:

1. `python3 tools/code/check_trace.py --skeletons DEMO-202`
2. `python3 tools/code/check_rules.py --from-config`
3. `python3 tools/code/check_trace.py DEMO-202`

## Provenance

- story.json sha1: ecec7ad1395bab36f3573805c3cba20c61347696
- design.json sha1: 81f3dd23725fcf64a14770c7d03380ca60534d35
- impact.json sha1: 990e2f2ad51997bf61b944af615e827b68eb991c
- Index stamp commit: 01c0744d0f6ffc08b769c0bb102497ccd0c519c2
- Framework version: 0.1.0
- Confirmed by: story Product Owner; design Product Owner; impact Product Owner
