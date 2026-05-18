"""Policy hooks exercised through a hivescope master/satellite topology."""

import dataclasses
import time
from typing import Any, Dict

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope.scenarios import admin_satellite

import hivemind_core.protocol as protocol_module


try:
    from hivemind_plugin_manager.protocols import PolicyContext, PolicyDecision
except ImportError:
    @dataclasses.dataclass
    class PolicyContext:
        client: Any = None
        user: Any = None
        source_ip: str = ""
        metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    @dataclasses.dataclass
    class PolicyDecision:
        allowed: bool = True
        reason: str = ""
        code: str = ""
        message_type: str = "hive.policy.denied"
        data: Dict[str, Any] = dataclasses.field(default_factory=dict)
        context_patch: Dict[str, Any] = dataclasses.field(default_factory=dict)
        stop_processing: bool = False


class CapturePolicy:
    def __init__(self, decision=None):
        self.decision = decision or PolicyDecision()
        self.contexts = []
        self.recorded = []
        self.hm_protocol = None

    def authorize_hive_message(self, message, context):
        self.contexts.append(("hive", context))
        return PolicyDecision()

    def authorize_bus_message(self, message, context):
        self.contexts.append(("bus", context))
        return self.decision

    def authorize_binary_payload(self, message, context):
        return PolicyDecision()

    def record_bus_message(self, message, context, result=None):
        self.recorded.append((message, context, result))


def _wait_for(condition, timeout: float = 2.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


def _attach_policy(monkeypatch, master, policy):
    monkeypatch.setattr(protocol_module, "PolicyContext", PolicyContext)
    monkeypatch.setattr(protocol_module, "PolicyDecision", PolicyDecision)
    policy.hm_protocol = master.hm_protocol
    master.hm_protocol.policy_protocols = [policy]


def _send_utterance(satellite, session_id=None):
    session_id = session_id or satellite.shim.session_id
    satellite.send(HiveMessage(
        HiveMessageType.BUS,
        payload=Message(
            "recognizer_loop:utterance",
            {"utterances": ["hello"]},
            {
                "session": {
                    "session_id": session_id,
                    "site_id": "client-site",
                },
                "api_key": "client-controlled",
            },
        ),
    ))


def test_policy_denial_blocks_bus_emit_and_notifies_satellite(monkeypatch):
    policy = CapturePolicy(PolicyDecision(
        allowed=False,
        reason="quota exceeded",
        code="quota_exceeded",
        data={"period": "daily"},
    ))
    b = admin_satellite()
    try:
        m = b.get_master("M0")
        _attach_policy(monkeypatch, m, policy)
        b.start_all()
        s = b.get_satellite("S0")

        denied = []
        s.shim.emitter.on(HiveMessageType.BUS, denied.append)

        _send_utterance(s)

        assert _wait_for(lambda: len(denied) >= 1), "policy denial was not sent downstream"
        assert not any(
            msg.msg_type == "recognizer_loop:utterance"
            for msg in m.agent_protocol.injected
        ), m.agent_protocol.injected
        assert denied[0].payload.msg_type == "hive.policy.denied"
        assert denied[0].payload.data["code"] == "quota_exceeded"
        assert denied[0].payload.data["reason"] == "quota exceeded"
        assert denied[0].payload.data["period"] == "daily"
        assert policy.recorded == []
    finally:
        b.stop_all()


def test_policy_context_patch_reaches_master_bus_with_server_user_context(monkeypatch):
    policy = CapturePolicy(PolicyDecision(
        context_patch={
            "session": {
                "blacklisted_intents": ["quota.intent"],
                "blacklisted_skills": ["quota.skill"],
            }
        }
    ))
    b = admin_satellite()
    try:
        m = b.get_master("M0")
        _attach_policy(monkeypatch, m, policy)
        b.start_all()
        s = b.get_satellite("S0")

        _send_utterance(s)

        assert _wait_for(lambda: any(
            msg.msg_type == "recognizer_loop:utterance"
            for msg in m.agent_protocol.injected
        )), m.agent_protocol.injected

        emitted = m.agent_protocol.last_injected("recognizer_loop:utterance")
        session = emitted.context["session"]
        assert "quota.intent" in session["blacklisted_intents"]
        assert "quota.skill" in session["blacklisted_skills"]

        bus_context = [ctx for hook, ctx in policy.contexts if hook == "bus"][-1]
        assert bus_context.client.key == s.identity.access_key
        assert bus_context.user.api_key == s.identity.access_key
        assert bus_context.user.name == "test-satellite"
        assert policy.recorded
        assert policy.recorded[-1][0].msg_type == "recognizer_loop:utterance"
    finally:
        b.stop_all()
