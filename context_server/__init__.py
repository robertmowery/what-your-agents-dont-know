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

"""Part 3: the Part 2 layers served as one contract, over MCP, from Cloud Run.

    contract.py   the four operations, the version, and the envelope every response carries
    server.py     the MCP server: caller identity, one log line per call, the HTTP app
    Dockerfile    the image Cloud Run runs (built from the repo root)

The layers behind the contract are Part 2's, unchanged: ``tessaway/layers``.
"""
