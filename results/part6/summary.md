# Part 6 results

Written by `analysis/part6_article_numbers.py` from the run records of Parts 1 to 5. Tessaway Freight is a fictional company and the data is synthetic. No model was called for this part.

Costs are estimates: tokens at list prices pinned on 2026-10-09 (checked again on 2026-10-27, unchanged), plus BigQuery bytes billed at $6.25 per TiB. The invoice is the authority. Every one of the 1266 records was priced again from its tokens and matches what it recorded (largest difference $0.0000005).

A scored record is the final record for each question and repeat; a failed run that was run again is counted in the all-in total, not in the unit.

## Cost per correct answer, by configuration

| Configuration | Part | Questions | Runs | Right | Confidently wrong | Declined | No answer | Cost per run | Cost per correct answer | From Jan 1, 2027 | Input tokens per run | Model calls per run | Input tokens per call | Cached share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Raw warehouse | 1 | part1 | 240 | 43.8% | 8.3% | 47.9% | 0.0% | 3.37¢ | 7.70¢ | 15.30¢ | 25,919 | 8.21 | 3,158 | 7.3% |
| Raw warehouse, bigger model | 1 | part1 | 240 | 55.8% | 22.5% | 21.7% | 0.0% | 7.19¢ | 12.87¢ | n/a | 20,159 | 7.70 | 2,618 | 0.4% |
| Semantic layer | 2 | part1 | 72 | 100.0% | 0.0% | 0.0% | 0.0% | 2.33¢ | 2.33¢ | 4.61¢ | 19,376 | 4.81 | 4,032 | 3.0% |
| Ontology | 2 | part1 | 72 | 50.0% | 5.6% | 44.4% | 0.0% | 4.92¢ | 9.83¢ | 19.57¢ | 61,862 | 13.40 | 4,616 | 31.2% |
| Knowledge graph | 2 | part1 | 72 | 45.8% | 5.6% | 48.6% | 0.0% | 5.33¢ | 11.63¢ | 23.19¢ | 58,589 | 12.46 | 4,703 | 25.9% |
| All three layers | 2 | part1 | 72 | 100.0% | 0.0% | 0.0% | 0.0% | 2.97¢ | 2.97¢ | 5.91¢ | 33,543 | 6.54 | 5,128 | 16.0% |
| Contract and SQL | 3 | part1 | 72 | 100.0% | 0.0% | 0.0% | 0.0% | 3.65¢ | 3.65¢ | 7.27¢ | 45,595 | 7.81 | 5,841 | 24.3% |
| Contract only | 3 | part1 | 72 | 80.6% | 0.0% | 19.4% | 0.0% | 3.21¢ | 3.99¢ | 7.98¢ | 37,624 | 7.11 | 5,291 | 24.3% |
| Contract and SQL, cited | 4 | part1 | 72 | 100.0% | 0.0% | 0.0% | 0.0% | 3.79¢ | 3.79¢ | 7.55¢ | 44,742 | 7.53 | 5,944 | 25.4% |
| Part 4's setup, drifted data | 5 | part1 | 72 | 83.3% | 16.7% | 0.0% | 0.0% | 3.95¢ | 4.74¢ | 9.45¢ | 49,491 | 7.92 | 6,251 | 29.4% |
| Part 4's setup, after the fix | 5 | part1 | 24 | 100.0% | 0.0% | 0.0% | 0.0% | 3.77¢ | 3.77¢ | 7.52¢ | 43,470 | 7.12 | 6,101 | 27.0% |
| Raw warehouse (blind questions) | 2 | holdout | 36 | 13.9% | 13.9% | 72.2% | 0.0% | 4.33¢ | 31.19¢ | 62.01¢ | 32,308 | 10.00 | 3,231 | 7.2% |
| Semantic layer (blind questions) | 2 | holdout | 36 | 100.0% | 0.0% | 0.0% | 0.0% | 4.39¢ | 4.39¢ | 8.70¢ | 36,743 | 7.44 | 4,936 | 12.1% |
| Contract only (blind questions) | 3 | holdout | 36 | 86.1% | 5.6% | 8.3% | 0.0% | 4.24¢ | 4.93¢ | 9.86¢ | 39,942 | 7.19 | 5,552 | 20.9% |
| Contract only, cited (blind questions) | 4 | holdout | 36 | 83.3% | 8.3% | 8.3% | 0.0% | 5.75¢ | 6.91¢ | 13.81¢ | 49,792 | 7.50 | 6,639 | 31.2% |
| Claude Agent SDK demonstration | 3 | part1 | 24 | 0.0% | 0.0% | 0.0% | 0.0% | 0.97¢ | n/a | n/a | 0 | 3.21 | 0 | n/a |

## Cost per correct answer by question group (24 Part 1 questions)

| Configuration | Lookup | Metric | Entity | Rule |
| --- | --- | --- | --- | --- |
| Raw warehouse | 0.55¢ (60/60) | 31.03¢ (8/60) | 18.43¢ (13/60) | 11.99¢ (24/60) |
| Raw warehouse, bigger model | 0.89¢ (60/60) | 27.95¢ (21/60) | 17.63¢ (29/60) | 23.89¢ (24/60) |
| Semantic layer | 1.09¢ (18/18) | 3.33¢ (18/18) | 2.07¢ (18/18) | 2.82¢ (18/18) |
| Ontology | 1.02¢ (18/18) | 22.73¢ (5/18) | 18.49¢ (6/18) | 15.85¢ (7/18) |
| Knowledge graph | 0.71¢ (18/18) | 54.90¢ (2/18) | 17.28¢ (8/18) | 24.57¢ (5/18) |
| All three layers | 1.53¢ (18/18) | 3.53¢ (18/18) | 3.39¢ (18/18) | 3.43¢ (18/18) |
| Contract and SQL | 1.81¢ (18/18) | 4.84¢ (18/18) | 4.00¢ (18/18) | 3.94¢ (18/18) |
| Contract only | 23.21¢ (4/18) | 3.15¢ (18/18) | 2.29¢ (18/18) | 2.26¢ (18/18) |
| Contract and SQL, cited | 2.64¢ (18/18) | 4.10¢ (18/18) | 3.82¢ (18/18) | 4.59¢ (18/18) |
| Part 4's setup, drifted data | 2.67¢ (18/18) | 6.84¢ (12/18) | 5.27¢ (15/18) | 5.03¢ (15/18) |
| Part 4's setup, after the fix | 2.38¢ (6/6) | 4.68¢ (6/6) | 3.67¢ (6/6) | 4.35¢ (6/6) |

## Where the money went (all scored runs on the 24 questions)

Total $47.94: right $26.44, confidently wrong $6.99, declined $14.51, no answer $0.00.

## Totals

- Scored runs: $54.68
- Failed attempts that were run again: $0.59
- Smoke tests and discarded runs: $2.24
- Claude demonstration (not scored): $0.23
- All recorded: $57.75

## Budget check

Agent `executive-questions`, owner Director of Business Intelligence (a fictional role), $0.10 per task, $5.00 per day.

| Configuration | Runs over the per-task limit |
| --- | --- |
| Raw warehouse | 2 |
| Raw warehouse, bigger model | 62 |
| Semantic layer | 0 |
| Ontology | 0 |
| Knowledge graph | 1 |
| All three layers | 0 |
| Contract and SQL | 0 |
| Contract only | 2 |
| Contract and SQL, cited | 0 |
| Part 4's setup, drifted data | 1 |
| Part 4's setup, after the fix | 0 |
| Raw warehouse (blind questions) | 0 |
| Semantic layer (blind questions) | 1 |
| Contract only (blind questions) | 0 |
| Contract only, cited (blind questions) | 4 |
| Claude Agent SDK demonstration | 0 |

| Day (UTC) | Recorded spend | Over the daily limit |
| --- | --- | --- |
| 2026-10-09 | $40.03 | yes |
| 2026-10-13 | $11.67 | yes |
| 2026-10-15 | $3.80 | no |
