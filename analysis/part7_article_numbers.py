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

"""Part 7: every number in the articles, from the Part 7 run records.

Reads results/part7/runs/{canary,rollback,rollout}.jsonl, routing_changes.jsonl,
the frozen answer keys (golden sets v1 and v2), the registry, the semantic layer
and the Part 1 to 6 records (through tessaway/meter.py) and writes
results/part7/article_numbers.json and summary.md. It calls no model.

Usage:
    python analysis/part7_article_numbers.py
"""

# ruff: noqa: E501

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from context_server import versions  # noqa: E402
from tessaway import golden_set, meter, questions, registry  # noqa: E402
from tessaway.layers import semantic  # noqa: E402

RES = ROOT / "results" / "part7"
PHASES = ("canary", "rollback", "rollout")
REVENUE_QUESTIONS = ("M2", "M3", "M4", "E1", "E3", "R3")
MARGIN_QUESTIONS = ("M3", "M4")
SERIES_ROWS = (
    ("p1_flash", "Part 1", "Raw warehouse"),
    ("p2_semantic", "Part 2", "Semantic layer"),
    ("p3_available", "Part 3", "Context contract and SQL"),
    ("p4_available", "Part 4", "Contract, cited answers"),
    ("p5_drift", "Part 5", "Billing's reload in place"),
    ("p5_after_fix", "Part 5", "After the fix"),
)


def rows(phase: str) -> list[dict[str, Any]]:
    """The scored record per question and repeat for one phase."""
    return meter.scored(meter.load(f"part7/runs/{phase}.jsonl"))


def counts(records: list[dict[str, Any]]) -> dict[str, int]:
    """Outcome counts for a set of runs."""
    c = Counter(r["outcome"] for r in records)
    return {o: c.get(o, 0) for o in meter.OUTCOMES} | {"runs": len(records)}


def stamped(r: dict[str, Any], requested: bool | None = None) -> dict[str, set[int]]:
    """Versions of revenue and margin the contract stamped in a run's tool calls.

    ``requested`` True keeps only calls where the agent passed definition_versions
    itself, False only calls it did not, None all of them.
    """
    found: dict[str, set[int]] = {"revenue": set(), "margin": set()}
    for call in r.get("tool_calls") or []:
        asked = bool((call.get("arguments") or {}).get("definition_versions"))
        if requested is not None and asked != requested:
            continue
        for d in call.get("definitions") or []:
            if d.get("id") in found:
                found[d["id"]].add(int(d["version"]))
    return found


def served_ok(r: dict[str, Any]) -> bool:
    """Every call the agent did not pin itself was served the versions its routing says."""
    want = versions.STATES[r["expected_state"]]
    got = stamped(r, requested=False)
    return all(not got[i] or got[i] == {want[i]} for i in ("revenue", "margin"))


def asked_for_versions(r: dict[str, Any]) -> list[dict[str, Any]]:
    """The calls in which the agent passed definition_versions itself."""
    return [
        {"tool": c["tool"], "definition_versions": c["arguments"]["definition_versions"]}
        for c in r.get("tool_calls") or []
        if (c.get("arguments") or {}).get("definition_versions")
    ]


def sql_dating(r: dict[str, Any]) -> str:
    """How the agent's own SQL dated revenue in this run, read from its queries."""
    text = " ".join(str(q.get("sql", "")) for q in r.get("queries") or []).lower()
    if not text:
        return "no SQL"
    by_delivery = "tms_stop" in text and ("bil_cust_inv" in text)
    by_invoice = "inv_dt" in text
    if by_delivery:
        return "delivery date"
    if by_invoice:
        return "invoice date"
    return "other"


def dependents() -> dict[str, Any]:
    """What depends on revenue, found in the repo: the bill of materials' dependents list."""
    spec = yaml.safe_load((semantic.PROJECT_DIR / "models" / "semantic.yml").read_text())
    metric_deps = sorted(
        m["name"]
        for m in spec["metrics"]
        if m.get("type") == "derived"
        and "revenue" in [x["name"] for x in m["type_params"].get("metrics", [])]
    )
    qs = [q for q in questions.load() if "revenue" in q.definitions]
    catalog = {m["name"]: m["description"] for m in semantic.catalog()["metrics"]}
    data = registry.load()
    return {
        "semantic_metrics_built_on_revenue": metric_deps,
        "questions_listing_revenue": [q.id for q in qs],
        "ontology_terms": data["definitions"]["revenue"]["serves"]["terms"],
        "definitions_built_on_revenue": [
            i
            for i, d in data["definitions"].items()
            if (i != "revenue" and "revenue" in d["title"].lower()) or i == "margin"
        ],
        "tool_description_copy": "invoice date" in catalog.get("revenue", ""),
    }


SHIFT_SQL = """
WITH fx AS (
  SELECT eff_mo_dt, fx_rt FROM ref_fx_rate WHERE from_curr_cd = 'CAD' AND to_curr_cd = 'USD'
),
dlv AS (
  SELECT load_id, DATE(arr_ts, tz_nm) AS dlvr_dt FROM tms_stop WHERE stop_typ_cd = 'DL'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY load_id ORDER BY stop_seq DESC) = 1
),
docs AS (
  SELECT 'invoice' AS kind, i.inv_dt AS v1_dt, d.dlvr_dt AS v2_dt,
         i.inv_tot_amt * IF(i.curr_cd = 'CAD', fx.fx_rt, 1) AS usd
  FROM bil_cust_inv i JOIN dlv d USING (load_id)
  LEFT JOIN fx ON fx.eff_mo_dt = DATE_TRUNC(i.inv_dt, MONTH)
  UNION ALL
  SELECT 'credit_memo', c.cr_dt, d.dlvr_dt, -c.cr_amt * IF(c.curr_cd = 'CAD', fx.fx_rt, 1)
  FROM bil_cr_memo c JOIN dlv d USING (load_id)
  LEFT JOIN fx ON fx.eff_mo_dt = DATE_TRUNC(c.cr_dt, MONTH)
)
SELECT kind,
  COUNTIF(v1_dt BETWEEN '2026-07-01' AND '2026-09-30' AND v2_dt < '2026-07-01') AS leave_n,
  ROUND(SUM(IF(v1_dt BETWEEN '2026-07-01' AND '2026-09-30' AND v2_dt < '2026-07-01', usd, 0)), 2) AS leave_usd,
  COUNTIF(v2_dt BETWEEN '2026-07-01' AND '2026-09-30' AND v1_dt > '2026-09-30') AS enter_n,
  ROUND(SUM(IF(v2_dt BETWEEN '2026-07-01' AND '2026-09-30' AND v1_dt > '2026-09-30', usd, 0)), 2) AS enter_usd,
  MAX(DATE_DIFF(v1_dt, v2_dt, DAY)) AS max_lag_days,
  ROUND(AVG(DATE_DIFF(v1_dt, v2_dt, DAY)), 2) AS mean_lag_days
FROM docs GROUP BY kind ORDER BY kind
"""


def quarter_shift() -> list[dict[str, Any]]:
    """Which documents leave and enter Q3 2026 when revenue moves to the delivery date."""
    from tessaway.warehouse import query

    reply = query.run_readonly(SHIFT_SQL)
    if "error" in reply:
        raise SystemExit(reply["error"])
    return [dict(zip(reply["columns"], row, strict=True)) for row in reply["rows"]]


def bom(state: str) -> dict[str, Any]:
    """The bill of materials entry for revenue in one state."""
    v = versions.STATES[state]
    hist = {int(h["version"]): h for h in registry.history("revenue")}
    mhist = {int(h["version"]): h for h in registry.history("margin")}
    return {
        "id": "revenue",
        "version": v["revenue"],
        "owner": registry.owner_of("revenue", v["revenue"]),
        "effective": hist[v["revenue"]]["effective"],
        "change": hist[v["revenue"]]["change"],
        "served_with": {"margin": v["margin"], "margin_change": mhist[v["margin"]]["change"]},
        "metric_names": versions.metric_names(v) or {"revenue": "revenue"},
    }


def predictions(n: dict[str, Any]) -> list[dict[str, Any]]:
    """Check each prediction in results/part7/predictions.md against the numbers."""
    c = n["phases"]
    can = c["canary"]
    out = []

    def add(p: str, held: bool, numbers: str) -> None:
        out.append({"prediction": p, "held": bool(held), "numbers": numbers})

    v1 = can["by_state"]["v1"]
    add("P1", v1["right"] >= 46, f"{v1['right']} of {v1['runs']} version 1 canary runs right")
    rq = {q: can["version2_by_question"][q] for q in ("M2", "E3", "R3")}
    add(
        "P2",
        all(x["outcome"] == "right" and "revenue@2" in x["cited"] for x in rq.values()),
        "; ".join(
            f"{q}: {x['outcome']}, cites {','.join(x['cited']) or '-'}" for q, x in rq.items()
        ),
    )
    mq = {q: can["version2_by_question"][q] for q in MARGIN_QUESTIONS}
    add(
        "P3",
        all(x["outcome"] != "right" for x in mq.values()) and any(x["mixed"] for x in mq.values()),
        "; ".join(f"{q}: {x['outcome']}{', mixed' if x['mixed'] else ''}" for q, x in mq.items()),
    )
    e1 = [r for p in PHASES for r in rows(p) if r["question_id"] == "E1"]
    add(
        "P4",
        all(r["outcome"] == "right" for r in e1),
        f"E1 right in {sum(r['outcome'] == 'right' for r in e1)} of {len(e1)}",
    )
    other = [x for q, x in can["version2_by_question"].items() if q not in REVENUE_QUESTIONS]
    add(
        "P5",
        sum(x["outcome"] == "right" for x in other) >= 17,
        f"{sum(x['outcome'] == 'right' for x in other)} of {len(other)}",
    )
    bad = sum(c[p]["served_mismatch"] for p in PHASES)
    asked = sum(c[p]["runs_that_asked_for_a_version"] for p in PHASES)
    add(
        "P6",
        bad == 0 and asked == 0,
        f"{bad} runs routed to a version their routing did not say; {asked} runs in which the"
        " agent asked for a version itself",
    )
    rb = n["rollback"]
    add(
        "P7",
        rb is not None and rb["until_served_seconds"] < 600,
        f"{rb['until_served_seconds']:.0f} s from the change to the service serving it"
        if rb
        else "no rollback",
    )
    r = c["rollback"]
    add(
        "P8",
        r["right"] >= 70 and r["served_v2_runs"] == 0,
        f"{r['right']} of {r['runs']} right; {r['served_v2_runs']} served version 2",
    )
    o = c["rollout"]
    mm = [x for x in rows("rollout") if x["question_id"] in MARGIN_QUESTIONS]
    add(
        "P9",
        o["right"] >= 70 and all(x["outcome"] == "right" for x in mm),
        f"{o['right']} of {o['runs']} right; M3 and M4 right in {sum(x['outcome'] == 'right' for x in mm)} of {len(mm)}",
    )
    v1hits = [
        x
        for p in PHASES
        for x in rows(p)
        if x["question_id"] in ("M2", "E3", "R3")
        and x["gold_version"] == 2
        and x.get("matched_decoy", "").startswith("revenue version 1")
    ]
    add("P10", not v1hits, f"{len(v1hits)} version 2 runs gave the version 1 figure")
    base = n["part4_cost_per_correct_usd"]
    within = {p: abs(c[p]["cost_per_correct_usd"] / base - 1) <= 0.2 for p in PHASES}
    add(
        "P11",
        all(within.values()),
        "; ".join(f"{p} {c[p]['cost_per_correct_usd'] * 100:.2f} cents" for p in PHASES)
        + f" (Part 4 {base * 100:.2f})",
    )
    return out


def main() -> None:
    """Write article_numbers.json and summary.md."""
    gs1, gs2 = golden_set.load(1), golden_set.load(2)
    changed = json.loads((RES / "gold_answers_v2.json").read_text())["changed"]
    n: dict[str, Any] = {"written_by": "analysis/part7_article_numbers.py", "phases": {}}
    for phase in PHASES:
        rs = rows(phase)
        roll = meter.rollup(rs)
        by_state: dict[str, Any] = {}
        for st in sorted({r["expected_state"] for r in rs}):
            sub = [r for r in rs if r["expected_state"] == st]
            by_state[st] = counts(sub) | {"right": sum(r["outcome"] == "right" for r in sub)}
        entry = {
            **counts(rs),
            "right": roll["outcomes"]["right"],
            "cost_per_run_usd": roll["cost_per_run_usd"],
            "cost_per_correct_usd": roll["cost_per_correct_usd"],
            "spend_usd": roll["spend_usd"],
            "input_tokens_per_run": roll["input_tokens_per_run"],
            "model_calls_per_run": roll["model_calls_per_run"],
            "by_state": by_state,
            "served_mismatch": sum(not served_ok(r) for r in rs),
            "served_v2_runs": sum(2 in (r["served_versions"].get("revenue") or []) for r in rs),
            "mixed": sum(bool(r.get("matched_mixed")) for r in rs),
            "runs_that_asked_for_a_version": sum(bool(asked_for_versions(r)) for r in rs),
            "runs_asking": [
                {
                    "question_id": r["question_id"],
                    "trial": r["trial"],
                    "state": r["expected_state"],
                    "outcome": r["outcome"],
                    "asked": asked_for_versions(r),
                }
                for r in rs
                if asked_for_versions(r)
            ],
            "replaced_attempts": len(meter.replaced(meter.load(f"part7/runs/{phase}.jsonl"))),
            "by_question": {
                q: {
                    "right": sum(r["outcome"] == "right" for r in rs if r["question_id"] == q),
                    "runs": sum(1 for r in rs if r["question_id"] == q),
                }
                for q in REVENUE_QUESTIONS
            },
            "revenue_questions_right": sum(
                r["outcome"] == "right" for r in rs if r["question_id"] in REVENUE_QUESTIONS
            ),
            "revenue_questions_runs": sum(1 for r in rs if r["question_id"] in REVENUE_QUESTIONS),
            "sql_dating_on_revenue_questions": dict(
                Counter(sql_dating(r) for r in rs if r["question_id"] in REVENUE_QUESTIONS)
            ),
        }
        if phase == "canary":
            v2runs = {r["question_id"]: r for r in rs if r["expected_state"] == "revenue_v2"}
            entry["version2_by_question"] = {
                q: {
                    "outcome": r["outcome"],
                    "extracted": r["extracted"],
                    "gold_v2": gs2.gold(q),
                    "gold_v1": gs1.gold(q),
                    "mixed": bool(r.get("matched_mixed")),
                    "matched_decoy": r.get("matched_decoy", ""),
                    "served": r["served_versions"],
                    "asked_for_versions": asked_for_versions(r),
                    "cited": r["cited_versions"],
                    "answer_source": r.get("answer_source"),
                    "sql_dating": sql_dating(r),
                }
                for q, r in sorted(v2runs.items())
            }
        n["phases"][phase] = entry
    changes = (
        [
            json.loads(x)
            for x in (RES / "routing_changes.jsonl").read_text().splitlines()
            if x.strip()
        ]
        if (RES / "routing_changes.jsonl").exists()
        else []
    )
    n["routing_changes"] = changes
    n["rollback"] = next((c for c in changes if c["routing"] == "v1"), None)
    n["rollout_change"] = next((c for c in changes if c["routing"] == "v2"), None)
    n["answer_key_changes"] = changed
    n["quarter_shift"] = quarter_shift()
    n["dependents"] = dependents()
    n["bill_of_materials"] = {"before": bom("v1"), "canary": bom("revenue_v2"), "after": bom("v2")}
    p4 = meter.rollup(meter.scored(meter.load("part4/runs/available.jsonl")))
    n["part4_cost_per_correct_usd"] = p4["cost_per_correct_usd"]
    series = []
    for key, part, label in SERIES_ROWS:
        cfg = next(c for c in meter.SERIES if c.key == key)
        r = meter.rollup(meter.scored(meter.load(cfg.path)))
        series.append(
            {
                "key": key,
                "part": part,
                "label": label,
                "runs": r["runs"],
                **r["shares"],
                "cost_per_correct_usd": r["cost_per_correct_usd"],
            }
        )
    ro = meter.rollup(rows("rollout"))
    series.append(
        {
            "key": "p7_rollout",
            "part": "Part 7",
            "label": "Revenue version 2",
            "runs": ro["runs"],
            **ro["shares"],
            "cost_per_correct_usd": ro["cost_per_correct_usd"],
        }
    )
    n["series_close"] = series
    from run_part3 import spend as run_spend

    sp = run_spend(RES)
    n["spend"] = {"gemini_total_usd": sp["gemini_total_usd"], "by_folder": sp["gemini_by_folder"]}
    ledger = json.loads((ROOT / "results" / "series_spend.json").read_text())
    n["series_ledger"] = {
        k: ledger[k]
        for k in (
            "spent_usd_parts_2_to_7",
            "approved_usd_parts_2_to_7",
            "hard_cap_usd_parts_2_to_7",
            "part1_spent_usd_not_counted_toward_cap",
        )
    }
    n["predictions"] = predictions(n)
    (RES / "article_numbers.json").write_text(json.dumps(n, indent=1, default=str) + "\n")
    (RES / "summary.md").write_text(summary(n))
    print("wrote article_numbers.json and summary.md")
    for p in n["predictions"]:
        print(p["prediction"], "held" if p["held"] else "NOT HELD", "-", p["numbers"])


def summary(n: dict[str, Any]) -> str:
    """A readable summary of the numbers."""
    out = [
        "# Part 7 results",
        "",
        "Written by `analysis/part7_article_numbers.py`. Tessaway Freight is a fictional company and the data is synthetic.",
        "",
        "| Phase | Runs | Right | Confidently wrong | Declined | No answer | Mixed versions | Served a wrong version | Cost per correct |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for p, e in n["phases"].items():
        out.append(
            f"| {p} | {e['runs']} | {e['right']} | {e['confidently_wrong']} | {e['declined']} | {e['no_answer']} | {e['mixed']} | {e['served_mismatch']} | {e['cost_per_correct_usd'] * 100:.2f} cents |"
        )
    out += [
        "",
        "## Canary: the version 2 run of each question",
        "",
        "| Question | Outcome | Answer | Version 2 key | Version 1 key | Served | Cited | Agent SQL dated revenue by |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for q, x in n["phases"]["canary"]["version2_by_question"].items():
        out.append(
            f"| {q} | {x['outcome']}{' (mixed)' if x['mixed'] else ''} | {str(x['extracted'])[:22]} | {x['gold_v2']} | {x['gold_v1']} | {x['served']} | {', '.join(x['cited'])} | {x['sql_dating']} |"
        )
    rb = n["rollback"]
    if rb:
        out += [
            "",
            f"Rollback: {rb['until_served_seconds']:.0f} seconds from the new revision's creation to it serving all traffic, everyone on version 1.",
        ]
    out += ["", "## Predictions", ""] + [
        f"- {p['prediction']}: {'held' if p['held'] else 'did not hold'} ({p['numbers']})"
        for p in n["predictions"]
    ]
    out += [
        "",
        "## Series",
        "",
        "| Part | Configuration | Runs | Right | Confidently wrong | Declined | Cost per correct |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in n["series_close"]:
        out.append(
            f"| {s['part']} | {s['label']} | {s['runs']} | {s['right']:.1%} | {s['confidently_wrong']:.1%} | {s['declined']:.1%} | {s['cost_per_correct_usd'] * 100:.2f} cents |"
        )
    out += [
        "",
        f"Part 7 spend (Gemini and BigQuery, estimated): ${n['spend']['gemini_total_usd']:.2f}.",
    ]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
