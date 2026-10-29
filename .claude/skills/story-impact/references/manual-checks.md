# Manual checks the index cannot do

| Check | Why | How |
|---|---|---|
| Order of execution | A trigger and a record-triggered flow on the same object interact | List both from the index, then read each for DML on the same object |
| Dynamic SOQL | String-built queries hide field references | grep for `Database.query(` in consumer classes and read the string |
| `without sharing` reach | Elevated-context classes change who sees what | From `inventory.json`, list `without sharing` consumers and read why |
| Required-field impact | A new required field breaks existing inserts | For each new required field, list every insert path from the consumers |
| Managed-package behaviour | Not in the repo | Mark Unverifiable; name the package and the behaviour assumed |
