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

"""Derive the figures the Part 3 articles would quote.

Reads ``results/part3/summary.json``, the saved runs under
``results/part3/runs`` and, for the side-by-side, ``results/part2/summary.json``.
Makes no model or cloud call. Writes ``results/part3/article_numbers.json``.

Beyond the summary it works out one thing the brief flagged as unmeasured:
order. In a run that called both ``compute_metric`` and ``run_sql``, which came
first. "Then it checked against SQL" needs the metric first; the figures say
how often that held. It also reads whether the final replies of those runs say
why SQL was run, and finds contract calls whose metric filter carried SQL (a
subquery or a forced error) instead of a filter.

The Claude demonstration is reported only as whether it worked, which
operations it called, and what it cost. No answer of it is scored or counted.

Usage:
    python analysis/part3_article_numbers.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_part2  # noqa: E402 - the repository root has to be on the path first
import run_part3  # noqa: E402
from tessaway import questions  # noqa: E402

PART3 = ROOT / "results" / "part3"
OUT = PART3 / "article_numbers.json"
PART2_SUMMARY = ROOT / "results" / "part2" / "summary.json"
SQL, METRIC = "run_sql", "compute_metric"


def order(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """In runs that called both the metric operation and SQL, which came first."""
    both = [r for r in rows if METRIC in r["tools_in_order"] and SQL in r["tools_in_order"]]
    metric_first = sum(
        1 for r in both if r["tools_in_order"].index(METRIC) < r["tools_in_order"].index(SQL)
    )
    return {
        "runs_that_called_both": len(both),
        "metric_first_then_sql": metric_first,
        "sql_first_then_metric": len(both) - metric_first,
    }


# Words a final reply would use if it said it ran SQL to check the contract's number.
CHECK_WORDS = re.compile(
    r"verif|confirm|cross-?check|double-?check|sanity|validat|corroborat|\bcheck", re.I
)
# A metric filter that carries more than a filter: a subquery, a forced error, the catalog.
SQL_IN_FILTER = re.compile(r"\bselect\b|\berror\s*\(|information_schema", re.I)
FILTER_ARGS = ("where", "group_by", "order_by")


def stated_reason(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """In runs that called both the metric operation and SQL, does the reply say why.

    Only the final reply is saved; the model's text between calls is not, so
    this reads the final reply alone.
    """
    both = [r for r in rows if METRIC in r["tools_in_order"] and SQL in r["tools_in_order"]]
    naming = [
        {"question_id": r["question_id"], "trial": r["trial"]}
        for r in both
        if CHECK_WORDS.search(r["answer_text"])
    ]
    return {
        "what": "Runs that called both, and how many final replies use a word such as verify,"
        " confirm, check, cross-check or validate. The run record keeps the final reply only.",
        "runs_that_called_both": len(both),
        "replies_that_name_a_check": len(naming),
        "which": naming,
    }


def sql_through_the_filter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Contract calls whose filter arguments carried SQL beyond a metric filter."""
    runs = []
    for r in rows:
        calls = []
        for c in r["tool_calls"]:
            if c["tool"] != METRIC:
                continue
            args = c.get("arguments") or {}
            carried = json.dumps({k: args.get(k) for k in FILTER_ARGS})
            if not SQL_IN_FILTER.search(carried):
                continue
            calls.append(
                {
                    "seq": c.get("seq"),
                    "where": args.get("where"),
                    "refused_at_the_call_limit": bool(c.get("refused")),
                    "error_returned": c.get("error", ""),
                    "rows_returned": (c.get("result") or {}).get("rows")
                    if isinstance(c.get("result"), dict)
                    else None,
                }
            )
        if calls:
            runs.append(
                {
                    "question_id": r["question_id"],
                    "trial": r["trial"],
                    "outcome": r.get("outcome", "not scored"),
                    "final_answer": r.get("extracted", ""),
                    "answer_source": r.get("answer_source", ""),
                    "metric_calls_in_run": sum(1 for c in r["tool_calls"] if c["tool"] == METRIC),
                    "calls": calls,
                }
            )
    return {
        "runs": len(runs),
        "calls": sum(len(x["calls"]) for x in runs),
        "calls_that_ran": sum(
            1 for x in runs for c in x["calls"] if not c["refused_at_the_call_limit"]
        ),
        "detail": runs,
    }


def reply_tail(rows: list[dict[str, Any]], qid: str, trial: int, chars: int = 600) -> dict[str, Any]:
    """The end of one saved reply, verbatim, for quoting."""
    r = next(x for x in rows if x["question_id"] == qid and x["trial"] == trial)
    return {
        "question_id": qid,
        "trial": trial,
        "outcome": r["outcome"],
        "answer_source": r["answer_source"],
        "final_answer": r["extracted"],
        "gold": r["gold"],
        "operations_called": r["tools_in_order"],
        "reply_tail": r["answer_text"].strip()[-chars:],
    }


def example(rows: list[dict[str, Any]], qid: str) -> dict[str, Any] | None:
    """One real run, for the article's example of what routing breaks."""
    picked = sorted((r for r in rows if r["question_id"] == qid), key=lambda r: r["trial"])
    if not picked:
        return None
    r = picked[0]
    text = r["answer_text"].strip()
    every = {q.id: q for q in [*questions.load(), *questions.load(run_part3.HOLDOUT_QUESTIONS)]}
    return {
        "question_id": qid,
        "question": every[qid].question,
        "trial": r["trial"],
        "outcome": r["outcome"],
        "final_answer": r["extracted"],
        "operations_called": r["tools_in_order"],
        "reply_last_400_chars": text[-400:],
    }


def part2_figures() -> dict[str, Any]:
    """The Part 2 all-three figures the article sets beside Part 3."""
    if not PART2_SUMMARY.exists():
        return {}
    summary = json.loads(PART2_SUMMARY.read_text())
    block = next((b for b in summary["configurations"] if b["config"] == "flash_all_three"), None)
    if block is None:
        return {}
    around = block["tool_use"].get("went_around_the_semantic_layer", {})
    return {
        "config": "flash_all_three",
        "right": block["summary"]["overall"]["right"],
        "runs": block["summary"]["overall"]["runs"],
        "metric_question_runs": around.get("runs_on_such_questions"),
        "ran_sql_beside_the_metric": around.get("runs_that_ran_sql"),
        "never_called_the_metric_tool": around.get("of_which_never_called_the_metric_tool"),
        "mean_cost_usd": block["effort"]["mean_cost_usd"],
        "mean_sql_queries": block["effort"]["mean_sql_queries"],
    }


def main() -> None:
    """Write article_numbers.json."""
    summary = json.loads((PART3 / "summary.json").read_text())
    rows = {name: run_part3.rows_in(PART3 / "runs" / f"{name}.jsonl") for name in run_part3.CONFIGS}
    blocks = summary["configurations"]
    available, routed, holdout = (
        rows[run_part3.AVAILABLE],
        rows[run_part3.ROUTED],
        rows[run_part3.ROUTED_HOLDOUT],
    )
    by_id = {q.id: q for q in questions.load()}
    metric_questions = [
        r for r in available if run_part2.applies_to("semantic", by_id[r["question_id"]])
    ]
    claude = run_part3.rows_in(PART3 / "runs" / "claude_demo.jsonl")
    numbers: dict[str, Any] = {
        "what": "Figures for the Part 3 articles, derived from results/part3. Three runs per"
        " question; small differences are not findings.",
        "contract_version": summary["contract_version"],
        "outcomes": {
            name: {
                "runs": b["summary"]["overall"]["runs"],
                **{k: b["summary"]["overall"][k] for k in run_part3.scoring.BINS},
                "by_group": {
                    g: {k: v[k] for k in ("runs", *run_part3.scoring.BINS)}
                    for g, v in b["summary"]["by_group"].items()
                },
            }
            for name, b in blocks.items()
        },
        "answer_source": {name: b["answer_source"] for name, b in blocks.items()},
        "answer_source_by_group": {name: b["answer_source_by_group"] for name, b in blocks.items()},
        "tool_use": {name: b["tool_use"] for name, b in blocks.items()},
        "order_in_available_runs": {
            "all_runs": order(available),
            "questions_one_metric_answers": order(metric_questions),
        },
        "cost_of_the_second_route": {
            name: {
                k: b["effort"][k]
                for k in (
                    "mean_sql_queries",
                    "mean_input_tokens",
                    "mean_output_tokens",
                    "mean_seconds",
                    "mean_cost_usd",
                    "total_cost_usd",
                )
            }
            for name, b in blocks.items()
        },
        "why_it_ran_sql": stated_reason(available),
        "sql_through_the_metric_filter": {
            name: sql_through_the_filter(rows[name]) for name in run_part3.CONFIGS
        }
        | {"claude_demo": sql_through_the_filter(claude)},
        "quoted_replies": {
            "available_M1_metric_first_then_sql": reply_tail(available, "M1", 1),
            "routed_L4_declined": reply_tail(routed, "L4", 0),
            "routed_L6_sql_in_the_filter": reply_tail(routed, "L6", 1),
            "routed_holdout_H10_wrong": reply_tail(holdout, "H10", 0),
            "routed_holdout_H10_wrong_2": reply_tail(holdout, "H10", 1),
            "routed_holdout_H11_declined": reply_tail(holdout, run_part3.NOT_ANSWERABLE, 0),
        },
        "routed_lookups_right": [
            {"question_id": r["question_id"], "trial": r["trial"], "source": r["answer_source"]}
            for r in routed
            if r["group"] == "lookup" and r["outcome"] == "right"
        ],
        "predictions_note": "P12 held only after a labeling correction made after the runs:"
        " one call the MCP layer refused (E6, invalid arguments, no response ID, no log line) was"
        " first counted as a cut-off call and failed P12; it is now counted apart, and P12 is"
        " tested by its written rule (results/part3/run_log.md). Held as written: P1-P4, P6-P11.",
        "predictions_held_as_written": sum(
            1 for p in summary["predictions"] if p["held"] and p["prediction"] != "P12"
        ),
        "where_routing_breaks": summary["where_routing_breaks"],
        "examples": {
            "routed_lookup": example(routed, "L4"),
            "routed_h11": example(holdout, run_part3.NOT_ANSWERABLE),
        },
        "versions": {name: b["versions"] for name, b in blocks.items()},
        "server_log_check": {
            k: v for k, v in (summary.get("server_log_check") or {}).items() if k != "problems"
        },
        "auth_check": summary.get("auth_check"),
        "predictions": summary["predictions"],
        "predictions_held": sum(1 for p in summary["predictions"] if p["held"]),
        "predictions_tested": sum(1 for p in summary["predictions"] if p["held"] is not None),
        "part2_side_by_side": part2_figures(),
        "spend": summary["spend"],
        "claude_demonstration": {
            "scored": False,
            "configuration": "available (contract over HTTP and the SQL tool)",
            "questions_run": len(claude),
            "runs_that_called_the_contract_without_an_error": sum(
                1 for r in claude if r["contract_calls"] and not r["error"] and not r["timed_out"]
            ),
            "operations_called": dict(
                Counter(
                    c["tool"]
                    for r in claude
                    for c in r["tool_calls"]
                    if c["tool"] in run_part3.OPERATIONS
                )
            ),
            "sql_queries": sum(r["sql_queries"] for r in claude),
            "cost_usd_list_price_estimate": round(sum(float(r["cost_usd"]) for r in claude), 4),
            "cost_usd_reported_by_the_sdk": round(
                sum(float(r.get("sdk_reported_cost_usd") or 0) for r in claude), 4
            ),
        },
    }
    OUT.write_text(json.dumps(numbers, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
