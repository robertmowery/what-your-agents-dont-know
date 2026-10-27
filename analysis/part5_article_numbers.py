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

"""Derive the figures the Part 5 articles quote.

Reads ``results/part5/summary.json``, the saved runs, traces and alerts under
``results/part5``, the drift records in ``results/part5/drift``, the frozen
golden set, the definition registry and ``results/series_spend.json``. Runs
the data generator (no cloud call) for one example invoice before and after
the reload. Makes no model or cloud call. Writes ``results/part5/article_numbers.json``.

Beyond the summary it works out what the articles need and the summary does
not hold: the drifted answers beside what a recomputed answer key would have
said, one example row of the changed column, one wrong answer's trace in
full, the attribute names on the root span split into standard and own, and
how long each execution took.

Usage:
    python analysis/part5_article_numbers.py
"""

# ruff: noqa: E501

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_part3  # noqa: E402 - the repository root has to be on the path first
import run_part5  # noqa: E402
from tessaway import drift, golden_set, registry, scoring, tracing  # noqa: E402
from tessaway.warehouse import generate  # noqa: E402

P5 = ROOT / "results" / "part5"
OUT = P5 / "article_numbers.json"
LEDGER = ROOT / "results" / "series_spend.json"
DRIFTED = run_part5.DRIFTED


def example_invoice() -> dict[str, Any]:
    """One Canadian-dollar invoice from Q3, as stored before the reload and after it."""
    tables = generate.generate()
    inv = next(
        r for r in tables["bil_cust_inv"]
        if r["curr_cd"] == "CAD" and "2026-08-01" <= r["inv_dt"] < "2026-09-01"
    )  # fmt: skip
    month = int(inv["inv_dt"][5:7])
    rate = float(generate.CAD_TO_USD[month])
    before = float(inv["inv_tot_amt"])
    after = round(before * rate, 2)
    return {
        "inv_id": inv["inv_id"],
        "inv_dt": inv["inv_dt"],
        "curr_cd": inv["curr_cd"],
        "stored_before": before,
        "stored_after": after,
        "rate": rate,
        "read_through_the_definition_before": round(before * rate, 2),
        "read_through_the_definition_after": round(after * rate, 2),
        "columns": [c for c, _ in drift.schema.TABLES["bil_cust_inv"]],
    }


def recomputed_agrees(drift_rows: list[dict[str, Any]], record: dict[str, Any]) -> dict[str, Any]:
    """Would a recomputed answer key have passed the drifted answers? Score each against both keys."""
    gs = golden_set.load()
    qs = {q.id: q for q in gs.questions}
    recomputed = record["gold_recomputed_on_copy"]["questions"]
    out: dict[str, Any] = {}
    for qid in DRIFTED:
        rows = [r for r in drift_rows if r["question_id"] == qid]
        q = qs[qid]
        rk = recomputed[qid]["recomputed"]
        right_vs_recomputed = sum(
            1 for r in rows
            if scoring.score(q, rk, [], r["answer_text"]).outcome == scoring.RIGHT
        )  # fmt: skip
        out[qid] = {
            "frozen": gs.gold(qid),
            "recomputed_on_drifted_copy": rk,
            "change_pct": recomputed[qid]["change_pct"],
            "agent_answers": [r["extracted"] for r in rows],
            "right_against_frozen": sum(1 for r in rows if r["outcome"] == scoring.RIGHT),
            "right_against_recomputed": right_vs_recomputed,
            "runs": len(rows),
        }
    return out


def example_trace(rows: list[dict[str, Any]], traces: list[dict[str, Any]]) -> dict[str, Any]:
    """The first drifted M2 run's trace: the root span's attributes and ADK's spans under it."""
    row = next(r for r in sorted(rows, key=lambda r: r["trial"]) if r["question_id"] == "M2")
    t = next(t for t in traces if t["run_id"] == row["run_id"])
    root = next(s for s in t["spans"] if s["name"] == tracing.ROOT_SPAN)
    names = Counter(s["name"].split(" ")[0] for s in t["spans"])
    tools = [
        {"name": s["name"], "ms": s["duration_ms"]}
        for s in t["spans"] if s["name"].startswith("execute_tool")
    ]  # fmt: skip
    calls = [
        {"seq": c["seq"], "tool": c["tool"], "arguments": c.get("arguments"),
         "definitions": [f"{d['id']}@{d['version']}" for d in c.get("definitions") or []],
         "rows": (c.get("result") or {}).get("rows") if isinstance(c.get("result"), dict) else None}
        for c in row["tool_calls"]
    ]  # fmt: skip
    return {
        "question_id": row["question_id"],
        "execution": row["trial"] + 1,
        "run_id": row["run_id"],
        "answer": row["extracted"],
        "gold": row["gold"],
        "outcome": row["outcome"],
        "final_lines": "\n".join(row["answer_text"].strip().splitlines()[-3:]),
        "cited": row["sources_cited"],
        "served": row["served_by_agent_record"],
        "root_attributes": root["attributes"],
        "root_ms": root["duration_ms"],
        "spans": len(t["spans"]),
        "span_kinds": dict(names),
        "tool_spans": tools,
        "tool_calls": calls,
        "queries": [q.get("sql") for q in row.get("queries") or []],
    }


def attribute_names(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Root-span attribute names, split into the OpenTelemetry conventions and this repo's own."""
    names: set[str] = set()
    for t in traces:
        for s in t["spans"]:
            if s["name"] == tracing.ROOT_SPAN:
                names |= set(s["attributes"])
    standard = sorted(n for n in names if n in tracing.STANDARD)
    own = sorted(n for n in names if n.startswith("tessaway."))
    return {"standard": standard, "own": own, "standard_count": len(standard), "own_count": len(own)}


def execution_minutes(raised: list[dict[str, Any]], drift_rows: list[dict[str, Any]], fix_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Wall-clock span of each execution's runs, from the records' finish times."""
    out = {}
    for name, rows in (("drift", drift_rows), ("after_fix", fix_rows)):
        for n, items in run_part5.executions(rows).items():
            times = sorted(datetime.fromisoformat(r["finished_at"]) for r in items)
            out[f"{name}_e{n}"] = {"first": times[0].isoformat(), "last": times[-1].isoformat(),
                                   "minutes_first_to_last": round((times[-1] - times[0]).total_seconds() / 60, 1)}  # fmt: skip
    return out


def attempt_latency(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean latency per drift execution over every attempt, and over the first 24 (reruns left out)."""
    out = {}
    for n in sorted({r["trial"] + 1 for r in attempts}):
        every = [r["seconds"] for r in attempts if r["trial"] + 1 == n]
        first = [r["seconds"] for r in attempts if r["trial"] + 1 == n and not r.get("retry_of_failed")]
        out[str(n)] = {"attempts": len(every), "mean_seconds": round(sum(every) / len(every), 1),
                       "first_tries": len(first), "first_tries_mean_seconds": round(sum(first) / len(first), 1)}
    return out


def main() -> None:
    """Write results/part5/article_numbers.json."""
    s = json.loads((P5 / "summary.json").read_text())
    rows = run_part5.phase_rows()
    drift_rows, fix_rows = rows["drift"], rows["after_fix"]
    traces = run_part5.read_traces(P5, "drift") + run_part5.read_traces(P5, "after_fix")
    records = {p.stem: json.loads(p.read_text()) for p in sorted((P5 / "drift").glob("*.json"))}
    ledger = json.loads(LEDGER.read_text())
    reg = registry.load()
    raised = s.get("alerts_raised", [])
    numbers = {
        "model": s["model"],
        "contract_version": s["contract_version"],
        "golden_set": s["golden_set"],
        "question_count": len(golden_set.load().questions),
        "alert_rule": s["alert_rule"],
        "bands": s["bands"],
        "operational": s["operational"],
        "operational_by_execution": s["operational_by_execution"],
        "green_by_execution": s["green_by_execution"],
        "failed_attempts": s["failed_attempts"],
        # Latency counting every attempt, failed first tries included, as a dashboard would see it.
        "attempt_latency_by_execution": attempt_latency(run_part5.attempts(P5 / "runs" / "drift.jsonl")),
        "answers": {k: {kk: v[kk] for kk in ("runs", "overall", "right_share", "by_group")} for k, v in s["answers"].items()},
        "answers_by_execution": s["answers_by_execution"],
        "drifted_questions": {q: s["answers"]["drift"]["by_question"][q] for q in DRIFTED},
        "alerts": s["alerts"],
        "alerts_raised": raised,
        "time_to_detection": s["time_to_detection"],
        "narrowing": s["narrowing"],
        "owners": {d: e["owner"] for d, e in reg["definitions"].items()},
        "currency_definition": {k: reg["definitions"]["currency"][k] for k in ("title", "owner", "version", "where")},
        "revenue_definition": {k: reg["definitions"]["revenue"][k] for k in ("title", "owner", "version", "where")},
        "traces": s["traces"],
        "attribute_names": attribute_names(traces),
        "example_trace": example_trace(drift_rows, run_part5.read_traces(P5, "drift")),
        "drift_records": {
            k: {
                "changed_rows": v["status"]["changed_rows"],
                "changed_rows_by_table": {t: x.get("rows_with_a_changed_amount") for t, x in v["status"]["tables"].items() if t in drift.TABLES},
                "row_counts_and_types_as_record": all(x["rows"] == x["rows_in_record"] and x["same_columns_and_types"] for x in v["status"]["tables"].values()),
                "currency_codes_changed": sum(x.get("rows_with_a_changed_currency_code") or 0 for x in v["status"]["tables"].values()),
                "out_of_tolerance": v["gold_recomputed_on_copy"]["out_of_tolerance"],
                "recomputed": {q: x["recomputed"] for q, x in v["gold_recomputed_on_copy"]["questions"].items() if q in ("M2", "M3", "M4", "E1", "E3", "R3", "R6", "L6")},
                "change_pct": {q: x["change_pct"] for q, x in v["gold_recomputed_on_copy"]["questions"].items() if q in ("M2", "M3", "M4", "E3", "R3", "R6")},
            }
            for k, v in records.items()
        },
        "recomputed_key_against_drifted_answers": recomputed_agrees(drift_rows, records["restated"]),
        "wrong_runs_own_sql": {
            "wrong_runs": len(wrong := [r for r in drift_rows if r["outcome"] == scoring.WRONG]),
            "ran_sql": sum(1 for r in wrong if r["query_count"]),
            "sql_applied_the_fx_rate": sum(1 for r in wrong if any("fx" in str(q.get("sql", "")).lower() for q in r["queries"])),
            "answer_source": dict(Counter(r["answer_source"] for r in wrong)),
            "by_question": {
                q: [sum("fx" in str(x.get("sql", "")).lower() for x in r["queries"]) for r in wrong if r["question_id"] == q]
                for q in DRIFTED
            },
        },
        "example_invoice": example_invoice(),
        "execution_minutes": execution_minutes(raised, drift_rows, fix_rows),
        "server_log_check": {k: v for k, v in (s.get("server_log_check") or {}).items() if k != "problems"},
        "predictions": s["predictions"],
        "predictions_held": sum(1 for p in s["predictions"] if p["held"]),
        "predictions_total": len(s["predictions"]),
        "spend": {
            "part5": ledger["parts"]["5"],
            "series_spent_parts_2_to_7": ledger["spent_usd_parts_2_to_7"],
            "approved": ledger["approved_usd_parts_2_to_7"],
            "hard_cap": ledger["hard_cap_usd_parts_2_to_7"],
            "remaining_to_hard_cap": ledger["remaining_to_hard_cap_usd"],
        },
        "smoke": {
            "runs": [
                {"question_id": r["question_id"], "trial": r["trial"], "outcome": r["outcome"], "timed_out": r["timed_out"],
                 "error": str(r["error"]).strip().splitlines()[0][:80] if r["error"] else ""}
                for r in run_part3.read_jsonl(P5 / "smoke" / "runs" / "smoke.jsonl")
            ],
        },
    }
    OUT.write_text(json.dumps(numbers, indent=1, default=str) + "\n")
    print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
