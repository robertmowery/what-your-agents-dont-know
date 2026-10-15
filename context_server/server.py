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

"""The context server: the contract over MCP (streamable HTTP), for Cloud Run.

Secured. On Cloud Run the service accepts only callers with the
``roles/run.invoker`` role, each agent under its own service account (see
``infra/part3``). Cloud Run checks the caller's Google ID token before a
request reaches this code. The server refuses, as well, any request that
arrives without a caller identity, so a deployment that was opened to the
public by mistake still answers nobody.

Observable. Every operation writes one JSON line to standard output, which
Cloud Logging stores as a structured entry: caller, operation, contract
version, time, response ID, the run ID the caller sent, and (from contract
2.0.0) the definitions the response served, as ``id@version``.

Usage (inside the container; see Dockerfile):
    python -m context_server.server            # listens on $PORT, default 8080
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from context_server import contract

RUN_HEADER = "x-tessaway-run"
LOG_EVENT = "contract_call"
# Paths that answer without a caller identity: the container's own health check.
OPEN_PATHS = frozenset({"/healthz"})


def _emit_stdout(line: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(line, default=str) + "\n")
    sys.stdout.flush()


# Where log lines go. Tests replace it to read them back.
emit: Callable[[dict[str, Any]], None] = _emit_stdout


def caller_from_headers(headers: Any) -> str:
    """Return the caller's email from its Google ID token, or "" when there is none.

    Cloud Run has already checked the token, and it passes the token on with
    its signature removed, so the payload is read here and not checked again.
    """
    if not headers:
        return ""
    for name in ("x-serverless-authorization", "authorization"):
        value = headers.get(name) or ""
        scheme, _, token = value.partition(" ")
        if scheme.lower() != "bearer" or token.count(".") < 1:
            continue
        payload = token.split(".")[1]
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except (ValueError, UnicodeDecodeError):
            continue
        caller = claims.get("email") or claims.get("sub") or ""
        if caller:
            return str(caller)
    return ""


class RequireCaller:
    """Refuse any request that carries no caller identity, before MCP sees it."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the MCP app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Let a request through only when it says who is calling."""
        if scope["type"] == "http" and scope.get("path") not in OPEN_PATHS:
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if not caller_from_headers(headers):
                body = json.dumps({"error": "unauthenticated: no caller identity"}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        if scope["type"] == "http" and scope.get("path") == "/healthz":
            body = json.dumps(
                {"contract": contract.CONTRACT_NAME, "version": contract.CONTRACT_VERSION}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def _respond(
    ctx: Context | None,
    operation: str,
    work: Callable[[dict[str, Any]], dict[str, Any]],
    arguments: dict[str, Any] | None = None,
) -> str:
    """Run one operation, stamp the response, and write the log line.

    The log line names each definition the response served, as ``id@version``,
    so the server's own record says which definitions reached which run.
    """
    started = time.perf_counter()
    record: dict[str, Any] = {}
    try:
        result = work(record)
    except Exception as exc:  # noqa: BLE001 - an operation's failure is returned to the caller
        result = {"error": f"{type(exc).__name__}: {exc}"[:1500]}
    reply = contract.envelope(operation, result, arguments)
    headers = None
    if ctx is not None:
        try:
            headers = ctx.headers
        except (ValueError, AttributeError):
            headers = None
    emit(
        {
            "severity": "INFO",
            "message": LOG_EVENT,
            "event": LOG_EVENT,
            "caller": caller_from_headers(headers) or "unknown",
            "operation": operation,
            "contract_version": reply["contract_version"],
            "response_id": reply["response_id"],
            "definitions": [f"{d['id']}@{d['version']}" for d in reply["definitions"]],
            "run_id": (headers or {}).get(RUN_HEADER, "") if headers else "",
            "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "ok": "error" not in result,
            "ms": round((time.perf_counter() - started) * 1000),
            "bytes_billed": int(record.get("bytes_billed") or 0),
        }
    )
    return json.dumps(reply, default=str)


def build_server(state: contract.State) -> MCPServer:
    """Return the MCP server with the four operations and nothing else."""
    server = MCPServer(
        name=contract.CONTRACT_NAME,
        version=contract.CONTRACT_VERSION,
        instructions=(
            "Tessaway Freight's context contract. Every response carries the contract version,"
            " a response ID, and the definitions it served with their id, version and owner."
        ),
    )

    async def lookup_definition(ctx: Context, term: str = "") -> str:
        return await anyio.to_thread.run_sync(
            _respond, ctx, contract.LOOKUP_DEFINITION, lambda _: contract.lookup_definition(term)
        )

    async def compute_metric(
        ctx: Context,
        metrics: list[str],
        group_by: list[str] | None = None,
        where: list[str] | None = None,
        start_date: str = "",
        end_date: str = "",
        order_by: list[str] | None = None,
        limit: int = 50,
    ) -> str:
        def work(record: dict[str, Any]) -> dict[str, Any]:
            return contract.compute_metric(
                metrics, group_by, where, start_date, end_date, order_by, limit, record
            )

        return await anyio.to_thread.run_sync(
            _respond, ctx, contract.COMPUTE_METRIC, work, {"metrics": list(metrics or [])}
        )

    async def check_rule(ctx: Context, rule: str = "") -> str:
        return await anyio.to_thread.run_sync(
            _respond, ctx, contract.CHECK_RULE, lambda _: contract.check_rule(state, rule)
        )

    async def resolve_entity(ctx: Context, name_or_id: str) -> str:
        return await anyio.to_thread.run_sync(
            _respond,
            ctx,
            contract.RESOLVE_ENTITY,
            lambda _: contract.resolve_entity(state, name_or_id),
        )

    for operation, fn in (
        (contract.LOOKUP_DEFINITION, lookup_definition),
        (contract.COMPUTE_METRIC, compute_metric),
        (contract.CHECK_RULE, check_rule),
        (contract.RESOLVE_ENTITY, resolve_entity),
    ):
        server.add_tool(
            fn,
            name=operation,
            description=contract.description(operation),
            structured_output=False,
        )
    return server


def build_app(state: contract.State) -> ASGIApp:
    """Return the HTTP app: the MCP endpoint at /mcp, behind the caller check."""
    server = build_server(state)
    app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        # Cloud Run fronts the service with its own host name; it, not this
        # check, decides who can reach the container.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return RequireCaller(app)


def main() -> None:
    """Load the layers, then serve."""
    import uvicorn

    from tessaway.layers import graph, semantic

    started = time.perf_counter()
    state = contract.build_state(graph.rows_from_bigquery())
    semantic.worker()
    emit(
        {
            "severity": "INFO",
            "message": "contract_server_ready",
            "event": "ready",
            "contract_version": contract.CONTRACT_VERSION,
            "operations": list(contract.OPERATIONS),
            "rules": len(state.rules),
            "seconds_to_start": round(time.perf_counter() - started, 1),
        }
    )
    uvicorn.run(build_app(state), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
