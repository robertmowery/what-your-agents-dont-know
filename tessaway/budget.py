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

"""Part 6: agent budgets. One owner, a limit per task and a limit per day.

``data/agent_budgets.json`` names each agent's owner and its limits. The checks
here read recorded runs (the same records the meter prices) and report which
runs would have crossed the per-task limit, what the agent was doing when they
did, and which days would have crossed the per-day limit. They run after the
fact; in a live deployment the same numbers would stop a run or a day.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tessaway.meter import spend

ROOT = Path(__file__).resolve().parent.parent
BUDGETS_PATH = ROOT / "data" / "agent_budgets.json"


def load(path: Path = BUDGETS_PATH) -> dict[str, Any]:
    """Read the budget file and check that every agent has an owner and two positive limits."""
    data = json.loads(path.read_text())
    for agent in data["agents"]:
        if not str(agent.get("owner", "")).strip():
            raise ValueError(f"agent {agent.get('agent')!r} has no owner")
        for key in ("limit_per_task_usd", "limit_per_day_usd"):
            if not float(agent.get(key, 0)) > 0:
                raise ValueError(f"agent {agent.get('agent')!r} needs a positive {key}")
    return data


def agent(name: str, path: Path = BUDGETS_PATH) -> dict[str, Any]:
    """Return one agent's entry from the budget file."""
    for entry in load(path)["agents"]:
        if entry["agent"] == name:
            return entry
    raise KeyError(name)


def over_task_limit(records: Iterable[dict[str, Any]], limit_usd: float) -> list[dict[str, Any]]:
    """Runs whose cost crossed the per-task limit, with what the agent was doing.

    Each entry keeps the question, outcome, cost, model calls, queries, whether the
    run asked for more queries than the eight it was allowed, and whether it hit the
    model-call ceiling.
    """
    out = []
    for r in records:
        cost = spend(r)
        if cost > limit_usd:
            out.append(
                {
                    "question_id": r["question_id"],
                    "group": r.get("group"),
                    "trial": r.get("trial"),
                    "outcome": r.get("outcome"),
                    "cost_usd": cost,
                    "model_calls": r.get("model_calls"),
                    "query_count": r.get("query_count"),
                    "asked_past_query_limit": (r.get("queries_refused_over_limit") or 0) > 0,
                    "hit_model_call_ceiling": bool(r.get("hit_model_call_ceiling")),
                    "input_tokens_total": r.get("input_tokens_total"),
                    "retry_of_failed": bool(r.get("retry_of_failed")),
                }
            )
    return out


def spend_by_day(records: Iterable[dict[str, Any]]) -> dict[str, float]:
    """Total recorded spend per UTC day, from each record's ``finished_at``."""
    days: dict[str, float] = defaultdict(float)
    for r in records:
        stamp = r.get("finished_at")
        if not stamp:
            continue
        days[stamp[:10]] += spend(r)
    return dict(sorted(days.items()))


def over_day_limit(by_day: dict[str, float], limit_usd: float) -> dict[str, float]:
    """The days whose spend crossed the per-day limit."""
    return {day: usd for day, usd in by_day.items() if usd > limit_usd}
