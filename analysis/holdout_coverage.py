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

"""What the frozen semantic layer can say about each held-out question.

Run before any agent sees the held-out set. For each of the 12 questions in
``questions/holdout.yaml`` it tries to reproduce the saved gold answer through
the semantic layer as it stands, calling ``semantic.run_metrics``: the function
behind the agent's ``query_metrics`` tool, with the tool's own limit of 50 rows.

Each question has a short list of attempts, written here by hand and tried in
order from the least work to the most. The first attempt that answers the
question as asked and whose value matches the gold answer, under the question's
own tolerance, gives the question its class:

    one_metric_query        one metric and a period, nothing else
    metric_plus_filter      one metric query with a filter, a grouping or a sort
                            on something the layer already accepts
    several_or_arithmetic   more than one metric query, or arithmetic on the rows
    not_answerable          no attempt reproduces the gold answer

Where a question names a carrier type, a customer or the like, the bare metric
for the whole company is also run as a control. It leaves out a condition of
the question, so it is never the class; if it lands inside the tolerance anyway
the question cannot tell a right reading from that wrong one, and that is
flagged.

This is a statement about the layer, not about the agent. It is written once,
before the runs, and is not adjusted afterward. It makes BigQuery calls and no
model call.

Usage:
    python analysis/holdout_coverage.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tessaway import questions, scoring  # noqa: E402 - the root has to be on the path first

HOLDOUT_PATH = ROOT / "questions" / "holdout.yaml"
GOLD_PATH = ROOT / "results" / "holdout" / "gold_answers.json"
OUT_JSON = ROOT / "results" / "holdout" / "coverage.json"
OUT_MD = ROOT / "results" / "holdout" / "coverage.md"

ONE = "one_metric_query"
FILTER = "metric_plus_filter"
SEVERAL = "several_or_arithmetic"
NONE = "not_answerable"
# An attempt that leaves out a condition the question states (the metric for the
# whole company, say). It is run to see what it returns and is never the class.
CONTROL = "control_drops_a_condition"
CLASSES = (ONE, FILTER, SEVERAL, NONE)
CLASS_LABEL = {
    ONE: "one metric query, as is",
    FILTER: "metric plus a filter or dimension the layer already has",
    SEVERAL: "needs more than one metric query or arithmetic on results",
    NONE: "not answerable from the layer",
}

Reply = dict[str, Any]
Runner = Callable[[dict[str, Any]], Reply]

Q2 = {"start_date": "2026-04-01", "end_date": "2026-06-30"}
Q3 = {"start_date": "2026-07-01", "end_date": "2026-09-30"}
H1_2026 = {"start_date": "2026-01-01", "end_date": "2026-06-30"}


def column(reply: Reply, name: str) -> list[Any]:
    """Return one column of a metric reply."""
    position = reply["columns"].index(name)
    return [row[position] for row in reply["rows"]]


def first(name: str) -> Callable[[list[Reply]], Any]:
    """Read the named column of the first row of the only reply."""
    return lambda replies: column(replies[0], name)[0]


def share_of_true(replies: list[Reply]) -> float:
    """Revenue on rows flagged true, as a percentage of revenue on all rows."""
    flags = column(replies[0], "tender__is_cross_border")
    values = [float(v) for v in column(replies[0], "revenue")]
    flagged = sum(v for flag, v in zip(flags, values, strict=True) if flag in (True, "true"))
    return 100 * flagged / sum(values)


def count_over_250k(replies: list[Reply]) -> int:
    """Count the customers whose revenue is above $250,000.

    The rows are sorted from high to low and cut at 50, so the count is only
    sound when the last row returned is already under the line.
    """
    values = [float(v) for v in column(replies[0], "revenue")]
    if replies[0].get("truncated") and values[-1] > 250000:
        raise ValueError("50 rows were not enough to reach the line")
    return sum(1 for v in values if v > 250000)


def top_five_share(replies: list[Reply]) -> float:
    """The five largest customers' revenue as a percentage of all revenue."""
    top = sum(float(v) for v in column(replies[0], "revenue"))
    return 100 * top / float(column(replies[1], "revenue")[0])


def weekend_total(replies: list[Reply]) -> int:
    """Add up delivered loads on the days that fall on a Saturday or a Sunday."""
    total = 0
    for reply in replies:
        if reply.get("truncated"):
            raise ValueError("a day was cut off by the 50-row limit")
        days = column(reply, "metric_time__day")
        for day, loads in zip(days, column(reply, "delivered_loads"), strict=True):
            if dt.date.fromisoformat(str(day)[:10]).weekday() >= 5:
                total += int(loads)
    return total


def difference(a: str, b: str) -> Callable[[list[Reply]], Any]:
    """Subtract one column of the first row from another."""
    return lambda replies: float(column(replies[0], a)[0]) - float(column(replies[0], b)[0])


# For each question: attempts in order, least work first. Each attempt is
# (class, what it is, the metric requests, how the answer is read from the rows).
Attempt = tuple[str, str, list[dict[str, Any]], Callable[[list[Reply]], Any]]

ATTEMPTS: dict[str, list[Attempt]] = {
    "H1": [
        (
            CONTROL,
            "the official rate for the period",
            [{"metrics": ["on_time_rate"], **Q2}],
            first("on_time_rate"),
        ),
        (
            FILTER,
            "the official rate, filtered to the own-fleet carrier type",
            [{"metrics": ["on_time_rate"], "where": ["tender__carrier_type = 'OWN'"], **Q2}],
            first("on_time_rate"),
        ),
    ],
    "H2": [
        (
            CONTROL,
            "margin percentage for the period",
            [{"metrics": ["margin_percentage"], **H1_2026}],
            first("margin_percentage"),
        ),
        (
            FILTER,
            "margin percentage, filtered to the outside-carrier type",
            [
                {
                    "metrics": ["margin_percentage"],
                    "where": ["tender__carrier_type = '3P'"],
                    **H1_2026,
                }
            ],
            first("margin_percentage"),
        ),
    ],
    "H3": [
        (
            SEVERAL,
            "revenue grouped by the cross-border flag, then one row over the sum",
            [{"metrics": ["revenue"], "group_by": ["tender__is_cross_border"], **Q3}],
            share_of_true,
        ),
    ],
    "H4": [
        (
            CONTROL,
            "margin per load for the period",
            [{"metrics": ["margin_per_load"], **Q3}],
            first("margin_per_load"),
        ),
        (
            FILTER,
            "margin per load, filtered to the reefer equipment type",
            [{"metrics": ["margin_per_load"], "where": ["tender__equipment_type = 'REEF'"], **Q3}],
            first("margin_per_load"),
        ),
    ],
    "H5": [
        (
            FILTER,
            "delivered loads grouped by customer, sorted high to low, first row",
            [
                {
                    "metrics": ["delivered_loads"],
                    "group_by": ["tender__customer_name"],
                    "order_by": ["-delivered_loads"],
                    "limit": 1,
                    **H1_2026,
                }
            ],
            first("tender__customer_name"),
        ),
    ],
    "H6": [
        (
            CONTROL,
            "customers that shipped in the period",
            [{"metrics": ["customers_shipped"], **Q3}],
            first("customers_shipped"),
        ),
        (
            SEVERAL,
            "revenue grouped by customer, sorted high to low, then count rows over the line",
            [
                {
                    "metrics": ["revenue"],
                    "group_by": ["tender__customer_name"],
                    "order_by": ["-revenue"],
                    **Q3,
                }
            ],
            count_over_250k,
        ),
    ],
    "H7": [
        (
            SEVERAL,
            "the top five customers by revenue, and total revenue, then a division",
            [
                {
                    "metrics": ["revenue"],
                    "group_by": ["tender__customer_name"],
                    "order_by": ["-revenue"],
                    "limit": 5,
                    **Q3,
                },
                {"metrics": ["revenue"], **Q3},
            ],
            top_five_share,
        ),
    ],
    "H8": [
        (
            CONTROL,
            "loads booked in the period",
            [{"metrics": ["loads_booked"], **H1_2026}],
            first("loads_booked"),
        ),
        (
            FILTER,
            "loads booked, filtered to the customer by name",
            [
                {
                    "metrics": ["loads_booked"],
                    "where": ["tender__customer_name = 'Kestrel Packaging'"],
                    **H1_2026,
                }
            ],
            first("loads_booked"),
        ),
    ],
    "H9": [
        (
            CONTROL,
            "delivered loads in the period",
            [{"metrics": ["delivered_loads"], **Q3}],
            first("delivered_loads"),
        ),
        (
            FILTER,
            "delivered loads, with a day-of-week expression on the metric's day as a filter",
            [
                {
                    "metrics": ["delivered_loads"],
                    "where": ["EXTRACT(DAYOFWEEK FROM metric_time__day) IN (1, 7)"],
                    **Q3,
                }
            ],
            first("delivered_loads"),
        ),
        (
            SEVERAL,
            "delivered loads by day in two halves (92 days, 50 rows a call), then add up"
            " the Saturdays and Sundays",
            [
                {
                    "metrics": ["delivered_loads"],
                    "group_by": ["metric_time__day"],
                    "order_by": ["metric_time__day"],
                    "start_date": "2026-07-01",
                    "end_date": "2026-08-15",
                },
                {
                    "metrics": ["delivered_loads"],
                    "group_by": ["metric_time__day"],
                    "order_by": ["metric_time__day"],
                    "start_date": "2026-08-16",
                    "end_date": "2026-09-30",
                },
            ],
            weekend_total,
        ),
    ],
    "H10": [
        (
            CONTROL,
            "official late deliveries in the period",
            [{"metrics": ["late_deliveries"], **Q3}],
            first("late_deliveries"),
        ),
        (
            FILTER,
            "delivered loads, filtered to not on time and shipper-delayed",
            [
                {
                    "metrics": ["delivered_loads"],
                    "where": [
                        "delivery__arrived_on_time = false",
                        "delivery__shipper_delayed = true",
                    ],
                    **Q3,
                }
            ],
            first("delivered_loads"),
        ),
        (
            SEVERAL,
            "delivered loads less the loads measured for on-time, in one query",
            [{"metrics": ["delivered_loads", "on_time_measured_loads"], **Q3}],
            difference("delivered_loads", "on_time_measured_loads"),
        ),
    ],
    "H11": [
        (
            CONTROL,
            "delivered loads that cannot be billed yet",
            [{"metrics": ["delivered_loads_not_billable"], **Q3}],
            first("delivered_loads_not_billable"),
        ),
        (
            FILTER,
            "delivered loads, filtered to no signed proof of delivery",
            [{"metrics": ["delivered_loads"], "where": ["delivery__has_signed_pod = false"], **Q3}],
            first("delivered_loads"),
        ),
    ],
    "H12": [
        (
            CONTROL,
            "the portal rate for the period",
            [{"metrics": ["portal_on_time_rate"], **Q3}],
            first("portal_on_time_rate"),
        ),
        (
            FILTER,
            "the portal rate, filtered to the customer by name",
            [
                {
                    "metrics": ["portal_on_time_rate"],
                    "where": ["tender__customer_name = 'Northgate Foods Group'"],
                    **Q3,
                }
            ],
            first("portal_on_time_rate"),
        ),
    ],
}

# Things a reader of the class should know, written before the runs.
NOTES = {
    "H4": "Flaw in the question, found here and left as it is: margin per load for the whole"
    " company in the quarter is within the question's 1% tolerance of the reefer answer, so the"
    " scorer cannot tell an answer that ignores 'reefer' from a right one. The whole-company"
    " reading is not among the question's decoys.",
    "H9": "The filter is a SQL day-of-week expression on the metric's own day, which MetricFlow"
    " accepts. The layer has no day-of-week dimension; an agent has to think of the expression"
    " or fetch the days and count.",
}

# Why a question with no matching attempt cannot be answered, said once here.
NOT_ANSWERABLE_NOTE = {
    "H11": "The layer knows whether a signed proof of delivery is on file"
    " (delivery__has_signed_pod). It has no metric and no dimension for whether any"
    " proof-of-delivery document is on file, so it cannot separate loads with unsigned"
    " paperwork from loads with none.",
}


def matches(question: questions.Question, gold: Any, value: Any) -> bool:
    """Say whether a value is the gold answer, by the scorer's own rules."""
    if value is None:
        return False
    if question.answer_type == "text":
        accept = question.accept or (str(gold),)
        return scoring._text_matches(str(value), accept, question.reject)
    return scoring.numbers_match(
        float(value), float(gold), question.tolerance_kind, question.tolerance_value
    )


def classify(
    question: questions.Question, gold: Any, attempts: list[Attempt], run: Runner
) -> dict[str, Any]:
    """Try each attempt in order and return the question's class with the evidence."""
    tried: list[dict[str, Any]] = []
    chosen: dict[str, Any] | None = None
    for kind, what, requests, read in attempts:
        entry: dict[str, Any] = {"class": kind, "what": what, "requests": requests}
        replies = [run(request) for request in requests]
        errors = [str(r["error"])[:400] for r in replies if "error" in r]
        value: Any = None
        if errors:
            entry["error"] = errors[0]
        else:
            entry["rows_returned"] = [r["row_count"] for r in replies]
            try:
                value = read(replies)
            except (ValueError, IndexError, ZeroDivisionError) as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
        if isinstance(value, float):
            value = round(value, 4)
        entry["value"] = value
        entry["matches_gold"] = matches(question, gold, value)
        tried.append(entry)
        if entry["matches_gold"] and chosen is None and kind != CONTROL:
            chosen = entry
    control_hits = [e for e in tried if e["class"] == CONTROL and e["matches_gold"]]
    kind = chosen["class"] if chosen else NONE
    return {
        "question_id": question.id,
        "group": question.group,
        "question": question.question,
        "gold": gold,
        "class": kind,
        "class_label": CLASS_LABEL[kind],
        "metric_queries_needed": len(chosen["requests"]) if chosen else None,
        "query_used": chosen["requests"] if chosen else None,
        "how": chosen["what"] if chosen else NOT_ANSWERABLE_NOTE.get(question.id, ""),
        "value_from_the_layer": chosen["value"] if chosen else None,
        "note": NOTES.get(question.id, ""),
        "a_query_that_drops_a_condition_also_scores_right": bool(control_hits),
        "value_of_that_query": control_hits[0]["value"] if control_hits else None,
        "attempts": tried,
    }


def metric_runner() -> Runner:
    """Return a runner that calls the semantic layer the way the agent's tool does."""
    from tessaway.layers import semantic

    def run(request: dict[str, Any]) -> Reply:
        return semantic.run_metrics(
            list(request["metrics"]),
            request.get("group_by"),
            request.get("where"),
            request.get("start_date", ""),
            request.get("end_date", ""),
            request.get("order_by"),
            request.get("limit", 50),
        )

    return run


def build(run: Runner) -> dict[str, Any]:
    """Classify every held-out question."""
    gold = questions.load_gold(GOLD_PATH)
    results = [
        classify(q, gold[q.id]["gold"], ATTEMPTS[q.id], run) for q in questions.load(HOLDOUT_PATH)
    ]
    return {
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "what": "For each held-out question, the least work through the semantic layer, as it"
        " stood before any held-out agent run, that reproduces the saved gold answer. Metric"
        " requests go through semantic.run_metrics, the function behind the agent's"
        " query_metrics tool, with its limit of 50 rows.",
        "classes": CLASS_LABEL,
        "counts": {kind: sum(1 for r in results if r["class"] == kind) for kind in CLASSES},
        "questions_where_dropping_a_condition_still_scores_right": [
            r["question_id"]
            for r in results
            if r["a_query_that_drops_a_condition_also_scores_right"]
        ],
        "by_class": {
            kind: [r["question_id"] for r in results if r["class"] == kind] for kind in CLASSES
        },
        "questions": results,
    }


def to_markdown(report: dict[str, Any]) -> str:
    """Write the short coverage note."""
    lines = [
        "# Held-out set: what the semantic layer covers",
        "",
        "Written by `analysis/holdout_coverage.py` before any agent ran on the held-out"
        " questions. It is a statement about the layer as it stood, not about the agent, and"
        " it is not adjusted after the runs.",
        "",
        "For each question the script tried a short list of metric requests, least work first,"
        " through the same function the agent's `query_metrics` tool calls. The class is the"
        " first attempt that answers the question as asked and reproduced the saved gold"
        " answer within the question's own tolerance. The bare metric with the question's"
        " condition left out was also run as a control and is never the class. Every attempt,"
        " with the value it returned, is in `coverage.json`.",
        "",
        "| Class | Questions | Which |",
        "| --- | --- | --- |",
    ]
    for kind in CLASSES:
        ids = report["by_class"][kind]
        lines.append(f"| {CLASS_LABEL[kind]} | {len(ids)} | {', '.join(ids) or 'none'} |")
    lines += [
        "",
        "| Question | Group | Class | Metric queries | How | Layer value | Gold |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["questions"]:
        lines.append(
            f"| {r['question_id']} | {r['group']} | {r['class_label']}"
            f" | {r['metric_queries_needed'] or 'n/a'} | {r['how']}"
            f" | {r['value_from_the_layer'] if r['class'] != NONE else 'n/a'} | {r['gold']} |"
        )
    lines += ["", "## Notes", ""]
    for r in report["questions"]:
        if r["note"]:
            lines.append(f"- {r['question_id']}: {r['note']}")
        if r["class"] == NONE:
            lines.append(f"- {r['question_id']}: {r['how']}")
        if r["a_query_that_drops_a_condition_also_scores_right"]:
            lines.append(
                f"- {r['question_id']}: the bare metric with the question's condition left out"
                f" returns {r['value_of_that_query']}, which the scorer accepts against a gold"
                f" answer of {r['gold']}."
            )
    lines += [
        "",
        "No question is a bare metric over a period: each names a carrier type, an equipment"
        " type, a customer, a threshold, a ranking, a weekday or a cause. That is why the"
        " first class is empty.",
        "",
        "For comparison: on the 24 Part 1 questions, one metric query reproduces the gold"
        " answer to all 18 questions outside the lookup group"
        " (`results/part2/semantic_gold_check.json`). Those checks allowed a filter, a grouping"
        " or a sort, so they span the first two classes here.",
        "",
        "The attempts were written by hand by someone who could read the layer. An agent has"
        " to find the same route from the tool description alone. A question in the third"
        " class can still be answered with the SQL tool, and so can one in the fourth.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    """Run the coverage check and save it."""
    if OUT_JSON.exists() and "--force" not in sys.argv[1:]:
        raise SystemExit(
            f"{OUT_JSON.relative_to(ROOT)} exists. It is written once, before the runs."
        )
    report = build(metric_runner())
    OUT_JSON.write_text(json.dumps(report, indent=1, default=str) + "\n")
    OUT_MD.write_text(to_markdown(report))
    for r in report["questions"]:
        print(f"{r['question_id']:4s} {r['class']:22s} layer={r['value_from_the_layer']!s:>24}"
              f"  gold={r['gold']}")  # fmt: skip
        for attempt in r["attempts"]:
            print(f"       {attempt['class']:22s} {attempt['value']!s:>22}"
                  f" {'match' if attempt['matches_gold'] else '     '}"
                  f" {attempt.get('error', '')[:90]}")  # fmt: skip
    print(report["counts"])


if __name__ == "__main__":
    main()
