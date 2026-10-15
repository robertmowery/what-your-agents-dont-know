# The held-out question set

Tessaway Freight is a fictional company and its data is synthetic.

`questions/holdout.yaml` holds 12 questions that were not part of Part 1. They exist to check that a context layer built with the 24 Part 1 questions in view also works on questions nobody had in view when the layer was built.

## When and by whom

The set was written on 2026-10-09, after the Part 2 context layers were committed. The git history shows the order.

The writer was not shown the layers. The writer could read only:

- `data/DEFINITIONS.md` and `data/TRAPS.md`
- `questions/part1.yaml`
- `tessaway/questions.py`, `tessaway/warehouse/schema.py`, `tessaway/warehouse/query.py` and `tessaway/config.py`
- `results/part1/gold_answers.json`
- the README through the end of its Part 1 section
- the warehouse itself, through read-only SQL

The writer did not open the semantic layer, the ontology, the graph, any module that builds or serves a layer, the Part 2 run script, any Part 2 result or analysis, any article draft or brief, or the Part 2 section of the README. The writer did see the names of some test files and of the `results/part2` directory in directory listings, and the heading of the README's Part 2 section. No model was called and no agent was run while the set was written.

## The rules the set was written to

- Twelve questions an executive at a freight broker would plainly ask: four `metric`, four `entity` and four `rule`, with the same meanings as in Part 1. No lookups.
- Every question can be answered from the warehouse using only definitions that are in `data/DEFINITIONS.md`. No new definition was written. A question that would have needed one was dropped before it went into the file.
- No question is a Part 1 question with only the period changed. The set uses other periods and other cuts: own fleet and outside carriers, equipment type, cross-border share, a named customer, a top five, a threshold, weekdays, and who caused a delay.
- The question text carries no hint about definitions.
- Each question has hand-written gold SQL that follows the Part 1 patterns for local time, real loads, parent customers, currency and billing; an answer type and a tolerance on the Part 1 conventions; the definitions it depends on; why; and at least one decoy, the most natural naive reading, with its SQL.
- Every gold query and every decoy was run on BigQuery, and the values are saved in `results/holdout/gold_answers.json`. A question was kept only if its gold answer differs from every decoy by more than the tolerance. No gold answer is null or zero, and none rests on fewer than 20 loads.

## What was changed while writing, before any agent ran

These changes were made by comparing gold SQL with decoy SQL. No agent had run.

- A question on how many outside carriers delivered loads in a month was dropped: every reading gave the same number.
- Two candidate questions on canceled loads were set aside at the design stage, without being run: from the row counts, the naive reading would have landed within the tolerance of the correct one.
- Two decoys were removed because they could not be told apart from another value: one on H8 returned the same number as another decoy, and one on H12 (portal on-time for only the sites with Northgate in the name) came out within the tolerance of the gold answer.

## After the first agent run

The set is not edited after any agent runs on it. No question is dropped, reworded or re-scored to fit results. If a question turns out to be flawed, it stays in the file and the flaw is reported beside the results.
