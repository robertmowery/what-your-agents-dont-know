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

"""The traceability check (Part 4): plain code, no model in the loop.

An answer is traceable when all three hold:

1. it names at least one definition id and version (the ``SOURCES:`` line);
2. every id and version it names exists in the registry, with an owner;
3. the server's call log shows every one of them served, at that version, in
   that run (matched by the run ID the agent sent with each call).

The third check is what separates a trace from an agent writing down an id it
never used. Each run gets one status:

    traceable          all three checks pass
    no_sources_line    the reply has no SOURCES line at all
    cites_none         the SOURCES line is empty
    cites_unregistered it names an id or version the registry does not hold
    cites_unserved     everything it names is registered, but something was not
                       served in that run
"""

from __future__ import annotations

import json
import re
from typing import Any

from tessaway import registry

TRACEABLE = "traceable"
NO_SOURCES_LINE = "no_sources_line"
CITES_NONE = "cites_none"
CITES_UNREGISTERED = "cites_unregistered"
CITES_UNSERVED = "cites_unserved"
STATUSES = (TRACEABLE, NO_SOURCES_LINE, CITES_NONE, CITES_UNREGISTERED, CITES_UNSERVED)

_SOURCES_LINE = re.compile(
    r"^[\s>*_`#-]*SOURCES[*_`]*\s*:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE
)
_PAIR = re.compile(r'"id"\s*:\s*"([^"]+)"\s*,\s*"version"\s*:\s*"?([0-9]+)"?')


def _version(value: Any) -> int | None:
    try:
        text = str(value).strip().lstrip("vV")
        return int(float(text)) if text and float(text).is_integer() else None
    except (TypeError, ValueError):
        return None


def parse_sources(reply: str) -> dict[str, Any]:
    """Read the last SOURCES line of a reply.

    Returns whether a line was found, the (id, version) pairs it names in order
    (version None when it cannot be read as a whole number), and whether the
    line could not be read as JSON (then the pairs come from a plain pattern).
    """
    found = _SOURCES_LINE.findall(reply or "")
    if not found:
        return {"line_found": False, "cited": [], "malformed": False, "raw": ""}
    raw = found[-1].strip().strip("`")
    cited: list[tuple[str, int | None]] = []
    malformed = False
    try:
        items = json.loads(raw) if raw else []
        if not isinstance(items, list):
            raise ValueError("not a list")
        for item in items:
            if isinstance(item, dict):
                cited.append((str(item.get("id", "")).strip(), _version(item.get("version"))))
            else:
                text = str(item)
                ident, _, ver = text.partition("@")
                cited.append((ident.strip(), _version(ver)))
    except (ValueError, json.JSONDecodeError):
        malformed = True
        cited = [(i.strip(), _version(v)) for i, v in _PAIR.findall(raw)]
    cited = list(dict.fromkeys(cited))
    return {"line_found": True, "cited": cited, "malformed": malformed, "raw": raw[:500]}


def served_in_log(log_lines: list[dict[str, Any]]) -> set[tuple[str, int]]:
    """Return the (id, version) pairs the server log says one run was served."""
    served: set[tuple[str, int]] = set()
    for line in log_lines:
        for item in line.get("definitions") or []:
            ident, _, ver = str(item).partition("@")
            version = _version(ver)
            if ident and version is not None:
                served.add((ident, version))
    return served


def served_in_record(tool_calls: list[dict[str, Any]]) -> set[tuple[str, int]]:
    """Return the (id, version) pairs the agent's own record says it was served."""
    served: set[tuple[str, int]] = set()
    for call in tool_calls:
        for item in call.get("definitions") or []:
            version = _version(item.get("version"))
            if item.get("id") and version is not None:
                served.add((str(item["id"]), version))
    return served


def check(
    reply: str, served: set[tuple[str, int]], data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Apply the three checks to one reply, given what the server log says it served."""
    parsed = parse_sources(reply)
    cited = parsed["cited"]
    unregistered = [f"{i}@{v}" for i, v in cited if v is None or not registry.owner_of(i, v, data)]
    registered = [(i, v) for i, v in cited if v is not None and registry.owner_of(i, v, data)]
    unserved = [f"{i}@{v}" for i, v in registered if (i, v) not in served]
    if not parsed["line_found"]:
        status = NO_SOURCES_LINE
    elif not cited:
        status = CITES_NONE
    elif unregistered:
        status = CITES_UNREGISTERED
    elif unserved:
        status = CITES_UNSERVED
    else:
        status = TRACEABLE
    return {
        "status": status,
        "traceable": status == TRACEABLE,
        "sources_line": parsed["line_found"],
        "sources_malformed": parsed["malformed"],
        "cited": [f"{i}@{v}" for i, v in cited],
        "cited_owners": {f"{i}@{v}": registry.owner_of(i, v, data) for i, v in registered},
        "unregistered": unregistered,
        # Anything named that the server did not serve in this run, registered or not.
        "cited_not_served": [f"{i}@{v}" for i, v in cited if (i, v) not in served],
        "served": sorted(f"{i}@{v}" for i, v in served),
        "served_not_cited": bool(served) and not cited,
    }
