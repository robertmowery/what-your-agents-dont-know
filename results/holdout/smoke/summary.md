# Held-out fairness test for Part 2

Written by `run_holdout.py`. Tessaway Freight is a fictional company and the data is synthetic.

Twelve questions written after the Part 2 layers were committed, by a writer who was not shown the layers (`data/HOLDOUT.md`). Two agents on `gemini-3.8-flash` with Google ADK: the Part 1 agent (schema and the SQL tool), and the same agent with the semantic layer's `query_metrics` tool. The layer, the tool description, the instruction and the scorer are Part 2's, unchanged. Each reply is scored into one of four bins. Shares are of all runs.

Each question ran three times: 36 runs a configuration. One run is 2.8 points of an overall share and 8.3 points within a question group. Small differences are not findings.

| Configuration | Tools beside `run_sql` | Runs | Complete | Right | Confidently wrong | Declined | No answer | Est. cost | Cost per question |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | none | 2 of 2 | yes | 0.0% | 0.0% | 100.0% | 0.0% | $0.06 | $0.0323 |
| flash_semantic | `query_metrics` | 2 of 2 | yes | 100.0% | 0.0% | 0.0% | 0.0% | $0.06 | $0.0284 |

Change from baseline to semantic layer, in percentage points: right +100.0, confidently wrong +0.0, declined -100.0.

## Beside the 24 Part 1 questions

| Question set | Baseline right | Semantic layer right | Change in points |
| --- | --- | --- | --- |
| 24 Part 1 questions (the layer's author knew them) | 43.8% | 100.0% | +56.2 |
| 12 held-out questions | 0.0% | 100.0% | +100.0 |

The 24 include six lookup questions that every configuration gets right; the held-out set has none. The Part 1 baseline ran each question ten times.

## By question group: right / confidently wrong / declined / no answer

| Configuration | metric | entity | rule |
| --- | --- | --- | --- |
| baseline | 0 / 0 / 1 / 0 (0.0% right) | 0 / 0 / 1 / 0 (0.0% right) | n/a |
| flash_semantic | 1 / 0 / 0 / 0 (100.0% right) | 1 / 0 / 0 / 0 (100.0% right) | n/a |

## By coverage class: right / confidently wrong / declined / no answer

The class says what the semantic layer could answer, and was fixed in `coverage.json` before any run (`coverage.md`).

| Coverage class | Questions | baseline | flash_semantic |
| --- | --- | --- | --- |
| one metric query, as is | none | n/a | n/a |
| metric plus a filter or dimension the layer already has | H1, H5 | 0 / 0 / 2 / 0 (0.0% right) | 2 / 0 / 0 / 0 (100.0% right) |
| needs more than one metric query or arithmetic on results | none | n/a | n/a |
| not answerable from the layer | none | n/a | n/a |

## By question

Counts are right / confidently wrong / declined / no answer. Answers are the final line of each run, in run order.

| Question | Group | Coverage class | Gold | baseline | baseline answers | flash_semantic | flash_semantic answers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | metric | metric_plus_filter | 88.17 | 0 / 0 / 1 / 0 | NEEDS_CLARIFICATION | 1 / 0 / 0 / 0 | 88.1656804733728 |
| H5 | entity | metric_plus_filter | Northgate Foods Group | 0 / 0 / 1 / 0 | NEEDS_CLARIFICATION | 1 / 0 / 0 / 0 | Northgate Foods Group |

The questions:

- H1: What was our own fleet's on-time delivery rate in Q2 2026?
- H5: Which customer did we deliver the most loads for in the first half of 2026?

## Tool calls, semantic-layer configuration

Mean calls per run: `run_sql` 2.00, `query_metrics` 2.50. 2 of 2 runs called the metric tool and 2 ran SQL. The first call was SQL in 1 runs. 0 metric calls came back with an error.

| Coverage class | Runs | Metric tool only | Both tools | SQL only | No tool call | Right, metric tool only | Right, both | Right, SQL only |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| metric plus a filter or dimension the layer already has | 2 | 0 | 2 | 0 | 0 | 0 of 0 | 2 of 2 | 0 of 0 |
| all | 2 | 0 | 2 | 0 | 0 | 0 of 0 | 2 of 2 | 0 of 0 |

### Going around the semantic layer

The bypass count: runs on a question that one metric query answers (the first two coverage classes), in which the agent ran SQL anyway. 2 of 2 such runs ran SQL (0 never called the metric tool, 2 called both); 2 of those were right. 0 were answered from metrics alone, 0 of them right.

## Tokens, time and cost per question

| Configuration | Input tokens | Output tokens | Cache-read share of input | Model calls | SQL queries | Seconds | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 26,537 | 3,294 | 0.0% | 10.00 | 8.00 | 42.3 | $0.0323 |
| flash_semantic | 23,866 | 2,791 | 0.0% | 5.50 | 2.00 | 29.7 | $0.0284 |

## Limits

Each question allows 8 SQL queries and, with the semantic layer, 8 metric calls; the agent is told both. The ceilings on model calls are Part 1's and Part 2's.

| Configuration | Model-call ceiling | Asked for a further SQL query | Asked for a further metric call | Hit the model-call ceiling | Timed out | Ended in an error | Repeated once after a failure | Declines that mention the query limit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 16 | 2 of 2 | n/a | 0 | 0 | 0 | 0 | 0 of 2 |
| flash_semantic | 24 | 0 of 2 | 0 | 0 | 0 | 0 | 0 | 0 of 0 |

Model names and prices were checked on 2026-10-09. Costs are estimates from token counts and list prices.
