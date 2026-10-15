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

"""How an agent reaches the deployed context server, and under which identity.

The service's URL and the agents' service accounts come from the Part 3
Terraform outputs (``infra/part3``) at run time. Neither is written to the
results: ``scrub`` replaces both, and the project id, before anything is saved.

Each agent calls under its own service account. The run mints that account's
Google ID token by impersonation, with the operator's own Application Default
Credentials and the ``roles/iam.serviceAccountOpenIdTokenCreator`` grant in
``infra/part3``. No key file exists for any of these accounts.
"""

from __future__ import annotations

import functools
import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request

from tessaway import config

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = ROOT / "infra" / "part3"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
URL_PLACEHOLDER = "CONTRACT_URL"
PROJECT_PLACEHOLDER = "PROJECT"

# Mint a new token when the cached one has less than this many seconds left.
_REFRESH_MARGIN_S = 600


@dataclass(frozen=True)
class Deployment:
    """Where the contract is served, and who may call it."""

    url: str  # the service URL; the MCP endpoint is url + "/mcp"
    callers: dict[str, str]  # configuration name -> service account email

    @property
    def endpoint(self) -> str:
        """The MCP endpoint."""
        return self.url.rstrip("/") + "/mcp"


@functools.cache
def deployment() -> Deployment:
    """Read the service URL and the callers from the Part 3 Terraform outputs."""
    found = subprocess.run(
        ["terraform", "output", "-json"],
        cwd=TERRAFORM_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    outputs = json.loads(found.stdout)
    url = str(outputs["service_url"]["value"])
    if not url:
        raise SystemExit("The context server is not deployed: see infra/part3/README.md.")
    return Deployment(url=url, callers=dict(outputs["callers"]["value"]))


_tokens: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def id_token(service_account: str, audience: str) -> str:
    """Return a Google ID token for ``service_account``, minted by impersonation."""
    with _lock:
        cached = _tokens.get(service_account)
        if cached and cached[1] - time.time() > _REFRESH_MARGIN_S:
            return cached[0]
        config.project()  # pin the quota project before any credential is made
        source, _ = google.auth.default(scopes=SCOPES)
        target = impersonated_credentials.Credentials(
            source_credentials=source, target_principal=service_account, target_scopes=SCOPES
        )
        minted = impersonated_credentials.IDTokenCredentials(
            target, target_audience=audience, include_email=True
        )
        minted.refresh(Request())
        expiry = minted.expiry.timestamp() if minted.expiry else time.time() + 3000
        _tokens[service_account] = (str(minted.token), expiry)
        return str(minted.token)


def scrub(text: str) -> str:
    """Remove the service URL and the project id from text that is about to be saved."""
    if not text:
        return text
    try:
        url = deployment().url
    except (subprocess.CalledProcessError, FileNotFoundError, SystemExit, KeyError):
        url = ""
    if url:
        text = text.replace(url, URL_PLACEHOLDER).replace(
            url.removeprefix("https://"), URL_PLACEHOLDER
        )
    project = config.project()
    return text.replace(project, PROJECT_PLACEHOLDER)
