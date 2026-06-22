# hivemind-core
# Copyright (C) 2026 Casimiro Ferreira
# SPDX-License-Identifier: Apache-2.0
import os
import time
import argparse
from ovos_utils.log import init_service_logger, LOG
from ovos_utils.xdg_utils import xdg_state_home
from hivemind_core.service import HiveMindService


def parse_args():
    parser = argparse.ArgumentParser(description="Run the HiveMind service.")
    parser.add_argument('--log-level', type=str, default="DEBUG", help="Set the logging level (e.g., DEBUG, INFO, ERROR).")
    parser.add_argument('--log-path', type=str, default=None, help="Set the directory path for logs.")
    parser.add_argument(
        '--with-admin',
        action='store_true',
        help="Start the HiveMind Admin Panel web UI (requires hivemind-core[admin])."
    )
    parser.add_argument(
        '--admin-host',
        type=str,
        default="127.0.0.1",
        help="Admin Panel host (default: 127.0.0.1). Requires --with-admin."
    )
    parser.add_argument(
        '--admin-port',
        type=int,
        default=8100,
        help="Admin Panel port (default: 8100). Requires --with-admin."
    )
    return parser.parse_args()


def start_admin_with_error(host, port, error):
    """Start the admin panel with error diagnostics when core failed to start.

    The admin panel is an optional, standalone package (hivemind-admin-panel).
    It is only imported here, lazily, so core has no hard dependency on it.
    """
    from hivemind_admin_panel import start_admin_server, init_injected_objects

    db = None
    try:
        from hivemind_core.database import ClientDatabase
        from hivemind_core.config import get_server_config

        cfg = get_server_config()
        try:
            db = ClientDatabase()
        except Exception:
            # Fallback to JSON backend so the panel can still inspect clients
            cfg['database'] = {
                'module': 'hivemind-json-db-plugin',
                'hivemind-json-db-plugin': {
                    'name': 'clients',
                    'subfolder': 'hivemind-core'
                }
            }
            cfg.store()
            LOG.warning("Switched to JSON database backend")
            db = ClientDatabase()
    except Exception as db_err:
        LOG.error("Could not create database: %s", db_err)

    init_injected_objects(service=None, db=db, protocol=None, startup_error=error)
    start_admin_server(host=host, port=port)


def main():
    args = parse_args()

    # Set log level
    init_service_logger("core")
    LOG.set_level(args.log_level)

    # Set log path if provided, otherwise use default
    if args.log_path:
        LOG.base_path = args.log_path
    else:
        LOG.base_path = os.path.join(xdg_state_home(), "hivemind")

    if LOG.base_path == "stdout":
        LOG.info("logs printed to stdout (not saved to file)")
    else:
        LOG.info(f"log files can be found at: {LOG.base_path}/core.log")

    try:
        service = HiveMindService()

        if args.with_admin:
            service._admin_enabled = True
            service._admin_host = args.admin_host
            service._admin_port = args.admin_port
            LOG.info(f"Admin Panel will start at http://{args.admin_host}:{args.admin_port}/")

        service.run()

    except Exception as e:
        error_msg = f"Failed to start HiveMind service: {e}"
        LOG.exception(error_msg)

        # Start the admin panel for error diagnostics if requested
        if args.with_admin:
            time.sleep(0.5)  # let log output flush before the admin server starts
            start_admin_with_error(host=args.admin_host, port=args.admin_port, error=e)
            LOG.warning("Admin Panel started for error diagnostics at http://%s:%s/",
                        args.admin_host, args.admin_port)
            from ovos_utils import wait_for_exit_signal
            wait_for_exit_signal()
        else:
            raise


if __name__ == "__main__":
    main()
