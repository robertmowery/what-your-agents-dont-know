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

"""What both agents are told. The two runtimes get the same words.

The instruction gives the agent its job, the schema as names and types, and
the form of the final line the scorer reads. It says nothing about what any
table, column or code means. Changing a word here changes the experiment, and
the results in ``results/part1`` would no longer describe the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tessaway.warehouse import schema
from tessaway.warehouse.query import MAX_QUERIES

TOOL_NAME = "run_sql"

# Sent to the model as the tool's description, on both runtimes.
TOOL_DESCRIPTION = (
    "Runs one read-only GoogleSQL SELECT statement against the Tessaway Freight warehouse in"
    " BigQuery and returns the rows. Table names need no dataset prefix. At most 50 rows are"
    " returned."
)

DECLINE_TOKEN = "NEEDS_CLARIFICATION"

# The most model calls one question may use, on either runtime. An agent that
# uses every query still has calls left to answer.
MAX_MODEL_CALLS = 16

# Seconds before one question is abandoned.
RUN_TIMEOUT_S = 300.0

INSTRUCTION = f"""You are a data analyst at Tessaway Freight. You answer business questions \
from the company's data warehouse in BigQuery. Today is October 1, 2026.

Use the {TOOL_NAME} tool to query the warehouse. It runs one read-only GoogleSQL SELECT \
statement at a time. You can run at most {MAX_QUERIES} queries for a question.

These are the tables in the warehouse. Table names, column names and column types are all \
you are given about them.

{schema.render_for_agent()}

When you are done, reply with a short explanation and end with one final line in exactly \
this form:

ANSWER: <value>

For a count, an amount or a rate, <value> is a single number with no words. Give money in \
US dollars and rates as a percentage from 0 to 100. For a "who" or "which" question, <value> \
is the name.

If you cannot answer from the warehouse, or you need the person asking to clarify something \
first, say what you need and end with this line instead:

ANSWER: {DECLINE_TOKEN}
"""


@dataclass
class AgentRun:
    """What one agent did with one question, in the same shape for both runtimes."""

    final_text: str = ""
    seconds: float = 0.0
    model_calls: int = 0
    # Input tokens billed at the full rate, input tokens read from a cache, and
    # input tokens written to a cache. Together they are everything sent.
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Includes thinking tokens, which bill as output.
    output_tokens: int = 0
    # Every query the agent sent, in order, with row counts and errors.
    queries: list[dict[str, Any]] = field(default_factory=list)
    queries_refused_over_limit: int = 0
    bytes_billed: int = 0
    timed_out: bool = False
    error: str = ""
    # The model name the provider reported serving, when it reports one.
    model_reported: str = ""
