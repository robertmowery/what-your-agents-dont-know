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

"""Part 6: the meter prices tokens, picks the scored record and rolls spend up."""

from __future__ import annotations

import pytest

from tessaway import meter


def run(**overrides):
    base = {
        "question_id": "M1",
        "group": "metric",
        "trial": 0,
        "model": "gemini-3.8-flash",
        "outcome": "right",
        "input_tokens": 1_000_000,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "input_tokens_total": 1_000_000,
        "output_tokens": 100_000,
        "model_calls": 4,
        "query_count": 2,
        "cost_usd": 1.125,
        "bigquery_bytes_billed": 0,
        "bigquery_usd": 0.0,
    }
    base.update(overrides)
    return base


def test_cost_function_prices_each_kind_of_token():
    # 1M uncached input at $0.75, 100k output at $3.75, 1M cached input at $0.075.
    r = run(cache_read_tokens=1_000_000)
    assert meter.model_cost(r) == pytest.approx(0.75 + 0.375 + 0.075)


def test_bigquery_cost_is_on_demand_rate_per_tebibyte():
    assert meter.bigquery_cost(run(bigquery_bytes_billed=2**40)) == pytest.approx(6.25)


def test_spend_is_model_plus_bigquery_as_recorded():
    assert meter.spend(run(cost_usd=0.03, bigquery_usd=0.0001)) == pytest.approx(0.0301)


def test_unknown_model_has_no_price():
    with pytest.raises(KeyError):
        meter.prices_for("some-other-model")


def test_the_rerun_replaces_the_failed_attempt():
    failed = run(outcome="no_answer", cost_usd=0.5)
    rerun = run(outcome="right", cost_usd=0.1, retry_of_failed=True)
    other = run(question_id="M2", cost_usd=0.2)
    records = [failed, rerun, other]
    assert meter.scored(records) == [rerun, other]
    assert meter.replaced(records) == [failed]


def test_cost_per_correct_answer_divides_all_scored_spend_by_right_answers():
    records = [
        run(outcome="right", cost_usd=0.02),
        run(question_id="M2", outcome="confidently_wrong", cost_usd=0.03),
        run(question_id="M3", outcome="declined", cost_usd=0.05),
        run(question_id="M4", outcome="right", cost_usd=0.02),
    ]
    r = meter.rollup(records)
    assert r["spend_usd"] == pytest.approx(0.12)
    assert r["cost_per_correct_usd"] == pytest.approx(0.06)
    assert r["spend_by_outcome_usd"]["declined"] == pytest.approx(0.05)
    assert r["shares"]["right"] == pytest.approx(0.5)


def test_no_right_answers_means_no_cost_per_correct():
    assert meter.rollup([run(outcome="declined")])["cost_per_correct_usd"] is None


def test_step_profile_averages_the_prompt_at_each_call():
    records = [
        run(prompt_tokens_by_call=[[100, 0], [300, 0]]),
        run(question_id="M2", prompt_tokens_by_call=[[200, 0]]),
    ]
    profile = meter.step_profile(records, steps=3)
    assert profile[0] == {"step": 1, "runs": 2, "mean_input_tokens": 150}
    assert profile[1] == {"step": 2, "runs": 1, "mean_input_tokens": 300}
    assert profile[2]["runs"] == 0


def test_reprice_uses_other_prices_and_keeps_bigquery():
    r = run(bigquery_usd=0.01)
    assert meter.reprice([r], usd_in=1.50, usd_out=7.50, usd_cache_read=0.15) == pytest.approx(
        1.5 + 0.75 + 0.01
    )


def test_every_saved_record_matches_its_tokens():
    """The cost each run recorded is what its tokens cost at the pinned prices."""
    checked = 0
    for cfg in meter.SERIES + meter.UNSCORED + meter.PART7:
        for r in meter.load(cfg.path):
            assert meter.model_cost(r) == pytest.approx(float(r["cost_usd"]), abs=1e-6), (
                cfg.key,
                r["run_id"],
            )
            if "bigquery_bytes_billed" in r:  # the Claude demonstration kept dollars, not bytes
                assert meter.bigquery_cost(r) == pytest.approx(
                    float(r["bigquery_usd"]), abs=1e-6
                ), (cfg.key, r["run_id"])
            checked += 1
    assert checked > 1000


def test_series_covers_every_scored_runs_file():
    import glob

    listed = {cfg.path for cfg in meter.SERIES + meter.UNSCORED + meter.PART7}
    found = {
        str(p).split("results/", 1)[1]
        for p in map(str, sorted(glob.glob(str(meter.RESULTS / "*" / "runs" / "*.jsonl"))))
    }
    assert found <= listed
