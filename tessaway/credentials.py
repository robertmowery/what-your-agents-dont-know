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

"""Where the Anthropic API key comes from. Never from this repository.

The key is read at run time, in this order:

1. ``ANTHROPIC_API_KEY`` in the environment.
2. On macOS, the Keychain item named by ``ANTHROPIC_KEYCHAIN_SERVICE``, read with
   the ``security`` command for the current user.

Nothing here writes the key anywhere, and :func:`redact` removes it from any
text that is about to be logged or saved.
"""

from __future__ import annotations

import os
import subprocess
import sys

KEYCHAIN_SERVICE_ENV = "ANTHROPIC_KEYCHAIN_SERVICE"

MISSING = (
    "No Anthropic API key. Set ANTHROPIC_API_KEY in your shell, or on macOS set "
    "ANTHROPIC_KEYCHAIN_SERVICE to the name of a Keychain item that holds the key."
)


def anthropic_api_key() -> str:
    """Return the Anthropic API key, or raise ``RuntimeError`` if there is none."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    service = os.environ.get(KEYCHAIN_SERVICE_ENV, "").strip()
    if service and sys.platform == "darwin":
        found = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                os.environ.get("USER", ""),
                "-s",
                service,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip()
    raise RuntimeError(MISSING)


def redact(text: str, key: str | None) -> str:
    """Return ``text`` with ``key`` replaced, so an error message can be saved safely."""
    return text.replace(key, "[REDACTED]") if key else text
