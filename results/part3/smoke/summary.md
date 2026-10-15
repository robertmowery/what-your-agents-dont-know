# Part 3 results

Written by `run_part3.py`. Tessaway Freight is a fictional company and the data is synthetic.

The Part 2 layers served as one contract (version 1.0.0) by an MCP server on Cloud Run, called by the Part 2 agent (Google ADK, `gemini-3.8-flash`) under its own service account. **available**: the contract and the SQL tool. **routed**: the contract only. Each reply is scored by the Part 1 scorer, unchanged.

Three runs per question: one run is 1.4 points of a 72-run share, 2.8 points of a 36-run share and 5.6 points within a question group of six. Small differences are not findings.

| Configuration | Questions | Tools | Runs | Complete | Right | Confidently wrong | Declined | No answer | Est. cost | Cost per question |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| available | part1 (1) | 5 | 1 of 1 | yes | 100.0% (1) | 0.0% (0) | 0.0% (0) | 0.0% (0) | $0.04 | $0.0355 |
| routed | part1 (1) | 4 | 1 of 1 | yes | 100.0% (1) | 0.0% (0) | 0.0% (0) | 0.0% (0) | $0.03 | $0.0305 |

## By question group: right / confidently wrong / declined / no answer

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| available | n/a | 1 / 0 / 0 / 0 | n/a | n/a |
| routed | n/a | 1 / 0 / 0 / 0 | n/a | n/a |

## 1. Where each answer came from

Worked out in code (`tessaway/answer_source.py`) by matching the value on the final `ANSWER:` line against every value the contract and the SQL tool returned in the run. The agent's own account is not used. "both" means the two routes returned the same value. Each cell: runs (of which right).

| Configuration | Runs | contract | sql | both | neither | no answer value |
| --- | --- | --- | --- | --- | --- | --- |
| available | 1 | 0 (0 right) | 0 (0 right) | 1 (1 right) | 0 (0 right) | 0 (0 right) |
| routed | 1 | 1 (1 right) | 0 (0 right) | 0 (0 right) | 0 (0 right) | 0 (0 right) |

### By question group

| Configuration | Group | Runs | contract | sql | both | neither | no answer value |
| --- | --- | --- | --- | --- | --- | --- | --- |
| available | metric | 1 | 0 (0 right) | 0 (0 right) | 1 (1 right) | 0 (0 right) | 0 (0 right) |
| routed | metric | 1 | 1 (1 right) | 0 (0 right) | 0 (0 right) | 0 (0 right) | 0 (0 right) |

## 2. Tool calls

Mean calls per run (runs that called it). Calls refused over a limit are not counted.

| Configuration | `run_sql` | `lookup_definition` | `compute_metric` | `check_rule` | `resolve_entity` | No contract call | No SQL | First call SQL | First call contract |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| available | 1.00 (1) | 2.00 (1) | 1.00 (1) | 1.00 (1) | 0.00 (0) | 0 | 0 | 0 | 1 |
| routed | 0.00 (0) | 3.00 (1) | 1.00 (1) | 2.00 (1) | 0.00 (0) | 0 | 1 | 0 | 1 |

On the questions one metric answers (available, 1 runs): `compute_metric` called in 1, SQL run in 1, both in 1, SQL without the metric in 0, the contract without SQL in 0.

## 3. What the second route costs: per question, available against routed

| Configuration | SQL queries | Input tokens | Output tokens | Model calls | Seconds | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| available | 1.00 | 32,956 | 3,565 | 6.00 | 43.8 | $0.0355 |
| routed | 0.00 | 32,955 | 2,229 | 7.00 | 88.9 | $0.0305 |

| Question | Group | SQL queries (available) | Cost available | Cost routed | Seconds available | Seconds routed |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | metric | 1.0 | $0.0355 | $0.0305 | 43.8 | 88.9 |

## 4. What routing breaks: the six lookups and H11, routed

| Question | Run | What it did | Final answer | Correct | Operations called |
| --- | --- | --- | --- | --- | --- |

## 5. Versions and the server's record

- available: 4 of 4 contract responses carried a version and a response ID; versions seen {'1.0.0': 4}.
- routed: 6 of 6 contract responses carried a version and a response ID; versions seen {'1.0.0': 6}.
- Server log against the agents' records: 10 of 10 recorded calls agree (same response ID, operation, version and caller); 0 recorded calls missing from the log; 0 log lines not in an agent's record; 2 of 2 runs agree in full. See `server_log_check.md`.
- Secured: no token -> HTTP 403, refused (as expected).
- Secured: a token with a forged signature -> HTTP 401, refused (as expected).
- Secured: the routed agent's ID token -> HTTP 200, accepted (as expected).

## Limits and failures

| Configuration | Model-call ceiling | Refused a further SQL query | Refused a further contract call | Hit the ceiling | Timed out | Ended in an error |
| --- | --- | --- | --- | --- | --- | --- |
| available | 48 | 0 | 0 | 0 | 0 | 0 |
| routed | 48 | 0 | 0 | 0 | 0 | 0 |

## Spend

- Gemini (model) $0.31 and BigQuery $0.0042: $0.31 for Part 3, smoke tests included.
- Anthropic (Claude demonstration, outside the Gemini budget): $0.02 over 1 runs.

Model names and prices were checked on 2026-10-09. Costs are estimates.
