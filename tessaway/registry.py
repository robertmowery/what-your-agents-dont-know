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

"""The definition registry (Part 4): every definition's id, version and owner.

The registry is ``data/definition_registry.json``. Each definition keeps the id
it has in ``data/DEFINITIONS.md`` and carries a version, an owner (a fictional
role at Tessaway Freight) and the history of its versions. It also lists what
the context contract serves under it: ontology terms, metrics and rules. The
contract uses that list to stamp each response with the definitions it served;
the traceability check uses the history to say whether a cited version exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

PATH = Path(__file__).resolve().parent.parent / "data" / "definition_registry.json"
KINDS = ("terms", "metrics", "rules")


@dataclass(frozen=True)
class Definition:
    """One definition at its current version."""

    id: str
    version: int
    owner: str
    title: str

    def stamp(self) -> dict[str, Any]:
        """Return what a contract response carries for this definition."""
        return {"id": self.id, "version": self.version, "owner": self.owner}


@cache
def load(path: str = str(PATH)) -> dict[str, Any]:
    """Read the registry file."""
    return dict(json.loads(Path(path).read_text()))


def definitions(data: dict[str, Any] | None = None) -> dict[str, Definition]:
    """Return every definition at its current version, by id."""
    data = data or load()
    return {
        ident: Definition(ident, int(d["version"]), str(d.get("owner") or ""), str(d["title"]))
        for ident, d in data["definitions"].items()
    }


def index(data: dict[str, Any] | None = None) -> dict[tuple[str, str], str]:
    """Map (kind, served name) to the definition id that serves it."""
    data = data or load()
    found: dict[tuple[str, str], str] = {}
    for ident, d in data["definitions"].items():
        for kind in KINDS:
            for name in d.get("serves", {}).get(kind, []):
                found[(kind, name)] = ident
    return found


def owner_of(ident: str, version: int, data: dict[str, Any] | None = None) -> str:
    """Return the owner of a definition at a version, or "" when that version does not exist."""
    data = data or load()
    entry = data["definitions"].get(ident)
    if not entry:
        return ""
    for past in entry.get("history", []):
        if int(past["version"]) == int(version):
            return str(entry.get("owner") or "")
    return ""


def history(ident: str, data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return a definition's version history, oldest first."""
    data = data or load()
    entry = data["definitions"].get(ident) or {}
    return list(entry.get("history", []))


def served_by(kind: str, names: list[str], data: dict[str, Any] | None = None) -> list[str]:
    """Return the definition ids that serve these terms, metrics or rules, in first-seen order."""
    lookup = index(data)
    ids = [lookup[(kind, n)] for n in names if (kind, n) in lookup]
    return list(dict.fromkeys(ids))


def stamps(
    ids: list[str], data: dict[str, Any] | None = None, versions: dict[str, int] | None = None
) -> list[dict[str, Any]]:
    """Return the id, version and owner of each definition id, sorted by id.

    ``versions`` (Part 7) names the version a response served for a definition
    when it was not the current one; the version must be in the history.
    """
    current = definitions(data)
    out = []
    for i in sorted(set(ids)):
        if i not in current:
            continue
        stamp = current[i].stamp()
        wanted = (versions or {}).get(i)
        if wanted is not None and int(wanted) != stamp["version"]:
            if not owner_of(i, int(wanted), data):
                raise ValueError(f"{i} has no version {wanted} in the registry")
            stamp["version"] = int(wanted)
        out.append(stamp)
    return out
