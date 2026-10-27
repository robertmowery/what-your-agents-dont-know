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

"""Part 5: what a trace carries, and that nested spans land in the run's trace."""


from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tessaway import registry, tracing

ROOT = Path(__file__).resolve().parents[1]


def _part4_row(question_id: str) -> dict[str, Any]:
    for line in (ROOT / "results/part4/runs/available.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r["question_id"] == question_id:
            return dict(r)
    raise AssertionError(question_id)


def _owners() -> dict[str, str]:
    return {d: e["owner"] for d, e in registry.load()["definitions"].items()}


def test_end_attributes_carry_the_context_and_the_score() -> None:
    row = _part4_row("M2")
    a = tracing.end_attributes(row, _owners())
    assert a[tracing.DEFINITIONS_CITED] == row["sources_cited"]
    assert a[tracing.DEFINITIONS_SERVED] == row["served_by_agent_record"]
    assert a[tracing.OUTCOME] == "right"
    assert a[tracing.RUN_ID] == row["run_id"]
    assert a[tracing.GEN_AI_USAGE_INPUT_TOKENS] == row["input_tokens_total"]
    assert "Controller" in a[tracing.DEFINITION_OWNERS]
    assert tracing.ERROR_TYPE not in a


def test_a_timeout_is_an_error_type() -> None:
    row = dict(_part4_row("L1"), timed_out=True)
    assert tracing.end_attributes(row, _owners())[tracing.ERROR_TYPE] == "timeout"


def test_every_attribute_is_a_standard_name_or_our_own() -> None:
    row = _part4_row("E3")
    names = set(tracing.end_attributes(row, _owners())) | set(
        tracing.start_attributes(
            run_phase="drift",
            execution=1,
            question_id="E3",
            group="entity",
            model="m",
            golden_set_version=1,
            contract_version="2.0.0",
            registry_sha256="ab" * 32,
        )
    )
    for name in names:
        assert name in tracing.STANDARD or name.startswith("tessaway."), name


def test_nested_spans_collect_under_one_trace_and_drop_long_values() -> None:
    collector = tracing.configure()
    tracer = tracing.tracer()
    with tracer.start_as_current_span(
        tracing.ROOT_SPAN, attributes={tracing.QUESTION_ID: "M2"}
    ) as root:
        with tracer.start_as_current_span(
            "call_llm",
            attributes={"gen_ai.request.model": "m", "gcp.vertex.agent.llm_request": "x" * 5000},
        ):
            pass
        with tracer.start_as_current_span(
            tracing.SCORE_SPAN, attributes={tracing.OUTCOME: "right"}
        ):
            pass
        trace_id = root.get_span_context().trace_id
    spans = collector.pop(trace_id)
    assert [s["name"] for s in spans] == [tracing.ROOT_SPAN, "call_llm", tracing.SCORE_SPAN]
    root_id = spans[0]["span_id"]
    assert spans[1]["parent_span_id"] == root_id and spans[2]["parent_span_id"] == root_id
    assert "gcp.vertex.agent.llm_request" not in spans[1]["attributes"]
    assert spans[1]["attributes"]["gen_ai.request.model"] == "m"
    assert collector.pop(trace_id) == []
