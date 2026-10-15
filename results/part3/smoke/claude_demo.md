# Part 3: the Claude demonstration

Unscored. One pass over the 24 Part 1 questions with the Claude Agent SDK (claude-agent-sdk==0.2.165) and `claude-sonnet-5-5`, reached through Anthropic's API (not Vertex AI), with the key read at run time from the macOS Keychain. The agent ran the **available** configuration: the Part 1 SQL tool in-process, and the same deployed contract endpoint the Gemini agents used, as a remote MCP server over HTTP, under its own service account. It has no context code of its own.

No answer was scored and none is reported. This file says only whether it worked, which operations it called, and what it cost.

| Measure | Value |
| --- | --- |
| Questions run | 1 of 24 |
| Runs that called the contract and finished without an error | 1 |
| Runs that ended in an error or a timeout | 0 |
| Runs that called no contract operation | 0 |
| Contract responses that carried the version | 3 of 3 |
| Server log lines for these runs, and how many match a recorded response ID | 0, 0 |
| SQL queries | 0 |
| Estimated cost (list prices) | $0.02 |
| Cost the SDK reported | $0.02 |
| Cap | $5.00 |

Calls by operation:

- `compute_metric`: 2
- `lookup_definition`: 1

Caller in the server log: 
