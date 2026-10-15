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

"""What a Part 3 agent is told, in its two configurations.

available   The Part 1 instruction, word for word, with one paragraph added after
            the paragraph about the SQL tool, naming the contract's tools. As in
            Part 2, it neither tells the agent to prefer the contract nor to
            check it with SQL.
routed      The same instruction with the SQL tool's paragraph replaced by a
            paragraph about the contract's tools, and the table list taken out,
            because this agent has no tool that can read a table.

What each contract tool does is in its description, which the agent reads
from the server (``context_server/contract.py``), not from here. Committed
before any Part 3 agent ran. Changing a word here changes the experiment.
"""

from __future__ import annotations

from tessaway.agents import prompt
from tessaway.layers import MAX_LAYER_CALLS

# The contract's operations, in the order the paragraph names them.
OPERATIONS = ("lookup_definition", "compute_metric", "check_rule", "resolve_entity")

AVAILABLE = "available"
ROUTED = "routed"
CONFIGURATIONS = (AVAILABLE, ROUTED)

_NAMES = ", ".join(OPERATIONS[:-1]) + f" and {OPERATIONS[-1]}"

_CONTRACT = (
    f"The server serves the company's business definitions as a contract: look up a"
    f" definition, compute a named metric, check a rule, or resolve an entity. Every response"
    f" carries the contract version and a response ID. You can call each of these tools at most"
    f" {MAX_LAYER_CALLS} times for a question."
)

AVAILABLE_PARAGRAPH = f"You also have the tools of Tessaway's context server: {_NAMES}. {_CONTRACT}"
ROUTED_PARAGRAPH = f"Use the tools of Tessaway's context server: {_NAMES}. {_CONTRACT}"

# The Part 1 paragraphs this module works around.
_SQL_PARAGRAPH_START = f"Use the {prompt.TOOL_NAME} tool to query the warehouse."
_TABLES_START = "These are the tables in the warehouse."
_REPLY_START = "When you are done, reply"


def _paragraphs() -> list[str]:
    parts = prompt.INSTRUCTION.split("\n\n")
    if sum(1 for p in parts if p.startswith(_SQL_PARAGRAPH_START)) != 1:
        raise ValueError("the Part 1 instruction no longer has one paragraph about the SQL tool")
    return parts


def build_instruction(configuration: str) -> str:
    """Return the instruction for ``available`` or ``routed``."""
    parts = _paragraphs()
    sql = next(i for i, p in enumerate(parts) if p.startswith(_SQL_PARAGRAPH_START))
    if configuration == AVAILABLE:
        return "\n\n".join([*parts[: sql + 1], AVAILABLE_PARAGRAPH, *parts[sql + 1 :]])
    if configuration == ROUTED:
        tables = next(i for i, p in enumerate(parts) if p.startswith(_TABLES_START))
        reply = next(i for i, p in enumerate(parts) if p.startswith(_REPLY_START))
        kept = [*parts[:sql], ROUTED_PARAGRAPH, *parts[sql + 1 : tables], *parts[reply:]]
        return "\n\n".join(kept)
    raise ValueError(f"unknown configuration {configuration!r}")
