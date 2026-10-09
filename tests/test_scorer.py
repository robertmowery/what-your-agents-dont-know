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

"""How replies are scored, rule by rule, with no model and no cloud call."""

import pytest

from tessaway import questions, scoring
from tessaway.agents import prompt
from tessaway.questions import Decoy, Question
from tessaway.warehouse import schema


def make(
    answer_type: str = "number", kind: str = "exact", value: float = 0.0, **kw: object
) -> Question:
    return Question(
        id="T1", group="metric", question="?", answer_type=answer_type, tolerance_kind=kind,
        tolerance_value=value, definitions=(), why="", gold_sql="SELECT 1", **kw,  # type: ignore[arg-type]
    )  # fmt: skip


COUNT = make()
MONEY = make("money", "rel", 0.01)
RATE = make("percent", "abs", 0.5)
NAME = make(
    "text", accept=("Northgate Foods Group", "Northgate Foods"), reject=("Joliet", "Canada")
)


# --- reading the final line ----------------------------------------------------


def test_the_last_answer_line_is_the_answer() -> None:
    reply = "First pass.\nANSWER: 10\nOn reflection that double counts.\nANSWER: 8"
    assert scoring.extract_answer(reply) == "8"


@pytest.mark.parametrize(
    "line", ["ANSWER: 42", "**ANSWER:** 42", "answer: 42", "  ANSWER:42  ", "> ANSWER: `42`"]
)
def test_markdown_around_the_answer_line_is_tolerated(line: str) -> None:
    assert scoring.extract_answer(f"Explanation.\n\n{line}") == "42"


def test_a_reply_without_an_answer_line_has_no_answer() -> None:
    assert scoring.extract_answer("The answer is 42.") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1128", 1128.0),
        ("1,128", 1128.0),
        ("$10,294,019.12", 10294019.12),
        ("10294019.12 USD", 10294019.12),
        ("87.44%", 87.44),
        ("10.3 million", 10_300_000.0),
        ("$10.3M", 10_300_000.0),
        ("-250.50", -250.5),
        ("36 customers in Q3 2026", 36.0),
        ("approximately 409.19 per load", 409.19),
    ],
)
def test_numbers_are_read_in_the_forms_models_write_them(text: str, expected: float) -> None:
    assert scoring.parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["unknown", "N/A", "", "Q3"])
def test_text_with_no_number_is_not_a_number(text: str) -> None:
    assert scoring.parse_number(text) is None


# --- the bins ------------------------------------------------------------------


def test_a_matching_count_is_right_and_any_other_count_is_confidently_wrong() -> None:
    assert scoring.score(COUNT, 1097, [], "ANSWER: 1,097").outcome == scoring.RIGHT
    assert scoring.score(COUNT, 1097, [], "ANSWER: 1098").outcome == scoring.WRONG


def test_money_is_right_within_one_percent() -> None:
    gold = 10_294_019.12
    assert scoring.score(MONEY, gold, [], "ANSWER: $10,300,000").outcome == scoring.RIGHT
    assert scoring.score(MONEY, gold, [], "ANSWER: 10610385.50").outcome == scoring.WRONG


def test_a_rate_is_right_within_half_a_point() -> None:
    assert scoring.score(RATE, 87.44, [], "ANSWER: 87.0").outcome == scoring.RIGHT
    assert scoring.score(RATE, 87.44, [], "ANSWER: 84.41%").outcome == scoring.WRONG


def test_a_rate_given_as_a_fraction_is_scored_on_the_number() -> None:
    assert scoring.score(RATE, 87.44, [], "ANSWER: 0.8744").outcome == scoring.RIGHT
    assert scoring.score(RATE, 87.44, [], "ANSWER: 0.8441").outcome == scoring.WRONG


def test_the_decline_token_is_a_decline() -> None:
    reply = "On-time could mean several things here.\nANSWER: NEEDS_CLARIFICATION"
    assert scoring.score(RATE, 87.44, [], reply).outcome == scoring.DECLINED
    assert scoring.score(NAME, "x", [], "ANSWER: needs clarification").outcome == scoring.DECLINED


def test_an_answer_line_with_no_number_is_a_decline() -> None:
    assert scoring.score(COUNT, 5, [], "ANSWER: cannot be determined").outcome == scoring.DECLINED


def test_no_answer_line_is_a_decline_only_when_the_reply_asks_or_gives_up() -> None:
    asks = "Could you confirm which definition of on-time you want?"
    states = "The on-time rate was 84.41 percent."
    assert scoring.score(RATE, 87.44, [], asks).outcome == scoring.DECLINED
    assert scoring.score(RATE, 87.44, [], states).outcome == scoring.NO_ANSWER


def test_a_failed_run_with_nothing_to_read_is_no_answer() -> None:
    assert scoring.score(COUNT, 5, [], "", failed=True).outcome == scoring.NO_ANSWER
    partial = "I need to clarify the tables first."
    assert scoring.score(COUNT, 5, [], partial, failed=True).outcome == scoring.NO_ANSWER


def test_a_failed_run_that_still_gave_a_final_line_is_scored_on_it() -> None:
    assert scoring.score(COUNT, 5, [], "ANSWER: 5", failed=True).outcome == scoring.RIGHT


def test_an_answer_with_caveats_is_still_an_answer() -> None:
    reply = "Assuming on-time means inside the appointment window.\nANSWER: 84.41"
    verdict = scoring.score(RATE, 87.44, [], reply)
    assert verdict.outcome == scoring.WRONG
    assert verdict.flagged_assumption


def test_a_plain_wrong_answer_is_not_flagged_as_an_assumption() -> None:
    verdict = scoring.score(RATE, 87.44, [], "The rate was computed from stops.\nANSWER: 84.41")
    assert not verdict.flagged_assumption


def test_a_decline_that_blames_the_query_limit_is_flagged_but_still_a_decline() -> None:
    reply = "I reached my query limit before the final sum.\nANSWER: NEEDS_CLARIFICATION"
    verdict = scoring.score(COUNT, 5, [], reply)
    assert verdict.outcome == scoring.DECLINED and verdict.mentions_query_limit
    asks = "Which definition of on-time do you want?\nANSWER: NEEDS_CLARIFICATION"
    assert not scoring.score(COUNT, 5, [], asks).mentions_query_limit


# --- names ---------------------------------------------------------------------


def test_a_name_is_right_when_it_holds_an_accepted_form() -> None:
    gold = "Northgate Foods Group"
    assert scoring.score(NAME, gold, [], "ANSWER: Northgate Foods Group").outcome == scoring.RIGHT
    assert scoring.score(NAME, gold, [], "ANSWER: northgate foods").outcome == scoring.RIGHT


def test_a_site_or_bill_to_row_is_not_the_customer() -> None:
    gold = "Northgate Foods Group"
    site = "ANSWER: Northgate Foods - Joliet DC"
    other = "ANSWER: Pellam Paper - Savannah Mill"
    assert scoring.score(NAME, gold, [], site).outcome == scoring.WRONG
    assert scoring.score(NAME, gold, [], other).outcome == scoring.WRONG


def test_a_name_with_no_accept_list_must_hold_the_gold_answer() -> None:
    plain = make("text")
    assert scoring.score(plain, "Green Bay", [], "ANSWER: Green Bay, WI").outcome == scoring.RIGHT
    assert scoring.score(plain, "Green Bay", [], "ANSWER: Tampa Bay").outcome == scoring.WRONG


# --- naming the mistake ----------------------------------------------------------


def test_a_wrong_answer_is_matched_to_the_reading_that_produces_it() -> None:
    decoys = [
        {"label": "operations definition", "value": 84.41},
        {"label": "portal definition", "value": 91.52},
    ]
    verdict = scoring.score(RATE, 87.44, decoys, "ANSWER: 91.5")
    assert (verdict.outcome, verdict.matched_decoy) == (scoring.WRONG, "portal definition")
    assert scoring.score(RATE, 87.44, decoys, "ANSWER: 50").matched_decoy == ""
    named = scoring.score(
        NAME, "Northgate Foods Group",
        [{"label": "largest shipper row", "value": "Pellam Paper - Savannah Mill"}],
        "ANSWER: Pellam Paper - Savannah Mill",
    )  # fmt: skip
    assert named.matched_decoy == "largest shipper row"


def test_a_right_answer_never_reports_a_decoy() -> None:
    decoys = [{"label": "same number by another route", "value": 1097}]
    assert scoring.score(COUNT, 1097, decoys, "ANSWER: 1097").matched_decoy == ""


# --- adding it up ----------------------------------------------------------------


def test_shares_are_of_all_runs_and_add_to_one() -> None:
    outcomes = [scoring.RIGHT] * 5 + [scoring.WRONG] * 3 + [scoring.DECLINED, scoring.NO_ANSWER]
    result = scoring.shares(outcomes)
    assert result["runs"] == 10
    assert result["confidently_wrong_share"] == 0.3
    assert sum(result[f"{name}_share"] for name in scoring.BINS) == pytest.approx(1.0)


def test_summary_splits_by_group_and_question() -> None:
    rows = [
        {"question_id": "L1", "group": "lookup", "outcome": scoring.RIGHT, "cost_usd": 0.01},
        {"question_id": "M1", "group": "metric", "outcome": scoring.WRONG, "cost_usd": 0.03,
         "matched_decoy": "operations definition", "flagged_assumption": True},
    ]  # fmt: skip
    summary = scoring.summarize(rows)
    assert summary["overall"]["confidently_wrong_share"] == 0.5
    assert summary["by_group"]["lookup"]["right_share"] == 1.0
    assert summary["by_question"]["M1"]["decoys_matched"] == {"operations definition": 1}
    assert summary["wrong_answers_that_flagged_an_assumption"] == 1
    assert summary["total_cost_usd"] == 0.04


# --- the question set and what the agents are shown --------------------------------


def test_the_question_set_has_four_groups_of_six() -> None:
    asked = questions.load()
    assert len(asked) == 24
    assert {g: sum(q.group == g for q in asked) for g in questions.GROUPS} == dict.fromkeys(
        questions.GROUPS, 6
    )


def test_lookups_need_no_definition_and_every_other_question_names_one() -> None:
    for question in questions.load():
        assert bool(question.definitions) == (question.group != "lookup"), question.id
        assert question.why


def test_gold_sql_is_a_single_read_only_statement_with_no_project_in_it() -> None:
    for question in questions.load():
        for sql in [question.gold_sql, *(d.sql for d in question.decoys)]:
            assert sql.lstrip().upper().startswith(("SELECT", "WITH")), question.id
            assert ";" not in sql and "`" not in sql, question.id


def test_decoys_are_well_formed() -> None:
    for question in questions.load():
        assert all(isinstance(d, Decoy) and d.label and d.sql for d in question.decoys)


def test_agents_are_shown_every_table_and_column_and_no_definitions() -> None:
    text = prompt.INSTRUCTION
    for table, columns in schema.TABLES.items():
        assert table in text
        assert all(f"  {name} {kind}" in text for name, kind in columns)
    for meaning in ["proof of delivery", "parent account", "re-tender", "appointment window",
                    "Canadian", "UTC", "local time", "test load", "voided", "bill-to"]:  # fmt: skip
        assert meaning.lower() not in text.lower(), meaning


def test_agents_are_told_how_to_decline() -> None:
    assert f"ANSWER: {prompt.DECLINE_TOKEN}" in prompt.INSTRUCTION
