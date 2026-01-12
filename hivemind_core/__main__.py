# hivemind-core
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
import os
import argparse
from ovos_utils.log import init_service_logger, LOG
from ovos_utils.xdg_utils import xdg_state_home
from hivemind_core.service import HiveMindService


def parse_args():
    parser = argparse.ArgumentParser(description="Run the HiveMind service.")
    parser.add_argument('--log-level', type=str, default="DEBUG", help="Set the logging level (e.g., DEBUG, INFO, ERROR).")
    parser.add_argument('--log-path', type=str, default=None, help="Set the directory path for logs.")
    return parser.parse_args()


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

    service = HiveMindService()
    service.run()


if __name__ == "__main__":
    main()
