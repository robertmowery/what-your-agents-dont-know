# Copyright 2026 Robert H. Mowery III
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Agent one: Google ADK with a Gemini model through Vertex AI.

One agent, one tool. The agent gets the shared instruction and can do exactly
one thing to the warehouse: run a read-only query.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.runners import InMemoryRunner
from google.genai import types

from tessaway import config
from tessaway.agents import prompt
from tessaway.warehouse import query

# Retry transient quota errors (429) instead of failing the question.
RETRY = types.GenerateContentConfig(
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=6, initial_delay=2.0, max_delay=30.0),
    )
)

USER_ID = "u"


def build(model: str, log: query.QueryLog) -> Agent:
    """Return a fresh analyst agent whose queries are recorded in ``log``."""

    async def run_sql(sql: str) -> dict[str, Any]:
        return await asyncio.to_thread(query.run_readonly, sql, log)

    # The docstring is the tool description the model reads.
    run_sql.__doc__ = prompt.TOOL_DESCRIPTION
    return Agent(
        name="analyst",
        model=model,
        instruction=prompt.INSTRUCTION,
        tools=[run_sql],
        generate_content_config=RETRY,
    )


async def ask(model: str, question: str) -> prompt.AgentRun:
    """Ask one question in a fresh session and record what happened."""
    config.project()  # fail early, and pin the quota project, before any client is made
    log = query.QueryLog()
    run = prompt.AgentRun()
    runner = InMemoryRunner(agent=build(model, log), app_name="tessaway_part1")
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id=USER_ID)
    started = time.perf_counter()

    async def consume() -> None:
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=question)]),
            run_config=RunConfig(max_llm_calls=prompt.MAX_MODEL_CALLS),
        ):
            if getattr(event, "partial", False):
                continue
            usage = getattr(event, "usage_metadata", None)
            if usage is not None:
                cached = usage.cached_content_token_count or 0
                run.model_calls += 1
                run.input_tokens += (usage.prompt_token_count or 0) - cached
                run.cache_read_tokens += cached
                run.output_tokens += (usage.candidates_token_count or 0) + (
                    usage.thoughts_token_count or 0
                )
            version = getattr(event, "model_version", None)
            if version:
                run.model_reported = version
            if event.content and event.content.parts:
                text = "".join(
                    part.text or ""
                    for part in event.content.parts
                    if not getattr(part, "thought", False)
                )
                if text.strip():
                    run.final_text = text

    try:
        await asyncio.wait_for(consume(), prompt.RUN_TIMEOUT_S)
    except TimeoutError:
        run.timed_out = True
    except Exception as exc:  # noqa: BLE001 - a failed run is a finding, so record it
        run.error = f"{type(exc).__name__}: {exc}"[:600]
    run.seconds = time.perf_counter() - started
    run.queries = log.queries
    run.queries_refused_over_limit = log.refused_over_limit
    run.bytes_billed = log.bytes_billed
    return run
