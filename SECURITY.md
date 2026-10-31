# Security policy

## Reporting a guard bypass or other vulnerability

Please report privately. Don't open a public issue, discussion or PR that describes the problem.

1. Use GitHub private vulnerability reporting: the **Security** tab of this repository, then
   **Report a vulnerability**. Only the maintainers see the report.
2. If that button isn't there yet (the maintainer turns the feature on when the repository is
   published), open a public issue titled "Request for a private security contact" with no
   technical details, and a maintainer will arrange a private channel.

A useful report includes:
- the framework version (`VERSION`) and the commit;
- the operating system and shell;
- the guard mode in effect (`.claude/settings.json`, plus any local override);
- the exact tool call or command, and what the guard did against what you expected.

Use synthetic data only. Never include org exports, record IDs, credentials or session IDs in a
report.

Reports are handled by the maintainers as time allows. This is a reference project maintained on a
best-effort basis, with no response-time commitment.

## In scope

- **Guard bypasses.** The guard (`tools/guard/`) can be made to allow something its mode or
  policy forbids, such as a write outside the mode's paths, a blocked command, an org-changing
  Salesforce CLI command, a push or a fetch off the allowlist. A tripwire or kill-switch failure
  counts too, as does any path where the guard exits other than 0 or 2.
- **Data-scan misses.** `tools/guard/scan_data.py` fails to flag a pattern it claims to cover.
- **Write-boundary escapes.** A framework script writes outside `ai-context/` (or outside its
  documented output path) when it claims not to, for example through `..`, a symlink or a crafted
  `--id` or `--slug`.
- **Scope-lock escapes in `build` mode.** A source write lands outside the committed build package
  scope.
- **CI or rendered-output problems.** Something lets an unreviewed change to the control paths
  reach the default branch, where the documented setup claims it can't.

## Out of scope

- Code the assistant writes and then runs, such as a test runner executing a file in scope,
  defeating a laptop control. This is a documented, accepted limit of Layer 1 (below). A report
  that shows a new, cheaper route is still welcome.
- Behaviour of Claude Code, GitHub Copilot or Salesforce products themselves. Report those to
  their vendors.
- An adopter's own remote that lacks CODEOWNERS, branch protection or CI. The framework documents
  that setup but can't enforce it.
- Model output quality, such as a wrong impact or a missed component. Open an ordinary issue with a
  synthetic reproduction.

## What the guard does and does not guarantee

Protection comes in two layers. Read
[What the guard guarantees](docs/DESIGN.md#what-the-guard-guarantees) for the full statement.

- **Layer 1: on the laptop, best effort.** The hook, the deny rules and the tripwire stop the
  assistant from making ordinary mistakes. They also make it harder for the assistant to act on a
  hostile instruction in a file it reads. They are not a boundary against code the assistant can
  write and then run. Anything the assistant can write and then run can, in principle, defeat a
  laptop control.
- **Layer 2: on the server, the hard guarantee.** This layer is made up of:
  - CODEOWNERS plus branch protection on `tools/guard/`, `.claude/settings.json`, `.github/` and
    `CODEOWNERS`;
  - the CI workflow;
  - secret scanning and the data scan;
  - human review of every PR.

  Nothing reaches the shared branch without human review once that is enabled and confirmed on
  the remote. Until then, this layer is a plan, not a guarantee.

On this public repository, the second-reviewer rule for control-path changes is not enforced yet.
Branch protection with required reviews needs at least two maintainers. See
[CONTRIBUTING.md](CONTRIBUTING.md#review-rules).

Copilot users get the rendered instructions but no guard today.
