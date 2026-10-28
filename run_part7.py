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

"""Part 7: ship a definition change the way a code change ships.

Revenue version 2 (data/DEFINITIONS.md) goes out through the context contract
(2.1.0) in three phases, each the same 24 questions three times through Part 4's
agent (Google ADK, gemini-3.8-flash, contract and SQL, cited answers):

    canary    the server sends repeat 2 (one run in three) to revenue version 2,
              the rest stay on version 1; margin is untouched
    rollback  the routing goes back to everyone on version 1, by a new revision
    rollout   revenue version 2 and margin version 2 for everyone

The agent sends its repeat number as its cohort; the server decides the version
(context_server/versions.py). Each run is scored against the frozen answer key
for the version its phase routed it to: golden set v1 or golden set v2. A margin
answer that matches the "revenue moved, cost did not" figure is flagged mixed.

Usage:
    python run_part7.py --set-routing canary          # a new revision; records how long it took
    python run_part7.py canary [--questions M2,M3] [--out smoke]
    python run_part7.py --set-routing v1              # the rollback
    python run_part7.py rollback
    python run_part7.py --set-routing v2
    python run_part7.py rollout
    python run_part7.py --read-server-log --since 2026-10-27T00:00:00Z
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_part2
import run_part3
import run_part4
from tessaway import contract_client, golden_set, questions, scoring
from tessaway.agents import adk_contract_agent, provenance_prompt

ROOT = Path(__file__).parent
RESULTS = ROOT / "results" / "part7"
LEDGER_PATH = run_part2.LEDGER_PATH
PART7_LINE_USD = 8.70
STOP_LINE_USD = 10.0
DEFAULT_RUNS = 3
SERVICE, REGION = "tessaway-context", "us-central1"

# Routing tables (context_server/versions.py) and what each phase expects.
ROUTINGS: dict[str, dict[str, Any]] = {
    "v1": {"default": "v1", "cohorts": {}},
    "canary": {"default": "v1", "cohorts": {"2": "revenue_v2"}},
    "v2": {"default": "v2", "cohorts": {}},
}
PHASES: dict[str, str] = {"canary": "canary", "rollback": "v1", "rollout": "v2"}
GOLD_FOR_STATE = {"v1": 1, "revenue_v2": 2, "v2": 2}
MIXED_LABEL = "revenue version 2 with carrier cost still on version 1 invoice dates"


def expected_state(phase: str, trial: int) -> str:
    """The state the server should serve one run in, from its phase's routing table."""
    table = ROUTINGS[PHASES[phase]]
    return str(table["cohorts"].get(str(trial), table["default"]))


def served_versions(row: dict[str, Any]) -> dict[str, list[int]]:
    """The versions of revenue and margin the contract actually stamped in this run."""
    found: dict[str, set[int]] = {"revenue": set(), "margin": set()}
    for item in row.get("served_by_agent_record") or []:
        ident, _, version = item.partition("@")
        if ident in found and version.isdigit():
            found[ident].add(int(version))
    return {k: sorted(v) for k, v in found.items()}


def score_row(
    row: dict[str, Any], gold_v1: dict[str, Any], gold_v2: dict[str, Any]
) -> dict[str, Any]:
    """Add the Part 7 fields: the state expected, the key used, and whether it mixed versions."""
    state = row["expected_state"]
    key = GOLD_FOR_STATE[state]
    row["gold_version"] = key
    entry = (gold_v2 if key == 2 else gold_v1)[row["question_id"]]
    mixed = [d["value"] for d in entry.get("decoys", []) if d["label"] == MIXED_LABEL]
    row["matched_mixed"] = bool(mixed) and row.get("matched_decoy") == MIXED_LABEL
    row["served_versions"] = served_versions(row)
    row["cited_versions"] = sorted(
        c for c in row.get("sources_cited") or [] if c.split("@")[0] in ("revenue", "margin")
    )
    return row


def spend(root: Path = RESULTS) -> dict[str, Any]:
    """Estimated Part 7 spend across every saved run, smoke tests included."""
    return run_part3.spend(root)


def write_ledger(cloud_run_usd: float | None = None) -> dict[str, Any]:
    """Write the Part 7 line of the series ledger."""
    ledger = json.loads(LEDGER_PATH.read_text()) if LEDGER_PATH.exists() else {}
    parts = dict(ledger.get("parts", {}))
    totals = spend()
    previous = parts.get("7", {})
    parts["7"] = {
        "what": (
            "Revenue version 2 through the contract: canary, rollback check, full rollout,"
            " 24 questions x 3 each."
        ),
        "line_usd": PART7_LINE_USD,
        "stop_line_usd": STOP_LINE_USD,
        "spent_usd": totals["gemini_total_usd"],
        "model_usd": totals["gemini_model_usd"],
        "bigquery_usd": totals["bigquery_usd"],
        "by_folder": totals["gemini_by_folder"],
    }
    if cloud_run_usd is not None or "cloud_run_usd_estimate" in previous:
        parts["7"]["cloud_run_usd_estimate"] = (
            cloud_run_usd if cloud_run_usd is not None else previous["cloud_run_usd_estimate"]
        )
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
    LEDGER_PATH.write_text(json.dumps(ledger, indent=1) + "\n")
    return ledger


def _session(project: str) -> Any:
    """An HTTP session signed with your Application Default Credentials."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"], quota_project_id=project
    )
    return AuthorizedSession(creds)


def service_url(project: str) -> str:
    """The Cloud Run Admin API address of the context server."""
    return f"https://run.googleapis.com/v2/projects/{project}/locations/{REGION}/services/{SERVICE}"


def update_routing_env(project: str, value: str) -> dict[str, Any]:
    """Set TESSAWAY_ROUTING on the service and wait until the new revision takes all traffic.

    Cloud Run makes a new revision; the old one keeps serving until the new one
    has loaded its layers and passed its startup check. Uses the Cloud Run Admin
    API with your Application Default Credentials, the same login Terraform uses.
    Returns the service as Cloud Run reports it afterwards.
    """
    session = _session(project)
    url = service_url(project)
    found = session.get(url)
    found.raise_for_status()
    template = found.json()["template"]
    for container in template["containers"]:
        env = [e for e in container.get("env", []) if e["name"] != "TESSAWAY_ROUTING"]
        container["env"] = [*env, {"name": "TESSAWAY_ROUTING", "value": value}]
    template.pop("revision", None)
    reply = session.patch(url, json={"template": template}, params={"updateMask": "template"})
    reply.raise_for_status()
    operation = reply.json()["name"]
    while True:
        status = session.get(f"https://run.googleapis.com/v2/{operation}").json()
        if status.get("done"):
            if "error" in status:
                raise RuntimeError(status["error"])
            break
        time.sleep(5)
    after = session.get(url)
    after.raise_for_status()
    return dict(after.json())


def revision_times(project: str, revision: str) -> dict[str, Any]:
    """When Cloud Run created a revision and when it became ready to serve."""
    session = _session(project)
    found = session.get(f"{service_url(project)}/revisions/{revision}")
    found.raise_for_status()
    rev = found.json()
    ready = next((c for c in rev.get("conditions", []) if c.get("type") == "Ready"), {})
    env = {e["name"]: e.get("value") for c in rev["containers"] for e in c.get("env", [])}
    return {
        "revision": revision,
        "created": rev.get("createTime"),
        "ready": ready.get("lastTransitionTime"),
        "routing_env": env.get("TESSAWAY_ROUTING"),
    }


def set_routing(name: str, project: str, out: Path = RESULTS) -> dict[str, Any]:
    """Change the routing by a new Cloud Run revision, and time it until it takes all traffic."""
    table = ROUTINGS[name]
    value = json.dumps(table, separators=(",", ":"))
    started = time.perf_counter()
    at = datetime.now(UTC).isoformat(timespec="seconds")
    service = update_routing_env(project, value)
    seconds = time.perf_counter() - started
    latest = str(service.get("latestReadyRevision", "")).rsplit("/", 1)[-1]
    traffic = service.get("trafficStatuses") or []
    serving = [t for t in traffic if int(t.get("percent", 0)) == 100]
    times = revision_times(project, latest)
    if times["routing_env"] != value or not serving:
        raise RuntimeError(f"the new routing is not serving: {times}, traffic {traffic}")
    record = {
        "routing": name,
        "table": table,
        "started_at": at,
        "until_served_seconds": round(seconds, 1),
        **times,
        "steps": [
            "set TESSAWAY_ROUTING on the service (Cloud Run Admin API; a new revision)",
            "Cloud Run starts the revision, waits for its startup check, moves 100% of traffic",
        ],
    }
    out.mkdir(parents=True, exist_ok=True)
    with (out / "routing_changes.jsonl").open("a") as handle:
        handle.write(json.dumps(record) + "\n")
    print(json.dumps(record))
    return record


def record_past_change(
    name: str, project: str, revision: str, started_at: str, out: Path = RESULTS
) -> dict[str, Any]:
    """Write a routing change's record from Cloud Run's own revision times (see run_log.md)."""
    times = revision_times(project, revision)
    created = datetime.fromisoformat(times["created"].replace("Z", "+00:00"))
    ready = datetime.fromisoformat(times["ready"].replace("Z", "+00:00"))
    record = {
        "routing": name,
        "table": ROUTINGS[name],
        "started_at": started_at,
        "until_served_seconds": round((ready - created).total_seconds(), 1),
        **times,
        "steps": [
            "set TESSAWAY_ROUTING on the service (Cloud Run Admin API; a new revision)",
            "Cloud Run starts the revision, waits for its startup check, moves 100% of traffic",
        ],
        "timed_from": "Cloud Run's revision createTime to its Ready condition",
    }
    with (out / "routing_changes.jsonl").open("a") as handle:
        handle.write(json.dumps(record) + "\n")
    print(json.dumps(record))
    return record


async def run_phase(
    phase: str,
    *,
    runs: int,
    wanted: set[str] | None,
    concurrency: int,
    out: Path,
    retry_failed: bool,
) -> None:
    """Run one phase, appending each finished run to its JSONL file."""
    configuration, _ = run_part4.CONFIGS[run_part4.AVAILABLE]
    instruction = provenance_prompt.build_instruction(configuration)
    gs1, gs2 = golden_set.load(1), golden_set.load(2)
    asked = [q for q in questions.load() if wanted is None or q.id in wanted]
    path = out / "runs" / f"{phase}.jsonl"
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
    print(f"[{phase}] {len(todo)} run(s) to do, {len(done)} already saved", flush=True)
    if not todo:
        return
    where = contract_client.deployment()
    caller = where.callers[configuration]
    gate = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    state = {"spent": float(spend()["gemini_total_usd"]), "stopped": False, "finished": 0}

    async def one(question: questions.Question, trial: int) -> None:
        async with gate:
            if state["spent"] >= STOP_LINE_USD:
                state["stopped"] = True
                return
            expected = expected_state(phase, trial)
            gold = (gs2 if GOLD_FOR_STATE[expected] == 2 else gs1).answers
            token = await asyncio.to_thread(contract_client.id_token, caller, where.url)
            run = await adk_contract_agent.ask(
                run_part4.BASE.model, question.question, configuration, where.endpoint, token,
                instruction,
                cohort=str(trial),
            )  # fmt: skip
            row = run_part4.to_row(phase, question, trial, run, gold[question.id], caller)
            row["phase"], row["cohort"], row["expected_state"] = phase, str(trial), expected
            row = score_row(row, gs1.answers, gs2.answers)
            if (question.id, trial) in done:
                row["retry_of_failed"] = True
            async with lock:
                with path.open("a") as handle:
                    handle.write(json.dumps(row) + "\n")
                state["spent"] += row["cost_usd"] + row["bigquery_usd"]
                state["finished"] += 1
                cites = ",".join(row["sources_cited"]) or "-"
                mixed = " MIXED" if row["matched_mixed"] else ""
                err = " ERR " + row["error"][:80] if row["error"] else ""
                print(
                    f"[{phase}] {question.id} #{trial} {expected:<10} {row['outcome']:<17}"
                    f" {row['extracted'][:20]!r} served={row['served_versions']} cites={cites}"
                    f"{mixed} ${row['cost_usd']:.4f} total=${state['spent']:.2f}"
                    f" ({state['finished']}/{len(todo)}){err}",
                    flush=True,
                )

    await asyncio.gather(*(one(question, trial) for question, trial in todo))
    if state["stopped"]:
        print(f"[{phase}] STOPPED at the stop line of ${STOP_LINE_USD:.2f}; the phase is partial.")


async def main(args: argparse.Namespace) -> None:
    """Change routing, run a phase, or read the server log."""
    out = RESULTS / args.out if args.out else RESULTS
    if args.set_routing:
        from tessaway import config

        set_routing(args.set_routing, config.project(), out)
        return
    if args.read_server_log:
        print(f"{run_part4.save_server_log(args.since, out)} server log lines saved")
        return
    wanted = {q.strip() for q in args.questions.split(",") if q.strip()} or None
    for phase in args.phases:
        await run_phase(
            phase, runs=args.runs, wanted=wanted, concurrency=args.concurrency, out=out,
            retry_failed=args.retry_failed,
        )  # fmt: skip
    if not args.out:
        write_ledger(args.cloud_run_usd)
    print(f"Part 7 spend so far: ${spend()['gemini_total_usd']:.4f}")


def parse_args() -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description="Run the Part 7 experiment.")
    parser.add_argument("phases", nargs="*", help=f"Any of: {', '.join(PHASES)}")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--questions", default="")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", default="")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--set-routing", choices=sorted(ROUTINGS), default="")
    parser.add_argument("--read-server-log", action="store_true")
    parser.add_argument("--since", default="2026-10-27T00:00:00Z")
    parser.add_argument("--cloud-run-usd", type=float, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
