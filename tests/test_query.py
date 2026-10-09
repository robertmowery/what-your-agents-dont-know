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
