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

"""Runs the Part 5 experiment from the operator's side, and writes every number the articles use.

Part 5 turns the 24 Part 1 questions into a standing check: a frozen golden set
(``tessaway/golden_set.py``), run by a Cloud Run job (``golden_check/job.py``,
``infra/part5``) through the same agent and contract as Part 4's available
configuration, with an OpenTelemetry trace per run (``tessaway/tracing.py``)
and an alert rule written before the drift (``tessaway/alert_rule.py``). Then
a drift is planted in a copy of the warehouse (``tessaway/drift.py``): billing
reloads 2026 with Canadian amounts already in US dollars, and ``curr_cd`` still
says ``CAD``.

    baseline    Part 4's available run, reused (72 runs, no new spend)
    drift       three executions of the job with the drift in place (72 runs)
    after_fix   one execution after the revert (24 runs)

The job is started by hand; the nightly schedule is defined in Terraform and paused.
Predictions: ``results/part5/predictions.md``, committed before the first scored run.

Usage:
    python run_part5.py --write-baseline                    # the alert rule's baseline, before any run
    python run_part5.py --execute drift 1 --dataset tessaway_wh_p5
    python run_part5.py --execute smoke 1 --dataset tessaway_wh_p5 --questions L1,M1,M2,R3
    python run_part5.py --pull drift                        # copy records, traces, alerts from the bucket
    python run_part5.py --pull smoke --out smoke
    python run_part5.py --record-drift restated --dataset tessaway_wh_p5   # status and recomputed gold
    python run_part5.py --read-server-log --since 2026-10-14T00:00:00Z
    python run_part5.py --summarize-only

Files written under results/part5 (or results/part5/NAME): runs/<phase>.jsonl,
traces/<phase>.jsonl, alerts/<phase>.json, drift/<name>.json, server_log.jsonl,
summary.json, summary.md, and the Part 5 lines of results/series_spend.json.
Nothing written names the Google Cloud project, the service URL or an email
address: ``run_part4.clean`` runs over every saved line.
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_part2
import run_part3
import run_part4
from tessaway import alert_rule, config, drift, golden_set, registry, scoring, tracing

ROOT = Path(__file__).parent
RESULTS = ROOT / "results" / "part5"
PART3_AVAILABLE = ROOT / "results" / "part3" / "runs" / "available.jsonl"
PART4_AVAILABLE = ROOT / "results" / "part4" / "runs" / "available.jsonl"
PART4_LOG = ROOT / "results" / "part4" / "server_log.jsonl"
LEDGER_PATH = run_part2.LEDGER_PATH
PART5_DIR = ROOT / "infra" / "part5"
JOB = "tessaway-golden-check"
REGION = "us-central1"
DATASET = "tessaway_wh_p5"
STOP_LINE_USD = 7.0
PLANNED_USD = 3.95
LINE_USD = 4.80
DRIFTED = (
    "M2",
    "M3",
    "E3",
    "R3",
)  # out of tolerance with history restated (part-5-check.md, section 2)
PHASES = ("drift", "after_fix")
OWNER_OF_DRIFT = "Controller"
SIGNALS = {
    "seconds": "latency per run (s)",
    "cost_usd": "model cost per run ($)",
    "input_tokens_total": "input tokens per run",
    "output_tokens": "output tokens per run",
    "query_count": "SQL queries per run",
    "contract_calls": "contract calls per run",
    "model_calls": "model calls per run",
}
BAND_SIGNALS = ("seconds", "cost_usd", "input_tokens_total", "query_count")
MAX_FAILED_PER_EXECUTION = 1


# --- reading -----------------------------------------------------------------------------


def rows_of(path: Path) -> list[dict[str, Any]]:
    """Saved runs, a later line for the same question and trial replacing an earlier one."""
    return run_part3.rows_in(path)


def phase_rows(out: Path = RESULTS) -> dict[str, list[dict[str, Any]]]:
    """Every phase's runs: the reused baseline, Part 3's pass, and Part 5's own."""
    found = {
        "baseline": rows_of(PART4_AVAILABLE),
        "part3_available": rows_of(PART3_AVAILABLE),
    }
    for phase in PHASES:
        found[phase] = rows_of(out / "runs" / f"{phase}.jsonl")
    return found


def executions(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Runs grouped by execution (trial 0 is execution 1)."""
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(int(r["trial"]) + 1, []).append(r)
    return dict(sorted(out.items()))


def failed(row: dict[str, Any]) -> bool:
    """The run ended in an error or a timeout: what an uptime dashboard counts."""
    return bool(row.get("error")) or bool(row.get("timed_out"))


# --- the job, from the operator's side ---------------------------------------------------


def _tf_output(root: Path, name: str) -> str:
    found = subprocess.run(
        ["terraform", "output", "-raw", name], cwd=root, capture_output=True, text=True, check=True
    )
    return found.stdout.strip()


def execute(
    phase: str,
    execution: int,
    dataset: str,
    questions_arg: str,
    budget: float,
    retry_failed: bool = False,
) -> int:
    """Start one execution of the job by hand and wait for it to finish."""
    args = ["--phase", phase, "--execution", str(execution), "--budget-usd", f"{budget:.2f}"]
    if questions_arg:
        args += ["--questions", questions_arg]
    if retry_failed:
        args.append("--retry-failed")
    token = run_part3._token_file()
    try:
        found = subprocess.run(
            [
                "gcloud", "run", "jobs", "execute", JOB,
                "--project", config.project(), "--region", REGION,
                "--access-token-file", token, "--wait",
                "--args", "^@^" + "@".join(args),
                "--update-env-vars", f"BQ_DATASET={dataset}",
            ],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
    finally:
        os.remove(token)
    print(run_part4.clean(found.stdout[-2000:]), run_part4.clean(found.stderr[-2000:]))
    return found.returncode


def pull(phase: str, out: Path) -> dict[str, int]:
    """Copy one phase's records, traces and alerts from the bucket, cleaned, into ``out``."""
    from google.cloud import storage

    bucket = storage.Client(project=config.project()).bucket(
        _tf_output(PART5_DIR, "results_bucket")
    )
    runs, traces, alerts = [], [], []
    for blob in sorted(bucket.list_blobs(prefix=f"part5/{phase}/"), key=lambda b: b.name):
        text = run_part4.clean(blob.download_as_text())
        if "/runs/" in blob.name:
            runs.append(json.loads(text))
        elif "/traces/" in blob.name:
            traces.append(json.loads(text))
        elif blob.name.endswith("alert.json"):
            alerts.append(json.loads(text))
    order = {q.id: i for i, q in enumerate(golden_set.load().questions)}
    # A failed first try sorts before its retry, so the retry is the line that counts.
    runs.sort(key=lambda r: (r["trial"], order[r["question_id"]], bool(r.get("retry_of_failed"))))
    traces.sort(key=lambda t: (t["trial"], order[t["question_id"]]))
    alerts.sort(key=lambda a: a["execution"])
    for folder, items, name in (
        ("runs", runs, f"{phase}.jsonl"),
        ("traces", traces, f"{phase}.jsonl"),
    ):
        (out / folder).mkdir(parents=True, exist_ok=True)
        (out / folder / name).write_text("".join(json.dumps(i) + "\n" for i in items))
    (out / "alerts").mkdir(parents=True, exist_ok=True)
    (out / "alerts" / f"{phase}.json").write_text(json.dumps(alerts, indent=1) + "\n")
    return {"runs": len(runs), "traces": len(traces), "alerts": len(alerts)}


def record_drift(name: str, dataset: str, out: Path = RESULTS) -> dict[str, Any]:
    """Save the copy's state and what the gold SQL would say on it, under drift/<name>.json."""
    found = {
        "name": name,
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": drift.status(dataset),
        "gold_recomputed_on_copy": drift.gold_on(dataset),
    }
    path = out / "drift" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(run_part4.clean(json.dumps(found, indent=1, default=str)) + "\n")
    return found


def save_alert_log(since: str, out: Path = RESULTS) -> int:
    """Read every verdict the job raised back from Cloud Logging, in order, cleaned.

    The job writes ``alert.json`` per execution, and a retry pass on the same
    execution writes it again; the log keeps every verdict as it was raised.
    """
    log_filter = (
        'resource.type="cloud_run_job"'
        f' AND resource.labels.job_name="{JOB}"'
        ' AND (jsonPayload.event="golden_set_alert" OR jsonPayload.event="golden_set_quiet")'
        f' AND timestamp>="{since}"'
    )
    token = run_part3._token_file()
    try:
        found = subprocess.run(
            ["gcloud", "logging", "read", log_filter, "--project", config.project(),
             "--access-token-file", token, "--format=json", "--order=asc", "--limit=1000"],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
    finally:
        os.remove(token)
    lines = []
    for entry in json.loads(found.stdout or "[]"):
        p = dict(entry.get("jsonPayload") or {})
        p["log_timestamp"] = entry.get("timestamp", "")
        p["job_execution"] = (entry.get("labels") or {}).get(
            "run.googleapis.com/execution_name", ""
        )
        lines.append(run_part4.cleaned(p))
    (out / "alerts").mkdir(parents=True, exist_ok=True)
    (out / "alerts" / "raised.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    return len(lines)


def save_server_log(since: str, out: Path = RESULTS) -> int:
    """Read the context server's call log back from Cloud Logging, cleaned."""
    lines = [run_part4.cleaned(line) for line in run_part3.read_server_log(since)]
    (out / "server_log.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    return len(lines)


# --- the measurements ----------------------------------------------------------------------


def _stats(values: list[float], digits: int = 4) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), digits),
        "sd": round(statistics.stdev(values), digits) if len(values) > 1 else 0.0,
        "median": round(statistics.median(values), digits),
        "min": round(min(values), digits),
        "max": round(max(values), digits),
    }


def operational(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The signals a dashboard shows, for one set of runs."""
    out: dict[str, Any] = {
        "runs": len(rows),
        "failed_runs": sum(1 for r in rows if failed(r)),
        "error_runs": sum(1 for r in rows if r.get("error")),
        "timed_out_runs": sum(1 for r in rows if r.get("timed_out")),
        "failed_share": round(sum(1 for r in rows if failed(r)) / len(rows), 4) if rows else None,
        "total_cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in rows), 4),
    }
    for key in SIGNALS:
        out[key] = _stats([float(r.get(key) or 0) for r in rows])
    return out


def bands(baseline: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """The green band for each signal: the baseline's per-run mean plus or minus one standard deviation."""
    found = {}
    for key in BAND_SIGNALS:
        s = _stats([float(r.get(key) or 0) for r in baseline])
        found[key] = {"low": round(s["mean"] - s["sd"], 4), "high": round(s["mean"] + s["sd"], 4),
                      "mean": s["mean"], "sd": s["sd"]}  # fmt: skip
    return found


def attempts(path: Path) -> list[dict[str, Any]]:
    """Every run as executed, a failed first try and its retry both included: what a dashboard counts."""
    return run_part3.read_jsonl(path)


def phase_attempts(out: Path = RESULTS) -> dict[str, list[dict[str, Any]]]:
    """Every attempt, by phase."""
    found = {"baseline": attempts(PART4_AVAILABLE), "part3_available": attempts(PART3_AVAILABLE)}
    for phase in PHASES:
        found[phase] = attempts(out / "runs" / f"{phase}.jsonl")
    return found


def green(
    rows: list[dict[str, Any]],
    band: dict[str, dict[str, float]],
    tried: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Whether one execution's means sit inside every band, and failures stay at or under the limit.

    Failures are counted over every attempt (``tried``), a failed first try included.
    """
    checks = {}
    for key, b in band.items():
        mean = statistics.fmean(float(r.get(key) or 0) for r in rows) if rows else 0.0
        checks[key] = {"mean": round(mean, 4), "inside": b["low"] <= mean <= b["high"]}
    fails = sum(1 for r in (tried if tried is not None else rows) if failed(r))
    checks["failed_runs"] = {"count": fails, "inside": fails <= MAX_FAILED_PER_EXECUTION}
    return {"green": all(c["inside"] for c in checks.values()), "checks": checks}


def answers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Bins overall, by group and by question."""

    def bins(items: list[dict[str, Any]]) -> dict[str, int]:
        c = Counter(r["outcome"] for r in items)
        return {b: c.get(b, 0) for b in scoring.BINS}

    order = [q.id for q in golden_set.load().questions]
    return {
        "runs": len(rows),
        "overall": bins(rows),
        "right_share": round(sum(1 for r in rows if r["outcome"] == scoring.RIGHT) / len(rows), 4)
        if rows
        else None,
        "by_group": {
            g: bins([r for r in rows if r["group"] == g])
            for g in ("lookup", "metric", "entity", "rule")
        },
        "by_question": {
            q: {
                **bins(items),
                "answers": [r["extracted"] for r in items],
                "decoys": [r.get("matched_decoy") or "" for r in items],
            }
            for q in order
            if (
                items := sorted(
                    (r for r in rows if r["question_id"] == q), key=lambda r: r["trial"]
                )
            )
        },
    }


def alerts_for(rows: list[dict[str, Any]], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """The alert rule applied to each execution of a set of runs."""
    return [
        {"execution": n, **alert_rule.evaluate(items, baseline)}
        for n, items in executions(rows).items()
    ]


def newly_wrong(rows: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Runs not scored right on questions the baseline got right every time."""
    always_right = {
        q for q in {r["question_id"] for r in baseline}
        if all(r["outcome"] == scoring.RIGHT for r in baseline if r["question_id"] == q)
    }  # fmt: skip
    return [r for r in rows if r["outcome"] != scoring.RIGHT and r["question_id"] in always_right]


def narrowing(wrong: list[dict[str, Any]]) -> dict[str, Any]:
    """What the newly wrong answers cite, and whose definitions those are."""
    owners = {d: e["owner"] for d, e in registry.load()["definitions"].items()}
    cited = Counter(c for r in wrong for c in r.get("sources_cited") or [])
    served = Counter(c for r in wrong for c in r.get("served_by_agent_record") or [])
    citing = [r for r in wrong if r.get("sources_cited")]
    shared = set.intersection(*(set(r["sources_cited"]) for r in citing)) if citing else set()
    owner_sets = [{owners.get(c.split("@")[0], "?") for c in r["sources_cited"]} for r in citing]
    return {
        "runs": len(wrong),
        "runs_citing_something": len(citing),
        "cited": dict(cited.most_common()),
        "served": dict(served.most_common()),
        "cited_by_every_citing_run": sorted(shared),
        "most_cited": cited.most_common(1)[0][0] if cited else None,
        "runs_citing_a_controller_definition": sum(1 for s in owner_sets if OWNER_OF_DRIFT in s),
        "runs_citing_only_controller_definitions": sum(
            1 for s in owner_sets if s == {OWNER_OF_DRIFT}
        ),
        "runs_citing_currency": sum(
            1 for r in citing if any(c.startswith("currency@") for c in r["sources_cited"])
        ),
        "runs_served_currency": sum(
            1
            for r in wrong
            if any(c.startswith("currency@") for c in r.get("served_by_agent_record") or [])
        ),
        "owners_cited": dict(Counter(o for s in owner_sets for o in s)),
        "by_question": {
            q: [
                {
                    "trial": r["trial"],
                    "outcome": r["outcome"],
                    "answer": r["extracted"],
                    "cited": r.get("sources_cited"),
                    "served": r.get("served_by_agent_record"),
                }
                for r in wrong
                if r["question_id"] == q
            ]
            for q in dict.fromkeys(r["question_id"] for r in wrong)
        },
    }


def trace_check(rows: list[dict[str, Any]], traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether every run has one complete trace that agrees with its record."""
    by_run = {t["run_id"]: t for t in traces}
    problems: list[str] = []
    adk_scopes: Counter[str] = Counter()
    span_counts = []
    durations = []
    for r in rows:
        t = by_run.get(r["run_id"])
        if t is None:
            problems.append(f"{r['question_id']}#{r['trial']}: no trace")
            continue
        roots = [s for s in t["spans"] if s["name"] == tracing.ROOT_SPAN]
        if len(roots) != 1:
            problems.append(f"{r['question_id']}#{r['trial']}: {len(roots)} root spans")
            continue
        root = roots[0]
        a = root["attributes"]
        under = [s for s in t["spans"] if s["trace_id"] == root["trace_id"] and s is not root]
        model_spans = [
            s for s in under if s["scope"] != tracing.TRACER_NAME and "call_llm" in s["name"]
        ]
        score = [s for s in under if s["name"] == tracing.SCORE_SPAN]
        adk_scopes.update(
            s["name"].split(" ")[0] for s in under if s["scope"] != tracing.TRACER_NAME
        )
        span_counts.append(len(t["spans"]))
        durations.append(root["duration_ms"] or 0)
        checks = {
            "question": a.get(tracing.QUESTION_ID) == r["question_id"],
            "contract_version": a.get(tracing.CONTRACT_VERSION) == run_part4.CONTRACT_VERSION,
            "cited_matches_record": list(a.get(tracing.DEFINITIONS_CITED) or [])
            == list(r.get("sources_cited") or []),
            "outcome_matches_record": a.get(tracing.OUTCOME) == r["outcome"],
            "golden_set_version": a.get(tracing.GOLDEN_SET_VERSION) == golden_set.CURRENT_VERSION,
            "model_call_span": bool(model_spans) or failed(r),
            "score_span": len(score) == 1,
        }
        for k, ok in checks.items():
            if not ok:
                problems.append(f"{r['question_id']}#{r['trial']}: {k}")
    return {
        "runs": len(rows),
        "traces": len(traces),
        "complete": len(rows) - len({p.split(":")[0] for p in problems}),
        "problems": problems,
        "spans_per_trace": _stats([float(x) for x in span_counts], 1),
        "adk_span_names": dict(adk_scopes.most_common(12)),
        "root_duration_ms": _stats([float(x) for x in durations], 1),
    }


def read_traces(out: Path, phase: str) -> list[dict[str, Any]]:
    """A phase's saved traces."""
    return run_part3.read_jsonl(out / "traces" / f"{phase}.jsonl")


def spend(out: Path = RESULTS) -> dict[str, Any]:
    """Estimated Part 5 spend across every saved run, smoke tests included."""
    return run_part3.spend(out)


def write_ledger(cloud_run_usd: float | None = None) -> dict[str, Any]:
    """Write the Part 5 lines of the series ledger."""
    ledger = json.loads(LEDGER_PATH.read_text()) if LEDGER_PATH.exists() else {}
    parts = dict(ledger.get("parts", {}))
    totals = spend()
    previous = parts.get("5", {})
    parts["5"] = {
        "what": "Standing answer check: the 24 questions as a frozen golden set in a Cloud Run job; drift planted (3 executions), after the fix (1). Baseline reused from Part 4.",
        "line_usd": LINE_USD,
        "planned_usd": PLANNED_USD,
        "stop_line_usd": STOP_LINE_USD,
        "spent_usd": totals["gemini_total_usd"],
        "model_usd": totals["gemini_model_usd"],
        "bigquery_usd": totals["bigquery_usd"],
        "by_folder": totals["gemini_by_folder"],
    }
    if cloud_run_usd is not None or "cloud_run_usd_estimate" in previous:
        parts["5"]["cloud_run_usd_estimate"] = (
            cloud_run_usd if cloud_run_usd is not None else previous["cloud_run_usd_estimate"]
        )
    spent = round(sum(float(p.get("spent_usd") or 0) for p in parts.values()), 4)
    ledger.update(
        {
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "parts": parts,
            "spent_usd_parts_2_to_7": spent,
            "remaining_to_approved_usd": round(run_part2.SERIES_APPROVED_USD - spent, 4),
            "remaining_to_hard_cap_usd": round(run_part2.SERIES_CAP_USD - spent, 4),
        }
    )
    LEDGER_PATH.write_text(json.dumps(ledger, indent=1) + "\n")
    return ledger


# --- predictions, summary --------------------------------------------------------------------


def evaluate(s: dict[str, Any], rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Test each prediction in results/part5/predictions.md by its stated rule."""
    out: list[dict[str, Any]] = []

    def add(number: str, held: bool | None, numbers: str) -> None:
        out.append({"prediction": number, "held": held, "numbers": numbers})

    dr, fx = rows.get("drift", []), rows.get("after_fix", [])
    if dr:
        per = s["green_by_execution"]["drift"]
        detail = "; ".join(
            f"e{e['execution']}: "
            + ", ".join(
                f"{k} {c.get('mean', c.get('count'))}{'' if c['inside'] else ' OUT'}"
                for k, c in e["checks"].items()
            )
            for e in per
        )
        add("P1", len(per) == 3 and all(e["green"] for e in per), detail)
        right = sum(1 for r in dr if r["outcome"] == scoring.RIGHT)
        four = [r for r in dr if r["question_id"] in DRIFTED]
        four_not = [r for r in four if r["outcome"] != scoring.RIGHT]
        add("P2", right <= 64 and len(four_not) >= 8,
            f"right {right} of {len(dr)}; not right on M2, M3, E3, R3: {len(four_not)} of {len(four)}")  # fmt: skip
        lk = [r for r in dr if r["group"] == "lookup"]
        rest = [r for r in dr if r["question_id"] not in DRIFTED]
        lk_right = sum(1 for r in lk if r["outcome"] == scoring.RIGHT)
        rest_right = sum(1 for r in rest if r["outcome"] == scoring.RIGHT)
        add("P3", lk_right == len(lk) == 18 and rest_right >= 58,
            f"lookups right {lk_right} of {len(lk)}; the other 20 questions right {rest_right} of {len(rest)}"
            f" (missed: {sorted(r['question_id'] + '#' + str(r['trial']) for r in rest if r['outcome'] != scoring.RIGHT)})")  # fmt: skip
        conf = [r for r in four_not if r["outcome"] == scoring.WRONG]
        decoyed = [r for r in four_not if r.get("matched_decoy")]
        share = len(conf) / len(four_not) if four_not else None
        add("P4", bool(four_not) and share is not None and share >= 0.8 and not decoyed,
            f"confidently wrong {len(conf)} of {len(four_not)} not-right runs on the four; matching a decoy {len(decoyed)}")  # fmt: skip
        al = s["alerts"]["drift"]
        live = [a for a in s.get("alerts_raised", []) if a.get("phase") == "drift"]
        if live:
            # What the job raised: the first verdict per execution, before any retry pass.
            first: dict[int, dict[str, Any]] = {}
            for a in live:
                first.setdefault(
                    int(a["execution"]), {**a, "fired": a["event"] == "golden_set_alert"}
                )
            al = [first[k] for k in sorted(first)]
        fired = [a["execution"] for a in al if a["fired"]]
        lookup_named = any("lookup" in a["groups_below"] for a in al)
        add("P5", fired == [1, 2, 3] and not lookup_named,
            f"fired on executions {fired} of {[a['execution'] for a in al]}; groups below: {[a['groups_below'] for a in al]}")  # fmt: skip
    quiet_base = [a for k in ("baseline", "part3_available") for a in s["alerts"].get(k, [])]
    quiet_fix = s["alerts"].get("after_fix", [])
    if quiet_base and quiet_fix:
        add("P6", not any(a["fired"] for a in quiet_base + quiet_fix),
            f"baseline executions fired {sum(a['fired'] for a in quiet_base)} of {len(quiet_base)}; after the fix fired {sum(a['fired'] for a in quiet_fix)} of {len(quiet_fix)}")  # fmt: skip
    if fx:
        right = sum(1 for r in fx if r["outcome"] == scoring.RIGHT)
        add("P7", right >= 23, f"right {right} of {len(fx)}")
    if dr:
        n = s["narrowing"]
        held = (
            n["runs_citing_something"] > 0
            and n["runs_citing_a_controller_definition"] == n["runs_citing_something"]
            and n["most_cited"] == "revenue@1"
            and n["runs_citing_currency"] < n["runs_citing_something"] / 2
        )
        add("P8", held,
            f"{n['runs']} newly wrong runs, {n['runs_citing_something']} citing; {n['runs_citing_a_controller_definition']} cite a Controller definition;"
            f" most cited {n['most_cited']}; citing currency@1 {n['runs_citing_currency']}; cited {n['cited']}")  # fmt: skip
    if dr and fx:
        t = s["traces"]
        total = t["drift"]["runs"] + t["after_fix"]["runs"]
        complete = t["drift"]["complete"] + t["after_fix"]["complete"]
        add("P9", complete == total == 96,
            f"{complete} of {total} runs with a complete, agreeing trace; problems {t['drift']['problems'][:5] + t['after_fix']['problems'][:5]}")  # fmt: skip
    if dr:
        cost = statistics.fmean(float(r["cost_usd"]) for r in dr)
        add(
            "P10",
            cost <= 0.0451,
            f"mean model cost per run ${cost:.4f} (baseline ${s['operational']['baseline']['cost_usd']['mean']:.4f}; the line is $0.0451)",
        )
    lc = s.get("server_log_check")
    if lc:
        add("P11", lc["agreeing_calls"] == lc["agent_calls"] - lc["calls_refused_before_the_contract_ran"]
            and lc["server_lines_missing_from_agent_record"] == 0,
            f"{lc['agreeing_calls']} of {lc['agent_calls']} calls agree ({lc['calls_refused_before_the_contract_ran']} refused before the contract ran); {lc['server_lines_missing_from_agent_record']} server lines not in a record")  # fmt: skip
    return out


def build_summary(out: Path = RESULTS) -> dict[str, Any]:
    """Write summary.json and summary.md from the saved runs, traces, alerts and drift records."""
    rows = phase_rows(out)
    tried = phase_attempts(out)
    base_rows = rows["baseline"]
    baseline_alert = alert_rule.load_baseline()
    band = bands(base_rows)
    s: dict[str, Any] = {
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": run_part4.BASE.model,
        "contract_version": run_part4.CONTRACT_VERSION,
        "golden_set": {
            k: golden_set.manifest()[k]
            for k in ("version", "owner", "frozen_on", "answers_sha256", "questions_sha256")
        },
        "alert_rule": alert_rule.RULE,
        "bands": band,
        "operational": {k: operational(v) for k, v in rows.items() if v},
        "operational_by_execution": {
            k: [{"execution": n, **operational(items)} for n, items in executions(v).items()]
            for k, v in rows.items()
            if v
        },
        "green_by_execution": {
            k: [
                {"execution": n, **green(items, band, executions(tried[k]).get(n, []))}
                for n, items in executions(v).items()
            ]
            for k, v in rows.items()
            if v
        },
        "failed_attempts": {
            k: {
                "attempts": len(tried[k]),
                "failed": sum(1 for r in tried[k] if failed(r)),
                "rerun_after_failure": sum(1 for r in tried[k] if r.get("retry_of_failed")),
                "failures": [
                    f"{r['question_id']}#{r['trial']}: {'timeout' if r.get('timed_out') else str(r.get('error')).strip().splitlines()[0][:60]}"
                    for r in tried[k]
                    if failed(r)
                ],
            }
            for k in rows
            if tried.get(k)
        },
        "answers": {k: answers(v) for k, v in rows.items() if v},
        "answers_by_execution": {
            k: [{"execution": n, **answers(items)["overall"]} for n, items in executions(v).items()]
            for k, v in rows.items()
            if v
        },
        "alerts": {k: alerts_for(v, baseline_alert) for k, v in rows.items() if v},
        "alerts_from_the_job": {
            p: json.loads((out / "alerts" / f"{p}.json").read_text())
            for p in PHASES
            if (out / "alerts" / f"{p}.json").exists()
        },
    }
    raised = out / "alerts" / "raised.jsonl"
    s["alerts_raised"] = run_part3.read_jsonl(raised) if raised.exists() else []
    first = next((a["execution"] for a in s["alerts"].get("drift", []) if a["fired"]), None)
    s["time_to_detection"] = {
        "first_execution_that_fired": first,
        "executions_run": len(s["alerts"].get("drift", [])),
    }
    s["narrowing"] = narrowing(newly_wrong(rows.get("drift", []), base_rows))
    s["traces"] = {p: trace_check(rows[p], read_traces(out, p)) for p in PHASES if rows.get(p)}
    s["drift_records"] = (
        {p.stem: json.loads(p.read_text()) for p in sorted((out / "drift").glob("*.json"))}
        if (out / "drift").exists()
        else {}
    )
    log_lines = run_part3.read_jsonl(out / "server_log.jsonl")
    every = [r for p in PHASES for r in rows.get(p, [])]
    s["server_log_check"] = run_part3.compare_log(every, log_lines) if log_lines and every else None
    s["predictions"] = evaluate(s, rows)
    s["spend"] = spend(out)
    (out / "summary.json").write_text(run_part4.clean(json.dumps(s, indent=1, default=str)) + "\n")
    (out / "summary.md").write_text(run_part4.clean(render(s)))
    return s


def _b(b: dict[str, int]) -> str:
    return " / ".join(str(b[k]) for k in scoring.BINS)


def render(s: dict[str, Any]) -> str:
    """Render the summary as Markdown."""
    names = {"baseline": "Baseline (Part 4 available, reused)", "part3_available": "Part 3 available (second baseline pass)",
             "drift": "Drift", "after_fix": "After the fix"}  # fmt: skip
    lines = [
        "# Part 5 results",
        "",
        "Written by `run_part5.py`. Tessaway Freight is a fictional company, the data is synthetic, and every owner is a fictional role.",
        "",
        f"The golden set is version {s['golden_set']['version']} (owner: {s['golden_set']['owner']}; frozen {s['golden_set']['frozen_on']}), scored by the Part 1 scorer against the frozen answers. The agent is Part 4's available configuration: Google ADK, `{s['model']}`, contract {s['contract_version']} and the SQL tool, citing its definitions. Part 5's runs come from a Cloud Run job, one execution per 24 questions; the baseline is Part 4's run from the Mac, reused, and has no traces.",
        "",
        "One run is 1.4 points of a 72-run share and 4.2 points of a 24-run share. Small differences are not findings.",
        "",
        "## 1. The operational signals (what a dashboard shows)",
        "",
        "Per run, mean (standard deviation). Failed: ended in an error or a timeout.",
        "",
        "| Phase | Runs | Failed | Latency s | Cost $ | Input tokens | Output tokens | SQL queries | Contract calls | Model calls |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    def ms(o: dict[str, Any], k: str, fmt: str) -> str:
        return f"{o[k]['mean']:{fmt}} ({o[k]['sd']:{fmt}})"

    for k, o in s["operational"].items():
        lines.append(
            f"| {names.get(k, k)} | {o['runs']} | {o['failed_runs']} | {ms(o, 'seconds', '.1f')} | {ms(o, 'cost_usd', '.4f')} | {ms(o, 'input_tokens_total', ',.0f')} | {ms(o, 'output_tokens', ',.0f')} | {ms(o, 'query_count', '.2f')} | {ms(o, 'contract_calls', '.2f')} | {ms(o, 'model_calls', '.2f')} |"
        )
    lines += [
        "",
        "Failed attempts (an error or a timeout), counting first tries that were later run again: "
        + "; ".join(
            f"{names.get(k, k)} {v['failed']} of {v['attempts']}"
            + (f" ({', '.join(v['failures'])})" if v["failures"] else "")
            for k, v in s.get("failed_attempts", {}).items()
        ),
    ]
    lines += ["", "### By execution, against the green bands", "",
              "Band: the baseline's per-run mean plus or minus one standard deviation. " + ", ".join(
                  f"{k} {b['low']:g} to {b['high']:g}" for k, b in s["bands"].items()) + f"; failed runs at most {MAX_FAILED_PER_EXECUTION} in 24.",
              "", "| Phase | Execution | Latency s | Cost $ | Input tokens | SQL queries | Failed | Green |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for k, per in s["green_by_execution"].items():
        for e in per:
            c = e["checks"]
            lines.append(
                f"| {names.get(k, k)} | {e['execution']} | {c['seconds']['mean']:.1f} | {c['cost_usd']['mean']:.4f} | {c['input_tokens_total']['mean']:,.0f} | {c['query_count']['mean']:.2f} | {c['failed_runs']['count']} | {'yes' if e['green'] else 'NO'} |"
            )
    lines += ["", "## 2. The answers", "", "Right / confidently wrong / declined / no answer.", "",
              "| Phase | Runs | Overall | Lookup | Metric | Entity | Rule |", "| --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for k, a in s["answers"].items():
        g = a["by_group"]
        lines.append(
            f"| {names.get(k, k)} | {a['runs']} | {_b(a['overall'])} | {_b(g['lookup'])} | {_b(g['metric'])} | {_b(g['entity'])} | {_b(g['rule'])} |"
        )
    lines += [
        "",
        "### By execution",
        "",
        "| Phase | Execution | Right / wrong / declined / no answer |",
        "| --- | --- | --- |",
    ]
    for k, per in s["answers_by_execution"].items():
        for e in per:
            lines.append(f"| {names.get(k, k)} | {e['execution']} | {_b(e)} |")
    lines += [
        "",
        "### The questions that moved",
        "",
        "| Phase | Question | Right / wrong / declined / no answer | Answers | Decoys matched |",
        "| --- | --- | --- | --- | --- |",
    ]
    for k in ("drift", "after_fix"):
        for q, v in (s["answers"].get(k) or {}).get("by_question", {}).items():
            if v[scoring.RIGHT] < sum(v[b] for b in scoring.BINS) or q in DRIFTED:
                lines.append(
                    f"| {names[k]} | {q} | {_b(v)} | {', '.join(v['answers'])} | {', '.join(d for d in v['decoys'] if d) or '-'} |"
                )
    lines += ["", "## 3. The alert rule", "", f"Rule: {s['alert_rule']}", "",
              "| Phase | Execution | Fired | Groups below the baseline | Runs not right |", "| --- | --- | --- | --- | --- |"]  # fmt: skip
    for k, per in s["alerts"].items():
        for a in per:
            lines.append(
                f"| {names.get(k, k)} | {a['execution']} | {'yes' if a['fired'] else 'no'} | {', '.join(a['groups_below']) or '-'} | {', '.join(a['missed']) or '-'} |"
            )
    if s.get("alerts_raised"):
        lines += ["", "### Every verdict the job raised, in order (from Cloud Logging)", "",
                  "A retry pass on an execution raises a second verdict for it. The table above recomputes the rule from the final records.", "",
                  "| Time (UTC) | Phase | Execution | Verdict | Right of runs | Groups below | Runs not right |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
        for a in s["alerts_raised"]:
            lines.append(
                f"| {a['log_timestamp'][:19]} | {a.get('phase')} | {a.get('execution')} | {'fired' if a['event'] == 'golden_set_alert' else 'quiet'} | {a.get('right')} of {a.get('runs')} | {', '.join(a.get('groups_below') or []) or '-'} | {', '.join(a.get('missed') or []) or '-'} |"
            )
    t = s["time_to_detection"]
    lines += [
        "",
        f"Time to detection: the first drift execution that fired was execution {t['first_execution_that_fired']} of {t['executions_run']}. The job's own verdicts (`alerts/*.json`) are in `summary.json` beside these, recomputed from the same records.",
        "",
    ]
    n = s["narrowing"]
    lines += ["## 4. Where the trace points", "",
              f"Newly wrong runs (not right, on questions the baseline got right in every run): {n['runs']}; {n['runs_citing_something']} cite at least one definition.", "",
              f"- Cited: {n['cited']}", f"- Served by the contract in those runs: {n['served']}",
              f"- Cited by every citing run: {n['cited_by_every_citing_run'] or 'none'}; most cited: {n['most_cited']}",
              f"- Owners of what they cite: {n['owners_cited']}; runs citing a Controller definition: {n['runs_citing_a_controller_definition']}",
              f"- Runs citing `currency@1`: {n['runs_citing_currency']}; runs in which the contract served `currency@1`: {n['runs_served_currency']}", ""]  # fmt: skip
    lines += [
        "## 5. The traces",
        "",
        "| Phase | Runs | Traces | Complete and agreeing | Spans per trace | Problems |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for k, tc in s["traces"].items():
        lines.append(
            f"| {names[k]} | {tc['runs']} | {tc['traces']} | {tc['complete']} | {tc['spans_per_trace'].get('mean', '-')} | {'; '.join(tc['problems'][:5]) or '-'} |"
        )
    lines += [""]
    if s["drift_records"]:
        lines += ["## 6. The drift, measured without a model", "",
                  "The reviewed gold SQL, run against the copy in each state. This is what the answer key would say if it were recomputed; nothing is scored against it.", "",
                  "| State | Rows with a changed amount | Row counts and types as the record | Out of tolerance | M2 | M3 | M4 | E3 | R3 | R6 |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
        for name, rec in s["drift_records"].items():
            st, g = rec["status"], rec["gold_recomputed_on_copy"]["questions"]
            same = all(
                v["rows"] == v["rows_in_record"] and v["same_columns_and_types"]
                for v in st["tables"].values()
            )
            moved = rec["gold_recomputed_on_copy"]["out_of_tolerance"]
            cells = " | ".join(
                f"{g[q]['recomputed']} ({g[q]['change_pct']:+.2f}%)"
                if g[q]["change_pct"] is not None
                else str(g[q]["recomputed"])
                for q in ("M2", "M3", "M4", "E3", "R3", "R6")
            )
            lines.append(
                f"| {name} | {st['changed_rows']} | {'yes' if same else 'NO'} | {len(moved)}: {', '.join(moved) or '-'} | {cells} |"
            )
        lines += [""]
    lc = s.get("server_log_check")
    if lc:
        lines += ["## 7. The server's record", "",
                  f"{lc['agreeing_calls']} of {lc['agent_calls']} recorded contract calls agree with the server log ({lc['calls_refused_before_the_contract_ran']} refused by the MCP layer before the contract ran); {lc['server_lines_missing_from_agent_record']} log lines not in a record; {lc['runs_agreeing']} of {lc['runs']} runs agree in full. Callers: {lc['callers_in_log']}.", ""]  # fmt: skip
    if s["predictions"]:
        lines += [
            "## Predictions",
            "",
            "As written in `predictions.md` before the first scored run, each tested by its own rule.",
            "",
            "| # | Held | Numbers |",
            "| --- | --- | --- |",
        ]
        for p in s["predictions"]:
            lines.append(f"| {p['prediction']} | {'yes' if p['held'] else 'NO'} | {p['numbers']} |")
    sp = s["spend"]
    lines += ["", "## Spend", "",
              f"- Gemini (model) ${sp['gemini_model_usd']:.2f} and BigQuery ${sp['bigquery_usd']:.4f}: ${sp['gemini_total_usd']:.2f} for Part 5, smoke test included.", "",
              "Model names and prices as checked for the series in `tessaway/config.py`. Costs are estimates.", ""]  # fmt: skip
    return "\n".join(lines)


def main(args: argparse.Namespace) -> None:
    """Do one step from the command line, then write the summary when there is something to summarize."""
    out = RESULTS / args.out if args.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    if args.write_baseline:
        base = alert_rule.write_baseline(rows_of(PART4_AVAILABLE))
        print(json.dumps(base, indent=1))
        return
    if args.execute:
        phase, number = args.execute[0], int(args.execute[1])
        spent = float(spend()["gemini_total_usd"])
        if spent >= STOP_LINE_USD:
            raise SystemExit(
                f"Part 5 Gemini spend is ${spent:.2f}, at or over the ${STOP_LINE_USD:.2f} stop line."
            )
        budget = min(args.budget_usd, STOP_LINE_USD - spent)
        raise SystemExit(
            execute(phase, number, args.dataset, args.questions, budget, args.retry_failed)
        )
    if args.pull:
        print(pull(args.pull, out))
        return
    if args.record_drift:
        found = record_drift(args.record_drift, args.dataset, out)
        print(json.dumps({"changed_rows": found["status"]["changed_rows"],
                          "out_of_tolerance": found["gold_recomputed_on_copy"]["out_of_tolerance"]}))  # fmt: skip
        return
    if args.read_server_log:
        print(f"{save_server_log(args.since, out)} server log lines saved")
        print(f"{save_alert_log(args.since, out)} alert verdicts saved")
    summary = build_summary(out)
    if not args.out:
        write_ledger(args.cloud_run_usd)
    for p in summary["predictions"]:
        print(p["prediction"], "held" if p["held"] else "NOT HELD", p["numbers"])


def parse_args() -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(
        description="Run the Part 5 experiment from the operator's side."
    )
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--execute", nargs=2, metavar=("PHASE", "EXECUTION"))
    parser.add_argument("--dataset", default=DATASET)
    parser.add_argument("--questions", default="")
    parser.add_argument("--budget-usd", type=float, default=2.0)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--pull", default="")
    parser.add_argument("--record-drift", default="")
    parser.add_argument("--read-server-log", action="store_true")
    parser.add_argument("--since", default="2026-10-14T00:00:00Z")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--out", default="")
    parser.add_argument("--cloud-run-usd", type=float, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    main(parse_args())
