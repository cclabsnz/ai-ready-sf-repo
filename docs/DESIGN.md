# AI-Ready Salesforce Repo: Design

Oct 29, 2026 · @Gaurav

## Premise and principles

The framework exists to make Salesforce metadata legible to an AI assistant without letting the assistant touch an org, invent a field, or leak a record. Everything a build squad wants from it (impact analysis, discovery packs, PR review, test design, wiki pages) is a consumer of that one capability. It is built and shipped as a versioned product with an owner, a changelog and regression tests, not as a folder of prompts that squads copy and edit. On org access, the stance is: the assistant gets no org access unless a programme opts in to a read-only level against named non-production orgs; the guard blocks the assistant from logging in, deploying, writing data or running code in an org (a laptop control, best effort; see "What the guard guarantees").

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
| Offline guard | PreToolUse hook on every tool (matcher `.*`) in `.claude/settings.json`, registered as `sh "$CLAUDE_PROJECT_DIR/tools/guard/guard.sh"`, which runs `tools/guard/guard.py` with `-I`. The wrapper exits 2 if no interpreter is found or `guard.py` is unreadable, and maps any other exit code to 2, so a missing Python blocks rather than passes. `guard.cmd` is a Windows fallback, not the registered command. Rules live in `tools/guard/policy.json`; the active mode picks the allowed write paths, the Bash allowlist and the Salesforce CLI level. Mirrored as a Copilot hook in `.github/hooks/`. | `sfdx`, org logins and every other org-changing `sf` command, pushes, `curl`, `wget`, writes outside the mode's paths, Bash outside the mode's allowlist, unquoted globs that could expand to an option, WebFetch to domains not on the allowlist, MCP tools that write (and every MCP tool in `advise`), and any write or non-read-only Bash while the tripwire is tripped |
| Deny rules | Static `permissions.deny` patterns in the same settings file for the always-blocked Salesforce CLI command prefixes, `sfdx`, `git push`, `curl`, `wget` and `WebFetch` | Belt and braces: a deny rule applies even when the hook cannot start. They do not cover Write/Edit paths, colon-style ids, the `force` topic or `--flags-dir`; those depend on the hook |
| Data boundary | `.gitignore` for `data/`, `ai-context/**/inputs/`, `ai-context/**/*.pptx\|xlsx\|docx`, `index/*.json`; plus `tools/guard/scan_data.py` as a pre-commit hook and a pipeline gate | Org exports, user inputs and generated reports entering git; Salesforce IDs, account-number formats, emails and `LLC_BI__` record names in any committed file |
| Secrets | gitleaks (or the platform's native scanner) pre-commit and in CI | Keys, tokens and credentials in commits |
| Kill switch | One line in `.claude/settings.json` (`"env": {"AI_FRAMEWORK_MODE": "advise"}`) that the guard reads: in `advise` mode every write is blocked and only read-only Bash runs, and the model is told to output recommendations only. The committed value is the ceiling: committed `advise` always wins over any local override | Programme-wide pause in minutes if a skill misbehaves, without touching squads' machines |

The control plane ships with its own test: `tools/guard/test_guard.py` feeds synthetic tool calls (an `sf org login`, a write to `force-app/`, a fetch to a blog) and asserts exit code 2 on each, runs the registered hook command itself, and runs the wrapper with no Python on PATH. CI runs it on a Linux and a Windows agent on every PR, and onboarding runs it once on each laptop.

### Modes

The guard has four modes, set by `AI_FRAMEWORK_MODE`. Committed `.claude/settings.json` holds `normal`. A person may select another mode only for themselves, through a personal git-ignored `.claude/settings.local.json`, and only while the committed value is `normal`. A committed `advise` always wins. A committed `build` or `maintain` is not trusted and is treated as `advise`, as is an unreadable or unknown committed value. An unknown local value blocks.

| Mode | Who | Writes allowed | Bash rule | Salesforce CLI level |
| --- | --- | --- | --- | --- |
| `advise` | Everyone, when the programme pulls the kill switch | None | Read-only commands only (`cat`, `ls`, `grep`, read-only `git`, `find` without actions, `query.py`). Redirects only to `/dev/null` or a file descriptor; no `$`, brace or command substitution | `none` |
| `normal` | The default for every squad member | `ai-context/`, `index/` | Read-only commands plus the framework scripts (index build and query, evals, lint, `test_guard.py`, `scan_data.py`, skill scripts). Every write target the command makes must also be under the mode's write paths | `offline` |
| `build` | A developer, by personal override | Same as `normal`; source writes are scoped to the active story, and no story scope exists yet (WS8), so none are allowed | `normal` plus dev tooling: `git add` and `git commit` (local only), `pnpm exec` prettier, eslint, jest and sfdx-lwc-jest, `pnpm lint`, `pnpm format`, `pnpm test` | `offline` |
| `maintain` | A framework maintainer, by personal override | The framework paths listed under `maintain` in `policy.json` (for example `framework/`, `tools/`, `docs/`, `README.md`), plus `ai-context/` and `index/` | `normal` plus the maintainer allowlist (`maintainer_tools` in `policy.json`): `cp`, `mv`, `mkdir`, `rm`, `touch`, `rmdir`, `sed`, `diff`, `cmp`, `tar` in list mode, `git add` and `git commit`, `pnpm exec` prettier, eslint and jest, and Python scripts under `tools/`, `framework/`, `fixtures/`, `demo/` and `ai-context/` | `offline` |

Outside `advise`, Bash is allowlist-based: a command that is not on the mode's list is blocked, and so is any command whose write targets the guard cannot work out. The framework scripts' own output flags count as write targets: `build_index.py --out` (joined to `--root`, abbreviations included) and `write_report.py`'s `ai-context/<id>-<slug>/` (a `/`, `\` or `..` in `--id` or `--slug`, or a `--root` other than `.`, blocks); `query.py` only prints. Scripts, `pnpm` and the Salesforce CLI run only from the project root, with no `cd` before them. In every mode, including `advise`, an unquoted glob word is blocked when it starts with `-`, when it comes after a `cd`, `pushd` or `popd` on the same line, when it holds an expansion, or when it matches a name starting with `-` in the working directory: the shell would hand such a match to the command as an option (`sort -[o]`, `find .. -delet[e]`, `rg x *` beside a file named `--pre=sh`). Quote the glob (`'*.py'`) to pass it literally. Git is a subcommand allowlist (`status`, `diff`, `log`, `show`, `rev-parse`, `ls-files`, `check-ignore`, `blame`, `branch --show-current`; `add` and `commit` only in `build` and `maintain`); global options such as `-C` and `-c` are refused. Pushes, `git commit --amend` (and any prefix of it git accepts, such as `--amen`), `curl`, `wget`, `ssh`, `scp` and `sfdx` are blocked in every mode. A `git commit` whose message holds `$`, braces or a substitution is blocked because the guard cannot read it; the block message says to write the message to a file under `ai-context/` and run `git commit -F ai-context/<file>`. The guard refuses writes to these paths in every mode (a laptop rule, best effort; see Layer 1 below): `tools/guard/`, `.claude/settings.json`, `.claude/settings.local.json`, `.github/workflows/`, `.github/hooks/`, every `CODEOWNERS` file, and `.git/`. Those change by a human-applied patch with a second reviewer, and the human applies and commits the guard files together.

#### Tripwire

The guard compares two things on every write and every non-read-only Bash call. First, `tools/guard`, `.claude/settings.json`, `.github/workflows`, `.github/hooks`, `.github/CODEOWNERS` and `CODEOWNERS` against `HEAD` (the rendered `.github/instructions/` and other generated `.github/` trees are not watched, so a `maintain` render does not trip it) (including untracked files and files hidden with skip-worktree or assume-unchanged). Second, `.git/config`, the files it includes, the hooks directory and any `core.hooksPath` directory against a baseline a human recorded. Adding a remote URL or setting branch tracking does not change the baseline. While either differs, every write and every non-read-only Bash call is blocked in every mode, and when `.git` itself is untrusted every git command is blocked too. The block message names the way out: commit or revert the guard files, or have a human re-baseline. The re-baseline command (`--rebaseline`, run on `tools/guard/guard.py` from a terminal) records the baseline in the git directory; it refuses to run without a terminal, and the hook blocks any Bash line that names the guard script or `--rebaseline`. An `include.path`, `includeIf` path or `core.hooksPath` value containing a quote, backslash, `#` or `;` makes the tripwire fail closed until a human simplifies the line and re-baselines.

#### Salesforce CLI access levels

The Salesforce CLI is limited to local, offline commands by default. Four levels, in order: `none`, `offline`, `org-metadata`, `org-data`. `advise` gets `none`; `normal`, `build` and `maintain` get `offline` (help, version, local generators, `code-analyzer run`, `project convert source`). `org-metadata` adds read-only metadata commands (`sobject describe`, `sobject list`, `org list metadata`, `project retrieve preview`), and `org-data` adds `data query`. `sf org list` is on no level: it lists the locally authenticated org usernames, which the assistant does not need. Raising a level is a one-line change to `sf.mode_level` in `tools/guard/policy.json`, so it needs a reviewed PR, because `tools/guard/` is human-only. An org command must name its org with an org flag whose alias is in `sf.allowed_orgs`, which is empty by default. Never list a production alias. `org-data` puts real org data into the assistant's context and transcripts; opt in knowingly. At every level the guard blocks login, logout and auth; `org display` (it prints tokens), `org create`, `org delete`, `org open`, `org resume`, `org generate password` and `org assign permset`; `sf deploy` and `sf retrieve`, `project deploy`, `project retrieve start` and `project delete` (`project retrieve preview` is allowed at `org-metadata`); `apex run`; every data write, export, bulk or resume command (`data create`, `update`, `upsert`, `delete`, `import`, `export`, `bulk`, `resume`); colon-style command ids and the legacy `force` topic; `--flags-dir`; and the `sfdx` binary. Every Salesforce CLI command must run from the repo root.

### What the guard guarantees

**Layer 1: on the laptop, best effort.** The hook, the deny rules and the tripwire stop the assistant from making ordinary mistakes and make it harder for the assistant to act on a hostile instruction in a file it reads. They are not a boundary against code the assistant can write and then run. Anything the assistant can write and then run can, in principle, defeat a laptop control.

**Layer 2: on the server, the hard guarantee.** CODEOWNERS plus branch protection on `tools/guard/`, `.claude/settings.json`, `.github/` and `CODEOWNERS`, the CI workflow, secret scanning and the data scan, and human review of every PR. Once CODEOWNERS and branch protection are enabled and confirmed (an open item in `HANDOFF.md`), nothing reaches the shared branch without human review, whatever happened on a laptop. Until then this layer is a plan, not a guarantee.

Limits accepted in Layer 1, each with its backstop:

- **Code the assistant runs can do anything.** In `maintain`, a framework or workspace Python script (`python3 tools/x.py`, `python3 ai-context/x.py`); in `build`, `pnpm test`, `pnpm lint` and `pnpm format`, which run `package.json` scripts; jest, which by default discovery runs any test file under the repo root, including files the assistant wrote under `ai-context/`; eslint, which loads formatters from installed packages. Backstop: server-side review. Recommended: a human-owned jest config with `roots: ["<rootDir>/force-app"]` and `<rootDir>/ai-context/` in `testPathIgnorePatterns`.
- **Such code can also reset the tripwire**, for example by committing a tampered guard, policy, settings or CI file and then rewriting `.git/ai-guard-baseline`. Backstop: CODEOWNERS and branch protection on the paths above.
- **Bash write-target checks are pattern-based and incomplete.** They model the common writers (redirects, `tee`, `sed -i`, `cp`, `mv`, `rm` and similar, git) and treat anything they cannot model as unknown, which blocks it. They cannot see writes made inside a program the assistant runs. The server-side layer is the guarantee.
- **If the hook cannot start, the hook cannot block.** A missing `tools/guard/guard.sh` or an unset `CLAUDE_PROJECT_DIR` makes the registered command exit 127, which Claude Code treats as a warning and allows. Backstops: the static `permissions.deny` rules (which cover the always-blocked Salesforce CLI command prefixes, `git push`, `curl`, `wget` and `WebFetch`, but not Write/Edit paths, and not colon-style command ids, the `force` topic or `--flags-dir`, which only the hook catches), a CI test that runs the registered hook command, and review of `.claude/**`, `tools/**` and `.github/**`.
- **Default jest coverage output.** `--coverage` writes `coverage/` at the repo root.
- **Not hashed by the tripwire:** global and system git config (`~/.gitconfig`, `/etc/gitconfig`) and `config.worktree`. They are human-owned and outside every mode's write paths.
- **MCP tools are judged by name.** The hook runs for every tool. Tools in `tools.read_only` in `policy.json` pass in every mode. An MCP tool (`mcp__<server>__<name>`) is blocked in `advise`; in other modes it is blocked when `<name>` contains a write verb (`tools.mcp_write_pattern`: write, edit, create, delete, send, run and similar) and allowed otherwise, so an MCP server that writes under an innocent name is not caught. Any other tool is blocked in `advise` and allowed elsewhere. Backstop: review which MCP servers a programme enables.
- **The guard has a time limit.** The hook times out at 10 seconds, and a timed-out hook may let the call through, so the guard blocks itself ("guard ran out of time; failing closed") 7 seconds after it starts. Each git call it makes gets at most 3 seconds, and a git timeout counts as unverifiable, which blocks. Recursive commands share one budget of 20000 entries per call; past it the command is unknown and blocked.
- **Windows is Inferred, not tested.** Claude Code on Windows is assumed to run hook commands through Git Bash; the documentation could not be checked from the environment this was built in. `guard.cmd` is a documented fallback and its behaviour is Unverifiable until the Windows CI job runs. The first Windows CI run is the check.

Operations a human must know:

- **One-time step after applying the guard patches:** run the re-baseline command from a terminal (see the README). Until then every write and every non-read-only Bash call is blocked.
- **Re-baseline whenever `.git/config` or `.git/hooks/` legitimately change**, for example when installing husky hooks or editing core settings.
- **Every new git worktree needs its own re-baseline.** The baseline lives in each worktree's git directory, so a fresh `git worktree add` blocks writes there until a human runs the re-baseline command from inside it.
- **Commit messages with `$`, braces or a substitution:** write the message to a file under `ai-context/` and run `git commit -F ai-context/<file>`; the guard cannot read such a message on the command line and blocks it.
- **Changes the tripwire watches:** `.github/workflows/`, `.github/hooks/` and CODEOWNERS files, plus `tools/guard/` and `.claude/settings.json`. A `maintain` render that rewrites `.github/instructions/` or the other generated `.github/` trees does not trip it.
- **Bash that mentions the guard script is always blocked**, including `cat`. Read the file with the editor or the Read tool.
- **While the tripwire is tripped,** the block applies in every mode as described above.

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
| `tools/guard/guard.py` + `guard.sh` + `guard.cmd` | PreToolUse hook: reads the mode (advise, normal, build, maintain), blocks `sfdx`, org-changing `sf` commands, pushes, `curl`, writes outside the mode's paths (resolved through `..` and symlinks first, so neither can escape), Bash off the mode's allowlist and fetches off the allowlist; the tripwire blocks writes and non-read-only Bash while guard files or git config differ from `HEAD` or the baseline; the re-baseline flag is human-only | The offline guard of the control plane; `guard.sh` is the registered wrapper and exits 2 when no interpreter is found so the guard fails closed; `guard.cmd` is the Windows fallback |
| `tools/guard/policy.json` | The guard's rules as data: blocked command patterns, the git subcommand allowlist, fetch allowlist, tripwire paths, always-blocked write paths, per-mode write paths and Bash groups, and the Salesforce CLI levels and allowed orgs | Rules change by a reviewed PR without editing code; an unreadable policy blocks |
| `tools/guard/test_guard.py` | Synthetic hook payloads with required exit codes, the registered hook command run as written, a run with no Python on PATH (must exit 2), a throwaway repo with symlinks out of `ai-context/` (must be blocked), and tripwire and mode cases | Proves the control on each OS in CI and on each laptop at onboarding |
| `tools/guard/scan_data.py` | Regex scan for Salesforce IDs, NZ account and IRD formats, emails, credentialed URLs, session IDs, managed record names; pre-commit and CI | The data boundary as a control, not a request |
| `tools/build/render.py` | Renders `CLAUDE.md`, `.github/instructions/*` (with `applyTo` from `scope`), both knowledge trees, a generated knowledge index with a computed "Used by" column, both skill trees (minus evals), both agent trees; `--check` fails CI on drift | One source tree, two generated outputs |
| `tools/build/lint.py` | Knowledge: owner, date, method, no stored counts, staleness; skills: description ≤ 200 chars with when/not-for, input checklist, ≥ 3 eval cases; agents: tools listed, no persona prose | The multi-squad hygiene rules as code |
| `tools/evals/run_skill.py` | Output assertions: references present, labels on every claim, banned phrases absent, verdict in set, every cited `path:line` exists; pass only if every run passes | Skill regression and variance, harness-independent |
| `tools/evals/run_agent.py` | Trajectory assertions over a JSONL tool-call log: must-call, must-not-call, must-block | Agent regression; works with any harness that logs tool calls |
| `framework/skills/story-impact/` | SKILL.md, input checklist, seed-term method, manual checks, `write_report.py`, three eval cases | The first skill, built as the template for the rest |
| `framework/skills/pr-reference-check/` | SKILL.md, input checklist, `extract_refs.py` (diff against the PR's target branch), three eval cases with diff fixtures | The second skill; CI does the deterministic review checks |
| `framework/agents/` | `analyst`, `reviewer`, `discovery-lead`: posture plus skill table only; `evals/analyst.json` and a sample run log | Layer 5, kept to three |
| `.claude/settings.json` | Project hooks on every write and fetch tool, deny rules, the committed mode (`normal`) that doubles as the kill switch | Enforcement in the layer that runs everywhere |
| `.gitattributes` | LF line endings for `*.sh`, `tools/guard/*.json` and `tools/guard/*.py`; CRLF for `*.cmd` | A Windows checkout must not break the shell wrapper or alter the guard files the tripwire compares |
| `.github/workflows/framework-ci.yml` | Matrix on Ubuntu and Windows: guard test, data scan, lint, render check, index build, agent eval; gitleaks job | Everything above, gated on every PR |
| `fixtures/` | Synthetic Account fields, Apex (one at API 45 and `without sharing`), a flow, a permission set, an LWC, three diff patches | Evals and CI never see real metadata |

What the skeleton does not yet include, by design: a release-impact skill, docx and pptx builders, the Copilot hook registration (a README placeholder marks the gap), and a plugin manifest. Each is a consumer of what is here and lands after Gate 2.
