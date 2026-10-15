# Part 2 run log

What was run, in order, and anything that changed between runs. Times are UTC on 2026-10-09.

## 1. Smoke test, before the full run

`python run_part2.py --runs 1 --questions L1,M1 --out smoke`: two questions, one run each, for each of the four configurations. Saved under `results/part2/smoke` and never mixed with the full run. The layers, the tool descriptions and the instruction paragraphs were committed before it (commit `746cb95`).

All eight runs completed and were scored. Estimated spend: $0.32.

One of the eight, `flash_ontology` on M1, ended with no answer. It made 8 SQL queries and 7 ontology lookups, every one inside the limits the agent is told about, and was stopped by the harness's ceiling of 16 model calls before it could reply.

## 2. One change to the harness after the smoke test: the model-call ceiling

Part 1 stops a run at 16 model calls. The agent is not told that number. It is set above the limit the agent is told about (8 queries) so that, in the words of `tessaway/agents/prompt.py`, "an agent that uses every query still has calls left to answer."

Part 2 gives the agent more tools, each with its own allowance of 8 calls, and the ceiling was still 16. An agent could stay inside every limit it was told about and be cut off with no chance to answer. That breaks the guarantee Part 1 states, and it would have shown up as "no answer" runs that say nothing about the layer.

The fix: the ceiling is 16 plus 8 for each layer tool (24 with one layer tool, 40 with all three). See `max_model_calls` in `tessaway/agents/adk_layer_agent.py` and its test.

What this change is and is not:

- It was made after the smoke test and before any run of the full experiment. No full-run result existed.
- It changes nothing the model sees. No definition, no layer, no tool description and no word of the instruction was touched.
- It was not made to help a question that failed. It restores a property of the harness that Part 1 documents.
- The baseline is Part 1's and keeps its ceiling of 16. No Part 1 run reached it.
- The smoke runs made under the old ceiling stay in `results/part2/smoke` as they were, and their cost stays in the spend ledger.
- `summary.md` reports each configuration's ceiling and how many runs reached it.

## 3. Cost estimate from the smoke test

The smoke test gives one lookup run and one metric run per configuration. Each was scaled by what the same question cost in Part 1 to estimate all 24 questions at three runs:

| Configuration | Estimate |
| --- | --- |
| flash_semantic | $2.13 |
| flash_ontology | $2.88 |
| flash_graph | $2.87 |
| flash_all_three | $3.72 |
| Total | $11.59 |

That is above the $9.60 line in the approved budget and below the $14 at which the run would have been held for a decision. Treating every non-lookup question as costing what M1 cost, which overstates it because M1 was one of the dearest questions in Part 1, gives $14.34. `run_part2.py` stops starting new runs if Part 2 spend reaches $14.

## 4. A second, one-run smoke test of the changed ceiling

`python run_part2.py flash_ontology --runs 1 --questions M1 --out smoke2`. One run, to check the changed ceiling in the real run path. It used 8 SQL queries and 5 ontology lookups, was not cut off, and declined. Saved under `results/part2/smoke2`. Estimated spend: $0.06.

## 5. The full run

Started at 20:26 UTC at commit `5bb2701`, with the code, layers, descriptions and instruction exactly as committed there. Four configurations, 24 questions, three runs each: 288 runs.

| Configuration | First run finished | Last run finished | Estimated cost of the 72 runs kept |
| --- | --- | --- | --- |
| flash_semantic | 20:26 | 20:37 | $1.64 |
| flash_ontology | 20:38 | 20:54 | $3.51 |
| flash_graph | 20:54 | 21:13 | $3.81 |
| flash_all_three | 21:13 | 21:21 | $2.12 |

Nothing was changed during or after the full run: no layer, no description, no instruction, no harness setting. No configuration was discarded or run again as a whole.

## 6. Four runs repeated once, by the Part 1 rule

Part 1's rule is that a run that ends in an error or a timeout with nothing to score is run once more, and only once, and that both attempts stay in `runs/`. Four of the 288 runs ended that way and were repeated with `python run_part2.py flash_semantic flash_graph --retry-failed`:

| Configuration | Question, run | First attempt | Second attempt |
| --- | --- | --- | --- |
| flash_semantic | E3, third run | Timed out at 300 seconds | Right |
| flash_graph | M6, first run | Timed out at 300 seconds | Declined |
| flash_graph | M6, third run | Timed out at 300 seconds | Declined |
| flash_graph | R5, second run | Harness error, see below | Right |

The summaries use the second attempt. The first attempts are still in `results/part2/runs/` (their cost is in the ledger), which is why two of those files hold more than 72 lines.

## 7. A bug found in the Part 1 SQL tool, and not fixed

The `flash_graph` run on R5 failed with `TypeError: Object of type relativedelta is not JSON serializable`. The agent wrote a query whose result held a BigQuery `INTERVAL` value. `tessaway/warehouse/query.py` turns dates, decimals and bytes into values JSON can carry and does not handle intervals, so the tool's result could not be sent back to the model and the run ended.

This is in the SQL tool, which is Part 1's and is used unchanged in every Part 2 configuration. It happened once in 292 Part 2 runs and never in Part 1's saved runs. It was left as it is: the SQL tool is meant to be the same in both parts, and changing it after the runs had started would have meant discarding and repeating a configuration for a failure the retry rule already covers. It should be fixed before Part 3, and the fix noted there.

## 8. Spend

| | Runs | Estimated spend |
| --- | --- | --- |
| Smoke test | 8 | $0.32 |
| Second smoke test | 1 | $0.06 |
| Full run, including the four first attempts that were repeated | 292 | $11.39 |
| Part 2 total | 301 | $11.77 |

The approved line for Part 2 was about $9.60, so Part 2 ran $2.17 over its line. The ontology and graph configurations are why: they cost about 5 cents a question against the 3.3 cents the line assumed, because the agent called the layer tool about four or five times a question and still used nearly all of its SQL queries. Parts 2 to 7 have spent $11.77 of the $35 approved, under the hard cap of $45. Part 1's $26.52 was spent before that budget and is not counted in it. `results/series_spend.json` is the ledger.
