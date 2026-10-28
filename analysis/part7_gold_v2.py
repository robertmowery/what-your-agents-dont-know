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

"""Part 7: compute the version 2 answer key once, before any agent runs.

Runs the reviewed version 2 gold SQL (``questions/part7_revenue_v2.yaml``) on
the warehouse of record and writes ``results/part7/gold_answers_v2.json``: the
version 1 answers for the 18 questions revenue does not reach, and the version 2
answers for the six it does, each with the version 1 answer and, for the two
margin questions, the "mixed" figure (revenue moved, carrier cost not) as a
decoy. It refuses to run once the file exists: golden set version 2 pins it.

Usage:
    python analysis/part7_gold_v2.py
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from tessaway import questions
from tessaway.warehouse import query

ROOT = Path(__file__).resolve().parents[1]
V2_SQL = ROOT / "questions" / "part7_revenue_v2.yaml"
OUT = ROOT / "results" / "part7" / "gold_answers_v2.json"


def main() -> None:
    """Compute and save the version 2 answers."""
    if OUT.exists():
        raise SystemExit(f"{OUT.relative_to(ROOT)} exists and is frozen as golden set v2.")
    v1 = questions.load_gold()
    spec = yaml.safe_load(V2_SQL.read_text())
    answers = {
        qid: {"gold": entry["gold"], "decoys": list(entry["decoys"])} for qid, entry in v1.items()
    }
    changed = {}
    for item in spec["questions"]:
        qid = item["id"]
        gold = query.scalar(item["gold_sql_v2"])
        decoys = [
            {"label": "revenue version 1 (the answer before the change)", "value": v1[qid]["gold"]}
        ]
        if "mixed_sql" in item:
            decoys.append(
                {
                    "label": "revenue version 2 with carrier cost still on version 1 invoice dates",
                    "value": query.scalar(item["mixed_sql"]),
                }
            )
        decoys += list(v1[qid]["decoys"])
        answers[qid] = {"gold": gold, "decoys": decoys}
        changed[qid] = {
            "v1": v1[qid]["gold"],
            "v2": gold,
            **({"mixed": decoys[1]["value"]} if "mixed_sql" in item else {}),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"version": 2, "question_count": len(answers), "changed": changed, "answers": answers},
            indent=1,
        )
        + "\n"
    )
    for qid, c in changed.items():
        print(qid, c)


if __name__ == "__main__":
    main()
