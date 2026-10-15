# Part 2 results

Written by `run_part2.py`. Tessaway Freight is a fictional company and the data is synthetic.

Each configuration is the Part 1 agent (Google ADK, `gemini-3.8-flash`) with the same SQL tool and one extra tool per context layer. Each reply is scored by the Part 1 scorer into one of four bins. Shares are of all runs.

The baseline row is Part 1's Flash result at ten runs per question and was not run again. The Part 2 rows ran each question three times, so their shares are rougher: one run is 1.4 points of an overall share and 5.6 points within a question group. Small differences are not findings.

| Configuration | Tools beside `run_sql` | Runs | Complete | Right | Confidently wrong | Declined | No answer | Est. cost | Cost per question |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | none | 10 of 10 | yes | 0.0% | 50.0% | 50.0% | 0.0% | $0.51 | $0.0511 |
| flash_ontology | `lookup_ontology` | 1 of 1 | yes | 0.0% | 0.0% | 100.0% | 0.0% | $0.06 | $0.0578 |

## Right, by question group

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| baseline | n/a | 0.0% (0 of 10) | n/a | n/a |
| flash_ontology | n/a | 0.0% (0 of 1) | n/a | n/a |

## Confidently wrong, by question group

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| baseline | n/a | 50.0% (5 of 10) | n/a | n/a |
| flash_ontology | n/a | 0.0% (0 of 1) | n/a | n/a |

## Declined, by question group

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| baseline | n/a | 50.0% (5 of 10) | n/a | n/a |
| flash_ontology | n/a | 100.0% (1 of 1) | n/a | n/a |

## Change against the baseline, in percentage points

Right / confidently wrong / declined. A positive first number is more right answers.

| Configuration | overall | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- | --- |
| flash_ontology | +0.0 / -50.0 / +50.0 | n/a | +0.0 / -50.0 / +50.0 | n/a | n/a |

## By question: right / confidently wrong / declined / no answer

| Question | Group | baseline | flash_ontology |
| --- | --- | --- | --- |
| M1 | metric | 0 / 5 / 5 / 0 | 0 / 0 / 1 / 0 |

## Tool calls

Mean calls per run, counting calls that were let through. The agent was free to use a layer tool or ignore it.

| Configuration | `run_sql` | `query_metrics` | `lookup_ontology` | `query_graph` | Runs with no layer call | Runs with no SQL | First call was SQL |
| --- | --- | --- | --- | --- | --- | --- | --- |
| flash_ontology | 8.00 (1 runs) | not given | 5.00 (1 runs) | not given | 0 of 1 | 0 of 1 | 0 of 1 |

### Where a layer applied, and whether the agent used it

A layer applies to a question when it holds something the question needs. The rule is `applies_to` in `run_part2.py`, fixed before any run: the semantic layer applies when one metric query answers the question; the ontology when an official definition decides it; the graph when one of those definitions is about customers or loads.

| Configuration | Layer | Questions | Runs | Used the layer | Ignored the layer |
| --- | --- | --- | --- | --- | --- |
| flash_ontology | ontology | 1 | 1 | 1 | 0 |

### Going around the semantic layer

The bypass count: runs on a question that one metric query answers, in which the agent ran SQL anyway.

| Configuration | Runs on such questions | Ran SQL | Never called the metric tool | Called both | Right when SQL was run | Answered from metrics alone | Right from metrics alone |
| --- | --- | --- | --- | --- | --- | --- | --- |

## Tokens, time and cost per question

| Configuration | Input tokens | Output tokens | Cache-read share of input | Model calls | SQL queries | Seconds | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 32,561 | 7,412 | 5.2% | 10.00 | 8.00 | 93.8 | $0.0511 |
| flash_ontology | 73,043 | 4,458 | 27.9% | 15.00 | 8.00 | 67.7 | $0.0578 |

## Limits

Each question allows 8 SQL queries and 8 calls to each layer tool, and the agent is told both. A run is also stopped at a ceiling of model calls it is not told about: 16 in Part 1, and 16 plus 8 for each layer tool here, so an agent inside the limits it was told about always has calls left to answer.

| Configuration | Model-call ceiling | Asked for a further SQL query | Asked for a further layer call | Hit the model-call ceiling | Timed out | Declines that mention the query limit |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 16 | 10 of 10 | n/a | n/a | 0 | 1 of 5 |
| flash_ontology | 24 | 1 of 1 | 0 | 0 | 0 | 1 of 1 |

## Wrong answers that said they were assuming something

- baseline: 0 of 5 confidently wrong answers used a word such as "assume", "interpret" or "definition" somewhere in the reply.
- flash_ontology: 0 of 0 confidently wrong answers used a word such as "assume", "interpret" or "definition" somewhere in the reply.

## Not run

- flash_semantic
- flash_graph
- flash_all_three

Model names and prices were checked on 2026-10-09. Costs are estimates from token counts and list prices.
