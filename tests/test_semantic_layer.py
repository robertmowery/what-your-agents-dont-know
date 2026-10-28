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

"""The semantic layer's definitions and its tool, checked without any cloud call.

Whether each metric returns the right number is a cloud test: see
``tests/test_cloud.py``, which runs MetricFlow's SQL on BigQuery beside the
Part 1 gold SQL.
"""

import yaml

from tessaway import questions
from tessaway.layers import semantic

SEMANTIC_YML = semantic.PROJECT_DIR / "models" / "semantic.yml"


def defined() -> dict[str, dict[str, str]]:
    """The metrics an agent can ask for by name.

    Part 7's version 2 metrics (names ending ``_v2`` or ``_r2``) are served by the
    contract under the version 1 names and are not in the catalog;
    tests/test_part7_versions.py covers them.
    """
    every = yaml.safe_load(SEMANTIC_YML.read_text())["metrics"]
    return {m["name"]: m for m in every if not m["name"].endswith(("_v2", "_r2"))}


def test_the_catalog_lists_exactly_the_metrics_the_yaml_defines() -> None:
    catalog = {m["name"]: m for m in semantic.catalog()["metrics"]}
    assert set(catalog) == set(defined())
    assert len(catalog) == 18


def test_the_catalog_carries_each_metric_description_as_written() -> None:
    catalog = {m["name"]: m for m in semantic.catalog()["metrics"]}
    for name, metric in defined().items():
        assert catalog[name]["description"] == " ".join(metric["description"].split()), name


def test_the_metrics_the_brief_names_are_defined() -> None:
    assert {"on_time_rate", "margin_per_load", "delivered_loads", "revenue"} <= set(defined())


def test_every_metric_has_a_gold_check() -> None:
    cases = yaml.safe_load(semantic.GOLD_CHECKS_PATH.read_text())
    checked = {case["request"]["metrics"][0] for case in cases}
    assert checked == set(defined())


def test_a_gold_check_names_a_real_question_or_carries_its_own_reference() -> None:
    ids = {q.id for q in questions.load()}
    for case in yaml.safe_load(semantic.GOLD_CHECKS_PATH.read_text()):
        assert ("question" in case) != ("reference_sql" in case)
        if "question" in case:
            assert case["question"] in ids


def test_no_view_or_metric_names_a_particular_account_or_carrier() -> None:
    text = SEMANTIC_YML.read_text().lower()
    for path in (semantic.PROJECT_DIR / "models").glob("*.sql"):
        text += path.read_text().lower()
    for name in ("northgate", "harlow", "sunmeadow", "ledgerline", "pellam", "midvale"):
        assert name not in text


# --- filters: a bare dimension name is written the way MetricFlow wants it ---------

KINDS = {
    "tender__carrier_name": "categorical",
    "tender__is_cross_border": "categorical",
    "delivery__delivered_date": "time",
}


def test_a_bare_dimension_name_is_wrapped() -> None:
    assert (
        semantic.to_metricflow_filter("tender__carrier_name = 'Some Carrier'", KINDS)
        == "{{ Dimension('tender__carrier_name') }} = 'Some Carrier'"
    )


def test_text_inside_quotes_is_left_alone() -> None:
    assert (
        semantic.to_metricflow_filter("tender__carrier_name = 'tender__is_cross_border'", KINDS)
        == "{{ Dimension('tender__carrier_name') }} = 'tender__is_cross_border'"
    )


def test_time_names_become_time_dimensions() -> None:
    assert (
        semantic.to_metricflow_filter("metric_time__month = '2026-09-01'", KINDS)
        == "{{ TimeDimension('metric_time', 'month') }} = '2026-09-01'"
    )
    assert (
        semantic.to_metricflow_filter("delivery__delivered_date >= '2026-09-01'", KINDS)
        == "{{ TimeDimension('delivery__delivered_date', 'day') }} >= '2026-09-01'"
    )
    assert (
        semantic.to_metricflow_filter("delivery__delivered_date__month = '2026-09-01'", KINDS)
        == "{{ TimeDimension('delivery__delivered_date', 'month') }} = '2026-09-01'"
    )


def test_a_filter_already_in_metricflow_form_or_with_unknown_names_is_unchanged() -> None:
    written = "{{ Dimension('tender__carrier_name') }} = 'X'"
    assert semantic.to_metricflow_filter(written, KINDS) == written
    assert semantic.to_metricflow_filter("nothing__known = 1 AND true", KINDS) == (
        "nothing__known = 1 AND true"
    )
