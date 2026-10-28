# Part 7 run log

All times UTC, October 27, 2026. Tessaway Freight is a fictional company.

- **Before any run** (commit f20f23f): revenue version 2 and margin version 2 in data/DEFINITIONS.md, the registry, the semantic layer (`financial_documents_v2`, `revenue_v2` and the margin metrics) and the lookup wording; golden set v2 computed once and pinned by hash; contract 2.1.0 with server-side routing; predictions. MetricFlow's version 2 metrics were checked against the version 2 gold SQL on the warehouse of record before the runs: the same six figures.
- **Deploy.** The gcloud CLI's own login needed a reauthentication this session could not do, so the image was built and the routing changed through the Cloud Build and Cloud Run Admin APIs with Application Default Credentials, the login Terraform uses. Image `context-server:p7-1`; the service came up at 19:52 with the canary routing set by Terraform (`{"default": "v1", "cohorts": {"2": "revenue_v2"}}`).
- **Smoke** (results/part7/smoke): the first six runs failed to open an MCP session while the new invoker grants propagated (refused at Cloud Run's front end before reaching the server, no model call, $0); they were run once more and answered. M2 and M3, three repeats: as designed, M3's version 2 run gave the "revenue moved, cost did not" figure. Smoke spend $0.28.
- **Canary**, 20:00 to 20:43, 72 runs at four at a time; E3 repeat 0 hit the 300-second limit and M4 repeat 1 failed, each run once more (both records kept). Gemini was slow (most runs 100 to 300 seconds); the contract's own calls took 2 ms for a lookup and under a second for a typical metric.
- **Rollback**, 20:44:04: the routing set to everyone on version 1 (revision tessaway-context-00002-zrd). Ready and serving all traffic at 20:49:07, 303 seconds after it was created. No run was in flight. The script's own timing crashed on a health check: Cloud Run reserves paths ending in "z", so `/healthz` is answered by Cloud Run's front end with a 404 and never reaches the server. The record in routing_changes.jsonl is taken from Cloud Run's revision times instead, and the script now waits on the Admin API's operation and checks the serving revision's settings.
- **Rollback check**, from 20:49, 72 runs at six at a time.
- **Rollback check** finished at about 21:02: 72 runs, none failed.
- **Rollout**, 21:03:41: the routing set to everyone on version 2, revenue and margin (revision tessaway-context-00003-78v), timed by the script: 311 seconds until the new revision served all traffic. Then 72 runs at six at a time.

## Teardown check (Oct 27, 2026, after the runs)

- Cloud Run services in the series project: 0. Artifact Registry repositories: 0. infra/part3 Terraform state: 0 resources.
- `pytest -q -m "not cloud"`: 314 passed, 11 deselected.
