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

"""Runs the Part 1 experiment and writes every number the articles use.

Each configuration (a runtime and a pinned model) is asked each question in
``questions/part1.yaml`` a number of times. Every reply is scored in code and
saved with the SQL the agent wrote, its token counts and its estimated cost.

Usage:
    python run_part1.py [CONFIG ...] [options]

    python run_part1.py                                   # every configuration, 10 runs each
    python run_part1.py adk_gemini_flash --runs 2 --questions L1,M1 --out smoke
    python run_part1.py --summarize-only                  # rebuild the summary from saved runs

Options:
    --runs N           Runs per question (default 10).
    --questions IDS    Comma-separated question ids (default: all).
    --concurrency N    Questions in flight at once (default 6).
    --budget-usd X     Stop starting new runs once estimated spend, across every
                       saved run in results/part1, reaches X (default 45).
    --out NAME         Write under results/part1/NAME instead of results/part1.
                       Used for smoke tests so they never mix with the full run.
    --retry-failed     Run again any saved run that ended with no answer because
                       of an error or a timeout. Done at most once.
    --summarize-only   Score the saved replies again and rewrite the summaries.

Files written (under results/part1):
    gold_answers.json        the correct answer to every question, from the gold SQL
    runs/<config>.jsonl      one line per run, appended as it finishes (resumable)
    <config>.json            every run for a configuration, with its metadata
    summary.json, summary.md the shares by configuration and question group
    spend.json               estimated spend across everything run so far
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

from tessaway import config, questions, scoring
from tessaway.agents import adk_agent, claude_agent, prompt
from tessaway.warehouse import generate

RESULTS = Path(__file__).parent / "results" / "part1"
DEFAULT_RUNS = 10
DEFAULT_BUDGET_USD = 45.0

ASK: dict[str, Callable[[str, str], Awaitable[prompt.AgentRun]]] = {
    "adk": adk_agent.ask,
    "claude_sdk": claude_agent.ask,
}
PACKAGE = {"adk": "google-adk", "claude_sdk": "claude-agent-sdk"}


def read_runs(path: Path) -> list[dict[str, Any]]:
    """Read saved runs. A later line for the same question and trial replaces an earlier one."""
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                latest[(row["question_id"], row["trial"])] = row
    return [latest[key] for key in sorted(latest)]


def spend(root: Path = RESULTS) -> dict[str, Any]:
    """Add up estimated spend across every saved run, smoke tests included."""
    by_config: dict[str, dict[str, float]] = {}
    for path in sorted(root.rglob("runs/*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            entry = by_config.setdefault(
                row["config"], {"runs": 0, "model_usd": 0.0, "bigquery_usd": 0.0}
            )
            entry["runs"] += 1
            entry["model_usd"] += float(row.get("cost_usd") or 0)
            entry["bigquery_usd"] += float(row.get("bigquery_usd") or 0)
    for entry in by_config.values():
        entry["model_usd"] = round(entry["model_usd"], 4)
        entry["bigquery_usd"] = round(entry["bigquery_usd"], 4)
    total = sum(e["model_usd"] + e["bigquery_usd"] for e in by_config.values())
    return {
        "note": (
            "Estimated from token counts and list prices in tessaway/config.py, and from"
            " BigQuery bytes billed at the on-demand rate. Every line ever appended is"
            " counted, including smoke tests and runs that were later repeated. The"
            " invoice is the authority."
        ),
        "prices_checked_on": config.MODELS_VERIFIED_ON,
        "by_config": by_config,
        "total_usd": round(total, 4),
    }


def to_row(
    cfg: config.ModelConfig,
    question: questions.Question,
    trial: int,
    run: prompt.AgentRun,
    gold: dict[str, Any],
) -> dict[str, Any]:
    """Score one run and flatten it into the row saved under ``results/``."""
    failed = bool(run.error) or run.timed_out
    verdict = scoring.score(question, gold["gold"], gold["decoys"], run.final_text, failed=failed)
    cost = cfg.cost(
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cache_read=run.cache_read_tokens,
        cache_write=run.cache_write_tokens,
    )
    return {
        "config": cfg.key,
        "model": cfg.model,
        "question_id": question.id,
        "group": question.group,
        "trial": trial,
        **verdict.as_dict(),
        "gold": gold["gold"],
        "answer_text": run.final_text,
        "queries": run.queries,
        "query_count": len(run.queries),
        "queries_refused_over_limit": run.queries_refused_over_limit,
        "model_calls": run.model_calls,
        "input_tokens": run.input_tokens,
        "cache_read_tokens": run.cache_read_tokens,
        "cache_write_tokens": run.cache_write_tokens,
        "input_tokens_total": run.input_tokens + run.cache_read_tokens + run.cache_write_tokens,
        "output_tokens": run.output_tokens,
        "cost_usd": round(cost, 6),
        "bigquery_bytes_billed": run.bytes_billed,
        "bigquery_usd": round(run.bytes_billed / 2**40 * config.BQ_USD_PER_TIB, 6),
        "seconds": round(run.seconds, 1),
        "timed_out": run.timed_out,
        "error": run.error,
        "model_reported": run.model_reported,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def rescore(
    row: dict[str, Any], by_id: dict[str, questions.Question], gold: dict[str, Any]
) -> None:
    """Score a saved reply again with the current scorer, in place."""
    question = by_id[row["question_id"]]
    entry = gold[question.id]
    failed = bool(row.get("error")) or bool(row.get("timed_out"))
    verdict = scoring.score(
        question, entry["gold"], entry["decoys"], row.get("answer_text", ""), failed=failed
    )
    row.update(verdict.as_dict())
    row["gold"] = entry["gold"]


async def run_config(
    cfg: config.ModelConfig,
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
    path = out / "runs" / f"{cfg.key}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = {(r["question_id"], r["trial"]): r for r in read_runs(path)}
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
    print(f"[{cfg.key}] {len(todo)} run(s) to do, {len(done)} already saved", flush=True)

    gate = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    state = {"spent": float(spend()["total_usd"]), "stopped": False, "finished": 0}

    async def one(question: questions.Question, trial: int) -> None:
        async with gate:
            if state["spent"] >= budget_usd:
                state["stopped"] = True
                return
            run = await ASK[cfg.runtime](cfg.model, question.question)
            row = to_row(cfg, question, trial, run, gold[question.id])
            if (question.id, trial) in done:
                row["retry_of_failed"] = True
            async with lock:
                with path.open("a") as handle:
                    handle.write(json.dumps(row) + "\n")
                state["spent"] += row["cost_usd"] + row["bigquery_usd"]
                state["finished"] += 1
                print(
                    f"[{cfg.key}] {question.id} #{trial} {row['outcome']:<17}"
                    f" {row['extracted'][:40]!r} ${row['cost_usd']:.4f}"
                    f" total=${state['spent']:.2f} ({state['finished']}/{len(todo)})",
                    flush=True,
                )

    await asyncio.gather(*(one(question, trial) for question, trial in todo))
    if state["stopped"]:
        print(f"[{cfg.key}] STOPPED at the budget of ${budget_usd:.2f}; the run is partial.")


def write_config_file(
    cfg: config.ModelConfig, asked: list[questions.Question], gold: dict[str, Any],
    *, runs: int, out: Path,
) -> dict[str, Any] | None:  # fmt: skip
    """Write ``<config>.json`` from the saved runs and return its summary block."""
    rows = read_runs(out / "runs" / f"{cfg.key}.jsonl")
    if not rows:
        return None
    by_id = {q.id: q for q in asked}
    rows = [r for r in rows if r["question_id"] in by_id and r["trial"] < runs]
    for row in rows:
        rescore(row, by_id, gold)
    expected = len(asked) * runs
    reported = sorted({r["model_reported"] for r in rows if r.get("model_reported")})
    block = {
        "config": cfg.key,
        "runtime": cfg.runtime,
        "runtime_package": f"{PACKAGE[cfg.runtime]}=="
        f"{importlib.metadata.version(PACKAGE[cfg.runtime])}",
        "vendor": cfg.vendor,
        "model": cfg.model,
        "model_tier": cfg.tier,
        "model_reported_by_provider": reported,
        "model_and_prices_checked_on": config.MODELS_VERIFIED_ON,
        "usd_per_million_tokens": {
            "input": cfg.usd_in,
            "output": cfg.usd_out,
            "cache_read": cfg.usd_cache_read,
            "cache_write": cfg.usd_cache_write,
        },
        "first_run_finished_at": min(r["finished_at"] for r in rows),
        "last_run_finished_at": max(r["finished_at"] for r in rows),
        "question_count": len(asked),
        "runs_per_question": runs,
        "runs_expected": expected,
        "runs_saved": len(rows),
        "complete": len(rows) == expected,
        # Runs that first ended in an error or a timeout with nothing to score and
        # were run once more. Both attempts stay in runs/<config>.jsonl.
        "runs_repeated_after_a_failure": sum(1 for r in rows if r.get("retry_of_failed")),
        "data_seed": generate.SEED,
        "summary": scoring.summarize(rows),
    }
    (out / f"{cfg.key}.json").write_text(json.dumps({**block, "runs": rows}, indent=1) + "\n")
    return block


def pct(share: float | None) -> str:
    """Format a share as a percentage for the Markdown summary."""
    return "n/a" if share is None else f"{100 * share:.1f}%"


def write_summary(blocks: list[dict[str, Any]], waiting: dict[str, str], out: Path) -> None:
    """Write ``summary.json`` and ``summary.md`` across configurations."""
    payload = {
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "bins": list(scoring.BINS),
        "headline": "confidently_wrong_share: share of all runs where the agent gave an answer"
        " and it was wrong",
        "configurations": blocks,
        "not_run": waiting,
    }
    (out / "summary.json").write_text(json.dumps(payload, indent=1) + "\n")

    lines = [
        "# Part 1 results",
        "",
        "Written by `run_part1.py`. Tessaway Freight is a fictional company and the data is"
        " synthetic.",
        "",
        "Each reply is scored in code into one of four bins. Shares are of all runs.",
        "",
        "| Configuration | Model | Questions | Runs | Complete | Right | Confidently wrong"
        " | Declined | No answer | Est. cost | Cost per question |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for block in blocks:
        overall = block["summary"]["overall"]
        lines.append(
            f"| {block['config']} | `{block['model']}` | {block['question_count']}"
            f" | {block['runs_saved']} of {block['runs_expected']}"
            f" | {'yes' if block['complete'] else 'NO, partial'}"
            f" | {pct(overall['right_share'])} | {pct(overall['confidently_wrong_share'])}"
            f" | {pct(overall['declined_share'])} | {pct(overall['no_answer_share'])}"
            f" | ${block['summary']['total_cost_usd']:.2f}"
            f" | ${block['summary']['mean_cost_usd_per_question']:.4f} |"
        )
    lines += ["", "## Confidently wrong, by question group", ""]
    lines += ["| Configuration | " + " | ".join(questions.GROUPS) + " |"]
    lines += ["| --- |" + " --- |" * len(questions.GROUPS)]
    for block in blocks:
        groups = block["summary"]["by_group"]
        cells = [
            pct(groups[g]["confidently_wrong_share"]) if g in groups else "n/a"
            for g in questions.GROUPS
        ]
        lines.append(f"| {block['config']} | " + " | ".join(cells) + " |")
    lines += ["", "## Right, by question group", ""]
    lines += ["| Configuration | " + " | ".join(questions.GROUPS) + " |"]
    lines += ["| --- |" + " --- |" * len(questions.GROUPS)]
    for block in blocks:
        groups = block["summary"]["by_group"]
        cells = [pct(groups[g]["right_share"]) if g in groups else "n/a" for g in questions.GROUPS]
        lines.append(f"| {block['config']} | " + " | ".join(cells) + " |")
    lines += ["", "## By question: right / confidently wrong / declined / no answer", ""]
    lines += ["| Question | Group | " + " | ".join(b["config"] for b in blocks) + " |"]
    lines += ["| --- | --- |" + " --- |" * len(blocks)]
    ids = sorted({qid for b in blocks for qid in b["summary"]["by_question"]})
    for qid in ids:
        cells, group = [], ""
        for block in blocks:
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
    lines += ["", "## Wrong answers that said they were assuming something", ""]
    for block in blocks:
        summary = block["summary"]
        lines.append(
            f"- {block['config']}: {summary['wrong_answers_that_flagged_an_assumption']} of"
            f" {summary['wrong_answers']} confidently wrong answers used a word such as"
            ' "assume", "interpret" or "definition" somewhere in the reply.'
        )
    lines += ["", "## The query limit", ""]
    lines.append(
        "Each question allows a fixed number of queries, and the agent is told the number."
        " These counts show how often that limit was reached."
    )
    lines.append("")
    for block in blocks:
        summary = block["summary"]
        lines.append(
            f"- {block['config']}: {summary['runs_that_used_every_query']} of"
            f" {block['runs_saved']} runs asked for another query after using them all."
            f" {summary['declines_that_mention_the_query_limit']} of {summary['declines']}"
            " declines mention running out of queries."
        )
    if waiting:
        lines += ["", "## Not run", ""]
        lines += [f"- {key}: {reason}" for key, reason in waiting.items()]
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
    names = args.configs or list(config.CONFIGS)
    unknown = [n for n in names if n not in config.CONFIGS]
    if unknown:
        raise SystemExit(f"Unknown configuration(s): {', '.join(unknown)}")

    if args.summarize_only:
        gold = questions.load_gold()
    else:
        # The correct answers are computed fresh from the gold SQL on every run.
        gold = questions.compute_gold(all_questions)
        questions.GOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
        questions.GOLD_PATH.write_text(
            json.dumps(
                {"seed": generate.SEED, "question_count": len(all_questions), "answers": gold},
                indent=1,
            )
            + "\n"
        )

    waiting: dict[str, str] = {}
    previous = out / "summary.json"
    if args.summarize_only and previous.exists():
        # Keep the reasons recorded when the configurations were last tried.
        waiting = dict(json.loads(previous.read_text()).get("not_run", {}))
    for name in names:
        cfg = config.CONFIGS[name]
        if args.summarize_only:
            continue
        if cfg.runtime == "claude_sdk":
            ok, reason = await claude_agent.available(cfg.model)
            if not ok:
                waiting[name] = f"{cfg.model} could not be reached on Vertex AI: {reason}"
                print(f"[{name}] skipped: {waiting[name]}", flush=True)
                continue
        await run_config(
            cfg, asked, gold, runs=args.runs, concurrency=args.concurrency,
            budget_usd=args.budget_usd, out=out, retry_failed=args.retry_failed,
        )  # fmt: skip

    blocks = []
    for name in config.CONFIGS:
        block = write_config_file(config.CONFIGS[name], asked, gold, runs=args.runs, out=out)
        if block is not None:
            blocks.append(block)
        elif name not in waiting:
            waiting[name] = "no runs saved"
    write_summary(blocks, waiting, out)
    (RESULTS / "spend.json").write_text(json.dumps(spend(), indent=1) + "\n")
    print(f"estimated spend so far: ${spend()['total_usd']:.2f}")
    print(f"results in {out}")


def parse_args() -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description="Run the Part 1 experiment.")
    parser.add_argument("configs", nargs="*", help=f"Any of: {', '.join(config.CONFIGS)}")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--questions", default="")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--out", default="")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
