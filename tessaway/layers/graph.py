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

"""The knowledge graph: Tessaway's actual accounts, loads and tenders in Oxigraph.

The ontology (``ontology/tessaway.ttl``) says what kinds of things exist. This
module holds the particular things, as nodes and edges that use the ontology's
own identifiers:

    tw:Customer, tw:ShipperSite, tw:BillToParty    the rows of the customer master
    tw:Tender                                      every row of the load table
    tw:Load                                        one node per load, counted once
    tw:Carrier, tw:ProofOfDelivery, tw:Invoice

    site   tw:rollsUpTo    customer        tender  tw:replaces     tender
    tender tw:shipperSite  site            load    tw:firstTender  tender
    tender tw:billTo       bill-to party   load    tw:finalTender  tender
    tender tw:carrier      carrier         load    tw:customer     customer
    proof  tw:proofFor     tender          invoice tw:forTender    tender

It is built from five warehouse tables and nothing else. The agent run loads
them from BigQuery; the tests build the same graph from the data generator, so
they need no cloud access.

Usage:
    python -m tessaway.layers.graph        # load from BigQuery and print the node counts
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from typing import Any

import pyoxigraph as ox

TW = "https://tessaway.example/ontology#"
ID = "https://tessaway.example/id/"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
XSD = "http://www.w3.org/2001/XMLSchema#"

# Declared for the agent, so a query can use them without a PREFIX line.
PREFIXES = {
    "tw": TW,
    "twd": ID,
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": XSD,
}

# The warehouse columns the graph is built from.
SOURCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "mdm_cust_acct": ("acct_id", "acct_nm", "acct_typ_cd", "prnt_acct_id"),
    "tms_carr": ("carr_id", "carr_nm"),
    "tms_load_hdr": (
        "load_id",
        "orig_load_id",
        "shpr_acct_id",
        "bill_to_acct_id",
        "carr_id",
        "load_stat_cd",
        "test_flg",
        "void_flg",
    ),
    "bil_pod_doc": ("pod_doc_id", "load_id", "signed_flg"),
    "bil_cust_inv": ("inv_id", "load_id"),
}

ACCOUNT_CLASS = {"PRNT": "Customer", "SHPR": "ShipperSite", "BLTO": "BillToParty"}

MAX_ROWS = 50

Rows = dict[str, list[dict[str, Any]]]


def rows_from_generator() -> Rows:
    """Return the source rows from the data generator. No cloud call."""
    from tessaway.warehouse import generate

    tables = generate.generate()
    return {
        name: [{column: row[column] for column in columns} for row in tables[name]]
        for name, columns in SOURCE_COLUMNS.items()
    }


def rows_from_bigquery() -> Rows:
    """Return the source rows from the warehouse in BigQuery."""
    from tessaway.warehouse import query

    rows: Rows = {}
    for name, columns in SOURCE_COLUMNS.items():
        job = query.client().query(
            f"SELECT {', '.join(columns)} FROM {name}",
            job_config=query._job_config(dry_run=False),
        )
        rows[name] = [dict(row.items()) for row in job.result(timeout=query.QUERY_TIMEOUT_S)]
    return rows


def _iri(local: str) -> str:
    return f"<{ID}{local}>"


def _tw(name: str) -> str:
    return f"<{TW}{name}>"


def _text(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _flag(value: Any) -> str:
    return f'"{"true" if value else "false"}"^^<{XSD}boolean>'


def triples(rows: Rows) -> Iterator[tuple[str, str, str]]:
    """Yield the graph as N-Triples terms, built from the source rows."""
    kind = f"<{RDF_TYPE}>"
    label = f"<{RDFS_LABEL}>"

    parent_of: dict[str, str] = {}
    for account in rows["mdm_cust_acct"]:
        node = _iri(account["acct_id"])
        yield node, kind, _tw(ACCOUNT_CLASS[account["acct_typ_cd"]])
        yield node, _tw("accountId"), _text(account["acct_id"])
        yield node, label, _text(account["acct_nm"])
        # Only a shipping site rolls up to a customer. The definitions say
        # nothing about what a bill-to party's parent means, so it is left out.
        if account["acct_typ_cd"] == "SHPR":
            parent_of[account["acct_id"]] = account["prnt_acct_id"]
            yield node, _tw("rollsUpTo"), _iri(account["prnt_acct_id"])

    for carrier in rows["tms_carr"]:
        node = _iri(carrier["carr_id"])
        yield node, kind, _tw("Carrier")
        yield node, _tw("carrierId"), _text(carrier["carr_id"])
        yield node, label, _text(carrier["carr_nm"])

    retender_of: dict[str, dict[str, Any]] = {}
    for tender in rows["tms_load_hdr"]:
        node = _iri(tender["load_id"])
        yield node, kind, _tw("Tender")
        yield node, _tw("tenderId"), _text(tender["load_id"])
        yield node, _tw("status"), _text(tender["load_stat_cd"])
        yield node, _tw("isTest"), _flag(tender["test_flg"])
        yield node, _tw("isVoid"), _flag(tender["void_flg"])
        yield node, _tw("shipperSite"), _iri(tender["shpr_acct_id"])
        yield node, _tw("billTo"), _iri(tender["bill_to_acct_id"])
        yield node, _tw("carrier"), _iri(tender["carr_id"])
        if tender["test_flg"]:
            yield node, kind, _tw("TestRow")
        if tender["void_flg"]:
            yield node, kind, _tw("VoidedRow")
        if tender["orig_load_id"]:
            retender_of[tender["orig_load_id"]] = tender
            yield node, _tw("replaces"), _iri(tender["orig_load_id"])

    signed = {proof["load_id"] for proof in rows["bil_pod_doc"] if proof["signed_flg"]}
    for tender in rows["tms_load_hdr"]:
        # A load is one shipment counted once, from its first tender, and a
        # test or voided row is not a load.
        if tender["orig_load_id"] or tender["test_flg"] or tender["void_flg"]:
            continue
        final = retender_of.get(tender["load_id"], tender)
        node = _iri(f"load-{tender['load_id']}")
        yield node, kind, _tw("Load")
        yield node, _tw("loadId"), _text(tender["load_id"])
        yield node, _tw("firstTender"), _iri(tender["load_id"])
        yield node, _tw("finalTender"), _iri(final["load_id"])
        yield node, _tw("customer"), _iri(parent_of[tender["shpr_acct_id"]])
        if final["load_stat_cd"] == "DLVD":
            yield node, kind, _tw("DeliveredLoad")
            if final["load_id"] in signed:
                yield node, kind, _tw("BillableLoad")
        elif final["load_stat_cd"] == "CANC":
            yield node, kind, _tw("CanceledLoad")

    for proof in rows["bil_pod_doc"]:
        node = _iri(proof["pod_doc_id"])
        yield node, kind, _tw("ProofOfDelivery")
        yield node, _tw("proofFor"), _iri(proof["load_id"])
        yield node, _tw("signed"), _flag(proof["signed_flg"])

    for invoice in rows["bil_cust_inv"]:
        node = _iri(invoice["inv_id"])
        yield node, kind, _tw("Invoice")
        yield node, _tw("forTender"), _iri(invoice["load_id"])


def ntriples(rows: Rows) -> str:
    """Return the graph as N-Triples text."""
    return "".join(f"{s} {p} {o} .\n" for s, p, o in triples(rows))


def build_store(rows: Rows) -> ox.Store:
    """Return an in-memory Oxigraph store holding the graph."""
    store = ox.Store()
    store.load(ntriples(rows).encode(), format=ox.RdfFormat.N_TRIPLES)
    return store


_store: ox.Store | None = None
_store_lock = threading.Lock()


def store() -> ox.Store:
    """Return one shared store for the process, loaded from BigQuery on first use."""
    global _store
    with _store_lock:
        if _store is None:
            _store = build_store(rows_from_bigquery())
        return _store


def _short(iri: str) -> str:
    """Write an IRI with its prefix when it has one."""
    for prefix, base in PREFIXES.items():
        if iri.startswith(base):
            return f"{prefix}:{iri[len(base) :]}"
    return f"<{iri}>"


def _plain(term: Any) -> Any:
    """Turn an RDF term into something JSON can carry."""
    if term is None:
        return None
    if isinstance(term, ox.NamedNode):
        return _short(term.value)
    if isinstance(term, ox.Literal):
        datatype = term.datatype.value
        if datatype == f"{XSD}boolean":
            return term.value == "true"
        if datatype in {f"{XSD}integer", f"{XSD}int", f"{XSD}long"}:
            return int(term.value)
        if datatype in {f"{XSD}decimal", f"{XSD}double", f"{XSD}float"}:
            return float(term.value)
        return term.value
    return str(term)


_UPDATE = re.compile(
    r"^\s*(?:(?:PREFIX|BASE)\b[^\n]*\n\s*)*(INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|COPY|MOVE|ADD|WITH)\b",
    re.IGNORECASE,
)


def run_sparql(sparql: str, graph: ox.Store | None = None) -> dict[str, Any]:
    """Run one read-only SPARQL query and return its rows.

    Args:
        sparql: A SELECT, ASK, CONSTRUCT or DESCRIBE query. The prefixes in
            ``PREFIXES`` are already declared.
        graph: The store to query. Defaults to the shared one.

    Returns:
        ``{"columns", "rows", "row_count", "truncated"}`` for SELECT,
        ``{"result": bool}`` for ASK, or ``{"error": message}``. Errors are
        returned, not raised, so the model can read them and try again.
    """
    if _UPDATE.match(sparql or ""):
        return {"error": "Only read-only SPARQL queries are allowed. This tool cannot change data."}
    target = graph if graph is not None else store()
    try:
        result = target.query(sparql, prefixes=PREFIXES)
        if isinstance(result, ox.QueryBoolean):
            return {"result": bool(result)}
        if isinstance(result, ox.QuerySolutions):
            columns = [variable.value for variable in result.variables]
            rows = []
            for solution in result:
                rows.append([_plain(solution[name]) for name in columns])
                if len(rows) > MAX_ROWS:
                    break
        else:
            columns = ["subject", "predicate", "object"]
            rows = []
            for triple in result:
                rows.append(
                    [_plain(triple.subject), _plain(triple.predicate), _plain(triple.object)]
                )
                if len(rows) > MAX_ROWS:
                    break
    except (SyntaxError, OSError, ValueError) as exc:
        return {"error": " ".join(str(exc).split())[:1500]}
    return {
        "columns": columns,
        "rows": rows[:MAX_ROWS],
        "row_count": len(rows[:MAX_ROWS]),
        "truncated": len(rows) > MAX_ROWS,
    }


def counts(graph: ox.Store) -> dict[str, int]:
    """Count the nodes of each class and the re-tender links."""
    result: dict[str, int] = {}
    reply = run_sparql("SELECT ?c (COUNT(?s) AS ?n) WHERE { ?s a ?c } GROUP BY ?c", graph)
    for name, number in reply["rows"]:
        result[str(name).removeprefix("tw:")] = int(number)
    links = run_sparql("SELECT (COUNT(*) AS ?n) WHERE { ?a tw:replaces ?b }", graph)
    result["replaces"] = int(links["rows"][0][0])
    return result


def main() -> None:
    """Load the graph from BigQuery and print what it holds."""
    graph = store()
    print(f"{len(graph):,d} triples")
    for name, number in sorted(counts(graph).items()):
        print(f"{name:18s} {number:>8,d}")


if __name__ == "__main__":
    main()
