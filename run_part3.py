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

"""Runs the Part 3 experiment and writes every number the articles use.

Part 3 serves the Part 2 layers as one contract from a context server on Cloud
Run (``context_server/``) and asks where each answer came from. The agent is
the Part 2 agent with its layer tools replaced by ADK's MCP toolset pointed at
the server, under its own service account. Two configurations:

    available         the contract and the SQL tool; the 24 Part 1 questions
    routed            the contract only; the 24 Part 1 questions
    routed_holdout    the contract only; the 12 held-out questions

The questions, the correct answers and the scorer are Part 1's (and the
held-out set's), unchanged. Predictions: ``results/part3/predictions.md``,
committed before the first scored run.

Usage:
    python run_part3.py [CONFIG ...] [options]

    python run_part3.py                                  # all three, 3 runs each
    python run_part3.py available routed --runs 1 --questions L1,M1 --out smoke
    python run_part3.py --check-auth                     # an unauthenticated call is refused
    python run_part3.py --read-server-log                # read the call log back and compare
    python run_part3.py --claude-demo                    # the unscored Claude pass
    python run_part3.py --summarize-only

Options:
    --runs N           Runs per question (default 3).
    --questions IDS    Comma-separated question ids (default: all of the configuration's set).
    --concurrency N    Questions in flight at once (default 6).
    --budget-usd X     Stop starting runs once estimated Part 3 Gemini spend reaches X (default 15).
    --out NAME         Write under results/part3/NAME (smoke tests).
    --retry-failed     Run again, once, a saved run that ended in an error or a timeout.

Files written (under results/part3, or results/part3/NAME):
    runs/<config>.jsonl      one line per run, appended as it finishes (resumable)
    server_log.jsonl         the server's call log, read back from Cloud Logging
    summary.json, summary.md, server_log_check.md
    claude_demo.md, runs/claude_demo.jsonl
and the Part 3 lines of ``results/series_spend.json``.

Nothing written names the Google Cloud project or the service URL:
``tessaway.contract_client.scrub`` replaces both before any line is saved.
"""

# The report-writing code below builds long Markdown lines; they are kept whole to read as tables.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_part1
import run_part2
from tessaway import answer_source, config, contract_client, questions, scoring
from tessaway.agents import adk_contract_agent, contract_prompt, prompt
from tessaway.layers import MAX_LAYER_CALLS

ROOT = Path(__file__).parent
RESULTS = ROOT / "results" / "part3"
HOLDOUT_QUESTIONS = ROOT / "questions" / "holdout.yaml"
HOLDOUT_GOLD = ROOT / "results" / "holdout" / "gold_answers.json"
LEDGER_PATH = run_part2.LEDGER_PATH

BASE = run_part2.BASE
CLAUDE = config.CONFIGS["claude_sonnet"]
DEFAULT_RUNS = 3
DEFAULT_BUDGET_USD = 15.0
CLAUDE_CAP_USD = 5.0
PART3_LINE_USD = 4.80
PLANNED_LOW_USD, PLANNED_HIGH_USD = 5.50, 7.50
CONTRACT_VERSION = "1.0.0"
SERVICE_NAME = "tessaway-context"

AVAILABLE, ROUTED, ROUTED_HOLDOUT = "available", "routed", "routed_holdout"
# Configuration -> (what the agent is given, which question set).
CONFIGS: dict[str, tuple[str, str]] = {
    AVAILABLE: (contract_prompt.AVAILABLE, "part1"),
    ROUTED: (contract_prompt.ROUTED, "part1"),
    ROUTED_HOLDOUT: (contract_prompt.ROUTED, "holdout"),
}
OPERATIONS = contract_prompt.OPERATIONS
SQL = prompt.TOOL_NAME
LOOKUPS = ("L1", "L2", "L3", "L4", "L5", "L6")
NOT_ANSWERABLE = "H11"


def question_set(name: str) -> tuple[list[questions.Question], dict[str, Any]]:
    """Return a question set and its correct answers."""
    if name == "holdout":
        return questions.load(HOLDOUT_QUESTIONS), questions.load_gold(HOLDOUT_GOLD)
    return questions.load(), questions.load_gold()


def scrubbed(row: dict[str, Any]) -> dict[str, Any]:
    """Return the row with the project id and the service URL taken out."""
    return dict(json.loads(contract_client.scrub(json.dumps(row))))


def to_row(
    name: str,
    question: questions.Question,
    trial: int,
    run: adk_contract_agent.ContractAgentRun,
    gold: dict[str, Any],
    caller: str,
) -> dict[str, Any]:
    """Score one run, say where its answer came from, and flatten it into the saved row."""
    failed = bool(run.error) or run.timed_out
    verdict = scoring.score(question, gold["gold"], gold["decoys"], run.final_text, failed=failed)
    cost = BASE.cost(
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cache_read=run.cache_read_tokens,
        cache_write=run.cache_write_tokens,
    )
    let_through = [call for call in run.tool_calls if not call.get("refused")]
    source = answer_source.classify(verdict.extracted, question.answer_type, run.tool_calls)
    contract_calls = [c for c in let_through if c["tool"] in OPERATIONS]
    row = {
        "config": name,
        "configuration": run.configuration,
        "model": BASE.model,
        "question_id": question.id,
        "group": question.group,
        "answer_type": question.answer_type,
        "trial": trial,
        "run_id": run.run_id,
        "caller": caller,
        **verdict.as_dict(),
        "gold": gold["gold"],
        "answer_text": run.final_text,
        "answer_source": source["source"],
        "answer_matched_calls": source["matched_calls"],
        "tools_offered": run.tools_offered,
        "queries": run.queries,
        "query_count": len(run.queries),
        "queries_refused_over_limit": run.queries_refused_over_limit,
        "tool_calls": run.tool_calls,
        "tool_call_counts": dict(Counter(call["tool"] for call in let_through)),
        "tools_in_order": [call["tool"] for call in let_through],
        "contract_calls": len(contract_calls),
        "contract_versions": sorted({str(c.get("contract_version", "")) for c in contract_calls}),
        "contract_calls_without_version": sum(
            1 for c in contract_calls if not c.get("contract_version") or not c.get("response_id")
        ),
        "contract_calls_refused": run.layer_calls_refused,
        "model_calls": run.model_calls,
        "hit_model_call_ceiling": "LlmCallsLimit" in run.error,
        "prompt_tokens_by_call": run.prompt_tokens_by_call,
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
    return scrubbed(row)


def rows_in(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file of runs; a later line for the same question and trial replaces one."""
    return run_part1.read_runs(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read every line of a JSONL file, none replaced: for spend and the server log."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def spend(root: Path = RESULTS) -> dict[str, Any]:
    """Add up estimated Part 3 spend across every saved run, smoke tests included."""
    by_folder: dict[str, dict[str, Any]] = {}
    claude = {"runs": 0, "usd": 0.0}
    for path in sorted(root.rglob("runs/*.jsonl")):
        folder = str(path.parent.parent.relative_to(root))
        for row in read_jsonl(path):
            if row.get("runtime") == "claude_sdk":
                claude["runs"] += 1
                # The higher of the list-price estimate and what the SDK reported.
                claude["usd"] += max(
                    float(row.get("cost_usd") or 0), float(row.get("sdk_reported_cost_usd") or 0)
                )
                continue
            entry = by_folder.setdefault(
                "full run" if folder == "." else folder,
                {"runs": 0, "model_usd": 0.0, "bigquery_usd": 0.0},
            )
            entry["runs"] += 1
            entry["model_usd"] += float(row.get("cost_usd") or 0)
            entry["bigquery_usd"] += float(row.get("bigquery_usd") or 0)
    for entry in by_folder.values():
        entry["model_usd"] = round(entry["model_usd"], 4)
        entry["bigquery_usd"] = round(entry["bigquery_usd"], 4)
    contract_bq = 0.0
    log_path = root / "server_log.jsonl"
    if log_path.exists():
        billed = sum(int(line.get("bytes_billed") or 0) for line in read_jsonl(log_path))
        contract_bq = billed / 2**40 * config.BQ_USD_PER_TIB
    gemini = sum(e["model_usd"] for e in by_folder.values())
    bigquery = sum(e["bigquery_usd"] for e in by_folder.values()) + contract_bq
    return {
        "note": (
            "Estimated from token counts and list prices in tessaway/config.py, and BigQuery"
            " bytes billed at the on-demand rate (the SQL tool's from each run, the contract's"
            " from the server log). Every run ever saved under results/part3 is counted. The"
            " invoices are the authority."
        ),
        "prices_checked_on": config.MODELS_VERIFIED_ON,
        "gemini_by_folder": by_folder,
        "gemini_model_usd": round(gemini, 4),
        "bigquery_usd": round(bigquery, 4),
        "contract_bigquery_usd": round(contract_bq, 6),
        "gemini_total_usd": round(gemini + bigquery, 4),
        "anthropic": {"runs": claude["runs"], "usd": round(float(claude["usd"]), 4)},
    }


def write_ledger(cloud_run_usd: float | None = None) -> dict[str, Any]:
    """Write the Part 3 lines of the series ledger: Gemini and, apart, Anthropic."""
    ledger = json.loads(LEDGER_PATH.read_text()) if LEDGER_PATH.exists() else {}
    parts = dict(ledger.get("parts", {}))
    totals = spend()
    previous = parts.get("3", {})
    parts["3"] = {
        "what": "Context contract on Cloud Run: available and routed, 24 questions; routed, 12 held-out.",
        "line_usd": PART3_LINE_USD,
        "planned_usd": [PLANNED_LOW_USD, PLANNED_HIGH_USD],
        "spent_usd": totals["gemini_total_usd"],
        "model_usd": totals["gemini_model_usd"],
        "bigquery_usd": totals["bigquery_usd"],
        "by_folder": totals["gemini_by_folder"],
    }
    if cloud_run_usd is not None or "cloud_run_usd_estimate" in previous:
        parts["3"]["cloud_run_usd_estimate"] = (
            cloud_run_usd if cloud_run_usd is not None else previous["cloud_run_usd_estimate"]
        )
    spent = round(sum(float(p.get("spent_usd") or 0) for p in parts.values()), 4)
    ledger.update(
        {
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "parts": parts,
            "spent_usd_parts_2_to_7": spent,
            "remaining_to_approved_usd": round(run_part2.SERIES_APPROVED_USD - spent, 4),
            "remaining_to_hard_cap_usd": round(run_part2.SERIES_CAP_USD - spent, 4),
        }
    )
    anthropic = dict(ledger.get("anthropic_outside_cap", {}))
    anthropic["part3_claude_demo"] = {
        "what": "Unscored Claude Agent SDK pass over the 24 questions, claude-sonnet-5-5 through"
        " Anthropic's API. Billed by Anthropic, outside the Gemini budget and its cap.",
        "cap_usd": CLAUDE_CAP_USD,
        "runs": totals["anthropic"]["runs"],
        "spent_usd": totals["anthropic"]["usd"],
    }
    ledger["anthropic_outside_cap"] = anthropic
    LEDGER_PATH.write_text(json.dumps(ledger, indent=1) + "\n")
    return ledger


async def run_config(
    name: str,
    *,
    runs: int,
    wanted: set[str] | None,
    concurrency: int,
    budget_usd: float,
    out: Path,
    retry_failed: bool,
) -> None:
    """Run one configuration, appending each finished run to its JSONL file."""
    configuration, set_name = CONFIGS[name]
    asked, gold = question_set(set_name)
    asked = [q for q in asked if wanted is None or q.id in wanted]
    path = out / "runs" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = {(r["question_id"], r["trial"]): r for r in rows_in(path)}
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
    where = contract_client.deployment()
    caller = where.callers[configuration]
    gate = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    state = {"spent": float(spend()["gemini_total_usd"]), "stopped": False, "finished": 0}

    async def one(question: questions.Question, trial: int) -> None:
        async with gate:
            if state["spent"] >= budget_usd:
                state["stopped"] = True
                return
            token = await asyncio.to_thread(contract_client.id_token, caller, where.url)
            run = await adk_contract_agent.ask(
                BASE.model, question.question, configuration, where.endpoint, token
            )
            row = to_row(name, question, trial, run, gold[question.id], caller)
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
                    f" {row['extracted'][:28]!r} src={row['answer_source']} [{used}]"
                    f" ${row['cost_usd']:.4f} total=${state['spent']:.2f}"
                    f" ({state['finished']}/{len(todo)}){' ERR ' + row['error'][:80] if row['error'] else ''}",
                    flush=True,
                )

    await asyncio.gather(*(one(question, trial) for question, trial in todo))
    if state["stopped"]:
        print(f"[{name}] STOPPED at the budget of ${budget_usd:.2f}; the run is partial.")


# --- secured: an unauthenticated call is refused -----------------------------------------


def _post(url: str, headers: dict[str, str]) -> int:
    """POST an MCP initialize request and return the HTTP status."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "auth-check", "version": "0"},
            },
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            **headers,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def check_auth() -> dict[str, Any]:
    """Call the deployed service with no token, a forged token, and an agent's token."""
    where = contract_client.deployment()
    token = contract_client.id_token(where.callers[contract_prompt.ROUTED], where.url)
    forged = token.rsplit(".", 1)[0] + ".forged-signature"
    checks = [
        ("no token", {}, "refused"),
        ("a token with a forged signature", {"authorization": f"Bearer {forged}"}, "refused"),
        ("the routed agent's ID token", {"authorization": f"Bearer {token}"}, "accepted"),
    ]
    results = []
    for what, headers, expected in checks:
        status = _post(where.endpoint, headers)
        outcome = "accepted" if status == 200 else "refused"
        results.append(
            {
                "call": what,
                "http_status": status,
                "outcome": outcome,
                "expected": expected,
                "as_expected": outcome == expected,
            }
        )
    report = {
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "endpoint": contract_client.URL_PLACEHOLDER + "/mcp",
        "results": results,
        "all_as_expected": all(r["as_expected"] for r in results),
    }
    (RESULTS / "auth_check.json").write_text(
        contract_client.scrub(json.dumps(report, indent=1)) + "\n"
    )
    return report


# --- observable: the server's log, read back --------------------------------------------


def _token_file() -> str:
    """Write a short-lived access token from the operator's ADC for one gcloud call."""
    import google.auth
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(scopes=contract_client.SCOPES)
    credentials.refresh(Request())
    handle, path = tempfile.mkstemp(prefix="p3tok_")
    with os.fdopen(handle, "w") as out:
        out.write(str(credentials.token))
    os.chmod(path, 0o600)
    return path


def read_server_log(since: str) -> list[dict[str, Any]]:
    """Read every contract_call line the server wrote since ``since`` from Cloud Logging."""
    log_filter = (
        'resource.type="cloud_run_revision"'
        f' AND resource.labels.service_name="{SERVICE_NAME}"'
        ' AND jsonPayload.event="contract_call"'
        f' AND timestamp>="{since}"'
    )
    found = None
    for attempt in range(3):
        token_path = _token_file()
        try:
            found = subprocess.run(
                [
                    "gcloud",
                    "logging",
                    "read",
                    log_filter,
                    "--project",
                    config.project(),
                    "--access-token-file",
                    token_path,
                    "--format=json",
                    "--order=asc",
                    "--limit=100000",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            os.remove(token_path)
        if found.returncode == 0:
            break
        print(f"gcloud logging read failed (attempt {attempt + 1}):"
              f" {contract_client.scrub(found.stderr[-400:])}")  # fmt: skip
        time.sleep(10)
    if found is None or found.returncode != 0:
        raise SystemExit("could not read the server log back")
    lines = []
    for entry in json.loads(found.stdout or "[]"):
        payload = dict(entry.get("jsonPayload") or {})
        payload["log_timestamp"] = entry.get("timestamp", "")
        payload["revision"] = (entry.get("resource", {}).get("labels", {}) or {}).get(
            "revision_name", ""
        )
        lines.append(payload)
    return [dict(json.loads(contract_client.scrub(json.dumps(line)))) for line in lines]


def save_server_log(since: str) -> int:
    """Read the log back and save it beside the runs."""
    lines = read_server_log(since)
    path = RESULTS / "server_log.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return len(lines)


def compare_log(rows: list[dict[str, Any]], log: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the server's record of each run's contract calls with the agent's own.

    A call agrees when the response ID the agent recorded is in the server log
    with the same operation, contract version and caller. A server line whose
    run ID belongs to a run, but whose response ID that run never recorded, is
    a call the agent's record is missing.
    """
    by_run: dict[str, list[dict[str, Any]]] = {}
    for line in log:
        by_run.setdefault(str(line.get("run_id", "")), []).append(line)
    totals: Counter[str] = Counter()
    problems: list[dict[str, Any]] = []
    runs_agreeing = 0
    for row in rows:
        server = {str(line["response_id"]): line for line in by_run.get(row["run_id"], [])}
        recorded = [
            c for c in row["tool_calls"] if c["tool"] in OPERATIONS and not c.get("refused")
        ]
        cut_off = bool(row.get("error") or row.get("timed_out"))
        ok = True
        seen = set()
        for call in recorded:
            totals["agent_calls"] += 1
            rid = call.get("response_id")
            if not rid and call.get("error"):
                # The MCP layer refused the call (its arguments failed the published
                # schema) before the contract code ran: no envelope, no version, and
                # no server log line. Both records agree it was never answered.
                totals["calls_refused_before_the_contract_ran"] += 1
                problems.append(
                    {
                        "run_id": row["run_id"],
                        "question_id": row["question_id"],
                        "problem": "refused by the MCP layer before the contract ran;"
                        " no response ID, no server log line",
                        "operation": call["tool"],
                        "error": str(call["error"])[:300],
                    }
                )
                continue
            if not rid:
                totals["agent_calls_without_response"] += 1
                ok = False
                problems.append(
                    {
                        "run_id": row["run_id"],
                        "question_id": row["question_id"],
                        "problem": "agent recorded a call with no response",
                        "operation": call["tool"],
                        "cut_off_run": cut_off,
                    }
                )
                continue
            seen.add(rid)
            logged = server.get(rid)
            if logged is None:
                totals["agent_calls_missing_from_server_log"] += 1
                ok = False
                problems.append(
                    {
                        "run_id": row["run_id"],
                        "question_id": row["question_id"],
                        "problem": "not in the server log",
                        "response_id": rid,
                    }
                )
                continue
            same = (
                logged.get("operation") == call["tool"]
                and logged.get("contract_version") == call.get("contract_version")
                and logged.get("caller") == row["caller"]
            )
            if same:
                totals["agreeing_calls"] += 1
            else:
                totals["calls_that_differ"] += 1
                ok = False
                problems.append(
                    {
                        "run_id": row["run_id"],
                        "question_id": row["question_id"],
                        "problem": "differs",
                        "response_id": rid,
                        "agent": [call["tool"], call.get("contract_version"), row["caller"]],
                        "server": [
                            logged.get("operation"),
                            logged.get("contract_version"),
                            logged.get("caller"),
                        ],
                    }
                )
        for rid, line in server.items():
            totals["server_lines"] += 1
            if rid not in seen:
                totals["server_lines_missing_from_agent_record"] += 1
                ok = False
                problems.append(
                    {
                        "run_id": row["run_id"],
                        "question_id": row["question_id"],
                        "problem": "in the server log, not in the agent's record",
                        "response_id": rid,
                        "operation": line.get("operation"),
                        "cut_off_run": cut_off,
                    }
                )
        if ok:
            runs_agreeing += 1
        else:
            totals["runs_cut_off_with_a_problem" if cut_off else "runs_with_a_problem"] += 1
    run_ids = {row["run_id"] for row in rows}
    callers = Counter(str(line.get("caller")) for line in log if line.get("run_id") in run_ids)
    return {
        "runs": len(rows),
        "runs_agreeing": runs_agreeing,
        "agent_calls": totals["agent_calls"],
        "server_lines": totals["server_lines"],
        "agreeing_calls": totals["agreeing_calls"],
        "agent_calls_missing_from_server_log": totals["agent_calls_missing_from_server_log"],
        "agent_calls_without_response": totals["agent_calls_without_response"],
        "calls_refused_before_the_contract_ran": totals["calls_refused_before_the_contract_ran"],
        "server_lines_missing_from_agent_record": totals["server_lines_missing_from_agent_record"],
        "calls_that_differ": totals["calls_that_differ"],
        "runs_with_a_problem": totals["runs_with_a_problem"],
        "runs_cut_off_with_a_problem": totals["runs_cut_off_with_a_problem"],
        "callers_in_log": dict(callers),
        "problems": problems[:200],
    }


# --- summaries ---------------------------------------------------------------------------


def calls(row: dict[str, Any], tool: str) -> int:
    """How many calls to ``tool`` a run made that were let through."""
    return int(row["tool_call_counts"].get(tool, 0))


def sources(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count answer sources, and outcomes within each source."""
    counted = Counter(r["answer_source"] for r in rows)
    result: dict[str, Any] = {"runs": len(rows)}
    for name in (*answer_source.SOURCES, answer_source.NO_VALUE):
        within = [r for r in rows if r["answer_source"] == name]
        result[name] = {
            "runs": counted.get(name, 0),
            **{
                outcome: sum(1 for r in within if r["outcome"] == outcome)
                for outcome in scoring.BINS
            },
        }
    return result


def tool_use(rows: list[dict[str, Any]], set_name: str) -> dict[str, Any]:
    """Which tools the agent called, and when it used SQL beside a metric."""
    tools = [SQL, *OPERATIONS]
    result: dict[str, Any] = {
        "runs": len(rows),
        "mean_calls_per_run": {
            t: round(sum(calls(r, t) for r in rows) / len(rows), 2) for t in tools
        },
        "runs_that_called": {t: sum(1 for r in rows if calls(r, t)) for t in tools},
        "runs_with_no_contract_call": sum(1 for r in rows if not r["contract_calls"]),
        "runs_with_no_sql_call": sum(1 for r in rows if not calls(r, SQL)),
        "runs_whose_first_call_was_sql": sum(1 for r in rows if r["tools_in_order"][:1] == [SQL]),
        "runs_whose_first_call_was_the_contract": sum(
            1 for r in rows if r["tools_in_order"][:1] and r["tools_in_order"][0] in OPERATIONS
        ),
    }
    if set_name == "part1":
        by_id = {q.id: q for q in questions.load()}
        relevant = [r for r in rows if run_part2.applies_to("semantic", by_id[r["question_id"]])]
        result["where_one_metric_answers"] = {
            "what": "Runs on the 18 Part 1 questions one metric query answers (run_part2.applies_to).",
            "runs": len(relevant),
            "called_compute_metric": sum(1 for r in relevant if calls(r, "compute_metric")),
            "ran_sql": sum(1 for r in relevant if calls(r, SQL)),
            "called_both": sum(1 for r in relevant if calls(r, SQL) and calls(r, "compute_metric")),
            "sql_only": sum(
                1 for r in relevant if calls(r, SQL) and not calls(r, "compute_metric")
            ),
            "contract_only": sum(1 for r in relevant if r["contract_calls"] and not calls(r, SQL)),
        }
    return result


def versions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count contract responses and whether each carried the version and a response ID."""
    recorded = [
        c
        for r in rows
        for c in r["tool_calls"]
        if c["tool"] in OPERATIONS and not c.get("refused") and "result" in c
    ]
    stamped = [c for c in recorded if c.get("contract_version") and c.get("response_id")]
    return {
        "contract_responses": len(recorded),
        "with_version_and_response_id": len(stamped),
        "versions_seen": dict(Counter(str(c.get("contract_version")) for c in recorded)),
        "all_stamped": len(stamped) == len(recorded),
    }


def limits(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How often a run met one of the harness's limits, or failed."""
    return {
        "runs_refused_a_further_sql_query": sum(
            1 for r in rows if (r.get("queries_refused_over_limit") or 0) > 0
        ),
        "runs_refused_a_further_contract_call": sum(
            1 for r in rows if sum((r.get("contract_calls_refused") or {}).values()) > 0
        ),
        "runs_that_hit_the_model_call_ceiling": sum(
            1 for r in rows if r.get("hit_model_call_ceiling")
        ),
        "runs_that_timed_out": sum(1 for r in rows if r.get("timed_out")),
        "runs_that_ended_in_an_error": sum(1 for r in rows if r.get("error")),
    }


def block_for(
    name: str, rows: list[dict[str, Any]], runs: int, wanted: set[str] | None
) -> dict[str, Any]:
    """Everything the summary reports about one configuration."""
    configuration, set_name = CONFIGS[name]
    asked, _ = question_set(set_name)
    asked = [q for q in asked if wanted is None or q.id in wanted]
    return {
        "config": name,
        "configuration": configuration,
        "question_set": set_name,
        "tools": [SQL, *OPERATIONS]
        if configuration == contract_prompt.AVAILABLE
        else list(OPERATIONS),
        "runtime_package": f"google-adk=={importlib.metadata.version('google-adk')}",
        "mcp_package": f"mcp=={importlib.metadata.version('mcp')}",
        "model": BASE.model,
        "model_reported_by_provider": sorted(
            {r["model_reported"] for r in rows if r.get("model_reported")}
        ),
        "contract_version": CONTRACT_VERSION,
        "question_count": len(asked),
        "runs_per_question": runs,
        "runs_expected": len(asked) * runs,
        "runs_saved": len(rows),
        "complete": len(rows) == len(asked) * runs,
        "runs_repeated_after_a_failure": sum(1 for r in rows if r.get("retry_of_failed")),
        "first_run_finished_at": min((r["finished_at"] for r in rows), default=""),
        "last_run_finished_at": max((r["finished_at"] for r in rows), default=""),
        "sql_query_limit": prompt.MAX_QUERIES,
        "contract_call_limit_per_operation": MAX_LAYER_CALLS,
        "model_call_ceiling": adk_contract_agent.max_model_calls(),
        "summary": scoring.summarize(rows),
        "effort": run_part2.effort(rows),
        "answer_source": sources(rows),
        "answer_source_by_group": {
            g: sources([r for r in rows if r["group"] == g])
            for g in questions.GROUPS
            if any(r["group"] == g for r in rows)
        },
        "tool_use": tool_use(rows, set_name),
        "versions": versions(rows),
        "limits": limits(rows),
    }


def where_routing_breaks(rows: list[dict[str, Any]], ids: tuple[str, ...]) -> list[dict[str, Any]]:
    """What the routed agent did on each run of the given questions."""
    picked = sorted(
        (r for r in rows if r["question_id"] in ids),
        key=lambda r: (ids.index(r["question_id"]), r["trial"]),
    )
    return [
        {
            "question_id": r["question_id"],
            "trial": r["trial"],
            "outcome": r["outcome"],
            "extracted": r["extracted"],
            "gold": r["gold"],
            "answer_source": r["answer_source"],
            "operations_called": r["tools_in_order"],
            "what_it_did": (
                "declined"
                if r["outcome"] == scoring.DECLINED
                else "no answer"
                if r["outcome"] == scoring.NO_ANSWER
                else f"answered {'right' if r['outcome'] == scoring.RIGHT else 'wrong'}"
                f" from {r['answer_source']}"
            ),
        }
        for r in picked
    ]


def per_question_cost(
    available: list[dict[str, Any]], routed: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Per question: SQL queries, tokens, seconds and dollars, available beside routed."""
    table = []
    for q in questions.load():
        a = [r for r in available if r["question_id"] == q.id]
        b = [r for r in routed if r["question_id"] == q.id]
        if not a and not b:
            continue
        table.append(
            {
                "question_id": q.id,
                "group": q.group,
                "available": run_part2.effort(a) if a else None,
                "routed": run_part2.effort(b) if b else None,
            }
        )
    return table


def evaluate(
    blocks: dict[str, dict[str, Any]],
    rows: dict[str, list[dict[str, Any]]],
    log_check: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Test each prediction in results/part3/predictions.md by its stated rule."""
    out: list[dict[str, Any]] = []

    def add(number: str, held: bool | None, numbers: str) -> None:
        out.append({"prediction": number, "held": held, "numbers": numbers})

    av, ro, ho = rows.get(AVAILABLE, []), rows.get(ROUTED, []), rows.get(ROUTED_HOLDOUT, [])
    if av:
        counted = Counter(r["answer_source"] for r in av)
        top = max(answer_source.SOURCES, key=lambda s: counted.get(s, 0))
        add(
            "P1",
            top == answer_source.BOTH
            and counted[top]
            > max(counted.get(s, 0) for s in answer_source.SOURCES if s != answer_source.BOTH),
            ", ".join(
                f"{s} {counted.get(s, 0)}" for s in (*answer_source.SOURCES, answer_source.NO_VALUE)
            ),
        )
        lookups = [
            r
            for r in av
            if r["question_id"] in LOOKUPS and r["answer_source"] != answer_source.NO_VALUE
        ]
        from_sql = sum(1 for r in lookups if r["answer_source"] == answer_source.SQL)
        add(
            "P2",
            from_sql >= 15,
            f"{from_sql} of {len(lookups)} lookup runs with an answer value from SQL alone",
        )
        w = blocks[AVAILABLE]["tool_use"]["where_one_metric_answers"]
        add(
            "P3",
            w["ran_sql"] >= 38 and w["called_compute_metric"] >= 49,
            f"ran SQL in {w['ran_sql']} of {w['runs']}; called compute_metric in {w['called_compute_metric']}",
        )
        s = blocks[AVAILABLE]["summary"]["overall"]
        add(
            "P4",
            s["right"] >= 68 and s["confidently_wrong"] <= 2,
            f"right {s['right']} of {s['runs']}; confidently wrong {s['confidently_wrong']}",
        )
        t = blocks[AVAILABLE]["tool_use"]["runs_that_called"]
        add(
            "P5",
            t["resolve_entity"] < 18 and t["check_rule"] < 18,
            f"resolve_entity in {t['resolve_entity']} of {len(av)}; check_rule in {t['check_rule']}",
        )
    if ro:
        three = [r for r in ro if r["group"] in ("metric", "entity", "rule")]
        right = sum(1 for r in three if r["outcome"] == scoring.RIGHT)
        via = sum(1 for r in three if r["answer_source"] == answer_source.CONTRACT)
        add(
            "P6", right >= 49 and via >= 45, f"right {right} of {len(three)}; source contract {via}"
        )
        look = [r for r in ro if r["question_id"] in LOOKUPS]
        c = Counter(r["outcome"] for r in look)
        add(
            "P7",
            c[scoring.RIGHT] <= 4
            and c[scoring.DECLINED] >= 9
            and c[scoring.WRONG] < c[scoring.DECLINED],
            f"of {len(look)}: right {c[scoring.RIGHT]}, declined {c[scoring.DECLINED]},"
            f" confidently wrong {c[scoring.WRONG]}, no answer {c[scoring.NO_ANSWER]}",
        )
    if ho:
        h11 = Counter(r["outcome"] for r in ho if r["question_id"] == NOT_ANSWERABLE)
        add(
            "P8",
            h11[scoring.RIGHT] == 0 and h11[scoring.DECLINED] >= 2,
            f"H11: right {h11[scoring.RIGHT]}, declined {h11[scoring.DECLINED]},"
            f" confidently wrong {h11[scoring.WRONG]}, no answer {h11[scoring.NO_ANSWER]}",
        )
        rest = [r for r in ho if r["question_id"] != NOT_ANSWERABLE]
        right = sum(1 for r in rest if r["outcome"] == scoring.RIGHT)
        add("P9", right >= 28, f"right {right} of {len(rest)}")
    if av and ro:
        ea, er = blocks[AVAILABLE]["effort"], blocks[ROUTED]["effort"]
        add(
            "P10",
            er["mean_cost_usd"] < ea["mean_cost_usd"]
            and er["mean_seconds"] < ea["mean_seconds"]
            and ea["mean_sql_queries"] >= 1.5,
            f"cost ${ea['mean_cost_usd']:.4f} available vs ${er['mean_cost_usd']:.4f} routed;"
            f" seconds {ea['mean_seconds']} vs {er['mean_seconds']}; SQL queries {ea['mean_sql_queries']}",
        )
    every = [r for name in (AVAILABLE, ROUTED, ROUTED_HOLDOUT) for r in rows.get(name, [])]
    if every:
        v = versions(every)
        add(
            "P11",
            v["all_stamped"] and set(v["versions_seen"]) == {CONTRACT_VERSION},
            f"{v['with_version_and_response_id']} of {v['contract_responses']} responses stamped;"
            f" versions {v['versions_seen']}",
        )
    if log_check is not None:
        # The rule as written: every call recorded with a response ID is in the log with
        # the same operation, version and caller, and every log line for a run is in that
        # run's record. Calls with no response ID are reported apart.
        agree = (
            log_check["agent_calls_missing_from_server_log"] == 0
            and log_check["calls_that_differ"] == 0
            and log_check["runs_with_a_problem"] == 0
        )
        with_id = log_check["agent_calls"] - log_check["agent_calls_without_response"]
        with_id -= log_check["calls_refused_before_the_contract_ran"]
        add(
            "P12",
            agree,
            f"{log_check['agreeing_calls']} of {with_id} calls recorded with a response ID agree;"
            f" {log_check['server_lines_missing_from_agent_record']} server lines not in an agent"
            f" record; apart: {log_check['calls_refused_before_the_contract_ran']} call(s) refused"
            " by the MCP layer before the contract ran (no response ID, no log line),"
            f" {log_check['agent_calls_without_response']} cut off",
        )
    else:
        add("P12", None, "server log not read back yet")
    return out


def pct(share: float | None) -> str:
    """Format a share as a percentage."""
    return run_part1.pct(share)


def _source_line(name: str, s: dict[str, Any]) -> str:
    cells = [
        f"{s[k]['runs']} ({s[k]['right']} right)"
        for k in (*answer_source.SOURCES, answer_source.NO_VALUE)
    ]
    return f"| {name} | {s['runs']} | " + " | ".join(cells) + " |"


def write_summary(out: Path, runs: int, wanted: set[str] | None) -> dict[str, Any]:
    """Write summary.json and summary.md for whatever runs are saved under ``out``."""
    rows = {name: rows_in(out / "runs" / f"{name}.jsonl") for name in CONFIGS}
    rows = {
        name: [
            r for r in rs if r["trial"] < runs and (wanted is None or r["question_id"] in wanted)
        ]
        for name, rs in rows.items()
        if rs
    }
    rows = {name: rs for name, rs in rows.items() if rs}
    for name, rs in rows.items():
        _, set_name = CONFIGS[name]
        asked, gold = question_set(set_name)
        by_id = {q.id: q for q in asked}
        for row in rs:
            run_part1.rescore(row, by_id, gold)
            row.update(
                {
                    "answer_source": answer_source.classify(
                        row["extracted"], row["answer_type"], row["tool_calls"]
                    )["source"]
                }
            )
    blocks = {name: block_for(name, rs, runs, wanted) for name, rs in rows.items()}
    log_path = RESULTS / "server_log.jsonl"
    log_check = None
    if log_path.exists():
        everything = [r for rs in rows.values() for r in rs]
        log_check = compare_log(everything, read_jsonl(log_path))
    auth = (
        json.loads((RESULTS / "auth_check.json").read_text())
        if (RESULTS / "auth_check.json").exists()
        else None
    )
    predictions = evaluate(blocks, rows, log_check) if out == RESULTS else []
    routed = rows.get(ROUTED, [])
    breaks = {
        "lookups": where_routing_breaks(routed, LOOKUPS),
        "h11": where_routing_breaks(rows.get(ROUTED_HOLDOUT, []), (NOT_ANSWERABLE,)),
    }
    payload = {
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": (
            "Three runs per question: one run is 1.4 points of a 72-run share, 2.8 points of a"
            " 36-run share and 5.6 points within a question group of six. Small differences"
            " are not findings."
        ),
        "contract_version": CONTRACT_VERSION,
        "configurations": blocks,
        "where_routing_breaks": breaks,
        "cost_per_question": per_question_cost(rows.get(AVAILABLE, []), routed),
        "server_log_check": log_check,
        "auth_check": auth,
        "predictions": predictions,
        "spend": spend(),
    }
    (out / "summary.json").write_text(contract_client.scrub(json.dumps(payload, indent=1)) + "\n")
    (out / "summary.md").write_text(contract_client.scrub(render(payload)))
    if log_check is not None and out == RESULTS:
        (RESULTS / "server_log_check.md").write_text(render_log_check(log_check, blocks))
    return payload


def render(p: dict[str, Any]) -> str:
    """The Markdown summary."""
    blocks = p["configurations"]
    lines = [
        "# Part 3 results",
        "",
        "Written by `run_part3.py`. Tessaway Freight is a fictional company and the data is synthetic.",
        "",
        "The Part 2 layers served as one contract (version " + p["contract_version"] + ") by an MCP"
        " server on Cloud Run, called by the Part 2 agent (Google ADK, `" + BASE.model + "`) under"
        " its own service account. **available**: the contract and the SQL tool. **routed**: the"
        " contract only. Each reply is scored by the Part 1 scorer, unchanged.",
        "",
        p["note"],
        "",
        "| Configuration | Questions | Tools | Runs | Complete | Right | Confidently wrong | Declined"
        " | No answer | Est. cost | Cost per question |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for b in blocks.values():
        o = b["summary"]["overall"]
        lines.append(
            f"| {b['config']} | {b['question_set']} ({b['question_count']}) | {len(b['tools'])}"
            f" | {b['runs_saved']} of {b['runs_expected']} | {'yes' if b['complete'] else 'NO'}"
            f" | {pct(o['right_share'])} ({o['right']}) | {pct(o['confidently_wrong_share'])} ({o['confidently_wrong']})"
            f" | {pct(o['declined_share'])} ({o['declined']}) | {pct(o['no_answer_share'])} ({o['no_answer']})"
            f" | ${b['effort']['total_cost_usd']:.2f} | ${b['effort']['mean_cost_usd']:.4f} |"
        )
    lines += [
        "",
        "## By question group: right / confidently wrong / declined / no answer",
        "",
        "| Configuration | " + " | ".join(questions.GROUPS) + " |",
        "| --- |" + " --- |" * len(questions.GROUPS),
    ]
    for b in blocks.values():
        g = b["summary"]["by_group"]
        lines.append(
            f"| {b['config']} | "
            + " | ".join(
                f"{g[x]['right']} / {g[x]['confidently_wrong']} / {g[x]['declined']} / {g[x]['no_answer']}"
                if x in g
                else "n/a"
                for x in questions.GROUPS
            )
            + " |"
        )

    lines += [
        "",
        "## 1. Where each answer came from",
        "",
        "Worked out in code (`tessaway/answer_source.py`) by matching the value on the final"
        " `ANSWER:` line against every value the contract and the SQL tool returned in the run."
        ' The agent\'s own account is not used. "both" means the two routes returned the same'
        " value. Each cell: runs (of which right).",
        "",
        "| Configuration | Runs | contract | sql | both | neither | no answer value |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for b in blocks.values():
        lines.append(_source_line(b["config"], b["answer_source"]))
    lines += [
        "",
        "### By question group",
        "",
        "| Configuration | Group | Runs | contract | sql | both | neither | no answer value |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for b in blocks.values():
        for group, s in b["answer_source_by_group"].items():
            lines.append(_source_line(f"{b['config']} | {group}", s))

    lines += [
        "",
        "## 2. Tool calls",
        "",
        "Mean calls per run (runs that called it). Calls refused over a limit are not counted.",
        "",
        "| Configuration | "
        + " | ".join(f"`{t}`" for t in (SQL, *OPERATIONS))
        + " | No contract call | No SQL | First call SQL | First call contract |",
        "| --- |" + " --- |" * (len(OPERATIONS) + 5),
    ]
    for b in blocks.values():
        u = b["tool_use"]
        cells = [
            f"{u['mean_calls_per_run'][t]:.2f} ({u['runs_that_called'][t]})"
            for t in (SQL, *OPERATIONS)
        ]
        lines.append(
            f"| {b['config']} | "
            + " | ".join(cells)
            + f" | {u['runs_with_no_contract_call']} | {u['runs_with_no_sql_call']}"
            f" | {u['runs_whose_first_call_was_sql']} | {u['runs_whose_first_call_was_the_contract']} |"
        )
    for b in blocks.values():
        w = b["tool_use"].get("where_one_metric_answers")
        if w and b["configuration"] == contract_prompt.AVAILABLE:
            lines += [
                "",
                f"On the questions one metric answers ({b['config']}, {w['runs']} runs):"
                f" `compute_metric` called in {w['called_compute_metric']}, SQL run in {w['ran_sql']},"
                f" both in {w['called_both']}, SQL without the metric in {w['sql_only']},"
                f" the contract without SQL in {w['contract_only']}.",
            ]

    lines += [
        "",
        "## 3. What the second route costs: per question, available against routed",
        "",
        "| Configuration | SQL queries | Input tokens | Output tokens | Model calls | Seconds | Cost |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for b in blocks.values():
        e = b["effort"]
        lines.append(
            f"| {b['config']} | {e['mean_sql_queries']:.2f} | {e['mean_input_tokens']:,d}"
            f" | {e['mean_output_tokens']:,d} | {e['mean_model_calls']:.2f} | {e['mean_seconds']:.1f}"
            f" | ${e['mean_cost_usd']:.4f} |"
        )
    if p["cost_per_question"]:
        lines += [
            "",
            "| Question | Group | SQL queries (available) | Cost available | Cost routed"
            " | Seconds available | Seconds routed |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for item in p["cost_per_question"]:
            a, r = item["available"], item["routed"]
            cost_a = "${:.4f}".format(a["mean_cost_usd"]) if a else "n/a"
            cost_r = "${:.4f}".format(r["mean_cost_usd"]) if r else "n/a"
            lines.append(
                f"| {item['question_id']} | {item['group']} | {a['mean_sql_queries'] if a else 'n/a'}"
                f" | {cost_a} | {cost_r}"
                f" | {a['mean_seconds'] if a else 'n/a'} | {r['mean_seconds'] if r else 'n/a'} |"
            )

    lines += [
        "",
        "## 4. What routing breaks: the six lookups and H11, routed",
        "",
        "| Question | Run | What it did | Final answer | Correct | Operations called |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in p["where_routing_breaks"]["lookups"] + p["where_routing_breaks"]["h11"]:
        ops = ", ".join(item["operations_called"]) or "none"
        lines.append(
            f"| {item['question_id']} | {item['trial'] + 1} | {item['what_it_did']}"
            f" | {item['extracted'][:40] or '(none)'} | {item['gold']} | {ops} |"
        )

    lines += ["", "## 5. Versions and the server's record", ""]
    for b in blocks.values():
        v = b["versions"]
        lines.append(
            f"- {b['config']}: {v['with_version_and_response_id']} of {v['contract_responses']}"
            f" contract responses carried a version and a response ID; versions seen {v['versions_seen']}."
        )
    lc = p["server_log_check"]
    if lc:
        lines.append(
            f"- Server log against the agents' records: {lc['agreeing_calls']} of {lc['agent_calls']}"
            f" recorded calls agree (same response ID, operation, version and caller);"
            f" {lc['agent_calls_missing_from_server_log']} recorded calls missing from the log;"
            f" {lc['server_lines_missing_from_agent_record']} log lines not in an agent's record;"
            f" {lc['runs_agreeing']} of {lc['runs']} runs agree in full. See `server_log_check.md`."
        )
    if p.get("auth_check"):
        for item in p["auth_check"]["results"]:
            lines.append(
                f"- Secured: {item['call']} -> HTTP {item['http_status']}, {item['outcome']}"
                f" ({'as expected' if item['as_expected'] else 'NOT as expected'})."
            )

    lines += [
        "",
        "## Limits and failures",
        "",
        "| Configuration | Model-call ceiling | Refused a further SQL query | Refused a further contract call"
        " | Hit the ceiling | Timed out | Ended in an error |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for b in blocks.values():
        lim = b["limits"]
        lines.append(
            f"| {b['config']} | {b['model_call_ceiling']} | {lim['runs_refused_a_further_sql_query']}"
            f" | {lim['runs_refused_a_further_contract_call']} | {lim['runs_that_hit_the_model_call_ceiling']}"
            f" | {lim['runs_that_timed_out']} | {lim['runs_that_ended_in_an_error']} |"
        )

    if p["predictions"]:
        lines += [
            "",
            "## Predictions",
            "",
            "As written in `predictions.md` before the first scored run, each tested by its own rule.",
            "",
            "| # | Held | Numbers |",
            "| --- | --- | --- |",
        ]
        for item in p["predictions"]:
            held = "not tested" if item["held"] is None else ("yes" if item["held"] else "NO")
            lines.append(f"| {item['prediction']} | {held} | {item['numbers']} |")
    s = p["spend"]
    lines += [
        "",
        "## Spend",
        "",
        f"- Gemini (model) ${s['gemini_model_usd']:.2f} and BigQuery ${s['bigquery_usd']:.4f}:"
        f" ${s['gemini_total_usd']:.2f} for Part 3, smoke tests included.",
        f"- Anthropic (Claude demonstration, outside the Gemini budget): ${s['anthropic']['usd']:.2f}"
        f" over {s['anthropic']['runs']} runs.",
        "",
        f"Model names and prices were checked on {config.MODELS_VERIFIED_ON}. Costs are estimates.",
        "",
    ]
    return "\n".join(lines)


def render_log_check(lc: dict[str, Any], blocks: dict[str, dict[str, Any]]) -> str:
    """The server-log check, in Markdown."""
    lines = [
        "# Part 3: the server's call log against the agents' own records",
        "",
        "Written by `run_part3.py`. The context server writes one structured line per contract"
        " call (caller, operation, contract version, time, response ID, run ID). After the runs"
        " the lines were read back from Cloud Logging (`server_log.jsonl`) and compared with what"
        " each agent recorded itself: the response ID, operation and version of every contract"
        " response it received, and the service account it ran under.",
        "",
        "| Measure | Count |",
        "| --- | --- |",
        f"| Runs compared | {lc['runs']} |",
        f"| Runs whose two records agree in full | {lc['runs_agreeing']} |",
        f"| Contract calls the agents recorded | {lc['agent_calls']} |",
        f"| Server log lines for those runs | {lc['server_lines']} |",
        f"| Recorded calls that agree (response ID, operation, version, caller) | {lc['agreeing_calls']} |",
        f"| Recorded calls missing from the server log | {lc['agent_calls_missing_from_server_log']} |",
        f"| Recorded calls with no response and no error (the run was cut off) | {lc['agent_calls_without_response']} |",
        f"| Recorded calls the MCP layer refused before the contract ran (invalid arguments: no response ID, no log line) | {lc['calls_refused_before_the_contract_ran']} |",
        f"| Server log lines not in the agent's record | {lc['server_lines_missing_from_agent_record']} |",
        f"| Calls that differ | {lc['calls_that_differ']} |",
        f"| Runs with a mismatch, not cut off | {lc['runs_with_a_problem']} |",
        f"| Runs with a mismatch, cut off by a timeout or an error | {lc['runs_cut_off_with_a_problem']} |",
        "",
        "Callers in the log (the project id is replaced by PROJECT):",
        "",
    ]
    lines += [
        f"- `{caller}`: {count} calls" for caller, count in sorted(lc["callers_in_log"].items())
    ]
    if lc["problems"]:
        lines += ["", "## Mismatches", "", "```", *[json.dumps(x) for x in lc["problems"]], "```"]
    lines.append("")
    return "\n".join(lines)


# --- the Claude demonstration (unscored) -------------------------------------------------


async def claude_demo(out: Path, wanted: set[str] | None, concurrency: int = 3) -> None:
    """One unscored pass over the 24 questions with the Claude Agent SDK.

    Records whether each run worked, which operations it called, and what it
    cost. Nothing is scored, and no answer is saved, so no accuracy figure can
    be read from it. New runs stop once the estimated spend could pass the cap.
    """
    from tessaway.agents import claude_contract_agent

    asked = [q for q in questions.load() if wanted is None or q.id in wanted]
    path = out / "runs" / "claude_demo.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = {r["question_id"] for r in rows_in(path)}
    todo = [q for q in asked if q.id not in done]
    where = contract_client.deployment()
    caller = where.callers["claude"]
    state: dict[str, Any] = {"spent": spend()["anthropic"]["usd"], "most": 0.15, "stopped": False}
    gate, lock = asyncio.Semaphore(concurrency), asyncio.Lock()

    async def one(question: questions.Question) -> None:
        async with gate:
            if state["spent"] + concurrency * state["most"] >= CLAUDE_CAP_USD:
                state["stopped"] = True
                return
            token = await asyncio.to_thread(contract_client.id_token, caller, where.url)
            run = await claude_contract_agent.ask(
                CLAUDE.model, question.question, where.endpoint, token
            )
            cost = CLAUDE.cost(
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                cache_read=run.cache_read_tokens,
                cache_write=run.cache_write_tokens,
            )
            contract_calls = [c for c in run.tool_calls if c["tool"] in OPERATIONS]
            row: dict[str, Any] = {
                "config": "claude_demo",
                "runtime": "claude_sdk",
                "configuration": contract_prompt.AVAILABLE,
                "model": CLAUDE.model,
                "model_reported": run.model_reported,
                "question_id": question.id,
                "group": question.group,
                "trial": 0,
                "run_id": run.run_id,
                "caller": caller,
                "gave_a_final_answer_line": scoring.extract_answer(run.final_text) is not None,
                "tool_calls": run.tool_calls,
                "tools_in_order": [c["tool"] for c in run.tool_calls],
                "contract_calls": len(contract_calls),
                "contract_calls_with_version": sum(
                    1 for c in contract_calls if c.get("contract_version")
                ),
                "sql_queries": len(run.queries),
                "model_calls": run.model_calls,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "cache_read_tokens": run.cache_read_tokens,
                "cache_write_tokens": run.cache_write_tokens,
                "cost_usd": round(cost, 6),
                "sdk_reported_cost_usd": run.sdk_cost_usd,
                "bigquery_usd": round(run.bytes_billed / 2**40 * config.BQ_USD_PER_TIB, 6),
                "seconds": round(run.seconds, 1),
                "timed_out": run.timed_out,
                "error": run.error,
                "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            row = scrubbed(row)
            async with lock:
                with path.open("a") as handle:
                    handle.write(json.dumps(row) + "\n")
                state["spent"] += max(cost, float(run.sdk_cost_usd or 0))
                state["most"] = max(state["most"], cost)
                print(
                    f"[claude_demo] {question.id} contract={row['contract_calls']} sql={row['sql_queries']}"
                    f" ${cost:.4f} total=${state['spent']:.2f}"
                    f"{' ERR ' + row['error'][:100] if row['error'] else ''}",
                    flush=True,
                )

    await asyncio.gather(*(one(q) for q in todo))
    if state["stopped"]:
        print(f"[claude_demo] STOPPED before the ${CLAUDE_CAP_USD:.2f} cap; the pass is partial.")


def write_claude_demo(out: Path) -> None:
    """Write claude_demo.md: whether it worked, which operations it called, what it cost."""
    rows = rows_in(out / "runs" / "claude_demo.jsonl")
    if not rows:
        return
    ops = Counter(c["tool"] for r in rows for c in r["tool_calls"])
    worked = [r for r in rows if not r["error"] and not r["timed_out"] and r["contract_calls"]]
    log_path = RESULTS / "server_log.jsonl"
    log = read_jsonl(log_path)
    ids = {r["run_id"] for r in rows}
    in_log = [line for line in log if line.get("run_id") in ids]
    recorded = {c.get("response_id") for r in rows for c in r["tool_calls"] if c.get("response_id")}
    cost = sum(float(r["cost_usd"]) for r in rows)
    sdk_cost = sum(float(r.get("sdk_reported_cost_usd") or 0) for r in rows)
    lines = [
        "# Part 3: the Claude demonstration",
        "",
        "Unscored. One pass over the 24 Part 1 questions with the Claude Agent SDK"
        f" (claude-agent-sdk=={importlib.metadata.version('claude-agent-sdk')}) and `{CLAUDE.model}`,"
        " reached through Anthropic's API (not Vertex AI), with the key read at run time from the"
        " macOS Keychain. The agent ran the **available** configuration: the Part 1 SQL tool"
        " in-process, and the same deployed contract endpoint the Gemini agents used, as a remote"
        " MCP server over HTTP, under its own service account. It has no context code of its own.",
        "",
        "No answer was scored and none is reported. This file says only whether it worked, which"
        " operations it called, and what it cost.",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Questions run | {len(rows)} of 24 |",
        f"| Runs that called the contract and finished without an error | {len(worked)} |",
        f"| Runs that ended in an error or a timeout | {sum(1 for r in rows if r['error'] or r['timed_out'])} |",
        f"| Runs that called no contract operation | {sum(1 for r in rows if not r['contract_calls'])} |",
        f"| Contract responses that carried the version | {sum(r['contract_calls_with_version'] for r in rows)}"
        f" of {sum(r['contract_calls'] for r in rows)} |",
        f"| Server log lines for these runs, and how many match a recorded response ID | {len(in_log)},"
        f" {sum(1 for line in in_log if line.get('response_id') in recorded)} |",
        f"| SQL queries | {sum(r['sql_queries'] for r in rows)} |",
        f"| Estimated cost (list prices) | ${cost:.2f} |",
        f"| Cost the SDK reported | ${sdk_cost:.2f} |",
        f"| Cap | ${CLAUDE_CAP_USD:.2f} |",
        "",
        "Calls by tool (the four contract operations, and the SQL tool):",
        "",
    ]
    lines += [f"- `{name}`: {count}" for name, count in sorted(ops.items())]
    callers = Counter(str(line.get("caller")) for line in in_log)
    lines += [
        "",
        "Caller in the server log: " + ", ".join(f"`{c}` ({n})" for c, n in callers.items()),
        "",
    ]
    errors = [r for r in rows if r["error"]]
    if errors:
        lines += (
            ["Errors:", ""] + [f"- {r['question_id']}: {r['error'][:200]}" for r in errors] + [""]
        )
    (out / "claude_demo.md").write_text(contract_client.scrub("\n".join(lines)))


# --- main ---------------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> None:
    """Run what was asked, then write the results files."""
    out = RESULTS / args.out if args.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    wanted = set(args.questions.split(",")) if args.questions else None
    if args.check_auth:
        report = check_auth()
        print(json.dumps(report["results"], indent=1))
        return
    if args.read_server_log:
        count = save_server_log(args.since)
        print(f"read {count} server log lines since {args.since}")
    if args.claude_demo:
        await claude_demo(out, wanted)
        write_claude_demo(out)
    names = args.configs or ([] if (args.claude_demo or args.read_server_log) else list(CONFIGS))
    unknown = [n for n in names if n not in CONFIGS]
    if unknown:
        raise SystemExit(f"Unknown configuration(s): {', '.join(unknown)}")
    if not args.summarize_only:
        for name in names:
            await run_config(
                name,
                runs=args.runs,
                wanted=wanted,
                concurrency=args.concurrency,
                budget_usd=args.budget_usd,
                out=out,
                retry_failed=args.retry_failed,
            )
    write_summary(out, args.runs, wanted)
    write_claude_demo(out)
    ledger = write_ledger(args.cloud_run_usd)
    totals = spend()
    print(
        f"estimated Part 3 Gemini spend so far: ${totals['gemini_total_usd']:.2f};"
        f" Anthropic: ${totals['anthropic']['usd']:.2f}"
    )
    print(
        f"Parts 2 to 7 so far: ${ledger['spent_usd_parts_2_to_7']:.2f} of"
        f" ${run_part2.SERIES_APPROVED_USD:.0f} approved (hard cap ${run_part2.SERIES_CAP_USD:.0f})"
    )
    print(f"results in {out.relative_to(ROOT)}")


def parse_args() -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description="Run the Part 3 experiment.")
    parser.add_argument("configs", nargs="*", help=f"Any of: {', '.join(CONFIGS)}")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--questions", default="")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--out", default="")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--check-auth", action="store_true")
    parser.add_argument("--read-server-log", action="store_true")
    parser.add_argument("--since", default="2026-10-13T00:00:00Z")
    parser.add_argument("--claude-demo", action="store_true")
    parser.add_argument("--cloud-run-usd", type=float, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
