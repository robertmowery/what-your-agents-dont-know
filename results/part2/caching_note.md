# Prompt caching: what was checked before the Part 2 runs

Checked on 2026-10-09, before any Part 2 agent ran. Part 1 recorded that 7.3% of the Flash configuration's input tokens were read from a cache. The question was whether the instruction and schema repeated on every call could be cached without changing what the model sees.

Short answer: nothing was switched on. Implicit caching is already on, and the repeated prefix is too short for either kind of caching to act on it.

## How caching works for gemini-3.8-flash on Vertex AI today

Source: the Vertex AI "Context caching overview" page, read on 2026-10-09 (https://docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview).

- **Implicit caching** is on by default for every Google Cloud project and supports Gemini 3.8 Flash. A cache hit bills the cached input tokens at a 90% discount. There is no storage charge. Hits are best-effort; Google's advice is to put large common content at the start of the prompt and to send requests with the same prefix close together.
- The minimum for an implicit cache hit on Gemini 3.8 Flash is **6,144 tokens** of matching prefix.
- **Explicit caching** means creating a cache through the API and referring to it by name. It guarantees the discount, charges for storage by the hour, and needs at least **4,096 tokens** on Gemini 3 family models.
- In both cases the response reports the cached tokens in `cachedContentTokenCount`, which is what Part 1 recorded and Part 2 records.

## How ADK 2.11.0 exposes it

`google.adk.agents.context_cache_config.ContextCacheConfig`, set on an `App`, turns on explicit caching for the agents in the app. Its own documentation says caching "begins on the second turn of a session at the earliest" and needs the cacheable prefix to reach the model's minimum (4,096 tokens for Gemini 3), so "short or single-turn sessions are therefore never cached." This harness asks each question in a fresh session with one user turn, so that setting would never create a cache here.

## The repeated prefix, measured

Counted with the Vertex AI `countTokens` call (no generation, no charge): the system instruction, the tool declarations and a ten-word question.

| Configuration | Tokens before the first tool call |
| --- | --- |
| Part 1 baseline (SQL tool only) | 1,202 |
| Semantic layer | 3,016 |
| Ontology | 1,350 |
| Knowledge graph | 1,654 |
| All three | 3,616 |

Every one is below 4,096 and below 6,144. The prefix that every question shares cannot be cached by either mechanism, in Part 1 or in Part 2.

## Where Part 1's 7.3% came from

A run sends its whole conversation again on every model call, so the prefix of one call is the previous call in full. Once a run's conversation passes 6,144 tokens, later calls in the same run can hit the implicit cache. In Part 1's Flash runs, 72 of the 248 saved runs had a cache read; none was a lookup question, which finish in two short calls. The cache reads were within-run, not across questions.

## What was done

- No caching mechanism was turned on, and no model input was changed. Implicit caching stays on as the project default, exactly as in Part 1, so the two parts are measured the same way.
- Explicit caching was not used: the shared prefix is under the 4,096-token minimum in every configuration, ADK's setting cannot act on single-turn sessions, and using it for some configurations and not others would have made their costs incomparable.
- Padding the prompt to reach a minimum was not considered: it would change what the model sees.
- `run_part2.py` records prompt tokens and cached tokens for every model call (`prompt_tokens_by_call`), so the cache-read share is reported for each configuration beside the baseline's 7.3%.
