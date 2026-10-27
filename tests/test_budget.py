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

"""Part 6: every agent has an owner and limits, and the checks find what crossed them."""

from __future__ import annotations

import json

import pytest

from tessaway import budget


def test_budget_file_names_an_owner_and_two_limits():
    data = budget.load()
    assert data["agents"]
    for entry in data["agents"]:
        assert entry["owner"].strip()
        assert entry["limit_per_task_usd"] > 0
        assert entry["limit_per_day_usd"] > entry["limit_per_task_usd"]
    assert "fictional" in data["about"]


def test_an_agent_without_an_owner_is_refused(tmp_path):
    path = tmp_path / "budgets.json"
    path.write_text(
        json.dumps(
            {
                "agents": [
                    {"agent": "a", "owner": " ", "limit_per_task_usd": 1, "limit_per_day_usd": 2}
                ]
            }
        )
    )
    with pytest.raises(ValueError):
        budget.load(path)


def test_runs_over_the_task_limit_carry_what_the_agent_was_doing():
    records = [
        {
            "question_id": "M1",
            "group": "metric",
            "trial": 0,
            "outcome": "declined",
            "cost_usd": 0.12,
            "bigquery_usd": 0.0,
            "model_calls": 11,
            "query_count": 8,
            "queries_refused_over_limit": 1,
            "input_tokens_total": 90_000,
        },
        {
            "question_id": "L1",
            "group": "lookup",
            "trial": 0,
            "outcome": "right",
            "cost_usd": 0.01,
            "bigquery_usd": 0.0,
            "model_calls": 2,
            "query_count": 1,
        },
    ]
    over = budget.over_task_limit(records, 0.10)
    assert [o["question_id"] for o in over] == ["M1"]
    assert over[0]["asked_past_query_limit"] is True
    assert over[0]["model_calls"] == 11


def test_spend_by_day_uses_the_utc_date():
    records = [
        {"finished_at": "2026-10-09T23:59:00+00:00", "cost_usd": 1.0, "bigquery_usd": 0.0},
        {"finished_at": "2026-10-10T00:01:00+00:00", "cost_usd": 2.0, "bigquery_usd": 0.5},
        {"finished_at": "2026-10-10T08:00:00+00:00", "cost_usd": 3.0, "bigquery_usd": 0.0},
    ]
    days = budget.spend_by_day(records)
    assert days == {"2026-10-09": 1.0, "2026-10-10": 5.5}
    assert budget.over_day_limit(days, 5.0) == {"2026-10-10": 5.5}
