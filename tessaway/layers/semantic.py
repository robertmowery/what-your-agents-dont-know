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

"""The semantic layer: named metrics, compiled to SQL by MetricFlow.

The metrics are defined in open YAML in ``semantic_layer/models/semantic.yml``
and built on a handful of dbt views in the same folder. This module is the
test harness's side of it:

    1. a metric request (metric names, group-by names, filters, a time range)
       goes to a MetricFlow worker process, which returns the SQL MetricFlow
       generates for it;
    2. that SQL runs on BigQuery through the same client and byte limit as the
       agent's SQL tool, and the rows come back.

MetricFlow runs in its own virtual environment (see ``semantic_layer/mf_worker.py``
for why). ``semantic_layer/catalog.json`` is the list of metrics and dimensions
MetricFlow reports for the project; it is committed so the tool description can
be built, and tested, with no worker and no cloud call.

Usage:
    python -m tessaway.layers.semantic --write-catalog   # refresh catalog.json from MetricFlow
    python -m tessaway.layers.semantic --check-gold      # every metric against the Part 1 gold SQL
    python -m tessaway.layers.semantic --write-export    # copy dbt's OSI document to exports/
    python -m tessaway.layers.semantic --redact-saved    # rewrite the saved gold check, no cloud

Files this module saves (the gold check and the OSI export) carry ``PROJECT``
in place of the Google Cloud project ID; see ``config.redact_project``.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from google.api_core import exceptions as gax
from google.cloud import bigquery

from tessaway import config
from tessaway.layers import ToolLog
from tessaway.warehouse import query

ROOT = Path(__file__).resolve().parents[2]
PROJECT_DIR = ROOT / "semantic_layer"
WORKER_PATH = PROJECT_DIR / "mf_worker.py"
WORKER_PYTHON = ROOT / ".venv-dbt" / "bin" / "python"
CATALOG_PATH = PROJECT_DIR / "catalog.json"
GOLD_CHECKS_PATH = PROJECT_DIR / "gold_checks.yaml"
GOLD_CHECK_RESULT_PATH = ROOT / "results" / "part2" / "semantic_gold_check.json"
OSI_TARGET_PATH = PROJECT_DIR / "target" / "osi_document.json"
OSI_EXPORT_PATH = PROJECT_DIR / "exports" / "osi_document.json"

MAX_ROWS = query.MAX_ROWS
GRAINS = ("day", "week", "month", "quarter", "year")


class Worker:
    """A MetricFlow worker process, spoken to in JSON lines."""

    def __init__(self) -> None:
        """Start the worker and wait until MetricFlow has loaded the project."""
        if not WORKER_PYTHON.exists():
            raise RuntimeError(
                f"{WORKER_PYTHON} not found. Create it with: python3 -m venv .venv-dbt &&"
                " .venv-dbt/bin/pip install -r requirements-semantic.txt"
            )
        config.project()  # the worker reads the project from the environment
        self._lock = threading.Lock()
        self._process = subprocess.Popen(
            [str(WORKER_PYTHON), str(WORKER_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=PROJECT_DIR,
            env={**os.environ, "DBT_SEND_ANONYMOUS_USAGE_STATS": "false", "DO_NOT_TRACK": "1"},
        )
        ready = self._read()
        if not ready.get("ready"):
            raise RuntimeError(f"MetricFlow worker failed to start: {ready.get('error')}")

    def _read(self) -> dict[str, Any]:
        assert self._process.stdout is not None
        line = self._process.stdout.readline()
        if not line:
            return {"error": "the MetricFlow worker stopped"}
        return dict(json.loads(line))

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send one request and return the reply."""
        with self._lock:
            assert self._process.stdin is not None
            self._process.stdin.write(json.dumps(payload) + "\n")
            self._process.stdin.flush()
            return self._read()

    def close(self) -> None:
        """Stop the worker."""
        if self._process.poll() is None:
            self._process.terminate()


_worker: Worker | None = None
_worker_lock = threading.Lock()


def worker() -> Worker:
    """Return one shared worker for the process."""
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = Worker()
            atexit.register(_worker.close)
        return _worker


def catalog() -> dict[str, Any]:
    """Return the committed list of metrics and dimensions."""
    return dict(json.loads(CATALOG_PATH.read_text()))


def to_metricflow_filter(text: str, dimensions: dict[str, str]) -> str:
    """Write a plain filter the way MetricFlow wants it.

    MetricFlow filters name a dimension as ``{{ Dimension('tender__carrier_name') }}``.
    An agent may write the bare name instead, and this wraps it. Text inside
    single quotes is left alone, and a filter that already uses the template
    form is returned as it is.

    Args:
        text: One filter, for example ``tender__carrier_name = 'Some Carrier'``.
        dimensions: Dimension name to its type, ``time`` or ``categorical``.
    """
    if "{{" in text:
        return text

    def wrap(match: re.Match[str]) -> str:
        name = match.group(0)
        base, _, grain = name.rpartition("__")
        if name.startswith("metric_time"):
            return (
                f"{{{{ TimeDimension('metric_time', '{grain if grain in GRAINS else 'day'}') }}}}"
            )
        if dimensions.get(name) == "time":
            return f"{{{{ TimeDimension('{name}', 'day') }}}}"
        if name in dimensions:
            return f"{{{{ Dimension('{name}') }}}}"
        if grain in GRAINS and dimensions.get(base) == "time":
            return f"{{{{ TimeDimension('{base}', '{grain}') }}}}"
        return name

    pieces = re.split(r"('(?:[^'\\]|\\.|'')*')", text)
    for position in range(0, len(pieces), 2):
        pieces[position] = re.sub(r"\b[a-z][a-z0-9_]*\b", wrap, pieces[position])
    return "".join(pieces)


def generate_sql(
    metrics: list[str],
    group_by: list[str] | None = None,
    where: list[str] | None = None,
    start_date: str = "",
    end_date: str = "",
    order_by: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Ask MetricFlow for the SQL that answers a metric request.

    Returns:
        ``{"sql": text}`` or ``{"error": message}``.
    """
    kinds = {d["name"]: d["type"] for d in catalog()["dimensions"]}
    return worker().request(
        {
            "op": "explain",
            "metrics": metrics,
            "group_by": group_by or [],
            "where": [to_metricflow_filter(item, kinds) for item in (where or [])],
            "start_date": start_date,
            "end_date": end_date,
            "order_by": order_by or [],
            "limit": limit,
        }
    )


def run_metrics(
    metrics: list[str],
    group_by: list[str] | None = None,
    where: list[str] | None = None,
    start_date: str = "",
    end_date: str = "",
    order_by: list[str] | None = None,
    limit: int | None = None,
    entry: dict[str, Any] | None = None,
    log: ToolLog | None = None,
) -> dict[str, Any]:
    """Answer a metric request: MetricFlow writes the SQL and BigQuery runs it.

    Args:
        metrics: Metric names.
        group_by: Dimension names, or ``metric_time__<grain>``.
        where: Filters on dimension names. All must hold.
        start_date: First day of the metric's own time, ``YYYY-MM-DD``.
        end_date: Last day, inclusive.
        order_by: Names to sort by; a leading ``-`` sorts descending.
        limit: Most rows to return, at most ``MAX_ROWS``.
        entry: The tool-call record to add the generated SQL and its cost to.
        log: Where to add the bytes billed.

    Returns:
        ``{"columns", "rows", "row_count", "truncated"}`` or ``{"error": message}``.
        The generated SQL is recorded, never returned to the caller.
    """
    wanted = MAX_ROWS if not limit or limit < 1 else min(int(limit), MAX_ROWS)
    try:
        reply = generate_sql(metrics, group_by, where, start_date, end_date, order_by, wanted + 1)
    except ValueError as exc:
        reply = {"error": str(exc)}
    if "sql" not in reply:
        message = str(reply.get("error", "the semantic layer could not answer"))
        message = message.replace(config.project(), "PROJECT")
        if entry is not None:
            entry["error"] = message[:500]
        return {"error": message[:1500]}
    sql = str(reply["sql"])
    if entry is not None:
        entry["generated_sql"] = sql
    job_config = bigquery.QueryJobConfig(
        use_legacy_sql=False, use_query_cache=True, maximum_bytes_billed=query.MAX_BYTES_BILLED
    )
    try:
        job = query.client().query(sql, job_config=job_config)
        iterator = job.result(timeout=query.QUERY_TIMEOUT_S, max_results=wanted + 1)
        columns = [f.name for f in iterator.schema]
        rows = [[query._plain(v) for v in row.values()] for row in iterator]
    except (gax.GoogleAPICallError, TimeoutError) as exc:
        message = query._error_text(exc)
        if entry is not None:
            entry["error"] = message[:500]
        return {"error": message[:1500]}
    billed = job.total_bytes_billed or 0
    if entry is not None:
        entry.update({"row_count": len(rows[:wanted]), "bytes_billed": billed})
    if log is not None:
        log.bytes_billed += billed
    return {
        "columns": columns,
        "rows": rows[:wanted],
        "row_count": len(rows[:wanted]),
        "truncated": len(rows) > wanted,
    }


def write_catalog() -> dict[str, Any]:
    """Ask MetricFlow what the project defines and save it as ``catalog.json``."""
    reply = worker().request({"op": "catalog"})
    if "metrics" not in reply:
        raise RuntimeError(f"MetricFlow could not list the metrics: {reply.get('error')}")
    CATALOG_PATH.write_text(json.dumps(reply, indent=1) + "\n")
    return reply


def write_export() -> dict[str, Any]:
    """Copy the OSI document ``dbt parse`` wrote into ``semantic_layer/exports``.

    dbt-core writes ``target/osi_document.json`` beside the semantic manifest
    (see ``results/part2/ossie_note.md``). Its dataset sources are fully
    qualified table names, so the project ID is replaced before it is saved.
    """
    if not OSI_TARGET_PATH.exists():
        raise SystemExit(f"{OSI_TARGET_PATH} not found. Run `dbt parse` in semantic_layer first.")
    # Replaced in the text, so the file is otherwise byte for byte what dbt wrote.
    text = str(config.redact_project(OSI_TARGET_PATH.read_text()))
    OSI_EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OSI_EXPORT_PATH.write_text(text)
    return dict(json.loads(text))


def check_against_gold() -> dict[str, Any]:
    """Run every case in ``gold_checks.yaml`` and compare it with the Part 1 gold SQL.

    A case names a metric request and either a question, whose gold SQL is the
    reference, or reference SQL of its own taken from a part of the gold SQL.
    The comparison uses the question's own tolerance, or exact equality to the
    cent for reference SQL.
    """
    from tessaway import questions, scoring

    by_id = {q.id: q for q in questions.load()}
    cases = yaml.safe_load(GOLD_CHECKS_PATH.read_text())
    results = []
    for case in cases:
        request = case["request"]
        reply = run_metrics(
            request["metrics"],
            request.get("group_by"),
            request.get("where"),
            request.get("start_date", ""),
            request.get("end_date", ""),
            request.get("order_by"),
            request.get("limit"),
        )
        sql = generate_sql(
            request["metrics"],
            request.get("group_by"),
            request.get("where"),
            request.get("start_date", ""),
            request.get("end_date", ""),
            request.get("order_by"),
            request.get("limit"),
        ).get("sql", "")
        got: Any = None
        if reply.get("rows"):
            got = reply["rows"][0][reply["columns"].index(case["answer_column"])]
        if "question" in case:
            question = by_id[case["question"]]
            expected = query.scalar(question.gold_sql)
            if question.answer_type == "text":
                matches = str(got) == str(expected)
            else:
                matches = got is not None and scoring.numbers_match(
                    float(got), float(expected), question.tolerance_kind, question.tolerance_value
                )
            reference = f"gold SQL of {question.id}"
        else:
            expected = query.scalar(case["reference_sql"])
            matches = got is not None and abs(float(got) - float(expected)) < 0.005
            reference = "reference SQL in gold_checks.yaml"
        results.append(
            {
                "metric": request["metrics"][0],
                "request": request,
                "compared_with": reference,
                "expected": expected,
                "got": got,
                "matches": bool(matches),
                "error": reply.get("error", ""),
                "generated_sql": sql,
            }
        )
    covered = {r["metric"] for r in results}
    every = {m["name"] for m in catalog()["metrics"]}
    return {
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "what": "Each metric's MetricFlow-generated SQL, run on BigQuery, beside the Part 1"
        " gold SQL run on the same warehouse.",
        "cases": len(results),
        "matching": sum(1 for r in results if r["matches"]),
        "metrics_defined": sorted(every),
        "metrics_not_checked": sorted(every - covered),
        "all_match": all(r["matches"] for r in results) and not (every - covered),
        "results": results,
    }


def main() -> None:
    """Refresh the catalog or run the gold check."""
    if sys.argv[1:] == ["--write-catalog"]:
        reply = write_catalog()
        print(f"wrote {CATALOG_PATH.relative_to(ROOT)}: {len(reply['metrics'])} metrics,"
              f" {len(reply['dimensions'])} dimensions")  # fmt: skip
    elif sys.argv[1:] == ["--write-export"]:
        export = write_export()
        print(f"wrote {OSI_EXPORT_PATH.relative_to(ROOT)}: {export['version']}")
    elif sys.argv[1:] == ["--redact-saved"]:
        report = json.loads(GOLD_CHECK_RESULT_PATH.read_text())
        GOLD_CHECK_RESULT_PATH.write_text(
            json.dumps(config.redact_project(report), indent=1) + "\n"
        )
        print(f"rewrote {GOLD_CHECK_RESULT_PATH.relative_to(ROOT)} with the project ID replaced")
    elif sys.argv[1:] == ["--check-gold"]:
        report = check_against_gold()
        GOLD_CHECK_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLD_CHECK_RESULT_PATH.write_text(
            json.dumps(config.redact_project(report), indent=1) + "\n"
        )
        for result in report["results"]:
            mark = "ok  " if result["matches"] else "FAIL"
            print(
                f"{mark} {result['metric']:30s} got {result['got']!s:>22}"
                f"  expected {result['expected']!s:>22}  ({result['compared_with']})"
            )
        print(f"{report['matching']} of {report['cases']} match;"
              f" metrics not checked: {report['metrics_not_checked']}")  # fmt: skip
        print(f"wrote {GOLD_CHECK_RESULT_PATH.relative_to(ROOT)}")
        if not report["all_match"]:
            raise SystemExit(1)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
