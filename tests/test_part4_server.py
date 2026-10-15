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

"""Part 4: contract 2.0.0 over MCP, with no cloud call. The server's log names what it served."""

from __future__ import annotations

from typing import Any

import pytest

from context_server import contract, server
from tests.test_contract import call, fake_metrics, lines  # noqa: F401 - pytest fixtures


@pytest.mark.usefixtures("fake_metrics")
def test_the_log_line_names_the_definitions_each_response_served(
    lines: list[dict[str, Any]],  # noqa: F811
) -> None:
    replies = [
        call(contract.COMPUTE_METRIC, {"metrics": ["late_deliveries"], "start_date": "2026-07-01"}),
        call(contract.LOOKUP_DEFINITION, {"term": "customer"}),
        call(contract.CHECK_RULE, {"rule": "invoice"}),
        call(contract.LOOKUP_DEFINITION, {"term": "miles"}),
    ]
    logged = [line for line in lines if line["event"] == server.LOG_EVENT]
    assert len(logged) == len(replies)
    for line, reply in zip(logged, replies, strict=True):
        assert reply["contract_version"] == "2.0.0"
        assert line["definitions"] == [f"{d['id']}@{d['version']}" for d in reply["definitions"]]
        for d in reply["definitions"]:
            assert d["owner"]
    assert logged[0]["definitions"] == ["on_time@1"]
    assert "customer@1" in logged[1]["definitions"]
    assert logged[2]["definitions"] == ["billable@1"]
    assert logged[3]["definitions"] == []
