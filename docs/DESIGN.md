# AI-Ready Salesforce Repo: Design

Oct 29, 2026 · @Gaurav

## Premise and principles

The framework exists to make Salesforce metadata legible to an AI assistant without letting the assistant touch an org, invent a field, or leak a record. Everything a build squad wants from it (impact analysis, discovery packs, PR review, test design, wiki pages) is a consumer of that one capability. It is built and shipped as a versioned product with an owner, a changelog and regression tests, not as a folder of prompts that squads copy and edit.

Six rules it never breaks:

1. **The checkout is the only source of truth.** Knowledge files are leads to re-verify. Anything countable is computed from the repo at a stated commit, never typed into a file.
2. **Deterministic before probabilistic.** If a script can do a check (existence of an API name, a count, a secret pattern, a manifest diff), a script does it and the model interprets the result. The model is reserved for judgement: scope, meaning, risk.
3. **Enforcement lives in the layer that runs everywhere.** Hooks and deny rules sit in project settings so every agent, skill and direct invocation inherits them. A rule written only in prose is a request.
4. **Nothing from an org enters git.** Exports, inputs and generated reports are git-ignored by path and scanned pre-commit. Fixtures are synthetic.
5. **Every claim carries evidence and a label.** `path:line` or "zero hits for pattern X", labelled Confirmed, Inferred or Unverifiable under one taxonomy for all squads.
6. **The assistant never approves, deploys, pushes or decides.** It produces evidence, options and open decisions with an owner role. Humans act.

The design assumes two AI tools (Claude Code and GitHub Copilot), Windows and macOS laptops, 6–10 squads of about six people, and a single Salesforce repo per programme with managed packages (nCino, FSC or similar) alongside custom metadata.

## Architecture

&#91;embedded content: architecture · 5 layers inside one control plane\]

Each layer only reads downward. Skills never grep the checkout directly; they read the index. Agents never carry facts; they carry a posture and a list of skills. The control plane is not a layer but the boundary every layer runs inside, which is why it is built first.

## Layer 1: the metadata index

The index is the foundation and the first thing built. One stdlib-only Python script (`tools/index/build_index.py`) walks `force-app/`, `pkg-*/` and `manifest/`, and emits `index/metadata.json` plus `index/inventory.json`, stamped with the commit SHA, the script version and the UTC time. Nothing in the index comes from an org; it is a projection of the checkout.

| Output | Contents | Consumed by |
| --- | --- | --- |
| `metadata.json` nodes | Every object, field, record type, class, trigger, LWC, Aura bundle, flow, permission set, custom permission, custom label, named credential, with type, path, API version and managed namespace | All skills: existence checks, type checks, `path:line` evidence |
| `metadata.json` edges | References between nodes found by parsing: SOQL field use in Apex, `@AuraEnabled` consumers, flow element references, permission-set field grants, LWC imports | Story impact (hop expansion), PR reference check (consumers of a changed field) |
| `inventory.json` | Counts and distributions: classes by API version, flows by process type, Aura vs LWC, `without sharing` classes, Remote Site vs Named Credential, report types, FlexiPages | Release impact baseline, knowledge-file lint (no stored counts), dashboards |
| `stamp` block | `commit`, `indexVersion`, `builtAt`, `namespaces[]` | Every report cites it; staleness is decided by comparing stamps, never by judgement |

Rules for the index:

- Parsing is by file type with deliberately narrow regexes and XML parsing; no fuzzy matching. A false negative is reported as "zero hits for pattern X" and is still evidence.
- Every `path` and `path:line` in the index is relative to the repo root (the git checkout's top level), whatever `--root` was, so evidence opens from the checkout as cited. `tools/index/test_index.py` proves it on the fixtures.
- Managed-package metadata is indexed from `pkg-*/` and from a committed `namespaces.json` list; package internals the repo does not hold are marked Unverifiable, not guessed.
- The index is rebuilt in CI on every PR and committed artefacts are never trusted: a skill that finds the stamp's commit does not match `HEAD` rebuilds before proceeding.
- Query helpers (`tools/index/query.py`) answer the questions skills ask: `consumers(apiName, hops)`, `exists(apiName)`, `type(apiName)`, `below_api_floor(n)`. Skills call these, not `grep`.

## Layer 2: the control plane

The control plane is built and tested before the first skill, because every later layer assumes it. It has five parts, each enforced by a mechanism rather than by text.

| Part | Mechanism | What it stops |
| --- | --- | --- |
| Offline guard | PreToolUse hook on `Bash`, `Write`, `Edit` in `.claude/settings.json`, calling `tools/guard/guard.py` through `guard.cmd` (Windows) and `guard.sh` (Unix). The wrapper exits 2 if no interpreter is found, so a missing Python blocks rather than passes. Mirrored as a Copilot hook in `.github/hooks/`. | `sf`/`sfdx` calls, org logins, `git push`, `sf project deploy`, writes outside `ai-context/` and `index/`, WebFetch to domains not on the allowlist |
| Deny rules | `permissions.deny` patterns in the same settings file for the commands above | Belt and braces: a deny rule applies even when the hook is misconfigured |
| Data boundary | `.gitignore` for `data/`, `ai-context/**/inputs/`, `ai-context/**/*.pptx\|xlsx\|docx`, `index/*.json`; plus `tools/guard/scan_data.py` as a pre-commit hook and a pipeline gate | Org exports, user inputs and generated reports entering git; Salesforce IDs, account-number formats, emails and `LLC_BI__` record names in any committed file |
| Secrets | gitleaks (or the platform's native scanner) pre-commit and in CI | Keys, tokens and credentials in commits |
| Kill switch | One line in `.claude/settings.json` (`"env": {"AI_FRAMEWORK_MODE": "advise"}`) that the guard reads: in `advise` mode every write and commit is blocked and the model is told to output recommendations only | Programme-wide pause in minutes if a skill misbehaves, without touching squads' machines |

The control plane ships with its own test: `tools/guard/test_guard.py` feeds synthetic tool calls (an `sf org login`, a write to `force-app/`, a fetch to a blog) and asserts exit code 2 on each. CI runs it on a Linux and a Windows agent on every PR, and onboarding runs it once on each laptop.

## Layer 3: context tiers

Three tiers, one source tree. The `.claude/` and `.github/` trees are build outputs of `framework/`, generated by `tools/build/render.py`, and CI fails when either diverges from its generated form. Squads edit `framework/`; nobody edits the outputs.

| Tier | Source | Rendered to | Loaded | Owned by |
| --- | --- | --- | --- | --- |
| Rules (always true for this codebase) | `framework/rules/*.md` with a `scope` front-matter (`**` or a glob) | `CLAUDE.md` imports, `.github/instructions/*.instructions.md` with `applyTo` set from `scope` | Always in Claude Code; by glob in Copilot, so rules that must apply everywhere use `scope: "**"` | Framework guild |
| Facts (true now, may drift) | `framework/knowledge/<topic>.md` with `owner`, `last_verified`, `verified_by` front-matter | `.claude/knowledge/` and `.github/knowledge/`, plus a generated `README.md` index | On demand, by the skill or agent that names the topic | The named owner; CODEOWNERS enforces review |
| Memory (personal) | Each tool's own store | Never rendered, never shared | Only by its user | Its user |

Rules that keep the tiers honest:

- A fact file may contain rules, patterns, gotchas and decisions. It may not contain a count, a version number or a list of API names; `tools/build/lint_knowledge.py` rejects those and points to the index.
- Every fact file states its evidence method (`verified_by: xml-parse | deploy-error | index-query | org-export`). `org-export` entries name the export's date, never its contents.
- The evidence taxonomy (Confirmed, Inferred, Unverifiable) and the output-path convention (`ai-context/<work-item-id>-<slug>/`) are rules with `scope: "**"`, so every tool and every squad uses the same labels and folders.
- Promotion from personal memory to a fact file is a PR that must carry `path:line` evidence or be labelled `promoted, unverified`. There is no seed-memory step; agents read fact files on demand, so a personal copy has nothing to add and something to drift.

## Layer 4: skills

A skill is a thin interpreter over the index: it asks the query helpers for facts, applies the methodology, and writes a report with evidence. It never counts, never greps, and never fetches outside the allowlist.

Every skill has the same anatomy, enforced by `tools/build/lint_skill.py`:

| File | Purpose | Rule |
| --- | --- | --- |
| `SKILL.md` | Front-matter (`name`, `description` ≤ 200 chars stating what, when, and not-for) plus the method | Description is the routing signal; detail lives in the body, never the description |
| `references/input-checklist.md` | Required and optional inputs, what each unlocks, what is recorded as unknown when missing | Ask once, continue with unknowns, cap confidence |
| `references/*.md` | Domain detail, taxonomies, output templates | Loaded only when the method points to them |
| `scripts/*.py` | Anything deterministic: queries, counts, docx/pptx/xlsx builders | stdlib only; `--version` flag; runs on Windows via `py -3` |
| `evals/cases/*.json` and `evals/expected/*` | Three to five synthetic inputs with expected outputs | Required to merge; run with variance (N=5) |

The first two skills, in order:

1. **story-impact.** Input: a work item (story, feature, defect) as text. Method: seed terms from the taxonomy, `consumers()` to two hops, triage with recorded drop reasons, classify each hit (layer, ownership, change type, impact, confidence), write `ai-context/<id>-<slug>/impact.md` and the RICEFW workbook. This is the skill that proves the index and pays back first.
2. **pr-reference-check.** Input: a diff. Method: extract every API name referenced in changed files, `exists()` and `type()` against the index, report invented names and type mismatches with `path:line`. Deterministic checks (secrets, manifest completeness, naming, debug statements) are not in this skill; they are CI steps the skill links to.

Then, by demand and only once the first two are stable on one squad: release-impact (reads `inventory.json` against release notes), discovery-pack, test-case-design, wiki-page. Each is a consumer of the same index and the same evidence taxonomy, so each is mostly method and templates.

Evals run on every PR touching `framework/skills/`. A case passes when the deterministic assertions hold on all five runs (every cited `path:line` exists, no banned phrases, evidence labels on every claim) and the rubric score is at or above the committed threshold on at least four.

## Layer 5: agents

An agent is justified only when a workflow needs a posture that a single skill cannot carry: a fixed tool set, a fixed set of skills, and a fixed list of things it must refuse. Three are enough for most programmes; a fourth needs a written reason.

| Agent | Posture | Skills | Must refuse |
| --- | --- | --- | --- |
| `analyst` | Read-only on the build, offline, writes only to `ai-context/` | story-impact, release-impact | Any org call, any write outside `ai-context/`, any recommendation phrased as a decision |
| `reviewer` | Read-only, offline, no writes at all | pr-reference-check, test-quality judgement | Approving, voting, editing code, reformatting |
| `discovery-lead` | Read-only on the build, offline, writes only to `ai-context/` | discovery-pack, wiki-page, test-case-design | Writing code, committing, estimating in points |

Agent files contain a posture and a skill table, nothing else: no persona prose, no domain facts, no counts. Everything an agent knows about the org it reads from fact files on demand.

Agent evals assert on trajectory, from the tool-call log the harness emits:

- **Must call:** the fact README before any claim; `query.py` before any count; the input checklist before asking the user anything.
- **Must not call:** `sf`, `sfdx`, `git push`, any write under `force-app/`, any fetch off the allowlist.
- **Refusal cases:** "log into UAT and check" produces a hook block (exit 2 in the log) and an explicit refusal in the output; "just approve it" produces "ready for human review" and no vote.
- **Output assertions:** the same deterministic checks as the skill evals, since an agent's output is a skill's output.

Runner: `tools/evals/run_agent.py` invokes the agent headless with a fixture repo checked out, captures the log, and applies the assertions. If the framework is packaged as a plugin, `claude plugin eval` can replace the runner; the assertions stay the same.

## Packaging and operating model

The framework is a versioned plugin, not a set of files squads copy. A squad pins a version in its repo; the guild cuts releases with a changelog; a rollback is a version bump down. That one decision removes forks, lets evals gate releases, and gives the kill switch a single place to live.

| Element | Design |
| --- | --- |
| Versioning | Semantic. Patch = fact or template changes; minor = new skill or new eval cases; major = a change to the evidence taxonomy, output paths or control plane. Squads must be on the current major. |
| Ownership | A guild of two or three people drawn from different squads, named in CODEOWNERS for `framework/`, `tools/` and the rendered trees. Every PR into those paths needs one guild reviewer. |
| Contradiction protocol | When a squad's finding contradicts a fact file: PR records both claims with evidence, the file's owner arbitrates within the sprint, the superseded claim stays as a dated correction with the reason. The index settles anything countable automatically. |
| Cadence | Fortnightly, 30 minutes, rotating chair: stale files (over 90 days), failed evals, open contradictions, skills proposed. Monthly: a one-page health note to squad leads with eval pass rates and usage. |
| Onboarding | Fifteen minutes per person: install and pin, run `tools/guard/test_guard.py` on the laptop, run one golden eval, read the precedence rule, know the guild. A squad is not onboarded until every member has passed the guard test. |
| Decommission | Any skill with no use in two sprints and no owner is moved to `framework/attic/` and removed from the render. The index and control plane are never retired while the repo exists. |

What stays out: seed-memory (pointers only, no copies), org facts in agents or skills, any check a script could do, any output path other than `ai-context/`, and any automation that casts a vote, deploys or pushes.

## Build order

&#91;embedded content: build order · 8 weeks, 3 gates\]

The index and control plane are built together in the first fortnight because the first skill needs both. Gate 2 is the one that matters: no second squad, no second skill in anger, until the pilot squad has used story-impact on real work for two weeks and the evals pass on every run. Release-impact, discovery and the rest come after v1.0, by demand, each as a consumer of the same index.

## Example repo

`ai-ready-sf-repo.zip` (delivered in the conversation) is a working skeleton of this design: 86 files, stdlib Python only, no network access needed. On the included synthetic fixtures every check passes: every guard case blocks or allows as specified (including the wrapper failing closed with no Python on PATH), the data scan is clean, the lint passes, the rendered trees match their source, the index finds all five consumers of `Account.Risk_Rating__c` across two hops (permission set, flow, two Apex classes, one LWC), the skill eval passes on a good report and fails on one with a hallucinated path and a banned phrase, and the agent trajectory eval passes on a sample log that includes a blocked `sf org login`.

| Path | What it is | Why it exists |
| --- | --- | --- |
| `framework/` | The one source tree squads edit: `rules/`, `knowledge/`, `skills/`, `agents/` | Single source of truth; CODEOWNERS puts the guild on every change |
| `tools/index/build_index.py` | Walks `force-app/` and `pkg-*/`, emits `metadata.json` (nodes, edges) and `inventory.json` (counts) stamped with commit SHA, version and time | Layer 1; the thing every skill reads instead of grepping |
| `tools/index/test_index.py` | Builds the index on the fixtures and checks every node path and `path:line` opens from the repo root | Evidence the skill evals and reviewers can follow without knowing where the index was built |
| `tools/index/query.py` | `exists`, `type`, `consumers --hops`, `below-api-floor`, `stamp`, `check-stale` (exit 3 when the index commit is not HEAD) | Skills call this; zero hits are reported as evidence |
| `tools/guard/guard.py` + `guard.sh` + `guard.cmd` | PreToolUse hook: blocks `sf`/`sfdx`, `git push`, `curl`, writes outside `ai-context/` (paths resolved through `..` and symlinks first, so neither can escape), fetches off the allowlist; honours `AI_FRAMEWORK_MODE=advise` | Layer 2; the wrappers exit 2 when no interpreter is found so the guard fails closed |
| `tools/guard/test_guard.py` | Synthetic hook payloads with required exit codes, plus a run with no Python on PATH (must exit 2) and a throwaway repo with symlinks out of `ai-context/` (must be blocked) | Proves the control on each OS in CI and on each laptop at onboarding |
| `tools/guard/scan_data.py` | Regex scan for Salesforce IDs, NZ account and IRD formats, emails, credentialed URLs, session IDs, managed record names; pre-commit and CI | The data boundary as a control, not a request |
| `tools/build/render.py` | Renders `CLAUDE.md`, `.github/instructions/*` (with `applyTo` from `scope`), both knowledge trees, a generated knowledge index with a computed "Used by" column, both skill trees (minus evals), both agent trees; `--check` fails CI on drift | One source tree, two generated outputs |
| `tools/build/lint.py` | Knowledge: owner, date, method, no stored counts, staleness; skills: description ≤ 200 chars with when/not-for, input checklist, ≥ 3 eval cases; agents: tools listed, no persona prose | The multi-squad hygiene rules as code |
| `tools/evals/run_skill.py` | Output assertions: references present, labels on every claim, banned phrases absent, verdict in set, every cited `path:line` exists; pass only if every run passes | Skill regression and variance, harness-independent |
| `tools/evals/run_agent.py` | Trajectory assertions over a JSONL tool-call log: must-call, must-not-call, must-block | Agent regression; works with any harness that logs tool calls |
| `framework/skills/story-impact/` | SKILL.md, input checklist, seed-term method, manual checks, `write_report.py`, three eval cases | The first skill, built as the template for the rest |
| `framework/skills/pr-reference-check/` | SKILL.md, input checklist, `extract_refs.py` (diff against the PR's target branch), three eval cases with diff fixtures | The second skill; CI does the deterministic review checks |
| `framework/agents/` | `analyst`, `reviewer`, `discovery-lead`: posture plus skill table only; `evals/analyst.json` and a sample run log | Layer 5, kept to three |
| `.claude/settings.json` | Project hooks on every write and fetch tool, deny rules, the kill-switch env var | Enforcement in the layer that runs everywhere |
| `.github/workflows/framework-ci.yml` | Matrix on Ubuntu and Windows: guard test, data scan, lint, render check, index build, agent eval; gitleaks job | Everything above, gated on every PR |
| `fixtures/` | Synthetic Account fields, Apex (one at API 45 and `without sharing`), a flow, a permission set, an LWC, three diff patches | Evals and CI never see real metadata |

What the skeleton does not yet include, by design: a release-impact skill, docx and pptx builders, the Copilot hook registration (a README placeholder marks the gap), and a plugin manifest. Each is a consumer of what is here and lands after Gate 2.
