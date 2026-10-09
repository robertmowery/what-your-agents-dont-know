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

"""Derive the figures quoted in the Part 1 articles from the saved runs.

``run_part1.py`` writes one line per run to ``results/part1/runs``. This script
reads those lines, makes no model or cloud call, and writes
``results/part1/article_numbers.json``. Every number in the Part 1 articles
that is not already in ``summary.md`` is in that file.

Usage:
    python analysis/part1_article_numbers.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "results" / "part1" / "runs"
OUT = ROOT / "results" / "part1" / "article_numbers.json"

CONFIGS = ("adk_gemini_flash", "adk_gemini_pro")
BINS = ("right", "confidently_wrong", "declined", "no_answer")
# Questions whose individual answers the articles discuss.
DISCUSSED = ("M1", "R1", "R5", "E1", "E2", "E4", "M2", "M3", "M5")


def load(config: str) -> list[dict[str, Any]]:
    """Return one row per question and trial, keeping the last attempt of each."""
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    with (RUNS / f"{config}.jsonl").open() as handle:
        for line in handle:
            row = json.loads(line)
            latest[(row["question_id"], row["trial"])] = row
    return list(latest.values())


def counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count each bin and give its share of the rows."""
    tally = Counter(row["outcome"] for row in rows)
    total = len(rows)
    result: dict[str, Any] = {"runs": total}
    for name in BINS:
        result[name] = tally.get(name, 0)
        result[f"{name}_pct"] = round(100 * tally.get(name, 0) / total, 1) if total else None
    return result


def mean(rows: list[dict[str, Any]], key: str, digits: int = 4) -> float:
    """Average one numeric field over the rows."""
    return round(sum(float(row.get(key) or 0) for row in rows) / len(rows), digits)


def describe(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Everything the articles quote about one configuration."""
    with_definition = [row for row in rows if row["group"] != "lookup"]
    wrong = [row for row in rows if row["outcome"] == "confidently_wrong"]
    return {
        "model": rows[0]["model"],
        "all_questions": counts(rows),
        "questions_needing_a_definition": counts(with_definition),
        "by_group": {
            group: {
                **counts([row for row in rows if row["group"] == group]),
                "mean_queries": mean(
                    [row for row in rows if row["group"] == group], "query_count", 1
                ),
                "mean_cost_usd": mean([row for row in rows if row["group"] == group], "cost_usd"),
            }
            for group in ("lookup", "metric", "entity", "rule")
        },
        "mean_queries": mean(rows, "query_count", 2),
        "mean_model_calls": mean(rows, "model_calls", 2),
        "mean_input_tokens": round(mean(rows, "input_tokens_total", 0)),
        "mean_output_tokens": round(mean(rows, "output_tokens", 0)),
        "mean_seconds": mean(rows, "seconds", 1),
        "cache_read_share_of_input_pct": round(
            100
            * sum(row["cache_read_tokens"] for row in rows)
            / sum(row["input_tokens_total"] for row in rows),
            1,
        ),
        "runs_that_used_every_query": sum(1 for row in rows if row["query_count"] >= 8),
        "runs_refused_a_further_query": sum(
            1 for row in rows if row["queries_refused_over_limit"] > 0
        ),
        "cost_usd": round(sum(row["cost_usd"] for row in rows), 2),
        "mean_cost_usd_by_outcome": {
            name: mean([row for row in rows if row["outcome"] == name], "cost_usd")
            for name in BINS
            if any(row["outcome"] == name for row in rows)
        },
        "wrong_answers": len(wrong),
        "wrong_answers_matching_a_named_wrong_reading": sum(
            1 for row in wrong if row["matched_decoy"]
        ),
        "wrong_answers_that_flagged_an_assumption": sum(
            1 for row in wrong if row["flagged_assumption"]
        ),
        "discussed_questions": {
            qid: {
                "gold": next(row["gold"] for row in rows if row["question_id"] == qid),
                **counts([row for row in rows if row["question_id"] == qid]),
                "answers_given": dict(
                    Counter(
                        str(row["extracted"])
                        for row in rows
                        if row["question_id"] == qid and row["outcome"] != "declined"
                    )
                ),
            }
            for qid in DISCUSSED
        },
    }


def main() -> None:
    """Write the derived figures."""
    data = {config: describe(load(config)) for config in CONFIGS}
    flash, pro = (data[config]["all_questions"] for config in CONFIGS)
    data["stronger_model_minus_base"] = {
        name: pro[name] - flash[name] for name in ("right", "confidently_wrong", "declined")
    }
    both = load(CONFIGS[0]) + load(CONFIGS[1])
    data["both_models"] = {
        "runs": len(both),
        "lookup": counts([row for row in both if row["group"] == "lookup"]),
        "by_discussed_question": {
            qid: counts([row for row in both if row["question_id"] == qid]) for qid in DISCUSSED
        },
    }
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
