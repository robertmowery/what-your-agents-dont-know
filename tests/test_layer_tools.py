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

"""What a Part 2 agent is told and what its tools allow, with no model and no cloud call."""

import asyncio
import json
import re
from typing import Any

import pytest

from tessaway import layers, questions
from tessaway.agents import adk_layer_agent, layer_prompt, prompt
from tessaway.layers import ToolLog, ontology
from tessaway.warehouse import query

COMBINATIONS = [("semantic",), ("ontology",), ("graph",), layers.LAYERS]


# --- the instruction is Part 1's, plus one paragraph per tool ----------------------


def test_with_no_layer_the_instruction_is_the_part_1_instruction() -> None:
    assert layer_prompt.build_instruction(()) == prompt.INSTRUCTION


@pytest.mark.parametrize("combination", COMBINATIONS)
def test_taking_the_added_paragraphs_out_gives_the_part_1_instruction(
    combination: tuple[str, ...],
) -> None:
    text = layer_prompt.build_instruction(combination)
    for layer in combination:
        paragraph = layer_prompt.INSTRUCTION_PARAGRAPH[layer]
        assert text.count(paragraph) == 1
        text = text.replace(f"\n\n{paragraph}", "")
    assert text == prompt.INSTRUCTION


def test_a_configuration_is_told_only_about_its_own_tools() -> None:
    text = layer_prompt.build_instruction(("ontology",))
    assert layer_prompt.ONTOLOGY_TOOL in text
    assert layer_prompt.SEMANTIC_TOOL not in text
    assert layer_prompt.GRAPH_TOOL not in text


def test_the_agent_is_told_each_tool_limit_and_the_sql_limit_is_unchanged() -> None:
    text = layer_prompt.build_instruction(layers.LAYERS)
    assert f"at most {query.MAX_QUERIES} queries" in text
    assert text.count(f"at most {layers.MAX_LAYER_CALLS} times") == 3
    assert layers.MAX_LAYER_CALLS == query.MAX_QUERIES == 8


# --- the agent has the SQL tool beside each layer tool -----------------------------


@pytest.mark.parametrize("combination", COMBINATIONS)
def test_the_sql_tool_stays_beside_the_layer_tools(combination: tuple[str, ...]) -> None:
    agent = adk_layer_agent.build("any-model", combination, query.QueryLog(), ToolLog())
    names = [tool.__name__ for tool in agent.tools]  # type: ignore[union-attr]
    assert names == [prompt.TOOL_NAME, *(layer_prompt.TOOL_OF_LAYER[c] for c in combination)]
    assert agent.tools[0].__doc__ == prompt.TOOL_DESCRIPTION
    for tool, layer in zip(agent.tools[1:], combination, strict=True):
        assert tool.__doc__ == layer_prompt.tool_description(layer)


# --- no description states an answer -----------------------------------------------


def told_to_the_model() -> dict[str, str]:
    """Everything a Part 2 agent can read before it runs a query."""
    texts = {
        f"instruction paragraph: {k}": v for k, v in layer_prompt.INSTRUCTION_PARAGRAPH.items()
    }
    texts.update(
        {f"tool description: {k}": layer_prompt.tool_description(k) for k in layers.LAYERS}
    )
    texts["ontology, every term"] = json.dumps([e.as_dict() for e in ontology.entries()])
    return texts


def numbers_in(text: str) -> set[float]:
    return {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def test_no_tool_description_or_ontology_entry_states_an_answer() -> None:
    gold = questions.load_gold()
    asked = [q for q in questions.load() if q.group != "lookup"]
    assert len(asked) == 18
    for where, text in told_to_the_model().items():
        found = numbers_in(text)
        for question in asked:
            answer = gold[question.id]["gold"]
            if question.answer_type == "text":
                for form in (str(answer), *question.accept):
                    assert form.lower() not in text.lower(), (where, question.id)
            else:
                assert not any(abs(n - float(answer)) < 0.005 for n in found), (where, question.id)


def test_no_tool_description_names_a_particular_account_or_carrier() -> None:
    for where, text in told_to_the_model().items():
        for name in ("northgate", "harlow", "sunmeadow", "ledgerline", "pellam", "midvale"):
            assert name not in text.lower(), where


def test_no_description_repeats_a_question() -> None:
    told = " ".join(told_to_the_model().values()).lower()
    for question in questions.load():
        assert question.question.lower() not in told


def test_the_graph_description_uses_only_names_the_ontology_declares() -> None:
    declared = {entry.name for entry in ontology.entries()}
    for name in set(re.findall(r"tw:[A-Za-z]+", layer_prompt.GRAPH_DESCRIPTION)):
        assert name in declared, name


# --- every tool call is recorded, and each tool has its own allowance ----------------


def call(agent: Any, name: str, **arguments: Any) -> dict[str, Any]:
    tool = next(t for t in agent.tools if t.__name__ == name)
    return dict(asyncio.run(tool(**arguments)))


def test_an_ontology_lookup_is_recorded_with_what_it_matched() -> None:
    tools = ToolLog()
    agent = adk_layer_agent.build("any-model", ("ontology",), query.QueryLog(), tools)
    reply = call(agent, layer_prompt.ONTOLOGY_TOOL, term="billable")
    assert reply["matches"][0]["term"] == "tw:BillableLoad"
    assert tools.calls == [
        {
            "seq": 1,
            "tool": layer_prompt.ONTOLOGY_TOOL,
            "arguments": {"term": "billable"},
            "matches": ["tw:BillableLoad"],
        }
    ]


def test_a_layer_tool_refuses_the_ninth_call_and_says_so() -> None:
    tools = ToolLog()
    agent = adk_layer_agent.build("any-model", ("ontology",), query.QueryLog(), tools)
    for _ in range(layers.MAX_LAYER_CALLS):
        assert "error" not in call(agent, layer_prompt.ONTOLOGY_TOOL, term="load")
    assert call(agent, layer_prompt.ONTOLOGY_TOOL, term="load") == {
        "error": layers.LAYER_LIMIT_MESSAGE
    }
    assert tools.refused_over_limit == {layer_prompt.ONTOLOGY_TOOL: 1}
    assert tools.count(layer_prompt.ONTOLOGY_TOOL) == layers.MAX_LAYER_CALLS
    assert len(tools.calls) == layers.MAX_LAYER_CALLS + 1


def test_the_sql_limit_is_refused_before_bigquery_and_recorded_in_order() -> None:
    log = query.QueryLog(queries=[{"sql": "SELECT 1"}] * query.MAX_QUERIES)
    tools = ToolLog()
    agent = adk_layer_agent.build("any-model", ("ontology",), log, tools)
    call(agent, layer_prompt.ONTOLOGY_TOOL, term="load")
    assert call(agent, prompt.TOOL_NAME, sql="SELECT 2") == {"error": query.LIMIT_MESSAGE}
    assert [(c["seq"], c["tool"]) for c in tools.calls] == [
        (1, layer_prompt.ONTOLOGY_TOOL),
        (2, prompt.TOOL_NAME),
    ]
    assert tools.calls[1]["refused"] is True
    assert log.refused_over_limit == 1


def test_an_agent_inside_every_limit_it_was_told_about_has_calls_left_to_answer() -> None:
    assert adk_layer_agent.max_model_calls(()) == prompt.MAX_MODEL_CALLS
    for combination in COMBINATIONS:
        told = query.MAX_QUERIES + layers.MAX_LAYER_CALLS * len(combination)
        assert adk_layer_agent.max_model_calls(combination) > told + 1
