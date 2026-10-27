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

"""Derive the figures the Part 6 articles quote, from the run records of Parts 1 to 5.

Reads every runs file listed in ``tessaway.meter.SERIES`` and ``UNSCORED``, the
smoke-test runs beside them, ``results/series_spend.json`` and
``data/agent_budgets.json``. Prices every record again from its token counts and
stops if that does not match the cost the run recorded. Makes no model or cloud
call. Writes ``results/part6/article_numbers.json`` and ``results/part6/summary.md``.

Usage:
    python analysis/part6_article_numbers.py
"""

# ruff: noqa: E501

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tessaway import budget, meter  # noqa: E402
from tessaway.config import BQ_USD_PER_TIB, CONFIGS, MODELS_VERIFIED_ON  # noqa: E402

OUT = ROOT / "results" / "part6"

# Checked on the Vertex AI pricing page on 2026-10-27 (global endpoint, per million
# tokens). Flash's prices are introductory through Dec 31, 2026 and double on Jan 1, 2027.
PRICES_CHECKED_ON = "2026-10-27"
FLASH_FROM_2027 = {"usd_in": 1.50, "usd_out": 7.50, "usd_cache_read": 0.15}
TOLERANCE_USD = 1e-6


def check_recorded_costs(all_records: list[dict]) -> dict:
    """Price every record again and compare with what it recorded."""
    worst_model = worst_bq = 0.0
    no_bytes = 0
    for r in all_records:
        worst_model = max(worst_model, abs(meter.model_cost(r) - float(r.get("cost_usd") or 0)))
        if "bigquery_bytes_billed" not in r:
            no_bytes += 1  # the record kept the dollars but not the bytes; nothing to price again
            continue
        worst_bq = max(worst_bq, abs(meter.bigquery_cost(r) - float(r.get("bigquery_usd") or 0)))
    ok = worst_model <= TOLERANCE_USD and worst_bq <= TOLERANCE_USD
    if not ok:
        raise SystemExit(
            f"recorded costs do not match the tokens: model {worst_model}, BigQuery {worst_bq}"
        )
    return {
        "records_checked": len(all_records),
        "largest_model_difference_usd": worst_model,
        "largest_bigquery_difference_usd": worst_bq,
        "records_without_bytes_billed": no_bytes,
        "tolerance_usd": TOLERANCE_USD,
    }


def smoke_spend() -> dict:
    """Spend recorded by every smoke-test and discarded run, by part."""
    out = {}
    for path in sorted(
        glob.glob(str(ROOT / "results" / "*" / "smoke*" / "**" / "*.jsonl"), recursive=True)
    ):
        part = Path(path).relative_to(ROOT / "results").parts[0]
        out[part] = out.get(part, 0.0) + sum(meter.spend(r) for r in meter.load(path))
    return out


def main() -> None:
    """Price every configuration, check the budget and write the results."""
    OUT.mkdir(parents=True, exist_ok=True)
    configs = {}
    every_record = []
    budgets = budget.load()
    agent = budgets["agents"][0]
    task_limit = float(agent["limit_per_task_usd"])
    day_limit = float(agent["limit_per_day_usd"])

    for cfg in meter.SERIES + meter.UNSCORED:
        records = meter.load(cfg.path)
        every_record.extend(records)
        final = meter.scored(records)
        extra = meter.replaced(records)
        entry = {
            "part": cfg.part,
            "label": cfg.label,
            "question_set": cfg.question_set,
            "context": cfg.context,
            "model": sorted({r["model"] for r in records}),
            "attempts": len(records),
            "replaced_attempts": len(extra),
            "replaced_spend_usd": sum(meter.spend(r) for r in extra),
            "scored": meter.rollup(final),
            "by_group": meter.by_group(final) if cfg in meter.SERIES else {},
            "step_profile": meter.step_profile(final, steps=22),
            "over_task_limit": budget.over_task_limit(records, task_limit),
        }
        over = entry["over_task_limit"]
        entry["over_task_limit_summary"] = {
            "runs": len(over),
            "outcomes": {o: sum(1 for x in over if x["outcome"] == o) for o in meter.OUTCOMES},
            "by_group": {g: sum(1 for x in over if x["group"] == g) for g in meter.GROUPS},
            "asked_past_query_limit": sum(1 for x in over if x["asked_past_query_limit"]),
            "hit_model_call_ceiling": sum(1 for x in over if x["hit_model_call_ceiling"]),
            "mean_model_calls": (sum(x["model_calls"] or 0 for x in over) / len(over))
            if over
            else None,
            "mean_cost_usd": (sum(x["cost_usd"] for x in over) / len(over)) if over else None,
            "share_of_runs": len(over) / len(records),
        }
        if cfg in meter.UNSCORED:
            entry["note"] = (
                "Recorded with tokens and cost but never scored; no cost per correct answer."
            )
        if records[0]["model"] == "gemini-3.8-flash":
            jan = meter.reprice(final, **FLASH_FROM_2027)
            right = entry["scored"]["outcomes"]["right"]
            entry["from_2027"] = {
                "spend_usd": jan,
                "cost_per_correct_usd": jan / right if right else None,
            }
        configs[cfg.key] = entry

    checks = check_recorded_costs(every_record)
    smoke = smoke_spend()
    scored_total = sum(
        c["scored"]["spend_usd"] for k, c in configs.items() if k != "p3_claude_demo"
    )
    replaced_total = sum(c["replaced_spend_usd"] for c in configs.values())
    demo_total = configs["p3_claude_demo"]["scored"]["spend_usd"]
    by_day = budget.spend_by_day(every_record)

    main24 = [
        k for k, c in configs.items() if c["question_set"] == "part1" and k != "p3_claude_demo"
    ]
    wasted = {
        "configurations": main24,
        "spend_usd": sum(configs[k]["scored"]["spend_usd"] for k in main24),
        "by_outcome_usd": {
            o: sum(configs[k]["scored"]["spend_by_outcome_usd"][o] for k in main24)
            for o in meter.OUTCOMES
        },
    }
    series_spend = json.loads((ROOT / "results" / "series_spend.json").read_text())

    numbers = {
        "written_by": "analysis/part6_article_numbers.py",
        "prices": {
            "pinned_on": MODELS_VERIFIED_ON,
            "checked_again_on": PRICES_CHECKED_ON,
            "per_million_tokens": {
                c.model: {"input": c.usd_in, "cached_input": c.usd_cache_read, "output": c.usd_out}
                for c in CONFIGS.values()
            },
            "gemini_3_8_flash_from_2027": FLASH_FROM_2027,
            "bigquery_usd_per_tib": BQ_USD_PER_TIB,
        },
        "recorded_cost_check": checks,
        "configurations": configs,
        "totals": {
            "scored_runs_usd": scored_total,
            "replaced_attempts_usd": replaced_total,
            "smoke_and_discarded_usd": smoke,
            "smoke_and_discarded_total_usd": sum(smoke.values()),
            "claude_demo_usd": demo_total,
            "all_recorded_usd": scored_total + replaced_total + sum(smoke.values()) + demo_total,
            "series_spend_ledger": series_spend,
        },
        "spend_by_outcome_24_questions": wasted,
        "budget": {
            "agent": agent["agent"],
            "owner": agent["owner"],
            "limit_per_task_usd": task_limit,
            "limit_per_day_usd": day_limit,
            "runs_over_task_limit": {k: len(c["over_task_limit"]) for k, c in configs.items()},
            "spend_by_day_usd": by_day,
            "days_over_limit": budget.over_day_limit(by_day, day_limit),
        },
    }
    (OUT / "article_numbers.json").write_text(json.dumps(numbers, indent=1) + "\n")
    (OUT / "summary.md").write_text(summary(numbers))
    print(
        f"wrote {OUT / 'article_numbers.json'} and summary.md; {checks['records_checked']} records priced again, all match"
    )


def _usd(x: float | None, cents: bool = False) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:.2f}¢" if cents else f"${x:,.2f}"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def summary(n: dict) -> str:
    """The results as a readable table, for the repo and the drafts."""
    lines = [
        "# Part 6 results",
        "",
        "Written by `analysis/part6_article_numbers.py` from the run records of Parts 1 to 5. Tessaway Freight is a fictional company and the data is synthetic. No model was called for this part.",
        "",
        f"Costs are estimates: tokens at list prices pinned on {n['prices']['pinned_on']} (checked again on {n['prices']['checked_again_on']}, unchanged), plus BigQuery bytes billed at ${n['prices']['bigquery_usd_per_tib']} per TiB. The invoice is the authority. Every one of the {n['recorded_cost_check']['records_checked']} records was priced again from its tokens and matches what it recorded (largest difference ${n['recorded_cost_check']['largest_model_difference_usd']:.7f}).",
        "",
        "A scored record is the final record for each question and repeat; a failed run that was run again is counted in the all-in total, not in the unit.",
        "",
        "## Cost per correct answer, by configuration",
        "",
        "| Configuration | Part | Questions | Runs | Right | Confidently wrong | Declined | No answer | Cost per run | Cost per correct answer | From Jan 1, 2027 | Input tokens per run | Model calls per run | Input tokens per call | Cached share |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in n["configurations"].values():
        s = c["scored"]
        jan = c.get("from_2027", {}).get("cost_per_correct_usd")
        lines.append(
            f"| {c['label']} | {c['part']} | {c['question_set']} | {s['runs']} | {_pct(s['shares']['right'])} | {_pct(s['shares']['confidently_wrong'])} | {_pct(s['shares']['declined'])} | {_pct(s['shares']['no_answer'])} | {_usd(s['cost_per_run_usd'], True)} | {_usd(s['cost_per_correct_usd'], True)} | {_usd(jan, True)} | {s['input_tokens_per_run']:,.0f} | {s['model_calls_per_run']:.2f} | {s['input_tokens_per_model_call']:,.0f} | {_pct(s['cached_share_of_input'])} |"
        )
    lines += [
        "",
        "## Cost per correct answer by question group (24 Part 1 questions)",
        "",
        "| Configuration | Lookup | Metric | Entity | Rule |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in n["configurations"].values():
        if c["question_set"] != "part1" or not c["by_group"]:
            continue
        cells = []
        for g in ("lookup", "metric", "entity", "rule"):
            gr = c["by_group"].get(g)
            cells.append(
                "n/a"
                if not gr
                else f"{_usd(gr['cost_per_correct_usd'], True)} ({gr['outcomes']['right']}/{gr['runs']})"
            )
        lines.append(f"| {c['label']} | " + " | ".join(cells) + " |")
    w = n["spend_by_outcome_24_questions"]
    lines += [
        "",
        "## Where the money went (all scored runs on the 24 questions)",
        "",
        f"Total {_usd(w['spend_usd'])}: "
        + ", ".join(f"{o.replace('_', ' ')} {_usd(v)}" for o, v in w["by_outcome_usd"].items())
        + ".",
    ]
    t = n["totals"]
    lines += [
        "",
        "## Totals",
        "",
        f"- Scored runs: {_usd(t['scored_runs_usd'])}",
        f"- Failed attempts that were run again: {_usd(t['replaced_attempts_usd'])}",
        f"- Smoke tests and discarded runs: {_usd(t['smoke_and_discarded_total_usd'])}",
        f"- Claude demonstration (not scored): {_usd(t['claude_demo_usd'])}",
        f"- All recorded: {_usd(t['all_recorded_usd'])}",
    ]
    b = n["budget"]
    lines += [
        "",
        "## Budget check",
        "",
        f"Agent `{b['agent']}`, owner {b['owner']} (a fictional role), {_usd(b['limit_per_task_usd'])} per task, {_usd(b['limit_per_day_usd'])} per day.",
        "",
        "| Configuration | Runs over the per-task limit |",
        "| --- | --- |",
    ]
    for key, count in b["runs_over_task_limit"].items():
        lines.append(f"| {n['configurations'][key]['label']} | {count} |")
    lines += ["", "| Day (UTC) | Recorded spend | Over the daily limit |", "| --- | --- | --- |"]
    for day, usd in b["spend_by_day_usd"].items():
        lines.append(f"| {day} | {_usd(usd)} | {'yes' if day in b['days_over_limit'] else 'no'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
