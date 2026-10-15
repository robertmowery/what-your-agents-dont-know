# Part 3 results

Written by `run_part3.py`. Tessaway Freight is a fictional company and the data is synthetic.

The Part 2 layers served as one contract (version 1.0.0) by an MCP server on Cloud Run, called by the Part 2 agent (Google ADK, `gemini-3.8-flash`) under its own service account. **available**: the contract and the SQL tool. **routed**: the contract only. Each reply is scored by the Part 1 scorer, unchanged.

Three runs per question: one run is 1.4 points of a 72-run share, 2.8 points of a 36-run share and 5.6 points within a question group of six. Small differences are not findings.

| Configuration | Questions | Tools | Runs | Complete | Right | Confidently wrong | Declined | No answer | Est. cost | Cost per question |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| available | part1 (24) | 5 | 72 of 72 | yes | 100.0% (72) | 0.0% (0) | 0.0% (0) | 0.0% (0) | $2.61 | $0.0362 |
| routed | part1 (24) | 4 | 72 of 72 | yes | 80.6% (58) | 0.0% (0) | 19.4% (14) | 0.0% (0) | $2.31 | $0.0321 |
| routed_holdout | holdout (12) | 4 | 36 of 36 | yes | 86.1% (31) | 5.6% (2) | 8.3% (3) | 0.0% (0) | $1.53 | $0.0424 |

## By question group: right / confidently wrong / declined / no answer

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| available | 18 / 0 / 0 / 0 | 18 / 0 / 0 / 0 | 18 / 0 / 0 / 0 | 18 / 0 / 0 / 0 |
| routed | 4 / 0 / 14 / 0 | 18 / 0 / 0 / 0 | 18 / 0 / 0 / 0 | 18 / 0 / 0 / 0 |
| routed_holdout | n/a | 12 / 0 / 0 / 0 | 12 / 0 / 0 / 0 | 7 / 2 / 3 / 0 |

## 1. Where each answer came from

Worked out in code (`tessaway/answer_source.py`) by matching the value on the final `ANSWER:` line against every value the contract and the SQL tool returned in the run. The agent's own account is not used. "both" means the two routes returned the same value. Each cell: runs (of which right).

| Configuration | Runs | contract | sql | both | neither | no answer value |
| --- | --- | --- | --- | --- | --- | --- |
| available | 72 | 15 (15 right) | 18 (18 right) | 39 (39 right) | 0 (0 right) | 0 (0 right) |
| routed | 72 | 54 (54 right) | 0 (0 right) | 0 (0 right) | 4 (4 right) | 14 (0 right) |
| routed_holdout | 36 | 21 (19 right) | 0 (0 right) | 0 (0 right) | 12 (12 right) | 3 (0 right) |

### By question group

| Configuration | Group | Runs | contract | sql | both | neither | no answer value |
| --- | --- | --- | --- | --- | --- | --- | --- |
| available | lookup | 18 | 0 (0 right) | 18 (18 right) | 0 (0 right) | 0 (0 right) | 0 (0 right) |
| available | metric | 18 | 8 (8 right) | 0 (0 right) | 10 (10 right) | 0 (0 right) | 0 (0 right) |
| available | entity | 18 | 2 (2 right) | 0 (0 right) | 16 (16 right) | 0 (0 right) | 0 (0 right) |
| available | rule | 18 | 5 (5 right) | 0 (0 right) | 13 (13 right) | 0 (0 right) | 0 (0 right) |
| routed | lookup | 18 | 0 (0 right) | 0 (0 right) | 0 (0 right) | 4 (4 right) | 14 (0 right) |
| routed | metric | 18 | 18 (18 right) | 0 (0 right) | 0 (0 right) | 0 (0 right) | 0 (0 right) |
| routed | entity | 18 | 18 (18 right) | 0 (0 right) | 0 (0 right) | 0 (0 right) | 0 (0 right) |
| routed | rule | 18 | 18 (18 right) | 0 (0 right) | 0 (0 right) | 0 (0 right) | 0 (0 right) |
| routed_holdout | metric | 12 | 9 (9 right) | 0 (0 right) | 0 (0 right) | 3 (3 right) | 0 (0 right) |
| routed_holdout | entity | 12 | 6 (6 right) | 0 (0 right) | 0 (0 right) | 6 (6 right) | 0 (0 right) |
| routed_holdout | rule | 12 | 6 (4 right) | 0 (0 right) | 0 (0 right) | 3 (3 right) | 3 (0 right) |

## 2. Tool calls

Mean calls per run (runs that called it). Calls refused over a limit are not counted.

| Configuration | `run_sql` | `lookup_definition` | `compute_metric` | `check_rule` | `resolve_entity` | No contract call | No SQL | First call SQL | First call contract |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| available | 2.99 (69) | 1.86 (65) | 1.18 (54) | 0.65 (35) | 0.17 (12) | 3 | 3 | 14 | 58 |
| routed | 0.00 (0) | 2.38 (72) | 2.06 (68) | 0.90 (54) | 0.92 (29) | 0 | 72 | 0 | 72 |
| routed_holdout | 0.00 (0) | 2.56 (36) | 2.92 (36) | 1.00 (28) | 0.33 (10) | 0 | 36 | 0 | 36 |

On the questions one metric answers (available, 54 runs): `compute_metric` called in 54, SQL run in 51, both in 51, SQL without the metric in 0, the contract without SQL in 3.

## 3. What the second route costs: per question, available against routed

| Configuration | SQL queries | Input tokens | Output tokens | Model calls | Seconds | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| available | 2.99 | 45,595 | 2,532 | 7.81 | 79.3 | $0.0362 |
| routed | 0.00 | 37,624 | 2,695 | 7.11 | 43.3 | $0.0321 |
| routed_holdout | 0.00 | 39,942 | 4,830 | 7.19 | 58.7 | $0.0424 |

| Question | Group | SQL queries (available) | Cost available | Cost routed | Seconds available | Seconds routed |
| --- | --- | --- | --- | --- | --- | --- |
| L1 | lookup | 5.67 | $0.0380 | $0.0532 | 75.1 | 62.8 |
| L2 | lookup | 3.33 | $0.0212 | $0.0426 | 28.8 | 48.5 |
| L3 | lookup | 1.0 | $0.0069 | $0.0520 | 23.3 | 77.0 |
| L4 | lookup | 1.0 | $0.0103 | $0.0330 | 33.2 | 31.9 |
| L5 | lookup | 1.67 | $0.0165 | $0.0306 | 26.7 | 40.5 |
| L6 | lookup | 1.67 | $0.0153 | $0.0980 | 59.3 | 141.7 |
| M1 | metric | 1.33 | $0.0572 | $0.0371 | 98.0 | 62.3 |
| M2 | metric | 2.67 | $0.0519 | $0.0329 | 99.4 | 39.5 |
| M3 | metric | 1.0 | $0.0551 | $0.0481 | 110.7 | 80.8 |
| M4 | metric | 1.0 | $0.0388 | $0.0339 | 77.8 | 43.5 |
| M5 | metric | 3.33 | $0.0287 | $0.0105 | 98.4 | 23.0 |
| M6 | metric | 7.0 | $0.0576 | $0.0269 | 106.2 | 24.0 |
| E1 | entity | 1.0 | $0.0218 | $0.0123 | 40.6 | 21.7 |
| E2 | entity | 4.0 | $0.0353 | $0.0126 | 81.2 | 15.8 |
| E3 | entity | 4.67 | $0.0842 | $0.0540 | 196.4 | 66.4 |
| E4 | entity | 1.33 | $0.0184 | $0.0087 | 39.8 | 15.6 |
| E5 | entity | 4.0 | $0.0378 | $0.0232 | 71.7 | 25.9 |
| E6 | entity | 4.0 | $0.0401 | $0.0267 | 121.6 | 30.2 |
| R1 | rule | 3.67 | $0.0360 | $0.0164 | 116.2 | 24.0 |
| R2 | rule | 3.33 | $0.0330 | $0.0165 | 68.3 | 22.8 |
| R3 | rule | 4.67 | $0.0595 | $0.0540 | 125.8 | 75.5 |
| R4 | rule | 3.67 | $0.0286 | $0.0088 | 80.4 | 14.2 |
| R5 | rule | 2.0 | $0.0353 | $0.0217 | 39.1 | 25.5 |
| R6 | rule | 4.67 | $0.0414 | $0.0179 | 86.3 | 25.4 |

## 4. What routing breaks: the six lookups and H11, routed

| Question | Run | What it did | Final answer | Correct | Operations called |
| --- | --- | --- | --- | --- | --- |
| L1 | 1 | declined | NEEDS_CLARIFICATION | 65 | lookup_definition, check_rule, resolve_entity, compute_metric, lookup_definition, check_rule, compute_metric |
| L1 | 2 | answered right from neither | 65 | 65 | lookup_definition, check_rule, check_rule, resolve_entity, lookup_definition, compute_metric, compute_metric, compute_metric, resolve_entity, resolve_entity, lookup_definition, compute_metric, compute_metric, resolve_entity, resolve_entity, resolve_entity, resolve_entity |
| L1 | 3 | declined | NEEDS_CLARIFICATION | 65 | lookup_definition, check_rule, lookup_definition, check_rule, compute_metric, resolve_entity, lookup_definition, compute_metric, compute_metric |
| L2 | 1 | declined | NEEDS_CLARIFICATION | 11 | lookup_definition, lookup_definition, check_rule, lookup_definition, lookup_definition, lookup_definition, lookup_definition, resolve_entity, compute_metric, resolve_entity, compute_metric |
| L2 | 2 | declined | NEEDS_CLARIFICATION | 11 | lookup_definition, lookup_definition, lookup_definition, check_rule, resolve_entity, resolve_entity, lookup_definition, lookup_definition |
| L2 | 3 | declined | NEEDS_CLARIFICATION | 11 | lookup_definition, lookup_definition, lookup_definition, lookup_definition, check_rule, resolve_entity, lookup_definition, lookup_definition, compute_metric, resolve_entity |
| L3 | 1 | declined | NEEDS_CLARIFICATION | Green Bay | resolve_entity, resolve_entity, compute_metric, lookup_definition, check_rule, resolve_entity, resolve_entity, lookup_definition, resolve_entity, resolve_entity, lookup_definition, compute_metric, compute_metric, compute_metric, compute_metric, compute_metric |
| L3 | 2 | declined | NEEDS_CLARIFICATION | Green Bay | resolve_entity, resolve_entity, resolve_entity, lookup_definition, check_rule, compute_metric, compute_metric, compute_metric, lookup_definition, lookup_definition, resolve_entity, resolve_entity, resolve_entity |
| L3 | 3 | declined | NEEDS_CLARIFICATION | Green Bay | resolve_entity, resolve_entity, resolve_entity, compute_metric, lookup_definition, check_rule, resolve_entity, compute_metric, compute_metric, resolve_entity, lookup_definition, resolve_entity |
| L4 | 1 | declined | NEEDS_CLARIFICATION | BHRI | resolve_entity, lookup_definition, lookup_definition, check_rule, compute_metric, resolve_entity, lookup_definition |
| L4 | 2 | declined | NEEDS_CLARIFICATION | BHRI | resolve_entity, lookup_definition, lookup_definition, check_rule, compute_metric, lookup_definition, resolve_entity, lookup_definition |
| L4 | 3 | declined | NEEDS_CLARIFICATION | BHRI | resolve_entity, lookup_definition, lookup_definition, check_rule, compute_metric, resolve_entity, lookup_definition |
| L5 | 1 | declined | NEEDS_CLARIFICATION | 638 | resolve_entity, lookup_definition, lookup_definition, check_rule, lookup_definition |
| L5 | 2 | declined | NEEDS_CLARIFICATION | 638 | resolve_entity, lookup_definition, lookup_definition, check_rule, lookup_definition, lookup_definition |
| L5 | 3 | declined | NEEDS_CLARIFICATION | 638 | resolve_entity, lookup_definition, lookup_definition, check_rule, lookup_definition, lookup_definition, resolve_entity |
| L6 | 1 | answered right from neither | 0.7318 | 0.7318 | lookup_definition, check_rule, lookup_definition, lookup_definition, lookup_definition, compute_metric, compute_metric, resolve_entity, resolve_entity, compute_metric, compute_metric, resolve_entity, lookup_definition, lookup_definition, lookup_definition, compute_metric, lookup_definition, compute_metric, resolve_entity, resolve_entity |
| L6 | 2 | answered right from neither | 0.7318 | 0.7318 | lookup_definition, check_rule, resolve_entity, lookup_definition, lookup_definition, compute_metric, compute_metric, resolve_entity, lookup_definition, lookup_definition, compute_metric, compute_metric, compute_metric, compute_metric, compute_metric, compute_metric |
| L6 | 3 | answered right from neither | 0.7318 | 0.7318 | lookup_definition, check_rule, resolve_entity, compute_metric, compute_metric, compute_metric, resolve_entity, resolve_entity |
| H11 | 1 | declined | NEEDS_CLARIFICATION | 27 | lookup_definition, lookup_definition, compute_metric, check_rule, compute_metric, lookup_definition, lookup_definition, lookup_definition, check_rule, check_rule, lookup_definition |
| H11 | 2 | declined | NEEDS_CLARIFICATION | 27 | lookup_definition, lookup_definition, check_rule, check_rule, compute_metric, compute_metric, lookup_definition, lookup_definition, lookup_definition, compute_metric, resolve_entity |
| H11 | 3 | declined | NEEDS_CLARIFICATION | 27 | lookup_definition, lookup_definition, lookup_definition, check_rule, compute_metric, check_rule, compute_metric, lookup_definition, lookup_definition, compute_metric |

## 5. Versions and the server's record

- available: 277 of 277 contract responses carried a version and a response ID; versions seen {'1.0.0': 277}.
- routed: 450 of 450 contract responses carried a version and a response ID; versions seen {'1.0.0': 450}.
- routed_holdout: 245 of 245 contract responses carried a version and a response ID; versions seen {'1.0.0': 245}.
- Server log against the agents' records: 972 of 973 recorded calls agree (same response ID, operation, version and caller); 0 recorded calls missing from the log; 0 log lines not in an agent's record; 180 of 180 runs agree in full. See `server_log_check.md`.
- Secured: no token -> HTTP 403, refused (as expected).
- Secured: a token with a forged signature -> HTTP 401, refused (as expected).
- Secured: the routed agent's ID token -> HTTP 200, accepted (as expected).

## Limits and failures

| Configuration | Model-call ceiling | Refused a further SQL query | Refused a further contract call | Hit the ceiling | Timed out | Ended in an error |
| --- | --- | --- | --- | --- | --- | --- |
| available | 48 | 0 | 0 | 0 | 0 | 0 |
| routed | 48 | 0 | 2 | 0 | 0 | 0 |
| routed_holdout | 48 | 0 | 1 | 0 | 0 | 0 |

## Predictions

As written in `predictions.md` before the first scored run, each tested by its own rule.

| # | Held | Numbers |
| --- | --- | --- |
| P1 | yes | contract 15, sql 18, both 39, neither 0, no_answer_value 0 |
| P2 | yes | 18 of 18 lookup runs with an answer value from SQL alone |
| P3 | yes | ran SQL in 51 of 54; called compute_metric in 54 |
| P4 | yes | right 72 of 72; confidently wrong 0 |
| P5 | NO | resolve_entity in 12 of 72; check_rule in 35 |
| P6 | yes | right 54 of 54; source contract 54 |
| P7 | yes | of 18: right 4, declined 14, confidently wrong 0, no answer 0 |
| P8 | yes | H11: right 0, declined 3, confidently wrong 0, no answer 0 |
| P9 | yes | right 31 of 33 |
| P10 | yes | cost $0.0362 available vs $0.0321 routed; seconds 79.3 vs 43.3; SQL queries 2.99 |
| P11 | yes | 972 of 972 responses stamped; versions {'1.0.0': 972} |
| P12 | yes | 972 of 972 calls recorded with a response ID agree; 0 server lines not in an agent record; apart: 1 call(s) refused by the MCP layer before the contract ran (no response ID, no log line), 0 cut off |

## Spend

- Gemini (model) $6.73 and BigQuery $0.0976: $6.83 for Part 3, smoke tests included.
- Anthropic (Claude demonstration, outside the Gemini budget): $0.28 over 25 runs.

Model names and prices were checked on 2026-10-09. Costs are estimates.
