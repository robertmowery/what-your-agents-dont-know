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

"""Part 3: what each configuration is told, and what the harness gives it."""

from __future__ import annotations

from typing import Any

from context_server import contract
from tessaway.agents import adk_contract_agent, contract_prompt, prompt


def test_available_is_the_part1_instruction_plus_one_paragraph() -> None:
    text = contract_prompt.build_instruction(contract_prompt.AVAILABLE)
    assert text.replace("\n\n" + contract_prompt.AVAILABLE_PARAGRAPH, "") == prompt.INSTRUCTION


def test_neither_instruction_tells_the_agent_which_route_to_prefer() -> None:
    for name in contract_prompt.CONFIGURATIONS:
        text = contract_prompt.build_instruction(name).lower()
        for word in ("prefer", "instead of", "check your", "verify", "always use", "only use"):
            assert word not in text, (name, word)


def test_routed_drops_the_sql_tool_and_the_tables_and_keeps_the_rest() -> None:
    text = contract_prompt.build_instruction(contract_prompt.ROUTED)
    assert prompt.TOOL_NAME not in text
    assert "These are the tables" not in text
    assert contract_prompt.ROUTED_PARAGRAPH in text
    first = prompt.INSTRUCTION.split("\n\n")[0]
    assert text.startswith(first)
    reply = prompt.INSTRUCTION[prompt.INSTRUCTION.index("When you are done, reply") :]
    assert text.endswith(reply)


def test_the_paragraph_names_the_operations_the_server_publishes() -> None:
    assert contract_prompt.OPERATIONS == contract.OPERATIONS
    for name in contract.OPERATIONS:
        assert name in contract_prompt.AVAILABLE_PARAGRAPH


def test_the_model_call_ceiling_leaves_calls_to_answer() -> None:
    from tessaway.layers import MAX_LAYER_CALLS

    used = prompt.MAX_MODEL_CALLS + MAX_LAYER_CALLS * len(contract.OPERATIONS)
    assert adk_contract_agent.max_model_calls() == used


def test_a_contract_reply_is_read_from_the_mcp_tool_response() -> None:
    reply: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": '{"contract_version": "1.0.0", "response_id": "r",'
                ' "result": {"rows": [[1]]}}',
            }
        ],
        "isError": False,
    }
    envelope = adk_contract_agent.parse_contract_reply(reply)
    assert envelope["response_id"] == "r"
    assert "error" in adk_contract_agent.parse_contract_reply({"error": "boom"})
    assert "error" in adk_contract_agent.parse_contract_reply({"content": [{"text": "not json"}]})
