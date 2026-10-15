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

"""The knowledge graph, checked without any cloud call.

The graph is built here from the data generator. The agent run builds the same
graph from BigQuery; ``tests/test_cloud.py`` checks that the two agree.
"""

import pyoxigraph as ox
import pytest
import rdflib
from rdflib.namespace import OWL, RDF

from tessaway.layers import graph, ontology
from tessaway.warehouse import generate


@pytest.fixture(scope="module")
def rows() -> graph.Rows:
    return graph.rows_from_generator()


@pytest.fixture(scope="module")
def store(rows: graph.Rows) -> ox.Store:
    return graph.build_store(rows)


def number(store: ox.Store, sparql: str) -> int:
    return int(graph.run_sparql(sparql, store)["rows"][0][0])


# --- the counts data/TRAPS.md states ---------------------------------------------


def test_the_graph_has_the_accounts_traps_md_counts(store: ox.Store) -> None:
    counts = graph.counts(store)
    assert counts["Customer"] == 39
    assert counts["ShipperSite"] == 71
    assert counts["BillToParty"] == 32


def test_the_graph_has_the_576_re_tender_links(store: ox.Store) -> None:
    assert graph.counts(store)["replaces"] == 576
    assert number(store, "SELECT (COUNT(DISTINCT ?b) AS ?n) WHERE { ?a tw:replaces ?b }") == 576


def test_every_load_row_is_a_tender_and_test_and_voided_rows_are_flagged(store: ox.Store) -> None:
    counts = graph.counts(store)
    assert counts["Tender"] == len(generate.generate()["tms_load_hdr"])
    assert counts["TestRow"] == 139
    assert counts["VoidedRow"] == 237


def test_a_load_is_counted_once_and_test_and_voided_rows_are_not_loads(
    rows: graph.Rows, store: ox.Store
) -> None:
    real_first_tenders = [
        row
        for row in rows["tms_load_hdr"]
        if not row["orig_load_id"] and not row["test_flg"] and not row["void_flg"]
    ]
    assert graph.counts(store)["Load"] == len(real_first_tenders)
    assert number(
        store,
        "SELECT (COUNT(?l) AS ?n) WHERE { ?l a tw:Load ; tw:firstTender ?t ."
        " { ?t a tw:TestRow } UNION { ?t a tw:VoidedRow } UNION { ?t tw:replaces ?x } }",
    ) == 0  # fmt: skip


def test_every_site_rolls_up_to_one_customer_and_no_bill_to_party_does(store: ox.Store) -> None:
    assert number(store, "SELECT (COUNT(*) AS ?n) WHERE { ?s tw:rollsUpTo ?c }") == 71
    assert number(
        store, "SELECT (COUNT(*) AS ?n) WHERE { ?s a tw:BillToParty ; tw:rollsUpTo ?c }"
    ) == 0  # fmt: skip


def test_a_customer_is_reached_from_sites_that_do_not_carry_its_name(store: ox.Store) -> None:
    # data/DEFINITIONS.md names this example: one parent, sites under three names.
    reply = graph.run_sparql(
        "SELECT ?name WHERE { ?c a tw:Customer ; rdfs:label 'Northgate Foods Group' ."
        " ?s tw:rollsUpTo ?c ; rdfs:label ?name } ORDER BY ?name",
        store,
    )
    names = [row[0] for row in reply["rows"]]
    assert len(names) == 6
    assert any(name.startswith("Harlow Dairy Co.") for name in names)
    assert any(name.startswith("Sunmeadow Bakeries") for name in names)


def test_the_graph_uses_the_warehouse_ids(rows: graph.Rows, store: ox.Store) -> None:
    reply = graph.run_sparql(
        "SELECT ?id WHERE { ?t a tw:Tender ; tw:tenderId ?id } ORDER BY ?id LIMIT 1", store
    )
    assert reply["rows"][0][0] == min(row["load_id"] for row in rows["tms_load_hdr"])


# --- one vocabulary for the ontology and the graph -------------------------------


def test_every_class_and_edge_in_the_graph_is_declared_in_the_ontology(rows: graph.Rows) -> None:
    declared = ontology.ontology_graph()
    used_classes, used_properties = set(), set()
    for _, predicate, value in graph.triples(rows):
        if predicate == f"<{graph.RDF_TYPE}>":
            used_classes.add(value.strip("<>"))
        elif predicate.startswith(f"<{graph.TW}"):
            used_properties.add(predicate.strip("<>"))
    for name in used_classes:
        assert (rdflib.URIRef(name), RDF.type, OWL.Class) in declared, name
    for name in used_properties:
        assert (rdflib.URIRef(name), None, None) in declared, name


# --- the tool is read-only and bounded -------------------------------------------


def test_a_query_returns_at_most_fifty_rows_and_says_when_it_cut_them(store: ox.Store) -> None:
    reply = graph.run_sparql("SELECT ?t WHERE { ?t a tw:Tender }", store)
    assert reply["row_count"] == graph.MAX_ROWS == 50
    assert reply["truncated"] is True


@pytest.mark.parametrize(
    "update",
    [
        "INSERT DATA { twd:x a tw:Customer }",
        "PREFIX tw: <https://tessaway.example/ontology#>\nDELETE WHERE { ?s a tw:Customer }",
        "CLEAR ALL",
    ],
)
def test_an_update_is_refused_and_changes_nothing(store: ox.Store, update: str) -> None:
    before = len(store)
    assert "error" in graph.run_sparql(update, store)
    assert len(store) == before


def test_a_syntax_error_is_returned_not_raised(store: ox.Store) -> None:
    assert "error" in graph.run_sparql("SELEC ?x WHERE { ?x a tw:Load }", store)


def test_ask_and_count_queries_work_with_the_declared_prefixes(store: ox.Store) -> None:
    assert graph.run_sparql("ASK { ?x a tw:Load }", store) == {"result": True}
    assert number(store, "SELECT (COUNT(?c) AS ?n) WHERE { ?c a tw:Carrier }") == 65
