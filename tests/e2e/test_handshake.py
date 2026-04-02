"""
E2E tests for HiveMind protocol handshake and encryption negotiation.

Tests the core HiveMindListenerProtocol's handshake behavior:
- RSA key exchange
- Password-based PAKE
- Pre-shared keys
- Invalid key rejection
"""

import pytest
from hivescope import TopologyBuilder
from hivescope.scenarios import single_satellite
from hivescope.assertions import (
    assert_handshake_complete,
    assert_encryption_match,
    assert_client_not_registered,
)


class TestRSAHandshake:
    """Test RSA-based handshake (no password)."""

    def test_satellite_rsa_handshakes_with_master(self):
        """Satellite completes RSA handshake with master."""
        b = single_satellite()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            # Master has pre-registered the satellite
            m.register_satellite("test-key", password=None)

            # Satellite connects
            s.connect(m)
            s.wait_for_handshake(timeout=5)

            # Verify handshake completed
            assert_handshake_complete(m, s)
        finally:
            b.stop_all()

    def test_invalid_api_key_rejected(self):
        """Master rejects connection with invalid API key."""
        b = single_satellite()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            # Register with correct key, but satellite will try wrong key
            m.register_satellite("correct-key", password=None)

            # Satellite tries to connect with wrong key
            # This should fail (connection closed), but we just verify master
            # doesn't register the peer
            try:
                s.connect(m, force_key="wrong-key")
            except Exception:
                pass  # Connection expected to fail

            # Master should not have registered the satellite
            assert_client_not_registered(m, s.peer)
        finally:
            b.stop_all()


class TestPasswordHandshake:
    """Test password-based PAKE handshake."""

    def test_satellite_password_pake_handshake(self):
        """Satellite completes password-based PAKE handshake."""
        b = single_satellite()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            # Register with password
            m.register_satellite("test-key", password="test-password")

            # Satellite connects
            s.connect(m)
            s.wait_for_handshake(timeout=5)

            # Verify handshake completed
            assert_handshake_complete(m, s)
            # Both should have negotiated the same encryption
            assert_encryption_match(m, s)
        finally:
            b.stop_all()


class TestEncryptionNegotiation:
    """Test encryption algorithm selection."""

    def test_master_and_satellite_agree_on_cipher(self):
        """Master and satellite negotiate matching cipher and encoding."""
        b = single_satellite()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            m.register_satellite("test-key", password="test-password")
            s.connect(m)
            s.wait_for_handshake(timeout=5)

            # Verify encryption settings match
            assert_encryption_match(m, s)
        finally:
            b.stop_all()
