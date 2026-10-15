# Part 2 test status

Recorded on 2026-10-09, after the runs.

| Run | Command | Result |
| --- | --- | --- |
| Default: no model, no cloud | `python -m pytest -q` | 154 passed, 5 deselected |
| Cloud: BigQuery and the MetricFlow environment | `python -m pytest -q -m cloud` | 5 passed |
| Lint | `ruff check .` and `ruff format --check .` | Clean |
| Types | `mypy` | No issues in 30 source files |

What the cloud tests hold:

- Every one of the 18 metrics returns what the Part 1 gold SQL returns: 25 of 25 checks. The saved comparison, with the SQL MetricFlow generated for each, is `results/part2/semantic_gold_check.json`.
- The committed `semantic_layer/catalog.json` is what MetricFlow reports for the project.
- The SQL comes from MetricFlow and reads the dbt views.
- The knowledge graph built from BigQuery is, triple for triple, the graph built from the data generator.

What the default tests hold, among others:

- Every one of the 11 SHACL shapes passes on the generated data (about 216,000 triples) and fails on a violation built to break it.
- The graph has 39 customers, 71 shipping sites, 32 bill-to parties and 576 re-tender links, as `data/TRAPS.md` states.
- No tool description, instruction paragraph or ontology entry states an answer, names a particular account or carrier, or repeats a question.
- Taking the added paragraphs out of the Part 2 instruction gives the Part 1 instruction exactly.
