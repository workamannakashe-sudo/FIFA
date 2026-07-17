import heapq
from typing import Dict, List, Tuple, Set, Optional

class Edge:
    def __init__(self, source: str, target: str, length: float, capacity: float):
        self.source = source
        self.target = target
        self.length = length          # Base travel time / distance in seconds
        self.capacity = capacity      # Maximum flow capacity (people per second)
        self.occupancy = 0.0          # Current number of people on this edge
        self.is_blocked = False       # Set to True in emergencies

    def get_effective_weight(self) -> float:
        if self.is_blocked:
            return float('inf')
        
        # Congestion factor: Lighthill-Whitham-Richards crowd dynamics flow relation model
        # As occupancy approaches capacity, effective travel time increases quadratically.
        congestion_ratio = min(self.occupancy / max(self.capacity, 1.0), 3.0)
        # Weight formula: base_length * (1 + alpha * (occupancy / capacity) ^ beta)
        alpha = 2.5
        beta = 2
        effective_weight = self.length * (1.0 + alpha * (congestion_ratio ** beta))
        return effective_weight


class StadiumGraph:
    def __init__(self):
        self.nodes: Set[str] = set()
        self.exits: Set[str] = set()
        # Adjacency list: node_name -> dict of target_name -> Edge
        self.adj: Dict[str, Dict[str, Edge]] = {}

    def add_node(self, name: str, is_exit: bool = False):
        self.nodes.add(name)
        if is_exit:
            self.exits.add(name)
        if name not in self.adj:
            self.adj[name] = {}

    def add_edge(self, source: str, target: str, length: float, capacity: float, bidirectional: bool = True):
        self.add_node(source)
        self.add_node(target)
        
        edge = Edge(source, target, length, capacity)
        self.adj[source][target] = edge
        
        if bidirectional:
            rev_edge = Edge(target, source, length, capacity)
            self.adj[target][source] = rev_edge

    def set_edge_blocked(self, source: str, target: str, is_blocked: bool, bidirectional: bool = True):
        if source in self.adj and target in self.adj[source]:
            self.adj[source][target].is_blocked = is_blocked
        if bidirectional and target in self.adj and source in self.adj[target]:
            self.adj[target][source].is_blocked = is_blocked

    def set_node_blocked(self, node: str, is_blocked: bool):
        """Block all edges connected to/from this node in case of an localized hazard."""
        if node in self.adj:
            for target in self.adj[node]:
                self.adj[node][target].is_blocked = is_blocked
        for src in self.adj:
            if node in self.adj[src]:
                self.adj[src][node].is_blocked = is_blocked

    def update_edge_occupancy(self, source: str, target: str, occupancy: float, bidirectional: bool = True):
        if source in self.adj and target in self.adj[source]:
            self.adj[source][target].occupancy = max(0.0, occupancy)
        if bidirectional and target in self.adj and source in self.adj[target]:
            self.adj[target][source].occupancy = max(0.0, occupancy)

    def reset_congestion(self):
        for src in self.adj:
            for target in self.adj[src]:
                self.adj[src][target].occupancy = 0.0
                self.adj[src][target].is_blocked = False

    def calculate_evacuation_routes(self, start_node: str) -> Tuple[List[str], float]:
        """
        Uses a modified Dijkstra's algorithm to calculate the optimal path from
        start_node to ANY available exit gate, taking congestion weights into account.
        
        Returns:
            Tuple[List[str], float]: (path of nodes, total travel time/weight)
        """
        if start_node not in self.nodes:
            return [], float('inf')
        
        # Dijkstra state
        distances = {node: float('inf') for node in self.nodes}
        distances[start_node] = 0.0
        
        # Predecessors to reconstruct path
        predecessors = {node: None for node in self.nodes}
        
        # Priority queue stores (distance, node)
        pq = [(0.0, start_node)]
        visited = set()
        
        nearest_exit: Optional[str] = None
        min_exit_dist = float('inf')
        
        while pq:
            curr_dist, curr_node = heapq.heappop(pq)
            
            if curr_node in visited:
                continue
            visited.add(curr_node)
            
            # If we reached an exit, check if it's the closest/best
            if curr_node in self.exits:
                if curr_dist < min_exit_dist:
                    min_exit_dist = curr_dist
                    nearest_exit = curr_node
                    # Since we want the absolute shortest path to ANY exit,
                    # and Dijkstra processes in increasing distance, the first exit
                    # we pop is guaranteed to be the optimal path.
                    break
            
            # Relax neighbors
            neighbors = self.adj.get(curr_node, {})
            for target, edge in neighbors.items():
                if target in visited:
                    continue
                
                weight = edge.get_effective_weight()
                if weight == float('inf'):
                    continue
                    
                new_dist = curr_dist + weight
                if new_dist < distances[target]:
                    distances[target] = new_dist
                    predecessors[target] = curr_node
                    heapq.heappush(pq, (new_dist, target))
                    
        if nearest_exit is None:
            return [], float('inf')
            
        # Reconstruct path
        path = []
        curr = nearest_exit
        while curr is not None:
            path.append(curr)
            curr = predecessors[curr]
        path.reverse()
        
        return path, min_exit_dist

    def get_crush_risk_zones(self) -> Dict:
        """
        Crowd Crush Prevention Algorithm (Feature #93).
        Identifies corridors exhibiting crush conditions by combining:
          - Density ratio >= 0.80 (>80% capacity — Fruin Level of Service E/F boundary)
          - AND effective_weight >= 3x base_length (LWR model quadratic penalty threshold)
        
        Returns a severity dict: {level: LOW|MODERATE|CRITICAL, zones: [...], summary: str}
        """
        crush_zones = []
        seen = set()
        
        for src in self.adj:
            for tgt, edge in self.adj[src].items():
                edge_id = tuple(sorted([src, tgt]))
                if edge_id in seen or edge.is_blocked:
                    continue
                seen.add(edge_id)
                
                if edge.capacity <= 0:
                    continue
                
                density_ratio = edge.occupancy / edge.capacity
                effective_w = edge.get_effective_weight()
                
                # Crush condition: high density AND severe congestion penalty
                if density_ratio >= 0.80 and effective_w >= (edge.length * 3.0):
                    crush_zones.append({
                        "source": src,
                        "target": tgt,
                        "density_ratio": round(density_ratio, 3),
                        "effective_weight": round(effective_w, 2),
                        "base_length": edge.length,
                        "penalty_multiplier": round(effective_w / max(edge.length, 1), 2),
                        "occupancy": edge.occupancy,
                        "capacity": edge.capacity,
                    })
        
        # Sort by severity (highest density first)
        crush_zones.sort(key=lambda z: z["density_ratio"], reverse=True)
        
        # Determine overall risk level
        if len(crush_zones) == 0:
            level = "LOW"
            summary = "No crush-risk corridors detected. Crowd flow within safe parameters."
        elif len(crush_zones) <= 2:
            level = "MODERATE"
            summary = f"{len(crush_zones)} corridor(s) approaching crush density. Monitor and prepare rerouting."
        else:
            level = "CRITICAL"
            summary = f"CRUSH ALERT: {len(crush_zones)} corridors at dangerous density. Immediate intervention required."
        
        return {
            "level": level,
            "zone_count": len(crush_zones),
            "zones": crush_zones,
            "summary": summary
        }

    def get_bottlenecks(self, threshold: float = 1.2) -> List[Dict]:
        """
        Identify edges where occupancy/capacity exceeds threshold.
        """
        bottlenecks = []
        seen = set()
        for src in self.adj:
            for tgt, edge in self.adj[src].items():
                edge_id = tuple(sorted([src, tgt]))
                if edge_id in seen:
                    continue
                seen.add(edge_id)
                
                if edge.capacity > 0:
                    ratio = edge.occupancy / edge.capacity
                    if ratio >= threshold or edge.is_blocked:
                        bottlenecks.append({
                            "source": src,
                            "target": tgt,
                            "occupancy": edge.occupancy,
                            "capacity": edge.capacity,
                            "ratio": ratio,
                            "is_blocked": edge.is_blocked
                        })
        return bottlenecks
