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

"""The question set: what an executive asks, and the SQL that answers it correctly.

Each question in ``questions/part1.yaml`` carries:

    id, group      one of four groups: lookup, metric, entity, rule
    question       the words the agent is given, and nothing more
    answer_type    number, money, percent or text
    tolerance      how close a numeric answer must be to count as right
    definitions    which official definitions in data/DEFINITIONS.md decide it
    why            why that definition is the correct one for this question
    gold_sql       hand-written SQL that produces the correct answer
    decoys         plausible wrong readings, each with the SQL that produces it

Agents never see this file or the definitions. The decoys are not shown to
anyone at run time either: the scorer uses them afterward to name which wrong
reading an answer matches.

Usage:
    python -m tessaway.questions     # run every gold and decoy query, save the answers
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = ROOT / "questions" / "part1.yaml"
DEFINITIONS_PATH = ROOT / "data" / "DEFINITIONS.md"
GOLD_PATH = ROOT / "results" / "part1" / "gold_answers.json"

GROUPS = ("lookup", "metric", "entity", "rule")
ANSWER_TYPES = ("number", "money", "percent", "text")
TOLERANCE_KINDS = ("exact", "abs", "rel")


@dataclass(frozen=True)
class Decoy:
    """A plausible wrong reading of a question, and the SQL that produces it."""

    label: str
    sql: str


@dataclass(frozen=True)
class Question:
    """One question, its correct answer's SQL, and how answers are judged."""

    id: str
    group: str
    question: str
    answer_type: str
    tolerance_kind: str
    tolerance_value: float
    definitions: tuple[str, ...]
    why: str
    gold_sql: str
    decoys: tuple[Decoy, ...] = ()
    # Text answers only: any of ``accept`` must appear, and none of ``reject``.
    accept: tuple[str, ...] = ()
    reject: tuple[str, ...] = field(default=())


def definition_ids(path: Path = DEFINITIONS_PATH) -> set[str]:
    """Return the ids of the official definitions, read from their headings."""
    return set(re.findall(r"^## `([a-z_]+)`", path.read_text(), flags=re.MULTILINE))


def load(path: Path = QUESTIONS_PATH) -> list[Question]:
    """Read and validate the question file."""
    known = definition_ids()
    questions: list[Question] = []
    seen: set[str] = set()
    for raw in yaml.safe_load(path.read_text()):
        tolerance = raw["tolerance"]
        question = Question(
            id=raw["id"],
            group=raw["group"],
            question=raw["question"],
            answer_type=raw["answer_type"],
            tolerance_kind=tolerance["kind"],
            tolerance_value=float(tolerance.get("value", 0.0)),
            definitions=tuple(raw.get("definitions", [])),
            why=raw["why"],
            gold_sql=raw["gold_sql"],
            decoys=tuple(Decoy(d["label"], d["sql"]) for d in raw.get("decoys", [])),
            accept=tuple(raw.get("accept", [])),
            reject=tuple(raw.get("reject", [])),
        )
        if question.id in seen:
            raise ValueError(f"duplicate question id {question.id}")
        if question.group not in GROUPS:
            raise ValueError(f"{question.id}: unknown group {question.group}")
        if question.answer_type not in ANSWER_TYPES:
            raise ValueError(f"{question.id}: unknown answer type {question.answer_type}")
        if question.tolerance_kind not in TOLERANCE_KINDS:
            raise ValueError(f"{question.id}: unknown tolerance {question.tolerance_kind}")
        missing = set(question.definitions) - known
        if missing:
            raise ValueError(f"{question.id}: no such definition(s) {sorted(missing)}")
        seen.add(question.id)
        questions.append(question)
    return questions


def compute_gold(questions: list[Question]) -> dict[str, dict[str, Any]]:
    """Run every gold and decoy query on BigQuery and return the answers."""
    from tessaway.warehouse import query  # imported here so loading needs no cloud access

    answers: dict[str, dict[str, Any]] = {}
    for question in questions:
        answers[question.id] = {
            "gold": query.scalar(question.gold_sql),
            "decoys": [
                {"label": decoy.label, "value": query.scalar(decoy.sql)}
                for decoy in question.decoys
            ],
        }
    return answers


def load_gold(path: Path = GOLD_PATH) -> dict[str, dict[str, Any]]:
    """Read the saved gold answers."""
    return dict(json.loads(path.read_text())["answers"])


def main() -> None:
    """Compute and save the gold answers, and print them beside the decoys."""
    from tessaway.warehouse import generate

    questions = load()
    answers = compute_gold(questions)
    GOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLD_PATH.write_text(
        json.dumps({"seed": generate.SEED, "question_count": len(questions), "answers": answers},
                   indent=1)
        + "\n"
    )  # fmt: skip
    for question in questions:
        entry = answers[question.id]
        print(f"{question.id} [{question.group}] {question.question}")
        print(f"     gold: {entry['gold']}")
        for decoy in entry["decoys"]:
            print(f"     decoy: {decoy['value']}  ({decoy['label']})")
    print(f"saved {GOLD_PATH}")


if __name__ == "__main__":
    main()
