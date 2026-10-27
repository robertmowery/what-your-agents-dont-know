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

"""One execution of the standing answer check, as a Cloud Run job (Part 5).

Runs every question of the frozen golden set once through the same agent as
Part 4's available configuration (Google ADK, the contract and the SQL tool,
the citing instruction), scores each answer with the Part 1 scorer against
the frozen answers, writes one run record and one trace per question, and
applies the alert rule to the execution.

    python -m golden_check.job --phase drift --execution 1

Environment (set on the job by ``infra/part5``):

    GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, GOOGLE_GENAI_USE_ENTERPRISE
    BQ_DATASET, BQ_LOCATION   the warehouse the SQL tool reads
    CONTRACT_URL              the context server; the MCP endpoint is this plus /mcp
    RESULTS_BUCKET            where records, traces and the alert land
    CLOUD_TRACE               "1" to send spans to Cloud Trace as well

Where results land: ``gs://RESULTS_BUCKET/part5/<phase>/e<execution>/``, with
``runs/<question>.json``, ``traces/<question>.json`` and ``alert.json``. A
question whose record is already there is skipped, so an execution that
stopped can be started again. The run record is Part 4's, unchanged; the
trace sits beside it, joined by run ID.

The job signs its calls to the context server with an ID token for its own
service account, minted by the metadata server. No key is involved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import run_part4
from context_server import contract
from tessaway import alert_rule, config, golden_set, registry, scoring, tracing
from tessaway.agents import adk_contract_agent, contract_prompt, provenance_prompt

PREFIX = "part5"
FIRST_TRY = ".first_try.json"  # a failed run's record, kept when it is run again
DEFAULT_CONCURRENCY = 4


class Store(Protocol):
    """Where an execution's files go."""

    def names(self, prefix: str) -> list[str]:
        """Object names under a prefix."""
        ...

    def put(self, name: str, text: str) -> None:
        """Write one object."""
        ...

    def get(self, name: str) -> str | None:
        """Read one object, or None."""
        ...


class GcsStore:
    """A Cloud Storage bucket."""

    def __init__(self, bucket: str) -> None:
        """Open the bucket."""
        from google.cloud import storage

        self.bucket = storage.Client(project=config.project()).bucket(bucket)

    def names(self, prefix: str) -> list[str]:
        """Object names under a prefix."""
        return [b.name for b in self.bucket.list_blobs(prefix=prefix)]

    def put(self, name: str, text: str) -> None:
        """Write one object."""
        self.bucket.blob(name).upload_from_string(text, content_type="application/json")

    def get(self, name: str) -> str | None:
        """Read one object, or None."""
        blob = self.bucket.blob(name)
        return blob.download_as_text() if blob.exists() else None


class DirStore:
    """A local folder, for tests."""

    def __init__(self, root: Path) -> None:
        """Use ``root``."""
        self.root = root

    def names(self, prefix: str) -> list[str]:
        """File names under a prefix."""
        base = self.root / prefix
        return (
            sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())
            if base.exists()
            else []
        )

    def put(self, name: str, text: str) -> None:
        """Write one file."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def get(self, name: str) -> str | None:
        """Read one file, or None."""
        path = self.root / name
        return path.read_text() if path.exists() else None


SCHEDULED = "scheduled"


def where(phase: str, execution: int, label: str = "") -> str:
    """The object prefix for one execution.

    Executions started by hand are numbered (``e1``, ``e2``...). A scheduled
    execution has no number of its own, so it is named by ``label``: its UTC
    date and the Cloud Run execution ID (see :func:`scheduled_label`). Each
    night then writes its own folder and asks all 24 questions again.
    """
    return f"{PREFIX}/{phase}/{label or f'e{execution}'}"


def scheduled_label(now: datetime | None = None, environ: dict[str, str] | None = None) -> str:
    """The folder name for one scheduled execution: ``YYYY-MM-DD`` plus Cloud Run's execution ID."""
    now = now or datetime.now(UTC)
    env = os.environ if environ is None else environ
    run_id = env.get("CLOUD_RUN_EXECUTION", "")
    return now.strftime("%Y-%m-%d") + (f"-{run_id}" if run_id else "")


def metadata_id_token(audience: str) -> tuple[str, str]:
    """An ID token for the job's own service account, and that account's email."""
    import google.auth
    import google.oauth2.id_token
    from google.auth.transport.requests import Request

    token = google.oauth2.id_token.fetch_id_token(Request(), audience)
    credentials, _ = google.auth.default()
    email = getattr(credentials, "service_account_email", "") or "job"
    if email == "default":
        import urllib.request

        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=10) as handle:
            email = handle.read().decode()
    return str(token), str(email)


def log(event: str, severity: str = "INFO", **fields: Any) -> None:
    """One structured line for Cloud Logging."""
    line = {"severity": severity, "message": event, "event": event, **fields}
    sys.stdout.write(json.dumps(line, default=str) + "\n")
    sys.stdout.flush()


Ask = Callable[..., Awaitable[adk_contract_agent.ContractAgentRun]]


async def run_execution(
    phase: str,
    execution: int,
    *,
    store: Store,
    url: str,
    wanted: set[str] | None = None,
    label: str = "",
    concurrency: int = DEFAULT_CONCURRENCY,
    budget_usd: float = 2.0,
    collector: tracing.RunCollector | None = None,
    retry_failed: bool = False,
    ask: Ask = adk_contract_agent.ask,
    token_for: Callable[[str], tuple[str, str]] = metadata_id_token,
) -> dict[str, Any]:
    """Run the golden set once, write records and traces, and return the alert verdict."""
    gs = golden_set.load()
    baseline = alert_rule.load_baseline()
    collector = collector or tracing.configure()
    tracer = tracing.tracer()
    owners = {d: e["owner"] for d, e in registry.load()["definitions"].items()}
    registry_sha = golden_set.sha256(registry.PATH)
    instruction = provenance_prompt.build_instruction(contract_prompt.AVAILABLE)
    url = url.rstrip("/")
    endpoint = url + "/mcp"
    prefix = where(phase, execution, label)
    done = {
        n.rsplit("/", 1)[1].removesuffix(".json")
        for n in store.names(f"{prefix}/runs/")
        if not n.endswith(FIRST_TRY)
    }
    asked = [q for q in gs.questions if wanted is None or q.id in wanted]
    retry: set[str] = set()
    if retry_failed:
        # Part 1's rule, as in Parts 3 and 4: a run that ended in an error or a
        # timeout is run again, once. The failed record is kept beside the new one.
        for q in asked:
            text = store.get(f"{prefix}/runs/{q.id}.json") if q.id in done else None
            saved = json.loads(text) if text else None
            if (
                saved
                and (saved.get("error") or saved.get("timed_out"))
                and not saved.get("retry_of_failed")
            ):
                store.put(f"{prefix}/runs/{q.id}{FIRST_TRY}", text or "")
                trace_text = store.get(f"{prefix}/traces/{q.id}.json")
                if trace_text:
                    store.put(f"{prefix}/traces/{q.id}{FIRST_TRY}", trace_text)
                retry.add(q.id)
    todo = [q for q in asked if q.id not in done or q.id in retry]
    log("golden_set_execution_start", phase=phase, execution=execution, questions=len(asked),
        to_run=len(todo), golden_set_version=gs.version)  # fmt: skip
    gate = asyncio.Semaphore(concurrency)
    state: dict[str, Any] = {"spent": 0.0, "stopped": False}

    async def one(question: Any) -> None:
        async with gate:
            if state["spent"] >= budget_usd:
                state["stopped"] = True
                return
            token, caller = await asyncio.to_thread(token_for, url)
            start = tracing.start_attributes(
                run_phase=phase, execution=execution, question_id=question.id,
                group=question.group, model=run_part4.BASE.model, golden_set_version=gs.version,
                contract_version=contract.CONTRACT_VERSION, registry_sha256=registry_sha,
            )  # fmt: skip
            with tracer.start_as_current_span(tracing.ROOT_SPAN, attributes=start) as span:
                run = await ask(
                    run_part4.BASE.model, question.question, contract_prompt.AVAILABLE,
                    endpoint, token, instruction,
                )  # fmt: skip
                row = run_part4.to_row(
                    phase, question, execution - 1, run, gs.answers[question.id], caller
                )
                if question.id in retry:
                    row["retry_of_failed"] = True
                span.set_attributes(tracing.end_attributes(row, owners))
                with tracer.start_as_current_span(
                    tracing.SCORE_SPAN, attributes=tracing.score_attributes(row)
                ):
                    pass
                trace_id = span.get_span_context().trace_id
            spans = collector.pop(trace_id)
            store.put(f"{prefix}/runs/{question.id}.json", json.dumps(row))
            trace_doc = {"run_id": row["run_id"], "question_id": question.id,
                         "trial": row["trial"], "spans": spans}  # fmt: skip
            store.put(f"{prefix}/traces/{question.id}.json", json.dumps(trace_doc))
            state["spent"] += float(row["cost_usd"]) + float(row["bigquery_usd"])
            log("golden_set_run", phase=phase, execution=execution, question_id=question.id,
                outcome=row["outcome"], cost_usd=row["cost_usd"], seconds=row["seconds"],
                cited=row["sources_cited"], error=str(row["error"])[:120])  # fmt: skip

    await asyncio.gather(*(one(q) for q in todo))
    rows = []
    for q in asked:
        text = store.get(f"{prefix}/runs/{q.id}.json")
        if text:
            rows.append(json.loads(text))
    verdict = alert_rule.evaluate(rows, baseline)
    verdict.update(
        {
            "phase": phase,
            "execution": execution,
            "runs": len(rows),
            "right": sum(1 for r in rows if r["outcome"] == scoring.RIGHT),
            "rule": alert_rule.RULE,
            "stopped_at_budget": state["stopped"],
            "evaluated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    store.put(f"{prefix}/alert.json", json.dumps(verdict, indent=1))
    log(
        "golden_set_alert" if verdict["fired"] else "golden_set_quiet",
        severity="WARNING" if verdict["fired"] else "INFO",
        **{
            k: verdict[k] for k in ("phase", "execution", "runs", "right", "groups_below", "missed")
        },
    )
    return verdict


def main() -> None:
    """Command line: one execution, in the Cloud Run job."""
    parser = argparse.ArgumentParser(description="One execution of the golden-set check.")
    parser.add_argument("--phase", default="scheduled")
    parser.add_argument("--execution", type=int, default=1)
    parser.add_argument("--questions", default="")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--budget-usd", type=float, default=2.0)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    project = config.project()
    wanted = {q.strip() for q in args.questions.split(",") if q.strip()} or None
    collector = tracing.configure(
        cloud_trace_project=project if os.environ.get("CLOUD_TRACE") == "1" else None
    )
    asyncio.run(
        run_execution(
            args.phase,
            args.execution,
            store=GcsStore(os.environ["RESULTS_BUCKET"]),
            url=os.environ["CONTRACT_URL"],
            wanted=wanted,
            label=scheduled_label() if args.phase == SCHEDULED else "",
            concurrency=args.concurrency,
            budget_usd=args.budget_usd,
            collector=collector,
            retry_failed=args.retry_failed,
        )
    )
    provider = tracing.trace.get_tracer_provider()
    flush = getattr(provider, "force_flush", None)
    if flush:
        flush()


if __name__ == "__main__":
    main()
