"""Regression guard for the recurring ``object.__new__`` fixture breakage.

Several test fixtures build ``HiveMindListenerProtocol`` with
``object.__new__``, skipping ``__init__``/``__post_init__``, then hand-set
only the handful of attributes their own test touches. Every attribute added
to ``__post_init__`` since has broken those fixtures at least once:
``last_seen_update_interval``, ``_identity_rsa_key``, and ``_seen_flood_ids``.

The attributes below now have class-level defaults (or, for
``_seen_flood_ids``, a lazily-materialized per-instance value), so a
bypass-built instance sees working values without every fixture having to
hand-set them. This test is the tripwire: if a future attribute is added to
``__post_init__`` without a class default, a bypass-built instance will
raise ``AttributeError`` on that attribute, and this test must be extended
(not worked around with ``getattr``) to name it.
"""
import ast
import inspect

from hivemind_bus_client.hive_map import FloodIdCache

from hivemind_core.protocol import HiveMindListenerProtocol

# __post_init__ attributes a bypass-built instance still does not see. Every
# one is a mutable container that the fixtures touching it already hand-set,
# so none is currently reachable as an AttributeError. This is a known-gap
# list, not a target: do not add to it. A new name here means a new
# __post_init__ attribute shipped without a class default, which is the exact
# recurrence this module exists to stop.
KNOWN_BYPASS_GAPS = frozenset({
    "clients",
    "_answered_floods",
    "_pending_cascades",
    "_last_seen_updates",
    "_noise_psks",
})


def _post_init_attributes() -> set:
    """Every ``self.X = ...`` target in ``__post_init__``, read from source."""
    src = inspect.getsource(HiveMindListenerProtocol)
    tree = ast.parse("class _X:\n" + "\n".join(
        "    " + line for line in src.split("\n")[1:]))
    found = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "__post_init__"):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Assign):
                targets = inner.targets
            elif isinstance(inner, ast.AnnAssign):
                targets = [inner.target]
            else:
                continue
            for target in targets:
                if (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"):
                    found.add(target.attr)
    return found


def _bypassed() -> HiveMindListenerProtocol:
    return object.__new__(HiveMindListenerProtocol)


def test_last_seen_update_interval_has_a_default():
    proto = _bypassed()
    assert proto.last_seen_update_interval == 0.0


def test_identity_rsa_key_cache_has_a_default():
    proto = _bypassed()
    assert proto._identity_rsa_key is None


def test_seen_flood_ids_is_a_real_flood_id_cache():
    proto = _bypassed()
    assert isinstance(proto._seen_flood_ids, FloodIdCache)
    assert proto._seen_flood_ids.check("flood-1") is False
    assert proto._seen_flood_ids.check("flood-1") is True


def test_seen_flood_ids_is_not_shared_between_instances():
    a, b = _bypassed(), _bypassed()
    a._seen_flood_ids.add("flood-1")
    assert "flood-1" not in b._seen_flood_ids


def test_seen_flood_ids_can_still_be_overridden_by_a_fixture():
    proto = _bypassed()
    shared = FloodIdCache()
    proto._seen_flood_ids = shared
    assert proto._seen_flood_ids is shared


def test_every_post_init_attribute_survives_bypassed_construction():
    """The generic tripwire.

    The named tests above cover specific semantics. This one needs no
    maintenance: it reads ``__post_init__`` and fails on any attribute a
    bypass-built instance cannot see. Give the class a default (see
    ``_flood_id_cache`` and its property for the mutable case) rather than
    adding the name to ``KNOWN_BYPASS_GAPS``.
    """
    proto = _bypassed()
    missing = {name for name in _post_init_attributes() if not hasattr(proto, name)}
    assert missing <= KNOWN_BYPASS_GAPS, (
        "new __post_init__ attribute(s) with no class default: "
        f"{sorted(missing - KNOWN_BYPASS_GAPS)}"
    )


def test_known_gap_list_has_no_stale_entries():
    """A gap that gets fixed must leave the list, or the list stops meaning
    anything."""
    proto = _bypassed()
    stale = {name for name in KNOWN_BYPASS_GAPS if hasattr(proto, name)}
    assert not stale, f"fixed attributes still listed as gaps: {sorted(stale)}"


def test_ping_flood_throttle_state_has_defaults():
    """#208 added these to the ping path; they are fields, not assignments."""
    proto = _bypassed()
    assert proto._last_ping_flood == 0.0
    assert proto.ping_flood_interval == 30.0
