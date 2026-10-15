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

"""Part 3: the check of the server's call log against the agents' own records."""

from __future__ import annotations

from typing import Any

import run_part3

CALLER = "agent@PROJECT.iam.gserviceaccount.com"


def row(calls: list[dict[str, Any]], run_id: str = "run-1", error: str = "") -> dict[str, Any]:
    return {
        "run_id": run_id,
        "question_id": "M1",
        "caller": CALLER,
        "error": error,
        "timed_out": False,
        "tool_calls": calls,
    }


def call(rid: str, op: str = "compute_metric", **extra: Any) -> dict[str, Any]:
    return {"tool": op, "response_id": rid, "contract_version": "1.0.0", "result": {}, **extra}


def line(
    rid: str, op: str = "compute_metric", run_id: str = "run-1", **extra: Any
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "response_id": rid,
        "operation": op,
        "contract_version": "1.0.0",
        "caller": CALLER,
        **extra,
    }


def test_matching_records_agree() -> None:
    check = run_part3.compare_log(
        [row([call("a"), call("b", "check_rule")])], [line("a"), line("b", "check_rule")]
    )
    assert check["agreeing_calls"] == 2
    assert check["runs_agreeing"] == 1
    assert check["problems"] == []


def test_a_call_missing_from_the_log_or_an_extra_log_line_is_a_mismatch() -> None:
    missing = run_part3.compare_log([row([call("a"), call("b")])], [line("a")])
    assert missing["agent_calls_missing_from_server_log"] == 1
    assert missing["runs_with_a_problem"] == 1
    extra = run_part3.compare_log([row([call("a")])], [line("a"), line("z")])
    assert extra["server_lines_missing_from_agent_record"] == 1
    assert extra["runs_with_a_problem"] == 1


def test_a_different_caller_or_version_is_a_mismatch() -> None:
    check = run_part3.compare_log([row([call("a")])], [line("a", caller="someone-else")])
    assert check["calls_that_differ"] == 1
    check = run_part3.compare_log([row([call("a")])], [line("a", contract_version="2.0.0")])
    assert check["calls_that_differ"] == 1


def test_a_call_the_mcp_layer_refused_is_counted_apart_not_as_a_mismatch() -> None:
    refused = {"tool": "compute_metric", "error": "1 validation error for compute_metricArguments"}
    check = run_part3.compare_log([row([refused, call("a")])], [line("a")])
    assert check["calls_refused_before_the_contract_ran"] == 1
    assert check["runs_with_a_problem"] == 0
    assert check["agreeing_calls"] == 1


def test_calls_refused_by_the_harness_limit_never_reach_the_server() -> None:
    over = {"tool": "compute_metric", "refused": True}
    check = run_part3.compare_log([row([call("a"), over])], [line("a")])
    assert check["agent_calls"] == 1
    assert check["runs_agreeing"] == 1
