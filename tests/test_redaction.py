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

"""The Google Cloud project ID never reaches a Part 2 results file or export.

No model and no cloud call: the redaction is plain string work on saved files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import run_part2
from tessaway import config
from tessaway.layers import semantic

ROOT = Path(__file__).resolve().parents[1]
FAKE = "my-test-project-123"


def test_the_project_id_is_replaced_in_every_string_inside_a_row() -> None:
    row = {
        "sql": f"SELECT 1 FROM `{FAKE}`.`ds`.`t`",
        "calls": [{"generated_sql": f"FROM `{FAKE}`.x", "row_count": 3}],
        "cost_usd": 0.01,
        "timed_out": False,
    }
    clean = config.redact_project(row, FAKE)
    assert FAKE not in json.dumps(clean)
    assert clean["sql"] == "SELECT 1 FROM `PROJECT`.`ds`.`t`"
    assert clean["calls"][0]["row_count"] == 3
    assert clean["cost_usd"] == 0.01 and clean["timed_out"] is False


def test_with_no_project_set_nothing_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    row = {"sql": f"FROM `{FAKE}`.x"}
    assert config.redact_project(row) == row


def test_saved_runs_are_rewritten_in_place_and_every_line_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", FAKE)
    runs = tmp_path / "runs"
    runs.mkdir()
    lines = [
        {"question_id": "M1", "trial": 0, "tool_calls": [{"generated_sql": f"FROM `{FAKE}`.a"}]},
        {"question_id": "M1", "trial": 0, "retry_of_failed": True, "tool_calls": []},
        {"question_id": "L1", "trial": 0, "answer_text": "Green Bay"},
    ]
    path = runs / "flash_semantic.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    assert run_part2.redact_saved_runs(tmp_path) == 1
    saved = path.read_text().splitlines()
    assert len(saved) == 3
    assert FAKE not in path.read_text()
    assert saved[1:] == [json.dumps(line) for line in lines[1:]]
    assert run_part2.redact_saved_runs(tmp_path) == 0


def test_the_osi_export_is_dbt_output_with_only_the_project_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", FAKE)
    target, export = tmp_path / "target.json", tmp_path / "exports" / "osi.json"
    target.write_text(json.dumps({"version": "0.1.1", "source": f"`{FAKE}`.`ds`.`loads`"}))
    monkeypatch.setattr(semantic, "OSI_TARGET_PATH", target)
    monkeypatch.setattr(semantic, "OSI_EXPORT_PATH", export)
    semantic.write_export()
    assert export.read_text() == target.read_text().replace(FAKE, "PROJECT")


def test_no_committed_part2_or_holdout_results_file_or_export_names_the_project() -> None:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project or project == "your-project-id":
        pytest.skip("no project set, so there is no ID to look for")
    files = [
        *sorted((ROOT / "results" / "part2").rglob("*.json*")),
        *sorted((ROOT / "results" / "holdout").rglob("*.json*")),
        *sorted((ROOT / "semantic_layer" / "exports").glob("*")),
    ]
    assert files
    named = [str(f.relative_to(ROOT)) for f in files if project in f.read_text()]
    assert named == []
