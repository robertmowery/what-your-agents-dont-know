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

"""Checks that need BigQuery and the MetricFlow environment.

These are kept out of the default test run, which makes no cloud call:

    python -m pytest -q             # everything else
    python -m pytest -q -m cloud    # these

They need Application Default Credentials, the loaded warehouse, the dbt views
(``dbt run`` in ``semantic_layer/``) and the ``.venv-dbt`` environment.
"""

import pytest

from tessaway.layers import graph, semantic

pytestmark = pytest.mark.cloud


def test_every_metric_returns_what_the_part_1_gold_sql_returns() -> None:
    report = semantic.check_against_gold()
    failed = [r for r in report["results"] if not r["matches"]]
    assert not failed, [(r["metric"], r["got"], r["expected"], r["error"]) for r in failed]
    assert report["metrics_not_checked"] == []
    assert report["cases"] == 25


def test_the_committed_catalog_is_what_metricflow_reports() -> None:
    live = semantic.worker().request({"op": "catalog"})
    assert live == semantic.catalog()


def test_metricflow_wrote_the_sql_and_it_reads_the_dbt_views() -> None:
    reply = semantic.generate_sql(["on_time_rate"], start_date="2026-09-01", end_date="2026-09-30")
    assert "tessaway_sem" in reply["sql"]
    assert "on_time_measured_loads" in reply["sql"]


def test_an_unknown_metric_is_an_error_the_agent_can_read() -> None:
    reply = semantic.run_metrics(["no_such_metric"])
    assert "error" in reply
    assert "no_such_metric" in reply["error"]


def test_the_graph_from_bigquery_is_the_graph_from_the_generator() -> None:
    from_cloud = set(graph.triples(graph.rows_from_bigquery()))
    from_seed = set(graph.triples(graph.rows_from_generator()))
    assert from_cloud == from_seed
    assert len(from_cloud) > 200_000
