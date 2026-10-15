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

"""Runs the Part 2 experiment and writes every number the articles use.

Part 2 asks the Part 1 questions again, of the Part 1 agent on the Part 1
warehouse, with a context layer added: a semantic layer, an ontology, a
knowledge graph, and then all three. Each layer reaches the agent as one extra
tool beside the same SQL tool. The questions, the correct answers and the
scorer are Part 1's, unchanged.

The baseline is Part 1's ``adk_gemini_flash`` results (ten runs per question).
It is read from ``results/part1`` and is not run again.

Usage:
    python run_part2.py [CONFIG ...] [options]

    python run_part2.py                                    # all four configurations, 3 runs each
    python run_part2.py flash_semantic --runs 1 --questions L1,M1 --out smoke
    python run_part2.py --summarize-only                   # rebuild the summary from saved runs

Options:
    --runs N           Runs per question (default 3).
    --questions IDS    Comma-separated question ids (default: all).
    --concurrency N    Questions in flight at once (default 6).
    --budget-usd X     Stop starting new runs once estimated Part 2 spend, across every
                       saved run under results/part2, reaches X (default 14).
    --out NAME         Write under results/part2/NAME instead of results/part2.
                       Used for smoke tests so they never mix with the full run.
    --retry-failed     Run again any saved run that ended with no answer because
                       of an error or a timeout. Done at most once.
    --summarize-only   Score the saved replies again and rewrite the summaries.
    --redact-saved     Replace the Google Cloud project ID with ``PROJECT`` in the saved
                       runs first. New runs are saved that way already. With
                       --summarize-only this makes no model or cloud call.

The project ID never appears in a results file: MetricFlow's SQL names it, and
every row is passed through ``config.redact_project`` before it is saved.

Files written (under results/part2):
    runs/<config>.jsonl       one line per run, appended as it finishes (resumable)
    <config>.json             every run for a configuration, with its metadata
    summary.json, summary.md  every configuration beside the Part 1 baseline
    spend.json                estimated Part 2 spend across everything run so far
and ``results/series_spend.json``, the ledger for Parts 2 to 7.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

import run_part1
from tessaway import config, questions, scoring
from tessaway.agents import adk_layer_agent, layer_prompt, prompt
from tessaway.layers import LAYERS, MAX_LAYER_CALLS, semantic
from tessaway.warehouse import generate

ROOT = Path(__file__).parent
RESULTS = ROOT / "results" / "part2"
BASELINE_PATH = ROOT / "results" / "part1" / "adk_gemini_flash.json"
LEDGER_PATH = ROOT / "results" / "series_spend.json"
DEFAULT_RUNS = 3
DEFAULT_BUDGET_USD = 14.0

# The one model this part runs, with Part 1's prices.
BASE = config.CONFIGS["adk_gemini_flash"]

# Configuration name -> the layers whose tools the agent is given.
LAYER_CONFIGS: dict[str, tuple[str, ...]] = {
    "flash_semantic": ("semantic",),
    "flash_ontology": ("ontology",),
    "flash_graph": ("graph",),
    "flash_all_three": LAYERS,
}

# What Robert approved for model spend after Part 1, and what Part 1 had cost.
SERIES_APPROVED_USD = 35.0
SERIES_CAP_USD = 45.0
PART1_SPENT_USD = 26.52
PART2_LINE_USD = 9.60

ALL_TOOLS = (prompt.TOOL_NAME, *(layer_prompt.TOOL_OF_LAYER[layer] for layer in LAYERS))

# The relationships the knowledge graph holds are the ones these two
# definitions are about: which site rolls up to which customer, and which rows
# are one load.
GRAPH_DEFINITIONS = {"customer", "load"}


def semantic_answerable() -> set[str]:
    """Return the questions one metric query answers, per the gold checks."""
    cases = yaml.safe_load(semantic.GOLD_CHECKS_PATH.read_text())
    return {case["question"] for case in cases if "question" in case}


def applies_to(layer: str, question: questions.Question) -> bool:
    """Say whether a layer holds something a question needs.

    Fixed before any run. The semantic layer applies when one metric query
    answers the question. The ontology applies when an official definition
    decides the question. The graph applies when one of the definitions that
    decide it is about a relationship the graph holds.
    """
    if layer == "semantic":
        return question.id in semantic_answerable()
    if layer == "ontology":
        return bool(question.definitions)
    return bool(GRAPH_DEFINITIONS & set(question.definitions))


def spend(root: Path = RESULTS) -> dict[str, Any]:
    """Add up estimated Part 2 spend across every saved run, smoke tests included."""
    by_folder: dict[str, dict[str, float]] = {}
    for path in sorted(root.rglob("runs/*.jsonl")):
        folder = str(path.parent.parent.relative_to(root)) or "."
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
            " results/part2 is counted: the full run, smoke tests, runs that were later"
            " repeated and any discarded runs. The invoice is the authority."
        ),
        "prices_checked_on": config.MODELS_VERIFIED_ON,
        "by_folder": by_folder,
        "model_usd": round(sum(e["model_usd"] for e in by_folder.values()), 4),
        "bigquery_usd": round(sum(e["bigquery_usd"] for e in by_folder.values()), 4),
        "total_usd": round(sum(e["model_usd"] + e["bigquery_usd"] for e in by_folder.values()), 4),
    }


def write_ledger() -> dict[str, Any]:
    """Write the series ledger: what Parts 2 to 7 have spent against the approved cap."""
    ledger: dict[str, Any] = {}
    if LEDGER_PATH.exists():
        ledger = json.loads(LEDGER_PATH.read_text())
    parts = dict(ledger.get("parts", {}))
    part2 = spend()
    parts["2"] = {
        "line_usd": PART2_LINE_USD,
        "spent_usd": part2["total_usd"],
        "model_usd": part2["model_usd"],
        "bigquery_usd": part2["bigquery_usd"],
        "by_folder": part2["by_folder"],
    }
    spent = round(sum(float(p.get("spent_usd") or 0) for p in parts.values()), 4)
    ledger = {
        "note": (
            "Estimated spend on agent runs for Parts 2 to 7, smoke tests and discarded runs"
            " included. Part 1 was spent before this budget was approved and is listed apart;"
            " it does not count toward the cap."
        ),
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "part1_spent_usd_not_counted_toward_cap": PART1_SPENT_USD,
        "approved_usd_parts_2_to_7": SERIES_APPROVED_USD,
        "hard_cap_usd_parts_2_to_7": SERIES_CAP_USD,
        "parts": parts,
        "spent_usd_parts_2_to_7": spent,
        "remaining_to_approved_usd": round(SERIES_APPROVED_USD - spent, 4),
        "remaining_to_hard_cap_usd": round(SERIES_CAP_USD - spent, 4),
    }
    LEDGER_PATH.write_text(json.dumps(ledger, indent=1) + "\n")
    return ledger


def to_row(
    name: str,
    question: questions.Question,
    trial: int,
    run: adk_layer_agent.LayerAgentRun,
    gold: dict[str, Any],
) -> dict[str, Any]:
    """Score one run and flatten it into the row saved under ``results/``."""
    failed = bool(run.error) or run.timed_out
    verdict = scoring.score(question, gold["gold"], gold["decoys"], run.final_text, failed=failed)
    cost = BASE.cost(
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cache_read=run.cache_read_tokens,
        cache_write=run.cache_write_tokens,
    )
    let_through = [call for call in run.tool_calls if not call.get("refused")]
    billed = run.bytes_billed + run.layer_bytes_billed
    row = {
        "config": name,
        "layers": list(LAYER_CONFIGS[name]),
        "model": BASE.model,
        "question_id": question.id,
        "group": question.group,
        "trial": trial,
        **verdict.as_dict(),
        "gold": gold["gold"],
        "answer_text": run.final_text,
        "queries": run.queries,
        "query_count": len(run.queries),
        "queries_refused_over_limit": run.queries_refused_over_limit,
        "tool_calls": run.tool_calls,
        "tool_call_counts": dict(Counter(call["tool"] for call in let_through)),
        "tools_in_order": [call["tool"] for call in let_through],
        "layer_calls_refused": run.layer_calls_refused,
        "model_calls": run.model_calls,
        "hit_model_call_ceiling": "LlmCallsLimit" in run.error,
        "prompt_tokens_by_call": run.prompt_tokens_by_call,
        "input_tokens": run.input_tokens,
        "cache_read_tokens": run.cache_read_tokens,
        "cache_write_tokens": run.cache_write_tokens,
        "input_tokens_total": run.input_tokens + run.cache_read_tokens + run.cache_write_tokens,
        "output_tokens": run.output_tokens,
        "cost_usd": round(cost, 6),
        "bigquery_bytes_billed": billed,
        "bigquery_usd": round(billed / 2**40 * config.BQ_USD_PER_TIB, 6),
        "seconds": round(run.seconds, 1),
        "timed_out": run.timed_out,
        "error": run.error,
        "model_reported": run.model_reported,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    # MetricFlow's SQL names the project; results files never do.
    return dict(config.redact_project(row))


def redact_saved_runs(out: Path) -> int:
    """Rewrite every saved ``runs/<config>.jsonl`` under ``out`` with the project ID replaced.

    Every line is kept, first attempts included, in the same order; only strings
    holding the project ID change. No model or cloud call is made. Returns the
    number of lines that changed.
    """
    changed = 0
    for path in sorted((out / "runs").glob("*.jsonl")):
        lines = []
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                clean = config.redact_project(row)
                changed += clean != row
                line = json.dumps(clean)
            lines.append(line)
        path.write_text("\n".join(lines) + "\n")
    return changed


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
) -> None:
    """Run one configuration, appending each finished run to its JSONL file."""
    layers = LAYER_CONFIGS[name]
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
    await asyncio.to_thread(adk_layer_agent.warm_up, layers)

    gate = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    state = {"spent": float(spend()["total_usd"]), "stopped": False, "finished": 0}

    async def one(question: questions.Question, trial: int) -> None:
        async with gate:
            if state["spent"] >= budget_usd:
                state["stopped"] = True
                return
            run = await adk_layer_agent.ask(BASE.model, question.question, layers)
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


def mean(rows: list[dict[str, Any]], key: str, digits: int = 4) -> float:
    """Average one numeric field over the rows."""
    return round(sum(float(r.get(key) or 0) for r in rows) / len(rows), digits) if rows else 0.0


def effort(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Tokens, calls, time and cost per question, for one set of runs."""
    total_in = sum(int(r.get("input_tokens_total") or 0) for r in rows)
    cached = sum(int(r.get("cache_read_tokens") or 0) for r in rows)
    return {
        "mean_input_tokens": round(mean(rows, "input_tokens_total", 0)),
        "mean_output_tokens": round(mean(rows, "output_tokens", 0)),
        "cache_read_share_of_input": round(cached / total_in, 4) if total_in else None,
        "runs_with_a_cache_read": sum(1 for r in rows if (r.get("cache_read_tokens") or 0) > 0),
        "mean_model_calls": mean(rows, "model_calls", 2),
        "mean_sql_queries": mean(rows, "query_count", 2),
        "mean_seconds": mean(rows, "seconds", 1),
        "mean_cost_usd": mean(rows, "cost_usd"),
        "total_cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in rows), 4),
    }


def tool_use(
    rows: list[dict[str, Any]], layers: tuple[str, ...], by_id: dict[str, questions.Question]
) -> dict[str, Any]:
    """Count which tools the agent called, and when it went around a layer.

    ``went_around_the_semantic_layer`` is the bypass count: runs on a question
    that one metric query answers, in which the agent ran SQL anyway.
    """
    layer_tools = [layer_prompt.TOOL_OF_LAYER[layer] for layer in layers]

    def calls(row: dict[str, Any], tool: str) -> int:
        return int(row["tool_call_counts"].get(tool, 0))

    def used_any_layer(row: dict[str, Any]) -> bool:
        return any(calls(row, tool) for tool in layer_tools)

    result: dict[str, Any] = {
        "runs": len(rows),
        "mean_calls_per_run": {
            tool: round(sum(calls(r, tool) for r in rows) / len(rows), 2)
            for tool in (prompt.TOOL_NAME, *layer_tools)
        },
        "total_calls": {
            tool: sum(calls(r, tool) for r in rows) for tool in (prompt.TOOL_NAME, *layer_tools)
        },
        "runs_that_called": {
            tool: sum(1 for r in rows if calls(r, tool))
            for tool in (prompt.TOOL_NAME, *layer_tools)
        },
        "runs_with_no_layer_call": sum(1 for r in rows if not used_any_layer(r)),
        "runs_with_no_sql_call": sum(1 for r in rows if not calls(r, prompt.TOOL_NAME)),
        "runs_whose_first_call_was_sql": sum(
            1 for r in rows if r["tools_in_order"][:1] == [prompt.TOOL_NAME]
        ),
        "where_a_layer_applies": {},
    }
    for layer in layers:
        tool = layer_prompt.TOOL_OF_LAYER[layer]
        relevant = [r for r in rows if applies_to(layer, by_id[r["question_id"]])]
        result["where_a_layer_applies"][layer] = {
            "questions": len({r["question_id"] for r in relevant}),
            "runs": len(relevant),
            "runs_that_used_the_layer": sum(1 for r in relevant if calls(r, tool)),
            "runs_that_ignored_the_layer": sum(1 for r in relevant if not calls(r, tool)),
        }
    if "semantic" in layers:
        tool = layer_prompt.SEMANTIC_TOOL
        relevant = [r for r in rows if applies_to("semantic", by_id[r["question_id"]])]
        around = [r for r in relevant if calls(r, prompt.TOOL_NAME)]
        result["went_around_the_semantic_layer"] = {
            "what": "Runs on a question that one metric query answers, in which the agent"
            " ran at least one SQL query.",
            "runs_on_such_questions": len(relevant),
            "runs_that_ran_sql": len(around),
            "of_which_never_called_the_metric_tool": sum(1 for r in around if not calls(r, tool)),
            "of_which_called_both": sum(1 for r in around if calls(r, tool)),
            "outcomes_when_sql_was_run": scoring.shares([r["outcome"] for r in around]),
            "runs_answered_from_metrics_alone": len(relevant) - len(around),
            "outcomes_from_metrics_alone": scoring.shares(
                [r["outcome"] for r in relevant if not calls(r, prompt.TOOL_NAME)]
            ),
        }
    return result


def limits(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count how often a run ran into one of the harness's limits."""
    return {
        "runs_refused_a_further_sql_query": sum(
            1 for r in rows if (r.get("queries_refused_over_limit") or 0) > 0
        ),
        "runs_refused_a_further_layer_call": sum(
            1 for r in rows if sum((r.get("layer_calls_refused") or {}).values()) > 0
        ),
        "runs_that_hit_the_model_call_ceiling": sum(
            1 for r in rows if r.get("hit_model_call_ceiling")
        ),
        "runs_that_timed_out": sum(1 for r in rows if r.get("timed_out")),
        "runs_that_ended_in_an_error": sum(1 for r in rows if r.get("error")),
    }


def write_config_file(
    name: str, asked: list[questions.Question], gold: dict[str, Any], *, runs: int, out: Path
) -> dict[str, Any] | None:
    """Write ``<config>.json`` from the saved runs and return its summary block."""
    rows = run_part1.read_runs(out / "runs" / f"{name}.jsonl")
    if not rows:
        return None
    by_id = {q.id: q for q in asked}
    rows = [
        config.redact_project(r) for r in rows if r["question_id"] in by_id and r["trial"] < runs
    ]
    for row in rows:
        run_part1.rescore(row, by_id, gold)
    layers = LAYER_CONFIGS[name]
    expected = len(asked) * runs
    block = {
        "config": name,
        "layers": list(layers),
        "tools": [prompt.TOOL_NAME, *(layer_prompt.TOOL_OF_LAYER[layer] for layer in layers)],
        "runtime": BASE.runtime,
        "runtime_package": f"google-adk=={importlib.metadata.version('google-adk')}",
        "layer_packages": layer_packages(),
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
        "question_count": len(asked),
        "runs_per_question": runs,
        "runs_expected": expected,
        "runs_saved": len(rows),
        "complete": len(rows) == expected,
        "runs_repeated_after_a_failure": sum(1 for r in rows if r.get("retry_of_failed")),
        "sql_query_limit": prompt.MAX_QUERIES,
        "layer_call_limit_per_tool": MAX_LAYER_CALLS,
        "model_call_ceiling": adk_layer_agent.max_model_calls(layers),
        "data_seed": generate.SEED,
        "summary": scoring.summarize(rows),
        "effort": effort(rows),
        "tool_use": tool_use(rows, layers, by_id),
        "tool_use_by_group": {
            group: tool_use([r for r in rows if r["group"] == group], layers, by_id)
            for group in questions.GROUPS
            if any(r["group"] == group for r in rows)
        },
        "limits": limits(rows),
    }
    (out / f"{name}.json").write_text(json.dumps({**block, "runs": rows}, indent=1) + "\n")
    return block


def layer_packages() -> dict[str, str]:
    """Return the pinned versions of what the layers are built with."""
    versions = {
        name: importlib.metadata.version(name) for name in ("rdflib", "pyshacl", "pyoxigraph")
    }
    pinned = (ROOT / "requirements-semantic.txt").read_text()
    for line in pinned.splitlines():
        if "==" in line and not line.startswith("#"):
            package, _, version = line.partition("==")
            versions[package.split("[")[0].strip()] = version.strip()
    return versions


def baseline(asked: list[questions.Question]) -> dict[str, Any]:
    """Read the Part 1 Flash results: the comparison point, which is not run again."""
    saved = json.loads(BASELINE_PATH.read_text())
    ids = {q.id for q in asked}
    rows = [r for r in saved["runs"] if r["question_id"] in ids]
    return {
        "config": "baseline",
        "source": str(BASELINE_PATH.relative_to(ROOT)),
        "what": "Part 1, adk_gemini_flash: schema and the SQL tool only. Not run again.",
        "layers": [],
        "tools": [prompt.TOOL_NAME],
        "model": saved["model"],
        "question_count": len(ids),
        "runs_per_question": saved["runs_per_question"],
        "runs_saved": len(rows),
        "runs_expected": len(rows),
        "complete": saved["complete"],
        "last_run_finished_at": saved["last_run_finished_at"],
        "summary": scoring.summarize(rows),
        "effort": effort(rows),
        "limits": {
            "runs_refused_a_further_sql_query": sum(
                1 for r in rows if (r.get("queries_refused_over_limit") or 0) > 0
            ),
            "runs_that_timed_out": sum(1 for r in rows if r.get("timed_out")),
            "runs_that_ended_in_an_error": sum(1 for r in rows if r.get("error")),
        },
    }


def changes(block: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Return a configuration's change against the baseline, in percentage points."""

    def points(now: dict[str, Any], before: dict[str, Any]) -> dict[str, float]:
        return {
            name: round(100 * (now[f"{name}_share"] - before[f"{name}_share"]), 1)
            for name in (scoring.RIGHT, scoring.WRONG, scoring.DECLINED)
        }

    result = {"overall": points(block["summary"]["overall"], base["summary"]["overall"])}
    for group in questions.GROUPS:
        if group in block["summary"]["by_group"] and group in base["summary"]["by_group"]:
            result[group] = points(
                block["summary"]["by_group"][group], base["summary"]["by_group"][group]
            )
    return result


def pct(share: float | None) -> str:
    """Format a share as a percentage."""
    return run_part1.pct(share)


def signed(points: float) -> str:
    """Format a change in percentage points with its sign."""
    return f"{points:+.1f}"


def write_summary(blocks: list[dict[str, Any]], base: dict[str, Any], out: Path) -> None:
    """Write ``summary.json`` and ``summary.md``: every configuration beside the baseline."""
    for block in blocks:
        block["change_vs_baseline_points"] = changes(block, base)
    payload = {
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "bins": list(scoring.BINS),
        "note": (
            "The baseline is Part 1's Flash configuration at ten runs per question. The"
            " Part 2 configurations ran each question three times, so their shares are"
            " rougher: one run is 1.4 points of an overall share and 5.6 points within a"
            " question group of six."
        ),
        "baseline": base,
        "configurations": blocks,
        "not_run": [name for name in LAYER_CONFIGS if name not in {b["config"] for b in blocks}],
    }
    (out / "summary.json").write_text(json.dumps(payload, indent=1) + "\n")

    everything = [base, *blocks]
    lines = [
        "# Part 2 results",
        "",
        "Written by `run_part2.py`. Tessaway Freight is a fictional company and the data is"
        " synthetic.",
        "",
        "Each configuration is the Part 1 agent (Google ADK, `" + BASE.model + "`) with the same"
        " SQL tool and one extra tool per context layer. Each reply is scored by the Part 1"
        " scorer into one of four bins. Shares are of all runs.",
        "",
        "The baseline row is Part 1's Flash result at ten runs per question and was not run"
        " again. The Part 2 rows ran each question three times, so their shares are rougher:"
        " one run is 1.4 points of an overall share and 5.6 points within a question group."
        " Small differences are not findings.",
        "",
        "| Configuration | Tools beside `run_sql` | Runs | Complete | Right | Confidently wrong"
        " | Declined | No answer | Est. cost | Cost per question |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for block in everything:
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
    for title, key in (
        ("Right", "right"),
        ("Confidently wrong", "confidently_wrong"),
        ("Declined", "declined"),
    ):
        lines += ["", f"## {title}, by question group", ""]
        lines += ["| Configuration | " + " | ".join(questions.GROUPS) + " |"]
        lines += ["| --- |" + " --- |" * len(questions.GROUPS)]
        for block in everything:
            groups = block["summary"]["by_group"]
            cells = [
                f"{pct(groups[g][f'{key}_share'])} ({groups[g][key]} of {groups[g]['runs']})"
                if g in groups
                else "n/a"
                for g in questions.GROUPS
            ]
            lines.append(f"| {block['config']} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Change against the baseline, in percentage points",
        "",
        "Right / confidently wrong / declined. A positive first number is more right answers.",
        "",
        "| Configuration | overall | " + " | ".join(questions.GROUPS) + " |",
        "| --- | --- |" + " --- |" * len(questions.GROUPS),
    ]
    for block in blocks:
        change = block["change_vs_baseline_points"]
        cells = [
            " / ".join(signed(change[scope][name]) for name in ("right", "confidently_wrong",
                                                                 "declined"))
            if scope in change
            else "n/a"
            for scope in ("overall", *questions.GROUPS)
        ]  # fmt: skip
        lines.append(f"| {block['config']} | " + " | ".join(cells) + " |")

    lines += ["", "## By question: right / confidently wrong / declined / no answer", ""]
    lines += ["| Question | Group | " + " | ".join(b["config"] for b in everything) + " |"]
    lines += ["| --- | --- |" + " --- |" * len(everything)]
    ids = sorted({qid for b in everything for qid in b["summary"]["by_question"]})
    for qid in ids:
        cells, group = [], ""
        for block in everything:
            entry = block["summary"]["by_question"].get(qid)
            if entry is None:
                cells.append("n/a")
                continue
            group = entry["group"]
            cells.append(
                f"{entry['right']} / {entry['confidently_wrong']} / {entry['declined']}"
                f" / {entry['no_answer']}"
            )
        lines.append(f"| {qid} | {group} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Tool calls",
        "",
        "Mean calls per run, counting calls that were let through. The agent was free to use"
        " a layer tool or ignore it.",
        "",
        "| Configuration | "
        + " | ".join(f"`{tool}`" for tool in ALL_TOOLS)
        + " | Runs with no layer call | Runs with no SQL | First call was SQL |",
        "| --- |" + " --- |" * (len(ALL_TOOLS) + 3),
    ]
    for block in blocks:
        use = block["tool_use"]
        cells = [
            f"{use['mean_calls_per_run'][tool]:.2f} ({use['runs_that_called'][tool]} runs)"
            if tool in use["mean_calls_per_run"]
            else "not given"
            for tool in ALL_TOOLS
        ]
        lines.append(
            f"| {block['config']} | "
            + " | ".join(cells)
            + f" | {use['runs_with_no_layer_call']} of {use['runs']}"
            f" | {use['runs_with_no_sql_call']} of {use['runs']}"
            f" | {use['runs_whose_first_call_was_sql']} of {use['runs']} |"
        )
    lines += [
        "",
        "### Where a layer applied, and whether the agent used it",
        "",
        "A layer applies to a question when it holds something the question needs. The rule"
        " is `applies_to` in `run_part2.py`, fixed before any run: the semantic layer applies"
        " when one metric query answers the question; the ontology when an official"
        " definition decides it; the graph when one of those definitions is about customers"
        " or loads.",
        "",
        "| Configuration | Layer | Questions | Runs | Used the layer | Ignored the layer |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for block in blocks:
        for layer, entry in block["tool_use"]["where_a_layer_applies"].items():
            lines.append(
                f"| {block['config']} | {layer} | {entry['questions']} | {entry['runs']}"
                f" | {entry['runs_that_used_the_layer']} | {entry['runs_that_ignored_the_layer']} |"
            )
    lines += [
        "",
        "### Going around the semantic layer",
        "",
        "The bypass count: runs on a question that one metric query answers, in which the"
        " agent ran SQL anyway.",
        "",
        "| Configuration | Runs on such questions | Ran SQL | Never called the metric tool"
        " | Called both | Right when SQL was run | Answered from metrics alone"
        " | Right from metrics alone |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for block in blocks:
        around = block["tool_use"].get("went_around_the_semantic_layer")
        if around is None:
            continue
        with_sql, alone = around["outcomes_when_sql_was_run"], around["outcomes_from_metrics_alone"]
        lines.append(
            f"| {block['config']} | {around['runs_on_such_questions']}"
            f" | {around['runs_that_ran_sql']}"
            f" | {around['of_which_never_called_the_metric_tool']}"
            f" | {around['of_which_called_both']}"
            f" | {with_sql['right']} of {with_sql['runs']}"
            f" | {around['runs_answered_from_metrics_alone']}"
            f" | {alone['right']} of {alone['runs']} |"
        )

    lines += [
        "",
        "## Tokens, time and cost per question",
        "",
        "| Configuration | Input tokens | Output tokens | Cache-read share of input"
        " | Model calls | SQL queries | Seconds | Cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for block in everything:
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
        f"Each question allows {prompt.MAX_QUERIES} SQL queries and {MAX_LAYER_CALLS} calls to"
        " each layer tool, and the agent is told both. A run is also stopped at a ceiling of"
        f" model calls it is not told about: {prompt.MAX_MODEL_CALLS} in Part 1, and"
        f" {prompt.MAX_MODEL_CALLS} plus {MAX_LAYER_CALLS} for each layer tool here, so an agent"
        " inside the limits it was told about always has calls left to answer.",
        "",
        "| Configuration | Model-call ceiling | Asked for a further SQL query"
        " | Asked for a further layer call | Hit the model-call ceiling | Timed out"
        " | Declines that mention the query limit |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for block in everything:
        lim, summary = block["limits"], block["summary"]
        lines.append(
            f"| {block['config']} | {block.get('model_call_ceiling', prompt.MAX_MODEL_CALLS)}"
            f" | {lim['runs_refused_a_further_sql_query']} of {block['runs_saved']}"
            f" | {lim.get('runs_refused_a_further_layer_call', 'n/a')}"
            f" | {lim.get('runs_that_hit_the_model_call_ceiling', 'n/a')}"
            f" | {lim['runs_that_timed_out']}"
            f" | {summary['declines_that_mention_the_query_limit']} of {summary['declines']} |"
        )

    lines += ["", "## Wrong answers that said they were assuming something", ""]
    for block in everything:
        summary = block["summary"]
        lines.append(
            f"- {block['config']}: {summary['wrong_answers_that_flagged_an_assumption']} of"
            f" {summary['wrong_answers']} confidently wrong answers used a word such as"
            ' "assume", "interpret" or "definition" somewhere in the reply.'
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
    all_questions = questions.load()
    wanted = set(args.questions.split(",")) if args.questions else None
    asked = [q for q in all_questions if wanted is None or q.id in wanted]
    names = args.configs or list(LAYER_CONFIGS)
    unknown = [n for n in names if n not in LAYER_CONFIGS]
    if unknown:
        raise SystemExit(f"Unknown configuration(s): {', '.join(unknown)}")
    # The correct answers are Part 1's, as saved. tests/test_cloud.py holds that
    # the gold SQL still returns them.
    gold = questions.load_gold()

    if args.redact_saved:
        print(f"replaced the project ID in {redact_saved_runs(out)} saved run(s) under {out}")
    if not args.summarize_only:
        for name in names:
            await run_config(
                name, asked, gold, runs=args.runs, concurrency=args.concurrency,
                budget_usd=args.budget_usd, out=out, retry_failed=args.retry_failed,
            )  # fmt: skip

    blocks = []
    for name in LAYER_CONFIGS:
        block = write_config_file(name, asked, gold, runs=args.runs, out=out)
        if block is not None:
            blocks.append(block)
    write_summary(blocks, baseline(asked), out)
    (RESULTS / "spend.json").write_text(json.dumps(spend(), indent=1) + "\n")
    ledger = write_ledger()
    print(f"estimated Part 2 spend so far: ${spend()['total_usd']:.2f}")
    print(f"Parts 2 to 7 so far: ${ledger['spent_usd_parts_2_to_7']:.2f} of"
          f" ${SERIES_APPROVED_USD:.0f} approved (hard cap ${SERIES_CAP_USD:.0f})")  # fmt: skip
    print(f"results in {out}")


def parse_args() -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description="Run the Part 2 experiment.")
    parser.add_argument("configs", nargs="*", help=f"Any of: {', '.join(LAYER_CONFIGS)}")
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
