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

"""The ontology and its rules, checked without any cloud call.

Every SHACL shape must pass on the generated data and fail on a violation
built to break it.
"""

import json

import pytest
import rdflib
from rdflib.namespace import RDF, SH

from tessaway import questions
from tessaway.layers import graph, ontology

PREFIXES = """
@prefix tw: <https://tessaway.example/ontology#> .
@prefix twd: <https://tessaway.example/id/> .
"""

# A small world in which every rule holds: one customer with one site, one
# bill-to party, one delivered load on one tender, signed for and invoiced.
VALID = """
twd:C1 a tw:Customer .
twd:C2 a tw:Customer .
twd:S1 a tw:ShipperSite ; tw:rollsUpTo twd:C1 .
twd:B1 a tw:BillToParty .
twd:T1 a tw:Tender ; tw:status "DLVD" ; tw:isTest false ; tw:isVoid false ;
    tw:shipperSite twd:S1 ; tw:billTo twd:B1 .
twd:L1 a tw:Load, tw:DeliveredLoad ; tw:firstTender twd:T1 ; tw:finalTender twd:T1 ;
    tw:customer twd:C1 .
twd:P1 a tw:ProofOfDelivery ; tw:proofFor twd:T1 ; tw:signed true .
twd:I1 a tw:Invoice ; tw:forTender twd:T1 .
"""

# One violation per shape: triples added to the valid world that break that rule.
VIOLATIONS = {
    "tw:LoadCountedOnceShape": """
        twd:T2 a tw:Tender ; tw:status "DLVD" ; tw:isTest false ; tw:isVoid false ;
            tw:shipperSite twd:S1 ; tw:billTo twd:B1 .
        twd:L1 tw:firstTender twd:T2 .
    """,
    "tw:TestOrVoidIsNotALoadShape": """
        twd:T2 a tw:Tender, tw:TestRow ; tw:status "DLVD" ; tw:isTest true ; tw:isVoid false ;
            tw:shipperSite twd:S1 ; tw:billTo twd:B1 .
        twd:L2 a tw:Load ; tw:firstTender twd:T2 ; tw:finalTender twd:T2 ; tw:customer twd:C1 .
    """,
    "tw:LoadBookedOnFirstTenderShape": """
        twd:T2 a tw:Tender ; tw:status "RTND" ; tw:isTest false ; tw:isVoid false ;
            tw:shipperSite twd:S1 ; tw:billTo twd:B1 .
        twd:T3 a tw:Tender ; tw:status "DLVD" ; tw:isTest false ; tw:isVoid false ;
            tw:shipperSite twd:S1 ; tw:billTo twd:B1 ; tw:replaces twd:T2 .
        twd:L2 a tw:Load ; tw:firstTender twd:T3 ; tw:finalTender twd:T3 ; tw:customer twd:C1 .
    """,
    "tw:RetenderShape": """
        twd:T2 a tw:Tender ; tw:status "DLVD" ; tw:isTest false ; tw:isVoid false ;
            tw:shipperSite twd:S1 ; tw:billTo twd:B1 .
        twd:T3 a tw:Tender ; tw:status "DLVD" ; tw:isTest false ; tw:isVoid false ;
            tw:shipperSite twd:S1 ; tw:billTo twd:B1 ; tw:replaces twd:T2 .
    """,
    "tw:CustomerIsAParentShape": """
        twd:C1 tw:rollsUpTo twd:C2 .
    """,
    "tw:SiteRollsUpToOneCustomerShape": """
        twd:S2 a tw:ShipperSite .
    """,
    "tw:TenderAccountsShape": """
        twd:T2 a tw:Tender ; tw:status "BOOK" ; tw:isTest false ; tw:isVoid false ;
            tw:shipperSite twd:C1 ; tw:billTo twd:B1 .
    """,
    "tw:LoadBelongsToParentShape": """
        twd:T2 a tw:Tender ; tw:status "BOOK" ; tw:isTest false ; tw:isVoid false ;
            tw:shipperSite twd:S1 ; tw:billTo twd:B1 .
        twd:L2 a tw:Load ; tw:firstTender twd:T2 ; tw:finalTender twd:T2 ; tw:customer twd:C2 .
    """,
    "tw:InvoiceNeedsSignedProofShape": """
        twd:T2 a tw:Tender ; tw:status "DLVD" ; tw:isTest false ; tw:isVoid false ;
            tw:shipperSite twd:S1 ; tw:billTo twd:B1 .
        twd:P2 a tw:ProofOfDelivery ; tw:proofFor twd:T2 ; tw:signed false .
        twd:I2 a tw:Invoice ; tw:forTender twd:T2 .
    """,
    "tw:TestLoadsAreNeverBilledShape": """
        twd:T2 a tw:Tender, tw:TestRow ; tw:status "DLVD" ; tw:isTest true ; tw:isVoid false ;
            tw:shipperSite twd:S1 ; tw:billTo twd:B1 .
        twd:P2 a tw:ProofOfDelivery ; tw:proofFor twd:T2 ; tw:signed true .
        twd:I2 a tw:Invoice ; tw:forTender twd:T2 .
    """,
    "tw:DeliveredLoadShape": """
        twd:T2 a tw:Tender ; tw:status "CANC" ; tw:isTest false ; tw:isVoid false ;
            tw:shipperSite twd:S1 ; tw:billTo twd:B1 .
        twd:L2 a tw:Load, tw:DeliveredLoad ; tw:firstTender twd:T2 ; tw:finalTender twd:T2 ;
            tw:customer twd:C1 .
    """,
}


def world(extra: str = "") -> rdflib.Graph:
    return rdflib.Graph().parse(data=PREFIXES + VALID + extra, format="turtle")


def shape_names() -> set[str]:
    shapes = ontology.shapes_graph()
    return {
        f"tw:{str(shape).removeprefix(str(ontology.TW))}"
        for shape in shapes.subjects(RDF.type, SH.NodeShape)
        if isinstance(shape, rdflib.URIRef)
    }


# --- the files ---------------------------------------------------------------------


def test_the_ontology_names_the_classes_the_brief_lists() -> None:
    names = {entry.name for entry in ontology.entries() if entry.kind == "class"}
    assert {
        "tw:Load",
        "tw:Tender",
        "tw:Customer",
        "tw:ShipperSite",
        "tw:BillToParty",
        "tw:ProofOfDelivery",
    } <= names


def test_every_shape_states_its_rule_in_words() -> None:
    shapes = ontology.shapes_graph()
    for shape in shapes.subjects(RDF.type, SH.NodeShape):
        assert len(str(shapes.value(shape, SH.message) or "")) > 20, shape


def test_every_term_has_a_label_and_classes_and_terms_have_a_definition() -> None:
    for entry in ontology.entries():
        assert entry.label, entry.name
        if entry.kind in {"class", "business term"}:
            assert entry.definition, entry.name


# --- every rule passes on the generated data ---------------------------------------


@pytest.fixture(scope="module")
def generated() -> rdflib.Graph:
    return rdflib.Graph().parse(data=graph.ntriples(graph.rows_from_generator()), format="nt")


def test_every_shacl_rule_passes_on_the_generated_data(generated: rdflib.Graph) -> None:
    conforms, broken, text = ontology.validate(generated)
    assert conforms, text[:2000]
    assert broken == set()


# --- and every rule fails on a violation built to break it -------------------------


def test_the_small_valid_world_breaks_no_rule() -> None:
    conforms, broken, text = ontology.validate(world())
    assert conforms, text
    assert broken == set()


def test_every_shape_has_a_violation_case() -> None:
    assert set(VIOLATIONS) == shape_names()
    assert len(VIOLATIONS) == 11


@pytest.mark.parametrize("shape", sorted(VIOLATIONS))
def test_each_shacl_rule_fails_on_a_constructed_violation(shape: str) -> None:
    conforms, broken, _ = ontology.validate(world(VIOLATIONS[shape]))
    assert not conforms
    assert shape in broken


# --- the lookup the agent uses -----------------------------------------------------


def test_a_lookup_returns_the_definition_the_rules_and_the_warehouse_source() -> None:
    match = ontology.lookup("customer")["matches"][0]
    assert match["term"] == "tw:Customer"
    assert match["definition"] == "A customer is a parent account."
    assert any("parent of the site that shipped" in rule for rule in match["rules"])
    assert match["rules_checked_against_data"]
    assert any("PRNT" in source for source in match["warehouse_source"])


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("on time", "tw:OnTime"),
        ("on-time delivery rate", "tw:OnTime"),
        ("portal", "tw:PortalOnTime"),
        ("billable", "tw:BillableLoad"),
        ("proof of delivery", "tw:ProofOfDelivery"),
        ("tw:Load", "tw:Load"),
        ("loads", "tw:Load"),
        ("shipper site", "tw:ShipperSite"),
        ("bill-to party", "tw:BillToParty"),
        ("re-tender", "tw:Tender"),
        ("margin per load", "tw:Margin"),
        ("time zone", "tw:LocalTime"),
        ("Canadian dollars", "tw:Currency"),
    ],
)
def test_a_term_is_found_by_its_label_or_another_name(term: str, expected: str) -> None:
    assert ontology.lookup(term)["matches"][0]["term"] == expected


def test_an_empty_or_unknown_term_lists_every_term() -> None:
    for term in ("", "zeppelin"):
        reply = ontology.lookup(term)
        assert reply["matches"] == []
        assert len(reply["all_terms"]) == len(ontology.entries())


def test_a_lookup_returns_at_most_six_entries() -> None:
    assert len(ontology.lookup("load")["matches"]) <= ontology.MAX_MATCHES == 6


# --- nothing in the ontology answers a question -------------------------------------


def test_the_ontology_names_no_particular_account_carrier_or_load() -> None:
    text = (ontology.ONTOLOGY_PATH.read_text() + ontology.SHAPES_PATH.read_text()).lower()
    for name in ("northgate", "harlow", "sunmeadow", "ledgerline", "pellam", "midvale"):
        assert name not in text


def test_every_definition_a_question_cites_can_be_looked_up() -> None:
    # The ontology states each official definition; none is left for SQL alone.
    cited = {name for question in questions.load() for name in question.definitions}
    assert cited == questions.definition_ids()
    lookups = {
        "load": "load",
        "delivered_load": "delivered load",
        "billable": "billable",
        "on_time": "on-time",
        "portal_on_time": "portal on-time",
        "customer": "customer",
        "revenue": "revenue",
        "margin": "margin",
        "currency": "currency",
        "local_time": "local time",
    }
    assert set(lookups) == cited
    for term in lookups.values():
        reply = ontology.lookup(term)
        assert reply["matches"], term
        assert len(json.dumps(reply)) > 200
