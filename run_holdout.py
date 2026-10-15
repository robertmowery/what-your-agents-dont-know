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

"""Runs the held-out fairness test for Part 2.

In Part 2 the semantic layer took the Flash agent from 43.8% right to 100% on
the 24 Part 1 questions. The layer was written by someone who knew those
questions. ``questions/holdout.yaml`` holds 12 questions written afterward by
a writer who was not shown the layer (see ``data/HOLDOUT.md``). This script
asks them of two agents and changes nothing else:

    baseline         the Part 1 Flash agent: the schema and the SQL tool
    flash_semantic   the Part 2 semantic configuration: the same, plus query_metrics

The agents, the instruction, the tools, the limits and the scorer are imported
from Part 1 and Part 2 as they are. Nothing under ``results/part1`` or
``results/part2`` is written. ``results/holdout/coverage.json``, written by
``analysis/holdout_coverage.py`` before any run, says what the layer could
answer; this script reads it to group the results and does not change it.

Usage:
    python run_holdout.py [CONFIG ...] [options]

    python run_holdout.py                                    # both configurations, 3 runs each
    python run_holdout.py --runs 1 --questions H1,H5 --out smoke
    python run_holdout.py --summarize-only

Options:
    --runs N           Runs per question (default 3).
    --questions IDS    Comma-separated question ids (default: all 12).
    --concurrency N    Questions in flight at once (default 6).
    --budget-usd X     Stop starting new runs once estimated held-out spend, across
                       every saved run under results/holdout, reaches X (default 5).
    --out NAME         Write under results/holdout/NAME (used for the smoke test).
    --retry-failed     Run again, once, any saved run that ended with no answer
                       because of an error or a timeout. The Part 1 rule.
    --summarize-only   Score the saved replies again and rewrite the summaries.
    --redact-saved     Replace the Google Cloud project ID with ``PROJECT`` in the saved
                       runs first (no model or cloud call). New runs are saved that
                       way already, through ``run_part2.to_row``.

Files written (under results/holdout):
    runs/<config>.jsonl       one line per run, appended as it finishes (resumable)
    <config>.json             every run for a configuration, with its metadata
    summary.json, summary.md  both configurations, by group, coverage class and question
    spend.json                estimated held-out spend across everything run so far
and the "holdout" entry of ``results/series_spend.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_part1
import run_part2
from tessaway import config, questions, scoring
from tessaway.agents import adk_agent, adk_layer_agent, layer_prompt, prompt
from tessaway.layers import MAX_LAYER_CALLS
from tessaway.warehouse import generate

ROOT = Path(__file__).parent
RESULTS = ROOT / "results" / "holdout"
QUESTIONS_PATH = ROOT / "questions" / "holdout.yaml"
GOLD_PATH = RESULTS / "gold_answers.json"
COVERAGE_PATH = RESULTS / "coverage.json"
PART2_SUMMARY_PATH = ROOT / "results" / "part2" / "summary.json"
DEFAULT_RUNS = 3
DEFAULT_BUDGET_USD = 5.0
LINE_USD = 4.0

BASE = run_part2.BASE
BASELINE = "baseline"
SEMANTIC = "flash_semantic"

# Configuration name -> the layers whose tools the agent is given.
CONFIGS: dict[str, tuple[str, ...]] = {BASELINE: (), SEMANTIC: ("semantic",)}

CLASSES = ("one_metric_query", "metric_plus_filter", "several_or_arithmetic", "not_answerable")
# The classes in which one metric query answers the question. A run on such a
# question that ran SQL anyway went around the semantic layer (the bypass count).
ONE_QUERY_CLASSES = ("one_metric_query", "metric_plus_filter")
GROUPS = ("metric", "entity", "rule")

Asker = Callable[[str, questions.Question], Awaitable[prompt.AgentRun]]


async def ask(name: str, question: questions.Question) -> prompt.AgentRun:
    """Ask one question of one configuration, through the Part 1 or Part 2 agent."""
    if name == BASELINE:
        return await adk_agent.ask(BASE.model, question.question)
    return await adk_layer_agent.ask(BASE.model, question.question, CONFIGS[name])


def to_row(
    name: str, question: questions.Question, trial: int, run: prompt.AgentRun, gold: dict[str, Any]
) -> dict[str, Any]:
    """Score one run with the Part 1 scorer and flatten it into the saved row.

    A semantic-layer run is saved by ``run_part2.to_row``. A baseline run is
    saved by ``run_part1.to_row`` and given the tool-call fields the Part 2
    rows have, worked out from its SQL queries, so one summary reads both.
    """
    if isinstance(run, adk_layer_agent.LayerAgentRun):
        return run_part2.to_row(name, question, trial, run, gold)
    row = run_part1.to_row(BASE, question, trial, run, gold)
    let_through = len(run.queries)
    row.update(
        {
            "config": name,
            "layers": [],
            "tool_calls": [
                {"seq": n + 1, "tool": prompt.TOOL_NAME, "arguments": {"sql": q.get("sql", "")}}
                for n, q in enumerate(run.queries)
            ],
            "tool_call_counts": {prompt.TOOL_NAME: let_through} if let_through else {},
            "tools_in_order": [prompt.TOOL_NAME] * let_through,
            "layer_calls_refused": {},
            "hit_model_call_ceiling": "LlmCallsLimit" in run.error,
        }
    )
    return row


def spend(root: Path = RESULTS) -> dict[str, Any]:
    """Add up estimated held-out spend across every saved run, smoke test included."""
    by_folder: dict[str, dict[str, float]] = {}
    for path in sorted(root.rglob("runs/*.jsonl")):
        folder = str(path.parent.parent.relative_to(root))
        entry = by_folder.setdefault(
            "full run" if folder == "." else folder,
            {"runs": 0, "model_usd": 0.0, "bigquery_usd": 0.0},
        )
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            entry["runs"] += 1
            entry["model_usd"] += float(row.get("cost_usd") or 0)
            entry["bigquery_usd"] += float(row.get("bigquery_usd") or 0)
    for entry in by_folder.values():
        entry["model_usd"] = round(entry["model_usd"], 4)
        entry["bigquery_usd"] = round(entry["bigquery_usd"], 4)
    return {
        "note": (
            "Estimated from token counts and list prices in tessaway/config.py, and from"
            " BigQuery bytes billed at the on-demand rate. Every line ever appended under"
            " results/holdout is counted: the full run, the smoke test and any run later"
            " repeated. The invoice is the authority."
        ),
        "prices_checked_on": config.MODELS_VERIFIED_ON,
        "by_folder": by_folder,
        "model_usd": round(sum(e["model_usd"] for e in by_folder.values()), 4),
        "bigquery_usd": round(sum(e["bigquery_usd"] for e in by_folder.values()), 4),
        "total_usd": round(sum(e["model_usd"] + e["bigquery_usd"] for e in by_folder.values()), 4),
    }


def write_ledger(ledger_path: Path = run_part2.LEDGER_PATH, root: Path = RESULTS) -> dict[str, Any]:
    """Add the held-out test to the series ledger, leaving every other entry as it is."""
    ledger: dict[str, Any] = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    parts = dict(ledger.get("parts", {}))
    mine = spend(root)
    parts["holdout"] = {
        "what": "Held-out fairness test for Part 2: 12 questions, baseline and semantic layer.",
        "line_usd": LINE_USD,
        "spent_usd": mine["total_usd"],
        "model_usd": mine["model_usd"],
        "bigquery_usd": mine["bigquery_usd"],
        "by_folder": mine["by_folder"],
    }
    spent = round(sum(float(p.get("spent_usd") or 0) for p in parts.values()), 4)
    approved = float(ledger.get("approved_usd_parts_2_to_7", run_part2.SERIES_APPROVED_USD))
    cap = float(ledger.get("hard_cap_usd_parts_2_to_7", run_part2.SERIES_CAP_USD))
    ledger.update(
        {
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "parts": parts,
            "spent_usd_parts_2_to_7": spent,
            "remaining_to_approved_usd": round(approved - spent, 4),
            "remaining_to_hard_cap_usd": round(cap - spent, 4),
        }
    )
    ledger_path.write_text(json.dumps(ledger, indent=1) + "\n")
    return ledger


async def run_config(
    name: str,
    asked: list[questions.Question],
    gold: dict[str, Any],
    *,
    runs: int,
    concurrency: int,
    budget_usd: float,
    out: Path,
    retry_failed: bool,
    asker: Asker = ask,
    spend_root: Path = RESULTS,
) -> None:
    """Run one configuration, appending each finished run to its JSONL file.

    The loop is the one in ``run_part2.run_config``: resumable, a budget stop,
    and at most one repeat of a run that ended in an error or a timeout.
    """
    path = out / "runs" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = {(r["question_id"], r["trial"]): r for r in run_part1.read_runs(path)}
    todo = []
    for trial in range(runs):
        for question in asked:
            saved = done.get((question.id, trial))
            if saved is None or (
                retry_failed
                and saved["outcome"] == scoring.NO_ANSWER
                and (saved.get("error") or saved.get("timed_out"))
                and not saved.get("retry_of_failed")
            ):
                todo.append((question, trial))
    print(f"[{name}] {len(todo)} run(s) to do, {len(done)} already saved", flush=True)
    if not todo:
        return
    if asker is ask and CONFIGS[name]:
        await asyncio.to_thread(adk_layer_agent.warm_up, CONFIGS[name])

    gate = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    state = {"spent": float(spend(spend_root)["total_usd"]), "stopped": False, "finished": 0}

    async def one(question: questions.Question, trial: int) -> None:
        async with gate:
            if state["spent"] >= budget_usd:
                state["stopped"] = True
                return
            run = await asker(name, question)
            row = to_row(name, question, trial, run, gold[question.id])
            if (question.id, trial) in done:
                row["retry_of_failed"] = True
            async with lock:
                with path.open("a") as handle:
                    handle.write(json.dumps(row) + "\n")
                state["spent"] += row["cost_usd"] + row["bigquery_usd"]
                state["finished"] += 1
                used = ",".join(f"{t}={n}" for t, n in sorted(row["tool_call_counts"].items()))
                print(
                    f"[{name}] {question.id} #{trial} {row['outcome']:<17}"
                    f" {row['extracted'][:32]!r} [{used}] ${row['cost_usd']:.4f}"
                    f" total=${state['spent']:.2f} ({state['finished']}/{len(todo)})",
                    flush=True,
                )

    await asyncio.gather(*(one(question, trial) for question, trial in todo))
    if state["stopped"]:
        print(f"[{name}] STOPPED at the budget of ${budget_usd:.2f}; the run is partial.")


def coverage_classes(path: Path = COVERAGE_PATH) -> dict[str, str]:
    """Return each question's coverage class, as fixed before the runs."""
    report = json.loads(path.read_text())
    return {entry["question_id"]: entry["class"] for entry in report["questions"]}


def calls(row: dict[str, Any], tool: str) -> int:
    """Return how many calls to a tool a run made that were let through."""
    return int(row["tool_call_counts"].get(tool, 0))


def tool_use(rows: list[dict[str, Any]], classes: dict[str, str]) -> dict[str, Any]:
    """Count SQL and metric-tool calls, and the bypass count, for one set of runs."""
    sql, metric = prompt.TOOL_NAME, layer_prompt.SEMANTIC_TOOL
    count = len(rows)

    def split(items: list[dict[str, Any]]) -> dict[str, Any]:
        metrics_only = [r for r in items if calls(r, metric) and not calls(r, sql)]
        both = [r for r in items if calls(r, metric) and calls(r, sql)]
        sql_only = [r for r in items if calls(r, sql) and not calls(r, metric)]
        neither = [r for r in items if not calls(r, sql) and not calls(r, metric)]
        return {
            "runs": len(items),
            "metric_tool_only": len(metrics_only),
            "both_tools": len(both),
            "sql_only": len(sql_only),
            "no_tool_call": len(neither),
            "outcomes_metric_tool_only": scoring.shares([r["outcome"] for r in metrics_only]),
            "outcomes_both_tools": scoring.shares([r["outcome"] for r in both]),
            "outcomes_sql_only": scoring.shares([r["outcome"] for r in sql_only]),
        }

    one_query = [r for r in rows if classes[r["question_id"]] in ONE_QUERY_CLASSES]
    around = [r for r in one_query if calls(r, sql)]
    return {
        "runs": count,
        "mean_calls_per_run": {
            tool: round(sum(calls(r, tool) for r in rows) / count, 2) if count else 0.0
            for tool in (sql, metric)
        },
        "total_calls": {tool: sum(calls(r, tool) for r in rows) for tool in (sql, metric)},
        "runs_that_called": {
            tool: sum(1 for r in rows if calls(r, tool)) for tool in (sql, metric)
        },
        "runs_whose_first_call_was_sql": sum(1 for r in rows if r["tools_in_order"][:1] == [sql]),
        "metric_calls_that_returned_an_error": sum(
            1
            for r in rows
            for call in r["tool_calls"]
            if call["tool"] == metric and call.get("error") and not call.get("refused")
        ),
        "all_runs": split(rows),
        "by_coverage_class": {
            kind: split([r for r in rows if classes[r["question_id"]] == kind])
            for kind in CLASSES
            if any(classes[r["question_id"]] == kind for r in rows)
        },
        "went_around_the_semantic_layer": {
            "what": "Runs on a question that one metric query answers (coverage classes"
            " one_metric_query and metric_plus_filter), in which the agent ran at least one"
            " SQL query.",
            "runs_on_such_questions": len(one_query),
            "runs_that_ran_sql": len(around),
            "of_which_never_called_the_metric_tool": sum(1 for r in around if not calls(r, metric)),
            "of_which_called_both": sum(1 for r in around if calls(r, metric)),
            "outcomes_when_sql_was_run": scoring.shares([r["outcome"] for r in around]),
            "runs_answered_from_metrics_alone": len(one_query) - len(around),
            "outcomes_from_metrics_alone": scoring.shares(
                [r["outcome"] for r in one_query if not calls(r, sql)]
            ),
        },
    }


def by_class(rows: list[dict[str, Any]], classes: dict[str, str]) -> dict[str, Any]:
    """Return the outcome shares for each coverage class."""
    result: dict[str, Any] = {}
    for kind in CLASSES:
        items = [r for r in rows if classes[r["question_id"]] == kind]
        if items:
            result[kind] = {
                **scoring.shares([r["outcome"] for r in items]),
                "questions": sorted({r["question_id"] for r in items}, key=question_order),
            }
    return result


def question_order(qid: str) -> int:
    """Sort H2 before H10."""
    return int(qid[1:]) if qid[1:].isdigit() else 0


def answers_given(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Return, for each question, what each run answered and how it was scored."""
    result: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda r: (question_order(r["question_id"]), r["trial"])):
        result.setdefault(row["question_id"], []).append(
            {
                "trial": row["trial"],
                "outcome": row["outcome"],
                "answer": row["extracted"],
                "matched_decoy": row.get("matched_decoy", ""),
            }
        )
    return result


def write_config_file(
    name: str,
    asked: list[questions.Question],
    gold: dict[str, Any],
    classes: dict[str, str],
    *,
    runs: int,
    out: Path,
) -> dict[str, Any] | None:
    """Write ``<config>.json`` from the saved runs and return its summary block."""
    rows = run_part1.read_runs(out / "runs" / f"{name}.jsonl")
    if not rows:
        return None
    by_id = {q.id: q for q in asked}
    rows = [
        config.redact_project(r) for r in rows if r["question_id"] in by_id and r["trial"] < runs
    ]
    if not rows:
        return None
    for row in rows:
        run_part1.rescore(row, by_id, gold)
    layers = CONFIGS[name]
    expected = len(asked) * runs
    block = {
        "config": name,
        "what": "The Part 1 Flash agent: the schema and the SQL tool only."
        if name == BASELINE
        else "The Part 2 semantic configuration: the same agent with the query_metrics tool.",
        "layers": list(layers),
        "tools": [prompt.TOOL_NAME, *(layer_prompt.TOOL_OF_LAYER[layer] for layer in layers)],
        "runtime": BASE.runtime,
        "runtime_package": f"google-adk=={importlib.metadata.version('google-adk')}",
        "model": BASE.model,
        "model_reported_by_provider": sorted(
            {r["model_reported"] for r in rows if r.get("model_reported")}
        ),
        "model_and_prices_checked_on": config.MODELS_VERIFIED_ON,
        "usd_per_million_tokens": {
            "input": BASE.usd_in,
            "output": BASE.usd_out,
            "cache_read": BASE.usd_cache_read,
        },
        "first_run_finished_at": min(r["finished_at"] for r in rows),
        "last_run_finished_at": max(r["finished_at"] for r in rows),
        "question_file": str(QUESTIONS_PATH.relative_to(ROOT)),
        "question_count": len(asked),
        "runs_per_question": runs,
        "runs_expected": expected,
        "runs_saved": len(rows),
        "complete": len(rows) == expected,
        "runs_repeated_after_a_failure": sum(1 for r in rows if r.get("retry_of_failed")),
        "sql_query_limit": prompt.MAX_QUERIES,
        "layer_call_limit_per_tool": MAX_LAYER_CALLS if layers else None,
        "model_call_ceiling": adk_layer_agent.max_model_calls(layers),
        "data_seed": generate.SEED,
        "summary": scoring.summarize(rows),
        "by_coverage_class": by_class(rows, classes),
        "answers_given": answers_given(rows),
        "effort": run_part2.effort(rows),
        "tool_use": tool_use(rows, classes),
        "limits": run_part2.limits(rows),
    }
    (out / f"{name}.json").write_text(json.dumps({**block, "runs": rows}, indent=1) + "\n")
    return block


def points(now: dict[str, Any], before: dict[str, Any]) -> dict[str, float]:
    """Return the change from one set of shares to another, in percentage points."""
    return {
        name: round(100 * (now[f"{name}_share"] - before[f"{name}_share"]), 1)
        for name in (scoring.RIGHT, scoring.WRONG, scoring.DECLINED)
    }


def changes(block: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Return the semantic configuration's change against the held-out baseline."""
    result: dict[str, Any] = {
        "overall": points(block["summary"]["overall"], base["summary"]["overall"]),
        "by_group": {},
        "by_coverage_class": {},
    }
    for group, entry in block["summary"]["by_group"].items():
        if group in base["summary"]["by_group"]:
            result["by_group"][group] = points(entry, base["summary"]["by_group"][group])
    for kind, entry in block["by_coverage_class"].items():
        if kind in base["by_coverage_class"]:
            result["by_coverage_class"][kind] = points(entry, base["by_coverage_class"][kind])
    return result


def part2_figures(path: Path = PART2_SUMMARY_PATH) -> dict[str, Any]:
    """Read the 24-question figures this test is set beside. Nothing there is changed."""
    if not path.exists():
        return {}
    saved = json.loads(path.read_text())
    semantic = next((b for b in saved["configurations"] if b["config"] == SEMANTIC), None)
    if semantic is None:
        return {}
    return {
        "source": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "questions": 24,
        "baseline": {**saved["baseline"]["summary"]["overall"], "runs_per_question": 10},
        SEMANTIC: {**semantic["summary"]["overall"], "runs_per_question": 3},
        "change_points": points(
            semantic["summary"]["overall"], saved["baseline"]["summary"]["overall"]
        ),
    }


def pct(share: float | None) -> str:
    """Format a share as a percentage."""
    return run_part1.pct(share)


def triple(entry: dict[str, Any]) -> str:
    """Format right / confidently wrong / declined / no answer as counts."""
    return (
        f"{entry['right']} / {entry['confidently_wrong']} / {entry['declined']}"
        f" / {entry['no_answer']}"
    )


def write_summary(
    blocks: list[dict[str, Any]],
    asked: list[questions.Question],
    gold: dict[str, Any],
    coverage: dict[str, Any],
    out: Path,
) -> None:
    """Write ``summary.json`` and ``summary.md``: both configurations side by side."""
    classes = {entry["question_id"]: entry["class"] for entry in coverage["questions"]}
    labels: dict[str, str] = coverage["classes"]
    by_name = {b["config"]: b for b in blocks}
    base, layer = by_name.get(BASELINE), by_name.get(SEMANTIC)
    change = changes(layer, base) if base and layer else None
    part2 = part2_figures()
    payload = {
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "bins": list(scoring.BINS),
        "note": (
            "Twelve held-out questions, three runs each: 36 runs a configuration. One run is"
            " 2.8 points of an overall share and 8.3 points within a question group of four."
            " Small differences are not findings."
        ),
        "coverage_checked_at": coverage["checked_at"],
        "coverage_counts": coverage["counts"],
        "coverage_class_of_question": classes,
        "configurations": blocks,
        "change_semantic_vs_baseline_points": change,
        "on_the_24_part_1_questions": part2,
        "not_run": [name for name in CONFIGS if name not in by_name],
    }
    (out / "summary.json").write_text(json.dumps(payload, indent=1) + "\n")

    lines = [
        "# Held-out fairness test for Part 2",
        "",
        "Written by `run_holdout.py`. Tessaway Freight is a fictional company and the data is"
        " synthetic.",
        "",
        "Twelve questions written after the Part 2 layers were committed, by a writer who was"
        " not shown the layers (`data/HOLDOUT.md`). Two agents on `" + BASE.model + "` with"
        " Google ADK: the Part 1 agent (schema and the SQL tool), and the same agent with the"
        " semantic layer's `query_metrics` tool. The layer, the tool description, the"
        " instruction and the scorer are Part 2's, unchanged. Each reply is scored into one of"
        " four bins. Shares are of all runs.",
        "",
        "Each question ran three times: 36 runs a configuration. One run is 2.8 points of an"
        " overall share and 8.3 points within a question group. Small differences are not"
        " findings.",
        "",
        "| Configuration | Tools beside `run_sql` | Runs | Complete | Right | Confidently wrong"
        " | Declined | No answer | Est. cost | Cost per question |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for block in blocks:
        overall = block["summary"]["overall"]
        extra = ", ".join(f"`{t}`" for t in block["tools"][1:]) or "none"
        lines.append(
            f"| {block['config']} | {extra} | {block['runs_saved']} of {block['runs_expected']}"
            f" | {'yes' if block['complete'] else 'NO, partial'}"
            f" | {pct(overall['right_share'])} | {pct(overall['confidently_wrong_share'])}"
            f" | {pct(overall['declined_share'])} | {pct(overall['no_answer_share'])}"
            f" | ${block['effort']['total_cost_usd']:.2f}"
            f" | ${block['effort']['mean_cost_usd']:.4f} |"
        )
    if change:
        c = change["overall"]
        lines += [
            "",
            "Change from baseline to semantic layer, in percentage points: right"
            f" {c['right']:+.1f}, confidently wrong {c['confidently_wrong']:+.1f}, declined"
            f" {c['declined']:+.1f}.",
        ]
    if part2:
        lines += [
            "",
            "## Beside the 24 Part 1 questions",
            "",
            "| Question set | Baseline right | Semantic layer right | Change in points |",
            "| --- | --- | --- | --- |",
            f"| 24 Part 1 questions (the layer's author knew them) |"
            f" {pct(part2['baseline']['right_share'])}"
            f" | {pct(part2[SEMANTIC]['right_share'])} | {part2['change_points']['right']:+.1f} |",
        ]
        if base and layer and change:
            lines.append(
                "| 12 held-out questions |"
                f" {pct(base['summary']['overall']['right_share'])}"
                f" | {pct(layer['summary']['overall']['right_share'])}"
                f" | {change['overall']['right']:+.1f} |"
            )
        lines += [
            "",
            "The 24 include six lookup questions that every configuration gets right; the"
            " held-out set has none. The Part 1 baseline ran each question ten times.",
        ]

    lines += [
        "",
        "## By question group: right / confidently wrong / declined / no answer",
        "",
        "| Configuration | " + " | ".join(GROUPS) + " |",
        "| --- |" + " --- |" * len(GROUPS),
    ]
    for block in blocks:
        groups = block["summary"]["by_group"]
        cells = [
            f"{triple(groups[g])} ({pct(groups[g]['right_share'])} right)" if g in groups else "n/a"
            for g in GROUPS
        ]
        lines.append(f"| {block['config']} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## By coverage class: right / confidently wrong / declined / no answer",
        "",
        "The class says what the semantic layer could answer, and was fixed in"
        " `coverage.json` before any run (`coverage.md`).",
        "",
        "| Coverage class | Questions | " + " | ".join(b["config"] for b in blocks) + " |",
        "| --- | --- |" + " --- |" * len(blocks),
    ]
    for kind in CLASSES:
        ids = [q.id for q in asked if classes[q.id] == kind]
        cells = []
        for block in blocks:
            entry = block["by_coverage_class"].get(kind)
            cells.append(f"{triple(entry)} ({pct(entry['right_share'])} right)" if entry else "n/a")
        lines.append(f"| {labels[kind]} | {', '.join(ids) or 'none'} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## By question",
        "",
        "Counts are right / confidently wrong / declined / no answer. Answers are the final"
        " line of each run, in run order.",
        "",
        "| Question | Group | Coverage class | Gold | "
        + " | ".join(f"{b['config']} | {b['config']} answers" for b in blocks)
        + " |",
        "| --- | --- | --- | --- |" + " --- | --- |" * len(blocks),
    ]
    for question in asked:
        cells = []
        for block in blocks:
            entry = block["summary"]["by_question"].get(question.id)
            given = block["answers_given"].get(question.id, [])
            cells.append(triple(entry) if entry else "n/a")
            cells.append("; ".join(str(g["answer"] or "(none)") for g in given))
        lines.append(
            f"| {question.id} | {question.group} | {classes[question.id]}"
            f" | {gold[question.id]['gold']} | " + " | ".join(cells) + " |"
        )
    lines += ["", "The questions:", ""]
    lines += [f"- {q.id}: {q.question}" for q in asked]

    if layer:
        use = layer["tool_use"]
        lines += [
            "",
            "## Tool calls, semantic-layer configuration",
            "",
            f"Mean calls per run: `run_sql` {use['mean_calls_per_run'][prompt.TOOL_NAME]:.2f},"
            f" `query_metrics` {use['mean_calls_per_run'][layer_prompt.SEMANTIC_TOOL]:.2f}."
            f" {use['runs_that_called'][layer_prompt.SEMANTIC_TOOL]} of {use['runs']} runs"
            f" called the metric tool and {use['runs_that_called'][prompt.TOOL_NAME]} ran SQL."
            f" The first call was SQL in {use['runs_whose_first_call_was_sql']} runs."
            f" {use['metric_calls_that_returned_an_error']} metric calls came back with an"
            " error.",
            "",
            "| Coverage class | Runs | Metric tool only | Both tools | SQL only | No tool call"
            " | Right, metric tool only | Right, both | Right, SQL only |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        rows = [(labels[k], v) for k, v in use["by_coverage_class"].items()]
        for label, entry in [*rows, ("all", use["all_runs"])]:
            lines.append(
                f"| {label} | {entry['runs']} | {entry['metric_tool_only']}"
                f" | {entry['both_tools']} | {entry['sql_only']} | {entry['no_tool_call']}"
                f" | {entry['outcomes_metric_tool_only']['right']} of {entry['metric_tool_only']}"
                f" | {entry['outcomes_both_tools']['right']} of {entry['both_tools']}"
                f" | {entry['outcomes_sql_only']['right']} of {entry['sql_only']} |"
            )
        around = use["went_around_the_semantic_layer"]
        lines += [
            "",
            "### Going around the semantic layer",
            "",
            "The bypass count: runs on a question that one metric query answers (the first"
            f" two coverage classes), in which the agent ran SQL anyway."
            f" {around['runs_that_ran_sql']} of {around['runs_on_such_questions']} such runs ran"
            f" SQL ({around['of_which_never_called_the_metric_tool']} never called the metric"
            f" tool, {around['of_which_called_both']} called both);"
            f" {around['outcomes_when_sql_was_run']['right']} of those were right."
            f" {around['runs_answered_from_metrics_alone']} were answered from metrics alone,"
            f" {around['outcomes_from_metrics_alone']['right']} of them right.",
        ]

    lines += [
        "",
        "## Tokens, time and cost per question",
        "",
        "| Configuration | Input tokens | Output tokens | Cache-read share of input"
        " | Model calls | SQL queries | Seconds | Cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for block in blocks:
        e = block["effort"]
        lines.append(
            f"| {block['config']} | {e['mean_input_tokens']:,d} | {e['mean_output_tokens']:,d}"
            f" | {pct(e['cache_read_share_of_input'])} | {e['mean_model_calls']:.2f}"
            f" | {e['mean_sql_queries']:.2f} | {e['mean_seconds']:.1f}"
            f" | ${e['mean_cost_usd']:.4f} |"
        )
    lines += [
        "",
        "## Limits",
        "",
        f"Each question allows {prompt.MAX_QUERIES} SQL queries and, with the semantic layer,"
        f" {MAX_LAYER_CALLS} metric calls; the agent is told both. The ceilings on model calls"
        " are Part 1's and Part 2's.",
        "",
        "| Configuration | Model-call ceiling | Asked for a further SQL query"
        " | Asked for a further metric call | Hit the model-call ceiling | Timed out"
        " | Ended in an error | Repeated once after a failure"
        " | Declines that mention the query limit |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for block in blocks:
        lim, summary = block["limits"], block["summary"]
        lines.append(
            f"| {block['config']} | {block['model_call_ceiling']}"
            f" | {lim['runs_refused_a_further_sql_query']} of {block['runs_saved']}"
            f" | {lim['runs_refused_a_further_layer_call'] if block['layers'] else 'n/a'}"
            f" | {lim['runs_that_hit_the_model_call_ceiling']}"
            f" | {lim['runs_that_timed_out']} | {lim['runs_that_ended_in_an_error']}"
            f" | {block['runs_repeated_after_a_failure']}"
            f" | {summary['declines_that_mention_the_query_limit']} of {summary['declines']} |"
        )
    if payload["not_run"]:
        lines += ["", "## Not run", ""]
        lines += [f"- {name}" for name in payload["not_run"]]
    lines += [
        "",
        "Model names and prices were checked on "
        f"{config.MODELS_VERIFIED_ON}. Costs are estimates from token counts and list prices.",
        "",
    ]
    (out / "summary.md").write_text("\n".join(lines))


async def main(args: argparse.Namespace) -> None:
    """Run the requested configurations, then write every results file."""
    out = RESULTS / args.out if args.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    wanted = set(args.questions.split(",")) if args.questions else None
    asked = [q for q in questions.load(QUESTIONS_PATH) if wanted is None or q.id in wanted]
    names = args.configs or list(CONFIGS)
    unknown = [n for n in names if n not in CONFIGS]
    if unknown:
        raise SystemExit(f"Unknown configuration(s): {', '.join(unknown)}")
    if not COVERAGE_PATH.exists():
        raise SystemExit(
            "Run analysis/holdout_coverage.py first: coverage is fixed before any run."
        )
    gold = questions.load_gold(GOLD_PATH)
    coverage = json.loads(COVERAGE_PATH.read_text())
    classes = coverage_classes()

    if args.redact_saved:
        changed = run_part2.redact_saved_runs(out)
        print(f"replaced the project ID in {changed} saved run(s) under {out}")
    if not args.summarize_only:
        for name in names:
            await run_config(
                name, asked, gold, runs=args.runs, concurrency=args.concurrency,
                budget_usd=args.budget_usd, out=out, retry_failed=args.retry_failed,
            )  # fmt: skip

    blocks = []
    for name in CONFIGS:
        block = write_config_file(name, asked, gold, classes, runs=args.runs, out=out)
        if block is not None:
            blocks.append(block)
    write_summary(blocks, asked, gold, coverage, out)
    (RESULTS / "spend.json").write_text(json.dumps(spend(), indent=1) + "\n")
    ledger = write_ledger()
    print(f"estimated held-out spend so far: ${spend()['total_usd']:.2f}")
    print(f"Parts 2 to 7 so far: ${ledger['spent_usd_parts_2_to_7']:.2f}"
          f" (hard cap ${ledger['hard_cap_usd_parts_2_to_7']:.0f})")  # fmt: skip
    print(f"results in {out}")


def parse_args() -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description="Run the held-out fairness test for Part 2.")
    parser.add_argument("configs", nargs="*", help=f"Any of: {', '.join(CONFIGS)}")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--questions", default="")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--out", default="")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--redact-saved", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
