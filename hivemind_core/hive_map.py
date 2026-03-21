"""Hive topology mapper built from PING-only network discovery.

Every node responds to a PING by propagating its own PING (with the same
``flood_id``), so all nodes in the hive sync simultaneously.  An ephemeral
``flood_id`` prevents infinite loops.
"""
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from hivemind_bus_client.message import HiveMessage


@dataclass
class NodeInfo:
    """Metadata about a node discovered via PING flood."""

    peer: str
    site_id: Optional[str] = None
    timestamp: Optional[float] = None       # sender's clock when they created the PING
    received_at: Optional[float] = None     # our local clock when we received it

    @property
    def rtt_ms(self) -> Optional[float]:
        """Round-trip time in milliseconds, or None if timestamps are unavailable."""
        if self.received_at is not None and self.timestamp is not None:
            return (self.received_at - self.timestamp) * 1000
        return None


class HiveMapper:
    """Collect responsive PINGs from a flood and build a directed hive topology graph.

    Usage::

        mapper = HiveMapper()
        mapper.start_ping(flood_id)
        # ... feed each received inner PING HiveMessage ...
        mapper.on_ping(ping_msg)
        print(mapper.to_ascii(root_peer="my-node::session1"))
    """

    def __init__(self) -> None:
        # peer → NodeInfo for every node that responded
        self.nodes: Dict[str, NodeInfo] = {}
        # source peer → set of target peers (directed edges from route records)
        self.edges: Dict[str, Set[str]] = {}
        # flood_id → set of peer IDs that already sent a PING (deduplication)
        self._seen_pings: Dict[str, Set[str]] = {}

    def start_ping(self, flood_id: str) -> None:
        """Register a new PING session, clearing stale deduplication state for that ID.

        Args:
            flood_id: UUID string from the PING payload.
        """
        self._seen_pings[flood_id] = set()

    def on_ping(self, message: HiveMessage, received_at: Optional[float] = None) -> bool:
        """Ingest a received PING HiveMessage and update the topology graph.

        The route on *message* must already contain the hop history transferred
        from the outer PROPAGATE wrapper (done by ``_unpack_message`` in the server
        protocol before this method is called).

        Args:
            message: Inner PING HiveMessage with ``msg_type == HiveMessageType.PING``.
            received_at: Local clock timestamp when the PING was received.

        Returns:
            True if the PING was new and the graph was updated; False if duplicate.
        """
        payload = message.payload
        if not isinstance(payload, dict):
            return False

        flood_id = payload.get("flood_id", "")
        peer = payload.get("peer", "")

        if not peer:
            return False

        seen = self._seen_pings.setdefault(flood_id, set())
        if peer in seen:
            return False
        seen.add(peer)

        self.nodes[peer] = NodeInfo(
            peer=peer,
            site_id=payload.get("site_id"),
            timestamp=payload.get("timestamp"),
            received_at=received_at,
        )

        for hop in message.route:
            source = hop.get("source", "")
            targets = hop.get("targets") or []
            if source:
                edge_set = self.edges.setdefault(source, set())
                for t in targets:
                    if t:
                        edge_set.add(t)

        return True

    def to_dict(self) -> dict:
        """Return a JSON-serialisable snapshot of the current topology.

        Returns:
            dict with keys ``nodes`` (list of node dicts) and ``edges``
            (list of ``{source, target}`` dicts).
        """
        nodes = [
            {
                "peer": n.peer,
                "site_id": n.site_id,
                "timestamp": n.timestamp,
                "rtt_ms": n.rtt_ms,
            }
            for n in self.nodes.values()
        ]
        edges = [
            {"source": src, "target": tgt}
            for src, targets in self.edges.items()
            for tgt in targets
        ]
        return {"nodes": nodes, "edges": edges}

    def to_json(self) -> str:
        """Return ``to_dict()`` as a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def to_ascii(self, root_peer: Optional[str] = None) -> str:
        """Render the hive topology as a human-readable ASCII tree.

        PING routes flow *toward* the originator, so edges are stored as
        ``relayer → originator``.  When ``root_peer`` (the local node / PING
        originator) is supplied the edge direction is inverted for display so
        that the tree reads top-down from the originator outward to leaf nodes.

        Args:
            root_peer: Peer ID of the local node, labeled ``[self]`` at the
                tree root.  Omit to display the raw edge directions.

        Returns:
            Multi-line string representing the topology.
        """
        if not self.nodes and not self.edges:
            return "[No nodes discovered]"

        lines: List[str] = []

        if root_peer is not None:
            # Build display children as the *inverse* of stored edges:
            # stored: relayer → originator  →  display: originator ← relayer
            display_children: Dict[str, List[str]] = {}
            for src, targets in self.edges.items():
                for t in targets:
                    display_children.setdefault(t, [])
                    if src not in display_children[t]:
                        display_children[t].append(src)

            def _render_inv(peer: str, prefix: str, is_last: bool) -> None:
                connector = "└── " if is_last else "├── "
                node = self.nodes.get(peer)
                site = f"  site={node.site_id}" if node and node.site_id else ""
                rtt = (f"  rtt={node.rtt_ms:.0f}ms"
                       if node and node.rtt_ms is not None else "")
                lines.append(f"{prefix}{connector}{peer}{site}{rtt}")
                kids = display_children.get(peer, [])
                child_prefix = prefix + ("    " if is_last else "│   ")
                for i, kid in enumerate(kids):
                    _render_inv(kid, child_prefix, i == len(kids) - 1)

            node = self.nodes.get(root_peer)
            site = f"  site={node.site_id}" if node and node.site_id else ""
            lines.append(f"[self] {root_peer}{site}")
            kids = display_children.get(root_peer, [])
            for i, kid in enumerate(kids):
                _render_inv(kid, "", i == len(kids) - 1)

        else:
            # Raw display following stored edge direction (relayer → originator)
            children: Dict[str, List[str]] = {}
            all_targets: Set[str] = set()
            for src, targets in self.edges.items():
                children.setdefault(src, [])
                for t in targets:
                    children[src].append(t)
                    all_targets.add(t)

            candidate_roots = [p for p in self.edges if p not in all_targets]
            display_roots = candidate_roots or list(self.edges.keys())[:1]

            def _render(peer: str, prefix: str, is_last: bool) -> None:
                connector = "└── " if is_last else "├── "
                node = self.nodes.get(peer)
                site = f"  site={node.site_id}" if node and node.site_id else ""
                rtt = (f"  rtt={node.rtt_ms:.0f}ms"
                       if node and node.rtt_ms is not None else "")
                lines.append(f"{prefix}{connector}{peer}{site}{rtt}")
                kids = children.get(peer, [])
                child_prefix = prefix + ("    " if is_last else "│   ")
                for i, kid in enumerate(kids):
                    _render(kid, child_prefix, i == len(kids) - 1)

            for root in display_roots:
                node = self.nodes.get(root)
                site = f"  site={node.site_id}" if node and node.site_id else ""
                lines.append(f"{root}{site}")
                kids = children.get(root, [])
                for i, kid in enumerate(kids):
                    _render(kid, "", i == len(kids) - 1)

        return "\n".join(lines) if lines else "[No topology data]"

    def clear(self) -> None:
        """Reset the mapper to an empty state."""
        self.nodes.clear()
        self.edges.clear()
        self._seen_pings.clear()
