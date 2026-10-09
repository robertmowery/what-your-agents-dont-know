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

"""The one thing an agent can do to the warehouse: run a read-only query.

Both agent runtimes call ``run_readonly`` through a thin tool wrapper, so the
two see the same rows, the same errors and the same limits.

Read-only is enforced by BigQuery, not by reading the SQL text: every statement
is dry-run first, and anything BigQuery does not classify as a plain SELECT is
refused before it runs.
"""

from __future__ import annotations

import datetime as dt
import decimal
import threading
from dataclasses import dataclass, field
from typing import Any

from google.api_core import exceptions as gax
from google.cloud import bigquery

from tessaway import config

# What one query may return to the model, and what it may scan. The warehouse
# is a few megabytes, so the scan cap only stops a mistake.
MAX_ROWS = 50
MAX_BYTES_BILLED = 200 * 1024 * 1024
QUERY_TIMEOUT_S = 60

_client: bigquery.Client | None = None
_client_lock = threading.Lock()


def client() -> bigquery.Client:
    """Return one shared BigQuery client bound to the configured project."""
    global _client
    with _client_lock:
        if _client is None:
            _client = bigquery.Client(project=config.project(), location=config.BQ_LOCATION)
        return _client


# How many queries one agent run may send for one question. The agent is told
# this number, and the tool refuses the next query with a message that says so.
MAX_QUERIES = 8

LIMIT_MESSAGE = (
    f"Query limit reached: all {MAX_QUERIES} queries for this question are used."
    " Give your final answer now."
)


@dataclass
class QueryLog:
    """Every query one agent run sent, kept for the results file."""

    queries: list[dict[str, Any]] = field(default_factory=list)
    bytes_billed: int = 0
    # Queries refused because the run had already used its allowance.
    refused_over_limit: int = 0


def _plain(value: Any) -> Any:
    """Turn a BigQuery cell into something JSON can carry."""
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def _job_config(*, dry_run: bool) -> bigquery.QueryJobConfig:
    job_config = bigquery.QueryJobConfig(
        default_dataset=f"{config.project()}.{config.DATASET}",
        dry_run=dry_run,
        use_query_cache=not dry_run,
        use_legacy_sql=False,
    )
    if not dry_run:
        job_config.maximum_bytes_billed = MAX_BYTES_BILLED
    return job_config


def _error_text(exc: Exception) -> str:
    """Return BigQuery's own message, without the request URL, job id or project."""
    errors = getattr(exc, "errors", None) or []
    message = (errors[0].get("message") if errors else None) or getattr(exc, "message", "")
    message = str(message or exc).split("\n\nLocation:")[0]
    return message.replace(config.project(), "PROJECT").strip()


def run_readonly(sql: str, log: QueryLog | None = None) -> dict[str, Any]:
    """Run one SELECT statement and return its rows.

    Args:
        sql: A single GoogleSQL statement. Table names need no dataset prefix.
        log: Where to record the statement and what it cost.

    Returns:
        ``{"columns", "rows", "row_count", "truncated"}`` on success, or
        ``{"error": message}``. Errors are returned, not raised, so the model
        can read them and try again.
    """
    entry: dict[str, Any] = {"sql": sql}
    if log is not None:
        if len(log.queries) >= MAX_QUERIES:
            log.refused_over_limit += 1
            return {"error": LIMIT_MESSAGE}
        log.queries.append(entry)
    try:
        check = client().query(sql, job_config=_job_config(dry_run=True))
        if check.statement_type != "SELECT":
            entry["error"] = f"refused: statement type {check.statement_type}"
            return {"error": "Only a single SELECT statement is allowed. This tool is read-only."}
        job = client().query(sql, job_config=_job_config(dry_run=False))
        iterator = job.result(timeout=QUERY_TIMEOUT_S, max_results=MAX_ROWS + 1)
        columns = [f.name for f in iterator.schema]
        rows = [[_plain(v) for v in row.values()] for row in iterator]
    except (gax.GoogleAPICallError, TimeoutError) as exc:
        message = _error_text(exc)
        entry["error"] = message[:500]
        return {"error": message[:1500]}
    billed = job.total_bytes_billed or 0
    entry.update({"row_count": len(rows[:MAX_ROWS]), "bytes_billed": billed})
    if log is not None:
        log.bytes_billed += billed
    return {
        "columns": columns,
        "rows": rows[:MAX_ROWS],
        "row_count": len(rows[:MAX_ROWS]),
        "truncated": len(rows) > MAX_ROWS,
    }


def scalar(sql: str) -> Any:
    """Run trusted SQL from this repo and return the first cell of the first row."""
    job = client().query(sql, job_config=_job_config(dry_run=False))
    rows = list(job.result(timeout=QUERY_TIMEOUT_S))
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ValueError(f"expected one row with one column, got {len(rows)} row(s)")
    return _plain(rows[0][0])
