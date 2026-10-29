# Seed-term derivation

1. Nouns in the work item that name a business thing (Account, Loan, Collateral, Risk Rating) → candidate objects and fields.
2. Map each noun to API names using the index: `query.py type <Object>` then look for fields whose name contains the noun.
3. Add managed-package equivalents from `namespaces.json` (e.g. `LLC_BI__Loan__c`).
4. Add any API name the work item quotes verbatim.
5. Write one term per line to `scan/terms.txt`. State in the output which terms were derived and which were quoted.
