# Held-out set: what the semantic layer covers

Written by `analysis/holdout_coverage.py` before any agent ran on the held-out questions. It is a statement about the layer as it stood, not about the agent, and it is not adjusted after the runs.

For each question the script tried a short list of metric requests, least work first, through the same function the agent's `query_metrics` tool calls. The class is the first attempt that answers the question as asked and reproduced the saved gold answer within the question's own tolerance. The bare metric with the question's condition left out was also run as a control and is never the class. Every attempt, with the value it returned, is in `coverage.json`.

| Class | Questions | Which |
| --- | --- | --- |
| one metric query, as is | 0 | none |
| metric plus a filter or dimension the layer already has | 8 | H1, H2, H4, H5, H8, H9, H10, H12 |
| needs more than one metric query or arithmetic on results | 3 | H3, H6, H7 |
| not answerable from the layer | 1 | H11 |

| Question | Group | Class | Metric queries | How | Layer value | Gold |
| --- | --- | --- | --- | --- | --- | --- |
| H1 | metric | metric plus a filter or dimension the layer already has | 1 | the official rate, filtered to the own-fleet carrier type | 88.1657 | 88.17 |
| H2 | metric | metric plus a filter or dimension the layer already has | 1 | margin percentage, filtered to the outside-carrier type | 12.3596 | 12.36 |
| H3 | metric | needs more than one metric query or arithmetic on results | 1 | revenue grouped by the cross-border flag, then one row over the sum | 9.5804 | 9.58 |
| H4 | metric | metric plus a filter or dimension the layer already has | 1 | margin per load, filtered to the reefer equipment type | 408.7377 | 408.74 |
| H5 | entity | metric plus a filter or dimension the layer already has | 1 | delivered loads grouped by customer, sorted high to low, first row | Northgate Foods Group | Northgate Foods Group |
| H6 | entity | needs more than one metric query or arithmetic on results | 1 | revenue grouped by customer, sorted high to low, then count rows over the line | 17 | 17 |
| H7 | entity | needs more than one metric query or arithmetic on results | 2 | the top five customers by revenue, and total revenue, then a division | 30.9309 | 30.93 |
| H8 | entity | metric plus a filter or dimension the layer already has | 1 | loads booked, filtered to the customer by name | 216 | 216 |
| H9 | rule | metric plus a filter or dimension the layer already has | 1 | delivered loads, with a day-of-week expression on the metric's day as a filter | 1119 | 1119 |
| H10 | rule | metric plus a filter or dimension the layer already has | 1 | delivered loads, filtered to not on time and shipper-delayed | 139 | 139 |
| H11 | rule | not answerable from the layer | n/a | The layer knows whether a signed proof of delivery is on file (delivery__has_signed_pod). It has no metric and no dimension for whether any proof-of-delivery document is on file, so it cannot separate loads with unsigned paperwork from loads with none. | n/a | 27 |
| H12 | rule | metric plus a filter or dimension the layer already has | 1 | the portal rate, filtered to the customer by name | 89.3764 | 89.38 |

## Notes

- H4: Flaw in the question, found here and left as it is: margin per load for the whole company in the quarter is within the question's 1% tolerance of the reefer answer, so the scorer cannot tell an answer that ignores 'reefer' from a right one. The whole-company reading is not among the question's decoys.
- H4: the bare metric with the question's condition left out returns 409.1868, which the scorer accepts against a gold answer of 408.74.
- H9: The filter is a SQL day-of-week expression on the metric's own day, which MetricFlow accepts. The layer has no day-of-week dimension; an agent has to think of the expression or fetch the days and count.
- H11: The layer knows whether a signed proof of delivery is on file (delivery__has_signed_pod). It has no metric and no dimension for whether any proof-of-delivery document is on file, so it cannot separate loads with unsigned paperwork from loads with none.

No question is a bare metric over a period: each names a carrier type, an equipment type, a customer, a threshold, a ranking, a weekday or a cause. That is why the first class is empty.

For comparison: on the 24 Part 1 questions, one metric query reproduces the gold answer to all 18 questions outside the lookup group (`results/part2/semantic_gold_check.json`). Those checks allowed a filter, a grouping or a sort, so they span the first two classes here.

The attempts were written by hand by someone who could read the layer. An agent has to find the same route from the tool description alone. A question in the third class can still be answered with the SQL tool, and so can one in the fourth.
