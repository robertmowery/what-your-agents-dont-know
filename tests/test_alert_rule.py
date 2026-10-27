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

"""Part 5: the alert rule, written before the drift, stays quiet when nothing changed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tessaway import alert_rule, scoring

ROOT = Path(__file__).resolve().parents[1]
PASSES = {
    "part3_available": ROOT / "results/part3/runs/available.jsonl",
    "part4_available": ROOT / "results/part4/runs/available.jsonl",
}


def _rows(path: Path) -> list[dict[str, Any]]:
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            latest[(r["question_id"], r["trial"])] = r
    return list(latest.values())


def test_the_saved_baseline_is_part4_available() -> None:
    saved = alert_rule.load_baseline()
    assert saved == alert_rule.baseline_from(_rows(PASSES["part4_available"]))
    assert saved["runs"] == 72
    assert {g: v["share"] for g, v in saved["groups"].items()} == {
        "lookup": 1.0, "metric": 1.0, "entity": 1.0, "rule": 1.0,
    }  # fmt: skip


@pytest.mark.parametrize("name", sorted(PASSES))
@pytest.mark.parametrize("trial", [0, 1, 2])
def test_quiet_on_each_execution_of_both_baseline_passes(name: str, trial: int) -> None:
    rows = [r for r in _rows(PASSES[name]) if r["trial"] == trial]
    assert len(rows) == 24
    verdict = alert_rule.evaluate(rows, alert_rule.load_baseline())
    assert not verdict["fired"], verdict


def test_one_wrong_answer_fires_it_and_names_the_group() -> None:
    rows = [r for r in _rows(PASSES["part4_available"]) if r["trial"] == 0]
    rows = [dict(r, outcome=scoring.WRONG) if r["question_id"] == "M2" else r for r in rows]
    verdict = alert_rule.evaluate(rows, alert_rule.load_baseline())
    assert verdict["fired"]
    assert verdict["groups_below"] == ["metric"]
    assert verdict["missed"] == ["M2/confidently_wrong"]


def test_a_failed_run_counts_against_its_group() -> None:
    rows = [r for r in _rows(PASSES["part4_available"]) if r["trial"] == 0]
    rows = [dict(r, outcome=scoring.NO_ANSWER) if r["question_id"] == "L1" else r for r in rows]
    assert alert_rule.evaluate(rows, alert_rule.load_baseline())["groups_below"] == ["lookup"]


def test_the_rule_reads_no_operational_signal() -> None:
    rows = [r for r in _rows(PASSES["part4_available"]) if r["trial"] == 0]
    slow = [dict(r, seconds=10_000.0, cost_usd=10.0, query_count=50) for r in rows]
    assert not alert_rule.evaluate(slow, alert_rule.load_baseline())["fired"]
