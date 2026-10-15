# Part 3 predictions

Written on 2026-10-13, before any Part 3 agent run, and committed before the first scored run. Each prediction states the rule it is tested by. `run_part3.py` writes the numbers each rule reads into `results/part3/summary.json`; `results/part3/summary.md` reports, prediction by prediction, whether it held. A prediction that fails is reported as failed; none is reworded after the runs.

## What runs

- The contract: `context_server/` on Cloud Run, version 1.0.0, four operations (`lookup_definition`, `compute_metric`, `check_rule`, `resolve_entity`) over the Part 2 layers, unchanged. No free-form query.
- Two configurations, both Google ADK 2.11.0 with `gemini-3.8-flash`, three runs per question:
  - **available**: the contract and the Part 1 read-only SQL tool. The instruction is Part 1's with one paragraph naming the contract's tools (`tessaway/agents/contract_prompt.py`). It does not tell the agent to prefer either.
  - **routed**: the contract only.
- Questions: the 24 Part 1 questions in both configurations (72 runs each); the 12 held-out questions in routed only (36 runs). 180 runs.
- Scoring: the Part 1 scorer, unchanged.
- The SQL tool changed in one respect from Parts 1 and 2: a result cell JSON cannot carry (a BigQuery `INTERVAL`, which ended one Part 2 run) is now written as text instead of ending the run.

## How an answer's source is decided

By code, in `tessaway/answer_source.py`, never by what the agent says. The value on the final `ANSWER:` line is compared with every number and name each tool returned in that run (free text such as definitions and rule statements excluded):

- a number matches when the returned number, rounded to the decimal places the agent wrote, equals it; for a percentage question the returned number times 100 is tried too;
- a name matches when one contains the other, compared on words, and the shorter has at least four characters.

The source is **contract** (matches a contract value only), **sql** (a SQL value only), **both**, or **neither** (matches nothing returned: worked out, or from nowhere). Runs with no answer value (declines, no final line) are counted apart. When both routes return the same number the run is "both"; that means the routes agreed, not that the agent used both.

## Predictions

| # | Prediction | Tested by |
| --- | --- | --- |
| P1 | In **available**, on the 24 questions, the most common answer source is **both**. | Of the 72 runs, "both" is the largest of the four source counts. |
| P2 | In **available**, the lookup questions are answered from SQL alone, because the contract holds none of those facts. | Of the 18 lookup runs (L1 to L6) with an answer value, at least 15 have source "sql". |
| P3 | In **available**, the agent still runs its own SQL beside the contract on questions one metric answers, as it did in Part 2 (48 of 54). | Of the runs on the 18 questions `run_part2.applies_to("semantic", ...)` marks, at least 38 of 54 call `run_sql` and at least 49 of 54 call `compute_metric`. |
| P4 | In **available**, accuracy stays where Part 2 left it. | Right in at least 68 of 72 runs; confidently wrong in at most 2. |
| P5 | In **available**, the graph is still ignored, and rules are rarely checked. | `resolve_entity` is called in fewer than 18 of 72 runs; `check_rule` in fewer than 18 of 72. |
| P6 | In **routed**, the metric, entity and rule questions are answered through the contract. | Right in at least 49 of the 54 runs on those three groups, and at least 45 of those 54 runs have source "contract". |
| P7 | In **routed**, the lookup questions mostly fail, and fail by declining more than by guessing. | Of the 18 lookup runs: right in at most 4, declined in at least 9, and confidently wrong in fewer runs than declined. |
| P8 | In **routed**, H11 (paperwork on file but unsigned), which the layer cannot answer, is never answered right. | H11 right in 0 of 3 runs, and declined in at least 2 of 3. |
| P9 | In **routed**, the other 11 held-out questions are mostly answered right through the contract alone. | Right in at least 28 of their 33 runs. |
| P10 | Closing the second route makes each question cheaper. | On the 24 questions, routed's mean cost per question and mean seconds per question are both lower than available's, and available's mean SQL queries per question is at least 1.5. |
| P11 | Every contract response carries the contract version. | 100% of contract responses recorded in every run (smoke tests excluded) carry `contract_version` 1.0.0 and a response ID. |
| P12 | The server's call log and the agents' own records agree. | Every contract call an agent recorded with a response ID appears in the server log with the same operation, version and caller identity, and every server log line for a run is in that run's record. Calls cut off by a run's timeout or error are listed separately, not counted as agreement. |

## What would change the article

- If P1 fails because "contract" is the largest source, the agent was not checking against SQL, and the "then it checked" reading is wrong.
- If P3 fails, the Part 2 double-check did not survive serving the layers through one endpoint.
- If P6 or P9 fails, routing costs more than lookups.
- If P12 fails, the observability claim fails and the article says so.

## Spend

Planned: 180 runs at Part 2's measured 2.9 to 4.3 cents per question, about $5.50 to $7.50 of Gemini spend. The run stops if estimated Part 3 Gemini spend passes $15. The Claude demonstration (unscored, one pass, `claude-sonnet-5-5` through Anthropic's API) is capped at $5 and is reported only as whether it worked, which operations it called, and what it cost.
