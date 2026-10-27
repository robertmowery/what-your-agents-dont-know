# Part 5 predictions

Written on 2026-10-14, before any Part 5 agent run and before the drift is planted, and committed before the smoke test and the first scored run. Each prediction states the rule it is tested by. `run_part5.py` writes the numbers each rule reads into `results/part5/summary.json`, and `results/part5/summary.md` reports, prediction by prediction, whether it held. A prediction that fails is reported as failed; none is reworded after the runs.

The design is the revision Robert approved on 2026-10-14 at 22:04 ET (`workflow/briefs/checks/part-5-check.md`, section 6).

## What runs

- **The golden set, version 1.** The 24 Part 1 questions and their saved answers, frozen: `questions/golden_set_v1.json` pins `questions/part1.yaml` and `results/part1/gold_answers.json` by SHA-256, and `tessaway/golden_set.py` refuses to load answers whose file moved. Every Part 5 run is scored against those values with the Part 1 scorer, unchanged. The gold SQL is not run to score anything. `tests/test_golden_set.py` fails if the answer key is recomputed while the drift is in place.
- **The agent.** Part 4's available configuration, word for word: Google ADK 2.11.0, `gemini-3.8-flash`, contract 2.0.0 and the SQL tool, the citing instruction (`tessaway/agents/provenance_prompt.py`). One scored runtime.
- **The job.** `golden_check/job.py` in a Cloud Run job (`infra/part5`): one execution asks the 24 questions once, four at a time, writes one run record and one trace per question to a bucket, and applies the alert rule. The run record is Part 4's format, unchanged. Executions are started by hand; the nightly Cloud Scheduler entry is defined in Terraform and paused.
- **Traces.** OpenTelemetry, on the new runs only (`tessaway/tracing.py`). One trace per run: a root span `golden_set.run` with the question, the golden set version, the contract version, the definitions cited and served with their owners, the model, tokens, cost, latency, query counts and the score, a `golden_set.score` child span, and Google ADK's own spans underneath. The baseline has run records and no traces.
- **The warehouse.** The context server (`infra/part3`, image rebuilt from this commit, no code change) and the job's SQL tool both read a copy of the warehouse, `tessaway_wh_p5`, loaded from `tessaway.warehouse.generate` (seed 20261009), with the semantic layer's views over it in `tessaway_sem_p5`. The warehouse of record is never touched.
- **The drift** (`tessaway/drift.py`), planted in the copy after the smoke test: billing reloads 2026 with every Canadian-dollar amount already converted to US dollars at the month's rate (`ROUND(amount * rate, 2)`), and `curr_cd` left as `CAD`. Invoices at the invoice month, credit memos at the credit month, canceled-load fees at the fee month, costs on an invoiced load at the invoice month. Same tables, columns, types and row counts.
- **The fix.** The revert script loads the billing tables in the copy again from the generator. Nothing else changes.

## Phases

| Phase | Runs | Source |
| --- | --- | --- |
| Baseline | 72 | Part 4 available, reused (`results/part4/runs/available.jsonl`); no spend |
| Drift | 72 | Three executions of the job, 24 questions each |
| After the fix | 24 | One execution |

A smoke test of four questions (L1, M1, M2, R3) runs on the clean copy before the drift is planted, to check the job, the traces and the copy. It is not scored as a phase.

## The alert rule

Committed in this commit, before the drift (`tessaway/alert_rule.py`): after each execution, if the share of runs scored right in any question group is lower than that group's share in the baseline (Part 4 available, 72 runs), the alert fires. Nothing operational goes into it. `tests/test_alert_rule.py` shows it quiet on both earlier passes of this configuration (Part 3 and Part 4 available), each read as three executions of 24. With a baseline of 18 of 18 right in every group, one miss in an execution fires it.

**Time to detection** is the first execution that fires, counted in executions and reported as the schedule interval (one night, if the schedule were running).

## Measured without a model (not predictions)

Before the drift phase, `tessaway/drift.py gold` runs the reviewed gold SQL against the copy: clean, then with the drift starting Oct 1, 2026 (forward only), Sep 1, 2026, and restated for all of 2026. The check of the brief computed the effect in plain Python (`part-5-check.md`, section 2): restated, 4 of 24 answers leave tolerance (M2, M3, E3, R3); from Sep 1, 1 (R3); from Oct 1, 0. These runs record what BigQuery says; the forward case is reported as a limit of a fixed-period golden set, at no model cost.

## Green, defined now

For each drift execution, an operational signal is **green** when the execution's mean per run lies inside the baseline's per-run mean plus or minus one standard deviation (Part 4 available, 72 runs): latency (seconds), model cost, input tokens and SQL queries. Failures are green at no more than 1 run in 24 ending in an error or a timeout (the baseline had 0 in 72).

## Predictions

| # | Prediction | Tested by |
| --- | --- | --- |
| P1 | Every operational signal stays green through the drift. | All three drift executions green on latency, cost, input tokens, SQL queries and failures, by the definition above. |
| P2 | The right-answer share drops, and the drop falls on the four questions the drift reaches. | Drift phase right in at most 64 of 72 runs, and at least 8 of the 12 runs on M2, M3, E3 and R3 not right. |
| P3 | Nothing else moves. | Lookups right in 18 of 18 drift runs, and the 20 questions outside M2, M3, E3 and R3 right in at least 58 of 60. |
| P4 | The wrong answers are confident and look like no known mistake. | Of the not-right drift runs on M2, M3, E3 and R3, at least 80% are confidently wrong (not declined or failed), and none matches a stored decoy. |
| P5 | The check catches it on the first execution, and keeps catching it. | The alert fires on drift executions 1, 2 and 3, never naming the lookup group. |
| P6 | The alert stays quiet when nothing changed. | Quiet on all six baseline executions (Part 3 and Part 4 available, three each; also a test) and on the after-the-fix execution. |
| P7 | The fix brings the answers back. | After the fix, right in at least 23 of 24. |
| P8 | The trace narrows the search to an owner, not to the cause. | Of the newly wrong drift runs that cite anything, every one cites a definition the Controller owns; `revenue@1` is the definition cited most; `currency@1`, the definition the drift makes false, is cited in fewer than half. |
| P9 | Every new run carries a complete trace that agrees with its record. | All 96 scored runs (drift and after the fix) have one trace with one root span carrying the question, golden set version 1, contract 2.0.0, cited definitions equal to the record's, and the record's outcome, plus a score span and at least one ADK model-call span (a run that failed before any model call excepted). |
| P10 | The drift costs nothing you would notice on a bill. | Mean model cost per run in the drift phase at most $0.0451 (Part 4 available $0.0376, plus 20%). |
| P11 | The server's call log and the job's records agree. | As Part 4's P8: every recorded call with a response ID is in the server log with the same operation, version and caller; no server line for a scored run is missing from its record. |

## What would change the article

- If P1 fails, a signal moved. The headline holds only if the move sits inside what a dashboard would treat as noise; the article says which signal moved and by how much, and the subtitle changes.
- If P2 fails because the answers did not move, the agents did not follow the served definition through to the stored amounts, and the article is about that instead.
- If P5 fails, the check missed it, and section 6 says how.
- If P8 fails because the answers cite `currency@1`, the trace pointed at the right definition, and section 7 says so.
- If P9 fails, the trace cannot be trusted as the way back, and the article says so before using one.

## Spend

Planned: about 100 runs (72 drift, 24 after the fix, 4 smoke) at Part 4's measured $0.0376 per question: about $3.95 of Gemini spend. The job stops starting runs at a per-execution budget, and no execution is started once estimated Part 5 Gemini spend reaches $7 (the stop line Robert approved). Cloud Run (the context server and the job) is deployed for the runs and torn down after; its cost is recorded apart as an estimate. No Claude runs in this part.
