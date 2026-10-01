"""The service must build its agent through ``AgentProtocolFactory.create``.

``create`` is the ONLY place the entry-point name a plugin was loaded under is
recorded on the instance, as ``plugin_id`` (hivemind-plugin-manager). The
service used to build ``AgentProtocolFactory.get_class(name)(config=config)``
itself, so ``create`` was never reached on the service path, ``plugin_id`` was
never set, and ``HiveMindListenerProtocol._agent_label`` fell through to the
generic ``hivemind`` on every real deployment. harness-b measured exactly that
on a real bus with a real service and a real client: the Layer-1
``destination`` was ``hivemind`` with AND without the plugin-manager change
that populates the field
(``knowledge/wiki/audits/gate-ledger/live-hivemind-plugin-manager-65.md``).

These cells pin core's half of the pair: the service goes through the factory
and does not touch what the factory recorded. Whether ``create`` labels at all
is the plugin manager's half, and the released 0.10.0a1 does not, which is why
the end-to-end cell supplies a labelling ``create`` instead of asserting
against whatever happens to be installed.
"""
from unittest import mock

import pytest

from hivemind_core import service as service_mod


AGENT_MODULE = "hivemind-ovos-agent-plugin"


class _Agent:
    """Minimal stand-in for an agent plugin instance."""

    def __init__(self, config=None, bus=None, hm_protocol=None):
        self.config = config
        self.bus = bus
        self.hm_protocol = hm_protocol


@pytest.fixture
def agent_config(monkeypatch):
    """A server config naming one agent module, as a deployment has."""
    cfg = {"agent_protocol": {"module": AGENT_MODULE,
                              AGENT_MODULE: {"host": "127.0.0.1"}}}
    monkeypatch.setattr(service_mod, "get_server_config", lambda: cfg)
    return cfg


def test_the_service_builds_through_create_and_not_the_class(agent_config):
    """THE REGRESSION GUARD. A builder that calls ``get_class`` and constructs
    the class itself passes every other cell in this repository while leaving
    ``plugin_id`` unset, because nothing else in core reads it. So the cell has
    to watch which factory method is used, not only what comes back."""
    calls = []

    class SpyFactory:
        @staticmethod
        def create(plugin_name, config=None, bus=None, hm_protocol=None):
            calls.append(("create", plugin_name, config, bus, hm_protocol))
            return _Agent(config=config, bus=bus)

        @staticmethod
        def get_class(plugin_name):  # pragma: no cover - must not be reached
            calls.append(("get_class", plugin_name))
            raise AssertionError(
                "the service built the agent class directly; plugin_id is then "
                "never recorded and the Layer-1 destination stays 'hivemind'")

    monkeypatch_target = "hivemind_core.service.AgentProtocolFactory"
    with mock.patch(monkeypatch_target, SpyFactory):
        builder, config = service_mod.get_agent_protocol()
        svc = service_mod.HiveMindService.__new__(service_mod.HiveMindService)
        svc.agent_retry_delay = 0.0
        agent = svc._start_agent_protocol(builder, config)

    assert [c[0] for c in calls] == ["create"]
    assert calls[0][1] == AGENT_MODULE, "create got the wrong entry-point name"
    assert isinstance(agent, _Agent)
    # the per-module config, not the whole agent_protocol block
    assert calls[0][2] == {"host": "127.0.0.1"}


def test_a_service_built_agent_carries_the_entry_point_id(agent_config):
    """THE CELL THE TASK ASKS FOR. Given a ``create`` that records the name,
    the agent the service hands on carries it. Core must not drop or overwrite
    what the factory set."""

    class LabellingFactory:
        @staticmethod
        def create(plugin_name, config=None, bus=None, hm_protocol=None):
            agent = _Agent(config=config, bus=bus)
            agent.plugin_id = plugin_name  # what the factory does
            return agent

        @staticmethod
        def get_class(plugin_name):  # pragma: no cover - must not be reached
            raise AssertionError(
                "the service built the agent class directly instead of going "
                "through create, so plugin_id is never recorded")

    with mock.patch("hivemind_core.service.AgentProtocolFactory",
                    LabellingFactory):
        builder, config = service_mod.get_agent_protocol()
        svc = service_mod.HiveMindService.__new__(service_mod.HiveMindService)
        svc.agent_retry_delay = 0.0
        agent = svc._start_agent_protocol(builder, config)

    assert agent.plugin_id == AGENT_MODULE


def test_the_label_the_node_stamps_is_the_entry_point_id(agent_config):
    """The point of the whole change, read through the property that stamps it.
    ``_agent_label`` is what goes on the wire as the Layer-1 ``destination``."""
    from hivemind_core.protocol import HiveMindListenerProtocol

    class LabellingFactory:
        @staticmethod
        def create(plugin_name, config=None, bus=None, hm_protocol=None):
            agent = _Agent(config=config, bus=bus)
            agent.plugin_id = plugin_name
            return agent

        @staticmethod
        def get_class(plugin_name):  # pragma: no cover - must not be reached
            raise AssertionError(
                "the service built the agent class directly instead of going "
                "through create, so plugin_id is never recorded")

    with mock.patch("hivemind_core.service.AgentProtocolFactory",
                    LabellingFactory):
        builder, config = service_mod.get_agent_protocol()
        svc = service_mod.HiveMindService.__new__(service_mod.HiveMindService)
        svc.agent_retry_delay = 0.0
        agent = svc._start_agent_protocol(builder, config)

    protocol = HiveMindListenerProtocol.__new__(HiveMindListenerProtocol)
    protocol.agent_protocol = agent
    assert protocol._agent_label == AGENT_MODULE

    # CONTROL: the same property on an agent the factory never labelled is the
    # generic label. This is the state every deployment was in, and it is what
    # the released plugin manager still produces, so it must keep working.
    unlabelled = _Agent()
    protocol.agent_protocol = unlabelled
    assert protocol._agent_label == "hivemind"


def test_the_bus_is_not_passed_from_the_service(agent_config):
    """A REGRESSION GUARD FOR A TRAP, not a style preference.

    ``create`` forwards ``bus`` straight to the plugin, and the plugins compare
    against ``ovos_utils.fakebus.FakeBus`` while ``hivemind_core.service``
    imports ``hivemind_bus_client.fakebus.FakeBus``, a DIFFERENT class. Passing
    this module's ``FakeBus`` would make the plugin's ``isinstance`` check fail,
    so it would keep the fake bus and never connect to the real messagebus: a
    node that looks healthy and answers nothing. Leaving ``bus`` unset gives the
    plugin a false value, which it reads as "build your own"."""
    seen = {}

    class SpyFactory:
        @staticmethod
        def create(plugin_name, config=None, bus=None, hm_protocol=None):
            seen["bus"] = bus
            return _Agent(config=config, bus=bus)

        @staticmethod
        def get_class(plugin_name):  # pragma: no cover - must not be reached
            raise AssertionError(
                "the service built the agent class directly instead of going "
                "through create, so plugin_id is never recorded")

    with mock.patch("hivemind_core.service.AgentProtocolFactory", SpyFactory):
        builder, config = service_mod.get_agent_protocol()
        svc = service_mod.HiveMindService.__new__(service_mod.HiveMindService)
        svc.agent_retry_delay = 0.0
        svc._start_agent_protocol(builder, config)

    assert not seen["bus"], (
        "the service passed a bus; a plugin that isinstance-checks a different "
        "FakeBus class would then never build its real messagebus client")


def test_an_unreachable_backend_is_still_retried(agent_config):
    """The retry loop must survive the move to a builder: an agent that raises
    ConnectionError leaves nothing to build listeners around, and exiting would
    take the hive down until a human restarts it."""
    attempts = []

    class StubbornFactory:
        @staticmethod
        def create(plugin_name, config=None, bus=None, hm_protocol=None):
            attempts.append(config)
            if len(attempts) < 3:
                raise ConnectionError("backend is not up")
            return _Agent(config=config)

        @staticmethod
        def get_class(plugin_name):  # pragma: no cover - must not be reached
            raise AssertionError(
                "the service built the agent class directly instead of going "
                "through create, so plugin_id is never recorded")

    with mock.patch("hivemind_core.service.AgentProtocolFactory",
                    StubbornFactory):
        builder, config = service_mod.get_agent_protocol()
        svc = service_mod.HiveMindService.__new__(service_mod.HiveMindService)
        svc.agent_retry_delay = 0.0
        agent = svc._start_agent_protocol(builder, config)

    assert isinstance(agent, _Agent)
    assert len(attempts) == 3
