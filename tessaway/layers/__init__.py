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

"""The three context layers of Part 2, and the record of how an agent used them.

    semantic   named metrics in YAML, compiled to SQL by MetricFlow (semantic_layer/)
    ontology   classes in OWL and rules in SHACL (ontology/)
    graph      the actual accounts, loads and tenders in an Oxigraph store

Every layer is written from data/DEFINITIONS.md and from nothing else. Each is
handed to the agent as one extra tool beside the read-only SQL tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LAYERS = ("semantic", "ontology", "graph")

# How many times one agent run may call one layer tool for one question. It is
# the same number as the SQL tool's query limit, and the agent is told it.
MAX_LAYER_CALLS = 8

LAYER_LIMIT_MESSAGE = (
    f"Call limit reached: all {MAX_LAYER_CALLS} calls to this tool for this question are used."
)


@dataclass
class ToolLog:
    """Every tool call one agent run made, in order, kept for the results file."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    # Layer tool calls refused because the run had used that tool's allowance.
    refused_over_limit: dict[str, int] = field(default_factory=dict)
    # BigQuery bytes billed by metric queries. SQL tool queries are counted in
    # the query log, as in Part 1.
    bytes_billed: int = 0

    def count(self, tool: str) -> int:
        """Return how many calls to ``tool`` have been let through so far."""
        return sum(1 for call in self.calls if call["tool"] == tool and not call.get("refused"))

    def begin(self, tool: str, arguments: dict[str, Any], *, limit: int | None) -> dict[str, Any]:
        """Record a call and say whether it is over the tool's allowance.

        Returns the entry for the call. When the allowance is used up the entry
        has ``refused`` set and the caller returns the limit message instead of
        doing the work.
        """
        entry: dict[str, Any] = {"seq": len(self.calls) + 1, "tool": tool, "arguments": arguments}
        if limit is not None and self.count(tool) >= limit:
            entry["refused"] = True
            self.refused_over_limit[tool] = self.refused_over_limit.get(tool, 0) + 1
        self.calls.append(entry)
        return entry
