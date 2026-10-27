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

"""Part 5: the golden set is frozen, and a recomputed answer key is refused.

The cloud test at the end runs the gold SQL against the drifted copy and shows
why: the recomputed key moves with the drift. Run it with ``pytest -m cloud``
while the drift is planted in ``tessaway_wh_p5``.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from tessaway import golden_set, questions, scoring

ROOT = Path(__file__).resolve().parents[1]
DRIFTED_M2 = (
    10134528.91  # part-5-check.md, section 2: M2 read through the definitions after the drift
)


def _copy_repo_files(tmp: Path) -> Path:
    for rel in ("questions/part1.yaml", "questions/golden_set_v1.json", "results/part1/gold_answers.json",
                "data/DEFINITIONS.md"):  # fmt: skip
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp / rel)
    return tmp


def test_the_frozen_set_loads_and_matches_part1() -> None:
    gs = golden_set.load()
    assert gs.version == 1
    assert len(gs.questions) == 24
    assert gs.answers == questions.load_gold()
    assert gs.gold("M2") == 10294019.12


def test_the_manifest_pins_both_files_by_hash() -> None:
    m = golden_set.verify()
    assert m["answers_sha256"] == golden_set.sha256(ROOT / m["answers_file"])
    assert m["questions_sha256"] == golden_set.sha256(ROOT / m["questions_file"])


def test_a_recomputed_answer_key_is_refused(tmp_path: Path) -> None:
    """Writing the drifted M2 into the answers file, as recomputing during the drift would, fails the load."""
    root = _copy_repo_files(tmp_path)
    path = root / "results/part1/gold_answers.json"
    data = json.loads(path.read_text())
    data["answers"]["M2"]["gold"] = DRIFTED_M2
    path.write_text(json.dumps(data, indent=1) + "\n")
    with pytest.raises(golden_set.GoldenSetChangedError):
        golden_set.load(root=root)


def test_recomputing_the_saved_answers_is_refused() -> None:
    with pytest.raises(golden_set.GoldenSetChangedError):
        golden_set.refuse_recompute()
    with pytest.raises(golden_set.GoldenSetChangedError):
        questions.main()


def test_the_drifted_figure_scores_wrong_against_the_frozen_key() -> None:
    gs = golden_set.load()
    m2 = next(q for q in gs.questions if q.id == "M2")
    verdict = scoring.score(m2, gs.gold("M2"), gs.answers["M2"]["decoys"], f"ANSWER: {DRIFTED_M2}")
    assert verdict.outcome == scoring.WRONG
    assert verdict.matched_decoy == ""
    same = scoring.score(m2, DRIFTED_M2, [], f"ANSWER: {DRIFTED_M2}")
    assert same.outcome == scoring.RIGHT  # what a recomputed key would have said


@pytest.mark.cloud
def test_with_the_drift_in_place_the_gold_sql_moves_and_the_frozen_key_does_not() -> None:
    from tessaway import drift

    dataset = os.environ.get("P5_DRIFT_DATASET", "tessaway_wh_p5")
    found = drift.gold_on(dataset)
    if not found["out_of_tolerance"]:
        pytest.skip(f"no drift planted in {dataset}")
    assert set(found["out_of_tolerance"]) >= {"M2", "R3"}
    assert golden_set.load().gold("M2") == 10294019.12
    golden_set.verify()
