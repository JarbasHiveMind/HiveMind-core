# hivemind-core
# Copyright (C) 2026 Casimiro Ferreira
# SPDX-License-Identifier: Apache-2.0
import os.path
from typing import Mapping, Optional

from json_database import JsonStorageXDG
from ovos_utils.log import LOG
from ovos_utils.xdg_utils import xdg_config_home, xdg_data_home


_DEFAULT = {
    # enable the hivemind binarization protocol
    "binarize": False,  # default False because of a bug in old hivemind-bus-client versions

    # sort encodings by order of preference
    "allowed_encodings": ["JSON-B64", "JSON-URLSAFE-B64",
                          "JSON-B91",
                          "JSON-Z85B", "JSON-Z85P",
                          "JSON-B32", "JSON-HEX"],
    "allowed_ciphers": ["CHACHA20-POLY1305", 'AES-GCM'],

    # minimum HiveMind protocol version a client must negotiate to be admitted.
    # 2 = require binary framing + handshake (rejects the oldest json-only /
    # no-binary clients). The server advertises max(this, crypto-derived min).
    "min_protocol_version": 2,

    # password-strength policy (bans low-entropy, guessable passwords).
    # `min_password_bits` is enforced at `add-client` (ingestion) and, unless
    # `runtime_password_strength_check` is disabled, again at handshake time as
    # a backstop against a manually edited database. The runtime check can also
    # be disabled with the env var HIVEMIND_DISABLE_PASSWORD_STRENGTH_CHECK=1.
    "min_password_bits": 40,
    "runtime_password_strength_check": True,

    # configure various plugins
    "agent_protocol": {"module": "hivemind-ovos-agent-plugin",
                       "hivemind-ovos-agent-plugin": {
                           "host": "127.0.0.1",
                           "port": 8181
                       }},
    "binary_protocol": {"module": None},
    # local-network discovery (optional hivemind-presence package)
    "presence": {
        "enabled": True,
        "name": "HiveMind-Node",
        "zeroconf": True,   # mDNS (optional zeroconf)
        "upnp": False,      # UPnP/SSDP (optional upnpclient)
    },
    # optional connection to a master above this node — HIVEMIND-NODE-1
    # §3.3/§4. Disabled by default: the node is a top-level master. Enable it
    # and the node also holds one connection upstream.
    # `key` and `password` are the credentials that master issued to this node
    # with `hivemind-core add-client`. `ssl` picks ws:// or wss:// for `host`,
    # and `self_signed` accepts a self-signed certificate from the master.
    "upstream": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 5678,
        "key": "",
        "password": "",
        "ssl": False,
        "self_signed": True,
    },
    "network_protocol": {"hivemind-websocket-plugin": {
                             "host": "0.0.0.0",
                             "port": 5678,
                             "ssl": False,
                             "cert_dir": f"{xdg_data_home()}/hivemind",
                             "cert_name": "hivemind"
                         },
                         "hivemind-http-plugin": {
                             "host": "0.0.0.0",
                             "port": 5679,
                             "ssl": False,
                             "cert_dir": f"{xdg_data_home()}/hivemind",
                             "cert_name": "hivemind"
                         }},
    # policy admission chain — evaluated for every client message before
    # injection into the agent bus. See HiveMind-core#85.
    #
    # The chain is ALWAYS fail-closed: any unhandled exception in a
    # policy becomes Verdict.deny("policy_error", ...). No knob.
    #
    # MessageTypeACLPolicy (the allowed_types whitelist enforcement) is
    # ALWAYS prepended to whatever appears in `chain` below — it cannot
    # be disabled by configuration. This list is for *additional*
    # policies layered on top.
    # OVOS transformer pipelines applied to the text/bus path
    # (OVOS-TRANSFORM). Loading is config-gated and opt-in: a plugin only
    # loads when named in its section, e.g.
    #   "utterance_transformers": {"ovos-utterance-corrections-plugin": {}}
    # utterance/metadata transformers run on client utterances before they
    # reach the agent bus; dialog transformers rewrite QUERY/CASCADE answer
    # chunks before they are sent back to clients.
    "utterance_transformers": {},
    "metadata_transformers": {},
    "dialog_transformers": {},
    "policy": {
        "chain": [
            # OVOSAgentPolicy ships with hivemind-ovos-agent-plugin
            # (the default agent_protocol) and injects skill/intent
            # blacklists from Client.metadata into the OVOS session.
            # Drop this entry if running a non-OVOS agent.
            {"module": "hivemind-ovos-agent-policy"},
        ],
    },

    # Minimum seconds between two responsive PING floods emitted by this node.
    # Answering a flood costs one send per connected peer, and every satellite
    # floods on its own schedule, so with no floor here the node's fan-out work
    # grows with the square of the mesh size. Inside the window the node still
    # answers the peer that pinged it — directly, one send — so that peer's map
    # is never wrong; only the mesh-wide fan-out waits. Keep this well under the
    # satellites' own ping period, or a node's entry in remote maps goes stale.
    "ping_flood_interval": 30,

    # Debounce for the synchronous client-db last_seen write. update_last_seen
    # runs on every inbound message, inline on the tornado IOLoop thread; the
    # JSON backend's commit() rewrites the entire client store on each call.
    # 60 seconds is coarse enough that "when did we last hear from this
    # client" stays accurate while cutting that write rate drastically. Set
    # to 0 to write on every message (disables throttling entirely).
    "last_seen_update_interval": 60,
}


def _default_database() -> dict:
    """Pick the default client-database backend.

    Fresh installs default to **SQLite** — transactional, concurrency-safe,
    stdlib-only — which suits a server authenticating and policy-checking
    many clients concurrently. An existing JSON deployment (a ``clients.json``
    already on disk, with no SQLite db yet) keeps its JSON backend so an
    upgrade never strands the credentials store; move it with
    ``hivemind-core migrate-db --to sqlite``.
    """
    base = os.path.join(xdg_data_home(), "hivemind-core")
    json_db = os.path.join(base, "clients.json")
    sqlite_db = os.path.join(base, "clients.db")
    if os.path.isfile(json_db) and not os.path.isfile(sqlite_db):
        module = "hivemind-json-db-plugin"
    else:
        module = "hivemind-sqlite-db-plugin"
    return {"module": module,
            module: {"name": "clients", "subfolder": "hivemind-core"}}


def get_server_config() -> JsonStorageXDG:
    """from ~/.config/hivemind-core/server.json """
    defaults = {**_DEFAULT, "database": _default_database()}
    db = JsonStorageXDG("server",
                          xdg_folder=xdg_config_home(),
                          subfolder="hivemind-core")
    if not os.path.isfile(db.path):
        db.merge(defaults)
        db.store()
    # ensure all top level keys are present
    for k, v in defaults.items():
        if k not in db:
            db[k] = v
        elif isinstance(v, dict) and isinstance(db[k], dict) and "module" in v:
            # ...and that a partially specified single-plugin block keeps the
            # rest of its defaults. Overriding one setting is the common case:
            #     {"agent_protocol": {"hivemind-ovos-agent-plugin": {...}}}
            # Without this the block loses "module" and the service dies at
            # startup with a bare KeyError.
            #
            # Only blocks that name a "module" are filled. In a multi-transport
            # block like `network_protocol` the sub-keys ARE the set of enabled
            # transports, so backfilling them would start a transport the
            # operator never asked for.
            for subk, subv in v.items():
                if subk not in db[k]:
                    db[k][subk] = subv
    # back-compat for the policy block: legacy installs may have
    # `policy.fail_open` (removed — chain is unconditionally fail-closed)
    # or be missing `policy.chain` (we default to OVOSAgentPolicy).
    policy_cfg = db.get("policy") or {}
    if not isinstance(policy_cfg, dict):
        policy_cfg = {}
    if "fail_open" in policy_cfg:
        LOG.warning(
            "policy.fail_open is no longer honoured — the chain is "
            "always fail-closed. Remove this key from server.json."
        )
        policy_cfg.pop("fail_open", None)
    if "chain" not in policy_cfg:
        policy_cfg["chain"] = list(_DEFAULT["policy"]["chain"])
    db["policy"] = policy_cfg
    # the `upstream` block is indexed sub-key by sub-key at the use site
    # (`HiveMindService._connect_upstream`), and that runs BEFORE the network
    # protocols start. A hand-edited block holding only some of the keys — or
    # `null` — raised KeyError/TypeError there and took the whole node offline,
    # satellites included. Deep-merge it against the defaults, like the policy
    # block above, so every sub-key is always present.
    db["upstream"] = upstream_config(db)
    return db


def upstream_config(server_config: Optional[Mapping] = None) -> dict:
    """The ``upstream`` block, every sub-key present.

    ``get_server_config`` calls this, so a config read the normal way is
    already complete. It is also called at the read site
    (``HiveMindService._connect_upstream``) because that is the code that
    would take the node offline if a sub-key were ever missing, and merging
    an already-merged block changes nothing.
    """
    if server_config is None:
        server_config = get_server_config()
    upstream = server_config.get("upstream")
    if not isinstance(upstream, dict):
        if "upstream" in server_config:
            LOG.warning(
                f"server.json 'upstream' is {type(upstream).__name__}, not a "
                f"block of settings — using the defaults (upstream disabled)."
            )
        upstream = {}
    return {**_DEFAULT["upstream"], **upstream}


def runtime_password_min_bits() -> float:
    """Minimum password bits the *runtime handshake* backstop enforces.

    Returns 0.0 when the runtime check is disabled (so callers pass
    ``min_bits=0`` to ``PasswordHandShake`` and skip re-validation). The
    add-client (ingestion) gate is separate and always applies.

    Disabled by the ``HIVEMIND_DISABLE_PASSWORD_STRENGTH_CHECK`` env var
    (``1``/``true``/``yes``) or ``runtime_password_strength_check: false`` in
    the config; otherwise returns the configured ``min_password_bits``.
    """
    if os.environ.get("HIVEMIND_DISABLE_PASSWORD_STRENGTH_CHECK", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return 0.0
    # get_server_config() backfills every top level key, so _DEFAULT is the
    # single source of truth for these fallbacks
    cfg = get_server_config()
    if not cfg.get("runtime_password_strength_check",
                   _DEFAULT["runtime_password_strength_check"]):
        return 0.0
    return float(cfg.get("min_password_bits", _DEFAULT["min_password_bits"]))
