# Part 5 results

Written by `run_part5.py`. Tessaway Freight is a fictional company, the data is synthetic, and every owner is a fictional role.

The golden set is version 1 (owner: Head of Data; frozen 2026-10-09), scored by the Part 1 scorer against the frozen answers. The agent is Part 4's available configuration: Google ADK, `gemini-3.8-flash`, contract 2.0.0 and the SQL tool, citing its definitions. Part 5's runs come from a Cloud Run job, one execution per 24 questions; the baseline is Part 4's run from the Mac, reused, and has no traces.

One run is 1.4 points of a 72-run share and 4.2 points of a 24-run share. Small differences are not findings.

## 1. The operational signals (what a dashboard shows)

Per run, mean (standard deviation). Failed: ended in an error or a timeout.

| Phase | Runs | Failed | Latency s | Cost $ | Input tokens | Output tokens | SQL queries | Contract calls | Model calls |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline (Part 4 available, reused) | 72 | 0 | 67.0 (38.6) | 0.0376 (0.0162) | 44,742 (22,442) | 3,129 (2,127) | 2.75 (1.96) | 3.99 (1.83) | 7.53 (2.80) |
| Part 3 available (second baseline pass) | 72 | 0 | 79.3 (51.5) | 0.0362 (0.0190) | 45,595 (27,457) | 2,532 (2,266) | 2.99 (1.87) | 3.86 (2.31) | 7.81 (3.35) |
| Drift | 72 | 0 | 62.2 (40.9) | 0.0393 (0.0176) | 49,491 (28,985) | 3,192 (2,246) | 2.96 (2.09) | 4.22 (2.29) | 7.92 (3.25) |
| After the fix | 24 | 0 | 41.8 (20.6) | 0.0375 (0.0184) | 43,470 (24,622) | 3,418 (2,662) | 2.50 (1.79) | 4.08 (2.19) | 7.12 (3.04) |

Failed attempts (an error or a timeout), counting first tries that were later run again: Baseline (Part 4 available, reused) 0 of 72; Part 3 available (second baseline pass) 2 of 74 (L2#0: _ResourceExhaustedError: , L1#0: _ResourceExhaustedError: ); Drift 3 of 75 (L1#0: _ResourceExhaustedError: , L5#0: timeout, M4#0: timeout); After the fix 0 of 24

### By execution, against the green bands

Band: the baseline's per-run mean plus or minus one standard deviation. seconds 28.3213 to 105.62, cost_usd 0.0214 to 0.0538, input_tokens_total 22300.6 to 67183.9, query_count 0.7945 to 4.7055; failed runs at most 1 in 24.

| Phase | Execution | Latency s | Cost $ | Input tokens | SQL queries | Failed | Green |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline (Part 4 available, reused) | 1 | 63.9 | 0.0378 | 44,737 | 2.96 | 0 | yes |
| Baseline (Part 4 available, reused) | 2 | 70.7 | 0.0393 | 46,365 | 2.88 | 0 | yes |
| Baseline (Part 4 available, reused) | 3 | 66.4 | 0.0358 | 43,125 | 2.42 | 0 | yes |
| Part 3 available (second baseline pass) | 1 | 87.1 | 0.0389 | 50,103 | 3.25 | 2 | NO |
| Part 3 available (second baseline pass) | 2 | 74.2 | 0.0346 | 42,846 | 2.79 | 0 | yes |
| Part 3 available (second baseline pass) | 3 | 76.8 | 0.0351 | 43,836 | 2.92 | 0 | yes |
| Drift | 1 | 89.5 | 0.0401 | 50,276 | 2.96 | 3 | NO |
| Drift | 2 | 56.1 | 0.0381 | 46,548 | 2.58 | 0 | yes |
| Drift | 3 | 41.0 | 0.0395 | 51,647 | 3.33 | 0 | yes |
| After the fix | 1 | 41.8 | 0.0375 | 43,470 | 2.50 | 0 | yes |

## 2. The answers

Right / confidently wrong / declined / no answer.

| Phase | Runs | Overall | Lookup | Metric | Entity | Rule |
| --- | --- | --- | --- | --- | --- | --- |
| Baseline (Part 4 available, reused) | 72 | 72 / 0 / 0 / 0 | 18 / 0 / 0 / 0 | 18 / 0 / 0 / 0 | 18 / 0 / 0 / 0 | 18 / 0 / 0 / 0 |
| Part 3 available (second baseline pass) | 72 | 72 / 0 / 0 / 0 | 18 / 0 / 0 / 0 | 18 / 0 / 0 / 0 | 18 / 0 / 0 / 0 | 18 / 0 / 0 / 0 |
| Drift | 72 | 60 / 12 / 0 / 0 | 18 / 0 / 0 / 0 | 12 / 6 / 0 / 0 | 15 / 3 / 0 / 0 | 15 / 3 / 0 / 0 |
| After the fix | 24 | 24 / 0 / 0 / 0 | 6 / 0 / 0 / 0 | 6 / 0 / 0 / 0 | 6 / 0 / 0 / 0 | 6 / 0 / 0 / 0 |

### By execution

| Phase | Execution | Right / wrong / declined / no answer |
| --- | --- | --- |
| Baseline (Part 4 available, reused) | 1 | 24 / 0 / 0 / 0 |
| Baseline (Part 4 available, reused) | 2 | 24 / 0 / 0 / 0 |
| Baseline (Part 4 available, reused) | 3 | 24 / 0 / 0 / 0 |
| Part 3 available (second baseline pass) | 1 | 24 / 0 / 0 / 0 |
| Part 3 available (second baseline pass) | 2 | 24 / 0 / 0 / 0 |
| Part 3 available (second baseline pass) | 3 | 24 / 0 / 0 / 0 |
| Drift | 1 | 20 / 4 / 0 / 0 |
| Drift | 2 | 20 / 4 / 0 / 0 |
| Drift | 3 | 20 / 4 / 0 / 0 |
| After the fix | 1 | 24 / 0 / 0 / 0 |

### The questions that moved

| Phase | Question | Right / wrong / declined / no answer | Answers | Decoys matched |
| --- | --- | --- | --- | --- |
| Drift | M2 | 0 / 3 / 0 / 0 | 10134528.894054, 10134528.894054, 10134528.894054 | - |
| Drift | M3 | 0 / 3 / 0 / 0 | 403.112811604, 403.112811604, 403.112811604 | - |
| Drift | E3 | 0 / 3 / 0 / 0 | 1252448.312611, 1252448.312611, 1252448.312611 | - |
| Drift | R3 | 0 / 3 / 0 / 0 | 826718.544054, 826718.544054, 826718.544054 | - |
| After the fix | M2 | 1 / 0 / 0 / 0 | 10294019.115413 | - |
| After the fix | M3 | 1 / 0 / 0 / 0 | 409.186793016 | - |
| After the fix | E3 | 1 / 0 / 0 / 0 | 1299690.263658 | - |
| After the fix | R3 | 1 / 0 / 0 / 0 | 986208.765413 | - |

## 3. The alert rule

Rule: Fire when the share of runs scored right in any question group is lower than that group's share in the baseline (Part 4 available, 72 runs).

| Phase | Execution | Fired | Groups below the baseline | Runs not right |
| --- | --- | --- | --- | --- |
| Baseline (Part 4 available, reused) | 1 | no | - | - |
| Baseline (Part 4 available, reused) | 2 | no | - | - |
| Baseline (Part 4 available, reused) | 3 | no | - | - |
| Part 3 available (second baseline pass) | 1 | no | - | - |
| Part 3 available (second baseline pass) | 2 | no | - | - |
| Part 3 available (second baseline pass) | 3 | no | - | - |
| Drift | 1 | yes | metric, entity, rule | E3/confidently_wrong, M2/confidently_wrong, M3/confidently_wrong, R3/confidently_wrong |
| Drift | 2 | yes | metric, entity, rule | E3/confidently_wrong, M2/confidently_wrong, M3/confidently_wrong, R3/confidently_wrong |
| Drift | 3 | yes | metric, entity, rule | E3/confidently_wrong, M2/confidently_wrong, M3/confidently_wrong, R3/confidently_wrong |
| After the fix | 1 | no | - | - |

### Every verdict the job raised, in order (from Cloud Logging)

A retry pass on an execution raises a second verdict for it. The table above recomputes the rule from the final records.

| Time (UTC) | Phase | Execution | Verdict | Right of runs | Groups below | Runs not right |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-15T02:59:31 | smoke | 1 | fired | 3 of 4 | rule | R3/no_answer |
| 2026-10-15T03:07:41 | smoke | 2 | fired | 0 of 1 | lookup | L1/no_answer |
| 2026-10-15T03:29:05 | drift | 1 | fired | 17 of 24 | lookup, metric, entity, rule | E3/confidently_wrong, L1/no_answer, L5/no_answer, M2/confidently_wrong, M3/confidently_wrong, M4/no_answer, R3/confidently_wrong |
| 2026-10-15T03:35:16 | drift | 1 | fired | 20 of 24 | metric, entity, rule | E3/confidently_wrong, M2/confidently_wrong, M3/confidently_wrong, R3/confidently_wrong |
| 2026-10-15T03:43:39 | drift | 2 | fired | 20 of 24 | metric, entity, rule | E3/confidently_wrong, M2/confidently_wrong, M3/confidently_wrong, R3/confidently_wrong |
| 2026-10-15T03:46:04 | drift | 2 | fired | 20 of 24 | metric, entity, rule | E3/confidently_wrong, M2/confidently_wrong, M3/confidently_wrong, R3/confidently_wrong |
| 2026-10-15T03:51:54 | drift | 3 | fired | 20 of 24 | metric, entity, rule | E3/confidently_wrong, M2/confidently_wrong, M3/confidently_wrong, R3/confidently_wrong |
| 2026-10-15T03:54:09 | drift | 3 | fired | 20 of 24 | metric, entity, rule | E3/confidently_wrong, M2/confidently_wrong, M3/confidently_wrong, R3/confidently_wrong |
| 2026-10-15T04:02:17 | after_fix | 1 | quiet | 24 of 24 | - | - |
| 2026-10-15T04:04:24 | after_fix | 1 | quiet | 24 of 24 | - | - |

Time to detection: the first drift execution that fired was execution 1 of 3. The job's own verdicts (`alerts/*.json`) are in `summary.json` beside these, recomputed from the same records.

## 4. Where the trace points

Newly wrong runs (not right, on questions the baseline got right in every run): 12; 12 cite at least one definition.

- Cited: {'revenue@1': 9, 'customer@1': 3, 'margin@1': 3}
- Served by the contract in those runs: {'revenue@1': 12, 'currency@1': 7, 'customer@1': 7, 'billable@1': 6, 'margin@1': 5, 'load@1': 4, 'portal_on_time@1': 3, 'delivered_load@1': 3, 'on_time@1': 1}
- Cited by every citing run: none; most cited: revenue@1
- Owners of what they cite: {'VP Account Management': 3, 'Controller': 12}; runs citing a Controller definition: 12
- Runs citing `currency@1`: 0; runs in which the contract served `currency@1`: 7

## 5. The traces

| Phase | Runs | Traces | Complete and agreeing | Spans per trace | Problems |
| --- | --- | --- | --- | --- | --- |
| Drift | 72 | 75 | 72 | 34.6 | - |
| After the fix | 24 | 24 | 24 | 32.3 | - |

## 6. The drift, measured without a model

The reviewed gold SQL, run against the copy in each state. This is what the answer key would say if it were recomputed; nothing is scored against it.

| State | Rows with a changed amount | Row counts and types as the record | Out of tolerance | M2 | M3 | M4 | E3 | R3 | R6 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| after_revert | 0 | yes | 0: - | 10294019.12 (+0.00%) | 409.19 (+0.00%) | 13.24 (+0.00%) | 1299690.26 (+0.00%) | 986208.77 (+0.00%) | 3050.0 (+0.00%) |
| clean | 0 | yes | 0: - | 10294019.12 (+0.00%) | 409.19 (+0.00%) | 13.24 (+0.00%) | 1299690.26 (+0.00%) | 986208.77 (+0.00%) | 3050.0 (+0.00%) |
| clean_after_revert | 0 | yes | 0: - | 10294019.12 (+0.00%) | 409.19 (+0.00%) | 13.24 (+0.00%) | 1299690.26 (+0.00%) | 986208.77 (+0.00%) | 3050.0 (+0.00%) |
| forward_from_oct1 | 28 | yes | 0: - | 10294019.12 (+0.00%) | 409.19 (+0.00%) | 13.24 (+0.00%) | 1299690.26 (+0.00%) | 986208.77 (+0.00%) | 3050.0 (+0.00%) |
| from_sep1 | 179 | yes | 1: R3 | 10248876.91 (-0.44%) | 407.56 (-0.40%) | 13.25 (+0.08%) | 1289937.62 (-0.75%) | 941066.56 (-4.58%) | 3050.0 (+0.00%) |
| restated | 1610 | yes | 4: M2, M3, E3, R3 | 10134528.89 (-1.55%) | 403.11 (-1.49%) | 13.25 (+0.08%) | 1252448.31 (-3.63%) | 826718.54 (-16.17%) | 3050.0 (+0.00%) |

## 7. The server's record

402 of 402 recorded contract calls agree with the server log (0 refused by the MCP layer before the contract ran); 0 log lines not in a record; 96 of 96 runs agree in full. Callers: {'tw-p5-check': 402}.

## Predictions

As written in `predictions.md` before the first scored run, each tested by its own rule.

| # | Held | Numbers |
| --- | --- | --- |
| P1 | NO | e1: seconds 89.4833, cost_usd 0.0401, input_tokens_total 50276.4583, query_count 2.9583, failed_runs 3 OUT; e2: seconds 56.1375, cost_usd 0.0381, input_tokens_total 46548.0833, query_count 2.5833, failed_runs 0; e3: seconds 40.9625, cost_usd 0.0395, input_tokens_total 51647.25, query_count 3.3333, failed_runs 0 |
| P2 | yes | right 60 of 72; not right on M2, M3, E3, R3: 12 of 12 |
| P3 | yes | lookups right 18 of 18; the other 20 questions right 60 of 60 (missed: []) |
| P4 | yes | confidently wrong 12 of 12 not-right runs on the four; matching a decoy 0 |
| P5 | NO | fired on executions [1, 2, 3] of [1, 2, 3]; groups below: [['lookup', 'metric', 'entity', 'rule'], ['metric', 'entity', 'rule'], ['metric', 'entity', 'rule']] |
| P6 | yes | baseline executions fired 0 of 6; after the fix fired 0 of 1 |
| P7 | yes | right 24 of 24 |
| P8 | yes | 12 newly wrong runs, 12 citing; 12 cite a Controller definition; most cited revenue@1; citing currency@1 0; cited {'revenue@1': 9, 'customer@1': 3, 'margin@1': 3} |
| P9 | yes | 96 of 96 runs with a complete, agreeing trace; problems [] |
| P10 | yes | mean model cost per run $0.0393 (baseline $0.0376; the line is $0.0451) |
| P11 | yes | 402 of 402 calls agree (0 refused before the contract ran); 0 server lines not in a record |

## Spend

- Gemini (model) $3.96 and BigQuery $0.0545: $4.01 for Part 5, smoke test included.

Model names and prices as checked for the series in `tessaway/config.py`. Costs are estimates.
