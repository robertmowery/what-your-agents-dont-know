# What Your Agents Don't Know

Reference code for the article series *What Your Agents Don't Know* by Robert H. Mowery III ([robertmowery.com](https://robertmowery.com)).

Your agents can reach your data. This series shows how to give them what it means, and how to govern, watch and pay for that once they are doing real work.

Each part pairs an executive article on Medium with a technical companion on Substack. Every number in the articles comes from code in this repository.

| Part | Topic |
| --- | --- |
| 1 | Measuring context failure against a raw warehouse |
| 2 | One dataset, three context layers: metrics, an ontology and a graph |
| 3 | A context contract over MCP |
| 4 | Provenance: tracing an answer to a definition, an owner and a version |
| 5 | Evals that catch context drift |
| 6 | Cost per correct answer |
| 7 | Shipping a definition change |

The freight company used throughout, Tessaway Freight, is fictional, and its data is synthetic.

- **Agent runtimes:** Google Agent Development Kit, pinned to `google-adk==2.11.0`, and the Claude Agent SDK, pinned to `claude-agent-sdk==0.2.165`
- **Models:** Gemini and Claude, both through Vertex AI in one Google Cloud project. Exact model names are pinned in `tessaway/config.py` and recorded in every results file.
- **Warehouse:** BigQuery
- **Python:** 3.11 or later

## Set up

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

gcloud auth application-default login
cp .env.example .env                       # set GOOGLE_CLOUD_PROJECT to a project you own

cd infra && cp terraform.tfvars.example terraform.tfvars   # set project_id
terraform init && terraform apply          # two APIs and one private dataset
cd ..

.venv/bin/python -m tessaway.warehouse.load   # generate the data and load it to BigQuery
```

There are no keys in this repository and none are needed. See [infra/README.md](infra/README.md) for what Terraform creates and for the one console step that enables Claude on Vertex AI.

## Part 1: a clean warehouse and two agents

Part 1 asks one question: if an agent can read every table in a clean warehouse, how often is it confidently wrong about ordinary business questions?

The warehouse is complete and its joins are valid. What it does not hold is meaning. Six traps are planted in it, each a pattern common in freight data, and each is written down in [data/TRAPS.md](data/TRAPS.md) before any agent runs.

| Term | Where the meanings split |
| --- | --- |
| On-time | Operations counts arrival inside the appointment window. The portal counts delivery by the requested date. The customer contract leaves out delays the shipper caused. |
| Delivered | A status event says delivered. Billing waits for signed proof of delivery. |
| Margin per load | Revenue minus carrier pay, until fuel surcharges, accessorials, credits and canceled-load fees sit in other tables. |
| Customer | The shipper, the bill-to party and the parent account are three different rows. |
| A load | Re-tendered loads appear twice. Test and voided loads are flagged, not deleted. |
| Money and time | Cross-border loads carry Canadian dollars. Timestamps are in UTC, appointments in local time. |

### What is in the repo

| Piece | Where | Needs a model |
| --- | --- | --- |
| The schema: names and types, which is all an agent is shown | `tessaway/warehouse/schema.py` | No |
| The data generator, fixed seed | `tessaway/warehouse/generate.py` | No |
| The BigQuery loader | `tessaway/warehouse/load.py` | No |
| The one tool: a read-only query | `tessaway/warehouse/query.py` | No |
| The traps | `data/TRAPS.md` | No |
| The official definitions, which agents never see | `data/DEFINITIONS.md` | No |
| 24 questions with gold SQL, tolerances and decoys | `questions/part1.yaml` | No |
| The instruction both agents get | `tessaway/agents/prompt.py` | No |
| Agent one: Google ADK on Gemini | `tessaway/agents/adk_agent.py` | Yes |
| Agent two: Claude Agent SDK on Claude through Vertex AI | `tessaway/agents/claude_agent.py` | Yes |
| The scorer: plain code, no model | `tessaway/scoring.py` | No |
| The run script | `run_part1.py` | Yes |

### The question set

Twenty-four questions an executive would ask, six in each of four groups:

| Group | What it tests | Example |
| --- | --- | --- |
| `lookup` | Nothing. One table, no definition needed. The control group. | How many carriers do we have on file? |
| `metric` | A number with a definition behind it | What was our on-time delivery rate in September 2026? |
| `entity` | Who or what something is | Who was our largest customer by revenue in Q3 2026? |
| `rule` | A business rule that decides the answer | How many loads delivered in September 2026 are we still unable to bill? |

Each entry in `questions/part1.yaml` stores the question, its group, the hand-written SQL that produces the correct answer, a tolerance, which official definition decides it, and why. It also stores decoys: plausible wrong readings with the SQL that produces each, so the scorer can name the mistake an agent made.

### The agents

Both agents get the same instruction, the same schema and the same single tool. The schema is table names, column names and types. Nothing says what a column means.

The tool runs one read-only `SELECT` at a time and returns at most 50 rows. An agent may run at most 8 queries for a question, and is told so.

| Configuration | Runtime | Model |
| --- | --- | --- |
| `adk_gemini_flash` | Google ADK | `gemini-3.8-flash` |
| `adk_gemini_pro` | Google ADK | `gemini-3.1-pro-preview`, the stronger Gemini |
| `claude_sonnet` | Claude Agent SDK | `claude-sonnet-5-5` through Vertex AI |
| `claude_opus` | Claude Agent SDK | `claude-opus-5-5` through Vertex AI, the stronger Claude |

The Claude Agent SDK's built-in tools are switched off and no local settings are loaded, so the Claude agent has the warehouse tool and nothing else. The one difference in what the models see is the tool's name: `run_sql` on ADK, `mcp__warehouse__run_sql` on the Claude Agent SDK, which prefixes tools it serves in-process.

### Scoring

Every reply ends with a line `ANSWER: <value>`, or `ANSWER: NEEDS_CLARIFICATION` when the agent declines or asks. Plain code sorts each reply into one bin:

| Bin | Meaning |
| --- | --- |
| `right` | Matches the correct answer within the tolerance |
| `confidently_wrong` | The agent gave an answer and it does not match |
| `declined` | The agent said it could not answer, or asked for clarification |
| `no_answer` | Nothing to score: an error, a timeout or no final line |

The headline number is the confidently wrong share, overall and by question group. Counts must match exactly. Money is right within one percent and rates within half a percentage point.

### Run it

```bash
.venv/bin/python -m pytest -q                 # generator, scorer and query limits; no model, no cloud
.venv/bin/python -m tessaway.questions        # run the gold SQL and print every correct answer

# A two-question smoke test, kept apart from the real run
.venv/bin/python run_part1.py --runs 1 --questions L1,M1 --out smoke

# The experiment: 24 questions x 10 runs for each configuration
.venv/bin/python run_part1.py
```

`run_part1.py` appends each run to `results/part1/runs/<config>.jsonl` as it finishes, so a stopped run picks up where it left off. It stops starting new runs when estimated spend reaches `--budget-usd` (default 45). A Claude configuration that cannot be reached on Vertex AI is skipped and listed as not run.

### Results files

Every number is written by `run_part1.py`:

| File | Holds |
| --- | --- |
| `results/part1/gold_answers.json` | The correct answer to every question, and what each decoy returns |
| `results/part1/<config>.json` | Every run: the reply, the bin, the SQL the agent wrote, tokens and estimated cost, plus the model name and the date it was checked |
| `results/part1/summary.md`, `summary.json` | Right, confidently wrong, declined and no answer, by configuration, question group and question |
| `results/part1/spend.json` | Estimated spend across everything run, smoke tests included |

### Where the runs stand

Both Gemini configurations are complete: 24 questions, 10 runs each, 240 runs per configuration. The two Claude configurations are built and wired but have not run, because the Claude models were not yet enabled for the project on Vertex AI. `results/part1/summary.md` says which configurations ran and which did not, and it is the authority for every number.

Two things to know when reading the results:

- The limit of 8 queries per question was reached in most runs outside the lookup group. `summary.md` counts how often, and how many declines say they ran out of queries.
- A run that ended in a timeout with nothing to score was run once more, and only once. Both attempts are in `results/part1/runs/`.

### Rules this experiment keeps

- The traps, the definitions and the questions were committed before any agent ran.
- No trap is tuned and no question is dropped after seeing agent results. If the agents do well, that is the result.
- Nothing is scored by a model.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
