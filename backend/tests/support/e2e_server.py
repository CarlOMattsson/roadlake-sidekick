"""A real Sidekick server on the loopback for the browser e2e suite (frontend/tests/e2e-real).

Run it from `backend/` with the test database environment loaded (`tools/test-db-pool.sh env K`):

    python -m tests.support.e2e_server

It migrates and empties the test database, creates one user with a personal token, serves the full
application (the MCP endpoint at `/mcp/`) with uvicorn on a free loopback port, and prints one JSON
line `{"url": ..., "token": ...}` once the server accepts requests. The process runs until it is
stopped. Only the guarded test database is touched, and the token exists for this run only.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys

import uvicorn

from sidekick.api.app import create_app
from sidekick.shared.auth import MCP_SCOPES
from tests.db import database_factory
from tests.support.settings import make_settings

LOOPBACK = "127.0.0.1"


async def serve() -> None:
    app = create_app(make_settings(), database_factory())
    auth = app.state.container.auth
    user_id = auth.provision_user("e2e-owner", "E2E Owner")
    token = auth.create_personal_token(user_id, "e2e", scopes=frozenset(MCP_SCOPES))
    listener = socket.socket()
    listener.bind((LOOPBACK, 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    started = asyncio.ensure_future(server.serve(sockets=[listener]))
    while not server.started:
        if started.done():
            await started
        await asyncio.sleep(0.05)
    print(json.dumps({"url": f"http://{LOOPBACK}:{port}", "token": token}), flush=True)
    await started


if __name__ == "__main__":
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        sys.exit(0)
