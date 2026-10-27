# Part 5 run log

Times are UTC, 2026-10-15 unless marked. The Google Cloud project, the service URL and email addresses are written as PROJECT, CONTRACT_URL and EMAIL throughout `results/part5`; service accounts keep their short names.

## Before any run

- **Gate.** Robert approved the revised experiment on 2026-10-14 at 22:04 ET (02:04 UTC on the 15th): the revision in `workflow/briefs/checks/part-5-check.md` exactly as proposed, the Medium headline "Green Dashboards, Wrong Answers", the Substack title "Evals That Catch Context Drift: Traces, a Golden Set and a Scheduled Check", series spend above the $35 figure while staying under the $45 hard cap, and the slot Tue Nov 24, 2026, 8:00 AM ET (`workflow/gate-log.md`).
- **Commit `892938a`** (about 02:28): the frozen golden set (`questions/golden_set_v1.json`, `tessaway/golden_set.py`), the drift and revert script (`tessaway/drift.py`), the alert rule and its baseline (`tessaway/alert_rule.py`, `results/part5/alert_baseline.json`), tracing (`tessaway/tracing.py`), the job (`golden_check/`), the Terraform root for the job and its paused schedule (`infra/part5`), two dataset variables in `infra/part3` (defaults unchanged), the tests and `predictions.md`. Committed and pushed before the copy was made, before the smoke test and before any scored run. `pytest -m "not cloud"`: 287 passed.
- **Working tree.** At about 22:27 ET on the 14th another agent's public-repo sync overwrote some tracked files in the working tree with older versions, including four of the uncommitted Part 5 edits above. They were restored from HEAD and the Part 5 edits were made again before commit `892938a`; nothing ran in between.
- **Versions.** Python 3.13.4, google-adk 2.11.0, mcp 2.3.0, opentelemetry-api and -sdk 1.42.1, opentelemetry-exporter-gcp-trace 1.15.0, google-cloud-storage 3.17.0, dbt-metricflow 0.15.0 in its own environment.

## The copy, and the drift measured without a model (results/part5/drift)

- `python -m tessaway.drift copy --dataset tessaway_wh_p5` (02:31): every warehouse table loaded from `tessaway.warehouse.generate`, seed 20261009, fingerprint `2b8171584cfe…`, the same row counts as the record. The semantic layer's views were built over it in `tessaway_sem_p5` (`dbt run`, 6 views).
- `clean.json`: the reviewed gold SQL on the copy gives all 24 frozen answers exactly; 0 rows differ from the record.
- `forward_from_oct1.json`: the reload for documents dated on or after Oct 1, 2026 changes 28 amounts (costs on loads not yet invoiced) and moves 0 of 24 answers.
- `from_sep1.json`: from Sep 1, 179 amounts change and 1 answer leaves tolerance (R3, -4.58%; E3 -0.75%, M2 -0.44%), as the check of the brief computed.
- `clean_after_revert.json`: after each variant the revert reloaded the billing tables; 0 rows differ.
- `restated.json` (03:11, after the smoke test): the reload for all of 2026, 1,610 amounts in six billing tables; row counts, columns and types identical to the record; 0 currency codes changed; 4 of 24 answers out of tolerance: M2 10,134,528.89 (-1.55%), M3 403.11 (-1.49%), E3 1,252,448.31 (-3.63%), R3 826,718.54 (-16.17%). The check computed M2 as 10,134,528.91 and E3 and R3 a cent higher; the two cents come from storing each converted amount rounded to the cent. `pytest -m cloud tests/test_golden_set.py` passed with the drift in place.
- `after_revert.json` (03:55): 0 rows differ, 0 answers out of tolerance.

## Deployment

- `infra/part3` applied in two steps as in Part 4, with `warehouse_dataset = tessaway_wh_p5` and `semantic_dataset = tessaway_sem_p5`: the image `context-server:p5-1` built by Cloud Build from commit `892938a` (no server code changed since Part 4; contract 2.0.0), service up at about 02:45. The context server and the job read the copy for the whole of Part 5; the drift and the fix are changes to the copy, not to the deployment, so the server never restarted.
- `infra/part5` applied in two steps: bucket, the job's and the scheduler's service accounts and grants, then the Cloud Run job `tessaway-golden-check` (image `golden-check:p5-1`, Part 3's repository and build account) and the Cloud Scheduler entry `tessaway-golden-check-nightly`, created paused (`schedule_paused = true` in the Terraform output). The schedule was never resumed. Every execution was started by hand with `run_part5.py --execute`, which calls `gcloud run jobs execute ... --wait`.

## Smoke test (results/part5/smoke), on the clean copy

- **First try (02:46):** the job could not list its results bucket: HTTP 403 for `serviceusage.services.use`. `tessaway.config` pins the quota project on every client, which needs `roles/serviceusage.serviceUsageConsumer`. Added to `infra/part5` and applied. No model call had been made.
- **Execution 1 (02:51 to 02:59), L1, M1, M2, R3:** L1, M1 and M2 right; R3 reached the 300-second limit with no answer. The wiring held: four records in Part 4's format, four traces with ADK's spans nested under the root, the alert written. The traces showed the first MCP `tools/list` taking 12.8 seconds in every run. ADK probes for an mTLS client certificate before each MCP session; on Cloud Run the probe waits and then fails, where on the Mac it fails at once (`get_tools` measured from the Mac: 0.5 to 0.6 s). **Harness change:** `GOOGLE_API_USE_CLIENT_CERTIFICATE=false` on the job (`infra/part5/main.tf`). It changes nothing the agent is given or told; the server is still reached over TLS.
- **Execution 2 (03:02 to 03:07), L1 only:** `tools/list` now 84 ms. L1 reached the 300-second limit: one Gemini call ran 244 seconds. A probe from the Mac at the same time (four one-sentence requests to `gemini-3.8-flash`) took 53.5 s, 5.7 s, 8.1 s, and the fourth ended in HTTP 504 DEADLINE_EXCEEDED after 57 s, so the slowness was on Gemini's side, not the job's. Ten minutes later the same probe took 18.7, 4.8, 4.3 and 6.6 s, and the drift phase started.
- Smoke spend: 5 runs, $0.18 of Gemini.

## Drift phase (results/part5/runs/drift.jsonl), three executions

- Execution 1, 03:16 to 03:29: 17 of 24 right in the job's first verdict. The four drifted questions confidently wrong; three runs failed on Gemini's side: L1 on HTTP 429 (ResourceExhausted) after the client's retries, L5 and M4 at the 300-second limit. The alert fired naming lookup, metric, entity and rule.
- **Harness change after execution 1:** the job had no way to rerun a failed run. `--retry-failed` was added (`golden_check/job.py`, image `golden-check:p5-2`): the Part 1 rule Parts 3 and 4 used, a run that ended in an error or a timeout is run once more, the failed record is kept beside the new one as `<question>.first_try.json`, both count toward spend, and the summary uses the later one. Execution 1's retry pass (03:32 to 03:35) answered L1, L5 and M4 right, and the job's second verdict for execution 1 fired naming metric, entity and rule.
- Execution 2, 03:37 to 03:43 (retry pass: nothing to rerun), and execution 3, 03:47 to 03:52 (retry pass: nothing to rerun): no failures; 20 of 24 right each, the same four questions confidently wrong, the alert fired each time naming metric, entity and rule.
- Every wrong answer was the same number in all three executions: M2 10,134,528.894054, M3 403.112811604, E3 1,252,448.312611, R3 826,718.544054, each the drifted figure the gold SQL gives on the drifted copy, and none matching a stored decoy.
- `alert.json` in the bucket keeps only the last verdict per execution, because a retry pass writes it again. Every verdict as raised is read back from Cloud Logging into `alerts/raised.jsonl` (`run_part5.py --read-server-log`), and the predictions are tested on the first verdict per execution.

## After the fix (results/part5/runs/after_fix.jsonl)

- `python -m tessaway.drift revert` at 03:55, then one execution, 03:57 to 04:02: 24 of 24 right, the alert quiet. Retry pass: nothing to rerun.

## Reading back

- `run_part5.py --read-server-log --since 2026-10-15T02:40:00Z` at about 04:05: 430 `contract_call` lines (smoke included) and 10 alert verdicts. Against the scored runs' records, 402 of 402 calls agree; 0 log lines for a scored run are missing from its record.
- Cloud Trace: 99 traces with a `golden_set.run` root since 03:13 (75 drift attempts and 24 after the fix), read through the Cloud Trace API. The traces in `results/part5/traces` are the job's own copies, written beside each record; they are what the summary reads.

## Teardown

- `terraform destroy` in `infra/part5` at 04:06 (18 resources: the job, the paused schedule, both service accounts and their grants, the bucket with its objects; the APIs stay on) and in `infra/part3` at 04:07 with the same variables as the apply (25 resources: the service, its accounts and grants, the image repository with the `context-server:p5-1`, `golden-check:p5-1` and `golden-check:p5-2` images, the build staging bucket). The datasets `tessaway_wh_p5` and `tessaway_sem_p5` deleted with their contents; `tessaway_wh` and `tessaway_sem` untouched.
- Checked afterward with gcloud (every call with `--project` and a short-lived token file from Application Default Credentials, deleted after each call): no Cloud Run service or job in us-central1, no Cloud Scheduler job, no `tw-p*` service account, no Artifact Registry repository, no Part 3 or Part 5 bucket; both Terraform states empty. The gcloud default project was not changed.
- Not Terraform resources and left in place: Cloud Build's build records, the job's and the service's log entries, and the traces in Cloud Trace, all of which expire under the project's retention settings.
- Cloud Run, estimated at list prices: the context server (one warm instance, 2 vCPU and 4 GiB, CPU always allocated, about 02:44 to 04:08, about $0.22), the job's executions (about 70 minutes of 2 vCPU and 2 GiB across 11 executions, about $0.22) and three Cloud Builds (about $0.03): $0.47, recorded in the ledger as an estimate apart from model spend.

## Spend

- Gemini, Part 5, smoke tests and the three repeated runs included: $3.96 of model spend and $0.05 of BigQuery, $4.01 in all (planned about $3.95; the stop line was $7 and was not reached).
- Series ledger (`results/series_spend.json`), Parts 2 to 7: $31.13, $3.87 under the $35 approved and $13.87 under the $45 hard cap.
- No Anthropic spend in Part 5.
