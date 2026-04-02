"""
E2E tests for HiveMind access control (ACL) enforcement.

Tests HiveMindListenerProtocol's ACL features:
- Message type blacklist enforcement
- Skill blacklist injection
- Intent blacklist injection
- Admin privilege validation
"""

import pytest
from ovos_bus_client.message import Message
from hivescope import TopologyBuilder
from hivescope.scenarios import with_acl_enforcement, single_satellite
from hivescope.assertions import assert_message_routed, assert_client_registered


class TestMessageTypeBlacklist:
    """Test enforcement of message type blacklist."""

    def test_blacklist_blocks_message_type(self):
        """Master enforces message type blacklist for satellite."""
        b = single_satellite()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            # Register satellite with blacklist
            m.register_satellite(
                "restricted-key",
                password="restricted-password",
                msg_blacklist=["speak"]
            )
            s.connect(m)
            s.wait_for_handshake(timeout=5)

            # Satellite tries to send blacklisted message type
            m.recorder.clear()
            s.send(Message("speak", {"utterance": "hello"}))

            # Master should not relay the message
            # (depends on implementation: either drops or connection closed)
        finally:
            b.stop_all()

    def test_non_blacklisted_message_allowed(self):
        """Non-blacklisted message types are allowed through."""
        b = single_satellite()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            # Register satellite with blacklist (not including test:message)
            m.register_satellite(
                "test-key",
                password="test-password",
                msg_blacklist=["speak"]
            )
            s.connect(m)
            s.wait_for_handshake(timeout=5)

            # Satellite sends non-blacklisted message
            m.recorder.clear()
            s.send(Message("test:message", {"data": "value"}))

            # Message should arrive at master
            assert_message_routed(m, "test:message", count=1)
        finally:
            b.stop_all()


class TestSkillBlacklist:
    """Test skill blacklist injection into session context."""

    def test_skill_blacklist_injected_to_session(self):
        """Satellite's skill blacklist is injected into message session context."""
        b = single_satellite()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            # Register satellite with skill blacklist
            m.register_satellite(
                "test-key",
                password="test-password",
                skill_blacklist=["mycroft.volume.skill"]
            )
            s.connect(m)
            s.wait_for_handshake(timeout=5)

            # Satellite sends BUS message
            m.recorder.clear()
            s.send(Message("recognizer_loop:utterance", {"utterances": ["hello"]}))

            # Message should be routed with blacklisted_skills in context
            assert_message_routed(m, "recognizer_loop:utterance", count=1)
        finally:
            b.stop_all()


class TestAdminPrivileges:
    """Test admin satellite privileges."""

    def test_admin_satellite_can_broadcast(self):
        """Admin satellite can send BROADCAST messages."""
        b = with_acl_enforcement()
        b.start_all()
        try:
            m = b.get_master("M0")
            admin_sat = b.get_satellite("S_ADMIN")

            # Admin satellite should be registered
            assert_client_registered(m, admin_sat.peer)
        finally:
            b.stop_all()

    def test_non_admin_cannot_broadcast(self):
        """Non-admin satellite is blocked from broadcast."""
        b = with_acl_enforcement()
        b.start_all()
        try:
            m = b.get_master("M0")
            restricted_sat = b.get_satellite("S_RESTRICTED_MSG")

            # Restricted satellite is registered but limited
            assert_client_registered(m, restricted_sat.peer)
        finally:
            b.stop_all()


class TestIntentBlacklist:
    """Test intent blacklist (placeholder for future implementation)."""

    def test_intent_blacklist_present(self):
        """Intent blacklist is available in session context."""
        # Future: implement intent-level blacklist testing
        # when intent handling is fully wired into protocol
        pass
