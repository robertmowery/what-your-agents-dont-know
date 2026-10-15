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

"""Part 3: the context contract and its server, checked with no cloud call.

The graph is built from the data generator, as in tests/test_graph.py. The
metric operation is checked with the MetricFlow call replaced, because it needs
BigQuery; ``tests/test_part3_cloud.py`` checks it, and the refused
unauthenticated call, against the deployed service.

The four contract properties, and the test that holds each:

    explicit    test_the_server_publishes_exactly_the_four_operations_and_no_query_tool
    secured     test_a_call_without_a_caller_identity_is_refused
    versioned   test_every_operation_stamps_the_version_and_a_response_id
    observable  test_every_call_writes_one_log_line_that_matches_its_response
"""

from __future__ import annotations

import base64
import functools
import json
from typing import Any

import anyio
import pytest
from mcp import Client
from starlette.testclient import TestClient

from context_server import contract, server
from tessaway.agents import layer_prompt
from tessaway.layers import graph


@functools.cache
def state() -> contract.State:
    return contract.State(
        store=graph.build_store(graph.rows_from_generator()), rules=contract.rule_table(set())
    )


def token(email: str) -> str:
    """An ID token as Cloud Run passes it on: header, claims, signature removed."""

    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part({'email': email, 'aud': 'x'})}.SIGNATURE_REMOVED"


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(server, "emit", captured.append)
    return captured


@pytest.fixture
def fake_metrics(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def run_metrics(*args: Any) -> dict[str, Any]:
        calls.append(args)
        entry = args[7]
        entry["bytes_billed"] = 1234
        return {"columns": ["revenue"], "rows": [[1234567.89]], "row_count": 1, "truncated": False}

    monkeypatch.setattr(contract.semantic, "run_metrics", run_metrics)
    return calls


async def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(server.build_server(state())) as client:
        result = await client.call_tool(name, arguments)
    text = result.content[0].text  # type: ignore[union-attr]
    return dict(json.loads(text))


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return anyio.run(_call, name, arguments)


def test_the_server_publishes_exactly_the_four_operations_and_no_query_tool() -> None:
    async def names() -> list[Any]:
        async with Client(server.build_server(state())) as client:
            listed = await client.list_tools()
        return list(listed.tools)

    tools = anyio.run(names)
    assert sorted(t.name for t in tools) == sorted(contract.OPERATIONS)
    assert len(contract.OPERATIONS) == 4
    schemas = {
        t.name: json.dumps(t.input_schema if hasattr(t, "input_schema") else t.inputSchema)
        for t in tools
    }
    # No operation takes a query: the caller names things, the server writes the queries.
    for name, schema in schemas.items():
        assert '"sql"' not in schema and '"sparql"' not in schema, name


def test_the_metric_operation_reads_the_part2_metric_description_word_for_word() -> None:
    assert contract.description(contract.COMPUTE_METRIC) == layer_prompt.semantic_description()
    assert contract.description(contract.LOOKUP_DEFINITION) == layer_prompt.ONTOLOGY_DESCRIPTION


@pytest.mark.usefixtures("fake_metrics")
@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        (contract.LOOKUP_DEFINITION, {"term": "customer"}),
        (contract.COMPUTE_METRIC, {"metrics": ["revenue"], "start_date": "2026-07-01"}),
        (contract.CHECK_RULE, {"rule": "invoice"}),
        (contract.RESOLVE_ENTITY, {"name_or_id": "Northgate"}),
        (contract.RESOLVE_ENTITY, {"name_or_id": ""}),  # an error is stamped too
    ],
)
def test_every_operation_stamps_the_version_and_a_response_id(
    operation: str, arguments: dict[str, Any], lines: list[dict[str, Any]]
) -> None:
    reply = call(operation, arguments)
    assert reply["contract"] == contract.CONTRACT_NAME
    assert reply["contract_version"] == contract.CONTRACT_VERSION
    assert reply["operation"] == operation
    assert len(reply["response_id"]) == 36
    assert isinstance(reply["result"], dict)


def test_response_ids_are_never_reused(lines: list[dict[str, Any]]) -> None:
    ids = {call(contract.CHECK_RULE, {"rule": ""})["response_id"] for _ in range(5)}
    assert len(ids) == 5


def test_lookup_definition_is_the_ontology_lookup(lines: list[dict[str, Any]]) -> None:
    reply = call(contract.LOOKUP_DEFINITION, {"term": "customer"})
    assert reply["result"]["matches"][0]["term"] == "tw:Customer"
    assert reply["result"]["matches"][0]["definition"]


def test_compute_metric_passes_the_request_to_the_semantic_layer(
    fake_metrics: list[tuple[Any, ...]], lines: list[dict[str, Any]]
) -> None:
    reply = call(
        contract.COMPUTE_METRIC,
        {
            "metrics": ["revenue"],
            "group_by": ["customer__customer_name"],
            "start_date": "2026-07-01",
            "end_date": "2026-09-30",
            "limit": 5,
        },
    )
    assert reply["result"]["rows"] == [[1234567.89]]
    metrics, group_by, _where, start, end, _order_by, limit, _ = fake_metrics[0]
    assert (metrics, group_by, start, end, limit) == (
        ["revenue"],
        ["customer__customer_name"],
        "2026-07-01",
        "2026-09-30",
        5,
    )
    assert "generated_sql" not in json.dumps(reply)
    assert lines[-1]["bytes_billed"] == 1234


def test_check_rule_lists_every_rule_and_finds_one_by_its_words(
    lines: list[dict[str, Any]],
) -> None:
    every = call(contract.CHECK_RULE, {"rule": ""})["result"]["all_rules"]
    assert len(every) == len(state().rules) >= 9
    found = call(contract.CHECK_RULE, {"rule": "invoice signed proof"})["result"]["matches"]
    assert found[0]["rule"] == "tw:InvoiceNeedsSignedProofShape"
    assert found[0]["holds_in_current_data"] is True


def test_a_broken_rule_is_reported_as_not_holding() -> None:
    rules = contract.rule_table({"tw:TestLoadsAreNeverBilledShape"})
    held = {r["rule"]: r["holds_in_current_data"] for r in rules}
    assert held["tw:TestLoadsAreNeverBilledShape"] is False
    assert sum(held.values()) == len(rules) - 1


def test_resolve_entity_finds_a_customer_and_its_sites(lines: list[dict[str, Any]]) -> None:
    result = call(contract.RESOLVE_ENTITY, {"name_or_id": "northgate foods"})["result"]
    first = result["entities"][0]
    assert first["label"].lower().startswith("northgate foods")
    assert "tw:Customer" in first["types"]
    edges = {item["edge"]: item for item in first.get("linked_from", [])}
    assert edges["tw:rollsUpTo"]["count"] >= 1


def test_resolve_entity_finds_a_load_by_id_with_its_tenders(lines: list[dict[str, Any]]) -> None:
    rows = graph.rows_from_generator()["tms_load_hdr"]
    first = next(
        r for r in rows if not r["orig_load_id"] and not r["test_flg"] and not r["void_flg"]
    )
    result = call(contract.RESOLVE_ENTITY, {"name_or_id": first["load_id"]})["result"]
    kinds = {t for entity in result["entities"] for t in entity["types"]}
    assert {"tw:Load", "tw:Tender"} <= kinds


def test_resolve_entity_cannot_be_used_to_run_a_query(lines: list[dict[str, Any]]) -> None:
    sneaky = '" } } SELECT * WHERE { ?s ?p ?o } #'
    result = call(contract.RESOLVE_ENTITY, {"name_or_id": sneaky})["result"]
    assert result.get("entities") == [] or "error" in result


def test_every_call_writes_one_log_line_that_matches_its_response(
    lines: list[dict[str, Any]],
) -> None:
    replies = [
        call(contract.CHECK_RULE, {"rule": "re-tender"}),
        call(contract.LOOKUP_DEFINITION, {"term": "load"}),
    ]
    calls = [line for line in lines if line["event"] == server.LOG_EVENT]
    assert len(calls) == 2
    for line, reply in zip(calls, replies, strict=True):
        assert line["response_id"] == reply["response_id"]
        assert line["operation"] == reply["operation"]
        assert line["contract_version"] == contract.CONTRACT_VERSION
        assert {"caller", "time", "run_id", "ok", "ms"} <= set(line)


def test_the_caller_is_read_from_the_id_token() -> None:
    email = "agent-routed@example.iam.gserviceaccount.com"
    assert server.caller_from_headers({"authorization": f"Bearer {token(email)}"}) == email
    assert server.caller_from_headers({"authorization": "Bearer not-a-token"}) == ""
    assert server.caller_from_headers({}) == ""


MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def _rpc(method: str, params: dict[str, Any], rpc_id: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}


def test_a_call_without_a_caller_identity_is_refused(lines: list[dict[str, Any]]) -> None:
    with TestClient(server.build_app(state())) as http:
        refused = http.post("/mcp", headers=MCP_HEADERS, json=_rpc("tools/list", {}))
        assert refused.status_code == 401
        forged = http.post(
            "/mcp",
            headers={**MCP_HEADERS, "authorization": "Bearer x"},
            json=_rpc("tools/list", {}),
        )
        assert forged.status_code == 401
        assert http.get("/healthz").status_code == 200
    assert lines == []


def test_an_identified_caller_gets_through_and_is_logged_by_name(
    lines: list[dict[str, Any]],
) -> None:
    email = "agent-available@example.iam.gserviceaccount.com"
    headers = {
        **MCP_HEADERS,
        "authorization": f"Bearer {token(email)}",
        server.RUN_HEADER: "run-123",
    }
    with TestClient(server.build_app(state())) as http:
        init = http.post(
            "/mcp",
            headers=headers,
            json=_rpc(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            ),
        )
        assert init.status_code == 200, init.text
        reply = http.post(
            "/mcp",
            headers=headers,
            json=_rpc(
                "tools/call", {"name": contract.CHECK_RULE, "arguments": {"rule": "test loads"}}, 2
            ),
        )
        assert reply.status_code == 200, reply.text
    body = json.loads(reply.json()["result"]["content"][0]["text"])
    assert body["contract_version"] == contract.CONTRACT_VERSION
    assert lines[-1]["caller"] == email
    assert lines[-1]["run_id"] == "run-123"
    assert lines[-1]["response_id"] == body["response_id"]
