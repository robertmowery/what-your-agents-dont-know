# Part 3: the server's call log against the agents' own records

Written by `run_part3.py`. The context server writes one structured line per contract call (caller, operation, contract version, time, response ID, run ID). After the runs the lines were read back from Cloud Logging (`server_log.jsonl`) and compared with what each agent recorded itself: the response ID, operation and version of every contract response it received, and the service account it ran under.

| Measure | Count |
| --- | --- |
| Runs compared | 180 |
| Runs whose two records agree in full | 180 |
| Contract calls the agents recorded | 973 |
| Server log lines for those runs | 972 |
| Recorded calls that agree (response ID, operation, version, caller) | 972 |
| Recorded calls missing from the server log | 0 |
| Recorded calls with no response and no error (the run was cut off) | 0 |
| Recorded calls the MCP layer refused before the contract ran (invalid arguments: no response ID, no log line) | 1 |
| Server log lines not in the agent's record | 0 |
| Calls that differ | 0 |
| Runs with a mismatch, not cut off | 0 |
| Runs with a mismatch, cut off by a timeout or an error | 0 |

Callers in the log (the project id is replaced by PROJECT):

- `tw-p3-agent-available@PROJECT.iam.gserviceaccount.com`: 277 calls
- `tw-p3-agent-routed@PROJECT.iam.gserviceaccount.com`: 695 calls

## Mismatches

```
{"run_id": "4f5f9993-d589-48aa-8d68-8f7d74ec79e9", "question_id": "E6", "problem": "refused by the MCP layer before the contract ran; no response ID, no server log line", "operation": "compute_metric", "error": "Error executing tool compute_metric: 1 validation error for compute_metricArguments\nwhere\n  Input should be a valid list [type=list_type, input_value=\"tender__carrier_type = '3P'\", input_type=str]\n    For further information visit https://errors.pydantic.dev/2.14/v/list_type"}
```
