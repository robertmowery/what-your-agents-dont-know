# Held-out fairness test: run log

What was run, in order, and anything that changed between steps. All on 2026-10-09. Tessaway Freight is a fictional company and the data is synthetic.

## 1. Coverage check, before any agent run

`python analysis/holdout_coverage.py`. For each of the 12 questions it tried metric requests through `semantic.run_metrics`, the function behind the agent's `query_metrics` tool, and compared the result with the saved gold answer. BigQuery calls only; no model call.

The script was run twice before it was committed, and no agent had run either time. The first pass took the first attempt that matched the gold answer, and on H4 that was the bare company-wide metric: margin per load for the whole company in Q3 (409.19) is within the question's 1% tolerance of the reefer answer (408.74). A query that ignores a condition of the question is not an answer to it, so the rule was changed: the bare metric is run as a control and is never the class. The second pass is the one committed. The only question whose class changed is H4, from "one metric query, as is" to "metric plus a filter". The flaw in H4 stays in the question file, as `data/HOLDOUT.md` requires, and is reported in `coverage.md`.

Result: 0 questions answerable by a bare metric, 8 by a metric with a filter or dimension the layer has, 3 needing more than one query or arithmetic, 1 not answerable from the layer (H11).

## 2. Predictions

`results/holdout/predictions.md`, written after the coverage check and before any agent run. The coverage files, the predictions, `run_holdout.py` and its tests were committed and pushed together (commit `b6e0a22`) before the smoke test.

## 3. Smoke test

`python run_holdout.py --runs 1 --questions H1,H5 --out smoke`: two questions, one run, both configurations. Saved under `results/holdout/smoke` and never mixed with the full run.

| Configuration | H1 | H5 | Estimated cost |
| --- | --- | --- | --- |
| baseline | declined | declined | $0.07 |
| flash_semantic | right | right | $0.06 |

Cost estimate for the 72 runs from the smoke test: about $2.20 at the smoke test's mean cost a run, and $2.95 if every run cost what the dearest smoke run in its configuration did. Both are under the $5 at which the run would have been held. `run_holdout.py` stops starting new runs if held-out spend reaches $5.

## 4. The full run

`python run_holdout.py` at commit `b6e0a22`, with nothing changed after the smoke test. Two configurations, 12 questions, three runs each: 72 runs.

| Configuration | Runs | Right | Confidently wrong | Declined | No answer | Estimated cost |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 36 | 5 | 5 | 26 | 0 | $1.54 |
| flash_semantic | 36 | 36 | 0 | 0 | 0 | $1.55 |

No run ended in an error or a timeout, so no run was repeated and `--retry-failed` was never used. No run reached the model-call ceiling. No run was discarded. Each runs file holds exactly 36 lines.

## 5. What was not changed

Nothing under `semantic_layer/`, `ontology/`, `tessaway/` or `questions/`, no tool description, no instruction text, no part of the scorer, and no gold answer. `run_part2.py` and every file under `results/part1` and `results/part2` are as they were. `pyproject.toml` gained the new scripts in its mypy file list.

## 6. Things a reader should know

- The predictions were wrong in both directions. The baseline was predicted at 7 to 12 right of 36 and got 5. The semantic configuration was predicted at 20 to 30 and got 36.
- H11 was classed "not answerable from the layer", and the semantic configuration still got it right in all three runs. In each run the agent asked the metric tool for `delivered_loads_not_billable` (197, which is one of the question's decoys), did not report it, and worked out the 27 with SQL. The layer did not hold the answer; it appears to have shown the agent what a delivered load and a billable load are.
- On H9 no run used a day-of-week filter. All three fetched delivered loads by day in two or three metric calls and added up the weekends, which is the third coverage class's route, not the second's.
- The bypass count is 23 of 24, but it does not mean what it meant in Part 2's prediction. Every one of the 36 semantic runs called the metric tool, 35 also ran SQL, and none answered from SQL alone. The SQL was mostly looking up code values (carrier types, equipment types) or checking the metric's number.
- H4's flaw did not decide anything: all three semantic runs filtered to `tender__equipment_type = 'REEF'`, and all three baseline runs declined. Without H4 the figures are 5 of 33 and 33 of 33.
- Three runs a question is a small sample: one run is 2.8 points overall.
- The held-out questions were written from the same `data/DEFINITIONS.md` the layer was written from. The test checks whether the layer fits questions its author had not seen. It does not check questions that need a definition the layer's author never had.

## 7. Spend

| | Runs | Estimated spend |
| --- | --- | --- |
| Smoke test | 4 | $0.12 |
| Full run | 72 | $3.14 |
| Held-out total | 76 | $3.27 |

The budget was about $3 to $4. The coverage check's BigQuery queries (about 30 small metric queries) are not in the ledger; the 76 agent runs billed $0.05 of BigQuery between them. Parts 2 to 7 stood at $11.77 and now stand at $15.03 of the $35 approved, under the hard cap of $45. `results/series_spend.json` has the "holdout" entry.
