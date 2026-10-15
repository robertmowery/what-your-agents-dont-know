# Part 4 results

Written by `run_part4.py`. Tessaway Freight is a fictional company, the data is synthetic, and every definition owner is a fictional role.

Contract 2.0.0: every response lists the definitions it served, each with id, version and owner from `data/definition_registry.json`. The agent is Part 3's (Google ADK, `gemini-3.8-flash`), told one more thing: put a `SOURCES:` line naming the definitions its answer relies on before the `ANSWER:` line (`tessaway/agents/provenance_prompt.py`). Traceability is decided in code (`tessaway/traceability.py`) against the server's own call log.

Three runs per question: one run is 1.4 points of a 72-run share and 2.8 points of a 36-run share. Small differences are not findings.

## 1. Bins, beside Part 3's run of the same configuration

Right / confidently wrong / declined / no answer.

| Configuration | Questions | Part 4 (citations) | Part 3 (no citations) | Change in runs |
| --- | --- | --- | --- | --- |
| available | part1 (24) | 1 / 0 / 0 / 1 of 2 | 72 / 0 / 0 / 0 of 72 | right -71, confidently_wrong +0, declined +0, no_answer +1 |
| routed_holdout | holdout (12) | 1 / 0 / 0 / 1 of 2 | 31 / 2 / 3 / 0 of 36 | right -30, confidently_wrong -2, declined -3, no_answer +1 |

## 2. How many answers could be traced

Of runs on questions that need a definition (every group but lookup) that ended in an answer value. Traceable: the answer names an id and version, the registry holds it with an owner, and the server log shows it served in that run.

| Configuration | Answered | Traceable | Share | Citing without using | Using without citing |
| --- | --- | --- | --- | --- | --- |
| available | 1 | 1 | 100.0% | 0 (0.0%) | 0 (0.0%) |
| routed_holdout | 1 | 1 | 100.0% | 0 (0.0%) | 0 (0.0%) |

### How the rest failed

| Configuration | Miss | Runs |
| --- | --- | --- |

### By question group

| Configuration | Group | Answered | Traceable | Share |
| --- | --- | --- | --- | --- |
| available | metric | 1 | 1 | 100.0% |
| routed_holdout | metric | 1 | 1 | 100.0% |

### By question

| Configuration | Question | Answered | Traceable | Statuses | Cited |
| --- | --- | --- | --- | --- | --- |
| available | M1 | 1 | 1 | traceable | on_time@1 |
| routed_holdout | H1 | 1 | 1 | traceable | delivered_load@1, load@1, on_time@1 |

### The lookups (no definition needed)

- available: 1 runs; 0 cite nothing, 0 cite something (0 of those served), 1 have no SOURCES line; the server served a definition in 1.

## 3. The contract and the server's record

- available: 8 of 8 contract responses carried a version and a response ID; versions seen {'2.0.0': 8}; names a response returned that the registry does not map: 0.
- routed_holdout: 23 of 23 contract responses carried a version and a response ID; versions seen {'2.0.0': 23}; names a response returned that the registry does not map: 0.
- Server log against the agents' records: 31 of 31 recorded calls agree; 0 refused by the MCP layer before the contract ran; 0 log lines not in an agent's record; 4 of 4 runs agree in full.

## 4. The audit

From Part 3 (no Part 4 run was confidently wrong): routed_holdout H10 run 0; the three checks say `no_sources_line`. The full trail is in `audit.md`.

## 5. Tokens, time and cost per question

| Configuration | Input tokens | Output tokens | Model calls | SQL queries | Seconds | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| available | 34,335 | 1,958 | 6.5 | 2.0 | 94.5 | $0.0299 |
| routed_holdout | 104,568 | 14,390 | 11.0 | 0.0 | 192.0 | $0.1004 |

## 6. Limits and failures

| Configuration | Refused a further SQL query | Refused a further contract call | Hit the ceiling | Timed out | Ended in an error |
| --- | --- | --- | --- | --- | --- |
| available | 0 | 0 | 0 | 0 | 1 |
| routed_holdout | 0 | 0 | 0 | 1 | 0 |

## Predictions

As written in `predictions.md` before the first scored run, each tested by its own rule.

| # | Held | Numbers |
| --- | --- | --- |
| P1 | NO | right 1 of 2, confidently wrong 0 (Part 3: 72 and 0) |
| P2 | NO | right 1 of 2, confidently wrong 0, H11 right 0 (Part 3: 31, 2, 0) |
| P3 | yes | traceable 1 of 1 answered (100.0%) |
| P4 | yes | traceable 1 of 1 answered (100.0%) |
| P5 | NO | citing without using 0; using without citing 0 (answered, non-lookup, both configurations) |
| P6 | NO | 0 of 1 lookup runs cite nothing; 0 cite something; 1 have no SOURCES line |
| P7 | yes | 31 of 31 responses stamped; versions {'2.0.0': 31}; responses without a definitions field 0; names not in the registry 0 |
| P8 | yes | 31 of 31 calls agree (0 refused before the contract ran); 0 server lines not in an agent record; served sets agree in 4 of 4 runs |
| P9 | NO | H10 confidently wrong in 0 of 1; 0 of those cite on_time@1; answers [''] |
| P10 | yes | cost per question $0.0299 (Part 3 available $0.0362; the line is $0.0434) |

## Spend

- Gemini (model) $0.26 and BigQuery $0.0044: $0.26 for Part 4, smoke tests included.

Model names and prices as checked for the series in `tessaway/config.py`. Costs are estimates.
