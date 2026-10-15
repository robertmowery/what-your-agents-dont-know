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

"""Runs the Part 4 experiment: every answer cites the definitions it used.

Part 4 adds a definition registry (``data/definition_registry.json``): every
definition gets an id, a version and an owner. The context server (contract
2.0.0) stamps each response with the definitions it served, and writes them in
its call log. The agent is Part 3's, told one more thing: name the definitions
its answer relies on, on a SOURCES line before the ANSWER line. Plain code
(``tessaway/traceability.py``) decides whether each answer is traceable.

    available         the contract and the SQL tool; the 24 Part 1 questions
                      (Part 5 reuses this run as its baseline)
    routed_holdout    the contract only; the 12 held-out questions

Predictions: ``results/part4/predictions.md``, committed before the first scored run.

Usage:
    python run_part4.py [CONFIG ...] [options]

    python run_part4.py                                       # both, 3 runs each
    python run_part4.py available routed_holdout --runs 1 --questions L1,M1,H1,H10 --out smoke
    python run_part4.py --read-server-log --since 2026-10-13T18:00:00Z
    python run_part4.py --summarize-only
    python run_part4.py --audit RUN_ID                         # print one run's audit trail

Options:
    --runs N, --questions IDS, --concurrency N, --out NAME, --retry-failed: as in Part 3.
    --budget-usd X     Stop starting runs once estimated Part 4 Gemini spend reaches X (default 7).

Files written (under results/part4, or results/part4/NAME):
    runs/<config>.jsonl, server_log.jsonl, summary.json, summary.md, audit.md,
    server_log_check.md, and the Part 4 lines of results/series_spend.json.
Nothing written names the Google Cloud project, the service URL or an email
address: ``tessaway.contract_client.scrub`` runs over every saved line.
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_part2
import run_part3
from context_server import contract
from tessaway import contract_client, questions, registry, scoring, traceability
from tessaway.agents import adk_contract_agent, contract_prompt, provenance_prompt

ROOT = Path(__file__).parent
RESULTS = ROOT / "results" / "part4"
PART3 = ROOT / "results" / "part3"
LEDGER_PATH = run_part2.LEDGER_PATH
BASE = run_part2.BASE
DEFAULT_RUNS = 3
DEFAULT_BUDGET_USD = 7.0
PART4_LINE_USD = 2.40
PLANNED_USD = 4.60
CONTRACT_VERSION = contract.CONTRACT_VERSION

AVAILABLE, ROUTED_HOLDOUT = "available", "routed_holdout"
CONFIGS: dict[str, tuple[str, str]] = {
    AVAILABLE: (contract_prompt.AVAILABLE, "part1"),
    ROUTED_HOLDOUT: (contract_prompt.ROUTED, "holdout"),
}
OPERATIONS = contract_prompt.OPERATIONS
LOOKUPS = run_part3.LOOKUPS
# The audit fallback, fixed in predictions.md before any run.
FALLBACK_AUDIT = {"config": "routed_holdout", "question_id": "H10", "trial": 0}


_SA_SUFFIX = re.compile(r"@PROJECT\.iam\.gserviceaccount\.com")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def clean(text: str) -> str:
    """Take the project id, the service URL and every email address out of text to be saved.

    A service account keeps its short name (``tw-p3-agent-available``); any
    other address becomes EMAIL.
    """
    text = _SA_SUFFIX.sub("", contract_client.scrub(text))
    return _EMAIL.sub("EMAIL", text)


def cleaned(item: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a saved item with ``clean`` applied."""
    return dict(json.loads(clean(json.dumps(item))))


def question_order(set_name: str) -> list[str]:
    """Question ids in the order of their question file."""
    return [q.id for q in run_part3.question_set(set_name)[0]]


def is_lookup(row: dict[str, Any]) -> bool:
    """A lookup question needs no definition."""
    return row["group"] == "lookup"


def answered(row: dict[str, Any]) -> bool:
    """The run ended with an answer value (right or confidently wrong)."""
    return row["outcome"] in (scoring.RIGHT, scoring.WRONG)


def to_row(
    name: str,
    question: questions.Question,
    trial: int,
    run: adk_contract_agent.ContractAgentRun,
    gold: dict[str, Any],
    caller: str,
) -> dict[str, Any]:
    """Part 3's saved row, plus the citation and the definitions the agent's record says it got."""
    row = cleaned(run_part3.to_row(name, question, trial, run, gold, caller))
    parsed = traceability.parse_sources(run.final_text)
    row["sources_line"] = parsed["line_found"]
    row["sources_cited"] = [f"{i}@{v}" for i, v in parsed["cited"]]
    row["sources_malformed"] = parsed["malformed"]
    row["served_by_agent_record"] = sorted(
        f"{i}@{v}" for i, v in traceability.served_in_record(run.tool_calls)
    )
    row["contract_responses_without_definitions_field"] = sum(
        1
        for c in run.tool_calls
        if c["tool"] in OPERATIONS and "result" in c and "definitions" not in c
    )
    return row


def spend(root: Path = RESULTS) -> dict[str, Any]:
    """Estimated Part 4 spend across every saved run, smoke tests included."""
    return run_part3.spend(root)


def write_ledger(cloud_run_usd: float | None = None) -> dict[str, Any]:
    """Write the Part 4 lines of the series ledger."""
    ledger = json.loads(LEDGER_PATH.read_text()) if LEDGER_PATH.exists() else {}
    parts = dict(ledger.get("parts", {}))
    totals = spend()
    previous = parts.get("4", {})
    parts["4"] = {
        "what": "Provenance: available with citations, 24 questions (Part 5's baseline); routed with citations, 12 held-out.",
        "line_usd": PART4_LINE_USD,
        "planned_usd": PLANNED_USD,
        "stop_line_usd": DEFAULT_BUDGET_USD,
        "spent_usd": totals["gemini_total_usd"],
        "model_usd": totals["gemini_model_usd"],
        "bigquery_usd": totals["bigquery_usd"],
        "by_folder": totals["gemini_by_folder"],
    }
    if cloud_run_usd is not None or "cloud_run_usd_estimate" in previous:
        parts["4"]["cloud_run_usd_estimate"] = (
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
    instruction = provenance_prompt.build_instruction(configuration)
    asked, gold = run_part3.question_set(set_name)
    asked = [q for q in asked if wanted is None or q.id in wanted]
    path = out / "runs" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = {(r["question_id"], r["trial"]): r for r in run_part3.rows_in(path)}
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
                BASE.model, question.question, configuration, where.endpoint, token, instruction
            )
            row = to_row(name, question, trial, run, gold[question.id], caller)
            if (question.id, trial) in done:
                row["retry_of_failed"] = True
            async with lock:
                with path.open("a") as handle:
                    handle.write(json.dumps(row) + "\n")
                state["spent"] += row["cost_usd"] + row["bigquery_usd"]
                state["finished"] += 1
                print(
                    f"[{name}] {question.id} #{trial} {row['outcome']:<17}"
                    f" {row['extracted'][:24]!r} cites={','.join(row['sources_cited']) or '-'}"
                    f" ${row['cost_usd']:.4f} total=${state['spent']:.2f}"
                    f" ({state['finished']}/{len(todo)}){' ERR ' + row['error'][:80] if row['error'] else ''}",
                    flush=True,
                )

    await asyncio.gather(*(one(question, trial) for question, trial in todo))
    if state["stopped"]:
        print(f"[{name}] STOPPED at the budget of ${budget_usd:.2f}; the run is partial.")


# --- the server log -----------------------------------------------------------------------


def save_server_log(since: str, out: Path = RESULTS) -> int:
    """Read the server's call log back from Cloud Logging and save it beside the runs."""
    lines = [cleaned(line) for line in run_part3.read_server_log(since)]
    (out / "server_log.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    return len(lines)


def log_by_run(out: Path = RESULTS) -> dict[str, list[dict[str, Any]]]:
    """The saved server log, grouped by the run ID each call carried."""
    found: dict[str, list[dict[str, Any]]] = {}
    for line in run_part3.read_jsonl(out / "server_log.jsonl"):
        found.setdefault(str(line.get("run_id", "")), []).append(line)
    return found


def trace(row: dict[str, Any], log: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Apply the three checks to one saved run against the server log."""
    served = traceability.served_in_log(log.get(row["run_id"], []))
    return traceability.check(row["answer_text"], served)


# --- the measurements ----------------------------------------------------------------------


def share(n: int, d: int) -> float | None:
    """Return n as a percentage of d, or None when d is zero."""
    return round(100.0 * n / d, 1) if d else None


def traceability_block(
    rows: list[dict[str, Any]], log: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Every traceability number for one configuration, by the rules in predictions.md."""
    checked = [(r, trace(r, log)) for r in rows]
    need = [(r, t) for r, t in checked if not is_lookup(r)]
    need_answered = [(r, t) for r, t in need if answered(r)]
    lookups = [(r, t) for r, t in checked if is_lookup(r)]

    def statuses(items: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, int]:
        counted = Counter(t["status"] for _, t in items)
        return {s: counted.get(s, 0) for s in traceability.STATUSES}

    def misses(items: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, int]:
        """Non-traceable runs by kind; cites_none splits by whether anything was served."""
        out = Counter()
        for _, t in items:
            if t["traceable"]:
                continue
            kind = t["status"]
            if kind in (traceability.CITES_NONE, traceability.NO_SOURCES_LINE):
                kind += "_but_served" if t["served"] else "_nothing_served"
            out[kind] += 1
        return dict(out)

    traceable = sum(1 for _, t in need_answered if t["traceable"])
    return {
        "runs": len(rows),
        "needs_definition": {
            "runs": len(need),
            "answered_runs": len(need_answered),
            "traceable": traceable,
            "share_traceable_of_answered": share(traceable, len(need_answered)),
            "traceable_of_all_runs": sum(1 for _, t in need if t["traceable"]),
            "share_traceable_of_all_runs": share(
                sum(1 for _, t in need if t["traceable"]), len(need)
            ),
            "citing_without_using": sum(1 for _, t in need_answered if t["cited_not_served"]),
            "share_citing_without_using": share(
                sum(1 for _, t in need_answered if t["cited_not_served"]), len(need_answered)
            ),
            "using_without_citing": sum(1 for _, t in need_answered if t["served_not_cited"]),
            "share_using_without_citing": share(
                sum(1 for _, t in need_answered if t["served_not_cited"]), len(need_answered)
            ),
            "statuses_answered": statuses(need_answered),
            "misses_answered": misses(need_answered),
            "statuses_all": statuses(need),
            "sources_line_unreadable_as_json": sum(
                1 for r, _ in need if r.get("sources_malformed")
            ),
            "by_group": {
                g: {
                    "answered": len(items),
                    "traceable": sum(1 for _, t in items if t["traceable"]),
                    "share": share(sum(1 for _, t in items if t["traceable"]), len(items)),
                }
                for g in questions.GROUPS
                if (items := [(r, t) for r, t in need_answered if r["group"] == g])
            },
            "by_question": {
                qid: {
                    "answered": len(items),
                    "traceable": sum(1 for _, t in items if t["traceable"]),
                    "statuses": [t["status"] for _, t in items],
                    "cited": sorted({c for _, t in items for c in t["cited"]}),
                }
                for qid in dict.fromkeys(r["question_id"] for r in rows)
                if (items := [(r, t) for r, t in need_answered if r["question_id"] == qid])
            },
        },
        "lookups": {
            "runs": len(lookups),
            "cite_nothing": sum(1 for _, t in lookups if t["sources_line"] and not t["cited"]),
            "no_sources_line": sum(1 for _, t in lookups if not t["sources_line"]),
            "cite_something": sum(1 for _, t in lookups if t["cited"]),
            "cite_something_served": sum(1 for _, t in lookups if t["cited"] and t["traceable"]),
            "served_something": sum(1 for _, t in lookups if t["served"]),
        },
        "record_and_log_agree_on_served": sum(
            1 for r, t in checked if sorted(r.get("served_by_agent_record") or []) == t["served"]
        ),
        "definition_versions_per_run": {
            r["run_id"]: {
                "question_id": r["question_id"],
                "trial": r["trial"],
                "cited": t["cited"],
                "served": t["served"],
                "status": t["status"],
            }
            for r, t in checked
        },
    }


def unmapped(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Terms, metrics and rules a response handed back that the registry does not map."""
    index = registry.index()
    missing: Counter[str] = Counter()
    for r in rows:
        for c in r["tool_calls"]:
            res = c.get("result")
            if c["tool"] not in OPERATIONS or not isinstance(res, dict) or "error" in res:
                continue
            if c["tool"] == contract.LOOKUP_DEFINITION:
                names = [("terms", m.get("term", "")) for m in res.get("matches") or []]
            elif c["tool"] == contract.COMPUTE_METRIC:
                names = [("metrics", m) for m in (c.get("arguments") or {}).get("metrics") or []]
            elif c["tool"] == contract.CHECK_RULE:
                names = [("rules", m.get("rule", "")) for m in res.get("matches") or []]
            else:
                names = [
                    ("terms", t) for e in res.get("entities") or [] for t in e.get("types") or []
                ]
            for kind, name in names:
                if (kind, str(name)) not in index:
                    missing[f"{kind}:{name}"] += 1
    return {"names_not_in_registry": dict(missing), "count": sum(missing.values())}


def bins(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count runs in each scoring bin."""
    counted = Counter(r["outcome"] for r in rows)
    return {b: counted.get(b, 0) for b in scoring.BINS}


def accuracy_against_part3(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """This run's bins beside Part 3's run of the same configuration and questions."""
    before = run_part3.rows_in(PART3 / "runs" / f"{name}.jsonl")
    now, then = bins(rows), bins(before)
    return {
        "part3_runs": len(before),
        "part4_runs": len(rows),
        "part3": then,
        "part4": now,
        "change_in_runs": {b: now[b] - then[b] for b in scoring.BINS},
        "by_question": {
            qid: {
                "part3": bins([r for r in before if r["question_id"] == qid]),
                "part4": bins([r for r in rows if r["question_id"] == qid]),
            }
            for qid in question_order(CONFIGS[name][1])
        },
    }


# --- the audit ---------------------------------------------------------------------------


def pick_audit(rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """The audit example, by the rule in predictions.md.

    The first confidently wrong run: configurations in the order available,
    routed_holdout; questions in question-file order; trials ascending. If
    there is none, Part 3's routed_holdout H10 run 0, labeled as from Part 3.
    """
    for name in CONFIGS:
        order = question_order(CONFIGS[name][1])
        wrong = sorted(
            (r for r in rows.get(name, []) if r["outcome"] == scoring.WRONG),
            key=lambda r: (order.index(r["question_id"]), r["trial"]),
        )
        if wrong:
            return {"from": "part4", "config": name, "row": wrong[0]}
    part3 = run_part3.rows_in(PART3 / "runs" / f"{FALLBACK_AUDIT['config']}.jsonl")
    row = next(
        r
        for r in part3
        if r["question_id"] == FALLBACK_AUDIT["question_id"]
        and r["trial"] == FALLBACK_AUDIT["trial"]
    )
    return {"from": "part3", "config": FALLBACK_AUDIT["config"], "row": cleaned(row)}


def _metric_descriptions() -> dict[str, str]:
    catalog = json.loads((ROOT / "semantic_layer" / "catalog.json").read_text())
    return {
        m["name"]: str(m.get("description") or m.get("label") or "") for m in catalog["metrics"]
    }


def audit(row: dict[str, Any], log_lines: list[dict[str, Any]], origin: str) -> dict[str, Any]:
    """Follow one answer to the definitions, versions and owners behind it, step by step."""
    steps: list[dict[str, Any]] = []
    clock = time.perf_counter()

    def step(name: str, detail: Any) -> None:
        nonlocal clock
        now = time.perf_counter()
        steps.append({"step": name, "ms": round((now - clock) * 1000, 2), "detail": detail})
        clock = now

    step(
        "the answer",
        {
            "question_id": row["question_id"],
            "trial": row["trial"],
            "outcome": row["outcome"],
            "answer": row["extracted"],
            "gold": row["gold"],
            "run_id": row["run_id"],
            "final_lines": "\n".join(row["answer_text"].strip().splitlines()[-4:]),
        },
    )
    parsed = traceability.parse_sources(row["answer_text"])
    step(
        "what the answer cites",
        {
            "sources_line": parsed["raw"] if parsed["line_found"] else None,
            "cited": [f"{i}@{v}" for i, v in parsed["cited"]],
        },
    )
    calls = []
    by_rid = {str(line.get("response_id")): line for line in log_lines}
    for c in row["tool_calls"]:
        if c["tool"] not in OPERATIONS or c.get("refused"):
            continue
        served_here = [
            f"{i}@{registry.definitions()[i].version}"
            for i in contract.served_definitions(
                c["tool"], c.get("arguments"), c.get("result") or {}
            )
        ]
        logged = by_rid.get(str(c.get("response_id")))
        calls.append(
            {
                "seq": c["seq"],
                "operation": c["tool"],
                "arguments": c.get("arguments"),
                "contract_version": c.get("contract_version"),
                "definitions_in_response": [
                    f"{d['id']}@{d['version']}" for d in c.get("definitions") or []
                ],
                "definitions_by_registry_mapping": served_here,
                "in_server_log": logged is not None,
                "server_log_definitions": logged.get("definitions") if logged else None,
                "server_log_time": (logged.get("time") or logged.get("log_timestamp"))
                if logged
                else None,
                "result_rows": (c.get("result") or {}).get("rows")
                if c["tool"] == contract.COMPUTE_METRIC
                else None,
            }
        )
    step(
        "the server's record of the run",
        {"contract_calls": calls, "server_log_lines": len(log_lines)},
    )
    if origin == "part4":
        served = traceability.served_in_log(log_lines)
        basis = "the server log's definitions field"
    else:
        # Contract 1.0.0 did not stamp definitions. Rebuild what each call served
        # through the Part 4 registry, and count only calls the server log confirms.
        served = {
            (d.split("@")[0], int(d.split("@")[1]))
            for c in calls
            if c["in_server_log"]
            for d in c["definitions_by_registry_mapping"]
        }
        basis = "Part 3 calls confirmed in Part 3's server log by response ID, mapped through the Part 4 registry at version 1"
    checked = traceability.check(row["answer_text"], served)
    step(
        "the three checks",
        {
            "basis_for_served": basis,
            **{
                k: checked[k]
                for k in (
                    "status",
                    "cited",
                    "unregistered",
                    "cited_not_served",
                    "served",
                    "served_not_cited",
                )
            },
        },
    )
    descriptions = _metric_descriptions()
    owners = registry.load()["owners"]
    defs = []
    named = [c.split("@")[0] for c in checked["cited"]] or [
        s.split("@")[0] for s in checked["served"]
    ]
    for ident in dict.fromkeys(named):
        entry = registry.load()["definitions"].get(ident)
        if not entry:
            defs.append({"id": ident, "in_registry": False})
            continue
        metric_text = {
            m: descriptions.get(m, "")
            for m in entry["serves"]["metrics"]
            if any(m in (c.get("arguments") or {}).get("metrics", []) for c in row["tool_calls"])
        }
        defs.append(
            {
                "id": ident,
                "title": entry["title"],
                "version": entry["version"],
                "owner": entry["owner"],
                "owner_role": owners.get(entry["owner"], ""),
                "where": entry["where"],
                "history": entry["history"],
                "metrics_used_in_this_run": metric_text,
            }
        )
    step("the registry entries and owners", defs)
    return {"from": origin, "steps": steps, "check": checked}


def render_audit(picked: dict[str, Any], result: dict[str, Any]) -> str:
    """Render one audit trail as Markdown."""
    row = picked["row"]
    lines = ["# Part 4 audit: one wrong answer, followed home", ""]
    if picked["from"] == "part3":
        lines += [
            "**This run is from Part 3, not Part 4.** No Part 4 run was confidently wrong, so by the rule in `predictions.md` the audit is Part 3's routed_holdout H10 run 0. Contract 1.0.0 did not stamp definitions and Part 3's agent was not asked to cite, so the definitions served are rebuilt from the calls Part 3 recorded, through the Part 4 registry at version 1 (no definition has changed since), and each call is confirmed in Part 3's server log by its response ID.",
            "",
        ]
    else:
        lines += [
            f"Picked by the rule in `predictions.md`: the first confidently wrong Part 4 run ({picked['config']}).",
            "",
        ]
    lines += [
        f"Question {row['question_id']}, run {row['trial']}, configuration {picked['config']}. Run ID `{row['run_id']}`.",
        "",
    ]
    for s in result["steps"]:
        lines += [
            f"## {s['step'].capitalize()} ({s['ms']} ms)",
            "",
            "```json",
            json.dumps(s["detail"], indent=1, default=str)[:6000],
            "```",
            "",
        ]
    total = round(sum(s["ms"] for s in result["steps"]), 1)
    lines += [f"The whole trace took {total} ms of plain code, with no model in the loop.", ""]
    return "\n".join(lines)


# --- predictions, summary ---------------------------------------------------------------------


def evaluate(
    blocks: dict[str, dict[str, Any]],
    rows: dict[str, list[dict[str, Any]]],
    log_check: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Test each prediction in results/part4/predictions.md by its stated rule."""
    out: list[dict[str, Any]] = []

    def add(number: str, held: bool | None, numbers: str) -> None:
        out.append({"prediction": number, "held": held, "numbers": numbers})

    av, ho = rows.get(AVAILABLE, []), rows.get(ROUTED_HOLDOUT, [])
    if av:
        b = bins(av)
        add(
            "P1",
            b[scoring.RIGHT] >= 69 and b[scoring.WRONG] <= 1,
            f"right {b[scoring.RIGHT]} of {len(av)}, confidently wrong {b[scoring.WRONG]} (Part 3: 72 and 0)",
        )
    if ho:
        b = bins(ho)
        h11 = bins([r for r in ho if r["question_id"] == "H11"])
        add(
            "P2",
            b[scoring.RIGHT] >= 28 and b[scoring.WRONG] <= 3 and h11[scoring.RIGHT] == 0,
            f"right {b[scoring.RIGHT]} of {len(ho)}, confidently wrong {b[scoring.WRONG]}, H11 right {h11[scoring.RIGHT]} (Part 3: 31, 2, 0)",
        )
    for number, name in (("P3", AVAILABLE), ("P4", ROUTED_HOLDOUT)):
        if name in blocks:
            n = blocks[name]["traceability"]["needs_definition"]
            share_ = n["share_traceable_of_answered"]
            add(
                number,
                share_ is not None and share_ >= 80.0,
                f"traceable {n['traceable']} of {n['answered_runs']} answered ({share_}%)",
            )
    if blocks:
        cw = sum(
            b["traceability"]["needs_definition"]["citing_without_using"] for b in blocks.values()
        )
        uw = sum(
            b["traceability"]["needs_definition"]["using_without_citing"] for b in blocks.values()
        )
        add(
            "P5",
            cw > uw,
            f"citing without using {cw}; using without citing {uw} (answered, non-lookup, both configurations)",
        )
    if AVAILABLE in blocks:
        lk = blocks[AVAILABLE]["traceability"]["lookups"]
        add(
            "P6",
            lk["cite_nothing"] >= 12,
            f"{lk['cite_nothing']} of {lk['runs']} lookup runs cite nothing; {lk['cite_something']} cite something; {lk['no_sources_line']} have no SOURCES line",
        )
    if blocks:
        resp = sum(b["versions"]["contract_responses"] for b in blocks.values())
        ok = sum(b["versions"]["with_version_and_response_id"] for b in blocks.values())
        seen = Counter()
        for b in blocks.values():
            seen.update(b["versions"]["versions_seen"])
        missing_field = sum(
            int(r.get("contract_responses_without_definitions_field") or 0)
            for rs in rows.values()
            for r in rs
        )
        unm = sum(b["unmapped"]["count"] for b in blocks.values())
        add(
            "P7",
            ok == resp and set(seen) == {CONTRACT_VERSION} and missing_field == 0 and unm == 0,
            f"{ok} of {resp} responses stamped; versions {dict(seen)}; responses without a definitions field {missing_field}; names not in the registry {unm}",
        )
    if log_check is not None and blocks:
        total_runs = sum(len(rs) for rs in rows.values())
        agree = sum(b["traceability"]["record_and_log_agree_on_served"] for b in blocks.values())
        held = (
            log_check["agreeing_calls"]
            == log_check["agent_calls"] - log_check["calls_refused_before_the_contract_ran"]
            and log_check["server_lines_missing_from_agent_record"] == 0
            and agree == total_runs
        )
        add(
            "P8",
            held,
            f"{log_check['agreeing_calls']} of {log_check['agent_calls']} calls agree ({log_check['calls_refused_before_the_contract_ran']} refused before the contract ran); {log_check['server_lines_missing_from_agent_record']} server lines not in an agent record; served sets agree in {agree} of {total_runs} runs",
        )
    if ho:
        h10 = [r for r in ho if r["question_id"] == "H10"]
        wrong = [r for r in h10 if r["outcome"] == scoring.WRONG]
        cites = [
            r for r in wrong if any(c.startswith("on_time@1") for c in r.get("sources_cited") or [])
        ]
        add(
            "P9",
            len(wrong) >= 1 and len(cites) == len(wrong),
            f"H10 confidently wrong in {len(wrong)} of {len(h10)}; {len(cites)} of those cite on_time@1; answers {[r['extracted'] for r in h10]}",
        )
    if av:
        cost = sum(float(r["cost_usd"]) for r in av) / len(av)
        add(
            "P10",
            cost <= 0.0434,
            f"cost per question ${cost:.4f} (Part 3 available $0.0362; the line is $0.0434)",
        )
    return out


def build_summary(out: Path, runs: int, wanted: set[str] | None) -> dict[str, Any]:
    """Write summary.json, summary.md and audit.md from the saved runs and server log."""
    rows = {name: run_part3.rows_in(out / "runs" / f"{name}.jsonl") for name in CONFIGS}
    rows = {k: v for k, v in rows.items() if v}
    log = log_by_run(out)
    log_lines = run_part3.read_jsonl(out / "server_log.jsonl")
    blocks: dict[str, dict[str, Any]] = {}
    for name, rs in rows.items():
        block = run_part3.block_for(name, rs, runs, wanted)
        block["contract_version"] = CONTRACT_VERSION
        block["traceability"] = traceability_block(rs, log) if log_lines else None
        block["unmapped"] = unmapped(rs)
        block["accuracy_against_part3"] = accuracy_against_part3(name, rs)
        blocks[name] = block
    every = [r for rs in rows.values() for r in rs]
    log_check = run_part3.compare_log(every, log_lines) if log_lines else None
    preds = (
        evaluate({k: v for k, v in blocks.items() if v["traceability"]}, rows, log_check)
        if log_lines
        else []
    )
    picked = pick_audit(rows) if rows else None
    audit_result = None
    if picked:
        if picked["from"] == "part4":
            lines = log.get(picked["row"]["run_id"], [])
        else:
            lines = [
                cleaned(line)
                for line in run_part3.read_jsonl(PART3 / "server_log.jsonl")
                if line.get("run_id") == picked["row"]["run_id"]
            ]
        audit_result = audit(picked["row"], lines, picked["from"])
        (out / "audit.md").write_text(clean(render_audit(picked, audit_result)))
    summary = {
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": BASE.model,
        "contract_version": CONTRACT_VERSION,
        "configs": blocks,
        "server_log_check": log_check,
        "predictions": preds,
        "audit": {
            "from": picked["from"],
            "config": picked["config"],
            "question_id": picked["row"]["question_id"],
            "trial": picked["row"]["trial"],
            "run_id": picked["row"]["run_id"],
            "status": audit_result["check"]["status"],
        }
        if picked and audit_result
        else None,
        "spend": spend(out if out != RESULTS else RESULTS),
    }
    (out / "summary.json").write_text(clean(json.dumps(summary, indent=1, default=str)) + "\n")
    (out / "summary.md").write_text(clean(render(summary)))
    return summary


def _bins_line(b: dict[str, int], n: int) -> str:
    return " / ".join(f"{b[k]}" for k in scoring.BINS) + f" of {n}"


def render(s: dict[str, Any]) -> str:
    """Render the summary as Markdown."""
    lines_out = [
        "# Part 4 results",
        "",
        "Written by `run_part4.py`. Tessaway Freight is a fictional company, the data is synthetic, and every definition owner is a fictional role.",
        "",
        f"Contract {s['contract_version']}: every response lists the definitions it served, each with id, version and owner from `data/definition_registry.json`. The agent is Part 3's (Google ADK, `{s['model']}`), told one more thing: put a `SOURCES:` line naming the definitions its answer relies on before the `ANSWER:` line (`tessaway/agents/provenance_prompt.py`). Traceability is decided in code (`tessaway/traceability.py`) against the server's own call log.",
        "",
        "Three runs per question: one run is 1.4 points of a 72-run share and 2.8 points of a 36-run share. Small differences are not findings.",
        "",
        "## 1. Bins, beside Part 3's run of the same configuration",
        "",
        "Right / confidently wrong / declined / no answer.",
        "",
        "| Configuration | Questions | Part 4 (citations) | Part 3 (no citations) | Change in runs |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, b in s["configs"].items():
        a = b["accuracy_against_part3"]
        ch = ", ".join(f"{k} {v:+d}" for k, v in a["change_in_runs"].items())
        lines_out.append(
            f"| {name} | {b['question_set']} ({b['question_count']}) | {_bins_line(a['part4'], a['part4_runs'])} | {_bins_line(a['part3'], a['part3_runs'])} | {ch} |"
        )
    lines_out += [
        "",
        "## 2. How many answers could be traced",
        "",
        "Of runs on questions that need a definition (every group but lookup) that ended in an answer value. Traceable: the answer names an id and version, the registry holds it with an owner, and the server log shows it served in that run.",
        "",
        "| Configuration | Answered | Traceable | Share | Citing without using | Using without citing |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, b in s["configs"].items():
        t = b["traceability"]
        if not t:
            continue
        n = t["needs_definition"]
        lines_out.append(
            f"| {name} | {n['answered_runs']} | {n['traceable']} | {n['share_traceable_of_answered']}% | {n['citing_without_using']} ({n['share_citing_without_using']}%) | {n['using_without_citing']} ({n['share_using_without_citing']}%) |"
        )
    lines_out += [
        "",
        "### How the rest failed",
        "",
        "| Configuration | Miss | Runs |",
        "| --- | --- | --- |",
    ]
    for name, b in s["configs"].items():
        t = b["traceability"]
        if t:
            for k, v in sorted(
                t["needs_definition"]["misses_answered"].items(), key=lambda kv: -kv[1]
            ):
                lines_out.append(f"| {name} | {k} | {v} |")
    lines_out += [
        "",
        "### By question group",
        "",
        "| Configuration | Group | Answered | Traceable | Share |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, b in s["configs"].items():
        t = b["traceability"]
        if t:
            for g, v in t["needs_definition"]["by_group"].items():
                lines_out.append(
                    f"| {name} | {g} | {v['answered']} | {v['traceable']} | {v['share']}% |"
                )
    lines_out += [
        "",
        "### By question",
        "",
        "| Configuration | Question | Answered | Traceable | Statuses | Cited |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, b in s["configs"].items():
        t = b["traceability"]
        if t:
            for q, v in t["needs_definition"]["by_question"].items():
                lines_out.append(
                    f"| {name} | {q} | {v['answered']} | {v['traceable']} | {', '.join(v['statuses'])} | {', '.join(v['cited']) or '-'} |"
                )
    lines_out += ["", "### The lookups (no definition needed)", ""]
    for name, b in s["configs"].items():
        t = b["traceability"]
        if t and t["lookups"]["runs"]:
            lk = t["lookups"]
            lines_out.append(
                f"- {name}: {lk['runs']} runs; {lk['cite_nothing']} cite nothing, {lk['cite_something']} cite something ({lk['cite_something_served']} of those served), {lk['no_sources_line']} have no SOURCES line; the server served a definition in {lk['served_something']}."
            )
    lines_out += ["", "## 3. The contract and the server's record", ""]
    for name, b in s["configs"].items():
        v = b["versions"]
        lines_out.append(
            f"- {name}: {v['with_version_and_response_id']} of {v['contract_responses']} contract responses carried a version and a response ID; versions seen {v['versions_seen']}; names a response returned that the registry does not map: {b['unmapped']['count']}."
        )
    lc = s.get("server_log_check")
    if lc:
        lines_out.append(
            f"- Server log against the agents' records: {lc['agreeing_calls']} of {lc['agent_calls']} recorded calls agree; {lc['calls_refused_before_the_contract_ran']} refused by the MCP layer before the contract ran; {lc['server_lines_missing_from_agent_record']} log lines not in an agent's record; {lc['runs_agreeing']} of {lc['runs']} runs agree in full."
        )
    lines_out += ["", "## 4. The audit", ""]
    a = s.get("audit")
    if a:
        lines_out.append(
            f"From {'Part 3 (no Part 4 run was confidently wrong)' if a['from'] == 'part3' else 'Part 4'}: {a['config']} {a['question_id']} run {a['trial']}; the three checks say `{a['status']}`. The full trail is in `audit.md`."
        )
    lines_out += [
        "",
        "## 5. Tokens, time and cost per question",
        "",
        "| Configuration | Input tokens | Output tokens | Model calls | SQL queries | Seconds | Cost |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, b in s["configs"].items():
        e = b["effort"]
        lines_out.append(
            f"| {name} | {e['mean_input_tokens']:,} | {e['mean_output_tokens']:,} | {e['mean_model_calls']} | {e['mean_sql_queries']} | {e['mean_seconds']} | ${e['mean_cost_usd']:.4f} |"
        )
    lines_out += [
        "",
        "## 6. Limits and failures",
        "",
        "| Configuration | Refused a further SQL query | Refused a further contract call | Hit the ceiling | Timed out | Ended in an error |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, b in s["configs"].items():
        li = b["limits"]
        lines_out.append(
            f"| {name} | {li['runs_refused_a_further_sql_query']} | {li['runs_refused_a_further_contract_call']} | {li['runs_that_hit_the_model_call_ceiling']} | {li['runs_that_timed_out']} | {li['runs_that_ended_in_an_error']} |"
        )
    if s["predictions"]:
        lines_out += [
            "",
            "## Predictions",
            "",
            "As written in `predictions.md` before the first scored run, each tested by its own rule.",
            "",
            "| # | Held | Numbers |",
            "| --- | --- | --- |",
        ]
        for p in s["predictions"]:
            lines_out.append(
                f"| {p['prediction']} | {'yes' if p['held'] else 'NO'} | {p['numbers']} |"
            )
    sp = s["spend"]
    lines_out += [
        "",
        "## Spend",
        "",
        f"- Gemini (model) ${sp['gemini_model_usd']:.2f} and BigQuery ${sp['bigquery_usd']:.4f}: ${sp['gemini_total_usd']:.2f} for Part 4, smoke tests included.",
        "",
        "Model names and prices as checked for the series in `tessaway/config.py`. Costs are estimates.",
        "",
    ]
    return "\n".join(lines_out)


async def main(args: argparse.Namespace) -> None:
    """Run, read the log, or audit, then write the summary."""
    out = RESULTS / args.out if args.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    wanted = {q.strip() for q in args.questions.split(",") if q.strip()} or None
    if args.audit:
        for name in CONFIGS:
            for r in run_part3.rows_in(out / "runs" / f"{name}.jsonl"):
                if r["run_id"] == args.audit:
                    result = audit(r, log_by_run(out).get(r["run_id"], []), "part4")
                    print(render_audit({"from": "part4", "config": name, "row": r}, result))
                    return
        raise SystemExit("no saved Part 4 run has that run ID")
    if args.read_server_log:
        print(f"{save_server_log(args.since, out)} server log lines saved")
    elif not args.summarize_only:
        for name in args.configs or list(CONFIGS):
            await run_config(
                name,
                runs=args.runs,
                wanted=wanted,
                concurrency=args.concurrency,
                budget_usd=args.budget_usd,
                out=out,
                retry_failed=args.retry_failed,
            )
    summary = build_summary(out, args.runs, wanted)
    if not args.out:
        write_ledger(args.cloud_run_usd)
    for p in summary["predictions"]:
        print(p["prediction"], "held" if p["held"] else "NOT HELD", p["numbers"])


def parse_args() -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description="Run the Part 4 experiment.")
    parser.add_argument("configs", nargs="*", help=f"Any of: {', '.join(CONFIGS)}")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--questions", default="")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--out", default="")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--read-server-log", action="store_true")
    parser.add_argument("--since", default="2026-10-13T00:00:00Z")
    parser.add_argument("--audit", default="")
    parser.add_argument("--cloud-run-usd", type=float, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
