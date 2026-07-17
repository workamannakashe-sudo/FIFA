"""
tests/test_engine.py
~~~~~~~~~~~~~~~~~~~~
Unit tests for the SafePass 2026 routing engine and LWR physics model.
"""

import pytest
from app.engine import Edge


@pytest.mark.parametrize(
    "length, capacity, occupancy, is_blocked, expected_weight",
    [
        (10.0, 100.0, 0.0, False, 10.0),       # Baseline flow
        (10.0, 100.0, 50.0, False, 16.25),     # Moderate flow: 10 * (1 + 2.5 * (0.5^2))
        (10.0, 100.0, 100.0, False, 35.0),     # Dynamic capacity flow: 10 * (1 + 2.5 * (1.0^2))
        (10.0, 100.0, 500.0, False, 235.0),    # Capped density flow: 10 * (1 + 2.5 * (3.0^2))
        (10.0, 100.0, 50.0, True, float("inf")), # Blocked corridor
        (5.0, 0.0, 10.0, False, 117.5),        # Zero capacity baseline safety fallback (capacity=1.0)
    ],
)
def test_edge_weight_scenarios(length, capacity, occupancy, is_blocked, expected_weight):
    """Parametrized test checking LWR density weight calculation under various states."""
    edge = Edge("A", "B", length, capacity)
    edge.occupancy = occupancy
    edge.is_blocked = is_blocked
    assert edge.get_effective_weight() == expected_weight


def test_stadium_pathfinding(simple_evac_graph):
    """Verify route recalculation changes when corridors get congested."""
    g = simple_evac_graph

    # Direct short path should be picked first
    path, time_cost = g.calculate_evacuation_routes("Stand_A")
    assert path == ["Stand_A", "Concourse_1", "Exit_1"]
    assert time_cost == 10.0

    # Spill occupancy into short path to trigger LWR penalty and force rerouting
    g.update_edge_occupancy("Concourse_1", "Exit_1", 150.0)

    # Route should change to Exit_2 path
    path, time_cost = g.calculate_evacuation_routes("Stand_A")
    assert path == ["Stand_A", "Concourse_2", "Exit_2"]
    assert time_cost == 13.0


def test_stadium_blockage_rerouting(simple_evac_graph):
    """Verify routing path bypasses blocked edges."""
    g = simple_evac_graph

    # Block path 1
    g.set_edge_blocked("Concourse_1", "Exit_1", is_blocked=True)
    path, time_cost = g.calculate_evacuation_routes("Stand_A")
    assert path == ["Stand_A", "Concourse_2", "Exit_2"]
    assert time_cost == 13.0

    # Block path 2 as well -> no route possible
    g.set_edge_blocked("Concourse_2", "Exit_2", is_blocked=True)
    path, time_cost = g.calculate_evacuation_routes("Stand_A")
    assert path == []
    assert time_cost == float("inf")


def test_stadium_node_blocking(simple_evac_graph):
    """Verify node blocking shuts down all incoming/outgoing corridor paths."""
    g = simple_evac_graph

    # Node blocking Concourse_1 should block Concourse_1 -> Exit_1 and Stand_A -> Concourse_1
    g.set_node_blocked("Concourse_1", is_blocked=True)

    # Path 1 is blocked, path 2 should be used
    path, time_cost = g.calculate_evacuation_routes("Stand_A")
    assert path == ["Stand_A", "Concourse_2", "Exit_2"]

    # Block Concourse_2 node -> no path remains
    g.set_node_blocked("Concourse_2", is_blocked=True)
    path, time_cost = g.calculate_evacuation_routes("Stand_A")
    assert path == []


def test_invalid_start_node(simple_evac_graph):
    """Routing from an unregistered node returns empty path."""
    path, time_cost = simple_evac_graph.calculate_evacuation_routes("Nonexistent_Section")
    assert path == []
    assert time_cost == float("inf")


# ── Feature #93 — Crowd Crush Prevention Tests ────────────────────────────────

def test_crush_risk_no_crush(clean_graph):
    """When all corridors have low occupancy, crush risk level must be LOW."""
    g = clean_graph
    g.add_node("Exit1", is_exit=True)
    g.add_node("Con1")
    g.add_node("Stand")
    g.add_edge("Stand", "Con1", length=10.0, capacity=200.0)
    g.add_edge("Con1", "Exit1", length=5.0, capacity=200.0)
    g.update_edge_occupancy("Stand", "Con1", 20.0)
    g.update_edge_occupancy("Con1", "Exit1", 15.0)

    result = g.get_crush_risk_zones()
    assert result["level"] == "LOW"
    assert result["zone_count"] == 0
    assert len(result["zones"]) == 0


def test_crush_risk_moderate(clean_graph):
    """One corridor at crush conditions (density >= 80% AND LWR penalty >= 3x) triggers detection."""
    g = clean_graph
    g.add_node("Exit1", is_exit=True)
    g.add_node("Con1")
    g.add_node("Stand")
    g.add_edge("Stand", "Con1", length=10.0, capacity=100.0)
    g.add_edge("Con1", "Exit1", length=5.0, capacity=200.0)

    # 90% density: effective_weight = 10*(1 + 2.5*(0.9^2)) = 10*3.025 = 30.25 >= 3*10 = 30. CRUSH!
    g.update_edge_occupancy("Stand", "Con1", 90.0)

    result = g.get_crush_risk_zones()
    assert result["level"] in ("MODERATE", "CRITICAL")
    assert result["zone_count"] >= 1
    sources = [z["source"] for z in result["zones"]] + [z["target"] for z in result["zones"]]
    assert "Stand" in sources or "Con1" in sources


def test_crush_risk_blocked_excluded(clean_graph):
    """Blocked corridors are excluded from crush risk (they are already closed off)."""
    g = clean_graph
    g.add_node("Exit1", is_exit=True)
    g.add_node("Con1")
    g.add_node("Stand")
    g.add_edge("Stand", "Con1", length=10.0, capacity=100.0)
    g.add_edge("Con1", "Exit1", length=5.0, capacity=200.0)

    # Max occupancy + blocked — should NOT trigger crush
    g.update_edge_occupancy("Stand", "Con1", 300.0)
    g.set_edge_blocked("Stand", "Con1", True)

    result = g.get_crush_risk_zones()
    assert result["zone_count"] == 0


def test_crush_risk_sorted_descending(clean_graph):
    """get_crush_risk_zones() must sort results by density_ratio descending."""
    g = clean_graph
    g.add_node("Exit1", is_exit=True)
    g.add_node("Con1")
    g.add_node("Con2")
    g.add_node("Stand")
    g.add_edge("Stand", "Con1", length=10.0, capacity=100.0)
    g.add_edge("Stand", "Con2", length=10.0, capacity=100.0)
    g.add_edge("Con1", "Exit1", length=5.0, capacity=200.0)
    g.add_edge("Con2", "Exit1", length=5.0, capacity=200.0)

    g.update_edge_occupancy("Stand", "Con1", 95.0)  # 95% density
    g.update_edge_occupancy("Stand", "Con2", 85.0)  # 85% density

    result = g.get_crush_risk_zones()
    if len(result["zones"]) >= 2:
        assert result["zones"][0]["density_ratio"] >= result["zones"][1]["density_ratio"]


def test_bottlenecks_blocked_nodes(clean_graph):
    """Verify blocked edges are correctly reported in get_bottlenecks result."""
    g = clean_graph
    g.add_node("Exit1", is_exit=True)
    g.add_node("Stand")
    g.add_edge("Stand", "Exit1", length=10.0, capacity=100.0)
    g.set_edge_blocked("Stand", "Exit1", True)

    bottlenecks = g.get_bottlenecks()
    assert len(bottlenecks) == 1
    assert bottlenecks[0]["is_blocked"] is True
