# Discarded smoke runs

These runs were made while the harness was being finished. They are not results. They are kept because they cost money, and `spend.json` counts every run ever made.

| Folder | What was wrong or different |
| --- | --- |
| `attempt1` | The query tool had a bug and every query failed. |
| `attempt2` | Tool fixed. No query limit yet; the `on-time` question ran into the cap on model calls and gave no answer. |
| `attempt3` | Query limit of 12 added and stated in the instruction. Cost per question was too high for the spending cap. |
| `attempt4` | Query limit of 8, the final harness, on `gemini-3.5-flash`. The baseline Gemini model was then changed to `gemini-3.8-flash`, which is newer and half the price. |

The smoke test on the final harness and final models is in `results/part1/smoke`.
