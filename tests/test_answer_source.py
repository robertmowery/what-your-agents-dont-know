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

"""Part 3: the rule that says where a final answer came from."""

from __future__ import annotations

from typing import Any

from tessaway import answer_source as src


def metric(rows: list[list[Any]], response_id: str = "r1", seq: int = 1) -> dict[str, Any]:
    return {
        "seq": seq,
        "tool": "compute_metric",
        "response_id": response_id,
        "result": {"columns": ["x"], "rows": rows},
    }


def sql(rows: list[list[Any]], seq: int = 2) -> dict[str, Any]:
    return {"seq": seq, "tool": "run_sql", "result": {"columns": ["x"], "rows": rows}}


def test_the_same_number_from_both_tools_is_both() -> None:
    calls = [metric([[1234567.89]]), sql([[1234567.89]])]
    found = src.classify("1234567.89", "money", calls)
    assert found["source"] == src.BOTH
    assert [m["tool"] for m in found["matched_calls"]] == ["compute_metric", "run_sql"]
    assert found["matched_calls"][0]["response_id"] == "r1"


def test_a_number_from_one_tool_only_is_credited_to_that_tool() -> None:
    assert src.classify("42", "number", [metric([[42]]), sql([[41]])])["source"] == src.CONTRACT
    assert src.classify("41", "number", [metric([[42]]), sql([[41]])])["source"] == src.SQL


def test_a_worked_out_number_is_neither() -> None:
    # A margin percentage written from two returned amounts.
    calls = [metric([[1000.0, 250.0]]), sql([[1000.0]])]
    assert src.classify("25", "percent", calls)["source"] == src.NEITHER


def test_rounding_follows_the_places_the_agent_wrote() -> None:
    assert src.classify("87.5", "percent", [metric([[87.4612]])])["source"] == src.CONTRACT
    assert src.classify("87.46", "percent", [metric([[87.4612]])])["source"] == src.CONTRACT
    assert src.classify("87.47", "percent", [metric([[87.4612]])])["source"] == src.NEITHER
    assert src.classify("$1,234,568", "money", [sql([[1234567.89]])])["source"] == src.SQL


def test_a_fraction_counts_as_a_percentage_only_for_a_percentage_question() -> None:
    assert src.classify("87.5", "percent", [metric([[0.875]])])["source"] == src.CONTRACT
    assert src.classify("50", "number", [metric([[0.5]])])["source"] == src.NEITHER


def test_names_match_on_words() -> None:
    calls = [metric([["Northgate Foods Group", 1.0]]), sql([["northgate foods group"]])]
    assert src.classify("Northgate Foods Group", "text", calls)["source"] == src.BOTH
    assert src.classify("Northgate Foods", "text", calls[:1])["source"] == src.CONTRACT
    assert src.classify("Kestrel", "text", calls)["source"] == src.NEITHER


def test_entity_and_definition_results_are_searched_but_free_text_is_not() -> None:
    entity = {
        "seq": 1,
        "tool": "resolve_entity",
        "response_id": "r9",
        "result": {
            "entities": [
                {
                    "label": "Brightline Haulage",
                    "linked_from": [{"edge": "tw:carrier", "count": 86}],
                }
            ]
        },
    }
    definition = {
        "seq": 2,
        "tool": "lookup_definition",
        "result": {"matches": [{"definition": "A load is late after 15 minutes."}]},
    }
    assert src.classify("86", "number", [entity])["source"] == src.CONTRACT
    assert src.classify("Brightline Haulage", "text", [entity])["source"] == src.CONTRACT
    assert src.classify("15", "number", [definition])["source"] == src.NEITHER


def test_declines_refusals_and_errors_are_not_sources() -> None:
    assert src.classify("NEEDS_CLARIFICATION", "number", [metric([[1]])])["source"] == src.NO_VALUE
    assert src.classify("", "number", [metric([[1]])])["source"] == src.NO_VALUE
    refused = {"seq": 3, "tool": "run_sql", "refused": True}
    failed = {"seq": 4, "tool": "compute_metric", "error": "bad metric"}
    assert src.classify("1", "number", [refused, failed])["source"] == src.NEITHER


def test_numbers_returned_as_text_are_numbers() -> None:
    assert src.classify("27", "number", [sql([["27"]])])["source"] == src.SQL
    assert src.classify("27", "number", [sql([["L1000027"]])])["source"] == src.NEITHER
