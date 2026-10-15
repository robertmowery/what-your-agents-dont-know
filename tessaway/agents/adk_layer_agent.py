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

"""The Part 2 agent: Part 1's ADK agent with one extra tool per context layer.

The model, the instruction's Part 1 text, the schema, the SQL tool and its
limit of queries are the ones Part 1 used. What is added is in
``tessaway/agents/layer_prompt.py``. The agent may use a layer tool or ignore
it; every tool call is recorded in order so that can be counted afterward.

The layers are handed to the agent in-process. There is no server and no MCP
here; serving them is Part 3.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.runners import InMemoryRunner
from google.genai import types

from tessaway import config
from tessaway.agents import adk_agent, layer_prompt, prompt
from tessaway.layers import LAYER_LIMIT_MESSAGE, MAX_LAYER_CALLS, ToolLog, graph, ontology, semantic
from tessaway.warehouse import query


@dataclass
class LayerAgentRun(prompt.AgentRun):
    """What one Part 2 agent run did: the Part 1 record plus every tool call."""

    # Every tool call in order: {"seq", "tool", "arguments", and what came back}.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # Layer tool calls refused because that tool's allowance was used up.
    layer_calls_refused: dict[str, int] = field(default_factory=dict)
    # BigQuery bytes billed by metric queries, beside ``bytes_billed`` for the SQL tool.
    layer_bytes_billed: int = 0
    # Prompt tokens and cached tokens of each model call, in order.
    prompt_tokens_by_call: list[list[int]] = field(default_factory=list)


def _outcome(entry: dict[str, Any], result: dict[str, Any]) -> None:
    """Note on a tool-call record what the tool returned, without the rows."""
    if "error" in result:
        entry.setdefault("error", str(result["error"])[:500])
    elif "row_count" in result:
        entry.setdefault("row_count", result["row_count"])


def build(model: str, layers: tuple[str, ...], log: query.QueryLog, tools: ToolLog) -> Agent:
    """Return a fresh analyst agent with the SQL tool and one tool per layer."""

    async def run_sql(sql: str) -> dict[str, Any]:
        entry = tools.begin(prompt.TOOL_NAME, {"sql": sql}, limit=None)
        result = await asyncio.to_thread(query.run_readonly, sql, log)
        if result.get("error") == query.LIMIT_MESSAGE:
            entry["refused"] = True
        _outcome(entry, result)
        return result

    async def query_metrics(
        metrics: list[str],
        group_by: list[str] | None = None,
        where: list[str] | None = None,
        start_date: str = "",
        end_date: str = "",
        order_by: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        arguments = {
            "metrics": metrics,
            "group_by": group_by or [],
            "where": where or [],
            "start_date": start_date,
            "end_date": end_date,
            "order_by": order_by or [],
            "limit": limit,
        }
        entry = tools.begin(layer_prompt.SEMANTIC_TOOL, arguments, limit=MAX_LAYER_CALLS)
        if entry.get("refused"):
            return {"error": LAYER_LIMIT_MESSAGE}
        result = await asyncio.to_thread(
            semantic.run_metrics,
            list(metrics or []),
            group_by,
            where,
            start_date,
            end_date,
            order_by,
            limit,
            entry,
            tools,
        )
        _outcome(entry, result)
        return result

    async def lookup_ontology(term: str = "") -> dict[str, Any]:
        entry = tools.begin(layer_prompt.ONTOLOGY_TOOL, {"term": term}, limit=MAX_LAYER_CALLS)
        if entry.get("refused"):
            return {"error": LAYER_LIMIT_MESSAGE}
        result = ontology.lookup(term)
        entry["matches"] = [match["term"] for match in result["matches"]]
        return result

    async def query_graph(sparql: str) -> dict[str, Any]:
        entry = tools.begin(layer_prompt.GRAPH_TOOL, {"sparql": sparql}, limit=MAX_LAYER_CALLS)
        if entry.get("refused"):
            return {"error": LAYER_LIMIT_MESSAGE}
        result = await asyncio.to_thread(graph.run_sparql, sparql)
        _outcome(entry, result)
        return result

    # Each docstring is the tool description the model reads.
    run_sql.__doc__ = prompt.TOOL_DESCRIPTION
    layer_tools = {"semantic": query_metrics, "ontology": lookup_ontology, "graph": query_graph}
    for layer, tool in layer_tools.items():
        tool.__doc__ = layer_prompt.tool_description(layer)
    chosen: list[Any] = [run_sql]
    chosen += [layer_tools[layer] for layer in layer_prompt.LAYERS if layer in layers]
    return Agent(
        name="analyst",
        model=model,
        instruction=layer_prompt.build_instruction(layers),
        tools=chosen,
        generate_content_config=adk_agent.RETRY,
    )


def max_model_calls(layers: tuple[str, ...]) -> int:
    """Return the most model calls one question may use with these layer tools.

    Part 1 allows 16 model calls for a tool the agent may call 8 times, so an
    agent that uses every query still has calls left to answer. Each layer tool
    brings its own allowance of calls, and the ceiling rises by that much, so
    the same holds here: an agent that stays inside every limit it was told
    about is never cut off before it can answer. The model is not told this
    number in either part.
    """
    return prompt.MAX_MODEL_CALLS + MAX_LAYER_CALLS * len(layers)


def warm_up(layers: tuple[str, ...]) -> None:
    """Load what the layer tools need before the first question is timed."""
    if "semantic" in layers:
        semantic.worker()
    if "graph" in layers:
        graph.store()
    if "ontology" in layers:
        ontology.entries()


async def ask(model: str, question: str, layers: tuple[str, ...]) -> LayerAgentRun:
    """Ask one question in a fresh session and record what happened.

    The loop is the one in ``adk_agent.ask``, with the tool calls kept as well.
    """
    config.project()  # fail early, and pin the quota project, before any client is made
    log = query.QueryLog()
    tools = ToolLog()
    run = LayerAgentRun()
    runner = InMemoryRunner(agent=build(model, layers, log, tools), app_name="tessaway_part2")
    session = await runner.session_service.create_session(
        app_name=runner.app_name, user_id=adk_agent.USER_ID
    )
    started = time.perf_counter()

    async def consume() -> None:
        async for event in runner.run_async(
            user_id=adk_agent.USER_ID,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=question)]),
            run_config=RunConfig(max_llm_calls=max_model_calls(layers)),
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
                run.prompt_tokens_by_call.append([usage.prompt_token_count or 0, cached])
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
    run.tool_calls = tools.calls
    run.layer_calls_refused = tools.refused_over_limit
    run.layer_bytes_billed = tools.bytes_billed
    return run
