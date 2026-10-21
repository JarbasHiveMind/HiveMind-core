"""Live-OVOS e2e: a satellite QUERY is answered by a REAL OVOS stack (ovoscope's
MiniCroft running an actual skill through the full intent pipeline), and the
spoken answer streams back to the satellite. Unlike the FakeBus e2e, this proves
the async natural_language_query path works against genuine OVOS skills.

Heavy: MiniCroft boots a real OVOS instance (tens of seconds). Skipped where
ovoscope/ovos-core/the test skill aren't installed.
"""
import time
from pathlib import Path

import pytest

pytest.importorskip("hivescope")
pytest.importorskip("ovoscope")
ovoscope_agent = pytest.importorskip("hivescope.plugins.ovoscope_agent")

from hivemind_bus_client.message import HiveMessage, HiveMessageType  # noqa: E402
from ovos_bus_client.message import Message  # noqa: E402
from hivescope.topology import TopologyBuilder  # noqa: E402

_SKILL = "ovos-skill-hello-world.openvoiceos"


def _how_are_you_dialogs():
    """The lines the skill may answer "how are you" with, read from its own files."""
    try:
        import ovos_skill_hello_world
    except ImportError:
        return []
    dialog = (Path(ovos_skill_hello_world.__file__).parent
              / "locale" / "en-US" / "dialog" / "how_are_you.dialog")
    return dialog.read_text().splitlines()


_HOW_ARE_YOU_DIALOGS = _how_are_you_dialogs()


def _has_skill():
    from importlib.metadata import entry_points
    return _SKILL in [e.name for e in entry_points(group="opm.skill")]


@pytest.mark.skipif(not _has_skill(), reason="needs ovos-skill-hello-world")
@pytest.mark.slow
def test_query_answered_by_real_ovos_stack():
    agent = ovoscope_agent.OvoscopeAgentProtocol(skill_ids=[_SKILL])
    b = TopologyBuilder()
    m = b.add_master("M0", agent_protocol=agent)
    m.register_satellite("k", password="p",
                         allowed_types=["recognizer_loop:utterance"])
    b.add_satellite("S0", upstream=m, allowed_types=["recognizer_loop:utterance"])
    b.start_all()
    try:
        s = b.get_satellite("S0")
        inner = HiveMessage(HiveMessageType.BUS,
                            payload=Message("recognizer_loop:utterance",
                                            {"utterances": ["how are you"], "lang": "en-US"}))
        s.send(HiveMessage(HiveMessageType.QUERY, payload=inner,
                           metadata={"query_id": "q1", "originator_peer": s.peer}))
        # wait_for returns the newest record, which is the stream-end frame
        # once the stream has finished, so pick the speak frames instead.
        def spoken():
            return [r.payload["payload"]["data"]["utterance"]
                    for r in s.recorder.received(HiveMessageType.QUERY.value,
                                                 direction="in")
                    if "utterance" in r.payload["payload"]["data"]]

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not spoken():
            time.sleep(0.02)
        assert spoken(), "real-OVOS QUERY answer never reached the satellite"
        assert spoken()[0] in _HOW_ARE_YOU_DIALOGS
    finally:
        b.stop_all()
        try:
            agent.shutdown()
        except Exception:
            pass
