"""HiveMindListenerProtocol.shutdown() releases the PSK pool at once.

The idle release (#338) drops the pool after each burst of derivations. A
host that drops the listener while a derivation is still queued has nothing
to wait for, so shutdown() cancels what is queued, leaves what is running,
and drops the pool. hivescope's MasterNode.cleanup calls it.
"""
import asyncio
import threading
import unittest
from unittest.mock import patch

from hivemind_core import protocol as protocol_module

from tests.test_noise_psk_off_loop import (PASSWORD, PSK, _Row, _make_protocol,
                                           _settle)


class TestShutdown(unittest.TestCase):

    def setUp(self):
        self.proto, self.patcher = _make_protocol(_Row({}))
        self.addCleanup(self.patcher.stop)

    def test_on_a_listener_that_never_derived_it_is_a_no_op(self):
        self.assertIsNone(self.proto._noise_psk_executor)
        self.proto.shutdown()
        self.proto.shutdown()
        self.assertIsNone(self.proto._noise_psk_executor)

    def test_a_queued_derivation_is_cancelled_and_the_threads_end(self):
        """Two workers busy, a third derivation queued, then shutdown()."""
        release = threading.Event()
        started = threading.Barrier(self.proto.NOISE_PSK_WORKERS + 1)

        def slow_derive(password, node_id=None):
            started.wait(timeout=10)
            release.wait(timeout=10)
            return PSK

        before = set(threading.enumerate())
        with patch.object(protocol_module, "derive_psk", side_effect=slow_derive):
            running = [self.proto._start_noise_psk_derivation(f"busy-{i}", None)
                       for i in range(self.proto.NOISE_PSK_WORKERS)]
            started.wait(timeout=10)  # both workers are inside derive_psk
            queued = self.proto._start_noise_psk_derivation("queued", None)
            self.assertFalse(queued.running())
            workers = [t for t in threading.enumerate()
                       if t not in before and t.name.startswith("noise-psk")]
            self.assertEqual(len(workers), self.proto.NOISE_PSK_WORKERS)

            self.proto.shutdown()

            self.assertTrue(queued.cancelled(), "the queued derivation still waits")
            self.assertIsNone(self.proto._noise_psk_executor)
            release.set()
            for f in running:
                self.assertEqual(f.result(timeout=10), PSK)
        for t in workers:
            t.join(timeout=10)
            self.assertFalse(t.is_alive(), f"{t.name} outlived shutdown()")
        # the cancelled future removed its own entry; the pool is not poisoned
        self.assertNotIn(self.proto._noise_psk_key("queued"),
                         self.proto._noise_psk_futures or {})

    def test_the_listener_derives_again_after_shutdown(self):
        async def scenario():
            with patch.object(protocol_module, "derive_psk", return_value=PSK):
                return await self.proto._derive_noise_psk_async(PASSWORD, None)

        self.assertEqual(asyncio.run(scenario()), PSK)
        self.proto.shutdown()
        self.proto._noise_psks.clear()
        self.assertEqual(asyncio.run(scenario()), PSK)
        self.proto.shutdown()
        self.assertIsNone(self.proto._noise_psk_executor)

    def test_an_injected_pool_is_left_alone(self):
        class NotAPool:
            closed = False

            def shutdown(self, *a, **k):
                self.closed = True

        pool = NotAPool()
        self.proto._noise_psk_executor = pool
        self.proto.shutdown()
        self.assertIs(self.proto._noise_psk_executor, pool)
        self.assertFalse(pool.closed)


class TestServiceCallsShutdown(unittest.TestCase):
    """HiveMindService.run() shuts the listener down after presence and upstream."""

    def test_run_calls_shutdown_in_the_cleanup_order(self):
        from unittest import mock

        from hivemind_core.service import HiveMindService

        calls = []
        listener = mock.MagicMock()
        listener.shutdown.side_effect = lambda: calls.append("shutdown")
        with mock.patch("hivemind_core.service.ClientDatabase"):
            svc = HiveMindService(identity=mock.MagicMock())
        svc.hm_protocol = mock.MagicMock(return_value=listener)
        svc._start_rendezvous = lambda hm_protocol: None
        svc._connect_upstream = lambda hm_protocol: None
        svc._start_presence = lambda: None
        svc._stop_presence = lambda: calls.append("presence")
        svc._stop_upstream = lambda: calls.append("upstream")
        svc._status = mock.MagicMock()
        svc._status.set_stopping.side_effect = lambda: calls.append("stopping")
        with mock.patch("hivemind_core.service.get_agent_protocol",
                        lambda: (lambda config: mock.MagicMock(), {})), \
             mock.patch("hivemind_core.service.get_binary_protocol",
                        lambda: (lambda **kw: mock.MagicMock(), {})), \
             mock.patch("hivemind_core.service.get_server_config",
                        lambda: {"network_protocol": {"websocket": {}}}), \
             mock.patch("hivemind_core.service.NetworkProtocolFactory.get_class",
                        lambda name: type("Listener", (), {
                            "__init__": lambda self, **kw: None,
                            "run": lambda self: None})), \
             mock.patch("hivemind_core.service.create_daemon",
                        lambda target, args=(): None), \
             mock.patch("hivemind_core.service.wait_for_exit_signal", lambda: None):
            svc.run()
        self.assertEqual(calls, ["presence", "upstream", "shutdown", "stopping"])
