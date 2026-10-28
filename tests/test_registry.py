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

"""Part 4: the definition registry. No definition without an owner, nothing served unowned."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from rdflib.namespace import RDF, SH

from tessaway import registry
from tessaway.layers import ontology

ROOT = Path(__file__).resolve().parent.parent


def test_every_definition_has_an_owner_a_version_and_that_version_in_its_history() -> None:
    data = registry.load()
    for ident, entry in data["definitions"].items():
        assert entry.get("owner"), f"{ident} has no owner"
        assert entry["owner"] in data["owners"], f"{ident}'s owner is not a listed role"
        # Part 7: a version written but not yet released is in the history, not current.
        versions = [int(h["version"]) for h in entry["history"] if h.get("released", True)]
        assert int(entry["version"]) == max(versions), ident
        assert registry.owner_of(ident, entry["version"]) == entry["owner"]


def test_a_definition_without_an_owner_fails() -> None:
    data = json.loads(registry.PATH.read_text())
    data["definitions"]["on_time"]["owner"] = ""
    assert registry.owner_of("on_time", 1, data) == ""
    assert registry.owner_of("on_time", 2) == ""  # a version that was never written
    assert registry.owner_of("no_such_definition", 1) == ""


def test_the_ids_are_the_ones_in_definitions_md() -> None:
    text = (ROOT / "data" / "DEFINITIONS.md").read_text()
    headed = set(re.findall(r"^## `([a-z_]+)`", text, re.MULTILINE))
    assert set(registry.load()["definitions"]) == headed


def _served_names() -> dict[str, set[str]]:
    terms = {t["term"] for t in ontology.lookup("")["all_terms"]}
    shapes = ontology.shapes_graph()
    rules = {ontology._name(s) for s in shapes.subjects(RDF.type, SH.NodeShape)}
    catalog = json.loads((ROOT / "semantic_layer" / "catalog.json").read_text())
    metrics = {m["name"] for m in catalog["metrics"]}
    return {"terms": terms, "metrics": metrics, "rules": rules}


def test_everything_the_contract_can_serve_belongs_to_exactly_one_definition() -> None:
    served = _served_names()
    listed: Counter[tuple[str, str]] = Counter()
    for entry in registry.load()["definitions"].values():
        for kind in registry.KINDS:
            for name in entry["serves"][kind]:
                listed[(kind, name)] += 1
    for kind, names in served.items():
        for name in names:
            assert listed[(kind, name)] == 1, (
                f"{kind} {name} is listed {listed[(kind, name)]} times"
            )
    # And nothing in the registry names a term, metric or rule that does not exist.
    for kind, name in listed:
        assert name in served[kind], f"{kind} {name} is not served by any layer"


def test_stamps_carry_id_version_and_owner() -> None:
    stamps = registry.stamps(registry.served_by("metrics", ["late_deliveries", "on_time_rate"]))
    assert stamps == [{"id": "on_time", "version": 1, "owner": "VP Operations"}]
