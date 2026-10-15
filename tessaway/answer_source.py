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

"""Where a final answer came from, worked out in code from what each tool returned.

The agent's own account of where its answer came from is not used. For each
run, the value on the final ``ANSWER:`` line is compared with every value the
contract returned and every value the SQL tool returned in that run:

    contract   it matches a value the contract returned, and no SQL value
    sql        it matches a SQL value, and no contract value
    both       it matches a value from each
    neither    it matches nothing either tool returned: the agent worked it out
               (a ratio of two returned numbers, say) or wrote it from nowhere

Runs with no answer value (a decline, no final line) are counted apart.

The matching rule, fixed in ``results/part3/predictions.md`` before any scored run:

- A number matches a returned number when the returned number, rounded to the
  decimal places the agent wrote, is the agent's number: an answer of 87.5
  matches 87.46 and 87.54, and an answer of 1234568 matches 1234567.89. For a
  question whose answer is a percentage, the returned number times 100 is
  tried as well, so 0.875 matches 87.5.
- A name matches a returned text value when, compared on words without regard
  to case or punctuation, one contains the other and the shorter has at least
  four characters.
- Values are every number and text the tool returned, at any depth, except
  free text: definitions, rule statements and error messages. A number written
  inside a sentence is not a value.

Matching by value credits both sources whenever they agree, which is most of
the time; "both" means the two routes returned the same number, not that the
agent used both.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from tessaway import scoring

CONTRACT = "contract"
SQL = "sql"
BOTH = "both"
NEITHER = "neither"
NO_VALUE = "no_answer_value"
SOURCES = (CONTRACT, SQL, BOTH, NEITHER)

SQL_TOOL = "run_sql"
CONTRACT_TOOLS = ("lookup_definition", "compute_metric", "check_rule", "resolve_entity")

# Free text: not values an answer could be read from.
_FREE_TEXT_KEYS = frozenset(
    {"definition", "statement", "rules", "rules_checked_against_data", "warehouse_source", "error"}
)
_NUMERIC_TEXT = re.compile(r"^[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$")
_MIN_NAME_CHARS = 4


def leaves(value: Any, key: str = "") -> Iterator[Any]:
    """Yield every number and text value in a tool result, skipping free text."""
    if key in _FREE_TEXT_KEYS:
        return
    if isinstance(value, dict):
        for name, item in value.items():
            yield from leaves(item, str(name))
    elif isinstance(value, list | tuple):
        for item in value:
            yield from leaves(item, key)
    elif value is not None and not isinstance(value, bool):
        yield value


def as_number(value: Any) -> float | None:
    """Return a returned value as a number, when it is one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and _NUMERIC_TEXT.match(value.strip()):
        return float(value.strip())
    return None


def decimal_places(text: str) -> int:
    """Return how many decimal places the agent wrote in its answer's first number."""
    cleaned = text.replace(",", "")
    match = re.search(r"\d+(?:\.(\d+))?", cleaned)
    if match is None or match.group(1) is None:
        return 0
    return len(match.group(1))


def number_matches(answer: float, places: int, returned: float, *, percent: bool) -> bool:
    """Say whether a returned number, rounded as the agent rounded, is the agent's number."""
    half = 0.5 * 10.0**-places
    candidates = (returned, returned * 100) if percent else (returned,)
    return any(abs(answer - c) <= half + 1e-9 * max(1.0, abs(c)) for c in candidates)


def name_matches(answer: str, returned: str) -> bool:
    """Say whether a returned text value names what the agent named."""
    a, r = scoring._normalize(answer), scoring._normalize(returned)
    if not a or not r:
        return False
    shorter = a if len(a) <= len(r) else r
    if len(shorter) < _MIN_NAME_CHARS:
        return False
    return f" {a} " in f" {r} " or f" {r} " in f" {a} "


def answer_value(extracted: str, answer_type: str) -> float | str | None:
    """Return the value on the final line: a number, a name, or None for no value."""
    if not extracted or scoring.DECLINE_TOKEN in extracted.upper().replace(" ", "_"):
        return None
    if answer_type == "text":
        return extracted if scoring._normalize(extracted) else None
    return scoring.parse_number(extracted)


def matches(extracted: str, answer_type: str, result: Any) -> bool:
    """Say whether a final answer matches any value in one tool result."""
    value = answer_value(extracted, answer_type)
    if value is None:
        return False
    for leaf in leaves(result):
        if isinstance(value, str):
            if isinstance(leaf, str) and name_matches(value, leaf):
                return True
            continue
        number = as_number(leaf)
        if number is not None and number_matches(
            value, decimal_places(extracted), number, percent=answer_type == "percent"
        ):
            return True
    return False


def classify(extracted: str, answer_type: str, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Say where one run's final answer came from.

    Args:
        extracted: The text after ``ANSWER:``, as the scorer read it.
        answer_type: The question's answer type: number, money, percent or text.
        tool_calls: The run's tool calls, each with ``tool`` and, when it
            returned something, ``result``.

    Returns:
        ``{"source", "matched_calls"}``. ``matched_calls`` lists the calls whose
        result held the value, by tool, sequence number and response ID.
    """
    if answer_value(extracted, answer_type) is None:
        return {"source": NO_VALUE, "matched_calls": []}
    matched = []
    for call in tool_calls:
        if call.get("refused") or "result" not in call:
            continue
        if call["tool"] not in (SQL_TOOL, *CONTRACT_TOOLS):
            continue
        if matches(extracted, answer_type, call["result"]):
            matched.append(
                {
                    "tool": call["tool"],
                    "seq": call.get("seq"),
                    "response_id": call.get("response_id", ""),
                }
            )
    from_contract = any(m["tool"] in CONTRACT_TOOLS for m in matched)
    from_sql = any(m["tool"] == SQL_TOOL for m in matched)
    if from_contract and from_sql:
        source = BOTH
    elif from_contract:
        source = CONTRACT
    elif from_sql:
        source = SQL
    else:
        source = NEITHER
    return {"source": source, "matched_calls": matched}
