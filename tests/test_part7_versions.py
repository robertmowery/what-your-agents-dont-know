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

"""Part 7: two versions of revenue, served side by side and routed on the server. No cloud call."""

from __future__ import annotations

import json
from typing import Any

import pytest

from context_server import contract, server, versions
from tessaway import golden_set, registry

CANARY = {"default": "v1", "cohorts": {"2": "revenue_v2"}}


def test_the_canary_sends_one_cohort_in_three_to_version_2() -> None:
    served = [versions.resolve(str(c), table=CANARY) for c in (0, 1, 2)]
    assert [s[0] for s in served] == ["v1", "v1", "revenue_v2"]
    assert served[2][1] == {"revenue": 2, "margin": 1}
    assert versions.resolve(None, table=CANARY) == ("v1", {"revenue": 1, "margin": 1})


def test_a_caller_can_ask_for_a_version_and_unknown_ones_are_refused() -> None:
    assert versions.resolve("0", {"revenue": 2}, table=CANARY) == (
        "requested",
        {"revenue": 2, "margin": 1},
    )
    with pytest.raises(ValueError):
        versions.resolve("0", {"revenue": 3}, table=CANARY)
    with pytest.raises(ValueError):
        versions.resolve("0", {"margin": 2}, table=CANARY)  # margin 2 needs revenue 2
    with pytest.raises(ValueError):
        versions.resolve("0", table={"default": "v3", "cohorts": {}})


def test_rollback_is_a_routing_change(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(versions.ROUTING_ENV, json.dumps(CANARY))
    assert versions.resolve("2")[0] == "revenue_v2"
    monkeypatch.setenv(versions.ROUTING_ENV, json.dumps({"default": "v1"}))
    assert versions.resolve("2")[0] == "v1"


def test_metric_names_follow_the_versions_and_come_back_as_asked() -> None:
    asked, group_by, _where, back = versions.rewrite_request(
        ["margin_percentage"], ["document__document_type"], None, {"revenue": 2, "margin": 1}
    )
    assert asked == ["margin_percentage_r2"] and group_by == ["document_v2__document_type"]
    assert versions.rename_columns({"columns": ["margin_percentage_r2"]}, back) == {
        "columns": ["margin_percentage"]
    }
    asked, *_ = versions.rewrite_request(
        ["margin", "loads_booked"], None, None, versions.STATES["v2"]
    )
    assert asked == ["margin_v2", "loads_booked"]
    assert versions.rewrite_request(["revenue"], None, None, versions.STATES["v1"])[0] == [
        "revenue"
    ]


def test_every_version_2_metric_is_in_the_semantic_layer() -> None:
    text = (golden_set.ROOT / "semantic_layer" / "models" / "semantic.yml").read_text()
    for table in (versions.metric_names(s) for s in versions.STATES.values()):
        for name in table.values():
            assert f"- name: {name}\n" in text, name


def test_the_envelope_stamps_the_version_served() -> None:
    reply = contract.envelope(
        contract.COMPUTE_METRIC,
        {"rows": [[0]]},
        {"metrics": ["revenue"]},
        {"revenue": 2, "margin": 1},
    )
    assert reply["contract_version"] == "2.1.0"
    assert reply["definitions"] == [{"id": "revenue", "version": 2, "owner": "Controller"}]
    v1 = contract.envelope(
        contract.COMPUTE_METRIC, {"rows": [[0]]}, {"metrics": ["revenue"]}, versions.STATES["v1"]
    )
    assert v1["definitions"][0]["version"] == 1


def test_registry_refuses_a_version_it_does_not_hold() -> None:
    with pytest.raises(ValueError):
        registry.stamps(["currency"], versions={"currency": 2})
    assert registry.owner_of("revenue", 2) == "Controller"
    assert registry.owner_of("revenue", 1) == "Controller"  # version 1 stays in the history
    assert registry.definitions()["revenue"].version == 2  # current since the rollout


def test_lookup_is_worded_for_the_version_served() -> None:
    v1 = contract.lookup_definition("revenue")
    v2 = contract.lookup_definition("revenue", {"revenue": 2, "margin": 1})
    rules_v1 = " ".join(next(m for m in v1["matches"] if m["term"] == "tw:Revenue")["rules"])
    rules_v2 = " ".join(next(m for m in v2["matches"] if m["term"] == "tw:Revenue")["rules"])
    assert "credit date" in rules_v1 and "delivered" in rules_v2 and "credit date" not in rules_v2


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(server, "emit", captured.append)
    return captured


class _Ctx:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def test_the_server_routes_on_the_cohort_header_and_logs_it(
    monkeypatch: pytest.MonkeyPatch, lines: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv(versions.ROUTING_ENV, json.dumps(CANARY))
    seen: list[Any] = []

    def run_metrics(*args: Any) -> dict[str, Any]:
        seen.append(args[0])
        return {"columns": list(args[0]), "rows": [[1.0]], "row_count": 1, "truncated": False}

    monkeypatch.setattr(contract.semantic, "run_metrics", run_metrics)
    for cohort in ("0", "2"):
        ctx = _Ctx({versions.COHORT_HEADER: cohort})
        route = server._route(ctx, None)  # type: ignore[arg-type]
        reply = json.loads(
            server._respond(
                ctx,  # type: ignore[arg-type]
                contract.COMPUTE_METRIC,
                lambda r, route=route: contract.compute_metric(
                    ["revenue"], None, None, "2026-07-01", "2026-09-30", None, 50, r, route[1]
                ),
                {"metrics": ["revenue"]},
                route,
            )
        )
        assert reply["result"]["columns"] == ["revenue"]
    assert seen == [["revenue"], ["revenue_v2"]]
    assert [(line["cohort"], line["state"], line["definitions"]) for line in lines] == [
        ("0", "v1", ["revenue@1"]),
        ("2", "revenue_v2", ["revenue@2"]),
    ]


def test_golden_set_v2_is_frozen_and_moves_only_the_revenue_questions() -> None:
    v1 = golden_set.load(1)
    v2 = golden_set.load(2)
    moved = sorted(q for q in v1.answers if v1.gold(q) != v2.gold(q))
    assert moved == ["E3", "M2", "M3", "M4", "R3"]
    assert v2.gold("E1") == v1.gold("E1")
    mixed = [d for d in v2.answers["M3"]["decoys"] if "carrier cost" in d["label"]]
    assert mixed and mixed[0]["value"] != v2.gold("M3")
