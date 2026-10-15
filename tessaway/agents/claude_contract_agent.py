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

"""The Part 3 demonstration: the Claude Agent SDK reading the same contract.

Unscored. It shows that a second vendor's runtime can call the same endpoint
with no context code of its own. It runs the **available** configuration: the
Part 1 SQL tool, served in-process exactly as in Part 1, and the deployed
contract as a remote MCP server over HTTP, under its own service account. The
instruction is the available instruction (``contract_prompt``).

Claude is reached through Anthropic's API, with the key read at run time by
``tessaway.credentials`` (never stored, never printed).
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    tool,
)
from claude_agent_sdk import query as sdk_query

from tessaway import config, credentials
from tessaway.agents import adk_contract_agent, claude_agent, contract_prompt, prompt
from tessaway.warehouse import query

CONTRACT_SERVER = "contract"
WAREHOUSE_SERVER = claude_agent.SERVER_NAME


@dataclass
class ClaudeContractRun(prompt.AgentRun):
    """What one demonstration run did."""

    run_id: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    sdk_cost_usd: float | None = None


def options(
    model: str, log: query.QueryLog, workdir: str, endpoint: str, headers: dict[str, str]
) -> ClaudeAgentOptions:
    """Return SDK options: the SQL tool in-process and the contract over HTTP."""

    @tool(prompt.TOOL_NAME, prompt.TOOL_DESCRIPTION, {"sql": str})
    async def run_sql(args: dict[str, Any]) -> dict[str, Any]:
        result = await asyncio.to_thread(query.run_readonly, args["sql"], log)
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    warehouse = create_sdk_mcp_server(name=WAREHOUSE_SERVER, version="1.0.0", tools=[run_sql])
    allowed = [claude_agent.TOOL_FULL_NAME] + [
        f"mcp__{CONTRACT_SERVER}__{name}" for name in contract_prompt.OPERATIONS
    ]
    return ClaudeAgentOptions(
        model=model,
        system_prompt=contract_prompt.build_instruction(contract_prompt.AVAILABLE),
        tools=[],
        mcp_servers={
            WAREHOUSE_SERVER: warehouse,
            CONTRACT_SERVER: {"type": "http", "url": endpoint, "headers": headers},
        },
        strict_mcp_config=True,
        allowed_tools=allowed,
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=adk_contract_agent.max_model_calls(),
        cwd=workdir,
        env=claude_agent.sdk_env(),
    )


def _short(name: str) -> str:
    return name.rsplit("__", 1)[-1]


async def ask(model: str, question: str, endpoint: str, token: str) -> ClaudeContractRun:
    """Ask one question and record which tools were called and what it cost."""
    log = query.QueryLog()
    run = ClaudeContractRun(run_id=str(uuid.uuid4()))
    headers = {"Authorization": f"Bearer {token}", adk_contract_agent.RUN_HEADER: run.run_id}
    pending: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()

    async def consume(workdir: str) -> None:
        async for message in sdk_query(
            prompt=question, options=options(model, log, workdir, endpoint, headers)
        ):
            if isinstance(message, AssistantMessage):
                run.model_reported = message.model or run.model_reported
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        entry = {
                            "seq": len(run.tool_calls) + 1,
                            "tool": _short(block.name),
                            "server": block.name.split("__")[1] if "__" in block.name else "",
                        }
                        run.tool_calls.append(entry)
                        pending[block.id] = entry
                text = "".join(b.text for b in message.content if isinstance(b, TextBlock))
                if text.strip():
                    run.final_text = text
            elif isinstance(message, UserMessage) and isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock) and block.tool_use_id in pending:
                        entry = pending.pop(block.tool_use_id)
                        entry["is_error"] = bool(block.is_error)
                        text = (
                            block.content
                            if isinstance(block.content, str)
                            else "".join(
                                str(part.get("text", ""))
                                for part in (block.content or [])
                                if isinstance(part, dict)
                            )
                        )
                        if entry["tool"] in contract_prompt.OPERATIONS:
                            try:
                                reply = json.loads(text)
                                entry["response_id"] = reply.get("response_id", "")
                                entry["contract_version"] = reply.get("contract_version", "")
                            except (json.JSONDecodeError, AttributeError):
                                entry["error"] = text[:300]
            elif isinstance(message, ResultMessage):
                usage = message.usage or {}
                run.model_calls = message.num_turns
                run.input_tokens = int(usage.get("input_tokens") or 0)
                run.cache_read_tokens = int(usage.get("cache_read_input_tokens") or 0)
                run.cache_write_tokens = int(usage.get("cache_creation_input_tokens") or 0)
                run.output_tokens = int(usage.get("output_tokens") or 0)
                run.sdk_cost_usd = getattr(message, "total_cost_usd", None)
                if message.is_error:
                    detail = "; ".join(message.errors or []) or message.result or message.subtype
                    run.error = f"{message.subtype}: {detail}"[:600]

    with tempfile.TemporaryDirectory(prefix="tessaway_claude_") as workdir:
        try:
            await asyncio.wait_for(consume(workdir), prompt.RUN_TIMEOUT_S)
        except TimeoutError:
            run.timed_out = True
        except Exception as exc:  # noqa: BLE001 - a failed run is a finding, so record it
            run.error = f"{type(exc).__name__}: {exc}"[:600]
    if run.error and config.CLAUDE_ROUTE != "vertex":
        run.error = credentials.redact(run.error, credentials.anthropic_api_key())
        run.error = run.error.replace(token, "[TOKEN]")
    run.seconds = time.perf_counter() - started
    run.queries = log.queries
    run.queries_refused_over_limit = log.refused_over_limit
    run.bytes_billed = log.bytes_billed
    return run
