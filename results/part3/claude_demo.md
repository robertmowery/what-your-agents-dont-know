# Part 3: the Claude demonstration

Unscored. One pass over the 24 Part 1 questions with the Claude Agent SDK (claude-agent-sdk==0.2.165) and `claude-sonnet-5-5`, reached through Anthropic's API (not Vertex AI), with the key read at run time from the macOS Keychain. The agent ran the **available** configuration: the Part 1 SQL tool in-process, and the same deployed contract endpoint the Gemini agents used, as a remote MCP server over HTTP, under its own service account. It has no context code of its own.

No answer was scored and none is reported. This file says only whether it worked, which operations it called, and what it cost.

| Measure | Value |
| --- | --- |
| Questions run | 24 of 24 |
| Runs that called the contract and finished without an error | 19 |
| Runs that ended in an error or a timeout | 0 |
| Runs that called no contract operation | 5 |
| Contract responses that carried the version | 43 of 43 |
| Server log lines for these runs, and how many match a recorded response ID | 43, 43 |
| SQL queries | 10 |
| Estimated cost (list prices) | $0.23 |
| Cost the SDK reported | $0.26 |
| Cap | $5.00 |

Calls by tool (the four contract operations, and the SQL tool):

- `compute_metric`: 24
- `lookup_definition`: 17
- `resolve_entity`: 2
- `run_sql`: 10

Caller in the server log: `tw-p3-agent-claude@PROJECT.iam.gserviceaccount.com` (43)
