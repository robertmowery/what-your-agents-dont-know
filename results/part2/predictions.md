# Part 2: what was predicted, written before any run

Written on 2026-10-09, after the three layers, their tools and their tests were built and before any Part 2 agent was run (the git history shows the order). Nothing here is a result.

## What the approved brief predicts

From `workflow/briefs/approved/part-2.md`, "What I expect, written down before any run":

> The semantic layer should move the metric group, the ontology the rule group, and the graph the entity group. Lookups should stay where they are. These are predictions, not results, and the article reports where they were wrong.

The brief makes three more claims that the runs can contradict:

- The working subtitle: "Each one fixed a different kind of wrong answer."
- "Role in the series": this part "shows that no single layer closes all of it."
- "What I will not do": "If one layer does most of the work, or the combined run is no better than the best single layer, the article says so."

## How each prediction will be read against the runs

Fixed now, so the reading cannot be chosen afterward. The baseline is Part 1's `adk_gemini_flash` result at ten runs per question. Each Part 2 configuration runs each question three times: 18 runs per question group, so one run is 5.6 points within a group.

| Prediction | Holds when |
| --- | --- |
| The semantic layer moves the metric group | In `flash_semantic`, the metric group's right share is more than two runs' worth (11.1 points) above the baseline's, and metric is the group it raised most |
| The ontology moves the rule group | The same test for `flash_ontology` and the rule group |
| The graph moves the entity group | The same test for `flash_graph` and the entity group |
| Lookups stay where they are | In every configuration, at least 17 of 18 lookup runs are right (the baseline is 60 of 60) |
| Each layer fixes a different kind of wrong answer | The three single-layer configurations raise three different groups most |
| No single layer closes all of the gap | No single-layer configuration is right on every question outside the lookup group in every run |
| All three together beat the best single layer | `flash_all_three` has a higher overall right share than the best single layer by more than two runs (2.8 points overall), without a higher confidently wrong share |

A prediction that fails any part of its test is reported as not holding, with the numbers.

## Known before any run

These are facts about the build, not predictions, and they bear on how the results should be read:

- The semantic layer was checked against the Part 1 gold SQL (`results/part2/semantic_gold_check.json`): one metric query reproduces the correct answer to all 18 questions outside the lookup group, including the entity and rule questions. The customer roll-up, the load count and the signed-proof rule are in `data/DEFINITIONS.md`, so they are in the metrics. If the agent uses the metric tool well, the semantic layer alone could move all three groups, which would contradict the brief's one-layer-per-group picture. Whether the agent finds and trusts the right metric is what the runs measure.
- The ontology states every official definition but computes nothing. The agent still has to write the SQL, within the same limit of 8 queries.
- The knowledge graph holds accounts, carriers, tenders and loads and how they connect. It holds no dates and no amounts, so on its own it cannot answer a question about a period. It can only tell the agent which rows belong together.
- The layers, the tool descriptions and the added instruction paragraphs were written by the person who wrote the questions, from the definitions file. That is a limit of this experiment and is stated in the articles.

## The bypass count

Also fixed before any run (`applies_to` and `tool_use` in `run_part2.py`):

- A layer applies to a question when it holds something the question needs: the semantic layer when one metric query answers it (18 questions), the ontology when an official definition decides it (18 questions), the graph when one of those definitions is `customer` or `load` (13 questions).
- A run ignored a layer when the layer applied and the agent never called its tool.
- A run went around the semantic layer (the bypass count) when one metric query answers the question and the agent ran at least one SQL query anyway.
