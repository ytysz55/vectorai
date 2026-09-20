# Dataset splits

Design-family-level development, validation, and locked-test split declarations live here. Derived variants must remain in the same split as their source family.

`locked_test` payloads and grants are never committed. Access requires an out-of-repository `LockedSplitGrant` whose `dataset_sha256` matches the exact manifest. CI and routine development select only development/validation families; synthetic locked fixtures exercise the guard without exposing real blind-test data. A grant is an intent/audit gate, not a substitute for storage ACLs.
