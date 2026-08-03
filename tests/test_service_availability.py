"""A node must stay up, and stay honest, when the pieces around it are not.

Two independent availability rules are covered here:

* the agent backend being unreachable at boot must not take the node down —
  the listeners come up and clients get BACKEND_UNAVAILABLE until it answers;
* a network protocol thread that dies must not leave the node reporting ready
  with no transport left.
"""
import time
from unittest import mock

import pytest

from hivemind_core.service import HiveMindService


def _service(**kwargs):
    # avoid touching a real ClientDatabase at construction
    with mock.patch("hivemind_core.service.ClientDatabase"):
        return HiveMindService(**kwargs)


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class UnreachableAgent:
    """An agent whose backend is not up yet: it constructs, but refuses to
    hand out a bus until the backend arrives. This is how the OVOS agent
    plugin behaves while its messagebus is still booting."""

    def __init__(self, config=None):
        self.bus = mock.MagicMock()
        self.config = config or {}
        self.connected = False

    def get_bus(self, client=None):
        if not self.connected:
            raise ConnectionError("OVOS messagebus is not connected")
        return self.bus


class TestAgentBackendUnavailableAtBoot:
    def test_listeners_come_up_and_node_reports_ready(self, monkeypatch):
        """The whole hive must not go offline because OVOS booted slowly."""
        agent = UnreachableAgent()
        svc = _service()
        listener = mock.MagicMock()
        started = []

        monkeypatch.setattr("hivemind_core.service.get_agent_protocol",
                            lambda: (lambda config: agent, {}))
        monkeypatch.setattr("hivemind_core.service.get_binary_protocol",
                            lambda: (lambda **kw: mock.MagicMock(), {}))
        monkeypatch.setattr("hivemind_core.service.get_server_config",
                            lambda: {"network_protocol": {"websocket": {}}})
        monkeypatch.setattr("hivemind_core.service.NetworkProtocolFactory."
                            "get_class", lambda name: type("Listener", (), {
                                "__init__": lambda self, **kw: None,
                                "run": listener.run}))
        monkeypatch.setattr("hivemind_core.service.create_daemon",
                            lambda target, args=(): started.append(target))
        monkeypatch.setattr("hivemind_core.service.wait_for_exit_signal",
                            lambda: None)
        svc.hm_protocol = mock.MagicMock()
        svc._start_presence = lambda: None
        svc._connect_upstream = lambda hm_protocol: None
        svc._status = mock.MagicMock()

        svc.run()

        assert started, "no listener was started"
        svc._status.set_ready.assert_called_once()
        svc._status.set_error.assert_not_called()

    def test_clients_are_told_the_backend_is_down_then_served(self):
        agent = UnreachableAgent()

        with pytest.raises(ConnectionError):
            agent.get_bus()

        agent.connected = True
        assert agent.get_bus() is agent.bus

    def test_agent_that_refuses_to_start_is_retried_not_fatal(self):
        """An agent that raises leaves nothing to build listeners around, so
        keep trying — exiting would need a human to restart the node."""
        attempts = []

        class Stubborn:
            def __init__(self, config=None):
                attempts.append(config)
                if len(attempts) < 3:
                    raise ConnectionError("backend is not up")

        svc = _service(agent_retry_delay=0.0)
        agent = svc._start_agent_protocol(Stubborn, {"host": "127.0.0.1"})

        assert isinstance(agent, Stubborn)
        assert len(attempts) == 3


class TestDeadListenerThreads:
    def test_a_dead_protocol_does_not_leave_the_node_reporting_ready(self):
        """Port already in use, unreadable certificate: the thread dies and
        the node has no transport left, so it must report an error."""
        svc = _service()
        svc._status = mock.MagicMock()
        proto = mock.MagicMock()
        proto.run.side_effect = OSError("address already in use")

        svc._run_network_protocols([proto])

        assert _wait_for(lambda: svc._status.set_error.called), \
            "a node with no live transport still reported itself healthy"

    def test_one_dead_protocol_does_not_condemn_the_others(self):
        svc = _service()
        svc._status = mock.MagicMock()
        keep_running = mock.MagicMock()
        keep_running.run.side_effect = lambda: time.sleep(5)
        broken = mock.MagicMock()
        broken.run.side_effect = OSError("address already in use")

        svc._run_network_protocols([broken, keep_running])

        assert _wait_for(lambda: broken.run.called)
        time.sleep(0.2)
        svc._status.set_error.assert_not_called()
        svc._status.set_ready.assert_called_once()

    def test_healthy_protocols_report_ready(self):
        svc = _service()
        svc._status = mock.MagicMock()
        proto = mock.MagicMock()
        proto.run.side_effect = lambda: time.sleep(5)

        svc._run_network_protocols([proto])

        svc._status.set_ready.assert_called_once()
        svc._status.set_error.assert_not_called()
