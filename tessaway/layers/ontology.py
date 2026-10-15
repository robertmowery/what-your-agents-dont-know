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

"""The ontology: Tessaway's classes in OWL and its checkable rules in SHACL.

``ontology/tessaway.ttl`` says what exists (load, tender, customer, shipping
site, bill-to party, proof of delivery and so on) and carries, on each term,
its definition and the rules that say how a number is worked out.
``ontology/shapes.ttl`` holds the rules that data can be checked against.

Both files are read with rdflib, and the shapes are checked with pyshacl. The
agent reaches the ontology through ``lookup``: give it a term, get back the
definition, the rules and where the warehouse holds it.

Usage:
    python -m tessaway.layers.ontology            # list every term
    python -m tessaway.layers.ontology customer   # look one up
    python -m tessaway.layers.ontology --validate # check the knowledge graph in BigQuery
"""

from __future__ import annotations

import functools
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import rdflib
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY_PATH = ROOT / "ontology" / "tessaway.ttl"
SHAPES_PATH = ROOT / "ontology" / "shapes.ttl"

TW = rdflib.Namespace("https://tessaway.example/ontology#")

# The most entries one lookup returns.
MAX_MATCHES = 6

_KINDS = {
    OWL.Class: "class",
    OWL.ObjectProperty: "relationship",
    OWL.DatatypeProperty: "attribute",
    TW.BusinessTerm: "business term",
}
_STOP_WORDS = {"a", "an", "the", "of", "for", "to", "is", "what", "our", "we", "in", "and", "or"}


@dataclass(frozen=True)
class Entry:
    """One term of the ontology, as the agent is shown it."""

    name: str  # prefixed, for example tw:Load
    kind: str
    label: str
    also_called: tuple[str, ...] = ()
    definition: str = ""
    rules: tuple[str, ...] = ()
    rules_checked_against_data: tuple[str, ...] = ()
    kind_of: tuple[str, ...] = ()
    never_also_a: tuple[str, ...] = ()
    not_the_same_as: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    warehouse_source: tuple[str, ...] = ()
    words: frozenset[str] = field(default_factory=frozenset, compare=False)

    def as_dict(self) -> dict[str, Any]:
        """Return the entry without empty fields."""
        result: dict[str, Any] = {"term": self.name, "kind": self.kind, "label": self.label}
        for key in (
            "also_called",
            "definition",
            "rules",
            "rules_checked_against_data",
            "kind_of",
            "never_also_a",
            "not_the_same_as",
            "links",
            "warehouse_source",
        ):
            value = getattr(self, key)
            if value:
                result[key] = list(value) if isinstance(value, tuple) else value
        return result


@functools.cache
def ontology_graph() -> rdflib.Graph:
    """Return the OWL file as a graph."""
    return rdflib.Graph().parse(ONTOLOGY_PATH, format="turtle")


@functools.cache
def shapes_graph() -> rdflib.Graph:
    """Return the SHACL file as a graph."""
    return rdflib.Graph().parse(SHAPES_PATH, format="turtle")


def _name(node: Any) -> str:
    return f"tw:{str(node).removeprefix(str(TW))}"


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _words(text: str) -> list[str]:
    """Split a label, a camel-case name or a search term into comparable words."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return [_stem(word) for word in re.findall(r"[a-z0-9]+", spaced.lower())]


def _texts(graph: rdflib.Graph, node: Any, predicate: Any) -> tuple[str, ...]:
    return tuple(sorted(str(value) for value in graph.objects(node, predicate)))


@functools.cache
def entries() -> tuple[Entry, ...]:
    """Return every term in the ontology, with the shapes that target it."""
    graph, shapes = ontology_graph(), shapes_graph()
    checked: dict[Any, list[str]] = {}
    for shape in shapes.subjects(RDF.type, SH.NodeShape):
        message = str(shapes.value(shape, SH.message))
        for aimed_at in shapes.objects(shape, SH.targetClass):
            checked.setdefault(aimed_at, []).append(message)
        for aimed_at in shapes.objects(shape, SH.targetSubjectsOf):
            checked.setdefault(aimed_at, []).append(message)

    result = []
    for kind_iri, kind in _KINDS.items():
        for node in sorted(graph.subjects(RDF.type, kind_iri), key=str):
            if node == TW.BusinessTerm:
                continue
            label = str(graph.value(node, RDFS.label) or "")
            also = _texts(graph, node, SKOS.altLabel)
            links = []
            if kind == "class":
                for prop in sorted(graph.subjects(RDFS.domain, node), key=str):
                    other = graph.value(prop, RDFS.range)
                    if (prop, RDF.type, OWL.ObjectProperty) in graph and other is not None:
                        links.append(f"{_name(node)} {_name(prop)} {_name(other)}")
                for prop in sorted(graph.subjects(RDFS.range, node), key=str):
                    other = graph.value(prop, RDFS.domain)
                    if (prop, RDF.type, OWL.ObjectProperty) in graph and other is not None:
                        links.append(f"{_name(other)} {_name(prop)} {_name(node)}")
            elif kind in {"relationship", "attribute"}:
                start, end = graph.value(node, RDFS.domain), graph.value(node, RDFS.range)
                if start is not None and end is not None and kind == "relationship":
                    links.append(f"{_name(start)} {_name(node)} {_name(end)}")
            disjoint = {_name(o) for o in graph.objects(node, OWL.disjointWith)} | {
                _name(s) for s in graph.subjects(OWL.disjointWith, node)
            }
            names = [label, *also, str(node).removeprefix(str(TW))]
            result.append(
                Entry(
                    name=_name(node),
                    kind=kind,
                    label=label,
                    also_called=also,
                    definition=str(graph.value(node, SKOS.definition) or ""),
                    rules=_texts(graph, node, TW.rule),
                    rules_checked_against_data=tuple(sorted(checked.get(node, []))),
                    kind_of=tuple(sorted(_name(o) for o in graph.objects(node, RDFS.subClassOf))),
                    never_also_a=tuple(sorted(disjoint)),
                    not_the_same_as=tuple(
                        sorted(_name(o) for o in graph.objects(node, TW.notTheSameAs))
                    ),
                    links=tuple(dict.fromkeys(links)),
                    warehouse_source=_texts(graph, node, TW.warehouseSource),
                    words=frozenset(word for name in names for word in _words(name)),
                )
            )
    return tuple(result)


def index() -> list[dict[str, str]]:
    """Return every term as a name, a kind and a label: the table of contents."""
    return [{"term": e.name, "kind": e.kind, "label": e.label} for e in entries()]


def lookup(term: str) -> dict[str, Any]:
    """Look a term up in the ontology.

    Args:
        term: A word or phrase, or a name such as ``tw:Load``. Empty lists every term.

    Returns:
        ``{"term", "matches": [...]}`` with at most ``MAX_MATCHES`` entries. When
        nothing matches, or the term is empty, ``all_terms`` lists what there is.
    """
    asked = (term or "").strip()
    wanted = [word for word in _words(asked.removeprefix("tw:")) if word not in _STOP_WORDS]
    if not wanted:
        return {"term": asked, "matches": [], "all_terms": index()}
    phrase = " ".join(wanted)
    # A word that names few terms says more than a word that names many.
    weight = {
        word: 1 / max(1, sum(1 for entry in entries() if word in entry.words)) for word in wanted
    }
    scored = []
    for entry in entries():
        names = [entry.label, *entry.also_called, entry.name.removeprefix("tw:")]
        shared = sum(weight[word] for word in wanted if word in entry.words)
        if any(" ".join(_words(name)) == phrase for name in names):
            score = 3.0
        elif all(word in entry.words for word in wanted):
            score = 2.0
        elif shared > 0:
            score = 1.0
        else:
            continue
        scored.append((score, shared, entry))
    if not scored:
        return {"term": asked, "matches": [], "all_terms": index()}
    floor = 2.0 if max(score for score, _, _ in scored) >= 2 else 1.0
    ranked = sorted(scored, key=lambda item: (-item[0], -item[1]))
    matches = [entry for score, _, entry in ranked if score >= floor]
    return {"term": asked, "matches": [entry.as_dict() for entry in matches[:MAX_MATCHES]]}


def validate(data: rdflib.Graph) -> tuple[bool, set[str], str]:
    """Check a data graph against every shape.

    Returns:
        Whether the data conforms, the names of the shapes it breaks, and
        pyshacl's report text.
    """
    import pyshacl

    shapes = shapes_graph()
    conforms, report, text = pyshacl.validate(
        data, shacl_graph=shapes, ont_graph=ontology_graph(), inference="none", advanced=True
    )
    broken: set[str] = set()
    for result in report.subjects(RDF.type, SH.ValidationResult):
        source = report.value(result, SH.sourceShape)
        for candidate in shapes.subjects(RDF.type, SH.NodeShape):
            if source == candidate or _reaches(shapes, candidate, source, report):
                broken.add(_name(candidate))
    return bool(conforms), broken, str(text)


def _reaches(shapes: rdflib.Graph, node_shape: Any, source: Any, report: rdflib.Graph) -> bool:
    """Say whether a result's source shape is a part of ``node_shape``.

    A blank-node property shape is copied into the report, so it is matched on
    what it says (its path and constraints), not on its identity.
    """
    signature = _signature(report, source)
    for part in shapes.objects(node_shape, None):
        if isinstance(part, rdflib.BNode) and _signature(shapes, part) == signature:
            return True
    return False


def _signature(graph: rdflib.Graph, node: Any, depth: int = 0) -> str:
    """Describe a blank node by its contents, so copies of it compare equal."""
    if not isinstance(node, rdflib.BNode) or depth > 6:
        return str(node)
    parts = sorted(
        f"{predicate}={_signature(graph, value, depth + 1)}"
        for predicate, value in graph.predicate_objects(node)
    )
    return "[" + ";".join(parts) + "]"


def main() -> None:
    """Print a lookup, or check the knowledge graph against the shapes."""
    if sys.argv[1:] == ["--validate"]:
        from tessaway.layers import graph

        data = rdflib.Graph().parse(data=graph.ntriples(graph.rows_from_bigquery()), format="nt")
        conforms, broken, text = validate(data)
        print(f"{len(data):,d} triples; conforms: {conforms}; shapes broken: {sorted(broken)}")
        if not conforms:
            print(text[:3000])
        return
    print(json.dumps(lookup(" ".join(sys.argv[1:])), indent=1))


if __name__ == "__main__":
    main()
