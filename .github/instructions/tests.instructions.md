---
applyTo: "tests/**/*.py"
---

# Test Engineering Instructions

- Reproduce the bug or invariant first.
- Add the smallest regression test that would have failed before the fix.
- Test fail-closed behavior, not only happy paths.
- Never weaken or delete a test just to make CI green.
- For market-data changes, cover provenance, timestamp semantics, delayed/research behavior, source-family independence, provider failure isolation, and structured execution authority where relevant.
- Same-bar target/stop ambiguity must never be converted into an automatic win.
- Numerical probability gates must remain sample-aware.
- Prefer deterministic fixtures over live external calls.
- Keep tests independent of paid credentials unless explicitly marked and isolated.
- Run targeted tests first, then the broadest practical suite required by `.github/workflows/test.yml`.
