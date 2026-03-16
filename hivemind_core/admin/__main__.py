# hivemind-admin
# Copyright (C) 2026 HiveMind Community
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""Main entry point for HiveMind-admin.

This module provides the FastAPI application that serves both the REST API
and the static web UI for HiveMind-core management.

When started via hivemind-core with --with-admin flag, this module has
direct access to internal HiveMind-core objects.

Example:
    ```bash
    # Standalone mode
    hivemind-admin --host 0.0.0.0 --port 9000 --reload

    # Integrated with hivemind-core
    hivemind-core listen --with-admin --admin-port 8000
    ```
"""

import argparse
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from hivemind_core.admin.api import app as api_app
from hivemind_core.admin.version import __version__

__all__ = ["app", "main"]

#: Directory containing static files (SPA web UI)
static_dir = Path(__file__).parent / "static"

#: Main FastAPI application instance
app = FastAPI(title="HiveMind Admin")

# Mount the API app under /api prefix
app.mount("/api", api_app)

# Mount static files for direct access (CSS, JS, images)
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root() -> FileResponse:
    """Serve the main index.html file for the SPA.

    Returns:
        FileResponse: The index.html file from static directory.
    """
    return FileResponse(static_dir / "index.html")


@app.get("/index.html")
async def index() -> FileResponse:
    """Serve the main index.html file for the SPA.

    Returns:
        FileResponse: The index.html file from static directory.
    """
    return FileResponse(static_dir / "index.html")


def main() -> None:
    """Start the HiveMind Admin uvicorn server.

    Parses command-line arguments and starts the uvicorn ASGI server
    with the specified configuration.

    CLI Args:
        --host: Server host (default: 127.0.0.1)
        --port: Server port (default: 8000)
        --reload: Enable auto-reload for development
        --version: Show version and exit

    Note:
        Default credentials are admin/admin. Change them in
        ~/.config/hivemind-core/server.json (admin_user, admin_pass).
    """
    parser = argparse.ArgumentParser(description="HiveMind Admin Server")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Server port (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit",
    )

    args = parser.parse_args()

    import uvicorn

    print(f"HiveMind Admin v{__version__}")
    print(f"Starting server on http://{args.host}:{args.port}")
    print("Change admin credentials in server.json: admin_user, admin_pass")

    uvicorn.run(
        "hivemind_core.admin.__main__:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
