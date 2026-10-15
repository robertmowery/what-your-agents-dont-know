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

"""The Anthropic key is read at run time and never lands in the repository."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tessaway import credentials

ROOT = Path(__file__).resolve().parents[1]
# The shape of an Anthropic API key. Built in pieces so this file does not match itself.
KEY_PATTERN = re.compile("sk-" + "ant-" + r"[A-Za-z0-9_\-]{20,}")


def test_the_environment_variable_is_used_first(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-value-not-a-key")
    monkeypatch.setenv(credentials.KEYCHAIN_SERVICE_ENV, "")
    assert credentials.anthropic_api_key() == "test-value-not-a-key"


def test_a_missing_key_is_an_error_that_says_how_to_set_one(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv(credentials.KEYCHAIN_SERVICE_ENV, "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        credentials.anthropic_api_key()


def test_redact_removes_the_key_from_a_message():
    assert credentials.redact("bad key abc123 refused", "abc123") == "bad key [REDACTED] refused"
    assert credentials.redact("nothing to hide", None) == "nothing to hide"


def test_no_tracked_file_contains_an_anthropic_key():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    leaks = []
    for name in tracked:
        path = ROOT / name
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if KEY_PATTERN.search(text):
            leaks.append(name)
    assert leaks == []
