from hivemind_core.service import HiveMindService
from ovos_utils.log import init_service_logger, LOG
import os

from ovos_utils.xdg_utils import xdg_state_home

from ovos_config.meta import get_xdg_base


def main():
    init_service_logger("core")
    LOG.base_path = os.path.join(xdg_state_home(), "hivemind")
    service = HiveMindService()
    service.run()


if __name__ == "__main__":
    main()
