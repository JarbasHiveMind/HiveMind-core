"""The Noise PSK is derived off the IOLoop and persisted in the client row.

argon2id (time_cost=3, 64 MiB) costs ~750 ms on a half-core container and
used to run inline in ``handle_noise_handshake_message`` on the single
IOLoop thread serving every connected client: N first-time passwords after
a restart meant N x 750 ms of frozen message delivery, serialized however
many cores the node had. Now message 1 is parked while a worker thread
derives the key, the derivation is started as soon as the offer goes out,
and the key is stored in the client's database row (beside the TOFU pin, in
the row that already holds the password it derives from) bound to the node
id and password it was derived for, so a restart re-derives nothing for a
client seen before and a stale key is simply not matched.
"""
import asyncio
import dataclasses
import json
import threading
import unittest
from concurrent.futures import Future as ConcurrentFuture
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_bus_client.noise import (
    NOISE_PATTERN_XX,
    NOISE_SUITES,
    build_prologue,
    noise_protocol_name,
    start_noise_handshake,
)

import hivemind_core.protocol as protocol_module
from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol

NODE_ID = "node-A"
SUITE = NOISE_SUITES[0]
PSK = bytes(range(32))
PASSWORD = "site-password"


class _Row:
    """A client row the way a database plugin hands it back."""

    def __init__(self, metadata=None):
        self.metadata = metadata


class _Db:
    def __init__(self, row):
        self.row = row
        self.updates = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_client_by_api_key(self, key):
        return self.row

    def update_item(self, user):
        self.updates.append(dict(user.metadata or {}))


class _ManualExecutor:
    """A worker pool whose derivations the test completes by hand."""

    def __init__(self):
        self.pending = []

    def submit(self, fn, *args, **kwargs):
        future = ConcurrentFuture()
        self.pending.append(future)
        return future

    def finish(self, index=0, result=PSK):
        # from a thread, as a real worker would: the state copy is queued
        # on the loop, the completion callbacks behind it
        worker = threading.Thread(target=self.pending[index].set_result, args=(result,))
        worker.start()
        worker.join()


def _make_protocol(row, node_id=NODE_ID):
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()
    proto = HiveMindListenerProtocol(agent_protocol=agent, db=_Db(row))
    patcher = patch.object(HiveMindListenerProtocol, "_node_id",
                           new_callable=PropertyMock, return_value=node_id)
    patcher.start()
    return proto, patcher


def _make_client(proto, password=PASSWORD):
    client = HiveMindClientConnection(
        key="api-key", send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=proto, pswd_handshake=SimpleNamespace(password=password))
    client.name = "test-client"
    client.send = MagicMock()
    client._hello_payload = {"node_id": NODE_ID}
    client._handshake_payload = {
        "max_protocol_version": 3,
        "noise": {"patterns": [NOISE_PATTERN_XX], "suites": [SUITE]}}
    return client


def _message_1(client, password=PASSWORD):
    """A real initiator's Noise message 1 for ``client``'s offer."""
    prologue = build_prologue(client._hello_payload, client._handshake_payload,
                              noise_protocol_name(NOISE_PATTERN_XX, SUITE))
    initiator = start_noise_handshake(
        initiator=True, pattern=NOISE_PATTERN_XX, suite=SUITE,
        password=password, node_id=NODE_ID, prologue=prologue)
    msg = initiator.write_message(json.dumps({"binarize": False}).encode())
    return initiator, HiveMessage(HiveMessageType.HANDSHAKE, {
        "noise": {"pattern": NOISE_PATTERN_XX, "suite": SUITE, "msg": msg.hex()}})


def _finish_handshake(proto, client, initiator):
    (msg2,), _ = client.send.call_args
    initiator.read_message(bytes.fromhex(msg2.payload["noise"]["msg"]))
    proto.handle_noise_handshake_message(HiveMessage(HiveMessageType.HANDSHAKE, {
        "noise": {"msg": initiator.write_message(b"").hex()}}), client)


def _bound_row(proto, psk=PSK, password=PASSWORD, **extra):
    metadata = {proto.NOISE_PSK_METADATA_KEY: psk.hex(),
                proto.NOISE_PSK_BINDING_METADATA_KEY: proto._noise_psk_binding(
                    password.encode("utf-8"))}
    metadata.update(extra)
    return _Row(metadata)


async def _settle(turns=3):
    for _ in range(turns):
        await asyncio.sleep(0)


class TestPersistedKey(unittest.TestCase):
    def setUp(self):
        self.row = _Row()
        self.protocol, patcher = _make_protocol(self.row)
        self.addCleanup(patcher.stop)

    def test_a_key_persisted_in_the_row_is_used_without_deriving(self):
        self.row.metadata = _bound_row(self.protocol).metadata
        with patch.object(protocol_module, "derive_psk") as derive:
            psk = self.protocol.noise_psk(PASSWORD, _make_client(self.protocol))
        derive.assert_not_called()
        self.assertEqual(psk, PSK)

    def test_a_derived_key_is_persisted_beside_the_pin_with_its_binding(self):
        self.row.metadata = {"noise_pubkey": "pinned"}
        with patch.object(protocol_module, "derive_psk", return_value=PSK):
            self.protocol.noise_psk(PASSWORD, _make_client(self.protocol))
        self.assertEqual(self.protocol.db.updates, [{
            "noise_pubkey": "pinned", "noise_psk": PSK.hex(),
            "noise_psk_for": self.protocol._noise_psk_binding(PASSWORD.encode())}])

    def test_a_key_bound_to_another_node_id_is_not_matched(self):
        with patch.object(HiveMindListenerProtocol, "_node_id",
                          new_callable=PropertyMock, return_value="node-B"):
            self.row.metadata = _bound_row(self.protocol).metadata  # bound to node-B
        with patch.object(protocol_module, "derive_psk", return_value=b"x" * 32) as derive:
            psk = self.protocol.noise_psk(PASSWORD, _make_client(self.protocol))
        derive.assert_called_once()
        self.assertEqual(psk, b"x" * 32)

    def test_a_key_bound_to_another_password_is_not_matched(self):
        """The password changed under a persisted key: the binding says so,
        deterministically, before any handshake is attempted."""
        self.row.metadata = _bound_row(self.protocol, password="old-password").metadata
        with patch.object(protocol_module, "derive_psk", return_value=b"y" * 32) as derive:
            psk = self.protocol.noise_psk(PASSWORD, _make_client(self.protocol))
        derive.assert_called_once()
        self.assertEqual(psk, b"y" * 32)
        # and the row now carries the key for the current password
        self.assertEqual(self.row.metadata["noise_psk"], (b"y" * 32).hex())

    def test_malformed_persisted_values_are_ignored(self):
        binding = self.protocol._noise_psk_binding(PASSWORD.encode())
        for bad in ("zz", "ab" * 31, 42, None, ["ab" * 32]):
            self.row.metadata = {"noise_psk": bad, "noise_psk_for": binding}
            self.protocol._noise_psks.clear()
            with patch.object(protocol_module, "derive_psk", return_value=b"y" * 32) as derive:
                self.protocol.noise_psk(PASSWORD, _make_client(self.protocol))
            derive.assert_called_once()

    def test_a_row_whose_metadata_is_not_a_dict_is_tolerated(self):
        self.row.metadata = "not a dict"
        with patch.object(protocol_module, "derive_psk", return_value=PSK):
            psk = self.protocol.noise_psk(PASSWORD, _make_client(self.protocol))
        self.assertEqual(psk, PSK)
        self.assertEqual(self.row.metadata["noise_psk"], PSK.hex())

    def test_a_row_without_a_key_gets_one_on_a_memory_hit(self):
        with patch.object(protocol_module, "derive_psk", return_value=PSK):
            self.protocol.noise_psk(PASSWORD, _make_client(self.protocol))
        other_row = _Row()
        self.protocol.db.row = other_row
        other = _make_client(self.protocol)
        other.key = "other-api-key"
        with patch.object(protocol_module, "derive_psk") as derive:
            self.protocol.noise_psk(PASSWORD, other)
        derive.assert_not_called()
        self.assertEqual(other_row.metadata["noise_psk"], PSK.hex())

    def test_a_node_with_the_wrong_password_causes_one_idempotent_write(self):
        """The persisted value is a function of the row's own password, so a
        peer that knows only the api key cannot make the node write anything
        but the right key, and only once. (XXpsk2 mixes the PSK into message
        2, so the wrong password fails on the node, not here.)"""
        for _ in range(3):
            client = _make_client(self.protocol)
            initiator, message = _message_1(client, password="wrong-password")
            self.protocol.handle_noise_handshake_message(message, client)
            (msg2,), _ = client.send.call_args
            with self.assertRaises(Exception):
                initiator.read_message(bytes.fromhex(msg2.payload["noise"]["msg"]))
        self.assertEqual(len(self.protocol.db.updates), 1)
        self.assertEqual(self.row.metadata["noise_psk_for"],
                         self.protocol._noise_psk_binding(PASSWORD.encode()))
        self.assertEqual(len(self.protocol._noise_psks), 1)

    def test_the_key_never_reaches_the_logs(self):
        lines = []
        with patch.object(protocol_module.LOG, "debug", lines.append), \
                patch.object(protocol_module.LOG, "info", lines.append), \
                patch.object(protocol_module.LOG, "warning", lines.append), \
                patch.object(protocol_module.LOG, "error", lines.append), \
                patch.object(protocol_module.LOG, "exception", lines.append):
            self.protocol.noise_psk("very-secret-password", _make_client(self.protocol))
        self.assertEqual(lines, [])


class TestOffLoopHandshake(unittest.TestCase):
    """With an event loop running, message 1 is parked, not derived inline.

    The worker pool is replaced by one whose derivations the test completes
    by hand, from a thread, exactly as a real worker's completion arrives:
    nothing here depends on argon2's speed.
    """

    def setUp(self):
        self.row = _Row({})
        self.proto, patcher = _make_protocol(self.row)
        self.addCleanup(patcher.stop)
        self.executor = _ManualExecutor()
        self.proto._noise_psk_executor = self.executor

    def test_message_1_is_parked_and_completes_when_the_key_arrives(self):
        client = _make_client(self.proto)
        initiator, message = _message_1(client)
        real_psk = protocol_module.derive_psk(PASSWORD.encode(), node_id=NODE_ID)

        async def scenario():
            self.proto.handle_noise_handshake_message(message, client)
            # parked: nothing sent, nothing derived on this thread
            self.assertTrue(client.noise_psk_pending)
            client.send.assert_not_called()
            self.assertIsNone(client.noise_handshake)
            self.assertEqual(len(self.executor.pending), 1)
            self.executor.finish(result=real_psk)
            await self.proto._noise_psk_futures[(PASSWORD.encode(), NODE_ID)]
            await _settle()

        asyncio.run(scenario())
        self.assertFalse(client.noise_psk_pending)
        client.disconnect.assert_not_called()
        # message 2 went out, the initiator finishes the handshake, the key
        # was remembered and persisted
        _finish_handshake(self.proto, client, initiator)
        self.assertIsNotNone(client.noise_transport)
        self.assertEqual(self.row.metadata["noise_psk"], real_psk.hex())
        self.assertIn((PASSWORD.encode(), NODE_ID), self.proto._noise_psks)

    def test_a_duplicate_frame_while_parked_is_rejected_even_if_the_key_arrived(self):
        """The completion callback that fills the cache is queued separately
        from the one that resumes the parked frame; a duplicate landing in
        between must not start a second handshake off the cache."""
        client = _make_client(self.proto)
        _initiator, message = _message_1(client)

        async def scenario():
            self.proto.handle_noise_handshake_message(message, client)
            self.assertTrue(client.noise_psk_pending)
            self.proto._remember_noise_psk((PASSWORD.encode(), NODE_ID), PSK)  # the gap
            self.proto.handle_noise_handshake_message(message, client)  # duplicate

        asyncio.run(scenario())
        client.disconnect.assert_called_once_with(1008, unittest.mock.ANY)
        client.send.assert_not_called()

    def test_concurrent_connections_share_one_derivation(self):
        async def scenario():
            futures = [self.proto._derive_noise_psk_async(PASSWORD, None) for _ in range(20)]
            self.assertEqual(len({id(f) for f in futures}), 1)
            self.executor.finish()
            await futures[0]
            await _settle()

        asyncio.run(scenario())
        self.assertEqual(len(self.executor.pending), 1)
        self.assertIn((PASSWORD.encode(), NODE_ID), self.proto._noise_psks)

    def test_the_offer_starts_the_derivation_that_message_1_then_shares(self):
        client = _make_client(self.proto)
        _initiator, message = _message_1(client)

        async def scenario():
            self.proto._prewarm_noise_psk(client)
            self.assertEqual(len(self.executor.pending), 1)
            self.proto.handle_noise_handshake_message(message, client)
            self.assertTrue(client.noise_psk_pending)
            self.assertEqual(len(self.executor.pending), 1, "message 1 joined the prewarm")
            self.executor.finish()
            await self.proto._noise_psk_futures[(PASSWORD.encode(), NODE_ID)]
            await _settle()

        asyncio.run(scenario())
        self.assertFalse(client.noise_psk_pending)
        self.assertEqual(client.send.call_count, 1)

    def test_a_client_gone_while_deriving_is_not_resumed(self):
        client = _make_client(self.proto)
        _initiator, message = _message_1(client)

        async def scenario():
            self.proto.handle_noise_handshake_message(message, client)
            self.assertTrue(client.noise_psk_pending)
            self.proto.handle_client_disconnected(client)
            self.executor.finish()
            await self.proto._noise_psk_futures[(PASSWORD.encode(), NODE_ID)]
            await _settle()

        asyncio.run(scenario())
        self.assertTrue(client.disconnected)
        self.assertFalse(client.noise_psk_pending)
        client.send.assert_not_called()

    def test_an_abort_while_parked_does_not_resume_the_frame(self):
        """The transport reports the close a few loop turns after the abort;
        the parked frame must not run in between."""
        client = _make_client(self.proto)
        _initiator, message = _message_1(client)

        async def scenario():
            self.proto.handle_noise_handshake_message(message, client)
            self.proto._abort_noise_handshake(client, "duplicate")
            self.executor.finish()
            await self.proto._noise_psk_futures[(PASSWORD.encode(), NODE_ID)]
            await _settle()

        asyncio.run(scenario())
        client.send.assert_not_called()
        self.assertFalse(client.noise_psk_pending)
        client.disconnect.assert_called_once_with(1008, unittest.mock.ANY)

    def test_a_failed_derivation_aborts_the_parked_handshake(self):
        client = _make_client(self.proto)
        _initiator, message = _message_1(client)

        async def scenario():
            self.proto.handle_noise_handshake_message(message, client)
            worker = threading.Thread(
                target=self.executor.pending[0].set_exception, args=(RuntimeError("argon2"),))
            worker.start()
            worker.join()
            with self.assertRaises(RuntimeError):
                await self.proto._noise_psk_futures[(PASSWORD.encode(), NODE_ID)]
            await _settle()

        with patch.object(protocol_module.LOG, "error") as error:
            asyncio.run(scenario())
        client.disconnect.assert_called_once_with(1008, unittest.mock.ANY)
        client.send.assert_not_called()
        self.assertTrue(any("RuntimeError" in str(c) for c in error.call_args_list))
        self.assertFalse(any(PASSWORD in str(c) for c in error.call_args_list))

    def test_without_a_loop_the_key_is_derived_inline(self):
        self.proto._noise_psk_executor = None
        client = _make_client(self.proto)
        _initiator, message = _message_1(client)
        self.proto.handle_noise_handshake_message(message, client)
        self.assertFalse(client.noise_psk_pending)
        self.assertEqual(client.send.call_count, 1)

    def test_a_transport_thread_derives_inline_while_the_loop_serves_others(self):
        """The MQTT transport calls in from its own thread with no running
        loop while the websocket transport's loop is up: that path derives
        inline and shares the same cache."""
        results = []

        def from_transport_thread():
            with patch.object(protocol_module, "derive_psk", return_value=PSK):
                results.append(self.proto.noise_psk(PASSWORD, _make_client(self.proto)))

        async def scenario():
            worker = threading.Thread(target=from_transport_thread)
            worker.start()
            while worker.is_alive():
                await asyncio.sleep(0.01)

        asyncio.run(scenario())
        self.assertEqual(results, [PSK])
        self.assertEqual(self.executor.pending, [], "nothing went through the pool")
        self.assertIn((PASSWORD.encode(), NODE_ID), self.proto._noise_psks)

    def test_a_future_from_a_closed_loop_is_replaced(self):
        async def first():
            self.proto._derive_noise_psk_async(PASSWORD, None)

        async def second():
            future = self.proto._derive_noise_psk_async(PASSWORD, None)
            self.assertIs(future.get_loop(), asyncio.get_running_loop())

        asyncio.run(first())  # the loop closes with the derivation unfinished
        asyncio.run(second())
        self.assertEqual(len(self.executor.pending), 2, "a fresh derivation was started")


class TestCompletedFutureRace(unittest.TestCase):
    """A worker finishes: the result is copied onto the asyncio future by a
    queued call, and the completion callback is queued behind that. A same-key
    caller landing between the two used to see ``done()`` and start a second
    argon2 derivation, and the stale callback then evicted that replacement
    so a third caller started yet another one."""

    def test_a_caller_in_the_completion_gap_shares_the_finished_key(self):
        proto, patcher = _make_protocol(_Row({}))
        self.addCleanup(patcher.stop)
        executor = _ManualExecutor()
        proto._noise_psk_executor = executor
        seen = {}

        async def scenario():
            loop = asyncio.get_running_loop()
            first = proto._derive_noise_psk_async(PASSWORD, None)
            self.assertFalse(first.done())
            executor.finish()  # state copy queued; our caller queues behind it

            def in_the_gap():
                seen["first_done"] = first.done()
                seen["second"] = proto._derive_noise_psk_async(PASSWORD, None)

            loop.call_soon(in_the_gap)
            await _settle(4)
            # a later caller takes the handshake path's first step: the cache
            seen["third"] = proto._cached_noise_psk((PASSWORD.encode(), NODE_ID), None)

        asyncio.run(scenario())
        self.assertTrue(seen["first_done"], "the gap was reproduced")
        self.assertEqual(len(executor.pending), 1, "one derivation for three callers")
        self.assertEqual(seen["second"].result(), PSK)
        self.assertEqual(seen["third"], PSK)
        self.assertEqual(proto._noise_psk_futures, {}, "no stale or orphaned entry")


class TestBackingFields(unittest.TestCase):
    def test_backing_fields_stay_out_of_init_and_repr(self):
        fields = {f.name: f for f in dataclasses.fields(HiveMindListenerProtocol)}
        for name in ("_noise_psk_executor", "_noise_psk_futures",
                     "_noise_psk_persisted_keys", "_noise_psk_lock"):
            self.assertFalse(fields[name].init, name)
            self.assertFalse(fields[name].repr, name)

    def test_a_failed_derivation_is_logged_without_the_password(self):
        proto, patcher = _make_protocol(_Row({}))
        self.addCleanup(patcher.stop)
        lines = []

        async def scenario():
            with patch.object(protocol_module, "derive_psk",
                              side_effect=RuntimeError("argon2 exploded")), \
                    patch.object(protocol_module.LOG, "error", lines.append):
                future = proto._derive_noise_psk_async("very-secret-password", None)
                with self.assertRaises(RuntimeError):
                    await future
                await _settle()

        asyncio.run(scenario())
        self.assertEqual(len(lines), 1)
        self.assertIn("RuntimeError", lines[0])
        self.assertNotIn("very-secret-password", lines[0])
        self.assertEqual(proto._noise_psks, {})


if __name__ == "__main__":
    unittest.main()
