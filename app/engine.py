"""
app/engine.py
~~~~~~~~~~~~~
Core crowd-routing engine for SafePass 2026.

Implements the LWR (Lighthill-Whitham-Richards) fluid-dynamics model for
pedestrian crowd flow, combined with a congestion-aware Dijkstra shortest-path
algorithm to compute real-time optimal evacuation routes for a 36-node stadium
graph.

References
----------
- Lighthill & Whitham (1955), "On kinematic waves II."
- Fruin, J.J. (1971), "Pedestrian Planning and Design." (Level of Service model)
"""

from __future__ import annotations

import heapq
import logging
from typing import Dict, List, Optional, Set, Tuple

from app.constants import (
    BOTTLENECK_OCCUPANCY_THRESHOLD,
    CRUSH_DENSITY_THRESHOLD,
    CRUSH_MODERATE_MAX_ZONES,
    CRUSH_WEIGHT_MULTIPLIER,
    LWR_ALPHA,
    LWR_BETA,
    LWR_MAX_RATIO_CAP,
)

__all__ = ["Edge", "StadiumGraph"]

logger = logging.getLogger("safepass.engine")


class Edge:
    """
    Directed weighted edge representing a stadium corridor or stairway.

    Attributes
    ----------
    source : str
        Origin node identifier.
    target : str
        Destination node identifier.
    length : float
        Base travel time in seconds under free-flow conditions.
    capacity : float
        Maximum sustainable flow in people per second.
    occupancy : float
        Current number of people on this corridor segment.
    is_blocked : bool
        When ``True``, the corridor is impassable (fire, collapse, lockdown).
    """

    __slots__ = ("source", "target", "length", "capacity", "occupancy", "is_blocked")

    def __init__(
        self,
        source: str,
        target: str,
        length: float,
        capacity: float,
    ) -> None:
        self.source: str = source
        self.target: str = target
        self.length: float = length
        self.capacity: float = capacity
        self.occupancy: float = 0.0
        self.is_blocked: bool = False

    def get_effective_weight(self) -> float:
        """
        Compute the congestion-adjusted travel cost for this edge.

        Uses the LWR model:
        ``weight = length × (1 + α × (density_ratio ^ β))``

        A blocked edge returns ``float('inf')``, making it invisible to the
        path-finder.

        Returns
        -------
        float
            Effective travel time in seconds.
        """
        if self.is_blocked:
            return float("inf")

        # Clamp density ratio to avoid runaway weights beyond physical sense.
        density_ratio: float = min(
            self.occupancy / max(self.capacity, 1.0), LWR_MAX_RATIO_CAP
        )
        return self.length * (1.0 + LWR_ALPHA * (density_ratio**LWR_BETA))

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"Edge({self.source!r} → {self.target!r}, "
            f"len={self.length}, occ={self.occupancy}/{self.capacity}, "
            f"blocked={self.is_blocked})"
        )


class StadiumGraph:
    """
    Weighted directed graph modelling the egress network of a FIFA stadium.

    Nodes represent physical locations (seating sections, concourses, exit
    gates).  Edges represent passable corridors with LWR-adjusted travel costs.
    """

    def __init__(self) -> None:
        self.nodes: Set[str] = set()
        self.exits: Set[str] = set()
        #: Adjacency list: node_name → {neighbour_name → Edge}
        self.adj: Dict[str, Dict[str, Edge]] = {}

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def add_node(self, name: str, *, is_exit: bool = False) -> None:
        """Register a node.  Idempotent — safe to call multiple times."""
        self.nodes.add(name)
        if is_exit:
            self.exits.add(name)
        self.adj.setdefault(name, {})

    def add_edge(
        self,
        source: str,
        target: str,
        *,
        length: float,
        capacity: float,
        bidirectional: bool = True,
    ) -> None:
        """
        Add a directed corridor edge (and its reverse if *bidirectional*).

        Both endpoint nodes are registered automatically if not yet present.
        """
        self.add_node(source)
        self.add_node(target)
        self.adj[source][target] = Edge(source, target, length, capacity)
        if bidirectional:
            self.adj[target][source] = Edge(target, source, length, capacity)

    # ------------------------------------------------------------------
    # State mutations
    # ------------------------------------------------------------------

    def set_edge_blocked(
        self,
        source: str,
        target: str,
        is_blocked: bool,
        *,
        bidirectional: bool = True,
    ) -> None:
        """Toggle the blocked state of a specific corridor edge."""
        if source in self.adj and target in self.adj[source]:
            self.adj[source][target].is_blocked = is_blocked
        if bidirectional and target in self.adj and source in self.adj[target]:
            self.adj[target][source].is_blocked = is_blocked

    def set_node_blocked(self, node: str, is_blocked: bool) -> None:
        """
        Block or unblock all corridors connected to *node*.

        Used for localised hazard containment (fire zone, structural failure).
        """
        if node in self.adj:
            for target in self.adj[node]:
                self.adj[node][target].is_blocked = is_blocked
        for src in self.adj:
            if node in self.adj[src]:
                self.adj[src][node].is_blocked = is_blocked

    def update_edge_occupancy(
        self,
        source: str,
        target: str,
        occupancy: float,
        *,
        bidirectional: bool = True,
    ) -> None:
        """Update the live occupancy count for an edge, clamped to ≥ 0."""
        clamped = max(0.0, occupancy)
        if source in self.adj and target in self.adj[source]:
            self.adj[source][target].occupancy = clamped
        if bidirectional and target in self.adj and source in self.adj[target]:
            self.adj[target][source].occupancy = clamped

    def reset_congestion(self) -> None:
        """Clear all occupancy and blockage state (used when loading a new scenario)."""
        for src in self.adj:
            for edge in self.adj[src].values():
                edge.occupancy = 0.0
                edge.is_blocked = False

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def calculate_evacuation_routes(
        self, start_node: str
    ) -> Tuple[List[str], float]:
        """
        Compute the optimal evacuation path from *start_node* to the nearest
        available exit using congestion-aware Dijkstra's algorithm.

        The algorithm terminates as soon as the first (nearest) exit is popped
        from the priority queue, guaranteeing optimality without exploring the
        entire graph.

        Parameters
        ----------
        start_node : str
            Name of the seating section or concourse from which to evacuate.

        Returns
        -------
        Tuple[List[str], float]
            ``(path, total_travel_time_seconds)`` where *path* is an ordered
            list of node names from start to exit.  Returns ``([], inf)`` when
            no reachable exit exists.
        """
        if start_node not in self.nodes:
            logger.warning("calculate_evacuation_routes: unknown node %r", start_node)
            return [], float("inf")

        distances: Dict[str, float] = {n: float("inf") for n in self.nodes}
        distances[start_node] = 0.0
        predecessors: Dict[str, Optional[str]] = {n: None for n in self.nodes}
        pq: List[Tuple[float, str]] = [(0.0, start_node)]
        visited: Set[str] = set()
        nearest_exit: Optional[str] = None
        min_exit_dist: float = float("inf")

        while pq:
            curr_dist, curr_node = heapq.heappop(pq)
            if curr_node in visited:
                continue
            visited.add(curr_node)

            if curr_node in self.exits:
                # First exit reached by Dijkstra is always the shortest path.
                min_exit_dist = curr_dist
                nearest_exit = curr_node
                break

            for target, edge in self.adj.get(curr_node, {}).items():
                if target in visited:
                    continue
                weight = edge.get_effective_weight()
                if weight == float("inf"):
                    continue
                new_dist = curr_dist + weight
                if new_dist < distances[target]:
                    distances[target] = new_dist
                    predecessors[target] = curr_node
                    heapq.heappush(pq, (new_dist, target))

        if nearest_exit is None:
            return [], float("inf")

        # Reconstruct path by following predecessor chain backwards.
        path: List[str] = []
        curr: Optional[str] = nearest_exit
        while curr is not None:
            path.append(curr)
            curr = predecessors[curr]
        path.reverse()
        return path, min_exit_dist

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_crush_risk_zones(self) -> Dict:
        """
        Crowd Crush Prevention Algorithm (Feature #93).

        Identifies corridors simultaneously at Fruin Level of Service E/F:
        - Density ratio ≥ ``CRUSH_DENSITY_THRESHOLD`` (≥ 80 % by default)
        - AND effective weight ≥ ``CRUSH_WEIGHT_MULTIPLIER`` × base length

        Blocked edges are excluded — they are already closed to pedestrians.

        Returns
        -------
        dict
            ``{level: "LOW"|"MODERATE"|"CRITICAL", zone_count: int,
               zones: List[dict], summary: str}``
        """
        crush_zones: List[Dict] = []
        seen: Set[Tuple[str, str]] = set()

        for src, neighbours in self.adj.items():
            for tgt, edge in neighbours.items():
                edge_id = (min(src, tgt), max(src, tgt))
                if edge_id in seen or edge.is_blocked or edge.capacity <= 0:
                    continue
                seen.add(edge_id)

                density_ratio = edge.occupancy / edge.capacity
                effective_w = edge.get_effective_weight()

                if density_ratio >= CRUSH_DENSITY_THRESHOLD and effective_w >= (
                    edge.length * CRUSH_WEIGHT_MULTIPLIER
                ):
                    crush_zones.append(
                        {
                            "source": src,
                            "target": tgt,
                            "density_ratio": round(density_ratio, 3),
                            "effective_weight": round(effective_w, 2),
                            "base_length": edge.length,
                            "penalty_multiplier": round(
                                effective_w / max(edge.length, 1), 2
                            ),
                            "occupancy": edge.occupancy,
                            "capacity": edge.capacity,
                        }
                    )

        crush_zones.sort(key=lambda z: z["density_ratio"], reverse=True)

        zone_count = len(crush_zones)
        if zone_count == 0:
            level, summary = (
                "LOW",
                "No crush-risk corridors detected. Crowd flow within safe parameters.",
            )
        elif zone_count <= CRUSH_MODERATE_MAX_ZONES:
            level = "MODERATE"
            summary = (
                f"{zone_count} corridor(s) approaching crush density. "
                "Monitor and prepare rerouting."
            )
        else:
            level = "CRITICAL"
            summary = (
                f"CRUSH ALERT: {zone_count} corridors at dangerous density. "
                "Immediate intervention required."
            )

        return {
            "level": level,
            "zone_count": zone_count,
            "zones": crush_zones,
            "summary": summary,
        }

    def get_bottlenecks(
        self, threshold: float = BOTTLENECK_OCCUPANCY_THRESHOLD
    ) -> List[Dict]:
        """
        Return edges where the occupancy/capacity ratio exceeds *threshold*
        or which are explicitly blocked.

        Parameters
        ----------
        threshold : float
            Occupancy/capacity ratio above which a corridor is a bottleneck.
            Defaults to ``BOTTLENECK_OCCUPANCY_THRESHOLD``.
        """
        bottlenecks: List[Dict] = []
        seen: Set[Tuple[str, str]] = set()

        for src, neighbours in self.adj.items():
            for tgt, edge in neighbours.items():
                edge_id = (min(src, tgt), max(src, tgt))
                if edge_id in seen:
                    continue
                seen.add(edge_id)

                if edge.capacity > 0:
                    ratio = edge.occupancy / edge.capacity
                    if ratio >= threshold or edge.is_blocked:
                        bottlenecks.append(
                            {
                                "source": src,
                                "target": tgt,
                                "occupancy": edge.occupancy,
                                "capacity": edge.capacity,
                                "ratio": round(ratio, 3),
                                "is_blocked": edge.is_blocked,
                            }
                        )
        return bottlenecks
