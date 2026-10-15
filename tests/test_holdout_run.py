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

"""The held-out run script and coverage check, tested with no model and no cloud call."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import run_holdout
import run_part2
from tessaway import questions
from tessaway.agents import adk_layer_agent, layer_prompt, prompt
from tessaway.layers import semantic

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import holdout_coverage as coverage

HOLDOUT = questions.load(run_holdout.QUESTIONS_PATH)
BY_ID = {q.id: q for q in HOLDOUT}
GOLD = questions.load_gold(run_holdout.GOLD_PATH)
SQL, METRIC = prompt.TOOL_NAME, layer_prompt.SEMANTIC_TOOL


def reply(columns: list[str], rows: list[list[Any]], truncated: bool = False) -> dict[str, Any]:
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}


# --- the coverage check ---------------------------------------------------------------


def test_every_held_out_question_has_coverage_attempts() -> None:
    assert set(coverage.ATTEMPTS) == set(BY_ID)


def test_coverage_attempts_use_only_what_the_layer_defines() -> None:
    catalog = semantic.catalog()
    metrics = {m["name"] for m in catalog["metrics"]}
    dimensions = {d["name"] for d in catalog["dimensions"]}
    for qid, attempts in coverage.ATTEMPTS.items():
        for _kind, _what, requests, _read in attempts:
            for request in requests:
                assert set(request["metrics"]) <= metrics, qid
                assert set(request.get("group_by", [])) <= dimensions, qid


def test_a_control_attempt_is_never_the_class_even_when_it_matches() -> None:
    attempts: list[coverage.Attempt] = [
        (coverage.CONTROL, "bare", [{"metrics": ["m"]}], coverage.first("m")),
        (coverage.FILTER, "filtered", [{"metrics": ["m"], "where": ["x"]}], coverage.first("m")),
    ]
    result = coverage.classify(BY_ID["H4"], 408.74, attempts, lambda _: reply(["m"], [[409.0]]))
    assert result["class"] == coverage.FILTER
    assert result["a_query_that_drops_a_condition_also_scores_right"] is True


def test_the_first_faithful_attempt_that_matches_gives_the_class() -> None:
    def run(request: dict[str, Any]) -> dict[str, Any]:
        return reply(["m"], [[216 if request.get("where") else 6989]])

    attempts: list[coverage.Attempt] = [
        (coverage.CONTROL, "bare", [{"metrics": ["m"]}], coverage.first("m")),
        (coverage.FILTER, "filtered", [{"metrics": ["m"], "where": ["x"]}], coverage.first("m")),
    ]
    result = coverage.classify(BY_ID["H8"], 216, attempts, run)
    assert result["class"] == coverage.FILTER
    assert result["metric_queries_needed"] == 1
    assert result["a_query_that_drops_a_condition_also_scores_right"] is False


def test_a_question_no_attempt_reproduces_is_not_answerable() -> None:
    attempts: list[coverage.Attempt] = [
        (coverage.FILTER, "wrong", [{"metrics": ["m"]}], coverage.first("m")),
        (coverage.SEVERAL, "errors", [{"metrics": ["m"]}], coverage.first("m")),
    ]
    replies = iter([reply(["m"], [[197]]), {"error": "no such metric"}])
    result = coverage.classify(BY_ID["H11"], 27, attempts, lambda _: next(replies))
    assert result["class"] == coverage.NONE
    assert result["query_used"] is None
    assert result["attempts"][1]["error"] == "no such metric"


def test_the_arithmetic_on_rows() -> None:
    flags = reply(["tender__is_cross_border", "revenue"], [[True, 10.0], [False, 90.0]])
    assert coverage.share_of_true([flags]) == 10.0
    by_customer = reply(["c", "revenue"], [["a", 300000.0], ["b", 250000.0], ["c", 1.0]])
    assert coverage.count_over_250k([by_customer]) == 1
    days = reply(
        ["metric_time__day", "delivered_loads"],
        [["2026-07-03T00:00:00", 5], ["2026-07-04T00:00:00", 7], ["2026-07-05", 2]],
    )
    assert coverage.weekend_total([days]) == 9
    top = reply(["c", "revenue"], [["a", 30.0], ["b", 20.0]])
    assert coverage.top_five_share([top, reply(["revenue"], [[200.0]])]) == 25.0


def test_the_saved_coverage_covers_all_twelve_questions_with_known_classes() -> None:
    saved = json.loads(run_holdout.COVERAGE_PATH.read_text())
    classes = run_holdout.coverage_classes()
    assert set(classes) == set(BY_ID)
    assert set(classes.values()) <= set(run_holdout.CLASSES)
    assert sum(saved["counts"].values()) == 12
    for entry in saved["questions"]:
        assert (entry["query_used"] is None) == (entry["class"] == coverage.NONE)


def test_the_coverage_classes_mean_the_same_in_both_files() -> None:
    assert run_holdout.CLASSES == coverage.CLASSES
    assert set(run_holdout.ONE_QUERY_CLASSES) == {coverage.ONE, coverage.FILTER}


# --- the run script -------------------------------------------------------------------


def test_the_semantic_configuration_is_part_2s_and_the_baseline_has_no_layer() -> None:
    assert run_holdout.CONFIGS[run_holdout.SEMANTIC] == run_part2.LAYER_CONFIGS["flash_semantic"]
    assert run_holdout.CONFIGS[run_holdout.BASELINE] == ()
    assert run_holdout.BASE.model == "gemini-3.8-flash"
    assert adk_layer_agent.max_model_calls(()) == prompt.MAX_MODEL_CALLS


def test_results_go_under_holdout_and_never_under_part_1_or_part_2() -> None:
    assert run_holdout.RESULTS.name == "holdout"
    assert run_part2.RESULTS not in (run_holdout.RESULTS, *run_holdout.RESULTS.parents)


def baseline_run(text: str, queries: int = 2) -> prompt.AgentRun:
    return prompt.AgentRun(
        final_text=text,
        seconds=1.0,
        model_calls=queries + 1,
        input_tokens=1000,
        output_tokens=100,
        queries=[{"sql": f"SELECT {n}", "row_count": 1} for n in range(queries)],
    )


def layer_run(text: str, tools: list[str]) -> adk_layer_agent.LayerAgentRun:
    return adk_layer_agent.LayerAgentRun(
        final_text=text,
        seconds=1.0,
        model_calls=len(tools) + 1,
        input_tokens=2000,
        output_tokens=100,
        queries=[{"sql": "SELECT 1"} for tool in tools if tool == SQL],
        tool_calls=[{"seq": n + 1, "tool": tool, "arguments": {}} for n, tool in enumerate(tools)],
    )


def test_a_baseline_row_is_scored_by_the_part_1_scorer_and_carries_tool_fields() -> None:
    row = run_holdout.to_row("baseline", BY_ID["H8"], 0, baseline_run("ANSWER: 216"), GOLD["H8"])
    assert (row["config"], row["outcome"], row["layers"]) == ("baseline", "right", [])
    assert row["tool_call_counts"] == {SQL: 2}
    assert row["tools_in_order"] == [SQL, SQL]
    wrong = run_holdout.to_row("baseline", BY_ID["H8"], 1, baseline_run("ANSWER: 233"), GOLD["H8"])
    assert wrong["outcome"] == "confidently_wrong"
    assert wrong["matched_decoy"] == "every load row for the customer's sites"


def test_a_semantic_row_is_the_part_2_row() -> None:
    run = layer_run("ANSWER: NEEDS_CLARIFICATION", [METRIC, SQL])
    row = run_holdout.to_row("flash_semantic", BY_ID["H11"], 0, run, GOLD["H11"])
    assert row["outcome"] == "declined"
    assert row["layers"] == ["semantic"]
    assert row["tool_call_counts"] == {METRIC: 1, SQL: 1}


def rows_for(plan: list[tuple[str, str, list[str]]]) -> list[dict[str, Any]]:
    return [
        run_holdout.to_row("flash_semantic", BY_ID[qid], n, layer_run(text, tools), GOLD[qid])
        for n, (qid, text, tools) in enumerate(plan)
    ]


def test_the_bypass_count_is_sql_on_a_question_one_metric_query_answers() -> None:
    classes = {"H8": "metric_plus_filter", "H7": "several_or_arithmetic", "H11": "not_answerable"}
    rows = rows_for(
        [
            ("H8", "ANSWER: 216", [METRIC]),
            ("H8", "ANSWER: 216", [METRIC, SQL]),
            ("H8", "ANSWER: 233", [SQL]),
            ("H7", "ANSWER: 30.93", [METRIC, SQL]),
            ("H11", "ANSWER: 197", [METRIC]),
        ]
    )
    use = run_holdout.tool_use(rows, classes)
    around = use["went_around_the_semantic_layer"]
    assert around["runs_on_such_questions"] == 3
    assert around["runs_that_ran_sql"] == 2
    assert around["of_which_never_called_the_metric_tool"] == 1
    assert around["outcomes_when_sql_was_run"]["right"] == 1
    assert around["outcomes_from_metrics_alone"]["right"] == 1
    assert use["by_coverage_class"]["not_answerable"]["metric_tool_only"] == 1
    assert use["all_runs"] == {**use["all_runs"], "runs": 5, "both_tools": 2, "sql_only": 1}
    shares = run_holdout.by_class(rows, classes)
    assert shares["metric_plus_filter"]["right"] == 2
    assert shares["not_answerable"]["confidently_wrong"] == 1


def test_answers_given_lists_each_run_in_question_order() -> None:
    rows = rows_for([("H10", "ANSWER: 139", [METRIC]), ("H2", "ANSWER: 13.23", [METRIC])])
    given = run_holdout.answers_given(rows)
    assert list(given) == ["H2", "H10"]
    assert given["H2"][0]["matched_decoy"] == "the whole company, own fleet included"


def test_the_run_loop_saves_resumes_stops_at_the_budget_and_repeats_a_failure_once(
    tmp_path: Path,
) -> None:
    asked = [BY_ID["H5"], BY_ID["H8"]]
    seen: list[str] = []

    async def asker(name: str, question: questions.Question) -> prompt.AgentRun:
        seen.append(question.id)
        if question.id == "H5" and seen.count("H5") == 1:
            return prompt.AgentRun(error="boom")
        return baseline_run("ANSWER: 216")

    def go(**extra: Any) -> None:
        options: dict[str, Any] = {
            "runs": 1, "concurrency": 1, "budget_usd": 5.0, "out": tmp_path,
            "retry_failed": False, "asker": asker, "spend_root": tmp_path,
        }  # fmt: skip
        asyncio.run(run_holdout.run_config("baseline", asked, GOLD, **{**options, **extra}))

    go()
    path = tmp_path / "runs" / "baseline.jsonl"
    assert len(path.read_text().splitlines()) == 2
    go()  # nothing left to do
    assert len(seen) == 2
    go(retry_failed=True)  # the failed H5 run again
    go(retry_failed=True)  # and never a third time
    assert seen == ["H5", "H8", "H5"]
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(r["question_id"], r["outcome"]) for r in lines] == [
        ("H5", "no_answer"), ("H8", "right"), ("H5", "confidently_wrong"),
    ]  # fmt: skip
    assert lines[2]["retry_of_failed"] is True
    go(runs=2, budget_usd=0.0)  # over budget: no new run starts
    assert len(seen) == 3


def test_the_ledger_gains_a_holdout_entry_and_keeps_part_2(tmp_path: Path) -> None:
    ledger = tmp_path / "series_spend.json"
    part2 = {"line_usd": 9.6, "spent_usd": 11.7682}
    ledger.write_text(
        json.dumps(
            {
                "note": "n",
                "approved_usd_parts_2_to_7": 35.0,
                "hard_cap_usd_parts_2_to_7": 45.0,
                "parts": {"2": part2},
            }
        )
    )
    runs = tmp_path / "holdout" / "smoke" / "runs"
    runs.mkdir(parents=True)
    (runs / "baseline.jsonl").write_text(json.dumps({"cost_usd": 0.5, "bigquery_usd": 0.25}) + "\n")
    written = run_holdout.write_ledger(ledger, tmp_path / "holdout")
    assert written["parts"]["2"] == part2
    assert written["parts"]["holdout"]["spent_usd"] == 0.75
    assert written["parts"]["holdout"]["by_folder"]["smoke"]["runs"] == 1
    assert written["spent_usd_parts_2_to_7"] == 12.5182
    assert written["remaining_to_hard_cap_usd"] == 32.4818
    assert written["note"] == "n"


def test_the_summary_is_written_from_saved_runs(tmp_path: Path) -> None:
    saved = json.loads(run_holdout.COVERAGE_PATH.read_text())
    classes = run_holdout.coverage_classes()
    plan = {
        "baseline": lambda q: baseline_run("ANSWER: NEEDS_CLARIFICATION"),
        "flash_semantic": lambda q: layer_run(f"ANSWER: {GOLD[q.id]['gold']}", [METRIC]),
    }
    (tmp_path / "runs").mkdir()
    for name, make in plan.items():
        rows = [run_holdout.to_row(name, q, 0, make(q), GOLD[q.id]) for q in HOLDOUT]
        (tmp_path / "runs" / f"{name}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows)
        )
    blocks = [
        run_holdout.write_config_file(name, HOLDOUT, GOLD, classes, runs=1, out=tmp_path)
        for name in run_holdout.CONFIGS
    ]
    assert all(b is not None and b["complete"] for b in blocks)
    run_holdout.write_summary([b for b in blocks if b], HOLDOUT, GOLD, saved, tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["change_semantic_vs_baseline_points"]["overall"] == {
        "right": 100.0, "confidently_wrong": 0.0, "declined": -100.0,
    }  # fmt: skip
    assert (
        summary["configurations"][1]["tool_use"]["went_around_the_semantic_layer"][
            "runs_that_ran_sql"
        ]
        == 0
    )
    text = (tmp_path / "summary.md").read_text()
    assert "## By coverage class" in text and "| H12 | rule |" in text
    assert "12 held-out questions" in text


# --- the article numbers --------------------------------------------------------------


def test_article_numbers_are_derived_from_saved_rows_alone() -> None:
    import holdout_article_numbers as numbers

    saved = json.loads(run_holdout.COVERAGE_PATH.read_text())
    metric_call = {
        "seq": 1,
        "tool": METRIC,
        "arguments": {
            "metrics": ["delivered_loads_not_billable"],
            "where": ["x = 1"],
            "start_date": "2026-07-01",
            "end_date": "2026-09-30",
            "limit": 50,
        },
        "row_count": 1,
    }
    rows: dict[str, list[dict[str, Any]]] = {"baseline": [], "flash_semantic": []}
    for trial in range(3):
        for q in HOLDOUT:
            rows["baseline"].append(
                run_holdout.to_row(
                    "baseline", q, trial, baseline_run("ANSWER: NEEDS_CLARIFICATION"), GOLD[q.id]
                )
            )
            answer = 197 if q.id == "H11" else GOLD[q.id]["gold"]
            run = layer_run(f"ANSWER: {answer}", [METRIC])
            run.tool_calls = [metric_call]
            rows["flash_semantic"].append(
                run_holdout.to_row("flash_semantic", q, trial, run, GOLD[q.id])
            )
    report = numbers.build(rows, saved, HOLDOUT, {})
    assert report["complete"] == {"baseline": True, "flash_semantic": True}
    overall = report["configurations"]["flash_semantic"]["overall"]
    assert (overall["right"], overall["confidently_wrong"], overall["right_pct"]) == (33, 3, 91.7)
    assert report["change_baseline_to_semantic_points"]["overall"]["right"] == 91.7
    assert (
        report["configurations"]["flash_semantic"]["by_coverage_class"]["not_answerable"][
            "confidently_wrong"
        ]
        == 3
    )
    failures = report["semantic_runs_not_right"]
    assert [f["question_id"] for f in failures] == ["H11", "H11", "H11"]
    assert failures[0]["metrics_asked_for"] == ["delivered_loads_not_billable"]
    assert failures[0]["filters_used"] == ["x = 1"]
    assert failures[0]["tool_calls"][0]["period"] == ["2026-07-01", "2026-09-30"]
    assert failures[0]["matched_decoy"].startswith("every delivered load that cannot be billed")
    assert report["per_question"][10]["flash_semantic"]["answers"] == ["197", "197", "197"]
    assert report["without_the_flawed_questions"]["questions_left_out"] == ["H4"]
    assert report["without_the_flawed_questions"]["flash_semantic"]["runs"] == 33
    read = {p["claim"]: p["holds"] for p in report["predictions_read_against_the_runs"]}
    assert read["The layer helps on questions it was not built for"] is True
    assert read["The layer generalizes as well as Part 2 suggested"] is False
    assert read["The layer's failures are the ones coverage predicts"] is True


def test_a_sql_call_is_described_by_its_statement() -> None:
    import holdout_article_numbers as numbers

    call = {"seq": 2, "tool": SQL, "arguments": {"sql": "SELECT 1\n  FROM t"}, "error": "bad"}
    assert numbers.describe_call(call) == {
        "seq": 2, "tool": SQL, "sql": "SELECT 1 FROM t", "error": "bad",
    }  # fmt: skip
