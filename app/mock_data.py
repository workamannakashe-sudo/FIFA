"""
app/mock_data.py
~~~~~~~~~~~~~~~~
Mock data and topologies for SafePass 2026 stadium simulations.

Contains:
1. `create_stadium_network()`: Build a 36-node graph model of a modern stadium
   egress path.
2. `SCENARIOS`: High-density crowd scenarios to evaluate routing path updates.
"""

from __future__ import annotations

from typing import Dict, List

from app.engine import StadiumGraph

__all__ = ["create_stadium_network", "SCENARIOS"]


def create_stadium_network() -> StadiumGraph:
    """
    Initialize an expanded 36-node stadium topology for simulation.

    Models a standard modern host venue with:
    - 8 outer exit gates.
    - 8 inner concourse connection rings.
    - 16 stand segments.
    - 2 VIP suites.
    - 2 wheelchair platforms.

    Returns
    -------
    StadiumGraph
        The constructed stadium graph structure.
    """
    g = StadiumGraph()

    # 1. Main Exit Gates (8 Exits)
    exit_gates: List[str] = [
        "Gate_A1_North",
        "Gate_A2_North",
        "Gate_B1_East",
        "Gate_B2_East",
        "Gate_C1_South",
        "Gate_C2_South",
        "Gate_D1_West",
        "Gate_D2_West",
    ]
    for gate in exit_gates:
        g.add_node(gate, is_exit=True)

    # 2. Concourse Nodes (8 Ring Corridor sections)
    concourses: List[str] = [
        "Concourse_North_1",
        "Concourse_North_2",
        "Concourse_East_1",
        "Concourse_East_2",
        "Concourse_South_1",
        "Concourse_South_2",
        "Concourse_West_1",
        "Concourse_West_2",
    ]
    for con in concourses:
        g.add_node(con)

    # 3. Seating bowl Stand Sections (20 stands total)
    lower_stands: List[str] = [f"Section_{101 + i}_Lower" for i in range(8)]
    upper_stands: List[str] = [f"Section_{201 + i}_Upper" for i in range(8)]
    vip_stands: List[str] = ["VIP_Suite_North", "VIP_Suite_South"]
    accessible_stands: List[str] = ["Wheelchair_Zone_East", "Wheelchair_Zone_West"]

    for stand in lower_stands + upper_stands + vip_stands + accessible_stands:
        g.add_node(stand)

    # --- Edge Connections (Travel times in seconds, capacities in people/sec) ---

    # Connect lower bowl seating (large capacity stairways)
    g.add_edge("Section_101_Lower", "Concourse_North_1", length=6.0, capacity=150.0)
    g.add_edge("Section_102_Lower", "Concourse_North_2", length=6.0, capacity=150.0)
    g.add_edge("Section_103_Lower", "Concourse_East_1", length=6.0, capacity=150.0)
    g.add_edge("Section_104_Lower", "Concourse_East_2", length=6.0, capacity=150.0)
    g.add_edge("Section_105_Lower", "Concourse_South_1", length=6.0, capacity=150.0)
    g.add_edge("Section_106_Lower", "Concourse_South_2", length=6.0, capacity=150.0)
    g.add_edge("Section_107_Lower", "Concourse_West_1", length=6.0, capacity=150.0)
    g.add_edge("Section_108_Lower", "Concourse_West_2", length=6.0, capacity=150.0)

    # Connect upper bowl seating (longer stairways, lower capacity)
    g.add_edge("Section_201_Upper", "Concourse_North_1", length=20.0, capacity=80.0)
    g.add_edge("Section_202_Upper", "Concourse_North_2", length=20.0, capacity=80.0)
    g.add_edge("Section_203_Upper", "Concourse_East_1", length=20.0, capacity=80.0)
    g.add_edge("Section_204_Upper", "Concourse_East_2", length=20.0, capacity=80.0)
    g.add_edge("Section_205_Upper", "Concourse_South_1", length=20.0, capacity=80.0)
    g.add_edge("Section_206_Upper", "Concourse_South_2", length=20.0, capacity=80.0)
    g.add_edge("Section_207_Upper", "Concourse_West_1", length=20.0, capacity=80.0)
    g.add_edge("Section_208_Upper", "Concourse_West_2", length=20.0, capacity=80.0)

    # VIP and Wheelchair ramp pathways
    g.add_edge("Wheelchair_Zone_East", "Concourse_East_1", length=14.0, capacity=100.0)
    g.add_edge("Wheelchair_Zone_West", "Concourse_West_2", length=14.0, capacity=100.0)
    g.add_edge("VIP_Suite_North", "Concourse_North_1", length=4.0, capacity=60.0)
    g.add_edge("VIP_Suite_South", "Concourse_South_2", length=4.0, capacity=60.0)

    # Connect Concourse Ring together (horizontal flow)
    g.add_edge("Concourse_North_1", "Concourse_North_2", length=10.0, capacity=200.0)
    g.add_edge("Concourse_North_2", "Concourse_East_1", length=10.0, capacity=200.0)
    g.add_edge("Concourse_East_1", "Concourse_East_2", length=10.0, capacity=200.0)
    g.add_edge("Concourse_East_2", "Concourse_South_1", length=10.0, capacity=200.0)
    g.add_edge("Concourse_South_1", "Concourse_South_2", length=10.0, capacity=200.0)
    g.add_edge("Concourse_South_2", "Concourse_West_1", length=10.0, capacity=200.0)
    g.add_edge("Concourse_West_1", "Concourse_West_2", length=10.0, capacity=200.0)
    g.add_edge("Concourse_West_2", "Concourse_North_1", length=10.0, capacity=200.0)

    # Connect Concourses to Exit Gates
    g.add_edge("Concourse_North_1", "Gate_A1_North", length=5.0, capacity=110.0)
    g.add_edge("Concourse_North_2", "Gate_A2_North", length=5.0, capacity=110.0)
    g.add_edge("Concourse_East_1", "Gate_B1_East", length=5.0, capacity=110.0)
    g.add_edge("Concourse_East_2", "Gate_B2_East", length=5.0, capacity=110.0)
    g.add_edge("Concourse_South_1", "Gate_C1_South", length=5.0, capacity=110.0)
    g.add_edge("Concourse_South_2", "Gate_C2_South", length=5.0, capacity=110.0)
    g.add_edge("Concourse_West_1", "Gate_D1_West", length=5.0, capacity=110.0)
    g.add_edge("Concourse_West_2", "Gate_D2_West", length=5.0, capacity=110.0)

    return g


# Preloaded crowd profiles mapped to the topology layout
SCENARIOS: Dict[str, Dict] = {
    "normal": {
        "title": "Standard Egress",
        "description": (
            "Nominal post-match outflow. Stable crowd levels across all concourses "
            "and exit stairwells."
        ),
        "incident": None,
        "blocked_edges": [],
        "blocked_nodes": [],
        "occupancies": {
            ("Section_101_Lower", "Concourse_North_1"): 12.0,
            ("Section_102_Lower", "Concourse_North_2"): 10.0,
            ("Section_103_Lower", "Concourse_East_1"): 15.0,
            ("Section_104_Lower", "Concourse_East_2"): 14.0,
            ("Section_105_Lower", "Concourse_South_1"): 11.0,
            ("Section_106_Lower", "Concourse_South_2"): 12.0,
            ("Section_107_Lower", "Concourse_West_1"): 10.0,
            ("Section_108_Lower", "Concourse_West_2"): 13.0,
            ("Concourse_North_1", "Gate_A1_North"): 15.0,
            ("Concourse_North_2", "Gate_A2_North"): 14.0,
            ("Concourse_East_1", "Gate_B1_East"): 18.0,
            ("Concourse_East_2", "Gate_B2_East"): 19.0,
            ("Concourse_South_1", "Gate_C1_South"): 16.0,
            ("Concourse_South_2", "Gate_C2_South"): 15.0,
            ("Concourse_West_1", "Gate_D1_West"): 14.0,
            ("Concourse_West_2", "Gate_D2_West"): 16.0,
        },
    },
    "bottleneck": {
        "title": "East Plaza Turnstile Saturation",
        "description": (
            "Scanner hardware crash at East Exit Gates (B1 & B2). Crowd densities "
            "spike on the East Concourse, forcing rerouting to Gate A2 (North) and "
            "Gate C1 (South)."
        ),
        "incident": "Egress hardware crash at East Plaza",
        "blocked_edges": [],
        "blocked_nodes": [],
        "occupancies": {
            ("Section_103_Lower", "Concourse_East_1"): 85.0,
            ("Section_104_Lower", "Concourse_East_2"): 95.0,
            ("Section_203_Upper", "Concourse_East_1"): 60.0,
            ("Section_204_Upper", "Concourse_East_2"): 65.0,
            ("Wheelchair_Zone_East", "Concourse_East_1"): 45.0,
            ("Concourse_East_1", "Gate_B1_East"): 290.0,
            ("Concourse_East_2", "Gate_B2_East"): 280.0,
            ("Concourse_East_1", "Concourse_East_2"): 120.0,
            ("Concourse_North_2", "Concourse_East_1"): 90.0,
            ("Concourse_East_2", "Concourse_South_1"): 110.0,
            ("Concourse_North_1", "Gate_A1_North"): 35.0,
            ("Concourse_South_2", "Gate_C2_South"): 38.0,
        },
    },
    "emergency": {
        "title": "Concourse East Fire & Gate B Lockout",
        "description": (
            "Fire alert triggered in East Concourse Section 1. East Gates are locked "
            "out. Dynamic pathfinder immediately redirects all East Stands and "
            "Wheelchair users to North and South exits."
        ),
        "incident": "Active Hazard: Fire in East Concourse",
        "blocked_nodes": ["Concourse_East_1"],
        "blocked_edges": [
            ("Concourse_East_1", "Gate_B1_East"),
            ("Concourse_East_2", "Gate_B2_East"),
            ("Concourse_North_2", "Concourse_East_1"),
            ("Concourse_East_1", "Concourse_East_2"),
        ],
        "occupancies": {
            ("Section_101_Lower", "Concourse_North_1"): 20.0,
            ("Section_105_Lower", "Concourse_South_1"): 25.0,
            ("Concourse_North_1", "Gate_A1_North"): 90.0,
            ("Concourse_North_2", "Gate_A2_North"): 95.0,
            ("Concourse_South_1", "Gate_C1_South"): 95.0,
            ("Concourse_South_2", "Gate_C2_South"): 90.0,
            ("Concourse_West_1", "Gate_D1_West"): 40.0,
            ("Concourse_West_2", "Gate_D2_West"): 40.0,
            ("Concourse_South_2", "Concourse_West_1"): 50.0,
            ("Concourse_West_2", "Concourse_North_1"): 45.0,
        },
    },
}
