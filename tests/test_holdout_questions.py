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

"""The held-out question set, checked without any cloud call or model."""

import json
import os
import re
from collections import Counter

from tessaway import questions

# The reader's own Google Cloud project, if set; no query may name it.
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()

HOLDOUT_PATH = questions.ROOT / "questions" / "holdout.yaml"
HOLDOUT_GOLD_PATH = questions.ROOT / "results" / "holdout" / "gold_answers.json"

HOLDOUT = questions.load(HOLDOUT_PATH)
PART1 = questions.load()

WRITE_WORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CALL|EXPORT|LOAD)\b",
    flags=re.IGNORECASE,
)


def _all_sql() -> list[tuple[str, str]]:
    pairs = []
    for q in HOLDOUT:
        pairs.append((f"{q.id} gold", q.gold_sql))
        pairs += [(f"{q.id} decoy '{d.label}'", d.sql) for d in q.decoys]
    return pairs


def _without_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def test_there_are_twelve_questions_four_in_each_group_and_no_lookups() -> None:
    assert len(HOLDOUT) == 12
    assert Counter(q.group for q in HOLDOUT) == {"metric": 4, "entity": 4, "rule": 4}


def test_ids_are_h1_to_h12_and_none_is_a_part_1_id() -> None:
    ids = [q.id for q in HOLDOUT]
    assert ids == [f"H{n}" for n in range(1, 13)]
    assert not set(ids) & {q.id for q in PART1}


def test_every_question_names_a_definition_that_exists() -> None:
    known = questions.definition_ids()
    for q in HOLDOUT:
        assert q.definitions, q.id
        assert set(q.definitions) <= known, q.id


def test_every_query_is_one_read_only_select_with_no_project_in_it() -> None:
    for name, sql in _all_sql():
        code = _without_comments(sql).strip()
        assert re.match(r"(?i)(SELECT|WITH)\b", code), name
        assert ";" not in code, name
        assert not WRITE_WORDS.search(code), name
        assert not PROJECT or PROJECT not in sql, name
        assert "tessaway_wh" not in sql, name
        assert "`" not in sql, name


def test_every_question_has_a_decoy_with_a_label_and_sql() -> None:
    for q in HOLDOUT:
        assert q.decoys, q.id
        for decoy in q.decoys:
            assert decoy.label.strip() and decoy.sql.strip(), q.id


def test_no_question_repeats_a_part_1_question_or_another_holdout_question() -> None:
    part1_text = {_normalized(q.question) for q in PART1}
    holdout_text = [_normalized(q.question) for q in HOLDOUT]
    assert not set(holdout_text) & part1_text
    assert len(set(holdout_text)) == len(holdout_text)


def test_text_answers_carry_accept_and_reject_lists() -> None:
    for q in HOLDOUT:
        if q.answer_type == "text":
            assert q.accept and q.reject, q.id


def test_tolerances_follow_the_part_1_conventions() -> None:
    for q in HOLDOUT:
        if q.answer_type == "money":
            assert (q.tolerance_kind, q.tolerance_value) == ("rel", 0.01), q.id
        if q.answer_type == "percent":
            assert (q.tolerance_kind, q.tolerance_value) == ("abs", 0.5), q.id
        if q.answer_type == "text":
            assert q.tolerance_kind == "exact", q.id


def test_saved_gold_answers_differ_from_every_decoy_by_more_than_the_tolerance() -> None:
    saved = json.loads(HOLDOUT_GOLD_PATH.read_text())
    assert saved["question_count"] == 12
    answers = saved["answers"]
    assert list(answers) == [q.id for q in HOLDOUT]
    for q in HOLDOUT:
        gold = answers[q.id]["gold"]
        assert gold not in (None, 0, ""), q.id
        decoys = answers[q.id]["decoys"]
        assert [d["label"] for d in decoys] == [d.label for d in q.decoys], q.id
        for decoy in decoys:
            value = decoy["value"]
            if q.answer_type == "text":
                assert value != gold, (q.id, decoy["label"])
                continue
            allowed = {
                "exact": 0.0,
                "abs": q.tolerance_value,
                "rel": q.tolerance_value * abs(gold),
            }[q.tolerance_kind]
            assert abs(value - gold) > allowed, (q.id, decoy["label"])
