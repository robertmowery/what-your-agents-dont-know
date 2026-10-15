# Part 2 results

Written by `run_part2.py`. Tessaway Freight is a fictional company and the data is synthetic.

Each configuration is the Part 1 agent (Google ADK, `gemini-3.8-flash`) with the same SQL tool and one extra tool per context layer. Each reply is scored by the Part 1 scorer into one of four bins. Shares are of all runs.

The baseline row is Part 1's Flash result at ten runs per question and was not run again. The Part 2 rows ran each question three times, so their shares are rougher: one run is 1.4 points of an overall share and 5.6 points within a question group. Small differences are not findings.

| Configuration | Tools beside `run_sql` | Runs | Complete | Right | Confidently wrong | Declined | No answer | Est. cost | Cost per question |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | none | 240 of 240 | yes | 43.8% | 8.3% | 47.9% | 0.0% | $7.98 | $0.0332 |
| flash_semantic | `query_metrics` | 72 of 72 | yes | 100.0% | 0.0% | 0.0% | 0.0% | $1.64 | $0.0228 |
| flash_ontology | `lookup_ontology` | 72 of 72 | yes | 50.0% | 5.6% | 44.4% | 0.0% | $3.51 | $0.0487 |
| flash_graph | `query_graph` | 72 of 72 | yes | 45.8% | 5.6% | 48.6% | 0.0% | $3.81 | $0.0530 |
| flash_all_three | `query_metrics`, `lookup_ontology`, `query_graph` | 72 of 72 | yes | 100.0% | 0.0% | 0.0% | 0.0% | $2.12 | $0.0294 |

## Right, by question group

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| baseline | 100.0% (60 of 60) | 13.3% (8 of 60) | 21.7% (13 of 60) | 40.0% (24 of 60) |
| flash_semantic | 100.0% (18 of 18) | 100.0% (18 of 18) | 100.0% (18 of 18) | 100.0% (18 of 18) |
| flash_ontology | 100.0% (18 of 18) | 27.8% (5 of 18) | 33.3% (6 of 18) | 38.9% (7 of 18) |
| flash_graph | 100.0% (18 of 18) | 11.1% (2 of 18) | 44.4% (8 of 18) | 27.8% (5 of 18) |
| flash_all_three | 100.0% (18 of 18) | 100.0% (18 of 18) | 100.0% (18 of 18) | 100.0% (18 of 18) |

## Confidently wrong, by question group

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| baseline | 0.0% (0 of 60) | 10.0% (6 of 60) | 10.0% (6 of 60) | 13.3% (8 of 60) |
| flash_semantic | 0.0% (0 of 18) | 0.0% (0 of 18) | 0.0% (0 of 18) | 0.0% (0 of 18) |
| flash_ontology | 0.0% (0 of 18) | 0.0% (0 of 18) | 16.7% (3 of 18) | 5.6% (1 of 18) |
| flash_graph | 0.0% (0 of 18) | 5.6% (1 of 18) | 0.0% (0 of 18) | 16.7% (3 of 18) |
| flash_all_three | 0.0% (0 of 18) | 0.0% (0 of 18) | 0.0% (0 of 18) | 0.0% (0 of 18) |

## Declined, by question group

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| baseline | 0.0% (0 of 60) | 76.7% (46 of 60) | 68.3% (41 of 60) | 46.7% (28 of 60) |
| flash_semantic | 0.0% (0 of 18) | 0.0% (0 of 18) | 0.0% (0 of 18) | 0.0% (0 of 18) |
| flash_ontology | 0.0% (0 of 18) | 72.2% (13 of 18) | 50.0% (9 of 18) | 55.6% (10 of 18) |
| flash_graph | 0.0% (0 of 18) | 83.3% (15 of 18) | 55.6% (10 of 18) | 55.6% (10 of 18) |
| flash_all_three | 0.0% (0 of 18) | 0.0% (0 of 18) | 0.0% (0 of 18) | 0.0% (0 of 18) |

## Change against the baseline, in percentage points

Right / confidently wrong / declined. A positive first number is more right answers.

| Configuration | overall | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- | --- |
| flash_semantic | +56.2 / -8.3 / -47.9 | +0.0 / +0.0 / +0.0 | +86.7 / -10.0 / -76.7 | +78.3 / -10.0 / -68.3 | +60.0 / -13.3 / -46.7 |
| flash_ontology | +6.2 / -2.8 / -3.5 | +0.0 / +0.0 / +0.0 | +14.4 / -10.0 / -4.5 | +11.7 / +6.7 / -18.3 | -1.1 / -7.8 / +8.9 |
| flash_graph | +2.1 / -2.8 / +0.7 | +0.0 / +0.0 / +0.0 | -2.2 / -4.4 / +6.7 | +22.8 / -10.0 / -12.8 | -12.2 / +3.3 / +8.9 |
| flash_all_three | +56.2 / -8.3 / -47.9 | +0.0 / +0.0 / +0.0 | +86.7 / -10.0 / -76.7 | +78.3 / -10.0 / -68.3 | +60.0 / -13.3 / -46.7 |

## By question: right / confidently wrong / declined / no answer

| Question | Group | baseline | flash_semantic | flash_ontology | flash_graph | flash_all_three |
| --- | --- | --- | --- | --- | --- | --- |
| E1 | entity | 4 / 0 / 6 / 0 | 3 / 0 / 0 / 0 | 1 / 0 / 2 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 |
| E2 | entity | 0 / 0 / 10 / 0 | 3 / 0 / 0 / 0 | 0 / 3 / 0 / 0 | 2 / 0 / 1 / 0 | 3 / 0 / 0 / 0 |
| E3 | entity | 0 / 1 / 9 / 0 | 3 / 0 / 0 / 0 | 0 / 0 / 3 / 0 | 0 / 0 / 3 / 0 | 3 / 0 / 0 / 0 |
| E4 | entity | 0 / 4 / 6 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 1 / 0 / 2 / 0 | 3 / 0 / 0 / 0 |
| E5 | entity | 1 / 1 / 8 / 0 | 3 / 0 / 0 / 0 | 1 / 0 / 2 / 0 | 0 / 0 / 3 / 0 | 3 / 0 / 0 / 0 |
| E6 | entity | 8 / 0 / 2 / 0 | 3 / 0 / 0 / 0 | 1 / 0 / 2 / 0 | 2 / 0 / 1 / 0 | 3 / 0 / 0 / 0 |
| L1 | lookup | 10 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 |
| L2 | lookup | 10 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 |
| L3 | lookup | 10 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 |
| L4 | lookup | 10 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 |
| L5 | lookup | 10 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 |
| L6 | lookup | 10 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 |
| M1 | metric | 0 / 5 / 5 / 0 | 3 / 0 / 0 / 0 | 0 / 0 / 3 / 0 | 0 / 1 / 2 / 0 | 3 / 0 / 0 / 0 |
| M2 | metric | 0 / 0 / 10 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 0 / 0 / 3 / 0 | 3 / 0 / 0 / 0 |
| M3 | metric | 0 / 0 / 10 / 0 | 3 / 0 / 0 / 0 | 0 / 0 / 3 / 0 | 0 / 0 / 3 / 0 | 3 / 0 / 0 / 0 |
| M4 | metric | 0 / 0 / 10 / 0 | 3 / 0 / 0 / 0 | 1 / 0 / 2 / 0 | 0 / 0 / 3 / 0 | 3 / 0 / 0 / 0 |
| M5 | metric | 4 / 1 / 5 / 0 | 3 / 0 / 0 / 0 | 1 / 0 / 2 / 0 | 2 / 0 / 1 / 0 | 3 / 0 / 0 / 0 |
| M6 | metric | 4 / 0 / 6 / 0 | 3 / 0 / 0 / 0 | 0 / 0 / 3 / 0 | 0 / 0 / 3 / 0 | 3 / 0 / 0 / 0 |
| R1 | rule | 0 / 7 / 3 / 0 | 3 / 0 / 0 / 0 | 1 / 0 / 2 / 0 | 0 / 1 / 2 / 0 | 3 / 0 / 0 / 0 |
| R2 | rule | 1 / 1 / 8 / 0 | 3 / 0 / 0 / 0 | 0 / 1 / 2 / 0 | 0 / 1 / 2 / 0 | 3 / 0 / 0 / 0 |
| R3 | rule | 0 / 0 / 10 / 0 | 3 / 0 / 0 / 0 | 0 / 0 / 3 / 0 | 0 / 0 / 3 / 0 | 3 / 0 / 0 / 0 |
| R4 | rule | 8 / 0 / 2 / 0 | 3 / 0 / 0 / 0 | 0 / 0 / 3 / 0 | 2 / 1 / 0 / 0 | 3 / 0 / 0 / 0 |
| R5 | rule | 10 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 |
| R6 | rule | 5 / 0 / 5 / 0 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 0 / 0 / 3 / 0 | 3 / 0 / 0 / 0 |

## Tool calls

Mean calls per run, counting calls that were let through. The agent was free to use a layer tool or ignore it.

| Configuration | `run_sql` | `query_metrics` | `lookup_ontology` | `query_graph` | Runs with no layer call | Runs with no SQL | First call was SQL |
| --- | --- | --- | --- | --- | --- | --- | --- |
| flash_semantic | 2.49 (66 runs) | 1.32 (54 runs) | not given | not given | 18 of 72 | 6 of 72 | 25 of 72 |
| flash_ontology | 6.54 (72 runs) | not given | 5.07 (68 runs) | not given | 4 of 72 | 0 of 72 | 13 of 72 |
| flash_graph | 6.46 (72 runs) | not given | not given | 4.03 (58 runs) | 14 of 72 | 0 of 72 | 72 of 72 |
| flash_all_three | 2.72 (66 runs) | 1.19 (54 runs) | 1.61 (65 runs) | 0.04 (3 runs) | 7 of 72 | 6 of 72 | 15 of 72 |

### Where a layer applied, and whether the agent used it

A layer applies to a question when it holds something the question needs. The rule is `applies_to` in `run_part2.py`, fixed before any run: the semantic layer applies when one metric query answers the question; the ontology when an official definition decides it; the graph when one of those definitions is about customers or loads.

| Configuration | Layer | Questions | Runs | Used the layer | Ignored the layer |
| --- | --- | --- | --- | --- | --- |
| flash_semantic | semantic | 18 | 54 | 54 | 0 |
| flash_ontology | ontology | 18 | 54 | 54 | 0 |
| flash_graph | graph | 13 | 39 | 39 | 0 |
| flash_all_three | semantic | 18 | 54 | 54 | 0 |
| flash_all_three | ontology | 18 | 54 | 54 | 0 |
| flash_all_three | graph | 13 | 39 | 0 | 39 |

### Going around the semantic layer

The bypass count: runs on a question that one metric query answers, in which the agent ran SQL anyway.

| Configuration | Runs on such questions | Ran SQL | Never called the metric tool | Called both | Right when SQL was run | Answered from metrics alone | Right from metrics alone |
| --- | --- | --- | --- | --- | --- | --- | --- |
| flash_semantic | 54 | 48 | 0 | 48 | 48 of 48 | 6 | 6 of 6 |
| flash_all_three | 54 | 48 | 0 | 48 | 48 of 48 | 6 | 6 of 6 |

## Tokens, time and cost per question

| Configuration | Input tokens | Output tokens | Cache-read share of input | Model calls | SQL queries | Seconds | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 25,919 | 4,021 | 7.3% | 8.21 | 6.48 | 92.8 | $0.0332 |
| flash_semantic | 19,376 | 2,308 | 3.0% | 4.81 | 2.49 | 35.8 | $0.0228 |
| flash_ontology | 61,862 | 4,091 | 31.2% | 13.40 | 6.54 | 71.1 | $0.0487 |
| flash_graph | 58,589 | 5,141 | 25.9% | 12.46 | 6.46 | 86.6 | $0.0530 |
| flash_all_three | 33,543 | 2,096 | 16.1% | 6.54 | 2.72 | 38.5 | $0.0294 |

## Limits

Each question allows 8 SQL queries and 8 calls to each layer tool, and the agent is told both. A run is also stopped at a ceiling of model calls it is not told about: 16 in Part 1, and 16 plus 8 for each layer tool here, so an agent inside the limits it was told about always has calls left to answer.

| Configuration | Model-call ceiling | Asked for a further SQL query | Asked for a further layer call | Hit the model-call ceiling | Timed out | Declines that mention the query limit |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 16 | 174 of 240 | n/a | n/a | 0 | 4 of 115 |
| flash_semantic | 24 | 0 of 72 | 0 | 0 | 0 | 0 of 0 |
| flash_ontology | 24 | 51 of 72 | 8 | 0 | 0 | 23 of 32 |
| flash_graph | 24 | 51 of 72 | 19 | 0 | 0 | 1 of 35 |
| flash_all_three | 40 | 1 of 72 | 0 | 0 | 0 | 0 of 0 |

## Wrong answers that said they were assuming something

- baseline: 0 of 20 confidently wrong answers used a word such as "assume", "interpret" or "definition" somewhere in the reply.
- flash_semantic: 0 of 0 confidently wrong answers used a word such as "assume", "interpret" or "definition" somewhere in the reply.
- flash_ontology: 3 of 4 confidently wrong answers used a word such as "assume", "interpret" or "definition" somewhere in the reply.
- flash_graph: 0 of 4 confidently wrong answers used a word such as "assume", "interpret" or "definition" somewhere in the reply.
- flash_all_three: 0 of 0 confidently wrong answers used a word such as "assume", "interpret" or "definition" somewhere in the reply.

Model names and prices were checked on 2026-10-09. Costs are estimates from token counts and list prices.
