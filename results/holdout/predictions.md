# Held-out fairness test: what was predicted, written before any run

Written on 2026-10-09, after the coverage check (`coverage.json`, `coverage.md`) and before any agent was run on the held-out questions, the smoke test included. The git history shows the order. Nothing here is a result.

## Why this test exists

In Part 2 the semantic layer took the Flash agent from 43.8% right to 100% on the 24 Part 1 questions. The person who wrote the layer knew those questions, and one metric query reproduces the gold answer to each of the 18 hard ones. That result may say more about the fit between the layer and the questions than about semantic layers. The 12 held-out questions were written afterward by a writer who was not shown the layer (`data/HOLDOUT.md`).

This test may show that the layer does much less on questions it was not built for. If it does, that is the finding and it is reported as such.

## Predictions, one line each

- Baseline (the Part 1 agent, schema and SQL only): about a quarter right, 7 to 12 of 36 runs, with most of the rest declined. On the 18 Part 1 questions outside the lookup group the same agent was right in 25% of runs, and the held-out set has no lookups.
- Semantic layer (the Part 2 semantic configuration): about 25 of 36 right (roughly 70%), anywhere from 20 to 30. Well above the baseline and short of the 100% it scored on the Part 1 questions.

## Where the semantic configuration is expected to fall short

By coverage class, fixed in `coverage.json`:

- Metric plus a filter or dimension the layer already has (8 questions, 24 runs): mostly right, 19 to 23 of 24. H9 is the likeliest miss: the weekend filter needs a SQL day-of-week expression the tool description does not suggest.
- More than one metric query or arithmetic on results (3 questions, 9 runs): mixed, 4 to 7 of 9. The agent has to fetch rows and do a division, a count or a top-five sum itself, or fall back to SQL.
- Not answerable from the layer (H11, 3 runs): 0 or 1 of 3. The layer has a metric that sounds like the answer (`delivered_loads_not_billable`) and returns 197, which is one of the question's decoys. The expected failure is a confidently wrong 197.

## How the result will be read

Fixed now, so the reading cannot be chosen afterward. Each configuration runs each question three times: 36 runs, so one run is 2.8 points overall and 8.3 points within a group of four questions.

| Claim | Holds when |
| --- | --- |
| The layer helps on questions it was not built for | The semantic configuration's right share is more than two runs (5.6 points) above the held-out baseline's |
| The layer generalizes as well as Part 2 suggested | The semantic configuration is right in at least 34 of 36 runs |
| The layer does much less on unseen questions | The gain over the held-out baseline, in points, is less than half the 56.2-point gain on the 24 Part 1 questions |
| The layer's failures are the ones coverage predicts | Wrong and declined semantic runs fall mostly in the third and fourth coverage classes |
| The layer does no harm | The semantic configuration's confidently wrong share is not more than two runs above the baseline's |

A claim that fails its test is reported as not holding, with the numbers.

## The bypass count

Fixed before any run (`tool_use` in `run_holdout.py`): a run went around the semantic layer when one metric query answers the question (the first two coverage classes, 8 questions and 24 runs) and the agent ran at least one SQL query anyway.

## Known before any run

- No held-out question is a bare metric over a period. Each adds a condition. On the Part 1 set, 11 of the 18 gold checks were a bare metric and a period.
- H4 has a flaw, found by the coverage check and left in place as `data/HOLDOUT.md` requires: margin per load for the whole company in Q3 (409.19) is within the question's 1% tolerance of the reefer answer (408.74). An agent that ignores "reefer" is scored right. H4 results are reported with that caveat.
- The coverage attempts were written by someone who could read the layer. They show what the layer can express, not what the agent will find.
- Nothing under `semantic_layer/`, no tool description, no instruction text and no part of the scorer was changed for this test. The harness is Part 2's: Google ADK, `gemini-3.8-flash`, 8 SQL queries and 8 metric calls a question, a ceiling of 16 model calls for the baseline and 24 with the metric tool, and one repeat of a run that ends in an error or a timeout.
