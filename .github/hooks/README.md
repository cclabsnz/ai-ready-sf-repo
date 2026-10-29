# Copilot hook parity

Copilot supports lifecycle hooks (preview in VS Code; available in Copilot CLI and the coding agent).
Register `tools/guard/guard.sh` (or `guard.cmd`) as the pre-tool hook here so Copilot users get
the same offline guard as Claude Code users. Until this is configured, Copilot users are governed
by prose only and the onboarding checklist must say so.
