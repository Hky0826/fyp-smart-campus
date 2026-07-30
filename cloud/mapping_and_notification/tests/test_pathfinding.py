from cloud.mapping_and_notification.mapping.instructions import build_instructions, turn_direction
from cloud.mapping_and_notification.mapping.pathfinding import GraphEdge, GraphNode, NoRouteError, find_path


def test_astar_filters_rbac_and_keeps_stable_edges():
    nodes = [GraphNode(1, 1, 0, 0, "Start"), GraphNode(2, 1, 10, 0, "Restricted", allowed_roles=frozenset({"STAFF"})), GraphNode(3, 1, 20, 0, "End")]
    edges = [GraphEdge(11, 1, 2, 1), GraphEdge(12, 2, 3, 1)]
    try:
        find_path(nodes, edges, 1, 3, roles={"STUDENT"})
    except NoRouteError:
        pass
    else:
        raise AssertionError("restricted route should not be available")
    route = find_path(nodes, edges, 1, 3, roles={"STAFF"})
    assert [node.node_id for node in route.nodes] == [1, 2, 3]
    assert [edge.edge_id for edge in route.edges] == [11, 12]


def test_instruction_geometry_uses_screen_space_turns():
    assert turn_direction((1, 0), (0, 1)) == "right"
    nodes = [GraphNode(1, 1, 0, 0, "Entrance"), GraphNode(2, 1, 10, 0, "Corridor", node_type="CORRIDOR"), GraphNode(3, 1, 10, 10, "Office")]
    instructions = build_instructions(nodes, [GraphEdge(1, 1, 2, 10), GraphEdge(2, 2, 3, 10)])
    assert instructions[-1]["action"] == "arrive"
    assert any(step["action"] == "right" for step in instructions)
