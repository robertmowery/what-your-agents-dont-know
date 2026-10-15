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

"""Derive the figures the Part 4 articles quote.

Reads ``results/part4/summary.json``, the saved runs under ``results/part4/runs``,
``results/part4/server_log.jsonl``, ``results/part4/audit.md``,
``data/definition_registry.json``, Part 3's summary and runs, the Part 2
held-out summary and ``results/series_spend.json``. Makes no model or cloud
call. Writes ``results/part4/article_numbers.json``.

Beyond the summary it works out what the articles need and the summary does
not hold: how many definitions an answer cites against how many the server
served in that run, the three H10 runs side by side with their replies, the
H10 runs of earlier parts, the registry's shape, and the audit's step times.

Usage:
    python analysis/part4_article_numbers.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_part3  # noqa: E402 - the repository root has to be on the path first
import run_part4  # noqa: E402

P4 = ROOT / "results" / "part4"
P3 = ROOT / "results" / "part3"
OUT = P4 / "article_numbers.json"
REGISTRY = ROOT / "data" / "definition_registry.json"


def cited_against_served(rows: list[dict[str, Any]], log: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """On answered runs that need a definition: definitions cited, against definitions served."""
    items = [(r, run_part4.trace(r, log)) for r in rows if not run_part4.is_lookup(r) and run_part4.answered(r)]
    cited = [len(t["cited"]) for _, t in items]
    served = [len(t["served"]) for _, t in items]
    fewer = sum(1 for _, t in items if set(t["served"]) - set(t["cited"]))
    equal = sum(1 for _, t in items if set(t["served"]) == set(t["cited"]))
    return {
        "runs": len(items),
        "mean_cited": round(mean(cited), 2),
        "mean_served": round(mean(served), 2),
        "cited_counts": dict(sorted(Counter(cited).items())),
        "served_counts": dict(sorted(Counter(served).items())),
        "runs_served_something_not_cited": fewer,
        "runs_cited_exactly_what_was_served": equal,
    }


def last_paragraphs(text: str) -> str:
    """The reply from its last paragraph before SOURCES to the end, verbatim."""
    parts = text.strip().split("\n\n")
    return "\n\n".join(parts[-2:]) if len(parts) >= 2 else text.strip()


def h10_part4(log: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Every saved H10 run in Part 4, the replaced one included."""
    every = run_part3.read_jsonl(P4 / "runs" / "routed_holdout.jsonl")
    scored = {r["run_id"] for r in run_part3.rows_in(P4 / "runs" / "routed_holdout.jsonl")}
    out = []
    for r in every:
        if r["question_id"] != "H10":
            continue
        t = run_part4.trace(r, log) if r["run_id"] in scored else None
        out.append({
            "trial": r["trial"],
            "run_id": r["run_id"],
            "scored": r["run_id"] in scored,
            "outcome": r["outcome"],
            "answer": r.get("extracted"),
            "timed_out": r.get("timed_out"),
            "model_calls": r.get("model_calls"),
            "cited": r.get("sources_cited"),
            "served_by_log": t["served"] if t else None,
            "status": t["status"] if t else None,
            "reply_names_139": "139" in (r.get("answer_text") or ""),
            "reply_end": last_paragraphs(r.get("answer_text") or ""),
            "tools_in_order": r.get("tools_in_order"),
        })
    return {"runs": out, "gold": next(r["gold"] for r in every if r["question_id"] == "H10")}


def audit_calls(run_id: str, log: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The audit run's contract calls, in order: operation, arguments, definitions, rows, log time."""
    row = next(r for r in run_part3.rows_in(P4 / "runs" / "routed_holdout.jsonl") if r["run_id"] == run_id)
    by_rid = {str(line.get("response_id")): line for line in log.get(run_id, [])}
    out = []
    for c in row["tool_calls"]:
        logged = by_rid.get(str(c.get("response_id")), {})
        res = c.get("result") or {}
        out.append({
            "seq": c["seq"],
            "operation": c["tool"],
            "arguments": c.get("arguments"),
            "definitions": [f"{d['id']}@{d['version']}" for d in c.get("definitions") or []],
            "owners": sorted({d.get("owner", "") for d in c.get("definitions") or []}),
            "rows": res.get("rows") if isinstance(res, dict) else None,
            "columns": res.get("columns") if isinstance(res, dict) else None,
            "in_server_log": bool(logged),
            "log_time": logged.get("time") or logged.get("log_timestamp"),
        })
    return out


def h10_part3() -> list[dict[str, Any]]:
    """Part 3's routed_holdout H10 runs: answer and outcome."""
    rows = run_part3.rows_in(P3 / "runs" / "routed_holdout.jsonl")
    return [{"trial": r["trial"], "outcome": r["outcome"], "answer": r.get("extracted"),
             "reply_names_139": "139" in (r.get("answer_text") or "")}
            for r in rows if r["question_id"] == "H10"]


def h10_holdout() -> dict[str, Any]:
    """Part 2's held-out runs on H10, raw warehouse and semantic layer plus SQL, from the saved runs."""
    out = {}
    for name in ("baseline", "flash_semantic"):
        found = sorted((ROOT / "results" / "holdout" / "runs").glob(f"{name}*.jsonl"))
        rows = [r for p in found for r in run_part3.read_jsonl(p) if r.get("question_id") == "H10"]
        out[name] = {"files": [str(p.relative_to(ROOT)) for p in found],
                     "outcomes": dict(Counter(r["outcome"] for r in rows)),
                     "answers": [r.get("extracted") for r in rows]}
    return out


def registry_shape() -> dict[str, Any]:
    data = json.loads(REGISTRY.read_text())
    defs = data["definitions"]
    by_owner: dict[str, list[str]] = {}
    for ident, d in defs.items():
        by_owner.setdefault(d["owner"], []).append(ident)
    served = Counter()
    for d in defs.values():
        for kind, names in d.get("serves", {}).items():
            served[kind] += len(names)
    return {
        "definitions": len(defs),
        "owners": len(by_owner),
        "by_owner": by_owner,
        "versions": dict(Counter(int(d["version"]) for d in defs.values())),
        "served_names": dict(served),
        "on_time": {k: defs["on_time"][k] for k in ("title", "owner", "version", "where")}
        | {"history": defs["on_time"]["history"], "serves": defs["on_time"]["serves"],
           "owner_role": data["owners"][defs["on_time"]["owner"]]},
    }


def audit_times() -> dict[str, Any]:
    text = (P4 / "audit.md").read_text()
    steps = re.findall(r"^## (.+?) \(([0-9.]+) ms\)$", text, re.M)
    total = re.search(r"The whole trace took ([0-9.]+) ms", text)
    return {"steps": [{"step": s, "ms": float(ms)} for s, ms in steps],
            "total_ms": float(total.group(1)) if total else None}


def main() -> None:
    s = json.loads((P4 / "summary.json").read_text())
    p3 = json.loads((P3 / "summary.json").read_text())
    ledger = json.loads((ROOT / "results" / "series_spend.json").read_text())
    log = run_part4.log_by_run(P4)
    rows = {n: run_part3.rows_in(P4 / "runs" / f"{n}.jsonl") for n in run_part4.CONFIGS}
    out: dict[str, Any] = {"written_by": "analysis/part4_article_numbers.py", "contract_version": s["contract_version"],
                           "model": s["model"]}
    out["outcomes"] = {n: s["configs"][n]["summary"]["overall"] for n in rows}
    out["accuracy_against_part3"] = {
        n: {k: s["configs"][n]["accuracy_against_part3"][k] for k in ("part3", "part4", "change_in_runs")}
        | {"questions_that_changed": {
            q: v for q, v in s["configs"][n]["accuracy_against_part3"]["by_question"].items() if v["part3"] != v["part4"]}}
        for n in rows}
    out["traceability"] = {n: {k: v for k, v in s["configs"][n]["traceability"]["needs_definition"].items()
                               if k not in ("by_question",)} for n in rows}
    out["lookups"] = s["configs"]["available"]["traceability"]["lookups"]
    out["cited_against_served"] = {n: cited_against_served(rs, log) for n, rs in rows.items()}
    out["answer_source"] = {
        "part4_available": {k: v["runs"] for k, v in s["configs"]["available"]["answer_source"].items() if k != "runs"},
        "part3_available": {k: v["runs"] for k, v in p3["configurations"]["available"]["answer_source"].items() if k != "runs"},
    }
    out["contract"] = {n: s["configs"][n]["versions"] for n in rows}
    out["server_log_check"] = s["server_log_check"]
    out["server_log_lines_saved"] = len(run_part3.read_jsonl(P4 / "server_log.jsonl"))
    out["h10"] = {"part4": h10_part4(log), "part3_routed_holdout": h10_part3(), "part2_holdout": h10_holdout()}
    out["registry"] = registry_shape()
    out["audit"] = s["audit"] | audit_times() | {"calls": audit_calls(s["audit"]["run_id"], log)}
    out["effort"] = {n: s["configs"][n]["effort"] for n in rows}
    out["effort_part3"] = {n: p3["configurations"][n]["effort"] for n in ("available", "routed_holdout")}
    out["predictions"] = s["predictions"]
    out["spend"] = {"part4": ledger["parts"].get("4"), "series_total_usd": ledger.get("spent_usd_parts_2_to_7"),
                    "approved_usd": ledger["approved_usd_parts_2_to_7"], "hard_cap_usd": ledger["hard_cap_usd_parts_2_to_7"]}
    OUT.write_text(json.dumps(out, indent=1, default=str) + "\n")
    print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
