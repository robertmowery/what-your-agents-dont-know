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

"""A small MetricFlow worker: metric requests in, generated SQL out.

This file runs in its own virtual environment (``.venv-dbt``, built from
``requirements-semantic.txt``), because dbt-bigquery and google-adk pin
versions of google-genai that cannot be installed together. The test harness
starts it as a child process and talks to it in JSON, one object per line:

    {"op": "catalog"}
        -> {"metrics": [...], "dimensions": [...]}
    {"op": "explain", "metrics": [...], "group_by": [...], "where": [...],
     "start_date": "2026-09-01", "end_date": "2026-09-30", "order_by": [...], "limit": 50}
        -> {"sql": "..."}   or   {"error": "..."}

The worker never runs a metric query. It asks MetricFlow for the SQL
(``MetricFlowEngine.explain``, the same call behind ``mf query --explain``)
and hands that SQL back; the harness runs it on BigQuery through the same
client and limits as the agent's SQL tool.

Usage:
    .venv-dbt/bin/python semantic_layer/mf_worker.py      # then write JSON lines to stdin
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent


def _engine() -> Any:
    """Load the dbt project and return a MetricFlow engine for it."""
    from dbt_metricflow.cli.cli_configuration import CLIConfiguration

    os.chdir(PROJECT_DIR)
    configuration = CLIConfiguration()
    configuration.setup(
        dbt_profiles_path=PROJECT_DIR, dbt_project_path=PROJECT_DIR, configure_file_logging=False
    )
    return configuration.mf


def _catalog(engine: Any) -> dict[str, Any]:
    """List every metric with its description and the names it can be grouped by."""
    metrics = []
    dimensions: dict[str, dict[str, str]] = {}
    for metric in sorted(engine.list_metrics(include_dimensions=True), key=lambda m: m.name):
        names = sorted({d.dunder_name for d in metric.dimensions})
        for dimension in metric.dimensions:
            dimensions.setdefault(
                dimension.dunder_name,
                {
                    "name": dimension.dunder_name,
                    "type": str(dimension.type.value).lower(),
                    "description": " ".join((dimension.description or "").split()),
                },
            )
        metrics.append(
            {
                "name": metric.name,
                "label": metric.label or "",
                "type": str(metric.type.value).lower(),
                "description": " ".join((metric.description or "").split()),
                "dimensions": names,
            }
        )
    return {"metrics": metrics, "dimensions": [dimensions[k] for k in sorted(dimensions)]}


def _day(value: str, *, end: bool) -> dt.datetime | None:
    """Read a ``YYYY-MM-DD`` bound for metric_time; an end date covers its whole day."""
    if not value:
        return None
    day = dt.date.fromisoformat(value)
    return dt.datetime.combine(day, dt.time.max if end else dt.time.min).replace(microsecond=0)


def _explain(engine: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Ask MetricFlow for the SQL that answers one metric request."""
    from metricflow.engine.metricflow_engine import MetricFlowQueryRequest

    mf_request = MetricFlowQueryRequest.create(
        metric_names=list(request.get("metrics") or []),
        group_by_names=list(request.get("group_by") or []) or None,
        where_constraints=list(request.get("where") or []) or None,
        time_constraint_start=_day(str(request.get("start_date") or ""), end=False),
        time_constraint_end=_day(str(request.get("end_date") or ""), end=True),
        order_by_names=list(request.get("order_by") or []) or None,
        limit=request.get("limit"),
    )
    result = engine.explain(mf_request)
    return {"sql": result.sql_statement.sql}


def main() -> None:
    """Serve requests until stdin closes."""
    # dbt and MetricFlow print to stdout. Keep the real stdout for replies only.
    replies = os.fdopen(os.dup(sys.stdout.fileno()), "w")
    sys.stdout = sys.stderr
    try:
        engine = _engine()
    except Exception as exc:
        replies.write(json.dumps({"ready": False, "error": f"{type(exc).__name__}: {exc}"}) + "\n")
        replies.flush()
        raise SystemExit(1) from exc
    replies.write(json.dumps({"ready": True}) + "\n")
    replies.flush()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            if request.get("op") == "catalog":
                reply = _catalog(engine)
            elif request.get("op") == "explain":
                reply = _explain(engine, request)
            else:
                reply = {"error": f"unknown op {request.get('op')!r}"}
        except Exception as exc:  # noqa: BLE001 - a bad request is returned, not raised
            reply = {"error": " ".join(f"{exc}".split())[:1500] or type(exc).__name__}
        replies.write(json.dumps(reply) + "\n")
        replies.flush()


if __name__ == "__main__":
    main()
