# Trade-off criteria: solution-design

Each trade-off names one `criterion` from this list and a `note`. The note states a finding with evidence (`path:line`) or names the missing input and the owner role who holds it. It never states a number the build does not show.

| Criterion | What the note covers |
|---|---|
| `security` | Sharing declarations, user-mode access, permission sets and field access the option relies on or changes |
| `governor-limits` | SOQL and DML per transaction, loops, trigger context, async needs |
| `data-volume` | Record volumes and bulk loads; volumes are org data, so Unverifiable unless an input states them |
| `licence-fit` | Features or licences the option needs; Unverifiable unless an input states the licences held |
| `maintainability` | How many places hold the logic, test classes affected, in-flight stories on the same components (from the register) |
| `reuse` | Existing components the option builds on, or what the build already does for the do-nothing option |
