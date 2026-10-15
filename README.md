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

## Part 2: one dataset, three context layers

Part 2 asks the Part 1 questions again, of the same agent on the same warehouse, with a context layer added. Three layers are built, each from [data/DEFINITIONS.md](data/DEFINITIONS.md) and from nothing else, and each answers a different question:

| Layer | The question it answers | What is built | Built with |
| --- | --- | --- | --- |
| Semantic layer | What does this number mean? | 18 named metrics in YAML, on six dbt views | `dbt-metricflow==0.15.0` (MetricFlow 0.213.0), `dbt-core==1.12.5`, `dbt-bigquery==1.12.1` |
| Ontology | What exists, and which rules bind it? | 19 classes, 19 properties and 6 business terms in OWL; 11 rules in SHACL | `rdflib==7.6.0`, `pyshacl==0.40.1` |
| Knowledge graph | How do these particular things connect? | The actual accounts, carriers, tenders and loads: about 216,000 triples | Oxigraph, through `pyoxigraph==0.5.11` |

Nothing is added to the warehouse tables, and no question, correct answer, trap or scoring rule is changed.

### What is in the repo for Part 2

| Piece | Where | Needs a model |
| --- | --- | --- |
| The metrics, in YAML | `semantic_layer/models/semantic.yml` | No |
| The dbt views the metrics sit on | `semantic_layer/models/*.sql` | No |
| The MetricFlow worker: a metric request in, generated SQL out | `semantic_layer/mf_worker.py` | No |
| The harness side of the semantic layer, and the gold check | `tessaway/layers/semantic.py` | No |
| The ontology's classes and terms (OWL) | `ontology/tessaway.ttl` | No |
| The rules data can be checked against (SHACL) | `ontology/shapes.ttl` | No |
| Loading, looking up and validating the ontology | `tessaway/layers/ontology.py` | No |
| The graph loader and the SPARQL tool | `tessaway/layers/graph.py` | No |
| What a Part 2 agent is told | `tessaway/agents/layer_prompt.py` | No |
| The Part 2 agent: Part 1's, with one extra tool per layer | `tessaway/agents/adk_layer_agent.py` | Yes |
| The run script | `run_part2.py` | Yes |

### Where each definition's logic lives

MetricFlow writes the SQL for every metric query; nothing here imitates it with templates. What MetricFlow cannot say is done in a dbt view the metric sits on, which is the ordinary way to use it.

| Definition | In a dbt view (`semantic_layer/models`) | In the metric YAML |
| --- | --- | --- |
| `load` | `loads.sql`: one row per first tender, never a test or voided row; booked on the UTC date | `loads_booked` counts the rows |
| `delivered_load` | `deliveries.sql`: status `DLVD`, real loads only, the last delivery stop | `delivered_loads` counts the rows and is dated by `delivered_date` |
| `local_time` | `deliveries.sql`: the delivery date and the on-time comparison are made on the clock at the stop | Nothing: MetricFlow has no way to pick the last stop or apply a row's own time zone |
| `on_time` | `deliveries.sql`: two row flags, `arrived_on_time` and `shipper_delayed` | The rule itself: which rows are on time, which rows are measured, and the ratio (`on_time_rate`) |
| `portal_on_time` | `portal_shipments.sql`: the portal's own flag and date | `portal_on_time_rate`, labeled as not the official rate |
| `billable` | `deliveries.sql`: one row flag, `has_signed_pod` | `delivered_loads_not_billable` |
| `customer` | `tenders.sql` and `deliveries.sql`: the parent the shipping site rolls up to | The `tender__customer_name` dimension; `customers_shipped` counts distinct parents with a delivery |
| `revenue`, `margin` | `financial_documents.sql`: invoices, credit memos and canceled-load fees as one row each, with revenue and carrier cost | `revenue`, `carrier_cost`, `margin`, `invoiced_loads`, `margin_per_load`, `margin_percentage` |
| `currency` | `financial_documents.sql`: every amount in US dollars at the document month's rate | Nothing |

The ontology states every one of these definitions in words and computes nothing. Its SHACL shapes cover the rules that data can be checked against (a load is counted once, a test or voided row is not a load, a site rolls up to one customer, an invoice needs a signed proof of delivery, and so on). Rules that say how a number is worked out are `tw:rule` notes on the term they belong to, because they describe a calculation, not a shape the graph must have.

The knowledge graph uses the ontology's identifiers. It holds which site rolls up to which customer, the bill-to party and carrier on every tender, which tender replaced which, and one node per load. It holds no dates and no amounts.

### How a layer reaches the agent

In this part each layer is handed to the agent inside the test harness, as one extra tool beside the same read-only SQL tool. There is no server and no MCP; that is Part 3.

| Tool | Layer | What it does |
| --- | --- | --- |
| `run_sql` | none | Part 1's tool, unchanged: one read-only `SELECT`, at most 50 rows, at most 8 queries per question |
| `query_metrics` | Semantic | Takes metric names, group-by names, filters and a date range. MetricFlow writes the SQL, BigQuery runs it, the rows come back. The agent never sees the SQL |
| `lookup_ontology` | Ontology | Takes a term and returns its definition, its rules and where the warehouse holds it |
| `query_graph` | Knowledge graph | Runs one read-only SPARQL query against the Oxigraph store, at most 50 rows |

Each layer tool may be called at most 8 times per question, and the agent is told so. The instruction is Part 1's with one paragraph added per tool; a test holds that taking those paragraphs out gives the Part 1 text exactly. The agent is free to use a layer or ignore it, and every tool call is saved in order.

| Configuration | Tools | Runs |
| --- | --- | --- |
| baseline | `run_sql` | Part 1's `adk_gemini_flash` result, 10 runs per question. Not run again |
| `flash_semantic` | `run_sql`, `query_metrics` | 24 questions x 3 |
| `flash_ontology` | `run_sql`, `lookup_ontology` | 24 questions x 3 |
| `flash_graph` | `run_sql`, `query_graph` | 24 questions x 3 |
| `flash_all_three` | all four | 24 questions x 3 |

All four run on Google ADK with `gemini-3.8-flash`. With three runs per question the shares are rougher than Part 1's: one run is 1.4 points of an overall share and 5.6 points within a question group. Small differences are not findings.

### Set up and run

```bash
.venv/bin/pip install -r requirements-dev.txt          # adds rdflib, pyshacl and pyoxigraph

# dbt and MetricFlow live in their own environment: dbt-bigquery and google-adk
# need versions of google-genai that cannot be installed together.
python3 -m venv .venv-dbt
.venv-dbt/bin/pip install -r requirements-semantic.txt

cd infra && terraform apply && cd ..                   # adds the tessaway_sem dataset for the views

set -a && source .env && set +a                        # dbt reads the project from the environment
(cd semantic_layer && DBT_PROFILES_DIR=. ../.venv-dbt/bin/dbt run)   # build the six views

.venv/bin/python -m pytest -q                          # no model, no cloud: every SHACL rule, the graph counts, the tool descriptions
.venv/bin/python -m pytest -q -m cloud                 # BigQuery: every metric against the Part 1 gold SQL
.venv/bin/python -m tessaway.layers.semantic --check-gold   # the same check, saved to results/part2

.venv/bin/python run_part2.py --runs 1 --questions L1,M1 --out smoke   # a smoke test, kept apart
.venv/bin/python run_part2.py                          # the experiment: 4 configurations x 24 questions x 3 runs
.venv/bin/python analysis/part2_article_numbers.py     # the figures the articles quote
```

### Results files

| File | Holds |
| --- | --- |
| `results/part2/predictions.md` | What the brief predicted and how each prediction is read against the runs, written before any run |
| `results/part2/semantic_gold_check.json` | Every metric's MetricFlow SQL, run on BigQuery, beside the Part 1 gold SQL |
| `results/part2/<config>.json`, `runs/<config>.jsonl` | Every run: the reply, the bin, every tool call in order, the SQL MetricFlow generated, tokens and estimated cost |
| `results/part2/summary.md`, `summary.json` | Each configuration beside the baseline: right, confidently wrong and declined overall, by group and by question; the change against the baseline; tool calls and the bypass count; tokens and cost; limits |
| `results/part2/article_numbers.json` | Everything the Part 2 articles quote |
| `results/part2/caching_note.md` | How prompt caching works for this model today, and why nothing was switched on |
| `results/part2/ossie_note.md` | What Apache Ossie tooling exists today and what was tried |
| `results/part2/spend.json`, `results/series_spend.json` | Estimated spend for Part 2, and for Parts 2 to 7 against the approved budget |

The SQL MetricFlow generates names the Google Cloud project. Wherever it is saved (the runs, the gold check, `semantic_layer/exports/osi_document.json`), the project ID is replaced with `PROJECT`; your own runs are saved the same way.

### Where the Part 2 runs stand

All four configurations are complete: 24 questions, three runs each, 288 runs. `results/part2/summary.md` is the authority for every number, and `results/part2/run_log.md` says what was run in what order.

Three things to know when reading the results:

- After a two-question smoke test and before the full run, the harness's ceiling on model calls was raised from Part 1's 16 to 16 plus 8 for each layer tool. The agent is never told that number, and nothing it sees changed. Without the change an agent could stay inside every limit it was told about and be cut off before it could answer. The run log has the detail.
- Four runs ended in a timeout or a harness error with nothing to score and were run once more, by the Part 1 rule. Both attempts are in `results/part2/runs/`.
- The semantic layer was built by someone who knew the 24 questions, and one metric query reproduces the correct answer to all 18 that need a definition (`semantic_layer/gold_checks.yaml`). The runs measure whether the agent finds and uses the right metric. They do not measure how a semantic layer written without sight of the questions would do.

### Rules this experiment keeps

- The layers, the tool descriptions and the instruction paragraphs were committed before any Part 2 agent ran.
- No definition, description or instruction is added or reworded after seeing which questions fail. A configuration with a real bug is discarded and run again in full, and that is recorded.
- No layer answers a question. Each states a definition, a rule or a relationship, and tests check that no description holds an answer.
- The layers were written by the person who wrote the questions, from the definitions file. That is a limit of the experiment.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
