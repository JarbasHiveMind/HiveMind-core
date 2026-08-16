"""_start_rendezvous refuses to bind a too-old hivemind-rendezvous.

hivemind-rendezvous 2.0.0a1 (PR #14, "fix!: address mailboxes by
authenticated identity") switched mailbox addressing from the recipient's
public key to the caller's authenticated access key — which is what this
protocol passes to ``mailbox.handle()``. An older, unpinned install still
imports cleanly and accepts deposits, it just never delivers them: silent
mail loss. A version gate must refuse to bind it, leaving the node an
honest non-rendezvous node instead.
"""

import sys
import types
from types import SimpleNamespace

from hivemind_core.service import HiveMindService


class _StubMailbox:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _install_stub_rendezvous(monkeypatch, version):
    pkg = types.ModuleType("hivemind_rendezvous")
    pkg.RendezvousMailbox = _StubMailbox
    version_mod = types.ModuleType("hivemind_rendezvous.version")
    version_mod.VERSION_MAJOR, version_mod.VERSION_MINOR, version_mod.VERSION_BUILD = version
    monkeypatch.setitem(sys.modules, "hivemind_rendezvous", pkg)
    monkeypatch.setitem(sys.modules, "hivemind_rendezvous.version", version_mod)


def _run(monkeypatch, version):
    _install_stub_rendezvous(monkeypatch, version)
    monkeypatch.setattr(
        "hivemind_core.service.get_server_config",
        lambda: {"rendezvous": {"enabled": True}},
    )
    hm_protocol = SimpleNamespace(mailbox=None)
    HiveMindService._start_rendezvous(None, hm_protocol)
    return hm_protocol


def test_compatible_rendezvous_is_bound(monkeypatch):
    hm_protocol = _run(monkeypatch, (2, 0, 0))
    assert isinstance(hm_protocol.mailbox, _StubMailbox)


def test_incompatible_rendezvous_is_refused(monkeypatch):
    hm_protocol = _run(monkeypatch, (1, 0, 0))
    assert hm_protocol.mailbox is None
