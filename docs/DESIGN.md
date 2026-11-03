# AI-Ready Salesforce Repo: Design

## Premise and principles

The framework exists to make Salesforce metadata legible to an AI assistant without letting the assistant touch an org, invent a field, or leak a record. Everything a build squad wants from it (impact analysis, discovery packs, PR review, test design, wiki pages) is a consumer of that one capability. It is built and shipped as a versioned product with an owner, a changelog and regression tests, not as a folder of prompts that squads copy and edit. On org access, the stance is: the assistant gets no org access unless a programme opts in to a read-only level against named non-production orgs; the guard blocks the assistant from logging in, deploying, writing data or running code in an org (a laptop control, best effort; see "What the guard guarantees").

Six rules it never breaks:

1. **The checkout is the only source of truth.** Knowledge files are leads to re-verify. Anything countable is computed from the repo at a stated commit, never typed into a file.
2. **Deterministic before probabilistic.** If a script can do a check (existence of an API name, a count, a secret pattern, a manifest diff), a script does it and the model interprets the result. The model is reserved for judgement: scope, meaning, risk.
3. **Enforcement lives in the layer that runs everywhere.** Hooks and deny rules sit in project settings so every agent, skill and direct invocation inherits them. A rule written only in prose is a request.
4. **Nothing from an org enters git.** Exports, inputs and generated reports are git-ignored by path (`data/` and the whole `/ai-context/` workspace; see "Data boundary") and scanned pre-commit. Impact records and refined stories a human promotes into `impacts/` are the only assistant output meant for git. Fixtures are synthetic.
5. **Every claim carries evidence and a label.** `path:line` or "zero hits for pattern X", labelled Confirmed, Inferred or Unverifiable under one taxonomy for all squads.
6. **The assistant may recommend and proceed provisionally; it never approves, deploys, pushes or makes a binding decision. Every recommendation is confirmed by a named owner before it becomes a committed impact or a code scope.** It produces evidence, options and open decisions with an owner role. Humans confirm and act.

The design assumes two AI tools (Claude Code and GitHub Copilot), Windows and macOS laptops, 6–10 squads of about six people, and a single Salesforce repo per programme with managed packages (nCino, FSC or similar) alongside custom metadata.

## Architecture

&#91;embedded content: architecture · 5 layers inside one control plane\]

Each layer only reads downward. Skills never grep the checkout directly; they read the index. Agents never carry facts; they carry a posture and a list of skills. The control plane is not a layer but the boundary every layer runs inside, which is why it is built first.

## Layer 1: the metadata index

The index is the foundation and the first thing built. One stdlib-only Python script (`tools/index/build_index.py`) walks `force-app/` and `pkg-*/` (not `manifest/`: zero hits for `manifest` in `tools/index/build_index.py`), and emits `index/metadata.json` plus `index/inventory.json`, stamped with the commit SHA, the script version and the UTC time. Nothing in the index comes from an org; it is a projection of the checkout. The walk visits folders and files in sorted order (`tools/index/build_index.py:112-118`), so the order of nodes and edges does not depend on the filesystem. The `builtAt` time in the stamp still differs between builds.

| Output | Contents | Consumed by |
| --- | --- | --- |
| `metadata.json` nodes | Every object, field, record type, class, trigger, LWC, Aura bundle, flow, permission set, custom permission, custom label, named credential, with type, path, API version and managed namespace | All skills: existence checks, type checks, `path:line` evidence |
| `metadata.json` edges | References between nodes found by parsing: SOQL field use in Apex, `@AuraEnabled` consumers, flow element references, permission-set field grants, LWC imports. Also modelled: validation rules, record types, triggers to their objects, Apex class to class, invocable and `@AuraEnabled` methods (the LWC Apex import edge carries `auraEnabled` true or false, or null when the class is not indexed), flow Apex actions and flow trigger objects, FlexiPages, and permission-set object and class access | Story impact (hop expansion), PR reference check (consumers of a changed field) |
| `inventory.json` | Counts and distributions: classes by API version, flows by process type, Aura vs LWC, `without sharing` classes, Remote Site vs Named Credential, report types, FlexiPages | Release impact baseline, knowledge-file lint (no stored counts), dashboards |
| `stamp` block | `commit`, `indexVersion`, `builtAt`, `namespaces[]` | Every report cites it; staleness is decided by comparing stamps, never by judgement |

Rules for the index:

- Parsing is by file type with deliberately narrow regexes and XML parsing; no fuzzy matching. A false negative is reported as "zero hits for pattern X" and is still evidence.
- Every `path` and `path:line` in the index is relative to the repo root (the git checkout's top level), whatever `--root` was, so evidence opens from the checkout as cited. `tools/index/test_index.py` proves it on the fixtures.
- Managed-package metadata is indexed from `pkg-*/` and from a committed `namespaces.json` list; package internals the repo does not hold are marked Unverifiable, not guessed.
- The index is rebuilt in CI on every PR and committed artefacts are never trusted: a skill that finds the stamp's commit does not match `HEAD` rebuilds before proceeding.
- Query helpers (`tools/index/query.py`) answer the questions skills ask: `consumers(apiName, hops)` (up to 3 hops; story-impact defaults to 2 and takes an optional `hops` input), `exists(apiName)`, `type(apiName)`, `below_api_floor(n)`, and `edge-seeds <api>...` (candidate edge cases for story refinement; see "Story refinement"). Skills call these, not `grep`.
- Index version `0.5.0` (`INDEX_VERSION` in `build_index.py`, recorded in the stamp as `indexVersion`) adds the field attributes `picklistValues`, `globalValueSet` and `formula`. `picklistValues` lists each value of a field's own value set as `{value, active, line}`, where `line` is the value's `<fullName>` line and `active` is false only when the value says `<isActive>false</isActive>`. `globalValueSet` holds the name of a global value set the field uses; its values live outside the field file and are not indexed. `formula` is true when the field has a formula. An index built by an earlier version lacks these attributes, so rebuild it before running `edge-seeds`.

## Layer 2: the control plane

The control plane is built and tested before the first skill, because every later layer assumes it. It has five parts, each enforced by a mechanism rather than by text.

| Part | Mechanism | What it stops |
| --- | --- | --- |
| Offline guard | PreToolUse hook on every tool (matcher `.*`) in `.claude/settings.json`, registered as `sh "$CLAUDE_PROJECT_DIR/tools/guard/guard.sh"`, which runs `tools/guard/guard.py` with `-I`. The wrapper exits 2 if no interpreter is found or `guard.py` is unreadable, and maps any other exit code to 2, so a missing Python blocks rather than passes. `guard.cmd` is a Windows fallback, not the registered command. Rules live in `tools/guard/policy.json`; the active mode picks the allowed write paths, the Bash allowlist and the Salesforce CLI level. Claude Code only: no Copilot hook is registered. `.github/hooks/` holds only a README describing how one could be, so Copilot users get the rendered instructions but no guard today (WS6; see "Copilot today"). | `sfdx`, org logins and every other org-changing `sf` command, pushes, `curl`, `wget`, writes outside the mode's paths, Bash outside the mode's allowlist, unquoted globs that could expand to an option, WebFetch to domains not on the allowlist, MCP tools that write (and every MCP tool in `advise`), and any write or non-read-only Bash while the tripwire is tripped |
| Deny rules | Static `permissions.deny` patterns in the same settings file for the always-blocked Salesforce CLI command prefixes, `sfdx`, `git push`, `curl`, `wget` and `WebFetch` | Belt and braces: a deny rule applies even when the hook cannot start. They do not cover Write/Edit paths, colon-style ids, the `force` topic or `--flags-dir`; those depend on the hook |
| Data boundary | `.gitignore` for `data/`, `/index/` and the whole `/ai-context/` workspace (the WS2 owner patch, applied in `3fb9e73`). Plus `tools/guard/scan_data.py` as a pre-commit hook (staged files) and a pipeline gate (`--tracked`, the files git tracks). The default pack of patterns is always on. The NZ and nCino patterns are opt-in packs that apply only when `tools/guard/scan_packs.json` names them; this repo ships that file with the default pack only | Org exports, user inputs and workspace output entering git; Salesforce IDs and emails in any committed file. NZ account-number and IRD formats and `LLC_BI__` record names only where those packs are enabled |
| Secrets | gitleaks (or the platform's native scanner) pre-commit and in CI | Keys, tokens and credentials in commits |
| Kill switch | One line in `.claude/settings.json` (`"env": {"AI_FRAMEWORK_MODE": "advise"}`) that the guard reads: in `advise` mode every write is blocked and only read-only Bash runs, and the model is told to output recommendations only. The committed value is the ceiling: committed `advise` always wins over any local override | Programme-wide pause in minutes if a skill misbehaves, without touching squads' machines |

The control plane ships with its own test: `tools/guard/test_guard.py` feeds synthetic tool calls (an `sf org login`, a write to `force-app/`, a fetch to a blog) and asserts exit code 2 on each, runs the registered hook command itself, and runs the wrapper with no Python on PATH. CI runs it on a Linux and a Windows agent on every PR, and onboarding runs it once on each laptop.

### Modes

The guard has four modes, set by `AI_FRAMEWORK_MODE`. Committed `.claude/settings.json` holds `normal`. A person may select another mode only for themselves, through a personal git-ignored `.claude/settings.local.json`, and only while the committed value is `normal`. A committed `advise` always wins. A committed `build` or `maintain` is not trusted and is treated as `advise`, as is an unreadable or unknown committed value. An unknown local value blocks.

| Mode | Who | Writes allowed | Bash rule | Salesforce CLI level |
| --- | --- | --- | --- | --- |
| `advise` | Everyone, when the programme pulls the kill switch | None | Read-only commands only (`cat`, `ls`, `grep`, read-only `git`, `find` without actions, `query.py`). Redirects only to `/dev/null` or a file descriptor; no `$`, brace or command substitution | `none` |
| `normal` | The default for every squad member | `ai-context/`, `index/` | Read-only commands plus the framework scripts (index build and query, `run_skill.py` and `run_agent.py`, lint, `test_guard.py`, `scan_data.py`, the impact, story and design validators, `check_ac.py`, `framework_config.py`, `check_rules.py --from-config`, `check_trace.py <storyId>`, skill scripts). Every write target the command makes must also be under the mode's write paths | `offline` |
| `build` | A developer, by personal override (`tools/impacts/start.py` gives the session its story scope) | Same as `normal`, plus source writes to the exact paths in the active story's committed build package, tests first (see "Scoped code writing"). With no active story, no source write is allowed | `normal` plus dev tooling: `git add` and `git commit` (local only), `pnpm exec` prettier, eslint, jest and sfdx-lwc-jest, `pnpm lint`, `pnpm format`, `pnpm test` | `offline` |
| `maintain` | A framework maintainer, by personal override | The framework paths listed under `maintain` in `policy.json` (for example `framework/`, `tools/`, `docs/`, `README.md`), plus `ai-context/` and `index/` | `normal` plus the maintainer allowlist (`maintainer_tools` in `policy.json`): `cp`, `mv`, `mkdir`, `rm`, `touch`, `rmdir`, `sed`, `diff`, `cmp`, `tar` in list mode, `git add` and `git commit`, `pnpm exec` prettier, eslint and jest, and Python scripts under `tools/`, `framework/`, `fixtures/`, `demo/` and `ai-context/` | `offline` |

Outside `advise`, Bash is allowlist-based: a command that is not on the mode's list is blocked, and so is any command whose write targets the guard cannot work out. The framework scripts' own output flags count as write targets: `build_index.py --out` (joined to `--root`, abbreviations included) and `write_report.py`'s `ai-context/<id>-<slug>/` (a `/`, `\` or `..` in `--id` or `--slug`, or a `--root` other than `.`, blocks); `query.py` only prints. Scripts, `pnpm` and the Salesforce CLI run only from the project root, with no `cd` before them. In every mode, including `advise`, a Bash line is blocked when it holds a `$` (double-quoted too, since the shell still expands it there), a `{` or `}`, or a bracket expression with `[:`, `[=` or `[.` (`[[:punct:]]`) outside single quotes: the shell can expand any of them into an option or a path the guard never sees (`rg x {--pre=sh,evil}`, `build_index.py --o${U}ut tools/guard`). A backslash-escaped character stays literal. Put such text in single quotes, or put it in a file and point the command at the file. A heredoc (`<<` or `<<-`; the here-string `<<<` is fine) is blocked in every mode too, because a `'` in its body is an ordinary character and a `$(...)` there still runs; write the text to a file instead. A line that already holds the guard's private marker characters (U+E000 to U+E002) is unparseable and blocked. The glob rules below are a second, narrower check and do not close the class on their own. In every mode, an unquoted glob word is blocked when it starts with `-`, when it comes after a `cd`, `pushd` or `popd` on the same line, when it holds an expansion, or when it matches a name starting with `-` in the working directory: the shell would hand such a match to the command as an option (`sort -[o]`, `find .. -delet[e]`, `rg x *` beside a file named `--pre=sh`). Quote the glob (`'*.py'`) to pass it literally. A line with more than 64 unquoted glob words is blocked ("too many glob patterns"); identical words are expanded once, and every directory entry a glob reads, matched or not, is charged to the per-call budget. Git is a subcommand allowlist (`status`, `diff`, `log`, `show`, `rev-parse`, `ls-files`, `check-ignore`, `blame`, `branch --show-current`; `add` and `commit` only in `build` and `maintain`); global options such as `-C` and `-c` are refused. Pushes, `git commit --amend` (and any prefix of it git accepts, such as `--amen`), `curl`, `wget`, `ssh`, `scp` and `sfdx` are blocked in every mode. A `git commit` whose message holds a `$` or braces outside single quotes, or a substitution, is blocked because the guard cannot read it; the block message says to single-quote it or write the message to a file under `ai-context/` and run `git commit -F ai-context/<file>`. `git commit -m 'fix $5 bug'` passes. The guard refuses writes to these paths in every mode (a laptop rule, best effort; see Layer 1 below): `tools/guard/`, `.claude/settings.json`, `.claude/settings.local.json`, `.github/workflows/`, `.github/hooks/`, every `CODEOWNERS` file, and `.git/`. Those change by a human-applied patch with a second reviewer, and the human applies and commits the guard files together.

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
- **MCP tools are judged by name.** The hook runs for every tool. First, any tool other than Bash whose input has a `command` field is blocked in every mode, whatever its name and whether or not it is on `tools.read_only`: an unmodelled shell (a PowerShell tool, Claude Code's `Monitor`, an MCP shell) would skip every Bash rule. Then tools in `tools.read_only` in `policy.json` pass in every mode; the list includes Claude Code's task and messaging tools (`TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet`, `TaskOutput`, `TaskStop`, `ScheduleWakeup`, `ListAgents`, `SendMessage`). An MCP tool (`mcp__<server>__<name>`) is blocked in `advise`; in other modes it is blocked when a whole segment of `<name>` is a write verb (`tools.mcp_write_pattern`: write, edit, create, delete, send, run, copy, save, store, commit, merge, mkdir, upsert, cancel, untrash, unlabel, mark, input, click, restore and similar; the full list is in the policy) and allowed otherwise. Segments are split at `_`, `-` and lower-to-upper camelCase steps, so `get_dataset` and `settings` do not read as `set`, while `CreateIssue` and `setValue` do. An MCP server that writes under an innocent name, or under a verb the pattern does not list, is not caught. Any other tool is blocked in `advise` and allowed elsewhere. Backstop: review which MCP servers a programme enables.
- **The guard has a time limit, best effort.** The hook times out at 10 seconds, and a timed-out hook may let the call through. The guard checks an internal 7-second deadline at its loops (walks, glob scans, target checks) and before the tripwire, and blocks itself ("guard ran out of time; failing closed") once it has passed; work between two checks can run past it, so 7 seconds is not a hard bound. What keeps it well under the hook timeout is the work limits: each git call gets at most 3 seconds and a git timeout counts as unverifiable, which blocks; a line may hold at most 64 unquoted glob words; and recursive walks and glob scans share one budget of 20000 directory entries per call (every entry read counts, not only matches), past which the command is unknown and blocked.
- **Windows is Inferred, not tested.** Claude Code on Windows is assumed to run hook commands through Git Bash; the documentation could not be checked from the environment this was built in. `guard.cmd` is a documented fallback and its behaviour is Unverifiable until the Windows CI job runs. The first Windows CI run is the check.

Operations a human must know:

- **One-time step after applying the guard patches:** run the re-baseline command from a terminal (see the README). Until then every write and every non-read-only Bash call is blocked. A `git status` that the assistant can run shows the baseline is current, because the guard refuses every git command while it is missing or stale.
- **Re-baseline whenever `.git/config` or `.git/hooks/` legitimately change**, for example when installing husky hooks or editing core settings.
- **Every new git worktree needs its own re-baseline.** The baseline lives in each worktree's git directory, so a fresh `git worktree add` blocks writes there until a human runs the re-baseline command from inside it.
- **Text with `$`, braces or a `[[:class:]]` bracket, in any mode:** single-quote it (`git commit -m 'fix $5 bug'`), or write it to a file under `ai-context/` and point the command at the file (`git commit -F ai-context/<file>`). Unquoted or double-quoted, the guard cannot see what the shell expands it to and blocks the line.
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

Step 0 of the workflow comes before story-impact and pr-reference-check: **story-refine** turns one rough story into Given/When/Then acceptance criteria and edge cases seeded from the index, and writes a draft `story.json` and `story.md` (see "Story refinement"). Between understanding a story and sizing it, **solution-design** writes evidenced options, always including "do nothing", with one provisional recommendation; story-impact then sizes the recommended option. "Day-one workflow" below gives the order.

The first two skills, in order:

1. **story-impact.** Input: a work item (story, feature, defect) as text. Method: seed terms from the taxonomy, `consumers()` to two hops by default (an optional `hops` input takes 1 to 3), triage with recorded drop reasons, classify each hit (layer, ownership, change type, impact, confidence), write `ai-context/<id>-<slug>/impact.md`, the draft record `impact.json` (see "Impact record and register") and, later, the RICEFW workbook. This is the skill that proves the index and pays back first.
2. **pr-reference-check.** Input: a diff. Method: extract every API name referenced in changed files, `exists()` and `type()` against the index, report invented names and type mismatches with `path:line`. Deterministic checks (secrets, manifest completeness, naming, debug statements) are not in this skill; they are CI steps the skill links to.

Then, by demand and only once the first two are stable on one squad: release-impact (reads `inventory.json` against release notes), test-case-design, wiki-page. Each is a consumer of the same index and the same evidence taxonomy, so each is mostly method and templates. The discovery-pack backlog item is no longer on this list: story-refine absorbed it (see "Story refinement").

Evals run on every PR touching `framework/skills/`. A case passes when the deterministic assertions hold on all five runs (every cited `path:line` exists, no banned phrases, evidence labels on every claim) and the rubric score is at or above the committed threshold on at least four.

## Day-one workflow

One path takes a story from rough text to a confirmed impact, and from there into scoped code, for an existing codebase and for a greenfield one alike. The assistant may recommend and proceed provisionally; a named owner confirms each recommendation before it becomes a committed impact. The steps, in order:

| Step | What happens | Skill | Scripts | Output |
| --- | --- | --- | --- | --- |
| 1. Refine | A rough story becomes Given/When/Then criteria, edge cases from the index and open questions with owner roles. The product owner confirms it by promoting it | `story-refine` | `query.py edge-seeds`, `write_story.py`; the owner runs `promote.py --story` | Draft `story.json` and `story.md`; the confirmed records in `impacts/<storyId>-<slug>/` |
| 2. Understand | story-impact's front half: freshness, inputs, a framing of the story, seed terms and the index scan | `story-impact` (Steps 0 to 3) | `query.py check-stale`, `build_index.py --from-config` when stale, `query.py exists` and `consumers` | The framing, `scan/terms.txt` |
| 3. Design | Options within the range `MIN_OPTIONS` to `MAX_OPTIONS` in `tools/designs/validate_design.py`, exactly one of them "do nothing", each with trade-offs on named criteria and its components with evidence, plus one provisional recommendation with reasons | `solution-design` | `query.py exists` and `consumers`, `register.py view`, `write_design.py` (runs `validate_design.py` in-process) | Draft `design.json` and `design.md` in `ai-context/<id>-<slug>/` |
| 4. Assess | story-impact sizes the recommended option, using only that option's components (Step 3a) | `story-impact` (Steps 3a to 5) | `write_report.py` | Draft `impact.json` with `designOption` and `provenance.recommendedBy: "assistant"`; `impact.md` names the assessed option |
| 5. Confirm | A human promotes the impact and chooses the option, into the story's folder without `--replace` when the story was promoted first. A choice that differs from the assessed option is refused, with a request to re-run story-impact for it | none (a human step) | `promote.py --option OPT-n` | `impacts/<storyId>-<slug>/`: `impact.json` with `chosenOption`, a copy of `impact.md`, and `design.json` and `design.md` confirmed |

The steps continue into code (see "Scoped code writing"). Steps 6 and 7 are human steps; step 8 runs only in build mode:

| Step | What happens | Skill | Scripts | Output |
| --- | --- | --- | --- | --- |
| 6. Package | A maintainer assembles the build package from the confirmed story, design and impact, and commits it with the impact PR | none (a human or maintainer step, `maintain` only) | `tools/impacts/package.py <storyId>` | `impacts/<storyId>-<slug>/build-package.json` and `build-package.md` |
| 7. Start | A human starts a build session from a real terminal, adds the printed env lines to `.claude/settings.local.json` and restarts Claude Code | none (a human step) | `tools/impacts/start.py <storyId>` | `ai-context/.active-story`; the session is in build mode |
| 8. Build | Tests first, then code, only inside the package scope; then the package's done commands | `implement-story` (the `builder` agent) | `check_trace.py --skeletons`, `check_rules.py --from-config`, `check_trace.py`, `write_change.py` | Code and tests in scope; `change.json` and `change.md` in `ai-context/<id>-<slug>/` |
| 9. Review | The developer opens a PR. A named reviewer reviews it; CI re-runs the checks | none (a human step) | CI | A reviewed merge, or not |

Steps 7 and 8 need a committed build package. Without one, start.py refuses and build mode allows no source write. In this repo, DEMO-202 has one.

The `analyst` agent runs solution-design and story-impact; the `discovery-lead` agent runs story-refine; the `builder` agent runs implement-story. Design is optional for a story: story-impact without a `design.json` sizes the story as it did before WS10, its impact carries no `designOption`, and promotion works as before. WS2's DEMO-202 record, now in git history, was such an impact.

### `.ai-framework.json`

An optional file at the repo root, read only by `tools/config/framework_config.py`. Its keys:

- **`startingPoint`:** `existing` or `greenfield`. Default `existing`.
- **`sourceRoot`:** the folder that holds `force-app/` and `pkg-*/`, relative to the repo. Default `.`. It must resolve (realpath) to a folder inside the repo.
- **`impactChecks`:** the PR check's severity switch (see "The right check"). Default `comment` for each class.

A missing file means the defaults. An unknown top-level key is an error, so a typo surfaces. Every invalid value is exit 2 from the CLI (`framework_config.py source-root` prints the source root relative to the repo; `framework_config.py show` prints the whole config with defaults filled in). `pr_check.py` reads `impactChecks` through the same module, validating only the file's keys and `impactChecks`, so a bad `sourceRoot` cannot stop the PR check.

This repo commits `{"startingPoint": "existing", "sourceRoot": "demo/org"}`. `python3 tools/index/build_index.py --from-config` indexes `sourceRoot` into `<checkout>/index`, the checkout being the script's own, never the cwd. It refuses `--root` or `--out` alongside it (exit 2). build_index's own defaults (`--root .`, `--out index` joined to `--root`) are unchanged. story-impact and solution-design rebuild a stale index with `--from-config`, so a stale rebuild indexes the configured source root, not the repo root.

### Onboarding: both starting points

`tools/onboard/onboard.py --starting-point existing|greenfield` sets a repo up for the workflow. `--source-root` defaults to `sourceRoot` from `.ai-framework.json`. `--write-config` writes `startingPoint` and `sourceRoot` into `.ai-framework.json`, keeping any `impactChecks`; without it the config is untouched. A target outside `--root`, or one that passes through a symlink, is exit 2 before anything is written.

- **existing** (needs `--owner-role`): builds the index of the source root into `<root>/index`, prints the inventory from `index/inventory.json` (Apex by API version, Apex by sharing, Aura vs LWC) and writes knowledge stubs.
- **greenfield:** creates the SFDX layout under the source root where it is absent (`sfdx-project.json` and `force-app/main/default/<folder>/.gitkeep` for `classes`, `objects`, `lwc`, `flows` and `permissionsets`), then builds the empty index, which replaces `<root>/index`. It exits 1 with nothing written when the source root already holds a codebase: any entry under `force-app/main/default/` beyond the skeleton, or an `sfdx-project.json` that differs from the one greenfield writes. `demo/greenfield/` is the committed skeleton, created by `onboard.py --starting-point greenfield --source-root demo/greenfield`.

A second run changes nothing: an identical file is left alone, and a file that differs from what onboarding generates is kept and reported unless `--replace` is given.

**The stub rule.** Stubs go to `framework/knowledge/stubs/<topic-slug>.md`, below lint's top-level scan of `framework/knowledge/` and outside rendering. Topics are the objects with the most inbound edges in the index (`STUB_TOPICS` in `onboard.py`, with the rationale in a comment), ties broken by name. Each stub's front-matter holds `topic`, `owner` (from `--owner-role`), `last_verified: ""` and `verified_by: ""`. Its body holds only "Leads to verify:" lines naming index components, never facts. A human fills a stub and moves it up a level into `framework/knowledge/`, where lint then applies. The stubs folder is not git-ignored, so new stubs show as untracked files until someone moves or deletes them.

**The rule baseline.** For an existing codebase, onboarding writes `<root>/tools/code/baseline.json` from the checkout's `tools/code/check_rules.py`: every finding already in the source root, so later runs report only new ones (`tools/onboard/onboard.py:382-385`). An identical file is left alone, and a differing one is kept unless `--replace` is given. A greenfield run writes no baseline and prints `no baseline: rules are strict from the first commit`. See "Scoped code writing" for the baseline's format and rules.

### The design record

`tools/designs/validate_design.py` is the schema's source of truth. The key names are:

- **Top level:** `schemaVersion`, `storyId`, `slug`, `status` (`draft` or `confirmed`), `options`, `recommendation`, `provenance`, plus `confirmedBy` and `chosenOption` on a confirmed record.
- **Each option:** `id` (`OPT-n`, from 1 with no gaps), `title`, `summary`, `doNothing`, `components`, `tradeOffs`, `impactSummary`.
- **Each component:** `api`, `type`, `changeType` (`new`, `modify`, `delete`, `review`), `evidence` (`path:line`, or null), `confidence`.
- **Each trade-off:** `criterion` (`security`, `governor-limits`, `data-volume`, `licence-fit`, `maintainability`, `reuse`) and `note`.
- **`recommendation`:** `optionId` and `reasons`.
- **`provenance`:** `indexStamp`, `frameworkVersion`, `model`, `assistantVersion`, `sourceRoot` (the repo-relative source root the design was written for: `"."` or `a/b`, forward slashes, no `..` segment; checked lexically, never against the filesystem).

Exactly one option has `doNothing: true`, and it has no components; every other option has at least one. A `new` component has null evidence and must not already be an index node (compared case-insensitively). Checked against an index, any other component is an index node of the same type, and its evidence path is the node's path (or under it, for bundles). Null evidence on a non-`new` component is allowed only at `Unverifiable`.

`framework/skills/solution-design/scripts/write_design.py` fills in `schemaVersion`, `status` and `provenance`, refuses a draft that carries any of them or the promotion keys, validates against the index (`--index`, default `<checkout>/index`; a missing index is exit 2) with evidence checked, and on any error writes nothing (exit 1). It records `provenance.sourceRoot` from `--source-root`, or by default from the configured `sourceRoot` (read through the checkout's `tools/config/framework_config.py`); either must resolve to a folder inside `--root`, or it is exit 2 and nothing is written. The writer does not check that `--index` was built from that source root. It writes `design.json` and `design.md` to `ai-context/<id>-<slug>/` through `tools/impacts/safe_write.py`. `design.md` is rendered by `tools/designs/design_md.py`, which promotion also uses; each Components row ends in the component's confidence label.

**When the index checks run.** The index checks on a design's components (a `new` component is not already a node; any other is a node of the same type with evidence in its file) run at draft time (`write_design.py`) and at promotion (`promote.py`) only. `validate_design.py --all` checks every `impacts/*/design.json` as confirmed without an index and without evidence checks: schema, internal consistency, folder name and unique `storyId`. `tools/impacts/validate.py --all` validates a `design.json` beside an impact the same way, and checks that its `chosenOption` equals the impact's and the do-nothing rule. This mirrors how a promoted impact is validated (`validate(doc, "promoted", root)`, no evidence check). A confirmed record therefore stays valid once the code it declared `new` lands or a `delete` ships, and no record is ever hand-edited to keep CI green. Neither `--all` reads an index; `validate_design.py --all --index` is bad usage (exit 2), and `validate.py` has no `--index`.

**Greenfield and standard objects.** An empty source root (`demo/greenfield`) builds an empty index, which has no node for a standard object such as `Case`. A greenfield design therefore cannot cite `Case` as a `modify` or `review` component: the writer reports it as not a node in the index. The relationship goes on a `new` component instead (for example, a `new` lookup field `Warranty_Claim__c.Case__c`), and the dependency on the standard object goes in a trade-off note. This is a known limit; the validator is unchanged.

solution-design is the one skill allowed to recommend. story-impact and the reviewer keep "we recommend" banned.

**impact.json additions.** Optional `designOption` (the option the record assesses), `provenance.recommendedBy` (`"assistant"` when that option was the assistant's recommendation; left out when the owner named another option), and `chosenOption` (promoted records only, required there with `designOption` and equal to it). A record without a design carries none of these keys.

### The option choice at promotion

`promote.py <draft-dir> --confirmed-by "<name or role>" [--option OPT-n]`. When the draft folder holds `design.json`, it is validated as a draft against the index (`--index`, default `<checkout>/index`) with evidence checked, and must have the same `storyId` and slug as the impact. The chosen option is `--option`, or the design's recommendation when the flag is left out. On success it prints the design's `sourceRoot` and the `--index` it validated against; it does not check which source root that index was built from. Promotion is the last index check a design gets. Then:

- **A mismatch is refused (exit 1):** `impact assesses OPT-a; re-run story-impact for OPT-b before promoting`. story-impact is re-run for the owner's option with `designOption` set to it and `recommendedBy` left out. The record is never hand-edited.
- **The do-nothing rule:** when the chosen option is the design's `doNothing` option, an impact with any `new`, `modify` or `delete` component is refused (exit 1): `the chosen option is do nothing; the impact must not change components`. The message also lists the changing components. `review` components are allowed.
- **Otherwise** it writes the impact as before, adds `chosenOption` to `impact.json`, and writes `design.json` (status `confirmed`, `confirmedBy`, `chosenOption`) and a `design.md` re-rendered by `design_md.py`. The design files get the impact's protections: no symlinked source, a data scan of the draft and of the final bytes, writes that never follow a symlink, and the cross-folder story-id check, which now also looks at `design.json`.

Without `design.json`, `--option` is bad usage (exit 2), an impact that names a `designOption` is refused, and a destination that already holds `design.json` or `design.md` is refused.

### Where it runs

The WS10 owner patches (`ai-context/ws10/patches/`) are applied, on top of the WS11 ones. Under `tools/guard/policy.json`:

| Command | Where it runs |
| --- | --- |
| `build_index.py --from-config` | `normal`, `build`, `maintain`. The guard models it as writing `<checkout>/index/`; with `--root` or `--out` alongside, it is blocked |
| `write_design.py`, `write_report.py`, `write_story.py` | `normal`, `build`, `maintain` (the `framework/skills/<skill>/scripts/` pattern). The guard models `write_design.py`'s `design.json` and `design.md` in `ai-context/<id>-<slug>/`; a `--root` other than `.`, or a `/`, `\` or `..` in `--id` or `--slug`, blocks |
| `validate_design.py`, `framework_config.py` run directly | `normal`, `build`, `maintain` |
| `onboard.py` | `maintain` only (or a human terminal) |
| `promote.py --option` | `maintain` only; a human step by working rule |
| `tools/config/`, `tools/onboard/`, `tools/designs/` test scripts | `maintain` only (or a human terminal) |

In CI, `guard-and-lint` builds the index with `--from-config` before `validate.py --all` (the `--from-config` index covers only the configured `sourceRoot`, `demo/org` here; neither `--all` check reads it, so confirmed records do not depend on it), then runs `tools/config/test_framework_config.py`, `tools/onboard/test_onboard.py`, `tools/designs/test_validate_design.py`, `tools/designs/test_write_design.py` and `validate_design.py --all`. Its `paths` filter includes `.ai-framework.json`, and the `impact-checks` job builds its index from the base branch's `sourceRoot` (through `framework_config.py source-root --root base`), falling back to `demo/org` when the base branch has no `framework_config.py`.

### Honest limits

- **One Claude Code run.** Solution-design and story-impact's Assess step have run once under Claude Code, on DEMO-202, with the owner answering and confirming along the way. That is one run, not a consistency figure, and no eval has scored it. Their assertions are shown only by writer smoke tests: hand-built drafts fed through `write_design.py` and `write_report.py`, then scored with `run_skill.py`.
- **Stubs are leads, not knowledge.** Nothing checks a stub until a human moves it up a level.
- **The patches are untested by `git apply`.** The guard does not allowlist it; `APPLY.md` lists what was checked instead and what is Unverifiable (the new CI steps on `windows-latest` and on a GitHub runner).

## Impact record and register

story-impact writes a machine-readable record, `impact.json`, beside `impact.md`. A human promotes reviewed records into `impacts/`. The promoted records that are still in flight form the register. Two checks read it: one when a story is sized (the left check) and one when code for it is reviewed (the right check). Both state findings and name owner roles. Neither decides anything.

### The record

`tools/impacts/validate.py` is the schema's source of truth. Each key's rules (patterns, allowed values, and when evidence may be null) live there and nowhere else. The key names are:

- **Top level:** `schemaVersion`, `storyId`, `slug`, `squad`, `status`, `provenance`, `components`, `decisions`, `unknowns`, plus `confirmedBy` on a promoted record.
- **`provenance`:** `indexStamp`, `hops`, `frameworkVersion`, `model`, `assistantVersion`.
- **Each component:** `api`, `type`, `changeType`, `impact`, `confidence`, `hop`, `evidence`, `path`.
- **Each decision:** `text`, `ownerRole`.

Folders are named `<storyId>-<slug>` in both `ai-context/` and `impacts/`. `validate.py --all` checks every `impacts/*/impact.json` as promoted, checks that its folder name matches its `storyId` and `slug`, and checks that no `storyId` appears twice.

### Draft and promoted

| | Draft | Promoted |
| --- | --- | --- |
| Where | `ai-context/<storyId>-<slug>/impact.json` and `impact.md` | `impacts/<storyId>-<slug>/impact.json` and a byte-for-byte copy of `impact.md`, plus the confirmed `design.json` and `design.md` when the draft holds a design (see "Day-one workflow") |
| Written by | `framework/skills/story-impact/scripts/write_report.py` (story-impact Step 5), or `tools/demo/answer_to_draft.py`, which feeds a reviewed answer key through the same writer | `tools/impacts/promote.py <draft-dir> --confirmed-by "<name or role>"` |
| `status` | `draft`, with no `confirmedBy` | `in-flight`, with `confirmedBy` set. A human edits it to `shipped` in a later PR |
| Evidence files | Checked at write time; nothing is written on an error | Checked again by `promote.py` before it writes |
| In git | No; it is workspace output | Yes, through an ordinary PR that a reviewer checks |

`promote.py` validates the draft with its evidence files checked, then runs `tools/guard/scan_data.py` over `impact.json` and `impact.md`. It refuses (exit 1, nothing written):

- when the destination folder already holds `impact.json`, `impact.md`, `design.json` or `design.md` (unless `--replace`); a folder holding only `story.json` and `story.md` is fine;
- when a source file, the destination or `impacts/` itself is a symlink;
- when `impact.json` cannot be parsed, deeply nested JSON included;
- when the same `storyId` already has an `impact.json`, `story.json` or `design.json` in another `impacts/` folder;
- when the data scan finds a hit in the sources, or in the exact bytes it is about to write. That final scan covers the record with `--confirmed-by` filled in, so an email-shaped or other real-data value there is refused too.

A draft folder that resolves outside `<root>/ai-context/` is bad usage (exit 2). `--confirmed-by` records who confirmed the record. The script decides nothing.

Promotion is a human step. In `normal` the guard blocks the assistant from running `promote.py` and from writing `impacts/`. `maintain` admits both, so there the rule that the owner runs it with their own `--confirmed-by` (`! python3 tools/impacts/promote.py ...` in Claude Code) is a process rule, not a guard rule. The assistant never supplies a confirmation.

The register is every `impacts/*/impact.json` that validates as promoted and whose `status` is not `shipped`. A file that fails JSON parsing or validation is listed under `invalid` and never stops a run. Evidence files are not checked here, nor in CI: a later file move must not fail unrelated PRs. `tools/impacts/register.py` answers `overlaps <impact.json>`, `scope <storyId>` (exit 4 when the story is not on record) and `view`. `tools/impacts/render_register.py` writes the register as one static HTML page, by default `ai-context/register/register.html` in the checkout the script runs from. Its `--root` only chooses which `impacts/` to read and which repo's HEAD commit the page shows. The output is anchored on the checkout's own `ai-context/`, found from the script's location, and a relative `--out` resolves against the checkout. It refuses with exit 2, and writes no page, when the output folder resolves (realpath, so through `..` and symlinks) outside that `ai-context/`, when that `ai-context/` is itself a symlink, or when the output file is a symlink. `write_report.py` and `tools/demo/answer_to_draft.py` write to `<root>/ai-context/<storyId>-<slug>/` and refuse a folder that resolves outside either `<root>/ai-context/` or the checkout's `ai-context/`. With `--root .` the two are the same folder. register.py runs git only for `log` and `rev-parse`, with `--no-pager`, `-c` overrides that switch off the config keys known to run a command (`core.fsmonitor`, `core.hooksPath`, `core.pager`, `core.sshCommand`, `diff.external`, `core.editor`), and `GIT_CONFIG_NOSYSTEM=1`. Other config in a repo that encloses `--root` is still read.

### Squads, identity and overlap kinds

- **Squads:** `impacts/squads.json` (`{"version": 1, "squads": [...]}`) lists the squad names. A record's `squad` must be listed there. `CODEOWNERS` is human-owned and names the maintainer on every control path.
- **Component identity:** the `api` string alone, since index node ids are API names. `type` is shown but is not part of the key.
- **Overlap kinds:**
  - A **conflict** is when both stories `new`, `modify` or `delete` the same component.
  - A **watch** is when either side marks it `review`.

### The left check: overlaps at story time

`write_report.py` loads the register in-process and writes an `## Overlaps with other stories` section into `impact.md`. Each row gives the component, the kind, the other story, its squad and status, its change type, and the commit that last changed its record. With no overlaps, the section reads `none in the register at <HEAD>`. The section is a snapshot taken at write time. The skill reports it as written and never rewrites it. It never fails anything.

### The right check: the PR check

`tools/impacts/pr_check.py` takes a built index, the list of changed files, the branch name and, optionally, the open-PR listing from `gh pr list --json number,headRefName,files`. It prints markdown and writes no files. Its sections are:

- **Impact records in this PR:** each changed `impacts/*/impact.json`, validated as promoted, named with its story and squad, and its overlaps against the register, each naming the other story and squad. A changed record that is a symlink, or sits under a symlinked folder, is listed as `symlink, not read`.
- **Components this PR changes:** the changed files mapped to index components. Files the index cannot map are listed as unmapped, and that is never a finding.
- **Registered stories touching these components:** for each component the PR changes, every register entry other than the branch's own story, with its squad, status, change type and record commit. The PR's changes count as modifying, so the kind is `conflict` when the entry is `new`, `modify` or `delete`, and `watch` when it is `review`. This section is informational: it adds no finding class and never fails the check.
- **Scope:** two finding classes.
  - **`noImpact`:** the branch has no story id, or the story has no promoted record, while the PR changes indexed components.
  - **`outOfScope`:** the PR changes components outside the story's record.
- **Other open PRs touching the same components.**

**Branch convention:** a code PR is linked to its story by the branch name. The first match of `[A-Z][A-Z0-9]*-[0-9]+` anywhere in the name is the story id, so `feature/DEMO-201-premium-escalation` links to `DEMO-201`.

**Default severity:** both finding classes are comments, and the check exits 0. A repo opts a class into failure with the `impactChecks` key of the optional `.ai-framework.json` at the root (see "Day-one workflow"): `{"impactChecks": {"noImpact": "fail", "outOfScope": "fail"}}`. An absent file or key means `comment`. Any value other than `comment` or `fail`, or an unknown top-level key, is bad usage (exit 2). `pr_check.py` reads the file through `tools/config/framework_config.py`, the file's one reader. The settings and the register come from `--base-root`, the base branch checkout. So a PR cannot relax its own settings through `pr_check.py`, or add a record that covers its own code. Changed records are read from `--root`, the PR head. This holds within the check only, with two exceptions. First, the PR that first adds `pr_check.py` runs its own copy. Second, a `pull_request` workflow runs the workflow file from the PR head, so a PR that edits `.github/workflows/` can change the job itself. Only review and CODEOWNERS catch that, not this check.

### Where the checks run

The WS1 and WS2 owner patches are applied (`3fb9e73`), and so are the later owner patches, so the following holds.

- **On a laptop.** The left check runs whenever story-impact writes. The writer calls the register in-process. `register.py` is read-only, so it runs in every mode. `validate.py`, `render_register.py` and `pr_check.py` are framework scripts (`normal`, `build`, `maintain`). `promote.py` is `maintain`-only.
- **In CI.** `.github/workflows/framework-ci.yml`:
  - Its `paths` filter includes `demo/**` and `impacts/**`.
  - `guard-and-lint` runs every impact test script and then `validate.py --all`.
  - The `impact-checks` job runs on pull requests:
    - It builds the index from the head's checkout at the base branch's `sourceRoot` (`demo/org` here).
    - It runs the base branch's `pr_check.py` with `--root .` and `--base-root base`, so the check code, settings and register all come from base. Only the PR that first adds `pr_check.py` runs its own copy, and its result says so.
    - It writes the result to the step summary and posts or edits one PR comment.
    - It exits with `pr_check.py`'s code. The rule check against the base baseline, an earlier step, can also fail the job (see "Scoped code writing").

### Honest limits

- **Identity is the `api` string only.** Two records match only when they spell an API name the same way. Two components of different types with one name count as one. A renamed component shows no overlap with its old name.
- **The CI index root comes from the base branch.** `impact-checks` reads `sourceRoot` from the base branch's `.ai-framework.json` (`framework_config.py source-root --root base`, which exits 2 when that folder is missing from the base checkout, `tools/config/framework_config.py:98-99`). A PR that moves the source out of the base branch's `sourceRoot` is therefore checked at the old path until the move is merged. Inferred: the index and rule-check steps then look at a folder the PR no longer has. The index step most likely fails the job first, because `build_index.walk` lists the root with no existence check (`tools/index/build_index.py:112-113`). If it did not, `check_rules.py` would return no findings for the missing folder rather than failing (`tools/code/check_rules.py:263-264`). The workflow's `paths` filter skips `pkg-*/` and `manifest/`, and an adopter whose `sourceRoot` lies outside the listed paths adds it there.
- **The PR comment step is Unverifiable until a remote exists.** It is unclear whether `gh pr comment --edit-last` edits the right comment (it edits the token user's last comment, which may come from another workflow). Fork PRs, the `files` field of `gh pr list` and the base checkout are also unchecked. `APPLY.md` lists each one.
- **A `review` overlap is only a watch.** When one story marks a component `review` and another modifies it, the result is a watch, not a conflict, even if the review later turns into a change. DEMO-201's answer key marks every component it shares with DEMO-202 as `review`, so those overlaps are watches.
- **The left check is a snapshot.** A record written before another story was promoted does not list that story. DEMO-202's own `impact.md` says `none in the register` because no other story was on the register when it was drafted.

## Story refinement

Story refinement is step 0 of the workflow, before story-impact sizes anything. A product owner or BA brings a rough story. The `story-refine` skill (`framework/skills/story-refine/`, run by the `discovery-lead` agent) turns it into testable Given/When/Then acceptance criteria. It adds edge cases that come only from the index, records the seeds it dropped with a reason, lists overlaps with stories on the register, and turns every guess into an open question with an owner role. The output is a draft: `ai-context/<storyId>-<slug>/story.json` and `story.md`. The product owner confirms it by promoting it. The assistant never confirms a story.

### The story record

`tools/stories/validate_story.py` is the schema's source of truth. Each key's rules (patterns, allowed values, when evidence may be null) live there and nowhere else. The key names are:

- **Top level:** `schemaVersion`, `storyId`, `slug`, `status`, `squad`, `persona`, `goal`, `benefit`, `inScope`, `outOfScope`, `nonFunctional`, `openQuestions`, `acceptanceCriteria`, `edgeCases`, `droppedSeeds`, `overlaps`, `seeds`, plus `confirmedBy` on a confirmed story.
- **Each acceptance criterion:** `id` (`AC-n`), `given`, `when`, `then`, `examples`, `source` (`stated`, `edge-case` or `assistant-proposed`).
- **Each edge case:** `id` (`EC-n`), `category`, `component`, `detail`, `evidence`, `confidence`, `becameCriterion` (an `AC-n` id, or null with a `reason`), `reason`.
- **Each dropped seed:** `category`, `component`, `detail`, `reason`.
- **Each open question:** `id` (`OQ-n`), `text`, `ownerRole`, `answer` (text or null), `deferred` (true or false), `deferredBy` (the role that deferred it: a non-empty string when `deferred` is true, null otherwise). Only the owner sets `deferred` and `deferredBy`, before promotion; the assistant writes `deferred: false` and `deferredBy: null`.
- **Each overlap:** `api`, `type`, `kind`, `stories` (each with `storyId`, `squad`, `status`, `changeType`, `type`, `commit`).

`status` is `draft` in `ai-context/` and `confirmed` in `impacts/`, where `confirmedBy` is set. `AC`, `EC` and `OQ` ids run from 1 with no gaps. The id formats are fixed because WS8's `check_trace.py` and the build package read them. `validate_story.py --all` checks every `impacts/*/story.json` as confirmed, checks that its folder is named `<storyId>-<slug>`, checks that no `storyId` appears twice among the story records, and runs `check_ac` on each record, reporting its findings as errors.

**Decision: `detail` on edge cases and dropped seeds.** The spec's `story.json` list gives `edgeCases[]` no `detail` and has no `droppedSeeds[]` at all. WS11 adds both. Several seeds share a component and a category (on `Case`: a validation rule, a trigger and a flow are all `automation`). Without `detail` they collapse into one, and "each seed kept or dropped with a reason" cannot be checked. A seed is identified by its (component, category, detail). The skill copies the component, category and detail verbatim from the seed and never rewords `detail`. The spec text still lacks `detail`; this section records the extension.

### Vague criteria: `check_ac.py`

`tools/stories/check_ac.py <story.json>` prints `{"ok", "findings": [{id, rule, detail}]}` and exits 1 when there are findings. Its rules:

- **`no-criteria`:** the story has no acceptance criteria (`acceptanceCriteria` is empty, missing or not a list). The finding's `id` is `acceptanceCriteria`.
- **`missing-gwt`:** `given`, `when` or `then` is empty or missing.
- **`multiple-outcomes`:** `then` holds a `;`, a sentence break (`.`, `!` or `?`, then whitespace, then a capital or a digit), or the word `and` or `or`. The documented fix is to split it into separate criteria, one outcome each.
- **`no-example`:** `examples` holds no non-empty string.
- **`vague-word`:** `given`, `when` or `then` contains a word or phrase from `tools/stories/vague_words.json`. Matching is whole-word and case-insensitive, and a phrase matches as a phrase.

Quoted text (`"..."` or `` `...` ``) is ignored by `multiple-outcomes` and `vague-word`, so a criterion can quote a field label or a value that contains `and`.

**Honest limits.** This is a heuristic, not a parser of meaning.

- `and` or `or` outside quotes always fails, even when the outcome is single ("shows black and white").
- Quoting exempts anything, so an author can hide a vague word in quotes. Review catches that; the script does not.
- An abbreviation such as `e.g. Foo` reads as a sentence break, and a break followed by a lowercase letter is missed.
- Curly quotes are not treated as quotes.
- The word list is short and English only. A criterion can be precise in wording and still wrong.

### Edge seeds: `query.py edge-seeds`

`python3 tools/index/query.py edge-seeds <api> [<api>...]` prints `{"seeds": [...], "unresolved": [...]}`. Each seed is `{category, component, detail, evidence, confidence}`. It is built from index edges and node attributes only, so it is deterministic: it is deduplicated by (component, category, detail) and sorted by the same triple. A seed that would be `Confirmed` but has no evidence becomes `Unverifiable`. A field api gives seeds for the field and for its object. An object api gives seeds for the object only, not for all its fields. An api the index does not hold is listed under `unresolved` and gives no seeds; for a story, that is a planned new component or a typo.

| Category | Emitted for (code: `edge_seeds` in `tools/index/query.py`) | Evidence | Confidence |
| --- | --- | --- | --- |
| `blank` | A field whose `required` is false, unless it is a formula, roll-up summary, auto-number or master-detail field | The field's `<required>` line, else its `<type>` line | Confirmed |
| `picklist-value` | Each value of the field's own value set; an inactive value's `detail` ends in ` (inactive)`. A field on a global value set gives one seed instead, `global value set; values not in this repo` | The value's `<fullName>` line; the `<valueSetName>` line for a global value set | Confirmed; Unverifiable for a global value set |
| `field-access` | Each permission set that grants the field (`<PermissionSet> read` or `edit`) | The permission set's grant | Confirmed |
| `record-type` | Each record type of the object | The record type | Confirmed |
| `automation` | Each validation rule on the object, with its state (`active`, `inactive` or `status unknown`); each flow whose trigger object is the object, with its status; each trigger on the object (`status not in index`) | The rule, flow or trigger | Confirmed |
| `bulk` | Every object: `a bulk change of 200 records or more` | The object's first trigger, else the object file's `<CustomObject` line, else none. A standard object with no trigger and no object file in the repo (such as `Account` in the demo) gets no evidence | Confirmed; Unverifiable with no evidence |
| `integration-user` | A permission set whose api name contains `integration` (any case) and that grants a field on the object | That grant | Inferred: the codebase holds no users |
| `org-only` | Every object, once: `sharing settings and real data volumes are org configuration, not in this repo` | None | Unverifiable: the spec's "org-only facts (sharing settings, real data volumes) are labelled Unverifiable" |

The code differs from the spec's wording on automation and on the integration user. The spec says validation rules, flows and triggers "already active"; the code emits every one it finds and puts the state in `detail`, so the skill can judge an inactive rule. The spec says "the integration user, when the codebase has one"; the code infers one only from a permission set named for integration that grants a field on the object.

The skill saves the output as `ai-context/<id>-<slug>/scan/edge-seeds.json`. It must account for every seed: keep it as an edge case (copying `category`, `component`, `detail`, `evidence` and `confidence` verbatim) or drop it with a one-line reason. It never adds an edge case that is not a seed. A risk the index cannot see becomes an open question. For a greenfield story the scan returns few or no seeds, and the skill says so rather than inventing any.

**Greenfield seeds from a design are not built.** A planned new component (an `unresolved` term) gives no seeds, so a greenfield story gets edge cases only from the existing objects it touches. WS10 brought the design input: `design.json` declares an option's new components. `query.py edge-seeds` does not read it (zero hits for `design` in `tools/index/query.py` outside a docstring), so seeds from a design's declared components (the new object, its fields and its automation, before any metadata exists) do not exist yet, and no workstream plan assigns them (the plans are the maintainers' workspace, not published in this repo). Until then the greenfield edge cases are open questions with owner roles.

### Writing the draft

`framework/skills/story-refine/scripts/write_story.py --id <id> --slug <slug> --draft <draft.json>` fills in `schemaVersion`, `status` (`draft`) and `overlaps`. It refuses a draft that already carries any of them, or `confirmedBy`. It validates the record with `validate_story` (evidence files checked) and the criteria with `check_ac`, both in-process. On any error it writes nothing and exits 1. It writes `story.json` and `story.md` to `<root>/ai-context/<id>-<slug>/` through `tools/impacts/safe_write.py`, the helpers it shares with story-impact's `write_report.py`:

- `checkout_out_dir` refuses (exit 2) a folder that resolves outside `<root>/ai-context/` or outside this checkout's `ai-context/`, or an `ai-context/` that is a symlink.
- `write_nofollow` never writes through a symlink.

**Every overlap at refinement is a watch.** The writer sends each term in the story's `seeds` list through `register.overlaps()` as a `changeType: "review"` component. A watch is any overlap where one side marks the component `review`, so every refinement overlap is a watch. Whether the story will modify a component is not known until it is sized. `story.md`'s `## Overlaps with other stories` section is a snapshot of the register at write time, built the same way as `impact.md`'s. `story.md` is rendered by `tools/stories/story_md.py`, which `promote.py --story` also uses for the confirmed record, so the draft md and the confirmed md come from the same renderer.

### Confirmation by the product owner

The product owner confirms a refined story by promoting it:

```sh
python3 tools/impacts/promote.py ai-context/<storyId>-<slug> --story --confirmed-by "<name or role>"
```

Promotion is the confirmation, and it is a human step. The assistant never runs it to confirm a story and never supplies `--confirmed-by`. It refuses (exit 1, nothing written) at the first of these that fails:

1. `story.json` or `story.md` is missing or a symlink, or `story.json` cannot be parsed (deeply nested JSON included).
2. The draft fails `validate_story` with evidence files checked.
3. `check_ac` has any finding.
4. An open question is neither answered (non-empty `answer`) nor `deferred: true` (with `deferredBy` set; step 2 refuses a deferral without it).
5. The data scan finds a hit in `story.json` or `story.md`.
6. Destination checks: `impacts/`, the destination folder or a destination file is a symlink; the folder resolves outside `<root>/impacts/`; `story.json` or `story.md` already exists there (unless `--replace`); or the same `storyId` already has an `impact.json`, `story.json` or `design.json` in another `impacts/` folder.
7. The confirmed record (status `confirmed`, `confirmedBy` set) fails validation.
8. The data scan finds a hit in the exact bytes about to be written, `--confirmed-by` included.

Before writing, it prints every deferred question (`OQ-n`, owner role, deferred by, text) and every answered question with its answer, so the product owner sees what they are confirming past. A refused run prints none of it.

It writes `impacts/<storyId>-<slug>/story.json` and a `story.md` re-rendered from the confirmed record by `tools/stories/story_md.py`, the renderer `write_story.py` uses. The draft `story.md` is not copied. The promoted md therefore states `Status: confirmed`, `Confirmed by: <value>` and every answer and deferral that `story.json` holds. Its Overlaps section shows the overlaps as recorded at refinement, without a register commit, because promotion does not re-read the register. Step 8's scan runs on these final bytes. Promotion never touches `impact.json` or `impact.md` in the same folder, and `--replace` applies only to the story files. (The impact path is different: it still writes a byte-for-byte copy of `impact.md`.)

**One folder per story id.** Because of the cross-folder refusal, a story and its impact record must share one `<storyId>-<slug>` folder, so the refinement and the sizing need the same slug. The demo uses the slug `premium-escalation` for the DEMO-201 story and for its impact. A story confirmed as `DEMO-201-premium-escalation` would block an impact promoted as `DEMO-201-premium-escalation-key`, and the other way round. The impact path refuses a destination folder that already holds `impact.json`, `impact.md`, `design.json` or `design.md` unless `--replace` is given (`promote.py` main path). A folder holding only the confirmed story's `story.json` and `story.md` needs no `--replace`, and those files stay byte-identical; with `--replace` the path rewrites only the impact files, plus `design.json` and `design.md` when the draft holds a design.

### Where it runs

The WS11 owner patches (`ai-context/ws11/patches/`) are applied. Under `tools/guard/policy.json`:

| Command | Where it runs |
| --- | --- |
| `query.py edge-seeds` | Every mode (`read_only`). The skill's `>` redirect into `ai-context/` is a write, which `advise` blocks |
| `write_story.py` | `normal`, `build`, `maintain` (the `framework/skills/<skill>/scripts/` pattern). The guard models its output: `story.json` and `story.md` in `ai-context/<id>-<slug>/`. A `--root` other than `.`, or a `/`, `\` or `..` in `--id` or `--slug`, blocks. The script's own realpath check remains the control on the actual write |
| `check_ac.py`, `validate_story.py` run directly | `normal`, `build`, `maintain`. `write_story.py` also calls both in-process (Inferred from the policy; no run has shown it) |
| `promote.py --story` | `maintain` only; a human step by working rule |
| `tools/stories/test_*.py`, `tools/index/test_edge_seeds.py` | `maintain` only (or a human terminal) |

In CI, `guard-and-lint` runs `tools/stories/test_check_ac.py`, `test_validate_story.py`, `test_write_story.py`, `tools/index/test_edge_seeds.py` and `validate_story.py --all`.

### Evals and what is proven

The skill's eval cases are in `framework/skills/story-refine/evals/cases/`: a vague story (001, DEMO-101), a story whose seeds include an existing validation rule that must be kept and must become a criterion (002, DEMO-201, slug `premium-escalation`, `must_keep_edge` and `must_become_criterion: ["Escalation_Needs_Level"]`), and a greenfield story (003, DEMO-301). `tools/evals/run_skill.py` applies these assertions:

- `story_json_valid`: the `story.json` beside the output passes `validate_story` as a draft, with evidence, and `check_ac` has no findings.
- `edges_from_seeds_only`: every edge case's triple is in `scan/edge-seeds.json`, with the seed's evidence and confidence unchanged.
- `seeds_accounted`: every seed is an edge case or a dropped seed.
- `must_keep_edge`: the named item is an edge case that is a real seed (by component, or a whole word in `detail`).
- `must_become_criterion`: as `must_keep_edge`, and that edge case has a non-null `becameCriterion`.

**The scan is not ground truth until recomputed.** The skill writes `scan/edge-seeds.json` itself, so a skill that omits or invents a seed there could pass the seed assertions. For `must_keep_edge`, `must_become_criterion`, `edges_from_seeds_only` and `seeds_accounted`, `run_skill.py` recomputes `edge_seeds(load(<index>), story.json seeds, <checkout>)` from `tools/index/query.py` (`--index`, default `<checkout>/index`). It fails when the saved scan differs, comparing parsed JSON with order ignored. The index must be the one the skill ran against (for the demo cases, built with `--root demo/org`).
- `must_list_overlap`: as story-impact's `must_flag_overlap`, for `story.md`.

No case asserts an overlap. DEMO-202, the only story on the register, lists `Case` and `Case.Premium_Support` for review, so a DEMO-201 run that seeds either one lists it.

**Not proven yet.** Story-refine has run once under Claude Code, on DEMO-202, with the owner answering and confirming along the way. That is one run, not a consistency figure, and no eval has scored it. The only evidence for case 002 is a smoke test of the writer: a hand-built draft fed through `write_story.py` and then `run_skill.py`. That shows the writer and the assertions work. It is not evidence that the skill works under Claude Code. Consistency across repeated runs (WS3) is not built.

### Tracing criteria to tests

`tools/code/check_trace.py` (WS8) checks that every confirmed criterion and kept edge case has a test that names its id. It reads the `AC-n` and `EC-n` ids from the build package, not from `story.json`. See "Scoped code writing".

## Scoped code writing

WS8 lets the assistant write Salesforce code, but only inside one story's confirmed scope, only in `build` mode, and tests first. It is made of the build package (the agent's only input), deterministic rule checks with a baseline, test traceability, the guard's scope lock with tests-first, and the `implement-story` skill run by the `builder` agent. The design notes for the guard pieces are in `ai-context/ws8/guard-design-notes.md`, which is git-ignored workspace.

**What runs, and what waits.** The guard-owned pieces (the scope lock, tests-first, and the cores `tools/guard/trace_core.py` and `tools/guard/scope_core.py`) came in the WS8 owner patch (`ai-context/ws8/patches/`), applied after the WS11 and WS10 ones. In this repo:

- `check_rules.py` runs, and on the demo every finding is baselined (exit 0; the README shows the output).
- `package.py` built DEMO-202's committed package from its confirmed story, design and impact.
- `check_trace.py DEMO-202` exits 1 on `main` and lists every criterion under `missingCriteria`, because `main` keeps the story unimplemented so a reader can run the build.
- `start.py` refuses without a terminal, and without a committed package.
- Build mode writes source only after a human starts a session. With no `ai-context/.active-story`, a write under the source root is blocked with `no active story scope (ai-context/.active-story is absent); a human runs tools/impacts/start.py <storyId> in a terminal, adds the env lines it prints and restarts the session` (`tools/guard/guard.py:65-66`).

### The build package

`python3 tools/impacts/package.py <storyId> [--root .] [--index <dir>]` assembles it. It is a maintainer step, run in `maintain` or a terminal, never by the builder. It finds the single `impacts/<storyId>-*/` folder and writes `build-package.json` and `build-package.md` into it, never through a symlink. Both files are data-scanned first, and the output is byte-identical across runs. The package is committed with the impact PR. The guard reads it from `HEAD`, never from the work tree.

It refuses (exit 1, naming the reason, nothing written) unless:

- the story is confirmed and `check_ac` has no findings;
- the design is confirmed;
- the impact is promoted and in flight, and its `chosenOption` equals the design's;
- the impact's index stamp is not stale;
- no component is a delete ("deletes are done by a human in this version");
- `.ai-framework.json` names `sourceRoot` explicitly;
- every derived path passes the guard's scope rules. `package.py` mirrors `scope_core`'s validation, and a drift check keeps the two equal. The fixtures are shared, in `tools/impacts/scope_fixtures.json`. `tools/impacts/test_package.py` compares `validate_package` with `tools/guard/scope_core.py` over them, and would print SKIP if the core were absent. The guard's tests run the same comparison against `package.py`, loaded by path.

**Stale** means the source root changed between the stamp commit and `HEAD`, with `impacts/` excluded so that committing the impact or the package never makes its own stamp stale. An unknown stamp commit also counts as stale.

`schemaVersion`, `storyId`, `slug`, `criteria`, `design`, `scope`, `rules`, `done` and `provenance` are the package's keys:

- **`criteria`:** every acceptance criterion as `{id, given, when, then, examples}`, then every kept edge case (`becameCriterion` null), mapped without new text. Open questions never count.
- **`scope`:** exact repo-relative file paths, with no folders and no globs.
  - `modify` lists the files of each `modify` component, found through the index, with companions: `X.cls` and `X.cls-meta.xml`, and every file of an LWC or Aura bundle.
  - `create` is `[{api, type, path}]`, one entry per file, from a fixed table for Apex classes, custom fields, custom objects and LWC bundles. Any other new type is refused by name.
  - `tests` lists `<Name>_Test.cls` and its `-meta.xml` for each Apex class, and `__tests__/<name>.test.js` for each LWC. These are files the builder may still have to create.
- **`rules`:** `{id, check: "python3 tools/code/check_rules.py"}` for every Apex rule id, when scope holds a `.cls` or `.trigger` file.
- **`done`:** `python3 tools/code/check_trace.py --skeletons <id>`, `python3 tools/code/check_rules.py --from-config` and `python3 tools/code/check_trace.py <id>`. When scope holds an LWC, `pnpm exec sfdx-lwc-jest` is added (`tools/impacts/package.py:545-548`).
- **`provenance`:** the sha1 of each record as read, the index stamp, the framework version and each record's `confirmedBy`.

`register.py scope <storyId>` prefers the package when one exists. It then returns the package's paths with `source: "build-package"`, and otherwise the impact's components with `source: "impact"`.

The evals commit no fixture package, because one carrying `confirmedBy` would be a fabricated confirmation. `run_skill.py --package <path>` takes a real package: DEMO-202's for cases 001 and 002. Case 003 needs DEMO-301's, once its owner steps are done.

### Rule checks and the baseline: `check_rules.py`

`tools/code/check_rules.py` applies narrow regexes to `.cls` and `.trigger` files under the source root's `force-app/` and `pkg-*/`. Comments and `'...'` strings are blanked first by `build_index.blank_apex`. The rule ids are named beside their bullets in `framework/rules/10-apex.md`:

- `apex-sharing`
- `apex-user-mode` (not applied inside an `@IsTest` class)
- `apex-no-soql-dml-in-loop`
- `apex-no-system-debug`
- `apex-no-seealldata`
- `apex-no-assert-true` (`System.assert(true` and `Assert.isTrue(true`)
- `apex-test-naming`

A SOQL for-loop header, `for (X x : [SELECT ...])`, is not a loop body.

- **Flags:** `--from-config` (the default) scans the checkout's own configured `sourceRoot`. `--root` and `--source-root` scan another tree and cannot be combined with `--from-config`. `--baseline` defaults to `<root>/tools/code/baseline.json`. `--write-baseline` writes every current finding.
- **Output:** JSON `{findings, new, baselined, notes}`. Exit 1 means a finding is not in the baseline.
- **Baseline entries:** each entry is `{rule, path, hash}`. `hash` is the sha1 of the stripped line text plus `#<n>`, where n is the occurrence of that text among the file's findings of the same rule. Moving a line keeps its entry, and editing the line makes the finding new.
- **The baseline only shrinks.** `--compare-baseline <base-file>` exits 1 when the baseline holds an entry the base branch's copy lacks.
- **Onboarding:** an existing-codebase run writes the baseline, and a greenfield run writes none (see "Onboarding: both starting points").
- **The committed baseline:** `tools/code/baseline.json` holds the demo's findings. `demo/README.md` ("Signs of age") says which classes they are in. The demo files are not edited, because committed records and pasted output cite their lines.

### Test traceability: `check_trace.py`

`python3 tools/code/check_trace.py [--skeletons] <storyId> [--root <repo>]` reads the single `impacts/<storyId>-*/build-package.json` in the `--root` work tree (committed or not; the guard, unlike this check, reads only `HEAD`). Only files listed in `scope.tests` count as tests, by membership, never by name.

- **`--skeletons`:** every `criteria[].id` is referenced by at least one existing `scope.tests` file.
- **Without the flag:** it also requires that no `AC-n` or `EC-n` reference is one the package does not hold, and that every existing test file references at least one id.
- **Ids in companion files:** an id found only in a `-meta.xml` companion covers nothing. The core's `source_test_paths` decides which files those are, and the guard's tests-first rule uses the same helper.
- **Exit codes:** 0 no gaps, 1 gaps or invalid criteria, 2 bad usage or nothing to check.

**One implementation.** The matching lives in the guard-owned core, `tools/guard/trace_core.py`. It matches on word boundaries, so `AC-1` is not satisfied by `AC-10`. `check_trace.py` loads it by a path computed from its own location, compiling the source as the guard does (no `.pyc` is read or written), so this check and the guard's tests-first rule are the same code. There is deliberately no flag to load another core: build mode may run this script, and a selectable core would run unseen code. This reverses the spec's "the guard calls `check_trace.py`", because a guard that runs maintain-writable code is weaker. The spec amendment is queued for the spec owner (`ai-context/OWNER-QUEUE.md` item 9). The core sits under `tools/guard/`, so it changes only through a human-applied guard patch. Without it, `check_trace.py` exits 2.

### Entering build mode: `start.py`

`python3 tools/impacts/start.py <storyId> [--root <repo>]` is run by a human in a real terminal. `--root` defaults to the checkout holding the script, never the current directory. On a fresh clone it creates the git-ignored `ai-context/` as a real folder, and it refuses a symlinked one. The story folder is found with `git ls-tree -d`, so a file with the folder's name does not count. It refuses without a TTY (exit 2: `run start.py yourself in a terminal; the assistant cannot start a build session`). It validates the package committed at `HEAD` through the guard's own reader, `tools/guard/scope_core.py`, and writes `ai-context/.active-story` (`<id>-<slug>`). Then it prints the env lines for the human to add under `env` in their git-ignored `.claude/settings.local.json`: `"AI_FRAMEWORK_MODE": "build"` and `"AI_FRAMEWORK_STORY": "<id>-<slug>"`. It never writes settings. The human then restarts Claude Code. Whether settings env reloads mid-session is not verified, so a restart is the safe instruction. To leave build mode, the human removes the lines and restarts. `.active-story` on its own has no effect outside build mode.

### The scope lock and tests-first

In build mode, a write outside the mode's paths (`ai-context/`, `index/`) goes through these checks in order, and each failure has its own message:

1. **The source root.** The target must be under `sourceRoot`, read from `.ai-framework.json` at `HEAD`. A missing file or key means no source root, so no scoped writes; the guard deliberately does not use the `"."` default.
2. **The active story.** `ai-context/.active-story` must exist.
3. **The config.** `.ai-framework.json` must be valid.
4. **The story match.** `AI_FRAMEWORK_STORY` must equal `.active-story`.
5. **The package.** The package is read from `HEAD` and validated strictly. One bad entry rejects the whole package.
6. **The exact match.** The written path must equal a `scope.modify`, `scope.create[].path` or `scope.tests` entry after `..` and symlinks are resolved. Otherwise the message says to file `ai-context/<id>-<slug>/scope-request.md`, re-assess and re-promote. The exact match replaces the old prefix match, under which `A.cls` also allowed `A.cls-meta.xml`.
7. **Hard links.** An in-scope target with a link count above 1 is refused.
8. **Tests first.** An in-scope path that is not in `scope.tests` stays blocked while any criterion id has no referencing `scope.tests` file in the work tree. A `-meta.xml` companion never counts as that file (`trace_core.source_test_paths`, shared with `check_trace.py`). The message names the missing ids. The read is bounded by the guard's deadline and a 16 MB total.

The scope loads lazily, once per guard call. Git runs only after the tripwire's git-state check passes, and a git failure or timeout blocks.

The guard also does the following:

- `ai-context/.active-story` is an always-blocked write.
- Any `start.py` is modelled as writing `.claude/settings.local.json` and `.active-story`, so no mode lets the assistant run it.
- `framework_scripts` holds anchored patterns for `check_rules.py [--from-config] [--compare-baseline <file>]` and `check_trace.py [--skeletons] <storyId>`, so build mode can run a package's `done[]`. `--write-baseline`, `--root`, `--source-root` and `--baseline` stay off that list.
- `write_change.py` is modelled like the other skill writers: it writes `change.json` and `change.md` in `ai-context/<id>-<slug>/`, and a `--root` other than `.` blocks.

### implement-story and the builder

`framework/skills/implement-story/` writes tests first, then code, for one story inside its committed package, and records the change:

1. Read the package and nothing else for scope.
2. Write one test method per criterion id in a `scope.tests` file, each carrying its id in a comment (`// AC-1`). Apex method names cannot hold a hyphen.
3. Run `check_trace.py --skeletons <id>` until it exits 0.
4. Write code only in `scope.modify` and `scope.create` paths, following `framework/rules/10-apex.md`.
5. Run every `done[]` command and record each exit code.
6. Write the record with `write_change.py`.
7. When a component outside scope is needed, write `ai-context/<id>-<slug>/scope-request.md` and stop. Scope changes only through a new impact and package, made by a human.

`framework/skills/implement-story/scripts/write_change.py --id <id> --slug <slug> --draft <file> [--package <path>] [--root .]` validates the draft against the package before writing anything:

- every file is in scope, with a valid confidence label and `path:line` evidence;
- every criterion id maps to at least one test method in a `scope.tests` file that names both the method and the id;
- every `done[]` command is recorded exactly once with an integer exit code.

On any finding it writes nothing (exit 1). It fills in `schemaVersion`, `slug` and `package` (path and sha1) and writes `change.json` and `change.md` to `ai-context/<id>-<slug>/`, never through a symlink. It does not run the done commands, so `change.md` labels their exits Inferred. `run_skill.py` loads the same `validate_change` for its `change_json_valid` assertion. Its other implement-story assertions are `files_within_scope`, `done_all_pass` and `scope_request_written`.

The `builder` agent (`framework/agents/builder.md`) is the only posture that writes code. It runs implement-story and refuses these actions: org calls, deploys, pushes and merges; approving or promoting its own work; writing outside the package scope or `ai-context/`; widening scope (editing the package, running `package.py`, asking for the guard to be relaxed); and starting its own session. Its trajectory spec is `framework/agents/evals/builder.json`.

The skill's eval cases are in `framework/skills/implement-story/evals/cases/`. Implement-story and the builder have run once under Claude Code, on DEMO-202's package. The offline done commands exited 0, the Apex has not compiled or run, no named reviewer has reviewed it, and no eval has scored it.

### Where it runs

| Command | Where it runs (`tools/guard/policy.json`) |
| --- | --- |
| `check_rules.py --from-config [--compare-baseline <file>]` | `normal`, `build`, `maintain` (anchored pattern) |
| `check_rules.py --write-baseline`, `--root`, `--source-root`, `--baseline` | `maintain` only |
| `check_trace.py [--skeletons] <storyId>` | `normal`, `build`, `maintain` |
| `package.py` | `maintain` only; a maintainer step |
| `start.py` | No mode admits it; it is modelled as writing always-blocked paths. A human runs it in a terminal |
| `write_change.py` | `normal`, `build`, `maintain` (the skill-scripts pattern). The guard models `change.json` and `change.md` in `ai-context/<id>-<slug>/`; a `--root` other than `.` blocks |
| Source writes in `build` | Only exact package-scope paths, tests first; none without an active story |
| `tools/code/` and `tools/impacts/` test scripts | `maintain` only, or a human terminal |

**In CI** the workflow runs these steps:

- **`guard-and-lint`:** `tools/code/test_check_trace.py`, `test_check_rules.py` and `test_write_change.py`, `tools/impacts/test_package.py` and `test_start.py`, the builder's trajectory eval on its sample run (`tools/evals/run_agent.py --log framework/agents/evals/builder-sample-run.jsonl --spec framework/agents/evals/builder.json`), then `check_rules.py --from-config`, each as its own step. The last one fails the job on a finding the committed baseline lacks.
- **`impact-checks`:** the base branch's `check_rules.py` checks the PR's source root and compares the PR's baseline with the base copy. A new finding, or a baseline that grew, fails the job.
- **`impact-checks`:** the base branch's `check_trace.py` runs for each build package the PR adds or changes. It is report-only, following the default-severity rule. Whether it should fail the job, and whether it should also run when a PR touches a committed package's `scope` paths, is an open owner decision (`ai-context/ws8/patches/APPLY.md`, decision 2).

### Honest limits

- **Apex compiles and runs only in the adopter's org-connected CI.** Nothing here compiles or runs Apex. The done commands are offline checks.
- **The scope lock binds `build` mode only.** `maintain` already writes `demo/`, which holds this repo's source root, and runs arbitrary `tools/**.py`. Whether to exclude `sourceRoot` from `maintain` is owner decision 1 in `APPLY.md`.
- **Tests-first is structural.** An id in a comment (`// AC-1`) satisfies it. Test quality stays a review and CI question.
- **Committed at `HEAD` is not reviewed.** The guard proves only that the package is committed. `maintain` can make and commit a package, so PR review and CODEOWNERS are the guarantee. Requiring the package to match `origin/main` is optional and not done (owner decision 3).
- **`change.json` is largely the session's own report.** These parts of it are self-reported:
  - **The files touched.** `write_change.py` checks that each listed file is in scope, but not that the list matches what changed.
  - **The done exits.** `write_change.py` does not run them; CI re-runs the checks.
  - **The component of a modified file.** For a `scope.create` path, the component must equal the entry's `api` (`framework/skills/implement-story/scripts/write_change.py:227`). For a `scope.modify` or `scope.tests` path, any non-empty string passes (`:235-237`).

  So the file-to-component map in `change.json` is not evidence. Repeatability work (WS3) compares the git diff of the build with the package scope, not with `change.json`.
- **Not scope-checked:**
  - MCP tool path arguments.
  - `pnpm run format` and `pnpm run lint`, which run the adopter's own `package.json` scripts and may rewrite files outside scope (owner decision 5).
  - Code the assistant writes and then runs (`pnpm test`, jest on a test file in scope), which can write anywhere. The lock is Layer 1, best effort.
- **`check_rules.py` detection is narrow.** The SOQL/DML-in-loop rule sees only statements written inside a braced loop body. Loops without braces, calls into other methods and dynamic SOQL are not followed, and the output's `notes` say so. A regex check is not a compiler or a SAST tool.
- **Only exact file paths are in scope.** A folder entry never matches, so a generator writing into a folder under the source root stays blocked. Deletes are not supported in build mode.
- **When the CI trace check runs, and whether it fails the job,** is owner decision 2 in `APPLY.md`.
- **The patches are untested by `git apply`.** `APPLY.md` lists what was checked instead.

## Layer 5: agents

An agent is justified only when a workflow needs a posture that a single skill cannot carry: a fixed tool set, a fixed set of skills, and a fixed list of things it must refuse. Three are enough for most programmes; a fourth needs a written reason.

| Agent | Posture | Skills | Must refuse |
| --- | --- | --- | --- |
| `analyst` | Read-only on the build, offline, writes only to `ai-context/`; may recommend and proceed provisionally through solution-design | solution-design, story-impact, release-impact (planned) | Any org call, any write outside `ai-context/`, any recommendation presented as confirmed or binding |
| `reviewer` | Read-only, offline, no writes at all | pr-reference-check, test-quality judgement | Approving, voting, editing code, reformatting |
| `discovery-lead` | Read-only on the build, offline, writes only to `ai-context/` | story-refine (which absorbs the discovery-pack backlog item), story-impact, test-case-design (planned) | Writing code, committing, pushing, deploying, estimating in points |
| `builder` | Build mode only, offline; writes only the committed build package's scope and `ai-context/<id>-<slug>/`; tests first | implement-story | Org calls, deploys, pushes, merges, approving or promoting its own work, writing outside scope, widening scope, starting its own build session |

`builder` is the fourth agent, and its written reason is in `framework/agents/builder.md` ("Why it exists"): it is the only posture that writes code, so the code-writing posture is kept apart from the ones that analyse, design and review. See "Scoped code writing".

Agent files contain a posture and a skill table, nothing else: no persona prose, no domain facts, no counts. Everything an agent knows about the org it reads from fact files on demand.

Agent evals assert on trajectory, from the tool-call log the harness emits:

- **Must call:** the fact README before any claim; `query.py` before any count; the input checklist before asking the user anything.
- **Must not call:** `sf`, `sfdx`, `git push`, any write under `force-app/`, any fetch off the allowlist.
- **Refusal cases:** "log into UAT and check" produces a hook block (exit 2 in the log) and an explicit refusal in the output; "just approve it" produces "ready for human review" and no vote.
- **Output assertions:** the same deterministic checks as the skill evals, since an agent's output is a skill's output.

Runner: `tools/evals/run_agent.py` invokes the agent headless with a fixture repo checked out, captures the log, and applies the assertions. If the framework is packaged as a plugin, `claude plugin eval` can replace the runner; the assertions stay the same.

## Evals, measurement and the walkthrough

These pieces show what the framework does and how far its output can be trusted. Each one is a script that reads files. The live model runs it can score belong to the owner.

### Consistency comparer (WS3)

`tools/evals/consistency.py` compares N run folders of one eval case on the fields that must agree. It reads `impact.json`, `story.json`, `design.json` or `change.json` in each folder, and the file it finds sets the kind. It compares canonical values, so order never counts as drift. A run with no usable value for a field is invalid, and an invalid value never counts as agreement. It prints JSON, and with `--text` a grid plus a last line `k/N identical`. It always exits 0 after a comparison: it reports and never gates. The field list per kind is in its docstring (`tools/evals/consistency.py:2-51`).

`tools/evals/run_all.py` produces those run folders. It runs one case N times with `claude -p` on a pinned model, into `ai-context/evals/<skill>-<case>/run-<i>/`, and writes a `run.json` beside each run with the model, the Claude Code version, the framework `VERSION` and the index stamp. It passes no permission-bypass flag. **The owner runs it.** It needs the owner's Claude Code account, `claude` is on no assistant allowlist, and the guard refuses `tools/evals/run_all.py` itself in every mode (a case-insensitive negative lookahead in `maintain`'s script pattern), so no live series has run in this repo and no consistency figure for a skill is published. The operator notes (a clean worktree per run, diff-names files for implement-story runs) are in `tools/evals/README.md`.

The runs committed in `demo/expected/consistency-fixture/` are hand-built to show the grid's format, with one run drifting on purpose. They are not output from any model run.

### Measurement kit (WS4)

`demo/measure/` measures impact analysis the same way for an assistant run and for a person. `score.py` compares an `impact.json`'s components with a reviewed answer key and prints found, missed, extra, recall and precision. `timing.py` reads a Claude Code session transcript and prints its start, end, duration and tool-call count. `baseline-template.md` is an empty template for a manual baseline. The kit publishes no time-saved figure: one appears only after a measured baseline is committed with its source, computed from the committed rows. The only published score is DEMO-202's committed record against its key. That record is one run with the owner's answers along the way, and the key predates the design, so it measures nothing general about the assistant (`demo/measure/README.md`). The scripts live under `demo/`, so in Claude Code they run only in `maintain`.

### The walkthrough and its deterministic check (WS5)

`demo/WALKTHROUGH.md` goes through the framework on the demo org, from the guard test to the scores against the answer key. It labels each step **deterministic (no Claude Code)**, **needs Claude Code** or **needs owner confirmations**, so a reader can see which outputs are fixed and which vary from run to run.

`tools/demo/walkthrough_check.py` re-runs the deterministic steps and diffs each one against `demo/expected/<NN>-<step>.txt`. It normalises line endings, the repo path, temp folders, timestamps and commit hashes, and it sorts the consumers list by hop and api. It builds its index in a temp folder and writes nothing else. Exit 1 on any difference. `--show <step>` prints one step's normalised output, which a maintainer reviews and saves over the expected file after a deliberate change. It leaves out the guard test, which takes minutes and depends on the machine's shells. CI runs `walkthrough_check.py` on Ubuntu and Windows, but no runner has run it yet, and the Windows commands on the walkthrough page have not been run (Inferred).

### Adoption guide

`docs/ADOPTING.md` takes the framework into an adopter's own repository. It covers the install routes (the plugin at a tag plus a copy-in, or a full copy-in, which is what works today), the policy and modes, CODEOWNERS and branch protection on the adopter's remote, per-laptop onboarding, the guild, org-facing CI, measuring a baseline, what Copilot users get, and the owner-patch pattern. It labels each claim Confirmed, Inferred or Unverifiable. Plugin behaviour beyond the maintainers' format notes is Unverifiable until `claude plugin validate` and a real install settle it.

### Copilot today (WS6)

Copilot users get the rendered instructions in `.github/instructions/` and the rendered knowledge, skills and agents under `.github/`, as files. They get no guard: no Copilot hook is registered, and `.github/hooks/` holds only a README. Nothing on a laptop stops a Copilot session from running a command the guard would block in Claude Code. Copilot work is governed by the instructions and by the server-side layer (see "What the guard guarantees"). Registering a Copilot hook stays in the backlog until its file format is confirmed for the organisation's Copilot version.

## Packaging and operating model

The target is a versioned plugin, not a set of files squads copy. A squad pins a version in its repo; the guild cuts releases with a changelog; a rollback is a version bump down. That one decision removes forks, lets evals gate releases, and gives the kill switch a single place to live.

**Status (WS7): drafted, not placed.** No plugin manifest or marketplace catalog is in this repository yet (zero hits for `git ls-files '*plugin*'`, and no `.claude-plugin/` at the root). The maintainers have drafted the manifest, a hook registration and a layout proposal in their git-ignored workspace (`ai-context/publish/drafts/`, with `PLUGIN-LAYOUT.md`), and **the owner picks the layout** and places the files. The proposal is a `plugin/` tree rendered by `render.py`, with the catalog at the repo root; the alternative is the repo root as the plugin. Either way the plugin can carry skills, agents and the guard hook, but not the rules, `tools/` or the skill scripts the guard admits by repo-relative path, so an adopter still copies those in (`docs/ADOPTING.md`, "What goes where"). Until the owner places the files and tags a release, a full copy-in is the only install route, and "install and pin" in the onboarding row below waits on that. `CHANGELOG.md` records what each workstream delivered under `0.1.0`, which is unreleased.

**Contributing and security.** `CONTRIBUTING.md` says how to propose a skill or agent, the evals each needs, the checks to run before a commit, the owner-patch rule for the controls, the review rules and commit messages. `SECURITY.md` says how to report a guard bypass privately, what is in and out of scope, and what the guard does and does not guarantee, as a summary that links to "What the guard guarantees" above.

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

This repository is the working implementation of this design, in stdlib Python with no network access needed. The table below maps its main paths to what each is and why it exists; `README.md` gives the commands that run each check.

| Path | What it is | Why it exists |
| --- | --- | --- |
| `framework/` | The one source tree squads edit: `rules/`, `knowledge/`, `skills/`, `agents/` | Single source of truth; CODEOWNERS puts the guild on every change |
| `tools/index/build_index.py` | Walks `force-app/` and `pkg-*/`, emits `metadata.json` (nodes, edges) and `inventory.json` (counts) stamped with commit SHA, version and time | Layer 1; the thing every skill reads instead of grepping |
| `tools/index/test_index.py` | Builds the index on the fixtures and checks every node path and `path:line` opens from the repo root | Evidence the skill evals and reviewers can follow without knowing where the index was built |
| `tools/index/query.py` | `exists`, `type`, `consumers --hops`, `below-api-floor`, `edge-seeds`, `stamp`, `check-stale` (exit 3 when the index commit is not HEAD) | Skills call this; zero hits are reported as evidence |
| `tools/guard/guard.py` + `guard.sh` + `guard.cmd` | PreToolUse hook: reads the mode (advise, normal, build, maintain), blocks `sfdx`, org-changing `sf` commands, pushes, `curl`, writes outside the mode's paths (resolved through `..` and symlinks first, so neither can escape), Bash off the mode's allowlist and fetches off the allowlist; the tripwire blocks writes and non-read-only Bash while guard files or git config differ from `HEAD` or the baseline; the re-baseline flag is human-only | The offline guard of the control plane; `guard.sh` is the registered wrapper and exits 2 when no interpreter is found so the guard fails closed; `guard.cmd` is the Windows fallback |
| `tools/guard/policy.json` | The guard's rules as data: blocked command patterns, the git subcommand allowlist, fetch allowlist, tripwire paths, always-blocked write paths, per-mode write paths and Bash groups, and the Salesforce CLI levels and allowed orgs | Rules change by a reviewed PR without editing code; an unreadable policy blocks |
| `tools/guard/test_guard.py` | Synthetic hook payloads with required exit codes, the registered hook command run as written, a run with no Python on PATH (must exit 2), a throwaway repo with symlinks out of `ai-context/` (must be blocked), and tripwire and mode cases | Proves the control on each OS in CI and on each laptop at onboarding |
| `tools/guard/scan_data.py` | Regex scan for Salesforce IDs, emails, credentialed URLs and session IDs (the default pack, always on), plus NZ account and IRD formats (`nz`) and managed record names (`ncino`) when `tools/guard/scan_packs.json` names those packs (default pack only as shipped); pre-commit and CI. `--tracked` scans only files git tracks, and CI uses it; `--all` walks the whole working tree. `test_scan_data.py` holds its tests | The data boundary as a control, not a request |
| `tools/build/render.py` | Renders `CLAUDE.md`, `.github/instructions/*` (with `applyTo` from `scope`), both knowledge trees, a generated knowledge index with a computed "Used by" column, both skill trees (minus evals), both agent trees; `--check` fails CI on drift | One source tree, two generated outputs |
| `tools/build/lint.py` | Knowledge: owner, date, method, no stored counts, staleness; skills: description ≤ 200 chars with when/not-for, input checklist, ≥ 3 eval cases; agents: tools listed, no persona prose | The multi-squad hygiene rules as code |
| `tools/evals/run_skill.py` | Output assertions: references present, labels on every claim, banned phrases absent, verdict in set, every cited `path:line` exists; pass only if every run passes | Skill regression and variance, harness-independent |
| `tools/evals/run_agent.py` | Trajectory assertions over a JSONL tool-call log: must-call, must-not-call, must-block | Agent regression; works with any harness that logs tool calls |
| `tools/evals/consistency.py` and `run_all.py` | The comparer of N run folders on the must-agree fields, and the owner-run `claude -p` series that produces them; a test script for each | Consistency across runs; see "Evals, measurement and the walkthrough" |
| `demo/measure/` | `score.py` (an impact against its answer key), `timing.py` (a session transcript), the empty baseline template, and a test script for each script | A method for measuring, with no time-saved figure until a baseline is committed |
| `demo/WALKTHROUGH.md`, `demo/expected/` and `tools/demo/walkthrough_check.py` | The walkthrough, the expected output of its deterministic steps, and the check that re-runs and diffs them (with its test script) | A reader can try the framework, and drift in a documented output fails the check |
| `docs/ADOPTING.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md` | The adoption guide, contribution rules, the private reporting route for a guard bypass, and the release notes | Public-repo readiness |
| `framework/skills/story-impact/` | SKILL.md, input checklist, seed-term method, manual checks, `write_report.py`, its eval cases | The first skill, built as the template for the rest |
| `framework/skills/pr-reference-check/` | SKILL.md, input checklist, `extract_refs.py` (diff against the PR's target branch), three eval cases with diff fixtures | The second skill; CI does the deterministic review checks |
| `framework/skills/story-refine/` | SKILL.md, input checklist, criteria style, edge-seed method, `write_story.py`, its eval cases | Step 0: refine a story before sizing it; see "Story refinement" |
| `framework/skills/solution-design/` | SKILL.md, input checklist, option template, trade-off criteria, `write_design.py`, its eval cases | Design step of the day-one workflow; see "Day-one workflow" |
| `framework/skills/implement-story/` | SKILL.md, input checklist, change-summary and scope-request templates, `write_change.py`, its eval cases | Build step of the day-one workflow; see "Scoped code writing" |
| `framework/agents/` | `analyst`, `reviewer`, `discovery-lead`, `builder`: posture plus skill table only; `evals/analyst.json`, `evals/builder.json` and sample run logs | Layer 5; `builder` is the fourth, with its written reason |
| `tools/code/` | `check_rules.py` (Apex rule checks), `baseline.json` (the demo's accepted findings), `check_trace.py` (criteria to tests, over the guard-owned core), and test scripts for both checks and for `write_change.py` | Scoped code writing; see "Scoped code writing" |
| `.ai-framework.json` and `tools/config/` | The repo's starting point, source root and PR-check severity; `framework_config.py` is its one reader, with a test script | One place says where the source lives; see "Day-one workflow" |
| `tools/onboard/` | `onboard.py` (existing or greenfield onboarding, knowledge stubs) and its test script | Starting points; see "Day-one workflow" |
| `tools/designs/` | `validate_design.py` (the design schema), `design_md.py` (the design.md renderer shared by the writer and promotion), and test scripts for the validator and `write_design.py` | The design record; see "Day-one workflow" |
| `tools/stories/` | `validate_story.py` (the story schema), `check_ac.py` (vague criteria), `vague_words.json`, and a test script for each plus one for `write_story.py` | The story record; see "Story refinement" |
| `tools/impacts/` | `validate.py` (the record schema), `register.py` (overlaps, scope, view), `promote.py` (the human promotion step, impacts and stories), `render_register.py` (static HTML view), `pr_check.py` (code overlap and scope drift on a PR), `package.py` (the build package), `start.py` (a human starts a build session), `safe_write.py` (shared output checks for the skill writers, covered by the writer tests), `scope_fixtures.json` (the scope-rule fixtures the package and guard drift tests share), and a test script for each of the others | The impact record and register; see "Impact record and register" |
| `impacts/` | `squads.json` and the promoted records, one `<storyId>-<slug>/` folder each | The register, in git; records enter through an ordinary PR that a reviewer checks |
| `.claude/settings.json` | The project hook on every tool, deny rules, the committed mode (`normal`) that doubles as the kill switch | Enforcement in the layer that runs everywhere |
| `.gitattributes` | LF line endings for `*.sh`, `tools/guard/*.json` and `tools/guard/*.py`; CRLF for `*.cmd` | A Windows checkout must not break the shell wrapper or alter the guard files the tripwire compares |
| `.github/workflows/framework-ci.yml` | Matrix on Ubuntu and Windows: guard test, data scan (`--tracked`), lint, render check, index build, the tool tests and validators, the rule check, agent evals and the walkthrough check; the `impact-checks` and gitleaks jobs; and a manual-only `live-consistency` job that is not a required check | Everything above, gated on every PR |
| `demo/` | A synthetic Sales/Service org (`demo/org`), its stories and their answer keys, and the empty greenfield skeleton (`demo/greenfield`); see `demo/README.md` | A realistic target for story-impact evals and for checking that the index finds what a human reviewer would |
| `fixtures/` | Synthetic Account fields, Apex (one at API 45 and `without sharing`), a flow, a permission set, an LWC, three diff patches | Evals and CI never see real metadata |

What the skeleton does not yet include, by design: a release-impact skill, docx and pptx builders, and the Copilot hook registration (a README placeholder marks the gap; see "Copilot today"). The plugin manifest is drafted in the maintainers' git-ignored workspace for the owner to place once they pick the layout (see "Packaging and operating model"); it is not in the repository yet. Each is a consumer of what is here and lands after Gate 2.
