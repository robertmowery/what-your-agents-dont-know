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

"""Scores agent answers in plain code. No model is in the loop.

Every reply lands in exactly one bin:

    right              the answer matches the correct one within the tolerance
    confidently_wrong  the agent gave an answer and it does not match
    declined           the agent said it could not answer or asked for clarification
    no_answer          the run produced nothing to score (error, timeout, no final line)

The headline number is the share of runs that are confidently wrong.

The scorer reads the last line of the form ``ANSWER: <value>``. The rules that
needed deciding are written out in the functions below, and each has a test in
``tests/test_scorer.py``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Any

from tessaway.agents.prompt import DECLINE_TOKEN
from tessaway.questions import Question

RIGHT = "right"
WRONG = "confidently_wrong"
DECLINED = "declined"
NO_ANSWER = "no_answer"
BINS = (RIGHT, WRONG, DECLINED, NO_ANSWER)

# The final line. Markdown emphasis around it is tolerated.
_ANSWER_LINE = re.compile(r"^[\s>*_`#-]*ANSWER[*_`]*\s*:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)

# Used only when a reply has no ANSWER line at all: words that mean the agent
# stopped to ask or said it could not answer.
_DECLINE_WORDS = re.compile(
    r"clarif|could you (please )?(confirm|specify|tell)|which (definition|one) (do|did|would) you"
    r"|cannot (answer|determine|be determined)|can't (answer|determine)"
    r"|unable to (answer|determine)"
    r"|not enough information|need more information",
    re.IGNORECASE,
)

# Secondary flag, not a bin: the reply says out loud that it chose a reading.
_ASSUMPTION_WORDS = re.compile(
    r"\bassum\w*|\binterpret\w*|\bdefin(?:e|ed|es|ing|ition|itions)\b|\bambiguous\b|\bunclear\b"
    r"|\bdepend(?:s|ing)? on\b|\bcaveat\w*|\bnote that\b",
    re.IGNORECASE,
)

# Secondary flag, not a bin: the reply says it ran out of its query allowance.
# A decline for that reason is the harness speaking, not the agent's judgment.
_LIMIT_WORDS = re.compile(
    r"query limit|limit (was |has been )?reached|reached (my|the|a) [a-z ]*limit"
    r"|(ran|run|running) out of quer|no (more|remaining|further) quer"
    r"|(maximum|max) (number of )?(allowed )?quer|quer(y|ies) (budget|allowance|quota|limit)"
    r"|used (all|up)( of)? (my|the|\d+)",
    re.IGNORECASE,
)

# A number that does not start inside a word, so the 3 in "Q3" is not read as one.
_NUMBER = re.compile(r"(?<![A-Za-z\d.,])[-+]?\(?\$?\s*\d[\d,]*(?:\.\d+)?")
_SCALE = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mm": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
}


@dataclass(frozen=True)
class Score:
    """The verdict on one reply."""

    outcome: str
    extracted: str  # the text after "ANSWER:", or "" when there was no such line
    value: float | str | None  # the parsed number, or the text for name questions
    matched_decoy: str  # label of the wrong reading the answer matches, or ""
    flagged_assumption: bool  # the reply says it assumed or chose a definition
    mentions_query_limit: bool = False  # the reply says it ran out of queries

    def as_dict(self) -> dict[str, Any]:
        """Return the fields saved with each run."""
        return {
            "outcome": self.outcome,
            "extracted": self.extracted,
            "value": self.value,
            "matched_decoy": self.matched_decoy,
            "flagged_assumption": self.flagged_assumption,
            "mentions_query_limit": self.mentions_query_limit,
        }


def extract_answer(reply: str) -> str | None:
    """Return the text after the last ``ANSWER:`` line, or None if there is none."""
    matches = _ANSWER_LINE.findall(reply or "")
    if not matches:
        return None
    return str(matches[-1]).strip().strip("*_`").strip()


def parse_number(text: str) -> float | None:
    """Read the number from an answer such as ``$1,234.50``, ``87.2%`` or ``10.4 million``.

    When the text holds more than one number ("36 customers in 2026"), the
    first is the answer. Returns None when it holds none.
    """
    cleaned = text.replace("\u2212", "-").replace("USD", " ").replace("US$", "$")
    match = _NUMBER.search(cleaned)
    if match is None:
        return None
    token = match.group(0)
    negative = token.startswith(("-", "(")) or cleaned[: match.start()].rstrip().endswith("-")
    digits = re.sub(r"[^\d.]", "", token)
    if not digits or digits == ".":
        return None
    value = float(digits)
    word = re.match(r"\s*([a-z]+)", cleaned[match.end() :].lower())
    if word and word.group(1) in _SCALE:
        value *= _SCALE[word.group(1)]
    return -value if negative else value


def _normalize(text: str) -> str:
    """Lowercase and reduce punctuation to spaces, so names compare on their words."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def numbers_match(value: float, target: float, kind: str, tolerance: float) -> bool:
    """Compare a numeric answer with a target under one tolerance rule."""
    if kind == "exact":
        return abs(value - target) < 1e-9
    if kind == "abs":
        return abs(value - target) <= tolerance + 1e-9
    return abs(value - target) <= tolerance * abs(target) + 1e-9


def _as_percent(value: float, target: float) -> float:
    """Read a fraction as a percentage when the correct answer is clearly a percentage.

    The instruction asks for 0 to 100. An agent that answers 0.861 for 86.1
    percent has the right number in the wrong unit, and is scored on the number.
    """
    if 0 <= value <= 1 and target > 1.5:
        return value * 100
    return value


def _text_matches(answer: str, accept: tuple[str, ...], reject: tuple[str, ...]) -> bool:
    """A name is right when it contains an accepted form and no rejected one."""
    normalized = f" {_normalize(answer)} "
    if any(f" {_normalize(bad)} " in normalized for bad in reject):
        return False
    return any(f" {_normalize(good)} " in normalized for good in accept)


def score(
    question: Question,
    gold: Any,
    decoys: list[dict[str, Any]],
    reply: str,
    *,
    failed: bool = False,
) -> Score:
    """Sort one reply into a bin.

    Args:
        question: The question that was asked.
        gold: The correct answer from the question's gold SQL.
        decoys: ``[{"label", "value"}]`` from the question's decoy SQL.
        reply: The agent's final text.
        failed: True when the run ended in an error or a timeout.
    """
    verdict = _bin(question, gold, decoys, reply, failed=failed)
    if _LIMIT_WORDS.search(reply or ""):
        return replace(verdict, mentions_query_limit=True)
    return verdict


def _bin(
    question: Question, gold: Any, decoys: list[dict[str, Any]], reply: str, *, failed: bool
) -> Score:
    """Choose the bin. ``score`` adds the flags that do not affect it."""
    flagged = bool(_ASSUMPTION_WORDS.search(reply or ""))
    extracted = extract_answer(reply)

    if extracted is None:
        # No final line. A reply that stops to ask is a decline; anything else
        # is not scored as an answer, because code cannot tell which number in
        # a paragraph the agent meant.
        if reply and reply.strip() and not failed and _DECLINE_WORDS.search(reply):
            return Score(DECLINED, "", None, "", flagged)
        return Score(NO_ANSWER, "", None, "", flagged)

    if DECLINE_TOKEN in extracted.upper().replace(" ", "_"):
        return Score(DECLINED, extracted, None, "", flagged)

    if question.answer_type == "text":
        accept = question.accept or (str(gold),)
        if _text_matches(extracted, accept, question.reject):
            return Score(RIGHT, extracted, extracted, "", flagged)
        if not _normalize(extracted):
            return Score(DECLINED, extracted, None, "", flagged)
        matched = next(
            (d["label"] for d in decoys if _text_matches(extracted, (str(d["value"]),), ())), ""
        )
        return Score(WRONG, extracted, extracted, matched, flagged)

    value = parse_number(extracted)
    if value is None:
        # "ANSWER: unknown" or "ANSWER: N/A": the agent did not commit to a
        # number, which is a decline.
        return Score(DECLINED, extracted, None, "", flagged)
    target = float(gold)
    if question.answer_type == "percent":
        value = _as_percent(value, target)
    kind, tolerance = question.tolerance_kind, question.tolerance_value
    if numbers_match(value, target, kind, tolerance):
        return Score(RIGHT, extracted, value, "", flagged)
    matched = ""
    for decoy in decoys:
        if decoy["value"] is not None and numbers_match(
            value, float(decoy["value"]), kind, tolerance
        ):
            matched = str(decoy["label"])
            break
    return Score(WRONG, extracted, value, matched, flagged)


def shares(outcomes: list[str]) -> dict[str, Any]:
    """Count each bin and give its share of all runs."""
    counts = Counter(outcomes)
    total = len(outcomes)
    result: dict[str, Any] = {"runs": total}
    for name in BINS:
        result[name] = counts.get(name, 0)
        result[f"{name}_share"] = round(counts.get(name, 0) / total, 4) if total else None
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize one configuration's runs: overall, by group and by question."""
    by_group: dict[str, list[str]] = {}
    by_question: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_group.setdefault(row["group"], []).append(row["outcome"])
        by_question.setdefault(row["question_id"], []).append(row)

    def mean(key: str, items: list[dict[str, Any]]) -> float:
        return round(sum(float(i.get(key) or 0) for i in items) / len(items), 4) if items else 0.0

    wrong = [r for r in rows if r["outcome"] == WRONG]
    return {
        "overall": shares([r["outcome"] for r in rows]),
        "by_group": {group: shares(outcomes) for group, outcomes in by_group.items()},
        "by_question": {
            qid: {
                **shares([r["outcome"] for r in items]),
                "group": items[0]["group"],
                "mean_input_tokens": mean("input_tokens_total", items),
                "mean_output_tokens": mean("output_tokens", items),
                "mean_cost_usd": mean("cost_usd", items),
                "mean_queries": mean("query_count", items),
                "decoys_matched": dict(
                    Counter(r["matched_decoy"] for r in items if r.get("matched_decoy"))
                ),
            }
            for qid, items in by_question.items()
        },
        "wrong_answers_that_flagged_an_assumption": sum(
            1 for r in wrong if r.get("flagged_assumption")
        ),
        "wrong_answers": len(wrong),
        "declines": sum(1 for r in rows if r["outcome"] == DECLINED),
        "declines_that_mention_the_query_limit": sum(
            1 for r in rows if r["outcome"] == DECLINED and r.get("mentions_query_limit")
        ),
        "runs_that_used_every_query": sum(
            1 for r in rows if (r.get("queries_refused_over_limit") or 0) > 0
        ),
        "mean_cost_usd_per_question": mean("cost_usd", rows),
        "mean_input_tokens_per_question": mean("input_tokens_total", rows),
        "mean_output_tokens_per_question": mean("output_tokens", rows),
        "total_cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in rows), 4),
    }
