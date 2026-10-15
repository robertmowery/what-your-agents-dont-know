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

"""The query tool's limits, checked without any cloud call."""

from typing import ClassVar

from tessaway.agents import prompt
from tessaway.warehouse import query


def test_a_run_that_has_used_its_queries_is_refused_before_bigquery_is_called() -> None:
    log = query.QueryLog(queries=[{"sql": "SELECT 1"}] * query.MAX_QUERIES)
    result = query.run_readonly("SELECT 2", log)
    assert result == {"error": query.LIMIT_MESSAGE}
    assert len(log.queries) == query.MAX_QUERIES
    assert log.refused_over_limit == 1


def test_agents_are_told_the_query_limit_and_have_calls_left_to_answer() -> None:
    assert f"at most {query.MAX_QUERIES} queries" in prompt.INSTRUCTION
    assert prompt.MAX_MODEL_CALLS > query.MAX_QUERIES + 1


# Part 3: the INTERVAL fix. In Part 2 one run ended because a query result held
# a BigQuery INTERVAL, which the client returns as a relativedelta, and the
# result could not be turned into JSON (results/part2/run_log.md).


class _Field:
    def __init__(self, name: str) -> None:
        self.name = name


class _Row:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def values(self) -> list[object]:
        return self._values


class _Result(list):
    schema: ClassVar[list[_Field]] = [_Field("gap"), _Field("hours"), _Field("amount")]


class _Job:
    statement_type = "SELECT"
    total_bytes_billed = 10

    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def result(self, **_: object) -> _Result:
        return _Result(self._rows)


class _Client:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def query(self, sql: str, job_config: object = None) -> _Job:
        return _Job(self._rows)


def test_an_interval_in_a_result_is_written_as_text_and_the_result_is_json(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import datetime as dt
    import decimal
    import json

    from dateutil.relativedelta import relativedelta

    rows = [
        _Row(
            [
                relativedelta(days=2, hours=3, minutes=4, seconds=5),
                dt.timedelta(hours=26),
                decimal.Decimal("12.50"),
            ]
        ),
        _Row([relativedelta(years=1, months=2), None, decimal.Decimal("0")]),
    ]
    monkeypatch.setattr(query, "client", lambda: _Client(rows))
    monkeypatch.setattr(query.config, "project", lambda: "test-project")
    result = query.run_readonly("SELECT ts2 - ts1 AS gap FROM t", query.QueryLog())
    json.dumps(result)  # raised TypeError before the fix
    assert result["rows"][0] == ["0-0 2 3:04:05", "0-0 1 2:00:00", 12.5]
    assert result["rows"][1] == ["1-2 0 0:00:00", None, 0.0]


def test_cells_json_cannot_carry_never_stop_a_run() -> None:
    class Odd:
        def __str__(self) -> str:
            return "odd value"

    assert query._plain(Odd()) == "odd value"
    assert query._plain([Odd(), 1]) == ["odd value", 1]
    assert query._plain({"a": Odd()}) == {"a": "odd value"}
