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

"""Part 6: the meter. Cost per correct answer from the run records the series saved.

Every run since Part 1 wrote down its tokens (uncached input, cached input,
output), its model calls, its queries, the BigQuery bytes it was billed for and
an estimated cost. This module reads those records, prices them again from
their token counts as a check on the recorded cost, picks the record that was
scored for each question and repeat, and rolls the spend up by configuration,
question group and outcome. Nothing here calls a model or a cloud service.

Costs are estimates from list prices on ``config.MODELS_VERIFIED_ON``; the
invoice is the authority.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tessaway.config import BQ_USD_PER_TIB, CONFIGS, ModelConfig

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

OUTCOMES = ("right", "confidently_wrong", "declined", "no_answer")
GROUPS = ("lookup", "metric", "entity", "rule")


@dataclass(frozen=True)
class Configuration:
    """One configuration the series ran, and where its run records are."""

    key: str
    part: int
    label: str
    path: str  # relative to results/
    question_set: str  # "part1" (the 24 Part 1 questions) or "holdout" (the 12 blind ones)
    context: str  # what the agent was given, in a few words


# Every scored configuration in Parts 1 to 5, in the order the series built them.
SERIES: tuple[Configuration, ...] = (
    Configuration(
        "p1_flash",
        1,
        "Raw warehouse",
        "part1/runs/adk_gemini_flash.jsonl",
        "part1",
        "table and column names, one SQL tool",
    ),
    Configuration(
        "p1_pro",
        1,
        "Raw warehouse, bigger model",
        "part1/runs/adk_gemini_pro.jsonl",
        "part1",
        "the same, on gemini-3.1-pro-preview",
    ),
    Configuration(
        "p2_semantic",
        2,
        "Semantic layer",
        "part2/runs/flash_semantic.jsonl",
        "part1",
        "a metric tool beside the SQL tool",
    ),
    Configuration(
        "p2_ontology",
        2,
        "Ontology",
        "part2/runs/flash_ontology.jsonl",
        "part1",
        "an ontology tool beside the SQL tool",
    ),
    Configuration(
        "p2_graph",
        2,
        "Knowledge graph",
        "part2/runs/flash_graph.jsonl",
        "part1",
        "a graph tool beside the SQL tool",
    ),
    Configuration(
        "p2_all_three",
        2,
        "All three layers",
        "part2/runs/flash_all_three.jsonl",
        "part1",
        "all three layer tools beside the SQL tool",
    ),
    Configuration(
        "p3_available",
        3,
        "Contract and SQL",
        "part3/runs/available.jsonl",
        "part1",
        "the context contract over MCP beside the SQL tool",
    ),
    Configuration(
        "p3_routed",
        3,
        "Contract only",
        "part3/runs/routed.jsonl",
        "part1",
        "the context contract, no SQL tool",
    ),
    Configuration(
        "p4_available",
        4,
        "Contract and SQL, cited",
        "part4/runs/available.jsonl",
        "part1",
        "contract 2.0.0 with provenance, SQL tool, cited answers",
    ),
    Configuration(
        "p5_drift",
        5,
        "Part 4's setup, drifted data",
        "part5/runs/drift.jsonl",
        "part1",
        "Part 4's setup on the warehouse copy with billing's reload",
    ),
    Configuration(
        "p5_after_fix",
        5,
        "Part 4's setup, after the fix",
        "part5/runs/after_fix.jsonl",
        "part1",
        "Part 4's setup after the reload was reverted",
    ),
    Configuration(
        "h_baseline",
        2,
        "Raw warehouse (blind questions)",
        "holdout/runs/baseline.jsonl",
        "holdout",
        "table and column names, one SQL tool",
    ),
    Configuration(
        "h_semantic",
        2,
        "Semantic layer (blind questions)",
        "holdout/runs/flash_semantic.jsonl",
        "holdout",
        "a metric tool beside SQL",
    ),
    Configuration(
        "p3_routed_holdout",
        3,
        "Contract only (blind questions)",
        "part3/runs/routed_holdout.jsonl",
        "holdout",
        "the context contract, no SQL",
    ),
    Configuration(
        "p4_routed_holdout",
        4,
        "Contract only, cited (blind questions)",
        "part4/runs/routed_holdout.jsonl",
        "holdout",
        "contract 2.0.0 with provenance, no SQL, cited answers",
    ),
)

# Recorded with costs but never scored, so they have no cost per correct answer.
UNSCORED: tuple[Configuration, ...] = (
    Configuration(
        "p3_claude_demo",
        3,
        "Claude Agent SDK demonstration",
        "part3/runs/claude_demo.jsonl",
        "part1",
        "contract and SQL, claude-sonnet-5-5, not scored",
    ),
)


def configuration(key: str) -> Configuration:
    """Return the configuration with this key."""
    for cfg in SERIES + UNSCORED:
        if cfg.key == key:
            return cfg
    raise KeyError(key)


def prices_for(model: str) -> ModelConfig:
    """Return the price entry for a model name, from ``config.CONFIGS``."""
    for cfg in CONFIGS.values():
        if cfg.model == model:
            return cfg
    raise KeyError(f"no price for model {model!r}")


def model_cost(record: dict[str, Any], prices: ModelConfig | None = None) -> float:
    """Price one run's tokens: uncached input, cached input, cache writes and output.

    ``input_tokens`` in a record is the input billed at the full rate;
    ``cache_read_tokens`` is input served from the provider's cache, billed at the
    cached rate; output includes thinking tokens.

    Args:
        record: One saved run.
        prices: The price entry to use. Defaults to the record's own model at the
            prices the series pinned.
    """
    p = prices or prices_for(record["model"])
    return p.cost(
        input_tokens=record.get("input_tokens") or 0,
        output_tokens=record.get("output_tokens") or 0,
        cache_read=record.get("cache_read_tokens") or 0,
        cache_write=record.get("cache_write_tokens") or 0,
    )


def bigquery_cost(record: dict[str, Any]) -> float:
    """Price the BigQuery bytes a run was billed for, at the on-demand rate."""
    return (record.get("bigquery_bytes_billed") or 0) / 2**40 * BQ_USD_PER_TIB


def spend(record: dict[str, Any]) -> float:
    """What one run cost as recorded: model estimate plus BigQuery."""
    return float(record.get("cost_usd") or 0) + float(record.get("bigquery_usd") or 0)


def load(path: Path | str) -> list[dict[str, Any]]:
    """Read every saved attempt in a runs file, in the order they were written."""
    path = Path(path)
    if not path.is_absolute():
        path = RESULTS / path
    with path.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def scored(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the record that was scored for each question and repeat.

    A run that failed (an error or a timeout) was run once more, and the rerun was
    written after it, marked ``retry_of_failed``. The later record is the one the
    part scored. Order follows the first appearance of each question and repeat.
    """
    final: dict[tuple[str, int], dict[str, Any]] = {}
    for r in records:
        final[(r["question_id"], r["trial"])] = r
    return list(final.values())


def replaced(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the attempts a rerun replaced: spent, but not scored."""
    records = list(records)
    keep = {id(r) for r in scored(records)}
    return [r for r in records if id(r) not in keep]


def _mean(total: float, n: int) -> float | None:
    return total / n if n else None


def rollup(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll scored records up into the figures Part 6 reports for one slice.

    Cost per correct answer is the spend on these records divided by how many of
    them were right. It is ``None`` when none were right.
    """
    n = len(records)
    counts = {o: sum(1 for r in records if r.get("outcome") == o) for o in OUTCOMES}
    total = sum(spend(r) for r in records)
    model_usd = sum(float(r.get("cost_usd") or 0) for r in records)
    bq_usd = sum(float(r.get("bigquery_usd") or 0) for r in records)
    input_total = sum(r.get("input_tokens_total") or 0 for r in records)
    cached = sum(r.get("cache_read_tokens") or 0 for r in records)
    output = sum(r.get("output_tokens") or 0 for r in records)
    calls = sum(r.get("model_calls") or 0 for r in records)
    queries = sum(r.get("query_count") or 0 for r in records)
    right = counts["right"]
    return {
        "runs": n,
        "outcomes": counts,
        "shares": {o: (counts[o] / n if n else None) for o in OUTCOMES},
        "spend_usd": total,
        "model_usd": model_usd,
        "bigquery_usd": bq_usd,
        "cost_per_run_usd": _mean(total, n),
        "cost_per_correct_usd": (total / right) if right else None,
        "spend_by_outcome_usd": {
            o: sum(spend(r) for r in records if r.get("outcome") == o) for o in OUTCOMES
        },
        "input_tokens_per_run": _mean(input_total, n),
        "cached_share_of_input": (cached / input_total) if input_total else None,
        "output_tokens_per_run": _mean(output, n),
        "model_calls_per_run": _mean(calls, n),
        "queries_per_run": _mean(queries, n),
        "input_tokens_per_model_call": _mean(input_total, calls),
        "runs_at_query_limit": sum(
            1 for r in records if (r.get("queries_refused_over_limit") or 0) > 0
        ),
    }


def by_group(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Roll scored records up per question group (lookup, metric, entity, rule)."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        groups[r["group"]].append(r)
    return {g: rollup(groups[g]) for g in GROUPS if g in groups}


def step_profile(records: list[dict[str, Any]], steps: int = 8) -> list[dict[str, Any]]:
    """Mean input tokens sent at each model call, for runs that recorded them per call.

    ``prompt_tokens_by_call`` holds ``[prompt_tokens, cached_tokens]`` for each model
    call in order. Each step reports the mean prompt size over the runs that reached
    that step, and how many did.
    """
    out = []
    for i in range(steps):
        sizes = [
            r["prompt_tokens_by_call"][i][0]
            for r in records
            if r.get("prompt_tokens_by_call") and len(r["prompt_tokens_by_call"]) > i
        ]
        out.append(
            {"step": i + 1, "runs": len(sizes), "mean_input_tokens": _mean(sum(sizes), len(sizes))}
        )
    return out


def reprice(
    records: list[dict[str, Any]], usd_in: float, usd_out: float, usd_cache_read: float
) -> float:
    """Total spend on these records at other model prices; BigQuery stays as recorded."""
    total = 0.0
    for r in records:
        total += (
            (r.get("input_tokens") or 0) * usd_in
            + (r.get("output_tokens") or 0) * usd_out
            + (r.get("cache_read_tokens") or 0) * usd_cache_read
        ) / 1_000_000 + float(r.get("bigquery_usd") or 0)
    return total
