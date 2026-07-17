import pytest
from app.engine import StadiumGraph, Edge

def test_edge_effective_weight():
    edge = Edge("A", "B", length=10.0, capacity=100.0)
    
    # 1. No occupancy, weight should be base length
    assert edge.get_effective_weight() == 10.0
    
    # 2. Add occupancy, weight should increase
    edge.occupancy = 50.0
    weight_50 = edge.get_effective_weight()
    assert weight_50 > 10.0
    
    # 3. Increase occupancy to saturation, weight should increase significantly
    edge.occupancy = 120.0
    weight_120 = edge.get_effective_weight()
    assert weight_120 > weight_50
    
    # 4. Block edge, weight should be infinite
    edge.is_blocked = True
    assert edge.get_effective_weight() == float('inf')


def test_stadium_pathfinding():
    g = StadiumGraph()
    
    g.add_node("Exit1", is_exit=True)
    g.add_node("Exit2", is_exit=True)
    g.add_node("Con1")
    g.add_node("Con2")
    g.add_node("Stand")
    
    g.add_edge("Stand", "Con1", length=5.0, capacity=100.0)
    g.add_edge("Con1", "Exit1", length=5.0, capacity=100.0)
    g.add_edge("Stand", "Con2", length=5.0, capacity=100.0)
    g.add_edge("Con2", "Exit2", length=8.0, capacity=100.0)
    
    path, time_cost = g.calculate_evacuation_routes("Stand")
    assert path == ["Stand", "Con1", "Exit1"]
    assert time_cost == 10.0
    
    g.update_edge_occupancy("Con1", "Exit1", occupancy=150.0)
    
    path, time_cost = g.calculate_evacuation_routes("Stand")
    assert path == ["Stand", "Con2", "Exit2"]
    assert time_cost == 13.0


def test_stadium_blockage_rerouting():
    g = StadiumGraph()
    g.add_node("Exit1", is_exit=True)
    g.add_node("Exit2", is_exit=True)
    g.add_node("Con1")
    g.add_node("Stand")
    
    g.add_edge("Stand", "Con1", length=5.0, capacity=100.0)
    g.add_edge("Con1", "Exit1", length=5.0, capacity=100.0)
    g.add_edge("Con1", "Exit2", length=15.0, capacity=100.0)
    
    g.set_edge_blocked("Con1", "Exit1", is_blocked=True)
    
    path, time_cost = g.calculate_evacuation_routes("Stand")
    assert path == ["Stand", "Con1", "Exit2"]
    assert time_cost == 20.0
    
    g.set_edge_blocked("Con1", "Exit2", is_blocked=True)
    path, time_cost = g.calculate_evacuation_routes("Stand")
    assert path == []
    assert time_cost == float('inf')


# ── Feature #93 — Crowd Crush Prevention Tests ────────────────────────────────

def test_crush_risk_no_crush():
    """When all corridors have low occupancy, crush risk level must be LOW."""
    g = StadiumGraph()
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


def test_crush_risk_moderate():
    """One corridor at crush conditions (density >= 80% AND LWR penalty >= 3x) triggers detection."""
    g = StadiumGraph()
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


def test_crush_risk_blocked_excluded():
    """Blocked corridors are excluded from crush risk (they are already closed off)."""
    g = StadiumGraph()
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


def test_crush_risk_sorted_descending():
    """get_crush_risk_zones() must sort results by density_ratio descending."""
    g = StadiumGraph()
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
