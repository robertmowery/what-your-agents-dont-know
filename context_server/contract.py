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

"""The context contract: four operations over the Part 2 layers, and nothing else.

Explicit. The contract is this fixed list of operations. Each one calls a Part 2
layer as it is:

    lookup_definition   look up a definition    -> tessaway.layers.ontology.lookup
    compute_metric      compute a named metric  -> tessaway.layers.semantic.run_metrics
    check_rule          check a rule            -> the SHACL shapes, checked by
                                                   tessaway.layers.ontology.validate
    resolve_entity      resolve an entity       -> the knowledge graph, through fixed
                                                   queries run by tessaway.layers.graph

There is no free-form query in the contract: no SQL, and no SPARQL. The caller
names a metric, a term, a rule or an entity; the server writes every query.

Versioned. ``CONTRACT_VERSION`` is stamped on every response by ``envelope``,
with a response ID, so an answer can be matched to the call it came from.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import pyoxigraph as ox
import rdflib
from rdflib.namespace import RDF, SH

from tessaway.agents import layer_prompt
from tessaway.layers import graph, ontology, semantic

CONTRACT_NAME = "tessaway-context"
# Raise the minor version when an operation is added, the major version when one
# changes what it returns or stops being offered.
CONTRACT_VERSION = "1.0.0"

LOOKUP_DEFINITION = "lookup_definition"
COMPUTE_METRIC = "compute_metric"
CHECK_RULE = "check_rule"
RESOLVE_ENTITY = "resolve_entity"
OPERATIONS = (LOOKUP_DEFINITION, COMPUTE_METRIC, CHECK_RULE, RESOLVE_ENTITY)

# What one resolve_entity call returns at most: entities, and named neighbors per edge.
MAX_ENTITIES = 10
MAX_LINKED = 20
MAX_RULE_MATCHES = 6

# Edge and value names in the knowledge graph (tessaway/layers/graph.py).
_ID_PREDICATES = ("accountId", "carrierId", "tenderId", "loadId")
_ATTRIBUTES = ("status", "isTest", "isVoid", "signed")

DESCRIPTIONS = {
    LOOKUP_DEFINITION: layer_prompt.ONTOLOGY_DESCRIPTION,
    COMPUTE_METRIC: "",  # built from the metric catalog at first use, see description()
    CHECK_RULE: (
        "Looks up Tessaway Freight's checkable business rules and says whether the company's"
        " current data keeps each one. Each rule is stated in plain words, names the kinds of"
        " things it applies to, and was checked against the knowledge graph built from the"
        " warehouse when the server started. Give a word or a phrase about the rule, for example"
        " invoice or re-tender. With an empty rule it lists every rule."
    ),
    RESOLVE_ENTITY: (
        "Finds an account, a carrier, a tender or a load in Tessaway Freight's knowledge graph"
        " by its name, part of its name, or its id, and says what it is and how it connects:"
        " for example which customer a shipping site rolls up to, a customer's shipping sites,"
        " or a load's first and final tender, its customer, and whether it was delivered,"
        " billable or canceled. Returns at most 10 entities. Names are matched without regard"
        " to case."
    ),
}


def description(operation: str) -> str:
    """Return the description a caller reads for an operation."""
    if operation == COMPUTE_METRIC:
        # The Part 2 metric tool's description, word for word.
        return layer_prompt.semantic_description()
    return DESCRIPTIONS[operation]


def envelope(operation: str, result: dict[str, Any]) -> dict[str, Any]:
    """Wrap one operation's result with the contract name, version and a new response ID."""
    return {
        "contract": CONTRACT_NAME,
        "contract_version": CONTRACT_VERSION,
        "operation": operation,
        "response_id": str(uuid.uuid4()),
        "result": result,
    }


@dataclass
class State:
    """What the server loads once at start: the graph and the rule check."""

    store: ox.Store
    rules: list[dict[str, Any]] = field(default_factory=list)


def rule_table(broken: set[str]) -> list[dict[str, Any]]:
    """List every SHACL shape as a rule, with whether the data keeps it."""
    shapes = ontology.shapes_graph()
    rules = []
    for shape in sorted(shapes.subjects(RDF.type, SH.NodeShape), key=str):
        name = ontology._name(shape)
        targets = [
            *shapes.objects(shape, SH.targetClass),
            *shapes.objects(shape, SH.targetSubjectsOf),
        ]
        rules.append(
            {
                "rule": name,
                "statement": str(shapes.value(shape, SH.message) or ""),
                "applies_to": sorted(ontology._name(t) for t in targets),
                "holds_in_current_data": name not in broken,
            }
        )
    return rules


def build_state(rows: graph.Rows) -> State:
    """Build the graph store and check every rule against it. Slow: about half a minute."""
    store = graph.build_store(rows)
    data = rdflib.Graph().parse(data=graph.ntriples(rows), format="nt")
    _, broken, _ = ontology.validate(data)
    return State(store=store, rules=rule_table(broken))


# --- the four operations -------------------------------------------------------------


def lookup_definition(term: str = "") -> dict[str, Any]:
    """Look a term up in the ontology."""
    return ontology.lookup(term)


def compute_metric(
    metrics: list[str],
    group_by: list[str] | None = None,
    where: list[str] | None = None,
    start_date: str = "",
    end_date: str = "",
    order_by: list[str] | None = None,
    limit: int = 50,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute named metrics through the semantic layer.

    ``record`` receives the generated SQL and the bytes billed, for the server
    log. Neither is returned to the caller.
    """
    entry: dict[str, Any] = {} if record is None else record
    return semantic.run_metrics(
        list(metrics or []), group_by, where, start_date, end_date, order_by, limit, entry
    )


def check_rule(state: State, rule: str = "") -> dict[str, Any]:
    """Return the rules that match the words given, or every rule."""
    asked = (rule or "").strip()
    stop = ontology._STOP_WORDS | {"rule", "rules"}
    wanted = [word for word in ontology._words(asked.removeprefix("tw:")) if word not in stop]
    every = [{"rule": r["rule"], "statement": r["statement"]} for r in state.rules]
    if not wanted:
        return {"rule": asked, "matches": [], "all_rules": every}
    scored = []
    for entry in state.rules:
        text = " ".join(
            [entry["rule"].removeprefix("tw:"), entry["statement"], *entry["applies_to"]]
        )
        words = set(ontology._words(text.replace("tw:", " ")))
        shared = sum(1 for word in wanted if word in words)
        if shared:
            scored.append((shared, entry))
    if not scored:
        return {"rule": asked, "matches": [], "all_rules": every}
    best = max(shared for shared, _ in scored)
    matches = [entry for shared, entry in sorted(scored, key=lambda s: -s[0]) if shared == best]
    return {"rule": asked, "matches": matches[:MAX_RULE_MATCHES]}


def _literal(text: str) -> str:
    """Write text as a SPARQL string literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + re.sub(r"[\r\n\t]", " ", escaped) + '"'


def _full(short: str) -> str:
    """Turn a prefixed name back into a full IRI for a query."""
    prefix, _, local = short.partition(":")
    return f"<{graph.PREFIXES[prefix]}{local}>"


def _describe(store: ox.Store, node: str) -> dict[str, Any]:
    """Say what one node is and how it connects."""
    iri = _full(node)
    reply = graph.run_sparql(f"SELECT ?p ?o WHERE {{ {iri} ?p ?o }}", store)
    entity: dict[str, Any] = {"entity": node, "types": [], "label": "", "ids": {}}
    attributes: dict[str, Any] = {}
    links: list[dict[str, Any]] = []
    for predicate, value in reply.get("rows", []):
        name = str(predicate).removeprefix("tw:")
        if predicate == "rdf:type":
            entity["types"].append(value)
        elif predicate == "rdfs:label":
            entity["label"] = value
        elif name in _ID_PREDICATES:
            entity["ids"][name] = value
        elif name in _ATTRIBUTES:
            attributes[name] = value
        elif isinstance(value, str) and value.startswith("twd:"):
            links.append({"edge": predicate, "to": value, **_name_of(store, value)})
    entity["types"].sort()
    if attributes:
        entity["attributes"] = attributes
    if links:
        entity["links"] = links
    counts = graph.run_sparql(
        f"SELECT ?p (COUNT(?s) AS ?n) WHERE {{ ?s ?p {iri} }} GROUP BY ?p ORDER BY ?p", store
    )
    linked_from = []
    for predicate, number in counts.get("rows", []):
        item: dict[str, Any] = {"edge": predicate, "count": int(number)}
        if int(number) <= MAX_LINKED:
            names = graph.run_sparql(
                f"SELECT ?s WHERE {{ ?s {_full(predicate)} {iri} }} ORDER BY ?s", store
            )
            item["from"] = [{"entity": row[0], **_name_of(store, row[0])} for row in names["rows"]]
        linked_from.append(item)
    if linked_from:
        entity["linked_from"] = linked_from
    return entity


def _name_of(store: ox.Store, node: str) -> dict[str, Any]:
    """Return a node's label or id, whichever it has, to show beside a link."""
    reply = graph.run_sparql(
        f"SELECT ?l ?i WHERE {{ OPTIONAL {{ {_full(node)} rdfs:label ?l }}"
        f" OPTIONAL {{ {_full(node)} tw:accountId|tw:carrierId|tw:tenderId|tw:loadId ?i }} }}",
        store,
    )
    rows = reply.get("rows") or [[None, None]]
    label, ident = rows[0]
    return {"label": label} if label else ({"id": ident} if ident else {})


def resolve_entity(state: State, name_or_id: str) -> dict[str, Any]:
    """Find entities by name or id and describe each one."""
    asked = " ".join((name_or_id or "").split())[:200]
    if not asked:
        return {"error": "Give a name, part of a name, or an id."}
    text = _literal(asked.lower())
    ids = "|".join(f"tw:{name}" for name in _ID_PREDICATES)
    reply = graph.run_sparql(
        "SELECT DISTINCT ?node ?exact WHERE {"
        f" {{ ?node rdfs:label ?l . FILTER(CONTAINS(LCASE(STR(?l)), {text}))"
        f"   BIND(LCASE(STR(?l)) = {text} AS ?exact) }}"
        f" UNION {{ ?node {ids} ?i . FILTER(LCASE(STR(?i)) = {text}) BIND(true AS ?exact) }}"
        f"}} ORDER BY DESC(?exact) ?node LIMIT {MAX_ENTITIES + 1}",
        state.store,
    )
    if "error" in reply:
        return {"error": reply["error"]}
    nodes = list(dict.fromkeys(row[0] for row in reply["rows"]))
    return {
        "name_or_id": asked,
        "entities": [_describe(state.store, node) for node in nodes[:MAX_ENTITIES]],
        "more_matches": len(nodes) > MAX_ENTITIES,
    }
