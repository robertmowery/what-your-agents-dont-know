# Part 4 run log

Times are UTC, 2026-10-13. The Google Cloud project, the service URL and email addresses are written as PROJECT, CONTRACT_URL and EMAIL throughout `results/part4`; service accounts keep their short names.

## Before any run

- **Gate.** Robert approved the revised experiment at 13:43 ET (17:43 UTC): the full version, the headline "An Answer You Can't Trace Is an Answer You Can't Fix", and a Part 4 stop line of $7 (`workflow/gate-log.md`; the check that led to it is `workflow/briefs/checks/part-4-check.md`, commit `73bf2e5`).
- **Commit `32a0ec2`** (about 17:52): the definition registry (`data/definition_registry.json`), contract 2.0.0, the citing agent's instruction, the traceability checker, `run_part4.py`, the tests and `predictions.md`, committed and pushed before the smoke test and before any scored run. `pytest -m "not cloud"`: 260 passed.
- **Versions** as in Part 3's run environment: Python 3.13.4, google-adk 2.11.0, mcp 2.3.0, rdflib 7.6.0, pyshacl 0.40.1, dbt-metricflow 0.15.0 in its own environment.
- **Deployment.** `infra/part3`, Part 3's Terraform root, applied again in two steps, with no change to its files: the repository, staging bucket and service accounts (`-var image=""`, 21 resources, about 17:54), then the Cloud Run service with image `context-server:p4-1` (built by Cloud Build from the commit above, 17:55 to 17:58), 17:59 to 18:04 (5 min 17 s, while the server loaded the graph, checked the rules and started MetricFlow). The Dockerfile and `.gcloudignore` now carry `data/definition_registry.json` into the image and nothing else from `data/`. The image name and the service account names keep Part 3's `p3` prefix because the Terraform root is Part 3's.
- **Checked.** `pytest -m cloud tests/test_part3_cloud.py`: the first try returned HTTP 403 for about a minute after the invoker grants were created, as in Part 3, until they propagated; the second try passed, 5 of 5 (every operation answers on the deployed service with version 2.0.0; an unauthenticated call is refused).

## Smoke test (results/part4/smoke)

One run each: available on L1 and M1; routed_holdout on H1 and H10. Spend $0.26.

| Configuration | Question | Outcome | Cited | Served (server log) |
| --- | --- | --- | --- | --- |
| available | M1 | right | on_time@1 | delivered_load@1, on_time@1, portal_on_time@1 |
| available | L1 | no answer: Gemini returned HTTP 429 (ResourceExhausted) after the client's retries | (no reply) | delivered_load@1, load@1, margin@1 |
| routed_holdout | H1 | right | delivered_load@1, load@1, on_time@1 | billable@1, customer@1, delivered_load@1, load@1, margin@1, on_time@1 |
| routed_holdout | H10 | no answer: the run reached the 300-second limit (14 model calls, several slowed by 429 retries) | (no reply) | seven definitions |

Wiring: 31 of 31 contract responses carried 2.0.0, a response ID and the definitions field; the server log, read back from Cloud Logging, agreed with the agents' records on all 31 calls, and in all 4 runs the definitions the agent's record says it was served equal those the server log names. Both answers given were traceable. No harness change after the smoke test.

The two failures are rate limits, not the experiment. The full run uses 4 questions in flight instead of Part 3's 6 to put less pressure on the quota; that changes nothing an agent is given or told.

## Full run (results/part4)

- `python run_part4.py --concurrency 4`, three runs per question, started 18:15:36. available 18:15 to about 18:37 (72 runs), routed_holdout about 18:37 to 18:53 (36 runs). 108 runs, no error, no 429 that ended a run.
- One routed_holdout run (H10, run 2) reached the 300-second limit with no answer (13 model calls). It was run again once with `--retry-failed`, the Part 1 rule Part 3 also used, at 18:54 to about 18:57; the repeat answered 0 (confidently wrong) and cited `on_time@1`. Both lines are kept in `runs/routed_holdout.jsonl` and both count toward spend; the summary uses the later line. The timed-out run's 13 contract calls are in `server_log.jsonl` under its own run ID and are not counted in the log check, because that run is replaced.
- The server log was read back from Cloud Logging at about 18:58 (`--read-server-log --since 2026-10-13T18:15:00Z`): 576 `contract_call` lines, 563 for the 108 scored runs and 13 for the replaced run.
- No harness change after the full run, apart from one label: the audit printed the server log's time as empty, because Cloud Logging moves a payload field named `time` into the entry's timestamp. The audit now reads `log_timestamp` when `time` is absent. It changes no number.

## Teardown

- `terraform destroy` in `infra/part3`, from 19:00:21, with the same image variable as the apply: 25 resources destroyed (the Cloud Run service and its invoker grants, the five service accounts and their grants, the image repository with the `p4-1` image, the build staging bucket, and the API enablement records; the APIs themselves stay on, `disable_on_destroy = false`).
- Checked afterward with gcloud (every call with `--project` and a short-lived token file from Application Default Credentials, deleted after each call): no Cloud Run service in us-central1, no `tw-p3-*` service account, no Artifact Registry repository, no Part 3 bucket; the Terraform state is empty. The gcloud default project was not changed.
- Not Terraform resources and left in place: Cloud Build's build record, and the service's log entries in Cloud Logging, which expire under the project's retention settings.
- Cloud Run cost, estimated at list prices: one warm instance of 2 vCPU and 4 GiB with CPU always allocated, about 18:00 to 19:01, roughly $0.20, plus about $0.01 of Cloud Build; recorded in the ledger as an estimate of $0.21, apart from model spend.

## Spend

- Gemini, Part 4, smoke test and the repeated run included: $5.19 of model spend and $0.06 of BigQuery, $5.25 in all (planned about $4.60; the stop line was $7 and was not reached).
- Series ledger (`results/series_spend.json`), Parts 2 to 7: $27.11, $7.89 under the $35 approved and $17.89 under the $45 hard cap.
- No Anthropic spend in Part 4.
