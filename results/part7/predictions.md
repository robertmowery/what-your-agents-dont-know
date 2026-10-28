# Part 7 predictions

Written 2026-10-27, before any Part 7 agent run, after revenue version 2, margin version 2, their gold SQL and golden set v2 were committed. Every number is checked by `analysis/part7_article_numbers.py` from the run records. Tessaway Freight is a fictional company.

The phases: **canary** (repeat 2 of each question routed to revenue version 2 with margin untouched, repeats 0 and 1 on version 1; 72 runs), **rollback** (routing back to version 1 for everyone by a new revision, then 72 runs), **rollout** (revenue version 2 and margin version 2 for everyone; 72 runs). Version 1 runs are scored against golden set v1, version 2 runs against golden set v2.

| # | Prediction | How it is checked |
|---|---|---|
| P1 | In the canary, the 48 version 1 runs are right at least 46 times, as in Part 4 (72 of 72). | outcome, canary, expected state v1 |
| P2 | In the canary, the version 2 runs of M2, E3 and R3 (one each) are right against golden set v2 and cite revenue version 2. | outcome and citations |
| P3 | In the canary, the version 2 runs of M3 and M4 are not right, and at least one of them matches the figure for revenue version 2 with carrier cost still on version 1 dates: the dependent nobody listed. | outcome, matched_mixed |
| P4 | E1 (largest customer) gives the same name in every phase and is right in every run. | outcome for E1 |
| P5 | The 18 questions revenue does not reach are right in at least 17 of their 18 version 2 runs in the canary. | outcome |
| P6 | Every run is served the versions its routing says, and no other: no version 2 stamp in a version 1 run and no version 1 revenue stamp in a version 2 run. | served_versions against expected state |
| P7 | The rollback is one command, takes under 10 minutes from the command to the service serving the new routing, and no run fails while it happens (no run is in flight). | routing_changes.jsonl |
| P8 | After the rollback, at least 70 of 72 runs are right against golden set v1, and none is served revenue version 2. | outcome, served_versions |
| P9 | In the rollout, at least 70 of 72 runs are right against golden set v2, and M3 and M4 are right in all three repeats. | outcome |
| P10 | No version 2 run gives the version 1 figure for M2, E3 or R3. | matched_decoy |
| P11 | Cost per correct answer in each phase is within 20% of Part 4's 3.79 cents. | tessaway/meter.py |
