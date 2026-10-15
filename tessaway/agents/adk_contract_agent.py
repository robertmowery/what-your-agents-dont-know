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

"""The Part 3 agent: the Part 2 agent, reading the layers from the served contract.

Google ADK, the same model, retry settings and SQL tool as Parts 1 and 2. The
layer tools are gone; in their place is ADK's MCP toolset pointed at the
deployed context server, under the configuration's own service account. The
agent has no context code of its own: the four tools, their descriptions and
their arguments all come from the server.

    available   the contract and the SQL tool
    routed      the contract only

Every tool call is recorded in order with what came back, so the run script
can match the final answer to the values each tool returned. Each contract
call is held to the same allowance as a Part 2 layer tool.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.runners import InMemoryRunner
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from tessaway import config
from tessaway.agents import adk_agent, adk_layer_agent, contract_prompt, prompt
from tessaway.layers import LAYER_LIMIT_MESSAGE, MAX_LAYER_CALLS, ToolLog
from tessaway.warehouse import query

RUN_HEADER = "X-Tessaway-Run"


@dataclass
class ContractAgentRun(adk_layer_agent.LayerAgentRun):
    """What one Part 3 run did: the Part 2 record, plus the run's ID and caller."""

    run_id: str = ""
    configuration: str = ""
    tools_offered: list[str] = field(default_factory=list)


def max_model_calls() -> int:
    """The model-call ceiling: Part 1's 16 plus each contract tool's allowance.

    The same rule as Part 2, which added each layer tool's allowance, so an
    agent inside every limit it was told about always has calls left to answer.
    The same ceiling holds in both configurations.
    """
    return prompt.MAX_MODEL_CALLS + MAX_LAYER_CALLS * len(contract_prompt.OPERATIONS)


def parse_contract_reply(response: Any) -> dict[str, Any]:
    """Read the contract envelope out of what ADK's MCP tool returned."""
    if not isinstance(response, dict):
        return {"error": f"unexpected tool response: {str(response)[:300]}"}
    if "content" not in response:
        return {"error": str(response.get("error", response))[:500]}
    texts = [c.get("text", "") for c in response.get("content") or [] if isinstance(c, dict)]
    try:
        envelope = json.loads("".join(texts))
    except json.JSONDecodeError:
        return {"error": ("".join(texts) or "empty response")[:500]}
    if not isinstance(envelope, dict):
        return {"error": "the response is not a contract envelope"}
    return envelope


def build(
    model: str,
    configuration: str,
    log: query.QueryLog,
    tools: ToolLog,
    toolset: McpToolset,
    instruction: str | None = None,
) -> Agent:
    """Return a fresh agent for one configuration, recording every tool call.

    ``instruction`` replaces the configuration's Part 3 instruction (Part 4 adds
    the citation paragraph, ``tessaway/agents/provenance_prompt.py``).
    """
    pending: dict[str, dict[str, Any]] = {}

    async def run_sql(sql: str) -> dict[str, Any]:
        entry = tools.begin(prompt.TOOL_NAME, {"sql": sql}, limit=None)
        result = await asyncio.to_thread(query.run_readonly, sql, log)
        if result.get("error") == query.LIMIT_MESSAGE:
            entry["refused"] = True
        if "error" in result:
            entry["error"] = str(result["error"])[:500]
        else:
            entry["row_count"] = result["row_count"]
            entry["result"] = {"columns": result["columns"], "rows": result["rows"]}
        return result

    run_sql.__doc__ = prompt.TOOL_DESCRIPTION

    def before(tool: BaseTool, args: dict[str, Any], context: ToolContext) -> dict[str, Any] | None:
        if tool.name not in contract_prompt.OPERATIONS:
            return None
        entry = tools.begin(tool.name, dict(args), limit=MAX_LAYER_CALLS)
        if entry.get("refused"):
            return {"error": LAYER_LIMIT_MESSAGE}
        pending[context.function_call_id or str(entry["seq"])] = entry
        return None

    def after(
        tool: BaseTool, args: dict[str, Any], context: ToolContext, response: dict[str, Any]
    ) -> dict[str, Any] | None:
        if tool.name not in contract_prompt.OPERATIONS:
            return None
        entry = pending.pop(context.function_call_id or "", None)
        if entry is None:
            return None
        envelope = parse_contract_reply(response)
        if "result" not in envelope:
            entry["error"] = str(envelope.get("error", "no result"))[:500]
            return None
        entry["response_id"] = envelope.get("response_id", "")
        entry["contract_version"] = envelope.get("contract_version", "")
        if "definitions" in envelope:
            entry["definitions"] = envelope["definitions"]
        entry["result"] = envelope["result"]
        if isinstance(envelope["result"], dict) and "error" in envelope["result"]:
            entry["error"] = str(envelope["result"]["error"])[:500]
        return None

    chosen: list[Any] = [toolset]
    if configuration == contract_prompt.AVAILABLE:
        chosen.insert(0, run_sql)
    return Agent(
        name="analyst",
        model=model,
        instruction=instruction or contract_prompt.build_instruction(configuration),
        tools=chosen,
        generate_content_config=adk_agent.RETRY,
        before_tool_callback=before,
        after_tool_callback=after,
    )


def toolset_for(endpoint: str, token: str, run_id: str) -> McpToolset:
    """Return ADK's MCP toolset for the contract, signed as one agent, for one run."""
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=endpoint,
            headers={"Authorization": f"Bearer {token}", RUN_HEADER: run_id},
            timeout=30.0,
            sse_read_timeout=300.0,
        ),
        tool_filter=list(contract_prompt.OPERATIONS),
    )


async def ask(
    model: str,
    question: str,
    configuration: str,
    endpoint: str,
    token: str,
    instruction: str | None = None,
) -> ContractAgentRun:
    """Ask one question in a fresh session and record what happened."""
    config.project()
    run_id = str(uuid.uuid4())
    log = query.QueryLog()
    tools = ToolLog()
    run = ContractAgentRun(run_id=run_id, configuration=configuration)
    toolset = toolset_for(endpoint, token, run_id)
    agent = build(model, configuration, log, tools, toolset, instruction)
    runner = InMemoryRunner(agent=agent, app_name="tessaway_part3")
    session = await runner.session_service.create_session(
        app_name=runner.app_name, user_id=adk_agent.USER_ID
    )
    started = time.perf_counter()

    async def consume() -> None:
        async for event in runner.run_async(
            user_id=adk_agent.USER_ID,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=question)]),
            run_config=RunConfig(max_llm_calls=max_model_calls()),
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
        offered = await toolset.get_tools()
        run.tools_offered = sorted(
            ([prompt.TOOL_NAME] if configuration == contract_prompt.AVAILABLE else [])
            + [tool.name for tool in offered]
        )
        await asyncio.wait_for(consume(), prompt.RUN_TIMEOUT_S)
    except TimeoutError:
        run.timed_out = True
    except Exception as exc:  # noqa: BLE001 - a failed run is a finding, so record it
        run.error = f"{type(exc).__name__}: {exc}"[:600]
    finally:
        # Closing a finished session must not fail the run.
        with contextlib.suppress(Exception):
            await toolset.close()
    run.seconds = time.perf_counter() - started
    run.queries = log.queries
    run.queries_refused_over_limit = log.refused_over_limit
    run.bytes_billed = log.bytes_billed
    run.tool_calls = tools.calls
    run.layer_calls_refused = tools.refused_over_limit
    return run
