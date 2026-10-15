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

"""Settings for the experiment: the cloud project, the dataset, and the pinned models.

Nothing here is a secret. Authentication is Application Default Credentials
(``gcloud auth application-default login``). The project always comes from the
environment and is passed to every client explicitly, so a different default
project on the machine is never picked up by accident.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

load_dotenv()

DATASET = os.environ.get("BQ_DATASET", "tessaway_wh")
BQ_LOCATION = os.environ.get("BQ_LOCATION", "US")
GEMINI_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
CLAUDE_VERTEX_REGION = os.environ.get("CLAUDE_VERTEX_REGION", "global")
# How the Claude agent reaches Claude: "anthropic" (Anthropic's API, key read at
# run time, see tessaway/credentials.py) or "vertex" (Vertex AI, no key).
CLAUDE_ROUTE = os.environ.get("CLAUDE_ROUTE", "anthropic").strip().lower()

# The date the model names and prices below were checked against the provider
# listings for the project. Recorded in every results file.
MODELS_VERIFIED_ON = "2026-10-09"

# BigQuery on-demand analysis price, US multi-region, dollars per tebibyte.
BQ_USD_PER_TIB = 6.25


def project() -> str:
    """Return the Google Cloud project, and make it the quota project too."""
    value = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not value or value == "your-project-id":
        raise SystemExit("Set GOOGLE_CLOUD_PROJECT in .env (copy .env.example).")
    # User credentials carry their own quota project. Pin it to this project so
    # no request is ever attributed to whatever the machine default happens to be.
    os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] = value
    return value


# What a saved results file or export says in place of the Google Cloud project.
PROJECT_PLACEHOLDER = "PROJECT"


def redact_project(value: Any, project_id: str | None = None) -> Any:
    """Return ``value`` with the Google Cloud project ID replaced by ``PROJECT_PLACEHOLDER``.

    MetricFlow and dbt write fully qualified table names, so the project ID ends
    up in generated SQL and in exports. Results files and exports are published
    with the code, and the project is the reader's own, so it is never saved.
    Strings are rewritten anywhere inside dicts and lists; other values are
    returned unchanged. With no project set there is nothing to replace.

    Args:
        value: A string, or a dict or list holding strings anywhere inside it.
        project_id: The ID to replace. Defaults to ``GOOGLE_CLOUD_PROJECT``.
    """
    if project_id is None:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project_id or project_id == PROJECT_PLACEHOLDER:
        return value
    if isinstance(value, str):
        return value.replace(project_id, PROJECT_PLACEHOLDER)
    if isinstance(value, list):
        return [redact_project(item, project_id) for item in value]
    if isinstance(value, dict):
        return {key: redact_project(item, project_id) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class ModelConfig:
    """One agent configuration: a runtime, a pinned model, and its list prices.

    Prices are dollars per million tokens on the Vertex AI global endpoint, as
    published on ``MODELS_VERIFIED_ON``. They are used to estimate what a run
    cost; the invoice is the authority.
    """

    key: str
    runtime: str  # "adk" or "claude_sdk"
    vendor: str
    model: str
    tier: str  # "base" or "strong"
    usd_in: float
    usd_out: float
    usd_cache_read: float
    usd_cache_write: float

    def cost(
        self, *, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0
    ) -> float:
        """Estimate dollars for one run.

        Args:
            input_tokens: Input tokens billed at the full rate (not cached).
            output_tokens: Output tokens, including thinking tokens.
            cache_read: Input tokens read from a cache.
            cache_write: Input tokens written to a cache.
        """
        return (
            input_tokens * self.usd_in
            + output_tokens * self.usd_out
            + cache_read * self.usd_cache_read
            + cache_write * self.usd_cache_write
        ) / 1_000_000


CONFIGS: dict[str, ModelConfig] = {
    c.key: c
    for c in [
        # Gemini 3.8 Flash is on promotional pricing through December 31, 2026.
        ModelConfig(
            "adk_gemini_flash", "adk", "google", "gemini-3.8-flash", "base", 0.75, 3.75, 0.075, 0.0
        ),
        ModelConfig(
            "adk_gemini_pro",
            "adk",
            "google",
            "gemini-3.1-pro-preview",
            "strong",
            2.00,
            12.00,
            0.20,
            0.0,
        ),
        ModelConfig(
            "claude_sonnet",
            "claude_sdk",
            "anthropic",
            "claude-sonnet-5-5",
            "base",
            2.00,
            10.00,
            0.10,
            2.50,
        ),
        ModelConfig(
            "claude_opus",
            "claude_sdk",
            "anthropic",
            "claude-opus-5-5",
            "strong",
            4.00,
            20.00,
            0.20,
            5.00,
        ),
    ]
}
