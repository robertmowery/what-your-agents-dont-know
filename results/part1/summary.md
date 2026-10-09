# Part 1 results

Written by `run_part1.py`. Tessaway Freight is a fictional company and the data is synthetic.

Each reply is scored in code into one of four bins. Shares are of all runs.

| Configuration | Model | Questions | Runs | Complete | Right | Confidently wrong | Declined | No answer | Est. cost | Cost per question |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| adk_gemini_flash | `gemini-3.8-flash` | 24 | 240 of 240 | yes | 43.8% | 8.3% | 47.9% | 0.0% | $7.98 | $0.0332 |
| adk_gemini_pro | `gemini-3.1-pro-preview` | 24 | 240 of 240 | yes | 55.8% | 22.5% | 21.7% | 0.0% | $17.14 | $0.0714 |

## Confidently wrong, by question group

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| adk_gemini_flash | 0.0% | 10.0% | 10.0% | 13.3% |
| adk_gemini_pro | 0.0% | 21.7% | 38.3% | 30.0% |

## Right, by question group

| Configuration | lookup | metric | entity | rule |
| --- | --- | --- | --- | --- |
| adk_gemini_flash | 100.0% | 13.3% | 21.7% | 40.0% |
| adk_gemini_pro | 100.0% | 35.0% | 48.3% | 40.0% |

## By question: right / confidently wrong / declined / no answer

| Question | Group | adk_gemini_flash | adk_gemini_pro |
| --- | --- | --- | --- |
| E1 | entity | 4 / 0 / 6 / 0 | 8 / 1 / 1 / 0 |
| E2 | entity | 0 / 0 / 10 / 0 | 1 / 6 / 3 / 0 |
| E3 | entity | 0 / 1 / 9 / 0 | 6 / 2 / 2 / 0 |
| E4 | entity | 0 / 4 / 6 / 0 | 0 / 10 / 0 / 0 |
| E5 | entity | 1 / 1 / 8 / 0 | 4 / 4 / 2 / 0 |
| E6 | entity | 8 / 0 / 2 / 0 | 10 / 0 / 0 / 0 |
| L1 | lookup | 10 / 0 / 0 / 0 | 10 / 0 / 0 / 0 |
| L2 | lookup | 10 / 0 / 0 / 0 | 10 / 0 / 0 / 0 |
| L3 | lookup | 10 / 0 / 0 / 0 | 10 / 0 / 0 / 0 |
| L4 | lookup | 10 / 0 / 0 / 0 | 10 / 0 / 0 / 0 |
| L5 | lookup | 10 / 0 / 0 / 0 | 10 / 0 / 0 / 0 |
| L6 | lookup | 10 / 0 / 0 / 0 | 10 / 0 / 0 / 0 |
| M1 | metric | 0 / 5 / 5 / 0 | 0 / 8 / 2 / 0 |
| M2 | metric | 0 / 0 / 10 / 0 | 6 / 0 / 4 / 0 |
| M3 | metric | 0 / 0 / 10 / 0 | 0 / 0 / 10 / 0 |
| M4 | metric | 0 / 0 / 10 / 0 | 1 / 1 / 8 / 0 |
| M5 | metric | 4 / 1 / 5 / 0 | 6 / 4 / 0 / 0 |
| M6 | metric | 4 / 0 / 6 / 0 | 8 / 0 / 2 / 0 |
| R1 | rule | 0 / 7 / 3 / 0 | 0 / 9 / 1 / 0 |
| R2 | rule | 1 / 1 / 8 / 0 | 1 / 5 / 4 / 0 |
| R3 | rule | 0 / 0 / 10 / 0 | 0 / 2 / 8 / 0 |
| R4 | rule | 8 / 0 / 2 / 0 | 7 / 2 / 1 / 0 |
| R5 | rule | 10 / 0 / 0 / 0 | 8 / 0 / 2 / 0 |
| R6 | rule | 5 / 0 / 5 / 0 | 8 / 0 / 2 / 0 |

## Wrong answers that said they were assuming something

- adk_gemini_flash: 0 of 20 confidently wrong answers used a word such as "assume", "interpret" or "definition" somewhere in the reply.
- adk_gemini_pro: 1 of 54 confidently wrong answers used a word such as "assume", "interpret" or "definition" somewhere in the reply.

## The query limit

Each question allows a fixed number of queries, and the agent is told the number. These counts show how often that limit was reached.

- adk_gemini_flash: 174 of 240 runs asked for another query after using them all. 4 of 115 declines mention running out of queries.
- adk_gemini_pro: 164 of 240 runs asked for another query after using them all. 12 of 52 declines mention running out of queries.

## Not run

- claude_sonnet: claude-sonnet-5-5 could not be reached on Vertex AI: RateLimitError: Error code: 429 - {'error': {'code': 429, 'message': 'Quota exceeded for aiplatform.googleapis.com/global_online_prediction_requests_per_base_model with base model: anthropic-claude-sonnet. Please submit a quota increase request. https://cloud.google.com/vertex-ai/docs/generative-ai/
- claude_opus: claude-opus-5-5 could not be reached on Vertex AI: RateLimitError: Error code: 429 - {'error': {'code': 429, 'message': 'Quota exceeded for aiplatform.googleapis.com/global_online_prediction_requests_per_base_model with base model: anthropic-claude-opus. Please submit a quota increase request. https://cloud.google.com/vertex-ai/docs/generative-ai/qu

Model names and prices were checked on 2026-10-09. Costs are estimates from token counts and list prices.
