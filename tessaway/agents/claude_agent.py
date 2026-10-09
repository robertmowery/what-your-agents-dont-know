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

"""Agent two: the Claude Agent SDK with a Claude model through Vertex AI.

The same task and the same tool surface as the ADK agent: the shared
instruction, and one tool that runs a read-only query. The SDK's built-in
tools (files, shell, web) are switched off, and no settings, memory or skills
are loaded from the machine, so the model has nothing but the warehouse tool.

Claude is reached through Vertex AI in the same Google Cloud project, with
Application Default Credentials. There is no API key.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
    tool,
)
from claude_agent_sdk import query as sdk_query

from tessaway import config
from tessaway.agents import prompt
from tessaway.warehouse import query

SERVER_NAME = "warehouse"
# The name the model sees for the tool. The SDK prefixes tools it serves
# in-process; the ADK agent sees the bare name.
TOOL_FULL_NAME = f"mcp__{SERVER_NAME}__{prompt.TOOL_NAME}"


def vertex_env() -> dict[str, str]:
    """Environment that points the SDK at Claude on Vertex AI in this project."""
    project = config.project()
    return {
        "CLAUDE_CODE_USE_VERTEX": "1",
        "ANTHROPIC_VERTEX_PROJECT_ID": project,
        "CLOUD_ML_REGION": config.CLAUDE_VERTEX_REGION,
        "GOOGLE_CLOUD_PROJECT": project,
        "GOOGLE_CLOUD_QUOTA_PROJECT": project,
        # Keep the run to model calls and the one tool: no telemetry, updates or
        # background requests.
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
    }


def options(model: str, log: query.QueryLog, workdir: str) -> ClaudeAgentOptions:
    """Return SDK options for one question, with queries recorded in ``log``."""

    @tool(prompt.TOOL_NAME, prompt.TOOL_DESCRIPTION, {"sql": str})
    async def run_sql(args: dict[str, Any]) -> dict[str, Any]:
        result = await asyncio.to_thread(query.run_readonly, args["sql"], log)
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    server = create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=[run_sql])
    return ClaudeAgentOptions(
        model=model,
        system_prompt=prompt.INSTRUCTION,
        tools=[],  # no built-in tools at all
        mcp_servers={SERVER_NAME: server},
        strict_mcp_config=True,
        allowed_tools=[TOOL_FULL_NAME],
        permission_mode="dontAsk",
        setting_sources=[],  # nothing loaded from user or project settings
        max_turns=prompt.MAX_MODEL_CALLS,
        cwd=workdir,
        env=vertex_env(),
    )


async def ask(model: str, question: str) -> prompt.AgentRun:
    """Ask one question in a fresh session and record what happened."""
    log = query.QueryLog()
    run = prompt.AgentRun()
    started = time.perf_counter()

    async def consume(workdir: str) -> None:
        async for message in sdk_query(prompt=question, options=options(model, log, workdir)):
            if isinstance(message, AssistantMessage):
                run.model_reported = message.model or run.model_reported
                text = "".join(b.text for b in message.content if isinstance(b, TextBlock))
                if text.strip():
                    run.final_text = text
                if message.error:
                    run.error = f"assistant error: {message.error}"
            elif isinstance(message, ResultMessage):
                usage = message.usage or {}
                run.model_calls = message.num_turns
                run.input_tokens = int(usage.get("input_tokens") or 0)
                run.cache_read_tokens = int(usage.get("cache_read_input_tokens") or 0)
                run.cache_write_tokens = int(usage.get("cache_creation_input_tokens") or 0)
                run.output_tokens = int(usage.get("output_tokens") or 0)
                if message.is_error:
                    detail = "; ".join(message.errors or []) or message.result or message.subtype
                    run.error = f"{message.subtype}: {detail}"[:600]

    # An empty working directory: the SDK has no file tools, and this makes
    # sure there is no project file for it to pick up either.
    with tempfile.TemporaryDirectory(prefix="tessaway_claude_") as workdir:
        try:
            await asyncio.wait_for(consume(workdir), prompt.RUN_TIMEOUT_S)
        except TimeoutError:
            run.timed_out = True
        except Exception as exc:  # noqa: BLE001 - a failed run is a finding, so record it
            run.error = f"{type(exc).__name__}: {exc}"[:600]
    run.seconds = time.perf_counter() - started
    run.queries = log.queries
    run.queries_refused_over_limit = log.refused_over_limit
    run.bytes_billed = log.bytes_billed
    return run


async def available(model: str) -> tuple[bool, str]:
    """Make one tiny call to see whether the model can be reached on Vertex AI.

    Returns:
        ``(True, "")`` when the model answers, otherwise ``(False, reason)``.
        Nothing here tries another route when the call is refused.
    """
    from anthropic import AsyncAnthropicVertex

    client = AsyncAnthropicVertex(
        project_id=config.project(), region=config.CLAUDE_VERTEX_REGION, max_retries=0
    )
    try:
        await client.messages.create(
            model=model, max_tokens=8, messages=[{"role": "user", "content": "Reply: ok"}]
        )
    except Exception as exc:  # noqa: BLE001 - any refusal means "not available", with its reason
        reason = f"{type(exc).__name__}: {exc}".replace(config.project(), "PROJECT")
        return False, reason[:300]
    return True, ""
