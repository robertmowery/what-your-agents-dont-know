# Held-out fairness test for Part 2

Written by `run_holdout.py`. Tessaway Freight is a fictional company and the data is synthetic.

Twelve questions written after the Part 2 layers were committed, by a writer who was not shown the layers (`data/HOLDOUT.md`). Two agents on `gemini-3.8-flash` with Google ADK: the Part 1 agent (schema and the SQL tool), and the same agent with the semantic layer's `query_metrics` tool. The layer, the tool description, the instruction and the scorer are Part 2's, unchanged. Each reply is scored into one of four bins. Shares are of all runs.

Each question ran three times: 36 runs a configuration. One run is 2.8 points of an overall share and 8.3 points within a question group. Small differences are not findings.

| Configuration | Tools beside `run_sql` | Runs | Complete | Right | Confidently wrong | Declined | No answer | Est. cost | Cost per question |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | none | 36 of 36 | yes | 13.9% | 13.9% | 72.2% | 0.0% | $1.54 | $0.0428 |
| flash_semantic | `query_metrics` | 36 of 36 | yes | 100.0% | 0.0% | 0.0% | 0.0% | $1.55 | $0.0431 |

Change from baseline to semantic layer, in percentage points: right +86.1, confidently wrong -13.9, declined -72.2.

## Beside the 24 Part 1 questions

| Question set | Baseline right | Semantic layer right | Change in points |
| --- | --- | --- | --- |
| 24 Part 1 questions (the layer's author knew them) | 43.8% | 100.0% | +56.2 |
| 12 held-out questions | 13.9% | 100.0% | +86.1 |

The 24 include six lookup questions that every configuration gets right; the held-out set has none. The Part 1 baseline ran each question ten times.

## By question group: right / confidently wrong / declined / no answer

| Configuration | metric | entity | rule |
| --- | --- | --- | --- |
| baseline | 0 / 0 / 12 / 0 (0.0% right) | 2 / 4 / 6 / 0 (16.7% right) | 3 / 1 / 8 / 0 (25.0% right) |
| flash_semantic | 12 / 0 / 0 / 0 (100.0% right) | 12 / 0 / 0 / 0 (100.0% right) | 12 / 0 / 0 / 0 (100.0% right) |

## By coverage class: right / confidently wrong / declined / no answer

The class says what the semantic layer could answer, and was fixed in `coverage.json` before any run (`coverage.md`).

| Coverage class | Questions | baseline | flash_semantic |
| --- | --- | --- | --- |
| one metric query, as is | none | n/a | n/a |
| metric plus a filter or dimension the layer already has | H1, H2, H4, H5, H8, H9, H10, H12 | 4 / 4 / 16 / 0 (16.7% right) | 24 / 0 / 0 / 0 (100.0% right) |
| needs more than one metric query or arithmetic on results | H3, H6, H7 | 0 / 1 / 8 / 0 (0.0% right) | 9 / 0 / 0 / 0 (100.0% right) |
| not answerable from the layer | H11 | 1 / 0 / 2 / 0 (33.3% right) | 3 / 0 / 0 / 0 (100.0% right) |

## By question

Counts are right / confidently wrong / declined / no answer. Answers are the final line of each run, in run order.

| Question | Group | Coverage class | Gold | baseline | baseline answers | flash_semantic | flash_semantic answers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | metric | metric_plus_filter | 88.17 | 0 / 0 / 3 / 0 | NEEDS_CLARIFICATION; NEEDS_CLARIFICATION; NEEDS_CLARIFICATION | 3 / 0 / 0 / 0 | 88.1656804733728; 88.1656804733728; 88.1656804733728 |
| H2 | metric | metric_plus_filter | 12.36 | 0 / 0 / 3 / 0 | NEEDS_CLARIFICATION; NEEDS_CLARIFICATION; NEEDS_CLARIFICATION | 3 / 0 / 0 / 0 | 12.359558455; 12.359558455; 12.359558455 |
| H3 | metric | several_or_arithmetic | 9.58 | 0 / 0 / 3 / 0 | NEEDS_CLARIFICATION; NEEDS_CLARIFICATION; NEEDS_CLARIFICATION | 3 / 0 / 0 / 0 | 9.58; 9.58; 9.58 |
| H4 | metric | metric_plus_filter | 408.74 | 0 / 0 / 3 / 0 | NEEDS_CLARIFICATION; NEEDS_CLARIFICATION; NEEDS_CLARIFICATION | 3 / 0 / 0 / 0 | 408.74; 408.74; 408.74 |
| H5 | entity | metric_plus_filter | Northgate Foods Group | 2 / 1 / 0 / 0 | Pellam Paper Corp; Northgate Foods Group; Northgate Foods Group | 3 / 0 / 0 / 0 | Northgate Foods Group; Northgate Foods Group; Northgate Foods Group |
| H6 | entity | several_or_arithmetic | 17 | 0 / 1 / 2 / 0 | 13; NEEDS_CLARIFICATION; NEEDS_CLARIFICATION | 3 / 0 / 0 / 0 | 17; 17; 17 |
| H7 | entity | several_or_arithmetic | 30.93 | 0 / 0 / 3 / 0 | NEEDS_CLARIFICATION; NEEDS_CLARIFICATION; NEEDS_CLARIFICATION | 3 / 0 / 0 / 0 | 30.93; 30.93; 30.93 |
| H8 | entity | metric_plus_filter | 216 | 0 / 2 / 1 / 0 | 225; NEEDS_CLARIFICATION; 225 | 3 / 0 / 0 / 0 | 216; 216; 216 |
| H9 | rule | metric_plus_filter | 1119 | 0 / 0 / 3 / 0 | NEEDS_CLARIFICATION; NEEDS_CLARIFICATION; NEEDS_CLARIFICATION | 3 / 0 / 0 / 0 | 1119; 1119; 1119 |
| H10 | rule | metric_plus_filter | 139 | 0 / 1 / 2 / 0 | NEEDS_CLARIFICATION; 40; NEEDS_CLARIFICATION | 3 / 0 / 0 / 0 | 139; 139; 139 |
| H11 | rule | not_answerable | 27 | 1 / 0 / 2 / 0 | 27; NEEDS_CLARIFICATION; NEEDS_CLARIFICATION | 3 / 0 / 0 / 0 | 27; 27; 27 |
| H12 | rule | metric_plus_filter | 89.38 | 2 / 0 / 1 / 0 | 89.53; 89.53; NEEDS_CLARIFICATION | 3 / 0 / 0 / 0 | 89.3764434180139; 89.38; 89.3764434180139 |

The questions:

- H1: What was our own fleet's on-time delivery rate in Q2 2026?
- H2: What was our margin percentage on loads hauled by outside carriers in the first half of 2026?
- H3: What share of our Q3 2026 revenue came from cross-border loads?
- H4: What was our average margin per load on reefer loads in Q3 2026?
- H5: Which customer did we deliver the most loads for in the first half of 2026?
- H6: How many customers each brought in more than $250,000 of revenue in Q3 2026?
- H7: What share of our Q3 2026 revenue came from our five largest customers?
- H8: How many loads did we book for Kestrel Packaging in the first half of 2026?
- H9: How many of our Q3 2026 deliveries arrived on a Saturday or Sunday?
- H10: How many late deliveries in Q3 2026 were the shipper's fault?
- H11: How many loads delivered in Q3 2026 have proof-of-delivery paperwork on file but still can't be billed?
- H12: What on-time rate did Northgate Foods see in the portal for its Q3 2026 deliveries?

## Tool calls, semantic-layer configuration

Mean calls per run: `run_sql` 3.78, `query_metrics` 2.58. 36 of 36 runs called the metric tool and 35 ran SQL. The first call was SQL in 12 runs. 0 metric calls came back with an error.

| Coverage class | Runs | Metric tool only | Both tools | SQL only | No tool call | Right, metric tool only | Right, both | Right, SQL only |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| metric plus a filter or dimension the layer already has | 24 | 1 | 23 | 0 | 0 | 1 of 1 | 23 of 23 | 0 of 0 |
| needs more than one metric query or arithmetic on results | 9 | 0 | 9 | 0 | 0 | 0 of 0 | 9 of 9 | 0 of 0 |
| not answerable from the layer | 3 | 0 | 3 | 0 | 0 | 0 of 0 | 3 of 3 | 0 of 0 |
| all | 36 | 1 | 35 | 0 | 0 | 1 of 1 | 35 of 35 | 0 of 0 |

### Going around the semantic layer

The bypass count: runs on a question that one metric query answers (the first two coverage classes), in which the agent ran SQL anyway. 23 of 24 such runs ran SQL (0 never called the metric tool, 23 called both); 23 of those were right. 1 were answered from metrics alone, 1 of them right.

## Tokens, time and cost per question

| Configuration | Input tokens | Output tokens | Cache-read share of input | Model calls | SQL queries | Seconds | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 32,308 | 5,370 | 7.2% | 10.00 | 8.00 | 82.9 | $0.0428 |
| flash_semantic | 36,743 | 4,937 | 12.1% | 7.44 | 3.78 | 60.9 | $0.0431 |

## Limits

Each question allows 8 SQL queries and, with the semantic layer, 8 metric calls; the agent is told both. The ceilings on model calls are Part 1's and Part 2's.

| Configuration | Model-call ceiling | Asked for a further SQL query | Asked for a further metric call | Hit the model-call ceiling | Timed out | Ended in an error | Repeated once after a failure | Declines that mention the query limit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 16 | 36 of 36 | n/a | 0 | 0 | 0 | 0 | 2 of 26 |
| flash_semantic | 24 | 3 of 36 | 0 | 0 | 0 | 0 | 0 | 0 of 0 |

Model names and prices were checked on 2026-10-09. Costs are estimates from token counts and list prices.
