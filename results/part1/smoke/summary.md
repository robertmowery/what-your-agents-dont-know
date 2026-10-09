# Part 1 results

Written by `run_part1.py`. Tessaway Freight is a fictional company and the data is synthetic.

Each reply is scored in code into one of four bins. Shares are of all runs.

| Configuration | Model | Questions | Runs | Complete | Right | Confidently wrong | Declined | No answer | Est. cost | Cost per question |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| adk_gemini_flash | `gemini-3.8-flash` | 2 | 2 of 2 | yes | 50.0% | 50.0% | 0.0% | 0.0% | $0.07 | $0.0342 |
| adk_gemini_pro | `gemini-3.1-pro-preview` | 2 | 2 of 2 | yes | 50.0% | 50.0% | 0.0% | 0.0% | $0.11 | $0.0557 |

## Confidently wrong, by question group

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| adk_gemini_flash | 0.0% | 100.0% | n/a | n/a |
| adk_gemini_pro | 0.0% | 100.0% | n/a | n/a |

## Right, by question group

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| adk_gemini_flash | 100.0% | 0.0% | n/a | n/a |
| adk_gemini_pro | 100.0% | 0.0% | n/a | n/a |

## By question: right / confidently wrong / declined / no answer

| Question | Group | adk_gemini_flash | adk_gemini_pro |
| --- | --- | --- | --- |
| L1 | lookup | 1 / 0 / 0 / 0 | 1 / 0 / 0 / 0 |
| M1 | metric | 0 / 1 / 0 / 0 | 0 / 1 / 0 / 0 |

## Wrong answers that said they were assuming something

- adk_gemini_flash: 0 of 1 confidently wrong answers used a word such as "assume", "interpret" or "definition" somewhere in the reply.
- adk_gemini_pro: 0 of 1 confidently wrong answers used a word such as "assume", "interpret" or "definition" somewhere in the reply.

## Not run

- claude_sonnet: no runs saved
- claude_opus: no runs saved

Model names and prices were checked on 2026-10-09. Costs are estimates from token counts and list prices.
