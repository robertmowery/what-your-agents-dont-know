# Part 3 run log

Times are UTC, 2026-10-13. The Google Cloud project and the service URL are written as PROJECT and CONTRACT_URL throughout `results/part3`.

## Before any run

- **Versions checked in the run environment.** Python 3.13.4, google-adk 2.11.0, mcp 2.3.0 (with mcp-types 2.3.0), claude-agent-sdk 0.2.165, google-cloud-bigquery 3.46.1, rdflib 7.6.0, pyshacl 0.40.1, pyoxigraph 0.5.11; MetricFlow in its own environment as in Part 2 (dbt-metricflow 0.15.0). mcp 2.x renamed FastMCP to `MCPServer`; the server uses `MCPServer` with the streamable HTTP transport, stateless, JSON responses.
- **The INTERVAL fix.** `tessaway/warehouse/query.py` now writes a BigQuery `INTERVAL` cell (which the client returns as a `relativedelta`) in BigQuery's canonical text form, and writes any other cell JSON cannot carry as text, instead of ending the run. Tested in `tests/test_query.py`. This is the only change to the SQL tool since Parts 1 and 2.
- **Commit `7c172dc`** (15:42): the contract server, the Terraform, both agents, the harness, the tests and `predictions.md`, committed and pushed before the first agent run.
- **Deployment.** `infra/part3` applied in two steps: the repository, staging bucket and service accounts (15:27), then the Cloud Run service with image `context-server:p3-1`, built by Cloud Build from the working tree (15:30 to 15:33, 3 min 31 s). The service listens after loading the knowledge graph from BigQuery, checking the eleven SHACL rules against it and starting MetricFlow: 205 s on its first start. One instance kept warm (`min_instances = 1`), CPU always allocated, at most two instances.
- **Note on the image.** The image was built from the working tree, which at that moment also held another session's uncommitted Part 2 edits to `tessaway/config.py` and `tessaway/layers/semantic.py`. Those edits add functions that write the project id out of saved files (`redact_project`, `write_export`); they do not touch `run_metrics`, `generate_sql` or anything the contract calls, so the layers behind the contract behave as Part 2's.
- **Secured, checked.** `python run_part3.py --check-auth`: no token, HTTP 403 (Cloud Run IAM); a token with a forged signature, HTTP 401; the routed agent's ID token, HTTP 200. The first try of the third call returned 403 for about a minute after the invoker grant was created, until the grant propagated; the check was run again and passed. `pytest -m cloud tests/test_part3_cloud.py`: 5 passed (every operation answers on the deployed service with the version stamped; an unauthenticated call refused).

## Smoke test (results/part3/smoke)

Two questions per configuration, one run each: available and routed on L1 and M1; routed_holdout on H1 and H11. Spend $0.26.

| Configuration | Question | Outcome | Answer source | Tools called |
| --- | --- | --- | --- | --- |
| available | L1 | right | sql | run_sql 4, check_rule 2, lookup_definition 1 |
| available | M1 | right | both | compute_metric 1, run_sql 1, lookup_definition 2, check_rule 1 |
| routed | L1 | declined | none | all four operations |
| routed | M1 | right | contract | compute_metric 1, lookup_definition 3, check_rule 2 |
| routed_holdout | H1 | right | contract | compute_metric 4, lookup_definition 3, check_rule 1, resolve_entity 1 |
| routed_holdout | H11 | declined | none | lookup_definition 8, compute_metric 3, check_rule 2, resolve_entity 1 |

Wiring: every contract response (44) carried version 1.0.0 and a response ID; the server log, read back from Cloud Logging, agreed with the agents' records on all 44 calls (response ID, operation, version and caller), and each configuration appeared under its own service account. The routed agent was offered the four operations and no SQL tool; the available agent all five.

### Harness changes after the smoke test, and why

None of these changes what an agent is given, told or scored on.

1. `write_summary` crashed (division by zero) when a `--questions` filter left a configuration with no runs, as it did when the held-out smoke summary was written. Configurations left empty by the filter are now dropped before the summary is built.
2. The server log was read with the run-file reader, which keys lines by question and trial; log lines have neither, so the summary failed. Log lines, and the spend total, are now read with a plain line reader. For spend this also means a run repeated after a failure is counted twice, as Part 2 counted it, instead of once.
3. `gcloud logging read` failed once with no message and then worked; the reader now retries twice and prints gcloud's error (with the project id taken out).

## Full run (results/part3)

- `python run_part3.py`, three runs per question, six questions in flight, started 15:52:23. available 15:52 to 16:09, routed 16:09 to 16:18, routed_holdout 16:18 to 16:24. 180 runs.
- Two available runs (L1 and L2, first trial) ended in `ResourceExhausted` (HTTP 429 from Gemini) after the client's own retries, with no answer. They were run again once with `--retry-failed`, the Part 1 rule, at 16:27 to 16:28; both were right. Both lines are kept in `runs/available.jsonl` and both count toward spend; the summary uses the later line.
- The Claude demonstration ran beside the Gemini runs, 15:54 to 15:55 (`python run_part3.py --claude-demo`), after a one-question check under `smoke/` at 15:53. 24 questions, no errors. See `claude_demo.md`.
- The server log was read back from Cloud Logging at about 16:29 (`--read-server-log --since 2026-10-13T15:00:00Z`): 1,070 `contract_call` lines covering the smoke test, the cloud tests, the full run and the Claude demonstration (`server_log.jsonl`).

### Harness changes after the full run, and why

None changes a run, a score or an answer source. All three change only how the server-log check is labeled and how spend is counted.

1. **The server-log check named one call wrongly.** In one available run on E6, the agent called `compute_metric` with `where` as a string instead of a list. The MCP SDK refused the call against the published schema before the contract code ran: the agent got an error, no envelope, no version, no response ID, and the server wrote no log line. The first summary counted this as "a call with no response (the run was cut off)" and marked the run as a mismatch, which failed P12. P12's written rule covers calls recorded with a response ID, and every log line for a run; this call has neither. The check now puts such calls in their own count, "refused by the MCP layer before the contract ran", reports it beside P12, and tests P12 by its rule as written. With the label corrected P12 holds; the refused call is reported in `summary.md`, `server_log_check.md` and `article_numbers.json`. It is also a finding: a call the protocol layer refuses never reaches the server's own log.
2. The Anthropic spend now counts, for each run, the higher of the list-price estimate and the cost the SDK reported ($0.28 against $0.25 at list prices).
3. `claude_demo.md` heads its call counts "Calls by tool", because the counts include the SQL tool.

## Teardown

- `terraform destroy` in `infra/part3`, 16:30:06 to 16:30:46 UTC: 25 resources destroyed (the Cloud Run service and its invoker grants, the five service accounts and their grants, the image repository with its image, the build staging bucket with its objects, and the API enablement records). The APIs themselves were left on (`disable_on_destroy = false`), as in `infra/`.
- Checked afterward with gcloud: no Cloud Run service in us-central1, no `tw-p3-*` service account, no Artifact Registry repository, no Part 3 bucket; the Terraform state is empty.
- `infra/` (the datasets of Parts 1 and 2) was not touched.
- Not Terraform resources and left in place: Cloud Build's build record, and the service's log entries in Cloud Logging, which expire under the project's retention settings.
- Cloud Run cost, estimated at list prices: one instance of 2 vCPU and 4 GiB with CPU always allocated, about 15:34 to 16:30, roughly $0.16, plus about $0.01 of Cloud Build; recorded in the ledger as an estimate of $0.20, apart from model spend.

## Spend

- Gemini, Part 3, smoke tests and the two repeated runs included: $6.73 of model spend and $0.10 of BigQuery, $6.83 in all (the plan was $5.50 to $7.50; the stop line was $15).
- Anthropic (Claude demonstration, smoke check included): $0.28, against a cap of $5.
- Series ledger (`results/series_spend.json`), Parts 2 to 7: $21.86 of the $35 approved, $23.14 under the $45 hard cap. Anthropic spend is listed apart, outside the cap.
