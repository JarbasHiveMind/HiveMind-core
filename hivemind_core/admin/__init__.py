# hivemind-admin
# Copyright (C) 2026 Casimiro Ferreira
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
"""HiveMind Admin - Web-based management UI for HiveMind-core.

This module provides a web-based administration interface for HiveMind-core,
allowing management of clients, permissions, and server configuration via
a REST API and web UI.

When hivemind-core is started with --with-admin flag, this module gets
direct access to internal HiveMind-core objects for real-time monitoring.
"""

from typing import TYPE_CHECKING

from ovos_utils import create_daemon
from ovos_utils.log import LOG

if TYPE_CHECKING:
    from hivemind_core.service import HiveMindService
    from hivemind_core.database import ClientDatabase
    from hivemind_core.protocol import HiveMindListenerProtocol

__version__ = "0.2.0"
__all__ = ["start_admin_server", "init_injected_objects", "get_admin_app"]


def init_injected_objects(
    service: "HiveMindService" = None,
    db: "ClientDatabase" = None,
    protocol: "HiveMindListenerProtocol" = None,
    startup_error: Exception = None
) -> None:
    """Initialize admin with direct access to core objects.

    Args:
        service: HiveMindService instance.
        db: ClientDatabase instance.
        protocol: HiveMindListenerProtocol instance.
        startup_error: Exception if core failed to start.
    """
    from hivemind_core.admin.api import init_injected_objects as _init
    _init(service=service, db=db, protocol=protocol, logger=LOG, startup_error=startup_error)


def start_admin_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Start the HiveMind Admin web server.

    This function starts a uvicorn server hosting the FastAPI admin interface.
    It should be called after hivemind-core service is running.

    Args:
        host: Host to bind the server (default: 127.0.0.1).
        port: Port to bind the server (default: 8000).
        reload: Enable auto-reload for development (default: False).

    Note:
        This function runs the server in a daemon thread and returns
        immediately. The server will shut down when the main process exits.
    """
    import uvicorn
    from hivemind_core.admin.__main__ import app

    def _run_server():
        LOG.info(f"Starting HiveMind Admin UI at http://{host}:{port}")
        LOG.info("Change admin credentials in ~/.config/hivemind-core/server.json (admin_user, admin_pass)")
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=reload,
            log_level="info",
        )

    # Run server in daemon thread
    create_daemon(_run_server)
    LOG.info("HiveMind Admin server thread started")


def get_admin_app():
    """Get the FastAPI app instance for admin UI.

    Returns:
        FastAPI app configured with all admin routes.
    """
    from hivemind_core.admin.api import get_admin_app
    return get_admin_app()
