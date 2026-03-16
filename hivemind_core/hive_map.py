"""Hive topology mapper built from PING/PONG discovery messages."""
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from hivemind_bus_client.message import HiveMessage


@dataclass
class NodeInfo:
    """Metadata about a node discovered via PING/PONG."""

    peer: str
    site_id: Optional[str] = None
    pong_timestamp: Optional[float] = None
    ping_timestamp: Optional[float] = None

    @property
    def rtt_ms(self) -> Optional[float]:
        """Round-trip time in milliseconds, or None if timestamps are unavailable."""
        if self.pong_timestamp is not None and self.ping_timestamp is not None:
            return (self.pong_timestamp - self.ping_timestamp) * 1000
        return None


class HiveMapper:
    """Collect PONG responses from a PING flood and build a directed hive topology graph.

    Usage::

        mapper = HiveMapper()
        mapper.start_ping(ping_id)
        # ... feed each received inner PONG HiveMessage ...
        mapper.on_pong(pong_msg)
        print(mapper.to_ascii(root_peer="my-node::session1"))
    """

    def __init__(self) -> None:
        # peer → NodeInfo for every node that responded
        self.nodes: Dict[str, NodeInfo] = {}
        # source peer → set of target peers (directed edges from route records)
        self.edges: Dict[str, Set[str]] = {}
        # ping_id → set of peer IDs that already sent a PONG (deduplication)
        self._seen_pongs: Dict[str, Set[str]] = {}

    def start_ping(self, ping_id: str) -> None:
        """Register a new PING session, clearing stale deduplication state for that ID.

        Args:
            ping_id: UUID string from the PING payload.
        """
        self._seen_pongs[ping_id] = set()

    def on_pong(self, message: HiveMessage) -> bool:
        """Ingest a received inner PONG HiveMessage and update the topology graph.

        The route on *message* must already contain the hop history transferred
        from the outer PROPAGATE wrapper (done by ``_unpack_message`` in the server
        protocol before this method is called).

        Args:
            message: Inner PONG HiveMessage with ``msg_type == HiveMessageType.PONG``.

        Returns:
            True if the PONG was new and the graph was updated; False if duplicate.
        """
        payload = message.payload
        if not isinstance(payload, dict):
            return False

        ping_id = payload.get("ping_id", "")
        peer = payload.get("peer", "")

        if not peer:
            return False

        seen = self._seen_pongs.setdefault(ping_id, set())
        if peer in seen:
            return False
        seen.add(peer)

        self.nodes[peer] = NodeInfo(
            peer=peer,
            site_id=payload.get("site_id"),
            pong_timestamp=payload.get("pong_timestamp"),
            ping_timestamp=payload.get("timestamp"),
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
                "pong_timestamp": n.pong_timestamp,
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

        PONG routes flow *toward* the originator, so edges are stored as
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
        self._seen_pongs.clear()
