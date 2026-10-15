# Part 4 results

Written by `run_part4.py`. Tessaway Freight is a fictional company, the data is synthetic, and every definition owner is a fictional role.

Contract 2.0.0: every response lists the definitions it served, each with id, version and owner from `data/definition_registry.json`. The agent is Part 3's (Google ADK, `gemini-3.8-flash`), told one more thing: put a `SOURCES:` line naming the definitions its answer relies on before the `ANSWER:` line (`tessaway/agents/provenance_prompt.py`). Traceability is decided in code (`tessaway/traceability.py`) against the server's own call log.

Three runs per question: one run is 1.4 points of a 72-run share and 2.8 points of a 36-run share. Small differences are not findings.

## 1. Bins, beside Part 3's run of the same configuration

Right / confidently wrong / declined / no answer.

| Configuration | Questions | Part 4 (citations) | Part 3 (no citations) | Change in runs |
| --- | --- | --- | --- | --- |
| available | part1 (24) | 72 / 0 / 0 / 0 of 72 | 72 / 0 / 0 / 0 of 72 | right +0, confidently_wrong +0, declined +0, no_answer +0 |
| routed_holdout | holdout (12) | 30 / 3 / 3 / 0 of 36 | 31 / 2 / 3 / 0 of 36 | right -1, confidently_wrong +1, declined +0, no_answer +0 |

## 2. How many answers could be traced

Of runs on questions that need a definition (every group but lookup) that ended in an answer value. Traceable: the answer names an id and version, the registry holds it with an owner, and the server log shows it served in that run.

| Configuration | Answered | Traceable | Share | Citing without using | Using without citing |
| --- | --- | --- | --- | --- | --- |
| available | 54 | 54 | 100.0% | 0 (0.0%) | 0 (0.0%) |
| routed_holdout | 33 | 33 | 100.0% | 0 (0.0%) | 0 (0.0%) |

### How the rest failed

| Configuration | Miss | Runs |
| --- | --- | --- |

### By question group

| Configuration | Group | Answered | Traceable | Share |
| --- | --- | --- | --- | --- |
| available | metric | 18 | 18 | 100.0% |
| available | entity | 18 | 18 | 100.0% |
| available | rule | 18 | 18 | 100.0% |
| routed_holdout | metric | 12 | 12 | 100.0% |
| routed_holdout | entity | 12 | 12 | 100.0% |
| routed_holdout | rule | 9 | 9 | 100.0% |

### By question

| Configuration | Question | Answered | Traceable | Statuses | Cited |
| --- | --- | --- | --- | --- | --- |
| available | E1 | 3 | 3 | traceable, traceable, traceable | customer@1, revenue@1 |
| available | E2 | 3 | 3 | traceable, traceable, traceable | customer@1 |
| available | E3 | 3 | 3 | traceable, traceable, traceable | customer@1, revenue@1 |
| available | E4 | 3 | 3 | traceable, traceable, traceable | load@1 |
| available | E5 | 3 | 3 | traceable, traceable, traceable | customer@1, delivered_load@1 |
| available | E6 | 3 | 3 | traceable, traceable, traceable | delivered_load@1 |
| available | M1 | 3 | 3 | traceable, traceable, traceable | delivered_load@1, on_time@1 |
| available | M2 | 3 | 3 | traceable, traceable, traceable | revenue@1 |
| available | M3 | 3 | 3 | traceable, traceable, traceable | margin@1 |
| available | M4 | 3 | 3 | traceable, traceable, traceable | margin@1, revenue@1 |
| available | M5 | 3 | 3 | traceable, traceable, traceable | delivered_load@1 |
| available | M6 | 3 | 3 | traceable, traceable, traceable | delivered_load@1 |
| available | R1 | 3 | 3 | traceable, traceable, traceable | on_time@1 |
| available | R2 | 3 | 3 | traceable, traceable, traceable | billable@1 |
| available | R3 | 3 | 3 | traceable, traceable, traceable | revenue@1 |
| available | R4 | 3 | 3 | traceable, traceable, traceable | delivered_load@1 |
| available | R5 | 3 | 3 | traceable, traceable, traceable | portal_on_time@1 |
| available | R6 | 3 | 3 | traceable, traceable, traceable | margin@1 |
| routed_holdout | H1 | 3 | 3 | traceable, traceable, traceable | delivered_load@1, load@1, on_time@1 |
| routed_holdout | H10 | 3 | 3 | traceable, traceable, traceable | on_time@1 |
| routed_holdout | H12 | 3 | 3 | traceable, traceable, traceable | customer@1, portal_on_time@1 |
| routed_holdout | H2 | 3 | 3 | traceable, traceable, traceable | margin@1, revenue@1 |
| routed_holdout | H3 | 3 | 3 | traceable, traceable, traceable | revenue@1 |
| routed_holdout | H4 | 3 | 3 | traceable, traceable, traceable | billable@1, margin@1 |
| routed_holdout | H5 | 3 | 3 | traceable, traceable, traceable | delivered_load@1 |
| routed_holdout | H6 | 3 | 3 | traceable, traceable, traceable | customer@1, revenue@1 |
| routed_holdout | H7 | 3 | 3 | traceable, traceable, traceable | customer@1, revenue@1 |
| routed_holdout | H8 | 3 | 3 | traceable, traceable, traceable | customer@1, load@1 |
| routed_holdout | H9 | 3 | 3 | traceable, traceable, traceable | delivered_load@1 |

### The lookups (no definition needed)

- available: 18 runs; 11 cite nothing, 7 cite something (7 of those served), 0 have no SOURCES line; the server served a definition in 12.

## 3. The contract and the server's record

- available: 287 of 287 contract responses carried a version and a response ID; versions seen {'2.0.0': 287}; names a response returned that the registry does not map: 0.
- routed_holdout: 276 of 276 contract responses carried a version and a response ID; versions seen {'2.0.0': 276}; names a response returned that the registry does not map: 0.
- Server log against the agents' records: 563 of 563 recorded calls agree; 0 refused by the MCP layer before the contract ran; 0 log lines not in an agent's record; 108 of 108 runs agree in full.

## 4. The audit

From Part 4: routed_holdout H10 run 0; the three checks say `traceable`. The full trail is in `audit.md`.

## 5. Tokens, time and cost per question

| Configuration | Input tokens | Output tokens | Model calls | SQL queries | Seconds | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| available | 44,742 | 3,129 | 7.53 | 2.75 | 67.0 | $0.0376 |
| routed_holdout | 49,792 | 8,187 | 7.5 | 0.0 | 89.1 | $0.0575 |

## 6. Limits and failures

| Configuration | Refused a further SQL query | Refused a further contract call | Hit the ceiling | Timed out | Ended in an error |
| --- | --- | --- | --- | --- | --- |
| available | 0 | 0 | 0 | 0 | 0 |
| routed_holdout | 0 | 0 | 0 | 0 | 0 |

## Predictions

As written in `predictions.md` before the first scored run, each tested by its own rule.

| # | Held | Numbers |
| --- | --- | --- |
| P1 | yes | right 72 of 72, confidently wrong 0 (Part 3: 72 and 0) |
| P2 | yes | right 30 of 36, confidently wrong 3, H11 right 0 (Part 3: 31, 2, 0) |
| P3 | yes | traceable 54 of 54 answered (100.0%) |
| P4 | yes | traceable 33 of 33 answered (100.0%) |
| P5 | NO | citing without using 0; using without citing 0 (answered, non-lookup, both configurations) |
| P6 | NO | 11 of 18 lookup runs cite nothing; 7 cite something; 0 have no SOURCES line |
| P7 | yes | 563 of 563 responses stamped; versions {'2.0.0': 563}; responses without a definitions field 0; names not in the registry 0 |
| P8 | yes | 563 of 563 calls agree (0 refused before the contract ran); 0 server lines not in an agent record; served sets agree in 108 of 108 runs |
| P9 | yes | H10 confidently wrong in 3 of 3; 3 of those cite on_time@1; answers ['0', '0', '0'] |
| P10 | yes | cost per question $0.0376 (Part 3 available $0.0362; the line is $0.0434) |

## Spend

- Gemini (model) $5.19 and BigQuery $0.0643: $5.25 for Part 4, smoke tests included.

Model names and prices as checked for the series in `tessaway/config.py`. Costs are estimates.
