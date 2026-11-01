# Story: DEMO-202 round-robin-assignment

Status: confirmed. Confirmed by: Product Owner. Squad: Service Ops. Seeds: `Case`, `CaseAssignmentService`, `CaseTrigger`, `CaseTriggerHandler`.

- Persona: Service Ops case manager who distributes cases to agents (Product Owner, OQ-1)
- Goal: Assign each newly created case an owner from the agent pool in turn
- Benefit: Even workload across agents, with no manual triage (Product Owner, OQ-2)

## Acceptance criteria

| AC | Given | When | Then | Examples | Source |
|---|---|---|---|---|---|
| AC-1 | The agent pool holds 2 active users, "Agent A" and "Agent B" | A user creates 2 cases in one save | The 2 cases are owned by 2 different agents from the pool. | Pool: "Agent A", "Agent B". Cases "Synthetic Case 1" and "Synthetic Case 2" created together. Owners: "Agent A" for one case, "Agent B" for the other. | stated |
| AC-2 | The agent pool holds 2 active users, "Agent A" and "Agent B", and the last case assigned went to "Agent A" | A user creates 1 case in a later, separate save | The case is owned by "Agent B". | Save 1 creates "Synthetic Case 10", owned by "Agent A". Save 2 creates "Synthetic Case 11", owned by "Agent B". | assistant-proposed |
| AC-3 | The agent pool holds 2 active users, "Agent A" and "Agent B", with no prior assignments | A data load creates 200 cases in one transaction | Each of the 2 agents owns 100 of the 200 cases. | 200 cases "Synthetic Bulk 1" to "Synthetic Bulk 200" loaded together. "Agent A" owns 100. "Agent B" owns 100. | edge-case |
| AC-4 | The agent pool holds active user "Agent A" and inactive user "Agent C" | A user creates 3 cases in one save | No case is owned by "Agent C". | Cases "Synthetic Case 21" to "Synthetic Case 23" created together. All 3 owned by "Agent A". | assistant-proposed |
| AC-5 | The agent pool holds only inactive user "Agent C" | A user creates 1 case | The case is saved with its default owner. | "Synthetic Case 31" created by "Creator X" with no active pool member. Owner stays "Creator X" and no error is shown. | stated |
| AC-6 | The agent pool holds 2 active users, "Agent A" and "Agent B" | A user creates 2 cases of record type "Premium_Support" in one save | The 2 cases are owned by 2 different agents from the pool. | "Synthetic Premium 1" and "Synthetic Premium 2" created together. Owners: "Agent A" for one case, "Agent B" for the other. | edge-case |
| AC-7 | The agent pool holds 2 active users, "Agent A" and "Agent B" | "Creator X" creates 1 case with owner set to "Agent Z" | The case is owned by "Agent Z". | "Synthetic Case 41" created by "Creator X" with owner "Agent Z". Owner stays "Agent Z". | stated |

## Edge cases

| EC | Category | Component | Detail | Evidence | Confidence | Criterion |
|---|---|---|---|---|---|---|
| EC-1 | automation | `Case` | trigger CaseTrigger (status not in index) | `demo/org/force-app/main/default/triggers/CaseTrigger.trigger:1` | Confirmed | none: CaseTrigger runs on before update and after update only (CaseTrigger.trigger:1), so assignment at creation needs an insert context; the update re-assignment stays unchanged (OQ-3). |
| EC-2 | bulk | `Case` | a bulk change of 200 records or more | `demo/org/force-app/main/default/triggers/CaseTrigger.trigger:1` | Confirmed | AC-3 |
| EC-3 | org-only | `Case` | sharing settings and real data volumes are org configuration, not in this repo | none | Unverifiable | none: Assignee visibility and real volumes cannot be seen in the repo; raised for the Salesforce Admin as OQ-8. |
| EC-4 | record-type | `Case` | record type Case.Premium_Support | `demo/org/force-app/main/default/objects/Case/recordTypes/Premium_Support.recordType-meta.xml:2` | Confirmed | AC-6 |

## Dropped seeds

| Category | Component | Detail | Reason |
|---|---|---|---|
| automation | `Case` | flow Case_Escalate_Premium (Active) | Record-triggered on Update with Escalation_Level__c "Level 2" (flow-meta.xml:52-61) and only sends a notification; it never sets the owner, so new-case assignment does not meet it (Inferred). |
| automation | `Case` | validation rule Case.Escalation_Needs_Level (active) | Formula reads only IsEscalated and Escalation_Level__c (validationRule-meta.xml:6-12); assignment changes the owner only, so it cannot trip the rule (Inferred). |

## Overlaps with other stories

- none recorded at refinement

## Open questions

| OQ | Question | Owner role | Answer | Deferred | Deferred by |
|---|---|---|---|---|---|
| OQ-1 | The story names no persona. Who asked for this and who uses it: a Service Ops manager, the service agents, or both? | Product Owner | A Service Ops case manager who distributes cases to agents. | no | none |
| OQ-2 | The story states no benefit. What outcome is wanted: even workload, faster first response, less manual triage, or something else? | Product Owner | Even workload across agents, with no manual triage. | no | none |
| OQ-3 | The story says "new cases". Does that mean cases at creation, cases whose Status is "New", or both? The current CaseAssignmentService only re-assigns cases set back to "New" during an update (CaseAssignmentService.cls:4-5, :22). Should that update path stay, and share the same rotation? | Product Owner | Newly created cases only. The existing re-assignment on update stays unchanged. | no | none |
| OQ-4 | Which cases are excluded, if any: by origin (Web, Email, Phone, API or integration-created), by type, or by creator? | Product Owner | None excluded. | no | none |
| OQ-5 | Which users form the agent pool? The current placeholder uses active direct user members of the "Escalation_Agents" queue (CaseAssignmentService.cls:13, :47-65). Is that the pool for all new cases, or is another queue or group wanted? | Product Owner | Active users in the Escalation_Agents queue. | no | none |
| OQ-6 | Does round-robin apply to cases of record type "Premium_Support" as well as other cases, or does Premium Support use its own pool or rule? | Product Owner | Yes, Premium_Support cases join the same rotation. | no | none |
| OQ-7 | What should happen when the agent pool has no active member? Today the placeholder leaves the owner unchanged (CaseAssignmentService.cls:30-31). | Product Owner | The case keeps its default owner, with no error. | no | none |
| OQ-8 | What are the expected case volumes (per day and at peak, including bulk loads), and can each assigned agent see the case under the org's sharing settings? Both are org configuration, not in this repo. | Salesforce Admin | none | yes | Product Owner |
| OQ-9 | Should assignment take agent availability, capacity or skills into account (out of office, open case limits), or is plain rotation enough? | Product Owner | No. Plain rotation; availability, capacity and skills are out of scope for this story. | no | none |
| OQ-10 | Does the org already use case assignment rules, Omni-Channel routing or another tool that sets the owner of new cases? If so, which one wins? This is org configuration, not in this repo. | Salesforce Admin | none | yes | Product Owner |
| OQ-11 | Should round-robin replace an owner set explicitly at creation (by a user, an integration or a test), or only assign cases whose owner is still the default, the creator? | Product Owner | Honour an explicit owner. Round-robin assigns only cases whose owner is still the creator. | no | none |

## Scope

### In scope

- Setting the owner of newly created cases by round-robin across the active users of the Escalation_Agents queue (OQ-3, OQ-5)
- Premium_Support cases join the same rotation (OQ-6)
- Keeping the rotation position between transactions, so the next case goes to the next agent (AC-2)
- Cases created with an explicit owner other than the creator keep that owner (OQ-11)

### Out of scope

- Changing the existing re-assignment of cases set back to "New" on update (OQ-3)
- Availability, capacity or skills-based routing (OQ-9)

### Non-functional

- Volumes, timing and peak load are not stated; no number is assumed (OQ-8)
- Sharing and visibility for assignees is org configuration, not in this repo (OQ-8)

_Rendered by promote.py from the confirmed story.json (status confirmed). The confirmer is recorded in confirmedBy. Overlaps are as recorded at refinement; at refinement every overlap is a watch._
