"""The inbound message ACL is not twin-aware while the outbound gate is.

The outbound gate in hivemind-ovos-agent-plugin admits a message type when
the client's allowed_types holds it OR its migration twin
(ovos_spec_tools.migration_counterpart, singleton __init__.py line 406).
The inbound gate, MessageTypeACLPolicy.review in hivemind_core/policy.py,
tests plain membership only. A satellite granted the legacy spelling
(``recognizer_loop:utterance``) is denied the spec spelling
(``ovos.utterance.handle``) on the inbound path, on the same list the
outbound gate admits both spellings on. Node 9 (T-1010, live report from
joergz in the HiveMind Support room) hit exactly this: the twin pair
recognizer_loop:utterance / ovos.utterance.handle was granted as the legacy
spelling and the hub still denied the spec reply.

The fix makes review() admit EITHER spelling of a migrated pair through the
same migration_counterpart() lookup, keeping deny-by-default: a type with
no twin, or an empty allowed_types, still denies.
"""
from unittest.mock import MagicMock
from types import SimpleNamespace
import unittest

from hivemind_core.policy import MessageTypeACLPolicy
from ovos_bus_client.message import Message


def _msg(msg_type):
    return Message(msg_type, {"utterance": "hi"})


def _client(allowed_types):
    db = MagicMock()
    db.get_client_by_api_key = MagicMock(
        return_value=SimpleNamespace(allowed_types=list(allowed_types)))
    c = SimpleNamespace(
        allowed_types=list(allowed_types),
        is_admin=False,
        resolve_user=lambda db_, ttl=5.0, force=False:
            db_.get_client_by_api_key("k"))
    return c, db


class TestACLTwinAwareness(unittest.TestCase):
    def test_legacy_grant_admits_spec_type(self):
        """recognizer_loop:utterance granted -> ovos.utterance.handle admitted,
        the twin pair of the T-1010 node 9 report."""
        c, db = _client(["recognizer_loop:utterance"])
        p = MessageTypeACLPolicy(hm_protocol=SimpleNamespace(db=db))
        v = p.review(_msg("ovos.utterance.handle"), c)
        self.assertFalse(v.denied, v.reason)

    def test_spec_grant_admits_legacy_type(self):
        """The bridge is symmetric: ovos.utterance.handle in the list also
        admits the legacy spelling."""
        c, db = _client(["ovos.utterance.handle"])
        p = MessageTypeACLPolicy(hm_protocol=SimpleNamespace(db=db))
        v = p.review(_msg("recognizer_loop:utterance"), c)
        self.assertFalse(v.denied, v.reason)

    def test_speak_twin_pair_admits_both_spellings(self):
        """speak and speak:b64 pairs behave like the utterance pair."""
        c, db = _client(["speak"])
        p = MessageTypeACLPolicy(hm_protocol=SimpleNamespace(db=db))
        v = p.review(_msg("ovos.utterance.speak"), c)
        self.assertFalse(v.denied, v.reason)

        c2, db2 = _client(["speak:b64_audio"])
        p2 = MessageTypeACLPolicy(hm_protocol=SimpleNamespace(db=db2))
        v2 = p2.review(_msg("ovos.utterance.speak.b64"), c2)
        self.assertFalse(v2.denied, v2.reason)

    def test_unmigrated_type_still_denies(self):
        """Deny-by-default keeps its meaning: a type with no twin admits
        neither spelling."""
        c, db = _client(["recognizer_loop:utterance"])
        p = MessageTypeACLPolicy(hm_protocol=SimpleNamespace(db=db))
        v = p.review(_msg("mycroft.audio.queue.x"), c)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "acl_disallowed_type")

    def test_empty_allowed_types_denies_twin(self):
        """Empty whitelist admits nothing, twin lookup or not."""
        c, db = _client([])
        p = MessageTypeACLPolicy(hm_protocol=SimpleNamespace(db=db))
        v = p.review(_msg("ovos.utterance.handle"), c)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "acl_disallowed_type")


if __name__ == "__main__":
    unittest.main()
