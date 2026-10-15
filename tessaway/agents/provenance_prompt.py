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

"""What a Part 4 agent is told: Part 3's instruction, plus one paragraph asking it to cite.

The Part 3 instruction for the configuration (``contract_prompt``), word for
word, with one paragraph added at the end. The paragraph asks for one line,
before the final ``ANSWER:`` line, naming the definitions the answer relied
on as the contract returned them: id and version. The ``ANSWER:`` line stays
last, so the Part 1 scorer reads the reply as before.

The record is asked for as a line of text and not through ADK's structured
output, because an ADK agent given an output schema cannot also call tools.

Committed before any Part 4 agent ran. Changing a word here changes the experiment.
"""

from __future__ import annotations

from tessaway.agents import contract_prompt

SOURCES_TOKEN = "SOURCES"

CITATION_PARAGRAPH = (
    "Each response from the context server lists the definitions it used, each with an id, a"
    " version and an owner. On the line just before your ANSWER line, list the definitions your"
    " answer relies on, as the context server gave them to you for this question, in exactly"
    " this form:\n\n"
    f'{SOURCES_TOKEN}: [{{"id": "<definition id>", "version": <version>}}]\n\n'
    "List each definition once. If your answer relies on none of them, write this line"
    f" instead:\n\n{SOURCES_TOKEN}: []"
)


def build_instruction(configuration: str) -> str:
    """Return the Part 3 instruction for ``available`` or ``routed`` with the citation paragraph."""
    return (
        contract_prompt.build_instruction(configuration).rstrip("\n")
        + "\n\n"
        + (CITATION_PARAGRAPH + "\n")
    )
