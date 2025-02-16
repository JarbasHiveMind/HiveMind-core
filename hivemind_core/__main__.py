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
