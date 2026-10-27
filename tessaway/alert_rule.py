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

"""The alert rule for the standing answer check, written before the drift was planted.

The rule: after each execution of the golden set, compare the share of runs
scored right in each question group (lookup, metric, entity, rule) with the
same share in the baseline. If any group's share is lower than the baseline's,
the alert fires and names the groups and the questions that missed.

Nothing else goes into the rule. It reads the scorer's verdict on each run and
no operational signal: latency, cost and errors belong to the dashboards it is
meant to sit beside. A run that ends in an error or a timeout is not right, so
it counts against its group like any other miss.

The baseline is Part 4's available run (72 runs of the 24 questions through
the contract and the SQL tool), saved as ``results/part5/alert_baseline.json``
by :func:`write_baseline` before any Part 5 run. The rule is not tuned after
any result; ``tests/test_alert_rule.py`` checks that it stays quiet on both
earlier passes of the same configuration (Part 3 and Part 4 available), each
read one execution (24 runs) at a time.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tessaway import questions, scoring

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "results" / "part5" / "alert_baseline.json"
BASELINE_SOURCE = "results/part4/runs/available.jsonl"
RULE = (
    "Fire when the share of runs scored right in any question group is lower than that"
    " group's share in the baseline (Part 4 available, 72 runs)."
)


def right_share_by_group(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Runs, runs right and the share right, for each question group present."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        g = out.setdefault(row["group"], {"runs": 0, "right": 0})
        g["runs"] += 1
        g["right"] += int(row["outcome"] == scoring.RIGHT)
    for g in out.values():
        g["share"] = round(g["right"] / g["runs"], 4) if g["runs"] else None
    return {k: out[k] for k in questions.GROUPS if k in out}


def baseline_from(rows: Iterable[dict[str, Any]], source: str = BASELINE_SOURCE) -> dict[str, Any]:
    """Build the baseline the rule compares against."""
    rows = list(rows)
    return {"source": source, "runs": len(rows), "rule": RULE, "groups": right_share_by_group(rows)}


def write_baseline(rows: Iterable[dict[str, Any]], path: Path = BASELINE_PATH) -> dict[str, Any]:
    """Save the baseline beside the Part 5 results."""
    base = baseline_from(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(base, indent=1) + "\n")
    return base


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, Any]:
    """Read the saved baseline."""
    return dict(json.loads(path.read_text()))


def evaluate(rows: Iterable[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    """Apply the rule to one execution's runs.

    Returns ``{"fired", "groups_below", "by_group", "missed"}``: whether the
    alert fires, which groups fell below their baseline share, every group's
    share now and in the baseline, and the runs that were not right, as
    ``question_id/outcome``.
    """
    rows = list(rows)
    now = right_share_by_group(rows)
    below = []
    by_group = {}
    for group, cur in now.items():
        base = baseline["groups"].get(group)
        base_share = base["share"] if base else None
        by_group[group] = {**cur, "baseline_share": base_share}
        if base_share is not None and cur["share"] is not None and cur["share"] < base_share:
            below.append(group)
    missed = sorted(
        f"{r['question_id']}/{r['outcome']}" for r in rows if r["outcome"] != scoring.RIGHT
    )
    return {"fired": bool(below), "groups_below": below, "by_group": by_group, "missed": missed}
