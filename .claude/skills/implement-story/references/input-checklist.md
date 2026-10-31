# Input checklist: implement-story

| Input | Required | Unlocks | If missing |
|---|---|---|---|
| Build mode: a human ran `tools/impacts/start.py <id>`, pasted the env lines and restarted the session | Yes | Writes inside the package scope | Stop; the guard refuses every write under the source root. Name the step for the human |
| Story ID and slug | Yes | Package location `impacts/<id>-<slug>/` and output folder `ai-context/<id>-<slug>/` | Ask once |
| `impacts/<id>-<slug>/build-package.json`, committed | Yes | Criteria, scope, rules, done commands | Stop; a maintainer runs `tools/impacts/package.py <id>` after the owner confirms the story, design and impact |
| `criteria[]` in the package | Yes | One test skeleton per id | The package is refused by the guard; stop and report |
| `scope.modify`, `scope.create`, `scope.tests` | Yes | Where code and tests may be written | A needed file that is not listed is a scope request (Step 7), never a write |
| `rules[]` and `done[]` | Yes | The checks the change has to pass | Report the package as incomplete |
| Anything else (story text, design notes, chat) | No | Nothing: the package is the only input | Ignore it for scope; raise a conflict with the package as a scope request |

Attached files are copied to `ai-context/<id>-<slug>/inputs/` (git-ignored). Never move the user's original.
