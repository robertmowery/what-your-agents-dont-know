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

"""Part 7: serving two versions of a definition, and routing a canary.

Revenue version 2 (data/DEFINITIONS.md) moves revenue from the invoice date to
the delivery date. While it rolls out, the contract serves both versions. Which
one a request gets is decided here, on the server, never in an agent:

- A routing table, read from the ``TESSAWAY_ROUTING`` environment variable,
  names a default state and, optionally, a state per cohort. The caller sends
  its cohort in the ``X-Tessaway-Cohort`` header; in these runs the cohort is
  the repeat number, so ``{"default": "v1", "cohorts": {"2": "revenue_v2"}}``
  sends one repeat in three to version 2.
- A caller may also ask for a version outright with ``definition_versions``
  (for example ``{"revenue": 2}``), which wins over the routing table.

A state is a version for each definition that changed. Rolling back is a change
to the routing table, which on Cloud Run is a new revision with one environment
variable changed; no image is rebuilt and no data is touched.

The semantic layer holds the version 2 metrics under their own names
(``revenue_v2`` and so on, semantic_layer/models/semantic.yml). An agent always
asks for ``revenue``; this module turns that into the metric for the version
served and turns the column name back.
"""

from __future__ import annotations

import json
import os
from typing import Any

ROUTING_ENV = "TESSAWAY_ROUTING"
COHORT_HEADER = "x-tessaway-cohort"
CHANGED = ("revenue", "margin")

# The states a request can be served in: a version for each definition that changed.
STATES: dict[str, dict[str, int]] = {
    "v1": {"revenue": 1, "margin": 1},
    "revenue_v2": {"revenue": 2, "margin": 1},
    "v2": {"revenue": 2, "margin": 2},
}
DEFAULT_ROUTING: dict[str, Any] = {"default": "v1", "cohorts": {}}

# Metric names in the semantic layer, by (revenue version, margin version).
_METRICS: dict[tuple[int, int], dict[str, str]] = {
    (1, 1): {},
    # Revenue moved, margin did not: margin's metrics are built on revenue, so
    # they pick up version 2 revenue while carrier cost keeps the invoice date.
    (2, 1): {
        "revenue": "revenue_v2",
        "margin": "margin_r2",
        "margin_per_load": "margin_per_load_r2",
        "margin_percentage": "margin_percentage_r2",
    },
    (2, 2): {
        "revenue": "revenue_v2",
        "carrier_cost": "carrier_cost_v2",
        "invoiced_loads": "invoiced_loads_v2",
        "margin": "margin_v2",
        "margin_per_load": "margin_per_load_v2",
        "margin_percentage": "margin_percentage_v2",
    },
}
# Metrics whose version 2 lives in the financial_documents_v2 semantic model.
_DOCUMENT_PREFIX = ("document__", "document_v2__")


def routing() -> dict[str, Any]:
    """Return the routing table from the environment, checked."""
    raw = os.environ.get(ROUTING_ENV, "").strip()
    table = json.loads(raw) if raw else dict(DEFAULT_ROUTING)
    table.setdefault("cohorts", {})
    for state in [table["default"], *table["cohorts"].values()]:
        if state not in STATES:
            raise ValueError(f"routing names an unknown state {state!r}; known: {sorted(STATES)}")
    return table


def resolve(
    cohort: str | None, asked: dict[str, Any] | None = None, table: dict[str, Any] | None = None
) -> tuple[str, dict[str, int]]:
    """Return the state's name and the versions to serve one request.

    Args:
        cohort: The caller's cohort header, or None.
        asked: Versions the caller asked for outright, e.g. ``{"revenue": 2}``.
        table: The routing table; read from the environment when omitted.
    """
    table = table or routing()
    for state in [table["default"], *table.get("cohorts", {}).values()]:
        if state not in STATES:
            raise ValueError(f"routing names an unknown state {state!r}; known: {sorted(STATES)}")
    table.setdefault("cohorts", {})
    name = (
        table["cohorts"].get(str(cohort), table["default"])
        if cohort is not None
        else table["default"]
    )
    versions = dict(STATES[name])
    for ident, version in (asked or {}).items():
        if ident not in CHANGED:
            continue  # only the definitions that changed have more than one version
        if int(version) not in (1, 2):
            raise ValueError(f"{ident} has versions 1 and 2, not {version}")
        versions[ident] = int(version)
    if versions["margin"] == 2 and versions["revenue"] == 1:
        raise ValueError("margin version 2 is defined on revenue version 2; ask for both")
    if versions != STATES[name]:
        name = "requested"
    return name, versions


def metric_names(versions: dict[str, int]) -> dict[str, str]:
    """Map each asked-for metric name to the semantic layer's name for these versions."""
    return dict(_METRICS[(versions["revenue"], versions["margin"])])


def rewrite_request(
    metrics: list[str],
    group_by: list[str] | None,
    where: list[str] | None,
    versions: dict[str, int],
) -> tuple[list[str], list[str] | None, list[str] | None, dict[str, str]]:
    """Return the metric request in the semantic layer's names, and the names to put back."""
    names = metric_names(versions)
    asked = [names.get(m, m) for m in metrics]
    back = {names[m]: m for m in metrics if m in names}
    if any(m.endswith("_v2") or m.endswith("_r2") for m in asked):
        old, new = _DOCUMENT_PREFIX
        group_by = [g.replace(old, new) for g in group_by] if group_by else group_by
        where = [w.replace(old, new) for w in where] if where else where
    return asked, group_by, where, back


def rename_columns(result: dict[str, Any], back: dict[str, str]) -> dict[str, Any]:
    """Give the result's columns the names the caller asked for."""
    if back and isinstance(result, dict) and "columns" in result:
        result = dict(result)
        result["columns"] = [back.get(c, c) for c in result["columns"]]
    return result


def text_versions(path: str | None = None) -> dict[str, Any]:
    """Return the version 2 wording of each changed term, for lookup_definition."""
    from pathlib import Path

    where = (
        Path(path)
        if path
        else Path(__file__).resolve().parents[1] / "data" / "definition_versions.json"
    )
    return dict(json.loads(where.read_text()))


def reword_matches(result: dict[str, Any], versions: dict[str, int]) -> dict[str, Any]:
    """Replace a looked-up term's wording with the version served, where it differs."""
    if not isinstance(result, dict):
        return result
    wording = text_versions()["terms"]
    for match in result.get("matches") or []:
        entry = wording.get(str(match.get("term", "")))
        if not entry:
            continue
        version = versions.get(entry["definition"], 1)
        text = entry.get(str(version))
        if text:
            match.update(text)
    return result
