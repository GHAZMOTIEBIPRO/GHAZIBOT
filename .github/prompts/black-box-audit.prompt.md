# BLACK BOX OMEGA — Repository Audit

Audit the latest `main` of this repository as a principal engineer and financial-data reliability reviewer.

Read `AGENTS.md` and repository instructions first.

Inspect:
- recent commits and open PRs;
- data-fabric/provider paths;
- three intelligence paths;
- V11/execution gates;
- target learning, failure attribution, and similar cases;
- workflow topology, concurrency, schedules, state ownership, and artifacts;
- Telegram dedupe/freshness;
- tests and CI.

Find only evidence-backed issues. For each issue record:
- severity P0/P1/P2/P3;
- concrete file/function/workflow;
- root cause;
- affected state/data path;
- regression test needed;
- smallest safe fix.

Prioritize correctness, data honesty, security, runtime reliability, and false-confidence prevention over cosmetic work.

Do not stop at a report when implementation is authorized: fix the highest-value safe issue on a branch, test it, open a PR, and follow CI to green.
