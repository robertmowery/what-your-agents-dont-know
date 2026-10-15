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

"""Derive the figures quoted in the Part 2 articles from the saved runs.

``run_part2.py`` writes one line per run to ``results/part2/runs``, and Part 1
left its Flash runs in ``results/part1/runs``. This script reads those lines,
makes no model or cloud call, and writes ``results/part2/article_numbers.json``.
Every number in the Part 2 articles that is not already in ``summary.md`` is in
that file. Replies and SQL are not copied into it: a run is named by its
question and trial, and the text stays in the runs files.

The predictions are read against the runs by the rules written down in
``results/part2/predictions.md`` before any run.

Usage:
    python analysis/part2_article_numbers.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_part2  # noqa: E402 - the repository root has to be on the path first
from tessaway import questions  # noqa: E402
from tessaway.agents import layer_prompt, prompt  # noqa: E402

PART2_RUNS = ROOT / "results" / "part2" / "runs"
PART1_RUNS = ROOT / "results" / "part1" / "runs" / "adk_gemini_flash.jsonl"
OUT = ROOT / "results" / "part2" / "article_numbers.json"

BINS = ("right", "confidently_wrong", "declined", "no_answer")
GROUPS = ("lookup", "metric", "entity", "rule")
RUNS_PER_QUESTION = 3
# Questions whose individual answers the articles discuss: on-time, loads
# booked, customer count, largest customer, margin per load, revenue, late deliveries.
DISCUSSED = ("M1", "E4", "E2", "E1", "M3", "M2", "R1")
# The group the brief predicts each single layer moves.
PREDICTED_GROUP = {
    "flash_semantic": "metric",
    "flash_ontology": "rule",
    "flash_graph": "entity",
}
SINGLE = tuple(PREDICTED_GROUP)


def load(path: Path, max_trial: int | None = None) -> list[dict[str, Any]]:
    """Return one row per question and trial, keeping the last attempt of each."""
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    with path.open() as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if max_trial is None or row["trial"] < max_trial:
                    latest[(row["question_id"], row["trial"])] = row
    return [latest[key] for key in sorted(latest)]


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
    return round(sum(float(row.get(key) or 0) for row in rows) / len(rows), digits) if rows else 0.0


def points(now: dict[str, Any], before: dict[str, Any]) -> dict[str, float]:
    """Change in each bin's share, in percentage points, from the counts."""
    return {
        name: round(100 * (now[name] / now["runs"] - before[name] / before["runs"]), 1)
        for name in BINS[:3]
    }


def effort(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Queries, tokens, time and cost per question."""
    total_in = sum(row["input_tokens_total"] for row in rows)
    return {
        "mean_sql_queries": mean(rows, "query_count", 2),
        "mean_model_calls": mean(rows, "model_calls", 2),
        "mean_input_tokens": round(mean(rows, "input_tokens_total", 0)),
        "mean_output_tokens": round(mean(rows, "output_tokens", 0)),
        "cache_read_share_of_input_pct": round(
            100 * sum(row["cache_read_tokens"] for row in rows) / total_in, 1
        ),
        "mean_seconds": mean(rows, "seconds", 1),
        "mean_cost_usd": mean(rows, "cost_usd"),
        "cost_usd": round(sum(row["cost_usd"] for row in rows), 2),
        "mean_cost_usd_by_group": {
            group: mean([row for row in rows if row["group"] == group], "cost_usd")
            for group in GROUPS
        },
        "cost_usd_per_right_answer": round(
            sum(row["cost_usd"] for row in rows)
            / max(1, sum(1 for row in rows if row["outcome"] == "right")),
            4,
        ),
    }


def discussed(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Outcomes and the answers given, for the questions the articles discuss."""
    result = {}
    for qid in DISCUSSED:
        mine = [row for row in rows if row["question_id"] == qid]
        result[qid] = {
            "gold": mine[0]["gold"],
            **counts(mine),
            "answers_given": dict(
                Counter(str(row["extracted"]) for row in mine if row["outcome"] != "declined")
            ),
            "wrong_readings_matched": dict(
                Counter(row["matched_decoy"] for row in mine if row["matched_decoy"])
            ),
        }
    return result


def instructive_wrong_answers(rows: list[dict[str, Any]], layers: tuple[str, ...]) -> list[Any]:
    """Pick three confidently wrong runs that show the most, by a fixed rule.

    A run that called a layer tool and was still wrong comes first, then a run
    whose answer matches a named wrong reading, then question and trial order.
    At most one run per question, so three different questions are shown.
    """
    layer_tools = {layer_prompt.TOOL_OF_LAYER[layer] for layer in layers}
    wrong = [row for row in rows if row["outcome"] == "confidently_wrong"]
    wrong.sort(
        key=lambda row: (
            not any(tool in layer_tools for tool in row["tools_in_order"]),
            not row["matched_decoy"],
            row["question_id"],
            row["trial"],
        )
    )
    chosen: list[dict[str, Any]] = []
    for row in wrong:
        if row["question_id"] in {c["question_id"] for c in chosen}:
            continue
        chosen.append(
            {
                "question_id": row["question_id"],
                "trial": row["trial"],
                "answered": row["extracted"],
                "gold": row["gold"],
                "wrong_reading_matched": row["matched_decoy"],
                "said_it_was_assuming": row["flagged_assumption"],
                "tools_in_order": row["tools_in_order"],
                "tool_call_counts": row["tool_call_counts"],
                "ontology_terms_matched": [
                    call.get("matches", [])
                    for call in row["tool_calls"]
                    if call["tool"] == layer_prompt.ONTOLOGY_TOOL and not call.get("refused")
                ],
                "metrics_asked_for": [
                    call["arguments"]["metrics"]
                    for call in row["tool_calls"]
                    if call["tool"] == layer_prompt.SEMANTIC_TOOL and not call.get("refused")
                ],
                "where": f"results/part2/runs/{row['config']}.jsonl",
            }
        )
        if len(chosen) == 3:
            break
    return chosen


def describe(name: str, rows: list[dict[str, Any]], base: dict[str, Any]) -> dict[str, Any]:
    """Everything the articles quote about one Part 2 configuration."""
    layers = run_part2.LAYER_CONFIGS[name]
    by_id = {q.id: q for q in questions.load()}
    needing = [row for row in rows if row["group"] != "lookup"]
    by_group = {group: counts([r for r in rows if r["group"] == group]) for group in GROUPS}
    use = run_part2.tool_use(rows, layers, by_id)
    return {
        "layers": list(layers),
        "tools": [prompt.TOOL_NAME, *(layer_prompt.TOOL_OF_LAYER[layer] for layer in layers)],
        "model": rows[0]["model"],
        "runs_per_question": RUNS_PER_QUESTION,
        "complete": len(rows) == RUNS_PER_QUESTION * len(by_id),
        "all_questions": counts(rows),
        "questions_needing_a_definition": counts(needing),
        "by_group": by_group,
        "change_vs_baseline_points": {
            "all_questions": points(counts(rows), base["all_questions"]),
            "questions_needing_a_definition": points(
                counts(needing), base["questions_needing_a_definition"]
            ),
            **{group: points(by_group[group], base["by_group"][group]) for group in GROUPS},
        },
        "by_question": {
            qid: counts([row for row in rows if row["question_id"] == qid]) for qid in sorted(by_id)
        },
        "questions_right_in_every_run": sorted(
            qid
            for qid in by_id
            if all(r["outcome"] == "right" for r in rows if r["question_id"] == qid)
        ),
        "questions_never_right": sorted(
            qid
            for qid in by_id
            if not any(r["outcome"] == "right" for r in rows if r["question_id"] == qid)
        ),
        "discussed_questions": discussed(rows),
        "effort": effort(rows),
        "tool_use": use,
        "tool_use_by_group": {
            group: run_part2.tool_use([r for r in rows if r["group"] == group], layers, by_id)
            for group in GROUPS
        },
        "limits": run_part2.limits(rows),
        "wrong_answers": sum(1 for row in rows if row["outcome"] == "confidently_wrong"),
        "wrong_answers_matching_a_named_wrong_reading": sum(
            1 for row in rows if row["outcome"] == "confidently_wrong" and row["matched_decoy"]
        ),
        "wrong_answers_that_flagged_an_assumption": sum(
            1 for row in rows if row["outcome"] == "confidently_wrong" and row["flagged_assumption"]
        ),
        "wrong_answers_after_calling_a_layer_tool": sum(
            1
            for row in rows
            if row["outcome"] == "confidently_wrong"
            and any(tool != prompt.TOOL_NAME for tool in row["tools_in_order"])
        ),
        "sql_that_read_the_semantic_layer_views": sum(
            1
            for row in rows
            if any("tessaway_sem" in str(q.get("sql", "")).lower() for q in row["queries"])
        ),
        "three_most_instructive_wrong_answers": instructive_wrong_answers(rows, layers),
    }


def describe_baseline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The Part 1 Flash result, in the same shape."""
    ids = sorted({row["question_id"] for row in rows})
    return {
        "what": "Part 1, adk_gemini_flash, ten runs per question. Not run again.",
        "layers": [],
        "tools": [prompt.TOOL_NAME],
        "model": rows[0]["model"],
        "runs_per_question": 10,
        "all_questions": counts(rows),
        "questions_needing_a_definition": counts([r for r in rows if r["group"] != "lookup"]),
        "by_group": {group: counts([r for r in rows if r["group"] == group]) for group in GROUPS},
        "by_question": {qid: counts([r for r in rows if r["question_id"] == qid]) for qid in ids},
        "discussed_questions": discussed(rows),
        "effort": effort(rows),
        "wrong_answers": sum(1 for row in rows if row["outcome"] == "confidently_wrong"),
    }


def read_predictions(data: dict[str, Any]) -> dict[str, Any]:
    """Read each prediction against the runs, by the rules in predictions.md."""
    two_runs_in_a_group = round(100 * 2 / 18, 1)  # 11.1 points
    two_runs_overall = round(100 * 2 / 72, 1)  # 2.8 points
    verdicts: dict[str, Any] = {
        "rules": "results/part2/predictions.md, written before any run",
        "two_runs_in_a_group_points": two_runs_in_a_group,
        "two_runs_overall_points": two_runs_overall,
    }
    most_raised = {}
    for name in SINGLE:
        change = data[name]["change_vs_baseline_points"]
        gains = {group: change[group]["right"] for group in ("metric", "entity", "rule")}
        top = max(gains.values())
        raised_most = sorted(group for group, gain in gains.items() if gain == top)
        most_raised[name] = raised_most
        predicted = PREDICTED_GROUP[name]
        verdicts[f"{name}_moves_the_{predicted}_group"] = {
            "right_change_points_by_group": gains,
            "confidently_wrong_change_points_by_group": {
                group: change[group]["confidently_wrong"] for group in ("metric", "entity", "rule")
            },
            "predicted_group": predicted,
            "predicted_group_gain_points": gains[predicted],
            "group_raised_most": raised_most,
            "groups_raised_by_more_than_two_runs": sorted(
                group for group, gain in gains.items() if gain > two_runs_in_a_group
            ),
            "holds": gains[predicted] > two_runs_in_a_group and raised_most == [predicted],
        }
    verdicts["lookups_stay_where_they_are"] = {
        "right_of_18_by_configuration": {
            name: data[name]["by_group"]["lookup"]["right"] for name in run_part2.LAYER_CONFIGS
        },
        "holds": all(
            data[name]["by_group"]["lookup"]["right"] >= 17 for name in run_part2.LAYER_CONFIGS
        ),
    }
    verdicts["each_layer_fixes_a_different_kind_of_wrong_answer"] = {
        "group_raised_most_by_configuration": most_raised,
        "holds": all(len(groups) == 1 for groups in most_raised.values())
        and len({groups[0] for groups in most_raised.values()}) == 3,
    }
    verdicts["no_single_layer_closes_all_of_the_gap"] = {
        "right_of_54_outside_lookups": {
            name: data[name]["questions_needing_a_definition"]["right"] for name in SINGLE
        },
        "holds": all(data[name]["questions_needing_a_definition"]["right"] < 54 for name in SINGLE),
    }
    best = max(SINGLE, key=lambda name: data[name]["all_questions"]["right_pct"])
    together, alone = data["flash_all_three"]["all_questions"], data[best]["all_questions"]
    verdicts["all_three_beat_the_best_single_layer"] = {
        "best_single_layer": best,
        "best_single_layer_right_pct": alone["right_pct"],
        "all_three_right_pct": together["right_pct"],
        "difference_points": round(together["right_pct"] - alone["right_pct"], 1),
        "best_single_layer_confidently_wrong_pct": alone["confidently_wrong_pct"],
        "all_three_confidently_wrong_pct": together["confidently_wrong_pct"],
        "holds": together["right_pct"] - alone["right_pct"] > two_runs_overall
        and together["confidently_wrong_pct"] <= alone["confidently_wrong_pct"],
    }
    return verdicts


def quoted_runs() -> dict[str, Any]:
    """The runs the articles quote, located by configuration, question and trial.

    The text stays in the runs files; this names where it is and the facts the
    articles state about it, so a reader can check the quote.
    """
    quotes = {}
    for key, name, qid, trial in (
        ("ontology_read_the_definition_and_declined", "flash_ontology", "M1", 2),
        ("semantic_layer_answered", "flash_semantic", "M1", 2),
    ):
        row = next(
            r for r in load(PART2_RUNS / f"{name}.jsonl", RUNS_PER_QUESTION)
            if r["question_id"] == qid and r["trial"] == trial
        )  # fmt: skip
        quotes[key] = {
            "where": f"results/part2/runs/{name}.jsonl",
            "question_id": qid,
            "trial": trial,
            "outcome": row["outcome"],
            "answered": row["extracted"],
            "gold": row["gold"],
            "tool_call_counts": row["tool_call_counts"],
            "queries_refused_over_limit": row["queries_refused_over_limit"],
            "mentions_query_limit": row["mentions_query_limit"],
        }
    return quotes


def ontology_declines() -> dict[str, Any]:
    """How the ontology configuration's declines came about.

    A decline "read the ontology first" when the run called ``lookup_ontology``
    at least once before it gave up. On the on-time question (M1), a decline
    "states the official definition" when its reply names the official or
    contract definition, which the ontology holds as ``tw:OnTime``.
    """
    rows = load(PART2_RUNS / "flash_ontology.jsonl", RUNS_PER_QUESTION)
    declined = [r for r in rows if r["outcome"] == "declined"]
    m1 = [r for r in declined if r["question_id"] == "M1"]
    return {
        "declines": len(declined),
        "declines_after_reading_the_ontology": sum(
            1 for r in declined if layer_prompt.ONTOLOGY_TOOL in r["tools_in_order"]
        ),
        "declines_that_mention_the_query_limit": sum(
            1 for r in declined if r["mentions_query_limit"]
        ),
        "declines_refused_a_ninth_query": sum(
            1 for r in declined if r["queries_refused_over_limit"] > 0
        ),
        "m1_runs": sum(1 for r in rows if r["question_id"] == "M1"),
        "m1_declines": len(m1),
        "m1_declines_that_state_the_official_definition": sum(
            1
            for r in m1
            if "official" in r["answer_text"].lower() or "contract" in r["answer_text"].lower()
        ),
    }


def holdout_beside_part2() -> dict[str, Any]:
    """The fairness test beside the 24 Part 1 questions, as Fig. 2.3 draws it."""
    holdout = json.loads((ROOT / "results" / "holdout" / "article_numbers.json").read_text())
    side = holdout["side_by_side"]
    return {
        "source": "results/holdout/article_numbers.json (side_by_side)",
        "held_out_12_questions": side["held_out_12_questions"],
        "all_24_questions": side["all_24_questions"],
    }


def main() -> None:
    """Write the derived figures."""
    base = describe_baseline(load(PART1_RUNS))
    data: dict[str, Any] = {
        "note": (
            "The baseline is Part 1's Flash configuration at ten runs per question. Part 2"
            " ran each question three times per configuration: one run is 1.4 points of an"
            " overall share and 5.6 points within a question group. Small differences are"
            " not findings."
        ),
        "baseline": base,
    }
    missing = []
    for name in run_part2.LAYER_CONFIGS:
        path = PART2_RUNS / f"{name}.jsonl"
        if not path.exists():
            missing.append(name)
            continue
        data[name] = describe(name, load(path, RUNS_PER_QUESTION), base)
    data["not_run"] = missing
    if not missing:
        data["predictions"] = read_predictions(data)
        data["all_new_runs"] = {
            "runs": sum(data[name]["all_questions"]["runs"] for name in run_part2.LAYER_CONFIGS),
            "cost_usd": round(
                sum(data[name]["effort"]["cost_usd"] for name in run_part2.LAYER_CONFIGS), 2
            ),
        }
        data["quoted_runs"] = quoted_runs()
        data["ontology_declines"] = ontology_declines()
        data["semantic_layer_against_baseline_cost_cents"] = {
            "baseline": round(100 * base["effort"]["mean_cost_usd"], 2),
            "flash_semantic": round(100 * data["flash_semantic"]["effort"]["mean_cost_usd"], 2),
        }
        data["fairness_test"] = holdout_beside_part2()
    spend_path = ROOT / "results" / "series_spend.json"
    if spend_path.exists():
        data["spend"] = json.loads(spend_path.read_text())
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
