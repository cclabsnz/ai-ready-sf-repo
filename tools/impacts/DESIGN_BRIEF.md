# Design Brief: Interlocking

Scope: `tools/impacts/render_register.py` output only (the static register view).

## Concept

A railway interlocking panel. Each Salesforce component is a track section; each story is
a train that claims it. Two trains that both change a section is a conflict (red lamp); a
shared section where at most one story changes it is a watch (amber lamp). The page reads
like a signal-box diagram: what is occupied, by whom, and since which commit. Readers are
tech leads and release owners checking collisions before a sprint starts.

Concepts considered: Concept zero (discarded): dark dashboard with cards and one accent.
Also rejected: a lab-notebook ledger (too close to the "paper ledger" AI-tell) and a
departure-board split-flap (needs scripts). Chosen without owner confirmation; the owner
can override.

## Boldness

Spent on the shared-components table: a full-height signal-lamp stripe at the left of each
row and the story "trains" drawn as linked claim tokens. Everything else stays quiet.

## Tokens

| Token | Light | Dark |
|---|---|---|
| `--panel` (ground) | `#E4E7E3` | `#161A19` |
| `--plate` (raised surface) | `#F4F5F2` | `#1F2422` |
| `--ink` | `#121614` | `#E6E9E5` |
| `--muted` | `#4F5753` | `#9AA39E` |
| `--rule` | `#C3C8C2` | `#343B38` |
| `--red` (conflict lamp) | `#B3261E` | `#F2675C` |
| `--amber` (watch lamp) | `#8A5A00` | `#E3A93B` |

- Display: `"DIN Alternate", Bahnschrift, "DIN 2014", "Arial Narrow", sans-serif` (DIN is
  the railway-signage face). Body: `"Avenir Next", "Segoe UI", "Helvetica Neue", Arial,
  sans-serif`. Mono for API names and commits: `ui-monospace, "SF Mono", Menlo, Consolas, monospace`.
- Scale: commit/title `clamp(2.25rem, 7vw, 4.5rem)`, section heads `1.25rem`, body `0.9375rem`,
  labels `0.75rem` uppercase mono. Tabular figures everywhere.
- Radius 2px (enamel plates, not pills). Borders 1px `--rule`. No shadows.

## Wireframe

```
IMPACT REGISTER                                   HEAD abc1234
Track occupancy at HEAD                   [2 conflict] [3 watch] [4 stories]
------------------------------------------------------------------------------
Shared components
|R| Account_Trigger    ApexTrigger   [DEMO-1 modify]==[DEMO-2 delete]
|A| Case.Status__c     CustomField   [DEMO-1 review]==[DEMO-3 modify]
------------------------------------------------------------------------------
Stories on record
DEMO-1  slug  squad  in-flight  confirmed by Tech Lead   7 components
  decisions...
------------------------------------------------------------------------------
Files that failed validation (only when present)
```

## Motion

None. The page is static, with no scripts (project brief overrides design-dna's
technical-signature and motion rules). No CSS animation either.

## Precedence notes

Project brief > design-dna: no external URLs, so no web fonts (local stacks only), no
scripts, no technical signature.

## What this concept is NOT

- Not a card grid or KPI-tile dashboard.
- Not traffic-light emoji or icon fonts; lamps are plain CSS bars with text labels.
- Not colour-only: every lamp also carries the word "conflict" or "watch".
- Not a decision tool: the page states findings and owner roles, nothing more.
