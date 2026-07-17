from app.engine import StadiumGraph

def create_stadium_network() -> StadiumGraph:
    """
    Initializes an expanded 36-node stadium topology representing a modern
    FIFA-compliant stadium (e.g. MetLife/Azteca style) with detailed seating sections,
    wheelchair access points, split concourses, and multiple exit turnstiles.
    """
    g = StadiumGraph()
    
    # 1. Main Exit Gates (8 Exits)
    exit_gates = [
        "Gate_A1_North", "Gate_A2_North",
        "Gate_B1_East", "Gate_B2_East",
        "Gate_C1_South", "Gate_C2_South",
        "Gate_D1_West", "Gate_D2_West"
    ]
    for gate in exit_gates:
        g.add_node(gate, is_exit=True)
        
    # 2. Concourse Nodes (8 Ring Corridor sections)
    concourses = [
        "Concourse_North_1", "Concourse_North_2",
        "Concourse_East_1", "Concourse_East_2",
        "Concourse_South_1", "Concourse_South_2",
        "Concourse_West_1", "Concourse_West_2"
    ]
    for con in concourses:
        g.add_node(con)
        
    # 3. Seating bowl Stand Sections (16 sections, 2 VIP Suites, 2 Wheelchair zones = 20 stands)
    # Seating Bowl Sections (Lower & Upper)
    lower_stands = [f"Section_{101 + i}_Lower" for i in range(8)]
    upper_stands = [f"Section_{201 + i}_Upper" for i in range(8)]
    vip_stands = ["VIP_Suite_North", "VIP_Suite_South"]
    accessible_stands = ["Wheelchair_Zone_East", "Wheelchair_Zone_West"]
    
    for stand in lower_stands + upper_stands + vip_stands + accessible_stands:
        g.add_node(stand)

    # --- Edge Connections (Travel times in seconds, Egress capacities in people/sec) ---
    
    # Connect lower bowl seating (nominal egress speed, large capacity stairways)
    # North Stands connect to Concourse North
    g.add_edge("Section_101_Lower", "Concourse_North_1", length=6.0, capacity=150.0)
    g.add_edge("Section_102_Lower", "Concourse_North_2", length=6.0, capacity=150.0)
    # East Stands connect to Concourse East
    g.add_edge("Section_103_Lower", "Concourse_East_1", length=6.0, capacity=150.0)
    g.add_edge("Section_104_Lower", "Concourse_East_2", length=6.0, capacity=150.0)
    # South Stands connect to Concourse South
    g.add_edge("Section_105_Lower", "Concourse_South_1", length=6.0, capacity=150.0)
    g.add_edge("Section_106_Lower", "Concourse_South_2", length=6.0, capacity=150.0)
    # West Stands connect to Concourse West
    g.add_edge("Section_107_Lower", "Concourse_West_1", length=6.0, capacity=150.0)
    g.add_edge("Section_108_Lower", "Concourse_West_2", length=6.0, capacity=150.0)
    
    # Connect upper bowl seating (longer stair/escalator egress times, lower capacities)
    g.add_edge("Section_201_Upper", "Concourse_North_1", length=20.0, capacity=80.0)
    g.add_edge("Section_202_Upper", "Concourse_North_2", length=20.0, capacity=80.0)
    g.add_edge("Section_203_Upper", "Concourse_East_1", length=20.0, capacity=80.0)
    g.add_edge("Section_204_Upper", "Concourse_East_2", length=20.0, capacity=80.0)
    g.add_edge("Section_205_Upper", "Concourse_South_1", length=20.0, capacity=80.0)
    g.add_edge("Section_206_Upper", "Concourse_South_2", length=20.0, capacity=80.0)
    g.add_edge("Section_207_Upper", "Concourse_West_1", length=20.0, capacity=80.0)
    g.add_edge("Section_208_Upper", "Concourse_West_2", length=20.0, capacity=80.0)
    
    # VIP and Wheelchair Accessible Egress paths
    # Wheelchair zones use ramp connections (long length but wheelchair accessible, moderate capacity)
    g.add_edge("Wheelchair_Zone_East", "Concourse_East_1", length=14.0, capacity=100.0)
    g.add_edge("Wheelchair_Zone_West", "Concourse_West_2", length=14.0, capacity=100.0)
    # VIP suites connect directly to executive escape exits
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

# Preloaded scenarios scaled to the 36-node graph layout
SCENARIOS = {
    "normal": {
        "title": "Standard Egress",
        "description": "Nominal post-match outflow. Stable crowd levels across all concourses and exit stairwells.",
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
        }
    },
    
    "bottleneck": {
        "title": "East Plaza Turnstile Saturation",
        "description": "Scanner hardware crash at East Exit Gates (B1 & B2). Crowd densities spike on the East Concourse, forcing rerouting to Gate A2 (North) and Gate C1 (South).",
        "incident": "Egress hardware crash at East Plaza",
        "blocked_edges": [],
        "blocked_nodes": [],
        "occupancies": {
            ("Section_103_Lower", "Concourse_East_1"): 85.0,
            ("Section_104_Lower", "Concourse_East_2"): 95.0,
            ("Section_203_Upper", "Concourse_East_1"): 60.0,
            ("Section_204_Upper", "Concourse_East_2"): 65.0,
            ("Wheelchair_Zone_East", "Concourse_East_1"): 45.0,
            # Gate B links saturated
            ("Concourse_East_1", "Gate_B1_East"): 290.0,
            ("Concourse_East_2", "Gate_B2_East"): 280.0,
            # Concourse ring handles overflow
            ("Concourse_East_1", "Concourse_East_2"): 120.0,
            ("Concourse_North_2", "Concourse_East_1"): 90.0,
            ("Concourse_East_2", "Concourse_South_1"): 110.0,
            ("Concourse_North_1", "Gate_A1_North"): 35.0,
            ("Concourse_South_2", "Gate_C2_South"): 38.0,
        }
    },
    
    "emergency": {
        "title": "Concourse East Fire & Gate B Lockout",
        "description": "Fire alert triggered in East Concourse Section 1. East Gates are locked out. Dynamic pathfinder immediately redirects all East Stands and Wheelchair users to North and South exits.",
        "incident": "Active Hazard: Fire in East Concourse",
        "blocked_nodes": ["Concourse_East_1"],
        "blocked_edges": [
            ("Concourse_East_1", "Gate_B1_East"),
            ("Concourse_East_2", "Gate_B2_East"),
            ("Concourse_North_2", "Concourse_East_1"),
            ("Concourse_East_1", "Concourse_East_2")
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
        }
    }
}
