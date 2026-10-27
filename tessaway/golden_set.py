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

"""The golden set: the 24 Part 1 questions and their correct answers, frozen and versioned.

Part 5 runs the question set as a standing check. What makes it a check rather
than a rerun is that the answer key does not move. ``questions/golden_set_v1.json``
pins the question file and the saved answers (``results/part1/gold_answers.json``)
by SHA-256, and :func:`load` refuses to return answers whose file no longer
matches. The gold SQL is kept for review, but it is not run again while the check
is in use: if a source column changes meaning, the gold SQL reads the changed
column the same way an agent does, and a recomputed answer key would agree with
the wrong answer.

A later version (Part 7 plans one for a planned definition change) is a new
manifest beside this one with its own answers file; version 1 stays as it is.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tessaway import questions

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "questions"
CURRENT_VERSION = 1


class GoldenSetChangedError(RuntimeError):
    """A pinned file no longer matches its hash: the answer key moved."""


@dataclass(frozen=True)
class GoldenSet:
    """One frozen version of the golden set."""

    version: int
    owner: str
    frozen_on: str
    questions: list[questions.Question]
    answers: dict[str, dict[str, Any]]  # question id -> {"gold", "decoys"}

    def gold(self, question_id: str) -> Any:
        """The correct answer for one question."""
        return self.answers[question_id]["gold"]


def manifest_path(version: int = CURRENT_VERSION) -> Path:
    """Where a version's manifest lives."""
    return MANIFESTS / f"golden_set_v{version}.json"


def manifest(version: int = CURRENT_VERSION) -> dict[str, Any]:
    """Read a version's manifest."""
    return dict(json.loads(manifest_path(version).read_text()))


def sha256(path: Path) -> str:
    """The SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(version: int = CURRENT_VERSION, root: Path = ROOT) -> dict[str, Any]:
    """Check both pinned files against the manifest and raise if either moved."""
    m = manifest(version)
    for key in ("questions", "answers"):
        path = root / m[f"{key}_file"]
        found = sha256(path)
        if found != m[f"{key}_sha256"]:
            raise GoldenSetChangedError(
                f"golden set v{version}: {m[f'{key}_file']} has SHA-256 {found[:12]},"
                f" the manifest pins {m[f'{key}_sha256'][:12]}. The answer key is frozen;"
                " a changed key is a new version, never an edit."
            )
    return m


def load(version: int = CURRENT_VERSION, root: Path = ROOT) -> GoldenSet:
    """Return the frozen golden set, after checking that neither pinned file moved."""
    m = verify(version, root)
    asked = questions.load(root / m["questions_file"])
    answers = questions.load_gold(root / m["answers_file"])
    if sorted(answers) != sorted(q.id for q in asked):
        raise GoldenSetChangedError(f"golden set v{version}: questions and answers do not match")
    return GoldenSet(
        version=int(m["version"]),
        owner=str(m["owner"]),
        frozen_on=str(m["frozen_on"]),
        questions=asked,
        answers=answers,
    )


def refuse_recompute(version: int = CURRENT_VERSION, root: Path = ROOT) -> None:
    """Stop anything that would write a new answer key over a frozen one.

    ``python -m tessaway.questions`` recomputes the gold answers from the
    warehouse and saves them. Once a golden set pins that file, doing so would
    move the key the check scores against, so it is refused.
    """
    m = manifest(version)
    if (root / m["answers_file"]).resolve() == questions.GOLD_PATH.resolve():
        raise GoldenSetChangedError(
            f"{m['answers_file']} is frozen as golden set v{version}. Recomputing it from"
            " the warehouse would score a changed column's answers against themselves."
            " Write a new version instead."
        )
