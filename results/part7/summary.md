# Part 7 results

Written by `analysis/part7_article_numbers.py`. Tessaway Freight is a fictional company and the data is synthetic.

| Phase | Runs | Right | Confidently wrong | Declined | No answer | Mixed versions | Served a wrong version | Cost per correct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| canary | 72 | 70 | 2 | 0 | 0 | 2 | 0 | 4.32 cents |
| rollback | 72 | 72 | 0 | 0 | 0 | 0 | 0 | 4.05 cents |
| rollout | 72 | 72 | 0 | 0 | 0 | 0 | 0 | 4.51 cents |

## Canary: the version 2 run of each question

| Question | Outcome | Answer | Version 2 key | Version 1 key | Served | Cited | Agent SQL dated revenue by |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E1 | right | Northgate Foods Group | Northgate Foods Group | Northgate Foods Group | {'revenue': [1, 2], 'margin': []} | revenue@2 | no SQL |
| E2 | right | 36 | 36 | 36 | {'revenue': [], 'margin': []} |  | other |
| E3 | right | 1264316.46509 | 1264316.47 | 1299690.26 | {'revenue': [2], 'margin': [1]} | revenue@2 | delivery date |
| E4 | right | 1170 | 1170 | 1170 | {'revenue': [], 'margin': []} |  | other |
| E5 | right | 433 | 433 | 433 | {'revenue': [], 'margin': []} |  | other |
| E6 | right | Midvale Transport | Midvale Transport | Midvale Transport | {'revenue': [], 'margin': [1]} |  | other |
| L1 | right | 65 | 65 | 65 | {'revenue': [], 'margin': [1]} |  | other |
| L2 | right | 11 | 11 | 11 | {'revenue': [], 'margin': []} |  | other |
| L3 | right | Green Bay | Green Bay | Green Bay | {'revenue': [], 'margin': []} |  | other |
| L4 | right | BHRI | BHRI | BHRI | {'revenue': [], 'margin': [1]} |  | other |
| L5 | right | 638 | 638 | 638 | {'revenue': [2], 'margin': []} |  | other |
| L6 | right | 0.7318 | 0.7318 | 0.7318 | {'revenue': [], 'margin': []} |  | other |
| M1 | right | 87.4409820585458 | 87.44 | 87.44 | {'revenue': [], 'margin': []} |  | other |
| M2 | right | 10017891.861957 | 10017891.86 | 10294019.12 | {'revenue': [2], 'margin': []} | revenue@2 | delivery date |
| M3 | confidently_wrong (mixed) | 326.315468449 | 417.28 | 409.19 | {'revenue': [2], 'margin': [1]} | margin@1 | invoice date |
| M4 | confidently_wrong (mixed) | 10.853412633 | 13.48 | 13.24 | {'revenue': [1, 2], 'margin': [1]} | margin@1 | no SQL |
| M5 | right | 1097 | 1097 | 1097 | {'revenue': [], 'margin': []} |  | other |
| M6 | right | 393 | 393 | 393 | {'revenue': [], 'margin': [1]} |  | other |
| R1 | right | 133 | 133 | 133 | {'revenue': [], 'margin': []} |  | no SQL |
| R2 | right | 142 | 142 | 142 | {'revenue': [2], 'margin': []} |  | other |
| R3 | right | 956094.601957 | 956094.6 | 986208.77 | {'revenue': [1, 2], 'margin': []} | revenue@2 | delivery date |
| R4 | right | 30 | 30 | 30 | {'revenue': [], 'margin': []} |  | other |
| R5 | right | 91.52233363719235 | 91.52 | 91.52 | {'revenue': [], 'margin': []} |  | other |
| R6 | right | 3050 | 3050.0 | 3050.0 | {'revenue': [2], 'margin': [1]} | margin@1, revenue@2 | other |

Rollback: 303 seconds from the new revision's creation to it serving all traffic, everyone on version 1.

## Predictions

- P1: held (48 of 48 version 1 canary runs right)
- P2: held (M2: right, cites revenue@2; E3: right, cites revenue@2; R3: right, cites revenue@2)
- P3: held (M3: confidently_wrong, mixed; M4: confidently_wrong, mixed)
- P4: held (E1 right in 9 of 9)
- P5: held (18 of 18)
- P6: did not hold (0 runs routed to a version their routing did not say; 11 runs in which the agent asked for a version itself)
- P7: held (303 s from the change to the service serving it)
- P8: held (72 of 72 right; 0 served version 2)
- P9: held (72 of 72 right; M3 and M4 right in 6 of 6)
- P10: held (0 version 2 runs gave the version 1 figure)
- P11: held (canary 4.32 cents; rollback 4.05 cents; rollout 4.51 cents (Part 4 3.79))

## Series

| Part | Configuration | Runs | Right | Confidently wrong | Declined | Cost per correct |
| --- | --- | --- | --- | --- | --- | --- |
| Part 1 | Raw warehouse | 240 | 43.8% | 8.3% | 47.9% | 7.70 cents |
| Part 2 | Semantic layer | 72 | 100.0% | 0.0% | 0.0% | 2.33 cents |
| Part 3 | Context contract and SQL | 72 | 100.0% | 0.0% | 0.0% | 3.65 cents |
| Part 4 | Contract, cited answers | 72 | 100.0% | 0.0% | 0.0% | 3.79 cents |
| Part 5 | Billing's reload in place | 72 | 83.3% | 16.7% | 0.0% | 4.74 cents |
| Part 5 | After the fix | 24 | 100.0% | 0.0% | 0.0% | 3.77 cents |
| Part 7 | Revenue version 2 | 72 | 100.0% | 0.0% | 0.0% | 4.51 cents |

Part 7 spend (Gemini and BigQuery, estimated): $9.58.
