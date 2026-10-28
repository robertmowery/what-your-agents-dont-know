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

"""Part 5: one execution of the job, with the agent replaced by a fixed reply.

Checks the wiring and nothing about Gemini: records in Part 4's format, one
trace per run joined by run ID, ADK-style child spans landing in the run's
trace, the alert written, and an execution that stopped picking up where it left off.
"""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from context_server import contract
from golden_check import job
from tessaway import tracing
from tessaway.agents import adk_contract_agent

ROOT = Path(__file__).resolve().parents[1]
REPLIES = {
    "L1": "SOURCES: []\nANSWER: 65",
    "M2": 'SOURCES: [{"id": "revenue", "version": 1}]\nANSWER: 10134528.91',
}


def _part4_keys() -> set[str]:
    return set(
        json.loads((ROOT / "results/part4/runs/available.jsonl").read_text().splitlines()[0])
    )


async def fake_ask(model: str, question: str, configuration: str, endpoint: str, token: str,
                   instruction: str | None = None) -> adk_contract_agent.ContractAgentRun:  # fmt: skip
    qid = next(
        k for k, v in {"L1": "How many", "M2": "revenue"}.items() if v.lower() in question.lower()
    )
    with tracing.tracer().start_as_current_span(
        "call_llm gemini", attributes={"gen_ai.request.model": model}
    ):
        pass
    run = adk_contract_agent.ContractAgentRun(run_id=f"run-{qid}", configuration=configuration)
    run.final_text = REPLIES[qid]
    run.model_calls, run.input_tokens, run.output_tokens, run.seconds = 3, 1000, 100, 1.5
    return run


@pytest.fixture
def store(tmp_path: Path) -> job.DirStore:
    return job.DirStore(tmp_path)


def _execute(store: job.DirStore, wanted: set[str]) -> dict[str, Any]:
    return asyncio.run(
        job.run_execution(
            "drift",
            1,
            store=store,
            url="https://contract.example",
            wanted=wanted,
            collector=tracing.configure(),
            ask=fake_ask,
            token_for=lambda _: ("token", "tw-p5-check"),
        )
    )


def test_one_execution_writes_records_traces_and_the_alert(store: job.DirStore) -> None:
    verdict = _execute(store, {"L1", "M2"})
    m2 = json.loads(store.get("part5/drift/e1/runs/M2.json") or "")
    l1 = json.loads(store.get("part5/drift/e1/runs/L1.json") or "")
    assert set(m2) == _part4_keys()  # the run record's format is Part 4's
    assert m2["outcome"] == "confidently_wrong" and l1["outcome"] == "right"
    assert m2["sources_cited"] == ["revenue@1"] and m2["trial"] == 0 and m2["config"] == "drift"
    t = json.loads(store.get("part5/drift/e1/traces/M2.json") or "")
    assert t["run_id"] == m2["run_id"]
    names = [s["name"] for s in t["spans"]]
    assert (
        names.count(tracing.ROOT_SPAN) == 1
        and tracing.SCORE_SPAN in names
        and "call_llm gemini" in names
    )
    root = next(s for s in t["spans"] if s["name"] == tracing.ROOT_SPAN)
    assert all(s["parent_span_id"] == root["span_id"] for s in t["spans"] if s is not root)
    a = root["attributes"]
    assert a[tracing.DEFINITIONS_CITED] == ["revenue@1"]
    assert a[tracing.OUTCOME] == "confidently_wrong"
    assert (
        a[tracing.CONTRACT_VERSION] == contract.CONTRACT_VERSION
        and a[tracing.GOLDEN_SET_VERSION] == 1
    )
    assert a[tracing.DEFINITION_OWNERS] == ["Controller"]
    assert verdict["fired"] and verdict["groups_below"] == ["metric"]
    assert json.loads(store.get("part5/drift/e1/alert.json") or "")["fired"]


def test_a_stopped_execution_resumes_without_asking_again(store: job.DirStore) -> None:
    _execute(store, {"L1"})
    first = store.get("part5/drift/e1/runs/L1.json")
    _execute(store, {"L1", "M2"})
    assert store.get("part5/drift/e1/runs/L1.json") == first
    assert store.get("part5/drift/e1/runs/M2.json")


def test_a_failed_run_is_run_again_once_and_both_records_are_kept(store: job.DirStore) -> None:
    async def failing(*args: Any, **kwargs: Any) -> adk_contract_agent.ContractAgentRun:
        run = await fake_ask(*args, **kwargs)
        run.final_text, run.error = "", "_ResourceExhaustedError: 429"
        return run

    asyncio.run(
        job.run_execution(
            "drift",
            1,
            store=store,
            url="https://contract.example",
            wanted={"L1"},
            collector=tracing.configure(),
            ask=failing,
            token_for=lambda _: ("token", "tw-p5-check"),
        )
    )
    assert json.loads(store.get("part5/drift/e1/runs/L1.json") or "")["outcome"] == "no_answer"
    _execute(store, {"L1"})  # without --retry-failed: nothing is asked again
    assert json.loads(store.get("part5/drift/e1/runs/L1.json") or "")["outcome"] == "no_answer"
    asyncio.run(
        job.run_execution(
            "drift",
            1,
            store=store,
            url="https://contract.example",
            wanted={"L1"},
            collector=tracing.configure(),
            ask=fake_ask,
            retry_failed=True,
            token_for=lambda _: ("token", "tw-p5-check"),
        )
    )
    again = json.loads(store.get("part5/drift/e1/runs/L1.json") or "")
    first = json.loads(store.get(f"part5/drift/e1/runs/L1{job.FIRST_TRY}") or "")
    assert again["outcome"] == "right" and again["retry_of_failed"] is True
    assert first["outcome"] == "no_answer" and "retry_of_failed" not in first


async def any_answer(model: str, question: str, configuration: str, endpoint: str, token: str,
                     instruction: str | None = None) -> adk_contract_agent.ContractAgentRun:  # fmt: skip
    run = adk_contract_agent.ContractAgentRun(
        run_id=f"run-{abs(hash(question))}", configuration=configuration
    )
    run.final_text, run.model_calls, run.seconds = "SOURCES: []\nANSWER: 0", 1, 0.1
    return run


def test_scheduled_executions_on_different_dates_write_their_own_folders_and_ask_all_24(
    store: job.DirStore,
) -> None:
    from datetime import UTC, datetime

    labels = [
        job.scheduled_label(
            datetime(2026, 11, 24, 11, 15, tzinfo=UTC),
            {"CLOUD_RUN_EXECUTION": "tessaway-golden-check-a1b2c"},
        ),
        job.scheduled_label(
            datetime(2026, 11, 25, 11, 15, tzinfo=UTC),
            {"CLOUD_RUN_EXECUTION": "tessaway-golden-check-d3e4f"},
        ),
    ]
    assert labels[0] != labels[1] and labels[0].startswith("2026-11-24")
    for label in labels:
        verdict = asyncio.run(
            job.run_execution(
                job.SCHEDULED,
                1,
                store=store,
                url="https://contract.example",
                label=label,
                collector=tracing.configure(),
                ask=any_answer,
                token_for=lambda _: ("token", "tw-p5-check"),
            )
        )
        assert verdict["runs"] == 24
    folders = {n.split("/")[2] for n in store.names("part5/scheduled/")}
    assert folders == set(labels)
    for label in labels:
        runs = list(store.names(f"part5/scheduled/{label}/runs/"))
        assert len(runs) == 24
