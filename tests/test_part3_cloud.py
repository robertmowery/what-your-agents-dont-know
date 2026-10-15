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

"""Part 3, against the deployed context server: run with ``pytest -m cloud``.

Needs the service from ``infra/part3`` to be up, and the operator's
Application Default Credentials. Skipped when the service is not deployed.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import httpx
import pytest

from context_server import contract
from tessaway import contract_client

pytestmark = pytest.mark.cloud

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def _where() -> contract_client.Deployment:
    try:
        return contract_client.deployment()
    except (subprocess.CalledProcessError, FileNotFoundError, SystemExit, KeyError):
        pytest.skip("the Part 3 context server is not deployed")


def _rpc(method: str, params: dict[str, Any], rpc_id: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}


def _signed(caller: str = "routed") -> dict[str, str]:
    where = _where()
    token = contract_client.id_token(where.callers[caller], where.url)
    return {**HEADERS, "authorization": f"Bearer {token}", "x-tessaway-run": "pytest-cloud"}


def test_an_unauthenticated_call_is_refused_by_the_deployed_service() -> None:
    where = _where()
    reply = httpx.post(where.endpoint, headers=HEADERS, json=_rpc("tools/list", {}), timeout=30)
    assert reply.status_code in (401, 403)


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        (contract.LOOKUP_DEFINITION, {"term": "on-time delivery"}),
        (
            contract.COMPUTE_METRIC,
            {"metrics": ["revenue"], "start_date": "2026-07-01", "end_date": "2026-09-30"},
        ),
        (contract.CHECK_RULE, {"rule": "invoice"}),
        (contract.RESOLVE_ENTITY, {"name_or_id": "Northgate Foods"}),
    ],
)
def test_every_operation_answers_with_the_version_on_the_deployed_service(
    operation: str, arguments: dict[str, Any]
) -> None:
    where = _where()
    headers = _signed()
    with httpx.Client(timeout=120) as http:
        init = http.post(
            where.endpoint,
            headers=headers,
            json=_rpc(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
            ),
        )
        assert init.status_code == 200
        reply = http.post(
            where.endpoint,
            headers=headers,
            json=_rpc("tools/call", {"name": operation, "arguments": arguments}, 2),
        )
    assert reply.status_code == 200
    body = json.loads(reply.json()["result"]["content"][0]["text"])
    assert body["contract_version"] == contract.CONTRACT_VERSION
    assert body["response_id"]
    assert "error" not in body["result"], body["result"]
