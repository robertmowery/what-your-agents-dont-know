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

"""Derive the figures an article would quote about the held-out test.

``run_holdout.py`` writes one line per run to ``results/holdout/runs``. This
script reads those lines, the coverage classes fixed before the runs, and the
saved Part 1 and Part 2 runs for the side-by-side. It makes no model or cloud
call and writes ``results/holdout/article_numbers.json``.

For every semantic-layer run that was not right it lists the tool calls the
agent made (which metric, which filters, or the SQL), so an article can say why
the run failed. The predictions are read against the runs by the rules written
down in ``results/holdout/predictions.md`` before any run.

Usage:
    python analysis/holdout_article_numbers.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_holdout  # noqa: E402 - the repository root has to be on the path first
import run_part1  # noqa: E402
from tessaway import questions  # noqa: E402
from tessaway.agents import layer_prompt, prompt  # noqa: E402

HOLDOUT = ROOT / "results" / "holdout"
OUT = HOLDOUT / "article_numbers.json"
PART1_RUNS = ROOT / "results" / "part1" / "runs" / "adk_gemini_flash.jsonl"
PART2_RUNS = ROOT / "results" / "part2" / "runs" / "flash_semantic.jsonl"

BINS = ("right", "confidently_wrong", "declined", "no_answer")
RUNS_PER_QUESTION = 3
SQL, METRIC = prompt.TOOL_NAME, layer_prompt.SEMANTIC_TOOL
BASELINE, SEMANTIC = run_holdout.BASELINE, run_holdout.SEMANTIC


def tally(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count each outcome and give it as a percentage of the runs."""
    counts = Counter(r["outcome"] for r in rows)
    total = len(rows)
    result: dict[str, Any] = {"runs": total}
    for name in BINS:
        result[name] = counts.get(name, 0)
        result[f"{name}_pct"] = round(100 * counts.get(name, 0) / total, 1) if total else None
    return result


def change(now: dict[str, Any], before: dict[str, Any]) -> dict[str, float]:
    """Return the change between two tallies, in percentage points."""
    return {
        name: round(now[f"{name}_pct"] - before[f"{name}_pct"], 1)
        for name in ("right", "confidently_wrong", "declined")
    }


def breakdown(rows: list[dict[str, Any]], classes: dict[str, str]) -> dict[str, Any]:
    """Tally one configuration overall, by question group and by coverage class."""
    return {
        "overall": tally(rows),
        "by_group": {
            group: tally([r for r in rows if r["group"] == group])
            for group in run_holdout.GROUPS
            if any(r["group"] == group for r in rows)
        },
        "by_coverage_class": {
            kind: tally([r for r in rows if classes[r["question_id"]] == kind])
            for kind in run_holdout.CLASSES
            if any(classes[r["question_id"]] == kind for r in rows)
        },
    }


def changes(now: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    """Return the change between two breakdowns wherever both have runs."""
    return {
        "overall": change(now["overall"], before["overall"]),
        "by_group": {
            g: change(entry, before["by_group"][g])
            for g, entry in now["by_group"].items()
            if g in before["by_group"]
        },
        "by_coverage_class": {
            k: change(entry, before["by_coverage_class"][k])
            for k, entry in now["by_coverage_class"].items()
            if k in before["by_coverage_class"]
        },
    }


def describe_call(call: dict[str, Any]) -> dict[str, Any]:
    """Reduce one saved tool call to what an article needs to say what the agent did."""
    arguments = call.get("arguments") or {}
    entry: dict[str, Any] = {"seq": call.get("seq"), "tool": call["tool"]}
    if call["tool"] == METRIC:
        entry["metrics"] = arguments.get("metrics") or []
        for key in ("group_by", "where", "order_by"):
            if arguments.get(key):
                entry[key] = arguments[key]
        if arguments.get("start_date") or arguments.get("end_date"):
            entry["period"] = [arguments.get("start_date", ""), arguments.get("end_date", "")]
        if arguments.get("limit") not in (None, 50):
            entry["limit"] = arguments["limit"]
    else:
        entry["sql"] = " ".join(str(arguments.get("sql", "")).split())
    if call.get("refused"):
        entry["refused_over_limit"] = True
    if call.get("error"):
        entry["error"] = str(call["error"])[:300]
    elif "row_count" in call:
        entry["rows"] = call["row_count"]
    return entry


def failure(row: dict[str, Any], kind: str) -> dict[str, Any]:
    """Describe one run that was not right: what it answered and every tool call it made."""
    made = [describe_call(call) for call in row.get("tool_calls", [])]
    metric_calls = [c for c in made if c["tool"] == METRIC and not c.get("refused_over_limit")]
    return {
        "question_id": row["question_id"],
        "trial": row["trial"],
        "group": row["group"],
        "coverage_class": kind,
        "outcome": row["outcome"],
        "answer": row["extracted"],
        "gold": row["gold"],
        "matched_decoy": row.get("matched_decoy", ""),
        "metric_calls": len(metric_calls),
        "metric_calls_with_an_error": sum(1 for c in metric_calls if c.get("error")),
        "sql_calls": sum(1 for c in made if c["tool"] == SQL and not c.get("refused_over_limit")),
        "metrics_asked_for": sorted({m for c in metric_calls for m in c["metrics"]}),
        "filters_used": sorted({w for c in metric_calls for w in c.get("where", [])}),
        "group_bys_used": sorted({g for c in metric_calls for g in c.get("group_by", [])}),
        "hit_sql_limit": (row.get("queries_refused_over_limit") or 0) > 0,
        "hit_metric_limit": sum((row.get("layer_calls_refused") or {}).values()) > 0,
        "timed_out": bool(row.get("timed_out")),
        "error": row.get("error", ""),
        "tool_calls": made,
    }


def per_question(
    asked: list[questions.Question],
    rows_by_config: dict[str, list[dict[str, Any]]],
    coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return each question with what every run of each configuration answered."""
    by_id = {entry["question_id"]: entry for entry in coverage["questions"]}
    result = []
    for question in asked:
        entry: dict[str, Any] = {
            "question_id": question.id,
            "group": question.group,
            "question": question.question,
            "gold": by_id[question.id]["gold"],
            "coverage_class": by_id[question.id]["class"],
            "coverage_note": by_id[question.id].get("note", ""),
        }
        for name, rows in rows_by_config.items():
            mine = sorted(
                (r for r in rows if r["question_id"] == question.id), key=lambda r: r["trial"]
            )
            entry[name] = {
                **{k: v for k, v in tally(mine).items() if not k.endswith("_pct")},
                "outcomes": [r["outcome"] for r in mine],
                "answers": [r["extracted"] for r in mine],
                "decoys_matched": [r["matched_decoy"] for r in mine if r.get("matched_decoy")],
                "tools": [
                    {SQL: run_holdout.calls(r, SQL), METRIC: run_holdout.calls(r, METRIC)}
                    for r in mine
                ],
            }
        result.append(entry)
    return result


def part1_set() -> dict[str, Any]:
    """The 24-question figures this test is set beside, from the saved Part 1 and Part 2 runs."""
    base = run_part1.read_runs(PART1_RUNS)
    layer = [r for r in run_part1.read_runs(PART2_RUNS) if r["trial"] < RUNS_PER_QUESTION]
    if not base or not layer:
        return {}

    def hard(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [r for r in rows if r["group"] != "lookup"]

    return {
        "all_24_questions": {
            "baseline": {**tally(base), "runs_per_question": 10},
            SEMANTIC: {**tally(layer), "runs_per_question": RUNS_PER_QUESTION},
            "change_points": change(tally(layer), tally(base)),
        },
        "the_18_outside_the_lookup_group": {
            "note": "The held-out set has no lookup questions, so this is the like-for-like row.",
            "baseline": {**tally(hard(base)), "runs_per_question": 10},
            SEMANTIC: {**tally(hard(layer)), "runs_per_question": RUNS_PER_QUESTION},
            "change_points": change(tally(hard(layer)), tally(hard(base))),
        },
    }


def read_predictions(
    base: dict[str, Any],
    layer: dict[str, Any],
    failures: list[dict[str, Any]],
    part1: dict[str, Any],
) -> list[dict[str, Any]]:
    """Read each claim in predictions.md against the runs, by the rule written there."""
    b, s = base["overall"], layer["overall"]
    one_run = round(100 / s["runs"], 1) if s["runs"] else 0.0
    gain = round(s["right_pct"] - b["right_pct"], 1)
    part1_gain = part1.get("all_24_questions", {}).get("change_points", {}).get("right")
    outside = [
        f for f in failures if f["coverage_class"] in ("several_or_arithmetic", "not_answerable")
    ]
    result = [
        {
            "claim": "The layer helps on questions it was not built for",
            "rule": "semantic right share more than two runs above the held-out baseline's",
            "holds": gain > 2 * one_run,
            "numbers": {"gain_points": gain, "two_runs_points": round(2 * one_run, 1)},
        },
        {
            "claim": "The layer generalizes as well as Part 2 suggested",
            "rule": "semantic right in at least 34 of 36 runs",
            "holds": s["right"] >= 34,
            "numbers": {"right": s["right"], "runs": s["runs"]},
        },
        {
            "claim": "The layer does much less on unseen questions",
            "rule": "gain over the held-out baseline is less than half the gain on the 24",
            "holds": None if part1_gain is None else gain < part1_gain / 2,
            "numbers": {"gain_points": gain, "gain_points_on_the_24": part1_gain},
        },
        {
            "claim": "The layer's failures are the ones coverage predicts",
            "rule": "wrong and declined semantic runs fall mostly in the third and fourth classes",
            "holds": None if not failures else len(outside) > len(failures) / 2,
            "numbers": {"failures": len(failures), "in_third_or_fourth_class": len(outside)},
        },
        {
            "claim": "The layer does no harm",
            "rule": "semantic confidently wrong share not more than two runs above the baseline's",
            "holds": s["confidently_wrong_pct"] - b["confidently_wrong_pct"] <= 2 * one_run,
            "numbers": {
                "baseline_confidently_wrong": b["confidently_wrong"],
                "semantic_confidently_wrong": s["confidently_wrong"],
            },
        },
    ]
    predicted = {BASELINE: (7, 12), SEMANTIC: (20, 30)}
    for name, block in ((BASELINE, b), (SEMANTIC, s)):
        low, high = predicted[name]
        result.append(
            {
                "claim": f"{name}: between {low} and {high} of 36 runs right",
                "rule": "the range written in predictions.md",
                "holds": low <= block["right"] <= high,
                "numbers": {"right": block["right"], "runs": block["runs"]},
            }
        )
    return result


def build(
    rows_by_config: dict[str, list[dict[str, Any]]],
    coverage: dict[str, Any],
    asked: list[questions.Question],
    part1: dict[str, Any],
) -> dict[str, Any]:
    """Put together every figure from the saved runs."""
    classes = {entry["question_id"]: entry["class"] for entry in coverage["questions"]}
    blocks = {name: breakdown(rows, classes) for name, rows in rows_by_config.items()}
    base, layer = blocks[BASELINE], blocks[SEMANTIC]
    semantic_rows = rows_by_config[SEMANTIC]
    failures = [
        failure(r, classes[r["question_id"]])
        for r in sorted(
            semantic_rows,
            key=lambda r: (run_holdout.question_order(r["question_id"]), r["trial"]),
        )
        if r["outcome"] != "right"
    ]
    flawed = coverage.get("questions_where_dropping_a_condition_still_scores_right", [])
    without = {
        name: tally([r for r in rows if r["question_id"] not in flawed])
        for name, rows in rows_by_config.items()
    }
    use = run_holdout.tool_use(semantic_rows, classes)
    return {
        "what": "Figures for the held-out fairness test of Part 2, derived from"
        " results/holdout/runs by analysis/holdout_article_numbers.py.",
        "complete": {
            name: len(rows) == len(asked) * RUNS_PER_QUESTION
            for name, rows in rows_by_config.items()
        },
        "runs_per_question": RUNS_PER_QUESTION,
        "questions": len(asked),
        "one_run_in_points": {"overall": round(100 / (len(asked) * RUNS_PER_QUESTION), 1)},
        "coverage": {
            "labels": coverage["classes"],
            "counts": coverage["counts"],
            "by_class": coverage["by_class"],
            "checked_at": coverage["checked_at"],
        },
        "configurations": blocks,
        "change_baseline_to_semantic_points": changes(layer, base),
        "side_by_side": {
            "held_out_12_questions": {
                "baseline": base["overall"],
                SEMANTIC: layer["overall"],
                "change_points": change(layer["overall"], base["overall"]),
            },
            **part1,
        },
        "without_the_flawed_questions": {
            "questions_left_out": flawed,
            "why": "The coverage check found that an answer ignoring the question's condition"
            " is still scored right.",
            **without,
            "change_points": change(without[SEMANTIC], without[BASELINE]),
        },
        "per_question": per_question(asked, rows_by_config, coverage),
        "semantic_tool_use": use,
        "bypass": use["went_around_the_semantic_layer"],
        "semantic_runs_not_right": failures,
        "semantic_runs_not_right_by_question": dict(Counter(f["question_id"] for f in failures)),
        "baseline_decoys_matched": dict(
            Counter(
                f"{r['question_id']}: {r['matched_decoy']}"
                for r in rows_by_config[BASELINE]
                if r.get("matched_decoy")
            )
        ),
        "semantic_decoys_matched": dict(
            Counter(
                f"{r['question_id']}: {r['matched_decoy']}"
                for r in semantic_rows
                if r.get("matched_decoy")
            )
        ),
        "runs_repeated_after_a_failure": {
            name: sum(1 for r in rows if r.get("retry_of_failed"))
            for name, rows in rows_by_config.items()
        },
        "predictions_read_against_the_runs": read_predictions(base, layer, failures, part1),
        "spend": run_holdout.spend(),
    }


def load_rows(root: Path = HOLDOUT) -> dict[str, list[dict[str, Any]]]:
    """Read the saved runs of both configurations, scored again with the current scorer."""
    asked = questions.load(run_holdout.QUESTIONS_PATH)
    gold = questions.load_gold(run_holdout.GOLD_PATH)
    by_id = {q.id: q for q in asked}
    result = {}
    for name in run_holdout.CONFIGS:
        rows = [
            r
            for r in run_part1.read_runs(root / "runs" / f"{name}.jsonl")
            if r["question_id"] in by_id and r["trial"] < RUNS_PER_QUESTION
        ]
        for row in rows:
            run_part1.rescore(row, by_id, gold)
        result[name] = rows
    return result


def main() -> None:
    """Write ``article_numbers.json`` and print the headline."""
    rows = load_rows()
    if not all(rows.values()):
        raise SystemExit("No saved held-out runs for both configurations yet.")
    coverage = json.loads(run_holdout.COVERAGE_PATH.read_text())
    report = build(rows, coverage, questions.load(run_holdout.QUESTIONS_PATH), part1_set())
    OUT.write_text(json.dumps(report, indent=1) + "\n")
    for name, block in report["configurations"].items():
        o = block["overall"]
        print(f"{name:15s} right {o['right']}/{o['runs']} ({o['right_pct']}%)"
              f"  wrong {o['confidently_wrong']}  declined {o['declined']}"
              f"  no answer {o['no_answer']}")  # fmt: skip
    print("change:", report["change_baseline_to_semantic_points"]["overall"])
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
