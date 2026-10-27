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

"""OpenTelemetry traces for the standing answer check (Part 5).

Each run of a golden-set question gets one trace. Its root span,
``golden_set.run``, carries what a dashboard needs to follow a wrong answer
back: the question, the golden set version, the contract version and the
definition ids and versions the answer cited and was served, the model,
tokens, cost, latency and query counts, and the score. A child span,
``golden_set.score``, holds the scorer's verdict on its own. Google ADK's
own spans (the agent invocation, each model call, each tool call) nest under
the root, because ADK emits them through the global tracer provider.

Attribute names. Where the OpenTelemetry semantic conventions for generative
AI define a name (``opentelemetry-semantic-conventions`` 0.63b1, incubating),
it is used: ``gen_ai.operation.name``, ``gen_ai.agent.name``,
``gen_ai.provider.name``, ``gen_ai.request.model``, ``gen_ai.response.model``,
``gen_ai.conversation.id``, ``gen_ai.usage.input_tokens``,
``gen_ai.usage.output_tokens``, ``gen_ai.usage.cache_read.input_tokens``, and
``error.type``. Everything else is this repo's own, under ``tessaway.``: the
conventions have no names for a golden set, a context contract, a definition
version or a score.

The run record (``runs/*.jsonl``) is unchanged from Part 4; the trace is
written beside it and joined to it by ``tessaway.run.id``.

Message content is kept out of ADK's spans (``ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false``):
the run record already holds the answer text, and the spans stay small.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

SERVICE_NAME = "tessaway-golden-check"
TRACER_NAME = "tessaway.golden_set"
ROOT_SPAN = "golden_set.run"
SCORE_SPAN = "golden_set.score"

# Names from the OpenTelemetry semantic conventions for generative AI.
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_AGENT_NAME = "gen_ai.agent.name"
GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_CONVERSATION_ID = "gen_ai.conversation.id"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_USAGE_CACHE_READ = "gen_ai.usage.cache_read.input_tokens"
ERROR_TYPE = "error.type"
STANDARD = (
    GEN_AI_OPERATION_NAME,
    GEN_AI_AGENT_NAME,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_CONVERSATION_ID,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    GEN_AI_USAGE_CACHE_READ,
    ERROR_TYPE,
)

# This repo's own names.
RUN_ID = "tessaway.run.id"
PHASE = "tessaway.check.phase"
EXECUTION = "tessaway.check.execution"
QUESTION_ID = "tessaway.question.id"
QUESTION_GROUP = "tessaway.question.group"
GOLDEN_SET_VERSION = "tessaway.golden_set.version"
CONTRACT_VERSION = "tessaway.context.contract_version"
REGISTRY_SHA = "tessaway.context.registry_sha256"
DEFINITIONS_CITED = "tessaway.context.definitions_cited"
DEFINITIONS_SERVED = "tessaway.context.definitions_served"
DEFINITION_OWNERS = "tessaway.context.definition_owners"
MODEL_CALLS = "tessaway.model.call_count"
SQL_QUERIES = "tessaway.sql.query_count"
CONTRACT_CALLS = "tessaway.contract.call_count"
COST_USD = "tessaway.cost.usd"
LATENCY_S = "tessaway.latency.seconds"
OUTCOME = "tessaway.score.outcome"
EXTRACTED = "tessaway.score.extracted"
GOLD = "tessaway.score.gold"
DECOY = "tessaway.score.matched_decoy"

# Attributes kept when a span is written to a file: every name above, plus
# short values from ADK's spans. Long values (request payloads) are dropped.
_KEEP_PREFIXES = ("gen_ai.", "tessaway.", "error.", "gcp.vertex.agent.", "mcp.")
_MAX_VALUE_CHARS = 300


def disable_content_capture() -> None:
    """Keep prompts and replies out of ADK's spans."""
    os.environ.setdefault("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", "false")


class RunCollector(SpanExporter):
    """Holds finished spans in memory, grouped by trace, until the run's trace is taken."""

    def __init__(self) -> None:
        """Start empty."""
        self._spans: dict[int, list[ReadableSpan]] = {}
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Keep each finished span under its trace id."""
        with self._lock:
            for span in spans:
                if span.context is not None:
                    self._spans.setdefault(span.context.trace_id, []).append(span)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """Nothing to release."""

    def pop(self, trace_id: int) -> list[dict[str, Any]]:
        """Remove and return one trace's spans as plain dicts, oldest first."""
        with self._lock:
            spans = self._spans.pop(trace_id, [])
        return [to_dict(s) for s in sorted(spans, key=lambda s: s.start_time or 0)]


def _value(value: Any) -> Any:
    if isinstance(value, tuple | list):
        return [_value(v) for v in value]
    return value


def to_dict(span: ReadableSpan) -> dict[str, Any]:
    """A span as a small JSON-ready dict, with long or unknown attributes left out."""
    attrs = {}
    for key, value in (span.attributes or {}).items():
        if not key.startswith(_KEEP_PREFIXES):
            continue
        if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
            continue
        attrs[key] = _value(value)
    ctx = span.context
    start, end = span.start_time or 0, span.end_time or 0
    return {
        "name": span.name,
        "trace_id": f"{ctx.trace_id:032x}" if ctx else "",
        "span_id": f"{ctx.span_id:016x}" if ctx else "",
        "parent_span_id": f"{span.parent.span_id:016x}" if span.parent else "",
        "scope": span.instrumentation_scope.name if span.instrumentation_scope else "",
        "start_unix_nano": start,
        "duration_ms": round((end - start) / 1e6, 1) if end and start else None,
        "status": span.status.status_code.name if span.status else "UNSET",
        "attributes": attrs,
    }


def configure(*, cloud_trace_project: str | None = None) -> RunCollector:
    """Install a tracer provider that collects every span, and optionally sends them to Cloud Trace.

    Returns the collector, from which each run's spans are taken by trace id.
    OpenTelemetry allows one global provider per process, so a second call
    returns the first call's collector.
    """
    global _collector
    if _collector is not None:
        return _collector
    disable_content_capture()
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    collector = RunCollector()
    provider.add_span_processor(SimpleSpanProcessor(collector))
    if cloud_trace_project:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(CloudTraceSpanExporter(project_id=cloud_trace_project))
        )
    trace.set_tracer_provider(provider)
    _collector = collector
    return collector


_collector: RunCollector | None = None


def tracer() -> trace.Tracer:
    """This repo's tracer."""
    return trace.get_tracer(TRACER_NAME)


def start_attributes(
    *, run_phase: str, execution: int, question_id: str, group: str, model: str,
    golden_set_version: int, contract_version: str, registry_sha256: str,
) -> dict[str, Any]:  # fmt: skip
    """What the root span knows before the agent starts."""
    return {
        GEN_AI_OPERATION_NAME: "invoke_agent",
        GEN_AI_AGENT_NAME: "analyst",
        GEN_AI_PROVIDER_NAME: "gcp.vertex_ai",
        GEN_AI_REQUEST_MODEL: model,
        PHASE: run_phase,
        EXECUTION: execution,
        QUESTION_ID: question_id,
        QUESTION_GROUP: group,
        GOLDEN_SET_VERSION: golden_set_version,
        CONTRACT_VERSION: contract_version,
        REGISTRY_SHA: registry_sha256[:12],
    }


def end_attributes(row: dict[str, Any], owners: dict[str, str]) -> dict[str, Any]:
    """What the root span learns from the saved run record.

    ``owners`` maps definition id to its owner, from the registry. Only values
    OpenTelemetry can carry are returned (strings, numbers, booleans, lists of strings).
    """
    cited = list(row.get("sources_cited") or [])
    served = list(row.get("served_by_agent_record") or [])
    named = [c.split("@")[0] for c in cited]
    attrs: dict[str, Any] = {
        RUN_ID: str(row["run_id"]),
        GEN_AI_CONVERSATION_ID: str(row["run_id"]),
        GEN_AI_RESPONSE_MODEL: str(row.get("model_reported") or ""),
        GEN_AI_USAGE_INPUT_TOKENS: int(row.get("input_tokens_total") or 0),
        GEN_AI_USAGE_OUTPUT_TOKENS: int(row.get("output_tokens") or 0),
        GEN_AI_USAGE_CACHE_READ: int(row.get("cache_read_tokens") or 0),
        DEFINITIONS_CITED: cited,
        DEFINITIONS_SERVED: served,
        DEFINITION_OWNERS: sorted({owners.get(n, "unregistered") for n in named}),
        MODEL_CALLS: int(row.get("model_calls") or 0),
        SQL_QUERIES: int(row.get("query_count") or 0),
        CONTRACT_CALLS: int(row.get("contract_calls") or 0),
        COST_USD: float(row.get("cost_usd") or 0.0),
        LATENCY_S: float(row.get("seconds") or 0.0),
        OUTCOME: str(row["outcome"]),
        EXTRACTED: str(row.get("extracted") or "")[:200],
        GOLD: str(row.get("gold")),
        DECOY: str(row.get("matched_decoy") or ""),
    }
    if row.get("timed_out"):
        attrs[ERROR_TYPE] = "timeout"
    elif row.get("error"):
        attrs[ERROR_TYPE] = str(row["error"]).split(":")[0][:80]
    return attrs


def score_attributes(row: dict[str, Any]) -> dict[str, Any]:
    """The score span's attributes."""
    return {
        RUN_ID: str(row["run_id"]),
        OUTCOME: str(row["outcome"]),
        EXTRACTED: str(row.get("extracted") or "")[:200],
        GOLD: str(row.get("gold")),
        DECOY: str(row.get("matched_decoy") or ""),
    }
