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

"""Part 4: the traceability checker on hand-made passing and failing answers."""

from __future__ import annotations

from typing import Any

import pytest

import run_part4
from context_server import contract
from tessaway import scoring, traceability as tr
from tessaway.agents import contract_prompt, provenance_prompt

SERVED = {("on_time", 1), ("delivered_load", 1)}


def reply(sources: str, answer: str = "139") -> str:
    return f"Some explanation.\n\n{sources}\nANSWER: {answer}"


@pytest.mark.parametrize(
    ("sources", "status"),
    [
        ('SOURCES: [{"id": "on_time", "version": 1}]', tr.TRACEABLE),
        ('SOURCES: [{"id": "on_time", "version": 1}, {"id": "delivered_load", "version": "1"}]', tr.TRACEABLE),
        ("SOURCES: []", tr.CITES_NONE),
        ("", tr.NO_SOURCES_LINE),
        ('SOURCES: [{"id": "on_time", "version": 2}]', tr.CITES_UNREGISTERED),
        ('SOURCES: [{"id": "late_deliveries", "version": 1}]', tr.CITES_UNREGISTERED),
        ('SOURCES: [{"id": "on_time"}]', tr.CITES_UNREGISTERED),
        ('SOURCES: [{"id": "revenue", "version": 1}]', tr.CITES_UNSERVED),
        ('SOURCES: [{"id": "on_time", "version": 1}, {"id": "revenue", "version": 1}]', tr.CITES_UNSERVED),
        ('**SOURCES:** [{"id": "on_time", "version": 1}]', tr.TRACEABLE),
        ('SOURCES: on_time version 1 {"id": "on_time", "version": 1}', tr.TRACEABLE),
    ],
)
def test_the_three_checks(sources: str, status: str) -> None:
    assert tr.check(reply(sources), SERVED)["status"] == status


def test_a_citation_is_not_a_trace_when_nothing_was_served() -> None:
    result = tr.check(reply('SOURCES: [{"id": "on_time", "version": 1}]'), set())
    assert result["status"] == tr.CITES_UNSERVED
    assert result["cited_not_served"] == ["on_time@1"]


def test_using_without_citing() -> None:
    assert tr.check(reply("SOURCES: []"), SERVED)["served_not_cited"] is True
    assert tr.check(reply("SOURCES: []"), set())["served_not_cited"] is False


def test_the_last_sources_line_counts() -> None:
    text = 'SOURCES: [{"id": "revenue", "version": 1}]\n' + reply(
        'SOURCES: [{"id": "on_time", "version": 1}]'
    )
    assert tr.check(text, SERVED)["traceable"]


def test_served_is_read_from_the_log_and_from_the_record() -> None:
    log = [{"definitions": ["on_time@1", "delivered_load@1"]}, {"definitions": []}, {}]
    assert tr.served_in_log(log) == SERVED
    record = [{"definitions": [{"id": "on_time", "version": 1, "owner": "VP Operations"}]}, {}]
    assert tr.served_in_record(record) == {("on_time", 1)}


def test_the_scorer_still_reads_the_answer_after_a_sources_line() -> None:
    assert scoring.extract_answer(reply('SOURCES: [{"id": "on_time", "version": 1}]')) == "139"


def test_the_instruction_is_part3s_word_for_word_plus_one_paragraph() -> None:
    for configuration in contract_prompt.CONFIGURATIONS:
        before = contract_prompt.build_instruction(configuration).rstrip("\n")
        after = provenance_prompt.build_instruction(configuration)
        assert after.startswith(before)
        assert after.rstrip("\n").endswith(f"{provenance_prompt.SOURCES_TOKEN}: []")
        assert after.count("ANSWER:") == before.count("ANSWER:")


def test_the_envelope_names_the_definitions_served() -> None:
    reply_ = contract.envelope(
        contract.COMPUTE_METRIC, {"rows": [[0]]}, {"metrics": ["late_deliveries"]}
    )
    assert reply_["contract_version"] == contract.CONTRACT_VERSION
    assert reply_["definitions"] == [{"id": "on_time", "version": 1, "owner": "VP Operations"}]
    # A failed call serves nothing; a lookup that matches nothing serves nothing.
    assert contract.envelope(contract.COMPUTE_METRIC, {"error": "x"}, {"metrics": ["revenue"]})[
        "definitions"
    ] == []
    empty = {"term": "miles", "matches": [], "all_terms": [{"term": "tw:Load"}]}
    assert contract.envelope(contract.LOOKUP_DEFINITION, empty)["definitions"] == []
    matched = {"term": "late", "matches": [{"term": "tw:OnTime"}]}
    stamped = contract.envelope(contract.LOOKUP_DEFINITION, matched)
    assert stamped["definitions"] == [{"id": "on_time", "version": 1, "owner": "VP Operations"}]
    assert stamped["result"]["matches"][0]["definition"]["owner"] == "VP Operations"


def _row(qid: str, group: str, outcome: str, text: str, run_id: str) -> dict[str, Any]:
    return {
        "question_id": qid, "group": group, "outcome": outcome, "answer_text": text,
        "run_id": run_id, "trial": 0, "served_by_agent_record": [],
    }  # fmt: skip


def test_the_traceability_block_counts_by_the_written_rules() -> None:
    rows = [
        _row("M1", "metric", scoring.RIGHT, reply('SOURCES: [{"id": "on_time", "version": 1}]'), "a"),
        _row("M2", "metric", scoring.RIGHT, reply("SOURCES: []"), "b"),
        _row("M3", "metric", scoring.RIGHT, reply('SOURCES: [{"id": "revenue", "version": 1}]'), "c"),
        _row("M4", "metric", scoring.DECLINED, reply("SOURCES: []", "NEEDS_CLARIFICATION"), "d"),
        _row("L1", "lookup", scoring.RIGHT, reply("SOURCES: []", "65"), "e"),
    ]  # fmt: skip
    log = {k: [{"definitions": ["on_time@1"]}] for k in "abcde"}
    block = run_part4.traceability_block(rows, log)
    need = block["needs_definition"]
    assert need["answered_runs"] == 3 and need["traceable"] == 1
    assert need["citing_without_using"] == 1 and need["using_without_citing"] == 1
    assert block["lookups"] == {
        "runs": 1, "cite_nothing": 1, "no_sources_line": 0, "cite_something": 0,
        "cite_something_served": 0, "served_something": 1,
    }  # fmt: skip


def test_the_audit_falls_back_to_part3s_h10_when_nothing_is_wrong() -> None:
    picked = run_part4.pick_audit({"available": [], "routed_holdout": []})
    assert picked["from"] == "part3"
    assert (picked["row"]["question_id"], picked["row"]["trial"]) == ("H10", 0)


def test_the_audit_picks_the_first_wrong_run_in_question_order() -> None:
    rows = {
        "available": [],
        "routed_holdout": [
            {**_row("H12", "rule", scoring.WRONG, "", "x"), "trial": 0},
            {**_row("H10", "rule", scoring.WRONG, "", "y"), "trial": 2},
            {**_row("H10", "rule", scoring.WRONG, "", "z"), "trial": 1},
        ],
    }
    picked = run_part4.pick_audit(rows)
    assert picked["from"] == "part4" and picked["row"]["run_id"] == "z"


def test_clean_takes_out_emails_and_keeps_service_account_names() -> None:
    text = "tw-p3-agent-routed@PROJECT.iam.gserviceaccount.com and someone@example.com"
    assert run_part4.clean(text) == "tw-p3-agent-routed and EMAIL"
